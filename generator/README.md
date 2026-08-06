# Bộ sinh câu hỏi eval

Sinh bộ đề từ đồ thị Neo4j + index Qdrant của `legal-rag`. Thiết kế đầy đủ ở
[`../giai-phap-sinh-cau-hoi-eval.md`](../giai-phap-sinh-cau-hoi-eval.md).

## Chạy

Không cần cài gì thêm — dùng luôn venv của `legal-rag` (đã có `neo4j`, `qdrant_client`):

```bash
cd D:/Project/GenQuesAI
"D:/Project/Chatbot-Law/chatbot/.venv/Scripts/python.exe" -m generator.run_g1 \
    --n 50 --pool 2500 --out out/g1.jsonl
```

Cần Neo4j (`:7687`) và Qdrant (`:6333`) đang chạy. **Không cần LLM, không cần `ragas`** —
G1 hoàn toàn deterministic. Đường dẫn tới repo RAG đổi được bằng biến môi trường
`LEGAL_RAG_ROOT`.

## Cấu trúc

| File | Việc |
|---|---|
| `common.py` | `point_id` (bản chép + tự đối chiếu), chuẩn hoá số hiệu, hash, kết nối |
| `gold.py` | Tìm gold span trong Qdrant, chấm điểm bằng chứng, cổng C1 |
| `g1_replaces.py` | Chọn ca + dựng item cho nhóm G1 |
| `run_g1.py` | CLI |

## Hai chốt chặn chạy trước khi sinh

**1. `point_id` phải khớp index thật.** `common.point_id` là bản chép từ
`legal_rag/retrieval/index.py` (không import trực tiếp vì module đó kéo theo
`embedder` → torch). `verify_point_id()` đối chiếu 20 point ngẫu nhiên với id thật
trong Qdrant; lệch thì dừng, không sinh đề trên công thức đã lỗi thời.

**2. Cổng C1 kiểm hash trước, offset sau.** Chunk có thể giữ nguyên `chunk_id` mà đổi
nội dung (§10.1 R1) — chỉ hash bắt được. Rớt C1 là **lỗi pipeline**, phải điều tra
chứ không phải loại câu rồi đi tiếp.

## Chấm điểm bằng chứng (`evidence_score`)

Số hiệu văn bản cũ xuất hiện trong văn bản mới **không** đương nhiên là bằng chứng bãi
bỏ — nó có thể chỉ là dẫn chiếu. `gold._diem_bang_chung()` chấm:

| Điểm | Nghĩa |
|---|---|
| +2 | tiêu đề Điều chứa "hiệu lực" / "thi hành" / "chuyển tiếp" / "bãi bỏ" |
| +3 | có từ khoá bãi bỏ **đứng trước** số hiệu → đúng câu dẫn của điều khoản |
| +1 | có từ khoá nhưng đứng sau → yếu hơn |

Ngưỡng nhận `>= 3` (`MIN_DIEM_BANG_CHUNG`). Span được nới **ngược lên tới câu dẫn**,
vì điều khoản thi hành viết dạng *"Các quy định sau đây hết hiệu lực…:"* rồi mới liệt
kê — cắt riêng mục danh sách sẽ mất câu mang nghĩa.

## Kết quả G1 (2026-08-06)

```
point_id đối chiếu index: 20/20 khớp
50 item ghi ra out/g1.jsonl

ung_vien                2500      C1 pass                 50/50
bỏ vì số hiệu              8      có gold_spans           50/50
bỏ vì trùng VB mới         0      có distractor           50/50
bỏ vì bằng chứng yếu       4      span có từ khoá         43/50
bỏ vì không thấy span      6      evidence_score 5: 37 · 3: 13
tỷ lệ sống sót         73.5%      độ dài span  139–892 (tb 408)
```

`C1 fail = 0` — index và công thức `point_id` nhất quán.

## Còn lại

- **C4 (ablation) chưa chạy** — cần LLM, đang để `not_run`.
- **C5 (review tay) chưa lấy mẫu.** Cần người đọc, đặc biệt nhóm Luật (`/QH`): ví dụ
  *"03/2022/QH15 bị thay thế bởi văn bản nào?"* — 03/2022 vốn là luật **sửa đổi** cho
  27/2008/QH12, cả hai cùng hết hiệu lực khi luật mới ra. Đồ thị ghi vậy và văn bản
  xác nhận vậy, nhưng câu hỏi đặt thẳng vào văn bản sửa đổi thì hơi khiên cưỡng —
  cần người có chuyên môn phán.
