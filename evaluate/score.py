"""Chấm bộ đề: 4 chiều của `framework.grader` + đo cấp chunk + triage (Mục 8).

    python -m evaluate.score --n 8                 # thử 1 câu/nhóm
    python -m evaluate.score                       # chạy hết (chế độ 'cu')
    python -m evaluate.score --che-do moi          # bật hộp đen + Set-F1

Phần chấm nội dung dùng `framework.grader` — bản chép từ `legal_rag.evaluation.grader`
(ROADMAP A3: framework phải chạy được trên máy KHÔNG có repo `Chatbot-Law`). Chế độ
mặc định `cu` tái lập đúng ngữ nghĩa bản gốc, đã kiểm 0/375 lệch, nên các baseline đã
commit vẫn so được. Bổ sung ba thứ bản gốc không có:

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
    """Đo truy hồi ở cấp chunk + phân loại nguyên nhân sai (triage Mục 8).

    A2: đối chiếu theo NỘI DUNG (`framework.doi_chieu`), id chỉ còn là đường nhanh.
    Nhờ đó hệ không chung không gian id với corpus — hộp đen, chunk khác cách — vẫn
    đo được recall. Hệ quả cần biết khi đọc số: recall thành LIÊN TỤC (độ phủ 0..1
    của từng span) thay vì nhị phân; với hộp trắng legal-rag hai đường cho cùng kết
    quả vì id trúng là phủ 1.0.
    """
    from framework.doi_chieu import doi_chieu_gold

    gold_spans = case.get("_gold_spans") or [{"chunk_id": c}
                                             for c in case["_gold_chunks"]]
    gold_texts = case.get("_gold_texts") or []
    ids = res.get("retrieved_chunks", []) or []
    ctx = res.get("retrieved_contexts", []) or []

    if not gold_spans:
        return {"co_gold": False}

    kq = doi_chieu_gold(gold_spans, gold_texts, ids, ctx, k=k)
    recall = sum(x.diem for x in kq) / len(kq)
    khop = [x for x in kq if x.khop]
    so_lay_ve = max(len(ids), len(ctx))
    precision = (len(khop) / min(so_lay_ve, k)) if so_lay_ve else 0.0

    # Recall ở NHIỀU mức k. Khi đổi `rerank_top_k` của hệ, recall@k mới không so được
    # với lần chạy trước; giữ thêm recall@12 để đối chiếu đúng cùng cửa sổ.
    recall_tai = {}
    for kk in (5, 12, 30):
        r_kk = doi_chieu_gold(gold_spans, gold_texts, ids, ctx, k=kk)
        recall_tai[kk] = sum(x.diem for x in r_kk) / len(r_kk)

    hang_gold = min((x.hang for x in khop if x.hang is not None), default=None)

    # Bẫy có xếp TRÊN gold không? -> "retriever nhầm", khác hẳn "retriever sót".
    # Bẫy đối chiếu bằng CẢ hai đường như gold: id (bộ đề cũ) + text (bộ đề mới).
    bay_spans = [{"chunk_id": b} for b in (case.get("_distractors") or [])]
    bay_texts = case.get("_distractor_texts") or []
    if len(bay_texts) < len(bay_spans):
        bay_texts = bay_texts + [""] * (len(bay_spans) - len(bay_texts))
    kq_bay = doi_chieu_gold(bay_spans, bay_texts, ids, ctx, k=k) if bay_spans else []
    hang_bay = min((x.hang for x in kq_bay if x.khop and x.hang is not None),
                   default=None)
    bay_tren = (hang_bay is not None
                and (hang_gold is None or hang_bay < hang_gold))
    return {"co_gold": True, "recall": round(recall, 3),
            "precision": round(precision, 3),
            "recall_tai": {kk: round(v, 3) for kk, v in recall_tai.items()},
            "so_lay_ve": so_lay_ve,
            "gold_trong_topk": bool(khop), "hang_gold": hang_gold,
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
    ap.add_argument("--che-do", dest="che_do", default="cu", choices=("cu", "moi"),
                    help="'cu' = ngữ nghĩa grader gốc legal-rag (so được với baseline "
                         "đã lưu); 'moi' = thêm hỗ trợ hộp đen + Set-F1")
    ap.add_argument("--adapter", default="legal_rag", choices=("legal_rag", "http"),
                    help="hệ được đo (B): 'legal_rag' = hộp trắng trên máy này; "
                         "'http' = hộp đen qua endpoint POST JSON (cần --url)")
    ap.add_argument("--url", help="endpoint cho --adapter http")
    args = ap.parse_args()

    # Grader của FRAMEWORK, không import từ legal-rag nữa: framework phải chạy được
    # trên máy không có repo đó (ROADMAP A3). `che_do="cu"` tái lập đúng ngữ nghĩa
    # grader gốc — đã kiểm 0/375 lệch — để loạt baseline đã commit vẫn so được.
    # Đổi sang "moi" là hành động CÓ Ý THỨC và phải re-baseline.
    from framework.grader import aggregate, grade as _grade, la_loi_quota as _is_quota_error
    from .adapters import tao_adapter
    he = tao_adapter(args.adapter, args.url)

    def grade(res, ex, nhom=None):
        # Set-F1 CHỈ cho G4′ — nhóm duy nhất có đáp án là DANH SÁCH, nơi thừa cũng sai
        # như thiếu. Áp cho mọi nhóm là phạt hệ vì nhắc tới chính văn bản ĐƯỢC HỎI:
        # câu "87/2011/TT-BNNPTNT bị thay thế bởi văn bản nào?" buộc hệ phải nhắc
        # 87/2011 để trả lời mạch lạc, và Set-F1 tính đó là "thừa" -> F1 = 0.5 -> trượt
        # dù đáp án hoàn toàn đúng. Đo thật: G1/G3/G4 trượt 100%, G7 trượt 79/90.
        return _grade(res, ex, che_do=args.che_do,
                      set_f1_cho=({"norms_include"}
                                  if args.che_do == "moi" and nhom == "G4"
                                  else frozenset()))

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
            res = he.ask(c["question"], at).thanh_dict()
        except Exception as e:                                  # noqa: BLE001
            if _is_quota_error(e):
                blocked.append(c["id"])
            else:
                rows.append({"id": c["id"], "group": c["category"],
                             "loi": f"{type(e).__name__}: {e}"[:140]})
            continue

        checks = grade(res, c["expect"], c["category"])
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
