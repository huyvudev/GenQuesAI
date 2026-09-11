"""Lấy mẫu ngẫu nhiên cho CẢ 3 nhóm bất đồng còn lại (gộp cả kết quả gốc + kết quả retry
null_api mới) để đọc tay phân tích nguyên nhân:
  - A1: DeepSeek nói có quan hệ thật, Gemini nói KhongLienQuan
  - A2: Gemini nói có quan hệ thật, DeepSeek nói KhongLienQuan (chưa từng xác minh)
  - sac_thai: cả 2 nói có quan hệ thật nhưng khác LOẠI mức độ (ThayThe/BaiBoToanBo/SuaDoi/BaiBoTungPhan)

Chạy: cd genquesai/legal_rag && python _mau_3_nhom_con_lai.py [so_luong_moi_nhom]
Ghi ra: _mau_A1_<ts>.md, _mau_A2_<ts>.md, _mau_sac_thai_<ts>.md
"""
from __future__ import annotations
import json
import random
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, "D:/Project/GenQuesAI")

from genquesai.legal_rag.config import get_settings
from genquesai.legal_rag.graph.client import Neo4jClient

KET_QUA_PATH = "_rasoat_2llm_deploy/rasoat_2llm_log_KETQUA.jsonl"
RETRY_PATH = "_retry_null_api_batched_log.jsonl"
CON_LAI_PATH = "_con_lai_bat_dong_chua_xu_ly.jsonl"

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


def phan_loai(ds, gm) -> str | None:
    if ds is None or gm is None:
        return None
    if ds == gm:
        return None  # dong thuan, khong phai bat dong
    if ds != "KhongLienQuan" and gm == "KhongLienQuan":
        return "A1"
    if gm != "KhongLienQuan" and ds == "KhongLienQuan":
        return "A2"
    return "sac_thai"


def gom_ung_vien() -> dict[str, list[dict]]:
    nhom: dict[str, list[dict]] = {"A1": [], "A2": [], "sac_thai": []}

    # Nguon 1: audit log goc, con da_duyet=true, khong phai null_api (da xu ly rieng)
    with open(CON_LAI_PATH, encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            ds, gm = r["loai_deepseek"], r["loai_gemini"]
            loai = phan_loai(ds, gm)
            if loai:
                nhom[loai].append(r)

    # Nguon 2: ket qua retry null_api, cac ca gio da co du lieu that va roi vao 1 trong 3 nhom
    with open(RETRY_PATH, encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            if d.get("loi"):
                continue
            for r in d["ket_qua"]:
                loai = phan_loai(r["loai_deepseek"], r["loai_gemini"])
                if loai:
                    nhom[loai].append({**r, "norm_id": d["norm_id"], "so_hieu_nguon": d["so_hieu"],
                                       "tieu_de_nguon": d["tieu_de"]})
    return nhom


def ghi_mau(neo, ten_nhom: str, mau: list[dict], out_path: str) -> None:
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(f"# Mẫu ngẫu nhiên {len(mau)} ca — nhóm {ten_nhom}\n\n")
        f.write("Đọc từng ca, đối chiếu toàn văn nguồn thực tế với lý do 2 model đưa ra, "
                "tự phán quyết ai đúng (hoặc cả 2 đều có lý — với sắc thái mức độ). "
                "Ghi verdict cuối mỗi ca.\n\n---\n\n")
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
                f.write(f" — {tgt_meta['tieu_de']} ({tgt_meta['loai_vb']}, {tgt_meta['co_quan']}, {tgt_meta['ngay']})\n")
            else:
                f.write(" — (không tìm thấy Norm đích trong graph)\n")
            f.write(f"\n**DeepSeek đề xuất**: {r['loai_deepseek']} — lý do: {r['ly_do_deepseek']}\n")
            f.write(f"\n**Gemini đề xuất**: {r['loai_gemini']} — lý do: {r['ly_do_gemini']}\n")
            f.write(f"\n**Loại hiện tại trong graph**: {r['loai_hien_tai_graph']}\n")
            f.write(f"\n<details><summary>Toàn văn nguồn ({len(toan_van)} ký tự)</summary>\n\n```\n{toan_van[:15000]}\n```\n\n</details>\n\n")
            f.write("**VERDICT**: \n\n---\n\n")
    print(f"  Đã ghi {out_path} ({len(mau)} ca)")


def main(so_luong: int = 25) -> None:
    s = get_settings()
    neo = Neo4jClient(s)

    print("== Gom ứng viên 3 nhóm (gộp audit log gốc + retry null_api) ==")
    nhom = gom_ung_vien()
    for k, v in nhom.items():
        print(f"  {k}: {len(v)} cạnh")

    random.seed(42)
    ts = time.strftime("%Y%m%d_%H%M%S")
    for k, v in nhom.items():
        mau = random.sample(v, min(so_luong, len(v)))
        out_path = f"_mau_{k}_{ts}.md"
        ghi_mau(neo, k, mau, out_path)


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 25
    main(n)
