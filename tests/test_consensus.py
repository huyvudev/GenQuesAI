"""genquesai.legal_rag.ingestion.consensus — phần thuần (không Neo4j).

Khoá lại 4 tình huống đồng thuận đa nguồn v3 (rule.md §0.1/§2): nhánh A (có
metadata) khớp/lệch, nhánh B (không metadata, có regex) khớp, nhánh C (không gì cả,
chỉ LLM — không có "khớp/lệch" mà là None).
"""
from __future__ import annotations

from genquesai.legal_rag.ingestion.consensus import dong_thuan, dong_thuan_per_edge, extract_metadata_relations


def test_extract_metadata_relations_dung_target_docnum() -> None:
    """referenceType 3 -> CanCu/GUIDED_BY; 10 -> SuaDoi/AMENDS (rule.md §0.1, REL_MAP)."""
    data = {"references": [
        {"referenceType": 3, "targetDocument": {"docNum": "25/2011/NĐ-CP"}},
        {"referenceType": 10, "targetDocument": {"docNum": "12/2016/TT-BTTTT"}},
        {"referenceType": 999, "targetDocument": {"docNum": "khong-map-duoc"}},
    ]}
    rel = extract_metadata_relations(data)
    assert rel == [
        ("CanCu", "GUIDED_BY", "25/2011/NĐ-CP"),
        ("SuaDoi", "AMENDS", "12/2016/TT-BTTTT"),
    ]


def test_nhanh_a_ca_3_nguon_khop_thi_duyet() -> None:
    meta = [("SuaDoi", "AMENDS", "12/2016/TT-BTTTT")]
    kq = dong_thuan(meta, meta, meta)
    assert kq["nhanh"] == "A"
    assert kq["khop"] is True


def test_nhanh_a_llm_lech_thi_khong_duyet() -> None:
    meta = [("SuaDoi", "AMENDS", "12/2016/TT-BTTTT")]
    kq = dong_thuan(meta, meta, [])   # LLM không thấy gì -> lệch
    assert kq["nhanh"] == "A"
    assert kq["khop"] is False


def test_nhanh_b_khong_metadata_co_regex_khop_llm() -> None:
    regex = [("ThayThe", "REPLACES", "05/2010/CT-BGDDT")]
    kq = dong_thuan(None, regex, regex)
    assert kq["nhanh"] == "B"
    assert kq["khop"] is True


def test_nhanh_c_khong_gi_ca_khong_co_khai_niem_khop() -> None:
    """Biện pháp cuối — chỉ LLM, không có gì đối chiếu -> khop=None (khác False)."""
    kq = dong_thuan(None, None, [("ThayThe", "REPLACES", "05/2010/CT-BGDDT")])
    assert kq["nhanh"] == "C"
    assert kq["khop"] is None


# ── dong_thuan_per_edge (rebuild 2026-08-24) ──────────────────────────────────────

def test_per_edge_ca_3_nguon_khop_thi_duyet_dung_cach() -> None:
    meta = [("SuaDoi", "AMENDS", "12/2016/TT-BTTTT")]
    out = dong_thuan_per_edge(meta, meta, meta)
    assert out == [{"loai": "SuaDoi", "edge": "AMENDS", "target": "12/2016/TT-BTTTT",
                    "da_duyet": True, "mismatch": False, "only_llm": False,
                    "nguon": ["llm", "metadata", "regex"]}]


def test_per_edge_khong_mat_canh_khi_nguon_mac_dinh_thieu() -> None:
    """Bug đã sửa: nhánh A (metadata khả dụng), metadata CHỈ thấy X, nhưng LLM thấy
    CẢ X lẫn Y — Y phải vẫn được trả về (gắn mismatch), KHÔNG bị lặng lẽ bỏ qua chỉ
    vì metadata (nguồn "mặc định" theo thiết kế cũ) không thấy nó."""
    meta = [("CanCu", "GUIDED_BY", "X/2020/NĐ-CP")]
    llm = [("CanCu", "GUIDED_BY", "X/2020/NĐ-CP"), ("CanCu", "GUIDED_BY", "Y/2021/QH14")]
    out = dong_thuan_per_edge(meta, None, llm)
    by_target = {e["target"]: e for e in out}
    assert set(by_target) == {"X/2020/NĐ-CP", "Y/2021/QH14"}
    assert by_target["X/2020/NĐ-CP"]["da_duyet"] is True   # có ở đủ nguồn khả dụng (metadata+llm)
    assert by_target["Y/2021/QH14"]["da_duyet"] is False   # chỉ llm thấy -> mismatch, không bị mất
    assert by_target["Y/2021/QH14"]["mismatch"] is True
    assert by_target["Y/2021/QH14"]["nguon"] == ["llm"]


def test_per_edge_nhanh_b_regex_llm_khop_mot_phan() -> None:
    regex = [("ThayThe", "REPLACES", "A/2019/NĐ-CP")]
    llm = [("ThayThe", "REPLACES", "A/2019/NĐ-CP"), ("SuaDoi", "AMENDS", "B/2018/TT-BTC")]
    out = dong_thuan_per_edge(None, regex, llm)
    by_target = {e["target"]: e for e in out}
    assert by_target["A/2019/NĐ-CP"]["da_duyet"] is True
    assert by_target["B/2018/TT-BTC"]["mismatch"] is True
    assert by_target["B/2018/TT-BTC"]["only_llm"] is False   # regex CÓ khả dụng, chỉ là không thấy cạnh này


def test_per_edge_nhanh_c_chi_llm_luon_only_llm() -> None:
    llm = [("CanCu", "GUIDED_BY", "Z/2015/QH13")]
    out = dong_thuan_per_edge(None, None, llm)
    assert out == [{"loai": "CanCu", "edge": "GUIDED_BY", "target": "Z/2015/QH13",
                    "da_duyet": False, "mismatch": False, "only_llm": True, "nguon": ["llm"]}]


def test_per_edge_khong_gi_ca_tra_list_rong() -> None:
    assert dong_thuan_per_edge(None, None, []) == []
    assert dong_thuan_per_edge([], [], []) == []
