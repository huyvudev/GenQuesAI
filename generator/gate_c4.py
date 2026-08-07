"""Cổng C4 — kiểm CẦN THIẾT (bất biến I4b).

Hỏi lại đúng câu đó nhưng **không kèm ngữ cảnh**. Mô hình vẫn trả lời đúng bằng kiến
thức sẵn có ⇒ câu này không đo retrieval ⇒ hạ nhóm (§2: "Trượt thì → Hạ nhóm").

Ragas không có bước này, và thiếu nó thì điểm retrieval bị thổi phồng — với luật VN
càng đúng, vì nhiều điều khoản phổ biến đã nằm trong tham số mô hình.

KHÔNG áp dụng cho G6/G8: mục tiêu của hai nhóm đó vốn LÀ từ chối, nên "mô hình không
trả lời được" là hành vi mong muốn chứ không phải tín hiệu về retrieval.
"""
from __future__ import annotations

import re
import unicodedata
from concurrent.futures import ThreadPoolExecutor

from .common import core_so_hieu

BO_QUA_NHOM = {"G6", "G8"}
NGUONG_TRUNG = 0.50          # F1 token giữa câu trả lời không-ngữ-cảnh và reference

SYSTEM = """Bạn trả lời câu hỏi pháp luật Việt Nam CHỈ bằng kiến thức sẵn có của mình.

- Không có tài liệu nào được cung cấp.
- Nếu bạn không chắc chắn, trả lời đúng hai chữ: KHÔNG BIẾT
- Không suy đoán, không nói chung chung. Thà nói KHÔNG BIẾT còn hơn đoán.
- Trả lời ngắn gọn, tối đa 3 câu."""

_TU = re.compile(r"[0-9a-zA-ZđĐàáâãèéêìíòóôõùúăđĩũơưăạảấầẩẫậắằẳẵặẹẻẽếềể"
                 r"ễệỉịọỏốồổỗộớờởỡợụủứừửữựỳỵỷỹý]+", re.IGNORECASE)


def _chuan(s: str) -> str:
    return unicodedata.normalize("NFC", (s or "").lower())


def _tokens(s: str) -> set[str]:
    return {t for t in _TU.findall(_chuan(s)) if len(t) > 2}


def _f1_tru(a: str, b: str, bo: set[str]) -> float:
    """F1 token sau khi LOẠI tập `bo` khỏi cả hai vế — dùng để trừ phần câu hỏi
    đã cho sẵn, chỉ còn đo phần mô hình tự bổ sung."""
    ta, tb = _tokens(a) - bo, _tokens(b) - bo
    if not ta or not tb:
        return 0.0
    chung = len(ta & tb)
    if not chung:
        return 0.0
    p, r = chung / len(ta), chung / len(tb)
    return 2 * p * r / (p + r)


def _f1(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    chung = len(ta & tb)
    if not chung:
        return 0.0
    p, r = chung / len(ta), chung / len(tb)
    return 2 * p * r / (p + r)


def _tu_choi(tra_loi: str) -> bool:
    t = _chuan(tra_loi)
    return ("không biết" in t or "khong biet" in t or "không rõ" in t
            or "không chắc" in t or len(t.strip()) < 8)


def cham(item: dict, tra_loi: str) -> tuple[str, float]:
    """Trả (kết luận, điểm). 'leak' = mô hình tự trả lời đúng ⇒ câu không đo retrieval.

    NGUYÊN TẮC CHI PHỐI: chỉ tính những gì mô hình **tự cung cấp thêm**. Mọi thứ CÂU
    HỎI ĐÃ CHO SẴN đều phải trừ đi, nếu không grader sẽ tự lừa mình:

    · G5 hỏi "Theo {số hiệu}, …" ⇒ số hiệu có sẵn trong câu hỏi. Thấy nó trong câu
      trả lời không chứng minh gì. Bản grader đầu tiên chấm 6/6 ca G5 là leak với
      điểm 1.0 đúng vì lỗi này — trong khi mô hình dẫn sai Điều (18 thay vì 218).
    · Tiếng Việt pháp lý dùng chung rất nhiều từ vựng, và câu hỏi tự nó đã chứa phần
      lớn từ khoá chủ đề. So F1 thô thì một câu trả lời chung chung cũng vượt ngưỡng.
    """
    if _tu_choi(tra_loi):
        return "pass", 0.0
    rt = item.get("reference_type")
    rf = item.get("reference_fields") or {}
    hoi = _chuan(item.get("user_input", ""))

    if rt in ("field", "composed"):
        muc_tieu = [rf.get("norm_id_hieu_luc"), rf.get("so_hieu"),
                    core_so_hieu(item.get("reference", ""))]
        # Chỉ giữ định danh KHÔNG có sẵn trong câu hỏi.
        muc_tieu = [x for x in muc_tieu if x and x.lower() not in hoi]
        if muc_tieu:
            trung = any(m.lower() in _chuan(tra_loi) for m in muc_tieu)
            return ("leak" if trung else "pass"), 1.0 if trung else 0.0
        nhan = (rf.get("nhan") or "").lower()
        if nhan:
            # G3 nhị phân — base rate cao, xem cảnh báo ở run_c4.py
            t = _chuan(tra_loi)
            doan = ("không" in t[:40]) if nhan == "không" else ("có" in t[:40])
            return ("leak" if doan else "pass"), 1.0 if doan else 0.0
        # Định danh đã có sẵn trong câu hỏi -> rơi xuống so nội dung bên dưới.

    if rt == "field[]":
        ds = [x for x in (rf.get("danh_sach") or []) if x.lower() not in hoi]
        if ds:
            trung = sum(1 for x in ds if x.lower() in _chuan(tra_loi))
            ty = trung / len(ds)
            return ("leak" if ty >= 0.5 else "pass"), ty

    # Nội dung: F1 token SAU KHI trừ token đã có trong câu hỏi.
    bo = _tokens(hoi)
    diem = _f1_tru(tra_loi, item.get("reference", ""), bo)
    return ("leak" if diem >= NGUONG_TRUNG else "pass"), round(diem, 3)


def chay(items: list[dict], llm, workers: int = 4, log=print) -> dict:
    can = [it for it in items if it.get("group") not in BO_QUA_NHOM]

    def mot(it):
        try:
            tl = llm.chat(SYSTEM, it["user_input"], temperature=0.0, max_tokens=220)
        except Exception as ex:
            return it, None, f"loi_api:{type(ex).__name__}", 0.0
        kl, diem = cham(it, tl)
        return it, tl, kl, diem

    st = {"kiem": 0, "pass": 0, "leak": 0, "loi_api": 0}
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for i, (it, tl, kl, diem) in enumerate(ex.map(mot, can), 1):
            if kl.startswith("loi_api"):
                it["gates"]["C4"] = kl
                st["loi_api"] += 1
                continue
            st["kiem"] += 1
            st[kl] += 1
            it["gates"]["C4"] = kl
            it["c4_diem"] = diem
            it["c4_tra_loi_khong_ngu_canh"] = tl
            if kl == "leak":
                # §2: trượt C4 -> HẠ NHÓM, không xoá. Câu vẫn dùng được để đo
                # synthesis, chỉ không còn là bằng chứng về retrieval.
                it["difficulty"] = "easy"
                it["do_retrieval"] = False
            else:
                it["do_retrieval"] = True
            if i % 50 == 0:
                log(f"  ...{i}/{len(can)}")
    for it in items:
        if it.get("group") in BO_QUA_NHOM:
            it["gates"]["C4"] = "n/a_muc_tieu_la_tu_choi"
    return st
