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
        # **ส่งที่เก็บรูปเข้าไปด้วย เพื่อให้ Chrome โหลดรูปเองตั้งแต่ตอนหน้ายังเปิด**
        # (ผู้ใช้สั่ง 27 ส.ค. 2026 หลังไล่หาสาเหตุที่โดน Shopee บล็อก)
        #
        # ของเดิมโหลดรูปหลังปิดเบราว์เซอร์ จึงต้องใช้ตัวโหลดของ Python ซึ่งจาก
        # ฝั่ง Shopee เห็นเป็นคนละโปรแกรมยิงมาจากที่อยู่เดียวกัน 129 ครั้งใน
        # 10 นาที — ร่องรอยที่หนักที่สุดในบรรดาที่วิเคราะห์เจอ
        image_root = shared.DATA_DIR / "shopee_products"
        data = shopee_scrape.scrape(link, open_browser, log=say,
                                    image_root=image_root, want_all=want_all)
        api_key = load_gemini_api_key()
        candidates = data["images"] if want_all else data["selected"]
        folder = image_root / data["item_id"]
        saved = list(data.get("saved_files") or [])
        if len(saved) != len(candidates):
            # โหลดผ่านหน้าเว็บไม่ครบ (คลังรูปปิด CORS · หน้าโดนเด้งกลางคัน)
            # → ถอยไปใช้ตัวโหลดเดิมให้ครบ ดีกว่าปล่อยให้ได้รูปไม่ครบเงียบๆ
            say(f"Chrome โหลดรูปได้ {len(saved)}/{len(candidates)} ใบ "
                f"— ถอยไปใช้ตัวโหลดสำรองให้ครบ")
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
        # ไล่จุดขายให้ครบก่อน แล้วค่อยเลือก 3 ข้อที่ว้าวสุด (ผู้ใช้สั่ง 22 ส.ค. 2026)
        # เก็บรายการเต็มไว้ด้วย เพื่อให้สลับข้อที่ไม่ถูกใจได้โดยไม่ต้องยิง AI ใหม่
        analysis = shopee_scrape.analyse_features(
            data["name"], data["detail"], api_key, log=say
        )
        data["highlights"] = analysis["highlights"]
        data["features"] = analysis["features"]
        data["highlight_why"] = analysis["why"]
    return data
