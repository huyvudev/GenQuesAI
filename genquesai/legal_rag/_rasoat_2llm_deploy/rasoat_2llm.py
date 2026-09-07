#!/usr/bin/env python3
"""Rà soát lại quan hệ ThayThe/SuaDoi/BaiBoToanBo/BaiBoTungPhan bằng 2 LLM ĐỘC LẬP
(DeepSeek + Gemini), KHÔNG dùng regex/metadata — so sánh kết quả để tìm cạnh khả
nghi sai (bất đồng giữa 2 model, hoặc cả 2 cùng khác với nhãn hiện có trong graph).

Bối cảnh (2026-09-07): hôm trước đã tìm + sửa 397 cạnh ThayThe/BaiBoToanBo phân loại
sai qua 1 rule cấu trúc đơn giản (nguồn cấp bậc thấp hơn đích, hoặc nguồn là Văn bản
hợp nhất/Khác) — CHỈ bắt được phần "rõ ràng sai". Còn ~11.722 cạnh "cùng cấp bậc"
chưa rà được (rule cấu trúc không phân biệt đúng/sai). Việc này dùng LLM để rà tiếp,
bao trùm luôn phần chưa rà được đó.

KHÔNG có dữ liệu thô (preamble "Căn cứ...") trên server -> chỉ dùng TIÊU ĐỀ + nội
dung đầu các Điều của văn bản NGUỒN (đã có sẵn trong Neo4j) — đủ để đánh giá lại
ThayThe/SuaDoi/BaiBoToanBo/BaiBoTungPhan (tín hiệu chính nằm ở tiêu đề/nội dung nguồn,
không phải phần "Căn cứ").

Chạy 24/7 (systemd), tự dừng gọi DeepSeek trong khung GIỜ CAO ĐIỂM (T2-T6, 01:00-04:00
và 06:00-10:00 UTC = 08:00-11:00 và 13:00-17:00 giờ VN) — nguồn: DeepSeek đổi giá theo
giờ từ 16/8/2026. Gemini không giới hạn giờ.

Checkpoint resumable: rasoat_2llm_log.jsonl (1 dòng/VB nguồn đã xử lý, ghi TRƯỚC khi
qua VB tiếp — khởi động lại đọc file này để biết đã làm tới đâu, không làm lại).
"""
from __future__ import annotations
import json
import os
import sys
import time
from datetime import datetime, timezone, timedelta

from neo4j import GraphDatabase
from openai import OpenAI

HERE = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(HERE, "rasoat_2llm.env")
LOG_PATH = os.path.join(HERE, "rasoat_2llm_log.jsonl")
PROGRESS_PATH = os.path.join(HERE, "rasoat_2llm_progress.log")

_LOAI_HOP_LE = {"ThayThe", "SuaDoi", "BaiBoToanBo", "BaiBoTungPhan", "KhongLienQuan"}


def _load_env(path: str) -> dict:
    out = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def _log(msg: str) -> None:
    line = f"{datetime.now().isoformat(timespec='seconds')} {msg}"
    print(line, flush=True)
    with open(PROGRESS_PATH, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def deepseek_offpeak_giay_cho(now: datetime | None = None) -> float:
    """Trả số giây cần chờ tới khi hết giờ cao điểm DeepSeek (0 nếu đang off-peak).
    Cao điểm: Thứ 2-6, 01:00-04:00 UTC và 06:00-10:00 UTC (giá gấp đôi từ 16/8/2026)."""
    now = now or datetime.now(timezone.utc)
    if now.weekday() >= 5:  # Thu 7, CN luon off-peak
        return 0.0
    h = now.hour
    if 1 <= h < 4:
        het_gio = now.replace(hour=4, minute=0, second=0, microsecond=0)
        return (het_gio - now).total_seconds()
    if 6 <= h < 10:
        het_gio = now.replace(hour=10, minute=0, second=0, microsecond=0)
        return (het_gio - now).total_seconds()
    return 0.0


_SYS = (
    "Bạn là chuyên gia phân loại quan hệ HIỆU LỰC giữa văn bản pháp luật Việt Nam. Cho 1 văn bản "
    "NGUỒN và danh sách văn bản ĐÍCH mà nguồn được cho là có tác động tới, hãy TỰ ĐỌC nội dung "
    "nguồn và xác định ĐÚNG loại quan hệ với TỪNG đích — KHÔNG dựa vào nhãn có sẵn nào khác, tự "
    "phân loại lại từ đầu.\n\n"
    "5 loại (chọn đúng 1 cho mỗi đích):\n"
    "- ThayThe: nguồn THAY THẾ TOÀN BỘ đích (đích hết hiệu lực hoàn toàn, có nội dung mới thay vào)\n"
    "- BaiBoToanBo: nguồn BÃI BỎ TOÀN BỘ đích (như ThayThe nhưng KHÔNG có nội dung thay thế)\n"
    "- SuaDoi: nguồn chỉ SỬA ĐỔI/BỔ SUNG MỘT SỐ ĐIỀU của đích (đích vẫn còn hiệu lực phần lớn)\n"
    "- BaiBoTungPhan: nguồn chỉ BÃI BỎ 1 PHẦN (vài Điều/Khoản/Điểm) của đích, phần còn lại vẫn hiệu lực\n"
    "- KhongLienQuan: sau khi đọc kỹ, nguồn KHÔNG thực sự có quan hệ thay thế/sửa đổi/bãi bỏ nào với "
    "đích này (chỉ trùng số hiệu ngẫu nhiên, nhắc tên suông, hoặc chỉ là quan hệ CĂN CỨ/dẫn chiếu)\n\n"
    "QUY TẮC BẮT BUỘC: 1 văn bản CẤP THẤP HƠN (vd Nghị định/Thông tư/Quyết định/Công văn) KHÔNG THỂ "
    "ThayThe/BaiBoToanBo 1 văn bản CẤP CAO HƠN (vd Luật/Bộ luật/Pháp lệnh) — nguyên tắc pháp lý cơ "
    "bản. Nếu gặp trường hợp cấp thấp hơn được gán ThayThe/BaiBoToanBo lên cấp cao hơn, gần như chắc "
    "chắn là SAI — hãy đổi thành KhongLienQuan hoặc SuaDoi/BaiBoTungPhan nếu nội dung cho thấy đúng "
    "là có sửa đổi 1 phần. Văn bản hợp nhất (VBHN) KHÔNG BAO GIỜ hợp lệ để ThayThe/BaiBoToanBo bất kỳ "
    "văn bản nào (nó chỉ là bản tổng hợp tham khảo).\n\n"
    'Trả JSON: {"ket_qua": [{"target_so_hieu": "...", "loai": '
    '"ThayThe|BaiBoToanBo|SuaDoi|BaiBoTungPhan|KhongLienQuan", "ly_do": "..."}]}'
)


def _breadcrumb_vb(so_hieu: str, loai_vb: str, cap_bac, tieu_de: str) -> str:
    return f"{so_hieu} ({loai_vb}, cấp {cap_bac}) — {tieu_de or ''}"


def _prompt_user(src: dict, targets: list[dict]) -> str:
    ds_dich = "\n".join(
        f"- {_breadcrumb_vb(t['so_hieu'], t['loai_vb'], t['cap_bac'], t['tieu_de'])}" for t in targets
    )
    return (
        f"NGUỒN: {_breadcrumb_vb(src['so_hieu'], src['loai_vb'], src['cap_bac'], src['tieu_de'])}\n\n"
        f"NỘI DUNG VĂN BẢN NGUỒN (đã chọn lọc đoạn liên quan nhất):\n```\n{src['ctx']}\n```\n\n"
        f"DANH SÁCH ĐÍCH cần phân loại quan hệ:\n{ds_dich}\n"
    )


class LLMClient:
    def __init__(self, provider: str, model: str, api_key: str, base_url: str, extra: dict | None = None):
        self.provider, self.model = provider, model
        self._client = OpenAI(api_key=api_key, base_url=base_url)
        self._extra = extra or {}

    def _create(self, **kw):
        if self._extra:
            kw.setdefault("extra_body", {}).update(self._extra)
        for attempt in range(6):
            try:
                return self._client.chat.completions.create(**kw)
            except Exception as e:
                if attempt >= 5:
                    raise
                time.sleep(min(2 ** attempt * 2, 60))

    def chat_json(self, system: str, user: str, max_tokens: int = 1500) -> dict:
        try:
            r = self._create(model=self.model, temperature=0, max_tokens=max_tokens,
                             response_format={"type": "json_object"},
                             messages=[{"role": "system", "content": system}, {"role": "user", "content": user}])
            content = r.choices[0].message.content
            return json.loads(content) if content else {}
        except Exception as e:
            _log(f"  LOI goi {self.provider}: {e!r}")
            return {}


_Q_NGUON_CAN_RA = """
MATCH (a:Action)-[:ENACTED_BY]->(src:Norm)
WHERE a.loai IN ['ThayThe','SuaDoi','BaiBoToanBo','BaiBoTungPhan']
RETURN DISTINCT src.norm_id AS norm_id
ORDER BY norm_id
"""

_Q_THONG_TIN_NGUON = """
MATCH (n:Norm {norm_id:$nid}) RETURN n.so_hieu AS so_hieu, n.loai_vb AS loai_vb,
       n.cap_bac AS cap_bac, n.tieu_de AS tieu_de
"""

_Q_DICH_CUA_NGUON = """
MATCH (a:Action)-[:ENACTED_BY]->(src:Norm {norm_id:$nid})
WHERE a.loai IN ['ThayThe','SuaDoi','BaiBoToanBo','BaiBoTungPhan']
MATCH (a)-[:AFFECTS]->(tgt)
WITH a, tgt, CASE WHEN 'Norm' IN labels(tgt) THEN tgt ELSE null END AS tn
OPTIONAL MATCH (tgt)<-[:HAS_PART*0..]-(pn:Norm) WHERE 'Component' IN labels(tgt)
WITH a, coalesce(tn, pn) AS tgt_norm
WHERE tgt_norm IS NOT NULL
RETURN DISTINCT a.action_id AS action_id, a.loai AS loai_hien_tai,
       tgt_norm.norm_id AS tgt_norm_id, tgt_norm.so_hieu AS so_hieu,
       tgt_norm.loai_vb AS loai_vb, tgt_norm.cap_bac AS cap_bac, tgt_norm.tieu_de AS tieu_de
"""

_Q_TOAN_BO_DIEU = """
MATCH (n:Norm {norm_id:$nid})-[:HAS_PART*]->(d:Component)-[:HAS_VERSION]->(e:Expression)
WHERE d.loai IN ['Dieu','ToanVan']
RETURN d.duong_dan AS dd, e.text AS text, d.order_key AS ok
ORDER BY ok
"""


def _chuan_hoa_so_hieu(s: str) -> str:
    import re
    return re.sub(r"\s*/\s*", "/", s or "").strip().lower()


def _chon_ngu_canh(dieu_rows: list[dict], target_so_hieu: list[str], gioi_han_ky_tu: int = 6000) -> str:
    """Ưu tiên các Điều CÓ NHẮC tới số hiệu đích (thường là 'Điều khoản thi hành' sửa đổi
    luật khác, hay nằm ở CUỐI văn bản với luật lớn — lấy 8 Điều đầu là sai với luật lớn,
    đo thực tế 2026-09-07: Luật Đất đai 2024 bị chê oan 7/7 cạnh vì không thấy đúng đoạn).
    Luôn kèm thêm 2 Điều đầu (bối cảnh chung) + 2 Điều cuối (thường có hiệu lực thi hành)."""
    targets_norm = [_chuan_hoa_so_hieu(t) for t in target_so_hieu]
    uu_tien, con_lai = [], []
    for r in dieu_rows:
        text_norm = _chuan_hoa_so_hieu(r["text"] or "")
        if any(t and t in text_norm for t in targets_norm):
            uu_tien.append(r)
        else:
            con_lai.append(r)
    chon = uu_tien + con_lai[:2] + con_lai[-2:]
    seen, doan, tong = set(), [], 0
    for r in chon:
        if r["dd"] in seen:
            continue
        seen.add(r["dd"])
        t = r["text"] or ""
        doan.append(f"{r['dd']}: {t}")
        tong += len(t)
        if tong >= gioi_han_ky_tu:
            break
    return "\n\n".join(doan)


def lay_du_lieu_nguon(neo, norm_id: str) -> tuple[dict, list[dict]] | None:
    rows = neo.run(_Q_THONG_TIN_NGUON, nid=norm_id).data()
    if not rows:
        return None
    src = dict(rows[0])
    dich_rows = neo.run(_Q_DICH_CUA_NGUON, nid=norm_id).data()
    targets = [dict(r) for r in dich_rows]
    if not targets:
        return None
    dieu_rows = neo.run(_Q_TOAN_BO_DIEU, nid=norm_id).data()
    src["ctx"] = _chon_ngu_canh(dieu_rows, [t["so_hieu"] for t in targets])
    return src, targets


def xu_ly_1_vb(neo, llm_ds, llm_gm, norm_id: str) -> dict | None:
    data = lay_du_lieu_nguon(neo, norm_id)
    if not data:
        return None
    src, targets = data
    user_prompt = _prompt_user(src, targets)
    # Moi dich can ~100-150 token JSON (target_so_hieu+loai+ly_do) -> co gian theo so
    # dich, khong dung 1 muc co dinh (VB nhieu dich bi cat cut JSON, da gap thuc te
    # 2026-09-07 voi Gemini). San 500 token cho overhead + du phong.
    max_tok = max(1500, 500 + 200 * len(targets))

    cho = deepseek_offpeak_giay_cho()
    if cho > 0:
        _log(f"  Đang giờ cao điểm DeepSeek, chờ {cho:.0f}s...")
        time.sleep(cho + 1)

    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=2) as pool:
        f_ds = pool.submit(llm_ds.chat_json, _SYS, user_prompt, max_tok)
        f_gm = pool.submit(llm_gm.chat_json, _SYS, user_prompt, max_tok)
        out_ds, out_gm = f_ds.result(), f_gm.result()

    def _parse(out: dict) -> dict:
        m = {}
        for r in (out.get("ket_qua", []) if isinstance(out, dict) else []):
            sh, loai = r.get("target_so_hieu"), r.get("loai")
            if sh and loai in _LOAI_HOP_LE:
                m[sh] = {"loai": loai, "ly_do": r.get("ly_do", "")}
        return m

    ds_map, gm_map = _parse(out_ds), _parse(out_gm)
    ket_qua = []
    for t in targets:
        sh = t["so_hieu"]
        loai_ds = ds_map.get(sh, {}).get("loai")
        loai_gm = gm_map.get(sh, {}).get("loai")
        dong_thuan = loai_ds is not None and loai_ds == loai_gm
        ket_qua.append({
            "action_id": t["action_id"], "target_so_hieu": sh,
            "loai_hien_tai_graph": t["loai_hien_tai"],
            "loai_deepseek": loai_ds, "loai_gemini": loai_gm,
            "dong_thuan_2_model": dong_thuan,
            "khac_voi_graph": dong_thuan and loai_ds != t["loai_hien_tai"],
            "ly_do_deepseek": ds_map.get(sh, {}).get("ly_do", ""),
            "ly_do_gemini": gm_map.get(sh, {}).get("ly_do", ""),
        })
    return {"norm_id": norm_id, "so_hieu": src["so_hieu"], "tieu_de": src["tieu_de"],
           "so_dich": len(targets), "ket_qua": ket_qua}


def main(gioi_han: int | None = None) -> None:
    env = _load_env(ENV_PATH)
    driver = GraphDatabase.driver(env["NEO4J_URI"], auth=(env["NEO4J_USER"], env["NEO4J_PASSWORD"]))
    neo = driver.session()

    llm_ds = LLMClient("deepseek", env.get("DEEPSEEK_MODEL", "deepseek-v4-flash"),
                       env["DEEPSEEK_API_KEY"], "https://api.deepseek.com",
                       extra={"reasoning_effort": "none"})
    llm_gm = LLMClient("gemini", env.get("GEMINI_MODEL", "gemini-2.5-flash"),
                       env["GEMINI_API_KEY"], "https://generativelanguage.googleapis.com/v1beta/openai/",
                       extra={"extra_body": {"google": {"thinking_config": {"thinking_budget": 0}}}})

    da_xong = set()
    if os.path.exists(LOG_PATH):
        with open(LOG_PATH, encoding="utf-8") as f:
            for line in f:
                try:
                    da_xong.add(json.loads(line)["norm_id"])
                except Exception:
                    pass
    _log(f"Đã có {len(da_xong)} VB xử lý từ trước (resume)")

    danh_sach = [r["norm_id"] for r in neo.run(_Q_NGUON_CAN_RA).data()]
    con_lai = [nid for nid in danh_sach if nid not in da_xong]
    if gioi_han:
        con_lai = con_lai[:gioi_han]
    _log(f"Tổng {len(danh_sach)} VB nguồn cần rà, còn lại {len(con_lai)}"
        + (f" (giới hạn test: {gioi_han})" if gioi_han else ""))

    dem_bat_dong = 0
    for i, nid in enumerate(con_lai):
        try:
            out = xu_ly_1_vb(neo, llm_ds, llm_gm, nid)
        except Exception as e:
            _log(f"  LOI xu ly {nid}: {e!r}")
            out = None
        if out:
            n_bd = sum(1 for r in out["ket_qua"] if not r["dong_thuan_2_model"])
            dem_bat_dong += n_bd
            with open(LOG_PATH, "a", encoding="utf-8") as f:
                f.write(json.dumps(out, ensure_ascii=False) + "\n")
        else:
            with open(LOG_PATH, "a", encoding="utf-8") as f:
                f.write(json.dumps({"norm_id": nid, "loi": True}, ensure_ascii=False) + "\n")
        if (i + 1) % 50 == 0:
            _log(f"  {i+1}/{len(con_lai)} VB · bất đồng cộng dồn: {dem_bat_dong}")

    _log(f"XONG toàn bộ {len(con_lai)} VB. Tổng bất đồng: {dem_bat_dong}")


if __name__ == "__main__":
    gh = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1] else None
    main(gioi_han=gh)
