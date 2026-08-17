"""Bộ sinh có tái lập được không — đo trên hai lần chạy CÓ THẬT đã lưu lại.

`out/g1.jsonl` `out/g2.jsonl` `out/g7.jsonl` sinh bằng `run_g1/g2/g7`; lát cùng nhóm
trong `out/eval_set.jsonl` sinh bằng `run_all`. Theo README của bộ sinh thì hai bên
dùng cùng `n`, cùng `pool`, cùng `seed` — nên chúng PHẢI trùng nhau. Chỗ nào không
trùng là chỗ bộ sinh phụ thuộc thứ tự Neo4j trả về.

Vì sao điều này quan trọng với A1
─────────────────────────────────
ROADMAP đề xuất nghiệm thu A1 bằng "sinh lại rồi so với bản freeze". Kế hoạch đó chỉ
đọc được ở những nhóm mà **bản thân bộ sinh tái lập được**. Nhóm nào vốn đã không tái
lập thì diff luôn đỏ, dù A1 đúng hay sai — và không ai phân biệt được hai trường hợp.

Các test này chốt xem nhóm nào đang ở phía nào của ranh giới đó.

Cần `out/*.jsonl` (không version — `out/` nằm trong .gitignore) nên sẽ skip trên bản
clone sạch. Chấp nhận được: đây là phép đo về DỮ LIỆU đã chạy, không phải về mã nguồn.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.so_sanh import so_sanh

GOC = Path(__file__).resolve().parent.parent


def _lat(bo_de: list[dict], nhom: str) -> list[dict]:
    return [r for r in bo_de if r["group"] == nhom]


def _rieng(nhom: str) -> list[dict]:
    f = GOC / "out" / f"{nhom.lower()}.jsonl"
    if not f.exists():
        pytest.skip(f"thiếu {f} — chạy: python -m generator.run_{nhom.lower()}")
    return [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines() if x.strip()]


@pytest.mark.parametrize("nhom", ["G1", "G2"])
def test_nhom_tai_lap_duoc(bo_de, nhom):
    """G1 và G2 khớp từng chữ giữa hai lần chạy độc lập.

    Nghĩa là với hai nhóm này, "sinh lại rồi diff" LÀ một phép nghiệm thu A1 dùng
    được — diff đỏ ở đây thì chắc chắn do A1, không do thứ tự.
    """
    bc = so_sanh(_lat(bo_de, nhom), _rieng(nhom))
    assert bc["chi_ben_cu"] == [] and bc["chi_ben_moi"] == [], "khác tập câu"
    assert bc["doi_noi_dung"] == [], (
        f"{nhom} từng tái lập được mà nay lệch — xem trường nào trong báo cáo")


# PHÉP ĐO LỊCH SỬ trên hai artifact sinh bằng mã CŨ — 87/90 câu lệch. Nguyên nhân:
#   · distractor_ids  81 câu — `BAY_KHAC_VB` là `... LIMIT 2` KHÔNG có ORDER BY, nên
#     Neo4j trả hai hàng bất kỳ. Hai bẫy nội-văn-bản thì trùng; đúng hai bẫy
#     cross-norm là đổi. Bẫy là đầu vào của nhãn triage `retriever_nham`, nên bẫy trôi
#     thì hai lần chấm không so được với nhau ở mức nhãn nguyên nhân.
#   · question_form / persona / template  14–16 câu — gán theo VỊ TRÍ trong vòng lặp,
#     nên đổi thứ tự ứng viên là đổi dạng câu, dù chọn ra đúng cùng 90 item.
#
# ĐÃ SỬA ở bộ sinh: `ORDER BY` xác định cho `BAY_KHAC_VB` và cho subquery anh em,
# khoá phụ `e.expr_id` cho `LIMIT $pool`, và SẮP CHUẨN `rows` trước `rng.shuffle`.
# Tính chất mới được kiểm trực tiếp ở `tests/test_sinh_on_dinh.py` (đảo thứ tự đầu
# vào -> bộ đề y hệt), chứ không kiểm bằng hằng số dưới đây.
#
# Hằng số này KHÔNG tự về 0 khi sửa: nó so hai file đã sinh xong bằng mã cũ. Nó chỉ
# đổi khi có người sinh lại cả hai. Giữ lại để phép đo không bị mất.
G7_LECH_DA_BIET = 87


def test_G7_hai_artifact_cu_lech_dung_nhu_da_do(bo_de):
    """Ghim phép đo lịch sử. Đây là bằng chứng cho việc "sinh lại rồi diff" một mình
    KHÔNG đủ để nghiệm thu A1 — và là lý do bộ golden dựng trên sự kiện đồ thị."""
    bc = so_sanh(_lat(bo_de, "G7"), _rieng("G7"))
    assert bc["chi_ben_cu"] == [] and bc["chi_ben_moi"] == [], (
        "G7 chọn ra khác TẬP câu — nặng hơn hẳn mức lệch đã biết (chỉ khác nội dung)")
    n = len(bc["doi_noi_dung"])
    assert n == G7_LECH_DA_BIET, (
        f"{n} câu lệch, phép đo cũ là {G7_LECH_DA_BIET}. Hai artifact đổi nghĩa là "
        f"đã có người sinh lại — cập nhật hằng số kèm ghi chú vì sao.")


def test_bay_noi_van_ban_van_on_dinh(bo_de):
    """Phân định chính xác cái gì trôi: hai bẫy đầu (Điều khác CÙNG văn bản, lấy
    trong SELECT chính) phải ổn định. Chúng mà trôi nữa thì nguyên nhân khác hẳn."""
    cu = {r["id"]: r for r in _lat(bo_de, "G7")}
    moi = {r["id"]: r for r in _rieng("G7")}
    lech = [i for i in cu.keys() & moi.keys()
            if (cu[i].get("distractor_ids") or [])[:2]
            != (moi[i].get("distractor_ids") or [])[:2]]
    assert not lech, f"bẫy nội-văn-bản cũng trôi ở {len(lech)} câu: {lech[:5]}"
