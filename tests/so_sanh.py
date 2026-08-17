"""So hai bộ đề theo KHOÁ NỘI DUNG — bản dùng được của "sinh lại rồi diff".

    python -m tests.so_sanh out/eval_set.jsonl out/eval_set_a1.jsonl
    python -m tests.so_sanh cu.jsonl moi.jsonl --json bao_cao.json

Tách hai loại khác nhau, vì chúng có ý nghĩa ngược nhau
──────────────────────────────────────────────────────
**Khác TẬP CÂU** (câu này có ở bản cũ, không có ở bản mới): thường VÔ HẠI. Bộ sinh chọn
ứng viên bằng `ORDER BY ... LIMIT $pool` rồi `rng.shuffle`; các ca bằng điểm không có
thứ tự xác định, nên đổi thứ tự là đổi hoán vị là đổi bộ câu được chọn. Cần đọc, cần
giải thích được, nhưng không phải lỗi.

**Khác NỘI DUNG câu chung** (cùng một câu, đáp án khác): LUÔN là lỗi. Cùng sự kiện đồ
thị mà ra hai đáp án thì một trong hai sai — và bộ đề đã freeze là bên được coi là đúng.

Gộp hai loại vào một con số "N dòng khác nhau" là cách chắc chắn nhất khiến không ai
đọc kết quả diff nữa.

Khoá nội dung
─────────────
`(group, gold_node_ids đã sắp, as_of_date)` — tức ĐỊNH DANH ĐỒ THỊ của câu hỏi, không
phải vị trí của nó trong file. `id` dạng `G1-0007` đánh theo thứ tự sinh: chèn thêm một
câu ở đầu là mọi id sau đó lệch một, và diff theo id sẽ báo đỏ toàn bộ.

Trường biến thiên hợp lệ (xem `BO_QUA`) bị loại khỏi phép so — quan trọng nhất là
`user_input` của câu `situation`, vốn do LLM viết lại nên không tái lập được. Bản
template trước paraphrase thì deterministic, và ĐƯỢC so.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Không so — mỗi dòng một lý do, không phải "cho tiện".
BO_QUA = {
    "id",                       # vị trí trong file, không phải định danh
    "user_input",               # câu `situation` do LLM viết lại -> không tái lập
    "graph_snapshot",           # dấu thời gian lúc sinh
    "index_version",            # thuộc về hệ được đo, không thuộc bộ đề
    "generator_version",
    "human_verified",           # do người cập nhật sau khi sinh
    "status",
    "c4_diem", "c4_tra_loi_khong_ngu_canh", "do_retrieval",   # C4 chạy sau, gọi LLM
    "review_can_kiem",          # văn bản hướng dẫn cho người duyệt C5
}
# Trong `gates`, chỉ C1–C3 là tính chất của chính câu hỏi. C4 gọi LLM (không tái lập
# bit-đối-bit), C5 do người điền.
GATES_SO = ("C1", "C2", "C3")


def khoa(r: dict) -> tuple:
    """Định danh đồ thị của một câu. Xem ghi chú đầu file."""
    g = tuple(sorted(r.get("gold_node_ids") or []))
    if not g:
        # G8 không trỏ vào node nào (câu không có đáp án là đúng thiết kế) -> định danh
        # bằng chính tham số đã dựng ra nó.
        g = ("rf", json.dumps(r.get("reference_fields") or {},
                              ensure_ascii=False, sort_keys=True))
    return (r.get("group"), g, r.get("as_of_date"))


def _chuan(r: dict) -> dict:
    ra = {k: v for k, v in r.items() if k not in BO_QUA}
    if isinstance(r.get("gates"), dict):
        ra["gates"] = {k: r["gates"].get(k) for k in GATES_SO}
    # `user_input` của câu `lookup` sinh thẳng từ template -> deterministic, so được.
    # Của câu `situation` thì không. So đúng phần so được thay vì bỏ cả trường.
    if r.get("question_form") == "lookup":
        ra["user_input"] = r.get("user_input")
    return ra


def _khac_truong(a: dict, b: dict) -> dict[str, tuple]:
    ca, cb = _chuan(a), _chuan(b)
    ra = {}
    for k in sorted(set(ca) | set(cb)):
        if ca.get(k) != cb.get(k):
            ra[k] = (ca.get(k), cb.get(k))
    return ra


def _danh_chi_muc(rows: list[dict]) -> dict[tuple, dict]:
    """Khoá + số thứ tự lần lặp, để câu TRÙNG sự kiện vẫn ghép được 1–1.

    Bộ đề đã freeze CÓ câu trùng thật (xem `test_so_sanh.TRUNG_DA_BIET`). Nếu chỉ
    `{khoa(r): r}` thì bản trùng ghi đè bản trước và hai file giống hệt nhau lại báo
    "thiếu 2 câu" — bộ so sánh tự tạo ra sai lệch của chính nó.
    """
    dem: dict[tuple, int] = {}
    ra: dict[tuple, dict] = {}
    for r in rows:
        k = khoa(r)
        i = dem.get(k, 0)
        dem[k] = i + 1
        ra[(*k, i)] = r
    return ra


def so_sanh(cu: list[dict], moi: list[dict]) -> dict:
    ic, im = _danh_chi_muc(cu), _danh_chi_muc(moi)
    trung_cu = len(cu) - len({khoa(r) for r in cu})
    trung_moi = len(moi) - len({khoa(r) for r in moi})

    chung = sorted(set(ic) & set(im), key=lambda k: (k[0], str(k[1])))
    doi: list[dict] = []
    for k in chung:
        if kh := _khac_truong(ic[k], im[k]):
            doi.append({"khoa_nhom": k[0], "id_cu": ic[k]["id"], "id_moi": im[k]["id"],
                        "khac": {f: {"cu": v[0], "moi": v[1]} for f, v in kh.items()}})

    def _gon(ks):
        return sorted(({"nhom": k[0], "id": (ic.get(k) or im.get(k))["id"],
                        "khoa": str(k[1])[:120]} for k in ks),
                      key=lambda x: (x["nhom"], x["id"]))

    return {
        "so_cu": len(cu), "so_moi": len(moi),
        "trung_khoa_cu": trung_cu, "trung_khoa_moi": trung_moi,
        "chung": len(chung),
        "chi_ben_cu": _gon(set(ic) - set(im)),
        "chi_ben_moi": _gon(set(im) - set(ic)),
        "doi_noi_dung": doi,
    }


def in_bao_cao(bc: dict) -> None:
    print(f"\n  bản cũ {bc['so_cu']} câu   ·   bản mới {bc['so_moi']} câu   ·   "
          f"chung {bc['chung']} câu")
    for ben, ten in (("chi_ben_cu", "chỉ có ở bản CŨ"), ("chi_ben_moi", "chỉ có ở bản MỚI")):
        ds = bc[ben]
        if not ds:
            continue
        theo: dict[str, int] = {}
        for x in ds:
            theo[x["nhom"]] = theo.get(x["nhom"], 0) + 1
        print(f"\n  ~ {len(ds)} câu {ten}  "
              f"({', '.join(f'{k} {v}' for k, v in sorted(theo.items()))})")
        print("    Khác tập câu KHÔNG tự động là lỗi — bộ sinh chọn ứng viên qua")
        print("    `ORDER BY ... LIMIT` + shuffle, các ca bằng điểm không có thứ tự")
        print("    xác định. Nhưng phải GIẢI THÍCH ĐƯỢC, đừng chỉ ghi nhận.")
        for x in ds[:5]:
            print(f"      · {x['nhom']} {x['id']}  {x['khoa']}")
        if len(ds) > 5:
            print(f"      … còn {len(ds) - 5}")

    for k in ("trung_khoa_cu", "trung_khoa_moi"):
        if bc[k]:
            print(f"\n  ⚠️  {bc[k]} câu TRÙNG khoá nội dung ở bản "
                  f"{'cũ' if k.endswith('cu') else 'mới'} — cùng một sự kiện đồ thị bị "
                  f"hỏi hai lần, làm lệch trọng số khi chấm")

    doi = bc["doi_noi_dung"]
    if not doi:
        print("\n  ✅ Mọi câu CHUNG giống hệt nhau trên các trường có nghĩa.")
        return
    print(f"\n  ❌ {len(doi)} câu chung nhưng NỘI DUNG KHÁC — đây mới là lỗi thật:")
    dem: dict[str, int] = {}
    for d in doi:
        for f in d["khac"]:
            dem[f] = dem.get(f, 0) + 1
    print("     trường lệch: " +
          ", ".join(f"{k}×{v}" for k, v in sorted(dem.items(), key=lambda kv: -kv[1])))
    for d in doi[:5]:
        print(f"\n     {d['khoa_nhom']}  {d['id_cu']} → {d['id_moi']}")
        for f, v in list(d["khac"].items())[:4]:
            print(f"       {f}:\n         cũ  {str(v['cu'])[:160]}\n"
                  f"         mới {str(v['moi'])[:160]}")
    if len(doi) > 5:
        print(f"\n     … còn {len(doi) - 5} câu")


def _doc(f: Path) -> list[dict]:
    return [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines() if x.strip()]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cu", type=Path, help="bộ đề đã freeze")
    ap.add_argument("moi", type=Path, help="bộ đề sinh lại")
    ap.add_argument("--json", type=Path, help="ghi báo cáo đầy đủ ra file")
    a = ap.parse_args()

    bc = so_sanh(_doc(a.cu), _doc(a.moi))
    in_bao_cao(bc)
    if a.json:
        a.json.write_text(json.dumps(bc, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\n  báo cáo đầy đủ -> {a.json}")
    # Chỉ nội dung lệch mới là hỏng. Khác tập câu trả 0 để không ai học cách bỏ qua
    # exit code này.
    return 1 if bc["doi_noi_dung"] else 0


if __name__ == "__main__":
    sys.exit(main())
