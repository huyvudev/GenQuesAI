"""Replay từng kỳ vọng của bộ đề đã freeze lên `Corpus` — golden test của A1.

Chạy được là nhờ hai thứ rời nhau:
  `tests/golden/ky_vong.jsonl`  hợp đồng, sinh từ bộ đề, commit, offline
  `tests/golden/fixture/`       corpus để đối chiếu, xuất từ Neo4j một lần

Khi A1 xong, đây là **định nghĩa-xong**: 8 module `generator/` chuyển sang đọc `Corpus`,
và toàn bộ file này còn xanh ⇒ đường mới nhìn ra ĐÚNG những sự thật mà đường Cypher đã
nhìn ra. Câu nào sinh ra thì được phép khác; sự thật thì không.

Thiếu thực thể là ĐỎ, không phải skip: fixture đã hứa xuất đủ, nên thiếu nghĩa là bộ
xuất sai chứ không phải "chưa có dữ liệu". Skip ở đây là cách chắc chắn nhất để bộ
test lặng lẽ ngừng kiểm.
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import date
from pathlib import Path

import pytest

from framework import so_hieu as sh_mod
from framework import truy_van as tv

GOC = Path(__file__).resolve().parent.parent
KY_VONG = GOC / "tests" / "golden" / "ky_vong.jsonl"
PHAM_VI = GOC / "tests" / "golden" / "fixture" / "pham_vi.json"


def _tai() -> list[tuple[str, dict]]:
    """Nạp lúc IMPORT (không phải qua fixture) vì `parametrize` chạy khi thu thập."""
    if not KY_VONG.exists():
        return []
    dong = [json.loads(x) for x in
            KY_VONG.read_text(encoding="utf-8").splitlines() if x.strip()]
    return [(it["id"], s) for it in dong[1:] for s in it["su_kien"]]


_TAT_CA = _tai()
CHAN = [(i, s) for i, s in _TAT_CA if s["muc"] == "chan"]
CANH_BAO = [(i, s) for i, s in _TAT_CA if s["muc"] == "canh_bao"]


def _ten(iv: tuple[str, dict]) -> str:
    return f"{iv[0]}-{iv[1]['loai']}"


def _ngay(s: str | None) -> date | None:
    return date.fromisoformat(s[:10]) if s else None


def _norm(c, nid: str):
    n = c.norms.get(nid)
    assert n is not None, (
        f"fixture thiếu Norm {nid!r}. Bộ xuất phải phủ mọi văn bản kỳ vọng nhắc tới "
        f"— chạy lại: python -m tests.trich_fixture")
    return n


def _expr(c, eid: str):
    e = c.expressions.get(eid)
    assert e is not None, (
        f"fixture thiếu Expression {eid!r} — chạy lại: python -m tests.trich_fixture")
    return e


def _sh(x: str | None) -> str | None:
    return sh_mod.khoa(x)


# ── từng loại sự kiện ───────────────────────────────────────────────────────
def _thay_the_boi(c, s):
    goc = _norm(c, s["norm"])
    duoc = tv.thay_the_boi(c, s["norm"])
    if s.get("loc_moi_hon"):
        # G1 lọc `moi.ngay_hieu_luc > cu.ngay_hieu_luc` NGAY trong SELECT, rồi mới đòi
        # duy nhất. Bỏ bước lọc thì 24 cạnh ngược chiều + 46 cạnh cùng ngày (đã đo)
        # lọt vào và phá đẳng thức — báo đỏ ở chỗ dữ liệu vốn đã bị loại từ đầu.
        duoc = {x for x in duoc
                if (m := c.norms.get(x)) and m.ngay_hieu_luc and goc.ngay_hieu_luc
                and m.ngay_hieu_luc > goc.ngay_hieu_luc}
    if s.get("duy_nhat"):
        assert duoc == set(s["ky_vong"]), (
            f"{s['norm']} phải bị thay thế bởi ĐÚNG {s['ky_vong']}, thấy {sorted(duoc)}")
    else:
        thieu = set(s.get("ky_vong_chua") or s.get("ky_vong") or []) - duoc
        assert not thieu, f"{s['norm']}: thiếu văn bản thay thế {sorted(thieu)}"


def _da_thay_the_chua_so_hieu(c, s):
    duoc = {_sh(c.norms[x].so_hieu) for x in tv.da_thay_the(c, s["norm"])
            if x in c.norms}
    thieu = {x for x in s["so_hieu"] if _sh(x) not in duoc}
    assert not thieu, (
        f"{s['norm']} phải thay thế cả {sorted(thieu)} (bẫy 'anh em gần' của G1) — "
        f"mất chúng thì bộ đề hết phân biệt được retriever_nham với retriever_sot")


def _huong_dan(c, s):
    _norm(c, s["con"]), _norm(c, s["me"])
    assert s["me"] in tv.huong_dan_cho(c, s["con"]), (
        f"{s['con']} phải hướng dẫn {s['me']}")
    assert s["con"] in tv.duoc_huong_dan_boi(c, s["me"]), "chiều ngược không nhất quán"


def _tac_dong_toi(c, s):
    _norm(c, s["norm"])
    duoc = tv.tac_dong_toi(c, s["norm"])
    thieu = set(s["ky_vong_ids"]) - duoc
    assert not thieu, f"{s['norm']}: thiếu văn bản tác động {sorted(thieu)}"
    # Gộp theo số hiệu rồi mới so: nhiều norm_id là CÙNG một văn bản ghi khác cách,
    # không gộp thì danh sách trùng và Set-F1 phạt hệ vì trả lời đúng.
    duoc_sh = {_sh(c.norms[x].so_hieu) for x in duoc if x in c.norms} - {None}
    mong = {_sh(x) for x in s["ky_vong_so_hieu"]} - {None}
    thua = duoc_sh - mong
    assert not thua, (
        f"{s['norm']}: DƯ văn bản {sorted(thua)}. Dấu hiệu điển hình của việc đánh rơi "
        f"bộ lọc CAN_CU — 59% quan hệ đã duyệt là căn cứ pháp lý, không phải sửa đổi")
    assert not (mong - duoc_sh), f"{s['norm']}: thiếu {sorted(mong - duoc_sh)}"


def _so_hieu_norm(c, s):
    assert sh_mod.bang_nhau(_norm(c, s["norm"]).so_hieu, s["so_hieu"]), (
        f"{s['norm']} phải có số hiệu {s['so_hieu']!r}, "
        f"thấy {c.norms[s['norm']].so_hieu!r}")


def _ngay_hieu_luc_norm(c, s):
    assert _norm(c, s["norm"]).ngay_hieu_luc == _ngay(s["ngay"])


def _cap_bac(c, s):
    n = _norm(c, s["norm"])
    assert n.cap_bac == s["cap"], (
        f"{s['norm']} cấp bậc phải là {s['cap']}, thấy {n.cap_bac} — G6 không dựng "
        f"được nếu thang cấp bậc trôi")


def _chuyen_tiep(c, s):
    _norm(c, s["norm"])
    ds = {t.rule_id: t for t in tv.chuyen_tiep_cua(c, s["norm"])}
    t = ds.get(s["rule_id"])
    assert t is not None, (
        f"{s['norm']}: mất điều khoản chuyển tiếp {s['rule_id']!r} "
        f"(còn {sorted(ds)}) — kiểm ngưỡng do_tin 0.9 và cờ da_duyet")
    assert t.dieu_kien.strip() == s["dieu_kien"].strip()
    assert t.ap_dung.strip() == s["ap_dung"].strip()


def _expr_ton_tai(c, s):
    _expr(c, s["expr"])


def _expr_dong_tai(c, s):
    e = _expr(c, s["expr"])
    assert e.hieu_luc_den == _ngay(s["den"]), (
        f"{s['expr']} phải đóng tại {s['den']}, thấy {e.hieu_luc_den} — mốc chuyển "
        f"giao trôi thì mọi đáp án G2′ dựng trên nó sai theo")


def _expr_hieu_luc_tai(c, s):
    e = _expr(c, s["expr"])
    tai = tv.hieu_luc_tai(c, e.component_id, _ngay(s["moc"]))
    dang = tai is not None and tai.expression_id == s["expr"]
    if s["phai"]:
        assert dang, f"tại {s['moc']}, bản đang hiệu lực phải là {s['expr']}, thấy " \
                     f"{tai.expression_id if tai else None}"
    else:
        # on_boundary: hỏi ĐÚNG ngày chuyển giao thì bản cũ KHÔNG còn hiệu lực.
        assert not dang, (
            f"tại {s['moc']} bản {s['expr']} phải đã HẾT hiệu lực. Còn hiệu lực nghĩa "
            f"là khoảng đang bị hiểu là ĐÓNG [tu, den] thay vì nửa mở [tu, den) — "
            f"off-by-one mà 26/80 câu G2′ được dựng ra để bắt")


def _dieu_hien_hanh(c, s):
    _norm(c, s["norm"])
    muc = str(s["so_dieu"])
    ds = [d for d in tv.cac_dieu(c, s["norm"])
          if str(d.so_thu_tu).strip() == muc.strip()]
    assert ds, (
        f"{s['norm']} phải có Điều {muc!r}, thấy "
        f"{[d.so_thu_tu for d in tv.cac_dieu(c, s['norm'])][:12]} — nếu rỗng, khả năng "
        f"cao `HAS_PART*` bị dịch thành một-bước và mọi Điều lồng dưới Chương biến mất")
    assert any(tv.ban_hien_hanh(c, d.component_id) is not None
               and tv.ban_hien_hanh(c, d.component_id).expression_id == s["expr"]
               for d in ds), f"{s['norm']} Điều {muc}: bản hiện hành phải là {s['expr']}"


def _norm_theo_sh(c, s):
    ids = tv.norm_theo_so_hieu(c, s["so_hieu"], chuan_hoa=sh_mod.khoa)
    assert ids, f"fixture thiếu văn bản số hiệu {s['so_hieu']!r}"
    return ids


def _so_dieu_lon_nhat(c, s):
    ids = _norm_theo_sh(c, s)
    duoc = {tv.so_dieu_lon_nhat(c, x) for x in ids}
    assert s["ky_vong"] in duoc, (
        f"{s['so_hieu']}: số Điều lớn nhất phải là {s['ky_vong']}, thấy {sorted(x for x in duoc if x)}. "
        f"Tụt xuống nghĩa là duyệt cây sót nhánh — và câu G8 hỏi về một Điều CÓ THẬT")


def _so_dieu_khong_co(c, s):
    ids = _norm_theo_sh(c, s)
    assert all(s["so_dieu"] not in tv.so_dieu_da_dung(c, x) for x in ids), (
        f"{s['so_hieu']} Điều {s['so_dieu']} lại CÓ thật — câu G8 này không còn là "
        f"câu không có đáp án")


def _nam_ban_hanh(c, s):
    ids = _norm_theo_sh(c, s)
    assert any((n := c.norms[x]).ngay_ban_hanh and n.ngay_ban_hanh.year == s["nam"]
               for x in ids), f"{s['so_hieu']} phải ban hành năm {s['nam']}"


def _khong_co_norm(c, s):
    """Không replay được trên tập con — đọc phán quyết đã chốt lúc xuất fixture."""
    if not PHAM_VI.exists():
        pytest.skip("chưa có pham_vi.json — chạy python -m tests.trich_fixture")
    pv = json.loads(PHAM_VI.read_text(encoding="utf-8")).get("phu_dinh", {})
    if s["so_hieu"] not in pv:
        pytest.skip(f"{s['so_hieu']} chưa được chốt lúc xuất fixture")
    assert pv[s["so_hieu"]], (
        f"{s['so_hieu']} CÓ tồn tại trong đồ thị đầy đủ — câu G8(a) này có đáp án thật")


def _bo_qua(c, s):
    pytest.skip(s.get("ly_do", "không kiểm được bằng corpus"))


BANG = {
    "thay_the_boi": _thay_the_boi,
    "da_thay_the_chua_so_hieu": _da_thay_the_chua_so_hieu,
    "huong_dan": _huong_dan,
    "tac_dong_toi": _tac_dong_toi,
    "so_hieu_norm": _so_hieu_norm,
    "ngay_hieu_luc_norm": _ngay_hieu_luc_norm,
    "cap_bac": _cap_bac,
    "chuyen_tiep": _chuyen_tiep,
    "expr_ton_tai": _expr_ton_tai,
    "expr_dong_tai": _expr_dong_tai,
    "expr_hieu_luc_tai": _expr_hieu_luc_tai,
    "dieu_hien_hanh": _dieu_hien_hanh,
    "so_dieu_lon_nhat": _so_dieu_lon_nhat,
    "so_dieu_khong_co": _so_dieu_khong_co,
    "nam_ban_hanh": _nam_ban_hanh,
    "khong_co_norm": _khong_co_norm,
    "khong_kiem_duoc_bang_corpus": _bo_qua,
}


@pytest.mark.skipif(not CHAN, reason="chưa có ky_vong.jsonl — python -m tests.trich_ky_vong")
@pytest.mark.parametrize("item_id,sk", CHAN, ids=[_ten(x) for x in CHAN])
def test_su_kien(corpus, item_id, sk):
    ham = BANG.get(sk["loai"])
    assert ham is not None, (
        f"{item_id}: loại sự kiện {sk['loai']!r} chưa có bộ kiểm. Thêm loại vào "
        f"trich_ky_vong.py thì phải thêm cả ở đây, nếu không nó lặng lẽ không được kiểm")
    ham(corpus, sk)


# ── tầng cảnh báo: gộp lại, chỉ đỏ khi lệch HÀNG LOẠT ───────────────────────
# Từng ca lệch không nói lên gì (`reference_contexts` cắt từ cửa sổ Qdrant, có thể đã
# chuẩn hoá khoảng trắng khác với `Expression.text`). Nhưng lệch quá nửa thì ánh xạ
# Expression→chunk đã trôi — đúng ca mà A2 sinh ra để xử lý, và biết sớm thì tốt.
NGUONG_LECH = 0.35


def _chuan(s: str) -> str:
    return " ".join((s or "").split()).casefold()


@pytest.mark.skipif(not CANH_BAO, reason="chưa có ky_vong.jsonl")
def test_doan_trich_nam_trong_expression(corpus, record_property):
    ds = [(i, s) for i, s in CANH_BAO if s["loai"] == "doan_trich_trong_expr"]
    if not ds:
        pytest.skip("không có sự kiện doan_trich_trong_expr")
    lech = [i for i, s in ds
            if (e := corpus.expressions.get(s["expr"])) is None
            or _chuan(s["doan"])[:120] not in _chuan(e.text)]
    ty = len(lech) / len(ds)
    record_property("ty_le_lech", round(ty, 3))
    assert ty <= NGUONG_LECH, (
        f"{len(lech)}/{len(ds)} = {ty:.0%} đoạn trích không tìm thấy trong Expression "
        f"(ngưỡng {NGUONG_LECH:.0%}). Vài ca đầu: {lech[:5]}.\n"
        f"Lệch hàng loạt = ánh xạ Expression→chunk đã trôi; đây chính là ca A2 "
        f"(đối chiếu gold span theo NỘI DUNG thay vì chunk_id) được đặt ra để xử lý.")


@pytest.mark.skipif(not CANH_BAO, reason="chưa có ky_vong.jsonl")
def test_so_hieu_cua_expression_khop_van_ban(corpus, record_property):
    """G2 suy `norm_id` từ tiền tố `expr_id` — quy ước đặt tên của legal-rag, KHÔNG
    phải hợp đồng framework. Để cảnh báo vì corpus khác hoàn toàn có thể đặt khác."""
    ds = [(i, s) for i, s in CANH_BAO if s["loai"] == "so_hieu_norm"]
    if not ds:
        pytest.skip("không có sự kiện so_hieu_norm ở mức cảnh báo")
    lech = [i for i, s in ds
            if (n := corpus.norms.get(s["norm"])) is None
            or not sh_mod.bang_nhau(n.so_hieu, s["so_hieu"])]
    ty = len(lech) / len(ds)
    record_property("ty_le_lech", round(ty, 3))
    assert ty <= NGUONG_LECH, (
        f"{len(lech)}/{len(ds)} = {ty:.0%} expr_id không suy ra đúng văn bản. "
        f"Quy ước `<norm_id>::<phần>@<ngày>` có thể đã đổi. Vài ca: {lech[:5]}")


def test_moi_loai_su_kien_deu_co_bo_kiem():
    """Chặn kiểu hỏng nguy hiểm nhất của bộ golden: thêm kỳ vọng mới ở
    `trich_ky_vong.py` mà quên thêm bộ kiểm — file to ra, số test tăng, và loại mới
    KHÔNG được kiểm gì cả."""
    if not _TAT_CA:
        pytest.skip("chưa có ky_vong.jsonl")
    thieu = {s["loai"] for _, s in _TAT_CA
             if s["muc"] == "chan" and s["loai"] not in BANG}
    assert not thieu, f"loại sự kiện chưa có bộ kiểm: {sorted(thieu)}"


def test_moi_item_deu_co_it_nhat_mot_ky_vong():
    """400 câu thì phải có 400 item trong hợp đồng — kể cả G8(d) vốn không khẳng định
    gì về đồ thị, nó vẫn phải xuất hiện với ghi chú, để chỗ trống là CỐ Ý."""
    if not _TAT_CA:
        pytest.skip("chưa có ky_vong.jsonl")
    theo = defaultdict(int)
    for i, _ in _TAT_CA:
        theo[i] += 1
    assert len(theo) == 400, f"chỉ {len(theo)}/400 item có kỳ vọng"
