"""Khai báo năng lực corpus — sinh được nhóm nào, bao nhiêu câu.

Đây là bước tôi ước có từ đầu. Nhóm G2 được thiết kế quanh giả định "một Component có
nhiều Expression theo thời gian", chạy trên đồ thị thật ra **0 ứng viên**, phải làm lại
cả nhóm. Bước này biến lỗi đó thành một dòng cảnh báo TRƯỚC KHI tốn công.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .schema import Corpus, LoaiQuanHe, NguonQuanHe
from . import so_hieu
from .truy_van import khoa_nhap_nhang, nguon_cua

QUOTA = {"G1": 50, "G2": 80, "G3": 60, "G4": 40, "G5": 30, "G6": 25, "G7": 90, "G8": 25}
TEN = {"G1": "thay thế văn bản", "G2": "tại một thời điểm",
       "G3": "hiệu lực dây chuyền", "G4": "lịch sử sửa đổi",
       "G5": "chuyển tiếp", "G6": "xung đột (ứng viên)",
       "G7": "nội dung điều luật", "G8": "không có đáp án"}
# Cần gấp N lần quota mới đủ chỗ chọn lọc: bộ sinh loại rất nhiều ứng viên (tiêu đề
# hỏng, không có bằng chứng, trùng văn bản…). Đo thực tế tỷ lệ sống sót ~70%.
HE_SO = 3


@dataclass
class NangLuc:
    ma: str
    ten: str
    quota: int
    ung_vien: int
    ly_do_thieu: str | None = None

    @property
    def trang_thai(self) -> str:
        if self.ly_do_thieu:
            return "khong"
        return "du" if self.ung_vien >= self.quota * HE_SO else "thieu"

    @property
    def uoc_sinh(self) -> int:
        if self.ly_do_thieu:
            return 0
        return min(self.quota, self.ung_vien // HE_SO)


def _co_quan_he(c: Corpus, loai: set[LoaiQuanHe], loc_duyet: bool,
                nguon: NguonQuanHe | None = None) -> list:
    """Đếm ứng viên ĐÚNG NHƯ bộ sinh sẽ lọc — kể cả lọc theo nguồn.

    `nguon` bắt buộc phải khớp với bộ sinh tương ứng, nếu không báo cáo năng lực nói
    "đủ 50 câu G1" trong khi bộ sinh chỉ dựng được 12: G1 chỉ nhận cạnh trực tiếp,
    còn tổng THAY_THE gộp cả nhánh trích tự động của G4′.
    """
    ra = []
    for q in c.quan_he:
        if q.loai not in loai:
            continue
        if nguon is not None and nguon_cua(q) is not nguon:
            continue
        if loc_duyet and c.meta.quan_he_tu_dong and q.da_duyet is False:
            continue
        ra.append(q)
    return ra


def danh_gia(c: Corpus) -> list[NangLuc]:
    ra: list[NangLuc] = []

    def them(ma, ung_vien, ly_do=None):
        ra.append(NangLuc(ma, TEN[ma], QUOTA[ma], ung_vien, ly_do))

    # ── G7 / G8: tầng 0, chỉ cần nội dung ──
    co_text = sum(1 for e in c.expressions.values() if len(e.text or "") >= 250)
    them("G7", co_text, None if co_text else "không Expression nào đủ dài")
    them("G8", len(c.norms) * 4, None if c.norms else "corpus rỗng")

    # ── G2′: cần hiệu lực, VÀ corpus phải khai là có theo dõi ──
    if not c.meta.theo_doi_hieu_luc:
        them("G2", 0, "meta.theo_doi_hieu_luc = false — `hieu_luc_den` rỗng nghĩa là "
                      "KHÔNG BIẾT, không phải 'còn hiệu lực'")
    else:
        dong = sum(1 for e in c.expressions.values()
                   if e.hieu_luc_den and e.hieu_luc_tu
                   and e.hieu_luc_den > e.hieu_luc_tu)
        ty = dong / max(len(c.expressions), 1)
        them("G2", dong,
             None if dong else f"chỉ {ty:.0%} điều khoản có khoảng hiệu lực đóng")

    # ── G1: quan hệ thay thế. CHỈ cạnh trực tiếp — xem NguonQuanHe ──
    tt = _co_quan_he(c, {LoaiQuanHe.THAY_THE}, True, NguonQuanHe.CANH)
    them("G1", len(tt),
         None if tt else ("không có QuanHe.THAY_THE"
                          if not _co_quan_he(c, {LoaiQuanHe.THAY_THE}, True)
                          else "mọi quan hệ THAY_THE đều là bản trích tự động — G1 "
                               "dựng trên cạnh đã biên tập, xem NguonQuanHe"))

    # ── G3: hướng dẫn + thay thế (mẹ bị thay) ──
    hd = _co_quan_he(c, {LoaiQuanHe.HUONG_DAN}, True)
    bi_thay = {q.den_norm_id for q in tt}
    day = [q for q in hd if q.den_norm_id in bi_thay]
    them("G3", len(day),
         None if day else ("không có QuanHe.HUONG_DAN" if not hd
                           else "không văn bản mẹ nào vừa được hướng dẫn vừa bị thay thế"))

    # ── G4′: lịch sử tác động. CAN_CU bị loại ở LoaiQuanHe.tac_dong(); và chỉ nhánh
    # trích tự động — cạnh REPLACES trực tiếp thuộc về G1, tính vào đây là đếm hai lần ──
    td = _co_quan_he(c, LoaiQuanHe.tac_dong(), True, NguonQuanHe.TU_DONG)
    theo_dich: dict[str, set] = {}
    for q in td:
        theo_dich.setdefault(q.den_norm_id, set()).add(q.tu_norm_id)
    nhieu = sum(1 for v in theo_dich.values() if len(v) >= 2)
    them("G4", nhieu,
         None if nhieu else ("không có QuanHe.SUA_DOI/BAI_BO/THAY_THE"
                             if not td else "không văn bản nào bị ≥2 văn bản tác động"))

    # ── G5: điều khoản chuyển tiếp ──
    ct = [t for t in c.chuyen_tiep
          if not (c.meta.quan_he_tu_dong and t.da_duyet is False)]
    them("G5", len(ct), None if ct else "corpus không có điều khoản chuyển tiếp")

    # ── G6: cần cấp bậc. KHÔNG suy từ loai_vb — thứ bậc VN có ngoại lệ ──
    co_cap = sum(1 for n in c.norms.values() if n.cap_bac is not None)
    if not co_cap:
        them("G6", 0, "không Norm nào có `cap_bac` (framework không suy từ loai_vb)")
    else:
        khac_cap = sum(1 for q in hd
                       if (a := c.norms.get(q.tu_norm_id))
                       and (b := c.norms.get(q.den_norm_id))
                       and a.cap_bac is not None and b.cap_bac is not None
                       and a.cap_bac != b.cap_bac)
        them("G6", khac_cap, None if khac_cap else "không cặp văn bản khác cấp bậc nào")

    ra.sort(key=lambda x: ({"du": 0, "thieu": 1, "khong": 2}[x.trang_thai], x.ma))
    return ra


def in_bao_cao(c: Corpus, nl: list[NangLuc]) -> None:
    print(f"\nCorpus «{c.meta.ten}»   {len(c.norms):,} văn bản · "
          f"{len(c.components):,} thành phần · {len(c.expressions):,} nội dung")
    print(f"  theo dõi hiệu lực: {'có' if c.meta.theo_doi_hieu_luc else 'KHÔNG'}"
          f"   ·   quan hệ trích tự động: "
          f"{'có → bắt buộc lọc da_duyet' if c.meta.quan_he_tu_dong else 'không'}\n")
    bieu = {"du": "✅", "thieu": "⚠️ ", "khong": "❌"}
    tong = 0
    for x in nl:
        tong += x.uoc_sinh
        so = f"{x.uoc_sinh:>3}/{x.quota}" if x.trang_thai != "khong" else "  —"
        ghi = (x.ly_do_thieu if x.ly_do_thieu
               else (f"{x.ung_vien:,} ứng viên" if x.trang_thai == "du"
                     else f"chỉ {x.ung_vien:,} ứng viên → không đủ {x.quota} câu"))
        print(f"  {bieu[x.trang_thai]} {x.ma:3} {so}  {x.ten:22} {ghi}")
    print(f"\n  Ước sinh {tong}/{sum(QUOTA.values())} câu.")
    if c.meta.ghi_chu:
        print(f"  ⚠️  {c.meta.ghi_chu}")
    thieu = [x.ma for x in nl if x.trang_thai == "khong"]
    if thieu:
        print(f"  Bổ sung dữ liệu để mở khoá: {', '.join(thieu)}")


# ── kiểm chất lượng lúc nạp (corpus-schema.md §7) ───────────────────────────
_SO_HIEU = re.compile(r"\d+[a-zA-Z]?/\d{4}/[A-ZĐ][A-ZĐ0-9\-]*")
_SO_NAM = re.compile(r"^(\d+[a-zA-Z]?/\d{4})")


def kiem_chat_luong(c: Corpus) -> list[str]:
    """Mỗi mục dưới đây là một lỗi ĐÃ GẶP THẬT trên dữ liệu, không phải phòng xa."""
    canh: list[str] = []

    # Dùng bộ đọc của framework, KHÔNG dùng `_SO_HIEU` cũ: mẫu cũ đòi năm 4 chữ số nên
    # báo "không parse được" cho 46% kho, trong khi phần lớn số đó đọc được bình thường.
    # Cảnh báo sai chỗ còn tệ hơn không cảnh báo — nó dẫn người ta đi sửa dữ liệu lành.
    xau = [n.so_hieu or n.norm_id for n in c.norms.values() if not so_hieu.khoa(n.so_hieu)]
    if xau:
        canh.append(f"{len(xau):,} văn bản có `so_hieu` không đọc được "
                    f"(vd {xau[:3]}) — sẽ bị loại khi sinh")

    # Số hiệu dùng lại: `90/CP` ngày 15/12/1995 và `90/CP` ngày 24/11/1993 là HAI văn
    # bản. Nhóm nào có đáp án là định danh (G1, G4′) không dùng được chúng.
    nn = khoa_nhap_nhang(c, so_hieu.khoa)
    if nn:
        vd = list(nn)[:3]
        co_ngay = sum(1 for ids in nn.values()
                      for i in ids if (x := c.norms.get(i)) and x.ngay_ban_hanh)
        tong = sum(len(v) for v in nn.values())
        canh.append(
            f"{len(nn):,} số hiệu ứng với NHIỀU văn bản ({tong:,} văn bản, vd {vd}) — "
            f"câu hỏi có đáp án là định danh sẽ không đơn trị. "
            + (f"{co_ngay}/{tong} có `ngay_ban_hanh` để phân biệt"
               if co_ngay else "KHÔNG có `ngay_ban_hanh` để phân biệt — buộc phải loại"))

    # Chiều THAY_THE: bên thay phải MỚI HƠN bên bị thay.
    nguoc = 0
    for q in c.quan_he:
        if q.loai is not LoaiQuanHe.THAY_THE:
            continue
        a, b = c.norms.get(q.tu_norm_id), c.norms.get(q.den_norm_id)
        if a and b and a.ngay_hieu_luc and b.ngay_hieu_luc \
                and a.ngay_hieu_luc <= b.ngay_hieu_luc:
            nguoc += 1
    if nguoc:
        canh.append(f"{nguoc:,} cạnh THAY_THE có bên thay KHÔNG mới hơn bên bị thay "
                    f"— lỗi dữ liệu, phải loại chứ không dùng làm đáp án")

    rac = sum(1 for e in c.expressions.values()
              if e.hieu_luc_den and e.hieu_luc_den.year > 2100)
    if rac:
        canh.append(f"{rac:,} `hieu_luc_den` có năm > 2100 (giá trị sentinel) — loại")

    lo = sum(1 for n in c.norms.values()
             if n.tieu_de and _SO_HIEU.search(n.tieu_de))
    if lo:
        canh.append(f"{lo:,} tiêu đề văn bản CHỨA số hiệu — phải bóc trước khi dùng "
                    f"làm chủ đề câu hỏi, nếu không sẽ lộ đúng thứ cần giấu")

    gop: dict[str, set] = {}
    for n in c.norms.values():
        if m := _SO_NAM.match(n.so_hieu or ""):
            gop.setdefault(m.group(1), set()).add(n.norm_id)
    trung = sum(1 for v in gop.values() if len(v) > 1)
    if trung:
        canh.append(f"{trung:,} nhóm văn bản trùng số/năm — có thể là CÙNG một văn bản "
                    f"ghi khác cách; không gộp thì đáp án danh sách bị trùng")

    khong_nd = sum(1 for cid in c.components if not c.expr_theo_comp.get(cid))
    if khong_nd:
        canh.append(f"{khong_nd:,} thành phần không có nội dung nào")

    return canh
