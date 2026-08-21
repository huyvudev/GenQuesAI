"""Qdrant store — collection `legal_text_units`: named vector dense (bge-m3, 1024, Cosine)
+ sparse (thay BM25). Mỗi Expression = 1 point. (ARCH §4.3)"""
from __future__ import annotations

from qdrant_client import QdrantClient
from qdrant_client import models as qm

from ..config import Settings, get_settings

DENSE = "dense"
SPARSE = "sparse"


class QdrantStore:
    def __init__(self, settings: Settings | None = None):
        self._s = settings or get_settings()
        # check_compatibility=False: bỏ qua chênh lệch minor client/server (an toàn cho thao tác cơ bản)
        self.client = QdrantClient(url=self._s.qdrant_url, check_compatibility=False,
                                   timeout=self._s.qdrant_timeout)
        self.collection = self._s.qdrant_collection

    def exists(self) -> bool:
        return self.client.collection_exists(self.collection)

    def ensure_collection(self, recreate: bool = False) -> bool:
        """Tạo collection nếu chưa có. Trả True nếu vừa tạo."""
        if self.exists():
            if not recreate:
                return False
            self.client.delete_collection(self.collection)
        self.client.create_collection(
            collection_name=self.collection,
            vectors_config={
                DENSE: qm.VectorParams(size=self._s.embed_dense_dim, distance=qm.Distance.COSINE),
            },
            sparse_vectors_config={
                SPARSE: qm.SparseVectorParams(index=qm.SparseIndexParams(on_disk=False)),
            },
        )
        # Index payload để lọc TRƯỚC khi search (linh_vuc + khoảng hiệu lực) — ARCH §4.3
        for field_name, schema in [
            ("norm_id", qm.PayloadSchemaType.KEYWORD),
            ("expr_id", qm.PayloadSchemaType.KEYWORD),
            ("so_hieu", qm.PayloadSchemaType.KEYWORD),
            ("loai_vb", qm.PayloadSchemaType.KEYWORD),
            ("linh_vuc", qm.PayloadSchemaType.KEYWORD),
            ("hieu_luc_tu", qm.PayloadSchemaType.DATETIME),
            ("hieu_luc_den", qm.PayloadSchemaType.DATETIME),
        ]:
            self.client.create_payload_index(self.collection, field_name=field_name, field_schema=schema)
        return True

    def info(self) -> dict:
        c = self.client.get_collection(self.collection)
        return {"points": c.points_count, "status": str(c.status)}

    def upsert(self, points: list, chunk: int = 128) -> None:
        # Chunk để 1 request KHÔNG vượt giới hạn payload Qdrant (mặc định 32MB). VB có Phụ lục rất
        # dài -> hàng nghìn point/lần flush; gửi trọn gói sẽ lỗi 400 "JSON payload larger than allowed".
        for i in range(0, len(points), chunk):
            self.client.upsert(self.collection, points=points[i:i + chunk], wait=False)

    def search_dense(self, dense_vec, limit: int = 50, query_filter=None) -> list:
        return self.client.query_points(
            self.collection, query=list(dense_vec), using=DENSE,
            limit=limit, query_filter=query_filter, with_payload=True,
        ).points

    def search_sparse(self, sparse_vec, limit: int = 50, query_filter=None) -> list:
        return self.client.query_points(
            self.collection, query=sparse_vec, using=SPARSE,
            limit=limit, query_filter=query_filter, with_payload=True,
        ).points

    def _norm_filter(self, norm_id: str):
        return qm.Filter(must=[qm.FieldCondition(key="norm_id", match=qm.MatchValue(value=norm_id))])

    def count_by_norm(self, norm_id: str) -> int:
        """Số point của 1 VB (CDI: đối soát + undo)."""
        return self.client.count(self.collection, count_filter=self._norm_filter(norm_id),
                                 exact=True).count

    def delete_by_norm(self, norm_id: str) -> None:
        """Xoá toàn bộ point của 1 VB (CDI undo-import)."""
        self.client.delete(self.collection, points_selector=self._norm_filter(norm_id), wait=True)

    def delete_by_exprs(self, expr_ids: list[str]) -> int:
        """Xoá point theo expr_id (gồm MỌI cửa sổ 'expr_id#part' của 1 Expression) — CDI prune.
        Lọc theo payload expr_id nên đúng kể cả khi 1 Điều bị cắt thành nhiều point."""
        ids = [e for e in expr_ids if e]
        if not ids:
            return 0
        self.client.delete(self.collection, points_selector=qm.Filter(must=[
            qm.FieldCondition(key="expr_id", match=qm.MatchAny(any=ids))]), wait=True)
        return len(ids)

    def scroll_point_ids(self) -> set[str]:
        """Tập point_id ĐANG có trong Qdrant (cho embed resumable — bỏ qua đã embed)."""
        ids: set[str] = set()
        offset = None
        while True:
            pts, offset = self.client.scroll(self.collection, with_payload=False,
                                             with_vectors=False, limit=10000, offset=offset)
            for p in pts:
                ids.add(str(p.id))
            if offset is None:
                break
        return ids

    def scroll_norm_ids(self) -> set[str]:
        """Tập norm_id ĐANG có vector trong Qdrant (CDI: đối soát Neo4j↔Qdrant)."""
        ids: set[str] = set()
        offset = None
        while True:
            pts, offset = self.client.scroll(self.collection, with_payload=["norm_id"],
                                             with_vectors=False, limit=2000, offset=offset)
            for p in pts:
                nid = (p.payload or {}).get("norm_id")
                if nid:
                    ids.add(nid)
            if offset is None:
                break
        return ids

    def close(self) -> None:
        self.client.close()
