# Giải pháp: Sinh bộ câu hỏi eval từ cây quan hệ văn bản luật

> Mục tiêu: xây bộ câu hỏi eval cho hệ RAG (đo faithfulness / context precision / context recall) bằng cách khai thác cây quan hệ đã có sẵn trong Neo4j của dự án `legal-rag`, thay vì soạn tay hoặc dùng testset generator generic (Ragas thuần) không hiểu ngữ nghĩa pháp lý VN.

---

## Bước 1 — Trích "cây quan hệ" làm nguồn sự thật (không cần dựng mới)

Đồ thị Neo4j hiện có **đã là cây quan hệ** cần dùng — không cần vẽ lại. Chỉ cần rút ra các **mẫu hình quan hệ (pattern)** có ý nghĩa pháp lý; mỗi mẫu hình tương ứng với một loại tình huống mà hệ RAG cần được kiểm tra.

| Mẫu hình quan hệ trong cây | Tình huống pháp lý nó thể hiện |
|---|---|
| A → REPLACES → B | Văn bản mới thay thế văn bản cũ, có mốc ngày hiệu lực |
| 1 Component có nhiều Expression theo thời gian | Một điều khoản đã bị sửa nhiều lần — cần biết nội dung "tại một thời điểm" |
| Con → GUIDED_BY → Mẹ, rồi Mẹ bị REPLACES | Nghị định/Thông tư hướng dẫn có còn hiệu lực khi luật mẹ đã bị thay hay không |
| Expression bị đóng bởi Action | Lịch sử sửa đổi của một điều khoản cụ thể (ai sửa, khi nào) |
| TransitionRule đã duyệt gắn với một Norm | Tình huống chuyển tiếp — áp dụng văn bản nào |
| Hai Norm khác cấp bậc cùng điều chỉnh một vấn đề | Ca xung đột cần "lex superior/specialis" — vùng xám cố ý |
| Một Điều còn hiệu lực, nội dung độc lập | Câu hỏi nội dung thông thường |

Mỗi hàng = một "khuôn" để quét toàn bộ cây và lấy ra hàng loạt bộ ba **(tình huống thật, đáp án đúng, trích dẫn nguồn)** — hoàn toàn tự động, không cần đọc tay.

---

## Bước 2 — Sinh câu hỏi theo 2 tầng, không phải 1 tầng LLM duy nhất

- **Tầng 1 — Khung câu hỏi dựng sẵn (deterministic):** Với mỗi bộ ba lấy được ở Bước 1, ghép vào một mẫu câu cố định theo đúng loại tình huống (ví dụ mẫu "Văn bản X bị thay thế bởi văn bản nào?"). Câu hỏi và đáp án ở tầng này **100% đúng theo dữ liệu gốc**, không có khả năng LLM bịa — vì hoàn toàn không dùng LLM ở bước sinh sự thật.
- **Tầng 2 — Diễn đạt lại cho tự nhiên (tuỳ chọn, chỉ cho loại câu hỏi nội dung):** Chỉ nhóm "câu hỏi nội dung thông thường" mới cần LLM viết lại câu hỏi cho giống người dùng thật hỏi — LLM ở bước này **chỉ được phép đổi cách diễn đạt, tuyệt đối không được thêm/bớt sự kiện, ngày tháng, số hiệu**. 6/7 nhóm còn lại không cần LLM chút nào, nên gần như miễn phí và không lo hết quota Groq.

---

## Bước 3 — Ưu tiên lấy mẫu theo tỷ trọng thực tế đã đo được

Dùng đúng số liệu audit đã có (REPLACES 8.063, AMENDS 8.193, GUIDED_BY 5.887...) để cân đối bộ eval, tránh việc bộ câu hỏi bị lệch hẳn về loại quan hệ chiếm số lượng lớn nhất — điều dễ xảy ra nếu lấy mẫu ngẫu nhiên thuần.

---

## Bước 4 — Đưa nhóm "xung đột cố ý" vào để test đúng hành vi từ chối

Nhóm "hai Norm khác cấp bậc cùng điều chỉnh" không chấm theo đúng/sai nội dung như các nhóm khác — mục đích của nhóm này là **kiểm tra hệ có dám trả lời "chưa xác định" hay bị ép ra một đáp án sai** (đúng nguyên tắc bất biến #7). Tách riêng thành một chỉ số chấm điểm khác: "tỷ lệ nhận diện đúng ca cần từ chối", không gộp chung vào độ chính xác nội dung.

---

## Bước 5 — Vòng lặp đánh giá

Bộ câu hỏi sinh ra (kèm đáp án đúng + trích dẫn nguồn) đưa qua hệ RAG thật để lấy câu trả lời + ngữ cảnh mà hệ thực sự truy hồi được, rồi so sánh hai bên bằng các chỉ số chuẩn (độ trung thực với ngữ cảnh, độ liên quan câu trả lời, độ chính xác/độ phủ của phần truy hồi). Vì đáp án đúng đã có sẵn từ cây quan hệ, vòng lặp này có thể lặp lại nhiều lần mỗi khi đổi tham số retrieval/rerank mà không tốn công soạn lại eval set.
