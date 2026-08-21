"""CDI · validation gate — chặn VB rác TRƯỚC khi vào graph production (CDI-1b; gỡ G3).

Thuần (không DB): nhận (Norm, components) -> ValidationReport {level, errors, warnings}.
  FAIL -> KHÔNG nạp (đưa vào quarantine, gỡ raw dir để bulk-ingest không vô tình nạp lại).
  WARN -> vẫn nạp nhưng gắn cờ trong ledger (vd 0 Điều dùng fallback ToanVan).
Bắt lỗi parse THẦM LẶNG (VB 0 Điều vô hình với retrieval) ngay tại cổng.
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field
from datetime import date

from ..domain import Norm
from ..ingestion.structural_parser import ParsedComponent

# VBQPPL VN sớm nhất ~1945; chặn ngày tương lai/quá khứ phi lý (lỗi parse OCR).
_MIN_YEAR = 1945
_MAX_YEAR = 2100
# Số hiệu hợp lệ: có ít nhất 1 chữ số + 1 chữ cái (vd "94/2025/QH15", "01/NQ-CP").
_SH_OK = re.compile(r"\d.*[A-Za-zĐđ]|[A-Za-zĐđ].*\d")


@dataclass(slots=True)
class ValidationReport:
    level: str                                   # "OK" | "WARN" | "FAIL"
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """True nếu được phép nạp (OK hoặc WARN). FAIL -> False."""
        return self.level != "FAIL"

    def to_dict(self) -> dict:
        return {"level": self.level, "errors": self.errors, "warnings": self.warnings}


def _bad_year(d: date | None) -> bool:
    return d is not None and not (_MIN_YEAR <= d.year <= _MAX_YEAR)


def validate(norm: Norm, components: list[ParsedComponent]) -> ValidationReport:
    """Cổng kiểm định 1 VB đã load. Tất định, không phụ thuộc DB/LLM."""
    errors: list[str] = []
    warnings: list[str] = []

    # 1) Số hiệu — bắt buộc + định dạng tối thiểu
    sh = (norm.so_hieu or "").strip()
    if not sh:
        errors.append("thiếu số hiệu")
    elif not _SH_OK.search(sh):
        errors.append(f"số hiệu không hợp lệ: {sh!r}")
    elif sh == norm.norm_id:
        warnings.append("số hiệu = norm_id (có thể chưa chuẩn hoá)")

    # 2) Cấu trúc Điều — ca 0 Điều là lỗi parse thầm lặng (G3)
    n_dieu = sum(1 for c in components if c.loai == "Dieu")
    has_toanvan = any(c.loai == "ToanVan" for c in components)
    total_text = sum(len(c.text or "") for c in components)
    if not components or total_text < 50:
        errors.append("không có nội dung text (0 Component hoặc text quá ngắn)")
    elif n_dieu == 0 and has_toanvan:
        warnings.append("0 Điều — dùng fallback ToanVan (nên kiểm parser/định dạng nguồn)")
    elif n_dieu == 0:
        errors.append("0 Điều và không có fallback ToanVan")

    # 3) Ngày — bắt năm phi lý (lỗi OCR), cảnh báo thiếu/ngược
    if norm.ngay_ban_hanh is None and norm.ngay_hieu_luc is None:
        warnings.append("thiếu cả ngày ban hành lẫn ngày hiệu lực")
    if _bad_year(norm.ngay_ban_hanh):
        errors.append(f"ngày ban hành bất thường: {norm.ngay_ban_hanh}")
    if _bad_year(norm.ngay_hieu_luc):
        errors.append(f"ngày hiệu lực bất thường: {norm.ngay_hieu_luc}")
    if (norm.ngay_ban_hanh and norm.ngay_hieu_luc
            and norm.ngay_hieu_luc < norm.ngay_ban_hanh):
        warnings.append("ngày hiệu lực TRƯỚC ngày ban hành")

    level = "FAIL" if errors else ("WARN" if warnings else "OK")
    return ValidationReport(level, errors, warnings)
