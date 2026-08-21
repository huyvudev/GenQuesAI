"""CDI · orchestrator — gói ingest→validate→embed→reconcile→audit có RETRY (CDI-4b; gỡ G1).

Không ép Prefect/Airflow (thừa cho 1 máy): orchestrator thuần-Python, nhẹ, test được.
`with_retry` THUẦN (test bằng hàm flaky + sleep giả). `ingest_pdfs` end-to-end cho watch-folder.
`canary_check` smoke: VB vừa nạp PHẢI có point Qdrant (bắt lỗi "nạp graph nhưng quên embed").
"""
from __future__ import annotations
import time
from pathlib import Path
from typing import Callable


def with_retry(fn: Callable, *, attempts: int = 3, delay: float = 2.0, backoff: float = 2.0,
               exceptions: tuple = (Exception,), sleep: Callable[[float], None] = time.sleep,
               log=print):
    """Chạy fn với retry + exponential backoff. Hết lượt -> raise lỗi cuối. Thuần (sleep injectable)."""
    last = None
    d = delay
    for i in range(1, attempts + 1):
        try:
            return fn()
        except exceptions as e:  # noqa: BLE001
            last = e
            if i >= attempts:
                break
            log(f"  [retry {i}/{attempts}] {type(e).__name__}: {e} — chờ {d:.0f}s")
            sleep(d)
            d *= backoff
    raise last


def canary_check(store, norm_ids: list[str]) -> list[str]:
    """Trả các norm_id vừa nạp nhưng KHÔNG có point Qdrant (lẽ ra phải có) — smoke retrieval."""
    if store is None:
        return []
    return [nid for nid in norm_ids if store.count_by_norm(nid) == 0]


def ingest_pdfs(pdf_dir, neo, store, emb, base: Path, *, corpus_sub: str = "manual",
                source: str = "pipeline", attempts: int = 2, log=print) -> dict:
    """End-to-end 1 thư mục PDF (chế độ AUTO, dùng metadata đoán + CDI gate làm lưới an toàn):
    prepare (đoán + kiểm trùng) → normalize → apply_rows (dedup+gate+ingest+embed+refs+ledger)
    → canary. Bọc retry cho lỗi tạm (mạng/DB/embedder). Idempotent nên retry an toàn."""
    from ..ingestion.importer import prepare_rows, normalize_row, apply_rows
    pdfs = sorted(Path(pdf_dir).glob("*.pdf"))
    if not pdfs:
        return {"pdf": 0, "nap": 0, "skipped": "no pdf"}
    rows = prepare_rows(pdfs, neo, log=log)
    norm_rows = [normalize_row(r["file"], r["so_hieu"], r["loai"], r["ten"], r["ngay_bh"], r["ngay_hl"])
                 for r in rows if not r["dup"]]
    norm_rows = [r for r in norm_rows if r]
    if not norm_rows:
        return {"pdf": len(pdfs), "nap": 0, "skipped": "tất cả trùng/thiếu số hiệu"}
    res = with_retry(
        lambda: apply_rows(norm_rows, neo, store, emb, base, Path(pdf_dir),
                           corpus_sub=corpus_sub, source=source, log=log),
        attempts=attempts, log=log)
    res["canary_missing"] = canary_check(store, res.get("norm_ids", []))
    if res["canary_missing"]:
        log(f"  [canary] ⚠ {len(res['canary_missing'])} VB nạp graph nhưng THIẾU vector: "
            + ", ".join(res["canary_missing"]))
    return res
