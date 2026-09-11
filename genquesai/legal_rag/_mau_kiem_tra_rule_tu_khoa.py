"""Lấy mẫu để kiểm tra độ chính xác thật của rule từ khóa vừa thử (_rule_tu_khoa_sac_thai.py)
— ưu tiên các ca rule ra kết quả KHÁC CẢ 2 MODEL (nghi ngờ nhất), cộng thêm mẫu ngẫu
nhiên từ nhóm khớp Gemini/DeepSeek để kiểm tra tổng thể.

Chạy: cd genquesai/legal_rag && python _mau_kiem_tra_rule_tu_khoa.py
"""
from __future__ import annotations
import json
import random
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, "D:/Project/GenQuesAI")

from genquesai.legal_rag.config import get_settings
from genquesai.legal_rag.graph.client import Neo4jClient

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


def main() -> None:
    s = get_settings()
    neo = Neo4jClient(s)

    with open("_rule_tu_khoa_ket_qua.jsonl", encoding="utf-8") as f:
        tat_ca = [json.loads(line) for line in f]

    khac_ca_2 = [r for r in tat_ca if r["loai_de_xuat_rule"] not in (r["loai_deepseek"], r["loai_gemini"])]
    khop_gm = [r for r in tat_ca if r["loai_de_xuat_rule"] == r["loai_gemini"] and r["loai_de_xuat_rule"] != r["loai_deepseek"]]
    khop_ds = [r for r in tat_ca if r["loai_de_xuat_rule"] == r["loai_deepseek"] and r["loai_de_xuat_rule"] != r["loai_gemini"]]

    random.seed(42)
    mau = (khac_ca_2[:] if len(khac_ca_2) <= 25 else random.sample(khac_ca_2, 25)) \
        + random.sample(khop_gm, min(15, len(khop_gm))) \
        + random.sample(khop_ds, min(10, len(khop_ds)))
    print(f"khac_ca_2: {len(khac_ca_2)} (lay het toi da 25) | khop_gm mau: min(15,{len(khop_gm)}) | khop_ds mau: min(10,{len(khop_ds)})")
    print(f"Tong mau: {len(mau)}")

    with open("_mau_kiem_tra_rule.md", "w", encoding="utf-8") as f:
        f.write(f"# Kiểm tra rule từ khóa — {len(mau)} ca (ưu tiên 'khác cả 2 model')\n\n")
        f.write("Với mỗi ca, RULE đã tự động đề xuất 1 loại dựa trên tìm từ khóa 'bãi bỏ'/'thay thế' "
                "quanh vị trí nhắc số hiệu đích. Đọc toàn văn, tự phán quyết RULE đúng hay sai — "
                "không chỉ so với DeepSeek/Gemini mà so với NỘI DUNG THỰC.\n\n---\n\n")
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
            f.write(f"**Nguồn**: {r.get('so_hieu_nguon','?')}\n")
            f.write(f"**Đích (số hiệu)**: {r['target_so_hieu']}")
            if tgt_meta:
                f.write(f" — {tgt_meta['tieu_de']} ({tgt_meta['loai_vb']})\n")
            else:
                f.write("\n")
            f.write(f"\n**RULE đề xuất**: {r['loai_de_xuat_rule']} — ({r['ly_do_rule']})\n")
            f.write(f"**DeepSeek đề xuất**: {r['loai_deepseek']} · **Gemini đề xuất**: {r['loai_gemini']} "
                   f"· **Graph hiện tại**: {r['loai_hien_tai_graph']}\n")
            f.write(f"\n<details><summary>Toàn văn nguồn ({len(toan_van)} ký tự)</summary>\n\n```\n{toan_van[:15000]}\n```\n\n</details>\n\n")
            f.write("**VERDICT (rule đúng/sai, nếu sai thì loại đúng là gì)**: \n\n---\n\n")

    print("Đã ghi _mau_kiem_tra_rule.md")


if __name__ == "__main__":
    main()
