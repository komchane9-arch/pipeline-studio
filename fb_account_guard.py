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


def _sh(adb: str, serial: str, *args: str, timeout: float = 90.0):
    return subprocess.run([adb, "-s", serial, *args],
                          capture_output=True, timeout=timeout)


def _dump(adb: str, serial: str) -> str:
    """ผังหน้าจอตอนนี้ — คืนค่าว่างเมื่ออ่านไม่ได้"""
    remote = "/sdcard/fb_account_guard.xml"
    _sh(adb, serial, "shell", f"uiautomator dump {remote}")
    xml = _sh(adb, serial, "shell", f"cat {remote}").stdout.decode("utf-8", "replace")
    _sh(adb, serial, "shell", f"rm -f {remote}", timeout=20)
    return xml if "<node" in xml else ""


def _tap_profile_tab(adb: str, serial: str, xml: str) -> bool:
    """กดแท็บโปรไฟล์โดยหาจากผังจอ — คืน True เมื่อกดได้จริง"""
    for node in re.finditer(r"<node[^>]*>", xml):
        chunk = node.group(0)
        label = " ".join(re.findall(r'(?:content-desc|text)="([^"]*)"', chunk))
        if not label or not _PROFILE_TAB.search(label):
            continue
        box = re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', chunk)
        if not box:
            continue
        x1, y1, x2, y2 = (int(v) for v in box.groups())
        # แท็บล่างสุดเท่านั้น — คำว่า "โปรไฟล์" โผล่กลางหน้าได้หลายที่
        if y1 < 0.80 * _screen_height(xml):
            continue
        _sh(adb, serial, "shell", "input", "tap",
            str((x1 + x2) // 2), str((y1 + y2) // 2))
        return True
    return False


def _screen_height(xml: str) -> int:
    """ความสูงจอจากผัง — อ่านไม่ได้คืน 0 แล้วเงื่อนไขข้างบนจะยอมทุกแถว"""
    found = [int(m) for m in re.findall(r'bounds="\[\d+,\d+\]\[\d+,(\d+)\]"', xml)]
    return max(found) if found else 0


def read_account(adb: str, serial: str, wait: float = 6.0) -> str:
    """ชื่อบัญชี Facebook ที่แอปกำลังใช้อยู่บนเครื่องนี้ — อ่านไม่ออกคืนค่าว่าง

    เปิดแอปได้ (ข้อ 2.7 ยกเว้นให้เฉพาะตอนเปิดแอป) จากนั้นกดแท็บโปรไฟล์
    แล้วอ่านชื่อที่หัวหน้า — **ไม่แตะอะไรที่เปลี่ยนสถานะบัญชีเลย**
    """
    _sh(adb, serial, "shell", "monkey", "-p", APP,
        "-c", "android.intent.category.LAUNCHER", "1")
    time.sleep(wait)
    xml = _dump(adb, serial)
    if not xml:
        return ""
    if _tap_profile_tab(adb, serial, xml):
        time.sleep(wait)
        xml = _dump(adb, serial)
    # **ต้องพิสูจน์ก่อนว่าอยู่หน้าโปรไฟล์จริง** (ข้อ 2.3.1)
    #
    # เจอจริงตอนทดสอบเครื่องที่สอง: กดแท็บไม่ติด ยังค้างอยู่หน้าฟีด แล้วตัวอ่าน
    # หยิบคำว่า "สร้างสตอรี่" มาเป็นชื่อบัญชี — ได้ตัวตรวจที่ตอบผ่านทั้งที่ยัง
    # ไม่ผ่าน ซึ่งอันตรายกว่าไม่มีตัวตรวจเลย
    #
    # ป้ายนี้ **มีเฉพาะบนหน้าโปรไฟล์ของตัวเองเท่านั้น**
    #
    # รอบแรกผมใส่ "เพิ่มลงในสตอรี่" เข้าไปด้วย แล้วยังอ่านผิดอยู่ —
    # เพราะแถบสตอรี่บนหน้าฟีดก็มีคำนั้น กลายเป็นตัวชี้ที่ตอบว่าใช่ได้ทั้งสองหน้า
    # ซึ่งคือความผิดพลาดแบบเดียวกับที่ข้อ 2.3.1 เตือนไว้เป๊ะ
    marker = re.search(r'text="(แก้ไขโปรไฟล์|Edit profile)"', xml)
    if not marker:
        return ""
    # **ไล่ย้อนขึ้นจากปุ่ม "แก้ไขโปรไฟล์" ไม่ใช่หยิบบรรทัดแรกของจอ**
    #
    # เจอจริงตอนทดสอบเครื่องที่สอง: บรรทัดแรกของผังจอเป็นช่องคอมเมนต์ที่ค้าง
    # จากหน้าก่อน ("แสดงความคิดเห็น…") ตัวอ่านจึงคืนคำนั้นมาเป็นชื่อบัญชี
    # ทั้งที่ชื่อจริงอยู่ถัดลงมา — หยิบตำแหน่งผิด ไม่ใช่หน้าผิด
    #
    # โครงหน้าโปรไฟล์เรียงแบบนี้เสมอ: ชื่อ → จำนวนเพื่อน/โพสต์ → คำแนะนำตัว
    # → ปุ่ม ฉะนั้นไล่ย้อนจากปุ่มขึ้นไป เจอข้อความที่เป็นชื่อได้ก่อนตัวอื่น
    before = re.findall(r'text="([^"]{1,45})"', xml[:marker.start()])
    for text in reversed(before):
        clean = text.replace(" ", " ").strip()
        if (len(clean) < 3 or clean.isdigit() or _NOT_A_NAME.match(clean)
                or ":" in clean or "·" in clean
                or not re.fullmatch(r"[^<>{}\[\]|]{3,45}", clean)):
            continue
        return clean
    return ""


def same_account(a: str, b: str) -> bool:
    """ชื่อเดียวกันไหม — ยอมให้ช่องว่างและตัวพิมพ์ต่างกันได้"""
    norm = lambda s: re.sub(r"\s+", " ", str(s or "")).strip().casefold()
    return bool(norm(a)) and norm(a) == norm(b)


def require(adb: str, serial: str, expect: str) -> str:
    """ต้องเป็นบัญชีนี้เท่านั้นถึงจะโพสต์ได้ — คืนชื่อที่อ่านได้จริง

    โยน `AccountUnreadable` เมื่ออ่านไม่ออก และ `AccountMismatch` เมื่อไม่ตรง
    **ทั้งสองกรณีคือไม่ผ่าน** เพราะโพสต์ผิดบัญชีถอนคืนไม่ได้ ส่วนงานไม่เริ่ม
    เสียแค่เวลากดใหม่
    """
    if not str(expect or "").strip():
        raise AccountUnreadable(
            "ยังไม่รู้ว่าเครื่องนี้ควรโพสต์ในนามบัญชีไหน — ผูกบัญชีก่อนด้วย "
            f'python devices.py account {serial} "<ชื่อบัญชี>"')
    found = read_account(adb, serial)
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
