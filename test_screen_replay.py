"""เทสตัวตรวจหน้าจอ โดย **เล่นซ้ำผังจอจริงที่เก็บไว้แล้ว** — ไม่แตะมือถือเลย

**เจ้าของสั่ง 11 ก.ย. 2569** หลังผมชี้ว่าโฟลเดอร์ `data/evidence` เก็บผังจอจริง
ไว้ 342 ไฟล์ กับภาพ 509 ใบ รวม 367 MB **แต่ไม่เคยเอามาใช้ทดสอบเลย**

---

## ทำไมคุ้มมาก

ทุกการทดสอบวันนี้ต้องยิงใส่ TikTok ของจริง ใบละ 3-6 นาที และบางครั้ง
**โพสต์ขึ้นจริงแบบถอนไม่ได้** ทั้งที่สิ่งที่อยากรู้คือ *"ตัวตรวจตอบถูกไหม"*
ซึ่งตอบได้จากผังจอที่เก็บไว้แล้ว

    ยิงใส่ของจริง    3-6 นาที/รอบ · แย่งคิวมือถือ · เสี่ยงโพสต์ผิด
    เล่นซ้ำผังเก่า    เสี้ยววินาที · ไม่แตะมือถือ · ไม่มีความเสี่ยงใดๆ

ปัญหา "อ่านภาษาไทยไม่ออก" ที่ไล่กันทั้งวันวันนี้ ถ้ามีตัวนี้จะเจอใน 5 วินาที

## ความจริงที่ใช้ตัดสิน มาจากไหน

**ไม่ได้เขียนคำตอบเอาเองด้วยมือ** แต่อ่านจากตัวไฟล์หลักฐานโดยตรง

    มีกล่องระบบบัง      ผังมี package ของ permissioncontroller อยู่จริง
    อ่านชื่อปุ่มไม่ได้เลย  ไม่มี text/content-desc ที่ไม่ว่างสักอัน
    หน้าผลร้านค้า       มีทั้งคำว่า "ร้านค้า" และสัญลักษณ์ ฿

ตัวเลขที่วัดได้จากของจริง 342 ไฟล์: กล่องบัง 2 · อ่านไม่ได้ 9 · อ่านได้ 333

รันด้วย `python test_screen_replay.py` หรือ `python -m pytest test_screen_replay.py`
"""
from __future__ import annotations

import html
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import screen_read                                             # noqa: E402

EVIDENCE = Path(__file__).resolve().parent / "data" / "evidence"


def dumps() -> list[tuple[str, str]]:
    """ผังจอจริงทั้งหมดที่เก็บไว้ — คืน (ชื่อไฟล์, เนื้อผัง)"""
    rows = []
    for path in sorted(EVIDENCE.glob("*.xml")):
        try:
            rows.append((path.name, path.read_text(encoding="utf-8",
                                                   errors="replace")))
        except OSError:
            continue
    return rows


def labels_in(xml: str) -> set[str]:
    found = re.findall(r'(?:text|content-desc)="([^"]{1,60})"', html.unescape(xml))
    return {value for value in found if value.strip()}


# ------------------------------------------------------------------- เทส


def test_มีผังจอให้เล่นซ้ำจริง():
    rows = dumps()
    assert len(rows) >= 100, f"เจอผังจอแค่ {len(rows)} ไฟล์ — น้อยผิดปกติ"


def test_ตัวจับกล่องระบบไม่ตอบผิดสักไฟล์():
    """กล่องระบบต้องถูกจับได้ทุกไฟล์ที่มีจริง และห้ามจับผิดในไฟล์ที่ไม่มี

    **นี่คือตัวที่วันนี้ตอบผิดจนไล่ผิดทางหลายชั่วโมง** ตัวปิดคำชวนเดิมตอบว่า
    "ไม่มีคำชวนบังจอ" ทั้งที่มีกล่องขอสิทธิ์บังเต็มจอ
    """
    wrong = []
    for name, xml in dumps():
        truth = any(f'package="{pkg}"' in xml
                    for pkg in screen_read.SYSTEM_DIALOG_PACKAGES)
        got = bool(screen_read.blocking_system_dialog(xml))
        if truth != got:
            wrong.append(name)
    assert not wrong, f"ตอบผิด {len(wrong)} ไฟล์: {wrong[:3]}"


def test_ตัวตรวจไม่พังกับผังจอจริงสักไฟล์():
    """ผังจอจริงมีทุกรูปแบบ — ตัวตรวจต้องทนได้หมด ไม่ใช่ทนเฉพาะของที่แต่งเอง"""
    broke = []
    for name, xml in dumps():
        try:
            screen_read.blocking_system_dialog(xml)
            screen_read.thai_loose(xml[:400])
            view = screen_read.View(xml=xml, source="ระบบ", readable=True)
            view.has("ร้านค้า")
            view.any_of("ถัดไป", "โพสต์")
        except Exception as error:                             # noqa: BLE001
            broke.append(f"{name}: {type(error).__name__}: {error}")
    assert not broke, f"ตัวตรวจพัง {len(broke)} ไฟล์: {broke[:3]}"


def test_ตัวตรวจผลร้านค้าแยกหน้าถูกจากหน้าผิดได้():
    """`shop_results_visible` ต้องตอบใช่เฉพาะหน้าที่มีผลสินค้าจริง

    ของเดิมขึ้นต้นด้วย `if "ร้านค้า" not in plain: return False` ซึ่งทำให้
    ตอบ False ตลอดกาลบนเครื่องจริง เพราะชื่อแท็บอ่านไม่ได้
    """
    import tiktok_publish_bot as bot

    missed = []
    for name, xml in dumps():
        # หน้าที่มีทั้งชื่อแท็บและราคา = หน้าผลร้านค้าแน่นอน
        if "ร้านค้า" in xml and "฿" in xml:
            if not bot.shop_results_visible(xml):
                missed.append(name)
    assert not missed, f"หน้าผลร้านค้าที่ตอบว่าไม่ใช่ {len(missed)} ไฟล์: {missed[:3]}"


def test_ตัวตรวจผลร้านค้าต้องอ่านผังที่มาจากการอ่านตัวหนังสือบนภาพได้():
    """ทางที่ **ใช้จริงบนเครื่อง** แต่ไม่เคยมีเทสครอบเลย จนพลาดไปทั้งใบ

    หน้าผลร้านค้ามีนาฬิกานับถอยหลังเดินตลอด ผังจากระบบจึงอ่านไม่ได้
    ระบบเลยถอยไปอ่านตัวหนังสือจากภาพแทน — และตัวอ่านนั้น
    **คืนตัวพิมพ์เล็กเสมอ** กับ **อ่าน ฿ เป็นเลข 8**

    ของจริง 11 ก.ย. 2569 ใบงาน 29708428217 เวลา 16:48 — ภาพตอนล้มเห็น
    สินค้าขึ้นครบ 4 ใบพร้อมราคา แท็บร้านค้าถูกเลือกอยู่ แต่ตัวตรวจตอบว่า
    "ผลสินค้ายังไม่โหลด" แล้วทิ้งงานทั้งใบ เพราะเทียบชิปแบบตรงตัว
    """
    import tiktok_publish_bot as bot

    # คำที่ตัวอ่านภาพอ่านได้จริงจากภาพใบนั้น (คัดมาเฉพาะที่ตัวตรวจใช้)
    words = ["ถาม", "ดีที่สุด", "ร้านค้า", "วิดีโอ",
             "ตรงกันมากที่สุด", "สินค้าขายดี", "มีคะแนนสูงสุด", "กรอง",
             "mall", "สีขาว", "b66", "8143", "live", "topchoice",
             "8283.48 8363.48 3", "8179.75 8589.09 23", "876.45 8259.09 23"]
    ocr = ("<hierarchy source=\"ocr\">"
           + "".join(f'<node text="{w}" clickable="false" bounds="[0,0][1,1]"/>'
                     for w in words)
           + "</hierarchy>")
    assert bot.shop_results_visible(ocr), (
        "หน้าผลร้านค้าที่อ่านมาจากภาพต้องถูกนับว่าโหลดแล้ว")

    # และต้องไม่ตอบใช่กับหน้าที่ไม่มีผลสินค้า
    ว่าง = ('<hierarchy source="ocr">'
            '<node text="ถาม" clickable="false" bounds="[0,0][1,1]"/>'
            '<node text="ดีที่สุด" clickable="false" bounds="[0,0][1,1]"/>'
            '</hierarchy>')
    assert not bot.shop_results_visible(ว่าง), (
        "หน้าที่มีแค่ชื่อแท็บ ยังไม่มีสินค้า ต้องไม่ถูกนับว่าโหลดแล้ว")


def test_หน้าที่อ่านไม่ได้ต้องไม่ถูกนับว่าอ่านได้():
    """**หัวใจของกติกาข้อ 2.3.1** — "อ่านไม่ได้" ต้องไม่หน้าตาเหมือน "ไม่เจอ"

    ผังที่ไม่มีชื่อปุ่มสักอันแปลว่าอ่านอะไรไม่ได้เลย ตัวตรวจที่ไปถามว่า
    "เจอคำว่า X ไหม" กับผังแบบนี้จะได้คำตอบว่า "ไม่เจอ" เสมอ ซึ่งพาไป
    สรุปผิดว่าของนั้นไม่มีบนจอ ทั้งที่ความจริงคืออ่านไม่ออก
    """
    blind = [(n, x) for n, x in dumps() if not labels_in(x)]
    assert blind, "ไม่เจอผังที่อ่านไม่ได้เลยสักไฟล์ — ชุดทดสอบอาจไม่ครอบคลุม"
    for name, xml in blind:
        view = screen_read.View(xml=xml, source="ระบบ", readable=False,
                                why="หน้านี้ไม่ส่งตัวหนังสือออกมา")
        assert not view.readable, name
        assert view.why, f"{name}: อ่านไม่ได้แต่ไม่บอกเหตุผล"
        # ข้อความล้มต้องบอกสาเหตุจริง ไม่ใช่แค่ "ไม่พบ X"
        message = screen_read.why_not_found(view, "ไม่พบปุ่มค้นหา")
        assert "ไม่พบปุ่มค้นหา" in message and view.why in message, name


def test_เทียบคำแบบยอมวรรณยุกต์ตกใช้เฉพาะผังที่มาจากภาพ():
    """ผังจริงจากระบบต้องเทียบเป๊ะ — เทียบหลวมคือเปิดช่องให้กดผิดปุ่ม"""
    from_image = screen_read.View(words=["เพิม"], source="ภาพ", readable=True)
    from_system = screen_read.View(xml='<node text="เพิม"/>', source="ระบบ",
                                   readable=True)
    assert from_image.has("เพิ่ม"), "ผังจากภาพควรยอมให้ไม้เอกตก"
    assert not from_system.has("เพิ่ม"), "ผังจากระบบต้องเทียบเป๊ะ"


def test_แปลงยอดเล่นถูกทุกแบบ():
    import clip_results

    cases = {"0": 0, "39": 39, "1.2K": 1200, "1.2k": 1200, "12.5M": 12_500_000,
             "MALL": None, "12:36": None, "฿193": None, "": None}
    for text, want in cases.items():
        got = clip_results.to_number(text)
        assert got == want, f"{text!r} ควรได้ {want} แต่ได้ {got}"


def main() -> int:
    tests = [value for name, value in sorted(globals().items())
             if name.startswith("test_") and callable(value)]
    failed = 0
    print(f"เล่นซ้ำผังจอจริง {len(dumps())} ไฟล์ · เทส {len(tests)} ข้อ\n")
    for test in tests:
        name = test.__name__.replace("test_", "").replace("_", " ")
        try:
            test()
            print(f"  ✅ {name}")
        except AssertionError as error:
            failed += 1
            print(f"  ❌ {name}\n       {error}")
        except Exception as error:                             # noqa: BLE001
            failed += 1
            print(f"  ❌ {name}\n       เทสเองพัง: {type(error).__name__}: {error}")
    print(f"\n{'ผ่านหมด' if not failed else f'ไม่ผ่าน {failed} ข้อ'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
