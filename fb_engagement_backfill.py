"""ตามเก็บยอดไลก์/คอมเมนต์/แชร์ของโพสต์ที่ตัวเก็บประจำยังไม่เคยแตะ

เจ้าของสั่ง 22 ก.ย. 2569 — *"บล็อกการเก็บข้อมูลของ bot8 ทุก 6 ชั่วโมงก่อน
ชั่วคราวเพื่อทำงานนี้ พอทำเสร็จเปิดกลับเหมือนเดิม ให้ตามเก็บ ยอดไลค์ คอมเมนต์
แชร์ของโพสต์ที่เหลือ ค่อยๆ ตามเก็บ ทุก 6 โพสต์ให้เว้นระยะเวลา 1-5 นาทีแบบสุ่ม"*

## ทำไมต้องมีไฟล์นี้ ทั้งที่มีตัวเก็บประจำอยู่แล้ว

ตัวเก็บประจำ (`fb_engagement.py`) ทำงานทุก 6 ชั่วโมงและเก็บได้ดี **แต่เก็บ
ไม่ครบ** วัดเมื่อ 22 ก.ย. 2569

    ลิงก์โพสต์จากใบงานทั้งหมด   461
      ตามยอดไว้แล้ว             290
      ยังไม่เคยตามเลย           171   ← ไฟล์นี้มาเก็บส่วนนี้

    kamolchanok-lill    ตามแล้ว   0 · ยังไม่ตาม 137   ไม่เคยถูกเก็บเลยสักครั้ง
    kp-oo               ตามแล้ว  84 · ยังไม่ตาม  34   เงียบตั้งแต่ 13 ก.ย.
    khao-fang-nichapa   ตามแล้ว 195 · ยังไม่ตาม   0
    preaw-buchakorn     ตามแล้ว  11 · ยังไม่ตาม   0

**ไม่ได้เขียนตัวขูดหน้าเว็บใหม่** — ใช้ `fb_engagement.read_post()` ตัวเดิม
และเขียนลงตาราง `my_post` เดิม ข้อมูลจึงไปรวมกองเดียวกัน ไม่แตกเป็นสองชุด
ที่จะเพี้ยนจากกันทีหลัง

## จังหวะที่เจ้าของกำหนด

ตัวเก็บประจำพักระหว่าง **ใบงาน** (`BETWEEN_POSTS` 1–5 นาที) ส่วนรอบนี้เจ้าของ
สั่งให้พักทุก **6 โพสต์** ซึ่งถี่กว่า เพราะรอบนี้ไล่เก็บรวดเดียว 171 ใบ
ไม่ได้กระจายทั้งวันเหมือนรอบประจำ

## หยุดตัวเก็บประจำยังไง และเปิดคืนแน่ไหม

หยุดด้วยสวิตช์ `data/bots_paused.txt` ซึ่งเป็นทางเดียวกับที่หน้าเว็บใช้ —
**ไม่ฆ่าโปรเซส ไม่แก้โค้ด** ตัวเก็บประจำอ่านสวิตช์นี้ทุกต้นรอบแล้วนอนรอเอง

**เปิดคืนถูกวางไว้ใน `finally`** จึงคืนแม้โปรแกรมถูกกด Ctrl+C หรือพังกลางทาง
และถ้าตอนเริ่มพบว่ามีคนอื่นหยุดบอทไว้ก่อนแล้ว จะ**ไม่ไปแตะสวิตช์เลย**
เพราะการเปิดคืนจะกลายเป็นการปลดล็อกของคนอื่นโดยไม่ได้ตั้งใจ

รัน:
    python fb_engagement_backfill.py            เก็บจริง
    python fb_engagement_backfill.py --dry-run  ดูว่าจะเก็บอะไรบ้าง ไม่เปิดเบราว์เซอร์
    python fb_engagement_backfill.py --limit 12 ลองสั้นๆ ก่อน
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from datetime import datetime
from pathlib import Path

import fb_engagement as eng
import studio_shared as shared

HERE = Path(__file__).resolve().parent
JOBS_DIR = shared.DATA_DIR / "facebook-post-state" / "accounts"
PAUSE_FILE = shared.DATA_DIR / "bots_paused.txt"
STATE_FILE = shared.DATA_DIR / "fb_engagement_backfill.json"

# เจ้าของสั่ง 22 ก.ย. 2569 — พักทุก 6 โพสต์ ครั้งละ 1–5 นาทีแบบสุ่ม
POSTS_PER_REST = 6
REST_SECONDS = (60.0, 300.0)

# ข้อความที่เขียนลงสวิตช์ — ต้องอ่านแล้วรู้ว่าใครหยุดและทำไม
PAUSE_REASON = "ตามเก็บยอดโพสต์ที่ตกค้าง (fb_engagement_backfill.py)"


def log(message: str) -> None:
    stamp = datetime.now().strftime("%H:%M:%S")
    line = f"{stamp} {message}"
    print(line, flush=True)
    try:
        eng.log(f"[backfill] {message}")
    except Exception:
        pass


# ----------------------------------------------------------------- หาโพสต์ที่ตกค้าง

def _display_name(folder: str) -> str:
    """แปลงชื่อโฟลเดอร์เป็นชื่อบัญชีที่ใช้จริงในฐานข้อมูล

    ตาราง `my_post` เก็บชื่อแบบ "Khao Fang Nichapa" ส่วนโฟลเดอร์เป็น
    "khao-fang-nichapa" **ถ้าเขียนชื่อโฟลเดอร์ลงไปตรงๆ จะได้บัญชีซ้ำสองชื่อ
    ในตารางเดียวกัน** แล้วตัวนับทุกตัวที่จัดกลุ่มตามบัญชีจะเพี้ยน
    """
    for name in shared.known_accounts():
        if shared.account_dir(name).name == folder:
            return name
    return folder


def posts_from_jobs() -> list[dict]:
    """โพสต์ที่ลงกลุ่มสำเร็จจริงทุกใบงาน — อ่านจาก fb_jobs.json ของทุกบัญชี

    **นับเฉพาะ `posted is True`** ไม่ใช่ดูว่ามีลิงก์ เพราะบางรายการมีลิงก์
    แต่ลงไม่สำเร็จ (ช่อง error) การนับผิดตรงนี้จะทำให้ไปเปิดลิงก์ที่ไม่มีโพสต์
    """
    rows: dict[str, dict] = {}
    for path in sorted(JOBS_DIR.glob("*/fb_jobs.json")):
        try:
            jobs = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            log(f"⚠️ อ่าน {path} ไม่ได้: {exc}")
            continue
        for job in jobs:
            if not isinstance(job, dict):
                continue
            for res in (job.get("results") or []):
                if not isinstance(res, dict) or res.get("posted") is not True:
                    continue
                url = str(res.get("link") or "").strip()
                if not url or url in rows:
                    continue
                rows[url] = {
                    "post_url": url,
                    "group_id": str(res.get("group_id") or ""),
                    "group_name": str(res.get("group_name") or res.get("group_id") or ""),
                    "account": _display_name(path.parent.name),
                    "job_id": str(job.get("id") or ""),
                    "caption": str(job.get("caption") or ""),
                }
    return list(rows.values())


def already_tracked() -> set[str]:
    conn = eng.open_db()
    try:
        return {row[0] for row in conn.execute("SELECT DISTINCT post_url FROM my_post")}
    finally:
        conn.close()


def pending_posts(limit: int = 0) -> list[dict]:
    have = already_tracked()
    left = [p for p in posts_from_jobs() if p["post_url"] not in have]
    # เก่าก่อน — ใบที่ลงไว้นานแล้วมีโอกาสถูกลบมากกว่า เก็บก่อนจะได้รู้เร็ว
    left.sort(key=lambda p: (p["account"], p["job_id"]))
    return left[:limit] if limit else left


# ----------------------------------------------------------------- สวิตช์หยุดบอท

def pause_regular_collector() -> bool:
    """คืน True ถ้า "เราเป็นคนหยุด" เท่านั้น — คนอื่นหยุดไว้อยู่แล้วคืน False

    **สำคัญ** ถ้าคนอื่นหยุดไว้ก่อน เราห้ามเขียนทับและห้ามเปิดคืนตอนจบ
    ไม่งั้นจะไปปลดของเขาโดยที่เขาไม่รู้
    """
    existing = ""
    try:
        existing = PAUSE_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        existing = ""
    if existing:
        log(f"ℹ️ บอทถูกหยุดไว้อยู่แล้วโดย: {existing[:90]}")
        log("   จะไม่แตะสวิตช์ และจะไม่เปิดคืนตอนจบ")
        return False
    PAUSE_FILE.parent.mkdir(parents=True, exist_ok=True)
    PAUSE_FILE.write_text(PAUSE_REASON, encoding="utf-8")
    log(f"⏸ หยุดรอบเก็บประจำของ Bot8 ไว้ชั่วคราวแล้ว → {PAUSE_FILE.name}")
    return True


def resume_regular_collector(ours: bool) -> None:
    if not ours:
        log("ℹ️ ไม่ได้เปิดคืน เพราะไม่ใช่คนที่หยุดไว้")
        return
    try:
        now = PAUSE_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        now = ""
    if now and now != PAUSE_REASON:
        # ระหว่างที่เราทำงาน มีคนมาเขียนทับด้วยเหตุผลของเขา — ห้ามลบของเขา
        log(f"⚠️ สวิตช์ถูกเปลี่ยนเป็น: {now[:90]} — ไม่ลบให้ ปล่อยไว้ตามนั้น")
        return
    try:
        PAUSE_FILE.unlink(missing_ok=True)
        log("▶️ เปิดรอบเก็บประจำของ Bot8 กลับเหมือนเดิมแล้ว")
    except OSError as exc:
        log(f"❌ เปิดคืนไม่สำเร็จ: {exc} — ต้องลบไฟล์ {PAUSE_FILE} ด้วยมือ")


def pause_state() -> str:
    try:
        return PAUSE_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


# ----------------------------------------------------------------- เก็บจริง

def save_progress(done: int, total: int, ok: int, gone: int, failed: int) -> None:
    try:
        STATE_FILE.write_text(json.dumps({
            "updated_at": datetime.now().isoformat(timespec="seconds"),
            "done": done, "total": total,
            "ok": ok, "gone": gone, "failed": failed,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


def collect(posts: list[dict]) -> dict:
    """เปิดทีละโพสต์ อ่านยอด เขียนลงตารางเดิม — พักทุก 6 โพสต์"""
    from playwright.sync_api import sync_playwright   # noqa: PLC0415

    import bot_profiles                               # noqa: PLC0415
    import fb_mass_finder as mf                       # noqa: PLC0415

    # **ส่ง DATA_DIR ไม่ใช่ DATA_DIR/bot_profiles** — ProfileFarm ต่อ "bot_profiles"
    # ให้เองข้างใน ส่งพาธที่ต่อไว้แล้วจะได้ data/bot_profiles/bot_profiles ซึ่งว่าง
    # แล้วฟ้องว่า "ไม่พบโปรไฟล์บอท Bot8" ทั้งที่มีอยู่ (เจอจริงตอนรันรอบแรก)
    farm = bot_profiles.ProfileFarm(shared.DATA_DIR)
    entry = mf.find_bot(farm, eng.COLLECTOR_PROFILE)

    conn = eng.open_db()
    ok = gone = failed = 0
    started = time.monotonic()
    try:
        with sync_playwright() as playwright:
            browser = mf.launch_bot_browser(playwright, farm, entry)
            page = browser.new_page() if hasattr(browser, "new_page") else browser.pages[0]
            try:
                for index, post in enumerate(posts, 1):
                    label = f"{post['group_name'][:28]} ({post['account']})"
                    log(f"[{index}/{len(posts)}] {label}")
                    try:
                        result = eng.read_post(
                            page, post["post_url"],
                            group_name=post["group_name"],
                            account=post["account"])
                    except Exception as exc:              # noqa: BLE001
                        failed += 1
                        log(f"     ❌ อ่านไม่สำเร็จ: {str(exc)[:120]}")
                        result = {"reachable": False, "reactions": None,
                                  "comments": None, "shares": None,
                                  "note": f"อ่านไม่สำเร็จ: {str(exc)[:160]}"}
                    else:
                        if result.get("reachable"):
                            ok += 1
                            log(f"     ✅ ไลก์ {result.get('reactions')} · "
                                f"คอมเมนต์ {result.get('comments')} · "
                                f"แชร์ {result.get('shares')}")
                        else:
                            gone += 1
                            log(f"     ⚠️ เข้าไม่ถึง — {str(result.get('note'))[:90]}")

                    save_row(conn, post, result)
                    save_progress(index, len(posts), ok, gone, failed)

                    # พักทุก 6 โพสต์ตามที่เจ้าของสั่ง (ไม่พักหลังใบสุดท้าย)
                    if index % POSTS_PER_REST == 0 and index < len(posts):
                        nap = random.uniform(*REST_SECONDS)
                        left = len(posts) - index
                        log(f"  ⏳ พัก {int(nap)} วินาที (สุ่ม 1–5 นาที) · เหลืออีก {left} โพสต์")
                        time.sleep(nap)
            finally:
                try:
                    browser.close()
                except Exception:
                    pass
    finally:
        conn.close()

    return {"ok": ok, "gone": gone, "failed": failed,
            "total": len(posts), "minutes": (time.monotonic() - started) / 60}


def save_row(conn, post: dict, result: dict) -> None:
    """เขียนลงตาราง `my_post` ตัวเดียวกับที่ตัวเก็บประจำใช้

    **ห้ามสร้างตารางใหม่** ถ้าแยกตารางจะได้ตัวเลขสองชุดที่ไม่ตรงกัน
    แล้วไม่มีใครรู้ว่าชุดไหนจริง (กติกาข้อ 2.3 — ตัวเลขที่ขัดกันเองอันตราย
    กว่าไม่มีตัวเลข)
    """
    conn.execute(
        """INSERT INTO my_post (post_url, group_id, group_name, account,
                                reactions, comments, shares, reachable, note, checked_at)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (post["post_url"], post["group_id"], post["group_name"], post["account"],
         result.get("reactions"), result.get("comments"), result.get("shares"),
         1 if result.get("reachable") else 0, str(result.get("note") or ""),
         datetime.now().isoformat(timespec="seconds")))
    conn.commit()


# ----------------------------------------------------------------- เริ่มทำงาน

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="ดูว่าจะเก็บอะไร ไม่เปิดเบราว์เซอร์")
    ap.add_argument("--limit", type=int, default=0, help="เก็บแค่กี่โพสต์ (0 = ทั้งหมด)")
    args = ap.parse_args()

    posts = pending_posts(args.limit)
    if not posts:
        log("ไม่มีโพสต์ตกค้าง — ตามยอดครบทุกใบแล้ว")
        return 0

    by_account: dict[str, int] = {}
    for p in posts:
        by_account[p["account"]] = by_account.get(p["account"], 0) + 1
    log(f"โพสต์ที่ยังไม่เคยตามยอด {len(posts)} ใบ")
    for acct, n in sorted(by_account.items(), key=lambda kv: -kv[1]):
        log(f"   {acct:24s} {n:4d} ใบ")
    rests = (len(posts) - 1) // POSTS_PER_REST
    guess = (len(posts) * 20 + rests * 180) / 60
    log(f"พักทุก {POSTS_PER_REST} โพสต์ ครั้งละ 1–5 นาที → พัก {rests} ครั้ง "
        f"· คาดว่าใช้เวลาราว {guess:.0f} นาที")

    if args.dry_run:
        log("(--dry-run) ไม่ได้เปิดเบราว์เซอร์ ไม่ได้แตะสวิตช์หยุดบอท")
        return 0

    ours = pause_regular_collector()
    try:
        done = collect(posts)
    finally:
        resume_regular_collector(ours)
        log(f"สถานะสวิตช์ตอนนี้: {pause_state() or '(ไม่ได้หยุด — ปกติ)'}")

    log("")
    log(f"เสร็จแล้ว {done['total']} ใบ ใช้เวลา {done['minutes']:.0f} นาที")
    log(f"   อ่านยอดได้      {done['ok']}")
    log(f"   เข้าไม่ถึง/ถูกลบ {done['gone']}")
    log(f"   อ่านไม่สำเร็จ    {done['failed']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
