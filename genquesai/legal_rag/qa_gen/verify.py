"""Bước 3 — chấm đề, 2 vòng + quality gate cuối.

Vòng 1 (omission test): giữ Y HỆT cơ chế bản gốc (proposed.ipynb) — LLM đọc 2 đoạn,
hỏi có cần cả 2 không. Cơ chế này không phụ thuộc ngôn ngữ/embedding model nên dùng
thẳng được cho tiếng Việt, không cần sửa.

Vòng 2 (đối chiếu hiệu lực, MỚI — đặc thù luật): KHÔNG suy luận status từ cạnh như
spec bản đầu đề xuất — đọc THẲNG `hieu_luc_den` đã có sẵn trên từng Dieu (đã tính
đúng hiệu lực domino), vì đây là nguồn dữ liệu đáng tin nhất, thay vì tự suy luận
lại (rủi ro sai — xem thảo luận kiến trúc 2026-08-26)."""
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor

_P_OMISSION = (
    "Quyết định câu hỏi sau có THỰC SỰ cần CẢ HAI ngữ cảnh không.\n\n"
    "CÂU HỎI:\n{q}\n\nNGỮ CẢNH A:\n{a}\n\nNGỮ CẢNH B:\n{b}\n\n"
    "- tra_loi_duoc_chi_voi_a: có thể trả lời đầy đủ CHỈ với A (bỏ qua B) không?\n"
    "- tra_loi_duoc_chi_voi_b: có thể trả lời đầy đủ CHỈ với B (bỏ qua A) không?\n"
    'Trả JSON: {{"tra_loi_duoc_chi_voi_a": <true|false>, "tra_loi_duoc_chi_voi_b": <true|false>}}'
)

_P_ANSWERABILITY = (
    "Cho CÂU HỎI, NGỮ CẢNH và ĐÁP ÁN đề xuất, chấm điểm 1-5 mức độ câu hỏi trả lời "
    "được từ ngữ cảnh VÀ đáp án được ngữ cảnh hỗ trợ đúng.\n\n"
    "CÂU HỎI:\n{q}\n\nNGỮ CẢNH:\n{c}\n\nĐÁP ÁN:\n{a}\n\n"
    'Trả JSON: {{"diem": <int 1-5>}} (5=trả lời đầy đủ+đúng, 1=không liên quan/sai hẳn).'
)

_P_CHAM_BAY_HIEU_LUC = (
    "Đáp án dưới đây trả lời cho 1 câu hỏi về quy định ĐÃ HẾT HIỆU LỰC. Đáp án CHUẨN "
    "phải có cảnh báo rõ ràng rằng đây là quy định cũ/đã hết hiệu lực.\n\n"
    "ĐÁP ÁN:\n{a}\n\n"
    'Trả JSON: {{"co_canh_bao_het_hieu_luc": <true|false>}}'
)

ANSWERABILITY_MIN = 3
_SYS = "Bạn là chuyên gia chấm chất lượng QA cho benchmark RAG pháp luật Việt Nam. Chỉ trả JSON hợp lệ, không giải thích thêm."


def _map_limit(fn, items, workers: int) -> list:
    if not items:
        return []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(fn, items))


def vong_1_omission(llm, rows: list[dict], workers: int = 8) -> tuple[list[dict], dict]:
    """Áp cho 4 loại 2-ngữ-cảnh: structural_multihop, validity_change,
    cross_norm_guidance (multi-hop liên văn bản, thêm 2026-09-04), cross_field_multihop
    (multi-hop liên NGÀNH luật, thêm 2026-09-05 — bar SINH đã nới thành "cần cả 2 để
    đầy đủ" thay vì "bắt buộc mới trả lời được", nhưng vòng kiểm tra độc lập này GIỮ
    NGUYÊN câu hỏi gốc để chặn tiếp ca thực ra chỉ cần 1 bên)."""
    can_cham = [(i, r) for i, r in enumerate(rows)
               if r["type"] in ("structural_multihop", "validity_change", "cross_norm_guidance",
                                "cross_field_multihop")]
    if not can_cham:
        return rows, {"omission_checked": 0, "omission_drop": 0}

    def _cham(item):
        i, r = item
        out = llm.chat_json(_SYS, _P_OMISSION.format(q=r["question"], a=r["contexts"][0][:1500],
                                                     b=r["contexts"][1][:1500]),
                            temperature=0.0, max_tokens=100)
        if not out:
            return i, None  # loi goi LLM -> khong ro, giu lai (khong phat vo co)
        a_only = bool(out.get("tra_loi_duoc_chi_voi_a", True))
        b_only = bool(out.get("tra_loi_duoc_chi_voi_b", True))
        return i, (not a_only) and (not b_only)

    ket_qua = _map_limit(_cham, can_cham, workers)
    drop_idx = {i for i, giu in ket_qua if giu is False}
    kept = [r for i, r in enumerate(rows) if i not in drop_idx]
    return kept, {"omission_checked": len(can_cham), "omission_drop": len(drop_idx)}


def vong_2_hieu_luc(rows: list[dict]) -> tuple[list[dict], dict]:
    """Không gọi LLM — đối chiếu structural dựa trên field đã có sẵn từ Bước 2.

    Sửa 2026-08-26 (lỗ hổng thật phát hiện qua đối chiếu bản tóm tắt của user):
    trước đây CHỈ kiểm tra `validity_change`, để lọt `structural_multihop` — 1 cặp
    Điều tham chiếu chéo (CROSS_REF) có thể có 1 bên ĐÃ HẾT HIỆU LỰC mà không bị
    loại. Giờ dùng `validity_status_at_generation` (đã lưu ở Bước 2 cho MỌI loại)
    để loại `structural_multihop` nếu bất kỳ Điều nguồn nào hết hiệu lực — loại này
    không thiết kế để hỏi về lịch sử nên không có ngoại lệ như `validity_trap`."""
    kept, n_drop = [], 0
    for r in rows:
        if r["type"] == "validity_change":
            m = r.get("meta", {})
            if not (m.get("gia_tri_cu") and m.get("gia_tri_moi")):
                n_drop += 1
                continue
        elif r["type"] in ("structural_multihop", "cross_norm_guidance", "cross_field_multihop"):
            trang_thai = r.get("validity_status_at_generation", [])
            if any(not t.get("con_hieu_luc", True) for t in trang_thai):
                n_drop += 1
                continue
        kept.append(r)
    return kept, {"validity_drop": n_drop}


def cham_bay_hieu_luc(llm, rows: list[dict], workers: int = 8) -> tuple[list[dict], dict]:
    """Riêng cho validity_trap + partial_repeal: đáp án PHẢI có cảnh báo hết hiệu
    lực (partial_repeal thêm vào 2026-09-04 — cùng thất bại mode: đáp án bỏ sót
    cảnh báo phần đã bị bãi bỏ, coi như còn nguyên hiệu lực)."""
    can_cham = [(i, r) for i, r in enumerate(rows) if r["type"] in ("validity_trap", "partial_repeal")]
    if not can_cham:
        return rows, {"bay_checked": 0, "bay_drop": 0}

    def _cham(item):
        i, r = item
        out = llm.chat_json(_SYS, _P_CHAM_BAY_HIEU_LUC.format(a=r["answer"]), temperature=0.0, max_tokens=50)
        return i, bool(out.get("co_canh_bao_het_hieu_luc", False)) if out else True  # loi -> giu lai

    ket_qua = _map_limit(_cham, can_cham, workers)
    drop_idx = {i for i, ok in ket_qua if not ok}
    kept = [r for i, r in enumerate(rows) if i not in drop_idx]
    return kept, {"bay_checked": len(can_cham), "bay_drop": len(drop_idx)}


def quality_gate(llm, rows: list[dict], workers: int = 8) -> tuple[list[dict], dict]:
    """LEVER 1 — chấm answerability 1-5. Loại 'adversarial' KHÔNG bị chấm (đáp án cố
    tình sai theo thiết kế, chấm sẽ luôn thấp — đúng ngoại lệ giữ từ bản gốc)."""
    if not rows:
        return rows, {"gate_checked": 0, "gate_drop": 0}

    def _cham(r):
        ctx = "\n\n---\n\n".join(r["contexts"])
        out = llm.chat_json(_SYS, _P_ANSWERABILITY.format(q=r["question"], c=ctx[:3000], a=r["answer"]),
                            temperature=0.0, max_tokens=30)
        try:
            return int(out.get("diem", 3)) if out else 3
        except Exception:
            return 3

    can_cham = [r for r in rows if r["type"] != "adversarial"]
    diem = _map_limit(_cham, can_cham, workers)
    diem_map = dict(zip((id(r) for r in can_cham), diem))
    kept = [r for r in rows if r["type"] == "adversarial" or diem_map.get(id(r), 3) >= ANSWERABILITY_MIN]
    return kept, {"gate_checked": len(can_cham), "gate_drop": len(rows) - len(kept)}
