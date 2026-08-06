# Bộ sinh câu hỏi eval

Sinh bộ đề từ đồ thị Neo4j + index Qdrant của `legal-rag`. Thiết kế đầy đủ ở
[`../giai-phap-sinh-cau-hoi-eval.md`](../giai-phap-sinh-cau-hoi-eval.md).

## Chạy

Không cần cài gì thêm — dùng luôn venv của `legal-rag` (đã có `neo4j`, `qdrant_client`).
Cần Neo4j (`:7687`) và Qdrant (`:6333`) đang chạy. **Không cần `ragas`.** Đường dẫn tới
repo RAG đổi được bằng biến môi trường `LEGAL_RAG_ROOT`.

```bash
cd D:/Project/GenQuesAI
PY="D:/Project/Chatbot-Law/chatbot/.venv/Scripts/python.exe"

$PY -m generator.run_all --paraphrase all --out out/eval_set.jsonl   # trọn 400 câu
$PY -m generator.validate out/eval_set.jsonl                          # kiểm Mục 9

$PY -m generator.run_all --chi G3,G5 --out out/mot_phan.jsonl         # vài nhóm
$PY -m generator.run_g1 --n 50 --out out/g1.jsonl                     # một nhóm
```

`--paraphrase` **opt-in** — nó gọi API trả tiền bằng key trong `.env` của `legal-rag`.
Bỏ cờ này thì câu `situation` giữ bản template và cổng C2 ghi `chua_paraphrase`.

## Cấu trúc

| File | Việc |
|---|---|
| `common.py` | `point_id` (bản chép + tự đối chiếu), chuẩn hoá số hiệu, `chu_de_tu_norm`, hash, kết nối |
| `gold.py` | Tìm gold span trong Qdrant, chấm điểm bằng chứng, cổng C1 |
| `paraphrase.py` | Tầng LLM duy nhất + cổng C2 |
| `g1_replaces.py` `g2_temporal.py` `g3_chain.py` `g4_history.py` `g5_transition.py` `g6_conflict.py` `g7_content.py` `g8_unanswerable.py` | Tám nhóm |
| `run_all.py` | Sinh trọn bộ + gộp |
| `validate.py` | Kiểm theo tiêu chí nghiệm thu Mục 9 |

## Kết quả trọn bộ (2026-08-06)

```
nhóm  quota  sinh  situation      tổng sinh        400
G1       50    50          0      chờ review (G6)   25  ← chưa dùng được
G2       80    80         48      sẵn sàng         375
G3       60    60         36      situation        179
G4       40    40         20        · 60% trong nhóm hỗ trợ cả hai dạng
G5       30    30         21        · 45% trên toàn bộ
G6       25    25          0
G7       90    90         54      validate.py: ĐẠT toàn bộ tiêu chí
G8       25    25          0      kiểm được bằng máy
```

**G1, G6, G8 không dựng được dạng `situation`** — G1 phải nêu số hiệu mới hỏi được
"văn bản nào thay thế X"; G6 phải nêu cả hai văn bản; G8 hỏi về văn bản *không tồn
tại* nên buộc phải nêu định danh. Đây là 100 câu, nên tiêu chí "≥55% toàn bộ" không
đạt được về mặt cấu trúc — đã sửa thành "≥55% trong nhóm hỗ trợ cả hai dạng".

**G6 ở trạng thái `cho_review`**, không tính vào bộ dùng được: điều kiện (3) §4.2 —
hai quy định có *hệ quả pháp lý* khác nhau hay chỉ khác mức độ chi tiết — không tự
động hoá đáng tin được. **G8 không có `gold_spans` là đúng thiết kế**: câu không có
đáp án thì không có gì để trích dẫn.

## Còn lại

| Việc | Vì sao chưa làm |
|---|---|
| **C4 — ablation** | Cần chạy LLM không ngữ cảnh trên 400 câu |
| **C5 — review mẫu 50–100 câu** | Cần người; đây là thứ chốt `eval_set_ceiling`, **không có nó thì mọi chỉ số chưa diễn giải được** |
| **G6 duyệt 25 ca** | Điều kiện (3) §4.2 |

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

## G7 — nhóm nội dung (90 câu)

```bash
python -m generator.run_g7 --n 90 --pool 6000 --out out/g7.jsonl              # không LLM
python -m generator.run_g7 --n 90 --pool 6000 --paraphrase all --out out/g7.jsonl
```

`--paraphrase` **opt-in** vì nó gọi API trả tiền bằng key trong `.env` của `legal-rag`.
Không bật thì câu `situation` giữ bản template, cổng C2 ghi `chua_paraphrase`.

Điều kiện chọn ca, mỗi cái có lý do:

| Điều kiện | Vì sao |
|---|---|
| `hieu_luc_den IS NULL` | hỏi hiện tại, không lẫn G2′ |
| `n_parts = 1` | trọn nội dung trong **một** chunk — nếu không, đáp án trải nhiều chunk và `context_recall` mất nghĩa |
| loại tiêu đề thủ tục | "hiệu lực thi hành", "tổ chức thực hiện"… là boilerplate, và G1 đã dùng |
| loại tiêu đề boilerplate | "giải thích từ ngữ", "phạm vi điều chỉnh"… có ở gần như mọi văn bản ⇒ câu `situation` không nêu số hiệu sẽ **mơ hồ giữa 66.368 văn bản**, không có đáp án đúng duy nhất |
| tiêu đề 12–80 ký tự, không chứa số hiệu / tham chiếu Điều-Khoản | tiêu đề 250 ký tự nhét vào câu hỏi là **rò rỉ từ khoá** (trùng nguyên văn chunk đích ⇒ BM25 trúng ngay); tiêu đề hỏng do parse thì làm lộ cả số hiệu — đúng thứ dạng `situation` phải giấu |
| nội dung 300–2500 ký tự | đủ để hỏi, đủ ngắn để chấm |

Bẫy (`distractor_ids`): Điều khác **cùng văn bản** + cùng số Điều ở **văn bản khác cùng
lĩnh vực**. Bẫy cross-norm tính riêng cho từng item đã chọn — nhét vào `SELECT` thì nó
quét toàn đồ thị cho mỗi ứng viên và query treo.

### Kết quả G7 (2026-08-06)

```
90 item -> out/g7.jsonl          C1 pass            90/90
situation 54/90 = 60%            C2 pass         54/54 situation
(mục tiêu ≥50%)                  lộ số hiệu           0/54
69 văn bản riêng biệt            distractor  3,74 câu/item
```

Paraphrase: 54 lời gọi, `deepseek-v4-flash`, 0 lỗi API.

Ví dụ trước → sau:

> `Hiện nay bồ trí công tác sau miền nhiệm, cách chức Châp hành viên được quy định ra sao?`
> → `Hiện nay việc bố trí công tác sau khi miễn nhiệm, cách chức Chấp hành viên được quy định như thế nào?`

Chú ý: LLM **tự sửa lỗi OCR** trong tiêu đề nguồn ("bồ trí"→"bố trí", "miền nhiệm"→
"miễn nhiệm"). Câu hỏi tự nhiên hơn, nhưng hệ quả là nó **không còn khớp mặt chữ** với
chunk đích vốn vẫn giữ lỗi OCR. Với eval retrieval đây là điều tốt — buộc phải khớp
ngữ nghĩa chứ không ăn may bằng trùng chuỗi — nhưng cần biết là nó có xảy ra.

## G2′ — câu hỏi "tại một thời điểm" (80 câu)

```bash
python -m generator.run_g2 --n 80 --pool 8000 --paraphrase all --out out/g2.jsonl
```

Định nghĩa gốc của G2 có **0 ứng viên** (§10.3b) nên nhóm này dựng trên khoảng hiệu
lực đóng. Mô hình đã đo: `133.151/148.173 (90%)` Expression của văn bản bị thay có
`hieu_luc_den` **đúng bằng** `ngay_hieu_luc` của văn bản thay thế. 10% lệch bị loại ở
`WHERE` — mốc chuyển giao không rõ thì không dùng làm đáp án đúng được.

```
tu ─────────── giữa ────── den-7 ──┼── den ──────────>
                │            │     │
          mid_interval  near_boundary│  on_boundary
          đáp án = cũ    đáp án = cũ │  đáp án = MỚI
```

Khoảng là **nửa mở** `[tu, den)`. Hai loại đầu bắt lỗi *"hệ luôn trả bản mới nhất bất
kể hỏi năm nào"*; loại thứ ba bắt lỗi off-by-one ngay tại mốc. Bẫy luôn là **phía sai
thời điểm** của cùng mốc chuyển giao — đúng chủ đề, sai thời gian.

`on_boundary` dùng lại `find_evidence_span()` của G1: bằng chứng "văn bản cũ hết hiệu
lực" nằm ở điều khoản bãi bỏ trong văn bản mới.

### Kết quả G2′ (2026-08-06)

```
80 item -> out/g2.jsonl       C1 pass    80/80      lỗi logic thời gian   0
situation 48/80 = 60%         C2 pass    48/48      lộ số hiệu         0/48
mid 27 · near 27 · on 26      (mỗi loại ≥25%)       paraphrase 48 gọi, 0 lỗi
```

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
