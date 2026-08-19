"""Tìm gold span trong index Qdrant đang phục vụ RAG.

Bất biến I2 + §7.1: gold span phải trỏ vào ĐÚNG chunk mà retriever có khả năng trả
về, kèm offset trên `payload["text"]` (KHÔNG phải trên text đã embed — text đã embed
có thêm header của build_text_unit, xem §10.1 R3).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, asdict

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


def _norm_filter(norm_id: str):
    # Import TRỄ: `qdrant_client` chỉ cần khi thật sự quét index. Để ở tầng module thì
    # `import generator.g7_content` cũng kéo theo nó, và bộ test không đụng gì tới
    # Qdrant vẫn không chạy được trên máy chưa cài — đúng thứ ROADMAP A3 đang gỡ.
    from qdrant_client import models as qm
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
#
# "thay thế" / "bãi bỏ" KHÔNG dùng làm khoá đơn giản: cả hai đều có nghĩa kép —
#   · "thay thế MỘT SỐ CỤM TỪ/TỪ NGỮ tại <văn bản>" = sửa câu chữ (SUA_DOI thật),
#     khác hẳn "thay thế <văn bản>" = bãi bỏ toàn văn bản.
#   · "bãi bỏ ĐIỀU/KHOẢN/ĐIỂM/CHƯƠNG/MỤC ..." = bãi bỏ nội bộ MỘT PHẦN của chính
#     văn bản đang đọc (tự trỏ), khác hẳn "bãi bỏ <văn bản số hiệu khác>".
# Lẫn nghĩa làm G1-0012: needle 114/2018/NĐ-CP chỉ bị "thay thế cụm từ", nhưng câu
# "Bãi bỏ Điều 25, Điều 26..." đứng trước đó (bãi bỏ điều khoản CỦA CHÍNH văn bản
# 200/2025, không liên quan 114/2018) vẫn được tính là "câu dẫn" vì cùng nằm trước
# needle trong cùng đoạn liệt kê nhiều thao tác sửa/bãi bỏ nhắm vào nhiều văn bản.
_KW_BAI_BO_DON = ("hết hiệu lực", "ngưng hiệu lực")
_RE_THAY_THE_VB = re.compile(
    r"thay\s+thế(?!\s+(?:một\s+số\s+)?(?:cụm\s+từ|từ\s+ngữ)\b)")
_RE_BAI_BO_VB = re.compile(
    r"bãi\s+bỏ(?!\s+(?:điều|khoản|điểm|chương|mục)\b)")
_KW_TIEU_DE = ("hiệu lực", "thi hành", "chuyển tiếp", "bãi bỏ")
MAX_SPAN = 1200

# Văn bản kiểu "Quyết định công bố Danh mục văn bản QPPL hết hiệu lực" liệt kê nhiều
# văn bản theo STT, mỗi mục: <câu dẫn của mục TRƯỚC> \n <ngày> \n <STT> \n <mục hiện
# tại>. Quét ngược từ vị trí số hiệu thì gặp ngay câu dẫn của mục TRƯỚC — sai văn bản.
# Chặn quét ngược tại dòng CHỈ CHỨA MỘT SỐ (STT) gần nhất trước vị trí cần tìm.
_RE_STT_BOUNDARY = re.compile(r"\n\s*\d{1,4}\s*\n")


def _diem_bang_chung(text_low: str, tieu_de_low: str, i: int) -> tuple[int, int | None]:
    """Chấm điểm mức độ 'đây đúng là điều khoản bãi bỏ' + vị trí từ khoá dẫn."""
    diem = 0
    if any(k in tieu_de_low for k in _KW_TIEU_DE):
        diem += 2

    gioi_han = 0
    for m in _RE_STT_BOUNDARY.finditer(text_low, 0, i):
        gioi_han = m.end()                   # không quét ngược qua ranh giới mục

    vi_tri = None
    for k in _KW_BAI_BO_DON:
        p = text_low.rfind(k, gioi_han, i)   # từ khoá đứng TRƯỚC số hiệu -> câu dẫn
        if p >= 0 and (vi_tri is None or p > vi_tri):
            vi_tri = p
    for rx in (_RE_THAY_THE_VB, _RE_BAI_BO_VB):
        p = None
        for m in rx.finditer(text_low, gioi_han, i):
            p = m.start()
        if p is not None and (vi_tri is None or p > vi_tri):
            vi_tri = p

    if vi_tri is not None:
        diem += 3
    else:
        # Nhánh yếu vẫn phải tôn trọng ranh giới mục CẢ HAI PHÍA — không thì mục 46
        # "mượn" điểm từ từ khoá thuộc mục 44/45 phía trước hoặc 47/48 phía sau
        # (G1-0035), dù bản thân không có bằng chứng nào.
        m_sau = _RE_STT_BOUNDARY.search(text_low, i)
        bien_sau = m_sau.start() if m_sau else len(text_low)
        vung = text_low[gioi_han:bien_sau]
        if (any(k in vung for k in _KW_BAI_BO_DON) or _RE_THAY_THE_VB.search(vung)
                or _RE_BAI_BO_VB.search(vung)):
            diem += 1                        # có từ khoá nhưng đứng sau -> yếu hơn
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
        # Không có dấu nào phía sau (câu tận cùng CHUNK, dấu "." cuối không có khoảng
        # trắng theo sau nên ". " không khớp) -> lấy hết phần còn lại của chunk, để
        # MAX_SPAN (cắt từ ĐẦU span) lo phần quá dài, thay vì cắt cứng 200 ký tự và
        # mất đúng vế "...hết hiệu lực..." nằm ngay sau đó (G1-0048).
        sau = i + len(needle)
        cands = [x for x in (text.find("\n", sau), text.find("; ", sau),
                             text.find(". ", sau)) if x >= 0]
        end = (min(cands) + 1) if cands else len(text)
        m_bien = _RE_STT_BOUNDARY.search(text.lower(), sau)
        if m_bien and m_bien.start() < end:      # đừng lấn sang mục STT kế tiếp
            end = m_bien.start() + 1
        if end - start > MAX_SPAN:
            start = max(start, end - MAX_SPAN)

        span = GoldSpan(expr_id=expr_id, part=part, chunk_id=str(p.id),
                        start=start, end=end,
                        chunk_text_sha256=content_hash(text),
                        text=text[start:end].strip())
        if tot is None or diem > tot[1]:
            tot = (span, diem)
    return (tot[0], tot[1]) if tot else (None, 0)


def chunk_span(store, expr_id: str, part: int = 0) -> tuple[GoldSpan | None, dict]:
    """Lấy TRỌN chunk làm span — dùng cho G7, nơi đáp án chính là nội dung điều luật.

    Trả (span, payload). Payload để bên gọi lọc thêm (n_parts, tiêu đề, độ dài).
    """
    pid = point_id(expr_id, part)
    pts = store.client.retrieve(store.collection, ids=[pid], with_payload=True)
    if not pts:
        return None, {}
    pl = pts[0].payload or {}
    text = pl.get("text") or ""
    if not text:
        return None, pl
    return GoldSpan(expr_id=expr_id, part=part, chunk_id=pid,
                    start=0, end=len(text),
                    chunk_text_sha256=content_hash(text),
                    text=text), pl


_WS = re.compile(r"\s+")


def _chuan(s: str) -> str:
    return _WS.sub(" ", (s or "").strip()).casefold()


def chunk_span_khop(store, expr_id: str, needle: str) -> tuple[GoldSpan | None, dict]:
    """Như `chunk_span`, nhưng khi Điều bị chẻ thành NHIỀU `part` thì chọn part CHỨA
    `needle`, không mặc định lấy part 0.

    Bài học G5-0004: `TransitionRule` trích từ một khoản cụ thể trong Điều, nhưng
    Điều dài có thể chẻ thành 2-3 part trên Qdrant (payload có sẵn `n_parts`) — khoản
    đó có thể nằm ở part 1, trong khi lấy cứng part 0 cho ra ngữ cảnh nói về một
    khoản HOÀN TOÀN KHÁC. `needle` = chuỗi `ap_dung` (hay tiền tố của nó) đã trích.
    """
    pid0 = point_id(expr_id, 0)
    pts = store.client.retrieve(store.collection, ids=[pid0], with_payload=True)
    if not pts:
        return None, {}
    pl0 = pts[0].payload or {}
    n_parts = int(pl0.get("n_parts") or 1)

    can = _chuan(needle)[:80]           # tiền tố đủ dài để không khớp bừa, đủ ngắn để
    if can:                              # chịu được khác biệt nhỏ cuối câu do LLM diễn giải
        for part in range(n_parts):
            pl = pl0 if part == 0 else (
                (store.client.retrieve(store.collection, ids=[point_id(expr_id, part)],
                                       with_payload=True) or [None])[0])
            pl = pl.payload if hasattr(pl, "payload") else pl
            if not pl:
                continue
            text = pl.get("text") or ""
            if can in _chuan(text):
                return GoldSpan(expr_id=expr_id, part=part,
                                chunk_id=point_id(expr_id, part), start=0, end=len(text),
                                chunk_text_sha256=content_hash(text), text=text), pl

    # Không part nào chứa needle (khác biệt diễn giải quá lớn, hoặc chưa index) ->
    # lùi về hành vi cũ (part 0) thay vì bỏ item, evidence lúc đó yếu hơn nhưng còn.
    return chunk_span(store, expr_id, 0)


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
