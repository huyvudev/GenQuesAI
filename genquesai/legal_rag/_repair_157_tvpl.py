"""Xu ly 157 VB "that su thieu" (khong co noi dung o bat ky thu muc nao trong
corpus, da tai tu thuvienphapluat.vn vao CORPUS_DIR/tvpl_backfill/<id>/). Chay lai
resolve_relations cho rieng 157 VB nay, ghi vao SERVER production (Neo4j hien tai
dang dung, giong _repair_127_rong.py)."""
from __future__ import annotations
import json
import sys
from pathlib import Path

sys.path.insert(0, "D:/Project/GenQuesAI")

from genquesai.legal_rag.config import get_settings
from genquesai.legal_rag.graph.client import Neo4jClient
from genquesai.legal_rag.agent.llm import LLM
from genquesai.legal_rag.ingestion.consensus import resolve_relations, _FLAG
from genquesai.legal_rag.ingestion.reference_extractor import html_to_text
from _rebuild_full_corpus import build_local_file_index

HERE = Path(__file__).parent
LOG_PATH = HERE / "_repair_157_log.jsonl"
SCRATCH = Path(r"C:\Users\Huy\AppData\Local\Temp\claude\D--Project-GenQuesAI\5b20e156-444f-43bd-90f2-eb3d0665329e\scratchpad")


def main(limit: int | None = None) -> None:
    with open(SCRATCH / "build_corpus_ok_ids.json", encoding="utf-8") as f:
        ids = json.load(f)
    if limit:
        ids = ids[:limit]
    print(f"Se xu ly {len(ids)} VB", flush=True)

    s = get_settings()
    neo = Neo4jClient(s)
    neo.verify()
    llm = LLM(settings=s)

    corpus_dir = Path(s.corpus_dir)
    local_idx = build_local_file_index(corpus_dir)

    counts = {"khop": 0, "mismatch": 0, "only_llm": 0, "van_rong": 0, "loi": 0, "khong_thay_file": 0}
    for i, nid in enumerate(ids, 1):
        try:
            d = local_idx.get(nid)
            if d is None:
                counts["khong_thay_file"] += 1
                print(f"  ! {nid}: khong tim thay file (bat thuong)", flush=True)
                continue
            data = json.loads((d / "doc.json").read_text(encoding="utf-8"))["data"]
            title = data.get("title") or ""
            own = data.get("docNum") or ""
            text = html_to_text((d / "toanvan.html").read_text(encoding="utf-8", errors="ignore"))

            if len(text.strip()) < 60:
                counts["van_rong"] += 1
                print(f"  ! {nid}: van rong sau khi them ({d}) — bat thuong", flush=True)
                continue

            kq = resolve_relations(neo, llm, nid, data, title, text, own, log_path=LOG_PATH)
            flag = _FLAG[kq["nhanh"]]
            neo.run(f"MATCH (n:Norm {{norm_id:$id}}) SET n.{flag}=true", id=nid)
            if kq["khop"] is True:
                counts["khop"] += 1
            elif kq["khop"] is False:
                counts["mismatch"] += 1
            else:
                counts["only_llm"] += 1
        except Exception as e:
            counts["loi"] += 1
            print(f"  ! LOI {nid}: {e!r}", flush=True)

        if i % 20 == 0 or i == len(ids):
            print(f"{i}/{len(ids)} · {counts}", flush=True)

    print("XONG:", counts, flush=True)


if __name__ == "__main__":
    lim = int(sys.argv[1]) if len(sys.argv) > 1 else None
    main(limit=lim)
