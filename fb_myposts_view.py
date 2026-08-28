"""สร้างหน้าเว็บหน้าตาเหมือนเฟซบุ๊ก จากข้อมูลที่ fb_myposts.py เก็บมา

เจ้าของสั่ง 23 ส.ค. 2569:
  "ทำ excel + ทำ artifact ที่เหมือนเฟสบุ้ค สามารถคลิ้กเข้าไปดูคอมเมนต์
   เพิ่มเติมต่างๆได้ เก็บยอดไลค์ ยอดถูกใจในแต่ละคอมเมนต์มาด้วย
   เก็บรูปและข้อความทุกคอมเมนต์เลย"

ออก 2 ไฟล์จากเนื้อเดียวกัน
  ดูโพสต์.html   ← เปิดในเครื่องได้เลย (ดับเบิลคลิก) รูปคมเต็มความละเอียด
  artifact.html  ← เอาไปเผยแพร่เป็นหน้าเว็บส่วนตัว รูปฝังในไฟล์ บีบให้พอดีโควตา

**ทำไมต้องบีบรูปสำหรับตัวเผยแพร่** หน้าเว็บที่เผยแพร่ต้องไม่เกิน 16 MB และ
รูปทุกใบต้องฝังอยู่ในไฟล์ (ดึงจากข้างนอกไม่ได้) — โพสต์ 60 ใบมีรูปหลักร้อย
ถ้าฝังดิบๆ ทะลุโควตาแน่นอน โค้ดจึงลดขนาดลงเรื่อยๆ จนพอดี **แล้วบอกว่าลดไปเท่าไร**
ไม่ใช่เงียบๆ ตัดรูปทิ้ง

รัน:
    python fb_myposts_view.py                 สร้างทั้งสองไฟล์
    python fb_myposts_view.py --local-only    เอาเฉพาะไฟล์เปิดในเครื่อง
    python fb_myposts_view.py --budget-mb 14  เปลี่ยนโควตาไฟล์เผยแพร่
"""
from __future__ import annotations

import argparse
import base64
import html
import io
import json
import re
import sys
from datetime import datetime
from pathlib import Path

import fb_mass_finder as mf

OUT_DIR = mf.DATA_DIR / "myposts"
RAW_FILE = OUT_DIR / "myposts.json"
LOCAL_FILE = OUT_DIR / "ดูโพสต์.html"
ARTIFACT_FILE = OUT_DIR / "artifact.html"

BUDGET_MB = 15.0                 # เผื่อจาก 16 MB ไว้หน่อย
POST_IMAGE_STEPS = [(900, 80), (760, 74), (640, 68), (520, 60), (420, 52)]
COMMENT_IMAGE_STEPS = [(420, 74), (360, 68), (300, 60), (240, 52), (200, 45)]


def log(message: str) -> None:
    print(f"{datetime.now():%H:%M:%S} {message}", flush=True)


# ------------------------------------------------------------------- รูปภาพ
def encode_image(path: Path, max_width: int, quality: int) -> str | None:
    """ย่อรูปแล้วแปลงเป็นข้อความฝังในหน้าเว็บ — คืน None ถ้าอ่านไม่ได้"""
    try:
        from PIL import Image
    except ImportError:
        try:                       # ไม่มีตัวย่อรูป = ฝังของเดิมไปเลย
            raw = path.read_bytes()
        except OSError:
            return None
        return "data:image/jpeg;base64," + base64.b64encode(raw).decode()

    try:
        with Image.open(path) as image:
            image = image.convert("RGB")
            if image.width > max_width:
                ratio = max_width / image.width
                image = image.resize((max_width, max(1, round(image.height * ratio))),
                                     Image.LANCZOS)
            buffer = io.BytesIO()
            image.save(buffer, "JPEG", quality=quality, optimize=True)
        return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode()
    except Exception:
        return None


def collect_image_paths(posts: list[dict]) -> tuple[list[Path], list[Path]]:
    post_images, comment_images = [], []
    for post in posts:
        post_images += [Path(p) for p in (post.get("image_files") or [])]
        for item in post.get("comment_list") or []:
            comment_images += [Path(p) for p in (item.get("image_files") or [])]
    return ([p for p in post_images if p.is_file()],
            [p for p in comment_images if p.is_file()])


def build_image_bank(posts: list[dict], budget_bytes: int) -> tuple[dict, str]:
    """ย่อรูปทุกใบให้รวมแล้วไม่เกินโควตา — คืน (แผนที่พาธ→ข้อความรูป, หมายเหตุ)

    ไล่ลดคุณภาพเป็นขั้นๆ จนพอดี ถ้าลดจนสุดแล้วยังไม่พอ **จะบอกตรงๆ**
    ว่าเหลือรูปกี่ใบที่ต้องตัดออก ไม่ใช่ตัดเงียบๆ
    """
    post_paths, comment_paths = collect_image_paths(posts)
    total_files = len(post_paths) + len(comment_paths)
    if not total_files:
        return {}, "ไม่มีรูปให้ฝัง"

    for step in range(len(POST_IMAGE_STEPS)):
        pw, pq = POST_IMAGE_STEPS[step]
        cw, cq = COMMENT_IMAGE_STEPS[min(step, len(COMMENT_IMAGE_STEPS) - 1)]
        bank: dict[str, str] = {}
        size = 0
        for path in post_paths:
            data = encode_image(path, pw, pq)
            if data:
                bank[str(path)] = data
                size += len(data)
        for path in comment_paths:
            data = encode_image(path, cw, cq)
            if data:
                bank[str(path)] = data
                size += len(data)
        note = (f"ย่อรูปโพสต์เหลือกว้าง {pw} จุด (คุณภาพ {pq}) · "
                f"รูปคอมเมนต์ {cw} จุด — รวม {size/1e6:.1f} MB จาก {len(bank)} รูป")
        log(f"  ลองระดับที่ {step + 1}: {size/1e6:.1f} MB")
        if size <= budget_bytes:
            return bank, note

    # ลดจนสุดแล้วยังไม่พอ — ตัดรูปคอมเมนต์ออกก่อน เพราะรูปโพสต์สำคัญกว่า
    pw, pq = POST_IMAGE_STEPS[-1]
    bank, size = {}, 0
    for path in post_paths:
        data = encode_image(path, pw, pq)
        if data:
            bank[str(path)] = data
            size += len(data)
    dropped = len(comment_paths)
    note = (f"⚠️ รูปเยอะเกินโควตา — **ตัดรูปในคอมเมนต์ออก {dropped} ใบ** "
            f"(ยังอยู่ครบในเครื่อง เปิดจากไฟล์ ดูโพสต์.html ได้) "
            f"เหลือ {size/1e6:.1f} MB")
    log(f"  {note}")
    return bank, note


# -------------------------------------------------------------- ตัวช่วยเขียน
def esc(text) -> str:
    return html.escape(str(text or ""))


_URL_RE = re.compile(r"(https?://[^\s]+)")


def rich_text(text: str) -> str:
    """แปลงข้อความเป็น HTML — ขึ้นบรรทัดใหม่จริง + ลิงก์กดได้ + แฮชแท็กเน้นสี"""
    out = esc(text)
    out = _URL_RE.sub(
        lambda m: f'<a href="{m.group(1)}" target="_blank" rel="noopener">'
                  f'{m.group(1)[:60]}{"…" if len(m.group(1)) > 60 else ""}</a>',
        out)
    out = re.sub(r"(#[^\s#<]{1,40})", r'<span class="tag">\1</span>', out)
    return out.replace("\n", "<br>")


def initials(name: str) -> str:
    name = (name or "?").strip()
    return esc(name[:1].upper() or "?")


def _short(text: str, limit: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[:limit].rstrip() + "…"


def nice_number(value) -> str:
    try:
        value = int(value or 0)
    except (TypeError, ValueError):
        return "0"
    return f"{value:,}"


# ------------------------------------------------------------------ ชิ้นส่วน
def render_comment(item: dict, bank: dict | None) -> str:
    files = item.get("image_files") or []
    shots = []
    for path in files:
        src = bank.get(str(path)) if bank is not None else _file_url(path)
        if src:
            shots.append(f'<img class="cimg" src="{src}" loading="lazy" '
                         f'alt="รูปในคอมเมนต์">')
    likes = int(item.get("likes") or 0)
    spam = ' <span class="spam">อาจเป็นสแปม</span>' if item.get("is_spam") else ""
    return f"""
<div class="cmt{' reply' if item.get('is_reply') else ''}">
  <div class="ava sm">{initials(item.get('author'))}</div>
  <div class="cbody">
    <div class="bubble">
      <div class="cname">{esc(item.get('author'))}{spam}</div>
      <div class="ctext">{rich_text(item.get('text') or '')}</div>
    </div>
    {'<div class="cshots">' + ''.join(shots) + '</div>' if shots else ''}
    <div class="cmeta">
      <span class="clike">👍 {nice_number(likes)}</span>
      <span>{esc(item.get('when'))}</span>
    </div>
  </div>
</div>"""


def _file_url(path) -> str:
    return "file:///" + str(path).replace("\\", "/").replace(" ", "%20")


def render_post(post: dict, index: int, bank: dict | None) -> str:
    shots = []
    for path in post.get("image_files") or []:
        src = bank.get(str(path)) if bank is not None else _file_url(path)
        if src:
            shots.append(f'<img src="{src}" loading="lazy" alt="รูปในโพสต์">')
    grid = ""
    if shots:
        style = "one" if len(shots) == 1 else ("two" if len(shots) == 2 else "many")
        grid = f'<div class="shots {style}">{"".join(shots)}</div>'

    comments = post.get("comment_list")
    if comments is None:
        cblock = ('<div class="nocmt">ยังไม่ได้เก็บคอมเมนต์ของโพสต์นี้</div>')
    elif not comments:
        cblock = '<div class="nocmt">ไม่มีคอมเมนต์</div>'
    else:
        real = [c for c in comments if not c.get("is_spam")]
        spam_n = len(comments) - len(real)
        head = f"ดูคอมเมนต์ทั้งหมด {len(comments):,} อัน"
        if spam_n:
            head += f" (สแปม {spam_n})"
        cblock = (f'<details class="cwrap"><summary>{head}</summary>'
                  + "".join(render_comment(c, bank) for c in comments)
                  + "</details>")

    warn = ""
    if post.get("comment_warn"):
        warn = f'<div class="warn">⚠️ {esc(post["comment_warn"])}</div>'
    if post.get("unknown"):
        warn += (f'<div class="warn">⚠️ เฟซไม่ส่งตัวเลขช่องนี้มา: '
                 f'{esc(", ".join(post["unknown"]))} — ยอดรวมจริงอาจสูงกว่านี้</div>')

    total = int(post.get("total") or 0)
    caption = post.get("caption") or ""
    status = post.get("mass_status") or "ไม่แมส"
    kind = {"แมส": "mass", "ไม่แมส": "plain"}.get(status, "unsure")
    product = post.get("product") or "(ไม่ระบุ)"
    spread = int(post.get("product_groups") or 0)
    spread_tip = (f" · ชุดนี้ลงไป {spread} กลุ่ม" if spread > 1 else "")
    f = post.get("features") or {}
    chips = " ".join(
        f'<span class="chip">{esc(t)}</span>' for t in filter(None, [
            f.get("การเปิดหัว"), f.get("ช่วงเวลา"),
            f"{f.get('ตัวอักษร', 0)} ตัวอักษร",
            (f"อิโมจิ {f['อิโมจิ']}" if f.get("อิโมจิ") else ""),
            ("มีราคา" if f.get("มีราคา") else ""),
        ]))
    return f"""
<article class="post {kind}" data-group="{esc(post.get('gid'))}"
         data-mass="{kind}" data-product="{esc(post.get('product_key'))}"
         data-total="{total}" data-time="{post.get('posted_at') or 0}"
         data-text="{esc((caption + ' ' + (post.get('group_name') or '') + ' ' + product).lower())}"
         style="--i:{index}">
  <div class="ribbon {kind}">{esc(status)}</div>
  <header class="phead">
    <div class="ava">{initials(post.get('group_name'))}</div>
    <div class="pmeta">
      <div class="gname">{esc(post.get('group_name'))}</div>
      <div class="ptime">{esc(post.get('posted_at_text') or 'ไม่ทราบเวลา')}
        · <span class="prod" title="ชุดคอนเทนต์เดียวกัน{esc(spread_tip)}"
          >📦 {esc(product)}{esc(spread_tip)}</span></div>
    </div>
    <a class="open" href="{esc(post.get('url'))}" target="_blank"
       rel="noopener" title="เปิดโพสต์จริงบนเฟซบุ๊ก">↗</a>
  </header>
  <div class="chips">{chips}</div>
  <div class="cap">{rich_text(caption) or '<i>ไม่มีข้อความ</i>'}</div>
  {grid}
  {warn}
  <div class="bar">
    <span class="stat"><b>{nice_number(post.get('likes'))}</b> ถูกใจ</span>
    <span class="stat"><b>{nice_number(post.get('comments'))}</b> คอมเมนต์</span>
    <span class="stat"><b>{nice_number(post.get('shares'))}</b> แชร์</span>
    <span class="stat sum"><b>{nice_number(total)}</b> รวม</span>
  </div>
  {cblock}
</article>"""


# ------------------------------------------------------------------ ทั้งหน้า
CSS = """
:root{
  --bg:#f0f2f5; --card:#fff; --ink:#050505; --dim:#65676b; --line:#ced0d4;
  --accent:#1877f2; --chip:#e4e6eb; --warn:#8a6d00; --warnbg:#fff8e1;
  --spam:#b3261e; --good:#1F7A3D; --bad:#8B3A2F;
  --shadow:0 1px 2px rgba(0,0,0,.2);
}
@media (prefers-color-scheme:dark){
  :root:not([data-theme="light"]){
    --bg:#18191a; --card:#242526; --ink:#e4e6eb; --dim:#b0b3b8; --line:#3e4042;
    --accent:#2d88ff; --chip:#3a3b3c; --warn:#e3b341; --warnbg:#2b2410;
    --spam:#ff6b6b; --good:#3fa96b; --bad:#d1705f;
    --shadow:0 1px 2px rgba(0,0,0,.5);
  }
}
:root[data-theme="dark"]{
  --bg:#18191a; --card:#242526; --ink:#e4e6eb; --dim:#b0b3b8; --line:#3e4042;
  --accent:#2d88ff; --chip:#3a3b3c; --warn:#e3b341; --warnbg:#2b2410;
  --spam:#ff6b6b; --good:#3fa96b; --bad:#d1705f;
    --shadow:0 1px 2px rgba(0,0,0,.5);
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
  font-family:"Segoe UI",system-ui,-apple-system,"Sarabun","Noto Sans Thai",sans-serif;
  font-size:15px;line-height:1.5}
.wrap{max-width:720px;margin:0 auto;padding:16px 12px 64px}
h1{font-size:22px;margin:0 0 4px}
.sub{color:var(--dim);font-size:13px;margin-bottom:14px}
.tools{position:sticky;top:0;z-index:20;background:var(--bg);
  padding:10px 0;border-bottom:1px solid var(--line);margin-bottom:14px}
.row{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
/* min-width:0 สำคัญมาก — ช่องเลือกจะกว้างตามตัวเลือกที่ยาวที่สุดโดยอัตโนมัติ
   ชื่อสินค้าที่ยาวจึงดันหน้าทั้งหน้าให้ล้นออกด้านข้างบนมือถือ (เจอจริง 23 ส.ค.
   ล้นไป 119 จุดบนจอ 375) — ตัวนี้บอกว่า "หดได้ ไม่ต้องกางตามเนื้อใน" */
input,select{font:inherit;padding:8px 10px;border-radius:18px;
  border:1px solid var(--line);background:var(--card);color:var(--ink);
  max-width:100%;min-width:0}
input{flex:1 1 170px}
select{flex:1 1 150px;text-overflow:ellipsis}
.kpis{display:flex;gap:8px;flex-wrap:wrap;margin:10px 0 0}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:10px;
  padding:8px 12px;font-size:12px;color:var(--dim);flex:1;min-width:110px}
.kpi b{display:block;font-size:19px;color:var(--ink);line-height:1.25}
.seg{gap:6px;margin-bottom:8px}
.seg-b{font:inherit;font-size:13px;padding:7px 14px;border-radius:18px;cursor:pointer;
  border:1px solid var(--line);background:var(--card);color:var(--dim)}
.seg-b b{color:var(--ink)}
.seg-b.on{background:var(--accent);border-color:var(--accent);color:#fff}
.seg-b.on b{color:#fff}
.seg-b.mass.on{background:var(--good);border-color:var(--good)}
.seg-b.plain.on{background:var(--bad);border-color:var(--bad)}
.seg-b.unsure.on{background:var(--warn);border-color:var(--warn);color:#000}
.seg-b.unsure.on b{color:#000}
.post{background:var(--card);border-radius:10px;margin-bottom:16px;
  box-shadow:var(--shadow);overflow:hidden;position:relative;
  border-left:4px solid transparent}
.post.mass{border-left-color:var(--good)}
.post.plain{border-left-color:var(--bad)}
.post.unsure{border-left-color:var(--warn)}
.ribbon{position:absolute;top:10px;right:12px;font-size:11px;font-weight:700;
  padding:3px 9px;border-radius:10px;color:#fff;letter-spacing:.02em}
.ribbon.mass{background:var(--good)}
.ribbon.plain{background:var(--bad)}
.ribbon.unsure{background:var(--warn);color:#000}
.pmeta{min-width:0}
.prod{color:var(--accent)}
.chips{display:flex;gap:5px;flex-wrap:wrap;padding:2px 14px 8px}
.chip{font-size:11px;background:var(--chip);color:var(--dim);
  padding:2px 8px;border-radius:9px;white-space:nowrap}
.phead{display:flex;align-items:center;gap:10px;padding:12px 40px 6px 14px}
.ava{width:40px;height:40px;border-radius:50%;background:var(--accent);
  color:#fff;display:grid;place-items:center;font-weight:700;flex:none}
.ava.sm{width:30px;height:30px;font-size:13px;background:var(--dim)}
.gname{font-weight:600}
.ptime{color:var(--dim);font-size:12px}
.open{margin-left:auto;color:var(--dim);text-decoration:none;font-size:19px;
  padding:4px 8px;border-radius:8px}
.open:hover{background:var(--chip)}
.cap{padding:4px 14px 12px;white-space:normal;word-break:break-word}
.cap a,.ctext a{color:var(--accent)}
.tag{color:var(--accent)}
.shots{display:grid;gap:2px;background:var(--line)}
.shots.two{grid-template-columns:1fr 1fr}
.shots.many{grid-template-columns:1fr 1fr}
.shots img{width:100%;display:block;max-height:520px;object-fit:cover;cursor:zoom-in}
.shots.one img{max-height:640px;object-fit:contain;background:#000}
.bar{display:flex;gap:14px;flex-wrap:wrap;padding:10px 14px;
  border-top:1px solid var(--line);font-size:13px;color:var(--dim)}
.stat b{color:var(--ink)}
.stat.sum b{color:var(--accent)}
.warn{margin:8px 14px;padding:8px 10px;border-radius:8px;font-size:12px;
  background:var(--warnbg);color:var(--warn)}
.cwrap{border-top:1px solid var(--line);padding:6px 14px 12px}
.cwrap>summary{cursor:pointer;padding:8px 0;font-weight:600;color:var(--accent);
  font-size:14px;list-style:none}
.cwrap>summary::-webkit-details-marker{display:none}
.cwrap>summary::before{content:"▸ ";display:inline-block;transition:transform .15s}
.cwrap[open]>summary::before{content:"▾ "}
.nocmt{border-top:1px solid var(--line);padding:12px 14px;color:var(--dim);
  font-size:13px}
.cmt{display:flex;gap:8px;margin:10px 0}
.cmt.reply{margin-left:38px}
.cbody{min-width:0;flex:1}
.bubble{background:var(--chip);border-radius:16px;padding:8px 12px;
  display:inline-block;max-width:100%}
.cname{font-weight:600;font-size:13px}
.ctext{font-size:14px;word-break:break-word}
.cshots{margin-top:6px;display:flex;gap:6px;flex-wrap:wrap}
.cimg{max-width:200px;border-radius:10px;cursor:zoom-in}
.cmeta{display:flex;gap:12px;font-size:12px;color:var(--dim);padding:3px 12px}
.clike{font-weight:600;color:var(--ink)}
.spam{color:var(--spam);font-weight:400;font-size:11px}
.none{text-align:center;color:var(--dim);padding:40px 0}
#lb{position:fixed;inset:0;background:rgba(0,0,0,.9);display:none;
  place-items:center;z-index:99;cursor:zoom-out;padding:20px}
#lb.on{display:grid}
#lb img{max-width:100%;max-height:100%;border-radius:8px}
"""

JS = """
const posts=[...document.querySelectorAll('.post')];
const q=document.getElementById('q'), g=document.getElementById('g'),
      p=document.getElementById('p'), s=document.getElementById('s'),
      n=document.getElementById('n');
let massFilter='';
function apply(){
  const t=(q.value||'').toLowerCase().trim(), gid=g.value, prod=p.value;
  let shown=0;
  posts.forEach(el=>{
    const ok=(!gid||el.dataset.group===gid)
          &&(!prod||el.dataset.product===prod)
          &&(!massFilter||el.dataset.mass===massFilter)
          &&(!t||el.dataset.text.includes(t));
    el.style.display=ok?'':'none'; if(ok)shown++;
  });
  n.textContent=shown;
  document.getElementById('empty').style.display=shown?'none':'block';
  const box=document.getElementById('feed');
  const key=s.value;
  [...box.children].sort((a,b)=>key==='old'
      ? (+a.dataset.time)-(+b.dataset.time)
      : key==='new' ? (+b.dataset.time)-(+a.dataset.time)
      : (+b.dataset.total)-(+a.dataset.total))
    .forEach(el=>box.appendChild(el));
}
document.querySelectorAll('.seg-b').forEach(b=>b.addEventListener('click',()=>{
  document.querySelectorAll('.seg-b').forEach(x=>x.classList.remove('on'));
  b.classList.add('on'); massFilter=b.dataset.m; apply();
}));
[q,g,p,s].forEach(el=>el.addEventListener('input',apply));
const lb=document.getElementById('lb'), lbi=lb.querySelector('img');
document.addEventListener('click',e=>{
  if(e.target.matches('.shots img,.cimg')){lbi.src=e.target.src;lb.classList.add('on');}
  else if(e.target===lb||e.target===lbi){lb.classList.remove('on');}
});
document.addEventListener('keydown',e=>{if(e.key==='Escape')lb.classList.remove('on')});
apply();
"""


def build_body(data: dict, bank: dict | None, note: str) -> str:
    everything = list(data.get("posts") or [])
    everything.sort(key=lambda p: p.get("total") or 0, reverse=True)

    groups: dict = {}
    products: dict = {}
    for post in everything:
        groups.setdefault(post.get("gid"), post.get("group_name") or post.get("gid"))
        key = post.get("product_key")
        if key:
            slot = products.setdefault(key, {"label": post.get("product") or "?",
                                             "n": 0, "mass": 0})
            slot["n"] += 1
            if post.get("mass_status") == "แมส":
                slot["mass"] += 1

    n_mass = sum(1 for p in everything if p.get("mass_status") == "แมส")
    n_plain = sum(1 for p in everything if p.get("mass_status") == "ไม่แมส")
    n_unsure = len(everything) - n_mass - n_plain
    n_comments = sum(len(p.get("comment_list") or []) for p in everything)
    n_cimages = sum(len(c.get("image_files") or [])
                    for p in everything for c in (p.get("comment_list") or []))
    top = everything[0].get("total") if everything else 0
    rate = round(n_mass * 100 / len(everything), 1) if everything else 0

    gopts = "".join(f'<option value="{esc(gid)}">{esc(name)}</option>'
                    for gid, name in sorted(groups.items(), key=lambda x: x[1]))
    popts = "".join(
        f'<option value="{esc(k)}">{esc(_short(v["label"], 34))}'
        f' — {v["n"]} โพสต์ (แมส {v["mass"]})</option>'
        for k, v in sorted(products.items(),
                           key=lambda x: (-x[1]["mass"], -x[1]["n"])))
    unsure_btn = (f'<button class="seg-b unsure" data-m="unsure">'
                  f'ไม่แน่ใจ <b>{n_unsure}</b></button>' if n_unsure else "")
    cards = "".join(render_post(p, i, bank) for i, p in enumerate(everything))
    stamp = data.get("saved_at") or ""
    minimum = data.get("minimum", 100)

    # ประกาศภาษาไว้ต้นไฟล์ด้วย แม้ตัวห่อหุ้มน่าจะใส่ให้แล้ว — เบราว์เซอร์อ่าน
    # 1,024 ไบต์แรกเพื่อเดาภาษา ถ้าไม่มีบอกไว้เลยจะเดาเป็นภาษาฝรั่งแล้ว
    # ภาษาไทยกลายเป็นตัวอักษรขยะทั้งหน้า (เจอจริงตอนทดสอบ 23 ส.ค.)
    return f"""<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<div class="wrap">
<h1>โพสต์ของฉันทั้งหมด</h1>
<div class="sub">บัญชี {esc(data.get('my_name') or data.get('user_id'))}
 · เก็บเมื่อ {esc(stamp[:16].replace('T', ' '))}
 · เส้นแบ่งแมสคือยอดรวมเกิน {minimum}
 · {esc(note)}</div>

<div class="tools">
  <div class="row seg">
    <button class="seg-b on" data-m="">ทั้งหมด <b>{len(everything)}</b></button>
    <button class="seg-b mass" data-m="mass">🔥 แมส <b>{n_mass}</b></button>
    <button class="seg-b plain" data-m="plain">ไม่แมส <b>{n_plain}</b></button>
    {unsure_btn}
  </div>
  <div class="row">
    <input id="q" type="search" placeholder="ค้นหาแคปชัน · กลุ่ม · สินค้า…">
    <select id="g"><option value="">ทุกกลุ่ม ({len(groups)})</option>{gopts}</select>
    <select id="p"><option value="">ทุกสินค้า ({len(products)})</option>{popts}</select>
    <select id="s">
      <option value="top">ยอดรวมมากสุดก่อน</option>
      <option value="new">ใหม่สุดก่อน</option>
      <option value="old">เก่าสุดก่อน</option>
    </select>
  </div>
  <div class="kpis">
    <div class="kpi"><b><span id="n">{len(everything)}</span></b> โพสต์ที่แสดง</div>
    <div class="kpi"><b>{rate}%</b> อัตราแมส</div>
    <div class="kpi"><b>{len(products)}</b> ชุดสินค้า</div>
    <div class="kpi"><b>{n_comments:,}</b> คอมเมนต์</div>
    <div class="kpi"><b>{n_cimages:,}</b> รูปในคอมเมนต์</div>
    <div class="kpi"><b>{nice_number(top)}</b> ยอดสูงสุด</div>
  </div>
</div>

<div id="feed">{cards}</div>
<div id="empty" class="none" style="display:none">ไม่พบโพสต์ที่ตรงกับที่ค้น</div>
</div>
<div id="lb"><img alt="รูปขยาย"></div>
<style>{CSS}</style>
<script>{JS}</script>"""


def build(local_only: bool = False, budget_mb: float = BUDGET_MB) -> int:
    if not RAW_FILE.is_file():
        log(f"❌ ยังไม่มีข้อมูล — รัน python fb_myposts.py ก่อน ({RAW_FILE})")
        return 1
    data = json.loads(RAW_FILE.read_text(encoding="utf-8"))
    total_posts = len(data.get("posts") or []) + len(data.get("unsure") or [])
    if not total_posts:
        log("❌ ยังไม่มีโพสต์ในข้อมูล — อาจยังเก็บไม่เสร็จ")
        return 1
    log(f"โพสต์ในข้อมูล: {total_posts} ใบ")

    # 1) ไฟล์เปิดในเครื่อง — ชี้ไปที่ไฟล์รูปจริง ไม่จำกัดขนาด รูปคมสุด
    body = build_body(data, None, "รูปอ่านจากโฟลเดอร์ในเครื่อง (คมเต็มความละเอียด)")
    LOCAL_FILE.parent.mkdir(parents=True, exist_ok=True)
    LOCAL_FILE.write_text(
        "<!doctype html><html lang=\"th\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        "<title>โพสต์ของฉัน</title></head><body>" + body + "</body></html>",
        encoding="utf-8")
    log(f"✅ ไฟล์เปิดในเครื่อง: {LOCAL_FILE} "
        f"({LOCAL_FILE.stat().st_size/1e6:.1f} MB)")

    if local_only:
        return 0

    # 2) ไฟล์เผยแพร่ — ฝังรูปทั้งหมดลงในไฟล์ ต้องไม่เกินโควตา
    log("กำลังย่อรูปสำหรับไฟล์เผยแพร่…")
    posts = (data.get("posts") or []) + (data.get("unsure") or [])
    bank, note = build_image_bank(posts, int(budget_mb * 1e6))
    ARTIFACT_FILE.write_text(build_body(data, bank, note), encoding="utf-8")
    size = ARTIFACT_FILE.stat().st_size / 1e6
    log(f"{'✅' if size <= 16 else '❌'} ไฟล์เผยแพร่: {ARTIFACT_FILE} ({size:.1f} MB)")
    if size > 16:
        log("❌ ยังเกิน 16 MB — ลองสั่งใหม่ด้วย --budget-mb 10")
        return 2
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--local-only", action="store_true",
                        help="สร้างเฉพาะไฟล์ที่เปิดในเครื่อง (เร็ว ไม่ต้องย่อรูป)")
    parser.add_argument("--budget-mb", type=float, default=BUDGET_MB)
    args = parser.parse_args(argv)
    return build(args.local_only, args.budget_mb)


if __name__ == "__main__":
    sys.exit(main())
