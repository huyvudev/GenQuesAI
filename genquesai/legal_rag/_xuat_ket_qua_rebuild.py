"""Xuat ket qua rebuild ra 2 file:
1. `_da_khop.csv` — 73.809 canh da tu dong duyet (da_duyet=true), khong can ra tay.
2. `_can_ra.xlsx` — 98.287 canh mismatch/only_llm can nguoi duyet, 3 sheet theo loai
   canh (REPLACES len dau vi anh huong domino nang nhat, roi AMENDS, roi GUIDED_BY),
   trong moi sheet nhom/sap theo VB nguon. Co cot rong "QUYET DINH" de user dien."""
from __future__ import annotations
import csv
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, "D:/Project/GenQuesAI")

from genquesai.legal_rag.config import get_settings
from genquesai.legal_rag.graph.client import Neo4jClient
from genquesai.legal_rag.ingestion.reference_extractor import _EDGE_MAP
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

HERE = Path(__file__).parent

_LOAI_VI = {"ThayThe": "THAY THẾ (REPLACES)", "SuaDoi": "SỬA ĐỔI (AMENDS)", "CanCu": "CĂN CỨ (GUIDED_BY)",
           "BaiBoToanBo": "BÃI BỎ TOÀN BỘ (REPLACES)", "BaiBoTungPhan": "BÃI BỎ TỪNG PHẦN (AMENDS)"}
_LY_DO = {"mismatch": "Nguồn lệch nhau", "only_llm": "Chỉ 1 nguồn (LLM), không đối chiếu được"}


_CAP_VI = {"Dieu": "Điều", "Khoan": "Khoản", "Diem": "Điểm"}


def _cap_dich_str(duong_dan: str | None) -> str:
    """'Dieu 5 > Khoan 2' -> 'Điều 5, Khoản 2'. Không có duong_dan (đích là cả VB,
    hoặc chưa qua bước trích cấp Điều) -> 'Cả văn bản'."""
    if not duong_dan:
        return "Cả văn bản"
    parts = []
    for seg in duong_dan.split(" > "):
        seg = seg.strip()
        for prefix, vi in _CAP_VI.items():
            if seg.startswith(prefix + " "):
                parts.append(f"{vi} {seg[len(prefix) + 1:]}")
                break
        else:
            parts.append(seg)
    return ", ".join(parts) if parts else "Cả văn bản"


def _nguon_str(raw) -> str:
    """`a.nguon` lưu dạng chuỗi JSON (vd '[\"llm\", \"regex\"]') — parse trước khi
    join, không thì `", ".join(chuoi)` sẽ tách theo TỪNG KÝ TỰ (bug thật đã phát
    hiện 2026-08-25, file đã gửi user bị lỗi cột này)."""
    if not raw:
        return ""
    try:
        return ", ".join(json.loads(raw))
    except (TypeError, ValueError):
        return str(raw)

_Q_DA_KHOP = """
MATCH (a:Action)-[:ENACTED_BY]->(src:Norm)
MATCH (a)-[:AFFECTS]->(tgt)
WHERE a.da_duyet = true
MATCH (tgt_norm:Norm {norm_id: tgt.norm_id})
RETURN src.so_hieu AS sh_nguon, a.loai AS loai, tgt_norm.so_hieu AS sh_dich,
       tgt.duong_dan AS duong_dan, a.nguon AS nguon, a.confidence AS conf
ORDER BY src.so_hieu
"""

_Q_CAN_RA = """
MATCH (a:Action)-[:ENACTED_BY]->(src:Norm)
MATCH (a)-[:AFFECTS]->(tgt)
WHERE (a.mismatch = true OR a.only_llm = true) AND NOT a.loai IN ['SuaDoi', 'BaiBoTungPhan']
      AND coalesce(a.da_duyet, false) = false
MATCH (tgt_norm:Norm {norm_id: tgt.norm_id})
RETURN a.action_id AS action_id, src.norm_id AS norm_id_nguon, src.so_hieu AS sh_nguon,
       src.tieu_de AS td_nguon, a.loai AS loai, tgt_norm.so_hieu AS sh_dich,
       tgt_norm.tieu_de AS td_dich, a.nguon AS nguon, a.mismatch AS mismatch, a.only_llm AS only_llm,
       a.ai_verify AS ai_verify
ORDER BY src.so_hieu, tgt_norm.so_hieu
"""

# AMENDS: AFFECTS co the tro vao Norm (chua qua trich cap Dieu, hoac khong resolve
# duoc) HOAC Component (Dieu/Khoan/Diem, sau _trich_cap_dieu.py) — khac _Q_CAN_RA
# (chi Norm), phai MATCH (tgt) khong ghi ro nhan, roi tra ve rieng norm_id cua tgt
# de tra cuu Norm dich (Component cung co field norm_id, xem _trich_cap_dieu.py).
_Q_AMENDS_CAN_RA = """
MATCH (a:Action)-[:ENACTED_BY]->(src:Norm)
MATCH (a)-[:AFFECTS]->(tgt)
WHERE a.loai IN ['SuaDoi', 'BaiBoTungPhan'] AND (a.mismatch = true OR a.only_llm = true)
      AND coalesce(a.da_duyet, false) = false
MATCH (tgt_norm:Norm {norm_id: tgt.norm_id})
RETURN a.action_id AS action_id, src.norm_id AS norm_id_nguon, src.so_hieu AS sh_nguon,
       src.tieu_de AS td_nguon, a.loai AS loai, tgt_norm.so_hieu AS sh_dich,
       tgt_norm.tieu_de AS td_dich, tgt.duong_dan AS duong_dan,
       a.nguon AS nguon, a.mismatch AS mismatch, a.only_llm AS only_llm, a.ai_verify AS ai_verify
ORDER BY src.so_hieu, tgt_norm.so_hieu
"""


def xuat_da_khop(neo: Neo4jClient) -> int:
    rows = neo.run(_Q_DA_KHOP)
    out_path = HERE / "_da_khop.csv"
    with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["VB nguồn", "Loại cạnh", "VB đích", "Cấp đích", "Nguồn xác nhận", "Độ tin cậy"])
        for r in rows:
            w.writerow([r["sh_nguon"], _LOAI_VI.get(r["loai"], r["loai"]), r["sh_dich"],
                       _cap_dich_str(r["duong_dan"]), _nguon_str(r["nguon"]), r["conf"]])
    print(f"Đã xuất {len(rows):,} cạnh đã khớp -> {out_path}")
    return len(rows)


def xuat_can_ra(neo: Neo4jClient) -> int:
    """Nhóm sheet theo EDGE (REPLACES/AMENDS/GUIDED_BY) — quyết định domino hiệu lực
    khi duyệt — KHÔNG theo `loai` (loai giờ có 5 giá trị: ThayThe/SuaDoi/CanCu/
    BaiBoToanBo/BaiBoTungPhan, nhiều loai cùng chung 1 edge, xem `_EDGE_MAP`).
    `loai` hiển thị ở cột riêng trong mỗi sheet để phân biệt "thay thế" và "bãi bỏ".

    **AMENDS (2026-08-25):** sau khi trích cấp Điều xong (`_trich_cap_dieu.py`),
    sheet `3_AMENDS` có thêm cột "Cấp đích" (VD "Điều 5, Khoản 2" / "Cả văn bản")
    — quyết định người dùng: 1 cột gộp, sắp theo VB nguồn rồi VB đích."""
    rows = neo.run(_Q_CAN_RA)
    by_edge: dict[str, list] = {"REPLACES": [], "GUIDED_BY": []}
    for r in rows:
        edge = _EDGE_MAP.get(r["loai"])
        if edge is None or edge not in by_edge:
            continue
        by_edge[edge].append(r)
    amends_rows = neo.run(_Q_AMENDS_CAN_RA)

    wb = Workbook()
    wb.remove(wb.active)
    header = ["STT", "action_id", "VB nguồn (số hiệu)", "Tên VB nguồn", "Loại hành vi",
              "VB đích (số hiệu)", "Tên VB đích", "Lý do cần rà", "Nguồn tìm thấy",
              "AI Công vụ", "QUYẾT ĐỊNH (điền: dung / sai)"]
    bold = Font(bold=True)
    fill = PatternFill("solid", fgColor="D9E1F2")

    sheet_order = [("REPLACES", "1_REPLACES"), ("GUIDED_BY", "2_GUIDED_BY")]
    for edge, sheet_name in sheet_order:
        items = by_edge.get(edge, [])
        ws = wb.create_sheet(sheet_name)
        ws.append(header)
        for c in range(1, len(header) + 1):
            cell = ws.cell(row=1, column=c)
            cell.font = bold
            cell.fill = fill
        ws.freeze_panes = "A2"
        for i, r in enumerate(items, 1):
            ly_do = "Nguồn lệch nhau" if r["mismatch"] else "Chỉ 1 nguồn (LLM)"
            ws.append([i, r["action_id"], r["sh_nguon"], r["td_nguon"], _LOAI_VI.get(r["loai"], r["loai"]),
                      r["sh_dich"], r["td_dich"], ly_do, _nguon_str(r["nguon"]),
                      r.get("ai_verify") or "", ""])
        widths = [6, 34, 20, 46, 26, 20, 46, 22, 18, 14, 26]
        for c, w in enumerate(widths, 1):
            ws.column_dimensions[get_column_letter(c)].width = w
        print(f"  sheet {sheet_name}: {len(items):,} dòng")

    # Sheet AMENDS rieng — them cot "Cap dich"
    header_amends = ["STT", "action_id", "VB nguồn (số hiệu)", "Tên VB nguồn", "Loại hành vi",
                     "VB đích (số hiệu)", "Tên VB đích", "Cấp đích", "Lý do cần rà",
                     "Nguồn tìm thấy", "AI Công vụ", "QUYẾT ĐỊNH (điền: dung / sai)"]
    ws = wb.create_sheet("3_AMENDS")
    ws.append(header_amends)
    for c in range(1, len(header_amends) + 1):
        cell = ws.cell(row=1, column=c)
        cell.font = bold
        cell.fill = fill
    ws.freeze_panes = "A2"
    for i, r in enumerate(amends_rows, 1):
        ly_do = "Nguồn lệch nhau" if r["mismatch"] else "Chỉ 1 nguồn (LLM)"
        ws.append([i, r["action_id"], r["sh_nguon"], r["td_nguon"], _LOAI_VI.get(r["loai"], r["loai"]),
                  r["sh_dich"], r["td_dich"], _cap_dich_str(r["duong_dan"]), ly_do,
                  _nguon_str(r["nguon"]), r.get("ai_verify") or "", ""])
    widths_amends = [6, 40, 20, 46, 26, 20, 46, 20, 22, 18, 14, 26]
    for c, w in enumerate(widths_amends, 1):
        ws.column_dimensions[get_column_letter(c)].width = w
    print(f"  sheet 3_AMENDS: {len(amends_rows):,} dòng")

    out_path = HERE / "_can_ra.xlsx"
    wb.save(out_path)
    tong = sum(len(v) for v in by_edge.values()) + len(amends_rows)
    print(f"Đã xuất {tong:,} cạnh cần rà (REPLACES+GUIDED_BY+AMENDS) -> {out_path}")
    return tong


def main() -> None:
    s = get_settings()
    s_local = s.model_copy(update={
        "neo4j_uri": "bolt://localhost:7687", "neo4j_user": "neo4j",
        "neo4j_password": "123qwe", "neo4j_database": "neo4j",
    })
    neo = Neo4jClient(s_local)
    neo.verify()
    n1 = xuat_da_khop(neo)
    n2 = xuat_can_ra(neo)
    print(f"\nTỔNG: {n1:,} đã khớp + {n2:,} cần rà = {n1 + n2:,}")


if __name__ == "__main__":
    main()
