"""Sinh TOÀN BỘ bộ đề 400 câu và gộp thành một file.

    python -m generator.run_all --out out/eval_set.jsonl
    python -m generator.run_all --paraphrase all --out out/eval_set.jsonl

Quota theo Mục 4: G1 50 · G2′ 80 · G3 60 · G4′ 40 · G5 30 · G6 25 · G7 90 · G8 25.

G6 ra lò với `status = "cho_review"` và KHÔNG được tính vào bộ đề dùng được cho tới
khi có người duyệt điều kiện (3) §4.2 — script báo riêng, không gộp vào tổng "sẵn sàng".
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from .common import open_neo4j, open_qdrant, setup_stdout, verify_point_id
from . import (g1_replaces, g2_temporal, g3_chain, g4_history,
               g5_transition, g6_conflict, g7_content, g8_unanswerable)
from .run_g7 import chay_paraphrase

GENERATOR_VERSION = "1.0"
INDEX_VERSION = "bge-m3_v3"

NHOM = [
    ("G1", g1_replaces, 50, dict(pool=2500)),
    ("G2", g2_temporal, 80, dict(pool=8000)),
    ("G3", g3_chain, 60, dict(pool=4000)),
    ("G4", g4_history, 40, dict(pool=1500)),
    ("G5", g5_transition, 30, dict(pool=900)),
    ("G6", g6_conflict, 25, dict(pool=4000)),
    ("G7", g7_content, 90, dict(pool=6000)),
    ("G8", g8_unanswerable, 25, dict()),
]


def main() -> int:
    setup_stdout()
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="out/eval_set.jsonl")
    ap.add_argument("--paraphrase", default=None, help="'all' hoặc số câu mỗi nhóm")
    ap.add_argument("--chi", default=None, help="chỉ chạy các nhóm này, vd 'G3,G5'")
    args = ap.parse_args()

    neo, store = open_neo4j(), open_qdrant()
    snapshot = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    khop, kiem = verify_point_id(store)
    print(f"point_id đối chiếu index: {khop}/{kiem} khớp")
    if kiem and khop != kiem:
        print("DỪNG — công thức point_id đã lệch so với index. Xem §10.1.")
        return 1

    chon = set(args.chi.split(",")) if args.chi else None
    tat_ca, tong_ket = [], []

    for ma, mod, quota, kw in NHOM:
        if chon and ma not in chon:
            continue
        print(f"\n{'='*66}\n{ma} — quota {quota}")
        items, stat = mod.build(neo, store, n=quota, **kw)
        for k, v in stat.items():
            print(f"  {k:28} {v}")

        if args.paraphrase and any(
                getattr(x, "question_form", "") == "situation" for x in items):
            st = chay_paraphrase(items, args.paraphrase, log=lambda *_: None)
            if st:
                print(f"  paraphrase: {st.get('c2_pass',0)} qua / "
                      f"{st.get('c2_fail',0)} loại / {st.get('loi_api',0)} lỗi API")

        tat_ca.extend(items)
        sit = sum(1 for x in items if getattr(x, "question_form", "") == "situation")
        tong_ket.append((ma, quota, len(items), sit))

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as f:
        for it in tat_ca:
            d = dataclasses.asdict(it)
            d.setdefault("status", "san_sang")
            d["graph_snapshot"] = snapshot
            d["index_version"] = INDEX_VERSION
            d["generator_version"] = GENERATOR_VERSION
            f.write(json.dumps(d, ensure_ascii=False) + "\n")

    print(f"\n{'='*66}\nĐÃ GHI {len(tat_ca)} item -> {out}\n")
    print(f"  {'nhóm':6} {'quota':>6} {'sinh':>6} {'situation':>10}")
    for ma, q, c, s in tong_ket:
        canh = "" if c >= q else "  ← THIẾU"
        print(f"  {ma:6} {q:6} {c:6} {s:10}{canh}")

    cho_review = sum(1 for x in tat_ca
                     if getattr(x, "status", "san_sang") == "cho_review")
    print(f"\n  tổng sinh          {len(tat_ca)}")
    print(f"  chờ review (G6)    {cho_review}  ← chưa dùng được (§4.2)")
    print(f"  sẵn sàng           {len(tat_ca) - cho_review}")
    sit = sum(1 for x in tat_ca if getattr(x, "question_form", "") == "situation")
    print(f"  situation          {sit} = {100.0*sit/max(len(tat_ca),1):.0f}%"
          f"  (mục tiêu ≥55%)")
    neo.close(); store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
