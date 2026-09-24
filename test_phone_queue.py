# -*- coding: utf-8 -*-
"""เทสที่กดบัตรคิว — ใช้ฐานแยก ไม่แตะ data จริง (กติกา 7.4)"""
import os, sys, tempfile, threading, time, shutil
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="pqtest-"))
os.environ["STUDIO_DATA_DIR"] = str(TMP)
sys.path.insert(0, r"C:\project\2.Auto gen Video\8.pipeline studio")
import phone_queue as pq

DEV = "TESTDEV1"
DEV2 = "TESTDEV2"
ok = fail = 0

def check(name, got, want):
    global ok, fail
    if got == want:
        ok += 1; print(f"  OK   {name}: {got}")
    else:
        fail += 1; print(f"  FAIL {name}: ได้ {got!r} ควรได้ {want!r}")

print("=== 1. มาก่อนได้ก่อน (FIFO) ===")
a = pq.take(DEV, "แชท shopee", "ค้นหา A")
b = pq.take(DEV, "แชท lazada", "ค้นหา B")
c = pq.take(DEV, "แชท lineman", "ค้นหา C")
check("ใบแรกได้ทำเลย", pq.status(a)["state"], "running")
check("ใบสองยืนลำดับ 1", pq.position(b), 1)
check("ใบสามยืนลำดับ 2", pq.position(c), 2)

print("=== 2. เสร็จแล้วคนถัดไปเข้าทันที ===")
pq.finish(a, pq.DONE, "เสร็จ")
check("ใบสองได้ทำต่อ", pq.status(b)["state"], "running")
check("ใบสามเลื่อนเป็นลำดับ 1", pq.position(c), 1)

print("=== 3. หนึ่งเครื่องทำได้ทีละคนเท่านั้น ===")
running = [r for r in [pq.status(b), pq.status(c)] if r["state"] == "running"]
check("มีคนทำอยู่คนเดียว", len(running), 1)

print("=== 4. คนละเครื่องไม่ขวางกัน ===")
d = pq.take(DEV2, "แชท shopeefood", "ค้นหา D")
check("เครื่องที่สองได้ทำเลยทั้งที่เครื่องแรกไม่ว่าง", pq.status(d)["state"], "running")

print("=== 5. คนเดิมกดบัตรซ้ำเครื่องเดิมไม่ได้ ===")
duplicate_state_before = pq.status(c)["state"]
try:
    pq.take(DEV, "แชท lineman", "ซ้ำ")
    check("ต้องโยน error", "ไม่โยน", "โยน")
except pq.QueueError as e:
    check("โยน error ตามคาด", "โยน", "โยน")
    check("บัตรซ้ำแยกเป็น QueueBusy", isinstance(e, pq.QueueBusy), True)
    check("ไม่ยกเลิกบัตรของงานเดิม", pq.status(c)["state"], duplicate_state_before)

print("=== 6. ห้ามเว้น serial ว่าง ===")
try:
    pq.take("", "ใครสักคน", "งาน")
    check("ต้องโยน error", "ไม่โยน", "โยน")
except pq.QueueError:
    check("โยน error ตามคาด", "โยน", "โยน")

print("=== 7. คนถือบัตรหายไป ระบบตัดให้แล้วเรียกคิวถัดไป ===")
pq.STALE_RUNNING = 1.0                # คนกำลังทำหายไปเร็ว
time.sleep(1.4)                       # ปล่อยให้ b (กำลังทำ) ขาดชีพจร
pq.beat(c)                            # c ยังยืนรออยู่จริง เต้นชีพจรตามปกติ
pq._settle(pq.connect(), DEV)
check("คนกำลังทำที่หายไปถูกตัด", pq.status(b)["state"], "gone")
check("คนยืนรอไม่โดนตัดไปด้วย แล้วได้ทำแทน", pq.status(c)["state"], "running")
pq.STALE_RUNNING = 90.0

print("=== 8. รอคิวจริงด้วยสองเธรด — เสร็จปุ๊บอีกตัวเข้าใน ~1 วิ ===")
pq.finish(c, pq.DONE)
first = pq.take(DEV, "งานหน้า", "ถือจอ 2 วิ")
second = pq.take(DEV, "งานหลัง", "รอคิว")
got_at = {}
def waiter():
    t0 = time.time()
    pq.wait_turn(second, timeout=30)
    got_at["sec"] = time.time() - t0
th = threading.Thread(target=waiter); th.start()
time.sleep(2.0)
pq.finish(first, pq.DONE)
th.join(timeout=10)
delay = got_at.get("sec", 99)
check("งานหลังเริ่มหลังงานหน้าจบ", round(delay) in (2, 3), True)
print(f"       (ได้คิวหลังจากเริ่มรอ {delay:.2f} วิ · งานหน้าถือจอ 2.0 วิ)")

print("=== 9. with slot() คืนคิวเองแม้งานพัง ===")
pq.finish(second, pq.DONE)
try:
    with pq.slot(DEV, "งานที่พัง", "ทดสอบ") as t:
        raise ValueError("จำลองงานพัง")
except ValueError:
    pass
rows = [r for r in pq.history(DEV, 5) if r["owner"] == "งานที่พัง"]
check("บัตรถูกปิดเป็น failed", rows[0]["state"] if rows else "ไม่มี", "failed")
check("เคาน์เตอร์ว่างต่อได้", pq.board(DEV)[0]["running"], None)

print("=== 10. ด่านกันลืม: ยิง ADB โดยไม่กดบัตร ===")
try:
    pq.require_slot(DEV, "adb shell input tap")
    check("ต้องโยน error", "ไม่โยน", "โยน")
except pq.QueueError:
    check("ไม่มีบัตร = โยน error ตามคาด", "โยน", "โยน")

with pq.slot(DEV, "งานที่ทำถูกกติกา", "แตะจอ") as t:
    check("ถือบัตรอยู่ = ผ่านด่าน", pq.require_slot(DEV, "adb shell"), t)
check("ออกจาก with แล้วไม่ถือบัตรค้าง", pq.holding(DEV), None)

print("=== 11. โหมดจดอย่างเดียว (ด่าน 2) ===")
pq.ENFORCE = False
check("ไม่บังคับ = ปล่อยผ่าน", pq.require_slot(DEV, "ทดสอบโหมดจด"), None)
check("แต่ต้องจดไว้ว่าใครลืม", pq.BYPASS_LOG.exists(), True)
pq.ENFORCE = True

print(f"\nสรุป: ผ่าน {ok} · ไม่ผ่าน {fail}")
shutil.rmtree(TMP, ignore_errors=True)
sys.exit(1 if fail else 0)
