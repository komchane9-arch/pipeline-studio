"""ดึงข้อมูลสินค้า Shopee — ใช้ร่วมกันทั้งเซิร์ฟเวอร์หลักและเซิร์ฟเวอร์สายคลิป

ย้ายออกมาจาก app.py ตอนแยกสายคลิปเป็นคนละโปรเซส เพราะทั้งสองฝั่งต้องเรียกงานนี้
และทั้งคู่ต้องแย่งเบราว์เซอร์ตัวเดียวกัน — จึงต้องคุมด้วยล็อก **ข้ามโปรเซส**
ไม่ใช่ threading.Lock แบบเดิมที่กันได้แค่ในโปรเซสตัวเอง
"""

from __future__ import annotations

from pathlib import Path

import studio_shared as shared


def shopee_collect(link: str, want_all: bool = False, log=None) -> dict:
    """เปิดลิงก์ → ได้ชื่อสินค้า · รูปที่คัดแล้ว · จุดเด่น 3 ข้อ

    รูปที่คัด = สีละ 1 ใบ + ภาพรวมมีพื้นหลัง 1 ใบ (ให้ Gemini ดูรูปจริงแล้วเลือก
    เพราะดูจากชื่อไฟล์ไม่รู้ว่าใบไหนหน้าตาซ้ำกัน)
    """
    import shopee_scrape
    from flow_worker import load_gemini_api_key, open_browser

    def say(message: str) -> None:
        if log:
            log(message)
        else:
            shared.append_log("input", message)

    with shared.browser_lock(label="ดึงข้อมูล Shopee"):
        data = shopee_scrape.scrape(link, open_browser, log=say)
        api_key = load_gemini_api_key()
        candidates = data["images"] if want_all else data["selected"]
        folder = shared.DATA_DIR / "shopee_products" / data["item_id"]
        saved = shopee_scrape.download_images(
            [image["url"] for image in candidates], folder, log=say
        )
        paired = [{**image, "file": path} for image, path in zip(candidates, saved)]
        if want_all:
            picked = paired
        else:
            indexes = shopee_scrape.judge_images(
                [item["file"] for item in paired], api_key, log=say
            )
            picked = (
                [paired[i] for i in indexes] if indexes
                else shopee_scrape.spread_pick(paired)
            )
            say(f"คัดรูปเหลือ {len(picked)} ใบจาก {len(paired)} ใบ")
        data["picked"] = picked
        data["candidates"] = paired
        data["saved_images"] = [item["file"] for item in picked]
        data["folder"] = str(folder)
        data["highlights"] = shopee_scrape.extract_highlights(
            data["name"], data["detail"], api_key, log=say
        )
    return data
