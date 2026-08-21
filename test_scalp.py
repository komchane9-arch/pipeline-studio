# -*- coding: utf-8 -*-
"""เทสกล่องคำสั่งค้นหา + พนักงานเดินงาน — ใช้ฐานแยก ไม่แตะ data จริง (กติกา 7.4)"""
import os
import shutil
import sys
import tempfile

TMP = tempfile.mkdtemp(prefix="scalptest-")
os.environ["STUDIO_DATA_DIR"] = TMP
sys.path.insert(0, r"C:\project\2.Auto gen Video\8.pipeline studio")

import scalp_jobs as sj      # noqa: E402

ok = fail = 0


def check(name, got, want):
    global ok, fail
    if got == want:
        ok += 1
        print(f"  OK   {name}: {got}")
    else:
        fail += 1
        print(f"  FAIL {name}: ได้ {got!r} ควรได้ {want!r}")


print("=== 1. มาก่อนได้ก่อน ข้ามหัวข้อ ===")
a = sj.submit("shopee", "หูฟังบลูทูธ", "แชท shopee")
sj.submit("lazada", "เคสมือถือ", "แชท lazada")
sj.submit("lineman", "ชาไข่มุก", "แชท lineman")
sj.submit("shopeefood", "ข้าวมันไก่", "แชท shopeefood")
check("คิวรออยู่ 4 ใบ", len(sj.board()["queued"]), 4)
first = sj.claim_next("พนักงาน")
check("หยิบใบที่สั่งก่อนสุดได้ก่อน", first["chat"], "แชท shopee")
sj.finish(a, sj.DONE, "เสร็จ")
check("ใบถัดไปเรียงตามลำดับที่สั่ง", sj.claim_next("พนักงาน")["topic"], "lazada")

print("=== 2. กันสั่งซ้ำคำเดิม / หัวข้อมั่ว ===")
for label, args in (("คำเดิมซ้ำ", ("lineman", "ชาไข่มุก")), ("หัวข้อมั่ว", ("grab", "อะไรสักอย่าง"))):
    try:
        sj.submit(*args)
        check(label, "ไม่โยน", "โยน")
    except sj.JobError:
        check(f"{label} โยน error ตามคาด", "โยน", "โยน")

print("=== 3. ใบค้างตอนพนักงานเกิดใหม่ ต้องคืนเข้ากล่อง ===")
check("คืนเข้ากล่อง 1 ใบ", sj.reset_stuck("พนักงานคนใหม่"), 1)
check("ใบนั้นกลับเป็นรอคิว", sj.get(2)["state"], "queued")

print("=== 4. ติดธงรอคนตัดสิน ต้องไม่ขวางใบอื่น ===")
job = sj.claim_next("พนักงาน")
sj.finish(job["id"], sj.ATTENTION, "เจอ CAPTCHA")
check("ใบถัดไปยังหยิบได้ปกติ", sj.claim_next("พนักงาน") is not None, True)
check("ใบที่ติดธงโผล่ในหมวดรอคนตัดสิน", len(sj.board()["attention"]), 1)

print("=== 5. พนักงานเดินงานทำจริงหนึ่งใบ (ใช้ตัวทำงานปลอม) ===")
# ล้างกล่องก่อน — ไม่งั้นพนักงานจะหยิบใบเก่าจากข้อก่อนหน้ามาทำก่อนตามกติกา
# มาก่อนได้ก่อน (ซึ่งถูกแล้ว แต่ทำให้เทสข้อนี้วัดผิดใบ)
# ต้องล้างทั้งใบที่รอคิว **และใบที่ค้างสถานะกำลังทำ** เพราะพนักงานจะคืนใบค้าง
# เข้ากล่องตอนเกิดใหม่ แล้วมันจะมีเลขน้อยกว่าใบใหม่ = ได้ทำก่อน
_box = sj.board()
for _row in _box["queued"] + ([_box["running"]] if _box["running"] else []):
    sj.finish(_row["id"], sj.CANCELLED, "ล้างกล่องก่อนเทสข้อ 5")
import devices           # noqa: E402
import phone_queue       # noqa: E402
import scalp_worker      # noqa: E402

devices.upsert("SCALPDEV", name="เครื่องค้นหา (ทดสอบ)", enabled=True, lanes=["scalp"])
check("หาเครื่องสาย scalp เจอ", phone_queue.device_for_lane("scalp"), "SCALPDEV")

ran = []


def fake(job):
    # ต้องถือบัตรคิวอยู่จริงตอนทำงาน ไม่งั้นแปลว่าพนักงานไม่ได้เข้าคิว
    ran.append(phone_queue.holding("SCALPDEV") is not None)
    return "เก็บได้ 3 ชิ้น"


scalp_worker.HANDLERS[("shopee", "search")] = fake
job_id = sj.submit("shopee", "กระเป๋าผ้า", "แชท shopee")
scalp_worker.main(["--once"])
check("พนักงานถือบัตรคิวตอนลงมือจริง", ran, [True])
check("ปิดใบงานเป็นเสร็จแล้ว", sj.get(job_id)["state"], "done")
check("เก็บผลลัพธ์ไว้ให้แชทอ่าน", sj.get(job_id)["result"], "เก็บได้ 3 ชิ้น")
check("คืนคิวจอแล้ว ไม่ถือค้าง", phone_queue.holding("SCALPDEV"), None)

print("=== 6. ทางที่ยังไม่ได้เขียน ต้องล้มเสียงดัง ไม่ใช่เงียบ ===")
lazada_id = sj.submit("lazada", "รองเท้า", "แชท lazada")
while True:
    pending = sj.claim_next("พนักงาน")
    if pending is None:
        break
    scalp_worker.run_job(pending, "SCALPDEV")
row = sj.get(lazada_id)
check("ถูกติดธงว่ายังทำไม่ได้", row["state"], "attention")
check("บอกด้วยว่าขาดอะไร", "ยังไม่ได้เขียนตัวค้นหา" in row["note"], True)

print(f"\nสรุป: ผ่าน {ok} · ไม่ผ่าน {fail}")
shutil.rmtree(TMP, ignore_errors=True)
sys.exit(1 if fail else 0)
