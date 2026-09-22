"""สลับโปรไฟล์ในแอป Facebook บนมือถือ — และ**พิสูจน์ผลทุกครั้ง**

เจ้าของสั่ง 22 ก.ย. 2569 — *"ผมต้องการให้สลับ profile ได้ เพราะบางทีต้องลงคลิป
ผ่านอีกเพจ"* และ *"ให้ไล่ต่อจนจบจนเช็คได้"*

## ทำไมเรื่องนี้อันตรายกว่าที่เห็น

มือถือเครื่องเดียวถือหลายโปรไฟล์ และงานอัตโนมัติอื่นใช้เครื่องเดียวกัน
**สลับไปแล้วไม่ได้สลับกลับ = งานถัดไปโพสต์ออกในนามผิด ซึ่งกู้ไม่ได้**

วัดจริง 22 ก.ย. 2569 บน W4FYYPYTLFYLIFHM (REDMI 15C วิดีโอ) — เครื่องนี้ถือ
สามโปรไฟล์: คน 1 (Komchan Ramunudom) เพจ 2 (ไท คัดมาแล้วครับ · Squishy Cute
Club) โดยสายคลิปลง Reels ในนาม Squishy Cute Club ทุกวัน
ระหว่างทดสอบเครื่องเคยค้างในโหมดเพจผิดอยู่ ~20 นาที

## รากของปัญหาที่ทำให้รอบแรกล้ม 9 ครั้งติด

**แอป Facebook เปลี่ยนหน้าตาเมื่ออยู่โหมดเพจแบบมืออาชีพ**

    โหมดคน / เพจธรรมดา      เมนู = แท็บล่างขวาสุด
    โหมดเพจแบบมืออาชีพ       เมนู = ☰ มุมบนซ้าย
                            แท็บล่างขวาสุด = รูปโปรไฟล์เพจ (ไม่ใช่เมนู)

ตัวอ่านเดิมกดแท็บล่างขวาสุดเสมอ ในโหมดเพจจึงไปเปิดหน้าโปรไฟล์แทนเมนู วนอยู่
แบบนั้นจนหมดรอบ — **เขียนตัวตรวจจากหน้าจอที่เห็นครั้งเดียว แล้วคิดว่าทุกสถานะ
หน้าตาเหมือนกัน**

## ตัวตรวจในไฟล์นี้จึงใช้ "ของที่มีเฉพาะตอนเป็นจริง" สองตัว คนละสถานะ

    เป็นเพจ X อยู่ไหม   เปิดหน้าเพจ X แล้วต้องเจอ **ช่องเขียนโพสต์ + ปุ่มแอดมิน**
                        ถ้าไม่ได้เป็น จะเห็นปุ่ม "ติดตาม" แทน (มุมคนนอก)
    ไม่ได้เป็นเพจนั้น    เมนูใช้งานได้ตามปกติ → อ่านชื่อ **เหนือเส้น "ทางลัดของคุณ"**

ทั้งคู่เป็นการ "หาของที่มีเฉพาะตอนสำเร็จ" ไม่ใช่ "ไม่เจอของที่แปลว่าล้ม"
และ **"อ่านไม่ได้" คืนค่าว่าง ซึ่งไม่เท่ากับ "ไม่ใช่"** — คนเรียกต้องหยุด ไม่ใช่เดา
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import time
from pathlib import Path

FB = "com.facebook.katana"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# รหัสเพจที่เครื่องนี้ดูแล — แก้ได้ที่ data/fb_pages.json ไม่ต้องแก้โค้ด
PAGES_FILE = Path(__file__).resolve().parent / "data" / "fb_pages.json"
DEFAULT_PAGES = {"ไท คัดมาแล้วครับ": "301294969734492"}

SHORTCUT_MARKS = ("ทางลัดของคุณ", "Your shortcuts", "Your Shortcuts")
COMPOSER_MARKS = ("คุณกำลังคิดอะไรอยู่", "What's on your mind")
ADMIN_MARKS = ("แดชบอร์ด", "ลงโฆษณา", "Dashboard", "Advertise")
GUEST_MARKS = ("ติดตาม", "Follow")

APP_START = 17.0
PAGE_LOAD = 14.0
MENU_WAIT = 9.0
SHEET_WAIT = 9.0
AFTER_SWITCH = 32.0
VERIFY_TRIES = 4
VERIFY_GAP = 12.0


class ProfileError(RuntimeError):
    """สลับไม่สำเร็จ หรือพิสูจน์ผลไม่ได้ — **ทั้งสองอย่างต้องหยุด ห้ามเดาต่อ**"""


def pages() -> dict:
    try:
        data = json.loads(PAGES_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict) and data:
            return {str(k): str(v) for k, v in data.items()}
    except (OSError, ValueError):
        pass
    return dict(DEFAULT_PAGES)


# ------------------------------------------------------------------ พื้นฐาน

def sh_for(adb: str, serial: str):
    def run(*args, timeout: float = 120.0):
        return subprocess.run([adb, "-s", serial, *args], capture_output=True,
                              text=True, encoding="utf-8", errors="replace",
                              creationflags=NO_WINDOW, timeout=timeout)
    return run


def dump(sh) -> str:
    sh("shell", "uiautomator dump /sdcard/fb_profile.xml")
    xml = sh("shell", "cat /sdcard/fb_profile.xml").stdout or ""
    sh("shell", "rm -f /sdcard/fb_profile.xml")
    return xml


def rows(xml: str) -> list[tuple[str, int, int, int]]:
    """(ข้อความ, x กลาง, y กลาง, y บน)"""
    out = []
    for m in re.finditer(r'text="([^"]+)"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', xml):
        text = m.group(1).strip()
        if text:
            x1, y1, x2, y2 = (int(v) for v in m.groups()[1:])
            out.append((text, (x1 + x2) // 2, (y1 + y2) // 2, y1))
    return out


def wake(sh, log=lambda _m: None) -> bool:
    """ปลุกจอแล้ว **ยืนยันจาก dumpsys** ไม่ใช่สั่งแล้วเชื่อว่าติด"""
    for _ in range(3):
        sh("shell", "input", "keyevent", "KEYCODE_WAKEUP")
        time.sleep(1.2)
        sh("shell", "input", "swipe", "540", "1800", "540", "700", "250")
        time.sleep(1.4)
        state = sh("shell", "dumpsys window | grep -E 'mAwake=|mDreamingLockscreen='").stdout or ""
        if "mAwake=true" in state and "mDreamingLockscreen=false" in state:
            return True
    log("  ⚠️ ปลุกจอไม่ขึ้น")
    return False


def _open_page(sh, page_id: str) -> str:
    sh("shell", "am", "start", "-a", "android.intent.action.VIEW",
       "-d", f"fb://page/{page_id}", "-p", FB)
    time.sleep(PAGE_LOAD)
    return dump(sh)


# ------------------------------------------------- ตัวตรวจที่ 1: เป็นเพจนี้อยู่ไหม

def acting_as_page(sh, page_id: str, log=lambda _m: None) -> bool | None:
    """เรากำลังเป็นเพจนี้อยู่ไหม — True / False / None (อ่านไม่ได้)

    **ตรวจจากของที่มีเฉพาะตอนเป็นเพจนั้น** คือช่องเขียนโพสต์บนหน้าเพจ
    บวกปุ่มแอดมิน ส่วนคนนอกจะเห็นปุ่ม "ติดตาม" แทน

    None สำคัญ — แปลว่าหน้าไม่โหลด/อ่านไม่ออก ไม่ใช่ "ไม่ใช่"
    """
    xml = _open_page(sh, page_id)
    if len(xml) < 3000:
        log("  หน้าเพจโหลดไม่ขึ้น")
        return None
    mine = any(m in xml for m in COMPOSER_MARKS) and any(m in xml for m in ADMIN_MARKS)
    guest = any(m in xml for m in GUEST_MARKS)
    if mine:
        return True
    if guest:
        return False
    log("  หน้าเพจไม่มีทั้งช่องเขียนและปุ่มติดตาม — ยังตัดสินไม่ได้")
    return None


# ------------------------------------------------- ตัวตรวจที่ 2: อ่านชื่อจากเมนู

def _nav_cells(xml: str) -> list[tuple[int, int, int, int]]:
    """ช่องที่กดได้ซึ่งติดขอบล่างจอ = แถบนำทาง"""
    height = max((int(m) for m in re.findall(r'bounds="\[\d+,\d+\]\[\d+,(\d+)\]"', xml)),
                 default=0)
    if not height:
        return []
    cells = []
    for m in re.finditer(r'<node[^>]*clickable="true"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', xml):
        x1, y1, x2, y2 = (int(v) for v in m.groups())
        if y2 > height - 170 and y1 > height - 240 and (x2 - x1) < 300:
            cells.append((x1, y1, x2, y2))
    return sorted(cells)


def read_menu_name(xml: str) -> str:
    """ชื่อโปรไฟล์ที่ใช้อยู่ อ่านจากผังจอของ **หน้าเมนู** — "" เมื่ออ่านไม่ได้

    ยึดกับโครง ไม่ใช่ลำดับ: ชื่อที่ใช้อยู่จะอยู่ **เหนือเส้นแบ่ง "ทางลัดของคุณ"**
    เสมอ ส่วนชื่อที่อยู่ใต้เส้นเป็นแค่ทางลัด

    **นี่คือจุดที่ด่านเดิมพัง** — ของเดิมเช็คแค่ว่า "ชื่อนี้โผล่บนจอไหม" แต่ใน
    หน้าเมนูชื่อเพจโผล่สองที่เสมอ (หัวเมนู + ทางลัด) จึงตอบว่าใช่ได้ทั้งตอน
    ใช้โปรไฟล์นั้นจริงและตอนไม่ได้ใช้ (กติกาข้อ 2.3.1)
    """
    got = rows(xml)
    marks = [r[3] for r in got if any(m in r[0] for m in SHORTCUT_MARKS)]
    if not marks:
        return ""
    cut = min(marks)
    above = [r for r in got if r[3] < cut and len(r[0]) > 2
             and not r[0].isdigit() and r[0] not in ("เมนู", "Menu")]
    return max(above, key=lambda r: r[3])[0] if above else ""


def menu_name(sh, log=lambda _m: None) -> str:
    """ชื่อโปรไฟล์จากหน้าเมนู — "" เมื่ออ่านไม่ได้

    ใช้ได้เฉพาะตอน **ไม่ได้** อยู่โหมดเพจแบบมืออาชีพ (โหมดนั้นเมนูย้ายไปบนซ้าย)
    ตัวเรียกจึงต้องตรวจเพจก่อนเสมอ
    """
    for attempt in range(1, 4):
        sh("shell", "am", "force-stop", FB)
        time.sleep(2.0)
        sh("shell", "monkey", "-p", FB, "-c", "android.intent.category.LAUNCHER", "1")
        time.sleep(APP_START)
        sh("shell", "am", "start", "-a", "android.intent.action.VIEW", "-d", "fb://feed", "-p", FB)
        time.sleep(7.0)
        xml = dump(sh)
        cells = _nav_cells(xml)
        if not cells:
            log(f"  (เมนู รอบ {attempt}) ไม่เจอแถบนำทางล่าง")
            continue
        last = cells[-1]
        sh("shell", "input", "tap", str((last[0] + last[2]) // 2), str((last[1] + last[3]) // 2))
        time.sleep(MENU_WAIT)
        menu = dump(sh)
        if not any(m in menu for m in SHORTCUT_MARKS):
            log(f"  (เมนู รอบ {attempt}) กดแล้วยังไม่ใช่หน้าเมนู")
            continue
        name = read_menu_name(menu)
        if not name:
            log(f"  (เมนู รอบ {attempt}) ไม่เจอชื่อเหนือเส้นแบ่ง")
            continue
        return name
    return ""


# ------------------------------------------------------------------ ใครอยู่

def whoami(adb: str, serial: str, log=lambda _m: None) -> str:
    """โปรไฟล์ที่แอปใช้อยู่ — "" เมื่ออ่านไม่ได้ (**ไม่ใช่ "ไม่มี"**)"""
    sh = sh_for(adb, serial)
    for name, pid in pages().items():
        answer = acting_as_page(sh, pid, log)
        if answer is True:
            log(f"  โปรไฟล์ที่ใช้อยู่: {name} (จากช่องเขียนโพสต์บนหน้าเพจ)")
            return name
    name = menu_name(sh, log)
    log(f"  โปรไฟล์ที่ใช้อยู่: {name or '(อ่านไม่ได้)'} (จากเมนู)")
    return name


# ------------------------------------------------------------------ สลับ

def _reach_sheet(sh, now: str, log) -> dict:
    """เปิดรายการสลับโปรไฟล์ — คืน {ชื่อ: (x, y)}

    ปุ่ม ⌄ มีเฉพาะบน "หน้าโปรไฟล์ของตัวเราเอง" จึงต้องไปที่นั่นก่อน
      เป็นเพจอยู่  → เปิดหน้าเพจนั้นตรงๆ
      ไม่ใช่เพจ    → เมนู → แตะชื่อบนหัวเมนู (พาไปหน้าโปรไฟล์ปัจจุบัน)
    """
    known = pages()
    if now in known:
        xml = _open_page(sh, known[now])
    else:
        xml = None
        for attempt in range(1, 3):
            sh("shell", "am", "force-stop", FB)
            time.sleep(2.0)
            sh("shell", "monkey", "-p", FB, "-c", "android.intent.category.LAUNCHER", "1")
            time.sleep(APP_START)
            sh("shell", "am", "start", "-a", "android.intent.action.VIEW", "-d", "fb://feed", "-p", FB)
            time.sleep(7.0)
            cells = _nav_cells(dump(sh))
            if not cells:
                continue
            last = cells[-1]
            sh("shell", "input", "tap", str((last[0] + last[2]) // 2), str((last[1] + last[3]) // 2))
            time.sleep(MENU_WAIT)
            menu = dump(sh)
            spot = [r for r in rows(menu) if r[0] == now]
            if not spot:
                continue
            sh("shell", "input", "tap", str(spot[0][1]), str(spot[0][2]))
            time.sleep(SHEET_WAIT + 3)
            xml = dump(sh)
            break
        if xml is None:
            raise ProfileError("ไปหน้าโปรไฟล์ปัจจุบันไม่ได้ — เปิดรายการสลับไม่ได้")

    head = [r for r in rows(xml) if r[0] == now and r[3] < 950]
    if not head:
        raise ProfileError(f"อยู่หน้าโปรไฟล์แล้วแต่ไม่เจอชื่อ {now} บนหัวหน้า")
    anchor = head[0]
    chevron = None
    for m in re.finditer(r'<node[^>]*clickable="true"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', xml):
        x1, y1, x2, y2 = (int(v) for v in m.groups())
        if anchor[3] - 45 <= (y1 + y2) // 2 <= anchor[3] + 110 and x1 > anchor[1]:
            chevron = ((x1 + x2) // 2, (y1 + y2) // 2)
            break
    if chevron is None:
        raise ProfileError("ไม่เจอปุ่ม ⌄ ข้างชื่อโปรไฟล์")
    sh("shell", "input", "tap", str(chevron[0]), str(chevron[1]))
    time.sleep(SHEET_WAIT)
    sheet = dump(sh)
    found = {}
    for text, cx, cy, _ in rows(sheet):
        if len(text) > 2 and text not in ("ไปที่ศูนย์บัญชี", "เพจ", "Meta"):
            found.setdefault(text, (cx, cy))
    if len(found) < 2:
        raise ProfileError("เปิดรายการโปรไฟล์แล้วเจอไม่ถึง 2 ชื่อ")
    log("  รายการโปรไฟล์: " + " · ".join(found))
    return found


def same_name(a: str, b: str) -> bool:
    """ชื่อเดียวกันไหม — **ไม่สนตัวพิมพ์ใหญ่เล็กและช่องว่างหัวท้าย**

    จำเป็นเพราะชื่อเดียวกันถูกเขียนคนละแบบในสองที่: ทะเบียนเครื่องจด
    "Squishy cute club" ส่วนแอปบนจอเขียน "Squishy Cute Club" ถ้าเทียบตรงตัว
    ด่านจะสรุปว่า "อยู่ผิดโปรไฟล์" แล้วสั่งสลับไปหาชื่อที่ไม่มีอยู่จริง
    จบด้วยล้มทั้งที่เครื่องอยู่ถูกที่อยู่แล้ว
    """
    return (a or "").strip().casefold() == (b or "").strip().casefold()


def switch(adb: str, serial: str, want: str, log=lambda _m: None,
           now: str = "") -> str:
    """สลับไป `want` แล้ว**ยืนยันว่าเปลี่ยนจริง** — ไม่สำเร็จโยน ProfileError

    `now` = โปรไฟล์ปัจจุบันที่คนเรียก**อ่านมาแล้ว** ส่งมาได้เพื่อไม่ต้องอ่านซ้ำ
    การอ่านหนึ่งครั้งกินเวลาราวหนึ่งนาที (ต้องปิดแอป เปิดใหม่ แล้วเปิดเมนู)
    งานที่ต้องรู้ทางกลับอยู่แล้วจึงไม่ควรเสียเวลาไปฟรีๆ สองรอบ
    """
    sh = sh_for(adb, serial)
    now = (now or "").strip() or whoami(adb, serial, log)
    if not now:
        raise ProfileError("อ่านโปรไฟล์ปัจจุบันไม่ได้ — ไม่สลับ เพราะจะไม่รู้ทางกลับ")
    if same_name(now, want):
        log(f"  อยู่ที่ {now} อยู่แล้ว")
        return now

    log(f"  สลับ {now} → {want}")
    found = _reach_sheet(sh, now, log)
    # ใช้ชื่อ **ตามที่แอปสะกด** ไม่ใช่ตามที่คนเรียกมา — ปุ่มบนจอมีชื่อเดียว
    target = next((k for k in found if same_name(k, want)), "")
    if not target:
        raise ProfileError(f"ไม่มีโปรไฟล์ {want} บนเครื่องนี้ (มี: {', '.join(found)})")
    sh("shell", "input", "tap", str(found[target][0]), str(found[target][1]))
    time.sleep(AFTER_SWITCH)

    for attempt in range(1, VERIFY_TRIES + 1):
        got = whoami(adb, serial, log)
        if same_name(got, want):
            log(f"  ✅ ยืนยันแล้วว่าอยู่ที่ {want} (ตรวจรอบที่ {attempt})")
            return got
        log(f"  ยังไม่ใช่ (ได้ {got or 'อ่านไม่ได้'}) — รอ {VERIFY_GAP:.0f} วิแล้วตรวจใหม่")
        time.sleep(VERIFY_GAP)
    raise ProfileError(
        f"สั่งสลับไป {want} แล้วยืนยันไม่ได้ — เครื่องอาจอยู่โปรไฟล์ไหนก็ได้ "
        "ห้ามโพสต์ต่อ ต้องเข้าไปดูที่เครื่อง")


def require(adb: str, serial: str, want: str, log=lambda _m: None,
            now: str = "") -> str:
    """ด่านก่อนโพสต์ — ต้องอยู่โปรไฟล์นี้ให้ได้ ไม่งั้นโยน"""
    return switch(adb, serial, want, log, now)


# ----------------------------------------------------- ด่านสำหรับคนที่มีแค่ serial

def adb_path() -> str:
    """หา adb.exe แบบเดียวกับ app.py — ตัวที่เราคุมได้มาก่อน PATH เสมอ

    บทเรียนเดิมของโปรเจกต์: PATH เคยมี adb เก่าค้างแล้วสั่งมือถือไม่ได้
    """
    here = Path(__file__).resolve().parent
    for candidate in (
        here / "tools/platform-tools/adb.exe",
        Path("C:/project/2.Auto gen Video/7.web app/tools/platform-tools/adb.exe"),
        Path.home() / "AppData/Local/Android/Sdk/platform-tools/adb.exe",
        Path("C:/platform-tools/adb.exe"),
    ):
        if candidate.is_file():
            return str(candidate)
    found = shutil.which("adb")
    if found:
        return found
    raise ProfileError("ไม่พบ adb.exe — จึงตรวจโปรไฟล์ไม่ได้ (ยังไม่ได้ตรวจ ไม่ใช่ผ่าน)")


def guard(serial: str, want: str, log=lambda _m: None, now: str = "") -> str:
    """ด่านก่อนโพสต์ สำหรับคนเรียกที่มีแค่ serial — หา adb ให้เอง

    **ไม่รู้ว่าเครื่องไหน หรือไม่รู้ว่าต้องเป็นใคร = โยนทิ้ง ห้ามเดา**
    (กติกาข้อ 8: เดาเครื่องผิดแล้วโพสต์ออกในนามผิด กู้ไม่ได้ ส่วนล้มพร้อม
    เหตุผลเสียแค่เวลากดใหม่)
    """
    serial = (serial or "").strip()
    want = (want or "").strip()
    if not serial:
        raise ProfileError("ด่านตรวจโปรไฟล์ต้องรู้ว่าเครื่องไหน แต่ไม่ได้บอก serial มา")
    if not want:
        raise ProfileError(
            "ไม่รู้ว่าเครื่องนี้ต้องโพสต์ในนามใคร — ไปผูกบัญชีก่อนด้วย "
            f"`python devices.py account {serial} \"<ชื่อโปรไฟล์>\"`")
    return require(adb_path(), serial, want, log, now)
