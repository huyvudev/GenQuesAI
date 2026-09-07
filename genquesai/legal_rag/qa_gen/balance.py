"""Bước 4 — cân bằng tỉ lệ (TVD), mở rộng từ 3 sang 5 loại. Cơ chế giữ nguyên ý
tưởng bản gốc (proposed.ipynb), CHỈ khác: `rng` dùng CHUNG 1 instance xuyên suốt cả
lượt đầu lẫn lượt sinh bù (sửa bug reseed — xem `generate.py`)."""
from __future__ import annotations
import random

from .data import BangDuLieu, KeHoach
from .generate import sinh_de
from .verify import vong_1_omission, vong_2_hieu_luc, cham_bay_hieu_luc

_LOAI_KEY = {
    "single_hop": "mot_buoc", "structural_multihop": "cau_truc",
    "validity_change": "hieu_luc", "adversarial": "gai_bay", "validity_trap": "bay_hieu_luc",
    "partial_repeal": "bai_bo_tung_phan", "cross_norm_guidance": "huong_dan_lien_vb",
    "transitional_provision": "chuyen_tiep", "cross_field_multihop": "lien_nganh",
}

TVD_ACCEPT = 0.08
MAX_BALANCE_ITER = 2


def tvd(p: dict, q: dict) -> float:
    keys = set(p) | set(q)
    return 0.5 * sum(abs(p.get(k, 0) - q.get(k, 0)) for k in keys)


def phan_phoi_thuc_te(rows: list[dict]) -> dict:
    if not rows:
        return {}
    dem: dict[str, int] = {}
    for r in rows:
        dem[r["type"]] = dem.get(r["type"], 0) + 1
    tong = len(rows)
    return {k: v / tong for k, v in dem.items()}


def _cham_1_vong(llm_verify, rows: list[dict], workers: int) -> list[dict]:
    """`llm_verify`: model CHẤM (kiểm tra chéo, có thể khác model đã sinh — xem
    thảo luận 2026-09-05, config.py::verify_llm_*)."""
    rows, _ = vong_1_omission(llm_verify, rows, workers)
    rows, _ = vong_2_hieu_luc(rows)
    rows, _ = cham_bay_hieu_luc(llm_verify, rows, workers)
    return rows


def can_bang(llm, bang: BangDuLieu, ke_hoach: KeHoach, rows_ban_dau: list[dict],
            tong_muc_tieu: int, rng: random.Random, workers: int = 8,
            qdrant_store=None, qdrant_collection: str | None = None, embedder=None,
            llm_verify=None) -> tuple[list[dict], list[dict]]:
    """`llm`: model SINH (dùng cho lượt sinh bù). `llm_verify`: model CHẤM lượt bù
    (mặc định = `llm` nếu để None — xem qa_gen/run.py cách dựng model thứ 2)."""
    llm_verify = llm_verify or llm
    target = {
        "single_hop": ke_hoach.ty_le_mot_buoc, "structural_multihop": ke_hoach.ty_le_cau_truc,
        "validity_change": ke_hoach.ty_le_hieu_luc, "adversarial": ke_hoach.ty_le_gai_bay,
        "validity_trap": ke_hoach.ty_le_bay_hieu_luc,
        "partial_repeal": ke_hoach.ty_le_bai_bo_tung_phan,
        "cross_norm_guidance": ke_hoach.ty_le_huong_dan_lien_vb,
        "transitional_provision": ke_hoach.ty_le_chuyen_tiep,
        "cross_field_multihop": ke_hoach.ty_le_lien_nganh,
    }
    rows = list(rows_ban_dau)
    history = []
    for it in range(MAX_BALANCE_ITER):
        q = phan_phoi_thuc_te(rows)
        d = tvd(target, q)
        history.append({"iter": it, "tvd": d, **q})
        if d <= TVD_ACCEPT:
            break
        actual = {k: 0 for k in target}
        for r in rows:
            actual[r["type"]] = actual.get(r["type"], 0) + 1
        wanted = {t: int(round(target[t] * tong_muc_tieu)) for t in target}
        thieu = {t: max(0, wanted[t] - actual.get(t, 0)) for t in target}
        tong_thieu = sum(thieu.values())
        if tong_thieu == 0:
            break
        so_luong_bu = {_LOAI_KEY[t]: n for t, n in thieu.items()}
        bu_rows, _ = sinh_de(llm, bang, so_luong_bu, rng, workers,
                             qdrant_store=qdrant_store, qdrant_collection=qdrant_collection,
                             embedder=embedder)
        bu_rows = _cham_1_vong(llm_verify, bu_rows, workers)
        if len(bu_rows) < tong_thieu * 0.10:
            rows += bu_rows
            break
        rows += bu_rows
    return rows, history
