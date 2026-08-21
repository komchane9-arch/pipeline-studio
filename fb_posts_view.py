"""แสดงข้อมูลที่เก็บมาเป็นหน้าเว็บ **หน้าตาเหมือน Facebook**

ผู้ใช้สั่ง 18 ส.ค. 2569: "เวลาดึงมาโชว์ปรับให้ pattern เหมือนกับใน facebook เลย
เอาให้ดูแล้วเป็นแพทเทิร์นเดียวกันเข้าใจง่ายๆ"

เหตุผลที่ทำแบบนี้ไม่ใช่แค่สวย: คนที่อ่านรายงานคือคนที่ใช้ Facebook ทุกวัน
พอเห็นการ์ดหน้าตาเดิม สมองจะอ่าน caption/ยอด/คอมเมนต์ได้ทันทีโดยไม่ต้องแปลตาราง
และเทียบ "โพสต์แมส vs ไม่แมส" ได้ด้วยสายตาเดียว

รัน:  python fb_posts_view.py [โฟลเดอร์ดัมพ์] [--open]
"""
from __future__ import annotations

import html
import json
import re
import sys
import webbrowser
from datetime import datetime
from pathlib import Path

import fb_mass_finder as mf
import fb_posts_parse as pp

PROBE_DIR = mf.DATA_DIR / "fb_posts_probe"
OUT_FILE = mf.DATA_DIR / "fb_posts_view.html"

# เกณฑ์ "โพสต์แมส" ของผู้ใช้ — engagement เกิน 100 (ค่าเดียวกับ config min_likes)
MASS_THRESHOLD = 100

THAI_MONTHS = ["", "ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.",
               "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."]


def thai_time(ts: int | None) -> str:
    """เวลาแบบที่ Facebook เขียน — ใหม่ๆ บอกเป็น 'x ชม.' เก่าแล้วบอกวันที่"""
    if not ts:
        return ""
    when = datetime.fromtimestamp(ts)
    delta = datetime.now() - when
    if delta.days < 1:
        hours = int(delta.total_seconds() // 3600)
        return f"{hours} ชม." if hours else f"{int(delta.total_seconds() // 60)} นาที"
    if delta.days < 7:
        return f"{delta.days} วัน"
    if when.year == datetime.now().year:
        return f"{when.day} {THAI_MONTHS[when.month]}"
    return f"{when.day} {THAI_MONTHS[when.month]} {when.year + 543 - 2500:02d}"


def fb_number(n: int | None) -> str:
    """ย่อเลขแบบ Facebook ไทย — 2438 → '2.4 พัน' · 20528 → '2 หมื่น'"""
    if n is None:
        return "—"
    if n < 1_000:
        return f"{n:,}"
    if n < 10_000:
        return f"{n/1000:.1f}".rstrip("0").rstrip(".") + " พัน"
    if n < 100_000:
        return f"{n/10000:.1f}".rstrip("0").rstrip(".") + " หมื่น"
    if n < 1_000_000:
        return f"{n/100000:.1f}".rstrip("0").rstrip(".") + " แสน"
    return f"{n/1_000_000:.1f}".rstrip("0").rstrip(".") + " ล้าน"


def initials(name: str) -> str:
    parts = [p for p in re.split(r"\s+", name.strip()) if p]
    return (parts[0][:1] + (parts[1][:1] if len(parts) > 1 else "")).upper() or "?"


def avatar_html(name: str, uri: str = "", size: int = 40) -> str:
    if uri:
        return (f'<img class="ava" style="width:{size}px;height:{size}px" '
                f'src="{html.escape(uri)}" alt="" loading="lazy">')
    hue = sum(ord(c) for c in name) % 360
    return (f'<div class="ava fallback" style="width:{size}px;height:{size}px;'
            f'background:hsl({hue},45%,55%);font-size:{size//2.6:.0f}px">'
            f'{html.escape(initials(name))}</div>')


def image_grid(images: list[dict]) -> str:
    """ตารางรูปแบบ Facebook — 1 รูปเต็ม · 2 รูปคู่ · 3 รูปใหญ่+เล็ก · 4+ มี +N"""
    if not images:
        return ""
    shots = images[:4]
    extra = len(images) - len(shots)

    def one(img: dict, cls: str = "") -> str:
        alt = html.escape((img.get("alt") or "")[:120])
        return (f'<div class="ph {cls}"><img src="{html.escape(img["uri"])}" '
                f'alt="{alt}" title="{alt}" loading="lazy"></div>')

    if len(shots) == 1:
        body = one(shots[0], "solo")
    elif len(shots) == 2:
        body = one(shots[0]) + one(shots[1])
    elif len(shots) == 3:
        body = (f'<div class="col big">{one(shots[0])}</div>'
                f'<div class="col">{one(shots[1])}{one(shots[2])}</div>')
    else:
        last = one(shots[3])
        if extra:
            last = last.replace('<div class="ph ">', '<div class="ph more">')
            last = last.replace("</div>", f'<span class="plus">+{extra}</span></div>', 1)
        body = (f'<div class="col">{one(shots[0])}{one(shots[1])}</div>'
                f'<div class="col">{one(shots[2])}{last}</div>')
    return f'<div class="grid g{len(shots)}">{body}</div>'


def caption_html(text: str) -> str:
    if not text:
        return ""
    safe = html.escape(text)
    safe = re.sub(r"(#[^\s#]+)", r'<span class="tag">\1</span>', safe)
    short = len(text) <= 320
    body = safe.replace("\n", "<br>")
    if short:
        return f'<div class="cap">{body}</div>'
    cut = html.escape(text[:300]).replace("\n", "<br>")
    return (f'<div class="cap"><span class="short">{cut}…'
            f'<button class="more-btn">ดูเพิ่มเติม</button></span>'
            f'<span class="full" hidden>{body}</span></div>')


def post_card(post: dict, comments: list[dict], group_name: str) -> str:
    eng = pp.engagement(post)
    is_mass = eng > MASS_THRESHOLD
    badge = (f'<div class="verdict mass">🔥 โพสต์แมส · engagement {eng:,}</div>'
             if is_mass else
             f'<div class="verdict quiet">โพสต์เงียบ · engagement {eng:,}</div>')
    reactions = post.get("reactions")
    n_com = post.get("comments")
    n_share = post.get("shares")
    stat_left = (f'<span class="icons">👍❤️</span>'
                 f'<span>{fb_number(reactions)}</span>') if reactions else ""
    right = []
    if n_com:
        right.append(f"{fb_number(n_com)} ความคิดเห็น")
    if n_share:
        right.append(f"{fb_number(n_share)} การแชร์")
    stat_right = f'<span>{" · ".join(right)}</span>' if right else ""

    # ผู้ใช้สั่ง 18 ส.ค.: "ถ้ามี 100 คอมเมนต์ให้โชว์ให้หมด" — ไม่ตัดจำนวน
    shown = [c for c in comments if not c["spam"]]
    spam = [c for c in comments if c["spam"]]
    com_html = "".join(comment_html(c) for c in shown)
    if spam:
        rows = "".join(comment_html(c, spam=True) for c in spam)
        com_html += (
            f'<details class="spam-box"><summary>🚫 คอมเมนต์สแปม {len(spam)} '
            "รายการ (เงินกู้/พนัน/ขายของ) — ไม่นับตอนวิเคราะห์ฐานลูกค้า "
            "· กดเพื่อดู</summary>" + rows + "</details>")
    if comments:
        com_html = (f'<div class="com-head">ความคิดเห็นทั้งหมด {len(shown):,} รายการ'
                    + (f" · ซ่อนสแปม {len(spam)}" if spam else "")
                    + "</div>" + com_html)

    return f"""
<article class="card">
  {badge}
  <header class="head">
    {avatar_html(post.get("author", ""), post.get("avatar", ""))}
    <div class="who">
      <div class="name">{html.escape(post.get("author") or "ไม่ทราบชื่อ")}</div>
      <div class="meta">{html.escape(group_name)} · {thai_time(post.get("posted_at"))} ·
        <span class="globe">🌐</span></div>
    </div>
    <div class="dots">⋯</div>
  </header>
  {caption_html(post.get("caption") or "")}
  {image_grid(post.get("images") or [])}
  <div class="stats"><div class="l">{stat_left}</div><div class="r">{stat_right}</div></div>
  <div class="actions">
    <button>👍 ถูกใจ</button><button>💬 แสดงความคิดเห็น</button><button>↗ แชร์</button>
  </div>
  <div class="comments">{com_html}</div>
  <div class="src"><a href="{html.escape(post.get("url") or "#")}" target="_blank">
    เปิดโพสต์จริงบน Facebook ↗</a></div>
</article>"""


def comment_html(c: dict, spam: bool = False) -> str:
    body = html.escape(c["text"]) if c["text"] else '<i class="sticker">(สติกเกอร์/รูป)</i>'
    imgs = ""
    if c.get("images"):
        imgs = ('<div class="cimgs">'
                + "".join(f'<a href="{html.escape(u)}" target="_blank">'
                          f'<img src="{html.escape(u)}" loading="lazy" alt=""></a>'
                          for u in c["images"]) + "</div>")
    # ป้ายยอดไลค์แบบ Facebook — ฟองเล็กมุมขวาล่างของบับเบิล
    likes = int(c.get("likes") or 0)
    like_tag = (f'<span class="clikes" title="{likes:,} คนถูกใจ">👍 '
                f'{fb_number(likes)}</span>') if likes else ""
    depth = int(c.get("depth") or 0)
    return f"""
  <div class="com{' reply' if depth else ''}{' spam' if spam else ''}">
    {avatar_html(c["author"], c.get("avatar", ""), 32)}
    <div class="cbody">
      <div class="bubble-wrap">
        <div class="bubble">
          <a class="cname" href="{html.escape(c.get("author_url") or "#")}"
             target="_blank">{html.escape(c["author"])}</a>
          <div class="ctext">{body}</div>
        </div>{like_tag}
      </div>
      {imgs}
      <div class="cmeta"><span>ถูกใจ</span><span>ตอบกลับ</span>
        <span class="ctime">{html.escape(c.get("when", ""))}</span></div>
    </div>
  </div>"""


def parse_comments(articles: list[dict]) -> list[dict]:
    """แปลงบล็อก DOM เป็นคอมเมนต์ที่สะอาด + ติดธงสแปม

    aria-label ของ Facebook มีรูปแบบตายตัว: "ความคิดเห็นจาก <ชื่อ> เมื่อ <เวลา>"
    ใช้ตรงนั้นแยกชื่อ/เวลาออกมา แล้วตัดหัวข้อความที่ซ้ำกับชื่อ+เวลา และตัดปุ่ม
    ท้าย (ถูกใจ/ตอบกลับ/แชร์) ออก เหลือเฉพาะเนื้อคอมเมนต์จริง
    """
    out = []
    for a in articles:
        label = a.get("label") or ""
        m = re.match(r"ความคิดเห็นจาก\s+(.+?)(?:\s+เมื่อ\s+(.+?)(?:ที่แล้ว)?)?$", label)
        if not m:
            continue
        name = m.group(1).strip()
        when = (m.group(2) or "").strip()
        text = (a.get("text") or "").strip()
        # ตัดหัว "ชื่อ · เวลา" ที่ Facebook ใส่ซ้ำในตัวบล็อก
        text = re.sub(r"^" + re.escape(name) + r"\s*", "", text)
        text = re.sub(r"^·?\s*\d+\s*(สัปดาห์|วัน|ปี|ชม\.|นาที|เดือน)\s*", "", text)
        text = re.sub(r"^·\s*ติดตาม\s*", "", text)
        # ตัดปุ่มท้ายบล็อก
        text = re.sub(r"\s*(ถูกใจ|ตอบกลับ|แชร์|ดูคำแปล|แก้ไขแล้ว)\s*$", "", text).strip()
        text = re.sub(r"\s{2,}", " ", text)
        out.append({
            "author": name, "when": when, "text": text,
            "images": [a["firstImg"]] if a.get("firstImg") and a.get("imgs") else [],
            "spam": pp.is_spam(text),
            "spam_score": pp.spam_score(text),
        })
    return out


PAGE_CSS = """
:root{
  --bg:#f0f2f5; --card:#fff; --text:#050505; --dim:#65676b; --line:#ced0d4;
  --bubble:#f0f2f5; --blue:#1877f2; --mass:#e7f3ff; --massline:#1877f2;
}
:root:not([data-theme=light]) @media (prefers-color-scheme:dark){}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){
  --bg:#18191a; --card:#242526; --text:#e4e6eb; --dim:#b0b3b8; --line:#3e4042;
  --bubble:#3a3b3c; --mass:#263951;
}}
:root[data-theme=dark]{
  --bg:#18191a; --card:#242526; --text:#e4e6eb; --dim:#b0b3b8; --line:#3e4042;
  --bubble:#3a3b3c; --mass:#263951;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);
  font-family:"Segoe UI",system-ui,-apple-system,"Noto Sans Thai",Tahoma,sans-serif;
  font-size:15px;line-height:1.34}
.wrap{max-width:620px;margin:0 auto;padding:16px 12px 60px}
.top{background:var(--card);border-radius:8px;padding:14px 16px;margin-bottom:16px;
  box-shadow:0 1px 2px rgba(0,0,0,.2)}
.top h1{font-size:19px;margin:0 0 6px}
.top .sub{color:var(--dim);font-size:13px}
.legend{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px;font-size:12px}
.legend span{padding:3px 9px;border-radius:12px;background:var(--bubble)}
.card{background:var(--card);border-radius:8px;margin-bottom:16px;
  box-shadow:0 1px 2px rgba(0,0,0,.2);overflow:hidden}
.verdict{font-size:12px;padding:6px 16px;font-weight:600}
.verdict.mass{background:var(--mass);color:var(--massline);
  border-bottom:1px solid var(--line)}
.verdict.quiet{background:var(--bubble);color:var(--dim);
  border-bottom:1px solid var(--line)}
.head{display:flex;align-items:center;gap:8px;padding:12px 16px 0}
.ava{border-radius:50%;object-fit:cover;flex:none}
.ava.fallback{display:flex;align-items:center;justify-content:center;
  color:#fff;font-weight:600}
.who{flex:1;min-width:0}
.name{font-weight:600;font-size:15px}
.meta{color:var(--dim);font-size:13px}
.dots{color:var(--dim);font-size:20px;padding:0 6px}
.cap{padding:8px 16px 12px;white-space:normal;word-break:break-word}
.cap .tag{color:var(--blue)}
.more-btn{background:none;border:0;color:var(--dim);font:inherit;
  font-weight:600;cursor:pointer;padding:0 0 0 4px}
.grid{display:grid;gap:2px;background:var(--line)}
.grid.g1{grid-template-columns:1fr}
.grid.g2{grid-template-columns:1fr 1fr}
.grid.g3,.grid.g4{grid-template-columns:1fr 1fr}
.col{display:grid;gap:2px}
.ph{position:relative;overflow:hidden;background:var(--bubble)}
.ph img{width:100%;height:100%;object-fit:cover;display:block}
.ph.solo img{max-height:600px;object-fit:contain;background:#000}
.grid.g2 .ph,.grid.g3 .ph,.grid.g4 .ph{aspect-ratio:1/1}
.ph.more::after{content:"";position:absolute;inset:0;background:rgba(0,0,0,.45)}
.plus{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;
  color:#fff;font-size:28px;font-weight:600;z-index:2}
.stats{display:flex;justify-content:space-between;padding:10px 16px;
  color:var(--dim);font-size:15px}
.icons{margin-right:5px}
.actions{display:flex;border-top:1px solid var(--line);margin:0 12px;padding:4px 0}
.actions button{flex:1;background:none;border:0;color:var(--dim);font:inherit;
  font-weight:600;padding:8px;border-radius:6px;cursor:pointer}
.actions button:hover{background:var(--bubble)}
.comments{padding:6px 16px 12px;border-top:1px solid var(--line)}
.com-head{font-weight:600;color:var(--dim);font-size:14px;padding:8px 0 2px}
.com{display:flex;gap:8px;margin-top:10px}
.com.reply{margin-left:40px}
.com.spam{opacity:.75}
.cbody{min-width:0;flex:1}
.bubble-wrap{position:relative;display:inline-block;max-width:100%}
.bubble{background:var(--bubble);border-radius:18px;padding:8px 12px}
.cname{font-size:13px;font-weight:600;color:var(--text);text-decoration:none;display:block}
.cname:hover{text-decoration:underline}
.ctext{font-size:15px;word-break:break-word;white-space:pre-wrap}
.sticker{color:var(--dim)}
/* ป้ายยอดไลค์ลอยมุมขวาล่างของฟองข้อความ — เหมือน Facebook */
.clikes{position:absolute;right:-6px;bottom:-10px;background:var(--card);
  border:1px solid var(--line);border-radius:12px;padding:1px 6px;
  font-size:12px;color:var(--dim);box-shadow:0 1px 2px rgba(0,0,0,.2);
  white-space:nowrap}
.cimgs{margin-top:8px;display:flex;gap:6px;flex-wrap:wrap}
.cimgs img{max-width:180px;max-height:180px;border-radius:12px;display:block}
.cmeta{display:flex;gap:14px;font-size:12px;font-weight:600;color:var(--dim);
  padding:6px 0 0 12px}
.ctime{font-weight:400}
.spam-box{margin-top:14px;border:1px solid var(--line);border-radius:8px;
  padding:8px 12px}
.spam-box summary{cursor:pointer;color:var(--dim);font-size:13px;font-weight:600}
.src{padding:8px 16px 14px;font-size:12px}
.src a{color:var(--dim);text-decoration:none}
.src a:hover{text-decoration:underline}
"""

PAGE_JS = """
document.addEventListener('click', e => {
  if (!e.target.classList.contains('more-btn')) return;
  const cap = e.target.closest('.cap');
  cap.querySelector('.short').hidden = true;
  cap.querySelector('.full').hidden = false;
});
"""


def build_page(posts: list[dict], comments_by_post: dict[str, list],
               group_name: str, source: str) -> str:
    mass = sum(1 for p in posts if pp.engagement(p) > MASS_THRESHOLD)
    cards = "".join(post_card(p, comments_by_post.get(p["id"], []), group_name)
                    for p in posts)
    return f"""<!doctype html>
<html lang="th"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(group_name)} — ข้อมูลที่เก็บได้</title>
<style>{PAGE_CSS}</style></head><body>
<div class="wrap">
  <div class="top">
    <h1>{html.escape(group_name)}</h1>
    <div class="sub">{html.escape(source)}</div>
    <div class="legend">
      <span>🔥 แมส = engagement เกิน {MASS_THRESHOLD}</span>
      <span>👍 ไลค์ + 💬 คอมเมนต์ + ↗ แชร์</span>
      <span>🚫 สแปมถูกกรองออก</span>
    </div>
  </div>
  {cards}
</div>
<script>{PAGE_JS}</script></body></html>"""


def load_from_db(gid: str = "") -> tuple[list[dict], dict, str, str]:
    """อ่านจากฐานข้อมูลจริง — คืน (โพสต์, คอมเมนต์ต่อโพสต์, ชื่อกลุ่ม, บรรทัดสรุป)

    รูปชี้ไปที่ไฟล์บน Google Drive ไม่ใช่ URL ของ Facebook เพราะ URL ของ CDN
    หมดอายุใน ~103 ชม. (วัดจริง 18 ส.ค.) ส่วนไฟล์ที่เก็บไว้เปิดได้ตลอดไป
    """
    import fb_posts_store as store

    conn = store.connect()
    if not gid:
        row = conn.execute("""SELECT gid FROM fb_group WHERE posts_seen > 0
                              ORDER BY last_run_at DESC LIMIT 1""").fetchone()
        if row is None:
            raise SystemExit("ยังไม่มีกลุ่มที่เก็บข้อมูลแล้ว — รัน fb_posts_collect.py ก่อน")
        gid = row["gid"]
    g = conn.execute("SELECT * FROM fb_group WHERE gid=?", (gid,)).fetchone()

    def as_uri(rel: str | None, fallback: str = "") -> str:
        if rel:
            path = store.MEDIA_ROOT / rel
            if path.is_file():
                return path.as_uri()
        return fallback

    posts = []
    for r in conn.execute("""SELECT * FROM fb_post WHERE gid=?
                             ORDER BY engagement DESC""", (gid,)):
        images = [
            {"uri": as_uri(i["rel_path"], i["src_url"]), "alt": i["alt"] or "",
             "width": i["width"], "height": i["height"]}
            for i in conn.execute("""SELECT * FROM post_image WHERE post_id=?
                                     ORDER BY idx""", (r["post_id"],))
        ]
        posts.append({
            "id": r["post_id"], "url": r["url"], "author": r["author"],
            "author_url": r["author_url"],
            # ใช้ไฟล์ที่เก็บไว้ก่อนเสมอ — URL ของ Facebook หมดอายุใน ~103 ชม.
            "avatar": as_uri(r["avatar_path"], r["avatar"]),
            "posted_at": r["posted_at"], "caption": r["caption"],
            "reactions": r["reactions"], "comments": r["comments"],
            "shares": r["shares"], "images": images,
            "comments_got": r["comments_got"], "comments_state": r["comments_state"],
        })

    by_post: dict[str, list] = {}
    for r in conn.execute("""SELECT c.* FROM fb_comment c JOIN fb_post p
                             ON p.post_id=c.post_id WHERE p.gid=?
                             ORDER BY c.post_id, c.seq""", (gid,)):
        imgs = [as_uri(i["rel_path"], i["src_url"])
                for i in conn.execute("""SELECT * FROM comment_image
                                         WHERE comment_id=? ORDER BY idx""",
                                      (r["comment_id"],))]
        by_post.setdefault(r["post_id"], []).append({
            "author": r["author"], "author_url": r["author_url"],
            "avatar": as_uri(r["avatar_path"], r["avatar"]),
            "text": r["body"], "when": r["when_text"],
            "likes": r["likes"], "images": [u for u in imgs if u],
            "depth": r["depth"], "spam": bool(r["is_spam"]),
        })

    s = store.group_summary(conn, gid)
    note = (f"เก็บจริง {s['posts']:,} โพสต์ · แมส {s['mass']:,} · "
            f"คอมเมนต์ {s['comments']:,} · รูป {s['images']:,} "
            f"({s['image_mb']:.0f} MB บน Google Drive)")
    return posts, by_post, (g["name"] if g else "กลุ่ม"), note


def main() -> int:
    if "--db" in sys.argv:
        gid = ""
        if "--gid" in sys.argv:
            gid = sys.argv[sys.argv.index("--gid") + 1]
        posts, by_post, group_name, note = load_from_db(gid)
        page = build_page(posts, by_post, group_name, note)
        OUT_FILE.write_text(page, encoding="utf-8")
        print(f"✅ สร้างหน้าจากฐานข้อมูล: {OUT_FILE}")
        print(f"   {note}")
        if "--open" in sys.argv:
            webbrowser.open(OUT_FILE.as_uri())
        return 0

    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    folder = Path(args[0]) if args else None
    if folder is None:
        dumps = sorted(PROBE_DIR.glob("2*"), key=lambda p: p.name)
        if not dumps:
            raise SystemExit("ยังไม่มีดัมพ์ — รัน fb_posts_probe.py ก่อน")
        folder = dumps[-1]

    bodies = [p.read_text(encoding="utf-8", errors="replace")
              for p in sorted(folder.glob("feed_*.json"))]
    posts_map = pp.parse_bodies(bodies)

    summary_file = folder / "summary.json"
    summary = (json.loads(summary_file.read_text(encoding="utf-8"))
               if summary_file.is_file() else {})
    group_name = re.sub(r"\s*\(เฉลี่ย.*", "", summary.get("desc", "") or "กลุ่ม Facebook")

    by_post: dict[str, list] = {}
    # 1) คอมเมนต์ชุดเต็มจากตัวเก็บใหม่ (fb_posts_comments.py) ถ้ามี
    full = mf.DATA_DIR / "fb_posts_comments_test.json"
    if full.is_file():
        data = json.loads(full.read_text(encoding="utf-8"))
        target = re.search(r"/(?:posts|permalink)/(\d+)", data.get("url", "")
                           or summary.get("permalink", ""))
        rows = []
        for c in data.get("comments", []):
            rows.append({**c, "spam": pp.is_spam(c.get("text", ""))})
        if target and rows:
            by_post[target.group(1)] = rows
    # 2) สำรอง: ชุดเก่าจาก articles.json ของ probe
    if not by_post:
        arts_file = folder / "articles.json"
        articles = (json.loads(arts_file.read_text(encoding="utf-8"))
                    if arts_file.is_file() else [])
        target = re.search(r"/(?:posts|permalink)/(\d+)",
                           summary.get("permalink", ""))
        if target:
            by_post[target.group(1)] = parse_comments(articles)

    posts = sorted(posts_map.values(), key=lambda p: -pp.engagement(p))[:12]
    page = build_page(posts, by_post, group_name, folder.name)
    OUT_FILE.write_text(page, encoding="utf-8")
    total_com = sum(len(v) for v in by_post.values())
    total_spam = sum(1 for v in by_post.values() for c in v if c["spam"])
    total_like = sum(1 for v in by_post.values() for c in v if c.get("likes"))
    total_img = sum(1 for v in by_post.values() for c in v if c.get("images"))
    print(f"✅ สร้างหน้าแล้ว: {OUT_FILE}")
    print(f"   {len(posts)} โพสต์ · คอมเมนต์ {total_com} (สแปม {total_spam}) "
          f"· มียอดไลค์ {total_like} · มีรูป {total_img}")
    if "--open" in sys.argv:
        webbrowser.open(OUT_FILE.as_uri())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
