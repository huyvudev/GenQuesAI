"""Kiểm bộ soi bộ đề — luật cảnh báo và tính toàn vẹn của trang HTML dựng ra.

Trang này không có backend nên không có gì chạy thử được ở phía máy chủ; hỏng thì
hỏng im lặng trong trình duyệt. Hai thứ đáng kiểm bằng máy:

  · `canh_bao()` — phần mang giá trị thật, và là thứ dễ sai lặng lẽ nhất: một luật
    viết hụt điều kiện thì nó ngừng báo, và bộ soi trông vẫn "sạch".
  · dữ liệu nhúng — chuỗi `</script>` trong nội dung văn bản luật sẽ đóng thẻ sớm và
    làm trắng cả trang. Văn bản QPPL không có HTML, nhưng bộ đề còn nhúng cả câu trả
    lời của LLM ở `c4_tra_loi_khong_ngu_canh`, và cái đó thì không hứa gì cả.
"""
from __future__ import annotations

import json
import re

import pytest

from generator.soi_bo_de import LUAT, canh_bao, dung_html


def _it(**kw) -> dict:
    goc = {"id": "X-0000", "group": "G7", "question_form": "lookup",
           "user_input": "Điều 5 của 15/2018/NĐ-CP quy định gì?",
           "reference": "nội dung điều 5", "gates": {"C1": "pass"},
           "gold_spans": [{"expr_id": "e", "part": 0, "chunk_id": "c",
                           "start": 0, "end": 9, "chunk_text_sha256": "ab"}],
           "reference_contexts": ["nội dung"], "distractor_ids": ["d1"]}
    goc.update(kw)
    return goc


def _ma(rows) -> set[str]:
    return {m for ds in canh_bao(rows).values() for m in ds}


# ── từng luật: phải BÁO khi sai, và IM khi đúng ─────────────────────────────
def test_khong_bao_gi_khi_moi_thu_binh_thuong():
    assert canh_bao([_it()]) == {}


def test_bat_cau_trung():
    """Lỗi thật đã gặp: G8-0003 ≡ G8-0020 vì NGOAI_PHAM_VI ngắn hơn quota."""
    r = [_it(id="A"), _it(id="B")]           # cùng user_input
    assert canh_bao(r).keys() == {"A", "B"}
    assert "trung_cau" in canh_bao(r)["A"]


def test_bat_situation_lo_so_hieu():
    """Câu `situation` cố ý GIẤU định danh — nêu ra là mồi từ khoá cho BM25 (§5.2)."""
    xau = _it(question_form="situation",
              user_input="Quy định hiện hành tại 15/2018/NĐ-CP thế nào?")
    tot = _it(question_form="situation",
              user_input="Quy định hiện hành về cấp giấy phép xây dựng thế nào?")
    assert "lo_so_hieu" in _ma([xau])
    assert "lo_so_hieu" not in _ma([tot])


def test_G8_khong_co_gold_span_thi_KHONG_bao():
    """Câu không có đáp án thì không có gì để trích — đúng thiết kế, không phải lỗi."""
    assert "thieu_gold" not in _ma([_it(group="G8", gold_spans=[], gates={"C1": "n/a"},
                                        reference_contexts=[], distractor_ids=[])])
    assert "thieu_gold" in _ma([_it(group="G3", gold_spans=[], reference_contexts=[])])


def test_bat_C1_khong_pass():
    """C1 rớt là LỖI PIPELINE (§2) — phải nổi lên chứ không lẫn vào đám đông."""
    assert "c1_khong_pass" in _ma([_it(gates={"C1": "hash_mismatch"})])


def test_bat_C4_leak():
    assert "c4_leak" in _ma([_it(do_retrieval=False)])
    assert "c4_leak" not in _ma([_it(do_retrieval=True)])


def test_bat_bang_chung_yeu():
    assert "bang_chung_yeu" in _ma([_it(evidence_score=3)])
    assert "bang_chung_yeu" not in _ma([_it(evidence_score=5)])


def test_chi_bat_thieu_bay_o_nhom_thiet_ke_co_bay():
    """G1/G2/G7 dựng bẫy theo §5.3; G3/G4/G5 thì không — báo ở đó là nhiễu."""
    assert "khong_co_bay" in _ma([_it(group="G1", distractor_ids=[])])
    assert "khong_co_bay" not in _ma([_it(group="G4", distractor_ids=[])])


def test_bat_cho_review():
    assert "cho_review" in _ma([_it(group="G6", status="cho_review")])


def test_moi_ma_canh_bao_deu_co_mo_ta():
    """Thêm luật mà quên mô tả thì giao diện nổ `LUAT[m][0]` là undefined."""
    r = [_it(id="A", group="G6", status="cho_review", do_retrieval=False,
             evidence_score=1, gates={"C1": "fail"}, reference="",
             gold_spans=[], reference_contexts=[], distractor_ids=[]),
         _it(id="B", question_form="situation",
             user_input="Quy định về 15/2018/NĐ-CP thế nào?")]
    assert _ma(r) <= set(LUAT)
    assert all(len(v) == 2 and all(v) for v in LUAT.values())


# ── trang HTML dựng ra ──────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def trang(bo_de):
    return dung_html(bo_de, canh_bao(bo_de), "out/eval_set.jsonl")


def _tach(h: str, ten: str, mo: str):
    m = re.search(rf"const {ten}=({re.escape(mo)}.*?);\n", h, re.S)
    assert m, f"không tách được {ten} khỏi trang"
    return json.loads(m.group(1).replace("<\\/", "</"))


def test_du_lieu_nhung_parse_lai_duoc(trang, bo_de):
    assert len(_tach(trang, "DATA", "[")) == len(bo_de)
    assert set(_tach(trang, "LUAT", "{")) == set(LUAT)


# Bên trong một thẻ `<script>` cổ điển, bộ phân tích HTML chỉ dừng ở `</script` —
# KHÔNG dừng ở `<script>`. Nên bất biến đúng là "chỉ có MỘT chuỗi đóng thẻ", không
# phải "chỉ có một chuỗi `<script>`". Kiểm nhầm vế thứ hai thì test đỏ ở dữ liệu
# hoàn toàn vô hại, và người ta sẽ sửa cho hết đỏ thay vì hiểu vì sao.
_DONG_THE = re.compile(r"</\s*script", re.I)


def test_khong_dong_the_script_som(trang):
    """`</script>` lọt vào giữa dữ liệu là trang TRẮNG, không có thông báo lỗi."""
    assert len(_DONG_THE.findall(trang)) == 1


def test_chuoi_nguy_hiem_trong_du_lieu_van_an_toan():
    """Văn bản QPPL không có HTML, nhưng bộ đề còn nhúng câu trả lời của LLM ở
    `c4_tra_loi_khong_ngu_canh` — và cái đó thì không hứa gì cả."""
    r = [_it(reference="</script><script>alert(1)</script>",
             c4_tra_loi_khong_ngu_canh="</SCRIPT >  </ScRiPt>")]
    h = dung_html(r, canh_bao(r), "thu")
    assert len(_DONG_THE.findall(h)) == 1, "dữ liệu đóng thẻ script sớm"
    lai = _tach(h, "DATA", "[")
    assert len(lai) == 1
    assert lai[0]["reference"] == r[0]["reference"], "nội dung phải nguyên vẹn sau khi né"


def test_moi_id_JS_goi_toi_deu_ton_tai(trang):
    """`$('#dk')` trỏ vào phần tử không có -> null.textContent ném, và trang chết
    ngay ở lần vẽ đầu tiên."""
    can = set(re.findall(r"\$\('#([a-zA-Z-]+)'\)", trang))
    co = set(re.findall(r'id="([a-zA-Z-]+)"', trang))
    assert can and not (can - co), f"JS gọi id không có trong HTML: {sorted(can - co)}"


def test_canh_bao_deu_tro_vao_cau_co_that(trang, bo_de):
    cb = _tach(trang, "CB", "{")
    assert not set(cb) - {r["id"] for r in bo_de}


def test_bo_de_that_khong_vuot_qua_nguong_nhieu(bo_de):
    """Bộ soi chỉ có ích khi cảnh báo là TÍN HIỆU. Quá nửa bộ đề bị gắn cờ thì không
    ai đọc nữa — lúc đó phải siết luật lại, không phải quen với màu đỏ."""
    ty = len(canh_bao(bo_de)) / len(bo_de)
    assert ty <= 0.25, f"{ty:.0%} số câu có cảnh báo — luật đang quá rộng"
