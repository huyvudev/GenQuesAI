"""Kiểm tra CÒN LẠI bao nhiêu cạnh bất đồng (2 model không khớp nhau) CHƯA được xử lý
bởi bất kỳ rule fix nào trong 4 đợt trước (đồng thuận cao / khác cơ quan / VBHN / tin
Gemini nguồn đủ dày) — xác định qua trạng thái da_duyet HIỆN TẠI trong Neo4j (mọi rule
fix đều set da_duyet=false, nên da_duyet vẫn true nghĩa là chưa đụng tới).

Phân loại các cạnh còn lại theo dạng bất đồng để biết vì sao còn treo:
- "null_api": 1 trong 2 model bị lỗi API hoàn toàn (loai=None) -> chưa từng có ý kiến.
- "khongLienQuan_vs_that_A1": DeepSeek nói có thật, Gemini nói KhongLienQuan.
- "khongLienQuan_vs_that_A2": Gemini nói có thật, DeepSeek nói KhongLienQuan (ngược lại).
- "sac_thai_muc_do": cả 2 đều nói có quan hệ thật (khác None, khác KhongLienQuan) nhưng
  khác nhau về LOẠI mức độ (vd ThayThe vs SuaDoi, BaiBoToanBo vs BaiBoTungPhan...).

Chạy: cd genquesai/legal_rag && python _kiem_tra_con_lai_bat_dong.py
"""
from __future__ import annotations
import json
import sys
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, "D:/Project/GenQuesAI")

from genquesai.legal_rag.config import get_settings
from genquesai.legal_rag.graph.client import Neo4jClient

KET_QUA_PATH = "_rasoat_2llm_deploy/rasoat_2llm_log_KETQUA.jsonl"


def phan_loai(ds: str | None, gm: str | None) -> str:
    if ds is None or gm is None:
        return "null_api"
    if ds != "KhongLienQuan" and gm == "KhongLienQuan":
        return "khongLienQuan_vs_that_A1_deepseek"
    if gm != "KhongLienQuan" and ds == "KhongLienQuan":
        return "khongLienQuan_vs_that_A2_gemini"
    return "sac_thai_muc_do"


def main() -> None:
    s = get_settings()
    neo = Neo4jClient(s)

    print("== Đọc toàn bộ cạnh bất đồng từ audit log ==")
    bat_dong = []
    tong_cạnh = 0
    with open(KET_QUA_PATH, encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            if "ket_qua" not in d:
                continue
            for r in d["ket_qua"]:
                tong_cạnh += 1
                if not r["dong_thuan_2_model"]:
                    bat_dong.append({**r, "norm_id": d["norm_id"], "so_hieu_nguon": d["so_hieu"]})
    print(f"  Tổng cạnh đã rà soát: {tong_cạnh}")
    print(f"  Tổng cạnh bất đồng (2 model không khớp nhau): {len(bat_dong)} ({100*len(bat_dong)/tong_cạnh:.1f}%)")

    print("\n== Tra trạng thái da_duyet HIỆN TẠI trong Neo4j (còn true = chưa xử lý) ==")
    con_lai = []
    CHUNK = 1000
    action_ids = [r["action_id"] for r in bat_dong]
    trang_thai: dict[str, bool] = {}
    for i in range(0, len(action_ids), CHUNK):
        batch = action_ids[i:i + CHUNK]
        rows = neo.run(
            "MATCH (a:Action) WHERE a.action_id IN $ids RETURN a.action_id AS aid, a.da_duyet AS da_duyet",
            ids=batch)
        for row in rows:
            trang_thai[row["aid"]] = row["da_duyet"]
        print(f"  {min(i+CHUNK, len(action_ids))}/{len(action_ids)} đã tra")

    for r in bat_dong:
        dd = trang_thai.get(r["action_id"])
        if dd is True:  # còn nguyên, chưa bị revoke bởi rule nào
            con_lai.append(r)
        elif dd is None:
            # action_id không còn tồn tại (đã bị xoá/gộp lại) -> coi như đã xử lý, bỏ qua
            pass

    print(f"\n  CÒN LẠI CHƯA XỬ LÝ: {len(con_lai)}/{len(bat_dong)} cạnh bất đồng "
         f"({100*len(con_lai)/len(bat_dong):.1f}% của nhóm bất đồng, "
         f"{100*len(con_lai)/tong_cạnh:.1f}% của toàn bộ audit)")

    print("\n== Phân loại nhóm còn lại theo dạng bất đồng ==")
    dem = Counter(phan_loai(r["loai_deepseek"], r["loai_gemini"]) for r in con_lai)
    for k, v in dem.most_common():
        print(f"  {k}: {v} ({100*v/len(con_lai):.1f}%)")

    # Với riêng "sac_thai_muc_do", bóc tách xem cặp loại nào phổ biến nhất
    print("\n== Chi tiết 'sắc thái mức độ' — cặp (deepseek, gemini) phổ biến nhất ==")
    cap = Counter((r["loai_deepseek"], r["loai_gemini"]) for r in con_lai
                 if phan_loai(r["loai_deepseek"], r["loai_gemini"]) == "sac_thai_muc_do")
    for (ds, gm), v in cap.most_common(10):
        print(f"  DeepSeek={ds} / Gemini={gm}: {v}")

    # Với null_api, xem model nào lỗi nhiều hơn
    print("\n== Chi tiết 'null_api' — model nào bị lỗi ==")
    null_loai = Counter()
    for r in con_lai:
        if phan_loai(r["loai_deepseek"], r["loai_gemini"]) == "null_api":
            if r["loai_deepseek"] is None and r["loai_gemini"] is None:
                null_loai["ca_2_deu_null"] += 1
            elif r["loai_deepseek"] is None:
                null_loai["chi_deepseek_null"] += 1
            else:
                null_loai["chi_gemini_null"] += 1
    for k, v in null_loai.most_common():
        print(f"  {k}: {v}")

    out_path = "_con_lai_bat_dong_chua_xu_ly.jsonl"
    with open(out_path, "w", encoding="utf-8") as f:
        for r in con_lai:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"\nĐã ghi danh sách đầy đủ còn lại: {out_path}")


if __name__ == "__main__":
    main()
