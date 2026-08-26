"""Driver cho vong lap doi chieu canh qua chatbot luatvietnammisa.aicongvu.gov.vn.
Tach rieng khoi phan dieu khien trinh duyet: script nay CHI lo du lieu (lay lo tiep
theo tu Neo4j, dung cau hoi, parse cau tra loi, ghi log) — khong dung mcp browser.

Dung 2 lenh CLI, goi xen ke voi thao tac trinh duyet boi agent/fork dieu khien Chrome:

  python _batch_verify_driver.py next-batch --edge REPLACES --size 50
      -> in JSON {batch_file, question, count} ra stdout. Da luu manifest vao
         _batch_verify_manifests/<batch_id>.json (gom action_id theo dung thu tu
         cau hoi, de record doi chieu lai sau).

  python _batch_verify_driver.py record --batch-file <path> --answer-file <path_txt>
      -> parse cau tra loi (dang "1. Đúng" / "2) Sai" / "3 - Không rõ" moi dong,
         khong phan biet hoa thuong, chap nhan nhieu bien the dau cau), ghi vao
         _batch_verify_log.jsonl, in thong ke.

Nguon du lieu 'chua xu ly': doc TRUC TIEP tu Neo4j local (khong doc excel) —
dieu kien WHERE giong het _Q_CAN_RA / _Q_AMENDS_CAN_RA trong _xuat_ket_qua_rebuild.py
(mismatch/only_llm=true, da_duyet chua true) TRU action_id da co trong log JSONL
(bo qua, tranh hoi lai)."""
from __future__ import annotations
import argparse
import json
import sys
import uuid
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, "D:/Project/GenQuesAI")
from genquesai.legal_rag.config import get_settings
from genquesai.legal_rag.graph.client import Neo4jClient

HERE = Path(__file__).parent
LOG_PATH = HERE / "_batch_verify_log.jsonl"
MANIFEST_DIR = HERE / "_batch_verify_manifests"
MANIFEST_DIR.mkdir(exist_ok=True)

_LOAI_HOI = {
    "ThayThe": "thay thế",
    "BaiBoToanBo": "bãi bỏ toàn bộ",
    "SuaDoi": "sửa đổi/bổ sung (một phần)",
    "BaiBoTungPhan": "bãi bỏ một phần",
    "CanCu": "căn cứ vào / dựa trên",
}

_Q_REPLACES = """
MATCH (a:Action)-[:ENACTED_BY]->(src:Norm)
MATCH (a)-[:AFFECTS]->(tgt)
WHERE a.loai IN ['ThayThe','BaiBoToanBo'] AND (a.mismatch=true OR a.only_llm=true)
      AND coalesce(a.da_duyet,false)=false
      AND NOT src.so_hieu =~ '(?i).*(UBND|HĐND|HDND).*'
MATCH (tgt_norm:Norm {norm_id: tgt.norm_id})
WHERE NOT tgt_norm.so_hieu =~ '(?i).*(UBND|HĐND|HDND).*'
RETURN a.action_id AS action_id, src.so_hieu AS sh_nguon, a.loai AS loai, tgt_norm.so_hieu AS sh_dich
ORDER BY src.so_hieu, tgt_norm.so_hieu
"""
_Q_AMENDS = """
MATCH (a:Action)-[:ENACTED_BY]->(src:Norm)
MATCH (a)-[:AFFECTS]->(tgt)
WHERE a.loai IN ['SuaDoi','BaiBoTungPhan'] AND (a.mismatch=true OR a.only_llm=true)
      AND coalesce(a.da_duyet,false)=false
      AND NOT src.so_hieu =~ '(?i).*(UBND|HĐND|HDND).*'
MATCH (tgt_norm:Norm {norm_id: tgt.norm_id})
WHERE NOT tgt_norm.so_hieu =~ '(?i).*(UBND|HĐND|HDND).*'
RETURN a.action_id AS action_id, src.so_hieu AS sh_nguon, a.loai AS loai, tgt_norm.so_hieu AS sh_dich
ORDER BY src.so_hieu, tgt_norm.so_hieu
"""
_Q_GUIDED_BY = """
MATCH (a:Action)-[:ENACTED_BY]->(src:Norm)
MATCH (a)-[:AFFECTS]->(tgt)
WHERE a.loai = 'CanCu' AND (a.mismatch=true OR a.only_llm=true)
      AND coalesce(a.da_duyet,false)=false
      AND NOT src.so_hieu =~ '(?i).*(UBND|HĐND|HDND).*'
MATCH (tgt_norm:Norm {norm_id: tgt.norm_id})
WHERE NOT tgt_norm.so_hieu =~ '(?i).*(UBND|HĐND|HDND).*'
RETURN a.action_id AS action_id, src.so_hieu AS sh_nguon, a.loai AS loai, tgt_norm.so_hieu AS sh_dich
ORDER BY src.so_hieu, tgt_norm.so_hieu
"""
_QUERIES = {"REPLACES": _Q_REPLACES, "AMENDS": _Q_AMENDS, "GUIDED_BY": _Q_GUIDED_BY}


def _neo() -> Neo4jClient:
    s = get_settings()
    s_local = s.model_copy(update={
        "neo4j_uri": "bolt://localhost:7687", "neo4j_user": "neo4j",
        "neo4j_password": "123qwe", "neo4j_database": "neo4j",
    })
    neo = Neo4jClient(s_local)
    neo.verify()
    return neo


def _da_xong() -> set[str]:
    done: set[str] = set()
    if LOG_PATH.exists():
        with open(LOG_PATH, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    if rec.get("action_id"):
                        done.add(rec["action_id"])
                except Exception:
                    pass
    return done


_PREAMBLE = ("Các nhận định dưới đây đúng theo pháp luật VN không? Trả lời Đúng/Sai/Không rõ "
             "theo từng số thứ tự, không giải thích: ")
_MAX_CHARS_DEFAULT = 1850  # o so 2000 ky tu cua khung nhap tren trang — chua le


def cmd_next_batch(edge: str, size: int, max_chars: int) -> None:
    neo = _neo()
    rows = neo.run(_QUERIES[edge])
    done = _da_xong()
    remain = [r for r in rows if r["action_id"] not in done]
    if not remain:
        print(json.dumps({"done": True, "edge": edge, "message": "Hết — không còn dòng nào chưa xử lý cho edge này."}, ensure_ascii=False))
        return

    batch: list[dict] = []
    lines: list[str] = []
    total_len = len(_PREAMBLE)
    for r in remain:
        if len(batch) >= size:
            break
        hoi = _LOAI_HOI.get(r["loai"], r["loai"])
        line = f"{len(batch) + 1}) \"{r['sh_nguon']}\" {hoi} \"{r['sh_dich']}\"."
        added = len(line) + 1
        if batch and total_len + added > max_chars:
            break
        batch.append(dict(r))
        lines.append(line)
        total_len += added

    question = _PREAMBLE + " ".join(lines)
    batch_id = uuid.uuid4().hex[:12]
    manifest = {"batch_id": batch_id, "edge": edge, "action_ids": [r["action_id"] for r in batch],
                "sh_pairs": [[r["sh_nguon"], r["sh_dich"], r["loai"]] for r in batch]}
    mpath = MANIFEST_DIR / f"{batch_id}.json"
    mpath.write_text(json.dumps(manifest, ensure_ascii=False, indent=None), encoding="utf-8")

    remain_after = len(remain) - len(batch)
    print(json.dumps({
        "done": False, "edge": edge, "batch_id": batch_id, "batch_file": str(mpath),
        "count": len(batch), "chars": len(question), "remaining_after_this_batch": remain_after,
        "question": question,
    }, ensure_ascii=False))


def _chuan_hoa(v: str) -> str:
    v = v.strip().lower()
    if v.startswith(("đúng", "dung", "dúng", "đung")):
        return "dung"
    if v.startswith("sai"):
        return "sai"
    return "khong_ro"


def cmd_record(batch_file: str, answers_json: str) -> None:
    """`answers_json`: mang JSON cac chuoi verdict THEO DUNG THU TU DOM (khong phai
    so thu tu trong text — trang nay hien thi so bang CSS counter cua <ol>, KHONG
    nam trong textContent, nen phai lay theo VI TRI cac the la (leaf) chua dung
    'Sai'/'Dung'/'Khong ro' trong DOM)."""
    manifest = json.loads(Path(batch_file).read_text(encoding="utf-8"))
    action_ids = manifest["action_ids"]
    sh_pairs = manifest["sh_pairs"]
    n = len(action_ids)

    answers = json.loads(answers_json)

    ghi = 0
    thieu = []
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        for i in range(1, n + 1):
            if i - 1 < len(answers) and answers[i - 1]:
                verdict = _chuan_hoa(answers[i - 1])
                rec = {"action_id": action_ids[i - 1], "verdict": verdict,
                       "batch_id": manifest["batch_id"], "edge": manifest["edge"],
                       "sh_nguon": sh_pairs[i - 1][0], "sh_dich": sh_pairs[i - 1][1]}
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                ghi += 1
            else:
                thieu.append(i)

    counts = {"dung": 0, "sai": 0, "khong_ro": 0}
    for i in range(1, min(n, len(answers)) + 1):
        counts[_chuan_hoa(answers[i - 1])] += 1

    print(json.dumps({
        "batch_id": manifest["batch_id"], "expected": n, "parsed": ghi,
        "missing_indices": thieu, "counts": counts,
        "ok": ghi == n,
    }, ensure_ascii=False))


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    p1 = sub.add_parser("next-batch")
    p1.add_argument("--edge", required=True, choices=["REPLACES", "AMENDS", "GUIDED_BY"])
    p1.add_argument("--size", type=int, default=100)
    p1.add_argument("--max-chars", type=int, default=_MAX_CHARS_DEFAULT)

    p2 = sub.add_parser("record")
    p2.add_argument("--batch-file", required=True)
    p2.add_argument("--answers-file", required=True,
                     help="File chua JSON array cac verdict THEO THU TU DOM, vd [\"Sai\",\"Đúng\",...]")

    args = ap.parse_args()
    if args.cmd == "next-batch":
        cmd_next_batch(args.edge, args.size, args.max_chars)
    elif args.cmd == "record":
        text = Path(args.answers_file).read_text(encoding="utf-8")
        cmd_record(args.batch_file, text)


if __name__ == "__main__":
    main()
