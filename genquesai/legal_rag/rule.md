# Quy tắc dò quan hệ REPLACES / AMENDS / GUIDED_BY (regex + LLM)

> Tài liệu quy tắc cho module dò quan hệ giữa văn bản pháp luật trong
> `genquesai/legal_rag/`, viết trước khi code để chốt logic. Đúc kết từ thiết kế đã
> chạy thật và có số liệu kiểm chứng trên corpus 66k VB (Chatbot-Law
> `backbone.md §23`, 2026-08-01/03) — không phải suy đoán, là bản ghi lại cơ chế đã
> validate (LLM thắng regex 6/6 test case; audit toàn corpus sau khi áp dụng).

## 0. Trả lời trực tiếp — 2 câu hỏi gốc

> Câu hỏi gốc: *"nếu thay thế sửa đổi... thì bắt quan hệ như nào ví dụ như văn bản
> mới ghi thay thế sửa đổi văn bản cũ, còn quan hệ của luật, nghị định và thông tư
> thì bắt quan hệ như nào?"*

**Câu 1 — "Văn bản mới ghi thay thế/sửa đổi văn bản cũ" → bắt bằng gì?**

Đọc **TIÊU ĐỀ** của văn bản mới — vì luật VN luôn tự ghi kiểu *"Thông tư sửa đổi, bổ
sung một số điều của Thông tư số 12/2016/TT-BTTTT"* hoặc *"Quyết định bãi bỏ Chỉ thị
số 05/2010/CT-BGDĐT"*. Cơ chế: **neo theo ĐỘNG TỪ** trong tiêu đề, không neo theo
"có số hiệu xuất hiện ở đâu đó trong toàn văn":
- Có động từ **sửa đổi/bổ sung/điều chỉnh/thay thế/đình chỉ thi hành** → `AMENDS`.
- Có động từ **bãi bỏ/hủy bỏ** (không có nhóm trên) → `REPLACES`.
- Rồi trích MỌI số hiệu xuất hiện trong chính câu/tiêu đề đó (không phải toàn văn)
  làm đích của cạnh.

Nếu có sẵn metadata `referenceType` từ nguồn (vbpl.vn) thì dùng thẳng, không cần regex.
Với văn bản khó (OCR lỗi số hiệu, câu phức tạp lẫn nhiều động từ) thì cho LLM đọc lại
tiêu đề + đoạn đầu để phân loại chính xác hơn và vá số hiệu hỏng.

**Câu 2 — "Quan hệ Luật/Nghị định/Thông tư" → bắt bằng gì?**

Đọc đoạn **"Căn cứ..."** ở ĐẦU mỗi văn bản (trước "Điều 1") — không phải tiêu đề.
Luật VN bắt buộc liệt kê *"Căn cứ Luật Ban hành văn bản quy phạm pháp luật; Căn cứ
Nghị định số X;..."* ngay từ đầu. Mọi số hiệu xuất hiện trong đoạn đó → `GUIDED_BY`,
chiều cạnh là **con → cha** (Thông tư → Nghị định → Luật, tức văn bản chi tiết hơn
trỏ lên văn bản gốc mà nó dựa vào). Vì đây chỉ mô tả cấu trúc phân cấp (không làm
đổi hiệu lực của ai) nên **tự động duyệt**, không cần người rà — khác hẳn
`AMENDS`/`REPLACES` (luôn phải qua người duyệt vì có thể tự động đóng hiệu lực văn
bản cũ).

**Vì sao phải TÁCH RIÊNG 2 chỗ đọc (tiêu đề vs. đoạn căn cứ)?** Đây là bẫy quan
trọng nhất: nếu quét chung cả toàn văn để tìm "có động từ sửa/thay + có số hiệu ở
gần đó", hệ thống sẽ **nhầm câu "Căn cứ Nghị định X..." (chỉ là trích dẫn nguồn gốc,
không phải hành vi sửa đổi) thành `AMENDS`** — vì đoạn căn cứ cũng chứa số hiệu, và
có thể đứng gần một câu khác trong văn bản có nhắc "sửa đổi". Quy tắc bắt buộc: chỉ
đọc TIÊU ĐỀ cho REPLACES/AMENDS, chỉ đọc ĐOẠN CĂN CỨ cho GUIDED_BY — không trộn lẫn.

## 1. Ba loại cạnh, ba mức rủi ro

| Cạnh | Ý nghĩa | Chiều | Ảnh hưởng hiệu lực? | Duyệt tự động? |
|---|---|---|---|---|
| `REPLACES` | src (VB mới) thay thế tgt (VB cũ) | mới → cũ | **CÓ** — approve xong tự đóng hiệu lực VB cũ (domino) | KHÔNG — luôn `da_duyet=false` |
| `AMENDS` | src sửa đổi/bổ sung tgt | mới → cũ | Không đóng hẳn hiệu lực, chỉ đánh dấu đã sửa | KHÔNG — luôn `da_duyet=false` |
| `GUIDED_BY` | src căn cứ vào / cụ thể hoá tgt | con → cha (Thông tư→Nghị định→Luật) | KHÔNG | CÓ — regex tự `da_duyet=true` (rủi ro thấp) |

**Nguyên tắc bất biến:** cạnh nào có thể làm sai lệch trạng thái hiệu lực
(REPLACES/AMENDS) thì KHÔNG BAO GIỜ tự tin 100%, bất kể nguồn trích (kể cả LLM) —
luôn vào hàng đợi người duyệt trước khi được dùng để đóng hiệu lực.

## 2. Thứ tự ưu tiên nguồn (cao → thấp)

1. **`referenceType` có sẵn trong `doc.json`** (vbpl.vn tự gắn nhãn) — không cần regex/LLM, map thẳng:
   `12→REPLACES · 10→AMENDS · 1,3→GUIDED_BY`. Dùng khi có (VB crawl từ vbpl.vn).
2. **Regex trên TIÊU ĐỀ** (VB không có `referenceType` — nạp tay, crawl nguồn khác) — cho REPLACES/AMENDS.
3. **Regex trên đoạn "Căn cứ..."** (preamble, trước "Điều 1") — cho GUIDED_BY.
4. **LLM** — chỉ chạy cho tập con khó (VB có từ khoá sửa/thay/bãi bỏ ở tiêu đề mà regex
   không chắc, hoặc số hiệu bị lỗi OCR). LLM không thay thế lớp 2/3, mà HỢP NHẤT: giữ
   GUIDED_BY từ regex (recall cao, rủi ro thấp), bỏ AMENDS/REPLACES từ regex thô rồi
   để LLM phân loại lại cho đúng.

## 3. Regex — REPLACES/AMENDS (đọc TIÊU ĐỀ, không đọc toàn văn)

**Số hiệu đích:** regex tổng quát, KHÔNG giới hạn loại văn bản (bắt cả cấp tỉnh
QĐ-UBND/NQ-HĐND mà bản cũ bị mù), chịu khoảng trắng lệch do OCR quanh dấu `/`:

```
\d+\s*/\s*\d{4}\s*/\s*[A-ZĐ0-9]+(?:-[A-ZĐ0-9]+)*
```

**Neo theo ĐỘNG TỪ, không neo theo "có số hiệu xuất hiện đâu đó":**

```
có bất kỳ từ trong nhóm SUA   → loai=SuaDoi,  cạnh=AMENDS
  {"sửa đổi","bổ sung","điều chỉnh","thay thế","dừng thực hiện","đình chỉ thi hành"}
ngược lại, có từ trong nhóm BAIBO → loai=ThayThe, cạnh=REPLACES
  {"bãi bỏ","hủy bỏ","huỷ bỏ"}
```

Ưu tiên nhóm SUA trước — tiêu đề lẫn cả hai động từ ("sửa đổi và bãi bỏ một số điều")
thì coi là AMENDS (sửa từng phần), vì REPLACES kéo theo đóng hẳn hiệu lực nên phải
bảo thủ hơn khi không rõ ràng 100%.

**⚠️ Bẫy đã biết — PHẢI tránh:** regex ngây thơ dò "có từ khoá sửa/thay + có số hiệu
BẤT KỲ ĐÂU trong toàn văn" sẽ **nhầm câu "Căn cứ Nghị định X..." thành AMENDS** (vì
đoạn căn cứ cũng chứa số hiệu, và VB có thể vừa "căn cứ NĐ" vừa "sửa đổi TT khác" ở
chỗ khác). Bắt buộc: (a) chỉ đọc TIÊU ĐỀ cho REPLACES/AMENDS, không đọc toàn văn;
(b) chỉ trích số hiệu nằm TRONG câu có động từ sửa/thay, không phải mọi số hiệu của
văn bản.

**Loại bỏ tự trỏ:** số hiệu trùng với số hiệu của chính văn bản (`own_so_hieu`) phải
bị loại trước khi tạo cạnh.

## 4. Regex — GUIDED_BY (đọc đoạn "Căn cứ...", trước "Điều 1")

```
preamble = text[: vị trí "Điều 1"]   (nếu không tìm thấy "Điều 1" → 3000-3500 ký tự đầu)
mọi số hiệu VB tìm được trong preamble (trừ own_so_hieu, trừ số hiệu đã dùng ở REPLACES/AMENDS)
    → GUIDED_BY, da_duyet=true
```

Đây gần như luôn đúng vì luật VN bắt buộc liệt kê "Căn cứ Luật X; Căn cứ Nghị định
Y;..." ngay đầu văn bản theo đúng thể thức hành chính — rủi ro sai thấp, không ảnh
hưởng hiệu lực ai, nên KHÔNG cần qua người duyệt.

## 5. LLM — chỉ cho tập khó

**Khi nào gọi:** VB có từ khoá sửa/thay/bãi bỏ ở tiêu đề (tập con, không phải toàn
corpus — LLM đắt, tất định rẻ). Trên corpus thật tập này chiếm ~13% (8.608/66k).

**Input:** tiêu đề + đoạn preamble (≤3500 ký tự).

**Output JSON bắt buộc:**
```json
{"refs": [{"target": "24/2023/QH15", "loai": "ThayThe|SuaDoi|CanCu", "confidence": 0.0-1.0}]}
```

**System prompt (nguyên văn đã validate):**
> Bạn bóc QUAN HỆ THAM CHIẾU của một văn bản pháp luật Việt Nam thành JSON:
> `{"refs":[{"target":"số hiệu VB được tham chiếu (vd 24/2023/QH15)","loai":"ThayThe|SuaDoi|CanCu","confidence":0.0-1.0}]}`.
> ThayThe = văn bản này THAY THẾ VB đích; SuaDoi = SỬA ĐỔI/BỔ SUNG; CanCu = CĂN CỨ.
> SỬA số hiệu bị lỗi OCR (vd 'QH1 3' → 'QH13', '24/2023/QH1' → '24/2023/QH13').
> Chỉ lấy VB có SỐ HIỆU rõ. Không có thì `{"refs":[]}`.

**2 việc LLM làm được mà regex không làm được** (đo thật, 6/6 test case LLM thắng):
1. Phân biệt đúng "bãi bỏ" (REPLACES) khỏi "sửa đổi" (AMENDS) khi câu phức tạp/lẫn
   nhiều động từ trong cùng tiêu đề.
2. **Vá lỗi OCR số hiệu** — regex chỉ khớp chuỗi sạch, LLM suy luận ra số đúng từ
   ngữ cảnh (`"QH1 3"` → `"QH13"`).

**Hợp nhất kết quả khi có LLM:** GIỮ nguyên GUIDED_BY từ regex (mục 4), BỎ
AMENDS/REPLACES từ regex thô (mục 3), thay bằng kết quả LLM. Không trùng lặp cạnh
(so theo cặp `(edge, target)` đã có).

## 6. Chính sách confidence / duyệt

| Nguồn | `confidence` mặc định | `da_duyet` |
|---|---|---|
| `referenceType` (vbpl) | không cần field này (nguồn cấu trúc) | REPLACES/AMENDS: false · GUIDED_BY: true |
| Regex text (`text_regex`) | 0.85 (REPLACES/AMENDS) · 0.6 (GUIDED_BY) | REPLACES/AMENDS: false · GUIDED_BY: true |
| LLM (`llm`) | do LLM tự chấm 0.0–1.0 | luôn false (REPLACES/AMENDS/CanCu qua LLM đều chờ duyệt) |
| Tiêu đề tất định đã tinh chỉnh (`title_rule`) | 0.85 | false |

Action luôn ghi `source` (để truy vết cạnh này từ đâu ra: `text_regex`/`llm`/`title_rule`).

## 7. Mô hình dữ liệu (khớp `genquesai/legal_rag/ingestion/reconcile.py` đã có)

```
(a:Action {action_id, loai, confidence, da_duyet, source, enacted_by, ngay_hieu_luc})
(a)-[:ENACTED_BY]->(src:Norm)     # Action này do src ban hành
(a)-[:AFFECTS]->(tgt:Norm)        # Action này tác động tới tgt
(src)-[:REPLACES|AMENDS|GUIDED_BY]->(tgt)   # cạnh trực tiếp — "đường tắt" cho truy vấn/retrieval
```

`action_id` tất định: `f"{src_norm_id}->{target_so_hieu}:{edge}:{source_tag}"` — idempotent,
chạy lại không tạo trùng (MERGE).

## 8. Resume / không xử lý lại

Mỗi Norm đánh dấu đã xử lý bằng 1 flag (`refs_done` cho regex-only, `refs_llm_done`
khi có chạy LLM) để tránh chạy lại tốn kém (đặc biệt LLM). Batch mới chỉ xử lý VB
CHƯA có flag tương ứng.

## 9. Việc cần làm để hiện thực trong `genquesai/legal_rag/`

- [ ] `ingestion/reference_extractor.py` — regex mục 3 + 4, hàm `apply_references` ghi Action+cạnh.
- [ ] `ingestion/title_refs_parser.py` (hoặc gộp vào trên) — regex tiêu đề tinh chỉnh (mục 3, neo động từ).
- [ ] Lớp gọi LLM (tái dùng `agent/llm.py` đã có sẵn) theo prompt mục 5.
- [ ] CLI wiring (`cli.py`) — lệnh chạy dò quan hệ theo lô, có `--llm` bật/tắt giống `legal_rag ingest`.
