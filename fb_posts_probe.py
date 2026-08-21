"""สำรวจว่า Facebook ส่งอะไรมาให้เราได้บ้าง — **ต้องรันก่อนเขียนตัวเก็บจริง**

ทำไมต้องมีไฟล์นี้: โค้ดเดิม (`harvest()` ใน fb_mass_finder.py) ดึงแค่ตัวเลข 6 ตัว
คือลิงก์/ไลค์/แชร์/คอมเมนต์/วิว ยังไม่เคยแตะ caption · รูป · ตัวคอมเมนต์จริงเลย
จึง **ยังไม่มีหลักฐาน** ว่าของพวกนี้อยู่ในข้อมูลที่เราดักได้อยู่แล้วหรือเปล่า
ถ้าเดาผิดแล้วเขียนตัวเก็บไปเลย จะรู้ตัวตอนเก็บไปหลายวันแล้วว่าเก็บไม่ได้

ตอบ 7 คำถาม (ผลออกมาเป็นตัวเลขจริง ไม่ใช่ความเห็น):
  P1 caption อยู่ในฟีดไหม · กี่ % ของโพสต์
  P2 เวลาโพสต์ (creation_time) อยู่ในฟีดไหม
  P3 ยอดไลค์/คอมเมนต์/แชร์ เคยมาเป็น string ไหม (regex เดิมรับไม่ได้)
  P4 ยอดวิววิดีโอใช้คีย์ชื่ออะไร (ของเดิมจับไม่ได้เลยสักโพสต์)
  P5 URL รูปโพสต์ดึงได้ไหม · หมดอายุเมื่อไร (พารามิเตอร์ oe=)
  P6 คอมเมนต์ติดมากับฟีดเลยไหม (ถ้าใช่ = ประหยัดเวลามหาศาล)
  P7 เปิด permalink แล้วได้คอมเมนต์เต็มไหม · โครงสร้างเป็นอย่างไร

รัน:  python fb_posts_probe.py [ชื่อบอท] [--scrolls N] [--group URL]
"""
from __future__ import annotations

import json
import re
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

import fb_mass_finder as mf
from bot_profiles import ProfileFarm

HERE = Path(__file__).resolve().parent
OUT_DIR = mf.DATA_DIR / "fb_posts_probe"

# ---------------------------------------------------------------- ตัวจับข้อมูล
# หา story node ในก้อน JSON — FB ใช้ __typename":"Story" กำกับทุกโพสต์
STORY_RE = re.compile(r'"__typename"\s*:\s*"Story"')
# caption: FB ห่อไว้เป็น message:{text:...} (บางทีมี delight_ranges ตามหลัง)
MESSAGE_RE = re.compile(r'"message"\s*:\s*\{\s*"(?:delight_ranges"[^}]*?)?text"\s*:\s*"')
CREATION_RE = re.compile(r'"creation_time"\s*:\s*(\d{9,})')
# ตัวเลขที่มาเป็น string — regex เดิมรับเฉพาะเลขเปลือย จะพลาดทั้งดุ้น
STR_NUM_RE = re.compile(
    r'"(reaction_count|share_count|total_comment_count|comment_count)"'
    r'\s*:\s*(?:\{\s*"count"\s*:\s*)?"(\d+)"')
# รูปจาก CDN ของ FB — เอาเฉพาะไฟล์ภาพจริง ไม่เอา sprite/emoji
IMG_RE = re.compile(
    r'https://(?:scontent|external)[^"\\\s]*?\.(?:jpg|jpeg|png|webp)[^"\\\s]*')
OE_RE = re.compile(r"[?&]oe=([0-9A-Fa-f]{8})")
# คอมเมนต์: FB ส่ง body:{text:...} ใต้ comment edges
COMMENT_BODY_RE = re.compile(r'"body"\s*:\s*\{\s*"text"\s*:\s*"')
COMMENT_TYPENAME_RE = re.compile(r'"__typename"\s*:\s*"Comment"')
# จำนวนคอมเมนต์ของโพสต์ — อยู่ในฟีดครบทุกโพสต์ (ยืนยัน 18 ส.ค.: 91 ตัว/91 โพสต์)
# ใช้คัดว่าโพสต์ไหนคุ้มค่าเปิด (โพสต์คอมเมนต์ 0 ไม่ต้องเปิดเลย)
AGG_COMMENT_RE = re.compile(r'"aggregated_comment_count"\s*:\s*(\d+)')
# คีย์ยอดวิวทุกแบบที่เป็นไปได้ — ไว้หาว่าตัวจริงชื่ออะไร
VIEWKEY_RE = re.compile(r'"(\w*(?:view|play)_count\w*)"\s*:')


def log(message: str) -> None:
    stamp = datetime.now().strftime("%H:%M:%S")
    print(f"{stamp} {message}", flush=True)


# ดึงคอมเมนต์จาก DOM ที่ render แล้ว — **ไม่ใช่จาก JSON**
# (พิสูจน์ 18 ส.ค.: GraphQL ตอนเปิด permalink มีแต่ข้อมูลระบบ ส่วนคอมเมนต์จริง
#  โผล่อยู่ใน HTML เป็น div[role="article"] ซ้อนกัน — ตัวนอกสุดคือตัวโพสต์เอง)
_COMMENT_DOM_JS = """
() => {
  const out = [];
  for (const el of document.querySelectorAll('div[role="article"]')) {
    const label = el.getAttribute('aria-label') || '';
    const links = [...el.querySelectorAll('a[href*="/user/"], a[href*="facebook.com/"]')]
      .map(a => (a.innerText || '').trim()).filter(Boolean);
    const imgs = [...el.querySelectorAll('img')].map(i => i.src)
      .filter(s => s && s.startsWith('http'));
    out.push({
      label: label.slice(0, 80),
      depth: (el.querySelectorAll('div[role="article"]').length),
      text: (el.innerText || '').replace(/\\s+/g, ' ').slice(0, 220),
      chars: (el.innerText || '').length,
      links: links.slice(0, 3),
      imgs: imgs.length,
      firstImg: imgs[0] || '',
    });
  }
  return out;
}
"""


def probe_permalink(page, url: str, dump_dir: Path, drain) -> dict:
    """เจาะหน้าโพสต์เดี่ยวโดยเฉพาะ — หาว่าคอมเมนต์โผล่มาทางไหน

    รอบแรกพบว่า GraphQL ตอนเปิดหน้ามีแต่ข้อมูลระบบ (ตั้งค่าวิดีโอ/messenger)
    เนื้อโพสต์+คอมเมนต์ของ Facebook Comet ฝังมากับ HTML ตอน render ครั้งแรก
    แล้วคอมเมนต์ที่เหลือค่อยโหลดเพิ่มตอน "เลื่อนถึง" หรือ "กดดูเพิ่มเติม"
    จึงต้องเก็บทั้ง HTML และ GraphQL ที่เกิดหลังเลื่อน/กด
    """
    bodies: list[str] = []
    stages: list[dict] = []

    def snap(tag: str) -> None:
        html = page.content()
        (dump_dir / f"pl_{tag}.html").write_text(html, encoding="utf-8")
        drain(bodies)
        stages.append({
            "tag": tag,
            "html_bytes": len(html),
            "html_comment_bodies": len(COMMENT_BODY_RE.findall(html)),
            "html_comment_nodes": len(COMMENT_TYPENAME_RE.findall(html)),
            "gql_bodies": len(bodies),
            "gql_comment_bodies": len(COMMENT_BODY_RE.findall("\n".join(bodies))),
        })
        log(f"  [{tag}] HTML {len(html)/1024:.0f} KB · "
            f"คอมเมนต์ใน HTML {stages[-1]['html_comment_bodies']} · "
            f"GraphQL สะสม {len(bodies)} ก้อน "
            f"(คอมเมนต์ {stages[-1]['gql_comment_bodies']})")

    started = time.time()
    page.goto(url, wait_until="domcontentloaded", timeout=90_000)
    page.wait_for_timeout(6_000)
    snap("1_เปิดหน้า")

    # คอมเมนต์ของ Comet โหลดแบบขี้เกียจ — ต้องเลื่อนลงไปให้ถึงก่อน
    for i in range(3):
        page.mouse.wheel(0, 1400)
        page.wait_for_timeout(2_500)
    snap("2_เลื่อนลง")

    # สลับการเรียงเป็น "ความคิดเห็นทั้งหมด/ใหม่ที่สุด" — ค่าเริ่มต้นคือ
    # "เกี่ยวข้องมากที่สุด" ซึ่ง **ซ่อนคอมเมนต์ส่วนใหญ่ไว้** (เก็บได้ไม่ครบ)
    for label in ("เกี่ยวข้องมากที่สุด", "Most relevant", "จัดเรียงตาม"):
        try:
            el = page.get_by_text(label, exact=False)
            if el.count():
                el.first.click(timeout=4_000)
                page.wait_for_timeout(2_000)
                for choice in ("ความคิดเห็นทั้งหมด", "All comments", "ใหม่ที่สุด"):
                    opt = page.get_by_text(choice, exact=False)
                    if opt.count():
                        opt.first.click(timeout=4_000)
                        page.wait_for_timeout(3_500)
                        log(f"  สลับการเรียงเป็น: {choice}")
                        break
                break
        except Exception as error:
            log(f"  สลับการเรียงไม่ได้ ({label}): {type(error).__name__}")
    snap("3_เรียงใหม่")

    # กดดูคอมเมนต์เพิ่ม จนกว่าจะไม่มีปุ่ม (สูงสุด 5 ครั้งพอสำหรับการสำรวจ)
    more_re = re.compile(r"(ดูความคิดเห็นเพิ่มเติม|ดูความคิดเห็นอีก|ความคิดเห็นก่อนหน้า"
                         r"|View more comments|View \d+ more comment)")
    clicks = 0
    for _ in range(5):
        try:
            btn = page.get_by_text(more_re)
            if not btn.count():
                break
            btn.first.click(timeout=5_000)
            clicks += 1
            page.wait_for_timeout(3_000)
        except Exception:
            break
    log(f"  กด 'ดูความคิดเห็นเพิ่มเติม' ได้ {clicks} ครั้ง")
    snap("4_กดดูเพิ่ม")

    # ดึงคอมเมนต์จริงจาก DOM — นี่คือของที่จะเอาไปเก็บลงฐานข้อมูล
    articles = []
    try:
        articles = page.evaluate(_COMMENT_DOM_JS)
    except Exception as error:
        log(f"  อ่าน DOM ไม่ได้: {type(error).__name__}: {error}")
    (dump_dir / "articles.json").write_text(
        json.dumps(articles, ensure_ascii=False, indent=2), encoding="utf-8")
    elapsed = time.time() - started
    log(f"  บล็อก article: {len(articles)} · ใช้เวลาทั้งหมด {elapsed:.1f} วินาที")
    for a in articles[:8]:
        log(f"    [{a['chars']:>5} ตัวอักษร · รูป {a['imgs']}] "
            f"{a['label'][:36]:38} | {a['text'][:60]}")
    return {"url": url, "stages": stages, "more_clicks": clicks,
            "articles": articles, "seconds": round(elapsed, 1),
            "bodies": bodies}


def pick_group(argv_url: str | None) -> tuple[str, str]:
    """เลือกกลุ่มที่จะสำรวจ — ค่าเริ่มต้นคือกลุ่ม whitelist ที่คึกที่สุด

    ใช้กลุ่มคึกเพราะต้องการตัวอย่าง caption/รูป/คอมเมนต์เยอะพอจะวัดสัดส่วนได้
    """
    if argv_url:
        return argv_url, "(ระบุเอง)"
    state = mf.load_kw_state()
    items = [e for e in (state.get("whitelist") or {}).values() if e.get("url")]
    if not items:
        raise SystemExit("ไม่มีกลุ่มใน whitelist — ระบุเองด้วย --group <url>")
    items.sort(key=lambda e: -(e.get("avg") or 0))
    best = items[0]
    return best["url"], f'{best.get("name", "")} (เฉลี่ย {best.get("avg")})'


def analyse(bodies: list[str], label: str) -> dict:
    """นับสิ่งที่เจอในก้อน JSON ทั้งหมด — คืนตัวเลขล้วน ไม่ตีความ"""
    joined = "\n".join(bodies).replace("\\/", "/")
    post_ids = {m.group(2) for m in mf.POST_URL_RE.finditer(joined)}
    images = IMG_RE.findall(joined)
    expiries = []
    for url in images:
        m = OE_RE.search(url)
        if m:
            try:
                expiries.append(int(m.group(1), 16))
            except ValueError:
                pass
    now = time.time()
    view_keys = Counter(VIEWKEY_RE.findall(joined))
    return {
        "label": label,
        "bodies": len(bodies),
        "bytes": sum(len(b) for b in bodies),
        "stories": len(STORY_RE.findall(joined)),
        "post_urls": len(post_ids),
        "captions": len(MESSAGE_RE.findall(joined)),
        "creation_times": len(CREATION_RE.findall(joined)),
        "reactions": len(mf.REACTION_RE.findall(joined)),
        "string_numbers": Counter(k for k, _ in STR_NUM_RE.findall(joined)),
        "images": len(set(images)),
        "img_with_expiry": len(expiries),
        "expiry_hours": (sorted(round((e - now) / 3600, 1) for e in expiries)
                         if expiries else []),
        "comment_bodies": len(COMMENT_BODY_RE.findall(joined)),
        "comment_nodes": len(COMMENT_TYPENAME_RE.findall(joined)),
        "view_keys": dict(view_keys.most_common(6)),
    }


def report(res: dict) -> None:
    log(f"── ผล: {res['label']} "
        f"({res['bodies']} ก้อน · {res['bytes']/1024/1024:.1f} MB) ──")
    print(f"   story nodes        : {res['stories']:,}")
    print(f"   ลิงก์โพสต์ (ไม่ซ้ำ) : {res['post_urls']:,}")
    print(f"   caption (message)  : {res['captions']:,}")
    print(f"   creation_time      : {res['creation_times']:,}")
    print(f"   reaction_count     : {res['reactions']:,}")
    print(f"   รูป (URL ไม่ซ้ำ)    : {res['images']:,}  · มี oe= {res['img_with_expiry']:,}")
    if res["expiry_hours"]:
        hrs = res["expiry_hours"]
        print(f"   อายุ URL รูป       : สั้นสุด {hrs[0]} ชม. · ยาวสุด {hrs[-1]} ชม.")
    print(f"   คอมเมนต์ (body)    : {res['comment_bodies']:,} "
          f"· Comment node {res['comment_nodes']:,}")
    if res["string_numbers"]:
        print(f"   ⚠️ ตัวเลขมาเป็น string: {dict(res['string_numbers'])}")
    if res["view_keys"]:
        print(f"   คีย์ยอดวิวที่เจอ    : {res['view_keys']}")


def main() -> int:
    args = sys.argv[1:]
    bot_name = next((a for a in args if not a.startswith("--")), "Bot8")
    scrolls = 10
    group_url = None
    for i, a in enumerate(args):
        if a == "--scrolls" and i + 1 < len(args):
            scrolls = int(args[i + 1])
        if a == "--group" and i + 1 < len(args):
            group_url = args[i + 1]

    url, desc = pick_group(group_url)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dump_dir = OUT_DIR / stamp
    dump_dir.mkdir(parents=True, exist_ok=True)
    log(f"สำรวจกลุ่ม: {desc}")
    log(f"  {url}")
    log(f"บอท: {bot_name} · เลื่อน {scrolls} รอบ · ดัมพ์ลง {dump_dir}")

    farm = ProfileFarm(mf.DATA_DIR)
    entry = mf.find_bot(farm, bot_name)

    from playwright.sync_api import sync_playwright

    feed_bodies: list[str] = []
    post_bodies: list[str] = []
    permalink = ""
    expect_comments = 0          # จำนวนคอมเมนต์ที่ฟีดบอกไว้ (ไว้เทียบกับที่เก็บได้จริง)

    with sync_playwright() as pw:
        context = mf.launch_bot_browser(pw, farm, entry)
        try:
            page = context.pages[0] if context.pages else context.new_page()
            user_id = mf.ensure_logged_in(page, context)
            log(f"ล็อกอินอยู่ (user {user_id})")

            pending: list = []
            page.on("response", lambda r: pending.append(r)
                    if "/api/graphql" in r.url else None)

            def drain(into: list) -> None:
                for r in pending:
                    try:
                        into.append(r.text())
                    except Exception:
                        pass          # body ถูกทิ้งแล้ว — ข้ามตัวนั้น
                pending.clear()

            # ---------------------------------------------------- ส่วนที่ 1: ฟีด
            log("เปิดหน้ากลุ่ม…")
            page.goto(url, wait_until="domcontentloaded", timeout=90_000)
            page.wait_for_timeout(5_000)
            drain(feed_bodies)
            for i in range(1, scrolls + 1):
                page.keyboard.press("End")
                page.wait_for_timeout(3_000)
                drain(feed_bodies)
                if i % 5 == 0:
                    log(f"  เลื่อน {i}/{scrolls} รอบ — เก็บ body {len(feed_bodies)} ก้อน")
            html = page.content()

            # เลือกโพสต์ที่ "คอมเมนต์เยอะที่สุด" มาทดสอบ — ใบที่คอมเมนต์น้อย
            # ทดสอบการกดขยาย/การเรียงไม่ได้เลย (รอบแรกไปเจอโพสต์ต้อนรับสมาชิก
            # ที่ไม่มีคอมเมนต์เลย จึงไม่รู้ว่าเก็บคอมเมนต์ได้จริงไหม)
            # ใช้ harvest() ของโปรเจกต์ — โค้ดจับคู่ตัวเลขกับโพสต์ที่พิสูจน์แล้ว
            bucket: dict[str, dict] = {}
            for body in feed_bodies:
                try:
                    mf.harvest(body, bucket)
                except Exception:
                    pass
            mf.harvest(html, bucket)
            ranked = sorted(bucket.values(), key=lambda p: -p.get("comments", 0))
            if ranked and ranked[0].get("comments", 0) > 0:
                permalink = ranked[0]["url"]
                expect_comments = ranked[0]["comments"]
                log(f"เลือกโพสต์คอมเมนต์เยอะสุด: {expect_comments} คอมเมนต์ "
                    f"· ไลค์ {ranked[0].get('likes')} · จาก {len(bucket)} โพสต์")
                log("  5 อันดับคอมเมนต์: "
                    + ", ".join(str(p.get("comments", 0)) for p in ranked[:5]))
            elif ranked:
                permalink = ranked[0]["url"]
                log(f"⚠️ ทุกโพสต์คอมเมนต์ 0 จาก {len(bucket)} โพสต์ — "
                    "ทดสอบการเก็บคอมเมนต์ไม่ได้ในกลุ่มนี้")

            # ------------------------------------------- ส่วนที่ 2: เปิดโพสต์เดี่ยว
            if permalink:
                log(f"เจาะโพสต์เดี่ยว: {permalink}")
                pl = probe_permalink(page, permalink, dump_dir, drain)
                pl["expect_comments"] = expect_comments
                post_bodies = pl.pop("bodies")
                (dump_dir / "permalink_stages.json").write_text(
                    json.dumps(pl, ensure_ascii=False, indent=2), encoding="utf-8")
        finally:
            context.close()

    # ----------------------------------------------------------- บันทึก + สรุป
    for i, body in enumerate(feed_bodies):
        (dump_dir / f"feed_{i:03d}.json").write_text(body, encoding="utf-8")
    for i, body in enumerate(post_bodies):
        (dump_dir / f"post_{i:03d}.json").write_text(body, encoding="utf-8")
    (dump_dir / "page.html").write_text(html, encoding="utf-8")

    print()
    feed_res = analyse(feed_bodies, "ฟีดกลุ่ม (เลื่อนอย่างเดียว)")
    report(feed_res)
    post_res = None
    if post_bodies:
        print()
        post_res = analyse(post_bodies, "เปิดโพสต์เดี่ยว (permalink)")
        report(post_res)

    summary = {"at": stamp, "group": url, "desc": desc, "bot": bot_name,
               "scrolls": scrolls, "permalink": permalink,
               "feed": {k: (v if not isinstance(v, Counter) else dict(v))
                        for k, v in feed_res.items()},
               "post": ({k: (v if not isinstance(v, Counter) else dict(v))
                         for k, v in post_res.items()} if post_res else None)}
    (dump_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    # ------------------------------------------------------------ คำตอบ P1-P7
    print("\n" + "=" * 66)
    print("คำตอบที่ใช้ตัดสินใจ")
    print("=" * 66)
    posts = max(1, feed_res["post_urls"])
    cap_pct = feed_res["captions"] * 100 // posts
    time_pct = feed_res["creation_times"] * 100 // posts
    print(f"P1 caption ในฟีด      : {feed_res['captions']:,} ต่อ {posts:,} โพสต์ "
          f"(~{cap_pct}%) → " + ("✅ ดึงจากฟีดได้" if cap_pct >= 60
                                 else "❌ ต้องเปิดทีละโพสต์"))
    print(f"P2 เวลาโพสต์          : ~{time_pct}% → "
          + ("✅ ใช้ได้" if time_pct >= 60 else "⚠️ ต้องอ่านจากข้อความสัมพัทธ์แทน"))
    print(f"P3 ตัวเลขเป็น string   : "
          + (f"⚠️ เจอ {dict(feed_res['string_numbers'])} — regex เดิมพลาด"
             if feed_res["string_numbers"] else "✅ ไม่เจอ (regex เดิมพอ)"))
    print(f"P4 คีย์ยอดวิว          : "
          + (str(feed_res["view_keys"]) if feed_res["view_keys"]
             else "ไม่เจอเลย → โพสต์ในกลุ่มนี้ไม่มีวิดีโอ หรือ FB ไม่ส่งมา"))
    print(f"P5 รูป                : {feed_res['images']:,} URL · "
          + (f"อายุสั้นสุด {feed_res['expiry_hours'][0]} ชม. → ต้องโหลดภายในเวลานี้"
             if feed_res["expiry_hours"] else "ไม่มี oe= (อาจไม่หมดอายุ)"))
    print(f"P6 คอมเมนต์มากับฟีด    : {feed_res['comment_bodies']:,} ก้อน → "
          + ("✅ ได้คอมเมนต์ส่วนหนึ่งฟรี" if feed_res["comment_bodies"] > posts // 4
             else "❌ ไม่มี ต้องเปิดโพสต์"))
    if post_res:
        print(f"P7 เปิดโพสต์เดี่ยว     : คอมเมนต์ {post_res['comment_bodies']:,} ก้อน "
              f"· Comment node {post_res['comment_nodes']:,} → "
              + ("✅ ได้คอมเมนต์เต็ม" if post_res["comment_bodies"] > 3
                 else "⚠️ ได้น้อย ต้องกดขยายเพิ่ม"))
    print(f"\nดัมพ์ดิบเก็บไว้ที่: {dump_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
