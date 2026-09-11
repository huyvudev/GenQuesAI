"""Chạy lại rà soát 2 LLM CHỈ cho các văn bản nguồn có cạnh bị lỗi API hoàn toàn
(null_api — 1 hoặc cả 2 model không trả lời được ở lần chạy gốc trên VPS, KHÔNG phải
bất đồng thật) — lấy từ _con_lai_bat_dong_chua_xu_ly.jsonl (do _kiem_tra_con_lai_bat_dong.py
ghi ra, đã lọc còn da_duyet=true tức chưa xử lý).

Tái sử dụng trực tiếp logic gốc (xu_ly_1_vb, LLMClient, offpeak-wait...) từ
_rasoat_2llm_deploy/rasoat_2llm.py — chạy LOCAL (không cần VPS, quy mô nhỏ).

Ghi kết quả mới vào _retry_null_api_log.jsonl (checkpoint resumable, cùng format
{"norm_id","so_hieu","tieu_de","so_dich","ket_qua":[...]} như file gốc).

Chạy: cd genquesai/legal_rag && python _retry_null_api.py [workers]
Sau khi chạy xong, dùng _ap_dung_retry_null_api.py để áp fix cho các ca giờ đã đồng
thuận và khác graph hiện tại.
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
    xu_ly_1_vb, LLMClient, ApiTamThoiLoi, _load_env, ENV_PATH,
)
from neo4j import GraphDatabase

CON_LAI_PATH = os.path.join(HERE, "_con_lai_bat_dong_chua_xu_ly.jsonl")
LOG_PATH = os.path.join(HERE, "_retry_null_api_log.jsonl")
_GHI_LOCK = threading.Lock()


def lay_danh_sach_norm_id() -> list[str]:
    ids = set()
    with open(CON_LAI_PATH, encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            if r["loai_deepseek"] is None or r["loai_gemini"] is None:
                ids.add(r["norm_id"])
    return sorted(ids)


def _xu_ly_va_ghi(driver, llm_ds, llm_gm, nid: str, dem: dict) -> None:
    try:
        out = xu_ly_1_vb(driver, llm_ds, llm_gm, nid)
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
        if dem["i"] % 50 == 0:
            print(f"  {dem['i']}/{dem['tong']} VB đã xử lý lại", flush=True)


def main(workers: int = 6) -> None:
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
    wk = int(sys.argv[1]) if len(sys.argv) > 1 else 6
    main(workers=wk)
