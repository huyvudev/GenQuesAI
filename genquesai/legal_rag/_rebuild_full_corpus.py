"""REBUILD TOAN BO — chay lai consensus v3 (per-edge, sau khi da xoa sach Action ca
local lan server, 2026-08-24). Ghi vao LOCAL Neo4j (tranh downtime production trong
nhieu gio chay) — Qdrant van doc tu SERVER (day du du lieu text cho nhanh fallback,
local Qdrant chua duoc dong bo).

CHECKPOINT: moi VB xu ly xong ghi 1 dong JSONL vao `_rebuild_log.jsonl` (flush ngay,
khoa luong) — neu mat dien/mat mang giua chung, chay lai script nay se TU DONG resume
dung cho (dua vao co dong_thuan_*_done tren Norm, giong co che cu, khong xu ly lai VB
da xong). Bao cao tien do moi 100 VB vao `_rebuild_progress.log`.

Nguon van ban uu tien: file raw cuc bo (CORPUS_DIR/*/{norm_id}/doc.json+toanvan.html,
gom ca thu muc `cdi_backfill`) — neu khong co thi dung lai tu Qdrant (GIOI HAN: khong
co doan "Can cu...", GUIDED_BY han che — nguoi dung da chap nhan, xem
_TIEN_DO_XU_LY.md)."""
from __future__ import annotations
import json
import sys
import threading
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, "D:/Project/GenQuesAI")

from genquesai.legal_rag.config import get_settings
from genquesai.legal_rag.graph.client import Neo4jClient
from genquesai.legal_rag.agent.llm import LLM
from genquesai.legal_rag.ingestion.consensus import resolve_relations, _FLAG
from genquesai.legal_rag.ingestion.reference_extractor import html_to_text
from qdrant_client import QdrantClient

HERE = Path(__file__).parent
LOG_PATH = HERE / "_rebuild_log.jsonl"
PROGRESS_PATH = HERE / "_rebuild_progress.log"

_V3 = ("(coalesce(n.dong_thuan_meta_done,false) OR coalesce(n.dong_thuan_regex_done,false) "
      "OR coalesce(n.dong_thuan_llm_done,false))")


def _progress(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}"
    print(line, flush=True)
    with open(PROGRESS_PATH, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def build_local_file_index(corpus_dir: Path) -> dict[str, Path]:
    """norm_id -> thu muc chua doc.json+toanvan.html, quet toan bo CORPUS_DIR/*/*."""
    idx: dict[str, Path] = {}
    for p in corpus_dir.glob("*/*/doc.json"):
        d = p.parent
        if (d / "toanvan.html").exists():
            idx[d.name] = d
    return idx


def build_text_from_qdrant(q: QdrantClient, collection: str, norm_id: str) -> str:
    import re
    dieu_num_re = re.compile(r"^Dieu\s+(\d+)$", re.IGNORECASE)

    def sort_key(dd: str):
        m = dieu_num_re.match((dd or "").strip())
        return (0, int(m.group(1))) if m else (1, dd or "")

    def header(dd: str) -> str:
        m = dieu_num_re.match((dd or "").strip())
        if m:
            return f"Điều {m.group(1)}."
        if (dd or "").lower().startswith("phuluc"):
            return "Phụ lục " + dd[len("PhuLuc"):].strip()
        return dd or ""

    flt = {"must": [{"key": "norm_id", "match": {"value": norm_id}}]}
    pts, off = q.scroll(collection, scroll_filter=flt, limit=200,
                        with_payload=["duong_dan", "tieu_de", "text", "part"], with_vectors=False)
    all_pts = list(pts)
    while off:
        pts, off = q.scroll(collection, scroll_filter=flt, limit=200, offset=off,
                            with_payload=["duong_dan", "tieu_de", "text", "part"], with_vectors=False)
        all_pts.extend(pts)
    groups: dict[str, dict] = {}
    for p in all_pts:
        pl = p.payload or {}
        dd = pl.get("duong_dan") or ""
        g = groups.setdefault(dd, {"tieu_de": pl.get("tieu_de") or "", "parts": {}})
        g["parts"][pl.get("part") or 0] = pl.get("text") or ""
    ordered = sorted(groups.items(), key=lambda kv: sort_key(kv[0]))
    out = []
    for dd, g in ordered:
        body = " ".join(g["parts"][k] for k in sorted(g["parts"]))
        out.append(f"{header(dd)} {g['tieu_de']}\n{body}")
    return "\n\n".join(out)


def main(limit: int | None = None, workers: int = 10) -> None:
    s = get_settings()
    s_local = s.model_copy(update={
        "neo4j_uri": "bolt://localhost:7687", "neo4j_user": "neo4j",
        "neo4j_password": "123qwe", "neo4j_database": "neo4j",
    })
    neo = Neo4jClient(s_local)
    neo.verify()
    llm = LLM(settings=s)
    q = QdrantClient(url=s.qdrant_url, api_key=s.qdrant_api_key or None, timeout=60,
                     check_compatibility=False)

    corpus_dir = Path(s.corpus_dir)
    _progress(f"Dang quet file raw cuc bo tu {corpus_dir} ...")
    local_idx = build_local_file_index(corpus_dir)
    _progress(f"  -> {len(local_idx):,} VB co file raw cuc bo")

    rows = neo.run(f"MATCH (n:Norm) WHERE NOT {_V3} RETURN n.norm_id AS id, n.so_hieu AS sh, n.tieu_de AS td")
    tong_con_lai = neo.run("MATCH (n:Norm) RETURN count(n) AS n")[0]["n"]
    da_xong = tong_con_lai - len(rows)
    _progress(f"Tong {tong_con_lai:,} VB · da xong (resume) {da_xong:,} · con lai {len(rows):,}")
    if limit:
        rows = rows[:limit]
        _progress(f"  (--limit {limit}, chi xu ly {len(rows)} VB dau)")

    counts = {"tu_file": 0, "tu_qdrant": 0, "rong": 0, "loi": 0,
             "A": 0, "B": 0, "C": 0, "khop": 0, "mismatch": 0, "only_llm": 0}
    lock = threading.Lock()
    n_proc = 0

    def _viec(row) -> None:
        nonlocal n_proc
        nid, sh, td = row["id"], row["sh"], row["td"]
        try:
            d = local_idx.get(nid)
            if d is not None:
                data = json.loads((d / "doc.json").read_text(encoding="utf-8"))["data"]
                title = data.get("title") or td or ""
                own = data.get("docNum") or sh
                text = html_to_text((d / "toanvan.html").read_text(encoding="utf-8", errors="ignore"))
                nguon_text = "file"
            else:
                data = {}
                title, own = td or "", sh
                text = build_text_from_qdrant(q, s.qdrant_collection, nid)
                nguon_text = "qdrant"

            if len(text.strip()) < 60:
                with lock:
                    counts["rong"] += 1
                return

            kq = resolve_relations(neo, llm, nid, data, title, text, own, log_path=LOG_PATH)
            flag = _FLAG[kq["nhanh"]]
            neo.run(f"MATCH (n:Norm {{norm_id:$id}}) SET n.{flag}=true", id=nid)

            with lock:
                counts["tu_file" if nguon_text == "file" else "tu_qdrant"] += 1
                counts[kq["nhanh"]] += 1
                if kq["khop"] is True:
                    counts["khop"] += 1
                elif kq["khop"] is False:
                    counts["mismatch"] += 1
                else:
                    counts["only_llm"] += 1
                n_proc += 1
                if n_proc % 100 == 0:
                    _progress(f"{n_proc}/{len(rows)} · file={counts['tu_file']} qdrant={counts['tu_qdrant']} · "
                             f"A={counts['A']}/B={counts['B']}/C={counts['C']} · "
                             f"khop={counts['khop']} lech={counts['mismatch']} chi-LLM={counts['only_llm']} · "
                             f"rong={counts['rong']} loi={counts['loi']}")
        except Exception as e:
            with lock:
                counts["loi"] += 1
            _progress(f"  ! LOI {nid}: {e!r}")

    _progress(f"Bat dau xu ly {len(rows)} VB, workers={workers} ...")
    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(_viec, rows))

    _progress(f"XONG: {counts}")


if __name__ == "__main__":
    lim = int(sys.argv[1]) if len(sys.argv) > 1 else None
    wk = int(sys.argv[2]) if len(sys.argv) > 2 else 10
    main(limit=lim, workers=wk)
