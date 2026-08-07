# Phác thảo: schema corpus trung gian

> Hợp đồng ĐẦU VÀO của framework. Mọi kho văn bản QPPL — Neo4j, SQL, JSONL, hay file
> thô đã parse — map vào đây, rồi bộ sinh làm việc **duy nhất** với schema này.
>
> Trạng thái: phác thảo để bàn. Chưa cài đặt.

## Nguyên tắc thiết kế

**1. Mỗi trường bắt buộc là một rào cản gia nhập.** Corpus của người khác sẽ không có
`TransitionRule` đã tách, không có `Action.confidence`. Bắt buộc những thứ đó thì
framework không ai dùng được. Nên schema chia **tầng năng lực**: có tới đâu sinh tới đó.

**2. Nguyên văn là bất khả xâm phạm.** `Expression.text` phải là chữ trong văn bản gốc,
không tóm tắt, không chuẩn hoá nội dung. Toàn bộ hợp đồng grounding (I1–I4) dựa trên
việc đối chiếu chuỗi ký tự với nguồn — một lần tóm tắt xen vào là mất khả năng đó.

**3. Framework không đoán định dạng id.** `norm_id`, `component_id` là chuỗi tuỳ ý của
corpus. Framework chỉ dùng chúng để nối, không parse.

**4. Không biết ≠ không có.** Xem §4 — đây là chỗ dễ sai nhất.

---

## 1. Bốn thực thể

```python
@dataclass
class Norm:                          # một văn bản
    norm_id: str                     # khoá corpus-local
    so_hieu: str                     # "15/2018/NĐ-CP" — chuẩn hoá khi nạp, giữ bản thô
    loai_vb: str | None              # Luật · NghiDinh · ThongTu · QuyetDinh…
    tieu_de: str | None
    ngay_ban_hanh: date | None
    ngay_hieu_luc: date | None
    cap_bac: int | None              # thứ bậc pháp lý; nhỏ hơn = cao hơn
    co_quan_ban_hanh: str | None
    nguon_url: str | None            # BẮT BUỘC nếu muốn chạy review C5

@dataclass
class Component:                     # Điều / Khoản / Điểm / Phụ lục
    component_id: str
    norm_id: str
    loai: Literal["Dieu", "Khoan", "Diem", "PhuLuc", "ToanVan"]
    parent_id: str | None            # cây; None = con trực tiếp của Norm
    so_thu_tu: str | None            # "6", "12a"
    tieu_de: str | None
    thu_tu: int                      # thứ tự xuất hiện, để sắp ổn định

@dataclass
class Expression:                    # NỘI DUNG của một Component trong một khoảng thời gian
    expression_id: str
    component_id: str
    text: str                        # NGUYÊN VĂN
    hieu_luc_tu: date | None
    hieu_luc_den: date | None        # xem §4 về ý nghĩa của None

@dataclass
class QuanHe:                        # quan hệ giữa hai VĂN BẢN
    loai: LoaiQuanHe
    tu_norm_id: str                  # văn bản gây tác động
    den_norm_id: str                 # văn bản bị tác động
    ngay_hieu_luc: date | None
    do_tin: float | None             # 0..1 nếu trích tự động
    da_duyet: bool | None            # người đã xác nhận chưa
    pham_vi: str | None              # "toàn bộ" / "Điều 5" / …
```

### `LoaiQuanHe` — chỗ này phải tách bạch

```python
class LoaiQuanHe(Enum):
    THAY_THE   = "thay_the"      # A thay thế B  → B hết hiệu lực
    SUA_DOI    = "sua_doi"       # A sửa đổi/bổ sung B → B vẫn còn, nội dung đổi
    BAI_BO     = "bai_bo"        # A bãi bỏ B (một phần hoặc toàn bộ)
    HUONG_DAN  = "huong_dan"     # A hướng dẫn thi hành B
    CAN_CU     = "can_cu"        # A viện dẫn B làm căn cứ — KHÔNG tác động gì tới B
    HOP_NHAT   = "hop_nhat"      # văn bản hợp nhất
```

> **`CAN_CU` phải là một loại riêng và bộ sinh phải loại nó ra.** Trong corpus thật của
> `Chatbot-Law`, `CAN_CU` chiếm **28.286/48.213 ≈ 59%** quan hệ đã duyệt. Gộp nó vào
> "văn bản đã tác động tới X" thì **quá nửa đáp án nhóm G4′ sẽ liệt kê những văn bản chỉ
> viện dẫn X chứ không hề sửa X** — sai, mà lại sai một cách trông rất hợp lý.
>
> Đây là lỗi tôi suýt mắc. Nếu schema không có chỗ để phân biệt thì người dùng framework
> sẽ mắc lại, và không có cách nào phát hiện từ bên ngoài.

---

## 2. Tầng năng lực — corpus khai báo, framework sinh theo

| Tầng | Cần thêm gì | Mở khoá nhóm |
|---|---|---|
| **0** | `Norm` + `Component` + `Expression.text` | **G7** nội dung · **G8** không-có-đáp-án |
| **1** | `Expression.hieu_luc_tu/den` **và** cờ `theo_doi_hieu_luc` | **G2′** tại-một-thời-điểm |
| **2** | `QuanHe.THAY_THE` | **G1** thay thế |
| **3** | `QuanHe.HUONG_DAN` (+ tầng 2) | **G3** hiệu lực dây chuyền |
| **4** | `QuanHe.SUA_DOI` / `BAI_BO` | **G4′** lịch sử sửa đổi |
| **5** | `DieuKhoanChuyenTiep` (§3) | **G5** chuyển tiếp |
| **6** | `Norm.cap_bac` (+ tầng 0) | **G6** xung đột *(ứng viên, cần người duyệt)* |

Nạp corpus xong, framework in ra ngay:

```
Corpus "vbpl-bo-tu-phap"   12.400 văn bản · 486.000 điều khoản

  ✅ G7   90 câu     nội dung điều luật
  ✅ G8   25 câu     không-có-đáp-án
  ✅ G1   50 câu     8.100 quan hệ THAY_THE
  ⚠️  G2′  38 câu     chỉ 71% điều khoản có hieu_luc_den → không đủ 80
  ⚠️  G3   20 câu     340 quan hệ HUONG_DAN → không đủ 60
  ❌ G4′            corpus không có QuanHe.SUA_DOI
  ❌ G5             corpus không có điều khoản chuyển tiếp
  ❌ G6             corpus không có cap_bac

  Sinh được 223/400 câu.  Bổ sung SUA_DOI để mở khoá thêm 40 câu.
```

Đây là thứ tôi ước có từ đầu: tôi thiết kế G2 dựa trên giả định "một điều có nhiều
phiên bản theo thời gian", chạy ra **0 ứng viên**, phải làm lại cả nhóm. Bước khai báo
năng lực biến lỗi đó thành một dòng cảnh báo trước khi tốn công.

---

## 3. Hai thực thể tuỳ chọn

```python
@dataclass
class DieuKhoanChuyenTiep:           # tầng 5 → G5
    rule_id: str
    norm_id: str
    dieu_kien: str                   # "Hồ sơ nộp trước ngày Luật này có hiệu lực"
    ap_dung: str                     # "tiếp tục thực hiện đến hết thời hạn ghi trong giấy phép"
    nguon_component_id: str | None
    do_tin: float | None
    da_duyet: bool | None

@dataclass
class Chunk:                         # đường nhanh TUỲ CHỌN — xem §5
    chunk_id: str
    expression_id: str
    part: int
    text: str
```

---

## 4. `None` nghĩa là gì — chỗ dễ sai nhất

Trong `Chatbot-Law`, `hieu_luc_den = NULL` nghĩa là **còn hiệu lực**. Trong một corpus
chỉ nạp văn bản mà không theo dõi hiệu lực, `NULL` nghĩa là **không biết**.

Cùng một giá trị, **hai nghĩa ngược nhau**. Bộ sinh mà đoán sai thì sinh ra hàng loạt
câu "văn bản này còn hiệu lực" cho một corpus vốn không biết điều đó — và không có cách
nào phát hiện từ kết quả.

Nên corpus phải **khai báo tường minh** ở cấp bộ:

```python
@dataclass
class CorpusMeta:
    ten: str
    ngay_chot: date                  # dữ liệu cập nhật tới ngày nào
    theo_doi_hieu_luc: bool          # True  -> hieu_luc_den=None nghĩa là CÒN hiệu lực
                                     # False -> nghĩa là KHÔNG BIẾT → khoá tầng 1, tắt G2′
    quan_he_tu_dong: bool            # quan hệ do trích tự động? -> bắt buộc lọc do_tin/da_duyet
    nguon: str | None
```

Cùng loại vấn đề, một chỗ khác: `Norm.cap_bac`. Framework **không** được suy cấp bậc từ
`loai_vb` — thứ bậc pháp lý VN có ngoại lệ, và corpus mỗi nơi đánh số một kiểu. Không
khai báo thì tắt G6, đừng đoán.

---

## 5. Chunk: tuỳ chọn, và tại sao

Bộ đề hiện tại neo gold span vào `chunk_id = point_id(expr_id, part)` — **id của Qdrant
thuộc `legal-rag`**. Hệ khác chunk khác, id khác, hoàn toàn vô nghĩa với họ.

Nên framework đối chiếu bằng **nội dung**:

```
gold span (nguyên văn cắt từ Expression.text)
        ↕  chồng lấn chuỗi / token
retrieved_contexts[i]  (nguyên văn hệ được đo trả về)
```

`Chunk` chỉ là **đường nhanh tuỳ chọn** cho corpus nào tình cờ dùng chung không gian id
với hệ được đo — như trường hợp `Chatbot-Law` đo chính nó. Có thì `recall` nhị phân và
chính xác; không có thì `recall` liên tục theo độ chồng lấn. Không bắt buộc.

Giữ lại `chunk_text_sha256` như hiện nay: nó bắt được ca **id còn nguyên nhưng nội dung
đã đổi** — lỗi im lặng duy nhất mà mọi cổng khác đều không thấy.

---

## 6. Giao diện nạp

```python
class CorpusLoader(Protocol):
    def meta(self) -> CorpusMeta: ...
    def norms(self) -> Iterator[Norm]: ...
    def components(self) -> Iterator[Component]: ...
    def expressions(self) -> Iterator[Expression]: ...
    def quan_he(self) -> Iterator[QuanHe]: ...
    def chuyen_tiep(self) -> Iterator[DieuKhoanChuyenTiep]: ...   # tuỳ chọn
    def chunks(self) -> Iterator[Chunk]: ...                       # tuỳ chọn
```

Bản đầu cần hai loader để chứng minh trừu tượng đúng chỗ:

- `Neo4jLoader` — map từ schema `Chatbot-Law` (đã có sẵn toàn bộ Cypher)
- `JsonlLoader` — cho ai không dùng graph; cũng là định dạng trao đổi

**Chỉ khi corpus thứ hai chạy được mới biết mình trừu tượng đúng.** Một loader thì luôn
vừa khít với chính nó.

---

## 7. Kiểm chất lượng khi nạp

Chạy ngay lúc nạp, trước khi sinh câu nào — mỗi mục dưới đây là một lỗi đã gặp thật:

| Kiểm | Vì sao |
|---|---|
| `so_hieu` parse được | dữ liệu thật có `"Thông tư 38/2024/TT-BYT"` lẫn `"52/2024/NĐ-CP"`; và `03/2022/QH15` từng bị cắt thành `03/2022/QH` — sai toàn bộ nhóm Luật, không cổng nào bắt được |
| Chiều `THAY_THE` | so `ngay_hieu_luc` hai đầu; trong corpus thật **70/8.003 cạnh ngược chiều hoặc cùng ngày** → loại, đừng dùng làm đáp án |
| `hieu_luc_den > hieu_luc_tu` | corpus thật có **14 bản ghi năm 3000** (giá trị sentinel) |
| Tiêu đề chứa số hiệu | tiêu đề văn bản thật có dạng `"Thông tư số 12/2016/TT-BTTTT Quy định về…"` — dùng làm chủ đề câu hỏi là **lộ đúng thứ cần giấu** |
| Nhiều bản ghi cùng một văn bản | `19/2012/TTLT-BTC - BKH&ĐT-BTTTT` và `19/2012/TTLT-BTC-BKHĐT-BTTTT` là **một** văn bản; không gộp thì đáp án danh sách trùng và Set-F1 **phạt hệ vì trả lời đúng** |
| Component có Expression | nếu không thì tầng 0 cũng không sinh được |

---

## Câu hỏi còn mở

1. **`cap_bac` đánh số thế nào?** Cần một thang chuẩn (Hiến pháp=1, Luật=2, …) và bảng
   quy đổi từ thang riêng của từng corpus. Chưa có.
2. **Cần chuẩn hoá `so_hieu` tới mức nào?** Đủ để nối quan hệ, hay đủ để chấm
   exact-match giữa hai corpus khác nhau? Cái sau khó hơn nhiều.
3. **Corpus không có cây Điều/Khoản** (chỉ có toàn văn) — chấp nhận ở tầng 0 với
   `loai="ToanVan"`, hay bắt buộc phải parse?
