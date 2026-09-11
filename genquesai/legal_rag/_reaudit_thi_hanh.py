"""Gọi lại DeepSeek + Gemini cho 6.641 cạnh "nghi ngờ" (số hiệu đích CÓ xuất hiện trong
Điều khoản thi hành khi đọc đúng — khác với audit gốc bị bug chỉ đọc được node Điều rỗng)
— dùng ngữ cảnh GỌN (chỉ Điều khoản thi hành, không đọc cả văn bản) nên rẻ hơn audit gốc
nhiều dù số lượng cạnh tương đương.

Nhóm theo norm_id nguồn (nhiều cạnh chung 1 nguồn) để gọi 1 lần/nguồn thay vì 1 lần/cạnh.

Chạy: cd genquesai/legal_rag && python _reaudit_thi_hanh.py [workers]
"""
from __future__ import annotations
import json
import os
import sys
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, "D:/Project/GenQuesAI")
sys.path.insert(0, ".")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "_rasoat_2llm_deploy"))

from rasoat_2llm import LLMClient, ApiTamThoiLoi, _load_env, deepseek_offpeak_giay_cho, _LOAI_HOP_LE  # type: ignore
from genquesai.legal_rag.config import get_settings
from genquesai.legal_rag.graph.client import Neo4jClient
from _ngu_canh_gon import lay_dieu_khoan_thi_hanh

LOG_PATH = "_reaudit_thi_hanh_log.jsonl"
BATCH_SIZE = 10
_GHI_LOCK = threading.Lock()

_SYS = (
    "Bạn là chuyên gia pháp luật Việt Nam. Nhiệm vụ: đọc ĐIỀU KHOẢN THI HÀNH (phần cuối) "
    "của văn bản NGUỒN, xác định quan hệ THẬT với từng văn bản ĐÍCH trong danh sách — "
    "CHỈ dựa trên câu chữ tường minh, KHÔNG suy diễn theo chủ đề/tên gọi tương đồng. "
    "4 loại hợp lệ: ThayThe (thay thế toàn bộ đích), BaiBoToanBo (bãi bỏ toàn bộ đích), "
    "SuaDoi (sửa đổi một phần đích), BaiBoTungPhan (bãi bỏ một phần đích), "
    "KhongLienQuan (không có tuyên bố thật nào liên quan đích này). "
    'Trả JSON: {"ket_qua": [{"target_so_hieu": "...", "loai": '
    '"ThayThe|BaiBoToanBo|SuaDoi|BaiBoTungPhan|KhongLienQuan", "ly_do": "..."}]}'
)

_Q_SRC_META = "MATCH (n:Norm {norm_id:$nid}) RETURN n.so_hieu AS so_hieu, n.loai_vb AS loai_vb, n.cap_bac AS cap_bac, n.tieu_de AS tieu_de"
_Q_TGT_META = "MATCH (n:Norm {so_hieu:$sh}) RETURN n.loai_vb AS loai_vb, n.cap_bac AS cap_bac, n.tieu_de AS tieu_de LIMIT 1"
_Q_DA_DUYET = "MATCH (a:Action {action_id:$aid}) RETURN a.da_duyet AS da_duyet, a.loai AS loai"


def _breadcrumb(so_hieu, loai_vb, cap_bac, tieu_de) -> str:
    return f"{so_hieu} ({loai_vb}, cấp {cap_bac}) — {tieu_de or ''}"


def _prompt_user(src_meta, thi_hanh_text, targets) -> str:
    ds = "\n".join(f"- {_breadcrumb(t['so_hieu'], t.get('loai_vb'), t.get('cap_bac'), t.get('tieu_de'))}" for t in targets)
    return (
        f"DANH SÁCH VĂN BẢN ĐÍCH cần xác định quan hệ:\n{ds}\n\n"
        f"NGUỒN: {_breadcrumb(src_meta['so_hieu'], src_meta['loai_vb'], src_meta['cap_bac'], src_meta['tieu_de'])}\n\n"
        f"ĐIỀU KHOẢN THI HÀNH của văn bản NGUỒN:\n```\n{thi_hanh_text}\n```\n"
    )


def gom_theo_nguon() -> dict[str, list[dict]]:
    theo_nguon: dict[str, list[dict]] = defaultdict(list)
    seen = set()
    with open("_loc_re_ket_qua_v3.jsonl", encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            if not r.get("found_thi_hanh"):
                continue
            key = (r["norm_id"], r["target_so_hieu"])
            if key in seen:
                continue
            seen.add(key)
            theo_nguon[r["norm_id"]].append(r)
    return theo_nguon


def _parse(out: dict) -> dict:
    m = {}
    for r in (out.get("ket_qua", []) if isinstance(out, dict) else []):
        sh, loai = r.get("target_so_hieu"), r.get("loai")
        if sh and loai in _LOAI_HOP_LE:
            m[sh] = {"loai": loai, "ly_do": r.get("ly_do", "")}
    return m


def _goi_theo_lo(llm, src_meta, thi_hanh_text, targets: list[dict]) -> dict:
    gop: dict = {}
    for i in range(0, len(targets), BATCH_SIZE):
        lo = targets[i:i + BATCH_SIZE]
        user_prompt = _prompt_user(src_meta, thi_hanh_text, lo)
        max_tok = max(2000, 500 * len(lo))
        out = llm.chat_json(_SYS, user_prompt, max_tok)
        if out is None:
            raise ApiTamThoiLoi(f"{llm.provider} goi API that bai o 1 lo")
        gop.update(_parse(out))
    return gop


def xu_ly_1_nguon(neo, llm_ds, llm_gm, norm_id: str, canh: list[dict]) -> dict | None:
    src_rows = neo.run(_Q_SRC_META, nid=norm_id)
    if not src_rows:
        return None
    src_meta = src_rows[0]
    thi_hanh_text = lay_dieu_khoan_thi_hanh(neo, norm_id)
    if not thi_hanh_text:
        return None

    targets = []
    cache_tgt_meta: dict[str, dict] = {}
    for r in canh:
        sh = r["target_so_hieu"]
        if sh not in cache_tgt_meta:
            tm = neo.run(_Q_TGT_META, sh=sh)
            cache_tgt_meta[sh] = dict(tm[0]) if tm else {}
        targets.append({"so_hieu": sh, **cache_tgt_meta[sh], "action_id": r["action_id"], "nhom": r["nhom"]})

    cho = deepseek_offpeak_giay_cho()
    if cho > 0:
        print(f"  Đang giờ cao điểm DeepSeek, chờ {cho:.0f}s...", flush=True)
        time.sleep(cho + 1)

    with ThreadPoolExecutor(max_workers=2) as pool:
        f_ds = pool.submit(_goi_theo_lo, llm_ds, src_meta, thi_hanh_text, targets)
        f_gm = pool.submit(_goi_theo_lo, llm_gm, src_meta, thi_hanh_text, targets)
        ds_map, gm_map = f_ds.result(), f_gm.result()

    ket_qua = []
    for t in targets:
        sh = t["so_hieu"]
        loai_ds = ds_map.get(sh, {}).get("loai")
        loai_gm = gm_map.get(sh, {}).get("loai")
        rows = neo.run(_Q_DA_DUYET, aid=t["action_id"])
        loai_hien_tai = rows[0]["loai"] if rows else None
        da_duyet_hien_tai = rows[0]["da_duyet"] if rows else None
        ket_qua.append({
            "action_id": t["action_id"], "target_so_hieu": sh, "nhom": t["nhom"],
            "loai_hien_tai_graph": loai_hien_tai, "da_duyet_hien_tai": da_duyet_hien_tai,
            "loai_deepseek": loai_ds, "loai_gemini": loai_gm,
            "dong_thuan_2_model": loai_ds is not None and loai_ds == loai_gm,
            "ly_do_deepseek": ds_map.get(sh, {}).get("ly_do", ""),
            "ly_do_gemini": gm_map.get(sh, {}).get("ly_do", ""),
        })
    return {"norm_id": norm_id, "so_hieu_nguon": src_meta["so_hieu"], "ket_qua": ket_qua}


def _xu_ly_va_ghi(neo, llm_ds, llm_gm, nid: str, canh: list[dict], dem: dict) -> None:
    try:
        out = xu_ly_1_nguon(neo, llm_ds, llm_gm, nid, canh)
    except ApiTamThoiLoi as e:
        print(f"  {nid}: {e} — bỏ qua, thử lại lần sau. Nghỉ 300s...", flush=True)
        time.sleep(300)
        return
    except Exception as e:
        print(f"  LỖI xử lý {nid}: {e!r}", flush=True)
        out = None

    with _GHI_LOCK:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(out if out else {"norm_id": nid, "loi": True}, ensure_ascii=False) + "\n")
        dem["i"] += 1
        if dem["i"] % 100 == 0:
            print(f"  {dem['i']}/{dem['tong']} nguồn đã xử lý", flush=True)


def main(workers: int = 6) -> None:
    s = get_settings()
    neo = Neo4jClient(s)

    print("== Gom cạnh nghi ngờ theo nguồn ==")
    theo_nguon = gom_theo_nguon()
    print(f"  {sum(len(v) for v in theo_nguon.values())} cạnh, {len(theo_nguon)} nguồn riêng biệt")

    da_xong = set()
    if os.path.exists(LOG_PATH):
        with open(LOG_PATH, encoding="utf-8") as f:
            for line in f:
                try:
                    da_xong.add(json.loads(line)["norm_id"])
                except Exception:
                    pass
    con_lai = {k: v for k, v in theo_nguon.items() if k not in da_xong}
    print(f"  Đã xong từ trước (resume): {len(da_xong)} — còn lại: {len(con_lai)}")

    env = _load_env(os.path.join(HERE, "_rasoat_2llm_deploy", "rasoat_2llm.env"))
    llm_ds = LLMClient("deepseek", env.get("DEEPSEEK_MODEL", "deepseek-v4-flash"),
                       env["DEEPSEEK_API_KEY"], "https://api.deepseek.com",
                       extra={"reasoning_effort": "none"})
    llm_gm = LLMClient("gemini", env.get("GEMINI_MODEL", "gemini-2.5-flash"),
                       env["GEMINI_API_KEY"], "https://generativelanguage.googleapis.com/v1beta/openai/",
                       extra={"extra_body": {"google": {"thinking_config": {"thinking_budget": 0}}}})

    dem = {"i": 0, "tong": len(con_lai)}

    def _worker(nid_canh):
        nid, canh = nid_canh
        _xu_ly_va_ghi(neo, llm_ds, llm_gm, nid, canh, dem)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(_worker, con_lai.items()))

    print(f"\nXONG. Đã xử lý {len(con_lai)} nguồn, ghi vào {LOG_PATH}")


if __name__ == "__main__":
    wk = int(sys.argv[1]) if len(sys.argv) > 1 else 6
    main(workers=wk)
