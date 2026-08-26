"""Ra soat lai 10.133 canh REPLACES (loai ThayThe/BaiBoToanBo, mismatch/only_llm=true)
— nghi van sai phan loai (title tu ghi "mot so dieu/khoan/diem" nhung dang gan nhan
REPLACES). Chay lai CHINH XAC ham phan loai that (_phan_loai_dong_tu qua
extract_title_relations, roi extract_final_clause_relations neu title khong nhac
toi dich) — thuan regex, MIEN PHI, khong can LLM — de doi chieu voi loai da luu."""
from __future__ import annotations
import json
import sys
from pathlib import Path

sys.path.insert(0, "D:/Project/GenQuesAI")
sys.path.insert(0, str(Path(__file__).parent))

from genquesai.legal_rag.config import get_settings
from genquesai.legal_rag.graph.client import Neo4jClient
from genquesai.legal_rag.ingestion.reference_extractor import (
    extract_title_relations, extract_final_clause_relations, html_to_text, _norm_sh,
)
from _rebuild_full_corpus import build_local_file_index, build_text_from_qdrant
from qdrant_client import QdrantClient

HERE = Path(__file__).parent
LOG_PATH = HERE / "_ra_soat_replaces_log.jsonl"

_REPLACES_LOAI = {"ThayThe", "BaiBoToanBo"}
_AMENDS_LOAI = {"SuaDoi", "BaiBoTungPhan"}


def main(limit: int | None = None, dry_run: bool = True) -> None:
    s = get_settings()
    s_local = s.model_copy(update={
        "neo4j_uri": "bolt://localhost:7687", "neo4j_user": "neo4j",
        "neo4j_password": "123qwe", "neo4j_database": "neo4j",
    })
    neo = Neo4jClient(s_local)
    neo.verify()
    q = QdrantClient(url=s.qdrant_url, api_key=s.qdrant_api_key or None, timeout=60,
                     check_compatibility=False)
    corpus_dir = Path(s.corpus_dir)
    local_idx = build_local_file_index(corpus_dir)

    rows = neo.run("""
        MATCH (a:Action)-[:ENACTED_BY]->(src:Norm)
        MATCH (a)-[:AFFECTS]->(tgt:Norm)
        WHERE a.loai IN ['ThayThe', 'BaiBoToanBo'] AND (a.mismatch = true OR a.only_llm = true)
        RETURN a.action_id AS action_id, src.norm_id AS src_id, src.so_hieu AS src_sh,
               src.tieu_de AS src_title, tgt.norm_id AS tgt_id, tgt.so_hieu AS tgt_sh
    """)
    if limit:
        rows = rows[:limit]
    print(f"Cần rà: {len(rows):,} cạnh REPLACES")

    # gom theo src de doc file 1 lan / VB nguon (nhieu canh cung 1 nguon)
    by_src: dict[str, list[dict]] = {}
    for r in rows:
        by_src.setdefault(r["src_id"], []).append(dict(r))

    stats = {"giu_nguyen": 0, "doi_sang_amends": 0, "khong_the_kiem_tra": 0, "loi": 0}
    n = 0
    for src_id, items in by_src.items():
        n += 1
        if n % 500 == 0:
            print(f"  ...{n}/{len(by_src)} VB nguồn · {stats}")
        try:
            title = items[0]["src_title"] or ""
            own = items[0]["src_sh"]
            # buoc 1: chi can title (mien phi, da co san trong Neo4j)
            title_rel = extract_title_relations(title, own)
            title_map = {_norm_sh(t): (loai, edge) for loai, edge, t in title_rel}

            can_doc_full = any(_norm_sh(it["tgt_sh"]) not in title_map for it in items)
            full_map: dict[str, tuple[str, str]] = {}
            if can_doc_full:
                d = local_idx.get(src_id)
                try:
                    if d is not None:
                        text = html_to_text((d / "toanvan.html").read_text(encoding="utf-8", errors="ignore"))
                    else:
                        text = build_text_from_qdrant(q, s.qdrant_collection, src_id)
                    clause_rel = extract_final_clause_relations(text, own)
                    full_map = {_norm_sh(t): (loai, edge) for loai, edge, t in clause_rel}
                except Exception:
                    full_map = {}

            for it in items:
                tsh = _norm_sh(it["tgt_sh"])
                found = title_map.get(tsh) or full_map.get(tsh)
                if found is None:
                    stats["khong_the_kiem_tra"] += 1
                    _ghi_log({"action_id": it["action_id"], "src": it["src_sh"], "tgt": it["tgt_sh"],
                             "ket_qua": "khong_tim_thay_trong_regex", "giu_nguyen": True})
                    continue
                loai_moi, edge_moi = found
                if loai_moi in _AMENDS_LOAI:
                    stats["doi_sang_amends"] += 1
                    _ghi_log({"action_id": it["action_id"], "src": it["src_sh"], "tgt": it["tgt_sh"],
                             "loai_cu": "ThayThe/BaiBoToanBo", "loai_moi": loai_moi, "sua": True})
                    if not dry_run:
                        neo.run("""
                            MATCH (a:Action {action_id:$aid})-[:ENACTED_BY]->(src:Norm)
                            MATCH (a)-[:AFFECTS]->(tgt:Norm)
                            OPTIONAL MATCH (src)-[old:REPLACES]->(tgt)
                            DELETE old
                            MERGE (src)-[:AMENDS]->(tgt)
                            SET a.loai=$loai_moi, a.confidence=0.85
                        """, aid=it["action_id"], loai_moi=loai_moi)
                else:
                    stats["giu_nguyen"] += 1
        except Exception as e:
            stats["loi"] += len(items)
            print(f"  ! lỗi {src_id}: {e!r}")

    print(f"XONG: {stats}")
    print(f"(dry_run={dry_run} — {'CHƯA ghi gì vào Neo4j' if dry_run else 'ĐÃ ghi vào Neo4j'})")


def _ghi_log(rec: dict) -> None:
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")


if __name__ == "__main__":
    lim = int(sys.argv[1]) if len(sys.argv) > 1 else None
    dry = sys.argv[2].lower() != "false" if len(sys.argv) > 2 else True
    main(limit=lim, dry_run=dry)
