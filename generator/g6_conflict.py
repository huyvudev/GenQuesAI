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

# C5 lượt 1 (2026-08-19, 10 ca mẫu): 0/10 xác nhận là xung đột thật. Hai nguyên
# nhân giải thích 9/10 ca sai/không chắc — cả hai đều tự động hoá được, khác với
# điều kiện (3) (hệ quả pháp lý khác nhau) mà docstring module đã nói rõ là không
# tự động hoá được:
#
#   a) Điều kiện (1) "cùng còn hiệu lực" chỉ được xấp xỉ qua `hieu_luc_den is None`
#      của MỘT văn bản, không kiểm tra văn bản kia có phải chính là bên đã SỬA ĐỔI/
#      THAY THẾ/BÃI BỎ nó không. 4/10 ca sai (G6-0014, 0015, 0021, 0023) là cặp mà
#      một bên bãi bỏ trực tiếp bên kia (hoặc điều khoản liên quan) — không còn là
#      hai quy định song song để "xung đột". `tac_dong_toi()` đã có sẵn (G4 dùng)
#      và trả lời đúng câu hỏi này.
#   b) Điều kiện (2) "cùng điều chỉnh một nội dung cụ thể" dùng proxy Điều TRÙNG
#      TIÊU ĐỀ — nhưng các tiêu đề như "Hiệu lực thi hành", "Trách nhiệm thi hành",
#      "Tổ chức thực hiện" là mục THỦ TỤC xuất hiện gần như trong MỌI văn bản luật,
#      trùng tiêu đề ở đây không nói lên điều gì về nội dung. 3-4/10 ca sai/không
#      chắc (G6-0001, 0005, 0012, 0020) rơi đúng vào nhóm tiêu đề này.
#
# Vá cả hai. Điều kiện (3) vẫn KHÔNG tự động hoá được — mọi item vẫn ra
# `status="cho_review"`, người vẫn phải duyệt, nhưng bể ứng viên đưa cho người
# duyệt giờ sạch hơn nhiều thay vì đa số là rác có thể loại bằng máy.
#
# C5 lượt 2 (2026-08-19, 10 ca mẫu MỚI sau bản vá trên): vẫn 0/10 xung đột thật, dù
# tiêu đề không còn thuộc nhóm thủ tục ở trên (đúng như thiết kế). Đọc kỹ nội dung:
# 8/10 ca là "chỉ khác mức độ chi tiết" hoặc "khác nội dung cụ thể dù cùng tiêu đề" —
# và điểm chung: `con` HƯỚNG DẪN (GUIDED_BY) `me` theo đúng cách candidate được dựng,
# nên `con` LUÔN có xu hướng elaborate `me` một cách nhất quán chứ không mâu thuẫn —
# đây là bản chất quan hệ hướng dẫn, không phải lỗi trích riêng lẻ. Trong 8 ca đó,
# "Đối tượng áp dụng" và "Phạm vi điều chỉnh" (G6-0001, 0014, 0015, 0020 — 4/8) là
# tiêu đề Điều 1-2 GẦN NHƯ MỌI văn bản QPPL đều có theo thể thức chuẩn (NĐ 34/2016/NĐ-CP
# về kỹ thuật soạn thảo) — cùng bản chất thủ tục/kết cấu như nhóm đã loại ở trên, chỉ
# là bị bỏ sót. "Giải thích từ ngữ" (Điều 3, cũng chuẩn thể thức) thêm vào cho nhất
# quán dù ca mẫu (G6-0012) rơi vào lỗi khác (điều kiện 1, xem dưới).
#
# ĐÃ THỬ và KHÔNG dùng: so độ trùng lặp nội dung (Jaccard/overlap trên tập từ, và
# `framework.doi_chieu.do_phu` cửa sổ trượt) giữa hai đoạn Điều, hy vọng tách "chỉ
# khác chi tiết" (elaborate, nên giữ) khỏi "khác nội dung cụ thể" (nên loại). Đo trên
# 10 ca đã biết nhãn: cả hai độ đo cho điểm CHỒNG LẤN giữa hai nhóm (vd G6-0015 —
# elaborate, nên giữ — điểm THẤP hơn G6-0010 — khác nội dung, nên loại) — không tách
# được, và ngưỡng bất kỳ sẽ vừa lọt sai vừa loại nhầm. `do_phu` (thiết kế cho khớp
# NGUYÊN VĂN của A2) gần như luôn ra 0 giữa hai văn bản khác nhau dù cùng chủ đề —
# sai công cụ. Không đoán liều một ngưỡng chưa kiểm chứng được; ghi lại để người sau
# khỏi thử lại đúng hai hướng đã đi vào ngõ cụt này.
#
# Vấn đề gốc (elaborate do bản chất GUIDED_BY, không phải do chọn nhầm tiêu đề) VẪN
# CÒN sau bản vá này — cần nguồn ứng viên khác (vd cặp văn bản KHÔNG hướng dẫn nhau
# nhưng cùng chạm một vùng quản lý) hoặc so nội dung bằng embedding ngữ nghĩa thay vì
# từ vựng. Việc thiết kế lớn hơn, chưa làm ở đây.
_TIEU_DE_THU_TUC = (
    "hiệu lực thi hành", "trách nhiệm thi hành", "tổ chức thực hiện",
    "điều khoản thi hành", "điều khoản chung",
    "phạm vi điều chỉnh", "đối tượng áp dụng", "giải thích từ ngữ",
)


def _la_thu_tuc(tieu_de: str) -> bool:
    t = tieu_de.lower()
    return any(t == p or t.startswith(p + " ") or (p in t and len(t) < len(p) + 6)
               for p in _TIEU_DE_THU_TUC)


def ung_vien(c, pool: int, cap: int) -> list[dict]:
    """Bản duyệt `Corpus` của SELECT cũ (A1).

    Cặp (con hướng dẫn mẹ, khác cấp bậc) có hai Điều CÙNG TIÊU ĐỀ, cùng còn hiệu
    lực, và KHÔNG bên nào đã tác động (sửa đổi/thay thế/bãi bỏ) bên kia — ứng viên
    xung đột, người duyệt phán điều kiện (3) §4.2.
    `cap_bac` phải do corpus khai; framework không suy từ loai_vb.
    """
    from framework import truy_van as tv

    cap_ds: list[dict] = []
    for con in c.norms.values():
        if con.cap_bac is None or not con.so_hieu:
            continue
        for me_id in sorted(tv.huong_dan_cho(c, con.norm_id)):
            me = c.norms.get(me_id)
            if not (me and me.so_hieu and me.cap_bac is not None
                    and me.cap_bac != con.cap_bac):
                continue
            # (1) một bên đã sửa đổi/thay thế/bãi bỏ bên kia -> không còn là hai
            # quy định SONG SONG cùng hiệu lực, loại ngay, không đợi người duyệt.
            # nguon="ca_hai": mặc định "tu_dong" của tac_dong_toi() bỏ sót quan hệ chỉ
            # có ở cạnh trực tiếp (C5 lượt 3, G6-0012 — dù ca đó cuối cùng vẫn không có
            # trong đồ thị ở CẢ HAI nguồn, xác nhận qua Neo4j: khoảng trống dữ liệu,
            # không phải bỏ sót tham số — nhưng đồng bộ nguon vẫn đúng cho các ca khác).
            if (me.norm_id in tv.tac_dong_toi(c, con.norm_id, nguon="ca_hai")
                    or con.norm_id in tv.tac_dong_toi(c, me.norm_id, nguon="ca_hai")):
                continue
            cap_ds.append((con, me))
    cap_ds.sort(key=lambda x: (x[0].norm_id, x[1].norm_id))
    cap_ds = cap_ds[:pool]

    def dieu_hieu_luc(norm_id):
        ra = {}
        for d in tv.moi_thanh_phan(c, norm_id):
            if d.loai != "Dieu" or not d.tieu_de or len(d.tieu_de) < 15:
                continue
            if _la_thu_tuc(d.tieu_de):          # (2) tiêu đề thủ tục -> không phải
                continue                        # bằng chứng "cùng nội dung cụ thể"
            for e in tv.cac_ban(c, d.component_id):
                if e.hieu_luc_den is None:
                    ra.setdefault(d.tieu_de.lower(), (d.tieu_de, e.expression_id))
        return ra

    kq: list[dict] = []
    for con, me in cap_ds:
        if len(kq) >= cap:
            break
        dc, dm = dieu_hieu_luc(con.norm_id), dieu_hieu_luc(me.norm_id)
        for khoa in sorted(dc.keys() & dm.keys()):
            kq.append({
                "con_sh": con.so_hieu, "con_cap": con.cap_bac, "con_id": con.norm_id,
                "me_sh": me.so_hieu, "me_cap": me.cap_bac, "me_id": me.norm_id,
                "chu_de": dc[khoa][0], "ex_con": dc[khoa][1], "ex_me": dm[khoa][1],
            })
            if len(kq) >= cap:
                break
    return kq


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


def build(c, store, n: int = 25, pool: int = 4000,
          seed: int = 20260806) -> tuple[list[Item], dict]:
    rng = random.Random(seed)
    rows = ung_vien(c, pool, n * 8)
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
