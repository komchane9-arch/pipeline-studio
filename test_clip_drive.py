"""เทส clip_drive.py — ทุกเคสใช้โฟลเดอร์ชั่วคราว ไม่แตะ data จริง ไม่แตะ Drive จริง

"Drive" ในเทสนี้คือโฟลเดอร์ธรรมดาในเครื่อง เพราะสิ่งที่ต้องพิสูจน์คือ **ตรรกะ**
(ยกอะไร ข้ามอะไร เปลี่ยนชื่อยังไง โครงเปลี่ยนรุ่นแล้วรื้อของเก่าไหม พังแล้วบอกไหม)
ไม่ใช่ตัว Google Drive ส่วนเรื่องที่พิสูจน์ได้เฉพาะบน Drive จริง (atomic replace ·
ภาษาไทย · ความเร็ว) วัดแยกไปแล้วและรันของจริงซ้ำหลังเทสชุดนี้ผ่าน
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import clip_drive                                            # noqa: E402

PASS = 0
FAIL = 0
NOTES: list[str] = []


def check(name: str, got, want) -> None:
    global PASS, FAIL
    if got == want:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        NOTES.append(f"{name}\n       ได้: {got!r}\n       ควรได้: {want!r}")
        print(f"  ❌ {name}\n       ได้: {got!r}\n       ควรได้: {want!r}")


def truthy(name: str, got, want: bool = True) -> None:
    check(name, bool(got), want)


class Bench:
    """ที่ทำงานชั่วคราวหนึ่งชุด — data ปลอม + "Drive" ปลอม"""

    def __init__(self, config: dict | None = None):
        self.home = Path(tempfile.mkdtemp(prefix="clipdrive-test-"))
        self.data = self.home / "data"
        self.drive = self.home / "drive"
        self.data.mkdir(parents=True)
        self.drive.mkdir(parents=True)
        merged = {"clipdrive_folder": str(self.drive)}
        merged.update(config or {})
        (self.data / "config.json").write_text(
            json.dumps(merged, ensure_ascii=False), encoding="utf-8")

    def product(self, item_id: str, name: str = "สินค้าทดสอบ", *,
                frames: int = 2, videos: int = 1, images: int = 3,
                script: list[str] | None = None,
                prompts: list[str] | None = None,
                publish: dict | None = None,
                caption: str = "") -> Path:
        folder = self.data / "shopee_products" / item_id
        (folder / "storyboard").mkdir(parents=True, exist_ok=True)
        (folder / "video").mkdir(parents=True, exist_ok=True)
        run = {
            "item_id": item_id, "name": name,
            "highlights": ["จุดเด่นหนึ่ง", "จุดเด่นสอง"],
            "affiliate_url": "https://s.shopee.co.th/ทดสอบ",
            "storyboard": [f"storyboard/storyboard-{i:02d}.png" for i in range(1, frames + 1)],
            "videos": [f"video/clip-{i:02d}.mp4" for i in range(1, videos + 1)],
            "script": script if script is not None else ["บรรทัดหนึ่ง", "บรรทัดสอง"],
            "flow_prompts": prompts if prompts is not None else ["คำสั่งฉากหนึ่ง"],
        }
        if publish is not None:
            run["publish"] = publish
        if caption:
            run["caption"] = caption
        (folder / "run.json").write_text(
            json.dumps(run, ensure_ascii=False, indent=2), encoding="utf-8")
        (folder / "prompts.json").write_text("[]", encoding="utf-8")
        (folder / "script.json").write_text("[]", encoding="utf-8")
        (folder / "detail.txt").write_text("รายละเอียดสินค้า", encoding="utf-8")
        (folder / "gpt-storyboard.md").write_text("# คำตอบดิบ", encoding="utf-8")
        for i in range(1, frames + 1):
            (folder / "storyboard" / f"storyboard-{i:02d}.png").write_bytes(b"PNG" + bytes(200))
        for i in range(1, videos + 1):
            (folder / "video" / f"clip-{i:02d}.mp4").write_bytes(b"MP4" + bytes(5000))
        for i in range(1, images + 1):
            (folder / f"{i:02d}.jpg").write_bytes(b"JPG" + bytes(1000))
        return folder

    def out(self, *parts) -> Path:
        """พาธใต้โฟลเดอร์ของเราบน "Drive" ปลอม"""
        return self.drive.joinpath("pipeline-studio", *parts)

    def item(self, name: str, *parts) -> Path:
        """พาธในมุมมอง "ตามสินค้า" """
        return self.out(clip_drive.BY_PRODUCT, name, *parts)

    def cat(self, *parts) -> Path:
        """พาธในมุมมอง "ตามหมวด" """
        return self.out(clip_drive.BY_CATEGORY, *parts)

    def close(self) -> None:
        shutil.rmtree(self.home, ignore_errors=True)


# ------------------------------------------------------------------ 1 ชื่อ

print("\n[1] ชื่อโฟลเดอร์ที่ปลอดภัย")
check("ตัดอักขระที่ Windows ห้าม", clip_drive.safe_name('เสื้อ/ยืด:ผ้า*ดี?'), "เสื้อ ยืด ผ้า ดี")
check("ยุบช่องว่างซ้ำ", clip_drive.safe_name("ก    ข     ค"), "ก ข ค")
check("ตัดจุดท้ายชื่อ (Windows ตัดเงียบ)", clip_drive.safe_name("สินค้าดี..."), "สินค้าดี")
check("ตัดช่องว่างท้ายชื่อ", clip_drive.safe_name("สินค้า   "), "สินค้า")
check("ชื่อว่าง = ไม่มีชื่อ", clip_drive.safe_name(""), "ไม่มีชื่อ")
check("ชื่อเป็น None = ไม่มีชื่อ", clip_drive.safe_name(None), "ไม่มีชื่อ")
check("ตัดความยาวตามที่กำหนด", len(clip_drive.safe_name("ก" * 200)), 60)
check("อิโมจิไม่ถูกตัดทิ้ง", clip_drive.safe_name("เสื้อ 🔥 ดี"), "เสื้อ 🔥 ดี")
check("ขึ้นบรรทัดใหม่กลายเป็นช่องว่าง", clip_drive.safe_name("ก\nข"), "ก ข")
check("ชื่อโฟลเดอร์มี item_id ต่อท้าย",
      clip_drive.folder_name({"name": "เสื้อยืด"}, "123"), "เสื้อยืด-123")
check("ไม่มีชื่อสินค้าก็ยังได้โฟลเดอร์",
      clip_drive.folder_name({}, "123"), "ไม่มีชื่อ-123")

# ------------------------------------------------------------- 2 ที่อยู่

print("\n[2] ที่อยู่ปลายทาง")
bench = Bench()
check("โฟลเดอร์ย่อยปริยายคือ pipeline-studio",
      clip_drive.target_root(bench.data).name, "pipeline-studio")
check("ไม่ทับโฟลเดอร์ clips ของอีกแชท",
      "clips" in clip_drive.target_root(bench.data).parts, False)
ready, why = clip_drive.available(bench.data)
truthy(f"ฐานมีอยู่ = พร้อม ({why})", ready)
truthy("เรียก available แล้วสร้างโฟลเดอร์ให้เลย", clip_drive.target_root(bench.data).is_dir())
bench.close()

bench = Bench({"clipdrive_subdir": "ที่เก็บของฉัน"})
check("ตั้งชื่อโฟลเดอร์ย่อยเองได้",
      clip_drive.target_root(bench.data).name, "ที่เก็บของฉัน")
bench.close()

bench = Bench({"clipdrive_folder": r"Z:\ไม่มีไดรฟ์นี้"})
ready, why = clip_drive.available(bench.data)
check("ไดรฟ์หาย = ไม่พร้อม", ready, False)
truthy("บอกด้วยว่าเพราะ Google Drive ไม่ได้เปิด", "Google Drive" in why)
bench.close()

# ------------------------------------------------- 3 โครง 4 หมวด สองมุมมอง

print("\n[3] ยกขึ้นแล้วต้องได้ 4 หมวด ครบทั้งสองมุมมอง")
bench = Bench()
bench.product("111", "เสื้อยืดคอกลม", frames=3, videos=2, images=4)
result = clip_drive.sync_run(bench.data, "111")
truthy("ยกสำเร็จ", result["ok"])
# 5 ไฟล์เดี่ยว (มุมมองเดียว) + 3 สตอรีบอร์ด×2 + 2 คลิป×2 = 15
check("นับไฟล์ที่คัดลอก (ไฟล์ใหญ่ถูกยกสองมุมมอง)", result["copied"], 15)
check("รอบแรกไม่มีอะไรให้ข้าม", result["skipped"], 0)

name = "เสื้อยืดคอกลม-111"
print("  — มุมมอง ก: ตามสินค้า")
truthy("1-prompt มีคำสั่ง Flow อ่านออก", bench.item(name, "1-prompt", "คำสั่ง-flow.md").is_file())
truthy("1-prompt มีบทพูด", bench.item(name, "1-prompt", "บทพูด.md").is_file())
truthy("1-prompt มีของดิบ prompts.json", bench.item(name, "1-prompt", "prompts.json").is_file())
truthy("2-storyboard มีภาพ", bench.item(name, "2-storyboard", "storyboard-01.png").is_file())
truthy("2-storyboard มีคำตอบดิบ", bench.item(name, "2-storyboard", "gpt-storyboard.md").is_file())
truthy("3-clip มีคลิป", bench.item(name, "3-clip", "clip-02.mp4").is_file())
truthy("4-posting มีไฟล์การโพสต์", bench.item(name, "4-posting", "การโพสต์.md").is_file())
truthy("4-posting มีของดิบ publish.json", bench.item(name, "4-posting", "publish.json").is_file())
truthy("มีสรุปหน้าเดียว", bench.item(name, "สรุป.md").is_file())
truthy("run.json อยู่ที่รากของโฟลเดอร์สินค้า", bench.item(name, "run.json").is_file())

print("  — มุมมอง ข: ตามหมวด")
truthy("1-prompt รวมไฟล์เดียวต่อสินค้า", bench.cat("1-prompt", f"{name}.md").is_file())
truthy("2-storyboard แยกโฟลเดอร์ต่อสินค้า", bench.cat("2-storyboard", name, "storyboard-01.png").is_file())
truthy("3-clip เป็นไฟล์เรียบติดชื่อสินค้านำ", bench.cat("3-clip", f"{name}__clip-01.mp4").is_file())
truthy("4-posting รวมไฟล์เดียวต่อสินค้า", bench.cat("4-posting", f"{name}.md").is_file())
check("ของดิบไม่ซ้ำในมุมมองตามหมวด", bench.cat("2-storyboard", name, "run.json").exists(), False)

truthy("มีสารบัญ", bench.out("สารบัญ.md").is_file())
truthy("มีบันทึกการโพสต์", bench.out("บันทึกการโพสต์.md").is_file())
check("รูปสินค้า Shopee ไม่ถูกยก (เป็นของตั้งต้น ไม่ใช่ของที่เจน)",
      bench.item(name, "0-รูปสินค้า", "01.jpg").exists(), False)

print("\n[4] ยกซ้ำต้องไม่ทำงานซ้ำ")
again = clip_drive.sync_run(bench.data, "111")
truthy("ยกรอบสองสำเร็จ", again["ok"])
check("ไม่คัดลอกอะไรใหม่เลย", again["copied"], 0)
check("ข้ามครบทุกไฟล์", again["skipped"], 15)
check("ไม่มีอะไรค้างแล้ว", clip_drive.pending(bench.data), [])

print("\n[5] ไฟล์เปลี่ยน = ยกเฉพาะไฟล์นั้น (ทั้งสองมุมมอง)")
time.sleep(0.01)
(bench.data / "shopee_products" / "111" / "video" / "clip-01.mp4").write_bytes(b"MP4new" + bytes(6000))
check("รู้ว่าค้างอีกแล้ว", clip_drive.pending(bench.data), ["111"])
third = clip_drive.sync_run(bench.data, "111")
check("คัดลอกใหม่ 2 ที่ (สองมุมมองของไฟล์เดียวกัน)", third["copied"], 2)
check("ที่เหลือข้ามหมด", third["skipped"], 13)
source_size = (bench.data / "shopee_products" / "111" / "video" / "clip-01.mp4").stat().st_size
check("มุมมองตามสินค้าได้ของใหม่",
      bench.item(name, "3-clip", "clip-01.mp4").stat().st_size, source_size)
check("มุมมองตามหมวดได้ของใหม่ด้วย",
      bench.cat("3-clip", f"{name}__clip-01.mp4").stat().st_size, source_size)

print("\n[6] เปลี่ยนชื่อสินค้า = ของเก่าต้องหายทั้งสองมุมมอง")
folder = bench.data / "shopee_products" / "111"
run = json.loads((folder / "run.json").read_text(encoding="utf-8"))
run["name"] = "เสื้อยืดคอวี"
(folder / "run.json").write_text(json.dumps(run, ensure_ascii=False, indent=2), encoding="utf-8")
renamed = clip_drive.sync_run(bench.data, "111")
fresh = "เสื้อยืดคอวี-111"
truthy("ยกสำเร็จ", renamed["ok"])
truthy("โฟลเดอร์ใหม่โผล่ (ตามสินค้า)", bench.item(fresh).is_dir())
check("โฟลเดอร์เดิมหายไป (ตามสินค้า)", bench.item(name).exists(), False)
truthy("ของใหม่โผล่ในตามหมวด", bench.cat("3-clip", f"{fresh}__clip-01.mp4").is_file())
check("ของเดิมหายจากตามหมวด — คลิป", bench.cat("3-clip", f"{name}__clip-01.mp4").exists(), False)
check("ของเดิมหายจากตามหมวด — สตอรีบอร์ด", bench.cat("2-storyboard", name).exists(), False)
check("ของเดิมหายจากตามหมวด — prompt", bench.cat("1-prompt", f"{name}.md").exists(), False)
bench.close()

print("\n[7] โครงเปลี่ยนรุ่น = รื้อของเก่าทิ้ง ไม่ปะผสม")
bench = Bench()
bench.product("999", "ของเก่า")
clip_drive.sync_run(bench.data, "999")
old_junk = bench.item("ของเก่า-999", "storyboard", "เศษของรุ่นเก่า.png")
old_junk.parent.mkdir(parents=True, exist_ok=True)
old_junk.write_bytes(b"OLD")
state = clip_drive.load_state(bench.data)
state["items"]["999"]["layout"] = 1              # แกล้งว่าเป็นโครงรุ่นเก่า
clip_drive.save_state(bench.data, state)
check("โครงคนละรุ่น = ถือว่าค้าง", clip_drive.pending(bench.data), ["999"])
clip_drive.sync_run(bench.data, "999")
check("เศษของรุ่นเก่าถูกรื้อทิ้ง", old_junk.exists(), False)
truthy("ของรุ่นใหม่ครบ", bench.item("ของเก่า-999", "3-clip", "clip-01.mp4").is_file())
bench.close()

# ------------------------------------------------------- 8 หมวด 4 การโพสต์

print("\n[8] หมวด 4 — โพสต์ช่องทางไหน เวลาเท่าไร")
bench = Bench()
bench.product("444", "กระเป๋าสะพาย", publish={
    "facebook_reels": {"status": "posted", "posted_at": "2026-08-18T09:30:00",
                       "url": "https://fb.com/reel/1", "error": ""},
    "shopee_video": {"status": "failed", "posted_at": "2026-08-18T10:15:00",
                     "url": "", "error": "เดินผังไม่จบ หยุดที่ขั้น 8/28"},
}, caption="เสื้อสวยมาก\nhttps://s.shopee.co.th/x")
clip_drive.sync_run(bench.data, "444")
posting = bench.item("กระเป๋าสะพาย-444", "4-posting", "การโพสต์.md").read_text(encoding="utf-8")
truthy("มีชื่อช่องทางแบบอ่านออก", "Facebook Reels" in posting)
truthy("แปลงชื่อ shopee_video ด้วย", "Shopee Video" in posting)
truthy("บอกว่าโพสต์แล้ว", "โพสต์แล้ว" in posting)
truthy("บอกเวลาที่โพสต์", "2026-08-18 09:30" in posting)
truthy("มีลิงก์โพสต์", "https://fb.com/reel/1" in posting)
truthy("บอกว่าช่องทางไหนล้ม", "ล้มเหลว" in posting)
truthy("บอกเหตุผลที่ล้ม", "หยุดที่ขั้น 8/28" in posting)
truthy("มีแคปชันที่ใช้โพสต์", "เสื้อสวยมาก" in posting)
check("มุมมองตามหมวดได้ไฟล์เดียวกัน",
      bench.cat("4-posting", "กระเป๋าสะพาย-444.md").read_text(encoding="utf-8"), posting)
raw = json.loads(bench.item("กระเป๋าสะพาย-444", "4-posting", "publish.json").read_text(encoding="utf-8"))
check("ของดิบ publish.json ครบ", sorted(raw), ["facebook_reels", "shopee_video"])

print("\n[9] บันทึกการโพสต์รวมข้ามสินค้า เรียงตามเวลา")
bench.product("555", "หูฟังไร้สาย", publish={
    "facebook_reels": {"status": "posted", "posted_at": "2026-08-18T20:00:00",
                       "url": "https://fb.com/reel/2", "error": ""},
    "shopee_video": {"status": "pending", "posted_at": "", "url": "", "error": ""},
})
clip_drive.sync_run(bench.data, "555")
log = bench.out("บันทึกการโพสต์.md").read_text(encoding="utf-8")
truthy("นับจำนวนครั้งที่โพสต์", "โพสต์ไปแล้ว 3 ครั้ง" in log)
truthy("นับรายการที่ยังรอ", "รออยู่ 1 รายการ" in log)
truthy("มีสินค้าทั้งสองชิ้น", "กระเป๋าสะพาย" in log and "หูฟังไร้สาย" in log)
first = log.index("2026-08-18 20:00")
second = log.index("2026-08-18 10:15")
truthy("เรียงเวลาใหม่สุดขึ้นก่อน", first < second)
truthy("มีหัวข้อยังรอโพสต์", "ยังรอโพสต์" in log)

index = bench.out("สารบัญ.md").read_text(encoding="utf-8")
truthy("สารบัญบอกจำนวนรวม", "ทั้งหมด 2 ชิ้น" in index)
truthy("สารบัญมีคอลัมน์ 4 หมวด", "4·โพสต์แล้ว" in index)
truthy("สารบัญนับช่องทางที่โพสต์แล้ว", "| 1/2 |" in index)
truthy("สารบัญบอกว่าเก็บสองมุมมอง", "ตามสินค้า" in index and "ตามหมวด" in index)
bench.close()

print("\n[10] ยังไม่เคยโพสต์ = ต้องบอกให้รู้ ไม่ใช่ตารางว่างเฉยๆ")
bench = Bench()
bench.product("666", "ที่ชาร์จเร็ว")
clip_drive.sync_run(bench.data, "666")
log = bench.out("บันทึกการโพสต์.md").read_text(encoding="utf-8")
truthy("บอกว่ายังไม่มีการโพสต์", "ยังไม่มีการโพสต์ที่บันทึกไว้" in log)
truthy("ชี้ทางไปหาสาเหตุ (mark_posted ถูกเรียกหรือยัง)", "mark_posted" in log)
posting = bench.item("ที่ชาร์จเร็ว-666", "4-posting", "การโพสต์.md").read_text(encoding="utf-8")
truthy("บอกว่ายังไม่ได้อนุมัติ", "ยังไม่ได้อนุมัติ" in posting)
bench.close()

# ------------------------------------------------------------- 11 ผิดพลาด

print("\n[11] เจอปัญหาแล้วต้องบอก ไม่เงียบ")
bench = Bench()
missing = clip_drive.sync_run(bench.data, "ไม่มีสินค้านี้")
check("ไม่มีสินค้า = ไม่สำเร็จ", missing["ok"], False)
truthy("บอกเหตุผล", "ไม่พบโฟลเดอร์ของสินค้า" in missing["why"])
bench.close()

bench = Bench({"clipdrive_folder": r"Z:\ไม่มีไดรฟ์นี้"})
bench.product("222")
dead = clip_drive.sync_run(bench.data, "222")
check("ไดรฟ์หาย = ไม่สำเร็จ (ไม่ระเบิด)", dead["ok"], False)
truthy("บอกว่าเพราะไดรฟ์", "Google Drive" in dead["why"])
try:
    clip_drive.sync_all(bench.data)
    raised = ""
except clip_drive.DriveUnavailable as error:
    raised = str(error)
truthy("sync_all โยน DriveUnavailable ให้รู้ตัว", "Google Drive" in raised)
bench.close()

bench = Bench()
bench.product("333")
clip_drive.state_path(bench.data).write_text("{พังไม่ใช่ json", encoding="utf-8")
check("ไฟล์สถานะพัง = ถือว่ายังไม่เคยยก (ไม่ระเบิด)",
      clip_drive.load_state(bench.data)["items"], {})
truthy("ยกต่อได้ตามปกติ", clip_drive.sync_run(bench.data, "333")["ok"])
bench.close()

# --------------------------------------------------------------- 12 ตรวจ

print("\n[12] ตรวจของบน Drive")
bench = Bench()
bench.product("444", "กระเป๋าสะพาย")
clip_drive.sync_run(bench.data, "444")
report = clip_drive.verify(bench.data)
check("ตรวจแล้วครบ", (report["missing"], report["wrong_size"]), ([], []))
check("นับไฟล์ที่ตรวจ (5 + 2×2 + 1×2)", report["checked"], 11)

bench.item("กระเป๋าสะพาย-444", "3-clip", "clip-01.mp4").unlink()
report = clip_drive.verify(bench.data)
check("ไฟล์บน Drive หาย = จับได้", len(report["missing"]), 1)
truthy("บอกว่าไฟล์ไหน", "3-clip/clip-01.mp4" in report["missing"][0])

bench.cat("2-storyboard", "กระเป๋าสะพาย-444", "storyboard-01.png").write_bytes(b"short")
report = clip_drive.verify(bench.data)
check("ไฟล์ในมุมมองตามหมวดขนาดไม่ตรง = จับได้", len(report["wrong_size"]), 1)
bench.close()

# ------------------------------------------------------- 13 ไม่ชนอีกแชท

print("\n[13] ต้องไม่ชนกับ drive_store.py ของอีกแชท")
bench = Bench()
folder = bench.product("666", "ที่ชาร์จเร็ว")
before = (folder / "run.json").read_text(encoding="utf-8")
clip_drive.sync_run(bench.data, "666")
after = (folder / "run.json").read_text(encoding="utf-8")
check("ไม่แตะ run.json ต้นทางเลย (อีกแชทเขียนคีย์ drive ตรงนั้น)", after, before)
truthy("จำสถานะไว้ในไฟล์ของตัวเอง", clip_drive.state_path(bench.data).is_file())
check("ชื่อไฟล์สถานะไม่ซ้ำใคร",
      clip_drive.state_path(bench.data).name, "clip_drive_state.json")
check("ไม่ไปสร้างโฟลเดอร์ clips ของอีกแชท", (bench.drive / "clips").exists(), False)
config = json.loads((bench.data / "config.json").read_text(encoding="utf-8"))
check("ไม่ใช้คีย์ config ขึ้นต้นด้วย drive_ (ของอีกแชท)",
      {key for key in config if key.startswith("drive_")}, set())
bench.close()

# ------------------------------------------------------- 14 รูปสินค้าเสริม

print("\n[14] เปิดให้ยกรูปสินค้าด้วยได้")
bench = Bench({"clipdrive_images": True})
bench.product("777", "ขวดน้ำ", frames=1, videos=1, images=3)
result = clip_drive.sync_run(bench.data, "777")
check("นับรวมรูปสินค้าด้วย (5 + 1×2 + 1×2 + 3 รูป)", result["copied"], 12)
truthy("รูปสินค้าอยู่ในหมวด 0", bench.item("ขวดน้ำ-777", "0-รูปสินค้า", "01.jpg").is_file())
check("รูปสินค้าไม่ซ้ำในมุมมองตามหมวด",
      bench.cat("0-รูปสินค้า").exists(), False)
bench.close()

print("\n[15] ปิดสวิตช์ได้")
bench = Bench({"clipdrive_enabled": False})
check("อ่านสวิตช์ปิดได้", clip_drive.enabled(bench.data), False)
bench.close()
bench = Bench()
check("ปริยายคือเปิด", clip_drive.enabled(bench.data), True)
bench.close()

# --------------------------------------------------------------- สรุปผล

print("\n" + "=" * 58)
print(f"ผ่าน {PASS} · ไม่ผ่าน {FAIL}")
if NOTES:
    print("\nรายการที่ไม่ผ่าน:")
    for note in NOTES:
        print(f"  ❌ {note}")
print("=" * 58)
sys.exit(1 if FAIL else 0)
