"""A2 — đối chiếu gold span với phần truy hồi theo NỘI DUNG, không theo id.

Vì sao phải có tầng này
───────────────────────
`chunk_id` trong bộ đề là `point_id(expr_id, part)` — id Qdrant của `legal-rag`, vô
nghĩa với mọi hệ khác. Chấm recall bằng id thì công cụ chỉ đo được đúng MỘT hệ: hệ
dùng chung index với `legal-rag`. Với hệ hộp đen (chỉ trả `answer` + đoạn văn bản),
id thậm chí không tồn tại.

Đối chiếu nội dung: gold span là CHUỖI NGUYÊN VĂN cắt từ văn bản luật; hệ được đo trả
về các đoạn nguyên văn nó đã lấy. Câu hỏi "nội dung gold có được lấy về không" trả lời
được bằng chồng lấn chuỗi — không cần hai bên thoả thuận gì về id hay cách chunk.

Cách đo: CỬA SỔ TRƯỢT, không phải so bằng
─────────────────────────────────────────
Hệ khác chunk khác cách: span của bộ đề có thể nằm gọn trong một đoạn của họ, có thể
vắt ngang hai đoạn, đoạn của họ có thể kèm header/metadata. So bằng hay `in` cả chuỗi
đều gãy ngay ca đầu tiên. Thay vào đó:

    chuẩn hoá (gộp khoảng trắng, casefold)
    cắt span thành các cửa sổ CO ký tự, bước CO/2
    điểm = tỷ lệ cửa sổ xuất hiện trong văn bản đối chiếu

Tính chất được chọn có chủ đích:
  · span nằm gọn trong một đoạn -> điểm 1.0, bất kể đoạn đó dài hơn bao nhiêu
  · span vắt ngang hai đoạn      -> mỗi đoạn phủ một phần; đo trên UNION các đoạn
    thì vẫn ~1.0 — đúng ngữ nghĩa "nội dung ĐÃ được lấy về"
  · đoạn nói cùng chủ đề nhưng KHÁC văn bản -> các cửa sổ 64 ký tự gần như không
    trùng nguyên văn -> điểm ~0. Văn bản luật trùng nhau từng đoạn 64 ký tự là
    chuyện hiếm, và đó chính là lý do chọn cửa sổ dài thay vì token đơn lẻ.

Recall vì thế thành LIÊN TỤC thay vì nhị phân — ROADMAP A2 gọi đây là thay đổi chấp
nhận được và phản ánh đúng hơn.

`chunk_id` vẫn là ĐƯỜNG NHANH tuỳ chọn: hai bên chung không gian id thì so id trước,
trúng là khỏi đo chuỗi. Sai lệch duy nhất id bắt được mà nội dung không bắt được —
"id còn nguyên nhưng text đã đổi" — đã có hash của cổng C1 lo.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# 64 ký tự sau chuẩn hoá ~ 12-15 tiếng Việt — đủ dài để không khớp bừa giữa hai văn
# bản cùng chủ đề, đủ ngắn để span 139 ký tự (ngắn nhất trong bộ đề) vẫn ra >=3 cửa sổ.
CO_CUA_SO = 64
NGUONG_KHOP = 0.60          # >=60% cửa sổ tìm thấy -> tính là "đã lấy về"

_WS = re.compile(r"\s+")


def chuan(s: str | None) -> str:
    return _WS.sub(" ", (s or "").strip()).casefold()


def _cua_so(span_chuan: str) -> list[str]:
    if not span_chuan:
        return []
    if len(span_chuan) <= CO_CUA_SO:
        return [span_chuan]
    buoc = CO_CUA_SO // 2
    ra = [span_chuan[i:i + CO_CUA_SO]
          for i in range(0, len(span_chuan) - CO_CUA_SO + 1, buoc)]
    # cửa sổ chót phủ tận cuối span — không có nó thì đuôi span không được đo
    if not span_chuan.endswith(ra[-1]):
        ra.append(span_chuan[-CO_CUA_SO:])
    return ra


def do_phu(span: str, van_ban: str) -> float:
    """Tỷ lệ nội dung `span` xuất hiện trong `van_ban`. 0..1."""
    cs = _cua_so(chuan(span))
    if not cs:
        return 0.0
    vb = chuan(van_ban)
    return sum(1 for c in cs if c in vb) / len(cs)


@dataclass(slots=True)
class KetQuaDoiChieu:
    diem: float               # độ phủ tốt nhất đạt được (union nếu vắt ngang)
    hang: int | None          # hạng của đoạn ĐƠN LẺ tốt nhất đạt ngưỡng; None = không
    khop: bool                # diem >= NGUONG_KHOP


def doi_chieu(span: str, contexts: list[str],
              nguong: float = NGUONG_KHOP) -> KetQuaDoiChieu:
    """Span có nằm trong các đoạn hệ đã trả về không?

    Hai phép đo, hai mục đích — đừng gộp:
      `diem` đo trên UNION các đoạn: span vắt ngang hai đoạn kề nhau vẫn được tính
        đủ, vì câu hỏi là "nội dung có được lấy về KHÔNG".
      `hang` là đoạn ĐƠN LẺ sớm nhất tự nó đạt ngưỡng, vì câu hỏi của triage là
        "đoạn chứa đáp án đứng thứ mấy" — union không có thứ hạng.
    """
    cs = _cua_so(chuan(span))
    if not cs or not contexts:
        return KetQuaDoiChieu(0.0, None, False)

    hang = None
    con_thieu = set(range(len(cs)))
    for i, ctx in enumerate(contexts):
        vb = chuan(ctx)
        trung = [j for j in con_thieu if cs[j] in vb]
        if hang is None and sum(1 for c in cs if c in vb) / len(cs) >= nguong:
            hang = i
        con_thieu.difference_update(trung)
        if not con_thieu and hang is not None:
            break
    diem = 1.0 - len(con_thieu) / len(cs)
    return KetQuaDoiChieu(diem, hang, diem >= nguong)


def doi_chieu_gold(gold_spans: list[dict], gold_texts: list[str],
                   retrieved_ids: list[str], retrieved_contexts: list[str],
                   k: int, nguong: float = NGUONG_KHOP) -> list[KetQuaDoiChieu]:
    """Đối chiếu từng gold span với top-k phần truy hồi. Một kết quả cho mỗi span.

    Đường NHANH theo id chạy trước: hai bên chung không gian id (hộp trắng legal-rag)
    thì id trúng là điểm 1.0 tại đúng hạng đó — rẻ và chính xác tuyệt đối. Trượt id
    (hệ khác, hoặc hộp đen không có id) thì rơi xuống đường NỘI DUNG.

    `gold_texts` là `reference_contexts` của bộ đề — chuỗi nguyên văn của từng span,
    cùng thứ tự với `gold_spans`.
    """
    ids_k = retrieved_ids[:k] if retrieved_ids else []
    ctx_k = retrieved_contexts[:k] if retrieved_contexts else []
    ra: list[KetQuaDoiChieu] = []
    for i, g in enumerate(gold_spans):
        cid = (g or {}).get("chunk_id")
        if cid and cid in ids_k:
            ra.append(KetQuaDoiChieu(1.0, ids_k.index(cid), True))
            continue
        text = gold_texts[i] if i < len(gold_texts) else ""
        ra.append(doi_chieu(text, ctx_k, nguong))
    return ra
