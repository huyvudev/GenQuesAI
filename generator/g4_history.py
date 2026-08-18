"""G4′ — lịch sử sửa đổi, dựng trên `Action`/`AFFECTS` (§4.5).

    (vb_sua)<-[:ENACTED_BY]-(act:Action)-[:AFFECTS]->(vb_bi_sua)

Nguồn cũ (`Expression.action_dong`) chỉ 4.195 ca gói trong 104 văn bản. Nguồn này
rộng hơn 19× và trải đều. Đáp án `field[]`, chấm Set-F1 (phạt cả thiếu lẫn thừa).

BA bộ lọc bắt buộc, thứ tự quan trọng (§4.5):
  1. loai IN ['SuaDoi','ThayThe','BaiBo']  -> LOẠI 'CanCu' (căn cứ pháp lý, KHÔNG
     phải sửa đổi; chiếm 59% kho đã duyệt, không loại thì quá nửa đáp án sai)
  2. da_duyet = true
  3. confidence >= 0.85

Độ phân giải là CẤP VĂN BẢN, không phải cấp Điều — `AFFECTS` nối Action → Norm.
"""
from __future__ import annotations

import random
import re
from dataclasses import dataclass, field

from framework import so_hieu as _sh

from .common import chu_de_tu_norm, core_so_hieu, khoa_nhap_nhang
from .gold import find_evidence_span, gate_c1

MIN_SO_VB = 2          # phải bị ≥2 văn bản tác động -> mới là câu hỏi DANH SÁCH

def ung_vien(c, pool: int, min_conf: float) -> list[dict]:
    """Bản duyệt `Corpus` của khối Cypher cũ (A1).

        MATCH (act:Action)-[:AFFECTS]->(vb)  MATCH (act)-[:ENACTED_BY]->(nguon)
        WHERE act.loai IN ['SuaDoi','ThayThe','BaiBo'] AND act.da_duyet = true
          AND act.confidence >= $min_conf AND nguon.norm_id <> vb.norm_id
        WITH vb, collect(DISTINCT {...}) AS ds  WHERE size(ds) >= $min_vb
        ORDER BY size(ds) DESC  LIMIT $pool

    Ba bộ lọc bắt buộc (§4.5) nằm gọn trong `LoaiQuanHe.tac_dong()` + `nguon`:
    loại `CanCu` (59% quan hệ đã duyệt — gộp vào thì quá nửa đáp án sai), `da_duyet`,
    và `confidence >= 0.85`. Chỉ nhánh TRÍCH TỰ ĐỘNG: cạnh REPLACES trực tiếp thuộc
    về G1, tính vào đây là đếm hai lần cùng một sự kiện.

    Thêm khoá phụ khi sắp xếp — `ORDER BY size(ds) DESC` một mình có hàng loạt ca
    bằng điểm, và `LIMIT $pool` cắt vào giữa chúng theo thứ tự Neo4j tuỳ ý.
    """
    from framework.schema import LoaiQuanHe
    from framework.truy_van import nguon_cua
    from framework.schema import NguonQuanHe

    td = LoaiQuanHe.tac_dong()
    theo_dich: dict[str, dict[str, dict]] = {}
    for q in c.quan_he:
        if q.loai not in td or nguon_cua(q) is not NguonQuanHe.TU_DONG:
            continue
        if c.meta.quan_he_tu_dong and q.da_duyet is not True:
            continue
        if q.do_tin is not None and q.do_tin < min_conf:
            continue
        if q.tu_norm_id == q.den_norm_id:
            continue
        vb, ng = c.norms.get(q.den_norm_id), c.norms.get(q.tu_norm_id)
        if not (vb and vb.so_hieu and ng and ng.so_hieu):
            continue
        theo_dich.setdefault(q.den_norm_id, {})[q.tu_norm_id] = {
            "sh": ng.so_hieu, "id": ng.norm_id,
            "loai": q.loai.value, "ngay": q.ngay_hieu_luc}

    ra = [{"vb_id": vid, "vb_sh": c.norms[vid].so_hieu, "vb_td": c.norms[vid].tieu_de,
           "tac_dong": [d[k] for k in sorted(d)]}
          for vid, d in theo_dich.items() if len(d) >= MIN_SO_VB]
    ra.sort(key=lambda r: (-len(r["tac_dong"]), r["vb_id"]))
    return ra[:pool]


TPL_LOOKUP = [
    "{sh} đã bị những văn bản nào sửa đổi, bổ sung hoặc thay thế?",
    "Liệt kê các văn bản đã tác động tới {sh}.",
]
TPL_SITUATION = "Quy định về {chu_de} đã thay đổi qua những văn bản nào?"

# Nhiều bản ghi là CÙNG một văn bản viết khác nhau: '19/2012/TTLT-BTC - BKH&ĐT-BTTTT'
# vs '19/2012/TTLT-BTC-BKHĐT-BTTTT'. Gộp theo 'số/năm' để danh sách đáp án không trùng.
_SO_NAM = re.compile(r"^(\d+[a-zA-Z]?/\d{4})")


def _khoa_gop(sh: str) -> str:
    m = _SO_NAM.match(sh)
    return m.group(1) if m else sh


@dataclass
class Item:
    id: str
    group: str = "G4"
    question_form: str = "lookup"
    persona: str = "can_bo_phap_che"
    user_input: str = ""
    question_template: str = ""
    question_pre_paraphrase: str = ""
    reference: str = ""
    reference_type: str = "field[]"
    reference_fields: dict = field(default_factory=dict)
    gold_spans: list = field(default_factory=list)
    reference_contexts: list = field(default_factory=list)
    gold_node_ids: list = field(default_factory=list)
    distractor_ids: list = field(default_factory=list)
    evidence: str = "graph_only"
    gates: dict = field(default_factory=dict)
    grader: str = "set_f1"
    difficulty: str = "hard"
    human_verified: bool = False


def build(c, store, n: int = 40, pool: int = 1500, min_conf: float = 0.85,
          ty_le_situation: float = 0.5, seed: int = 20260806) -> tuple[list[Item], dict]:
    rng = random.Random(seed)
    rows = ung_vien(c, pool, min_conf)
    rng.shuffle(rows)
    nhap_nhang = khoa_nhap_nhang(c)

    items: list[Item] = []
    stat = {"ung_vien": len(rows), "bo_vi_so_hieu": 0, "bo_vi_gop_con_1": 0,
            "co_bang_chung": 0, "graph_only": 0, "c1_fail": 0, "co_suadoi": 0,
            "bo_vi_khoa_nhap_nhang": 0, "bo_phan_tu_nhap_nhang": 0}

    for r in rows:
        if len(items) >= n:
            break
        vb = core_so_hieu(r["vb_sh"])
        if not vb:
            stat["bo_vi_so_hieu"] += 1
            continue
        # Văn bản ĐƯỢC HỎI mà mơ hồ thì cả câu vô nghĩa — bỏ luôn.
        if _sh.khoa(vb) in nhap_nhang:
            stat["bo_vi_khoa_nhap_nhang"] += 1
            continue

        # Gộp trùng rồi mới kiểm số lượng: 3 biến thể của cùng 1 văn bản không phải
        # câu hỏi danh sách, và nếu giữ thì Set-F1 phạt hệ vì trả lời ĐÚNG một lần.
        gop: dict[str, dict] = {}
        for t in r["tac_dong"]:
            sh = core_so_hieu(t["sh"])
            if not sh or sh == vb:
                continue
            # Đáp án G4′ là DANH SÁCH số hiệu, chấm Set-F1. Một phần tử mơ hồ thì
            # không phán được hệ trả đúng hay sai phần tử đó -> bỏ phần tử, giữ câu.
            # Khác G1 ở chỗ: mất một phần tử vẫn còn câu hỏi, mất văn bản được hỏi thì không.
            if _sh.khoa(sh) in nhap_nhang:
                stat["bo_phan_tu_nhap_nhang"] += 1
                continue
            gop.setdefault(_khoa_gop(sh), {"sh": sh, "id": t["id"], "loai": t["loai"]})
        ds = list(gop.values())
        if len(ds) < MIN_SO_VB:
            stat["bo_vi_gop_con_1"] += 1
            continue
        if any(x["loai"] == "SuaDoi" for x in ds):
            stat["co_suadoi"] += 1

        dap_an = sorted(x["sh"] for x in ds)

        # Bằng chứng: điều khoản trong MỘT văn bản tác động có nhắc số hiệu `vb`.
        span, ev = None, "graph_only"
        for x in ds:
            s, diem = find_evidence_span(store, x["id"], vb)
            if s and diem >= 3:
                ok, ly_do = gate_c1(store, s)
                if ok:
                    span, ev = s, "span"
                    break
                stat["c1_fail"] += 1
        if span is None:
            # Không văn bản tác động nào có điều khoản nhắc tên `vb` -> không trích
            # dẫn được, vi phạm I2. Pool dư (2.741 ứng viên / 40 câu) nên siết luôn
            # thay vì hạ chuẩn thành graph_only.
            stat["graph_only"] += 1
            continue
        stat["co_bang_chung"] += 1

        chu_de = chu_de_tu_norm(r["vb_td"])     # bóc số hiệu khỏi tiêu đề văn bản
        la_sit = (sum(1 for x in items if x.question_form == "situation") < int(n * ty_le_situation)
                  and bool(chu_de))
        if la_sit:
            tpl, cau = TPL_SITUATION, TPL_SITUATION.format(chu_de=chu_de)
            form, persona = "situation", "luat_su"
        else:
            tpl = TPL_LOOKUP[len(items) % len(TPL_LOOKUP)]
            cau, form, persona = tpl.format(sh=vb), "lookup", "can_bo_phap_che"

        it = Item(
            id=f"G4-{len(items):04d}", question_form=form, persona=persona,
            user_input=cau, question_template=tpl, question_pre_paraphrase=cau,
            reference="; ".join(dap_an),
            reference_fields={"van_ban_bi_tac_dong": vb, "danh_sach": dap_an,
                              "so_luong": len(dap_an)},
            gold_spans=[span.to_json()] if span else [],
            reference_contexts=[span.text] if span else [],
            gold_node_ids=[f"Norm:{r['vb_id']}"] + [f"Norm:{x['id']}" for x in ds],
            evidence=ev,
        )
        it.gates = {"C1": "pass" if span else "n/a_khong_co_span",
                    "C2": "chua_paraphrase" if form == "situation" else "n/a_lookup",
                    "C3": "deterministic" if span else "graph_only",
                    "C4": "not_run", "C5": "not_sampled"}
        items.append(it)

    return items, stat
