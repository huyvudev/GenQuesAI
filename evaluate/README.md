# Tầng chấm — vòng đánh giá (Mục 6 & 8)

```bash
PY="D:/Project/Chatbot-Law/chatbot/.venv/Scripts/python.exe"
$PY -m evaluate.score --n 2                     # thử 2 câu/nhóm
$PY -m evaluate.score --out out/ket_qua.json    # chạy hết 375 câu
```

## Không dựng song song với `legal_rag/evaluation/`

`legal-rag` đã có một hệ eval hoàn chỉnh: `grader.py` **thuần** (không LLM, không DB),
chấm theo 4 chiều `citation · validity · content · behavior`; `runner.py` chịu được
hết quota (ca lỗi rate-limit đánh dấu BLOCKED, không tính pass/fail); và cả
`run_compare` đối chứng Graph RAG với RAG thuần.

Việc đúng là **đưa bộ đề 400 câu vào đúng khuôn đó**, không viết lại tầng chấm.

| File | Việc |
|---|---|
| `to_cases.py` | Bộ đề → khuôn `cases`/`expect` của `legal_rag.evaluation` |
| `ask_full.py` | Bọc `ask()` để giữ lại phần truy hồi mà nó bỏ đi |
| `score.py` | Gọi `grader.grade()` + đo cấp chunk + triage |

Điểm khớp đẹp nhất: `expect.not_governing` của họ **chính là** khái niệm "bẫy sai thời
điểm" của G2′ — văn bản KHÔNG được áp tại mốc hỏi. Bên kia đã có sẵn chỗ kiểm đúng thứ
đó, chỉ là chưa có ai sinh đủ ca để dùng.

## Ba thứ bổ sung

**1. Giữ lại đầu ra retrieval.** `ask()` trả `citations` **đã lọc theo câu trả lời** —
tức đầu ra của *synthesize*, không phải của *retrieval*. Chấm bằng nó thì không tách
được ba nguyên nhân sai. State của graph có sẵn khoá `retrieved`; `ask_full.py` bọc lại
ở repo NÀY, **không sửa code đang chạy production**.

`chunk_id` không nằm trong payload nhưng tính lại được bằng `point_id(expr_id, part)` —
công thức đã đối chiếu khớp 20/20 với index thật.

**2. Set-F1 cho G4′.** `grader` bên kia dùng `all(...)`: thiếu 1 trong 5 văn bản là 0
điểm. Câu hỏi danh sách cần phạt theo mức độ, nếu không sẽ không thấy hệ đang tiến bộ.

**3. Triage (Mục 8).** Mỗi ca sai gắn đúng một nhãn nguyên nhân:

| Nhãn | Điều kiện | Hành động |
|---|---|---|
| `retriever_sot` | gold không trong top-k | tăng k, đổi embedding, thêm BM25 hybrid |
| `retriever_nham` | bẫy xếp **trên** gold | thêm rerank, lọc theo metadata |
| `synthesis` | gold có mặt mà vẫn sai | sửa prompt, đổi model |

## Đọc báo cáo

Báo cáo in **`hạng gold`**, không in precision. Hầu hết ca chỉ có **một** gold chunk
nên `precision@12` trần là 1/12 ≈ 8% — gần như hằng số, không nói lên điều gì. Hạng của
chunk đúng thì đọc ra hành động ngay: hạng 1–3 mà vẫn sai ⇒ lỗi synthesis; hạng 9–12 ⇒
rerank yếu; không có hạng ⇒ retriever sót.

## Trạng thái

Đã chạy thử **14 ca (2/nhóm)** để chứng minh luồng thông — chưa chạy hết.

```
citation 67% · validity 83% · content 20% · behavior 100% · overall 64%
```

**Chưa đọc các con số này như kết quả.** n=14 quá nhỏ, và quan trọng hơn:
`eval_set_ceiling` (cổng C5) **chưa đo**, nên chưa biết trần trên là bao nhiêu.

Một giả thuyết đáng theo dõi khi chạy đủ: **G3 và G4′ recall 0%** ở mẫu thử. Đây là hai
nhóm duy nhất có gold span nằm ở **văn bản khác** với văn bản được hỏi (G3: điều khoản
bãi bỏ trong văn bản thay thế; G4′: điều khoản trong văn bản sửa đổi). Nếu giữ nguyên ở
cỡ mẫu lớn thì đó là tín hiệu kiến trúc — hệ truy hồi trong văn bản được hỏi chứ không
lần sang văn bản nhắc tới nó.

## Chi phí chạy đủ

~11 giây/câu (understand 1s · resolve 0,7s · retrieve 2,9s · rerank 2,6s · synthesize
4,6s), **375 câu ≈ 70 phút** và 2 lời gọi LLM mỗi câu.
