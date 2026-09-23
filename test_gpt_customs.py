# -*- coding: utf-8 -*-
"""ทะเบียน ChatGPT custom ของสายโปสเตอร์ — รันกับโฟลเดอร์ทดสอบ **ไม่แตะข้อมูลจริง**

    python test_gpt_customs.py

กติกาข้อ 7.4: ทดสอบห้ามแตะ data จริง — ไฟล์นี้ตั้ง STUDIO_DATA_DIR ไปที่โฟลเดอร์
ชั่วคราวก่อน import ทุกอย่าง แล้วลบทิ้งเมื่อจบ
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

TEMP = Path(tempfile.mkdtemp(prefix="customs-test-"))
os.environ["STUDIO_DATA_DIR"] = str(TEMP)

import gpt_customs as gc                                     # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass

ok = fail = 0


def check(label, got, want):
    global ok, fail
    if got == want:
        ok += 1
        print(f"  ✅ {label}")
    else:
        fail += 1
        print(f"  ❌ {label}\n       ได้ {got!r} · ต้องได้ {want!r}")


def refused(label, action):
    global ok, fail
    try:
        action()
    except gc.CustomError:
        ok += 1
        print(f"  ✅ {label}")
        return
    fail += 1
    print(f"  ❌ {label} — ควรปฏิเสธแต่ผ่าน")


try:
    assert str(gc.STORE).startswith(str(TEMP)), "ไม่ได้เขียนลงโฟลเดอร์ทดสอบ — หยุดก่อนแตะของจริง"
    print(f"(ทดสอบที่ {TEMP})")

    print("\n[1] ครั้งแรก — กล่อง Poster มีตัวอย่างให้ และเลือกไว้แล้ว")
    data = gc.load()
    check("กล่อง Poster มี 1 ตัว", len(data["poster"]["items"]), 1)
    check("ตัวอย่างถูกเลือกเป็นตัวที่ใช้", gc.selected("poster")["name"].startswith("นักสร้าง"), True)
    check("กล่อง Caption ยังว่าง", data["caption"]["items"], [])
    check("กล่องว่าง → ไม่มีตัวที่เลือก (ห้ามเดาให้)", gc.selected("caption"), None)

    print("\n[2] เพิ่มได้หลายตัว และตัวแรกของกล่องว่างถูกเลือกให้เอง")
    a = gc.add("caption", "แคปชันขายของ", "https://chatgpt.com/g/g-aaaa1111-caption")
    b = gc.add("caption", "แคปชันเล่าเรื่อง", "https://chatgpt.com/g/g-bbbb2222-story")
    check("มี 2 ตัวแล้ว", len(gc.load()["caption"]["items"]), 2)
    check("ตัวแรกที่เพิ่มถูกเลือกให้", gc.selected("caption")["id"], a["id"])

    print("\n[3] เพิ่มตัวใหม่ **ไม่เปลี่ยน** ตัวที่ใช้อยู่ (เลือกตัวไหนใช้ตัวนั้นจนกว่าจะเปลี่ยน)")
    check("ยังใช้ตัวแรกอยู่หลังเพิ่มตัวที่สอง", gc.selected("caption")["id"], a["id"])

    print("\n[4] เลือกเปลี่ยนแล้วใช้ตัวนั้นยาว")
    gc.use("caption", b["id"])
    check("เปลี่ยนเป็นตัวที่สองแล้ว", gc.selected("caption")["id"], b["id"])
    gc.add("caption", "ตัวที่สาม", "https://chatgpt.com/g/g-cccc3333-third")
    check("เพิ่มตัวที่สามแล้วก็ยังใช้ตัวที่สองอยู่", gc.selected("caption")["id"], b["id"])

    print("\n[5] สิ่งที่ต้องปฏิเสธ")
    refused("ลิงก์แชทธรรมดา /c/… ไม่ใช่ custom",
            lambda: gc.add("caption", "x", "https://chatgpt.com/c/68abc-123"))
    refused("ลิงก์เว็บอื่น", lambda: gc.add("caption", "x", "https://example.com/g/g-1"))
    refused("ลิงก์ซ้ำในกล่องเดียวกัน",
            lambda: gc.add("caption", "ซ้ำ", "https://chatgpt.com/g/g-aaaa1111-caption"))
    refused("ไม่ตั้งชื่อ", lambda: gc.add("caption", "  ", "https://chatgpt.com/g/g-dddd-4"))
    refused("กล่องที่ไม่มีอยู่จริง", lambda: gc.add("video", "x", "https://chatgpt.com/g/g-e-5"))
    refused("ลบตัวที่ใช้อยู่ (ต้องเลือกตัวอื่นก่อน)", lambda: gc.drop("caption", b["id"]))
    refused("เลือกรหัสที่ไม่มีอยู่", lambda: gc.use("caption", "nothere"))

    print("\n[6] ลบตัวที่ไม่ได้ใช้ได้ และกล่องอื่นไม่โดนผลกระทบ")
    gc.drop("caption", a["id"])
    check("เหลือ 2 ตัวในกล่อง Caption", len(gc.load()["caption"]["items"]), 2)
    check("กล่อง Poster ยังอยู่ครบ", len(gc.load()["poster"]["items"]), 1)

    print("\n[7] ลิงก์ที่มีหางต่อท้ายถูกตัดให้สะอาด")
    c = gc.add("comment", "คอมเมนต์", "https://chatgpt.com/g/g-ffff6666-cm/?model=gpt-4o")
    check("ตัด ?... และ / ท้ายทิ้ง", c["url"], "https://chatgpt.com/g/g-ffff6666-cm")
finally:
    shutil.rmtree(TEMP, ignore_errors=True)

print("\n" + "=" * 50)
print(f"ผ่าน {ok} · ไม่ผ่าน {fail}")
print("=" * 50)
sys.exit(1 if fail else 0)
