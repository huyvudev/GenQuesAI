"""Tầng 2 — diễn đạt lại câu hỏi (§3 của tài liệu thiết kế).

Đây là chỗ DUY NHẤT trong bộ sinh có LLM, và nó chỉ chạm vào `user_input`.
LLM không thấy đáp án, không thấy span, không ghi được vào trường nào khác —
xem bất biến I1/I3. Đầu ra bị chặn ngay bởi cổng C2 ở dưới.
"""
from __future__ import annotations

import re


SYSTEM = """Bạn viết lại câu hỏi pháp lý cho tự nhiên như người dân thật hỏi.

QUY TẮC BẮT BUỘC:
- Chỉ đổi CÁCH DIỄN ĐẠT. Tuyệt đối KHÔNG thêm bất kỳ số hiệu văn bản, ngày tháng,
  số Điều/Khoản/Điểm, tên cơ quan, hay con số nào không có trong câu gốc.
- KHÔNG trả lời câu hỏi. Chỉ viết lại chính câu hỏi đó.
- Giữ nguyên chủ đề. Không mở rộng, không thu hẹp.
- Viết 1 câu, tiếng Việt, giọng người đi hỏi thủ tục.
- Chỉ xuất ra câu hỏi, không giải thích, không dấu ngoặc kép."""

GIONG = {
    "chu_ho_kinh_doanh": "Bạn là chủ hộ kinh doanh nhỏ, không rành thuật ngữ luật.",
    "nguoi_dan": "Bạn là người dân bình thường, hỏi ngắn gọn.",
    "can_bo_phap_che": "Bạn là cán bộ pháp chế doanh nghiệp, hỏi chính xác.",
    "luat_su": "Bạn là luật sư, hỏi có trọng tâm.",
}

# ── C2: tập thực thể phải bảo toàn (§I3) ────────────────────────────────────
_ENT = [
    re.compile(r"\d+[a-zA-Z]?/\d{4}/[A-ZĐ][A-ZĐ0-9\-]*"),          # số hiệu
    re.compile(r"\b\d{1,2}[/-]\d{1,2}[/-]\d{4}\b"),                 # ngày
    re.compile(r"(?i)\b(?:điều|khoản|điểm)\s+\d+[a-zA-Z]?\b"),      # tham chiếu
    re.compile(r"\b\d[\d.,]{2,}\b"),                                # con số định lượng
]


_NGAY = re.compile(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{4})\b")


def _chuan_hoa(s: str) -> str:
    """'04/11/2020' và '4/11/2020' là CÙNG một ngày — không chuẩn hoá thì C2 báo
    động giả, loại oan bản viết lại chỉ vì LLM bỏ số 0 đứng đầu."""
    return _NGAY.sub(lambda m: f"{int(m[1])}/{int(m[2])}/{m[3]}", s or "")


def entities(s: str) -> set[str]:
    s = _chuan_hoa(s)
    out: set[str] = set()
    for rx in _ENT:
        out |= {m.group(0).lower() for m in rx.finditer(s)}
    return out


def gate_c2(goc: str, moi: str) -> tuple[bool, str]:
    """Thực thể MỚI xuất hiện ⇒ loại thẳng. Thực thể biến mất ⇒ hợp lệ (cố ý lược bỏ).

    Không sửa, không thử lại: câu bị loại là câu rẻ, câu sai lọt lưới là câu đắt.
    """
    if not moi or len(moi) < 8:
        return False, "qua_ngan"
    them = entities(moi) - entities(goc)
    if them:
        return False, f"them_thuc_the:{','.join(sorted(them))[:60]}"
    # Chỉ đòi dấu hỏi khi bản GỐC có dấu hỏi. Khuôn "Tôi cần biết quy định về ..."
    # vốn là câu trần thuật — bắt bản viết lại phải có '?' là loại oan chính khuôn
    # của mình. Rủi ro thật cần chặn là LLM đi TRẢ LỜI thay vì viết lại; dấu hiệu
    # của việc đó là bản mới dài bất thường, nên đo bằng tỷ lệ độ dài.
    if "?" in goc and "?" not in moi:
        return False, "mat_dang_cau_hoi"
    if len(moi) > max(2.5 * len(goc), len(goc) + 120):
        return False, "qua_dai_nghi_da_tra_loi"
    return True, "pass"


def make_llm():
    from genquesai.legal_rag.agent.llm import LLM
    from .common import _settings
    return LLM(settings=_settings())


def viet_lai(llm, cau_goc: str, persona: str) -> str:
    user = f"{GIONG.get(persona, '')}\n\nCâu hỏi cần viết lại:\n{cau_goc}"
    return llm.chat(SYSTEM, user, temperature=0.7, max_tokens=120).strip().strip('"')
