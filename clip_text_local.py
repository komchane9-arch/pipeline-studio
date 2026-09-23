# -*- coding: utf-8 -*-
"""อ่านตัวหนังสือที่อยู่บนคลิปด้วยตัวอ่านในเครื่อง — ใช้แทนการส่งภาพให้ Gemini

เจ้าของสั่ง 23 ก.ย. 2569: *"ทดลองเปลี่ยนตัวตรวจ ตัวเลือกทั้งหมดเป็น local ai
ให้หมดเลย"*

**ทำไมต้องตรวจตัวหนังสือบนคลิป** (เจ้าของสั่งไว้ตั้งแต่ 23 ส.ค. 2569)
Veo วาดตัวอักษรไทยพลาดบ่อย — ขาดกลางคำ สระลอย วรรณยุกต์ผิดที่ เจอจริงในคลิป
ทีวี 75 นิ้ว: บนจอเขียน "สายเก" ทั้งที่ควรเป็น "สายเกม" ดูจากไฟล์อย่างเดียว
จับไม่ได้เลย ต้องมองภาพจริง

ใช้ `screen_read.get_thai_ocr()` ตัวเดียวกับที่สายโพสต์ใช้อ่านหน้าจอมือถือ
จะได้ไม่มีตัวอ่านสองชุดที่ให้คำตอบไม่ตรงกัน
"""

from __future__ import annotations

import re
import time
from pathlib import Path

# ตัวอักษรไทยที่ถือว่าอ่านออก — ใช้ตัดสินว่าข้อความที่อ่านได้เป็นคำจริงหรือขยะ
THAI = re.compile(r"[฀-๿]")
# สระลอย/วรรณยุกต์ลอย = ตัวที่ต้องเกาะพยัญชนะแต่ไม่มีพยัญชนะนำหน้า
# นี่คืออาการที่ Veo ทำพลาดบ่อยที่สุด
FLOATING = re.compile(r"(?:^|[\s฀-๿]?)([ัิ-ฺ็-๎])")
# ความมั่นใจขั้นต่ำที่จะนับว่า "อ่านออก" — ต่ำกว่านี้ถือว่าเห็นแต่อ่านไม่ชัด
MIN_CONFIDENCE = 0.45
# ข้อความสั้นกว่านี้ไม่นับเป็นคำ (กัน OCR หลอนจากลายเส้นในภาพ)
MIN_CHARS = 2


def read_frames(frames: list, log=print) -> dict:
    """อ่านตัวหนังสือจากภาพนิ่งหลายใบ — คืนรูปเดียวกับที่ Gemini เคยคืน

        has_text        มีตัวหนังสือบนคลิปไหม (None = อ่านไม่ได้เลย)
        text_seen       ข้อความที่อ่านได้ทั้งหมด
        text_readable   ตัวหนังสืออ่านออกไหม (None = ไม่มีตัวหนังสือให้ตัดสิน)
        text_problem    อธิบายว่าอ่านไม่ออกตรงไหน

    **อ่านไม่ได้เลย ต้องคืน None ไม่ใช่ False** เพราะ "ยังไม่ได้ดู" กับ
    "ดูแล้วไม่มีตัวหนังสือ" เป็นคนละเรื่อง (กติกา 2.3.1 ข้อ 4)
    """
    blank = {"has_text": None, "text_seen": "", "text_readable": None,
             "text_problem": "", "text_engine": ""}
    frames = [Path(f) for f in (frames or []) if Path(f).is_file()]
    if not frames:
        blank["text_problem"] = "ไม่มีภาพนิ่งให้อ่าน"
        return blank

    try:
        import screen_read
        reader = screen_read.get_thai_ocr()
    except Exception as error:                                   # noqa: BLE001
        blank["text_problem"] = f"เปิดตัวอ่านตัวหนังสือไม่ได้: {type(error).__name__}"
        log(f"  เปิดตัวอ่านตัวหนังสือไม่ได้: {error}")
        return blank
    if reader is None:
        blank["text_problem"] = "ไม่มีตัวอ่านตัวหนังสือในเครื่อง"
        return blank

    began = time.perf_counter()
    seen: list[str] = []
    weak: list[str] = []
    for frame in frames:
        try:
            found = reader.readtext(str(frame), detail=1, paragraph=False)
        except Exception as error:                               # noqa: BLE001
            log(f"  อ่านภาพ {frame.name} ไม่ได้: {type(error).__name__}")
            continue
        for item in found:
            text = str(item[1] if len(item) > 1 else "").strip()
            conf = float(item[2]) if len(item) > 2 else 0.0
            letters = [c for c in text if not c.isspace()]
            if len(letters) < MIN_CHARS:
                continue
            if conf >= MIN_CONFIDENCE:
                seen.append(text)
            else:
                weak.append(text)

    took = time.perf_counter() - began
    every = seen + weak
    log(f"  อ่านตัวหนังสือจาก {len(frames)} ภาพใน {took:.1f} วินาที — "
        f"เจอ {len(seen)} ชิ้นที่ชัด · {len(weak)} ชิ้นที่ไม่ชัด")

    if not every:
        # อ่านครบทุกภาพแล้วไม่เจอตัวหนังสือเลย = **ตอบได้แน่นอนว่าไม่มี**
        return {"has_text": False, "text_seen": "", "text_readable": None,
                "text_problem": "", "text_engine": f"EasyOCR ({took:.1f} วินาที)"}

    joined = " · ".join(dict.fromkeys(every))          # ตัดซ้ำแต่คงลำดับ
    problems = []
    if weak and len(weak) >= len(seen):
        problems.append(f"อ่านไม่ชัด {len(weak)} ชิ้นจาก {len(every)} ชิ้น")
    floating = [t for t in every if _has_floating(t)]
    if floating:
        problems.append("มีสระหรือวรรณยุกต์ลอย: " + " · ".join(floating[:3]))

    return {
        "has_text": True,
        "text_seen": joined[:500],
        # ---- ห้ามเคลมว่า "อ่านออก" เพราะเราพิสูจน์ไม่ได้ --------------------
        #
        # วัดกับคลิปจริง 8 ใบเทียบกับคำตอบเดิมของ Gemini เมื่อ 23 ก.ย. 2569
        #
        #     มีตัวหนังสือไหม   ตรงกัน 7/8   <- ตัวอ่านในเครื่องทำได้ดี
        #     อ่านออกไหม        ตรงกัน 3/8   <- ทำไม่ได้
        #
        # เพราะ Gemini ตัดสินจาก **การสะกดผิด** เช่นเห็น "น่าน" แล้วรู้ว่าควรเป็น
        # "นาน" ซึ่งต้องเข้าใจภาษา ไม่ใช่แค่ดูรูปตัวอักษร ตัวอ่านในเครื่องเห็นแค่
        # ว่ามีตัวอักษรอะไรอยู่ตรงไหน
        #
        # จึงตอบได้แค่สองอย่าง: **False เมื่อเจอปัญหาที่พิสูจน์ได้** (สระลอย ·
        # อ่านไม่ชัดเกินครึ่ง) และ **None เมื่อยังตัดสินไม่ได้** ห้ามตอบ True
        # เพราะนั่นคือการบอกว่า "ตรวจแล้วผ่าน" ทั้งที่ไม่เคยตรวจเรื่องการสะกดเลย
        # (กติกา 2.3 — ตัวตรวจที่บอกผ่านทั้งที่ยังไม่ผ่าน อันตรายกว่าไม่มีตัวตรวจ)
        "text_readable": False if problems else None,
        "text_problem": " / ".join(problems),
        "text_engine": f"EasyOCR ({took:.1f} วินาที)",
    }


def _has_floating(text: str) -> bool:
    """มีสระหรือวรรณยุกต์ที่ไม่มีพยัญชนะให้เกาะไหม — อาการที่ Veo ทำพลาดบ่อย

    **ต้องมองย้อนข้ามเครื่องหมายตัวอื่นด้วย** เพราะภาษาไทยซ้อนเครื่องหมายได้
    เช่น "ซื้อ" = ซ + สระอือ + ไม้โท ถ้าดูแค่ตัวติดกันตัวเดียว ไม้โทจะเห็น
    สระอือแล้วนึกว่าลอย — เตือนผิดทันที (เจอจริงตอนทดสอบ 23 ก.ย. 2569
    คำว่า "ซื้อทีเดียว ใช้ยาวๆ ไปเลย" ถูกติดธงทั้งที่สะกดถูกทุกตัว)
    """
    consonant = re.compile(r"[ก-ฮ]")
    mark = re.compile(r"[ัิ-ฺ็-๎]")
    for index, ch in enumerate(text):
        if not mark.match(ch):
            continue
        back = index - 1
        while back >= 0 and mark.match(text[back]):
            back -= 1                     # ข้ามเครื่องหมายที่ซ้อนกันอยู่
        if back < 0 or not consonant.match(text[back]):
            return True
    return False


if __name__ == "__main__":                 # ลองด้วยมือ: python clip_text_local.py <คลิป>
    import sys
    import tempfile

    import clip_check

    if len(sys.argv) < 2:
        print("ใช้: python clip_text_local.py <ไฟล์คลิป>")
        raise SystemExit(0)
    with tempfile.TemporaryDirectory() as tmp:
        shots = clip_check.grab_frames(sys.argv[1], tmp)
        print(f"ตัดภาพได้ {len(shots)} ใบ")
        out = read_frames(shots)
    for key, value in out.items():
        print(f"  {key:<16} = {value!r}")
