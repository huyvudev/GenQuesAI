"""G8 — câu hỏi KHÔNG có đáp án (§4.3). Đo hallucination trực tiếp.

Nhóm rẻ nhất: bốn trong năm công thức hoàn toàn deterministic. Đáp án kỳ vọng là
NHÃN `không có thông tin`, chấm bằng tỷ lệ từ chối đúng — chỉ số RIÊNG, không gộp
vào accuracy (§6).

`gold_spans` RỖNG là đúng theo thiết kế: không có đoạn văn bản nào để trích dẫn cho
một câu hỏi không có đáp án. Đây là ngoại lệ duy nhất của tiêu chí "100% item có
gold_spans" ở Mục 9 — xem ghi chú trong run_all.py.
"""
from __future__ import annotations

import random
import re
from dataclasses import dataclass, field

from .common import core_so_hieu

# (a) số hiệu đúng hình thức nhưng KHÔNG tồn tại — lấy mẫu thật rồi đổi số
MAU_SO_HIEU = """
MATCH (n:Norm) WHERE n.so_hieu IS NOT NULL AND n.ngay_hieu_luc IS NOT NULL
RETURN n.so_hieu AS so_hieu, n.norm_id AS norm_id, n.ngay_hieu_luc AS hl
ORDER BY n.ngay_hieu_luc DESC LIMIT $k
"""
# (b) số Điều vượt quá: lấy các số Điều CÓ THẬT của một văn bản
DIEU_CUA_VB = """
MATCH (n:Norm {norm_id:$norm_id})-[:HAS_PART*]->(d:Component)
WHERE d.loai = 'Dieu' AND d.so_thu_tu IS NOT NULL
RETURN collect(DISTINCT d.so_thu_tu) AS ds
"""
TON_TAI = "MATCH (n:Norm) WHERE n.so_hieu CONTAINS $sh RETURN count(n) AS c"

# (d) ngoài phạm vi đã nạp — chủ đề chắc chắn không có trong corpus luật VN
NGOAI_PHAM_VI = [
    "quy định của Liên minh châu Âu về nhãn sinh thái cho đồ chơi trẻ em",
    "luật liên bang Hoa Kỳ về đăng ký nhãn hiệu âm thanh",
    "quy chuẩn của Nhật Bản về kiểm định thang máy dân dụng",
    "công ước quốc tế về khai thác khoáng sản trên Mặt Trăng",
    "luật bang California về quyền riêng tư dữ liệu sinh trắc học",
]


@dataclass
class Item:
    id: str
    group: str = "G8"
    question_form: str = "lookup"
    persona: str = "can_bo_phap_che"
    user_input: str = ""
    question_template: str = ""
    question_pre_paraphrase: str = ""
    cong_thuc: str = ""                    # a | b | c | d
    reference: str = "không có thông tin"
    reference_type: str = "label"
    reference_fields: dict = field(default_factory=dict)
    gold_spans: list = field(default_factory=list)      # RỖNG — đúng thiết kế
    reference_contexts: list = field(default_factory=list)
    gold_node_ids: list = field(default_factory=list)
    distractor_ids: list = field(default_factory=list)
    evidence: str = "khong_ton_tai"
    gates: dict = field(default_factory=dict)
    grader: str = "ty_le_tu_choi"
    difficulty: str = "medium"
    human_verified: bool = False


def _doi_so(sh: str, rng: random.Random) -> str | None:
    """'15/2018/NĐ-CP' -> '873/2018/NĐ-CP'. Số lớn bất thường -> chắc chắn không có."""
    m = re.match(r"^(\d+)(/\d{4}/.+)$", sh)
    if not m:
        return None
    return f"{rng.randint(700, 999)}{m.group(2)}"


def build(neo, store, n: int = 25, seed: int = 20260806) -> tuple[list[Item], dict]:
    rng = random.Random(seed)
    mau = neo.run(MAU_SO_HIEU, k=400)
    rng.shuffle(mau)

    items: list[Item] = []
    stat = {"mau": len(mau), "a": 0, "b": 0, "c": 0, "d": 0, "bo_vi_trung_that": 0}
    quota = {"a": 0, "b": 0, "c": 0, "d": 0}
    can = {"a": n // 4, "b": n // 4, "c": n // 4, "d": n - 3 * (n // 4)}

    for r in mau:
        if len(items) >= n:
            break
        sh = core_so_hieu(r["so_hieu"])
        if not sh:
            continue
        ct = min(("a", "b", "c", "d"), key=lambda k: quota[k] / max(can[k], 1))
        if quota[ct] >= can[ct]:
            continue

        it = None
        if ct == "a":
            gia = _doi_so(sh, rng)
            if not gia:
                continue
            # Bắt buộc đối chiếu: số bịa ra mà TRÙNG văn bản thật thì câu hỏi có đáp án.
            if neo.run(TON_TAI, sh=gia)[0]["c"] > 0:
                stat["bo_vi_trung_that"] += 1
                continue
            it = Item(id="", cong_thuc="a",
                      question_template="{sh} quy định về nội dung gì?",
                      user_input=f"{gia} quy định về nội dung gì?",
                      reference_fields={"so_hieu_gia": gia})

        elif ct == "b":
            ds = neo.run(DIEU_CUA_VB, norm_id=r["norm_id"])[0]["ds"] or []
            so = [int(x) for x in ds if str(x).isdigit()]
            if not so:
                continue
            vuot = max(so) + rng.randint(50, 150)
            it = Item(id="", cong_thuc="b",
                      question_template="Điều {stt} của {sh} quy định gì?",
                      user_input=f"Điều {vuot} của {sh} quy định gì?",
                      reference_fields={"so_hieu": sh, "dieu_khong_ton_tai": vuot,
                                        "dieu_lon_nhat_thuc_te": max(so)})

        elif ct == "c":
            hl = r["hl"]
            nam = (hl.to_native() if hasattr(hl, "to_native") else hl).year
            truoc = nam - rng.randint(3, 10)
            it = Item(id="", cong_thuc="c",
                      question_template="Năm {nam}, {sh} quy định thế nào về vấn đề này?",
                      user_input=f"Năm {truoc}, {sh} quy định thế nào về vấn đề này?",
                      reference_fields={"so_hieu": sh, "nam_hoi": truoc,
                                        "nam_ban_hanh": nam})
        else:
            cd = NGOAI_PHAM_VI[quota["d"] % len(NGOAI_PHAM_VI)]
            it = Item(id="", cong_thuc="d", persona="luat_su",
                      question_template="{chu_de} hiện nay thế nào?",
                      user_input=f"{cd} hiện nay quy định thế nào?",
                      reference_fields={"chu_de_ngoai_pham_vi": cd})

        it.id = f"G8-{len(items):04d}"
        it.question_pre_paraphrase = it.user_input
        it.gates = {"C1": "n/a_khong_co_span", "C2": "n/a_lookup",
                    "C3": "n/a_khong_co_dap_an",
                    "C4": "n/a_muc_tieu_la_tu_choi", "C5": "not_sampled"}
        items.append(it)
        quota[ct] += 1
        stat[ct] += 1

    return items, stat
