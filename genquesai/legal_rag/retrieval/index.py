"""Embed pipeline: Neo4j (Component/Expression) -> bge-m3 -> Qdrant (ARCH §5.1.7-8, §4.3).

Mỗi Expression có text -> 1 point: vector dense+sparse, payload để lọc point-in-time.
"""
from __future__ import annotations
import uuid
from typing import Callable

from qdrant_client import models as qm

from .embedder import Embedder
from .qdrant_store import QdrantStore, DENSE, SPARSE
from ..graph.client import Neo4jClient
from ..ingestion.text_unit import build_text_unit

_NS = uuid.uuid5(uuid.NAMESPACE_URL, "legal-rag/expr")

# Nhúng ở mức ĐIỀU (gọn + ngữ cảnh đầy đủ): mỗi point = 1 Điều với text gồm
# lead của Điều + toàn bộ Khoản/Điểm con (xếp theo order_key). Graph vẫn giữ
# Khoản/Điểm rời để drill-down. VB không có Điều -> dùng node ToanVan.
FETCH = """
MATCH (n:Norm)-[:HAS_PART*]->(d:Component)
WHERE d.loai IN ['Dieu','ToanVan','PhuLuc']
  AND ($norm_ids IS NULL OR n.norm_id IN $norm_ids)
MATCH (d)-[:HAS_VERSION]->(de:Expression)
CALL (d) {
  MATCH (d)-[:HAS_PART*0..]->(x:Component)-[:HAS_VERSION]->(e:Expression)
  WITH x, e ORDER BY x.order_key
  RETURN collect(e.text) AS texts
}
RETURN de.expr_id AS expr_id, d.comp_id AS comp_id, n.norm_id AS norm_id,
       n.so_hieu AS so_hieu, n.loai_vb AS loai_vb, n.tieu_de AS norm_tieu_de,
       d.duong_dan AS duong_dan, d.tieu_de AS comp_tieu_de, texts AS texts,
       de.hieu_luc_tu AS hieu_luc_tu, de.hieu_luc_den AS hieu_luc_den
"""


def point_id(expr_id: str, part: int = 0) -> str:
    # part=0 giữ NGUYÊN id cũ (uuid5(expr_id)) -> tương thích resume/undo cho chunk 1 mảnh;
    # part>0 (chunk dài bị cắt cửa sổ) dùng khoá 'expr_id#part'.
    key = expr_id if part == 0 else f"{expr_id}#{part}"
    return str(uuid.uuid5(_NS, key))


def split_windows(text: str, size: int, overlap: int) -> list[str]:
    """Cắt text dài thành cửa sổ ~size ký tự, chồng lấn overlap, ưu tiên ngắt ở xuống dòng/câu.
    Text ngắn -> trả 1 phần. Dùng để re-chunk Phụ lục/bảng gộp trong 1 Điều (ARCH §5.1.7)."""
    text = (text or "").strip()
    if len(text) <= size:
        return [text] if text else []
    out: list[str] = []
    start, n = 0, len(text)
    while start < n:
        end = min(start + size, n)
        if end < n:                       # tìm ranh giới đẹp trong nửa sau cửa sổ
            win = text[start:end]
            cut = max(win.rfind("\n"), win.rfind(". "), win.rfind("; "), win.rfind(", "))
            if cut > size // 2:
                end = start + cut + 1
        piece = text[start:end].strip()
        if piece:
            out.append(piece)
        if end >= n:
            break
        start = max(end - overlap, start + 1)
    return out


def _rfc(d) -> str | None:
    if d is None:
        return None
    iso = d.iso_format() if hasattr(d, "iso_format") else str(d)
    return f"{iso}T00:00:00Z"


def _sparse(lex: dict) -> qm.SparseVector:
    idx, val = [], []
    for k, v in lex.items():
        if v > 0:
            idx.append(int(k))
            val.append(float(v))
    return qm.SparseVector(indices=idx, values=val)


def embed_corpus(neo: Neo4jClient, store: QdrantStore, embedder: Embedder,
                 batch: int = 64, limit: int | None = None,
                 norm_ids: list[str] | None = None, skip_existing: bool = False,
                 window_chars: int = 1000, window_overlap: int = 120,
                 log: Callable[[str], None] = print) -> int:
    # skip_existing (resume): bỏ qua Điều đã embed (point_id có trong Qdrant) -> chạy lại không
    # làm lại từ đầu, gián đoạn vẫn tiến triển tích luỹ. Tải tập id 1 lần.
    existing = store.scroll_point_ids() if skip_existing else set()
    if skip_existing:
        log(f"  resume: đã có {len(existing):,} point — sẽ bỏ qua")
    buf: list[dict] = []
    total = skipped = 0

    def flush() -> None:
        nonlocal total
        # Re-chunk: mỗi Điều -> 1..N cửa sổ (Điều/Phụ lục dài bị cắt để embed đủ, không nuốt đuôi).
        win_texts: list[str] = []                         # text để embed (kèm header ngữ cảnh)
        win_meta: list[tuple[dict, int, int, str]] = []   # (row, part, n_parts, body_window)
        for r in buf:
            body = "\n".join(t for t in (r["texts"] or []) if t)
            wins = split_windows(body, window_chars, window_overlap) or [body]
            for part, w in enumerate(wins):
                win_texts.append(build_text_unit(r["so_hieu"], r["norm_tieu_de"],
                                                 r["duong_dan"], r["comp_tieu_de"], w))
                win_meta.append((r, part, len(wins), w))
        dense, lex = embedder.encode(win_texts)
        points = []
        for j, (r, part, n_parts, w) in enumerate(win_meta):
            points.append(qm.PointStruct(
                id=point_id(r["expr_id"], part),
                vector={DENSE: dense[j].tolist(), SPARSE: _sparse(lex[j])},
                payload={
                    "expr_id": r["expr_id"], "comp_id": r["comp_id"], "norm_id": r["norm_id"],
                    "so_hieu": r["so_hieu"], "loai_vb": r["loai_vb"], "duong_dan": r["duong_dan"],
                    "tieu_de": r["comp_tieu_de"], "text": w, "part": part, "n_parts": n_parts,
                    "hieu_luc_tu": _rfc(r["hieu_luc_tu"]), "hieu_luc_den": _rfc(r["hieu_luc_den"]),
                }))
        store.upsert(points)
        total += len(points)
        buf.clear()

    for r in neo.stream(FETCH, norm_ids=norm_ids):
        if existing and point_id(r["expr_id"]) in existing:
            skipped += 1
            continue
        buf.append(r)
        if len(buf) >= batch:
            flush()
            if total % (batch * 10) == 0:
                log(f"  embedded {total}" + (f" (skip {skipped:,})" if skip_existing else ""))
            if limit and total >= limit:
                return total
    if buf:
        flush()
    return total
