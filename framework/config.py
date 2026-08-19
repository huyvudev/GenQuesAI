"""Cấu hình cho framework — đọc từ file thay vì biến môi trường (ROADMAP C).

Thứ tự ưu tiên khi tìm `legal_rag_root` (đường dẫn tới repo `Chatbot-Law` chứa hệ RAG
cần nạp — xem `generator/common.py`):

    1. Biến môi trường `LEGAL_RAG_ROOT`, nếu có — ghi đè nhanh một lần (CI, thử
       nghiệm) mà không muốn sửa file.
    2. `genquesai.toml` ở thư mục làm việc hiện tại (đường dẫn đổi được qua biến môi
       trường `GENQUESAI_CONFIG`) — cấu hình bền, mỗi máy một bản, KHÔNG commit (xem
       `.gitignore`). Mẫu ở `genquesai.example.toml`.
    3. Không có gì cả -> mặc định sẵn trong code — framework tự cài chạy thử được
       ngay, không cấu hình cũng không lỗi (đúng tinh thần A3).
"""
from __future__ import annotations

import os
import tomllib
from functools import lru_cache
from pathlib import Path

_MAC_DINH_LEGAL_RAG_ROOT = r"D:\Project\Chatbot-Law\chatbot"


@lru_cache
def _doc_file() -> dict:
    f = Path(os.environ.get("GENQUESAI_CONFIG", "genquesai.toml"))
    if not f.exists():
        return {}
    return tomllib.loads(f.read_text(encoding="utf-8"))


def legal_rag_root() -> Path:
    if v := os.environ.get("LEGAL_RAG_ROOT"):
        return Path(v)
    v = _doc_file().get("paths", {}).get("legal_rag_root")
    return Path(v) if v else Path(_MAC_DINH_LEGAL_RAG_ROOT)
