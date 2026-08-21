"""ตัวเก็บข้อมูลโพสต์+คอมเมนต์ของกลุ่มที่ผ่านการคัดแล้ว

ออกแบบตามที่ผู้ใช้สั่ง 18 ส.ค. 2569:
  บอท 1 ตัว = 1 กลุ่มครบวงจร → "เลื่อนฟีดหาโพสต์ เสร็จแล้วเปิดโพสต์ สลับกัน"
  รันสองตัวขนานกัน (Bot8 / Bot9) คนละกลุ่ม — จองกลุ่มผ่านฐานข้อมูลกันชนกัน

ขั้นตอนต่อกลุ่ม:
  1. เลื่อนฟีดเก็บโพสต์ย้อนหลัง (caption · ยอด · เวลา · URL รูป) ← เร็ว งานเบา
  2. โหลดรูปโพสต์ลง Google Drive ← ไม่ใช้เบราว์เซอร์ ทำคู่ขนานได้
  3. เปิดเฉพาะโพสต์ที่ "มีคอมเมนต์ > 0" แล้วเก็บคอมเมนต์ทุกอัน ← ช้า
  4. สรุปเข้า Telegram

ทำไมไม่เปิดทุกโพสต์: วัดจากกลุ่มจริง 92 โพสต์ มีแค่ 5 โพสต์ที่คอมเมนต์ > 0
เปิดหมดทุกใบจะเสียเวลา 95% ไปกับโพสต์ที่ไม่มีอะไรให้เก็บ

รัน:  python fb_posts_collect.py Bot8 [--groups N] [--posts 1000] [--gid <id>]
"""
from __future__ import annotations

import random
import sqlite3
import sys
import time
import traceback
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import fb_mass_finder as mf
import fb_posts_comments as fc
import fb_posts_parse as pp
import fb_posts_store as store
import telegram_bot
from bot_profiles import ProfileFarm

HERE = Path(__file__).resolve().parent
LOG_FILE = mf.DATA_DIR / "logs" / "fb_posts_collect.log"

# ---------------------------------------------------------------- ค่าคุมจังหวะ
POSTS_TARGET = 1000          # โพสต์ย้อนหลังต่อกลุ่ม (ตามที่ผู้ใช้สั่ง)
MAX_SCROLLS = 260            # เพดานรอบเลื่อน — 1,000 โพสต์ใช้ ~200-220 รอบ
IDLE_LIMIT = 4               # เลื่อนแล้วไม่เพิ่มกี่รอบติดถึงถือว่าฟีดหมด
COMMENT_MIN = 1              # เปิดโพสต์ที่คอมเมนต์ตั้งแต่กี่อันขึ้นไป
PAUSE_BETWEEN_POSTS = (3, 7)      # พักสุ่มระหว่างเปิดโพสต์ (วินาที)
LONG_PAUSE_EVERY = 15            # เปิดครบกี่โพสต์ให้พักยาว
LONG_PAUSE = (45, 90)            # พักยาวกี่วินาที
IMAGE_WORKERS = 4                # โหลดรูปพร้อมกันกี่เส้น
IMAGE_TIMEOUT = 30


BOT_TAG = "?"          # ตั้งค่าใน main() — สองบอทเขียนล็อกไฟล์เดียวกัน


def log(message: str) -> None:
    """เขียนล็อก — ต้องมีชื่อบอทกำกับทุกบรรทัด

    Bot8 กับ Bot9 เขียนลงไฟล์เดียวกัน ถ้าไม่ติดป้ายชื่อจะแยกไม่ออกว่าบรรทัดไหน
    ของใคร (เกิดจริง 21 ส.ค.: Bot8 ตายแล้วไล่ล็อกย้อนหลังไม่ได้เลยว่าตายตอนไหน)
    """
    line = f"{datetime.now():%H:%M:%S} [{BOT_TAG}] {message}"
    print(line, flush=True)
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


def say(text: str) -> None:
    """รายงานเข้า Telegram — ใช้ช่องเดียวกับบอทหลัก (ส่งอย่างเดียว ไม่รับคำสั่ง)

    ตัวเก็บเป็นคนละโปรเซสกับ fb_mass_bot จึง **ห้ามเรียก getUpdates**
    (สองตัวอ่านคิวเดียวกัน = 409 ข้อความหายสลับกัน) — ส่งออกอย่างเดียวปลอดภัย
    """
    try:
        config = mf.load_config()
        token, chat = mf.telegram_target(config)
        telegram_bot.send_message(token, chat, text)
    except Exception as error:
        log(f"ส่ง Telegram ไม่สำเร็จ: {type(error).__name__}: {error}")


def fetch_image(url: str) -> bytes:
    """โหลดรูปตรงจาก CDN — ไม่ต้องใช้เบราว์เซอร์ ไม่ต้องมีคุกกี้

    พิสูจน์แล้ว 18 ส.ค.: ใส่ Referer ของ facebook.com ก็โหลดได้ 88 KB ปกติ
    """
    request = urllib.request.Request(url, headers={
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"),
        "Referer": "https://www.facebook.com/",
    })
    with urllib.request.urlopen(request, timeout=IMAGE_TIMEOUT) as resp:
        return resp.read()


def download_images(conn, gid: str, group_name: str, log=log) -> int:
    """โหลดรูปที่ยังค้างของกลุ่มนี้ทั้งหมด — คืนจำนวนที่เก็บสำเร็จ"""
    ok, why = store.disk_ok()
    if not ok:
        log(f"  ⛔ ไม่โหลดรูป: {why}")
        return 0
    ready, why = store.media_ready()
    if not ready:
        log(f"  ⛔ ไม่โหลดรูป: {why}")
        return 0

    jobs = conn.execute("""
        SELECT i.post_id AS owner, i.idx, i.src_url FROM post_image i
        JOIN fb_post p ON p.post_id = i.post_id
        WHERE p.gid=? AND i.state='pending' AND i.src_url != ''
    """, (gid,)).fetchall()
    jobs += conn.execute("""
        SELECT ci.comment_id AS owner, ci.idx, ci.src_url FROM comment_image ci
        JOIN fb_comment c ON c.comment_id = ci.comment_id
        JOIN fb_post p ON p.post_id = c.post_id
        WHERE p.gid=? AND ci.state='pending' AND ci.src_url != ''
    """, (gid,)).fetchall()
    if not jobs:
        return 0

    log(f"  โหลดรูป {len(jobs)} ไฟล์…")
    done = 0
    with ThreadPoolExecutor(max_workers=IMAGE_WORKERS) as pool:
        futures = {pool.submit(fetch_image, row["src_url"]): row for row in jobs}
        for future, row in ((f, futures[f]) for f in futures):
            table = "post_image" if "_" not in row["owner"] else "comment_image"
            try:
                data = future.result()
                if not data or len(data) < 500:
                    raise ValueError(f"ไฟล์เล็กผิดปกติ ({len(data)} bytes)")
                store.save_image(conn, table, row["owner"], row["idx"],
                                 data, gid, group_name,
                                 "posts" if table == "post_image" else "comments")
                done += 1
            except Exception as error:
                store.mark_image_failed(conn, table, row["owner"], row["idx"],
                                        f"{type(error).__name__}: {error}")
            if done and done % 50 == 0:
                conn.commit()
                ok, why = store.disk_ok()
                if not ok:
                    log(f"  ⛔ หยุดโหลดรูปกลางคัน: {why}")
                    break
    conn.commit()
    failed = len(jobs) - done
    log(f"  เก็บรูปสำเร็จ {done} ไฟล์" + (f" · ล้ม {failed}" if failed else ""))
    return done + download_avatars(conn, gid, group_name, log=log)


def download_avatars(conn, gid: str, group_name: str, log=log) -> int:
    """เก็บรูปโปรไฟล์คนโพสต์/คนคอมเมนต์ลง Drive

    ผู้ใช้สั่งให้เก็บ "ชื่อคน, รูป, เนื้อหาทั้งหมด" ของคนคอมเมนต์
    ถ้าเก็บแค่ URL ของ Facebook รูปจะหายใน ~103 ชม. (วัดอายุ URL จริงแล้ว)
    คนเดียวกันคอมเมนต์หลายที่ = ไฟล์เดียวกัน (ตั้งชื่อไฟล์ตาม sha256 จึงไม่ซ้ำ)
    """
    rows = conn.execute("""
        SELECT 'fb_post' AS t, post_id AS id, avatar FROM fb_post
        WHERE gid=? AND avatar!='' AND avatar_path=''
        UNION ALL
        SELECT 'fb_comment', c.comment_id, c.avatar FROM fb_comment c
        JOIN fb_post p ON p.post_id=c.post_id
        WHERE p.gid=? AND c.avatar!='' AND c.avatar_path=''
    """, (gid, gid)).fetchall()
    if not rows:
        return 0

    # โหลดรูปเดียวกันครั้งเดียวพอ แล้วแจกให้ทุกแถวที่ใช้ URL นั้น
    by_url: dict[str, list] = {}
    for row in rows:
        by_url.setdefault(row["avatar"], []).append(row)
    log(f"  โหลดรูปโปรไฟล์ {len(by_url)} รูป (ใช้ซ้ำ {len(rows)} จุด)…")

    done = 0
    with ThreadPoolExecutor(max_workers=IMAGE_WORKERS) as pool:
        futures = {pool.submit(fetch_image, url): url for url in by_url}
        for future in futures:
            url = futures[future]
            try:
                data = future.result()
                if not data or len(data) < 200:
                    raise ValueError("ไฟล์เล็กผิดปกติ")
                import hashlib
                sha = hashlib.sha256(data).hexdigest()
                folder = store.group_dir(gid, group_name) / "avatars" / sha[:2]
                folder.mkdir(parents=True, exist_ok=True)
                target = folder / f"{sha}.jpg"
                if not target.exists():
                    tmp = target.with_suffix(".tmp")
                    tmp.write_bytes(data)
                    tmp.replace(target)
                rel = str(target.relative_to(store.MEDIA_ROOT)).replace("\\", "/")
                for row in by_url[url]:
                    key = "post_id" if row["t"] == "fb_post" else "comment_id"
                    conn.execute(f"UPDATE {row['t']} SET avatar_path=? "
                                 f"WHERE {key}=?", (rel, row["id"]))
                    done += 1
            except Exception as error:
                log(f"    รูปโปรไฟล์โหลดไม่ได้: {type(error).__name__}")
    conn.commit()
    log(f"  เก็บรูปโปรไฟล์ {done} จุด")
    return done


# ปิดเสียงระดับหน้าเว็บ — ผู้ใช้สั่ง 21 ส.ค. 2569 ให้เงียบเป็นค่าเริ่มต้น
#
# ทำไมไม่พอที่จะใส่ --mute-audio ตอนเปิด Chrome อย่างเดียว:
#   flag นั้นปิดเสียง "ลำโพง" ของหน้าต่างก็จริง แต่คลิปยังเล่นอยู่เบื้องหลัง
#   กินซีพียูและแบนด์วิดท์ระหว่างเลื่อนฟีดหาโพสต์นับพันใบ และถ้า Chrome
#   ถูกเปิดค้างจากโปรไฟล์เดิม flag ตอน launch จะไม่มีผลกับหน้าต่างนั้นเลย
# ตัวนี้จึงหยุดคลิปที่ตัวหน้าเว็บ และดักคลิปที่โหลดเข้ามาใหม่ตอนเลื่อนด้วย
MUTE_JS = """
(() => {
  const hush = (m) => {
    try { m.muted = true; m.volume = 0; m.autoplay = false;
          if (!m.paused) m.pause(); } catch (e) {}
  };
  const sweep = (root) => {
    try { if (root && root.querySelectorAll)
            root.querySelectorAll('video,audio').forEach(hush); } catch (e) {}
  };
  sweep(document);                       // คลิปที่มีอยู่แล้วบนหน้า
  if (window.__hushInstalled) return;    // ติดตั้งด่านถาวรครั้งเดียวพอ
  window.__hushInstalled = true;
  // ด่านที่แน่นอนที่สุด: ไม่ว่าใครสั่งเล่น ต้องเงียบก่อนเล่นเสมอ
  // ตัวนี้ติดตั้งได้ตั้งแต่หน้ายังว่าง จึงต้องมาก่อนตัวที่ต้องใช้ DOM
  const play = HTMLMediaElement.prototype.play;
  HTMLMediaElement.prototype.play = function (...a) {
    this.muted = true; this.volume = 0;
    return play.apply(this, a);
  };
  // ดักคลิปที่โหลดเข้ามาใหม่ตอนเลื่อนฟีด
  // ⚠️ ต้อง observe `document` ไม่ใช่ `document.documentElement` — ตอนสคริปต์นี้
  // ถูกฝังไว้ล่วงหน้า (add_init_script) หน้ายังว่าง documentElement เป็น null
  // แล้ว observe จะโยน error ทำให้ทั้งก้อนตายตั้งแต่ยังไม่ทันติดตั้งอะไร
  try {
    new MutationObserver((list) => {
      for (const rec of list) {
        for (const node of rec.addedNodes) {
          if (node.tagName === 'VIDEO' || node.tagName === 'AUDIO') hush(node);
          else sweep(node);
        }
      }
    }).observe(document, {childList: true, subtree: true});
  } catch (e) {}
})();
"""


def hush_page(page, log=log) -> None:
    """สั่งปิดเสียงคลิปบนหน้าที่เปิดอยู่ตอนนี้ (เรียกซ้ำได้ ไม่มีผลข้างเคียง)"""
    try:
        page.evaluate(MUTE_JS)
    except Exception as error:
        log(f"  ปิดเสียงไม่สำเร็จ: {type(error).__name__}")


def collect_feed(page, group: dict, target: int, log=log) -> list[dict]:
    """เลื่อนฟีดเก็บโพสต์ย้อนหลัง — คืนรายการโพสต์ (ใหม่→เก่า)"""
    parser = pp.FeedParser()
    pending: list = []

    def on_response(response):
        if "/api/graphql" in response.url:
            pending.append(response)

    def drain() -> None:
        for response in pending:
            try:
                parser.add(response.text())
            except Exception:
                pass
        pending.clear()

    page.on("response", on_response)
    try:
        page.goto(group["url"], wait_until="domcontentloaded", timeout=90_000)
        page.wait_for_timeout(5_000)
        hush_page(page, log=log)          # ปิดเสียงคลิปในฟีดก่อนเริ่มเลื่อน
        if guard_blocked(page):
            raise mf.MassFinderError("Facebook ขอยืนยันตัวตน (checkpoint)")
        drain()
        idle = 0
        for round_number in range(1, MAX_SCROLLS + 1):
            if len(parser.posts) >= target:
                break
            before = len(parser.posts)
            page.keyboard.press("End")
            page.wait_for_timeout(3_000)
            drain()
            if round_number % 20 == 0:
                hush_page(page, log=log)   # กวาดคลิปที่เพิ่งโหลดเข้ามาซ้ำ
                log(f"  เลื่อน {round_number} รอบ — {len(parser.posts)} โพสต์")
            idle = idle + 1 if len(parser.posts) == before else 0
            if idle >= IDLE_LIMIT:
                log(f"  ฟีดหมดที่ {len(parser.posts)} โพสต์")
                break
    finally:
        page.remove_listener("response", on_response)
    return parser.as_legacy()


def guard_blocked(page) -> bool:
    """Facebook เริ่มกันแล้วหรือยัง — เจอเมื่อไรต้องหยุด ไม่ใช่ดันต่อ"""
    url = (page.url or "").lower()
    return "checkpoint" in url or "login" in url or "/suspended" in url


def collect_group(page, conn, group: dict, bot: str, target: int,
                  log=log) -> dict:
    """เก็บครบวงจรหนึ่งกลุ่ม — คืนสรุปผล"""
    gid, name = group["gid"], group.get("name") or group["gid"]
    run_id = store.start_run(conn, gid, bot, "feed")
    log(f"▶ เริ่มกลุ่ม: {name}")

    # ขั้นเลื่อนฟีด — ข้ามได้ถ้ารอบก่อนเลื่อนจนสุดไปแล้ว
    #
    # ทำไมต้องข้าม: บอทตายกลางทางบ่อย พอกลับมาทำต่อ ขั้นเลื่อนฟีดจะวิ่งใหม่
    # ทั้งพันโพสต์ทั้งที่โพสต์อยู่ในคลังครบแล้ว = เสียเวลาเปล่า 30-40 นาที/ครั้ง
    # (วัดจริง 21 ส.ค.: Bot8 กลับมาทำต่อแล้วเลื่อนซ้ำ 220 รอบก่อนไปต่อที่คอมเมนต์)
    have = conn.execute("SELECT COUNT(*) FROM fb_post WHERE gid=?",
                        (gid,)).fetchone()[0]
    if store.feed_done(conn, gid) and have:
        log(f"  ข้ามการเลื่อนฟีด — รอบก่อนเลื่อนจนสุดแล้ว มีโพสต์ในคลัง {have} ใบ")
        posts, new_posts = [], 0
    else:
        posts = collect_feed(page, group, target, log=log)
        if not posts:
            store.end_run(conn, run_id, "failed", note="ไม่ได้โพสต์เลย")
            raise mf.MassFinderError("อ่านโพสต์ไม่ได้ (อาจยังไม่ได้เป็นสมาชิก)")
        new_posts = store.save_posts(conn, gid, posts)
        store.mark_feed_done(conn, gid)
        log(f"  เก็บโพสต์ {len(posts)} (ใหม่ {new_posts})")

    images = download_images(conn, gid, name, log=log)

    # เปิดเฉพาะโพสต์ที่มีคอมเมนต์จริง เรียงจากคอมเมนต์เยอะไปน้อย
    todo = conn.execute("""
        SELECT post_id, url, comments FROM fb_post
        WHERE gid=? AND comments_state='pending' AND COALESCE(comments,0) >= ?
        ORDER BY comments DESC""", (gid, COMMENT_MIN)).fetchall()
    skipped = conn.execute("""
        UPDATE fb_post SET comments_state='skipped'
        WHERE gid=? AND comments_state='pending' AND COALESCE(comments,0) < ?
    """, (gid, COMMENT_MIN)).rowcount
    conn.commit()
    log(f"  ต้องเปิดอ่านคอมเมนต์ {len(todo)} โพสต์ "
        f"(ข้ามโพสต์ไม่มีคอมเมนต์ {skipped})")

    total_comments = 0
    opened = 0
    for row in todo:
        if guard_blocked(page):
            log("  ⛔ Facebook เริ่มกัน — หยุดกลุ่มนี้")
            store.end_run(conn, run_id, "blocked", posts_seen=len(posts),
                          posts_new=new_posts, comments_new=total_comments,
                          images_new=images, note="checkpoint")
            raise mf.MassFinderError("Facebook ขอยืนยันตัวตน — หยุดเก็บ")
        try:
            result = fc.collect_comments(page, row["url"], log=log,
                                         expect=row["comments"] or 0)
            total_comments += store.save_comments(conn, row["post_id"], result,
                                                  pp.is_spam, pp.spam_score)
        except Exception:
            conn.execute("""UPDATE fb_post SET comments_state='failed',
                            comments_note=? WHERE post_id=?""",
                         (traceback.format_exc()[-180:], row["post_id"]))
            conn.commit()
            log(f"  เก็บคอมเมนต์ล้ม: {row['post_id']}")
        opened += 1
        if opened % 20 == 0:
            store.renew_lease(conn, gid, bot)     # กันบอทอื่นแย่งกลุ่มกลางทาง
        if opened % LONG_PAUSE_EVERY == 0:
            nap = random.uniform(*LONG_PAUSE)
            log(f"  พักยาว {nap:.0f} วิ (เปิดไปแล้ว {opened}/{len(todo)} โพสต์)")
            time.sleep(nap)
        else:
            time.sleep(random.uniform(*PAUSE_BETWEEN_POSTS))

    images += download_images(conn, gid, name, log=log)   # รูปในคอมเมนต์
    summary = store.group_summary(conn, gid)
    store.end_run(conn, run_id, "done", posts_seen=len(posts),
                  posts_new=new_posts, comments_new=total_comments,
                  images_new=images)
    return {**summary, "posts_new": new_posts, "comments_new": total_comments,
            "images": images, "opened": opened}


def db_retry(what, *a, tries: int = 5):
    """เรียกงานฐานข้อมูลแบบทนล็อก — คืนผลลัพธ์ หรือโยนต่อถ้าไม่ไหวจริง

    ทำไมต้องมี: claim_group/finish_group อยู่นอก try ของลูปหลัก ถ้าเจอ
    "database is locked" ตอนสองบอทเขียนพร้อมกัน โปรเซสจะตายเงียบทั้งตัว
    ทั้งที่เป็นแค่การรอคิวเขียนไม่กี่วินาที (เกิดจริง 20 ส.ค. เวลา 03:06)
    """
    for attempt in range(tries):
        try:
            return what(*a)
        except sqlite3.OperationalError as error:
            if "locked" not in str(error).lower() or attempt == tries - 1:
                raise
            nap = 5 * (attempt + 1)
            log(f"  ฐานข้อมูลถูกล็อก — รอ {nap} วิแล้วลองใหม่ ({attempt + 1}/{tries})")
            time.sleep(nap)


def main() -> int:
    global BOT_TAG
    args = sys.argv[1:]
    bot = next((a for a in args if not a.startswith("--")), "Bot8")
    BOT_TAG = bot
    groups_limit = 1
    target = POSTS_TARGET
    only_gid = ""
    for i, a in enumerate(args):
        if a == "--groups" and i + 1 < len(args):
            groups_limit = int(args[i + 1])
        if a == "--posts" and i + 1 < len(args):
            target = int(args[i + 1])
        if a == "--gid" and i + 1 < len(args):
            only_gid = args[i + 1]

    conn = store.connect()
    stale = store.close_stale_runs(conn, bot)
    if stale:
        log(f"ปิดรายการรันค้างจากรอบก่อน {stale} รายการ (รอบที่แล้วบอทตายกลางทาง)")
    added = store.import_whitelist(conn)
    if added:
        log(f"ดึงกลุ่มจาก whitelist เข้าคิวเก็บ {added} กลุ่ม")

    ok, why = store.disk_ok()
    if not ok:
        say(f"⛔ ตัวเก็บข้อมูลไม่เริ่ม: {why}")
        log(f"⛔ {why}")
        return 1

    farm = ProfileFarm(mf.DATA_DIR)
    entry = mf.find_bot(farm, bot)
    from playwright.sync_api import sync_playwright

    done_groups = 0
    with sync_playwright() as pw:
        context = mf.launch_bot_browser(pw, farm, entry)
        try:
            # ปิดเสียงเป็นค่าเริ่มต้นทุกหน้าที่เปิดจากนี้ไป — ผู้ใช้สั่ง 21 ส.ค.
            # ต้องใส่ระดับ context ไม่ใช่เรียกใน collect_feed อย่างเดียว เพราะ
            # ขั้นเปิดโพสต์อ่านคอมเมนต์ก็เจอคลิปเล่นเอง และตอนบอททำงานต่อ
            # ขั้นเลื่อนฟีดจะถูกข้าม = ไม่มีใครสั่งปิดเสียงเลยสักครั้ง
            context.add_init_script(MUTE_JS)
            page = context.pages[0] if context.pages else context.new_page()
            hush_page(page, log=log)      # หน้าที่เปิดอยู่ก่อนแล้วต้องสั่งตรง
            mf.ensure_logged_in(page, context)
            log(f"{bot} พร้อมทำงาน")

            while done_groups < groups_limit:
                if only_gid:
                    row = conn.execute(
                        "SELECT gid, name, url, members FROM fb_group WHERE gid=?",
                        (only_gid,)).fetchone()
                    group = dict(row) if row else None
                    only_gid = ""
                else:
                    group = db_retry(store.claim_group, conn, bot)
                if group is None:
                    log("ไม่มีกลุ่มเหลือให้เก็บแล้ว")
                    break
                started = time.time()
                try:
                    result = collect_group(page, conn, group, bot, target, log=log)
                    db_retry(store.finish_group, conn, group["gid"], "done")
                    mins = (time.time() - started) / 60
                    log(f"✅ จบกลุ่ม {group.get('name')} ใน {mins:.1f} นาที")
                    say("\n".join([
                        f"📦 <b>เก็บข้อมูลเสร็จ: {group.get('name', '')[:45]}</b>",
                        f"โพสต์ {result['posts']:,} (แมส {result['mass']:,}) · "
                        f"คอมเมนต์ {result['comments']:,} · รูป {result['images']:,}",
                        f"เปิดอ่าน {result['opened']} โพสต์ · "
                        f"รูปรวม {result['image_mb']:.0f} MB · ใช้เวลา {mins:.0f} นาที",
                    ]))
                except Exception as error:
                    log(f"❌ กลุ่ม {group.get('name')}: {error}\n"
                        f"{traceback.format_exc()}")
                    db_retry(store.finish_group, conn, group["gid"], "failed",
                             str(error))
                    say(f"⚠️ เก็บกลุ่ม {group.get('name', '')[:40]} ไม่สำเร็จ: "
                        f"{str(error)[:120]}")
                    if "checkpoint" in str(error).lower() or "ยืนยันตัวตน" in str(error):
                        say(f"⛔ {bot} โดน Facebook กัน — หยุดตัวเก็บ")
                        break
                done_groups += 1
        finally:
            context.close()
    log(f"จบรอบ — ทำไป {done_groups} กลุ่ม")
    return 0


def guarded_main() -> int:
    """ห่อ main() ไว้ให้การตายทุกแบบทิ้งหลักฐานไว้ในล็อกของโปรเจกต์

    เดิมข้อผิดพลาดที่หลุดออกนอกลูปจะพิมพ์ traceback ลง stderr อย่างเดียว
    ซึ่งวิ่งเข้าหน้าต่างที่สั่งรัน แล้วหายไปพร้อมหน้าต่างนั้น — ผลคือ 21 ส.ค.
    Bot8 ตายโดยไม่มีร่องรอยเหลือในไฟล์ล็อกเลยแม้แต่บรรทัดเดียว
    """
    try:
        return main()
    except KeyboardInterrupt:
        log("หยุดด้วยมือ (Ctrl-C)")
        return 130
    except BaseException as error:
        log(f"💥 ตัวเก็บตายกลางทาง: {type(error).__name__}: {error}\n"
            f"{traceback.format_exc()}")
        try:
            say(f"💥 <b>{BOT_TAG} ตายกลางทาง</b>\n"
                f"{type(error).__name__}: {str(error)[:200]}")
        except Exception:
            pass
        return 1


if __name__ == "__main__":
    raise SystemExit(guarded_main())
