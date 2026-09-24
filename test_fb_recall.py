"""ทดสอบคลังโพสต์ /recall โดยไม่แตะข้อมูลจริงหรือมือถือ"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


TEST_ROOT = Path(tempfile.mkdtemp(prefix="pipeline-fb-recall-"))
os.environ["STUDIO_DATA_DIR"] = str(TEST_ROOT / "data")

import app  # noqa: E402
import fb_auto_post  # noqa: E402


def check(ok: bool, message: str) -> None:
    if not ok:
        raise AssertionError(message)
    print("✅ " + message)


app.FB_POST_DIR = TEST_ROOT / "images"
app.FB_POST_DIR.mkdir(parents=True, exist_ok=True)
app.fb_jobs = fb_auto_post.JobStore(TEST_ROOT / "fb_jobs.json")
app.fb_groups = fb_auto_post.GroupStore(TEST_ROOT / "fb_groups.json")
group = app.fb_groups.add("123", "กลุ่มทดสอบ")


saved = app.fb_jobs.add(
    id="saved-text", caption="โพสต์ที่เก็บไว้", comments=["คอมเมนต์หนึ่ง"],
    saved=True, saved_at="2026-09-03T15:00:00",
)
check(app.fb_jobs.saved_listing()[0]["id"] == saved["id"],
      "saved_listing คืนเฉพาะโพสต์ที่เก็บไว้")

draft = app.fb_jobs.add(id="draft", caption="ร่างสำหรับกดเก็บ")
card_text, card_keyboard = app._fb_card(draft)
buttons = [button for row in card_keyboard["inline_keyboard"] for button in row]
check(any(button.get("callback_data") == "fb:sv:draft" for button in buttons),
      "การ์ดงานมีปุ่มเก็บโพสต์")
note = app._telegram_callback("chat-test", "sv:draft", {})
check("เก็บโพสต์แล้ว" in note and app.fb_jobs.get("draft")["saved"],
      "กดปุ่มแล้วบันทึกโพสต์ไว้จริง")
recall_text, recall_keyboard = app._fb_recall_card()
recall_buttons = [button for row in recall_keyboard["inline_keyboard"] for button in row]
check("โพสต์ที่เก็บไว้" in recall_text and any(
    button.get("callback_data", "").startswith("fb:rc:") for button in recall_buttons
), "/recall แสดงรายการพร้อมปุ่มเรียกกลับ")
sent = []
old_say = app._fb_say
try:
    app._fb_say = lambda chat_id, text, keyboard=None: sent.append((text, keyboard)) or 1
    check(app._telegram_command("chat-test", "/recall"), "ตัวรับคำสั่งรู้จัก /recall")
    check(bool(sent and sent[-1][1]), "/recall ส่งการ์ดรายการกลับ Telegram")
finally:
    app._fb_say = old_say

recalled, problem = app._fb_recall_job(saved["id"], "chat-test")
check(not problem and recalled is not None, "เรียกโพสต์ข้อความกลับมาเป็นงานใหม่ได้")
check(recalled["status"] == fb_auto_post.STATUS_WAIT_IMAGE,
      "โพสต์ที่ยังไม่มีรูปรอรับรูปต่อ ไม่ถูกปฏิเสธ")
check(recalled["comments"] == ["คอมเมนต์หนึ่ง"], "คอมเมนต์ติดมากับงานที่เรียกกลับ")
check(recalled["saved"] is False, "งานใหม่ไม่ถูกเก็บซ้ำอัตโนมัติ")

source_image = app.FB_POST_DIR / "source.jpg"
source_image.write_bytes(b"test-image")
saved_image = app.fb_jobs.add(
    id="saved-image", caption="โพสต์มีรูป", image=str(source_image),
    images=[str(source_image)], groups=[group["group_id"]], set=group["set"],
    saved=True, saved_at="2026-09-03T15:01:00",
)
recalled_image, problem = app._fb_recall_job(saved_image["id"], "chat-test")
check(not problem and recalled_image is not None, "เรียกโพสต์พร้อมรูปกลับมาได้")
check(recalled_image["status"] == fb_auto_post.STATUS_READY, "โพสต์พร้อมรูปกลับมาพร้อมส่ง")
check(Path(recalled_image["image"]).is_file(), "คัดลอกรูปเป็นไฟล์ของงานใหม่")
check(Path(recalled_image["image"]) != source_image, "งานใหม่ไม่ใช้ไฟล์รูปร่วมกับต้นฉบับ")
check(recalled_image["groups"] == [group["group_id"]], "ชุดกลุ่มเดิมติดมากับงานใหม่")
check(
    recalled_image["source"] == "telegram" and recalled_image["run_at"] == ""
    and recalled_image["results"] == [] and recalled_image["started_at"] is None
    and recalled_image["finished_at"] is None,
    "งานที่เรียกกลับเริ่มสถานะใหม่เหมือนงานที่เพิ่งส่งเข้า Telegram",
)

shown, auto_started = [], []
old_show, old_auto = app._fb_show_card, app._fb_maybe_auto_start
try:
    app._fb_show_card = lambda job: shown.append(job["id"]) or job
    app._fb_maybe_auto_start = lambda job: auto_started.append(job["id"])
    note = app._telegram_callback("chat-test", f"rc:{saved_image['id']}", {})
    recalled_id = note.split()[1]
    check(shown == [recalled_id] and auto_started == [recalled_id],
          "เรียกจากปุ่ม /recall เข้าทางการ์ดและ auto-start เดียวกับงานใหม่")
finally:
    app._fb_show_card, app._fb_maybe_auto_start = old_show, old_auto

plain = app.fb_jobs.add(id="not-saved", caption="ไม่ได้เก็บ")
missing, problem = app._fb_recall_job(plain["id"], "chat-test")
check(missing is None and "ไม่พบโพสต์ที่เก็บไว้" in problem,
      "ห้าม /recall งานที่ไม่ได้กดเก็บ")

items = [
    {"id": f"old-{index}", "saved": index == 0, "pinned": False}
    for index in range(fb_auto_post.JOB_LIMIT + 3)
]
trimmed = fb_auto_post._trim_jobs(items)
check(any(job["id"] == "old-0" for job in trimmed), "โพสต์ที่เก็บไว้ไม่หลุดเมื่อประวัติเต็ม")

# 1. ยกเลิกงานที่ saved ไว้โดยตรง -> หลุดจาก /recall
to_cancel = app.fb_jobs.add(id="save-then-cancel", caption="โพสต์ขอยกเลิก", saved=True)
check(any(j["id"] == "save-then-cancel" for j in app.fb_jobs.saved_listing()), "มีใน saved_listing ก่อนยกเลิก")
app._fb_cancel_job("save-then-cancel")
check(not any(j["id"] == "save-then-cancel" for j in app.fb_jobs.saved_listing()), "ยกเลิกแล้วหลุดจาก saved_listing ทันที")
check(app.fb_jobs.get("save-then-cancel")["saved"] is False, "saved ถูกปลดเป็น False")

# 2. recall งานมาเปิด แล้วกดยกเลิกงานใหม่ -> งานต้นฉบับต้องหลุดจาก /recall ด้วย
parent_job = app.fb_jobs.add(id="parent-saved", caption="ต้นทางในคลัง", saved=True)
recalled_child, _ = app._fb_recall_job("parent-saved", "chat-test")
check(recalled_child["recalled_from"] == "parent-saved", "งานลูกผูกกับงานต้นทาง")
check(any(j["id"] == "parent-saved" for j in app.fb_jobs.saved_listing()), "ต้นทางยังอยู่ในคลังตอนเปิดเสร็จ")
app._fb_cancel_job(recalled_child["id"])
check(not any(j["id"] == "parent-saved" for j in app.fb_jobs.saved_listing()), "กดยกเลิกงานใหม่แล้ว งานต้นทางหลุดจาก /recall ทันที")
check(app.fb_jobs.get("parent-saved")["saved"] is False, "saved ของต้นทางถูกปลดเป็น False")

# 3. ทดสอบปุ่ม 🗑 ใน /recall (callback rx)
rx_job = app.fb_jobs.add(id="test-rx-delete", caption="ทดสอบปุ่มถังขยะ", saved=True)
check(any(j["id"] == "test-rx-delete" for j in app.fb_jobs.saved_listing()), "มีในรายการก่อนกดลบ")
rx_note = app._telegram_callback("chat-test", "rx:test-rx-delete", {})
check("ลบออกจาก /recall แล้ว" in rx_note, "ตอบกลับว่าลบแล้ว")
check(not any(j["id"] == "test-rx-delete" for j in app.fb_jobs.saved_listing()), "หลุดจากรายการหลังกดลบ")

print("\nทดสอบ /recall ผ่านทั้งหมด")

