"""G3 — hiệu lực dây chuyền: văn bản hướng dẫn còn dùng được khi văn bản mẹ bị thay?

    (con)-[:GUIDED_BY]->(me)<-[:REPLACES]-(moi)

Đo khả năng suy luận NHIỀU BƯỚC trên đồ thị. Đáp án `composed`.

Đáp án đúng lấy từ TRẠNG THÁI THẬT của `con` trong đồ thị, KHÔNG suy luận pháp lý:
văn bản hướng dẫn không đương nhiên hết hiệu lực khi văn bản mẹ bị thay, nên tự suy
sẽ sai. Đo trên 3.000 ca: 2.038 con còn hiệu lực / 938 hết / 24 một phần.
Ca "một phần" bị loại — không phát biểu được một đáp án đơn trị.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

from .common import chu_de_tu_norm, core_so_hieu
from .gold import chunk_span, find_evidence_span, gate_c1

MAX_MOI_ME = 2

SELECT = """
MATCH (con:Norm)-[:GUIDED_BY]->(me:Norm)<-[:REPLACES]-(moi:Norm)
WHERE con.so_hieu IS NOT NULL AND me.so_hieu IS NOT NULL AND moi.so_hieu IS NOT NULL
  AND moi.ngay_hieu_luc IS NOT NULL AND me.ngay_hieu_luc IS NOT NULL
  AND moi.ngay_hieu_luc > me.ngay_hieu_luc
  AND con.norm_id <> me.norm_id AND con.norm_id <> moi.norm_id
WITH con, me, moi LIMIT $pool
MATCH (con)-[:HAS_PART*]->(c:Component)-[:HAS_VERSION]->(e:Expression)
WITH con, me, moi,
     count(e) AS tong,
     count(CASE WHEN e.hieu_luc_den IS NULL THEN 1 END) AS mo,
     // Chỉ lấy expr của ĐIỀU: point trong Qdrant nằm ở mức Điều, lấy expr của
     // Khoản/Điểm thì chunk_span() không tìm ra point -> item mất gold_spans.
     head(collect(CASE WHEN c.loai = 'Dieu' AND e.hieu_luc_den IS NULL
                       THEN e.expr_id END)) AS ex_mo,
     head(collect(CASE WHEN c.loai = 'Dieu' THEN e.expr_id END)) AS ex_bat_ky
WHERE tong > 0 AND (mo = tong OR mo = 0)          // loại ca 'một phần'
RETURN con.norm_id AS con_id, con.so_hieu AS con_sh, con.tieu_de AS con_td,
       me.so_hieu AS me_sh, me.norm_id AS me_id,
       moi.so_hieu AS moi_sh, moi.norm_id AS moi_id,
       moi.ngay_hieu_luc AS moi_hl,
       (mo = tong) AS con_hieu_luc,
       coalesce(ex_mo, ex_bat_ky) AS expr_id
"""

TPL_LOOKUP = ("{con} hướng dẫn {me}. {me} đã bị {moi} thay thế. "
              "{con} còn hiệu lực không?")
TPL_SITUATION = ("Văn bản hướng dẫn tôi đang áp dụng về {chu_de} có văn bản mẹ đã bị "
                 "thay thế. Hướng dẫn đó còn dùng được không?")


@dataclass
class Item:
    id: str
    group: str = "G3"
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
    grader: str = "exact_match_nhan+judge_ly_do"
    difficulty: str = "hard"
    human_verified: bool = False


def build(neo, store, n: int = 60, pool: int = 4000, ty_le_situation: float = 0.6,
          seed: int = 20260806) -> tuple[list[Item], dict]:
    rng = random.Random(seed)
    rows = neo.run(SELECT, pool=pool)
    rng.shuffle(rows)

    items: list[Item] = []
    dem_me: dict[str, int] = {}
    stat = {"ung_vien": len(rows), "bo_vi_so_hieu": 0, "bo_vi_trung_me": 0,
            "bo_vi_khong_co_span": 0, "co_bang_chung": 0, "graph_only": 0,
            "c1_fail": 0, "nhan_con": 0, "nhan_het": 0}

    for r in rows:
        if len(items) >= n:
            break
        con, me, moi = (core_so_hieu(r["con_sh"]), core_so_hieu(r["me_sh"]),
                        core_so_hieu(r["moi_sh"]))
        if not (con and me and moi):
            stat["bo_vi_so_hieu"] += 1
            continue
        if dem_me.get(r["me_id"], 0) >= MAX_MOI_ME:
            stat["bo_vi_trung_me"] += 1
            continue

        con_hl = bool(r["con_hieu_luc"])
        nhan = "Có" if con_hl else "Không"
        if con_hl:
            ref = (f"Có — {con} vẫn còn hiệu lực. Việc {me} bị {moi} thay thế không "
                   f"đương nhiên làm {con} hết hiệu lực.")
        else:
            ref = f"Không — {con} đã hết hiệu lực."

        # Bằng chứng: với ca ĐÃ HẾT, tìm điều khoản bãi bỏ nhắc tên `con`.
        # Với ca CÒN hiệu lực không có câu nào tuyên bố điều đó -> dùng chính nội dung
        # `con` làm ngữ cảnh và đánh dấu evidence=graph_only cho trung thực.
        span, ev = None, "graph_only"
        if not con_hl:
            span, diem = find_evidence_span(store, r["moi_id"], con)
            if span and diem >= 3:
                ev = "span"
        if span is None and r["expr_id"]:
            span, _ = chunk_span(store, r["expr_id"], 0)

        if span is None:
            # Không có ngữ cảnh nào để trích dẫn -> vi phạm I2, bỏ item.
            stat["bo_vi_khong_co_span"] += 1
            continue
        ok, gates_c1 = gate_c1(store, span)
        if not ok:
            stat["c1_fail"] += 1
            continue
        stat["co_bang_chung" if ev == "span" else "graph_only"] += 1

        la_sit = sum(1 for x in items if x.question_form == "situation") < int(n * ty_le_situation)
        # Tiêu đề Norm CHỨA số hiệu -> phải bóc, không thì câu `situation` lộ đúng
        # thứ nó cần giấu và nhóm này gần như không sinh được câu situation nào.
        chu_de = chu_de_tu_norm(r["con_td"])
        if la_sit and chu_de:
            tpl, cau = TPL_SITUATION, TPL_SITUATION.format(chu_de=chu_de)
            persona, form = "chu_ho_kinh_doanh", "situation"
        else:
            tpl = TPL_LOOKUP
            cau = tpl.format(con=con, me=me, moi=moi)
            persona, form = "can_bo_phap_che", "lookup"

        it = Item(
            id=f"G3-{len(items):04d}", question_form=form, persona=persona,
            user_input=cau, question_template=tpl, question_pre_paraphrase=cau,
            reference=ref,
            reference_fields={"nhan": nhan, "con": con, "me": me, "moi": moi},
            gold_spans=[span.to_json()] if span else [],
            reference_contexts=[span.text] if span else [],
            gold_node_ids=[f"Norm:{r['con_id']}", f"Norm:{r['me_id']}",
                           f"Norm:{r['moi_id']}"],
            distractor_ids=[], evidence=ev,
        )
        it.gates = {"C1": gates_c1,
                    "C2": "chua_paraphrase" if form == "situation" else "n/a_lookup",
                    "C3": "deterministic" if ev == "span" else "graph_only",
                    "C4": "not_run", "C5": "not_sampled"}
        items.append(it)
        dem_me[r["me_id"]] = dem_me.get(r["me_id"], 0) + 1
        stat["nhan_con" if con_hl else "nhan_het"] += 1

    return items, stat
