"""Dựng phiếu review C5 — một trang HTML tự chứa.

Không có backend: phán quyết lưu vào localStorage của trình duyệt, người duyệt bấm
"Xuất CSV" khi xong. Không cần cài gì, không cần mạng, mở bằng double-click.
"""
from __future__ import annotations

import html
import json


def _esc(s) -> str:
    return html.escape(str(s if s is not None else ""))


def _the(it: dict, i: int) -> str:
    rf = it.get("reference_fields") or {}
    # ` · ` chứ không phải `""`: thẻ có từ hai văn bản trở lên thì các số hiệu dính
    # liền nhau thành một chuỗi vô nghĩa — `145/2020/NĐ-CP148/2018/NĐ-CP`. Lỗi này
    # nằm im vì phần lớn thẻ chỉ có một link, tới khi C5 bổ sung link cho G2/G7/G8
    # mới lộ. Người duyệt phải phân biệt được đâu là văn bản nào để bấm đúng cái.
    nguon = " · ".join(
        f'<a href="{_esc(n["url"])}" target="_blank" rel="noopener">'
        f'{_esc(n["so_hieu"] or n["norm_id"])}</a>'
        if n.get("url") else f'<span class="nolink">{_esc(n["so_hieu"] or n["norm_id"])}</span>'
        for n in (it.get("c5_nguon") or [])
    ) or '<span class="nolink">— không có link nguồn —</span>'

    ctx = "".join(f"<pre>{_esc(c)}</pre>" for c in (it.get("reference_contexts") or [])) \
        or '<p class="nolink">— nhóm này không có đoạn trích (đúng thiết kế) —</p>'

    phu = []
    if it.get("as_of_date"):
        phu.append(f"mốc hỏi <b>{_esc(it['as_of_date'])}</b> "
                   f"({_esc(it.get('as_of_kind'))})")
    if rf.get("danh_sach"):
        phu.append("danh sách: <b>" + _esc("; ".join(rf["danh_sach"])) + "</b>")
    phu_html = f'<div class="phu">{" · ".join(phu)}</div>' if phu else ""

    return f"""
<article class="card" data-id="{_esc(it['id'])}" data-group="{_esc(it['group'])}">
  <header>
    <span class="ma">{_esc(it['id'])}</span>
    <span class="tag">{_esc(it['group'])}</span>
    <span class="tag nhat">{_esc(it.get('question_form'))}</span>
    <span class="stt">{i}</span>
  </header>

  <div class="khoi">
    <h4>Câu hỏi</h4>
    <p class="hoi">{_esc(it.get('user_input'))}</p>
  </div>

  <div class="khoi">
    <h4>Đáp án bộ đề coi là ĐÚNG</h4>
    <p class="dapan">{_esc(it.get('reference'))}</p>
    {phu_html}
  </div>

  <div class="khoi kiem">
    <h4>Việc cần kiểm</h4>
    <p>{it.get('c5_cau_hoi_kiem', '')}</p>
    <p class="nguon">Văn bản gốc: {nguon}</p>
  </div>

  <details class="khoi">
    <summary>Đoạn trích dẫn bộ đề dùng làm ngữ cảnh</summary>
    {ctx}
  </details>

  <div class="phan-quyet">
    <label><input type="radio" name="v_{_esc(it['id'])}" value="dung"> Đúng</label>
    <label><input type="radio" name="v_{_esc(it['id'])}" value="sai"> Sai</label>
    <label><input type="radio" name="v_{_esc(it['id'])}" value="khong_chac"> Không chắc</label>
    <input type="text" class="ghichu" placeholder="ghi chú (nếu Sai — sai ở đâu?)">
  </div>
</article>"""


CSS = """
*{box-sizing:border-box}
body{font:15px/1.55 -apple-system,Segoe UI,Roboto,sans-serif;margin:0;
  background:#f6f7f9;color:#1a1d21}
.wrap{max-width:920px;margin:0 auto;padding:24px 18px 80px}
h1{font-size:22px;margin:0 0 4px}
.gt{background:#fff;border:1px solid #e3e6ea;border-radius:10px;padding:16px 18px;
  margin-bottom:22px}
.gt h2{font-size:15px;margin:14px 0 6px}
.gt ul{margin:6px 0;padding-left:20px}
.gt code{background:#eef0f3;padding:1px 5px;border-radius:4px;font-size:13px}
.card{background:#fff;border:1px solid #e3e6ea;border-radius:10px;padding:16px 18px;
  margin-bottom:16px}
.card.xong{border-color:#b8ddc0;background:#fbfefb}
.card header{display:flex;align-items:center;gap:8px;margin-bottom:12px}
.ma{font-family:ui-monospace,Consolas,monospace;font-weight:600;font-size:13px}
.tag{background:#eef0f3;border-radius:20px;padding:2px 10px;font-size:12px}
.tag.nhat{background:transparent;border:1px solid #dde1e6;color:#5b626b}
.stt{margin-left:auto;color:#9aa1a9;font-size:12px}
.khoi{margin:12px 0}
h4{font-size:12px;text-transform:uppercase;letter-spacing:.05em;color:#6b727b;
  margin:0 0 5px}
.hoi{font-size:16px;margin:0}
.dapan{margin:0;padding:9px 12px;background:#f2f6ff;border-left:3px solid #6f9dff;
  border-radius:0 6px 6px 0;white-space:pre-wrap}
.phu{font-size:13px;color:#5b626b;margin-top:6px}
.kiem{background:#fffaf0;border:1px solid #f0e2c8;border-radius:8px;padding:11px 13px}
.kiem p{margin:0 0 6px}
.nguon{font-size:13px}
.nguon a{color:#1a5fd0}
.nolink{color:#9aa1a9}
details summary{cursor:pointer;font-size:12px;text-transform:uppercase;
  letter-spacing:.05em;color:#6b727b}
pre{white-space:pre-wrap;background:#f6f7f9;border:1px solid #e8eaee;border-radius:6px;
  padding:10px 12px;font-size:13px;margin:8px 0 0;max-height:280px;overflow:auto}
.phan-quyet{display:flex;flex-wrap:wrap;gap:14px;align-items:center;margin-top:14px;
  padding-top:13px;border-top:1px solid #eef0f3}
.phan-quyet label{cursor:pointer;user-select:none}
.ghichu{flex:1;min-width:200px;padding:6px 9px;border:1px solid #dde1e6;
  border-radius:6px;font:inherit;font-size:14px}
.thanh{position:fixed;left:0;right:0;bottom:0;background:#fff;
  border-top:1px solid #e3e6ea;padding:10px 18px;display:flex;gap:14px;
  align-items:center;justify-content:center;font-size:14px}
button{font:inherit;padding:7px 15px;border-radius:7px;border:1px solid #c9ced5;
  background:#fff;cursor:pointer}
button.chinh{background:#1a5fd0;border-color:#1a5fd0;color:#fff}
@media (prefers-color-scheme:dark){
  body{background:#14171a;color:#e6e8ea}
  .gt,.card,.thanh{background:#1c2024;border-color:#2c3238}
  .card.xong{background:#182019;border-color:#2f4a35}
  .tag,.gt code,pre{background:#22272c}
  pre{border-color:#2c3238}
  .dapan{background:#1a2233}
  .kiem{background:#221d14;border-color:#3a3222}
  .ghichu,button{background:#22272c;border-color:#333a41;color:#e6e8ea}
  .nguon a{color:#7aa9f7}
}
"""

JS = """
const KEY='c5_'+DOC_ID;
const luu=()=>{const o={};document.querySelectorAll('.card').forEach(c=>{
  const id=c.dataset.id, r=c.querySelector('input[type=radio]:checked');
  o[id]={v:r?r.value:'', n:c.querySelector('.ghichu').value};});
  localStorage.setItem(KEY,JSON.stringify(o)); dem();};
const nap=()=>{const o=JSON.parse(localStorage.getItem(KEY)||'{}');
  document.querySelectorAll('.card').forEach(c=>{const d=o[c.dataset.id]; if(!d)return;
    if(d.v){const r=c.querySelector(`input[value="${d.v}"]`); if(r)r.checked=true;}
    c.querySelector('.ghichu').value=d.n||'';}); dem();};
const dem=()=>{const t=document.querySelectorAll('.card').length;
  let x=0; document.querySelectorAll('.card').forEach(c=>{
    const ok=!!c.querySelector('input[type=radio]:checked');
    c.classList.toggle('xong',ok); if(ok)x++;});
  document.getElementById('tiendo').textContent=`${x}/${t} đã duyệt`;};
document.addEventListener('change',luu);
document.addEventListener('input',e=>{if(e.target.classList.contains('ghichu'))luu();});
function xuat(){
  const h=['id','group','verdict','note'];const d=[h.join(',')];
  document.querySelectorAll('.card').forEach(c=>{
    const r=c.querySelector('input[type=radio]:checked');
    const n=(c.querySelector('.ghichu').value||'').replace(/"/g,'""');
    d.push([c.dataset.id,c.dataset.group,r?r.value:'',`"${n}"`].join(','));});
  const b=new Blob([d.join('\\n')],{type:'text/csv;charset=utf-8'});
  const a=document.createElement('a');a.href=URL.createObjectURL(b);
  a.download='c5_ket_qua.csv';a.click();}
nap();
"""


def dung_html(mau: list[dict], snapshot: str) -> str:
    nhom = sorted({it["group"] for it in mau})
    the = "\n".join(_the(it, i) for i, it in enumerate(sorted(
        mau, key=lambda x: (x["group"], x["id"])), 1))
    return f"""<!doctype html>
<meta charset="utf-8">
<title>Phiếu review C5 — {len(mau)} câu</title>
<style>{CSS}</style>
<div class="wrap">
<h1>Phiếu review C5</h1>
<p style="color:#6b727b;margin:0 0 18px">{len(mau)} câu · nhóm {", ".join(nhom)}
 · snapshot <code>{_esc(snapshot)}</code></p>

<div class="gt">
<h2>Việc này để làm gì</h2>
<p>Đáp án trong bộ đề sinh tự động từ đồ thị Neo4j, nên nó chỉ đúng <b>so với đồ
thị</b> — không phải so với luật. Nếu khâu trích xuất có lỗi thì bộ đề mã hoá đúng lỗi
đó, rồi <b>chấm sai một hệ RAG trả lời đúng</b>.</p>
<p>Tỷ lệ đúng bạn chấm ở đây gọi là <code>eval_set_ceiling</code> — <b>trần trên của
mọi chỉ số đánh giá về sau</b>. Chưa có nó thì không con số nào diễn giải được.</p>

<h2>Cách làm</h2>
<ul>
<li>Mỗi thẻ có ô <b>Việc cần kiểm</b> nêu đúng thứ phải đối chiếu — không cần tự nghĩ.</li>
<li>Mở link văn bản gốc, đối chiếu, chọn <b>Đúng</b> / <b>Sai</b> / <b>Không chắc</b>.</li>
<li>Chọn <b>Sai</b> thì ghi ngắn <i>sai ở đâu</i> — đó là đầu vào để sửa khâu trích xuất.</li>
<li><b>Không chắc</b> là lựa chọn hợp lệ. Đoán bừa làm hỏng chính con số cần đo.</li>
<li>Kết quả tự lưu trong trình duyệt. Xong thì bấm <b>Xuất CSV</b>.</li>
</ul>

<h2>Ngưỡng</h2>
<p>Nhóm nào dưới <b>95% đúng</b> thì <b>không đưa vào bộ eval tự động</b> — phải sửa
khâu trích xuất trước, hoặc chuyển nhóm đó sang duyệt tay toàn bộ.</p>
<p style="color:#6b727b;font-size:13px;margin-bottom:0">Lưu ý về độ phân giải: mẫu
này chia đều các nhóm, nên mỗi nhóm chỉ khoảng {max(1, len(mau)//max(len(nhom),1))}
câu. Ở cỡ đó, một câu sai đã kéo tỷ lệ xuống ~{100//max(len(mau)//max(len(nhom),1),1)}
điểm phần trăm — hãy đọc kết quả như một <b>phép sàng</b>, và mở rộng mẫu cho nhóm nào
ra kết quả sát ngưỡng.</p>
</div>

{the}
</div>
<div class="thanh">
  <span id="tiendo">0/0</span>
  <button class="chinh" onclick="xuat()">Xuất CSV</button>
  <button onclick="if(confirm('Xoá toàn bộ phán quyết đã chấm?')){{
    localStorage.removeItem('c5_'+DOC_ID);location.reload();}}">Xoá hết</button>
</div>
<script>const DOC_ID={json.dumps(snapshot)};{JS}</script>
"""
