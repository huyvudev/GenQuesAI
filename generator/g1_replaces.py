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

from framework import so_hieu as _sh

from .common import core_so_hieu, khoa_nhap_nhang
from .gold import GoldSpan, find_evidence_span, gate_c1

# Tối đa bao nhiêu câu dùng chung một văn bản thay thế. Một văn bản mới có thể bãi bỏ
# hàng chục văn bản cũ -> không chặn thì nhiều câu chung một đáp án, bộ đề mất đa dạng.
MAX_MOI_LAP = 2
# Điểm bằng chứng tối thiểu (gold.py). >=3 nghĩa là có từ khoá bãi bỏ đứng trước số
# hiệu, tức span thật sự là điều khoản bãi bỏ chứ không phải chỗ dẫn chiếu tình cờ.
MIN_DIEM_BANG_CHUNG = 3

def ung_vien(c, pool: int) -> list[dict]:
    """Bản duyệt `Corpus` của khối Cypher cũ (A1). Trả cùng khuôn dict như `neo.run`.

    Cypher gốc, giữ lại để đối chiếu khi đọc:

        MATCH (moi:Norm)-[:REPLACES]->(cu:Norm)
        WHERE moi.ngay_hieu_luc > cu.ngay_hieu_luc AND cả hai có so_hieu
        WITH cu, collect(DISTINCT moi) AS ds  WHERE size(ds) = 1
        CALL { anh em: văn bản khác cũng bị `moi` thay thế, lấy 3 }
        ORDER BY size(anh_em) DESC, moi.ngay_hieu_luc DESC  LIMIT $pool

    Bốn chỗ phải giữ nguyên ngữ nghĩa, mỗi chỗ một lý do:

    · **chỉ cạnh trực tiếp** (`nguon="canh"`). `Corpus` gộp cạnh REPLACES với
      `Action{loai:'ThayThe'}` thành cùng một enum; lấy cả hai thì G1 nuốt tập ứng
      viên của G4′. Xem `NguonQuanHe`.
    · **lọc `moi` mới hơn `cu` TRƯỚC khi đòi duy nhất.** Đảo thứ tự thì 24 cạnh ngược
      chiều + 46 cạnh cùng ngày (đã đo) làm hỏng điều kiện `size(ds) = 1`.
    · **`size(ds) = 1`** — đáp án phải đơn trị mới chấm exact-match được. Ca bị nhiều
      văn bản cùng thay là câu hỏi danh sách, thuộc về G4′.
    · **sắp xếp xác định.** Cypher `ORDER BY ... DESC` có hàng loạt ca bằng điểm và
      Neo4j không hứa thứ tự trong nhóm bằng điểm; ở đây thêm khoá phụ `cu_id` để
      `LIMIT pool` cắt vào cùng một chỗ mọi lần chạy.
    """
    from framework import truy_van as tv

    theo_cu: list[dict] = []
    for cu in c.norms.values():
        if not (cu.so_hieu and cu.ngay_hieu_luc):
            continue
        ds = [x for x in tv.thay_the_boi(c, cu.norm_id, nguon="canh")
              if (m := c.norms.get(x)) and m.so_hieu and m.ngay_hieu_luc
              and m.ngay_hieu_luc > cu.ngay_hieu_luc]
        if len(ds) != 1:
            continue
        moi = c.norms[ds[0]]
        anh_em = sorted(
            c.norms[x].so_hieu
            for x in tv.da_thay_the(c, moi.norm_id, nguon="canh")
            if x != cu.norm_id and (a := c.norms.get(x)) and a.so_hieu)[:3]
        theo_cu.append({
            "cu_id": cu.norm_id, "cu_so_hieu": cu.so_hieu, "cu_tieu_de": cu.tieu_de,
            "cu_loai": cu.loai_vb, "cu_hieu_luc": cu.ngay_hieu_luc,
            "moi_id": moi.norm_id, "moi_so_hieu": moi.so_hieu,
            "moi_tieu_de": moi.tieu_de, "moi_hieu_luc": moi.ngay_hieu_luc,
            "anh_em": anh_em,
        })
    theo_cu.sort(key=lambda r: (-len(r["anh_em"]),
                                -r["moi_hieu_luc"].toordinal(), r["cu_id"]))
    return theo_cu[:pool]

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


def build(c, store, n: int = 50, pool: int = 600, seed: int = 20260806) -> tuple[list[Item], dict]:
    """Sinh tối đa `n` item G1 từ `Corpus`. Trả (items, thống kê cổng).

    A1: tham số đầu là `framework.schema.Corpus`, không còn là client Neo4j. `store`
    (Qdrant) vẫn cần cho gold span — đó là việc của A2, không phải A1.
    """
    rng = random.Random(seed)
    rows = ung_vien(c, pool)
    rng.shuffle(rows)
    nhap_nhang = khoa_nhap_nhang(c)

    items: list[Item] = []
    dem_moi: dict[str, int] = {}
    stat = {"ung_vien": len(rows), "c1_pass": 0, "c1_fail": 0,
            "bo_vi_so_hieu": 0, "bo_vi_trung_vb_moi": 0,
            "bo_vi_bang_chung_yeu": 0, "bo_vi_khong_thay_span": 0,
            "bo_vi_khoa_nhap_nhang": 0}

    for r in rows:
        if len(items) >= n:
            break
        cu_core, moi_core = core_so_hieu(r["cu_so_hieu"]), core_so_hieu(r["moi_so_hieu"])
        if not cu_core or not moi_core:
            stat["bo_vi_so_hieu"] += 1          # số hiệu không parse được -> bỏ, không đoán
            continue
        # Đáp án G1 LÀ một số hiệu, chấm exact-match. Số hiệu ứng với nhiều văn bản thì
        # câu hỏi không đơn trị: hệ trả "90/CP" đúng hay sai còn tuỳ nó hiểu bản nào.
        # Hỏi ở đầu `cu` cũng vậy — đề bài mơ hồ thì đáp án không cứu được.
        if {_sh.khoa(cu_core), _sh.khoa(moi_core)} & nhap_nhang:
            stat["bo_vi_khoa_nhap_nhang"] += 1
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
