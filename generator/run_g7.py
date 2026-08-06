"""CLI sinh nhóm G7.

    python -m generator.run_g7 --n 90 --out out/g7.jsonl              # không gọi LLM
    python -m generator.run_g7 --n 90 --paraphrase 5                  # thử 5 câu
    python -m generator.run_g7 --n 90 --paraphrase all                # chạy hết

`--paraphrase` là OPT-IN vì nó gọi API trả tiền bằng key trong .env của legal-rag.
Không bật thì các câu `situation` giữ nguyên bản template, cổng C2 ghi `chua_paraphrase`.
"""
from __future__ import annotations

import argparse
import dataclasses
import io
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from .common import open_neo4j, open_qdrant, verify_point_id
from . import g7_content, paraphrase

GENERATOR_VERSION = "1.0"
INDEX_VERSION = "bge-m3_v3"


def chay_paraphrase(items, gioi_han, log=print) -> dict:
    """Viết lại các câu `situation`. Mọi bản viết lại đều qua cổng C2 (§I3)."""
    can = [x for x in items if x.question_form == "situation"]
    if gioi_han != "all":
        can = can[: int(gioi_han)]
    if not can:
        return {}
    llm = paraphrase.make_llm()
    st = {"goi": 0, "c2_pass": 0, "c2_fail": 0, "loi_api": 0}
    for it in can:
        goc = it.question_pre_paraphrase
        try:
            moi = paraphrase.viet_lai(llm, goc, it.persona)
            st["goi"] += 1
        except Exception as ex:
            it.gates["C2"] = f"loi_api:{type(ex).__name__}"
            st["loi_api"] += 1
            continue
        ok, ly_do = paraphrase.gate_c2(goc, moi)
        it.gates["C2"] = ly_do
        if ok:
            it.user_input = moi          # chỉ ghi khi qua cổng
            st["c2_pass"] += 1
        else:
            st["c2_fail"] += 1           # giữ nguyên bản template, KHÔNG sửa/thử lại
            log(f"  C2 loại: {ly_do}\n     gốc: {goc}\n     mới: {moi}")
    return st


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=90)
    ap.add_argument("--pool", type=int, default=4000)
    ap.add_argument("--situation", type=float, default=0.6, help="tỷ lệ câu dạng situation")
    ap.add_argument("--paraphrase", default=None, help="số câu cần viết lại, hoặc 'all'")
    ap.add_argument("--out", default="out/g7.jsonl")
    args = ap.parse_args()

    neo, store = open_neo4j(), open_qdrant()
    snapshot = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    khop, kiem = verify_point_id(store)
    print(f"point_id đối chiếu index: {khop}/{kiem} khớp")
    if kiem and khop != kiem:
        print("DỪNG — công thức point_id đã lệch so với index. Xem §10.1.")
        return 1

    items, stat = g7_content.build(neo, store, n=args.n, pool=args.pool,
                                   ty_le_situation=args.situation)
    print(f"\nsinh {len(items)} item")
    for k, v in stat.items():
        print(f"  {k:24} {v}")

    st_par = {}
    if args.paraphrase:
        print(f"\nparaphrase ({args.paraphrase}) — gọi LLM:")
        st_par = chay_paraphrase(items, args.paraphrase)
        for k, v in st_par.items():
            print(f"  {k:24} {v}")

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
    print(f"  situation {sit}/{len(items)} = {100.0*sit/max(len(items),1):.0f}%"
          f"  (mục tiêu ≥50% cho G7)")
    neo.close(); store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
