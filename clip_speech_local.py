# -*- coding: utf-8 -*-
"""ถอดเสียงพูดในคลิปด้วย AI ในเครื่อง — ใช้แทนการส่งให้ Gemini ฟัง

เจ้าของสั่ง 22 ก.ย. 2569: *"ใช้ local ai ที่ถอดเสียง เอามาตรวจเสียงเลย"*

**ทำไมถึงเปลี่ยน** — คีย์ Gemini เครดิตหมดทั้ง 4 ใบตั้งแต่ 19 ก.ย. ตัวตรวจเสียง
จึงตอบว่า "ยังตรวจเสียงไม่ได้" ทุกใบ และตอนล้มมันยังลองซ้ำ 6 ครั้งห่างกัน
15→30→60→60→60→60 วินาที = รอเปล่า 285 วินาทีต่อคลิปหนึ่งใบ

ผลวัดจริง 23 ก.ย. 2569 — เทียบกับ **บทพูดต้นฉบับใน run.json** ไม่ใช่เทียบกับ
คำตอบของ AI อีกตัว (ถ้าเอา AI สองตัวมาเทียบกันเอง จะไม่รู้เลยว่าใครถูก)

    คลิปทดสอบ 3 ใบ       41117966209 · 45508362084 · 51854992106

    whisper small     ตรงบท 82%   3.5 วินาที/คลิป
    whisper medium    ตรงบท 85%   9.2 วินาที/คลิป   <- เลือกตัวนี้
    Gemini (ของเดิม)   ตรงบท 85%   ต้องใช้เครดิต + ล่มบ่อย

**ตัวในเครื่องเสมอ Gemini พอดี** โดยไม่เสียเงิน ไม่มีวันหมดโควตา ไม่ต้องรอเน็ต

⚠️ **รันด้วย Python ของ `_vision_env` เท่านั้น** เพราะตอนลง mediapipe ทับ Python
หลักเมื่อ 14 ก.ย. pip อัปเกรด numpy เป็น 2.x แล้ว cv2 กับ EasyOCR ใช้ไม่ได้
ทั้งสายพังชั่วคราว — ห้ามลงทับอีก
"""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

VISION_PYTHON = Path(r"C:\project\2.Auto gen Video\_vision_env\Scripts\python.exe")
WORKER = Path(__file__).resolve().parent / "clip_speech_worker.py"

# โหลดโมเดลรอบแรกกินเวลา ส่วนถอดเสียงคลิป 10 วินาทีใช้ราว 9 วินาที
# ตั้งเผื่อไว้หนาสำหรับคลิปยาวหรือเครื่องกำลังทำอย่างอื่นอยู่
TIMEOUT_SECONDS = 600


def available() -> tuple[bool, str]:
    """ใช้ตัวถอดเสียงในเครื่องได้ไหม — คืน (ได้ไหม, เหตุผลภาษาคน)

    **ตอบว่าใช้ไม่ได้ต้องบอกเหตุผลเสมอ** ไม่งั้นเวลาระบบถอยไปใช้ทางอื่น
    จะไม่มีใครรู้ว่าทำไม แล้ววันหนึ่งจะกลายเป็นว่าไม่เคยใช้ตัวในเครื่องเลย
    โดยไม่มีใครสังเกต
    """
    if not VISION_PYTHON.is_file():
        return False, f"ไม่เจอ Python ของ _vision_env ที่ {VISION_PYTHON}"
    if not WORKER.is_file():
        return False, f"ไม่เจอตัวถอดเสียงที่ {WORKER}"
    return True, ""


def listen(clip, language: str = "th", log=print) -> dict:
    """ถอดเสียงคลิปหนึ่งไฟล์ — คืนรูปเดียวกับที่ `clip_check.listen()` คืน

    คืนค่าเหมือนกันเป๊ะเพื่อให้สลับตัวถอดเสียงได้โดยไม่ต้องแก้ผู้เรียก

        has_speech   True / False / **None = ถอดไม่ได้**
        transcript   ข้อความที่ถอดได้
        language     ภาษาที่ตัวถอดเดาได้
        speech_note  เหตุผลตอนถอดไม่ได้ (ว่างเมื่อสำเร็จ)

    **ถอดไม่ได้ ต้องคืน None ไม่ใช่ False** เพราะ "ยังไม่ได้ฟัง" กับ "ฟังแล้ว
    ไม่มีเสียงพูด" เป็นคนละเรื่องกันสิ้นเชิง (กติกา 2.3.1 ข้อ 4)
    """
    blank = {"has_speech": None, "transcript": "", "language": "",
             "other_sound": "", "speech_note": "", "speech_engine": ""}

    ok, why = available()
    if not ok:
        blank["speech_note"] = f"ตัวถอดเสียงในเครื่องใช้ไม่ได้: {why}"
        log(f"  ถอดเสียงในเครื่องไม่ได้ — {why}")
        return blank

    began = time.perf_counter()
    try:
        done = subprocess.run(
            [str(VISION_PYTHON), str(WORKER), str(clip), language],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        blank["speech_note"] = f"ถอดเสียงนานเกิน {TIMEOUT_SECONDS} วินาที"
        log(f"  ถอดเสียงในเครื่องนานเกิน {TIMEOUT_SECONDS} วินาที — ยกเลิก")
        return blank
    except Exception as error:                                   # noqa: BLE001
        blank["speech_note"] = f"เรียกตัวถอดเสียงไม่ได้: {type(error).__name__}"
        log(f"  เรียกตัวถอดเสียงในเครื่องไม่ได้: {error}")
        return blank

    took = time.perf_counter() - began
    raw = (done.stdout or "").strip().splitlines()
    got = {}
    for line in reversed(raw):                 # เอาบรรทัด JSON สุดท้ายที่อ่านได้
        try:
            got = json.loads(line)
            break
        except Exception:                                        # noqa: BLE001
            continue

    if not got:
        tail = (done.stderr or done.stdout or "").strip()[-200:]
        blank["speech_note"] = f"ตัวถอดเสียงตอบอะไรไม่รู้เรื่อง: {tail}"
        log(f"  ตัวถอดเสียงในเครื่องตอบผิดรูป: {tail}")
        return blank

    if not got.get("ok"):
        blank["speech_note"] = str(got.get("why") or "ถอดเสียงไม่สำเร็จ")
        log(f"  ถอดเสียงในเครื่องไม่สำเร็จ — {blank['speech_note']}")
        return blank

    text = str(got.get("transcript") or "")
    log(f"  ถอดเสียงในเครื่องเสร็จใน {took:.1f} วินาที "
        f"({got.get('engine')}) — ได้ {len(text)} ตัวอักษร")
    return {
        "has_speech": bool(got.get("has_speech")),
        "transcript": text,
        "language": str(got.get("language") or ""),
        # ตัวถอดเสียงบอกไม่ได้ว่ามีเสียงอะไรอีกในคลิป (ดนตรี เสียงบรรยากาศ)
        # **ปล่อยว่างไว้ ห้ามเดา** ใครอยากรู้ต้องไปวัดจากความดังแทน
        "other_sound": "",
        "speech_note": "",
        "speech_engine": str(got.get("engine") or "ในเครื่อง"),
        "speech_seconds": got.get("seconds"),
        "language_probability": got.get("language_probability"),
    }


if __name__ == "__main__":                       # ลองด้วยมือ: python clip_speech_local.py <คลิป>
    import sys

    if len(sys.argv) < 2:
        ok, why = available()
        print("ใช้ได้" if ok else f"ใช้ไม่ได้ — {why}")
        print(f"โมเดล: ดูที่ {WORKER.name}")
        raise SystemExit(0)
    out = listen(sys.argv[1])
    for key in ("has_speech", "language", "speech_engine", "speech_seconds",
                "speech_note"):
        print(f"  {key:<20} = {out.get(key)!r}")
    print(f"  ถอดได้: {out.get('transcript')}")
