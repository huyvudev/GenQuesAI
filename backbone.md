# BACKBONE — GenQuesAI · Đúc kết hệ thống

> Tài liệu tổng kết trạng thái THẬT của dự án **GenQuesAI** (repo này) — pipeline xử lý corpus
> pháp luật Việt Nam + sinh bộ câu hỏi benchmark cho hệ thống RAG. Cập nhật lần cuối: 2026-09-15.
>
> **Không phải hệ chatbot** — chatbot production (LangGraph agent, API, web UI) sống ở repo
> `Chatbot-Law` riêng. GenQuesAI dùng CHUNG Neo4j + Qdrant với Chatbot-Law (cùng 1 nguồn dữ liệu
> — server `221.132.33.149`) nhưng là 2 codebase độc lập, không phụ thuộc runtime lẫn nhau.

---

## 0. Hệ thống là gì

GenQuesAI có 2 việc chính, dùng chung 1 kho dữ liệu (Neo4j đồ thị pháp luật + Qdrant vector):

1. **Xử lý/rà soát corpus** — dò và duyệt quan hệ hiệu lực giữa các văn bản (REPLACES/AMENDS/
   GUIDED_BY: thay thế, sửa đổi, căn cứ), phát hiện + sửa lỗi dữ liệu (phân loại sai, trùng lặp,
   thu hẹp phạm vi corpus).
2. **`qa_gen`** — sinh bộ câu hỏi-đáp benchmark cho RAG luật, tận dụng đúng cấu trúc đồ thị
   (thay vì suy đoán quan hệ bằng cosine similarity trên corpus phẳng như bản gốc `proposed.ipynb`,
   đã bỏ hẳn khỏi repo).

Cả 2 việc đều ưu tiên **rẻ + rule-based khi có thể**, chỉ dùng LLM khi bắt buộc, và luôn có cơ
chế **tự chối/tự thẩm định** để tránh hallucinate thay vì ép LLM đoán bừa khi thiếu bằng chứng.

---

## 1. Cấu trúc repo

Đã dọn gọn 2026-09-14 (xoá toàn bộ script một-lần, backup, tài liệu lịch sử — chỉ giữ code
thuộc luồng chạy chính thức; lịch sử vẫn còn trong git log nếu cần đối chiếu):

```
GenQuesAI/
├── backbone.md                     # tài liệu này
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
│       └── qa_gen/{data,generate,prompts,verify,balance,paraphrase,run}.py   # ★ pipeline sinh câu hỏi
└── tests/
```

`.env` tại `genquesai/legal_rag/.env` trỏ THẲNG server production (`bolt://221.132.33.149:7687`
+ Qdrant `https://qdrant.hrental.name.vn`) — script phải chạy với CWD = `genquesai/legal_rag/`
để pydantic-settings nạp đúng `.env` (nạp theo CWD, không theo vị trí file). Local Neo4j (Docker,
`bolt://localhost:7687`, mật khẩu `123qwe`) được giữ **đồng bộ tuyệt đối** với server — mọi thay
đổi dữ liệu đều áp cho cả 2 bên rồi verify khớp.

Loại `lien_nganh` trong `qa_gen` cần `torch`+`FlagEmbedding` (không có sẵn trong python hệ
thống) — chạy qua venv riêng: `D:/Project/Chatbot-Law/chatbot/.venv/Scripts/python.exe`
(kèm `PYTHONPATH=D:/Project/GenQuesAI` để venv đó thấy được package `genquesai`).

---

## 2. Corpus — quy mô hiện tại + lịch sử xử lý

**Quy mô hiện tại** (2026-09-15, local và server đã đồng bộ khớp tuyệt đối):

| | Số lượng |
|---|---:|
| Norm (văn bản) | **39.113** |
| Component (Điều/Khoản/Điểm...) | 2.475.230 |
| Action (cạnh REPLACES/AMENDS/GUIDED_BY) | 164.968 |
| — đã duyệt (`da_duyet=true`) | 125.710 |
| Qdrant (vector) | 983.801 |
| Loại văn bản còn lại | 11 (chỉ giữ VBQPPL có cấu trúc: Luật, Bộ luật, Nghị định, Thông tư... đã bỏ "Khác"/Chỉ thị/Lệnh/Pháp lệnh) |
| Khoảng năm ban hành | 2000-01-03 → 2026-07-21 |

**Lịch sử xử lý (rút gọn, mốc quan trọng)**:

1. **Rebuild v3 consensus (2026-08-24/25)** — bỏ toàn bộ Action cũ nhiều nguồn không nhất quán,
   sinh lại TOÀN BỘ quan hệ hiệu lực qua **đồng thuận 3 nguồn** (metadata vbpl + regex + LLM),
   mỗi CẠNH tự xét đồng thuận riêng (`ingestion/consensus.py::dong_thuan_per_edge`).
2. **Sửa lỗi phân loại + backfill 284 VB rỗng (2026-08-25 → 09-04)** — nhiều vòng sửa bug
   trích xuất tham chiếu (xem comment chi tiết trong `ingestion/reference_extractor.py` §3.1-3.5).
3. **Rà soát 2 LLM độc lập (DeepSeek + Gemini, 2026-09-07/08, ĐÃ XONG)** — quét 16.384 VB nguồn
   có cạnh ThayThe/SuaDoi/BaiBoToanBo/BaiBoTungPhan, 2 model đọc TOÀN BỘ Điều (không chỉ đoạn
   cuối) độc lập, so sánh phát hiện bất đồng. Kết quả này + nhiều vòng rà tay tiếp theo (script
   một-lần, đã dọn khỏi repo) đưa `da_duyet` từ ~79.697 lên mức cao hơn nhiều trước khi có các
   đợt thu hẹp corpus dưới đây.
4. **Thu hẹp corpus 2 đợt (2026-09-14)** — theo quyết định người dùng, ưu tiên chất lượng dữ
   liệu có cấu trúc hơn số lượng:
   - Xoá 10.363 VB ban hành trước năm 2000 (dù 68,6% vẫn `ConHieuLuc` — đã cảnh báo trước khi
     xoá) → còn 56.005 Norm.
   - Xoá 16.892 VB thuộc 5 loại **Khác/Chỉ thị cấp Bộ/Chỉ thị TTg/Lệnh/Pháp lệnh** (97,9% loại
     "Khác" không có cấu trúc Điều, chỉ 1 khối `ToanVan`) → còn **39.113 Norm**.
   - Cả 2 đợt: backup đầy đủ trước khi xoá (`_backup_*_purge/`, đã gitignore), áp cho cả local
     + server, verify khớp tuyệt đối sau mỗi bước.
5. **Phát hiện lỗ hổng CDI vs đồ thị Action (2026-09-15)** — CDI (nguồn vbpl.vn thật, độc lập)
   đánh dấu 1 Norm `HetHieuLuc` nhưng đồ thị REPLACES/BaiBoToanBo hoàn toàn không giải thích được
   vì sao. Quét toàn corpus: **3.920 Norm** rơi vào tình trạng này (75 là Luật/Bộ luật — nhóm
   quan trọng nhất). Đã chạy backfill "dò ngược" (tìm văn bản thay thế thật qua trích dẫn +
   xác nhận LLM): **554 cạnh mới** được xác nhận và ghi vào graph (nguồn `backfill_reverse_*`),
   giảm nhóm Luật/Bộ luật "không rõ lý do" từ 75 xuống 20; còn ~3.390 văn bản loại khác chưa xử
   lý (không đáng tự động hoá thêm ở quy mô nhỏ lẻ).
6. **Phát hiện lỗ hổng `so_hieu` không duy nhất (2026-09-15)** — Luật và Nghị quyết Quốc hội
   đánh số ĐỘC LẬP theo 2 dãy riêng, nên trùng `so_hieu` giữa 2 loại khác nhau là chuyện BÌNH
   THƯỜNG về mặt lập pháp — nhưng mọi nơi tạo cạnh (`_EDGE_TMPL` trong `reference_extractor.py`,
   `_ghi_canh_moi` trong `consensus.py`) `MATCH` theo `so_hieu` KHÔNG kèm điều kiện loại văn bản,
   nên có thể MERGE nhầm cạnh vào cả 2 đích. Quét thấy **155 Action** hiện đang trỏ >1 đích cùng
   lúc (đa số `CanCu`/GUIDED_BY, rủi ro thấp; có 1 ca `ThayThe` đã duyệt, kiểm tra tay hoá ra vô
   hại vì 2 đích là cùng 1 văn bản bị trùng node). **CHƯA VÁ GỐC** — xem mục 6.

**Bug đã phát hiện + sửa trong `qa_gen/data.py::tim_luat`** (2026-09-15): `CONTAINS` không kèm
kiểm tra tiêu đề có BẮT ĐẦU đúng cụm từ khoá hay không, khiến "Đầu tư"/"Doanh nghiệp" bị nuốt vào
luật khác chủ đề dài hơn tình cờ chứa 2 từ đó (`Luật Quản lý và đầu tư vốn nhà nước tại doanh
nghiệp`). Đã sửa (yêu cầu tiêu đề bắt đầu đúng từ khoá) + nới điều kiện `tinh_trang` (chấp nhận cả
`HetHieuLucMotPhan`, không chỉ `ConHieuLuc` sạch — luật lớn hay bị sửa 1 phần vẫn còn hiệu lực
phần lớn).

---

## 3. `qa_gen` — pipeline sinh câu hỏi benchmark

5 bước (Bước 0→5), chạy qua `qa_gen/run.py`:

```
Neo4j (cấu trúc+quan hệ) ─┐
                          ├─► [0] Hợp nhất dữ liệu ─► [0b] Khớp bộ kịch bản liên ngành CỐ ĐỊNH
Qdrant (nội dung+vector) ─┘         │                          │
                                    └──────────┬───────────────┘
                                               ▼
                                    [1] Lập kế hoạch tỉ lệ ─► [2] Sinh đề (9 loại)
                                                                    │
                              [4] Cân bằng tỉ lệ (TVD) ◄── [3] Chấm đề (2 vòng + quality gate)
                                    │  ▲
                                    │  └── sinh bù nếu thiếu chỉ tiêu (quay lại [2])
                                    ▼
                              [5] Sinh biến thể ngôn ngữ (mô phỏng người dùng không chuyên)
                                    ▼
                              Bộ đề luật hoàn chỉnh (`_out_qa.jsonl`)
```

### 9 loại câu hỏi (`qa_gen/prompts.py` + `generate.py`)

| `type` | Ý tưởng | Nguồn dữ liệu |
|---|---|---|
| `single_hop` | 1 bước, 1 đoạn | Điều bất kỳ còn hiệu lực |
| `structural_multihop` | Multi-hop nội bộ, B trích dẫn thật A | cạnh `CROSS_REF` |
| `validity_change` | Trước/sau khi sửa đổi | REPLACES/AMENDS đã duyệt, đích cấp Điều |
| `adversarial` | Gài bẫy — đổi 1 giá trị cụ thể | Điều còn hiệu lực |
| `validity_trap` | Bẫy nhận biết hết hiệu lực | Điều đã hết hiệu lực, có thay thế |
| `partial_repeal` | Bãi bỏ 1 phần, Điều cha vẫn sống | `BaiBoTungPhan` đã duyệt |
| `cross_norm_guidance` | Multi-hop liên văn bản qua GUIDED_BY | cặp Norm A←B |
| `transitional_provision` | Điều khoản chuyển tiếp | `TransitionRule` đã duyệt, confidence≥0.8 |
| `cross_field_multihop` | Multi-hop LIÊN NGÀNH LUẬT (2 luật độc lập, khác lĩnh vực) | Bộ kịch bản CỐ ĐỊNH, xem dưới |

### `cross_field_multihop` — thiết kế lại hoàn toàn 2026-09-15

Trước đây: LLM tự đề xuất kịch bản mỗi lượt chạy (`P_DE_XUAT_KICH_BAN_LIEN_NGANH`, đã BỎ) — hay
bịa tên luật không khớp corpus thật, yield thấp (~5%), kết quả không ổn định giữa các lần chạy.

**Giờ**: `qa_gen/data.py::KICH_BAN_LIEN_NGANH_CO_DINH` — **156 kịch bản cố định**, sinh có hệ
thống 1 lần bằng cách đưa TOÀN BỘ 231 Luật/Bộ luật còn hiệu lực thật trong corpus cho LLM chọn
CẶP (chỉ được chọn từ danh sách, không bịa số hiệu khác) — đảm bảo khớp 100% (đối lại với cách cũ
chỉ ~50-75%). Chạm **160/231 luật (69%)** — tăng mạnh so với bộ 20 chọn tay ban đầu (19/231, 8%).
`lay_kich_ban_lien_nganh_co_dinh(neo)` tra thẳng `so_hieu` → `norm_id` (không qua LLM lúc chạy
pipeline). Bước 2 (`_gen_lien_nganh`) vẫn giữ nguyên: tìm Điều gần nghĩa nhất bằng bge-m3 trong
từng luật riêng, thử từng cặp tới khi LLM tự xác nhận thật sự liên quan, dừng ở cặp đầu tiên.

### Bước 5 — Biến thể ngôn ngữ (`qa_gen/paraphrase.py`, mới 2026-09-15)

Câu hỏi LLM tự sinh luôn quá "sạch" (đúng thuật ngữ, đúng số Điều) — không phản ánh cách người
dùng thật (dân, doanh nghiệp không chuyên) hỏi. Sau khi câu hỏi đã qua hết Bước 3/4 (đáp án đã
xác minh đúng), sinh thêm field `bien_the_ngon_ngu` (không đổi `question`/`answer` gốc):
- `doi_thuong`: văn phong người dân, không dùng đúng thuật ngữ pháp lý, không nêu số Điều.
- `mo_ho`: cố ý dùng sai/gần đúng 1 thuật ngữ hoặc thiếu 1 chi tiết — không được đổi bản chất
  khiến đáp án gốc sai.

Sinh bằng model chính (DeepSeek), kiểm tra nhẹ bằng model độc lập (`llm_verify`/Groq) — loại biến
thể nào lệch nghĩa. Bật mặc định, tắt được qua tham số CLI thứ 3 = `0`.

### Model kiểm tra chéo (Bước 3)

Dùng model KHÁC model sinh (tránh 1 model tự sinh + tự chấm bài mình): Sinh = DeepSeek
(`deepseek-v4-flash`), Kiểm tra = Groq (`openai/gpt-oss-120b`). Thiếu `VERIFY_LLM_API_KEY` → tự
rơi về dùng lại model sinh.

**Trạng thái lúc viết tài liệu này**: đang chạy 1 lượt sinh 1.000 câu (chạy nền, ~8-9 tiếng) — số
liệu mới nhất xem trực tiếp file `qa_gen/_out_qa.jsonl` sau khi log báo "XONG".

---

## 4. CDI (`cdi/`)

Đồng bộ liên tục trạng thái hiệu lực từ vbpl.vn (độc lập với cơ chế Action-based ở §2) —
`resync.py` đọc `effStatus`/`effTo` từ vbpl rồi ghi thẳng `Norm.tinh_trang`/`eff_to`. Đây là
nguồn **authoritative** cho SỰ KIỆN "còn/hết hiệu lực", nhưng KHÔNG giải thích ĐƯỢC THAY THẾ BỞI
AI — đó là việc của đồ thị Action (§2 mục 5, phát hiện lỗ hổng 2 nguồn lệch pha).

---

## 5. Việc còn tồn đọng

- [ ] **~3.390 văn bản** (không phải Luật) vẫn "hết hiệu lực nhưng không rõ lý do" — có thể mở
      rộng backfill nếu cần, nhưng lợi ích cận biên thấp (chỉ 14,3% tìm được ở đợt đã chạy).
- [ ] **20 Luật/Bộ luật** còn thiếu người thay thế rõ ràng (chuỗi sửa đổi quá dài/phân mảnh) —
      cần cách tiếp cận khác (dò nhiều bước) hoặc rà tay.
- [ ] **Lỗ hổng `so_hieu` không duy nhất CHƯA VÁ GỐC** — `_EDGE_TMPL`/`_ghi_canh_moi` cần thêm
      điều kiện `loai_vb`/`cap_bac` tương thích khi MATCH target theo so_hieu, tránh sinh thêm
      ca ambiguous mới ở các lượt xử lý sau. 155 ca hiện tại chưa dọn (đa số rủi ro thấp).
- [ ] **Rà lại hệ thống ThayThe/BaiBoToanBo quy mô lớn** — mẫu kiểm chứng 160 cạnh (2026-09-15)
      cho thấy ~40% sai phân loại theo khuôn mẫu "gán TOÀN BỘ trong khi thực chỉ TỪNG PHẦN",
      do vùng quét trích xuất (tiêu đề + đoạn cuối) bỏ sót câu bãi bỏ cụ thể nằm giữa thân văn
      bản. Đáng cân nhắc mở rộng vùng quét hoặc thêm rule tự động hạ cấp khi phát hiện mẫu này.
- [ ] **Bước 5 (biến thể ngôn ngữ) chưa test sống** — code đã viết + compile-check, nhưng chưa
      chạy thật (tránh tranh chấp rate-limit Groq với lượt sinh 1.000 câu đang chạy song song).
- [ ] **255 file đã `git rm` (dọn dẹp 2026-09-14) + code sửa hôm nay vẫn ở trạng thái staged/
      chưa commit** — cần xác nhận rồi commit gộp 1 lần.
