"""สมุดผลลัพธ์ของคลิป — ลงไปแล้วมีคนดูเท่าไร

**เจ้าของสั่ง 11 ก.ย. 2569** หลังผมชี้ว่าทั้งระบบวัดแต่ "ลงไปกี่ใบ"

ตอนนั้นตัวเลขคือ ใบงาน 468 ใบ · ลงครบสาย 8 ใบ · และในแผงสินค้า TikTok
ของคลิปที่เพิ่งลงเห็น **คำสั่งซื้อ 0 · CTR 0% · เพิ่มลงรถเข็น 0**

ถ้าตัวเลขพวกนั้นยังเป็น 0 ต่อไป การเร่งให้ลงได้ 300 ใบคือการทำของที่ไม่มีคนซื้อ
เร็วขึ้น 300 เท่า — **ต้องรู้ก่อนว่าคลิปแบบไหนมีคนดู แล้วค่อยทุ่มแรงไปทางนั้น**

---

## สิ่งที่ตัวนี้ทำ

อ่าน **ยอดเล่นของคลิปในโปรไฟล์ตัวเอง** แล้วจดไว้พร้อมเวลา อ่านซ้ำได้เรื่อยๆ
จะได้เห็นว่าคลิปไหนวิ่ง คลิปไหนนิ่ง

## ทำไมอ่านตัวเลข ไม่อ่านตัวหนังสือ

วัดจริง 11 ก.ย.: หน้า TikTok ส่งผังจอมาแต่ **อ่านชื่อปุ่มได้ 0 คำ** ต้องใช้
ตัวอ่านจากภาพ ซึ่งอ่านภาษาไทยได้บ้างไม่ได้บ้าง **แต่อ่านเลขอารบิกแม่นเสมอ**
ยอดเล่นเป็นเลขล้วน (`0` `39` `1.2K`) จึงเป็นค่าที่เชื่อถือได้ที่สุดบนหน้านั้น

## ข้อจำกัดที่ต้องรู้ก่อนใช้ตัวเลข

ตารางคลิปเรียง **ใหม่สุดขึ้นก่อน** ตัวนี้จึงจับคู่ช่องที่ N กับคลิปที่เราลงเป็น
ลำดับที่ N นับจากใหม่สุด — **ถ้าเจ้าของโพสต์เองด้วยมือ ลำดับจะเคลื่อน**

จึงมีด่านกันไว้: อ่านได้กี่ช่องก็จับคู่แค่นั้น และถ้าจำนวนไม่สมเหตุสมผล
จะ **ไม่จดเลยแล้วบอกว่าทำไม** ดีกว่าจดตัวเลขที่ผูกผิดคลิป
(กติกาข้อ 2.3.1 — "ยังไม่ได้วัด" ต้องไม่หน้าตาเหมือน "วัดแล้วได้ 0")
"""
from __future__ import annotations

import io
import json
import re
import subprocess
import time
from datetime import datetime
from pathlib import Path

import studio_shared as shared

RESULTS_FILE = shared.DATA_DIR / "clip_results.json"
TIKTOK_PACKAGE = "com.ss.android.ugc.trill"

# ยอดเล่นบนตารางคลิป: "0" "39" "1.2K" "12.5M" — เลขล้วน อาจมีหน่วยย่อท้าย
PLAY_COUNT_RE = re.compile(r"^\d+(?:\.\d+)?[KMBkmb]?$")

# พิกัดที่เทรนไว้บน REDMI 15C (จอ 720×1600)
TAB_PROFILE = (648, 1520)
TAB_VIDEOS = (82, 672)
CHIP_STUDIO = (143, 582)          # ชิป "TikTok Studio" บนหน้าโปรไฟล์
ANALYTICS_ROW = (612, 506)        # แถว "การวิเคราะห์ >" บนหน้า Studio

# ป้ายบนหน้า "การวิเคราะห์" ของ TikTok Studio — ค่าอยู่ **ใต้ป้าย** เสมอ
#
# **ต้องเทียบแบบหลวม** เพราะตัวอ่านภาพทำวรรณยุกต์/สระตกประจำ วัดจริง 11 ก.ย.
#   "ยอดการดูโพสต์"    อ่านได้เป็น "ยอดการดูไพสต์"
#   "ยอดรับชมโปรไฟล์"  อ่านได้เป็น "ยอดรับชมฺโปรไฟล์"
#   "ถูกใจ"            อ่านได้เป็น "ถูก"
STUDIO_FIELDS = {
    "views": ("ยอดการดูโพสต", "ยอดการด"),
    "profile_views": ("ยอดรับชม", "รับชมโปรไฟล"),
    "likes": ("ถูกใจ", "ถูก"),
    "comments": ("ความคิดเห็น", "ความคิด"),
    "shares": ("แชร์",),
}
# ระยะจากป้ายลงมาถึงตัวเลข (วัดจากหน้าจริง: 39–54 จุด)
VALUE_BELOW = (25, 75)
VALUE_SAME_COLUMN = 70


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def to_number(text: str) -> int | None:
    """แปลง "1.2K" เป็น 1200 — คืน None ถ้าไม่ใช่ยอดเล่น"""
    value = str(text or "").strip()
    if not PLAY_COUNT_RE.match(value):
        return None
    scale = {"K": 1_000, "M": 1_000_000,
             "B": 1_000_000_000}.get(value[-1:].upper(), 1)
    try:
        return int(float(value[:-1] if scale > 1 else value) * scale)
    except ValueError:
        return None


# ------------------------------------------------------------ ที่เก็บผลลัพธ์


def read_studio(serial: str, log=print) -> dict:
    """อ่านตัวเลขรวมของบัญชีจากหน้า TikTok Studio (รอบ 7 วัน)

    **ทำไมอ่านระดับบัญชี ไม่ใช่รายคลิป** (ตัดสินใจ 11 ก.ย. 2569)

    ลองจับคู่ยอดวิวรายคลิปมาแล้วสองวิธี **ไม่ผ่านทั้งคู่**

        จับคู่ตามลำดับช่องในตาราง   ถูก 1 จาก 4 — กล่อง "แบบร่าง" แทรกหัวแถว
                                    และตัวอ่านภาพอ่านเลขตกบางช่อง พอตกหนึ่งช่อง
                                    ลำดับที่เหลือเลื่อนผิดทั้งแถว
        จับคู่ด้วยลายนิ้วมือภาพ      ถูก 2 จาก 4 — ฮับ UGREEN สองใบหน้าตา
                                    เกือบเหมือนกัน ระยะห่าง 8–24 บิต ตัดเส้นไม่ได้

    **ตัวเลขที่ผูกผิดคลิปแย่กว่าไม่มีตัวเลข** เพราะพาไปสรุปผิดว่าสินค้าแบบไหน
    มีคนดู ระดับบัญชีไม่มีปัญหานี้เลยเพราะไม่ต้องจับคู่อะไร และตอบคำถามหลัก
    ได้อยู่แล้วว่า *"ที่ลงไปทั้งหมดมีคนดูไหม คนชอบไหม คนตามไหม"*
    """
    import re as _re

    def tap(x: int, y: int, wait: float) -> None:
        subprocess.run(["adb", "-s", serial, "shell", "input", "tap", str(x), str(y)],
                       capture_output=True, timeout=40)
        time.sleep(wait)

    try:
        import numpy as np
        from PIL import Image

        import fb_screen
        import tiktok_publish_bot as bot
        reader = bot.get_thai_ocr()
        if reader is None:
            return {"ok": False, "why": "ตัวอ่านจากภาพใช้ไม่ได้"}

        def shell(command: str) -> str:
            done = subprocess.run(["adb", "-s", serial, "shell", *command.split()],
                                  capture_output=True, timeout=40)
            return done.stdout.decode("utf-8", errors="replace")

        if not fb_screen.wake(shell, log=log):
            return {"ok": False, "why": "ปลุกจอไม่ขึ้น"}

        subprocess.run(["adb", "-s", serial, "shell", "am", "force-stop",
                        TIKTOK_PACKAGE], capture_output=True, timeout=40)
        subprocess.run(["adb", "-s", serial, "shell", "monkey", "-p", TIKTOK_PACKAGE,
                        "-c", "android.intent.category.LAUNCHER", "1"],
                       capture_output=True, timeout=40)
        time.sleep(8)
        tap(*TAB_PROFILE, 4.5)
        tap(*CHIP_STUDIO, 7.0)
        # แถว "การวิเคราะห์ >" บนหน้า Studio — พาไปหน้าตัวเลขละเอียด
        # (กล่องชวนเปิดรับข้อมูลถ้าเด้งมา จะถูกแถวนี้ปิดไปพร้อมกัน
        #  **ห้ามกดปุ่มยืนยันของกล่องนั้น** เพราะเป็นการเปลี่ยนตั้งค่าบัญชี)
        tap(*ANALYTICS_ROW, 6.0)
        png = subprocess.run(["adb", "-s", serial, "exec-out", "screencap", "-p"],
                             capture_output=True, timeout=60).stdout
        shot = Image.open(io.BytesIO(png)).convert("RGB")
        seen = reader.readtext(np.array(shot)) or []
    except Exception as error:                                 # noqa: BLE001
        return {"ok": False, "why": f"{type(error).__name__}: {error}"}

    words = []
    for points, value, score in seen:
        ys = [int(p[1]) for p in points]
        xs = [int(p[0]) for p in points]
        words.append({"text": str(value).strip(), "top": min(ys),
                      "left": min(xs), "score": float(score)})

    flat = " ".join(w["text"] for w in words)
    if "การวิเคราะห์" not in flat and "ตัวชิวัดหลัก" not in flat \
            and "ตัวชี้วัดหลัก" not in flat:
        return {"ok": False, "why": "ไม่ได้อยู่หน้าการวิเคราะห์",
                "seen": [w["text"][:20] for w in words[:6]]}

    import tiktok_publish_bot as bot                           # noqa: PLC0415
    loose = bot.thai_loose

    out = {}
    for key, labels in STUDIO_FIELDS.items():
        label = next((w for w in words
                      if any(loose(name) in loose(w["text"]) for name in labels)),
                     None)
        if label is None:
            continue
        # ค่าที่ต้องการอยู่ **ใต้ป้ายและตรงคอลัมน์เดียวกัน** — ไม่ใช่ตัวเลข
        # ที่อยู่ใกล้ที่สุดบนจอ ซึ่งอาจเป็นของป้ายอีกคอลัมน์
        below = [w for w in words
                 if VALUE_BELOW[0] < w["top"] - label["top"] < VALUE_BELOW[1]
                 and abs(w["left"] - label["left"]) < VALUE_SAME_COLUMN
                 and _re.fullmatch(r"[\d,]+(?:\.\d+)?[KMBkmb]?", w["text"])]
        if not below:
            continue
        below.sort(key=lambda w: w["top"])
        number = to_number(below[0]["text"].replace(",", ""))
        if number is not None:
            out[key] = number

    # **ยอดดูกับถูกใจคือสองค่าที่ขาดไม่ได้** ค่าอื่นขาดได้ (บางหน้าไม่แสดงครบ)
    # แยก "อ่านไม่ได้" ออกจาก "ค่าเป็น 0" — ถ้าเหมารวมจะสรุปผิดว่าไม่มีใครดู
    if "views" not in out or "likes" not in out:
        return {"ok": False, "why": f"อ่านยอดดู/ถูกใจไม่ได้ (ได้มา {sorted(out)})",
                **out}
    return {"ok": True, **out}


def load() -> dict:
    try:
        return json.loads(RESULTS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def record(item_id: str, target: str, views: int, note: str = "") -> None:
    """จดยอดหนึ่งครั้ง — เก็บเป็นประวัติ ไม่ทับของเดิม

    เก็บทุกครั้งที่วัดเพื่อให้ดูได้ว่า **ยอดวิ่งขึ้นหรือนิ่ง** ซึ่งบอกได้มากกว่า
    ตัวเลขวันเดียว: คลิปที่ได้ 500 วิวแล้วหยุด ต่างจากคลิปที่ได้ 500 แล้วยังวิ่ง
    """
    def change(data: dict) -> dict:
        if not isinstance(data, dict):
            data = {}
        key = f"{item_id}:{target}"
        rows = data.get(key)
        rows = list(rows) if isinstance(rows, list) else []
        rows.append({"at": _now(), "views": int(views), "note": str(note or "")})
        data[key] = rows[-40:]          # เก็บ 40 ครั้งล่าสุดพอ
        return data

    shared.update_json(RESULTS_FILE, change, default={},
                       label=f"จดยอดคลิป {item_id}")


def latest(item_id: str, target: str) -> dict | None:
    rows = load().get(f"{item_id}:{target}")
    return rows[-1] if rows else None


# ------------------------------------------------- อ่านยอดเล่นจากโปรไฟล์จริง


def read_profile_tiles(serial: str, log=print) -> list[int]:
    """อ่านยอดเล่นของคลิปในโปรไฟล์ เรียงใหม่สุดขึ้นก่อน

    คืนลิสต์ว่างถ้าอ่านไม่ได้ — **ห้ามคืน 0** เพราะ 0 เป็นยอดจริงที่เป็นไปได้
    (คลิปที่เพิ่งลงมียอด 0 จริงๆ) ถ้าปนกันจะแยก "อ่านไม่ออก" กับ
    "ไม่มีคนดู" ไม่ออก แล้วตัดสินใจผิดทั้งสาย
    """
    def tap(x: int, y: int, wait: float) -> None:
        subprocess.run(["adb", "-s", serial, "shell", "input", "tap", str(x), str(y)],
                       capture_output=True, timeout=40)
        time.sleep(wait)

    try:
        import numpy as np
        from PIL import Image

        import tiktok_publish_bot as bot
        reader = bot.get_thai_ocr()
        if reader is None:
            log("  ตัวอ่านจากภาพใช้ไม่ได้ — อ่านยอดเล่นไม่ได้")
            return []

        # **ต้องปลุกจอก่อนเสมอ** (แก้ 11 ก.ย. 2569) — รอบแรกที่เขียนลืมข้อนี้
        # แล้วได้ภาพจอดำขนาด 7,904 ไบต์ อ่านได้ 0 คำ แล้วรายงานว่า
        # "อ่านยอดเล่นไม่ได้" ซึ่งถูกแต่ไม่บอกสาเหตุจริงว่าจอดับอยู่
        #
        # ใช้ตัวปลุกของ `fb_screen` ที่ผ่านการใช้งานจริงมานาน ไม่เขียนใหม่เอง
        # — มันเช็คสถานะจอก่อน จอเปิดอยู่แล้วจะคืนทันทีไม่ยิงปุ่มมั่วแทรกงานอื่น
        import fb_screen
        def shell(command: str) -> str:
            done = subprocess.run(["adb", "-s", serial, "shell", *command.split()],
                                  capture_output=True, timeout=40)
            return done.stdout.decode("utf-8", errors="replace")

        if not fb_screen.wake(shell, log=log):
            log("  ปลุกจอไม่ขึ้น — อ่านยอดเล่นไม่ได้")
            return []

        # **ต้องเปิด TikTok เองก่อน ห้ามสมมติว่าเปิดค้างอยู่** (แก้ 11 ก.ย. 2569)
        # รอบแรกเขียนโดยเดาว่า TikTok อยู่หน้าสุด ของจริงจอไปอยู่ที่แอปข้อความ
        # การแตะพิกัดโปรไฟล์จึงไปตกบนแอปอื่นแล้วอ่านได้แต่ข้อความ LINE
        subprocess.run(["adb", "-s", serial, "shell", "am", "force-stop",
                        TIKTOK_PACKAGE], capture_output=True, timeout=40)
        subprocess.run(["adb", "-s", serial, "shell", "monkey", "-p", TIKTOK_PACKAGE,
                        "-c", "android.intent.category.LAUNCHER", "1"],
                       capture_output=True, timeout=40)
        time.sleep(8)

        # ยืนยันว่า TikTok อยู่หน้าสุดจริงก่อนแตะอะไร — อ่านจากชื่อหน้าจอ
        # ซึ่งไม่ต้องพึ่งผังจอที่ TikTok ไม่ยอมส่งมา
        where = shell("dumpsys window")
        if TIKTOK_PACKAGE not in where:
            log(f"  เปิด TikTok แล้วแต่ไม่ได้อยู่หน้าสุด — อ่านยอดเล่นไม่ได้")
            return []

        tap(*TAB_PROFILE, 4.5)
        tap(*TAB_VIDEOS, 3.5)
        png = subprocess.run(["adb", "-s", serial, "exec-out", "screencap", "-p"],
                             capture_output=True, timeout=60).stdout
        shot = Image.open(io.BytesIO(png)).convert("RGB")
    except Exception as error:                                 # noqa: BLE001
        log(f"  เปิดโปรไฟล์/แคปจอไม่สำเร็จ: {type(error).__name__}: {error}")
        return []

    try:
        seen_all = reader.readtext(np.array(shot)) or []
    except Exception as error:                                 # noqa: BLE001
        log(f"  อ่านตัวเลขจากภาพไม่สำเร็จ: {type(error).__name__}")
        return []

    # ---- ต้องพิสูจน์ว่าอยู่ **แท็บวิดีโอ** จริง ก่อนเชื่อตัวเลขใดๆ ------------
    #
    # **เจอจริง 11 ก.ย. 2569** แตะแท็บวิดีโอแล้วแต่จอไปอยู่ **แท็บร้านค้า**
    # (แถบแท็บเลื่อนเพราะโปรไฟล์มีชิปเพิ่มมา) ตัวอ่านไปเจอเลข "12" ที่ไหนสักแห่ง
    # บนหน้านั้นแล้วจดเป็น "12 วิว" ของคลิปใบล่าสุด — **ตัวเลขผิดที่ดูน่าเชื่อ
    # แย่กว่าไม่มีตัวเลข** เพราะมันพาไปสรุปผิดว่าสินค้าแบบไหนมีคนดู
    #
    # ด่านนี้จึงมองหาของที่มีเฉพาะบน "แท็บที่ไม่ใช่วิดีโอ" แล้วปฏิเสธทันที
    flat = " ".join(str(v).lower() for _, v, _ in seen_all)
    for wrong in ("tiktok shop", "ยังไม่มีสินค้า", "ผู้ขายยัง", "ยังไม่มีวิดีโอ"):
        if wrong in flat:
            log(f"  ไม่ได้อยู่แท็บวิดีโอ (เห็นคำว่า '{wrong}') — ไม่จดตัวเลขใดๆ")
            return []

    try:
        rows = []
        for points, value, score in seen_all:
            number = to_number(value)
            if number is None or float(score) < .30:
                continue
            xs = [int(p[0]) for p in points]
            ys = [int(p[1]) for p in points]
            top, left = min(ys), min(xs)
            if top < 700:            # ตัดส่วนหัวโปรไฟล์ (ยอดติดตาม/ถูกใจ) ออก
                continue
            rows.append((top, left, number))
    except Exception as error:                                 # noqa: BLE001
        log(f"  อ่านตัวเลขจากภาพไม่สำเร็จ: {type(error).__name__}")
        return []

    if not rows:
        # **ห้ามคืนลิสต์ว่างเงียบๆ** — ผู้เรียกจะรู้แค่ "อ่านไม่ได้" แล้วไล่หา
        # สาเหตุผิดทาง ต้องบอกว่าเห็นอะไรบนจอแทน จะได้รู้ว่าอยู่ผิดหน้าหรือ
        # อยู่ถูกหน้าแต่อ่านเลขไม่ออก (เจอจริง 11 ก.ย. — จอไปอยู่แอปข้อความ)
        try:
            seen = [str(v)[:22] for _, v, _ in reader.readtext(np.array(shot))][:6]
        except Exception:                                      # noqa: BLE001
            seen = []
        log(f"  ไม่เจอยอดเล่นสักช่อง — บนจอเห็น: {seen or '(อ่านอะไรไม่ได้เลย)'}")
        return []

    # ตารางเรียงซ้ายไปขวา บนลงล่าง — จัดแถวก่อนแล้วค่อยเรียงในแถว
    rows.sort(key=lambda r: (round(r[0] / 120), r[1]))
    return [number for _, _, number in rows]


# --------------------------------------------------------- เก็บผลของ TikTok


def collect_tiktok(serial: str, log=print) -> dict:
    """อ่านยอดเล่นแล้วจับคู่กับใบงานที่เราลง TikTok ไป เรียงใหม่สุดก่อน

    **ไม่จดถ้าจับคู่ไม่ลงตัว** — ตัวเลขที่ผูกผิดคลิปแย่กว่าไม่มีตัวเลข
    เพราะมันจะพาไปสรุปผิดว่าสินค้าแบบไหนขายได้
    """
    # **ปิดไว้ — วิธีนี้พิสูจน์แล้วว่าให้ตัวเลขผิด** (11 ก.ย. 2569)
    #
    # ทดสอบกับของจริง: จับคู่ถูก 1 จาก 4 ใบ เพราะกล่อง "แบบร่าง" แทรกหัวแถว
    # และตัวอ่านภาพอ่านเลขตกบางช่อง พอตกหนึ่งช่อง ลำดับที่เหลือเลื่อนผิดทั้งแถว
    # แถมยังอ่านเลขจากที่อื่นบนจอมาปน (ป้ายแจ้งเตือน "12" ถูกจดเป็นยอดวิว)
    #
    # เก็บโค้ดไว้เป็นบันทึกว่าเคยลองทางนี้แล้ว **แต่ห้ามให้มันเขียนข้อมูล**
    # เพราะตัวเลขที่ผูกผิดคลิปแย่กว่าไม่มีตัวเลข — ใช้ `read_studio` แทน
    return {"ok": False, "saved": 0,
            "why": ("ปิดใช้งาน — จับคู่ยอดวิวรายคลิปตามลำดับช่องพิสูจน์แล้วว่า"
                    "ผิด 3 จาก 4 ใบ ให้ใช้ `python clip_results.py ช่อง` "
                    "ซึ่งอ่านตัวเลขรวมของบัญชีที่เชื่อถือได้แทน")}

    import clip_store                                          # noqa: F401

    posted = []
    for run in clip_store.list_runs(shared.DATA_DIR) + clip_store.list_done(shared.DATA_DIR):
        info = (run.get("publish") or {}).get("tiktok") or {}
        if info.get("status") != "posted" or not info.get("posted_at"):
            continue
        posted.append((str(info["posted_at"]), str(run.get("item_id") or ""),
                       str(run.get("name") or "")[:40]))
    posted.sort(reverse=True)          # ใหม่สุดขึ้นก่อน = ลำดับเดียวกับตารางคลิป

    tiles = read_profile_tiles(serial, log=log)
    if not tiles:
        return {"ok": False, "why": "อ่านยอดเล่นจากโปรไฟล์ไม่ได้", "saved": 0}
    if not posted:
        return {"ok": False, "why": "ยังไม่มีใบงานที่ลง TikTok", "saved": 0}

    pairs = min(len(tiles), len(posted))
    log(f"  อ่านยอดเล่นได้ {len(tiles)} ช่อง · ใบที่เราลงไว้ {len(posted)} ใบ "
        f"— จับคู่ได้ {pairs} ใบ")
    saved = 0
    for index in range(pairs):
        views = tiles[index]
        _, item_id, name = posted[index]
        if not item_id:
            continue
        record(item_id, "tiktok", views, note=f"ช่องที่ {index + 1} ในโปรไฟล์")
        log(f"     {views:>8,} วิว  {item_id}  {name}")
        saved += 1
    return {"ok": True, "saved": saved, "tiles": len(tiles), "posted": len(posted)}


# -------------------------------------------------------------------- รายงาน


def report(log=print) -> None:
    """สรุปว่าคลิปไหนมีคนดู — เรียงมากไปน้อย"""
    import clip_store

    names = {}
    for run in clip_store.list_runs(shared.DATA_DIR) + clip_store.list_done(shared.DATA_DIR):
        names[str(run.get("item_id") or "")] = str(run.get("name") or "")[:44]

    rows = []
    for key, history in load().items():
        if not history:
            continue
        item_id, _, target = key.partition(":")
        rows.append((history[-1]["views"], item_id, target,
                     names.get(item_id, ""), history[-1]["at"], len(history)))
    if not rows:
        log("ยังไม่มีข้อมูลผลลัพธ์ — สั่ง collect_tiktok ก่อน")
        return

    rows.sort(reverse=True)
    log(f"ผลลัพธ์ของคลิปที่ลงไปแล้ว {len(rows)} ใบ (เรียงตามยอดวิว)")
    log(f"   {'ยอดวิว':>9}  {'ปลายทาง':<9} {'วัดล่าสุด':<17} สินค้า")
    for views, item_id, target, name, at, times in rows:
        log(f"   {views:>9,}  {target:<9} {at[5:16]:<17} {name}")
    total = sum(r[0] for r in rows)
    log(f"\n   รวม {total:,} วิว · เฉลี่ย {total // max(1, len(rows)):,} วิว/ใบ")


ACCOUNT_FILE = shared.DATA_DIR / "clip_account_stats.json"


def record_account(channel: str, stats: dict) -> None:
    """จดตัวเลขรวมของช่องหนึ่งครั้ง เก็บเป็นประวัติรายวัน"""
    def change(data: dict) -> dict:
        if not isinstance(data, dict):
            data = {}
        rows = data.get(channel)
        rows = list(rows) if isinstance(rows, list) else []
        rows.append({"at": _now(), **{k: v for k, v in stats.items() if k != "ok"}})
        data[channel] = rows[-180:]           # เก็บราวครึ่งปี
        return data

    shared.update_json(ACCOUNT_FILE, change, default={},
                       label=f"จดตัวเลขช่อง {channel}")


def account_report(log=print) -> None:
    """สรุปว่าช่องโตขึ้นไหม — และ **คนดูแล้วมีส่วนร่วมไหม**"""
    try:
        data = json.loads(ACCOUNT_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    if not data:
        log("ยังไม่มีตัวเลขช่อง — สั่ง `python clip_results.py ช่อง` ก่อน")
        return
    for channel, rows in data.items():
        log(f"\n=== {channel} === (รอบ 7 วันของ TikTok)")
        log(f"   {'วัดเมื่อ':<18}{'ยอดดู':>9}{'ถูกใจ':>8}{'ตามเพิ่ม':>10}   อัตราถูกใจ")
        for row in rows[-14:]:
            views = int(row.get("views") or 0)
            likes = int(row.get("likes") or 0)
            rate = f"{likes / views * 100:.2f}%" if views else "-"
            log(f"   {row.get('at', '')[:16]:<18}{views:>9,}{likes:>8,}"
                f"{int(row.get('followers') or 0):>10,}   {rate}")
        last = rows[-1]
        views, likes = int(last.get("views") or 0), int(last.get("likes") or 0)
        if views:
            rate = likes / views * 100
            log(f"\n   อัตราถูกใจล่าสุด {rate:.2f}%")
            # ค่าอ้างอิงที่ยอมรับกันทั่วไปของ TikTok อยู่ราว 3–9%
            if rate < 1.0:
                log("   ⚠️ ต่ำกว่าค่าปกติของ TikTok (ราว 3–9%) มาก — "
                    "คนเห็นคลิปแต่ไม่มีส่วนร่วม ปัญหาอยู่ที่ตัวคลิป ไม่ใช่ที่จำนวนที่ลง")


if __name__ == "__main__":
    import sys

    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    serial = sys.argv[2] if len(sys.argv) > 2 else "W4FYYPYTLFYLIFHM"
    if arg == "ช่อง":
        with shared.phone_lock(serial, owner="สมุดผลลัพธ์คลิป",
                               label="อ่านตัวเลขช่องจาก TikTok Studio",
                               queue=False):
            got = read_studio(serial)
        print(got)
        if got.get("ok"):
            record_account("tiktok:@artaiitgadget", got)
            print("จดแล้ว")
    elif arg == "เก็บ":
        with shared.phone_lock(serial, owner="สมุดผลลัพธ์คลิป",
                               label="อ่านยอดเล่นในโปรไฟล์", queue=False):
            print(collect_tiktok(serial))
    elif arg == "รายคลิป":
        report()
    else:
        account_report()
