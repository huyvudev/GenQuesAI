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
    extract_references_llm, extract_title_relations, html_to_text, _resolve_ten_luat,
)


def test_sua_doi_bo_sung_ro_rang() -> None:
    rel = extract_title_relations(
        "Thông tư sửa đổi, bổ sung một số điều của Thông tư số 12/2016/TT-BTTTT",
        "99/2024/TT-ABC")
    assert rel == [("SuaDoi", "AMENDS", "12/2016/TT-BTTTT")]


def test_bai_bo_don_thuan_la_replaces() -> None:
    rel = extract_title_relations(
        "Quyết định bãi bỏ Chỉ thị số 05/2010/CT-BGDDT", "10/2024/QD-BGDDT")
    assert rel == [("BaiBoToanBo", "REPLACES", "05/2010/CT-BGDDT")]


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


def test_final_clause_khong_lan_sang_dieu_nhiem_vu_sau_do() -> None:
    """Bug thật 2026-08-23 (user phát hiện, đo trên 5000 VB mẫu: 410 VB/8,2% dính,
    có ca dài tới 66.965 ký tự): trước đây đọc từ "hiệu lực thi hành" ĐẾN HẾT TOÀN
    VĂN — nếu Điều đó không phải Điều cuối, Điều TIẾP THEO ("Trách nhiệm thi hành"/
    "Tổ chức thực hiện") liệt kê NHIỆM VỤ giao bộ ngành (vd "trình Nghị định thay
    thế Nghị định Y") bị lẫn vào — đây là VIỆC GIAO CHO TƯƠNG LAI, không phải chính
    VB này thay thế Y. Phải dừng ở Điều tiếp theo, không đọc lan."""
    text = (
        "Điều 5. Hiệu lực thi hành. Nghị định này có hiệu lực thi hành từ ngày ký. "
        "Điều 6. Trách nhiệm thi hành. Bộ trưởng Bộ Tài chính có trách nhiệm nghiên "
        "cứu, trình Chính phủ ban hành Nghị định thay thế Nghị định số 20/2020/NĐ-CP "
        "trong năm 2027."
    )
    rel = extract_final_clause_relations(text, "10/2026/NĐ-CP")
    assert rel == []


def test_final_clause_khong_lan_sang_phu_luc() -> None:
    """Cùng bug — VB kết thúc bằng Phụ lục dài (bảng biểu, mẫu...) cũng phải bị chặn,
    không chỉ Điều tiếp theo."""
    text = (
        "Điều 5. Hiệu lực thi hành. Nghị định này có hiệu lực thi hành từ ngày ký. "
        "PHỤ LỤC I DANH MỤC BAN HÀNH KÈM THEO Mẫu số 01: ... thay thế Mẫu số cũ tại "
        "Thông tư số 20/2020/TT-BTC ..."
    )
    rel = extract_final_clause_relations(text, "10/2026/NĐ-CP")
    assert rel == []


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
    assert rel == [("BaiBoTungPhan", "AMENDS", "32/2007/QĐ-BKHCN")]


def test_thay_the_cac_quy_dinh_ve_la_amends_khong_phai_replaces() -> None:
    """§3.2 mở rộng thêm (ca thật 113460, phát hiện 2026-08-23 qua 2 agent con đọc
    tay đối chiếu độc lập): "thay thế CÁC QUY ĐỊNH VỀ [chủ đề] quy định tại X" cũng
    là sửa TỪNG PHẦN như "quy định liên quan" — mẫu cũ CHƯA khớp cụm "các quy định
    về", khiến 30/2008/QĐ-BGDĐT bị phân loại nhầm REPLACES toàn bộ."""
    text = (
        "hiệu lực thi hành kể từ ngày 10 tháng 8 năm 2016. 2. Thông tư liên tịch này "
        "bãi bỏ quy định liên quan đến tổ chức kiểm tra, cấp chứng chỉ tin học tại "
        "Khoản 5, Điều 3 Thông tư số 03/2011/TT-BGDĐT ngày 28/01/2011; thay thế các "
        "quy định về tổ chức kiểm tra, cấp chứng chỉ tin học theo chương trình giáo "
        "dục thường xuyên quy định tại Quyết định số 30/2008/QĐ-BGDĐT ngày 06/6/2008."
    )
    rel = extract_final_clause_relations(text, "37/2016/TTLT-BTTTT-BGDĐT")
    assert set(rel) == {
        ("BaiBoTungPhan", "AMENDS", "03/2011/TT-BGDĐT"),
        ("SuaDoi", "AMENDS", "30/2008/QĐ-BGDĐT"),
    }


def test_bai_bo_toan_bo_van_la_replaces() -> None:
    """Đối chứng: "bãi bỏ [toàn bộ] Quyết định số X" (không "nội dung"/"một số điều")
    vẫn phải là REPLACES như quy tắc gốc — chỉ câu có cụm từng-phần mới đổi AMENDS."""
    rel = extract_title_relations(
        "Quyết định bãi bỏ Chỉ thị số 05/2010/CT-BGDDT", "10/2024/QD-BGDDT")
    assert rel == [("BaiBoToanBo", "REPLACES", "05/2010/CT-BGDDT")]


def test_dong_tu_som_nhat_quyet_dinh_ca_cau_khong_phai_sua_luon_thang() -> None:
    """§3.4 (ca thật 19/2016/TT-BKHCN, 2026-08-22): "Bãi bỏ Thông tư A... và Thông tư
    B... sửa đổi, bổ sung Thông tư A..." — "sửa đổi" chỉ MÔ TẢ quan hệ B→A trong quá
    khứ, không phải hành động của VB hiện tại. Động từ SỚM NHẤT ("Bãi bỏ") phải quyết
    định cả câu -> REPLACES cho CẢ HAI, không phải AMENDS như luật "SUA luôn thắng" cũ."""
    text = (
        "Điều 2. Hiệu lực thi hành. Thông tư này có hiệu lực thi hành kể từ ngày ban "
        "hành. Bãi bỏ Thông tư số 19/2013/TT-BKHCN ngày 15 tháng 8 năm 2013 và Thông "
        "tư số 17/2014/TT-BKHCN ngày 16 tháng 6 năm 2014 sửa đổi, bổ sung Thông tư số "
        "19/2013/TT-BKHCN ngày 15 tháng 8 năm 2013."
    )
    rel = extract_final_clause_relations(text, "19/2016/TT-BKHCN")
    assert set(rel) == {
        ("BaiBoToanBo", "REPLACES", "19/2013/TT-BKHCN"),
        ("BaiBoToanBo", "REPLACES", "17/2014/TT-BKHCN"),
    }


def test_fallback_khong_lay_phan_truoc_dieu_1() -> None:
    """§3.1 mở rộng (ca thật 10/2007/QĐ-BKHCN, 2026-08-22): VB KHÔNG có cụm "hiệu lực
    thi hành"/"điều khoản thi hành" -> fallback lấy N ký tự cuối. Nếu VB ngắn hơn N,
    fallback KHÔNG được lẫn vào đoạn "Căn cứ..." trước "Điều 1" (bẫy gốc tái hiện qua
    đường vòng)."""
    text = (
        "Căn cứ Nghị định số 81/2002/NĐ-CP; Căn cứ Nghị định số 54/2003/NĐ-CP sửa đổi "
        "Nghị định số 81/2002/NĐ-CP; "
        "Điều 1. Ban hành kèm theo Quyết định này Quy định. "
        "Điều 2. Quyết định này có hiệu lực sau 15 ngày và thay thế Quyết định số "
        "16/2003/QĐ-BKHCN ngày 18 tháng 7 năm 2003."
    )
    rel = extract_final_clause_relations(text, "10/2007/QĐ-BKHCN")
    # KHÔNG được có 54/2003/NĐ-CP hay 81/2002/NĐ-CP (đoạn Căn cứ, trước Điều 1)
    assert rel == [("ThayThe", "REPLACES", "16/2003/QĐ-BKHCN")]


def test_menh_de_mo_ta_khong_bi_gan_nham_lam_dich() -> None:
    """§3.5 (ca thật 16/2016/TT-BKHCN, 2026-08-22): "Sửa đổi một số điều của Thông
    tư X ngày... hướng dẫn thi hành Nghị định Y..., được sửa đổi, bổ sung theo Thông
    tư Z1, Z2 và Z3" — CHỈ X là đích thật (AMENDS). Y/Z1/Z2/Z3 chỉ được NHẮC trong
    mệnh đề mô tả X (nó hướng dẫn NĐ nào, nó từng bị sửa bởi TT nào), không phải đối
    tượng VB hiện tại tác động."""
    title = (
        "Thông tư số 16/2016/TT-BKHCN Sửa đổi, bổ sung một số điều của Thông tư số "
        "01/2007/TT-BKHCN ngày 14 tháng 02 năm 2007 hướng dẫn thi hành Nghị định số "
        "103/2006/NĐ-CP ngày 22 tháng 9 năm 2006 của Chính phủ quy định chi tiết và "
        "hướng dẫn thi hành một số điều của Luật Sở hữu trí tuệ về sở hữu công "
        "nghiệp, được sửa đổi, bổ sung theo Thông tư số 13/2010/TT-BKHCN ngày 30 "
        "tháng 7 năm 2010, Thông tư số 18/2011/TT-BKHCN ngày 22 tháng 7 năm 2011 và "
        "Thông tư số 05/2013/TT-BKHCN ngày 20 tháng 02 năm 2013"
    )
    assert extract_title_relations(title, "16/2016/TT-BKHCN") == [
        ("SuaDoi", "AMENDS", "01/2007/TT-BKHCN")
    ]


def test_dong_ngoac_kep_thoat_menh_de_mo_ta_ve_lai_dich() -> None:
    """§3.5 (ca thật 10/2007/QĐ-BKHCN, 2026-08-22): "...thay thế Quyết định A..., B
    ...về việc "sửa đổi... của Quy định... ban hành kèm theo A..."" và Quyết định
    C..." — A và C là đích (REPLACES), B mô tả trong ngoặc kép cũng là đích riêng
    (câu trước ngoặc), số hiệu A LẶP LẠI bên trong ngoặc không tính thêm, C sau khi
    ngoặc ĐÃ ĐÓNG (dù trong cùng gap) vẫn là đích thật."""
    text = (
        "Điều 2. Quyết định này có hiệu lực sau 15 ngày và thay thế Quyết định số "
        '16/2003/QĐ-BKHCN ngày 18/7/2003 của Bộ trưởng về việc ban hành "Quy định '
        'về việc tuyển chọn tổ chức và cá nhân", Quyết định số 20/2005/QĐ-BKHCN '
        'ngày 23/12/2005 của Bộ trưởng về việc "sửa đổi, bổ sung các Điều 6, 7 của '
        "Quy định ban hành kèm theo Quyết định số 16/2003/QĐ-BKHCN ngày 18/7/2003 "
        'của Bộ trưởng" và Quyết định số 06/2006/QĐ-BKHCN ngày 26/01/2006 của Bộ '
        "trưởng."
    )
    rel = extract_final_clause_relations(text, "10/2007/QĐ-BKHCN")
    assert set(rel) == {
        ("ThayThe", "REPLACES", "16/2003/QĐ-BKHCN"),
        ("ThayThe", "REPLACES", "20/2005/QĐ-BKHCN"),
        ("ThayThe", "REPLACES", "06/2006/QĐ-BKHCN"),
    }


def test_html_to_text_giu_lien_mach_so_hieu_bi_tag_chen_giua() -> None:
    """Bug thật 2026-08-22 (VB 113783/most): HTML gốc tô đậm/nghiêng riêng TỪNG KÝ TỰ
    của số hiệu (vd do OCR/export PDF), <em> chèn giữa "QH" và "13". Dùng
    `re.sub(r"<[^>]+>", " ", html)` (bản cũ) làm số hiệu vỡ thành "QH 1 3" -> SOHIEU_RE
    chỉ bắt được "QH", mất "13". `html_to_text` (HTMLParser, không separator) phải
    giữ liền mạch."""
    html = "<p>Căn cứ Luật số 29/2013/QH<em>1</em><em>3</em> ngày 18 tháng 6 năm 2013;</p>"
    text = html_to_text(html)
    assert "29/2013/QH13" in text


class _FakeNeo:
    """Giả `Neo4jClient.run()` — trả sẵn `rows` bất kể câu Cypher, đủ để test
    `_resolve_ten_luat` không cần Neo4j thật (rule.md §5.4)."""

    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def run(self, cypher: str, **params):
        return self._rows


class _NgayBanHanh:
    """Giả `neo4j.time.Date` — chỉ cần 3 thuộc tính year/month/day mà
    `_resolve_ten_luat` đọc, không cần phụ thuộc `neo4j` thật trong test."""

    def __init__(self, y: int, m: int, d: int) -> None:
        self.year, self.month, self.day = y, m, d


def test_resolve_ten_luat_khop_dung_1_thi_lay(  # ca thật 2026-08-23: user phát hiện
) -> None:
    """Đúng 1 kết quả khớp tiêu đề -> lấy thẳng, không cần ngày."""
    neo = _FakeNeo([{"so_hieu": "63/2025/QH15", "ngay_ban_hanh": _NgayBanHanh(2025, 2, 18)}])
    assert _resolve_ten_luat(neo, "Luật Tổ chức Chính phủ") == "63/2025/QH15"


def test_resolve_ten_luat_mo_ho_khong_ngay_thi_bo() -> None:
    """Nhiều kết quả khớp tên, không có ngày để phân biệt -> bỏ, KHÔNG đoán đại."""
    neo = _FakeNeo([
        {"so_hieu": "76/2015/QH13", "ngay_ban_hanh": _NgayBanHanh(2015, 6, 19)},
        {"so_hieu": "63/2025/QH15", "ngay_ban_hanh": _NgayBanHanh(2025, 2, 18)},
    ])
    assert _resolve_ten_luat(neo, "Luật Tổ chức Chính phủ") is None


def test_resolve_ten_luat_mo_ho_co_ngay_khop_dung_1_thi_lay() -> None:
    """Nhiều kết quả khớp tên, nhưng chỉ 1 khớp đúng ngày ban hành -> lấy được."""
    neo = _FakeNeo([
        {"so_hieu": "76/2015/QH13", "ngay_ban_hanh": _NgayBanHanh(2015, 6, 19)},
        {"so_hieu": "63/2025/QH15", "ngay_ban_hanh": _NgayBanHanh(2025, 2, 18)},
    ])
    assert _resolve_ten_luat(neo, "Luật Tổ chức Chính phủ", "18/02/2025") == "63/2025/QH15"


def test_resolve_ten_luat_khong_khop_thi_bo() -> None:
    neo = _FakeNeo([])
    assert _resolve_ten_luat(neo, "Luật Không Tồn Tại") is None


def test_resolve_ten_luat_hien_phap_loai_tru_khong_tra() -> None:
    """Hiến pháp không phải Norm tham gia REPLACES/AMENDS/GUIDED_BY -> loại trừ hẳn,
    không gọi Neo4j (rule.md §5.4 nhóm 2)."""
    class _NeoNoQuery:
        def run(self, *a, **kw):
            raise AssertionError("không được gọi Neo4j cho Hiến pháp")
    assert _resolve_ten_luat(_NeoNoQuery(), "Hiến pháp nước CHXHCN Việt Nam") is None


def test_resolve_ten_luat_neo_none_thi_bo_khong_loi() -> None:
    """Không truyền `neo` (hành vi cũ, backward-compat) -> bỏ êm, không raise."""
    assert _resolve_ten_luat(None, "Luật Tổ chức Chính phủ") is None


class _FakeLLM:
    def __init__(self, data: dict) -> None:
        self._data = data

    def chat_json(self, system, user, temperature=0.0, max_tokens=800):
        return self._data


def test_extract_references_llm_ten_luat_duoc_resolve_qua_neo() -> None:
    """CanCu không có target (LLM không thấy số hiệu) nhưng có ten_luat+ngay -> tra
    ngược ra so_hieu qua Neo4j, vẫn tạo được cạnh GUIDED_BY (rule.md §5.4)."""
    llm = _FakeLLM({"refs": [
        {"target": "", "ten_luat": "Luật Tổ chức Chính phủ", "ngay": "18/02/2025",
         "loai": "CanCu", "confidence": 0.6},
    ]})
    neo = _FakeNeo([{"so_hieu": "63/2025/QH15", "ngay_ban_hanh": _NgayBanHanh(2025, 2, 18)}])
    out = extract_references_llm(llm, "VB test", "Căn cứ Luật Tổ chức Chính phủ...", "01/NQ-CP", neo=neo)
    assert out == [("CanCu", "GUIDED_BY", "63/2025/QH15")]


def test_extract_references_llm_ten_luat_khong_resolve_duoc_thi_bo_qua() -> None:
    """Không truyền `neo` -> ca ten_luat-only bị bỏ (không tạo cạnh sai/thiếu)."""
    llm = _FakeLLM({"refs": [
        {"target": "", "ten_luat": "Luật Tổ chức Chính phủ", "ngay": "18/02/2025",
         "loai": "CanCu", "confidence": 0.6},
    ]})
    out = extract_references_llm(llm, "VB test", "Căn cứ Luật Tổ chức Chính phủ...", "01/NQ-CP")
    assert out == []
