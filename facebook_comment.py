"""คอมเมนต์ใต้โพสต์ของตัวเองในกลุ่ม Facebook พร้อมแนบรูป (ผ่าน ADB)

ทำไมเข้าโพสต์ทาง "เนื้อหาของคุณ" ไม่ใช่เลื่อนหาในฟีดกลุ่ม:
  ฟีดกลุ่มเรียงตาม "เกี่ยวข้องมากที่สุด" ไม่ใช่ล่าสุด โพสต์ของเราจึงไม่อยู่บนจอ
  หาไม่เจอทั้งที่โพสต์ขึ้นแล้ว (เจอมาแล้วตอนรอบตรวจซ้ำของตัวโพสต์)
  ส่วนหน้า จัดการโพสต์ → เนื้อหาของคุณ แสดงเฉพาะโพสต์ของเราเรียงใหม่สุดก่อน
  จึงเชื่อได้ว่าเจอแน่และเป็นโพสต์ที่ถูกต้อง
"""

from __future__ import annotations

import random
import re
import time
from pathlib import Path

from facebook_group_post import (
    FB_PACKAGE,
    MIN_GAP_SECONDS,
    Phone,
    PostError,
)

MANAGE_HINTS = ["จัดการโพสต์", "Manage posts"]
PUBLISHED_HINTS = ["เผยแพร่แล้ว", "Published"]
VIEW_IN_GROUP_HINTS = ["ดูในกลุ่ม", "View in group"]
# ชื่อปุ่มจากหน้าจอจริง (ตรวจทีละหน้าบน Facebook 2026)
# ต้องแตะ 3 ชั้นกว่าจะได้ปุ่มแนบรูป: เปิดแผงคอมเมนต์ → แตะช่องพิมพ์ → ปุ่มรูป
OPEN_COMMENTS_HINTS = ["แสดงความคิดเห็น", "Comment"]
COMMENT_FIELD_HINTS = ["เขียนความคิดเห็นสาธารณะ", "เขียนความคิดเห็น", "Write a public comment"]
CAMERA_HINTS = ["แสดงรูปภาพและวิดีโอ", "Show photos and videos"]
FIRST_PHOTO_HINTS = ["รายการที่ 1", "item 1", "Item 1"]
# ยืนยันว่ารูปยังแนบอยู่หลังยุบแถบ — ไม่เดาจากการแตะผ่าน
ATTACHED_HINTS = ["รูปภาพที่แนบไว้", "Attached photo", "ลบภาพออก"]
SEND_HINTS = ["ส่ง", "Send"]
LIKE_HINTS = ["ถูกใจ", "Like"]
LIKED_HINTS = ["ถูกใจแล้ว", "Liked", "ยกเลิกการถูกใจ"]

SCROLL_TRIES = 5
DEFAULT_GAP_RANGE = (15.0, 20.0)


def open_own_post(phone: Phone, group_id: str, caption_probe: str) -> None:
    """เปิดโพสต์ของเราในกลุ่มนี้ผ่านหน้า "เนื้อหาของคุณ" """
    phone.open_group(group_id)

    manage = phone.find(phone.dump(), MANAGE_HINTS)
    if manage is None:
        raise PostError("ไม่พบปุ่มจัดการโพสต์ในหน้ากลุ่ม")
    phone.tap(manage)
    time.sleep(6.0)

    # หมวด "เผยแพร่แล้ว" อยู่ใต้หมวด "รอดำเนินการ" ต้องเลื่อนลงก่อนถึงเห็น
    #
    # เปิดโพสต์ด้วยการ **แตะที่ตัวแคปชัน** ไม่ใช่ปุ่ม "ดูในกลุ่ม" เพราะโพสต์มีรูปใหญ่
    # ทำให้แคปชันกับปุ่มไม่เคยอยู่บนจอเดียวกัน (พิสูจน์แล้ว: เลื่อนรอบ 2 เจอแคปชัน
    # รอบ 3 เจอปุ่ม) และปุ่มของโพสต์อื่นก็ชื่อเดียวกันหมด เสี่ยงเปิดผิดโพสต์
    # เข้าโพสต์ทางปุ่ม "ดูในกลุ่ม" ไม่ใช่แตะที่แคปชัน:
    #   แตะแคปชัน → เข้าหน้าคอมเมนต์ล้วน **ไม่มีปุ่มถูกใจของโพสต์** และปัดหาไม่ได้
    #                เพราะหน้านั้นปัดลงแล้วปิด
    #   ดูในกลุ่ม  → เข้าโพสต์เต็มในบริบทกลุ่ม มีแถบ ถูกใจ/แสดงความคิดเห็น/แชร์ ครบ
    # โพสต์ของเราเป็นตัวใหม่สุดในหมวด "เผยแพร่แล้ว" ปุ่มตัวบนสุดจึงเป็นของเรา
    probe = caption_probe.strip()[:12]
    seen_ours = False
    for _ in range(SCROLL_TRIES):
        xml = phone.dump()
        if probe and probe in xml:
            seen_ours = True
        if seen_ours:
            spot = topmost(phone, xml, VIEW_IN_GROUP_HINTS)
            if spot:
                phone.tap(spot)
                time.sleep(9.0)
                if not phone.find(phone.dump(), OPEN_COMMENTS_HINTS):
                    raise PostError("กดดูในกลุ่มแล้วแต่ไม่เข้าหน้าโพสต์")
                return
        phone.run("shell", "input", "swipe", "540", "1600", "540", "700", "400")
        time.sleep(2.0)
    raise PostError("หาโพสต์ของเราในหน้าเนื้อหาของคุณไม่เจอ")


def topmost(phone: Phone, xml: str, hints: list[str]) -> tuple[int, int] | None:
    """หา node ที่ตรงเงื่อนไขและอยู่สูงสุดบนจอ (โพสต์ใหม่สุดอยู่บนสุด)"""
    best: tuple[int, int] | None = None
    for node in re.finditer(r"<node[^>]*>", xml):
        tag = node.group(0)
        labels = re.findall(r'(?:text|content-desc)="([^"]*)"', tag)
        if not any(h.lower() in v.lower() for v in labels for h in hints):
            continue
        bounds = re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', tag)
        if not bounds:
            continue
        x1, y1, x2, y2 = (int(bounds.group(i)) for i in range(1, 5))
        if x2 - x1 < 8 or y2 - y1 < 8:
            continue
        point = ((x1 + x2) // 2, (y1 + y2) // 2)
        if best is None or point[1] < best[1]:
            best = point
    return best


def comment_on_open_post(phone: Phone, text: str, image_remote: str) -> dict:
    """คอมเมนต์ใต้โพสต์ที่เปิดค้างอยู่ พร้อมแนบรูป"""
    # ต้องแตะครบ 3 ชั้น ข้ามชั้นไหนแถบปุ่มรูปก็ไม่โผล่ (เจอมาแล้ว: ข้ามชั้นกลาง
    # แล้วหาปุ่มรูปไม่เจอ เลยได้คอมเมนต์เปล่าไม่มีรูป)
    phone.log("  เปิดแผงคอมเมนต์")
    opener = phone.find(phone.dump(), OPEN_COMMENTS_HINTS)
    if opener is None:
        raise PostError("ไม่พบปุ่มแสดงความคิดเห็นใต้โพสต์")
    phone.tap(opener)
    time.sleep(4.0)

    phone.log("  แตะช่องพิมพ์")
    field = phone.find(phone.dump(), COMMENT_FIELD_HINTS)
    if field is None:
        raise PostError("ไม่พบช่องเขียนความคิดเห็น")
    phone.tap(field)
    time.sleep(3.0)

    # แนบรูปก่อนพิมพ์ — แถบเครื่องมือหุบลงหลังพิมพ์ข้อความยาว
    phone.log("  แนบรูป")
    attached = False
    camera = phone.find(phone.dump(), CAMERA_HINTS)
    if camera is not None:
        phone.tap(camera)
        time.sleep(4.0)
        first = phone.find(phone.dump(), FIRST_PHOTO_HINTS)
        if first is not None:
            phone.tap(first)
            time.sleep(3.5)
            # ต้องกด Back ยุบแถบรูปก่อน!
            #
            # ตอนแถบรูปเปิดอยู่ uiautomator จะ dump เฉพาะหน้าต่างแถบรูป
            # ช่องพิมพ์กับปุ่มส่งหายไปจาก dump ทั้งที่ยังอยู่บนจอจริง
            # ถ้าไม่ยุบ โค้ดจะหาช่องพิมพ์ไม่เจอแล้วแตะมั่ว ข้อความไม่ลงช่อง
            # (รูปที่แนบไว้ไม่หายไปด้วย ยังอยู่เป็น "รูปภาพที่แนบไว้")
            phone.back()
            time.sleep(2.5)
            attached = bool(phone.find(phone.dump(), ATTACHED_HINTS))
    if not attached:
        phone.log("  แนบรูปไม่ได้ — คอมเมนต์เฉพาะข้อความ")

    phone.log("  พิมพ์ข้อความ")
    box = phone.find(phone.dump(), COMMENT_FIELD_HINTS) or field
    phone.tap(box)
    time.sleep(2.5)
    phone.type_text(text)
    time.sleep(2.0)
    if text.strip()[:10] not in phone.dump():
        raise PostError("พิมพ์คอมเมนต์แล้วแต่ข้อความไม่ขึ้นบนจอ")

    phone.log("  ส่งคอมเมนต์")
    send = phone.find(phone.dump(), SEND_HINTS)
    if send is None:
        raise PostError("ไม่พบปุ่มส่งคอมเมนต์")
    phone.tap(send)
    time.sleep(5.0)
    return {"commented": True, "image_attached": attached}


def like_open_post(phone: Phone) -> bool:
    """กดถูกใจโพสต์ที่เปิดอยู่ — อยู่ในหน้าโพสต์เดี่ยวจึงไม่มีปัญหาหยิบผิดโพสต์

    ห้ามปัดจอหาปุ่มในหน้านี้ — หน้าโพสต์เป็น ImmersiveActivity ที่ "ปัดลงแล้วปิด"
    ปัดหาปุ่มถูกใจทีไรเด้งกลับหน้าเนื้อหาของคุณทุกที (เจอมาแล้ว)
    ถ้าปุ่มไม่อยู่บนจอก็ข้ามไป ไม่ต้องฝืน
    """
    xml = phone.dump()
    if phone.find(xml, LIKED_HINTS):
        phone.log("  ถูกใจอยู่แล้ว")
        return True
    like = phone.find(xml, LIKE_HINTS)
    if like is None:
        phone.log("  หาปุ่มถูกใจไม่เจอ")
        return False
    phone.tap(like)
    time.sleep(2.5)
    ok = bool(phone.find(phone.dump(), LIKED_HINTS))
    phone.log("  กดถูกใจแล้ว" if ok else "  กดแล้วแต่ยืนยันไม่ได้")
    return ok


def comment_on_groups(
    adb: str, serial: str, image: Path, text: str, group_ids: list[str],
    caption_probe: str, also_like: bool = True, skip_comment: bool = False,
    gap_range: tuple[float, float] = DEFAULT_GAP_RANGE,
    dry_run: bool = False, log=print,
) -> list[dict]:
    """ไล่คอมเมนต์ใต้โพสต์ของเราทีละกลุ่ม"""
    low = max(MIN_GAP_SECONDS, min(gap_range))
    high = max(low, max(gap_range))
    phone = Phone(adb, serial, log=log)
    remote = phone.push_image(image)

    original_ime = phone.use_adb_keyboard()
    results: list[dict] = []
    try:
        for index, group_id in enumerate(group_ids, start=1):
            log(f"[{index}/{len(group_ids)}] กลุ่ม {group_id}")
            entry: dict = {"group_id": group_id}
            try:
                open_own_post(phone, group_id, caption_probe)
                # คอมเมนต์ก่อนเสมอ — เป็นงานหลัก และหน้าโพสต์เปิดมาที่โซนคอมเมนต์อยู่แล้ว
                # ส่วนถูกใจเป็นของแถม ทำหลังจบแล้วค่อยลองบนจอที่เหลืออยู่
                # กดถูกใจก่อน — เข้าทาง "ดูในกลุ่ม" แถบถูกใจอยู่บนจอพอดี
                # ถ้าคอมเมนต์ก่อน หน้าจะเลื่อนไปโซนคอมเมนต์แล้วหาปุ่มถูกใจไม่เจอ
                if also_like:
                    entry["liked"] = like_open_post(phone)
                if dry_run:
                    log("  [ซ้อม] ยังไม่ส่งคอมเมนต์")
                    entry["dry_run"] = True
                elif skip_comment:
                    log("  ข้ามคอมเมนต์ (ทำไปแล้ว)")
                else:
                    entry.update(comment_on_open_post(phone, text, remote))
                log("  สำเร็จ")
            except PostError as error:
                log(f"  ล้มเหลว: {error}")
                entry["error"] = str(error)
                for _ in range(3):
                    phone.back()
            results.append(entry)
            if index < len(group_ids):
                gap = random.uniform(low, high)
                log(f"  รออีก {gap:.0f} วินาที")
                time.sleep(gap)
    finally:
        phone.restore_keyboard(original_ime)
        log("คืนคีย์บอร์ดเดิมแล้ว")
    return results
