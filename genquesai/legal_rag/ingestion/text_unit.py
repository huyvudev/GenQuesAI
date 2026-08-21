"""Text Unit Builder — tạo chunk giàu ngữ cảnh cho mỗi Expression (ARCH §5.1.7).

Chunk = [trích dẫn duong_dan] + số hiệu/tiêu đề Norm + tiêu đề Điều + nội dung.
Giúp embedding "hiểu" đoạn text thuộc văn bản/điều nào.
"""
from __future__ import annotations

_SEG = {"Phan": "Phần", "Chuong": "Chương", "Muc": "Mục",
        "Dieu": "Điều", "Khoan": "Khoản", "Diem": "Điểm", "PhuLuc": "Phụ lục"}


def citation_from_path(duong_dan: str) -> str:
    """'Dieu 5 > Khoan 1' -> 'Điều 5 Khoản 1'; 'ToanVan' -> ''."""
    if not duong_dan or duong_dan == "ToanVan":
        return ""
    parts = []
    for seg in duong_dan.split(" > "):
        toks = seg.split(" ", 1)
        loai = _SEG.get(toks[0], toks[0])
        parts.append(f"{loai} {toks[1]}" if len(toks) > 1 else loai)
    return " ".join(parts)


def build_text_unit(so_hieu: str, norm_tieu_de: str | None, duong_dan: str,
                    comp_tieu_de: str | None, text: str) -> str:
    cite = citation_from_path(duong_dan)
    header = " — ".join(x for x in [
        (norm_tieu_de or so_hieu),
        f"{cite}. {comp_tieu_de}" if cite and comp_tieu_de else (cite or comp_tieu_de or ""),
    ] if x).strip(" —")
    return f"{header}\n{text}".strip() if header else (text or "")
