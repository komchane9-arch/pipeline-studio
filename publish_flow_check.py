"""ด่านตรวจ "การโพสต์ต้องกดหน้าจอจริง" — รันก่อนเพิ่มปลายทางใหม่ทุกครั้ง

    python publish_flow_check.py

กติกาเต็มอยู่ที่ `CLAUDE.md` ข้อ 2.7 (ผู้ใช้สั่งไว้ 25 ส.ค. 2569) ย่อได้ว่า
**ทุกการกระทำบนหน้าจอต้องผ่านระบบรับสัมผัสของ Android เหมือนนิ้วคนจริง**
ยกเว้นได้อย่างเดียวคือตอนเปิดแอป

**ทำไมถึงเป็นสคริปต์ ไม่ใช่บรรทัด grep ในคอมเมนต์**

ของเดิมเป็นสูตร `grep` ที่เขียนไว้ในหัว `publish_flow.py` ให้คนคัดลอกไปรัน
พอ 28 ส.ค. 2569 สายกลางเพิ่มที่อยู่ `POST /api/phone/type` (ให้คนนั่งคุมมือถือ
พิมพ์จากคีย์บอร์ดคอมได้) เราจะเติมคำนี้เข้าสูตรเพื่อกันไม่ให้ขั้นโพสต์หยิบไปใช้
**แต่พอกวาด `*.py` ทั้งหมด ด่านก็ไปจับตัวที่อยู่นั้นใน `app.py` ซึ่งมีอยู่โดยชอบ**

    app.py:3493:@app.post("/api/phone/type")        ← ไม่ใช่การละเมิด

ด่านที่เตือนผิดทุกครั้งจะถูกคนเลิกสนใจภายในไม่กี่วัน แล้วกลายเป็นด่านที่มีไว้เฉยๆ
(`CLAUDE.md` ข้อ 2.3 — *"ตัวตรวจที่บอกว่าผ่านทั้งที่ยังไม่ผ่าน อันตรายกว่าไม่มี
ตัวตรวจ"* ฝั่งกลับกันก็จริงเหมือนกัน) การรู้ว่า **ที่ไหนผิด ที่ไหนถูก** ต้องเขียน
ลงไฟล์ ไม่ใช่ฝากไว้ในสูตรบรรทัดเดียว

**ตรวจอะไรบ้าง** — ไล่หาคำต้องห้ามเฉพาะในไฟล์ที่ทำหน้าที่โพสต์จริง
ไม่กวาดทั้งโปรเจกต์ เพราะไฟล์ส่วนกลางมีสิทธิ์ถือของพวกนี้ไว้โดยชอบ

คืนค่า 0 = ผ่าน · 1 = เจอการละเมิด (เอาไปต่อท้าย && ได้)
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

# ไฟล์ที่ทำหน้าที่ "โพสต์จริง" — ที่เดียวที่กติกาข้อ 2.7 บังคับ
WATCHED = ["publish_flow.py", "tiktok_post.py",
           "fb_*.py", "fbx_*.py", "facebook_*.py", "shopee_*.py", "clip_*.py"]

# คำต้องห้าม → เหตุผลภาษาคนว่าทำไมถึงห้าม
BANNED = {
    r"graph\.facebook\.com": "เรียก API ของ Facebook ตรงๆ แทนที่จะกดบนจอ",
    r"/me/videos": "อัปโหลดคลิปผ่าน API ของ Facebook",
    r"open_api": "เรียก API ของแพลตฟอร์ม (Shopee/TikTok)",
    r"upload_video": "อัปโหลดคลิปผ่าน API",
    r"AccessibilityService": "ให้บริการช่วยเหลือกดแทน ไม่ใช่การแตะจริง",
    r"/api/phone/type": "พิมพ์ผ่านช่องควบคุม scrcpy — ทางนี้สำหรับคนนั่งคุม"
                        "มือถือเองเท่านั้น ขั้นโพสต์ต้องใช้ ADBKeyboard",
}

# บรรทัดที่ไม่นับว่าละเมิด — เอกสาร ไม่ใช่โค้ดที่ทำงานจริง
def _is_documentation(line: str) -> bool:
    stripped = line.strip()
    return (stripped.startswith(("#", "║", "╔", "╚", ">", "*"))
            or "║" in line)


def _say(message: str = "") -> None:
    """พิมพ์ออกจอ — คอนโซล Windows ตั้งค่าเริ่มต้นเป็น cp1252 ซึ่งพิมพ์ไทยไม่ได้
    ถ้าไม่ดักไว้ ด่านจะพังตอนรายงานผลแทนที่จะบอกคำตอบ

    ⚠️ **ต้องเปลี่ยนช่องทางออกทั้งช่อง ห้ามสลับไปมารายบรรทัด** ตอนแรกผมเขียนเป็น
    `try: print() except: เขียนลงช่องดิบ` ซึ่งได้ผลลัพธ์**สลับลำดับ** — บรรทัด
    ภาษาอังกฤษไปกองท้ายสุด แยกออกจากคำอธิบายภาษาไทยของมัน อ่านไม่รู้เรื่องเลย
    เพราะสองช่องนั้นเก็บของไว้คนละกอง แล้วเทออกจอคนละเวลา
    """
    print(message)


try:                                    # Python 3.7 ขึ้นไปเปลี่ยนได้ตรงๆ
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):       # ที่ไหนเปลี่ยนไม่ได้ก็ยังทำงานต่อได้
    pass


def scan(root: Path = HERE) -> list[tuple[str, int, str, str]]:
    """คืนรายการละเมิด — (ไฟล์, บรรทัด, เนื้อบรรทัด, เหตุผล)"""
    found: list[tuple[str, int, str, str]] = []
    seen: set[Path] = set()
    for pattern in WATCHED:
        for path in sorted(root.glob(pattern)):
            if path in seen or not path.is_file():
                continue
            seen.add(path)
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for number, line in enumerate(text.splitlines(), start=1):
                if _is_documentation(line):
                    continue
                for needle, why in BANNED.items():
                    if re.search(needle, line):
                        found.append((path.name, number, line.strip()[:110], why))
                        break
    return found


def main() -> int:
    hits = scan()
    if not hits:
        names = ", ".join(WATCHED)
        _say("✅ ผ่าน — ไม่มีทางลัดหลุดเข้าขั้นโพสต์")
        _say(f"   ตรวจไฟล์: {names}")
        _say("   ทุกจุดยังเป็นการกดหน้าจอจริงตามกติกา CLAUDE.md ข้อ 2.7")
        return 0

    _say(f"❌ เจอการละเมิดกติกาข้อ 2.7 จำนวน {len(hits)} จุด\n")
    for name, number, line, why in hits:
        _say(f"  {name}:{number}")
        _say(f"     {line}")
        _say(f"     ⤷ {why}\n")
    _say("การโพสต์ต้องเป็นการกดหน้าจอจริงทุกจุด ยกเว้นตอนเปิดแอปเท่านั้น")
    _say("เหตุผลเต็มอยู่ที่ CLAUDE.md ข้อ 2.7")
    return 1


if __name__ == "__main__":
    sys.exit(main())
