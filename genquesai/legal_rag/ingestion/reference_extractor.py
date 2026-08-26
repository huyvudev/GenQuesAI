"""Reference Extractor — bóc quan hệ Căn cứ/Sửa đổi/Thay thế từ TEXT (regex nền + LLM
tuỳ chọn). Quy tắc đầy đủ + lý do: xem `../rule.md`. Tóm tắt:

- REPLACES/AMENDS: đọc TIÊU ĐỀ + đoạn "Hiệu lực thi hành"/"Điều khoản thi hành" CUỐI
  văn bản (§3.1 — câu tuyên bố thay thế/sửa đổi rất hay nằm ở đây, không phải tiêu
  đề, vd "Thông tư này có hiệu lực... và thay thế Thông tư số X..."). Cả hai đều neo
  theo ĐỘNG TỪ (không neo theo "có số hiệu ở đâu đó" trong toàn văn — bẫy đã biết:
  nhầm câu "Căn cứ Nghị định X..." thành AMENDS).
- GUIDED_BY: đọc đoạn "Căn cứ..." (preamble, trước "Điều 1").
- REPLACES/AMENDS -> da_duyet=false (qua người duyệt, ảnh hưởng domino hiệu lực).
  GUIDED_BY -> da_duyet=true (rủi ro thấp, không đổi hiệu lực ai).
- LLM (tuỳ chọn, tham số `llm`): chỉ chạy cho VB có từ khoá sửa/thay/bãi bỏ ở tiêu đề;
  vá lỗi OCR số hiệu + phân loại đúng hơn regex khi câu phức tạp. Hợp nhất: GIỮ
  GUIDED_BY từ regex, THAY AMENDS/REPLACES bằng kết quả LLM.

Phần thuần (`extract_*`) tách khỏi phần chạm DB (`apply_references`,
`extract_corpus_references`) để test không cần Neo4j.
"""
from __future__ import annotations
import json
import re
import time
from pathlib import Path

from selectolax.parser import HTMLParser

from ..graph.client import Neo4jClient

# Số hiệu VBQPPL tổng quát — bắt MỌI loại (kể cả QĐ-UBND/NQ-HĐND cấp tỉnh), chịu
# khoảng trắng lệch do OCR quanh dấu '/'.
SOHIEU_RE = re.compile(r"\d+\s*/\s*\d{4}\s*/\s*[A-ZĐ0-9]+(?:-[A-ZĐ0-9]+)*", re.IGNORECASE)

# Neo theo ĐỘNG TỪ (rule.md §3) — SUA xét trước BAIBO/"thay thế" khi lẫn cả hai
# (bảo thủ hơn: coi là sửa từng phần thay vì thay thế toàn bộ).
#
# "thay thế" và "bãi bỏ/hủy bỏ" TÁCH RIÊNG khỏi SUA, xét NGỮ CẢNH (rule.md §3.2,
# phát hiện 2026-08-22 — 2 ca thật):
#   - 58/2015/TTLT-BCT-BKHCN: "thay thế Thông tư số X" (không "một số điều") = thay
#     TOÀN BỘ -> REPLACES, khớp referenceType=12 thật.
#   - 06/2016/TT-BKHCN: "bãi bỏ NỘI DUNG quy định liên quan đến... quy định TẠI
#     Quyết định số 32/2007/QĐ-BKHCN" = chỉ bãi bỏ 1 PHẦN NỘI DUNG nằm TRONG VB khác
#     (không phải toàn bộ VB đó) -> AMENDS, khớp referenceType=1 + LLM (không phải
#     REPLACES như quy tắc "bãi bỏ = luôn REPLACES" ngây thơ ban đầu).
# Cả hai đều dùng chung 1 luật: đi kèm cụm chỉ TỪNG PHẦN (_TUNG_PHAN) trong ~60 ký
# tự sau động từ -> AMENDS; không kèm -> REPLACES (nhắm thẳng toàn bộ văn bản đích).
#
# Bug thật 2026-08-23 (phát hiện qua 2 lượt Claude tự đọc tay đối chiếu — VB
# 113460): "thay thế CÁC QUY ĐỊNH VỀ [chủ đề cụ thể] quy định tại Quyết định số
# X..." KHÔNG khớp mẫu cũ (chỉ có "quy định liên quan", không có "các quy định
# về") -> bị phân loại nhầm REPLACES toàn bộ thay vì AMENDS từng phần. Thêm "các
# quy định về" — CÓ "các" (số nhiều, ngụ ý "một số quy định", không phải cả VB) —
# CỐ Ý KHÔNG thêm "quy định về" trần (không "các") vì dễ trùng với câu tả TOÀN BỘ
# nội dung VB đích (vd "thay thế Nghị định quy định về xử phạt vi phạm..." — ở đây
# "quy định về X" đang mô tả CẢ Nghị định đó nói về gì, không phải giới hạn phạm vi
# sửa đổi) — sẽ gây under-classify REPLACES thành AMENDS sai nếu thêm bừa.
SUA = ("sửa đổi", "bổ sung", "điều chỉnh", "dừng thực hiện", "đình chỉ thi hành")
_TUNG_PHAN = re.compile(
    r"một\s+số\s+(điều|khoản|điểm)|nội\s+dung|quy\s+định\s+li[êe]n\s+quan|"
    r"các\s+quy\s+định\s+về", re.IGNORECASE)
_THAY_THE_RE = re.compile(r"thay\s+thế", re.IGNORECASE)
_BAIBO_RE = re.compile(r"bãi\s+bỏ|h[uủ]y\s+bỏ|huỷ\s+bỏ", re.IGNORECASE)

# §3.5 (phát hiện 2026-08-22, ca thật 16/2016/TT-BKHCN): câu/tiêu đề dài có thể liệt
# kê MỘT SỐ HIỆU ĐÍCH THẬT rồi tiếp tục bằng MỆNH ĐỀ MÔ TẢ về chính số hiệu đó (nó
# hướng dẫn thi hành ai, nó từng được sửa bởi ai) — số hiệu xuất hiện TRONG mệnh đề mô
# tả không phải đích của VB hiện tại. Giới hạn CHỦ ĐÍCH ở 4 mẫu phổ biến nhất đã thấy
# trên dữ liệu thật (không cố vét cạn — bài toán ngữ nghĩa câu, xem rule.md §3.5 về
# rủi ro/giới hạn của cách tiếp cận này).
_MO_TA_RE = re.compile(
    r"hướng\s+dẫn\s+thi\s+hành|quy\s+định\s+chi\s+tiết|quy\s+định\s+về|"
    r"(?:được\s+)?sửa\s+đổi[,]?\s*bổ\s+sung", re.IGNORECASE)
_QUOTE_CHARS = '"“”'

# Bug thật 2026-08-23 (user phát hiện): đoạn "Hiệu lực thi hành" trước đây đọc TỪ VỊ
# TRÍ TÌM THẤY ĐẾN HẾT TOÀN VĂN (không giới hạn) — nếu Điều đó KHÔNG phải Điều cuối
# (thường gặp: theo sau còn "Điều X+1. Trách nhiệm thi hành"/"Tổ chức thực hiện" liệt
# kê NHIỆM VỤ giao bộ ngành, có thể nhắc "...trình Nghị định thay thế Nghị định
# Y..." — đây là VIỆC GIAO CHO TƯƠNG LAI, không phải chính VB này thay thế Y; hoặc
# theo sau là PHỤ LỤC dài hàng chục nghìn ký tự) thì nội dung không liên quan đó bị
# quét nhầm tìm REPLACES/AMENDS. Đo thật trên 5000 VB mẫu: 410 VB (8,2%) có đoạn dài
# bất thường (>2500 ký tự, có "nhiệm vụ"/"tổ chức thực hiện") — có ca thật dài tới
# 66.965-69.192 ký tự. Chặn: dừng đoạn ở Điều TIẾP THEO hoặc Phụ lục, tuỳ cái nào đến
# trước; không có cả hai thì fallback cắt ở 2000 ký tự (khớp ngân sách LLM dùng ở
# `consensus._preamble_va_dieu_khoan_cuoi`, rule.md §3.1/§5.1).
_DIEU_TIEP_RE = re.compile(r"Điều\s+\d+\s*\.", re.IGNORECASE)
_PHU_LUC_RE = re.compile(r"phụ\s*lục", re.IGNORECASE)


def _cat_doan_hieu_luc(text_n: str, i: int) -> str:
    """Đoạn 'Hiệu lực thi hành' bắt đầu tại `i` trong `text_n`, dừng ở Điều tiếp theo
    hoặc Phụ lục (cái nào đến trước), fallback cắt 2000 ký tự nếu không có cả hai."""
    duoi = text_n[i:]
    biens = [m.start() for m in _DIEU_TIEP_RE.finditer(duoi) if m.start() > 0]
    biens += [m.start() for m in _PHU_LUC_RE.finditer(duoi) if m.start() > 0]
    j = min(biens) if biens else len(duoi)
    return duoi[: min(j, 2000)]


def html_to_text(html: str) -> str:
    """`toanvan.html` -> text thuần, dùng cho mọi hàm dò quan hệ dựa trên regex.

    KHÔNG dùng `re.sub(r"<[^>]+>", " ", html)` (bug thật 2026-08-22): một số VB có
    thẻ inline (`<em>`, `<b>`...) chèn GIỮA TỪNG KÝ TỰ của số hiệu (HTML gốc tô đậm/
    nghiêng riêng từng ký tự, vd `"...QH</em><em>1</em><em>3..."`) — thay tag bằng
    khoảng trắng làm `"QH13"` vỡ thành `"QH 1 3"`, `SOHIEU_RE` chỉ bắt được `"QH"`,
    mất `"13"`. `HTMLParser.text()` (KHÔNG truyền `separator`) nối các text-node liền
    theo đúng DOM, giữ nguyên whitespace/newline THẬT đã có sẵn trong HTML nguồn —
    đã kiểm tra trên dữ liệu thật: không gây dính chữ giữa các `<p>` (HTML gốc format
    có xuống dòng thật giữa đoạn, không phải HTML minify)."""
    return HTMLParser(html).text()


def _norm_sh(s: str) -> str:
    return re.sub(r"\s*/\s*", "/", s or "").strip()


def _sohieu_in(s: str) -> list[str]:
    return list(dict.fromkeys(_norm_sh(x) for x in SOHIEU_RE.findall(_norm_sh(s))))


_SUA_RE = re.compile("|".join(re.escape(k) for k in SUA))


def _phan_loai_dong_tu(low: str) -> tuple[str, str] | None:
    """Phân loại REPLACES/AMENDS theo động từ (rule.md §3, §3.2, §3.4). `low` = text
    đã lowercase. Trả (loai, edge) hoặc None nếu không có động từ nào khớp.

    ĐỘNG TỪ XUẤT HIỆN SỚM NHẤT trong câu quyết định loại quan hệ cho CẢ CÂU (rule.md
    §3.4, phát hiện 2026-08-22) — KHÔNG phải "SUA có mặt bất kỳ đâu luôn thắng" (thiết
    kế cũ, sai). Câu liệt kê nhiều VB bị bãi bỏ/thay thế thường có 1 VB được MÔ TẢ
    bằng mệnh đề phụ chứa "sửa đổi, bổ sung [VB khác]" ở GIỮA/CUỐI câu (mô tả quan hệ
    LỊCH SỬ giữa 2 VB đó, không phải hành động của VB hiện tại) — động từ mô tả đó
    KHÔNG được áp cho cả câu, chỉ động từ CHÍNH (luôn ở đầu câu theo mẫu hành văn luật
    VN) mới quyết định.

    "thay thế"/"bãi bỏ" (không phải SUA) còn xét thêm ngữ cảnh riêng tại đúng vị trí
    xuất hiện: kèm cụm TỪNG PHẦN (_TUNG_PHAN) trong ~60 ký tự sau -> AMENDS; không
    kèm -> REPLACES.

    **Tách riêng "bãi bỏ" khỏi "thay thế"/"sửa đổi" (2026-08-25, yêu cầu người dùng):**
    "bãi bỏ" (xoá bỏ, KHÔNG có nội dung mới thay cho nội dung cũ) khác bản chất với
    "thay thế"/"sửa đổi" (CÓ nội dung mới) — trước đây gộp chung vào ThayThe/SuaDoi
    theo phạm vi, làm mất thông tin "đây là xoá hẳn hay chỉ đổi nội dung". Giờ trả
    `loai` riêng `BaiBoToanBo`/`BaiBoTungPhan` (edge vẫn theo phạm vi như cũ —
    REPLACES nếu toàn bộ, AMENDS nếu từng phần — chỉ khác ở field `loai` để phân biệt
    hành vi)."""
    ung_vien: list[tuple[int, str, str]] = []
    m = _SUA_RE.search(low)
    if m:
        ung_vien.append((m.start(), "SuaDoi", "AMENDS"))
    for m in _BAIBO_RE.finditer(low):
        if _TUNG_PHAN.search(low[m.end():m.end() + 60]):
            ung_vien.append((m.start(), "BaiBoTungPhan", "AMENDS"))
        else:
            ung_vien.append((m.start(), "BaiBoToanBo", "REPLACES"))
    for m in _THAY_THE_RE.finditer(low):
        if _TUNG_PHAN.search(low[m.end():m.end() + 60]):
            ung_vien.append((m.start(), "SuaDoi", "AMENDS"))
        else:
            ung_vien.append((m.start(), "ThayThe", "REPLACES"))
    if not ung_vien:
        return None
    ung_vien.sort(key=lambda x: x[0])
    _, loai, edge = ung_vien[0]
    return loai, edge


def _dich_trong_cau(cau: str, own_so_hieu: str | None = None) -> list[str]:
    """Số hiệu là ĐÍCH THẬT trong câu — không phải mọi số hiệu xuất hiện (rule.md
    §3.5). Số hiệu ĐẦU TIÊN (sau khi loại `own_so_hieu` — tiêu đề luôn bắt đầu bằng
    CHÍNH số hiệu của văn bản, vd "Thông tư số 16/2016/TT-BKHCN Sửa đổi...", đó
    KHÔNG phải đích) luôn là đích. Số hiệu tiếp theo bị LOẠI nếu nằm trong đoạn NGAY
    SAU 1 mẫu MÔ TẢ (_MO_TA_RE — "hướng dẫn thi hành X", "quy định chi tiết Y",
    "được sửa đổi theo Z"...) và KHÔNG nằm trong dấu ngoặc kép đã ĐÓNG lại (dấu ngoặc
    kép đóng = ranh giới thoát mệnh đề mô tả, quay lại liệt kê đích — ca thật
    10/2007/QĐ-BKHCN: "...về việc "sửa đổi... 16/2003..."", Quyết định số 06/2006..."
    — 06/2006 SAU dấu ngoặc đóng vẫn là đích thật).

    Bảo thủ có chủ đích: chỉ nhận 4 mẫu mô tả phổ biến nhất đã thấy trên dữ liệu
    thật (không cố vét cạn mọi cách diễn đạt) — xem rule.md §3.5 về rủi ro."""
    cau_n = _norm_sh(cau)
    own = _norm_sh(own_so_hieu) if own_so_hieu else None
    matches = [m for m in SOHIEU_RE.finditer(cau_n) if not own or m.group(0) != own]
    if not matches:
        return []
    out = [matches[0].group(0)]
    trong_mo_ta = False
    trong_ngoac = False
    prev_end = matches[0].end()
    for m in matches[1:]:
        gap = cau_n[prev_end:m.start()]
        # Tách gap theo dấu ngoặc kép — CHỈ kiểm tra _MO_TA_RE trên từng ĐOẠN NGOÀI
        # ngoặc riêng lẻ, KHÔNG search trên cả gap gộp lại. Bắt buộc: nếu 1 cặp ngoặc
        # mở+đóng nằm TRỌN trong CÙNG 1 gap (ca thật 10/2007/QĐ-BKHCN, đoạn đầu —
        # "...về việc "Quy định về việc tuyển chọn..."" mở+đóng ngay trong 1 gap),
        # search trên cả gap sẽ vẫn "thấy" cụm mô tả nằm BÊN TRONG ngoặc đã đóng.
        doan_list = re.split(f"[{re.escape(_QUOTE_CHARS)}]", gap)
        for idx, doan in enumerate(doan_list):
            if not trong_ngoac:
                if _MO_TA_RE.search(doan):
                    trong_mo_ta = True
            if idx < len(doan_list) - 1:      # còn dấu ngoặc phía sau đoạn này -> đảo trạng thái
                trong_ngoac = not trong_ngoac
                if not trong_ngoac:            # vừa đóng ngoặc -> thoát mệnh đề mô tả
                    trong_mo_ta = False
        if not trong_mo_ta:
            out.append(m.group(0))
        prev_end = m.end()
    return list(dict.fromkeys(_norm_sh(x) for x in out))


def _quan_he_theo_cau(doan: str, own_so_hieu: str | None = None,
                      exclude: set[str] | None = None) -> list[tuple[str, str, str]]:
    """Tách `doan` thành từng CÂU (theo dấu . hoặc ;), phân loại + trích số hiệu
    RIÊNG cho từng câu — KHÔNG gộp động từ của câu này với số hiệu của câu khác
    (rule.md §3.1, phát hiện 2026-08-22: câu boilerplate "văn bản viện dẫn được sửa
    đổi... thì theo văn bản mới" không nói về số hiệu cụ thể nào, nếu quét cả đoạn
    thì động từ "sửa đổi" ở câu đó bị gán nhầm cho số hiệu ở câu KHÁC)."""
    own = _norm_sh(own_so_hieu) if own_so_hieu else None
    used = set(exclude or set())
    if own:
        used.add(own)
    out: list[tuple[str, str, str]] = []
    for cau in re.split(r"(?<=[.;])\s+", doan):
        shs = [s for s in _dich_trong_cau(cau, own) if s and s not in used]
        if not shs:
            continue
        kq = _phan_loai_dong_tu(cau.lower())
        if kq is None:
            continue
        loai, edge = kq
        for sh in shs:
            out.append((loai, edge, sh))
            used.add(sh)
    return out


def extract_title_relations(title: str, own_so_hieu: str | None = None) -> list[tuple[str, str, str]]:
    """REPLACES/AMENDS từ TIÊU ĐỀ — neo theo động từ, theo từng câu (rule.md §3)."""
    return _quan_he_theo_cau(title or "", own_so_hieu)


def extract_final_clause_relations(text: str, own_so_hieu: str | None = None,
                                   exclude: set[str] | None = None) -> list[tuple[str, str, str]]:
    """REPLACES/AMENDS từ đoạn 'Hiệu lực thi hành'/'Điều khoản thi hành' — thường ở
    CUỐI văn bản (rule.md §3.1, phát hiện 2026-08-22). Câu tuyên bố thay thế/sửa đổi
    hay nằm ở đây, KHÔNG ở tiêu đề — vd 'Thông tư này có hiệu lực... và thay thế
    Thông tư liên tịch số 44/2013/TTLT-BCT-BKHCN...' (ca thật, đo trên corpus).
    Xử lý theo TỪNG CÂU (không phải cả đoạn) — xem `_quan_he_theo_cau`."""
    text_n = _norm_sh(text)
    low = text_n.lower()
    i = low.rfind("hiệu lực thi hành")
    if i < 0:
        i = low.rfind("điều khoản thi hành")
    if i >= 0:
        clause = _cat_doan_hieu_luc(text_n, i)
    else:
        # Bug thật 2026-08-22 (VB 13234/most): fallback "N ký tự cuối" cho VB KHÔNG
        # có "hiệu lực thi hành"/"điều khoản thi hành" — nếu VB ngắn hơn N ký tự thì
        # "N ký tự cuối" = TOÀN VĂN, tái hiện đúng bẫy gốc (mục 3): đoạn "Căn cứ..."
        # ở đầu bị lẫn vào, số hiệu trong đó bị gán nhầm REPLACES/AMENDS. Chặn: không
        # bao giờ lấy phần TRƯỚC "Điều 1" (ranh giới cuối cùng của preamble).
        #
        # Bug thật 2026-08-23: "N ký tự cuối VĂN BẢN" cũng dính đúng lỗi mục 3.1 nếu
        # VB kết thúc bằng Phụ lục dài — N ký tự cuối rơi hẳn vào Phụ lục, không phải
        # điều khoản thật. Cắt bỏ Phụ lục trước khi lấy N ký tự cuối, nếu có.
        j = text_n.find("Điều 1")
        sau_dieu_1 = text_n[j:] if j > 0 else text_n
        m = _PHU_LUC_RE.search(sau_dieu_1)
        gioi_han = sau_dieu_1[: m.start()] if m else sau_dieu_1
        clause = gioi_han[-3000:]
    return _quan_he_theo_cau(clause, own_so_hieu, exclude)


def extract_guided_by(text: str, own_so_hieu: str | None = None,
                      exclude: set[str] | None = None) -> list[tuple[str, str, str]]:
    """GUIDED_BY từ đoạn 'Căn cứ...' (preamble, trước 'Điều 1') — rule.md §4."""
    own = _norm_sh(own_so_hieu) if own_so_hieu else None
    text_n = _norm_sh(text)
    i = text_n.find("Điều 1")
    preamble = text_n[:i] if i > 0 else text_n[:3500]
    used = set(exclude or set())
    if own:
        used.add(own)
    out: list[tuple[str, str, str]] = []
    for sh in _sohieu_in(preamble):
        if sh not in used:
            out.append(("CanCu", "GUIDED_BY", sh))
            used.add(sh)
    return out


def extract_references(title: str, text: str, own_so_hieu: str | None = None) -> list[tuple[str, str, str]]:
    """Pure: hợp REPLACES/AMENDS (tiêu đề + đoạn 'Hiệu lực thi hành' cuối văn bản) +
    GUIDED_BY (preamble). Không DB, test thẳng được."""
    rel = extract_title_relations(title, own_so_hieu)
    rel += extract_final_clause_relations(text, own_so_hieu, exclude={s for _, _, s in rel})
    guided = extract_guided_by(text, own_so_hieu, exclude={s for _, _, s in rel})
    return rel + guided


_EDGE_MAP = {"ThayThe": "REPLACES", "SuaDoi": "AMENDS", "CanCu": "GUIDED_BY",
            "BaiBoToanBo": "REPLACES", "BaiBoTungPhan": "AMENDS"}
_LLM_SYS = (
    "Bạn bóc TOÀN BỘ quan hệ tham chiếu của một văn bản pháp luật Việt Nam thành JSON: "
    "{\"refs\":[{\"target\":\"số hiệu VB được tham chiếu nếu CÓ (vd 24/2023/QH15), "
    "để trống nếu không có\", \"ten_luat\":\"tên đầy đủ VB nếu KHÔNG thấy số hiệu rõ "
    "(vd 'Luật Tổ chức Chính phủ'), để trống nếu đã có target\", "
    "\"ngay\":\"ngày ban hành dạng DD/MM/YYYY nếu có, chỉ điền khi dùng ten_luat\", "
    "\"loai\":\"ThayThe|SuaDoi|BaiBoToanBo|BaiBoTungPhan|CanCu\", \"confidence\":0.0-1.0}]}. "
    "ThayThe = văn bản này THAY THẾ TOÀN BỘ VB đích bằng NỘI DUNG MỚI; SuaDoi = SỬA ĐỔI/"
    "BỔ SUNG (kể cả 'thay thế MỘT SỐ ĐIỀU/KHOẢN' — vẫn là SuaDoi, không phải ThayThe); "
    "BaiBoToanBo = BÃI BỎ/HUỶ BỎ TOÀN BỘ VB đích (xoá bỏ, KHÔNG có nội dung mới thay "
    "thế — khác ThayThe ở chỗ không có gì thay vào); BaiBoTungPhan = bãi bỏ/huỷ bỏ "
    "MỘT SỐ điều/khoản/nội dung (không phải toàn bộ VB); CanCu = CĂN CỨ "
    "(trích dẫn làm cơ sở pháp lý, thường ở đoạn đầu 'Căn cứ...'). "
    "BẮT BUỘC liệt kê ĐẦY ĐỦ mọi quan hệ tìm thấy — một văn bản thường có NHIỀU CanCu "
    "(mỗi dòng 'Căn cứ...' là 1 CanCu riêng) CỘNG THÊM tối đa 1 ThayThe/SuaDoi nếu có. "
    "KHÔNG chỉ chọn 1 quan hệ 'quan trọng nhất' rồi bỏ qua các CanCu khác. "
    "SỬA số hiệu bị lỗi OCR (vd 'QH1 3' → 'QH13', '24/2023/QH1' → '24/2023/QH13') — "
    "nhưng nếu văn bản KHÔNG ghi số hiệu ở đâu cả thì để target trống và dùng ten_luat, "
    "TUYỆT ĐỐI KHÔNG tự bịa/đoán ra một số hiệu không có trong văn bản. "
    "KHÔNG trích 'Hiến pháp' thành ref (dù có hay không có số hiệu)."
)

_TEN_LUAT_PREFIX_RE = re.compile(r"^(bộ\s+luật|luật)\s+", re.IGNORECASE)
_NGAY_RE = re.compile(r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})")


def _resolve_ten_luat(neo: Neo4jClient | None, ten_luat: str, ngay: str | None = None) -> str | None:
    """Tra ngược tên luật (không có số hiệu trong văn bản gốc) → so_hieu, qua so khớp
    `tieu_de` trong Neo4j — rule.md §5.4. CHỈ trả về khi khớp DUY NHẤT 1 kết quả (hoặc
    ≥2 kết quả nhưng đúng 1 khớp `ngay`) — mơ hồ thì bỏ, KHÔNG đoán (giữ nguyên triết
    lý "chỉ tự động khi chắc chắn" xuyên suốt rule.md). Loại trừ Hiến pháp hẳn (không
    phải Norm tham gia luồng REPLACES/AMENDS/GUIDED_BY thông thường)."""
    if neo is None or not ten_luat:
        return None
    ten = ten_luat.strip()
    if "hiến pháp" in ten.lower():
        return None
    tu_khoa = _TEN_LUAT_PREFIX_RE.sub("", ten).strip()
    if len(tu_khoa) < 4:
        return None
    rows = neo.run(
        "MATCH (n:Norm) WHERE n.loai_vb IN ['Luat','BoLuat'] "
        "AND toLower(n.tieu_de) CONTAINS toLower($tu_khoa) "
        "RETURN n.so_hieu AS so_hieu, n.ngay_ban_hanh AS ngay_ban_hanh",
        tu_khoa=tu_khoa)
    if len(rows) == 1:
        return rows[0]["so_hieu"]
    if len(rows) > 1 and ngay:
        m = _NGAY_RE.search(ngay)
        if m:
            d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
            khop = [r for r in rows if r["ngay_ban_hanh"] is not None
                   and (r["ngay_ban_hanh"].year, r["ngay_ban_hanh"].month, r["ngay_ban_hanh"].day) == (y, mo, d)]
            if len(khop) == 1:
                return khop[0]["so_hieu"]
    return None


def extract_references_llm(llm, title: str, preamble: str, own_so_hieu: str | None,
                           neo: Neo4jClient | None = None) -> list[tuple[str, str, str]]:
    """LLM bóc quan hệ (vá số hiệu OCR hỏng + phân loại đúng thay/sửa/căn cứ) — rule.md §5.
    `neo` (tuỳ chọn): khi CanCu không có số hiệu, tra ngược tên luật → so_hieu qua
    Neo4j (rule.md §5.4) — không truyền thì các ca này bị bỏ (hành vi cũ)."""
    own = _norm_sh(own_so_hieu) if own_so_hieu else None
    user = f"Văn bản: {own_so_hieu}\nTiêu đề: {title}\n\nPhần đầu (căn cứ):\n{(preamble or '')[:3500]}"
    # max_tokens mặc định (800) hay bị cắt cụt giữa chừng với VB có nhiều CanCu
    # (đặc biệt nhánh C đọc toàn văn) → JSON hỏng. Tăng lên 2000 cho đủ chỗ liệt kê.
    data = llm.chat_json(_LLM_SYS, user, max_tokens=2000)
    out: list[tuple[str, str, str]] = []
    seen: set[tuple[str, str]] = set()
    for r in (data.get("refs", []) if isinstance(data, dict) else []):
        loai = (r.get("loai") or "").strip()
        if loai not in _EDGE_MAP:
            continue
        tgt = _norm_sh(r.get("target") or "")
        if not tgt and loai == "CanCu":
            tgt = _resolve_ten_luat(neo, r.get("ten_luat") or "", r.get("ngay")) or ""
        edge = _EDGE_MAP[loai]
        if tgt and tgt != own and (edge, tgt) not in seen:
            out.append((loai, edge, tgt))
            seen.add((edge, tgt))
    return out


_EDGE_TMPL = """
MATCH (src:Norm {{norm_id:$sid}}), (tgt:Norm {{so_hieu:$tsh}})
WHERE src <> tgt
MERGE (a:Action {{action_id:$aid}})
  SET a.loai=$loai, a.confidence=$conf, a.da_duyet=$duyet, a.enacted_by=$sid,
      a.ngay_hieu_luc=src.ngay_hieu_luc, a.source=$source
MERGE (a)-[:ENACTED_BY]->(src)
MERGE (a)-[:AFFECTS]->(tgt)
MERGE (src)-[:{edge}]->(tgt)
RETURN 1
"""


def apply_references(neo: Neo4jClient, norm_id: str, refs: list[tuple[str, str, str]],
                     source: str = "text_regex") -> dict:
    """Ghi Action + cạnh vào graph. REPLACES/AMENDS -> da_duyet=false; GUIDED_BY -> true
    (rule.md §6). `source` ghi vào Action.source để truy vết cạnh này từ đâu ra.
    `MATCH (tgt:Norm {so_hieu:...})`: nếu đích chưa có trong graph thì không tạo gì
    (Cypher MERGE trên MATCH rỗng không chạy) — idempotent, an toàn chạy lại."""
    n = {"REPLACES": 0, "AMENDS": 0, "GUIDED_BY": 0}
    for loai, edge, target in refs:
        conf = 0.85 if edge in ("REPLACES", "AMENDS") else 0.6
        duyet = edge == "GUIDED_BY"
        rows = neo.run(_EDGE_TMPL.format(edge=edge), sid=norm_id, tsh=target,
                       aid=f"{norm_id}->{target}:{edge}:{source}", loai=loai, conf=conf,
                       duyet=duyet, source=source)
        if rows:
            n[edge] += 1
    return n


def extract_corpus_references(neo: Neo4jClient, base: Path, src_dirs: list[str],
                              llm=None, resume: bool = True, pace_seconds: float = 0.0,
                              log=print) -> dict:
    """Quét raw dirs (doc.json + toanvan.html) -> bóc quan hệ -> ghi graph. rule.md §5/§8.

    `llm` != None: hợp nhất — GIỮ GUIDED_BY regex, BỎ AMENDS/REPLACES regex thay bằng
    kết quả LLM (rule.md §5). `resume`: chỉ xử lý VB chưa có flag refs_done/refs_llm_done
    (mỗi VB chỉ áp dẫn chiếu một lần — tránh chạy LLM lại tốn kém trên VB đã xong)."""
    doc_dirs = sorted({p.parent for sub in src_dirs for p in base.glob(f"{sub}/*/doc.json")})
    total = {"REPLACES": 0, "AMENDS": 0, "GUIDED_BY": 0}
    n_norm = n_proc = 0
    flag = "refs_llm_done" if llm is not None else "refs_done"
    src_tag = "llm" if llm is not None else "text_regex"
    done: set[str] = set()
    if resume:
        done = {r["id"] for r in neo.run(f"MATCH (n:Norm) WHERE n.{flag}=true RETURN n.norm_id AS id")}
    for d in doc_dirs:
        tv = d / "toanvan.html"
        if not tv.exists() or d.name in done:
            continue
        try:
            data = json.loads((d / "doc.json").read_text(encoding="utf-8"))["data"]
        except Exception:
            continue
        title, own = data.get("title") or "", data.get("docNum")
        text = html_to_text(tv.read_text(encoding="utf-8", errors="ignore"))
        refs = extract_references(title, text, own)
        if llm is not None:
            # Bỏ AMENDS/REPLACES từ regex thô (hay bảo thủ/sót khi câu phức tạp) — LLM
            # là nguồn chuẩn cho 2 loại này. Giữ GUIDED_BY regex (recall cao, rủi ro thấp).
            refs = [r for r in refs if r[1] == "GUIDED_BY"]
            i = _norm_sh(text).find("Điều 1")
            preamble = _norm_sh(text)[:i] if i > 0 else _norm_sh(text)[:3500]
            seen = {(e, s) for _, e, s in refs}
            for loai, edge, tgt in extract_references_llm(llm, title, preamble, own, neo=neo):
                if (edge, tgt) not in seen:
                    refs.append((loai, edge, tgt))
                    seen.add((edge, tgt))
        r = apply_references(neo, d.name, refs, source=src_tag)
        neo.run(f"MATCH (n:Norm {{norm_id:$id}}) SET n.{flag}=true", id=d.name)
        if any(r.values()):
            n_norm += 1
        for k in total:
            total[k] += r[k]
        n_proc += 1
        if n_proc % 100 == 0:
            log(f"  [{src_tag}] {n_proc} VB xử lý · quan hệ "
                f"{total['REPLACES']}R/{total['AMENDS']}A/{total['GUIDED_BY']}G")
        if llm is not None and pace_seconds > 0:
            time.sleep(pace_seconds)
    return {"norm": n_norm, **total}
