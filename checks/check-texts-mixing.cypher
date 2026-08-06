// Kiểm: FETCH trong Chatbot-Law/chatbot/legal_rag/retrieval/index.py:26-30 có gom
// nhiều phiên bản của cùng một Component vào `texts` hay không.
//
// Nghi vấn (§10.2b của giai-phap-sinh-cau-hoi-eval.md): subquery gom Expression của
// mọi Component con mà KHÔNG lọc theo hieu_luc_den, nên một Khoản đã bị sửa sẽ đóng
// góp CẢ text cũ lẫn text mới vào body đem embed.
//
//   MATCH (d)-[:HAS_PART*0..]->(x:Component)-[:HAS_VERSION]->(e:Expression)
//   WITH x, e ORDER BY x.order_key
//   RETURN collect(e.text) AS texts        <-- không có điều kiện hiệu lực
//
// Chạy Q0 trước. Q0 ra toàn n=1 thì dừng — không có gì để trộn, nghi vấn bác bỏ.
// Cú pháp CALL (d) {...} cần Neo4j >= 5.23 (khớp với code hiện hành).


// ─────────────────────────────────────────────────────────────────────────────
// Q0 · Có Component nào nhiều hơn 1 Expression không?   [CHẠY CÁI NÀY TRƯỚC]
// Toàn bộ n = 1  ->  không thể trộn, dừng tại đây.
// ─────────────────────────────────────────────────────────────────────────────
MATCH (c:Component)-[:HAS_VERSION]->(e:Expression)
WITH c, count(e) AS n
RETURN n AS so_phien_ban, count(c) AS so_component
ORDER BY so_phien_ban;


// ─────────────────────────────────────────────────────────────────────────────
// Q1 · Điều/ToànVăn/PhụLục nào có subtree bị trộn phiên bản
// so_expr > so_comp  <=>  tồn tại Component trong subtree có >1 Expression
// <=>  `texts` của Điều đó chứa nhiều hơn một phiên bản.
// ─────────────────────────────────────────────────────────────────────────────
MATCH (n:Norm)-[:HAS_PART*]->(d:Component)
WHERE d.loai IN ['Dieu','ToanVan','PhuLuc']
CALL (d) {
  MATCH (d)-[:HAS_PART*0..]->(x:Component)-[:HAS_VERSION]->(e:Expression)
  RETURN count(DISTINCT x) AS so_comp, count(e) AS so_expr
}
WITH n, d, so_comp, so_expr
WHERE so_expr > so_comp
RETURN n.norm_id      AS norm_id,
       d.duong_dan    AS dieu,
       so_comp        AS so_thanh_phan,
       so_expr        AS so_expression,
       so_expr - so_comp AS so_ban_thua
ORDER BY so_ban_thua DESC, norm_id
LIMIT 50;


// ─────────────────────────────────────────────────────────────────────────────
// Q2 · Mổ một ca cụ thể — lấy norm_id/duong_dan từ Q1 điền vào
// Thành phần nào hiện ra >= 2 dòng  ->  cả 2 text đã vào body đem embed.
// ─────────────────────────────────────────────────────────────────────────────
:param norm_id  => 'ĐIỀN_TỪ_Q1';
:param duong_dan => 'ĐIỀN_TỪ_Q1';

MATCH (n:Norm {norm_id:$norm_id})-[:HAS_PART*]->(d:Component {duong_dan:$duong_dan})
MATCH (d)-[:HAS_PART*0..]->(x:Component)-[:HAS_VERSION]->(e:Expression)
RETURN x.duong_dan     AS thanh_phan,
       x.order_key     AS thu_tu,
       e.expr_id       AS expr_id,
       e.hieu_luc_tu   AS tu,
       e.hieu_luc_den  AS den,          // NULL = đang mở
       size(e.text)    AS do_dai,
       left(e.text, 90) AS trich
ORDER BY x.order_key, e.hieu_luc_tu;


// ─────────────────────────────────────────────────────────────────────────────
// Q3 · Khía cạnh thứ hai: FETCH trả BAO NHIÊU DÒNG cho mỗi Điều
//
// CẢNH BÁO — bản đầu của query này SAI và đã cho báo động giả:
//   count(de) đếm (đường đi Norm->d) × (Expression của d), KHÔNG phải số phiên bản.
//   `MATCH (n:Norm)-[:HAS_PART*]->(d)` khớp MỌI đường đi, mà HAS_PART không phải
//   cây thuần -> nhiều đường tới cùng một node. Phải count(DISTINCT de).
//
// Đo thật 2026-08-06: Dieu 2 / 111-2018-TT-BTC có 1 Component, 1 Expression,
// nhưng 7 đường đi (2 đường dài 2, 5 đường dài 3) -> "so_row = 7".
// ─────────────────────────────────────────────────────────────────────────────
MATCH (n:Norm)-[:HAS_PART*]->(d:Component)
WHERE d.loai IN ['Dieu','ToanVan','PhuLuc']
MATCH (d)-[:HAS_VERSION]->(de:Expression)
WITH n, d, count(DISTINCT de) AS so_phien_ban, count(de) AS so_dong_fetch
WHERE so_phien_ban > 1 OR so_dong_fetch > so_phien_ban
RETURN n.norm_id AS norm_id, d.duong_dan AS dieu,
       so_phien_ban,                              // > 1  -> có version thật
       so_dong_fetch,                             // > so_phien_ban -> FETCH chạy thừa
       so_dong_fetch - so_phien_ban AS dong_thua
ORDER BY dong_thua DESC, norm_id
LIMIT 50;


// ─────────────────────────────────────────────────────────────────────────────
// Q3b · Số dòng thừa của FETCH — chi phí embed lặp
// Mỗi dòng thừa = 1 lần build_text_unit + 1 lần encode() cho CÙNG nội dung.
// point_id giống nhau nên upsert idempotent (không hỏng dữ liệu), chỉ tốn compute.
// ─────────────────────────────────────────────────────────────────────────────
MATCH (n:Norm)-[:HAS_PART*]->(d:Component)
WHERE d.loai IN ['Dieu','ToanVan','PhuLuc']
WITH d, count(*) AS so_duong_di
RETURN count(*)               AS so_dieu,
       sum(so_duong_di)       AS tong_dong_fetch,
       sum(so_duong_di) - count(*) AS dong_thua,
       round(100.0 * (sum(so_duong_di) - count(*)) / sum(so_duong_di), 1) AS pct_lang_phi;


// ─────────────────────────────────────────────────────────────────────────────
// Q4 · Tác động lên nhóm G2 — con số cần để quyết định
// Ứng viên G2 = Điều có >1 phiên bản. Trong đó bao nhiêu % bị trộn text?
// bi_tron cao  ->  G2 không dùng được cho tới khi FETCH được sửa (Q5).
// ─────────────────────────────────────────────────────────────────────────────
MATCH (n:Norm)-[:HAS_PART*]->(d:Component)
WHERE d.loai IN ['Dieu','ToanVan','PhuLuc']
MATCH (d)-[:HAS_VERSION]->(de:Expression)
WITH d, count(de) AS ver_dieu
WHERE ver_dieu > 1
CALL (d) {
  MATCH (d)-[:HAS_PART*0..]->(x:Component)-[:HAS_VERSION]->(e:Expression)
  RETURN count(DISTINCT x) AS so_comp, count(e) AS so_expr
}
WITH count(*) AS ung_vien_G2,
     sum(CASE WHEN so_expr > so_comp THEN 1 ELSE 0 END) AS bi_tron
RETURN ung_vien_G2,
       bi_tron,
       ung_vien_G2 - bi_tron AS dung_duoc_ngay,
       CASE WHEN ung_vien_G2 = 0 THEN 0.0
            ELSE round(100.0 * bi_tron / ung_vien_G2, 1) END AS pct_bi_tron;


// ─────────────────────────────────────────────────────────────────────────────
// Q5 · Đối chứng: `texts` ĐÚNG tại một thời điểm nên trông thế nào
// So kết quả này với Q2 để thấy phần dư. Đây cũng là dạng điều kiện mà FETCH
// trong index.py cần bổ sung nếu Q1/Q4 xác nhận có trộn.
// ─────────────────────────────────────────────────────────────────────────────
:param as_of => '2024-07-01';

MATCH (n:Norm {norm_id:$norm_id})-[:HAS_PART*]->(d:Component {duong_dan:$duong_dan})
MATCH (d)-[:HAS_PART*0..]->(x:Component)-[:HAS_VERSION]->(e:Expression)
WHERE e.hieu_luc_tu <= date($as_of)
  AND (e.hieu_luc_den IS NULL OR e.hieu_luc_den > date($as_of))
WITH x, e ORDER BY x.order_key
RETURN count(e)              AS so_phan_dung_tai_thoi_diem,
       collect(x.duong_dan)  AS thanh_phan,
       size(reduce(s = '', t IN collect(e.text) | s + t + '\n')) AS do_dai_body;


// ─────────────────────────────────────────────────────────────────────────────
// KẾT QUẢ ĐÃ CHẠY — 2026-08-06, Neo4j localhost:7687
//
//   Q0   n=1 cho TOÀN BỘ 2.630.398 Component      -> KHÔNG có Component nào
//                                                    nhiều hơn 1 Expression
//   Q1   rỗng                                     -> KHÔNG có trộn phiên bản
//   Q4   ung_vien_G2=11.287 / bi_tron=0           (con số 11.287 là ảo — do lỗi
//                                                  đếm đường đi, xem Q3)
//   Q3b  ~ mỗi Điều bị FETCH lấy nhiều lần        -> embed lặp, xem §10.3
//
//   => Nghi vấn §10.2b BÁC BỎ. `texts` không trộn phiên bản.
//   => Nhưng phát sinh hai kết luận lớn hơn, ghi ở §10.3 của tài liệu chính:
//        (1) đồ thị KHÔNG có versioning cấp Component (action_tao = 0)
//            -> nhóm G2 theo định nghĩa cũ có 0 ứng viên
//        (2) FETCH duyệt trùng đường đi -> tốn compute embed
// ─────────────────────────────────────────────────────────────────────────────
