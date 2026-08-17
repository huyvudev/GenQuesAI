"""Kiểm phần KHÔNG cần Neo4j của bộ xuất fixture.

`xuat()` cần đồ thị nên không test được ở đây. Nhưng `gom_muc_tieu()` — bước quyết
định fixture sẽ chứa gì — thì thuần và chạy ngay được. Và nó là chỗ đáng test nhất:
gom thiếu thì fixture thiếu, replay báo "fixture thiếu Norm X", và người ta sẽ đi sửa
bộ xuất **sau khi** đã chờ Neo4j chạy xong một lượt.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.trich_fixture import CAN_CAY_DAY, gom_muc_tieu

GOC = Path(__file__).resolve().parent.parent
KY_VONG = GOC / "tests" / "golden" / "ky_vong.jsonl"


@pytest.fixture(scope="module")
def muc_tieu():
    if not KY_VONG.exists():
        pytest.skip("chưa có ky_vong.jsonl")
    kv = [json.loads(x) for x in
          KY_VONG.read_text(encoding="utf-8").splitlines() if x.strip()][1:]
    return gom_muc_tieu(kv), kv


def test_gom_du_moi_norm_ma_ky_vong_nhac_toi(muc_tieu):
    """Sót một `norm_id` là replay đỏ ở đúng câu đó — sau khi đã chờ Neo4j xuất xong."""
    mt, kv = muc_tieu
    can = set()
    for it in kv:
        for s in it["su_kien"]:
            for k in ("norm", "con", "me"):
                if s.get(k):
                    can.add(s[k])
            for k in ("ky_vong", "ky_vong_chua", "ky_vong_ids"):
                if isinstance(s.get(k), list):
                    can.update(x for x in s[k] if x)
    assert not (can - mt["norm_hat"]), f"sót {sorted(can - mt['norm_hat'])[:5]}"


def test_ky_vong_kieu_so_khong_bi_hieu_thanh_danh_sach(muc_tieu):
    """`ky_vong` là DANH SÁCH ở `thay_the_boi` nhưng là SỐ NGUYÊN ở `so_dieu_lon_nhat`.
    Cùng tên khoá, hai kiểu — từng làm bộ gom nổ `TypeError`."""
    mt, kv = muc_tieu
    assert all(isinstance(x, str) for x in mt["norm_hat"])
    # Số Điều của G8(b) (6, 16, 29, 67…) không được lọt vào tập văn bản: chúng sẽ
    # thành `MATCH (n:Norm {norm_id:'16'})` — không khớp gì, im lặng, và fixture
    # thiếu đúng những gì nó tưởng đã lấy.
    so_dieu = {str(s["ky_vong"]) for it in kv for s in it["su_kien"]
               if s["loai"] == "so_dieu_lon_nhat"}
    assert so_dieu, "không có sự kiện so_dieu_lon_nhat — test này không kiểm được gì"
    assert not (so_dieu & mt["norm_hat"])


def test_moi_su_kien_can_cay_day_deu_yeu_cau_tron_cay(muc_tieu):
    """Sự kiện về SỐ ĐIỀU chỉ đúng khi có trọn cây. Xuất nửa cây thì
    `so_dieu_lon_nhat` tụt và replay đỏ vì fixture, không vì A1."""
    mt, kv = muc_tieu
    can = {s["norm"] for it in kv for s in it["su_kien"]
           if s["loai"] in CAN_CAY_DAY and s.get("norm")}
    assert can <= mt["norm_cay_day"]
    # G7 (90 câu) + G8(b) tra bằng số hiệu -> ~69 văn bản, đủ nhỏ để xuất trọn cây
    assert len(mt["norm_cay_day"]) < 200, "tập cần trọn cây phình to, fixture sẽ nặng"


def test_ky_vong_phu_dinh_duoc_gom_rieng(muc_tieu):
    """G8(a) không replay được trên tập con -> phải chốt lúc xuất. Gom sót thì nó
    lặng lẽ pass trên corpus nghèo."""
    mt, kv = muc_tieu
    can = {s["so_hieu"] for it in kv for s in it["su_kien"]
           if s["loai"] == "khong_co_norm"}
    assert can and can == mt["so_hieu_phai_vang"]


def test_gom_du_expression(muc_tieu):
    mt, kv = muc_tieu
    can = {s["expr"] for it in kv for s in it["su_kien"] if s.get("expr")}
    assert can == mt["expr"]
