"""CDI · dedup — chống nạp đôi mạnh hơn so-khớp-chuỗi `so_hieu` (CDI-1; gỡ G8).

Lớp CHẶN (an toàn, không false-positive):
  (1) số hiệu CHUẨN HOÁ khớp tuyệt đối — gập nhiễu OCR khoảng trắng/dấu ("QH1 3"->"qh13").
  (2) content_hash trùng — cùng nội dung dù số hiệu/định dạng khác (re-upload).
Lớp CẢNH BÁO (advisory, không chặn):
  (3) số hiệu GẦN-GIỐNG — chỉ để chuyên gia rà; KHÔNG tự chặn vì "28/.." vs "29/.."
      là HAI VB khác nhau (chỉ lệch 1 số) — chặn mờ sẽ nuốt nhầm văn bản thật.
"""
from __future__ import annotations
import re
import unicodedata
from dataclasses import dataclass

_NONALNUM = re.compile(r"[^0-9a-z]+")


def normalize_so_hieu(s: str) -> str:
    """Chuẩn hoá số hiệu để so khớp: bỏ dấu, đ->d, hạ thường, bỏ ký tự không chữ-số.
    '29/2026/TT-BKHCN' -> '292026ttbkhcn' · 'QH1 3' -> 'qh13' · 'NĐ-CP' -> 'ndcp'."""
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.replace("đ", "d").replace("Đ", "d")
    return _NONALNUM.sub("", s.lower())


def _similar(a: str, b: str) -> float:
    """Tỉ lệ giống 0..1. RapidFuzz nếu cài, fallback difflib (không thêm dep cứng)."""
    try:
        from rapidfuzz.fuzz import ratio
        return ratio(a, b) / 100.0
    except ModuleNotFoundError:
        from difflib import SequenceMatcher
        return SequenceMatcher(None, a, b).ratio()


@dataclass(slots=True)
class DupMatch:
    kind: str            # "so_hieu" | "content"
    norm_id: str
    so_hieu: str
    score: float = 1.0


def find_duplicate(so_hieu: str, content_hash: str, existing: list[dict]) -> DupMatch | None:
    """Trả match CHẶN đầu tiên (ưu tiên số-hiệu rồi content). `existing`: list dict có
    {norm_id, so_hieu, content_hash}. None nếu không trùng -> được phép nạp."""
    nsh = normalize_so_hieu(so_hieu)
    if nsh:
        for e in existing:
            if normalize_so_hieu(e.get("so_hieu", "")) == nsh:
                return DupMatch("so_hieu", e["norm_id"], e.get("so_hieu", ""), 1.0)
    if content_hash:
        for e in existing:
            if e.get("content_hash") and e["content_hash"] == content_hash:
                return DupMatch("content", e["norm_id"], e.get("so_hieu", ""), 1.0)
    return None


def near_duplicates(so_hieu: str, existing: list[dict],
                    threshold: float = 0.9) -> list[DupMatch]:
    """Số hiệu GẦN-GIỐNG (advisory) — cảnh báo cho người rà, KHÔNG chặn nạp.
    Ngưỡng rộng tay (0.9) vì chỉ cảnh báo: '28/..' vs '29/..' (lệch 1 số) sẽ được nêu để rà."""
    nsh = normalize_so_hieu(so_hieu)
    if not nsh:
        return []
    out: list[DupMatch] = []
    for e in existing:
        esh = normalize_so_hieu(e.get("so_hieu", ""))
        if not esh or esh == nsh:
            continue
        sc = _similar(nsh, esh)
        if sc >= threshold:
            out.append(DupMatch("fuzzy", e["norm_id"], e.get("so_hieu", ""), round(sc, 3)))
    return sorted(out, key=lambda m: m.score, reverse=True)
