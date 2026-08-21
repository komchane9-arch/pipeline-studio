# -*- coding: utf-8 -*-
"""เทสว่า `studio_shared.phone_lock()` ของเดิม ต่อเข้าคิวใหม่แล้วจริง

ทำไมต้องมีเทสนี้แยกจาก test_phone_queue.py — ตัวนั้นเทสคิวเปล่าๆ ส่วนตัวนี้เทส
**ของเดิมทั้ง 5 ไฟล์ที่เรียก phone_lock อยู่แล้ว** ว่าได้ลำดับคิวไปด้วยโดยไม่ต้อง
แก้ตัวเอง และที่สำคัญกว่านั้นคือ **ขอซ้อนในโปรเซสเดิมแล้วต้องไม่ค้าง**
(ของเดิมขอซ้อนได้ ถ้าชั้นคิวขอซ้อนไม่ได้ = รอตัวเองตลอดกาล)

ใช้ฐานแยก ไม่แตะ data จริง (กติกา 7.4)
"""
import os
import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="plqtest-"))
os.environ["STUDIO_DATA_DIR"] = str(TMP)
sys.path.insert(0, r"C:\project\2.Auto gen Video\8.pipeline studio")

import phone_queue as pq          # noqa: E402
import studio_shared              # noqa: E402

DEV = "LOCKTESTDEV"
ok = fail = 0


def check(name, got, want):
    global ok, fail
    if got == want:
        ok += 1
        print(f"  OK   {name}: {got}")
    else:
        fail += 1
        print(f"  FAIL {name}: ได้ {got!r} ควรได้ {want!r}")


print("=== 1. phone_lock ธรรมดา → ต้องโผล่บนกระดานคิว ===")
seen = {}
with studio_shared.phone_lock(DEV, label="โพสต์กลุ่มที่ 1", owner="แชท post"):
    rows = pq.board(DEV)
    seen["running"] = rows[0]["running"]["owner"] if rows and rows[0]["running"] else None
    seen["task"] = rows[0]["running"]["task"] if rows and rows[0]["running"] else None
check("กระดานเห็นว่าใครถืออยู่", seen["running"], "แชท post")
check("กระดานเห็นว่ากำลังทำอะไร", seen["task"], "โพสต์กลุ่มที่ 1")
check("ออกจาก with แล้วเคาน์เตอร์ว่าง", pq.board(DEV)[0]["running"] if pq.board(DEV) else None, None)

print("=== 2. ขอซ้อนในโปรเซสเดิม ต้องไม่ค้าง ===")
done = []


def nested():
    with studio_shared.phone_lock(DEV, label="ชั้นนอก", owner="แชท video"):
        with studio_shared.phone_lock(DEV, label="ชั้นใน", owner="แชท video"):
            done.append("ผ่าน")


th = threading.Thread(target=nested, daemon=True)
th.start()
th.join(timeout=20)
check("ขอซ้อนสองชั้นแล้วจบได้", done, ["ผ่าน"])

print("=== 3. มาก่อนได้ก่อน ข้ามเธรด ===")
order = []
started = threading.Event()


def worker(name, hold):
    with studio_shared.phone_lock(DEV, label=f"งาน {name}", owner=name, timeout=60):
        order.append(name)
        if name == "คนแรก":
            started.set()
        time.sleep(hold)


t1 = threading.Thread(target=worker, args=("คนแรก", 1.5), daemon=True)
t1.start()
started.wait(timeout=10)
time.sleep(0.3)
t2 = threading.Thread(target=worker, args=("คนที่สอง", 0.1), daemon=True)
t2.start()
time.sleep(0.4)
t3 = threading.Thread(target=worker, args=("คนที่สาม", 0.1), daemon=True)
t3.start()
for t in (t1, t2, t3):
    t.join(timeout=60)
check("ได้คิวตามลำดับที่มาจริง", order, ["คนแรก", "คนที่สอง", "คนที่สาม"])

print("=== 4. queue=False (แค่มาลองจับ) ต้องไม่กินที่ในแถว ===")
before = len(pq.history(DEV, 100))
try:
    with studio_shared.phone_lock(DEV, timeout=0.5, poll=0.2, label="ตรวจว่าว่างไหม",
                                  queue=False):
        pass
except studio_shared.PhoneBusy:
    pass
check("ไม่มีบัตรใบใหม่เกิดขึ้น", len(pq.history(DEV, 100)), before)

print("=== 5. งานจร (queue=False) ต้องถูกปฏิเสธถ้ามีคนถืออยู่ ===")
blocked = {}


def holder():
    with studio_shared.phone_lock(DEV, label="งานยาว", owner="แชท post", timeout=60):
        time.sleep(1.5)


th = threading.Thread(target=holder, daemon=True)
th.start()
time.sleep(0.5)
try:
    with studio_shared.phone_lock(DEV, timeout=0.5, poll=0.2, label="งานจร", queue=False):
        blocked["ผล"] = "เข้าไปได้ (ผิด)"
except studio_shared.PhoneBusy:
    blocked["ผล"] = "ถูกปฏิเสธ"
th.join(timeout=30)
check("งานจรโดนกันจริงตอนไม่ว่าง", blocked.get("ผล"), "ถูกปฏิเสธ")

print(f"\nสรุป: ผ่าน {ok} · ไม่ผ่าน {fail}")
shutil.rmtree(TMP, ignore_errors=True)
sys.exit(1 if fail else 0)
