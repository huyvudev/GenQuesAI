"""Số hiệu ứng với nhiều văn bản — bộ sinh phải LOẠI, không được đoán.

`90/CP` ngày 15/12/1995 và `90/CP` ngày 24/11/1993 là hai văn bản khác nhau. Số hiệu
dạng cũ không mang năm nên bị tái sử dụng; đó là sự thật của dữ liệu, không phải lỗi
cần chữa. Cái phải chữa là bộ sinh: đừng dựng câu hỏi mà đáp án không đơn trị.

Sau A1, các test này chạy trên `Corpus` dựng tay — chính hợp đồng mà bộ sinh dùng ở
production, không còn lớp `neo` giả nào ở giữa.
"""
from __future__ import annotations

from datetime import date

from framework import so_hieu as sh
from framework.schema import (Corpus, CorpusMeta, LoaiQuanHe, NguonQuanHe, Norm,
                              QuanHe)
from framework.truy_van import khoa_nhap_nhang as kn_corpus
from generator import common, g1_replaces, g4_history


def _corpus(norms, qh=()) -> Corpus:
    c = Corpus(meta=CorpusMeta(ten="thu", theo_doi_hieu_luc=True, quan_he_tu_dong=True))
    c.norms = {n.norm_id: n for n in norms}
    c.quan_he = list(qh)
    c.dung_chi_muc()
    return c


def _n(nid, so_hieu, hl="2020-01-01"):
    return Norm(nid, so_hieu, ngay_hieu_luc=date.fromisoformat(hl))


# ── phát hiện ───────────────────────────────────────────────────────────────
def test_phat_hien_so_hieu_dung_lai():
    c = _corpus([_n("n1", "90/CP"), _n("n2", "90/CP"), _n("n3", "15/2018/NĐ-CP")])
    assert common.khoa_nhap_nhang(c) == frozenset({"90/cp"})


def test_khac_hoa_thuong_van_la_nhap_nhang_neu_khac_van_ban():
    """Hai NORM khác nhau chung khoá là nhập nhằng, bất kể cách ghi hoa thường."""
    c = _corpus([_n("n1", "15/2018/NĐ-CP"), _n("n2", "15/2018/nđ-cp")])
    assert common.khoa_nhap_nhang(c) == frozenset({"15/2018/nđ-cp"})


def test_ban_Corpus_va_ban_generator_cho_cung_ket_qua():
    """`common.khoa_nhap_nhang` uỷ quyền cho `truy_van` — hai đường không được lệch,
    nếu không bộ sinh và báo cáo năng lực loại hai tập câu khác nhau."""
    c = _corpus([_n("n1", "90/CP"), _n("n2", "90/CP"), _n("n3", "15/2018/NĐ-CP")])
    assert common.khoa_nhap_nhang(c) == frozenset(kn_corpus(c, sh.khoa))


# ── G1: đáp án LÀ định danh -> loại cả câu ──────────────────────────────────
def _c_g1(cu_sh="15/2018/NĐ-CP", moi_sh="20/2021/NĐ-CP", them=()):
    """Corpus tối thiểu cho một ứng viên G1: `moi` thay `cu` bằng cạnh trực tiếp."""
    norms = [_n("cu", cu_sh, "2018-01-01"), _n("moi", moi_sh, "2021-06-01"), *them]
    qh = [QuanHe(LoaiQuanHe.THAY_THE, "moi", "cu", da_duyet=True,
                 nguon=NguonQuanHe.CANH)]
    return _corpus(norms, qh)


def test_G1_loai_khi_dap_an_nhap_nhang():
    c = _c_g1(moi_sh="90/CP", them=[_n("x", "90/CP", "1995-12-15")])
    items, stat = g1_replaces.build(c, store=None, n=5, pool=10)
    assert items == [] and stat["bo_vi_khoa_nhap_nhang"] == 1


def test_G1_loai_khi_van_ban_DUOC_HOI_nhap_nhang():
    """Không chỉ đáp án. Đề bài mơ hồ thì đáp án đúng cũng không cứu được câu hỏi."""
    c = _c_g1(cu_sh="90/CP", them=[_n("x", "90/CP", "1993-11-24")])
    items, stat = g1_replaces.build(c, store=None, n=5, pool=10)
    assert items == [] and stat["bo_vi_khoa_nhap_nhang"] == 1


def test_G1_khong_loai_khi_khoa_duy_nhat():
    """Loại quá tay cũng là hỏng — phải đi tiếp tới bước tìm bằng chứng."""
    c = _c_g1()
    try:
        _, stat = g1_replaces.build(c, store=None, n=5, pool=10)
        assert stat["bo_vi_khoa_nhap_nhang"] == 0
    except AttributeError:
        pass          # đã đi tới bước tra Qdrant với store=None -> đúng mong đợi


def test_G1_ung_vien_chi_lay_canh_truc_tiep():
    """A1 không được đánh rơi bộ lọc nguồn: quan hệ THAY_THE từ nhánh Action
    (mang do_tin) thuộc về G4′, lọt vào đây là hai nhóm giẫm chân nhau."""
    norms = [_n("cu", "15/2018/NĐ-CP", "2018-01-01"),
             _n("moi", "20/2021/NĐ-CP", "2021-06-01")]
    qh = [QuanHe(LoaiQuanHe.THAY_THE, "moi", "cu", do_tin=0.95, da_duyet=True,
                 nguon=NguonQuanHe.TU_DONG)]
    assert g1_replaces.ung_vien(_corpus(norms, qh), 10) == []


# ── G4′: đáp án là DANH SÁCH -> bỏ phần tử, giữ câu ─────────────────────────
def _c_g4(vb_sh, nguon_shs, them=()):
    norms = [_n("vb", vb_sh, "2015-01-01"), *them]
    qh = []
    for i, s_ in enumerate(nguon_shs):
        norms.append(_n(f"ng{i}", s_, "2020-01-01"))
        qh.append(QuanHe(LoaiQuanHe.SUA_DOI, f"ng{i}", "vb", do_tin=0.9,
                         da_duyet=True, nguon=NguonQuanHe.TU_DONG))
    return _corpus(norms, qh)


def test_G4_loai_ca_cau_khi_van_ban_duoc_hoi_nhap_nhang():
    c = _c_g4("90/CP", ["15/2018/NĐ-CP", "16/2019/NĐ-CP"],
              them=[_n("x", "90/CP", "1993-11-24")])
    items, stat = g4_history.build(c, store=None, n=5, pool=10)
    assert items == [] and stat["bo_vi_khoa_nhap_nhang"] == 1


def test_G4_bo_phan_tu_nhap_nhang_chu_khong_bo_ca_cau():
    """Khác G1: mất một phần tử của danh sách vẫn còn câu hỏi. Chỉ khi còn dưới 2
    phần tử thì mới hết là câu hỏi danh sách."""
    c = _c_g4("15/2018/NĐ-CP", ["90/CP", "16/2019/NĐ-CP"],
              them=[_n("x", "90/CP", "1993-11-24")])
    items, stat = g4_history.build(c, store=None, n=5, pool=10)
    assert stat["bo_phan_tu_nhap_nhang"] == 1
    assert stat["bo_vi_gop_con_1"] == 1 and items == []


def test_G4_ung_vien_loai_can_cu():
    """Bộ lọc đắt nhất của framework phải sống sót qua A1: CAN_CU chiếm 59% quan hệ
    đã duyệt, đánh rơi là quá nửa đáp án liệt kê văn bản chỉ viện dẫn."""
    norms = [_n("vb", "15/2018/NĐ-CP"), _n("sua", "20/2021/NĐ-CP"),
             _n("vd", "99/2022/NĐ-CP"), _n("sua2", "30/2022/NĐ-CP")]
    qh = [QuanHe(LoaiQuanHe.SUA_DOI, "sua", "vb", do_tin=0.9, da_duyet=True,
                 nguon=NguonQuanHe.TU_DONG),
          QuanHe(LoaiQuanHe.SUA_DOI, "sua2", "vb", do_tin=0.9, da_duyet=True,
                 nguon=NguonQuanHe.TU_DONG),
          QuanHe(LoaiQuanHe.CAN_CU, "vd", "vb", do_tin=0.99, da_duyet=True,
                 nguon=NguonQuanHe.TU_DONG)]
    uv = g4_history.ung_vien(_corpus(norms, qh), 10, 0.85)
    assert len(uv) == 1
    assert {x["id"] for x in uv[0]["tac_dong"]} == {"sua", "sua2"}
