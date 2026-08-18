"""CLI sinh nhóm G2′ — câu hỏi "tại một thời điểm".

    python -m generator.run_g2 --n 80 --out out/g2.jsonl
    python -m generator.run_g2 --n 80 --paraphrase all --out out/g2.jsonl

`--paraphrase` opt-in (gọi API trả tiền) — như G7.
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from .common import nap_corpus, open_qdrant, verify_point_id, setup_stdout
from . import g2_temporal
from .run_g7 import chay_paraphrase

GENERATOR_VERSION = "1.0"
INDEX_VERSION = "bge-m3_v3"


def main() -> int:
    setup_stdout()
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=80)
    ap.add_argument("--pool", type=int, default=6000)
    ap.add_argument("--situation", type=float, default=0.6)
    ap.add_argument("--paraphrase", default=None)
    ap.add_argument("--out", default="out/g2.jsonl")
    args = ap.parse_args()

    corpus, store = nap_corpus(getattr(args, 'corpus', None)), open_qdrant()
    snapshot = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    khop, kiem = verify_point_id(store)
    print(f"point_id đối chiếu index: {khop}/{kiem} khớp")
    if kiem and khop != kiem:
        print("DỪNG — công thức point_id đã lệch so với index. Xem §10.1.")
        return 1

    items, stat = g2_temporal.build(corpus, store, n=args.n, pool=args.pool,
                                    ty_le_situation=args.situation)
    print(f"\nsinh {len(items)} item")
    for k, v in stat.items():
        print(f"  {k:26} {v}")

    if args.paraphrase:
        print(f"\nparaphrase ({args.paraphrase}) — gọi LLM:")
        for k, v in chay_paraphrase(items, args.paraphrase).items():
            print(f"  {k:26} {v}")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as f:
        for it in items:
            d = dataclasses.asdict(it)
            d["graph_snapshot"] = snapshot
            d["index_version"] = INDEX_VERSION
            d["generator_version"] = GENERATOR_VERSION
            f.write(json.dumps(d, ensure_ascii=False) + "\n")

    sit = sum(1 for x in items if x.question_form == "situation")
    print(f"\nđã ghi {len(items)} item -> {out}")
    print(f"  situation {sit}/{len(items)} = {100.0*sit/max(len(items),1):.0f}% (mục tiêu ≥50%)")
    for k in g2_temporal.KINDS:
        c = sum(1 for x in items if x.as_of_kind == k)
        print(f"  {k:16} {c:3}  = {100.0*c/max(len(items),1):.0f}% (mục tiêu ≥25%)")
    store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
