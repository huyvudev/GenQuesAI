"""5 prompt sinh câu hỏi — tiếng Việt, viết mới hoàn toàn cho domain luật (không tái
dùng P_SINGLE/P_MULTI/P_ADV tiếng Anh của bản gốc `proposed.ipynb` — theo đúng yêu
cầu người dùng 2026-08-26: bỏ hết phần sinh câu hỏi cũ, code lại)."""
from __future__ import annotations

P_MOT_BUOC = (
    "Bạn là chuyên gia ra đề QA cho benchmark RAG pháp luật Việt Nam.\n\n"
    "Nhiệm vụ: từ NGỮ CẢNH dưới đây, sinh 1 câu hỏi-đáp một bước (chỉ cần đúng 1 đoạn để trả lời).\n"
    "Yêu cầu:\n"
    "- Hỏi về NỘI DUNG (ai/cái gì/khi nào/bao lâu/bao nhiêu/tại sao), KHÔNG hỏi về cấu trúc văn bản.\n"
    "- KHÔNG hỏi dạng Có/Không.\n"
    "- Diễn đạt lại (paraphrase) — KHÔNG chép nguyên câu chữ đặc trưng trong ngữ cảnh, "
    "để không thể trả lời chỉ bằng khớp từ khoá.\n"
    "- Đáp án lấy trực tiếp được từ ngữ cảnh, ngắn gọn.\n\n"
    "NGỮ CẢNH ({breadcrumb}):\n```\n{ctx}\n```\n\n"
    'Trả JSON: {{"question": "...", "answer": "..."}}'
)

# Siet chat 2026-08-26 (do luong thuc te: ~50% bi loai o vong omission-test — cau
# hoi tuy co dung "fact_chi_co_a/b" nhung van vo tinh tra loi duoc chi voi 1 doan).
# Them yeu cau: dap an PHAI la 1 GIA TRI DUY NHAT chi tinh toan/suy ra duoc khi GHEP
# ca 2 (vd dieu kien o A + so lieu o B -> ket luan), khong phai 2 y doc lap ghep lai.
P_CAU_TRUC = (
    "Bạn là chuyên gia ra đề QA nhiều bước (multi-hop) cho benchmark RAG pháp luật Việt Nam.\n\n"
    "Đọc 2 ĐOẠN A và B — B có tham chiếu THẬT tới A (B ghi rõ 'theo Điều/Khoản ... của văn bản này' "
    "trỏ đúng vào A).\n\n"
    "Quy trình bắt buộc:\n"
    "1. Liệt kê 1-2 sự kiện CHỈ có trong A (không có trong B).\n"
    "2. Liệt kê 1-2 sự kiện CHỈ có trong B (không có trong A).\n"
    "3. Viết chuỗi suy luận 2 bước: bước 1 dùng B để biết B tham chiếu tới điều khoản nào của A; "
    "bước 2 dùng nội dung đó trong A để suy ra đáp án cuối.\n"
    "4. QUAN TRỌNG: đáp án phải là 1 kết luận DUY NHẤT chỉ tính/suy ra được khi KẾT HỢP cả điều "
    "kiện/định nghĩa ở A VỚI số liệu/quy định cụ thể ở B (hoặc ngược lại) — KHÔNG phải 2 ý độc lập "
    "ghép cạnh nhau. Tự kiểm tra: nếu chỉ đọc B mà vẫn suy ra được đáp án (vì B đã đủ ngữ cảnh), "
    "PHẢI viết lại câu hỏi cho tới khi thật sự cần A.\n"
    "5. Đặt câu hỏi sao cho CHỈ đọc A hoặc CHỈ đọc B không thể trả lời được — phải cần CẢ HAI.\n\n"
    "Cấm: câu hỏi Có/Không; câu hỏi chỉ cần 1 đoạn là trả lời được.\n\n"
    "ĐOẠN A ({breadcrumb_a}):\n```\n{ctx_a}\n```\n"
    "ĐOẠN B ({breadcrumb_b}, có tham chiếu tới A):\n```\n{ctx_b}\n```\n\n"
    'Trả JSON: {{"question":"...","answer":"...","fact_chi_co_a":"...","fact_chi_co_b":"...",'
    '"buoc_1":"...","buoc_2":"..."}}'
)

# Sua 2026-08-26: khong con dua san "NOI DUNG MOI" (bug that phat hien qua test —
# ghep bua 1 Dieu cua VB nguon, ra cau hoi lech han chu de). Thay vao do dua TOAN
# VAN van ban nguon, bat LLM TU TIM dung doan viet lai/thay the noi dung cu — dung
# cach da lam thanh cong voi _trich_cap_dieu.py (doc toan van, tim dung Dieu dich).
P_THAY_DOI_HIEU_LUC = (
    "Bạn là chuyên gia ra đề QA về THAY ĐỔI HIỆU LỰC pháp luật (RAG benchmark).\n\n"
    "NỘI DUNG CŨ dưới đây (đã hết hiệu lực từ {ngay_het_hl}) đã bị văn bản {so_hieu_nguon} "
    "sửa đổi/thay thế. Đọc TOÀN VĂN văn bản {so_hieu_nguon}, TÌM ĐÚNG đoạn viết lại/thay thế "
    "cho đúng nội dung cũ này (thường ghi dạng 'Điều X. Sửa đổi, bổ sung ... như sau: ...').\n\n"
    "Nếu KHÔNG tìm thấy đoạn thay thế rõ ràng tương ứng (vd trường hợp bãi bỏ hẳn, không có nội "
    "dung mới thay vào), trả về JSON với \"tim_thay\": false và để trống các trường còn lại — "
    "TUYỆT ĐỐI KHÔNG bịa nội dung mới.\n\n"
    "Nếu tìm thấy, sinh 1 câu hỏi mà đáp án BẮT BUỘC nêu RÕ CẢ quy định CŨ lẫn MỚI (không chỉ 1 "
    "chiều) — ví dụ dạng 'quy định về X đã thay đổi thế nào', không hỏi 'quy định hiện hành là gì'.\n\n"
    "NỘI DUNG CŨ ({breadcrumb_cu}):\n```\n{ctx_cu}\n```\n\n"
    "TOÀN VĂN văn bản {so_hieu_nguon} (đi tìm đoạn thay thế trong này):\n```\n{toan_van_nguon}\n```\n\n"
    'Trả JSON: {{"tim_thay": <true|false>, "question":"...", "answer":"...", '
    '"gia_tri_cu":"...", "gia_tri_moi":"..."}}'
)

P_GAI_BAY = (
    "Bạn là chuyên gia ra đề QA gài bẫy (adversarial) cho benchmark RAG pháp luật Việt Nam.\n\n"
    "Nhiệm vụ: tạo 1 câu hỏi-đáp mà đáp án SAI CÓ CHỦ ĐÍCH — đổi 1 giá trị cụ thể trong NGỮ CẢNH.\n\n"
    "Các bước:\n"
    "1. Tìm 1 con số/mức phạt/thời hạn/tỷ lệ % cụ thể trong NGỮ CẢNH — gọi là gia_tri_goc.\n"
    "2. Đặt ra gia_tri_doi — khác rõ rệt, KHÔNG xuất hiện trong ngữ cảnh (kể cả dạng chuỗi con).\n"
    "3. Viết câu hỏi tự nhiên (diễn đạt lại, không chép nguyên câu chữ đặc trưng) về giá trị đó; "
    "đáp án chứa gia_tri_doi.\n\n"
    "NGỮ CẢNH ({breadcrumb}):\n```\n{ctx}\n```\n\n"
    'Trả JSON: {{"question":"...","answer":"...","gia_tri_goc":"...","gia_tri_doi":"..."}}'
)

P_BAY_HIEU_LUC = (
    "Bạn là chuyên gia ra đề QA kiểm tra khả năng nhận biết QUY ĐỊNH ĐÃ HẾT HIỆU LỰC "
    "(RAG benchmark pháp luật Việt Nam) — lỗi rất phổ biến của RAG luật là trả lời theo văn bản cũ.\n\n"
    "NGỮ CẢNH dưới đây đã HẾT HIỆU LỰC từ {ngay_het_hl}, hiện được thay thế bởi quy định mới.\n\n"
    "Sinh 1 câu hỏi hỏi về nội dung trong NGỮ CẢNH này, NHƯNG KHÔNG được nhắc rằng đây là quy định cũ/"
    "đã hết hiệu lực trong câu hỏi (để test xem hệ thống có tự phát hiện và cảnh báo hay không).\n"
    "Đáp án CHUẨN phải: (a) nêu đúng nội dung trong ngữ cảnh này, VÀ (b) cảnh báo rõ đây là quy định "
    "ĐÃ HẾT HIỆU LỰC từ {ngay_het_hl}, không nên áp dụng.\n\n"
    "NGỮ CẢNH ({breadcrumb}, ĐÃ HẾT HIỆU LỰC):\n```\n{ctx}\n```\n\n"
    'Trả JSON: {{"question":"...","answer":"..."}}'
)


def breadcrumb(so_hieu: str, duong_dan: str) -> str:
    return f"{so_hieu} — {duong_dan.replace('Dieu', 'Điều').replace('Khoan', 'Khoản').replace('Diem', 'Điểm').replace(' > ', ', ')}"
