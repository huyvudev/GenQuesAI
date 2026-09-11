"""Áp dụng verdict đọc tay 59 ca "nguồn mỏng CÓ nhắc số hiệu đích" (_verdict_mong_found.jsonl).

Logic: verdict là "GEMINI_DUNG"/"DEEPSEEK_DUNG"/"KHONG_RO" (ai đúng), không phải loại cụ
thể — suy ra hành động theo hướng A1/A2 của từng ca (xác định qua loai_deepseek/
loai_gemini gốc trong _thin_source_candidates.json):
  - Nếu bên ĐÚNG là bên nói KhongLienQuan -> REVOKE (không có quan hệ thật).
  - Nếu bên ĐÚNG là bên nói loại thật -> so với loai_hien_tai_graph: nếu KHÁC thì revoke
    + annotate loại đúng (để rà tay sau xác nhận, không tự ghi đè loai); nếu GIỐNG thì
    không cần làm gì (graph đã đúng sẵn).
  - KHONG_RO -> để nguyên.

Chạy: cd genquesai/legal_rag && python _ap_dung_verdict_mong_found.py [--apply]
"""
from __future__ import annotations
import json
import sys
import time
from datetime import date

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, "D:/Project/GenQuesAI")

from genquesai.legal_rag.config import get_settings
from genquesai.legal_rag.graph.client import Neo4jClient
from genquesai.legal_rag.domain.models import derive_tinh_trang

_Q_TARGET_NORM = """
MATCH (a:Action {action_id:$aid})-[:AFFECTS]->(tgt)
OPTIONAL MATCH (tgt)<-[:HAS_PART*0..]-(pn:Norm)
RETURN coalesce(CASE WHEN 'Norm' IN labels(tgt) THEN tgt.norm_id ELSE null END, pn.norm_id) AS tgt_norm_id
"""
_Q_MO_LAI = "MATCH (e:Expression {action_dong:$aid}) SET e.hieu_luc_den=null, e.action_dong=null RETURN e.expr_id AS expr_id"
_Q_REVOKE = "MATCH (a:Action {action_id:$aid}) SET a.da_duyet=false, a.de_xuat_loai_2llm=$ghi_chu"
_Q_STATES = "MATCH (n:Norm {norm_id:$nid})-[:HAS_PART*]->(:Component)-[:HAS_VERSION]->(e:Expression) RETURN e.hieu_luc_tu AS tu, e.hieu_luc_den AS den"
_Q_DA_DUYET = "MATCH (a:Action {action_id:$aid}) RETURN a.da_duyet AS da_duyet"


def main(apply: bool = False) -> None:
    s = get_settings()
    neo = Neo4jClient(s)

    print("== Bước 1: đọc dữ liệu gốc + verdict ==")
    with open("_thin_source_candidates.json", encoding="utf-8") as f:
        data = json.load(f)
    goc = {}
    for direction in ["A1", "A2"]:
        for r in data[direction]:
            if r["so_hieu_found"]:
                goc[r["action_id"]] = {**r, "direction": direction}

    verdicts = {}
    with open("_verdict_mong_found.jsonl", encoding="utf-8") as f:
        for line in f:
            v = json.loads(line)
            verdicts[v["action_id"]] = v
    print(f"  {len(goc)} ca gốc, {len(verdicts)} verdict")

    can_revoke = []      # tin ben noi KhongLienQuan -> revoke luon
    can_sua_loai = []    # tin ben noi that, khac graph -> revoke + annotate
    khong_can_gi = 0
    khong_ro = 0

    for aid, v in verdicts.items():
        r = goc.get(aid)
        if not r:
            continue
        rows = neo.run(_Q_DA_DUYET, aid=aid)
        if not (rows and rows[0]["da_duyet"] is True):
            continue

        verdict = v["verdict"]
        if verdict == "KHONG_RO":
            khong_ro += 1
            continue

        ds, gm = r["loai_deepseek"], r["loai_gemini"]
        ben_dung_la_gemini = verdict == "GEMINI_DUNG"
        loai_dung = gm if ben_dung_la_gemini else ds

        if loai_dung == "KhongLienQuan":
            tn = neo.run(_Q_TARGET_NORM, aid=aid)
            if tn and tn[0]["tgt_norm_id"]:
                can_revoke.append({**r, "tgt_norm_id": tn[0]["tgt_norm_id"], "ghi_chu_verdict": v.get("ghi_chu", "")})
        else:
            if loai_dung == r["loai_hien_tai_graph"]:
                khong_can_gi += 1
                continue
            tn = neo.run(_Q_TARGET_NORM, aid=aid)
            if tn and tn[0]["tgt_norm_id"]:
                can_sua_loai.append({**r, "tgt_norm_id": tn[0]["tgt_norm_id"], "loai_dung": loai_dung,
                                    "ghi_chu_verdict": v.get("ghi_chu", "")})

    print(f"  Tin bên KhongLienQuan -> revoke: {len(can_revoke)}")
    print(f"  Tin bên loại thật, khác graph -> revoke+annotate: {len(can_sua_loai)}")
    print(f"  Khớp sẵn graph, không cần làm gì: {khong_can_gi}")
    print(f"  KHONG_RO -> để nguyên: {khong_ro}")

    tat_ca = can_revoke + can_sua_loai
    ts = time.strftime("%Y%m%d_%H%M%S")
    backup_path = f"_backup_mong_found_{ts}.jsonl"
    with open(backup_path, "w", encoding="utf-8") as f:
        for r in tat_ca:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"  Đã ghi backup: {backup_path}")

    if not apply:
        print("\n== DRY RUN — chưa ghi gì. Chạy lại với --apply để thực thi. ==")
        return

    print("\n== Bước 2: revoke + mở lại Expression ==")
    tgt_norm_ids: set[str] = set()
    expr_ids_mo_lai: list[str] = []
    for r in tat_ca:
        if "loai_dung" in r:
            ghi_chu = (f"MONG_FOUND_DOC_TAY: doc tay xac nhan loai dung la {r['loai_dung']} "
                      f"(graph hien tai {r['loai_hien_tai_graph']}), nguon mong nhung co nhac dich - {r['ghi_chu_verdict']}")
        else:
            ghi_chu = f"MONG_FOUND_KHONGLIENQUAN: doc tay xac nhan KhongLienQuan dung, nguon mong nhung co nhac dich - {r['ghi_chu_verdict']}"
        neo.run(_Q_REVOKE, aid=r["action_id"], ghi_chu=ghi_chu)
        mo_rows = neo.run(_Q_MO_LAI, aid=r["action_id"])
        expr_ids_mo_lai.extend(row["expr_id"] for row in mo_rows if row["expr_id"])
        tgt_norm_ids.add(r["tgt_norm_id"])
    print(f"  Đã revoke {len(tat_ca)} cạnh, mở lại {len(expr_ids_mo_lai)} Expression, "
         f"ảnh hưởng {len(tgt_norm_ids)} Norm")

    print("== Bước 3: tính lại tinh_trang ==")
    today = date.today()
    dem_tt: dict[str, int] = {}
    for nid in sorted(tgt_norm_ids):
        states = [(r["tu"], r["den"]) for r in neo.run(_Q_STATES, nid=nid)]
        tt = str(derive_tinh_trang(states, today))
        if tt == "HetHieuLuc":
            neo.run("MATCH (n:Norm {norm_id:$nid}) SET n.tinh_trang=$tt", nid=nid, tt=tt)
        else:
            neo.run("MATCH (n:Norm {norm_id:$nid}) SET n.tinh_trang=$tt, n.eff_to=null", nid=nid, tt=tt)
        dem_tt[tt] = dem_tt.get(tt, 0) + 1
    print(f"  Kết quả tinh_trang: {dem_tt}")

    print("== Bước 4: đồng bộ Qdrant ==")
    from qdrant_client import QdrantClient
    from qdrant_client import models as qm
    q = QdrantClient(url=s.qdrant_url, api_key=s.qdrant_api_key or None,
                     timeout=s.qdrant_timeout, check_compatibility=False)
    if expr_ids_mo_lai:
        q.delete_payload(s.qdrant_collection, keys=["hieu_luc_den"],
                         points=qm.Filter(must=[qm.FieldCondition(key="expr_id", match=qm.MatchAny(any=expr_ids_mo_lai))]),
                         wait=True)
    print(f"  Đã đồng bộ {len(expr_ids_mo_lai)} điểm Qdrant")
    print(f"\n=== XONG. Backup tại {backup_path}. ===")


if __name__ == "__main__":
    main(apply="--apply" in sys.argv)
