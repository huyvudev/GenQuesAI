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

## 0.1 Cập nhật luồng (v3) — ĐỒNG THUẬN ĐA NGUỒN, không phải chuỗi verify 1 chiều

> Lịch sử: v1 (mục 2/5 gốc) — LLM chỉ chạy cho ~13% VB, không đối chiếu gì. v2 (bản
> nháp giữa chừng, xem lịch sử git) — coi LLM là lớp "xác minh phụ" chạy SAU nguồn
> chính (metadata/regex), chỉ đổi kết quả khi lệch. **v3 (chốt theo làm rõ của
> người dùng 2026-08-21) — ĐỒNG THUẬN ĐA NGUỒN:** mọi nguồn khả dụng (metadata nếu
> có + regex nếu match + LLM LUÔN chạy) đứng NGANG HÀNG, so khớp lẫn nhau; duyệt tự
> động CHỈ khi TẤT CẢ nguồn khả dụng đồng ý — không có nguồn nào "chính" áp đặt lên
> nguồn khác nữa (khác hẳn v2).

```
Với mỗi VB:
  metadata = referenceType trong doc.json (rỗng nếu không có)
  regex    = quy tắc mục 3 (REPLACES/AMENDS, tiêu đề) + mục 4 (GUIDED_BY, đoạn căn cứ)
  llm      = LUÔN LUÔN chạy (mục 5) — không còn là lớp tuỳ chọn

  CÓ metadata (dù regex có match hay không):
    So 3 nguồn: metadata vs regex (nếu có) vs llm
    → CẢ 3 (hoặc metadata+llm nếu regex rỗng) cho CÙNG kết quả → da_duyet=TRUE (tự động duyệt)
    → có BẤT KỲ nguồn nào lệch → da_duyet=FALSE + cờ mismatch → đưa NGƯỜI DÙNG rà soát

  KHÔNG metadata, CÓ regex:
    So 2 nguồn: regex vs llm
    → khớp → da_duyet=TRUE
    → lệch → da_duyet=FALSE + cờ mismatch → đưa người dùng rà soát

  KHÔNG metadata, KHÔNG regex (biện pháp cuối):
    Chỉ có LLM (đọc TOÀN VĂN, mục 5.2) — không có gì đối chiếu → da_duyet=FALSE (1
    nguồn duy nhất không đủ tự tin để tự duyệt), gắn cờ "chỉ 1 nguồn (LLM), chưa đối
    chiếu được" để người rà soát biết đây là ca cần chú ý hơn ca có ≥2 nguồn lệch nhau.
```

**⚠️ THAY ĐỔI CHÍNH SÁCH có chủ đích (không phải quên):** v1/v2 gắn duyệt-tự-động
theo LOẠI CẠNH (GUIDED_BY tự duyệt vì rủi ro thấp; REPLACES/AMENDS luôn cần người vì
domino hiệu lực). **v3 bỏ quy tắc theo loại cạnh, thay bằng đồng thuận đa nguồn cho
MỌI loại cạnh như nhau** — kể cả REPLACES/AMENDS sẽ tự động duyệt nếu ≥2-3 nguồn khớp
nhau (không còn "luôn luôn false" bất chấp đồng thuận). Đây là lựa chọn của người
dùng (xác nhận 2026-08-21), không phải sơ suất bỏ mất domino-safety.

**Va chạm với `reconcile.py` đã có (quan trọng):** `reconcile_corpus` (chạy trong
`legal_rag ingest`) đã tự tạo Action từ metadata với chính sách RIÊNG của nó
(`conf=0.9→duyet=true` cho REPLACES/AMENDS, `conf=0.6→duyet=false` cho GUIDED_BY —
xem code thật ở mục 6.1). Lệnh `refs` (v3) chạy SAU `ingest`, **không tạo Action mới
cho nhánh có metadata** mà ĐỌC LẠI Action đã có (nhận diện qua field `source IS
NULL` — dấu hiệu Action đó do `reconcile.py` tạo, không phải `reference_extractor.py`),
chạy thêm regex + LLM, rồi **GHI ĐÈ `da_duyet`** theo kết quả đồng thuận 3 nguồn (ghi
đè quyết định ban đầu của `reconcile.py`, vì đó chỉ dựa trên 1 nguồn — metadata —
chưa đối chiếu).

**⚠️ Đánh đổi chi phí (đã cảnh báo, người dùng xác nhận chấp nhận 2026-08-21):** LLM
giờ chạy trên GẦN NHƯ TOÀN BỘ 66k VB (luôn chạy, không phải tập con ~13% như v1).
Ghi chú cũ trong `backbone.md §23`: Groq free tier TPD 100k token/ngày → ~50 VB/ngày
→ cả corpus ~1.360 ngày nếu chạy 1 luồng — **cần tính lại phương án quota/song
song/batch** khi hiện thực (Groq trả phí, provider khác, hoặc dùng Claude Code xử lý
base data như lần trước). Không chặn việc ghi rule, nhưng PHẢI giải quyết trước khi
chạy full corpus.

## 1. Ba loại cạnh

| Cạnh | Ý nghĩa | Chiều | Ảnh hưởng hiệu lực? |
|---|---|---|---|
| `REPLACES` | src (VB mới) thay thế tgt (VB cũ) | mới → cũ | **CÓ** — duyệt xong tự đóng hiệu lực VB cũ (domino, `close_replaced`) |
| `AMENDS` | src sửa đổi/bổ sung tgt | mới → cũ | Không đóng hẳn hiệu lực, chỉ đánh dấu đã sửa |
| `GUIDED_BY` | src căn cứ vào / cụ thể hoá tgt | con → cha (Thông tư→Nghị định→Luật) | KHÔNG |

**v3 — duyệt (`da_duyet`) KHÔNG còn cố định theo loại cạnh** (khác v1/v2, xem mục
0.1) — quyết định bởi ĐỒNG THUẬN ĐA NGUỒN (mục 2), áp dụng như nhau cho cả 3 loại.
`REPLACES` vẫn là loại có hệ quả nặng nhất khi duyệt (domino đóng hiệu lực) nên khi
mismatch, đây là loại đáng ưu tiên rà nhất trong hàng đợi người dùng.

## 2. Đồng thuận đa nguồn (v3) — không có nguồn nào "ưu tiên cao hơn" áp đặt lên nguồn khác

Ba nguồn, LUÔN thử cả ba (không phải chuỗi fallback dừng sớm):

1. **Metadata** — `referenceType` trong `doc.json` (map thẳng `12→REPLACES·10→AMENDS·1,3→GUIDED_BY`).
   Rỗng nếu VB không có (nạp tay, crawl nguồn khác).
2. **Regex** — tiêu đề (mục 3, REPLACES/AMENDS) + đoạn "Căn cứ..." (mục 4, GUIDED_BY).
   Rỗng nếu không khớp mẫu nào.
3. **LLM** — LUÔN chạy (mục 5), không còn là lớp tuỳ chọn cho tập con như v1.

**Quy tắc duyệt theo SỐ NGUỒN KHẢ DỤNG đồng ý** (chi tiết máy trạng thái: mục 0.1):

| Nguồn khả dụng | Khớp nhau? | `da_duyet` |
|---|---|---|
| Metadata + Regex + LLM (cả 3) | Khớp hết | `true` |
| Metadata + Regex + LLM (cả 3) | ≥1 lệch | `false` + cờ mismatch → người rà |
| Metadata + LLM (regex rỗng) | Khớp | `true` |
| Metadata + LLM (regex rỗng) | Lệch | `false` + cờ mismatch |
| Regex + LLM (không metadata) | Khớp | `true` |
| Regex + LLM (không metadata) | Lệch | `false` + cờ mismatch |
| Chỉ LLM (không metadata, không regex) | — (không có gì đối chiếu) | `false` + cờ "1 nguồn duy nhất" |

**Vì sao LLM luôn chạy dù đã có metadata:** không phải để thay thế metadata, mà để
làm nguồn ĐỘC LẬP THỨ 3 cho phép phát hiện ca metadata SAI (vbpl.vn không phải lúc
nào cũng gắn `referenceType` đúng — xem mục 5.3 điểm 3) — nếu chỉ so metadata với
regex mà bỏ LLM thì mất khả năng bắt lỗi khi CẢ metadata LẪN regex cùng sai giống
nhau (khó xảy ra nhưng không phải zero, vd cả hai đều bị đánh lừa bởi cùng 1 kiểu
OCR lỗi).

## 3. Regex — REPLACES/AMENDS (đọc TIÊU ĐỀ, không đọc toàn văn)

**Số hiệu đích:** regex tổng quát, KHÔNG giới hạn loại văn bản (bắt cả cấp tỉnh
QĐ-UBND/NQ-HĐND mà bản cũ bị mù), chịu khoảng trắng lệch do OCR quanh dấu `/`:

```
\d+\s*/\s*\d{4}\s*/\s*[A-ZĐ0-9]+(?:-[A-ZĐ0-9]+)*
```

**Neo theo ĐỘNG TỪ, không neo theo "có số hiệu xuất hiện đâu đó":**

```
có bất kỳ từ trong nhóm SUA   → loai=SuaDoi,  cạnh=AMENDS
  {"sửa đổi","bổ sung","điều chỉnh","dừng thực hiện","đình chỉ thi hành"}
ngược lại, có từ trong nhóm BAIBO → loai=ThayThe, cạnh=REPLACES
  {"bãi bỏ","hủy bỏ","huỷ bỏ"}
ngược lại, có "thay thế" (xét ngữ cảnh — mục 3.2)
```

Ưu tiên nhóm SUA trước — tiêu đề lẫn cả hai động từ ("sửa đổi và bãi bỏ một số điều")
thì coi là AMENDS (sửa từng phần), vì REPLACES kéo theo đóng hẳn hiệu lực nên phải
bảo thủ hơn khi không rõ ràng 100%.

**⚠️ Bẫy đã biết — PHẢI tránh:** regex ngây thơ dò "có từ khoá sửa/thay + có số hiệu
BẤT KỲ ĐÂU trong toàn văn" sẽ **nhầm câu "Căn cứ Nghị định X..." thành AMENDS** (vì
đoạn căn cứ cũng chứa số hiệu, và VB có thể vừa "căn cứ NĐ" vừa "sửa đổi TT khác" ở
chỗ khác). Bắt buộc: (a) chỉ đọc TIÊU ĐỀ (+ đoạn "Hiệu lực thi hành" — mục 3.1) cho
REPLACES/AMENDS, không đọc cả toàn văn; (b) chỉ trích số hiệu nằm TRONG CÙNG CÂU với
động từ sửa/thay (không phải "cùng đoạn" — mục 3.1 có bẫy thứ 2, xử lý theo câu).

**Loại bỏ tự trỏ:** số hiệu trùng với số hiệu của chính văn bản (`own_so_hieu`) phải
bị loại trước khi tạo cạnh.

### 3.1 Đoạn "Hiệu lực thi hành" CUỐI văn bản — nguồn thứ 2 cho REPLACES/AMENDS

**Phát hiện 2026-08-22 (đo trên corpus thật, ca `58/2015/TTLT-BCT-BKHCN`):** câu
tuyên bố thay thế/sửa đổi rất hay nằm ở **điều khoản CUỐI CÙNG** ("Điều X. Hiệu lực
thi hành") — KHÔNG ở tiêu đề. Ca thật: tiêu đề chỉ ghi "...Quy định về quản lý chất
lượng thép..." (không nhắc gì), nhưng ở vị trí 35.105/36.228 ký tự (gần cuối) có:
> *"Thông tư này có hiệu lực thi hành kể từ ngày 21/3/2016 và **thay thế** Thông tư
> liên tịch số 44/2013/TTLT-BCT-BKHCN..."*

Khớp đúng `referenceType=12` (REPLACES) trong metadata thật — nếu chỉ đọc tiêu đề sẽ
**bỏ sót 100%** loại cạnh này khi nó không được nhắc ở tiêu đề.

**Quy tắc:** tìm vị trí CUỐI CÙNG (`rfind`, không phải `find`) của cụm "hiệu lực thi
hành" hoặc "điều khoản thi hành" (không phân biệt hoa/thường); nếu không tìm thấy,
lấy 3000 ký tự cuối văn bản làm dự phòng. Áp quy tắc động từ (mục 3) + tách SỐ HIỆU
**theo câu** (không phải cả đoạn — xem bẫy #2 dưới) lên đoạn đó.

**⚠️ Bẫy #2 (khác bẫy #1 ở trên) — PHẢI xử lý THEO TỪNG CÂU:** đoạn "Hiệu lực thi
hành" thường có thêm câu boilerplate rất phổ biến:
> *"Trường hợp văn bản quy phạm pháp luật được viện dẫn trong Thông tư này được sửa
> đổi, bổ sung hoặc thay thế thì thực hiện theo văn bản mới."*

Câu này nói về **CÁC VB KHÁC được trích dẫn Ở NƠI KHÁC trong văn bản** (không có số
hiệu cụ thể ngay trong câu) — nếu quét "có động từ sửa đổi bất kỳ đâu trong ĐOẠN" sẽ
gán nhầm động từ này cho số hiệu ở CÂU KHÁC trong cùng đoạn. Bắt buộc: tách đoạn
thành từng câu (theo `.`/`;`), chỉ tạo cạnh khi ĐỘNG TỪ và SỐ HIỆU cùng nằm trong
MỘT CÂU (hàm `_quan_he_theo_cau`).

### 3.2 "thay thế"/"bãi bỏ" xét ngữ cảnh riêng — REPLACES toàn bộ vs AMENDS từng phần

**Phát hiện đợt 2026-08-22 (2 ca thật):**
- `58/2015/TTLT-BCT-BKHCN`: ban đầu "thay thế" bị xếp chung nhóm SUA (AMENDS) — sai,
  metadata (`referenceType=12`) nói rõ đó là REPLACES.
- `06/2016/TT-BKHCN`: *"bãi bỏ **nội dung** quy định liên quan đến... quy định
  **tại** Quyết định số 32/2007/QĐ-BKHCN"* — ban đầu "bãi bỏ" luôn = REPLACES là sai,
  câu này chỉ bãi bỏ 1 PHẦN NỘI DUNG nằm trong VB khác, không phải toàn bộ VB đó.

Quy tắc đúng, áp dụng CHUNG cho cả "thay thế" và "bãi bỏ/hủy bỏ" (`_phan_loai_dong_tu`):
- Đi kèm cụm chỉ TỪNG PHẦN (`_TUNG_PHAN`: "một số điều/khoản/điểm", "nội dung", "quy
  định liên quan") trong ~60 ký tự sau động từ → **AMENDS** (sửa/bãi 1 phần, giữ
  nguyên phần còn lại của VB đích).
- KHÔNG kèm cụm nào ở trên → **REPLACES** (nhắm thẳng, thay/bãi TOÀN BỘ VB đích).

Bảo thủ trên TOÀN CÂU (không phân biệt "thay thế" hay "bãi bỏ" nào match trước): chỉ
cần **1 lần** bất kỳ động từ nào kèm cụm từng-phần là coi cả câu đó AMENDS.

**Giới hạn đã biết (không phải bug, là mơ hồ ngôn ngữ pháp lý thật):** ca `06/2016`
ở trên — quy tắc tất định cho AMENDS, nhưng LLM (đọc CÙNG đoạn) tự phân loại
REPLACES. Đây là ví dụ ĐÚNG CHỨC NĂNG của thiết kế đồng thuận (mục 0.1/2): khi 2
nguồn độc lập bất đồng về 1 câu mơ hồ thật, hệ thống PHẢI gắn cờ đưa người rà, không
nên cố thêm quy tắc để ép 2 nguồn "khớp" nhân tạo.

### 3.3 HTML → text: dùng `html_to_text` (selectolax), KHÔNG regex thay tag bằng khoảng trắng

**Bug thật 2026-08-22** (VB `113783/most`): HTML gốc tô đậm/nghiêng RIÊNG TỪNG KÝ TỰ
của số hiệu (do OCR/export PDF), vd `"...QH</em><em>1</em><em>3..."`. Cách cũ
(`re.sub(r"<[^>]+>", " ", html)`) thay MỌI tag bằng khoảng trắng → `"QH13"` vỡ thành
`"QH 1 3"` → `SOHIEU_RE` chỉ bắt được `"QH"`, MẤT `"13"` — lỗi âm thầm, không crash,
chỉ lặng lẽ thiếu số hiệu.

**Sửa:** `html_to_text()` dùng `selectolax.parser.HTMLParser(html).text()` — **KHÔNG
truyền `separator`** (mặc định nối liền text-node theo DOM, không tự thêm khoảng
trắng) — giữ đúng `"QH13"` liền mạch. Đã kiểm tra: KHÔNG gây dính chữ giữa các `<p>`
trên dữ liệu thật (HTML nguồn format có xuống dòng thật giữa đoạn, không phải HTML
minify) — nếu đổi nguồn dữ liệu khác (HTML minify, không xuống dòng) thì giả định
này có thể sai, cần kiểm tra lại.

## 4. Regex — GUIDED_BY (đọc đoạn "Căn cứ...", trước "Điều 1")

```
preamble = text[: vị trí "Điều 1"]   (nếu không tìm thấy "Điều 1" → 3000-3500 ký tự đầu)
mọi số hiệu VB tìm được trong preamble (trừ own_so_hieu, trừ số hiệu đã dùng ở REPLACES/AMENDS)
    → GUIDED_BY (ứng viên — duyệt hay không do đồng thuận đa nguồn, mục 2, KHÔNG còn
      tự động `da_duyet=true` như v1)
```

Đây gần như luôn đúng vì luật VN bắt buộc liệt kê "Căn cứ Luật X; Căn cứ Nghị định
Y;..." ngay đầu văn bản theo đúng thể thức hành chính — rủi ro sai thấp (regex ít khi
bắt nhầm ở đoạn này), nhưng ở v3 vẫn phải qua bước so khớp với LLM trước khi quyết
định `da_duyet` (mục 2).

## 5. LLM — luôn chạy, 2 vai trò tuỳ số nguồn khả dụng (v3)

**Input chung — schema JSON không đổi:**
```json
{"refs": [{"target": "24/2023/QH15", "loai": "ThayThe|SuaDoi|CanCu", "confidence": 0.0-1.0}]}
```

**System prompt (bản v2, sửa 2026-08-22 — dùng cho cả 2 vai trò):**
> Bạn bóc TOÀN BỘ quan hệ tham chiếu của một văn bản pháp luật Việt Nam thành JSON:
> `{"refs":[{"target":"số hiệu VB được tham chiếu (vd 24/2023/QH15)","loai":"ThayThe|SuaDoi|CanCu","confidence":0.0-1.0}]}`.
> ThayThe = văn bản này THAY THẾ TOÀN BỘ VB đích; SuaDoi = SỬA ĐỔI/BỔ SUNG (kể cả
> "thay thế MỘT SỐ ĐIỀU/KHOẢN" — vẫn là SuaDoi, không phải ThayThe); CanCu = CĂN CỨ
> (trích dẫn làm cơ sở pháp lý, thường ở đoạn đầu "Căn cứ...").
> BẮT BUỘC liệt kê ĐẦY ĐỦ mọi quan hệ tìm thấy — một văn bản thường có NHIỀU CanCu
> (mỗi dòng "Căn cứ..." là 1 CanCu riêng) CỘNG THÊM tối đa 1 ThayThe/SuaDoi nếu có.
> KHÔNG chỉ chọn 1 quan hệ "quan trọng nhất" rồi bỏ qua các CanCu khác.
> SỬA số hiệu bị lỗi OCR (vd 'QH1 3' → 'QH13', '24/2023/QH1' → '24/2023/QH13').
> Chỉ lấy VB có SỐ HIỆU rõ. Không có thì `{"refs":[]}`.

**⚠️ Bẫy đã gặp thật (2026-08-22, test trên `--consensus --limit 3`):** bản prompt
v1 (chỉ nói "bóc QUAN HỆ THAM CHIẾU", không nói "liệt kê ĐẦY ĐỦ") khiến LLM **bỏ sót
gần hết `CanCu`** — đọc đúng đoạn "Căn cứ..." có 5 dòng nhưng chỉ trả về 1 kết quả
duy nhất (thường là `ThayThe`/`SuaDoi` — LLM tự coi đó là "quan trọng nhất" rồi bỏ
qua phần còn lại). Không phải model yếu — thêm câu "BẮT BUỘC liệt kê ĐẦY ĐỦ... KHÔNG
chỉ chọn 1 quan hệ quan trọng nhất" vào prompt sửa dứt điểm (verify lại: từ 1/6 quan
hệ → đủ 6/6 trên cùng input, cùng model `deepseek-chat`).

### 5.1 Vai trò ĐỒNG THUẬN (khi có metadata và/hoặc regex — 2 hoặc 3 nguồn)

**Input:** tiêu đề + đoạn preamble (≤1800 ký tự) **+ đoạn "Hiệu lực thi hành" cuối
văn bản (≤1500 ký tự)** — sửa 2026-08-22 cùng đợt phát hiện mục 3.1: nếu chỉ cho LLM
xem preamble, LLM sẽ KHÔNG THỂ thấy câu thay thế ở cuối văn bản dù regex đã thấy —
gây mismatch giả tạo (không phải LLM sai, mà không được cho xem). Chia ngân sách ký
tự RÕ RÀNG giữa 2 đoạn (không chỉ nối rồi cắt ở 3500) để đoạn cuối không bị cắt mất
khi preamble đã dài — xem `consensus._preamble_va_dieu_khoan_cuoi`. KHÔNG cần toàn
văn vì mục đích là ĐỘC LẬP đọc lại và cho ý kiến riêng, không phải "sửa" nguồn khác.

**So khớp:** so tập `(loai, target)` của LLM với tập của metadata (nếu có) và/hoặc
regex (nếu có) — xem bảng đầy đủ ở mục 2. Không có "nguồn thắng" — kết quả cuối chỉ
có 2 khả năng: **khớp → duyệt**, **lệch → không duyệt, đưa người rà** (metadata VẪN
được giữ làm giá trị hiển thị mặc định khi lệch, vì đó là dữ liệu gốc từ nguồn chính
thức, nhưng `da_duyet=false` bất kể — người dùng là người quyết định cuối, không phải
thuật toán tự chọn bên nào đúng).

### 5.2 Vai trò TRÍCH XUẤT DUY NHẤT (không metadata, không regex match — biện pháp cuối)

**Input:** TOÀN VĂN bản (không giới hạn ở tiêu đề/preamble — không còn gợi ý cấu
trúc nào để bám, có thể quan hệ nằm ở bất kỳ đâu trong văn bản). Cắt theo giới hạn
token của model (`synth_context_budget_chars`-style — xem `config.py`), ưu tiên giữ
preamble + các đoạn có nhắc số hiệu VB nếu văn bản quá dài để đưa hết.

**Không có gì để đối chiếu** — kết quả LLM là kết quả duy nhất, nhưng vẫn
`da_duyet=false` (1 nguồn không đủ để tự động duyệt theo quy tắc đồng thuận mục 2) —
gắn cờ riêng để người rà biết đây là ca "chỉ có LLM", mức tin thấp hơn ca có nguồn
đối chiếu mà khớp.

### 5.3 Vì sao LLM cần thiết (đo thật, 6/6 test case LLM thắng regex)

1. Phân biệt đúng "bãi bỏ" (REPLACES) khỏi "sửa đổi" (AMENDS) khi câu phức tạp/lẫn
   nhiều động từ trong cùng tiêu đề.
2. **Vá lỗi OCR số hiệu** — regex chỉ khớp chuỗi sạch, LLM suy luận ra số đúng từ
   ngữ cảnh (`"QH1 3"` → `"QH13"`).
3. **Bắt lỗi ở chính metadata** — vbpl.vn không phải lúc nào cũng gắn `referenceType`
   đúng 100%; LLM đọc độc lập là nguồn thứ 3 giúp phát hiện ca metadata VÀ regex cùng
   sai (hiếm nhưng không phải zero — vd cùng bị đánh lừa bởi 1 kiểu lỗi OCR).

## 6. Chính sách confidence / duyệt (v3 — đồng thuận, không theo loại cạnh)

| Tình huống | `confidence` ghi lại | `da_duyet` |
|---|---|---|
| Metadata + Regex + LLM khớp hết | giữ nguyên của từng nguồn (metadata: không field riêng; regex 0.85/0.6; llm tự chấm) | `true` |
| Metadata + LLM khớp (regex rỗng) | như trên | `true` |
| Regex + LLM khớp (không metadata) | như trên | `true` |
| Bất kỳ tổ hợp nào ở trên nhưng LỆCH | như trên, giữ NGUYÊN VĂN cả 2-3 kết quả (không xoá) | `false` + `mismatch=true` |
| Chỉ LLM (không metadata, không regex) | LLM tự chấm | `false` + `only_llm=true` |

**KHÔNG còn "nguyên tắc bất biến theo loại cạnh" ở v3** (mục 1 đã sửa lại) — đây là
đổi chính sách CÓ CHỦ ĐÍCH theo yêu cầu người dùng (2026-08-21): duyệt hay không do
đồng thuận đa nguồn quyết định như nhau cho REPLACES/AMENDS/GUIDED_BY. Điều duy nhất
còn giữ: `REPLACES` là loại có hệ quả nặng nhất khi được duyệt (domino đóng hiệu lực
qua `close_replaced`), nên khi bị `mismatch`, nó nên đứng ĐẦU hàng đợi người rà (ưu
tiên hiển thị, không phải ưu tiên xử lý tự động).

Action luôn ghi `source` (từ đâu ra: `referenceType`/`text_regex`/`llm`) — v3 thêm
`mismatch`/`only_llm` để giữ vết đối chiếu, và giữ NGUYÊN VĂN kết quả của mọi nguồn
tham gia so sánh khi có mâu thuẫn (không xoá thông tin của "bên thua" — không còn
khái niệm bên thua ở v3, tất cả nguồn ngang hàng).

## 7. Mô hình dữ liệu (v3 — field đồng thuận, không còn field "verified/mismatch theo 1 nguồn chính")

```
(a:Action {
  action_id, loai, confidence, da_duyet, source, enacted_by, ngay_hieu_luc,
  nguon_metadata,    # string (JSON) hoặc null — kết quả nhánh metadata nếu có
  nguon_regex,       # string (JSON) hoặc null — kết quả nhánh regex nếu có
  nguon_llm,         # string (JSON) — kết quả LLM (LUÔN có, v3 luôn chạy LLM)
  mismatch,          # bool — có ≥2 nguồn khả dụng nhưng KHÔNG khớp nhau
  only_llm,          # bool — chỉ có LLM (không metadata, không regex) — biện pháp cuối
})
(a)-[:ENACTED_BY]->(src:Norm)     # Action này do src ban hành
(a)-[:AFFECTS]->(tgt:Norm)        # Action này tác động tới tgt
(src)-[:REPLACES|AMENDS|GUIDED_BY]->(tgt)   # cạnh trực tiếp — "đường tắt" cho truy vấn/retrieval
```

Giữ nguyên văn cả 3 nguồn (`nguon_metadata`/`nguon_regex`/`nguon_llm`) thay vì chỉ
"kết quả cuối + 1 field gợi ý phụ" (thiết kế v2 cũ) — vì ở v3 không có nguồn nào
"chính", người rà cần thấy đủ cả 2-3 góc nhìn để tự quyết định khi có mismatch.

`action_id` tất định: `f"{src_norm_id}->{target_so_hieu}:{edge}:{source_tag}"` — idempotent,
chạy lại không tạo trùng (MERGE). Các field `llm_*` không đổi `action_id` (không tạo
Action thứ 2 khi LLM verify — SET thêm field vào Action đã có).

## 8. Resume / không xử lý lại (3 flag — 1 theo mỗi nhánh A/B/C)

| Flag | Ý nghĩa |
|---|---|
| `refs_meta_done` | đã xử lý xong nhánh A (có metadata — đối chiếu metadata+regex?+llm) |
| `refs_regex_done` | đã xử lý xong nhánh B (không metadata, có regex — đối chiếu regex+llm) |
| `refs_llm_done` | đã xử lý xong nhánh C (không metadata, không regex — chỉ llm) |

Mỗi Norm chỉ rơi vào ĐÚNG 1 nhánh theo NGUỒN NÀO KHẢ DỤNG (A nếu có metadata dù regex
có match hay không; B nếu không metadata nhưng regex match; C nếu cả hai đều không)
— việc phân nhánh (A/B/C) chỉ quyết định INPUT nào đưa cho LLM và SO VỚI GÌ, không
quyết định ai thắng ai (đó là đồng thuận, mục 2). Tách riêng tên flag để dễ audit "VB
này qua nhánh nào" khi rà dữ liệu, và resume độc lập theo từng nhánh.

## 9. Việc cần làm để hiện thực trong `genquesai/legal_rag/`

**Đã xong (v1, commit `cd1f545`):**
- [x] `ingestion/reference_extractor.py` — regex mục 3 + 4, hàm `apply_references` ghi Action+cạnh.
- [x] Prompt LLM (mục 5) + `extract_references_llm` — đã viết, tái dùng nguyên cho v3.
- [x] CLI `legal_rag refs [--llm]`.
- [x] Test `tests/test_reference_extractor.py` (6 ca, khoá bẫy đã biết).

**Đã xong (v3, commit sau `485b915`) — `ingestion/consensus.py`:**
- [x] `extract_metadata_relations(data)` — đọc `referenceType`/`targetDocument.docNum`
      trực tiếp từ `doc.json` (đã xác nhận có sẵn trên dữ liệu thật, không cần tra DB
      thêm), tái dùng `REL_MAP` của `reconcile.py` (không viết lại logic map riêng).
- [x] `dong_thuan(metadata, regex, llm)` — hàm thuần, so 2-3 tập `(edge, target)` tuỳ
      nguồn khả dụng, trả `{"nhanh": "A"|"B"|"C", "khop": bool|None, ...}`. Test ở
      `tests/test_consensus.py` (5 ca, gồm cả nhánh C `khop=None` khác `False`).
- [x] `resolve_relations(...)` — orchestrator: xác định nhánh, gọi LLM đúng input
      (preamble cho A/B, toàn văn ≤12.000 ký tự cho C), gọi `dong_thuan`, ghi kết quả.
- [x] **Xử lý va chạm với `reconcile.py`:** nhánh A tìm Action có sẵn qua
      `source IS NULL` (dấu hiệu do `reconcile_corpus` tạo lúc `ingest`) rồi UPDATE
      field đồng thuận + `da_duyet` lên Action đó — KHÔNG tạo Action thứ 2.
- [x] Field `nguon_metadata`/`nguon_regex`/`nguon_llm`/`mismatch`/`only_llm` trên `Action`.
- [x] 3 flag resume riêng (`refs_meta_done`/`refs_regex_done`/`refs_llm_done`).
- [x] CLI: `legal_rag refs --consensus`.

**Đã test trên DB thật (2026-08-22, local Neo4j, `--src most`, model `deepseek-chat`):**
- `--limit 3`: phát hiện + sửa 3 bug (mục 3.1, 3.2, 3.3 — final clause, "thay
  thế"/"bãi bỏ" ngữ cảnh, HTML tag). Thêm 9 test khoá lại.
- `--limit 40` (sau khi dọn dữ liệu tồn đọng từ các lần test trước — xoá
  `Action{source:"llm"}` + reset field đồng thuận + reset 3 flag resume, chỉ trên
  local test DB): **40 VB · nhánh A=35/B=5/C=0 · khớp=6 · 15 VB thực sự có Action ghi
  (target tồn tại trong graph) · trong đó `(regex∪LLM)` là tập con đúng của metadata
  4/15 · `regex==LLM` 3/15 · còn 11 xung đột loại cạnh**, phần lớn (9/11, VB
  `113783`) do `referenceType=1` (đã biết, giữ nguyên theo quyết định người dùng),
  còn lại (`110816`, `12041`) là ca văn bản mơ hồ thật — LLM và regex tự bất đồng,
  **đúng chức năng thiết kế** (đưa người rà, không phải bug).
- **Không còn phát hiện bug kỹ thuật nào** sau đợt sửa 3 bug trên. Tỷ lệ "khớp" thấp
  (6/40 ≈ 15%) phản ánh đúng thực tế dữ liệu (nhiều VB `most` có referenceType=1
  rải rác + độ mơ hồ ngôn ngữ pháp lý thật), không phải lỗi logic.

**Còn cần trước khi chạy full corpus:**
- [ ] Chốt phương án quota LLM (mục 0.1 đã cảnh báo — chi phí tăng từ ~13% VB lên
      ~100% VB, LLM giờ chạy trên MỌI VB không chỉ tập khó). Model `deepseek-chat`
      dùng để test — cần xác nhận đủ quota/ngân sách cho ~36-66k lượt gọi.
- [ ] Cân nhắc thêm bước dọn dữ liệu (`Action{source:"llm"}` cũ + reset field đồng
      thuận) nếu định chạy lại nhiều lần trong lúc còn phát triển — dữ liệu cũ chồng
      lên dữ liệu mới sẽ gây nhiễu số liệu (đã gặp thật khi test — mục 3.3 note).
