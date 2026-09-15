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
    huống thực tế) — lấy từ bộ kịch bản CỐ ĐỊNH đã kiểm chứng tay (`KICH_BAN_LIEN_NGANH_CO_DINH`),
    KHÔNG còn để LLM tự đề xuất mỗi lượt chạy (bỏ 2026-09-15 — LLM hay bịa kịch bản
    không khớp corpus thật, yield thấp). KHÔNG dựa cạnh trích dẫn có sẵn (khác
    `ThamChieuNoiBo`/`HuongDanLienVB`) vì 2 luật này KHÔNG trích dẫn nhau — chỉ tình cờ
    cùng cần trong 1 thủ tục. Xem thảo luận kiến trúc 2026-09-05 (data.py::P_LIEN_NGANH
    trong prompts.py)."""
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


# Sua 2026-09-15 (phat hien khi thu bo 20 "nut cau noi" lien nganh):
# 1. `tinh_trang = 'ConHieuLuc'` qua chat -- da so LUAT LON deu tung bi SUA nen ban
#    GOC luon o trang thai 'HetHieuLucMotPhan' (van dang hieu luc phan lon, chi 1
#    phan bi thay), con ban 'ConHieuLuc' sach chi la LUAT SUA DOI (da bi loai boi
#    dieu kien "khong chua 'sua doi'" ben duoi) -- ket qua: khong tim thay hau het
#    luat lon hay bi sua (Dau thau, Xu ly VPHC, Cac to chuc tin dung, Xay dung...).
#    Nay chap nhan CA HAI trang thai, uu tien ConHieuLuc khi phai chon 1.
# 2. Bo dieu kien `tinh_trang` cung trong Cypher (loc o Python) de lay dc ca 2 nhom
#    tinh_trang can, roi tu xep hang.
_Q_TIM_LUAT = """
MATCH (n:Norm) WHERE n.loai_vb IN ['Luat', 'BoLuat']
  AND toLower(n.tieu_de) CONTAINS toLower($kw)
  AND NOT toLower(n.tieu_de) CONTAINS 'sửa đổi'
  AND n.tinh_trang IN ['ConHieuLuc', 'HetHieuLucMotPhan']
RETURN n.norm_id AS norm_id, n.so_hieu AS so_hieu, n.tieu_de AS tieu_de,
       n.tinh_trang AS tinh_trang, n.ngay_ban_hanh AS ngay_ban_hanh
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


def _la_luat_dung_chu_de(tieu_de: str, kw_low: str) -> bool:
    """Bug thật 2026-09-15: CONTAINS ở BẤT KỲ ĐÂU trong câu bắt nhầm — vd từ khoá
    "Đầu tư"/"Doanh nghiệp" bị "Luật Quản lý và đầu tư vốn nhà nước tại doanh
    nghiệp" (chủ đề khác hẳn, chỉ tình cờ chứa 2 từ đó ở giữa câu) nuốt mất, vì
    luật ĐÚNG (Luật Đầu tư/Luật Doanh nghiệp) không có bản `ConHieuLuc` sạch để
    cạnh tranh. Sửa: sau khi bỏ tiền tố "Luật "/"Bộ luật ", phần còn lại phải BẮT
    ĐẦU BẰNG từ khoá — đúng cấu trúc tên luật thật ("Luật Đầu tư số ...",
    KHÔNG PHẢI từ khoá nằm giữa 1 câu mô tả dài hơn)."""
    loi = _TIEN_TO_LUAT_RE.sub("", (tieu_de or "").strip(), count=1)
    return loi.lower().startswith(kw_low)


def _ngay_key(r) -> tuple:
    n = r.get("ngay_ban_hanh")
    return (n.year, n.month, n.day) if n is not None else (0, 0, 0)


def tim_luat(neo: Neo4jClient, ten_luat: str) -> dict | None:
    kw = tu_khoa_tu_ten_luat(ten_luat)
    if not kw:
        return None
    rows = neo.run(_Q_TIM_LUAT, kw=kw)
    if not rows:
        return None
    kw_low = kw.strip().lower()
    dung_chu_de = [r for r in rows if _la_luat_dung_chu_de(r["tieu_de"], kw_low)]
    # Khong co ca nao "dung chu de" (khop CONTAINS o giua cau vd doi voi cum tu dai/
    # hiem) -> fallback ve toan bo ket qua CONTAINS cu, an toan hon la tra None.
    ung_vien = dung_chu_de or rows
    ung_vien = sorted(ung_vien, key=_ngay_key, reverse=True)          # moi nhat truoc
    ung_vien.sort(key=lambda r: r["tinh_trang"] != "ConHieuLuc")      # ConHieuLuc truoc (sort on dinh)
    return {"norm_id": ung_vien[0]["norm_id"], "so_hieu": ung_vien[0]["so_hieu"]}


# Bo kich ban lien nganh CO DINH - sinh co he thong tu catalog THAT (2026-09-15):
# dua toan bo 231 Luat/Bo luat con hieu luc (khong tinh ban 'sua doi') cho LLM
# chon CAP tu chinh danh sach nay (khong duoc bia so hieu khac) + viet boi_canh -
# khac han cach cu (LLM tu do de xuat ten luat roi fuzzy-match, ~50-75% khop) o
# cho MOI de xuat da bao dam khop 100% vi chon tu danh sach dong. 4 vong, moi vong
# loai tru cac cap da chon truoc do. Ket qua: 156 cap, cham 160/231 luat (69%) -
# tang manh so voi 19/231 (8%) cua bo 20 nut chon tay ban dau. Moi dong: (boi_canh,
# so_hieu_a, so_hieu_b) - dung THANG so_hieu (khong qua ten_luat/tim_luat nua, vi
# da co san so hieu CHINH XAC tu catalog that, tra truc tiep qua _Q_LUAT_THEO_SOHIEU).
KICH_BAN_LIEN_NGANH_CO_DINH: list[tuple[str, str, str]] = [
    ("Người lao động bị tai nạn lao động trong thời gian thử việc, yêu cầu bồi thường thiệt hại "
     "ngoài hợp đồng và trợ cấp tai nạn lao động.",
     "91/2015/QH13", "45/2019/QH14"),
    ("Vợ chồng ly hôn, tranh chấp quyền nuôi con và chia tài sản chung là bất động sản hình thành "
     "trong thời kỳ hôn nhân.",
     "52/2014/QH13", "91/2015/QH13"),
    ("Tranh chấp hợp đồng chuyển nhượng quyền sử dụng đất vô hiệu do không tuân thủ điều kiện về "
     "hình thức và chủ thể.",
     "31/2024/QH15", "91/2015/QH13"),
    ("Xét xử vụ án hình sự về tội cố ý gây thương tích, cần áp dụng Bộ luật Hình sự để định tội và "
     "Bộ luật Tố tụng hình sự để đánh giá chứng cứ.",
     "100/2015/QH13", "101/2015/QH13"),
    ("Người bị thiệt hại do tội phạm xâm phạm tính mạng, sức khỏe yêu cầu bồi thường thiệt hại "
     "theo quy định của Bộ luật Dân sự.",
     "100/2015/QH13", "91/2015/QH13"),
    ("Điều tra vụ án hình sự có dấu hiệu tội phạm, xác định thẩm quyền điều tra của cơ quan điều "
     "tra theo Luật Tổ chức cơ quan điều tra hình sự.",
     "101/2015/QH13", "99/2015/QH13"),
    ("Thi hành bản án dân sự về tranh chấp hợp đồng vay tài sản, áp dụng thủ tục thi hành án dân "
     "sự để kê biên tài sản.",
     "92/2015/QH13", "26/2008/QH12"),
    ("Tòa án giải quyết tranh chấp thương mại có thỏa thuận trọng tài, xem xét thẩm quyền của "
     "trọng tài theo Luật Trọng tài thương mại.",
     "92/2015/QH13", "54/2010/QH12"),
    ("Tranh chấp hợp đồng mua bán hàng hóa giữa các doanh nghiệp, áp dụng Luật Doanh nghiệp để xác "
     "định tư cách pháp lý và Luật Thương mại để giải quyết hợp đồng.",
     "59/2020/QH14", "36/2005/QH11"),
    ("Thành viên công ty trách nhiệm hữu hạn khởi kiện yêu cầu bồi thường thiệt hại do hành vi vi "
     "phạm nghĩa vụ của người quản lý.",
     "59/2020/QH14", "91/2015/QH13"),
    ("Xử lý hành vi xâm phạm quyền sở hữu trí tuệ đối với nhãn hiệu, áp dụng biện pháp dân sự và "
     "truy cứu trách nhiệm hình sự.",
     "50/2005/QH11", "100/2015/QH13"),
    ("Tranh chấp hợp đồng chuyển giao quyền sử dụng đối tượng sở hữu công nghiệp, kết hợp quy định "
     "của Luật Sở hữu trí tuệ và Luật Thương mại.",
     "50/2005/QH11", "36/2005/QH11"),
    ("Phân biệt hành vi vi phạm hành chính và tội phạm trong lĩnh vực giao thông đường bộ, áp dụng "
     "Luật Xử lý vi phạm hành chính và Bộ luật Hình sự.",
     "15/2012/QH13", "100/2015/QH13"),
    ("Công dân khiếu nại quyết định xử phạt vi phạm hành chính, kết hợp thủ tục khiếu nại và xử lý "
     "vi phạm hành chính.",
     "15/2012/QH13", "02/2011/QH13"),
    ("Khởi kiện quyết định hành chính bị khiếu nại ra Tòa án, áp dụng Luật Khiếu nại và Luật Tố "
     "tụng hành chính.",
     "02/2011/QH13", "93/2015/QH13"),
    ("Tố cáo hành vi tham nhũng trong cơ quan nhà nước, kết hợp Luật Tố cáo và Luật Phòng, chống "
     "tham nhũng để bảo vệ người tố cáo.",
     "25/2018/QH14", "36/2018/QH14"),
    ("Xử lý hành vi gây ô nhiễm môi trường, áp dụng Luật Bảo vệ môi trường và Bộ luật Hình sự về "
     "tội gây ô nhiễm môi trường.",
     "72/2020/QH14", "100/2015/QH13"),
    ("Yêu cầu bồi thường thiệt hại do ô nhiễm môi trường gây ra đối với sức khỏe và tài sản của cá "
     "nhân.",
     "72/2020/QH14", "91/2015/QH13"),
    ("Tai nạn lao động xảy ra tại nơi làm việc, xác định trách nhiệm của người sử dụng lao động và "
     "chế độ bảo hiểm tai nạn lao động.",
     "45/2019/QH14", "84/2015/QH13"),
    ("Tranh chấp về quyền thành lập và gia nhập tổ chức công đoàn cơ sở tại doanh nghiệp, kết hợp "
     "Bộ luật Lao động và Luật Công đoàn.",
     "45/2019/QH14", "50/2024/QH15"),
    ("Người bệnh khám bệnh, chữa bệnh trái tuyến và yêu cầu thanh toán bảo hiểm y tế, áp dụng Luật "
     "Bảo hiểm y tế và Luật Khám bệnh, chữa bệnh.",
     "25/2008/QH12", "15/2023/QH15"),
    ("Kinh doanh dược phẩm không đảm bảo an toàn thực phẩm, xử lý vi phạm theo Luật Dược và Luật "
     "An toàn thực phẩm.",
     "105/2016/QH13", "55/2010/QH12"),
    ("Sản xuất, buôn bán thực phẩm giả gây ngộ độc, truy cứu trách nhiệm hình sự về tội vi phạm an "
     "toàn thực phẩm.",
     "55/2010/QH12", "100/2015/QH13"),
    ("Công ty chứng khoán vi phạm quy định về vốn pháp định và cho vay chứng khoán, xử lý theo "
     "Luật Chứng khoán và Luật Các tổ chức tín dụng.",
     "54/2019/QH14", "32/2024/QH15"),
    ("Hành vi thao túng thị trường chứng khoán bị truy cứu trách nhiệm hình sự, kết hợp Luật Chứng "
     "khoán và Bộ luật Hình sự.",
     "54/2019/QH14", "100/2015/QH13"),
    ("Xử lý nợ xấu của tổ chức tín dụng, áp dụng quy định của Ngân hàng Nhà nước và Luật Các tổ "
     "chức tín dụng.",
     "46/2010/QH12", "32/2024/QH15"),
    ("Hành vi rửa tiền có nguồn gốc từ tội phạm, kết hợp Luật Phòng, chống rửa tiền và Bộ luật "
     "Hình sự.",
     "14/2022/QH15", "100/2015/QH13"),
    ("Báo cáo giao dịch đáng ngờ của tổ chức tín dụng, áp dụng Luật Phòng, chống rửa tiền và Luật "
     "Ngân hàng Nhà nước.",
     "14/2022/QH15", "46/2010/QH12"),
    ("Kinh doanh bất động sản nhà ở hình thành trong tương lai, kết hợp Luật Nhà ở và Luật Kinh "
     "doanh bất động sản.",
     "27/2023/QH15", "29/2023/QH15"),
    ("Dự án đầu tư xây dựng nhà ở thương mại, cần áp dụng Luật Nhà ở và Luật Đất đai để xác định "
     "quyền sử dụng đất.",
     "27/2023/QH15", "31/2024/QH15"),
    ("Chuyển nhượng dự án bất động sản, kết hợp Luật Kinh doanh bất động sản và Luật Đất đai về "
     "điều kiện chuyển nhượng.",
     "29/2023/QH15", "31/2024/QH15"),
    ("Xử phạt vi phạm hành chính về lấn chiếm đất đai, áp dụng Luật Đất đai và Luật Xử lý vi phạm "
     "hành chính.",
     "31/2024/QH15", "15/2012/QH13"),
    ("Xác định nghĩa vụ thuế sử dụng đất phi nông nghiệp đối với thửa đất ở, kết hợp Luật Đất đai "
     "và Luật Thuế sử dụng đất phi nông nghiệp.",
     "31/2024/QH15", "48/2010/QH12"),
    ("Kê khai và nộp thuế thu nhập doanh nghiệp, áp dụng Luật Quản lý thuế và Luật Thuế thu nhập "
     "doanh nghiệp.",
     "78/2006/QH11", "67/2025/QH15"),
    ("Hóa đơn giá trị gia tăng trong giao dịch thương mại, kết hợp Luật Thuế giá trị gia tăng và "
     "Luật Thương mại.",
     "48/2024/QH15", "36/2005/QH11"),
    ("Hạch toán thuế giá trị gia tăng đầu vào, áp dụng Luật Thuế giá trị gia tăng và Luật Kế toán.",
     "48/2024/QH15", "88/2015/QH13"),
    ("Lập báo cáo tài chính của doanh nghiệp, kết hợp Luật Kế toán và Luật Doanh nghiệp về trách "
     "nhiệm của người đại diện.",
     "88/2015/QH13", "59/2020/QH14"),
    ("Xử lý kỷ luật cán bộ, công chức, viên chức, áp dụng Luật Viên chức và Luật Cán bộ, công "
     "chức.",
     "58/2010/QH12", "80/2025/QH15"),
    ("Đấu giá tài sản là tài sản công tại đơn vị sự nghiệp công lập: phải áp dụng Luật Đấu giá tài "
     "sản về trình tự, thủ tục đấu giá và Luật Quản lý, sử dụng tài sản công về việc xác lập quyền "
     "sở hữu, xử lý, bán, thanh lý tài sản công.",
     "01/2016/QH14", "15/2017/QH14"),
    ("Ca bệnh truyền nhiễm nguy hiểm tại cơ sở khám bệnh, chữa bệnh: phải áp dụng Luật Phòng, "
     "chống bệnh truyền nhiễm về phân loại, biện pháp cách ly, khai báo dịch và Luật Khám bệnh, "
     "chữa bệnh về quyền, nghĩa vụ người bệnh, quy trình chuyên môn trong khám bệnh, chữa bệnh.",
     "03/2007/QH12", "15/2023/QH15"),
    ("Tranh chấp về sai số đo lường trong mua bán hàng hóa tiêu dùng: phải áp dụng Luật Đo lường "
     "về đơn vị đo, phương tiện đo, kiểm định và Luật Bảo vệ quyền lợi người tiêu dùng về thông "
     "tin, chất lượng hàng hóa và trách nhiệm bồi thường cho người tiêu dùng.",
     "04/2011/QH13", "19/2023/QH15"),
    ("Doanh nghiệp nhỏ và vừa tham gia gói thầu mua sắm công: phải áp dụng Luật Hỗ trợ doanh "
     "nghiệp nhỏ và vừa về ưu đãi, hỗ trợ và Luật Đấu thầu về điều kiện dự thầu, ưu đãi trong lựa "
     "chọn nhà thầu, bảo đảm cạnh tranh.",
     "04/2017/QH14", "22/2023/QH15"),
    ("Xử lý tình huống sử dụng vũ khí, công cụ hỗ trợ của Cảnh sát cơ động: phải áp dụng Luật Cảnh "
     "sát cơ động về thẩm quyền, nguyên tắc hoạt động và Luật Quản lý, sử dụng vũ khí, vật liệu nổ "
     "và công cụ hỗ trợ về điều kiện mang, sử dụng, bảo quản.",
     "04/2022/QH15", "42/2024/QH15"),
    ("Hàng hóa nhập khẩu không đạt chất lượng: phải áp dụng Luật Chất lượng sản phẩm, hàng hoá về "
     "tiêu chuẩn công bố, kiểm tra chất lượng và Luật Tiêu chuẩn và quy chuẩn kỹ thuật về ban "
     "hành, áp dụng tiêu chuẩn, quy chuẩn kỹ thuật.",
     "05/2007/QH12", "68/2006/QH11"),
    ("Bảo vệ thông tin bí mật trong hoạt động cơ yếu và an toàn thông tin mạng: phải áp dụng Luật "
     "Cơ yếu về quản lý, sử dụng mật mã và Luật An toàn thông tin mạng về bảo vệ hệ thống thông "
     "tin, dữ liệu, phòng chống tấn công mạng.",
     "05/2011/QH13", "86/2015/QH13"),
    ("Xuất khẩu, nhập khẩu hàng hóa có yếu tố nước ngoài: phải áp dụng Luật Quản lý ngoại thương "
     "về biện pháp quản lý, giấy phép, hạn ngạch và Luật Hải quan về thủ tục hải quan, kiểm tra, "
     "giám sát, thu thuế xuất khẩu, thuế nhập khẩu.",
     "05/2017/QH14", "54/2014/QH13"),
    ("Phim điện ảnh bị xâm phạm bản quyền: phải áp dụng Luật Điện ảnh về điều kiện phổ biến, lưu "
     "hành phim và Luật Sở hữu trí tuệ về quyền tác giả, quyền liên quan, xử lý hành vi sao chép, "
     "phân phối trái phép.",
     "05/2022/QH15", "50/2005/QH11"),
    ("Xử lý vi phạm trên vùng biển, đảo: phải áp dụng Luật Biên giới quốc gia về chế độ pháp lý "
     "đường biên giới, vùng biển và Luật Cảnh sát biển Việt Nam về thẩm quyền tuần tra, kiểm soát, "
     "xử lý vi phạm trên biển.",
     "06/2003/QH11", "33/2018/QH14"),
    ("Sự cố hóa chất gây cháy nổ tại kho, nhà máy: phải áp dụng Luật Hóa chất về phân loại, bảo "
     "quản, vận chuyển hóa chất nguy hiểm và Luật Phòng cháy, chữa cháy và cứu nạn, cứu hộ về "
     "phòng cháy, chữa cháy, cứu nạn, cứu hộ.",
     "06/2007/QH12", "55/2024/QH15"),
    ("Khen thưởng đối với cán bộ, công chức có thành tích: phải áp dụng Luật Thi đua, Khen thưởng "
     "về hình thức, tiêu chuẩn khen thưởng và Luật Cán bộ, công chức về quản lý, đánh giá, quyền "
     "lợi, kỷ luật cán bộ, công chức.",
     "06/2022/QH15", "80/2025/QH15"),
    ("Hợp đồng chuyển giao công nghệ có đối tượng là bí quyết kỹ thuật, sáng chế: phải áp dụng "
     "Luật Chuyển giao công nghệ về nội dung, điều kiện chuyển giao và Luật Sở hữu trí tuệ về bảo "
     "hộ sáng chế, bí mật kinh doanh, quyền sở hữu công nghiệp.",
     "07/2017/QH14", "50/2005/QH11"),
    ("Ủy thác tư pháp trong tố tụng dân sự có yếu tố nước ngoài: phải áp dụng Luật Tương trợ tư "
     "pháp về nguyên tắc, trình tự tương trợ tư pháp và Bộ luật Tố tụng dân sự về thẩm quyền, thủ "
     "tục ủy thác tư pháp, công nhận, cho thi hành bản án nước ngoài.",
     "08/2007/QH12", "92/2015/QH13"),
    ("Quản lý đào tạo đại học, sau đại học: phải áp dụng Luật Giáo dục đại học về tổ chức, hoạt "
     "động cơ sở giáo dục đại học, mở ngành, tuyển sinh và Luật Giáo dục về hệ thống giáo dục quốc "
     "dân, quyền, nghĩa vụ học tập.",
     "08/2012/QH13", "43/2019/QH14"),
    ("Quản lý, vận hành công trình thủy lợi gắn với đê điều trong mùa lũ: phải áp dụng Luật Thủy "
     "lợi về khai thác, bảo vệ công trình thủy lợi và Luật Đê điều về phân cấp đê, hộ đê, xử lý sự "
     "cố đê điều.",
     "08/2017/QH14", "79/2006/QH11"),
    ("Hoạt động đại lý bảo hiểm qua ngân hàng: phải áp dụng Luật Kinh doanh bảo hiểm về hợp đồng "
     "bảo hiểm, đại lý bảo hiểm và Luật Các tổ chức tín dụng về hoạt động ngân hàng, bảo vệ khách "
     "hàng, quản lý rủi ro.",
     "08/2022/QH15", "32/2024/QH15"),
    ("Quảng cáo thuốc lá, sản phẩm có hình ảnh thuốc lá: phải áp dụng Luật Phòng, chống tác hại "
     "của thuốc lá về cấm quảng cáo, khuyến mại thuốc lá và Luật Quảng cáo về điều kiện, nội dung, "
     "phương tiện quảng cáo.",
     "09/2012/QH13", "16/2012/QH13"),
    ("Phát triển du lịch gắn với bảo vệ môi trường tại khu, điểm du lịch: phải áp dụng Luật Du "
     "lịch về quản lý khu du lịch, kinh doanh dịch vụ du lịch và Luật Bảo vệ môi trường về đánh "
     "giá tác động môi trường, bảo vệ cảnh quan, xử lý chất thải.",
     "09/2017/QH14", "72/2020/QH14"),
    ("Yêu cầu bồi thường nhà nước trong tố tụng hành chính: phải áp dụng Luật Trách nhiệm bồi "
     "thường của nhà nước về căn cứ, phạm vi, thủ tục bồi thường và Luật Tố tụng hành chính về "
     "khởi kiện, thẩm quyền giải quyết vụ án hành chính.",
     "10/2017/QH14", "93/2015/QH13"),
    ("Thực hiện dân chủ ở xã, phường, thị trấn: phải áp dụng Luật Thực hiện dân chủ ở cơ sở về "
     "hình thức công khai, bàn, quyết định, giám sát và Luật Tổ chức chính quyền địa phương về "
     "nhiệm vụ, quyền hạn của chính quyền địa phương cấp xã.",
     "10/2022/QH15", "72/2025/QH15"),
    ("Xử lý người chưa thành niên vi phạm pháp luật: phải áp dụng Luật Trẻ em về quyền trẻ em, bảo "
     "vệ trẻ em và Luật Tư pháp người chưa thành niên về nguyên tắc xử lý, biện pháp thay thế, thủ "
     "tục tố tụng thân thiện.",
     "102/2016/QH13", "59/2024/QH15"),
    ("Yêu cầu cung cấp thông tin liên quan đến dữ liệu cá nhân: phải áp dụng Luật Tiếp cận thông "
     "tin về quyền tiếp cận thông tin, trình tự cung cấp thông tin và Luật Dữ liệu về quản lý, kết "
     "nối, chia sẻ dữ liệu, bảo vệ dữ liệu.",
     "104/2016/QH13", "60/2024/QH15"),
    ("Kinh doanh dược trực tuyến, thu thập dữ liệu người bệnh: phải áp dụng Luật Dược về điều kiện "
     "kinh doanh dược, bảo quản, phân phối thuốc và Luật Bảo vệ dữ liệu cá nhân về xử lý dữ liệu "
     "cá nhân, quyền của chủ thể dữ liệu.",
     "105/2016/QH13", "91/2025/QH15"),
    ("Nhập khẩu hàng hóa chịu thuế giá trị gia tăng: phải áp dụng Luật Thuế xuất khẩu, thuế nhập "
     "khẩu về đối tượng chịu thuế, trị giá tính thuế, thuế suất và Luật Thuế giá trị gia tăng về "
     "khấu trừ, hoàn thuế, giá tính thuế.",
     "107/2016/QH13", "48/2024/QH15"),
    ("Nội luật hóa điều ước quốc tế bằng văn bản quy phạm pháp luật: phải áp dụng Luật Điều ước "
     "quốc tế về ký kết, gia nhập, thực hiện điều ước và Luật Ban hành văn bản quy phạm pháp luật "
     "về thẩm quyền, trình tự ban hành văn bản.",
     "108/2016/QH13", "64/2025/QH15"),
    ("Hoạt động cứu trợ khẩn cấp cho người dân vùng thiên tai: phải áp dụng Luật Hoạt động chữ "
     "thập đỏ về vận động, tiếp nhận, phân phối nguồn cứu trợ và Luật Phòng, chống thiên tai về "
     "ứng phó, cứu trợ, khắc phục hậu quả thiên tai.",
     "11/2008/QH12", "33/2013/QH13"),
    ("Trợ giúp pháp lý miễn phí trong vụ án hình sự: phải áp dụng Luật Trợ giúp pháp lý về đối "
     "tượng, điều kiện, người thực hiện trợ giúp pháp lý và Luật Luật sư về hành nghề luật sư, "
     "quyền, nghĩa vụ của luật sư.",
     "11/2017/QH14", "65/2006/QH11"),
    ("Thăm dò, khai thác dầu khí: phải áp dụng Luật Dầu khí về hợp đồng dầu khí, quyền, nghĩa vụ "
     "nhà thầu và Luật Địa chất và Khoáng sản về điều tra cơ bản địa chất, thăm dò, khai thác "
     "khoáng sản.",
     "12/2022/QH15", "54/2024/QH15"),
    ("Bảo vệ đối tượng cảnh vệ: phải áp dụng Luật Cảnh vệ về đối tượng, biện pháp cảnh vệ và Luật "
     "Công an nhân dân về chức năng, nhiệm vụ, quyền hạn của Công an nhân dân trong bảo đảm an "
     "ninh, trật tự.",
     "13/2017/QH14", "37/2018/QH14"),
    ("Bạo lực gia đình trên cơ sở giới: phải áp dụng Luật Phòng, chống bạo lực gia đình về biện "
     "pháp bảo vệ, xử lý hành vi bạo lực và Luật Bình đẳng giới về thúc đẩy bình đẳng giới, cấm "
     "phân biệt đối xử.",
     "13/2022/QH15", "73/2006/QH11"),
    ("Tuyên truyền, phổ biến pháp luật và công khai thông tin pháp luật: phải áp dụng Luật Phổ "
     "biến, giáo dục pháp luật về nội dung, hình thức phổ biến và Luật Tiếp cận thông tin về công "
     "khai thông tin, quyền yêu cầu cung cấp thông tin.",
     "14/2012/QH13", "104/2016/QH13"),
    ("Trưng mua, trưng dụng tài sản phục vụ quốc phòng, khu quân sự: phải áp dụng Luật Trưng mua, "
     "trưng dụng tài sản về thẩm quyền, trình tự, bồi thường và Luật Quản lý, bảo vệ công trình "
     "quốc phòng và khu quân sự về phạm vi bảo vệ, sử dụng tài sản trong khu quân sự.",
     "15/2008/QH12", "25/2023/QH15"),
    ("Khai thác rừng gắn với bảo tồn đa dạng sinh học: phải áp dụng Luật Lâm nghiệp về phân loại "
     "rừng, khai thác, chuyển mục đích sử dụng rừng và Luật Đa dạng sinh học về bảo tồn loài, khu "
     "bảo tồn, hành lang đa dạng sinh học.",
     "16/2017/QH14", "20/2008/QH12"),
    ("Kiểm soát giá độc quyền, hành vi lạm dụng vị trí thống lĩnh thị trường: phải áp dụng Luật "
     "Giá về quản lý, bình ổn giá, hiệp thương giá và Luật Cạnh tranh về hành vi hạn chế cạnh "
     "tranh, kiểm soát tập trung kinh tế.",
     "16/2023/QH15", "23/2018/QH14"),
    ("Hợp tác xã sử dụng vốn, tài sản nhà nước: phải áp dụng Luật Hợp tác xã về tổ chức, quản lý, "
     "tài chính hợp tác xã và Luật Ngân sách nhà nước về lập, chấp hành, quyết toán ngân sách, hỗ "
     "trợ từ ngân sách.",
     "17/2023/QH15", "89/2025/QH15"),
    ("Quản lý, khai thác tài nguyên biển, hải đảo: phải áp dụng Luật Biển Việt Nam về vùng biển, "
     "chế độ pháp lý và Luật Tài nguyên, môi trường biển và hải đảo về điều tra, quản lý, khai "
     "thác, bảo vệ tài nguyên biển.",
     "18/2012/QH13", "82/2015/QH13"),
    ("Nuôi trồng, khai thác thủy sản và kiểm dịch động vật thủy sản: phải áp dụng Luật Thủy sản về "
     "nuôi trồng, khai thác, bảo vệ nguồn lợi thủy sản và Luật Thú y về phòng, chống dịch bệnh "
     "động vật, kiểm dịch.",
     "18/2017/QH14", "79/2015/QH13"),
    ("Giao dịch thương mại điện tử xâm phạm quyền lợi người tiêu dùng: phải áp dụng Luật Bảo vệ "
     "quyền lợi người tiêu dùng về trách nhiệm của tổ chức, cá nhân kinh doanh và Luật Thương mại "
     "điện tử về hoạt động thương mại điện tử, thông tin, hợp đồng điện tử.",
     "19/2023/QH15", "122/2025/QH15"),
    ("Tính thuế thu nhập cá nhân đối với thu nhập từ tiền lương, tiền công của người lao động làm "
     "việc theo hợp đồng lao động tại doanh nghiệp; phải kết hợp quy định về người nộp thuế, thu "
     "nhập chịu thuế, giảm trừ gia cảnh theo Luật Thuế thu nhập cá nhân với xác định quan hệ lao "
     "động, hợp đồng lao động, thời giờ làm việc và tiền lương theo Bộ luật Lao động.",
     "109/2025/QH15", "45/2019/QH14"),
    ("Xử lý nghĩa vụ thuế thu nhập cá nhân khi cá nhân chuyển nhượng phần vốn góp hoặc nhận cổ tức "
     "từ công ty; cần đối chiếu quy định thuế TNCN với quy định của Luật Doanh nghiệp về chuyển "
     "nhượng phần vốn góp, phân chia lợi nhuận và xác định thu nhập của thành viên, cổ đông.",
     "109/2025/QH15", "59/2020/QH14"),
    ("Kê khai, nộp thuế thu nhập cá nhân của cá nhân kinh doanh bất động sản khi chuyển nhượng nhà "
     "ở, quyền sử dụng đất; phải kết hợp Luật Thuế thu nhập cá nhân với Luật Kinh doanh bất động "
     "sản về điều kiện giao dịch, hợp đồng chuyển nhượng và xác định giá chuyển nhượng.",
     "109/2025/QH15", "29/2023/QH15"),
    ("Xác định thu nhập chịu thuế thu nhập cá nhân từ chuyển nhượng quyền sử dụng đất, thuê đất, "
     "thừa kế hoặc tặng cho quyền sử dụng đất; cần áp dụng Luật Thuế thu nhập cá nhân cùng Luật "
     "Đất đai để xác định quyền sử dụng đất, giá đất và căn cứ pháp lý của giao dịch.",
     "109/2025/QH15", "31/2024/QH15"),
    ("Giải quyết tranh chấp về tiền thuế thu nhập cá nhân phát sinh từ hợp đồng mua bán, tặng cho "
     "tài sản; phải kết hợp Luật Thuế thu nhập cá nhân với Bộ luật Dân sự về hiệu lực hợp đồng, "
     "nghĩa vụ thanh toán và quyền sở hữu tài sản.",
     "109/2025/QH15", "91/2015/QH13"),
    ("Xử lý việc chi trả bảo hiểm tiền gửi cho người gửi tiền khi tổ chức tín dụng bị phá sản hoặc "
     "mất khả năng chi trả; cần kết hợp Luật Bảo hiểm tiền gửi với Luật Các tổ chức tín dụng về "
     "kiểm soát đặc biệt, phá sản và quyền của người gửi tiền.",
     "111/2025/QH15", "32/2024/QH15"),
    ("Đánh giá phạm vi bảo hiểm tiền gửi và trách nhiệm của Ngân hàng Nhà nước trong giám sát an "
     "toàn hệ thống; phải kết hợp Luật Bảo hiểm tiền gửi với Luật Ngân hàng Nhà nước Việt Nam về "
     "chính sách tiền tệ, thanh tra, giám sát ngân hàng.",
     "111/2025/QH15", "46/2010/QH12"),
    ("Điều tra, xử lý hành vi tấn công mạng làm lộ dữ liệu cá nhân, dữ liệu hệ thống thông tin; "
     "cần kết hợp Luật An ninh mạng với Luật Dữ liệu về bảo vệ dữ liệu, chia sẻ dữ liệu và trách "
     "nhiệm của cơ quan, tổ chức.",
     "116/2025/QH15", "60/2024/QH15"),
    ("Xử lý vi phạm khi thu thập, mua bán, sử dụng trái phép dữ liệu cá nhân trên không gian mạng; "
     "phải kết hợp Luật An ninh mạng với Luật Bảo vệ dữ liệu cá nhân về nguyên tắc xử lý dữ liệu, "
     "quyền của chủ thể dữ liệu và biện pháp bảo vệ.",
     "116/2025/QH15", "91/2025/QH15"),
    ("Truy cứu trách nhiệm hình sự đối với hành vi xâm nhập trái phép hệ thống thông tin, phát tán "
     "mã độc hoặc chiếm đoạt dữ liệu; cần kết hợp Luật An ninh mạng với Bộ luật Hình sự về các tội "
     "danh trong lĩnh vực công nghệ thông tin, mạng máy tính.",
     "116/2025/QH15", "100/2015/QH13"),
    ("Từ chối cung cấp thông tin thuộc bí mật nhà nước cho công dân theo yêu cầu tiếp cận thông "
     "tin; phải kết hợp Luật Bảo vệ bí mật nhà nước với Luật Tiếp cận thông tin về phạm vi thông "
     "tin được tiếp cận và các trường hợp hạn chế, từ chối cung cấp.",
     "117/2025/QH15", "104/2016/QH13"),
    ("Quản lý, lưu trữ, truyền đưa thông tin trong hệ thống thông tin có yếu tố bí mật nhà nước; "
     "cần áp dụng Luật Bảo vệ bí mật nhà nước cùng Luật Công nghệ thông tin về ứng dụng công nghệ "
     "thông tin, an toàn thông tin và trách nhiệm của tổ chức, cá nhân.",
     "117/2025/QH15", "67/2006/QH11"),
    ("Hoạt động giám sát của Hội đồng nhân dân đối với chính quyền địa phương trong việc thực hiện "
     "nhiệm vụ, ngân sách và chính sách tại địa phương; phải kết hợp Luật Hoạt động giám sát của "
     "Quốc hội và Hội đồng nhân dân với Luật Tổ chức chính quyền địa phương về thẩm quyền, trách "
     "nhiệm và hình thức giám sát.",
     "121/2025/QH15", "72/2025/QH15"),
    ("Chất vấn và xem xét trách nhiệm của thành viên Chính phủ trước Quốc hội về việc thực hiện "
     "chính sách, pháp luật; cần kết hợp Luật Hoạt động giám sát của Quốc hội và Hội đồng nhân dân "
     "với Luật Tổ chức chính phủ về nhiệm vụ, quyền hạn và trách nhiệm của Chính phủ, Thủ tướng, "
     "Bộ trưởng.",
     "121/2025/QH15", "63/2025/QH15"),
    ("Giải quyết tranh chấp hợp đồng mua bán hàng hóa qua sàn thương mại điện tử, xác thực chữ ký "
     "điện tử và dữ liệu điện tử làm chứng cứ; phải kết hợp Luật Thương mại điện tử với Luật Giao "
     "dịch điện tử về giá trị pháp lý của thông điệp dữ liệu, chữ ký số và hợp đồng điện tử.",
     "122/2025/QH15", "20/2023/QH15"),
    ("Xác định nghĩa vụ của thương nhân khi cung cấp dịch vụ thương mại qua môi trường điện tử, xử "
     "lý vi phạm hợp đồng mua bán trực tuyến; phải kết hợp Luật Thương mại điện tử với Luật Thương "
     "mại về hoạt động mua bán hàng hóa, cung ứng dịch vụ và chế tài thương mại.",
     "122/2025/QH15", "36/2005/QH11"),
    ("Giải quyết quan hệ giữa cơ sở giáo dục nghề nghiệp, người học và doanh nghiệp trong đào tạo "
     "nghề gắn với hợp đồng lao động, học nghề, thử việc; cần kết hợp Luật Giáo dục nghề nghiệp "
     "với Bộ luật Lao động về hợp đồng đào tạo nghề, thời gian thử việc và quyền, nghĩa vụ của "
     "người lao động.",
     "124/2025/QH15", "45/2019/QH14"),
    ("Xử lý kỷ luật, đánh giá và bồi dưỡng nhà giáo trong cơ sở giáo dục nghề nghiệp; phải kết hợp "
     "Luật Giáo dục nghề nghiệp với Luật Nhà giáo về tiêu chuẩn, quyền, nghĩa vụ và trách nhiệm "
     "nghề nghiệp của nhà giáo.",
     "124/2025/QH15", "73/2025/QH15"),
    ("Thi hành án hình sự đối với người bị kết án tù có thời hạn, xét giảm thời hạn chấp hành án, "
     "tha tù trước thời hạn có điều kiện; phải kết hợp Luật Thi hành án hình sự với Bộ luật Hình "
     "sự về hình phạt, điều kiện tha tù và trách nhiệm của cơ quan thi hành án.",
     "127/2025/QH15", "100/2015/QH13"),
    ("Tổ chức thi hành bản án, quyết định hình sự đã có hiệu lực pháp luật; cần kết hợp Luật Thi "
     "hành án hình sự với Bộ luật Tố tụng hình sự về bản án, quyết định được thi hành, thẩm quyền "
     "ra quyết định thi hành án và chuyển giao hồ sơ.",
     "127/2025/QH15", "101/2015/QH13"),
    ("Quản lý, giáo dục, cải tạo phạm nhân và thi hành án treo, cải tạo không giam giữ; phải kết "
     "hợp Luật Thi hành án hình sự với Luật Thi hành án hình sự hiện hành về chế độ giam giữ, giáo "
     "dục và thi hành án tại cộng đồng.",
     "127/2025/QH15", "41/2019/QH14"),
    ("Áp dụng biện pháp tạm giữ, tạm giam, cấm đi khỏi nơi cư trú trong giai đoạn điều tra, truy "
     "tố, xét xử; cần kết hợp Luật Thi hành tạm giữ, tạm giam và cấm đi khỏi nơi cư trú với Bộ "
     "luật Tố tụng hình sự về căn cứ, thẩm quyền và thời hạn áp dụng biện pháp ngăn chặn.",
     "128/2025/QH15", "101/2015/QH13"),
    ("Xử lý trường hợp người bị tạm giữ, tạm giam bỏ trốn hoặc vi phạm quy định cấm đi khỏi nơi cư "
     "trú; phải kết hợp Luật Thi hành tạm giữ, tạm giam và cấm đi khỏi nơi cư trú với Bộ luật Hình "
     "sự về tội trốn khỏi nơi giam, trốn thi hành án và trách nhiệm hình sự.",
     "128/2025/QH15", "100/2015/QH13"),
    ("Ưu đãi, hỗ trợ doanh nghiệp đầu tư vào công nghệ cao, đổi mới sáng tạo và thương mại hóa kết "
     "quả nghiên cứu; cần kết hợp Luật Công nghệ cao với Luật Khoa học, Công nghệ và Đổi mới sáng "
     "tạo về tiêu chí công nghệ cao, chính sách ưu đãi và quản lý hoạt động nghiên cứu.",
     "133/2025/QH15", "93/2025/QH15"),
    ("Phát triển sản phẩm công nghệ số, dịch vụ công nghiệp công nghệ số có ứng dụng công nghệ "
     "cao; phải kết hợp Luật Công nghệ cao với Luật Công nghiệp công nghệ số về hạ tầng số, sản "
     "phẩm số và trách nhiệm của tổ chức, doanh nghiệp.",
     "133/2025/QH15", "71/2025/QH15"),
    ("Phát triển, cung cấp và sử dụng hệ thống trí tuệ nhân tạo có xử lý dữ liệu cá nhân; cần kết "
     "hợp Luật Trí tuệ nhân tạo với Luật Bảo vệ dữ liệu cá nhân về nguyên tắc minh bạch, trách "
     "nhiệm giải trình và quyền của chủ thể dữ liệu.",
     "134/2025/QH15", "91/2025/QH15"),
    ("Quản lý dữ liệu dùng để huấn luyện, kiểm thử hệ thống trí tuệ nhân tạo và chia sẻ dữ liệu "
     "giữa cơ quan, tổ chức; phải kết hợp Luật Trí tuệ nhân tạo với Luật Dữ liệu về xây dựng, kết "
     "nối, chia sẻ và bảo vệ dữ liệu.",
     "134/2025/QH15", "60/2024/QH15"),
    ("Xác định quyền tác giả đối với tác phẩm, chương trình máy tính được tạo ra bởi hoặc có sự hỗ "
     "trợ của trí tuệ nhân tạo; cần kết hợp Luật Trí tuệ nhân tạo với Luật Sở hữu trí tuệ về tác "
     "giả, chủ sở hữu quyền tác giả và hành vi xâm phạm.",
     "134/2025/QH15", "50/2005/QH11"),
    ("Lập dự toán, phân bổ, sử dụng ngân sách nhà nước cho hoạt động dự trữ quốc gia, mua sắm hàng "
     "dự trữ và xuất cấp khi có thiên tai, dịch bệnh; phải kết hợp Luật Dự trữ quốc gia với Luật "
     "Ngân sách nhà nước về nguồn kinh phí, thẩm quyền quyết định và quản lý tài chính.",
     "145/2025/QH15", "89/2025/QH15"),
    ("Mua sắm hàng hóa dự trữ quốc gia, lựa chọn nhà thầu cung cấp hàng dự trữ và quản lý hợp "
     "đồng; cần kết hợp Luật Dự trữ quốc gia với Luật Đấu thầu về hình thức lựa chọn nhà thầu, "
     "tiêu chuẩn đánh giá và ký kết hợp đồng.",
     "145/2025/QH15", "22/2023/QH15"),
    ("Xây dựng, kết nối, chia sẻ dữ liệu phục vụ chuyển đổi số quốc gia, chính quyền số và dịch vụ "
     "công trực tuyến; phải kết hợp Luật Chuyển đổi số với Luật Dữ liệu về hạ tầng dữ liệu, danh "
     "mục dữ liệu dùng chung và trách nhiệm của cơ quan nhà nước.",
     "148/2025/QH15", "60/2024/QH15"),
    ("Bảo đảm an toàn thông tin mạng trong quá trình chuyển đổi số, vận hành hệ thống thông tin và "
     "dịch vụ số; cần kết hợp Luật Chuyển đổi số với Luật An toàn thông tin mạng về cấp độ an "
     "toàn, biện pháp bảo vệ và ứng cứu sự cố.",
     "148/2025/QH15", "86/2015/QH13"),
    ("Giải quyết tranh chấp thương mại quốc tế tại Tòa án chuyên biệt trong Trung tâm tài chính "
     "quốc tế, thủ tục tố tụng và công nhận, cho thi hành bản án; phải kết hợp Luật Tòa án chuyên "
     "biệt tại Trung tâm tài chính quốc tế với Bộ luật Tố tụng dân sự về thẩm quyền, thủ tục và "
     "thi hành án dân sự.",
     "150/2025/QH15", "92/2015/QH13"),
    ("Giải quyết tranh chấp giữa nhà đầu tư nước ngoài và doanh nghiệp tại Trung tâm tài chính "
     "quốc tế bằng trọng tài hoặc tòa án chuyên biệt; cần kết hợp Luật Tòa án chuyên biệt tại "
     "Trung tâm tài chính quốc tế với Luật Trọng tài thương mại về thỏa thuận trọng tài, thẩm "
     "quyền và hủy phán quyết trọng tài.",
     "150/2025/QH15", "54/2010/QH12"),
    ("Xác định luật áp dụng và giải quyết tranh chấp hợp đồng có yếu tố nước ngoài tại Tòa án "
     "chuyên biệt trong Trung tâm tài chính quốc tế; phải kết hợp Luật Tòa án chuyên biệt tại "
     "Trung tâm tài chính quốc tế với Bộ luật Dân sự về hợp đồng, nghĩa vụ và bồi thường thiệt "
     "hại.",
     "150/2025/QH15", "91/2015/QH13"),
    ("Cấp, quản lý thẻ căn cước và cập nhật thông tin về nơi cư trú, hộ khẩu của công dân trong Cơ "
     "sở dữ liệu quốc gia về dân cư; cần kết hợp Luật Căn cước với Luật Cư trú về đăng ký thường "
     "trú, tạm trú và xác nhận thông tin cư trú.",
     "26/2023/QH15", "68/2020/QH14"),
    ("Thu thập, cập nhật, chia sẻ dữ liệu sinh trắc học, số định danh cá nhân và thông tin trong "
     "thẻ căn cước; phải kết hợp Luật Căn cước với Luật Bảo vệ dữ liệu cá nhân về mục đích xử lý, "
     "bảo mật và quyền của chủ thể dữ liệu.",
     "26/2023/QH15", "91/2025/QH15"),
    ("Sử dụng thẻ căn cước, giấy tờ xuất nhập cảnh trong kiểm soát xuất cảnh, nhập cảnh của công "
     "dân Việt Nam; cần kết hợp Luật Căn cước với Luật Xuất cảnh, nhập cảnh của công dân Việt Nam "
     "về giấy tờ hợp lệ, điều kiện xuất cảnh và trường hợp bị tạm hoãn xuất cảnh.",
     "26/2023/QH15", "49/2019/QH14"),
    ("Một cơ sở sản xuất nước uống đóng chai bị phát hiện vi khuẩn E. coli vượt ngưỡng cho phép "
     "trong sản phẩm. Cơ quan chức năng phải áp dụng Luật Phòng, chống bệnh truyền nhiễm để xử lý "
     "ổ dịch và Luật An toàn thực phẩm để xử phạt hành vi vi phạm an toàn thực phẩm, thu hồi sản "
     "phẩm.",
     "03/2007/QH12", "55/2010/QH12"),
    ("Doanh nghiệp nhập khẩu lô hàng hóa phải nộp thuế giá trị gia tăng ở khâu nhập khẩu và đồng "
     "thời thực hiện thủ tục cấp phép nhập khẩu theo quy định về quản lý ngoại thương. Cần kết hợp "
     "Luật Quản lý ngoại thương và Luật Thuế giá trị gia tăng để xác định nghĩa vụ thuế và điều "
     "kiện nhập khẩu.",
     "05/2017/QH14", "48/2024/QH15"),
    ("Trường đại học sa thải giảng viên không đúng quy trình. Giảng viên khiếu nại đòi bồi thường "
     "và phục hồi danh dự. Cần áp dụng Luật Giáo dục đại học về quyền và nghĩa vụ của giảng viên, "
     "đồng thời dùng Luật Nhà giáo để xác định tiêu chuẩn, chế độ đối với nhà giáo.",
     "08/2012/QH13", "73/2025/QH15"),
    ("Hội đồng nhân dân xã tổ chức lấy ý kiến nhân dân về dự toán ngân sách địa phương. Quy trình "
     "thực hiện dân chủ ở cơ sở và việc phân bổ, giám sát ngân sách nhà nước phải tuân theo Luật "
     "Thực hiện dân chủ ở cơ sở và Luật Ngân sách nhà nước.",
     "10/2022/QH15", "89/2025/QH15"),
    ("Một trẻ em bị bỏ rơi được đưa vào cơ sở bảo trợ xã hội, cần xác định người giám hộ và làm "
     "thủ tục nuôi con nuôi. Phải kết hợp Luật Trẻ em về bảo vệ, chăm sóc trẻ em và Luật Nuôi con "
     "nuôi về điều kiện, thủ tục nhận nuôi.",
     "102/2016/QH13", "52/2010/QH12"),
    ("Công dân yêu cầu cung cấp thông tin về dự án đầu tư công nghệ thông tin nhưng bị từ chối với "
     "lý do bí mật an toàn thông tin mạng. Cần áp dụng Luật Tiếp cận thông tin và Luật An toàn "
     "thông tin mạng để xác định phạm vi thông tin được tiếp cận.",
     "104/2016/QH13", "86/2015/QH13"),
    ("Người tiêu dùng mua thuốc tại nhà thuốc phát hiện thuốc giả, gây tổn hại sức khỏe. Cần kết "
     "hợp Luật Dược về quản lý chất lượng thuốc và Luật Bảo vệ quyền lợi người tiêu dùng về bồi "
     "thường thiệt hại.",
     "105/2016/QH13", "19/2023/QH15"),
    ("Người được trợ giúp pháp lý vi phạm hành chính trong lĩnh vực đất đai, được trợ giúp pháp lý "
     "để khiếu nại. Cần áp dụng Luật Trợ giúp pháp lý và Luật Xử lý vi phạm hành chính để giải "
     "quyết.",
     "11/2017/QH14", "15/2012/QH13"),
    ("Cơ quan nhà nước sử dụng tài sản công lãng phí, gây thất thoát ngân sách. Cần kết hợp Luật "
     "Tiết kiệm, chống lãng phí và Luật Quản lý, sử dụng tài sản công để xử lý trách nhiệm.",
     "110/2025/QH15", "15/2017/QH14"),
    ("Dự án quy hoạch đô thị mới được lập nhưng chồng lấn với quy hoạch sử dụng đất. Cần áp dụng "
     "Luật Quy hoạch và Luật Quy hoạch đô thị và nông thôn để điều chỉnh.",
     "112/2025/QH15", "47/2024/QH15"),
    ("Quốc hội giám sát việc thực hiện pháp luật về thanh tra tại các bộ, ngành. Cần áp dụng Luật "
     "Hoạt động giám sát của Quốc hội và Hội đồng nhân dân và Luật Thanh tra.",
     "121/2025/QH15", "84/2025/QH15"),
    ("Sàn thương mại điện tử phải hạch toán doanh thu và xuất hóa đơn cho người bán. Cần kết hợp "
     "Luật Thương mại điện tử và Luật Kế toán để đảm bảo tuân thủ.",
     "122/2025/QH15", "88/2015/QH13"),
    ("Cơ sở giáo dục nghề nghiệp muốn mở ngành đào tạo mới nhưng chưa đáp ứng điều kiện về giáo "
     "viên. Cần áp dụng Luật Giáo dục nghề nghiệp và Luật Việc làm để đảm bảo chất lượng.",
     "124/2025/QH15", "74/2014/QH13"),
    ("Cơ quan điều tra thi hành án hình sự gặp vướng mắc về thẩm quyền điều tra tội phạm. Cần kết "
     "hợp Luật Thi hành án hình sự và Luật Tổ chức cơ quan điều tra hình sự.",
     "127/2025/QH15", "99/2015/QH13"),
    ("Người bị tạm giữ, tạm giam khiếu nại về việc áp dụng biện pháp cấm đi khỏi nơi cư trú. Cần "
     "áp dụng Luật Thi hành tạm giữ, tạm giam và Luật Thi hành tạm giữ, tạm giam (mới) để giải "
     "quyết.",
     "128/2025/QH15", "94/2015/QH13"),
    ("Vợ bị chồng bạo lực gia đình, yêu cầu ly hôn và chia tài sản. Cần kết hợp Luật Phòng, chống "
     "bạo lực gia đình và Luật Hôn nhân và gia đình.",
     "13/2022/QH15", "52/2014/QH13"),
    ("Doanh nghiệp công nghệ cao được hưởng ưu đãi nhưng không đáp ứng điều kiện về nghiên cứu "
     "khoa học. Cần áp dụng Luật Công nghệ cao và Luật Khoa học và công nghệ để xử lý.",
     "133/2025/QH15", "29/2013/QH13"),
    ("Hệ thống trí tuệ nhân tạo xử lý dữ liệu cá nhân không được sự đồng ý. Cần kết hợp Luật Trí "
     "tuệ nhân tạo và Luật Công nghệ thông tin để bảo vệ quyền riêng tư.",
     "134/2025/QH15", "67/2006/QH11"),
    ("Dự trữ quốc gia được sử dụng để trả nợ công, nhưng vượt quá hạn mức. Cần áp dụng Luật Dự trữ "
     "quốc gia và Luật Quản lý nợ công.",
     "145/2025/QH15", "20/2017/QH14"),
    ("Chuyển đổi số trong cơ quan nhà nước nhưng phải đảm bảo an ninh mạng. Cần kết hợp Luật "
     "Chuyển đổi số và Luật An ninh mạng.",
     "148/2025/QH15", "24/2018/QH14"),
    ("Bệnh viện thực hiện ca ghép thận từ người hiến tặng, cần tuân thủ quy định về khám bệnh, "
     "chữa bệnh và hiến, lấy, ghép mô, bộ phận cơ thể người. Cần áp dụng Luật Khám bệnh, chữa bệnh "
     "và Luật Hiến, lấy, ghép mô, bộ phận cơ thể người và hiến, lấy xác.",
     "15/2023/QH15", "75/2006/QH11"),
    ("Chuyển đổi đất lâm nghiệp sang trồng cây công nghiệp. Cần kết hợp Luật Lâm nghiệp và Luật "
     "Trồng trọt để quản lý.",
     "16/2017/QH14", "31/2018/QH14"),
    ("Doanh nghiệp bán hàng đa cấp niêm yết giá không đúng, gây thiệt hại cho người tiêu dùng. Cần "
     "áp dụng Luật Giá và Luật Bảo vệ quyền lợi người tiêu dùng.",
     "16/2023/QH15", "19/2023/QH15"),
    ("Hợp tác xã nhỏ và vừa muốn tiếp cận vốn vay ưu đãi. Cần kết hợp Luật Hợp tác xã và Luật hỗ "
     "trợ doanh nghiệp nhỏ và vừa.",
     "17/2023/QH15", "04/2017/QH14"),
    ("Tàu cá nước ngoài xâm phạm vùng biển Việt Nam. Cần áp dụng Luật Biển Việt Nam và Bộ luật "
     "Hàng hải để xử lý.",
     "18/2012/QH13", "95/2015/QH13"),
    ("Nuôi trồng thủy sản gây ô nhiễm môi trường nước. Cần kết hợp Luật Thủy sản và Luật Bảo vệ "
     "môi trường.",
     "18/2017/QH14", "72/2020/QH14"),
    ("Phòng thủ dân sự ứng phó với thiên tai lớn. Cần áp dụng Luật Phòng thủ dân sự và Luật Phòng, "
     "chống thiên tai.",
     "18/2023/QH15", "33/2013/QH13"),
    ("Giao dịch điện tử trong lĩnh vực tài chính bị mất dữ liệu. Cần kết hợp Luật Giao dịch điện "
     "tử và Luật Dữ liệu.",
     "20/2023/QH15", "60/2024/QH15"),
    ("Chuyển giao công nghệ cao từ nước ngoài vào Việt Nam. Cần áp dụng Luật Công nghệ cao và Luật "
     "chuyển giao công nghệ.",
     "21/2008/QH12", "07/2017/QH14"),
    ("Kiểm toán độc lập dự trữ quốc gia. Cần kết hợp Luật Dự trữ quốc gia và Luật Kiểm toán độc "
     "lập.",
     "22/2012/QH13", "67/2011/QH12"),
    ("Phương tiện thủy nội địa gây tai nạn trên đường bộ. Cần áp dụng Luật Giao thông đường thủy "
     "nội địa và Luật Đường bộ.",
     "23/2004/QH11", "35/2024/QH15"),
    ("Người nước ngoài xin nhập quốc tịch Việt Nam. Cần kết hợp Luật Quốc tịch Việt Nam và Luật Hộ "
     "tịch.",
     "24/2008/QH12", "60/2014/QH13"),
    ("Doanh nghiệp viễn thông sử dụng tần số vô tuyến điện không đúng quy hoạch. Cần áp dụng Luật "
     "Viễn thông và Luật Tần số vô tuyến điện.",
     "24/2023/QH15", "42/2009/QH12"),
    ("Người cao tuổi khám chữa bệnh bằng bảo hiểm y tế. Cần kết hợp Luật Bảo hiểm y tế và Luật "
     "Người cao tuổi.",
     "25/2008/QH12", "39/2009/QH12"),
    ("Cơ sở kinh doanh vi phạm phòng cháy chữa cháy gây hỏa hoạn. Cần áp dụng Luật Phòng cháy và "
     "chữa cháy và Luật Phòng cháy, chữa cháy và cứu nạn, cứu hộ.",
     "27/2001/QH10", "55/2024/QH15"),
    ("Đo đạc bản đồ địa chính phục vụ cấp giấy chứng nhận quyền sử dụng đất. Cần kết hợp Luật Đo "
     "đạc và bản đồ và Luật Đất đai.",
     "27/2018/QH14", "31/2024/QH15"),
    ("Công an nhân dân yêu cầu cấp phiếu lý lịch tư pháp cho cán bộ. Cần áp dụng Luật Lý lịch tư "
     "pháp và Luật Công an nhân dân.",
     "28/2009/QH12", "37/2018/QH14"),
    ("Hành vi khủng bố đe dọa an ninh quốc gia. Cần kết hợp Luật Phòng, chống khủng bố và Luật An "
     "ninh Quốc gia.",
     "28/2013/QH13", "32/2004/QH11"),
    ("Mua bán bất động sản phải công chứng hợp đồng. Cần áp dụng Luật Kinh doanh bất động sản và "
     "Luật Công chứng.",
     "29/2023/QH15", "46/2024/QH15"),
    ("Sinh viên được tạm hoãn nghĩa vụ quân sự do đang học giáo dục quốc phòng. Cần kết hợp Luật "
     "Giáo dục quốc phòng và an ninh và Luật Nghĩa vụ quân sự.",
     "30/2013/QH13", "78/2015/QH13"),
    ("Chủ tịch nước quyết định đặc xá cho phạm nhân. Cần áp dụng Luật Đặc xá và Luật Thi hành án "
     "hình sự.",
     "30/2018/QH14", "41/2019/QH14"),
]


_Q_LUAT_THEO_SOHIEU = """
MATCH (n:Norm {so_hieu:$sh}) WHERE n.loai_vb IN ['Luat', 'BoLuat']
RETURN n.norm_id AS norm_id, n.so_hieu AS so_hieu, n.tinh_trang AS tinh_trang
"""


def _luat_theo_so_hieu(neo: Neo4jClient, so_hieu: str) -> dict | None:
    """Tra truc tiep 1 Luat/Bo luat theo so_hieu CHINH XAC (khong fuzzy nhu tim_luat)
    -- dung cho KICH_BAN_LIEN_NGANH_CO_DINH vi cac so hieu trong do da lay THANG tu
    catalog that luc sinh, khong can doan. Loc loai_vb Luat/BoLuat de tranh trung
    so_hieu voi Nghi quyet QH (2 day so doc lap, xem dieu tra 2026-09-15). Uu tien
    ban con hieu luc/hieu luc mot phan neu co nhieu ket qua trung so_hieu cung loai."""
    rows = neo.run(_Q_LUAT_THEO_SOHIEU, sh=so_hieu)
    if not rows:
        return None
    uu_tien = [r for r in rows if r["tinh_trang"] in ("ConHieuLuc", "HetHieuLucMotPhan")]
    r = (uu_tien or rows)[0]
    return {"norm_id": r["norm_id"], "so_hieu": r["so_hieu"]}


def lay_kich_ban_lien_nganh_co_dinh(neo: Neo4jClient) -> list[KichBanLienNganh]:
    """Buoc 0b - tra bo kich ban CO DINH (`KICH_BAN_LIEN_NGANH_CO_DINH`) vao Neo4j
    qua so_hieu truc tiep, KHONG goi LLM luc chay (thay `de_xuat_kich_ban_lien_nganh`
    cu, bo 2026-09-15). Kich ban khong con luat nao hieu luc (corpus doi) bi loai em."""
    ket_qua: list[KichBanLienNganh] = []
    for boi_canh, sh_a, sh_b in KICH_BAN_LIEN_NGANH_CO_DINH:
        la = _luat_theo_so_hieu(neo, sh_a)
        lb = _luat_theo_so_hieu(neo, sh_b)
        if not la or not lb or la["norm_id"] == lb["norm_id"]:
            continue
        ket_qua.append(KichBanLienNganh(
            boi_canh=boi_canh, norm_a=la["norm_id"], so_hieu_a=la["so_hieu"],
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
