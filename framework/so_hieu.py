"""Chuẩn hoá số hiệu văn bản QPPL.

Hàm này nằm trên đường đi NÓNG NHẤT của framework: mọi check citation và mọi phép lọc
ứng viên đều đi qua nó. Sai ở đây sai theo HAI hướng ngược nhau, và cả hai đều im lặng:

    quá CHẶT  -> mù một phần kho. Bộ sinh loại sạch những văn bản nó không đọc nổi,
                 rồi bộ đề báo cáo như thể đã phủ toàn bộ.
    quá LỎNG  -> hai văn bản khác nhau ra cùng một khoá. Hệ trả lời SAI được chấm ĐÚNG.

Nên nó được thiết kế theo số đo thật, không theo phỏng đoán.

Đo 2026-08-07 với mẫu cũ `\\d+[a-zA-Z]?/\\d{4}/[A-ZĐ][A-ZĐ0-9\\-]*` (66.368 văn bản):

  · chỉ **54,1%** số hiệu khớp — 30.479 văn bản trượt hoàn toàn
  · thiên lệch theo thập niên rất nặng: trước 1990 gần như 0%
    (dạng cũ không có năm trong số hiệu: `01/BKH-DN`, `003-TT/LB`, `01/CT-TTg`)
  · **106 văn bản bị CẮT CỤT**: `01/2001/CT.UBT` → `01/2001/CT` — sai định danh,
    tệ hơn bị loại, vì câu hỏi sẽ trỏ vào một văn bản không tồn tại
  · **498 core bị 1.056 văn bản dùng chung**: `01/2005/TTLT/BCA-BLĐTBXH` và
    `01/2005/TTLT/BNV-BTC` cùng ra `01/2005/TTLT` vì lớp ký tự dừng ở dấu `/`

Đo lại 2026-08-18 trên mẫu 3.000 văn bản, sau khi bản này thay bản cũ ở bộ sinh và ở
`grader` (chế độ `moi`):

  · đọc được **99%** (2.976/3.000), so với 53% của mẫu cũ
  · **1.382 văn bản** trước đây không bao giờ được hỏi tới nay đã dùng được
  · khoá còn va chạm: **6 nhóm / 12 văn bản (0,2%)**, và cả 12 đều có `ngay_ban_hanh`
    để phân biệt. Đó là nhập nhằng THẬT (`90/CP` 1995 vs 1993), không phải lỗi mẫu —
    xử lý ở `truy_van.khoa_nhap_nhang()`, không phải ở đây.
"""
from __future__ import annotations

import re
import unicodedata

# KÝ TỰ NHÌN GIỐNG HỆT NHƯNG KHÁC MÃ. Đây là chỗ exact-match thua một cách vô hình:
# hai chuỗi hiện lên màn hình y như nhau mà `==` trả False, nên hệ trả lời ĐÚNG bị
# chấm SAI và không ai đọc ra vì sao.
#
#   `Ð` U+00D0 (ETH) vs `Đ` U+0110  — `01/2001/TTLT/BLÐTBXH-BTC` và `.../BLĐTBXH-BTC`
#   `С` U+0421 (Kirin ES) vs `C`    — đo thật: `65/2025/TT-BTС` trong corpus
#   `–` U+2013 (en dash) vs `-`     — đo thật: `3710/VPCP–WEBCP`
#
# Hai ca sau tìm thấy khi replay bộ đề đã freeze lên đồ thị: chúng làm G4′ báo "DƯ văn
# bản" cho những văn bản thực ra đã có trong đáp án, chỉ khác một ký tự vô hình.
#
# Chỉ map những cặp TRÔNG GIỐNG HỆT. Kirin là nguồn phổ biến nhất (bố cục bàn phím,
# copy-paste từ Word). Gặp ký tự lạ khác thì thêm vào đây, đừng nới regex.
_ĐONG_DANG = {
    "Ð": "Đ", "ð": "đ",
    # Kirin -> Latin
    "А": "A", "В": "B", "Е": "E", "К": "K", "М": "M", "Н": "H", "О": "O",
    "Р": "P", "С": "C", "Т": "T", "У": "Y", "Х": "X",
    "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "у": "y", "х": "x",
    # các loại gạch ngang -> hyphen ASCII
    "–": "-", "—": "-", "‒": "-", "−": "-", "‐": "-",
}

# Dạng CÓ NĂM. Sau `số/năm/` thì lấy tới khoảng trắng — ký hiệu có thể chứa `/` (TTLT),
# `.` (CT.UBT), `&` (BKH&ĐT), chữ thường (TTg) và chữ số (QH15). Lớp ký tự liệt kê
# từng thứ một là cách chắc chắn sẽ bỏ sót; lấy-tới-khoảng-trắng thì không.
_CO_NAM = re.compile(r"\d+[a-zA-Z]?/\d{4}/[^\s,;()\[\]]+")

# Dạng NĂM HAI CHỮ SỐ — `127/99/TT-BTC`, dùng nhiều ở thập niên 1990.
#
# Phải thử TRƯỚC `_KHONG_NAM`, và đây không phải chuyện thứ tự cho đẹp. `_KHONG_NAM`
# dùng `search` nên với `127/99/TT-BTC` nó khớp từ giữa chuỗi và trả về `99/TT-BTC` —
# tiền tố `127` bị nuốt mất. Hậu quả: `127/99/TT-BTC` và `129/99/TT-BTC` ra CÙNG một
# khoá, tức hai văn bản khác nhau được chấm là bằng nhau. Đo trên mẫu 3.000 văn bản:
# 4/6 văn bản dạng này bị đánh đồng với văn bản khác.
#
# `[A-ZĐa-zđ]` sau dấu `/` thứ hai là chốt phân biệt với NGÀY THÁNG: `15/03/2024` có
# `2024` là chữ số nên không khớp, còn `127/99/TT-BTC` có `TT` là chữ cái nên khớp.
_NAM_NGAN = re.compile(r"\d+[a-zA-Z]?/\d{2}/[A-ZĐa-zđ][^\s,;()\[\]]*")

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
    m = _CO_NAM.search(s) or _NAM_NGAN.search(s) or _KHONG_NAM.search(s)
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

    for mau in (_CO_NAM, _NAM_NGAN):
        for m in mau.finditer(t):
            if any(x <= m.start() < y for x, y in phu):
                continue
            phu.append(m.span())
            them(m.group(0))
    for m in _KHONG_NAM.finditer(t):
        if any(a <= m.start() < b for a, b in phu):
            continue                     # nằm trong vùng đã khớp mẫu có-năm
        them(m.group(0))
    return ra
