"""genquesai.legal_rag.ingestion.reference_extractor — phần thuần (không Neo4j).

Khoá lại các ca đã đối chiếu tay khi viết module (rule.md), đặc biệt 3 bẫy:
1. Tiêu đề chỉ NHẮC số hiệu (vd trong "Căn cứ...") mà KHÔNG có động từ sửa/thay/bãi
   bỏ thì KHÔNG được tạo AMENDS/REPLACES — bug đã biết ở bản gốc Chatbot-Law.
2. (2026-08-22, ca thật 58/2015/TTLT-BCT-BKHCN) Câu tuyên bố "thay thế" thường nằm ở
   đoạn "Hiệu lực thi hành" CUỐI văn bản, không phải tiêu đề — §3.1.
3. (2026-08-22, cùng ca) "thay thế [VB] số X" (không kèm "một số điều") = REPLACES
   toàn bộ, khác "sửa đổi/thay thế MỘT SỐ ĐIỀU của X" = AMENDS từng phần — §3.2. Và
   phải xử lý THEO TỪNG CÂU — câu boilerplate ở đoạn cuối ("văn bản viện dẫn mà sửa
   đổi... thì theo văn bản mới") không được gán nhầm cho số hiệu ở câu khác.
"""
from __future__ import annotations

from genquesai.legal_rag.ingestion.reference_extractor import (
    extract_final_clause_relations, extract_guided_by, extract_references,
    extract_title_relations, html_to_text,
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


def test_thay_the_khong_kem_mot_so_dieu_la_replaces_toan_bo() -> None:
    """§3.2: "thay thế [VB] số X" (không "một số điều/khoản") = thay TOÀN BỘ văn bản
    -> REPLACES, khác hẳn "sửa đổi/thay thế một số điều" (AMENDS, §3)."""
    assert extract_title_relations(
        "Thông tư thay thế Thông tư số 12/2016/TT-BTTTT", "99/2024/TT-ABC"
    ) == [("ThayThe", "REPLACES", "12/2016/TT-BTTTT")]


def test_thay_the_mot_so_dieu_van_la_amends() -> None:
    assert extract_title_relations(
        "Thông tư sửa đổi, bổ sung và thay thế một số điều của Thông tư số 12/2016/TT-BTTTT",
        "99/2024/TT-ABC"
    ) == [("SuaDoi", "AMENDS", "12/2016/TT-BTTTT")]


def test_final_clause_bat_duoc_cau_thay_the_o_cuoi_van_ban() -> None:
    """§3.1, ca thật 58/2015/TTLT-BCT-BKHCN: câu tuyên bố thay thế nằm ở đoạn "Điều
    khoản thi hành" CUỐI văn bản (tiêu đề không nhắc gì) -> vẫn phải bắt được, và
    phân loại ĐÚNG REPLACES (khớp referenceType=12 thật trên vbpl.vn, không phải
    AMENDS như phân loại "thay thế" thô ban đầu)."""
    text = (
        "Chương I QUY ĐỊNH CHUNG Điều 1. Phạm vi điều chỉnh... "
        "Chương V ĐIỀU KHOẢN THI HÀNH Điều 21. Hiệu lực thi hành "
        "1. Thông tư này có hiệu lực thi hành kể từ ngày 21 tháng 3 năm 2016 và thay "
        "thế Thông tư liên tịch số 44/2013/TTLT-BCT-BKHCN ngày 31 tháng 12 năm 2013 "
        "của Bộ Công Thương và Bộ Khoa học và Công nghệ quy định quản lý chất lượng "
        "thép sản xuất trong nước và thép nhập khẩu."
    )
    rel = extract_final_clause_relations(text, "58/2015/TTLT-BCT-BKHCN")
    assert rel == [("ThayThe", "REPLACES", "44/2013/TTLT-BCT-BKHCN")]


def test_final_clause_boilerplate_khong_tao_canh_sai() -> None:
    """§3.1: câu boilerplate rất phổ biến "văn bản quy phạm pháp luật được viện dẫn
    ... được sửa đổi, bổ sung hoặc thay thế thì thực hiện theo văn bản mới" — nói về
    CÁC VB ĐƯỢC TRÍCH DẪN Ở NƠI KHÁC (không có số hiệu cụ thể trong CÙNG CÂU) — không
    được gán động từ "sửa đổi" của câu này cho số hiệu ở câu KHÁC trong cùng đoạn
    (bẫy suýt xảy ra thật khi viết §3.1 — quét theo câu để tránh)."""
    text = (
        "Điều 21. Hiệu lực thi hành. Thông tư này có hiệu lực thi hành kể từ ngày "
        "21 tháng 3 năm 2016 và thay thế Thông tư liên tịch số 44/2013/TTLT-BCT-BKHCN. "
        "Trường hợp văn bản quy phạm pháp luật được viện dẫn trong Thông tư liên tịch "
        "này được sửa đổi, bổ sung hoặc thay thế thì thực hiện theo văn bản mới."
    )
    rel = extract_final_clause_relations(text, "58/2015/TTLT-BCT-BKHCN")
    assert rel == [("ThayThe", "REPLACES", "44/2013/TTLT-BCT-BKHCN")]


def test_bai_bo_noi_dung_tai_vb_khac_la_amends_khong_phai_replaces() -> None:
    """§3.2 mở rộng (ca thật 06/2016/TT-BKHCN, 2026-08-22): "bãi bỏ NỘI DUNG quy định
    liên quan đến... quy định TẠI Quyết định số X" = chỉ bãi bỏ 1 PHẦN NỘI DUNG nằm
    TRONG VB khác (không phải toàn bộ VB đó) -> AMENDS, khớp referenceType=1 + LLM.
    Quy tắc "bãi bỏ = luôn REPLACES" ban đầu (mục 3) là SAI cho ca này."""
    text = (
        "Điều X. Hiệu lực thi hành. Thông tư này có hiệu lực thi hành kể từ ngày 20 "
        "tháng 6 năm 2016 và bãi bỏ nội dung quy định liên quan đến cấp giấy phép "
        "dịch vụ an toàn bức xạ quy định tại Quyết định số 32/2007/QĐ-BKHCN ngày 31 "
        "tháng 12 năm 2007 của Bộ trưởng Bộ Khoa học và Công nghệ."
    )
    rel = extract_final_clause_relations(text, "06/2016/TT-BKHCN")
    assert rel == [("SuaDoi", "AMENDS", "32/2007/QĐ-BKHCN")]


def test_bai_bo_toan_bo_van_la_replaces() -> None:
    """Đối chứng: "bãi bỏ [toàn bộ] Quyết định số X" (không "nội dung"/"một số điều")
    vẫn phải là REPLACES như quy tắc gốc — chỉ câu có cụm từng-phần mới đổi AMENDS."""
    rel = extract_title_relations(
        "Quyết định bãi bỏ Chỉ thị số 05/2010/CT-BGDDT", "10/2024/QD-BGDDT")
    assert rel == [("ThayThe", "REPLACES", "05/2010/CT-BGDDT")]


def test_html_to_text_giu_lien_mach_so_hieu_bi_tag_chen_giua() -> None:
    """Bug thật 2026-08-22 (VB 113783/most): HTML gốc tô đậm/nghiêng riêng TỪNG KÝ TỰ
    của số hiệu (vd do OCR/export PDF), <em> chèn giữa "QH" và "13". Dùng
    `re.sub(r"<[^>]+>", " ", html)` (bản cũ) làm số hiệu vỡ thành "QH 1 3" -> SOHIEU_RE
    chỉ bắt được "QH", mất "13". `html_to_text` (HTMLParser, không separator) phải
    giữ liền mạch."""
    html = "<p>Căn cứ Luật số 29/2013/QH<em>1</em><em>3</em> ngày 18 tháng 6 năm 2013;</p>"
    text = html_to_text(html)
    assert "29/2013/QH13" in text
