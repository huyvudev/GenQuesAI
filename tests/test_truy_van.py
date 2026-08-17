"""Ghim ngữ nghĩa của tầng truy vấn trên corpus DỰNG TAY — chạy offline, không Neo4j.

Mỗi test ở đây tương ứng một chỗ mà bản dịch Cypher → duyệt cây có thể sai **mà không
có triệu chứng nào**: bộ đề vẫn sinh ra đủ 400 câu, mọi cổng C1–C4 vẫn pass, chỉ có tập
ứng viên là đã khác. Đó là lý do phải kiểm ở đây chứ không đợi diff bộ đề cuối cùng.

Corpus dựng tay nhỏ tới mức đọc được bằng mắt, nên khi test đỏ thì đọc ra ngay nó đỏ vì
cái gì — khác hẳn với đỏ trên một subgraph 400 văn bản.
"""
from __future__ import annotations

from datetime import date

import pytest

from framework import truy_van as tv
from framework.schema import (Component, Corpus, CorpusMeta, DieuKhoanChuyenTiep,
                              Expression, LoaiQuanHe, NguonQuanHe, Norm, QuanHe)


def _corpus(norms=(), comps=(), exprs=(), qh=(), ct=(), **meta_kw) -> Corpus:
    m = {"ten": "thu", "theo_doi_hieu_luc": True, "quan_he_tu_dong": True}
    m.update(meta_kw)
    c = Corpus(meta=CorpusMeta(**m))
    c.norms = {n.norm_id: n for n in norms}
    c.components = {x.component_id: x for x in comps}
    c.expressions = {e.expression_id: e for e in exprs}
    c.quan_he = list(qh)
    c.chuyen_tiep = list(ct)
    c.dung_chi_muc()
    return c


def _n(nid, sh=None, **kw) -> Norm:
    return Norm(norm_id=nid, so_hieu=sh or f"{nid}/2020/NĐ-CP", **kw)


def _c(cid, nid, loai="Dieu", parent=None, stt=None, thu_tu=0, tieu_de=None) -> Component:
    return Component(component_id=cid, norm_id=nid, loai=loai, parent_id=parent,
                     so_thu_tu=stt, thu_tu=thu_tu, tieu_de=tieu_de)


def _e(eid, cid, text="nội dung", tu=None, den=None) -> Expression:
    return Expression(expression_id=eid, component_id=cid, text=text,
                      hieu_luc_tu=tu, hieu_luc_den=den)


# ── HAS_PART* vs HAS_PART ───────────────────────────────────────────────────
# Đây là chỗ dịch sai dễ nhất và im nhất. Văn bản mẫu:
#     VB
#      └─ Chương I            (con trực tiếp)
#          ├─ Điều 1          (cháu)
#          │   └─ Khoản 1     (chắt)
#          └─ Điều 2
def _vb_long_nhau() -> Corpus:
    return _corpus(
        norms=[_n("VB")],
        comps=[
            _c("ch1", "VB", "PhuLuc", None, "I", 0, "Chương I"),
            _c("d1", "VB", "Dieu", "ch1", "1", 1, "Điều 1"),
            _c("k1", "VB", "Khoan", "d1", "1", 2),
            _c("d2", "VB", "Dieu", "ch1", "2", 3, "Điều 2"),
        ])


def test_moi_thanh_phan_la_duong_di_bien_do_dai():
    """`HAS_PART*` lấy MỌI độ sâu — 4 thành phần, không phải 1."""
    c = _vb_long_nhau()
    assert {x.component_id for x in tv.moi_thanh_phan(c, "VB")} == {"ch1", "d1", "k1", "d2"}


def test_con_truc_tiep_chi_mot_buoc():
    """`HAS_PART` một bước — chỉ Chương. Lẫn với bản `*` là đổi cả tập ứng viên."""
    c = _vb_long_nhau()
    assert [x.component_id for x in tv.con_truc_tiep(c, "VB")] == ["ch1"]


def test_cac_dieu_tim_duoc_dieu_long_duoi_chuong():
    """Điều nằm dưới Chương. Dịch `HAS_PART*` thành một-bước thì mất SẠCH Điều —
    G7 (90 câu, nhóm lớn nhất) sẽ ra 0 ứng viên mà không có thông báo lỗi nào."""
    c = _vb_long_nhau()
    assert [x.component_id for x in tv.cac_dieu(c, "VB")] == ["d1", "d2"]


def test_hau_due_khong_gom_chinh_no():
    c = _vb_long_nhau()
    assert {x.component_id for x in tv.hau_due(c, "ch1")} == {"d1", "k1", "d2"}
    assert {x.component_id for x in tv.hau_due(c, "d1")} == {"k1"}


def test_hau_due_khong_lap_khi_do_thi_co_chu_trinh():
    """§10.3d: bản Cypher từng duyệt trùng đường đi. Chu trình cha-con là dạng cực
    đoan của ca đó — không chặn thì treo hoặc trả kết quả lặp vô hạn."""
    c = _corpus(norms=[_n("VB")],
                comps=[_c("a", "VB", parent="b"), _c("b", "VB", parent="a")])
    ra = tv.hau_due(c, "a")
    assert [x.component_id for x in ra] == ["b"]


def test_to_tien_khong_lap_khi_co_chu_trinh():
    c = _corpus(norms=[_n("VB")],
                comps=[_c("a", "VB", parent="b"), _c("b", "VB", parent="a")])
    assert [x.component_id for x in tv.to_tien(c, "a")] == ["b"]


def test_to_tien_di_tu_gan_toi_xa():
    c = _vb_long_nhau()
    assert [x.component_id for x in tv.to_tien(c, "k1")] == ["d1", "ch1"]


def test_thanh_phan_khong_thuoc_van_ban_thi_khong_lan_sang():
    """Hai văn bản khác nhau không được trộn thành phần của nhau."""
    c = _corpus(norms=[_n("A"), _n("B")],
                comps=[_c("a1", "A"), _c("b1", "B")])
    assert [x.component_id for x in tv.moi_thanh_phan(c, "A")] == ["a1"]


# ── chiều của quan hệ ───────────────────────────────────────────────────────
def test_thay_the_dung_chieu():
    """`(moi)-[:REPLACES]->(cu)`; loader map tu=moi, den=cu.

    Đảo chiều là lỗi cho ra đáp án NGƯỢC HOÀN TOÀN mà mọi cổng đều pass: câu hỏi
    "X bị thay thế bởi văn bản nào" trả về văn bản mà X đã thay thế.
    """
    c = _corpus(norms=[_n("moi"), _n("cu")],
                qh=[QuanHe(LoaiQuanHe.THAY_THE, "moi", "cu", da_duyet=True)])
    assert tv.thay_the_boi(c, "cu") == {"moi"}
    assert tv.thay_the_boi(c, "moi") == set()
    assert tv.da_thay_the(c, "moi") == {"cu"}


def test_huong_dan_dung_chieu():
    """`(con)-[:GUIDED_BY]->(me)`: con là văn bản hướng dẫn, me là văn bản mẹ."""
    c = _corpus(norms=[_n("con"), _n("me")],
                qh=[QuanHe(LoaiQuanHe.HUONG_DAN, "con", "me", da_duyet=True)])
    assert tv.huong_dan_cho(c, "con") == {"me"}
    assert tv.duoc_huong_dan_boi(c, "me") == {"con"}


# ── CAN_CU: bộ lọc đắt nhất của cả framework ────────────────────────────────
def test_tac_dong_toi_loai_can_cu():
    """`CAN_CU` chiếm 59% quan hệ đã duyệt. Không loại thì quá nửa đáp án G4′ là
    văn bản CHỈ VIỆN DẪN — sai một cách trông rất hợp lý."""
    c = _corpus(
        norms=[_n("bi"), _n("sua"), _n("vien_dan")],
        qh=[QuanHe(LoaiQuanHe.SUA_DOI, "sua", "bi", do_tin=0.9, da_duyet=True),
            QuanHe(LoaiQuanHe.CAN_CU, "vien_dan", "bi", do_tin=0.99, da_duyet=True)])
    assert tv.tac_dong_toi(c, "bi") == {"sua"}


def test_tac_dong_toi_loc_do_tin_va_da_duyet():
    c = _corpus(
        norms=[_n("bi"), _n("cao"), _n("thap"), _n("chua_duyet")],
        qh=[QuanHe(LoaiQuanHe.SUA_DOI, "cao", "bi", do_tin=0.9, da_duyet=True),
            QuanHe(LoaiQuanHe.SUA_DOI, "thap", "bi", do_tin=0.5, da_duyet=True),
            QuanHe(LoaiQuanHe.BAI_BO, "chua_duyet", "bi", do_tin=0.99, da_duyet=False)])
    assert tv.tac_dong_toi(c, "bi") == {"cao"}


def test_khong_ep_da_duyet_khi_corpus_khong_trich_tu_dong():
    """`da_duyet` chỉ có nghĩa ở corpus trích tự động. Ép ở corpus biên tập tay thì
    loại sạch quan hệ chỉ vì chúng không mang cờ vốn không tồn tại ở đó."""
    c = _corpus(norms=[_n("bi"), _n("sua")],
                qh=[QuanHe(LoaiQuanHe.SUA_DOI, "sua", "bi")],
                quan_he_tu_dong=False)
    assert tv.tac_dong_toi(c, "bi", nguon="ca_hai") == {"sua"}


def test_tac_dong_toi_bo_canh_tu_tro():
    c = _corpus(norms=[_n("x")],
                qh=[QuanHe(LoaiQuanHe.SUA_DOI, "x", "x", do_tin=0.9, da_duyet=True)])
    assert tv.tac_dong_toi(c, "x") == set()


# ── hai nguồn cùng đổ vào THAY_THE ──────────────────────────────────────────
# G1 dựng trên cạnh REPLACES, G4′ dựng trên Action. Cả hai ra `LoaiQuanHe.THAY_THE`,
# nên nếu không tách được nguồn thì HAI nhóm lấy nhầm tập của nhau — và không cổng
# C1–C5 nào thấy, vì mỗi câu vẫn tự nhất quán.
def test_tach_duoc_hai_nguon_khi_corpus_khai_bao():
    c = _corpus(
        norms=[_n("cu"), _n("moi_canh"), _n("moi_tu_dong")],
        qh=[QuanHe(LoaiQuanHe.THAY_THE, "moi_canh", "cu", da_duyet=True,
                   nguon=NguonQuanHe.CANH),
            QuanHe(LoaiQuanHe.THAY_THE, "moi_tu_dong", "cu", do_tin=0.95,
                   da_duyet=True, nguon=NguonQuanHe.TU_DONG)])
    assert tv.thay_the_boi(c, "cu", nguon="canh") == {"moi_canh"}
    assert tv.thay_the_boi(c, "cu", nguon="tu_dong") == {"moi_tu_dong"}
    assert tv.thay_the_boi(c, "cu", nguon="ca_hai") == {"moi_canh", "moi_tu_dong"}


def test_truong_khai_bao_THANG_proxy():
    """Ca mà proxy đoán SAI: cạnh trực tiếp nhưng loader có gán `do_tin`. Trước khi
    có trường `nguon`, quan hệ này bị xếp nhầm sang G4′ và biến mất khỏi G1."""
    c = _corpus(norms=[_n("cu"), _n("moi")],
                qh=[QuanHe(LoaiQuanHe.THAY_THE, "moi", "cu", do_tin=0.99,
                           da_duyet=True, nguon=NguonQuanHe.CANH)])
    assert tv.nguon_cua(c.quan_he[0]) is NguonQuanHe.CANH
    assert tv.thay_the_boi(c, "cu", nguon="canh") == {"moi"}
    assert tv.thay_the_boi(c, "cu", nguon="tu_dong") == set()


def test_corpus_cu_khong_khai_thi_lui_ve_proxy():
    """Corpus đã xuất trước khi có trường này vẫn phải nạp và dùng được."""
    c = _corpus(norms=[_n("cu"), _n("m1"), _n("m2")],
                qh=[QuanHe(LoaiQuanHe.THAY_THE, "m1", "cu", da_duyet=True),
                    QuanHe(LoaiQuanHe.THAY_THE, "m2", "cu", do_tin=0.9, da_duyet=True)])
    assert tv.thay_the_boi(c, "cu", nguon="canh") == {"m1"}
    assert tv.thay_the_boi(c, "cu", nguon="tu_dong") == {"m2"}


def test_bao_khi_dang_chay_bang_phong_doan():
    """Lùi về proxy thì phải NÓI. Im lặng ở đây nghĩa là người dùng framework tin
    rằng nguồn đã được tách, trong khi nó đang được đoán."""
    c = _corpus(norms=[_n("a"), _n("b")],
                qh=[QuanHe(LoaiQuanHe.THAY_THE, "a", "b", do_tin=0.9, da_duyet=True)])
    assert any("không khai `nguon`" in x for x in tv.kiem_gia_dinh_nguon(c))


def test_khai_bao_day_du_thi_khong_canh_bao_gi():
    c = _corpus(norms=[_n("cu"), _n("m1"), _n("m2")],
                qh=[QuanHe(LoaiQuanHe.THAY_THE, "m1", "cu", da_duyet=True,
                           nguon=NguonQuanHe.CANH),
                    QuanHe(LoaiQuanHe.THAY_THE, "m2", "cu", do_tin=0.9,
                           da_duyet=True, nguon=NguonQuanHe.TU_DONG)])
    assert tv.kiem_gia_dinh_nguon(c) == []


def test_bao_khi_mot_nhanh_rong():
    c = _corpus(norms=[_n("cu"), _n("m1")],
                qh=[QuanHe(LoaiQuanHe.THAY_THE, "m1", "cu", da_duyet=True,
                           nguon=NguonQuanHe.CANH)])
    assert any("G4′ sẽ ra rỗng" in x for x in tv.kiem_gia_dinh_nguon(c))


def test_tac_dong_toi_khong_lay_canh_truc_tiep():
    """G4′ dựng trên Action. Cạnh REPLACES trực tiếp cũng là THAY_THE nhưng KHÔNG
    thuộc lịch sử sửa đổi mà bộ đề hỏi — lấy vào là đáp án dài ra vô cớ."""
    c = _corpus(
        norms=[_n("bi"), _n("canh"), _n("act")],
        qh=[QuanHe(LoaiQuanHe.THAY_THE, "canh", "bi", da_duyet=True,
                   nguon=NguonQuanHe.CANH),
            QuanHe(LoaiQuanHe.SUA_DOI, "act", "bi", do_tin=0.9, da_duyet=True,
                   nguon=NguonQuanHe.TU_DONG)])
    assert tv.tac_dong_toi(c, "bi") == {"act"}


# ── thời gian: khoảng nửa mở ────────────────────────────────────────────────
def _vb_hai_ban() -> Corpus:
    """Điều 1 có hai bản, chuyển giao đúng 2024-11-15."""
    return _corpus(
        norms=[_n("VB")], comps=[_c("d1", "VB")],
        exprs=[_e("cu", "d1", "bản cũ", date(2020, 1, 1), date(2024, 11, 15)),
               _e("moi", "d1", "bản mới", date(2024, 11, 15), None)])


@pytest.mark.parametrize("moc,mong_doi", [
    (date(2024, 11, 14), "cu"),      # trước mốc  -> bản cũ
    (date(2024, 11, 15), "moi"),     # ĐÚNG mốc   -> bản MỚI  (nửa mở)
    (date(2024, 11, 16), "moi"),
    (date(2019, 12, 31), None),      # trước cả bản đầu -> không có bản nào
])
def test_hieu_luc_tai_la_khoang_nua_mo(moc, mong_doi):
    """`[tu, den)`. Đóng hai đầu thì tại mốc chuyển giao có HAI bản cùng khớp và hàm
    trả về bản gặp trước — đúng lỗi off-by-one mà loại `on_boundary` của G2′ được
    dựng ra để bắt (26/80 câu của nhóm)."""
    c = _vb_hai_ban()
    e = tv.hieu_luc_tai(c, "d1", moc)
    assert (e.expression_id if e else None) == mong_doi


def test_ban_hien_hanh_la_ban_khong_co_ngay_dong():
    c = _vb_hai_ban()
    assert tv.ban_hien_hanh(c, "d1").expression_id == "moi"


def test_ban_hien_hanh_tu_choi_khi_corpus_khong_theo_doi_hieu_luc():
    """`hieu_luc_den = None` là "còn hiệu lực" ở corpus này, "không biết" ở corpus
    khác. Trả về bừa thì sinh ra hàng loạt câu khẳng định hiệu lực cho một corpus
    vốn không theo dõi điều đó — và không phát hiện được từ kết quả."""
    c = _corpus(norms=[_n("VB")], comps=[_c("d1", "VB")],
                exprs=[_e("e1", "d1")], theo_doi_hieu_luc=False)
    with pytest.raises(ValueError, match="theo_doi_hieu_luc"):
        tv.ban_hien_hanh(c, "d1")


# ── số Điều ─────────────────────────────────────────────────────────────────
def test_so_dieu_doc_duoc_nhieu_cach_ghi():
    c = _corpus(norms=[_n("VB")],
                comps=[_c("a", "VB", stt="Điều 7"), _c("b", "VB", stt="12"),
                       _c("c", "VB", stt="12a"), _c("d", "VB", stt="Điều 3")])
    assert tv.so_dieu_da_dung(c, "VB") == {3, 7, 12}
    assert tv.so_dieu_lon_nhat(c, "VB") == 12


def test_so_thu_tu_khong_doc_duoc_thi_bo_chu_khong_doan():
    c = _corpus(norms=[_n("VB")],
                comps=[_c("a", "VB", stt="Điều 5"), _c("b", "VB", stt="Phụ lục"),
                       _c("c", "VB", stt=None)])
    assert tv.so_dieu_da_dung(c, "VB") == {5}


def test_so_dieu_lon_nhat_dem_ca_dieu_long_duoi_chuong():
    """G8(b) khẳng định "Điều 155 không tồn tại, lớn nhất là 16". Bỏ sót nhánh lồng
    thì con số tụt xuống và câu hỏi trở thành SAI — hỏi về một Điều có thật."""
    c = _vb_long_nhau()
    assert tv.so_dieu_lon_nhat(c, "VB") == 2


def test_khong_co_dieu_nao_thi_tra_none_chu_khong_phai_0():
    c = _corpus(norms=[_n("VB")], comps=[_c("k", "VB", "Khoan", stt="1")])
    assert tv.so_dieu_lon_nhat(c, "VB") is None


# ── chuyển tiếp ─────────────────────────────────────────────────────────────
def test_chuyen_tiep_dung_nguong_rieng():
    """Ngưỡng 0.9 của `TransitionRule` là thang RIÊNG, không dùng chung 0.85 của
    `Action` (§10.3h) — hai phân bố khác nhau."""
    c = _corpus(norms=[_n("VB")], ct=[
        DieuKhoanChuyenTiep("r1", "VB", "đk", "ap", do_tin=0.95, da_duyet=True),
        DieuKhoanChuyenTiep("r2", "VB", "đk", "ap", do_tin=0.87, da_duyet=True),
        DieuKhoanChuyenTiep("r3", "VB", "đk", "ap", do_tin=0.99, da_duyet=False)])
    assert [t.rule_id for t in tv.chuyen_tiep_cua(c, "VB")] == ["r1"]


# ── số hiệu ─────────────────────────────────────────────────────────────────
def test_norm_theo_so_hieu_tra_moi_ban_ghi_trung():
    """Corpus thật có 228 nhóm trùng số/năm. Trả một giá trị thì các bản còn lại
    biến mất im lặng và đáp án dạng danh sách bị thiếu."""
    c = _corpus(norms=[_n("a", "15/2018/NĐ-CP"), _n("b", "15/2018/NĐ-CP"),
                       _n("c", "16/2018/NĐ-CP")])
    assert sorted(tv.norm_theo_so_hieu(c, "15/2018/NĐ-CP")) == ["a", "b"]


def test_norm_theo_so_hieu_dung_duoc_bo_chuan_hoa_cua_framework():
    """`Ð` (U+00D0) và `Đ` (U+0110) trông giống hệt và dữ liệu thật dùng lẫn lộn."""
    from framework import so_hieu
    c = _corpus(norms=[_n("a", "01/2001/TTLT/BLÐTBXH-BTC")])
    assert tv.norm_theo_so_hieu(c, "01/2001/TTLT/BLĐTBXH-BTC",
                                chuan_hoa=so_hieu.khoa) == ["a"]
