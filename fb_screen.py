"""ดับจอมือถือตอนไม่มีงาน แล้วปลุกก่อนงานเริ่ม

**ทำไมต้องมี — วัดของจริง 18 ส.ค. 2026 เครื่อง 7a95129e**

    stay_on_while_plugged_in = 15    เสียบชาร์จแล้ว "ห้ามจอดับ" ทุกแบบ
    จอเปิดค้างมาแล้ว                  2 วัน 14 ชั่วโมง ไม่ดับเลยสักครั้ง
    อุณหภูมิแบต                       50.0 °C
    แบตเตอรี่                          15% ทั้งที่เสียบ AC อยู่

เป็นวงจรที่กัดตัวเอง: จอเปิดตลอด → ร้อน → ระบบหรี่กระแสชาร์จเพื่อกันแบตพัง →
แบตค้างต่ำทั้งที่เสียบอยู่ → ยิ่งทำงานยิ่งร้อน  เกิน 45 °C ค้างนานๆ แบตเสื่อมถาวร

**ทำได้เพราะเครื่องนี้ไม่มีรหัสล็อกหน้าจอ** (`lockscreen.password_type = null`
· `strongAuthRequired = 0`) ปลุกแล้วปัดทีเดียวใช้ได้เลย  ถ้าวันไหนตั้ง PIN ขึ้นมา
`wake()` จะปลุกได้แต่ผ่านล็อกไม่ได้ — จึง **ยืนยันด้วย uiautomator ว่าแตะจอได้จริง**
ไม่ใช่เชื่อแค่ว่า mWakefulness=Awake (จอสว่างแต่ติดหน้าล็อกก็ Awake เหมือนกัน)

**เวลาที่ใช้ วัดกับเครื่องจริงแล้ว**  ดับจอ 1.35 วิ · ปลุกจอ 1.33 วิ

ไฟล์นี้ฉีดคำสั่งเข้ามาจากข้างนอกได้ (`shell`) จึงทดสอบได้โดยไม่แตะ ADB จริง
"""

from __future__ import annotations

import re
import subprocess
import time

import studio_shared

# ไม่มีงานและไม่มีใครแตะเครื่องนานเท่านี้ (วินาที) = ดับจอ
IDLE_SECONDS = 180
# ปลุกจอล่วงหน้าก่อนงานตั้งเวลาจะเริ่ม (วินาที)
PREWAKE_SECONDS = 60
# ห้ามดับถ้ามีงานตั้งเวลาจะถึงภายในเท่านี้ (วินาที) — ดับแล้วปลุกทันทีคือเสียเปล่า
KEEP_AWAKE_BEFORE = 300
CMD_TIMEOUT = 20.0

# แอปที่สั่งปิดถาวร — ของผู้ใช้ที่ไม่เกี่ยวกับงานโพสต์แต่ค้างกินแรมอยู่เบื้องหลัง
# (วัดเมื่อ 18 ส.ค.: Netflix 238 MB · Line 284 MB · ChatGPT 152 MB ·
#  Bolt ผู้โดยสาร 152 MB · Bolt คนขับ 139 MB · Notion 153 MB รวมราว 1.1 GB)
#
# ชุดที่สอง เพิ่ม 25 ส.ค. 2569 หลังมือถือขึ้น "หน่วยความจำไม่พอ" ตอนเปิดแอป
# วัดของจริงเครื่อง REDMI 15C - โพสต์ 2 (แรม 5.52 GB ซึ่งน้อย):
#   Google ค้นหา/ผู้ช่วย 189 · Play Store 132 · กล้อง 108 ·
#   ภาพพื้นหลังหมุนเวียน Xiaomi 70 · ตัวจัดการไฟล์ Google 40 · สภาพอากาศ 17
#   รวมราว 556 MB
#
# **เจ้าของสั่งห้ามแตะ Shopee** (577 MB) เพราะเป็นแอปที่ใช้ทำงานจริง —
# ชุดนี้จึงเลือกมาให้คืนแรมได้พอๆ กันโดยไม่ต้องแตะมันเลย
#
# **ที่จงใจไม่ใส่**
#   com.google.android.apps.walletnfcrel  Google Wallet — เป็นแอปจ่ายเงิน
#                                         ไม่ใช่วอลเปเปอร์อย่างที่ชื่อชวนเข้าใจผิด
#   com.miui.miwallpaper                  ตัววาดภาพพื้นหลัง ปิดแล้วพื้นหลังอาจดำ
#   com.google.android.inputmethod.latin  คีย์บอร์ด — บอทต้องใช้พิมพ์แคปชัน
#   com.google.android.apps.messaging     ข้อความ SMS — เผื่อรหัสยืนยันตัวตน
IDLE_APPS = (
    "com.netflix.mediaclient",
    "jp.naver.line.android",
    "com.openai.chatgpt",
    "ee.mtakso.client",
    "ee.mtakso.driver",
    "notion.id",
    "com.google.android.googlequicksearchbox",
    "com.android.vending",
    "com.android.camera",
    "com.miui.android.fashiongallery",
    "com.google.android.apps.nbu.files",
    "com.miui.weather2",
)

_WAKE_RE = re.compile(r"mWakefulness=(\w+)")
# ต้องยึด `^\s*lastUserActivityTime=` ให้แน่น — ในผลเดียวกันมี
# `lastUserActivityTimeNoChangeLights=` กับ `mLastUserActivityTime(excludingAttention)=`
# ปนอยู่ด้วย จับผิดตัวแล้วจะได้เวลาที่ไม่ใช่การแตะจอจริง
_IDLE_RE = re.compile(r"^\s*lastUserActivityTime=\d+\s*\((\d+) ms ago\)", re.M)


def make_shell(serial: str, adb: str = "adb"):
    def call(command: str) -> str:
        done = subprocess.run(
            [adb, "-s", serial, "shell", command],
            capture_output=True, timeout=CMD_TIMEOUT,
            creationflags=studio_shared.NO_WINDOW,
        )
        return done.stdout.decode("utf-8", errors="replace")
    return call


# ------------------------------------------------------------------ อ่านสถานะ

def screen_size(shell, fallback: tuple[int, int] = (1080, 2400)) -> tuple[int, int]:
    """(กว้าง, สูง) ของจอเครื่องนี้ — อ่านไม่ออกใช้จออ้างอิง ดีกว่าล้มทั้งงาน"""
    try:
        found = re.search(r"(\d+)x(\d+)", shell("wm size"))
        if found:
            return int(found.group(1)), int(found.group(2))
    except Exception:
        pass
    return fallback


def wakefulness(shell) -> str:
    """Awake · Dozing · Asleep · "" ถ้าอ่านไม่ออก"""
    try:
        found = _WAKE_RE.search(shell("dumpsys power | grep mWakefulness="))
    except Exception:
        return ""
    return found.group(1) if found else ""


def is_awake(shell) -> bool:
    return wakefulness(shell) == "Awake"


def idle_seconds(shell) -> float:
    """ไม่มีการแตะจอมากี่วินาทีแล้ว — อ่านไม่ออกคืน -1

    ตัวนี้นับ **ทั้งนิ้วผู้ใช้และ `input tap` ของบอท** เพราะทั้งคู่เป็น input event
    เหมือนกันในสายตาของ PowerManager — จึงใช้ตัวเดียวคุมได้ทั้งสองเรื่อง
    ไม่ต้องแยกนับว่า "บอทใช้อยู่ไหม" กับ "ผู้ใช้ถือเครื่องอยู่ไหม"
    """
    try:
        found = _IDLE_RE.search(shell("dumpsys power"))
    except Exception:
        return -1.0
    return int(found.group(1)) / 1000.0 if found else -1.0


def on_lockscreen(shell) -> bool | None:
    """ติดหน้าล็อกอยู่ไหม — None = อ่านไม่ออก (**ไม่ใช่ "ไม่ติด"**)

    **เพิ่ม 22 ก.ย. 2569 เพราะทั้ง `is_awake` และ `can_touch` แยกไม่ออก**

        is_awake   หน้าล็อกไฟจอติดอยู่ → ตอบ "ตื่น"          ✗
        can_touch  หน้าล็อกก็มีผังจอของมันเอง → ตอบ "แตะได้"  ✗

    วัดกับ W4FYYPYTLFYLIFHM 22 ก.ย. 13:2x ตอนเครื่องล็อกอยู่จริง:
    `is_awake=True · can_touch=True · mDreamingLockscreen=true`
    ตัวที่ **มีเฉพาะตอนใช้งานได้จริง** จึงมีตัวเดียวคือ `mDreamingLockscreen=false`
    """
    try:
        text = shell("dumpsys window | grep mDreamingLockscreen=")
    except Exception:
        return None
    if "mDreamingLockscreen=false" in text:
        return False
    if "mDreamingLockscreen=true" in text:
        return True
    return None


def can_touch(shell) -> bool:
    """แตะจอแล้วมีผลจริงไหม — ต้อง **อ่านผังจอได้ และไม่ติดหน้าล็อก**

    เดิมเช็คแค่ว่าอ่านผังจอได้ ซึ่งหน้าล็อกก็ผ่าน (มันมีผังจอของตัวเอง)
    ทำให้ทางลัดของ `wake()` คืน True แล้วข้ามการปัดปลดล็อกทั้งหมด
    """
    if on_lockscreen(shell) is not False:
        return False
    try:
        return "<hierarchy" in shell(
            "uiautomator dump /sdcard/wake-probe.xml >/dev/null 2>&1; "
            "cat /sdcard/wake-probe.xml 2>/dev/null | head -c 200"
        )
    except Exception:
        return False


# ------------------------------------------------------------------ สั่งงาน

def wake(shell, log=None, tries: int = 2) -> bool:
    """ปลุกจอ + ปัดหน้าล็อกออก แล้ว**ยืนยันว่าแตะจอได้จริง**

    ยืนยันสำคัญกว่าการสั่ง — ถ้าปลุกไม่ขึ้นแล้วปล่อยงานเดินต่อ บอทจะไล่กด
    พิกัดบนจอที่ดับอยู่ครบทุกขั้นแล้วรายงานว่า "โพสต์แล้ว" ทั้งที่ไม่มีอะไรเกิดขึ้น
    """
    say = log or (lambda _: None)
    # ทางลัดตอนจอ**ใช้งานได้อยู่แล้ว** — ไม่ยิง keyevent ซ้ำ
    #
    # ห้ามยิง keyevent มั่วตอนจอใช้งานได้อยู่ ทางนี้ถูกเรียกทุกครั้งที่สร้าง Phone
    # ซึ่งเกิดกลางงานได้ การกดปุ่มแทรกตอนแอปกำลังเปิดหน้าอื่นค้างไว้คือทำงานพัง
    #
    # **แต่ "ตื่น" อย่างเดียวไม่พอ** (แก้ 22 ก.ย. 2569) — ของเดิมเช็คแค่
    # `is_awake()` ซึ่ง **หน้าล็อกก็ตอบว่าตื่น** เพราะไฟจอติดอยู่จริง ทางลัดจึง
    # คืน True แล้วข้ามการปัดปลดล็อกทั้งหมด ผลคือทุกงานที่สร้าง Phone ตอนเครื่อง
    # ติดหน้าล็อก จะไล่แตะพิกัดลงบนหน้าล็อกทีละขั้นโดยไม่มีอะไรฟ้อง
    #
    # เจอจริง 22 ก.ย. 13:07 บน W4FYYPYTLFYLIFHM — ตัวอ่านโปรไฟล์กดเปิดเมนู
    # 3 รอบแล้วรายงานว่า "อ่านไม่ได้" ทั้งที่แอปไม่มีอะไรผิด ภาพหน้าจอยืนยันว่า
    # เครื่องค้างอยู่ที่หน้าล็อกตลอด — ตรงกับตารางในกติกาข้อ 2.3.1 บรรทัด
    # "จอมือถือพร้อมใช้ไหม / ไฟจอติดไหม / ติดอยู่แล้วแต่ยังล็อกหน้าจอ" เป๊ะ
    #
    # `can_touch()` เป็นตัวเดียวกับที่ทางช้าใช้ตัดสินว่าสำเร็จ และ**ไม่ยิง
    # keyevent สักตัว** (แค่อ่านผังจอ) ข้อกังวลเดิมจึงยังอยู่ครบ
    try:
        if is_awake(shell) and can_touch(shell):
            return True
    except Exception:
        pass
    for attempt in range(1, tries + 1):
        try:
            if not is_awake(shell):
                shell("input keyevent 224")        # KEYCODE_WAKEUP (ไม่ใช่ 26 ที่สลับไปมา)
                time.sleep(1.2)
            shell("input keyevent 82")             # ปัดหน้าล็อกออก (เครื่องนี้ไม่มี PIN)
            time.sleep(0.6)
            # เครื่องบางรุ่นไม่ยอมปลดด้วยปุ่ม 82 ต้องปัดขึ้นจริงๆ
            # **พิกัดคิดจากขนาดจอของเครื่องนั้น ห้ามฝังตาย** (กติกาข้อ 2.7)
            # ของเดิมที่อื่นฝัง y=1800 ไว้ ซึ่งอยู่นอกจอของเครื่องสูง 1600 → ปัดไม่ติด
            if on_lockscreen(shell) is not False:
                width, height = screen_size(shell)
                shell(f"input swipe {width // 2} {int(height * 0.85)} "
                      f"{width // 2} {int(height * 0.25)} 250")
                time.sleep(1.0)
            if can_touch(shell):
                if attempt > 1:
                    say(f"  ปลุกจอสำเร็จรอบที่ {attempt}")
                return True
        except Exception as error:
            say(f"  ปลุกจอไม่สำเร็จ: {error}")
        time.sleep(0.8)
    say("  ⚠️ ปลุกจอไม่ขึ้น — จออาจติดหน้าล็อกที่ต้องใส่รหัส")
    return False


def sleep_screen(shell, log=None) -> bool:
    """ดับจอ — คืน True เมื่อยืนยันแล้วว่าดับจริง"""
    say = log or (lambda _: None)
    try:
        mode = wakefulness(shell)
        # **อ่านไม่ออก ≠ ดับอยู่แล้ว** — ถ้าเหมารวมกัน ADB หลุดจะถูกรายงานว่า
        # "ดับจอสำเร็จ" ทั้งที่จอยังสว่างค้างอยู่ แล้วไม่มีใครรู้ว่าไม่ได้ดับจริง
        if not mode:
            say("  อ่านสถานะจอไม่ได้ — ยังไม่สั่งดับ")
            return False
        if mode != "Awake":
            return True                            # ดับอยู่แล้ว ไม่ต้องสั่งซ้ำ
        shell("input keyevent 223")                # KEYCODE_SLEEP
        time.sleep(1.2)
        done = not is_awake(shell)
        say("  ดับจอมือถือแล้ว" if done else "  สั่งดับจอแล้วแต่จอยังสว่างอยู่")
        return done
    except Exception as error:
        say(f"  ดับจอไม่สำเร็จ: {error}")
        return False


def disable_stay_on(shell, log=None) -> bool:
    """เลิก "เสียบชาร์จแล้วห้ามจอดับ" — ไม่ปิดตัวนี้ ดับไปเดี๋ยวก็ติดกลับมาเอง"""
    say = log or (lambda _: None)
    try:
        now = (shell("settings get global stay_on_while_plugged_in") or "").strip()
        if now in ("0", "null", ""):
            return True
        shell("settings put global stay_on_while_plugged_in 0")
        say(f"  ปิดค่า stay_on_while_plugged_in (เดิม {now}) แล้ว")
        return True
    except Exception as error:
        say(f"  ปิด stay_on_while_plugged_in ไม่สำเร็จ: {error}")
        return False


def stop_idle_apps(shell, log=None, packages=IDLE_APPS) -> list[str]:
    """ปิดแอปของผู้ใช้ที่ค้างกินแรมอยู่ — คืนรายชื่อที่สั่งสำเร็จ"""
    say = log or (lambda _: None)
    done = []
    for package in packages:
        try:
            shell(f"am force-stop {package}")
            done.append(package)
        except Exception as error:
            say(f"  ปิด {package} ไม่สำเร็จ: {error}")
    if done:
        say(f"  ปิดแอปที่ไม่เกี่ยวกับงาน {len(done)} ตัว")
    return done


def status_text(shell) -> str:
    """สรุปสถานะจอไว้แปะใน /health"""
    mode = wakefulness(shell) or "?"
    idle = idle_seconds(shell)
    label = {"Awake": "🔆 จอเปิดอยู่", "Dozing": "🌙 จอดับอยู่",
             "Asleep": "🌙 จอดับอยู่"}.get(mode, f"❓ อ่านไม่ออก ({mode})")
    if idle < 0:
        return f"📱 <b>จอมือถือ</b>\n   {label}"
    return (f"📱 <b>จอมือถือ</b>\n   {label} · ไม่มีใครแตะมา "
            f"{idle / 60:.0f} นาที (ดับเมื่อครบ {IDLE_SECONDS // 60} นาที)")
