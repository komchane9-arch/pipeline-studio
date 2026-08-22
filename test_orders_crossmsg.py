# -*- coding: utf-8 -*-
"""เทสว่าข้อความข้ามแชทไม่ถูกจดเป็นคำสั่งงานอีกแล้ว — และของเดิมยังทำงานปกติ

**ที่มา** 22 ส.ค. 2569 พบว่าทะเบียนคำสั่ง 3 ใน 13 รายการเป็นของปลอม เกิดจาก
ข้อความที่แชทหนึ่งส่งไปหาอีกแชทถูกจดเป็น "คำสั่งงานจริง" แล้วระบบไล่จับชื่อไฟล์
จากเนื้อความมาตั้งเป็น "ไฟล์ที่กำลังทำ" ทั้งที่ไม่เคยแตะ → ด่านปักธงชนกันปลอมๆ
คู่เดียวเกิดซ้ำ 6 รอบในวันเดียว รอบละ 40,000-110,000 โทเคนที่ต้องเรียกเจ้าหน้าที่

ใช้ฐานแยก ไม่แตะ data จริง (กติกา 7.4)
"""
import os
import shutil
import sys
import tempfile

TMP = tempfile.mkdtemp(prefix="orderstest-")
os.environ["STUDIO_DATA_DIR"] = TMP
sys.path.insert(0, r"C:\project\2.Auto gen Video\8.pipeline studio")

import orders          # noqa: E402

ok = fail = 0


def check(name, got, want):
    global ok, fail
    if got == want:
        ok += 1
        print(f"  OK   {name}: {got}")
    else:
        fail += 1
        print(f"  FAIL {name}: ได้ {got!r} ควรได้ {want!r}")


print("=== 1. คำสั่งจริงจากเจ้าของ ต้องถูกจดตามปกติ ===")
row = orders.record("sess-A", "แชททดสอบ", "ช่วยแก้ app.py ให้หน่อย เรื่องหน่วงจอ")
check("จดหัวข้องาน", row["text"].startswith("ช่วยแก้ app.py"), True)
check("จับชื่อไฟล์ได้", "app.py" in row["files"], True)

print("=== 2. ข้อความข้ามแชท ต้องไม่ถูกจดเป็นคำสั่ง ===")
cross = ('<cross-session-message from="uds:\\\\.\\pipe\\cc-msg-x" from-name="webapp-video">\n'
         'แจ้งกันแก้ทับ — ผมแก้ clip_app.py กับ clip_store.py ไปแล้วนะครับ\n'
         '</cross-session-message>')
row = orders.record("sess-A", "แชททดสอบ", cross)
check("หัวข้องานไม่ถูกเขียนทับ", row["text"].startswith("ช่วยแก้ app.py"), True)
check("ไม่จับ clip_app.py มาใส่", "clip_app.py" in row["files"], False)
check("ไม่จับ clip_store.py มาใส่", "clip_store.py" in row["files"], False)
check("ไฟล์เดิมยังอยู่ครบ", "app.py" in row["files"], True)

print("=== 3. ข้อความระบบแบบอื่น ยังถูกกันเหมือนเดิม ===")
row = orders.record("sess-A", "แชททดสอบ", "<task-notification>งาน xyz เสร็จแล้ว fb_engage.py</task-notification>")
check("ไม่จับ fb_engage.py มาใส่", "fb_engage.py" in row["files"], False)

print("=== 4. คำตอบรับสั้นๆ ต้องไม่ล้างงานเดิม ===")
row = orders.record("sess-A", "แชททดสอบ", "ok")
check("หัวข้องานยังเดิม", row["text"].startswith("ช่วยแก้ app.py"), True)

print("=== 5. คำสั่งจริงอันใหม่ ยังเข้ามาแทนที่ได้ ===")
row = orders.record("sess-A", "แชททดสอบ", "เปลี่ยนใจ ไปแก้ web/phone.js แทน")
check("หัวข้องานเปลี่ยนตาม", row["text"].startswith("เปลี่ยนใจ"), True)
check("จับไฟล์ใหม่ได้", "web/phone.js" in row["files"], True)

print("=== 6. ข้อพิพาทปลอมต้องไม่เกิดอีก ===")
orders.record("sess-B", "แชทคลิป", "แก้ clip_app.py เรื่องปุ่มทำแล้ว")
cross_b = ('<cross-session-message from="x" from-name="แชทคลิป">\n'
           'ผมแก้ clip_app.py เสร็จแล้ว แจ้งให้ทราบ\n</cross-session-message>')
orders.record("sess-A", "แชททดสอบ", cross_b)
clash = orders.clashes("sess-A")
check("แชท A ไม่ถูกปักธงชนกับแชท B", len(clash), 0)

print("=== 7. บัตรตอกเวลา: แค่พูดถึงไฟล์เดียวกัน = เตือน ห้ามบล็อก ===")
orders.record("sess-C", "แชทซี", "ขอแก้ fb_report.py หน่อย")
orders.record("sess-D", "แชทดี", "เดี๋ยวผมดู fb_report.py ให้")
hits = orders.clashes("sess-C")
check("เจอว่าพูดถึงไฟล์เดียวกัน", len(hits) >= 1, True)
check("แต่ไม่ใช่ของจริง (ไม่มีใครตอกบัตรเข้า)",
      any(h.get("hard") for h in hits), False)

print("=== 8. อีกฝั่งตอกบัตรเข้าจริง = ต้องบล็อก ===")
import file_claims          # noqa: E402
file_claims.claim("fb_report.py", "แชทดี", why="ตอกบัตรเข้าจริง", session="sess-D")
hits = orders.clashes("sess-C")
check("คราวนี้เป็นของจริง", any(h.get("hard") for h in hits), True)
check("บอกไฟล์ที่ชนถูก", "fb_report.py" in sum((h["shared"] for h in hits), []), True)

print("=== 9. ตอกบัตรออกแล้ว = เลิกบล็อก ===")
file_claims.release("fb_report.py", "แชทดี", note="ทำเสร็จแล้ว")
hits = orders.clashes("sess-C")
check("กลับมาเป็นแค่เตือน", any(h.get("hard") for h in hits), False)

print(f"\nสรุป: ผ่าน {ok} · ไม่ผ่าน {fail}")
shutil.rmtree(TMP, ignore_errors=True)
sys.exit(1 if fail else 0)
