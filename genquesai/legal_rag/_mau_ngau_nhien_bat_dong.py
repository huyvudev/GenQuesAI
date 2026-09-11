"""Lấy mẫu ngẫu nhiên từ nhóm bất đồng "DeepSeek=có quan hệ thật, Gemini=KhongLienQuan"
(loại trừ các ca đã fix ở rule VBHN) để đọc tay và tính tỷ lệ Gemini đúng thực tế —
không suy luận qua so_hieu-match nữa mà đọc toàn văn + lý do 2 model đưa ra.

Chạy: cd genquesai/legal_rag && python _mau_ngau_nhien_bat_dong.py [so_luong_mau]
Ghi ra: _mau_doc_tay_<ts>.md — 1 file đọc được, mỗi ca có đủ: nguồn (toàn văn đã chọn lọc
ngữ cảnh + toàn văn KHÔNG cắt để đối chiếu), đích, lý do DeepSeek, lý do Gemini.
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

_Q_LOAI_VB_NGUON = "MATCH (n:Norm {norm_id:$nid}) RETURN n.loai_vb AS loai_vb, n.tieu_de AS tieu_de, n.co_quan_ban_hanh AS co_quan, n.ngay_ban_hanh AS ngay"
_Q_TOAN_VAN = """
MATCH (n:Norm {norm_id:$nid})-[:HAS_PART*]->(d:Component)-[:HAS_VERSION]->(e:Expression)
WHERE d.loai IN ['Dieu','ToanVan']
RETURN d.duong_dan AS dd, e.text AS text, d.order_key AS ok
ORDER BY ok
"""
_Q_TARGET_META = "MATCH (n:Norm {norm_id:$nid}) RETURN n.tieu_de AS tieu_de, n.co_quan_ban_hanh AS co_quan, n.ngay_ban_hanh AS ngay, n.loai_vb AS loai_vb"
_Q_TARGET_NORM = """
MATCH (a:Action {action_id:$aid})-[:AFFECTS]->(tgt)
OPTIONAL MATCH (tgt)<-[:HAS_PART*0..]-(pn:Norm)
RETURN coalesce(CASE WHEN 'Norm' IN labels(tgt) THEN tgt.norm_id ELSE null END, pn.norm_id) AS tgt_norm_id
"""


def _chuan_hoa(s: str) -> str:
    return "".join(ch for ch in (s or "").upper() if ch.isalnum())


def doc_ung_vien() -> list[dict]:
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
                if ds and gm and ds != "KhongLienQuan" and gm == "KhongLienQuan":
                    ket_qua.append({**r, "norm_id": d["norm_id"], "so_hieu_nguon": d["so_hieu"],
                                     "tieu_de_nguon": d["tieu_de"]})
    return ket_qua


def main(so_luong: int = 30) -> None:
    s = get_settings()
    neo = Neo4jClient(s)

    print("Lọc nhóm ứng viên (DeepSeek=có thật, Gemini=KhongLienQuan)...")
    ung_vien = doc_ung_vien()
    print(f"  {len(ung_vien)} cạnh")

    # Loại các ca nguồn là VBHN (đã fix riêng ở rule khác, khỏi lẫn vào mẫu)
    truoc = len(ung_vien)
    con_lai = []
    cache_loai_vb: dict[str, str] = {}
    for r in ung_vien:
        nid = r["norm_id"]
        if nid not in cache_loai_vb:
            rows = neo.run(_Q_LOAI_VB_NGUON, nid=nid)
            cache_loai_vb[nid] = rows[0]["loai_vb"] if rows else None
        if cache_loai_vb[nid] != "VanBanHopNhat":
            con_lai.append(r)
    print(f"  Sau khi loại VBHN: {len(con_lai)} (đã loại {truoc - len(con_lai)})")

    random.seed(42)
    mau = random.sample(con_lai, min(so_luong, len(con_lai)))
    print(f"  Lấy mẫu ngẫu nhiên: {len(mau)} ca (seed=42)")

    ts = time.strftime("%Y%m%d_%H%M%S")
    out_path = f"_mau_doc_tay_{ts}.md"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(f"# Mẫu ngẫu nhiên {len(mau)} ca — DeepSeek nói có quan hệ thật, Gemini nói KhongLienQuan\n\n")
        f.write("Đọc từng ca, tự đánh giá: Gemini đúng (thực sự không liên quan) hay DeepSeek đúng "
                "(thực sự có quan hệ, Gemini bỏ sót)? Ghi verdict cuối file.\n\n---\n\n")
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
            f.write(f"**Nguồn**: {r['so_hieu_nguon']} — {r['tieu_de_nguon']}\n")
            src_meta = cache_loai_vb.get(nid)
            f.write(f"**Đích (số hiệu)**: {r['target_so_hieu']}")
            if tgt_meta:
                f.write(f" — {tgt_meta['tieu_de']} ({tgt_meta['loai_vb']}, {tgt_meta['co_quan']}, {tgt_meta['ngay']})\n")
            else:
                f.write(" — (không tìm thấy Norm đích trong graph)\n")
            f.write(f"\n**DeepSeek đề xuất**: {r['loai_deepseek']} — lý do: {r['ly_do_deepseek']}\n")
            f.write(f"\n**Gemini đề xuất**: {r['loai_gemini']} — lý do: {r['ly_do_gemini']}\n")
            f.write(f"\n**Loại hiện tại trong graph**: {r['loai_hien_tai_graph']}\n")
            found = _chuan_hoa(r['target_so_hieu']) in _chuan_hoa(toan_van)
            f.write(f"\n**Số hiệu đích xuất hiện trong toàn văn nguồn (string match)?**: {'CÓ' if found else 'KHÔNG'}\n")
            f.write(f"\n<details><summary>Toàn văn nguồn ({len(toan_van)} ký tự)</summary>\n\n```\n{toan_van[:15000]}\n```\n\n</details>\n\n")
            f.write("**VERDICT (điền tay/agent)**: \n\n---\n\n")
            if i % 5 == 0:
                print(f"  {i}/{len(mau)} đã ghi")

    print(f"\nĐã ghi {out_path} — {len(mau)} ca để đọc.")


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    main(n)
