"""Lấy mẫu ngẫu nhiên từ nhóm "sắc thái mức độ" CÒN LẠI (sau khi đã loại 438 ca rule từ
khóa xử lý được) — đây là phần khó, không có tín hiệu từ khóa rõ ràng, cần đọc hiểu thật
để tìm NGUYÊN NHÂN 2 model bất đồng (không phải để áp fix).

Chạy: cd genquesai/legal_rag && python _mau_sac_thai_con_lai.py [so_luong]
"""
from __future__ import annotations
import json
import random
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, "D:/Project/GenQuesAI")

from genquesai.legal_rag.config import get_settings
from genquesai.legal_rag.graph.client import Neo4jClient

KET_QUA_PATH = "_rasoat_2llm_deploy/rasoat_2llm_log_KETQUA.jsonl"
RETRY_PATH = "_retry_null_api_batched_log.jsonl"
RULE_KETQUA_PATH = "_rule_tu_khoa_ket_qua.jsonl"

_Q_TOAN_VAN = """
MATCH (n:Norm {norm_id:$nid})-[:HAS_PART*]->(d:Component)-[:HAS_VERSION]->(e:Expression)
WHERE d.loai IN ['Dieu','ToanVan']
RETURN d.duong_dan AS dd, e.text AS text, d.order_key AS ok
ORDER BY ok
"""
_Q_TARGET_NORM = """
MATCH (a:Action {action_id:$aid})-[:AFFECTS]->(tgt)
OPTIONAL MATCH (tgt)<-[:HAS_PART*0..]-(pn:Norm)
RETURN coalesce(CASE WHEN 'Norm' IN labels(tgt) THEN tgt.norm_id ELSE null END, pn.norm_id) AS tgt_norm_id
"""
_Q_TARGET_META = "MATCH (n:Norm {norm_id:$nid}) RETURN n.tieu_de AS tieu_de, n.co_quan_ban_hanh AS co_quan, n.ngay_ban_hanh AS ngay, n.loai_vb AS loai_vb"
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
                    ket_qua.append({**r, "norm_id": d["norm_id"], "so_hieu_nguon": d["so_hieu"],
                                    "tieu_de_nguon": d["tieu_de"]})
    with open(RETRY_PATH, encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            if d.get("loi"):
                continue
            for r in d["ket_qua"]:
                ds, gm = r["loai_deepseek"], r["loai_gemini"]
                if ds and gm and ds != gm and ds != "KhongLienQuan" and gm != "KhongLienQuan":
                    ket_qua.append({**r, "norm_id": d["norm_id"], "so_hieu_nguon": d["so_hieu"],
                                    "tieu_de_nguon": d["tieu_de"]})
    return ket_qua


def main(so_luong: int = 30) -> None:
    s = get_settings()
    neo = Neo4jClient(s)

    print("== Gom ứng viên sắc thái mức độ, loại các ca rule từ khóa đã xử lý được ==")
    ung_vien = gom_ung_vien_sac_thai()
    da_xu_ly_boi_rule = set()
    with open(RULE_KETQUA_PATH, encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            if r["loai_de_xuat_rule"] in (r["loai_deepseek"], r["loai_gemini"]):
                da_xu_ly_boi_rule.add(r["action_id"])
    print(f"  {len(ung_vien)} cạnh tổng — {len(da_xu_ly_boi_rule)} đã xử lý bởi rule từ khóa")

    con_lai = []
    for r in ung_vien:
        if r["action_id"] in da_xu_ly_boi_rule:
            continue
        rows = neo.run(_Q_DA_DUYET, aid=r["action_id"])
        if rows and rows[0]["da_duyet"] is True:
            con_lai.append(r)
    print(f"  Còn lại (chưa xử lý, còn da_duyet=true): {len(con_lai)}")

    random.seed(7)
    mau = random.sample(con_lai, min(so_luong, len(con_lai)))
    print(f"  Lấy mẫu ngẫu nhiên: {len(mau)}")

    with open("_mau_sac_thai_con_lai.md", "w", encoding="utf-8") as f:
        f.write(f"# Mẫu {len(mau)} ca — sắc thái mức độ CÒN LẠI (sau khi loại rule từ khóa)\n\n")
        f.write("Mục tiêu: TÌM NGUYÊN NHÂN 2 model bất đồng, không phải áp fix. Đọc kỹ toàn văn, "
                "đối chiếu 2 lý do, phân tích vì sao mỗi bên nghĩ khác nhau.\n\n---\n\n")
        for i, r in enumerate(mau, 1):
            nid = r["norm_id"]
            rows = neo.run(_Q_TOAN_VAN, nid=nid)
            toan_van = "\n\n".join(f"[{row['dd']}]\n{row['text'] or ''}" for row in rows)
            tn = neo.run(_Q_TARGET_NORM, aid=r["action_id"])
            tgt_meta = None
            if tn and tn[0]["tgt_norm_id"]:
                tm = neo.run(_Q_TARGET_META, nid=tn[0]["tgt_norm_id"])
                if tm:
                    tgt_meta = tm[0]

            f.write(f"## Ca {i}/{len(mau)} — action_id={r['action_id']}\n\n")
            f.write(f"**Nguồn**: {r.get('so_hieu_nguon','?')} — {r.get('tieu_de_nguon','')}\n")
            f.write(f"**Đích (số hiệu)**: {r['target_so_hieu']}")
            if tgt_meta:
                f.write(f" — {tgt_meta['tieu_de']} ({tgt_meta['loai_vb']})\n")
            else:
                f.write("\n")
            f.write(f"\n**DeepSeek đề xuất**: {r['loai_deepseek']} — lý do: {r['ly_do_deepseek']}\n")
            f.write(f"\n**Gemini đề xuất**: {r['loai_gemini']} — lý do: {r['ly_do_gemini']}\n")
            f.write(f"\n**Loại hiện tại trong graph**: {r['loai_hien_tai_graph']}\n")
            f.write(f"\n<details><summary>Toàn văn nguồn ({len(toan_van)} ký tự)</summary>\n\n```\n{toan_van[:15000]}\n```\n\n</details>\n\n")
            f.write("**PHÂN TÍCH NGUYÊN NHÂN**: \n\n---\n\n")

    print("Đã ghi _mau_sac_thai_con_lai.md")


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    main(n)
