"""Đồng thuận đa nguồn (metadata + regex + LLM) — dò REPLACES/AMENDS/GUIDED_BY.

Quy tắc đầy đủ: xem `../rule.md` (mục 0.1, 2, 5, 6, 7 — v3). Tóm tắt:

- 3 nguồn NGANG HÀNG, LLM luôn chạy (không còn là lớp tuỳ chọn):
  metadata (`referenceType` trong `doc.json`) · regex (`reference_extractor.py`,
  tiêu đề cho REPLACES/AMENDS + đoạn "Căn cứ..." cho GUIDED_BY) · LLM (luôn chạy).
- Nhánh A (có metadata): so 2-3 nguồn (metadata + regex? + llm) — khớp hết mới duyệt.
- Nhánh B (không metadata, có regex): so regex vs llm — khớp mới duyệt.
- Nhánh C (không metadata, không regex): chỉ LLM — không đối chiếu được, không tự duyệt.
- `reconcile.py::reconcile_corpus` (chạy lúc `ingest`) đã tạo Action từ metadata với
  chính sách RIÊNG của nó (`source IS NULL`) — module này KHÔNG tạo Action trùng cho
  nhánh A, mà đọc lại Action đã có rồi cập nhật field đồng thuận + `da_duyet`.

Phần thuần (`extract_metadata_relations`, `dong_thuan`) tách khỏi phần chạm DB
(`resolve_relations`, `process_corpus`) để test không cần Neo4j.
"""
from __future__ import annotations
import json
import re
from pathlib import Path

from ..graph.client import Neo4jClient
from .reconcile import REL_MAP
from .reference_extractor import (
    _LLM_SYS, _norm_sh, extract_guided_by, extract_references_llm, extract_title_relations,
)

Quan_He = tuple[str, str, str]   # (loai, edge, target_so_hieu)


def extract_metadata_relations(data: dict) -> list[Quan_He]:
    """Nhánh metadata: `referenceType` trong `doc.json` -> [(loai, edge, so_hieu)].
    Dùng `targetDocument.docNum` (đã xác nhận có sẵn trong dữ liệu thật — không cần
    tra DB). Tái dùng `REL_MAP` của `reconcile.py` — một nguồn map, không viết lại."""
    out: list[Quan_He] = []
    for ref in (data.get("references") or []):
        rt = ref.get("referenceType")
        if rt not in REL_MAP:
            continue
        tsh = (ref.get("targetDocument") or {}).get("docNum")
        if not tsh:
            continue
        loai, edge = REL_MAP[rt]
        out.append((loai, edge, _norm_sh(tsh)))
    return out


def _as_pairs(refs: list[Quan_He]) -> set[tuple[str, str]]:
    return {(edge, target) for _, edge, target in refs}


def dong_thuan(metadata: list[Quan_He] | None, regex: list[Quan_He] | None,
               llm: list[Quan_He]) -> dict:
    """So khớp đa nguồn (rule.md mục 2). `metadata`/`regex` = None nghĩa là KHÔNG khả
    dụng (khác rỗng `[]` = khả dụng nhưng không tìm thấy gì). `llm` luôn là list (có
    thể rỗng — LLM chạy nhưng không thấy quan hệ nào).

    Trả {"nhanh": "A"|"B"|"C", "khop": bool|None, "metadata": set|None,
         "regex": set|None, "llm": set}. `khop=None` chỉ ở nhánh C (không có gì đối
    chiếu — không phải "khớp" hay "lệch", mà là "không đối chiếu được")."""
    llm_p = _as_pairs(llm)
    if metadata is not None:
        meta_p = _as_pairs(metadata)
        if regex is not None:
            regex_p = _as_pairs(regex)
            khop = meta_p == regex_p == llm_p
            return {"nhanh": "A", "khop": khop, "metadata": meta_p, "regex": regex_p, "llm": llm_p}
        khop = meta_p == llm_p
        return {"nhanh": "A", "khop": khop, "metadata": meta_p, "regex": None, "llm": llm_p}
    if regex is not None:
        regex_p = _as_pairs(regex)
        khop = regex_p == llm_p
        return {"nhanh": "B", "khop": khop, "metadata": None, "regex": regex_p, "llm": llm_p}
    return {"nhanh": "C", "khop": None, "metadata": None, "regex": None, "llm": llm_p}


# ── DB: nhánh A — cập nhật Action đã có (do reconcile.py tạo, source IS NULL) ──────
_FIND_META_ACTIONS = """
MATCH (a:Action)-[:ENACTED_BY]->(:Norm {norm_id:$id})
WHERE a.source IS NULL
RETURN a.action_id AS action_id
"""
_UPDATE_CONSENSUS = """
MATCH (a:Action {action_id:$aid})
SET a.nguon_metadata=$meta, a.nguon_regex=$regex, a.nguon_llm=$llm,
    a.mismatch=$mismatch, a.only_llm=$only_llm, a.da_duyet=$duyet
"""


def _ghi_ket_qua_dong_thuan(neo: Neo4jClient, norm_id: str, kq: dict, source: str) -> dict:
    """Ghi kết quả `dong_thuan` vào graph. Nhánh A: UPDATE Action đã có (không tạo
    trùng — rule.md mục 0.1). Nhánh B/C: TẠO Action mới (không có gì để update)."""
    meta_j = json.dumps(sorted(kq["metadata"]), ensure_ascii=False) if kq["metadata"] is not None else None
    regex_j = json.dumps(sorted(kq["regex"]), ensure_ascii=False) if kq["regex"] is not None else None
    llm_j = json.dumps(sorted(kq["llm"]), ensure_ascii=False)
    mismatch = kq["khop"] is False
    only_llm = kq["nhanh"] == "C"
    duyet = bool(kq["khop"])   # None (nhánh C) -> False; True/False giữ nguyên

    if kq["nhanh"] == "A":
        aids = [r["action_id"] for r in neo.run(_FIND_META_ACTIONS, id=norm_id)]
        for aid in aids:
            neo.run(_UPDATE_CONSENSUS, aid=aid, meta=meta_j, regex=regex_j, llm=llm_j,
                   mismatch=mismatch, only_llm=only_llm, duyet=duyet)
        return {"nhanh": "A", "actions_updated": len(aids), "khop": kq["khop"]}

    # Nhánh B/C: chưa có Action nào — tạo mới từ nguồn "đáng tin nhất khả dụng"
    # (regex ở nhánh B, llm ở nhánh C — rule.md mục 5.1/5.2 không chỉ định 1 nguồn
    # "thắng" khi lệch, chỉ chỉ định AI ĐƯỢC HIỂN THỊ MẶC ĐỊNH khi cần tạo cạnh).
    candidate_pairs = kq["regex"] if kq["nhanh"] == "B" else kq["llm"]
    n_created = 0
    for edge, target in candidate_pairs:
        loai = {"REPLACES": "ThayThe", "AMENDS": "SuaDoi", "GUIDED_BY": "CanCu"}[edge]
        conf = 0.85 if edge in ("REPLACES", "AMENDS") else 0.6
        rows = neo.run(
            f"""
            MATCH (src:Norm {{norm_id:$sid}}), (tgt:Norm {{so_hieu:$tsh}})
            WHERE src <> tgt
            MERGE (a:Action {{action_id:$aid}})
              SET a.loai=$loai, a.confidence=$conf, a.da_duyet=$duyet, a.enacted_by=$sid,
                  a.ngay_hieu_luc=src.ngay_hieu_luc, a.source=$source,
                  a.nguon_metadata=$meta, a.nguon_regex=$regex, a.nguon_llm=$llm,
                  a.mismatch=$mismatch, a.only_llm=$only_llm
            MERGE (a)-[:ENACTED_BY]->(src)
            MERGE (a)-[:AFFECTS]->(tgt)
            MERGE (src)-[:{edge}]->(tgt)
            RETURN 1
            """, sid=norm_id, tsh=target, aid=f"{norm_id}->{target}:{edge}:{source}",
            loai=loai, conf=conf, duyet=duyet, source=source,
            meta=meta_j, regex=regex_j, llm=llm_j, mismatch=mismatch, only_llm=only_llm)
        if rows:
            n_created += 1
    return {"nhanh": kq["nhanh"], "actions_created": n_created, "khop": kq["khop"]}


def resolve_relations(neo: Neo4jClient, llm_client, norm_id: str, data: dict,
                      title: str, text: str, own_so_hieu: str | None) -> dict:
    """Xử lý 1 VB theo luồng v3 (rule.md mục 0.1): xác định nhánh A/B/C, gọi LLM đúng
    input theo nhánh, đối chiếu, ghi kết quả. `llm_client` bắt buộc (khác
    `reference_extractor.extract_corpus_references` — ở đây LLM LUÔN chạy)."""
    meta = extract_metadata_relations(data)
    regex = extract_title_relations(title, own_so_hieu) + extract_guided_by(
        text, own_so_hieu, exclude={s for _, _, s in extract_title_relations(title, own_so_hieu)})

    meta_arg = meta if meta else None
    regex_arg = regex if regex else None

    if meta_arg is not None or regex_arg is not None:
        # Nhánh A/B — LLM chỉ cần tiêu đề + preamble (mục 5.1), có nguồn khác để đối chiếu.
        i = _norm_sh(text).find("Điều 1")
        preamble = _norm_sh(text)[:i] if i > 0 else _norm_sh(text)[:3500]
        llm_refs = extract_references_llm(llm_client, title, preamble, own_so_hieu)
    else:
        # Nhánh C — LLM là nguồn duy nhất, đọc TOÀN VĂN (mục 5.2), không giới hạn preamble.
        llm_refs = extract_references_llm(llm_client, title, _norm_sh(text)[:12000], own_so_hieu)

    kq = dong_thuan(meta_arg, regex_arg, llm_refs)
    ghi = _ghi_ket_qua_dong_thuan(neo, norm_id, kq, source="llm")
    return {**kq, **ghi}


def process_corpus(neo: Neo4jClient, llm_client, base: Path, src_dirs: list[str],
                   resume: bool = True, log=print) -> dict:
    """Quét raw dirs, chạy `resolve_relations` theo luồng v3 cho từng VB. Resume qua
    3 flag riêng theo nhánh (rule.md mục 8) — mỗi VB chỉ rơi vào đúng 1 nhánh nên chỉ
    1 flag/VB được set, nhưng kiểm tra cả 3 để coi là "đã xong"."""
    doc_dirs = sorted({p.parent for sub in src_dirs for p in base.glob(f"{sub}/*/doc.json")})
    counts = {"A": 0, "B": 0, "C": 0, "khop": 0, "mismatch": 0, "only_llm": 0}
    n_proc = 0
    done: set[str] = set()
    if resume:
        for flag in ("refs_meta_done", "refs_regex_done", "refs_llm_done"):
            done |= {r["id"] for r in neo.run(f"MATCH (n:Norm) WHERE n.{flag}=true RETURN n.norm_id AS id")}
    for d in doc_dirs:
        tv = d / "toanvan.html"
        if not tv.exists() or d.name in done:
            continue
        try:
            data = json.loads((d / "doc.json").read_text(encoding="utf-8"))["data"]
        except Exception:
            continue
        title, own = data.get("title") or "", data.get("docNum")
        text = re.sub(r"<[^>]+>", " ", tv.read_text(encoding="utf-8", errors="ignore"))
        kq = resolve_relations(neo, llm_client, d.name, data, title, text, own)
        flag = {"A": "refs_meta_done", "B": "refs_regex_done", "C": "refs_llm_done"}[kq["nhanh"]]
        neo.run(f"MATCH (n:Norm {{norm_id:$id}}) SET n.{flag}=true", id=d.name)
        counts[kq["nhanh"]] += 1
        if kq["khop"] is True:
            counts["khop"] += 1
        elif kq["khop"] is False:
            counts["mismatch"] += 1
        else:
            counts["only_llm"] += 1
        n_proc += 1
        if n_proc % 100 == 0:
            log(f"  {n_proc} VB · nhánh A={counts['A']}/B={counts['B']}/C={counts['C']} · "
                f"khớp={counts['khop']} lệch={counts['mismatch']} chỉ-LLM={counts['only_llm']}")
    return {"processed": n_proc, **counts}
