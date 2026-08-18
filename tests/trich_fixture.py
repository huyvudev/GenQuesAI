"""Xuất subgraph CÓ ĐÍCH từ Neo4j — corpus offline để replay `ky_vong.jsonl`.

    python -m tests.trich_fixture                 # cần Neo4j :7687 đang chạy
    python -m tests.trich_fixture --ra /tmp/fx

Vì sao không dùng `out/corpus/`
───────────────────────────────
`out/corpus/` là mẫu **3.000 văn bản ngẫu nhiên**. Đo thật: nó giao đúng **19/438**
văn bản mà bộ đề nhắc tới. Replay trên đó thì 96% kỳ vọng bị skip và bảng kết quả
báo xanh — loại xanh tệ hơn đỏ, vì nó trông như đã kiểm.

Fixture này đi ngược lại: đọc `ky_vong.jsonl` trước, rồi lấy đúng những gì các kỳ vọng
đó cần, không hơn.

Bốn tập, mỗi tập một lý do
──────────────────────────
`norm_hat`      văn bản được kỳ vọng nhắc tên.
`norm_lang_gieng` mọi văn bản ở ĐẦU KIA của cạnh trỏ vào `norm_hat`. Bắt buộc, vì
                nhiều kỳ vọng là **đẳng thức tập hợp** (`tac_dong_toi` phải ĐÚNG BẰNG
                danh sách này). Thiếu láng giềng thì tập bị cắt cụt và test **pass
                nhầm** — corpus nghèo đi làm đáp án co lại vừa khít.
`norm_cay_day`  văn bản cần TRỌN cây thành phần: nhóm G7 (Điều nào là hiện hành) và
                G8(b) (số Điều lớn nhất). Chỉ ~96 văn bản nên xuất trọn được.
`expr_can`      expression được trích dẫn, kèm MỌI bản khác của cùng Component —
                không có đủ các bản thì `hieu_luc_tai()` không có gì để chọn sai, và
                phép kiểm nửa mở `[tu, den)` mất ý nghĩa.

Kỳ vọng PHỦ ĐỊNH phải chốt lúc xuất
───────────────────────────────────
`khong_co_norm` (G8a: "số hiệu này không tồn tại") KHÔNG replay được trên tập con —
trên corpus nghèo thì cái gì cũng không tồn tại, test xanh mà chẳng kiểm gì. Nên nó
được đối chiếu **với đồ thị đầy đủ ngay tại đây**, và phán quyết ghi vào
`pham_vi.json` để commit kèm. Đó là cách duy nhất khiến nó có giá trị.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

GOC = Path(__file__).resolve().parent.parent
if str(GOC) not in sys.path:
    sys.path.insert(0, str(GOC))

from framework.jsonl_loader import JsonlWriter                       # noqa: E402
from framework.neo4j_loader import LOAI_COMP                         # noqa: E402
from framework.schema import (Component, CorpusMeta, DieuKhoanChuyenTiep,  # noqa: E402
                              Expression, LoaiQuanHe, NguonQuanHe, Norm, QuanHe,
                              _ngay)

KY_VONG = GOC / "tests" / "golden" / "ky_vong.jsonl"
MAC_DINH_RA = GOC / "tests" / "golden" / "fixture"

# Sự kiện nào cần trọn cây thành phần của văn bản
CAN_CAY_DAY = {"dieu_hien_hanh", "so_dieu_lon_nhat", "so_dieu_khong_co"}
# Đủ dài để phủ phép đối chiếu 120 ký tự đầu của `test_su_kien`, cộng biên an toàn.
MAX_TEXT = 600
CAT_DUOI = "…[cắt cho fixture]"
# Sự kiện nào tra văn bản bằng số hiệu chứ không bằng norm_id
TRA_BANG_SO_HIEU = {"khong_co_norm", "so_dieu_lon_nhat", "so_dieu_khong_co",
                    "nam_ban_hanh"}

Q_NORM = """
UNWIND $ids AS nid
MATCH (n:Norm {norm_id: nid})
RETURN n.norm_id AS id, n.so_hieu AS so_hieu, n.loai_vb AS loai_vb,
       n.tieu_de AS tieu_de, n.ngay_ban_hanh AS bh, n.ngay_hieu_luc AS hl,
       n.cap_bac AS cap_bac, n.co_quan_ban_hanh AS cq, n.nguon_url AS url
"""
Q_THEO_SO_HIEU = """
UNWIND $shs AS sh
MATCH (n:Norm) WHERE n.so_hieu = sh
RETURN sh AS hoi, n.norm_id AS id
"""
# Mọi cạnh có MỘT đầu nằm trong tập hạt — cả hai chiều. Một chiều thôi là đủ hỏng:
# `tac_dong_toi` cần cạnh ĐI VÀO, `da_thay_the` cần cạnh ĐI RA.
Q_CANH = """
UNWIND $ids AS nid
MATCH (a:Norm)-[r:REPLACES|GUIDED_BY]->(b:Norm)
WHERE a.norm_id = nid OR b.norm_id = nid
RETURN DISTINCT a.norm_id AS tu, b.norm_id AS den, type(r) AS loai
"""
Q_ACTION = """
UNWIND $ids AS nid
MATCH (act:Action)-[:ENACTED_BY]->(tu:Norm)
MATCH (act)-[:AFFECTS]->(den:Norm)
WHERE tu.norm_id = nid OR den.norm_id = nid
RETURN DISTINCT tu.norm_id AS tu, den.norm_id AS den, act.loai AS loai,
       act.ngay_hieu_luc AS ngay, act.confidence AS do_tin, act.da_duyet AS duyet
"""
Q_CAY = """
UNWIND $ids AS nid
MATCH (n:Norm {norm_id: nid})-[:HAS_PART*]->(c:Component)
WITH DISTINCT n, c
OPTIONAL MATCH (p:Component)-[:HAS_PART]->(c)
RETURN c.comp_id AS id, n.norm_id AS norm_id, c.loai AS loai,
       p.comp_id AS parent, c.so_thu_tu AS stt, c.tieu_de AS tieu_de,
       c.order_key AS thu_tu
"""
# Từ expr_id ngược về Component rồi lấy MỌI bản của Component đó.
Q_EXPR_QUANH = """
UNWIND $exprs AS eid
MATCH (c:Component)-[:HAS_VERSION]->(:Expression {expr_id: eid})
WITH DISTINCT c
MATCH (c)-[:HAS_VERSION]->(e:Expression)
RETURN DISTINCT e.expr_id AS id, c.comp_id AS comp_id, e.text AS text,
       e.hieu_luc_tu AS tu, e.hieu_luc_den AS den
"""
Q_COMP_CUA_EXPR = """
UNWIND $exprs AS eid
MATCH (n:Norm)-[:HAS_PART*]->(c:Component)-[:HAS_VERSION]->(:Expression {expr_id: eid})
WITH DISTINCT n, c
OPTIONAL MATCH (p:Component)-[:HAS_PART]->(c)
RETURN c.comp_id AS id, n.norm_id AS norm_id, c.loai AS loai,
       p.comp_id AS parent, c.so_thu_tu AS stt, c.tieu_de AS tieu_de,
       c.order_key AS thu_tu
"""
Q_EXPR_CUA_CAY = """
UNWIND $ids AS cid
MATCH (:Component {comp_id: cid})-[:HAS_VERSION]->(e:Expression)
RETURN DISTINCT e.expr_id AS id, cid AS comp_id, e.text AS text,
       e.hieu_luc_tu AS tu, e.hieu_luc_den AS den
"""
Q_CT = """
UNWIND $ids AS nid
MATCH (n:Norm {norm_id: nid})-[:HAS_TRANSITION]->(t:TransitionRule)
RETURN t.rule_id AS id, n.norm_id AS norm_id, t.dieu_kien AS dk,
       t.van_ban_ap_dung AS ap, t.nguon_dieu_khoan AS nguon,
       t.confidence AS do_tin, t.da_duyet AS duyet
"""
Q_DEM_SO_HIEU = """
UNWIND $shs AS sh
MATCH (n:Norm) WHERE n.so_hieu CONTAINS sh
RETURN sh AS hoi, count(n) AS c
"""
LOAI_CANH = {"REPLACES": LoaiQuanHe.THAY_THE, "GUIDED_BY": LoaiQuanHe.HUONG_DAN}
LOAI_ACTION = {"SuaDoi": LoaiQuanHe.SUA_DOI, "ThayThe": LoaiQuanHe.THAY_THE,
               "BaiBo": LoaiQuanHe.BAI_BO, "CanCu": LoaiQuanHe.CAN_CU}


def gom_muc_tieu(ky_vong: list[dict]) -> dict[str, set]:
    """Đi qua mọi sự kiện, gom những gì cần lấy. Không đoán — chỉ lấy cái được nhắc."""
    ra = {"norm_hat": set(), "norm_cay_day": set(), "expr": set(),
          "so_hieu": set(), "so_hieu_phai_vang": set(), "norm_chuyen_tiep": set()}
    for item in ky_vong:
        for s in item["su_kien"]:
            loai = s["loai"]
            for k in ("norm", "con", "me"):
                if s.get(k):
                    ra["norm_hat"].add(s[k])
            for k in ("ky_vong", "ky_vong_chua", "ky_vong_ids"):
                # `ky_vong` là DANH SÁCH norm_id ở `thay_the_boi`, nhưng là một SỐ
                # NGUYÊN ở `so_dieu_lon_nhat`. Cùng tên khoá, hai kiểu — kiểm kiểu ở
                # đây thay vì tin vào tên.
                if isinstance(s.get(k), list):
                    ra["norm_hat"].update(x for x in s[k] if x)
            if s.get("expr"):
                ra["expr"].add(s["expr"])
            if loai in CAN_CAY_DAY and s.get("norm"):
                ra["norm_cay_day"].add(s["norm"])
            if loai in TRA_BANG_SO_HIEU and s.get("so_hieu"):
                ra["so_hieu"].add(s["so_hieu"])
            if loai == "khong_co_norm":
                ra["so_hieu_phai_vang"].add(s["so_hieu"])
            if loai == "chuyen_tiep" and s.get("norm"):
                ra["norm_chuyen_tiep"].add(s["norm"])
    return ra


def xuat(neo, ra_dir: Path, ky_vong: list[dict]) -> dict:
    mt = gom_muc_tieu(ky_vong)

    # so_hieu -> norm_id (G8 b/c chỉ có số hiệu, không có norm_id trong bộ đề)
    theo_sh: dict[str, list[str]] = {}
    if mt["so_hieu"]:
        for r in neo.run(Q_THEO_SO_HIEU, shs=sorted(mt["so_hieu"])):
            theo_sh.setdefault(r["hoi"], []).append(str(r["id"]))
    for ids in theo_sh.values():
        mt["norm_hat"].update(ids)
        mt["norm_cay_day"].update(ids)

    hat = sorted(mt["norm_hat"])

    # ── quan hệ: lấy TRƯỚC để biết cần thêm văn bản láng giềng nào ──
    canh: list[QuanHe] = []
    lang_gieng: set[str] = set()
    for r in neo.run(Q_CANH, ids=hat):
        canh.append(QuanHe(loai=LOAI_CANH[r["loai"]], tu_norm_id=str(r["tu"]),
                           den_norm_id=str(r["den"]), da_duyet=True,
                           nguon=NguonQuanHe.CANH))
        lang_gieng.update((str(r["tu"]), str(r["den"])))
    for r in neo.run(Q_ACTION, ids=hat):
        if (loai := LOAI_ACTION.get(r["loai"])) is None:
            continue
        canh.append(QuanHe(loai=loai, tu_norm_id=str(r["tu"]), den_norm_id=str(r["den"]),
                           ngay_hieu_luc=_ngay(r["ngay"]), do_tin=r["do_tin"],
                           da_duyet=bool(r["duyet"]), nguon=NguonQuanHe.TU_DONG))
        lang_gieng.update((str(r["tu"]), str(r["den"])))

    tat_ca_norm = sorted(set(hat) | lang_gieng)
    norms = [Norm(norm_id=str(r["id"]), so_hieu=r["so_hieu"], so_hieu_tho=r["so_hieu"],
                  loai_vb=r["loai_vb"], tieu_de=r["tieu_de"],
                  ngay_ban_hanh=_ngay(r["bh"]), ngay_hieu_luc=_ngay(r["hl"]),
                  cap_bac=r["cap_bac"], co_quan_ban_hanh=r["cq"], nguon_url=r["url"])
             for r in neo.run(Q_NORM, ids=tat_ca_norm)]
    co_norm = {n.norm_id for n in norms}
    # Cạnh có đầu nào không xuất được thì bỏ: `Corpus` giữ cạnh trỏ vào hư vô sẽ làm
    # đẳng thức tập hợp lệch mà không đọc ra nguyên nhân.
    canh = [q for q in canh if q.tu_norm_id in co_norm and q.den_norm_id in co_norm]

    # ── thành phần ──
    def _comp(r) -> Component:
        return Component(component_id=str(r["id"]), norm_id=str(r["norm_id"]),
                         loai=LOAI_COMP.get(r["loai"], "ToanVan"),
                         parent_id=str(r["parent"]) if r["parent"] else None,
                         so_thu_tu=r["stt"], tieu_de=r["tieu_de"],
                         thu_tu=int(r["thu_tu"] or 0))

    comps: dict[str, Component] = {}
    cay = sorted(mt["norm_cay_day"] & co_norm)
    if cay:
        for r in neo.run(Q_CAY, ids=cay):
            comps[str(r["id"])] = _comp(r)
    exprs_can = sorted(mt["expr"])
    if exprs_can:
        for r in neo.run(Q_COMP_CUA_EXPR, exprs=exprs_can):
            comps[str(r["id"])] = _comp(r)

    # ── nội dung ──
    def _expr(r) -> Expression:
        return Expression(expression_id=str(r["id"]), component_id=str(r["comp_id"]),
                          text=r["text"] or "", hieu_luc_tu=_ngay(r["tu"]),
                          hieu_luc_den=_ngay(r["den"]))

    exprs: dict[str, Expression] = {}
    if exprs_can:
        # MỌI bản của Component chứ không chỉ bản được trích: thiếu các bản khác thì
        # `hieu_luc_tai()` không có gì để chọn sai và phép kiểm nửa mở thành vô nghĩa.
        for r in neo.run(Q_EXPR_QUANH, exprs=exprs_can):
            exprs[str(r["id"])] = _expr(r)
    if comps:
        for r in neo.run(Q_EXPR_CUA_CAY, ids=sorted(comps)):
            exprs.setdefault(str(r["id"]), _expr(r))
    exprs = {k: v for k, v in exprs.items() if v.component_id in comps}

    # Cắt bớt text để fixture commit được. Kỳ vọng golden chỉ đối chiếu ĐẦU đoạn trích
    # (120 ký tự đầu, xem `test_su_kien`), nên phần đuôi không phục vụ phép kiểm nào —
    # nhưng nó chiếm 12/19 MB. Giữ nguyên khi ngắn để mọi kỳ vọng hiện có vẫn kiểm được.
    # Đây là ĐÁNH ĐỔI CÓ Ý THỨC: fixture commit được thì golden chạy offline trên máy
    # trắng; không commit được thì chỉ máy có Neo4j mới chạy nổi — đúng thứ A3 vừa gỡ.
    for e in exprs.values():
        if len(e.text) > MAX_TEXT:
            e.text = e.text[:MAX_TEXT] + CAT_DUOI

    ct = [DieuKhoanChuyenTiep(rule_id=str(r["id"]), norm_id=str(r["norm_id"]),
                              dieu_kien=r["dk"] or "", ap_dung=r["ap"] or "",
                              nguon_component_id=r["nguon"], do_tin=r["do_tin"],
                              da_duyet=bool(r["duyet"]))
          for r in neo.run(Q_CT, ids=sorted(mt["norm_chuyen_tiep"] & co_norm))] \
        if mt["norm_chuyen_tiep"] else []

    # ── kỳ vọng phủ định: chốt NGAY, trên đồ thị đầy đủ ──
    vang: dict[str, bool] = {}
    if mt["so_hieu_phai_vang"]:
        for r in neo.run(Q_DEM_SO_HIEU, shs=sorted(mt["so_hieu_phai_vang"])):
            vang[r["hoi"]] = (r["c"] == 0)
        for sh in mt["so_hieu_phai_vang"]:
            vang.setdefault(sh, True)          # không có dòng trả về = đếm 0

    # ── ghi ──
    ra_dir.mkdir(parents=True, exist_ok=True)
    with JsonlWriter(ra_dir) as w:
        w.meta(CorpusMeta(
            ten="fixture-golden-a1", theo_doi_hieu_luc=True, quan_he_tu_dong=True,
            nguon="Neo4j legal-rag (subgraph có đích)",
            ghi_chu="TẬP CON có chủ đích, dựng từ tests/golden/ky_vong.jsonl. KHÔNG "
                    "phải mẫu đại diện — đừng chạy báo cáo năng lực trên nó. Kỳ vọng "
                    "phủ định đã chốt lúc xuất, xem pham_vi.json."))
        for ten, ds in (("norms.jsonl", norms), ("components.jsonl", comps.values()),
                        ("expressions.jsonl", exprs.values()), ("quan_he.jsonl", canh),
                        ("chuyen_tiep.jsonl", ct)):
            for x in ds:
                w.ghi(ten, x)

    # Thực thể kỳ vọng nhắc tới mà ĐỒ THỊ NGUỒN không có. Phân biệt hai chuyện khác
    # hẳn nhau, và trộn chúng là mất cả hai tín hiệu:
    #   bộ xuất gom sót      -> LỖI của tests/trich_fixture.py, phải đỏ
    #   nguồn vốn không có   -> bộ đề lệch phiên bản với đồ thị, không kiểm được
    # Chốt ngay tại đây vì chỉ lúc này mới còn đồ thị trong tay.
    thieu_norm = sorted(set(hat) - co_norm)
    thieu_expr = sorted(set(exprs_can) - set(exprs))
    tk = {"norm": len(norms), "norm_hat": len(hat), "component": len(comps),
          "expression": len(exprs), "quan_he": len(canh), "chuyen_tiep": len(ct),
          "so_hieu_khong_tim_thay": sorted(mt["so_hieu"] - set(theo_sh)),
          "nguon_khong_co_norm": len(thieu_norm),
          "nguon_khong_co_expr": len(thieu_expr),
          "phu_dinh_da_chot": vang}
    (ra_dir / "pham_vi.json").write_text(
        json.dumps({"day_du": False, "phu_dinh": vang,
                    "nguon_khong_co": {"norm": thieu_norm, "expr": thieu_expr,
                                       "so_hieu": sorted(mt["so_hieu"] - set(theo_sh))},
                    "thong_ke": tk},
                   ensure_ascii=False, indent=1), encoding="utf-8")
    return tk


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ky-vong", type=Path, default=KY_VONG)
    ap.add_argument("--ra", type=Path, default=MAC_DINH_RA)
    a = ap.parse_args()

    if not a.ky_vong.exists():
        print(f"thiếu {a.ky_vong} — chạy trước: python -m tests.trich_ky_vong")
        return 1
    ky_vong = [json.loads(x) for x in
               a.ky_vong.read_text(encoding="utf-8").splitlines() if x.strip()][1:]

    from generator.common import open_neo4j, setup_stdout
    setup_stdout()
    neo = open_neo4j()
    try:
        tk = xuat(neo, a.ra, ky_vong)
    finally:
        neo.close()

    co = sum(f.stat().st_size for f in a.ra.glob("*") if f.is_file())
    print(f"fixture -> {a.ra}   ({co / 1e6:.1f} MB)")
    if co > 15e6:
        # Fixture nên COMMIT được: đó là toàn bộ lý do nó tồn tại (replay offline,
        # máy trắng, không Neo4j). Quá to thì thu hẹp `norm_cay_day` chứ đừng bỏ
        # commit — bỏ commit là quay lại chỗ chỉ máy có Neo4j mới chạy được golden.
        print("  ⚠️  >15 MB. Cân nhắc thu hẹp tập cần trọn cây trước khi commit.")
    for k, v in tk.items():
        if isinstance(v, dict):
            xau = [s for s, ok in v.items() if not ok]
            print(f"  {k:24} {len(v)} chốt" + (f"  ⚠️  SAI: {xau}" if xau else "  ✓"))
        elif isinstance(v, list):
            print(f"  {k:24} {len(v)}" + (f"  ⚠️  {v[:5]}" if v else ""))
        else:
            print(f"  {k:24} {v:,}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
