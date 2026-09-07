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
from .prompts import P_DE_XUAT_KICH_BAN_LIEN_NGANH

_SYS_LIEN_NGANH = ("Bạn là chuyên gia ra đề QA cho benchmark RAG pháp luật Việt Nam. "
                  "Chỉ trả JSON hợp lệ, không giải thích thêm.")

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
class BaiBoTungPhan:
    """1 Khoản/Điểm bị bãi bỏ TỪNG PHẦN đã duyệt, trong khi Điều CHA vẫn còn hiệu
    lực (có bản hiện hành) — ca 'sạch' để hỏi 'phần nào bị bãi bỏ, phần còn lại còn
    hiệu lực không'. Khác `QuanHeHieuLuc` (ThayThe/SuaDoi/BaiBoToanBo): các loại đó
    đích là 1 Điều đã HẾT hiệu lực toàn bộ hoặc có nội dung thay thế rõ ràng; ở đây
    Điều cha KHÔNG hết hiệu lực, chỉ 1 phần con của nó bị xoá."""
    comp_id: str          # Khoan/Diem bi bai bo
    duong_dan: str
    text: str
    ngay_het_hl: date | None
    dieu_cha: Dieu         # ban hien hanh (con_hieu_luc=True) cua Dieu chua no


@dataclass
class HuongDanLienVB:
    """1 cặp Norm A (được hướng dẫn) <-[:GUIDED_BY]- Norm B (hướng dẫn), CẢ HAI còn
    hiệu lực. Quan hệ chỉ ở cấp Norm-Norm (không biết đúng Điều nào của B cụ thể hoá
    Điều nào của A) — xử lý giống `QuanHeHieuLuc`: đưa TOÀN VĂN B cho LLM tự tìm
    (xem `generate.py::_gen_huong_dan_lien_vb`)."""
    norm_a: str
    norm_b: str


@dataclass
class DieuKhoanChuyenTiep:
    """1 quy tắc CHUYỂN TIẾP (`TransitionRule`) đã duyệt, Norm nguồn còn hiệu lực,
    confidence cao (>=0.8). Khác các loại trên: `dieu_kien`/`van_ban_ap_dung` đã
    được TÁCH SẴN lúc ingest (LLM extract) — KHÔNG cần tự tìm kiếm trong toàn văn
    như `HuongDanLienVB`/`QuanHeHieuLuc`, rẻ và ít rủi ro hallucination hơn hẳn."""
    rule_id: str
    nguon_dieu_khoan: str    # vd "Điều 73 94/2025/QH15"
    dieu_kien: str           # truong hop nao ap dung quy tac chuyen tiep nay
    van_ban_ap_dung: str     # quy dinh nao duoc ap dung trong truong hop do
    dieu_kien_raw: str       # nguyen van doan Dieu chuyen tiep (ngu canh day du)
    so_hieu: str


@dataclass
class KichBanLienNganh:
    """1 kịch bản liên NGÀNH LUẬT (2 luật độc lập, khác lĩnh vực, cùng áp dụng 1 tình
    huống thực tế) — do LLM đề xuất 1 lần/lượt chạy (`de_xuat_kich_ban_lien_nganh`),
    KHÔNG dựa cạnh trích dẫn có sẵn (khác `ThamChieuNoiBo`/`HuongDanLienVB`) vì 2 luật
    này KHÔNG trích dẫn nhau — chỉ tình cờ cùng cần trong 1 thủ tục. Xem thảo luận
    kiến trúc 2026-09-05 (data.py::P_LIEN_NGANH trong prompts.py)."""
    boi_canh: str
    norm_a: str
    so_hieu_a: str
    norm_b: str
    so_hieu_b: str


@dataclass
class BangDuLieu:
    dieu: dict[str, Dieu] = field(default_factory=dict)       # comp_id -> Dieu
    quan_he_hieu_luc: list[QuanHeHieuLuc] = field(default_factory=list)
    tham_chieu_noi_bo: list[ThamChieuNoiBo] = field(default_factory=list)
    bai_bo_tung_phan: list[BaiBoTungPhan] = field(default_factory=list)
    huong_dan_lien_vb: list[HuongDanLienVB] = field(default_factory=list)
    dieu_khoan_chuyen_tiep: list[DieuKhoanChuyenTiep] = field(default_factory=list)
    kich_ban_lien_nganh: list[KichBanLienNganh] = field(default_factory=list)
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

# Chỉ lấy đích cấp Khoản/Điểm (không lấy cấp Điều — khi Action nhắm thẳng cả Điều,
# đo thực tế 2026-09-04: Điều đó LUÔN hết hiệu lực toàn bộ ở Neo4j hiện tại, không
# phải ca "bãi bỏ từng phần, phần khác còn sống" mà loại câu hỏi này cần). Lọc
# `e.hieu_luc_den IS NOT NULL` = phần này THẬT SỰ đã bị thay bởi bản mới/xoá.
# KHÔNG lọc "Điều cha còn hiệu lực" ở đây — join Python vào `bang.dieu` (đã có sẵn
# Qdrant fallback cho text rỗng, tránh viết lại logic fallback 1 lần nữa).
_Q_BAI_BO_TUNG_PHAN = """
MATCH (a:Action)-[:ENACTED_BY]->(:Norm)
MATCH (a)-[:AFFECTS]->(tgt:Component)
WHERE coalesce(a.da_duyet,false) = true AND a.loai = 'BaiBoTungPhan'
      AND tgt.loai IN ['Khoan','Diem']
MATCH (tgt)-[:HAS_VERSION]->(e:Expression)
WHERE e.hieu_luc_den IS NOT NULL
MATCH (dieu_cha:Component {loai:'Dieu'})-[:HAS_PART*1..2]->(tgt)
RETURN DISTINCT tgt.comp_id AS comp_id, tgt.duong_dan AS duong_dan, e.text AS text,
       e.hieu_luc_den AS ngay_het_hl, dieu_cha.comp_id AS dieu_cha_comp_id
"""

# Loc "con hieu luc" o cap NORM (n.tinh_trang) chu khong phai cap Dieu — quan he
# GUIDED_BY chi noi "van ban A duoc van ban B huong dan", khong gan voi 1 Dieu cu
# the nao, nen khong the dung con_hieu_luc cua tung Dieu nhu cac query khac.
_Q_GUIDED_BY = """
MATCH (a:Norm)-[:GUIDED_BY]->(b:Norm)
WHERE a.tinh_trang = 'ConHieuLuc' AND b.tinh_trang = 'ConHieuLuc' AND a.norm_id <> b.norm_id
RETURN DISTINCT a.norm_id AS norm_a, b.norm_id AS norm_b
"""

# TransitionRule KHONG gan voi 1 Component cu the (chi HAS_TRANSITION tu Norm) —
# nhung bu lai da co san dieu_kien/van_ban_ap_dung tach rieng luc ingest, khong can
# LLM tu tim doan nhu GUIDED_BY. Loc confidence>=0.8 (do thuc te 2026-09-04: chi
# loai 6/326 rule cua Norm con hieu luc, khong dang ke).
_Q_TRANSITION_RULE = """
MATCH (r:TransitionRule)
MATCH (n:Norm {norm_id: r.norm_id})
WHERE coalesce(r.da_duyet,false) = true AND n.tinh_trang = 'ConHieuLuc'
      AND coalesce(r.confidence,0) >= 0.8
RETURN r.rule_id AS rule_id, r.nguon_dieu_khoan AS nguon_dieu_khoan,
       r.dieu_kien AS dieu_kien, r.van_ban_ap_dung AS van_ban_ap_dung,
       r.dieu_kien_raw AS dieu_kien_raw, n.so_hieu AS so_hieu
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
    for r in neo.run(_Q_BAI_BO_TUNG_PHAN):
        text = r["text"]
        if not text or len(text) < _NGUONG_TEXT_TOI_THIEU:
            continue
        dieu_cha = bang.dieu.get(r["dieu_cha_comp_id"])
        if not dieu_cha or not dieu_cha.con_hieu_luc:
            continue  # Dieu cha da het hieu luc hoac khong co text dung -> khong phai ca "sach"
        bang.bai_bo_tung_phan.append(BaiBoTungPhan(
            comp_id=r["comp_id"], duong_dan=r["duong_dan"], text=text,
            ngay_het_hl=r["ngay_het_hl"], dieu_cha=dieu_cha))
    for r in neo.run(_Q_GUIDED_BY):
        if r["norm_a"] in norm_ids_co_dieu and r["norm_b"] in norm_ids_co_dieu:
            bang.huong_dan_lien_vb.append(HuongDanLienVB(**r))
    for r in neo.run(_Q_TRANSITION_RULE):
        if not r["dieu_kien"] or not r["van_ban_ap_dung"] or not r["dieu_kien_raw"]:
            continue
        bang.dieu_khoan_chuyen_tiep.append(DieuKhoanChuyenTiep(**r))
    return bang


_Q_TIM_LUAT = """
MATCH (n:Norm) WHERE n.loai_vb IN ['Luat', 'BoLuat']
  AND toLower(n.tieu_de) CONTAINS toLower($kw)
  AND NOT toLower(n.tieu_de) CONTAINS 'sửa đổi'
  AND n.tinh_trang = 'ConHieuLuc'
RETURN n.norm_id AS norm_id, n.so_hieu AS so_hieu
ORDER BY n.ngay_ban_hanh DESC
LIMIT 1
"""

_TIEN_TO_LUAT_RE = re.compile(r"^(bộ luật|luật)\s+", re.IGNORECASE)


def tu_khoa_tu_ten_luat(ten: str) -> str:
    """Rút từ khoá tìm kiếm TỪ TÊN LUẬT chính thức (không dùng từ khoá LLM tự ghi —
    đo thực tế 2026-09-05: LLM hay ghi kiểu mô tả tình huống thay vì cụm từ THẬT SỰ
    nằm trong tiêu đề) — bỏ tiền tố 'Luật '/'Bộ luật ' + phần 'số ...' phía sau."""
    t = (ten or "").strip()
    t = _TIEN_TO_LUAT_RE.sub("", t)
    t = re.split(r"\s+số\s+", t, flags=re.IGNORECASE)[0]
    return t.strip()


def tim_luat(neo: Neo4jClient, ten_luat: str) -> dict | None:
    kw = tu_khoa_tu_ten_luat(ten_luat)
    if not kw:
        return None
    rows = neo.run(_Q_TIM_LUAT, kw=kw)
    return rows[0] if rows else None


def de_xuat_kich_ban_lien_nganh(llm, neo: Neo4jClient, so_luong: int) -> list[KichBanLienNganh]:
    """Bước 0b (mới 2026-09-05) — hỏi LLM 1 LẦN DUY NHẤT đề xuất `so_luong` kịch bản
    liên ngành luật, tự động khớp tên luật vào Neo4j (không cần người duyệt — kịch
    bản khớp sai chỉ khiến `tim_luat` trả None, bị loại êm, không gây hại; kịch bản
    khớp đúng vẫn phải qua LLM tự thẩm định + omission-test ở Bước 2/3 mới được giữ)."""
    out = llm.chat_json(_SYS_LIEN_NGANH, P_DE_XUAT_KICH_BAN_LIEN_NGANH.format(n=so_luong),
                        temperature=0.6, max_tokens=2500)
    ket_qua: list[KichBanLienNganh] = []
    for kb in (out.get("kich_ban", []) if out else []):
        la = tim_luat(neo, kb.get("ten_luat_a", ""))
        lb = tim_luat(neo, kb.get("ten_luat_b", ""))
        if not la or not lb or la["norm_id"] == lb["norm_id"]:
            continue
        ket_qua.append(KichBanLienNganh(
            boi_canh=kb.get("boi_canh", ""), norm_a=la["norm_id"], so_hieu_a=la["so_hieu"],
            norm_b=lb["norm_id"], so_hieu_b=lb["so_hieu"]))
    return ket_qua


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
    ty_le_bai_bo_tung_phan: float
    mat_do_huong_dan_lien_vb: float
    ty_le_huong_dan_lien_vb: float
    ty_le_chuyen_tiep: float
    ty_le_lien_nganh: float


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
    # Khong scale theo tong_dieu nhu cac loai khac — kho ung vien (BaiBoTungPhan da
    # duyet, Dieu cha con hieu luc) la con so TUYET DOI co dinh toan corpus (~950,
    # do thuc te 2026-09-04), khong tang theo so Dieu. Ty le co dinh nho, phu thuoc
    # min() trong sinh_de() de tu cap khi tong_muc_tieu lon hon so ung vien co san.
    ty_le_bai_bo_tung_phan = 0.05

    # Mat do GUIDED_BY (cap A duoc huong dan <- B huong dan, ca 2 con hieu luc) tren
    # moi Dieu — quy mo THAT: ~21.7k cap / ~188k Dieu (do 2026-09-04) ~ 0.115. He so
    # 0.3 (nhe hon cau_truc dung 0.5 vi day la multi-hop LIEN van ban, kho hon —
    # phan lon Dieu A duoc chon se KHONG co doan tuong ung trong B, xem generate.py).
    mat_do_hdlv = len(bang.huong_dan_lien_vb) / tong_dieu
    ty_le_huong_dan_lien_vb = min(0.15, 0.05 + 0.3 * mat_do_hdlv)

    # Pool nho co dinh (326 rule confidence cao toan corpus, do 2026-09-04), giong
    # bai_bo_tung_phan — ty le nho co dinh, min() trong sinh_de() tu cap.
    ty_le_chuyen_tiep = 0.05

    # Pool kich ban do LLM de xuat 1 lan/luot chay (khong scale theo tong_dieu, giong
    # bai_bo_tung_phan/chuyen_tiep) — yield thap (~5% do thuc te 2026-09-05, kich ban
    # dung domain nhung phai thu nhieu Dieu ung vien moi ra cau dat chuan), ty le nho.
    ty_le_lien_nganh = 0.03

    ty_le_mot_buoc = max(0.10, 1.0 - ty_le_hieu_luc - ty_le_cau_truc - ty_le_bay_hieu_luc
                         - ty_le_gai_bay - ty_le_bai_bo_tung_phan - ty_le_huong_dan_lien_vb
                         - ty_le_chuyen_tiep - ty_le_lien_nganh)

    return KeHoach(
        ty_le_con_hieu_luc=ty_le_con_hieu_luc, ty_le_co_quan_he_hieu_luc=ty_le_co_qhhl,
        mat_do_tham_chieu_noi_bo=mat_do_cross_ref, ty_le_mot_buoc=ty_le_mot_buoc,
        ty_le_cau_truc=ty_le_cau_truc, ty_le_hieu_luc=ty_le_hieu_luc,
        ty_le_gai_bay=ty_le_gai_bay, ty_le_bay_hieu_luc=ty_le_bay_hieu_luc,
        ty_le_bai_bo_tung_phan=ty_le_bai_bo_tung_phan,
        mat_do_huong_dan_lien_vb=mat_do_hdlv, ty_le_huong_dan_lien_vb=ty_le_huong_dan_lien_vb,
        ty_le_chuyen_tiep=ty_le_chuyen_tiep, ty_le_lien_nganh=ty_le_lien_nganh)
