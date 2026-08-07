# Hai lỗi trong pipeline embed của `legal-rag`

Phát hiện khi dựng bộ eval (repo `GenQuesAI`). Cả hai **không phá dữ liệu**, nhưng lỗi
thứ nhất làm **thiếu point trong index** nên ảnh hưởng trực tiếp chất lượng retrieval.

Đo trên Neo4j + Qdrant production, 2026-08-06.

---

## 1. Resume chỉ kiểm `part=0` → thiếu point sau khi re-window

`chatbot/legal_rag/retrieval/index.py:127`

```python
for r in neo.stream(FETCH, norm_ids=norm_ids):
    if existing and point_id(r["expr_id"]) in existing:   # ← thiếu tham số part
        skipped += 1
        continue
```

`point_id()` mặc định `part=0`, nên vòng lặp chỉ hỏi *"cửa sổ đầu tiên của Điều này đã
embed chưa?"*.

**Hệ quả khi chạy với `skip_existing=True`:**

| Tình huống | Kết quả |
|---|---|
| Điều nở từ 1 → 3 cửa sổ (nội dung dài ra, hoặc `window_chars` giảm) | Thấy `part=0` đã có → **skip cả Điều** → `part=1,2` **không bao giờ được tạo** |
| Điều co từ 3 → 2 cửa sổ | `part=2` thành **mồ côi**, chỉ `delete_by_exprs` trong CDI prune mới dọn |

Trường hợp thứ nhất là mất mát im lặng: index thiếu phần đuôi của Điều, retrieval không
bao giờ tìm thấy nội dung đó, và không có lỗi nào được ném ra.

**Hướng sửa** — kiểm đủ số cửa sổ chứ không chỉ cửa sổ đầu. Cần biết `n_parts` trước
khi quyết định skip, nên phải split trước rồi mới đối chiếu:

```python
body = "\n".join(t for t in (r["texts"] or []) if t)
wins = split_windows(body, window_chars, window_overlap) or [body]
if existing and all(point_id(r["expr_id"], i) in existing for i in range(len(wins))):
    skipped += 1
    continue
```

Đổi lại thì `split_windows` chạy hai lần cho mỗi Điều (một lần ở đây, một lần trong
`flush`) — rẻ hơn nhiều so với embed thiếu.

---

## 2. `FETCH` duyệt trùng đường đi → embed lặp cùng nội dung

`chatbot/legal_rag/retrieval/index.py:22`

```cypher
MATCH (n:Norm)-[:HAS_PART*]->(d:Component)
```

`HAS_PART*` khớp **mọi đường đi**, mà đồ thị không phải cây thuần — có nhiều đường từ
`Norm` tới cùng một `Component`.

**Đo thực tế:** `Dieu 2` của `111-2018-TT-BTC` có **7 đường đi** từ Norm (2 đường dài 2,
5 đường dài 3) trong khi chỉ có **1 Component và 1 Expression**.

**Hệ quả:** `FETCH` trả 7 dòng cho Điều đó. Mỗi dòng chạy `build_text_unit()` +
`embedder.encode()` cho **cùng một nội dung**. `point_id` giống nhau nên upsert
idempotent — **không hỏng dữ liệu**, chỉ tốn compute. Embedding là phần đắt nhất của
pipeline.

**Hướng sửa** — thêm `DISTINCT` sau khi khớp đường đi:

```cypher
MATCH (n:Norm)-[:HAS_PART*]->(d:Component)
WHERE d.loai IN ['Dieu','ToanVan','PhuLuc']
  AND ($norm_ids IS NULL OR n.norm_id IN $norm_ids)
WITH DISTINCT n, d          // ← gộp các đường đi trùng
MATCH (d)-[:HAS_VERSION]->(de:Expression)
...
```

Nên đo lại tổng số dòng `FETCH` trước/sau để biết mức tiết kiệm thật.

---

## Hai điều đã kiểm và KHÔNG phải lỗi

Ghi lại để khỏi ai đi kiểm lại:

**`texts` không trộn phiên bản.** Nghi vấn ban đầu là subquery gom Expression của mọi
Component con mà không lọc `hieu_luc_den`, nên một Khoản đã sửa sẽ đóng góp cả text cũ
lẫn mới. **Không xảy ra**: toàn bộ 2.630.398 Component đều có **đúng 1** Expression
(`action_tao` = 0 — `versioning.amend_component()` chưa từng chạy). Không có gì để trộn.

**`point_id` ổn định qua re-index.** `uuid5(_NS, expr_id[#part])` với `_NS` là hằng số —
hàm thuần, không random, không timestamp. Đối chiếu 20/20 point thật trong Qdrant.

Script kiểm: `GenQuesAI/checks/check-texts-mixing.cypher`.
