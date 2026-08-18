"""Số hiệu ứng với nhiều văn bản — bộ sinh phải LOẠI, không được đoán.

`90/CP` ngày 15/12/1995 và `90/CP` ngày 24/11/1993 là hai văn bản khác nhau. Số hiệu
dạng cũ không mang năm nên bị tái sử dụng; đó là sự thật của dữ liệu, không phải lỗi
cần chữa. Cái phải chữa là bộ sinh: đừng dựng câu hỏi mà đáp án không đơn trị.

Các test dưới đây chạy được offline vì phép kiểm nhập nhằng nằm TRƯỚC bước tra Qdrant —
ứng viên bị loại thì không bao giờ chạm tới index. Đó cũng là thứ tự đúng: đắt nhất
để sau cùng.
"""
from __future__ import annotations

from framework import so_hieu as sh
from framework.schema import Corpus, CorpusMeta, Norm
from framework.truy_van import khoa_nhap_nhang as kn_corpus
from generator import common, g1_replaces, g4_history


class _Neo:
    """Chỉ cần hai thứ: `stream` cho bảng số hiệu, `run` cho truy vấn của nhóm."""

    def __init__(self, so_hieu_norm, rows=None):
        self.bang = [{"sh": s, "id": i} for i, s in so_hieu_norm]
        self.rows = rows or []

    def stream(self, q, **kw):
        assert q is common.Q_MOI_SO_HIEU
        return list(self.bang)

    def run(self, q, **kw):
        return list(self.rows)


def _sach_cache():
    common._cache_nhap_nhang.clear()


# ── phát hiện ───────────────────────────────────────────────────────────────
def test_phat_hien_so_hieu_dung_lai():
    _sach_cache()
    neo = _Neo([("n1", "90/CP"), ("n2", "90/CP"), ("n3", "15/2018/NĐ-CP")])
    assert common.khoa_nhap_nhang(neo) == frozenset({"90/cp"})


def test_cung_van_ban_ghi_khac_hoa_thuong_KHONG_tinh_la_nhap_nhang():
    """Nhập nhằng là hai VĂN BẢN khác nhau chung số hiệu — không phải một văn bản
    được ghi hai kiểu. Gộp lẫn hai chuyện thì loại oan dữ liệu lành."""
    _sach_cache()
    neo = _Neo([("n1", "15/2018/NĐ-CP"), ("n1", "15/2018/nđ-cp")])
    assert common.khoa_nhap_nhang(neo) == frozenset()


def test_nho_ket_qua_khong_quet_lai():
    """Quét toàn bộ Norm là truy vấn đắt và mỗi nhóm đều cần — không nhớ thì chạy
    trọn bộ sẽ quét 8 lần."""
    _sach_cache()
    neo = _Neo([("n1", "90/CP"), ("n2", "90/CP")])
    dem = {"n": 0}
    goc = neo.stream

    def dem_stream(q, **kw):
        dem["n"] += 1
        return goc(q, **kw)

    neo.stream = dem_stream
    common.khoa_nhap_nhang(neo)
    common.khoa_nhap_nhang(neo)
    assert dem["n"] == 1


def test_ban_Corpus_cho_cung_ket_qua():
    """Bản chạy trên `Corpus` (dùng sau A1) phải nhất quán với bản chạy trên Neo4j —
    nếu không, chuyển sang A1 là đổi lặng lẽ tập câu hỏi bị loại."""
    c = Corpus(meta=CorpusMeta(ten="t", theo_doi_hieu_luc=True))
    c.norms = {n.norm_id: n for n in
               [Norm("n1", "90/CP"), Norm("n2", "90/CP"), Norm("n3", "15/2018/NĐ-CP")]}
    c.dung_chi_muc()
    assert set(kn_corpus(c, sh.khoa)) == {"90/cp"}


# ── G1: đáp án LÀ định danh -> loại cả câu ──────────────────────────────────
def _row_g1(cu_sh, moi_sh):
    return {"cu_id": "c", "cu_so_hieu": cu_sh, "cu_tieu_de": "t", "cu_loai": "ND",
            "cu_hieu_luc": "2000-01-01", "moi_id": "m", "moi_so_hieu": moi_sh,
            "moi_tieu_de": "t2", "moi_hieu_luc": "2010-01-01", "anh_em": []}


def test_G1_loai_khi_dap_an_nhap_nhang():
    _sach_cache()
    neo = _Neo([("n1", "90/CP"), ("n2", "90/CP")], [_row_g1("15/2018/NĐ-CP", "90/CP")])
    items, stat = g1_replaces.build(neo, store=None, n=5, pool=10)
    assert items == []
    assert stat["bo_vi_khoa_nhap_nhang"] == 1


def test_G1_loai_khi_van_ban_DUOC_HOI_nhap_nhang():
    """Không chỉ đáp án. Đề bài mơ hồ thì đáp án đúng cũng không cứu được câu hỏi."""
    _sach_cache()
    neo = _Neo([("n1", "90/CP"), ("n2", "90/CP")], [_row_g1("90/CP", "15/2018/NĐ-CP")])
    items, stat = g1_replaces.build(neo, store=None, n=5, pool=10)
    assert items == [] and stat["bo_vi_khoa_nhap_nhang"] == 1


def test_G1_khong_loai_khi_khoa_duy_nhat():
    """Loại quá tay cũng là hỏng — phải đi tiếp tới bước tìm bằng chứng."""
    _sach_cache()
    neo = _Neo([("n1", "90/CP")], [_row_g1("15/2018/NĐ-CP", "16/2019/NĐ-CP")])
    try:
        _, stat = g1_replaces.build(neo, store=None, n=5, pool=10)
        assert stat["bo_vi_khoa_nhap_nhang"] == 0
    except AttributeError:
        pass          # đã đi tới bước tra Qdrant với store=None -> đúng như mong đợi


# ── G4′: đáp án là DANH SÁCH -> bỏ phần tử, giữ câu ─────────────────────────
def _row_g4(vb_sh, nguon):
    return {"vb_id": "v", "vb_sh": vb_sh, "vb_td": "Quy định về abc",
            "tac_dong": [{"sh": s, "id": f"i{i}", "loai": "SuaDoi", "ngay": None}
                         for i, s in enumerate(nguon)]}


def test_G4_loai_ca_cau_khi_van_ban_duoc_hoi_nhap_nhang():
    _sach_cache()
    neo = _Neo([("n1", "90/CP"), ("n2", "90/CP")],
               [_row_g4("90/CP", ["15/2018/NĐ-CP", "16/2019/NĐ-CP"])])
    items, stat = g4_history.build(neo, store=None, n=5, pool=10)
    assert items == [] and stat["bo_vi_khoa_nhap_nhang"] == 1


def test_G4_bo_phan_tu_nhap_nhang_chu_khong_bo_ca_cau():
    """Khác G1 ở chỗ này: mất một phần tử của danh sách vẫn còn câu hỏi. Chỉ khi
    còn dưới 2 phần tử thì mới hết là câu hỏi danh sách."""
    _sach_cache()
    neo = _Neo([("n1", "90/CP"), ("n2", "90/CP")],
               [_row_g4("15/2018/NĐ-CP", ["90/CP", "16/2019/NĐ-CP"])])
    items, stat = g4_history.build(neo, store=None, n=5, pool=10)
    assert stat["bo_phan_tu_nhap_nhang"] == 1
    # còn 1 phần tử -> không đủ là câu hỏi danh sách -> rơi vào bo_vi_gop_con_1
    assert stat["bo_vi_gop_con_1"] == 1 and items == []
