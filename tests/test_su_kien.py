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


def _pham_vi() -> dict:
    if not PHAM_VI.exists():
        return {}
    return json.loads(PHAM_VI.read_text(encoding="utf-8")).get("nguon_khong_co", {})


_KHONG_CO = _pham_vi()


def _vang_o_nguon(loai: str, ma: str) -> bool:
    return ma in set(_KHONG_CO.get(loai) or ())


def _norm(c, nid: str):
    n = c.norms.get(nid)
    if n is None and _vang_o_nguon("norm", nid):
        # KHÔNG phải lỗi bộ xuất: đồ thị nguồn vốn không có văn bản này. Nghĩa là bộ
        # đề đã freeze lệch phiên bản với đồ thị hiện tại — sinh lại bộ đề mới hết.
        pytest.skip(f"Norm {nid!r} không có trong đồ thị nguồn lúc xuất fixture "
                    f"— bộ đề lệch phiên bản, không phải lỗi mã")
    assert n is not None, (
        f"fixture thiếu Norm {nid!r}. Bộ xuất phải phủ mọi văn bản kỳ vọng nhắc tới "
        f"— chạy lại: python -m tests.trich_fixture")
    return n


def _expr(c, eid: str):
    e = c.expressions.get(eid)
    if e is None and _vang_o_nguon("expr", eid):
        pytest.skip(f"Expression {eid!r} không có trong đồ thị nguồn lúc xuất fixture "
                    f"— bộ đề lệch phiên bản, không phải lỗi mã")
    assert e is not None, (
        f"fixture thiếu Expression {eid!r} — chạy lại: python -m tests.trich_fixture")
    return e


def _sh(x: str | None) -> str | None:
    return sh_mod.khoa(x)


_cache_nn: dict[int, frozenset] = {}


def _nhap_nhang(c) -> frozenset:
    """Khoá số hiệu ứng với nhiều văn bản — nhớ theo corpus, tính một lần."""
    if (k := id(c)) not in _cache_nn:
        _cache_nn[k] = frozenset(tv.khoa_nhap_nhang(c, sh_mod.khoa))
    return _cache_nn[k]


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
    # Bộ sinh CỐ Ý bỏ khỏi danh sách những số hiệu ứng với nhiều văn bản — câu hỏi
    # danh sách không phán được hệ trả đúng hay sai phần tử mơ hồ. Nên đồ thị thô trả
    # về nhiều hơn đáp án là ĐÚNG THIẾT KẾ ở riêng những khoá đó.
    # Vẫn giữ nguyên sức mạnh của phép kiểm: rò rỉ CAN_CU sẽ kéo vào những văn bản có
    # khoá DUY NHẤT, và chúng vẫn bị bắt.
    # Bộ sinh còn gộp theo `số/năm` (`g4_history._khoa_gop`) để dồn các cách ghi khác
    # nhau của CÙNG một văn bản: `17/2006/TTLT/BLĐTBXH-BTC-BYT` và
    # `17/2006/TTLT-BLĐTBXH-BTC-BYT` chỉ khác dấu phân cách. Phép kiểm phải mô phỏng
    # đúng phép gộp đó, nếu không nó báo "DƯ" ở chính thứ bộ sinh cố ý dồn lại.
    so_nam = {x.split("/")[0] + "/" + x.split("/")[1] for x in mong if x.count("/") >= 2}
    thua = {x for x in duoc_sh - mong - set(_nhap_nhang(c))
            if not (x.count("/") >= 2 and x.split("/")[0] + "/" + x.split("/")[1] in so_nam)}
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
    if not ids and _vang_o_nguon("so_hieu", s["so_hieu"]):
        pytest.skip(f"số hiệu {s['so_hieu']!r} không có trong đồ thị nguồn "
                    f"— bộ đề lệch phiên bản, không phải lỗi mã")
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
    """G8(c) hỏi về một năm TRƯỚC khi văn bản có hiệu lực.

    Lưu ý tên trường gây nhầm: `reference_fields["nam_ban_hanh"]` thực ra chứa năm
    HIỆU LỰC (`g8_unanswerable` lấy từ `n.ngay_hieu_luc`), không phải năm ban hành.
    Hai mốc này lệch nhau thật — `65/2025/TT-BCT` ban hành 2025, hiệu lực 2026.
    Kiểm theo thứ bộ sinh THỰC SỰ dùng, và ghi lại chỗ đặt tên sai để đổi ở lần
    sinh sau (đổi tên trường bây giờ thì phải chạy lại paraphrase + C4, tốn tiền
    API cho một cái tên).
    """
    ids = _norm_theo_sh(c, s)
    assert any((n := c.norms[x]).ngay_hieu_luc and n.ngay_hieu_luc.year == s["nam"]
               for x in ids), (
        f"{s['so_hieu']} phải có hiệu lực năm {s['nam']}, thấy "
        f"{[str(c.norms[x].ngay_hieu_luc) for x in ids]}")


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
    # So với nội dung CẢ CÂY, không phải riêng một Expression: chunk trong index ghép
    # sẵn câu dẫn với các Khoản/Điểm bên dưới, còn `Expression.text` chỉ có phần của
    # riêng node đó (đo thật: 54 ký tự vs 890). So với node lẻ thì 80% ca lệch, và cái
    # đỏ đó nói về cách lưu trữ chứ không nói gì về ánh xạ Expression→chunk.
    lech, khong_co_text = [], []
    for i, s in ds:
        e = corpus.expressions.get(s["expr"])
        if e is None:
            lech.append(i)
            continue
        # Theo ĐÚNG mốc của expression được trích, không phải "hiện hành": gold span
        # của G2 là bản LỊCH SỬ đã đóng, và bản hiện hành của cùng Component là văn
        # bản khác hẳn. Lấy nhầm mốc thì 26% ca ra chuỗi rỗng.
        day_du = (tv.noi_dung_cay(corpus, e.component_id, moc=e.hieu_luc_tu)
                  or tv.noi_dung_cay(corpus, e.component_id))
        if not day_du.strip():
            # Đồ thị KHÔNG có nội dung, dù index có. Không kiểm được containment ở
            # đây — và bản thân nó là phát hiện riêng, đo ở test kế bên.
            khong_co_text.append(i)
            continue
        if _chuan(s["doan"])[:120] not in _chuan(day_du):
            lech.append(i)
    record_property("khong_co_text_trong_do_thi", len(khong_co_text))
    ds = [x for x in ds if x[0] not in set(khong_co_text)]
    if not ds:
        pytest.skip("không ca nào có nội dung trong đồ thị để đối chiếu")
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


# Không còn chốt "thiếu text trong đồ thị". Con số 62% từng ghi ở đây là SAI, và sai
# theo cách đáng ghi lại: nội dung văn bản QPPL nằm ở LÁ (Khoản 939.964 node 0% rỗng,
# Điểm 736.973 node 0% rỗng), còn Điều rỗng 69% vì Điều có Khoản con không mang text
# riêng. Hai lỗi cộng lại tạo ra ảo giác "đồ thị không có nội dung":
#   · `trich_fixture` xuất Component chứa expr mà KHÔNG xuất cây con
#   · phép kiểm ghép cây theo bản HIỆN HÀNH, trong khi gold span của G2 là bản lịch sử
# Sửa cả hai -> 0/375 thiếu nội dung. A1 KHÔNG bị chặn bởi chuyện này; nó chỉ phải
# ghép cây theo đúng mốc thay vì đọc `Expression.text` của một node.


# Bao nhiêu phần kỳ vọng được phép "không kiểm được vì nguồn không có". Ngưỡng này là
# cái chuông: bộ đề lệch phiên bản với đồ thị càng xa thì càng ít thứ được kiểm, và
# một ngày nào đó bộ golden xanh mà chẳng kiểm gì. Đo lúc chốt: 24%.
NGUONG_KHONG_KIEM_DUOC = 0.30


def test_phan_khong_kiem_duoc_khong_qua_lon(corpus):
    """Skip có đếm, có ngưỡng — nếu không thì skip chính là cách bộ golden chết dần."""
    if not _KHONG_CO:
        pytest.skip("fixture chưa ghi `nguon_khong_co` — chạy lại trich_fixture")
    vang_n = set(_KHONG_CO.get("norm") or ())
    vang_e = set(_KHONG_CO.get("expr") or ())
    dinh = sum(1 for _, s in CHAN
               if (s.get("norm") in vang_n or s.get("con") in vang_n
                   or s.get("me") in vang_n or s.get("expr") in vang_e))
    ty = dinh / max(len(CHAN), 1)
    assert ty <= NGUONG_KHONG_KIEM_DUOC, (
        f"{dinh}/{len(CHAN)} = {ty:.0%} kỳ vọng không kiểm được vì đồ thị nguồn thiếu "
        f"thực thể (ngưỡng {NGUONG_KHONG_KIEM_DUOC:.0%}).\n"
        f"Bộ đề đã freeze và đồ thị hiện tại đã lệch phiên bản quá xa — sinh lại bộ đề "
        f"rồi chạy lại `trich_ky_vong` + `trich_fixture`.")


def test_moi_item_deu_co_it_nhat_mot_ky_vong():
    """400 câu thì phải có 400 item trong hợp đồng — kể cả G8(d) vốn không khẳng định
    gì về đồ thị, nó vẫn phải xuất hiện với ghi chú, để chỗ trống là CỐ Ý."""
    if not _TAT_CA:
        pytest.skip("chưa có ky_vong.jsonl")
    theo = defaultdict(int)
    for i, _ in _TAT_CA:
        theo[i] += 1
    assert len(theo) == 400, f"chỉ {len(theo)}/400 item có kỳ vọng"
