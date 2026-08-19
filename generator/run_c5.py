"""Dựng phiếu review C5, và tổng hợp kết quả sau khi người duyệt xong.

    python -m generator.run_c5 --n 80                      # dựng phiếu
    python -m generator.run_c5 --cham out/c5_ket_qua.csv   # tổng hợp -> ceiling
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path

from .common import nap_corpus, setup_stdout
from . import render_c5, sample_c5

NGUONG = 95.0


def dung(eval_path: Path, out: Path, n: int) -> int:
    items = [json.loads(l) for l in eval_path.open(encoding="utf-8")]
    snapshot = items[0].get("graph_snapshot", "?") if items else "?"
    c = nap_corpus()
    mau = sample_c5.chuan_bi(items, c, tong=n)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_c5.dung_html(mau, snapshot), encoding="utf-8")
    (out.parent / "c5_mau.jsonl").write_text(
        "\n".join(json.dumps(x, ensure_ascii=False) for x in mau), encoding="utf-8")

    theo = defaultdict(int)
    for it in mau:
        theo[it["group"]] += 1
    print(f"phiếu: {out}  ({len(mau)} câu)")
    print("  " + " · ".join(f"{g} {c}" for g, c in sorted(theo.items())))
    print(f"  mẫu thô: {out.parent / 'c5_mau.jsonl'}")
    print(f"\nMở {out.name} bằng trình duyệt, duyệt xong bấm Xuất CSV,")
    print(f"rồi chạy:  python -m generator.run_c5 --cham out/c5_ket_qua.csv")
    return 0


def cham(csv_path: Path) -> int:
    rows = list(csv.DictReader(csv_path.open(encoding="utf-8-sig")))
    theo = defaultdict(lambda: defaultdict(int))
    for r in rows:
        theo[r["group"]][r["verdict"] or "chua_cham"] += 1

    print(f"{csv_path} — {len(rows)} câu\n")
    print(f"  {'nhóm':6} {'đúng':>5} {'sai':>5} {'?':>4} {'chưa':>5}  ceiling")
    tong_d = tong_c = 0
    duoi = []
    for g in sorted(theo):
        c = theo[g]
        d, s, k = c["dung"], c["sai"], c["khong_chac"]
        cham_roi = d + s + k
        if not cham_roi:
            print(f"  {g:6} {'—':>5} {'—':>5} {'—':>4} {c['chua_cham']:5}  chưa chấm")
            continue
        # 'Không chắc' tính là KHÔNG đạt: trần trên phải là con số bảo thủ.
        ty = 100.0 * d / cham_roi
        tong_d += d
        tong_c += cham_roi
        canh = "" if ty >= NGUONG else "  ← DƯỚI NGƯỠNG"
        print(f"  {g:6} {d:5} {s:5} {k:4} {c['chua_cham']:5}  {ty:5.1f}%{canh}")
        if ty < NGUONG:
            duoi.append(g)

    if tong_c:
        print(f"\n  eval_set_ceiling (chung) = {100.0*tong_d/tong_c:.1f}%"
              f"   [{tong_d}/{tong_c}]")
    print("\n  'Không chắc' tính là KHÔNG đạt — trần trên phải là con số bảo thủ.")
    if duoi:
        print(f"\n  Nhóm dưới {NGUONG:.0f}%: {', '.join(duoi)}")
        print("  → KHÔNG đưa vào bộ eval tự động cho tới khi sửa khâu trích xuất,")
        print("    hoặc chuyển nhóm đó sang duyệt tay toàn bộ (Mục 1 bước 3).")
    else:
        print(f"\n  Mọi nhóm đạt ≥{NGUONG:.0f}%. Ghi eval_set_ceiling vào báo cáo và")
        print("  đọc kèm nó trong MỌI chỉ số ở Mục 6.")
    return 0


def main(argv: list[str] | None = None) -> int:
    setup_stdout()
    ap = argparse.ArgumentParser(prog="python -m generator.run_c5")
    ap.add_argument("--eval", default="out/eval_set.jsonl")
    ap.add_argument("--out", default="out/review_c5.html")
    ap.add_argument("--n", type=int, default=80, help="cỡ mẫu, chia đều các nhóm")
    ap.add_argument("--cham", help="đường dẫn CSV do phiếu xuất ra")
    args = ap.parse_args(argv)
    if args.cham:
        return cham(Path(args.cham))
    return dung(Path(args.eval), Path(args.out), args.n)


if __name__ == "__main__":
    raise SystemExit(main())
