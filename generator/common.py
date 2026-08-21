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

from framework import so_hieu as _sh
from framework.config import legal_rag_root

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

# Hệ RAG ĐANG ĐƯỢC ĐO (system under test) nằm ở repo khác; nạp bằng đường dẫn thay vì
# cài đặt. Chỉ dùng cho đường ĐO (evaluate/ask_full.py --adapter legal_rag, generator/
# paraphrase.py cũ) — import package `legal_rag` TRẦN qua sys.path.
# Nguồn giá trị: framework/config.py (ROADMAP C — cấu hình bằng file, biến môi
# trường LEGAL_RAG_ROOT vẫn ghi đè được cho CI/thử nghiệm nhanh).
#
# KHÔNG dùng đường này để đọc corpus/CDI của chính GenQuesAI — cho việc đó dùng
# `genquesai.legal_rag` (bản clone cục bộ, xem genquesai/legal_rag/__init__.py). Hai
# package cùng tên `legal_rag` trần (bản của hệ được đo, và nếu lỡ trỏ legal_rag_root
# vào chính clone này) sẽ đè lẫn nhau theo sys.path — cố tình tách tên để tránh.
LEGAL_RAG_ROOT = legal_rag_root()
if str(LEGAL_RAG_ROOT) not in sys.path:
    sys.path.insert(0, str(LEGAL_RAG_ROOT))


def nap_env() -> None:
    """Đổ `.env` của legal-rag (hệ được đo) vào os.environ.

    `Settings` bên đó đọc `.env` TƯƠNG ĐỐI theo cwd. Chạy từ repo này thì cwd khác nên
    nó im lặng dùng giá trị mặc định — Neo4j sai mật khẩu, LLM thiếu api_key. Truyền
    `_env_file` chỉ chữa được chỗ nào ta tự khởi tạo Settings; những chỗ dùng
    `get_settings()` bên trong (agent/graph, embedder, reranker…) thì không với tới.
    Đổ vào môi trường là cách duy nhất phủ hết. KHÔNG ghi đè biến đã có sẵn.

    Chỉ phục vụ đường ĐO hệ ngoài (--adapter legal_rag) — gọi lười ngay trước khi
    import `legal_rag.agent.*` thật (xem evaluate/ask_full.py::ask_full), KHÔNG gọi
    lúc nạp module này. Đọc corpus/CDI cục bộ của GenQuesAI dùng `.env` riêng ở
    `genquesai/legal_rag/.env` (xem `_settings()`) — không đụng hàm này.

    Từng gọi vô điều kiện ở cuối module (mọi nơi import `generator.common` đều dính).
    Hệ quả: `os.environ` bị nạp từ `.env` CỦA CHATBOT-LAW, và pydantic-settings ưu
    tiên os.environ hơn `_env_file` — nên `genquesai.legal_rag.config.Settings` dù đã
    trỏ `.env` riêng vẫn bị `.env` bên Chatbot-Law ghi đè ÂM THẦM (chỉ "trông" độc lập
    khi hai file tình cờ giống nhau). Đã đo bằng thực nghiệm 2026-08-21.
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
# Uỷ quyền hết cho `framework.so_hieu` — một chỗ chuẩn hoá cho cả framework.
#
# Bản cũ ở đây đòi khuôn `số/NĂM-4-CHỮ-SỐ/ký hiệu`, nên **mù 46% kho**: mọi số hiệu
# không mang năm ở giữa đều trả None và bị bộ sinh loại ở `bo_vi_so_hieu`. Đo trên mẫu
# 3.000 văn bản thật: bản cũ đọc được 1.594 (53%), bản mới 2.976 (99%) — 1.382 văn bản
# (sắc lệnh, công văn VPCP, thông tư dạng `76-TC/TCDN`) trước đây KHÔNG BAO GIỜ được hỏi.
#
# Đây là lỗi MÙ, không phải lỗi sai: bộ đề im lặng thu hẹp phạm vi rồi báo cáo như thể
# đã phủ toàn kho. Với công cụ đo chatbot của người khác thì đó là hỏng nặng hơn sai số.
def core_so_hieu(so_hieu: str | None) -> str | None:
    """'Thông tư 38/2024/TT-BYT' -> '38/2024/TT-BYT'. Không khớp -> None."""
    return _sh.trich(so_hieu)


def khoa_nhap_nhang(c) -> frozenset[str]:
    """Khoá số hiệu ứng với NHIỀU HƠN MỘT văn bản trong `Corpus`.

    Số hiệu dạng cũ không mang năm nên bị tái sử dụng: `90/CP` ngày 15/12/1995 và
    `90/CP` ngày 24/11/1993 là hai văn bản khác nhau. Nhóm nào có ĐÁP ÁN LÀ ĐỊNH DANH
    (G1: "văn bản nào thay thế X", G4′: danh sách văn bản tác động) thì câu hỏi mất
    tính đơn trị — không chấm exact-match được.

    Framework KHÔNG viết lại số hiệu cho duy nhất: bịa định danh thì câu hỏi trỏ vào
    văn bản không tồn tại. Cách xử lý là LOẠI, và khai ra ở báo cáo năng lực.

    Đo trên corpus thật: 0,2% số hiệu bị dùng lại — nhỏ nên loại là đủ. Corpus nào tỷ
    lệ này cao thì `capabilities.kiem_chat_luong()` sẽ nói, và lúc đó mới đáng dựng
    câu hỏi nêu kèm ngày ban hành.
    """
    from framework.truy_van import khoa_nhap_nhang as _kn
    return frozenset(_kn(c, _sh.khoa))


def co_so_hieu(s: str | None) -> bool:
    """Canh rò rỉ định danh trong câu `situation`.

    Bộ canh phải LỎNG HƠN bộ trích — bỏ sót ở đây nghĩa là một câu situation lọt ra
    với số hiệu nằm sẵn trong đề, và nó mồi thẳng từ khoá cho BM25 (§5.2).
    `tim_tat_ca` phủ cả dạng có năm lẫn không năm, và không phân biệt hoa thường.

    Đã đo trên 179 câu situation của bộ đề hiện tại: bản này KHÔNG đánh dấu thêm câu
    nào — nới rộng mà không sinh dương tính giả.
    """
    return bool(s and _sh.tim_tat_ca(s))


# Tiêu đề Norm có dạng: "Thông tư số 12/2016/TT-BTTTT Quy định về việc chỉ định ..."
# -> CHỨA SỐ HIỆU, phải bóc trước khi dùng làm chủ đề cho câu `situation`.
_BOC_DAU = re.compile(r"^(?:quy định|hướng dẫn|ban hành|sửa đổi[^ ]*|về|việc)\s+",
                      re.IGNORECASE)


def _boc_so_hieu(t: str) -> str:
    """Cắt bỏ phần đầu tiêu đề cho tới hết số hiệu — lặp cho tới khi hết.

    Phải LẶP: dữ liệu thật ghi số hiệu hai lần trong một tiêu đề —
    'Thông tư số 76-TC/TCDN của Bộ Tài chính số 76 TC/TCDN ngày 15…'. Cắt một lần
    thì bản thứ hai còn nguyên, và chủ đề rút ra vẫn lộ định danh.
    """
    s = t.strip()
    for _ in range(4):
        lo = _sh.trich(s)
        if not lo or (i := s.find(lo)) < 0:
            break
        s = s[i + len(lo):].strip(' "\',.-')
    return s


def chu_de_tu_norm(tieu_de: str | None) -> str | None:
    """'Thông tư số 12/2016/TT-BTTTT Quy định về việc chỉ định phòng thử nghiệm…'
    -> 'chỉ định phòng thử nghiệm…'. Dùng để phân biệt chủ đề mà KHÔNG lộ số hiệu.

    Trả None nếu bóc xong vẫn còn số hiệu hoặc quá ngắn -> bỏ phần định hướng chủ đề.
    """
    if not tieu_de:
        return None
    s = _boc_so_hieu(tieu_de)
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
# Đọc corpus/CDI CỤC BỘ của GenQuesAI — dùng bản clone `genquesai.legal_rag`, KHÔNG
# phải package `legal_rag` trần (đó là hệ được đo, xem LEGAL_RAG_ROOT ở trên). `.env`
# riêng ở genquesai/legal_rag/.env — độc lập với `.env` của repo Chatbot-Law.
_GENQUESAI_LEGAL_RAG_ENV = Path(__file__).resolve().parent.parent / "genquesai" / "legal_rag" / ".env"


def _settings():
    from genquesai.legal_rag.config import Settings
    return Settings(_env_file=str(_GENQUESAI_LEGAL_RAG_ENV))


def open_neo4j():
    from genquesai.legal_rag.graph.client import Neo4jClient
    return Neo4jClient(settings=_settings())


def open_qdrant():
    from genquesai.legal_rag.retrieval.qdrant_store import QdrantStore
    try:
        return QdrantStore(settings=_settings())
    except TypeError:
        return QdrantStore()          # bản cũ không nhận tham số settings


# ── A1: bộ sinh đọc Corpus, không đọc Cypher ────────────────────────────────
_corpus_da_nap = {}


def nap_corpus(nguon: str | None = None, im_lang: bool = False):
    """Nạp `framework.schema.Corpus` — từ thư mục JSONL, hoặc từ Neo4j nếu không có.

    Đây là ranh giới A1: từ đây trở lên, bộ sinh KHÔNG biết Neo4j tồn tại. Đổi nguồn
    (JSONL của người khác, SQL, API) chỉ cần viết thêm một loader.

    Nạp trọn vào RAM. Đo trên corpus thật (36.558 văn bản · 2,1 triệu Component ·
    557 triệu ký tự): **~2 GB**. Chấp nhận được, và đổi lại là mọi truy vấn sau đó
    chạy trong bộ nhớ thay vì round-trip xuống Neo4j — bộ sinh cũ gọi `neo.run()` hàng
    nghìn lần cho riêng phần tìm bẫy.

    Nhớ theo `nguon` vì `run_all` sinh 8 nhóm trong một tiến trình; nạp lại 8 lần thì
    mất 8 lần thời gian mà không được gì.
    """
    from framework.schema import nap
    if nguon in _corpus_da_nap:
        return _corpus_da_nap[nguon]

    if nguon:
        from framework.jsonl_loader import JsonlLoader
        loader = JsonlLoader(nguon)
    else:
        from framework.neo4j_loader import Neo4jLoader
        loader = Neo4jLoader(open_neo4j())

    if not im_lang:
        print(f"  nạp corpus từ {nguon or 'Neo4j'}…", flush=True)
    c = nap(loader)
    if not im_lang:
        print(f"  {c!r}", flush=True)
        from framework.truy_van import kiem_gia_dinh_nguon
        for x in kiem_gia_dinh_nguon(c):
            print(f"  ⚠️  {x}", flush=True)
    _corpus_da_nap[nguon] = c
    return c
