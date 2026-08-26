"""Trich cap Dieu/Khoan/Diem cho cac canh AMENDS (loai='SuaDoi' hien tai, se tach lai
BaiBoToanBo/BaiBoTungPhan trong luot nay luon) — doc lai TOAN THAN VB nguon (khong
chi preamble nhu dot truoc), tim dung Dieu/Khoan/Diem cua VB dich bi nhac toi, tro
lai AFFECTS vao dung Component thay vi Norm.

Checkpoint: `_trich_dieu_log.jsonl` (flush ngay sau moi VB nguon) + Neo4j tu ghi
`da_xu_ly_cap_dieu=true` tren Action (dung resume, khong doc lai VB da xong)."""
from __future__ import annotations
import json
import sys
import threading
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, "D:/Project/GenQuesAI")

from genquesai.legal_rag.config import get_settings
from genquesai.legal_rag.graph.client import Neo4jClient
from genquesai.legal_rag.agent.llm import LLM
from genquesai.legal_rag.ingestion.reference_extractor import html_to_text
from qdrant_client import QdrantClient

# tai dung ham dung Qdrant tu script rebuild dem qua
sys.path.insert(0, str(Path(__file__).parent))
from _rebuild_full_corpus import build_local_file_index, build_text_from_qdrant  # noqa: E402

HERE = Path(__file__).parent
LOG_PATH = HERE / "_trich_dieu_log.jsonl"
PROGRESS_PATH = HERE / "_trich_dieu_progress.log"

# Bug that 2026-08-26 (user phat hien): text[:14000] cat cut VB dai truoc khi toi
# duoc cau "Bai bo Dieu X/Sua doi Dieu Y" — cau nay hay nam GIUA hoac CUOI van ban,
# khong chi dau. VD thuc te: VB 240.912 ky tu, cau "Bai bo Dieu 12, 13..." nam o vi
# tri 42.678 (17.7%), ngoai pham vi 14.000 ky tu cu. Sua: lay dau (nhieu Dieu tu sua
# thuong o day) GHEP THEM duoi (dieu khoan thi hanh/bai bo hay o day) cho VB dai,
# thay vi cat cung dau.
_MAX_HEAD = 50000
_MAX_TAIL = 8000


def _ngan_sach_text(text: str) -> str:
    if len(text) <= _MAX_HEAD + _MAX_TAIL:
        return text
    return (text[:_MAX_HEAD] + "\n\n[... (lược bớt đoạn giữa văn bản) ...]\n\n"
            + text[-_MAX_TAIL:])

_SYS = (
    "Bạn đọc TOÀN VĂN 1 văn bản pháp luật Việt Nam. Cho sẵn danh sách các VĂN BẢN ĐÍCH "
    "mà văn bản này đã xác định là có sửa đổi/bãi bỏ (không cần tìm đích mới, KHÔNG "
    "được thêm đích không có trong danh sách cho sẵn). Với MỖI đích trong danh sách, "
    "đọc kỹ toàn văn tìm CHÍNH XÁC Điều/Khoản/Điểm nào của đích đó bị nhắc tới. "
    "Trả JSON: {\"ket_qua\":[{\"target\":\"so_hieu đích (đúng như trong danh sách cho "
    "sẵn)\", \"dieu\":\"số Điều, vd '5' hoặc '5a' — để trống nếu văn bản chỉ nói chung "
    "chung không nêu Điều cụ thể\", \"khoan\":\"số Khoản nếu có nêu, để trống nếu "
    "không\", \"diem\":\"chữ Điểm nếu có nêu (vd 'a'), để trống nếu không\", "
    "\"loai\":\"SuaDoi|BaiBoToanBo|BaiBoTungPhan|ThayThe\"}]}. "
    "loai: SuaDoi = sửa đổi/bổ sung (CÓ nội dung mới thay cho nội dung cũ); "
    "BaiBoToanBo = bãi bỏ/huỷ bỏ TOÀN BỘ đích (xoá hẳn, KHÔNG có nội dung mới); "
    "BaiBoTungPhan = bãi bỏ/huỷ bỏ MỘT PHẦN đích (không phải toàn bộ VB); "
    "ThayThe = thay thế TOÀN BỘ đích bằng nội dung mới. "
    "Nếu 1 đích bị sửa ở NHIỀU Điều khác nhau (vd Điều 5 VÀ Điều 8), trả NHIỀU dòng "
    "riêng cho đích đó — mỗi dòng đúng 1 Điều/Khoản/Điểm. Nếu 1 đích trong danh sách "
    "cho sẵn mà bạn ĐỌC KHÔNG THẤY trong văn bản (không tìm lại được câu nhắc tới nó), "
    "vẫn phải trả 1 dòng cho nó với dieu/khoan/diem để trống và loai để trống — KHÔNG "
    "được bỏ sót đích nào trong danh sách cho sẵn. TUYỆT ĐỐI KHÔNG bịa số Điều không "
    "có thật trong văn bản."
)


def _progress(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}"
    print(line, flush=True)
    with open(PROGRESS_PATH, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def _duong_dan(dieu: str, khoan: str, diem: str) -> str:
    p = f"Dieu {dieu}"
    if khoan:
        p += f" > Khoan {khoan}"
        if diem:
            p += f" > Diem {diem}"
    return p


_LOG_LOCK = threading.Lock()


def _ghi_log(record: dict) -> None:
    with _LOG_LOCK:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
            f.flush()


def xu_ly_1_vb(neo: Neo4jClient, llm: LLM, local_idx: dict, q: QdrantClient, qdrant_coll: str,
              sid: str, actions: list[dict]) -> dict:
    """`actions`: list {action_id, tgt_norm_id, tgt_so_hieu}. Trả thống kê."""
    d = local_idx.get(sid)
    if d is not None:
        data = json.loads((d / "doc.json").read_text(encoding="utf-8"))["data"]
        title = data.get("title") or ""
        text = html_to_text((d / "toanvan.html").read_text(encoding="utf-8", errors="ignore"))
    else:
        rows = neo.run("MATCH (n:Norm {norm_id:$id}) RETURN n.tieu_de AS td", id=sid)
        title = rows[0]["td"] if rows else ""
        text = build_text_from_qdrant(q, qdrant_coll, sid)

    targets_biet = sorted({a["tgt_so_hieu"] for a in actions})
    user = (f"Văn bản: {sid}\nTiêu đề: {title}\n"
           f"Danh sách đích ĐÃ BIẾT bị sửa đổi/bãi bỏ: {', '.join(targets_biet)}\n\n"
           f"Toàn văn:\n{_ngan_sach_text(text)}")
    data_out = llm.chat_json(_SYS, user, max_tokens=3000)
    ket_qua = data_out.get("ket_qua", []) if isinstance(data_out, dict) else []

    # map target so_hieu -> list action (1 target co the co nhieu action neu... binh
    # thuong 1:1, nhung phong truong hop trung)
    by_target: dict[str, list[dict]] = {}
    for a in actions:
        by_target.setdefault(a["tgt_so_hieu"], []).append(a)

    stats = {"tong_dich": len(targets_biet), "resolved_dieu": 0, "khong_co_dieu": 0,
            "khong_resolve_duoc_component": 0, "loai_doi": 0, "dich_thieu_trong_ket_qua": 0}
    tra_ve = []
    da_thay: set[str] = set()

    for item in ket_qua:
        tgt_sh = (item.get("target") or "").strip()
        acts = by_target.get(tgt_sh)
        if not acts:
            continue  # LLM tra ve dich khong nam trong danh sach cho san -> bo qua
        dieu = (item.get("dieu") or "").strip()
        khoan = (item.get("khoan") or "").strip()
        diem = (item.get("diem") or "").strip()
        loai_moi = (item.get("loai") or "").strip()
        act = acts[0]  # 1 target = 1 action trong tap AMENDS hien tai
        da_thay.add(tgt_sh)

        rec = {"action_id": act["action_id"], "tgt_so_hieu": tgt_sh, "dieu": dieu,
               "khoan": khoan, "diem": diem, "loai_moi": loai_moi or None, "cap_dich": "VanBan"}

        if loai_moi and loai_moi != act.get("loai_cu"):
            stats["loai_doi"] += 1

        if not dieu:
            stats["khong_co_dieu"] += 1
            tra_ve.append(rec)
            continue

        dd = _duong_dan(dieu, khoan, diem)
        rows = neo.run(
            "MATCH (c:Component {norm_id:$tid, duong_dan:$dd}) RETURN c.comp_id AS cid",
            tid=act["tgt_norm_id"], dd=dd)
        if not rows:
            stats["khong_resolve_duoc_component"] += 1
            rec["ly_do_khong_resolve"] = f"khong tim thay Component duong_dan={dd!r}"
            tra_ve.append(rec)
            continue

        stats["resolved_dieu"] += 1
        cap = "Diem" if diem else ("Khoan" if khoan else "Dieu")
        rec["cap_dich"] = cap
        rec["comp_id"] = rows[0]["cid"]
        tra_ve.append(rec)

    for tgt_sh in targets_biet:
        if tgt_sh not in da_thay:
            stats["dich_thieu_trong_ket_qua"] += 1

    # Ghi vao Neo4j — QUAN TRONG: 1 target co the co NHIEU Dieu (nhieu dong tra_ve
    # cung action_id goc). Dong DAU TIEN cap nhat Action GOC tai cho; cac dong SAU
    # (Dieu khac cua CUNG 1 dich) phai TAO ACTION MOI (action_id rieng) — khong thi
    # ghi de lien tiep len cung 1 Action se chi giu duoc dong CUOI CUNG, mat het cac
    # Dieu con lai (bug that phat hien khi test 5 VB — 24 ket qua resolve nhung chi
    # 1 Action thuc su duoc cap nhat, 23 dong bi am tham mat vi MATCH lai tren AFFECTS
    # da doi sang Component tu lan truoc, khong con khop [:AFFECTS]->(Norm) nua)."""
    by_action_id: dict[str, list[dict]] = {}
    for rec in tra_ve:
        by_action_id.setdefault(rec["action_id"], []).append(rec)

    for orig_aid, group in by_action_id.items():
        goc = neo.run("""
            MATCH (a:Action {action_id:$aid})-[:ENACTED_BY]->(src:Norm)
            RETURN a.mismatch AS mismatch, a.only_llm AS only_llm, a.da_duyet AS da_duyet,
                   a.confidence AS confidence, a.source AS source, a.nguon AS nguon,
                   src.norm_id AS sid
        """, aid=orig_aid)
        if not goc:
            continue
        g = goc[0]
        for idx, rec in enumerate(group):
            aid = orig_aid if idx == 0 else f"{orig_aid}#{rec['dieu']}-{rec['khoan']}-{rec['diem']}"
            loai_set = ", a.loai=$loai_moi" if rec["loai_moi"] else ""
            loai_kw = {"loai_moi": rec["loai_moi"]} if rec["loai_moi"] else {}
            if rec.get("comp_id"):
                if idx == 0:
                    neo.run(f"""
                        MATCH (a:Action {{action_id:$aid}})-[r:AFFECTS]->(old:Norm)
                        MATCH (a)-[:ENACTED_BY]->(src:Norm)
                        MATCH (c:Component {{comp_id:$cid}})
                        OPTIONAL MATCH (src)-[old_edge:AMENDS]->(old)
                        DELETE r, old_edge
                        MERGE (a)-[:AFFECTS]->(c)
                        MERGE (src)-[:AMENDS]->(c)
                        SET a.cap_dich=$cap, a.da_xu_ly_cap_dieu=true{loai_set}
                        """, aid=aid, cid=rec["comp_id"], cap=rec["cap_dich"], **loai_kw)
                else:
                    neo.run(f"""
                        MATCH (src:Norm {{norm_id:$sid}})
                        MATCH (c:Component {{comp_id:$cid}})
                        MERGE (a:Action {{action_id:$aid}})
                          SET a.loai=coalesce($loai_moi, 'SuaDoi'), a.confidence=$confidence,
                              a.da_duyet=$da_duyet, a.enacted_by=$sid, a.source=$source,
                              a.mismatch=$mismatch, a.only_llm=$only_llm, a.nguon=$nguon,
                              a.cap_dich=$cap, a.da_xu_ly_cap_dieu=true
                        MERGE (a)-[:ENACTED_BY]->(src)
                        MERGE (a)-[:AFFECTS]->(c)
                        MERGE (src)-[:AMENDS]->(c)
                        """, aid=aid, cid=rec["comp_id"], sid=g["sid"], cap=rec["cap_dich"],
                        confidence=g["confidence"], da_duyet=g["da_duyet"], source=g["source"],
                        mismatch=g["mismatch"], only_llm=g["only_llm"], nguon=g["nguon"],
                        loai_moi=rec["loai_moi"])
            else:
                if idx == 0:
                    neo.run(f"""
                        MATCH (a:Action {{action_id:$aid}})
                        SET a.cap_dich=$cap, a.da_xu_ly_cap_dieu=true{loai_set}
                        """, aid=aid, cap=rec["cap_dich"], **loai_kw)
                # idx>0 khong resolve duoc Component VA khong phai dong dau -> chi ghi
                # vao log (tra_ve/log JSONL) de biet, khong tao Action rac tro vao Norm
                # trung voi Action goc (se gay MERGE trung action_id vo nghia).

    _ghi_log({"norm_id": sid, "targets_biet": targets_biet, "ket_qua": tra_ve, "stats": stats})
    return stats


def main(limit: int | None = None, workers: int = 8) -> None:
    s = get_settings()
    s_local = s.model_copy(update={
        "neo4j_uri": "bolt://localhost:7687", "neo4j_user": "neo4j",
        "neo4j_password": "123qwe", "neo4j_database": "neo4j",
    })
    neo = Neo4jClient(s_local)
    neo.verify()
    llm = LLM(settings=s)
    q = QdrantClient(url=s.qdrant_url, api_key=s.qdrant_api_key or None, timeout=60,
                     check_compatibility=False)

    corpus_dir = Path(s.corpus_dir)
    local_idx = build_local_file_index(corpus_dir)

    rows = neo.run("""
        MATCH (a:Action)-[:ENACTED_BY]->(src:Norm)
        MATCH (a)-[:AFFECTS]->(tgt:Norm)
        WHERE a.loai IN ['SuaDoi', 'BaiBoTungPhan']
              AND coalesce(a.da_xu_ly_cap_dieu, false) = false
        RETURN src.norm_id AS sid, a.action_id AS action_id, tgt.norm_id AS tgt_norm_id,
               tgt.so_hieu AS tgt_so_hieu, a.loai AS loai_cu
    """)
    by_src: dict[str, list[dict]] = {}
    for r in rows:
        by_src.setdefault(r["sid"], []).append(dict(r))
    sids = list(by_src.keys())
    if limit:
        sids = sids[:limit]
    _progress(f"Cần xử lý: {len(sids):,} VB nguồn ({sum(len(by_src[s_]) for s_ in sids):,} cạnh AMENDS)")

    agg = {"tong_dich": 0, "resolved_dieu": 0, "khong_co_dieu": 0,
          "khong_resolve_duoc_component": 0, "loai_doi": 0, "dich_thieu_trong_ket_qua": 0}
    lock = threading.Lock()
    n_done = 0

    def _viec(sid: str) -> None:
        nonlocal n_done
        try:
            st = xu_ly_1_vb(neo, llm, local_idx, q, s.qdrant_collection, sid, by_src[sid])
            with lock:
                for k in agg:
                    agg[k] += st[k]
                n_done += 1
                if n_done % 100 == 0:
                    _progress(f"{n_done}/{len(sids)} VB · {agg}")
        except Exception as e:
            _progress(f"  ! LOI {sid}: {e!r}")

    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(_viec, sids))

    _progress(f"XONG: {n_done}/{len(sids)} VB · {agg}")


if __name__ == "__main__":
    lim = int(sys.argv[1]) if len(sys.argv) > 1 else None
    wk = int(sys.argv[2]) if len(sys.argv) > 2 else 8
    main(limit=lim, workers=wk)
