# -*- coding: utf-8 -*-
"""ด่านกันโพสต์ผิดโปรไฟล์ — พิสูจน์ว่าด่านใหม่แยกสองสถานะออกจริง

**ทำไมต้องมีเทสนี้** ด่านเดิมของสายคลิปถามว่า *"เห็นคำว่า Squishy Cute Club
บนจอไหม"* ซึ่งหน้าเมนูของ Facebook ตอบว่า "เห็น" ได้ทั้งตอนใช้เพจนั้นอยู่จริง
และตอนใช้เพจอื่นอยู่ — เพราะเมนูโชว์ชื่อเพจสองที่เสมอ คือหัวเมนู (โปรไฟล์ที่
ใช้อยู่) กับรายการทางลัดข้างล่าง (เพจอื่นที่กดสลับไปได้)

เทสนี้เอาผังจอทั้งสองสถานะมายิงใส่ตัวตรวจเก่าและตัวตรวจใหม่ แล้วยืนยันว่า
**ตัวเก่าตอบเหมือนกันทั้งสองสถานะ (= ตาบอด) ส่วนตัวใหม่แยกออก**

    python test_fb_profile_guard.py
"""
from __future__ import annotations

import sys

import fb_profile
import publish_flow

ok = fail = 0


def check(label: str, got, want) -> None:
    global ok, fail
    if got == want:
        ok += 1
        print(f"  ✅ {label}")
    else:
        fail += 1
        print(f"  ❌ {label}\n       ได้ {got!r} · ต้องได้ {want!r}")


def row(text: str, top: int) -> str:
    return (f'<node text="{text}" clickable="true" '
            f'bounds="[60,{top}][1020,{top + 90}]" />')


def menu_xml(header: str, shortcuts: list[str]) -> str:
    """ผังจอหน้าเมนู — เรียงตามของจริงที่อ่านมาจาก W4FYYPYTLFYLIFHM (22 ก.ย. 2569)

        เมนู · <ชื่อที่ใช้อยู่> · 1 · ทางลัดของคุณ · <ทางลัด…> · แดชบอร์ดมืออาชีพ

    ชื่อที่ใช้อยู่อยู่ **เหนือ** เส้น "ทางลัดของคุณ" ส่วนของที่อยู่ใต้เส้นเป็น
    ทางลัดกับเมนูย่อย — ตัวอ่านจึงหยิบแถวที่อยู่ล่างสุด*เหนือเส้น*
    """
    parts = ['<hierarchy>', row("เมนู", 60), row(header, 300), row("1", 420),
             row("ทางลัดของคุณ", 700)]
    parts += [row(name, 820 + i * 110) for i, name in enumerate(shortcuts)]
    parts.append(row("แดชบอร์ดมืออาชีพ", 820 + len(shortcuts) * 110))
    return "".join(parts) + '</hierarchy>'


SQUISHY = "Squishy Cute Club"
THAI = "ไท คัดมาแล้วครับ"

# สองสถานะนี้ต่างกันแค่ว่าใครอยู่หัวเมนู — **ชื่อทั้งสองโผล่ในทั้งสองใบ**
AS_SQUISHY = menu_xml(SQUISHY, [THAI, SQUISHY])
AS_THAI = menu_xml(THAI, [SQUISHY, THAI])

print("[1] ตัวตรวจเดิม (มีข้อความนี้โผล่บนจอ) แยกสองสถานะไม่ออก — นี่คือรากของบั๊ก")
check("อยู่ Squishy จริง → เจอข้อความ", bool(publish_flow.find_node(AS_SQUISHY, SQUISHY)), True)
check("อยู่ ไท อยู่ → **ก็ยังเจอข้อความ** (ด่านหลอก)",
      bool(publish_flow.find_node(AS_THAI, SQUISHY)), True)

print("\n[2] ตัวอ่านใหม่ อ่านชื่อเหนือเส้น 'ทางลัดของคุณ' ได้ถูกทั้งสองสถานะ")
check("อยู่ Squishy", fb_profile.read_menu_name(AS_SQUISHY), SQUISHY)
check("อยู่ ไท", fb_profile.read_menu_name(AS_THAI), THAI)

print("\n[3] อ่านไม่ได้ต้องคืนค่าว่าง ไม่ใช่เดาชื่อใดชื่อหนึ่ง")
check("ผังจอว่าง", fb_profile.read_menu_name(""), "")
check("ไม่ใช่หน้าเมนู (ไม่มีเส้นแบ่ง)", fb_profile.read_menu_name(row(SQUISHY, 300)), "")

print("\n[4] ชื่อเดียวกันที่สะกดคนละตัวพิมพ์ต้องนับว่าเป็นคนเดียวกัน")
# ทะเบียนเครื่องจด "Squishy cute club" ส่วนแอปเขียน "Squishy Cute Club"
check("ทะเบียน vs แอป", fb_profile.same_name("Squishy cute club", SQUISHY), True)
check("เว้นวรรคหัวท้าย", fb_profile.same_name("  " + THAI + " ", THAI), True)
check("คนละเพจต้องไม่เท่ากัน", fb_profile.same_name(THAI, SQUISHY), False)

print("\n[5] ด่านต้องโยนทิ้งเมื่อไม่รู้ว่าเครื่องไหน/ต้องเป็นใคร — ห้ามเดา")
for label, args in (("ไม่บอก serial", ("", SQUISHY)), ("ไม่บอกชื่อโปรไฟล์", ("XYZ", ""))):
    try:
        fb_profile.guard(*args)
        check(label, "ไม่โยน", "ต้องโยน ProfileError")
    except fb_profile.ProfileError:
        check(label, "โยน ProfileError", "โยน ProfileError")

print("\n[6] ตัวตรวจใหม่ต้องลงทะเบียนในรายการวิธีตรวจ ไม่งั้นบันทึกจากหน้าเว็บไม่ได้")
check("มี profile_is ใน VERIFY_KINDS", "profile_is" in publish_flow.VERIFY_KINDS, True)

print("\n[7] อัปเกรดผังที่บันทึกไว้แล้ว — ต้องดูโครง ไม่ใช่ดูแค่ชื่อขั้น")
with_menu = [
    {"id": "open_app", "kind": "open_app"},
    {"id": "menu_open", "kind": "tap", "find": "เมนู"},
    {"id": "check_page", "kind": "wait", "verify": "text_appears", "verify_text": SQUISHY},
    {"id": "menu_close", "kind": "key", "value": "BACK"},
]
publish_flow._upgrade_sequence("facebook_reels", with_menu)
check("ผังที่ยังมีขั้นเปิดเมนู → อัปเกรดเป็น profile_is",
      with_menu[2]["verify"], "profile_is")

# ผังจริงของเครื่องสายคลิป: ขั้น check_page ถูกเปลี่ยนไปเป็น "รอหน้าฟีด" แล้ว
# และขั้นเมนูถูกลบทิ้ง — แตะเข้าไปจะทำให้ล้มทุกใบตั้งแต่ขั้นที่ 2
feed_wait = [
    {"id": "open_app", "kind": "open_app"},
    {"id": "check_page", "kind": "wait", "verify": "text_appears",
     "verify_text": "คุณกำลังคิดอะไรอยู่"},
]
publish_flow._upgrade_sequence("facebook_reels", feed_wait)
check("ขั้นรอหน้าฟีดที่ชื่อ check_page เหมือนกัน → ห้ามแตะ",
      feed_wait[1]["verify"], "text_appears")
check("และห้ามเปลี่ยนข้อความที่รอ",
      feed_wait[1]["verify_text"], "คุณกำลังคิดอะไรอยู่")

print("\n[8] ผังตั้งต้นของ facebook_reels ต้องไม่เหลือด่านหลอกอีก")
default = {s["id"]: s for s in publish_flow.DEFAULT_SEQUENCES["facebook_reels"]}
check("check_page ใช้ profile_is", default["check_page"].get("verify"), "profile_is")

print("\n[9] ปลายทางที่ต้องผ่านด่านโปรไฟล์ต้องมี facebook_reels")
check("facebook_reels อยู่ในรายการ",
      "facebook_reels" in publish_flow.PROFILE_GUARD_TARGETS, True)

print("\n[10] ด่านต้องทำงานตอนโพสต์จริง และตอนกู้งานที่ล้มกลางทางด้วย")


class OneStep:
    """ผังปลอมขั้นเดียว — เทสสนใจแค่ว่าด่านถูกเรียกไหม ไม่ได้สนว่ากดอะไร"""

    PACKAGE = "com.facebook.katana"

    def sequence(self, target):
        return [publish_flow.Step(id="open_app", name="เข้าแอป", kind="open_app",
                                  value=self.PACKAGE, verify="none")]


def guard_calls(store, **kwargs) -> int:
    """นับว่าด่านโปรไฟล์ถูกเรียกกี่ครั้งเมื่อสั่งเดินผังแบบนี้"""
    hits = []
    original = publish_flow._profile_guard
    publish_flow._profile_guard = lambda ctx: hits.append(1) or "ปลอม"
    try:
        context = publish_flow.RunContext(
            serial="test", store=store,
            target="facebook_reels" if store.PACKAGE.endswith("katana") else "shopee_video",
            screen=(1080, 2400), tap=lambda x, y: None,
            type_text=lambda value: None, run_adb=lambda *a, **k: b"",
            log=lambda message: None)
        context.dump = lambda: ""
        context.signature = lambda: "x"
        publish_flow.run_flow(context, **kwargs)
    finally:
        publish_flow._profile_guard = original
    return len(hits)


class OneStepShopee(OneStep):
    PACKAGE = "com.shopee.th"


check("โพสต์เต็มผัง → ด่านต้องทำงาน", guard_calls(OneStep()), 1)
check("กู้งานที่ล้มกลางทาง (เริ่มขั้น 5) → **ด่านต้องทำงานด้วย**",
      guard_calls(OneStep(), start_at=5), 1)
check("เดินทีละขั้นตอนเทรนผัง → ข้ามด่าน",
      guard_calls(OneStep(), start_at=1, stop_after=1), 0)
check("Shopee Video เป็นคนละแอป → ต้องไม่ไปตรวจโปรไฟล์ Facebook",
      guard_calls(OneStepShopee()), 0)

print("\n" + "=" * 56)
print(f"ผ่าน {ok} · ไม่ผ่าน {fail}")
print("=" * 56)
sys.exit(1 if fail else 0)
