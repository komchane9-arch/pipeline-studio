# -*- coding: utf-8 -*-
"""โพสต์ลง **เพจ** Facebook ด้วยการกดหน้าจอจริงทุกจุด

เจ้าของสั่ง 22 ก.ย. 2569 — *"เพิ่มการโพสต์ในเพจหน่อย … การโพสต์จะมี แคปชั่น รูป
คอมเมนต์ (ทำให้คอมเมนต์ได้มากกว่า 1) คล้ายๆ กับการโพสต์ในกลุ่ม แล้วกดไลก์โพสต์
กดไลก์คอมเมนต์หน่อย"* และเลือกให้ **เขียนเป็นไฟล์แยก** ไม่ยัดรวมกับตัวโพสต์กลุ่ม

## ทำไมเป็นไฟล์แยก แต่ไม่ได้ก๊อปโค้ด

`facebook_group_post.py` ยาว 4,000 บรรทัด และเกือบทั้งหมด **ไม่ได้ผูกกับกลุ่ม** —
การแนบรูป · พิมพ์แคปชัน · กดโพสต์ · ไลก์โพสต์ของตัวเอง · คอมเมนต์แล้วไลก์คอมเมนต์
ใช้หน้าจอชุดเดียวกันเป๊ะ ไฟล์นี้จึง **ยืมของพวกนั้นมาใช้** แล้วเขียนเองเฉพาะ
ส่วนที่ต่างจริง 3 อย่าง

    1. ไปถึงช่องเขียนโพสต์คนละทาง — กลุ่มเปิดหน้ากลุ่ม เพจใช้หน้าเพจตัวเอง
    2. ต้องสลับโปรไฟล์เป็นเพจก่อน แล้ว**สลับกลับ**ให้เรียบร้อย
    3. คอมเมนต์ได้เกิน 2 ข้อความ (ตัวโพสต์กลุ่มตั้งเพดานไว้ที่ 2)

ก๊อปโค้ดมาจะได้บั๊กเก่าสองชุดที่ต้องไล่แก้คนละรอบ — Facebook เปลี่ยนหน้าตาบ่อย
มาก ของที่แก้ไว้ที่เดียวจึงคุ้มกว่า

## กติกาที่ไฟล์นี้ยึด

**ทุกการกระทำเป็นการกดจอจริง** (CLAUDE.md ข้อ 2.7) ยกเว้นข้อเดียวคือการเปิดแอป
ไฟล์นี้จึง **ไม่มี `am start` ไปหน้าไหนทั้งสิ้น** — ไปหน้าเพจด้วยการแตะแท็บรูปเพจ
ที่มุมล่างขวา และเข้าหน้าโพสต์ด้วยการแตะปุ่มคอมเมนต์ ไม่ใช่ยิงลิงก์

**สลับโปรไฟล์แล้วต้องสลับกลับเสมอ** ค้างไว้ = งานถัดไปของสายคลิปโพสต์ออกในนามผิด
ซึ่งกู้ไม่ได้ ต้องเข้าไปลบเองในแอป จึงคืนโปรไฟล์ใน `finally` และ**พิสูจน์ผลด้วย**

    python facebook_page_post.py --list
    python facebook_page_post.py --dry-run --caption "ทดสอบ" --image a.jpg
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import facebook_group_post as g
import fb_profile as fp

# ช่องเขียนโพสต์บน **หน้าเพจ** เขียนคนละอย่างกับในกลุ่ม
PAGE_COMPOSER_HINTS = list(fp.COMPOSER_MARKS) + ["เขียนโพสต์", "Create post"]

# ปุ่มยืนยันหลังแนบรูปของหน้าเพจ (บางรุ่นเป็น "ถัดไป" บางรุ่นเป็น "เสร็จสิ้น")
PAGE_NEXT_HINTS = g.NEXT_HINTS

PAGE_LOAD = 8.0                 # รอหน้าเพจวาดเสร็จหลังแตะแท็บเพจ
COMPOSER_WAIT = 18.0            # รอช่องเขียนโพสต์โผล่
AFTER_POST = 14.0               # รอโพสต์ขึ้นหน้าเพจก่อนไปไลก์/คอมเมนต์
COMMENT_CHUNK = g.MAX_COMMENTS  # ตัวโพสต์กลุ่มรับได้ทีละ 2 — ยิงเป็นชุดๆ ไป


class PageError(RuntimeError):
    """โพสต์ลงเพจไม่สำเร็จ — ข้อความข้างในเขียนให้คนอ่านรู้เรื่องทันที"""


# --------------------------------------------------------------- ไปหน้าเพจ

def on_page(xml: str) -> bool:
    """อยู่บนหน้าเพจของเราเองไหม — **ดูของที่มีเฉพาะตอนเป็นจริง**

    คือ **ช่องเขียนโพสต์ + ปุ่มของแอดมิน** พร้อมกัน (กติกาข้อ 2.3.1)
    ไม่ใช่ "ไม่เจอปุ่มติดตาม" ซึ่งหน้าอื่นอีกหลายหน้าก็ตอบว่าใช่ได้
    """
    return (any(m in xml for m in fp.COMPOSER_MARKS)
            and any(m in xml for m in fp.ADMIN_MARKS))


def reach_page(phone: g.Phone, tries: int = 3) -> str:
    """แตะกลับมาหน้าเพจของเราเอง — คืนผังจอของหน้าเพจ

    **แตะแท็บล่างขวา ไม่ยิงลิงก์** เพราะในโหมดเพจแบบมืออาชีพ ช่องล่างขวาสุด
    คือรูปโปรไฟล์ของเพจ (เมนูย้ายไป ☰ มุมบนซ้ายแทน) — นี่คือจุดที่ตัวอ่านรุ่นแรก
    เข้าใจผิดจนวนล้ม 9 รอบติดเมื่อ 22 ก.ย. 2569
    """
    for attempt in range(1, tries + 1):
        xml = phone.dump()
        if on_page(xml):
            return xml
        cells = fp._nav_cells(xml)
        if not cells:
            phone.log(f"  (หาหน้าเพจ รอบ {attempt}) ไม่เจอแถบนำทางล่าง")
            time.sleep(2.0)
            continue
        x1, y1, x2, y2 = cells[-1]
        phone.log(f"  (หาหน้าเพจ รอบ {attempt}) แตะแท็บรูปเพจมุมล่างขวา")
        phone.tap(((x1 + x2) // 2, (y1 + y2) // 2))
        time.sleep(PAGE_LOAD)
    xml = phone.dump()
    if on_page(xml):
        return xml
    raise PageError(
        "กดกลับมาหน้าเพจไม่ได้ — ไม่เห็นช่องเขียนโพสต์กับปุ่มแอดมินพร้อมกัน "
        "(อาจโดนกล่องอะไรบังอยู่ ลองดูภาพหลักฐานที่เก็บไว้)")


# ------------------------------------------------------------ เขียนโพสต์

def compose(phone: g.Phone, caption: str, photo_count: int) -> None:
    """แตะช่องเขียนโพสต์ → แนบรูป → พิมพ์แคปชัน — **ยังไม่กดโพสต์**"""
    phone.log("  แตะช่องเขียนโพสต์ของเพจ")
    phone.tap(phone.wait_for(PAGE_COMPOSER_HINTS, timeout=COMPOSER_WAIT))
    time.sleep(3.0)

    if photo_count > 0:
        phone.log("  แนบรูป")
        # วนรอปุ่มแนบรูป ไม่ใช่มองครั้งเดียว — หน้าเพจโหลดช้ากว่าหน้ากลุ่ม
        # เพราะมีแถบเครื่องมือของแอดมินให้วาดเพิ่ม (บทเรียนเดียวกับตัวโพสต์กลุ่ม)
        photo = phone.find(phone.dump(), g.PHOTO_HINTS)
        for _ in range(g.PHOTO_BUTTON_TRIES):
            if photo is not None:
                break
            time.sleep(1.5)
            photo = phone.find(phone.dump(), g.PHOTO_HINTS)
        if photo is None:
            g.keep_failure_screen(phone, "ไม่พบปุ่มแนบรูปในหน้าเขียนโพสต์ของเพจ")
            raise PageError("ไม่พบปุ่มแนบรูปในหน้าเขียนโพสต์ของเพจ")
        phone.tap(photo)
        time.sleep(2.5)

        picked = g.pick_photos(phone, photo_count)
        if picked < 1:
            g.keep_failure_screen(phone, "เลือกรูปในแกลเลอรีไม่ได้")
            raise PageError("เลือกรูปในแกลเลอรีไม่ได้ — ไม่พบรูปในหน้าเลือกรูป")
        phone.log(f"  เลือกรูป {picked} ใบ"
                  + ("" if picked == photo_count else f" (ขอไว้ {photo_count} ใบ)"))
        nxt = phone.find(phone.dump(), PAGE_NEXT_HINTS)
        if nxt:
            phone.tap(nxt)
        time.sleep(2.0)

    phone.log("  พิมพ์แคปชัน")
    field = phone.find(phone.dump(), g.CAPTION_FIELD_HINTS + PAGE_COMPOSER_HINTS)
    if field is None:
        g.keep_failure_screen(phone, "ไม่พบช่องพิมพ์แคปชัน")
        raise PageError("ไม่พบช่องพิมพ์แคปชันในหน้าเขียนโพสต์ของเพจ")
    phone.tap(field)
    time.sleep(1.5)
    phone.type_text(caption)
    time.sleep(1.5)
    # **ยืนยันจากหน้าจอจริง** ไม่เชื่อว่าส่ง broadcast ผ่าน = ข้อความเข้าแล้ว
    if not g.screen_has(phone.dump(), caption.strip()[:10]):
        g.keep_failure_screen(phone, "พิมพ์แคปชันแล้วข้อความไม่ขึ้นบนจอ")
        raise PageError("พิมพ์แคปชันแล้วแต่ข้อความไม่ขึ้นบนหน้าจอ")

    done = phone.find(phone.dump(), g.CAPTION_DONE_HINTS)
    if done:
        phone.tap(done)
        time.sleep(2.0)


def press_post(phone: g.Phone, caption: str) -> None:
    """กดโพสต์แล้ว **พิสูจน์ว่าขึ้นจริง** — ไม่ใช่กดแล้วเชื่อว่าสำเร็จ"""
    # ปิดคีย์บอร์ดก่อนเสมอ ไม่งั้นปุ่มโพสต์โดนบังจนหายไปจากผังจอบนเครื่องจอเตี้ย
    phone.hide_keyboard()
    phone.log("  กดโพสต์")
    phone.tap(phone.wait_for(g.POST_HINTS, timeout=15, exact=True))
    time.sleep(AFTER_POST)

    # หาของที่ **มีเฉพาะตอนโพสต์ขึ้นแล้ว** คือแคปชันของเราโผล่บนหน้าเพจ
    probe = caption.strip()[:10]
    for attempt in range(1, 5):
        xml = phone.dump()
        if g.screen_has(xml, probe):
            phone.log(f"  ✅ เห็นโพสต์ของเราบนหน้าเพจแล้ว (ตรวจรอบที่ {attempt})")
            return
        phone.log(f"  ยังไม่เห็นโพสต์บนหน้าเพจ — รออีก 8 วิ (รอบ {attempt})")
        time.sleep(8.0)
    g.keep_failure_screen(phone, "กดโพสต์แล้วแต่ไม่เห็นโพสต์บนหน้าเพจ")
    raise PageError(
        "กดปุ่มโพสต์ไปแล้วแต่หาโพสต์บนหน้าเพจไม่เจอ — **ห้ามกดซ้ำ** "
        "เพราะอาจขึ้นไปแล้วจริงแต่หน้าจอยังไม่วาด ให้เข้าไปดูในแอปก่อน")


# ---------------------------------------------------------- ไลก์ + คอมเมนต์

def add_comments(phone: g.Phone, caption: str, comments: list[str],
                 photos=None) -> dict:
    """คอมเมนต์ใต้โพสต์ของเราแล้วไลก์ทุกข้อความ — **เกิน 2 ข้อความได้**

    ตัวโพสต์กลุ่มตั้งเพดานไว้ที่ `MAX_COMMENTS` (ตอนนี้ 2) เพราะกลุ่มส่วนใหญ่
    ไม่ให้คอมเมนต์รัว ส่วนเพจเป็นของเราเอง เจ้าของจึงขอให้ใส่ได้มากกว่านั้น
    **ไม่แก้เพดานของเขา** เพราะไฟล์นั้นเป็นของสายโพสต์และเพดานนั้นมีเหตุผลของมัน
    — ยิงเป็นชุดละ 2 แทน ได้ผลเท่ากันและไม่ไปแตะกติกาของอีกสาย
    """
    texts = [str(t).strip() for t in comments if str(t or "").strip()]
    if not texts:
        return dict(g.NO_COMMENT)
    shots = g._as_photos(photos, len(texts))
    done = liked = 0
    for start in range(0, len(texts), COMMENT_CHUNK):
        chunk = texts[start:start + COMMENT_CHUNK]
        phone.log(f"  คอมเมนต์ชุดที่ {start // COMMENT_CHUNK + 1} "
                  f"({len(chunk)} ข้อความ)")
        got = g.comment_post_of(phone, caption, chunk,
                                photos=shots[start:start + COMMENT_CHUNK])
        count = int(got.get("comment_count") or 0)
        done += count
        if got.get("comment_liked"):
            liked += count
        if count < len(chunk):
            phone.log(f"  ชุดนี้ลงได้ {count} จาก {len(chunk)} — หยุดไว้แค่นี้")
            break
        time.sleep(2.5)
    return {"commented": done > 0, "comment_liked": liked == done and done > 0,
            "comment_count": done}


# ------------------------------------------------------------------ งานรวม

def post_to_page(
    phone: g.Phone, page_name: str, caption: str, images: list[Path] | None = None,
    comments: list[str] | None = None, comment_images=None,
    dry_run: bool = False, restore_to: str = "", stop=lambda: False,
) -> dict:
    """โพสต์ลงเพจหนึ่งใบ — คืนผลว่าไปถึงขั้นไหน

    `restore_to` = โปรไฟล์ที่ต้องสลับกลับไปหลังเสร็จ เว้นว่างแปลว่า "โปรไฟล์ที่
    เครื่องใช้อยู่ก่อนเราเริ่ม" ซึ่งอ่านเอาเองตอนเริ่ม
    """
    images = [Path(p) for p in (images or [])]
    comments = list(comments or [])
    result: dict = {"page": page_name, "posted": False, "liked": False,
                    **dict(g.NO_COMMENT), "restored": ""}

    for path in images:
        if not path.is_file():
            raise PageError(f"ไม่พบไฟล์รูป {path}")

    g.require_network(phone)

    before = restore_to or fp.whoami(fp.adb_path(), phone.serial, phone.log)
    if not before:
        raise PageError(
            "อ่านไม่ได้ว่าตอนนี้เครื่องใช้โปรไฟล์ไหนอยู่ — **ไม่สลับ** "
            "เพราะสลับไปแล้วจะไม่รู้ทางกลับ ต้องเข้าไปดูที่เครื่องก่อน")
    phone.log(f"  โปรไฟล์ก่อนเริ่ม: {before}")

    try:
        # ส่ง `before` ไปด้วย เพราะเพิ่งอ่านมาเมื่อกี้ — ไม่งั้นด่านจะอ่านซ้ำอีกรอบ
        # ซึ่งกินเวลาราวหนึ่งนาทีโดยไม่ได้อะไรเพิ่ม
        fp.guard(phone.serial, page_name, phone.log, now=before)

        if images:
            phone.log(f"  ส่งรูป {len(images)} ใบเข้าเครื่อง")
            g.push_images(phone, images)
            g.ensure_images_newest(phone, images)

        reach_page(phone)
        compose(phone, caption, len(images))

        if dry_run:
            phone.log("  [ซ้อม] ยังไม่กดโพสต์ — ตรวจหน้าจอได้เลย")
            result["dry_run"] = True
            return result

        press_post(phone, caption)
        result["posted"] = True

        if stop():
            phone.log("  ผู้ใช้สั่งยกเลิก — ข้ามการไลก์/คอมเมนต์")
            return result

        # Facebook รุ่นใหม่วางแคปชันไว้ใต้รูป รูปสูงดันข้อความเลยขอบจอ
        g._reveal_caption_below_media(phone, caption)
        result["liked"] = g.like_post_of(phone, caption)
        result.update(add_comments(phone, caption, comments, comment_images))
        return result
    finally:
        # **ต้องคืนโปรไฟล์เสมอ แม้ตอนล้มกลางคัน** ค้างไว้ = งานถัดไปของสายคลิป
        # โพสต์ออกในนามเพจนี้ ซึ่งถอนไม่ได้ ต้องไปลบเองในแอป
        if not fp.same_name(before, page_name):
            try:
                result["restored"] = fp.guard(phone.serial, before, phone.log)
                phone.log(f"  คืนโปรไฟล์กลับเป็น {result['restored']} แล้ว")
            except Exception as error:               # noqa: BLE001
                # กลืนไม่ได้เด็ดขาด — ต้องดังพอให้คนเห็นและเข้าไปแก้ที่เครื่อง
                phone.log(f"  ⛔ คืนโปรไฟล์กลับไม่สำเร็จ: {error}")
                result["restored"] = ""
                result["restore_error"] = str(error)


# ---------------------------------------------------------------- สั่งจากคอนโซล

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="โพสต์ลงเพจ Facebook")
    parser.add_argument("--serial", default="", help="เครื่องไหน (ไม่บอก = อ่านจากทะเบียน)")
    parser.add_argument("--page", default="", help="ชื่อเพจตามที่แอปสะกด")
    parser.add_argument("--caption", default="", help="แคปชัน")
    parser.add_argument("--image", action="append", default=[], help="ไฟล์รูป (ใส่ซ้ำได้)")
    parser.add_argument("--comment", action="append", default=[], help="คอมเมนต์ (ใส่ซ้ำได้)")
    parser.add_argument("--dry-run", action="store_true", help="ทำทุกขั้นยกเว้นกดโพสต์")
    parser.add_argument("--list", action="store_true", help="ดูว่ามีเพจอะไรบ้าง")
    args = parser.parse_args(argv)

    if args.list:
        for name, pid in fp.pages().items():
            print(f"  {name}  ({pid})")
        return 0

    import devices                                          # noqa: PLC0415
    import phone_queue as pq                                # noqa: PLC0415

    serial = args.serial.strip() or devices.resolve(lane="clip")
    page = args.page.strip() or next(iter(fp.pages()), "")
    if not page:
        print("ไม่รู้ว่าจะลงเพจไหน — ใส่ --page หรือเพิ่มชื่อใน data/fb_pages.json")
        return 2
    if not args.caption.strip():
        print("ต้องมีแคปชัน — ใส่ --caption")
        return 2

    with pq.slot(serial, owner="facebook_page_post",
                 task=f"โพสต์ลงเพจ {page}", lane="clip"):
        phone = g.Phone(fp.adb_path(), serial)
        got = post_to_page(phone, page, args.caption,
                           images=[Path(p) for p in args.image],
                           comments=args.comment, dry_run=args.dry_run)
    print(got)
    return 0 if (got.get("posted") or got.get("dry_run")) else 1


if __name__ == "__main__":
    sys.exit(main())
