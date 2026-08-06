"""G2′ — câu hỏi "tại một thời điểm" (§4.4).

Định nghĩa GỐC của G2 ("1 Component có nhiều Expression theo thời gian") có **0 ứng
viên** trong đồ thị thật — xem §10.3b. Nhóm này dựng lại trên khoảng hiệu lực đóng.

Mô hình đã xác minh trên dữ liệu 2026-08-06:
    (moi)-[:REPLACES]->(cu),  Expression của `cu` đóng tại `hieu_luc_den`
    133.151/148.173 (90%) có  cu.Expression.hieu_luc_den == moi.ngay_hieu_luc
10% còn lại đóng sớm/muộn hơn -> mốc chuyển giao không rõ ràng -> LOẠI ở WHERE.

Ba loại mốc hỏi, khoảng hiệu lực là NỬA MỞ `[tu, den)`:

    tu ─────────── giữa ────── den-7 ──┼── den ──────────>
                    │            │     │
              mid_interval  near_boundary│  on_boundary
              đáp án = cu    đáp án = cu │  đáp án = MOI (cu đã hết hiệu lực)

Hai loại đầu bắt lỗi "hệ luôn trả về bản mới nhất bất kể hỏi năm nào".
Loại thứ ba bắt lỗi off-by-one: tại ĐÚNG ngày `den` thì `cu` KHÔNG còn hiệu lực.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import date, timedelta

import re

from .common import co_so_hieu, core_so_hieu
from .gold import chunk_span, find_evidence_span, gate_c1
from .g7_content import LOAI_TRU, tieu_de_hop_le

# Tiêu đề Norm có dạng: "Thông tư số 12/2016/TT-BTTTT Quy định về việc chỉ định ..."
# -> CHỨA SỐ HIỆU, phải bóc trước khi dùng làm chủ đề cho câu `situation`.
_BOC_SH = re.compile(r"^.*?\d+[a-zA-Z]?/\d{4}/[A-ZĐ][A-ZĐ0-9\-]*\s*", re.S)
_BOC_DAU = re.compile(r"^(?:quy định|hướng dẫn|ban hành|sửa đổi[^ ]*|về|việc)\s+",
                      re.IGNORECASE)


def chu_de_tu_norm(tieu_de: str | None) -> str | None:
    """'Thông tư số 12/2016/TT-BTTTT Quy định về việc chỉ định phòng thử nghiệm…'
    -> 'chỉ định phòng thử nghiệm…'. Dùng để phân biệt chủ đề mà KHÔNG lộ số hiệu.

    Trả None nếu bóc xong vẫn còn số hiệu hoặc quá ngắn -> bỏ phần định hướng chủ đề.
    """
    if not tieu_de:
        return None
    s = _BOC_SH.sub("", tieu_de.strip()).strip(' "\'')
    for _ in range(3):
        s2 = _BOC_DAU.sub("", s).strip()
        if s2 == s:
            break
        s = s2
    if len(s) > 90:
        s = s[:90].rsplit(" ", 1)[0]
    # Cắt đuôi từ nối bị hụt sau khi truncate: "…của Chính phủ" -> "…của" đọc rất kỳ.
    s = re.sub(r"\s+(?:của|và|về|cho|trong|theo|tại|đối với|thuộc)$", "", s).strip()
    if len(s) < 12 or co_so_hieu(s):
        return None
    return s[:1].lower() + s[1:]

MAX_MOI_CAP = 2           # tối đa 2 câu / cặp REPLACES
MIN_LEN, MAX_LEN = 250, 2500
MIN_NGAY = 40             # khoảng hiệu lực tối thiểu, đủ tách 3 mốc hỏi

SELECT = """
MATCH (moi:Norm)-[:REPLACES]->(cu:Norm)
WHERE moi.ngay_hieu_luc IS NOT NULL AND cu.ngay_hieu_luc IS NOT NULL
  AND moi.ngay_hieu_luc > cu.ngay_hieu_luc
  AND moi.so_hieu IS NOT NULL AND cu.so_hieu IS NOT NULL
MATCH (cu)-[:HAS_PART*]->(d:Component)-[:HAS_VERSION]->(e:Expression)
WHERE d.loai = 'Dieu'
  AND e.hieu_luc_den IS NOT NULL AND e.hieu_luc_tu IS NOT NULL
  AND e.hieu_luc_den = moi.ngay_hieu_luc          // mốc chuyển giao rõ ràng
  AND e.hieu_luc_den.year <= 2030                 // loại giá trị sentinel năm 3000
  AND duration.inDays(e.hieu_luc_tu, e.hieu_luc_den).days >= $min_ngay
  AND d.tieu_de IS NOT NULL AND size(d.tieu_de) >= 12 AND size(d.tieu_de) <= 80
  AND NONE(k IN $loai_tru WHERE toLower(d.tieu_de) CONTAINS k)
RETURN cu.norm_id AS cu_id, cu.so_hieu AS cu_so_hieu, cu.tieu_de AS cu_tieu_de,
       moi.norm_id AS moi_id, moi.so_hieu AS moi_so_hieu,
       d.so_thu_tu AS stt, d.tieu_de AS dieu_tieu_de, d.duong_dan AS duong_dan,
       e.expr_id AS expr_id, e.hieu_luc_tu AS tu, e.hieu_luc_den AS den
ORDER BY e.hieu_luc_den DESC
LIMIT $pool
"""

# Điều của văn bản MỚI — làm bẫy cho mid/near (đúng chủ đề, SAI thời điểm).
BAY_MOI = """
MATCH (n:Norm {norm_id:$moi_id})-[:HAS_PART*]->(k:Component)-[:HAS_VERSION]->(e:Expression)
WHERE k.loai = 'Dieu' AND e.hieu_luc_den IS NULL
RETURN e.expr_id AS ex LIMIT 2
"""

TPL_LOOKUP = {
    "con_hieu_luc": "Tại thời điểm {as_of}, Điều {stt} của {so_hieu} quy định gì?",
    "het_hieu_luc": "Ngày {as_of}, Điều {stt} của {so_hieu} còn hiệu lực không?",
}
# Có `chu_de` (bóc từ tiêu đề văn bản) thì thêm vào để phân biệt: chủ đề Điều kiểu
# "các hành vi bị nghiêm cấm" một mình thì trùng hàng chục văn bản, hỏi kèm ngày vẫn
# không ra đáp án duy nhất -> context_recall chấm vào đâu cũng sai.
TPL_SITUATION = {
    "con_hieu_luc": "Ngày {as_of}, {tieu_de} được quy định như thế nào?",
    "het_hieu_luc": "Ngày {as_of}, {tieu_de} áp dụng theo văn bản nào?",
}
TPL_SITUATION_CD = {
    "con_hieu_luc": "Ngày {as_of}, {tieu_de} theo quy định về {chu_de} là gì?",
    "het_hieu_luc": "Ngày {as_of}, {tieu_de} về {chu_de} áp dụng theo văn bản nào?",
}


def _ngay(v) -> date:
    return v.to_native() if hasattr(v, "to_native") else v


def _dd(d: date) -> str:
    return d.strftime("%d/%m/%Y")


@dataclass
class Item:
    id: str
    group: str = "G2"                 # mã máy giữ ASCII, dấu ′ chỉ dùng trong tài liệu
    question_form: str = "lookup"
    persona: str = "can_bo_phap_che"
    user_input: str = ""
    question_template: str = ""
    question_pre_paraphrase: str = ""
    as_of_date: str = ""
    as_of_kind: str = ""
    reference: str = ""
    reference_type: str = "span"
    reference_fields: dict = field(default_factory=dict)
    gold_spans: list = field(default_factory=list)
    reference_contexts: list = field(default_factory=list)
    gold_node_ids: list = field(default_factory=list)
    distractor_ids: list = field(default_factory=list)
    evidence: str = "span"
    gates: dict = field(default_factory=dict)
    grader: str = "faithfulness+non_llm_context_recall"
    difficulty: str = "hard"
    human_verified: bool = False


PERSONA_SIT = ["chu_ho_kinh_doanh", "nguoi_dan", "luat_su"]
KINDS = ["mid_interval", "near_boundary", "on_boundary"]


def build(neo, store, n: int = 80, pool: int = 6000, ty_le_situation: float = 0.6,
          seed: int = 20260806) -> tuple[list[Item], dict]:
    rng = random.Random(seed)
    rows = neo.run(SELECT, pool=pool, min_ngay=MIN_NGAY, loai_tru=LOAI_TRU)
    rng.shuffle(rows)

    items: list[Item] = []
    dem_cap: dict[tuple, int] = {}
    stat = {"ung_vien": len(rows), "c1_pass": 0, "c1_fail": 0,
            "bo_vi_so_hieu": 0, "bo_vi_trung_cap": 0, "bo_vi_khong_co_chunk": 0,
            "bo_vi_nhieu_part": 0, "bo_vi_do_dai": 0, "bo_vi_khong_co_bang_chung": 0}
    can_sit = int(round(n * ty_le_situation))
    quota_kind = {k: 0 for k in KINDS}

    for r in rows:
        if len(items) >= n:
            break
        cu_sh, moi_sh = core_so_hieu(r["cu_so_hieu"]), core_so_hieu(r["moi_so_hieu"])
        if not cu_sh or not moi_sh or not r["stt"]:
            stat["bo_vi_so_hieu"] += 1
            continue
        cap = (r["cu_id"], r["moi_id"])
        if dem_cap.get(cap, 0) >= MAX_MOI_CAP:
            stat["bo_vi_trung_cap"] += 1
            continue
        tieu_de = (r["dieu_tieu_de"] or "").strip().rstrip(".")
        if not tieu_de_hop_le(tieu_de):
            continue

        tu, den = _ngay(r["tu"]), _ngay(r["den"])
        # Cân đều ba loại mốc — mỗi loại ≥25% theo tiêu chí nghiệm thu (Mục 9).
        kind = min(KINDS, key=lambda k: quota_kind[k])
        if kind == "mid_interval":
            as_of = tu + (den - tu) / 2
        elif kind == "near_boundary":
            as_of = den - timedelta(days=7)
        else:
            as_of = den
        con_hieu_luc = kind != "on_boundary"      # [tu, den): tại đúng den là HẾT

        span_cu, pl = chunk_span(store, r["expr_id"], 0)
        if span_cu is None:
            stat["bo_vi_khong_co_chunk"] += 1
            continue
        if int(pl.get("n_parts", 1)) != 1:
            stat["bo_vi_nhieu_part"] += 1
            continue
        if not (MIN_LEN <= len(span_cu.text) <= MAX_LEN):
            stat["bo_vi_do_dai"] += 1
            continue

        if con_hieu_luc:
            # Đáp án = nội dung ĐANG hiệu lực tại as_of, tức chính Điều của `cu`.
            span, ref, ref_type = span_cu, span_cu.text, "span"
            dap_an_norm = cu_sh
        else:
            # Tại đúng mốc đóng: `cu` hết hiệu lực. Bằng chứng nằm ở điều khoản bãi bỏ
            # trong văn bản MỚI — dùng lại đúng bộ tìm bằng chứng của G1.
            span, diem = find_evidence_span(store, r["moi_id"], cu_sh)
            if span is None or diem < 3:
                stat["bo_vi_khong_co_bang_chung"] += 1
                continue
            ref = f"{moi_sh} — {cu_sh} hết hiệu lực từ {_dd(den)}."
            ref_type, dap_an_norm = "composed", moi_sh

        ok, ly_do = gate_c1(store, span)
        if not ok:
            stat["c1_fail"] += 1
            continue
        stat["c1_pass"] += 1

        so_sit = sum(1 for x in items if x.question_form == "situation")
        la_sit = so_sit < can_sit
        khoa = "con_hieu_luc" if con_hieu_luc else "het_hieu_luc"
        if la_sit:
            chu_de = chu_de_tu_norm(r["cu_tieu_de"])
            tpl = (TPL_SITUATION_CD if chu_de else TPL_SITUATION)[khoa]
            cau = tpl.format(as_of=_dd(as_of), chu_de=chu_de,
                             tieu_de=tieu_de[:1].lower() + tieu_de[1:])
            persona = PERSONA_SIT[len(items) % len(PERSONA_SIT)]
        else:
            tpl = TPL_LOOKUP[khoa]
            cau = tpl.format(as_of=_dd(as_of), stt=r["stt"], so_hieu=cu_sh)
            persona = "can_bo_phap_che"

        # Bẫy = phía SAI thời điểm của cùng mốc chuyển giao.
        bay = []
        try:
            nguon = ([x["ex"] for x in neo.run(BAY_MOI, moi_id=r["moi_id"])]
                     if con_hieu_luc else [r["expr_id"]])
            for ex in nguon:
                s2, _ = chunk_span(store, ex, 0)
                if s2 and s2.chunk_id != span.chunk_id:
                    bay.append(s2.chunk_id)
        except Exception:
            pass

        it = Item(
            id=f"G2-{len(items):04d}",
            question_form="situation" if la_sit else "lookup",
            persona=persona,
            user_input=cau, question_template=tpl, question_pre_paraphrase=cau,
            as_of_date=as_of.isoformat(), as_of_kind=kind,
            reference=ref, reference_type=ref_type,
            reference_fields={"norm_id_hieu_luc": dap_an_norm, "cu": cu_sh,
                              "moi": moi_sh, "moc_dong": den.isoformat()},
            gold_spans=[span.to_json()], reference_contexts=[span.text],
            gold_node_ids=[f"Expression:{r['expr_id']}"],
            distractor_ids=bay,
            grader=("faithfulness+non_llm_context_recall" if con_hieu_luc
                    else "exact_match+non_llm_context_recall"),
        )
        it.gates = {"C1": ly_do,
                    "C2": "chua_paraphrase" if la_sit else "n/a_lookup",
                    "C3": "deterministic", "C4": "not_run", "C5": "not_sampled"}
        items.append(it)
        dem_cap[cap] = dem_cap.get(cap, 0) + 1
        quota_kind[kind] += 1

    stat.update({f"kind_{k}": v for k, v in quota_kind.items()})
    return items, stat
