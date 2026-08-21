"""Importer — chức năng NẠP VĂN BẢN tự phục vụ từ PDF lẻ (ngoài crawler).

Dùng được qua CLI (Excel) lẫn API (JSON):
  1) prepare_rows(pdfs) -> [dict]  : đoán metadata + kiểm trùng (nguồn cho Excel và trang admin)
  2) <người dùng sửa/xác nhận>
  3) apply_rows(rows)              : trích text/OCR -> raw dir -> ingest -> embed -> refs

Toàn bộ LOCAL (pdftotext/OCR tesseract/bge-m3/regex) — KHÔNG tốn quota LLM.
"""
from __future__ import annotations
import html as htmllib
import json
import re
import subprocess
from datetime import datetime, date
from pathlib import Path

from ..graph.client import Neo4jClient

# ---------- thuần (test được) ----------
RE_SH = re.compile(r"S[ốôố]\s*:?\s*([0-9]+\s*/\s*(?:[0-9]{4}\s*/\s*)?[A-ZĐ]+(?:[-/][A-ZĐ]+)*)")
RE_NGAY = re.compile(r"ngày\s+(\d{1,2})\s+tháng\s+(\d{1,2})\s+năm\s+(\d{4})", re.IGNORECASE)
_KW = ("THÔNG TƯ", "NGHỊ ĐỊNH", "NGHỊ QUYẾT", "QUYẾT ĐỊNH", "CHỈ THỊ", "PHÁP LỆNH", "LUẬT")
DOCTYPE_ALLOWED = ("Luật", "Bộ luật", "Pháp lệnh", "Nghị định", "Nghị quyết", "Quyết định", "Chỉ thị", "Thông tư")


def parse_date(v) -> str | None:
    if v is None:
        return None
    if isinstance(v, (datetime, date)):
        return v.strftime("%Y-%m-%d")
    s = str(v).strip().strip("\t").strip()
    s = s.split()[0] if " " in s else s
    m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})", s)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    m = re.match(r"^(\d{1,2})[-/](\d{1,2})[-/](\d{2,4})", s)
    if m:
        y = m.group(3)
        y = "20" + y if len(y) == 2 else (y if len(y) == 4 else "2026")
        return f"{y}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
    return None


def norm_id_from(so_hieu: str) -> str:
    return re.sub(r"[^0-9A-Za-zĐđ]+", "-", so_hieu).strip("-")


def agency_from(so_hieu: str) -> str:
    u = (so_hieu or "").upper()
    if "/QH" in u:
        return "Quốc hội"
    if "NĐ-CP" in u or "ND-CP" in u or "NQ-CP" in u:
        return "Chính phủ"
    if "TT-BKHCN" in u:
        return "Bộ Khoa học và Công nghệ"
    if "TT-BTTTT" in u:
        return "Bộ Thông tin và Truyền thông"
    if "CT-TTG" in u or "QĐ-TTG" in u or "QD-TTG" in u:
        return "Thủ tướng Chính phủ"
    return "Khác"


def loai_from(so_hieu: str, header: str) -> str:
    u = (so_hieu or "").upper()
    if "TT-" in u:
        return "Thông tư"
    if "NĐ-CP" in u or "ND-CP" in u:
        return "Nghị định"
    if "NQ-" in u:
        return "Nghị quyết"
    if "CT-TTG" in u:
        return "Chỉ thị"
    if "QĐ-TTG" in u or "QD-TTG" in u:
        return "Quyết định"
    if "/QH" in u:
        hu = (header or "").upper()
        iL, iN = hu.find("LUẬT"), hu.find("NGHỊ QUYẾT")
        return "Nghị quyết" if (iN != -1 and (iL == -1 or iN < iL)) else "Luật"
    return "?"


def sohieu_from_name(stem: str, year: str | None) -> str | None:
    y = year or "2025"
    s = stem.lower()
    for pat, fmt in [(r"tt(\d+)20\d\d", "{}/2026/TT-BKHCN"), (r"luatso(\d+)\.(\d{4})", "{}/{}/QH15"),
                     (r"luat(\d+)[-_](\d{4})", "{}/{}/QH15"), (r"luat(\d+)", "{}/" + y + "/QH15"),
                     (r"(\d+)qh", "{}/" + y + "/QH15"), (r"(\d+)[-]?(?:ndcp|cp)", "{}/" + y + "/NĐ-CP"),
                     (r"(\d+)[-]?nqcp", "{}/NQ-CP"), (r"(\d+)nq", "{}/NQ-CP"),
                     (r"(\d+)[-]?ttg", "{}/" + y + "/QĐ-TTg"), (r"(\d+)[-]?ct", "{}/CT-TTg")]:
        m = re.match(pat, s)
        if m:
            gs = [int(g) if g and g.isdigit() else g for g in m.groups()]
            return fmt.format(*gs)
    return None


def _title_from(header: str) -> str:
    lines = [l.strip() for l in (header or "").splitlines() if l.strip()]
    for i, l in enumerate(lines):
        if any(l.upper().startswith(k) for k in _KW):
            t = re.split(r"Căn cứ|Số:|Người ký", " ".join(lines[i + 1:i + 6]))[0]
            return re.sub(r"\s+", " ", t)[:120].strip()
    return re.sub(r"\s+", " ", " ".join(lines[2:6]))[:120]


def extract_meta(header: str, stem: str, source: str) -> dict:
    cut = header.find("Căn cứ")
    head = header[:cut] if cut > 100 else header[:700]
    shm = RE_SH.search(re.sub(r"\s+", " ", head))
    ng = RE_NGAY.search(re.sub(r"\s+", " ", header))
    year = ng.group(3) if ng else None
    sh = re.sub(r"\s+", "", shm.group(1)) if shm else sohieu_from_name(stem, year)
    flags = []
    if not shm:
        flags.append("số hiệu suy từ tên file")
    if source == "ocr":
        flags.append("OCR")
    if not ng:
        flags.append("thiếu ngày")
    return {"so_hieu": sh, "loai": loai_from(sh or "", header),
            "ngay_bh": f"{ng.group(3)}-{int(ng.group(2)):02d}-{int(ng.group(1)):02d}" if ng else "",
            "ten": _title_from(header), "nghi_ngo": "; ".join(flags)}


def normalize_row(file: str, so_hieu: str, loai: str, ten: str, ngay_bh, ngay_hl) -> dict | None:
    """Chuẩn hoá 1 dòng (đã xác nhận) -> doc dict để nạp. Trả None nếu thiếu số hiệu."""
    sh, loai, ten = (so_hieu or "").strip(), (loai or "").strip(), (ten or "").strip()
    if not sh:
        return None
    if loai == "Chỉ thị" and "QĐ-TTG" in sh.upper():
        m = re.search(r"(\d+)\s*/\s*CT-TTg", ten, re.I)
        sh = m.group(0).replace(" ", "") if m else re.sub(r"/\d{4}/QĐ-TTg", "/CT-TTg", sh)
    sh = re.sub(r"^(\d)/(NQ-CP|CT-TTg)$", r"0\1/\2", sh)
    return {"file": str(file), "so_hieu": sh, "docType": loai or "Khác", "title": ten,
            "agency": agency_from(sh), "norm_id": norm_id_from(sh),
            "issueDate": parse_date(ngay_bh), "effFrom": parse_date(ngay_hl) or parse_date(ngay_bh)}


# ---------- I/O PDF ----------
def pdf_text(pdf: Path, first_pages: int | None = None, max_pages: int = 2000) -> tuple[str, str]:
    """Rút text: pdftotext (born-digital) hoặc OCR tesseract (scan). Trả (text, 'text'|'ocr').

    max_pages=2000: OCR TRỌN tài liệu (không chỉ vài trang đầu). Trần 2000 chỉ để chặn file
    lỗi/pathological; VBQPPL thực tế không dài tới mức đó."""
    args = ["pdftotext", "-enc", "UTF-8"] + (["-l", str(first_pages)] if first_pages else []) + [str(pdf), "-"]
    txt = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace").stdout
    if len(txt.replace(" ", "").strip()) > (400 if first_pages else 800):
        return txt, "text"
    # Cache OCR (chỉ full-doc): tránh OCR lại + cho phép PHA pre-OCR song song ghi sẵn.
    cache = Path(str(pdf) + ".ocr.txt") if first_pages is None else None
    if cache is not None and cache.exists():
        c = cache.read_text(encoding="utf-8", errors="replace")
        if len(c.strip()) >= 60:
            return c, "ocr"
    from pdf2image import convert_from_path
    import pytesseract
    kw = {"first_page": 1, "last_page": first_pages} if first_pages else {}
    imgs = convert_from_path(str(pdf), dpi=200, **kw)[:max_pages]
    text = "\n".join(pytesseract.image_to_string(i, lang="vie") for i in imgs)
    if cache is not None:
        try:
            cache.write_text(text, encoding="utf-8")
        except Exception:
            pass
    return text, "ocr"


# ---------- PHA 1: dò metadata (dùng chung CLI + API) ----------
def prepare_rows(pdfs: list[Path], neo: Neo4jClient, log=print) -> list[dict]:
    """Đoán metadata + kiểm trùng cho mỗi PDF. Trả list dict (cho Excel hoặc trang admin)."""
    existing = {r["sh"] for r in neo.run("MATCH (n:Norm) RETURN n.so_hieu AS sh")}
    out = []
    for i, pdf in enumerate(pdfs, 1):
        header, src = pdf_text(pdf, first_pages=2)
        m = extract_meta(header, pdf.stem, src)
        dup = bool(m["so_hieu"]) and m["so_hieu"] in existing
        out.append({"file": pdf.name, "so_hieu": m["so_hieu"] or "", "loai": m["loai"],
                    "ten": m["ten"], "ngay_bh": m["ngay_bh"], "ngay_hl": "",
                    "co_quan": agency_from(m["so_hieu"] or ""), "dup": dup,
                    "nghi_ngo": m["nghi_ngo"], "source": src})
        log(f"  {i}/{len(pdfs)} {pdf.name} -> {m['so_hieu']} [{src}]{' TRÙNG' if dup else ''}")
    return out


# ---------- PHA 2: nạp (dùng chung) ----------
def _rm_child(dd: Path, root: Path) -> None:
    """shutil.rmtree AN TOÀN: chỉ xoá khi dd thực sự NẰM TRONG root (không phải chính root/ngoài
    root). Chặn tai nạn rmtree(root) khi norm_id rỗng/'.' làm dd trùng root (bài học 2026-07-24)."""
    import shutil
    try:
        ddr, rr = dd.resolve(), root.resolve()
        if ddr != rr and rr in ddr.parents:
            shutil.rmtree(dd, ignore_errors=True)
    except OSError:
        pass


def _write_raw(dd: Path, d: dict, text: str, src: str, corpus_sub: str) -> None:
    """Dựng raw dir chuẩn (toanvan.html <pre> + doc.json + meta.json) để tái dùng pipeline OFFLINE."""
    dd.mkdir(parents=True, exist_ok=True)   # parents=True: nếu cha (staging) mất thì tự dựng lại,
                                             # KHÔNG crash cả run (bài học 2026-07-24)
    (dd / "toanvan.html").write_text(
        "<html><head><meta charset='utf-8'></head><body><pre>" + htmllib.escape(text) + "</pre></body></html>",
        encoding="utf-8")
    (dd / "doc.json").write_text(json.dumps({"data": {
        "docNum": d["so_hieu"], "docType": {"name": d["docType"]}, "agencyName": d["agency"],
        "issueDate": d["issueDate"], "effFrom": d["effFrom"], "title": d["title"],
        "effStatus": {"name": "Còn hiệu lực"}, "effTo": None, "references": []}}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    (dd / "meta.json").write_text(json.dumps(
        {"source": f"import/{corpus_sub}", "goc_pdf": d["file"], "toanvan": src,
         "added": datetime.now().isoformat()}, ensure_ascii=False), encoding="utf-8")


def apply_rows(rows: list[dict], neo: Neo4jClient, store, emb, base: Path, pdf_dir: Path,
               corpus_sub: str = "manual", source: str = "import", log=print,
               near_dup_warn: bool = True) -> dict:
    """Nạp từ list dict đã chuẩn hoá (mỗi dict = normalize_row output). Trả tổng kết.

    Có CDI gate: dedup (số hiệu chuẩn hoá + content_hash), validation gate (FAIL -> quarantine,
    gỡ raw dir để bulk-ingest không vô tình nạp lại), và ghi ledger (:IngestRun)."""
    import shutil
    from ..graph.ingest import ingest_norm
    from .loader import load_norm
    from .reference_extractor import extract_corpus_references
    from ..retrieval.index import embed_corpus
    from ..cdi import find_duplicate, near_duplicates, normalize_so_hieu, validate
    from ..cdi.ledger import record_run
    raw = base / corpus_sub
    raw.mkdir(parents=True, exist_ok=True)
    existing = neo.run("MATCH (n:Norm) RETURN n.norm_id AS norm_id, n.so_hieu AS so_hieu, "
                       "n.content_hash AS content_hash")
    existing_nsh = {normalize_so_hieu(e["so_hieu"]) for e in existing if e.get("so_hieu")}
    built, dups, quarantine, warned = [], [], [], []
    for i, d in enumerate(rows, 1):
        if not d:
            continue
        # (1) dedup rẻ TRƯỚC OCR: số hiệu chuẩn hoá khớp -> bỏ (khỏi tốn OCR)
        if normalize_so_hieu(d["so_hieu"]) in existing_nsh:
            dups.append({"so_hieu": d["so_hieu"], "kind": "so_hieu"})
            continue
        # text_override: text đã rút sẵn (PHA 3 .doc/.rtf convert+transcode) -> KHÔNG gọi pdf_text.
        if d.get("text_override"):
            text, src = d["text_override"], d.get("src", "doc")
        else:
            pdf = pdf_dir / d["file"]
            if not pdf.exists():
                log(f"  [!] thiếu {d['file']}")
                quarantine.append({"so_hieu": d["so_hieu"], "errors": ["thiếu file PDF"]})
                continue
            text, src = pdf_text(pdf)
        if len(text.strip()) < 60:
            log(f"  [!] {d['so_hieu']}: text rỗng")
            quarantine.append({"so_hieu": d["so_hieu"], "errors": ["text rỗng (<60 ký tự)"]})
            continue
        # BẢO VỆ: norm_id rỗng (vd so_hieu OCR rác chuẩn hoá thành '.') -> raw/'' == raw.
        # Nếu không chặn, _rm_child bên dưới sẽ shutil.rmtree(raw) XOÁ SẠCH staging (đã xảy ra
        # 2026-07-24: 1 VB '.' wipe 3.5k dir rồi mọi batch sau crash). Quarantine, KHÔNG đụng đĩa.
        if not d["norm_id"] or (raw / d["norm_id"]).resolve() == raw.resolve():
            quarantine.append({"so_hieu": d["so_hieu"], "errors": ["norm_id rỗng/không hợp lệ"]})
            log(f"  {i}/{len(rows)} {d['so_hieu']!r} norm_id rỗng -> quarantine (bỏ, không ghi)")
            continue
        dd = raw / d["norm_id"]
        _write_raw(dd, d, text, src, corpus_sub)
        loaded = load_norm(dd)
        if not loaded:
            _rm_child(dd, raw)
            quarantine.append({"so_hieu": d["so_hieu"], "errors": ["load_norm trả None"]})
            continue
        norm, comps = loaded
        # (2) dedup content_hash (re-upload khác số hiệu/định dạng)
        dup = find_duplicate(norm.so_hieu, norm.content_hash or "", existing)
        if dup:
            _rm_child(dd, raw)
            dups.append({"so_hieu": d["so_hieu"], "kind": dup.kind, "trung_voi": dup.so_hieu})
            log(f"  {i}/{len(rows)} {d['so_hieu']} TRÙNG ({dup.kind} ~ {dup.so_hieu}) -> bỏ")
            continue
        # (3) validation gate: FAIL -> quarantine (gỡ raw dir)
        rep = validate(norm, comps)
        if not rep.ok:
            _rm_child(dd, raw)
            quarantine.append({"so_hieu": d["so_hieu"], "errors": rep.errors})
            log(f"  {i}/{len(rows)} {d['so_hieu']} FAIL gate: {'; '.join(rep.errors)} -> quarantine")
            continue
        # PASS -> nạp (published=false; chỉ bật sau khi embed xong — G5)
        ingest_norm(neo, norm, comps)
        neo.run("MATCH (n:Norm {norm_id:$id}) SET n.tinh_trang='ConHieuLuc', n.published=false",
                id=norm.norm_id)
        built.append(norm.norm_id)
        existing.append({"norm_id": norm.norm_id, "so_hieu": norm.so_hieu,
                         "content_hash": norm.content_hash})
        existing_nsh.add(normalize_so_hieu(norm.so_hieu))
        # near_duplicates = O(n) fuzzy toàn corpus/VB (10s×48 = 482s/batch ở 41k Norm), CHỈ
        # advisory cho người rà tay. Bulk-load nền không ai đọc -> tắt được để khỏi là nút thắt.
        nd = near_duplicates(norm.so_hieu, existing[:-1]) if near_dup_warn else []
        flag = f" WARN: {'; '.join(rep.warnings)}" if rep.warnings else ""
        if rep.warnings or nd:
            warned.append({"so_hieu": d["so_hieu"], "warnings": rep.warnings,
                           "near": [m.so_hieu for m in nd]})
        log(f"  {i}/{len(rows)} {d['so_hieu']} [{src}] {len(text)} ký tự{flag}"
            + (f" (gần giống: {', '.join(m.so_hieu for m in nd)})" if nd else ""))
    n_pt = embed_corpus(neo, store, emb, batch=32, norm_ids=built) if built else 0
    if built:  # G5: publish CHỈ khi cả graph + vector đã xong
        neo.run("MATCH (n:Norm) WHERE n.norm_id IN $ids SET n.published=true", ids=built)
    refs = extract_corpus_references(neo, base, [corpus_sub]) if built else {"REPLACES": 0, "AMENDS": 0, "GUIDED_BY": 0}
    run_id = record_run(neo, source=source, command=f"import:{corpus_sub}", norm_ids=built,
                        n_ok=len(built), n_fail=len(quarantine), n_dup=len(dups), n_warn=len(warned),
                        failed=[q["so_hieu"] for q in quarantine],
                        validations={"quarantine": quarantine, "warned": warned},
                        extra={"point": n_pt, "refs": refs})
    return {"nap": len(built), "bo_trung": len(dups), "quarantine": quarantine, "warned": warned,
            "point": n_pt, "refs": refs, "norm_ids": built, "run_id": run_id}


# ---------- Excel wrapper (CLI) ----------
COLS = ["STT", "Tên file", "Tên văn bản (đoán)", "Số hiệu", "Loại VB", "Ngày ban hành",
        "Ngày hiệu lực", "Cơ quan ban hành", "Nghi ngờ / Ghi chú"]


def prepare(pdf_dir: Path, out_xlsx: Path, neo: Neo4jClient, log=print) -> dict:
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    rows = prepare_rows(sorted(pdf_dir.glob("*.pdf")), neo, log)
    wb = Workbook(); ws = wb.active; ws.title = "VB cần kiểm"
    yel = PatternFill("solid", fgColor="FFF2CC"); grn = PatternFill("solid", fgColor="E2EFDA")
    thin = Border(*[Side(style="thin", color="CCCCCC")] * 4)
    ws.merge_cells("A1:I1")
    ws["A1"] = ("HƯỚNG DẪN: Ô TÔ VÀNG cần kiểm/sửa/điền. Loại VB: " + " | ".join(DOCTYPE_ALLOWED) +
                ". Ngày: YYYY-MM-DD. Ghi chú 'TRÙNG' = đã có (sẽ bỏ qua). Xong: import-apply.")
    ws["A1"].font = Font(bold=True, color="C00000"); ws["A1"].alignment = Alignment(wrap_text=True, vertical="center")
    ws.row_dimensions[1].height = 56
    for j, c in enumerate(COLS, 1):
        cell = ws.cell(2, j, c); cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="4472C4")
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    for j, w in enumerate([5, 30, 40, 18, 14, 14, 14, 26, 30], 1):
        ws.column_dimensions[chr(64 + j)].width = w
    for i, m in enumerate(rows, 1):
        rr = i + 2
        note = ("TRÙNG (sẽ bỏ qua); " if m["dup"] else "") + m["nghi_ngo"]
        vals = [i, m["file"], m["ten"], m["so_hieu"], m["loai"], m["ngay_bh"], "", m["co_quan"], note]
        for j, v in enumerate(vals, 1):
            cell = ws.cell(rr, j, v); cell.border = thin
            cell.alignment = Alignment(wrap_text=True, vertical="center")
        ws.cell(rr, 4).fill = yel if ("tên file" in m["nghi_ngo"] or not m["so_hieu"]) else grn
        if m["loai"] == "?":
            ws.cell(rr, 5).fill = yel
        if not m["ngay_bh"]:
            ws.cell(rr, 6).fill = yel
        ws.cell(rr, 7).fill = yel
    ws.freeze_panes = "A3"
    out_xlsx.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out_xlsx)
    n_dup = sum(1 for m in rows if m["dup"])
    return {"pdf": len(rows), "trung": n_dup, "moi": len(rows) - n_dup, "xlsx": str(out_xlsx)}


def read_review(xlsx: Path) -> list[dict]:
    from openpyxl import load_workbook
    ws = load_workbook(xlsx).active
    out = []
    for r in range(3, ws.max_row + 1):
        fname = ws.cell(r, 2).value
        if not fname or "TRÙNG" in str(ws.cell(r, 9).value or "").upper():
            continue
        row = normalize_row(str(fname), str(ws.cell(r, 4).value or ""), str(ws.cell(r, 5).value or ""),
                            str(ws.cell(r, 3).value or ""), ws.cell(r, 6).value, ws.cell(r, 7).value)
        if row:
            out.append(row)
    return out


def apply_import(xlsx: Path, neo: Neo4jClient, store, emb, base: Path, pdf_dir: Path,
                 corpus_sub: str = "manual", log=print) -> dict:
    return apply_rows(read_review(xlsx), neo, store, emb, base, pdf_dir,
                      corpus_sub=corpus_sub, source="import-cli", log=log)
