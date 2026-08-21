"""Dataclass mô hình miền + enum, theo schema Neo4j (ARCH §4.2).

Quy ước (ARCH §1, §13):
- Versioning ở cấp Component (Điều/Khoản/Điểm), không ở cấp Norm.
- Tình trạng hiệu lực là DERIVED (suy ra từ Expression), KHÔNG lưu cứng.
- "Ngày hết hiệu lực" do Action đóng, không đọc thẳng từ văn bản (trừ khi VB tự ghi thời hạn).
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from datetime import date, datetime
from enum import StrEnum


class LoaiVB(StrEnum):
    HienPhap = "HienPhap"
    BoLuat = "BoLuat"
    Luat = "Luat"
    NghiQuyetQH = "NghiQuyetQH"
    PhapLenh = "PhapLenh"
    NghiQuyetUBTVQH = "NghiQuyetUBTVQH"
    Lenh = "Lenh"
    NghiDinh = "NghiDinh"
    NghiQuyetCP = "NghiQuyetCP"
    QuyetDinhTTg = "QuyetDinhTTg"
    ChiThiTTg = "ChiThiTTg"
    ThongTu = "ThongTu"
    ThongTuLienTich = "ThongTuLienTich"
    QuyetDinhBo = "QuyetDinhBo"
    ChiThiBo = "ChiThiBo"
    VanBanHopNhat = "VanBanHopNhat"
    Khac = "Khac"


# Cấp bậc cho lex superior (số NHỎ = cấp CAO hơn). ARCH §4.2 cap_bac.
CAP_BAC: dict[str, int] = {
    LoaiVB.HienPhap: 1,
    LoaiVB.BoLuat: 2, LoaiVB.Luat: 2, LoaiVB.NghiQuyetQH: 2,
    LoaiVB.PhapLenh: 3, LoaiVB.NghiQuyetUBTVQH: 3, LoaiVB.Lenh: 3,
    LoaiVB.NghiDinh: 4, LoaiVB.NghiQuyetCP: 4,
    LoaiVB.QuyetDinhTTg: 5, LoaiVB.ChiThiTTg: 5,
    LoaiVB.ThongTu: 6, LoaiVB.ThongTuLienTich: 6, LoaiVB.QuyetDinhBo: 6, LoaiVB.ChiThiBo: 6,
    LoaiVB.VanBanHopNhat: 6, LoaiVB.Khac: 9,
}


class LoaiComponent(StrEnum):
    Phan = "Phan"
    Chuong = "Chuong"
    Muc = "Muc"
    Dieu = "Dieu"
    Khoan = "Khoan"
    Diem = "Diem"
    PhuLuc = "PhuLuc"


class LoaiAction(StrEnum):
    ThayThe = "ThayThe"
    SuaDoi = "SuaDoi"
    BoSung = "BoSung"
    BaiBo = "BaiBo"
    DinhChi = "DinhChi"
    KhoiPhuc = "KhoiPhuc"


class TinhTrang(StrEnum):
    ConHieuLuc = "ConHieuLuc"
    HetHieuLuc = "HetHieuLuc"
    HetHieuLucMotPhan = "HetHieuLucMotPhan"
    ChuaCoHieuLuc = "ChuaCoHieuLuc"


def _clean(d: dict) -> dict:
    """Bỏ None để Neo4j MERGE/SET gọn (Neo4j không cho property = null)."""
    return {k: v for k, v in d.items() if v is not None}


@dataclass(slots=True)
class Norm:
    norm_id: str
    so_hieu: str
    loai_vb: str
    cap_bac: int
    co_quan_ban_hanh: str | None = None
    ngay_ban_hanh: date | None = None
    ngay_hieu_luc: date | None = None
    linh_vuc: list[str] = field(default_factory=list)
    tieu_de: str | None = None
    la_chuyen_nganh: bool = False
    nguon_url: str | None = None
    ingested_at: datetime | None = None
    content_hash: str | None = None       # SHA-256 toàn văn (CDI: dedup + phát hiện nguồn đổi)

    def to_neo4j(self) -> dict:
        return _clean(asdict(self))


@dataclass(slots=True)
class Component:
    comp_id: str
    norm_id: str
    loai: str
    so_thu_tu: str
    duong_dan: str
    tieu_de: str | None = None

    def to_neo4j(self) -> dict:
        return _clean(asdict(self))


@dataclass(slots=True)
class Expression:
    expr_id: str
    comp_id: str
    text: str
    hieu_luc_tu: date | None = None
    hieu_luc_den: date | None = None      # None = đang còn hiệu lực
    action_tao: str | None = None
    action_dong: str | None = None

    def to_neo4j(self) -> dict:
        return _clean(asdict(self))


@dataclass(slots=True)
class Action:
    action_id: str
    loai: str
    ngay_hieu_luc: date
    enacted_by: str                       # norm_id ban hành hành vi
    mo_ta: str | None = None
    confidence: float = 1.0
    da_duyet: bool = False

    def to_neo4j(self) -> dict:
        return _clean(asdict(self))


@dataclass(slots=True)
class TransitionRule:
    rule_id: str
    norm_id: str
    dieu_kien_raw: str
    van_ban_ap_dung: str
    nguon_dieu_khoan: str
    dieu_kien: str | None = None          # JSON điều kiện đã cấu trúc hóa
    confidence: float = 0.0
    da_duyet: bool = False

    def to_neo4j(self) -> dict:
        return _clean(asdict(self))


def derive_tinh_trang(expr_states: list[tuple[date | None, date | None]],
                      at: date | None = None) -> TinhTrang:
    """Suy ra tình trạng hiệu lực của một Norm tại ngày `at` từ danh sách
    (hieu_luc_tu, hieu_luc_den) của các Expression. ARCH §2."""
    at = at or date.today()
    open_cnt = closed_cnt = future_cnt = 0
    for tu, den in expr_states:
        if tu and at < tu:
            future_cnt += 1
            continue
        if den is None or at < den:
            open_cnt += 1
        else:
            closed_cnt += 1
    if open_cnt and closed_cnt:
        return TinhTrang.HetHieuLucMotPhan
    if open_cnt:
        return TinhTrang.ConHieuLuc
    if closed_cnt:
        return TinhTrang.HetHieuLuc
    return TinhTrang.ChuaCoHieuLuc
