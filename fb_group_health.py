# -*- coding: utf-8 -*-
"""สถานะรายกลุ่ม Facebook — กลุ่มไหนยังมีชีวิต กลุ่มไหนตายแล้ว

**เจ้าของสั่งไว้ 31 ส.ค. 2569** — *"เอากลุ่มที่ให้เสิชหาว่ากลุ่มไหนมี
engagement ดีไม่ดี ตายแล้วหรือยัง มาใส่บนเว็บ"*

---

## แยกสองเรื่องที่คนมักปนกัน

**"กลุ่มตาย" กับ "โพสต์เราไม่ติด" เป็นคนละเรื่อง และต้องแก้คนละทาง**

    กลุ่มเงียบ  โพสต์เราเงียบ  →  เลิกโพสต์กลุ่มนี้ ไปหากลุ่มใหม่
    กลุ่มคึกคัก โพสต์เราเงียบ  →  กลุ่มไม่ผิด **เนื้อหาเราไม่ตรงกลุ่ม**

ถ้ารายงานรวมกันเป็นตัวเลขเดียว จะแยกไม่ออกว่าควรทิ้งกลุ่มหรือควรแก้โพสต์
หน้านี้จึงวัดสองฝั่งแยกกันเสมอ

| ฝั่ง | อ่านจาก | ตอบคำถามว่า |
|---|---|---|
| กลุ่ม | `data/fb_posts.db` (โพสต์ของคนอื่น ที่ Bot8/Bot9 เก็บ) | กลุ่มนี้ยังมีคนเล่นอยู่ไหม |
| เรา | ตัวตามยอด (`fb_engagement`) | โพสต์ของเราได้ผลไหม |

## กติกาที่ห้ามละเมิด

1. **"ไม่มีข้อมูล" ต้องไม่ถูกรายงานว่า "ตายแล้ว"** (กติกาข้อ 2.3.1 ข้อ 4)
   กลุ่มที่บอทยังไม่เคยไปเก็บ กับกลุ่มที่ไปเก็บแล้วพบว่าเงียบ **หน้าตาต้องต่างกัน**
   ไม่งั้นวันที่บอทเก็บพัง ทุกกลุ่มจะกลายเป็น "ตายแล้ว" พร้อมกันแล้วเจ้าของ
   จะเลิกโพสต์กลุ่มที่ยังดีอยู่
2. **ชื่อกลุ่มเอาจากทะเบียนเท่านั้น** ห้ามใช้ชื่อที่บอทเก็บมา
   วัดจริง 31 ส.ค.: กลุ่ม `620834715525743` ถูกบอทบันทึกชื่อว่า **"เยี่ยมชม"**
   ซึ่งเป็นป้ายปุ่มบนหน้า ไม่ใช่ชื่อกลุ่ม (ของจริงคือ "อยากมีบ้านโว้ย")
3. **เปิดฐานข้อมูลแบบอ่านอย่างเดียวเสมอ** Bot8/Bot9 เขียนไฟล์นี้อยู่ตลอด
   (วัดตอนเขียน: 1.7 GB · แก้ล่าสุดเมื่อ 12 วินาทีก่อน) เปิดแบบเขียนได้เมื่อไร
   มีโอกาสไปล็อกจนบอทเก็บของค้าง
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

import studio_shared

# ---------------------------------------------------------------- ค่าเกณฑ์
#
# ตัวเลขพวกนี้มาจากของจริงที่วัดได้ 31 ส.ค. 2569 ไม่ได้ตั้งลอยๆ
#
#   แต่งห้าง แต่งบ้าน   ไลก์เฉลี่ย 92.4 · โพสต์เกิน 100 ไลก์ 81 ใบ  ← คึกคักสุด
#   อยากมีบ้านโว้ย      ไลก์เฉลี่ย  9.2 · โพสต์เกิน 100 ไลก์ 25 ใบ
#   รีวิวของดีประจำวัน   ไลก์เฉลี่ย  3.4 · โพสต์เกิน 100 ไลก์  8 ใบ
#   แชร์ตรงปกมาก       ไลก์เฉลี่ย  3.1 · โพสต์เกิน 100 ไลก์  4 ใบ
#   รีวิวครอบจักรวาล    ไลก์เฉลี่ย  2.3 · โพสต์เกิน 100 ไลก์  6 ใบ
#   ช้อปขั้นเทพ         ไลก์เฉลี่ย  0.9 · โพสต์เกิน 100 ไลก์  1 ใบ  ← ซบเซาสุด
#
# เส้นแบ่งที่ 2.0 จึงตัด "ช้อปขั้นเทพ" ออกจากกลุ่มที่เหลือได้พอดี
LIVELY_AVG = 2.0            # ไลก์เฉลี่ยต่อโพสต์ ตั้งแต่นี้ขึ้นไป = กลุ่มยังคึกคัก
FRESH_DAYS = 7.0            # ดูโพสต์ย้อนหลังกี่วัน
QUIET_DAYS = 3.0            # ไม่มีโพสต์ใหม่เกินนี้ = กลุ่มเงียบ
MIN_SAMPLE = 20             # เก็บได้น้อยกว่านี้ = ยังตัดสินไม่ได้
OUR_OK_REACTIONS = 2.0      # โพสต์เราได้ไลก์เฉลี่ยตั้งแต่นี้ = พอไปได้

POSTS_DB = "fb_posts.db"

# ป้ายสถานะ — `key` เอาไว้ให้หน้าเว็บเลือกสี ส่วน `label` เอาไว้ให้คนอ่าน
UNKNOWN = "unknown"
DEAD = "dead"
SLOW = "slow"
MISMATCH = "mismatch"
GOOD = "good"


def _posts_db() -> sqlite3.Connection | None:
    """เปิดฐานข้อมูลโพสต์แบบอ่านอย่างเดียว — เปิดไม่ได้คืน None ไม่โยน error

    เปิดไม่ได้ **ไม่ใช่เรื่องผิดปกติ** บอทอาจยังไม่เคยรัน หรือไฟล์ถูกย้าย
    หน้าเว็บต้องขึ้นว่า "ยังไม่รู้" ไม่ใช่ขึ้นว่าทุกกลุ่มตายหมด
    """
    path = Path(studio_shared.DATA_DIR) / POSTS_DB
    if not path.exists():
        return None
    try:
        conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True,
                               timeout=5.0)
        conn.row_factory = sqlite3.Row
        return conn
    except Exception:                                        # noqa: BLE001
        return None


def _group_side(conn: sqlite3.Connection | None, gid: str) -> dict:
    """ฝั่งกลุ่ม — โพสต์ของคนอื่นในกลุ่มนี้คึกคักแค่ไหน"""
    blank = {"known": False, "posts": 0, "fresh_posts": 0, "avg_reactions": None,
             "hot_posts": 0, "members": None, "last_post_ago_days": None}
    if conn is None or not gid:
        return blank
    try:
        since = int(time.time() - FRESH_DAYS * 86400)
        row = conn.execute(
            """SELECT COUNT(*) AS posts,
                      SUM(CASE WHEN posted_at >= ? THEN 1 ELSE 0 END) AS fresh,
                      AVG(reactions) AS avg_r,
                      SUM(CASE WHEN reactions >= 100 THEN 1 ELSE 0 END) AS hot,
                      MAX(posted_at) AS newest
               FROM fb_post WHERE gid = ?""", (since, gid)).fetchone()
        members = conn.execute(
            "SELECT members FROM fb_group WHERE gid = ?", (gid,)).fetchone()
    except Exception:                                        # noqa: BLE001
        return blank                       # อ่านไม่ได้ = ยังไม่รู้ ไม่ใช่ตาย
    posts = int(row["posts"] or 0)
    if not posts:
        return blank
    newest = row["newest"]
    ago = None
    if newest:
        try:
            ago = max(0.0, (time.time() - float(newest)) / 86400.0)
        except (TypeError, ValueError):
            ago = None
    return {
        "known": True,
        "posts": posts,
        "fresh_posts": int(row["fresh"] or 0),
        "avg_reactions": round(float(row["avg_r"] or 0.0), 1),
        "hot_posts": int(row["hot"] or 0),
        "members": (members["members"] if members else None) or None,
        "last_post_ago_days": None if ago is None else round(ago, 1),
    }


def _our_side(name: str) -> dict:
    """ฝั่งเรา — โพสต์ของเราในกลุ่มนี้ได้ผลแค่ไหน

    จับคู่ด้วย **ชื่อกลุ่ม** เพราะตัวตามยอดเก็บชื่อไว้ ไม่ได้เก็บรหัสกลุ่ม
    ชื่อไม่ตรง = ถือว่ายังไม่มีข้อมูล ไม่ใช่ถือว่าได้ 0
    """
    blank = {"known": False, "posts": 0, "avg_reactions": None,
             "avg_comments": None, "owed": 0}
    if not name:
        return blank
    try:
        import fb_engagement                                  # noqa: PLC0415

        conn = fb_engagement.open_db()
        row = conn.execute(
            """SELECT COUNT(DISTINCT post_url) AS posts,
                      AVG(reactions) AS avg_r, AVG(comments) AS avg_c
               FROM (SELECT post_url, MAX(reactions) AS reactions,
                            MAX(comments) AS comments
                     FROM my_post WHERE group_name = ? AND reachable = 1
                     GROUP BY post_url)""", (name,)).fetchone()
        owed = conn.execute(
            """SELECT COUNT(*) FROM my_comment c
               WHERE c.is_ours = 0 AND c.answered = 0 AND TRIM(c.body) <> ''
                 AND c.post_url IN (SELECT post_url FROM my_post
                                    WHERE group_name = ?)""", (name,)).fetchone()[0]
    except Exception:                                        # noqa: BLE001
        return blank
    posts = int(row["posts"] or 0)
    if not posts:
        return blank
    return {
        "known": True,
        "posts": posts,
        "avg_reactions": round(float(row["avg_r"] or 0.0), 1),
        "avg_comments": round(float(row["avg_c"] or 0.0), 1),
        "owed": int(owed or 0),
    }


def _verdict(group: dict, ours: dict) -> tuple[str, str, str]:
    """ตัดสินสถานะ — คืน (รหัส, ป้ายที่คนอ่าน, เหตุผล)

    **ลำดับการถามสำคัญมาก** ต้องถาม "รู้ไหม" ก่อน "ดีไหม" เสมอ
    ไม่งั้นกลุ่มที่ยังไม่เคยเก็บจะถูกตัดสินว่าตายทันที
    """
    if not group["known"]:
        return (UNKNOWN, "ยังไม่รู้",
                "บอทยังไม่เคยเก็บโพสต์ในกลุ่มนี้ — ยังตัดสินไม่ได้")
    if group["posts"] < MIN_SAMPLE:
        return (UNKNOWN, "ยังไม่รู้",
                f"เก็บได้แค่ {group['posts']} โพสต์ (ต้องมีอย่างน้อย "
                f"{MIN_SAMPLE} ใบถึงจะตัดสิน)")

    ago = group["last_post_ago_days"]
    if ago is not None and ago > QUIET_DAYS:
        return (DEAD, "ตายแล้ว",
                f"ไม่มีโพสต์ใหม่มา {ago:.0f} วัน — คนเลิกเล่นกลุ่มนี้แล้ว")

    avg = group["avg_reactions"] or 0.0
    if avg < LIVELY_AVG:
        return (SLOW, "ซบเซา",
                f"มีคนโพสต์อยู่ แต่ไลก์เฉลี่ยแค่ {avg:.1f} ต่อโพสต์ "
                f"— โพสต์อะไรไปก็เงียบ")

    # ถึงตรงนี้ = กลุ่มยังคึกคัก เหลือแค่ดูว่าของเราติดไหม
    if not ours["known"]:
        return (GOOD, "กลุ่มดี",
                f"กลุ่มคึกคัก (ไลก์เฉลี่ย {avg:.1f}) — เรายังไม่มีข้อมูล"
                f"โพสต์ของตัวเองในกลุ่มนี้")
    if (ours["avg_reactions"] or 0.0) < OUR_OK_REACTIONS:
        return (MISMATCH, "กลุ่มดีแต่ของเราไม่ติด",
                f"กลุ่มคึกคัก (ไลก์เฉลี่ย {avg:.1f}) แต่โพสต์เราได้เฉลี่ยแค่ "
                f"{ours['avg_reactions']:.1f} — ปัญหาอยู่ที่เนื้อหา ไม่ใช่กลุ่ม")
    return (GOOD, "ดี",
            f"กลุ่มคึกคัก (ไลก์เฉลี่ย {avg:.1f}) และโพสต์เราได้เฉลี่ย "
            f"{ours['avg_reactions']:.1f} ไลก์")


def _registry() -> list[dict]:
    """ทะเบียนกลุ่ม — **ถามเซิร์ฟเวอร์ ไม่เดาพาธไฟล์เอง**

    ทะเบียนกลุ่มเก็บแยกรายบัญชี (`studio_shared.account_file`) ซึ่งจงใจ
    **ล้มทันทีถ้าไม่บอกว่าบัญชีไหน** ตามกติกาข้อ 8 (ห้ามเดาว่าจะใช้บัญชีไหน
    เพราะ "โพสต์ลงบัญชีผิด" กู้คืนไม่ได้)

    โมดูลนี้ไม่รู้และไม่ควรรู้ว่าตอนนี้ใช้บัญชีไหน — **เซิร์ฟเวอร์รู้**
    จึงถามเอาจากที่อยู่เดียวกับที่หน้าเว็บใช้ ได้ที่มาเดียวกัน ไม่มีสองที่
    ให้ต้องแก้ตามกันเวลาโครงสร้างเปลี่ยน

    ปกติ `app.py` จะส่งรายชื่อเข้ามาให้ตรงๆ อยู่แล้ว ทางนี้มีไว้สำหรับเรียก
    จากบรรทัดคำสั่ง (`python fb_group_health.py`) เท่านั้น
    """
    import os                                                 # noqa: PLC0415
    import urllib.request                                     # noqa: PLC0415

    port = os.environ.get("STUDIO_PORT", "8866")
    try:
        url = f"http://127.0.0.1:{port}/api/fb/groups"
        with urllib.request.urlopen(url, timeout=10) as answer:
            data = json.loads(answer.read().decode("utf-8"))
        return [g for g in (data.get("groups") or []) if isinstance(g, dict)]
    except Exception as error:                               # noqa: BLE001
        raise RuntimeError(
            f"อ่านทะเบียนกลุ่มไม่ได้ ({error}) — เซิร์ฟเวอร์ {port} เปิดอยู่ไหม"
        ) from error


def report(groups: list[dict] | None = None) -> dict:
    """สถานะทุกกลุ่ม พร้อมสรุปหัวตาราง — รูปแบบที่หน้าเว็บใช้ได้ตรงๆ

    `groups` ใส่มาเองได้ (รายการจากทะเบียน) ไม่ใส่จะไปอ่านเอง
    """
    rows_in = groups if groups is not None else _registry()
    conn = _posts_db()
    out: list[dict] = []
    try:
        for item in rows_in:
            gid = str(item.get("group_id") or item.get("gid") or "")
            name = str(item.get("name") or "").strip()
            group = _group_side(conn, gid)
            ours = _our_side(name)
            key, label, why = _verdict(group, ours)
            out.append({
                "group_id": gid,
                "name": name or gid or "(ไม่มีชื่อ)",
                "set": item.get("set") or "",
                "enabled": bool(item.get("enabled", True)),
                "url": f"https://www.facebook.com/groups/{gid}" if gid else "",
                "status": key,
                "status_label": label,
                "why": why,
                "group_side": group,
                "our_side": ours,
            })
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:                                # noqa: BLE001
                pass

    order = {GOOD: 0, MISMATCH: 1, SLOW: 2, DEAD: 3, UNKNOWN: 4}
    out.sort(key=lambda r: (order.get(r["status"], 9),
                            -(r["group_side"]["avg_reactions"] or 0)))
    tally: dict[str, int] = {}
    for row in out:
        tally[row["status"]] = tally.get(row["status"], 0) + 1
    return {
        "ok": True,
        "groups": out,
        "tally": tally,
        "checked_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "note": ("อ่านจากโพสต์ของคนอื่นที่บอทเก็บมา + ยอดโพสต์ของเราเอง "
                 "— \"ยังไม่รู้\" แปลว่ายังไม่มีข้อมูลพอ ไม่ได้แปลว่ากลุ่มแย่"),
    }


if __name__ == "__main__":                                    # pragma: no cover
    import sys

    data = report()
    print(f"ตรวจ {len(data['groups'])} กลุ่ม เมื่อ {data['checked_at']}\n")
    for row in data["groups"]:
        g, o = row["group_side"], row["our_side"]
        print(f"[{row['status_label']}] {row['name'][:40]}")
        print(f"   {row['why']}")
        if g["known"]:
            print(f"   กลุ่ม: เก็บได้ {g['posts']:,} โพสต์ · ใหม่ {FRESH_DAYS:.0f} วัน "
                  f"{g['fresh_posts']} ใบ · เกิน 100 ไลก์ {g['hot_posts']} ใบ")
        if o["known"]:
            print(f"   เรา : {o['posts']} โพสต์ · ไลก์เฉลี่ย {o['avg_reactions']} "
                  f"· คอมเมนต์เฉลี่ย {o['avg_comments']} · ค้างตอบ {o['owed']}")
        print()
    sys.exit(0)
