"""Chấm bộ đề: 4 chiều của `legal_rag.grader` + đo cấp chunk + triage (Mục 8).

    python -m evaluate.score --n 8              # thử 1 câu/nhóm
    python -m evaluate.score                    # chạy hết

Phần chấm nội dung dùng NGUYÊN `legal_rag.evaluation.grader.grade()` — không viết lại.
Bổ sung ba thứ họ chưa có:

  · context_recall / precision ở CẤP CHUNK  (Mục 6: dùng metric không-LLM cho retrieval
    vì nó rẻ và KHÔNG TRÔI giữa các lần chạy — điều kiện để so delta có nghĩa)
  · Set-F1 cho G4′ — grader bên kia dùng all(...), tức thiếu 1 văn bản là 0 điểm; danh
    sách sửa đổi cần phạt theo mức độ, không phải nhị phân
  · TRIAGE: sai vì retriever sót / retriever nhầm / synthesis  (bảng Mục 8)
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path

from generator.common import LEGAL_RAG_ROOT, setup_stdout  # noqa: F401  (nạp sys.path)
from .to_cases import chuyen


def _f1(du_doan: set, that: set) -> float:
    if not that:
        return 1.0 if not du_doan else 0.0
    if not du_doan:
        return 0.0
    c = len(du_doan & that)
    if not c:
        return 0.0
    p, r = c / len(du_doan), c / len(that)
    return 2 * p * r / (p + r)


def do_chunk(res: dict, case: dict, k: int = 12) -> dict:
    """Đo truy hồi ở cấp chunk + phân loại nguyên nhân sai (triage Mục 8)."""
    gold = set(case["_gold_chunks"])
    bay = set(case["_distractors"])
    lay = res.get("retrieved_chunks", []) or []
    topk = lay[:k]

    if not gold:
        return {"co_gold": False}

    trung = gold & set(topk)
    recall = len(trung) / len(gold)
    precision = (len(trung) / len(topk)) if topk else 0.0

    # Recall ở NHIỀU mức k. Khi đổi `rerank_top_k` của hệ, recall@k mới không so được
    # với lần chạy trước; giữ thêm recall@12 để đối chiếu đúng cùng cửa sổ. Và nếu
    # recall@30 tăng mà tỷ lệ đạt không tăng thì nút thắt đã dời sang ngân sách ngữ
    # cảnh (`synth_context_budget_chars`), không còn ở truy hồi.
    recall_tai = {kk: len(gold & set(lay[:kk])) / len(gold)
                  for kk in (5, 12, 30) if kk <= max(len(lay), kk)}

    # Bẫy có xếp TRÊN gold không? -> "retriever nhầm", khác hẳn "retriever sót".
    hang_gold = next((i for i, c in enumerate(topk) if c in gold), None)
    hang_bay = next((i for i, c in enumerate(topk) if c in bay), None)
    bay_tren = (hang_bay is not None
                and (hang_gold is None or hang_bay < hang_gold))
    return {"co_gold": True, "recall": recall, "precision": precision,
            "recall_tai": recall_tai, "so_lay_ve": len(lay),
            "gold_trong_topk": bool(trung), "hang_gold": hang_gold,
            "bay_xep_tren_gold": bay_tren}


def triage(checks, cq: dict) -> str:
    """Một nhãn nguyên nhân cho mỗi ca sai — đầu vào của bảng hành động Mục 8."""
    dat = checks and all(c.passed for c in checks)
    if dat:
        return "dat"
    if not cq.get("co_gold"):
        return "sai_khong_do_duoc_retrieval"
    if not cq["gold_trong_topk"]:
        return "retriever_sot"                 # gold không nằm trong top-k
    if cq["bay_xep_tren_gold"]:
        return "retriever_nham"                # bẫy trên gold
    return "synthesis"                         # gold có mặt mà vẫn trả lời sai


def main() -> int:
    setup_stdout()
    ap = argparse.ArgumentParser()
    ap.add_argument("--eval", default="out/eval_set.jsonl")
    ap.add_argument("--n", type=int, help="giới hạn số câu MỖI NHÓM (để thử)")
    ap.add_argument("--out", default="out/ket_qua_eval.json")
    ap.add_argument("--k", type=int, default=12, help="top-k khi đo recall")
    args = ap.parse_args()

    from legal_rag.evaluation.grader import grade, aggregate
    from legal_rag.evaluation.runner import _is_quota_error
    from .ask_full import ask_full

    cases = chuyen(Path(args.eval))
    if args.n:
        theo = defaultdict(list)
        for c in cases:
            theo[c["category"]].append(c)
        cases = [c for g in sorted(theo) for c in theo[g][: args.n]]
    print(f"{len(cases)} ca  ·  " + " · ".join(
        f"{g} {n}" for g, n in sorted(Counter(c['category'] for c in cases).items())))

    rows, all_checks, blocked = [], [], []
    for i, c in enumerate(cases, 1):
        at = date.fromisoformat(c["as_of_date"]) if c.get("as_of_date") else None
        try:
            res = ask_full(c["question"], at)
        except Exception as e:                                  # noqa: BLE001
            if _is_quota_error(e):
                blocked.append(c["id"])
            else:
                rows.append({"id": c["id"], "group": c["category"],
                             "loi": f"{type(e).__name__}: {e}"[:140]})
            continue

        checks = grade(res, c["expect"])
        all_checks.extend(checks)
        cq = do_chunk(res, c, k=args.k)
        row = {
            "id": c["id"], "group": c["category"], "form": c["_question_form"],
            "dat": bool(checks) and all(x.passed for x in checks),
            "checks": f"{sum(1 for x in checks if x.passed)}/{len(checks)}",
            "truot": [x.name for x in checks if not x.passed],
            "status": res.get("status"),
            "nguyen_nhan": triage(checks, cq), **cq,
        }
        if c["category"] == "G4":
            # Set-F1 thay vì all-or-nothing: thiếu 1 trong 5 văn bản không phải là
            # "sai hoàn toàn", và phạt nhị phân thì không thấy hệ đang tiến bộ.
            nêu = {x.get("so_hieu") for x in (res.get("citations") or [])
                   if x.get("so_hieu")} | {x.get("so_hieu") for x in
                                           (res.get("focus_norms") or []) if x.get("so_hieu")}
            row["set_f1"] = round(_f1(nêu, set(c["expect"]["norms_include"])), 3)
        rows.append(row)
        if i % 10 == 0:
            print(f"  ...{i}/{len(cases)}")

    bao = {"khi": datetime.now().isoformat(timespec="seconds"),
           "n_ca": len(cases), "n_cham": len(cases) - len(blocked),
           "blocked": blocked, "rows": rows,
           "agg": {k: list(v) for k, v in aggregate(all_checks).items()}}
    Path(args.out).write_text(json.dumps(bao, ensure_ascii=False, indent=1),
                              encoding="utf-8")
    in_bao_cao(bao, rows)
    print(f"\nđã ghi {args.out}")
    return 0


def in_bao_cao(bao: dict, rows: list[dict]) -> None:
    ok = [r for r in rows if "loi" not in r]
    print("\n── Chỉ số theo chiều (grader của legal-rag) ──")
    for d in ("citation", "validity", "content", "behavior", "overall"):
        p, n, r = bao["agg"][d]
        print(f"   {d:9} {p}/{n}" + (f"  ({r*100:.0f}%)" if r is not None else "  —"))

    print("\n── Theo nhóm ──")
    # KHÔNG in precision: hầu hết ca chỉ có 1 gold chunk nên precision@12 trần là
    # 1/12 = 8% — gần như hằng số, không nói lên điều gì. `hạng gold` (vị trí của
    # chunk đúng trong danh sách trả về) mới đọc ra hành động: hạng 1-3 mà vẫn sai
    # thì lỗi ở synthesis; hạng 9-12 thì rerank yếu; không có hạng thì retriever sót.
    print(f"   {'nhóm':6} {'đạt':>7} {'recall@k':>9} {'hạng gold':>10}   nguyên nhân sai")
    theo = defaultdict(list)
    for r in ok:
        theo[r["group"]].append(r)
    for g in sorted(theo):
        rs = theo[g]
        dat = sum(1 for r in rs if r["dat"])
        cg = [r for r in rs if r.get("co_gold")]
        rc = sum(r["recall"] for r in cg) / len(cg) if cg else None
        hang = [r["hang_gold"] + 1 for r in cg if r.get("hang_gold") is not None]
        nn = Counter(r["nguyen_nhan"] for r in rs if not r["dat"])
        print(f"   {g:6} {dat:3}/{len(rs):<3}"
              f" {(f'{rc*100:.0f}%' if rc is not None else '—'):>9}"
              f" {(f'{sum(hang)/len(hang):.1f}' if hang else '—'):>10}"
              f"   {', '.join(f'{k}={v}' for k, v in nn.most_common()) or '—'}")

    cg = [r for r in ok if r.get("co_gold") and r.get("recall_tai")]
    if cg:
        print("\n── Recall theo cửa sổ k (để so giữa các lần đổi rerank_top_k) ──")
        print(f"   số đoạn hệ trả về, trung bình: "
              f"{sum(r['so_lay_ve'] for r in cg)/len(cg):.1f}")
        for kk in (5, 12, 30):
            v = [r["recall_tai"][kk] for r in cg if kk in r["recall_tai"]]
            if v:
                print(f"   recall@{kk:<3} {sum(v)/len(v)*100:5.0f}%   ({len(v)} ca)")

    print("\n── Triage (Mục 8): sai ở đâu → sửa gì ──")
    HANH_DONG = {
        "retriever_sot": "gold ngoài top-k → tăng k, đổi embedding, thêm BM25 hybrid",
        "retriever_nham": "bẫy xếp trên gold → thêm rerank, lọc theo metadata",
        "synthesis": "gold có mặt mà trả lời sai → sửa prompt, đổi model",
        "sai_khong_do_duoc_retrieval": "nhóm không có gold chunk (G8) — xem behavior",
    }
    for k, v in Counter(r["nguyen_nhan"] for r in ok if not r["dat"]).most_common():
        print(f"   {v:3}  {k:28} {HANH_DONG.get(k, '')}")

    loi = [r for r in rows if "loi" in r]
    if loi:
        print(f"\n   {len(loi)} ca lỗi: " + "; ".join(f"{r['id']} {r['loi'][:60]}"
                                                     for r in loi[:3]))
    if bao["blocked"]:
        print(f"   {len(bao['blocked'])} ca BLOCKED bởi quota — chạy lại là đủ điểm")


if __name__ == "__main__":
    sys.exit(main())
