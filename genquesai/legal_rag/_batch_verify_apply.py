"""Ap dung ket qua doi chieu tu AI Cong vu (luatvietnammisa) vao Neo4j.
Doc `_batch_verify_log.jsonl` (moi dong: {"action_id":..., "verdict": "dung"|"sai"|"khong_ro"}),
ghi vao Action:
  - a.ai_verify = verdict (luon ghi, de audit/tham khao)
  - neu verdict == "dung": a.da_duyet = true (VA giu nguyen mismatch/only_llm cu de
    biet no TUNG can ra — chi da_duyet=true la thay doi, khien no chuyen sang
    _da_khop.csv trong lan xuat lai)
Idempotent — chay lai nhieu lan an toan (MERGE/SET, khong tao trung)."""
from __future__ import annotations
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, "D:/Project/GenQuesAI")
from genquesai.legal_rag.config import get_settings
from genquesai.legal_rag.graph.client import Neo4jClient

HERE = Path(__file__).parent
LOG_PATH = HERE / "_batch_verify_log.jsonl"


def main() -> None:
    s = get_settings()
    s_local = s.model_copy(update={
        "neo4j_uri": "bolt://localhost:7687", "neo4j_user": "neo4j",
        "neo4j_password": "123qwe", "neo4j_database": "neo4j",
    })
    neo = Neo4jClient(s_local)
    neo.verify()

    if not LOG_PATH.exists():
        print("Chưa có log nào để áp dụng.")
        return

    counts = {"dung": 0, "sai": 0, "khong_ro": 0, "loi": 0}
    seen: set[str] = set()
    with open(LOG_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                counts["loi"] += 1
                continue
            aid = rec.get("action_id")
            verdict = rec.get("verdict")
            if not aid or verdict not in ("dung", "sai", "khong_ro") or aid in seen:
                continue
            seen.add(aid)
            if verdict == "dung":
                neo.run("MATCH (a:Action {action_id:$aid}) SET a.ai_verify=$v, a.da_duyet=true",
                       aid=aid, v=verdict)
            else:
                neo.run("MATCH (a:Action {action_id:$aid}) SET a.ai_verify=$v", aid=aid, v=verdict)
            counts[verdict] += 1

    print(f"Đã áp dụng {sum(counts.values()):,} dòng (dedup theo action_id): {counts}")


if __name__ == "__main__":
    main()
