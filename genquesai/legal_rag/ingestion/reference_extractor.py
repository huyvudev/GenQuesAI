"""Reference Extractor — bóc quan hệ Căn cứ/Sửa đổi/Thay thế từ TEXT (regex nền + LLM
tuỳ chọn). Quy tắc đầy đủ + lý do: xem `../rule.md`. Tóm tắt:

- REPLACES/AMENDS: chỉ đọc TIÊU ĐỀ, neo theo ĐỘNG TỪ (không neo theo "có số hiệu ở
  đâu đó" trong toàn văn — bẫy đã biết: nhầm câu "Căn cứ Nghị định X..." thành AMENDS).
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

from ..graph.client import Neo4jClient

# Số hiệu VBQPPL tổng quát — bắt MỌI loại (kể cả QĐ-UBND/NQ-HĐND cấp tỉnh), chịu
# khoảng trắng lệch do OCR quanh dấu '/'.
SOHIEU_RE = re.compile(r"\d+\s*/\s*\d{4}\s*/\s*[A-ZĐ0-9]+(?:-[A-ZĐ0-9]+)*", re.IGNORECASE)

# Neo theo ĐỘNG TỪ (rule.md §3) — SUA xét trước BAIBO khi tiêu đề lẫn cả hai (bảo thủ
# hơn: coi là sửa từng phần thay vì thay thế toàn bộ).
SUA = ("sửa đổi", "bổ sung", "điều chỉnh", "thay thế", "dừng thực hiện", "đình chỉ thi hành")
BAIBO = ("bãi bỏ", "hủy bỏ", "huỷ bỏ")


def _norm_sh(s: str) -> str:
    return re.sub(r"\s*/\s*", "/", s or "").strip()


def _sohieu_in(s: str) -> list[str]:
    return list(dict.fromkeys(_norm_sh(x) for x in SOHIEU_RE.findall(_norm_sh(s))))


def extract_title_relations(title: str, own_so_hieu: str | None = None) -> list[tuple[str, str, str]]:
    """REPLACES/AMENDS từ TIÊU ĐỀ — neo theo động từ (rule.md §3). Trả [(loai, edge, target)]."""
    title = title or ""
    low = title.lower()
    own = _norm_sh(own_so_hieu) if own_so_hieu else None
    shs = [s for s in _sohieu_in(title) if s and s != own]
    if not shs:
        return []
    if any(k in low for k in SUA):
        loai, edge = "SuaDoi", "AMENDS"
    elif any(k in low for k in BAIBO):
        loai, edge = "ThayThe", "REPLACES"
    else:
        return []
    return [(loai, edge, s) for s in shs]


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
    """Pure: hợp REPLACES/AMENDS (tiêu đề) + GUIDED_BY (preamble). Không DB, test thẳng được."""
    rel = extract_title_relations(title, own_so_hieu)
    guided = extract_guided_by(text, own_so_hieu, exclude={s for _, _, s in rel})
    return rel + guided


_EDGE_MAP = {"ThayThe": "REPLACES", "SuaDoi": "AMENDS", "CanCu": "GUIDED_BY"}
_LLM_SYS = (
    "Bạn bóc QUAN HỆ THAM CHIẾU của một văn bản pháp luật Việt Nam thành JSON: "
    "{\"refs\":[{\"target\":\"số hiệu VB được tham chiếu (vd 24/2023/QH15)\", "
    "\"loai\":\"ThayThe|SuaDoi|CanCu\", \"confidence\":0.0-1.0}]}. "
    "ThayThe = văn bản này THAY THẾ VB đích; SuaDoi = SỬA ĐỔI/BỔ SUNG; CanCu = CĂN CỨ. "
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
        text = re.sub(r"<[^>]+>", " ", tv.read_text(encoding="utf-8", errors="ignore"))
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
