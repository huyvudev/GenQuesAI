## ✅ Sửa 284 VB "rỗng" (2026-09-04) — XONG hoàn toàn

Rà lại 284 VB bị coi là "rỗng" (checkpoint cũ, xem mục dưới) — phát hiện 2 nguyên
nhân khác nhau, không phải vbpl.vn thiếu dữ liệu như tưởng ban đầu:

- **127 VB**: bug trong `build_local_file_index()` (`_rebuild_full_corpus.py`) —
  khi 1 `norm_id` xuất hiện ở NHIỀU thư mục con (`most/`, `tw/`, `mic/`, `manual/`,
  `cdi_backfill/`...), code cũ lấy thư mục quét SAU CÙNG (thứ tự bảng chữ cái) thay
  vì thư mục có nội dung dài nhất — 1 bản `toanvan.html` gần rỗng (~89 byte) ghi đè
  lên bản có nội dung thật (vd 25KB). **Đã sửa** hàm (ưu tiên file dài nhất khi
  trùng norm_id) + chạy lại `resolve_relations` riêng cho 127 VB này
  (`_repair_127_rong.py`) — 0 lỗi.
- **157 VB**: thật sự chưa từng crawl được nội dung từ vbpl.vn (mọi lần thử đều ra
  trang rỗng <200 byte). Tải thủ công qua trình duyệt (tài khoản trả phí
  thuvienphapluat.vn của user) — 155 VB ở tab "Văn bản Pháp Luật", 2 VB
  (`7711/TC/TCT`, `7333/TC/TCT`, công văn cũ 2004) ở tab "Công văn". Lưu vào
  `CORPUS_DIR/tvpl_backfill/<norm_id>/` (doc.json + toanvan.html), đối chiếu số
  hiệu 100% khớp trước khi ghi (phát hiện + sửa 1 bug Unicode NFD/NFC khi trích
  text từ trang — 1 số trang trả về tiếng Việt dạng tổ hợp, làm lệch so khớp số
  hiệu). Chạy `resolve_relations` riêng cho 157 VB (`_repair_157_tvpl.py`) — 0 lỗi.

**Kết quả**: `con lai rong = 0` (verify trực tiếp Neo4j production). Tổng Action
tăng từ 195.189 → **197.371** (+2.182 cạnh mới từ 284 VB này). Toàn bộ 66.368 VB
trong corpus giờ đã qua v3 thật sự hoàn chỉnh (trước đó 284 VB bị bỏ sót ngầm, không
lộ ra vì không nằm trong số liệu "cần rà"/"đã khớp" nào).

Script mới (chưa dọn, để tham khảo nếu cần chạy lại kiểu tương tự):
`_repair_127_rong.py`, `_repair_157_tvpl.py`. Sửa 1 chỗ trong
`_rebuild_full_corpus.py::build_local_file_index()` (đã commit vào working tree,
CHƯA commit git).

---

# Tiến độ xử lý cạnh REPLACES/AMENDS/GUIDED_BY toàn corpus (v3 consensus)

> File checkpoint — cập nhật liên tục trong quá trình xử lý. Đọc file này TRƯỚC khi
> hỏi lại "đang làm đến đâu" nếu máy/Claude bị sập giữa chừng. Xem thêm `rule.md`
> (quy tắc kỹ thuật đầy đủ) và code trong thư mục này (`_audit_corpus.py`,
> `_backfill_8k.py`, `_process_from_qdrant.py`).

Cập nhật lần cuối: 2026-08-25 sáng.

## 📊 CHỈ SỐ CHÍNH THỨC — CẬP NHẬT LẦN CUỐI 2026-08-25 ~23h15

**Thay thế hoàn toàn số liệu "đêm qua" ở dưới — số liệu dưới đây SAI/CŨ, đã qua thêm
2 lượt xử lý (trích cấp Điều + sửa 2 bug lệch số liệu khi xuất file) sau đó.**

Tổng Action: **190.206** (đã verify khớp 100%, không sót cạnh nào — kiểm tra trực
tiếp Neo4j `con_sot=0`):

| | Số cạnh | File |
|---|---|---|
| ✅ Tự động duyệt (không cần làm gì) | **79.697** | `3_THAM_KHAO_da_khop.csv` |
| ⚠️ **Cần rà tay** | **84.937** | `1_CAN_DUYET_can_ra.xlsx` — REPLACES 10.133 · GUIDED_BY 57.830 · AMENDS 16.974 |
| ⚠️ Đích mơ hồ (chưa có cạnh thật) | **25.572** | `2_CAN_XU_LY_dich_mo_ho.csv` |

Cả 3 file gộp tại `genquesai/legal_rag/_CAN_RA_SOAT/`. Đang chờ user duyệt xong
2 file "cần rà"/"đích mơ hồ" rồi đưa lại.

## Rà soát phụ — sửa lỗi phân loại REPLACES (2026-08-25 tối)

Test trang chat ngoài `luatvietnammisa.aicongvu.gov.vn` (10 cạnh/lô, xem hội thoại)
lộ ra 1.511 cạnh REPLACES nghi bị phân loại nhầm (tiêu đề VB tự ghi "một số điều"
nhưng gắn nhãn REPLACES/BaiBoToanBo thay vì AMENDS). Viết `_ra_soat_replaces_nghi_van.py`
— chạy lại CHÍNH XÁC hàm phân loại thật (regex thuần, MIỄN PHÍ, không LLM) đối
chiếu 9.848 cạnh REPLACES mismatch/only_llm: **1.305 sửa đúng thành AMENDS**, 2.647
xác nhận đúng là REPLACES, 5.896 không đối chiếu được qua regex (giữ nguyên). Đã
ghi vào Neo4j + xuất lại file (REPLACES 10.133→8.828, AMENDS 16.974→18.279, tổng
cần rà vẫn 84.937 — chỉ đổi PHÂN LOẠI, không đổi tổng số cần rà).

**Tiếp theo:** mở rộng test trang chat ngoài lên lô 30 cạnh/lần (đang làm).

## 📊 (CŨ — chỉ giữ lại làm lịch sử, xem số liệu chính thức ở trên)

- **Tổng corpus**: 66.368 Norm (VB) trên cả local và server (đã đồng bộ khớp nhau).
- **Rebuild v3 (per-edge) xử lý**: 66.084/66.368 VB có kết quả — 284 VB nội dung
  quá ngắn/rỗng (không xử lý được, không phải lỗi) · 0 lỗi (2 lỗi mạng tạm thời ban
  đầu đã chạy lại thành công).
  - Nguồn text: 36.744 VB đọc từ file raw cục bộ · 29.340 VB dựng lại từ Qdrant
    (không có preamble "Căn cứ..." → GUIDED_BY hạn chế cho nhóm này).
- **Tổng Action (cạnh) sau rebuild — số ĐÚNG sau khi dọn bug đích mơ hồ: 172.095**,
  chia 4 nhóm:

  | Nhóm | Số lượng | Ý nghĩa |
  |---|---|---|
  | `da_duyet=true` | **68.006** | Tự động duyệt — đủ nguồn khả dụng đồng ý, KHÔNG cần rà |
  | `mismatch=true` | **74.348** | Nguồn lệch nhau — cần rà tay |
  | `only_llm=true` | **4.169** | Chỉ 1 nguồn (LLM), không đối chiếu được — cần rà tay |
  | `dich_mo_ho=true` | **25.572** | Số hiệu đích trùng ≥2 Norm khác nhau trong graph — CHƯA có cạnh thật, cần xác định đích trước |

  → **Cần người rà tổng cộng: 78.517 (mismatch+only_llm, đã xuất `_can_ra.xlsx`) +
  25.572 (đích mơ hồ, đã xuất `_dich_mo_ho.csv`) = 104.089 dòng.**

- **1 bug dữ liệu phát hiện + đã sửa (2026-08-25 sáng)**: 1.247 số hiệu VB bị trùng
  giữa nhiều Norm khác nhau trong graph (dữ liệu cũ chưa dedup) → ghi cạnh nhầm
  nhân đôi/ba đích cho 25.572 Action (14,9% tổng). Đã dọn (xem mục dưới), tách
  riêng, KHÔNG tự đoán đích đúng.
- **Chi phí thực tế đợt rebuild**: ước tính ~$35 (DeepSeek off-peak, đã tính trước
  khi chạy — chưa có số thật từ dashboard DeepSeek để đối chiếu).
- **File output** (`genquesai/legal_rag/`): `_da_khop.csv` (68.006 dòng) ·
  `_can_ra.xlsx` (78.517 dòng, 3 sheet REPLACES/AMENDS/GUIDED_BY) ·
  `_dich_mo_ho.csv` (67.555 dòng, 25.572 Action) · `_rebuild_log.jsonl` (66.084
  dòng, checkpoint đầy đủ từng VB) · `_backup_actions_20260824_135225.jsonl`
  (132.219 Action — backup TRƯỚC KHI rebuild, dữ liệu cũ hoàn toàn, chỉ để đối
  chiếu lịch sử nếu cần, KHÔNG dùng để khôi phục).

## ⚠️ THAY ĐỔI LỚN vừa thực hiện (đọc trước khi làm gì tiếp)

1. **Local DB đã đồng bộ = server** (qua `neo4j-admin database dump` trên server →
   scp về → `neo4j-admin database load` vào local). Cả 2 bên giờ **66.368 Norm**
   giống hệt nhau. File dump: `genquesai/legal_rag/_dump/neo4j.dump` (701MB, có thể
   xoá sau khi xác nhận ổn).
2. **TOÀN BỘ Action (cạnh REPLACES/AMENDS/GUIDED_BY) đã bị XOÁ SẠCH — CẢ LOCAL LẪN
   SERVER (0 Action mỗi bên).** Đã backup trước khi xoá:
   `genquesai/legal_rag/_backup_actions_20260824_135225.jsonl` (132.219 Action, lấy
   trên server TRƯỚC lượt xoá — dùng để đối chiếu nếu cần, KHÔNG phải để khôi phục
   nguyên trạng vì đây là xoá có chủ đích để rebuild sạch).
3. Server có gián đoạn ngắn (~40 giây, dừng hẳn container `legalrag-neo4j` để dump —
   Community Edition không hỗ trợ `STOP DATABASE` runtime) — user đã xác nhận chấp
   nhận (không ai dùng DB lúc đó).
4. **Việc CẦN LÀM TIẾP:** đồ thị Norm/Component/Expression vẫn còn nguyên (không bị
   xoá), CHỈ Action bị xoá — cần chạy lại toàn bộ pipeline consensus v3 (rebuild
   per-edge) để TẠO LẠI Action từ đầu, theo đúng kế hoạch đã bàn (loại Action cũ,
   chỉ giữ Action sinh từ v3). Vì Action rỗng, nguồn `nguon_metadata/regex/llm` JSON
   cũ cũng KHÔNG CÒN — bắt buộc phải chạy lại LLM cho TOÀN BỘ 66.368 VB (không còn
   phân biệt 27.281 "có dữ liệu" vs 39.087 "thiếu" nữa — giờ tất cả đều cần chạy
   lại). Đây chính là Option C (~$35, DeepSeek off-peak) nhưng KHÔNG PHẢI lãng phí
   nữa — vì Action cũ đã bị xoá thật, không còn gì để đọc lại.
5. **Qdrant KHÔNG bị đụng tới** trong bước đồng bộ này (chỉ đồng bộ Neo4j) — Qdrant
   local vẫn là bản cũ, chưa khớp server. Có thể cần đồng bộ riêng sau nếu cần.

## Rebuild per-edge — ĐANG CHẠY (2026-08-24 ~22h04)

- **Sửa xong bug per-edge trong `consensus.py`**: hàm mới `dong_thuan_per_edge()` +
  `_ghi_canh_moi()` thay thế `_ghi_ket_qua_dong_thuan`/`_tao_action_moi` cũ — mỗi
  CẠNH tự xét đồng thuận riêng (không broadcast 1 quyết định cho cả VB nữa). Test
  mới trong `tests/test_consensus.py` (10 test, có ca khoá bug cũ). `pytest tests/`
  pass 100%.
- **Script chạy**: `_rebuild_full_corpus.py` — ghi vào **LOCAL Neo4j** (tránh downtime
  production nhiều giờ), đọc Qdrant từ **SERVER** (local Qdrant chưa đồng bộ). Ưu
  tiên file raw cục bộ (44.363 VB có sẵn), phần còn lại (~22.005 VB) dựng từ Qdrant.
  Checkpoint: `genquesai/legal_rag/_rebuild_log.jsonl` (1 dòng/VB, đầy đủ chi tiết
  từng cạnh — `da_duyet`/`mismatch`/`only_llm`/`nguon`), tiến độ:
  `genquesai/legal_rag/_rebuild_progress.log`.
- **Đã test 10 VB trước khi chạy full** — xác nhận: per-edge hoạt động đúng thật
  (VB `110855` có cạnh khớp lẫn cạnh lệch trong CÙNG 1 VB, không còn broadcast).
- [x] **XONG lúc 2026-08-25 00:06** (nhanh hơn ước tính — ~2 tiếng, không phải
  8-10 tiếng). Task `b1xksh661`. Kết quả cuối (đọc thật từ Neo4j local, 172.094
  Action):
  - 66.082/66.368 VB có kết quả (284 VB nội dung quá ngắn/rỗng · 2 lỗi MẠNG tạm
    thời, KHÔNG phải lỗi code — `39-2019-QĐ-UBND`, `12-2019-TT-BGDĐT`, cần chạy
    lại riêng 2 VB này).
  - Nguồn text: 36.744 từ file cục bộ · 29.338 dựng từ Qdrant.
  - **73.808 cạnh tự động duyệt (`da_duyet=true`, 42,9%)**.
  - **92.326 cạnh `mismatch` (53,6%) + 5.960 cạnh `only_llm` (3,5%) = 98.286 cạnh
    cần rà tay (57,1%)**.
- [x] Chạy lại 2 VB lỗi mạng — xong, 0 lỗi.
- [x] **Phát hiện + sửa bug "đích mơ hồ" (2026-08-25 sáng):** `_ghi_canh_moi` dùng
  `MATCH (tgt:Norm {so_hieu:$tsh})` — 1.247 so_hieu bị TRÙNG giữa nhiều Norm khác
  nhau trong graph (dữ liệu cũ, có Norm trùng chưa dedup) → khớp nhầm NHIỀU node,
  MERGE nhân đôi cạnh cho MỖI ứng viên. Ảnh hưởng: 25.572/172.096 Action (14,9%) bị
  nhân đôi/ba đích (tổng 67.555 cạnh sai, thay vì đúng 25.572). KHÔNG phải lỗi tính
  toán LLM (không cần chạy lại tốn tiền) — chỉ là lỗi ghi graph, sửa miễn phí.
  Đã chạy `_don_dep_dich_mo_ho.py`: xoá cạnh sai, đánh dấu 25.572 Action này
  `dich_mo_ho=true` (không tự đoán đích nào đúng), xuất danh sách ứng viên ra
  `_dich_mo_ho.csv` (67.555 dòng) để user tự quyết sau. Tổng Action ĐÚNG còn lại:
  **146.523** (68.006 tự động duyệt + 78.517 cần rà).
- [x] **Đã xuất 3 file cho user rà soát** (`genquesai/legal_rag/`):
  - `_da_khop.csv` — 68.006 cạnh đã tự động duyệt (không cần rà).
  - `_can_ra.xlsx` — 78.517 cạnh cần rà tay, 3 sheet theo loại (1_REPLACES 9.409 ·
    2_AMENDS 11.278 · 3_GUIDED_BY 57.830), nhóm theo VB nguồn trong mỗi sheet, có
    cột trống "QUYẾT ĐỊNH (điền: dung / sai)" để user điền.
  - `_dich_mo_ho.csv` — 25.572 Action (67.555 dòng ứng viên) có đích mơ hồ (số hiệu
    trùng nhiều VB) — CHƯA có cạnh nào trong graph cho nhóm này, cần user xác định
    thủ công đích đúng là VB nào (norm_id nào) trước khi tạo cạnh.
- [x] **Tách "Bãi bỏ" khỏi "Thay thế"/"Sửa đổi" (2026-08-25, quyết định user):**
  `loai` giờ có 5 giá trị: `ThayThe`/`SuaDoi`/`CanCu`/`BaiBoToanBo`/`BaiBoTungPhan`
  (2 giá trị mới). Đã sửa `reference_extractor.py` (regex `_phan_loai_dong_tu` +
  `_EDGE_MAP` + prompt LLM `_LLM_SYS`) + cập nhật test (`test_reference_extractor.py`,
  4 test đổi kỳ vọng). `pytest tests/` pass 100%. **CHƯA áp dụng retroactive** cho
  172.095 Action đã tạo (vẫn dùng phân loại cũ) — 13.968/29.483 cạnh ThayThe/SuaDoi
  có thể tách lại MIỄN PHÍ (có regex), 15.515 còn lại cần hỏi LLM lại (~$3-5) — CHƯA
  làm, có thể gộp vào lượt trích Điều sắp tới (đọc lại toàn thân 1 lần cho cả 2 việc).
- [x] **Sửa bug hiển thị "Nguồn" trong file xuất** (`_xuat_ket_qua_rebuild.py`):
  field `a.nguon` lưu dạng CHUỖI JSON, code cũ `", ".join(chuỗi)` tách nhầm theo
  TỪNG KÝ TỰ — file `_da_khop.csv`/`_can_ra.xlsx` gửi lúc trước bị lỗi cột này. Đã
  sửa (`_nguon_str()` parse JSON đúng) + gửi lại bản đúng.
- [x] **Ẩn 11.278 cạnh AMENDS khỏi `_can_ra.xlsx`** (quyết định user 2026-08-25) —
  để dành duyệt CHUNG với thông tin cấp Điều/Khoản/Điểm sau khi trích xong (tránh
  duyệt 2 lần). `_can_ra.xlsx` giờ chỉ còn 2 sheet: 1_REPLACES (9.409) +
  2_GUIDED_BY (57.830) = 67.239 dòng. `_da_khop.csv` (68.006, không cần duyệt)
  KHÔNG bị ẩn AMENDS — vẫn đủ, chỉ để tham khảo.
- [ ] **Việc tiếp theo (theo đúng thứ tự bàn với user):**
  1. User rà `_can_ra.xlsx` (67.239 dòng, REPLACES+GUIDED_BY) — điền cột QUYẾT ĐỊNH.
  2. (Song song/sau) User xử lý `_dich_mo_ho.csv` (25.572 VB đích mơ hồ).
  3. **Trích cấp Điều cho 9.418 VB nguồn có cạnh AMENDS** (15.424 cạnh) — ĐANG CHẠY
     (2026-08-25 20h34, task `b4s3m6vly`, script `_trich_cap_dieu.py`, workers=12).
     Đọc TOÀN THÂN (không chỉ preamble), tìm Điều/Khoản/Điểm VB đích, trỏ `AFFECTS`
     vào đúng Component thay vì Norm — kèm tách luôn Bãi bỏ (đọc 1 lần cho cả 2
     việc). Checkpoint: `_trich_dieu_log.jsonl` + `_trich_dieu_progress.log`.
     **Bug đã phát hiện + sửa TRƯỚC khi chạy full** (test 5 VB đầu): 1 đích bị sửa
     NHIỀU Điều — code gốc ghi đè liên tiếp lên CÙNG 1 Action, chỉ giữ được Điều
     cuối, mất các Điều khác. Đã sửa: Điều đầu tiên cập nhật Action gốc, các Điều
     sau tạo Action MỚI (action_id có hậu tố `#dieu-khoan-diem`). Verify lại bằng
     dữ liệu thật: 1 target ra đúng 2 Action riêng biệt (Khoản + Điều) — đúng.
  3b. [x] **XONG lúc 2026-08-25 21:22.** 9.063/9.063 VB, 0 lỗi. 14.715 đích xử lý →
     22.489 resolve được cấp Điều/Khoản/Điểm (10.260 không có Điều cụ thể, giữ cấp
     VB đúng bản chất; 6.412 có số Điều nhưng không tìm thấy Component tương ứng).
     4.099 cạnh đổi phân loại (tách Bãi bỏ). Action: 172.096 → **190.206**. Theo
     `cap_dich`: Điểm 5.200 · Điều 6.286 · Khoản 10.851 (tổng 22.337 cạnh cấp NHỎ
     HƠN văn bản) · VanBan (không resolve được/không có Điều) 10.298 · NULL
     (REPLACES/GUIDED_BY, không đụng tới) 157.571.
  4. Đóng hiệu lực cấp Component khi duyệt AMENDS (hàm mới `close_amended_component`,
     cascade xuống node lá nếu đích là Chương/Mục/Điều có con).
  5. [x] **XONG — đã ghép AMENDS vào `_can_ra.xlsx`** (2026-08-25 21h40): sheet mới
     `3_AMENDS` (16.974 dòng, có cột "Cấp đích" — VD "Điều 5, Khoản 2"/"Cả văn bản",
     1 cột gộp, sắp theo VB nguồn→VB đích, theo đúng lựa chọn user). `1_REPLACES`
     tăng lên 9.848 (do 1 số cạnh đổi loai qua BaiBoToanBo/ThayThe trong lượt trích
     Điều). `_da_khop.csv` cũng thêm cột "Cấp đích" (79.697 dòng). Đã sửa thêm 1 bug
     nhỏ: `_Q_DA_KHOP`/`_Q_CAN_RA` gốc chỉ match `AFFECTS->Norm`, bỏ sót các cạnh đã
     trỏ sang Component — sửa xong, verify tổng khớp (84.652 cần rà + 79.697 đã khớp
     + 25.572 đích mơ hồ + ~285 sót lại ≈ 190.206 Action thật). **Đã gửi user 2 file
     mới nhất.**
  6. **Việc tiếp theo:** User duyệt `_can_ra.xlsx` (3 sheet) + xử lý `_dich_mo_ho.csv`.
  7. Ghi cạnh thật vào graph theo mọi quyết định (REPLACES/GUIDED_BY + AMENDS cấp Điều).
  8. Đóng hiệu lực cấp Component khi duyệt AMENDS (hàm mới `close_amended_component`,
     cascade xuống node lá nếu đích là Chương/Mục/Điều có con) — **CHƯA CODE**.
  9. Đồng bộ local→server (dump/load ngược chiều so với lúc đồng bộ ban đầu) →
     HOÀN TẤT.

## Mục tiêu tổng

Duyệt (dò + đồng thuận đa nguồn) toàn bộ 66.368 VB trong corpus qua consensus v3
(metadata+regex+LLM), sau đó rà tay các cạnh chưa đồng thuận, rồi **rebuild lại toàn
bộ Action trong Neo4j từ đầu theo v3** (bỏ hết Action cũ từ pipeline trước), cuối
cùng đẩy DB lên cả local máy user và server production.

## Trạng thái các bước (theo thứ tự)

- [x] **Sửa bug trong code `consensus.py`/`reference_extractor.py`/`llm.py`** (xem
      `rule.md` các mục 3.1/5.2/5.4/9.2 + bug "nhánh A không có Action sẵn" sửa
      2026-08-24 tối) — ĐÃ SỬA trong working tree, **CHƯA COMMIT**. `pytest tests/`
      pass 100% sau mọi lần sửa.
- [x] **66.368/66.368 VB (100%) ĐÃ QUA V3 — XONG HOÀN TOÀN** (2026-08-24 ~21h,
      verify trực tiếp bằng query Neo4j, `chua=0`). Gồm:
      - 58.116 VB có sẵn từ trước phiên làm việc này.
      - 486 VB backfill được từ vbpl.vn (`_backfill_8k.py` — chỉ khớp được VB loại
        QPPL chính thức: Thông tư/Văn bản hợp nhất/Nghị định/Luật..., KHÔNG khớp
        được "văn bản cá biệt" vì vbpl.vn không đăng loại đó).
      - 7.779 VB xử lý qua Qdrant fallback (`_process_from_qdrant.py`) — GIỚI HẠN ĐÃ
        XÁC NHẬN & NGƯỜI DÙNG CHẤP NHẬN: Qdrant không lưu đoạn "Căn cứ..." nên
        GUIDED_BY gần như vắng bóng cho nhóm này, chỉ REPLACES/AMENDS dò được.
- [ ] **BƯỚC TIẾP THEO: Rebuild toàn bộ Action theo v3** (per-edge, không phải
      per-document như code hiện tại) — XOÁ Action cũ (amend_v2/title_rule/claude/
      cancu_backfill/...) CHO TOÀN BỘ 66.368 VB, CHỈ GIỮ Action sinh từ v3.
      **CHƯA VIẾT CODE** — mới bàn thiết kế. Lý do cần sửa: `_ghi_ket_qua_dong_thuan`
      hiện so khớp CẤP VĂN BẢN (toàn bộ tập quan hệ) rồi loang xuống MỌI Action — cần
      sửa thành so khớp CẤP TỪNG CẠNH mới đúng nguyên tắc "cũ = mặc định sai, chỉ
      nâng lên đúng khi có bằng chứng cụ thể" (user đã chốt 2026-08-24: không quan
      tâm Action cũ, mặc định coi là sai hết, muốn dùng hẳn kết quả v3 thay thế).
      Đây là thao tác XOÁ trên production (>122k Action) — cần backup/export trước
      khi chạy DELETE thật.
- [ ] **Sau rebuild: rà tay các cạnh `mismatch=true`/`only_llm=true`** (hàng đợi cần
      người duyệt) — xuất CSV dễ đọc (VB nguồn, cạnh đề xuất, VB đích, nguồn nào tìm
      ra, lý do lệch) cho user rà, user trả lại quyết định, rồi ghi cạnh thật vào
      Neo4j theo quyết định đó.
- [ ] **Đẩy DB lên local + server** (2 bản) — bước CUỐI CÙNG, sau khi mọi thứ ở trên
      xong. Xem chi tiết trong memory `ke-hoach-sync-db-local-server.md`.

## Số liệu tham chiếu nhanh

- Tổng Norm: 66.368. **Đã qua v3: 66.368 (100%)**.
- Kết quả gộp đợt xử lý 8.252 VB backfill/Qdrant hôm nay: khớp tự động ~482
  (462 Qdrant + ~20 trong 89 backfill retry), còn lại (mismatch + only_llm) cần rà
  tay — số chính xác cần audit lại (`_audit_corpus.py`) trước khi xuất CSV rà.
- **Vấn đề Action cũ (trước khi rebuild):** trong 58.116 VB "cũ" đã qua v3 trước
  phiên này, chỉ **53.176** Action thực sự được v3 đối chiếu; **62.707 Action cũ**
  (chủ yếu `amend_v2` 36.565) CHƯA TỪNG được v3 chạm tới do bug filter cũ (đã sửa,
  nhưng chỉ áp dụng cho VB xử lý MỚI — muốn áp cho 58.116 VB cũ phải rebuild).
- Môi trường: `.env` tại `genquesai/legal_rag/.env` trỏ THẲNG server production
  (`bolt://221.132.33.149:7687`, Neo4j user `neo4j` — xem file `.env` lấy pass, không
  commit). Chạy lệnh phải `cd` vào `genquesai/legal_rag/` để nạp đúng `.env`
  (pydantic-settings đọc `.env` theo CWD).
- Python cần dùng: `D:/Project/Chatbot-Law/chatbot/.venv/Scripts/python.exe` (có đủ
  neo4j+qdrant_client+openai+tenacity+httpx) cho script backfill/Qdrant; python hệ
  thống (`/c/Users/Huy/AppData/Local/Programs/Python/Python312/python`) đủ cho
  `refs --consensus` thường (không cần tenacity).
- Giá LLM (DeepSeek V4-Flash, 16/8/2026): off-peak $0,22/$0,66 per 1M token in/out;
  peak $0,44/$1,32. Off-peak = 08-11h và 13-17h giờ VN.

## Việc KHÔNG được quên

- Nhiều file code đã sửa trong working tree **CHƯA COMMIT** (`agent/llm.py`,
  `cli.py`, `ingestion/consensus.py`, `ingestion/reference_extractor.py`, `rule.md`,
  `tests/test_reference_extractor.py`) — nhớ commit sau khi mọi thứ chạy ổn (không
  commit vội để dễ rollback nếu phát hiện bug mới).
- `rule.md` CHƯA được cập nhật để phản ánh bug "nhánh A không có Action sẵn" vừa sửa
  tối 2026-08-24 (mục 9.2 hoặc thêm mục mới) — cần bổ sung trước khi commit.
- File rác/scratch trong thư mục này (`_*.py`, `_*.pkl`, `_*.json`, `_*.csv`) —
  KHÔNG commit, chỉ để chạy tay. Có thể dọn sau khi xong toàn bộ quy trình.
