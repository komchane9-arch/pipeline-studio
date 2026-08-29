"""โพสต์รูป + ข้อความลงกลุ่ม Facebook ทีละกลุ่มผ่าน ADB

ทำไมไม่ใช้ Graph API:
  การโพสต์ลงกลุ่มด้วย API ถูกปิดตั้งแต่ Facebook ตัด `publish_to_groups`
  ทางที่เหลือคือทำผ่านแอปบนมือถือเหมือนคนกดเอง

ทำไมหา element จากข้อความ ไม่ใช้พิกัดตายตัว:
  แอป Facebook เปลี่ยนหน้าตาบ่อยและแต่ละเครื่องความละเอียดต่างกัน พิกัดตายตัว
  พังทันทีที่อัปเดตแอป — อ่านจาก uiautomator แล้วหาปุ่มตามข้อความทนกว่ามาก

ข้อควรระวังที่บอกผู้ใช้ไปแล้ว: โพสต์ข้อความเดียวกันหลายกลุ่มติดกันเข้าข่ายสแปม
ตัวสคริปต์จึงบังคับให้มีระยะห่างระหว่างกลุ่มเสมอ (ตั้งค่าได้ ต่ำสุด 5 วินาที)
"""

from __future__ import annotations

import base64
import html
import json
import random
import re
import subprocess
import threading
import time
from pathlib import Path

import fb_comment_guard
import fb_limits
import fb_screen
import studio_shared

FB_PACKAGE = "com.facebook.katana"
REMOTE_DIR = "/sdcard/Pictures/pipeline"
ADB_KEYBOARD_IME = "com.android.adbkeyboard/.AdbIME"
# คีย์บอร์ดที่สลับไปแล้วผู้ใช้พิมพ์เองไม่ได้ — ข้ามตอนหาตัวสำรอง
SKIP_IME_HINTS = ("autofill", "kdeconnect", "remotekeyboard")

MIN_GAP_SECONDS = 5.0
# ระยะห่างแบบสุ่มระหว่างกลุ่ม — เว้นเท่ากันเป๊ะทุกครั้งเป็นรูปแบบที่ระบบกันสแปม
# มองออกง่ายกว่าเว้นไม่เท่ากัน
DEFAULT_GAP_RANGE = (15.0, 20.0)
UI_TIMEOUT = 25.0
# จำนวนรอบเปิดกลุ่ม — แต่ละรอบ force-stop แล้วเปิดใหม่ รอช่องเขียนโพสต์ 30 วินาที
OPEN_GROUP_TRIES = 3
STEP_SETTLE = 1.5

# ข้อความบนปุ่มที่ต้องกด — ใส่ทั้งไทยและอังกฤษเพราะแอปสลับภาษาตามเครื่อง
# เรียงจากเจาะจงสุดไปกว้างสุด ตัว find จะเลือกตัวที่ตรงที่สุดก่อน
# ห้ามใส่ "คุณกำลังคิดอะไรอยู่" — นั่นคือช่องเขียนโพสต์ของ**ฟีดหน้าแรก**
# ถ้าใส่ไว้ ระบบจะกดช่องนั้นแล้วโพสต์ลงไทม์ไลน์ตัวเองแทนที่จะลงกลุ่ม
COMPOSER_HINTS = ["เขียนอะไรสักหน่อย", "เขียนอะไรบางอย่าง", "Write something"]
# ในหน้าเขียนโพสต์ของกลุ่ม ปุ่มแนบรูปเขียนว่า "แกลเลอรี" ไม่ใช่ "รูปภาพ/วิดีโอ"
# (ตรวจจากหน้าจอจริงบน Facebook 2026) — ห้ามใส่ "รูปภาพ" เดี่ยวๆ เพราะไปชนกับ
# "รูปภาพหน้าปกของกลุ่ม" ที่อยู่บนสุดของหน้า
PHOTO_HINTS = ["แกลเลอรี", "Gallery", "รูปภาพ/วิดีโอ", "Photo/video"]
# วนหาปุ่มแนบรูปกี่รอบก่อนยอมแพ้ (รอบละ 1.5 วินาที) — รวมแล้วรอได้ ~12 วินาที
# พอๆ กับที่ขั้นหาช่องเขียนโพสต์รอได้ (15 วินาที) สองขั้นนี้ควรใจกว้างเท่ากัน
PHOTO_BUTTON_TRIES = 8
# รูปที่เพิ่งส่งเข้าเครื่องเป็นไฟล์ใหม่สุด จึงเป็น "รายการที่ 1" ในหน้าเลือกรูป
FIRST_PHOTO_HINTS = ["รายการที่ 1", "item 1", "Item 1"]
# แนบได้สูงสุดกี่ใบต่อโพสต์
MAX_PHOTOS = 3
# ช่องรูปในหน้าเลือกรูปมีป้ายเต็มว่า "รูปภาพ, รายการที่ N, ถ่ายเมื่อ …"
# ส่วนแถบล่างจอที่โชว์ใบที่เลือกแล้วใช้คำว่า "สื่อที่เลือก, รายการที่ K จาก K"
# ต้องแยกสองอันนี้ให้ขาด ไม่งั้นนับใบที่เลือกแล้วไปปนกับช่องในตาราง
PHOTO_CELL_PREFIX = "รูปภาพ, รายการที่"
PHOTO_PICKED_PREFIX = "สื่อที่เลือก"


def photo_cell(xml: str, number: int) -> tuple[int, int] | None:
    """ช่องรูปลำดับที่ N ในตารางเลือกรูป (ใหม่สุด = 1)"""
    for labels, (x1, y1, x2, y2) in iter_nodes(xml):
        for label in labels:
            if label.startswith(f"{PHOTO_CELL_PREFIX} {number},"):
                return ((x1 + x2) // 2, (y1 + y2) // 2)
    return None


def picked_count(xml: str) -> int:
    """จำนวนรูปที่เลือกไว้แล้ว อ่านจากแถบล่างจอ"""
    best = 0
    for labels, _ in iter_nodes(xml):
        for label in labels:
            if not label.startswith(PHOTO_PICKED_PREFIX):
                continue
            found = re.search(r"รายการที่\s*(\d+)\s*จาก", label)
            if found:
                best = max(best, int(found.group(1)))
    return best


def pick_photos(phone: Phone, count: int) -> int:
    """เลือกรูป `count` ใบล่าสุดในแกลเลอรี คืนจำนวนที่เลือกได้จริง

    แตะจากใบเก่าสุดไปใหม่สุด (รายการที่ N → 1) เพราะรูปที่ส่งเข้าเครื่องทีหลัง
    จะอยู่หน้าสุดของตาราง ถ้าแตะจากใบแรกลงไปลำดับในโพสต์จะกลับด้านกับที่ส่งมา
    """
    picked = 0
    for number in range(count, 0, -1):
        xml = phone.dump()
        cell = photo_cell(xml, number)
        if cell is None:
            phone.log(f"  ไม่พบช่องรูปที่ {number} ในแกลเลอรี")
            break
        before = picked_count(xml)
        phone.tap(cell)
        time.sleep(1.2)
        after = picked_count(phone.dump())
        if after <= before:
            phone.log(f"  แตะรูปที่ {number} แล้วแต่จำนวนที่เลือกไม่เพิ่ม")
            break
        picked = after
    return picked
# ช่องพิมพ์แคปชันหลังแนบรูป — ต้อง**แตะให้โฟกัสก่อน** ไม่งั้น ADBKeyboard
# ส่งข้อความไปแล้วไม่มีช่องไหนรับ ข้อความหายเงียบ (เจอจริง: รูปเข้าแต่แคปชันว่าง)
CAPTION_FIELD_HINTS = [
    "บอกอะไรสักหน่อยเกี่ยวกับรูปภาพ", "บอกอะไรสักหน่อย", "ชื่อโพสต์",
    "Say something about", "เขียนอะไรสักหน่อย",
]
# กล่อง "ต้องการโพสต์ให้เสร็จในภายหลังหรือไม่" ที่โผล่เมื่อมีฉบับร่างค้างอยู่
# ต้องกด "ทิ้งโพสต์" เสมอ — ถ้ากดบันทึกร่างไว้ รอบหน้าจะเจอกล่องนี้ซ้ำไม่จบ
DRAFT_DIALOG_HINTS = ["ต้องการโพสต์ให้เสร็จในภายหลัง", "Finish your post later"]
DISCARD_HINTS = ["ทิ้งโพสต์", "Discard post", "ทิ้ง", "Discard"]
# แตะช่องแคปชันแล้วแอปเปิดหน้า "เพิ่มข้อความ" แยกออกมา ต้องกด "เรียบร้อย"
# กลับเข้าหน้าเขียนโพสต์ก่อน ไม่งั้นปุ่มโพสต์ยังไม่โผล่
CAPTION_DONE_HINTS = ["เรียบร้อย", "Done", "เสร็จสิ้น"]
POST_HINTS = ["โพสต์", "Post", "แชร์", "Share"]
NEXT_HINTS = ["ถัดไป", "Next", "เสร็จสิ้น", "Done", "เสร็จ"]
# ปุ่มถูกใจ กับสถานะหลังกดแล้ว — ใช้ตัวหลังยืนยันว่ากดติดจริง ไม่ใช่เดา
LIKE_HINTS = ["ถูกใจ", "Like"]
# ป้ายที่บอกว่า "โพสต์นี้เรากดถูกใจไปแล้ว" — ตรวจจากหน้าจอจริงของแอปรุ่นนี้:
#   ปุ่ม     : content-desc = "ได้มีการกดปุ่ม ถูกใจ ไปแล้ว แตะสองครั้ง…"
#   แถวสรุป : "คุณแสดงความรู้สึก"   ← ไม่มีตัวเลขนำหน้าเมื่อมีแค่เราคนเดียว
# ที่ผ่านมาไล่หาแต่คำว่า "ถูกใจแล้ว" ซึ่ง**ไม่มีอยู่จริงในแอปนี้** เลยรายงานว่า
# กดไม่ติดทุกครั้งทั้งที่ติดแล้ว
LIKED_HINTS = [
    "ได้มีการกดปุ่ม ถูกใจ ไปแล้ว", "คุณแสดงความรู้สึก",
    "ถูกใจแล้ว", "Liked", "ยกเลิกการถูกใจ", "Remove Like",
]
POST_SETTLE_SECONDS = 12.0      # รอโพสต์ขึ้นฟีดก่อนไปหาปุ่มถูกใจ
# สัญญาณว่าอยู่หน้ากลุ่มจริง ไม่ใช่ฟีดหน้าแรกของแอป
GROUP_PAGE_HINTS = ["กลุ่มสาธารณะ", "กลุ่มส่วนตัว", "เข้าร่วมแล้ว", "Public group", "Private group", "Joined"]

# ปุ่ม "..." มุมขวาบนของโพสต์ กับเมนูคัดลอกลิงก์ที่เด้งขึ้นมา
POST_MENU_HINTS = [
    "ตัวเลือกเพิ่มเติม", "การดำเนินการกับโพสต์นี้", "ดูตัวเลือกเพิ่มเติม",
    "More options", "Actions for this post",
]
COPY_LINK_HINTS = ["คัดลอกลิงก์", "คัดลอกลิงค์", "Copy link"]
# เมนูชั้นแรกของบางโพสต์ไม่มี "คัดลอกลิงก์" ต้องกด "ตัวเลือกเพิ่มเติม" เข้าไปอีกชั้น
# (ตรวจจากหน้าจอจริง: ชั้นแรก = สนใจ/ไม่สนใจ/บันทึกโพสต์/รายงาน/ตัวเลือกเพิ่มเติม)
MORE_OPTIONS_HINTS = ["ตัวเลือกเพิ่มเติม", "More options", "ดูเพิ่มเติม", "See more"]


def _plain(value: str) -> str:
    """ถอด entity ของ XML กลับเป็นตัวอักษรจริง

    `uiautomator dump` คาย **XML ดิบ** อักขระที่ XML แปลความหมายพิเศษ และอักขระ
    นอก BMP (อีโมจิทั้งหมด) ถูกเขียนเป็น entity:

        🔥            → `&#128293;`
        &             → `&amp;`
        ขึ้นบรรทัดใหม่ → `&#10;`

    ส่วนภาษาไทยไม่โดนแปลง จึงเทียบตรงๆ ได้มาตลอดจนไม่มีใครสังเกต

    เอาข้อความที่ผู้ใช้พิมพ์ไปเทียบกับ XML ดิบจึงไม่มีทางเจอถ้ามีอักขระพวกนี้ปน
    **เจอจริง 13 ส.ค. งาน p617465263**: คอมเมนต์ขึ้นต้นด้วย 🔥 → ด่าน
    "พิมพ์คอมเมนต์แล้วแต่ข้อความไม่ขึ้นบนจอ" ตีกลับครบทั้ง 5 กลุ่ม
    ทั้งที่ข้อความอยู่ในช่องเรียบร้อยแล้ว คอมเมนต์เลยค้างไม่ได้ส่งสักอัน
    """
    return html.unescape(value) if "&" in value else value


def screen_has(xml: str, probe: str) -> bool:
    """ข้อความนี้โผล่บนจอไหม — ถอด entity ก่อนเทียบเสมอ

    ใช้แทนการเขียน `probe in xml` ตรงๆ ทุกที่ ไม่งั้นข้อความที่มีอีโมจิหรือ &
    จะถูกตัดสินว่า "ไม่อยู่บนจอ" ทั้งที่อยู่
    """
    return bool(probe) and probe in _plain(xml)


def iter_nodes(xml: str):
    """ไล่ node ทั้งหมดพร้อมป้ายข้อความและกรอบ — ใช้ร่วมกันทุกที่ที่ต้องอ่านหน้าจอ"""
    for node in re.finditer(r"<node[^>]*>", xml):
        tag = node.group(0)
        labels = [
            _plain(value).strip()
            for value in re.findall(r'(?:text|content-desc)="([^"]*)"', tag)
            if value.strip()
        ]
        bounds = re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', tag)
        if not labels or not bounds:
            continue
        box = tuple(int(bounds.group(i)) for i in range(1, 5))
        if box[2] - box[0] < 8 or box[3] - box[1] < 8:
            continue          # ข้าม node เล็กจิ๋วที่กดไม่โดน
        yield labels, box


class PostError(RuntimeError):
    """โพสต์ไม่สำเร็จ"""


class Phone:
    """คำสั่ง ADB ที่ใช้ซ้ำ รวมไว้ที่เดียว"""

    def __init__(self, adb: str, serial: str, log=print) -> None:
        self.adb = adb
        self.serial = serial
        self.log = log
        # ตัวนับกันชื่อไฟล์ซ้ำตอนส่งรูป + จำชื่อล่าสุดของแต่ละรูปไว้ลบใบเก่าทิ้ง
        self._push_seq = 0
        self._pushed: dict[str, str] = {}
        # **ปลุกจอก่อนเสมอ** — ตรงนี้คือทางผ่านเดียวของทุกงานที่ขับแอป Facebook
        # (งานโพสต์ · ตามเก็บ · เก็บยอด · แก้รูป · ลบโพสต์ · บอทตอบคอมเมนต์)
        # คุมที่นี่ที่เดียวจึงครบทุกทาง ไม่ต้องไปไล่ใส่ทีละจุดแล้วลืมบางจุด
        #
        # จอเปิดอยู่แล้วเสียแค่คำสั่งเดียว (~0.1 วิ) จอดับอยู่เสีย ~1.3 วิ
        fb_screen.wake(self.shell, log=self.log)

    def run(self, *args: str, timeout: float = 30) -> subprocess.CompletedProcess:
        # ซ่อนหน้าต่างคอนโซล — จุดนี้คือทางผ่านของคำสั่ง ADB **ทุกคำสั่ง**
        # โพสต์ 1 กลุ่มยิงหลายร้อยครั้ง (dump() เปิด 2 หน้าต่างต่อการอ่านจอ 1 ครั้ง)
        # ไม่ซ่อน = หน้าต่างดำกะพริบรัวทั้งวันและแย่งโฟกัสจนพิมพ์งานอื่นไม่ได้
        return subprocess.run(
            [self.adb, "-s", self.serial, *args],
            capture_output=True, timeout=timeout,
            creationflags=studio_shared.NO_WINDOW,
        )

    # ---- ขนาดจอจริง + การเลื่อนจอที่ย่อขยายตามจอ ----
    #
    # **เหตุการณ์ที่ทำให้ต้องมี 28 ส.ค. 2569** ย้ายงานโพสต์มาเครื่องใหม่
    # (REDMI 15C 720x1600) แล้วโพสต์ขึ้นครบ 6 กลุ่มแต่ **คอมเมนต์ไม่ลงสักกลุ่ม**
    # เพราะคำสั่งเลื่อนจอเขียนพิกัดตายตัวไว้ว่าเริ่มลากที่ y=1800 ซึ่งเป็นพิกัด
    # ของ Xiaomi (1080x2400) — บนจอสูง 1600 ตำแหน่งนั้น **อยู่นอกจอ** เลื่อนไม่ติด
    # หาปุ่มคอมเมนต์จึงไม่เจอทุกครั้ง แล้วข้ามไปเงียบๆ ว่า "โพสต์สำเร็จ"
    #
    # ผิดกติกา CLAUDE.md ข้อ 2.7 ที่เขียนไว้เองว่า "พิกัดห้ามฝังตายในโค้ด"
    # มีแบบนี้ 14 จุดในไฟล์เดียว — แก้ทีละจุดก็ลืมจุดใดจุดหนึ่งอยู่ดี
    # จึงรวมมาไว้ที่ทางผ่านเดียว แล้วให้ตัวเลขเดิมเป็น "พิกัดอ้างอิง" ที่ย่อขยายเอง
    REF_W, REF_H = 1080, 2400      # จอที่ใช้ตอนจูนตัวเลขพวกนี้ (Xiaomi 11T pro)

    @property
    def size(self) -> tuple[int, int]:
        """(กว้าง, สูง) ของจอเครื่องนี้ — ถามครั้งเดียวแล้วจำไว้"""
        cached = getattr(self, "_size", None)
        if cached:
            return cached
        size = (self.REF_W, self.REF_H)
        try:
            found = re.search(r"(\d+)x(\d+)", self.shell("wm size"))
            if found:
                size = (int(found.group(1)), int(found.group(2)))
        except Exception:
            pass          # ถามไม่ได้ก็ใช้จออ้างอิง ดีกว่าล้มทั้งงาน
        self._size = size
        return size

    def hide_keyboard(self, tries: int = 2) -> bool:
        """ปิดคีย์บอร์ดถ้ามันขึ้นอยู่ — คืน True เมื่อปิดแล้วจริง

        **เหตุการณ์ที่ทำให้ต้องมี 28 ส.ค. 2569** บนจอ 720x1600 พอพิมพ์แคปชันเสร็จ
        คีย์บอร์ดยังค้างอยู่ แล้ว **ปุ่ม "โพสต์" หายไปจากผังจอทั้งอัน** เพราะมันอยู่
        ติดขอบล่าง (y≈1504 จากจอสูง 1600) คีย์บอร์ดกินพื้นที่ตรงนั้นไปหมด

        ผลคือบอทหาปุ่มไม่เจอครบ 15 วินาทีแล้วล้ม ทั้งที่กดเองด้วยมือได้ปกติ
        จอ Xiaomi 1080x2400 ไม่เป็นเพราะสูงพอให้ปุ่มยังโผล่อยู่ — บั๊กนี้จึงโผล่
        เฉพาะตอนย้ายมาเครื่องจอเล็ก

        ใช้ BACK เพราะเป็นวิธีเดียวที่ปิดคีย์บอร์ดได้ทุกยี่ห้อ **แต่ต้องเช็คก่อนว่า
        คีย์บอร์ดขึ้นอยู่จริง** ไม่งั้น BACK จะกลายเป็นการถอยออกจากหน้าเขียนโพสต์
        แล้วเด้งกล่อง "บันทึกเป็นฉบับร่างหรือทิ้งโพสต์" ซึ่งเสียงานทั้งใบ
        """
        for _ in range(max(1, tries)):
            try:
                shown = "mInputShown=true" in self.shell(
                    "dumpsys input_method | grep mInputShown")
            except Exception:
                return False
            if not shown:
                return True
            self.run("shell", "input", "keyevent", "KEYCODE_BACK")
            time.sleep(1.2)
        return False

    def to_ref_y(self, y: float) -> float:
        """แปลงพิกัดแนวตั้ง**ที่อ่านมาจากหน้าจอจริง** ให้เป็นพิกัดอ้างอิง

        ต้องมีเพราะ `vswipe()` รับพิกัดอ้างอิงเสมอ ถ้าเอาค่าที่อ่านจากผังจอ
        (ซึ่งเป็นพิกัดจริงของเครื่องนั้น) ยัดเข้าไปตรงๆ มันจะโดนย่อซ้ำอีกรอบ
        — บนจอ 720x1600 จะเลื่อนได้แค่ 2 ใน 3 ของที่ตั้งใจ แล้วเลื่อนไม่ถึงปุ่ม
        (เจอตอนตรวจซ้ำ 28 ส.ค. 2569 ก่อนยิงทดสอบจริง)
        """
        return float(y) * self.REF_H / max(1, self.size[1])

    def vswipe(self, y_from, y_to, ms=None, x_ref: int = 540) -> None:
        """เลื่อนจอแนวตั้ง — **รับพิกัดบนจออ้างอิง 1080x2400 แล้วย่อขยายให้ตรงจอจริง**

        ตัวเลขที่ส่งเข้ามาเป็นค่าที่จูนไว้กับจอ Xiaomi ไม่ใช่พิกัดจริงของเครื่องนี้
        """
        width, height = self.size
        fx = width / self.REF_W
        fy = height / self.REF_H
        # กันหลุดขอบจอ — เลื่อนต้องอยู่ในจอทั้งจุดเริ่มและจุดจบ ไม่งั้นไม่มีอะไรเกิดขึ้น
        clamp = lambda v: max(1, min(height - 1, int(round(float(v) * fy))))
        self.run(
            "shell", "input", "swipe",
            str(max(1, min(width - 1, int(round(x_ref * fx))))), str(clamp(y_from)),
            str(max(1, min(width - 1, int(round(x_ref * fx))))), str(clamp(y_to)),
            str(int(ms if ms is not None else SCROLL_DURATION_MS)),
        )

    def shell(self, command: str, timeout: float = 30) -> str:
        result = self.run("shell", command, timeout=timeout)
        return result.stdout.decode("utf-8", errors="replace")

    # ------------------------------------------------------------- หน้าจอ

    def dump(self) -> str:
        """อ่านลำดับชั้น UI ปัจจุบัน"""
        self.shell(f"uiautomator dump {REMOTE_DIR}/ui.xml >/dev/null 2>&1")
        return self.shell(f"cat {REMOTE_DIR}/ui.xml")

    def find(self, xml: str, texts: list[str]) -> tuple[int, int] | None:
        """หาจุดกึ่งกลางของ node ที่ข้อความ (หรือ content-desc) ตรงกับตัวใดตัวหนึ่ง

        เลือก **ตัวที่ตรงที่สุด** ไม่ใช่ตัวแรกที่เจอ: ป้ายที่เท่ากันเป๊ะชนะป้ายที่
        แค่มีคำนั้นอยู่ข้างใน และคำที่อยู่ต้นรายการชนะคำที่อยู่ท้าย
        (เจอจริง: หา "รูปภาพ" แล้วไปโดน "รูปภาพหน้าปกของกลุ่ม" ที่อยู่บนสุดของหน้า)
        """
        best: tuple[int, tuple[int, int]] | None = None
        for labels, (x1, y1, x2, y2) in iter_nodes(xml):
            for order, hint in enumerate(texts):
                low = hint.lower()
                for label in labels:
                    name = label.lower()
                    if name == low:
                        score = order * 10          # ตรงเป๊ะ ดีสุด
                    elif name.startswith(low):
                        score = order * 10 + 3
                    elif low in name:
                        score = order * 10 + 6
                    else:
                        continue
                    point = ((x1 + x2) // 2, (y1 + y2) // 2)
                    if best is None or score < best[0]:
                        best = (score, point)
                    break
        return best[1] if best else None

    def find_exact(self, xml: str, texts: list[str]) -> tuple[int, int] | None:
        """หาเฉพาะ node ที่ป้าย **ตรงเป๊ะ** — ไม่รับ "กล่องที่มีคำนั้นอยู่ข้างใน"

        **ทำไมต้องแยกจาก `find()` 28 ส.ค. 2569** `find()` ยอมรับป้ายที่แค่มีคำนั้น
        อยู่ข้างในด้วย ซึ่งดีเวลาหาของที่ชื่อไม่แน่นอน แต่**อันตรายมากกับปุ่มที่กด
        แล้วย้อนไม่ได้** อย่างปุ่มโพสต์

        วัดจริงบนหน้าเขียนโพสต์ที่มีข้อความแล้ว: ปุ่มจริงอยู่ (610,1504)
        แต่ `find()` คืน (211,794) ซึ่งเป็นกล่องอื่นที่บังเอิญมีคำว่า "โพสต์"
        อยู่ในคำอธิบาย — กดไปแล้วไปโดนกล่อง "บันทึกเป็นฉบับร่างหรือทิ้งโพสต์"
        แล้วเสียงานทั้งใบโดยไม่มีอะไรเตือนว่ากดผิดปุ่ม
        """
        best: tuple[int, tuple[int, int]] | None = None
        for labels, (x1, y1, x2, y2) in iter_nodes(xml):
            for order, hint in enumerate(texts):
                low = hint.lower()
                for label in labels:
                    if label.lower().strip() != low:
                        continue
                    point = ((x1 + x2) // 2, (y1 + y2) // 2)
                    if best is None or order < best[0]:
                        best = (order, point)
                    break
        return best[1] if best else None

    def wait_for(self, texts: list[str], timeout: float = UI_TIMEOUT,
                 exact: bool = False) -> tuple[int, int]:
        """รอจนเจอปุ่มที่ต้องการ — ไม่ใช้ sleep ตายตัวเพราะแอปโหลดช้าเร็วไม่แน่นอน

        `exact=True` = รับเฉพาะป้ายที่ตรงเป๊ะ ใช้กับปุ่มที่กดผิดแล้วเสียงานทั้งใบ
        ล้มพร้อมบอกว่าเห็นป้ายอะไรอยู่บนจอบ้าง จะได้ไล่ต่อได้โดยไม่ต้องเดา
        """
        deadline = time.time() + timeout
        last = ""
        while time.time() < deadline:
            last = self.dump()
            found = (self.find_exact(last, texts) if exact
                     else self.find(last, texts))
            if found:
                return found
            time.sleep(1.0)
        near = self.find(last, texts) if exact else None
        extra = f" (เจอกล่องที่มีคำนี้อยู่ข้างในที่ {near} แต่ไม่ใช่ปุ่มจริง)" if near else ""
        raise PostError(f"หาปุ่มไม่เจอภายในเวลา: {texts[0]}{extra}")

    def tap(self, point: tuple[int, int]) -> None:
        self.run("shell", "input", "tap", str(point[0]), str(point[1]))
        time.sleep(STEP_SETTLE)

    def open_group(self, group_id: str) -> None:
        """เปิดหน้ากลุ่มให้แน่ใจว่าไปถึงจริง

        ต้อง force-stop ก่อนทุกครั้ง เพราะถ้าแอปเปิดค้างอยู่ deep link จะแค่ดึงแอป
        ขึ้นมาที่หน้าเดิม (ฟีดหน้าแรก) ไม่ได้พาเข้ากลุ่ม — เจอมาแล้วตอนกลุ่มที่สอง
        """
        self.log(f"เปิดกลุ่ม {group_id}")
        self.clear_draft_dialog()
        self.shell(f"am force-stop {FB_PACKAGE}")
        time.sleep(1.5)
        self.run(
            "shell", "am", "start", "-a", "android.intent.action.VIEW",
            # ต้องใช้ fb:// — ลิงก์ https เด้งหน้าเลือกแอปแทนที่จะเข้าแอปตรงๆ
            "-d", f"fb://group/{group_id}", timeout=30,
        )
        # สัญญาณเดียวที่เชื่อได้ว่า "อยู่หน้ากลุ่มแล้ว" คือช่องเขียนโพสต์ของกลุ่ม
        # ("เขียนอะไรสักหน่อย") เพราะ:
        #   - ฟีดหน้าแรกใช้คำว่า "คุณกำลังคิดอะไรอยู่" คนละคำ แยกออกชัด
        #   - "กลุ่มสาธารณะ"/"เข้าร่วมแล้ว" ใช้ไม่ได้ ไปตรงกับการ์ดกลุ่มแนะนำ
        #     ที่โผล่บนฟีดหน้าแรก แล้วนึกว่าถึงกลุ่มแล้วทั้งที่ยังไม่ถึง
        # ถ้ารอบแรกไม่เข้า ยิง deep link ซ้ำอีกรอบ (แอปเปิดเย็นบางทีค้างที่ฟีด)
        for attempt in range(OPEN_GROUP_TRIES):
            deadline = time.time() + 30
            while time.time() < deadline:
                time.sleep(2.0)
                xml = self.dump()
                # กล่องฉบับร่างโผล่ "หลัง" แอปเปิดใหม่ ไม่ใช่ก่อน จึงต้องดักตรงนี้ด้วย
                # ไม่ใช่เคลียร์แค่ตอนก่อน force-stop
                if self.find(xml, DRAFT_DIALOG_HINTS):
                    self.clear_draft_dialog()
                    continue
                if self.find(xml, COMPOSER_HINTS):
                    time.sleep(1.0)
                    return
            if attempt >= OPEN_GROUP_TRIES - 1:
                break
            # ต้อง force-stop ก่อนยิงซ้ำ **ทุกครั้ง** ไม่ใช่แค่ครั้งแรก
            #
            # ของเดิมยิง deep link ซ้ำเฉยๆ ซึ่งขัดกับกฎที่เขียนไว้ข้างบนเอง:
            # แอปเปิดค้างอยู่แล้ว deep link จะแค่ดึงแอปขึ้นมาหน้าเดิม ไม่พาไปไหน
            # วัดจาก log จริง 11 ส.ค.: ยิงซ้ำแบบเดิมกู้คืนได้ **0 จาก 4 ครั้ง**
            self.log(f"  ยังไม่เข้ากลุ่ม — ปิดแอปแล้วเปิดใหม่ (รอบ {attempt + 2})")
            self.clear_draft_dialog()
            self.shell(f"am force-stop {FB_PACKAGE}")
            time.sleep(2.5)          # เผื่อเครื่องร้อน/แบตต่ำ ปิดแอปช้ากว่าปกติ
            self.run(
                "shell", "am", "start", "-a", "android.intent.action.VIEW",
                "-d", f"fb://group/{group_id}", timeout=30,
            )
        raise PostError("เปิดหน้ากลุ่มไม่สำเร็จ — ไม่เจอช่องเขียนโพสต์ของกลุ่ม")

    def clear_draft_dialog(self) -> bool:
        """เคลียร์กล่องถามเรื่องฉบับร่างที่ค้างจากรอบก่อน

        ถ้าไม่เคลียร์ กล่องนี้จะบังหน้ากลุ่มไว้ทั้งรอบถัดไป แล้วทุกอย่างพังตาม
        """
        for _ in range(2):
            xml = self.dump()
            if not self.find(xml, DRAFT_DIALOG_HINTS):
                return False
            discard = self.find(xml, DISCARD_HINTS)
            if discard is None:
                return False
            self.log("  เจอฉบับร่างค้าง — ทิ้งทิ้ง")
            self.tap(discard)
            time.sleep(1.5)
        return True

    def back(self) -> None:
        self.run("shell", "input", "keyevent", "KEYCODE_BACK")
        time.sleep(1.0)

    def online(self) -> bool:
        """มือถือต่อเน็ตได้จริงไหม — ไม่ใช่แค่ "เปิด Wi-Fi ค้างไว้"

        ต้องเช็คของจริง เพราะ Wi-Fi เปิดอยู่แต่หลุด AP ก็ยังรายงานว่า `wifi_on=1`
        (เจอจริง 9 ส.ค.: Wi-Fi เปิด แต่ Supplicant DISCONNECTED · เน็ตมือถือปิด ·
         สัญญาณ OUT_OF_SERVICE) ผลคืองานที่ตั้งเวลาไว้ไล่โพสต์ครบ 6 กลุ่ม
        รายงานสำเร็จหมด แต่**ไม่มีโพสต์ไหนขึ้นจริงเลย** — เพราะหน้าเขียนโพสต์ของ
        Facebook ทำงานออฟไลน์ได้ครบทุกขั้น กด "โพสต์" แล้วแอปรับไว้เข้าคิวส่งทีหลัง
        ระบบเราเห็นว่ากดผ่านทุกปุ่มจึงนับว่าสำเร็จ

        ถือว่าออฟไลน์ต่อเมื่อ**ทั้งสองทางล้ม** — บางเครือข่ายบล็อก ICMP ping ไม่ผ่าน
        ทั้งที่เน็ตใช้ได้ จึงมีตัวสำรองไว้ ไม่งั้นจะไปบล็อกงานที่ยิงได้จริง
        """
        try:
            out = self.shell("ping -c 1 -W 2 8.8.8.8", timeout=15)
            if "0% packet loss" in out or "1 received" in out:
                return True
        except subprocess.SubprocessError:
            pass
        try:
            state = self.shell("dumpsys connectivity", timeout=25)
        except subprocess.SubprocessError:
            return False
        for line in state.splitlines():
            if "Active default network" in line:
                return "none" not in line.lower()
        return False

    # ------------------------------------------------------------ พิมพ์ไทย

    def normal_keyboard(self) -> str:
        """คีย์บอร์ดปกติตัวแรกที่ **เปิดใช้อยู่** (ไม่นับ ADBKeyboard)

        ต้องใช้ `ime list -s` ห้ามใส่ `-a`: `-a` รวมตัวที่ยังไม่ได้เปิดใช้มาด้วย
        แล้วสั่งสลับไปตัวที่ปิดอยู่จะเงียบไปเฉยๆ มือถือยังค้างที่ ADBKeyboard
        """
        for line in self.shell("ime list -s").splitlines():
            name = line.strip()
            if not name or ADB_KEYBOARD_IME in name:
                continue
            if any(hint in name.lower() for hint in SKIP_IME_HINTS):
                continue
            return name
        return ""

    def use_adb_keyboard(self) -> str:
        """สลับไป ADBKeyboard คืนคีย์บอร์ดเดิมไว้คืนค่าทีหลัง"""
        original = self.shell(
            "settings get secure default_input_method"
        ).strip()
        listing = self.shell("ime list -a -s")
        if ADB_KEYBOARD_IME not in listing:
            raise PostError(
                "ไม่มี ADBKeyboard บนเครื่องนี้ — พิมพ์ข้อความไทยอัตโนมัติไม่ได้"
            )
        # ค้างเป็น ADBKeyboard อยู่แล้วจากรอบก่อนที่คืนค่าไม่สำเร็จ
        # ถ้าจำค่านี้ไว้ "คืนค่า" จะกลายเป็นการตั้งกลับไปเป็น ADBKeyboard เหมือนเดิม
        # แล้วมือถือจะพิมพ์เองไม่ได้ตลอดไป (เจอจริง — ผู้ใช้ต้องมาถามว่าปิดยังไง)
        if not original or original == ADB_KEYBOARD_IME:
            original = self.normal_keyboard()
        self.shell(f"ime enable {ADB_KEYBOARD_IME}")
        self.shell(f"ime set {ADB_KEYBOARD_IME}")
        time.sleep(1.2)
        return original

    def restore_keyboard(self, original: str) -> None:
        """คืนคีย์บอร์ดเดิม แล้ว**ตรวจว่าคืนสำเร็จจริง**

        เดิมแค่ยิงคำสั่งแล้วบอกว่า "คืนแล้ว" โดยไม่ตรวจ พอคืนไม่สำเร็จ log จึงบอกว่า
        เรียบร้อยทั้งที่มือถือยังค้างที่ ADBKeyboard พิมพ์เองไม่ได้
        """
        target = original if original and original != ADB_KEYBOARD_IME else self.normal_keyboard()
        if not target:
            self.log("  หาคีย์บอร์ดปกติในเครื่องไม่เจอ — ยังค้างที่ ADBKeyboard")
            return
        self.shell(f"ime set {target}")
        time.sleep(1.0)
        now = self.shell("settings get secure default_input_method").strip()
        if now == ADB_KEYBOARD_IME:
            self.log(f"  คืนคีย์บอร์ดไม่สำเร็จ — ยังเป็น ADBKeyboard (ตั้งใจตั้งเป็น {target})")
        else:
            self.log(f"  คืนคีย์บอร์ดเป็น {now} แล้ว")

    def type_text(self, text: str) -> None:
        """ส่งข้อความเป็น base64 — รองรับไทย/อีโมจิ ไม่ติดปัญหา quote ในเชลล์"""
        encoded = base64.b64encode(text.encode("utf-8")).decode("ascii")
        self.shell(f'am broadcast -a ADB_INPUT_B64 --es msg "{encoded}"')
        time.sleep(1.0)

    # -------------------------------------------------------------- รูปภาพ

    def push_image(self, local: Path) -> str:
        """ส่งรูปเข้าเครื่อง **ด้วยชื่อใหม่ทุกครั้ง** แล้วเก็บกวาดชื่อเก่าทิ้ง

        ทำไมต้องเปลี่ยนชื่อไฟล์ทุกครั้ง — เรื่องนี้วัดกับเครื่องจริงแล้ว (13 ส.ค.):

        ตัวเลือกรูปของแอปเรียงช่องตาม **`_id` ของ MediaStore** ซึ่งเป็นลำดับตอนที่
        ไฟล์ถูกเพิ่มเข้าฐาน**ครั้งแรก** ไม่ใช่เวลาไฟล์:

            _id=729  p594651692-c1.jpg  แก้ไขล่าสุด 14:55  → ช่องที่ 1
            _id=728  p594651692-1.jpg   แก้ไขล่าสุด 15:26  → ช่องที่ 2  ← ใหม่กว่าแต่อยู่หลัง

        `push` ทับไฟล์ชื่อเดิมเป็นการ **update แถวเดิม** `_id` ไม่ขยับ รูปจึงไม่เลื่อน
        มาช่องแรกไม่ว่าจะ `touch` กี่ครั้ง — และแม้จะสั่งลบแถวทิ้งก่อนแล้ว push ใหม่
        ก็ยังได้ `_id` เดิมกลับมา (ลองแล้ว: ได้ 728 เท่าเดิม) เพราะ MediaStore ผูก
        `_id` ไว้กับ path

        พอเปลี่ยนชื่อไฟล์ ได้ `_id=731` แล้วขึ้นช่องแรกทันที

        **นี่คือรากของบั๊กรูปโพสต์ผิด**: รูปคอมเมนต์ถูกเพิ่มเข้าฐานทีหลังรูปโพสต์
        `_id` จึงสูงกว่าตลอดกาล กลุ่มที่ 2 เป็นต้นไปเลยแนบรูปคอมเมนต์เป็นรูปโพสต์
        (งาน p594651692 — ผิด 5 จาก 6 กลุ่ม)
        """
        self.shell(f"mkdir -p {REMOTE_DIR}")
        self._push_seq += 1
        stem, suffix = local.stem, local.suffix or ".jpg"
        remote = f"{REMOTE_DIR}/{stem}__{int(time.time())}{self._push_seq:02d}{suffix}"
        result = self.run("push", str(local), remote, timeout=180)
        if result.returncode != 0:
            raise PostError(
                f"ส่งรูปเข้ามือถือไม่สำเร็จ: "
                f"{result.stderr.decode('utf-8', errors='replace')[:150]}"
            )
        # ดันเวลาไฟล์เป็น "เดี๋ยวนี้" ก่อนสั่งสแกน — adb push รักษา mtime ของต้นทาง
        # (ตัวเรียงช่องไม่ได้ใช้ mtime แต่ที่อื่นในแอปใช้ เก็บไว้ให้ตรงกัน)
        self.shell(f"touch {remote}")
        self.shell(
            f"content call --uri content://media --method scan_file --arg {remote}"
        )
        time.sleep(1.5)
        # ทิ้งใบเก่าของรูปเดียวกัน ไม่งั้นแกลเลอรีผู้ใช้รกขึ้นเรื่อยๆ ทุกกลุ่มที่โพสต์
        old = self._pushed.get(local.name)
        if old and old != remote:
            self.shell(f"rm -f {old}")
            self.shell(
                f"content call --uri content://media --method scan_file --arg {old}"
            )
        self._pushed[local.name] = remote
        self.log(f"ส่งรูปเข้าเครื่องแล้ว: {remote}")
        return remote


# ปุ่มถูกใจของ "คอมเมนต์" ก็มีคำว่าถูกใจ ต้องแยกออกเวลาหาปุ่มของตัวโพสต์
COMMENT_LIKE_MARK = "ความคิดเห็น"


def post_like_buttons(xml: str) -> list[tuple[int, int]]:
    """ปุ่มถูกใจ **ของตัวโพสต์** เท่านั้น (ตัดของคอมเมนต์ออก)"""
    found = []
    for labels, (x1, y1, x2, y2) in iter_nodes(xml):
        text = " ".join(labels)
        if COMMENT_LIKE_MARK in text:
            continue
        low = text.lower()
        if not any(hint.lower() in low for hint in LIKE_HINTS):
            continue
        if any(hint.lower() in low for hint in LIKED_HINTS):
            continue
        if re.search(r"\d", low):
            continue
        found.append(((x1 + x2) // 2, (y1 + y2) // 2))
    return sorted(found, key=lambda point: point[1])


def post_liked(xml: str) -> bool:
    """โพสต์ (ไม่ใช่คอมเมนต์) ถูกใจไปแล้วหรือยัง — ใช้บนหน้าโพสต์เดี่ยว"""
    for labels, _ in iter_nodes(xml):
        text = " ".join(labels)
        if COMMENT_LIKE_MARK in text:
            continue
        if any(hint in text for hint in LIKED_HINTS):
            return True
    return False


def push_images(phone: Phone, images: list[Path]) -> int:
    """ส่งรูปทุกใบเข้าเครื่อง **เรียงทีละใบ** คืนจำนวนที่ส่งสำเร็จ

    ต้องส่งทีละใบตามลำดับ เพราะแกลเลอรีเรียงตามเวลาไฟล์ ใบที่ส่งทีหลังจะอยู่
    หน้าสุด — ตอนเลือกเราจึงแตะย้อนจากใบเก่าไปใหม่เพื่อให้ลำดับในโพสต์ตรงกับ
    ลำดับที่ผู้ใช้ส่งมา
    """
    pushed = 0
    for image in images:
        phone.push_image(image)
        pushed += 1
        time.sleep(1.0)
    return pushed


# ถาม MediaStore ว่าตัวเลือกรูปจะเรียงช่องยังไง
#
# **ต้องเรียงด้วย `_id` ไม่ใช่ `date_modified`** — วัดกับเครื่องจริงแล้ว ตัวเลือกรูป
# เรียงตามลำดับที่ไฟล์ถูกเพิ่มเข้าฐาน (`_id`) ไม่ใช่เวลาไฟล์ ไฟล์ที่ mtime ใหม่กว่า
# แต่ `_id` ต่ำกว่าจะอยู่ช่องหลัง (ดูรายละเอียดใน Phone.push_image)
#
# และต้องถาม MediaStore ไม่ใช่ `ls` โฟลเดอร์ของเรา เพราะตัวเลือกรูปเห็นรูป
# **ทั้งเครื่อง** (กล้อง · ภาพจับหน้าจอ · ดาวน์โหลด) โฟลเดอร์เราเป็นแค่ส่วนหนึ่ง
MEDIA_NEWEST_QUERY = (
    "content query --uri content://media/external/images/media "
    "--projection _data --sort '_id DESC' | head -n {count}"
)


def newest_media_names(phone: Phone, count: int) -> list[str]:
    """ชื่อไฟล์รูปที่จะไปอยู่ช่องที่ 1..count ของตัวเลือกรูป (เรียงตามช่อง)"""
    out = phone.shell(MEDIA_NEWEST_QUERY.format(count=max(1, count)), timeout=60)
    names = []
    for line in out.splitlines():
        found = re.search(r"_data=(\S+)", line.strip())
        if found:
            names.append(found.group(1).rstrip(",").rsplit("/", 1)[-1])
    return names


def ensure_images_newest(phone: Phone, images: list[Path]) -> None:
    """ยืนยันว่าช่องแรกๆ ของตัวเลือกรูปคือรูปที่เราเพิ่งส่ง ก่อนไปแตะเลือก

    ทำไมต้องมีด่านนี้: ตัวเลือกรูปแตะได้แค่ "ช่องที่ N" ระบุไฟล์ตรงๆ ไม่ได้เลย
    โค้ดทั้งไฟล์จึงตั้งอยู่บนสมมติฐานว่า **"ช่องแรก = ใบที่เราเพิ่งส่งเข้าไป"**

    สมมติฐานนี้พังมาแล้วสองแบบ:
      1. รูปคอมเมนต์ถูกส่งแทรกทุกกลุ่ม → กลุ่มที่ 2 เป็นต้นไปแนบรูปคอมเมนต์
      2. ส่งรูปโพสต์ทับชื่อเดิมก็ไม่ช่วย เพราะ `_id` ไม่ขยับ (ดู push_image)

    ตรวจไม่ผ่าน = **หยุด** ดีกว่าปล่อยให้โพสต์รูปผิดลงกลุ่มจริง
    """
    want = [
        phone._pushed.get(image.name, image.name)
        for image in images if image.name
    ]
    if not want:
        return                      # โพสต์ข้อความล้วน ไม่มีรูปให้ตรวจ
    want = [name.rsplit("/", 1)[-1] for name in want]
    got = newest_media_names(phone, len(want))
    if sorted(got) == sorted(want):
        return
    raise PostError(
        f"ช่องแรกของตัวเลือกรูปไม่ใช่รูปของโพสต์นี้ "
        f"(เจอ {got or 'ไม่เจออะไรเลย'} · ต้องเป็น {want}) — "
        "หยุดก่อนแนบรูปผิดใบ"
    )


def like_buttons(xml: str) -> list[tuple[int, int]]:
    """ปุ่ม "ถูกใจ" ที่**ยังไม่ได้กด** ทั้งหมดบนจอ เรียงจากบนลงล่าง

    ต้องตัดป้าย "ถูกใจแล้ว" ออก ไม่งั้นจะไปกดยกเลิกไลก์ที่กดไว้แล้ว
    และตัดตัวนับอย่าง "ถูกใจ 12 คน" ที่กดแล้วเปิดรายชื่อคนกด ไม่ได้กดไลก์
    """
    found: list[tuple[int, int]] = []
    for labels, (x1, y1, x2, y2) in iter_nodes(xml):
        text = " ".join(labels).lower()
        if not any(hint.lower() in text for hint in LIKE_HINTS):
            continue
        if any(hint.lower() in text for hint in LIKED_HINTS):
            continue
        if re.search(r"\d", text):        # มีตัวเลข = ตัวนับ ไม่ใช่ปุ่มกด
            continue
        found.append(((x1 + x2) // 2, (y1 + y2) // 2))
    return sorted(found, key=lambda point: point[1])


def _caption_box(xml: str, caption: str) -> tuple[int, int] | None:
    """ขอบบน-ล่างของข้อความโพสต์ของเราบนจอ (None = ไม่เห็นโพสต์)"""
    probe = caption.strip()[:12]
    if not probe:
        return None
    for labels, (_, y1, _, y2) in iter_nodes(xml):
        if any(probe in label for label in labels):
            return y1, y2
    return None


def _caption_bottom(xml: str, caption: str) -> int | None:
    box = _caption_box(xml, caption)
    return box[1] if box else None


# จำนวนรีแอคชันใต้โพสต์ เช่น "1 ความรู้สึก" / "37 ความรู้สึก, ความคิดเห็น 63 รายการ"
#
# ตัวนับนี้คือ**สัญญาณเดียวที่เชื่อได้**ว่าไลก์ติด เพราะแอปรุ่นนี้ไม่เปลี่ยนป้ายปุ่ม
# เป็น "ถูกใจแล้ว" เลย (ตรวจของจริง: กดแล้วตัวนับขึ้นเป็น 1 แต่ปุ่มยังเขียน "ถูกใจ"
# และ selected ยังเป็น false) — ที่ผ่านมาจึงรายงานว่าไลก์ไม่ติดทุกครั้งทั้งที่ติดแล้ว
REACTION_RE = re.compile(r"(\d+)\s*(?:ความรู้สึก|reaction)", re.I)
# "คุณแสดงความรู้สึก" = มีแค่เราคนเดียวที่กด ตัวเลขไม่ขึ้น ให้ถือว่านับได้ 1
SELF_REACTION_HINT = "คุณแสดงความรู้สึก"


def reaction_count(xml: str, top: int, span: int = 2000) -> int | None:
    """จำนวนรีแอคชันของโพสต์ที่เริ่มจากจุดนี้ลงไป (None = ยังไม่มีแถวตัวนับ)

    วัดจาก**ข้อความของโพสต์**ลงไป ไม่ใช่จากปุ่มที่กด เพราะพอกดถูกใจแล้วแถบด้านล่าง
    ขยับ (แถวตัวนับโผล่/ยืด) ถ้าวัดจากปุ่มจะหาไม่เจอในรอบตรวจ แล้วสรุปผิดว่าไม่ติด
    """
    best: tuple[int, int] | None = None
    for labels, (_, y1, _, _) in iter_nodes(xml):
        if y1 < top or y1 > top + span:
            continue
        joined = " ".join(labels)
        found = REACTION_RE.search(joined)
        if not found and SELF_REACTION_HINT not in joined:
            continue
        value = int(found.group(1)) if found else 1
        if best is None or y1 < best[0]:
            best = (y1, value)
    return best[1] if best else None


def liked_near(xml: str, top: int, span: int = 400) -> bool:
    """มีป้าย "ถูกใจแล้ว" ในช่วง y ที่กำหนดไหม

    ใช้ยืนยันหลังกด: ดูเฉพาะแถวรอบๆ ปุ่มที่เพิ่งกด ไม่ใช่ทั้งจอ ไม่งั้นจะไปนับ
    ไลก์ของโพสต์อื่นที่อยู่บนจอเดียวกัน แล้วรายงานว่าสำเร็จทั้งที่ไม่
    """
    for labels, (_, y1, _, _) in iter_nodes(xml):
        if y1 < top or y1 > top + span:
            continue
        if any(hint.lower() in " ".join(labels).lower() for hint in LIKED_HINTS):
            return True
    return False


LIKE_SCROLL_TRIES = 5


def _liked_in_post(xml: str, caption: str) -> bool:
    """โพสต์ของเราถูกใจไปแล้วหรือยัง — ดูเฉพาะในเขตของโพสต์นี้

    ต้องเช็ค **ก่อน** ไปหาปุ่ม เพราะพอกดถูกใจแล้ว แอปจะไม่มี node "ถูกใจ" แยกอีก
    เหลือแต่ป้าย "ได้มีการกดปุ่ม ถูกใจ ไปแล้ว" — ถ้าไล่หาปุ่มก่อนจะได้ว่างเปล่า
    แล้วสรุปผิดว่า "หาปุ่มไม่เจอ" ทั้งที่ความจริงคือถูกใจไปแล้ว
    """
    box = _caption_box(xml, caption)
    if box is None:
        return False
    limit = box[1] + POST_REGION_HEIGHT
    for header in post_headers(xml):
        if header > box[1]:
            limit = min(limit, header)      # หัวโพสต์ถัดไป = สุดเขตของโพสต์เรา
            break
    return liked_near(xml, box[1], span=max(0, limit - box[1]))
# แถบปุ่มของโพสต์หนึ่งอยู่ห่างจากข้อความไม่เกินความสูงรูป — เกินกว่านี้คือของโพสต์ถัดไป
POST_REGION_HEIGHT = 2000
# แถวตัวนับรีแอคชันอยู่ "ติดเหนือ" แถบปุ่มเสมอ (ตรวจจริง: ตัวนับ y=2128 ปุ่ม y=2265)
REACTION_GAP = 300


def _post_reactions(xml: str, like_y: int) -> int | None:
    """ตัวนับรีแอคชันของโพสต์ที่มีปุ่มถูกใจอยู่ที่ y นี้

    ต้องดูแค่ช่วงแคบๆ เหนือปุ่ม **ห้ามกวาดทั้งหน้าจอ** ไม่งั้นไปเจอตัวนับของโพสต์อื่น
    แล้วสรุปผิด (เจอจริง: โพสต์ที่เพิ่งลง 30 วินาที ได้ตัวเลข 31 มาจากโพสต์ข้างๆ
    แล้วรายงานเข้า Telegram ว่าถูกใจแล้วทั้งที่ยังไม่ได้กด)
    """
    return reaction_count(xml, max(0, like_y - REACTION_GAP), span=REACTION_GAP)


# หัวโพสต์ของแต่ละโพสต์ — ใช้เป็นเส้นแบ่งว่า "โพสต์ถัดไปเริ่มตรงไหน"
POST_HEADER_HINTS = ["ตัวเลือกเพิ่มเติมสำหรับโพสต์", "Actions for this post"]
# ความเร็วเลื่อน: ต่ำกว่านี้แอปจะตีเป็นการสะบัด (fling) แล้วเลื่อนเกินที่สั่ง
# วัดจริงแล้ว: สั่ง 600px ที่ 400ms เลื่อนจริง 746px · ที่ 900ms เลื่อนจริง 616px
SCROLL_DURATION_MS = 900
SCROLL_STEP = 700
# เขตที่แตะแล้วเข้าจริง — ล่างสุดของจอเป็นแถบปุ่มระบบ (ย้อนกลับ/หน้าหลัก) ซึ่งกินการแตะไป
# เจอจริง: ปุ่มถูกใจอยู่ y=2234 บนจอสูง 2400 แตะแล้วไม่มีอะไรเกิดขึ้นเลย
SAFE_TAP_TOP = 260
SAFE_TAP_MARGIN = 400
# หน้าโพสต์เดี่ยวใช้เขตกันแตะแคบกว่าฝั่งฟีด เพราะแถบปุ่มอยู่ต่ำกว่าแต่**แตะติดจริง**
#
# วัดจากจอจริง (9 ส.ค.): แถบปุ่ม y=2008-2123 · ช่องคอมเมนต์ y=2144-2250
# บนจอที่ screen_bottom=2253 — ช่องคอมเมนต์อยู่ต่ำกว่าปุ่มถูกใจอีก แต่แตะติดทุกครั้ง
# (คอมเมนต์ลงจริงครบทุกกลุ่ม) แปลว่าพื้นที่แตะได้ลงไปถึงอย่างน้อย y=2250
#
# ใช้ค่า 400 ของฝั่งฟีดกับหน้านี้ = ตัดปุ่มที่ y=2065 ทิ้งทุกครั้ง แล้วเลื่อนก็ไม่ช่วย
# เพราะโพสต์รูปเดียวสั้น เลื่อนแล้วปุ่มไม่ขยับ → ขึ้น "หาปุ่มถูกใจไม่เจอ" 100%
# ทั้งที่ปุ่มอยู่กลางจอ (เจอจริงในรอบตามเก็บ 5 กลุ่ม พลาดครบทั้ง 5)
SINGLE_POST_TAP_MARGIN = 120


def screen_bottom(xml: str) -> int:
    """ความสูงจอจากกรอบของ node ที่ล่างสุด"""
    bottom = 0
    for _, (_, _, _, y2) in iter_nodes(xml):
        bottom = max(bottom, y2)
    return bottom or 2400


def post_headers(xml: str) -> list[int]:
    """ตำแหน่ง y ของหัวโพสต์ทุกอันบนจอ เรียงจากบนลงล่าง"""
    tops = []
    for labels, (_, y1, _, _) in iter_nodes(xml):
        joined = " ".join(labels)
        if any(hint in joined for hint in POST_HEADER_HINTS):
            tops.append(y1)
    return sorted(tops)


def _own_like_button(xml: str, caption: str, scrolled: bool) -> tuple[int, int] | None:
    """ปุ่มถูกใจ "ของโพสต์เรา" บนจอตอนนี้ (None = ยังชี้ไม่ได้แน่ชัด)

    สองกรณี:
      ก. ยังเห็นข้อความของเรา → ปุ่มต้องอยู่ใต้ข้อความในระยะหนึ่งโพสต์
      ข. เลื่อนจนข้อความหลุดขอบบนไปแล้ว → ส่วนที่เหลือของโพสต์เราอยู่บนสุดของจอ
         ปุ่มของเราคือตัวที่อยู่ **เหนือหัวโพสต์ถัดไป** (หัวโพสต์เป็นเส้นแบ่งชัดเจน)
         ถ้าไม่มีหัวโพสต์ให้อ้างอิงเลย = ชี้ไม่ได้ ต้องไม่เดา
    """
    buttons = like_buttons(xml)
    if not buttons:
        return None
    box = _caption_box(xml, caption)
    if box is not None:
        inside = [p for p in buttons if box[1] <= p[1] <= box[1] + POST_REGION_HEIGHT]
        return inside[0] if inside else None
    if not scrolled:
        return None                     # ไม่เคยเห็นข้อความเลย ห้ามเดา
    headers = post_headers(xml)
    if not headers:
        return None
    above = [p for p in buttons if p[1] < headers[0]]
    return above[0] if above else None


STABLE_TOLERANCE = 12       # px ที่ยอมให้ขยับได้ถือว่า "นิ่งแล้ว"
STABLE_WAIT = 1.2


def _stable_like_button(phone: Phone, caption: str, scrolled: bool):
    """ตำแหน่งปุ่มถูกใจที่ **นิ่งแล้วจริง** พร้อม xml ล่าสุด

    ต้องอ่านสองรอบให้ได้ตำแหน่งเดิมก่อนถึงจะกด — ฟีดยังโหลดรูปอยู่ตลอด
    เนื้อหาด้านบนขยายตัวแล้วดันทุกอย่างเลื่อน ระหว่าง "อ่านตำแหน่ง" กับ "แตะ"
    ขยับไปได้เป็นร้อย px (วัดจริง: เลือกไว้ y=1400 พอแตะจริงปุ่มไปอยู่ y=1277
    แล้ว y=1400 กลายเป็นรูปโปรไฟล์ของโพสต์ถัดไป — แตะไปก็ไม่มีอะไรเกิดขึ้น)
    """
    first_xml = phone.dump()
    first = _own_like_button(first_xml, caption, scrolled)
    if first is None:
        return None, first_xml
    time.sleep(STABLE_WAIT)
    second_xml = phone.dump()
    second = _own_like_button(second_xml, caption, scrolled)
    if second is None or abs(second[1] - first[1]) > STABLE_TOLERANCE:
        phone.log("  หน้าจอยังขยับอยู่ — รอให้นิ่งก่อน")
        return None, second_xml
    return second, second_xml


# ป้ายของปุ่ม "แสดงความคิดเห็น" ในแถบปุ่มของโพสต์ — ใช้เป็นหมุดหาปุ่มถูกใจ
COMMENT_BUTTON_LABELS = ("แสดงความคิดเห็น", "Comment")
# ปุ่มในแถบเดียวกันมีขอบบน-ล่างตรงกัน เผื่อคลาดไว้เล็กน้อย
ROW_TOLERANCE = 20


def iter_widgets(xml: str):
    """ไล่ node ทุกตัว **รวมตัวที่ไม่มีป้าย** พร้อมบอกว่ากดได้ไหม

    ต่างจาก iter_nodes ที่ตัด node ไร้ป้ายทิ้งตั้งแต่ต้น ซึ่งใช้กับปุ่มถูกใจ
    ของหน้าโพสต์เดี่ยวไม่ได้เลยเพราะปุ่มนั้นไม่มีป้ายอะไรติดมาสักอย่าง
    """
    for node in re.finditer(r"<node[^>]*>", xml):
        tag = node.group(0)
        bounds = re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', tag)
        if not bounds:
            continue
        box = tuple(int(bounds.group(i)) for i in range(1, 5))
        if box[2] - box[0] < 8 or box[3] - box[1] < 8:
            continue
        labels = [
            _plain(value).strip()
            for value in re.findall(r'(?:text|content-desc)="([^"]*)"', tag)
            if value.strip()
        ]
        yield labels, box, 'clickable="true"' in tag


def action_bar_like_button(xml: str) -> tuple[int, int] | None:
    """ปุ่มถูกใจในแถบปุ่มของโพสต์ — หาจาก**ตำแหน่ง** ไม่ใช่จากป้าย

    บนหน้าโพสต์เดี่ยว ปุ่มถูกใจไม่มีป้ายอะไรเลยทั้ง text และ content-desc
    (ตรวจจากจอจริง: x=0-360 y=1725-1840 clickable=true class=Button labels=[])
    ตัวหาปุ่มเดิมไล่จากคำว่า "ถูกใจ" จึงไม่มีทางเจอ ไม่ว่าจะเลื่อนกี่รอบ —
    /followup เลยกดถูกใจพลาดครบทุกกลุ่ม ทั้งที่ปุ่มอยู่กลางจอ

    ในฟีดแอปใส่ป้าย "ถูกใจ" มาให้ แต่หน้าโพสต์เดี่ยวไม่ใส่ จึงต้องยึดปุ่ม
    "แสดงความคิดเห็น" ที่มีป้ายเสมอเป็นหมุด แล้วเอาปุ่มที่กดได้ตัวที่อยู่
    แถวเดียวกันและชิดซ้ายของหมุดที่สุด

    เทียบป้ายแบบ**ตรงเป๊ะ** ห้ามใช้ substring เพราะปุ่มของคอมเมนต์ชื่อ
    "ถูกใจปุ่มแสดงความคิดเห็นของ <ชื่อ>" ซึ่งมีคำเดียวกันอยู่ข้างใน
    """
    anchor = None
    for labels, box, clickable in iter_widgets(xml):
        if not clickable:
            continue
        if any(label in COMMENT_BUTTON_LABELS for label in labels):
            if anchor is None or box[1] < anchor[1]:
                anchor = box
    if anchor is None:
        return None
    ax1, ay1, _, ay2 = anchor
    best = None
    for _, box, clickable in iter_widgets(xml):
        if not clickable or box[2] > ax1:
            continue
        if abs(box[1] - ay1) > ROW_TOLERANCE or abs(box[3] - ay2) > ROW_TOLERANCE:
            continue
        if best is None or box[0] > best[0]:     # ตัวที่ชิดหมุดที่สุด
            best = box
    if best is None:
        return None
    return ((best[0] + best[2]) // 2, (best[1] + best[3]) // 2)


def like_single_post(phone: Phone) -> bool:
    """กดถูกใจบน "หน้าโพสต์เดี่ยว" — ทั้งหน้าคือโพสต์ของเราอยู่แล้ว

    ไม่ต้องใช้แคปชันเป็นหมุดเหมือนตอนอยู่ในฟีด และ**ห้ามใช้** ด้วย เพราะพอเลื่อน
    หาปุ่มไปสองสามรอบแคปชันจะหลุดขอบบน แล้วตรรกะที่ผูกกับแคปชันจะตันทันที
    (เจอจริง: เลื่อน 5 รอบแล้วขึ้น "ชี้ปุ่มถูกใจของโพสต์นี้ไม่ได้" ทั้งที่ปุ่มอยู่ตรงนั้น)
    """
    for attempt in range(3):
        xml = phone.dump()
        if post_liked(xml):
            phone.log("  โพสต์นี้ถูกใจอยู่แล้ว")
            return True
        buttons = post_like_buttons(xml)
        # ปุ่มไร้ป้ายในแถบปุ่ม — ทางเดียวที่ใช้ได้บนหน้าโพสต์เดี่ยว
        anchored = action_bar_like_button(xml)
        if anchored is not None and anchored not in buttons:
            buttons.append(anchored)
            buttons.sort(key=lambda point: point[1])
        safe_low = screen_bottom(xml) - SINGLE_POST_TAP_MARGIN
        usable = [p for p in buttons if SAFE_TAP_TOP <= p[1] <= safe_low]
        if usable:
            phone.tap(usable[0])
            time.sleep(2.5)
            if post_liked(phone.dump()):
                phone.log("  กดถูกใจแล้ว")
                return True
            phone.log("  กดแล้วแต่ยืนยันไม่ได้")
            return False
        if buttons:
            phone.log(f"  ปุ่มอยู่นอกเขตที่แตะเข้า (y={buttons[0][1]}) — เลื่อนก่อน")
        else:
            phone.log("  ยังไม่เห็นแถบปุ่ม — เลื่อนหา")
        phone.vswipe("1800", str(1800 - SCROLL_STEP), str(SCROLL_DURATION_MS),
        )
        time.sleep(2.0)
    phone.log("  หาปุ่มถูกใจในหน้าโพสต์ไม่เจอ")
    return False


def like_post_of(phone: Phone, caption: str, single_post: bool = False) -> bool:
    """กดถูกใจ "โพสต์ที่มีแคปชันนี้" โดยเจาะจง

    กติกาที่ต้องรักษาไว้:
      1. ชี้ปุ่มของโพสต์เราไม่ได้ = **ไม่แตะอะไรเลย** ดีกว่าไปกดของคนอื่น
      2. ตัวนับรีแอคชันอ่านจากช่วงติดเหนือปุ่มนั้นเท่านั้น (กวาดกว้างจะได้เลขของคนอื่น)
      3. เลื่อนช้าๆ ด้วย duration 900ms — เร็วกว่านี้แอปตีเป็นการสะบัดแล้วเลื่อนเกิน
         จนโพสต์เราหลุดจอ (วัดจริง: สั่ง 600 เลื่อนไป 746)
      4. **เลื่อนจนโพสต์เราหลุดจอไปแล้ว = หยุด ห้ามกดต่อ** (เพิ่ม 29 ส.ค. 2569)

    ข้อ 4 มาจากของจริงที่หลุดไปแล้ว — 29 ส.ค. 13:56 น. ระบบไป**กดถูกใจโพสต์
    ขายตึกของคนอื่น** ในกลุ่มที่เพิ่งโพสต์เสร็จ เจ้าของเห็นเองบนจอมือถือ

    ที่เป็นแบบนั้นเพราะด่านกันกดผิดโพสต์เดิมเขียนว่า `if not scrolled and ...`
    คือ **ตรวจเฉพาะรอบแรกก่อนเลื่อน** พอเลื่อนแล้วด่านถูกข้ามทุกรอบ ระบบจึง
    เลื่อนหาปุ่มไปเรื่อยๆ 4 รอบ (700px x 4 = 2,800px) แล้วเจอปุ่มของใครก็กด

    ลำดับจริงจาก log:
        13:56:04  ไม่มีเมนูคัดลอกลิงก์ — เลื่อนหาแล้วไม่เจอ
        13:56:08  แถบปุ่มยังไม่โผล่ — เลื่อนช้าๆ 700px      (ซ้ำ 4 รอบ)
        13:56:44  กดถูกใจแล้ว                                <- โพสต์คนอื่น
        13:57:05  เลื่อนกลับมาเจอโพสต์ของเราแล้ว            <- เพิ่งเจอ หลังกดไปแล้ว

    สังเกตว่าตัวคอมเมนต์มีด่านนี้อยู่แล้วและทำงานถูกต้อง ("ไม่เห็นข้อความโพสต์
    ของเราบนจอ — ไม่คอมเมนต์") ขาดแค่ตัวกดถูกใจตัวเดียว
    """
    if single_post:
        return like_single_post(phone)
    scrolled = False
    seen_caption = False        # เคยเห็นข้อความของเราบนจอแล้วหรือยัง
    since_seen = 0              # เลื่อนมากี่รอบแล้ว นับจากรอบที่เห็นครั้งสุดท้าย
    for attempt in range(LIKE_SCROLL_TRIES + 1):
        target, xml = _stable_like_button(phone, caption, scrolled)
        here = _caption_box(xml, caption) is not None
        if not here and attempt == 0:
            time.sleep(2.5)         # ฟีดอาจยังโหลดไม่เสร็จ ให้โอกาสอีกรอบ
            target, xml = _stable_like_button(phone, caption, scrolled)
            here = _caption_box(xml, caption) is not None
        if here:
            seen_caption = True
            since_seen = 0
        elif seen_caption:
            since_seen += 1

        if not seen_caption:
            phone.log("  ไม่เห็นข้อความโพสต์ของเราบนจอ — ไม่กดถูกใจ (กันกดผิดโพสต์)")
            return False
        # **เลื่อนเลยโพสต์เราไปแล้ว** — ปุ่มที่เห็นตอนนี้เป็นของโพสต์อื่นแน่นอน
        # ยอมให้เกินได้ 1 รอบ เพราะตอนข้อความเพิ่งหลุดขอบบน ปุ่มของเราก็ยังอยู่
        # เหนือหัวโพสต์ถัดไป ซึ่ง `_own_like_button` ชี้ได้ถูกจริง
        if since_seen > 1:
            phone.log("  เลื่อนจนโพสต์ของเราหลุดจอไปแล้ว — ไม่กดถูกใจ (กันกดผิดโพสต์)")
            return False

        if _liked_in_post(xml, caption):
            phone.log("  โพสต์นี้ถูกใจอยู่แล้ว")
            return True

        # ปุ่มอยู่ในเขตที่แตะไม่เข้า (ชนแถบระบบล่างจอ / แถบบน) — เลื่อนก่อนค่อยกด
        if target is not None:
            safe_low = screen_bottom(xml) - SAFE_TAP_MARGIN
            if not (SAFE_TAP_TOP <= target[1] <= safe_low):
                phone.log(f"  ปุ่มอยู่นอกเขตที่แตะเข้า (y={target[1]}) — เลื่อนก่อน")
                target = None
        if target is not None:
            before = _post_reactions(xml, target[1])
            phone.tap(target)
            time.sleep(2.5)
            after_xml = phone.dump()
            if liked_near(after_xml, max(0, target[1] - 250), span=500):
                phone.log("  กดถูกใจแล้ว")
                return True
            # ป้ายปุ่มไม่เปลี่ยนในแอปรุ่นนี้ — ดูตัวนับรีแอคชันว่าเพิ่มขึ้นจริงไหม
            moved, after_xml = _stable_like_button(phone, caption, scrolled)
            after = _post_reactions(after_xml, moved[1] if moved else target[1])
            if after is not None and after > (before or 0):
                phone.log(f"  กดถูกใจแล้ว (รีแอคชัน {before or 0} -> {after})")
                return True
            phone.log(f"  กดแล้วแต่ยืนยันไม่ได้ (รีแอคชัน {before} -> {after})")
            return False

        if attempt >= LIKE_SCROLL_TRIES:
            break
        phone.log(f"  แถบปุ่มยังไม่โผล่ — เลื่อนช้าๆ {SCROLL_STEP}px")
        phone.vswipe("1800", str(1800 - SCROLL_STEP), str(SCROLL_DURATION_MS),
        )
        scrolled = True
        time.sleep(2.0)

    phone.log("  ชี้ปุ่มถูกใจของโพสต์นี้ไม่ได้ — ไม่กด")
    return False
    return False


# ปุ่มเปิดแผงคอมเมนต์ + ช่องพิมพ์ + ปุ่มส่ง (ยกคำจากที่ตรวจหน้าจอจริงไว้แล้ว)
COMMENT_OPEN_HINTS = ["แสดงความคิดเห็น", "เขียนความคิดเห็น", "Comment"]
COMMENT_FIELD_HINTS = [
    "เขียนความคิดเห็นสาธารณะ", "เขียนความคิดเห็น", "Write a public comment",
]
COMMENT_SEND_HINTS = ["ส่ง", "Send"]
# ระยะจาก "ข้อความคอมเมนต์" ถึง "แถวปุ่มถูกใจ/ตอบกลับ" ของคอมเมนต์เดียวกัน
#
# วัดจากจอจริง:
#   คอมเมนต์ข้อความล้วน        ~438 px
#   คอมเมนต์ที่มีรูปแนบ+การ์ดลิงก์  1,610 px  ← รูปกับการ์ดดันแถวปุ่มลงไปไกลมาก
#
# ตั้งไว้ 520 px ตอนยังไม่มีฟีเจอร์แนบรูป พอเริ่มแนบรูปจริงเลยหาปุ่มไม่เจอทุกกลุ่ม
# (งาน p263538966: ถูกใจคอมเมนต์ 0/5 ทั้งที่คอมเมนต์ขึ้นครบ)
#
# กว้างขึ้นแล้วยังไม่เสี่ยงกดผิดคอมเมนต์ เพราะตัวเลือกหยิบ "ปุ่มตัวบนสุดที่อยู่ใต้
# ข้อความเรา" ซึ่งเป็นแถวปุ่มของคอมเมนต์เราเสมอ แถวของคอมเมนต์ถัดไปอยู่ต่ำกว่านั้น
COMMENT_REGION_HEIGHT = 1800
# ป้ายที่มีเฉพาะ "คอมเมนต์ที่ส่งขึ้นแล้ว" — ยังอยู่ในช่องพิมพ์จะไม่มีป้ายพวกนี้
COMMENT_POSTED_HINTS = ["ตอบกลับความคิดเห็นของ", "ถูกใจปุ่มแสดงความคิดเห็นของ", "Reply to"]
# เวลาที่โผล่เหนือข้อความคอมเมนต์ — คอมเมนต์ที่ขึ้นจริงมีแถว "ชื่อ · เมื่อสักครู่"
# เสมอ ส่วนข้อความที่ยังค้างในช่องพิมพ์ไม่มี
COMMENT_TIME_HINTS = ["เมื่อสักครู่", "นาที", "ชม.", "ชั่วโมง", "Just now", "ago"]
COMMENT_HEADER_GAP = 200
# ระยะจากท้ายข้อความคอมเมนต์ลงไปถึงป้ายเวลา (พิกัดอ้างอิงบนจอ 1080x2400)
# กว้างกว่าฝั่งบนมาก เพราะการ์ดลิงก์/รูปแนบมาคั่นระหว่างข้อความกับเวลาได้
# ป้ายที่บอกว่า "ตรงนี้คือหัวของคอมเมนต์อันหนึ่ง" — ใช้แบ่งว่าเวลาที่เจอ
# เป็นของคอมเมนต์เราหรือของอันถัดไป แทนการเดาระยะพิกเซล
COMMENT_HEAD_MARKS = ("รูปโปรไฟล์ของ", "profile picture of")


NO_COMMENT = {"commented": False, "comment_liked": False, "comment_count": 0}
MAX_COMMENTS = 2        # คอมเมนต์ต่อโพสต์ได้สูงสุดกี่ข้อความ


def _as_texts(comment) -> list[str]:
    """รับได้ทั้งข้อความเดียวและรายการข้อความ — ของเดิมส่งมาเป็นข้อความเดียว"""
    if isinstance(comment, (list, tuple)):
        items = [str(x).strip() for x in comment]
    else:
        items = [str(comment or "").strip()]
    return [x for x in items if x][:MAX_COMMENTS]


def _as_photos(photos, count: int) -> list:
    """จัดรูปคอมเมนต์ให้ยาวเท่าจำนวนข้อความ ช่องที่ไม่มีรูปเป็น None

    รับได้ทั้งไฟล์เดียว (ใช้กับข้อความแรก) และลิสต์เรียงตามช่องคอมเมนต์
    """
    if not photos:
        return [None] * count
    items = photos if isinstance(photos, (list, tuple)) else [photos]
    out = []
    for index in range(count):
        raw = items[index] if index < len(items) else None
        out.append(Path(raw) if raw else None)
    return out


# ============================================ เพดานการคอมเมนต์ต่อชั่วโมง
#
# คอมเมนต์รัวเกินไปเข้าข่ายสแปม โดนจำกัดการมองเห็นหรือระงับบัญชีได้
# นับแบบหน้าต่างเลื่อน (rolling window) ไม่ใช่รีเซ็ตทุกต้นชั่วโมง —
# ไม่งั้นยิง 10 ครั้งท้ายชั่วโมงแล้วยิงอีก 10 ต้นชั่วโมงถัดไปได้ทันที
#
# **แบ่งเป็นเลน 18 ส.ค. 2026** ของเดิมเป็นถังใบเดียวใช้ร่วมกันทั้งสายโพสต์
# (app.py → fb_auto_post) และสายตอบคอมเมนต์ (fb_engage) ผลคือ fb_engage ตอบ
# รอบเดียว 5 ครั้งกินโควตาไป 42% แล้วงานโพสต์ที่ผู้ใช้สั่งเองเหลือแค่ 7 กลุ่ม
# ในชั่วโมงนั้น โดยไม่มีใครรู้ตัวเพราะทั้งคู่เห็นตัวเลขเดียวกัน
#
# **แบ่ง ไม่ใช่แจกเพิ่ม** — สองสายนี้ใช้ **บัญชี Facebook เดียวกันบนมือถือเครื่อง
# เดียวกัน** เพดานนี้เป็นเพดานของ *บัญชี* ไม่ใช่ของโปรเซส ถ้าให้เลนละ 12 เท่ากับ
# ยิงจริง 24 ครั้ง/ชั่วโมงต่อบัญชีเดียว = เพิ่มความเสี่ยงโดนตีธงเป็นสองเท่าโดยที่
# ตั้งใจจะแค่ "แยกกัน" — ผลรวมของทุกเลนจึงต้องไม่เกิน COMMENT_LIMIT_PER_HOUR
# **ตัวเลขจริงอยู่ที่ fb_limits ตั้งแยกรายบัญชีได้** ค่าคงที่ตัวนี้เหลือไว้เป็น
# ค่าตั้งต้นและเพื่อให้โค้ดเก่าที่อ้างชื่อนี้ยังทำงานได้ — อย่าเอาไปตัดสินใจใหม่
COMMENT_LIMIT_PER_HOUR = fb_limits.DEFAULTS["per_hour"]
COMMENT_WINDOW_SECONDS = 3600.0
DEFAULT_COMMENT_LANE = fb_limits.DEFAULT_LANE
# **ต้องผ่าน studio_shared.DATA_DIR** ไม่ใช่ต่อ "data" เอง — ไม่งั้น
# STUDIO_DATA_DIR ไม่มีผลกับไฟล์นี้ แล้วสนามทดสอบจะไปอ่าน/เขียนโควตา
# ของจริง: เทสอ่านโควตาจริงจนผลเพี้ยน (เจอจริง 18 ส.ค.) และร้ายกว่านั้นคือ
# **เทสเขียนทับโควตาจริง** = กินโควตาคอมเมนต์ของวันนั้นไปฟรีๆ โดยไม่มีใครรู้
def COMMENT_TIMES_FILE():
    """แฟ้มของบัญชีที่กำลังทำงาน — ย้ายมาแยกรายบัญชี 28 ส.ค. 2569

    เดิมเป็นค่าคงที่ชี้แฟ้มใบเดียวที่ทุกบัญชีใช้ร่วมกัน พอมีบัญชีที่สอง
    ข้อมูลจะปนกันเงียบๆ จึงเปลี่ยนเป็นฟังก์ชันที่หาพาธตอนเรียกใช้
    """
    # นำเข้าตรงนี้ ไม่ใช่หัวไฟล์ — `fb_auto_post` นำเข้าไฟล์นี้กลับมา
    # ถ้าไว้หัวไฟล์จะเป็นวงกลม แล้วเซิร์ฟเวอร์เปิดไม่ขึ้นทั้งตัว (เจอจริง 28 ส.ค.)
    import fb_auto_post
    return fb_auto_post.state_file("comment_times.json")
# **เลนละไฟล์ ไม่ใช่ไฟล์เดียวหลายคีย์**
#
# app.py รันค้างข้ามวันโดยถือโค้ดเก่าไว้ในหน่วยความจำ ถ้าเปลี่ยนไฟล์เดิมให้เป็น
# รูปแบบใหม่ (dict แยกเลน) โค้ดเก่าที่ยังรันอยู่จะเขียนทับด้วยรูปแบบเดิม (list)
# แล้วยอดของอีกเลนหายเงียบๆ โดยไม่มี error — แยกไฟล์แล้วโค้ดเก่าที่ไม่รู้จักเลน
# ก็ยังทำงานถูกต้องต่อไปในเลน post ตามเดิม **ไม่ต้องรีสตาร์ต app.py**
#
# ⚠️ เก็บเป็น **ชื่อไฟล์** ไม่ใช่พาธสำเร็จรูป — ตั้งแต่ย้ายมาแยกรายบัญชี
# (28 ส.ค. 2569) พาธขึ้นกับบัญชีที่กำลังทำงาน ซึ่งยังไม่รู้ตอนโหลดไฟล์
# คิดพาธตรงนี้เมื่อไร จะได้พาธของบัญชีแรกที่บังเอิญเจอ แล้วค้างอย่างนั้นทั้งวัน
_COMMENT_LANE_NAMES = {
    "post": "comment_times.json",
    "reply": "comment_times_reply.json",
}
_comment_lock = threading.Lock()


def comment_lane_limit(lane: str = DEFAULT_COMMENT_LANE, account: str = "") -> int:
    """ช่องสูงสุดของเลนนั้นสำหรับบัญชีนั้น — ตั้งได้ที่ fb_limits"""
    return fb_limits.lane_limit(lane, account)


def comment_limit_per_hour(account: str = "") -> int:
    """เพดานรวมต่อชั่วโมงของบัญชีนั้น"""
    return fb_limits.per_hour(account)


def _lane_file(lane: str) -> Path:
    import fb_auto_post
    return fb_auto_post.state_file(
        _COMMENT_LANE_NAMES.get(lane, "comment_times.json"))


def _comment_times(lane: str = DEFAULT_COMMENT_LANE) -> list[float]:
    """เวลาที่คอมเมนต์สำเร็จ **ของเลนนั้น** ภายในหน้าต่างล่าสุด (เก่ากว่านั้นตัดทิ้ง)

    เก็บลงไฟล์เพราะรีสตาร์ตเซิร์ฟเวอร์บ่อย ถ้าเก็บในหน่วยความจำ
    รีสตาร์ตทีเดียวโควตาก็รีเซ็ตหมด ซึ่งทำให้เพดานไม่มีความหมาย
    """
    try:
        raw = json.loads(_lane_file(lane).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(raw, list):
        return []
    edge = time.time() - COMMENT_WINDOW_SECONDS
    return sorted(float(x) for x in raw if isinstance(x, (int, float)) and x > edge)


def _all_comment_times() -> list[float]:
    """เวลาที่คอมเมนต์สำเร็จของ **ทุกเลนรวมกัน** — ใช้คุมเพดานของบัญชี"""
    merged: list[float] = []
    for lane in _COMMENT_LANE_NAMES:
        merged.extend(_comment_times(lane))
    return sorted(merged)


# ลำดับความสำคัญของเลน — **ตัวหน้าสุดได้ก่อนเสมอ**
# เจ้าของสั่ง 28 ส.ค. 2569: "เลนตอบคอมเมนต์เป็น first priority เลนโพสต์เป็นรอง"
LANE_PRIORITY = ("reply", "post")


def lane_owning_hour() -> str:
    """เลนที่ **ยึดชั่วโมงนี้ไว้แล้ว** — คืน "" เมื่อยังไม่มีใครเริ่ม

    **กติกาที่เจ้าของสั่ง 28 ส.ค. 2569**

        ชั่วโมงหนึ่งทำได้เลนเดียวเท่านั้น
        ชั่วโมงไหนมีตอบคอมเมนต์  →  ห้ามโพสต์เลย
        ชั่วโมงไหนมีโพสต์        →  ห้ามตอบคอมเมนต์เลย

    **ทำไมต้องแยกกันเด็ดขาด** ของเดิมแบ่งเพดานให้สองเลนใช้พร้อมกัน (post 8 +
    reply 4) ซึ่งแปลว่าในหนึ่งชั่วโมง Facebook เห็นบัญชีนี้ทั้งโพสต์และตอบคอมเมนต์
    คนอื่นสลับกันรัวๆ — เป็นรูปแบบที่ดูเป็นบอทมากกว่าทำอย่างเดียวไปเลย

    ยึดจาก "เลนไหนมีคอมเมนต์สำเร็จในชั่วโมงที่ผ่านมา" ไม่ใช่จากธงที่ต้องมีคนไป
    ตั้ง/ล้าง — ธงที่ต้องล้างเองคือธงที่ค้างเมื่องานตายกลางคัน แล้วบัญชีจะถูก
    ล็อกไว้ทั้งวันโดยไม่มีใครรู้
    """
    for lane in LANE_PRIORITY:
        if _comment_times(lane):
            return lane
    return ""


def comment_quota_left(lane: str = DEFAULT_COMMENT_LANE, account: str = "") -> int:
    """คอมเมนต์ได้อีกกี่ครั้งในชั่วโมงนี้ — **เลนเดียวต่อชั่วโมง**

    ลำดับการตัดสิน
      1. ชั่วโมงนี้มีเลนอื่นยึดไว้แล้ว → 0 (ไม่ว่าเพดานจะเหลือเท่าไร)
      2. ยังว่าง หรือเป็นเลนของเราเอง → เหลือเท่าที่เพดานเลนกับเพดานบัญชีให้

    **ตัวนับยังเป็นถังรวมของทุกบัญชี** (ไฟล์เดียวต่อเลน) ส่วนเพดานแยกรายบัญชีแล้ว
    วันที่มีสองบัญชียิงพร้อมกัน ตัวนับรวมจะทำให้ **รัดกว่าความจริง** ซึ่งเป็นทาง
    ที่ปลอดภัย ไม่ใช่ทางที่ยิงเกิน — แต่ต้องมาแยกถังตอนนั้น
    ดู `fb_limits._slug()` ที่เตรียมชื่อไฟล์รายบัญชีไว้แล้ว

    ⚠️ **สิ่งที่ยังไม่ได้ทำ ตัดสินใจไว้ 28 ส.ค. 2569**

    เจ้าของสั่งด้วยว่า *"ให้สะสมเลนตอบไว้ครบ 12 แล้วค่อยทำ"* — ส่วนนั้นเป็นเรื่อง
    **จังหวะปล่อยงาน** ของตัวตอบคอมเมนต์ (`fb_engage`) ไม่ใช่ของด่านนี้
    ด่านนี้รู้แค่ "ทำไปแล้วกี่ครั้ง" ไม่รู้ว่า "มีงานรออยู่กี่ชิ้น"

    และการให้เลนตอบ **แซงคิว** เลนโพสต์ที่ยังไม่เริ่ม ก็ทำที่นี่ไม่ได้ด้วยเหตุผล
    เดียวกัน — ตอนนี้จึงเป็น "ใครเริ่มก่อนได้ชั่วโมงนั้นไป" ถ้าอยากให้เลนตอบ
    กันที่ไว้ล่วงหน้าจริงๆ ต้องให้ `fb_engage` บอกด่านนี้ว่ามีงานรออยู่
    """
    owner = lane_owning_hour()
    if owner and owner != lane:
        return 0
    by_lane = comment_lane_limit(lane, account) - len(_comment_times(lane))
    by_account = comment_limit_per_hour(account) - len(_all_comment_times())
    return max(0, min(by_lane, by_account))


def comment_quota_resets_in(lane: str = DEFAULT_COMMENT_LANE,
                            account: str = "") -> float:
    """อีกกี่วินาทีโควตาจะคืนมาหนึ่งช่อง (0 = ยังไม่เต็ม)

    ดูจากด่านที่ตันอยู่จริง — ตันเพราะเลนเต็มก็รอคอมเมนต์เก่าสุด *ของเลนนั้น*
    หลุดหน้าต่าง ตันเพราะเพดานบัญชีก็รอคอมเมนต์เก่าสุดของทุกเลนรวมกัน
    """
    if comment_quota_left(lane, account) > 0:
        return 0.0
    waits: list[float] = []
    mine = _comment_times(lane)
    if mine and len(mine) >= comment_lane_limit(lane, account):
        waits.append(mine[0] + COMMENT_WINDOW_SECONDS - time.time())
    everyone = _all_comment_times()
    if everyone and len(everyone) >= comment_limit_per_hour(account):
        waits.append(everyone[0] + COMMENT_WINDOW_SECONDS - time.time())
    return max(0.0, min(waits)) if waits else 0.0


def _note_comment_sent(lane: str = DEFAULT_COMMENT_LANE) -> None:
    """บันทึกว่าเพิ่งคอมเมนต์สำเร็จหนึ่งครั้ง **ในเลนนั้น**"""
    path = _lane_file(lane)
    with _comment_lock:
        times = _comment_times(lane)
        times.append(time.time())
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(times[-COMMENT_LIMIT_PER_HOUR * 4:]), encoding="utf-8"
            )
        except OSError:
            pass                      # เขียนไม่ได้ต้องไม่ล้มทั้งงาน


COMMENT_SEARCH_SCROLLS = 4
# จำนวนรอบตรวจว่าคอมเมนต์ขึ้นแล้วหลังกดส่ง (รอบละ 3.5 วิ)
COMMENT_POST_TRIES = 4


def _comment_already_there(phone: Phone, probe: str) -> bool:
    """คอมเมนต์นี้เคยส่งไปแล้วหรือยัง — ต้อง**เลื่อนหา** ไม่ใช่ดูแค่จอแรก

    เปิดหน้าโพสต์จากแจ้งเตือนแล้วคอมเมนต์เดิมมักอยู่ใต้ขอบจอ ยังไม่โหลดขึ้นมา
    ตัดสินจากจอแรกอย่างเดียวจะสรุปว่า "ยังไม่เคยคอมเมนต์" แล้วส่งซ้ำ

    เจอจริง 9 ส.ค.: รอบตามเก็บรอบสองส่งคอมเมนต์เดิมซ้ำอีกใบใน 3 กลุ่ม
    (นับจากจอจริง: เลื่อนรอบ 0 เจอ 0 ครั้ง · เลื่อนรอบ 1 ถึงเจอ)
    """
    if not probe:
        return False
    for _ in range(COMMENT_SEARCH_SCROLLS):
        if _comment_is_live(phone.dump(), probe):
            return True
        phone.vswipe("1800", str(1800 - SCROLL_STEP), str(SCROLL_DURATION_MS),
        )
        time.sleep(1.8)
    return False


# ป้ายที่ Facebook ขึ้นเมื่อคอมเมนต์ถูกปฏิเสธ — เห็นเฉพาะคนเขียน คนอื่นไม่เห็นเลย
COMMENT_REJECTED_MARKS = ("ถูกปฏิเสธ", "was rejected", "ไม่ผ่านการตรวจสอบ")


def comment_probe(text: str) -> str:
    """ชิ้นข้อความที่ใช้ตามหาคอมเมนต์ของเราบนจอ — ต้อง **ไม่ซ้ำกับใบอื่น**

    ปกติ 10 ตัวแรกก็พอ แต่คอมเมนต์ที่เหลือแต่ลิงก์ขึ้นต้นด้วย "https://s."
    เหมือนกันหมดทุกใบ — ตามหาแล้วไปเจอคอมเมนต์เก่าแทน แล้วไปกดไลก์ผิดใบ
    หรือรายงานว่า "มีอยู่แล้ว" ทั้งที่ยังไม่ได้ส่ง (เจอจริง 28 ส.ค. 2569)

    ลิงก์จึงใช้ **ท้ายลิงก์แรก** ซึ่งเป็นรหัสเฉพาะของสินค้าแต่ละชิ้น
    """
    body = (text or "").strip()
    if not body:
        return ""
    if body.lower().startswith(("http://", "https://")):
        # **Facebook แทนตัวลิงก์ด้วยการ์ดสินค้า — ตัว URL ไม่ถูกวาดออกมาเลย**
        # (วัดจากผังจอจริง 28 ส.ค. 2569) บนจอมีแค่
        #     "ลิงก์ที่แชร์: s.shopee.co.th, D-Link DWR-U2000 Mobile Ro..."
        # ตามหาด้วยตัว URL หรือรหัสท้ายลิงก์จึงไม่มีทางเจอ
        # ใช้ **ชื่อเว็บ** ซึ่งอยู่บนการ์ดแน่นอน และตัวที่เจอก่อนคือใบใหม่สุดเสมอ
        # เพราะคอมเมนต์ใหม่อยู่บนสุด
        host = body.split()[0].split("//", 1)[-1].split("/", 1)[0]
        return host or body[:10]
    return body[:10]


def links_only(text: str) -> str:
    """เหลือแต่ลิงก์ ตัดคำพูดทิ้ง — ใช้ตอนคอมเมนต์เต็มถูกปฏิเสธ

    **เจ้าของสั่ง 28 ส.ค. 2569** — *"ถ้าไลค์ไม่ขึ้นแสดงว่าคอมเมนต์ถูกปฏิเสธ
    ให้ตัดคำพูดออก เหลือแต่ลิ้ง แล้วคอมเมนต์ใหม่"*
    """
    urls = re.findall(r"https?://\S+", text or "")
    return chr(10).join(dict.fromkeys(urls))   # ตัดลิงก์ซ้ำ คงลำดับเดิม


def comment_rejected(phone: Phone, probe: str) -> bool:
    """คอมเมนต์นี้ถูกปฏิเสธไหม — ดูป้ายที่อยู่ใต้ข้อความของเรา

    ป้ายนี้โผล่ **เฉพาะบนจอของคนเขียน** คนอื่นเปิดดูจะไม่เห็นคอมเมนต์เลย
    จึงเป็นสัญญาณเดียวที่จับได้จากฝั่งเรา
    """
    xml = phone.dump()
    bottom = None
    for labels, (_, _, _, y2) in iter_nodes(xml):
        if any(probe in label for label in labels):
            bottom = y2
            break
    if bottom is None:
        return False
    for labels, (_, y1, _, _) in iter_nodes(xml):
        if y1 < bottom:
            continue
        joined = " ".join(labels)
        if any(mark in joined for mark in COMMENT_REJECTED_MARKS):
            return True
        if any(mark in joined for mark in COMMENT_HEAD_MARKS):
            break                       # ถึงคอมเมนต์ถัดไปแล้ว
    return False


def delete_own_comment(phone: Phone, text: str) -> bool:
    """ลบคอมเมนต์ของเราเอง — กดค้างบนข้อความแล้วเลือก "ลบความคิดเห็น"

    ท่าเดียวกับที่คนกดเอง (กติกาข้อ 2.7 ทุกอย่างต้องเป็นการกดจริง)
    ต้องเจอเมนูแบบ **ตรงเป๊ะ** เพราะบนเมนูนั้นมี "รายงาน" อยู่ใกล้ๆ ด้วย
    """
    probe = comment_probe(text)
    if not probe:
        return False
    spot = None
    for labels, (x1, y1, x2, y2) in iter_nodes(phone.dump()):
        if any(probe in label for label in labels):
            spot = ((x1 + x2) // 2, (y1 + y2) // 2)
            break
    if spot is None:
        phone.log("  ไม่เห็นคอมเมนต์ที่จะลบบนจอ")
        return False
    phone.run("shell", "input", "swipe", str(spot[0]), str(spot[1]),
              str(spot[0]), str(spot[1]), "900")          # กดค้าง
    time.sleep(3.0)
    menu = phone.find_exact(phone.dump(), ["ลบความคิดเห็น", "Delete comment"])
    if menu is None:
        phone.log("  ไม่เห็นเมนู 'ลบความคิดเห็น' — ไม่ลบ")
        phone.back()
        return False
    phone.tap(menu)
    time.sleep(2.5)
    confirm = phone.find_exact(phone.dump(), ["ลบ", "Delete"])
    if confirm is not None:
        phone.tap(confirm)
        time.sleep(2.5)
    gone = not screen_has(phone.dump(), probe)
    phone.log("  ลบคอมเมนต์เดิมแล้ว" if gone else "  ลบไม่สำเร็จ")
    return gone


def comment_single_post(phone: Phone, comment, photos=None,
                        links_only_on_reject: bool = False) -> dict:
    """คอมเมนต์บน "หน้าโพสต์เดี่ยว" — ช่องพิมพ์ตรึงอยู่ล่างจอตลอด

    ไม่ต้องหาแคปชันหรือกดปุ่มเปิดแผงก่อน ต่างจากตอนอยู่ในฟีด
    (สาเหตุที่คอมเมนต์ไม่ขึ้นหลายกลุ่ม: ขั้นก่อนหน้าเลื่อนจอจนแคปชันหลุด
    แล้วตรรกะที่ผูกกับแคปชันตัดสินว่า "ไม่เห็นโพสต์" เลยข้ามการคอมเมนต์ไปเลย)
    """
    texts = _as_texts(comment)
    if not texts:
        return dict(NO_COMMENT)
    shots = _as_photos(photos, len(texts))
    done, liked = 0, 0
    for order, text in enumerate(texts, 1):
        if _comment_already_there(phone, comment_probe(text)):
            phone.log(f"  คอมเมนต์ที่ {order} มีอยู่แล้ว — ไม่ซ้ำ")
            done += 1
            liked += 1 if like_own_comment(phone, text) else 0
            continue
        if not _write_comment(phone, text, shots[order - 1]):
            break
        done += 1
        ok = like_own_comment(phone, text)
        if not ok:
            # **ไลก์ไม่ขึ้น = คอมเมนต์ถูกปฏิเสธ** (เจ้าของสรุปไว้ 28 ส.ค. 2569)
            #
            # คอมเมนต์ที่ถูกปฏิเสธไม่มีแถว "ถูกใจ · ตอบกลับ" ให้กดเลย เพราะมัน
            # ไม่ได้เผยแพร่จริง — เราเห็นในฐานะคนเขียน แต่คนอื่นไม่เห็น
            # ตรวจของจริง 28 ส.ค.: ใต้คอมเมนต์ขึ้นว่า "ถูกปฏิเสธ / ดูความเห็น"
            # และคำว่า "ถูกใจ" ไม่ปรากฏบนจอเลยสักครั้ง
            #
            # เจ้าของสั่งให้ **ตัดคำพูดออก เหลือแต่ลิงก์ แล้วส่งใหม่**
            # เพราะตัวที่โดนคัดออกคือข้อความโฆษณา ไม่ใช่ตัวลิงก์
            # **ใช้เฉพาะกลุ่มที่เจ้าของเปิดไว้** (สั่ง 28 ส.ค. 2569: "loop นี้ใช้
            # เฉพาะกลุ่มรีวิวครอบจักรวาลเท่านั้น") — กลุ่มอื่นคอมเมนต์เต็มผ่านอยู่แล้ว
            # ตัดคำพูดทิ้งทุกกลุ่มคือทำให้กลุ่มที่ไม่มีปัญหาแย่ลงฟรีๆ
            bare = links_only(text) if links_only_on_reject else ""
            if bare and bare != text.strip():
                phone.log("  ไลก์คอมเมนต์ไม่ขึ้น = น่าจะถูกปฏิเสธ "
                          "— ลบแล้วส่งใหม่เหลือแต่ลิงก์")
                delete_own_comment(phone, text)
                time.sleep(2.0)
                if _write_comment(phone, bare, shots[order - 1]):
                    ok = like_own_comment(phone, bare)
                else:
                    done -= 1       # ส่งใหม่ไม่ผ่านด้วย = ใบนี้ไม่นับว่าลงแล้ว
        liked += 1 if ok else 0
        if order < len(texts):
            time.sleep(2.0)         # เว้นจังหวะก่อนพิมพ์ข้อความถัดไป
    return {
        "commented": done > 0,
        "comment_liked": liked > 0 and liked == done,
        "comment_count": done,
    }


CAPTION_BACK_TRIES = 6

# ตรวจซ้ำหลังโพสต์ — เลื่อนลงหาโพสต์ของเราได้กี่ครั้งก่อนยอมแพ้
#
# ตั้ง 4 เพราะโพสต์ที่เพิ่งลงควรอยู่ใน 2-3 หน้าจอแรก ถ้าเลื่อนเกินนี้ยังไม่เจอ
# แปลว่ารออนุมัติจริงหรือไม่ขึ้นจริง — เลื่อนต่อไปก็เปลืองเวลาจอเปล่าๆ
# ต้นทุน: ครั้งละ ~4.3 วินาที (ปัด + รอ 1.8 + dump 2.35)
VERIFY_SCROLL_TRIES = 4

# เมนูของโพสต์เป็นแผ่นเลื่อนได้ — เลื่อนหาได้กี่ครั้งก่อนยอมแพ้
#
# 3 พอ เพราะแผ่นเมนูมีไม่กี่หน้าจอ ถ้าเลื่อนสามครั้งยังไม่เจอ "คัดลอกลิงก์"
# แปลว่าโพสต์นั้นไม่มีตัวเลือกนั้นจริง (เช่น ยังรออนุมัติ) เลื่อนต่อก็เปลืองเวลา
MENU_SCROLL_TRIES = 3
# เลื่อนกลับขึ้นหัวหน้าโพสต์เพื่อหาปุ่ม … (คอมเมนต์ยาวๆ ดันปุ่มไปไกลได้)
LINK_TOP_SCROLL_TRIES = 8


def _scroll_back_to_caption(phone: Phone, caption: str) -> bool:
    """เลื่อน**กลับขึ้น**ไปหาข้อความโพสต์ของเรา คืน True ถ้าเจอ

    ปัดนิ้วจากบนลงล่าง = เนื้อหาเลื่อนกลับไปทางต้นฟีด (ตรงข้ามกับตอนหาแถบปุ่ม)
    เจอแล้วหยุดทันที ไม่เลื่อนเกินจนไปโผล่โพสต์ก่อนหน้า
    """
    if _caption_box(phone.dump(), caption) is not None:
        return True
    for _ in range(CAPTION_BACK_TRIES):
        phone.vswipe("700", str(700 + SCROLL_STEP), str(SCROLL_DURATION_MS),
        )
        time.sleep(1.8)
        if _caption_box(phone.dump(), caption) is not None:
            phone.log("  เลื่อนกลับมาเจอโพสต์ของเราแล้ว")
            return True
    return False


def comment_post_of(phone: Phone, caption: str, comment,
                    single_post: bool = False, photos=None,
                    links_only_on_reject: bool = False) -> dict:
    """คอมเมนต์ใต้ "โพสต์ที่มีแคปชันนี้"

    ทำทันทีหลังโพสต์ตอนโพสต์ยังอยู่ในฟีด ไม่ใช่ย้อนกลับมาหาทีหลัง —
    การไล่หาโพสต์เก่าผ่าน "จัดการโพสต์ → ดูในกลุ่ม" พังบ่อยมาก (สำเร็จ 2 จาก 4)
    ส่วนตอนเพิ่งโพสต์เสร็จเรามีข้อความของตัวเองเป็นหมุดอยู่บนจอแล้ว

    ยึดกติกาเดียวกับการกดถูกใจ: ไม่เห็นข้อความของเรา = ไม่แตะอะไรเลย
    """
    texts = _as_texts(comment)
    if not texts:
        return dict(NO_COMMENT)
    if single_post:
        return comment_single_post(phone, texts, photos, links_only_on_reject)
    shots = _as_photos(photos, len(texts))
    text = texts[0]
    # ขั้นกดถูกใจก่อนหน้านี้เลื่อนลงไปหาแถบปุ่มได้ไกลถึง 5 รอบ (3,500px)
    # แคปชันของเราจึงหลุดขอบบนไปแล้ว ต้องเลื่อนกลับขึ้นไปหาก่อน ไม่งั้นจะสรุปว่า
    # "ไม่เห็นโพสต์ของเรา" แล้วข้ามการคอมเมนต์ ทั้งที่ยังอยู่บนโพสต์ถูกตัว
    # (เจอจริง 9 ส.ค. งาน p263538966: กลุ่ม 4-5 ไลก์ติดแต่คอมเมนต์ 0)
    _scroll_back_to_caption(phone, caption)
    for attempt in range(LIKE_SCROLL_TRIES + 1):
        xml = phone.dump()
        box = _caption_box(xml, caption)
        if box is None:
            phone.log("  ไม่เห็นข้อความโพสต์ของเราบนจอ — ไม่คอมเมนต์")
            return dict(NO_COMMENT)
        top, bottom = box
        button = None
        for labels, (x1, y1, x2, y2) in iter_nodes(xml):
            if not (bottom <= y1 <= bottom + POST_REGION_HEIGHT):
                continue
            joined = " ".join(labels).lower()
            if any(hint.lower() in joined for hint in COMMENT_OPEN_HINTS):
                point = ((x1 + x2) // 2, (y1 + y2) // 2)
                if button is None or point[1] < button[1]:
                    button = point
        if _comment_is_live(xml, text.strip()[:10]):
            phone.log("  คอมเมนต์นี้มีอยู่แล้ว — ไม่คอมเมนต์ซ้ำ")
            return {"commented": True, "comment_liked": like_own_comment(phone, text)}
        if button is not None:
            phone.log("  เปิดแผงคอมเมนต์")
            phone.tap(button)
            time.sleep(3.0)
            # อยู่ในฟีด: เปิดแผงแล้วพิมพ์ได้ทีละข้อความเหมือนกัน
            done, liked = 0, 0
            for order, item in enumerate(texts, 1):
                if not _write_comment(phone, item, shots[order - 1]):
                    break
                done += 1
                liked += 1 if like_own_comment(phone, item) else 0
                if order < len(texts):
                    time.sleep(2.0)
            if not done:
                return dict(NO_COMMENT)
            return {
                "commented": True,
                "comment_liked": liked > 0 and liked == done,
                "comment_count": done,
            }
        if attempt >= LIKE_SCROLL_TRIES:
            break
        # `top` มาจากผังจอ = พิกัดจริงของเครื่องนี้ ต้องแปลงเป็นพิกัดอ้างอิงก่อน
        # ไม่งั้น vswipe จะย่อซ้ำอีกรอบ แล้วเลื่อนสั้นกว่าที่ตั้งใจ
        distance = min(1100, max(300, phone.to_ref_y(top) - 350))
        phone.log(f"  ยังไม่เห็นปุ่มคอมเมนต์ — เลื่อนขึ้น {distance:.0f}px (พิกัดอ้างอิง)")
        phone.vswipe(1800, 1800 - distance, 500)
        time.sleep(2.0)
    phone.log("  หาปุ่มคอมเมนต์ของโพสต์นี้ไม่เจอ")
    return dict(NO_COMMENT)


def like_own_comment(phone: Phone, text: str) -> bool:
    """กดถูกใจ "คอมเมนต์ของเราเอง" ที่เพิ่งส่ง

    หาปุ่มถูกใจที่อยู่ **ใต้ข้อความคอมเมนต์ของเราและใกล้ที่สุด** — ปุ่มถูกใจของ
    คอมเมนต์อยู่แถวเล็กๆ ใต้ตัวข้อความ ต่างจากแถบปุ่มใหญ่ของตัวโพสต์
    ไม่เห็นคอมเมนต์ของเรา = ไม่แตะอะไร เหมือนกติกาของการกดถูกใจโพสต์
    """
    probe = comment_probe(text)
    if not probe:
        return False
    xml = phone.dump()
    bottom = None
    for labels, (_, _, _, y2) in iter_nodes(xml):
        if any(probe in label for label in labels):
            bottom = y2
            break
    if bottom is None:
        phone.log("  ไม่เห็นคอมเมนต์ของเราบนจอ — ไม่กดถูกใจคอมเมนต์")
        return False
    if liked_near(xml, bottom, span=COMMENT_REGION_HEIGHT):
        phone.log("  คอมเมนต์นี้ถูกใจอยู่แล้ว")
        return True
    below = [
        point for point in like_buttons(xml)
        if bottom <= point[1] <= bottom + COMMENT_REGION_HEIGHT
    ]
    # แถบปุ่มของคอมเมนต์อาจตกอยู่ใต้ขอบจอ (โดนช่องพิมพ์บังอยู่) — เลื่อนขึ้นมาก่อน
    for _ in range(3):
        if below:
            break
        phone.vswipe("1600", "1150", str(SCROLL_DURATION_MS),
        )
        time.sleep(2.0)
        xml = phone.dump()
        bottom = None
        for labels, (_, _, _, y2) in iter_nodes(xml):
            if any(probe in label for label in labels):
                bottom = y2
                break
        if bottom is None:
            break
        if liked_near(xml, bottom, span=COMMENT_REGION_HEIGHT):
            phone.log("  คอมเมนต์นี้ถูกใจอยู่แล้ว")
            return True
        below = [
            point for point in like_buttons(xml)
            if bottom <= point[1] <= bottom + COMMENT_REGION_HEIGHT
        ]
    if not below:
        phone.log("  หาปุ่มถูกใจของคอมเมนต์ไม่เจอ")
        return False
    phone.tap(below[0])
    time.sleep(2.0)
    after = phone.dump()
    for labels, (_, _, _, y2) in iter_nodes(after):
        if any(probe in label for label in labels):
            if liked_near(after, y2, span=COMMENT_REGION_HEIGHT):
                phone.log("  กดถูกใจคอมเมนต์แล้ว")
                return True
            break
    phone.log("  กดถูกใจคอมเมนต์แล้วแต่ยืนยันไม่ได้")
    return False


# ปุ่มแนบรูปในแผงคอมเมนต์ — ชื่อจากหน้าจอจริง ไม่ใช่ปุ่มเดียวกับตอนเขียนโพสต์
# (ตอนเขียนโพสต์ปุ่มชื่อ "แกลเลอรี" · ในแผงคอมเมนต์ชื่อ "แสดงรูปภาพและวิดีโอ")
COMMENT_CAMERA_HINTS = ["แสดงรูปภาพและวิดีโอ", "Show photos and videos"]
COMMENT_FIRST_PHOTO_HINTS = ["รายการที่ 1", "item 1", "Item 1"]
# ยืนยันว่ารูปยังแนบอยู่จริงหลังยุบแถบ — ไม่เดาจากการที่แตะผ่าน
COMMENT_ATTACHED_HINTS = ["รูปภาพที่แนบไว้", "Attached photo", "ลบภาพออก"]


def attach_comment_photo(phone: Phone, photo: Path) -> bool:
    """แนบรูปเข้าคอมเมนต์ที่กำลังพิมพ์อยู่ (แผงคอมเมนต์ต้องเปิดและโฟกัสแล้ว)

    ดันรูปเข้าเครื่องใหม่ทุกครั้งก่อนแนบ เพื่อให้เป็น**ใบใหม่สุด** = "รายการที่ 1"
    ในแถบเลือกรูป ถ้าอาศัยว่าดันไว้ตั้งแต่ต้นงาน พอโพสต์กลุ่มถัดไปดันรูปโพสต์
    ตามเข้าไป ลำดับจะเลื่อนแล้วแนบผิดใบ

    แนบไม่ได้ไม่ถือว่าคอมเมนต์ล้ม — คืน False แล้วให้คอมเมนต์เป็นข้อความล้วนต่อไป
    """
    try:
        phone.push_image(photo)
    except PostError as error:
        phone.log(f"  ส่งรูปคอมเมนต์เข้าเครื่องไม่ได้: {error}")
        return False
    camera = phone.find(phone.dump(), COMMENT_CAMERA_HINTS)
    if camera is None:
        phone.log("  ไม่พบปุ่มแนบรูปในแผงคอมเมนต์ — คอมเมนต์เฉพาะข้อความ")
        return False
    phone.tap(camera)
    time.sleep(4.0)
    first = phone.find(phone.dump(), COMMENT_FIRST_PHOTO_HINTS)
    if first is None:
        phone.log("  ไม่เห็นรูปในแถบเลือก — คอมเมนต์เฉพาะข้อความ")
        phone.back()
        time.sleep(1.5)
        return False
    phone.tap(first)
    time.sleep(3.5)
    # ต้องกด Back ยุบแถบรูปก่อน!
    #
    # ตอนแถบรูปเปิดอยู่ uiautomator จะ dump เฉพาะหน้าต่างแถบรูป ช่องพิมพ์กับปุ่มส่ง
    # หายไปจาก dump ทั้งที่ยังอยู่บนจอจริง ถ้าไม่ยุบ โค้ดจะหาช่องพิมพ์ไม่เจอแล้ว
    # แตะมั่ว ข้อความไม่ลงช่อง (รูปที่แนบไว้ไม่หายไปด้วยตอนกด Back)
    phone.back()
    time.sleep(2.5)
    if phone.find(phone.dump(), COMMENT_ATTACHED_HINTS):
        phone.log("  แนบรูปกับคอมเมนต์แล้ว")
        return True
    phone.log("  แนบรูปไม่ติด — คอมเมนต์เฉพาะข้อความ")
    return False


def _attach_with_real_keyboard(phone: Phone, photo: Path) -> bool:
    """แนบรูปโดยสลับกลับไปคีย์บอร์ดจริงชั่วคราว แล้วคืน ADBKeyboard ให้พิมพ์ต่อ

    ADBKeyboard ไม่มีหน้าตา คีย์บอร์ดจึงไม่เด้งขึ้นมา และช่องคอมเมนต์ของ Facebook
    จะกาง**แถบเครื่องมือ** (ปุ่มรูป/สติกเกอร์) ก็ต่อเมื่อมีคีย์บอร์ดจริงดันจอขึ้นเท่านั้น
    พิสูจน์บนจอจริงแล้ว:

        IME = LatinIME      → แถบเครื่องมือโผล่ y=1391 "แสดงรูปภาพและวิดีโอ"
        IME = ADBKeyboard   → ไม่มีแถบเครื่องมือเลย หาปุ่มไม่เจอ

    รอบตามเก็บสลับเป็น ADBKeyboard ไว้ตลอดเพื่อพิมพ์ไทย ปุ่มแนบรูปจึงไม่มีวันโผล่
    """
    current = phone.shell("settings get secure default_input_method").strip()
    swapped = ""
    if current == ADB_KEYBOARD_IME:
        normal = phone.normal_keyboard()
        if not normal:
            phone.log("  ไม่มีคีย์บอร์ดปกติให้สลับ — คอมเมนต์เฉพาะข้อความ")
            return False
        phone.shell(f"ime set {normal}")
        time.sleep(1.5)
        swapped = normal
        # ต้องแตะช่องซ้ำให้คีย์บอร์ดจริงเด้ง แถบเครื่องมือถึงจะกางออกมา
        field = phone.find(phone.dump(), COMMENT_FIELD_HINTS)
        if field is not None:
            phone.tap(field)
            time.sleep(2.5)
    try:
        return attach_comment_photo(phone, photo)
    finally:
        if swapped:
            phone.shell(f"ime set {ADB_KEYBOARD_IME}")
            time.sleep(1.5)


def _watch_for_block(phone: Phone, xml: str) -> bool:
    """เจอข้อความบล็อกของ Facebook บนจอนี้ไหม — เจอแล้วสั่งพักทันที

    ใช้กับทางล้มที่ **ยังไม่ได้กดส่ง** (หาช่องพิมพ์ไม่เจอ / หาปุ่มส่งไม่เจอ)
    ทางพวกนี้ล้มได้จากเรื่องธรรมดาอย่างโพสต์ยังไม่ขึ้นหรือจอโหลดไม่ทัน จึง
    **ไม่นับเข้าตัวนับล้มติดกัน** — ไม่งั้นโพสต์ที่ยังรออนุมัติ 3 กลุ่มติดจะทำให้
    พักคอมเมนต์ทั้งระบบ 6 ชั่วโมงทั้งที่ไม่ได้โดนอะไรเลย
    แต่ถ้า Facebook ขึ้นข้อความบล็อกมาตรงๆ ก็คือคำตอบแล้ว พักได้ทันที
    """
    if not fb_comment_guard.detect_block(xml):
        return False
    note = fb_comment_guard.note_failure(xml)
    if note:
        phone.log("  เจอข้อความบล็อกจาก Facebook บนจอ — สั่งพักคอมเมนต์แล้ว")
    return True


def _write_comment(phone: Phone, text: str, photo: Path | None = None,
                   lane: str = DEFAULT_COMMENT_LANE) -> bool:
    """พิมพ์ + ส่งคอมเมนต์ในแผงที่เปิดอยู่ แล้วยืนยันว่าข้อความขึ้นจริง

    `lane` = ช่องโควตาที่จะหักและตรวจ ("post" งานโพสต์ · "reply" ตอบคอมเมนต์คนอื่น)
    ค่าตั้งต้นเป็น "post" ตั้งใจให้ผู้เรียกเดิมทุกรายทำงานเหมือนเดิมทุกประการ
    """
    # โดนบล็อกอยู่ = ไม่ต้องลอง ทางผ่านเดียวที่ส่งคอมเมนต์จริง คุมที่นี่ที่เดียวพอ
    #
    # 16 ส.ค. 2026 คอมเมนต์ล้ม 32 ครั้งติดกัน 5 ชั่วโมงโดยไม่มีใครหยุด เพราะ
    # ไม่มีด่านนี้ — แต่ละครั้งกินเวลาจอ ~2 นาที 20 วินาที รวมแล้วราว 75 นาที
    # และการยิงซ้ำระหว่างโดนบล็อกยิ่งยืดเวลาบล็อกออกไป
    # เพดานผูกกับ **เครื่อง** เพราะหนึ่งเครื่อง = หนึ่งบัญชีที่ล็อกอินค้างไว้
    # และ Facebook ให้เพดานไม่เท่ากันในแต่ละบัญชี (ตั้งแยกได้ที่ fb_limits)
    account = phone.serial
    hold = fb_comment_guard.hold_reason(account=account)
    if hold:
        phone.log(f"  {hold} — ข้ามคอมเมนต์")
        return False
    # เช็คเพดานก่อนลงมือ — ทางผ่านเดียวที่คอมเมนต์ถูกส่งจริง คุมที่นี่ที่เดียวพอ
    # เช็คก่อนพิมพ์/แนบรูป จะได้ไม่เสียเวลาทำงานเปล่าแล้วมาตันตอนกดส่ง
    if comment_quota_left(lane, account) <= 0:
        wait = comment_quota_resets_in(lane, account)
        phone.log(
            f"  ครบเพดานเลน {lane} ({comment_lane_limit(lane, account)} "
            f"คอมเมนต์/ชั่วโมง จากเพดานบัญชี {comment_limit_per_hour(account)}) "
            f"แล้ว — ข้ามไปก่อน (ว่างอีกช่องในอีก {wait / 60:.0f} นาที)"
        )
        return False
    opened = phone.dump()
    field = phone.find(opened, COMMENT_FIELD_HINTS)
    if field is None:
        phone.log("  ไม่พบช่องพิมพ์คอมเมนต์")
        _watch_for_block(phone, opened)
        phone.back()
        return False
    phone.tap(field)
    time.sleep(1.5)
    if photo is not None:
        # แนบรูป **ก่อน** พิมพ์ — แถบเครื่องมือหุบลงหลังพิมพ์ข้อความยาว
        # แล้วปุ่มแนบรูปจะหายไปจากจอ
        _attach_with_real_keyboard(phone, photo)
        # ตำแหน่งช่องพิมพ์ขยับหลังรูปเข้ามาแทรก ต้องหาใหม่แล้วแตะให้โฟกัสอีกครั้ง
        again = phone.find(phone.dump(), COMMENT_FIELD_HINTS)
        if again is not None:
            phone.tap(again)
            time.sleep(1.5)
    phone.type_text(text)
    time.sleep(1.5)
    # ต้องเห็นข้อความบนจอก่อนกดส่ง — broadcast ผ่านไม่ได้แปลว่าข้อความเข้าช่องจริง
    probe = comment_probe(text)
    typed = phone.dump()
    if not screen_has(typed, probe):
        phone.log("  พิมพ์คอมเมนต์แล้วแต่ข้อความไม่ขึ้นบนจอ")
        _watch_for_block(phone, typed)
        phone.back()
        return False
    send = phone.find(typed, COMMENT_SEND_HINTS)
    if send is None:
        phone.log("  ไม่พบปุ่มส่งคอมเมนต์")
        _watch_for_block(phone, typed)
        phone.back()
        return False
    phone.tap(send)
    # ตรวจซ้ำหลายรอบ ไม่ใช่รอบเดียว — คอมเมนต์ที่มีรูปแนบต้องรออัปโหลดเสร็จก่อน
    # ถึงจะโผล่ ตรวจรอบเดียวที่ 3.5 วินาทีเร็วเกินไป (เจอจริงงาน p263538966:
    # รายงาน "ยังไม่ขึ้น" ทั้งที่ขึ้นแล้ว) — false negative แบบนี้อันตรายกว่าช้า
    # เพราะรอบตามเก็บครั้งถัดไปจะนึกว่ายังไม่ได้ส่ง แล้วส่งซ้ำเป็นคอมเมนต์คู่
    # ต้องใช้ตัว "เลื่อนหา" ตัวเดียวกับตอนเช็คคอมเมนต์ซ้ำ ไม่ใช่ดูแค่จอเดียว
    #
    # คอมเมนต์ที่มีรูปแนบ + การ์ดลิงก์สูงถึง ~1,600px พอส่งเสร็จตัวมันเองมักถูกดัน
    # พ้นขอบจอ ตรวจจากจอเดียวจึงไม่เจอแล้วรายงานว่า "ยังไม่ขึ้น" ทั้งที่ขึ้นแล้ว
    # (เจอจริง 11 ส.ค. งาน p438217250: รายงานพลาด 4 จาก 5 กลุ่ม เปิดดูจริงมีครบ)
    live = False
    last = ""
    for _ in range(COMMENT_POST_TRIES):
        time.sleep(3.5)
        last = phone.dump()
        if _comment_is_live(last, probe) or _comment_already_there(phone, probe):
            live = True
            break
    # ยืนยันว่า "ขึ้นเป็นคอมเมนต์จริง" ไม่ใช่ข้อความค้างอยู่ในช่องพิมพ์
    #
    # เดิมเช็คแค่ว่าข้อความอยู่บนจอ ซึ่งข้อความที่ยังไม่ได้ส่งก็อยู่บนจอเหมือนกัน
    # (ค้างในช่องพิมพ์) จึงรายงานว่าส่งสำเร็จทั้งที่ไม่ได้ส่ง — ตรวจของจริงแล้วพบว่า
    # โพสต์ไม่มีคอมเมนต์นั้นอยู่เลย ทั้งที่ log บอกว่า "คอมเมนต์แล้ว"
    #
    # คอมเมนต์ที่ขึ้นจริงจะมีปุ่มประจำตัวตามมาด้วยเสมอ ("ตอบกลับความคิดเห็นของ …")
    if live:
        # นับเฉพาะที่ขึ้นจริง ไม่นับตอนกดส่งแล้วไม่ขึ้น — ไม่งั้นโควตาหมดฟรี
        _note_comment_sent(lane)
        fb_comment_guard.note_success()
        phone.log(f"  คอมเมนต์ขึ้นแล้ว (เลน {lane} เหลือชั่วโมงนี้ "
                  f"{comment_quota_left(lane, account)} · วันนี้เหลือ "
                  f"{fb_comment_guard.daily_left(account=account)})")
        return True
    # กดส่งไปแล้วแต่ไม่ขึ้น = ทางล้มที่น่าสงสัยที่สุด นับเข้าตัวนับและเก็บจอไว้เป็น
    # หลักฐานทุกครั้ง เพราะยังไม่เคยเห็นว่า Facebook ขึ้นข้อความว่าอะไรตอนบล็อก
    phone.log("  กดส่งแล้วแต่คอมเมนต์ยังไม่ขึ้น")
    note = fb_comment_guard.note_failure(last)
    if note:
        phone.log("  ⛔ ล้มติดกันครบเกณฑ์ — สั่งพักคอมเมนต์ทั้งระบบแล้ว")
    return False


def _comment_is_live(xml: str, probe: str) -> bool:
    """ข้อความนี้ขึ้นเป็นคอมเมนต์จริงแล้วหรือยัง

    คอมเมนต์ที่ขึ้นจริงมีโครงแบบนี้เสมอ:
        [ชื่อคนคอมเมนต์ · เมื่อสักครู่]     ← แถวหัว อยู่เหนือข้อความ
        [ข้อความคอมเมนต์]
        [ถูกใจ · ตอบกลับ]                  ← แถวปุ่ม (คอมเมนต์ใหม่ๆ ยังไม่โผล่ทันที)

    ตอนแรกใช้แถวปุ่มเป็นตัวยืนยัน แต่คอมเมนต์ที่เพิ่งส่งยังไม่มีแถวนั้น เลยรายงานว่า
    "ยังไม่ขึ้น" ทั้งที่ขึ้นแล้ว — เปลี่ยนมาดู**แถวหัวที่มีเวลา** ซึ่งมาพร้อมกันเสมอ
    ส่วนข้อความที่ยังค้างอยู่ในช่องพิมพ์ไม่มีแถวหัวนำหน้า จึงแยกออกจากกันได้
    """
    if not probe:
        return False
    top = bottom = None
    for labels, (_, y1, _, y2) in iter_nodes(xml):
        if any(probe in label for label in labels):
            top, bottom = y1, y2
            break
    if top is None:
        return False
    # **หาป้ายเวลาแบบไม่ผูกกับระยะพิกเซลเลย** (แก้รอบสอง 28 ส.ค. 2569)
    #
    # รอบแรกใช้ระยะตายตัวขึ้น-ลง แล้วยังพลาด เพราะ **คอมเมนต์ที่แนบรูปสูงมาก**
    # วัดจากเครื่องจริง (REDMI 15C):
    #     ไม่มีรูป  ข้อความจบ y=1194 · เวลา y=1383  ห่าง 189
    #     มีรูป     ข้อความจบ y=636  · เวลา y=1383  ห่าง 747
    # เผื่อระยะเท่าไรก็ยังมีเคสที่เกิน — และเผื่อมากไปก็ไปคว้าเวลาของคอมเมนต์ถัดไป
    #
    # เปลี่ยนมาใช้กติกาที่ตรงความจริงกว่า: **ไล่ลงจากข้อความของเรา เจอป้ายเวลา
    # ก่อนเจอหัวคอมเมนต์ถัดไป = เป็นเวลาของคอมเมนต์เรา** ไม่ต้องเดาระยะ
    # และใช้ได้กับจอทุกขนาดโดยไม่ต้องแก้อะไรอีก
    #
    # ยังดูฝั่งบนด้วย เพราะแอปบางรุ่นวางเวลาไว้ในหัวแถว [ชื่อ · เวลา]
    rows = sorted((y1, " ".join(labels)) for labels, (_, y1, _, _) in iter_nodes(xml))
    head_at = None
    for y1, joined in rows:
        if any(mark in joined for mark in COMMENT_HEAD_MARKS):
            head_at = y1
        if y1 >= top:
            break
    for y1, joined in rows:
        if y1 < (head_at if head_at is not None else top):
            continue                      # ยังไม่ถึงหัวคอมเมนต์ของเรา
        if y1 > (bottom or top) and any(mark in joined for mark in COMMENT_HEAD_MARKS):
            break                         # ถึงหัวของคอมเมนต์ถัดไปแล้ว หยุด
        if any(hint in joined for hint in COMMENT_TIME_HINTS):

                return True
        # แถวปุ่มใต้ข้อความ (คอมเมนต์เก่าที่โหลดมาเต็มแล้ว)
        if top <= y1 <= top + COMMENT_REGION_HEIGHT:
            if any(hint in joined for hint in COMMENT_POSTED_HINTS):
                return True
    return False


# แจ้งเตือน "ผู้ดูแลอนุมัติรูปภาพของคุณใน <ชื่อกลุ่ม> แล้ว"
#
# ทางนี้ดีกว่าเลื่อนหาในฟีดมาก: กดแล้วเข้า "หน้าโพสต์ของเรา" ตรงๆ หน้าเดียวมีทั้ง
# ปุ่มถูกใจและช่องคอมเมนต์ ไม่มีโพสต์คนอื่นให้กดผิด และไม่ขึ้นกับการเรียงฟีด
#
# แต่ใช้แทนกันไม่ได้ทั้งหมด — แจ้งเตือนนี้โผล่ **หลังผู้ดูแลอนุมัติ** เท่านั้น
# (กลุ่มพวกนี้ตั้งค่าให้ตรวจก่อนโพสต์ขึ้น) ตอนเพิ่งกดโพสต์เสร็จจึงยังไม่มี
NOTIFICATION_APPROVED_HINTS = [
    "อนุมัติรูปภาพของคุณใน", "อนุมัติโพสต์ของคุณใน", "approved your post in",
]
NOTIFICATION_SCROLL_TRIES = 6


def open_post_from_notification(phone: Phone, group_name: str, caption: str) -> bool:
    """เปิดโพสต์ของเราผ่านแจ้งเตือน "ผู้ดูแลอนุมัติ…" คืน True เมื่อเข้าถึงโพสต์จริง"""
    probe = (group_name or "").strip()[:12]
    if not probe:
        return False
    phone.log(f"เปิดแจ้งเตือนเพื่อหาโพสต์ในกลุ่ม {group_name[:24]}")
    phone.shell(f"am force-stop {FB_PACKAGE}")
    time.sleep(1.5)
    phone.run(
        "shell", "am", "start", "-a", "android.intent.action.VIEW",
        "-d", "fb://notifications", timeout=30,
    )
    time.sleep(8.0)

    tried = 0
    for attempt in range(NOTIFICATION_SCROLL_TRIES + 1):
        xml = phone.dump()
        matches = []
        for labels, (x1, y1, x2, y2) in iter_nodes(xml):
            text = " ".join(labels)
            if not any(hint in text for hint in NOTIFICATION_APPROVED_HINTS):
                continue
            if probe not in text:
                continue
            point = ((x1 + x2) // 2, (y1 + y2) // 2)
            if point not in matches:
                matches.append(point)
        # กลุ่มเดียวอาจมีแจ้งเตือนหลายอัน (โพสต์เก่า/ใหม่) — ลองทีละอันจนกว่าจะเจอ
        # โพสต์ที่ต้องการ เดิมลองอันแรกอันเดียวแล้วยอมแพ้ทันที
        for point in matches:
            if tried >= 3:
                break
            tried += 1
            phone.tap(point)
            # รอเป็นรอบ ไม่ใช่ sleep ยาวครั้งเดียว — หน้าโพสต์บางทีโหลดช้าเกิน 7 วินาที
            # แล้วถูกตัดสินว่า "ไม่ใช่โพสต์ที่ต้องการ" ทั้งที่กำลังจะขึ้น
            deadline = time.time() + 16
            while time.time() < deadline:
                time.sleep(2.5)
                if _caption_box(phone.dump(), caption) is not None:
                    phone.log("  เข้าหน้าโพสต์ของเราแล้ว")
                    return True
            # เปิดมาแล้วแต่ไม่เห็นแคปชัน — โพสต์ที่มีคอมเมนต์แล้ว แจ้งเตือนจะพา
            # ลงไปโผล่ที่โซนคอมเมนต์เลย ตัวโพสต์อยู่เหนือขอบจอ ต้องเลื่อนขึ้นไปดู
            for _ in range(4):
                phone.vswipe("700", "1900", str(SCROLL_DURATION_MS),
                )
                time.sleep(1.8)
                if _caption_box(phone.dump(), caption) is not None:
                    phone.log("  เลื่อนขึ้นแล้วเจอโพสต์ของเรา")
                    return True
            phone.log("  แจ้งเตือนนี้ไม่ใช่โพสต์ที่ต้องการ — ย้อนกลับไปลองอันอื่น")
            phone.back()
            time.sleep(3.0)
        if matches and tried >= 3:
            break
        if attempt >= NOTIFICATION_SCROLL_TRIES:
            break
        phone.vswipe("1800", str(1800 - SCROLL_STEP), str(SCROLL_DURATION_MS),
        )
        time.sleep(2.0)
    phone.log("  ไม่เจอแจ้งเตือนของกลุ่มนี้ (อาจยังไม่ได้รับอนุมัติ)")
    return False


# หน้า "เปิดด้วยแอปไหน" ที่ระบบเด้งขึ้นมาเวลายิงลิงก์ facebook.com เข้าไป
#
# เดิมโค้ดถือว่าเจอหน้านี้ = เปิดไม่ได้ แล้วเลิกล้มไปเลย แต่หน้านี้แค่ต้องกดเลือก
# ซึ่งเป็นงานที่เราทำอยู่แล้วทั้งไฟล์ — เลือก Facebook แล้วกด "ครั้งเดียว"
CHOOSER_MARK_HINTS = ["เปิดด้วย", "Open with", "เปิดโดยใช้", "การดำเนินการที่ทำได้"]
CHOOSER_APP_HINTS = ["Facebook", "เฟซบุ๊ก"]
# ต้องกด "เฉพาะครั้งนี้" ไม่ใช่ "ทุกครั้ง" — ตั้งเป็นค่าเริ่มต้นถาวรจะไปเปลี่ยน
# พฤติกรรมเครื่องผู้ใช้ในเรื่องที่ไม่เกี่ยวกับงานเรา
# (ยกป้ายจากจอจริง 13 ส.ค.: "เปิดด้วย | Facebook | เฉพาะครั้งนี้ | ทุกครั้ง")
CHOOSER_ONCE_HINTS = [
    "เฉพาะครั้งนี้", "ครั้งเดียว", "แค่ครั้งนี้", "Just once", "JUST ONCE",
]


def _pick_facebook_in_chooser(phone: Phone) -> bool:
    """ถ้าติดหน้าเลือกแอปอยู่ ให้เลือก Facebook — คืน True เมื่อได้กดจริง

    ตรวจป้ายหัวหน้าก่อนเสมอ ห้ามไล่หาคำว่า "Facebook" ลอยๆ เพราะในแอป Facebook
    เองก็มีคำนี้เต็มไปหมด จะกลายเป็นกดมั่วในหน้าปกติ
    """
    xml = phone.dump()
    if not any(screen_has(xml, hint) for hint in CHOOSER_MARK_HINTS):
        return False
    row = phone.find(xml, CHOOSER_APP_HINTS)
    if row is None:
        phone.log("  ติดหน้าเลือกแอปแต่ไม่เจอช่อง Facebook")
        return False
    phone.tap(row)
    time.sleep(1.5)
    once = phone.find(phone.dump(), CHOOSER_ONCE_HINTS)
    if once is not None:
        phone.tap(once)
    time.sleep(3.0)
    return True


# รอหน้าโพสต์โหลดหลังยิงลิงก์ — ลิงก์ย่อต้องวิ่งตาม redirect ก่อน ช้ากว่า fb://
POST_LINK_WAIT = 6.0
POST_LINK_TRIES = 3


def post_link_forms(link: str, group_id: str = "", post_id: str = "") -> list[tuple]:
    """ลิงก์ทุกแบบที่จะลองยิงเข้าแอป เรียงจากที่พิสูจน์แล้วว่าได้ผลก่อน

    (ชื่อที่เอาไว้ log, url, ระบุแพ็กเกจไหม)

    **วัดกับเครื่องจริง 13 ส.ค. ด้วยลิงก์ของงาน p540023972:**

      ลิงก์ย่อ เปล่าๆ (ไม่ระบุแอป)   → เข้าหน้าโพสต์ เห็นแคปชัน ✅
      ลิงก์ย่อ + `-p com.facebook.katana` → หน้าเลือกแอป (ResolverActivity) ❌
      permalink + ระบุแอป             → หน้าเลือกแอป ❌
      fb://group/<gid>/permalink/<pid> → ฟีดหลัก ❌
      fb://post/<pid>                  → ฟีดหลัก ❌

    **การระบุแพ็กเกจคือตัวที่ทำให้พัง** ไม่ใช่ตัวลิงก์ — ระบบมองว่ามีหลายทางเปิดได้
    เลยถามก่อน ปล่อยให้ระบบเลือกเองกลับเข้าแอปตรงๆ เลย

    ตัดรูปแบบ fb:// ทิ้งทั้งหมด เพราะพิสูจน์แล้วว่าไปฟีดหลักแน่นอน ลองไปก็เสีย
    เวลากลุ่มละ ~15 วินาทีเปล่าๆ ส่วนแบบระบุแอปเก็บไว้ท้ายสุดเป็นทางสำรอง
    (มีตัวกดหน้าเลือกแอปรออยู่แล้ว)
    """
    forms: list[tuple] = []
    if link:
        forms.append(("ลิงก์ที่เก็บไว้", link, False))
    if group_id and post_id:
        forms.append((
            "permalink",
            f"https://www.facebook.com/groups/{group_id}/permalink/{post_id}/",
            False,
        ))
    if link:
        forms.append(("ลิงก์ที่เก็บไว้ + ระบุแอป", link, True))
    return forms


def open_post_link(phone: Phone, link: str, caption: str,
                   group_id: str = "", post_id: str = "") -> bool:
    """เปิดโพสต์กลับมาจากลิงก์ที่เก็บไว้ — คืน True เมื่อเห็นแคปชันของเราจริง

    ยืนยันด้วย**แคปชัน**เท่านั้น ไม่เชื่อว่า "ยิง intent ผ่าน = เปิดถูกโพสต์"
    เพราะแอปเวลารับ deep link ไม่ได้จะเด้งเข้าฟีดหลักแบบเงียบๆ ซึ่ง am ก็ยัง
    รายงานว่าสำเร็จ ถ้าไม่เช็คแคปชันจะเข้าใจว่าเปิดได้แล้วไปกดถูกใจโพสต์คนอื่น

    ข้อจำกัดที่บันทึกไว้เดิม (resolve_post_link) บอกว่าเปิดไม่ได้ทุกแบบ —
    แต่ตอนนั้นยังไม่ได้จัดการหน้า "เปิดด้วยแอปไหน" ที่เด้งมาบัง รอบนี้จึงลองใหม่
    ถ้าสุดท้ายเปิดไม่ได้จริง ตัวเรียกจะถอยไปทำในฟีดเหมือนเดิม ไม่พังทั้งงาน
    """
    forms = post_link_forms(link, group_id, post_id)
    if not forms:
        return False
    for name, url, with_package in forms:
        phone.log(f"  เปิดโพสต์จากลิงก์ ({name})")
        phone.shell(f"am force-stop {FB_PACKAGE}")
        time.sleep(1.5)
        args = ["shell", "am", "start", "-a", "android.intent.action.VIEW", "-d", url]
        if with_package:
            args += ["-p", FB_PACKAGE]
        try:
            phone.run(*args, timeout=40)
        except Exception as error:          # ยิง intent พังต้องไม่ล้มทั้งกลุ่ม
            phone.log(f"    ยิงลิงก์ไม่ผ่าน: {error}")
            continue
        time.sleep(POST_LINK_WAIT)
        _pick_facebook_in_chooser(phone)
        for _ in range(POST_LINK_TRIES):
            if _caption_box(phone.dump(), caption) is not None:
                phone.log("    เข้าหน้าโพสต์จากลิงก์แล้ว")
                return True
            time.sleep(3.0)
    phone.log("  เปิดโพสต์จากลิงก์ไม่ได้ทุกแบบ")
    return False


def open_own_post(phone: Phone, group_id: str, group_name: str, caption: str,
                  clipboard=None, link: str = "", post_id: str = "") -> dict:
    """เปิดโพสต์ของเรา แล้วบอกว่าเข้าถึงได้ทางไหน + ลิงก์ที่เก็บมาได้ระหว่างทาง

    ลำดับที่ใช้ และเหตุผล:
      1. **ลิงก์ที่เคยเก็บไว้** — เร็วที่สุดและได้หน้าโพสต์เดี่ยวเลย ไม่ต้องพึ่ง
         ทั้งแจ้งเตือนและการเรียงฟีด
      2. **แจ้งเตือน** — กดแล้วเข้าหน้าโพสต์ของเราหน้าเดียว ไม่มีโพสต์คนอื่นให้กดผิด
         และไม่ขึ้นกับการเรียงฟีด (ฟีดกลุ่มเรียงตาม "เกี่ยวข้องมากที่สุด" โพสต์เก่า
         จมหาย — เลื่อน 14 รอบยังไม่เจอมาแล้ว 3 กลุ่ม)
      3. **ฟีดกลุ่ม** — ทางสุดท้าย และพอเจอแล้วให้ **คัดลอกลิงก์เก็บไว้ก่อน**
         แล้วเปิดผ่านลิงก์นั้นเพื่อย้ายไปทำงานบนหน้าโพสต์เดี่ยว

    ทำไมต้องดิ้นไปหน้าโพสต์เดี่ยวให้ได้: ในฟีดมีโพสต์คนอื่นปนอยู่ ทุกขั้นตอนต้อง
    คอยพิสูจน์ว่ากำลังแตะของเราไม่ใช่ของคนอื่น และ Facebook ยังแทรกแถบสินค้า
    ("สำหรับคุณ (N)") คั่นระหว่างแคปชันกับแถบปุ่มจนระยะเพี้ยน ส่วนหน้าโพสต์เดี่ยว
    ทั้งหน้าคือโพสต์เรา ไม่มีอะไรให้กดผิดเลย

    คืน {"route": "link"|"noti"|"feed"|"", "link": ลิงก์ที่เพิ่งเก็บได้ (อาจว่าง)}
    """
    if link and open_post_link(phone, link, caption, group_id, post_id):
        return {"route": "link", "link": ""}
    if open_post_from_notification(phone, group_name, caption):
        return {"route": "noti", "link": ""}
    phone.log("  ลองทางฟีดแทน")
    try:
        phone.open_group(group_id)
    except PostError as error:
        phone.log(f"  เปิดกลุ่มไม่ได้: {error}")
        return {"route": "", "link": ""}
    for _ in range(FEED_SCROLL_TRIES):
        if _caption_box(phone.dump(), caption) is not None:
            phone.log("  เจอโพสต์ในฟีดแล้ว")
            # เก็บลิงก์ตรงนี้เลย ตอนที่แคปชันยังอยู่บนจอ — เป็นจังหวะเดียวที่
            # ชี้ปุ่ม … ของโพสต์เราได้แน่นอน (ปุ่มตัวที่อยู่เหนือแคปชันและใกล้สุด)
            # ถ้าไปกดถูกใจ/คอมเมนต์ก่อน จอจะเลื่อนจนหมุดนี้หลุดไปแล้ว
            fresh = copy_post_link(phone, group_id, caption, clipboard) if clipboard else ""
            if fresh and open_post_link(phone, fresh, caption, group_id):
                return {"route": "link", "link": fresh}
            return {"route": "feed", "link": fresh}
        phone.vswipe("1800", str(1800 - SCROLL_STEP), str(SCROLL_DURATION_MS),
        )
        time.sleep(1.8)
    phone.log("  หาโพสต์ในฟีดไม่เจอ")
    return {"route": "", "link": ""}


FEED_SCROLL_TRIES = 12
# ทางที่ได้ "หน้าโพสต์เดี่ยว" — ทั้งสองทางนี้ทั้งหน้าคือโพสต์ของเรา
SINGLE_POST_ROUTES = ("noti", "link")


def followup_groups(
    adb: str, serial: str, caption: str, targets: list[dict],
    comment: str = "", log=print, stop=lambda: False, on_result=None,
    comment_images=None, clipboard=None,
) -> list[dict]:
    """ตามเก็บงานทีหลัง: เปิดโพสต์จากแจ้งเตือน แล้วกดถูกใจ + คอมเมนต์

    ใช้กับกลุ่มที่ต้องรอผู้ดูแลอนุมัติ — ตอนโพสต์เสร็จใหม่ๆ โพสต์ยังไม่ขึ้นให้ใครเห็น
    จึงยังกดถูกใจไม่ได้ ต้องกลับมาทำรอบสองหลังได้รับอนุมัติ

    targets = [{"group_id": ..., "name": ...}]
    """
    phone = Phone(adb, serial, log=log)
    # ไม่มีเน็ตก็เปิดโพสต์จากแจ้งเตือนไม่ได้ และคอมเมนต์จะค้างในคิวเหมือนกัน
    require_network(phone)
    log("เน็ตมือถือใช้ได้")
    original_ime = phone.use_adb_keyboard() if _as_texts(comment) else ""
    results: list[dict] = []
    try:
        for index, item in enumerate(targets, start=1):
            if stop():
                log("ผู้ใช้สั่งหยุด")
                break
            name = item.get("name", "")
            log(f"[{index}/{len(targets)}] {name[:30]}")
            if not phone.online():
                log(f"  {OFFLINE_MESSAGE}")
                break
            # ห้ามใส่ posted ลงไปเอง — "โพสต์ขึ้นหรือยัง" เป็นผลของรอบโพสต์
            # รอบตามเก็บแค่ "เปิดโพสต์นั้นไม่เจอ" ไม่ได้แปลว่าโพสต์ไม่ขึ้น
            # (เจอจริง: เขียน posted=False ทับของดี แล้วรอบถัดไปข้ามกลุ่มนั้นไปเลย)
            entry = {"group_id": item.get("group_id", ""), "index": index,
                     "total": len(targets)}
            opened = open_own_post(
                phone, entry["group_id"], name, caption, clipboard=clipboard,
                link=item.get("link", ""), post_id=item.get("post_id", ""),
            )
            route = opened["route"]
            # ลิงก์ที่เพิ่งคัดลอกระหว่างทาง (ทางฟีด) — เก็บทันทีไม่ต้องรอจบกลุ่ม
            if opened["link"]:
                entry["link"] = opened["link"]
            have_link = bool(entry.get("link") or item.get("link"))
            if not route:
                entry["error"] = "เปิดโพสต์ไม่ได้ (ทั้งลิงก์ แจ้งเตือน และฟีด)"
            else:
                single = route in SINGLE_POST_ROUTES
                entry["liked"] = like_post_of(phone, caption, single_post=single)
                if _as_texts(comment):
                    entry.update(
                        comment_post_of(phone, caption, comment,
                                        single_post=single, photos=comment_images)
                    )
                # เก็บลิงก์เป็นขั้นสุดท้ายของกลุ่มนี้ — เมนู … เปิดทับหน้าจอ
                # ถ้าทำก่อนจะไปบังปุ่มถูกใจกับช่องคอมเมนต์
                # เก็บไม่ได้ไม่ถือว่างานล้ม ลิงก์เป็นของแถม
                if clipboard is not None and not have_link:
                    got = (
                        copy_link_single_post(phone, clipboard) if single
                        else copy_post_link(phone, entry["group_id"], caption, clipboard)
                    )
                    # เก็บไม่ได้ = ไม่ต้องเขียนคีย์นี้เลย ปล่อยลิงก์เดิมที่เคยได้มาไว้
                    # ถ้าเขียน "" ลงไป จะไปทับลิงก์ดีของรอบก่อนหายหมด
                    if got:
                        entry["link"] = got
            results.append(entry)
            if on_result:
                on_result(entry)
    finally:
        if original_ime:
            phone.restore_keyboard(original_ime)
    return results


def copy_post_link(phone: Phone, group_id: str, caption: str, clipboard) -> str:
    """เก็บลิงก์ของโพสต์ที่เพิ่งลง จากเมนู "..." → คัดลอกลิงก์

    หาโพสต์ของเราด้วย**ข้อความแคปชัน** ไม่ใช่ "เอาโพสต์บนสุด" เพราะฟีดกลุ่มเรียงตาม
    "เกี่ยวข้องมากที่สุด" โพสต์บนสุดอาจเป็นของคนอื่น แล้วจะได้ลิงก์ผิดโพสต์ไปเลย
    ปุ่ม "..." ของโพสต์เดียวกันคือตัวที่อยู่**เหนือข้อความและใกล้ที่สุด** (แถวหัวโพสต์)

    เก็บไม่ได้ไม่ถือว่าโพสต์ล้มเหลว — คืน "" แล้วไปต่อ ลิงก์เป็นของแถม
    """
    probe = caption.strip()[:12]
    if not probe:
        return ""
    xml = phone.dump()
    caption_top = None
    for labels, (_, y1, _, _) in iter_nodes(xml):
        if any(probe in label for label in labels):
            caption_top = y1
            break
    if caption_top is None:
        phone.log("  ไม่เห็นโพสต์ของเราบนจอ — ข้ามการเก็บลิงก์")
        return ""

    menu: tuple[int, int] | None = None
    menu_bottom = -1
    for labels, (x1, y1, x2, y2) in iter_nodes(xml):
        text = " ".join(labels).lower()
        if not any(hint.lower() in text for hint in POST_MENU_HINTS):
            continue
        if y2 > caption_top:
            continue                      # อยู่ใต้ข้อความ = ของโพสต์ถัดไป
        if y2 > menu_bottom:
            menu_bottom = y2
            menu = ((x1 + x2) // 2, (y1 + y2) // 2)
    if menu is None:
        phone.log("  หาปุ่ม … ของโพสต์ไม่เจอ — ข้ามการเก็บลิงก์")
        return ""

    return _copy_link_from_menu(phone, menu, clipboard)


def copy_link_single_post(phone: Phone, clipboard) -> str:
    """เก็บลิงก์จาก "หน้าโพสต์เดี่ยว" (เข้ามาทางแจ้งเตือน)

    ทั้งหน้าคือโพสต์ของเรา ปุ่ม … ของตัวโพสต์จึงอยู่**บนสุดของหน้า**เสมอ
    ส่วนที่อยู่ต่ำลงมาเป็นของคอมเมนต์ — เอาตัวบนสุดได้เลย

    ห้ามใช้แคปชันเป็นหมุดแบบตอนอยู่ในฟีด เพราะขั้นกดถูกใจ/คอมเมนต์ก่อนหน้านี้
    เลื่อนจอจนแคปชันหลุดขอบบนไปแล้ว
    """
    if clipboard is None:
        return ""
    # ปุ่ม … อยู่**หัวหน้าจอ** (วัดจริง y=223) แต่ขั้นไลก์กับคอมเมนต์ก่อนหน้านี้
    # เลื่อนจอลงไปแล้ว ปุ่มจึงพ้นขอบบน ต้องเลื่อนกลับขึ้นไปหาก่อน
    # (วัดจริง 11 ส.ค.: เพิ่งเปิดหน้า เจอ 1 ตัว · เลื่อนลง 2 รอบ เจอ 0 ตัว)
    for attempt in range(LINK_TOP_SCROLL_TRIES + 1):
        best: tuple[int, int] | None = None
        best_top = -1
        for labels, (x1, y1, x2, y2) in iter_nodes(phone.dump()):
            text = " ".join(labels).lower()
            if not any(hint.lower() in text for hint in POST_MENU_HINTS):
                continue
            if best is None or y1 < best_top:
                best_top = y1
                best = ((x1 + x2) // 2, (y1 + y2) // 2)
        if best is not None:
            return _copy_link_from_menu(phone, best, clipboard)
        if attempt >= LINK_TOP_SCROLL_TRIES:
            break
        phone.vswipe("700", str(700 + SCROLL_STEP), str(SCROLL_DURATION_MS),
        )
        time.sleep(1.5)
    phone.log("  หาปุ่ม … ของโพสต์ไม่เจอ — ข้ามการเก็บลิงก์")
    return ""


def _find_in_sheet(phone: Phone, hints: list[str], tries: int = MENU_SCROLL_TRIES):
    """หาเมนูในแผ่นที่เลื่อนได้ — ไม่เจอบนจอแรกให้เลื่อนขึ้นแล้วหาใหม่

    **เมนูของ Facebook เป็นแผ่นเลื่อนได้ ไม่ใช่รายการสั้นๆ ที่เห็นครบในจอเดียว**
    ของเดิมถ่ายจอครั้งเดียวแล้วสรุปว่าไม่มี ผลที่วัดได้จาก log จริง:
    เก็บลิงก์สำเร็จ 68 · "ไม่มีเมนูคัดลอกลิงก์" 29 ครั้ง (84% ของความล้มทั้งหมด)
    ส่วนความล้มฝั่งคลิปบอร์ดเป็น 0 — ปัญหาอยู่ที่หาเมนูไม่เจอล้วนๆ

    เป็นรูปแบบเดียวกับที่ทำให้ `verify_liked` พังมาตลอด: สมมติว่า dump ครั้งเดียว
    เห็นเนื้อหาทั้งหมด ทั้งที่หน้าจอ Android เลื่อนได้เกือบทุกอย่าง
    """
    found = phone.find(phone.dump(), hints)
    for _ in range(tries):
        if found is not None:
            return found
        # ปัดขึ้นภายในแผ่นเมนู (แผ่นอยู่ครึ่งล่างของจอ)
        phone.vswipe("1600", "1100", str(SCROLL_DURATION_MS),
        )
        time.sleep(1.2)
        found = phone.find(phone.dump(), hints)
    return found


def _copy_link_from_menu(phone: Phone, menu: tuple[int, int], clipboard) -> str:
    """กดปุ่ม … แล้วไล่เมนูไปหา "คัดลอกลิงก์" แล้วอ่านค่าที่ได้จากคลิปบอร์ด"""
    phone.tap(menu)
    time.sleep(2.0)
    copy = _find_in_sheet(phone, COPY_LINK_HINTS)
    if copy is None:
        # ชั้นแรกไม่มี — เข้าไปดูใน "ตัวเลือกเพิ่มเติม" อีกชั้น
        more = _find_in_sheet(phone, MORE_OPTIONS_HINTS)
        if more is not None:
            phone.tap(more)
            time.sleep(2.0)
            copy = _find_in_sheet(phone, COPY_LINK_HINTS)
    if copy is None:
        phone.log("  ไม่มีเมนูคัดลอกลิงก์ — ข้ามการเก็บลิงก์ (เลื่อนหาแล้วไม่เจอ)")
        phone.back()
        return ""

    # ล้างท่อก่อน แล้ว "รอให้มือถือแจ้งว่าคลิปบอร์ดเปลี่ยน" หลังกด
    #
    # ห้ามใช้วิธีถามค่าคลิปบอร์ดตรงๆ: Android 10+ ห้ามอ่านคลิปบอร์ดจากเบื้องหลัง
    # คำถามนั้นจึงได้แต่ค่าที่ scrcpy จำไว้ล่าสุด (ตรวจกับมือถือจริงแล้ว — กดคัดลอก
    # สำเร็จจนเมนูปิด แต่ถามกลับมายังได้ค่าเดิม) การรอสัญญาณแจ้งเตือนจึงเป็นทางเดียว
    # ที่รู้ค่าจริง และยังใช้ยืนยันไปในตัวว่า "คัดลอกติดจริง" ไม่ใช่ของเก่าค้างท่อ
    try:
        clipboard.drain()
    except Exception:
        pass
    phone.tap(copy)
    try:
        link = (clipboard.wait_change(8.0) or "").strip()
    except Exception as error:            # อ่านคลิปบอร์ดพังต้องไม่ล้มทั้งงาน
        phone.log(f"  อ่านลิงก์จากคลิปบอร์ดไม่ได้: {error}")
        return ""
    if not link:
        phone.log("  กดคัดลอกแล้วแต่คลิปบอร์ดไม่เปลี่ยน — ไม่เก็บ")
        return ""
    # ต้องเป็นลิงก์ Facebook จริง
    if "facebook.com" not in link:
        phone.log("  คลิปบอร์ดไม่ใช่ลิงก์ Facebook — ไม่เก็บ")
        return ""
    phone.log(f"  เก็บลิงก์โพสต์แล้ว: {link[:70]}")
    return link


def verify_liked(phone: Phone, group_id: str, caption: str) -> dict:
    """เปิดกลุ่มซ้ำแล้วตรวจว่าโพสต์ขึ้นจริงและถูกใจไปแล้วจริง

    ตรวจทีหลังต่างหากเพราะตอนกดเสร็จใหม่ๆ ฟีดยังไม่นิ่ง บางทีขึ้นว่าถูกใจแล้ว
    แต่พอรีเฟรชจริงกลับไม่ติด — ต้องเปิดใหม่ถึงจะเชื่อได้

    ต้องเปิดด้วย fb://group/ เท่านั้น — ลิงก์ที่เก็บมาจากปุ่ม "คัดลอกลิงก์" เป็น
    ลิงก์ย่อแบบ /share/p/… ซึ่งเปิดกลับเข้าโพสต์ไม่ได้ (ตรวจกับมือถือจริงแล้ว:
    ยิงเข้าไปได้แค่หน้าเข้าแอป ส่วนถ้าระบุแอปจะเด้งหน้าเลือกแอปแทน)
    ลิงก์นั้นมีไว้ให้ "คนกดเปิดดู" ไม่ใช่ให้เครื่องเปิด
    """
    phone.run(
        "shell", "am", "start", "-a", "android.intent.action.VIEW",
        "-d", f"fb://group/{group_id}", timeout=30,
    )
    time.sleep(8.0)
    xml = phone.dump()
    # ข้อความยาวถูกตัดท้ายด้วย "..." จึงเทียบแค่ท่อนต้น
    probe = caption.strip()[:12]
    found_post = screen_has(xml, probe)

    # **ต้องเลื่อนหาด้วย ไม่ใช่ดูแค่จอแรก**
    #
    # ของเดิมเปิดกลุ่ม รอ 8 วินาที ถ่ายจอครั้งเดียว แล้วสรุปเลยว่าเจอ/ไม่เจอ
    # ผลที่วัดได้จากของจริง 106 ครั้ง: บอกว่า "เจอโพสต์" แค่ 10 ครั้ง (9%)
    # และ "ถูกใจแล้ว" **0 ครั้ง** — ตัวตรวจที่ตอบว่าไม่ผ่าน 100% ไม่ใช่ตัวตรวจ
    #
    # ที่ขัดกันเองชัดๆ: ครั้งที่กดถูกใจโพสต์ตัวเองสำเร็จ 79 ครั้ง ตัวตรวจกลับบอกว่า
    # "ไม่เจอโพสต์" ถึง 71 ครั้ง — กดถูกใจได้แปลว่าโพสต์อยู่บนจอตอนนั้นแน่นอน
    # (คอมเมนต์ 63/68 · เก็บลิงก์ 58/64 ก็ขัดกันแบบเดียวกัน)
    #
    # สาเหตุ: ฟีดกลุ่มเรียงตาม "ความเกี่ยวข้อง" ไม่ใช่เวลา และจอแรกมักเป็น
    # หัวกลุ่ม + ช่องเขียนโพสต์ + โพสต์ปักหมุด โพสต์ของเราจึงอยู่ต่ำกว่าขอบจอ
    # ยืนยันจาก log: ตรวจซ้ำใช้เวลา 10-12 วินาทีต่อกลุ่ม เท่ากับ sleep(8)+dump
    # พอดี = ไม่ได้ใช้เวลาค้นหาเลยแม้แต่วินาทีเดียว
    scrolled = 0
    while not found_post and scrolled < VERIFY_SCROLL_TRIES:
        phone.vswipe(str(700 + SCROLL_STEP), "700", str(SCROLL_DURATION_MS),
        )
        time.sleep(1.8)
        scrolled += 1
        xml = phone.dump()
        found_post = screen_has(xml, probe)
    if found_post and scrolled:
        phone.log(f"  เลื่อนลง {scrolled} ครั้งถึงเจอโพสต์ของเรา")
    # ต้องดูป้าย "ถูกใจแล้ว" **ใต้โพสต์ของเรา** ไม่ใช่ที่ไหนก็ได้บนจอ
    # (ไม่งั้นไปนับไลก์ของโพสต์คนอื่นที่อยู่บนจอเดียวกัน)
    bottom = _caption_bottom(xml, caption)
    # ป้าย "ถูกใจแล้ว" ไม่มีในแอปรุ่นนี้ จึงดูที่ตัวนับรีแอคชันเป็นหลัก
    # (โพสต์เพิ่งลงไม่กี่นาที ถ้ามีรีแอคชันแล้วก็คือของเราที่เพิ่งกด)
    # ตัวนับรีแอคชันต้องอ่านจากแถวที่ติดเหนือปุ่มถูกใจ**ของโพสต์เรา**เท่านั้น
    # กวาดกว้างๆ จะไปเจอตัวนับของโพสต์ข้างๆ แล้วรายงานผิดว่าถูกใจแล้ว
    liked = False
    if bottom is not None:
        liked = liked_near(xml, bottom, span=POST_REGION_HEIGHT)
        if not liked:
            own = [
                point for point in like_buttons(xml)
                if bottom <= point[1] <= bottom + POST_REGION_HEIGHT
            ]
            if own:
                liked = (_post_reactions(xml, own[0][1]) or 0) >= 1
    phone.log(
        f"  ตรวจซ้ำ: เจอโพสต์={'ใช่' if found_post else 'ไม่เจอ'} "
        f"· ถูกใจแล้ว={'ใช่' if liked else 'ยัง'}"
    )
    return {"group_id": group_id, "post_visible": found_post, "liked": liked}


def action_bar_top(xml: str, after: int | None = None) -> int | None:
    """ขอบบนของ "แถบปุ่ม" ของโพสต์ — ใช้หมุด "แสดงความคิดเห็น" ตัวเดียวกับที่หาปุ่มถูกใจ

    after = เอาเฉพาะแถบที่อยู่ใต้ y นี้ลงไป (ใช้ตอนอยู่ในฟีดที่มีโพสต์คนอื่นปน
    ต้องส่งขอบล่างของแคปชันเราเข้ามา ไม่งั้นได้แถบของโพสต์ที่อยู่เหนือขึ้นไป)
    """
    best = None
    for labels, box, clickable in iter_widgets(xml):
        if not clickable:
            continue
        if not any(label in COMMENT_BUTTON_LABELS for label in labels):
            continue
        if after is not None and box[1] < after:
            continue
        if best is None or box[1] < best:
            best = box[1]
    return best


# ── แถวตัวนับใต้โพสต์ ────────────────────────────────────────────────────
#
# **ผังต่างกันคนละแบบระหว่างสองหน้า** (วัดจากจอจริง 13 ส.ค.):
#
#   ในฟีด            ตัวนับ y=2128 → แถบปุ่ม y=2265     ตัวนับอยู่ "เหนือ" ปุ่ม
#   หน้าที่เปิดจากลิงก์  แถบปุ่ม y=1479 → ตัวนับ y=1594   ตัวนับอยู่ "ใต้" ปุ่ม
#
# จึงต้องกวาดทั้งสองฝั่งของแถบปุ่ม ไม่ใช่ฝั่งเดียว — เดิมอ่านเฉพาะฝั่งเหนือตามผัง
# ของฟีด พอไปเจอหน้าที่เปิดจากลิงก์เลยได้ว่างเปล่าทุกกลุ่ม
#
# ขอบล่างต้องหยุดที่ "แถวตัวกรองคอมเมนต์" เสมอ ทุกอย่างที่ต่ำกว่านั้นคือคอมเมนต์
# ของคนอื่น ซึ่งมีตัวนับถูกใจของตัวเอง กวาดเลยไปจะได้เลขของคอมเมนต์มาแทนของโพสต์
COMMENT_FILTER_HINTS = [
    "กำลังแสดงความคิดเห็น", "เกี่ยวข้องมากที่สุด", "Most relevant",
]
STAT_BELOW_GAP = 260

# รูปแบบตัวนับรีแอคชันที่เจอจริงแล้วทั้งสองแบบ:
#   "37 ความรู้สึก, ความคิดเห็น 63 รายการ"        (ในฟีด)
#   "คุณและคนอื่นๆ อีก 1 คนแสดงความรู้สึก"          (หน้าที่เปิดจากลิงก์)
# แบบหลังต้อง +1 เพราะ "คุณ" ไม่ถูกนับรวมในเลขนั้น
REACT_OTHERS_RE = re.compile(r"คุณและคนอื่นๆ\s*อีก\s*([\d,]+)\s*คน")
REACT_ONLY_OTHERS_RE = re.compile(r"คนอื่นๆ\s*อีก\s*([\d,]+)\s*คน")

# ยอดคอมเมนต์กับยอดแชร์: **หน้าที่เปิดจากลิงก์ไม่แสดงเลขให้เลย**ถ้ายอดยังน้อย
# (ตรวจของจริง: โพสต์ที่มีคอมเมนต์ 1 อัน ไม่มีป้ายบอกจำนวนเลยสักที่)
# จึงต้องยอมคืน None แล้วรายงานเป็น "?" — ห้ามเดาเป็น 0 เพราะ "ไม่มีใครคอมเมนต์"
# กับ "แอปไม่แสดงเลข" คนละเรื่องกัน เดาแล้วผู้ใช้ตัดสินใจผิดจากเลขปลอม
STAT_PATTERNS = {
    "reactions": [re.compile(r"([\d,]+)\s*(?:ความรู้สึก|reactions?)", re.I)],
    "comments": [
        re.compile(r"ความคิดเห็น\s*([\d,]+)\s*รายการ"),
        re.compile(r"ดูความคิดเห็นทั้งหมด\s*([\d,]+)"),
        re.compile(r"([\d,]+)\s*(?:ความคิดเห็น|comments?)", re.I),
    ],
    "shares": [
        re.compile(r"([\d,]+)\s*(?:ครั้งของการแชร์|การแชร์|shares?)", re.I),
        re.compile(r"แชร์\s*([\d,]+)\s*ครั้ง"),
        re.compile(r"([\d,]+)\s*แชร์"),
    ],
}


def _first_number(text: str, patterns: list) -> int | None:
    for pattern in patterns:
        found = pattern.search(text)
        if not found:
            continue
        for value in found.groups():
            if value:
                return int(value.replace(",", ""))
    return None


def _reaction_total(text: str) -> int | None:
    """ยอดรีแอคชันจากข้อความตัวนับ — รองรับทั้งแบบตัวเลขล้วนและแบบบรรยาย"""
    found = REACT_OTHERS_RE.search(text)
    if found:
        return int(found.group(1).replace(",", "")) + 1     # +1 = ตัวเราเอง
    direct = _first_number(text, STAT_PATTERNS["reactions"])
    if direct is not None:
        return direct
    found = REACT_ONLY_OTHERS_RE.search(text)
    if found:
        return int(found.group(1).replace(",", ""))
    if SELF_REACTION_HINT in text:
        return 1                       # มีแต่เรากด ตัวเลขไม่ขึ้น
    return None


def stat_band(xml: str, after: int | None = None) -> tuple[int, int] | None:
    """ช่วง y ที่ตัวนับของโพสต์นี้อยู่ (None = ยังหาแถบปุ่มไม่เจอ)"""
    top = action_bar_top(xml, after=after)
    if top is None:
        return None
    low = top + STAT_BELOW_GAP
    for labels, (_, y1, _, _), _ in iter_widgets(xml):
        if y1 <= top or not labels:
            continue
        if any(hint in " ".join(labels) for hint in COMMENT_FILTER_HINTS):
            low = min(low, y1)          # เจอเส้นแบ่งโซนคอมเมนต์ — หยุดตรงนี้
            break
    return max(0, top - REACTION_GAP), low


def post_stat_numbers(xml: str, after: int | None = None) -> dict:
    """อ่านยอด ถูกใจ/คอมเมนต์/แชร์ ของโพสต์จากจอตอนนี้ ({} = ยังหาแถบปุ่มไม่เจอ)

    อ่านจาก**ช่วงแคบๆ รอบแถบปุ่ม**เท่านั้น ห้ามกวาดทั้งจอ ด้วยเหตุผลเดียวกับ
    _post_reactions: กวาดกว้างจะไปเก็บตัวนับของโพสต์ข้างๆ หรือของคอมเมนต์
    ที่อยู่ใต้ลงไป แล้วรายงานเลขของคนอื่นเป็นของเรา
    """
    band = stat_band(xml, after=after)
    if band is None:
        return {}
    band_top, band_low = band
    texts = [
        " ".join(labels)
        for labels, (_, y1, _, _), _ in iter_widgets(xml)
        if band_top <= y1 < band_low and labels
    ]
    joined = " ".join(texts)
    stats = {key: _first_number(joined, patterns)
             for key, patterns in STAT_PATTERNS.items()}
    stats["reactions"] = _reaction_total(joined)
    return stats


STAT_SCROLL_TRIES = 4

# ── นับคอมเมนต์เอง ───────────────────────────────────────────────────────
#
# ต้องนับเองเพราะ**หน้าที่เปิดจากลิงก์ไม่มีป้ายบอกจำนวนคอมเมนต์เลยสักที่**
# (ไล่ดูจนสุดโซนคอมเมนต์แล้ว 13 ส.ค. เจอแต่ตัวคอมเมนต์เรียงกัน ไม่มีตัวเลขรวม)
#
# นับจาก "ข้อความของคอมเมนต์" ไม่ใช่ปุ่มตอบกลับ เพราะจอที่เลื่อนต่อกันมีคอมเมนต์
# เดิมค้างอยู่ด้วย ต้องมีตัวระบุตัวตนถึงจะไม่นับซ้ำ — ปุ่มตอบกลับของทุกคอมเมนต์
# ที่คนเดียวกันเขียนมีป้ายเหมือนกันเป๊ะ ("ตอบกลับความคิดเห็นของ Kamolchanok")
# ใช้แยกไม่ได้เลย
COMMENT_TEXT_MIN = 12
# ป้ายที่อยู่ในโซนคอมเมนต์แต่ไม่ใช่ตัวคอมเมนต์ — ยกมาจากของที่นับเกินจริง
# (รอบแรกนับได้ 6 ทั้งที่มีคอมเมนต์ 2: ติดป้ายตัวกรอง ชื่อคนเขียน รูปในช่องพิมพ์
#  และหัวหน้าจอเข้ามาด้วย)
COMMENT_CHROME_HINTS = (
    "สมาชิก", "ลิงก์ที่แชร์", "ความรู้สึก", "ตอบกลับ", "โหวต", "รูปโปรไฟล์",
    "เขียนความคิดเห็น", "กำลังแสดงความคิดเห็น", "โพสต์ต่อวัน", "แชร์กับ",
    "เกี่ยวข้องมากที่สุด", "Action chip", "profile picture", "โพสต์ของ",
    "ใหม่ที่สุด", "ทั้งหมด",
)
# ชื่อคนเขียนคอมเมนต์โผล่เป็นป้ายเดี่ยวๆ ข้างรูปโปรไฟล์ ยาวพอจะถูกนับเป็นคอมเมนต์
# ตัดทิ้งโดยอ่านชื่อจากป้าย "รูปโปรไฟล์ของ <ชื่อ>" ที่อยู่บนจอเดียวกัน
AVATAR_PREFIX = "รูปโปรไฟล์ของ"
# ใต้คอมเมนต์สุดท้ายมีการ์ด "กลุ่มที่แนะนำ" ต่อท้าย ซึ่งมีป้ายชื่อกลุ่มสั้นๆ เดี่ยวๆ
# ที่ไม่ติดคำว่า "สมาชิก" เลย (เจอจริง: "🏠 แต่งไปเถอะบ้านเรา") ถ้าไม่กั้นเพดาน
# จะถูกนับเป็นคอมเมนต์ — ใช้ป้ายแรกที่มีคำว่า "สมาชิก" เป็นเส้นตัด
COMMENT_ZONE_END_HINTS = ("สมาชิก", "โพสต์ต่อวัน")
COMMENT_COUNT_SCROLLS = 8
# ระยะจากรูปโปรไฟล์ลงมาถึงข้อความของคอมเมนต์นั้น
#
# วัดจริง: รูปโปรไฟล์ y=1859 → ข้อความ y=1927 (68px) · y=1393 → y=1461 (68px)
# ส่วนการ์ดลิงก์ที่แนบมาในคอมเมนต์อยู่ห่างลงไป 486px ขึ้นไป จึงตั้ง 400 เป็นเส้นแบ่ง
# ที่กันการ์ดลิงก์ออกได้โดยยังคลุมข้อความจริงเสมอ
COMMENT_TEXT_WINDOW = 400


def _comment_anchors(xml: str, low: int, high: int) -> list[tuple[int, str]]:
    """(y ของรูปโปรไฟล์, ชื่อคนเขียน) ของทุกคอมเมนต์บนจอ — หนึ่งรูป = หนึ่งคอมเมนต์"""
    found = []
    for labels, (_, y1, _, _), _ in iter_widgets(xml):
        if not (low < y1 < high):
            continue
        for label in labels:
            if label.startswith(AVATAR_PREFIX):
                found.append((y1, label[len(AVATAR_PREFIX):].strip()))
                break
    return found


def _comment_text_near(rows: list, anchor: int, name: str) -> str:
    """ข้อความของคอมเมนต์ที่มีรูปโปรไฟล์อยู่ที่ y นี้ ("" = หาไม่เจอ)

    ผูกข้อความเข้ากับรูปโปรไฟล์แทนการกวาดข้อความลอยๆ เพราะการ์ดลิงก์ที่แนบมา
    ในคอมเมนต์แตกเป็นหลาย node (ชื่อโดเมน · ชื่อสินค้า) ซึ่งกวาดแบบเดิมจะนับ
    เป็นคอมเมนต์เพิ่มอีกใบละ 2 รายการ (เจอจริง: คอมเมนต์ 2 อัน นับได้ 5)
    """
    for y1, labels in sorted(rows):
        if not (anchor < y1 < anchor + COMMENT_TEXT_WINDOW):
            continue
        for label in labels:
            text = " ".join(label.split())
            if len(text) < COMMENT_TEXT_MIN or text.startswith("http"):
                continue
            if any(hint in text for hint in COMMENT_CHROME_HINTS):
                continue
            if text == name:
                continue
            return text[:60]
    return ""


def count_comments(phone: Phone) -> int | None:
    """นับคอมเมนต์ของโพสต์ด้วยการเลื่อนดูจนสุด (None = ไม่เคยเข้าโซนคอมเมนต์)

    หยุดเมื่อจอไม่เปลี่ยนอีกแล้ว = เลื่อนสุดรายการ (ตรวจจริง: เลื่อนรอบ 5 กับ 6
    ได้จอเหมือนกันเป๊ะ) ไม่ใช่เลื่อนครบจำนวนรอบแล้วเดาว่าหมด
    """
    seen: set[str] = set()
    entered = False
    last = ""
    for _ in range(COMMENT_COUNT_SCROLLS + 1):
        xml = phone.dump()
        floor = None
        ceiling = None
        for labels, (_, y1, _, _), _ in iter_widgets(xml):
            joined = " ".join(labels)
            if floor is None and any(h in joined for h in COMMENT_FILTER_HINTS):
                floor = y1
                entered = True
            if any(h in joined for h in COMMENT_ZONE_END_HINTS):
                ceiling = y1 if ceiling is None else min(ceiling, y1)
        if entered:
            # พอป้ายตัวกรองเลื่อนพ้นจอไปแล้ว ห้ามกวาดตั้งแต่ y=0 — แถบหัวหน้าจอ
            # ("โพสต์ของ <ชื่อ>") จะหลุดเข้ามาถูกนับเป็นคอมเมนต์
            low = max(SAFE_TAP_TOP, floor if floor is not None else 0)
            high = ceiling if ceiling is not None else 10 ** 6
            rows = [
                (y1, labels) for labels, (_, y1, _, _), _ in iter_widgets(xml)
                if low < y1 < high and labels
            ]
            for anchor, name in _comment_anchors(xml, low, high):
                text = _comment_text_near(rows, anchor, name)
                if text:
                    seen.add(text)
        if xml == last:
            break
        last = xml
        phone.vswipe("1800", str(1800 - SCROLL_STEP), str(SCROLL_DURATION_MS),
        )
        time.sleep(1.8)
    return len(seen) if entered else None


# ปุ่มตอบกลับใต้คอมเมนต์แต่ละอัน — หนึ่งปุ่ม = หนึ่งคอมเมนต์
#
# ป้ายเต็มคือ "ตอบกลับความคิดเห็นของ <ชื่อต้น>, ปุ่ม แตะสองครั้งเพื่อตอบกลับ…"
# **ห้ามใช้ชื่อในป้ายนี้จับคู่กับรูปโปรไฟล์** เพราะปุ่มใส่มาแค่ชื่อต้น
# ("Kamolchanok") ส่วนรูปโปรไฟล์ใส่ชื่อเต็ม ("Kamolchanok Lill") — จับคู่ด้วย
# ตำแหน่งแทน: ปุ่มเป็นของคอมเมนต์ที่มีรูปโปรไฟล์อยู่เหนือมันและใกล้ที่สุด
REPLY_BUTTON_PREFIX = "ตอบกลับความคิดเห็นของ"


def visible_comments(xml: str, low: int = 0, high: int = 10 ** 6) -> list[dict]:
    """คอมเมนต์ที่เห็นบนจอตอนนี้ — [{"author", "text", "reply", "top"}]

    reply = พิกัดปุ่มตอบกลับของคอมเมนต์นั้น (None = ไม่เห็นปุ่มบนจอนี้)

    แบ่งเขตของแต่ละคอมเมนต์ด้วย "รูปโปรไฟล์ตัวถัดไป" เป็นเส้นแบ่ง ทุกอย่างที่อยู่
    ระหว่างรูปโปรไฟล์นี้กับตัวถัดไปคือของคอมเมนต์นี้

    หมายเหตุ: การหาข้อความของแต่ละคอมเมนต์ใช้ตรรกะเดียวกับ count_comments
    (ซึ่งทดสอบกับจอจริงแล้ว) ยังไม่ยุบรวมกันเพราะ count_comments เพิ่งยืนยันผล
    ไปสดๆ ควรยุบตอนที่ทดสอบทั้งคู่พร้อมกันได้
    """
    avatars: list[tuple[int, str]] = []
    replies: list[tuple[int, tuple[int, int]]] = []
    rows: list[tuple[int, list[str]]] = []
    for labels, box, clickable in iter_widgets(xml):
        y1 = box[1]
        if not (low < y1 < high):
            continue
        if labels:
            rows.append((y1, labels))
        for label in labels:
            if label.startswith(AVATAR_PREFIX):
                avatars.append((y1, label[len(AVATAR_PREFIX):].strip()))
                break
            if clickable and label.startswith(REPLY_BUTTON_PREFIX):
                replies.append(
                    (y1, ((box[0] + box[2]) // 2, (box[1] + box[3]) // 2))
                )
                break
    avatars.sort()
    found: list[dict] = []
    for index, (top, author) in enumerate(avatars):
        end = avatars[index + 1][0] if index + 1 < len(avatars) else high
        text = _comment_text_near(
            [(y, labels) for y, labels in rows if y < end], top, author
        )
        button = next((point for y, point in sorted(replies) if top < y < end), None)
        found.append({"author": author, "text": text, "reply": button, "top": top})
    return found


def read_post_stats(phone: Phone, caption: str, single_post: bool = True,
                    count_rows: bool = True) -> dict:
    """เลื่อนหาแถวตัวนับของโพสต์เราแล้วอ่านค่า ({} = หาไม่เจอ)

    ต้องเลื่อนเพราะโพสต์ที่มีรูปสูงจะดันแถบปุ่มพ้นขอบล่างจอตั้งแต่เปิดหน้ามา

    count_rows=False = ไม่ต้องนับคอมเมนต์เอง (เร็วขึ้นราว 20 วินาทีต่อกลุ่ม
    แต่ยอดคอมเมนต์จะเป็น None เมื่อแอปไม่แสดงเลขให้)
    """
    for attempt in range(STAT_SCROLL_TRIES + 1):
        xml = phone.dump()
        # ในฟีดต้องผูกกับแคปชันของเราเสมอ ไม่งั้นอ่านตัวนับของโพสต์คนอื่น
        after = None
        if not single_post:
            box = _caption_box(xml, caption)
            if box is None:
                phone.log("  ไม่เห็นข้อความโพสต์ของเราบนจอ — ไม่เก็บยอด")
                return {}
            after = box[1]
        stats = post_stat_numbers(xml, after=after)
        if stats and any(value is not None for value in stats.values()):
            # แอปไม่บอกจำนวนคอมเมนต์เมื่อยอดยังน้อย — นับเองต่อจากตรงนี้
            # ทำหลังอ่านตัวนับเสมอ เพราะการนับต้องเลื่อนยาวจนสุดโซนคอมเมนต์
            # ซึ่งจะพาแถบปุ่มหลุดจอไปแล้ว อ่านตัวนับทีหลังไม่ได้อีก
            if count_rows and stats.get("comments") is None:
                stats["comments"] = count_comments(phone)
            return stats
        if attempt >= STAT_SCROLL_TRIES:
            break
        phone.vswipe("1800", str(1800 - SCROLL_STEP), str(SCROLL_DURATION_MS),
        )
        time.sleep(1.8)
    phone.log("  หาแถวตัวนับของโพสต์ไม่เจอ")
    return {}


def collect_groups(
    adb: str, serial: str, caption: str, targets: list[dict],
    log=print, stop=lambda: False, on_result=None, clipboard=None,
) -> list[dict]:
    """เก็บยอด ถูกใจ/คอมเมนต์/แชร์ ของโพสต์ทุกกลุ่ม — ไม่แตะอะไรบนโพสต์เลย

    ต่างจากรอบตามเก็บตรงที่**อ่านอย่างเดียว** ไม่กดถูกใจ ไม่คอมเมนต์ จึงไม่ต้อง
    สลับคีย์บอร์ดและไม่กินโควตาคอมเมนต์ เรียกซ้ำกี่รอบก็ได้

    targets = [{"group_id", "name", "link", "post_id"}]
    """
    phone = Phone(adb, serial, log=log)
    require_network(phone)
    log("เน็ตมือถือใช้ได้")
    results: list[dict] = []
    for index, item in enumerate(targets, start=1):
        if stop():
            log("ผู้ใช้สั่งหยุด")
            break
        name = item.get("name", "")
        log(f"[{index}/{len(targets)}] {name[:30]}")
        if not phone.online():
            log(f"  {OFFLINE_MESSAGE}")
            break
        entry = {"group_id": item.get("group_id", ""), "index": index,
                 "total": len(targets)}
        opened = open_own_post(
            phone, entry["group_id"], name, caption, clipboard=clipboard,
            link=item.get("link", ""), post_id=item.get("post_id", ""),
        )
        if opened["link"]:
            entry["link"] = opened["link"]
        if not opened["route"]:
            entry["error"] = "เปิดโพสต์ไม่ได้ (ทั้งลิงก์ แจ้งเตือน และฟีด)"
        else:
            stats = read_post_stats(
                phone, caption,
                single_post=opened["route"] in SINGLE_POST_ROUTES,
            )
            if stats:
                entry["stats"] = stats
                log(f"  {format_stats(stats)}")
            else:
                entry["error"] = "เปิดโพสต์ได้ แต่อ่านแถวตัวนับไม่ได้"
        results.append(entry)
        if on_result:
            on_result(entry)
    return results


# ── แก้รูปของโพสต์ที่ลงไปแล้ว ─────────────────────────────────────────────
#
# ทำไมต้องมี: บั๊ก `_id` ของ MediaStore ทำให้โพสต์ตั้งแต่กลุ่มที่ 2 เป็นต้นไปแนบรูป
# คอมเมนต์แทนรูปโพสต์ (ดูข้อ 3.16 ในไฟล์บั๊ก) โพสต์ที่ลงไปแล้วต้องแก้ย้อนหลัง
#
# ทำไมไม่ลบแล้วโพสต์ใหม่:
#   - ลิงก์ · คอมเมนต์ · ยอดถูกใจ ของเดิมหายหมด
#   - ยิงเนื้อหาเดิมซ้ำลงกลุ่มเดิม = เพิ่มสัญญาณสแปมให้ Facebook
#
# ทดสอบกับโพสต์จริงแล้ว 6/6 กลุ่ม คอมเมนต์และยอดถูกใจอยู่ครบหลังแก้
EDIT_POST_HINTS = ("แก้ไขโพสต์", "Edit post")
REMOVE_PHOTO_HINTS = ("ลบรูปภาพออก", "Remove photo")
# ป้ายปุ่มเพิ่มรูปเปลี่ยนตามสถานะ: ยังมีรูปอยู่ = "เพิ่มสื่อ" (วัดได้ y≈960)
# ลบรูปหมดแล้ว = "แกลเลอรี" (ย้ายไป y≈1866) ต้องรับทั้งสองคำ
EDIT_ADD_MEDIA_HINTS = ("เพิ่มสื่อ", "เพิ่มรูปภาพ/วิดีโออื่นๆ", "แกลเลอรี", "Gallery")
SAVE_EDIT_HINTS = ("บันทึก", "Save")
COMPOSER_ACTIVITY = "ComposerActivity"


def _tap_clickable(phone: Phone, hints, tag: str, wait: float = 3.0) -> bool:
    """แตะ widget ที่ **กดได้** ตัวแรกที่ป้ายมีคำเหล่านี้

    ต้องกรอง clickable เพราะป้ายเดียวกันมักโผล่ทั้งบนตัวปุ่มและบน TextView ข้างใน
    แตะตัวที่กดไม่ได้บางทีไม่มีอะไรเกิดขึ้นเลย
    """
    for labels, box, clickable in iter_widgets(phone.dump()):
        if not clickable:
            continue
        if any(any(hint in label for hint in hints) for label in labels):
            phone.tap(((box[0] + box[2]) // 2, (box[1] + box[3]) // 2))
            time.sleep(wait)
            return True
    phone.log(f"  หา {tag} ไม่เจอ")
    return False


def _has_label(phone: Phone, hints) -> bool:
    return any(
        any(hint in label for hint in hints)
        for labels, _, _ in iter_widgets(phone.dump()) for label in labels
    )


def _in_composer(phone: Phone) -> bool:
    return COMPOSER_ACTIVITY in phone.shell("dumpsys window | grep mCurrentFocus")


def replace_post_image(phone: Phone, link: str, caption: str, group_id: str,
                       images: list[Path], post_id: str = "") -> str:
    """เปลี่ยนรูปของโพสต์ที่ลงไปแล้วให้เป็น images ("" = สำเร็จ · อื่นๆ = เหตุที่ล้ม)

    ทุกขั้นต้องเจอหมุดจริงถึงไปต่อ เจอไม่ครบ = หยุด ไม่เดาแล้วแตะมั่ว เพราะนี่คือ
    การแก้โพสต์จริงบนกลุ่มจริง แตะผิดทีเดียวอาจลบโพสต์หรือโพสต์ค้างไม่มีรูป
    """
    # รูปที่ถูกต้องต้องอยู่ช่องแรกของตัวเลือกรูป **ก่อน** เปิดแกลเลอรีเสมอ
    push_images(phone, images)
    ensure_images_newest(phone, images)

    if not open_post_link(phone, link, caption, group_id, post_id):
        return "เปิดโพสต์จากลิงก์ไม่ได้"
    if not _tap_clickable(phone, POST_MENU_HINTS, "ปุ่ม …", wait=2.5):
        return "หาปุ่ม … ของโพสต์ไม่เจอ"
    if not _tap_clickable(phone, EDIT_POST_HINTS, "เมนูแก้ไขโพสต์", wait=6.0):
        return "เมนูนี้ไม่มีตัวเลือกแก้ไขโพสต์"
    if not _in_composer(phone):
        return "กดแก้ไขแล้วแต่ไม่ได้เข้าหน้าแก้ไขโพสต์"

    if not _tap_clickable(phone, REMOVE_PHOTO_HINTS, "ปุ่มลบรูป", wait=3.0):
        return "หาปุ่มลบรูปไม่เจอ"
    if _has_label(phone, REMOVE_PHOTO_HINTS):
        return "กดลบรูปแล้วแต่รูปเดิมยังอยู่"
    phone.log("  ลบรูปเดิมออกแล้ว")

    if not _tap_clickable(phone, EDIT_ADD_MEDIA_HINTS, "ปุ่มเพิ่มรูป", wait=5.0):
        return "หาปุ่มเพิ่มรูปไม่เจอ"
    picked = pick_photos(phone, len(images))
    if picked < len(images):
        return f"เลือกรูปได้ {picked} จาก {len(images)} ใบ"
    phone.log(f"  เลือกรูปที่ถูกแล้ว {picked} ใบ")
    _tap_clickable(phone, NEXT_HINTS, "ปุ่มถัดไป", wait=5.0)

    if not _in_composer(phone):
        return "หลุดออกจากหน้าแก้ไขหลังเลือกรูป"
    if not _has_label(phone, REMOVE_PHOTO_HINTS):
        return "กลับมาหน้าแก้ไขแล้วแต่ไม่เห็นรูปที่แนบ"
    if not _tap_clickable(phone, SAVE_EDIT_HINTS, "ปุ่มบันทึก", wait=9.0):
        return "หาปุ่มบันทึกไม่เจอ"
    # ยังอยู่หน้าเดิม = กดบันทึกแล้วไม่ผ่าน (เน็ตหลุด / แอปเด้งกล่องอะไรมาขวาง)
    if _in_composer(phone):
        return "กดบันทึกแล้วแต่ยังค้างอยู่หน้าแก้ไข"
    phone.log("  บันทึกรูปใหม่แล้ว")
    return ""


def fix_images_groups(
    adb: str, serial: str, caption: str, targets: list[dict],
    images: list[Path], log=print, stop=lambda: False, on_result=None,
) -> list[dict]:
    """ไล่แก้รูปของโพสต์ทุกกลุ่มในงานเดียว

    targets = [{"group_id", "name", "link", "post_id"}] — ต้องมีลิงก์ถึงจะแก้ได้
    เพราะต้องเปิดโพสต์นั้นให้ตรงใบ ไม่ใช่ไล่เดาในฟีด
    """
    phone = Phone(adb, serial, log=log)
    require_network(phone)
    log("เน็ตมือถือใช้ได้")
    results: list[dict] = []
    for index, item in enumerate(targets, start=1):
        if stop():
            log("ผู้ใช้สั่งหยุด")
            break
        name = item.get("name", "")
        log(f"[{index}/{len(targets)}] {name[:30]}")
        if not phone.online():
            log(f"  {OFFLINE_MESSAGE}")
            break
        entry = {"group_id": item.get("group_id", ""), "index": index,
                 "total": len(targets)}
        link = item.get("link", "")
        if not link:
            entry["error"] = "ยังไม่มีลิงก์โพสต์ — แก้รูปไม่ได้"
        else:
            try:
                problem = replace_post_image(
                    phone, link, caption, entry["group_id"], images,
                    item.get("post_id", ""),
                )
            except PostError as error:
                problem = str(error)
            if problem:
                entry["error"] = problem
                log(f"  ❌ {problem}")
            else:
                entry["image_fixed"] = True
        results.append(entry)
        if on_result:
            on_result(entry)
    return results


def format_stats(stats: dict) -> str:
    """แปลงยอดเป็นข้อความอ่านง่าย — ค่าที่อ่านไม่ได้แสดงเป็น "?" ไม่ใช่ 0"""
    def show(key: str) -> str:
        value = stats.get(key)
        return "?" if value is None else str(value)
    return (f"❤️ {show('reactions')} · 💬 {show('comments')} "
            f"· 🔁 {show('shares')}")


POST_FAIL_DIR = studio_shared.POST_EVIDENCE / "post_failures"


def keep_failure_screen(phone: Phone, step: str) -> None:
    """เก็บหน้าจอตอนขั้นตอนโพสต์ล้ม — ไว้ตอบทีหลังว่า "บนจอมีอะไรอยู่"

    ทำไมต้องมี: 18 ส.ค. งาน p51955802 ล้มที่ขั้นแนบรูป แล้วไล่ย้อนไม่ได้เลยว่า
    ตอนนั้นจอเป็นอะไร — กล่องถามฉบับร่างบัง? หน้ายังโหลดไม่เสร็จ? Facebook
    เปลี่ยนหน้าจอ? สามอย่างนี้แก้คนละทางกันคนละเรื่อง แต่ไม่มีหลักฐานให้แยก
    (ช่องโหว่แบบเดียวกับตอนคอมเมนต์โดนบล็อก 16 ส.ค. ซึ่งแก้ไปแล้วเฉพาะฝั่งคอมเมนต์)

    ล้มเหลวตรงนี้ต้องไม่ทำให้งานล้มซ้ำซ้อน — เก็บไม่ได้ก็ปล่อยผ่านเงียบๆ
    """
    try:
        xml = phone.dump()
    except Exception:
        return
    try:
        saved = fb_comment_guard.save_evidence(xml, directory=POST_FAIL_DIR)
    except Exception:
        return
    if saved:
        phone.log(f"  เก็บหน้าจอไว้แล้ว: {saved.name} ({step})")


def post_to_group(
    phone: Phone, group_id: str, caption: str, dry_run: bool = False,
    clipboard=None, comment: str = "", photo_count: int = 1,
    comment_images=None, stop=lambda: False, links_only_on_reject: bool = False,
) -> dict:
    """โพสต์ลงกลุ่มเดียว — คืนผลว่าไปถึงขั้นไหน

    dry_run=True จะทำทุกขั้นยกเว้น**กดโพสต์จริง** ไว้ตรวจว่าไล่ UI ถูกไหม
    ก่อนปล่อยของจริงออกไปทั้ง 5 กลุ่ม
    """
    phone.open_group(group_id)

    phone.log("  แตะช่องเขียนโพสต์")
    phone.tap(phone.wait_for(COMPOSER_HINTS, timeout=15))
    time.sleep(3.0)

    phone.log("  แนบรูป")
    # **ต้องวนรอ ไม่ใช่มองครั้งเดียว** — ของเดิมนอนรอตายตัว 3 วินาทีแล้ว dump
    # ครั้งเดียว เจอก็เจอ ไม่เจอก็ล้มทันที ทั้งที่ขั้นก่อนหน้า (หาช่องเขียนโพสต์)
    # วนรอได้ถึง 15 วินาที — สองขั้นติดกันใช้มาตรฐานคนละอย่าง
    #
    # เจอจริง 18 ส.ค. งาน p51955802 กลุ่มช้อปขั้นเทพ: หน้ากลุ่มโหลดช้ากว่าปกติ
    # (กว่าจะเจอช่องเขียนโพสต์ก็กินไป 4 วินาทีแล้ว) พอถึงขั้นนี้จอยังไม่ทันวาด
    # ปุ่มเสร็จ เลยล้มทั้งที่กลุ่มไม่มีอะไรผิด — กลุ่มเดียวกันนี้โพสต์ผ่านมา
    # 11 ครั้งติดก่อนหน้านั้น และกลุ่มถัดไปที่ทำต่อทันทีก็ผ่านปกติ
    photo = phone.find(phone.dump(), PHOTO_HINTS)
    if photo is None:
        for _ in range(PHOTO_BUTTON_TRIES):
            time.sleep(1.5)
            photo = phone.find(phone.dump(), PHOTO_HINTS)
            if photo is not None:
                phone.log("  (ปุ่มแนบรูปมาช้า — รอจนเจอแล้ว)")
                break
    if photo is None:
        keep_failure_screen(phone, "ไม่พบปุ่มแนบรูป")
        raise PostError("ไม่พบปุ่มแนบรูปในหน้าเขียนโพสต์")
    phone.tap(photo)
    time.sleep(2.5)

    # รูปที่เพิ่งส่งเข้าไปเป็นไฟล์ใหม่สุด จึงอยู่หัวตารางของแกลเลอรี
    picked = pick_photos(phone, photo_count)
    if picked < 1:
        raise PostError("เลือกรูปในแกลเลอรีไม่ได้ — ไม่พบรูปในหน้าเลือกรูป")
    if picked < photo_count:
        phone.log(f"  เลือกได้ {picked} จาก {photo_count} ใบ — โพสต์เท่าที่เลือกได้")
    else:
        phone.log(f"  เลือกรูป {picked} ใบ")
    next_button = phone.find(phone.dump(), NEXT_HINTS)
    if next_button:
        phone.tap(next_button)
    time.sleep(2.0)

    phone.log("  พิมพ์แคปชัน")
    field = phone.find(phone.dump(), CAPTION_FIELD_HINTS)
    if field is None:
        raise PostError("ไม่พบช่องพิมพ์แคปชันหลังแนบรูป")
    phone.tap(field)
    time.sleep(1.5)
    phone.type_text(caption)
    time.sleep(1.5)
    # ยืนยันว่าข้อความเข้าจริง ไม่ใช่เดาจากการส่ง broadcast ผ่าน
    if not screen_has(phone.dump(), caption.strip()[:10]):
        raise PostError("พิมพ์แคปชันแล้วแต่ข้อความไม่ขึ้นบนหน้าจอ")

    # กลับจากหน้า "เพิ่มข้อความ" เข้าหน้าเขียนโพสต์ ปุ่มโพสต์ถึงจะโผล่
    done = phone.find(phone.dump(), CAPTION_DONE_HINTS)
    if done:
        phone.tap(done)
        time.sleep(2.0)

    if dry_run:
        phone.log("  [ซ้อม] ยังไม่กดโพสต์ — ตรวจหน้าจอได้เลย")
        return {"group_id": group_id, "posted": False, "dry_run": True}

    # ปิดคีย์บอร์ดก่อนเสมอ — ไม่งั้นปุ่มโพสต์ถูกคีย์บอร์ดบังจนหายไปจากผังจอ
    # บนเครื่องจอเตี้ย แล้วหาไม่เจอทั้งที่ปุ่มอยู่ตรงนั้น (ดู Phone.hide_keyboard)
    phone.hide_keyboard()
    phone.log("  กดโพสต์")
    phone.tap(phone.wait_for(POST_HINTS, timeout=15, exact=True))
    time.sleep(4.0)

    # ลำดับนี้สำคัญ: **เก็บลิงก์ก่อน แล้วค่อยใช้ลิงก์เปิดโพสต์ไปกดถูกใจ**
    # เพราะการกดถูกใจในฟีดต้องเดาว่าโพสต์ไหนเป็นของเรา ซึ่งพลาดบ่อย
    # (รอบก่อนไลก์ยืนยันได้แค่ 1 จาก 4 กลุ่ม) ส่วนเปิดด้วยลิงก์ตรงไม่ต้องเดาเลย
    # ผู้ใช้สั่งยกเลิกระหว่างกลุ่มนี้ = โพสต์ออกไปแล้วห้ามเดินหน้าต่อ
    #
    # ตัวโพสต์ยกเลิกกลางคันไม่ได้ (กดปุ่มโพสต์ไปแล้ว) แต่ขั้นเก็บลิงก์/ถูกใจ/
    # คอมเมนต์กินอีกราวหนึ่งนาที ข้ามได้ทันทีเพื่อให้คำสั่งยกเลิกมีผลเร็วขึ้น
    if stop():
        phone.log("  ผู้ใช้สั่งยกเลิก — ข้ามการเก็บลิงก์/ถูกใจ/คอมเมนต์")
        return {"group_id": group_id, "posted": True, "liked": False,
                "link": "", **dict(NO_COMMENT)}

    time.sleep(POST_SETTLE_SECONDS)         # รอโพสต์ขึ้นฟีดก่อน
    link = ""
    if clipboard is not None:
        link = copy_post_link(phone, group_id, caption, clipboard)
    # **ลำดับที่เจ้าของกำหนด 28 ส.ค. 2569**
    #
    #   โพสต์ → ไลก์โพสต์ → คอมเมนต์ 1 → ไลก์คอมเมนต์ 1
    #                     → คอมเมนต์ 2 → ไลก์คอมเมนต์ 2 → ... (วนเท่าจำนวนคอมเมนต์)
    #
    # มีลิงก์แล้วเปิดหน้าโพสต์เดี่ยวก่อน **แล้วทำทั้งไลก์และคอมเมนต์บนหน้านั้น**
    # ทั้งสองอย่างในฟีดต้องเลื่อนหาโพสต์ตัวเองเหมือนกัน ซึ่งเป็นด่านที่พังบนจอเล็ก
    # (วัด 28 ส.ค.: ฟีดล้ม 6/6 กลุ่ม · หน้าโพสต์เดี่ยวเจอทุกปุ่มโดยไม่ต้องเลื่อน)
    on_post_page = False
    if link:
        try:
            on_post_page = open_post_link(phone, link, caption, group_id=group_id)
        except Exception as error:      # เปิดไม่ได้ต้องไม่ทำให้ทั้งกลุ่มล้ม
            phone.log(f"  เปิดโพสต์จากลิงก์ไม่ได้ ({error}) — ถอยไปทำในฟีด")
    if on_post_page:
        phone.log("  ทำงานบนหน้าโพสต์เดี่ยว (ไม่ต้องเลื่อนหา)")
    # กดถูกใจโดยอ้างอิงแคปชันของเรา ไม่ใช่ "โพสต์บนสุด"
    liked = like_post_of(phone, caption, single_post=on_post_page)
    outcome = dict(NO_COMMENT)
    if _as_texts(comment):
        # **มีลิงก์แล้วให้เปิดหน้าโพสต์เดี่ยวไปคอมเมนต์ ดีกว่าไล่หาในฟีดมาก**
        # (เปลี่ยน 28 ส.ค. 2569)
        #
        # ในฟีดต้อง "เลื่อนหาโพสต์ตัวเอง → หาปุ่มคอมเมนต์ → กดเปิดแผง" สามด่าน
        # ที่พึ่งการเลื่อนจอทั้งหมด ส่วนหน้าโพสต์เดี่ยว **ช่องพิมพ์ตรึงอยู่ล่างจอ
        # ตลอด** ไม่ต้องเลื่อนเลยสักครั้ง
        #
        # วัดกับหน้าจอจริง 28 ส.ค. (REDMI 15C 720x1600) บนหน้าโพสต์เดี่ยว:
        #   ข้อความโพสต์ y 303..591 · ปุ่มคอมเมนต์ y 1397 · ช่องพิมพ์ (428,1436)
        #   ปุ่มส่ง (672,1519)  — เจอครบทุกตัวโดยไม่ต้องเลื่อน
        # ส่วนทางฟีดวันเดียวกันล้ม 6 จาก 6 กลุ่ม ("หาปุ่มคอมเมนต์ไม่เจอ")
        #
        # ยังเก็บทางฟีดไว้เป็นทางถอย — เปิดจากลิงก์ไม่ได้ทุกครั้ง (ดู open_post_link)
        # ทำหลังไลก์เสมอ — ในฟีดแผงคอมเมนต์เปิดทับหน้าจอแล้วหาปุ่มถูกใจไม่เจอ
        # ส่วนบนหน้าโพสต์เดี่ยวไม่มีปัญหานั้น แต่คงลำดับเดิมไว้ให้ตรงกับที่สั่ง
        outcome = comment_post_of(phone, caption, comment,
                                  single_post=on_post_page, photos=comment_images,
                                  links_only_on_reject=links_only_on_reject)
        phone.back()
        time.sleep(1.5)
    return {
        "group_id": group_id, "posted": True, "liked": liked,
        "link": link, **outcome,
    }


OFFLINE_MESSAGE = (
    "มือถือไม่ได้ต่อเน็ต — หยุดก่อนเริ่ม "
    "(ถ้าฝืนโพสต์ แอปจะรับไว้ในคิวออฟไลน์แล้วรายงานว่าสำเร็จ ทั้งที่ไม่มีอะไรขึ้นจริง)"
)


def _skipped(group_ids: list[str], reason: str) -> list[dict]:
    """ผลของกลุ่มที่ยังไม่ได้ลงมือทำ เพราะงานถูกตัดกลางคัน

    ต้องใส่ลงผลลัพธ์ด้วย ไม่ใช่ปล่อยหาย ไม่งั้นสรุปจะนับเฉพาะกลุ่มที่ลงมือทำ
    แล้วขึ้นว่า "โพสต์ 2/2" ทั้งที่ผู้ใช้เลือกไว้ 5 กลุ่ม — ดูเหมือนสำเร็จครบ
    ทั้งที่ 3 กลุ่มยังไม่ได้โพสต์เลย (เจอจริง 11 ส.ค. งาน p417566923)
    """
    return [
        {"group_id": group_id, "posted": False, "error": reason}
        for group_id in group_ids
    ]


def require_network(phone: Phone) -> None:
    """ไม่มีเน็ต = หยุดตรงนี้ ห้ามปล่อยให้ไหลไปกดปุ่มต่อ

    ด่านนี้มีเพราะเคยเสียไปแล้วทั้งชุด: ยิงครบ 6 กลุ่ม รายงานสำเร็จหมด
    แต่โพสต์ค้างอยู่ในคิวอัปโหลดของแอปทั้งหมด ไม่มีอันไหนถึง Facebook เลย
    """
    if not phone.online():
        raise PostError(OFFLINE_MESSAGE)


def post_to_groups(
    adb: str, serial: str, image, caption: str, group_ids: list[str],
    gap_range: tuple[float, float] = DEFAULT_GAP_RANGE,
    dry_run: bool = False, log=print, stop=lambda: False, on_result=None,
    clipboard=None, comment="", comment_images=None, links_only_groups=(),
) -> list[dict]:
    """ไล่โพสต์ทีละกลุ่ม เว้นระยะแบบสุ่มระหว่างกลุ่ม

    on_result ยิงทันทีที่กลุ่มหนึ่งจบ (สำเร็จหรือล้ม) — ฝั่งเรียกจะได้รายงาน
    ความคืบหน้าได้เลย ไม่ต้องรอครบทุกกลุ่มแล้วค่อยรู้ผลทีเดียว ซึ่งกินเวลา
    เป็นนาทีเมื่อโพสต์หลายกลุ่ม
    """
    low = max(MIN_GAP_SECONDS, min(gap_range))
    high = max(low, max(gap_range))
    phone = Phone(adb, serial, log=log)
    # เช็คก่อนแตะอะไรทั้งสิ้น — ล้มตรงนี้เสียแค่เวลา ล้มทีหลังเสียทั้งชุด
    require_network(phone)
    log("เน็ตมือถือใช้ได้")
    # รับได้ทั้งไฟล์เดียวและหลายไฟล์ — ของเดิมเรียกมาแบบไฟล์เดียว
    images = [Path(p) for p in (image if isinstance(image, (list, tuple)) else [image])]
    images = images[:MAX_PHOTOS]
    photo_count = push_images(phone, images)
    if photo_count > 1:
        log(f"ส่งรูปเข้าเครื่อง {photo_count} ใบ")

    original_ime = phone.use_adb_keyboard()
    results: list[dict] = []
    try:
        for index, group_id in enumerate(group_ids, start=1):
            if stop():
                log("ผู้ใช้สั่งหยุด")
                results += _skipped(group_ids[index - 1:], "ผู้ใช้สั่งหยุด")
                break
            log(f"[{index}/{len(group_ids)}] กลุ่ม {group_id}")
            # เน็ตหลุดกลางคัน: กลุ่มที่เหลือจะเข้าคิวออฟไลน์เงียบๆ แล้วรายงานว่าสำเร็จ
            # หยุดไว้ดีกว่า ผลของกลุ่มที่ทำไปแล้วยังอยู่ครบ
            if not phone.online():
                log(f"  {OFFLINE_MESSAGE}")
                results += _skipped(group_ids[index - 1:], "เน็ตมือถือหลุด — ยังไม่ได้โพสต์")
                break
            try:
                # อ่านข้อความคอมเมนต์ใหม่ทุกกลุ่ม — ผู้ใช้ตั้ง /comment กลางคันได้
                # ถ้าจับค่าไว้ตั้งแต่เริ่มงาน การตั้งทีหลังจะไม่มีผลกับกลุ่มที่เหลือ
                text = comment() if callable(comment) else comment
                # อ่านรูปคอมเมนต์ใหม่ทุกกลุ่มด้วยเหตุผลเดียวกับข้อความ
                shots = comment_images() if callable(comment_images) else comment_images
                # ส่งรูปโพสต์เข้าเครื่อง**ใหม่ทุกกลุ่ม** ไม่ใช่ครั้งเดียวก่อนวนลูป
                #
                # ขั้นคอมเมนต์ของกลุ่มก่อนหน้าส่งรูปคอมเมนต์เข้าไปแล้ว รูปนั้นจึง
                # กลายเป็นใบใหม่สุดแทน — ถ้าไม่ส่งรูปโพสต์ทับ กลุ่มนี้จะแนบรูป
                # คอมเมนต์เป็นรูปโพสต์ (เจอจริง งาน p594651692: กลุ่ม 2-6 รูปผิดหมด)
                if index > 1:
                    push_images(phone, images)
                ensure_images_newest(phone, images)
                entry = post_to_group(
                    phone, group_id, caption, dry_run, clipboard, text, photo_count,
                    comment_images=shots, stop=stop,
                    # **เปิดเฉพาะกลุ่มที่เจ้าของสั่ง** (28 ส.ค. 2569)
                    # กลุ่มอื่นคอมเมนต์เต็มผ่านอยู่แล้ว ตัดคำพูดทิ้งทุกกลุ่ม
                    # คือทำให้กลุ่มที่ไม่มีปัญหาแย่ลงฟรีๆ
                    links_only_on_reject=str(group_id) in set(links_only_groups),
                )
                results.append(entry)
                log("  สำเร็จ")
            except PostError as error:
                log(f"  ล้มเหลว: {error}")
                entry = {"group_id": group_id, "posted": False, "error": str(error)}
                results.append(entry)
                # เคลียร์หน้าค้างก่อนไปกลุ่มถัดไป ไม่งั้นกลุ่มถัดไปเริ่มจากหน้าผิด
                for _ in range(3):
                    phone.back()
            # รายงานทันทีที่กลุ่มนี้จบ ไม่ต้องรอครบทุกกลุ่ม
            if on_result:
                on_result({**entry, "index": index, "total": len(group_ids)})
            if index < len(group_ids):
                gap = random.uniform(low, high)
                log(f"  รออีก {gap:.0f} วินาทีก่อนกลุ่มถัดไป")
                waited = 0.0
                while waited < gap and not stop():
                    time.sleep(1.0)
                    waited += 1.0
        # รอบตรวจซ้ำท้ายสุด — เปิดทุกกลุ่มใหม่แล้วดูว่าโพสต์ขึ้นจริงและถูกใจติดจริง
        if not dry_run:
            log("ตรวจซ้ำทุกกลุ่ม")
            for entry in results:
                if not entry.get("posted"):
                    continue
                if stop():
                    break
                link = entry.get("link", "")
                check = verify_liked(phone, entry["group_id"], caption)
                entry["verified"] = check
                # ถูกใจไม่ติดตอนตรวจซ้ำ ลองกดให้อีกรอบตรงนั้นเลย
                # กดซ้ำได้เฉพาะตอนรอบแรก**ยังไม่สำเร็จ** — ปุ่มถูกใจเป็นสวิตช์
                # ถ้ารอบแรกกดติดแล้วมากดอีกทีคือยกเลิกไลก์ของตัวเอง
                if not entry.get("liked") and not check["liked"]:
                    log("  ถูกใจยังไม่ติด — กดใหม่")
                    entry["liked"] = like_post_of(phone, caption)
                    entry["verified"] = verify_liked(phone, entry["group_id"], caption)
                # รอบแรกเก็บลิงก์ไม่ได้ (โพสต์ยังไม่ขึ้นฟีด) — รอบนี้ลองอีกครั้ง
                if not link and clipboard is not None:
                    entry["link"] = copy_post_link(
                        phone, entry["group_id"], caption, clipboard
                    )
                if on_result:
                    on_result({**entry, "final": True})
    finally:
        phone.restore_keyboard(original_ime)
        log("คืนคีย์บอร์ดเดิมแล้ว")
    return results
