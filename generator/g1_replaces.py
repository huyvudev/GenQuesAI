"""G1 — 'Văn bản X bị thay thế bởi văn bản nào?'

Nhóm đơn giản nhất trong 8 nhóm: reference_type = `field`, chấm exact-match, KHÔNG
dùng LLM ở bất kỳ bước nào. Dựng trước tiên để hiệu chỉnh 5 cổng kiểm (§10 bước 4).

Chiều quan hệ đã xác minh trên dữ liệu thật 2026-08-06:
    (a)-[:REPLACES]->(b)  =  a THAY THẾ b        (a mới hơn b)
    7.933/8.003 cạnh có a.ngay_hieu_luc > b.ngay_hieu_luc.
70 cạnh còn lại (24 ngược chiều + 46 cùng ngày) bị loại ở mệnh đề WHERE bên dưới —
chúng là lỗi dữ liệu, dùng làm đáp án đúng sẽ hạ trần eval_set_ceiling.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

from .common import core_so_hieu
from .gold import GoldSpan, find_evidence_span, gate_c1

# Tối đa bao nhiêu câu dùng chung một văn bản thay thế. Một văn bản mới có thể bãi bỏ
# hàng chục văn bản cũ -> không chặn thì nhiều câu chung một đáp án, bộ đề mất đa dạng.
MAX_MOI_LAP = 2
# Điểm bằng chứng tối thiểu (gold.py). >=3 nghĩa là có từ khoá bãi bỏ đứng trước số
# hiệu, tức span thật sự là điều khoản bãi bỏ chứ không phải chỗ dẫn chiếu tình cờ.
MIN_DIEM_BANG_CHUNG = 3

# Chỉ lấy văn bản bị thay bởi ĐÚNG MỘT văn bản -> đáp án đơn trị, chấm exact-match
# được. Ca bị nhiều văn bản cùng thay là câu hỏi dạng danh sách, thuộc về G4'.
SELECT = """
MATCH (moi:Norm)-[:REPLACES]->(cu:Norm)
WHERE moi.ngay_hieu_luc IS NOT NULL AND cu.ngay_hieu_luc IS NOT NULL
  AND moi.ngay_hieu_luc > cu.ngay_hieu_luc
  AND moi.so_hieu IS NOT NULL AND cu.so_hieu IS NOT NULL
WITH cu, collect(DISTINCT moi) AS ds
WHERE size(ds) = 1
WITH cu, ds[0] AS moi
// anh em gần: văn bản khác cũng bị chính `moi` thay thế -> bẫy tự nhiên (§5.3)
CALL (moi, cu) {
  MATCH (moi)-[:REPLACES]->(anh_em:Norm)
  WHERE anh_em.norm_id <> cu.norm_id AND anh_em.so_hieu IS NOT NULL
  RETURN collect(anh_em.so_hieu)[0..3] AS anh_em_ids
}
RETURN cu.norm_id AS cu_id, cu.so_hieu AS cu_so_hieu, cu.tieu_de AS cu_tieu_de,
       cu.loai_vb AS cu_loai, cu.ngay_hieu_luc AS cu_hieu_luc,
       moi.norm_id AS moi_id, moi.so_hieu AS moi_so_hieu, moi.tieu_de AS moi_tieu_de,
       moi.ngay_hieu_luc AS moi_hieu_luc,
       anh_em_ids AS anh_em
ORDER BY size(anh_em_ids) DESC, moi.ngay_hieu_luc DESC
LIMIT $pool
"""

# Khuôn câu hỏi cố định — bất biến I1. Đa dạng hoá bề mặt bằng cách chọn khuôn,
# KHÔNG bằng LLM: G1 toàn dạng `lookup` nên không đi qua paraphrase().
TEMPLATES = [
    "{cu} bị thay thế bởi văn bản nào?",
    "Văn bản nào thay thế {cu}?",
    "{cu} hiện đã được thay thế bằng văn bản nào chưa?",
    "Cho biết văn bản thay thế {cu}.",
]


@dataclass
class Item:
    id: str
    group: str = "G1"
    question_form: str = "lookup"
    persona: str = "can_bo_phap_che"
    user_input: str = ""
    question_template: str = ""
    reference: str = ""
    reference_type: str = "field"
    reference_fields: dict = field(default_factory=dict)
    gold_spans: list = field(default_factory=list)
    reference_contexts: list = field(default_factory=list)
    gold_node_ids: list = field(default_factory=list)
    distractor_ids: list = field(default_factory=list)
    evidence: str = "graph_only"          # 'span' khi tìm được bằng chứng văn bản
    evidence_score: int = 0               # xem gold._diem_bang_chung
    gates: dict = field(default_factory=dict)
    grader: str = "exact_match"
    difficulty: str = "easy"
    human_verified: bool = False


def build(neo, store, n: int = 50, pool: int = 600, seed: int = 20260806) -> tuple[list[Item], dict]:
    """Sinh tối đa `n` item G1. Trả (items, thống kê cổng)."""
    rng = random.Random(seed)
    rows = neo.run(SELECT, pool=pool)
    rng.shuffle(rows)

    items: list[Item] = []
    dem_moi: dict[str, int] = {}
    stat = {"ung_vien": len(rows), "c1_pass": 0, "c1_fail": 0,
            "bo_vi_so_hieu": 0, "bo_vi_trung_vb_moi": 0,
            "bo_vi_bang_chung_yeu": 0, "bo_vi_khong_thay_span": 0}

    for r in rows:
        if len(items) >= n:
            break
        cu_core, moi_core = core_so_hieu(r["cu_so_hieu"]), core_so_hieu(r["moi_so_hieu"])
        if not cu_core or not moi_core:
            stat["bo_vi_so_hieu"] += 1          # số hiệu không parse được -> bỏ, không đoán
            continue
        if dem_moi.get(r["moi_id"], 0) >= MAX_MOI_LAP:
            stat["bo_vi_trung_vb_moi"] += 1     # đa dạng hoá đáp án
            continue

        # Bằng chứng văn bản: điều khoản trong VB MỚI tuyên bố VB CŨ hết hiệu lực.
        span, diem = find_evidence_span(store, r["moi_id"], cu_core)
        if span is None:
            stat["bo_vi_khong_thay_span"] += 1
            continue
        if diem < MIN_DIEM_BANG_CHUNG:
            # Số hiệu có xuất hiện nhưng không ở điều khoản bãi bỏ -> chỉ là dẫn chiếu.
            # Giữ lại sẽ làm context_recall chấm trên chunk không trả lời được câu hỏi.
            stat["bo_vi_bang_chung_yeu"] += 1
            continue

        ok, ly_do = gate_c1(store, span)
        if not ok:
            stat["c1_fail"] += 1                # C1 rớt = lỗi pipeline, phải báo (§2)
            continue
        stat["c1_pass"] += 1

        tpl = TEMPLATES[len(items) % len(TEMPLATES)]
        it = Item(
            id=f"G1-{len(items):04d}",
            user_input=tpl.format(cu=cu_core),
            question_template=tpl,
            reference=moi_core,
            reference_fields={"norm_id": r["moi_id"], "so_hieu": moi_core,
                              "ngay_hieu_luc": str(r["moi_hieu_luc"])},
            gold_node_ids=[f"Norm:{r['moi_id']}", f"Norm:{r['cu_id']}"],
            distractor_ids=[core_so_hieu(x) or x for x in (r["anh_em"] or [])],
            evidence="span",
            evidence_score=diem,
            gold_spans=[span.to_json()],
            reference_contexts=[span.text],
            grader="exact_match+non_llm_context_recall",
        )
        it.gates = {"C1": ly_do, "C2": "n/a_lookup", "C3": "deterministic",
                    "C4": "not_run", "C5": "not_sampled"}
        items.append(it)
        dem_moi[r["moi_id"]] = dem_moi.get(r["moi_id"], 0) + 1

    return items, stat
