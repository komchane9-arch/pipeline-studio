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
import fb_auto_post
import fb_profile as fp

# ช่องเขียนโพสต์บน **หน้าเพจ** เขียนคนละอย่างกับในกลุ่ม
PAGE_COMPOSER_HINTS = list(fp.COMPOSER_MARKS) + ["เขียนโพสต์", "Create post"]

# ปุ่มยืนยันหลังแนบรูปของหน้าเพจ (บางรุ่นเป็น "ถัดไป" บางรุ่นเป็น "เสร็จสิ้น")
PAGE_NEXT_HINTS = g.NEXT_HINTS

# **ของที่มีเฉพาะตอนรูปติดไปแล้วจริง** (กติกาข้อ 2.3.1)
#
# หน้าเขียนโพสต์ของเพจแนบรูปคนละแบบกับของกลุ่ม: แตะรูปในแกลเลอรีแล้ว
# **มันแนบให้เลยแล้วเด้งกลับหน้าเขียนโพสต์** ไม่ได้ค้างอยู่หน้าเลือกรูปเพื่อ
# ให้เลือกหลายใบ ตัวนับของกลุ่มที่รอดูคำว่า "สื่อที่เลือก" จึงไม่มีวันขยับ
# แล้วรายงานว่า "เลือกรูปไม่ได้" ทั้งที่รูปติดไปเรียบร้อยแล้ว
# (เจอจริง 22 ก.ย. 2569 13:20 — ผังจอตอนนั้นมีทั้ง "แก้ไขรูปภาพ" และ
#  "ลบรูปภาพออก" ซึ่งโผล่เฉพาะตอนมีรูปติดอยู่ พร้อมปุ่ม "ถัดไป")
PHOTO_ATTACHED_MARKS = ("ลบรูปภาพออก", "แก้ไขรูปภาพ", "เพิ่มสื่อ",
                        "Remove photo", "Edit photo", "Add more")

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

    **ทางที่แน่นอนที่สุดคือ เมนู → แตะชื่อตัวเองบนหัวเมนู** เพราะชื่อบนหัวเมนู
    พาไปหน้าโปรไฟล์ที่ใช้อยู่เสมอ ไม่ว่าแอปจะอยู่โหมดไหน

    ที่ไม่กดแท็บล่างขวาอย่างเดียว เพราะช่องนั้นเป็นคนละอย่างในแต่ละหน้า —
    อยู่หน้าเมนูมันคือแท็บเมนูเอง กดกี่ครั้งก็ไม่ไปไหน (เจอจริง 22 ก.ย. 2569
    กด 3 รอบแล้วยังอยู่ที่เมนูเหมือนเดิม)

    ทุกขั้นเป็นการแตะจอจริง ไม่มีการยิงลิงก์ลัดหน้า (กติกาข้อ 2.7)
    """
    # รอบก่อนอาจล้มกลางหน้าเขียนโพสต์แล้วทิ้งกล่อง "บันทึกเป็นฉบับร่าง" ไว้บัง
    # ไม่เคลียร์ก่อน ทุกการแตะจะไปโดนกล่องนั้นแทน (เจอจริง 22 ก.ย. 2569)
    phone.clear_draft_dialog()
    for attempt in range(1, tries + 1):
        xml = phone.dump()
        if on_page(xml):
            return xml

        # อยู่หน้าเมนูอยู่แล้ว → แตะชื่อบนหัวเมนูได้เลย
        name = fp.read_menu_name(xml)
        if name:
            spot = next((r for r in fp.rows(xml) if r[0].strip() == name), None)
            if spot:
                phone.log(f"  (หาหน้าเพจ รอบ {attempt}) อยู่หน้าเมนู — แตะชื่อ “{name}”")
                phone.tap((spot[1], spot[2]))
                time.sleep(PAGE_LOAD)
                continue

        # ยังไม่ใช่หน้าเมนู → เปิดเมนูก่อน (ปุ่มหาจากป้ายชื่อ ทนกว่าเดาตำแหน่ง)
        button = fp.menu_button(xml)
        if button is None:
            phone.log(f"  (หาหน้าเพจ รอบ {attempt}) หาปุ่มเมนูบนจอไม่เจอ")
            time.sleep(2.0)
            continue
        phone.log(f"  (หาหน้าเพจ รอบ {attempt}) เปิดเมนู")
        phone.tap(button)
        time.sleep(PAGE_LOAD)

    xml = phone.dump()
    if on_page(xml):
        return xml
    g.keep_failure_screen(phone, "กดกลับมาหน้าเพจไม่ได้")
    raise PageError(
        "กดกลับมาหน้าเพจไม่ได้ — ไม่เห็นช่องเขียนโพสต์กับปุ่มแอดมินพร้อมกัน "
        "(อาจโดนกล่องอะไรบังอยู่ ดูภาพหลักฐานที่เก็บไว้)")


# ------------------------------------------------------------ เขียนโพสต์

# กล่องแนะนำ "โน้ต" ที่เด้งมาบังตอนแตะพลาดไปโดนฟองโน้ต
NOTE_POPUP_MARKS = ("แชร์ความคิดของคุณด้วยโน้ต", "โน้ตจะแชร์อยู่เป็นเวลา 24 ชั่วโมง",
                    "Share what you're thinking with notes")
NOTE_CLOSE_MARKS = ("เข้าใจแล้ว", "Got it", "ปิด", "Close")
# กล่องชวนโปรโมท — **โผล่เฉพาะหลังโพสต์สำเร็จ** จึงใช้เป็นหลักฐานได้
PROMOTE_MARKS = ("เพิ่มการเข้าถึงของคุณ", "ลองโปรโมทโพสต์ของคุณ",
                 "Boost your post", "Promote post")

NOT_COMPOSER = ("โน้ต", "Note", "สตอรี่", "Story", "Reels", "ถ่ายทอดสด", "Live")


def find_composer(phone: g.Phone, xml: str) -> tuple[int, int] | None:
    """ช่องเขียนโพสต์ของเพจ — **ตัดฟองโน้ต/สตอรี่/Reels ออกก่อน**

    บนหน้าเพจมีฟอง "สร้างโน้ต: แสดงความคิดเห็น…" ลอยอยู่เหนือรูปโปรไฟล์
    แตะโดนแล้วจะเข้าหน้าเขียนโน้ต ซึ่งไม่มีปุ่มแนบรูป แล้วเด้งกล่องแนะนำโน้ตมาบัง
    (เจอจริง 22 ก.ย. 2569 14:21 — ผังจอที่เก็บไว้มีแต่กล่องแนะนำโน้ต)

    ตัวหาของกลาง (`phone.find`) เลือก "ตัวที่ตรงที่สุด" ซึ่งดีกับปุ่มทั่วไป
    แต่ที่นี่ต้องการ **ตัดตัวที่ห้ามโดนออกก่อน** ไม่ใช่จัดอันดับความใกล้เคียง
    """
    best = None
    for labels, (x1, y1, x2, y2) in g.iter_nodes(xml):
        joined = " ".join(labels)
        if any(bad in joined for bad in NOT_COMPOSER):
            continue
        if not any(hint in joined for hint in PAGE_COMPOSER_HINTS):
            continue
        point = ((x1 + x2) // 2, (y1 + y2) // 2)
        if best is None or point[1] > best[1]:      # เอาตัวที่อยู่ล่างสุด = ช่องจริง
            best = point
    return best


def dismiss_note_popup(phone: g.Phone) -> bool:
    """ปิดกล่องแนะนำโน้ตถ้ามันเด้งมา — คืน True เมื่อเจอและปิดแล้ว"""
    xml = phone.dump()
    if not any(mark in xml for mark in NOTE_POPUP_MARKS):
        return False
    phone.log("  เด้งกล่องแนะนำ “โน้ต” มาบัง — ปิดแล้วถอยกลับ")
    spot = phone.find(xml, list(NOTE_CLOSE_MARKS))
    if spot:
        phone.tap(spot)
        time.sleep(2.0)
    phone.back()
    time.sleep(2.5)
    return True


def compose(phone: g.Phone, caption: str, photo_count: int) -> None:
    """แตะช่องเขียนโพสต์ → แนบรูป → พิมพ์แคปชัน — **ยังไม่กดโพสต์**"""
    for attempt in range(1, 4):
        spot = find_composer(phone, phone.dump())
        if spot is None:
            phone.log(f"  (หาช่องเขียนโพสต์ รอบ {attempt}) ยังไม่เจอ — รออีก 4 วิ")
            time.sleep(4.0)
            continue
        phone.log(f"  แตะช่องเขียนโพสต์ของเพจ (รอบ {attempt})")
        phone.tap(spot)
        time.sleep(4.0)
        if dismiss_note_popup(phone):
            reach_page(phone)
            continue
        break
    else:
        g.keep_failure_screen(phone, "หาช่องเขียนโพสต์ของเพจไม่เจอ")
        raise PageError("หาช่องเขียนโพสต์ของเพจไม่เจอ")

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
        # **ตัดสินจากผลลัพธ์ ไม่ใช่จากตัวนับของหน้าเลือกรูป**
        # ตัวนับนั้นเป็นของหน้าเลือกหลายใบแบบกลุ่ม ซึ่งหน้าเพจไม่มี
        after = phone.dump()
        attached = any(mark in after for mark in PHOTO_ATTACHED_MARKS)
        if picked < 1 and not attached:
            g.keep_failure_screen(phone, "เลือกรูปในแกลเลอรีไม่ได้")
            raise PageError("เลือกรูปในแกลเลอรีไม่ได้ — ไม่พบรูปในหน้าเลือกรูป")
        if picked >= 1:
            phone.log(f"  เลือกรูป {picked} ใบ"
                      + ("" if picked == photo_count else f" (ขอไว้ {photo_count} ใบ)"))
        else:
            phone.log("  รูปติดไปแล้ว (หน้าเพจแนบให้ทันทีที่แตะ ไม่มีตัวนับให้ดู)")
    # **ห้ามกด "ถัดไป" ตรงนี้** — ต่างจากของกลุ่มตรงนี้จุดเดียวแต่สำคัญ
    #
    # ของกลุ่ม: หน้าเลือกรูปเป็นคนละหน้า ต้องกดถัดไปเพื่อกลับมาหน้าเขียนโพสต์
    # ของเพจ:   แตะรูปแล้วเด้งกลับมาหน้าเขียนโพสต์ให้เลย **ช่องพิมพ์อยู่ตรงนั้นแล้ว**
    #           กดถัดไปตอนนี้ = ข้ามไปหน้า "การตั้งค่าโพสต์" โดยที่ยังไม่มีแคปชัน
    # (เจอจริง 22 ก.ย. 13:31 — ผังจอที่เก็บไว้มีแต่ กลุ่มเป้าหมาย · กำหนดเวลา ·
    #  ป้าย AI ไม่มีช่องพิมพ์สักช่อง)

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

    # ปิดคีย์บอร์ดก่อนหาปุ่มถัดไป ไม่งั้นมันบังปุ่มที่ติดขอบล่างจนหายจากผังจอ
    phone.hide_keyboard()
    nxt = phone.find(phone.dump(), PAGE_NEXT_HINTS)
    if nxt is not None:
        phone.log("  กดถัดไป (ไปหน้าการตั้งค่าโพสต์)")
        phone.tap(nxt)
        time.sleep(3.0)


def press_post(phone: g.Phone, caption: str) -> None:
    """กดโพสต์แล้ว **พิสูจน์ว่าขึ้นจริง** — ไม่ใช่กดแล้วเชื่อว่าสำเร็จ"""
    # ปิดคีย์บอร์ดก่อนเสมอ ไม่งั้นปุ่มโพสต์โดนบังจนหายไปจากผังจอบนเครื่องจอเตี้ย
    phone.hide_keyboard()
    phone.log("  กดโพสต์")
    phone.tap(phone.wait_for(g.POST_HINTS, timeout=15, exact=True))
    time.sleep(AFTER_POST)

    # หาของที่ **มีเฉพาะตอนโพสต์ขึ้นแล้ว** — มีสองอย่าง รับได้ทั้งคู่
    #
    #   1. กล่องชวนโปรโมทโพสต์ — Facebook เด้งให้ **เฉพาะหลังโพสต์สำเร็จ**
    #      และมันบังหน้าเพจไว้ทั้งจอ ทำให้ข้อ 2 มองไม่เห็น (เจอจริง 22 ก.ย.
    #      14:32 — โพสต์ขึ้นจริงแล้วแต่ด่านตอบว่าไม่เห็น เพราะกล่องนี้บังอยู่)
    #   2. แคปชันของเราโผล่บนหน้าเพจ
    #
    # **ห้ามแตะ "โปรโมทโพสต์" เด็ดขาด** นั่นคือการซื้อโฆษณาด้วยเงินจริง
    probe = caption.strip()[:10]
    for attempt in range(1, 5):
        xml = phone.dump()
        if any(mark in xml for mark in PROMOTE_MARKS):
            phone.log("  ✅ Facebook เด้งกล่องชวนโปรโมทโพสต์ = โพสต์ขึ้นแล้วจริง")
            spot = phone.find(xml, ["ไม่ใช่ตอนนี้", "Not now"])
            if spot:
                phone.tap(spot)
                time.sleep(3.0)
            else:
                phone.back()
                time.sleep(2.5)
            return
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
                 photos=None, single_post: bool = False) -> dict:
    """คอมเมนต์ใต้โพสต์ของเราแล้วไลก์ทุกข้อความ — **เกิน 2 ข้อความได้**

    ตัวโพสต์กลุ่มตั้งเพดานไว้ที่ `MAX_COMMENTS` (ตอนนี้ 2) เพราะกลุ่มส่วนใหญ่
    ไม่ให้คอมเมนต์รัว ส่วนเพจเป็นของเราเอง เจ้าของจึงขอให้ใส่ได้มากกว่านั้น
    **ไม่แก้เพดานของเขา** เพราะไฟล์นั้นเป็นของสายโพสต์และเพดานนั้นมีเหตุผลของมัน
    — ยิงเป็นชุดละ 2 แทน ได้ผลเท่ากันและไม่ไปแตะกติกาของอีกสาย
    """
    texts = [str(t).strip() for t in comments if str(t or "").strip()]
    if not texts:
        return dict(g.NO_COMMENT)
    page_account = getattr(phone, "page_account", "")
    shots = g._as_photos(photos, len(texts))
    done = liked = 0
    for start in range(0, len(texts), COMMENT_CHUNK):
        chunk = texts[start:start + COMMENT_CHUNK]
        phone.log(f"  คอมเมนต์ชุดที่ {start // COMMENT_CHUNK + 1} "
                  f"({len(chunk)} ข้อความ)")
        # **เพดานคอมเมนต์ของเพจต้องนับแยกจากบัญชีคน** — ไม่งั้นตัวนับไปถามว่า
        # "สายโพสต์ใช้บัญชีไหน" ซึ่งมีสองบัญชีและระบบไม่ยอมเดา (กติกาข้อ 8)
        # แล้วล้มทั้งที่เพจไม่เกี่ยวอะไรกับโควตาของสองบัญชีนั้นเลย
        # (เจอจริง 22 ก.ย. 2569 14:47)
        with fb_auto_post.use_account(page_account or "เพจ"):
            got = g.comment_post_of(phone, caption, chunk, single_post=single_post,
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

    # **ต้องสลับไปคีย์บอร์ด ADBKeyboard ก่อนพิมพ์** ไม่งั้นข้อความที่ส่งไปหายเงียบ
    #
    # `type_text()` ส่งข้อความด้วยการ broadcast ให้คีย์บอร์ดตัวนั้นพิมพ์แทน
    # ถ้าคีย์บอร์ดที่ใช้อยู่เป็นตัวอื่น ไม่มีใครรับ broadcast — **ไม่มี error ด้วย**
    # ตัวโพสต์กลุ่มสลับไว้ที่รอบนอก (`post_to_groups`) ไฟล์นี้จึงต้องสลับเอง
    # (เจอจริง 22 ก.ย. 13:40 — พิมพ์แคปชันเสร็จแล้วช่องยังว่าง ขึ้น
    #  "คุณกำลังคิดอะไรอยู่" เป็นคำใบ้ของช่องว่างอยู่เหมือนเดิม)
    restore_ime = ""
    try:
        restore_ime = phone.use_adb_keyboard()
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
        phone.page_account = page_name          # ให้ตัวนับคอมเมนต์รู้ว่าเป็นของเพจนี้
        result["liked"] = g.like_post_of(phone, caption)
        result.update(add_comments(phone, caption, comments, comment_images))
        return result
    finally:
        if restore_ime:
            phone.restore_keyboard(restore_ime)
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
