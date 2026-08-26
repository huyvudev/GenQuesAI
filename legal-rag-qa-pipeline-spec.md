# Spec: Pipeline sinh đề QA tự động cho văn bản luật (RAG benchmark)

> Tài liệu này tổng hợp lại toàn bộ phần phân tích + thiết kế đã thảo luận, dùng làm brief đưa cho
> Claude Code (hoặc bất kỳ agent coding nào) để hiện thực hoá. Không phải code, mà là spec kiến trúc +
> yêu cầu hành vi + các cạm bẫy cần tránh.

## 1. Bối cảnh

Dự án gốc (`proposed.ipynb`) là một pipeline sinh câu hỏi-đáp (QA) tổng hợp từ một corpus văn bản, dùng
để benchmark một hệ thống RAG. Nó gồm 4 lớp: lập kế hoạch (Layer 1) → sinh câu hỏi (Layer 2) → chấm/lọc
chất lượng (Layer 3) → cân bằng tỉ lệ (Layer 4). Corpus gốc là một bảng chunk **phẳng** (`shared_corpus.parquet`),
không có cấu trúc phân cấp hay quan hệ tường minh giữa các đoạn.

Dữ liệu đầu vào thực tế của người dùng khác về bản chất:

- **Neo4j**: lưu **cấu trúc phân cấp** của văn bản luật — `Văn bản → Chương → Mục → Điều → Khoản → Điểm`
  — và **quan hệ pháp lý tường minh** giữa các node: `THAY_THE`, `SUA_DOI`, `BO_SUNG`, `BAI_BO`, `DINH_CHI`
  (có thể áp dụng cho cả văn bản hoặc chỉ một số điều/khoản cụ thể).
- **Qdrant**: lưu **nội dung** (text + vector embedding) của từng node trong Neo4j.

=> Mục tiêu: thiết kế lại pipeline để **tận dụng graph pháp lý thật** thay vì tự suy đoán quan hệ bằng
cosine similarity như bản gốc, đồng thời xử lý đúng vấn đề đặc thù của luật: **hiệu lực theo thời gian**.

## 2. Bài học từ notebook gốc — những gì PHẢI tránh lặp lại

Khi hiện thực hoá, tránh các lỗi/anti-pattern đã phát hiện trong bản gốc:

1. **Đừng hard-code đường dẫn nguồn dữ liệu** gắn với một môi trường cụ thể (bản gốc hard-code path
   Kaggle của một user cụ thể dù markdown nói là "auto-discover"). Dùng biến môi trường / config file.
2. **Đừng reseed RNG bằng một giá trị cố định ở mỗi lần gọi hàm sinh mẫu**, đặc biệt trong vòng lặp
   "sinh bù" (top-up) của Layer 4 — bản gốc tạo `random.Random(SEED + offset_cố_định)` mới mỗi lần gọi
   `layer2_generate()`/`allocate_multihop_pairs()`, kể cả khi gọi lại để bù dữ liệu thiếu. Hệ quả: rủi ro
   sinh trùng câu hỏi giữa lượt đầu và lượt bù. **Cách đúng**: seed nên incorporate một counter/iteration
   index tăng dần (hoặc dùng RNG instance dùng chung, không tạo mới), và nên có bước dedup (theo
   node_id cặp + question text) trước khi merge kết quả.
3. **Đừng để một cấu hình mặc định âm thầm gây tốn kém** — bản gốc mặc định chạy toàn bộ 4 biến thể
   ablation (~4x ngân sách LLM) chỉ vì `RUN_ABLATION_BATCH = '1'`. Mọi hành vi tốn tài nguyên (gọi LLM
   hàng loạt, batch job) phải yêu cầu bật rõ ràng, không mặc định bật.
4. **Đừng tính toán một giá trị rồi âm thầm không dùng nó** (bản gốc tính `best_delta` qua hiệu chỉnh
   nhưng không gán vào kết quả, luôn báo `NaN`, gây hiểu lầm giữa tài liệu và hành vi thật). Mọi số liệu
   được tính và ghi vào artefact/report phải phản ánh đúng giá trị thực sự được dùng để quyết định.
5. **Xoá code chết** trước khi bàn giao (bản gốc có hàm không còn được gọi ở đâu).
6. Ablation/flag nào tắt một cơ chế thì tên flag phải khớp đúng cơ chế bị tắt — tránh trường hợp tên
   ablation ngụ ý tắt A nhưng thực chất code đã tắt A' (một cơ chế khác đã thay thế A) từ trước.

## 3. Kiến trúc tổng quan — 5 bước

```
Neo4j (cấu trúc + quan hệ) ─┐
                             ├─► [0] Hợp nhất dữ liệu ─► [1] Lập kế hoạch ─► [2] Ra đề (4 loại)
Qdrant (nội dung) ──────────┘                                                      │
                                                                                     ▼
                              [4] Cân bằng tỉ lệ  ◄──────────────────────  [3] Chấm đề (2 vòng)
                                     │  ▲
                                     │  └── sinh bù nếu thiếu chỉ tiêu (quay lại bước [2])
                                     ▼
                              Bộ đề luật hoàn chỉnh
```

Giữ nguyên gần như 100% so với bản gốc: khung 4 lớp, cơ chế "sinh bù" của Layer 4, cơ chế câu hỏi gài
bẫy (adversarial) ở Layer 2. Thay đổi cốt lõi: nguồn quan hệ dùng cho Layer 1–2 (Neo4j thay vì suy đoán
cosine), và thêm một vòng chấm mới ở Layer 3 (kiểm tra hiệu lực).

## 4. Chi tiết từng bước

### Bước 0 — Hợp nhất dữ liệu (mới, thay cho việc đọc `shared_corpus.parquet`)

**Input**: Neo4j (graph), Qdrant (nội dung + vector).
**Output**: một bảng/collection "chunk giàu ngữ cảnh", mỗi bản ghi gồm:

```yaml
node_id: string           # khớp giữa Neo4j và Qdrant
text: string               # nội dung thật, lấy từ Qdrant
level: enum                # van_ban | chuong | muc | dieu | khoan | diem
parent_path: string[]      # breadcrumb, vd ["Nghị định 100/2019", "Chương II", "Điều 5", "Khoản 2"]
doc_id: string              # văn bản gốc chứa node này
status: enum                # con_hieu_luc | da_sua_doi | da_thay_the | da_bai_bo | dinh_chi
relations:                  # danh sách cạnh pháp lý liên quan tới node này
  - type: enum               # THAY_THE | SUA_DOI | BO_SUNG | BAI_BO | DINH_CHI
    direction: enum          # outgoing (node này tác động node khác) | incoming (bị tác động)
    target_node_id: string
    effective_date: date?    # nếu Neo4j có lưu
```

Cách lấy `status`: suy ra từ các cạnh `incoming` — nếu có cạnh `BAI_BO`/`THAY_THE` trỏ vào node và còn
hiệu lực tại thời điểm build, đánh dấu node là hết hiệu lực; nếu có `SUA_DOI`/`BO_SUNG` thì đánh dấu
"đã sửa đổi" nhưng vẫn có thể còn hiệu lực (tuỳ nội dung sửa).

### Bước 1 — Lập kế hoạch

Thay thế hoàn toàn cơ chế `build_graph()` (kNN cosine) + Louvain của bản gốc. Thay bằng truy vấn trực
tiếp trên Neo4j để tính các thống kê quyết định tỉ lệ 4 loại câu hỏi:

- `relation_density` = số cạnh quan hệ pháp lý / tổng số node — văn bản biến động nhiều → tăng tỉ lệ
  câu hỏi "thay đổi hiệu lực".
- `active_ratio` = tỉ lệ node có `status = con_hieu_luc` / tổng số node.
- `cross_ref_density` = mật độ tham chiếu chéo nội bộ văn bản (nếu đã bóc tách được, xem mục 4.2) —
  quyết định tỉ lệ câu hỏi "nhiều bước — cấu trúc".

Output: bộ tỉ lệ 4 loại (`ratio_single`, `ratio_structural`, `ratio_validity`, `ratio_adversarial`),
tổng = 1. Nên giữ nguyên cơ chế công thức "bậc thang tuyến tính" như bản gốc (dễ giải thích, dễ calibrate)
nhưng thay biến đầu vào từ avg-degree/entity-density sang 3 chỉ số trên.

### Bước 2 — Sinh đề (4 loại)

| Loại | Nguồn cặp/chunk | Ghi chú prompt |
|---|---|---|
| **Một bước** | 1 node bất kỳ (ưu tiên `con_hieu_luc`) | Đưa `parent_path` vào prompt làm ngữ cảnh; giữ constraint "paraphrase, không Yes/No" như bản gốc (`P_SINGLE`). |
| **Nhiều bước — cấu trúc** | 2 node có tham chiếu chéo thật trong cùng văn bản (không phải suy đoán cosine) | Nếu Neo4j chưa có cạnh tham chiếu nội bộ, cần thêm bước trích xuất (regex "theo Điều X", "quy định tại Khoản Y") trước khi build pipeline này. |
| **Thay đổi hiệu lực** (loại mới) | Cặp node nối bởi cạnh `THAY_THE`/`SUA_DOI`/`BO_SUNG`/`BAI_BO` | Prompt phải khác `P_MULTI` gốc: nói rõ đây là quan hệ trước/sau sửa đổi, bắt AI nêu **cả giá trị cũ lẫn giá trị mới** trong đáp án, không chỉ một chiều. |
| **Gài bẫy** | 1 node bất kỳ | Giữ gần như nguyên cơ chế `P_ADV` + `adversarial_rule_check_v3` (Levenshtein) + `llm_nli_bidirectional` của bản gốc — áp lên số liệu (mức phạt/thời hạn/tỷ lệ %) trong điều luật. |

Với 2 loại nhiều-bước, output mỗi câu hỏi nên có field `bridge_relation` ghi rõ loại quan hệ dùng làm
cầu nối (structural_ref / THAY_THE / SUA_DOI / ...) để Layer 3 và việc audit sau này dễ theo dõi.

### Bước 3 — Chấm đề (2 vòng)

**Vòng 1 — đủ ngữ cảnh (giữ nguyên cơ chế bản gốc)**: LLM-omission-test — hỏi AI "câu hỏi này có trả
lời được chỉ với 1 trong 2 đoạn không". Nếu có → loại (tương đương `llm_omission_one()` trong notebook
gốc). Áp cho cả 2 loại nhiều-bước. Với loại "thay đổi hiệu lực", tiêu chí "đủ ngữ cảnh" nghĩa là câu hỏi
phải cần cả giá trị cũ lẫn mới — nếu câu hỏi chỉ hỏi giá trị hiện hành thì thực chất là câu một-bước
trá hình, nên loại hoặc chuyển loại.

**Vòng 2 — còn hiệu lực (mới)**: đối chiếu lại `status` trên Neo4j tại thời điểm sinh đề.
- Với câu một-bước / nhiều-bước-cấu-trúc: nếu node nguồn có `status != con_hieu_luc` mà câu hỏi không
  nêu rõ đây là quy định cũ → loại.
- Với câu thay-đổi-hiệu-lực: kiểm tra đáp án có đề cập đúng cả hai chiều (giá trị trước và sau) không —
  nếu chỉ có một chiều → loại hoặc yêu cầu sinh lại.

Sau vòng 2 vẫn nên chạy thêm bước "quality gate" answerability giống LEVER 1 của bản gốc (chấm điểm
1–5 mức độ trả lời được, loại nếu điểm ≤ 2 — trừ câu gài bẫy vì đáp án của nó cố tình sai).

### Bước 4 — Cân bằng tỉ lệ

Giữ nguyên cơ chế TVD balancer (`tvd()`, `balance()`) của bản gốc, chỉ mở rộng từ so 3 tỉ lệ (single/multi/adv)
sang so 4 tỉ lệ. Khi lệch, sinh bù riêng cho loại đang thiếu, quay lại Bước 2 rồi qua lại Bước 3. Giới
hạn số vòng lặp (giữ `MAX_BALANCE_ITER` kiểu bản gốc) để tránh vòng lặp vô hạn khi corpus không đủ dữ
liệu cho một loại nào đó (ví dụ văn bản không có đủ cặp quan hệ sửa đổi để đạt chỉ tiêu loại "thay đổi
hiệu lực" — trường hợp này nên hạ chỉ tiêu và log rõ, không cố ép).

## 5. Schema đầu ra cuối cùng

```yaml
question: string
answer: string
contexts: string[]              # 1 hoặc 2 đoạn, đã bao gồm breadcrumb
type: enum                      # single | structural_multihop | validity_change | adversarial
source_node_ids: string[]
bridge_relation: string?        # chỉ có với 2 loại nhiều-bước
validity_status_at_generation: object   # snapshot trạng thái hiệu lực từng node nguồn tại lúc sinh
generated_at: datetime
```

Trường `validity_status_at_generation` quan trọng vì luật thay đổi theo thời gian — bộ đề cần tự mô tả
rõ nó đúng với phiên bản luật nào tại thời điểm tạo, để không bị "lỗi thời âm thầm" khi luật cập nhật
sau này.

## 6. Việc cần làm khi hiện thực hoá (gợi ý cho Claude Code)

1. Viết module kết nối + truy vấn Neo4j (Cypher) và Qdrant, output ra bảng hợp nhất ở Bước 0.
2. Viết các truy vấn thống kê cho Bước 1 (relation_density, active_ratio, cross_ref_density).
3. Viết 4 prompt sinh câu hỏi (tái dùng cấu trúc `P_SINGLE`/`P_MULTI`/`P_ADV` của bản gốc làm khung,
   thêm prompt mới cho loại "thay đổi hiệu lực").
4. Viết 2 vòng chấm ở Bước 3, tái dùng cơ chế omission-test bản gốc cho vòng 1, viết mới vòng 2 (đối
   chiếu `status`).
5. Viết lại TVD balancer cho 4 loại, đặc biệt chú ý fix lỗi RNG reseed đã nêu ở mục 2.
6. Viết bước dedup cuối cùng (theo cặp node_id + question) trước khi xuất file kết quả — phòng ngừa
   trùng lặp từ các vòng sinh bù.
7. Log rõ mọi trường hợp "hạ chỉ tiêu vì thiếu dữ liệu" (không âm thầm bỏ qua).
