"""Schema corpus trung gian — hợp đồng ĐẦU VÀO của framework.

Đặc tả: `framework/corpus-schema.md`. Mọi kho văn bản QPPL map vào đây, bộ sinh chỉ
làm việc với schema này chứ không biết gì về Neo4j/SQL/JSONL bên dưới.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import date
from enum import Enum
from typing import Iterator, Literal, Protocol


class LoaiQuanHe(str, Enum):
    THAY_THE = "thay_the"      # A thay thế B  -> B hết hiệu lực
    SUA_DOI = "sua_doi"        # A sửa đổi/bổ sung B -> B còn, nội dung đổi
    BAI_BO = "bai_bo"          # A bãi bỏ B (một phần hoặc toàn bộ)
    HUONG_DAN = "huong_dan"    # A hướng dẫn thi hành B
    CAN_CU = "can_cu"          # A viện dẫn B làm căn cứ — KHÔNG tác động tới B
    HOP_NHAT = "hop_nhat"

    @classmethod
    def tac_dong(cls) -> set["LoaiQuanHe"]:
        """Các loại THỰC SỰ tác động tới văn bản đích.

        `CAN_CU` bị loại ở đây và đó là điểm quan trọng nhất của enum này: trong corpus
        thật nó chiếm 59% quan hệ đã duyệt, gộp vào thì quá nửa đáp án "văn bản nào đã
        tác động tới X" sẽ là những văn bản chỉ VIỆN DẪN X — sai một cách trông rất
        hợp lý, và không phát hiện được từ bên ngoài.
        """
        return {cls.THAY_THE, cls.SUA_DOI, cls.BAI_BO}


class NguonQuanHe(str, Enum):
    """Quan hệ này TỪ ĐÂU RA — khác với nó NÓI GÌ (`LoaiQuanHe`).

    Cùng một `LoaiQuanHe.THAY_THE` có thể đến từ hai chỗ hoàn toàn khác nhau, và bộ
    sinh phân biệt chúng: **G1 chỉ dùng cạnh có sẵn, G4′ chỉ dùng bản trích tự động**.

        CANH     `(a)-[:REPLACES]->(b)` — cạnh đã có trong nguồn, đã biên tập
        TU_DONG  `(a)<-[:ENACTED_BY]-(Action{loai:'ThayThe'})-[:AFFECTS]->(b)`
                 — trích bằng LLM, mang `do_tin`/`da_duyet`

    Trước khi có trường này, hai nguồn bị gộp thành một giá trị enum và chỉ tách được
    bằng dấu hiệu gián tiếp `do_tin is None`. Proxy đó ĐÚNG với `Neo4jLoader` nhưng
    không phải hợp đồng: loader khác hoàn toàn có thể gán `do_tin` cho cạnh trực tiếp,
    và lúc đó G1 lặng lẽ lấy tập ứng viên của G4′ — không cổng nào thấy.

    `None` = corpus KHÔNG khai báo. Framework sẽ lùi về proxy và cảnh báo; không tự
    đoán là `CANH`, vì đoán sai thì hỏng đúng theo kiểu vừa mô tả.
    """
    CANH = "canh"
    TU_DONG = "tu_dong"


LoaiComponent = Literal["Dieu", "Khoan", "Diem", "PhuLuc", "ToanVan"]


@dataclass(slots=True)
class Norm:
    norm_id: str
    so_hieu: str
    so_hieu_tho: str | None = None       # bản gốc trước chuẩn hoá, giữ để truy vết
    loai_vb: str | None = None
    tieu_de: str | None = None
    ngay_ban_hanh: date | None = None
    ngay_hieu_luc: date | None = None
    cap_bac: int | None = None
    co_quan_ban_hanh: str | None = None
    nguon_url: str | None = None


@dataclass(slots=True)
class Component:
    component_id: str
    norm_id: str
    loai: LoaiComponent
    parent_id: str | None = None
    so_thu_tu: str | None = None
    tieu_de: str | None = None
    thu_tu: int = 0


@dataclass(slots=True)
class Expression:
    expression_id: str
    component_id: str
    text: str                            # NGUYÊN VĂN — không tóm tắt, không sửa
    hieu_luc_tu: date | None = None
    hieu_luc_den: date | None = None     # ý nghĩa của None phụ thuộc CorpusMeta


@dataclass(slots=True)
class QuanHe:
    loai: LoaiQuanHe
    tu_norm_id: str
    den_norm_id: str
    ngay_hieu_luc: date | None = None
    do_tin: float | None = None
    da_duyet: bool | None = None
    pham_vi: str | None = None
    nguon: NguonQuanHe | None = None     # None = corpus không khai; xem NguonQuanHe


@dataclass(slots=True)
class DieuKhoanChuyenTiep:
    rule_id: str
    norm_id: str
    dieu_kien: str
    ap_dung: str
    nguon_component_id: str | None = None
    do_tin: float | None = None
    da_duyet: bool | None = None


@dataclass(slots=True)
class Chunk:
    """Đường nhanh TUỲ CHỌN — chỉ dùng khi corpus và hệ được đo chung không gian id."""
    chunk_id: str
    expression_id: str
    part: int
    text: str


@dataclass(slots=True)
class CorpusMeta:
    ten: str
    ngay_chot: date | None = None
    theo_doi_hieu_luc: bool = False
    """True  -> `hieu_luc_den = None` nghĩa là CÒN hiệu lực.
    False -> nghĩa là KHÔNG BIẾT.

    Cùng một giá trị, hai nghĩa ngược nhau. Đoán sai thì sinh ra hàng loạt câu khẳng
    định hiệu lực cho một corpus vốn không theo dõi điều đó — và không có cách nào
    phát hiện từ kết quả. Khai False thì framework tự tắt nhóm G2′."""
    quan_he_tu_dong: bool = False        # True -> bắt buộc lọc do_tin/da_duyet
    nguon: str | None = None
    ghi_chu: str | None = None


@dataclass
class Corpus:
    """Toàn bộ corpus đã nạp vào bộ nhớ, kèm chỉ mục để bộ sinh dùng."""
    meta: CorpusMeta
    norms: dict[str, Norm] = field(default_factory=dict)
    components: dict[str, Component] = field(default_factory=dict)
    expressions: dict[str, Expression] = field(default_factory=dict)
    quan_he: list[QuanHe] = field(default_factory=list)
    chuyen_tiep: list[DieuKhoanChuyenTiep] = field(default_factory=list)
    chunks: dict[str, Chunk] = field(default_factory=dict)

    # chỉ mục dựng sau khi nạp
    comp_theo_norm: dict[str, list[str]] = field(default_factory=dict)
    expr_theo_comp: dict[str, list[str]] = field(default_factory=dict)
    qh_theo_dich: dict[str, list[QuanHe]] = field(default_factory=dict)

    def dung_chi_muc(self) -> None:
        self.comp_theo_norm.clear()
        self.expr_theo_comp.clear()
        self.qh_theo_dich.clear()
        for c in self.components.values():
            self.comp_theo_norm.setdefault(c.norm_id, []).append(c.component_id)
        for e in self.expressions.values():
            self.expr_theo_comp.setdefault(e.component_id, []).append(e.expression_id)
        for q in self.quan_he:
            self.qh_theo_dich.setdefault(q.den_norm_id, []).append(q)

    def __repr__(self) -> str:
        return (f"<Corpus {self.meta.ten}: {len(self.norms):,} VB · "
                f"{len(self.components):,} thành phần · "
                f"{len(self.expressions):,} nội dung · "
                f"{len(self.quan_he):,} quan hệ>")


class CorpusLoader(Protocol):
    """Hợp đồng nạp. Viết một lớp cho mỗi nguồn: Neo4j, SQL, JSONL…"""

    def meta(self) -> CorpusMeta: ...
    def norms(self) -> Iterator[Norm]: ...
    def components(self) -> Iterator[Component]: ...
    def expressions(self) -> Iterator[Expression]: ...
    def quan_he(self) -> Iterator[QuanHe]: ...

    def chuyen_tiep(self) -> Iterator[DieuKhoanChuyenTiep]:
        return iter(())

    def chunks(self) -> Iterator[Chunk]:
        return iter(())


def nap(loader: CorpusLoader) -> Corpus:
    c = Corpus(meta=loader.meta())
    for n in loader.norms():
        c.norms[n.norm_id] = n
    for x in loader.components():
        c.components[x.component_id] = x
    for e in loader.expressions():
        c.expressions[e.expression_id] = e
    c.quan_he = list(loader.quan_he())
    c.chuyen_tiep = list(loader.chuyen_tiep())
    for ch in loader.chunks():
        c.chunks[ch.chunk_id] = ch
    c.dung_chi_muc()
    return c


# ── (de)serialise ───────────────────────────────────────────────────────────
def _ngay(v) -> date | None:
    if v is None or v == "":
        return None
    if isinstance(v, date):
        return v
    if hasattr(v, "to_native"):          # neo4j.time.Date
        return v.to_native()
    return date.fromisoformat(str(v)[:10])


def sang_dict(x) -> dict:
    d = asdict(x)
    for k, v in d.items():
        if isinstance(v, date):
            d[k] = v.isoformat()
        elif isinstance(v, Enum):
            d[k] = v.value
    return {k: v for k, v in d.items() if v is not None}
