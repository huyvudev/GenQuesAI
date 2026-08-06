"""CLI sinh nhóm G1.

    <venv>/python.exe -m generator.run_g1 --n 50 --out out/g1.jsonl

Cần Neo4j + Qdrant đang chạy. Không cần LLM, không cần ragas.
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from .common import open_neo4j, open_qdrant, verify_point_id, setup_stdout
from . import g1_replaces

GENERATOR_VERSION = "1.0"
INDEX_VERSION = "bge-m3_v3"


def main() -> int:
    setup_stdout()
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=50, help="số câu cần sinh (quota G1 = 50)")
    ap.add_argument("--pool", type=int, default=600, help="số ứng viên rút từ đồ thị")
    ap.add_argument("--out", default="out/g1.jsonl")
    args = ap.parse_args()

    neo, store = open_neo4j(), open_qdrant()
    snapshot = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Chốt chặn trước khi sinh: bản chép point_id phải khớp index thật (§9).
    khop, kiem = verify_point_id(store)
    print(f"point_id đối chiếu index: {khop}/{kiem} khớp")
    if kiem and khop != kiem:
        print("DỪNG — công thức point_id đã lệch so với index. Xem §10.1.")
        return 1

    items, stat = g1_replaces.build(neo, store, n=args.n, pool=args.pool)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as f:
        for it in items:
            d = dataclasses.asdict(it)
            d["graph_snapshot"] = snapshot
            d["index_version"] = INDEX_VERSION
            d["generator_version"] = GENERATOR_VERSION
            f.write(json.dumps(d, ensure_ascii=False) + "\n")

    print(f"\nđã ghi {len(items)} item -> {out}")
    print("thống kê cổng:")
    for k, v in stat.items():
        print(f"  {k:16} {v}")
    if items:
        xet = sum(stat[k] for k in stat if k != "ung_vien")
        print(f"  {'ty_le_song_sot':22} {100.0 * len(items) / max(xet, 1):.1f}% "
              f"({len(items)}/{xet} ứng viên đã xét)")
    neo.close(); store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
