"""อ่านยอดพูดถึงจากหน้าจอ Facebook — ของสายโพสต์ ไม่เกี่ยวกับแฮชแท็ก

**ทำไมแยกออกมา** (ผู้ใช้สั่ง 27 ส.ค. 2026: *"แฮชแทกเป็นของของสายโพสต์ได้ไง
สายโพสต์ไม่ได้ใช้แฮชแทก"* → *"งั้นแยกไฟล์ออกมาสิ"*)

ตารางแบ่งเลนใน `CLAUDE.md` เขียนว่า `hashtag.py` เป็นของสายโพสต์ ซึ่ง**ผิด**
ตรวจของจริงแล้วพบว่า

    clip_app.py     hashtag.plan_for_run()   ← ตั้งแฮชแท็กให้คลิป (สายคลิป)
    app.py          plan_for_run · build_candidates
    publish_flow.py MENTION_MIN · looks_like_mention · parse_mention_count · passes

**สายโพสต์ไม่ได้ตั้งแฮชแท็กเลย** มันแค่ยืมตัวอ่านยอดพูดถึงไปใช้ตอนเลือกว่าจะ
แท็กร้านไหน ซึ่งเป็นคนละเรื่องกันโดยสิ้นเชิง — แค่บังเอิญเคยเขียนไว้ไฟล์เดียวกัน

พอปนกันสองเลย ผลคือเวลามีคนแก้ไฟล์นี้ อีกเลนจะ commit ไม่ได้เพราะติดงานคนอื่น
(เกิดจริง 27 ส.ค. — `hashtag.py` มีของค้าง 119 บรรทัดจากสองแชท commit ไม่ได้ทั้งไฟล์)

ตอนนี้ `hashtag.py` ดึงของพวกนี้ไปจากที่นี่ต่อ ของเดิมที่เรียก `hashtag_lib.passes()`
อยู่จึงยังทำงานเหมือนเดิมทุกอย่าง ไม่ต้องแก้ตาม — ใครจะย้ายไปเรียกตรงๆ ค่อยย้ายทีหลังได้
"""

from __future__ import annotations

import re

# เกณฑ์ยอดพูดถึงขั้นต่ำ — ผู้ใช้กำหนดไว้ที่หมื่น
MENTION_MIN = 10_000

UNIT_MULTIPLIER = {
    "พัน": 1_000, "หมื่น": 10_000, "แสน": 100_000, "ล้าน": 1_000_000,
    "k": 1_000, "m": 1_000_000, "b": 1_000_000_000,
}

# ตัวเลขที่อาจมีจุดทศนิยม ตามด้วยหน่วย (เว้นวรรคหรือไม่ก็ได้)
COUNT_RE = re.compile(
    r"(\d[\d,]*(?:\.\d+)?)\s*(พัน|หมื่น|แสน|ล้าน|[KkMmBb])?",
)

# ข้อความรอบตัวเลขที่บอกว่านี่คือ "ยอดพูดถึง" ไม่ใช่ตัวเลขอย่างอื่นบนจอ
MENTION_HINT_RE = re.compile(
    r"(โพสต์|ครั้ง|มีการพูดถึง|พูดถึง|views?|posts?|mentions?)", re.I
)


def parse_mention_count(text: str) -> int | None:
    """แปลงข้อความยอดพูดถึงเป็นจำนวนเต็ม — คืน None ถ้าไม่ใช่ตัวเลขยอด

    รองรับที่เจอได้จริงบนแอป: `12,345` · `1.2 หมื่น` · `12K` · `3 ล้าน`
    ตั้งใจ **ไม่เดา** เมื่ออ่านไม่ออก — คืน None แล้วให้ผู้เรียกรายงานตรงๆ
    ว่าอ่านยอดไม่ได้ ดีกว่าเดาเป็น 0 แล้วทิ้งแท็กที่จริงๆ ยอดสูง
    """
    if not text:
        return None
    match = COUNT_RE.search(str(text).replace(" ", " "))
    if not match:
        return None
    number_text, unit = match.group(1), (match.group(2) or "")
    try:
        number = float(number_text.replace(",", ""))
    except ValueError:
        return None
    multiplier = UNIT_MULTIPLIER.get(unit.casefold(), 1) if unit else 1
    return int(round(number * multiplier))


def looks_like_mention(text: str) -> bool:
    """ข้อความนี้น่าจะเป็นยอดพูดถึงไหม

    ใช้กรองตัวเลขอื่นบนแถวเดียวกัน (เช่นลำดับที่ หรือราคา) ออกก่อนแปลง
    ถ้าเป็นตัวเลขล้วนไม่มีคำใบ้ ก็ยังรับ — แอปบางรุ่นโชว์แค่ตัวเลขเปล่า
    """
    if not text:
        return False
    if MENTION_HINT_RE.search(text):
        return True
    return bool(re.fullmatch(
        r"[\d,.\s]*\d[\d,.\s]*(พัน|หมื่น|แสน|ล้าน|[KkMmBb])?", text.strip()))


def passes(count: int | None, minimum: int = MENTION_MIN) -> bool:
    """ผ่านเกณฑ์ไหม — อ่านยอดไม่ได้ถือว่า **ไม่ผ่าน**

    เลือกทางนี้เพราะโพสต์แท็กที่ไม่รู้ยอดคือเดาสุ่ม ส่วนการตกหล่นไป 1 แท็ก
    เสียหายน้อยกว่า และระบบรายงานให้เห็นทุกตัวว่าอ่านได้เท่าไร
    """
    return count is not None and count > minimum


if __name__ == "__main__":
    for sample in ("12,345", "1.2 หมื่น", "12K", "3 ล้าน", "อันดับ 5", "พูดถึง 8.4 พัน"):
        n = parse_mention_count(sample)
        mark = "✅" if passes(n) else "❌"
        print(f"{mark} {sample:16s} → {n if n is not None else 'อ่านไม่ออก'}")
