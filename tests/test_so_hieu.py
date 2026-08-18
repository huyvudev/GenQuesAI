"""Chuẩn hoá số hiệu — kiểm trên BIẾN THỂ CÓ THẬT lấy từ corpus, không phải ví dụ tự nghĩ.

Đây là hàm quyết định hai chuyện, và sai theo hai hướng ngược nhau:

    quá CHẶT  -> mù một phần kho. Bộ đề im lặng thu hẹp phạm vi rồi báo cáo như thể
                 đã phủ toàn bộ. Đây là lỗi đã tồn tại: mẫu cũ đọc được 53%.
    quá LỎNG  -> hai văn bản khác nhau bị coi là một. Hệ trả lời SAI được chấm ĐÚNG.

Nên mỗi test dưới đây đều ghim một trong hai hướng, và các ca đều lấy từ dữ liệu thật.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from framework import so_hieu as sh

GOC = Path(__file__).resolve().parent.parent
CORPUS = GOC / "out" / "corpus" / "norms.jsonl"


@pytest.fixture(scope="module")
def so_hieu_that() -> list[str]:
    if not CORPUS.exists():
        pytest.skip(f"thiếu {CORPUS} — chạy: python -m framework.cli xuat")
    return [r["so_hieu"] for l in CORPUS.read_text(encoding="utf-8").splitlines()
            if l.strip() and (r := json.loads(l)).get("so_hieu")]


# ── không được QUÁ CHẶT ─────────────────────────────────────────────────────
@pytest.mark.parametrize("s,mong", [
    ("15/2018/NĐ-CP", "15/2018/NĐ-CP"),
    ("Nghị định số 15/2018/NĐ-CP ngày 12/02/2018", "15/2018/NĐ-CP"),
    ("03/2022/QH15", "03/2022/QH15"),               # đuôi có chữ số
    ("01/2005/TTLT/BCA-BLĐTBXH", "01/2005/TTLT/BCA-BLĐTBXH"),   # ký hiệu có `/`
    ("01/2001/CT.UBT", "01/2001/CT.UBT"),           # ký hiệu có `.`
    ("127/99/TT-BTC", "127/99/TT-BTC"),             # năm 2 chữ số
    ("01/CT-TTg", "01/CT-TTg"),                     # không có năm
    ("8032/VPCP-V.III", "8032/VPCP-V.III"),         # công văn
    ("76-TC/TCDN", "76-TC/TCDN"),                   # phân cách bằng `-`
    ("113/SL", "113/SL"),                           # sắc lệnh 1950
])
def test_doc_duoc_moi_dang_co_that(s, mong):
    assert sh.trich(s) == mong


def test_doc_duoc_gan_het_corpus_that(so_hieu_that):
    """Mẫu cũ đọc được 53%. Ngưỡng 95% là để phát hiện hồi quy, không phải mục tiêu."""
    doc = sum(1 for s in so_hieu_that if sh.khoa(s))
    ty = doc / len(so_hieu_that)
    assert ty >= 0.95, f"chỉ đọc được {ty:.0%} — kho lại bị mù một phần"


def test_Ð_va_Đ_la_mot(so_hieu_that):
    """`Ð` U+00D0 và `Đ` U+0110 trông giống hệt, dữ liệu thật dùng lẫn lộn."""
    assert sh.bang_nhau("01/2001/TTLT/BLÐTBXH-BTC", "01/2001/TTLT/BLĐTBXH-BTC")


# ── không được QUÁ LỎNG ─────────────────────────────────────────────────────
@pytest.mark.parametrize("a,b", [
    ("127/99/TT-BTC", "129/99/TT-BTC"),             # từng gộp nhầm: cùng ra `99/tt-btc`
    ("106/99/QĐ-BTC", "124/99/QĐ-BTC"),
    ("01/2005/TTLT/BCA-BLĐTBXH", "01/2005/TTLT/BNV-BTC"),   # từng cắt cụt còn `01/2005/TTLT`
    ("15/2018/NĐ-CP", "15/2019/NĐ-CP"),
    ("15/2018/NĐ-CP", "16/2018/NĐ-CP"),
])
def test_hai_van_ban_khac_nhau_khong_duoc_bang_nhau(a, b):
    assert not sh.bang_nhau(a, b), f"{a} bị coi là {b} — trả lời sai sẽ được chấm đúng"


def test_khong_nuot_nham_ngay_thang():
    """`15/03/2024` là NGÀY. Mẫu năm-2-chữ-số phải phân biệt bằng chữ cái sau dấu `/`
    thứ hai, nếu không mọi ngày tháng trong câu trả lời đều thành số hiệu ma."""
    for s in ("15/03/2024", "01/01/2020", "ngày 28/02/2019"):
        assert sh.trich(s) is None, f"{s} không phải số hiệu"


def test_khong_de_lai_bong_ma_trong_van_ban():
    """`99/2021/NĐ-CP` không được đẻ thêm `2021/NĐ-CP`. Bóng ma lọt vào tập 'số hiệu
    hệ đã nêu' sẽ làm check `not_governing` báo sai — nó kiểm một văn bản KHÔNG
    được xuất hiện."""
    assert sh.tim_tat_ca("Theo 99/2021/NĐ-CP thì …") == ["99/2021/NĐ-CP"]


def test_vot_duoc_nhieu_so_hieu_trong_mot_cau_tra_loi():
    ra = sh.tim_tat_ca("Căn cứ 127/99/TT-BTC và 15/2018/NĐ-CP, xem thêm 01/CT-TTg.")
    assert set(ra) == {"127/99/TT-BTC", "15/2018/NĐ-CP", "01/CT-TTg"}


def test_ty_le_va_cham_khoa_tren_corpus_that(so_hieu_that):
    """Khoá phải gần như song ánh với văn bản. Va chạm nhiều nghĩa là exact-match
    đang chấp nhận nhầm văn bản ở quy mô lớn."""
    import collections
    dem = collections.Counter(k for s in so_hieu_that if (k := sh.khoa(s)))
    va = sum(v - 1 for v in dem.values() if v > 1)
    assert va / len(so_hieu_that) <= 0.01, f"{va} văn bản dùng chung khoá với văn bản khác"


# ── tầng chấm: hai chế độ ───────────────────────────────────────────────────
def test_che_do_moi_bat_duoc_ca_cat_cut():
    """Hai thông tư liên tịch khác nhau. Chế độ `cu` chấm ĐẠT vì cắt cụt còn
    `01/2005/TTLT` — đây chính là lý do phải có chế độ mới."""
    from framework.grader import grade
    de = {"norms_include": ["01/2005/TTLT/BCA-BLĐTBXH"]}
    sai = {"answer": "Theo 01/2005/TTLT/BNV-BTC",
           "citations": [{"so_hieu": "01/2005/TTLT/BNV-BTC"}]}
    assert all(c.passed for c in grade(sai, de, che_do="cu")), "ghim hành vi CŨ"
    assert not all(c.passed for c in grade(sai, de, che_do="moi"))


def test_che_do_moi_cham_dung_so_hieu_dang_cu():
    from framework.grader import grade
    de = {"norms_include": ["127/99/TT-BTC"]}
    dung = {"answer": "Theo Thông tư số 127/99/TT-BTC",
            "citations": [{"so_hieu": "127/99/TT-BTC"}]}
    assert not all(c.passed for c in grade(dung, de, che_do="cu")), \
        "chế độ cũ không đọc nổi dạng này — ghim lại để thấy vì sao phải đổi"
    assert all(c.passed for c in grade(dung, de, che_do="moi"))


# Bộ đề có lưu ĐÚNG số hiệu của văn bản không — việc đó phải so với ĐỒ THỊ, và nó đã
# được kiểm ở tầng golden (`test_su_kien`, sự kiện `so_hieu_norm`, 520 kỳ vọng).
#
# Đừng thay bằng phép tự-đối-chiếu "mẫu cũ đọc khác mẫu mới": nó đo tính chất của mẫu
# cũ chứ không đo bộ đề. Bản freeze TRƯỚC lưu sẵn `54/2014/QĐ-TT` nên tự-đối-chiếu cho
# 0 lỗi, trong khi bộ đề đó thực sự hỏng; bản MỚI lưu đầy đủ `72/2025/NQLT/UBTVQH15-CP`
# nên bị bắt oan 7 ca. Đúng chỗ để kiểm là đối chiếu với nguồn.
