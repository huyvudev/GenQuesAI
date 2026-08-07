"""Nạp/ghi corpus ở dạng JSONL — loader THỨ HAI, và là định dạng trao đổi.

Một thư mục, mỗi thực thể một file:

    corpus/
      meta.json
      norms.jsonl
      components.jsonl
      expressions.jsonl
      quan_he.jsonl
      chuyen_tiep.jsonl   (tuỳ chọn)
      chunks.jsonl        (tuỳ chọn)

Lý do JSONL chứ không phải một file JSON: `expressions.jsonl` của corpus thật có hàng
triệu dòng — phải đọc theo dòng, không nạp cả file vào RAM để parse.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Iterator

from .schema import (Chunk, Component, CorpusMeta, DieuKhoanChuyenTiep, Expression,
                     LoaiQuanHe, Norm, QuanHe, _ngay, sang_dict)


class JsonlLoader:
    def __init__(self, thu_muc: str | Path):
        self.d = Path(thu_muc)
        if not self.d.exists():
            raise FileNotFoundError(f"không thấy thư mục corpus: {self.d}")

    def _dong(self, ten: str) -> Iterator[dict]:
        f = self.d / ten
        if not f.exists():
            return
        with f.open(encoding="utf-8") as fh:
            for i, line in enumerate(fh, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError as e:
                    raise ValueError(f"{ten}:{i} JSON hỏng — {e}") from e

    def meta(self) -> CorpusMeta:
        f = self.d / "meta.json"
        if not f.exists():
            raise FileNotFoundError(
                f"thiếu {f}. Corpus PHẢI khai báo `theo_doi_hieu_luc` — không có nó thì "
                "`hieu_luc_den = null` vừa có thể là 'còn hiệu lực' vừa có thể là "
                "'không biết', hai nghĩa ngược nhau (xem corpus-schema.md §4).")
        r = json.loads(f.read_text(encoding="utf-8"))
        if "theo_doi_hieu_luc" not in r:
            raise ValueError("meta.json thiếu `theo_doi_hieu_luc` — bắt buộc khai báo.")
        return CorpusMeta(
            ten=r.get("ten", self.d.name),
            ngay_chot=_ngay(r.get("ngay_chot")),
            theo_doi_hieu_luc=bool(r["theo_doi_hieu_luc"]),
            quan_he_tu_dong=bool(r.get("quan_he_tu_dong", False)),
            nguon=r.get("nguon"), ghi_chu=r.get("ghi_chu"))

    def norms(self) -> Iterator[Norm]:
        for r in self._dong("norms.jsonl"):
            yield Norm(norm_id=str(r["norm_id"]), so_hieu=r["so_hieu"],
                       so_hieu_tho=r.get("so_hieu_tho"), loai_vb=r.get("loai_vb"),
                       tieu_de=r.get("tieu_de"),
                       ngay_ban_hanh=_ngay(r.get("ngay_ban_hanh")),
                       ngay_hieu_luc=_ngay(r.get("ngay_hieu_luc")),
                       cap_bac=r.get("cap_bac"),
                       co_quan_ban_hanh=r.get("co_quan_ban_hanh"),
                       nguon_url=r.get("nguon_url"))

    def components(self) -> Iterator[Component]:
        for r in self._dong("components.jsonl"):
            yield Component(component_id=str(r["component_id"]),
                            norm_id=str(r["norm_id"]), loai=r["loai"],
                            parent_id=(str(r["parent_id"])
                                       if r.get("parent_id") else None),
                            so_thu_tu=r.get("so_thu_tu"), tieu_de=r.get("tieu_de"),
                            thu_tu=int(r.get("thu_tu", 0)))

    def expressions(self) -> Iterator[Expression]:
        for r in self._dong("expressions.jsonl"):
            yield Expression(expression_id=str(r["expression_id"]),
                             component_id=str(r["component_id"]), text=r["text"],
                             hieu_luc_tu=_ngay(r.get("hieu_luc_tu")),
                             hieu_luc_den=_ngay(r.get("hieu_luc_den")))

    def quan_he(self) -> Iterator[QuanHe]:
        for r in self._dong("quan_he.jsonl"):
            try:
                loai = LoaiQuanHe(r["loai"])
            except ValueError:
                continue          # loại quan hệ lạ -> bỏ, đừng đoán nó nghĩa là gì
            yield QuanHe(loai=loai, tu_norm_id=str(r["tu_norm_id"]),
                         den_norm_id=str(r["den_norm_id"]),
                         ngay_hieu_luc=_ngay(r.get("ngay_hieu_luc")),
                         do_tin=r.get("do_tin"), da_duyet=r.get("da_duyet"),
                         pham_vi=r.get("pham_vi"))

    def chuyen_tiep(self) -> Iterator[DieuKhoanChuyenTiep]:
        for r in self._dong("chuyen_tiep.jsonl"):
            yield DieuKhoanChuyenTiep(
                rule_id=str(r["rule_id"]), norm_id=str(r["norm_id"]),
                dieu_kien=r["dieu_kien"], ap_dung=r["ap_dung"],
                nguon_component_id=r.get("nguon_component_id"),
                do_tin=r.get("do_tin"), da_duyet=r.get("da_duyet"))

    def chunks(self) -> Iterator[Chunk]:
        for r in self._dong("chunks.jsonl"):
            yield Chunk(chunk_id=str(r["chunk_id"]),
                        expression_id=str(r["expression_id"]),
                        part=int(r.get("part", 0)), text=r["text"])


# ── ghi ra ──────────────────────────────────────────────────────────────────
class JsonlWriter:
    """Ghi corpus ra JSONL — dùng để xuất từ nguồn khác sang định dạng trao đổi."""

    def __init__(self, thu_muc: str | Path):
        self.d = Path(thu_muc)
        self.d.mkdir(parents=True, exist_ok=True)
        self._fh: dict[str, object] = {}
        self.dem: dict[str, int] = {}

    def meta(self, m: CorpusMeta) -> None:
        r = {"ten": m.ten, "theo_doi_hieu_luc": m.theo_doi_hieu_luc,
             "quan_he_tu_dong": m.quan_he_tu_dong}
        if m.ngay_chot:
            r["ngay_chot"] = m.ngay_chot.isoformat()
        for k in ("nguon", "ghi_chu"):
            if getattr(m, k):
                r[k] = getattr(m, k)
        (self.d / "meta.json").write_text(
            json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")

    def ghi(self, ten: str, x) -> None:
        fh = self._fh.get(ten)
        if fh is None:
            fh = self._fh[ten] = (self.d / ten).open("w", encoding="utf-8")
        fh.write(json.dumps(sang_dict(x), ensure_ascii=False) + "\n")
        self.dem[ten] = self.dem.get(ten, 0) + 1

    def close(self) -> None:
        for fh in self._fh.values():
            fh.close()
        self._fh.clear()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
