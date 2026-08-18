"""Kiểm chính các BỘ KIỂM của `test_su_kien.py`, trên corpus dựng tay.

Vì sao cần: 1.531 test replay chỉ chạy được khi có fixture (cần Neo4j). Chừng nào
chưa có, **không một assertion nào trong `BANG` từng được thực thi** — bảng dispatch
có thể sai ở bất kỳ đâu và không ai biết. Một bộ kiểm luôn-pass thì tệ hơn không có,
vì nó chiếm chỗ.

Mỗi loại sự kiện được kiểm HAI chiều:
    dữ liệu đúng  -> bộ kiểm phải im
    dữ liệu sai   -> bộ kiểm phải kêu
Chỉ chiều thứ nhất thì `assert True` cũng qua.
"""
from __future__ import annotations

from datetime import date

import pytest

from framework.schema import (Component, Corpus, CorpusMeta, DieuKhoanChuyenTiep,
                              Expression, LoaiQuanHe, Norm, QuanHe)
from tests.test_su_kien import BANG


def _corpus() -> Corpus:
    """Một corpus tí hon nhưng đủ dựng được mọi loại sự kiện.

        cu  15/2018/NĐ-CP  (2018-01-01)   <- bị thay bởi moi
        em  16/2018/NĐ-CP  (2018-01-01)   <- cũng bị moi thay  (bẫy 'anh em gần')
        moi 20/2021/NĐ-CP  (2021-06-01)
        con 01/2022/TT-BTC  hướng dẫn moi, cấp 6; moi cấp 4
        sua 30/2022/NĐ-CP  SỬA ĐỔI cu        (Action, do_tin .95)
        vd  99/2022/NĐ-CP  VIỆN DẪN cu       (CanCu — phải bị loại)
    """
    c = Corpus(meta=CorpusMeta(ten="tí hon", theo_doi_hieu_luc=True,
                               quan_he_tu_dong=True))
    c.norms = {n.norm_id: n for n in [
        Norm("cu", "15/2018/NĐ-CP", ngay_hieu_luc=date(2018, 1, 1),
             ngay_ban_hanh=date(2017, 12, 1)),
        Norm("em", "16/2018/NĐ-CP", ngay_hieu_luc=date(2018, 1, 1)),
        Norm("moi", "20/2021/NĐ-CP", ngay_hieu_luc=date(2021, 6, 1), cap_bac=4),
        Norm("con", "01/2022/TT-BTC", ngay_hieu_luc=date(2022, 1, 1), cap_bac=6),
        Norm("sua", "30/2022/NĐ-CP", ngay_hieu_luc=date(2022, 3, 1)),
        Norm("vd", "99/2022/NĐ-CP", ngay_hieu_luc=date(2022, 4, 1)),
    ]}
    c.components = {x.component_id: x for x in [
        Component("ch", "cu", "PhuLuc", None, "I", 0, "Chương I"),
        Component("d1", "cu", "Dieu", "ch", "1", 1, "Phạm vi điều chỉnh"),
        Component("d9", "cu", "Dieu", "ch", "9", 2, "Điều khoản thi hành"),
    ]}
    c.expressions = {e.expression_id: e for e in [
        Expression("e1-cu", "d1", "nội dung bản cũ của Điều 1",
                   date(2018, 1, 1), date(2021, 6, 1)),
        Expression("e1-moi", "d1", "nội dung bản mới của Điều 1",
                   date(2021, 6, 1), None),
        Expression("e9", "d9", "nội dung Điều 9", date(2018, 1, 1), None),
    ]}
    c.quan_he = [
        QuanHe(LoaiQuanHe.THAY_THE, "moi", "cu", da_duyet=True),
        QuanHe(LoaiQuanHe.THAY_THE, "moi", "em", da_duyet=True),
        QuanHe(LoaiQuanHe.HUONG_DAN, "con", "moi", da_duyet=True),
        QuanHe(LoaiQuanHe.SUA_DOI, "sua", "cu", do_tin=0.95, da_duyet=True),
        QuanHe(LoaiQuanHe.CAN_CU, "vd", "cu", do_tin=0.99, da_duyet=True),
    ]
    c.chuyen_tiep = [DieuKhoanChuyenTiep("r1", "cu", "điều kiện A", "áp dụng B",
                                         do_tin=0.95, da_duyet=True)]
    c.dung_chi_muc()
    return c


# (tên, sự kiện ĐÚNG, cách phá corpus để nó thành SAI)
CA = [
    ("thay_the_boi",
     {"norm": "cu", "ky_vong": ["moi"], "duy_nhat": True, "loc_moi_hon": True},
     lambda c: c.quan_he.append(
         QuanHe(LoaiQuanHe.THAY_THE, "sua", "cu", da_duyet=True))),

    ("da_thay_the_chua_so_hieu",
     {"norm": "moi", "so_hieu": ["16/2018/NĐ-CP"]},
     lambda c: c.quan_he.remove(next(q for q in c.quan_he if q.den_norm_id == "em"))),

    ("huong_dan", {"con": "con", "me": "moi"},
     lambda c: c.quan_he.remove(
         next(q for q in c.quan_he if q.loai is LoaiQuanHe.HUONG_DAN))),

    # Phá bằng cách BỎ bộ lọc CAN_CU — mô phỏng đúng lỗi A1 dễ mắc nhất: đổi CanCu
    # thành SuaDoi thì `vd` lọt vào đáp án.
    ("tac_dong_toi",
     {"norm": "cu", "ky_vong_ids": ["sua"], "ky_vong_so_hieu": ["30/2022/NĐ-CP"]},
     lambda c: setattr(next(q for q in c.quan_he if q.tu_norm_id == "vd"),
                       "loai", LoaiQuanHe.SUA_DOI)),

    ("so_hieu_norm", {"norm": "cu", "so_hieu": "15/2018/NĐ-CP"},
     lambda c: setattr(c.norms["cu"], "so_hieu", "15/2019/NĐ-CP")),

    ("ngay_hieu_luc_norm", {"norm": "cu", "ngay": "2018-01-01"},
     lambda c: setattr(c.norms["cu"], "ngay_hieu_luc", date(2018, 1, 2))),

    ("cap_bac", {"norm": "con", "cap": 6},
     lambda c: setattr(c.norms["con"], "cap_bac", 5)),

    ("chuyen_tiep",
     {"norm": "cu", "rule_id": "r1", "do_tin": 0.95,
      "dieu_kien": "điều kiện A", "ap_dung": "áp dụng B"},
     lambda c: setattr(c.chuyen_tiep[0], "do_tin", 0.5)),

    ("expr_ton_tai", {"expr": "e9"}, lambda c: c.expressions.pop("e9")),

    ("expr_dong_tai", {"expr": "e1-cu", "den": "2021-06-01"},
     lambda c: setattr(c.expressions["e1-cu"], "hieu_luc_den", date(2021, 7, 1))),

    # Trong khoảng -> bản cũ đang hiệu lực
    ("expr_hieu_luc_tai", {"expr": "e1-cu", "moc": "2020-05-05", "phai": True},
     lambda c: setattr(c.expressions["e1-cu"], "hieu_luc_den", date(2019, 1, 1))),

    ("dieu_hien_hanh",
     {"norm": "cu", "so_dieu": "1", "tieu_de": "Phạm vi điều chỉnh", "expr": "e1-moi"},
     lambda c: setattr(c.components["d1"], "so_thu_tu", "2")),

    ("so_dieu_lon_nhat", {"so_hieu": "15/2018/NĐ-CP", "ky_vong": 9},
     lambda c: c.components.pop("d9")),

    ("so_dieu_khong_co", {"so_hieu": "15/2018/NĐ-CP", "so_dieu": 155},
     lambda c: setattr(c.components["d9"], "so_thu_tu", "155")),

    # `reference_fields["nam_ban_hanh"]` của G8(c) thực ra chứa năm HIỆU LỰC — tên
    # trường đặt sai, xem `_nam_ban_hanh` trong test_su_kien.py.
    ("nam_ban_hanh", {"so_hieu": "15/2018/NĐ-CP", "nam": 2018},
     lambda c: setattr(c.norms["cu"], "ngay_hieu_luc", date(2019, 1, 1))),
]


@pytest.mark.parametrize("loai,sk,pha", CA, ids=[x[0] for x in CA])
def test_bo_kiem_im_khi_du_lieu_dung(loai, sk, pha):
    BANG[loai](_corpus(), {"loai": loai, "muc": "chan", **sk})


@pytest.mark.parametrize("loai,sk,pha", CA, ids=[x[0] for x in CA])
def test_bo_kiem_keu_khi_du_lieu_sai(loai, sk, pha):
    """Chiều quan trọng hơn. Bộ kiểm không kêu = 1.531 test replay là trang trí."""
    c = _corpus()
    pha(c)
    c.dung_chi_muc()
    with pytest.raises(AssertionError):
        BANG[loai](c, {"loai": loai, "muc": "chan", **sk})


def test_moc_dung_ranh_gioi_thi_ban_cu_da_het_hieu_luc():
    """`on_boundary` — kỳ vọng `phai=False`. Đây là phép kiểm nửa mở `[tu, den)`,
    và là 26/80 câu của nhóm G2′."""
    c = _corpus()
    BANG["expr_hieu_luc_tai"](
        c, {"loai": "expr_hieu_luc_tai", "muc": "chan",
            "expr": "e1-cu", "moc": "2021-06-01", "phai": False})


def test_neu_khoang_bi_hieu_thanh_dong_thi_bo_kiem_keu():
    """Mô phỏng lỗi off-by-one: nới `hieu_luc_den` thêm một ngày thì tại mốc chuyển
    giao bản cũ vẫn 'còn hiệu lực' — và bộ kiểm phải bắt được."""
    c = _corpus()
    c.expressions["e1-cu"].hieu_luc_den = date(2021, 6, 2)
    with pytest.raises(AssertionError, match="nửa mở"):
        BANG["expr_hieu_luc_tai"](
            c, {"loai": "expr_hieu_luc_tai", "muc": "chan",
                "expr": "e1-cu", "moc": "2021-06-01", "phai": False})


def test_thieu_thuc_the_thi_bao_loi_chi_ro_cach_sua():
    """Thiếu dữ liệu phải ĐỎ kèm câu lệnh sửa, không được skip — skip là cách chắc
    chắn nhất để bộ golden lặng lẽ ngừng kiểm."""
    c = _corpus()
    with pytest.raises(AssertionError, match="trich_fixture"):
        BANG["so_hieu_norm"](c, {"loai": "so_hieu_norm", "muc": "chan",
                                 "norm": "khong-ton-tai", "so_hieu": "1/2020/NĐ-CP"})


def test_moi_loai_trong_BANG_deu_co_ca_kiem():
    """Thêm bộ kiểm mới mà quên thêm ca ở đây thì nó lại không được kiểm."""
    mien = {"khong_co_norm",                   # cần pham_vi.json, chốt lúc xuất
            "khong_kiem_duoc_bang_corpus"}     # cố ý skip
    assert set(BANG) - mien == {x[0] for x in CA}
