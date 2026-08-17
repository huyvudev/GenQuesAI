"""Bộ sinh phải cho ra CÙNG một bộ đề khi nguồn trả về cùng dữ liệu — bất kể thứ tự.

Chạy offline bằng `neo`/`store` giả. Đây là chỗ duy nhất kiểm được tính chất này mà
không cần Neo4j, và nó quan trọng gấp đôi vì A1: sau A1, ứng viên đến từ duyệt cây
`Corpus` chứ không từ Cypher, và **thứ tự duyệt cây không có lý do gì trùng thứ tự
Neo4j**. Bộ sinh nào còn phụ thuộc thứ tự thì A1 sẽ làm đổi toàn bộ bộ đề của nó, và
diff sẽ đỏ vì lý do không liên quan gì tới đúng/sai.
"""
from __future__ import annotations

import dataclasses
import random
from datetime import date

import pytest

from generator import g7_content, g8_unanswerable
from generator.common import point_id


# ── nhân đôi test: Qdrant giả ───────────────────────────────────────────────
class _Point:
    def __init__(self, pid, payload):
        self.id, self.payload = pid, payload


class _Client:
    def __init__(self, theo_id):
        self.theo_id = theo_id

    def retrieve(self, collection, ids, with_payload=True):
        return [_Point(i, self.theo_id[i]) for i in ids if i in self.theo_id]


class _Store:
    collection = "thu"

    def __init__(self, theo_id):
        self.client = _Client(theo_id)


def _noi_dung(i: int) -> str:
    """Đủ dài để qua MIN_LEN=300, đủ ngắn để dưới MAX_LEN=2500.

    KHÔNG được có khoảng trắng ở hai đầu: `gold.chunk_span()` lưu `text` nguyên vẹn
    còn `gold.gate_c1()` so `text[start:end].strip()` với nó, nên chunk nào có
    khoảng trắng thừa ở đầu/cuối sẽ rớt C1 với lý do `offset_mismatch`. Dữ liệu thật
    không có (G7 pass 90/90) nên chỗ này chưa cắn ai, nhưng nó là bẫy có thật.
    """
    return (f"Nội dung quy phạm số {i}. "
            + "Cơ quan có thẩm quyền thực hiện. " * 15).strip()


# ── G7 ──────────────────────────────────────────────────────────────────────
TIEU_DE = [
    "Bố trí công tác sau khi miễn nhiệm Chấp hành viên",
    "Trình tự cấp giấy chứng nhận đủ điều kiện kinh doanh",
    "Hồ sơ đề nghị cấp lại giấy phép hoạt động đo đạc",
    "Chế độ báo cáo định kỳ của tổ chức hành nghề",
    "Điều kiện đối với người đứng đầu cơ sở kiểm định",
    "Thẩm quyền quyết định thành lập hội đồng thẩm định",
]


def _g7_du_lieu(so_vb: int = 6):
    rows, payload = [], {}
    for i in range(so_vb):
        expr = f"vb{i}::Dieu {i + 1}@2024-01-01"
        rows.append({
            "norm_id": f"vb{i}", "so_hieu": f"{10 + i}/2024/NĐ-CP",
            "norm_tieu_de": f"Nghị định số {10 + i}", "linh_vuc": [],
            "loai_vb": "NghiDinh", "comp_id": f"c{i}", "stt": str(i + 1),
            "dieu_tieu_de": TIEU_DE[i % len(TIEU_DE)],
            "duong_dan": f"Điều {i + 1}", "expr_id": expr,
            "anh_em": [f"vb{i}::Dieu 99@2024-01-01"],
        })
        for e in (expr, f"vb{i}::Dieu 99@2024-01-01", f"khac{i}::Dieu {i + 1}@2024-01-01"):
            payload[point_id(e, 0)] = {"text": _noi_dung(i), "n_parts": 1,
                                       "tieu_de": TIEU_DE[i % len(TIEU_DE)]}
    return rows, _Store(payload)


class _NeoG7:
    """Trả `rows` đúng thứ tự được đưa vào — để mô phỏng nguồn đổi thứ tự."""

    def __init__(self, rows, bay_theo_stt=None):
        self.rows, self.bay = rows, bay_theo_stt or {}

    def run(self, q, **kw):
        if q is g7_content.SELECT:
            return list(self.rows)
        if q is g7_content.BAY_KHAC_VB:
            return list(self.bay.get(kw["stt"], []))
        raise AssertionError(f"truy vấn lạ: {q[:40]}")


def _g7_sinh(rows, store, n=4):
    items, _ = g7_content.build(_NeoG7(rows), store, n=n, pool=100)
    return [dataclasses.asdict(x) for x in items]


def test_g7_khong_phu_thuoc_thu_tu_dau_vao():
    """Tính chất cốt lõi. Trước khi sửa, `rng.shuffle` chạy thẳng trên thứ tự nguồn
    trả về, nên nguồn đổi thứ tự là bộ câu đổi — đo thật 87/90 câu lệch."""
    rows, store = _g7_du_lieu()
    chuan = _g7_sinh(rows, store)
    assert chuan, "dữ liệu giả không sinh ra item nào — test không kiểm được gì"

    for lan in range(6):
        xao = list(rows)
        random.Random(lan).shuffle(xao)
        assert _g7_sinh(xao, store) == chuan, f"lệch khi nguồn đảo thứ tự (lần {lan})"
    assert _g7_sinh(list(reversed(rows)), store) == chuan


def test_g7_dang_cau_khong_phu_thuoc_thu_tu():
    """Dạng câu (`lookup`/`situation`), persona và khuôn đều gán theo vị trí vòng lặp
    — chính là 14–16 câu lệch đã đo. Sắp chuẩn trước khi trộn là cái chốt cho cả ba."""
    rows, store = _g7_du_lieu()
    chuan = [(x["question_form"], x["persona"], x["question_template"])
             for x in _g7_sinh(rows, store)]
    dao = [(x["question_form"], x["persona"], x["question_template"])
           for x in _g7_sinh(list(reversed(rows)), store)]
    assert dao == chuan


def test_g7_bay_khong_phu_thuoc_thu_tu_nguon_tra_ve():
    """Bẫy cross-norm — 81/90 câu lệch trước khi sửa. Bẫy là đầu vào của nhãn triage
    `retriever_nham`, nên bẫy trôi thì hai lần chấm không so được với nhau."""
    rows, store = _g7_du_lieu()
    bay = {r["stt"]: [{"ex": f"khac{i}::Dieu {i + 1}@2024-01-01"}]
           for i, r in enumerate(rows)}
    a = [x["distractor_ids"] for x in
         [dataclasses.asdict(x) for x in
          g7_content.build(_NeoG7(rows, bay), store, n=4, pool=100)[0]]]
    b = [x["distractor_ids"] for x in
         [dataclasses.asdict(x) for x in
          g7_content.build(_NeoG7(list(reversed(rows)), bay), store, n=4, pool=100)[0]]]
    assert a == b and any(a), "bẫy trống -> test không kiểm được gì"


def test_g7_cypher_sap_xep_xac_dinh():
    """Phần thứ tự nằm TRONG Cypher không mô phỏng được bằng nguồn giả — kiểm bằng
    chính câu truy vấn. Thô, nhưng bắt được đúng ca đã xảy ra: `LIMIT` không kèm
    `ORDER BY`."""
    bay = g7_content.BAY_KHAC_VB
    assert "ORDER BY" in bay and bay.index("ORDER BY") < bay.index("LIMIT"), (
        "BAY_KHAC_VB có LIMIT mà không ORDER BY -> Neo4j trả hai hàng bất kỳ")
    sel = g7_content.SELECT
    assert "ORDER BY n.ngay_hieu_luc DESC, e.expr_id" in sel, (
        "thiếu khoá phụ: hàng nghìn văn bản chung ngày hiệu lực, LIMIT $pool sẽ cắt "
        "vào giữa khối bằng điểm và TẬP ứng viên đổi giữa hai lần chạy")
    assert "ORDER BY ex" in sel, "subquery anh em thiếu ORDER BY trước collect"


# ── G8 ──────────────────────────────────────────────────────────────────────
class _NeoG8:
    def __init__(self, so_vb: int = 400):
        self.mau = [{"so_hieu": f"{i % 90 + 1}/{2015 + i % 11}/NĐ-CP",
                     "norm_id": f"n{i}", "hl": date(2015 + i % 11, 6, 1)}
                    for i in range(so_vb)]

    def run(self, q, **kw):
        if q is g8_unanswerable.MAU_SO_HIEU:
            return list(self.mau)
        if q is g8_unanswerable.DIEU_CUA_VB:
            return [{"ds": [str(x) for x in range(1, 18)]}]
        if q is g8_unanswerable.TON_TAI:
            return [{"c": 0}]                     # số bịa ra không trùng văn bản thật
        raise AssertionError(f"truy vấn lạ: {q[:40]}")


def test_g8_khong_con_cau_trung():
    """Lỗi đã sửa: `NGOAI_PHAM_VI` có 5 chủ đề nhưng quota (d) ở n=25 là 7, vòng lặp
    quay vòng -> G8-0003 ≡ G8-0020 và G8-0004 ≡ G8-0024."""
    items, _ = g8_unanswerable.build(_NeoG8(), store=None, n=25)
    cau = [x.user_input for x in items]
    assert len(set(cau)) == len(cau), \
        f"còn {len(cau) - len(set(cau))} câu trùng: {[c for c in cau if cau.count(c) > 1][:3]}"


def test_g8_van_du_quota():
    """Chặn trùng không được đổi lại bằng việc thiếu câu."""
    items, _ = g8_unanswerable.build(_NeoG8(), store=None, n=25)
    assert len(items) == 25


def test_g8_moi_chu_de_ngoai_pham_vi_dung_dung_mot_lan():
    items, _ = g8_unanswerable.build(_NeoG8(), store=None, n=25)
    cd = [x.reference_fields["chu_de_ngoai_pham_vi"]
          for x in items if x.cong_thuc == "d"]
    assert len(set(cd)) == len(cd)
    assert set(cd) <= set(g8_unanswerable.NGOAI_PHAM_VI)


def test_g8_du_bon_cong_thuc():
    items, _ = g8_unanswerable.build(_NeoG8(), store=None, n=25)
    import collections
    dem = collections.Counter(x.cong_thuc for x in items)
    assert set(dem) == {"a", "b", "c", "d"}
    assert all(v >= 5 for v in dem.values()), dem


@pytest.mark.parametrize("n", [4, 12, 25, 40, 80])
def test_g8_khong_bao_gio_trung_o_moi_co_bo_de(n):
    """Quota (d) tăng theo n; ở n=80 nó vượt số chủ đề có sẵn và phải chuyển phần dư
    sang a/b/c chứ không lặp lại chủ đề."""
    items, _ = g8_unanswerable.build(_NeoG8(), store=None, n=n)
    cau = [x.user_input for x in items]
    assert len(set(cau)) == len(cau), f"n={n}: có câu trùng"
    assert len(items) == n, f"n={n}: chỉ sinh {len(items)}"


def test_g8_so_chu_de_du_cho_quota_hien_tai():
    """Chốt ngược: rút ngắn `NGOAI_PHAM_VI` xuống dưới quota (d) thì test này đỏ
    trước khi ai kịp sinh lại bộ đề với câu trùng."""
    assert len(g8_unanswerable.NGOAI_PHAM_VI) >= 25 - 3 * (25 // 4)
