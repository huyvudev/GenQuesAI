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

## Phạm vi số hiệu — vì sao bộ đề sinh lại sẽ khác bản đã freeze

`common.core_so_hieu` trước đây đòi khuôn `số/NĂM-4-CHỮ-SỐ/ký hiệu`, nên **mù 46% kho**:
mọi số hiệu không mang năm ở giữa (`01/CT-TTg`, `76-TC/TCDN`, `113/SL`, công văn
`8032/VPCP-V.III`) đều trả `None` và bị loại ở `bo_vi_so_hieu`.

Đó là lỗi **mù**, không phải lỗi sai: không con số nào bị chấm sai, nhưng bộ đề im lặng
thu hẹp phạm vi rồi báo cáo như thể đã phủ toàn kho. Chatbot yếu ở mảng công văn / văn
bản cũ thì bộ đề không phát hiện được.

Nay uỷ quyền hết cho `framework.so_hieu`. Đo trên mẫu 3.000 văn bản:

```
                              trước    sau
đọc được số hiệu               53%     99%     +1.382 văn bản dùng được
bóc được chủ đề từ tiêu đề     93%     98%     bộ bóc lặp, cắt tới số hiệu cuối cùng
```

**Hệ quả: sinh lại bộ đề sẽ ra bộ câu khác bản đã freeze** — tập ứng viên rộng gấp đôi.
Ba mốc eval đã lưu không so trực tiếp với lần chạy mới được, phải re-baseline.

### Số hiệu dùng lại

`90/CP` ngày 15/12/1995 và `90/CP` ngày 24/11/1993 là **hai văn bản**. Framework không
viết lại số hiệu cho duy nhất — bịa định danh thì câu hỏi trỏ vào văn bản không tồn tại.
Cách xử lý:

| | |
|---|---|
| **G1** đáp án LÀ định danh | loại cả câu — hỏi hay đáp mơ hồ thì câu hỏi vô nghĩa |
| **G4′** đáp án là DANH SÁCH | bỏ phần tử mơ hồ, giữ câu; còn <2 phần tử thì mới bỏ câu |
| nhóm khác | không ảnh hưởng — đáp án là nội dung, không phải định danh |

Đo thật: 6 khoá / 12 văn bản (0,2%) nên loại là đủ. Corpus nào tỷ lệ này cao thì
`framework.cli soi` sẽ báo, và lúc đó mới đáng dựng câu hỏi nêu kèm ngày ban hành.

## Soi bộ đề — xem bộ sinh vừa đẻ ra cái gì

```bash
$PY -m generator.soi_bo_de                      # -> out/soi_bo_de.html
$PY -m generator.soi_bo_de --vao out/g7.jsonl --ra out/g7.html
```

Một trang HTML tự chứa, double-click là mở. Lọc theo nhóm (chọn nhiều được) · dạng
`lookup`/`situation` · mã cảnh báo; tìm trong câu hỏi/đáp án/id; `j`/`k` hoặc phím mũi
tên để đi giữa các câu. Mỗi câu hiện đủ: câu hỏi (kèm bản trước paraphrase), đáp án,
bẫy, gold span với offset và hash, trạng thái năm cổng, điểm C4, JSON thô.

**Đừng lẫn với `run_c5`.** C5 là phiếu cho người có chuyên môn *luật* phán đáp án
đúng/sai để chốt `eval_set_ceiling` — mẫu nhỏ, có phán quyết, xuất CSV. Bộ soi là cho
người làm *kỹ thuật* nhìn toàn bộ, không phán quyết gì.

Cảnh báo tự động — mỗi luật là một lỗi **đã xảy ra thật**, và cố ý bắt những thứ mà
C1–C5 không bắt được vì từng câu vẫn tự nhất quán:

| | |
|---|---|
| `câu trùng` | có câu khác hỏi y hệt — chấm hai lần cùng một thứ |
| `situation lộ số hiệu` | dạng `situation` phải giấu định danh (§5.2) |
| `thiếu gold span` | không có đoạn trích thì `context_recall` không đo được gì |
| `C1 không pass` | lỗi pipeline (§2), phải điều tra chứ không loại câu |
| `C4 leak` | mô hình trả lời đúng khi không có ngữ cảnh ⇒ câu không đo retrieval |
| `bằng chứng yếu` | `evidence_score < 5`: có từ khoá nhưng không phải câu dẫn |
| `không có bẫy` | G1/G2/G7 thiếu distractor ⇒ mất phân biệt `retriever_nham`/`_sot` |
| `chờ review` | G6, điều kiện (3) §4.2 |

Chạy trên bộ đề hiện tại: **46/400 câu có cảnh báo**. Bốn câu `câu trùng` là hai cặp
G8 đã biết (bộ sinh đã sửa, bộ đề chưa sinh lại).

## C4 — kiểm cần thiết

```bash
$PY -m generator.run_c4 out/eval_set.jsonl     # ~350 lời gọi, ghi ngược vào file
```

Hỏi lại từng câu **không kèm ngữ cảnh**; mô hình vẫn trả lời đúng ⇒ câu đó không đo
retrieval ⇒ hạ nhóm (`do_retrieval = false`), **không xoá**. Bỏ qua G6/G8 vì mục tiêu
của hai nhóm đó vốn *là* từ chối.

```
nhóm  kiểm pass leak          đã kiểm 350 | pass 348 | leak 2
G1      50   50    0
G2      80   80    0          mô hình TỪ CHỐI HOÀN TOÀN: 318/350 = 91%
G3      60   60    0          trung vị điểm C4 = 0.0 · p90 = 0.0
G4      40   40    0
G5      30   29    1
G7      90   89    1
```

**Nguyên tắc chấm:** chỉ tính phần mô hình **tự bổ sung** — trừ hết những gì câu hỏi
đã cho sẵn. Định danh chỉ tính khi *không* có trong câu hỏi; nội dung so F1 token sau
khi loại token của câu hỏi khỏi cả hai vế.

Bản grader đầu tiên thiếu chỗ này nên báo 10 leak, trong đó cả 6 ca G5 đều điểm 1.0 —
G5 hỏi `"Theo {số hiệu}, …"` nên số hiệu vốn nằm sẵn trong câu hỏi. Sửa xong còn 2, và
đọc tay thì cả 2 chỉ trùng từ vựng chứ trả lời sai sự thật.

**Giới hạn:** phép đo là từ vựng, không phân biệt "đúng" với "sai nhưng cùng chủ đề".
Ở mức 1% thì đọc tay được; tỷ lệ tăng thì phải thay bằng LLM judge.

## C5 — phiếu review cho người duyệt

```bash
$PY -m generator.run_c5 --n 80                      # dựng out/review_c5.html
# mở file bằng trình duyệt, duyệt xong bấm "Xuất CSV"
$PY -m generator.run_c5 --cham out/c5_ket_qua.csv   # -> eval_set_ceiling
```

C5 **không đo hệ RAG** — nó đo *chính bộ đề*. Đáp án sinh từ đồ thị chỉ đúng so với
đồ thị, không phải so với luật; khâu trích xuất sai thì bộ đề mã hoá đúng lỗi đó rồi
chấm sai một hệ trả lời đúng. Kết quả là `eval_set_ceiling` — **trần trên của mọi chỉ
số ở Mục 6**.

Phiếu là **một trang HTML tự chứa**: không backend, không mạng, mở bằng double-click.
Phán quyết lưu localStorage, xuất CSV khi xong. Mỗi thẻ gồm câu hỏi, đáp án bộ đề coi
là đúng, **link tới văn bản gốc**, đoạn trích dẫn (thu gọn), và ô **"Việc cần kiểm"**
nêu đúng thứ phải đối chiếu cho nhóm đó — người duyệt không phải tự nghĩ ra.

| Nhóm | Việc cần kiểm |
|---|---|
| G1 | `moi` có thật sự *thay thế* `cu`, hay chỉ *sửa đổi, bổ sung*? |
| G2′ | Tại `as_of`, văn bản đang hiệu lực có đúng là văn bản ghi trong đáp án? |
| G3 | Văn bản hướng dẫn còn hiệu lực hay đã hết? |
| G4′ | Danh sách văn bản tác động có **đủ và đúng**? Thiếu hay thừa đều là sai |
| G5 | Điều khoản chuyển tiếp có thật sự quy định như đáp án? |
| G6 | **Điều kiện (3)**: hệ quả pháp lý khác nhau, hay chỉ khác mức độ chi tiết? |
| G7 | Đoạn trích có đúng là nội dung Điều đó, và có trả lời được câu hỏi? |
| G8 | Câu này có **thật sự** không có đáp án trong hệ thống văn bản? |

Mẫu **chia đều các nhóm** (10 câu/nhóm ở cỡ 80) chứ không theo tỷ lệ quota, vì
`eval_set_ceiling` đo **riêng từng nhóm**. Ở cỡ đó một câu sai kéo tỷ lệ xuống 10 điểm
phần trăm — phiếu nói rõ đây là **phép sàng**, nhóm nào ra kết quả sát ngưỡng thì phải
mở rộng mẫu. `--n 160` cho độ phân giải gấp đôi.

**"Không chắc" tính là KHÔNG đạt** khi tổng hợp: trần trên phải là con số bảo thủ.

## Còn lại

| Việc | |
|---|---|
| **Chạy C5** | Phiếu đã sẵn sàng, cần người có chuyên môn ngồi duyệt |
| **G6 duyệt 25 ca** | Nằm trong phiếu C5 |

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
