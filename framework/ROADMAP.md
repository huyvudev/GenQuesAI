# Lộ trình: từ bộ eval một dự án → framework dùng chung

> Mục tiêu: các nhà phát triển chatbot luật Việt Nam nạp cây luật của họ vào, framework
> sinh bộ đề và chấm hệ của họ. Hỗ trợ hộp trắng (có phần truy hồi) lẫn hộp đen.
>
> Trạng thái hiện tại: bộ eval **chạy được và đã cho số thật** trên một corpus. Đó là
> vị trí tốt để bắt đầu trừu tượng hoá — thiết kế framework trước khi có bản chạy được
> thì thường trừu tượng nhầm chỗ.

## Đã có

| | |
|---|---|
| 8 nhóm câu hỏi + lý do từng nhóm | tài sản chính, không phụ thuộc hệ nào |
| Hợp đồng grounding I1–I4, cổng C1–C5 | `generator/` |
| Bộ sinh 400 câu (394 kể từ khi G6 siết điều kiện), sinh lại được | đọc `Corpus`, không còn khoá vào Neo4j (A1) |
| Tầng chấm + triage, tự chứa | `framework/grader.py` (A3), không cần cài `Chatbot-Law` |
| Hợp đồng adapter cho hệ được đo, 2 adapter mẫu | `framework/adapter.py` + `evaluate/adapters.py` (B) |
| Đối chiếu gold theo nội dung, không cần chung id | `framework/doi_chieu.py` (A2) |
| Phiếu review C5 + tính ceiling | `generator/run_c5.py` — 3 lượt đã chạy (AI duyệt), lượt 4 đang chờ người ngoài dự án |
| Schema corpus trung gian + 2 loader + báo cáo năng lực | `framework/` |
| 2 mốc đo baseline trên bộ đề đã freeze | `out/ket_qua_*.json` |

---

## A — Gỡ ràng buộc  *(chặn mọi thứ khác)*

### A3. Tầng chấm tự chứa  ✅ **XONG**

`framework/grader.py` — 106 dòng thuần chép từ `legal_rag.evaluation.grader`, không
LLM, không DB, giữ nguyên 4 chiều `citation · validity · content · behavior` để số liệu
cũ vẫn so được. `evaluate/score.py` không còn `import legal_rag...` trực tiếp nào.

Framework cài được trên máy trắng — đưa cho người khác thử được ngay cả khi A1 chưa
xong (đúng thứ tự đã định: A3 trước, nhỏ nhất, gỡ được nhiều nhất).

### A2. Gold span đối chiếu theo NỘI DUNG, bỏ `chunk_id`  ✅ **XONG** (2026-08-19)

`framework/doi_chieu.py` — so chồng lấn chuỗi (cửa sổ trượt 64 ký tự, chuẩn hoá +
casefold) giữa gold span và `retrieved_contexts`, thay vì so `chunk_id`. `chunk_id`
giữ làm đường nhanh tuỳ chọn (trúng thì khỏi đo chuỗi); `chunk_text_sha256` của cổng
C1 vẫn lo ca *id còn nguyên nhưng nội dung đã đổi*.

Hệ quả đúng như dự tính: `recall` từ nhị phân thành liên tục. Đã kiểm với hộp trắng
legal-rag: đường id và đường nội dung cho cùng kết quả trên các ca đối chiếu được
(xem `tests/test_doi_chieu.py`).

### A1. Bộ sinh đọc `Corpus` thay vì Neo4j  ✅ **XONG** (2026-08-18)

Cả 8 module `generator/` nay duyệt `Corpus` qua `framework/truy_van.py`; không còn lời
gọi `neo.run()` nào ngoài `Neo4jLoader` (đúng vai). `run_all --corpus <thư mục JSONL>`
chạy trọn bộ sinh KHÔNG cần Neo4j.

Đối chiếu ứng viên Corpus-vs-Cypher trên đồ thị thật trước khi thay:
G1 2500/2500 khớp · G3 843/843 khớp · G4 2426/2507 (81 ca lệch là Cypher đếm BẢN GHI
Action thay vì VĂN BẢN nguồn — bản mới đúng hơn). Nạp trọn corpus ~2 GB RAM / ~2 phút,
đổi lại mọi truy vấn chạy trong bộ nhớ.

**Chỗ khó:** nhiều query dùng `HAS_PART*` — đường đi biến độ dài của Cypher — phải viết
lại thành duyệt cây trên `Corpus.comp_theo_norm`. Không khó về thuật toán nhưng **dễ sai
lặng lẽ**: bản Cypher đang trả về cả tổ tiên lẫn hậu duệ ở vài chỗ, và chính nó từng gây
lỗi duyệt trùng đường đi (§10.3d).

**Cách kiểm:** bộ golden ở `tests/` — xem `tests/README.md`. Chạy `pytest`.

> Kế hoạch ban đầu ("sinh lại rồi so với bản freeze") **không đủ**, và đo được: G1/G2
> khớp từng chữ giữa hai lần chạy độc lập, nhưng **G7 lệch 87/90 câu** — vì
> `BAY_KHAC_VB` là `LIMIT 2` không `ORDER BY`, và dạng câu gán theo vị trí vòng lặp.
> Ở G7 phép diff đó đỏ sẵn **trước khi A1 bắt đầu**. Nên bộ golden tách *bộ sinh chọn
> câu nào* (được phép đổi) khỏi *đồ thị nói sự thật gì* (không được đổi), và replay
> 1.531 sự kiện chưng cất từ bộ đề đã freeze.

Nền cho A1 đã có: `framework/truy_van.py` dịch một lần ngữ nghĩa Cypher
(`HAS_PART*` vs `HAS_PART`, loại `CAN_CU`, khoảng nửa mở `[tu, den)`), 29 test phủ.

---

## B — Hợp đồng hệ được đo  ✅ **XONG** (2026-08-19)

**B1.** `framework/adapter.py::RAGAdapter.ask(question, as_of_date) -> RAGResult`
với `RAGResult{answer, retrieved_contexts, retrieved_ids?, citations?, as_of_date?}`.

**B2.** Đối chiếu `retrieved_contexts` (chuỗi nguyên văn) với gold span bằng chồng lấn
— chính là A2, `framework/doi_chieu.py`.

**B3.** Hai adapter mẫu trong `evaluate/adapters.py`: `LegalRagAdapter` (hộp trắng) +
`HTTPAdapter` trong `framework/adapter.py` (hộp đen, chọn qua `score.py --adapter
legal_rag|http [--url ...]`).

> B3 quan trọng hơn vẻ ngoài: **adapter thứ hai là thứ duy nhất chứng minh hợp đồng
> đúng.** Cùng lý do đã viết `JsonlLoader` — một loader thì luôn vừa khít với chính nó,
> kể cả khi thiết kế sai. Và đúng vậy: chỉ khi xuất ra JSONL rồi nạp lại mới lộ ra
> chuyện lấy mẫu đầu-dãy làm báo cáo năng lực lạc quan giả.

---

## C — Đóng gói

`pyproject.toml` · CLI hợp nhất (`corpus soi` / `gen` / `run` / `report`) · cấu hình
bằng file thay cho biến môi trường · tài liệu cho người ngoài.

Phần này thẳng, không rủi ro kỹ thuật.

---

## D — Bộ chuẩn phát hành

**D1.** Chốt corpus tham chiếu + **ngày chốt luật**. Câu "tháng 7/2021 áp dụng văn bản
nào" đúng vĩnh viễn; câu "hiện nay quy định thế nào" hỏng khi có văn bản mới → phải viết
lại thành mốc cố định hoặc làm mới mỗi kỳ.

**D2.** C5 trên bộ chuẩn, **do người ngoài dự án duyệt**. Không phải thủ tục: đây là câu
trả lời cho *"đáp án của các anh có đúng không?"* mà bên bị chấm thấp chắc chắn sẽ hỏi.

**D3.** Chia ba phần: công khai (~100 câu, có đáp án — để tự kiểm) · ẩn (~250 câu — để
xếp hạng) · luân chuyển (~50 câu, sinh mới mỗi kỳ — để phát hiện hệ đã học thuộc phần ẩn).

**D4.** Đo **độ phủ corpus trước khi chấm**. Hệ không nạp văn bản X mà bị tính sai là so
sai đối tượng. Báo cáo hai con số tách rời: *độ phủ* (kho rộng đến đâu) và *chất lượng*
(với những văn bản nó CÓ thì tốt đến đâu). Gộp lại thì che mất cả hai.

---

## Chặn nhau

```
A3 ──► A2 ──► A1 ──► B ──► C ──► D
 ✅      ✅      ✅     ✅    ○      ○
                                 ▲
C5 (cần người, chạy song song) ──┘
   ba lượt AI duyệt xong, lượt kế chờ người ngoài dự án
```

**C5 chặn D và nên bắt đầu ngay.** Không phải vì thủ tục: nếu C5 cho thấy một nhóm dưới
95% thì phải **sửa bộ sinh**, mà sửa xong mới đóng gói được. Đóng gói trước rồi phát
hiện G4′ có 30% đáp án sai thì phải thu hồi bản đã phát hành.

**Trạng thái C5 (2026-08-19):** ba lượt AI duyệt thay (không tính vào D2 — D2 đòi người
ngoài dự án) đã tìm và vá được G1/G3/G5/G6 trong `generator/`; ceiling đo được tăng dần
78.8% → 72.5% (mẫu khác, không phải hồi quy) → 81.2%. Còn 2 khoảng trống KHÔNG sửa được
từ `generator/` — cần báo phía Chatbot-Law: (1) một số quan hệ SUA_DOI/THAY_THE/BAI_BO
không có trong đồ thị dù có trên vbpl.vn (G4-0025, G4-0039, G6-0012 kiểu); (2)
`Expression.hieu_luc_den` không cập nhật kịp các đợt bãi bỏ MỘT PHẦN (còn ~20% ca G3).
G6 còn một vấn đề thiết kế chưa giải: quan hệ hướng dẫn (`con` GUIDED_BY `me`) khiến
`con` luôn elaborate `me` một cách nhất quán — lọc tiêu đề Điều không đủ để tách xung
đột thật khỏi quan hệ hướng dẫn bình thường; cần đổi nguồn ứng viên hoặc so nội dung
bằng ngữ nghĩa. Chi tiết từng lượt: `c5-review-{1,2,3}-ket-qua` trong memory dự án.

Phiếu review C5 mới nhất (`out/review_c5.html`, snapshot `2026-08-19T06:45:52Z`) đã bàn
giao cho người ngoài dự án — D2 coi là xong khi có `out/c5_ket_qua.csv` từ lượt đó.

---

## Ba câu hỏi chưa trả lời được — chặn việc CHUYỂN sang corpus khác

(Không chặn A1 — A1 đã xong trên một corpus. Chặn bước sau: dùng framework cho nhà
phát triển khác, corpus khác. Chưa cấp bách so với C5/D đang làm.)

1. **Thang `cap_bac` chuẩn?** (Hiến pháp=1, Luật=2…) và quy đổi từ thang riêng của từng
   corpus ra sao. Không có thì G6 không chuyển sang corpus khác được.

2. **Chuẩn hoá `so_hieu` tới mức nào?** Đủ để nối quan hệ, hay đủ để so exact-match
   **giữa hai corpus khác nhau**? Cái sau khó hơn nhiều — và đáng lo nhất: bộ chuẩn hỏi
   về `15/2018/NĐ-CP` mà corpus của họ ghi `Nghị định 15/2018/NĐ-CP` thì exact-match
   trượt, **hệ bị chấm sai vì cách ghi chứ không vì chất lượng**.

3. **Corpus chỉ có toàn văn, không có cây Điều/Khoản** — chấp nhận ở tầng 0 với
   `loai="ToanVan"`, hay bắt buộc parse?

---

## Bài học đã trả giá — đưa vào framework để người sau khỏi trả lại

| | |
|---|---|
| Kiểm **năng lực corpus trước khi sinh** | G2 thiết kế quanh giả định "một Điều nhiều phiên bản", chạy thật ra **0 ứng viên**, phải làm lại cả nhóm |
| Tách `CAN_CU` khỏi quan hệ tác động | chiếm **59%** quan hệ đã duyệt; gộp vào thì quá nửa đáp án G4′ liệt kê văn bản **chỉ viện dẫn** — sai mà trông rất hợp lý |
| `None` phải khai báo nghĩa | `hieu_luc_den = null` là "còn hiệu lực" ở corpus này, "không biết" ở corpus khác |
| Lấy mẫu **ngẫu nhiên**, không lấy đầu dãy | mẫu đầu-dãy 4,5% chứa **đủ 340/340** văn bản có điều khoản chuyển tiếp của toàn corpus |
| Nhóm dựa trên quan hệ tụt theo **bình phương** tỷ lệ mẫu | cần cả hai đầu cạnh cùng trong mẫu: 4,5% văn bản → ~0,2% cạnh |
| Regex dùng để **canh** phải lỏng hơn bản dùng để **trích** | `core_so_hieu()` chỉ khớp chữ HOA, dữ liệu có `nđ-cp` viết thường → canh rò rỉ bị lọt |
| Thước đo không được tính điểm cho thông tin **đề bài đã cho** | grader C4 bản đầu chấm 6/6 ca G5 là leak điểm 1.0, chỉ vì số hiệu vốn nằm sẵn trong câu hỏi |
| Một văn bản có thể được ghi nhiều cách | không gộp thì đáp án danh sách trùng và Set-F1 **phạt hệ vì trả lời đúng** |
