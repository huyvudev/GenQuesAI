"""A2 — đối chiếu nội dung. Mỗi test ghim một ca mà so-theo-id không xử được.

Đây là tầng quyết định công cụ có đo được hệ KHÔNG dùng chung index với legal-rag hay
không. Sai theo hướng nào cũng hỏng theo cách riêng:

    quá chặt -> hệ chunk khác cách bị chấm recall 0 dù lấy về đúng nội dung
    quá lỏng -> đoạn "cùng chủ đề nhưng khác văn bản" được tính là gold -> recall ảo
"""
from __future__ import annotations

import pytest

from framework.doi_chieu import (NGUONG_KHOP, KetQuaDoiChieu, chuan, do_phu,
                                 doi_chieu, doi_chieu_gold)

# Một đoạn luật thật (G1-0000 của bộ đề cũ) — dùng nguyên văn để test giống production.
SPAN = ("Thông tư này thay thế các văn bản sau:\n"
        "Thông tư số 38/2012/TT-BNNPTNT ngày 02/8/2010 của Bộ Nông nghiệp và Phát "
        "triển nông thôn ban hành Danh mục bệnh động vật thuỷ sản phải công bố dịch;")


# ── các ca hệ CHUNK KHÁC CÁCH vẫn phải được điểm ────────────────────────────
def test_span_nam_gon_trong_doan_dai_hon():
    """Hệ khác chunk to hơn: span là một phần của đoạn họ trả. Phải khớp trọn."""
    doan = "PHẦN MỞ ĐẦU CỦA CHUNK. " + SPAN + " VÀ PHẦN ĐUÔI KÉO DÀI THÊM."
    assert do_phu(SPAN, doan) == 1.0


def test_khac_khoang_trang_va_hoa_thuong_van_khop():
    """Chuẩn hoá là bắt buộc: xuống dòng/tab/hoa thường là chuyện của tầng hiển thị,
    không phải của nội dung."""
    doan = " ".join(SPAN.upper().split())
    assert do_phu(SPAN, doan) == 1.0


def test_span_vat_ngang_hai_doan_van_duoc_tinh_du():
    """Hệ chunk NHỎ hơn: span bị cắt đôi vào hai đoạn kề nhau. Đo trên UNION nên
    recall vẫn ~1.0 — nội dung ĐÃ được lấy về, chỉ là nằm ở hai chỗ."""
    giua = len(SPAN) // 2
    kq = doi_chieu(SPAN, [SPAN[:giua + 40], SPAN[giua - 40:]])
    assert kq.diem >= 0.95
    assert kq.khop


def test_hang_la_doan_don_le_tot_nhat():
    """`hang` phục vụ triage nên phải là đoạn ĐƠN LẺ chứa đáp án, không phải union."""
    kq = doi_chieu(SPAN, ["đoạn nhiễu thứ nhất không liên quan gì", SPAN])
    assert kq.khop and kq.hang == 1


# ── các ca PHẢI trượt ───────────────────────────────────────────────────────
def test_cung_chu_de_khac_van_ban_khong_duoc_diem():
    """Chỗ dễ ăn gian nhất: đoạn nói đúng chủ đề nhưng của văn bản KHÁC. Cửa sổ 64
    ký tự nguyên văn gần như không trùng -> điểm ~0. Đây là lý do không đo bằng
    token đơn lẻ hay embedding."""
    khac = ("Thông tư này thay thế các văn bản sau:\n"
            "Thông tư số 79/2011/TT-BNNPTNT ngày 14/11/2011 của Bộ Nông nghiệp và "
            "Phát triển nông thôn quy định về chứng nhận chất lượng giống cây trồng;")
    assert do_phu(SPAN, khac) < NGUONG_KHOP


def test_khong_co_context_thi_khong_khop():
    kq = doi_chieu(SPAN, [])
    assert kq == KetQuaDoiChieu(0.0, None, False)


def test_span_rong_khong_khop_gi():
    assert doi_chieu("", ["văn bản bất kỳ"]).khop is False


def test_span_ngan_hon_cua_so_van_do_duoc():
    """Span ngắn nhất trong bộ đề là 139 ký tự, nhưng phòng ca cắt cụt: span ngắn hơn
    64 ký tự thành đúng một cửa sổ, vẫn phải hoạt động."""
    s = "Điều 5 có hiệu lực từ 2024."
    assert do_phu(s, f"abc {s} xyz") == 1.0
    assert do_phu(s, "không liên quan") == 0.0


def test_duoi_span_khong_bi_bo_quen():
    """Cửa sổ trượt bước CO/2 có thể hụt đuôi — cửa sổ chót phải neo vào cuối span,
    nếu không phần đuôi sai lệch không bao giờ bị phát hiện."""
    # giống hệt nhau trừ 70 ký tự cuối
    doan = SPAN[:-70] + " NỘI DUNG ĐÃ BỊ TRÁO Ở PHẦN ĐUÔI, KHÁC HOÀN TOÀN BẢN GỐC."
    assert do_phu(SPAN, doan) < 1.0


# ── doi_chieu_gold: đường nhanh id + đường nội dung ─────────────────────────
GOLD = [{"chunk_id": "id-thu"}]


def test_duong_nhanh_id_khi_hai_ben_chung_khong_gian():
    """Hộp trắng legal-rag: id trúng là 1.0 tại đúng hạng, khỏi đo chuỗi."""
    ra = doi_chieu_gold(GOLD, [SPAN], ["khac", "id-thu"], ["nhiễu", "nhiễu"], k=12)
    assert ra[0] == KetQuaDoiChieu(1.0, 1, True)


def test_id_truot_thi_roi_xuong_noi_dung():
    """Hệ khác: id chẳng khớp gì nhưng NỘI DUNG có — phải được điểm. Đây chính là
    điều A2 tồn tại để làm."""
    ra = doi_chieu_gold(GOLD, [SPAN], ["id-cua-he-khac"], ["mở đầu. " + SPAN], k=12)
    assert ra[0].khop and ra[0].hang == 0


def test_hop_den_khong_co_id_nao():
    ra = doi_chieu_gold(GOLD, [SPAN], [], [SPAN], k=12)
    assert ra[0].khop


def test_id_ngoai_top_k_khong_duoc_tinh():
    """Đường nhanh cũng phải tôn trọng cửa sổ k — id nằm ở hạng 15 mà k=12 thì là
    `retriever_sot`, không phải khớp."""
    ids = [f"x{i}" for i in range(14)] + ["id-thu"]
    ra = doi_chieu_gold(GOLD, [SPAN], ids, ["nhiễu"] * 15, k=12)
    assert not ra[0].khop


def test_moi_span_mot_ket_qua():
    gold = [{"chunk_id": "a"}, {"chunk_id": "b"}]
    ra = doi_chieu_gold(gold, [SPAN, "đoạn hai hoàn toàn khác"], ["a"], [SPAN], k=12)
    assert len(ra) == 2
    assert ra[0].khop and not ra[1].khop
