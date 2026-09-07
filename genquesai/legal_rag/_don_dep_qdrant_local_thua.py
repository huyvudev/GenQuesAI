"""Dọn điểm THỪA trên Qdrant local (có trên local nhưng KHÔNG có trên server) — sau
khi `_dong_bo_qdrant_local.py` upsert xong, local dư ra ~35k điểm so với server
(khả năng do logic re-chunk thay đổi qua thời gian tạo point_id khác, điểm cũ không
được dọn). Chỉ lấy ID (không lấy vector/payload) để nhẹ bộ nhớ — quét ~1.2 triệu ID
mỗi bên vẫn chỉ là chuỗi ngắn, không nặng như lần đồng bộ trước (có vector).

Chạy: cd genquesai/legal_rag && python _don_dep_qdrant_local_thua.py [--apply]"""
from __future__ import annotations
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, "D:/Project/GenQuesAI")

from qdrant_client import QdrantClient
from qdrant_client import models as qm

from genquesai.legal_rag.config import get_settings

SCROLL_BATCH = 5000


def quet_toan_bo_id(client: QdrantClient, collection: str) -> set[str]:
    ids: set[str] = set()
    offset = None
    while True:
        pts, offset = client.scroll(collection, limit=SCROLL_BATCH, offset=offset,
                                    with_payload=False, with_vectors=False)
        for p in pts:
            ids.add(str(p.id))
        if offset is None:
            break
    return ids


def main(apply: bool = False) -> None:
    s = get_settings()
    q_srv = QdrantClient(url=s.qdrant_url, api_key=s.qdrant_api_key or None,
                         timeout=120, check_compatibility=False)
    q_loc = QdrantClient(url="http://127.0.0.1:6333", timeout=120, check_compatibility=False)

    t0 = time.time()
    print("Quét toàn bộ ID trên SERVER...")
    ids_srv = quet_toan_bo_id(q_srv, s.qdrant_collection)
    print(f"  {len(ids_srv):,} ID ({time.time()-t0:.0f}s)")

    print("Quét toàn bộ ID trên LOCAL...")
    ids_loc = quet_toan_bo_id(q_loc, s.qdrant_collection)
    print(f"  {len(ids_loc):,} ID ({time.time()-t0:.0f}s)")

    thua = ids_loc - ids_srv
    thieu = ids_srv - ids_loc
    print(f"\nThừa trên local (sẽ xoá): {len(thua):,}")
    print(f"Thiếu trên local (bất thường, KHÔNG xoá gì — chỉ báo): {len(thieu):,}")

    if not apply:
        print("\n== DRY RUN — chưa xoá gì. Chạy lại với --apply để thực thi. ==")
        return

    if thua:
        thua_list = list(thua)
        CHUNK = 1000
        for i in range(0, len(thua_list), CHUNK):
            batch = thua_list[i:i + CHUNK]
            q_loc.delete(s.qdrant_collection, points_selector=qm.PointIdsList(points=batch), wait=True)
            print(f"  Đã xoá {min(i+CHUNK, len(thua_list))}/{len(thua_list)}")

    local_count = q_loc.get_collection(s.qdrant_collection).points_count
    print(f"\nXONG. Local sau dọn: {local_count:,} (server: {len(ids_srv):,})")


if __name__ == "__main__":
    main(apply="--apply" in sys.argv)
