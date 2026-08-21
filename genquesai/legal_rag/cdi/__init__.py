"""CDI — Continuous Document Integration (backbone.md §9).

Đưa VBQPPL mới + cập nhật trạng thái VB cũ vào graph+vector một cách
TỰ ĐỘNG · AN TOÀN · TÁI LẬP · CÓ KIỂM TOÁN.

Nguyên tắc giữ nguyên (ARCH §1): mọi node/cạnh do code TẤT ĐỊNH dựng
(regex + Cypher MERGE); LLM chỉ bóc nội dung điều khoản, KHÔNG quyết cấu trúc graph.

Các pha:
  CDI-1 (hashing/validation/dedup/ledger) — nền tin cậy: chống trùng + chặn rác + sổ kiểm toán.
  CDI-2 (resync)                          — đồng bộ effStatus từ nguồn, chống graph lỗi thời.
  CDI-3 (undo)                            — undo-import + prune orphan + đối soát 2 kho.
  CDI-4 (pipeline/watch)                  — orchestrator có retry + watch-folder tự nạp.
  CDI-5 (observability)                   — cdi status đọc ledger + metrics.
"""
from __future__ import annotations

from .hashing import content_hash, hash_html, normalize_text
from .validation import ValidationReport, validate
from .dedup import DupMatch, find_duplicate, near_duplicates, normalize_so_hieu

__all__ = [
    "content_hash", "hash_html", "normalize_text",
    "ValidationReport", "validate",
    "DupMatch", "find_duplicate", "near_duplicates", "normalize_so_hieu",
]
