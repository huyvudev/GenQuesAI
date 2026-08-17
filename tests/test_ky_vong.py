"""Kiểm chính hợp đồng golden — chạy offline, không cần Neo4j.

Bộ replay (`test_su_kien.py`) chỉ mạnh bằng file kỳ vọng mà nó đọc. Nếu file đó trôi
khỏi bộ đề, hoặc trích thiếu một nhóm, thì replay vẫn xanh trong khi chẳng còn kiểm
đúng thứ cần kiểm. Các test dưới đây canh đúng chỗ đó.
"""
from __future__ import annotations

import hashlib
from collections import Counter, defaultdict

import pytest

from tests.conftest import BO_DE
from tests.trich_ky_vong import chung_cat

# Nhóm nào BẮT BUỘC sinh ra loại kỳ vọng nào. Đây là chỗ ghi lại "nhóm này được đo
# bằng gì" — trích thiếu thì nhóm đó lặng lẽ không còn được golden bảo vệ.
BAT_BUOC = {
    "G1": {"thay_the_boi", "so_hieu_norm"},
    "G2": {"expr_dong_tai", "expr_hieu_luc_tai"},
    "G3": {"huong_dan", "thay_the_boi"},
    "G4": {"tac_dong_toi"},
    "G5": {"chuyen_tiep"},
    "G6": {"huong_dan", "cap_bac"},
    "G7": {"dieu_hien_hanh"},
}


def test_neo_dung_ban_bo_de_da_freeze(ky_vong_meta):
    """Bộ đề đổi mà kỳ vọng không sinh lại thì mọi test sau đó kiểm một hợp đồng đã
    lỗi thời — và vẫn xanh. Đây là dạng hỏng nguy hiểm nhất của một bộ golden."""
    if not BO_DE.exists():
        pytest.skip(f"thiếu {BO_DE}")
    thuc = hashlib.sha256(BO_DE.read_bytes()).hexdigest()
    assert ky_vong_meta["sha256_nguon"] == thuc, (
        "ky_vong.jsonl sinh từ một bản eval_set.jsonl KHÁC bản đang có.\n"
        "  Sinh lại: python -m tests.trich_ky_vong\n"
        "  Rồi ĐỌC diff của ky_vong.jsonl trước khi commit — nếu bộ đề không đổi thì "
        "hợp đồng cũng không được đổi.")


def test_du_400_item(ky_vong, ky_vong_meta):
    assert ky_vong_meta["so_item"] == 400
    assert len(ky_vong) == 400


def test_moi_nhom_sinh_du_loai_ky_vong(ky_vong):
    theo: dict[str, set] = defaultdict(set)
    for it in ky_vong:
        theo[it["nhom"]].update(s["loai"] for s in it["su_kien"])
    for nhom, can in BAT_BUOC.items():
        assert can <= theo[nhom], (
            f"{nhom} thiếu loại kỳ vọng {sorted(can - theo[nhom])} — nhóm này sẽ "
            f"không còn được golden bảo vệ ở đúng chỗ đặc trưng của nó")


def test_moi_item_deu_co_ky_vong_chan_tru_G8d(ky_vong):
    """Item chỉ toàn kỳ vọng mức `canh_bao` là item KHÔNG được bảo vệ. Chỉ G8(d)
    được phép, vì nó cố ý không khẳng định gì về đồ thị."""
    yeu = [it["id"] for it in ky_vong
           if not any(s["muc"] == "chan" for s in it["su_kien"])]
    ngoai_le = [i for i in yeu
                if any(s["loai"] == "khong_kiem_duoc_bang_corpus"
                       for it in ky_vong if it["id"] == i for s in it["su_kien"])]
    assert set(yeu) == set(ngoai_le), f"item không có kỳ vọng chặn nào: {sorted(set(yeu) - set(ngoai_le))}"


def test_khong_co_tham_chieu_rong(ky_vong):
    """Kỳ vọng trỏ vào `None` thì replay hoặc nổ khó hiểu, hoặc tệ hơn là pass."""
    xau = [(it["id"], s) for it in ky_vong for s in it["su_kien"]
           for k in ("norm", "expr", "con", "me", "so_hieu")
           if k in s and s[k] in (None, "")]
    assert not xau, f"{len(xau)} kỳ vọng có tham chiếu rỗng, vd {xau[:3]}"


def test_moi_su_kien_deu_khai_muc(ky_vong):
    hop_le = {"chan", "canh_bao", "ghi_chu"}
    xau = {s.get("muc") for it in ky_vong for s in it["su_kien"]} - hop_le
    assert not xau, f"mức không hợp lệ: {xau}"


def test_trich_lai_cho_ket_qua_y_het(bo_de, ky_vong):
    """Bộ trích phải deterministic. Không thì `ky_vong.jsonl` trôi mỗi lần chạy và
    diff của nó hết đọc được — đúng vấn đề mà cả bộ này sinh ra để tránh."""
    lai = chung_cat(bo_de)
    assert lai == ky_vong


def test_G4_kỳ_vọng_neu_du_ca_id_lan_so_hieu(ky_vong):
    """Kỳ vọng đắt nhất của bộ (bắt lỗi rơi bộ lọc CAN_CU) phải có đủ hai vế: `id`
    bắt lỗi truy vấn, `so_hieu` bắt lỗi gộp trùng. Thiếu vế nào cũng lọt một loại."""
    ds = [s for it in ky_vong if it["nhom"] == "G4"
          for s in it["su_kien"] if s["loai"] == "tac_dong_toi"]
    assert len(ds) == 40
    for s in ds:
        assert s["ky_vong_ids"] and s["ky_vong_so_hieu"]
        assert len(s["ky_vong_so_hieu"]) >= 2, "G4′ là câu hỏi DANH SÁCH (§4.5)"


def test_G2_co_du_ba_loai_moc_thoi_gian(ky_vong, bo_de):
    """`on_boundary` là loại DUY NHẤT kỳ vọng `phai=False` — nó là phép kiểm nửa mở.
    Mất nó thì lỗi off-by-one tại mốc chuyển giao không còn ai bắt."""
    ds = [s for it in ky_vong if it["nhom"] == "G2"
          for s in it["su_kien"] if s["loai"] == "expr_hieu_luc_tai"]
    dem = Counter(s["phai"] for s in ds)
    mong = Counter(r["as_of_kind"] == "on_boundary" for r in bo_de if r["group"] == "G2")
    assert dem[False] == mong[True] == 26
    assert dem[True] == 54


def test_so_luong_ky_vong_khong_tut(ky_vong_meta):
    """Chốt ngược: sửa bộ trích làm rơi một nhánh thì số sự kiện tụt, và test này đỏ
    trước khi ai kịp tin rằng "vẫn xanh nghĩa là vẫn ổn"."""
    assert ky_vong_meta["so_su_kien"] >= 2016
