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
    python facebook_page_post.py --caption "..." --image a.jpg            --comment "คอมเมนต์ 1" --comment "คอมเมนต์ 2"

พิสูจน์กับของจริงครบทุกขั้นแล้ว 22 ก.ย. 2569 บนเพจ "ไท คัดมาแล้วครับ":
โพสต์ขึ้น · ไลก์โพสต์ติด · คอมเมนต์ 2 ข้อความขึ้นครบพร้อมลิงก์ · ไลก์คอมเมนต์ติดทั้งคู่
· คืนโปรไฟล์กลับ Squishy Cute Club ได้

⚠️ **ยังเหลือรูที่ต้องรู้** — ด่านตรวจกติกาข้อ 2.7 (`publish_flow_check.py`) ยัง
ไม่มีคำว่า `am start` ในรายการคำต้องห้าม ทั้งโปรเจกต์จึงมีการยิงลิงก์ลัดหน้าอยู่
9 จุดโดยด่านมองไม่เห็น (ตัวโพสต์กลุ่ม 5 · ตัวสลับโปรไฟล์ 3 · publish_flow 1)
ไฟล์นี้ไม่มีสักจุด แต่ `fb_profile` ที่มันเรียกใช้มี — รายงานเจ้าของไว้แล้ว 22 ก.ย.
"""
from __future__ import annotations

import argparse
import html
import re
import sys
import time
from pathlib import Path

import facebook_group_post as g
import fb_auto_post
import fb_comment_guard
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
#
# **ทั้งหัวข้อนี้เขียนใหม่จากการไล่ทีละขั้นกับเครื่องจริง 22 ก.ย. 2569 16:25–16:41**
# (เจ้าของนั่งสั่งทีละขั้นแล้วดูผลทุกขั้น) ของเดิมยืมตัวไลก์/คอมเมนต์ของสายกลุ่ม
# มาใช้ตรงๆ แล้ว **ล้มทุกรอบ** เพราะหน้าเพจกับหน้ากลุ่มใช้ป้ายกำกับคนละชุด
# ตัวเลขในคำอธิบายข้างล่างคือค่าที่วัดได้จริงบน W4FYYPYTLFYLIFHM (720x1600)

# ปุ่มคอมเมนต์ต้องตรงเป๊ะ — บนหน้าเพจมีฟอง "สร้างโน้ต: แสดงความคิดเห็น…"
# ซึ่ง **มีคำนี้อยู่ข้างใน** ถ้าจับแบบ "มีคำนี้" จะไปโดนฟองโน้ตแทนปุ่มจริง
# (ผังจอจริง: ฟองโน้ตอยู่ [230,176][489,292] ส่วนปุ่มจริงอยู่แถวล่างของการ์ดโพสต์)
ACTION_COMMENT_EXACT = ("แสดงความคิดเห็น", "Comment")
ACTION_SHARE_MARKS = ("ปุ่มแชร์", "แชร์โพสต์", "Share post")

# ช่องพิมพ์คอมเมนต์ของ **เพจ** เขียนว่า "แสดงความคิดเห็นในชื่อ <ชื่อเพจ>"
# ซึ่งไม่ตรงกับคำที่สายกลุ่มหา (เขียนความคิดเห็น / เขียนความคิดเห็นสาธารณะ) สักคำ
COMMENT_FIELD_MARKS = ("แสดงความคิดเห็นในชื่อ", "เขียนความคิดเห็นสาธารณะ",
                       "เขียนความคิดเห็น", "Write a public comment", "Comment as")

# **ปุ่มส่งต้องตรงเป๊ะ และต้องอยู่ครึ่งล่างของจอ**
#
# เจอจริง 22 ก.ย. 16:33 — จับแบบ "มีคำว่า ส่ง" ไปโดนการ์ดสินค้า Shopee ที่เขียนว่า
# "ใหม่ พร้อมส่ง 4G/5G Wifi…" ซึ่งอยู่กลางจอ (408,570) แตะแล้ว **เด้งออกไปแอป
# Shopee ทั้งแอป** ร่างคอมเมนต์หายหมด ต้องกลับมาพิมพ์ใหม่
# ปุ่มจริงอยู่ (672,1418) — ช่องพิมพ์กับปุ่มส่งตรึงอยู่ล่างจอเสมอ
# (ตรงกับกติกาข้อ 3: ห้าม selector แบบ *="คำ" ในหน้าที่มีเนื้อหาผู้ใช้ปน)
SEND_EXACT = ("ส่ง", "Send")
SEND_MIN_RATIO = 0.6

# ปุ่มถูกใจของ **คอมเมนต์** มีป้ายกำกับ ต่างจากปุ่มถูกใจของโพสต์ที่ไม่มีเลย
COMMENT_LIKE_MARKS = ("ถูกใจปุ่มแสดงความคิดเห็นของ", "Like comment")
COMMENT_LIKED_MARKS = ("ได้มีการกดปุ่ม ถูกใจ ไปแล้ว", "Liked")
# ของที่มีเฉพาะตอนคอมเมนต์ **ส่งขึ้นไปแล้ว** — ยังอยู่ในช่องพิมพ์จะไม่มี
COMMENT_POSTED_MARKS = ("ตอบกลับความคิดเห็นของ", "เมื่อสักครู่", "Reply to")
# ของที่มีเฉพาะตอน **โพสต์ถูกไลก์แล้ว**
POST_LIKED_MARKS = ("คุณแสดงความรู้สึก", "ได้มีการกดปุ่ม ถูกใจ ไปแล้ว")

MAX_COMMENTS_PER_POST = 10      # กันวนหลุด ไม่ใช่เพดานของแพลตฟอร์ม
SCROLL_STEP = 700               # พิกัดอ้างอิง (Phone.vswipe ย่อขยายตามจอจริงให้)


# ---------------------------- ตัวอ่านผังจอ (ทดสอบได้โดยไม่ต้องมีมือถือ)

def _clickables(xml: str):
    """(ป้ายทั้งหมดของ node, กรอบ) ของทุกปุ่มที่กดได้"""
    for found in re.finditer(r'<node[^>]*clickable="true"[^>]*>', xml):
        tag = found.group(0)
        labels = [html.unescape(v).strip()
                  for v in re.findall(r'(?:text|content-desc)="([^"]*)"', tag)]
        box = re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', tag)
        if box:
            yield [label for label in labels if label], tuple(int(v) for v in box.groups())


def find_text_box(xml: str, needle: str) -> tuple[int, int, int, int] | None:
    """กรอบของ node แรกที่มีข้อความนี้ — None เมื่อไม่เจอ"""
    if not needle:
        return None
    for found in re.finditer(r'<node[^>]*>', xml):
        tag = found.group(0)
        labels = " ".join(html.unescape(v)
                          for v in re.findall(r'(?:text|content-desc)="([^"]*)"', tag))
        if needle in labels:
            box = re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', tag)
            if box:
                return tuple(int(v) for v in box.groups())
    return None


def find_action_bar(xml: str, below: int = 0) -> dict | None:
    """แถบ 👍 💬 ↗ ใต้โพสต์ — คืน {'like','comment','share','y'} หรือ None

    **ปุ่มถูกใจของโพสต์ไม่มีป้ายกำกับเลยสักตัว** (วัดจากเครื่องจริง 22 ก.ย. 16:26)
    ตัวหาปุ่มที่ค้นจากคำว่า "ถูกใจ" จึงไม่มีวันเจอ แล้วไล่เลื่อนจอหาจนโพสต์หลุดจอ
    ก่อนยอมแพ้ — นี่คือสาเหตุที่กดไลก์โพสต์ไม่ได้มาตลอดสามรอบแรก

        👍 ไม่มีชื่อ            x 0..88     ← ต้องคำนวณเอา
        💬 "แสดงความคิดเห็น"    x 88..176
        ↗  "ปุ่มแชร์ …"          x 176..264

    ปุ่มทั้งแถวกว้างเท่ากันและเรียงชิดกัน จุดกึ่งกลางของ 👍 จึงคำนวณได้จาก
    **ความกว้างของปุ่มคอมเมนต์เอง**: ขอบซ้ายของ 💬 ลบครึ่งความกว้าง
    (88 − 44 = 44 ตรงกับที่แตะแล้วติดจริง) ไม่ฝังพิกัดตายตัว ย้ายเครื่องก็ใช้ได้

    `below` = รับเฉพาะแถบที่อยู่ **ใต้** พิกัดนี้ ใช้ผูกแถบเข้ากับโพสต์ของเรา
    ตอนที่มีหลายโพสต์อยู่บนจอเดียวกัน
    """
    comments, shares = [], []
    for labels, (x1, y1, x2, y2) in _clickables(xml):
        middle = (y1 + y2) // 2
        if any(label in ACTION_COMMENT_EXACT for label in labels):
            comments.append((middle, x1, x2))
        elif any(mark in " ".join(labels) for mark in ACTION_SHARE_MARKS):
            shares.append((middle, x1, x2))
    best = None
    for middle, left, right in comments:
        if middle <= below:
            continue
        # ต้องมีปุ่มแชร์อยู่ขวามือในแถวเดียวกัน ถึงจะนับว่าเป็นแถบปุ่มของโพสต์จริง
        mate = next((s for s in shares
                     if abs(s[0] - middle) < 40 and s[1] >= right - 4), None)
        if mate is None:
            continue
        if best is None or middle < best[0]:
            width = max(1, right - left)
            best = (middle, {
                "like": (max(12, left - width // 2), middle),
                "comment": ((left + right) // 2, middle),
                "share": ((mate[1] + mate[2]) // 2, middle),
                "y": middle,
            })
    return best[1] if best else None


def find_comment_field(xml: str) -> tuple[int, int] | None:
    """ช่องพิมพ์คอมเมนต์ — None เมื่อยังไม่ได้เปิดแผงคอมเมนต์"""
    for labels, (x1, y1, x2, y2) in _clickables(xml):
        joined = " ".join(labels)
        if any(mark in joined for mark in COMMENT_FIELD_MARKS):
            return (x1 + x2) // 2, (y1 + y2) // 2
    return None


def find_send_button(xml: str, height: int) -> tuple[int, int] | None:
    """ปุ่มส่งคอมเมนต์ — **ป้ายตรงเป๊ะ และอยู่ครึ่งล่างของจอเท่านั้น**"""
    best = None
    for labels, (x1, y1, x2, y2) in _clickables(xml):
        if not any(label in SEND_EXACT for label in labels):
            continue
        middle = (y1 + y2) // 2
        if middle < height * SEND_MIN_RATIO:
            continue
        if best is None or middle > best[1]:
            best = ((x1 + x2) // 2, middle)
    return best


def find_comment_like(xml: str, below: int) -> tuple[tuple[int, int], bool] | None:
    """ปุ่มถูกใจของคอมเมนต์ตัวแรกที่อยู่ใต้พิกัดนี้ — คืน (จุดกด, ไลก์ไปแล้วไหม)

    ผูกกับ **ข้อความของคอมเมนต์นั้น** ไม่ใช่ "ปุ่มตัวแรกบนจอ" ไม่งั้นพอมีหลาย
    คอมเมนต์จะไปกดของผิดอัน และการกดซ้ำที่เดิมคือ **ยกเลิกไลก์** ไม่ใช่ไลก์เพิ่ม
    """
    best = None
    for labels, (x1, y1, x2, y2) in _clickables(xml):
        joined = " ".join(labels)
        liked = any(mark in joined for mark in COMMENT_LIKED_MARKS)
        if not liked and not any(mark in joined for mark in COMMENT_LIKE_MARKS):
            continue
        middle = (y1 + y2) // 2
        if middle <= below:
            continue
        if best is None or middle < best[0]:
            best = (middle, ((x1 + x2) // 2, middle), liked)
    return (best[1], best[2]) if best else None


def comment_probes(text: str) -> list[str]:
    """ชิ้นข้อความที่ใช้ยืนยันว่าคอมเมนต์นี้อยู่บนจอจริง

    ใช้สองชั้น: ท่อนแรกของข้อความ (ตัดอีโมจินำหน้าออก) กับ **รหัสท้ายลิงก์** ถ้ามี
    ลิงก์ย่อของ Shopee/Lazada เป็นตัวอักษรผสมตัวเลขที่ไม่ซ้ำใคร จึงเป็นหลักฐาน
    ที่ดีว่าข้อความเข้าไป **ครบ** ไม่ใช่เข้าไปแค่บรรทัดแรก
    """
    head = re.sub(r"^[^\w฀-๿]+", "", (text or "").strip())
    probes = [head.split("\n")[0][:14].strip()] if head else []
    probes += re.findall(r"/([A-Za-z0-9]{8,})", text or "")[:2]
    return [probe for probe in probes if probe]


# ------------------------------------------------------- ขับหน้าจอจริง

def scroll_to_post(phone: g.Phone, caption: str, tries: int = 10) -> dict:
    """เลื่อนหาโพสต์ของเราบนหน้าเพจจนเห็น **ทั้งแคปชันและแถบปุ่ม** — คืนแถบปุ่ม

    เห็นแคปชันอย่างเดียวยังกดอะไรไม่ได้ เพราะแถบปุ่มอาจยังอยู่ใต้ขอบจอ
    และเห็นแถบปุ่มอย่างเดียวก็ไม่ได้ เพราะไม่รู้ว่าเป็นแถบของโพสต์ไหน
    """
    probe = (caption or "").strip()[:12]
    if not probe:
        raise PageError("ไม่มีแคปชันให้ใช้เป็นหมุด — หาโพสต์ของเราไม่ได้")
    seen = False
    for attempt in range(1, tries + 1):
        xml = phone.dump()
        box = find_text_box(xml, probe)
        if box is None:
            if seen:
                phone.log(f"  (หาโพสต์ รอบ {attempt}) แคปชันหลุดจอไปแล้ว — เลื่อนกลับขึ้น")
                phone.vswipe(800, 800 + SCROLL_STEP // 2, 500)
            else:
                phone.log(f"  (หาโพสต์ รอบ {attempt}) ยังไม่เห็นแคปชัน — เลื่อนลง")
                phone.vswipe(1500, 1500 - SCROLL_STEP, 600)
            time.sleep(2.5)
            continue
        seen = True
        bar = find_action_bar(xml, below=box[3])
        if bar:
            phone.log(f"  เจอโพสต์ของเราพร้อมแถบปุ่มแล้ว (รอบ {attempt}) "
                      f"👍{bar['like']} 💬{bar['comment']}")
            return bar
        phone.log(f"  (หาโพสต์ รอบ {attempt}) เห็นแคปชันแล้วแต่แถบปุ่มยังไม่โผล่")
        phone.vswipe(1300, 1300 - SCROLL_STEP // 2, 500)
        time.sleep(2.5)
    g.keep_failure_screen(phone, "หาแถบปุ่มของโพสต์บนหน้าเพจไม่เจอ")
    raise PageError(
        "เลื่อนหาโพสต์ของเราบนหน้าเพจจนครบรอบแล้วยังไม่เห็นแถบปุ่ม 👍💬↗ "
        "— **ไม่แตะอะไรต่อ** เพราะกดมั่วอาจไปโดนโพสต์อื่น")


def like_post(phone: g.Phone, caption: str) -> bool:
    """กดถูกใจโพสต์ของเราเอง — คืน True เมื่อยืนยันได้ว่าติดจริง"""
    bar = scroll_to_post(phone, caption)
    xml = phone.dump()
    box = find_text_box(xml, caption.strip()[:12])
    low = box[1] - 200 if box else 0
    high = bar["y"] + 300
    for found in re.finditer(r'<node[^>]*>', xml):
        tag = found.group(0)
        labels = html.unescape(" ".join(
            re.findall(r'(?:text|content-desc)="([^"]*)"', tag)))
        if not any(mark in labels for mark in POST_LIKED_MARKS):
            continue
        spot = re.search(r'bounds="\[\d+,(\d+)\]\[\d+,(\d+)\]"', tag)
        if spot and low <= (int(spot.group(1)) + int(spot.group(2))) // 2 <= high:
            phone.log("  โพสต์นี้ถูกไลก์ไปแล้ว — ไม่กดซ้ำ (กดซ้ำ = ยกเลิกไลก์)")
            return True

    phone.log(f"  กดถูกใจโพสต์ที่ {bar['like']}")
    phone.tap(bar["like"])
    time.sleep(4.0)
    after = html.unescape(phone.dump())
    if any(mark in after for mark in POST_LIKED_MARKS):
        phone.log("  ✅ ไลก์ติดแล้ว (จอขึ้นว่าเราแสดงความรู้สึกไว้)")
        return True
    phone.log("  ⚠️ กดไปแล้วแต่ยังไม่เห็นร่องรอยว่าไลก์ติด — รายงานว่าไม่ติด ไม่กดซ้ำ")
    return False


def open_comments(phone: g.Phone, caption: str, tries: int = 2) -> bool:
    """แตะปุ่มคอมเมนต์เพื่อเปิดแผง — คืน True เมื่อเห็นช่องพิมพ์จริง"""
    for attempt in range(1, tries + 1):
        if find_comment_field(phone.dump()):
            return True
        bar = scroll_to_post(phone, caption)
        phone.log(f"  เปิดแผงคอมเมนต์ (รอบ {attempt})")
        phone.tap(bar["comment"])
        time.sleep(6.0)
        if find_comment_field(phone.dump()):
            phone.log("  ✅ แผงคอมเมนต์เปิดแล้ว (เห็นช่องพิมพ์)")
            return True
    g.keep_failure_screen(phone, "เปิดแผงคอมเมนต์ไม่ได้")
    return False


def write_comment(phone: g.Phone, text: str) -> bool:
    """พิมพ์คอมเมนต์หนึ่งข้อความแล้วส่ง — คืน True เมื่อยืนยันว่าขึ้นจริง

    เรียกได้เฉพาะตอนแผงคอมเมนต์เปิดอยู่แล้ว (ดู `open_comments`)
    """
    probes = comment_probes(text)
    if not probes:
        return False
    plain = html.unescape(phone.dump())
    if all(p in plain for p in probes) and any(m in plain for m in COMMENT_POSTED_MARKS):
        phone.log("  คอมเมนต์นี้มีอยู่แล้ว — ไม่ส่งซ้ำ")
        return True

    field = find_comment_field(phone.dump())
    if field is None:
        g.keep_failure_screen(phone, "หาช่องพิมพ์คอมเมนต์ไม่เจอ")
        return False
    phone.tap(field)
    time.sleep(2.5)
    phone.type_text(text)
    time.sleep(2.0)

    # **ต้องเห็นข้อความครบก่อนกดส่ง** ส่งไปครึ่งเดียวแล้วลบไม่ได้
    plain = html.unescape(phone.dump())
    missing = [p for p in probes if p not in plain]
    if missing:
        g.keep_failure_screen(phone, "พิมพ์คอมเมนต์แล้วข้อความไม่ครบบนจอ")
        phone.log(f"  ✕ ข้อความยังไม่ครบบนจอ (ขาด {missing}) — ไม่กดส่ง")
        return False

    send = find_send_button(phone.dump(), phone.size[1])
    if send is None:
        g.keep_failure_screen(phone, "หาปุ่มส่งคอมเมนต์ไม่เจอ")
        phone.log("  ✕ หาปุ่มส่งไม่เจอ — ข้อความยังอยู่ในช่อง ยังไม่ส่ง")
        return False
    phone.log(f"  กดส่งที่ {send}")
    phone.tap(send)
    time.sleep(7.0)

    after = html.unescape(phone.dump())
    posted = (all(p in after for p in probes)
              and any(m in after for m in COMMENT_POSTED_MARKS))
    phone.log("  ✅ คอมเมนต์ขึ้นแล้ว" if posted
              else "  ⚠️ กดส่งไปแล้วแต่ยังยืนยันไม่ได้ว่าขึ้น — ไม่ส่งซ้ำ")
    return posted


def like_comment(phone: g.Phone, text: str) -> bool:
    """กดถูกใจคอมเมนต์ของเราเอง — ผูกกับข้อความของคอมเมนต์นั้นโดยเฉพาะ"""
    probes = comment_probes(text)
    xml = phone.dump()
    box = next((b for b in (find_text_box(xml, p) for p in probes) if b), None)
    if box is None:
        phone.log("  ไม่เห็นคอมเมนต์นั้นบนจอ — ไม่กดถูกใจ (กันกดผิดอัน)")
        return False
    found = find_comment_like(xml, below=box[3] - 10)
    if found is None:
        phone.log("  หาปุ่มถูกใจของคอมเมนต์นั้นไม่เจอ")
        return False
    spot, already = found
    if already:
        phone.log("  คอมเมนต์นี้ถูกไลก์ไปแล้ว — ไม่กดซ้ำ")
        return True
    phone.log(f"  กดถูกใจคอมเมนต์ที่ {spot}")
    phone.tap(spot)
    time.sleep(4.0)
    again = find_comment_like(phone.dump(), below=box[3] - 10)
    if again and again[1]:
        phone.log("  ✅ ไลก์คอมเมนต์ติดแล้ว")
        return True
    phone.log("  ⚠️ กดแล้วแต่ปุ่มยังไม่เปลี่ยนสถานะ — รายงานว่าไม่ติด")
    return False


def close_comments(phone: g.Phone, tries: int = 3) -> bool:
    """ปิดแผงคอมเมนต์ด้วยการ **ปัดลง** เหมือนนิ้วคน ไม่ใช่กดย้อนกลับ

    ปัดจากขีดจับด้านบนของแผงลงไปล่างจอ — วัดจริง 22 ก.ย. 16:40 ปัดครั้งเดียวติด
    """
    width, height = phone.size
    for attempt in range(1, tries + 1):
        if find_comment_field(phone.dump()) is None:
            return True
        phone.log(f"  ปัดลงเพื่อปิดแผงคอมเมนต์ (รอบ {attempt})")
        phone.run("shell", "input", "swipe", str(width // 2), "120",
                  str(width // 2), str(int(height * 0.9)), "400")
        time.sleep(3.0)
    phone.log("  ⚠️ ปิดแผงคอมเมนต์ไม่ลง")
    return False


def add_comments(phone: g.Phone, caption: str, comments: list[str],
                 page_name: str = "") -> dict:
    """คอมเมนต์ใต้โพสต์ของเราแล้วไลก์ทุกข้อความ — **เกิน 2 ข้อความได้**

    ลำดับตามที่เจ้าของกำหนด: คอมเมนต์ 1 → ไลก์ 1 → คอมเมนต์ 2 → ไลก์ 2 → …

    **เพดานคอมเมนต์นับแยกในนามเพจ** ไม่ปนกับบัญชีคน — ไม่งั้นตัวนับจะไปถามว่า
    "สายโพสต์ใช้บัญชีไหน" ซึ่งมีสองบัญชีและระบบไม่ยอมเดา (กติกาข้อ 8) แล้วล้ม
    ทั้งที่เพจไม่เกี่ยวกับโควตาของสองบัญชีนั้นเลย (เจอจริง 22 ก.ย. 14:47)
    """
    texts = [str(t).strip() for t in comments
             if str(t or "").strip()][:MAX_COMMENTS_PER_POST]
    if not texts:
        return dict(g.NO_COMMENT)
    if not open_comments(phone, caption):
        return dict(g.NO_COMMENT)

    done = liked = 0
    with fb_auto_post.use_account(page_name or "เพจ"):
        hold = ""
        try:
            hold = fb_comment_guard.hold_reason(account=page_name or "เพจ")
        except Exception as error:                          # noqa: BLE001
            phone.log(f"  (อ่านสถานะเพดานคอมเมนต์ไม่ได้: {error} — ทำต่อ)")
        if hold:
            phone.log(f"  ⛔ ยังคอมเมนต์ไม่ได้: {hold}")
            close_comments(phone)
            return dict(g.NO_COMMENT)
        for order, text in enumerate(texts, 1):
            phone.log(f"  คอมเมนต์ที่ {order}/{len(texts)}")
            if not write_comment(phone, text):
                phone.log(f"  หยุดที่คอมเมนต์ที่ {order} — ไม่ไล่ต่อ")
                break
            done += 1
            try:
                g._note_comment_sent()
            except Exception:                               # noqa: BLE001
                pass        # ตัวนับพลาดต้องไม่ทำให้งานที่สำเร็จไปแล้วล้ม
            if like_comment(phone, text):
                liked += 1
            if order < len(texts):
                time.sleep(2.5)
    close_comments(phone)
    return {"commented": done > 0, "comment_count": done,
            "comment_liked": done > 0 and liked == done}


# ------------------------------------------------------------------ งานรวม

def post_to_page(
    phone: g.Phone, page_name: str, caption: str, images: list[Path] | None = None,
    comments: list[str] | None = None, dry_run: bool = False,
    restore_to: str = "", stop=lambda: False,
) -> dict:
    """โพสต์ลงเพจหนึ่งใบให้ครบวงจร — คืนผลว่าไปถึงขั้นไหน

    ลำดับทั้งหมดคือของที่ไล่ทีละขั้นกับเครื่องจริงแล้วผ่านทุกขั้น 22 ก.ย. 2569

        สลับเป็นเพจ → เปิดหน้าเพจ → ส่งรูปเข้าเครื่อง → แตะช่องเขียนโพสต์
        → แนบรูป → พิมพ์แคปชัน → ถัดไป → แชร์ → (กล่องชวนโปรโมท = ขึ้นแล้ว)
        → กลับหน้าเพจ → เลื่อนหาโพสต์ → ไลก์โพสต์
        → เปิดแผงคอมเมนต์ → คอมเมนต์ 1 → ไลก์ 1 → คอมเมนต์ 2 → ไลก์ 2 → …
        → ปิดแผงคอมเมนต์ → คืนคีย์บอร์ด → คืนโปรไฟล์

    `restore_to` = โปรไฟล์ที่ต้องสลับกลับหลังเสร็จ เว้นว่าง = อ่านเอาเองว่าตอนเริ่ม
    เครื่องใช้โปรไฟล์ไหนอยู่ ใส่ค่า `None` แปลว่า **ไม่ต้องสลับกลับ** (ใช้ตอน
    นั่งไล่ทีละขั้น จะได้ไม่เสียเวลารอบละ 8 นาทีกับการสลับไปกลับ)
    """
    images = [Path(p) for p in (images or [])]
    comments = list(comments or [])
    result: dict = {"page": page_name, "posted": False, "liked": False,
                    **dict(g.NO_COMMENT), "restored": ""}
    for path in images:
        if not path.is_file():
            raise PageError(f"ไม่พบไฟล์รูป {path}")

    g.require_network(phone)

    keep_profile = restore_to is not None
    before = (restore_to or "") if keep_profile else ""
    if keep_profile and not before:
        before = fp.whoami(fp.adb_path(), phone.serial, phone.log)
        if not before:
            raise PageError(
                "อ่านไม่ได้ว่าตอนนี้เครื่องใช้โปรไฟล์ไหนอยู่ — **ไม่สลับ** "
                "เพราะสลับไปแล้วจะไม่รู้ทางกลับ ต้องเข้าไปดูที่เครื่องก่อน")
        phone.log(f"  โปรไฟล์ก่อนเริ่ม: {before}")

    # **ต้องสลับไปคีย์บอร์ด ADBKeyboard ก่อนพิมพ์** ไม่งั้นข้อความที่ส่งไปหายเงียบ
    #
    # `type_text()` ส่งข้อความด้วยการ broadcast ให้คีย์บอร์ดตัวนั้นพิมพ์แทน
    # ถ้าคีย์บอร์ดที่ใช้อยู่เป็นตัวอื่น **ไม่มีใครรับ broadcast และไม่มี error ด้วย**
    # ตัวโพสต์กลุ่มสลับไว้ที่รอบนอก (`post_to_groups`) ไฟล์นี้จึงต้องสลับเอง
    # (เจอจริง 22 ก.ย. 13:40 — พิมพ์แคปชันเสร็จแล้วช่องยังว่างเปล่า)
    restore_ime = ""
    try:
        restore_ime = phone.use_adb_keyboard()
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

        # กล่องชวนโปรโมทปิดไปแล้วใน `press_post` ตอนนี้ควรอยู่หน้าเพจ
        reach_page(phone)
        result["liked"] = like_post(phone, caption)
        result.update(add_comments(phone, caption, comments, page_name=page_name))
        return result
    finally:
        if restore_ime:
            phone.restore_keyboard(restore_ime)
        # **ต้องคืนโปรไฟล์เสมอ แม้ตอนล้มกลางคัน** ค้างไว้ = งานถัดไปของสายคลิป
        # โพสต์ออกในนามเพจนี้ ซึ่งถอนไม่ได้ ต้องไปลบเองในแอป
        if keep_profile and before and not fp.same_name(before, page_name):
            try:
                result["restored"] = fp.guard(phone.serial, before, phone.log)
                phone.log(f"  คืนโปรไฟล์กลับเป็น {result['restored']} แล้ว")
            except Exception as error:                      # noqa: BLE001
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
    parser.add_argument("--stay", action="store_true",
                        help="ค้างไว้ที่เพจ ไม่ต้องสลับโปรไฟล์กลับ (ใช้ตอนไล่ทีละขั้น)")
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
                           comments=args.comment, dry_run=args.dry_run,
                           restore_to=None if args.stay else "")
    print(got)
    return 0 if (got.get("posted") or got.get("dry_run")) else 1


if __name__ == "__main__":
    sys.exit(main())
