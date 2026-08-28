"""คิวงานเจนคลิป — วางหลายลิงก์แล้วทำทีละงาน พร้อมจุดหยุดรออนุมัติ

ทำไมต้องมีคิว: เบราว์เซอร์มีโปรไฟล์เดียว (Chrome เปิดโปรไฟล์เดียวกันซ้อนกันไม่ได้)
ถ้าผู้ใช้วางลิงก์รวดเดียว 5 อัน แล้วแต่ละอันเปิดเบราว์เซอร์ของตัวเอง งานหลังจะไล่
หน้าต่างของงานหน้าออกกลางคัน — ทุกงานพังพร้อมกัน

ทำไมสถานะไม่ใช่เส้นตรง: ทุกชิ้นต้องผ่านการอนุมัติจากผู้ใช้ก่อนไปต่อ ตัวรันจึงไม่ได้
ไล่ทำจนจบรวดเดียว แต่ทำถึงจุดที่ต้องให้คนตัดสินแล้ว **หยุดรอ** งานที่หยุดรอไม่กิน
คิว งานถัดไปเดินต่อได้เลย

    queued ─► collecting ─► image_review ─► ready_storyboard ─► making_storyboard
                               (ตรวจรูป)      (รูปผ่านแล้ว)              │
                                                                         ▼
                                                              storyboard_review
                                                               (สตอรีบอร์ด+บทพูด)
                                                                    │       │
                                                       (สั่งแก้) revising    │
                                                                    └───────┤
                                                                            ▼
                                              ready_flow ─► generating ─► video_review
                                                                            │
                                                                            ▼
                                                                           done

"ทำได้เลย" มี 4 สถานะ: queued · ready_storyboard · revising · ready_flow
นอกนั้นคือรอคนกด ตัวรันจะข้ามไป

**ขั้น image_review มีไว้ทำไม** ผู้ใช้ต้องแก้ชุดรูปได้ก่อนส่งเข้า GPT — เพิ่ม/ลบ/
เปลี่ยนรูป เพราะตัวคัดอัตโนมัติเลือกผิดได้ และรูปที่ส่งเข้าไปเป็นตัวกำหนดหน้าตา
ของทั้งคลิป แก้ทีหลังคือต้องทำใหม่ทั้งงาน
"""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Callable

STAGE_QUEUED = "queued"
STAGE_COLLECTING = "collecting"
STAGE_IMAGE_REVIEW = "image_review"          # รอผู้ใช้ตรวจ/แก้ชุดรูปก่อนส่งเข้า GPT
STAGE_READY_STORYBOARD = "ready_storyboard"  # รูปผ่านแล้ว รอทำสตอรีบอร์ด
STAGE_MAKING = "making_storyboard"           # กำลังคุยกับ GPT อยู่
STAGE_STORYBOARD_REVIEW = "storyboard_review"
STAGE_SCRIPT_REVIEW = "script_review"
STAGE_REVISING = "revising"
STAGE_READY_FLOW = "ready_flow"
STAGE_GENERATING = "generating"
STAGE_VIDEO_REVIEW = "video_review"
# สองสถานะล่างนี้ใช้เฉพาะสาย TikTok repost (kind="tiktok") — คลิปผ่านแล้วแต่ยัง
# ต้องยืนยันของอีก 4 อย่างก่อนโพสต์ (Clip · Product ID · #hashtag · คำพูดบนตะกร้า)
# สาย Shopee ไม่ผ่านสองสถานะนี้ กด ✅ ที่คลิปแล้วจบที่ done เหมือนเดิม
STAGE_POST_REVIEW = "tiktok_post_review"
STAGE_POSTING = "tiktok_posting"
STAGE_DONE = "done"
STAGE_FAILED = "failed"
STAGE_CANCELLED = "cancelled"

# ถังขยะของคิว — ลบแล้วยังกู้ได้ภายในกี่วัน และเก็บได้มากสุดกี่ใบ
# ตั้งไว้ 7 วันเท่าถังขยะของฟาร์มโปรไฟล์บอท จะได้จำง่ายว่ากติกาเดียวกันทั้งระบบ
TRASH_DAYS = 7
TRASH_LIMIT = 200

# สถานะที่ตัวรันหยิบไปทำได้ทันที — ที่เหลือคือรอผู้ใช้กด
ACTIONABLE = {
    STAGE_QUEUED, STAGE_READY_STORYBOARD, STAGE_REVISING, STAGE_READY_FLOW,
    STAGE_POSTING,
}

# ทำได้ทีละกี่งาน — **ผู้ใช้สั่ง 25 ส.ค. 2026 "ทำทีละ 8 คิว"**
#
# ทำไมต้องมีเพดาน (เหตุการณ์จริงวันนั้น)
#     ผู้ใช้ส่งลิงก์ 33 ใบพร้อมกันตอน 15:55 ระบบไล่ดึงรวดโดยไม่มีเพดาน
#     ดึงสำเร็จ 8 ใบใน 10 นาที 44 วินาที (ใบละ ~80 วินาที · โหลดรูป 158 ใบ)
#     แล้ว **ใบที่ 9 โดน Shopee บล็อก** หลังจากนั้นล้มรวดอีก 25 ใบติดกัน
#     ผลสุดท้าย: สำเร็จ 8 · ล้ม 25
#
# ทำไมเลข 8 ตรงกับที่วัดได้พอดี — 8 คือจำนวนที่ทำได้จริงก่อนโดนบล็อก
# ไม่ใช่เลขที่คิดขึ้นเอง
#
# **นับอะไร** — งานที่เริ่มไปแล้วและยังไม่จบ (ทุกสถานะใน OPEN_STAGES ยกเว้น
# `queued` ซึ่งคือลิงก์ที่วางไว้เฉยๆ ยังไม่ได้แตะ) พองานใดจบ (done/failed/
# cancelled) ที่ว่างจะคืนมาแล้วตัวรันหยิบใบถัดไปเข้ามาเองจนครบ 8
#
# **ไม่กั้นงานที่เริ่มไปแล้ว** — เพดานนี้กั้นเฉพาะการ "เริ่มใบใหม่" เท่านั้น
# งานที่อยู่ในมือแล้ว (สั่งแก้ · ทำสตอรีบอร์ด · เจนคลิป) เดินต่อได้เสมอ
# ไม่งั้นงานที่ผู้ใช้นั่งรออยู่หน้าจอจะค้างเพราะติดเพดานของงานอื่น
BATCH_LIMIT = 8

# สถานะที่แปลว่า **เครื่องกำลังลงมือทำอยู่จริง** (ไม่ใช่จอดรอคนกด)
#
# แยกออกมาเพราะเพดานข้างบนต้องนับแค่พวกนี้ — งานที่รอคนกดอนุมัติไม่ได้ใช้
# เบราว์เซอร์ ไม่ได้ยิงหา Shopee ไม่ได้เผาเครดิต Flow มันแค่จอดรอเฉยๆ
# การนับมันเข้าไปด้วยทำให้คิวล็อกตัวเองเมื่อเจ้าของไม่ว่างมากดอนุมัติ
MACHINE_STAGES = {
    STAGE_COLLECTING,      # กำลังดึงหน้า Shopee
    STAGE_MAKING,          # กำลังคุยกับ GPT ทำสตอรีบอร์ด
    STAGE_REVISING,        # กำลังสั่งแก้กับ GPT
    STAGE_GENERATING,      # กำลังเผาเครดิตใน Google Flow
    STAGE_POSTING,         # กำลังแตะจอมือถือโพสต์
}

# เจอปลายทางบล็อก (Shopee ขึ้นหน้า "Please Try Again Later") ให้ **พักทั้งคิว**
# ไม่ใช่ไล่ยิงใบถัดไปจนหมด
#
# **เหตุการณ์จริง 2 รอบใน 2 ชั่วโมง (25 ส.ค. 2026)**
#   16:07  โดนบล็อกใบที่ 9 แล้วไล่ยิงต่ออีก 25 ใบ ล้มหมด · สร้างสินค้าผี 14 ชิ้น
#          และ **เขียนทับสินค้าจริงที่ทำไว้แล้ว 1 ชิ้น** (ชื่อ/จุดเด่น/คำบรรยายหาย)
#   17:42  ผู้ใช้ส่งลิงก์ใหม่ 33 ใบ โดนบล็อกทันที ล้มรวด 4 ใบใน 40 วินาที
#
# ยิ่งยิงตอนโดนบล็อก ยิ่งโดนนาน — และทุกใบที่ยิงคือการสร้างขยะเพิ่ม
# 20 นาทีมาจาก: รอบแรกบล็อกยาวเกิน 10 นาทีต่อเนื่อง แต่มีใบหนึ่งหลุดผ่านได้
# ตอนนาทีที่ 7 แปลว่าเป็นการจำกัดแบบมีช่วงเวลา ไม่ใช่แบนถาวร
BLOCK_HOLD_SECONDS = 20 * 60

# อาการที่แปลว่า "ปลายทางบล็อก" ไม่ใช่ "โค้ดเราพัง"
#
# `Execution context was destroyed` = หน้าเว็บถูกเด้งไปที่อื่นกลางคัน ซึ่งเป็นสิ่งที่
# Shopee ทำตอนกันเรา — วัดจริง 25 ส.ค. ล้มด้วยข้อความนี้ 4 ใบติดใน 40 วินาที
BLOCK_ERROR_HINTS = (
    "execution context was destroyed",
    "please try again later",
    "verify to continue",
    "too many request",
    "ไม่ให้ข้อมูลสินค้า",
    "net::err_",
)


def _looks_blocked_error(message: str) -> bool:
    low = str(message or "").lower()
    return any(hint in low for hint in BLOCK_ERROR_HINTS)


# ---- ยังไม่ได้ล็อกอิน = หยุดคิวทันที (เจ้าของสั่ง 28 ส.ค. 2569) -----------
#
# *"สร้างตัวป้องกัน ขึ้นว่ายังไม่ได้ log in ให้หยุดเลยทันที"*
#
# **เหตุการณ์ที่ทำให้ต้องมี** 28 ส.ค. 13:17–13:19 เจ้าของอนุมัติงาน 54 ใบ
# ChatGPT ไม่ได้ล็อกอินอยู่ ระบบจึงไล่ยิงทีละใบแล้วล้มทุกใบ **หมดทั้งคิว
# ใน 2 นาที 26 วินาที** ด้วยข้อความเดียวกันเป๊ะ 54 ครั้ง
#
# ต่างจากงานล้มธรรมดาตรงที่ **มันล้มแน่นอนทุกใบ** ไม่ใช่ใบนี้พังใบหน้าอาจผ่าน
# การไล่ต่อจึงไม่มีทางได้อะไรกลับมา มีแต่เผางานทิ้งให้ต้องมากู้ทีหลัง
# (เหตุผลเดียวกับที่คิวหยุดเมื่อ Shopee บล็อก — ปลายทางไม่พร้อมเหมือนกัน)
#
# **ต้องรอคน** ล็อกอินแทนกันไม่ได้ จึงพักแบบไม่มีกำหนดเวลา ไม่ใช่พักแล้วลองเอง
LOGIN_ERROR_HINTS = (
    "needslogin",
    "ยังไม่ได้ล็อกอิน",
    "ยังไม่ได้ล็อกอิน",
    "not logged in",
    "please log in",
    "sign in to continue",
)


def _looks_login_error(message: str) -> bool:
    """ข้อความนี้แปลว่ายังไม่ได้ล็อกอินปลายทางไหม — ล้มแน่นอนทุกใบ ต้องหยุด"""
    low = str(message or "").lower()
    return any(hint in low for hint in LOGIN_ERROR_HINTS)


# หน้าที่ Shopee เด้งมาแล้ว **คนช่วยอะไรไม่ได้** — มีแต่ปุ่ม "ลองใหม่" กับข้อความ
# ว่าให้รอสักครู่ ไม่มีจิ๊กซอว์ ไม่มีอะไรให้กด
#
# เหตุการณ์ที่ทำให้ต้องแยก (27 ส.ค. 2026): 01:22:52 ระบบเขียนว่า "ติด CAPTCHA —
# รอยืนยันก่อนทำต่อ (ค้าง 34 ใบ)" ผู้ใช้จึงรอว่าต้องไปเลื่อนจิ๊กซอว์ที่ไหนสักแห่ง
# **แต่ภาพหน้าจอที่เก็บไว้ตอน 01:22:49 พิสูจน์ว่าไม่มีจิ๊กซอว์เลย** หน้านั้นเขียนว่า
# "Please Try Again Later · Verification can't be completed. Please try again
# after a few minutes." มีแค่ปุ่ม Try Again — **ไม่มีอะไรให้คนทำ**
#
# ผลคือคิวนอนรอคนที่ช่วยอะไรไม่ได้อยู่ **6 ชั่วโมง 48 นาที** (01:22 → 08:11)
# ทั้งที่การพัก 20 นาทีแล้วลองเองก็พอ
#
# เรียกทุกอย่างว่า "CAPTCHA" เหมือนกันหมดคือรากของปัญหา — สองหน้านี้แก้คนละทาง
WAIT_ONLY_HINTS = (
    "please try again later",
    "try again later",
    "too many request",
    "execution context was destroyed",
    "net::err_",
)

# หน้าที่ **ต้องมีคนเลื่อนจิ๊กซอว์จริงๆ** ถึงจะผ่าน — อันนี้รอคนถูกแล้ว
NEEDS_HUMAN_HINTS = (
    "verify to continue",
    "captcha",
    "ยืนยันตัวตน",
    "จิ๊กซอว์",
)


def block_kind(message: str) -> str:
    """หน้าบล็อกแบบนี้ต้องรอคน หรือรอเวลาเฉยๆ

    คืน `"human"` = ต้องให้คนไปเลื่อนจิ๊กซอว์แล้วกดยืนยัน
    คืน `"wait"`  = พักแล้วลองเองได้ **ห้ามไปรอคน** เพราะไม่มีอะไรให้เขาทำ

    **ตรวจแบบ "ต้องมีคนทำ" ก่อนเสมอ** ข้อความหนึ่งอาจเข้าเงื่อนไขทั้งสองชุด
    (เช่นหน้าจิ๊กซอว์ที่มีคำว่า try again อยู่ด้วย) กรณีนั้นต้องเลือกทางที่
    ปลอดภัยกว่า = รอคน เพราะการเดาผิดทางนี้แค่ช้า ส่วนเดาผิดอีกทางคือยิงซ้ำ
    ใส่ด่านที่ยังไม่ผ่านจนโดนบล็อกหนักกว่าเดิม
    """
    low = str(message or "").lower()
    if any(hint in low for hint in NEEDS_HUMAN_HINTS):
        return "human"
    if any(hint in low for hint in WAIT_ONLY_HINTS):
        return "wait"
    return "human"          # ไม่รู้จัก = เลือกทางปลอดภัย

# ลำดับความสำคัญตอนหยิบงาน — **เลขน้อยได้ทำก่อน** (ผู้ใช้สั่ง 22 ส.ค. 2026)
#
# หลักการเดียว: **งานที่มีคนนั่งรออยู่หน้าจอ ต้องมาก่อนงานที่ไม่มีใครรอ**
#
# ปัญหาที่แก้: เดิมหยิบงานแรกในลิสต์ที่ทำได้ = เรียงตามเวลาที่เข้าคิวล้วนๆ
# พอผู้ใช้กด "แก้ไขบทพูด" แล้วพิมพ์คำสั่งแก้ งานนั้นกลายเป็น revising ซึ่งต้อง
# ต่อแถวเท่ากับงานใหม่ที่เพิ่งวางลิงก์มา — คนที่นั่งรอดูผลการแก้จึงต้องรอให้
# งานอื่นที่ไม่มีใครรอทำจนจบก่อน (งานละ ~1 ชั่วโมง) การแก้ทีละรอบเลยขาดตอน
#
# ตัวเลขเดียวกัน = ใครอยู่ก่อนในลิสต์ได้ก่อน (ลำดับเข้าคิวเดิม ไม่สลับมั่ว)
STAGE_PRIORITY = {
    STAGE_REVISING: 0,          # เพิ่งสั่งแก้ คนรอดูผลอยู่ตอนนี้
    STAGE_READY_STORYBOARD: 1,  # เพิ่งกดผ่านชุดรูป — คนยังอยู่ในแชท
    STAGE_READY_FLOW: 1,        # เพิ่งกดผ่านสตอรีบอร์ด — คนยังอยู่ในแชท
    STAGE_POSTING: 2,           # สั่งโพสต์แล้ว รอเครื่องว่าง
    STAGE_QUEUED: 3,            # ลิงก์ใหม่ที่เพิ่งวางไว้ ยังไม่มีใครรอผล
}
# สถานะที่ถือว่างานยังไม่จบ ใช้ตอนนับคิวและตอนหางานล่าสุดของแชท
OPEN_STAGES = {
    STAGE_QUEUED, STAGE_COLLECTING, STAGE_IMAGE_REVIEW, STAGE_READY_STORYBOARD,
    STAGE_MAKING,
    STAGE_STORYBOARD_REVIEW, STAGE_SCRIPT_REVIEW, STAGE_REVISING,
    STAGE_READY_FLOW, STAGE_GENERATING, STAGE_VIDEO_REVIEW,
    STAGE_POST_REVIEW, STAGE_POSTING,
}

STAGE_LABEL = {
    STAGE_QUEUED: "รอคิว",
    STAGE_COLLECTING: "กำลังดึงสินค้า",
    STAGE_IMAGE_REVIEW: "รอตรวจชุดรูป",
    STAGE_READY_STORYBOARD: "รอทำสตอรีบอร์ด",
    STAGE_MAKING: "กำลังทำสตอรีบอร์ด + บทพูด",
    # สตอรีบอร์ดกับบทพูดส่งไปพร้อมกันและกดอนุมัติแยกกัน จึงใช้สถานะเดียวคุมทั้งคู่
    # แล้วดูที่ธง storyboard_ok / script_ok ว่าผ่านครบหรือยัง
    STAGE_STORYBOARD_REVIEW: "รออนุมัติสตอรีบอร์ด + บทพูด",
    # เหลือไว้ให้งานรุ่นก่อนที่ยังค้างอยู่ในสถานะนี้เดินต่อได้
    STAGE_SCRIPT_REVIEW: "รออนุมัติบทพูด",
    STAGE_REVISING: "กำลังแก้ตามคำสั่ง",
    STAGE_READY_FLOW: "รอเจนใน Google Flow",
    STAGE_GENERATING: "กำลังเจนคลิป",
    STAGE_VIDEO_REVIEW: "รออนุมัติคลิป",
    STAGE_POST_REVIEW: "รอยืนยันก่อนโพสต์ TikTok",
    STAGE_POSTING: "กำลังโพสต์ขึ้น TikTok",
    STAGE_DONE: "เสร็จแล้ว",
    STAGE_FAILED: "ล้มเหลว",
    STAGE_CANCELLED: "ยกเลิก",
}


class ClipQueueError(RuntimeError):
    """คิวงานเจนคลิปมีปัญหา"""


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class ClipQueue:
    """เก็บคิวลงไฟล์ — รีสตาร์ตเซิร์ฟเวอร์แล้วงานที่ค้างไม่หาย

    งานที่ "กำลังทำอยู่" ตอนเซิร์ฟเวอร์ดับจะค้างสถานะกลางทาง (collecting/generating)
    จึงมี `recover()` ดึงกลับมาเป็นสถานะที่ทำใหม่ได้ตอนเปิดเซิร์ฟเวอร์
    """

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.lock = threading.RLock()
        self.jobs: list[dict] = []
        self._held = False           # คิวถูกพักเพราะติด CAPTCHA/โดนบล็อกอยู่ไหม
        self.hold_why: str = ""
        self.hold_at: str = ""
        # เวลาที่จะปลดพักเอง (0 = รอคนยืนยัน ไม่มีวันหมดอายุ)
        self.hold_until: float = 0.0
        self._load()

    def hold(self, why: str, seconds: float = 0.0) -> None:
        """พักการเริ่มงานใหม่ — รอคน หรือรอเวลา แล้วแต่ชนิดของหน้าที่โดนบล็อก

        ผู้ใช้สั่งไว้ 25 ส.ค. 2026: *"ถ้าติด capcha ให้หยุดและส่งกลับมาบอกผมทาง
        telegram ว่าติด capcha ผมจะแก้ให้ก่อน แล้วคอนเฟิร์มกลับไปค่อยรันต่อ"*

        **`seconds=0` = รอคนยืนยัน ไม่มีวันหมดอายุ** (พฤติกรรมเดิม) ใช้กับหน้า
        จิ๊กซอว์จริงที่ต้องมีคนเลื่อน — ปลดเองตามเวลาแล้วยิงต่อทั้งที่ด่านยังอยู่
        = กลับไปเป็นแบบเดิมที่ไล่ยิงจนล้มหมด

        **`seconds>0` = พักแล้วเดินต่อเอง** (เพิ่ม 27 ส.ค. 2026) ใช้กับหน้า
        "Please Try Again Later" ที่ **ไม่มีอะไรให้คนทำ** — รอคนในกรณีนั้นคือ
        การจอดคิวไว้เฉยๆ ซึ่งเกิดจริงแล้ว 6 ชั่วโมง 48 นาที กับลิงก์ 34 ใบ

        งานที่เริ่มไปแล้วเดินต่อได้ตามปกติทั้งสองแบบ พักเฉพาะการ **เริ่มใบใหม่**
        """
        with self.lock:
            self._held = True
            self.hold_why = why
            self.hold_at = _now()
            self.hold_until = (time.time() + seconds) if seconds > 0 else 0.0

    def held(self) -> bool:
        """คิวยังถูกพักอยู่ไหม — **พักแบบมีกำหนดจะปลดตัวเองตรงนี้**

        ปลดตอนถูกถาม ไม่ใช่ตั้งเวลาแยก เพราะตัวรันถามค่านี้ทุกครั้งก่อนหยิบงาน
        อยู่แล้ว การมีนาฬิกาปลุกอีกตัวมีแต่จะเพิ่มของที่ต้องดูแลโดยไม่ได้อะไรเพิ่ม
        """
        with self.lock:
            if self._held and self.hold_until and time.time() >= self.hold_until:
                self._held = False
                self.hold_why = ""
                self.hold_at = ""
                self.hold_until = 0.0
            return self._held

    def hold_left(self) -> int:
        """พักแบบมีกำหนดเหลืออีกกี่วินาที (0 = ไม่ได้พัก หรือพักแบบรอคน)"""
        with self.lock:
            if not self._held or not self.hold_until:
                return 0
            return max(0, int(self.hold_until - time.time()))

    def release_hold(self) -> None:
        """ผู้ใช้ยืนยันว่าแก้แล้ว — ทำงานต่อได้"""
        with self.lock:
            self._held = False
            self.hold_why = ""
            self.hold_at = ""
            self.hold_until = 0.0

    # ------------------------------------------------------------ ไฟล์

    def _load(self) -> None:
        try:
            self.jobs = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.jobs = []

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".json.tmp")
        temp.write_text(
            json.dumps(self.jobs, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        temp.replace(self.path)

    def recover(self) -> int:
        """งานที่ค้างกลางทางตอนเซิร์ฟเวอร์ดับ → ดึงกลับมาให้ทำใหม่ได้

        ไม่ทำแบบนี้งานจะค้าง "กำลังดึงสินค้า" ตลอดกาล ผู้ใช้รอเก้อโดยไม่มีอะไรฟ้อง
        """
        back = {
            STAGE_COLLECTING: STAGE_QUEUED,
            STAGE_MAKING: STAGE_READY_STORYBOARD,
            STAGE_GENERATING: STAGE_READY_FLOW,
            # ดับตอนกำลังโพสต์ = **ไม่รู้ว่าโพสต์ขึ้นไปแล้วหรือยัง** ห้ามยิงซ้ำเอง
            # เพราะโพสต์ TikTok ซ้ำแล้วเรียกคืนไม่ได้ ส่งกลับไปให้คนตัดสินแทน
            STAGE_POSTING: STAGE_POST_REVIEW,
        }
        notes = {
            STAGE_POSTING: (
                "เซิร์ฟเวอร์ดับระหว่างโพสต์ — เช็คใน TikTok ก่อนว่าขึ้นไปแล้วหรือยัง "
                "ค่อยกดโพสต์ซ้ำ"
            ),
        }
        moved = 0
        with self.lock:
            for job in self.jobs:
                if job.get("stage") in back:
                    was = job["stage"]
                    job["stage"] = back[was]
                    job["note"] = notes.get(
                        was, "เซิร์ฟเวอร์รีสตาร์ตระหว่างทำ — เอากลับเข้าคิวใหม่"
                    )
                    job["updated_at"] = _now()
                    moved += 1
            if moved:
                self._save()
        return moved

    # ------------------------------------------------------------ เขียน

    def add(self, link: str, chat_id: str) -> dict:
        with self.lock:
            job = {
                "id": f"{int(time.time() * 1000):x}{len(self.jobs):02x}",
                "link": link,
                "chat_id": str(chat_id),
                "stage": STAGE_QUEUED,
                "item_id": "",
                "name": "",
                "storyboard_ok": False,
                "script_ok": False,
                "pending_edit": None,
                "note": "",
                "error": "",
                "created_at": _now(),
                "updated_at": _now(),
            }
            self.jobs.append(job)
            self._save()
            return dict(job)

    def update(self, job_id: str, **fields) -> dict:
        """แก้ค่าในใบงาน — **ย้ายออกจากสถานะล้มเหลวแล้วต้องล้างข้อความล้มด้วย**

        เจ้าของเจอเอง 28 ส.ค. 2569: *"ทำไมหน้าเว็บยังขึ้นโชว์"* — หน้าเว็บขึ้น
        แถบแดง "ยังไม่ได้ล็อกอิน ChatGPT" บนใบงาน **55 ใบที่ทำสำเร็จไปแล้ว**
        เพราะตอนกู้งานกลับเข้าคิว เปลี่ยนแค่ `stage` แต่ `error` ยังค้างของเดิม
        แล้วไม่มีใครล้างให้ตลอดสายพาน

        นี่คือกับดักเดียวกับที่เจอทั้งวัน — **ป้ายบอกสถานะที่ไม่ตรงกับความจริง**
        คนอ่านแล้วนึกว่าพัง ทั้งที่งานเดินปกติ แล้วไปไล่หาสาเหตุที่ไม่มีอยู่จริง
        """
        with self.lock:
            for job in self.jobs:
                if job["id"] == job_id:
                    stage = fields.get("stage")
                    if (stage and stage != STAGE_FAILED
                            and "error" not in fields and job.get("error")):
                        fields = {**fields, "error": ""}
                    job.update(fields)
                    job["updated_at"] = _now()
                    self._save()
                    return dict(job)
        raise ClipQueueError(f"ไม่พบงาน {job_id}")

    def park(self, job_id: str, why: str = "") -> dict:
        """พักงานไว้ "รอแก้" — เครื่องจะไม่แตะจนกว่าจะเอากลับ (ผู้ใช้สั่ง 27 ส.ค. 2026)

        *"ให้สร้างอีกช่องนึงเป็นช่องรอแก้ สำหรับทุกขั้นตอน โดยมีปุ่มให้กดไปรอแก้
        ในใบงานด้วย"*

        **เก็บสถานะเดิมไว้ครบ ไม่เปลี่ยน `stage`** เพราะการพักคือ "หยุดไว้ตรงนี้"
        ไม่ใช่ "ถอยกลับ" — เอากลับเมื่อไรต้องกลับเข้าขั้นเดิมเป๊ะโดยไม่ต้องเดา
        ถ้าเปลี่ยน stage เป็นค่าพิเศษ จะต้องมีตารางแปลงกลับอีกชุด ซึ่งวันหนึ่งจะ
        ไม่ตรงกับสถานะที่เพิ่มใหม่ แล้วงานจะกลับผิดขั้นแบบเงียบๆ

        พักซ้ำได้ (แค่ทับเหตุผลใหม่) — ไม่ต้องให้ผู้เรียกไปเช็คก่อน
        """
        with self.lock:
            job = next((j for j in self.jobs if j["id"] == job_id), None)
            if not job:
                raise ClipQueueError(f"ไม่พบงาน {job_id}")
            job["parked"] = {
                "at": _now(),
                "from": job.get("stage") or "",
                "why": str(why or "").strip(),
            }
            job["updated_at"] = _now()
            self._save()
            return dict(job)

    def unpark(self, job_id: str) -> dict:
        """เอางานที่พักไว้กลับเข้าขั้นเดิม"""
        with self.lock:
            job = next((j for j in self.jobs if j["id"] == job_id), None)
            if not job:
                raise ClipQueueError(f"ไม่พบงาน {job_id}")
            if not job.get("parked"):
                raise ClipQueueError("งานนี้ไม่ได้พักไว้อยู่แล้ว")
            job.pop("parked", None)
            job["updated_at"] = _now()
            self._save()
            return dict(job)

    def parked(self) -> list[dict]:
        """งานที่พักไว้รอแก้ทั้งหมด — เรียงตามเวลาที่พัก ใบที่ค้างนานสุดขึ้นก่อน"""
        with self.lock:
            rows = [dict(j) for j in self.jobs if j.get("parked")]
        rows.sort(key=lambda j: (j.get("parked") or {}).get("at") or "")
        return rows

    def claim_next(self) -> dict | None:
        """หยิบงานที่ทำได้ทันทีมาหนึ่งงาน แล้วตั้งสถานะ "กำลังทำ" ทันทีในล็อกเดียว

        ต้องเปลี่ยนสถานะในล็อกเดียวกับตอนหยิบ ไม่งั้นถ้ามีตัวรันสองตัว (หรือกดสั่ง
        ซ้ำเร็วๆ) จะหยิบงานเดียวกันไปทำพร้อมกัน แล้วแย่งเบราว์เซอร์กันเอง
        """
        moving = {
            STAGE_QUEUED: STAGE_COLLECTING,
            STAGE_READY_STORYBOARD: STAGE_MAKING,
            STAGE_REVISING: STAGE_REVISING,
            STAGE_READY_FLOW: STAGE_GENERATING,
            # ทุกสถานะใน ACTIONABLE ต้องมีคู่ในตารางนี้ ไม่งั้น KeyError ตอนหยิบงาน
            STAGE_POSTING: STAGE_POSTING,
        }
        with self.lock:
            # นับ **เฉพาะงานที่เครื่องกำลังลงมือทำอยู่จริง** ไม่นับงานที่จอดรอคน
            # (ผู้ใช้สั่ง 26 ส.ค. 2026: "ตอนดึงข้อมูลจากลิ้งไม่ต้องมีลิมิต")
            #
            # **ของเดิมนับงานที่รอคนกดด้วย ซึ่งกลายเป็นการล็อกคิวตัวเอง**
            # วัดของจริง 27 ส.ค. 00:0x — ช่องเต็มไป 6 จาก 8 โดยเป็น
            #     video_review 4 ใบ · storyboard_review 2 ใบ  ← จอดรอคนกดทั้งหมด
            #     collecting 0 ใบ                              ← ไม่มีใครดึง Shopee เลย
            # แปลว่าเพดานไม่ได้กัน Shopee อะไรเลย มันแค่ห้ามดึงลิงก์ใหม่
            # เพราะเจ้าของยังไม่ว่างมากดอนุมัติของเก่า — เสียเวลาเปล่าล้วนๆ
            #
            # **ทำไมปลอดภัย** `ClipRunner` เดินอยู่ตัวเดียวและทำทีละงานเท่านั้น
            # การดึง Shopee จึงเรียงทีละใบอยู่แล้วโดยธรรมชาติ (ใบละ ~80 วินาที)
            # เพดานนี้ไม่เคยลดความถี่ต่อคำขอเลยแม้แต่นิดเดียว
            #
            # **แล้วอะไรกันการโดนบล็อก** — `BLOCK_HOLD_SECONDS` (พักทั้งคิว 20 นาที
            # ทันทีที่เจอหน้าบล็อก) ซึ่งเพิ่มเข้ามาทีหลังและตรงจุดกว่า เพราะมันตอบสนอง
            # ต่อ**อาการจริง**ที่ปลายทางส่งกลับมา ไม่ใช่การเดาเพดานล่วงหน้า
            busy = sum(1 for j in self.jobs if j.get("stage") in MACHINE_STAGES)
            # โดนปลายทางบล็อกอยู่ = ห้ามเริ่มใบใหม่จนกว่าจะพ้นเวลาพัก
            #
            # **ต้องเรียก `self.held()` ไม่ใช่อ่าน `self._held` ตรงๆ** เพราะการพัก
            # แบบมีกำหนดเวลา (หน้า "Please Try Again Later") ปลดตัวเองในเมท็อดนั้น
            # อ่านตัวแปรตรงๆ = พักแล้วไม่มีวันปลด กลายเป็นค้างถาวรเงียบๆ
            # (ล็อกเป็น RLock อยู่แล้ว เรียกซ้อนในล็อกเดิมได้)
            full = busy >= BATCH_LIMIT or self.held()

            # เลือกงานที่ "มีคนรออยู่" ก่อนงานที่ไม่มีใครรอ (ดู STAGE_PRIORITY)
            # ตัวเลขเท่ากันให้ตัวที่อยู่ก่อนในลิสต์ชนะ — ลำดับเข้าคิวเดิมไม่สลับ
            best = None
            for index, job in enumerate(self.jobs):
                stage = job.get("stage")
                if stage not in ACTIONABLE:
                    continue
                # **พักไว้รอแก้ = เครื่องห้ามแตะ** (ผู้ใช้สั่ง 27 ส.ค. 2026)
                # ไม่งั้นกดพักแล้วอีกเดี๋ยวตัวรันก็หยิบไปทำต่อ = ปุ่มพักไร้ความหมาย
                if job.get("parked"):
                    continue
                # เต็มเพดานแล้ว = เริ่มใบใหม่ไม่ได้ แต่งานที่เริ่มไปแล้วเดินต่อได้
                if full and stage == STAGE_QUEUED:
                    continue
                rank = (STAGE_PRIORITY.get(stage, 99), index)
                if best is None or rank < best[0]:
                    best = (rank, job)
            if best is not None:
                job = best[1]
                was = job["stage"]
                job["stage"] = moving[was]
                job["claimed_from"] = was
                job["updated_at"] = _now()
                self._save()
                return dict(job)
        return None

    def move(self, job_id: str, delta: int) -> dict:
        """เลื่อนลำดับงานที่ยัง "รอคิว" อยู่

        เลื่อนได้เฉพาะในกลุ่ม queued ด้วยกันเท่านั้น — งานที่เริ่มไปแล้วมีของค้าง
        อยู่ในเครื่อง (โฟลเดอร์สินค้า แชท GPT ที่เปิดไว้) การสลับตำแหน่งมันไม่ได้
        ทำให้เกิดอะไรขึ้นจริง มีแต่ทำให้รายการที่ผู้ใช้เห็นไม่ตรงกับความจริง
        """
        with self.lock:
            slots = [i for i, j in enumerate(self.jobs) if j.get("stage") == STAGE_QUEUED]
            here = next((k for k, i in enumerate(slots) if self.jobs[i]["id"] == job_id), None)
            if here is None:
                raise ClipQueueError("เลื่อนได้เฉพาะงานที่ยังรอคิวอยู่")
            there = here + (1 if delta > 0 else -1)
            if not 0 <= there < len(slots):
                raise ClipQueueError("อยู่สุดทางแล้ว")
            a, b = slots[here], slots[there]
            self.jobs[a], self.jobs[b] = self.jobs[b], self.jobs[a]
            self._save()
            return dict(self.jobs[b])

    # ---------------------------------------------------------- ถังขยะ

    def _trash_path(self) -> Path:
        return self.path.with_name(self.path.stem + "_trash.json")

    def _trash_load(self) -> list[dict]:
        try:
            return json.loads(self._trash_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []

    def _trash_save(self, items: list[dict]) -> None:
        path = self._trash_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(".json.tmp")
        temp.write_text(
            json.dumps(items, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        temp.replace(path)

    def _to_trash(self, jobs: list[dict], why: str) -> None:
        """เก็บงานที่ถูกลบไว้ก่อน ไม่ทิ้งทันที

        **ทำไม** 13 ส.ค. เคลียร์งาน failed ไป 8 ใบเพื่อล้างคิว แล้วภายหลังพบว่า
        ใบหนึ่งล้มเพราะบั๊กของระบบเอง ไม่ใช่ของเสีย — แต่ตอนนั้นกู้กลับมาไม่ได้
        สักใบเพราะ remove() ลบทิ้งจริง (ฟาร์มโปรไฟล์บอทมี _trash มาตั้งนานแล้ว
        คิวคลิปกลับไม่มี)

        เก็บ TRASH_DAYS วันแล้วค่อยหายเอง และจำกัดจำนวนไม่ให้ไฟล์โตไม่หยุด
        """
        if not jobs:
            return
        stamp = time.time()
        items = self._trash_load()
        for job in jobs:
            entry = dict(job)
            entry["_trashed_at"] = stamp
            entry["_trashed_why"] = why
            items.append(entry)
        cutoff = stamp - TRASH_DAYS * 86400
        items = [i for i in items if float(i.get("_trashed_at") or 0) >= cutoff]
        self._trash_save(items[-TRASH_LIMIT:])

    def trash(self) -> list[dict]:
        """งานในถังขยะ ใหม่สุดขึ้นก่อน"""
        return list(reversed(self._trash_load()))

    def restore(self, job_id: str = "") -> dict:
        """กู้งานจากถังขยะกลับเข้าคิว — ไม่ใส่ id = กู้ใบที่ลบล่าสุด

        กู้กลับมาเป็นสถานะเดิมตอนถูกลบ ไม่ใช่เอาไปเข้าคิวทำใหม่ (จะเจนใหม่
        ค่อยสั่ง retry ทีหลัง) — กู้แล้วเจนเองอัตโนมัติคือจ่ายเครดิตโดยไม่ได้สั่ง
        """
        with self.lock:
            items = self._trash_load()
            if not items:
                raise ClipQueueError("ถังขยะว่าง ไม่มีอะไรให้กู้")
            if job_id:
                found = next(
                    (i for i in range(len(items)) if items[i].get("id") == job_id), None
                )
                if found is None:
                    raise ClipQueueError(f"ไม่พบงาน {job_id} ในถังขยะ")
            else:
                found = len(items) - 1
            entry = items.pop(found)
            if any(j["id"] == entry.get("id") for j in self.jobs):
                raise ClipQueueError("งานนี้อยู่ในคิวอยู่แล้ว")
            entry.pop("_trashed_at", None)
            entry.pop("_trashed_why", None)
            self.jobs.append(entry)
            self._save()
            self._trash_save(items)
            return dict(entry)

    def remove(self, job_id: str) -> bool:
        """เอางานออกจากคิว — ใช้กับงานที่จบแล้วเท่านั้น

        ไม่แตะโฟลเดอร์งานในดิสก์ ของที่ทำไว้ยังอยู่ครบและยังเปิดดูได้จาก
        รายการ "งานที่เก็บไว้" — ตรงนี้คือเอาออกแค่แถวในคิว

        และ**ไม่ทิ้งทันที** — ย้ายเข้าถังขยะไว้ก่อน กู้กลับได้ด้วย restore()
        """
        with self.lock:
            job = next((j for j in self.jobs if j["id"] == job_id), None)
            if job is None:
                raise ClipQueueError(f"ไม่พบงาน {job_id}")
            if job.get("stage") in OPEN_STAGES:
                raise ClipQueueError("งานนี้ยังไม่จบ — ยกเลิกก่อนถึงจะลบได้")
            self._to_trash([job], "ลบจากคิว")
            self.jobs = [j for j in self.jobs if j["id"] != job_id]
            self._save()
            return True

    def prune(self, keep: int = 60) -> int:
        """ตัดงานที่จบแล้วให้เหลือเท่าที่กำหนด — ไฟล์คิวจะได้ไม่โตไม่หยุด"""
        with self.lock:
            closed = [j for j in self.jobs if j.get("stage") not in OPEN_STAGES]
            if len(closed) <= keep:
                return 0
            drop = {id(j) for j in closed[: len(closed) - keep]}
            before = len(self.jobs)
            self._to_trash([j for j in self.jobs if id(j) in drop], "ตัดคิวอัตโนมัติ")
            self.jobs = [j for j in self.jobs if id(j) not in drop]
            self._save()
            return before - len(self.jobs)

    # ------------------------------------------------------------- อ่าน

    def get(self, job_id: str) -> dict | None:
        with self.lock:
            return next((dict(j) for j in self.jobs if j["id"] == job_id), None)

    def all(self) -> list[dict]:
        with self.lock:
            return [dict(j) for j in self.jobs]

    def waiting(self) -> list[dict]:
        with self.lock:
            return [dict(j) for j in self.jobs if j.get("stage") in OPEN_STAGES]

    def load_now(self) -> dict:
        """ตอนนี้มีงานในมือกี่ใบ เต็มเพดานหรือยัง รอคิวอีกกี่ใบ

        ต้องมีตัวนี้เพราะถ้าเพดานทำงานเงียบๆ ผู้ใช้จะเห็นแค่ "ลิงก์ 25 ใบไม่ขยับ"
        แล้วนึกว่าระบบค้าง — เพดานที่มองไม่เห็นแยกไม่ออกจากของพัง
        """
        with self.lock:
            # **ต้องนับสูตรเดียวกับ `claim_next` เป๊ะ** ไม่งั้นหน้าเว็บจะบอกว่าเต็ม
            # ทั้งที่ตัวรันยังหยิบงานได้ (หรือกลับกัน) แล้วไล่บั๊กกันไม่จบ
            # ใบที่พักไว้รอแก้ไม่นับในทุกช่อง — เครื่องไม่แตะ คนก็ยังไม่แตะ
            # นับรวมเมื่อไรตัวเลขจะบอกว่ามีงานค้างเยอะทั้งที่ไม่มีอะไรเดินอยู่จริง
            live = [j for j in self.jobs if not j.get("parked")]
            busy = sum(1 for j in live if j.get("stage") in MACHINE_STAGES)
            waiting = sum(1 for j in live
                          if j.get("stage") in OPEN_STAGES
                          and j.get("stage") not in MACHINE_STAGES
                          and j.get("stage") != STAGE_QUEUED)
            queued = sum(1 for j in live if j.get("stage") == STAGE_QUEUED)
            parked = sum(1 for j in self.jobs if j.get("parked"))
        return {"busy": busy, "queued": queued, "limit": BATCH_LIMIT,
                # งานที่จอดรอคนกด — ไม่กินเพดาน แต่ต้องเห็นว่ามีอยู่เท่าไร
                "waiting": waiting,
                # งานที่พักไว้รอแก้ — ดูรายการเต็มด้วย /wait
                "parked": parked,
                "full": busy >= BATCH_LIMIT, "free": max(0, BATCH_LIMIT - busy)}

    def load_text(self) -> str:
        """สรุปภาระคิวเป็นภาษาคน — ใช้ในแชทและหน้าเว็บ"""
        info = self.load_now()
        head = f"⚙️ กำลังทำ {info['busy']}/{info['limit']} งาน"
        # งานที่จอดรอคนกดต้องแยกให้เห็น — ไม่งั้นเลข busy ที่ต่ำจะดูเหมือนระบบว่าง
        # ทั้งที่มีของค้างรอเจ้าของอยู่หลายใบ
        if info.get("waiting"):
            head += f" · รอคุณกดอนุมัติอีก {info['waiting']} ใบ"
        if info.get("parked"):
            head += f" · พักรอแก้อีก {info['parked']} ใบ (/wait)"
        if info["queued"]:
            head += f" · รอคิวอีก {info['queued']} ใบ"
        if info["full"] and info["queued"]:
            head += ("\nเต็มเพดานแล้ว — ใบใหม่จะเริ่มเองเมื่องานที่เครื่องทำอยู่จบ "
                     "(งานที่รอคุณกดอนุมัติไม่กินเพดาน ดึงลิงก์ใหม่ได้เรื่อยๆ)")
        elif not info["queued"]:
            head += " · ไม่มีใบรอคิว"
        return head

    def latest_for_chat(self, chat_id: str, stages: set[str] | None = None) -> dict | None:
        """งานล่าสุดของแชทนี้ที่อยู่ในสถานะที่สนใจ

        ใช้ตอนผู้ใช้พิมพ์คำสั่งแก้เข้ามาเฉยๆ โดยไม่ได้ระบุว่างานไหน — ผูกกับงาน
        ที่เพิ่งคุยกันอยู่ ไม่ใช่ให้ผู้ใช้ต้องจำรหัสงาน
        """
        with self.lock:
            found = [
                j for j in self.jobs
                if str(j.get("chat_id")) == str(chat_id)
                and (stages is None or j.get("stage") in stages)
            ]
        return dict(found[-1]) if found else None


class ClipRunner:
    """ตัวรันงานในคิว — ทีละงานเท่านั้น

    เดินอยู่ตัวเดียวตลอดอายุเซิร์ฟเวอร์ ปลุกด้วย `wake()` เมื่อมีงานใหม่หรือมีคนกด
    อนุมัติ ไม่ได้ใช้การวนถามถี่ๆ เพราะงานเจนคลิปนานเป็นนาที ไม่ต้องรีบ
    """

    def __init__(self, queue: ClipQueue, handler: Callable[[dict], None], log=print,
                 on_hold: Callable[[dict], None] | None = None) -> None:
        self.queue = queue
        self.handler = handler
        self.log = log
        # เรียกเมื่อคิวถูกพักเพราะปลายทางบล็อก — ตัวเรียกใช้ส่งข้อความเข้าแชท
        #
        # ต้องเป็น callback ไม่ใช่ให้ clip_queue ส่ง Telegram เอง เพราะไฟล์นี้เป็น
        # คิวล้วนๆ ไม่รู้จักแชท ถ้าผูกกันจะเทสคิวโดยไม่มีโทเคน Telegram ไม่ได้
        self.on_hold = on_hold
        self.signal = threading.Event()
        self.thread: threading.Thread | None = None
        self.current = ""

    def start(self) -> None:
        if self.thread and self.thread.is_alive():
            return
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def wake(self) -> None:
        self.signal.set()

    @property
    def busy(self) -> bool:
        return bool(self.current)

    def _loop(self) -> None:
        while True:
            job = self.queue.claim_next()
            if not job:
                # รอสัญญาณ แต่ตื่นเองทุก 30 วิด้วย เผื่อมีคนแก้ไฟล์คิวจากข้างนอก
                self.signal.wait(timeout=30)
                self.signal.clear()
                continue
            self.current = job["id"]
            try:
                self.handler(job)
            except Exception as error:
                # งานหนึ่งพังต้องไม่ทำให้ตัวรันตายทั้งตัว งานที่เหลือในคิวต้องเดินต่อ
                self.log(f"งาน {job['id']} ล้มเหลว: {type(error).__name__}: {error}")
                # ---- ยังไม่ได้ล็อกอิน = หยุดทันที (เจ้าของสั่ง 28 ส.ค. 2569) ----
                #
                # ต้องเช็ค **ก่อน** ตัวบล็อก เพราะเป็นเรื่องที่ล้มแน่นอนทุกใบ
                # ไล่ต่อไม่มีทางได้อะไรกลับมา มีแต่เผางานทิ้ง
                # (28 ส.ค. 13:17–13:19 ล้ม 54 ใบใน 2 นาที 26 วินาที ข้อความเดียวกันทุกใบ)
                #
                # พักแบบ **ไม่มีกำหนดเวลา** เพราะล็อกอินแทนกันไม่ได้ ต้องรอคนจริงๆ
                if _looks_login_error(str(error)):
                    already = self.queue.held()
                    self.queue.hold(str(error)[:200])
                    self.log(
                        "🛑 ยังไม่ได้ล็อกอินปลายทาง — หยุดคิวทันที "
                        "งานที่เหลือยังอยู่ครบ ไม่ได้ถูกเผาทิ้ง "
                        "ล็อกอินแล้วสั่งทำต่อได้เลย"
                    )
                    if not already and self.on_hold:
                        try:
                            self.on_hold({"job": job, "error": str(error)[:300],
                                          "kind": "login", "seconds": 0})
                        except Exception as hold_error:          # noqa: BLE001
                            self.log(f"แจ้งเรื่องคิวถูกพักไม่สำเร็จ: {hold_error}")
                    try:
                        self.queue.update(job["id"], stage=STAGE_FAILED,
                                          error=str(error)[:400])
                    except ClipQueueError:
                        pass
                    self.current = ""
                    continue
                # ปลายทางบล็อกอยู่ = พักทั้งคิว **ห้ามไล่ยิงใบถัดไปจนหมด**
                # (25 ส.ค. 2026 ไล่ยิงต่อ 25 ใบหลังโดนบล็อก ล้มหมด + สร้างขยะ 14 ชิ้น)
                if _looks_blocked_error(str(error)):
                    already = self.queue.held()
                    # **แยกสองหน้าออกจากกัน** (ผู้ใช้สั่ง 27 ส.ค. 2026)
                    #   wait  = "Please Try Again Later" ไม่มีอะไรให้คนทำ → พักเองแล้วไปต่อ
                    #   human = จิ๊กซอว์จริง ต้องมีคนเลื่อน → รอยืนยันเหมือนเดิม
                    kind = block_kind(str(error))
                    if kind == "wait":
                        self.queue.hold(str(error)[:200], seconds=BLOCK_HOLD_SECONDS)
                        self.log(
                            f"⛔ ปลายทางบล็อกอยู่ (แบบรอเวลา ไม่มีจิ๊กซอว์ให้เลื่อน) — "
                            f"พักคิว {BLOCK_HOLD_SECONDS // 60} นาทีแล้วทำต่อเอง "
                            f"ลิงก์ที่เหลือยังอยู่ครบ ไม่ต้องรอใครกดอะไร"
                        )
                    else:
                        self.queue.hold(str(error)[:200])
                        self.log(
                            f"⛔ ปลายทางขึ้นด่านยืนยันตัวตน — พักคิว ลิงก์ที่เหลือยังอยู่ครบ "
                            f"รอผู้ใช้เลื่อนจิ๊กซอว์แล้วยืนยันถึงจะทำต่อ"
                        )
                    # แจ้งครั้งเดียวตอนเพิ่งติด ไม่ใช่ทุกใบที่ล้ม
                    # (เตือนรัวๆ เท่ากับไม่มีเตือน เดี๋ยวก็เลิกอ่านกัน)
                    if not already and self.on_hold:
                        try:
                            self.on_hold({"job": job, "error": str(error)[:300],
                                          "kind": kind,
                                          "seconds": BLOCK_HOLD_SECONDS if kind == "wait" else 0})
                        except Exception as hold_error:      # noqa: BLE001
                            self.log(f"แจ้งเรื่องคิวถูกพักไม่สำเร็จ: {hold_error}")
                try:
                    self.queue.update(
                        job["id"], stage=STAGE_FAILED, error=str(error)[:400]
                    )
                except ClipQueueError:
                    pass
            finally:
                self.current = ""
