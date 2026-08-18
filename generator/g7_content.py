"""G7 — câu hỏi nội dung thông thường.

Nhóm lớn nhất (90 câu) và là nhóm ĐẦU TIÊN thật sự đo vector retrieval: G1 chỉ đo
đường đi tới metadata. Đáp án là `span` — trọn nội dung một Điều còn hiệu lực.

Điều kiện chọn ca, mỗi cái có lý do:
  · Expression còn mở (hieu_luc_den IS NULL)  -> hỏi hiện tại, không lẫn G2'
  · n_parts = 1                               -> trọn nội dung nằm trong MỘT chunk,
                                                 nếu không đáp án trải nhiều chunk và
                                                 context_recall không còn nghĩa rõ
  · loại bỏ Điều thủ tục ("hiệu lực thi hành",
    "tổ chức thực hiện"...)                   -> đó là boilerplate, và G1 đã dùng
  · độ dài 300–2500 ký tự                     -> đủ nội dung để hỏi, đủ ngắn để chấm
"""
from __future__ import annotations

import random
import re
from dataclasses import dataclass, field

from .common import core_so_hieu
from .gold import chunk_span, gate_c1

MAX_MOI_NORM = 2          # tối đa 2 câu / văn bản — tránh bộ đề dồn vào vài văn bản
MIN_LEN, MAX_LEN = 300, 2500

# Tiêu đề Điều mang tính thủ tục -> không phải nội dung quy phạm, loại khỏi G7.
# Bốn cái cuối là BOILERPLATE có mặt ở gần như mọi văn bản: hỏi "quy định về giải
# thích từ ngữ" mà không nêu số hiệu thì mơ hồ giữa 66.368 văn bản — câu vô nghĩa,
# và với dạng `situation` thì không có đáp án đúng duy nhất.
LOAI_TRU = ["hiệu lực", "thi hành", "tổ chức thực hiện", "trách nhiệm thi hành",
            "điều khoản chuyển tiếp", "quy định chuyển tiếp", "bãi bỏ",
            "giải thích từ ngữ", "phạm vi điều chỉnh", "đối tượng áp dụng",
            "nguyên tắc chung"]

# Tiêu đề dùng cho câu `situation` phải đủ dài để xác định chủ đề nhưng đủ ngắn để
# ra câu hỏi thật. Tiêu đề 250 ký tự nhét vào câu hỏi vừa không giống người hỏi, vừa
# là RÒ RỈ TỪ KHOÁ: trùng nguyên văn với chunk đích thì BM25 trúng ngay (§5.2).
SIT_TIEU_DE_MIN, SIT_TIEU_DE_MAX = 12, 80

# Tiêu đề hỏng do parse: ", Điều 42 Nghị định số 86/2018/NĐ-CP đã được". Nhét vào câu
# `situation` thì vừa vô nghĩa vừa LÀM LỘ số hiệu — đúng thứ dạng situation phải giấu.
_TD_XAU = re.compile(r"\d+/\d{4}/[A-ZĐ]|\b(?:điều|khoản|điểm)\s+\d", re.IGNORECASE)


def tieu_de_hop_le(td: str) -> bool:
    if not (SIT_TIEU_DE_MIN <= len(td) <= SIT_TIEU_DE_MAX):
        return False
    if not td[:1].isalpha():           # bắt đầu bằng dấu câu/chữ số -> parse hỏng
        return False
    return not _TD_XAU.search(td)

def ung_vien(c, pool: int, loai_tru: list[str]) -> list[dict]:
    """Bản duyệt `Corpus` của SELECT cũ (A1).

    Mọi Điều còn hiệu lực, tiêu đề sạch, của văn bản có số hiệu + ngày hiệu lực.
    Anh em gần: 2 Điều khác cùng văn bản, còn hiệu lực — sắp theo expr_id cho xác
    định (bài học `collect()[0..2]` không sắp của bản Cypher).
    """
    from framework import truy_van as tv

    ra: list[dict] = []
    for n in c.norms.values():
        if not (n.so_hieu and n.ngay_hieu_luc):
            continue
        dieu_mo: list[tuple] = []           # (Component, Expression) còn hiệu lực
        for d in tv.moi_thanh_phan(c, n.norm_id):
            if d.loai != "Dieu":
                continue
            for e in tv.cac_ban(c, d.component_id):
                if e.hieu_luc_den is None:
                    dieu_mo.append((d, e))
        for d, e in dieu_mo:
            td = d.tieu_de or ""
            if len(td) <= 8 or any(x in td.lower() for x in loai_tru):
                continue
            anh_em = sorted(e2.expression_id for d2, e2 in dieu_mo
                            if d2.component_id != d.component_id)[:2]
            ra.append({
                "norm_id": n.norm_id, "so_hieu": n.so_hieu, "norm_tieu_de": n.tieu_de,
                "linh_vuc": [], "loai_vb": n.loai_vb,
                "comp_id": d.component_id, "stt": d.so_thu_tu, "dieu_tieu_de": td,
                "duong_dan": f"Dieu {d.so_thu_tu}", "expr_id": e.expression_id,
                "anh_em": anh_em, "_hl": n.ngay_hieu_luc,
            })
    ra.sort(key=lambda r: (-r["_hl"].toordinal(), r["expr_id"]))
    return ra[:pool]


def bay_khac_vb(c, norm_id: str, stt) -> list[str]:
    """Bẫy cross-norm: Điều CÙNG SỐ ở văn bản khác, còn hiệu lực. Lấy 2, xác định.

    Bản Cypher lọc `n2.linh_vuc = $linh_vuc` nhưng `linh_vuc` là [] ở TOÀN BỘ Norm
    (đo 2026-08-06) nên điều kiện luôn đúng — thực chất là "văn bản bất kỳ". Giữ đúng
    hành vi đó.
    """
    from framework import truy_van as tv
    ra = []
    for n2 in c.norms.values():
        if n2.norm_id == norm_id:
            continue
        for d in tv.moi_thanh_phan(c, n2.norm_id):
            if d.loai != "Dieu" or d.so_thu_tu != stt:
                continue
            for e in tv.cac_ban(c, d.component_id):
                if e.hieu_luc_den is None:
                    ra.append(e.expression_id)
    return sorted(ra)[:2]


# `lookup` — người hỏi biết số hiệu. Đo metadata + retrieval có mồi từ khoá.
TPL_LOOKUP = [
    "Điều {stt} của {so_hieu} quy định gì?",
    "{so_hieu} quy định thế nào về {tieu_de}?",
    "Nội dung Điều {stt} {so_hieu} là gì?",
]
# Dùng khi tiêu đề Điều không sạch — chỉ neo vào số Điều, không trích tiêu đề.
TPL_LOOKUP_KHONG_TD = [
    "Điều {stt} của {so_hieu} quy định gì?",
    "Nội dung Điều {stt} {so_hieu} là gì?",
]
# `situation` — CỐ Ý bỏ số hiệu và số Điều. Đây là dạng đo retrieval thật, và là
# đầu vào cho paraphrase(). Bỏ định danh nên C2 chỉ cần chặn thực thể MỚI.
TPL_SITUATION = [
    "Quy định hiện hành về {tieu_de} như thế nào?",
    "Hiện nay {tieu_de} được quy định ra sao?",
    "Tôi cần biết quy định về {tieu_de}.",
]


# Chạy RIÊNG cho từng item đã chọn (~90 lần) thay vì lồng trong SELECT (~6.000 lần).
# LƯU Ý: `linh_vuc` là [] ở TOÀN BỘ 66.368 Norm (đo 2026-08-06) nên điều kiện dưới
# luôn đúng — thực tế bẫy là "cùng số Điều, văn bản bất kỳ", vẫn hợp lệ theo §5.3
# nhưng KHÔNG được thu hẹp theo lĩnh vực như tên gọi gợi ý.



@dataclass
class Item:
    id: str
    group: str = "G7"
    question_form: str = "lookup"
    persona: str = "can_bo_phap_che"
    user_input: str = ""
    question_template: str = ""
    question_pre_paraphrase: str = ""     # bản template trước khi LLM viết lại
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
    difficulty: str = "medium"
    human_verified: bool = False


PERSONA_SIT = ["chu_ho_kinh_doanh", "nguoi_dan", "luat_su"]


def build(c, store, n: int = 90, pool: int = 4000, ty_le_situation: float = 0.6,
          seed: int = 20260806) -> tuple[list[Item], dict]:
    rng = random.Random(seed)
    rows = ung_vien(c, pool, LOAI_TRU)

    # SẮP CHUẨN trước khi trộn. `shuffle` cho hoán vị phụ thuộc thứ tự ĐẦU VÀO, nên
    # nếu nguồn trả về thứ tự khác thì cùng seed vẫn ra bộ câu khác. Đo thật trên hai
    # lần chạy cùng tham số: 87/90 câu lệch (dạng câu, persona, khuôn, bẫy).
    #
    # Sắp ở đây thay vì chỉ dựa vào ORDER BY của Cypher, vì A1 sẽ thay Cypher bằng
    # duyệt `Corpus` — thứ tự duyệt cây KHÔNG có lý do gì trùng thứ tự Neo4j. Khoá
    # chuẩn hoá ở tầng Python là thứ duy nhất sống sót qua cuộc đổi đó.
    rows = sorted(rows, key=lambda r: str(r["expr_id"]))
    rng.shuffle(rows)

    items: list[Item] = []
    dem_norm: dict[str, int] = {}
    stat = {"ung_vien": len(rows), "c1_pass": 0, "c1_fail": 0,
            "bo_vi_so_hieu": 0, "bo_vi_trung_norm": 0, "bo_vi_khong_co_chunk": 0,
            "bo_vi_nhieu_part": 0, "bo_vi_do_dai": 0,
            "tieu_de_khong_hop_situation": 0}
    can_sit = int(round(n * ty_le_situation))

    for r in rows:
        if len(items) >= n:
            break
        so_hieu = core_so_hieu(r["so_hieu"])
        if not so_hieu or not r["stt"]:
            stat["bo_vi_so_hieu"] += 1
            continue
        if dem_norm.get(r["norm_id"], 0) >= MAX_MOI_NORM:
            stat["bo_vi_trung_norm"] += 1
            continue

        span, pl = chunk_span(store, r["expr_id"], 0)
        if span is None:
            stat["bo_vi_khong_co_chunk"] += 1
            continue
        if int(pl.get("n_parts", 1)) != 1:
            stat["bo_vi_nhieu_part"] += 1      # nội dung trải nhiều chunk -> bỏ
            continue
        if not (MIN_LEN <= len(span.text) <= MAX_LEN):
            stat["bo_vi_do_dai"] += 1
            continue

        ok, ly_do = gate_c1(store, span)
        if not ok:
            stat["c1_fail"] += 1
            continue
        stat["c1_pass"] += 1

        # Cân dạng câu: đủ situation trước, phần còn lại là lookup.
        # Chỉ tiêu đề đủ đặc trưng mới làm được câu `situation` — tiêu đề quá dài là
        # rò rỉ từ khoá, quá ngắn thì mơ hồ giữa hàng chục nghìn văn bản.
        so_sit = sum(1 for x in items if x.question_form == "situation")
        tieu_de = (r["dieu_tieu_de"] or "").strip().rstrip(".")
        hop_sit = tieu_de_hop_le(tieu_de)
        la_sit = so_sit < can_sit and hop_sit
        if not hop_sit:
            stat["tieu_de_khong_hop_situation"] += 1
        if la_sit:
            tpl = TPL_SITUATION[len(items) % len(TPL_SITUATION)]
            cau = tpl.format(tieu_de=tieu_de[:1].lower() + tieu_de[1:])
            persona = PERSONA_SIT[len(items) % len(PERSONA_SIT)]
        else:
            # Khuôn có {tieu_de} chỉ dùng khi tiêu đề sạch. Tiêu đề hỏng kiểu
            # 'khoản 7 Điều 62; khoản 1 Điều 63; cụm từ "Bộ Thông tin và Truyền'
            # nhét vào sẽ ra câu hỏi vô nghĩa — rơi về khuôn chỉ dùng số Điều.
            kho = TPL_LOOKUP if tieu_de_hop_le(tieu_de) else TPL_LOOKUP_KHONG_TD
            tpl = kho[len(items) % len(kho)]
            cau = tpl.format(stt=r["stt"], so_hieu=so_hieu, tieu_de=tieu_de)
            persona = "can_bo_phap_che"

        # Bẫy: Điều khác cùng văn bản + cùng số Điều ở văn bản khác cùng lĩnh vực.
        ex_bay = list(r["anh_em"] or [])
        ex_bay += bay_khac_vb(c, r["norm_id"], r["stt"])
        bay = []
        for ex in dict.fromkeys(ex_bay):
            s2, _ = chunk_span(store, ex, 0)
            if s2:
                bay.append(s2.chunk_id)

        it = Item(
            id=f"G7-{len(items):04d}",
            question_form="situation" if la_sit else "lookup",
            persona=persona,
            user_input=cau,
            question_template=tpl,
            question_pre_paraphrase=cau,
            reference=span.text,
            reference_fields={"norm_id": r["norm_id"], "so_hieu": so_hieu,
                              "dieu": r["duong_dan"], "tieu_de": tieu_de},
            gold_spans=[span.to_json()],
            reference_contexts=[span.text],
            gold_node_ids=[f"Expression:{r['expr_id']}"],
            distractor_ids=bay,
        )
        it.gates = {"C1": ly_do,
                    "C2": "chua_paraphrase" if la_sit else "n/a_lookup",
                    "C3": "deterministic",     # reference LÀ chính chunk -> hiển nhiên
                    "C4": "not_run", "C5": "not_sampled"}
        items.append(it)
        dem_norm[r["norm_id"]] = dem_norm.get(r["norm_id"], 0) + 1

    return items, stat
