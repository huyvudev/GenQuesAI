"""Thử rule từ khóa cho nhóm "sắc thái mức độ" (cả 2 model xác nhận có quan hệ thật,
khác nhau về LOẠI cụ thể) — dựa trên phát hiện đọc tay 25 mẫu (2026-09-09):
  - Quanh câu trích dẫn có "bãi bỏ" + (không có "toàn bộ" / "thay thế" gần đó)
    -> tin BaiBoTungPhan (đúng 5/5 mẫu đọc tay).
  - Quanh câu có "thay thế" -> tin ThayThe theo đúng động từ dùng (đúng ở các mẫu kiểm tra).
  - Ngược lại (không tìm thấy tín hiệu rõ, hoặc cả 2 từ khóa cùng xuất hiện) -> KHÔNG áp
    dụng rule, để rà tay riêng.

CHỈ phân loại dựa trên khớp CHUỖI THẬT trong toàn văn nguồn quanh vị trí nhắc số hiệu
đích — không suy diễn, không gọi LLM.

Chạy: cd genquesai/legal_rag && python _rule_tu_khoa_sac_thai.py
Ghi ra: _rule_tu_khoa_ket_qua.jsonl (để xem trước khi quyết định áp dụng)
"""
from __future__ import annotations
import json
import re
import sys
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, "D:/Project/GenQuesAI")

from genquesai.legal_rag.config import get_settings
from genquesai.legal_rag.graph.client import Neo4jClient

KET_QUA_PATH = "_rasoat_2llm_deploy/rasoat_2llm_log_KETQUA.jsonl"
RETRY_PATH = "_retry_null_api_batched_log.jsonl"
CUA_SO = 400  # ky tu truoc/sau vi tri nhac so hieu dich

_Q_TOAN_VAN = """
MATCH (n:Norm {norm_id:$nid})-[:HAS_PART*]->(d:Component)-[:HAS_VERSION]->(e:Expression)
WHERE d.loai IN ['Dieu','ToanVan']
RETURN e.text AS text
ORDER BY d.order_key
"""
_Q_DA_DUYET = "MATCH (a:Action {action_id:$aid}) RETURN a.da_duyet AS da_duyet"


def gom_ung_vien_sac_thai() -> list[dict]:
    ket_qua = []
    with open(KET_QUA_PATH, encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            if "ket_qua" not in d:
                continue
            for r in d["ket_qua"]:
                if r["dong_thuan_2_model"]:
                    continue
                ds, gm = r["loai_deepseek"], r["loai_gemini"]
                if ds and gm and ds != gm and ds != "KhongLienQuan" and gm != "KhongLienQuan":
                    ket_qua.append({**r, "norm_id": d["norm_id"], "so_hieu_nguon": d["so_hieu"]})
    with open(RETRY_PATH, encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            if d.get("loi"):
                continue
            for r in d["ket_qua"]:
                ds, gm = r["loai_deepseek"], r["loai_gemini"]
                if ds and gm and ds != gm and ds != "KhongLienQuan" and gm != "KhongLienQuan":
                    ket_qua.append({**r, "norm_id": d["norm_id"], "so_hieu_nguon": d["so_hieu"]})
    return ket_qua


def _chuan_hoa(s: str) -> str:
    return re.sub(r"\s*/\s*", "/", s or "").strip()


def ap_rule(toan_van: str, so_hieu_dich: str) -> tuple[str | None, str]:
    """Tra ve (loai_de_xuat, bang_chung) hoac (None, ly_do)."""
    sh = _chuan_hoa(so_hieu_dich)
    if not sh or sh not in toan_van:
        # thu tim khong dau cach quanh dau /
        idx = -1
    else:
        idx = toan_van.find(sh)
    if idx < 0:
        return None, "khong tim thay so hieu dich trong toan van"

    window = toan_van[max(0, idx - CUA_SO):idx + len(sh) + CUA_SO].lower()
    co_bai_bo = "bãi bỏ" in window
    co_thay_the = "thay thế" in window
    co_toan_bo = "toàn bộ" in window

    if co_thay_the and not co_bai_bo:
        return "ThayThe", "co 'thay the' gan so hieu dich, khong co 'bai bo'"
    if co_bai_bo and not co_thay_the and not co_toan_bo:
        return "BaiBoTungPhan", "co 'bai bo' gan so hieu dich, khong co 'toan bo'/'thay the'"
    return None, f"tin hieu lan lon (bai_bo={co_bai_bo}, thay_the={co_thay_the}, toan_bo={co_toan_bo})"


def main() -> None:
    s = get_settings()
    neo = Neo4jClient(s)

    print("== Gom ứng viên nhóm sắc thái mức độ (còn da_duyet=true) ==")
    ung_vien = gom_ung_vien_sac_thai()
    print(f"  {len(ung_vien)} cạnh ứng viên (trước lọc trạng thái)")

    cache_toan_van: dict[str, str] = {}
    dem_ket_qua = Counter()
    dong_y_ds, dong_y_gm, khac_ca_2 = 0, 0, 0
    ket_qua_ghi = []

    for i, r in enumerate(ung_vien):
        rows = neo.run(_Q_DA_DUYET, aid=r["action_id"])
        if not (rows and rows[0]["da_duyet"] is True):
            continue
        nid = r["norm_id"]
        if nid not in cache_toan_van:
            trows = neo.run(_Q_TOAN_VAN, nid=nid)
            cache_toan_van[nid] = "\n".join(row["text"] or "" for row in trows)
        loai_de_xuat, ly_do = ap_rule(cache_toan_van[nid], r["target_so_hieu"])
        dem_ket_qua[loai_de_xuat or "KHONG_RO"] += 1
        if loai_de_xuat:
            if loai_de_xuat == r["loai_deepseek"] and loai_de_xuat == r["loai_gemini"]:
                pass
            elif loai_de_xuat == r["loai_deepseek"]:
                dong_y_ds += 1
            elif loai_de_xuat == r["loai_gemini"]:
                dong_y_gm += 1
            else:
                khac_ca_2 += 1
            ket_qua_ghi.append({**r, "loai_de_xuat_rule": loai_de_xuat, "ly_do_rule": ly_do})
        if (i + 1) % 500 == 0:
            print(f"  {i+1}/{len(ung_vien)} đã quét")

    print(f"\n  Phân loại theo rule từ khóa:")
    for k, v in dem_ket_qua.most_common():
        print(f"    {k}: {v}")
    print(f"\n  Trong số rule ra kết quả (khớp DeepSeek: {dong_y_ds}, khớp Gemini: {dong_y_gm}, "
         f"khác cả 2: {khac_ca_2})")

    with open("_rule_tu_khoa_ket_qua.jsonl", "w", encoding="utf-8") as f:
        for r in ket_qua_ghi:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"\n  Đã ghi {len(ket_qua_ghi)} ca rule có kết quả vào _rule_tu_khoa_ket_qua.jsonl")


if __name__ == "__main__":
    main()
