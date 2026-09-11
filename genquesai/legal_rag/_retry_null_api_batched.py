"""Bản sửa của _retry_null_api.py — phát hiện 2026-09-09: retry lần đầu gần như vô ích
(2170/2418 cạnh vẫn null) vì nguyên nhân KHÔNG phải lỗi API ngẫu nhiên mà là JSON bị
CẮT CỤT (finish_reason=length) — VB có nhiều đích (vd 83 đích) cần nhiều token hơn công
thức cũ (500+200*n) cấp phát. Xác nhận qua debug 1 ca: dùng hết 17100/17100 token vẫn
chưa xong JSON.

Fix: CHIA NHỎ danh sách đích thành từng lô <= BATCH_SIZE, gọi LLM riêng cho từng lô rồi
gộp kết quả — không bao giờ 1 lần gọi phải xử lý quá nhiều đích cùng lúc nên không thể
bị cắt cụt vì thiếu token nữa.

Chạy: cd genquesai/legal_rag && python _retry_null_api_batched.py [workers]
"""
from __future__ import annotations
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

sys.stdout.reconfigure(encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "_rasoat_2llm_deploy"))

from rasoat_2llm import (  # type: ignore
    lay_du_lieu_nguon, _prompt_user, _SYS, _LOAI_HOP_LE,
    LLMClient, ApiTamThoiLoi, _load_env, deepseek_offpeak_giay_cho,
)
from neo4j import GraphDatabase

CON_LAI_PATH = os.path.join(HERE, "_con_lai_bat_dong_chua_xu_ly.jsonl")
LOG_PATH = os.path.join(HERE, "_retry_null_api_batched_log.jsonl")
BATCH_SIZE = 10
_GHI_LOCK = threading.Lock()


def lay_danh_sach_norm_id() -> list[str]:
    ids = set()
    with open(CON_LAI_PATH, encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            if r["loai_deepseek"] is None or r["loai_gemini"] is None:
                ids.add(r["norm_id"])
    return sorted(ids)


def _parse(out: dict) -> dict:
    m = {}
    for r in (out.get("ket_qua", []) if isinstance(out, dict) else []):
        sh, loai = r.get("target_so_hieu"), r.get("loai")
        if sh and loai in _LOAI_HOP_LE:
            m[sh] = {"loai": loai, "ly_do": r.get("ly_do", "")}
    return m


def _goi_theo_lo(llm, src: dict, targets: list[dict]) -> dict:
    """Gọi LLM cho danh sách targets, tự chia lô nếu dài, gộp kết quả lại."""
    gop: dict = {}
    for i in range(0, len(targets), BATCH_SIZE):
        lo = targets[i:i + BATCH_SIZE]
        user_prompt = _prompt_user(src, lo)
        max_tok = max(2000, 500 * len(lo))
        out = llm.chat_json(_SYS, user_prompt, max_tok)
        if out is None:
            raise ApiTamThoiLoi(f"{llm.provider} gọi API thất bại hẳn ở 1 lô")
        gop.update(_parse(out))
    return gop


def xu_ly_1_vb_batched(driver, llm_ds, llm_gm, norm_id: str) -> dict | None:
    with driver.session() as neo:
        data = lay_du_lieu_nguon(neo, norm_id)
    if not data:
        return None
    src, targets = data

    cho = deepseek_offpeak_giay_cho()
    if cho > 0:
        print(f"  Đang giờ cao điểm DeepSeek, chờ {cho:.0f}s...", flush=True)
        time.sleep(cho + 1)

    with ThreadPoolExecutor(max_workers=2) as pool:
        f_ds = pool.submit(_goi_theo_lo, llm_ds, src, targets)
        f_gm = pool.submit(_goi_theo_lo, llm_gm, src, targets)
        ds_map, gm_map = f_ds.result(), f_gm.result()

    ket_qua = []
    for t in targets:
        sh = t["so_hieu"]
        loai_ds = ds_map.get(sh, {}).get("loai")
        loai_gm = gm_map.get(sh, {}).get("loai")
        dong_thuan = loai_ds is not None and loai_ds == loai_gm
        ket_qua.append({
            "action_id": t["action_id"], "target_so_hieu": sh,
            "loai_hien_tai_graph": t["loai_hien_tai"],
            "loai_deepseek": loai_ds, "loai_gemini": loai_gm,
            "dong_thuan_2_model": dong_thuan,
            "khac_voi_graph": dong_thuan and loai_ds != t["loai_hien_tai"],
            "ly_do_deepseek": ds_map.get(sh, {}).get("ly_do", ""),
            "ly_do_gemini": gm_map.get(sh, {}).get("ly_do", ""),
        })
    return {"norm_id": norm_id, "so_hieu": src["so_hieu"], "tieu_de": src["tieu_de"],
           "so_dich": len(targets), "ket_qua": ket_qua}


def _xu_ly_va_ghi(driver, llm_ds, llm_gm, nid: str, dem: dict) -> None:
    try:
        out = xu_ly_1_vb_batched(driver, llm_ds, llm_gm, nid)
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
        print(f"  {dem['i']}/{dem['tong']} VB đã xử lý lại (batched)", flush=True)


def main(workers: int = 4) -> None:
    print("== Lấy danh sách VB nguồn cần chạy lại (có ít nhất 1 cạnh null_api) ==")
    danh_sach = lay_danh_sach_norm_id()
    print(f"  {len(danh_sach)} VB nguồn riêng biệt")

    da_xong = set()
    if os.path.exists(LOG_PATH):
        with open(LOG_PATH, encoding="utf-8") as f:
            for line in f:
                try:
                    da_xong.add(json.loads(line)["norm_id"])
                except Exception:
                    pass
    con_lai = [nid for nid in danh_sach if nid not in da_xong]
    print(f"  Đã xong từ trước (resume): {len(da_xong)} — còn lại: {len(con_lai)}")

    env = _load_env(os.path.join(HERE, "_rasoat_2llm_deploy", "rasoat_2llm.env"))
    driver = GraphDatabase.driver(env["NEO4J_URI"], auth=(env["NEO4J_USER"], env["NEO4J_PASSWORD"]))
    llm_ds = LLMClient("deepseek", env.get("DEEPSEEK_MODEL", "deepseek-v4-flash"),
                       env["DEEPSEEK_API_KEY"], "https://api.deepseek.com",
                       extra={"reasoning_effort": "none"})
    llm_gm = LLMClient("gemini", env.get("GEMINI_MODEL", "gemini-2.5-flash"),
                       env["GEMINI_API_KEY"], "https://generativelanguage.googleapis.com/v1beta/openai/",
                       extra={"extra_body": {"google": {"thinking_config": {"thinking_budget": 0}}}})

    dem = {"i": 0, "tong": len(con_lai)}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_xu_ly_va_ghi, driver, llm_ds, llm_gm, nid, dem) for nid in con_lai]
        for f in futures:
            f.result()

    print(f"\nXONG. Đã chạy lại {len(con_lai)} VB, ghi vào {LOG_PATH}")


if __name__ == "__main__":
    wk = int(sys.argv[1]) if len(sys.argv) > 1 else 4
    main(workers=wk)
