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
def mau_so_hieu(c, k: int) -> list[dict]:
    """400 văn bản mới nhất có số hiệu + ngày hiệu lực — nguyên liệu cho cả 4 công thức."""
    ds = [n for n in c.norms.values() if n.so_hieu and n.ngay_hieu_luc]
    ds.sort(key=lambda n: (-n.ngay_hieu_luc.toordinal(), n.norm_id))
    return [{"so_hieu": n.so_hieu, "norm_id": n.norm_id, "hl": n.ngay_hieu_luc}
            for n in ds[:k]]


def dieu_cua_vb(c, norm_id: str) -> list:
    from framework import truy_van as tv
    return sorted({d.so_thu_tu for d in tv.moi_thanh_phan(c, norm_id)
                   if d.loai == "Dieu" and d.so_thu_tu})


def ton_tai(c, sh: str) -> bool:
    """Số hiệu bịa có TRÙNG văn bản thật không — bắt buộc kiểm trước khi dùng."""
    return any(sh in (n.so_hieu or "") for n in c.norms.values())

# (d) ngoài phạm vi đã nạp — chủ đề chắc chắn không có trong corpus luật VN.
#
# Danh sách này là TRẦN CỨNG cho số câu công thức (d): mỗi chủ đề chỉ dùng được MỘT
# lần. Bản đầu có 5 chủ đề trong khi quota (d) ở n=25 là 7, và vòng lặp quay vòng
# `NGOAI_PHAM_VI[quota["d"] % len(...)]` -> sinh ra 2 câu TRÙNG NGUYÊN VĂN
# (G8-0003 ≡ G8-0020, G8-0004 ≡ G8-0024). Bộ đề tính 25 câu G8 nhưng chỉ có 23 câu
# phân biệt, 2 câu bị đếm hai lần khi chấm chiều `behavior`.
#
# Nay: đủ dài cho quota lớn hơn nhiều, và `build()` KHÔNG còn quay vòng — hết chủ đề
# thì (d) đóng lại và nhường chỗ cho a/b/c, chứ không lặp lại.
NGOAI_PHAM_VI = [
    "quy định của Liên minh châu Âu về nhãn sinh thái cho đồ chơi trẻ em",
    "luật liên bang Hoa Kỳ về đăng ký nhãn hiệu âm thanh",
    "quy chuẩn của Nhật Bản về kiểm định thang máy dân dụng",
    "công ước quốc tế về khai thác khoáng sản trên Mặt Trăng",
    "luật bang California về quyền riêng tư dữ liệu sinh trắc học",
    "chỉ thị của Liên minh châu Âu về hộ chiếu vắc-xin cho vật nuôi",
    "luật liên bang Đức về trách nhiệm dân sự của robot tự hành",
    "quy định của Anh về cấp phép khai thác năng lượng sóng biển",
    "công ước Nam Cực về bảo tồn loài nhuyễn thể",
    "luật bang Queensland về đăng kiểm tàu lượn siêu tốc",
    "quy chuẩn của Hàn Quốc về ghi nhãn dinh dưỡng thức ăn cho cá cảnh",
    "hiệp định ASEAN về công nhận lẫn nhau chứng chỉ lặn biển giải trí",
    "quy định của Thuỵ Sĩ về lưu ký vàng trong hầm dân sự",
    "luật liên bang Canada về bản quyền tiếng kêu động vật hoang dã",
    "quy chuẩn của Na Uy về an toàn trang trại cá hồi ngoài khơi",
    "công ước quốc tế về phân bổ quỹ đạo vệ tinh siêu nhỏ",
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


def build(c, store, n: int = 25, seed: int = 20260806) -> tuple[list[Item], dict]:
    rng = random.Random(seed)
    mau = mau_so_hieu(c, 400)
    rng.shuffle(mau)

    items: list[Item] = []
    stat = {"mau": len(mau), "a": 0, "b": 0, "c": 0, "d": 0, "bo_vi_trung_that": 0,
            "bo_vi_trung_cau": 0}
    quota = {"a": 0, "b": 0, "c": 0, "d": 0}
    can = {"a": n // 4, "b": n // 4, "c": n // 4, "d": n - 3 * (n // 4)}

    # (d) không tái sử dụng chủ đề -> trần cứng là số chủ đề có sẵn. Phần dư chuyển
    # cho a/b/c thay vì lặp lại chủ đề: một câu trùng làm lệch trọng số khi chấm,
    # còn thiếu một câu thì `run_all` báo "← THIẾU" và người ta thấy ngay.
    if can["d"] > len(NGOAI_PHAM_VI):
        du = can["d"] - len(NGOAI_PHAM_VI)
        can["d"] = len(NGOAI_PHAM_VI)
        for i, k in enumerate(("a", "b", "c")):
            can[k] += du // 3 + (1 if i < du % 3 else 0)

    da_hoi: set[str] = set()          # chặn trùng ở MỌI công thức, không riêng (d)

    for r in mau:
        if len(items) >= n:
            break
        sh = core_so_hieu(r["so_hieu"])
        if not sh:
            continue
        # Chỉ xét công thức còn chỗ. Bản cũ chọn công thức ít đầy nhất rồi `continue`
        # nếu nó đã đầy — nghĩa là khi một công thức cạn, mọi dòng còn lại đều bị bỏ
        # và các công thức khác không bao giờ lấp được phần thiếu.
        con_cho = [k for k in ("a", "b", "c", "d") if quota[k] < can[k]]
        if not con_cho:
            break
        ct = min(con_cho, key=lambda k: quota[k] / max(can[k], 1))

        it = None
        if ct == "a":
            gia = _doi_so(sh, rng)
            if not gia:
                continue
            # Bắt buộc đối chiếu: số bịa ra mà TRÙNG văn bản thật thì câu hỏi có đáp án.
            if ton_tai(c, gia):
                stat["bo_vi_trung_that"] += 1
                continue
            it = Item(id="", cong_thuc="a",
                      question_template="{sh} quy định về nội dung gì?",
                      user_input=f"{gia} quy định về nội dung gì?",
                      reference_fields={"so_hieu_gia": gia})

        elif ct == "b":
            ds = dieu_cua_vb(c, r["norm_id"])
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
            nam = r["hl"].year          # Corpus trả datetime.date thuần
            truoc = nam - rng.randint(3, 10)
            it = Item(id="", cong_thuc="c",
                      question_template="Năm {nam}, {sh} quy định thế nào về vấn đề này?",
                      user_input=f"Năm {truoc}, {sh} quy định thế nào về vấn đề này?",
                      reference_fields={"so_hieu": sh, "nam_hoi": truoc,
                                        "nam_ban_hanh": nam})
        else:
            # KHÔNG quay vòng: `can["d"]` đã bị chặn ở `len(NGOAI_PHAM_VI)` phía trên
            # nên chỉ số luôn hợp lệ, và mỗi chủ đề chỉ dùng đúng một lần.
            cd = NGOAI_PHAM_VI[quota["d"]]
            it = Item(id="", cong_thuc="d", persona="luat_su",
                      question_template="{chu_de} hiện nay thế nào?",
                      user_input=f"{cd} hiện nay quy định thế nào?",
                      reference_fields={"chu_de_ngoai_pham_vi": cd})

        # Lưới cuối: hai câu hỏi giống hệt nhau là hai lần chấm cùng một thứ. Công
        # thức (a) bịa số ngẫu nhiên nên vẫn có thể va nhau; (b)/(c) có thể trùng nếu
        # cùng một văn bản lọt vào mẫu hai lần.
        if it.user_input in da_hoi:
            stat["bo_vi_trung_cau"] += 1
            continue
        da_hoi.add(it.user_input)

        it.id = f"G8-{len(items):04d}"
        it.question_pre_paraphrase = it.user_input
        it.gates = {"C1": "n/a_khong_co_span", "C2": "n/a_lookup",
                    "C3": "n/a_khong_co_dap_an",
                    "C4": "n/a_muc_tieu_la_tu_choi", "C5": "not_sampled"}
        items.append(it)
        quota[ct] += 1
        stat[ct] += 1

    return items, stat
