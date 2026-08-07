"""Chạy cổng C4 trên bộ đề đã sinh, ghi kết quả ngược lại file.

    python -m generator.run_c4 out/eval_set.jsonl

Gọi LLM một lần cho mỗi item (trừ G6/G8) — ~350 lời gọi trên bộ 400 câu.
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

from .common import setup_stdout
from . import gate_c4, paraphrase


def main() -> int:
    setup_stdout()
    path = Path(sys.argv[1] if len(sys.argv) > 1 else "out/eval_set.jsonl")
    items = [json.loads(l) for l in path.open(encoding="utf-8")]
    print(f"{path} — {len(items)} item")

    st = gate_c4.chay(items, paraphrase.make_llm())
    print(f"\n  đã kiểm {st['kiem']} | pass {st['pass']} | leak {st['leak']} "
          f"| lỗi API {st['loi_api']}")

    with path.open("w", encoding="utf-8") as f:
        for it in items:
            f.write(json.dumps(it, ensure_ascii=False) + "\n")

    theo_nhom = defaultdict(Counter)
    for it in items:
        theo_nhom[it["group"]][it["gates"].get("C4", "?")] += 1

    print(f"\n  {'nhóm':6} {'kiểm':>6} {'pass':>6} {'leak':>6}  tỷ lệ leak")
    for g in sorted(theo_nhom):
        c = theo_nhom[g]
        kiem = c["pass"] + c["leak"]
        if not kiem:
            print(f"  {g:6} {'—':>6} {'—':>6} {'—':>6}  (không áp dụng)")
            continue
        print(f"  {g:6} {kiem:6} {c['pass']:6} {c['leak']:6}"
              f"  {100.0*c['leak']/kiem:5.0f}%")

    leak = st["leak"]
    print(f"\n  tổng leak {leak}/{st['kiem']} = {100.0*leak/max(st['kiem'],1):.0f}%"
          f"  → đã hạ nhóm (do_retrieval = false), KHÔNG xoá (§2)")
    print("\n  Lưu ý đọc số: G3 trả lời NHỊ PHÂN (Có/Không) nên đoán bừa cũng trúng"
          "\n  ~68% theo phân bố thật — tỷ lệ leak của G3 KHÔNG so sánh được với các"
          "\n  nhóm khác và không nên đọc như bằng chứng rò rỉ kiến thức.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
