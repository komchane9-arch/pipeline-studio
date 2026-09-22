# -*- coding: utf-8 -*-
"""ตัวอ่านหน้าจอของ "โพสต์ลงเพจ" — ยิงใส่ **ผังจอจริงที่เก็บมาจากเครื่อง**

ทุกเคสในนี้มาจากรอบที่พังจริงเมื่อ 22 ก.ย. 2569 ไม่ได้คิดขึ้นเอง
สามรอบแรกที่พังคือเพราะเดาว่าปุ่มอยู่ตรงไหนแล้วเดาผิด — เทสนี้จึงล็อกไว้ว่า
ถ้า Facebook เปลี่ยนหน้าตาจนตัวอ่านเพี้ยน จะรู้ตั้งแต่ก่อนแตะมือถือ

    python test_fb_page_post.py

ผังจอจริงเก็บไว้ที่ `testdata/fb_page/` — ดึงมาจาก W4FYYPYTLFYLIFHM (720x1600)
ตอนเปิดหน้าเพจ "ไท คัดมาแล้วครับ" เคสที่ไม่มีผังจริงเก็บไว้ (แผงคอมเมนต์)
ประกอบขึ้นจาก **ป้ายกับพิกัดที่จดไว้จาก log ของรอบจริง** ไม่ได้แต่งตัวเลขเอง
"""
from __future__ import annotations

import sys
from pathlib import Path

import facebook_page_post as pp

HERE = Path(__file__).resolve().parent
DATA = HERE / "testdata" / "fb_page"
ok = fail = 0


def check(label: str, got, want) -> None:
    global ok, fail
    if got == want:
        ok += 1
        print(f"  ✅ {label}")
    else:
        fail += 1
        print(f"  ❌ {label}\n       ได้ {got!r} · ต้องได้ {want!r}")


def node(text: str, x1: int, y1: int, x2: int, y2: int, clickable: bool = True) -> str:
    return (f'<node content-desc="{text}" clickable="{str(clickable).lower()}" '
            f'bounds="[{x1},{y1}][{x2},{y2}]" />')


# ============================================================ ผังจอจริง
REAL = (DATA / "page-post-with-bar.xml").read_text(encoding="utf-8")
TWO_BARS = (DATA / "page-two-bars.xml").read_text(encoding="utf-8")

print("[1] ผังจอจริงของโพสต์เราบนหน้าเพจ — ต้องได้พิกัดเดียวกับที่แตะแล้วติดจริง")
caption = pp.find_text_box(REAL, "เสียดาย เดือ")
check("เจอกรอบแคปชัน", caption is not None, True)
bar = pp.find_action_bar(REAL, below=caption[3])
check("ปุ่มคอมเมนต์ (มีป้ายกำกับ)", bar["comment"], (132, 1499))
check("ปุ่มแชร์ (มีป้ายกำกับ)", bar["share"], (220, 1499))
# **หัวใจของไฟล์นี้** — ปุ่มถูกใจไม่มีป้ายเลย ต้องคำนวณจากความกว้างปุ่มคอมเมนต์
# ค่า 44 คือจุดที่แตะแล้วไลก์ติดจริงเมื่อ 22 ก.ย. 16:28 (จอขึ้น 👍 1)
check("ปุ่มถูกใจ คำนวณได้ตรงกับที่แตะแล้วติดจริง", bar["like"], (44, 1499))

print("\n[2] มีหลายโพสต์บนจอเดียวกัน — ต้องหยิบแถบของโพสต์ที่เราชี้เท่านั้น")
first = pp.find_action_bar(TWO_BARS)
second = pp.find_action_bar(TWO_BARS, below=first["y"] + 1)
check("แถบแรกอยู่บนสุด", first["y"], 247)
check("บอกว่า 'เอาตัวที่อยู่ใต้ y นี้' แล้วได้แถบถัดไป", second["y"], 1421)
# การ์ดคนละแบบปุ่มกว้างไม่เท่ากัน (88 กับ 115) — พิกัดจึงต้องคำนวณ ห้ามฝังตาย
check("การ์ดที่ปุ่มกว้างกว่า ได้พิกัดถูกใจคนละค่า", first["like"], (31, 247))

print("\n[3] ฟอง 'สร้างโน้ต' บนหน้าเพจ ห้ามถูกนับเป็นปุ่มคอมเมนต์")
# ป้ายจริงจากผังจอ: 'สร้างโน้ต: แสดงความคิดเห็น…' ที่ [230,176][489,292]
note_only = ("<hierarchy>"
             + node("สร้างโน้ต: แสดงความคิดเห็น…", 230, 176, 489, 292)
             + node("ปุ่มแชร์ แตะสองครั้งเพื่อแชร์โพสต์", 489, 176, 600, 292)
             + "</hierarchy>")
check("มีแต่ฟองโน้ต → ต้องไม่เจอแถบปุ่ม", pp.find_action_bar(note_only), None)

print("\n[4] แถบปุ่มต้องมีปุ่มแชร์อยู่ขวามือด้วย ไม่งั้นไม่นับ")
lonely = "<hierarchy>" + node("แสดงความคิดเห็น", 88, 400, 176, 488) + "</hierarchy>"
check("เจอปุ่มคอมเมนต์ลอยๆ ตัวเดียว → ไม่นับเป็นแถบปุ่ม", pp.find_action_bar(lonely), None)

# ============================================================ แผงคอมเมนต์
# ป้ายกับพิกัดทั้งหมดในหัวข้อนี้คัดมาจาก log ของรอบจริง 22 ก.ย. 16:31–16:39
SHEET = ("<hierarchy>"
         # การ์ดสินค้า Shopee ที่คอมเมนต์ก่อนหน้าดึงมา — **กับดักของปุ่มส่ง**
         + node("ลิงก์ที่แชร์: s.shopee.co.th, ใหม่ พร้อมส่ง 4G/5G Wifi 8000mAh", 120, 520, 696, 620)
         + node("ส่งฟรี ร้านโค้ดคุ้ม", 60, 640, 300, 700)
         # แถวปุ่มของคอมเมนต์ที่ 1
         + node("ตอบกลับความคิดเห็นของ ไท คัดมาแล้วครับ, ปุ่ม", 104, 650, 230, 715)
         + node("ถูกใจปุ่มแสดงความคิดเห็นของ ไท คัดมาแล้วครับ", 552, 650, 616, 715)
         + node("โหวตลดอันดับความคิดเห็นของ ไท คัดมาแล้วครับ", 640, 650, 704, 715)
         # ช่องพิมพ์กับปุ่มส่ง — ตรึงอยู่ล่างจอเสมอ
         + node("แสดงความคิดเห็นในชื่อ ไท คัดมาแล้วครับ", 48, 1380, 672, 1450)
         + node("ส่ง", 640, 1386, 704, 1450)
         + "</hierarchy>")
HEIGHT = 1600

print("\n[5] ปุ่มส่ง — ห้ามไปโดนคำว่า 'พร้อมส่ง' ในการ์ดสินค้า (เกิดจริง เด้งออกไป Shopee)")
check("ได้ปุ่มส่งตัวจริงที่มุมล่างขวา", pp.find_send_button(SHEET, HEIGHT), (672, 1418))

trap = ("<hierarchy>"
        + node("ใหม่ พร้อมส่ง 4G/5G Wifi 8000mAh แบบพกพา 2in1", 120, 540, 696, 600)
        + "</hierarchy>")
check("มีแต่คำว่า 'พร้อมส่ง' กลางจอ → ต้องไม่คืนอะไรเลย",
      pp.find_send_button(trap, HEIGHT), None)

high = "<hierarchy>" + node("ส่ง", 640, 300, 704, 360) + "</hierarchy>"
check("ป้าย 'ส่ง' ตรงเป๊ะแต่อยู่ครึ่งบน → ยังไม่นับ (ปุ่มจริงตรึงอยู่ล่าง)",
      pp.find_send_button(high, HEIGHT), None)

print("\n[6] ช่องพิมพ์คอมเมนต์ของเพจเขียนคนละอย่างกับของกลุ่ม")
check("เจอช่องพิมพ์แบบเพจ", pp.find_comment_field(SHEET), (360, 1415))
group_style = ("<hierarchy>" + node("เขียนความคิดเห็นสาธารณะ", 48, 1380, 672, 1450)
               + "</hierarchy>")
check("แบบกลุ่มก็ยังต้องเจอ (ใช้ร่วมกันได้)", pp.find_comment_field(group_style), (360, 1415))
check("ยังไม่เปิดแผง → ต้องได้ None", pp.find_comment_field(lonely), None)

print("\n[7] ปุ่มถูกใจของคอมเมนต์ ต้องผูกกับคอมเมนต์ที่ชี้ ไม่ใช่ตัวแรกบนจอ")
spot = pp.find_comment_like(SHEET, below=600)
check("เจอปุ่มถูกใจของคอมเมนต์", spot[0], (584, 682))
check("ยังไม่ได้ไลก์", spot[1], False)
check("ถ้าชี้ต่ำกว่าปุ่มนั้น → ต้องไม่เจอ (กันกดของคอมเมนต์อื่น)",
      pp.find_comment_like(SHEET, below=900), None)

liked = ("<hierarchy>"
         + node("ได้มีการกดปุ่ม ถูกใจ ไปแล้ว แตะสองครั้งและแตะค้างไว้เพื่อเปลี่ยน",
                552, 650, 616, 715)
         + "</hierarchy>")
got = pp.find_comment_like(liked, below=600)
check("ไลก์ไปแล้ว → ต้องบอกว่าไลก์แล้ว (กดซ้ำ = ยกเลิกไลก์)", got[1], True)

print("\n[8] ชิ้นข้อความที่ใช้ยืนยันว่าคอมเมนต์เข้าครบ")
C1 = ("📍Pocket wifi แชร์ได้หลายเครื่อง แบตอึดใช้แทน powerbank ได้เลย \n\n"
      "https://s.shopee.co.th/2qUgVhUanu\nhttps://s.lazada.co.th/s.ZjGyIY?c=s")
probes = pp.comment_probes(C1)
check("ตัดอีโมจินำหน้าออกแล้วเอาท่อนแรก", probes[0], "Pocket wifi แช")
check("เก็บรหัสท้ายลิงก์ไว้ยืนยันว่าเข้าครบ ไม่ใช่แค่บรรทัดแรก",
      "2qUgVhUanu" in probes, True)
check("ข้อความว่าง → ไม่มีอะไรให้ยืนยัน", pp.comment_probes("   "), [])

print("\n[9] หาข้อความที่ไม่มีบนจอ ต้องคืน None ไม่ใช่เดาตำแหน่ง")
check("ไม่มีข้อความนี้", pp.find_text_box(REAL, "ข้อความที่ไม่มีอยู่จริงบนจอนี้"), None)
check("ส่งคำค้นว่างมา", pp.find_text_box(REAL, ""), None)

print("\n" + "=" * 58)
print(f"ผ่าน {ok} · ไม่ผ่าน {fail}")
print("=" * 58)
sys.exit(1 if fail else 0)
