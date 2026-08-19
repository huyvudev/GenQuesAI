"""Chuyển bộ đề 400 câu sang khuôn `cases` của `legal_rag.evaluation`.

KHÔNG dựng tầng chấm song song. `legal-rag` đã có `grader.py` thuần (không LLM, 4
chiều citation/validity/content/behavior) và `runner.py` chịu được hết quota — việc
đúng là đưa bộ đề vào đúng khuôn đó, rồi chỉ bổ sung thứ họ CHƯA có: đo ở cấp chunk.

Khuôn `expect` của họ (grader.py):
    citation : norms_include · dieu_include
    validity : status · as_of_date · governing_norm · not_governing
    content  : answer_contains_any · answer_mentions_any
    behavior : refused · warnings_include

Điểm khớp đẹp nhất là `not_governing`: nó chính là khái niệm "bẫy sai thời điểm" của
G2′ — văn bản KHÔNG được áp tại mốc hỏi. Bên kia đã có sẵn chỗ để kiểm đúng thứ đó.
"""
from __future__ import annotations

import json
import re
from pathlib import Path


def _tu_khoa(text: str, so: int = 6) -> list[str]:
    """Vài cụm lấy từ đáp án, làm proxy `answer_contains_any`.

    Grader bên kia so chuỗi con nên cụm phải đủ dài để không khớp bừa, đủ ngắn để câu
    trả lời viết lại vẫn chứa, và phải là mệnh đề TỬ TẾ — mảnh vụn giữa câu kiểu
    "I Mục 1, khoản ĐI Mục 2 Phụ lục I3 Nghị" thì không câu trả lời nào chứa nổi.
    """
    manh = re.split(r"[;.\n]", text or "")
    ra = []
    for m in manh:
        m = m.strip(" ,:-")
        if not (22 <= len(m) <= 90):
            continue
        if not m[:1].isalpha():                    # bắt đầu giữa chừng -> bỏ
            continue
        if len(m.split()[0]) < 3:                  # "I Mục 1, khoản ĐI…" -> mảnh vụn
            continue
        if len(m.split()) < 4:
            continue
        ra.append(m)
    return ra[:so]


# `duong_dan` dùng dạng không dấu ('Dieu 41'), còn `citations[].dieu_khoan` của hệ
# dùng dạng có dấu ('Điều 41'). Không quy đổi thì `dieu_include` không bao giờ khớp.
_SEG = {"Dieu": "Điều", "Khoan": "Khoản", "Diem": "Điểm", "Chuong": "Chương",
        "Muc": "Mục", "Phan": "Phần", "PhuLuc": "Phụ lục"}


def _dieu_co_dau(duong_dan: str | None) -> str | None:
    if not duong_dan:
        return None
    ra = []
    for seg in duong_dan.split(" > "):
        t = seg.split(" ", 1)
        ra.append(f"{_SEG.get(t[0], t[0])} {t[1]}" if len(t) > 1
                  else _SEG.get(t[0], t[0]))
    return " ".join(ra)


def _dat(ex: dict, khoa: str, gia_tri) -> None:
    """Chỉ đặt kỳ vọng khi CÓ giá trị.

    Danh sách rỗng là bẫy: `_has_any(answer, [])` trả False, nên `answer_contains_any:
    []` biến thành một check LUÔN TRƯỢT — phạt hệ thống vì bộ đề thiếu dữ liệu.
    """
    if gia_tri:
        ex[khoa] = gia_tri


def _case(it: dict) -> dict | None:
    g, rf = it["group"], it.get("reference_fields") or {}
    ex: dict = {}

    if g == "G1":
        ex["norms_include"] = [rf["so_hieu"]]

    elif g == "G2":
        ex["as_of_date"] = it["as_of_date"]
        ex["governing_norm"] = rf["norm_id_hieu_luc"]
        # Phía SAI thời điểm của cùng mốc chuyển giao -> KHÔNG được áp.
        khac = rf["moi"] if rf["norm_id_hieu_luc"] == rf["cu"] else rf["cu"]
        ex["not_governing"] = khac
        if it["reference_type"] == "span":
            _dat(ex, "answer_contains_any", _tu_khoa(it["reference"]))

    elif g == "G3":
        ex["norms_include"] = [rf["con"]]
        ex["answer_contains_any"] = (["còn hiệu lực", "vẫn có hiệu lực"]
                                     if rf["nhan"] == "Có"
                                     else ["hết hiệu lực", "không còn hiệu lực"])

    elif g == "G4":
        ex["norms_include"] = rf["danh_sach"]

    elif g == "G5":
        _dat(ex, "answer_contains_any", _tu_khoa(rf.get("ap_dung", "")))
        ex["norms_include"] = [rf["so_hieu"]]

    elif g == "G6":
        # Đáp án đúng KHÔNG phải một mức cụ thể: nêu cả hai + dẫn nguyên tắc, hoặc
        # từ chối khẳng định. Kiểm hành vi, không kiểm nội dung.
        ex["norms_include"] = [rf["a"], rf["b"]]

    elif g == "G7":
        _dat(ex, "dieu_include", [d] if (d := _dieu_co_dau(rf.get("dieu"))) else None)
        ex["norms_include"] = [rf["so_hieu"]]
        _dat(ex, "answer_contains_any", _tu_khoa(it["reference"]))

    elif g == "G8":
        ex["refused"] = True        # mục tiêu: từ chối, không bịa

    if not ex:
        return None
    return {
        "id": it["id"],
        "category": g,
        "question": it["user_input"],
        "as_of_date": it.get("as_of_date") or None,
        "expect": ex,
        # Phần `legal_rag.grader` không đo — dùng ở score.py
        "_gold_chunks": [s["chunk_id"] for s in it.get("gold_spans", [])],
        # A2: nguyên liệu đối chiếu theo NỘI DUNG — `reference_contexts` là chuỗi
        # nguyên văn của từng span, cùng thứ tự với gold_spans. Nhờ nó, hệ không
        # chung không gian id với legal-rag (hộp đen, chunk khác cách) vẫn đo được
        # recall. `chunk_id` ở trên chỉ còn là đường nhanh.
        "_gold_spans": it.get("gold_spans", []),
        "_gold_texts": it.get("reference_contexts", []),
        "_distractors": it.get("distractor_ids", []),
        # bộ đề hiện tại chưa lưu text bẫy (sinh trước A2) -> rỗng; lần sinh sau
        # bộ sinh sẽ điền, và nhãn `retriever_nham` sẽ hoạt động cả với hộp đen.
        "_distractor_texts": it.get("distractor_texts", []),
        "_reference": it.get("reference", ""),
        "_do_retrieval": it.get("do_retrieval", True),
        "_question_form": it.get("question_form"),
    }


def chuyen(eval_path: Path) -> list[dict]:
    ra = []
    for line in eval_path.open(encoding="utf-8"):
        it = json.loads(line)
        if it.get("status") == "cho_review":
            continue          # G6 chưa duyệt -> không tính vào vòng đánh giá (§4.2)
        c = _case(it)
        if c:
            ra.append(c)
    return ra
