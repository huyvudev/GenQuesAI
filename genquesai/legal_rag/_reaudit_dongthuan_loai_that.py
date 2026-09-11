"""Re-audit nhóm "đồng thuận cao, đồng thuận về 1 LOẠI THẬT cụ thể" (3.906 cạnh —
phần còn lại của 16.671 "đồng thuận cao" sau khi trừ 12.765 đồng thuận KhongLienQuan
đã xử lý ở nhóm A). Nhóm này bị revoke từ đợt đầu (2026-09-08, _sua_dong_thuan_2llm.py)
dựa trên ngữ cảnh CŨ (thiếu 84% nội dung) — CHƯA từng được re-audit lại.

Dùng lại đúng hạ tầng của _reaudit_thi_hanh.py (ngữ cảnh gọn: Căn cứ + Điều khoản thi
hành, cùng 2 model, cùng cơ chế batch).

Chạy: cd genquesai/legal_rag && python _reaudit_dongthuan_loai_that.py [workers]
"""
from __future__ import annotations
import json
import sys
from collections import defaultdict

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, "D:/Project/GenQuesAI")
sys.path.insert(0, ".")

from genquesai.legal_rag.config import get_settings
from genquesai.legal_rag.graph.client import Neo4jClient
import _reaudit_thi_hanh as base

base.LOG_PATH = "_reaudit_dongthuan_loai_that_log.jsonl"

_Q_ACTION_INFO = """
MATCH (a:Action {action_id:$aid})-[:ENACTED_BY]->(src:Norm)
MATCH (a)-[:AFFECTS]->(tgt)
OPTIONAL MATCH (tgt)<-[:HAS_PART*0..]-(pn:Norm) WHERE 'Component' IN labels(tgt)
WITH src, coalesce(CASE WHEN 'Norm' IN labels(tgt) THEN tgt ELSE null END, pn) AS tgt_norm
RETURN src.norm_id AS norm_id, tgt_norm.so_hieu AS target_so_hieu
"""
_Q_DA_DUYET = "MATCH (a:Action {action_id:$aid}) RETURN a.da_duyet AS da_duyet"


def gom_theo_nguon(neo) -> dict[str, list[dict]]:
    theo_nguon: dict[str, list[dict]] = defaultdict(list)
    with open("_backup_dong_thuan_2llm_20260908_221048.jsonl", encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            if r["loai_moi_de_xuat"] == "KhongLienQuan":
                continue  # da xu ly o nhom A
            rows = neo.run(_Q_DA_DUYET, aid=r["action_id"])
            if not (rows and rows[0]["da_duyet"] is False):
                continue  # chi xu ly ca da bi revoke tu dot dau, con nguyen trang thai do
            info = neo.run(_Q_ACTION_INFO, aid=r["action_id"])
            if not (info and info[0]["norm_id"] and info[0]["target_so_hieu"]):
                continue
            nid, tsh = info[0]["norm_id"], info[0]["target_so_hieu"]
            theo_nguon[nid].append({"action_id": r["action_id"], "target_so_hieu": tsh, "nhom": "D2"})
    return theo_nguon


def main(workers: int = 6) -> None:
    s = get_settings()
    neo = Neo4jClient(s)

    print("== Gom cạnh 'đồng thuận cao về loại thật' theo nguồn ==")
    theo_nguon = gom_theo_nguon(neo)
    print(f"  {sum(len(v) for v in theo_nguon.values())} cạnh, {len(theo_nguon)} nguồn riêng biệt")

    # Ghi de gom_theo_nguon cua module goc de tai su dung main() nguyen ban
    base.gom_theo_nguon = lambda: theo_nguon
    base.main(workers=workers)


if __name__ == "__main__":
    wk = int(sys.argv[1]) if len(sys.argv) > 1 else 6
    main(workers=wk)
