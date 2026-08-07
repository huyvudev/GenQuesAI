"""Nạp corpus từ đồ thị kiểu `legal-rag` — loader THỨ NHẤT.

Đây là chỗ toàn bộ hiểu biết riêng về schema Neo4j của `Chatbot-Law` bị nhốt lại. Bộ
sinh phía trên chỉ thấy `framework.schema`, không thấy Cypher.

Ánh xạ:
    Norm            -> Norm
    Component       -> Component  (parent qua HAS_PART)
    Expression      -> Expression
    REPLACES        -> THAY_THE
    GUIDED_BY       -> HUONG_DAN
    Action.loai     -> SUA_DOI · THAY_THE · BAI_BO · CAN_CU   ← xem ghi chú
    TransitionRule  -> DieuKhoanChuyenTiep

Ghi chú về `Action`: quan hệ tác động ở đồ thị này KHÔNG nằm trên cạnh Norm→Norm mà đi
vòng qua node `Action`:  (vb_sua)<-[:ENACTED_BY]-(Action)-[:AFFECTS]->(vb_bi_sua).
`Action.loai = 'CanCu'` là *căn cứ pháp lý*, KHÔNG phải sửa đổi — map sang
`LoaiQuanHe.CAN_CU` để `LoaiQuanHe.tac_dong()` tự loại nó ra.
"""
from __future__ import annotations

import random
from datetime import date
from typing import Iterator

from .schema import (Component, CorpusMeta, DieuKhoanChuyenTiep, Expression,
                     LoaiQuanHe, Norm, QuanHe, _ngay)

Q_NORM = """
MATCH (n:Norm) RETURN n.norm_id AS id, n.so_hieu AS so_hieu, n.loai_vb AS loai_vb,
  n.tieu_de AS tieu_de, n.ngay_ban_hanh AS bh, n.ngay_hieu_luc AS hl,
  n.cap_bac AS cap_bac, n.co_quan_ban_hanh AS cq, n.nguon_url AS url
"""
# WITH DISTINCT: HAS_PART* khớp mọi đường đi và đồ thị không phải cây thuần — không gộp
# thì mỗi Component ra nhiều dòng (đo thật: có Điều 7 đường đi).
Q_COMP = """
MATCH (n:Norm)-[:HAS_PART*]->(c:Component)
WITH DISTINCT n, c
OPTIONAL MATCH (p:Component)-[:HAS_PART]->(c)
RETURN c.comp_id AS id, n.norm_id AS norm_id, c.loai AS loai,
       p.comp_id AS parent, c.so_thu_tu AS stt, c.tieu_de AS tieu_de,
       c.order_key AS thu_tu
"""
Q_EXPR = """
MATCH (c:Component)-[:HAS_VERSION]->(e:Expression)
RETURN e.expr_id AS id, c.comp_id AS comp_id, e.text AS text,
       e.hieu_luc_tu AS tu, e.hieu_luc_den AS den
"""
Q_TT = "MATCH (a:Norm)-[:REPLACES]->(b:Norm) RETURN a.norm_id AS tu, b.norm_id AS den"
Q_HD = "MATCH (a:Norm)-[:GUIDED_BY]->(b:Norm) RETURN a.norm_id AS tu, b.norm_id AS den"
Q_ACT = """
MATCH (act:Action)-[:ENACTED_BY]->(tu:Norm)
MATCH (act)-[:AFFECTS]->(den:Norm)
RETURN tu.norm_id AS tu, den.norm_id AS den, act.loai AS loai,
       act.ngay_hieu_luc AS ngay, act.confidence AS do_tin, act.da_duyet AS duyet
"""
Q_CT = """
MATCH (n:Norm)-[:HAS_TRANSITION]->(t:TransitionRule)
RETURN t.rule_id AS id, n.norm_id AS norm_id, t.dieu_kien AS dk,
       t.van_ban_ap_dung AS ap, t.nguon_dieu_khoan AS nguon,
       t.confidence AS do_tin, t.da_duyet AS duyet
"""
LOAI_ACTION = {"SuaDoi": LoaiQuanHe.SUA_DOI, "ThayThe": LoaiQuanHe.THAY_THE,
               "BaiBo": LoaiQuanHe.BAI_BO, "CanCu": LoaiQuanHe.CAN_CU}
LOAI_COMP = {"Dieu": "Dieu", "Khoan": "Khoan", "Diem": "Diem",
             "PhuLuc": "PhuLuc", "ToanVan": "ToanVan"}


class Neo4jLoader:
    def __init__(self, neo, ten: str = "chatbot-law", gioi_han_norm: int | None = None,
                 seed: int = 20260807):
        self.neo = neo
        self.ten = ten
        self.gh = gioi_han_norm
        self.seed = seed
        self._nhan: set[str] | None = None      # norm_id được giữ khi lấy mẫu

    # Lấy mẫu để xuất bản gọn: corpus đầy có 2,6 triệu Expression.
    def _giu(self, norm_id: str) -> bool:
        return self._nhan is None or norm_id in self._nhan

    def meta(self) -> CorpusMeta:
        ghi_chu = None
        if self.gh:
            ghi_chu = (
                f"MẪU {self.gh:,} văn bản lấy ngẫu nhiên (seed {self.seed}). "
                "Các nhóm dựa trên QUAN HỆ (G1/G3/G4) tụt theo BÌNH PHƯƠNG tỷ lệ mẫu "
                "vì cần cả hai đầu cạnh cùng nằm trong mẫu — đo thật: mẫu 4,5% giữ "
                "lại ~0,2% số cạnh. Đừng đọc báo cáo năng lực của mẫu như của corpus đầy.")
        return CorpusMeta(
            ten=self.ten, ngay_chot=date.today(), ghi_chu=ghi_chu,
            # Đồ thị này ĐÓNG Expression khi văn bản bị thay -> None = còn hiệu lực.
            theo_doi_hieu_luc=True,
            # Quan hệ trích bằng LLM, có `confidence`/`da_duyet` -> bắt buộc lọc.
            quan_he_tu_dong=True,
            nguon="Neo4j legal-rag")

    def norms(self) -> Iterator[Norm]:
        rows = self.neo.run(Q_NORM)
        if self.gh:
            # Lấy NGẪU NHIÊN, không lấy N đầu tiên: `MATCH (n:Norm)` quét theo thứ tự
            # tạo node, nên "3.000 đầu tiên" là lô nạp sớm nhất — và các pass trích
            # xuất (TransitionRule, Action…) thường chạy trên đúng lô đó. Lấy đầu dãy
            # thì báo cáo năng lực LẠC QUAN GIẢ: đo thật, mẫu đầu-dãy 3.000 VB chứa
            # đủ 340/340 văn bản có điều khoản chuyển tiếp của TOÀN corpus 66.368 VB.
            rows = [r for r in rows if r["so_hieu"]]
            random.Random(self.seed).shuffle(rows)
            rows = rows[: self.gh]
            self._nhan = {str(r["id"]) for r in rows}
        for r in rows:
            if not r["so_hieu"]:
                continue
            yield Norm(norm_id=str(r["id"]), so_hieu=r["so_hieu"],
                       so_hieu_tho=r["so_hieu"], loai_vb=r["loai_vb"],
                       tieu_de=r["tieu_de"], ngay_ban_hanh=_ngay(r["bh"]),
                       ngay_hieu_luc=_ngay(r["hl"]), cap_bac=r["cap_bac"],
                       co_quan_ban_hanh=r["cq"], nguon_url=r["url"])

    def components(self) -> Iterator[Component]:
        for r in self.neo.stream(Q_COMP):
            if not self._giu(str(r["norm_id"])):
                continue
            yield Component(component_id=str(r["id"]), norm_id=str(r["norm_id"]),
                            loai=LOAI_COMP.get(r["loai"], "ToanVan"),
                            parent_id=str(r["parent"]) if r["parent"] else None,
                            so_thu_tu=r["stt"], tieu_de=r["tieu_de"],
                            thu_tu=int(r["thu_tu"] or 0))

    def expressions(self) -> Iterator[Expression]:
        giu = self._comp_giu()
        for r in self.neo.stream(Q_EXPR):
            if giu is not None and str(r["comp_id"]) not in giu:
                continue
            yield Expression(expression_id=str(r["id"]),
                             component_id=str(r["comp_id"]), text=r["text"] or "",
                             hieu_luc_tu=_ngay(r["tu"]), hieu_luc_den=_ngay(r["den"]))

    def _comp_giu(self) -> set[str] | None:
        if self._nhan is None:
            return None
        if not hasattr(self, "_cg"):
            self._cg = {str(r["id"]) for r in self.neo.stream(Q_COMP)
                        if self._giu(str(r["norm_id"]))}
        return self._cg

    def quan_he(self) -> Iterator[QuanHe]:
        for q, loai in ((Q_TT, LoaiQuanHe.THAY_THE), (Q_HD, LoaiQuanHe.HUONG_DAN)):
            for r in self.neo.stream(q):
                if self._giu(str(r["tu"])) and self._giu(str(r["den"])):
                    yield QuanHe(loai=loai, tu_norm_id=str(r["tu"]),
                                 den_norm_id=str(r["den"]), da_duyet=True)
        for r in self.neo.stream(Q_ACT):
            loai = LOAI_ACTION.get(r["loai"])
            if not loai or not (self._giu(str(r["tu"])) and self._giu(str(r["den"]))):
                continue
            yield QuanHe(loai=loai, tu_norm_id=str(r["tu"]), den_norm_id=str(r["den"]),
                         ngay_hieu_luc=_ngay(r["ngay"]), do_tin=r["do_tin"],
                         da_duyet=bool(r["duyet"]))

    def chuyen_tiep(self) -> Iterator[DieuKhoanChuyenTiep]:
        for r in self.neo.stream(Q_CT):
            if not self._giu(str(r["norm_id"])):
                continue
            yield DieuKhoanChuyenTiep(
                rule_id=str(r["id"]), norm_id=str(r["norm_id"]),
                dieu_kien=r["dk"] or "", ap_dung=r["ap"] or "",
                nguon_component_id=r["nguon"], do_tin=r["do_tin"],
                da_duyet=bool(r["duyet"]))
