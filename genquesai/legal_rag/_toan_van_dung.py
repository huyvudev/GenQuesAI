"""Hàm lấy TOÀN VĂN NGUỒN ĐÚNG — sửa lỗi phát hiện 2026-09-10: câu truy vấn cũ dùng
xuyên suốt toàn bộ đợt rà soát 2 LLM (`rasoat_2llm.py::_Q_TOAN_BO_DIEU` và mọi script
dossier sau này) chỉ lấy text gắn TRỰC TIẾP vào Component loại 'Dieu'/'ToanVan', bỏ sót
hoàn toàn text nằm ở Khoản/Điểm con — đo trên mẫu 300 VB: thiếu trung bình 83,9% nội
dung, 63,7% VB bị ảnh hưởng nặng.

Hàm này lấy TẤT CẢ Component (không lọc loai), ghép lại thành văn bản đọc được, có giữ
tiêu đề Điều (vì đó là ngữ cảnh quan trọng dù bản thân Điều không có text riêng).
"""
from __future__ import annotations

_Q_TOAN_VAN_DUNG = """
MATCH (n:Norm {norm_id:$nid})-[:HAS_PART*]->(d:Component)-[:HAS_VERSION]->(e:Expression)
RETURN d.loai AS loai, d.duong_dan AS dd, d.tieu_de AS tieu_de, e.text AS text, d.order_key AS ok
ORDER BY ok
"""


def lay_toan_van_dung(neo, norm_id: str) -> str:
    """Trả về toàn văn nguồn ĐÚNG (mọi cấp Component), format dễ đọc."""
    rows = neo.run(_Q_TOAN_VAN_DUNG, nid=norm_id)
    lines = []
    last_dieu = None
    for r in rows:
        if r["loai"] == "Dieu":
            last_dieu = r["dd"]
            tieu_de = f" {r['tieu_de']}" if r["tieu_de"] else ""
            lines.append(f"\n[{r['dd']}.{tieu_de}]")
            if r["text"]:
                lines.append(r["text"])
        else:
            lines.append(f"[{r['dd']}] {r['text'] or ''}")
    return "\n".join(lines).strip()


def do_dai_khong_rong(s: str) -> int:
    return len("".join((s or "").split()))


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    sys.path.insert(0, "D:/Project/GenQuesAI")
    from genquesai.legal_rag.config import get_settings
    from genquesai.legal_rag.graph.client import Neo4jClient
    s = get_settings()
    neo = Neo4jClient(s)
    tv = lay_toan_van_dung(neo, "133548")
    print(tv)
    print("\n--- do dai:", len(tv), "ky tu ---")
