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

SELECT = """
MATCH (n:Norm)-[:HAS_PART*]->(d:Component)-[:HAS_VERSION]->(e:Expression)
WHERE d.loai = 'Dieu'
  AND e.hieu_luc_den IS NULL
  AND n.so_hieu IS NOT NULL AND n.ngay_hieu_luc IS NOT NULL
  AND d.tieu_de IS NOT NULL AND size(d.tieu_de) > 8
  AND NONE(k IN $loai_tru WHERE toLower(d.tieu_de) CONTAINS k)
// anh em gần (§5.3). order_key đánh số trên MỌI Component (gồm Khoản/Điểm) nên hai
// Điều liền nhau cách xa về order_key -> lọc theo so_thu_tu mới đúng "liền kề".
CALL (n, d) {
  MATCH (n)-[:HAS_PART*]->(k:Component)-[:HAS_VERSION]->(ke:Expression)
  WHERE k.loai = 'Dieu' AND k.comp_id <> d.comp_id AND ke.hieu_luc_den IS NULL
  RETURN collect(DISTINCT ke.expr_id)[0..2] AS ke_expr
}
// Bẫy cross-norm (cùng số Điều, văn bản khác) KHÔNG tính ở đây: nó quét toàn đồ thị
// cho MỖI ứng viên -> query treo. Tính riêng bằng BAY_KHAC_VB, chỉ cho item đã chọn.
RETURN n.norm_id AS norm_id, n.so_hieu AS so_hieu, n.tieu_de AS norm_tieu_de,
       n.linh_vuc AS linh_vuc, n.loai_vb AS loai_vb,
       d.comp_id AS comp_id, d.so_thu_tu AS stt, d.tieu_de AS dieu_tieu_de,
       d.duong_dan AS duong_dan, e.expr_id AS expr_id,
       ke_expr AS anh_em
ORDER BY n.ngay_hieu_luc DESC
LIMIT $pool
"""

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
BAY_KHAC_VB = """
MATCH (n2:Norm)-[:HAS_PART]->(k2:Component)-[:HAS_VERSION]->(e2:Expression)
WHERE n2.linh_vuc = $linh_vuc AND n2.norm_id <> $norm_id
  AND k2.loai = 'Dieu' AND k2.so_thu_tu = $stt AND e2.hieu_luc_den IS NULL
RETURN e2.expr_id AS ex LIMIT 2
"""


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


def build(neo, store, n: int = 90, pool: int = 4000, ty_le_situation: float = 0.6,
          seed: int = 20260806) -> tuple[list[Item], dict]:
    rng = random.Random(seed)
    rows = neo.run(SELECT, pool=pool, loai_tru=LOAI_TRU)
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
        try:
            ex_bay += [x["ex"] for x in neo.run(
                BAY_KHAC_VB, norm_id=r["norm_id"], linh_vuc=r["linh_vuc"],
                stt=r["stt"])]
        except Exception:
            pass                                  # thiếu bẫy không làm hỏng item
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
