"""ตรวจโครงสร้าง CSS ก่อนส่งขึ้นหน้าเว็บ — จับ "ปีกกาเกิน/ขาด" ที่นับแล้วไม่เห็น

**ที่มา** 27 ส.ค. 2569 ผมเขียน `web/styles.css` แล้วเผลอทิ้ง **ปีกกาปิดเกิน
1 ตัวกลางไฟล์** กับ **`@media` ที่เปิดค้างไม่ปิดท้ายไฟล์** สองอย่างนี้
**หักล้างกันพอดีในการนับ** — เปิด 505 ปิด 505 ตัวนับบอกว่าสมดุล

แต่ของจริงพังหนัก: ปีกกาลอยที่ระดับบนสุดทำให้เบราว์เซอร์กิน `@media` ก้อนถัดไป
เป็นชื่อ selector แล้ว **ทิ้งทั้งกฎ** ผลคือกฎ

    @media (max-width: 900px) { .layout { grid-template-columns: 1fr; } }

**ไม่เคยทำงานเลย** จอแคบจึงยังถูกบังคับเป็นสองคอลัมน์ ที่จอ 375 จุด
ช่องมือถือเหลือ 46 จุด ปุ่มข้างในกว้าง 46-86 จุดจึงทะลุออกไป ล้นขวา 95 จุด

**ทำไมตัวทดสอบของผมไม่จับ** — ผมวัด 11 ระดับซูมบนจอ 3792 ได้ความกว้าง
1896-7584 จุด **ทุกค่าเกิน 900 หมด** กฎที่พังจึงไม่เคยถูกเรียกใช้เลยสักครั้ง
และตอนอ่าน `document.styleSheets` ผมเห็นว่าค้นหา `.topbar` แล้วได้ **ลิสต์ว่าง**
ซึ่งเป็นสัญญาณว่าตัวเดินกฎมีปัญหา — **แต่ผมมองข้ามเพราะค่าที่คำนวณออกมาถูก**

ตรงกับกติกาข้อ 2.3 เป๊ะ: ตัวตรวจที่บอกว่าผ่านทั้งที่ยังไม่ผ่าน อันตรายกว่าไม่มีตัวตรวจ

วิธีใช้
    python css_check.py                 ตรวจทุกไฟล์ .css ใน web/
    python css_check.py web/styles.css  ตรวจไฟล์เดียว
คืน exit code 1 เมื่อเจอปัญหา — เอาไปต่อกับ hook หรือ CI ได้
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# ตัดคอมเมนต์กับข้อความในเครื่องหมายคำพูดออกก่อน ไม่งั้นปีกกาที่อยู่ข้างในถูกนับด้วย
_COMMENT_RE = re.compile(r"/\*.*?\*/", re.S)
_STRING_RE = re.compile(r"'[^'\n]*'|\"[^\"\n]*\"")


def _strip(text: str) -> str:
    """แทนคอมเมนต์/ข้อความด้วยช่องว่างเท่าเดิม เพื่อให้เลขบรรทัดไม่เพี้ยน"""
    def blank(match: re.Match) -> str:
        return re.sub(r"[^\n]", " ", match.group(0))
    return _STRING_RE.sub(blank, _COMMENT_RE.sub(blank, text))


def problems(text: str) -> list[str]:
    """คืนรายการปัญหาโครงสร้างที่เจอ — ลิสต์ว่าง = ผ่าน

    ตรวจสามอย่างที่การนับรวมมองไม่เห็น
      1. ปีกกาปิดเกินตอนที่ยังไม่มีอะไรเปิดค้าง (ปีกกาลอยที่ระดับบนสุด)
      2. ปีกกาเปิดค้างตอนจบไฟล์ — ของที่เขียนต่อท้ายจะตกไปอยู่ข้างในเงียบๆ
      3. `@media`/`@supports` ที่เปิดแล้วไม่ปิด — บอกเลขบรรทัดที่เปิดไว้
    """
    clean = _strip(text)
    found: list[str] = []
    stack: list[tuple[int, str]] = []      # (บรรทัดที่เปิด, หัวข้อของบล็อก)
    line_no = 1
    head = ""                              # ข้อความก่อนปีกกาเปิด ใช้บอกว่าบล็อกอะไร

    for char in clean:
        if char == "\n":
            line_no += 1
            head = ""
            continue
        if char == "{":
            stack.append((line_no, head.strip()[:60]))
            head = ""
        elif char == "}":
            if not stack:
                found.append(
                    f"บรรทัด {line_no}: **ปีกกาปิดเกิน** — ตรงนี้ไม่มีบล็อกเปิดค้างอยู่\n"
                    f"    ผลคือกฎก้อนถัดไปจะถูกกลืนเป็นชื่อ selector แล้วถูกทิ้งทั้งก้อน"
                )
            else:
                stack.pop()
        else:
            head += char

    for line, what in stack:
        found.append(
            f"บรรทัด {line}: **ปีกกาเปิดค้างไม่ปิด** ({what or 'ไม่ทราบชื่อบล็อก'})\n"
            f"    เบราว์เซอร์ปิดให้เองจึงยังทำงาน แต่ของที่เขียนต่อท้ายจะตกไปอยู่ข้างในเงียบๆ"
        )
    return found


def check(path: Path) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        return [f"อ่านไฟล์ไม่ได้: {error}"]
    return problems(text)


def main(argv: list[str]) -> int:
    targets = [Path(a) for a in argv[1:]]
    if not targets:
        targets = sorted(Path("web").glob("*.css"))
    if not targets:
        print("ไม่พบไฟล์ .css ให้ตรวจ")
        return 0

    bad = 0
    for path in targets:
        issues = check(path)
        opened = path.read_text(encoding="utf-8", errors="replace")
        counts = (opened.count("{"), opened.count("}"))
        if issues:
            bad += 1
            print(f"\n❌ {path}  (นับปีกกา เปิด {counts[0]} ปิด {counts[1]}"
                  + (" — **สมดุลแต่วางผิดที่**" if counts[0] == counts[1] else "") + ")")
            for issue in issues:
                print(f"   {issue}")
        else:
            print(f"✅ {path}  โครงสร้างถูกต้อง (ปีกกา {counts[0]} คู่)")
    if bad:
        print(f"\nเจอไฟล์ที่มีปัญหา {bad} ไฟล์ — แก้ก่อนส่งขึ้นหน้าเว็บ")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
