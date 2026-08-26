"""Bước 0 (hợp nhất dữ liệu) + Bước 1 (lập kế hoạch tỉ lệ) — pipeline sinh QA luật.

Không đọc `shared_corpus.parquet` như bản gốc (proposed.ipynb) — dữ liệu lấy thẳng
từ Neo4j (cấu trúc + hiệu lực + quan hệ luôn đủ). Xem `legal-rag-qa-pipeline-spec.md`
+ phần thảo luận kiến trúc 2026-08-26.

**Sửa bug thật 2026-08-26** (user phát hiện qua nghi vấn, đã kiểm chứng): claim ban
đầu "Neo4j đã đủ nội dung, không cần Qdrant" SAI — kiểm hết corpus thì 60,8%
Điều/Toàn văn/Phụ lục có `Expression.text` rỗng/quá ngắn trong Neo4j (301.048/
495.134), trong khi Qdrant (field `text` trong payload, không chỉ để tìm vector)
CÓ đủ nội dung cho các trường hợp đó — rất có thể do lúc đồng bộ 2 kho, một số văn
bản chỉ nhúng xong vector mà chưa ghi lại text vào Neo4j. Giờ đọc Neo4j trước, THIẾU
mới lấy dự phòng từ Qdrant — mở rộng vùng dữ liệu dùng được từ ~188k lên gần 495k Điều."""
from __future__ import annotations
import re
from dataclasses import dataclass, field
from datetime import date

from ..config import Settings
from ..graph.client import Neo4jClient

_DIEU_SO_RE = re.compile(r"Dieu (\d+)([a-z]?)")


@dataclass
class Dieu:
    comp_id: str
    norm_id: str
    so_hieu: str
    duong_dan: str
    tieu_de_vb: str
    text: str
    hieu_luc_tu: date | None
    hieu_luc_den: date | None

    @property
    def con_hieu_luc(self) -> bool:
        return self.hieu_luc_den is None


@dataclass
class QuanHeHieuLuc:
    """1 quan hệ REPLACES/AMENDS ĐÃ DUYỆT, đích đã xác định cấp Điều/Khoản/Điểm cụ
    thể (không phải 'cả văn bản') — đủ dữ liệu để hỏi 'trước/sau sửa đổi'.

    KHÔNG lưu 'Điều nào của VB nguồn chứa nội dung thay thế' — Neo4j hiện không có
    field này (chỉ biết Điều CŨ nào bị ảnh hưởng, không biết Điều MỚI tương ứng).
    Sửa 2026-08-26 (phát hiện qua test thật — ghép bừa 1 Điều nguồn ra câu hỏi lệch
    chủ đề): thay vì đoán, đưa TOÀN VĂN văn bản nguồn cho LLM tự tìm đúng đoạn."""
    src_norm_id: str
    tgt_comp_id: str
    loai: str          # ThayThe | SuaDoi | BaiBoToanBo | BaiBoTungPhan
    ngay_hieu_luc: date | None


@dataclass
class ThamChieuNoiBo:
    src_comp_id: str
    tgt_comp_id: str


@dataclass
class BangDuLieu:
    dieu: dict[str, Dieu] = field(default_factory=dict)       # comp_id -> Dieu
    quan_he_hieu_luc: list[QuanHeHieuLuc] = field(default_factory=list)
    tham_chieu_noi_bo: list[ThamChieuNoiBo] = field(default_factory=list)
    so_dieu_lay_tu_qdrant: int = 0


_Q_DIEU = """
MATCH (n:Norm)-[:HAS_PART*]->(d:Component)-[:HAS_VERSION]->(e:Expression)
WHERE d.loai IN ['Dieu','ToanVan','PhuLuc']
RETURN d.comp_id AS comp_id, n.norm_id AS norm_id, n.so_hieu AS so_hieu,
       d.duong_dan AS duong_dan, n.tieu_de AS tieu_de_vb, e.text AS text,
       e.hieu_luc_tu AS hieu_luc_tu, e.hieu_luc_den AS hieu_luc_den
"""

_NGUONG_TEXT_TOI_THIEU = 30


def tai_qdrant_fallback(s: Settings) -> dict[str, str]:
    """Quét TOÀN BỘ collection Qdrant 1 lần, trả {comp_id: text} — dùng làm dự
    phòng khi `Expression.text` rỗng/quá ngắn trong Neo4j (xem docstring module).
    Chỉ lấy 2 field payload cần thiết (`comp_id`, `text`), không lấy vector —
    ~832k điểm, quét 1 lần mất vài phút, chấp nhận được vì chỉ chạy 1 lần/phiên."""
    from qdrant_client import QdrantClient

    q = QdrantClient(url=s.qdrant_url, api_key=s.qdrant_api_key or None,
                     timeout=120, check_compatibility=False)
    out: dict[str, str] = {}
    offset = None
    while True:
        points, offset = q.scroll(
            s.qdrant_collection, limit=2000, offset=offset,
            with_payload=["comp_id", "text"], with_vectors=False)
        for p in points:
            cid = (p.payload or {}).get("comp_id")
            t = (p.payload or {}).get("text")
            if cid and t and len(t) >= _NGUONG_TEXT_TOI_THIEU:
                out[cid] = t
        if offset is None:
            break
    return out

# Chỉ lấy cạnh đã DUYỆT (da_duyet=true) — tránh benchmark học theo quan hệ sai
# (đã phát hiện nhiều GUIDED_BY/AMENDS dương tính giả trong đợt rà soát 2026-08-26).
# Chỉ lấy AMENDS/REPLACES đã xác định cấp Điều/Khoản/Điểm cụ thể (AFFECTS -> Component,
# không phải Norm) — mới đủ để hỏi "nội dung cũ" đúng 1 đơn vị rõ ràng. KHÔNG join
# sang Điều cụ thể của src nữa (bug đã sửa — xem docstring QuanHeHieuLuc).
_Q_QUAN_HE_HIEU_LUC = """
MATCH (a:Action)-[:ENACTED_BY]->(src:Norm)
MATCH (a)-[:AFFECTS]->(tgt:Component)
WHERE coalesce(a.da_duyet,false) = true
      AND a.loai IN ['ThayThe','SuaDoi','BaiBoToanBo','BaiBoTungPhan']
RETURN DISTINCT src.norm_id AS src_norm_id, tgt.comp_id AS tgt_comp_id,
       a.loai AS loai, a.ngay_hieu_luc AS ngay_hieu_luc
"""

_Q_CROSS_REF = """
MATCH (a:Component)-[:CROSS_REF]->(b:Component)
WHERE a.loai = 'Dieu' AND b.loai = 'Dieu'
RETURN DISTINCT a.comp_id AS src_comp_id, b.comp_id AS tgt_comp_id
"""


def hop_nhat_du_lieu(neo: Neo4jClient, qdrant_fallback: dict[str, str] | None = None) -> BangDuLieu:
    """Bước 0 — đọc Neo4j trước; nếu `Expression.text` rỗng/quá ngắn thì lấy dự
    phòng từ `qdrant_fallback` (kết quả `tai_qdrant_fallback()`, truyền vào từ
    `run.py` để chỉ quét Qdrant 1 lần/phiên, không quét lại mỗi lần gọi hàm này)."""
    qdrant_fallback = qdrant_fallback or {}
    bang = BangDuLieu()
    tu_qdrant = 0
    for r in neo.run(_Q_DIEU):
        text = r["text"]
        if not text or len(text) < _NGUONG_TEXT_TOI_THIEU:
            text = qdrant_fallback.get(r["comp_id"])
            if text:
                tu_qdrant += 1
        if not text or len(text) < _NGUONG_TEXT_TOI_THIEU:
            continue
        bang.dieu[r["comp_id"]] = Dieu(
            comp_id=r["comp_id"], norm_id=r["norm_id"], so_hieu=r["so_hieu"],
            duong_dan=r["duong_dan"], tieu_de_vb=r["tieu_de_vb"], text=text,
            hieu_luc_tu=r["hieu_luc_tu"], hieu_luc_den=r["hieu_luc_den"])
    bang.so_dieu_lay_tu_qdrant = tu_qdrant
    norm_ids_co_dieu = {d.norm_id for d in bang.dieu.values()}
    for r in neo.run(_Q_QUAN_HE_HIEU_LUC):
        if r["src_norm_id"] in norm_ids_co_dieu and r["tgt_comp_id"] in bang.dieu:
            bang.quan_he_hieu_luc.append(QuanHeHieuLuc(**r))
    for r in neo.run(_Q_CROSS_REF):
        if r["src_comp_id"] in bang.dieu and r["tgt_comp_id"] in bang.dieu:
            bang.tham_chieu_noi_bo.append(ThamChieuNoiBo(**r))
    return bang


def parent_path(d: Dieu) -> list[str]:
    """Breadcrumb [số hiệu VB, Chương (nếu có), Điều/Khoản/Điểm] — field còn thiếu
    trong output trước đây (2026-08-26, user phát hiện qua đối chiếu bản tóm tắt)."""
    dd = d.duong_dan.replace("Dieu", "Điều").replace("Khoan", "Khoản").replace("Diem", "Điểm")
    return [d.so_hieu] + [p.strip() for p in dd.split(">")]


def validity_status(d: Dieu) -> dict:
    """Trạng thái hiệu lực TẠI THỜI ĐIỂM sinh đề — field còn thiếu trước đây, cần
    lưu để bộ đề tự mô tả đúng phiên bản luật nào (spec §5)."""
    return {"con_hieu_luc": d.con_hieu_luc,
           "hieu_luc_tu": str(d.hieu_luc_tu) if d.hieu_luc_tu else None,
           "hieu_luc_den": str(d.hieu_luc_den) if d.hieu_luc_den else None}


def toan_van_vb(bang: BangDuLieu, norm_id: str, max_chars: int = 14000) -> str:
    """Ghép toàn văn 1 văn bản từ các Điều đã có sẵn trong `bang.dieu` (không cần
    đọc lại file gốc/Qdrant — dữ liệu đã có đủ). Sắp theo đúng thứ tự số Điều."""
    dieu_cua_vb = [d for d in bang.dieu.values() if d.norm_id == norm_id]

    def _key(d: Dieu):
        m = _DIEU_SO_RE.match(d.duong_dan)
        return (int(m.group(1)), m.group(2)) if m else (999999, "")

    dieu_cua_vb.sort(key=_key)
    doan = []
    tong = 0
    for d in dieu_cua_vb:
        chunk = f"{d.duong_dan.replace('Dieu', 'Điều')}: {d.text}"
        doan.append(chunk)
        tong += len(chunk)
        if tong >= max_chars:
            break
    return "\n\n".join(doan)[:max_chars]


@dataclass
class KeHoach:
    ty_le_con_hieu_luc: float
    ty_le_co_quan_he_hieu_luc: float
    mat_do_tham_chieu_noi_bo: float
    ty_le_mot_buoc: float
    ty_le_cau_truc: float
    ty_le_hieu_luc: float
    ty_le_gai_bay: float
    ty_le_bay_hieu_luc: float


def lap_ke_hoach(bang: BangDuLieu) -> KeHoach:
    """Bước 1 — thay công thức avg-degree/entity-density của bản gốc (calibrate cho
    2 corpus tiếng Anh, không còn ý nghĩa ở đây) bằng 3 chỉ số thật của graph luật."""
    tong_dieu = max(1, len(bang.dieu))
    con_hieu_luc = sum(1 for d in bang.dieu.values() if d.con_hieu_luc)
    ty_le_con_hieu_luc = con_hieu_luc / tong_dieu

    dieu_co_qhhl = {qh.tgt_comp_id for qh in bang.quan_he_hieu_luc}
    ty_le_co_qhhl = len(dieu_co_qhhl) / tong_dieu

    mat_do_cross_ref = len(bang.tham_chieu_noi_bo) / tong_dieu

    # Bậc thang tuyến tính đơn giản — hiệu chỉnh theo phân phối THẬT của graph luật
    # (không dùng ngưỡng 5/50 avg-degree của bản gốc, vô nghĩa với domain khác hẳn).
    ty_le_hieu_luc = min(0.30, 0.10 + 2.0 * ty_le_co_qhhl)
    ty_le_cau_truc = min(0.30, 0.10 + 0.5 * mat_do_cross_ref)
    ty_le_bay_hieu_luc = min(0.15, 0.05 + (1.0 - ty_le_con_hieu_luc) * 0.3)
    ty_le_gai_bay = 0.15
    ty_le_mot_buoc = max(0.10, 1.0 - ty_le_hieu_luc - ty_le_cau_truc
                         - ty_le_bay_hieu_luc - ty_le_gai_bay)

    return KeHoach(
        ty_le_con_hieu_luc=ty_le_con_hieu_luc, ty_le_co_quan_he_hieu_luc=ty_le_co_qhhl,
        mat_do_tham_chieu_noi_bo=mat_do_cross_ref, ty_le_mot_buoc=ty_le_mot_buoc,
        ty_le_cau_truc=ty_le_cau_truc, ty_le_hieu_luc=ty_le_hieu_luc,
        ty_le_gai_bay=ty_le_gai_bay, ty_le_bay_hieu_luc=ty_le_bay_hieu_luc)
