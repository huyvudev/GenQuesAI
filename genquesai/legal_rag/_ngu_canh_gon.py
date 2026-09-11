"""Ngữ cảnh GỌN — chỉ lấy đúng 2 chỗ mà tuyên bố thay thế/sửa đổi/bãi bỏ thường xuất hiện:
  1. "Căn cứ" (preamble đầu văn bản, TRƯỚC Chương/Điều/Phụ lục đầu tiên) — CHƯA BAO GIỜ
     được lưu vào Neo4j (structural_parser.py discard hẳn phần này khi ingest) -> phải đọc
     trực tiếp từ raw HTML gốc (crawl/data/raw/.../{norm_id}/toanvan.html).
  2. "Điều khoản thi hành" / "Hiệu lực thi hành" — thường là 1-2 Điều CUỐI văn bản — CÓ
     trong Neo4j nhưng bug cũ chỉ đọc node Điều (rỗng), bỏ sót Khoản/Điểm con (nơi chứa
     nội dung thật) -> lấy đúng bằng cách đọc TOÀN BỘ subtree của (các) Điều cuối.

Tránh đọc Phụ lục/toàn bộ Điều giữa (nhiễu — có thể chứa bảng dữ liệu, danh mục không
liên quan tới quan hệ ThayThe/SuaDoi/BaiBoToanBo/BaiBoTungPhan) -> bộ lọc gọn hơn, ít
nhiễu hơn nhiều so với đọc toàn văn đầy đủ.
"""
from __future__ import annotations
import os
import re

from selectolax.parser import HTMLParser

RAW_DIRS = ["tw", "mic", "most", "related", "cdi_backfill", "tvpl_backfill", "manual"]
RAW_BASE = "D:/Project/Chatbot-Law/crawl/data/raw"

RE_PHAN = re.compile(r"^Phần\s+(?:thứ\s+)?(.+?)\s*$", re.IGNORECASE)
RE_CHUONG = re.compile(r"^Chương\s+([IVXLCDM]+|\d+)\b\.?\s*(.*)$", re.IGNORECASE)
RE_MUC = re.compile(r"^Mục\s+(\d+)\b\.?\s*(.*)$", re.IGNORECASE)
RE_DIEU = re.compile(r"^Điều\s+(\d+[a-zđ]?)\s*[.\-–:]?\s*(.*)$")
RE_PHU_LUC = re.compile(r"^PHỤ\s*LỤC(?:\s+SỐ)?\s*([IVXLCDM]+|\d+[A-Za-zĐ]?)?\b\.?\s*(.*)$")


def _norm(t: str) -> str:
    return re.sub(r"\s+", " ", (t or "")).strip()


def _tim_raw_html(norm_id: str) -> str | None:
    for d in RAW_DIRS:
        p = os.path.join(RAW_BASE, d, norm_id, "toanvan.html")
        if os.path.exists(p):
            return p
    return None


def lay_can_cu(norm_id: str) -> str:
    """Đọc trực tiếp raw HTML, trả về đoạn PREAMBLE (Căn cứ...) trước Chương/Điều/Phụ lục
    đầu tiên. Rỗng nếu không tìm thấy raw hoặc văn bản không có preamble."""
    path = _tim_raw_html(norm_id)
    if not path:
        return ""
    try:
        html = open(path, encoding="utf-8").read()
    except Exception:
        return ""
    tree = HTMLParser(html)
    body = tree.body or tree
    lines = []
    for p in body.css("p, h1, h2, h3, h4, h5, h6"):
        t = _norm(p.text(separator=" ", strip=True))
        if not t:
            continue
        if RE_PHAN.match(t) or RE_CHUONG.match(t) or RE_MUC.match(t) or RE_DIEU.match(t) or RE_PHU_LUC.match(t):
            break
        lines.append(t)
    return "\n".join(lines)


_Q_DIEU_CUOI = """
MATCH (n:Norm {norm_id:$nid})-[:HAS_PART*]->(d:Component {loai:'Dieu'})
RETURN d.duong_dan AS dd, d.tieu_de AS tieu_de, d.order_key AS ok
ORDER BY ok DESC
LIMIT 3
"""
_Q_SUBTREE = """
MATCH (n:Norm {norm_id:$nid})-[:HAS_PART*]->(d:Component)-[:HAS_VERSION]->(e:Expression)
WHERE d.duong_dan STARTS WITH $prefix
RETURN d.loai AS loai, d.duong_dan AS dd, e.text AS text, d.order_key AS ok
ORDER BY ok
"""
RE_HIEU_LUC_TITLE = re.compile(r"hiệu\s+lực|điều\s+khoản\s+thi\s+hành|tổ\s+chức\s+thực\s+hiện", re.IGNORECASE)


def lay_dieu_khoan_thi_hanh(neo, norm_id: str) -> str:
    """Lấy toàn bộ subtree (Điều + Khoản + Điểm con) của Điều CUỐI văn bản — ưu tiên Điều
    có tiêu đề khớp 'hiệu lực'/'điều khoản thi hành'/'tổ chức thực hiện' trong 3 Điều cuối,
    nếu không có thì lấy đúng Điều cuối cùng."""
    dieu_cuoi = neo.run(_Q_DIEU_CUOI, nid=norm_id)
    if not dieu_cuoi:
        return ""
    target = None
    for r in dieu_cuoi:
        if r["tieu_de"] and RE_HIEU_LUC_TITLE.search(r["tieu_de"]):
            target = r
            break
    if target is None:
        target = dieu_cuoi[0]

    rows = neo.run(_Q_SUBTREE, nid=norm_id, prefix=target["dd"])
    lines = [f"[{target['dd']}. {target['tieu_de'] or ''}]"]
    for r in rows:
        if r["text"]:
            lines.append(f"[{r['dd']}] {r['text']}")
    return "\n".join(lines)


def lay_ngu_canh_gon(neo, norm_id: str) -> str:
    can_cu = lay_can_cu(norm_id)
    thi_hanh = lay_dieu_khoan_thi_hanh(neo, norm_id)
    out = []
    if can_cu:
        out.append("=== CĂN CỨ ===\n" + can_cu)
    if thi_hanh:
        out.append("=== ĐIỀU KHOẢN THI HÀNH ===\n" + thi_hanh)
    return "\n\n".join(out)


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    sys.path.insert(0, "D:/Project/GenQuesAI")
    from genquesai.legal_rag.config import get_settings
    from genquesai.legal_rag.graph.client import Neo4jClient
    s = get_settings()
    neo = Neo4jClient(s)
    print(lay_ngu_canh_gon(neo, "133548"))
