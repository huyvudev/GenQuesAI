"""CLI legal_rag (bản clone CDI trong GenQuesAI): python -m legal_rag {init-db|health|ingest|embed|pit|refs|cdi}

Rút gọn từ Chatbot-Law/chatbot/legal_rag/cli.py — chỉ giữ các lệnh mà module đã clone
hỗ trợ (không có review/approve, ocr — thuộc §10 AV, không được mang theo). Xem
legal_rag/__init__.py để biết phạm vi clone. Quy tắc dò quan hệ (`refs`): xem `rule.md`.
"""
from __future__ import annotations
import argparse
import logging
from datetime import date
from pathlib import Path

from .config import get_settings
from .graph import Neo4jClient
from .graph.schema import init_schema
from .graph.ingest import ingest_norm
from .graph.queries import point_in_time, norm_summary
from .ingestion.loader import load_norm
from .retrieval import QdrantStore


def cmd_init_db(args) -> int:
    s = get_settings()
    print(f"Neo4j: {s.neo4j_uri} | Qdrant: {s.qdrant_url}")
    with Neo4jClient(s) as c:
        c.verify()
        res = init_schema(c)
        print(f"✓ Neo4j schema: {res['constraints']} constraints, {res['indexes']} indexes")
    q = QdrantStore(s)
    created = q.ensure_collection(recreate=args.recreate)
    print(f"✓ Qdrant collection '{q.collection}': {'vừa tạo' if created else 'đã có'} | {q.info()}")
    q.close()
    print("✓ init-db xong.")
    return 0


def cmd_health(args) -> int:
    s = get_settings()
    ok = True
    try:
        with Neo4jClient(s) as c:
            c.verify()
        print("✓ Neo4j: UP")
    except Exception as e:  # noqa: BLE001
        ok = False
        print(f"✗ Neo4j: DOWN — {e}")
    try:
        q = QdrantStore(s)
        print(f"✓ Qdrant: UP | collection '{q.collection}' tồn tại: {q.exists()}")
        q.close()
    except Exception as e:  # noqa: BLE001
        ok = False
        print(f"✗ Qdrant: DOWN — {e}")
    return 0 if ok else 1


def cmd_ingest(args) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    s = get_settings()
    base = Path(args.corpus or s.corpus_dir)
    srcs = args.src or ["*"]
    doc_dirs = sorted({p.parent for sub in srcs for p in base.glob(f"{sub}/*/doc.json")})
    if args.limit:
        doc_dirs = doc_dirs[: args.limit]
    from .cdi import validate
    gate = not args.no_gate
    print(f"Ingest {len(doc_dirs)} VB từ {base} (src={srcs})" + ("" if gate else " [GATE TẮT]"))
    n_norm = n_comp = skip = fail = 0
    quarantine: list[str] = []
    with Neo4jClient(s) as c:
        c.verify()
        for i, d in enumerate(doc_dirs, 1):
            loaded = load_norm(d)
            if not loaded:
                skip += 1
                continue
            norm, comps = loaded
            if gate:  # CDI validation gate — chặn VB rác (0 Điều/ngày sai/số hiệu lệch)
                rep = validate(norm, comps)
                if not rep.ok:
                    fail += 1
                    quarantine.append(f"{norm.so_hieu}: {'; '.join(rep.errors)}")
                    continue
            n_comp += ingest_norm(c, norm, comps)
            n_norm += 1
            if i % 100 == 0 or i == len(doc_dirs):
                print(f"  {i}/{len(doc_dirs)} | norm={n_norm} component={n_comp} skip={skip} fail={fail}")
    print(f"✓ ingest xong: {n_norm} Norm, {n_comp} Component, bỏ {skip} (không text), "
          f"FAIL gate {fail}.")
    if quarantine:
        print("  Quarantine (FAIL gate):")
        for q in quarantine[:20]:
            print(f"    - {q}")
    return 0


def cmd_pit(args) -> int:
    s = get_settings()
    at = date.fromisoformat(args.date) if args.date else date.today()
    with Neo4jClient(s) as c:
        for r in norm_summary(c, args.so_hieu):
            print(f"VB: {r['tieu_de']} | loại={r['loai']} | hiệu lực {r['hieu_luc']} | {r['so_component']} component")
        rows = point_in_time(c, args.so_hieu, at, args.duong_dan)
    print(f"\n— Nội dung {args.so_hieu} tính đến ngày {at} — {len(rows)} mục —")
    for r in rows[: args.n]:
        head = f"  [{r['dieu_khoan']}] {r['tieu_de'] or ''}".rstrip()
        print(head)
        if r["noi_dung"]:
            print(f"      {r['noi_dung'][:200].replace(chr(10), ' ')}")
    return 0


def cmd_embed(args) -> int:
    import time
    from .retrieval.embedder import Embedder
    from .retrieval.index import embed_corpus
    s = get_settings()
    store = QdrantStore(s)
    store.ensure_collection(recreate=args.recreate)
    emb = Embedder(s.embed_model, device=args.device, max_length=s.embed_max_length)
    print(f"Embedder: {s.embed_model} | device={emb.device} | batch={args.batch}"
          + (f" | limit={args.limit}" if args.limit else ""))
    t0 = time.time()
    with Neo4jClient(s) as c:
        n = embed_corpus(c, store, emb, batch=args.batch, limit=args.limit,
                         skip_existing=args.resume,
                         window_chars=s.embed_window_chars, window_overlap=s.embed_window_overlap)
    store.close()
    dt = time.time() - t0
    print(f"✓ embed xong: {n} point trong {dt:.0f}s ({n/max(dt,1):.1f}/s)")
    return 0


def cmd_refs(args) -> int:
    """Dò quan hệ REPLACES/AMENDS/GUIDED_BY — rule.md.

    Mặc định: regex + LLM tuỳ chọn (`--llm`), không đối chiếu metadata (v1).
    `--consensus`: luồng v3 — metadata + regex + LLM ĐỒNG THUẬN đa nguồn (rule.md
    mục 0.1/2), LLM LUÔN chạy (không cần `--llm`), duyệt tự động chỉ khi các nguồn
    khả dụng khớp nhau."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    s = get_settings()
    base = Path(args.corpus or s.corpus_dir)
    srcs = args.src or ["*"]

    if args.consensus:
        from .agent.llm import LLM
        from .ingestion.consensus import process_corpus
        llm = LLM(settings=s)
        with Neo4jClient(s) as c:
            c.verify()
            res = process_corpus(c, llm, base, srcs, resume=not args.no_resume, limit=args.limit,
                                 workers=args.workers)
        print(f"✓ refs --consensus xong: {res['processed']} VB · "
              f"nhánh A={res['A']}/B={res['B']}/C={res['C']} · "
              f"khớp={res['khop']} · lệch={res['mismatch']} (cần rà) · "
              f"chỉ-LLM={res['only_llm']} (cần rà)")
        return 0

    from .ingestion.reference_extractor import extract_corpus_references
    llm = None
    if args.llm:
        from .agent.llm import LLM
        llm = LLM(settings=s)
    with Neo4jClient(s) as c:
        c.verify()
        res = extract_corpus_references(c, base, srcs, llm=llm, resume=not args.no_resume,
                                        pace_seconds=args.pace)
    print(f"✓ refs xong: {res['norm']} VB có cạnh mới · "
          f"{res['REPLACES']}R/{res['AMENDS']}A/{res['GUIDED_BY']}G"
          + (" [LLM]" if llm else " [chỉ regex]"))
    return 0


def _print_status(st: dict) -> None:
    print(f"VB (Norm): {st['norms']} · published {st['published']} / unpublished {st['unpublished']}")
    print("  tình trạng: " + " · ".join(f"{k}={v}" for k, v in sorted(st["by_tinh_trang"].items())))
    ch = st["content_hash_coverage"]
    print(f"  content_hash: {ch['hashed']}/{ch['total']} ({ch['pct']}%)")
    if "consistency" in st:
        c = st["consistency"]
        flag = "✓ khớp" if c["ok"] else f"⚠ thiếu vector {c['n_missing_vectors']} · mồ côi {c['n_orphan_vectors']}"
        print(f"  Neo4j↔Qdrant: {c['n_graph_embeddable']} VB có nội dung · {c['n_qdrant_norms']} VB có vector → {flag}")
        if c["missing_vectors"]:
            print(f"    thiếu vector (≤10): {', '.join(c['missing_vectors'][:10])}")
        if c["orphan_vectors"]:
            print(f"    vector mồ côi (≤10): {', '.join(c['orphan_vectors'][:10])}")
    if st["ledger_runs"]:
        print("  Ledger (gần nhất):")
        for r in st["ledger_runs"]:
            print(f"    {r['ts'][:19]} | {r['command']:<16} src={r['source']:<8} "
                  f"ok={r['n_ok']} fail={r['n_fail']} dup={r['n_dup']} warn={r['n_warn']}")


def cmd_cdi_status(args) -> int:
    from .cdi.status import cdi_status
    s = get_settings()
    store = None
    try:
        store = QdrantStore(s)
        if not store.exists():
            store.close(); store = None
    except Exception:  # noqa: BLE001
        store = None
    with Neo4jClient(s) as c:
        st = cdi_status(c, store, runs=args.runs)
    if store:
        store.close()
    _print_status(st)
    return 0


def cmd_cdi_runs(args) -> int:
    from .cdi.ledger import list_runs, get_run
    import json
    s = get_settings()
    with Neo4jClient(s) as c:
        if args.run_id:
            r = get_run(c, args.run_id)
            if not r:
                print(f"Không thấy run {args.run_id}"); return 1
            print(json.dumps(r, ensure_ascii=False, indent=2))
            return 0
        runs = list_runs(c, args.limit)
    print(f"— {len(runs)} lần nạp/đồng bộ gần nhất —")
    for r in runs:
        print(f"  {r['run_id']} | {r['ts'][:19]} | {r['command']:<16} src={r['source']:<8} "
              f"ok={r['n_ok']} fail={r['n_fail']} dup={r['n_dup']} warn={r['n_warn']} ({r['n_norm']} VB)")
    return 0


def cmd_cdi_resync(args) -> int:
    import logging
    from .cdi.resync import resync_corpus, make_vbpl_fetcher
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    s = get_settings()
    fetch = make_vbpl_fetcher()
    store = None if args.dry_run else QdrantStore(s)
    with Neo4jClient(s) as c:
        res = resync_corpus(c, store, fetch, limit=args.limit, dry_run=args.dry_run)
    if store:
        store.close()
    print(f"✓ resync{' (dry-run)' if args.dry_run else ''}: kiểm {res['checked']} VB · "
          f"đổi {res['changed']} · đóng hiệu lực {res['closed']} · lỗi fetch {res['errors']}")
    return 0


def cmd_cdi_undo(args) -> int:
    from .cdi.undo import undo_import
    s = get_settings()
    if not args.yes:
        print(f"⚠ Sẽ GỠ SẠCH {args.norm_id} khỏi graph + Qdrant. Thêm --yes để xác nhận.")
        return 1
    base = Path(args.corpus or s.corpus_dir)
    raw = next(iter(base.glob(f"*/{args.norm_id}")), None)
    store = QdrantStore(s)
    with Neo4jClient(s) as c:
        res = undo_import(c, store, args.norm_id, raw_dir=raw)
    store.close()
    if not res["found"]:
        print(f"Không thấy VB {args.norm_id}"); return 1
    print(f"✓ undo {args.norm_id}: gỡ {res['component']} Component · {res['expression']} Expression · "
          f"{res['action']} Action · {res['transition']} TransitionRule · {res['points']} point Qdrant"
          + (" · raw dir" if res["raw_removed"] else "") + f" (run {res['run_id']})")
    return 0


def cmd_cdi_verify(args) -> int:
    from .cdi.undo import consistency_check
    s = get_settings()
    store = QdrantStore(s)
    with Neo4jClient(s) as c:
        res = consistency_check(c, store)
    store.close()
    flag = "✓ KHỚP" if res["ok"] else "⚠ LỆCH"
    print(f"{flag} | Neo4j {res['n_graph_embeddable']} VB có nội dung · Qdrant {res['n_qdrant_norms']} VB có vector")
    print(f"  thiếu vector: {res['n_missing_vectors']} (published-mà-thiếu: {res['n_published_no_vector']})")
    print(f"  vector mồ côi: {res['n_orphan_vectors']}")
    for nid in res["missing_vectors"][:20]:
        print(f"    - thiếu: {nid}")
    for nid in res["orphan_vectors"][:20]:
        print(f"    - mồ côi: {nid}")
    return 0 if res["ok"] else 1


def cmd_cdi_watch(args) -> int:
    import logging
    from .cdi.watch import watch_folder
    from .cdi.pipeline import ingest_pdfs
    from .retrieval.embedder import Embedder
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    s = get_settings()
    base = Path(args.corpus or s.corpus_dir)
    store = QdrantStore(s); emb = Embedder(s.embed_model, device=args.device)
    with Neo4jClient(s) as c:
        handler = lambda inbox: ingest_pdfs(inbox, c, store, emb, base,
                                            corpus_sub=args.sub, source="watch")
        watch_folder(args.inbox, handler, poll_interval=args.poll)
    store.close()
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="legal_rag", description="legal_rag (clone CDI trong GenQuesAI)")
    sub = p.add_subparsers(dest="cmd", required=True)

    pi = sub.add_parser("init-db", help="tạo schema Neo4j + collection Qdrant")
    pi.add_argument("--recreate", action="store_true", help="xóa & tạo lại collection Qdrant")
    pi.set_defaults(func=cmd_init_db)

    ph = sub.add_parser("health", help="kiểm tra kết nối Neo4j + Qdrant")
    ph.set_defaults(func=cmd_health)

    pg = sub.add_parser("ingest", help="đẩy corpus raw vào Neo4j (Norm/Component/Expression)")
    pg.add_argument("--corpus", default=None, help="thư mục gốc (mặc định CORPUS_DIR)")
    pg.add_argument("--src", nargs="+", default=None, help="corpus con (mặc định tất cả)")
    pg.add_argument("--limit", type=int, default=None)
    pg.add_argument("--no-gate", action="store_true", dest="no_gate",
                    help="tắt CDI validation gate (nạp cả VB lỗi 0 Điều/ngày sai)")
    pg.set_defaults(func=cmd_ingest)

    pp = sub.add_parser("pit", help="point-in-time: nội dung VB tại 1 ngày")
    pp.add_argument("--so-hieu", required=True, dest="so_hieu")
    pp.add_argument("--date", default=None, help="YYYY-MM-DD (mặc định hôm nay)")
    pp.add_argument("--duong-dan", default=None, dest="duong_dan", help='vd "Dieu 1"')
    pp.add_argument("--n", type=int, default=20)
    pp.set_defaults(func=cmd_pit)

    pe = sub.add_parser("embed", help="nhúng Component/Expression -> Qdrant (bge-m3)")
    pe.add_argument("--limit", type=int, default=None, help="số point tối đa (validate)")
    pe.add_argument("--batch", type=int, default=128)
    pe.add_argument("--device", default=None, help="mps|cpu|cuda (mặc định auto)")
    pe.add_argument("--recreate", action="store_true", help="xóa & tạo lại collection")
    pe.add_argument("--resume", action="store_true", help="bỏ qua Điều đã embed (resumable)")
    pe.set_defaults(func=cmd_embed)

    pr = sub.add_parser("refs", help="dò quan hệ REPLACES/AMENDS/GUIDED_BY (regex + LLM tuỳ chọn, xem rule.md)")
    pr.add_argument("--corpus", default=None, help="thư mục gốc (mặc định CORPUS_DIR)")
    pr.add_argument("--src", nargs="+", default=None, help="corpus con (mặc định tất cả)")
    pr.add_argument("--llm", action="store_true",
                    help="bật LLM cho VB có từ khoá sửa/thay/bãi bỏ ở tiêu đề (vá OCR + phân loại đúng hơn)")
    pr.add_argument("--consensus", action="store_true",
                    help="luồng v3: metadata+regex+LLM đồng thuận đa nguồn (rule.md §0.1) — LLM LUÔN chạy, bỏ qua --llm/--pace")
    pr.add_argument("--no-resume", action="store_true", dest="no_resume",
                    help="xử lý lại cả VB đã có flag refs_*_done (mặc định bỏ qua)")
    pr.add_argument("--pace", type=float, default=0.0, help="giây nghỉ giữa các lượt LLM (chỉ áp dụng khi KHÔNG --consensus)")
    pr.add_argument("--limit", type=int, default=None, help="chỉ xử lý N VB đầu tiên (test nhỏ trước khi chạy full corpus)")
    pr.add_argument("--workers", type=int, default=1,
                    help="số luồng chạy song song (chỉ áp dụng với --consensus — mặc định 1 = tuần tự)")
    pr.set_defaults(func=cmd_refs)

    # CDI — Continuous Document Integration (backbone.md §9)
    pcdi = sub.add_parser("cdi", help="tích hợp văn bản liên tục (status/runs/resync/undo/verify/watch)")
    cdisub = pcdi.add_subparsers(dest="cdi_cmd", required=True)
    c_st = cdisub.add_parser("status", help="tổng quan: counts + ledger + đối soát 2 kho")
    c_st.add_argument("--runs", type=int, default=5, help="số dòng ledger gần nhất")
    c_st.set_defaults(func=cmd_cdi_status)
    c_rn = cdisub.add_parser("runs", help="lịch sử nạp/đồng bộ (ledger)")
    c_rn.add_argument("--limit", type=int, default=20)
    c_rn.add_argument("--run-id", default=None, dest="run_id", help="xem chi tiết 1 run (JSON)")
    c_rn.set_defaults(func=cmd_cdi_runs)
    c_rs = cdisub.add_parser("resync", help="đồng bộ effStatus từ vbpl (chống graph lỗi thời, G2)")
    c_rs.add_argument("--limit", type=int, default=None)
    c_rs.add_argument("--dry-run", action="store_true", dest="dry_run", help="chỉ báo cáo, không ghi")
    c_rs.set_defaults(func=cmd_cdi_resync)
    c_un = cdisub.add_parser("undo", help="gỡ sạch 1 VB khỏi graph + Qdrant (+raw)")
    c_un.add_argument("norm_id")
    c_un.add_argument("--corpus", default=None)
    c_un.add_argument("--yes", action="store_true", help="xác nhận gỡ (bắt buộc)")
    c_un.set_defaults(func=cmd_cdi_undo)
    c_vf = cdisub.add_parser("verify", help="đối soát Neo4j↔Qdrant (thiếu vector / mồ côi, G5)")
    c_vf.set_defaults(func=cmd_cdi_verify)
    c_wt = cdisub.add_parser("watch", help="theo dõi inbox -> tự nạp PDF mới (G1)")
    c_wt.add_argument("inbox", help="thư mục inbox (bỏ PDF vào sẽ tự nạp)")
    c_wt.add_argument("--sub", default="manual", help="corpus con (mặc định manual)")
    c_wt.add_argument("--corpus", default=None)
    c_wt.add_argument("--poll", type=float, default=5.0, help="chu kỳ polling (giây) nếu không có watchdog")
    c_wt.add_argument("--device", default=None)
    c_wt.set_defaults(func=cmd_cdi_watch)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
