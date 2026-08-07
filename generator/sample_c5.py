"""Cổng C5 — rút mẫu phân tầng để người duyệt kiểm (Mục 1).

C5 KHÔNG đo hệ RAG. Nó đo **chính bộ đề**: đáp án sinh từ đồ thị chỉ đúng *so với đồ
thị*, không phải so với luật. Nếu pipeline trích xuất sai (REPLACES ngược chiều, parse
sai ngày, gán nhầm Điều) thì bộ đề mã hoá đúng lỗi đó và chấm sai một hệ trả lời đúng.

Kết quả C5 = `eval_set_ceiling` = TRẦN TRÊN của mọi chỉ số ở Mục 6. Không có nó thì
không con số nào ở vòng đánh giá diễn giải được.

Mỗi nhóm có một CÂU HỎI KIỂM riêng — người duyệt không phải tự nghĩ ra phải đối chiếu
cái gì.
"""
from __future__ import annotations

import json
import random
from collections import defaultdict

# Việc người duyệt phải làm, theo từng nhóm. Viết ở dạng mệnh lệnh cụ thể chứ không
# phải "kiểm tra xem có đúng không" — mơ hồ thì mỗi người hiểu một kiểu.
CAU_HOI_KIEM = {
    "G1": "Mở văn bản nguồn: <b>{moi}</b> có thật sự thay thế <b>{cu}</b> không? "
          "Chú ý phân biệt <i>thay thế</i> với <i>sửa đổi, bổ sung</i>.",
    "G2": "Tại <b>{as_of}</b>, văn bản đang có hiệu lực về nội dung này có đúng là "
          "<b>{norm}</b> không? Mốc chuyển giao ghi nhận là <b>{moc}</b>.",
    "G3": "<b>{con}</b> hiện còn hiệu lực hay đã hết? Đáp án bộ đề ghi: "
          "<b>{nhan}</b>. Lưu ý: văn bản mẹ bị thay KHÔNG đương nhiên làm văn bản "
          "hướng dẫn hết hiệu lực.",
    "G4": "Danh sách văn bản đã tác động tới <b>{vb}</b> có <b>đủ và đúng</b> không? "
          "Thiếu một văn bản hay thừa một văn bản đều tính là sai.",
    "G5": "Điều khoản chuyển tiếp tại <b>{nguon}</b> có thật sự quy định như đáp án "
          "không?",
    "G6": "<b>Điều kiện (3):</b> hai quy định có <b>hệ quả pháp lý khác nhau</b> "
          "(mức, thời hạn, điều kiện) hay chỉ khác mức độ chi tiết? "
          "Chỉ khác chi tiết ⇒ <b>KHÔNG phải xung đột</b>, đánh Sai.",
    "G7": "Đoạn trích dẫn có đúng là nội dung của <b>{dieu}</b> thuộc <b>{sh}</b>, "
          "và có trả lời được câu hỏi không?",
    "G8": "Câu hỏi này có <b>thật sự không có đáp án</b> trong hệ thống văn bản không? "
          "Nếu thực tế có văn bản/điều khoản tương ứng thì đánh Sai.",
}

URL_NGUON = """
UNWIND $ids AS nid
MATCH (n:Norm {norm_id: nid})
RETURN nid AS norm_id, n.nguon_url AS url, n.tieu_de AS tieu_de, n.so_hieu AS so_hieu
"""


def _mo_ta_kiem(it: dict) -> str:
    rf = it.get("reference_fields") or {}
    g = it["group"]
    try:
        if g == "G1":
            return CAU_HOI_KIEM[g].format(moi=rf.get("so_hieu"), cu=_cu_tu_hoi(it))
        if g == "G2":
            return CAU_HOI_KIEM[g].format(as_of=it.get("as_of_date"),
                                          norm=rf.get("norm_id_hieu_luc"),
                                          moc=rf.get("moc_dong"))
        if g == "G3":
            return CAU_HOI_KIEM[g].format(con=rf.get("con"), nhan=rf.get("nhan"))
        if g == "G4":
            return CAU_HOI_KIEM[g].format(vb=rf.get("van_ban_bi_tac_dong"))
        if g == "G5":
            return CAU_HOI_KIEM[g].format(nguon=rf.get("nguon_dieu_khoan")
                                          or rf.get("so_hieu"))
        if g == "G7":
            return CAU_HOI_KIEM[g].format(dieu=rf.get("dieu"), sh=rf.get("so_hieu"))
    except Exception:
        pass
    return CAU_HOI_KIEM.get(g, "Đáp án có đúng không?")


def _cu_tu_hoi(it: dict) -> str:
    from .common import core_so_hieu
    return core_so_hieu(it.get("user_input", "")) or "(văn bản trong câu hỏi)"


def _norm_ids(it: dict) -> list[str]:
    out = []
    for x in it.get("gold_node_ids") or []:
        if x.startswith("Norm:"):
            out.append(x.split(":", 1)[1])
    return out


def rut_mau(items: list[dict], tong: int = 80, seed: int = 20260807) -> list[dict]:
    """Phân tầng theo nhóm, và trong G2 phân tầng tiếp theo `as_of_kind`.

    Chia ĐỀU các nhóm chứ không theo tỷ lệ quota: `eval_set_ceiling` đo RIÊNG từng
    nhóm (Mục 9), nên nhóm 25 câu cũng cần đủ mẫu như nhóm 90 câu.
    """
    rng = random.Random(seed)
    theo_nhom: dict[str, list] = defaultdict(list)
    for it in items:
        theo_nhom[it["group"]].append(it)

    moi_nhom = max(1, tong // len(theo_nhom))
    mau: list[dict] = []
    for g in sorted(theo_nhom):
        ds = theo_nhom[g]
        if g == "G2":
            phu: dict[str, list] = defaultdict(list)
            for it in ds:
                phu[it.get("as_of_kind", "?")].append(it)
            lay, da = [], set()
            for k in sorted(phu):
                rng.shuffle(phu[k])
                phan = phu[k][: max(1, moi_nhom // len(phu))]
                lay += phan
                da |= {x["id"] for x in phan}
            # Chia đều ba loại xong thường hụt vài câu do làm tròn -> bù cho đủ
            # chỉ tiêu, nếu không nhóm này bị lấy mẫu ít hơn các nhóm khác.
            if len(lay) < moi_nhom:
                lay += [x for x in ds if x["id"] not in da][:moi_nhom - len(lay)]
            mau += lay[:moi_nhom]
        else:
            rng.shuffle(ds)
            mau += ds[:moi_nhom]
    return mau


def chuan_bi(items: list[dict], neo, tong: int = 80) -> list[dict]:
    """Rút mẫu + gắn câu hỏi kiểm + link văn bản gốc."""
    mau = rut_mau(items, tong)
    ids = sorted({x for it in mau for x in _norm_ids(it)})
    thong_tin = {r["norm_id"]: r for r in neo.run(URL_NGUON, ids=ids)} if ids else {}

    for it in mau:
        it["c5_cau_hoi_kiem"] = _mo_ta_kiem(it)
        it["c5_nguon"] = [
            {"norm_id": nid,
             "so_hieu": (thong_tin.get(nid) or {}).get("so_hieu"),
             "tieu_de": (thong_tin.get(nid) or {}).get("tieu_de"),
             "url": (thong_tin.get(nid) or {}).get("url")}
            for nid in _norm_ids(it)
        ]
    return mau
