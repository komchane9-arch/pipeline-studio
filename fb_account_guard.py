# -*- coding: utf-8 -*-
"""ด่านกันโพสต์ผิดบัญชี — อ่านชื่อบัญชีจากหน้าจอมือถือจริงก่อนเริ่มโพสต์

**เจ้าของสั่งต่อสายโพสต์บัญชีที่สอง 16 ก.ย. 2569** พอมีสองบัญชีขึ้นไป
ความผิดพลาดที่แพงที่สุดของทั้งระบบคือ **โพสต์ขึ้นในนามบัญชีผิด ซึ่งถอนคืนไม่ได้**

ระบบกันเรื่องนี้ไว้แน่นหนาในชั้นบน — `posting_account()` ยอมโยน error ทิ้งงาน
ดีกว่าเดาบัญชี และทะเบียนบังคับหนึ่งเครื่องต่อหนึ่งไอดี **แต่ชั้นล่างสุดไม่มีใครกัน
เลย**: ตัวโพสต์เปิดแอป Facebook แล้วกดโพสต์ตามพิกัด โดยไม่เคยถามสักครั้งว่า
แอปกำลังเปิดอยู่ที่บัญชีไหน

วัดจริงบนเครื่อง 7a95129e วันนั้น: **ล็อกอินค้างไว้ 6 บัญชี**

    61577429086714 · 100009163339074 · 100000408141427
    61560607347143 · 61590826046544 · 61593954667334

ถ้าใครสลับบัญชีในแอปทิ้งไว้ งานถัดไปจะโพสต์ในนามคนนั้นทันทีโดยไม่มีอะไรฟ้อง

## ตัวตรวจนี้ถามคำถามที่ถูกต้อง (กติกาข้อ 2.3.1)

ถาม **"ตอนนี้ชื่อบัญชีบนจอคืออะไร"** แล้วเทียบกับที่ทะเบียนผูกไว้ —
ไม่ใช่ถามว่า "ไม่เจอสัญญาณว่าผิดใช่ไหม" ซึ่งตอบว่าใช่ได้ทั้งตอนถูกและตอนอ่านไม่ออก

และแยกสามสถานะออกจากกันชัดเจน

    ตรงกัน        → ไปต่อ
    ไม่ตรง        → หยุด บอกว่าเจอชื่อไหนบนจอ
    อ่านไม่ออก     → **หยุดเหมือนกัน** ไม่ใช่ปล่อยผ่าน
                    (ข้อ 2.3.1 ข้อ 4: "ยังไม่ได้ตรวจ" ห้ามหน้าตาเหมือน "ตรวจแล้วผ่าน")

## ไม่ฝังพิกัดตายในโค้ด (ข้อ 2.7.3)

หาแท็บโปรไฟล์จากผังหน้าจอด้วยคำบรรยายปุ่ม แล้วกดกลางกรอบของมันจริง
เปลี่ยนรุ่นมือถือหรือความละเอียดจอแล้วยังใช้ได้เหมือนเดิม
"""

from __future__ import annotations

import re
import subprocess
import time

import fb_screen
from collections import Counter
from pathlib import Path

# ปุ่มแท็บโปรไฟล์ — Facebook เรียกต่างกันตามภาษาเครื่อง
_PROFILE_TAB = re.compile(r"โปรไฟล์|profile|บัญชี|เมนู|menu", re.IGNORECASE)
# ป้ายบนหน้าโปรไฟล์ที่ **ไม่ใช่ชื่อคน** — กันหยิบผิดบรรทัด
_NOT_A_NAME = re.compile(
    r"^(โพสต์|เพิ่มลงในสตอรี่|สร้างสตอรี่|แก้ไขโปรไฟล์|ทั้งหมด|รูปภาพ|Reels|เพื่อน|"
    r"ดูทั้งหมด|รายละเอียดส่วนตัว|แชร์โน้ต|อัพเดตโปรไฟล์ของคุณ|"
    r"แสดงความคิดเห็น|เขียนความคิดเห็น|คุณกำลังคิดอะไรอยู่|"
    r"เพื่อนที่มีสิ่งที่เหมือนกัน|มีเพื่อนร่วมกัน|รายการใหม่|"
    r"ใช้ Facebook ให้เกิดประโยชน์มากขึ้น)")

APP = "com.facebook.katana"


class AccountMismatch(RuntimeError):
    """บัญชีบนจอไม่ตรงกับที่ทะเบียนผูกไว้ — ห้ามโพสต์ต่อ"""


class AccountUnreadable(RuntimeError):
    """อ่านชื่อบัญชีจากจอไม่ได้ — ถือว่าไม่ผ่าน ไม่ใช่ปล่อยผ่าน"""


class ScreenAsleep(AccountUnreadable):
    """ปลุกจอไม่ขึ้น จึงยังไม่ได้ตรวจอะไรเลย — คนละเรื่องกับตรวจแล้วอ่านไม่ออก"""


# **ต้องใส่ธงซ่อนหน้าต่างเสมอ** Windows 11 ตั้ง Windows Terminal เป็นตัวรับ
# คอนโซล โปรเซสที่ไม่ใส่ธงนี้จะเด้งหน้าต่างดำขึ้นมาจริงทุกครั้งที่ถูกเรียก
# ด่านนี้ยิง adb ทุก 2 วินาที สูงสุด 12 รอบ = เด้งได้ถึง 36 หน้าต่างต่อการตรวจ
# หนึ่งครั้ง (วัดจริง 21 ก.ย. 2569: WindowsTerminal.exe เกิด 9 ตัวใน 40 วินาที
# ตอนคิวตอบคอมเมนต์วนอ่านชื่อบัญชีไม่สำเร็จ)
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _sh(adb: str, serial: str, *args: str, timeout: float = 90.0):
    return subprocess.run([adb, "-s", serial, *args],
                          capture_output=True, timeout=timeout,
                          creationflags=NO_WINDOW)


def _dump(adb: str, serial: str) -> str:
    """ผังหน้าจอตอนนี้ — คืนค่าว่างเมื่ออ่านไม่ได้"""
    remote = "/sdcard/fb_account_guard.xml"
    _sh(adb, serial, "shell", f"uiautomator dump {remote}")
    xml = _sh(adb, serial, "shell", f"cat {remote}").stdout.decode("utf-8", "replace")
    _sh(adb, serial, "shell", f"rm -f {remote}", timeout=20)
    return xml if "<node" in xml else ""


def _bottom_tabs(xml: str) -> list[tuple[int, int, int, int, str]]:
    """ช่องแท็บแถวล่างสุด เรียงซ้าย→ขวา — หาจาก**เรขาคณิต** ไม่พึ่งป้าย

    **วัดจริง 16 ก.ย. 2569** Facebook บนเครื่องนี้ไม่ใส่ป้ายให้แถบล่างเลย
    ในช่วงแรกหลังเปิดแอป (รอ 24 วินาทีแล้วยังไม่มี) การหาแท็บจากคำว่า
    "โปรไฟล์" จึงล้มเหลวแบบสุ่มขึ้นกับว่าแอปโหลดเสร็จหรือยัง

    แต่**รูปทรงมาก่อนป้ายเสมอ**: แถบล่างคือช่องกดได้ความกว้างเท่ากัน 6 ช่อง
    เรียงเต็มความกว้างจอ ซึ่งอ่านได้ตั้งแต่วินาทีที่ 2 ทุกครั้ง
    """
    height = _screen_height(xml)
    width = max((int(m) for m in
                 re.findall(r'bounds="\[\d+,\d+\]\[(\d+),\d+\]"', xml)), default=0)
    if not height or not width:
        return []
    bands: dict[int, list[tuple[int, int, int, int, str]]] = {}
    for node in re.finditer(r"<node[^>]*>", xml):
        chunk = node.group(0)
        box = re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', chunk)
        if not box or 'clickable="true"' not in chunk:
            continue
        x1, y1, x2, y2 = (int(v) for v in box.groups())
        if y1 < 0.84 * height:
            continue
        if not (0.10 * width < x2 - x1 < 0.25 * width):
            continue
        desc = (re.search(r'content-desc="([^"]*)"', chunk) or [None, ""])[1]
        bands.setdefault(y1, []).append((x1, x2, y1, y2, desc))
    if not bands:
        return []

    # หน้าคอมเมนต์มีปุ่มเลือกว่า "ตอบในนามใคร" อยู่ชิดขอบล่าง และ node
    # เดียวกันมักซ้อนกัน 2 ชั้นด้วย bounds เดิม เดิมเราเห็นสอง node นั้นแล้ว
    # เข้าใจผิดว่าเป็นแถบนำทาง ก่อนแตะไปเปิด composer/identity sheet แทน
    # แถบนำทางจริงต้องมี 5–6 ช่องคนละตำแหน่งและกางเกือบเต็มความกว้างจอ.
    candidates: list[list[tuple[int, int, int, int, str]]] = []
    for rows in bands.values():
        unique: dict[tuple[int, int, int, int], tuple[int, int, int, int, str]] = {}
        for row in rows:
            key = row[:4]
            # เก็บป้ายที่มีข้อความไว้ หาก node ซ้อนกันมี bounds เดียวกัน
            if key not in unique or (not unique[key][4] and row[4]):
                unique[key] = row
        tabs = sorted(unique.values())
        if len(tabs) < 5:
            continue
        if tabs[0][0] > 0.08 * width or tabs[-1][1] < 0.92 * width:
            continue
        candidates.append(tabs)
    if not candidates:
        return []
    return max(candidates, key=lambda rows: (rows[0][2], len(rows)))


def _tap_profile_tab(adb: str, serial: str, xml: str) -> bool:
    """กดแท็บโปรไฟล์ — คืน True เมื่อกดไปแล้วจริง

    มีป้ายก็ใช้ป้าย (แม่นกว่า) ไม่มีป้ายก็ใช้ช่องขวาสุดของแถบล่าง
    ซึ่งเป็นแท็บโปรไฟล์เสมอ (`โปรไฟล์, แท็บ 6 จาก 6`)

    **กดผิดช่องไม่อันตราย** เพราะปลายทางยังต้องเจอป้าย "แก้ไขโปรไฟล์"
    ถึงจะยอมอ่านชื่อ กดผิดจึงได้ผลลัพธ์ "อ่านไม่ออก" ไม่ใช่ชื่อผิด
    """
    tabs = _bottom_tabs(xml)
    if not tabs:
        return False
    target = None
    for x1, x2, y1, y2, desc in tabs:
        if desc and _PROFILE_TAB.search(desc):
            target = (x1, x2, y1, y2)
            break
    if target is None:
        x1, x2, y1, y2, _ = tabs[-1]
        target = (x1, x2, y1, y2)
    x1, x2, y1, y2 = target
    _sh(adb, serial, "shell", "input", "tap",
        str((x1 + x2) // 2), str((y1 + y2) // 2))
    return True


def _screen_height(xml: str) -> int:
    """ความสูงจอจากผัง — อ่านไม่ได้คืน 0 แล้วเงื่อนไขข้างบนจะยอมทุกแถว"""
    found = [int(m) for m in re.findall(r'bounds="\[\d+,\d+\]\[\d+,(\d+)\]"', xml)]
    return max(found) if found else 0


def _wake(adb: str, serial: str, log=None) -> bool:
    """ปลุกจอ + ปัดหน้าล็อกออก **แล้วยืนยันว่าแตะจอได้จริง**

    **บทเรียน 16 ก.ย. 2569 — ด่านนี้กันงานจริงของเจ้าของไว้เพราะขาดขั้นนี้**
    ระบบดับจอมือถือให้เองทุกไม่กี่นาทีตอนไม่มีงาน จอจึงหลับเกือบตลอดเวลา
    ตัวด่านถูกเรียกจาก `_fb_run_job` ซึ่งเป็นขั้นตรวจความพร้อม **ก่อน**
    ตัวคุมมือถือจะถูกสร้าง และตัวปลุกจอตัวจริงอยู่ใน `Phone.__init__`
    ด่านจึงไปอ่านผังจอที่ยังดับอยู่ แล้วตอบ "อ่านไม่ออก" ทุกครั้ง

    วัดจริงบนเครื่อง 7a95129e
        จอดับ    ผังจอ 10,704 ตัวอักษร  หาแท็บโปรไฟล์ไม่เจอเลย
        ปลุกแล้ว  ผังจอ 41,311 ตัวอักษร  เจอ `โปรไฟล์, แท็บ 6 จาก 6` ทันที

    ใช้ `fb_screen.wake` ตัวเดียวกับที่ทั้งระบบใช้ ไม่เขียนวิธีปลุกใหม่ซ้อน
    เพราะตัวนั้น**ยืนยันว่าแตะจอได้จริง** ไม่ใช่สั่งปลุกแล้วเชื่อว่าขึ้น
    (เคยเขียนเป็น `input keyevent KEYCODE_WAKEUP` แล้วเดินต่อเลย ซึ่งวัดแล้ว
    ไม่พอ — "สั่งแล้ว" ไม่เท่ากับ "เกิดขึ้นจริง" ข้อ 2.3.1)
    """
    def shell(cmd: str) -> str:
        return _sh(adb, serial, "shell", *cmd.split()).stdout.decode("utf-8", "replace")

    return fb_screen.wake(shell, log=log)


def _name_near_marker(xml: str) -> str:
    """ชื่อบัญชีจากหน้าโปรไฟล์ — ต้องเห็นหลักฐานว่าอยู่หน้าโปรไฟล์จริงก่อน

    **ต้องพิสูจน์ก่อนว่าอยู่หน้าโปรไฟล์จริง** (ข้อ 2.3.1) ป้าย "แก้ไขโปรไฟล์"
    มีเฉพาะบนหน้าโปรไฟล์ของตัวเองเท่านั้น — หน้าฟีดไม่มี หน้าโปรไฟล์คนอื่นไม่มี
    """
    marker = re.search(r'text="(แก้ไขโปรไฟล์|Edit profile)"', xml)
    if not marker:
        return ""
    # คำบรรยายรูปโปรไฟล์พ่วงชื่อเจ้าของมาให้ตรงๆ ใช้ก่อนถ้ามี
    picture = re.search(
        r'content-desc="(?:รูปโปรไฟล์ของ|Profile picture of)\s+([^"<]{3,60})"',
        xml, re.IGNORECASE)
    if picture:
        return re.sub(r"\s+", " ", picture.group(1)).strip()
    # **ไล่ย้อนขึ้นจากปุ่ม "แก้ไขโปรไฟล์" ไม่ใช่หยิบบรรทัดแรกของจอ**
    #
    # เจอจริงตอนทดสอบเครื่องที่สอง: บรรทัดแรกของผังจอเป็นช่องคอมเมนต์ที่ค้าง
    # จากหน้าก่อน ("แสดงความคิดเห็น…") ตัวอ่านจึงคืนคำนั้นมาเป็นชื่อบัญชี
    # ทั้งที่ชื่อจริงอยู่ถัดลงมา — หยิบตำแหน่งผิด ไม่ใช่หน้าผิด
    #
    # โครงหน้าโปรไฟล์เรียงแบบนี้เสมอ: ชื่อ → จำนวนโพสต์ → ปุ่ม
    # ไล่ย้อนจากปุ่มขึ้นไปจึงเจอชื่อก่อนตัวอื่น
    for text in reversed(re.findall(r'text="([^"]{1,45})"', xml[:marker.start()])):
        clean = re.sub(r"\s+", " ", text.replace(" ", " ")).strip()
        if (len(clean) < 3 or clean.isdigit() or _NOT_A_NAME.match(clean)
                or re.fullmatch(r'(?:[\d,.]+\s*)?(?:posts?|friends?|followers?|following)', clean, re.I)
                or ":" in clean or "·" in clean
                or not re.fullmatch(r"[^<>{}\[\]|]{3,45}", clean)):
            continue
        return clean
    return ""


def _open_facebook_fresh(adb: str, serial: str, log=None) -> None:
    """ปิด Facebook จริงแล้วเปิดหน้าฟีดใหม่ก่อนยืนยันบัญชี.

    Android/Facebook คืน activity เดิมแม้เปิดจาก launcher ใหม่ จึงอาจกลับไปหน้า
    โพสต์ของคิวตอบคอมเมนต์ การเปิด ``fb://feed`` หลัง force-stop บังคับให้มี
    แถบนำทางหลักอีกครั้ง โดยไม่ระบุ profile id และไม่เปลี่ยนบัญชีผู้ใช้.
    """
    if log:
        log("ปิด Facebook ของงานก่อนหน้า แล้วเปิดหน้าฟีดใหม่เพื่อตรวจบัญชี")
    _sh(adb, serial, "shell", "am", "force-stop", APP)
    time.sleep(1.0)
    opened = _sh(
        adb, serial, "shell", "am", "start", "-a",
        "android.intent.action.VIEW", "-d", "fb://feed",
    )
    if opened.returncode:
        _sh(adb, serial, "shell", "monkey", "-p", APP,
            "-c", "android.intent.category.LAUNCHER", "1")


def read_account(adb: str, serial: str, wait: float = 6.0, *,
                 fresh_start: bool = False, log=None) -> str:
    """ชื่อบัญชี Facebook ที่แอป**กำลังใช้อยู่**บนเครื่องนี้ — อ่านไม่ออกคืนค่าว่าง

    เปิดแอป (ข้อ 2.7 ยกเว้นให้เฉพาะตอนเปิดแอป) แล้ว**กด**แท็บโปรไฟล์
    ด้วยการแตะจอจริง จากนั้นอ่านชื่อบนหน้าโปรไฟล์
    — ไม่แตะอะไรที่เปลี่ยนสถานะบัญชีเลย

    ## สองอย่างที่ห้ามใส่กลับเข้ามา (ทั้งคู่วัดแล้วว่าให้ชื่อผิด 16 ก.ย. 2569)

    **1. ห้ามใช้ `fb://profile`** เครื่อง 7a95129e ล็อกอินค้างไว้ 6 บัญชี
    ลิงก์นี้เปิดหน้าโปรไฟล์ของ **'คมไท รามอญ'** ทั้งที่บัญชีที่ใช้งานอยู่จริง
    คือ **'Preaw Buchakorn'** (ยืนยันด้วยภาพหน้าจอทั้งสองหน้า) หน้านั้นมีปุ่ม
    "แก้ไขโปรไฟล์" ครบ จึงผ่านด่านพิสูจน์ทุกอย่าง **แต่เป็นคนละบัญชีกับที่จะโพสต์**
    — ตัวตรวจที่ตอบผิดแบบนี้อันตรายกว่าไม่มีเลย (ข้อ 2.3)

    **2. ห้ามอ่านชื่อจากหน้าที่ค้างอยู่ก่อนเปิดแอป** เคยมีทางลัดแบบนั้น
    วัดจริง 3 รอบติดได้ 3 คำตอบ: 'ตัวกรอง' · '' · 'Preaw Buchakorn'
    คำแรกเป็นป้ายปุ่มบนจอ ไม่ใช่ชื่อคน

    ``fresh_start=True`` ใช้ต้นงานโพสต์และคิวตอบ: ปิด Facebook ที่งานก่อนหน้า
    เปิดค้างไว้ แล้วเปิดหน้าฟีดใหม่ก่อนตรวจบัญชี งานตอบคอมเมนต์รอบถัดไปยังเปิด
    จาก ``post_url`` ที่บันทึกในคิว จึงไม่พึ่งหน้าเดิมที่ถูกปิดไป.
    """
    if not _wake(adb, serial):
        raise ScreenAsleep(
            "ปลุกจอมือถือไม่ขึ้น — ยังไม่ได้ตรวจบัญชีเลยสักนิด "
            "(จออาจติดหน้าล็อกที่ต้องใส่รหัส)")

    if fresh_start:
        _open_facebook_fresh(adb, serial, log=log)
    else:
        _sh(adb, serial, "shell", "monkey", "-p", APP,
            "-c", "android.intent.category.LAUNCHER", "1")

    # รอ**จนแถบแท็บโผล่จริง** ไม่ใช่รอเวลาตายตัวแล้วเดาว่าพร้อมแล้ว
    for _ in range(12 if fresh_start else 8):
        time.sleep(2.0)
        xml = _dump(adb, serial)
        if xml and _bottom_tabs(xml):
            break
    else:
        return ""

    if not _tap_profile_tab(adb, serial, xml):
        return ""
    # หน้าโปรไฟล์บางรอบแสดงโครงก่อนข้อความชื่อ อย่าตัดสินจาก dump เดียว.
    edge = time.monotonic() + max(wait, 2.0)
    while True:
        time.sleep(min(2.0, max(0.0, edge - time.monotonic())))
        found = _name_near_marker(_dump(adb, serial))
        if found:
            return found
        if time.monotonic() >= edge:
            return ""


def same_account(a: str, b: str) -> bool:
    """ชื่อเดียวกันไหม — ยอมให้ช่องว่างและตัวพิมพ์ต่างกันได้"""
    norm = lambda s: re.sub(r"\s+", " ", str(s or "")).strip().casefold()
    return bool(norm(a)) and norm(a) == norm(b)


def require(adb: str, serial: str, expect: str, *,
            fresh_start: bool = False, log=None) -> str:
    """ต้องเป็นบัญชีนี้เท่านั้นถึงจะโพสต์ได้ — คืนชื่อที่อ่านได้จริง

    โยน `AccountUnreadable` เมื่ออ่านไม่ออก และ `AccountMismatch` เมื่อไม่ตรง
    **ทั้งสองกรณีคือไม่ผ่าน** เพราะโพสต์ผิดบัญชีถอนคืนไม่ได้ ส่วนงานไม่เริ่ม
    เสียแค่เวลากดใหม่
    """
    if not str(expect or "").strip():
        raise AccountUnreadable(
            "ยังไม่รู้ว่าเครื่องนี้ควรโพสต์ในนามบัญชีไหน — ผูกบัญชีก่อนด้วย "
            f'python devices.py account {serial} "<ชื่อบัญชี>"')
    found = read_account(
        adb, serial, fresh_start=fresh_start, log=log)
    if not found:
        raise AccountUnreadable(
            "อ่านชื่อบัญชีจากหน้าจอไม่ได้ — ไม่ยอมให้โพสต์ต่อ เพราะยังพิสูจน์ไม่ได้ "
            "ว่าแอปเปิดอยู่ที่บัญชีไหน (ปลดล็อกจอแล้วลองใหม่)")
    if not same_account(found, expect):
        raise AccountMismatch(
            f"แอป Facebook บนเครื่องนี้เปิดอยู่ที่บัญชี '{found}' "
            f"แต่ใบงานเป็นของ '{expect}' — หยุดไว้ก่อน "
            "สลับบัญชีในแอปให้ถูกแล้วค่อยสั่งใหม่")
    return found


def main() -> int:
    """เช็คด้วยมือ: python fb_account_guard.py <serial> [ชื่อบัญชีที่คาดไว้]"""
    import sys
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    if len(sys.argv) < 2:
        print("ใช้: python fb_account_guard.py <serial> [ชื่อบัญชี]")
        return 1
    serial = sys.argv[1]
    adb = _find_adb()
    found = read_account(adb, serial)
    print(f"บัญชีบนจอของ {serial}: {found or '(อ่านไม่ออก)'}")
    if len(sys.argv) > 2:
        ok = same_account(found, sys.argv[2])
        print(("✅ ตรงกับ " if ok else "❌ ไม่ตรงกับ ") + sys.argv[2])
        return 0 if ok else 2
    return 0


def _find_adb() -> str:
    """หา adb ที่ใช้ได้จริง — เครื่องนี้มีหลายที่ ห้ามเดาที่เดียวแล้วล้ม"""
    for path in (r"C:\project\2.Auto gen Video\7.web app\tools\platform-tools\adb.exe",
                 r"C:\adb\adb.exe"):
        if Path(path).is_file():
            return path
    return "adb"


ADB = _find_adb()

if __name__ == "__main__":
    raise SystemExit(main())
