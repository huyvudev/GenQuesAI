"""Grader thuần — chấm một kết quả `ask()` theo `expect`. Không LLM, không DB.

NGUỒN: chép từ `legal_rag/evaluation/grader.py` của dự án `legal-rag`
(`D:/Project/Chatbot-Law/chatbot`), giữ nguyên 4 chiều và tên từng check để số liệu
đo trước đây vẫn so được.

Vì sao chép mà không import: framework phải cài được trên máy KHÔNG có `Chatbot-Law`.
Phụ thuộc vào repo của một dự án cụ thể thì không ai ngoài dự án đó dùng được.

Khác bản gốc ở ba chỗ, đều là thứ bản gốc không cần vì nó chấm bộ golden viết tay:

  · `norms_include` thêm chế độ Set-F1 (`grade_set`) — bản gốc dùng `all(...)` nên
    thiếu 1 trong 5 văn bản là 0 điểm. Câu hỏi danh sách cần phạt theo mức độ, nếu
    không thì hệ tiến bộ mà chỉ số không nhúc nhích.
  · so khớp số hiệu chuẩn hoá hai đầu (bản gốc so chuỗi con thô).
  · `REFUSAL_MARKERS` tách thành hằng số công khai để adapter khác bổ sung được.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from . import so_hieu as _sh

# Cụm từ cho thấy hệ TỪ CHỐI / không kết luận. Danh sách này phụ thuộc cách hành văn
# của từng hệ — framework cho phép mở rộng thay vì bắt mọi hệ nói giống nhau.
REFUSAL_MARKERS: tuple[str, ...] = (
    "ngoài phạm vi",
    "không đủ cơ sở",
    "chưa đủ cơ sở",
    "chưa xác định",
    "không tìm thấy quy định",
    "không có thông tin",
    "không tìm thấy văn bản",
)

# Mẫu CŨ — chỉ khuôn `số/NĂM-4-CHỮ-SỐ/ký hiệu`. Giữ lại cho `che_do="cu"`, KHÔNG phải
# vì nó đúng mà vì các mốc baseline đã lưu được chấm bằng nó; bỏ đi là mất khả năng so
# hồi quy. Hai chỗ nó sai, đã đo trên corpus thật:
#   · mù 47% số hiệu — mọi dạng không mang năm ở giữa (`01/CT-TTg`, `76-TC/TCDN`)
#   · CẮT CỤT — `01/2005/TTLT/BCA-BLĐTBXH` -> `01/2005/TTLT`, và 498 lõi bị 1.056 văn
#     bản dùng chung ⇒ hai văn bản khác nhau được chấm là bằng nhau
# `che_do="moi"` dùng `framework.so_hieu`, đã đo đọc được 99%.
_SO_HIEU = re.compile(r"\d+[a-zA-Z]?/\d{4}/[A-ZĐ][A-ZĐ0-9\-]*", re.IGNORECASE)


@dataclass(slots=True)
class Check:
    dimension: str            # citation | validity | content | behavior
    name: str
    passed: bool
    score: float | None = None   # None = nhị phân; có giá trị = chấm liên tục


def chuan_so_hieu(s: str | None, moi: bool = False) -> str | None:
    """'Nghị định 15/2018/NĐ-CP' -> '15/2018/nđ-cp'.

    Chuẩn hoá hai đầu trước khi so là bắt buộc với framework: bộ chuẩn ghi
    `15/2018/NĐ-CP` còn corpus của họ có thể ghi `Nghị định 15/2018/NĐ-CP`. So chuỗi
    thô thì hệ bị chấm sai vì CÁCH GHI, không phải vì chất lượng.

    `moi=True` dùng `framework.so_hieu` — đọc được cả dạng không mang năm và không cắt
    cụt ký hiệu ghép. Mặc định vẫn là mẫu cũ để `che_do="cu"` giữ nguyên ngữ nghĩa.
    """
    if moi:
        return _sh.khoa(s)
    if not s:
        return None
    m = _SO_HIEU.search(s)
    return m.group(0).lower() if m else None


def is_refusal(answer: str, markers: tuple[str, ...] = REFUSAL_MARKERS) -> bool:
    a = (answer or "").lower()
    return any(m in a for m in markers)


# Chế độ CŨ: đúng ngữ nghĩa `legal_rag/evaluation/grader.py` bản gốc. Giữ lại để các
# lần đo trước vẫn so được — một framework mà thước đo lặng lẽ đổi giữa các phiên bản
# thì không dùng để theo dõi tiến bộ được. Đổi chế độ phải là hành động CÓ Ý THỨC.
MARKERS_CU: tuple[str, ...] = REFUSAL_MARKERS[:5]


def _neu_ra(result: dict, hop_den: bool = True, moi: bool = False) -> set[str]:
    """Số hiệu hệ nêu ra — gộp `focus_norms` và `citations`, đã chuẩn hoá.

    `hop_den=True` vớt thêm số hiệu ngay trong câu trả lời: hệ hộp đen không nêu
    `citations` có cấu trúc, không vớt thì mọi check citation của chúng đều trượt.
    """
    out: set[str] = set()
    for khoa in ("focus_norms", "citations"):
        for x in result.get(khoa, []) or []:
            if (sh := chuan_so_hieu(x.get("so_hieu"), moi)):
                out.add(sh)
    if hop_den:
        if moi:
            # `tim_tat_ca` che vùng đã khớp mẫu có-năm trước khi chạy mẫu không-năm,
            # nếu không `99/2021/NĐ-CP` đẻ ra bóng ma `2021/NĐ-CP` — và bóng ma đó lọt
            # vào tập "số hiệu hệ đã nêu", làm check `not_governing` báo sai.
            out.update(x.casefold() for x in _sh.tim_tat_ca(result.get("answer", "")))
        else:
            for m in _SO_HIEU.finditer(result.get("answer", "") or ""):
                out.add(m.group(0).lower())
    return out


def _co_bat_ky(text: str, needles: list[str]) -> bool:
    t = (text or "").lower()
    return any(n.lower() in t for n in needles)


def _f1(du_doan: set, that: set) -> float:
    if not that:
        return 1.0 if not du_doan else 0.0
    c = len(du_doan & that)
    if not c:
        return 0.0
    p, r = c / len(du_doan), c / len(that)
    return 2 * p * r / (p + r)


def grade(result: dict, expect: dict, set_f1_cho: set[str] = frozenset(),
          che_do: str = "moi") -> list[Check]:
    """Chấm một ca. Chỉ kiểm những khoá CÓ MẶT trong `expect`.

    `set_f1_cho`: tên các khoá chấm bằng Set-F1 thay vì all-or-nothing.
    `che_do`: "moi" (mặc định) hoặc "cu" — "cu" tái lập đúng ngữ nghĩa grader gốc của
    `legal-rag`, để so được với các lần đo đã lưu. Ba khác biệt giữa hai chế độ:
    vớt số hiệu trong câu trả lời (hộp đen), danh sách cụm từ từ chối, và Set-F1.
    """
    cu = che_do == "cu"
    checks: list[Check] = []
    answer = result.get("answer", "")
    neu_ra = _neu_ra(result, hop_den=not cu, moi=not cu)
    if cu:
        set_f1_cho = frozenset()

    # ── citation ──
    if "norms_include" in expect:
        can = {chuan_so_hieu(x, not cu) or (x or "").lower()
               for x in expect["norms_include"]}
        if "norms_include" in set_f1_cho:
            f = _f1(neu_ra, can)
            checks.append(Check("citation", "norms_include", f >= 0.999, round(f, 3)))
        else:
            checks.append(Check("citation", "norms_include", can <= neu_ra))
    if "dieu_include" in expect:
        cits = " ".join(str(c.get("dieu_khoan", ""))
                        for c in result.get("citations", []) or [])
        # Hệ hộp đen không có `citations` -> tìm trong chính câu trả lời.
        checks.append(Check("citation", "dieu_include",
                            _co_bat_ky(cits or answer, expect["dieu_include"])))

    # ── validity ──
    if "status" in expect:
        checks.append(Check("validity", "status",
                            result.get("status") == expect["status"]))
    if "as_of_date" in expect:
        checks.append(Check("validity", "as_of_date",
                            result.get("as_of_date") == expect["as_of_date"]))
    if "governing_norm" in expect:
        can = chuan_so_hieu(expect["governing_norm"], not cu)
        checks.append(Check("validity", "governing_norm", can in neu_ra))
    if "not_governing" in expect:
        # Văn bản KHÔNG được áp tại mốc hỏi — đây chính là bẫy sai-thời-điểm của G2′.
        cam = chuan_so_hieu(expect["not_governing"], not cu)
        checks.append(Check("validity", "not_governing", cam not in neu_ra))

    # ── content ──
    for khoa in ("answer_contains_any", "answer_mentions_any"):
        if khoa in expect:
            checks.append(Check("content", khoa, _co_bat_ky(answer, expect[khoa])))

    # ── behavior ──
    if "refused" in expect:
        mk = MARKERS_CU if cu else REFUSAL_MARKERS
        checks.append(Check("behavior", "refused",
                            is_refusal(answer, mk) == expect["refused"]))
    if "warnings_include" in expect:
        w = set(result.get("warnings", []) or [])
        checks.append(Check("behavior", "warnings_include",
                            all(x in w for x in expect["warnings_include"])))
    return checks


def aggregate(all_checks: list[Check]) -> dict:
    """Gộp theo chiều + tổng. Trả {chiều: (đạt, tổng, tỷ lệ)}."""
    out: dict = {}
    tp = tn = 0
    for d in ("citation", "validity", "content", "behavior"):
        cs = [c for c in all_checks if c.dimension == d]
        p = sum(1 for c in cs if c.passed)
        out[d] = (p, len(cs), (p / len(cs)) if cs else None)
        tp += p
        tn += len(cs)
    out["overall"] = (tp, tn, (tp / tn) if tn else None)
    return out


def la_loi_quota(e: Exception) -> bool:
    """Lỗi hết quota -> ca BLOCKED, không tính đúng/sai. Chạy lại là đủ điểm."""
    s = f"{type(e).__name__}: {e}".lower()
    return any(k in s for k in ("ratelimit", "rate limit", "429", "quota",
                                "tokens per day", "insufficient_quota"))
