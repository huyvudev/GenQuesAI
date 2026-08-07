"""Chuẩn hoá số hiệu văn bản QPPL.

Hàm này nằm trên đường đi NÓNG NHẤT của framework: mọi check citation đều đi qua nó.
Sai ở đây là sai lan toàn hệ — hệ được đo bị chấm sai vì CÁCH GHI chứ không vì chất
lượng. Nên nó được thiết kế theo số đo thật trên 66.368 văn bản, không theo phỏng đoán.

Đo 2026-08-07 với mẫu cũ `\\d+[a-zA-Z]?/\\d{4}/[A-ZĐ][A-ZĐ0-9\\-]*`:

  · chỉ **54,1%** số hiệu khớp — 30.479 văn bản trượt hoàn toàn
  · thiên lệch theo thập niên rất nặng: trước 1990 gần như 0%, 2010s chỉ 51,2%
    (dạng cũ không có năm trong số hiệu: `01/BKH-DN`, `003-TT/LB`, `01/CT-TTg`)
  · **106 văn bản bị CẮT CỤT**: `01/2001/CT.UBT` → `01/2001/CT` — sai định danh,
    tệ hơn bị loại, vì câu hỏi sẽ trỏ vào một văn bản không tồn tại
  · **498 core bị 1.056 văn bản dùng chung**: `01/2005/TTLT/BCA-BLĐTBXH` và
    `01/2005/TTLT/BNV-BTC` cùng ra `01/2005/TTLT` vì lớp ký tự dừng ở dấu `/`
"""
from __future__ import annotations

import re
import unicodedata

# `Ð` U+00D0 (ETH) và `Đ` U+0110 (D WITH STROKE) trông giống hệt nhau và dữ liệu thật
# dùng LẪN LỘN: `01/2001/TTLT/BLÐTBXH-BTC` với `.../BLĐTBXH-BTC` là CÙNG một văn bản.
_ĐONG_DANG = {"Ð": "Đ", "ð": "đ"}

# Dạng CÓ NĂM. Sau `số/năm/` thì lấy tới khoảng trắng — ký hiệu có thể chứa `/` (TTLT),
# `.` (CT.UBT), `&` (BKH&ĐT), chữ thường (TTg) và chữ số (QH15). Lớp ký tự liệt kê
# từng thứ một là cách chắc chắn sẽ bỏ sót; lấy-tới-khoảng-trắng thì không.
_CO_NAM = re.compile(r"\d+[a-zA-Z]?/\d{4}/[^\s,;()\[\]]+")

# Dạng KHÔNG CÓ NĂM — văn bản cũ. Phải có chữ cái sau dấu phân cách để không nuốt
# nhầm ngày tháng (`15/2018`) hay phân số.
_KHONG_NAM = re.compile(r"\d+[a-zA-Z]?\s*[/-]\s*[A-ZĐa-zđ][^\s,;()\[\]]*")

_DUOI_THUA = ".,;:)]}'\"-–—"


def _chuan_ky_tu(s: str) -> str:
    s = unicodedata.normalize("NFC", s)
    return "".join(_ĐONG_DANG.get(c, c) for c in s)


def trich(s: str | None) -> str | None:
    """Rút phần lõi số hiệu ra khỏi chuỗi tuỳ ý. Không thấy -> None.

    'Nghị định số 15/2018/NĐ-CP ngày…' -> '15/2018/NĐ-CP'
    '01/2005/TTLT/BCA-BLĐTBXH'         -> '01/2005/TTLT/BCA-BLĐTBXH'   (không cắt)
    '01/CT-TTg'                        -> '01/CT-TTg'                  (không có năm)
    """
    if not s:
        return None
    s = _chuan_ky_tu(s)
    m = _CO_NAM.search(s) or _KHONG_NAM.search(s)
    if not m:
        return None
    lo = m.group(0).rstrip(_DUOI_THUA)
    return lo.replace(" ", "") or None


def khoa(s: str | None) -> str | None:
    """Khoá để SO SÁNH hai số hiệu: đã chuẩn hoá ký tự, bỏ hoa/thường.

    Dùng cho exact-match giữa bộ đề và câu trả lời của hệ được đo.
    """
    lo = trich(s)
    return lo.casefold() if lo else None


def bang_nhau(a: str | None, b: str | None) -> bool:
    ka, kb = khoa(a), khoa(b)
    return ka is not None and ka == kb


def tim_tat_ca(text: str | None) -> list[str]:
    """Mọi số hiệu xuất hiện trong một đoạn văn — dùng cho hệ HỘP ĐEN không trả
    `citations` có cấu trúc, phải vớt số hiệu ngay trong câu trả lời.

    Mẫu KHÔNG-NĂM chỉ chạy trên phần văn bản mà mẫu CÓ-NĂM chưa phủ. Không che thì
    `99/2021/NĐ-CP` đẻ ra bóng ma `2021/NĐ-CP` — và bóng ma đó lọt vào tập "số hiệu
    hệ đã nêu", làm check `not_governing` báo sai (nó kiểm một văn bản KHÔNG được
    xuất hiện).
    """
    if not text:
        return []
    t = _chuan_ky_tu(text)
    ra, da, phu = [], set(), []

    def them(lo: str) -> None:
        lo = lo.rstrip(_DUOI_THUA).replace(" ", "")
        k = lo.casefold()
        if lo and k not in da:
            da.add(k)
            ra.append(lo)

    for m in _CO_NAM.finditer(t):
        phu.append(m.span())
        them(m.group(0))
    for m in _KHONG_NAM.finditer(t):
        if any(a <= m.start() < b for a, b in phu):
            continue                     # nằm trong vùng đã khớp mẫu có-năm
        them(m.group(0))
    return ra
