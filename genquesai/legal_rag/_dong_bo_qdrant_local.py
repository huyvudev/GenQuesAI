"""Đồng bộ Qdrant LOCAL từ SERVER — copy toàn bộ (server=1.184.976 điểm, local chỉ có
832.731 — lệch ~30%, có từ lâu chứ không phải riêng vụ 284 VB hôm qua).

Cách làm: scroll TOÀN BỘ điểm (kèm vector dense+sparse+payload) từ server theo trang,
upsert thẳng vào local theo batch — không dùng snapshot API (cần quyền admin snapshot
trên server, không chắc có) nên đi đường an toàn hơn dù chậm hơn.

Idempotent: chạy lại nhiều lần không sao (upsert theo đúng id cũ, ghi đè bằng chính
nó nếu đã có).

Chạy: cd genquesai/legal_rag && python _dong_bo_qdrant_local.py"""
from __future__ import annotations
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, "D:/Project/GenQuesAI")

from qdrant_client import QdrantClient
from qdrant_client import models as qm

from genquesai.legal_rag.config import get_settings

BATCH = 100


def main() -> None:
    s = get_settings()
    q_srv = QdrantClient(url=s.qdrant_url, api_key=s.qdrant_api_key or None,
                         timeout=120, check_compatibility=False)
    q_loc = QdrantClient(url="http://127.0.0.1:6333", timeout=120, check_compatibility=False)

    total_srv = q_srv.get_collection(s.qdrant_collection).points_count
    print(f"Server: {total_srv:,} điểm. Bắt đầu scroll+upsert...")

    t0 = time.time()
    offset = None
    done = 0
    while True:
        points, offset = q_srv.scroll(
            s.qdrant_collection, limit=BATCH, offset=offset,
            with_payload=True, with_vectors=True)
        if not points:
            break
        upsert_points = [
            qm.PointStruct(id=p.id, vector=p.vector, payload=p.payload)
            for p in points
        ]
        # wait=True (khac ban truoc): tranh don request cho local khi RAM he thong dang
        # cang thang (vmmemWSL ~13.8GB, chi con ~3GB trong luc chay lan dau bi kill).
        q_loc.upsert(s.qdrant_collection, points=upsert_points, wait=True)
        done += len(points)
        del points, upsert_points
        if done % 3000 == 0 or offset is None:
            elapsed = time.time() - t0
            rate = done / elapsed if elapsed else 0
            eta = (total_srv - done) / rate if rate else 0
            print(f"  {done:,}/{total_srv:,} ({100*done/total_srv:.1f}%) "
                 f"· {elapsed:.0f}s trôi qua · ước còn {eta:.0f}s")
        if offset is None:
            break

    print(f"XONG: đã upsert {done:,} điểm trong {time.time()-t0:.0f}s")
    local_count = q_loc.get_collection(s.qdrant_collection).points_count
    print(f"Local sau đồng bộ: {local_count:,} điểm (server: {total_srv:,})")


if __name__ == "__main__":
    main()
