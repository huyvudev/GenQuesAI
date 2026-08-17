"""Bộ soi bộ đề — một trang HTML tự chứa để đọc và kiểm 400 câu đã sinh.

    python -m generator.soi_bo_de                          # -> out/soi_bo_de.html
    python -m generator.soi_bo_de --vao out/g7.jsonl --ra /tmp/g7.html

Khác `render_c5.py` ở mục đích, đừng lẫn:

    C5   người có chuyên môn LUẬT phán đáp án đúng/sai -> `eval_set_ceiling`
         mẫu nhỏ, có phán quyết, xuất CSV
    soi  người làm KỸ THUẬT xem bộ sinh vừa đẻ ra cái gì
         toàn bộ, không phán quyết, có lọc và cảnh báo tự động

Cùng quy ước với phiếu C5: không backend, không mạng, mở bằng double-click.

Cảnh báo tự động
────────────────
Mỗi luật dưới đây là một lỗi ĐÃ XẢY RA THẬT trên bộ đề này, không phải phòng xa.
Chúng cố ý bắt những thứ mà cổng C1–C5 KHÔNG bắt được — vì mỗi câu vẫn tự nhất quán,
chỉ bộ đề xét như một tổng thể mới thấy sai.
"""
from __future__ import annotations

import argparse
import html
import json
import sys
from collections import Counter
from pathlib import Path

from .common import co_so_hieu, setup_stdout

# mã -> (nhãn, giải thích ngắn hiện trong giao diện)
LUAT = {
    "trung_cau": ("câu trùng",
                  "có câu khác hỏi y hệt — chấm hai lần cùng một thứ, lệch trọng số"),
    "lo_so_hieu": ("situation lộ số hiệu",
                   "câu situation phải GIẤU định danh, nêu ra là mồi từ khoá cho BM25"),
    "thieu_gold": ("thiếu gold span",
                   "không có đoạn trích thì context_recall không đo được gì"),
    "c1_khong_pass": ("C1 không pass",
                      "C1 rớt là LỖI PIPELINE (§2) — phải điều tra, không phải loại câu"),
    "c4_leak": ("C4 leak",
                "mô hình trả lời đúng khi KHÔNG có ngữ cảnh -> câu này không đo retrieval"),
    "bang_chung_yeu": ("bằng chứng yếu",
                       "evidence_score < 5: span có từ khoá nhưng không phải câu dẫn"),
    "khong_co_bay": ("không có bẫy",
                     "thiếu distractor thì không phân biệt được retriever_nham với _sot"),
    "dap_an_rong": ("đáp án rỗng", "không có gì để chấm"),
    "trich_dan_rong": ("trích dẫn rỗng",
                       "có gold_spans nhưng không có văn bản đi kèm"),
    "cho_review": ("chờ review",
                   "G6: điều kiện (3) §4.2 không tự động hoá đáng tin được"),
}
# Ba nhóm này thiết kế là PHẢI có bẫy (§5.3). G3/G4/G5 thì không.
CAN_BAY = {"G1", "G2", "G7"}
# G8 không có gold_spans là đúng thiết kế: câu không có đáp án thì không trích gì.
KHONG_CAN_SPAN = {"G8"}


def canh_bao(rows: list[dict]) -> dict[str, list[str]]:
    """Trả {id: [mã cảnh báo]}. Không phán quyết — chỉ nêu chỗ đáng nhìn."""
    dem_cau = Counter(r.get("user_input", "") for r in rows)
    ra: dict[str, list[str]] = {}
    for r in rows:
        g, gates = r.get("group"), (r.get("gates") or {})
        c: list[str] = []
        if dem_cau[r.get("user_input", "")] > 1:
            c.append("trung_cau")
        if r.get("question_form") == "situation" and co_so_hieu(r.get("user_input") or ""):
            c.append("lo_so_hieu")
        if not r.get("gold_spans") and g not in KHONG_CAN_SPAN:
            c.append("thieu_gold")
        if gates.get("C1") != "pass" and g not in KHONG_CAN_SPAN:
            c.append("c1_khong_pass")
        if r.get("do_retrieval") is False:
            c.append("c4_leak")
        if r.get("evidence_score") is not None and r["evidence_score"] < 5:
            c.append("bang_chung_yeu")
        if not r.get("distractor_ids") and g in CAN_BAY:
            c.append("khong_co_bay")
        if not r.get("reference"):
            c.append("dap_an_rong")
        if r.get("gold_spans") and not r.get("reference_contexts"):
            c.append("trich_dan_rong")
        if r.get("status") == "cho_review":
            c.append("cho_review")
        if c:
            ra[r["id"]] = c
    return ra


CSS = """
*{box-sizing:border-box}
html,body{height:100%}
body{font:14px/1.5 -apple-system,Segoe UI,Roboto,sans-serif;margin:0;
  background:#f6f7f9;color:#1a1d21;display:flex;flex-direction:column}
header{background:#fff;border-bottom:1px solid #e3e6ea;padding:10px 16px;flex:none}
.tieu{display:flex;align-items:baseline;gap:12px;flex-wrap:wrap}
h1{font-size:16px;margin:0}
.meta{color:#6b727b;font-size:12px}
.chips{display:flex;gap:6px;flex-wrap:wrap;margin-top:8px}
.chip{border:1px solid #dde1e6;background:#fff;border-radius:20px;padding:3px 11px;
  font-size:12px;cursor:pointer;user-select:none;font-family:inherit;color:inherit}
.chip:hover{border-color:#9aa1a9}
.chip.on{background:#1a5fd0;border-color:#1a5fd0;color:#fff}
.chip.cb{border-color:#e3c9a0;background:#fffaf0}
.chip.cb.on{background:#c47b1b;border-color:#c47b1b;color:#fff}
.chip .n{opacity:.65;margin-left:5px}
main{flex:1;display:flex;min-height:0}
#ds{width:290px;flex:none;border-right:1px solid #e3e6ea;background:#fff;
  overflow:auto;padding:8px}
#ds .mu{padding:9px 10px;border-radius:7px;cursor:pointer;margin-bottom:2px}
#ds .mu:hover{background:#f2f4f7}
#ds .mu.chon{background:#e8f0fe}
#ds .ma{font-family:ui-monospace,Consolas,monospace;font-size:12px;font-weight:600}
#ds .ma .co{color:#c47b1b;margin-left:5px}
#ds .hoi{color:#5b626b;font-size:12px;margin-top:2px;
  display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
#ct{flex:1;overflow:auto;padding:18px 22px 60px}
.rong{color:#9aa1a9;text-align:center;margin-top:60px}
.hd{display:flex;align-items:center;gap:7px;flex-wrap:wrap;margin-bottom:14px}
.hd .ma{font-family:ui-monospace,Consolas,monospace;font-weight:700;font-size:15px}
.tag{background:#eef0f3;border-radius:20px;padding:2px 10px;font-size:12px}
.tag.v{background:transparent;border:1px solid #dde1e6;color:#5b626b}
.kb{margin:0 0 16px;padding:11px 13px;background:#fffaf0;border:1px solid #f0e2c8;
  border-radius:8px}
.kb b{color:#8a5a10}
.kb div{font-size:13px;margin-top:3px}
h4{font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:#6b727b;
  margin:18px 0 6px}
.hoi-to{font-size:17px;margin:0}
.truoc{color:#6b727b;font-size:13px;margin:6px 0 0;padding-left:11px;
  border-left:2px solid #e3e6ea}
.dapan{margin:0;padding:10px 13px;background:#f2f6ff;border-left:3px solid #6f9dff;
  border-radius:0 6px 6px 0;white-space:pre-wrap}
table{border-collapse:collapse;font-size:13px;width:100%;max-width:760px}
td{padding:4px 10px 4px 0;vertical-align:top;border-bottom:1px solid #eef0f3}
td.k{color:#6b727b;width:190px;white-space:nowrap}
code,.mono{font-family:ui-monospace,Consolas,monospace;font-size:12px}
pre{white-space:pre-wrap;background:#fff;border:1px solid #e8eaee;border-radius:6px;
  padding:11px 13px;font-size:13px;margin:6px 0 0;max-height:340px;overflow:auto}
.span-hd{font-size:12px;color:#6b727b;margin-top:12px}
details{margin-top:18px}
summary{cursor:pointer;font-size:11px;text-transform:uppercase;letter-spacing:.06em;
  color:#6b727b}
.tim{padding:5px 10px;border:1px solid #dde1e6;border-radius:7px;font:inherit;
  font-size:13px;width:200px;background:#fff;color:inherit}
.dk{margin-left:auto;color:#6b727b;font-size:12px}
mark{background:#ffe89a;color:inherit;border-radius:2px}
@media (prefers-color-scheme:dark){
  body{background:#14171a;color:#e6e8ea}
  header,#ds,pre,.chip,.tim{background:#1c2024;border-color:#2c3238}
  #ds .mu:hover{background:#22272c} #ds .mu.chon{background:#1b2b47}
  .tag,code{background:#22272c}
  .dapan{background:#1a2233} .kb{background:#221d14;border-color:#3a3222}
  .kb b{color:#e0a94c} .chip.cb{background:#221d14;border-color:#3a3222}
  td{border-color:#22272c} mark{background:#6b5417;color:#f4e6c0}
}
"""

JS = r"""
const $=s=>document.querySelector(s);
const esc=s=>String(s??'').replace(/[&<>"]/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[m]));
let loc={nhom:new Set(),dang:'',cb:'',tim:''}, chon=null;

const cua=r=>CB[r.id]||[];
function qua(r){
  if(loc.nhom.size && !loc.nhom.has(r.group))return false;
  if(loc.dang && r.question_form!==loc.dang)return false;
  if(loc.cb==='__any'){if(!cua(r).length)return false;}
  else if(loc.cb && !cua(r).includes(loc.cb))return false;
  if(loc.tim){
    const t=loc.tim.toLowerCase();
    const kho=[r.id,r.user_input,r.reference,JSON.stringify(r.reference_fields||{})].join(' ').toLowerCase();
    if(!kho.includes(t))return false;
  }
  return true;
}
function veDs(){
  const ds=DATA.filter(qua);
  $('#dk').textContent=`${ds.length}/${DATA.length} câu`;
  $('#ds').innerHTML=ds.map(r=>{
    const n=cua(r).length;
    return `<div class="mu${chon===r.id?' chon':''}" data-id="${r.id}">
      <div class="ma">${r.id}${n?`<span class="co">⚠${n>1?n:''}</span>`:''}</div>
      <div class="hoi">${esc(r.user_input)}</div></div>`;}).join('')
    ||'<p class="rong">không câu nào khớp</p>';
  if(ds.length && !ds.some(r=>r.id===chon))ve(ds[0].id);
  else if(!ds.length){chon=null;$('#ct').innerHTML='<p class="rong">không câu nào khớp bộ lọc</p>';}
}
const bang=o=>Object.entries(o||{}).map(([k,v])=>
  `<tr><td class="k">${esc(k)}</td><td>${esc(Array.isArray(v)?v.join('; '):
    (typeof v==='object'?JSON.stringify(v):v))}</td></tr>`).join('');

function ve(id){
  chon=id;
  document.querySelectorAll('#ds .mu').forEach(e=>e.classList.toggle('chon',e.dataset.id===id));
  const r=DATA.find(x=>x.id===id); if(!r)return;
  const cb=cua(r);
  const kb=cb.length?`<div class="kb">${cb.map(m=>
    `<div><b>⚠ ${esc(LUAT[m][0])}</b> — ${esc(LUAT[m][1])}</div>`).join('')}</div>`:'';
  const truoc=(r.question_pre_paraphrase&&r.question_pre_paraphrase!==r.user_input)
    ?`<p class="truoc"><b>trước paraphrase:</b> ${esc(r.question_pre_paraphrase)}</p>`:'';
  const bay=(r.distractor_ids||[]).length
    ?`<h4>Bẫy (${r.distractor_ids.length})</h4><div class="mono">${r.distractor_ids.map(esc).join('<br>')}</div>`:'';
  const spans=(r.gold_spans||[]).map((g,i)=>{
    const t=(r.reference_contexts||[])[i];
    return `<div class="span-hd"><code>${esc(g.expr_id)}</code> · part ${g.part}
      · offset [${g.start}:${g.end}] · chunk <code>${esc(g.chunk_id)}</code>
      · sha <code>${esc((g.chunk_text_sha256||'').slice(0,12))}…</code></div>
      ${t?`<pre>${esc(t)}</pre>`:''}`;}).join('')
    ||'<p style="color:#9aa1a9;margin:6px 0 0">— không có (đúng thiết kế với G8) —</p>';
  const cong=Object.entries(r.gates||{}).map(([k,v])=>
    `<span class="tag v">${k} ${esc(v)}</span>`).join(' ');
  const phu={};
  for(const k of ['reference_type','grader','difficulty','evidence','evidence_score',
                  'as_of_date','as_of_kind','cong_thuc','c4_diem','do_retrieval',
                  'question_template','graph_snapshot','index_version'])
    if(r[k]!==undefined)phu[k]=r[k];
  if((r.gold_node_ids||[]).length)phu['gold_node_ids']=r.gold_node_ids;
  if(r.c4_tra_loi_khong_ngu_canh)phu['c4_trả_lời_không_ngữ_cảnh']=r.c4_tra_loi_khong_ngu_canh;

  $('#ct').innerHTML=`
  <div class="hd"><span class="ma">${r.id}</span>
    <span class="tag">${r.group}</span>
    <span class="tag v">${esc(r.question_form)}</span>
    <span class="tag v">${esc(r.persona)}</span>
    ${r.status&&r.status!=='san_sang'?`<span class="tag">${esc(r.status)}</span>`:''}</div>
  ${kb}
  <h4>Câu hỏi</h4><p class="hoi-to">${esc(r.user_input)}</p>${truoc}
  <h4>Đáp án bộ đề coi là đúng</h4><p class="dapan">${esc(r.reference)}</p>
  <h4>Trường đáp án</h4><table>${bang(r.reference_fields)}</table>
  ${bay}
  <h4>Gold span</h4>${spans}
  <h4>Cổng</h4><div>${cong}</div>
  <h4>Siêu dữ liệu</h4><table>${bang(phu)}</table>
  <details><summary>JSON thô</summary>
    <pre>${esc(JSON.stringify(r,null,1))}</pre></details>`;
  $('#ct').scrollTop=0;
}
function nut(sel,lay){
  document.querySelectorAll(sel).forEach(b=>b.onclick=()=>{lay(b);veDs();});
}
// Nhóm cho chọn NHIỀU (xem G1 và G3 cùng lúc); dạng và cảnh báo chỉ một, vì hai
// cái đó dùng để khoanh vùng chứ không phải để gộp.
nut('#f-nhom .chip',b=>{
  const g=b.dataset.v;
  if(loc.nhom.has(g))loc.nhom.delete(g);else loc.nhom.add(g);
  b.classList.toggle('on');});
nut('#f-dang .chip',b=>{
  loc.dang=loc.dang===b.dataset.v?'':b.dataset.v;
  document.querySelectorAll('#f-dang .chip').forEach(x=>
    x.classList.toggle('on',x.dataset.v===loc.dang));});
nut('#f-cb .chip',b=>{
  loc.cb=loc.cb===b.dataset.v?'':b.dataset.v;
  document.querySelectorAll('#f-cb .chip').forEach(x=>
    x.classList.toggle('on',x.dataset.v===loc.cb));});
$('#tim').oninput=e=>{loc.tim=e.target.value.trim();veDs();};
$('#ds').onclick=e=>{const m=e.target.closest('.mu');if(m)ve(m.dataset.id);};
document.onkeydown=e=>{
  if(e.target.tagName==='INPUT')return;
  if(e.key!=='j'&&e.key!=='k'&&e.key!=='ArrowDown'&&e.key!=='ArrowUp')return;
  const ds=DATA.filter(qua), i=ds.findIndex(r=>r.id===chon);
  const j=(e.key==='j'||e.key==='ArrowDown')?i+1:i-1;
  if(j>=0&&j<ds.length){ve(ds[j].id);
    const el=document.querySelector(`#ds .mu[data-id="${ds[j].id}"]`);
    if(el)el.scrollIntoView({block:'nearest'});}
  e.preventDefault();};
veDs();
"""


def _esc(s) -> str:
    return html.escape(str(s if s is not None else ""))


def _nhung(x) -> str:
    """JSON nhúng vào <script>. `</` phải cắt, nếu không chuỗi chứa '</script>'
    trong nội dung văn bản sẽ đóng thẻ sớm và cả trang hỏng."""
    return json.dumps(x, ensure_ascii=False).replace("</", "<\\/")


def dung_html(rows: list[dict], cb: dict[str, list[str]], nguon: str) -> str:
    nhom = Counter(r["group"] for r in rows)
    dang = Counter(r.get("question_form") for r in rows)
    dem_cb = Counter(m for ds in cb.values() for m in ds)
    snap = next((r.get("graph_snapshot") for r in rows if r.get("graph_snapshot")), "—")

    chip_nhom = "".join(
        f'<button class="chip" data-v="{g}">{g}<span class="n">{n}</span></button>'
        for g, n in sorted(nhom.items()))
    chip_dang = "".join(
        f'<button class="chip" data-v="{_esc(d)}">{_esc(d)}<span class="n">{n}</span></button>'
        for d, n in sorted(dang.items()) if d)
    chip_cb = (f'<button class="chip cb" data-v="__any">⚠ có cảnh báo'
               f'<span class="n">{len(cb)}</span></button>') + "".join(
        f'<button class="chip cb" data-v="{m}">{_esc(LUAT[m][0])}'
        f'<span class="n">{n}</span></button>'
        for m, n in dem_cb.most_common())

    return f"""<!doctype html>
<meta charset="utf-8">
<title>Soi bộ đề — {len(rows)} câu</title>
<style>{CSS}</style>
<header>
  <div class="tieu">
    <h1>Soi bộ đề</h1>
    <span class="meta">{len(rows)} câu · <code>{_esc(nguon)}</code>
      · snapshot <code>{_esc(snap)}</code></span>
    <input id="tim" class="tim" placeholder="tìm trong câu hỏi / đáp án / id…">
    <span class="dk" id="dk"></span>
  </div>
  <div class="chips" id="f-nhom">{chip_nhom}</div>
  <div class="chips" id="f-dang">{chip_dang}</div>
  <div class="chips" id="f-cb">{chip_cb}</div>
</header>
<main><div id="ds"></div><div id="ct"></div></main>
<script>
const DATA={_nhung(rows)};
const CB={_nhung(cb)};
const LUAT={_nhung({k: list(v) for k, v in LUAT.items()})};
{JS}
</script>
"""


def main() -> int:
    setup_stdout()
    ap = argparse.ArgumentParser()
    ap.add_argument("--vao", type=Path, default=Path("out/eval_set.jsonl"))
    ap.add_argument("--ra", type=Path, default=Path("out/soi_bo_de.html"))
    a = ap.parse_args()

    if not a.vao.exists():
        print(f"không thấy {a.vao} — chạy `python -m generator.run_all` trước")
        return 1
    rows = [json.loads(x) for x in
            a.vao.read_text(encoding="utf-8").splitlines() if x.strip()]
    cb = canh_bao(rows)

    a.ra.parent.mkdir(parents=True, exist_ok=True)
    a.ra.write_text(dung_html(rows, cb, str(a.vao).replace("\\", "/")),
                    encoding="utf-8")

    print(f"{len(rows)} câu -> {a.ra}   ({a.ra.stat().st_size / 1024:.0f} KB)")
    dem = Counter(m for ds in cb.values() for m in ds)
    if dem:
        print(f"\n  {len(cb)} câu có cảnh báo:")
        for m, n in dem.most_common():
            print(f"   {n:>4}  {LUAT[m][0]:<22} {LUAT[m][1]}")
    else:
        print("  không câu nào có cảnh báo")
    return 0


if __name__ == "__main__":
    sys.exit(main())
