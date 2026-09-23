# -*- coding: utf-8 -*-
"""ตัวทำงานสายโปสเตอร์ — กล่อง Poster · Caption · Comment ส่งของเข้า ChatGPT custom

สเปค: SPEC-สายโปสเตอร์.md · custom ที่ใช้อ่านจาก gpt_customs (ตัวที่เลือกไว้ของกล่องนั้น)

    python poster_worker.py <poster_id> poster|caption|comment

## ส่งอะไรเข้าไป

    Poster    ชื่อสินค้า + จุดเด่น + รูปสินค้าทั้งชุด        → รูปโปสเตอร์
    Caption   รูปโปสเตอร์ + ชื่อสินค้า                     → แคปชัน
    Comment   รูปโปสเตอร์ + แคปชัน + ลิงก์ Shopee (+ Lazada) → คอมเมนต์ที่มีลิงก์

## ตัดสินว่าสำเร็จจากของที่มีเฉพาะตอนสำเร็จ (กติกาข้อ 2.3.1)

- Poster  = ดาวน์โหลดรูปจากคำตอบได้จริงอย่างน้อย 1 ใบ (ไม่ใช่แค่ "GPT ตอบแล้ว")
- Caption = มีข้อความตอบกลับที่ไม่ใช่คำปฏิเสธ
- Comment = **ลิงก์ Shopee อยู่ในคำตอบจริง** — คอมเมนต์ที่ไม่มีลิงก์คือของเสีย
  เพราะหน้าที่ทั้งหมดของมันคือพาคนไปซื้อ

## ใช้เบราว์เซอร์ตัวไหน

โปรไฟล์ ChatGPT เดิมที่ล็อกอินไว้แล้ว (ตัวเดียวกับสายคลิปทำสตอรีบอร์ด) และถือล็อก
`browser_lock()` ตัวเดียวกัน — เปิดโปรไฟล์เดียวกันซ้อนกัน ตัวที่เปิดทีหลังจะไล่ตัวแรก
ออกกลางงาน (ข้อ 7.5)
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import gpt_customs
import poster_store as ps
import studio_shared

BOXES = ("poster", "caption", "comment")


class StageError(RuntimeError):
    """ขั้นนี้ไม่สำเร็จ — ข้อความเป็นภาษาคน"""


def _custom(box: str) -> dict:
    row = gpt_customs.selected(box)
    if not row:
        raise StageError(
            f"กล่อง {gpt_customs.BOXES[box]} ยังไม่ได้เลือก ChatGPT custom — "
            "เพิ่ม/เลือกที่หน้าเว็บก่อน")
    return row


def ask_poster(card: dict) -> str:
    lines = [f"สินค้า: {card.get('product_name') or card['name']}"]
    if card.get("highlights"):
        lines += ["", "จุดเด่น:"] + [f"- {text}" for text in card["highlights"]]
    lines += ["", f"แนบรูปสินค้าจริงมาให้ {len(card['images'])} ใบ",
              "ช่วยทำโปสเตอร์โฆษณาสินค้านี้ **ออกมาเป็นรูปภาพ** ให้ด้วย"]
    return "\n".join(lines)


def ask_caption(card: dict) -> str:
    return (f"สินค้า: {card.get('product_name') or card['name']}\n\n"
            "แนบรูปโปสเตอร์มาให้ 1 ใบ ช่วยเขียนแคปชันสำหรับโพสต์รูปนี้ลงเพจ Facebook")


def ask_comment(card: dict) -> str:
    lines = [f"สินค้า: {card.get('product_name') or card['name']}", "",
             "แคปชันของโพสต์:", card["caption"], "",
             f"ลิงก์ Shopee: {card['shopee_url']}"]
    if card.get("lazada_url"):
        lines.append(f"ลิงก์ Lazada: {card['lazada_url']}")
    lines += ["", "แนบรูปโปสเตอร์มาให้ 1 ใบ ช่วยเขียนคอมเมนต์ใต้โพสต์ "
              "โดยใส่ลิงก์ข้างบนไว้ในคอมเมนต์ด้วย"]
    return "\n".join(lines)


def comments_from(reply: str, card: dict) -> list[str]:
    """คอมเมนต์จากคำตอบ — ต้องมีลิงก์ Shopee อยู่ข้างในจริง ไม่งั้นโยน error"""
    text = (reply or "").strip()
    link = card.get("shopee_url") or ""
    if not text:
        raise StageError("ChatGPT ไม่ได้ตอบคอมเมนต์กลับมา")
    if link and link not in text:
        raise StageError(
            "คอมเมนต์ที่ได้ไม่มีลิงก์ Shopee อยู่ข้างใน — ไม่เอาไปใช้ "
            "(คอมเมนต์ต้องพาคนไปซื้อได้) · ดูคำตอบดิบในโฟลเดอร์ raw/")
    lazada = card.get("lazada_url") or ""
    if lazada and lazada not in text:
        raise StageError("คอมเมนต์ที่ได้ไม่มีลิงก์ Lazada อยู่ข้างใน — ไม่เอาไปใช้")
    return [text]


def run(poster_id: str, box: str, log=print, instruction: str = "") -> dict:
    """ทำกล่อง `box` ของใบนี้หนึ่งรอบ — สำเร็จแล้วบันทึกของไว้ **รอคนตรวจ**

    **ไม่ย้ายใบไปกล่องถัดไปเอง** (เจ้าของสั่ง 23 ก.ย. 2569 ให้เหมือนกระดานเดิม)
    ใบรออยู่ในกล่องจนกว่าจะมีคนกด ✅ อนุมัติ หรือเปิด ☐ อัตโนมัติของกล่องนั้น

    `instruction` = ✏️ สั่งแก้ — ส่งคำสั่งแก้เข้า **แชทเดิม** ที่ทำของชิ้นนี้ออกมา
    ไม่ใช่เปิดแชทใหม่ เพราะ GPT ต้องเห็นของเดิมถึงจะแก้ตรงจุดที่บอกได้
    """
    if box not in BOXES:
        raise StageError(f"ไม่รู้จักกล่อง {box}")
    card = ps.load(poster_id)
    if not card:
        raise StageError(f"ไม่พบใบ {poster_id}")
    if card.get("stage") != box:
        raise StageError(
            f"ใบนี้อยู่กล่อง {ps.STAGE_LABEL.get(card.get('stage'), card.get('stage'))} "
            f"ไม่ใช่ {ps.STAGE_LABEL[box]} — ห้ามข้ามขั้น (ข้อ 2.9)")
    custom = _custom(box)
    here = ps.folder(poster_id)
    chat = (card.get(f"{box}_custom") or {}).get("chat", "")
    if instruction and not chat:
        raise StageError("ยังไม่มีแชทเดิมให้สั่งแก้ — กด 🔁 ทำใหม่แทน")
    if box == "poster":
        files = [here / name for name in card["images"]]
        ask = ask_poster(card)
    else:
        files = [here / card["poster_images"][0]] if card.get("poster_images") else []
        if not files or not files[0].is_file():
            raise StageError("ไม่พบไฟล์รูปโปสเตอร์ — ต้องผ่านกล่อง Poster ก่อน")
        if box == "comment" and not card.get("shopee_url"):
            raise StageError("ใบนี้ไม่มีลิงก์ Shopee — คอมเมนต์ไม่มีลิงก์ให้ใส่")
        ask = ask_caption(card) if box == "caption" else ask_comment(card)
    missing = [f.name for f in files if not f.is_file()]
    if missing:
        raise StageError(f"ไฟล์รูปหาย: {', '.join(missing)}")
    if instruction:
        # สั่งแก้ = พิมพ์คำสั่งลงแชทเดิมอย่างเดียว ไม่แนบรูปซ้ำ (GPT เห็นรูปในแชทแล้ว)
        ask, files = instruction.strip(), []

    import chatgpt_driver
    from flow_worker import open_browser, space_out
    from playwright.sync_api import sync_playwright

    what = f"สั่งแก้: {ask[:60]}" if instruction else f"แนบรูป {len(files)} ใบ"
    log(f"[{poster_id}] กล่อง {ps.STAGE_LABEL[box]} · ใช้ “{custom['name']}” · {what}")
    ps.set_status(poster_id, "running")
    space_out("chatgpt", log=log)
    stamp = {"id": custom["id"], "name": custom["name"], "url": custom["url"],
             "at": ps._now()}
    with studio_shared.browser_lock(label=f"สายโปสเตอร์ {ps.STAGE_LABEL[box]} {poster_id}"):
        with sync_playwright() as playwright:
            browser = open_browser(playwright, hidden=True)
            page = browser.pages[0] if browser.pages else browser.new_page()
            try:
                session = chatgpt_driver.ChatGPTSession(page, log=log)
                session.open(chat if instruction else custom["url"])
                reply = session.ask(ask, files)
                ps.save_raw(poster_id, box, f"ถาม:\n{ask}\n\n---- ตอบ:\n{reply}\n\n"
                                            f"แชท: {page.url}")
                if box == "poster":
                    log("รอ ChatGPT วาดโปสเตอร์…")
                    urls = session.wait_reply_images(minimum=1)
                    if not urls:
                        last = session.state().get("lastReply", "")
                        if chatgpt_driver.image_quota_out(last):
                            raise StageError("โควตารูปของบัญชี ChatGPT หมด — รอคืนสิทธิ์ก่อน")
                        raise StageError("ChatGPT ไม่ได้วาดรูปโปสเตอร์ออกมา")
                    # ตั้งชื่อตามเวลา — ของรอบก่อนไม่ถูกทับ ย้อนกลับไปใช้ได้
                    saved = session.download_reply_images(
                        here / "poster", prefix=f"poster-{time.strftime('%m%d-%H%M%S')}")
                    if not saved:
                        raise StageError("เห็นรูปในคำตอบแต่โหลดมาเก็บไม่ได้สักใบ")
                    ps.set_result(poster_id, "poster",
                                  poster_images=[p.relative_to(here).as_posix() for p in saved],
                                  poster_custom={**stamp, "chat": page.url})
                elif box == "caption":
                    text = (reply or "").strip()
                    if not text:
                        raise StageError("ChatGPT ไม่ได้ตอบแคปชันกลับมา")
                    ps.set_result(poster_id, "caption", caption=text,
                                  caption_custom={**stamp, "chat": page.url})
                else:
                    ps.set_result(poster_id, "comment", comments=comments_from(reply, card),
                                  comment_custom={**stamp, "chat": page.url})
            finally:
                browser.close()
    log(f"[{poster_id}] ✅ กล่อง {ps.STAGE_LABEL[box]} ได้ของแล้ว — รอตรวจ")
    return ps.load(poster_id)


def run_safe(poster_id: str, box: str, log=print, instruction: str = "") -> bool:
    """เหมือน `run` แต่จดความล้มเหลวลงใบ (ป้ายแดงบนการ์ด) ไม่โยนต่อ"""
    try:
        run(poster_id, box, log=log, instruction=instruction)
        return True
    except Exception as error:                                   # noqa: BLE001
        why = str(error) or error.__class__.__name__
        log(f"[{poster_id}] ✕ กล่อง {ps.STAGE_LABEL.get(box, box)} ไม่สำเร็จ: {why}")
        try:
            ps.fail(poster_id, f"{ps.STAGE_LABEL.get(box, box)}: {why}")
        except ps.PosterError:
            pass
        return False


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(2)
    sys.exit(0 if run_safe(sys.argv[1], sys.argv[2]) else 1)
