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
    "Cấm: câu hỏi Có/Không; câu hỏi chỉ cần 1 đoạn là trả lời được. 'A'/'B' CHỈ là nhãn tạm để bạn "
    "phân biệt 2 đoạn trong hướng dẫn này — TUYỆT ĐỐI KHÔNG chép nguyên chữ 'A'/'B'/'đoạn A'/'văn "
    "bản B' vào question/answer/fact_chi_co_a/fact_chi_co_b/buoc_1/buoc_2 — phải gọi bằng tên/số "
    "hiệu văn bản và Điều/Khoản THẬT (vd 'Điều 5 Nghị định 10/2020/NĐ-CP', không phải 'Điều A').\n\n"
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


# Loai moi 2026-09-04: bai bo TUNG PHAN (khac P_THAY_DOI_HIEU_LUC — o day KHONG co
# noi dung thay the, chi la XOA; khac P_BAY_HIEU_LUC — o day Dieu CHA van con hieu
# luc, chi 1 khoan/diem con cua no mat hieu luc, khong phai ca Dieu).
P_BAI_BO_TUNG_PHAN = (
    "Bạn là chuyên gia ra đề QA kiểm tra khả năng nhận biết BÃI BỎ TỪNG PHẦN "
    "(RAG benchmark pháp luật Việt Nam) — lỗi phổ biến: RAG coi cả Điều còn nguyên "
    "hiệu lực (vì đa số nội dung Điều còn đúng), trong khi 1 khoản/điểm cụ thể bên "
    "trong đã bị bãi bỏ và không còn áp dụng.\n\n"
    "PHẦN dưới đây ({breadcrumb_phan}) đã bị BÃI BỎ (xoá bỏ, KHÔNG có nội dung thay "
    "thế) từ {ngay_het_hl}. Điều CHA chứa nó ({breadcrumb_dieu}) HIỆN VẪN CÒN HIỆU "
    "LỰC — nội dung hiện hành của Điều cha (đã bỏ phần bị bãi bỏ) cho ở dưới.\n\n"
    "Sinh 1 câu hỏi hỏi về đúng NỘI DUNG của PHẦN ĐÃ BỊ BÃI BỎ này — hỏi tự nhiên "
    "như đang hỏi về 1 quy định hiện hành, KHÔNG được nhắc trong câu hỏi rằng phần "
    "này đã bị bãi bỏ (để test hệ thống có tự phát hiện hay không).\n"
    "Đáp án CHUẨN phải: (a) nêu rõ phần này ĐÃ BỊ BÃI BỎ từ {ngay_het_hl}, không còn "
    "áp dụng — KHÔNG được trả lời như thể nội dung đó vẫn còn hiệu lực, VÀ (b) nói rõ "
    "đây chỉ là bãi bỏ 1 phần, các nội dung khác của {breadcrumb_dieu} không bị ảnh "
    "hưởng và vẫn còn hiệu lực.\n\n"
    "PHẦN ĐÃ BỊ BÃI BỎ ({breadcrumb_phan}):\n```\n{ctx_phan}\n```\n\n"
    "NỘI DUNG HIỆN HÀNH của Điều cha ({breadcrumb_dieu}):\n```\n{ctx_dieu}\n```\n\n"
    'Trả JSON: {{"question":"...","answer":"..."}}'
)


# Loai moi 2026-09-04: multi-hop LIEN VAN BAN qua GUIDED_BY (Luat/Nghi dinh <-
# Nghi dinh/Thong tu huong dan). Quan he chi o cap Norm-Norm (khong biet dung Dieu
# nao cua B cu the hoa Dieu A) -> giong cach da giai voi QuanHeHieuLuc: dua TOAN VAN
# B cho LLM tu tim, tu choi (tim_thay:false) neu khong that su khop chu de.
P_HUONG_DAN_LIEN_VB = (
    "Bạn là chuyên gia ra đề QA nhiều bước (multi-hop) LIÊN VĂN BẢN cho benchmark RAG "
    "pháp luật Việt Nam.\n\n"
    "ĐIỀU A dưới đây thuộc văn bản gốc (quy định nguyên tắc chung). Văn bản B là văn bản "
    "HƯỚNG DẪN/CĂN CỨ theo văn bản của Điều A (quan hệ GUIDED_BY), tức B thường cụ thể "
    "hoá/hướng dẫn thi hành MỘT SỐ điều khoản của văn bản gốc (không phải toàn bộ).\n\n"
    "Bước 1: Đọc TOÀN VĂN B, tìm đoạn THẬT SỰ cụ thể hoá/hướng dẫn thi hành ĐÚNG nội dung "
    "của ĐIỀU A này (không phải đoạn nói về chủ đề khác của văn bản gốc). Đoạn B tìm được "
    "PHẢI là nội dung THỰC CHẤT/chuyên môn (số liệu, điều kiện, quy trình, đối tượng áp "
    "dụng, mức phạt...) — KHÔNG tính các đoạn CHUNG CHUNG/THỦ TỤC xuất hiện giống nhau ở "
    "hầu hết mọi văn bản (vd 'các Bộ, cơ quan ngang Bộ... chịu trách nhiệm thi hành', "
    "'Quyết định này có hiệu lực kể từ ngày...') dù chủ đề trùng khớp bề mặt. Nếu KHÔNG tìm "
    "thấy đoạn thực chất nào như vậy, trả về JSON với \"tim_thay\": false và để trống các "
    "trường còn lại — TUYỆT ĐỐI KHÔNG bịa.\n\n"
    "Nếu tìm thấy, quy trình bắt buộc (giống multi-hop nội bộ):\n"
    "1. Liệt kê 1-2 sự kiện CHỈ có trong Điều A.\n"
    "2. Liệt kê 1-2 sự kiện CHỈ có trong đoạn B tìm được.\n"
    "3. Viết chuỗi suy luận 2 bước: bước 1 dùng A để biết nguyên tắc/điều kiện chung, "
    "bước 2 dùng đoạn B để biết chi tiết/số liệu cụ thể hoá nguyên tắc đó.\n"
    "4. Đáp án phải là 1 kết luận DUY NHẤT chỉ tính/suy ra được khi KẾT HỢP cả Điều A "
    "VỚI đoạn B — không phải 2 ý độc lập ghép cạnh nhau. Tự kiểm tra: nếu chỉ đọc đoạn B "
    "mà vẫn suy ra được đáp án, PHẢI viết lại cho tới khi thật sự cần cả A.\n"
    "5. Đặt câu hỏi sao cho CHỈ đọc A hoặc CHỈ đọc đoạn B không thể trả lời được.\n\n"
    "Cấm: câu hỏi Có/Không. 'Điều A'/'văn bản B' CHỈ là nhãn tạm để bạn phân biệt 2 nguồn trong "
    "hướng dẫn này — TUYỆT ĐỐI KHÔNG chép nguyên chữ 'A'/'B'/'Điều A'/'văn bản B' vào "
    "question/answer/fact_chi_co_a/fact_chi_co_b/buoc_1/buoc_2 — phải gọi bằng tên/số hiệu văn bản "
    "và Điều/Khoản THẬT (vd 'Điều 5 Nghị định 10/2020/NĐ-CP', không phải 'Điều A').\n\n"
    "ĐIỀU A ({breadcrumb_a}):\n```\n{ctx_a}\n```\n"
    "TOÀN VĂN văn bản B ({so_hieu_b}, hướng dẫn/căn cứ theo văn bản của Điều A):\n```\n{toan_van_b}\n```\n\n"
    'Trả JSON: {{"tim_thay": <true|false>, "question":"...", "answer":"...", '
    '"doan_b_tim_duoc":"...", "fact_chi_co_a":"...", "fact_chi_co_b":"...", '
    '"buoc_1":"...", "buoc_2":"..."}}'
)


# Loai moi 2026-09-04: DIEU KHOAN CHUYEN TIEP (TransitionRule) — khac cac loai tren:
# dieu_kien/van_ban_ap_dung da tach san luc ingest, KHONG can LLM tim kiem gi them,
# chi can dung hoa thanh 1 tinh huong tu nhien + cau hoi.
P_CHUYEN_TIEP = (
    "Bạn là chuyên gia ra đề QA về ĐIỀU KHOẢN CHUYỂN TIẾP (transitional provision) cho "
    "benchmark RAG pháp luật Việt Nam — lỗi phổ biến: RAG áp dụng máy móc quy định MỚI cho "
    "các trường hợp phát sinh TRƯỚC ngày văn bản mới có hiệu lực, trong khi những trường hợp "
    "đó phải áp dụng theo quy định CHUYỂN TIẾP riêng (khác quy định mới).\n\n"
    "ĐIỀU KHOẢN CHUYỂN TIẾP dưới đây ({breadcrumb}) quy định: khi ĐIỀU KIỆN sau xảy ra thì "
    "áp dụng theo QUY ĐỊNH sau.\n\n"
    "ĐIỀU KIỆN: {dieu_kien}\n"
    "QUY ĐỊNH ÁP DỤNG: {van_ban_ap_dung}\n\n"
    "NGUYÊN VĂN đầy đủ (tham khảo thêm ngữ cảnh, không bắt buộc dùng hết):\n```\n{ctx}\n```\n\n"
    "Nhiệm vụ: dựng 1 TÌNH HUỐNG cụ thể (diễn đạt lại, KHÔNG chép nguyên câu chữ của ĐIỀU "
    "KIỆN) khớp đúng với ĐIỀU KIỆN trên, rồi hỏi trong tình huống đó thì áp dụng/xử lý ra sao.\n"
    "Yêu cầu:\n"
    "- Câu hỏi mô tả 1 tình huống/trường hợp CỤ THỂ (không hỏi trực tiếp bằng chính câu chữ "
    "ĐIỀU KIỆN ở trên).\n"
    "- KHÔNG hỏi dạng Có/Không — CẤM các câu hỏi kết thúc bằng '... hay không?', '... có phải "
    "không?', '... đúng không?'. Hỏi bằng 'xử lý thế nào', 'áp dụng quy định nào', 'phải làm "
    "gì' — KHÔNG hỏi 'có phải làm X hay không'.\n"
    "- Đáp án phải nêu đúng theo QUY ĐỊNH ÁP DỤNG ở trên, diễn đạt tự nhiên, đầy đủ.\n\n"
    'Trả JSON: {{"question":"...","answer":"..."}}'
)


# Loai moi 2026-09-05: multi-hop LIEN NGANH LUAT (2 luat DOC LAP, khac linh vuc, cung
# ap dung 1 tinh huong thuc te — vd Luat Dau tu + Luat Doanh nghiep khi thanh lap DN
# FDI). Khac han P_CAU_TRUC/P_HUONG_DAN_LIEN_VB: khong co canh trich dan/GUIDED_BY
# nao noi 2 luat nay — phai tu de xuat cap linh vuc (P_DE_XUAT_KICH_BAN_LIEN_NGANH,
# goi 1 LAN cho ca luot chay) roi tu dong khop ten luat vao Neo4j (data.py::tim_luat),
# KHONG can nguoi duyet (thu nghiem 2026-09-05: LLM de xuat + tu tham dinh lai o
# P_LIEN_NGANH la du an toan, xem thao luan kien truc). Da do thuc te: bar "bat buoc
# can ca 2 moi tra loi duoc" (giong P_CAU_TRUC) khien loai nay gan nhu khong ra duoc
# cau nao (0/45 mot mach) — PHAI noi bar thanh "can ca 2 de co dap an DAY DU/CHINH
# XAC" (van dam bao multi-hop that qua vong_1_omission o Buoc 3, chi khac muc do bat
# buoc). Sau khi noi, do duoc ~5% yield tren cac cap domain dung flavor.
P_DE_XUAT_KICH_BAN_LIEN_NGANH = (
    "Liệt kê {n} tình huống pháp lý THỰC TẾ phổ biến ở Việt Nam mà khi giải quyết PHẢI kết hợp "
    "kiến thức từ 2 NGÀNH LUẬT/LĨNH VỰC KHÁC NHAU thật sự (KHÔNG tính trường hợp 1 luật gốc + "
    "nghị định/thông tư hướng dẫn thi hành CHÍNH luật đó — chỉ tính 2 luật ĐỘC LẬP, thuộc 2 lĩnh "
    "vực khác nhau, cùng áp dụng cho 1 việc thực tế).\n\n"
    "Với mỗi tình huống, ghi:\n"
    "- boi_canh: mô tả CỤ THỂ 1-2 câu, có đủ TỪ KHOÁ CHUYÊN MÔN của cả 2 luật (không viết chung "
    "chung) — vd 'Nhà đầu tư nước ngoài xin thuê đất để xây nhà xưởng, cần biết tỷ lệ sở hữu vốn "
    "tối đa và thủ tục giao đất, cho thuê đất' (không viết 'doanh nghiệp thuê đất' suông).\n"
    "- ten_luat_a / ten_luat_b: TÊN VĂN BẢN LUẬT chính thức (vd 'Luật Đầu tư', 'Bộ luật Lao động') "
    "— phải là luật/bộ luật CẤP CAO (Quốc hội ban hành), không phải nghị định/thông tư.\n\n"
    'Trả JSON: {{"kich_ban": [{{"boi_canh":"...","ten_luat_a":"...","ten_luat_b":"..."}}, ...]}}'
)

P_LIEN_NGANH = (
    "Bạn là chuyên gia ra đề QA nhiều bước (multi-hop) LIÊN NGÀNH LUẬT cho benchmark RAG "
    "pháp luật Việt Nam.\n\n"
    "Bối cảnh chung: {boi_canh}\n\n"
    "Đọc 2 ĐOẠN A (thuộc {so_hieu_a}) và B (thuộc {so_hieu_b}) dưới đây.\n\n"
    "Bước 1 - THẨM ĐỊNH (bắt buộc làm trước): xác định A và B có THẬT SỰ CÙNG áp dụng trong 1 tình "
    "huống pháp lý thực tế khớp với bối cảnh trên không (LƯU Ý: 2 đoạn có thể xử lý 2 KHÍA CẠNH "
    "RIÊNG của cùng 1 tình huống — không nhất thiết đoạn này phụ thuộc đoạn kia — vẫn tính là liên "
    "quan, miễn là 1 câu trả lời ĐẦY ĐỦ/CHÍNH XÁC cho tình huống đó cần nêu CẢ 2 khía cạnh), hay "
    "chúng chỉ giống nhau ở BỀ MẶT (cùng nhắc 1 từ khoá) trong khi thực chất nói về 2 việc hoàn "
    "toàn độc lập, không cùng phục vụ tình huống nào cả.\n"
    "Nếu KHÔNG thật sự liên quan (2 việc độc lập), trả về JSON {{\"lien_quan\": false}} và DỪNG LẠI "
    "— TUYỆT ĐỐI KHÔNG cố ghép ép cho ra câu hỏi.\n\n"
    "Nếu THẬT SỰ liên quan, làm tiếp:\n"
    "1. Liệt kê 1-2 sự kiện CHỈ có trong A (không có trong B).\n"
    "2. Liệt kê 1-2 sự kiện CHỈ có trong B (không có trong A).\n"
    "3. Viết chuỗi suy luận 2 bước dẫn tới đáp án.\n"
    "4. Đáp án phải NÊU RÕ CẢ nội dung rút ra từ A LẪN từ B — 1 câu trả lời chỉ dựa vào 1 bên vẫn có "
    "thể ĐÚNG nhưng bị xem là THIẾU/KHÔNG ĐẦY ĐỦ. KHÔNG cần đáp án là kiểu suy luận diễn dịch bắt "
    "buộc (không cần 'nếu thiếu A thì tính sai số liệu') — chỉ cần A và B mỗi bên đóng góp 1 phần "
    "THIẾT YẾU cho 1 câu trả lời trọn vẹn.\n"
    "5. Đặt câu hỏi mô tả 1 TÌNH HUỐNG cụ thể tự nhiên (không hỏi trực tiếp bằng câu chữ của A/B), "
    "sao cho 1 câu trả lời chỉ dựa A HOẶC chỉ dựa B sẽ bị coi là thiếu ý.\n\n"
    "Cấm: câu hỏi Có/Không. 'A'/'B' CHỈ là nhãn tạm để bạn phân biệt 2 đoạn trong hướng dẫn này — "
    "TUYỆT ĐỐI KHÔNG chép nguyên chữ 'A'/'B'/'đoạn A'/'đoạn B' vào "
    "question/answer/fact_chi_co_a/fact_chi_co_b/buoc_1/buoc_2 — phải gọi bằng tên/số hiệu văn bản "
    "và Điều/Khoản THẬT (vd 'Điều 5 Luật Đầu tư', không phải 'Điều A').\n\n"
    "ĐOẠN A ({breadcrumb_a}):\n```\n{ctx_a}\n```\n"
    "ĐOẠN B ({breadcrumb_b}):\n```\n{ctx_b}\n```\n\n"
    'Trả JSON: {{"lien_quan": <true|false>, "question":"...","answer":"...",'
    '"fact_chi_co_a":"...","fact_chi_co_b":"...","buoc_1":"...","buoc_2":"..."}}'
)


def breadcrumb(so_hieu: str, duong_dan: str) -> str:
    return f"{so_hieu} — {duong_dan.replace('Dieu', 'Điều').replace('Khoan', 'Khoản').replace('Diem', 'Điểm').replace(' > ', ', ')}"
