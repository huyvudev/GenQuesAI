"""Trich xuat tham chieu noi bo (Dieu A -> Dieu B, CUNG 1 van ban) — phuc vu loai cau
hoi "nhieu buoc - cau truc" trong pipeline sinh QA (thao luan voi user 2026-08-26).

Nguyen tac: CHI bat truong hop KHONG MO HO — cau phai co neo ro rang chi ve CHINH
van ban nay (vd "Nghi dinh nay", "Luat nay", "neu tren"), khong co neo thi BO QUA,
khong co gang doan (giu dung triet ly "chi tu dong khi chac chan" da dung xuyen suot
du an cho REPLACES/AMENDS/GUIDED_BY).

Nguon du lieu: dung THANG Expression.text da co san tren tung Component (Dieu/Khoan/
Diem) — KHONG can doc lai toan van HTML/Qdrant, vi mỗi Component da co noi dung
rieng cua no trong graph. Thuan regex, khong can LLM, chay duoc ca 66k van ban re.

Tao canh moi loai CROSS_REF (Component -> Component, CUNG norm_id), kem property
`cau_trich` (cau goc, de audit lai neu nghi ngo) va `source='regex_noi_bo_v1'`."""
from __future__ import annotations
import re
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, "D:/Project/GenQuesAI")
from genquesai.legal_rag.config import get_settings
from genquesai.legal_rag.graph.client import Neo4jClient

# Neo dam bao chi ve CHINH van ban nay — khong co neo thi BO QUA cau do hoan toan.
_ANCHOR_RE = re.compile(
    r"(?:Nghị định|Thông tư liên tịch|Thông tư|Quyết định|Luật|Bộ luật|Pháp lệnh|"
    r"Nghị quyết|Chỉ thị|Văn bản)\s+này"
    r"|nêu trên|nói trên|đã nêu ở trên|đã nêu trên",
    re.IGNORECASE,
)

# Nhan dien "vung liet ke" trich dan — 1 token la Diem X | Khoan Y | Dieu Z, noi
# voi nhau boi khoang trang (chuoi cung 1 muc: "Diem b Khoan 4 Dieu 18") HOAC
# ","/"va"/"hoac" (bat dau muc moi trong danh sach: "Khoan 2 va Diem b Khoan 4
# Dieu 18, Diem a Khoan 3 va Diem c Khoan 4 Dieu 30" — 2026-08-26, user yeu cau mo
# rong bat cau liet ke nhieu Dieu/Khoan/Diem, truoc do regex don le bo sot).
_TOKEN = r"(?:[Đđ]iểm\s+[a-zđ]|[Kk]hoản\s+\d+[a-zđ]?|Điều\s+\d+[a-zđ]?)"
_ZONE_RE = re.compile(rf"{_TOKEN}(?:\s*(?:,|và|hoặc)?\s+{_TOKEN})*")
_SEP_RE = re.compile(r"\s*,\s*|\s+và\s+|\s+hoặc\s+")
_ITEM_RE = re.compile(
    r"(?:[Đđ]iểm\s+([a-zđ])\s*)?(?:[Kk]hoản\s+(\d+[a-zđ]?)\s*)?(?:Điều\s+(\d+[a-zđ]?))?"
)

_CAU_SPLIT_RE = re.compile(r"(?<=[.;])\s+")


def _duong_dan(dieu: str, khoan: str | None, diem: str | None) -> str:
    p = f"Dieu {dieu}"
    if khoan:
        p += f" > Khoan {khoan}"
        if diem:
            p += f" > Diem {diem}"
    return p


def _parse_zone(zone_text: str) -> list[tuple[str | None, str | None, str]]:
    """1 'vung' -> list (diem, khoan, dieu). Suy luan PHAI SANG TRAI: muc nao thieu
    Khoan/Dieu thi 'muon' cua muc gan nhat ben PHAI co gia tri do (dung quy uoc hanh
    van luat VN — Dieu/Khoan chung thuong dung CUOI danh sach). Da kiem chung tay
    tren 4 ca that (xem lich su thao luan) truoc khi ghep vao pipeline chinh."""
    segs = [s for s in _SEP_RE.split(zone_text) if s.strip()]
    parsed: list[list[str | None]] = []
    for seg in segs:
        m = _ITEM_RE.fullmatch(seg.strip())
        if not m or not any(m.groups()):
            continue
        parsed.append(list(m.groups()))  # [diem, khoan, dieu]
    carry_khoan: str | None = None
    carry_dieu: str | None = None
    for item in reversed(parsed):
        diem, khoan, dieu = item
        if dieu is not None:
            carry_dieu = dieu
            carry_khoan = khoan  # Dieu doc lap (khong kem khoan) -> reset carry_khoan=None dung y muon
        else:
            item[2] = carry_dieu
            if khoan is not None:
                carry_khoan = khoan
            elif diem is not None:
                item[1] = carry_khoan
    return [(d, k, e) for d, k, e in parsed if e is not None]


def tim_tham_chieu_trong_text(text: str) -> list[tuple[str, str]]:
    """Tra list (duong_dan_dich, cau_trich) — CHỈ những trích dẫn nằm trong câu có
    neo tự-tham-chiếu rõ ràng."""
    out: list[tuple[str, str]] = []
    if not text:
        return out
    for cau in _CAU_SPLIT_RE.split(text):
        if not _ANCHOR_RE.search(cau):
            continue
        for zone_m in _ZONE_RE.finditer(cau):
            for diem, khoan, dieu in _parse_zone(zone_m.group(0)):
                dd = _duong_dan(dieu, khoan, diem)
                out.append((dd, cau.strip()[:300]))
    return out


def _neo() -> Neo4jClient:
    s = get_settings()
    s_local = s.model_copy(update={
        "neo4j_uri": "bolt://localhost:7687", "neo4j_user": "neo4j",
        "neo4j_password": "123qwe", "neo4j_database": "neo4j",
    })
    neo = Neo4jClient(s_local)
    neo.verify()
    return neo


def xu_ly_1_vb(neo: Neo4jClient, norm_id: str, components: list[dict]) -> dict:
    """`components`: list {comp_id, duong_dan, text}. Tra thong ke."""
    by_duong_dan = {c["duong_dan"]: c["comp_id"] for c in components}
    stats = {"cau_tim_thay": 0, "resolved": 0, "khong_resolve": 0, "tu_tham_chieu": 0}
    edges: list[tuple[str, str, str]] = []  # (src_comp_id, tgt_comp_id, cau_trich)

    for c in components:
        found = tim_tham_chieu_trong_text(c["text"])
        for dd_dich, cau in found:
            stats["cau_tim_thay"] += 1
            # tu tro vao chinh no, HOAC tro vao chinh cha/con truc tiep cua no (vd
            # Khoan 15 cua Dieu 9 "tham chieu" ve Dieu 9 — cung 1 don vi, khong phai
            # cau noi multi-hop that) -> vo nghia, bo qua ca 2 chieu.
            if dd_dich == c["duong_dan"] or dd_dich.startswith(c["duong_dan"] + " > ") \
                    or c["duong_dan"].startswith(dd_dich + " > "):
                stats["tu_tham_chieu"] += 1
                continue
            tgt_id = by_duong_dan.get(dd_dich)
            if tgt_id is None:
                stats["khong_resolve"] += 1
                continue
            stats["resolved"] += 1
            edges.append((c["comp_id"], tgt_id, cau))

    if edges:
        neo.run(
            """
            UNWIND $rows AS row
            MATCH (src:Component {comp_id: row.src})
            MATCH (tgt:Component {comp_id: row.tgt})
            MERGE (src)-[r:CROSS_REF]->(tgt)
            SET r.cau_trich = row.cau, r.source = 'regex_noi_bo_v1'
            """,
            rows=[{"src": s, "tgt": t, "cau": c} for s, t, c in edges],
        )
    return stats


def main(limit: int | None = None) -> None:
    neo = _neo()
    print("Đang lấy danh sách Component có nội dung (Dieu/Khoan/Diem/ToanVan/PhuLuc)...")
    rows = neo.run("""
        MATCH (n:Norm)-[:HAS_PART*]->(d:Component)-[:HAS_VERSION]->(e:Expression)
        WHERE d.loai IN ['Dieu','Khoan','Diem','ToanVan','PhuLuc']
        RETURN n.norm_id AS norm_id, d.comp_id AS comp_id, d.duong_dan AS duong_dan,
               e.text AS text
    """)
    print(f"Tổng {len(rows):,} Component — đang gom theo văn bản...")
    by_norm: dict[str, list[dict]] = {}
    for r in rows:
        by_norm.setdefault(r["norm_id"], []).append(dict(r))
    del rows
    norm_ids = list(by_norm.keys())
    if limit:
        norm_ids = norm_ids[:limit]
    print(f"Cần xử lý: {len(norm_ids):,} văn bản")

    agg = {"cau_tim_thay": 0, "resolved": 0, "khong_resolve": 0, "tu_tham_chieu": 0}
    t0 = time.time()
    for i, nid in enumerate(norm_ids, 1):
        st = xu_ly_1_vb(neo, nid, by_norm[nid])
        for k in agg:
            agg[k] += st[k]
        if i % 2000 == 0:
            elapsed = time.time() - t0
            print(f"  ...{i:,}/{len(norm_ids):,} VB ({elapsed:.0f}s) · {agg}")

    print(f"XONG: {len(norm_ids):,} VB · {agg}")


if __name__ == "__main__":
    lim = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1] else None
    main(limit=lim)
