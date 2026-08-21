"""genquesai.legal_rag.ingestion.consensus — phần thuần (không Neo4j).

Khoá lại 4 tình huống đồng thuận đa nguồn v3 (rule.md §0.1/§2): nhánh A (có
metadata) khớp/lệch, nhánh B (không metadata, có regex) khớp, nhánh C (không gì cả,
chỉ LLM — không có "khớp/lệch" mà là None).
"""
from __future__ import annotations

from genquesai.legal_rag.ingestion.consensus import dong_thuan, extract_metadata_relations


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
