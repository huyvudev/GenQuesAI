# Giải pháp v2: Sinh bộ câu hỏi eval từ cây quan hệ văn bản luật

> **Mục tiêu:** xây bộ eval cho hệ RAG của dự án `legal-rag` bằng cách khai thác đồ thị Neo4j đã có, sao cho mỗi câu hỏi (a) có đáp án đúng truy được về dữ liệu gốc, (b) **chỉ ra được cấu phần nào của pipeline sai khi nó fail**, và (c) tái chạy được nhiều lần mà không phải soạn lại.

> **Thay đổi lớn so với v1:** bỏ cân tỷ trọng theo số cạnh trong đồ thị; gắn mỗi nhóm câu hỏi với cấu phần pipeline nó đo; định nghĩa gold context ở **cấp chunk** thay vì cấp node; thêm nhóm "không có đáp án"; thêm hợp đồng chấm điểm và tiêu chí nghiệm thu.

---

## 0 — Giả định & phạm vi

Tài liệu này giả định các nhãn/quan hệ sau đã tồn tại trong đồ thị: `Norm`, `Component`, `Expression`, `Action`, `TransitionRule`; quan hệ `REPLACES`, `AMENDS`, `GUIDED_BY`. **Cần đối chiếu lại tên thật trước khi code** — nếu lệch, chỉ phải sửa phần Cypher ở Bước 2, không ảnh hưởng thiết kế.

Ngoài phạm vi: eval cho tầng giao diện, đo latency/chi phí, và eval cho các loại văn bản chưa được nạp vào đồ thị.

---

## 1 — Trần chính xác của bộ eval (làm trước tiên)

Đáp án sinh từ đồ thị chỉ đúng **so với đồ thị**, không phải so với luật. Nếu pipeline extraction có lỗi (REPLACES ngược chiều, parse sai ngày hiệu lực, gán nhầm Điều), bộ eval sẽ mã hoá chính lỗi đó và chấm sai một hệ RAG trả lời đúng.

Vì vậy **bước đầu tiên không phải là sinh câu hỏi, mà là đo độ tin của nguồn**:

1. Rút mẫu phân tầng **50–100 bộ ba** (đều các nhóm ở Bước 2), review tay đối chiếu văn bản gốc.
2. Ghi lại tỷ lệ đúng → gọi là `eval_set_ceiling`. Mọi chỉ số về sau phải được đọc kèm con số này.
3. Nếu `eval_set_ceiling < 95%` ở nhóm nào, **không đưa nhóm đó vào bộ eval tự động** — sửa extraction trước, hoặc chuyển nhóm đó sang chế độ human-verified toàn bộ.

Chi phí: một buổi review. Không làm bước này thì mọi con số ở Bước 6 đều không diễn giải được.

---

## 2 — Bảng mẫu hình: mỗi nhóm đo cái gì, chấm thế nào

Đây là bảng trung tâm của toàn bộ thiết kế. Cột "Cấu phần đo được" là thứ v1 thiếu — không có nó, một câu fail không quy được về hành động sửa.

| Mã | Mẫu hình trong đồ thị | Tình huống pháp lý | Cấu phần pipeline nó đo | Dạng đáp án | Cách chấm |
|---|---|---|---|---|---|
| **G1** | `A -[:REPLACES]-> B` | Văn bản mới thay văn bản cũ, có mốc hiệu lực | Router → truy vấn metadata/graph | ID văn bản + ngày | Exact-match |
| **G2** | 1 `Component` có nhiều `Expression` theo thời gian | Nội dung điều khoản "tại một thời điểm" | Bộ lọc thời gian + chọn phiên bản | Đoạn nội dung | Faithfulness + gold chunk |
| **G3** | `Con -[:GUIDED_BY]-> Mẹ`, `Mẹ` bị `REPLACES` | Nghị định/Thông tư hướng dẫn còn hiệu lực không | Suy luận nhiều bước trên đồ thị | Có/Không + lý do | Exact-match nhãn + judge lý do |
| **G4** | `Expression` bị đóng bởi `Action` | Lịch sử sửa đổi một điều khoản (ai sửa, khi nào) | Truy vấn metadata + tổng hợp danh sách | Danh sách (văn bản, ngày) | Set-F1 |
| **G5** | `TransitionRule` đã duyệt gắn với `Norm` | Tình huống chuyển tiếp — áp dụng văn bản nào | Router + suy luận điều kiện | ID văn bản + điều kiện | Exact-match + judge |
| **G6** | Hai `Norm` khác cấp cùng điều chỉnh một vấn đề | Ca cần lex superior/specialis — vùng xám cố ý | Hành vi từ chối | Nhãn: `từ chối` / `nêu cả hai` | Tỷ lệ nhận diện đúng (chỉ số riêng) |
| **G7** | Một Điều còn hiệu lực, nội dung độc lập | Câu hỏi nội dung thông thường | Vector retrieval + synthesis | Đoạn nội dung | Faithfulness, answer relevancy, context precision/recall |
| **G8** | *(không có trong đồ thị — sinh chủ đích)* | Câu hỏi hệ chắc chắn không có dữ liệu | Hành vi từ chối / chống bịa | Nhãn: `không có thông tin` | Tỷ lệ từ chối đúng (chỉ số riêng) |

### 2.1 — Hai dạng câu hỏi, phải tách bạch

Câu hỏi template có nguy cơ **rò rỉ từ khoá**: nếu câu hỏi chứa đúng số hiệu văn bản, BM25 trúng chunk đích ngay lập tức và điểm retrieval đẹp giả tạo. Vì vậy mỗi câu phải mang nhãn `question_form`:

- **`lookup`** — người hỏi biết số hiệu/số Điều ("Nghị định 15/2020/NĐ-CP bị thay thế bởi văn bản nào?"). Đo được graph/metadata, **không** đo được retrieval.
- **`situation`** — người hỏi chỉ mô tả sự việc, không nêu số hiệu ("Doanh nghiệp tôi nhập khẩu thực phẩm chức năng thì thủ tục công bố hiện nay theo quy định nào?"). Đây mới là dạng đo retrieval thật.

Tỷ lệ mục tiêu: **40% `lookup` / 60% `situation`** trên toàn bộ. Nhóm G2 và G7 phải có ít nhất một nửa là `situation`.

### 2.2 — Distractor có chủ đích

Khi quét đồ thị, **ưu tiên chọn ca có "anh em gần"** thay vì ca dễ:

- cùng số hiệu khác năm ban hành,
- cùng số Điều nhưng thuộc văn bản khác,
- văn bản có nhiều lần sửa đổi liên tiếp (chọn phiên bản giữa, không chọn phiên bản đầu/cuối).

Ghi các id gây nhiễu vào trường `distractor_ids` để sau này phân tích: hệ trả sai vì *không tìm được* hay vì *tìm nhầm anh em gần*. Không có bước này, bộ eval sẽ không phân biệt nổi retriever tốt và retriever tệ.

---

## 3 — Sinh câu hỏi theo 2 tầng

**Tầng 1 — Khung dựng sẵn (deterministic).** Mỗi bộ ba `(tình huống, đáp án, nguồn)` lấy ở Bước 2 ghép vào mẫu câu cố định theo nhóm. Không dùng LLM ⇒ không có khả năng bịa sự kiện. Đây là nguồn sự thật duy nhất.

**Tầng 2 — Diễn đạt lại (LLM).** Áp dụng cho **mọi câu `situation`**, không chỉ nhóm G7 như v1 — vì câu `situation` bắt buộc phải bỏ số hiệu văn bản và viết lại theo giọng người dùng thật, mà việc đó không làm bằng template được.

Ràng buộc cứng cho LLM ở tầng này:

- chỉ được đổi cách diễn đạt; **cấm** thêm/bớt/sửa sự kiện, ngày tháng, số hiệu, tên cơ quan;
- **không được** chạm vào trường `answer` và `gold_chunk_ids` — LLM chỉ nhận và trả về đúng chuỗi câu hỏi;
- mỗi câu paraphrase phải qua kiểm tự động: mọi số hiệu/ngày xuất hiện trong bản gốc mà **không** cố ý bị lược bỏ thì phải còn nguyên trong bản mới; câu vi phạm bị loại, không sửa.

Ước tính: khoảng 60% số câu cần gọi LLM (phần `situation`), phần còn lại miễn phí.

---

## 4 — Quota cố định thay cho cân theo số cạnh

v1 cân bộ eval theo số lượng cạnh đã audit (REPLACES 8.063, AMENDS 8.193, GUIDED_BY 5.887…). **Đây là sai trục.** Số cạnh phản ánh cấu trúc hệ thống văn bản luật, không phản ánh phân bố câu hỏi người dùng, cũng không phản ánh độ khó. 8k cạnh `REPLACES` không có nghĩa 30% câu hỏi thực tế là về thay thế văn bản.

Thay bằng **quota cố định, nghiêng về nhóm khó** (tổng 400 câu cho vòng đầu):

| Nhóm | Số câu | Lý do trọng số |
|---|---|---|
| G7 — nội dung thông thường | 90 | Chiếm đa số truy vấn thực tế |
| G2 — tại một thời điểm | 80 | **Chỗ hệ RAG gãy nhiều nhất**, cần độ phân giải cao |
| G3 — hiệu lực dây chuyền | 60 | Suy luận nhiều bước, giá trị chẩn đoán cao |
| G1 — thay thế văn bản | 50 | Dễ, nhưng là kiểm tra hồi quy nền |
| G4 — lịch sử sửa đổi | 40 | Đo khả năng tổng hợp danh sách |
| G5 — chuyển tiếp | 30 | Ít ca sạch trong đồ thị |
| G6 — xung đột cố ý | 25 | Giới hạn bởi năng lực review tay |
| G8 — không có đáp án | 25 | Rẻ để sinh, đo hallucination trực tiếp |
| **Tổng** | **400** | |

Khi có log truy vấn thật, bổ sung một nhóm **G9 — từ log người dùng** và dịch dần trọng số về phân bố thật. Đó mới là căn cứ hợp lệ để đổi tỷ trọng.

---

## 5 — Gold context phải ở cấp chunk

Đây là chi tiết implementation dễ vỡ nhất và v1 chưa nhắc tới.

`context_precision` / `context_recall` so sánh **ngữ cảnh retriever trả về** với **ngữ cảnh đúng**. Retriever trả về *chunk*, còn đồ thị cho ta *node*. Nếu gold context chỉ ghi node id, hai bên không so được — chỉ số sẽ hoặc không tính được, hoặc tính sai một cách âm thầm.

Yêu cầu bắt buộc:

- mỗi item eval phải có `gold_chunk_ids: [...]` — id của **đúng những chunk mà retriever có khả năng trả về**, lấy từ chính index đang phục vụ RAG, không phải từ một lần chunk lại;
- giữ thêm `gold_node_ids` để truy vết ngược về đồ thị;
- nếu một node không map được sang chunk nào trong index hiện tại → **loại item đó**, đồng thời ghi nhận như một lỗi coverage của pipeline ingest (thông tin này tự nó đã có giá trị).

---

## 6 — Hợp đồng chấm điểm

Không dùng một cách chấm cho tất cả. LLM judge đắt, chậm và trôi giữa các lần chạy — chỉ dùng nơi thật sự cần.

| Loại đáp án | Nhóm | Cách chấm | Ghi chú |
|---|---|---|---|
| ID văn bản, ngày hiệu lực | G1, G5 | **Exact-match** sau chuẩn hoá | Chuẩn hoá số hiệu và định dạng ngày trước khi so |
| Danh sách (văn bản, ngày) | G4 | **Set-F1** | Phạt cả thiếu lẫn thừa |
| Nhãn có/không | G3 | Exact-match nhãn; lý do chấm bằng judge | Tách 2 điểm, đừng gộp |
| Đoạn nội dung | G2, G7 | Faithfulness, answer relevancy, context precision/recall | Judge chỉ ở đây |
| Nhãn từ chối | G6, G8 | Tỷ lệ nhận diện đúng | **Chỉ số riêng, không gộp vào accuracy** |

### 6.1 — Định nghĩa lại nhóm G6 cho chặt

v1 định nghĩa xung đột là "hai Norm khác cấp bậc cùng điều chỉnh một vấn đề". **Định nghĩa này quá lỏng** — nghị định hướng dẫn luật là quan hệ bình thường, không phải mâu thuẫn. Label tự động theo tiêu chí này sẽ phạt hệ thống vì nó trả lời đúng.

Một ca chỉ được vào G6 khi thoả **cả ba**:

1. hai norm cùng còn hiệu lực tại thời điểm hỏi;
2. cùng điều chỉnh một hành vi/đối tượng cụ thể;
3. đưa ra **hệ quả pháp lý khác nhau** (mức, thời hạn, điều kiện) — không phải chỉ khác mức độ chi tiết.

Điều kiện (3) không tự động hoá đáng tin được ⇒ **G6 bắt buộc human review 100%**. Giữ nhóm nhỏ (25 câu) nhưng sạch, tốt hơn 200 câu nhiễu.

---

## 7 — Schema output

Một dòng JSONL cho mỗi item. Freeze file này lại; mọi lần chạy eval đọc đúng file đã freeze.

```json
{
  "id": "G2-0137",
  "group": "G2",
  "question_form": "situation",
  "question": "Hiện nay doanh nghiệp nhập khẩu thực phẩm chức năng phải công bố sản phẩm theo thủ tục nào?",
  "question_template": "Nội dung của {component} tại thời điểm {as_of_date} là gì?",
  "as_of_date": "2024-07-01",
  "answer": "…",
  "answer_type": "passage",
  "gold_chunk_ids": ["chunk_88213", "chunk_88214"],
  "gold_node_ids": ["Expression:41207"],
  "distractor_ids": ["chunk_71902"],
  "grader": "faithfulness+context_recall",
  "difficulty": "hard",
  "human_verified": false,
  "graph_snapshot": "2026-08-06T14:00Z",
  "index_version": "bge-m3_v3"
}
```

Bắt buộc có `graph_snapshot` và `index_version`: đồ thị hoặc index đổi thì bộ eval stale, và so sánh giữa các lần chạy mất ý nghĩa. Khi một trong hai đổi, sinh bộ mới và **giữ bộ cũ** để so hồi quy.

---

## 8 — Vòng lặp đánh giá

1. Chạy toàn bộ 400 câu qua hệ RAG thật, thu `answer` + `retrieved_contexts`.
2. Chấm theo đúng grader của từng nhóm (Bước 6) — không gộp.
3. Báo cáo **tách theo nhóm và theo `question_form`**, kèm `eval_set_ceiling`. Một con số tổng duy nhất che mất chính thứ ta cần biết.
4. Khi đổi tham số retrieval/rerank: chạy lại trên đúng file đã freeze, so delta theo từng nhóm.

Phân tích lỗi cần trả lời được: câu sai vì *retriever không tìm thấy* (gold chunk không nằm trong top-k), vì *tìm nhầm distractor*, hay vì *tìm đúng nhưng synthesis sai*. Ba nguyên nhân này dẫn tới ba hành động sửa hoàn toàn khác nhau — trường `distractor_ids` và `gold_chunk_ids` tồn tại chính là để tách được chúng.

---

## 9 — Tiêu chí nghiệm thu

Bộ eval được coi là dùng được khi:

- [ ] `eval_set_ceiling ≥ 95%` trên mẫu audit tay ở Bước 1, đo riêng từng nhóm;
- [ ] đủ 400 câu theo đúng quota Bước 4, sai lệch mỗi nhóm ≤ 10%;
- [ ] tỷ lệ `situation` ≥ 55% toàn bộ; G2 và G7 mỗi nhóm ≥ 50%;
- [ ] 100% item có `gold_chunk_ids` không rỗng và mọi chunk id đều tồn tại trong index hiện hành;
- [ ] G6 và G8 đã human-verified toàn bộ;
- [ ] 0 câu paraphrase vi phạm kiểm tra bảo toàn số hiệu/ngày ở Bước 3;
- [ ] file JSONL đã freeze, có `graph_snapshot` + `index_version`, đã commit.

Chưa đặt ngưỡng điểm mục tiêu cho hệ RAG ở vòng này — **vòng đầu là để lấy baseline**, ngưỡng đặt sau khi có số thật.

---

## Phụ lục — Điểm cần bổ sung từ phía dự án

- **Nguyên tắc bất biến #7** được viện dẫn ở nhóm G6 (hành vi từ chối) nhưng chưa trích nội dung ở đây — cần chép một dòng vào để tài liệu tự đứng được.
- Cần xác nhận tên nhãn/quan hệ Neo4j thật (mục 0) trước khi viết Cypher.
- Cần xác nhận `chunk_id` của index hiện hành là ổn định qua các lần re-index, hay đổi mỗi lần — nếu đổi, phải map qua một khoá bền hơn, nếu không toàn bộ `gold_chunk_ids` sẽ mục sau lần re-index đầu tiên.
