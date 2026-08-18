"""Kiểm bộ đề theo tiêu chí nghiệm thu Mục 9.

    python -m generator.validate out/eval_set.jsonl

Kiểm được bằng máy thì phải kiểm bằng máy — đọc bằng mắt không lặp lại được, và
mỗi lần sinh lại bộ đề đều phải qua đúng bộ kiểm này.
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

from .common import co_so_hieu, setup_stdout

QUOTA = {"G1": 50, "G2": 80, "G3": 60, "G4": 40, "G5": 30, "G6": 25, "G7": 90, "G8": 25}
# Ba nhóm này KHÔNG dựng được câu `situation` vì bản chất câu hỏi:
#   G1 phải nêu số hiệu mới hỏi được "văn bản nào thay thế X"
#   G6 phải nêu cả hai văn bản mới dựng được tình huống xung đột
#   G8 hỏi về văn bản/điều KHÔNG tồn tại nên buộc phải nêu định danh
CHI_LOOKUP = {"G1", "G6", "G8"}
# G8 không có gold_spans là ĐÚNG THIẾT KẾ: câu không có đáp án thì không có đoạn nào
# để trích dẫn. Đây là ngoại lệ duy nhất của tiêu chí "100% item có gold_spans".
KHONG_CAN_SPAN = {"G8"}


def kiem(path: Path) -> int:
    rows = [json.loads(l) for l in path.open(encoding="utf-8")]
    nhom = Counter(r["group"] for r in rows)
    loi, canh = [], []

    def ok(dieu_kien, mo_ta, chi_tiet=""):
        print(f"  [{'OK ' if dieu_kien else 'LỖI'}] {mo_ta}"
              + (f"  — {chi_tiet}" if chi_tiet else ""))
        if not dieu_kien:
            loi.append(mo_ta)

    print(f"\n{path}  —  {len(rows)} item\n")

    print("Quota (Mục 4):")
    for g, q in QUOTA.items():
        ok(nhom.get(g, 0) == q, f"{g} = {q}", f"thực tế {nhom.get(g, 0)}")

    print("\nGrounding (Mục 2):")
    ref_hop_le = {"span", "field", "composed", "field[]", "label", "nhan"}
    xau = [r["id"] for r in rows if r["reference_type"] not in ref_hop_le]
    ok(not xau, "100% reference_type hợp lệ (0 item do LLM viết)", str(xau[:5]))

    thieu = [r["id"] for r in rows
             if r["group"] not in KHONG_CAN_SPAN and not r["gold_spans"]]
    ok(not thieu, "gold_spans không rỗng (trừ G8)",
       f"{len(thieu)} thiếu: {thieu[:5]}")

    khoa = {"expr_id", "part", "chunk_id", "start", "end", "chunk_text_sha256"}
    thieu_khoa = [r["id"] for r in rows for s in r["gold_spans"]
                  if not khoa <= set(s)]
    ok(not thieu_khoa, "gold_spans đủ 6 trường khoá (§7.1)", str(thieu_khoa[:5]))

    c1_fail = [r["id"] for r in rows
               if r["gates"].get("C1", "").startswith(("hash_", "offset_", "chunk_"))]
    ok(not c1_fail, "0 item rớt C1", str(c1_fail[:5]))

    # C2 loại thì GIỮ BẢN TEMPLATE — item vẫn hợp lệ. Tiêu chí đúng là "không bản
    # viết lại vi phạm nào LỌT VÀO bộ đề", tức user_input phải khác bản LLM đã bị loại.
    c2_loai = [r["id"] for r in rows
               if r["gates"].get("C2", "").startswith(("them_thuc_the", "qua_dai",
                                                       "mat_dang", "qua_ngan"))]
    lot = [r["id"] for r in rows if r["id"] in set(c2_loai)
           and r["user_input"] != r["question_pre_paraphrase"]]
    ok(not lot, "0 bản viết lại vi phạm C2 lọt vào bộ đề", str(lot[:5]))
    if c2_loai:
        print(f"       ({len(c2_loai)} bản viết lại bị C2 loại, đã giữ bản template)")

    print("\nDạng câu (§5.2):")
    sit = [r for r in rows if r["question_form"] == "situation"]
    du_dieu_kien = [r for r in rows if r["group"] not in CHI_LOOKUP]
    pct_all = 100.0 * len(sit) / len(rows)
    pct_el = 100.0 * len(sit) / max(len(du_dieu_kien), 1)
    ok(pct_el >= 55, "situation ≥55% trong các nhóm hỗ trợ cả hai dạng",
       f"{len(sit)}/{len(du_dieu_kien)} = {pct_el:.0f}%")
    print(f"       (trên toàn bộ: {len(sit)}/{len(rows)} = {pct_all:.0f}% — "
          f"{sum(nhom[g] for g in CHI_LOOKUP)} câu thuộc nhóm chỉ-lookup)")

    for g in ("G2", "G7"):
        s = sum(1 for r in rows if r["group"] == g and r["question_form"] == "situation")
        ok(s >= nhom[g] * 0.5, f"{g} situation ≥50%", f"{s}/{nhom[g]}")

    lo = [r["id"] for r in sit if co_so_hieu(r["user_input"])]
    ok(not lo, "0 câu situation lộ số hiệu", f"{len(lo)}: {lo[:5]}")

    # Hai câu hỏi GIỐNG HỆT là hai lần chấm cùng một thứ — và nếu `reference` của
    # chúng khác nhau thì tệ hơn nhiều: hệ trả lời kiểu gì cũng trượt một câu.
    # Đã xảy ra ở hai chỗ khác nhau (G8 quay vòng chủ đề, G3 situation dựng từ cùng
    # một văn bản con), nên kiểm ở tầng nghiệm thu chứ đừng vá từng nhóm.
    dem_cau = Counter(r["user_input"] for r in rows)
    trung = [c for c, k in dem_cau.items() if k > 1]
    xung_dot = [c for c in trung
                if len({r.get("reference") for r in rows if r["user_input"] == c}) > 1]
    ok(not trung, "0 câu hỏi trùng nguyên văn",
       f"{len(trung)} câu trùng"
       + (f", trong đó {len(xung_dot)} câu ĐÁP ÁN MÂU THUẪN" if xung_dot else "")
       + (f": {[r['id'] for r in rows if r['user_input'] in trung][:6]}" if trung else ""))

    print("\nG2′ — mốc thời gian (§4.4):")
    g2 = [r for r in rows if r["group"] == "G2"]
    kinds = Counter(r.get("as_of_kind") for r in g2)
    for k in ("mid_interval", "near_boundary", "on_boundary"):
        ok(kinds[k] >= len(g2) * 0.25, f"{k} ≥25%", f"{kinds[k]}/{len(g2)}")
    lech = [r["id"] for r in g2
            if (r["as_of_kind"] == "on_boundary") != (r["reference_type"] == "composed")]
    ok(not lech, "as_of_kind khớp reference_type", str(lech[:5]))

    print("\nG4′/G5 — bộ lọc nguồn (§4.5):")
    g5 = [r for r in rows if r["group"] == "G5"]
    thap = [r["id"] for r in g5 if (r["reference_fields"].get("confidence") or 0) < 0.9]
    ok(not thap, "G5 confidence ≥0.9", str(thap[:5]))
    g4 = [r for r in rows if r["group"] == "G4"]
    it_qua = [r["id"] for r in g4 if len(r["reference_fields"].get("danh_sach", [])) < 2]
    ok(not it_qua, "G4 mỗi câu ≥2 văn bản (câu hỏi danh sách)", str(it_qua[:5]))

    print("\nC4 — kiểm cần thiết (§I4b):")
    da_c4 = [r for r in rows if r["gates"].get("C4") not in (None, "not_run")]
    if len(da_c4) < len(rows):
        print(f"  [--- ] chưa chạy C4 trên {len(rows)-len(da_c4)} item "
              f"— chạy `python -m generator.run_c4`")
    else:
        kiem = [r for r in rows if r["gates"]["C4"] in ("pass", "leak")]
        leak = [r for r in kiem if r["gates"]["C4"] == "leak"]
        ty = 100.0 * len(leak) / max(len(kiem), 1)
        ok(ty <= 10, "tỷ lệ leak ≤10% (bộ đề thật sự cần retrieval)",
           f"{len(leak)}/{len(kiem)} = {ty:.0f}%")
        tu_choi = sum(1 for r in kiem if r.get("c4_diem") == 0)
        print(f"       ({tu_choi}/{len(kiem)} = "
              f"{100.0*tu_choi/max(len(kiem),1):.0f}% mô hình từ chối hoàn toàn)")
        lech = [r["id"] for r in kiem
                if (r["gates"]["C4"] == "leak") == bool(r.get("do_retrieval", True))]
        ok(not lech, "leak đã hạ nhóm (do_retrieval=false)", str(lech[:5]))

    print("\nReview tay:")
    g6 = [r for r in rows if r["group"] == "G6"]
    ok(all(r.get("status") == "cho_review" for r in g6),
       "G6 đánh dấu cho_review, chưa tính vào bộ dùng được", f"{len(g6)} câu")
    chua = [r["id"] for r in rows if r["gates"].get("C5") != "not_sampled"
            and not r["human_verified"]]
    print(f"  [--- ] C5 chưa lấy mẫu — cần chạy để chốt eval_set_ceiling (Mục 1)")

    print("\nPhiên bản:")
    for f in ("graph_snapshot", "index_version", "generator_version"):
        ok(all(r.get(f) for r in rows), f"mọi item có {f}")

    print(f"\n{'='*62}")
    if loi:
        print(f"KHÔNG ĐẠT — {len(loi)} tiêu chí lỗi:")
        for x in loi:
            print(f"  · {x}")
        return 1
    print("ĐẠT toàn bộ tiêu chí kiểm được bằng máy.")
    print("Còn lại cần người: C5 (review mẫu) và duyệt 25 ca G6.")
    return 0


if __name__ == "__main__":
    setup_stdout()
    raise SystemExit(kiem(Path(sys.argv[1] if len(sys.argv) > 1
                              else "out/eval_set.jsonl")))
