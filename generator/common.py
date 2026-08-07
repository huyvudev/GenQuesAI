"""Tiện ích dùng chung cho bộ sinh câu hỏi eval.

Nguyên tắc (Mục 2 của giai-phap-sinh-cau-hoi-eval.md): mọi thứ trong file này đều
DETERMINISTIC. Không có lời gọi LLM nào ở tầng sinh sự thật.
"""
from __future__ import annotations

import hashlib
import io
import os
import re
import sys
import uuid
from pathlib import Path

_stdout_da_boc = False


def setup_stdout() -> None:
    """Console Windows mặc định cp1252 -> chữ Việt vỡ. Bọc lại UTF-8.

    Phải idempotent: nhiều module `run_*` import lẫn nhau, bọc hai lần thì lớp bị bỏ
    sẽ đóng luôn buffer bên dưới -> 'I/O operation on closed file'.
    """
    global _stdout_da_boc
    if _stdout_da_boc:
        return
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    _stdout_da_boc = True

# Code của hệ RAG nằm ở repo khác; nạp bằng đường dẫn thay vì cài đặt.
LEGAL_RAG_ROOT = Path(os.environ.get("LEGAL_RAG_ROOT", r"D:\Project\Chatbot-Law\chatbot"))
if str(LEGAL_RAG_ROOT) not in sys.path:
    sys.path.insert(0, str(LEGAL_RAG_ROOT))


def nap_env() -> None:
    """Đổ `.env` của legal-rag vào os.environ.

    `Settings` bên đó đọc `.env` TƯƠNG ĐỐI theo cwd. Chạy từ repo này thì cwd khác nên
    nó im lặng dùng giá trị mặc định — Neo4j sai mật khẩu, LLM thiếu api_key. Truyền
    `_env_file` chỉ chữa được chỗ nào ta tự khởi tạo Settings; những chỗ dùng
    `get_settings()` bên trong (agent/graph, embedder, reranker…) thì không với tới.
    Đổ vào môi trường là cách duy nhất phủ hết. KHÔNG ghi đè biến đã có sẵn.
    """
    f = LEGAL_RAG_ROOT / ".env"
    if not f.exists():
        return
    for dong in f.read_text(encoding="utf-8").splitlines():
        dong = dong.strip()
        if not dong or dong.startswith("#") or "=" not in dong:
            continue
        k, v = dong.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


nap_env()

# ── point_id ────────────────────────────────────────────────────────────────
# Chép nguyên văn từ legal_rag/retrieval/index.py:16,38-42. KHÔNG import trực tiếp
# vì module đó kéo theo embedder (torch/bge-m3) — nặng và không cần cho việc sinh đề.
# verify_point_id() đối chiếu lại với index thật để bản chép không lệch âm thầm.
_NS = uuid.uuid5(uuid.NAMESPACE_URL, "legal-rag/expr")


def point_id(expr_id: str, part: int = 0) -> str:
    key = expr_id if part == 0 else f"{expr_id}#{part}"
    return str(uuid.uuid5(_NS, key))


def verify_point_id(store, sample: int = 20) -> tuple[int, int]:
    """Đối chiếu point_id tự tính với id thật trong Qdrant (§9 — nghiệm thu).

    Trả (số khớp, số kiểm). Lệch  ->  bản chép đã lỗi thời, DỪNG sinh đề.
    """
    pts, _ = store.client.scroll(store.collection, with_payload=True,
                                 with_vectors=False, limit=sample)
    khop = 0
    for p in pts:
        pl = p.payload or {}
        if point_id(pl.get("expr_id", ""), pl.get("part", 0)) == str(p.id):
            khop += 1
    return khop, len(pts)


# ── chuẩn hoá số hiệu ───────────────────────────────────────────────────────
# Dữ liệu thật không đồng nhất: "52/2024/NĐ-CP" nhưng cũng "Thông tư 38/2024/TT-BYT".
# Chấm exact-match phải so trên phần lõi, nếu không sẽ báo sai hàng loạt.
# Đuôi có thể chứa CHỮ SỐ: 'QH15', 'QH12'. Thiếu \d ở lớp ký tự thì '03/2022/QH15'
# bị cắt còn '03/2022/QH' — số hiệu sai, và exact-match sẽ báo sai toàn bộ nhóm Luật.
_SO_HIEU = re.compile(r"\d+[a-zA-Z]?/\d{4}/[A-ZĐ][A-ZĐ0-9\-]*", re.UNICODE)


def core_so_hieu(so_hieu: str | None) -> str | None:
    """'Thông tư 38/2024/TT-BYT' -> '38/2024/TT-BYT'. Không khớp -> None."""
    if not so_hieu:
        return None
    m = _SO_HIEU.search(so_hieu)
    return m.group(0) if m else None


# Bản KHÔNG phân biệt hoa thường — dùng để PHÁT HIỆN rò rỉ, không để trích chuẩn.
# Dữ liệu thật có cả 'nđ-cp' viết thường; dùng core_so_hieu() để canh rò rỉ thì lọt.
_SO_HIEU_I = re.compile(r"\d+[a-zA-Z]?/\d{4}/[A-ZĐ][A-ZĐ0-9\-]*", re.IGNORECASE)


def co_so_hieu(s: str | None) -> bool:
    return bool(s and _SO_HIEU_I.search(s))


# Tiêu đề Norm có dạng: "Thông tư số 12/2016/TT-BTTTT Quy định về việc chỉ định ..."
# -> CHỨA SỐ HIỆU, phải bóc trước khi dùng làm chủ đề cho câu `situation`.
_BOC_SH = re.compile(r"^.*?\d+[a-zA-Z]?/\d{4}/[A-ZĐ][A-ZĐ0-9\-]*\s*", re.S)
_BOC_DAU = re.compile(r"^(?:quy định|hướng dẫn|ban hành|sửa đổi[^ ]*|về|việc)\s+",
                      re.IGNORECASE)


def chu_de_tu_norm(tieu_de: str | None) -> str | None:
    """'Thông tư số 12/2016/TT-BTTTT Quy định về việc chỉ định phòng thử nghiệm…'
    -> 'chỉ định phòng thử nghiệm…'. Dùng để phân biệt chủ đề mà KHÔNG lộ số hiệu.

    Trả None nếu bóc xong vẫn còn số hiệu hoặc quá ngắn -> bỏ phần định hướng chủ đề.
    """
    if not tieu_de:
        return None
    s = _BOC_SH.sub("", tieu_de.strip()).strip(' "\'')
    for _ in range(3):
        s2 = _BOC_DAU.sub("", s).strip()
        if s2 == s:
            break
        s = s2
    if len(s) > 90:
        s = s[:90].rsplit(" ", 1)[0]
    # Cắt đuôi từ nối bị hụt sau khi truncate: "…của Chính phủ" -> "…của" đọc rất kỳ.
    s = re.sub(r"\s+(?:của|và|về|cho|trong|theo|tại|đối với|thuộc)$", "", s).strip()
    if len(s) < 12 or co_so_hieu(s):
        return None
    return s[:1].lower() + s[1:]


# ── hash nội dung ───────────────────────────────────────────────────────────
# Cùng cách chuẩn hoá với legal_rag/cdi/hashing.py để hai bên so được với nhau.
_WS = re.compile(r"\s+")


def content_hash(text: str) -> str:
    norm = _WS.sub(" ", (text or "").strip())
    return hashlib.sha256(norm.encode("utf-8")).hexdigest() if norm else ""


# ── kết nối ─────────────────────────────────────────────────────────────────
# Settings của legal-rag đọc `.env` tương đối theo cwd. Chạy từ repo này thì cwd
# khác -> phải trỏ thẳng vào file, nếu không nó im lặng dùng mật khẩu mặc định.
def _settings():
    from legal_rag.config import Settings
    return Settings(_env_file=str(LEGAL_RAG_ROOT / ".env"))


def open_neo4j():
    from legal_rag.graph.client import Neo4jClient
    return Neo4jClient(settings=_settings())


def open_qdrant():
    from legal_rag.retrieval.qdrant_store import QdrantStore
    try:
        return QdrantStore(settings=_settings())
    except TypeError:
        return QdrantStore()          # bản cũ không nhận tham số settings
