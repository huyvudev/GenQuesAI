"""G6 — ca xung đột cố ý. **SINH ỨNG VIÊN, KHÔNG SINH ĐỀ HOÀN CHỈNH.**

§4.2: một ca chỉ vào G6 khi thoả CẢ BA
  (1) hai norm cùng còn hiệu lực tại thời điểm hỏi
  (2) cùng điều chỉnh một hành vi/đối tượng cụ thể
  (3) đưa ra HỆ QUẢ PHÁP LÝ KHÁC NHAU (mức, thời hạn, điều kiện)

(1) và (2) tự động hoá được. **(3) thì không** — và định nghĩa lỏng "hai Norm khác cấp
cùng điều chỉnh một vấn đề" sẽ gắn nhãn xung đột cho quan hệ hướng dẫn bình thường,
tức PHẠT hệ thống vì nó trả lời đúng.

Nên mọi item nhóm này ra lò với `status = "cho_review"` và `human_verified = false`.
**Chưa review thì KHÔNG được tính vào bộ đề.** 25 câu sạch hơn 200 câu nhiễu.

Proxy cho (2): hai văn bản khác cấp bậc, liên hệ GUIDED_BY, và có Điều TRÙNG TIÊU ĐỀ
— dấu hiệu mạnh cho việc cùng điều chỉnh một nội dung cụ thể.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

from .common import core_so_hieu
from .gold import chunk_span, gate_c1

SELECT = """
MATCH (con:Norm)-[:GUIDED_BY]->(me:Norm)
WHERE con.cap_bac IS NOT NULL AND me.cap_bac IS NOT NULL
  AND con.cap_bac <> me.cap_bac
  AND con.so_hieu IS NOT NULL AND me.so_hieu IS NOT NULL
WITH con, me LIMIT $pool
MATCH (con)-[:HAS_PART*]->(dc:Component)-[:HAS_VERSION]->(ec:Expression)
MATCH (me)-[:HAS_PART*]->(dm:Component)-[:HAS_VERSION]->(em:Expression)
WHERE dc.loai = 'Dieu' AND dm.loai = 'Dieu'
  AND ec.hieu_luc_den IS NULL AND em.hieu_luc_den IS NULL   // (1) cùng còn hiệu lực
  AND dc.tieu_de IS NOT NULL AND dm.tieu_de IS NOT NULL
  AND toLower(dc.tieu_de) = toLower(dm.tieu_de)             // (2) cùng chủ đề cụ thể
  AND size(dc.tieu_de) >= 15
RETURN con.so_hieu AS con_sh, con.cap_bac AS con_cap, con.norm_id AS con_id,
       me.so_hieu AS me_sh, me.cap_bac AS me_cap, me.norm_id AS me_id,
       dc.tieu_de AS chu_de, ec.expr_id AS ex_con, em.expr_id AS ex_me
LIMIT $cap
"""

TPL = ("Về {chu_de}: {a} và {b} cùng có quy định. "
       "Trường hợp hai bên quy định khác nhau thì áp dụng theo văn bản nào?")


@dataclass
class Item:
    id: str
    group: str = "G6"
    status: str = "cho_review"            # CHƯA dùng được cho tới khi có người duyệt
    question_form: str = "lookup"
    persona: str = "luat_su"
    user_input: str = ""
    question_template: str = ""
    question_pre_paraphrase: str = ""
    reference: str = ""
    reference_type: str = "nhan"
    reference_fields: dict = field(default_factory=dict)
    gold_spans: list = field(default_factory=list)
    reference_contexts: list = field(default_factory=list)
    gold_node_ids: list = field(default_factory=list)
    distractor_ids: list = field(default_factory=list)
    evidence: str = "span"
    gates: dict = field(default_factory=dict)
    grader: str = "ty_le_nhan_dien_dung"
    difficulty: str = "hard"
    human_verified: bool = False
    review_can_kiem: str = ("Điều kiện (3) §4.2: hai quy định có HỆ QUẢ PHÁP LÝ khác "
                            "nhau (mức/thời hạn/điều kiện) hay chỉ khác mức độ chi "
                            "tiết? Chỉ khác chi tiết -> LOẠI, không phải xung đột.")


def build(neo, store, n: int = 25, pool: int = 4000,
          seed: int = 20260806) -> tuple[list[Item], dict]:
    rng = random.Random(seed)
    rows = neo.run(SELECT, pool=pool, cap=n * 8)
    rng.shuffle(rows)

    items: list[Item] = []
    da_dung: set[tuple] = set()
    stat = {"ung_vien": len(rows), "bo_vi_so_hieu": 0, "bo_vi_trung_cap": 0,
            "bo_vi_khong_co_chunk": 0, "c1_fail": 0}

    for r in rows:
        if len(items) >= n:
            break
        a, b = core_so_hieu(r["con_sh"]), core_so_hieu(r["me_sh"])
        if not a or not b:
            stat["bo_vi_so_hieu"] += 1
            continue
        khoa = (r["con_id"], r["me_id"])
        if khoa in da_dung:
            stat["bo_vi_trung_cap"] += 1
            continue

        s_con, _ = chunk_span(store, r["ex_con"], 0)
        s_me, _ = chunk_span(store, r["ex_me"], 0)
        if not s_con or not s_me:
            stat["bo_vi_khong_co_chunk"] += 1
            continue
        ok1, _ = gate_c1(store, s_con)
        ok2, _ = gate_c1(store, s_me)
        if not (ok1 and ok2):
            stat["c1_fail"] += 1
            continue

        chu_de = (r["chu_de"] or "").strip().rstrip(".")
        it = Item(
            id=f"G6-{len(items):04d}",
            user_input=TPL.format(chu_de=chu_de[:1].lower() + chu_de[1:], a=a, b=b),
            question_template=TPL,
            question_pre_paraphrase=TPL,
            # Đáp án ĐÚNG không phải một mức cụ thể mà là hành vi: nêu cả hai +
            # dẫn nguyên tắc áp dụng, hoặc từ chối khẳng định một đáp án duy nhất.
            reference="neu_ca_hai_hoac_tu_choi",
            reference_fields={"a": a, "cap_a": r["con_cap"],
                              "b": b, "cap_b": r["me_cap"], "chu_de": chu_de},
            gold_spans=[s_con.to_json(), s_me.to_json()],
            reference_contexts=[s_con.text, s_me.text],
            gold_node_ids=[f"Norm:{r['con_id']}", f"Norm:{r['me_id']}"],
        )
        it.gates = {"C1": "pass", "C2": "n/a_lookup",
                    "C3": "deterministic", "C4": "not_run",
                    "C5": "BAT_BUOC_chua_lam"}
        items.append(it)
        da_dung.add(khoa)

    return items, stat
