"""Structural parser ★ — bóc cây Phần/Chương/Mục/Điều/Khoản/Điểm từ toanvan.html.

Cấu trúc thật vbpl.vn (đã verify trên Luật 94/2025/QH15):
- Nội dung nằm trong các <p>; phần header (QUỐC HỘI, số hiệu…) nằm trong <div> -> tự bỏ qua.
- Tiêu đề cấp bậc: "Chương I" + dòng tên chương (in hoa), "Điều N. <tiêu đề>".
- Khoản: "N. …"  ·  Điểm: "x) …"  ·  Trước Chương đầu là preamble (LUẬT, Căn cứ…) -> bỏ.

duong_dan dùng làm path trích dẫn (ARCH §4.2): Điều-gốc "Dieu 12 > Khoan 2 > Diem a";
Chương/Mục giữ path tổ chức riêng ("Chuong I", "Chuong I > Muc 1") + nối cây qua `parent`.
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field

from selectolax.parser import HTMLParser

from ..domain import LoaiComponent

# Regex áp lên text đã chuẩn hoá của từng <p>
RE_PHAN = re.compile(r"^Phần\s+(?:thứ\s+)?(.+?)\s*$", re.IGNORECASE)
RE_CHUONG = re.compile(r"^Chương\s+([IVXLCDM]+|\d+)\b\.?\s*(.*)$", re.IGNORECASE)
RE_MUC = re.compile(r"^Mục\s+(\d+)\b\.?\s*(.*)$", re.IGNORECASE)
# Hậu tố chữ: "Điều 5a" là điều CHÈN MỚI (khác Điều 5) — phải giữ 'a' để không gộp nhầm.
RE_DIEU = re.compile(r"^Điều\s+(\d+[a-zđ]?)\s*[.\-–:]?\s*(.*)$")
RE_KHOAN = re.compile(r"^(\d+[a-zđ]?)\s*[.)]\s+(.*)$")
RE_DIEM = re.compile(r"^([a-zđ])\)\s*(.*)$")
# Phụ lục: heading IN HOA (case-sensitive để KHÔNG bắt nhầm câu "…quy định tại Phụ lục 1…").
# Khớp "PHỤ LỤC", "PHỤ LỤC I", "PHỤ LỤC SỐ 1", "PHỤ LỤC 01". Phần đuôi (nếu cùng dòng) là tiêu đề.
RE_PHU_LUC = re.compile(r"^PHỤ\s*LỤC(?:\s+SỐ)?\s*([IVXLCDM]+|\d+[A-Za-zĐ]?)?\b\.?\s*(.*)$")

# Thẻ "lá" chứa text cần lấy trọn (không đi sâu): đoạn <p> + tiêu đề <h1..h6>.
# vbpl đôi khi bọc heading "Điều N."/"Chương I" trong <h2>/<h3> — phải bắt như <p>.
_LEAF_TEXT_TAGS = {"p", "h1", "h2", "h3", "h4", "h5", "h6"}


@dataclass
class ParsedComponent:
    loai: str
    so_thu_tu: str
    duong_dan: str
    parent: str | None = None
    tieu_de: str | None = None
    _lines: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n".join(self._lines).strip()

    def add(self, line: str) -> None:
        if line:
            self._lines.append(line)


def _norm(t: str) -> str:
    return re.sub(r"\s+", " ", (t or "")).strip()


def _is_data_table(table) -> bool:
    """Bảng DỮ LIỆU (định mức/biểu mẫu) -> serialize Markdown giữ hàng/cột.
    Bảng LAYOUT (vbpl bọc cả thân VB trong 1 <table>) chứa tiêu đề cấu trúc Điều/Chương/Mục/
    Phụ lục -> KHÔNG serialize, để <p> bên trong chảy bình thường (không mất cây Điều)."""
    for cell in table.css("td, th"):
        t = _norm(cell.text(separator=" ", strip=True))
        if RE_DIEU.match(t) or RE_CHUONG.match(t) or RE_MUC.match(t) or RE_PHU_LUC.match(t):
            return False
    return True


def _table_to_md(table) -> str:
    """<table> -> Markdown: mỗi hàng 1 dòng '| ô | ô |'. Dùng td.text() nên bắt được cả ô bọc
    <p> lẫn ô text-trần (32% ô trong corpus không bọc <p> -> trước đây bị mất hoàn toàn)."""
    rows = []
    for tr in table.css("tr"):
        cells = [_norm(td.text(separator=" ", strip=True)) for td in tr.css("td, th")]
        if any(cells):
            rows.append("| " + " | ".join(cells) + " |")
    return "\n".join(rows)


def _kids(node):
    """Con trực tiếp theo thứ tự (dùng .child/.next thay .css để prune được subtree)."""
    c = node.child
    while c is not None:
        yield c
        c = c.next


def _paragraphs(html: str) -> list[str]:
    tree = HTMLParser(html)
    body = tree.body or tree
    if body.css_first("p") is None and body.css_first("table") is None:
        # Fallback: VBHN / VB OCR là 1 khối <pre> (không có <p>) -> tách theo dòng vật lý.
        # Dòng gãy giữa khoản sẽ được parse_structure nối vào leaf (text thường).
        return [_norm(line) for line in body.text(separator="\n").splitlines()]
    # DFS 1 LƯỢT theo document-order, PRUNE nguyên ruột bảng-dữ-liệu. Tránh cách quét cũ O(p×sâu×
    # bảng) (VB nhiều <p> + bảng lồng nhau chậm hàng chục giây/VB). Bảng dữ liệu -> Markdown rồi bỏ
    # ruột; bảng layout -> đi vào để <p> con (tiêu đề Điều...) chảy bình thường.
    out: list[str] = []
    stack = list(_kids(body))[::-1]                 # đảo để pop LIFO giữ đúng thứ tự tài liệu
    while stack:
        n = stack.pop()
        tag = n.tag
        if tag == "table":
            if _is_data_table(n):
                md = _table_to_md(n)
                if md:
                    out.append(md)
                continue                            # prune: ruột bảng đã gộp vào Markdown
            stack.extend(list(_kids(n))[::-1])       # bảng layout: đi sâu
        elif tag in _LEAF_TEXT_TAGS:
            # <p> và tiêu đề <h1..h6>: lấy trọn text, không đi sâu. vbpl bọc "Điều N."/"Chương I"
            # trong <h2>/<h3> (chỉ chứa text-node, không element con) -> nếu đi sâu như nhánh else
            # thì text tiêu đề bị MẤT hoàn toàn (mất cây Điều + mất luôn chữ tiêu đề khỏi embedding).
            out.append(_norm(n.text(separator=" ", strip=True)))
        else:
            stack.extend(list(_kids(n))[::-1])
    return out


def parse_structure(html: str) -> list[ParsedComponent]:
    out: list[ParsedComponent] = []
    cur_phan = cur_chuong = cur_muc = cur_dieu = cur_khoan = None  # type: str | None
    leaf: ParsedComponent | None = None     # component nhận text chạy
    pending_title: ParsedComponent | None = None  # Chương/Mục đang chờ dòng tên
    started = False

    def emit(c: ParsedComponent) -> ParsedComponent:
        out.append(c)
        return c

    for raw in _paragraphs(html):
        if not raw:
            continue

        m = RE_PHU_LUC.match(raw)
        if m:
            # Phụ lục đứng NGOÀI cây Điều (con trực tiếp của Norm). Đóng mọi ngữ cảnh Điều/Chương
            # + set cur_dieu/cur_khoan=None -> dòng "1." "a)" trong bảng KHÔNG thành Khoản/Điểm rác.
            cur_phan = cur_chuong = cur_muc = cur_dieu = cur_khoan = None
            pending_title = None
            started = True
            st = m.group(1) or "1"
            dd = f"PhuLuc {st}"
            c = emit(ParsedComponent(LoaiComponent.PhuLuc, st, dd, parent=None))
            leaf = c                         # text + bảng phía sau gom vào phụ lục
            if m.group(2):
                c.tieu_de = _norm(m.group(2))
            else:
                pending_title = c            # dòng kế (tên phụ lục) làm tiêu đề
            continue

        m = RE_CHUONG.match(raw)
        if m:
            pending_title = None
            cur_muc = cur_dieu = cur_khoan = None
            leaf = None
            started = True
            st = m.group(1).upper()
            cur_chuong = f"Chuong {st}"
            c = emit(ParsedComponent(LoaiComponent.Chuong, st, cur_chuong, parent=cur_phan))
            if m.group(2):
                c.tieu_de = _norm(m.group(2))
            else:
                pending_title = c
            continue

        m = RE_MUC.match(raw)
        if m:
            pending_title = None
            cur_dieu = cur_khoan = None
            leaf = None
            started = True
            st = m.group(1)
            cur_muc = (f"{cur_chuong} > " if cur_chuong else "") + f"Muc {st}"
            c = emit(ParsedComponent(LoaiComponent.Muc, st, cur_muc, parent=cur_chuong))
            if m.group(2):
                c.tieu_de = _norm(m.group(2))
            else:
                pending_title = c
            continue

        m = RE_DIEU.match(raw)
        if m:
            pending_title = None
            cur_khoan = None
            started = True
            st = m.group(1)
            cur_dieu = f"Dieu {st}"
            parent = cur_muc or cur_chuong or cur_phan
            c = emit(ParsedComponent(LoaiComponent.Dieu, st, cur_dieu, parent=parent,
                                     tieu_de=_norm(m.group(2)) or None))
            leaf = c
            continue

        if started and cur_khoan:
            m = RE_DIEM.match(raw)
            if m:
                pending_title = None
                st = m.group(1)
                dd = f"{cur_khoan} > Diem {st}"
                c = emit(ParsedComponent(LoaiComponent.Diem, st, dd, parent=cur_khoan))
                c.add(_norm(m.group(2)))
                leaf = c
                continue

        if started and cur_dieu:
            m = RE_KHOAN.match(raw)
            if m:
                pending_title = None
                st = m.group(1)
                cur_khoan = f"{cur_dieu} > Khoan {st}"
                c = emit(ParsedComponent(LoaiComponent.Khoan, st, cur_khoan, parent=cur_dieu))
                c.add(_norm(m.group(2)))
                leaf = c
                continue

        # text thường
        if pending_title is not None:
            pending_title.tieu_de = raw
            pending_title = None
            continue
        if leaf is not None:
            leaf.add(raw)
        # else: preamble / ngoài cấu trúc -> bỏ

    return out
