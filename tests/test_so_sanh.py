"""Test cho chính bộ so sánh — bằng ĐỘT BIẾN.

Một bộ so sánh không có test là thứ nguy hiểm: nó báo xanh và không ai biết nó có thật
sự nhìn vào đâu không. Cách kiểm duy nhất đáng tin là **cố tình phá** bộ đề rồi đòi nó
phải kêu; và sửa những chỗ được phép đổi rồi đòi nó phải IM.

Vế thứ hai quan trọng ngang vế thứ nhất: bộ so sánh kêu ầm ĩ vì `id` lệch một đơn vị
thì chỉ vài lần là người ta ngừng đọc nó.
"""
from __future__ import annotations

import copy

import pytest

from tests.so_sanh import khoa, so_sanh


@pytest.fixture
def mau(bo_de):
    """Lát nhỏ, đủ nhiều nhóm để phủ các dạng khoá khác nhau."""
    theo: dict[str, list] = {}
    for r in bo_de:
        theo.setdefault(r["group"], []).append(r)
    return [r for g in sorted(theo) for r in theo[g][:4]]


def test_so_voi_chinh_no_khong_lech(bo_de):
    bc = so_sanh(bo_de, copy.deepcopy(bo_de))
    assert bc["chung"] == len(bo_de)
    assert bc["doi_noi_dung"] == []
    assert bc["chi_ben_cu"] == [] and bc["chi_ben_moi"] == []


# Lỗi của BỘ ĐỀ ĐÃ FREEZE — đã sửa ở bộ sinh, còn lại trong artifact.
#
# `g8_unanswerable.NGOAI_PHAM_VI` chỉ có 5 chủ đề, trong khi quota công thức (d) là
# `n - 3*(n//4)` = 7 khi n=25. Bộ sinh quay vòng danh sách nên đẻ ra 2 câu TRÙNG
# NGUYÊN VĂN: G8-0003 ≡ G8-0020 và G8-0004 ≡ G8-0024. Hệ quả: G8 tính 25 câu nhưng
# chỉ có 23 câu phân biệt, 2 câu bị đếm hai lần khi chấm chiều `behavior`.
#
# Bộ sinh đã sửa (`NGOAI_PHAM_VI` 16 chủ đề + trần cứng "mỗi chủ đề một lần" + lưới
# chặn trùng ở mọi công thức; xem `tests/test_sinh_on_dinh.py`). Nhưng `eval_set.jsonl`
# là artifact đã freeze — con số này chỉ về 0 SAU KHI sinh lại bộ đề, việc đó cần
# Neo4j và kéo theo phải re-baseline cả ba lần chạy eval đã lưu.
TRUNG_DA_BIET = 0


def test_so_cau_trung_su_kien_khong_tang(bo_de):
    """Hai câu chung khoá nội dung = cùng một sự kiện đồ thị bị hỏi hai lần."""
    ks = [khoa(r) for r in bo_de]
    trung = len(ks) - len(set(ks))
    assert trung == TRUNG_DA_BIET, (
        f"{trung} câu trùng sự kiện (đã biết: {TRUNG_DA_BIET}). "
        f"Tăng = bộ sinh mới đẻ thêm câu trùng; giảm = đã sửa, hạ TRUNG_DA_BIET xuống.")


@pytest.mark.skipif(TRUNG_DA_BIET == 0, reason="bộ đề không còn câu trùng — đã sửa ở bộ sinh")
def test_cau_trung_deu_nam_o_G8(bo_de):
    """Ghim phạm vi lỗi. Trùng lan sang nhóm khác là chuyện hoàn toàn khác — các
    nhóm kia dựng trên sự kiện đồ thị, trùng ở đó nghĩa là truy vấn trả về lặp."""
    import collections
    dem = collections.Counter(khoa(r) for r in bo_de)
    assert {k[0] for k, v in dem.items() if v > 1} == {"G8"}


def test_doi_dap_an_thi_bi_bat(mau):
    moi = copy.deepcopy(mau)
    moi[0]["reference"] = "ĐÁP ÁN ĐÃ BỊ ĐỔI"
    bc = so_sanh(mau, moi)
    assert len(bc["doi_noi_dung"]) == 1
    assert "reference" in bc["doi_noi_dung"][0]["khac"]


def test_doi_gold_span_thi_bi_bat(mau):
    """Span trôi mà không ai biết là ca hỏng tệ nhất: đáp án vẫn đúng chữ, nhưng
    `context_recall` chấm trên một đoạn không trả lời được câu hỏi."""
    moi = copy.deepcopy(mau)
    tk = next(r for r in moi if r.get("gold_spans"))
    tk["gold_spans"][0]["start"] += 7
    bc = so_sanh(mau, moi)
    assert any("gold_spans" in d["khac"] for d in bc["doi_noi_dung"])


def test_mat_bay_thi_bi_bat(mau):
    moi = copy.deepcopy(mau)
    tk = next(r for r in moi if r.get("distractor_ids"))
    tk["distractor_ids"] = []
    bc = so_sanh(mau, moi)
    assert any("distractor_ids" in d["khac"] for d in bc["doi_noi_dung"])


def test_doi_cong_C1_thi_bi_bat(mau):
    """C1 rớt là LỖI PIPELINE (§2), không phải chuyện để bỏ qua khi so hồi quy."""
    moi = copy.deepcopy(mau)
    moi[0]["gates"] = dict(moi[0]["gates"], C1="fail_hash")
    bc = so_sanh(mau, moi)
    assert any("gates" in d["khac"] for d in bc["doi_noi_dung"])


def test_doi_id_thi_KHONG_bi_bat(mau):
    """`id` là vị trí trong file. Chèn một câu ở đầu làm lệch mọi id phía sau — diff
    theo id sẽ đỏ toàn bộ và che mất lỗi thật."""
    moi = copy.deepcopy(mau)
    for i, r in enumerate(moi):
        r["id"] = f"{r['group']}-9{i:03d}"
    assert so_sanh(mau, moi)["doi_noi_dung"] == []


def test_paraphrase_khac_thi_KHONG_bi_bat(mau):
    """Câu `situation` do LLM viết lại — chạy lại ra chữ khác là bình thường."""
    moi = copy.deepcopy(mau)
    doi = 0
    for r in moi:
        if r.get("question_form") == "situation":
            r["user_input"] = "Một cách diễn đạt khác hoàn toàn của cùng câu hỏi."
            doi += 1
    assert doi, "lát mẫu không có câu situation nào — test này không kiểm được gì"
    assert so_sanh(mau, moi)["doi_noi_dung"] == []


def test_doi_cau_lookup_thi_VAN_bi_bat(mau):
    """`lookup` sinh thẳng từ template, không qua LLM -> phải tái lập được từng chữ.
    Nới lỏng cả `lookup` là mất luôn khả năng phát hiện template bị sửa."""
    moi = copy.deepcopy(mau)
    tk = next(r for r in moi if r.get("question_form") == "lookup")
    tk["user_input"] = "Câu hỏi đã bị viết lại."
    bc = so_sanh(mau, moi)
    assert any("user_input" in d["khac"] for d in bc["doi_noi_dung"])


def test_c4_chay_lai_khac_thi_KHONG_bi_bat(mau):
    """C4 gọi LLM: điểm lệch giữa hai lần chạy là bản chất, không phải hồi quy."""
    moi = copy.deepcopy(mau)
    for r in moi:
        r["c4_diem"] = 0.42
        r["c4_tra_loi_khong_ngu_canh"] = "một câu trả lời khác"
    assert so_sanh(mau, moi)["doi_noi_dung"] == []


def test_thieu_cau_bao_rieng_khong_lan_vao_loi_noi_dung(mau):
    """Khác TẬP CÂU và khác NỘI DUNG phải nằm ở hai ô khác nhau — gộp lại thì con số
    'N dòng khác nhau' không đọc ra hành động nào."""
    bc = so_sanh(mau, mau[2:])
    assert len(bc["chi_ben_cu"]) == 2
    assert bc["doi_noi_dung"] == []


def test_them_cau_moi_bao_rieng(mau):
    them = copy.deepcopy(mau[0])
    them["id"] = "G1-9999"
    them["gold_node_ids"] = ["Norm:khong-co-that"]
    bc = so_sanh(mau, mau + [them])
    assert len(bc["chi_ben_moi"]) == 1
    assert bc["doi_noi_dung"] == []


def test_phat_hien_cau_trung_su_kien(mau):
    """Hai câu cùng sự kiện đồ thị làm lệch trọng số khi chấm — phải báo."""
    bc = so_sanh(mau + [copy.deepcopy(mau[0])], mau)
    assert bc["trung_khoa_cu"] == 1


def test_g8_van_co_khoa_du_khong_tro_vao_node_nao(bo_de):
    """G8 không có `gold_node_ids` (đúng thiết kế: câu không có đáp án thì không có gì
    để trích dẫn). Khoá phải rơi về `reference_fields`, nếu không cả 25 câu G8 dồn
    chung một khoá và bộ so sánh ghép bừa."""
    g8 = [r for r in bo_de if r["group"] == "G8"]
    assert len({khoa(r) for r in g8}) == len(g8) - TRUNG_DA_BIET
