"""เตรียมบทพูดไทยให้ Veo อ่านออก — ถอดบทเรียนจาก KVID

ปัญหาที่ KVID เจอมาก่อน: เสียงพูดไทยของ Veo **ล้มบ่อย** (audio generation failed)
โดยเฉพาะเมื่อบทมีเครื่องหมายตกใจ/คำถาม และเมื่อประโยคยาวติดกันไม่มีจังหวะพัก

บันไดแก้ของ KVID มี 3 รอบ ไล่จากเบาไปหนัก:

    รอบ 1  ตัด ! ? ออก + เว้นวรรคจังหวะคำ      ← ทำตั้งแต่รอบแรก ไม่รอให้ล้มก่อน
    รอบ 2  เว้นวรรคถี่ขึ้น (พูดช้า/ชัดขึ้น)
    รอบ 3  ให้ AI เรียบเรียงประโยคใหม่ให้สั้นลง
    ยังล้ม → ข้ามคลิป ไม่วนต่อ

โมดูลนี้ทำรอบ 1–2 (แก้ข้อความล้วน ไม่ต้องเรียก AI) ส่วนรอบ 3 ต้องยิงกลับไปหา GPT
จึงอยู่ฝั่งผู้เรียก

**ทำไมไม่ตัดคำไทยจริงๆ** การตัดคำต้องใช้พจนานุกรม/ไลบรารีเพิ่ม และถ้าตัดผิดจะ
ทำให้ความหมายเพี้ยนกว่าเดิม — ที่ต้องการคือ "จังหวะพัก" ซึ่งใส่ที่ **ขอบวรรคที่มี
อยู่แล้ว** ก็พอ (GPT เขียนบทแนวพูดคุยโดยเว้นวรรคเป็นวลีอยู่แล้ว)
"""

from __future__ import annotations

import re

# เครื่องหมายที่ทำให้ TTS ไทยสะดุด — ตัดทิ้งได้โดยความหมายไม่เปลี่ยน
SHOUTY_RE = re.compile(r"[!?！？]+")
# จุดไข่ปลา/ขีดยาวที่ TTS อ่านไม่ออก
NOISE_RE = re.compile(r"[……]+|[—–]{1,}")
MULTI_SPACE_RE = re.compile(r"[ \t ]{2,}")
SPACE_BEFORE_PUNCT_RE = re.compile(r"\s+([,.])")
THAI_RUN_RE = re.compile(r"[฀-๿]+")


def strip_shouty(text: str) -> str:
    """ตัด ! ? และเครื่องหมายกวนอื่นๆ ออก แล้วเก็บช่องว่างให้เรียบร้อย"""
    out = SHOUTY_RE.sub(" ", text or "")
    out = NOISE_RE.sub(" ", out)
    out = MULTI_SPACE_RE.sub(" ", out)
    out = SPACE_BEFORE_PUNCT_RE.sub(r"\1", out)
    return out.strip()


def pace(text: str, level: int = 1) -> str:
    """ใส่จังหวะพักด้วยจุลภาคที่ขอบวรรคเดิม

    level 1 = ไม่เพิ่มจังหวะ (แค่ทำความสะอาด)
    level 2 = ใส่จุลภาคที่ทุกวรรค ทำให้พูดช้าลง/ชัดขึ้น

    ใส่**เฉพาะขอบที่ทั้งสองฝั่งเป็นอักษรไทย** — ไม่ไปแทรกกลางชื่อรุ่นภาษาอังกฤษ
    หรือกลางตัวเลข ซึ่งจะทำให้อ่านผิด
    """
    if level < 2:
        return text
    parts = [p for p in (text or "").split(" ") if p]
    if len(parts) < 2:
        return text
    out = [parts[0]]
    for part in parts[1:]:
        previous = out[-1]
        both_thai = bool(THAI_RUN_RE.search(previous[-1:])) and bool(
            THAI_RUN_RE.search(part[:1])
        )
        # ไม่ซ้อนจุลภาคถ้าท้ายวรรคก่อนมีอยู่แล้ว
        if both_thai and not previous.endswith((",", ".")):
            out[-1] = previous + ","
        out.append(part)
    return " ".join(out)


def speech_ready(text: str, level: int = 1) -> str:
    """ทำบทให้พร้อมให้ Veo อ่าน — เรียกได้ทั้งกับบทพูดล้วนและกับ prompt ทั้งก้อน

    ปลอดภัยกับข้อความอังกฤษด้วย (แค่ตัด ! ? ซึ่งไม่กระทบคำสั่งกล้อง/แสง)
    """
    return pace(strip_shouty(text), level)


# จำนวนระดับที่โมดูลนี้ทำได้ — เกินจากนี้ต้องให้ AI เรียบเรียงใหม่
MAX_LEVEL = 2
