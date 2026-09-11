"""Lấy TOÀN BỘ 295 ca "khác nhóm" (DeepSeek đề xuất loại TOÀN BỘ [ThayThe/BaiBoToanBo]
><-> Gemini đề xuất loại TỪNG PHẦN [SuaDoi/BaiBoTungPhan], hoặc ngược lại) — nhóm này
THẬT SỰ ảnh hưởng đúng/sai hiệu lực (đóng toàn bộ VB đích hay chỉ đóng đúng 1
Điều/Khoản), khác nhóm "cùng nhóm" (79% còn lại) chỉ khác nhãn không ảnh hưởng gì.

Chia thành 3 file để đọc tay song song qua 3 fork.

Chạy: cd genquesai/legal_rag && python _mau_khac_nhom_toan_bo.py
"""
from __future__ import annotations
import json
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, "D:/Project/GenQuesAI")

from genquesai.legal_rag.config import get_settings
from genquesai.legal_rag.graph.client import Neo4jClient

KET_QUA_PATH = "_rasoat_2llm_deploy/rasoat_2llm_log_KETQUA.jsonl"
RETRY_PATH = "_retry_null_api_batched_log.jsonl"
RULE_KETQUA_PATH = "_rule_tu_khoa_ket_qua.jsonl"

TOAN_BO = {"ThayThe", "BaiBoToanBo"}
TUNG_PHAN = {"SuaDoi", "BaiBoTungPhan"}

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
    out = []
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
                    out.append({**r, "norm_id": d["norm_id"], "so_hieu_nguon": d["so_hieu"],
                               "tieu_de_nguon": d["tieu_de"]})
    with open(RETRY_PATH, encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            if d.get("loi"):
                continue
            for r in d["ket_qua"]:
                ds, gm = r["loai_deepseek"], r["loai_gemini"]
                if ds and gm and ds != gm and ds != "KhongLienQuan" and gm != "KhongLienQuan":
                    out.append({**r, "norm_id": d["norm_id"], "so_hieu_nguon": d["so_hieu"],
                               "tieu_de_nguon": d["tieu_de"]})
    return out


def main() -> None:
    s = get_settings()
    neo = Neo4jClient(s)

    print("== Gom + lọc nhóm khác nhóm (toàn bộ vs từng phần) ==")
    ung_vien = gom_ung_vien_sac_thai()
    da_xu_ly = set()
    with open(RULE_KETQUA_PATH, encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            if r["loai_de_xuat_rule"] in (r["loai_deepseek"], r["loai_gemini"]):
                da_xu_ly.add(r["action_id"])

    khac_nhom = []
    for r in ung_vien:
        if r["action_id"] in da_xu_ly:
            continue
        ds, gm = r["loai_deepseek"], r["loai_gemini"]
        is_khac = (ds in TOAN_BO and gm in TUNG_PHAN) or (ds in TUNG_PHAN and gm in TOAN_BO)
        if not is_khac:
            continue
        rows = neo.run(_Q_DA_DUYET, aid=r["action_id"])
        if rows and rows[0]["da_duyet"] is True:
            khac_nhom.append(r)
    print(f"  {len(khac_nhom)} ca khác nhóm còn da_duyet=true")

    SO_FILE = 3
    chunk_size = (len(khac_nhom) + SO_FILE - 1) // SO_FILE
    for idx in range(SO_FILE):
        batch = khac_nhom[idx * chunk_size:(idx + 1) * chunk_size]
        if not batch:
            continue
        out_path = f"_mau_khac_nhom_phan{idx+1}.md"
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(f"# Nhóm 'khác nhóm' (toàn bộ vs từng phần) — phần {idx+1}/{SO_FILE} ({len(batch)} ca)\n\n")
            f.write("Đây là nhóm ẢNH HƯỞNG THẬT tới đúng/sai hiệu lực — 1 bên nói đóng TOÀN BỘ văn bản "
                   "đích (ThayThe/BaiBoToanBo), bên kia nói chỉ đóng TỪNG PHẦN cụ thể (SuaDoi/BaiBoTungPhan). "
                   "Đọc kỹ, xác định LOẠI ĐÚNG THỰC SỰ cho từng ca.\n\n---\n\n")
            for i, r in enumerate(batch, 1):
                nid = r["norm_id"]
                rows = neo.run(_Q_TOAN_VAN, nid=nid)
                toan_van = "\n\n".join(f"[{row['dd']}]\n{row['text'] or ''}" for row in rows)
                tn = neo.run(_Q_TARGET_NORM, aid=r["action_id"])
                tgt_meta = None
                if tn and tn[0]["tgt_norm_id"]:
                    tm = neo.run(_Q_TARGET_META, nid=tn[0]["tgt_norm_id"])
                    if tm:
                        tgt_meta = tm[0]

                f.write(f"## Ca {i}/{len(batch)} — action_id={r['action_id']}\n\n")
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
                f.write("**VERDICT (loại đúng thực sự)**: \n\n---\n\n")
        print(f"  Đã ghi {out_path} ({len(batch)} ca)")


if __name__ == "__main__":
    main()
