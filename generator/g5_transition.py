"""G5 — tình huống chuyển tiếp, dựng trên `TransitionRule` (§4.5).

    (n:Norm)-[:HAS_TRANSITION]->(t:TransitionRule)

Trường của rule: `dieu_kien` (điều kiện áp dụng), `van_ban_ap_dung` (áp dụng cái gì),
`nguon_dieu_khoan` (điều khoản gốc), `da_duyet`, `confidence`.

NGƯỠNG RIÊNG: `TransitionRule` chấm trên thang tới **1.0** trong khi `Action` chặn ở
0.9 — hai pipeline trích xuất khác nhau, không dùng chung hằng số (§4.5). Toàn bộ 941
rule đều `da_duyet = true`; lọc `confidence >= 0.9` còn 870.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

from .common import co_so_hieu, core_so_hieu
from .gold import chunk_span, gate_c1

MAX_MOI_NORM = 3

SELECT = """
MATCH (n:Norm)-[:HAS_TRANSITION]->(t:TransitionRule)
WHERE t.da_duyet = true AND t.confidence >= $min_conf
  AND t.dieu_kien IS NOT NULL AND t.van_ban_ap_dung IS NOT NULL
  AND size(t.dieu_kien) >= 25 AND size(t.dieu_kien) <= 260
  AND n.so_hieu IS NOT NULL
OPTIONAL MATCH (n)-[:HAS_PART*]->(d:Component)-[:HAS_VERSION]->(e:Expression)
WHERE d.loai = 'Dieu' AND t.nguon_dieu_khoan CONTAINS ('Điều ' + d.so_thu_tu)
RETURN n.norm_id AS norm_id, n.so_hieu AS so_hieu,
       t.rule_id AS rule_id, t.dieu_kien AS dieu_kien,
       t.van_ban_ap_dung AS ap_dung, t.nguon_dieu_khoan AS nguon,
       t.confidence AS conf, head(collect(e.expr_id)) AS expr_id
ORDER BY t.confidence DESC
LIMIT $pool
"""

TPL_LOOKUP = "Theo {sh}, {dieu_kien} thì xử lý thế nào?"
TPL_SITUATION = "{dieu_kien} thì bây giờ áp dụng theo quy định nào?"


@dataclass
class Item:
    id: str
    group: str = "G5"
    question_form: str = "lookup"
    persona: str = "can_bo_phap_che"
    user_input: str = ""
    question_template: str = ""
    question_pre_paraphrase: str = ""
    reference: str = ""
    reference_type: str = "composed"
    reference_fields: dict = field(default_factory=dict)
    gold_spans: list = field(default_factory=list)
    reference_contexts: list = field(default_factory=list)
    gold_node_ids: list = field(default_factory=list)
    distractor_ids: list = field(default_factory=list)
    evidence: str = "graph_only"
    gates: dict = field(default_factory=dict)
    grader: str = "exact_match+judge"
    difficulty: str = "hard"
    human_verified: bool = False


def build(neo, store, n: int = 30, pool: int = 900, min_conf: float = 0.9,
          ty_le_situation: float = 0.7, seed: int = 20260806) -> tuple[list[Item], dict]:
    rng = random.Random(seed)
    rows = neo.run(SELECT, pool=pool, min_conf=min_conf)
    rng.shuffle(rows)

    items: list[Item] = []
    dem: dict[str, int] = {}
    stat = {"ung_vien": len(rows), "bo_vi_so_hieu": 0, "bo_vi_trung_norm": 0,
            "co_span": 0, "graph_only": 0, "c1_fail": 0, "bo_vi_dieu_kien_lo_sh": 0}

    for r in rows:
        if len(items) >= n:
            break
        sh = core_so_hieu(r["so_hieu"])
        if not sh:
            stat["bo_vi_so_hieu"] += 1
            continue
        if dem.get(r["norm_id"], 0) >= MAX_MOI_NORM:
            stat["bo_vi_trung_norm"] += 1
            continue

        dk = (r["dieu_kien"] or "").strip().rstrip(".")
        ap_dung = (r["ap_dung"] or "").strip().rstrip(".")

        span, ev = None, "graph_only"
        if r["expr_id"]:
            span, _ = chunk_span(store, r["expr_id"], 0)
            if span:
                ok, ly_do = gate_c1(store, span)
                if not ok:
                    stat["c1_fail"] += 1
                    span = None
                else:
                    ev = "span"
        stat["co_span" if ev == "span" else "graph_only"] += 1

        # Dạng `situation` phải KHÔNG nêu số hiệu — điều kiện chuyển tiếp đôi khi tự
        # nó có nhắc văn bản, khi đó chỉ dùng được dạng lookup.
        la_sit = (sum(1 for x in items if x.question_form == "situation") < int(n * ty_le_situation)
                  and not co_so_hieu(dk))
        if not la_sit and co_so_hieu(dk):
            stat["bo_vi_dieu_kien_lo_sh"] += 1
        if la_sit:
            tpl = TPL_SITUATION
            cau = tpl.format(dieu_kien=dk[:1].upper() + dk[1:])
            form, persona = "situation", "chu_ho_kinh_doanh"
        else:
            tpl = TPL_LOOKUP
            cau = tpl.format(sh=sh, dieu_kien=dk[:1].lower() + dk[1:])
            form, persona = "lookup", "luat_su"

        it = Item(
            id=f"G5-{len(items):04d}", question_form=form, persona=persona,
            user_input=cau, question_template=tpl, question_pre_paraphrase=cau,
            reference=f"{ap_dung}. (Theo {r['nguon'] or sh})",
            reference_fields={"so_hieu": sh, "dieu_kien": dk, "ap_dung": ap_dung,
                              "nguon_dieu_khoan": r["nguon"],
                              "confidence": r["conf"]},
            gold_spans=[span.to_json()] if span else [],
            reference_contexts=[span.text] if span else [],
            gold_node_ids=[f"TransitionRule:{r['rule_id']}", f"Norm:{r['norm_id']}"],
            evidence=ev,
        )
        it.gates = {"C1": "pass" if span else "n/a_khong_co_span",
                    "C2": "chua_paraphrase" if form == "situation" else "n/a_lookup",
                    "C3": "deterministic" if span else "graph_only",
                    "C4": "not_run", "C5": "not_sampled"}
        items.append(it)
        dem[r["norm_id"]] = dem.get(r["norm_id"], 0) + 1

    return items, stat
