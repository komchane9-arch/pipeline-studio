"""ด่านตรวจ "การโพสต์ต้องกดหน้าจอจริง" — รันก่อนเพิ่มปลายทางใหม่ทุกครั้ง

    python publish_flow_check.py

กติกาเต็มอยู่ที่ `CLAUDE.md` ข้อ 2.7 (ผู้ใช้สั่งไว้ 25 ส.ค. 2569) ย่อได้ว่า
**ทุกการกระทำบนหน้าจอต้องผ่านระบบรับสัมผัสของ Android เหมือนนิ้วคนจริง**
ยกเว้นได้อย่างเดียวคือตอนเปิดแอป

คืนค่า 0 = ผ่าน · 1 = เจอการละเมิด (เอาไปต่อท้าย && ได้)


ตรวจอะไร และไม่ตรวจอะไร
───────────────────────────────────────────────────────────────────────────
ตรวจ **เฉพาะไฟล์ที่ทำหน้าที่โพสต์จริง** (`WATCHED`) ไม่กวาดทั้งโปรเจกต์
เพราะไฟล์ส่วนกลางมีสิทธิ์ถือของพวกนี้ไว้โดยชอบ — `app.py` เป็นคนให้บริการ
ช่องพิมพ์ผ่าน scrcpy สำหรับคนนั่งคุมมือถือเอง ซึ่งไม่ผิดกติกา

⚠️ **ด่านนี้กันการเรียกตรง ไม่ได้กันการเรียกผ่านคนกลาง**

ถ้ามีคนสร้างไฟล์ใหม่ (เช่น `phone_type.py`) ที่ห่อ scrcpy ไว้ข้างใน แล้วให้
`publish_flow.py` เรียกไฟล์นั้นแทน **ด่านจะมองไม่เห็นเลย** เพราะไฟล์กลาง
ไม่อยู่ในรายการตรวจ และตัวไฟล์โพสต์เองก็ไม่มีคำต้องห้ามสักคำ

ยังไม่เกิดจริง (ตรวจแล้ว ทั้งโปรเจกต์มี `app.py` ไฟล์เดียวที่แตะ scrcpy)
จึงยังไม่แก้ แต่ **ผ่านด่านนี้ไม่ได้แปลว่าปลอดภัยแน่นอน** ถ้าวันหนึ่งมีไฟล์
คนกลางแบบนั้นเกิดขึ้น ต้องเอาชื่อมันมาใส่ `WATCHED` ด้วย
(แชท pipeline-studio ชี้จุดนี้ไว้ 28 ส.ค. 2569)


ทำไมถึงเป็นสคริปต์ ไม่ใช่บรรทัด grep ในคอมเมนต์
───────────────────────────────────────────────────────────────────────────
ของเดิมเป็นสูตร `grep` เขียนไว้ในหัว `publish_flow.py` ให้คนคัดลอกไปรัน
พอ 28 ส.ค. 2569 สายกลางเพิ่ม `POST /api/phone/type` (ให้คนนั่งคุมมือถือพิมพ์
จากคีย์บอร์ดคอมได้) เราจะเติมคำนี้เข้าสูตรเพื่อกันไม่ให้ขั้นโพสต์หยิบไปใช้
**แต่พอกวาด `*.py` ทั้งหมด ด่านก็ไปจับตัวที่อยู่นั้นใน `app.py` ซึ่งมีอยู่โดยชอบ**

    app.py:3493:@app.post("/api/phone/type")        ← ไม่ใช่การละเมิด

ด่านที่เตือนผิดทุกครั้งจะถูกคนเลิกสนใจภายในไม่กี่วัน แล้วกลายเป็นด่านที่มีไว้เฉยๆ
(ฝั่งกลับของ `CLAUDE.md` ข้อ 2.3) การรู้ว่า **ที่ไหนผิด ที่ไหนถูก** ต้องเขียนลงไฟล์
ไม่ใช่ฝากไว้ในสูตรบรรทัดเดียว


ทำไมถึงแกะโครงสร้างโค้ด ไม่ใช่อ่านทีละบรรทัด
───────────────────────────────────────────────────────────────────────────
รอบแรกอ่านทีละบรรทัดแล้วข้ามบรรทัดที่ขึ้นต้นด้วย `#` **ซึ่งไม่พอ** —
คำอธิบายในเครื่องหมายคำพูดสามตัวยังโดนฟ้อง

    \"\"\"ห้ามใช้ scrcpy_control ในขั้นโพสต์\"\"\"      ← โดนฟ้องคำอธิบายตัวเอง

ตอนนั้นยังไม่เกิดปัญหาเพราะกรอบหัว `publish_flow.py` ใช้ `#` **แต่ใครก็ตามที่ไป
เขียนอธิบายข้อห้ามนี้ไว้ในคำอธิบายหัวฟังก์ชัน จะโดนด่านฟ้องคำอธิบายของตัวเอง**
แล้วพากลับไปสู่ปลายทางเดิม คือคนเลิกเชื่อด่าน

การไล่เพิ่มรูปแบบคอมเมนต์ทีละแบบเป็นการวิ่งไล่อาการ ไม่มีวันจบ
**ให้ Python แกะโครงสร้างไฟล์ให้แทน** แล้วดูเฉพาะของที่เป็นโค้ดจริง —
คอมเมนต์หายไปเองตั้งแต่ต้น และคำอธิบายตัดออกได้ตรงๆ ไม่ต้องเดารูปแบบ
(แชท pipeline-studio เสนอวิธีนี้ 28 ส.ค. 2569)
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

try:                                    # Python 3.7 ขึ้นไปเปลี่ยนได้ตรงๆ
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):       # ที่ไหนเปลี่ยนไม่ได้ก็ยังทำงานต่อได้
    pass

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
    r"scrcpy_control": "สั่งจอผ่านช่องควบคุม scrcpy — ไม่ใช่การกดจริงตามข้อ 2.7 "
                       "ขั้นโพสต์ต้องใช้ adb shell input / ADBKeyboard เท่านั้น",
}

# ─────────────────────────────────────────────────────────────────────────
# ทำไมถึงดักคำว่า `scrcpy_control` ทั้งคำ ไม่ใช่แค่ `send_text` กับ `send_key`
#
# ตอนแรกดักไว้แค่ `/api/phone/type` ซึ่งเป็น **ที่อยู่บนเว็บ** แชท pipeline-studio
# ลองยิงของผิดใส่ 4 บรรทัดแล้วพบว่า **ด่านปล่อยผ่านบรรทัดที่อันตรายที่สุด**
#
#     scrcpy_control.send_text(ADB, serial, "x")     ← ไม่โดนจับ
#     api("/api/phone/type")                         ← โดนจับ
#
# เพราะไฟล์ในนี้เป็น Python ด้วยกัน คนเขียนจะ `import scrcpy_control` แล้วเรียก
# ตรงๆ **ไม่มีเหตุผลอะไรให้ไปยิงผ่านที่อยู่เว็บของเซิร์ฟเวอร์ตัวเอง**
# ทางที่คนจะเผลอใช้จริง จึงเป็นทางที่ด่านเดิมมองไม่เห็น
#
# เขาเสนอให้เติมเฉพาะ `send_text` กับ `send_key` และเตือนว่าอย่าดักทั้งโมดูล
# เพราะ `send_touch` / `set_clipboard` ใช้ในหน้าคุมมือถือได้ตามปกติ
# **ข้อกังวลนั้นถูก แต่ไม่ตกกับด่านนี้** — ด่านนี้ตรวจเฉพาะไฟล์ที่โพสต์จริง
# ส่วนของที่ใช้โดยชอบทั้งหมดอยู่ใน `app.py` ซึ่งไม่ได้อยู่ในรายการตรวจ
# ตรวจของจริงแล้ว: ทั้งโปรเจกต์มี `app.py` ไฟล์เดียวที่แตะโมดูลนี้
#
# ดักทั้งโมดูลจึงได้ **ครอบคลุมกว่า โดยไม่เตือนผิดเพิ่มสักบรรทัด** และถ้าวันหนึ่ง
# มีคนต้องใช้จริงในไฟล์โพสต์ ก็ควรมาชนด่านแล้วให้เจ้าของตัดสิน ไม่ใช่ผ่านไปเงียบๆ
#
# **ยืนยันแล้วว่าเปลี่ยนชื่อเรียกหลบไม่ได้** — ยังไงก็ต้อง import ก่อนใช้
#     from scrcpy_control import send_text as t1     → จับที่บรรทัด import
#     import scrcpy_control as sc                    → จับที่บรรทัด import
# ─────────────────────────────────────────────────────────────────────────


def _docstring_nodes(tree: ast.AST) -> set[int]:
    """เก็บตำแหน่งของคำอธิบายทุกก้อน — พวกนี้เป็นเอกสาร ไม่ใช่โค้ดที่ทำงาน"""
    marked: set[int] = set()
    holders = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
    for node in ast.walk(tree):
        if not isinstance(node, holders):
            continue
        body = getattr(node, "body", None)
        if not body:
            continue
        first = body[0]
        if (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)):
            marked.add(id(first.value))
    return marked


def _dotted(node: ast.AST) -> str:
    """คืนชื่อแบบเต็มของสิ่งที่ถูกอ้างถึง เช่น `scrcpy_control.send_text`"""
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


def banned_aliases(tree: ast.AST) -> dict[str, str]:
    """หาชื่อย่อที่ผูกไว้กับของต้องห้าม เช่น `import scrcpy_control as sc` → `sc`

    ดักที่บรรทัด import อย่างเดียวก็พอจะจับไฟล์ได้แล้ว **แต่รายงานจะบอกแค่ว่า
    ผิดที่บรรทัด import** คนแก้ต้องไปไล่หาเองว่าเรียกใช้ตรงไหนบ้าง ตัวนี้จึงตาม
    ชื่อย่อไปชี้จุดที่เรียกจริงด้วย รายงานจะได้บอกครบว่าต้องแก้กี่ที่
    """
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                for needle, why in BANNED.items():
                    if re.search(needle, alias.name):
                        aliases[alias.asname or alias.name.split(".")[0]] = why
        elif isinstance(node, ast.ImportFrom):
            for needle, why in BANNED.items():
                if re.search(needle, node.module or ""):
                    for alias in node.names:
                        aliases[alias.asname or alias.name] = why
    return aliases


def code_units(tree: ast.AST) -> list[tuple[int, str]]:
    """คืนเฉพาะของที่เป็นโค้ดจริง — (บรรทัด, ข้อความที่จะเอาไปตรวจ)

    คอมเมนต์ไม่โผล่มาตรงนี้เลยเพราะ Python ทิ้งไปตั้งแต่ตอนแกะ
    ส่วนคำอธิบายถูกตัดออกด้วย `_docstring_nodes`
    """
    skip = _docstring_nodes(tree)
    units: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        line = getattr(node, "lineno", 0)
        if isinstance(node, ast.Import):
            units += [(line, alias.name) for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            units.append((line, node.module or ""))
            units += [(line, alias.name) for alias in node.names]
        elif isinstance(node, (ast.Attribute, ast.Name)):
            name = _dotted(node)
            if name:
                units.append((line, name))
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) not in skip:
                units.append((line, node.value))
    return units


def scan(root: Path = HERE) -> tuple[list[tuple[str, int, str, str]], list[str]]:
    """คืน (รายการละเมิด, รายชื่อไฟล์ที่แกะไม่ได้)

    ละเมิด = (ไฟล์, บรรทัด, เนื้อบรรทัดจริง, เหตุผล)
    """
    found: list[tuple[str, int, str, str]] = []
    broken: list[str] = []
    seen: set[Path] = set()

    for pattern in WATCHED:
        for path in sorted(root.glob(pattern)):
            if path in seen or not path.is_file():
                continue
            seen.add(path)
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
                tree = ast.parse(text)
            except (OSError, SyntaxError) as error:
                # แกะไม่ได้ = ตรวจไม่ได้ **ต้องดังขึ้น ห้ามนับว่าผ่าน**
                broken.append(f"{path.name} — {type(error).__name__}: {error}")
                continue

            lines = text.splitlines()
            aliases = banned_aliases(tree)
            hits: dict[int, str] = {}          # บรรทัดละครั้งเดียว
            for number, unit in code_units(tree):
                if number in hits:
                    continue
                head = unit.split(".")[0]
                if head in aliases:
                    hits[number] = aliases[head]
                    continue
                for needle, why in BANNED.items():
                    if re.search(needle, unit):
                        hits[number] = why
                        break
            for number in sorted(hits):
                raw = lines[number - 1].strip() if 0 < number <= len(lines) else ""
                found.append((path.name, number, raw[:110], hits[number]))
    return found, broken


def main() -> int:
    hits, broken = scan()

    if broken:
        print(f"⚠️ แกะไฟล์ไม่ได้ {len(broken)} ไฟล์ — ตรวจไม่ได้ ไม่ใช่ผ่าน\n")
        for row in broken:
            print(f"  {row}")
        print()

    if not hits:
        if broken:
            print("ไฟล์ที่เหลือไม่เจอทางลัด แต่ยังตรวจไม่ครบเพราะไฟล์ข้างบนเสีย")
            return 1
        print("✅ ผ่าน — ไม่มีทางลัดหลุดเข้าขั้นโพสต์")
        print(f"   ตรวจไฟล์: {', '.join(WATCHED)}")
        print("   ทุกจุดยังเป็นการกดหน้าจอจริงตามกติกา CLAUDE.md ข้อ 2.7")
        return 0

    print(f"❌ เจอการละเมิดกติกาข้อ 2.7 จำนวน {len(hits)} จุด\n")
    for name, number, line, why in hits:
        print(f"  {name}:{number}")
        print(f"     {line}")
        print(f"     ⤷ {why}\n")
    print("การโพสต์ต้องเป็นการกดหน้าจอจริงทุกจุด ยกเว้นตอนเปิดแอปเท่านั้น")
    print("เหตุผลเต็มอยู่ที่ CLAUDE.md ข้อ 2.7")
    return 1


if __name__ == "__main__":
    sys.exit(main())
