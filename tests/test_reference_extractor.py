"""genquesai.legal_rag.ingestion.reference_extractor — phần thuần (không Neo4j).

Khoá lại 4 ca đã đối chiếu tay khi viết module (rule.md), đặc biệt ca "bẫy": tiêu đề
chỉ NHẮC số hiệu (vd trong "Căn cứ...") mà KHÔNG có động từ sửa/thay/bãi bỏ thì KHÔNG
được tạo AMENDS/REPLACES — đây chính là bug đã biết ở bản gốc Chatbot-Law (regex thô
nhầm "Căn cứ Nghị định X..." thành AMENDS).
"""
from __future__ import annotations

from genquesai.legal_rag.ingestion.reference_extractor import (
    extract_guided_by, extract_references, extract_title_relations,
)


def test_sua_doi_bo_sung_ro_rang() -> None:
    rel = extract_title_relations(
        "Thông tư sửa đổi, bổ sung một số điều của Thông tư số 12/2016/TT-BTTTT",
        "99/2024/TT-ABC")
    assert rel == [("SuaDoi", "AMENDS", "12/2016/TT-BTTTT")]


def test_bai_bo_don_thuan_la_replaces() -> None:
    rel = extract_title_relations(
        "Quyết định bãi bỏ Chỉ thị số 05/2010/CT-BGDDT", "10/2024/QD-BGDDT")
    assert rel == [("ThayThe", "REPLACES", "05/2010/CT-BGDDT")]


def test_nhac_so_hieu_khong_dong_tu_khong_tao_canh() -> None:
    """Bẫy đã biết (rule.md §3): tiêu đề "quy định chi tiết thi hành Nghị định X" —
    có số hiệu nhưng KHÔNG có động từ sửa/thay/bãi bỏ -> không phải AMENDS/REPLACES."""
    rel = extract_title_relations(
        "Thông tư quy định chi tiết thi hành Nghị định số 15/2020/ND-CP",
        "20/2024/TT-BTC")
    assert rel == []


def test_guided_by_tu_doan_can_cu() -> None:
    text = ("Căn cứ Luật Ban hành văn bản quy phạm pháp luật; "
            "Căn cứ Nghị định số 15/2020/NĐ-CP; "
            "Điều 1. Phạm vi điều chỉnh...")
    guided = extract_guided_by(text, "20/2024/TT-BTC")
    assert guided == [("CanCu", "GUIDED_BY", "15/2020/NĐ-CP")]


def test_extract_references_hop_nhat_khong_trung_muc_tieu() -> None:
    """Số hiệu đã lấy làm REPLACES/AMENDS (từ tiêu đề) không bị lặp lại thành GUIDED_BY
    dù cũng xuất hiện trong đoạn căn cứ."""
    title = "Thông tư sửa đổi, bổ sung Thông tư số 12/2016/TT-BTTTT"
    text = "Căn cứ Thông tư số 12/2016/TT-BTTTT; Điều 1. Phạm vi điều chỉnh..."
    refs = extract_references(title, text, "99/2024/TT-ABC")
    assert refs == [("SuaDoi", "AMENDS", "12/2016/TT-BTTTT")]


def test_tu_tro_bi_loai() -> None:
    assert extract_title_relations(
        "Thông tư 12/2016/TT-BTTTT sửa đổi Thông tư 12/2016/TT-BTTTT",
        "12/2016/TT-BTTTT") == []
