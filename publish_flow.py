"""ผังการโพสต์วิดีโอบนมือถือ — เทรนพิกัดเอง แยกผังต่อปลายทาง ต่อเครื่อง

ปลายทางที่รองรับตอนนี้: Shopee Video และ Facebook Reels
ที่จะทำต่อ: TikTok Video · Instagram Reels
แต่ละปลายทางมีผังของตัวเองเพราะหน้าจอคนละแอปคนละลำดับ และเก็บแยกต่อ serial
เพราะจอคนละขนาด

╔══════════════════════════════════════════════════════════════════════════╗
║  กติกาที่ผู้ใช้สั่งไว้ 25 ส.ค. 2026 — ห้ามละเมิดในทุกปลายทาง               ║
║                                                                          ║
║  **ทุกจุดต้องเป็นการกดหน้าจอจริง ยกเว้นได้อย่างเดียวคือตอนเปิดแอป**        ║
║                                                                          ║
║  ได้    input tap / input swipe / input keyevent / ADBKeyboard           ║
║  ได้    เปิดแอปด้วย monkey หรือ am start (ขั้น open_app) — ข้อยกเว้นเดียว  ║
║  ห้าม   เรียก API ของแพลตฟอร์ม · ฉีดโค้ดเข้าแอป · accessibility service   ║
║         · ยิง intent ข้ามขั้นตอนที่ควรกด                                  ║
║         · พิมพ์ผ่านช่องควบคุม scrcpy (POST /api/phone/type)                ║
║                                                                          ║
║  เพิ่มปลายทางใหม่เมื่อไร ต้องผ่านคำสั่งนี้โดยไม่เจออะไรเลย:                 ║
║    python publish_flow_check.py                                          ║
║                                                                          ║
║  เหตุผลเต็มอยู่ที่ CLAUDE.md ข้อ 2.7                                       ║
╚══════════════════════════════════════════════════════════════════════════╝

ทำไมต้องเทรนพิกัดเอง ไม่ฝังพิกัดไว้ในโค้ด
    บทเรียนจาก notes.md ข้อ 2.2 — พิกัดตายตัว "พังทุกครั้งที่แอปเปลี่ยนหน้าตา"
    แต่สองแอปนี้หา element จากข้อความไม่ได้ทุกจุด จึงใช้ทางสายกลาง: ผู้ใช้เทรนเอง
    เก็บเป็นสัดส่วนจอ 0..1 แล้วเทรนซ้ำเฉพาะขั้นที่เพี้ยนเมื่อแอปอัปเดต

ขั้นพิเศษ 2 แบบตามที่ผู้ใช้กำหนด
    paste_link    วางลิงก์ Shopee ที่ส่งเข้ามาทาง Telegram ตอนแรก
    type_hashtag  พิมพ์แท็กทีละตัว อ่านยอดพูดถึงที่แอปโชว์ แล้วเก็บเฉพาะตัวที่ผ่านเกณฑ์

**กติกาที่ยึดทั้งไฟล์: ทุกขั้นต้องพิสูจน์ว่าทำสำเร็จจริงก่อนไปขั้นถัดไป**
    เหตุผลอยู่ใน CLAUDE.md ข้อ 2.3 — "ตัวตรวจที่บอกว่าผ่านทั้งที่ยังไม่ผ่าน
    อันตรายกว่าไม่มีตัวตรวจ" การแตะแล้วเชื่อว่าติดคือการเดา ที่นี่จึงอ่านหน้าจอ
    กลับมายืนยันทุกขั้น ไม่ผ่าน = หยุด ไม่เดินต่อไปกดมั่วบนหน้าจอที่ไม่รู้จัก
"""

from __future__ import annotations

import hashlib
import json
import math
import random
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

import hashtag as hashtag_lib

DATA_DIR = Path(__file__).resolve().parent / "data"
FLOW_DIR = DATA_DIR / "publish_flows"

SHOPEE_PACKAGE = "com.shopee.th"
FACEBOOK_PACKAGE = "com.facebook.katana"

DEFAULT_SETTLE = 1.2
DEFAULT_VERIFY_TIMEOUT = 10.0

# ---------------------------------------------------------- ทำให้เหมือนคนกด
#
# `adb shell input tap` เป็นการแตะจริงที่ระดับระบบปฏิบัติการ (ทางเดียวกับนิ้ว)
# แต่มันแตะ **จุดเดิมเป๊ะทุกครั้ง** ซึ่งนิ้วคนทำไม่ได้ — คนกดปุ่มเดียวกันสิบครั้ง
# ก็ลงไม่ตรงกันสักครั้ง และเว้นจังหวะไม่เท่ากันเป๊ะด้วย
#
# ค่าที่เลือก: รัศมี 6 พิกเซลบนจอ 1080 กว้าง = 0.56% ของความกว้างจอ ปุ่มจริงใน
# Shopee/Facebook เล็กสุดที่วัดได้กว้างราว 90 พิกเซล การเยื้อง 6 พิกเซลจากจุด
# กึ่งกลางจึงยังอยู่ในปุ่มเสมอ แม้เยื้องเต็มรัศมีในแนวทแยง
TAP_JITTER_PX = 6
# เวลาพักระหว่างขั้น สุ่มบวก/ลบ 18% — พักที่ตั้งไว้ 1.2 วิ จะกลายเป็น 0.98–1.42 วิ
SETTLE_JITTER = 0.18


def humanize_point(
    point: tuple[int, int], width: int, height: int, radius: int = TAP_JITTER_PX
) -> tuple[int, int]:
    """เยื้องจุดกดแบบสุ่มเล็กน้อยรอบจุดเดิม แล้วกันไม่ให้หลุดขอบจอ

    สุ่มเป็น **วงกลม** ไม่ใช่สี่เหลี่ยม เพราะการสุ่มในสี่เหลี่ยมทำให้มุมทั้งสี่
    ถูกเลือกบ่อยกว่าที่ควร ซึ่งเป็นลายเซ็นที่สังเกตได้ถ้ามีใครมานั่งดูสถิติ

    รัศมี 0 = ปิดการสุ่ม (ใช้ตอนเทรนพิกัด ที่ต้องแตะตรงจุดเป๊ะเพื่อยืนยันว่า
    จุดที่เทรนถูกต้องจริง ไม่ใช่บังเอิญรอดเพราะเยื้องไปโดนพอดี)
    """
    x, y = int(point[0]), int(point[1])
    if radius > 0:
        angle = random.uniform(0, 2 * math.pi)
        # รากที่สองของค่าสุ่ม — ทำให้จุดกระจายทั่ววงเท่ากัน ไม่กระจุกตรงกลาง
        distance = radius * math.sqrt(random.random())
        x += int(round(math.cos(angle) * distance))
        y += int(round(math.sin(angle) * distance))
    # ห้ามหลุดขอบจอ ไม่งั้น adb จะแตะไม่ติดหรือไปโดนแถบระบบ
    x = max(1, min(x, max(1, width - 2)))
    y = max(1, min(y, max(1, height - 2)))
    return x, y


def humanize_delay(seconds: float, spread: float = SETTLE_JITTER) -> float:
    """สุ่มเวลาพักรอบค่าที่ตั้งไว้ — ไม่ให้จังหวะเป๊ะเท่ากันทุกครั้ง"""
    if seconds <= 0 or spread <= 0:
        return max(0.0, seconds)
    return max(0.0, seconds * random.uniform(1.0 - spread, 1.0 + spread))
SUGGESTION_TIMEOUT = 8.0


class StepError(RuntimeError):
    """ขั้นนี้ทำไม่สำเร็จ — ผู้เรียกตัดสินว่าจะหยุดหรือข้าม"""


# ------------------------------------------------------------------ นิยามขั้น


# ชนิดของขั้น — ทุกชนิดที่ผู้ใช้เพิ่มเองได้จากหน้าเว็บ
KINDS = {
    "open_app":     "เปิดแอป (ไม่ใช้พิกัด)",
    "tap":          "แตะตามพิกัดที่เทรนไว้",
    "type_text":    "พิมพ์ข้อความ",
    "paste_link":   "วางลิงก์สินค้า",
    "type_hashtag": "ใส่แฮชแท็ก (คัดตามยอดพูดถึง)",
    # ใช้กับแอปที่ **ไม่ได้โชว์ยอดพูดถึง** ข้างตัวเลือกแท็ก อย่าง Facebook —
    # แท็กถูกคัดมาแล้วตั้งแต่ตอนสร้างชุดแท็กของสินค้า ตรงนี้แค่พิมพ์ลงไป
    "type_tags":    "พิมพ์แฮชแท็กที่คัดไว้แล้ว (ไม่อ่านยอด)",
    "popup":        "ปิดป็อปอัปถ้ามี",
    "key":          "กดปุ่มระบบ (BACK / ENTER)",
    # ปัดจอไม่ต้องเทรนพิกัด — ปัดกลางจอใช้ได้กับทุกหน้า และ "ปัดให้ถูกที่" ไม่มีอยู่จริง
    # สิ่งที่ต้องถูกคือ **ปัดแล้วเห็นของที่ต้องการ** ซึ่งขั้นถัดไปเป็นคนพิสูจน์เอง
    "swipe":        "ปัดจอขึ้น/ลง",
    "wait":         "รอเฉยๆ",
}

# วิธีตรวจว่าขั้นนั้นสำเร็จจริง
VERIFY_KINDS = {
    "screen_changed": "หน้าจอเปลี่ยนไปจากก่อนกด",
    "text_appears":   "มีข้อความนี้โผล่บนจอ",
    "text_gone":      "ข้อความนี้หายไปจากจอ",
    "app_frontmost":  "แอปนี้ขึ้นมาอยู่หน้าสุด",
    "field_has_text": "ข้อความที่พิมพ์ไปอยู่บนจอจริง",
    "tags_present":   "แฮชแท็กที่เลือกอยู่บนจอครบ",
    "left_screen":    "ออกจากหน้าเดิมไปแล้ว (ใช้กับปุ่มโพสต์)",
    "keyboard_open":  "คีย์บอร์ดเด้งขึ้นมาแล้ว (ใช้กับการแตะช่องพิมพ์)",
    "toggle_on":      "สวิตช์ถูกเปิดแล้ว (ดูจากสีบนจอจริง)",
    "toggle_off":     "สวิตช์ถูกปิดแล้ว (ดูจากสีบนจอจริง)",
    "none":           "ไม่ตรวจ (ใช้เมื่อขั้นนั้นไม่มีผลให้เห็น)",
}

# ตัวตรวจปริยายของแต่ละชนิด — ผู้ใช้เปลี่ยนได้ทีหลังจากหน้าเว็บ
DEFAULT_VERIFY = {
    "open_app":     "app_frontmost",
    "tap":          "screen_changed",
    "type_text":    "field_has_text",
    # วางลิงก์ใช้ text_appears ไม่ใช่ field_has_text — field_has_text ตรวจแค่ 24
    # ตัวแรกของสิ่งที่ "เราส่งไป" ซึ่งผ่านได้แม้แอปจะเอาไปแปะผิดช่อง ส่วน
    # text_appears ให้ระบุ **ข้อความที่ต้องเห็นจริงบนจอ** ได้ตรงๆ
    # (ขั้นในผังตั้งต้นระบุโดเมน Shopee ไว้ ซึ่งคงที่ทุกสินค้า)
    "paste_link":   "text_appears",
    "type_hashtag": "tags_present",
    "type_tags":    "tags_present",
    "popup":        "none",
    "key":          "screen_changed",
    "swipe":        "screen_changed",
    "wait":         "none",
}


@dataclass
class Step:
    """หนึ่งขั้นในผัง — id เป็นกุญแจเก็บพิกัด ห้ามเปลี่ยนหลังเทรนแล้ว"""

    id: str
    name: str
    kind: str = "tap"
    # คำใบ้ไว้หาปุ่มจาก resource-id / content-desc / text — **ใช้ก่อนพิกัดเสมอ**
    # ปุ่มที่เลื่อนไปมาได้ (อยู่ในฟีด/รายการ) ต้องใช้ทางนี้ พิกัดตายตัวเอาไม่อยู่
    # ว่างไว้ = ใช้พิกัดที่เทรนอย่างเดียวเหมือนเดิม
    find: str = ""
    value: str = ""                 # ข้อความที่พิมพ์ / package ของแอป / วินาทีที่รอ
    settle: float = DEFAULT_SETTLE
    optional: bool = False          # ข้ามได้เมื่อยังไม่ได้เทรนหรือตรวจไม่ผ่าน
    verify: str = ""                # ว่าง = ใช้ค่าปริยายตามชนิด
    verify_text: str = ""           # ข้อความที่ใช้กับ text_appears / text_gone
    verify_timeout: float = DEFAULT_VERIFY_TIMEOUT

    def verify_kind(self) -> str:
        return self.verify or DEFAULT_VERIFY.get(self.kind, "screen_changed")


def _step(id_: str, name: str, **kwargs) -> dict:
    return asdict(Step(id=id_, name=name, **kwargs))


# ผังตั้งต้นของแต่ละปลายทาง — เป็นแค่จุดเริ่ม ผู้ใช้เพิ่ม/ลบ/สลับได้ทั้งหมด
#
# **ที่มาของผังชุดนี้ (11 ส.ค. 2026)** ผู้ใช้เดินทั้งสองแอปด้วยมือจริงหนึ่งรอบ
# ผมอัดหน้าจอ + เก็บพิกัดนิ้วจาก /dev/input แล้วให้ผู้ใช้ตรวจทีละขั้นในสมุด
# ขั้นที่เห็นข้างล่างคือผลของการตรวจนั้น ไม่ใช่การเดาจากหน้าตาแอปอีกต่อไป
# ของเดิมเดาไว้ผิดหลายจุด ที่แก้ตามคำสั่งผู้ใช้:
#   Shopee   ต้องกด "คลังภาพ" ก่อนเลือกคลิป · มี "ถัดไป" สองครั้งไม่ใช่ครั้งเดียว ·
#            มีขั้นใส่ข้อความบนคลิปทั้งชุด · **ไม่มีขั้นวางลิงก์** (ผูกสินค้าในแอป)
#   Facebook ต้องสลับไปโปรไฟล์เพจก่อน · **มีขั้นวางลิงก์จริง** ผ่านหน้า
#            "สร้างลิงก์กำหนดเอง" ซึ่งเป็นทางเดียวที่ได้ค่าคอมมิชชั่น
#
# บันทึกเต็มพร้อมภาพครอบทุกจุดอยู่ที่ data/publish_flows/LEARNED_STEPS.md
DEFAULT_SEQUENCES: dict[str, list[dict]] = {
    "shopee_video": [
        _step("open_app", "เข้าแอป Shopee", kind="open_app",
              value=SHOPEE_PACKAGE, settle=3.0),
        # **ขั้นนี้ตรวจไม่ได้จริงๆ — จึงประกาศตรงๆ ว่าไม่ตรวจ**
        #
        # ไล่มาแล้วสองแบบ ทั้งคู่ใช้ไม่ได้ด้วยเหตุผลคนละข้อ (วัดกับจอ 3 · 26 ส.ค. 2026)
        #
        #   "จอต้องเปลี่ยน"  ล้มทุกครั้งที่**เราอยู่หน้านั้นอยู่แล้ว** — Shopee จำแท็บ
        #                    สุดท้ายไว้ แม้ force-stop ก็ยังกลับมาที่ Live & Video
        #                    กดแท็บเดิมซ้ำจอไม่เปลี่ยน = ฟ้องว่าไม่ผ่านทั้งที่ถูกที่แล้ว
        #
        #   "ต้องเห็นคำว่า…" อ่านหน้าจอไม่ได้เลย **ล้ม 12 ครั้งรวด** เพราะ uiautomator
        #                    รอให้จอนิ่งก่อนถึงจะดูดผังได้ แต่ฟีดวิดีโอเล่นตลอดเวลา
        #                    จอไม่มีวันนิ่ง (แม้ใส่ตัวลองซ้ำ 3 รอบให้แล้วก็ยังล้มหมด)
        #
        # **ยอมประกาศว่าไม่ตรวจ ดีกว่าใส่ตัวตรวจที่ล้มทั้งที่กดถูก** — ตัวตรวจที่
        # ให้คำตอบผิดอันตรายกว่าไม่มีตัวตรวจ (กติกาข้อ 2.3) ที่นี่จึงย้ายภาระการ
        # พิสูจน์ไปไว้ที่ **ขั้นถัดไป** ซึ่งพาออกจากฟีดวิดีโอไปหน้าโปรไฟล์ที่นิ่ง
        # และอ่านได้จริง ถ้าขั้นนี้กดพลาด ขั้นถัดไปจะจับได้เอง = เสียแค่การกดเปล่า
        # หนึ่งครั้ง ไม่ใช่เดินหน้าไปกดมั่วจนถึงปุ่มโพสต์
        _step("live_and_video", "กด Live & Video", settle=2.0, verify="none"),
        # id เดิมคือ tab_mine — **ห้ามเปลี่ยน** เพราะพิกัดที่ผู้ใช้เทรนไว้ผูกกับ id นี้
        # (เปลี่ยนแค่ชื่อที่แสดงให้ตรงกับที่ผู้ใช้เรียกจริง: รูปคน = โปรไฟล์ตัวเอง)
        _step("tab_mine", "กดตรงรูปคน (โปรไฟล์ตัวเอง)", settle=2.0),
        _step("post_video", "กด ＋ โพสต์วิดีโอ", settle=2.0),
        _step("gallery", "กดคลังภาพ", settle=2.0),
        _step("latest_clip", "เลือกคลิปที่จะโพสต์", settle=1.5),
        _step("next_1", "กดถัดไป (ครั้งที่ 1)", settle=1.5),
        _step("next_2", "กดถัดไป (ครั้งที่ 2)", settle=1.5),
        _step("cover_pick", "กดเลือกภาพปก", settle=1.5),
        _step("overlay_add", "กด ⊕ เพิ่มข้อความ", settle=1.5),
        _step("overlay_template", "เลือกเทมเพลตข้อความ"),
        _step("overlay_field", "แตะช่องกรอกข้อความ"),
        _step("overlay_type", "พิมพ์ข้อความบนคลิป", kind="type_text"),
        # ปิดคีย์บอร์ดก่อน ไม่งั้นปุ่ม ✓ ยืนยันภาพปกถูกคีย์บอร์ดบังจนกดไม่โดน
        _step("overlay_keyboard_done", "กดปุ่มปิดคีย์บอร์ด"),
        _step("overlay_confirm", "กดเครื่องหมาย ✓ ของกล่องข้อความ"),
        _step("cover_confirm", "กด ✓ ยืนยันภาพปก", settle=2.0),
        _step("caption_field", "แตะช่องแคปชัน"),
        # ตรวจว่า **แท็กที่คัดมาแล้วอยู่บนจอครบจริง** ไม่ใช่แค่ "จอเปลี่ยน"
        # พิมพ์แท็กแล้วแอปอาจกินไปบางตัว (ยาวเกิน / อักขระไม่รับ) ซึ่งจะเงียบสนิท
        _step("hashtag_type", "พิมพ์ # ตามลิสต์ (คัดตามยอดพูดถึง)", kind="type_hashtag",
              verify="tags_present"),
        # ผู้ใช้สั่งเพิ่ม 25 ส.ค. 2026 — "ถัดจาก 18 มันจะมีแคปชั่นที่ให้ google
        # gemini คิดมาใช่ไหม เอาอันนั้นมาพิมพ์ต่อ"
        #
        # **ห้ามใส่ `value`** — เว้นว่างไว้ตัวรันจะหยิบ `context.caption` ของงานนั้น
        # มาพิมพ์เอง (ชื่อสินค้า + จุดเด่นที่ AI คัด + ลิงก์ affiliate)
        # ถ้าใส่ข้อความตายตัว ทุกคลิปจะได้แคปชันเดียวกันหมด
        _step("caption_type", "พิมพ์แคปชันของงานนี้ (ที่ AI คิดไว้)",
              kind="type_text", settle=1.5),
        _step("hashtag_confirm", "กดตกลง"),
        _step("product_open", "แตะเพื่อเพิ่มสินค้า", settle=2.0),
        # ผูกสินค้าด้วย **การวางลิงก์** ไม่ใช่ค้นหาชื่อ — ผู้ใช้ยืนยัน 11 ส.ค.
        # ค้นหาด้วยชื่อได้สินค้าผิดตัวง่ายมาก (ชื่อสินค้า Shopee ซ้ำกันทั้งตลาด)
        # ส่วนลิงก์ที่วางคือลิงก์ affiliate ตัวเดียวกับที่ส่งเข้ามาทาง Telegram
        _step("product_link_field", "แตะช่องวางลิงก์สินค้า"),
        # ตรวจว่า **ลิงก์ไปอยู่บนจอจริง** โดยเกาะโดเมน Shopee ซึ่งคงที่ทุกสินค้า
        # (ลิงก์ affiliate จริงหน้าตา https://s.shopee.co.th/xxxxxxxx)
        # เกาะทั้งลิงก์ไม่ได้เพราะเปลี่ยนทุกงาน และแอปมักตัดท้ายด้วย …
        _step("link_paste", "วางลิงก์ Shopee", kind="paste_link",
              verify="text_appears", verify_text=r"shopee\.co\.th|shopee\.com"),
        # ผู้ใช้สั่งเพิ่ม 25 ส.ค. 2026 — "เอาลิ้ง shopee จากงานนั้นๆ ไปวาง"
        # วางลิงก์เดิมของงานนั้นซ้ำอีกที่หนึ่ง ต่อจากขั้นวางลิงก์ข้างบน
        #
        # ตั้งเป็นขั้นข้ามได้ (`optional`) เพราะบางหน้าไม่มีช่องที่สอง
        # ถ้าไม่ข้ามได้ จะค้างทั้งงานเพียงเพราะหาช่องไม่เจอ
        _step("affiliate_paste", "วางลิงก์ Shopee ของงานนี้ (ซ้ำอีกที่)",
              kind="paste_link", optional=True, settle=1.5),
        _step("product_import", "กดนำเข้า", settle=2.5),
        _step("product_pick", "กดรายการสินค้าที่ค้นเจอ"),
        _step("product_add", "กดเพิ่ม", settle=2.0),
        # สองสวิตช์นี้ต้องตั้งทุกครั้ง ค่าไม่ติดข้ามโพสต์
        _step("duet_off", "กดปิด duet (อนุญาตให้นำเนื้อหาไปใช้ซ้ำ)"),
        _step("ai_label_on", "กดระบุว่าเป็น AI"),
        _step("post", "กดโพสต์", settle=4.0,
              verify="text_appears", verify_text="สำเร็จ|โพสต์แล้ว|เผยแพร่|กำลังอัป"),
    ],
    "facebook_reels": [
        _step("open_app", "เข้าแอป Facebook", kind="open_app",
              value=FACEBOOK_PACKAGE, settle=3.0),
        # **ยืนยันว่าโพสต์ในนามเพจ ไม่ใช่สลับให้** — โพสต์ผิดโปรไฟล์แล้วเรียกคืนไม่ได้
        # แอปจำโปรไฟล์ล่าสุดไว้เอง การกดสลับซ้ำตอนที่ถูกอยู่แล้วจะไม่มีอะไรเกิดขึ้น
        # แล้วตัวตรวจจะค้าง จึงเปิดเมนูมา "อ่านว่าใครอยู่" แทน ผิดเมื่อไรหยุดทันที
        _step("menu_open", "กดเมนู ☰", find="เมนู", settle=2.0),
        _step("check_page", "ยืนยันว่ากำลังใช้โปรไฟล์เพจ", kind="wait", value="0.5",
              verify="text_appears", verify_text="Squishy Cute Club"),
        _step("menu_close", "ปิดเมนู", kind="key", value="BACK", settle=1.5),
        # ปุ่มพวกนี้เลื่อนไปกับฟีด (เจอจริง: y=168 รอบหนึ่ง y=443 อีกรอบ)
        # จึงต้องเกาะ content-desc พิกัดเป็นแค่ตาข่ายรองรับ
        _step("reels_tab", "กดแท็บ Reels", find="แท็บ Reels", settle=2.0),
        _step("create_reel", "กดการ์ดสร้างคลิป Reels",
              find="สร้างคลิป Reels", settle=2.5),
        _step("latest_clip", "เลือกคลิปที่จะโพสต์", settle=1.5),
        _step("next_1", "กดถัดไป", settle=2.0),
        _step("caption_field", "แตะช่องคำอธิบาย"),
        # **ไม่ใช่ type_hashtag** เพราะ Facebook ไม่ได้โชว์ยอดพูดถึงข้างตัวเลือก
        # ตัวคัดจึงอ่านยอดไม่ได้สักตัวแล้วตัดทิ้งหมด (เหตุผลเต็มที่ run_tags_step)
        _step("hashtag_type", "พิมพ์ hashtag ตามลิสต์", kind="type_tags"),
        _step("scroll_to_product", "เลื่อนลงหาเมนูเพิ่มสินค้า",
              kind="swipe", value="down"),
        _step("product_open", "กดเพิ่มสินค้า", find="เพิ่มสินค้า", settle=2.5),
        _step("custom_link", "กดสร้างลิงก์กำหนดเอง", settle=2.5),
        _step("url_field", "แตะช่อง URL", find="URL"),
        # ตรวจว่า **ลิงก์ไปอยู่บนจอจริง** โดยเกาะโดเมน Shopee ซึ่งคงที่ทุกสินค้า
        # (ลิงก์ affiliate จริงหน้าตา https://s.shopee.co.th/xxxxxxxx)
        # เกาะทั้งลิงก์ไม่ได้เพราะเปลี่ยนทุกงาน และแอปมักตัดท้ายด้วย …
        _step("link_paste", "วางลิงก์ Shopee", kind="paste_link",
              verify="text_appears", verify_text=r"shopee\.co\.th|shopee\.com"),
        _step("save_1", "กดบันทึก (หน้าลิงก์)", find="บันทึก", settle=2.5),
        _step("save_2", "กดบันทึก (หน้าเพิ่มสินค้า)", find="บันทึก", settle=2.5),
        _step("scroll_to_ai", "เลื่อนลงมาด้านล่าง", kind="swipe", value="down"),
        _step("ai_label_on", "กดเพิ่มป้าย AI"),
        _step("share", "กดแชร์เลย", find="แชร์เลย", settle=4.0,
              verify="text_appears", verify_text="กำลังอัปโหลด|โพสต์แล้ว|เผยแพร่"),
    ],
}

TARGET_NAMES = {
    "shopee_video": "Shopee Video",
    "facebook_reels": "Facebook Reels",
}


def _safe_name(serial: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", serial or "")[:80]


# --------------------------------------------------------------- ที่เก็บผัง


def _upgrade_sequence(target: str, sequence: list[dict]) -> bool:
    """อัปเกรดผังที่บันทึกไว้แล้วให้ตรงกับกติกาใหม่ — คืน True ถ้ามีอะไรเปลี่ยน

    **ทำไมต้องมีตัวนี้** ผังของแต่ละเครื่องถูก *คัดลอก* จากค่าตั้งต้นในโค้ดตั้งแต่
    ครั้งแรกที่เปิดใช้ แล้วเก็บแยกเป็นไฟล์ของเครื่องนั้น การแก้ค่าตั้งต้นทีหลัง
    **จึงไม่มีผลกับเครื่องที่ตั้งไปแล้ว** ถ้าไม่ไล่แก้ตรงนี้ คำว่า "แก้แล้ว"
    จะจริงเฉพาะเครื่องที่ยังไม่เคยใช้ ส่วนเครื่องจริงของผู้ใช้ยังพังเหมือนเดิม
    (วัดจริง 25 ส.ค. 2026: มีผังที่บันทึกไว้แล้ว 2 เครื่อง ทั้งคู่มีขั้นนี้)

    ตอนนี้มีข้อเดียว — **Facebook ไม่ได้โชว์ยอดพูดถึงข้างตัวเลือกแฮชแท็ก**
    ขั้นที่ตั้งเป็น "คัดตามยอดพูดถึง" จึงอ่านยอดไม่ได้สักตัว แล้วตัดทิ้งทั้งหมด
    จบด้วย "ไม่มีแฮชแท็กตัวไหนผ่านเกณฑ์เลย" = โพสต์ไม่ออก
    """
    if target != "facebook_reels":
        return False
    changed = False
    for entry in sequence:
        if entry.get("kind") == "type_hashtag":
            entry["kind"] = "type_tags"
            # ตัวตรวจเดิมของ type_hashtag คือ tags_present ซึ่งใช้กับตัวใหม่ได้เลย
            # แต่ถ้าผู้ใช้เคยตั้งเป็นอย่างอื่นไว้ **ห้ามทับ** ของที่เขาตั้งเอง
            if not entry.get("verify"):
                entry["verify"] = "tags_present"
            changed = True
    return changed


class FlowStore:
    """ผัง + พิกัดของเครื่องหนึ่ง แยกตามปลายทาง

    เก็บรวมไฟล์เดียวต่อเครื่องเพราะย้ายเครื่อง/สำรองข้อมูลทีเดียวจบ
    """

    def __init__(self, serial: str, root: Path | None = None) -> None:
        self.serial = serial
        base = (root or DATA_DIR) / "publish_flows"
        self.path = base / f"{_safe_name(serial)}.json"
        self.data: dict = {"serial": serial, "targets": {}}
        self.load()

    def load(self) -> None:
        if self.path.is_file():
            try:
                self.data = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                pass
        self.data.setdefault("serial", self.serial)
        self.data.setdefault("targets", {})

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temporary.replace(self.path)      # เขียนแบบ atomic กันไฟล์พังตอนไฟดับ

    # ------------------------------------------------------------- ลำดับขั้น

    def _target(self, target: str) -> dict:
        if target not in DEFAULT_SEQUENCES:
            raise StepError(f"ไม่รู้จักปลายทาง {target}")
        block = self.data["targets"].setdefault(target, {})
        block.setdefault("sequence", [dict(s) for s in DEFAULT_SEQUENCES[target]])
        block.setdefault("positions", {})
        if _upgrade_sequence(target, block["sequence"]):
            self.save()
        return block

    def sequence(self, target: str) -> list[Step]:
        raw = self._target(target)["sequence"]
        steps: list[Step] = []
        for entry in raw:
            allowed = {k: v for k, v in entry.items() if k in Step.__annotations__}
            steps.append(Step(**allowed))
        return steps

    def _write_sequence(self, target: str, steps: list[Step]) -> None:
        self._target(target)["sequence"] = [asdict(step) for step in steps]
        self.save()

    def _new_id(self, target: str) -> str:
        """id ของขั้นที่เพิ่มเอง — เดินหน้าอย่างเดียว ไม่วนใช้เลขซ้ำ

        ถ้าวนใช้เลขซ้ำ ขั้นใหม่จะไปหยิบพิกัดเก่าของขั้นที่ลบไปแล้วมาแตะ
        ซึ่งคือการกดมั่วบนหน้าจอที่ไม่รู้ว่าคืออะไร
        """
        block = self._target(target)
        counter = int(block.get("next_id", 1))
        used = {step["id"] for step in block["sequence"]}
        while f"step_{counter}" in used:
            counter += 1
        block["next_id"] = counter + 1
        return f"step_{counter}"

    def insert_step(
        self, target: str, name: str, after_id: str = "", kind: str = "tap"
    ) -> Step:
        if kind not in KINDS:
            raise StepError(f"ไม่รู้จักชนิดขั้น {kind}")
        steps = self.sequence(target)
        step = Step(id=self._new_id(target), name=name[:80] or "ขั้นใหม่", kind=kind)
        index = len(steps)
        for position, existing in enumerate(steps):
            if existing.id == after_id:
                index = position + 1
                break
        steps.insert(index, step)
        self._write_sequence(target, steps)
        return step

    def delete_step(self, target: str, step_id: str) -> bool:
        steps = self.sequence(target)
        kept = [step for step in steps if step.id != step_id]
        if len(kept) == len(steps):
            return False
        self._write_sequence(target, kept)
        # ลบพิกัดทิ้งด้วย เพราะ id นี้จะไม่ถูกใช้ซ้ำอีก เก็บไว้ก็เป็นขยะ
        self._target(target)["positions"].pop(step_id, None)
        self.save()
        return True

    def move_step(self, target: str, step_id: str, offset: int) -> bool:
        steps = self.sequence(target)
        ids = [step.id for step in steps]
        if step_id not in ids:
            return False
        old = ids.index(step_id)
        new = max(0, min(len(steps) - 1, old + offset))
        if new == old:
            return False
        steps.insert(new, steps.pop(old))
        self._write_sequence(target, steps)
        return True

    def update_step(self, target: str, step_id: str, **changes) -> Step:
        steps = self.sequence(target)
        for step in steps:
            if step.id != step_id:
                continue
            for key, value in changes.items():
                if value is None or key not in Step.__annotations__:
                    continue
                if key == "kind" and value not in KINDS:
                    raise StepError(f"ไม่รู้จักชนิดขั้น {value}")
                if key == "verify" and value and value not in VERIFY_KINDS:
                    raise StepError(f"ไม่รู้จักวิธีตรวจ {value}")
                setattr(step, key, value)
            self._write_sequence(target, steps)
            return step
        raise StepError(f"ไม่พบขั้น {step_id}")

    def reset(self, target: str) -> None:
        """คืนผังตั้งต้น — **เก็บพิกัดไว้** เพื่อให้ขั้นเดิมที่ id ตรงกันใช้ต่อได้เลย"""
        self._target(target)["sequence"] = [
            dict(step) for step in DEFAULT_SEQUENCES[target]
        ]
        self.save()

    # ---------------------------------------------------------------- พิกัด

    def train(
        self, target: str, step_id: str, x: int, y: int, width: int, height: int
    ) -> dict:
        if not width or not height:
            raise StepError("ไม่รู้ขนาดจอ เทรนไม่ได้")
        point = {
            "rx": round(x / width, 5),
            "ry": round(y / height, 5),
            "trained_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        self._target(target)["positions"][step_id] = point
        self.save()
        return point

    def clear_position(self, target: str, step_id: str) -> bool:
        removed = self._target(target)["positions"].pop(step_id, None) is not None
        if removed:
            self.save()
        return removed

    def point_for(
        self, target: str, step_id: str, width: int, height: int
    ) -> tuple[int, int] | None:
        entry = self._target(target)["positions"].get(step_id)
        if not entry:
            return None
        return int(entry["rx"] * width), int(entry["ry"] * height)

    def positions(self, target: str) -> dict:
        return dict(self._target(target)["positions"])


# ------------------------------------------------------- อ่านหน้าจอมือถือ


UI_DUMP_PATH = "/sdcard/window_dump.xml"

NODE_RE = re.compile(
    r'<node[^>]*?text="([^"]*)"[^>]*?bounds="\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]"'
)

# ข้อความบนแถบสถานะที่เปลี่ยนเองตลอดเวลา — ต้องตัดออกก่อนเทียบว่าจอเปลี่ยนไหม
# ไม่งั้นนาฬิกาเดินหนึ่งนาทีจะทำให้ระบบคิดว่า "กดติดแล้ว" ทั้งที่ไม่มีอะไรเกิดขึ้น
VOLATILE_RE = re.compile(r"^(\d{1,2}:\d{2}(:\d{2})?|\d{1,3}\s*%|[\d.]+\s*(KB|MB|GB)/s)$")


# อ่านผังจอไม่ได้แล้วลองใหม่กี่รอบ — **จำเป็นมากบนฟีดวิดีโอ**
#
# วัดกับจอ 3 บนหน้า Live & Video ของ Shopee เมื่อ 26 ส.ค. 2026: อ่าน 5 ครั้ง
# **ล้ม 3 สำเร็จ 2** (ล้ม 60%) เพราะ `uiautomator` รอให้หน้าจอ "นิ่ง" ก่อนถึงจะ
# ดูดผังได้ แต่ฟีดวิดีโอเล่นตลอดเวลา หน้าจอจึงไม่เคยนิ่ง มันเลยยอมแพ้ด้วย
# "could not get idle state" ซึ่งกินเวลา **13 วินาทีต่อครั้งที่ล้ม**
#
# ผลที่เกิดจริง: วงจรตรวจผลมีเวลา 10 วินาที แต่การอ่านที่ล้มกิน 13 วินาที
# **จึงได้ลองแค่ครั้งเดียวเสมอ** = ทุกขั้นบนฟีดวิดีโอมีโอกาสล้มฟรี 60%
# ทั้งที่กดถูกทุกอย่าง (ขั้น "กด Live & Video" ล้มด้วยเหตุนี้)
#
# ลองซ้ำในตัวอ่านเองแทนที่จะไปยืดเวลาตรวจ เพราะทุกคนที่เรียกตัวอ่านได้ประโยชน์
# หมด ไม่ต้องไล่แก้ทีละจุด และของที่ล้มเพราะจอไม่นิ่งคือ **ล้มชั่วคราว** ล้วนๆ
UI_DUMP_TRIES = 3
UI_DUMP_RETRY_GAP = 0.6


def dump_ui(run_adb: Callable[..., bytes], log: Callable[[str], None] | None = None) -> str:
    """คืน XML ลำดับชั้น UI ของหน้าจอปัจจุบัน — คืนค่าว่างถ้าอ่านไม่ได้

    **ต้องลบไฟล์เก่าทิ้งก่อนเสมอ** บางหน้าจอ uiautomator dump ล้มจริง
    (หน้าตัดต่อคลิป Reels ของ Facebook ล้มทุกครั้ง — ยืนยัน 12 ส.ค.) ถ้าไม่ลบก่อน
    คำสั่ง cat จะคืนผังของ "หน้าที่แล้ว" กลับมา แล้วตัวตรวจจะตัดสินจากหน้าจอผิดตัว
    โดยไม่มีอะไรฟ้อง — ซึ่งอันตรายกว่าไม่มีตัวตรวจเลย
    """
    for attempt in range(1, UI_DUMP_TRIES + 1):
        run_adb("shell", "rm", "-f", UI_DUMP_PATH)
        run_adb("shell", "uiautomator", "dump", UI_DUMP_PATH)
        raw = run_adb("shell", "cat", UI_DUMP_PATH)
        xml = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)
        if "<node" in xml:
            if attempt > 1 and log:
                log(f"   อ่านผังจอได้ในรอบที่ {attempt}")
            return xml
        if attempt < UI_DUMP_TRIES:
            time.sleep(UI_DUMP_RETRY_GAP)
    if log:
        log(f"   ⚠️ อ่านผังจอไม่ได้เลยทั้ง {UI_DUMP_TRIES} รอบ "
            "— หน้าจอนี้มีอะไรขยับตลอด (วิดีโอเล่นอยู่)")
    return ""


# รูปแบบจริงจากมือถือคือ  mCurrentFocus=Window{e36e918 u0 com.shopee.th/…Activity}
# คือมีทั้งรหัสหน้าต่างและ user id คั่นก่อนถึงชื่อแอป **สองช่องว่าง** ไม่ใช่ช่องเดียว
#
# ของเดิมเขียนไว้ว่า `\S*\s+(pkg/Activity)` ซึ่งบังคับให้ชื่อแอปอยู่ถัดจากช่องว่างแรก
# → **ไม่เคยจับได้เลยสักครั้ง** `foreground()` จึงคืนค่าว่างเสมอ ผลคือเวลาดูดผัง UI
# ไม่ได้ ลายเซ็นสำรองกลายเป็น "หน้าจอ:" เท่ากันทุกครั้ง = ตัวตรวจตาบอด ทุกขั้นจะ
# ฟ้อง "หน้าจอยังเหมือนเดิม" ทั้งที่กดติด (พิสูจน์กับเครื่องจริง 19 ส.ค. 2026)
#
# เกาะ `{…}` แล้วค่อยหาโทเคนที่มี `/` แบบเดียวกับ `frontmost_package` ซึ่งถูกอยู่แล้ว
# หน้าต่างระบบที่ไม่มีชื่อแอป (เช่น NotificationShade) จะไม่ match = คืนค่าว่าง ถูกต้อง
FOCUS_RE = re.compile(r"mCurrentFocus=\S*\{[^}]*?\s([\w.]+/[\w.$]+)")


def foreground(run_adb: Callable[..., bytes]) -> str:
    """ชื่อหน้าจอที่อยู่หน้าสุด — ใช้แทนลายเซ็นเมื่ออ่านผัง UI ไม่ได้

    หยาบกว่าการเทียบผังมาก (เปลี่ยนเนื้อหาในหน้าเดิมจะจับไม่ได้) แต่ยัง
    **จริง** อยู่ ดีกว่าเดาว่าผ่านตอนที่ไม่รู้อะไรเลย
    """
    raw = run_adb("shell", "dumpsys", "window", "displays")
    out = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)
    found = FOCUS_RE.search(out)
    return found.group(1) if found else ""


def iter_nodes(xml: str):
    """คืน (ข้อความ, x1, y1, x2, y2) ของทุก node ที่มีข้อความ"""
    for match in NODE_RE.finditer(xml or ""):
        text = match.group(1)
        if not text:
            continue
        yield (text, *(int(match.group(i)) for i in range(2, 6)))


def find_node(xml: str, pattern: str) -> tuple[int, int] | None:
    """หา node ที่ข้อความตรง pattern คืนจุดกึ่งกลางเป็นพิกัดจริง"""
    regex = re.compile(pattern, re.I)
    for text, x1, y1, x2, y2 in iter_nodes(xml):
        if regex.search(text):
            return ((x1 + x2) // 2, (y1 + y2) // 2)
    return None


# ตัวหาปุ่มแบบเกาะ "ป้ายชื่อ" ของ element แทนพิกัด
#
# **ทำไมต้องมี** จากการไล่ Facebook จริง 12 ส.ค. — แท็บ Reels อยู่ y=168 รอบหนึ่ง
# แล้ว y=443 อีกรอบ เพราะมันเลื่อนไปกับฟีด พิกัดตายตัวจึงกดพลาดแน่นอน
# แต่ content-desc ของมัน ("แท็บ Reels") ไม่เปลี่ยน
#
# สำรวจไว้ก่อนหน้านี้: หน้าแรก Shopee มี resource-id 24% · content-desc 38% ·
# text 0% — ตัวหาเดิมที่ค้นแต่ text จึงหาอะไรไม่เจอเลย
ELEMENT_RE = re.compile(r"<node\b[^>]*?>")


def _attr(raw: str, name: str) -> str:
    found = re.search(name + r'="([^"]*)"', raw)
    return found.group(1) if found else ""


def find_target(xml: str, needle: str) -> tuple[int, int] | None:
    """หา element จากคำใบ้เดียว โดยลอง resource-id → content-desc → text

    คืนจุดกึ่งกลาง · เลือกอันที่ **กดได้** ก่อนเสมอ เพราะป้ายข้อความกับปุ่มจริง
    มักเป็นคนละ node กัน (ป้ายอยู่ข้างใน ปุ่มเป็นกรอบข้างนอก) กดที่ป้ายบางที
    ไม่ติดเพราะมันไม่ใช่ตัวรับการกด
    """
    if not needle:
        return None
    low = needle.strip().lower()
    best = None
    for raw in ELEMENT_RE.findall(xml or ""):
        bounds = re.search(r'bounds="\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]"', raw)
        if not bounds:
            continue
        haystack = "|".join((
            _attr(raw, "resource-id").split("/")[-1],
            _attr(raw, "content-desc"),
            _attr(raw, "text"),
        )).lower()
        if low not in haystack:
            continue
        x1, y1, x2, y2 = (int(bounds.group(i)) for i in range(1, 5))
        point = ((x1 + x2) // 2, (y1 + y2) // 2)
        if _attr(raw, "clickable") == "true":
            return point
        best = best or point
    return best


def has_text(xml: str, needle: str) -> bool:
    """มีข้อความนี้อยู่บนจอไหม — เทียบแบบตัดเว้นวรรค กันแอปจัดบรรทัดใหม่"""
    target = re.sub(r"\s+", "", needle or "")
    if not target:
        return False
    joined = re.sub(r"\s+", "", " ".join(text for text, *_ in iter_nodes(xml)))
    return target in joined


def screen_signature(xml: str) -> str:
    """ลายเซ็นของหน้าจอ ใช้บอกว่า 'เปลี่ยนไปแล้ว' หรือยัง

    นับ **สถานะสวิตช์** เข้าไปด้วย ไม่ใช่แค่ข้อความ — การกดสวิตช์ (ปิด duet /
    เปิดป้าย AI) ไม่ทำให้ข้อความบนจอเปลี่ยนสักตัว ถ้าดูแต่ข้อความจะสรุปว่า
    "กดไม่ติด" ทั้งที่กดติดแล้ว แล้วผังจะหยุดทั้งที่ไม่มีอะไรผิด
    """
    labels = sorted(
        text.strip() for text, *_ in iter_nodes(xml)
        if text.strip() and not VOLATILE_RE.match(text.strip())
    )
    switches = sorted(
        f"{_attr(raw, 'resource-id').split('/')[-1]}"
        f"|{_attr(raw, 'content-desc')[:40]}={_attr(raw, 'checked')}"
        for raw in ELEMENT_RE.findall(xml or "")
        if _attr(raw, "checkable") == "true"
    )
    blob = " ".join(labels) + "\n" + " ".join(switches)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()


def frontmost_package(run_adb: Callable[..., bytes]) -> str:
    """package ของแอปที่อยู่หน้าสุด — ใช้ยืนยันว่าเปิดแอปติดจริง"""
    output = run_adb(
        "shell", "dumpsys", "window", "displays"
    ).decode("utf-8", errors="replace")
    match = re.search(r"mCurrentFocus=.*?\{[^}]*?\s([A-Za-z0-9_.]+)/", output)
    if match:
        return match.group(1)
    output = run_adb("shell", "dumpsys", "activity", "activities").decode(
        "utf-8", errors="replace"
    )
    match = re.search(r"topResumedActivity=.*?\s([A-Za-z0-9_.]+)/", output)
    return match.group(1) if match else ""


POPUP_DISMISS_PATTERNS = [
    r"^ตกลง$", r"^ยอมรับ$", r"^เข้าใจแล้ว$", r"^ปิด$", r"^ข้าม$", r"^ไม่ใช่ตอนนี้$",
    r"^OK$", r"^Got it$", r"^Accept$", r"^Skip$", r"^Close$", r"^Later$", r"^Not now$",
]


# ------------------------------------------------- โฆษณาที่เด้งแทรกกลางผัง
#
# **ทำไมขั้น popup อย่างเดียวไม่พอ** ขั้น popup เป็นขั้นหนึ่งในผัง = ปิดได้เฉพาะ
# ตำแหน่งที่วางไว้ แต่โฆษณา/โปรโมชันของ Shopee เด้งได้ทุกจังหวะ (โดยเฉพาะตอน
# เพิ่งเปิดแอปและตอนสลับหน้า) เด้งมาคั่นตรงไหนก็บังปุ่มของขั้นนั้นจนทั้งผังหยุด
#
# ตัวนี้จึงทำงาน **ทุกขั้น** โดยไม่ต้องเพิ่มขั้นในผัง และไม่กินเวลาเพิ่ม เพราะ
# ใช้ผัง UI ที่ run_step อ่านมาอยู่แล้วตอนจดลายเซ็นหน้าจอก่อนเริ่มขั้น

# คำที่ยืนยันว่าสิ่งที่บังอยู่คือโฆษณาจริง ไม่ใช่หน้าจอปกติของผัง
AD_MARKERS = [r"โฆษณา", r"ผู้สนับสนุน", r"Sponsored", r"Advertisement"]

# ปุ่มปิด — เรียงจากเจาะจงไปกว้าง กดตัวที่เจาะจงก่อนเสมอ
#
# **ห้ามใส่คำที่ผังใช้จริง** เช่น "ตกลง" "ยอมรับ" "ถัดไป" เพราะถ้าเผลอกด
# ระหว่างขั้นปกติจะกลายเป็นการกดยืนยันอะไรบางอย่างแทนผู้ใช้ ซึ่งร้ายกว่าโฆษณา
# ที่ปิดไม่ได้ — ตัวปิดโฆษณาต้องปิดอย่างเดียว ห้ามตัดสินใจแทน
AD_CLOSE_TEXTS = [
    r"^ปิดโฆษณา$", r"^ข้ามโฆษณา$", r"^ไม่สนใจ$", r"^ไม่ ?ขอบคุณ$", r"^ไม่เอา$",
    r"^ไว้ก่อน$", r"^ภายหลัง$", r"^ปิด$",
    r"^Close ?ad$", r"^Skip ?ad$", r"^No,? ?thanks$", r"^Maybe later$",
    r"^Dismiss$", r"^Close$",
    r"^[×✕✖✗Xx]$",                      # กากบาทมุมกล่อง — ต้องเป็นตัวเดียวโดดๆ
]

# ป้ายกำกับของปุ่มปิดที่ไม่มีข้อความ (กากบาทที่เป็นรูปภาพ) — หาใน
# resource-id / content-desc แทน เพราะปุ่มพวกนี้ text ว่างเปล่า
AD_CLOSE_LABELS = ["ปิดโฆษณา", "close_ad", "ad_close", "btn_close", "ปิด", "close"]

# ปิดซ้อนได้กี่ชั้นต่อหนึ่งขั้น — โฆษณาซ้อนกันสองสามชั้นเจอได้ แต่ถ้าปิดแล้ว
# ยังโผล่ไม่หยุดแปลว่าเรากดผิดปุ่ม วนไม่รู้จบดีกว่าหยุดแล้วให้คนดู
AD_DISMISS_MAX = 3


# ---------------------------------------------- ป็อปอัปโปรโมชันที่ไม่มีป้ายอะไรเลย
#
# **ที่ต้องเขียนใหม่ทั้งชุด** ตรวจกับป็อปอัปตัวจริงบนจอ 3 เมื่อ 26 ส.ค. 2026
# (Shopee เด้ง "ซีรีส์สั้นดูฟรี แจก 200,000 COINS" ทับหน้า Live & Video) พบว่า
# ตัวเดิมพังสองต่อ:
#
#   looks_like_ad()  → False   ในป็อปอัปไม่มีคำว่า "โฆษณา/Sponsored" สักคำ
#   find_ad_close()  → (579, 1086) ซึ่งคือปุ่ม "close product panel" ของฟีดวิดีโอ
#                       **คนละปุ่มกันคนละที่** กดแล้วป็อปอัปยังอยู่ แต่ระบบจะจด
#                       ว่า "ปิดโฆษณาแล้ว" — ตัวตรวจที่บอกว่าผ่านทั้งที่ยังไม่ผ่าน
#
# ปุ่มกากบาทจริงของป็อปอัปคือ `[324,1201][396,1273]` ที่ **`clickable="false"`
# และไม่มี text · content-desc · resource-id เลยแม้แต่ตัวเดียว** — หาโดยอ่านป้าย
# เป็นไปไม่ได้ตั้งแต่ต้น จึงต้องเกาะ **รูปทรงและตำแหน่ง** แทน
# (หลักการเดียวกับตัวจับแผ่นคลุมหน้าจอใน chatgpt_driver.py ที่ใช้ได้จริงมาแล้ว)

# แผ่นคลุมต้องกินพื้นที่จอเท่าไรถึงนับว่าเป็นป็อปอัป — ตัวจริงวัดได้ 91.75%
OVERLAY_MIN_COVER = 0.85
# ขนาดด้านของปุ่มกากบาท (พิกเซล) — ตัวจริงที่วัดได้ 72×72 และ 48×48
CLOSE_MIN_SIDE, CLOSE_MAX_SIDE = 32, 120
# เบี้ยวจากกึ่งกลางจอได้กี่ส่วนของความกว้าง — ตัวจริงตรงกึ่งกลางเป๊ะ (360/720)
CLOSE_CENTER_TOLERANCE = 0.08


def _bounds(raw: str) -> tuple[int, int, int, int] | None:
    hit = re.search(r'bounds="\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]"', raw)
    return tuple(int(hit.group(i)) for i in range(1, 5)) if hit else None    # type: ignore[return-value]


def _unlabeled(raw: str) -> bool:
    """node นี้ไม่มีป้ายอะไรให้จับเลยใช่ไหม (ปุ่มรูปภาพล้วน)"""
    return not (_attr(raw, "text") or _attr(raw, "content-desc")
                or _attr(raw, "resource-id"))


def find_overlay_close(xml: str, screen: tuple[int, int]) -> tuple[int, int] | None:
    """หาปุ่มกากบาทของป็อปอัปที่ไม่มีป้าย — คืน None ถ้าไม่มั่นใจ

    **ยอมไม่เจอ ดีกว่าเดาผิด** ถ้ากดพลาดในหน้าที่ไม่ใช่ป็อปอัป อาจไปโดนปุ่ม
    "ซื้อโดยใช้โค้ด" หรือปุ่มโพสต์ ซึ่งร้ายกว่าโฆษณาที่ปิดไม่ได้มาก
    จึงบังคับครบทั้ง 4 ข้อ ขาดข้อเดียวก็คืน None

    เงื่อนไข
      1. มีแผ่นคลุมกดได้กินพื้นที่จอตั้งแต่ 85% ขึ้นไป (= มีอะไรบังอยู่จริง)
      2. มีกล่องเนื้อหากดได้อยู่ข้างใน (= การ์ดโปรโมชัน) และเล็กกว่าแผ่นคลุม
      3. ปุ่มต้องเป็นสี่เหลี่ยมจัตุรัส ด้าน 32–120 px และไม่มีป้ายใดๆ
      4. ปุ่มต้องอยู่ **ใต้การ์ด** และอยู่กลางจอในแนวนอน (±8% ของความกว้าง)
    """
    width, height = screen
    if width <= 0 or height <= 0:
        return None
    area = width * height
    scrim = card = None
    for raw in ELEMENT_RE.findall(xml or ""):
        if _attr(raw, "clickable") != "true":
            continue
        box = _bounds(raw)
        if not box:
            continue
        x1, y1, x2, y2 = box
        size = (x2 - x1) * (y2 - y1)
        if size >= area * OVERLAY_MIN_COVER:
            if scrim is None or size > (scrim[2] - scrim[0]) * (scrim[3] - scrim[1]):
                scrim = box
        elif size > area * 0.10 and _unlabeled(raw):
            if card is None or size > (card[2] - card[0]) * (card[3] - card[1]):
                card = box
    if scrim is None or card is None:
        return None

    middle = width / 2
    best = None
    for raw in ELEMENT_RE.findall(xml or ""):
        box = _bounds(raw)
        if not box or not _unlabeled(raw):
            continue
        x1, y1, x2, y2 = box
        side, tall = x2 - x1, y2 - y1
        if not (CLOSE_MIN_SIDE <= side <= CLOSE_MAX_SIDE):
            continue
        if not (CLOSE_MIN_SIDE <= tall <= CLOSE_MAX_SIDE):
            continue
        if not (0.8 <= side / tall <= 1.25):        # ต้องเป็นจัตุรัส ไม่ใช่แถบยาว
            continue
        if y1 < card[3]:                            # ต้องอยู่ใต้การ์ด ไม่ใช่ในการ์ด
            continue
        away = abs((x1 + x2) / 2 - middle)
        if away > width * CLOSE_CENTER_TOLERANCE:
            continue
        if best is None or away < best[0]:
            best = (away, ((x1 + x2) // 2, (y1 + y2) // 2))
    return best[1] if best else None


def looks_like_overlay(xml: str, screen: tuple[int, int]) -> bool:
    """มีป็อปอัปคลุมจออยู่ไหม — ใช้คู่กับ `looks_like_ad` ที่ดูจากคำ

    ต้องมีทั้งสองตัวเพราะจับคนละอย่าง: ตัวเดิมจับ "โฆษณาที่บอกว่าตัวเองเป็นโฆษณา"
    ส่วนตัวนี้จับ "อะไรก็ตามที่คลุมจนกดของข้างล่างไม่ได้" ซึ่งป็อปอัปโปรโมชัน
    ของ Shopee เข้าข่ายอย่างหลังเท่านั้น
    """
    return find_overlay_close(xml, screen) is not None


def looks_like_ad(xml: str) -> bool:
    """หน้าจอนี้มีโฆษณาบังอยู่ไหม — ดูจากคำที่บอกว่าเป็นโฆษณาเท่านั้น

    เข้มไว้ก่อนโดยตั้งใจ: ถ้าเดาว่าเป็นโฆษณาผิด เราจะไปกดปุ่มปิดของหน้าจอปกติ
    แล้วผังจะพังโดยไม่มีใครรู้ว่าเพราะอะไร
    """
    for pattern in AD_MARKERS:
        if re.search(pattern, xml or "", re.I):
            return True
    return False


def find_ad_close(
    xml: str, screen: tuple[int, int] | None = None
) -> tuple[tuple[int, int], str] | None:
    """หาปุ่มปิดโฆษณา คืน (พิกัด, คำอธิบายว่าเจอจากอะไร)

    **ป็อปอัปคลุมจอต้องมาก่อนการหาจากป้ายเสมอ** เพราะเวลามีป็อปอัปคลุมอยู่
    การไล่หาป้ายจะไปเจอปุ่มปิดของ**หน้าที่อยู่ข้างล่าง** ซึ่งกดไปก็ไม่ช่วยอะไร
    แถมทำให้ระบบเชื่อว่าปิดโฆษณาแล้ว (วัดกับป็อปอัปตัวจริง 26 ส.ค. 2026:
    ได้ปุ่ม "close product panel" ของฟีดวิดีโอ ทั้งที่ป็อปอัปอยู่คนละที่)
    """
    if screen:
        point = find_overlay_close(xml, screen)
        if point:
            return point, "กากบาทของป็อปอัปที่คลุมจอ (หาจากรูปทรง)"
    for pattern in AD_CLOSE_TEXTS:
        point = find_node(xml, pattern)
        if point:
            return point, f"ปุ่มข้อความ {pattern}"
    for label in AD_CLOSE_LABELS:
        point = find_target(xml, label)
        if point:
            return point, f"ปุ่มที่มีป้าย \"{label}\""
    return None


def dismiss_ads(
    context: "RunContext", xml: str = "", force: bool = False
) -> list[str]:
    """ปิดโฆษณาที่บังอยู่ คืนรายการสิ่งที่ปิดไป (ว่าง = ไม่มีอะไรให้ปิด)

    force=True ใช้ตอน "ขั้นล้มเพราะหาปุ่มไม่เจอ" — ตอนนั้นไม่ต้องรอให้เจอคำว่า
    โฆษณา เพราะมีอะไรบางอย่างบังอยู่แน่แล้ว แต่ยังกดได้เฉพาะปุ่มปิดเท่านั้น
    """
    if not getattr(context, "ad_guard", True):
        return []
    closed: list[str] = []
    current = xml
    for _ in range(AD_DISMISS_MAX):
        if not current:
            current = context.dump()
        if not current:
            break
        # ป็อปอัปคลุมจอนับเป็นโฆษณาด้วย แม้ในนั้นจะไม่มีคำว่า "โฆษณา" สักคำ
        # (ป็อปอัปโปรโมชันของ Shopee ไม่เคยเขียนบอกว่าตัวเองเป็นโฆษณา)
        if not force and not (looks_like_ad(current)
                              or looks_like_overlay(current, context.screen)):
            break
        found = find_ad_close(current, context.screen)
        if not found:
            if force:
                # หาปุ่มปิดไม่เจอทั้งที่ขั้นล้ม — พิมพ์ปุ่มที่มีบนจอออกมาให้ดู
                #
                # รายการ AD_CLOSE_TEXTS มาจากการคาดเดารูปแบบปุ่มปิดของ Shopee
                # ยังไม่ได้ยืนยันกับโฆษณาตัวจริง ถ้าปุ่มจริงเขียนต่างจากที่เดาไว้
                # ต้องเห็นข้อความจริงถึงจะเติมเข้ารายการได้ถูก — ไม่ใช่เดาซ้ำ
                labels = []
                for raw in ELEMENT_RE.findall(current):
                    if _attr(raw, "clickable") != "true":
                        continue
                    name = (_attr(raw, "text") or _attr(raw, "content-desc")
                            or _attr(raw, "resource-id").split("/")[-1])
                    if name and name not in labels:
                        labels.append(name[:24])
                    if len(labels) >= 8:
                        break
                if labels:
                    context.log("   หาปุ่มปิดไม่เจอ — ปุ่มที่กดได้บนจอตอนนี้: "
                                + " · ".join(labels))
            break
        point, how = found
        context.tap_at(*point)
        time.sleep(0.8)
        closed.append(how)
        context.log(f"   ปิดโฆษณาที่บังอยู่ ({how})")
        current = ""                    # อ่านจอใหม่ เผื่อมีซ้อนอีกชั้น
        force = False                   # ชั้นถัดไปต้องยืนยันว่าเป็นโฆษณาจริง
    return closed


# ------------------------------------------------------------- บริบทการรัน


@dataclass
class RunContext:
    """สิ่งที่ตัวรันต้องใช้ — ฉีดจากภายนอกเพื่อให้เทสได้โดยไม่ต้องมีมือถือจริง"""

    serial: str
    store: FlowStore
    target: str
    screen: tuple[int, int]
    tap: Callable[[int, int], None]
    type_text: Callable[[str], None]
    run_adb: Callable[..., bytes]
    caption: str = ""
    link: str = ""                                  # ลิงก์ Shopee ที่ส่งมาทาง Telegram
    # วางข้อความผ่านคลิปบอร์ดของมือถือ (ตั้งค่า + สั่งวางในครั้งเดียว)
    # เว้นว่าง = ไม่มีช่องทางนี้ ตัวรันจะถอยไปพิมพ์ทีละตัวอักษรเหมือนเดิม
    set_clipboard: Callable[[str, bool], None] | None = None
    hashtags: list[str] = field(default_factory=list)
    mention_min: int = hashtag_lib.MENTION_MIN
    log: Callable[[str], None] = print
    stop: Callable[[], bool] = lambda: False
    report: Callable[[Step, bool, str], None] = lambda step, ok, message: None
    # ผลการคัดแฮชแท็กจากหน้าจอจริง — เก็บไว้รายงานกลับเข้าแชท
    tag_results: list[dict] = field(default_factory=list)
    # สุ่มเยื้องจุดกดกี่พิกเซล — 0 = ปิด แตะตรงจุดเป๊ะ
    #
    # ต้องปิดตอน **เทรนพิกัด** เพราะตอนนั้นเราต้องพิสูจน์ว่าจุดที่เทรนถูกจริง
    # ถ้าเยื้องแล้วบังเอิญไปโดนปุ่มพอดี เราจะเก็บพิกัดที่ผิดไว้โดยไม่รู้ตัว
    tap_jitter: int = TAP_JITTER_PX
    # สุ่มเวลาพักบวก/ลบกี่ส่วน — 0 = ปิด พักตามที่ตั้งไว้เป๊ะ
    settle_jitter: float = SETTLE_JITTER
    # ปิดโฆษณาที่เด้งแทรกให้อัตโนมัติ — ปิดได้เผื่อต้องไล่บั๊กว่าใครกดปุ่มนั้น
    ad_guard: bool = True
    # โฆษณาที่ปิดไปแล้วทั้งรอบ — รายงานกลับเข้าแชท ไม่ปิดเงียบๆ
    ads_closed: list[str] = field(default_factory=list)
    # แอปที่ผังนี้ต้องอยู่ตลอดทาง — `run_flow` เติมให้เองจากขั้น open_app
    # ใช้จับกรณี "จอเปลี่ยนแล้วก็จริง แต่หลุดไปแอปอื่น" ซึ่งเดิมนับว่าผ่าน
    # เว้นว่าง = ไม่ตรวจ (ผังที่ตั้งใจข้ามแอปยังทำงานได้เหมือนเดิม)
    app_package: str = ""

    # ---------------------------------------------- เตรียมของก่อนเริ่มกดจอ
    #
    # **สองตัวนี้ทำก่อนขั้นที่ 1 เสมอ ไม่ใช่ขั้นในผัง** (ผู้ใช้สั่ง 26 ส.ค. 2026:
    # "ให้เตรียมคลิปเข้าเครื่องเลยตั้งแต่กดเริ่มงาน")
    #
    # ที่ไม่ทำเป็นขั้นในผัง เพราะขั้นในผังถูกแก้/ลบได้จากหน้าเว็บ — ถ้าใครเผลอลบ
    # ขั้นส่งคลิปทิ้ง ผังจะยังเดินได้จนจบแล้ว **โพสต์คลิปของสินค้าอื่น** ซึ่งถอนไม่ได้
    # ส่วนสองตัวนี้อยู่นอกผัง ลบไม่ได้ และใช้ได้กับทุกปลายทางพร้อมกัน

    # ส่งคลิปของงานนี้เข้าเครื่อง แล้วทำให้เป็นวิดีโอใบล่าสุดในแกลเลอรี
    # คืนข้อความบอกว่าทำอะไรไป (ส่งใหม่ / มีอยู่แล้ว) — เว้นว่าง = ไม่มีคลิปให้ส่ง
    #
    # **จำเป็นเพราะขั้น "เลือกคลิปที่จะโพสต์" แตะพิกัดที่เทรนไว้เฉยๆ**
    # มันไม่ได้อ่านว่าช่องนั้นเป็นคลิปอะไร ถ้าคลิปของงานไม่ได้เป็นใบล่าสุด
    # มันจะหยิบคลิปเก่าของสินค้าอื่นมาโพสต์โดยไม่มีอะไรฟ้อง
    # (เจอจริง 26 ส.ค. 2026: ในเครื่องมีแต่คลิปตอนเทรนวันที่ 25 ส.ค. สองใบ)
    send_clip: Callable[[], str] | None = None

    # ปลุกจอ + ปัดปลดล็อก คืนข้อความว่าทำอะไรไป
    #
    # **จำเป็นเพราะไม่มีขั้นไหนในผังปลุกจอเลยสักขั้น** (grep "wake" ได้ 0 ผลลัพธ์)
    # ตัวตรวจของขั้นแรกดูแค่ว่าแอปไหนอยู่หน้าสุด ซึ่ง**ผ่านได้ทั้งที่จอดับสนิท** —
    # แล้วขั้นที่เหลือจะไปแตะบนหน้าล็อกทีละขั้นโดยที่ทุกขั้นรายงานว่า "จอเปลี่ยนแล้ว"
    # (เจอจริง 26 ส.ค. 2026: ขั้น 1 ผ่านทั้งที่ mWakefulness=Asleep)
    wake_screen: Callable[[], str] | None = None

    def tap_at(self, x: int, y: int) -> tuple[int, int]:
        """แตะแบบเยื้องสุ่มเล็กน้อย — **ทางเดียวที่โค้ดในไฟล์นี้ใช้แตะจอ**

        ห้ามเรียก `context.tap()` ตรงๆ ที่ไหนอีก ไม่งั้นจะมีบางขั้นที่แตะจุดเดิม
        เป๊ะทุกครั้งปนอยู่ กลายเป็นลายเซ็นที่เด่นกว่าเดิมเสียอีก

        คืนจุดที่แตะจริง เพื่อให้บันทึกลง log ได้ว่าลงตรงไหน
        """
        point = humanize_point((x, y), self.screen[0], self.screen[1], self.tap_jitter)
        self.tap(*point)
        return point

    def pause(self, seconds: float) -> None:
        """พักแบบสุ่มรอบค่าที่ตั้งไว้"""
        time.sleep(humanize_delay(seconds, self.settle_jitter))

    def dump(self) -> str:
        return dump_ui(self.run_adb, log=self.log)

    def read(self) -> tuple[str, str]:
        """อ่านผังจอ **ครั้งเดียว** แล้วคืนทั้งผังและลายเซ็น

        เดิม signature() อ่านผังมาแล้วทิ้งผังไป ตัวปิดโฆษณาจึงต้องอ่านซ้ำอีกรอบ
        = เสียเวลา adb สองเท่าทุกขั้น (28 ขั้นก็ 28 รอบที่ไม่จำเป็น)
        """
        xml = self.dump()
        return xml, (screen_signature(xml) if xml
                     else "หน้าจอ:" + foreground(self.run_adb))

    def signature(self) -> str:
        """ลายเซ็นหน้าจอสำหรับเทียบว่า "เปลี่ยนไปแล้วหรือยัง"

        ใช้ผัง UI ถ้าอ่านได้ · อ่านไม่ได้ก็ถอยไปใช้ชื่อหน้าจอที่อยู่หน้าสุดแทน
        ห้ามคืนค่าว่างเฉยๆ เพราะว่างเทียบกับว่างจะเท่ากันเสมอ = ตัวตรวจตาบอด
        """
        xml = self.dump()
        return screen_signature(xml) if xml else "หน้าจอ:" + foreground(self.run_adb)


# --------------------------------------------------------------- ตัวตรวจผล


def verify_step(context: RunContext, step: Step, before: str, typed: str = "") -> str:
    """ตรวจว่าขั้นนี้สำเร็จจริง — คืนข้อความอธิบาย ไม่ผ่านให้โยน StepError

    ทุกตัวตรวจเป็นแบบ "รอจนกว่าจะเห็นผล" ไม่ใช่เช็คครั้งเดียวแล้วตัดสิน
    เพราะแอปมือถือวาดหน้าจอช้ากว่าคำสั่งแตะเสมอ
    """
    kind = step.verify_kind()
    if kind == "none":
        return "ไม่ได้ตั้งตัวตรวจ"

    deadline = time.time() + max(1.0, step.verify_timeout)
    last = ""
    while time.time() < deadline:
        if context.stop():
            raise StepError("ถูกสั่งหยุดระหว่างตรวจผล")
        xml = context.dump()

        if kind == "screen_changed":
            # ใช้ลายเซ็นแบบเดียวกับตอนก่อนกด (ถอยไปใช้ชื่อหน้าจอได้ถ้าอ่านผังไม่ได้)
            if context.signature() != before:
                # "จอเปลี่ยน" ตอบได้แค่ว่ามีอะไรเปลี่ยน ตอบไม่ได้ว่า**เปลี่ยนไปถูกที่ไหม**
                #
                # เจอจริง 19 ส.ค. 2026: กด "Live & Video" แล้ว Shopee เด้งหน้า
                # "ยืนยันตัวตน" (WebPageActivity) — จอเปลี่ยนจริงจึงผ่าน แล้วอีก
                # สองขั้นถัดไปก็แตะบนหน้าที่ไม่ใช่ต่อไปอีกโดยไม่มีใครรู้ กว่าจะตาย
                # คือขั้นที่ 4 ทำให้ไล่บั๊กผิดจุดว่าขั้น 4 พัง ทั้งที่พังตั้งแต่ขั้น 2
                #
                # จึงเพิ่มสองด่านตรงนี้ ด่านละเรื่อง:
                where = foreground(context.run_adb)          # "package/Activity"
                landed = where.split("/")[0]

                # ด่าน 1 — ห้ามหลุดออกจากแอปที่ผังกำลังเดินอยู่
                # (เจอจริงเหมือนกัน: แตะแล้วโดนแบนเนอร์ Shopee เปิด Chrome ทิ้งไว้)
                if context.app_package and landed and \
                        not landed.startswith(context.app_package):
                    raise StepError(
                        f"หน้าจอเปลี่ยนก็จริง แต่หลุดออกจากแอป {context.app_package} "
                        f"ไปที่ {where} — ขั้นนี้ไม่ได้พาไปหน้าที่ต้องการ")

                # ด่าน 2 — ถ้าขั้นนี้บอกไว้ว่า "ต้องเห็นข้อความนี้" ก็ต้องเห็นจริง
                # ตั้งได้จากปุ่ม ✎ ในหน้าเว็บ ไม่ต้องแก้โค้ด และไม่ตั้งก็ยังทำงาน
                # เหมือนเดิมทุกประการ — เป็นการ**อัปเกรดทีละขั้นเท่าที่รู้จริง**
                want = (step.verify_text or "").strip()
                if want and not find_node(xml, want):
                    last = f"หน้าจอเปลี่ยนแล้วแต่ยังไม่เจอ “{want}” (ตอนนี้อยู่ที่ {where})"
                else:
                    # บอกด้วยว่าไปโผล่หน้าไหน — log ที่บอกแค่ "เปลี่ยนแล้ว"
                    # ไม่พอให้คนอ่านจับได้ว่าหลงทาง
                    return f"หน้าจอเปลี่ยนแล้ว → {where or 'อ่านชื่อหน้าจอไม่ได้'}"
            else:
                last = "หน้าจอยังเหมือนเดิม"

        elif kind == "text_appears":
            pattern = (step.verify_text or "").strip()
            if not pattern and typed:
                # ไม่ได้ระบุข้อความที่ต้องเห็น แต่ขั้นนี้พิมพ์/วางอะไรลงไป → ใช้สิ่งนั้น
                #
                # **สำคัญ** ของเดิมถอยไปใช้ "." ซึ่งเป็น regex ที่เจออะไรก็ผ่าน
                # = ไม่ได้ตรวจอะไรเลยแต่รายงานว่าตรวจแล้ว ซึ่งแย่กว่าไม่ตรวจ
                # เพราะทำให้คนเชื่อว่ามีด่านอยู่ ต้อง escape ด้วยเพราะลิงก์มี . และ ?
                # ซึ่งเป็นอักขระพิเศษของ regex · ตัดที่ 24 ตัวเพราะแอปมักตัดท้ายด้วย …
                pattern = re.escape(typed.strip()[:24])
            if not pattern:
                raise StepError(
                    "ตั้งวิธีตรวจเป็น “มีข้อความนี้โผล่บนจอ” แต่ไม่ได้บอกว่าข้อความอะไร "
                    "— ไปใส่ที่ปุ่ม ✎ ของขั้นนี้ หรือเปลี่ยนวิธีตรวจ")
            if find_node(xml, pattern):
                return f"เจอข้อความที่รอ ({pattern})"
            last = f"ยังไม่เจอข้อความ {pattern}"

        elif kind == "text_gone":
            pattern = step.verify_text or "."
            if not find_node(xml, pattern):
                return f"ข้อความ {pattern} หายไปแล้ว"
            last = f"ข้อความ {pattern} ยังอยู่"

        elif kind == "app_frontmost":
            package = step.value or ""
            current = frontmost_package(context.run_adb)
            if package and current.startswith(package):
                return f"แอป {package} อยู่หน้าสุดแล้ว"
            last = f"หน้าสุดตอนนี้คือ {current or 'อ่านไม่ได้'} ไม่ใช่ {package}"

        elif kind == "field_has_text":
            probe = (typed or step.value or "").strip()
            if not probe:
                return "ไม่มีข้อความให้ตรวจ ถือว่าผ่าน"
            # ลิงก์/ข้อความยาวมักถูกแอปตัดท้ายด้วย … จึงตรวจแค่ท่อนหน้าที่ยาวพอ
            needle = probe[:24]
            if has_text(xml, needle):
                return f"เห็นข้อความบนจอแล้ว ({needle[:18]}…)"
            last = "ยังไม่เห็นข้อความที่พิมพ์บนจอ"

        elif kind == "left_screen":
            # **ใช้กับปุ่มโพสต์ — ห้ามใช้ "เจอข้อความสำเร็จ"**
            #
            # วัดจากของจริง 28 ส.ค. 2569: กดโพสต์แล้ว Shopee **เด้งกลับ
            # หน้าฟีดเงียบๆ ไม่ขึ้นข้อความว่าสำเร็จเลย** ตัวตรวจเดิมที่รอ
            # คำว่า "สำเร็จ|โพสต์แล้ว|เผยแพร่" จึงตอบว่าไม่ผ่านทั้งที่คลิป
            # ขึ้นจริงแล้ว (ยืนยันจากโปรไฟล์)
            #
            # **อันตรายมาก** เพราะตัวรันจะคิดว่าล้มแล้วกดโพสต์ซ้ำ
            # = คลิปเดียวขึ้นสองรอบ ซึ่งถอนไม่ได้ ต้องไปลบเองในแอป
            #
            # "ออกจากหน้าเดิมแล้ว" เป็นสัญญาณที่ตรงกว่า — หน้าโพสต์จะปิด
            # ตัวเองก็ต่อเมื่อรับงานแล้วเท่านั้น กดไม่ติดหน้าจะยังอยู่ที่เดิม
            where = foreground(context.run_adb)
            # **แอปดับก็นับว่า "ออกจากหน้าเดิม" เหมือนกัน** ถ้าไม่กันไว้
            # แอปแครชหลังกดโพสต์จะถูกนับว่าโพสต์สำเร็จ ซึ่งแย่กว่าตัวเดิม
            landed = where.split("/")[0]
            if context.app_package and landed and not landed.startswith(
                    context.app_package):
                raise StepError(
                    f"ออกจากหน้าเดิมก็จริง แต่หลุดออกจากแอป "
                    f"{context.app_package} ไปที่ {where} — "
                    f"แอปอาจดับ ไม่ใช่โพสต์สำเร็จ")
            if step.verify_text and step.verify_text in where:
                last = f"ยังอยู่หน้าเดิม ({where})"
            elif not step.verify_text and context.signature() == before:
                last = "หน้าจอยังเหมือนเดิม"
            else:
                return f"ออกจากหน้าเดิมแล้ว → {where or 'อ่านชื่อหน้าจอไม่ได้'}"

        elif kind == "keyboard_open":
            # แตะช่องพิมพ์ **ไม่ทำให้เปลี่ยนหน้า** ตัวตรวจ "หน้าจอเปลี่ยน"
            # จึงตอบว่าไม่ผ่านทุกครั้งทั้งที่กดติดแล้ว (เจอจริง 27 ส.ค. 2569
            # — ขั้นแตะช่องแคปชันเสียเวลา 193 วินาทีไปกับการลองซ้ำเปล่าๆ)
            shown = context.run_adb("shell", "dumpsys", "input_method")
            text = shown if isinstance(shown, str) else str(shown)
            if "mInputShown=true" in text:
                return "คีย์บอร์ดเด้งขึ้นแล้ว"
            last = "คีย์บอร์ดยังไม่ขึ้น"

        elif kind in ("toggle_on", "toggle_off"):
            # **ต้องดูสีจริงบนภาพ ไม่ใช่ผังจอ** สวิตช์ของ Shopee ไม่มี
            # `checked` ในผังจอเลย เทียบลายเซ็นหน้าจอจึงไม่มีวันจับได้
            # (ของเดิมตอบ "สวิตช์ยังไม่ขยับ" ตลอดแม้กดติดแล้ว)
            #
            # ตรวจ **สถานะที่ต้องการ** ไม่ใช่ "เปลี่ยนไปจากเดิมไหม" —
            # กดสองครั้งกลับมาที่เดิมจะได้ผลถูกต้องด้วย
            label = (step.find or "").split(":", 1)[-1]
            found = find_row_toggle(context, label, context.screen[0])
            if found is None:
                last = "หาสวิตช์บนจอไม่เจอ"
            else:
                want_on = kind == "toggle_on"
                if found[2] == want_on:
                    return f"สวิตช์{'เปิด' if want_on else 'ปิด'}แล้ว"
                last = f"สวิตช์ยัง{'ปิด' if want_on else 'เปิด'}อยู่"

        elif kind == "tags_present":
            wanted = [item["tag"] for item in context.tag_results if item.get("used")]
            if not wanted:
                # ไม่มีอะไรให้ตรวจ = ขั้นนี้ไม่ได้ทำอะไร **ไม่ใช่ผ่าน**
                # ปล่อยผ่านคือการโกหกว่าตรวจแล้วทั้งที่ไม่ได้ตรวจอะไรเลย
                if step.optional:
                    return "ไม่มีแท็กให้ตรวจ — ขั้นนี้ข้ามได้"
                raise StepError("ไม่มีแท็กถูกใส่ลงไปเลย — ไม่ผ่าน")
            missing = [tag for tag in wanted if not has_text(xml, tag)]
            if not missing:
                return f"เห็นแท็กครบ {len(wanted)} ตัว"
            last = f"ยังไม่เห็นแท็ก {', '.join(missing[:3])}"

        else:
            return f"ไม่รู้จักวิธีตรวจ {kind} — ข้ามการตรวจ"

        time.sleep(0.6)

    raise StepError(f"ตรวจไม่ผ่าน: {last or kind}")


# ------------------------------------------------------- ขั้นพิเศษ: แฮชแท็ก


def _mention_count_for(xml: str, tag: str) -> tuple[int | None, str]:
    """หายอดพูดถึงของแท็กจากแถว suggestion — คืน (ยอด, ข้อความดิบที่อ่านได้)

    วิธี: หา node ที่เป็นชื่อแท็กก่อน แล้วมองหาตัวเลขที่อยู่ **แถวเดียวกัน**
    (กึ่งกลางแนวตั้งห่างกันไม่เกินความสูงของแถว) เพราะแอปวางยอดไว้ท้ายแถวเสมอ
    ไม่ไล่หาตัวเลขทั้งจอ ไม่งั้นจะไปหยิบยอดของแท็กแถวอื่นมาตอบ
    """
    needle = re.sub(r"\s+", "", tag).casefold()
    # **ต้องลองทุกตัวที่ชื่อตรง ไม่ใช่หยุดที่ตัวแรก** (แก้ 27 ส.ค. 2569)
    #
    # ชื่อแท็กโผล่บนจอ **สองที่พร้อมกัน** — ตัวที่เราเพิ่งพิมพ์ลงช่อง
    # กับตัวที่อยู่ในแถวรายการแนะนำ วัดจากผังจอจริง:
    #
    #     #TCL                 ซ้าย 256  บน 195   ← ข้อความในช่องพิมพ์
    #     #TCL                 ซ้าย  32  บน 516   ← แถวรายการแนะนำ
    #     31.2ล้าน การมองเห็น  ซ้าย 480  บน 522   ← ยอด อยู่แถวเดียวกับตัวล่าง
    #
    # ของเดิมหยุดที่ตัวแรก (ตัวในช่องพิมพ์) แล้วหายอดในแถวนั้นไม่เจอ
    # จึงตอบว่า "อ่านยอดไม่ได้" ทุกแท็ก แล้วโดนข้ามหมด
    anchors = [(x1, y1, x2, y2) for text, x1, y1, x2, y2 in iter_nodes(xml)
               if re.sub(r"\s+", "", text).lstrip("#").casefold() == needle]
    if not anchors:
        return None, ""
    for anchor in anchors:
        found = _count_on_row(xml, anchor)
        if found[0] is not None:
            return found
    return None, ""


def _count_on_row(xml: str, anchor: tuple[int, int, int, int]) -> tuple[int | None, str]:
    """หายอดที่อยู่ **แถวเดียวกัน** กับจุดยึดที่ให้มา"""
    ax1, ay1, ax2, ay2 = anchor
    center = (ay1 + ay2) / 2
    tolerance = max(24, (ay2 - ay1))
    best: tuple[int, str] | None = None
    for text, x1, y1, x2, y2 in iter_nodes(xml):
        if (x1, y1, x2, y2) == anchor:
            continue
        if abs(((y1 + y2) / 2) - center) > tolerance:
            continue
        if not hashtag_lib.looks_like_mention(text):
            continue
        count = hashtag_lib.parse_mention_count(text)
        if count is None:
            continue
        # ตัวที่อยู่ขวาสุดของแถวมักเป็นยอด ส่วนซ้ายเป็นชื่อ/ไอคอน
        if best is None or x1 > best[0]:
            best = (x1, text)
    if best is None:
        return None, ""
    return hashtag_lib.parse_mention_count(best[1]), best[1]


def run_hashtag_step(context: RunContext, step: Step) -> str:
    """ใส่แฮชแท็ก — **คัดลอกทั้งชุดแล้ววางทีเดียว** (เจ้าของสั่ง 27 ส.ค. 2569)

    *"เอาใหม่ คัดลอกแฮชแทกมาทั้งหมด แล้ววางเลย ทีเดียว"*

    **ของเดิมพิมพ์ทีละตัวแล้วอ่านยอดพูดถึงจากรายการแนะนำ** ซึ่งพังสามชั้นซ้อน
    เมื่อไล่ทดสอบกับของจริง 27 ส.ค. 2569:

        · ต้องพิมพ์ `#` นำหน้า รายการแนะนำถึงโผล่ (ของเดิมพิมพ์ชื่อเปล่า)
        · Shopee เปลี่ยนคำเป็น "การมองเห็น" ตัวอ่านยอดจึงหาไม่เจอ
        · ชื่อแท็กโผล่สองที่ (ในช่องพิมพ์ + ในรายการ) ระบบยึดผิดตัว

    แก้ครบทั้งสามแล้วยังได้แค่ 2 จาก 5 ตัว เพราะรายการแนะนำโผล่ไม่ทันบ้าง
    กดเลือกไม่ติดบ้าง — **การวางทีเดียวไม่ต้องพึ่งรายการแนะนำเลย** จึงไม่มี
    ชั้นไหนให้พังอีก

    ⚠️ **แลกมาด้วยการเลิกคัดตามยอดพูดถึง** แท็กทุกตัวที่เตรียมไว้จะถูกใส่หมด
    ไม่ได้กรองว่าตัวไหนคนค้นเยอะ — ถ้าอยากกรอง ต้องไปกรองตั้งแต่ตอนคิดแท็ก
    """
    if not context.hashtags:
        # **ห้ามตอบว่าผ่านเด็ดขาด** (แก้ 28 ส.ค. 2569)
        #
        # ของเดิมคืนข้อความเฉยๆ ซึ่งนับเป็น "ผ่าน" แล้วผังเดินต่อจนกดโพสต์
        # ผลคือ **คลิปขึ้นจริงโดยไม่มีแฮชแท็กสักตัว แล้วรายงานว่า 22/22
        # สำเร็จ** — เจอกับตัว 28 ส.ค. 02:27 (Pocket WiFi6) ถ้าเจ้าของ
        # ไม่ทักว่า "ทำไมยังไม่มีแฮชแท็ก" ก็ไม่มีใครรู้เลย
        #
        # กติกาข้อ 2.3 ของโปรเจกต์: ตัวตรวจที่บอกว่าผ่านทั้งที่ยังไม่ผ่าน
        # อันตรายกว่าไม่มีตัวตรวจ เพราะพาไปเชื่อผิดทั้งสาย
        #
        # (ตัวของ Facebook เดิมทำถูกอยู่แล้ว — โยน StepError ถ้าไม่ใช่ขั้น
        # ที่ข้ามได้ ตอนผมรวมสองตัวเข้าด้วยกันเผลอเอาพฤติกรรมที่อ่อนกว่ามาใช้)
        if step.optional:
            return "ไม่มีแฮชแท็กให้ใส่ — ขั้นนี้ข้ามได้ จึงข้ามไป"
        raise StepError(
            "ไม่มีแฮชแท็กให้ใส่ — หยุดก่อนโพสต์ เพราะโพสต์ไปก็ไม่มีแท็กสักตัว\n"
            "สร้างแท็กของสินค้านี้ก่อนด้วย /tags ในแชท แล้วค่อยสั่งลงใหม่")

    tags = []
    for tag in context.hashtags:
        clean = hashtag_lib.normalize(tag)
        if clean and clean not in tags:
            tags.append(clean)
    if not tags:
        return "แฮชแท็กที่ให้มาใช้ไม่ได้สักตัว"

    # **ล้างช่องให้เกลี้ยงก่อนวางเสมอ** (27 ส.ค. 2569)
    #
    # การวางเป็นการ "แทรกตรงเคอร์เซอร์" ไม่ใช่ "เขียนทับ" ถ้ามีของเก่าค้าง
    # อยู่ในช่อง (ลองรอบก่อนแล้วล้ม · ผู้ใช้พิมพ์ค้างไว้) แท็กใหม่จะไปต่อท้าย
    # กลายเป็นข้อความเละ — เจอจริงตอนทดสอบ ได้ "#ตอบสนองไวอมพิวเตอร์#ภาพสวยคมชัด"
    _clear_field(context)

    # เว้นวรรคระหว่างแท็ก — ติดกันแอปจะอ่านเป็นแท็กเดียวยาวๆ
    text = " ".join("#" + t for t in tags)
    context.tag_results = [{"tag": t, "count": None, "raw": "", "used": True}
                           for t in tags]
    _put_tag(context, text)
    context.pause(step.settle)
    context.log(f"  วางแฮชแท็กทีเดียว {len(tags)} ตัว: {text}")
    return f"วางแฮชแท็กแล้ว {len(tags)} ตัว"


def _clear_field(context: RunContext) -> None:
    """ล้างข้อความในช่องที่กำลังโฟกัสให้เกลี้ยง

    เลือกทั้งหมดแล้วลบทีเดียว (Ctrl+A → Del) ถ้าเครื่องไม่รองรับก็ถอยไปกดลบรัวๆ
    เพดาน 200 ครั้งพอสำหรับช่องที่จำกัด 150 ตัวอักษร
    """
    try:
        context.run_adb("shell", "input", "keycombination", "113", "29")
        context.run_adb("shell", "input", "keyevent", "67")
        return
    except Exception:                                          # noqa: BLE001
        pass
    context.run_adb("shell", "input", "keyevent", *(["67"] * 60))


def run_tags_step(context: RunContext, step: Step) -> str:
    """ใส่แฮชแท็กแบบไม่คัดตามยอด — ใช้กับ Facebook Reels

    **เคยหายไปเพราะผมลบทิ้งโดยไม่ตั้งใจ** (28 ส.ค. 2569) ตอนเขียน
    `run_hashtag_step` ใหม่ ผมแทนที่โค้ดตั้งแต่หัวฟังก์ชันนั้นยาวไปถึง
    `_put_tag` ซึ่ง `run_tags_step` นอนอยู่ตรงกลางพอดี — ไวยากรณ์ยังผ่าน
    เพราะที่เรียกใช้อยู่ในฟังก์ชันอื่น Python จึงไม่ฟ้องจนกว่าจะรันถึงบรรทัดนั้น
    **ผัง Facebook Reels จะพังทั้ง 27 ใบตอนรันจริง** ถ้าไม่เจอก่อน

    **ทำไมต้องมีแยกจากของ Shopee ตั้งแต่แรก** (เหตุผลเดิม 25 ส.ค. 2569)
    ตัวคัดตามยอดพูดถึงต้องอ่าน "ยอด" ที่แอปโชว์ท้ายแถวตัวเลือก ซึ่งเป็นของ
    Shopee — **Facebook ไม่โชว์ตัวเลขนั้น** พออ่านไม่ได้ก็ตัดสินว่าไม่ผ่าน
    ทุกตัวแล้วลบทิ้ง จบด้วย "ไม่มีแฮชแท็กตัวไหนผ่านเกณฑ์เลย" = โพสต์ไม่ออกเลย

    **ตอนนี้ทั้งสองทางทำเหมือนกันแล้ว** เพราะเจ้าของสั่งให้ฝั่ง Shopee เลิกคัด
    ตามยอดแล้วเปลี่ยนเป็นวางทีเดียวเหมือนกัน จึงเหลือทางเดียวจริงๆ
    เก็บชื่อนี้ไว้เพราะผังที่บันทึกไว้แล้วอ้างชนิด `type_tags` อยู่
    """
    return run_hashtag_step(context, step)


def _put_tag(context: RunContext, text: str) -> None:
    """ใส่แฮชแท็กลงช่อง — **คัดลอกมาวาง ไม่พิมพ์** (เจ้าของสั่ง 27 ส.ค. 2569)

    *"เปลี่ยนใหม่ให้ copy มาทีละแฮชแทกแล้วเอามาวางเลยไม่ต้องพิมพ์"*

    **ทำไมวางดีกว่าพิมพ์** การพิมพ์ผ่าน ADBKeyboard ส่งตัวอักษรเข้าไปทีละชุด
    ซึ่งแอปมองเป็นการพิมพ์จริง แล้วรายการแนะนำจะไล่โหลดใหม่ทุกตัวอักษร
    ส่วนการวางเป็นเหตุการณ์เดียวจบ แอปเห็นข้อความเต็มทันที

    ผลพลอยได้: ไม่ต้องสลับคีย์บอร์ดไป ADBKeyboard เลยสำหรับขั้นนี้

    วางไม่ได้ก็ถอยไปพิมพ์ **แต่ต้องขึ้น log ว่าถอย** ไม่ใช่เงียบ —
    ถ้าคลิปบอร์ดใช้ไม่ได้ถาวร ต้องรู้ตั้งแต่ครั้งแรก
    """
    if context.set_clipboard:
        try:
            context.set_clipboard(text, True)
            return
        except Exception as error:                             # noqa: BLE001
            context.log(f"  วางผ่านคลิปบอร์ดไม่ได้ ({error}) — ถอยไปพิมพ์แทน")
    context.type_text(text)


def _clear_typed(context: RunContext, text: str) -> None:
    """ลบข้อความที่เพิ่งพิมพ์ทิ้ง — กดลบทีละตัวตามจำนวนอักษรที่พิมพ์ไป"""
    for _ in range(len(text) + 1):
        context.run_adb("shell", "input", "keyevent", "67")   # KEYCODE_DEL


# ------------------------------------------------------------------ ตัวรัน


# ระยะจากขอบขวาถึงกึ่งกลางสวิตช์ — วัดจากของจริง (จอ 720 กว้าง สวิตช์อยู่ที่ 641)
ROW_RIGHT_INSET = 79
# สีพื้นหลังของหน้า — ใช้แยกว่าตรงไหนคือตัวสวิตช์ ตรงไหนคือที่ว่าง
PAGE_BG = (255, 255, 255)
# สีของสวิตช์ตอนปิด (เทาอ่อน) วัดจากของจริง 28 ส.ค. 2569
SWITCH_OFF = (224, 224, 224)
COLOR_SLACK = 12                # ยอมให้เพี้ยนได้เท่านี้ต่อช่องสี


def _near(a, b, slack: int = COLOR_SLACK) -> bool:
    return all(abs(int(x) - int(y)) <= slack for x, y in zip(a, b))


def screen_pixels(context: "RunContext"):
    """ภาพหน้าจอตอนนี้ในรูปที่อ่านสีทีละจุดได้ — คืน None ถ้าอ่านไม่ได้"""
    try:
        import io                                              # noqa: PLC0415
        from PIL import Image                                  # noqa: PLC0415
        raw_png = context.run_adb("exec-out", "screencap", "-p")
        return Image.open(io.BytesIO(raw_png)).convert("RGB")
    except Exception:                                          # noqa: BLE001
        return None


def find_row_toggle(context: "RunContext", label: str, width: int):
    """หาสวิตช์เปิด/ปิดของแถวที่มีป้ายนี้ — คืน (x, y, เปิดอยู่ไหม)

    **หาจากสีบนภาพจริง ไม่ใช่จากผังจอ** เพราะสวิตช์ของ Shopee
    ไม่มี `checkable` ในผังจอเลยสักตัว (ยืนยัน 28 ส.ค. 2569 — ไล่ทั้งผัง
    ได้ 0 รายการ) ผังจอจึงบอกไม่ได้ทั้งว่าสวิตช์อยู่ตรงไหนและเปิดอยู่ไหม

    **ทำไมเอาแค่กึ่งกลางป้ายไม่พอ** ป้ายอยู่บรรทัดบน ส่วนสวิตช์วางกึ่งกลาง
    ของทั้งรายการ (ป้าย + คำอธิบายใต้ป้าย) วัดจริง: ป้ายกึ่งกลางที่ y=846
    แต่ตัวสวิตช์อยู่ y 845–885 กึ่งกลางจริงคือ 865 — แตะที่ 846 คือ
    **ขอบบนสุดพอดี** พอบวกการสุ่มเยื้องนิดเดียวก็หลุดออกนอกปุ่ม
    ซึ่งเป็นเหตุที่ขั้นปิด duet กดไม่ติดทั้งที่พิกัดดู "ใกล้เคียง"
    """
    regex = re.compile(label, re.I)
    top = None
    for text, _x1, y1, _x2, _y2 in iter_nodes(context.dump()):
        if regex.search(text):
            top = y1
            break
    if top is None:
        return None
    image = screen_pixels(context)
    if image is None:
        return None
    x = max(0, width - ROW_RIGHT_INSET)
    hits = []
    for y in range(max(0, top - 20), min(image.size[1], top + 180)):
        if not _near(image.getpixel((x, y)), PAGE_BG):
            hits.append(y)
        elif hits:
            break                   # เจอครบหนึ่งก้อนแล้ว พอ
    if not hits:
        return None
    middle = (hits[0] + hits[-1]) // 2
    on = not _near(image.getpixel((x, middle)), SWITCH_OFF)
    return (x, middle, on)


def locate(
    context: RunContext, step: Step, width: int, height: int
) -> tuple[tuple[int, int] | None, str]:
    """หาจุดที่จะแตะ — **หาจากป้ายชื่อก่อน แล้วค่อยตกไปใช้พิกัดที่เทรน**

    เรียงลำดับแบบนี้เพราะป้ายชื่อ (resource-id / content-desc) ทนต่อการเลื่อนจอ
    และการอัปเดตแอป ส่วนพิกัดเป็นตาข่ายรองรับสำหรับปุ่มที่ไม่มีป้ายอะไรเลย
    (Shopee 38% ของปุ่มบนหน้าแรกไม่มีทั้ง id ทั้ง desc ทั้ง text)
    """
    if step.find:
        # `แถวขวา:ข้อความ` = หาป้ายก่อน แล้วแตะที่ **ปลายขวาของแถวนั้น**
        #
        # ใช้กับสวิตช์เปิด/ปิดที่ไม่มีป้ายอะไรเลยบนตัวมันเอง แต่มีข้อความ
        # อธิบายอยู่ซ้ายมือในแถวเดียวกัน — แตะที่ป้ายตรงๆ ไม่ทำให้สวิตช์ขยับ
        #
        # **ทำไมต้องมี** (27 ส.ค. 2569) ขั้นปิด duet กับติ๊ก AI ใช้พิกัดตายตัว
        # พอมีการ์ดสินค้าเพิ่มเข้ามา ทุกอย่างเลื่อนลง **205 จุด** พิกัดเลยพลาด
        # ทั้งสองขั้น — เกาะป้ายแล้วเลื่อนตามได้เอง ไม่ต้องเทรนใหม่ทุกครั้ง
        # ที่หน้าตาแอปขยับ
        if step.find.startswith("แถวขวา:"):
            label = step.find.split(":", 1)[1]
            found = find_row_toggle(context, label, width)
            if found:
                x, y, on = found
                return (x, y), (f"สวิตช์ของแถว “{label}” "
                                f"(ตอนนี้{'เปิด' if on else 'ปิด'}อยู่)")
        else:
            point = find_target(context.dump(), step.find)
            if point:
                return point, f"หาเจอจากป้าย “{step.find}”"
    trained = context.store.point_for(context.target, step.id, width, height)
    if trained:
        return trained, "พิกัดที่เทรนไว้"
    return None, ""


def _put_text(context: RunContext, step: Step, text: str) -> str:
    """ใส่ข้อความลงช่องที่โฟกัสอยู่ — **ลิงก์ใช้คัดลอก-วาง** ที่เหลือพิมพ์ตามเดิม

    **ผู้ใช้สั่งไว้ 25 ส.ค. 2026** — "ให้ปรับเป็นการ copy link จากรายละเอียดมาใส่
    โดย copy paste ได้เลย"

    ทำไมลิงก์ต้องต่างจากข้อความอื่น: ช่อง URL ของ Facebook เป็นช่องที่มีตัวเติมคำ
    ให้ระหว่างพิมพ์ การส่งทีละตัวอักษรจึงมีโอกาสโดนแอปเติม/ตัด/แก้ระหว่างทาง และ
    ลิงก์ที่ผิดแม้ตัวเดียวก็พาไปหน้าอื่นทั้งดุ้น ส่วนการวางคือของทั้งก้อนลงไปครั้งเดียว
    ไม่มีจังหวะให้แอปแทรก — เป็นท่าเดียวกับที่คนทำ (กดค้าง → วาง)

    ลิงก์ที่วางคือ `context.link` = `affiliate_url` ของงานนั้น ซึ่งคือลิงก์ที่ผู้ใช้
    ส่งเข้ามาเอง **ไม่ใช่ลิงก์ที่ระบบแปลงขึ้น** (ลิงก์ที่แปลงเองไม่มีรหัสผู้แนะนำ
    โพสต์ไปก็ไม่ได้ค่าคอม)

    วางไม่ได้ก็ถอยไปพิมพ์ **แต่ต้องขึ้น log ว่าถอย** ไม่ใช่เงียบ เพราะถ้าวันหนึ่ง
    คลิปบอร์ดใช้ไม่ได้ถาวร เราต้องรู้ตั้งแต่ครั้งแรก ไม่ใช่มารู้ตอนลิงก์เพี้ยน
    (ขั้นนี้ยังมีด่านตรวจ `text_appears` เกาะโดเมน Shopee ปิดท้ายอยู่แล้ว
    ไม่ว่าจะมาทางไหน ถ้าลิงก์ไม่ขึ้นบนจอจริงก็ไม่ผ่านอยู่ดี)
    """
    if step.kind == "paste_link" and context.set_clipboard:
        try:
            context.set_clipboard(text, True)
            return f"คัดลอก-วางลิงก์ {len(text)} ตัวอักษร"
        except Exception as error:      # noqa: BLE001 — ทางไหนล้มก็ต้องมีทางถอย
            context.log(f"  วางผ่านคลิปบอร์ดไม่ได้ ({error}) — ถอยไปพิมพ์ทีละตัวแทน")
    context.type_text(text)
    return f"พิมพ์ {len(text)} ตัวอักษร"


def run_step(context: RunContext, step: Step) -> str:
    """ทำหนึ่งขั้นแล้ว **ตรวจผล** คืนข้อความสรุป"""
    width, height = context.screen
    xml, before = context.read()
    typed = ""

    # โฆษณาเด้งมาบังก่อนขั้นนี้จะเริ่ม → ปิดก่อน แล้วอ่านจอใหม่
    # ใช้ผัง xml ที่เพิ่งอ่านมา ไม่ยิง adb เพิ่ม
    ad_notes = dismiss_ads(context, xml)
    if ad_notes:
        context.ads_closed.extend(ad_notes)
        _, before = context.read()      # ลายเซ็น "ก่อนทำ" ต้องเป็นจอหลังปิดโฆษณา

    if step.kind == "open_app":
        package = step.value or SHOPEE_PACKAGE
        context.run_adb(
            "shell", "monkey", "-p", package,
            "-c", "android.intent.category.LAUNCHER", "1",
        )
        summary = f"เปิดแอป {package}"

    elif step.kind == "wait":
        seconds = float(step.value or step.settle or 1)
        time.sleep(max(0.0, min(60.0, seconds)))
        summary = f"รอ {seconds:g} วินาที"

    elif step.kind == "popup":
        xml = context.dump()
        summary = "ไม่มีป็อปอัป ข้ามไป"
        for pattern in POPUP_DISMISS_PATTERNS:
            point = find_node(xml, pattern)
            if point:
                context.tap_at(*point)
                summary = f"ปิดป็อปอัปด้วยปุ่มที่ตรงกับ {pattern}"
                break
        else:
            trained = context.store.point_for(context.target, step.id, width, height)
            if trained:
                context.tap_at(*trained)
                summary = "ไม่เจอปุ่มตามข้อความ ใช้พิกัดที่เทรนไว้แทน"

    elif step.kind == "key":
        # ปุ่มระบบ (BACK / ENTER / HOME) — ไม่มีพิกัด ไม่ต้องเทรน
        name = (step.value or "BACK").strip().upper()
        context.run_adb("shell", "input", "keyevent", name)
        summary = f"กดปุ่มระบบ {name}"

    elif step.kind == "swipe":
        # ปัดจากกลางจอเสมอ — ขอบซ้าย/ขวาเป็นพื้นที่ปัดกลับของระบบ ปัดตรงนั้นจะ
        # กลายเป็นย้อนหน้าแทนการเลื่อนเนื้อหา (เจอมาแล้วในแอปที่ใช้ท่าทางเต็มจอ)
        direction = (step.value or "down").strip().lower()
        middle = width // 2
        far, near = int(height * 0.72), int(height * 0.30)
        start, end = (far, near) if direction in ("down", "ลง") else (near, far)
        context.run_adb(
            "shell", "input", "swipe",
            str(middle), str(start), str(middle), str(end), "400",
        )
        summary = f"ปัดจอ{'ลง' if direction in ('down', 'ลง') else 'ขึ้น'}"

    elif step.kind == "type_hashtag":
        summary = run_hashtag_step(context, step)

    elif step.kind == "type_tags":
        summary = run_tags_step(context, step)

    elif step.kind in {"type_text", "paste_link"}:
        typed = context.link if step.kind == "paste_link" else (
            step.value or context.caption
        )
        if not typed:
            if step.optional:
                return "ไม่มีข้อความให้พิมพ์ — ข้ามไป"
            raise StepError("ไม่มีข้อความให้พิมพ์")
        point, _ = locate(context, step, width, height)
        if point:                       # รู้ตำแหน่งช่องก็แตะให้โฟกัสก่อน
            context.tap_at(*point)
            time.sleep(0.6)
        summary = _put_text(context, step, typed)

    else:                               # tap
        point, how = locate(context, step, width, height)
        if point is None:
            if step.optional:
                return "หาปุ่มไม่เจอและเป็นขั้นที่ข้ามได้ — ข้ามไป"
            if step.find:
                raise StepError(
                    f"หาปุ่ม \"{step.find}\" บนจอไม่เจอ และยังไม่ได้เทรนพิกัดสำรองของ"
                    f" \"{step.name}\""
                )
            raise StepError(f"ยังไม่ได้เทรนตำแหน่งของขั้น \"{step.name}\"")
        hit = context.tap_at(*point)
        # บอกจุดที่ **แตะจริง** ไม่ใช่จุดที่ตั้งใจ ไม่งั้นตอนไล่บั๊กจะเทียบกับ
        # หน้าจอไม่ตรง แล้วหลงคิดว่าพิกัดที่เทรนไว้เพี้ยน
        drift = "" if hit == tuple(point) else f" · เยื้องจาก {point[0]}, {point[1]}"
        summary = f"แตะที่ {hit[0]}, {hit[1]} ({how}){drift}"

    context.pause(step.settle)
    proof = verify_step(context, step, before, typed=typed)
    head = f"ปิดโฆษณา {len(ad_notes)} ชั้นก่อน · " if ad_notes else ""
    return f"{head}{summary} · ตรวจแล้ว: {proof}"


def run_flow(
    context: RunContext, start_at: int = 1, stop_after: int | None = None
) -> dict:
    """เดินผังทั้งชุด — หยุดทันทีที่ขั้นบังคับทำไม่สำเร็จ

    ไม่เดินต่อเมื่อขั้นบังคับล้ม เพราะขั้นถัดไปอ้างอิงหน้าจอที่ควรจะเปลี่ยนไปแล้ว
    ถ้าดันทุรังต่อคือการแตะมั่วบนหน้าจอที่ไม่รู้ว่าเป็นอะไร ซึ่งอาจไปกดโพสต์จริง
    """
    steps = context.store.sequence(context.target)

    # ---- เตรียมของก่อนแตะจอขั้นแรก (ผู้ใช้สั่ง 26 ส.ค. 2026) ----------------
    #
    # ลำดับสำคัญ: **ปลุกจอก่อน แล้วค่อยส่งคลิป** เพราะการส่งคลิปสั่งให้ระบบ
    # แกลเลอรีสแกนไฟล์ใหม่ ซึ่งทำตอนจอดับก็ได้ แต่ถ้าปลุกทีหลังจอจะสว่างขึ้นมา
    # ตอนที่ขั้นแรกกำลังจะกดพอดี แล้วภาพยังไม่ทันนิ่ง
    #
    # **ล้มตรงนี้ต้องหยุดทันที ห้ามเดินผังต่อ** — เดินต่อคือการกดจนถึงปุ่มโพสต์
    # โดยที่คลิปในเครื่องเป็นของสินค้าอื่น ซึ่งโพสต์ขึ้นแล้วถอนไม่ได้
    ready: list[dict] = []
    for job, label in ((context.wake_screen, "ปลุกจอ"),
                       (context.send_clip, "ส่งคลิปเข้าเครื่อง")):
        if job is None:
            continue
        try:
            note = job()
        except Exception as error:                       # noqa: BLE001
            why = f"{label}ไม่สำเร็จ: {type(error).__name__}: {error}"
            context.log(f"✕ {why}")
            ready.append({"step": "prepare", "name": label, "ok": False, "message": why})
            return {"target": context.target, "done": 0, "total": len(steps),
                    "results": ready, "tags": [], "ads_closed": [], "ok": False}
        if note:
            context.log(f"✓ {note}")
            ready.append({"step": "prepare", "name": label, "ok": True, "message": note})

    # แอปที่ผังนี้ต้องอยู่ตลอดทาง — เอาจากขั้น open_app ของผังเอง ไม่ฮาร์ดโค้ด
    # ผู้ใช้เปลี่ยนแอปปลายทางในผังได้ ตัวตรวจจะตามไปเอง
    if not context.app_package:
        for step in steps:
            if step.kind == "open_app" and step.value:
                context.app_package = step.value.strip()
                break

    results: list[dict] = list(ready)
    done = 0
    for number, step in enumerate(steps, start=1):
        if number < start_at:
            continue
        if context.stop():
            results.append({"step": step.id, "ok": False, "message": "ถูกสั่งหยุด"})
            break
        try:
            message = run_step(context, step)
            ok = True
        except StepError as error:
            message, ok = str(error), False
        except Exception as error:                       # noqa: BLE001
            message, ok = f"{type(error).__name__}: {error}", False

        if not ok:
            # ล้มเพราะ "หาปุ่มไม่เจอ" มักแปลว่ามีอะไรบังอยู่ ไม่ใช่ปุ่มหายจริง
            # ตรงนี้ยอมกดปุ่มปิดโดยไม่ต้องเจอคำว่าโฆษณาก่อน (force) เพราะรู้แล้วว่า
            # หน้าจอไม่ใช่ที่ที่ควรเป็น — แต่ยังกดได้แค่ปุ่มปิดเท่านั้น
            #
            # **ลองซ้ำครั้งเดียว** ไม่วนซ้ำเรื่อยๆ เพราะถ้าปิดแล้วยังล้มอีก แปลว่า
            # สาเหตุไม่ใช่โฆษณา การวนต่อคือการกดมั่วบนหน้าจอที่ไม่รู้จัก
            closed = dismiss_ads(context, force=True)
            if closed:
                context.ads_closed.extend(closed)
                context.log(f"   ปิดของที่บังอยู่แล้วลองขั้นนี้ใหม่: {step.name}")
                try:
                    message = run_step(context, step)
                    ok = True
                    message = f"ปิดโฆษณาแล้วทำซ้ำสำเร็จ · {message}"
                except StepError as error:
                    message = f"ปิดโฆษณาแล้วยังไม่ผ่าน: {error}"
                except Exception as error:               # noqa: BLE001
                    message = (f"ปิดโฆษณาแล้วยังไม่ผ่าน: "
                               f"{type(error).__name__}: {error}")

        results.append({"step": step.id, "name": step.name, "ok": ok, "message": message})
        context.report(step, ok, message)
        context.log(f"{number}. {step.name} — {'✓' if ok else '✗'} {message}")

        if not ok and not step.optional:
            break
        done += 1
        if stop_after is not None and number >= stop_after:
            break

    return {
        "target": context.target,
        "done": done,
        "total": len(steps),
        "results": results,
        "tags": context.tag_results,
        # ปิดโฆษณาไปกี่ครั้ง — รายงานออกไปเสมอ ไม่ปิดเงียบๆ ถ้าตัวเลขนี้พุ่งขึ้น
        # แปลว่าแอปเปลี่ยนพฤติกรรม ควรรู้ก่อนที่ผังจะเริ่มพังเอง
        "ads_closed": list(context.ads_closed),
        "ok": all(item["ok"] for item in results) if results else False,
    }
