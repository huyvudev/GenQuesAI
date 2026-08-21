"""CDI · resync — đồng bộ trạng thái hiệu lực từ NGUỒN, chống graph lỗi thời thầm (CDI-2; gỡ G2).

vbpl ĐỔI `effStatus` của VB cũ liên tục (bị thay thế / hết hiệu lực). Hệ thống hiện chỉ
đọc effStatus LÚC NẠP → graph dần sai. Job này: với mỗi Norm đang `ConHieuLuc` (có id vbpl),
gọi lại gateway, so `effStatus/effTo` (+ content_hash) → nếu ĐỔI: re-reconcile (đóng hiệu lực)
+ đồng bộ payload Qdrant + ghi ledger.

`diff_norm` THUẦN (test được); fetcher INJECTABLE (test bằng fake, prod dùng vbpl gateway).
Tất định, KHÔNG LLM.
"""
from __future__ import annotations
from typing import Callable

from ..graph.client import Neo4jClient

# fetcher: norm_id -> dict kiểu doc.json `data` ({effStatus:{name}, effTo, content_hash?}) hoặc None
Fetcher = Callable[[str], dict | None]


def diff_norm(current: dict, fresh: dict) -> dict:
    """So trạng thái HIỆN TẠI trong graph với dữ liệu MỚI từ nguồn. Thuần, không DB.

    current: {tinh_trang, eff_to (date|str|None), content_hash}
    fresh  : {effStatus:{name}, effTo, content_hash?}  (kiểu doc.json `data`)
    Trả: {changed, tinh_trang, eff_to, tt_changed, eff_changed, content_changed}."""
    from ..ingestion.reconcile import map_tinh_trang, _date
    new_tt = str(map_tinh_trang((fresh.get("effStatus") or {}).get("name")))
    new_eff = _date(fresh.get("effTo"))
    new_eff_s = new_eff.isoformat() if new_eff else None
    cur_eff = current.get("eff_to")
    cur_eff_s = cur_eff.isoformat() if hasattr(cur_eff, "isoformat") else (cur_eff or None)
    tt_changed = new_tt != (current.get("tinh_trang") or "")
    eff_changed = new_eff_s != cur_eff_s
    content_changed = bool(fresh.get("content_hash")) and fresh["content_hash"] != current.get("content_hash")
    return {"changed": tt_changed or eff_changed or content_changed,
            "tinh_trang": new_tt, "eff_to": new_eff_s,
            "tt_changed": tt_changed, "eff_changed": eff_changed,
            "content_changed": content_changed}


def apply_resync(neo: Neo4jClient, store, norm_id: str, diff: dict) -> dict:
    """Áp 1 thay đổi đã phát hiện: cập nhật tình trạng/eff_to; nếu hết hiệu lực toàn bộ +
    có ngày → đóng các Expression đang mở + đồng bộ payload Qdrant. Tái dùng reconcile."""
    from ..ingestion.reconcile import _UPDATE, _CLOSE, sync_vector_norm
    from ..domain import TinhTrang
    neo.run(_UPDATE, id=norm_id, tt=diff["tinh_trang"], eff_to=diff["eff_to"])
    closed = 0
    if diff["tinh_trang"] == str(TinhTrang.HetHieuLuc) and diff["eff_to"]:
        neo.run(_CLOSE, id=norm_id, d=diff["eff_to"])
        closed = 1
        if store is not None:
            sync_vector_norm(neo, store, norm_id)
    return {"norm_id": norm_id, "closed": closed, **diff}


_CANDIDATES = """
MATCH (n:Norm)
WHERE n.tinh_trang IN ['ConHieuLuc','HetHieuLucMotPhan','ChuaCoHieuLuc']
  AND n.norm_id =~ '[0-9]+'
RETURN n.norm_id AS norm_id, n.so_hieu AS so_hieu, n.tinh_trang AS tinh_trang,
       toString(n.eff_to) AS eff_to, n.content_hash AS content_hash
ORDER BY n.norm_id
"""


def resync_corpus(neo: Neo4jClient, store, fetch: Fetcher, limit: int | None = None,
                  dry_run: bool = False, log=print) -> dict:
    """Quét các Norm còn-hiệu-lực (id vbpl) → fetch nguồn → diff → áp thay đổi. Ghi ledger.
    `dry_run`: chỉ phát hiện + báo cáo, KHÔNG ghi graph/Qdrant/ledger."""
    cands = neo.run(_CANDIDATES)
    if limit:
        cands = cands[:limit]
    checked = changed = closed = errors = 0
    changes: list[dict] = []
    for i, c in enumerate(cands, 1):
        try:
            fresh = fetch(c["norm_id"])
        except Exception as e:  # noqa: BLE001 — 1 VB lỗi mạng không chặn cả mẻ
            errors += 1
            log(f"  [!] {c['so_hieu']}: fetch lỗi {type(e).__name__}")
            continue
        checked += 1
        if not fresh:
            continue
        d = diff_norm(c, fresh)
        if not d["changed"]:
            continue
        closed += 1 if (not dry_run and apply_resync(neo, store, c["norm_id"], d)["closed"]) else 0
        changed += 1
        changes.append({"so_hieu": c["so_hieu"], "tu": c["tinh_trang"], "den": d["tinh_trang"],
                        "eff_to": d["eff_to"], "content_changed": d["content_changed"]})
        log(f"  {i}/{len(cands)} {c['so_hieu']}: {c['tinh_trang']} -> {d['tinh_trang']}"
            + (f" (@ {d['eff_to']})" if d["eff_to"] else "")
            + (" [NỘI DUNG ĐỔI]" if d["content_changed"] else "")
            + (" [dry-run]" if dry_run else ""))
    run_id = None
    if not dry_run:
        from .ledger import record_run
        run_id = record_run(neo, source="vbpl", command="resync",
                            norm_ids=[c["so_hieu"] for c in changes],
                            n_ok=changed, n_fail=errors,
                            extra={"checked": checked, "closed": closed, "changes": changes})
    return {"checked": checked, "changed": changed, "closed": closed, "errors": errors,
            "changes": changes, "run_id": run_id, "dry_run": dry_run}


# ---------- Fetcher thật: vbpl gateway (best-effort; schema có thể đổi) ----------
_GATEWAY = "https://vbpl-bientap-gateway.moj.gov.vn/api/qtdc/public/doc/{id}"


def make_vbpl_fetcher(base_url: str = _GATEWAY, timeout: float = 20.0) -> Fetcher:
    """Tạo fetcher gọi gateway MOJ. Trả dict {effStatus, effTo, content_hash} hoặc None.

    Lưu ý: chỉ chạy cho Norm có norm_id là id vbpl (số). VB nạp tay (norm_id từ số hiệu)
    bị loại ở `_CANDIDATES`. Schema gateway có thể thay đổi — đọc phòng thủ."""
    import httpx

    def fetch(norm_id: str) -> dict | None:
        r = httpx.get(base_url.format(id=norm_id), timeout=timeout,
                      headers={"Accept": "application/json"})
        if r.status_code != 200:
            return None
        body = r.json()
        data = body.get("data", body) if isinstance(body, dict) else {}
        eff_status = data.get("effStatus")
        if isinstance(eff_status, str):
            eff_status = {"name": eff_status}
        return {"effStatus": eff_status or {}, "effTo": data.get("effTo")}

    return fetch
