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
        data["candidates"] = paired
        data["folder"] = str(folder)

        # ---- ให้ Gemini กรองให้ก่อนถึงมือคน (ผู้ใช้สั่ง 27 ส.ค. 2026) ----------
        #
        # *"ส่งไปให้ Gemini ทั้งหมด ทั้งรูปและรายละเอียด … เพื่อให้ gemini ช่วย
        #   กรองก่อน และผมจะเข้าไป approve อีกที ขั้นตอน gemini นี้ให้ทำต่อเลย
        #   หลังจากได้รูปและรายละเอียด"*
        #
        # ทำตรงนี้เพราะเป็นจุดแรกที่ **มีครบทั้งสองอย่าง** — รูปโหลดเสร็จแล้ว
        # และรายละเอียดอ่านมาแล้ว ทำที่อื่นต้องไปเปิดไฟล์อ่านใหม่โดยไม่จำเป็น
        #
        # เดิมเป็นสองงานแยกกันที่ไม่รู้จักกัน (เลือกรูปจากรูปล้วน · เขียนจุดเด่น
        # จากข้อความล้วน) ผลคือรูปที่เลือกกับจุดเด่นที่เขียนไม่เกี่ยวกันเลย
        #
        # ⚠️ **ต้องทำทั้งกรณี `want_all` และไม่ `want_all`** — สายคลิปเรียกด้วย
        # `want_all=True` เสมอ (clip_app.py) เพราะอยากได้คลังรูปทั้งชุดไว้ให้
        # ผู้ใช้สลับเอง ถ้าวางขั้นตอนนี้ไว้ในสาขา `else` มันจะไม่เคยทำงานเลย
        # (ผมพลาดแบบนี้จริงตอน 12:27 — ล้มเงียบโดยไม่มี log สักบรรทัด)
        #
        # `want_all` คุมแค่ว่า **คลังรูปมีกี่ใบ** ไม่ได้คุมว่าจะให้ Gemini กรองไหม
        say(f"ส่งรูป {len(paired)} ใบ + รายละเอียด ให้ Gemini กรองให้ก่อน…")
        try:
            curated = shopee_scrape.curate_for_ad(
                data["name"], data["detail"],
                [item["file"] for item in paired], api_key, log=say,
            )
            data["picked"] = [paired[i] for i in curated["indexes"]]
            data["highlights"] = curated["highlights"]
            data["highlight_why"] = curated["why"]
            # เก็บจุดขายที่ไล่ได้ทั้งหมดไว้เป็นคลังสำรอง ให้สลับข้อที่ไม่ถูกใจได้
            # โดยไม่ต้องยิง AI ใหม่ (ผู้ใช้สั่ง 22 ส.ค. 2026)
            data["features"] = curated["features"]
            say(f"Gemini คัดเหลือ {len(data['picked'])} ใบจาก {len(paired)} ใบ "
                f"พร้อมคำโฆษณาครบทุกใบ — รอคุณกดอนุมัติ")
        except Exception as error:                           # noqa: BLE001
            # **ล้มแล้วต้องดัง ไม่ใช่เงียบ** ขั้นตอนนี้ผู้ใช้สั่งให้เพิ่มเอง
            # ถ้าถอยเงียบๆ จะไม่มีใครรู้เลยว่ามันไม่เคยทำงาน
            say(f"⚠️ Gemini กรองชุดรูปไม่สำเร็จ ({error}) — ถอยไปใช้วิธีเดิม "
                f"(เลือกรูปกับเขียนจุดเด่นแยกกัน ซึ่งอาจไม่ตรงกัน)")
            indexes = shopee_scrape.judge_images(
                [item["file"] for item in paired], api_key, log=say
            )
            data["picked"] = (
                [paired[i] for i in indexes] if indexes
                else shopee_scrape.spread_pick(paired)
            )
            say(f"คัดรูปเหลือ {len(data['picked'])} ใบจาก {len(paired)} ใบ")
            analysis = shopee_scrape.analyse_features(
                data["name"], data["detail"], api_key, log=say
            )
            data["highlights"] = analysis["highlights"]
            data["features"] = analysis["features"]
            data["highlight_why"] = analysis["why"]
        data["saved_images"] = [item["file"] for item in data["picked"]]
    return data
