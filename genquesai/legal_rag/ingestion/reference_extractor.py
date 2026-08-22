"""Reference Extractor — bóc quan hệ Căn cứ/Sửa đổi/Thay thế từ TEXT (regex nền + LLM
tuỳ chọn). Quy tắc đầy đủ + lý do: xem `../rule.md`. Tóm tắt:

- REPLACES/AMENDS: đọc TIÊU ĐỀ + đoạn "Hiệu lực thi hành"/"Điều khoản thi hành" CUỐI
  văn bản (§3.1 — câu tuyên bố thay thế/sửa đổi rất hay nằm ở đây, không phải tiêu
  đề, vd "Thông tư này có hiệu lực... và thay thế Thông tư số X..."). Cả hai đều neo
  theo ĐỘNG TỪ (không neo theo "có số hiệu ở đâu đó" trong toàn văn — bẫy đã biết:
  nhầm câu "Căn cứ Nghị định X..." thành AMENDS).
- GUIDED_BY: đọc đoạn "Căn cứ..." (preamble, trước "Điều 1").
- REPLACES/AMENDS -> da_duyet=false (qua người duyệt, ảnh hưởng domino hiệu lực).
  GUIDED_BY -> da_duyet=true (rủi ro thấp, không đổi hiệu lực ai).
- LLM (tuỳ chọn, tham số `llm`): chỉ chạy cho VB có từ khoá sửa/thay/bãi bỏ ở tiêu đề;
  vá lỗi OCR số hiệu + phân loại đúng hơn regex khi câu phức tạp. Hợp nhất: GIỮ
  GUIDED_BY từ regex, THAY AMENDS/REPLACES bằng kết quả LLM.

Phần thuần (`extract_*`) tách khỏi phần chạm DB (`apply_references`,
`extract_corpus_references`) để test không cần Neo4j.
"""
from __future__ import annotations
import json
import re
import time
from pathlib import Path

from selectolax.parser import HTMLParser

from ..graph.client import Neo4jClient

# Số hiệu VBQPPL tổng quát — bắt MỌI loại (kể cả QĐ-UBND/NQ-HĐND cấp tỉnh), chịu
# khoảng trắng lệch do OCR quanh dấu '/'.
SOHIEU_RE = re.compile(r"\d+\s*/\s*\d{4}\s*/\s*[A-ZĐ0-9]+(?:-[A-ZĐ0-9]+)*", re.IGNORECASE)

# Neo theo ĐỘNG TỪ (rule.md §3) — SUA xét trước BAIBO/"thay thế" khi lẫn cả hai
# (bảo thủ hơn: coi là sửa từng phần thay vì thay thế toàn bộ).
#
# "thay thế" và "bãi bỏ/hủy bỏ" TÁCH RIÊNG khỏi SUA, xét NGỮ CẢNH (rule.md §3.2,
# phát hiện 2026-08-22 — 2 ca thật):
#   - 58/2015/TTLT-BCT-BKHCN: "thay thế Thông tư số X" (không "một số điều") = thay
#     TOÀN BỘ -> REPLACES, khớp referenceType=12 thật.
#   - 06/2016/TT-BKHCN: "bãi bỏ NỘI DUNG quy định liên quan đến... quy định TẠI
#     Quyết định số 32/2007/QĐ-BKHCN" = chỉ bãi bỏ 1 PHẦN NỘI DUNG nằm TRONG VB khác
#     (không phải toàn bộ VB đó) -> AMENDS, khớp referenceType=1 + LLM (không phải
#     REPLACES như quy tắc "bãi bỏ = luôn REPLACES" ngây thơ ban đầu).
# Cả hai đều dùng chung 1 luật: đi kèm cụm chỉ TỪNG PHẦN (_TUNG_PHAN) trong ~60 ký
# tự sau động từ -> AMENDS; không kèm -> REPLACES (nhắm thẳng toàn bộ văn bản đích).
SUA = ("sửa đổi", "bổ sung", "điều chỉnh", "dừng thực hiện", "đình chỉ thi hành")
_TUNG_PHAN = re.compile(
    r"một\s+số\s+(điều|khoản|điểm)|nội\s+dung|quy\s+định\s+li[êe]n\s+quan", re.IGNORECASE)
_THAY_THE_RE = re.compile(r"thay\s+thế", re.IGNORECASE)
_BAIBO_RE = re.compile(r"bãi\s+bỏ|h[uủ]y\s+bỏ|huỷ\s+bỏ", re.IGNORECASE)


def html_to_text(html: str) -> str:
    """`toanvan.html` -> text thuần, dùng cho mọi hàm dò quan hệ dựa trên regex.

    KHÔNG dùng `re.sub(r"<[^>]+>", " ", html)` (bug thật 2026-08-22): một số VB có
    thẻ inline (`<em>`, `<b>`...) chèn GIỮA TỪNG KÝ TỰ của số hiệu (HTML gốc tô đậm/
    nghiêng riêng từng ký tự, vd `"...QH</em><em>1</em><em>3..."`) — thay tag bằng
    khoảng trắng làm `"QH13"` vỡ thành `"QH 1 3"`, `SOHIEU_RE` chỉ bắt được `"QH"`,
    mất `"13"`. `HTMLParser.text()` (KHÔNG truyền `separator`) nối các text-node liền
    theo đúng DOM, giữ nguyên whitespace/newline THẬT đã có sẵn trong HTML nguồn —
    đã kiểm tra trên dữ liệu thật: không gây dính chữ giữa các `<p>` (HTML gốc format
    có xuống dòng thật giữa đoạn, không phải HTML minify)."""
    return HTMLParser(html).text()


def _norm_sh(s: str) -> str:
    return re.sub(r"\s*/\s*", "/", s or "").strip()


def _sohieu_in(s: str) -> list[str]:
    return list(dict.fromkeys(_norm_sh(x) for x in SOHIEU_RE.findall(_norm_sh(s))))


_SUA_RE = re.compile("|".join(re.escape(k) for k in SUA))


def _phan_loai_dong_tu(low: str) -> tuple[str, str] | None:
    """Phân loại REPLACES/AMENDS theo động từ (rule.md §3, §3.2, §3.4). `low` = text
    đã lowercase. Trả (loai, edge) hoặc None nếu không có động từ nào khớp.

    ĐỘNG TỪ XUẤT HIỆN SỚM NHẤT trong câu quyết định loại quan hệ cho CẢ CÂU (rule.md
    §3.4, phát hiện 2026-08-22) — KHÔNG phải "SUA có mặt bất kỳ đâu luôn thắng" (thiết
    kế cũ, sai). Câu liệt kê nhiều VB bị bãi bỏ/thay thế thường có 1 VB được MÔ TẢ
    bằng mệnh đề phụ chứa "sửa đổi, bổ sung [VB khác]" ở GIỮA/CUỐI câu (mô tả quan hệ
    LỊCH SỬ giữa 2 VB đó, không phải hành động của VB hiện tại) — động từ mô tả đó
    KHÔNG được áp cho cả câu, chỉ động từ CHÍNH (luôn ở đầu câu theo mẫu hành văn luật
    VN) mới quyết định.

    "thay thế"/"bãi bỏ" (không phải SUA) còn xét thêm ngữ cảnh riêng tại đúng vị trí
    xuất hiện: kèm cụm TỪNG PHẦN (_TUNG_PHAN) trong ~60 ký tự sau -> AMENDS; không
    kèm -> REPLACES."""
    ung_vien: list[tuple[int, str, str]] = []
    m = _SUA_RE.search(low)
    if m:
        ung_vien.append((m.start(), "SuaDoi", "AMENDS"))
    for m in list(_BAIBO_RE.finditer(low)) + list(_THAY_THE_RE.finditer(low)):
        if _TUNG_PHAN.search(low[m.end():m.end() + 60]):
            ung_vien.append((m.start(), "SuaDoi", "AMENDS"))
        else:
            ung_vien.append((m.start(), "ThayThe", "REPLACES"))
    if not ung_vien:
        return None
    ung_vien.sort(key=lambda x: x[0])
    _, loai, edge = ung_vien[0]
    return loai, edge


def _quan_he_theo_cau(doan: str, own_so_hieu: str | None = None,
                      exclude: set[str] | None = None) -> list[tuple[str, str, str]]:
    """Tách `doan` thành từng CÂU (theo dấu . hoặc ;), phân loại + trích số hiệu
    RIÊNG cho từng câu — KHÔNG gộp động từ của câu này với số hiệu của câu khác
    (rule.md §3.1, phát hiện 2026-08-22: câu boilerplate "văn bản viện dẫn được sửa
    đổi... thì theo văn bản mới" không nói về số hiệu cụ thể nào, nếu quét cả đoạn
    thì động từ "sửa đổi" ở câu đó bị gán nhầm cho số hiệu ở câu KHÁC)."""
    own = _norm_sh(own_so_hieu) if own_so_hieu else None
    used = set(exclude or set())
    if own:
        used.add(own)
    out: list[tuple[str, str, str]] = []
    for cau in re.split(r"(?<=[.;])\s+", doan):
        shs = [s for s in _sohieu_in(cau) if s and s not in used]
        if not shs:
            continue
        kq = _phan_loai_dong_tu(cau.lower())
        if kq is None:
            continue
        loai, edge = kq
        for sh in shs:
            out.append((loai, edge, sh))
            used.add(sh)
    return out


def extract_title_relations(title: str, own_so_hieu: str | None = None) -> list[tuple[str, str, str]]:
    """REPLACES/AMENDS từ TIÊU ĐỀ — neo theo động từ, theo từng câu (rule.md §3)."""
    return _quan_he_theo_cau(title or "", own_so_hieu)


def extract_final_clause_relations(text: str, own_so_hieu: str | None = None,
                                   exclude: set[str] | None = None) -> list[tuple[str, str, str]]:
    """REPLACES/AMENDS từ đoạn 'Hiệu lực thi hành'/'Điều khoản thi hành' — thường ở
    CUỐI văn bản (rule.md §3.1, phát hiện 2026-08-22). Câu tuyên bố thay thế/sửa đổi
    hay nằm ở đây, KHÔNG ở tiêu đề — vd 'Thông tư này có hiệu lực... và thay thế
    Thông tư liên tịch số 44/2013/TTLT-BCT-BKHCN...' (ca thật, đo trên corpus).
    Xử lý theo TỪNG CÂU (không phải cả đoạn) — xem `_quan_he_theo_cau`."""
    text_n = _norm_sh(text)
    low = text_n.lower()
    i = low.rfind("hiệu lực thi hành")
    if i < 0:
        i = low.rfind("điều khoản thi hành")
    if i >= 0:
        clause = text_n[i:]
    else:
        # Bug thật 2026-08-22 (VB 13234/most): fallback "N ký tự cuối" cho VB KHÔNG
        # có "hiệu lực thi hành"/"điều khoản thi hành" — nếu VB ngắn hơn N ký tự thì
        # "N ký tự cuối" = TOÀN VĂN, tái hiện đúng bẫy gốc (mục 3): đoạn "Căn cứ..."
        # ở đầu bị lẫn vào, số hiệu trong đó bị gán nhầm REPLACES/AMENDS. Chặn: không
        # bao giờ lấy phần TRƯỚC "Điều 1" (ranh giới cuối cùng của preamble).
        j = text_n.find("Điều 1")
        sau_dieu_1 = text_n[j:] if j > 0 else text_n
        clause = sau_dieu_1[-3000:]
    return _quan_he_theo_cau(clause, own_so_hieu, exclude)


def extract_guided_by(text: str, own_so_hieu: str | None = None,
                      exclude: set[str] | None = None) -> list[tuple[str, str, str]]:
    """GUIDED_BY từ đoạn 'Căn cứ...' (preamble, trước 'Điều 1') — rule.md §4."""
    own = _norm_sh(own_so_hieu) if own_so_hieu else None
    text_n = _norm_sh(text)
    i = text_n.find("Điều 1")
    preamble = text_n[:i] if i > 0 else text_n[:3500]
    used = set(exclude or set())
    if own:
        used.add(own)
    out: list[tuple[str, str, str]] = []
    for sh in _sohieu_in(preamble):
        if sh not in used:
            out.append(("CanCu", "GUIDED_BY", sh))
            used.add(sh)
    return out


def extract_references(title: str, text: str, own_so_hieu: str | None = None) -> list[tuple[str, str, str]]:
    """Pure: hợp REPLACES/AMENDS (tiêu đề + đoạn 'Hiệu lực thi hành' cuối văn bản) +
    GUIDED_BY (preamble). Không DB, test thẳng được."""
    rel = extract_title_relations(title, own_so_hieu)
    rel += extract_final_clause_relations(text, own_so_hieu, exclude={s for _, _, s in rel})
    guided = extract_guided_by(text, own_so_hieu, exclude={s for _, _, s in rel})
    return rel + guided


_EDGE_MAP = {"ThayThe": "REPLACES", "SuaDoi": "AMENDS", "CanCu": "GUIDED_BY"}
_LLM_SYS = (
    "Bạn bóc TOÀN BỘ quan hệ tham chiếu của một văn bản pháp luật Việt Nam thành JSON: "
    "{\"refs\":[{\"target\":\"số hiệu VB được tham chiếu (vd 24/2023/QH15)\", "
    "\"loai\":\"ThayThe|SuaDoi|CanCu\", \"confidence\":0.0-1.0}]}. "
    "ThayThe = văn bản này THAY THẾ TOÀN BỘ VB đích; SuaDoi = SỬA ĐỔI/BỔ SUNG (kể cả "
    "'thay thế MỘT SỐ ĐIỀU/KHOẢN' — vẫn là SuaDoi, không phải ThayThe); CanCu = CĂN CỨ "
    "(trích dẫn làm cơ sở pháp lý, thường ở đoạn đầu 'Căn cứ...'). "
    "BẮT BUỘC liệt kê ĐẦY ĐỦ mọi quan hệ tìm thấy — một văn bản thường có NHIỀU CanCu "
    "(mỗi dòng 'Căn cứ...' là 1 CanCu riêng) CỘNG THÊM tối đa 1 ThayThe/SuaDoi nếu có. "
    "KHÔNG chỉ chọn 1 quan hệ 'quan trọng nhất' rồi bỏ qua các CanCu khác. "
    "SỬA số hiệu bị lỗi OCR (vd 'QH1 3' → 'QH13', '24/2023/QH1' → '24/2023/QH13'). "
    "Chỉ lấy VB có SỐ HIỆU rõ. Không có thì {\"refs\":[]}."
)


def extract_references_llm(llm, title: str, preamble: str, own_so_hieu: str | None) -> list[tuple[str, str, str]]:
    """LLM bóc quan hệ (vá số hiệu OCR hỏng + phân loại đúng thay/sửa/căn cứ) — rule.md §5."""
    own = _norm_sh(own_so_hieu) if own_so_hieu else None
    user = f"Văn bản: {own_so_hieu}\nTiêu đề: {title}\n\nPhần đầu (căn cứ):\n{(preamble or '')[:3500]}"
    data = llm.chat_json(_LLM_SYS, user)
    out: list[tuple[str, str, str]] = []
    for r in (data.get("refs", []) if isinstance(data, dict) else []):
        loai = (r.get("loai") or "").strip()
        tgt = _norm_sh(r.get("target") or "")
        if loai in _EDGE_MAP and tgt and tgt != own and (_EDGE_MAP[loai], tgt) not in {(e, s) for _, e, s in out}:
            out.append((loai, _EDGE_MAP[loai], tgt))
    return out


_EDGE_TMPL = """
MATCH (src:Norm {{norm_id:$sid}}), (tgt:Norm {{so_hieu:$tsh}})
WHERE src <> tgt
MERGE (a:Action {{action_id:$aid}})
  SET a.loai=$loai, a.confidence=$conf, a.da_duyet=$duyet, a.enacted_by=$sid,
      a.ngay_hieu_luc=src.ngay_hieu_luc, a.source=$source
MERGE (a)-[:ENACTED_BY]->(src)
MERGE (a)-[:AFFECTS]->(tgt)
MERGE (src)-[:{edge}]->(tgt)
RETURN 1
"""


def apply_references(neo: Neo4jClient, norm_id: str, refs: list[tuple[str, str, str]],
                     source: str = "text_regex") -> dict:
    """Ghi Action + cạnh vào graph. REPLACES/AMENDS -> da_duyet=false; GUIDED_BY -> true
    (rule.md §6). `source` ghi vào Action.source để truy vết cạnh này từ đâu ra.
    `MATCH (tgt:Norm {so_hieu:...})`: nếu đích chưa có trong graph thì không tạo gì
    (Cypher MERGE trên MATCH rỗng không chạy) — idempotent, an toàn chạy lại."""
    n = {"REPLACES": 0, "AMENDS": 0, "GUIDED_BY": 0}
    for loai, edge, target in refs:
        conf = 0.85 if edge in ("REPLACES", "AMENDS") else 0.6
        duyet = edge == "GUIDED_BY"
        rows = neo.run(_EDGE_TMPL.format(edge=edge), sid=norm_id, tsh=target,
                       aid=f"{norm_id}->{target}:{edge}:{source}", loai=loai, conf=conf,
                       duyet=duyet, source=source)
        if rows:
            n[edge] += 1
    return n


def extract_corpus_references(neo: Neo4jClient, base: Path, src_dirs: list[str],
                              llm=None, resume: bool = True, pace_seconds: float = 0.0,
                              log=print) -> dict:
    """Quét raw dirs (doc.json + toanvan.html) -> bóc quan hệ -> ghi graph. rule.md §5/§8.

    `llm` != None: hợp nhất — GIỮ GUIDED_BY regex, BỎ AMENDS/REPLACES regex thay bằng
    kết quả LLM (rule.md §5). `resume`: chỉ xử lý VB chưa có flag refs_done/refs_llm_done
    (mỗi VB chỉ áp dẫn chiếu một lần — tránh chạy LLM lại tốn kém trên VB đã xong)."""
    doc_dirs = sorted({p.parent for sub in src_dirs for p in base.glob(f"{sub}/*/doc.json")})
    total = {"REPLACES": 0, "AMENDS": 0, "GUIDED_BY": 0}
    n_norm = n_proc = 0
    flag = "refs_llm_done" if llm is not None else "refs_done"
    src_tag = "llm" if llm is not None else "text_regex"
    done: set[str] = set()
    if resume:
        done = {r["id"] for r in neo.run(f"MATCH (n:Norm) WHERE n.{flag}=true RETURN n.norm_id AS id")}
    for d in doc_dirs:
        tv = d / "toanvan.html"
        if not tv.exists() or d.name in done:
            continue
        try:
            data = json.loads((d / "doc.json").read_text(encoding="utf-8"))["data"]
        except Exception:
            continue
        title, own = data.get("title") or "", data.get("docNum")
        text = html_to_text(tv.read_text(encoding="utf-8", errors="ignore"))
        refs = extract_references(title, text, own)
        if llm is not None:
            # Bỏ AMENDS/REPLACES từ regex thô (hay bảo thủ/sót khi câu phức tạp) — LLM
            # là nguồn chuẩn cho 2 loại này. Giữ GUIDED_BY regex (recall cao, rủi ro thấp).
            refs = [r for r in refs if r[1] == "GUIDED_BY"]
            i = _norm_sh(text).find("Điều 1")
            preamble = _norm_sh(text)[:i] if i > 0 else _norm_sh(text)[:3500]
            seen = {(e, s) for _, e, s in refs}
            for loai, edge, tgt in extract_references_llm(llm, title, preamble, own):
                if (edge, tgt) not in seen:
                    refs.append((loai, edge, tgt))
                    seen.add((edge, tgt))
        r = apply_references(neo, d.name, refs, source=src_tag)
        neo.run(f"MATCH (n:Norm {{norm_id:$id}}) SET n.{flag}=true", id=d.name)
        if any(r.values()):
            n_norm += 1
        for k in total:
            total[k] += r[k]
        n_proc += 1
        if n_proc % 100 == 0:
            log(f"  [{src_tag}] {n_proc} VB xử lý · quan hệ "
                f"{total['REPLACES']}R/{total['AMENDS']}A/{total['GUIDED_BY']}G")
        if llm is not None and pace_seconds > 0:
            time.sleep(pace_seconds)
    return {"norm": n_norm, **total}
