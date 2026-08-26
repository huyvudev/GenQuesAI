"""Đồng thuận đa nguồn (metadata + regex + LLM) — dò REPLACES/AMENDS/GUIDED_BY.

Quy tắc đầy đủ: xem `../rule.md` (mục 0.1, 2, 5, 6, 7 — v3). Tóm tắt:

- 3 nguồn NGANG HÀNG, LLM luôn chạy (không còn là lớp tuỳ chọn):
  metadata (`referenceType` trong `doc.json`) · regex (`reference_extractor.py`,
  tiêu đề cho REPLACES/AMENDS + đoạn "Căn cứ..." cho GUIDED_BY) · LLM (luôn chạy).
- Nhánh A (có metadata): so 2-3 nguồn (metadata + regex? + llm) — khớp hết mới duyệt.
- Nhánh B (không metadata, có regex): so regex vs llm — khớp mới duyệt.
- Nhánh C (không metadata, không regex): chỉ LLM — không đối chiếu được, không tự duyệt.
- `reconcile.py::reconcile_corpus` (chạy lúc `ingest`) đã tạo Action từ metadata với
  chính sách RIÊNG của nó — module này KHÔNG tạo Action trùng cho
  nhánh A, mà đọc lại Action đã có rồi cập nhật field đồng thuận + `da_duyet`.

Phần thuần (`extract_metadata_relations`, `dong_thuan`) tách khỏi phần chạm DB
(`resolve_relations`, `process_corpus`) để test không cần Neo4j.
"""
from __future__ import annotations
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from ..graph.client import Neo4jClient
from .reconcile import REL_MAP
from .reference_extractor import (
    _cat_doan_hieu_luc, _norm_sh, _PHU_LUC_RE, extract_references, extract_references_llm, html_to_text,
)

Quan_He = tuple[str, str, str]   # (loai, edge, target_so_hieu)

# Flag resume theo nhánh (rule.md mục 8). ĐẶT TÊN `dong_thuan_*` — KHÔNG dùng
# `refs_llm_done`/`refs_done` (bug thật 2026-08-22): đó là tên field mà pipeline v1
# (`reference_extractor.py::extract_corpus_references`) VÀ dữ liệu production GỐC
# của Chatbot-Law (title_refs_parser.py/claude_refs_*, backbone.md §23) đã dùng từ
# trước trên **7.550 VB thật** (không liên quan gì tới consensus v3) — nếu dùng
# trùng tên, resume logic của v3 sẽ coi nhầm 7.550 VB đó là "đã xong theo v3" (dù
# CHƯA TỪNG qua consensus) và bỏ sót vĩnh viễn, âm thầm, không báo lỗi gì. Đã xác
# nhận trên server production: refs_llm_done=true nhưng KHÔNG Action nào có field
# nguon_llm (dấu hiệu chắc chắn là flag CŨ, không phải v3 tạo).
_FLAG = {"A": "dong_thuan_meta_done", "B": "dong_thuan_regex_done", "C": "dong_thuan_llm_done"}


def extract_metadata_relations(data: dict) -> list[Quan_He]:
    """Nhánh metadata: `referenceType` trong `doc.json` -> [(loai, edge, so_hieu)].
    Dùng `targetDocument.docNum` (đã xác nhận có sẵn trong dữ liệu thật — không cần
    tra DB). Tái dùng `REL_MAP` của `reconcile.py` — một nguồn map, không viết lại."""
    out: list[Quan_He] = []
    for ref in (data.get("references") or []):
        rt = ref.get("referenceType")
        if rt not in REL_MAP:
            continue
        tsh = (ref.get("targetDocument") or {}).get("docNum")
        if not tsh:
            continue
        loai, edge = REL_MAP[rt]
        out.append((loai, edge, _norm_sh(tsh)))
    return out


def _as_pairs(refs: list[Quan_He]) -> set[tuple[str, str]]:
    return {(edge, target) for _, edge, target in refs}


def dong_thuan(metadata: list[Quan_He] | None, regex: list[Quan_He] | None,
               llm: list[Quan_He]) -> dict:
    """So khớp đa nguồn (rule.md mục 2). `metadata`/`regex` = None nghĩa là KHÔNG khả
    dụng (khác rỗng `[]` = khả dụng nhưng không tìm thấy gì). `llm` luôn là list (có
    thể rỗng — LLM chạy nhưng không thấy quan hệ nào).

    Trả {"nhanh": "A"|"B"|"C", "khop": bool|None, "metadata": set|None,
         "regex": set|None, "llm": set}. `khop=None` chỉ ở nhánh C (không có gì đối
    chiếu — không phải "khớp" hay "lệch", mà là "không đối chiếu được")."""
    llm_p = _as_pairs(llm)
    if metadata is not None:
        meta_p = _as_pairs(metadata)
        if regex is not None:
            regex_p = _as_pairs(regex)
            khop = meta_p == regex_p == llm_p
            return {"nhanh": "A", "khop": khop, "metadata": meta_p, "regex": regex_p, "llm": llm_p}
        khop = meta_p == llm_p
        return {"nhanh": "A", "khop": khop, "metadata": meta_p, "regex": None, "llm": llm_p}
    if regex is not None:
        regex_p = _as_pairs(regex)
        khop = regex_p == llm_p
        return {"nhanh": "B", "khop": khop, "metadata": None, "regex": regex_p, "llm": llm_p}
    return {"nhanh": "C", "khop": None, "metadata": None, "regex": None, "llm": llm_p}


def dong_thuan_per_edge(metadata: list[Quan_He] | None, regex: list[Quan_He] | None,
                        llm: list[Quan_He]) -> list[dict]:
    """So khớp CẤP TỪNG CẠNH (rule.md mục X, sửa 2026-08-24) — quyết định `da_duyet`
    riêng cho mỗi (edge,target), KHÔNG broadcast 1 quyết định chung cho cả VB như
    `dong_thuan()` cũ.

    **Bug đã sửa:** thiết kế cũ chỉ tạo Action từ 1 "nguồn mặc định" (metadata ở
    nhánh A, regex ở nhánh B, llm ở nhánh C) — nếu nguồn mặc định KHÔNG thấy 1 cạnh
    nhưng nguồn khác (vd LLM) THẤY, cạnh đó bị lặng lẽ không tạo Action nào, kể cả
    khi cần gắn cờ `mismatch` để người rà biết. Ở đây: hợp NHẤT mọi cạnh mà BẤT KỲ
    nguồn khả dụng nào tìm thấy, mỗi cạnh tự xét đồng thuận riêng — có mặt ở ĐỦ mọi
    nguồn khả dụng thì `da_duyet=True`; thiếu ở ≥1 nguồn khả dụng thì `mismatch=True`;
    chỉ có LLM là nguồn duy nhất (không metadata, không regex) thì `only_llm=True`.

    Trả list dict {"loai","edge","target","da_duyet","mismatch","only_llm","nguon"}
    (`nguon` = tên các nguồn đã tìm thấy đúng cạnh này, để người rà biết vì sao)."""
    sources: dict[str, set[tuple[str, str]] | None] = {
        "metadata": _as_pairs(metadata) if metadata is not None else None,
        "regex": _as_pairs(regex) if regex is not None else None,
        "llm": _as_pairs(llm),  # LLM luôn khả dụng (list rỗng nếu không thấy gì)
    }
    available = {k: v for k, v in sources.items() if v is not None}
    chi_llm = len(available) == 1  # tương đương nhánh C (chỉ "llm" nằm trong available)

    loai_map: dict[tuple[str, str], str] = {}
    for refs in (metadata, regex, llm):
        for loai, edge, target in (refs or []):
            loai_map[(edge, target)] = loai

    all_pairs: set[tuple[str, str]] = set()
    for v in available.values():
        all_pairs |= v

    out: list[dict] = []
    for edge, target in sorted(all_pairs):
        found_in = sorted(name for name, v in available.items() if (edge, target) in v)
        if chi_llm:
            da_duyet, mismatch, only_llm = False, False, True
        else:
            khop = len(found_in) == len(available)
            da_duyet, mismatch, only_llm = khop, not khop, False
        out.append({"loai": loai_map[(edge, target)], "edge": edge, "target": target,
                    "da_duyet": da_duyet, "mismatch": mismatch, "only_llm": only_llm,
                    "nguon": found_in})
    return out


def _ghi_canh_moi(neo: Neo4jClient, norm_id: str, edges: list[dict], source: str) -> list[dict]:
    """Tạo Action cho từng cạnh trong `edges` (đầu ra `dong_thuan_per_edge`). Chỉ TẠO
    MỚI — không còn nhánh "update Action cũ" (rebuild 2026-08-24: mọi Action cũ đã bị
    xoá sạch trước khi chạy lại, xem rule.md). Trả lại `edges` bổ sung field `da_tao`
    (False nếu VB đích không tồn tại trong graph — không thể MERGE cạnh, cần biết để
    không tưởng nhầm là đã ghi)."""
    out: list[dict] = []
    for e in edges:
        loai, edge, target = e["loai"], e["edge"], e["target"]
        conf = 0.85 if edge in ("REPLACES", "AMENDS") else 0.6
        rows = neo.run(
            f"""
            MATCH (src:Norm {{norm_id:$sid}}), (tgt:Norm {{so_hieu:$tsh}})
            WHERE src <> tgt
            MERGE (a:Action {{action_id:$aid}})
              SET a.loai=$loai, a.confidence=$conf, a.da_duyet=$duyet, a.enacted_by=$sid,
                  a.ngay_hieu_luc=src.ngay_hieu_luc, a.source=$source,
                  a.mismatch=$mismatch, a.only_llm=$only_llm, a.nguon=$nguon
            MERGE (a)-[:ENACTED_BY]->(src)
            MERGE (a)-[:AFFECTS]->(tgt)
            MERGE (src)-[:{edge}]->(tgt)
            RETURN 1
            """, sid=norm_id, tsh=target, aid=f"{norm_id}->{target}:{edge}:{source}",
            loai=loai, conf=conf, duyet=e["da_duyet"], source=source,
            mismatch=e["mismatch"], only_llm=e["only_llm"], nguon=json.dumps(e["nguon"], ensure_ascii=False))
        out.append({**e, "da_tao": bool(rows)})
    return out


def _preamble_va_dieu_khoan_cuoi(text: str) -> str:
    """Đoạn "Căn cứ..." (đầu) + đoạn "Hiệu lực thi hành" (cuối) ghép lại — input DUY
    NHẤT cho LLM ở CẢ 3 nhánh A/B/C (rule.md §3.1/§5.1/§5.2 — sửa 2026-08-23: nhánh C
    không còn đọc TOÀN VĂN, xem `resolve_relations`). PHẢI cho LLM thấy CẢ đoạn cuối,
    không chỉ preamble — nếu không LLM sẽ thiếu đúng những gì regex thiếu (không phải
    vì LLM sai, mà vì không được cho xem), khiến so sánh mismatch giả tạo.

    Đoạn cuối dùng chung `_cat_doan_hieu_luc` với regex (dừng ở Điều tiếp theo/Phụ
    lục, KHÔNG chỉ cắt cứng theo ký tự) — sửa 2026-08-23: cắt cứng 1500 ký tự vẫn có
    thể lẫn "Trách nhiệm thi hành"/"Tổ chức thực hiện" (nhiệm vụ giao bộ ngành,
    không phải hành vi của chính VB này) nếu nội dung đó rơi trong 1500 ký tự đầu
    sau "hiệu lực thi hành". Chia ngân sách ký tự RÕ RÀNG (preamble ≤1800, đoạn cuối
    ≤1500) vì `extract_references_llm` cắt CHUỖI TỔNG ở 3500 ký tự."""
    text_n = _norm_sh(text)
    low = text_n.lower()
    i = text_n.find("Điều 1")
    preamble = (text_n[:i] if i > 0 else text_n[:1800])[:1800]
    j = low.rfind("hiệu lực thi hành")
    if j < 0:
        j = low.rfind("điều khoản thi hành")
    if j >= 0:
        dieu_khoan_cuoi = _cat_doan_hieu_luc(text_n, j)[:1500]
    else:
        m = _PHU_LUC_RE.search(text_n)
        gioi_han = text_n[: m.start()] if m else text_n
        dieu_khoan_cuoi = gioi_han[-1500:]
    return (f"[PHẦN ĐẦU — căn cứ]\n{preamble}\n\n"
            f"[PHẦN CUỐI — hiệu lực thi hành, thường ghi rõ thay thế/sửa đổi VB nào]\n{dieu_khoan_cuoi}")


_LOG_LOCK = threading.Lock()


def _ghi_log_tien_do(log_path: Path, record: dict) -> None:
    """Ghi 1 dòng JSONL vào file tiến trình — append-only, khoá luồng (workers>1),
    flush ngay để không mất khi mất điện/mất mạng giữa chừng (rebuild 2026-08-24,
    yêu cầu người dùng: '1 cơ hội duy nhất', phải có checkpoint sống)."""
    with _LOG_LOCK:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
            f.flush()


def resolve_relations(neo: Neo4jClient, llm_client, norm_id: str, data: dict,
                      title: str, text: str, own_so_hieu: str | None,
                      log_path: Path | None = None) -> dict:
    """Xử lý 1 VB theo luồng v3 (rule.md mục 0.1): xác định nhánh A/B/C, gọi LLM đúng
    input theo nhánh, đối chiếu CẤP TỪNG CẠNH (`dong_thuan_per_edge`, rebuild
    2026-08-24), ghi kết quả vào graph + (nếu có `log_path`) 1 dòng JSONL checkpoint.
    `llm_client` bắt buộc (khác `reference_extractor.extract_corpus_references` — ở
    đây LLM LUÔN chạy)."""
    meta = extract_metadata_relations(data)
    regex = extract_references(title, text, own_so_hieu)

    meta_arg = meta if meta else None
    regex_arg = regex if regex else None

    # LLM luôn đọc CÙNG 2 vùng (preamble "Căn cứ..." + đoạn "Hiệu lực thi hành",
    # mục 5.1) BẤT KỂ nhánh A/B/C — kể cả nhánh C (không có gì đối chiếu) KHÔNG còn
    # đọc "TOÀN VĂN" như thiết kế cũ (mục 5.2 cũ). Sửa 2026-08-23 (user phát hiện):
    # đọc toàn văn khiến LLM lẫn vào các đoạn "Trách nhiệm thi hành"/"Tổ chức thực
    # hiện" liệt kê NHIỆM VỤ giao bộ ngành (vd "...trình Nghị định thay thế Nghị
    # định Y...") — đây là VIỆC GIAO CHO TƯƠNG LAI, không phải chính VB này thay thế
    # Y, nhưng LLM đọc toàn văn dễ hiểu nhầm thành quan hệ thật. Quy tắc "chỉ đọc 2
    # vùng đúng ngữ nghĩa" (rule.md §0) áp dụng cho CẢ regex LẪN LLM, không chỉ regex.
    llm_input = _preamble_va_dieu_khoan_cuoi(text)
    llm_refs = extract_references_llm(llm_client, title, llm_input, own_so_hieu, neo=neo)

    kq = dong_thuan(meta_arg, regex_arg, llm_refs)  # chỉ để phân nhánh + thống kê
    edges = dong_thuan_per_edge(meta_arg, regex_arg, llm_refs)
    edges = _ghi_canh_moi(neo, norm_id, edges, source="llm")

    if log_path is not None:
        _ghi_log_tien_do(log_path, {
            "norm_id": norm_id, "so_hieu": own_so_hieu, "title": title,
            "nhanh": kq["nhanh"], "n_edges": len(edges), "edges": edges,
        })
    return {**kq, "edges": edges}


def _xu_ly_1_vb(neo: Neo4jClient, llm_client, d: Path, log_path: Path | None = None) -> dict | None:
    """Xử lý 1 VB (đọc file + `resolve_relations` + set flag resume). Trả `kq` hoặc
    `None` nếu đọc file lỗi. Hàm trần, không đụng state chia sẻ — an toàn gọi song
    song (mỗi lời gọi 1 luồng), xem `process_corpus`."""
    try:
        data = json.loads((d / "doc.json").read_text(encoding="utf-8"))["data"]
    except Exception:
        return None
    title, own = data.get("title") or "", data.get("docNum")
    try:
        text = html_to_text((d / "toanvan.html").read_text(encoding="utf-8", errors="ignore"))
        kq = resolve_relations(neo, llm_client, d.name, data, title, text, own, log_path=log_path)
        flag = _FLAG[kq["nhanh"]]
        neo.run(f"MATCH (n:Norm {{norm_id:$id}}) SET n.{flag}=true", id=d.name)
        return kq
    except Exception as e:
        # 1 VB lỗi (JSON LLM hỏng, mạng chập chờn, ...) KHÔNG được làm sập cả batch
        # song song — batch full corpus từng chết vì đúng lỗi này (rule.md mục 9.2).
        # Không set flag → VB này sẽ được thử lại ở lượt resume kế tiếp.
        print(f"  ! lỗi xử lý {d.name}: {e!r}")
        return None


def process_corpus(neo: Neo4jClient, llm_client, base: Path, src_dirs: list[str],
                   resume: bool = True, limit: int | None = None, workers: int = 1,
                   log=print, log_path: Path | None = None) -> dict:
    """Quét raw dirs, chạy `resolve_relations` theo luồng v3 cho từng VB. Resume qua
    3 flag riêng theo nhánh (rule.md mục 8) — mỗi VB chỉ rơi vào đúng 1 nhánh nên chỉ
    1 flag/VB được set, nhưng kiểm tra cả 3 để coi là "đã xong". `limit`: chỉ chọn N
    VB đầu tiên (theo thứ tự path, sau khi lọc done/thiếu toanvan.html) — dùng để test
    nhỏ trước khi chạy full corpus (rule.md mục 9).

    `workers`: số luồng chạy song song (mặc định 1 = tuần tự, an toàn tương thích
    ngược). `Neo4jClient.run()` tự mở session riêng mỗi lời gọi (driver neo4j
    thread-safe) và `LLM` (OpenAI SDK) cũng thread-safe — dùng CHUNG 1 instance qua
    các luồng, không cần tạo riêng mỗi luồng (rule.md mục 10)."""
    doc_dirs = sorted({p.parent for sub in src_dirs for p in base.glob(f"{sub}/*/doc.json")})
    done: set[str] = set()
    if resume:
        for flag in _FLAG.values():
            done |= {r["id"] for r in neo.run(f"MATCH (n:Norm) WHERE n.{flag}=true RETURN n.norm_id AS id")}
    # Chỉ xử lý thư mục corpus có Norm THẬT trong Neo4j (đã `ingest`) — thư mục
    # crawl nhưng chưa ingest thì SET flag ở cuối `_xu_ly_1_vb` là no-op (không
    # khớp node nào), nên KHÔNG BAO GIỜ được đánh dấu "đã xong" → nếu không lọc ở
    # đây, mỗi lần resume sẽ xử lý lại vô hạn đúng các VB này, tốn LLM vô ích và có
    # thể tạo Action mồ côi (rule.md mục 9.2 — phát hiện khi full corpus "kẹt" ở
    # ~29.219 dù job vẫn chạy bình thường).
    all_norm_ids = {r["id"] for r in neo.run("MATCH (n:Norm) RETURN n.norm_id AS id")}
    can_xu_ly = [d for d in doc_dirs
                 if (d / "toanvan.html").exists() and d.name in all_norm_ids and d.name not in done]
    n_chua_ingest = sum(1 for d in doc_dirs if (d / "toanvan.html").exists() and d.name not in all_norm_ids)
    if n_chua_ingest:
        log(f"  (bỏ qua {n_chua_ingest} thư mục corpus chưa `ingest` vào Neo4j — chạy `ingest` trước)")
    if limit:
        can_xu_ly = can_xu_ly[:limit]

    counts = {"A": 0, "B": 0, "C": 0, "khop": 0, "mismatch": 0, "only_llm": 0}
    n_proc = 0
    lock = threading.Lock()

    def _viec(d: Path) -> None:
        nonlocal n_proc
        kq = _xu_ly_1_vb(neo, llm_client, d, log_path=log_path)
        if kq is None:
            return
        with lock:
            counts[kq["nhanh"]] += 1
            if kq["khop"] is True:
                counts["khop"] += 1
            elif kq["khop"] is False:
                counts["mismatch"] += 1
            else:
                counts["only_llm"] += 1
            n_proc += 1
            if n_proc % 100 == 0:
                log(f"  {n_proc} VB · nhánh A={counts['A']}/B={counts['B']}/C={counts['C']} · "
                    f"khớp={counts['khop']} lệch={counts['mismatch']} chỉ-LLM={counts['only_llm']}")

    if workers <= 1:
        for d in can_xu_ly:
            _viec(d)
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            list(pool.map(_viec, can_xu_ly))
    return {"processed": n_proc, **counts}
