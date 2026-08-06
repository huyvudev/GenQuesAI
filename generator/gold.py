"""Tìm gold span trong index Qdrant đang phục vụ RAG.

Bất biến I2 + §7.1: gold span phải trỏ vào ĐÚNG chunk mà retriever có khả năng trả
về, kèm offset trên `payload["text"]` (KHÔNG phải trên text đã embed — text đã embed
có thêm header của build_text_unit, xem §10.1 R3).
"""
from __future__ import annotations

from dataclasses import dataclass, asdict

from qdrant_client import models as qm

from .common import content_hash, point_id


@dataclass
class GoldSpan:
    expr_id: str
    part: int
    chunk_id: str
    start: int
    end: int
    chunk_text_sha256: str
    text: str

    def to_json(self) -> dict:
        d = asdict(self)
        d.pop("text")           # text nằm ở `reference`, không lặp lại trong span
        return d


def _norm_filter(norm_id: str) -> qm.Filter:
    return qm.Filter(must=[qm.FieldCondition(key="norm_id",
                                             match=qm.MatchValue(value=norm_id))])


def points_of_norm(store, norm_id: str, cap: int = 2000) -> list:
    """Mọi point của một văn bản. norm_id đã có payload index nên lọc rẻ."""
    out, offset = [], None
    while len(out) < cap:
        pts, offset = store.client.scroll(
            store.collection, scroll_filter=_norm_filter(norm_id),
            with_payload=True, with_vectors=False, limit=256, offset=offset)
        out.extend(pts)
        if offset is None:
            break
    return out


# Điều khoản thi hành thường viết: "Các quy định sau đây HẾT HIỆU LỰC kể từ ngày ...:"
# rồi liệt kê từng văn bản. Số hiệu văn bản cũ nằm ở một mục trong danh sách, còn câu
# mang nghĩa nằm ở phần DẪN phía trên — nên phải bắt cả hai, không cắt riêng mục.
_KW_BAI_BO = ("hết hiệu lực", "bãi bỏ", "thay thế", "ngưng hiệu lực")
_KW_TIEU_DE = ("hiệu lực", "thi hành", "chuyển tiếp", "bãi bỏ")
MAX_SPAN = 1200


def _diem_bang_chung(text_low: str, tieu_de_low: str, i: int) -> tuple[int, int | None]:
    """Chấm điểm mức độ 'đây đúng là điều khoản bãi bỏ' + vị trí từ khoá dẫn."""
    diem = 0
    if any(k in tieu_de_low for k in _KW_TIEU_DE):
        diem += 2
    vi_tri = None
    for k in _KW_BAI_BO:
        p = text_low.rfind(k, 0, i)          # từ khoá đứng TRƯỚC số hiệu -> câu dẫn
        if p >= 0 and (vi_tri is None or p > vi_tri):
            vi_tri = p
    if vi_tri is not None:
        diem += 3
    elif any(k in text_low for k in _KW_BAI_BO):
        diem += 1                            # có từ khoá nhưng đứng sau -> yếu hơn
    return diem, vi_tri


def find_evidence_span(store, norm_id: str, needle: str) -> tuple[GoldSpan | None, int]:
    """Span bằng chứng TỐT NHẤT trong `norm_id` cho việc bãi bỏ `needle`.

    Duyệt mọi chunk của văn bản, chấm điểm, lấy cao nhất — KHÔNG lấy chunk khớp đầu
    tiên: số hiệu văn bản cũ có thể xuất hiện ở chỗ chỉ dẫn chiếu, không phải chỗ bãi
    bỏ. Trả (span, điểm); điểm 0 nghĩa là chỉ thấy nhắc tên, không phải bằng chứng.
    """
    if not needle:
        return None, 0
    tot: tuple[GoldSpan, int] | None = None
    for p in points_of_norm(store, norm_id):
        pl = p.payload or {}
        text = pl.get("text") or ""
        i = text.find(needle)
        if i < 0:
            continue
        expr_id, part = pl.get("expr_id", ""), int(pl.get("part", 0))
        if point_id(expr_id, part) != str(p.id):     # kiểm chéo id (§9)
            continue

        diem, kw = _diem_bang_chung(text.lower(), (pl.get("tieu_de") or "").lower(), i)

        # Bắt đầu span từ câu DẪN chứa từ khoá, nếu nó đủ gần; nếu không thì từ đầu câu.
        if kw is not None and i - kw <= MAX_SPAN:
            start = max(text.rfind("\n", 0, kw), text.rfind(". ", 0, kw)) + 1
        else:
            start = max(text.rfind("\n", 0, i), text.rfind(". ", 0, i)) + 1
        if start < 0:
            start = 0
        # Kết thúc ở cuối mục chứa số hiệu (dấu ; hoặc . hoặc xuống dòng).
        sau = i + len(needle)
        cands = [x for x in (text.find("\n", sau), text.find("; ", sau),
                             text.find(". ", sau)) if x >= 0]
        end = (min(cands) + 1) if cands else min(len(text), sau + 200)
        if end - start > MAX_SPAN:
            start = max(start, end - MAX_SPAN)

        span = GoldSpan(expr_id=expr_id, part=part, chunk_id=str(p.id),
                        start=start, end=end,
                        chunk_text_sha256=content_hash(text),
                        text=text[start:end].strip())
        if tot is None or diem > tot[1]:
            tot = (span, diem)
    return (tot[0], tot[1]) if tot else (None, 0)


def gate_c1(store, span: GoldSpan) -> tuple[bool, str]:
    """C1 — chunk còn nguyên nội dung (hash khớp) VÀ span nằm đúng offset.

    Đây là cổng duy nhất bắt được ca 'id còn nguyên nhưng text đã đổi' (§10.1 R1).
    """
    pts = store.client.retrieve(store.collection, ids=[span.chunk_id], with_payload=True)
    if not pts:
        return False, "chunk_missing"
    text = (pts[0].payload or {}).get("text") or ""
    if content_hash(text) != span.chunk_text_sha256:
        return False, "hash_mismatch"
    if text[span.start:span.end].strip() != span.text:
        return False, "offset_mismatch"
    return True, "pass"
