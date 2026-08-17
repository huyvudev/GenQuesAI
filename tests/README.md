# Bộ test golden cho A1

> **A1** (ROADMAP): chuyển 8 module `generator/` từ Cypher trực tiếp sang truy vấn trên
> `framework.schema.Corpus`. ROADMAP tự đánh giá: *"không khó về thuật toán nhưng **dễ
> sai lặng lẽ**"*. Bộ này là lưới đỡ cho đúng chỗ "lặng lẽ" đó.

```bash
pip install -e ".[dev]"
pytest                                  # 124 test chạy offline, không cần Neo4j
python -m tests.trich_fixture           # (một lần, cần Neo4j) mở khoá 1.531 test còn lại
```

## Vì sao không so thẳng hai file bộ đề

ROADMAP đề xuất: *"sinh lại bộ 400 câu qua đường mới, so với `out/eval_set.jsonl` đã
freeze. Khác nhau ở đâu thì phải giải thích được ở đó."* Đúng hướng, nhưng thiếu một
bước — và đo thật thì thấy ngay:

| | |
|---|---|
| G1, G2 | hai lần chạy độc lập khớp **từng chữ** |
| G7 | hai lần chạy độc lập lệch **87/90 câu** |

G7 lệch **không phải vì ai sửa gì** — bộ sinh vốn phụ thuộc thứ tự Neo4j trả về (chi
tiết ở mục cuối; đã sửa). Nghĩa là phép "sinh lại rồi diff" từng đỏ sẵn 87 câu **trước
khi A1 bắt đầu**, không phân biệt được A1 đúng hay sai.

Sửa xong thì phép diff đó dùng được lại — nhưng chỉ cho những gì bộ sinh hứa tái lập.
Nó vẫn không nói được gì về việc *đường mới có nhìn ra đúng sự thật cũ không*, vì ứng
viên sau A1 đến từ duyệt cây `Corpus` chứ không từ Cypher. Nên bộ này vẫn tách hai thứ
đang bị trộn:

```
bộ sinh chọn CÂU nào      được phép đổi   (thứ tự, seed, ca bằng điểm)
đồ thị nói SỰ THẬT gì     KHÔNG được đổi  ← A1 chỉ có thể phá chỗ này
```

## Các tầng

| | n | chạy được khi | kiểm gì |
|---|---|---|---|
| `test_truy_van.py` | 34 | luôn | ngữ nghĩa duyệt cây trên corpus **dựng tay**, đọc được bằng mắt |
| `test_sinh_on_dinh.py` | 14 | luôn | bộ sinh cho ra bộ đề y hệt dù nguồn đảo thứ tự — chạy bằng `neo`/`store` giả |
| `test_bo_kiem.py` | 34 | luôn | chính 15 bộ kiểm của tầng replay, **hai chiều**: đúng thì im, sai thì kêu |
| `test_so_sanh.py` | 15 | luôn | bộ so sánh, kiểm bằng **đột biến** |
| `test_ky_vong.py` | 10 | luôn | hợp đồng golden: neo đúng bản bộ đề, đủ nhóm, không rỗng |
| `test_trich_fixture.py` | 5 | luôn | bộ gom mục tiêu fixture — sót ở đây thì phải chờ Neo4j một lượt mới biết |
| `test_nguon_quan_he.py` | 6 | luôn | `QuanHe.nguon` sống sót qua vòng ghi–đọc JSONL, và báo cáo năng lực đếm đúng tập |
| `test_tai_lap.py` | 4 | có `out/*.jsonl` | nhóm nào bộ sinh tái lập được, nhóm nào không |
| `test_su_kien.py` | 1.531 | **có fixture** | **replay** từng kỳ vọng của bộ đề đã freeze lên `Corpus` |

`test_bo_kiem.py` có mặt vì tầng replay chưa chạy được: chừng nào chưa có fixture thì
không một assertion nào trong bảng dispatch từng được thực thi. Nó dựng corpus tí hon,
chạy đủ 15 bộ kiểm trên dữ liệu đúng (phải im) rồi **phá corpus theo đúng kiểu A1 dễ
mắc** — đổi `CanCu` thành `SuaDoi`, nới `hieu_luc_den` thêm một ngày, bỏ một nhánh cây
— và đòi chúng phải kêu.

## Luồng dữ liệu

```
out/eval_set.jsonl          bộ đề đã freeze, 400 câu
        │
        │  python -m tests.trich_ky_vong          (offline, deterministic)
        ▼
tests/golden/ky_vong.jsonl  2.016 SỰ KIỆN ĐỒ THỊ — hợp đồng, commit
        │                   neo vào bộ đề bằng sha256; bộ đề đổi mà quên sinh lại
        │                   thì `test_ky_vong.py` đỏ ngay
        │
        │  python -m tests.trich_fixture          (cần Neo4j, chạy MỘT LẦN)
        ▼
tests/golden/fixture/       corpus subgraph CÓ ĐÍCH — commit, replay offline mãi về sau
        │
        │  pytest
        ▼
test_su_kien.py             replay từng sự kiện
```

Kỳ vọng phát biểu bằng `norm_id`/`expr_id`, **không nhắc Cypher, không nhắc `Corpus`**.
Nhờ vậy cùng một file kiểm được cả đường Neo4j hiện tại lẫn đường sau A1 — đó là điều
kiện để nó là golden thật chứ không phải ảnh chụp của một cách hiện thực.

### Fixture phải CÓ ĐÍCH, không được lấy mẫu

`out/corpus/` là mẫu 3.000 văn bản ngẫu nhiên — đo thật, nó giao đúng **19/438** văn bản
mà bộ đề nhắc tới. Replay trên đó thì 96% kỳ vọng bị skip và bảng kết quả báo xanh.
`trich_fixture.py` đi ngược lại: đọc `ky_vong.jsonl` trước, rồi lấy đúng cái các kỳ vọng
đó cần — kèm **mọi văn bản ở đầu kia của cạnh trỏ vào**, vì nhiều kỳ vọng là đẳng thức
tập hợp và thiếu láng giềng sẽ khiến chúng **pass nhầm**.

Kỳ vọng phủ định (`G8(a)`: "số hiệu này không tồn tại") không replay được trên tập con —
trên corpus nghèo thì cái gì cũng không tồn tại. Chúng được đối chiếu với đồ thị đầy đủ
**ngay lúc xuất** và phán quyết ghi vào `pham_vi.json`.

## Định nghĩa-xong của A1

1. 8 module `generator/` không còn `neo.run(...)`; đọc `Corpus` qua `framework/truy_van.py`.
2. `pytest` xanh toàn bộ — **1.531 kỳ vọng replay không được đỏ dòng nào**.
3. `python -m tests.so_sanh out/eval_set.jsonl out/eval_set_a1.jsonl`:
   - `doi_noi_dung` **rỗng** ở G1, G2 (hai nhóm đã chứng minh là tái lập được);
   - khác **tập câu** ở nhóm khác thì phải giải thích được bằng thứ tự/ca bằng điểm —
     ghi lời giải thích vào PR, đừng chỉ ghi nhận con số.

## Ba việc bộ này phát hiện được

Cả ba đều là loại lỗi **không có triệu chứng** ở mọi cổng C1–C5 hiện có.

### ✅ Đã sửa ở bộ sinh — `2 câu G8 trùng nguyên văn`

`NGOAI_PHAM_VI` chỉ có 5 chủ đề trong khi quota công thức (d) ở n=25 là 7; vòng lặp quay
vòng danh sách → `G8-0003 ≡ G8-0020`, `G8-0004 ≡ G8-0024`. G8 tính 25 câu nhưng chỉ có
23 câu phân biệt, 2 câu đếm hai lần khi chấm `behavior`.

Sửa ba lớp: danh sách lên 16 chủ đề · trần cứng "mỗi chủ đề dùng đúng một lần" với phần
dư chuyển sang a/b/c · lưới chặn trùng ở **mọi** công thức. Kiểm ở
`test_sinh_on_dinh.py` cho n ∈ {4, 12, 25, 40, 80}.

### ✅ Đã sửa ở bộ sinh — `G7 không tái lập được`

87/90 câu lệch giữa hai lần chạy cùng tham số. Ba nguồn phi xác định:

| | |
|---|---|
| `BAY_KHAC_VB` | `LIMIT 2` không `ORDER BY` → Neo4j trả hai hàng bất kỳ (81 câu) |
| subquery *anh em* | `collect(DISTINCT ...)[0..2]` không sắp trước khi cắt |
| `ORDER BY n.ngay_hieu_luc DESC` | hàng nghìn văn bản chung ngày → `LIMIT $pool` cắt vào giữa khối bằng điểm, **tập** ứng viên đổi |
| `rng.shuffle(rows)` | hoán vị phụ thuộc thứ tự đầu vào → dạng câu/persona/khuôn gán theo vị trí đổi theo (14–16 câu) |

Sửa: `ORDER BY` xác định cho cả ba truy vấn, **và sắp chuẩn `rows` theo `expr_id` trước
khi trộn**. Cái sau quan trọng nhất với A1 — sau A1 ứng viên đến từ duyệt cây `Corpus`,
thứ tự không có lý do gì trùng Neo4j, nên khoá chuẩn hoá ở tầng Python là thứ duy nhất
sống sót.

`test_sinh_on_dinh.py` kiểm trực tiếp tính chất đó: đảo thứ tự đầu vào → bộ đề y hệt.

### ✅ Đã sửa ở schema — `Corpus` gộp mất hai nguồn của `THAY_THE`

Cạnh `REPLACES` (G1 dùng) và `Action{loai:'ThayThe'}` (G4′ dùng) cùng map về một giá trị
enum, chỉ tách được bằng proxy `do_tin is None`.

Nay `QuanHe.nguon: NguonQuanHe` khai thẳng — `CANH` cho cạnh đã biên tập, `TU_DONG` cho
bản trích tự động. `LoaiQuanHe` nói quan hệ *nghĩa là gì*, `NguonQuanHe` nói nó *từ đâu
ra*; hai trục độc lập. Cả hai loader đều khai, JSONL giữ được qua vòng ghi–đọc, và
`framework.cli soi` in cảnh báo khi corpus không khai (lùi về proxy).

Sửa kéo theo một chỗ đang sai âm thầm: `capabilities.danh_gia()` đếm ứng viên G1 trên
**toàn bộ** `THAY_THE`. Trên corpus mẫu nó báo **38 ứng viên G1** trong khi bộ sinh chỉ
dùng được **19** — đúng một nửa là nhánh trích tự động, bị đếm ở cả G1 lẫn G4′. Nay mỗi
nhóm đếm đúng tập mà nó sẽ dùng.

---

**Bộ đề đã freeze vẫn mang hai lỗi G8/G7.** Sửa nằm ở bộ sinh; `out/eval_set.jsonl` chỉ
sạch sau khi sinh lại — cần Neo4j, và kéo theo phải re-baseline cả ba lần chạy eval đã
lưu. Trong lúc chờ, hai hằng số `TRUNG_DA_BIET` và `G7_LECH_DA_BIET` giữ phép đo lại.
