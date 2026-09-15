"""Bước 5 (tuỳ chọn, sau Bước 4) — sinh biến thể ngôn ngữ "người dùng thật" cho mỗi
câu đã duyệt xong. Mục đích: bộ câu hỏi do LLM tự sinh luôn quá "sạch" (đúng thuật
ngữ pháp lý, đúng số Điều) — người dùng thật (dân, doanh nghiệp không chuyên) hỏi
lủng củng, sai/thiếu thuật ngữ, không nhớ số hiệu văn bản. Test theo văn phong đó
mới đo được độ bền (robustness) thật của RAG với người dùng không chuyên.

Thiết kế (thảo luận 2026-09-15):
- Chạy SAU Bước 4 (chỉ trên câu đã qua hết mọi vòng duyệt) — biến thể chỉ đổi CÁCH
  HỎI, KHÔNG đổi `question`/`answer` gốc (giữ nguyên làm bản "chuẩn"), tránh phải
  chạy lại omission-test/quality_gate nặng cho từng biến thể.
- 2 mức, không nổ tổ hợp: `doi_thuong` (văn phong người dân, không dùng đúng thuật
  ngữ/số Điều) và `mo_ho` (cố ý sai/thiếu 1 chi tiết nhỏ, KHÔNG được đổi bản chất
  tình huống khiến đáp án gốc sai).
- Kiểm tra nhẹ 1 lệnh LLM/biến thể (không phải toàn bộ Bước 3) — chỉ xác nhận biến
  thể còn hỏi đúng cùng vấn đề pháp lý như câu gốc, loại nếu không.
"""
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor

_SYS = ("Bạn đóng vai người dân/doanh nghiệp Việt Nam KHÔNG có chuyên môn pháp luật, "
       "đang cần hỏi 1 câu hỏi pháp lý. Chỉ trả JSON hợp lệ, không giải thích thêm.")

_MUC_DO = {
    "doi_thuong": (
        "Viết lại CÂU HỎI sau theo văn phong người dân bình thường hỏi luật sư/tổng đài tư "
        "vấn — mô tả tình huống bằng ngôn ngữ đời thường, KHÔNG dùng đúng thuật ngữ pháp lý "
        "chuyên ngành (vd thay 'cố ý gây thương tích' bằng 'đánh người bị thương'), KHÔNG "
        "nêu số Điều/Khoản hay số hiệu văn bản cụ thể. Có thể hỏi hơi vòng vo, kể tình huống "
        "trước rồi mới hỏi.\n\n"
        "TUYỆT ĐỐI không đổi bản chất tình huống pháp lý — ĐÁP ÁN GỐC bên dưới phải vẫn trả "
        "lời đúng cho câu hỏi mới."),
    "mo_ho": (
        "Viết lại CÂU HỎI sau nhưng cố ý dùng SAI hoặc GẦN ĐÚNG 1 thuật ngữ pháp lý (vd nhầm "
        "'khởi tố' thành 'khởi kiện', nhầm 'bãi bỏ' thành 'huỷ bỏ'), hoặc bỏ bớt 1 chi tiết "
        "phụ khiến câu hỏi hơi mơ hồ — mô phỏng người hỏi không chắc chắn thuật ngữ.\n\n"
        "TUYỆT ĐỐI không đổi bản chất tình huống pháp lý và KHÔNG được mơ hồ tới mức đáp án "
        "gốc không còn áp dụng đúng — ĐÁP ÁN GỐC bên dưới phải vẫn trả lời đúng cho câu hỏi mới."),
}

_P_BIEN_THE = """{huong_dan}

CÂU HỎI GỐC:
{q}

ĐÁP ÁN GỐC (chỉ để bạn hiểu ngữ cảnh, KHÔNG lặp lại trong câu hỏi):
{a}

Trả JSON: {{"cau_hoi_bien_the": "..."}}"""

_P_KIEM_TRA = """Câu hỏi BIẾN THỂ dưới đây có còn hỏi ĐÚNG CÙNG 1 vấn đề pháp lý như câu hỏi GỐC
không — tức ĐÁP ÁN GỐC có còn trả lời đúng, đầy đủ cho câu hỏi biến thể không?

CÂU HỎI GỐC: {q_goc}
CÂU HỎI BIẾN THỂ: {q_bt}
ĐÁP ÁN GỐC: {a}

Trả JSON: {{"con_dung_dap_an_goc": <true|false>}}"""


def _map_limit(fn, items, workers: int) -> list:
    if not items:
        return []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(fn, items))


def sinh_bien_the_ngon_ngu(llm, rows: list[dict], workers: int = 8, llm_kiem_tra=None) -> tuple[list[dict], dict]:
    """Bước 5 — thêm field `bien_the_ngon_ngu` (list[{"muc_do","cau_hoi"}]) vào mỗi
    dòng trong `rows`. KHÔNG loại bỏ dòng nào khỏi `rows` — chỉ bổ sung field; biến
    thể không xác nhận được (lỗi LLM hoặc lệch nghĩa) bị bỏ khỏi list biến thể của
    riêng dòng đó, không ảnh hưởng tới câu hỏi gốc.

    `llm` sinh biến thể (nên dùng model SINH, giống Bước 2); `llm_kiem_tra` (tuỳ
    chọn, mặc định dùng lại `llm`) chấm lại xem biến thể còn đúng nghĩa không — nên
    truyền model KHÁC (vd `llm_verify` của Bước 3) để giữ đúng tinh thần "đồng thuận
    đa nguồn" xuyên suốt dự án, không bắt buộc."""
    if not rows:
        return rows, {"cau_can_bien_the": 0, "bien_the_sinh": 0, "bien_the_loai": 0}
    llm_kt = llm_kiem_tra or llm

    def _xu_ly(r: dict) -> list[dict]:
        bien_the = []
        for muc_do, huong_dan in _MUC_DO.items():
            out = llm.chat_json(_SYS, _P_BIEN_THE.format(huong_dan=huong_dan, q=r["question"],
                                                          a=r["answer"][:1500]),
                                temperature=0.7, max_tokens=400)
            cau_hoi_bt = (out.get("cau_hoi_bien_the") or "").strip() if out else ""
            if not cau_hoi_bt:
                continue
            kt = llm_kt.chat_json(_SYS, _P_KIEM_TRA.format(q_goc=r["question"], q_bt=cau_hoi_bt,
                                                           a=r["answer"][:1500]),
                                  temperature=0.0, max_tokens=50)
            if kt and kt.get("con_dung_dap_an_goc"):
                bien_the.append({"muc_do": muc_do, "cau_hoi": cau_hoi_bt})
        return bien_the

    ket_qua = _map_limit(_xu_ly, rows, workers)
    tong_sinh = tong_loai = 0
    for r, bien_the in zip(rows, ket_qua):
        r["bien_the_ngon_ngu"] = bien_the
        tong_sinh += len(bien_the)
        tong_loai += len(_MUC_DO) - len(bien_the)
    return rows, {"cau_can_bien_the": len(rows), "bien_the_sinh": tong_sinh, "bien_the_loai": tong_loai}
