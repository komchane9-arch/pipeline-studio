"""คุยกับ Gemini Gem ผ่านเบราว์เซอร์ — ส่งชื่อ/รายละเอียด/รูปสินค้า แล้วรับ prompt กลับ

ผู้ใช้ยืนยันว่า GEMS ในผัง = Gemini Gem (gemini.google.com/gem/...) ขับผ่าน
เบราว์เซอร์แบบเดียวกับที่ทำกับ Google Flow — ใช้โปรไฟล์เบราว์เซอร์ของโปรเจกต์นี้
(สร้างแยก ไม่ยุ่งกับ Chrome หลักของผู้ใช้) ล็อกอิน Google ครั้งเดียวด้วย
`python flow_worker.py login`

หมายเหตุความจริงของ selector:
  selector ในไฟล์นี้อิงโครงหน้า gemini.google.com (ช่องพิมพ์เป็น rich-textarea
  + ปุ่มส่ง aria-label) แต่ **ยังไม่ได้ยืนยันกับหน้าจริงในเครื่องนี้** — การรันจริง
  ครั้งแรกให้เปิดด้วย `python flow_worker.py inspect` ตรวจก่อนตามกติกาโปรเจกต์เดิม
  (ห้ามเดา selector แล้วปล่อยผ่าน)
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

RESPONSE_TIMEOUT = 120        # Gem ตอบช้าได้ โดยเฉพาะตอนแนบรูป
PROBE_MESSAGE = (
    "ทดสอบระบบ 1 รอบ: สินค้า 'กระดาษทิชชู่ตัวอย่าง' รายละเอียด 'หนา 3 ชั้น ยกลัง' "
    "ช่วยสร้างโครงคลิปตามรูปแบบของ Gem นี้ แล้วบอกด้วยว่าได้ทั้งหมดกี่ฉาก "
    "ความยาวรวมกี่วินาที ตอบท้ายสุดเป็น JSON: {\"scenes\": N, \"seconds\": N}"
)


def _find_input(page):
    """ช่องพิมพ์ของ Gemini — ลองตามลำดับจากเจาะจงสุดไปกว้างสุด"""
    for selector in (
        "rich-textarea .ql-editor",
        '[contenteditable="true"][role="textbox"]',
        '[contenteditable="true"]',
    ):
        box = page.locator(selector).first
        if box.count():
            return box
    return None


def ask_gem(page, link: str, message: str, image_path: str | Path | None = None,
            log=print) -> str:
    """เปิด Gem ตามลิงก์ พิมพ์ข้อความ (แนบรูปถ้ามี) แล้วคืนคำตอบล่าสุดเป็นข้อความ"""
    page.goto(link, wait_until="domcontentloaded", timeout=90_000)
    time.sleep(4)
    if "accounts.google.com" in page.url:
        raise RuntimeError("ยังไม่ได้ล็อกอิน Google — รัน `python flow_worker.py login` ก่อน")

    box = _find_input(page)
    if box is None:
        raise RuntimeError("หาช่องพิมพ์ของ Gem ไม่เจอ — โครงหน้าอาจเปลี่ยน ให้ inspect ก่อน")

    if image_path:
        attach = page.locator('input[type="file"]').first
        if attach.count():
            attach.set_input_files(str(image_path))
            time.sleep(3)
            log("แนบรูปแล้ว")
        else:
            log("ไม่พบช่องแนบรูป — ส่งเฉพาะข้อความ")

    box.click()
    page.keyboard.type(message, delay=10)
    time.sleep(0.5)

    # นับจำนวนคำตอบก่อนส่ง เพื่อรอจน "มีคำตอบใหม่" ไม่ใช่แค่รอเวลา
    answers_before = page.locator("model-response, [data-test-id='model-response']").count()
    page.keyboard.press("Enter")
    log("ส่งข้อความเข้า Gem แล้ว — รอคำตอบ")

    deadline = time.time() + RESPONSE_TIMEOUT
    while time.time() < deadline:
        answers = page.locator("model-response, [data-test-id='model-response']")
        if answers.count() > answers_before:
            last = answers.last
            # รอจนข้อความหยุดยาวขึ้น = ตอบจบแล้ว
            length = -1
            for _ in range(60):
                text = last.inner_text()
                if len(text) == length and length > 0:
                    return text
                length = len(text)
                time.sleep(2)
            return last.inner_text()
        time.sleep(2)
    raise RuntimeError(f"Gem ไม่ตอบภายใน {RESPONSE_TIMEOUT} วินาที")


def parse_probe(text: str) -> dict:
    """อ่านจำนวนฉาก/วินาทีจากคำตอบ — เอา JSON ท้ายข้อความก่อน ไม่มีค่อยไล่จากคำ"""
    for match in reversed(list(re.finditer(r"\{[^{}]*\}", text))):
        try:
            data = json.loads(match.group(0))
            if "scenes" in data and "seconds" in data:
                return {"scenes": int(data["scenes"]), "seconds": int(data["seconds"])}
        except (ValueError, TypeError):
            continue
    scenes = re.search(r"(\d+)\s*ฉาก", text)
    seconds = re.search(r"(\d+)\s*วินาที", text)
    if scenes and seconds:
        return {"scenes": int(scenes.group(1)), "seconds": int(seconds.group(1))}
    raise RuntimeError("อ่านจำนวนฉาก/วินาทีจากคำตอบของ Gem ไม่ได้")


def probe_gem(link: str, log=print) -> dict:
    """test 1 รอบ: เปิดเบราว์เซอร์ → ถาม Gem → คืน {seconds, scenes}"""
    from playwright.sync_api import sync_playwright

    import flow_worker

    with sync_playwright() as playwright:
        browser = flow_worker.open_browser(playwright, hidden=False)
        page = browser.pages[0] if browser.pages else browser.new_page()
        try:
            answer = ask_gem(page, link, PROBE_MESSAGE, log=log)
            log(f"ได้คำตอบ {len(answer)} ตัวอักษร")
            return parse_probe(answer)
        finally:
            browser.close()
