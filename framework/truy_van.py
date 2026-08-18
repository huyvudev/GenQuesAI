"""Tầng truy vấn trên `Corpus` — NỀN cho A1.

A1 (ROADMAP) là việc chuyển 8 module `generator/` từ Cypher trực tiếp sang truy vấn
trên `framework.schema.Corpus`. Module này là chỗ ngữ nghĩa Cypher được dịch MỘT LẦN,
có test phủ, để 8 module kia không mỗi nơi dịch một kiểu.

ROADMAP gọi A1 là *"không khó về thuật toán nhưng dễ sai lặng lẽ"*. Ba chỗ sai lặng lẽ
đã biết, mỗi chỗ có một hàm riêng ở đây thay vì để người viết tự suy:

1.  `HAS_PART*` (đường đi biến độ dài) ≠ `HAS_PART` (một bước).
    `g7_content.SELECT` dùng `*` để lấy MỌI Điều, nhưng `g7_content.BAY_KHAC_VB` dùng
    một-bước để lấy Điều CẤP CAO NHẤT. Lẫn hai cái là đổi tập ứng viên mà không có
    triệu chứng nào. → `moi_thanh_phan()` vs `con_truc_tiep()`.

2.  Đồ thị KHÔNG phải cây thuần: `Neo4jLoader.Q_COMP` ghi rõ "đo thật: có Điều 7 đường
    đi", nên bản Cypher phải `WITH DISTINCT`. Bản duyệt cây phải khử trùng tương đương,
    nếu không cùng một Component vào tập ứng viên nhiều lần và tỷ lệ lấy mẫu lệch.

3.  `CAN_CU` chiếm 59% quan hệ đã duyệt. Gộp vào "văn bản nào đã tác động tới X" thì
    quá nửa đáp án là văn bản chỉ VIỆN DẪN X. → `tac_dong_toi()` lọc sẵn.

── Hai nguồn cùng đổ vào một loại quan hệ ─────────────────────────────────────
Đồ thị nguồn có HAI đường sinh ra `LoaiQuanHe.THAY_THE`:

    Q_TT   `(a)-[:REPLACES]->(b)`                     — cạnh có sẵn, đã duyệt
    Q_ACT  `(a)<-[:ENACTED_BY]-(Action{loai:'ThayThe'})-[:AFFECTS]->(b)` — LLM trích

Bộ sinh phân biệt hai đường đó: **G1 chỉ dùng cạnh, G4′ chỉ dùng Action.** Nên
`QuanHe.nguon` (`NguonQuanHe`) khai báo thẳng, và mọi hàm dưới đây lọc theo nó.

Corpus CŨ không có trường này — `nguon_cua()` lùi về proxy `do_tin is None` để chúng
vẫn nạp được, nhưng `kiem_gia_dinh_nguon()` sẽ nói rõ là đang chạy bằng phỏng đoán.
Proxy đúng với `Neo4jLoader` nhưng không phải hợp đồng: loader khác hoàn toàn có thể
gán `do_tin` cho cạnh trực tiếp, và lúc đó G1 lặng lẽ lấy tập ứng viên của G4′.
"""
from __future__ import annotations

from datetime import date
from typing import Iterable, Literal

from .schema import (Component, Corpus, DieuKhoanChuyenTiep, Expression, LoaiQuanHe,
                     NguonQuanHe)

Nguon = Literal["canh", "tu_dong", "ca_hai"]

# Ngưỡng đã chốt ở §10.3h sau khi xem phân bố — hai thang RIÊNG, không dùng chung.
MIN_DO_TIN_ACTION = 0.85
MIN_DO_TIN_CHUYEN_TIEP = 0.9


# ── nguồn của một quan hệ ───────────────────────────────────────────────────
def nguon_cua(q) -> NguonQuanHe:
    """Nguồn của một quan hệ: ưu tiên trường khai báo, lùi về proxy nếu thiếu.

    Corpus khai `nguon` thì dùng thẳng. Corpus cũ không khai thì đoán bằng `do_tin`
    — chỉ nhánh `Action` mang `confidence`. Đoán, và `kiem_gia_dinh_nguon()` nói rõ
    là đang đoán; đây không phải chỗ để im lặng.
    """
    if q.nguon is not None:
        return q.nguon
    return NguonQuanHe.TU_DONG if q.do_tin is not None else NguonQuanHe.CANH


_THEO_TEN = {"canh": NguonQuanHe.CANH, "tu_dong": NguonQuanHe.TU_DONG}


def _hop_nguon(q, nguon: Nguon) -> bool:
    return nguon == "ca_hai" or nguon_cua(q) is _THEO_TEN[nguon]


def kiem_gia_dinh_nguon(c: Corpus) -> list[str]:
    """Cảnh báo khi việc tách hai nguồn không đáng tin. Im lặng = tách được.

    Gọi lúc nạp corpus lạ, trước khi sinh đề.
    """
    canh: list[str] = []
    tt = [q for q in c.quan_he if q.loai is LoaiQuanHe.THAY_THE]
    if not tt:
        return canh

    thieu = [q for q in tt if q.nguon is None]
    if thieu:
        canh.append(
            f"{len(thieu):,}/{len(tt):,} quan hệ THAY_THE không khai `nguon` — đang "
            "suy bằng proxy `do_tin is None`. Proxy đúng với đồ thị kiểu legal-rag, "
            "nhưng loader gán `do_tin` cho cả cạnh trực tiếp sẽ khiến G1 lấy nhầm "
            "tập ứng viên của G4′ mà không cổng nào thấy.")

    theo = {n: sum(1 for q in tt if nguon_cua(q) is n) for n in NguonQuanHe}
    if not theo[NguonQuanHe.CANH]:
        canh.append("không quan hệ THAY_THE nào đến từ cạnh trực tiếp — G1 sẽ ra rỗng")
    if not theo[NguonQuanHe.TU_DONG]:
        canh.append("không quan hệ tác động nào trích tự động — G4′ sẽ ra rỗng")
    return canh


# ── quan hệ cấp văn bản ─────────────────────────────────────────────────────
def _theo_dich(c: Corpus, norm_id: str) -> list:
    return c.qh_theo_dich.get(norm_id, [])


def _theo_nguon(c: Corpus, norm_id: str) -> list:
    # `Corpus` chỉ đánh chỉ mục theo ĐÍCH. Quét tuyến tính ở đây là cố ý: thêm chỉ mục
    # thứ hai vào `Corpus` là đổi hợp đồng schema, và các nhóm cần chiều này (G1 tìm
    # anh em) chỉ gọi ~vài trăm lần. Nếu về sau thành nút thắt thì thêm `qh_theo_nguon`
    # vào `Corpus.dung_chi_muc()` chứ đừng nhân bản vòng lặp này ra chỗ khác.
    return [q for q in c.quan_he if q.tu_norm_id == norm_id]


def thay_the_boi(c: Corpus, norm_id: str, nguon: Nguon = "canh") -> set[str]:
    """Những văn bản THAY THẾ `norm_id` (tức `norm_id` là bên bị thay).

    Cypher gốc: `MATCH (moi)-[:REPLACES]->(cu)` với `cu.norm_id = norm_id`.
    `nguon="canh"` là mặc định vì G1 dựng trên cạnh REPLACES, không trên Action.
    """
    return {q.tu_norm_id for q in _theo_dich(c, norm_id)
            if q.loai is LoaiQuanHe.THAY_THE and _hop_nguon(q, nguon)}


def da_thay_the(c: Corpus, norm_id: str, nguon: Nguon = "canh") -> set[str]:
    """Những văn bản BỊ `norm_id` thay thế. Chiều ngược của `thay_the_boi`.

    Dùng cho bẫy "anh em gần" của G1: văn bản khác cũng bị chính `moi` thay thế.
    """
    return {q.den_norm_id for q in _theo_nguon(c, norm_id)
            if q.loai is LoaiQuanHe.THAY_THE and _hop_nguon(q, nguon)}


def huong_dan_cho(c: Corpus, norm_id: str) -> set[str]:
    """Văn bản mẹ mà `norm_id` hướng dẫn thi hành.

    Cypher gốc: `(con)-[:GUIDED_BY]->(me)`; loader map `tu=con`, `den=me`.
    """
    return {q.den_norm_id for q in _theo_nguon(c, norm_id)
            if q.loai is LoaiQuanHe.HUONG_DAN}


def duoc_huong_dan_boi(c: Corpus, norm_id: str) -> set[str]:
    """Các văn bản hướng dẫn thi hành `norm_id`."""
    return {q.tu_norm_id for q in _theo_dich(c, norm_id)
            if q.loai is LoaiQuanHe.HUONG_DAN}


def tac_dong_toi(c: Corpus, norm_id: str,
                 min_do_tin: float = MIN_DO_TIN_ACTION,
                 nguon: Nguon = "tu_dong") -> set[str]:
    """Các văn bản đã SỬA ĐỔI / THAY THẾ / BÃI BỎ `norm_id` — đáp án G4′.

    Ba bộ lọc bắt buộc, đúng thứ tự §4.5:
      1. loại ∈ {SUA_DOI, THAY_THE, BAI_BO}  → `CAN_CU` bị `tac_dong()` loại sẵn
      2. `da_duyet = true`  (chỉ ép khi corpus khai `quan_he_tu_dong`)
      3. `do_tin >= 0.85`

    Tự loại `norm_id` khỏi kết quả: đồ thị có cạnh tự trỏ, giữ lại thì đáp án
    "văn bản nào tác động tới X" chứa chính X.
    """
    td = LoaiQuanHe.tac_dong()
    ra: set[str] = set()
    for q in _theo_dich(c, norm_id):
        if q.loai not in td or not _hop_nguon(q, nguon):
            continue
        if c.meta.quan_he_tu_dong and q.da_duyet is not True:
            continue
        if q.do_tin is not None and q.do_tin < min_do_tin:
            continue
        if q.tu_norm_id == norm_id:
            continue
        ra.add(q.tu_norm_id)
    return ra


def chuyen_tiep_cua(c: Corpus, norm_id: str,
                    min_do_tin: float = MIN_DO_TIN_CHUYEN_TIEP
                    ) -> list[DieuKhoanChuyenTiep]:
    """Điều khoản chuyển tiếp của `norm_id` — nguồn G5.

    Ngưỡng RIÊNG 0.9, không dùng chung với `Action` (§10.3h): hai thang điểm khác
    nhau, dùng chung một ngưỡng là trộn hai phân bố.
    """
    return [t for t in c.chuyen_tiep
            if t.norm_id == norm_id
            and not (c.meta.quan_he_tu_dong and t.da_duyet is not True)
            and not (t.do_tin is not None and t.do_tin < min_do_tin)]


# ── cây thành phần ──────────────────────────────────────────────────────────
def moi_thanh_phan(c: Corpus, norm_id: str) -> list[Component]:
    """≡ `(n:Norm)-[:HAS_PART*]->(c:Component)` — MỌI thành phần, mọi độ sâu.

    Khử trùng là bắt buộc, không phải phòng xa: `Q_COMP` phải `WITH DISTINCT` vì
    "đo thật: có Điều 7 đường đi". `comp_theo_norm` khoá theo `component_id` nên
    đã khử sẵn — hàm này tồn tại để chỗ gọi KHÔNG tự viết lại vòng lặp và đánh rơi
    tính chất đó.
    """
    return [c.components[cid] for cid in c.comp_theo_norm.get(norm_id, ())]


def con_truc_tiep(c: Corpus, norm_id: str) -> list[Component]:
    """≡ `(n:Norm)-[:HAS_PART]->(c:Component)` — MỘT bước, chỉ cấp cao nhất.

    Khác `moi_thanh_phan` đúng ở chỗ này: một văn bản có 20 Điều và 300 Khoản thì
    hàm này trả 20, hàm kia trả 320. `g7_content.BAY_KHAC_VB` dùng bản một-bước.
    """
    return [x for x in moi_thanh_phan(c, norm_id) if x.parent_id is None]


def hau_due(c: Corpus, component_id: str) -> list[Component]:
    """Toàn bộ cây con dưới `component_id`, KHÔNG gồm chính nó.

    Duyệt có tập `da_tham`: đồ thị nguồn không phải cây thuần, để nguyên thì một
    node đến được theo nhiều đường sẽ vào kết quả nhiều lần (§10.3d — đúng lỗi
    'FETCH duyệt trùng đường đi' đã báo cho nhóm legal-rag).
    """
    goc = c.components.get(component_id)
    if goc is None:
        return []
    con_theo_cha: dict[str, list[Component]] = {}
    for x in moi_thanh_phan(c, goc.norm_id):
        if x.parent_id:
            con_theo_cha.setdefault(x.parent_id, []).append(x)

    ra: list[Component] = []
    da_tham = {component_id}
    hang_doi = list(con_theo_cha.get(component_id, ()))
    while hang_doi:
        x = hang_doi.pop()
        if x.component_id in da_tham:
            continue
        da_tham.add(x.component_id)
        ra.append(x)
        hang_doi.extend(con_theo_cha.get(x.component_id, ()))
    return ra


def to_tien(c: Corpus, component_id: str) -> list[Component]:
    """Chuỗi cha từ gần tới xa. Có chặn vòng lặp — dữ liệu thật đã có chu trình."""
    ra: list[Component] = []
    da_tham = {component_id}
    x = c.components.get(component_id)
    while x is not None and x.parent_id and x.parent_id not in da_tham:
        da_tham.add(x.parent_id)
        cha = c.components.get(x.parent_id)
        if cha is None:
            break
        ra.append(cha)
        x = cha
    return ra


def cac_dieu(c: Corpus, norm_id: str) -> list[Component]:
    """Mọi Component `loai='Dieu'` của văn bản, sắp theo `thu_tu`.

    Dùng `moi_thanh_phan` (biến độ dài) chứ KHÔNG dùng `con_truc_tiep`: có văn bản
    lồng Điều dưới Chương/Mục, lấy một-bước thì mất sạch.
    """
    return sorted((x for x in moi_thanh_phan(c, norm_id) if x.loai == "Dieu"),
                  key=lambda x: (x.thu_tu, x.component_id))


def _so_dieu(stt: str | None) -> int | None:
    """'Điều 12' · '12' · '12a' -> 12. Không parse được -> None, KHÔNG đoán."""
    if not stt:
        return None
    so = ""
    for ch in str(stt):
        if ch.isdigit():
            so += ch
        elif so:
            break
    return int(so) if so else None


def so_dieu_da_dung(c: Corpus, norm_id: str) -> set[int]:
    """Tập số Điều CÓ THẬT của văn bản — G8 công thức (b) dựng trên đây."""
    return {n for x in cac_dieu(c, norm_id) if (n := _so_dieu(x.so_thu_tu)) is not None}


def so_dieu_lon_nhat(c: Corpus, norm_id: str) -> int | None:
    ds = so_dieu_da_dung(c, norm_id)
    return max(ds) if ds else None


# ── nội dung theo thời gian ─────────────────────────────────────────────────
def cac_ban(c: Corpus, component_id: str) -> list[Expression]:
    return [c.expressions[e] for e in c.expr_theo_comp.get(component_id, ())]


def ban_hien_hanh(c: Corpus, component_id: str) -> Expression | None:
    """Bản đang có hiệu lực: `hieu_luc_den IS NULL`.

    Chỉ gọi được khi `meta.theo_doi_hieu_luc = True`. Corpus không theo dõi hiệu lực
    thì `None` nghĩa là KHÔNG BIẾT, và trả về nó như "còn hiệu lực" là bịa — nên
    hàm này ném lỗi thay vì trả kết quả sai im lặng.
    """
    if not c.meta.theo_doi_hieu_luc:
        raise ValueError(
            f"corpus «{c.meta.ten}» khai theo_doi_hieu_luc=False: `hieu_luc_den=None` "
            "nghĩa là KHÔNG BIẾT, không phải 'còn hiệu lực'. Không suy hiệu lực được.")
    for e in cac_ban(c, component_id):
        if e.hieu_luc_den is None:
            return e
    return None


def hieu_luc_tai(c: Corpus, component_id: str, moc: date) -> Expression | None:
    """Bản có hiệu lực tại `moc`. Khoảng NỬA MỞ `[tu, den)` — §4.4.

    Nửa mở là toàn bộ ý nghĩa của loại `on_boundary`: hỏi ĐÚNG ngày văn bản mới có
    hiệu lực thì đáp án là văn bản MỚI. Đóng hai đầu là bug off-by-one mà chính nhóm
    G2′ được dựng ra để bắt.
    """
    for e in cac_ban(c, component_id):
        if e.hieu_luc_tu is not None and moc < e.hieu_luc_tu:
            continue
        if e.hieu_luc_den is not None and moc >= e.hieu_luc_den:
            continue
        return e
    return None


# ── tra cứu theo số hiệu ────────────────────────────────────────────────────
def norm_theo_so_hieu(c: Corpus, so_hieu: str, chuan_hoa=None) -> list[str]:
    """Mọi `norm_id` có số hiệu khớp. TRẢ DANH SÁCH, không trả một giá trị.

    Corpus thật có 228 nhóm trùng số/năm (`kiem_chat_luong`) — cùng một văn bản ghi
    nhiều cách. Trả một giá trị thì chỗ gọi im lặng bỏ mất các bản còn lại, và đáp án
    dạng danh sách bị thiếu.
    """
    if chuan_hoa is None:
        def chuan_hoa(x):
            return (x or "").strip().upper()
    dich = chuan_hoa(so_hieu)
    return [n.norm_id for n in c.norms.values() if chuan_hoa(n.so_hieu) == dich]


def khoa_nhap_nhang(c: Corpus, chuan_hoa=None) -> dict[str, list[str]]:
    """Những khoá số hiệu ứng với NHIỀU HƠN MỘT văn bản.

    Số hiệu được cơ quan ban hành đặt, và dạng cũ không mang năm nên có thể tái sử
    dụng: `90/CP` ngày 15/12/1995 và `90/CP` ngày 24/11/1993 là hai văn bản khác nhau.

    Framework KHÔNG viết lại số hiệu để làm cho nó duy nhất — bịa định danh thì câu
    hỏi trỏ vào một văn bản không tồn tại, đúng thứ cổng C1 sinh ra để chặn. Thay vào
    đó nêu ra ở đây, và bộ sinh tự quyết: nhóm nào có ĐÁP ÁN LÀ ĐỊNH DANH (G1, G4′)
    thì phải loại, vì câu hỏi không có đáp án đơn trị.

    Đo trên mẫu 3.000 văn bản thật: 6 khoá / 12 văn bản (0,2%). Nhưng đó là tính chất
    của corpus NÀY — corpus khác có thể tệ hơn nhiều, nên phải đo chứ đừng giả định.
    """
    if chuan_hoa is None:
        from . import so_hieu
        chuan_hoa = so_hieu.khoa
    gom: dict[str, list[str]] = {}
    for n in c.norms.values():
        if (k := chuan_hoa(n.so_hieu)):
            gom.setdefault(k, []).append(n.norm_id)
    return {k: v for k, v in gom.items() if len(v) > 1}


def loc_da_duyet(c: Corpus, qs: Iterable) -> list:
    """Bộ lọc `da_duyet` áp đúng chỗ: chỉ ép khi corpus khai là trích tự động."""
    if not c.meta.quan_he_tu_dong:
        return list(qs)
    return [q for q in qs if q.da_duyet is True]
