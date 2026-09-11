# BACKBONE — GenQuesAI · Đúc kết hệ thống

> Tài liệu tổng kết trạng thái THẬT của dự án **GenQuesAI** (repo này) — pipeline xử lý corpus
> pháp luật Việt Nam + sinh bộ câu hỏi benchmark cho hệ thống RAG. Cập nhật lần cuối: 2026-09-07.
>
> **Không phải hệ chatbot** — chatbot production (LangGraph agent, API, web UI) sống ở repo
> `Chatbot-Law` riêng (xem `Chatbot-Law/backbone.md`). GenQuesAI dùng CHUNG Neo4j + Qdrant với
> Chatbot-Law (cùng 1 nguồn dữ liệu — server `221.132.33.149`) nhưng là 2 codebase độc lập,
> không phụ thuộc runtime lẫn nhau.

---

## 0. Hệ thống là gì

GenQuesAI có 2 việc chính, dùng chung 1 kho dữ liệu (Neo4j đồ thị pháp luật + Qdrant vector):

1. **Xử lý/rà soát corpus** — dò và duyệt quan hệ hiệu lực giữa các văn bản (REPLACES/AMENDS/
   GUIDED_BY: thay thế, sửa đổi, căn cứ), phát hiện + sửa lỗi dữ liệu (phân loại sai, nội dung
   rỗng, trùng lặp).
2. **`qa_gen`** — sinh bộ câu hỏi-đáp benchmark cho RAG luật, tận dụng đúng cấu trúc đồ thị
   (thay vì suy đoán quan hệ bằng cosine similarity trên corpus phẳng như bản gốc `proposed.ipynb`).

Cả 2 việc đều ưu tiên **rẻ + rule-based khi có thể**, chỉ dùng LLM khi bắt buộc, và luôn có cơ
chế **tự chối/tự thẩm định** để tránh hallucinate thay vì ép LLM đoán bừa khi thiếu bằng chứng.

---

## 1. Cấu trúc repo

```
GenQuesAI/
├── backbone.md                     # tài liệu này
├── legal-rag-qa-pipeline-spec.md   # spec THIẾT KẾ gốc của qa_gen (bản brief ban đầu — xem §3)
├── proposed.ipynb                  # notebook GỐC (corpus phẳng, cosine similarity — đã bỏ, chỉ giữ tham khảo)
├── genquesai/
│   ├── cli.py
│   └── legal_rag/
│       ├── config.py               # Settings (pydantic-settings, đọc .env theo CWD)
│       ├── domain/models.py        # Norm/Component/Expression/Action/TransitionRule + derive_tinh_trang
│       ├── graph/{client,ingest,queries,schema}.py
│       ├── retrieval/{qdrant_store,embedder,index}.py   # bge-m3 dense+sparse
│       ├── agent/llm.py            # LLM client OpenAI-compatible đa nhà cung cấp
│       ├── ingestion/{structural_parser,loader,reconcile,reference_extractor,consensus,...}.py
│       ├── cdi/{pipeline,resync,dedup,hashing,ledger,undo,validation,watch,status}.py
│       ├── qa_gen/{data,generate,prompts,verify,balance,run}.py   # ★ pipeline sinh câu hỏi
│       ├── _TIEN_DO_XU_LY.md       # checkpoint SỐNG của đợt xử lý corpus v3 — đọc TRƯỚC khi hỏi tiến độ
│       └── _*.py                   # script sửa bug/đồng bộ 1 lần, không thuộc pipeline chính thức (xem §6)
└── tests/
```

`.env` tại `genquesai/legal_rag/.env` trỏ THẲNG server production (`bolt://221.132.33.149:7687`
+ Qdrant `https://qdrant.hrental.name.vn`) — script phải chạy với CWD = `genquesai/legal_rag/`
để pydantic-settings nạp đúng `.env` (nạp theo CWD, không theo vị trí file).

---

## 2. Corpus & lịch sử xử lý (consensus v3)

**Quy mô hiện tại** (Neo4j + Qdrant, local và server đã đồng bộ khớp tuyệt đối — xem §6):
66.368 Norm · 2.630.398 Component · 197.371 Action (cạnh REPLACES/AMENDS/GUIDED_BY) · 1.184.976
điểm vector Qdrant.

**Lịch sử ngắn gọn** (chi tiết đầy đủ + số liệu từng giai đoạn nằm trong
`genquesai/legal_rag/_TIEN_DO_XU_LY.md` — file checkpoint sống, ĐỌC FILE ĐÓ trước khi hỏi lại
tiến độ, đừng chỉ dựa memory):

1. **Rebuild v3 (per-edge, 2026-08-24/25)** — bỏ toàn bộ Action cũ (pipeline trước, lẫn nhiều
   nguồn `amend_v2`/`title_rule`/... không nhất quán), sinh lại TOÀN BỘ quan hệ hiệu lực cho
   66.368 VB qua **consensus 3 nguồn** (regex + LLM + metadata vbpl), mỗi CẠNH tự xét đồng thuận
   riêng (sửa bug cũ: trước đó 1 quyết định bị broadcast cho cả văn bản).
2. **Rà soát REPLACES nghi vấn (2026-08-25)** — 1.305/9.848 cạnh bị phân loại nhầm ("một số điều"
   nhưng gắn nhãn thay thế toàn bộ) → sửa lại bằng regex thuần, không tốn LLM.
3. **Trích cấp Điều cho AMENDS (2026-08-25)** — 9.063 VB, resolve đích AMENDS xuống đúng cấp
   Điều/Khoản/Điểm thay vì để nguyên cấp văn bản.
4. **Sửa 284 VB "rỗng" (2026-09-04)** — 127 VB do bug `build_local_file_index()` (chọn nhầm thư
   mục quét sau cùng thay vì bản dài nhất khi 1 VB có ở nhiều thư mục nguồn); 157 VB thật sự
   chưa từng crawl được, tải tay từ thuvienphapluat.vn. +2.182 Action mới.
5. **Bug cạnh ThayThe/BaiBoToanBo phân loại sai (2026-09-05, phát hiện tình cờ khi thử nghiệm
   qa_gen)** — cơ chế `_dong_hieu_luc_da_duyet.py` đóng hiệu lực TOÀN BỘ văn bản đích khi có 1
   cạnh REPLACES/BaiBoToanBo trỏ tới, KHÔNG kiểm tra nguồn có đủ thẩm quyền hay không. Xác nhận
   **ảnh hưởng thật tới production** (retrieval Chatbot-Law lọc theo đúng field bị hỏng này) —
   phát hiện quan trọng nhất đợt này. Sửa 397 cạnh qua 2 rule cấu trúc (không cần LLM): nguồn
   cấp bậc thấp hơn đích (253 cạnh) + nguồn là Văn bản hợp nhất/loại "Khác" (144 cạnh, luôn sai
   vì VBHN không phải hành vi lập pháp mới). Còn **~11.722 cạnh "cùng cấp bậc"** rule cấu trúc
   không phân biệt được đúng/sai — đang được rà tiếp bằng 2 LLM độc lập (xem §5).
6. **Đồng bộ local↔server (2026-09-05/06)** — Neo4j (đẩy chênh lệch qua Bolt, không cần dump/
   restore toàn bộ) + Qdrant (copy toàn bộ 1,18 triệu điểm, ~60 phút) — 2 bên khớp tuyệt đối.

---

## 3. `qa_gen` — pipeline sinh câu hỏi benchmark

Kiến trúc theo đúng spec gốc (`legal-rag-qa-pipeline-spec.md`) — 4 bước Bước 0→4, **spec đã
lỗi thời về SỐ LOẠI câu hỏi** (viết khi mới có 4 loại, nay đã 9 — nội dung kiến trúc còn lại
vẫn đúng):

```
Neo4j (cấu trúc+quan hệ) ─┐
                          ├─► [0] Hợp nhất dữ liệu ─► [0b] Đề xuất kịch bản liên ngành (LLM, 1 lần)
Qdrant (nội dung+vector) ─┘         │                          │
                                    └──────────┬───────────────┘
                                               ▼
                                    [1] Lập kế hoạch tỉ lệ ─► [2] Sinh đề (9 loại)
                                                                    │
                              [4] Cân bằng tỉ lệ (TVD) ◄── [3] Chấm đề (2 vòng + quality gate)
                                    │  ▲
                                    │  └── sinh bù nếu thiếu chỉ tiêu (quay lại [2])
                                    ▼
                              Bộ đề luật hoàn chỉnh (`_out_qa.jsonl`)
```

### 9 loại câu hỏi (`qa_gen/prompts.py` + `generate.py`)

| `type` | Ý tưởng | Nguồn dữ liệu |
|---|---|---|
| `single_hop` | 1 bước, 1 đoạn | Điều bất kỳ còn hiệu lực |
| `structural_multihop` | Multi-hop nội bộ, B trích dẫn thật A | cạnh `CROSS_REF` |
| `validity_change` | Trước/sau khi sửa đổi (không phải multihop — báo cáo 2 sự kiện song song, không suy luận kết hợp) | REPLACES/AMENDS đã duyệt, đích cấp Điều |
| `adversarial` | Gài bẫy — đổi 1 giá trị cụ thể | Điều còn hiệu lực |
| `validity_trap` | Bẫy nhận biết hết hiệu lực | Điều đã hết hiệu lực, có thay thế |
| `partial_repeal` | Bãi bỏ 1 phần, Điều cha vẫn sống | `BaiBoTungPhan` đã duyệt |
| `cross_norm_guidance` | Multi-hop liên văn bản qua GUIDED_BY | cặp Norm A←B (B hướng dẫn A) |
| `transitional_provision` | Điều khoản chuyển tiếp | `TransitionRule` đã duyệt, confidence≥0.8 |
| `cross_field_multihop` | **Multi-hop LIÊN NGÀNH LUẬT** (2 luật độc lập khác lĩnh vực, vd Đầu tư+Đất đai) — MỚI 2026-09-05 | Không có cạnh sẵn — LLM tự đề xuất kịch bản (`P_DE_XUAT_KICH_BAN_LIEN_NGANH`, gọi 1 lần), tự khớp tên luật vào Neo4j, rồi embed bối cảnh (bge-m3) tìm Điều liên quan nhất trong từng luật |

**`cross_field_multihop` cần `torch`+`FlagEmbedding`** (không có sẵn trong mọi môi trường) —
`sinh_de()` tự bỏ qua loại này êm nếu thiếu, không lỗi. Bar thẩm định của loại này đã NỚI so
với 2 loại multihop kia: "cần cả 2 để đáp án ĐẦY ĐỦ" thay vì "bắt buộc mới trả lời được" — đo
thực tế: bar chặt khiến loại này gần như không ra được câu nào (0/45).

### Model kiểm tra chéo (Bước 3, 2026-09-06)

Bước 3 (`verify.py`: omission-test, bẫy hiệu lực, answerability) dùng model **KHÁC** với model
sinh (Bước 2), tránh 1 model tự sinh + tự chấm bài mình bỏ sót lỗi hệ thống — đúng tinh thần
"đa nguồn đồng thuận" đã dùng cho phân loại cạnh (§2). Cấu hình qua `config.py`:
- Sinh (Bước 2): `LLM_PROVIDER` — hiện là **DeepSeek** (`deepseek-v4-flash`).
- Kiểm tra (Bước 3): `VERIFY_LLM_PROVIDER` — hiện là **Groq** (`openai/gpt-oss-120b`,
  `llama-3.3-70b-versatile` cũ đã bị Groq deprecate).
- Thiếu `VERIFY_LLM_API_KEY` → tự rơi về dùng lại model sinh, không bắt buộc phải có 2 key.

**Đã test full pipeline 2 lần** (2026-09-06): mẻ 20 câu (19 câu, 682s) và mẻ 150 câu (146 câu,
3.643s) — cả 9 loại hoạt động đúng qua production Neo4j+Qdrant thật. Phát hiện + sửa 1 bug lúc
test: `Embedder` (bge-m3) không thread-safe khi nhiều luồng cùng lazy-load model lần đầu (lỗi
"meta tensor") — sửa bằng cách nạp model 1 lần ở luồng chính trước Bước 2.

**Lỗi chất lượng đã phát hiện + sửa (2026-09-06)**: `P_CAU_TRUC`/`P_HUONG_DAN_LIEN_VB`/
`P_LIEN_NGANH` dùng nhãn nội bộ "Điều A"/"đoạn B" trong hướng dẫn — model đôi khi CHÉP NGUYÊN
nhãn đó vào đáp án thay vì gọi tên văn bản thật (vd "Theo Điều A (4527/2003/QĐ-UB)..."). Đã
thêm dòng cấm rõ ràng trong cả 3 prompt.

---

## 4. CDI (`cdi/`)

Đồng bộ liên tục trạng thái hiệu lực từ vbpl.vn (độc lập với cơ chế Action-based ở §2) —
`resync.py` đọc `effStatus`/`effTo` từ vbpl rồi ghi thẳng `Norm.tinh_trang`/`eff_to`. **Lưu ý
quan trọng**: đây là nguồn ĐỘC LẬP với `n.tinh_trang` do Action suy ra — khi rà bug tại §2 mục
5, 1 phiên CDI resync chạy song song từng ghi đè lại đúng lúc đang sửa 1 Norm (Luật Đất đai
2024) — không phải lỗi lặp lại, chỉ là 2 tiến trình ghi cùng lúc, đã xử lý ổn.

---

## 5. Rà soát cạnh bằng 2 LLM độc lập (đang chạy 24/7, 2026-09-07)

Sau khi rule cấu trúc (§2 mục 5) chỉ bắt được phần "rõ ràng sai", phần còn lại (~11.722 cạnh
cùng cấp bậc) được rà tiếp bằng **2 LLM hoàn toàn độc lập** (không regex/metadata) — so sánh
kết quả để tìm cạnh khả nghi. Script + hạ tầng nằm NGOÀI `qa_gen` (không phải benchmark, là
công cụ audit dữ liệu 1 lần):

- **Vị trí**: `genquesai/legal_rag/_rasoat_2llm_deploy/rasoat_2llm.py` (bản gốc) — đã deploy
  bản chạy thật lên **VPS** `221.132.33.149:/root/rasoat_2llm/` (không chạy trên máy local).
- **Phạm vi**: 53.126 cạnh (`ThayThe`/`SuaDoi`/`BaiBoToanBo`/`BaiBoTungPhan`), gộp theo 16.384
  VB nguồn (1 lượt gọi/model xử lý hết các cạnh của 1 VB cùng lúc).
- **2 model**: DeepSeek (giống model sinh qa_gen) + **Gemini** (`gemini-2.5-flash`, config
  `AUDIT_LLM_*` — tách biệt hoàn toàn với `VERIFY_LLM_*` của qa_gen Bước 3, KHÔNG dùng chung).
- **Giới hạn dữ liệu đã biết**: server KHÔNG có corpus thô (preamble "Căn cứ..." không lưu
  trong Neo4j) — chỉ dùng được tiêu đề + nội dung Điều (ưu tiên Điều có nhắc số hiệu đích, cộng
  2 Điều đầu + 2 Điều cuối — luật lớn thường có "Điều khoản thi hành" sửa luật khác ở CUỐI văn
  bản, không phải đầu). Không rà được GUIDED_BY (ít rủi ro hơn, đã auto-duyệt từ trước).
- **Ràng buộc DeepSeek**: chỉ gọi trong giờ **off-peak** (mọi lúc trừ T2-T6 01:00-04:00 UTC và
  06:00-10:00 UTC = 08:00-11:00 và 13:00-17:00 giờ VN, theo bảng giá DeepSeek từ 16/8/2026) —
  kiểm tra lại TRƯỚC MỖI văn bản (không phải 1 lần lúc khởi động), tự tạm dừng đúng lúc bước
  vào giờ cao điểm, tự chạy tiếp khi hết. Gemini không giới hạn giờ.
- **Triển khai**: `systemd` service `rasoat-2llm.service` trên VPS (`Restart=always`, tự chạy
  lại khi VPS reboot). Checkpoint resumable: `/root/rasoat_2llm/rasoat_2llm_log.jsonl` (1
  dòng/VB, an toàn nếu service restart giữa chừng).
- **Kết quả CHỈ GHI LOG, KHÔNG tự động sửa graph** — đầu ra là danh sách bất đồng để người
  duyệt tay, giống mọi cơ chế "human-in-the-loop" khác của dự án.
- **Trạng thái lúc viết tài liệu này**: đang chạy, tiến độ + số liệu mới nhất xem trực tiếp
  `ssh 221.132.33.149 "tail -f /root/rasoat_2llm/rasoat_2llm_progress.log"` — KHÔNG chép số vào
  đây vì thay đổi liên tục.

---

## 6. Việc còn tồn đọng

- [ ] Chờ đợt rà 2-LLM (§5) chạy xong toàn bộ 16.384 VB → người duyệt tay danh sách bất đồng →
      áp dụng sửa vào graph (giống cách đã làm với 397 cạnh ở §2 mục 5).
- [ ] Loại `cross_field_multihop` mới ở tỷ lệ nhỏ cố định (3%, giống `bai_bo_tung_phan`/
      `chuyen_tiep`) — có thể cần tinh chỉnh thêm khi có nhiều dữ liệu thực tế hơn.
- [ ] Script rà soát/sửa bug (`_sua_253_canh_thay_the_sai.py`, `_sua_them_canh_sai_vbhn_khac.py`,
      `_dong_bo_local_tu_server.py`, `_dong_bo_qdrant_local.py`) đang nằm rời rạc trong
      `genquesai/legal_rag/`, giữ lại làm tham khảo (không phải pipeline chính thức) — có thể
      dọn/gộp lại sau khi mọi việc ổn định.
