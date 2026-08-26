"""Entry point — chạy toàn bộ pipeline sinh QA (Bước 0-4). Không giữ khối
"ablation batch" của bản gốc (proposed.ipynb) — đây là công cụ sinh đề thực tế,
không phải phục vụ so sánh 4 biến thể cho báo cáo nghiên cứu (giả định mặc định,
nêu rõ với user — nếu cần ablation thì làm riêng sau).

Chạy: python -m genquesai.legal_rag.qa_gen.run [tong_muc_tieu] [workers]
(chạy TỪ thư mục genquesai/legal_rag để .env load đúng — xem bài học từ các script khác)."""
from __future__ import annotations
import json
import random
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, "D:/Project/GenQuesAI")

from genquesai.legal_rag.config import get_settings
from genquesai.legal_rag.graph.client import Neo4jClient
from genquesai.legal_rag.agent.llm import LLM
from genquesai.legal_rag.qa_gen.data import hop_nhat_du_lieu, lap_ke_hoach, tai_qdrant_fallback
from genquesai.legal_rag.qa_gen.generate import sinh_de
from genquesai.legal_rag.qa_gen.verify import vong_1_omission, vong_2_hieu_luc, cham_bay_hieu_luc, quality_gate
from genquesai.legal_rag.qa_gen.balance import can_bang, phan_phoi_thuc_te

HERE = Path(__file__).parent
RANDOM_SEED = 42


def main(tong_muc_tieu: int = 20, workers: int = 8) -> None:
    s = get_settings()
    s_local = s.model_copy(update={
        "neo4j_uri": "bolt://localhost:7687", "neo4j_user": "neo4j",
        "neo4j_password": "123qwe", "neo4j_database": "neo4j",
    })
    neo = Neo4jClient(s_local)
    neo.verify()
    llm = LLM(settings=s)

    t0 = time.time()
    print("== Bước 0: hợp nhất dữ liệu ==")
    print("  Đang quét Qdrant lấy dự phòng nội dung (1 lần, ~vài phút)...")
    qdrant_fallback = tai_qdrant_fallback(s)
    print(f"  Qdrant fallback: {len(qdrant_fallback):,} comp_id có nội dung ({time.time()-t0:.0f}s)")
    bang = hop_nhat_du_lieu(neo, qdrant_fallback)
    print(f"  {len(bang.dieu):,} Điều ({bang.so_dieu_lay_tu_qdrant:,} lấy từ Qdrant) · "
         f"{len(bang.quan_he_hieu_luc):,} quan hệ hiệu lực đã duyệt (cấp Điều/Khoản/Điểm) · "
         f"{len(bang.tham_chieu_noi_bo):,} tham chiếu nội bộ ({time.time()-t0:.0f}s)")

    print("== Bước 1: lập kế hoạch ==")
    ke_hoach = lap_ke_hoach(bang)
    print(f"  con_hieu_luc={ke_hoach.ty_le_con_hieu_luc:.2%} co_qhhl={ke_hoach.ty_le_co_quan_he_hieu_luc:.2%} "
         f"mat_do_cross_ref={ke_hoach.mat_do_tham_chieu_noi_bo:.3f}")
    print(f"  tỉ lệ: một_bước={ke_hoach.ty_le_mot_buoc:.1%} cấu_trúc={ke_hoach.ty_le_cau_truc:.1%} "
         f"hiệu_lực={ke_hoach.ty_le_hieu_luc:.1%} gài_bẫy={ke_hoach.ty_le_gai_bay:.1%} "
         f"bẫy_hiệu_lực={ke_hoach.ty_le_bay_hieu_luc:.1%}")

    so_luong = {
        "mot_buoc": int(round(tong_muc_tieu * ke_hoach.ty_le_mot_buoc)),
        "cau_truc": int(round(tong_muc_tieu * ke_hoach.ty_le_cau_truc)),
        "hieu_luc": int(round(tong_muc_tieu * ke_hoach.ty_le_hieu_luc)),
        "gai_bay": int(round(tong_muc_tieu * ke_hoach.ty_le_gai_bay)),
        "bay_hieu_luc": int(round(tong_muc_tieu * ke_hoach.ty_le_bay_hieu_luc)),
    }
    print(f"  ngân sách sinh: {so_luong}")

    rng = random.Random(RANDOM_SEED)  # 1 instance DUY NHẤT, truyền xuyên suốt (sửa bug reseed)

    print("== Bước 2: sinh đề ==")
    rows, diag2 = sinh_de(llm, bang, so_luong, rng, workers)
    print(f"  {diag2} -> tổng {len(rows)} câu ({time.time()-t0:.0f}s)")

    print("== Bước 3: chấm đề ==")
    rows, diag3a = vong_1_omission(llm, rows, workers)
    rows, diag3b = vong_2_hieu_luc(rows)
    rows, diag3c = cham_bay_hieu_luc(llm, rows, workers)
    print(f"  vòng 1 (omission): {diag3a} · vòng 2 (hiệu lực): {diag3b} · bẫy hiệu lực: {diag3c}")
    rows, diag3d = quality_gate(llm, rows, workers)
    print(f"  quality gate: {diag3d} -> còn {len(rows)} câu")

    print("== Bước 4: cân bằng tỉ lệ ==")
    rows, history = can_bang(llm, bang, ke_hoach, rows, tong_muc_tieu, rng, workers)
    print(f"  lịch sử TVD: {history}")

    phan_phoi = phan_phoi_thuc_te(rows)
    print(f"\n=== XONG: {len(rows)} câu hỏi ({time.time()-t0:.0f}s) ===")
    print(f"Phân phối thực tế: { {k: round(v,3) for k,v in phan_phoi.items()} }")

    out_path = HERE / "_out_qa.jsonl"
    with open(out_path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")
    print(f"Đã ghi: {out_path}")


if __name__ == "__main__":
    tt = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1] else 20
    wk = int(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2] else 8
    main(tong_muc_tieu=tt, workers=wk)
