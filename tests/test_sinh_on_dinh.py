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


def _g7_corpus(so_vb: int = 6, xao_id=None):
    """Corpus dựng tay cho G7 — sau A1, bộ sinh đọc thẳng `Corpus`.

    `xao_id` đổi THỨ TỰ CHÈN của dict norms — mô phỏng "nguồn trả thứ tự khác".
    Sau A1 nguồn phi xác định duy nhất còn lại là thứ tự duyệt dict, và bộ sinh phải
    bất biến với nó.
    """
    from datetime import date
    from framework.schema import Component, Corpus, CorpusMeta, Expression, Norm

    c = Corpus(meta=CorpusMeta(ten="thu", theo_doi_hieu_luc=True))
    thu_tu = list(range(so_vb))
    if xao_id is not None:
        random.Random(xao_id).shuffle(thu_tu)
    payload = {}
    for i in thu_tu:
        nid = f"vb{i}"
        c.norms[nid] = Norm(nid, f"{10 + i}/2024/NĐ-CP", tieu_de=f"Nghị định số {10+i}",
                            loai_vb="NghiDinh", ngay_hieu_luc=date(2024, 1, 1))
        for so, ten in ((i + 1, TIEU_DE[i % len(TIEU_DE)]), (99, "Điều khoản dự phòng về báo cáo")):
            cid = f"{nid}::d{so}"
            c.components[cid] = Component(cid, nid, "Dieu", None, str(so), ten, so)
            eid = f"{nid}::Dieu {so}@2024-01-01"
            c.expressions[eid] = Expression(eid, cid, _noi_dung(i), date(2024, 1, 1), None)
            payload[point_id(eid, 0)] = {"text": _noi_dung(i), "n_parts": 1, "tieu_de": ten}
        # van ban khac co Dieu cung so — bay cross-norm
        nid2 = f"khac{i}"
        c.norms[nid2] = Norm(nid2, f"{50 + i}/2024/TT-BYT", tieu_de="Thông tư khác",
                             ngay_hieu_luc=date(2024, 1, 1))
        cid2 = f"{nid2}::d{i + 1}"
        c.components[cid2] = Component(cid2, nid2, "Dieu", None, str(i + 1), "Tiêu đề đủ dài cho bẫy", 0)
        eid2 = f"{nid2}::Dieu {i + 1}@2024-01-01"
        c.expressions[eid2] = Expression(eid2, cid2, _noi_dung(i), date(2024, 1, 1), None)
        payload[point_id(eid2, 0)] = {"text": _noi_dung(i), "n_parts": 1}
    c.dung_chi_muc()
    return c, _Store(payload)


def _g7_sinh(c, store, n=4):
    items, _ = g7_content.build(c, store, n=n, pool=100)
    return [dataclasses.asdict(x) for x in items]


def test_g7_khong_phu_thuoc_thu_tu_dau_vao():
    """Sau A1, nguồn phi xác định là THỨ TỰ DUYỆT DICT của `Corpus`. Bộ sinh sắp
    chuẩn theo `expr_id` trước khi trộn nên phải bất biến với thứ tự chèn."""
    c0, store = _g7_corpus()
    chuan = _g7_sinh(c0, store)
    assert chuan, "dữ liệu giả không sinh ra item nào — test không kiểm được gì"
    for lan in range(5):
        c2, store2 = _g7_corpus(xao_id=lan)
        assert _g7_sinh(c2, store2) == chuan, f"lệch khi đổi thứ tự chèn (lần {lan})"


def test_g7_dang_cau_khong_phu_thuoc_thu_tu():
    c0, store = _g7_corpus()
    chuan = [(x["question_form"], x["persona"], x["question_template"])
             for x in _g7_sinh(c0, store)]
    c2, store2 = _g7_corpus(xao_id=99)
    dao = [(x["question_form"], x["persona"], x["question_template"])
           for x in _g7_sinh(c2, store2)]
    assert dao == chuan


def test_g7_bay_xac_dinh_va_du():
    """Bẫy (anh em + cross-norm) là đầu vào của nhãn `retriever_nham` — phải có, và
    phải y hệt giữa hai lần dựng."""
    c0, store = _g7_corpus()
    a = [x["distractor_ids"] for x in _g7_sinh(c0, store)]
    c2, store2 = _g7_corpus(xao_id=7)
    b = [x["distractor_ids"] for x in _g7_sinh(c2, store2)]
    assert a == b and all(a), "bẫy trống hoặc trôi"


# ── G8 ──────────────────────────────────────────────────────────────────────
def _g8_corpus(so_vb: int = 400):
    from datetime import date
    from framework.schema import Component, Corpus, CorpusMeta, Norm
    c = Corpus(meta=CorpusMeta(ten="thu", theo_doi_hieu_luc=True))
    for i in range(so_vb):
        nid = f"n{i}"
        c.norms[nid] = Norm(nid, f"{i % 90 + 1}/{2015 + i % 11}/NĐ-CP",
                            ngay_hieu_luc=date(2015 + i % 11, 6, 1))
        for so in range(1, 18):
            cid = f"{nid}::d{so}"
            c.components[cid] = Component(cid, nid, "Dieu", None, str(so), f"Điều {so}", so)
    c.dung_chi_muc()
    return c


def test_g8_khong_con_cau_trung():
    """Lỗi đã sửa: `NGOAI_PHAM_VI` có 5 chủ đề nhưng quota (d) ở n=25 là 7, vòng lặp
    quay vòng -> G8-0003 ≡ G8-0020 và G8-0004 ≡ G8-0024."""
    items, _ = g8_unanswerable.build(_g8_corpus(), store=None, n=25)
    cau = [x.user_input for x in items]
    assert len(set(cau)) == len(cau), \
        f"còn {len(cau) - len(set(cau))} câu trùng: {[c for c in cau if cau.count(c) > 1][:3]}"


def test_g8_van_du_quota():
    """Chặn trùng không được đổi lại bằng việc thiếu câu."""
    items, _ = g8_unanswerable.build(_g8_corpus(), store=None, n=25)
    assert len(items) == 25


def test_g8_moi_chu_de_ngoai_pham_vi_dung_dung_mot_lan():
    items, _ = g8_unanswerable.build(_g8_corpus(), store=None, n=25)
    cd = [x.reference_fields["chu_de_ngoai_pham_vi"]
          for x in items if x.cong_thuc == "d"]
    assert len(set(cd)) == len(cd)
    assert set(cd) <= set(g8_unanswerable.NGOAI_PHAM_VI)


def test_g8_du_bon_cong_thuc():
    items, _ = g8_unanswerable.build(_g8_corpus(), store=None, n=25)
    import collections
    dem = collections.Counter(x.cong_thuc for x in items)
    assert set(dem) == {"a", "b", "c", "d"}
    assert all(v >= 5 for v in dem.values()), dem


@pytest.mark.parametrize("n", [4, 12, 25, 40, 80])
def test_g8_khong_bao_gio_trung_o_moi_co_bo_de(n):
    """Quota (d) tăng theo n; ở n=80 nó vượt số chủ đề có sẵn và phải chuyển phần dư
    sang a/b/c chứ không lặp lại chủ đề."""
    items, _ = g8_unanswerable.build(_g8_corpus(), store=None, n=n)
    cau = [x.user_input for x in items]
    assert len(set(cau)) == len(cau), f"n={n}: có câu trùng"
    assert len(items) == n, f"n={n}: chỉ sinh {len(items)}"


def test_g8_so_chu_de_du_cho_quota_hien_tai():
    """Chốt ngược: rút ngắn `NGOAI_PHAM_VI` xuống dưới quota (d) thì test này đỏ
    trước khi ai kịp sinh lại bộ đề với câu trùng."""
    assert len(g8_unanswerable.NGOAI_PHAM_VI) >= 25 - 3 * (25 // 4)
