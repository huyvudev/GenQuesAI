"""Chưng cất bộ đề đã freeze thành SỰ KIỆN ĐỒ THỊ — hợp đồng golden của A1.

    python -m tests.trich_ky_vong                      # -> tests/golden/ky_vong.jsonl
    python -m tests.trich_ky_vong --vao out/g1.jsonl --ra /tmp/x.jsonl

Vì sao có bước này thay vì so thẳng hai file bộ đề
──────────────────────────────────────────────────
ROADMAP đề xuất kiểm A1 bằng cách *"sinh lại bộ 400 câu qua đường mới, so với
`out/eval_set.jsonl` đã freeze"*. Đúng hướng, nhưng so thẳng thì **kêu rất to kể cả khi
A1 hoàn toàn đúng**, vì bộ sinh chọn ứng viên theo:

    rows = neo.run(SELECT ... ORDER BY ... LIMIT $pool);  rng.shuffle(rows)

`ORDER BY size(anh_em) DESC, ngay_hieu_luc DESC` có **hàng loạt ca bằng điểm**, và
Neo4j không hứa thứ tự trong nhóm bằng điểm. Đổi thứ tự → `shuffle` cho hoán vị khác →
chọn ra bộ câu khác, dù mọi sự kiện đồ thị đều giống hệt. Diff sẽ đỏ vì lý do vô
nghĩa, và người đọc sẽ học cách bỏ qua nó — thước đo mất tác dụng.

Bước này tách hai thứ đang bị trộn:

    *bộ sinh chọn CÂU nào*     — được phép đổi, phụ thuộc thứ tự và seed
    *đồ thị nói SỰ THẬT gì*    — KHÔNG được phép đổi, đây mới là thứ A1 có thể phá

`ky_vong.jsonl` chỉ giữ vế thứ hai. Mỗi dòng là một khẳng định về corpus, phát biểu
bằng `norm_id`/`expr_id` — không nhắc Cypher, không nhắc `Corpus`, nên **cùng một file
kiểm được cả bản Neo4j lẫn bản sau A1**. Đó là điều kiện để nó là golden thật.

Mức nghiêm ngặt (`muc`)
───────────────────────
`chan`     — sai là A1 hỏng, chặn merge.
`canh_bao` — lệch có thể do khác biệt hợp lệ (chunk window, chuẩn hoá text). Báo, không
             chặn. Để ở đây thay vì bỏ đi, vì lệch HÀNG LOẠT ở tầng này vẫn là tín hiệu.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

GOC = Path(__file__).resolve().parent.parent
MAC_DINH_VAO = GOC / "out" / "eval_set.jsonl"
MAC_DINH_RA = GOC / "tests" / "golden" / "ky_vong.jsonl"


def _id(x: str, tien_to: str) -> str | None:
    """'Norm:106174' -> '106174'. Sai tiền tố -> None (không đoán)."""
    return x[len(tien_to) + 1:] if x.startswith(tien_to + ":") else None


def _norm_cua_expr(expr_id: str) -> str | None:
    """'146475::Dieu 4@2020-12-25' -> '146475'.

    Quy ước đặt tên của `legal-rag`, KHÔNG phải hợp đồng của framework. Chỉ dùng để
    ghi thêm một kỳ vọng phụ; mọi sự kiện chính đều tra qua `Corpus.expressions`.
    """
    return expr_id.split("::", 1)[0] if "::" in expr_id else None


def _sk(loai: str, muc: str = "chan", **kw) -> dict:
    return {"loai": loai, "muc": muc, **kw}


# ── từng nhóm ───────────────────────────────────────────────────────────────
def _g1(r: dict) -> list[dict]:
    rf = r["reference_fields"]
    moi = _id(r["gold_node_ids"][0], "Norm")
    cu = _id(r["gold_node_ids"][1], "Norm")
    ra = [
        # Điều kiện `size(ds) = 1` của G1 là SAU khi lọc `moi mới hơn cu` — nên phép
        # kiểm cũng phải lọc trước rồi mới đòi duy nhất, nếu không sẽ báo sai ở những
        # văn bản có thêm cạnh REPLACES ngược chiều (đã đo: 24 cạnh).
        _sk("thay_the_boi", norm=cu, ky_vong=[moi], duy_nhat=True, loc_moi_hon=True),
        _sk("so_hieu_norm", norm=moi, so_hieu=rf["so_hieu"]),
        _sk("ngay_hieu_luc_norm", norm=moi, ngay=rf.get("ngay_hieu_luc")),
    ]
    if r.get("distractor_ids"):
        # Bẫy G1 = "anh em gần": văn bản KHÁC cũng bị chính `moi` thay thế. Nếu A1 làm
        # mất chiều ngược của quan hệ thì bẫy biến mất trong im lặng — và bộ đề mất
        # đúng cái phân biệt `retriever_nham` với `retriever_sot`.
        ra.append(_sk("da_thay_the_chua_so_hieu", norm=moi,
                      so_hieu=sorted(r["distractor_ids"])))
    return ra


def _g2(r: dict) -> list[dict]:
    rf = r["reference_fields"]
    expr = _id(r["gold_node_ids"][0], "Expression")
    kind, moc = r["as_of_kind"], r["as_of_date"]
    ra = [
        _sk("expr_dong_tai", expr=expr, den=rf["moc_dong"]),
        # TRỌNG TÂM CỦA G2′: khoảng hiệu lực là NỬA MỞ [tu, den). Đúng ngày chuyển
        # giao thì bản CŨ đã hết. Đóng hai đầu là off-by-one — và `on_boundary` được
        # dựng ra chỉ để bắt đúng lỗi đó, nên nó phải là kỳ vọng `False` ở đây.
        _sk("expr_hieu_luc_tai", expr=expr, moc=moc, phai=(kind != "on_boundary")),
    ]
    if (nid := _norm_cua_expr(expr or "")):
        ra.append(_sk("so_hieu_norm", norm=nid, so_hieu=rf["cu"], muc="canh_bao"))
    return ra


def _g3(r: dict) -> list[dict]:
    rf = r["reference_fields"]
    con, me, moi = (_id(x, "Norm") for x in r["gold_node_ids"][:3])
    return [
        _sk("huong_dan", con=con, me=me),
        # `ky_vong_chua` chứ không `duy_nhat`: G3 không đòi văn bản mẹ chỉ bị đúng
        # một văn bản thay thế — đó là điều kiện của G1, chép nhầm sang đây thì test
        # đỏ ở những ca hoàn toàn hợp lệ.
        _sk("thay_the_boi", norm=me, ky_vong_chua=[moi], loc_moi_hon=True),
        _sk("so_hieu_norm", norm=con, so_hieu=rf["con"]),
        _sk("so_hieu_norm", norm=me, so_hieu=rf["me"]),
        _sk("so_hieu_norm", norm=moi, so_hieu=rf["moi"]),
    ]


def _g4(r: dict) -> list[dict]:
    rf = r["reference_fields"]
    vb = _id(r["gold_node_ids"][0], "Norm")
    nguon = [_id(x, "Norm") for x in r["gold_node_ids"][1:]]
    return [
        # Kỳ vọng ĐẮT NHẤT của cả bộ: nếu A1 đánh rơi bộ lọc `CAN_CU` thì tập này
        # phình ra (59% quan hệ đã duyệt là CanCu) và test đỏ ngay. Ghi cả `norm_id`
        # lẫn `so_hieu` vì gộp trùng số/năm diễn ra ở tầng so_hieu — hai vế bắt được
        # hai loại lỗi khác nhau.
        _sk("tac_dong_toi", norm=vb, ky_vong_ids=sorted(x for x in nguon if x),
            ky_vong_so_hieu=sorted(rf["danh_sach"])),
        _sk("so_hieu_norm", norm=vb, so_hieu=rf["van_ban_bi_tac_dong"]),
    ]


def _g5(r: dict) -> list[dict]:
    rf = r["reference_fields"]
    rule = _id(r["gold_node_ids"][0], "TransitionRule")
    norm = _id(r["gold_node_ids"][1], "Norm")
    return [
        _sk("chuyen_tiep", norm=norm, rule_id=rule, do_tin=rf.get("confidence"),
            dieu_kien=rf["dieu_kien"], ap_dung=rf["ap_dung"]),
        _sk("so_hieu_norm", norm=norm, so_hieu=rf["so_hieu"]),
    ]


def _g6(r: dict) -> list[dict]:
    rf = r["reference_fields"]
    con, me = (_id(x, "Norm") for x in r["gold_node_ids"][:2])
    return [
        _sk("huong_dan", con=con, me=me),
        # `cap_bac` là thứ DUY NHẤT mở khoá G6 ở corpus khác (báo cáo năng lực từ
        # chối cả nhóm khi không Norm nào có cap_bac). Pin lại cả hai đầu.
        _sk("cap_bac", norm=con, cap=rf["cap_a"]),
        _sk("cap_bac", norm=me, cap=rf["cap_b"]),
        _sk("so_hieu_norm", norm=con, so_hieu=rf["a"]),
        _sk("so_hieu_norm", norm=me, so_hieu=rf["b"]),
    ]


_TIEN_TO_DIEU = re.compile(r"^\s*(?:Điều|Dieu)\s*", re.IGNORECASE)


def _g7(r: dict) -> list[dict]:
    rf = r["reference_fields"]
    expr = _id(r["gold_node_ids"][0], "Expression")
    # `reference_fields["dieu"]` lấy từ `Component.duong_dan` — quy ước hiển thị của
    # legal-rag, có chỗ ghi 'Dieu 50a' có chỗ ghi '50a'. Kỳ vọng phải nói về SỐ ĐIỀU
    # (`so_thu_tu`), thứ độc lập với cách hiển thị; giữ nguyên `duong_dan` thì 15/90
    # ca G7 đỏ chỉ vì tiền tố, và cái đỏ đó che mất lỗi thật.
    so_dieu = _TIEN_TO_DIEU.sub("", str(rf["dieu"])).strip()
    return [
        # Kỳ vọng bắt trực tiếp chỗ dịch `HAS_PART*`: Điều này phải nằm trong tập
        # thành phần của văn bản, đúng số, đúng tiêu đề, và bản hiện hành đúng expr.
        # Dịch nhầm sang `HAS_PART` một-bước thì mọi Điều lồng dưới Chương biến mất.
        _sk("dieu_hien_hanh", norm=rf["norm_id"], so_dieu=so_dieu,
            tieu_de=rf["tieu_de"], expr=expr),
        _sk("so_hieu_norm", norm=rf["norm_id"], so_hieu=rf["so_hieu"]),
    ]


def _g8(r: dict) -> list[dict]:
    rf, ct = r["reference_fields"], r.get("cong_thuc")
    if ct == "a":
        return [_sk("khong_co_norm", so_hieu=rf["so_hieu_gia"])]
    if ct == "b":
        # G8(b) là phép kiểm `HAS_PART*` sạch nhất trong cả bộ: nó khẳng định số Điều
        # LỚN NHẤT của một văn bản có thật. Duyệt cây sót một nhánh thì con số tụt và
        # test đỏ — trong khi bộ đề vẫn "trông đúng" ở mọi cổng khác.
        return [
            _sk("so_dieu_lon_nhat", so_hieu=rf["so_hieu"],
                ky_vong=rf["dieu_lon_nhat_thuc_te"]),
            _sk("so_dieu_khong_co", so_hieu=rf["so_hieu"],
                so_dieu=rf["dieu_khong_ton_tai"]),
        ]
    if ct == "c":
        return [_sk("nam_ban_hanh", so_hieu=rf["so_hieu"], nam=rf["nam_ban_hanh"])]
    # (d) chủ đề ngoài phạm vi corpus — không có sự kiện đồ thị nào để kiểm. Ghi lại
    # để tổng số item khớp 400 và chỗ trống này là CỐ Ý, không phải bỏ sót.
    return [_sk("khong_kiem_duoc_bang_corpus", muc="ghi_chu",
                ly_do="chủ đề ngoài phạm vi — G8(d) không khẳng định gì về đồ thị")]


THEO_NHOM = {"G1": _g1, "G2": _g2, "G3": _g3, "G4": _g4,
             "G5": _g5, "G6": _g6, "G7": _g7, "G8": _g8}


def _span(r: dict) -> list[dict]:
    """Sự kiện chung mọi nhóm: expression được trích dẫn phải tồn tại, và đoạn trích
    phải nằm trong nội dung của nó.

    Vế thứ hai để `canh_bao`: `reference_contexts` cắt từ `payload["text"]` của Qdrant
    — một CỬA SỔ trên nội dung Expression, có thể đã qua chuẩn hoá khoảng trắng. Lệch
    lẻ tẻ là bình thường; lệch hàng loạt nghĩa là ánh xạ Expression→chunk đã trôi, và
    đó chính là ca A2 được thiết kế để xử lý.
    """
    ra = []
    for i, g in enumerate(r.get("gold_spans") or []):
        ra.append(_sk("expr_ton_tai", expr=g["expr_id"]))
        if i < len(r.get("reference_contexts") or []):
            ra.append(_sk("doan_trich_trong_expr", muc="canh_bao", expr=g["expr_id"],
                          doan=r["reference_contexts"][i][:200]))
    return ra


def chung_cat(rows: list[dict]) -> list[dict]:
    ra = []
    for r in rows:
        nhom = r["group"]
        su_kien = THEO_NHOM[nhom](r) + _span(r)
        # Bỏ sự kiện có tham chiếu rỗng thay vì để nó thành `None` giữa file: một kỳ
        # vọng không nêu được đối tượng thì không kiểm được gì, giữ lại chỉ tạo nhiễu.
        su_kien = [s for s in su_kien
                   if all(s.get(k) not in (None, "") for k in ("norm", "expr", "con")
                          if k in s)]
        ra.append({"id": r["id"], "nhom": nhom, "su_kien": su_kien})
    return ra


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--vao", type=Path, default=MAC_DINH_VAO)
    ap.add_argument("--ra", type=Path, default=MAC_DINH_RA)
    a = ap.parse_args()

    raw = a.vao.read_bytes()
    rows = [json.loads(x) for x in raw.decode("utf-8").splitlines() if x.strip()]
    ky_vong = chung_cat(rows)

    a.ra.parent.mkdir(parents=True, exist_ok=True)
    with a.ra.open("w", encoding="utf-8", newline="\n") as f:
        # Dòng đầu neo file này vào ĐÚNG bản bộ đề đã sinh ra nó. Bộ đề đổi mà kỳ vọng
        # không sinh lại thì test vẫn xanh trên một hợp đồng đã lỗi thời — im lặng và
        # tệ hơn là đỏ. `test_ky_vong.py` kiểm dòng này mỗi lần chạy.
        json.dump({"_meta": {
            "nguon": str(a.vao.relative_to(GOC)).replace("\\", "/"),
            "sha256_nguon": hashlib.sha256(raw).hexdigest(),
            "so_item": len(rows),
            "so_su_kien": sum(len(x["su_kien"]) for x in ky_vong),
        }}, f, ensure_ascii=False)
        f.write("\n")
        for x in ky_vong:
            json.dump(x, f, ensure_ascii=False)
            f.write("\n")

    dem: dict[str, int] = {}
    for x in ky_vong:
        for s in x["su_kien"]:
            dem[s["loai"]] = dem.get(s["loai"], 0) + 1
    print(f"{len(rows)} item -> {sum(dem.values())} sự kiện  ->  {a.ra}")
    for k, v in sorted(dem.items(), key=lambda kv: -kv[1]):
        print(f"  {v:>5}  {k}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
