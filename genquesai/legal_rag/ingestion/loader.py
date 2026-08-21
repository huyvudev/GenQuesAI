"""Loader — đọc 1 thư mục VB raw (crawl/data/raw/.../{id}/) -> Norm + cây Component.

Map metadata (doc.json/meta.json) sang Norm; parse toanvan.html sang Component.
VB không theo cấu trúc "Điều" (Thông tư cũ format mục) -> 1 Component 'ToanVan' chứa cả text.
"""
from __future__ import annotations
import json
from datetime import date, datetime
from pathlib import Path

from selectolax.parser import HTMLParser

from ..domain import Norm, LoaiVB, CAP_BAC
from .structural_parser import ParsedComponent, parse_structure, _paragraphs, RE_PHU_LUC

TOANVAN_LOAI = "ToanVan"  # component fallback cho VB không có cấu trúc Điều


def _date(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s).date()
    except ValueError:
        return None


def _loai_vb(doc_type: str | None, agency: str | None) -> str:
    t = (doc_type or "").strip().lower()
    ag = (agency or "").lower()
    if "hiến pháp" in t:
        return LoaiVB.HienPhap
    if "bộ luật" in t:
        return LoaiVB.BoLuat
    if t == "luật" or t.startswith("luật"):
        return LoaiVB.Luat
    if "pháp lệnh" in t:
        return LoaiVB.PhapLenh
    if "nghị quyết" in t:
        if "thường vụ" in ag:
            return LoaiVB.NghiQuyetUBTVQH
        if "chính phủ" in ag:
            return LoaiVB.NghiQuyetCP
        return LoaiVB.NghiQuyetQH
    if t == "lệnh":
        return LoaiVB.Lenh
    if "nghị định" in t:
        return LoaiVB.NghiDinh
    if "quyết định" in t:
        return LoaiVB.QuyetDinhTTg if "thủ tướng" in ag else LoaiVB.QuyetDinhBo
    if "chỉ thị" in t:
        return LoaiVB.ChiThiTTg if "thủ tướng" in ag else LoaiVB.ChiThiBo
    if "liên tịch" in t:
        return LoaiVB.ThongTuLienTich
    if "thông tư" in t:
        return LoaiVB.ThongTu
    if "hợp nhất" in t:
        return LoaiVB.VanBanHopNhat
    return LoaiVB.Khac


def _full_text(html: str) -> str:
    body = HTMLParser(html).body
    return body.text(separator="\n", strip=True) if body else ""


def load_norm(doc_dir: Path) -> tuple[Norm, list[ParsedComponent]] | None:
    """Đọc 1 VB. Trả None nếu thiếu doc.json hoặc không có toàn văn text."""
    dj = doc_dir / "doc.json"
    tv = doc_dir / "toanvan.html"
    if not dj.exists():
        return None
    try:
        data = json.loads(dj.read_text(encoding="utf-8")).get("data", {})
    except Exception:
        return None

    loai = _loai_vb((data.get("docType") or {}).get("name"), data.get("agencyName"))
    norm = Norm(
        norm_id=doc_dir.name,
        so_hieu=data.get("docNum") or doc_dir.name,
        loai_vb=loai,
        cap_bac=CAP_BAC.get(loai, 9),
        co_quan_ban_hanh=data.get("agencyName"),
        ngay_ban_hanh=_date(data.get("issueDate")),
        ngay_hieu_luc=_date(data.get("effFrom")),
        tieu_de=data.get("title"),
        nguon_url=f"https://vbpl.vn/van-ban/chi-tiet/--{doc_dir.name}",
        ingested_at=datetime.now(),
    )

    comps: list[ParsedComponent] = []
    if tv.exists():
        html = tv.read_text(encoding="utf-8")
        comps = parse_structure(html)
        # content_hash trên toàn văn (CDI): dedup re-upload + phát hiện nguồn ĐỔI nội dung.
        from ..cdi.hashing import content_hash
        norm.content_hash = content_hash(_full_text(html)) or None
        # Không bóc được ĐIỀU nào (rỗng, hoặc chỉ có header Chương/Mục không text)
        # -> 1 component toàn văn để vẫn embed/truy hồi được (VB format cũ/scan/bảng).
        if not any(c.loai == "Dieu" for c in comps):
            # NHƯNG nếu có Phụ lục (VB format Mục, không Điều) thì GIỮ Phụ lục làm component riêng
            # (không thì bị nuốt vào ToanVan -> mất citation/bảng). ToanVan = thân TRƯỚC Phụ lục đầu.
            phu = [c for c in comps if c.loai == "PhuLuc"]
            if phu:
                body_lines: list[str] = []
                for p in _paragraphs(html):
                    if RE_PHU_LUC.match(p):
                        break
                    if p:
                        body_lines.append(p)
                comps = []
                if body_lines:
                    tv = ParsedComponent(TOANVAN_LOAI, "0", TOANVAN_LOAI, parent=None,
                                         tieu_de=norm.tieu_de)
                    tv.add("\n".join(body_lines))
                    comps.append(tv)
                comps += phu
            else:
                txt = _full_text(html)
                if txt:
                    comps = [ParsedComponent(TOANVAN_LOAI, "0", TOANVAN_LOAI, parent=None,
                                             tieu_de=norm.tieu_de)]
                    comps[0].add(txt)
    if not comps:
        return None  # không có nội dung text -> bỏ (scan-only sẽ xử lý OCR sau)
    return norm, comps
