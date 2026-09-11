"""Tạo 2 bộ dossier từ _thin_source_candidates.json:
1. TOÀN BỘ 59 ca "found" (số hiệu đích có nhắc trong nội dung mỏng) — đọc kỹ hết.
2. Mẫu ngẫu nhiên 40 ca "not found" — xác minh xem tín hiệu "không nhắc -> tin bên phủ
   định" còn đáng tin không khi nội dung vốn đã mỏng/thiếu (khác với lúc có toàn văn đầy đủ).

Chạy: cd genquesai/legal_rag && python _mau_nguon_mong.py
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


def ghi_dossier(neo, ten: str, mau: list[dict], out_path: str, huong: str) -> None:
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(f"# {ten} — hướng {huong} ({len(mau)} ca)\n\n")
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

            f.write(f"## Ca {i}/{len(mau)} — action_id={r['action_id']} — hướng {huong}\n\n")
            f.write(f"**Nguồn**: {r.get('so_hieu_nguon','?')} — {r.get('tieu_de_nguon','')}\n")
            f.write(f"**Đích (số hiệu)**: {r['target_so_hieu']}")
            if tgt_meta:
                f.write(f" — {tgt_meta['tieu_de']} ({tgt_meta['loai_vb']})\n")
            else:
                f.write("\n")
            f.write(f"\n**DeepSeek đề xuất**: {r['loai_deepseek']} — lý do: {r['ly_do_deepseek']}\n")
            f.write(f"\n**Gemini đề xuất**: {r['loai_gemini']} — lý do: {r['ly_do_gemini']}\n")
            f.write(f"\n**Loại hiện tại trong graph**: {r['loai_hien_tai_graph']}\n")
            f.write(f"\n**Độ dài toàn văn nguồn (đã biết là MỎNG/THIẾU)**: {r['do_dai']} ký tự\n")
            f.write(f"\n<details><summary>Toàn văn nguồn đầy đủ</summary>\n\n```\n{toan_van}\n```\n\n</details>\n\n")
            f.write("**VERDICT**: \n\n---\n\n")


def main() -> None:
    s = get_settings()
    neo = Neo4jClient(s)

    with open("_thin_source_candidates.json", encoding="utf-8") as f:
        data = json.load(f)

    found_a1 = [r for r in data["A1"] if r["so_hieu_found"]]
    found_a2 = [r for r in data["A2"] if r["so_hieu_found"]]
    print(f"found A1={len(found_a1)}, A2={len(found_a2)}")
    ghi_dossier(neo, "Nguồn mỏng - CÓ nhắc số hiệu đích - A1", found_a1, "_mau_mong_found_A1.md", "A1")
    ghi_dossier(neo, "Nguồn mỏng - CÓ nhắc số hiệu đích - A2", found_a2, "_mau_mong_found_A2.md", "A2")

    random.seed(42)
    not_found_a1 = [r for r in data["A1"] if not r["so_hieu_found"]]
    not_found_a2 = [r for r in data["A2"] if not r["so_hieu_found"]]
    mau_a1 = random.sample(not_found_a1, min(30, len(not_found_a1)))
    mau_a2 = random.sample(not_found_a2, min(20, len(not_found_a2)))
    print(f"mau not_found A1={len(mau_a1)}, A2={len(mau_a2)}")
    ghi_dossier(neo, "Nguồn mỏng - KHÔNG nhắc số hiệu đích (mẫu) - A1", mau_a1, "_mau_mong_notfound_A1.md", "A1")
    ghi_dossier(neo, "Nguồn mỏng - KHÔNG nhắc số hiệu đích (mẫu) - A2", mau_a2, "_mau_mong_notfound_A2.md", "A2")

    print("Đã ghi 4 file dossier.")


if __name__ == "__main__":
    main()
