# Bộ test golden cho A1

> **A1** (ROADMAP): chuyển 8 module `generator/` từ Cypher trực tiếp sang truy vấn trên
> `framework.schema.Corpus`. ROADMAP tự đánh giá: *"không khó về thuật toán nhưng **dễ
> sai lặng lẽ**"*. Bộ này là lưới đỡ cho đúng chỗ "lặng lẽ" đó.

```bash
pip install -e ".[dev]"
pytest                          # 166 test chạy offline
python -m tests.trich_fixture   # (cần Neo4j) mở khoá 1.531 kỳ vọng replay
pytest                          # 1.700 test
```

## Vì sao không so thẳng hai file bộ đề

ROADMAP đề xuất: *"sinh lại bộ 400 câu qua đường mới, so với bản đã freeze"*. Đúng
hướng, nhưng một mình thì không đủ — và đo thật thì thấy ngay:

- bộ sinh từng **không tái lập được** (G7 lệch 87/90 giữa hai lần chạy cùng tham số);
  đã sửa, nay có `test_sinh_on_dinh.py` giữ tính chất đó
- kể cả khi tái lập được, diff vẫn không nói gì về việc **đường mới có nhìn ra đúng sự
  thật cũ không** — sau A1 ứng viên đến từ duyệt cây `Corpus`, không từ Cypher

Nên bộ này tách hai thứ đang bị trộn:

```
bộ sinh chọn CÂU nào      được phép đổi   (thứ tự, seed, ca bằng điểm)
đồ thị nói SỰ THẬT gì     KHÔNG được đổi  ← A1 chỉ có thể phá chỗ này
```

## Các tầng

| | n | chạy được khi | kiểm gì |
|---|---|---|---|
| `test_truy_van.py` | 34 | luôn | ngữ nghĩa duyệt cây trên corpus **dựng tay**, đọc được bằng mắt |
| `test_bo_kiem.py` | 34 | luôn | chính 15 bộ kiểm của tầng replay, **hai chiều**: đúng thì im, sai thì kêu |
| `test_so_hieu.py` | 23 | luôn | chuẩn hoá số hiệu, ca lấy từ **biến thể có thật** trong corpus |
| `test_so_sanh.py` | 15 | luôn | bộ so sánh bộ đề, kiểm bằng **đột biến** |
| `test_sinh_on_dinh.py` | 14 | luôn | bộ sinh cho ra bộ đề y hệt dù nguồn đảo thứ tự (`neo`/`store` giả) |
| `test_ky_vong.py` | 10 | luôn | hợp đồng golden có còn neo đúng bộ đề không |
| `test_nhap_nhang.py` | 9 | luôn | số hiệu dùng lại → G1 loại câu, G4′ bỏ phần tử |
| `test_soi_bo_de.py` | 16 | luôn | luật cảnh báo của bộ soi + tính toàn vẹn trang HTML |
| `test_nguon_quan_he.py` | 6 | luôn | `QuanHe.nguon` sống sót qua vòng ghi–đọc JSONL |
| `test_trich_fixture.py` | 5 | luôn | bộ gom mục tiêu fixture |
| `test_su_kien.py` | 1.535 | **có fixture** | **replay** từng kỳ vọng của bộ đề lên `Corpus` |

`test_bo_kiem.py` tồn tại vì tầng replay cần fixture: chừng nào chưa xuất thì không một
assertion nào trong bảng dispatch được thực thi. Nó dựng corpus tí hon, chạy đủ 15 bộ
kiểm trên dữ liệu đúng (phải im) rồi **phá corpus theo đúng kiểu A1 dễ mắc** — đổi
`CanCu` thành `SuaDoi`, nới `hieu_luc_den` thêm một ngày, bỏ một nhánh cây — và đòi
chúng phải kêu.

## Luồng dữ liệu

```
out/eval_set.jsonl          bộ đề đã freeze, 400 câu
        │
        │  python -m tests.trich_ky_vong          (offline, deterministic)
        ▼
tests/golden/ky_vong.jsonl  2.016 SỰ KIỆN ĐỒ THỊ — hợp đồng, COMMIT
        │                   neo vào bộ đề bằng sha256; bộ đề đổi mà quên sinh lại
        │                   thì `test_ky_vong.py` đỏ ngay
        │
        │  python -m tests.trich_fixture          (cần Neo4j)
        ▼
tests/golden/fixture/       subgraph CÓ ĐÍCH — KHÔNG commit (18 MB, sinh lại mỗi
        │                   vòng). Riêng `pham_vi.json` thì commit.
        │  pytest
        ▼
test_su_kien.py             replay từng sự kiện
```

Kỳ vọng phát biểu bằng `norm_id`/`expr_id`, **không nhắc Cypher, không nhắc `Corpus`** —
nhờ vậy cùng một file kiểm được cả đường hiện tại lẫn đường sau A1.

### Fixture phải CÓ ĐÍCH, không được lấy mẫu

`out/corpus/` là mẫu 3.000 văn bản ngẫu nhiên — đo thật, chỉ giao 19/438 văn bản mà bộ
đề nhắc tới. Replay trên đó thì 96% kỳ vọng bị skip và bảng kết quả **báo xanh**.
`trich_fixture.py` đi ngược lại: đọc `ky_vong.jsonl` trước, lấy đúng cái cần — kèm **mọi
văn bản ở đầu kia của cạnh trỏ vào**, vì nhiều kỳ vọng là đẳng thức tập hợp và thiếu
láng giềng sẽ khiến chúng **pass nhầm**.

Hai loại "không kiểm được", tách bạch vì trộn là mất cả hai tín hiệu:

| | |
|---|---|
| **bộ xuất gom sót** | ĐỎ — lỗi của `trich_fixture.py` |
| **đồ thị nguồn vốn không có** | skip kèm lý do, ghi vào `pham_vi.json` lúc xuất. Skip **có đếm và có ngưỡng** (`NGUONG_KHONG_KIEM_DUOC`) — không có ngưỡng thì skip chính là cách một bộ golden chết dần mà vẫn xanh |

Kỳ vọng **phủ định** (`G8(a)`: "số hiệu này không tồn tại") không replay được trên tập
con — trên corpus nghèo thì cái gì cũng không tồn tại. Chúng được đối chiếu với đồ thị
đầy đủ **ngay lúc xuất** và phán quyết ghi vào `pham_vi.json`.

## Định nghĩa-xong của A1

1. 8 module `generator/` không còn `neo.run(...)`; đọc `Corpus` qua `framework/truy_van.py`.
2. `pytest` xanh toàn bộ — **1.531 kỳ vọng replay không được đỏ dòng nào**.
3. `python -m tests.so_sanh <bản cũ> <bản A1>`: khác **tập câu** thì phải giải thích được
   bằng thứ tự/ca bằng điểm — ghi lời giải thích vào PR, đừng chỉ ghi nhận con số.

## Những gì bộ này đã tìm ra

Tất cả đều là lỗi **không có triệu chứng** ở mọi cổng C1–C5.

| | |
|---|---|
| ✅ **G8 sinh câu trùng** | `NGOAI_PHAM_VI` 5 chủ đề / quota 7 → 2 cặp câu trùng nguyên văn |
| ✅ **G7 không tái lập được** | 87/90 câu lệch giữa hai lần chạy — `LIMIT` không `ORDER BY`, và dạng câu gán theo vị trí vòng lặp |
| ✅ **`Corpus` gộp mất hai nguồn `THAY_THE`** | cạnh `REPLACES` (G1) và `Action` (G4′) → thêm `QuanHe.nguon` |
| ✅ **`so_hieu` mù 46% kho** | mẫu cũ đòi năm 4 chữ số → 1.382 văn bản không bao giờ được hỏi |
| ✅ **Ký tự nhìn giống hệt** | `С` Kirin, `–` en-dash trong số hiệu → hai chuỗi hiện y hệt mà `==` trả False |
| ✅ **G5 gold span trỏ nhầm Điều** | `CONTAINS 'Điều ' + stt` khớp tiền tố; 77% ứng viên có >1 Điều khớp, 7/30 câu đã trỏ sai |
| ✅ **G3 hai câu giống hệt, hai đáp án khác** | hệ trả lời kiểu gì cũng trượt một câu |
| ⬜ **62% gold span không có nội dung trong đồ thị** | xem dưới — chặn A1 |

### Chặn A1: nội dung chỉ nằm trong index

`Expression.text` trong Neo4j chứa văn bản của **riêng node đó** — với văn bản QPPL
thường chỉ là câu dẫn:

```
Expression   54 ký tự   "Bãi bỏ toàn bộ các văn bản quy phạm pháp luật sau đây:"
chunk       890 ký tự   câu dẫn + trọn danh sách văn bản bị bãi bỏ
```

14% Expression rỗng hoàn toàn, và với **gold span thì 62% không có nội dung nào trong đồ
thị** — nó sống trong Qdrant.

Bộ sinh hiện tại đọc Qdrant nên không thấy. Bộ sinh sau A1 đọc `Corpus` sẽ mù đúng chừng
ấy, và bộ lọc độ dài của G7 (300–2500 ký tự) sẽ loại nhầm gần hết ứng viên. **A1 không
thể chỉ đổi nguồn truy vấn**: hoặc ingest ghi text vào đồ thị, hoặc `Corpus` nạp thêm
`chunks` (schema đã chừa chỗ) và bộ sinh lùi về đó khi text rỗng.

`truy_van.noi_dung_cay()` ghép node + cả cây con — đúng thứ A1 cần.
`test_do_thi_co_noi_dung_de_A1_doc_duoc` chốt con số 62%; nó phải **đi xuống**, tăng là
hồi quy.
