"""G3 — hiệu lực dây chuyền: văn bản hướng dẫn còn dùng được khi văn bản mẹ bị thay?

    (con)-[:GUIDED_BY]->(me)<-[:REPLACES]-(moi)

Đo khả năng suy luận NHIỀU BƯỚC trên đồ thị. Đáp án `composed`.

Đáp án đúng lấy từ TRẠNG THÁI THẬT của `con` trong đồ thị, KHÔNG suy luận pháp lý:
văn bản hướng dẫn không đương nhiên hết hiệu lực khi văn bản mẹ bị thay, nên tự suy
sẽ sai. Đo trên 3.000 ca: 2.038 con còn hiệu lực / 938 hết / 24 một phần.
Ca "một phần" bị loại — không phát biểu được một đáp án đơn trị.

C5 lượt 2 (2026-08-19, 10 ca mẫu): 7/10 ca nhãn "còn hiệu lực toàn bộ" (mo==tong) thực ra
đã "hết hiệu lực MỘT PHẦN" theo vbpl.vn — bộ lọc trên KHÔNG bắt được vì dựa hoàn toàn vào
`Expression.hieu_luc_den` của corpus, và trường đó không cập nhật kịp các đợt bãi bỏ sau
này (khoảng trống dữ liệu, không phải lỗi lọc). Đối chiếu 8 ca sai: 4/8 CÓ dấu vết trong
đồ thị (một văn bản khác có quan hệ SUA_DOI/THAY_THE/BAI_BO trỏ tới `con`, dù
`hieu_luc_den` không phản ánh) — 4/8 còn lại (kể cả ca mâu thuẫn nặng nhất) không có tín
hiệu gì trong corpus, không cách nào bắt được từ trong này. Vá phần bắt được được: nhãn
"còn hiệu lực toàn bộ" giờ đòi thêm điều kiện KHÔNG văn bản nào từng tác động tới `con`
— rẻ, và loại được khoảng nửa số ca sai đã đo. Nửa còn lại vẫn là giới hạn dữ liệu.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

from .common import chu_de_tu_norm, core_so_hieu
from .gold import chunk_span, find_evidence_span, gate_c1

MAX_MOI_ME = 2

def ung_vien(c, pool: int) -> list[dict]:
    """Bản duyệt `Corpus` của khối Cypher cũ (A1).

        MATCH (con)-[:GUIDED_BY]->(me)<-[:REPLACES]-(moi)
        WHERE moi.ngay_hieu_luc > me.ngay_hieu_luc, con khác cả me lẫn moi
        WITH con, me, moi LIMIT $pool
        MATCH (con)-[:HAS_PART*]->(c)-[:HAS_VERSION]->(e)
        WHERE tong > 0 AND (mo = tong OR mo = 0)      // loại ca 'một phần'

    Ba chỗ giữ nguyên ngữ nghĩa:

    · **`mo = tong OR mo = 0`** — văn bản con phải hoặc còn hiệu lực TOÀN BỘ, hoặc
      hết TOÀN BỘ. Ca 'một phần' không có nhãn Có/Không đơn trị nên không hỏi được.
    · **chỉ lấy expr của ĐIỀU.** Point trong Qdrant nằm ở mức Điều; lấy expr của
      Khoản/Điểm thì `chunk_span()` không tìm ra point và item mất gold_spans.
    · **ưu tiên expr còn mở**, lùi về expr bất kỳ — `coalesce(ex_mo, ex_bat_ky)`.

    Khác Cypher cũ đúng một chỗ, và là chỗ SỬA: `head(collect(...))` chọn expr bất
    kỳ trong nhóm; ở đây `min(...)` cho xác định. Cùng lỗi với `BAY_KHAC_VB` của G7.
    """
    from framework import truy_van as tv

    ra: list[dict] = []
    for con in c.norms.values():
        if not con.so_hieu:
            continue
        for me_id in sorted(tv.huong_dan_cho(c, con.norm_id)):
            me = c.norms.get(me_id)
            if not (me and me.so_hieu and me.ngay_hieu_luc and me_id != con.norm_id):
                continue
            for moi_id in sorted(tv.thay_the_boi(c, me_id, nguon="canh")):
                moi = c.norms.get(moi_id)
                if not (moi and moi.so_hieu and moi.ngay_hieu_luc):
                    continue
                if moi.ngay_hieu_luc <= me.ngay_hieu_luc or moi_id == con.norm_id:
                    continue
                ra.append({"con": con, "me": me, "moi": moi})
    ra.sort(key=lambda r: (r["con"].norm_id, r["me"].norm_id, r["moi"].norm_id))
    ra = ra[:pool]

    kq: list[dict] = []
    for r in ra:
        con = r["con"]
        tong = mo = 0
        ex_mo: list[str] = []
        ex_bat_ky: list[str] = []
        for comp in tv.moi_thanh_phan(c, con.norm_id):
            for e in tv.cac_ban(c, comp.component_id):
                tong += 1
                con_mo = e.hieu_luc_den is None
                mo += 1 if con_mo else 0
                if comp.loai == "Dieu":
                    (ex_mo if con_mo else ex_bat_ky).append(e.expression_id)
        if tong == 0 or not (mo == tong or mo == 0):
            continue
        # Nhãn "còn hiệu lực toàn bộ" (mo==tong) dựa trên hieu_luc_den có thể sai khi
        # dữ liệu chưa cập nhật đợt bãi bỏ MỘT PHẦN sau này (C5 lượt 2). Có văn bản
        # khác tác động (SUA_DOI/THAY_THE/BAI_BO), bất kể nguồn nào (§9), là dấu hiệu
        # KHÔNG nên tin nhãn "toàn bộ". Không kiểm nhánh mo==0 ("đã hết") — dấu vết tác
        # động ở đó chỉ CỦNG CỐ nhãn, không mâu thuẫn.
        if mo == tong and tv.tac_dong_toi(c, con.norm_id, nguon="ca_hai"):
            continue
        expr = min(ex_mo) if ex_mo else (min(ex_bat_ky) if ex_bat_ky else None)
        kq.append({
            "con_id": con.norm_id, "con_sh": con.so_hieu, "con_td": con.tieu_de,
            "me_sh": r["me"].so_hieu, "me_id": r["me"].norm_id,
            "moi_sh": r["moi"].so_hieu, "moi_id": r["moi"].norm_id,
            "moi_hl": r["moi"].ngay_hieu_luc,
            "con_hieu_luc": mo == tong, "expr_id": expr,
        })
    return kq


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


def build(c, store, n: int = 60, pool: int = 4000, ty_le_situation: float = 0.6,
          seed: int = 20260806) -> tuple[list[Item], dict]:
    rng = random.Random(seed)
    rows = ung_vien(c, pool)
    rng.shuffle(rows)

    items: list[Item] = []
    dem_me: dict[str, int] = {}
    da_hoi: set[str] = set()
    stat = {"ung_vien": len(rows), "bo_vi_so_hieu": 0, "bo_vi_trung_me": 0,
            "bo_vi_khong_co_span": 0, "co_bang_chung": 0, "graph_only": 0,
            "c1_fail": 0, "nhan_con": 0, "nhan_het": 0, "bo_vi_trung_cau": 0}

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

        # Câu `situation` chỉ dựng từ CHỦ ĐỀ của văn bản con, cố ý giấu mọi định danh.
        # Nên hai chuỗi hiệu lực khác nhau đi qua CÙNG một văn bản con sẽ ra câu hỏi
        # y hệt — mà `reference` lại khác nhau (khác văn bản mẹ). Hai câu giống hệt
        # với hai đáp án khác nhau thì hệ trả lời kiểu gì cũng trượt một câu.
        # Đo thật: 4 câu như vậy trong một lần sinh.
        if cau in da_hoi:
            stat["bo_vi_trung_cau"] += 1
            continue
        da_hoi.add(cau)

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
