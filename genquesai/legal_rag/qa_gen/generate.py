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

from .data import (BangDuLieu, BaiBoTungPhan, Dieu, DieuKhoanChuyenTiep, KichBanLienNganh,
                   toan_van_vb, parent_path, validity_status)
from .prompts import (P_MOT_BUOC, P_CAU_TRUC, P_THAY_DOI_HIEU_LUC, P_GAI_BAY,
                      P_BAY_HIEU_LUC, P_BAI_BO_TUNG_PHAN, P_HUONG_DAN_LIEN_VB,
                      P_CHUYEN_TIEP, P_LIEN_NGANH, breadcrumb)

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


def _gen_bai_bo_tung_phan(llm, item: BaiBoTungPhan) -> dict | None:
    out = llm.chat_json(_SYS, P_BAI_BO_TUNG_PHAN.format(
        breadcrumb_phan=breadcrumb(item.dieu_cha.so_hieu, item.duong_dan),
        ngay_het_hl=item.ngay_het_hl,
        breadcrumb_dieu=breadcrumb(item.dieu_cha.so_hieu, item.dieu_cha.duong_dan),
        ctx_phan=item.text[:2000], ctx_dieu=item.dieu_cha.text[:2500]),
        temperature=0.4, max_tokens=500)
    if not out or "question" not in out or "answer" not in out:
        return None
    return {"question": out["question"], "answer": out["answer"],
           "contexts": [item.text, item.dieu_cha.text],
           "type": "partial_repeal", "source_comp_ids": [item.comp_id, item.dieu_cha.comp_id],
           **_meta_chung(item.dieu_cha),
           "meta": {"phan_bi_bai_bo": item.duong_dan, "ngay_het_hl_phan": str(item.ngay_het_hl)}}


def _gen_huong_dan_lien_vb(llm, bang: BangDuLieu, a: Dieu, norm_b: str, so_hieu_b: str) -> dict | None:
    tv_b = toan_van_vb(bang, norm_b)
    if not tv_b:
        return None
    out = llm.chat_json(_SYS, P_HUONG_DAN_LIEN_VB.format(
        breadcrumb_a=breadcrumb(a.so_hieu, a.duong_dan), ctx_a=a.text[:2000],
        so_hieu_b=so_hieu_b, toan_van_b=tv_b), temperature=0.3, max_tokens=900)
    if not out or not out.get("tim_thay"):
        return None
    needed = {"question", "answer", "doan_b_tim_duoc", "fact_chi_co_a", "fact_chi_co_b", "buoc_1", "buoc_2"}
    if not needed <= out.keys() or not out["doan_b_tim_duoc"]:
        return None
    return {"question": out["question"], "answer": out["answer"],
           "contexts": [a.text, out["doan_b_tim_duoc"]],
           "type": "cross_norm_guidance", "source_comp_ids": [a.comp_id],
           "bridge_relation": "GUIDED_BY", **_meta_chung(a),
           "meta": {"vb_huong_dan": so_hieu_b, "doan_b_tim_duoc": out["doan_b_tim_duoc"],
                    "fact_chi_co_a": out["fact_chi_co_a"], "fact_chi_co_b": out["fact_chi_co_b"],
                    "buoc_1": out["buoc_1"], "buoc_2": out["buoc_2"]}}


def _gen_chuyen_tiep(llm, item: DieuKhoanChuyenTiep) -> dict | None:
    out = llm.chat_json(_SYS, P_CHUYEN_TIEP.format(
        breadcrumb=f"{item.so_hieu} — {item.nguon_dieu_khoan}",
        dieu_kien=item.dieu_kien, van_ban_ap_dung=item.van_ban_ap_dung,
        ctx=item.dieu_kien_raw[:1500]), temperature=0.4, max_tokens=500)
    if not out or "question" not in out or "answer" not in out:
        return None
    return {"question": out["question"], "answer": out["answer"],
           "contexts": [item.dieu_kien_raw],
           "type": "transitional_provision", "source_comp_ids": [item.rule_id],
           "parent_path": [[item.so_hieu, item.nguon_dieu_khoan]],
           "meta": {"dieu_kien": item.dieu_kien, "van_ban_ap_dung": item.van_ban_ap_dung}}


def _ung_vien_lien_nganh(qdrant_store, collection: str, vec, norm_id: str, k: int) -> list:
    """Tìm k Điều gần bối cảnh nhất TRONG 1 norm_id cụ thể (đã lọc còn hiệu lực) —
    dùng chính vector bối cảnh (embed 1 lần/kịch bản), không cần biết trước Điều nào."""
    from qdrant_client import models as qm
    filt = qm.Filter(must=[
        qm.FieldCondition(key="norm_id", match=qm.MatchValue(value=norm_id)),
        qm.FieldCondition(key="part", match=qm.MatchValue(value=0)),
        qm.IsNullCondition(is_null=qm.PayloadField(key="hieu_luc_den")),
    ])
    return qdrant_store.query_points(collection, query=vec, using="dense",
                                     query_filter=filt, limit=k, with_payload=True).points


def _pp_payload(p: dict) -> list[str]:
    dd = (p.get("duong_dan") or "").replace("Dieu", "Điều").replace("Khoan", "Khoản").replace("Diem", "Điểm")
    return [p["so_hieu"]] + [x.strip() for x in dd.split(">")]


def _gen_lien_nganh(llm, qdrant_store, collection: str, embedder, kb: KichBanLienNganh,
                    so_ung_vien: int = 3) -> dict | None:
    """Thử lần lượt các cặp (Điều gần bối cảnh nhất trong luật A) x (...trong luật B),
    dừng ở cặp ĐẦU TIÊN LLM tự nhận thật sự liên quan (P_LIEN_NGANH tự thẩm định trước
    khi viết) — không cần biết trước Điều nào đúng, cũng không cần người duyệt kịch
    bản (kịch bản khớp sai chỉ khiến MỌI cặp đều bị từ chối ở đây, không gây hại)."""
    dense, _ = embedder.encode([kb.boi_canh])
    vec = dense[0].tolist()
    ung_vien_a = _ung_vien_lien_nganh(qdrant_store, collection, vec, kb.norm_a, so_ung_vien)
    ung_vien_b = _ung_vien_lien_nganh(qdrant_store, collection, vec, kb.norm_b, so_ung_vien)
    if not ung_vien_a or not ung_vien_b:
        return None
    for pa_pt in ung_vien_a:
        pa = pa_pt.payload
        for pb_pt in ung_vien_b:
            pb = pb_pt.payload
            out = llm.chat_json(_SYS, P_LIEN_NGANH.format(
                boi_canh=kb.boi_canh, so_hieu_a=pa["so_hieu"], so_hieu_b=pb["so_hieu"],
                breadcrumb_a=breadcrumb(pa["so_hieu"], pa["duong_dan"]), ctx_a=pa["text"][:2000],
                breadcrumb_b=breadcrumb(pb["so_hieu"], pb["duong_dan"]), ctx_b=pb["text"][:2000]),
                temperature=0.4, max_tokens=700)
            if not out or not out.get("lien_quan"):
                continue
            needed = {"question", "answer", "fact_chi_co_a", "fact_chi_co_b", "buoc_1", "buoc_2"}
            if not needed <= out.keys():
                continue
            return {"question": out["question"], "answer": out["answer"],
                   "contexts": [pa["text"], pb["text"]],
                   "type": "cross_field_multihop",
                   "source_comp_ids": [pa["comp_id"], pb["comp_id"]],
                   "bridge_relation": "SCENARIO_SEED",
                   "parent_path": [_pp_payload(pa), _pp_payload(pb)],
                   "validity_status_at_generation": [
                       {"con_hieu_luc": True, "hieu_luc_tu": pa.get("hieu_luc_tu"), "hieu_luc_den": None},
                       {"con_hieu_luc": True, "hieu_luc_tu": pb.get("hieu_luc_tu"), "hieu_luc_den": None}],
                   "meta": {"boi_canh": kb.boi_canh, "fact_chi_co_a": out["fact_chi_co_a"],
                            "fact_chi_co_b": out["fact_chi_co_b"], "buoc_1": out["buoc_1"],
                            "buoc_2": out["buoc_2"]}}
    return None


def _map_limit(fn, items, workers: int) -> list:
    if not items:
        return []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(fn, items))


def sinh_de(llm, bang: BangDuLieu, so_luong: dict[str, int], rng: random.Random,
           workers: int = 8, qdrant_store=None, qdrant_collection: str | None = None,
           embedder=None) -> tuple[list[dict], dict]:
    """`so_luong`: {'mot_buoc':N, 'cau_truc':N, 'hieu_luc':N, 'gai_bay':N, 'bay_hieu_luc':N,
    'bai_bo_tung_phan':N, 'huong_dan_lien_vb':N, 'chuyen_tiep':N, 'lien_nganh':N}.

    `qdrant_store`/`qdrant_collection`/`embedder`: CHỈ cần cho loại `lien_nganh` (cần
    embed trực tiếp bối cảnh — model bge-m3 thật, gói `FlagEmbedding`+`torch`, KHÔNG
    có sẵn trong mọi môi trường chạy pipeline này). Để `None` (mặc định) -> bỏ qua loại
    này êm, không lỗi — các loại khác không bị ảnh hưởng."""
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

    # 6. Bãi bỏ từng phần (Khoan/Diem bi bai bo, Dieu cha van con hieu luc — pool
    # NHO co dinh toan corpus, khac cac loai tren khong scale theo tong_dieu).
    ung_vien_bbtp = list(bang.bai_bo_tung_phan)
    rng.shuffle(ung_vien_bbtp)
    n = min(so_luong.get("bai_bo_tung_phan", 0), len(ung_vien_bbtp))
    chon = ung_vien_bbtp[:n]
    for out in _map_limit(lambda item: _gen_bai_bo_tung_phan(llm, item), chon, workers):
        if out: rows.append(out)
    diag["bai_bo_tung_phan_ok"] = sum(1 for r in rows if r["type"] == "partial_repeal")

    # 7. Multi-hop LIÊN VĂN BẢN (GUIDED_BY): chọn ngẫu nhiên 1 cặp (A được hướng dẫn,
    # B hướng dẫn) rồi 1 Điều ngẫu nhiên của A. Over-provision RẤT MẠNH — đo thực tế
    # 2026-09-04: yield chỉ ~5-8% SAU vòng 1+2 (thấp hơn hẳn hiệu_lực ~25%, vì đây là
    # tìm 1 đoạn cụ thể trong TOÀN VĂN B mà không biết trước B có nhắc Điều A hay
    # không — phần lớn Điều A ngẫu nhiên không được B hướng dẫn cụ thể). Hàm tự biết
    # pass/fail (trả None) nên dùng được pattern "dừng sớm khi đủ".
    dieu_theo_norm: dict[str, list[Dieu]] = {}
    for d in con_hieu_luc_list:
        dieu_theo_norm.setdefault(d.norm_id, []).append(d)
    ung_vien_hdlv = list(bang.huong_dan_lien_vb)
    rng.shuffle(ung_vien_hdlv)
    n_target = so_luong.get("huong_dan_lien_vb", 0)
    over_hdlv = max(1, int(round(n_target * 15)))
    chon_cap = ung_vien_hdlv[:min(over_hdlv, len(ung_vien_hdlv))]
    chon = [(rng.choice(dieu_theo_norm[p.norm_a]), p.norm_b, _so_hieu_cua_norm(p.norm_b))
           for p in chon_cap if p.norm_a in dieu_theo_norm]
    ok = 0
    for out in _map_limit(lambda x: _gen_huong_dan_lien_vb(llm, bang, x[0], x[1], x[2]), chon, workers):
        if out and ok < n_target:
            rows.append(out); ok += 1
    diag["huong_dan_lien_vb_ok"] = ok

    # 8. Điều khoản chuyển tiếp (TransitionRule, pool nhỏ cố định giống bãi_bỏ_từng_phần).
    ung_vien_ct = list(bang.dieu_khoan_chuyen_tiep)
    rng.shuffle(ung_vien_ct)
    n = min(so_luong.get("chuyen_tiep", 0), len(ung_vien_ct))
    chon = ung_vien_ct[:n]
    for out in _map_limit(lambda item: _gen_chuyen_tiep(llm, item), chon, workers):
        if out: rows.append(out)
    diag["chuyen_tiep_ok"] = sum(1 for r in rows if r["type"] == "transitional_provision")

    # 9. Multi-hop LIEN NGANH LUAT (kich ban CO DINH da kiem chung tay, xem
    # data.py::lay_kich_ban_lien_nganh_co_dinh). Bo qua em neu thieu qdrant_store/embedder
    # (moi truong khong co torch+FlagEmbedding) hoac chua co kich ban nao khop duoc.
    if qdrant_store is not None and embedder is not None and bang.kich_ban_lien_nganh:
        ung_vien_kb = list(bang.kich_ban_lien_nganh)
        rng.shuffle(ung_vien_kb)
        n_target = so_luong.get("lien_nganh", 0)
        # Da co retry noi bo (thu het to hop ung vien 2 ben trong _gen_lien_nganh) nen
        # khong can over-provision manh nhu huong_dan_lien_vb — chi can du kich ban.
        over = max(1, int(round(n_target * 3)))
        chon = ung_vien_kb[:min(over, len(ung_vien_kb))]
        ok = 0
        for out in _map_limit(
                lambda kb: _gen_lien_nganh(llm, qdrant_store, qdrant_collection, embedder, kb),
                chon, workers):
            if out and ok < n_target:
                rows.append(out); ok += 1
        diag["lien_nganh_ok"] = ok

    return rows, diag
