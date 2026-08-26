"""Bước 2 — sinh 5 loại câu hỏi. Dùng ThreadPoolExecutor (LLM client hiện có trong
dự án là đồng bộ, không phải async — theo đúng convention `_trich_cap_dieu.py`).

Sửa bug RNG reseed của bản gốc (proposed.ipynb): `rng` được tạo 1 LẦN DUY NHẤT ở
`run.py` rồi TRUYỀN VÀO đây — không tự tạo `random.Random(seed_cố_định)` mỗi lần
gọi hàm (bug thật đã tìm thấy: sinh bù ở Bước 4 gọi lại đúng hàm này với cùng seed,
tăng rủi ro trùng câu hỏi giữa lượt đầu và lượt bù)."""
from __future__ import annotations
import random
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from .data import BangDuLieu, Dieu, toan_van_vb, parent_path, validity_status
from .prompts import (P_MOT_BUOC, P_CAU_TRUC, P_THAY_DOI_HIEU_LUC, P_GAI_BAY,
                      P_BAY_HIEU_LUC, breadcrumb)

_SYS = "Bạn là chuyên gia ra đề QA cho benchmark RAG pháp luật Việt Nam. Chỉ trả JSON hợp lệ, không giải thích thêm."


def _meta_chung(*dieu_list: Dieu) -> dict:
    """`parent_path`/`validity_status_at_generation` cho MỌI loại câu — field còn
    thiếu trước đây (2026-08-26, phát hiện qua đối chiếu bản tóm tắt của user), theo
    đúng schema Bước 5 trong spec: bộ đề phải tự mô tả đúng phiên bản luật + vị trí
    trong cây văn bản, không chỉ 2 loại liên quan hiệu lực mới có."""
    return {"parent_path": [parent_path(d) for d in dieu_list],
           "validity_status_at_generation": [validity_status(d) for d in dieu_list]}


def _gen_mot_buoc(llm, d: Dieu) -> dict | None:
    out = llm.chat_json(_SYS, P_MOT_BUOC.format(breadcrumb=breadcrumb(d.so_hieu, d.duong_dan),
                                                ctx=d.text[:2500]), temperature=0.4, max_tokens=400)
    if not out or "question" not in out or "answer" not in out:
        return None
    return {"question": out["question"], "answer": out["answer"], "contexts": [d.text],
           "type": "single_hop", "source_comp_ids": [d.comp_id], **_meta_chung(d)}


def _gen_cau_truc(llm, a: Dieu, b: Dieu) -> dict | None:
    out = llm.chat_json(_SYS, P_CAU_TRUC.format(
        breadcrumb_a=breadcrumb(a.so_hieu, a.duong_dan), ctx_a=a.text[:2000],
        breadcrumb_b=breadcrumb(b.so_hieu, b.duong_dan), ctx_b=b.text[:2000]),
        temperature=0.4, max_tokens=700)
    needed = {"question", "answer", "fact_chi_co_a", "fact_chi_co_b", "buoc_1", "buoc_2"}
    if not out or not needed <= out.keys():
        return None
    return {"question": out["question"], "answer": out["answer"], "contexts": [a.text, b.text],
           "type": "structural_multihop", "source_comp_ids": [a.comp_id, b.comp_id],
           "bridge_relation": "CROSS_REF", **_meta_chung(a, b),
           "meta": {k: out[k] for k in ("fact_chi_co_a", "fact_chi_co_b", "buoc_1", "buoc_2")}}


def _gen_hieu_luc(llm, bang: BangDuLieu, cu: Dieu, src_norm_id: str, so_hieu_nguon: str,
                  ngay_hl_moi) -> dict | None:
    tv = toan_van_vb(bang, src_norm_id)
    if not tv:
        return None
    out = llm.chat_json(_SYS, P_THAY_DOI_HIEU_LUC.format(
        ngay_het_hl=cu.hieu_luc_den, so_hieu_nguon=so_hieu_nguon,
        breadcrumb_cu=breadcrumb(cu.so_hieu, cu.duong_dan), ctx_cu=cu.text[:2500],
        toan_van_nguon=tv), temperature=0.3, max_tokens=800)
    if not out or not out.get("tim_thay"):
        return None
    needed = {"question", "answer", "gia_tri_cu", "gia_tri_moi"}
    if not needed <= out.keys() or not out["gia_tri_moi"]:
        return None
    return {"question": out["question"], "answer": out["answer"],
           "contexts": [cu.text, out["gia_tri_moi"]],
           "type": "validity_change", "source_comp_ids": [cu.comp_id],
           "bridge_relation": "AMENDS_OR_REPLACES", **_meta_chung(cu),
           "meta": {"gia_tri_cu": out["gia_tri_cu"], "gia_tri_moi": out["gia_tri_moi"],
                    "ngay_het_hl_cu": str(cu.hieu_luc_den), "ngay_hieu_luc_moi": str(ngay_hl_moi),
                    "vb_nguon": so_hieu_nguon}}


def _gen_gai_bay(llm, d: Dieu) -> dict | None:
    out = llm.chat_json(_SYS, P_GAI_BAY.format(breadcrumb=breadcrumb(d.so_hieu, d.duong_dan),
                                               ctx=d.text[:2500]), temperature=0.5, max_tokens=400)
    needed = {"question", "answer", "gia_tri_goc", "gia_tri_doi"}
    if not out or not needed <= out.keys():
        return None
    gtg, gtd = str(out["gia_tri_goc"]).strip(), str(out["gia_tri_doi"]).strip()
    if not gtg or not gtd or gtg.lower() == gtd.lower():
        return None
    if gtg.lower() not in d.text.lower():
        return None  # gia_tri_goc phai co that trong ngu canh
    if gtd.lower() in d.text.lower():
        return None  # gia_tri_doi khong duoc trung/la substring cua ngu canh
    return {"question": out["question"], "answer": out["answer"], "contexts": [d.text],
           "type": "adversarial", "source_comp_ids": [d.comp_id], **_meta_chung(d),
           "meta": {"gia_tri_goc": gtg, "gia_tri_doi": gtd}}


def _gen_bay_hieu_luc(llm, cu: Dieu) -> dict | None:
    out = llm.chat_json(_SYS, P_BAY_HIEU_LUC.format(
        ngay_het_hl=cu.hieu_luc_den, breadcrumb=breadcrumb(cu.so_hieu, cu.duong_dan),
        ctx=cu.text[:2500]), temperature=0.4, max_tokens=500)
    if not out or "question" not in out or "answer" not in out:
        return None
    return {"question": out["question"], "answer": out["answer"], "contexts": [cu.text],
           "type": "validity_trap", "source_comp_ids": [cu.comp_id], **_meta_chung(cu),
           "meta": {"ngay_het_hl": str(cu.hieu_luc_den)}}


def _map_limit(fn, items, workers: int) -> list:
    if not items:
        return []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(fn, items))


def sinh_de(llm, bang: BangDuLieu, so_luong: dict[str, int], rng: random.Random,
           workers: int = 8) -> tuple[list[dict], dict]:
    """`so_luong`: {'mot_buoc':N, 'cau_truc':N, 'hieu_luc':N, 'gai_bay':N, 'bay_hieu_luc':N}."""
    rows: list[dict] = []
    diag: dict[str, int] = {}
    dieu_list = list(bang.dieu.values())
    con_hieu_luc_list = [d for d in dieu_list if d.con_hieu_luc]

    # 1. Một bước
    n = min(so_luong.get("mot_buoc", 0), len(con_hieu_luc_list))
    chon = rng.sample(con_hieu_luc_list, n) if n else []
    for out in _map_limit(lambda d: _gen_mot_buoc(llm, d), chon, workers):
        if out: rows.append(out)
    diag["mot_buoc_ok"] = sum(1 for r in rows if r["type"] == "single_hop")

    # 2. Nhiều bước — cấu trúc (tu CROSS_REF that). Sinh dư ~2.5x mục tiêu (do_luong
    # thuc te 2026-08-26: ~50% bi loai o vong omission-test Buoc 3, xay ra SAU ham
    # nay nen khong tu phat hien duoc tai day — khac gai_bay tu kiem tra ngay).
    cap_cau_truc = [(bang.dieu[t.src_comp_id], bang.dieu[t.tgt_comp_id])
                    for t in bang.tham_chieu_noi_bo]
    rng.shuffle(cap_cau_truc)
    over_ct = max(1, int(round(so_luong.get("cau_truc", 0) * 2.5)))
    chon = cap_cau_truc[:min(over_ct, len(cap_cau_truc))]
    for out in _map_limit(lambda ab: _gen_cau_truc(llm, ab[0], ab[1]), chon, workers):
        if out: rows.append(out)
    diag["cau_truc_ok"] = sum(1 for r in rows if r["type"] == "structural_multihop")

    # 3. Thay đổi hiệu lực (tu REPLACES/AMENDS da duyet, dich la Component cu the).
    # Can bo sung so_hieu cua src_norm_id de dua vao prompt — tra tu chinh bang.dieu
    # (moi VB co it nhat 1 Dieu trong bang, tat ca deu chung 1 so_hieu).
    def _so_hieu_cua_norm(norm_id: str) -> str | None:
        for d in bang.dieu.values():
            if d.norm_id == norm_id:
                return d.so_hieu
        return None

    ung_vien_hieu_luc = [
        (bang.dieu[qh.tgt_comp_id], qh.src_norm_id, _so_hieu_cua_norm(qh.src_norm_id), qh.ngay_hieu_luc)
        for qh in bang.quan_he_hieu_luc if bang.dieu[qh.tgt_comp_id].hieu_luc_den is not None
    ]
    ung_vien_hieu_luc = [x for x in ung_vien_hieu_luc if x[2]]
    rng.shuffle(ung_vien_hieu_luc)
    # Sinh dư ~4.5x mục tiêu — do_luong thuc te 2026-08-26: yield chi ~25% (LLM tu
    # choi "tim_thay:false" khi khong khop dung chu de, dung y muon — xem generate.py
    # docstring _gen_hieu_luc / QuanHeHieuLuc). Ham nay tu biet pass/fail (tra None)
    # nen dung duoc pattern "dung som khi du" giong gai_bay.
    n_target = so_luong.get("hieu_luc", 0)
    over_hl = max(1, int(round(n_target * 4.5)))
    chon = ung_vien_hieu_luc[:min(over_hl, len(ung_vien_hieu_luc))]
    ok = 0
    for out in _map_limit(lambda cmn: _gen_hieu_luc(llm, bang, cmn[0], cmn[1], cmn[2], cmn[3]), chon, workers):
        if out and ok < n_target:
            rows.append(out); ok += 1
    diag["hieu_luc_ok"] = ok

    # 4. Gài bẫy (over-provision 1.6x vi bi loai kha nhieu qua rule-check)
    n_target = so_luong.get("gai_bay", 0)
    over = max(1, int(round(n_target * 1.6)))
    chon = rng.sample(con_hieu_luc_list, min(over, len(con_hieu_luc_list))) if over else []
    ok = 0
    for out in _map_limit(lambda d: _gen_gai_bay(llm, d), chon, workers):
        if out and ok < n_target:
            rows.append(out); ok += 1
    diag["gai_bay_ok"] = ok

    # 5. Bẫy hiệu lực (Dieu da het hieu luc, co Dieu thay the con hieu luc)
    da_het_hl_co_thay_the = [bang.dieu[qh.tgt_comp_id] for qh in bang.quan_he_hieu_luc
                             if bang.dieu[qh.tgt_comp_id].hieu_luc_den is not None]
    rng.shuffle(da_het_hl_co_thay_the)
    n = min(so_luong.get("bay_hieu_luc", 0), len(da_het_hl_co_thay_the))
    chon = da_het_hl_co_thay_the[:n]
    for out in _map_limit(lambda d: _gen_bay_hieu_luc(llm, d), chon, workers):
        if out: rows.append(out)
    diag["bay_hieu_luc_ok"] = sum(1 for r in rows if r["type"] == "validity_trap")

    return rows, diag
