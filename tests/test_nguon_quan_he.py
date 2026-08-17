"""`QuanHe.nguon` phải sống sót qua vòng ghi–đọc JSONL.

JSONL là **định dạng trao đổi** của framework: người dùng xuất corpus của họ ra rồi
nạp lại ở máy khác. Trường nào rơi mất ở khâu này thì mọi thứ dựng trên nó im lặng
lùi về phỏng đoán — đúng thứ trường `nguon` sinh ra để chấm dứt.

Ghi chú lịch sử: chính vòng xuất-rồi-nạp-lại này từng lộ ra chuyện lấy mẫu đầu-dãy
làm báo cáo năng lực lạc quan giả (ROADMAP §B3). Một loader thì luôn vừa khít với
chính nó, kể cả khi thiết kế sai.
"""
from __future__ import annotations

import json

import pytest

from framework import truy_van as tv
from framework.capabilities import danh_gia
from framework.jsonl_loader import JsonlLoader, JsonlWriter
from framework.schema import (CorpusMeta, LoaiQuanHe, NguonQuanHe, Norm, QuanHe,
                              nap, sang_dict)


QH = [
    QuanHe(LoaiQuanHe.THAY_THE, "moi", "cu", da_duyet=True, nguon=NguonQuanHe.CANH),
    QuanHe(LoaiQuanHe.SUA_DOI, "sua", "cu", do_tin=0.9, da_duyet=True,
           nguon=NguonQuanHe.TU_DONG),
    QuanHe(LoaiQuanHe.HUONG_DAN, "con", "cu", da_duyet=True),      # cố ý KHÔNG khai
]


@pytest.fixture
def thu_muc(tmp_path):
    with JsonlWriter(tmp_path) as w:
        w.meta(CorpusMeta(ten="thu", theo_doi_hieu_luc=True, quan_he_tu_dong=True))
        for nid in ("cu", "moi", "sua", "con"):
            w.ghi("norms.jsonl", Norm(nid, f"{nid}/2020/NĐ-CP"))
        for q in QH:
            w.ghi("quan_he.jsonl", q)
    return tmp_path


def test_ghi_ra_dung_chuoi_khong_phai_ten_enum(thu_muc):
    """`NguonQuanHe.CANH` phải ra `"canh"`. Ghi ra `"NguonQuanHe.CANH"` thì file vẫn
    đọc được bằng mắt nhưng `NguonQuanHe(...)` sẽ ném và trường rơi về None."""
    dong = [json.loads(x) for x in
            (thu_muc / "quan_he.jsonl").read_text(encoding="utf-8").splitlines()]
    assert dong[0]["nguon"] == "canh"
    assert dong[1]["nguon"] == "tu_dong"
    assert "nguon" not in dong[2], "không khai thì không ghi, đừng bịa giá trị"


def test_doc_lai_giu_nguyen_nguon(thu_muc):
    c = nap(JsonlLoader(thu_muc))
    theo = {(q.loai, q.tu_norm_id): q.nguon for q in c.quan_he}
    assert theo[(LoaiQuanHe.THAY_THE, "moi")] is NguonQuanHe.CANH
    assert theo[(LoaiQuanHe.SUA_DOI, "sua")] is NguonQuanHe.TU_DONG
    assert theo[(LoaiQuanHe.HUONG_DAN, "con")] is None


def test_truy_van_tach_dung_sau_khi_doc_lai(thu_muc):
    c = nap(JsonlLoader(thu_muc))
    assert tv.thay_the_boi(c, "cu", nguon="canh") == {"moi"}
    assert tv.thay_the_boi(c, "cu", nguon="tu_dong") == set()
    assert tv.tac_dong_toi(c, "cu") == {"sua"}


def test_nguon_la_thi_ve_None_chu_khong_no(tmp_path):
    """Corpus của người khác có thể ghi `nguon` bằng từ vựng riêng. Ném ra thì cả
    corpus không nạp được; đoán thì sai im lặng. Về `None` rồi cảnh báo là đúng."""
    with JsonlWriter(tmp_path) as w:
        w.meta(CorpusMeta(ten="la", theo_doi_hieu_luc=True))
        w.ghi("norms.jsonl", Norm("a", "1/2020/NĐ-CP"))
        w.ghi("norms.jsonl", Norm("b", "2/2020/NĐ-CP"))
    (tmp_path / "quan_he.jsonl").write_text(json.dumps({
        "loai": "thay_the", "tu_norm_id": "a", "den_norm_id": "b",
        "nguon": "curated_by_hand"}, ensure_ascii=False) + "\n", encoding="utf-8")
    c = nap(JsonlLoader(tmp_path))
    assert len(c.quan_he) == 1 and c.quan_he[0].nguon is None


def test_sang_dict_bo_qua_nguon_rong():
    assert "nguon" not in sang_dict(QuanHe(LoaiQuanHe.THAY_THE, "a", "b"))


def test_bao_cao_nang_luc_dem_dung_tap_ma_bo_sinh_se_dung(thu_muc):
    """G1 chỉ nhận cạnh trực tiếp. Trước khi có `nguon`, `danh_gia` đếm cả nhánh
    trích tự động — đo trên corpus mẫu thật, nó báo 38 ứng viên G1 trong khi chỉ 19
    dùng được. Báo cáo năng lực lạc quan giả là thứ khiến người ta sinh đề rồi mới
    phát hiện thiếu."""
    c = nap(JsonlLoader(thu_muc))
    theo = {x.ma: x for x in danh_gia(c)}
    assert theo["G1"].ung_vien == 1, "chỉ cạnh CANH mới tính cho G1"
