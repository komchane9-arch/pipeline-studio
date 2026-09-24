"""ดึงข้อมูลสินค้า Shopee — ใช้ร่วมกันทั้งเซิร์ฟเวอร์หลักและเซิร์ฟเวอร์สายคลิป

ย้ายออกมาจาก app.py ตอนแยกสายคลิปเป็นคนละโปรเซส เพราะทั้งสองฝั่งต้องเรียกงานนี้
และทั้งคู่ต้องแย่งเบราว์เซอร์ตัวเดียวกัน — จึงต้องคุมด้วยล็อก **ข้ามโปรเซส**
ไม่ใช่ threading.Lock แบบเดิมที่กันได้แค่ในโปรเซสตัวเอง
"""

from __future__ import annotations

from pathlib import Path

import studio_shared as shared


def shopee_collect(link: str, want_all: bool = False, log=None,
                   profile: str = "") -> dict:
    """เปิดลิงก์ → ได้ชื่อสินค้า · รูปที่คัดแล้ว · จุดเด่น 3 ข้อ

    รูปที่คัด = สีละ 1 ใบ + ภาพรวมมีพื้นหลัง 1 ใบ (ให้ Gemini ดูรูปจริงแล้วเลือก
    เพราะดูจากชื่อไฟล์ไม่รู้ว่าใบไหนหน้าตาซ้ำกัน)
    """
    import shopee_scrape
    from flow_worker import (load_gemini_api_key, open_browser,
                             profile_named as flow_worker_profile)

    def say(message: str) -> None:
        if log:
            log(message)
        else:
            shared.append_log("input", message)

    # ---- แยกโปรไฟล์ได้ (สายคลิปขอเพิ่ม 30 ส.ค. 2569) ----------------------
    #
    # *"storyboard กับ ดึงลิ้ง แยกคนทำกันไม่ได้หรอ"* — แยกได้ **แต่ต้องคนละ
    # โปรไฟล์ Chrome** เพราะ Chrome เปิดโปรไฟล์เดียวกันซ้อนไม่ได้ ของเดิมทั้ง
    # สองงานใช้โปรไฟล์เดียวกันจึงต้องผลัดกันตลอด
    #
    # **ค่าปริยายว่าง = โปรไฟล์เดิมทุกอย่าง สายโพสต์จึงไม่กระทบเลย**
    # ผู้เรียกที่อยากแยกต้องส่งชื่อโปรไฟล์เข้ามาเอง และโปรไฟล์นั้น
    # **ต้องล็อกอิน Shopee ไว้แล้ว** ไม่งั้นหน้าสินค้าเปิดไม่ได้
    if profile:
        _here = flow_worker_profile(profile)
        _open = lambda pw, hidden=False, _d=_here: open_browser(pw, hidden, _d)   # noqa: E731
    else:
        _open = open_browser
    with shared.browser_lock(label="ดึงข้อมูล Shopee", profile=profile):
        # **ส่งที่เก็บรูปเข้าไปด้วย เพื่อให้ Chrome โหลดรูปเองตั้งแต่ตอนหน้ายังเปิด**
        # (ผู้ใช้สั่ง 27 ส.ค. 2026 หลังไล่หาสาเหตุที่โดน Shopee บล็อก)
        #
        # ของเดิมโหลดรูปหลังปิดเบราว์เซอร์ จึงต้องใช้ตัวโหลดของ Python ซึ่งจาก
        # ฝั่ง Shopee เห็นเป็นคนละโปรแกรมยิงมาจากที่อยู่เดียวกัน 129 ครั้งใน
        # 10 นาที — ร่องรอยที่หนักที่สุดในบรรดาที่วิเคราะห์เจอ
        # ---- หาที่เก็บของสินค้าชิ้นนี้ **ก่อน** เริ่มดึง ------------------
        #
        # **ห้ามต่อพาธ `shopee_products` ตรงๆ** (แก้ 27 ส.ค. 2569)
        #
        # ของเดิมสร้างโฟลเดอร์ที่ `shopee_products/` เสมอ ไม่ถามว่าสินค้าชิ้นนี้
        # มีของเก่าอยู่ไหน พอส่งลิงก์เดิมเข้ามาซ้ำหลังทำคลิปเสร็จแล้ว
        # จะได้ **สองชุดต่อสินค้าหนึ่งชิ้น** — ชุดใหม่มีแต่รูป ส่วนชุดเก่าที่มี
        # คลิป (จ่ายเครดิต Veo ไปแล้ว) หายจากทุกรายการเงียบๆ เพราะตัวค้นเจอ
        # ชุดใหม่ที่ว่างกว่าก่อน — เจอของจริง 4 คู่ ตอนย้ายที่เก็บ
        #
        # `clip_store.target_dir()` รู้จักโฟลเดอร์ทั้ง 9 อัน (clips/ · clipsfb/
        # · waitclips/ …) เจอของเก่าที่ไหนก็เขียนทับที่นั่น ไม่เจอค่อยสร้างใหม่
        #
        # คลี่ลิงก์เองตรงนี้แล้วส่ง **ลิงก์เต็ม** ให้ `scrape` ไปเลย
        # `resolve_link` ไม่ยิงซ้ำถ้าอ่านรหัสจากลิงก์ได้อยู่แล้ว = ไม่เสียคำขอเพิ่ม
        import clip_store                                       # noqa: PLC0415
        full_url = shopee_scrape.resolve_link(link)
        _shop_id, item_id = shopee_scrape.parse_ids(full_url)
        image_root = clip_store.target_dir(shared.DATA_DIR, item_id).parent
        if image_root.name != "shopee_products":
            say(f"สินค้านี้มีของเก่าอยู่แล้วที่ {image_root.name}/ — เขียนต่อที่เดิม")
        data = shopee_scrape.scrape(full_url, _open, log=say,
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
        curate_into(data, paired, api_key, say)
        data["saved_images"] = [item["file"] for item in data["picked"]]
    return data


def curate_into(data: dict, paired: list[dict], api_key, say=print) -> None:
    """คัดรูป + เขียนจุดเด่นให้ตรงกัน แล้วเขียนผลลงใน `data`

    **แยกออกมาเป็นฟังก์ชันเมื่อ 28 ส.ค. 2569** เพื่อให้ **งานป้อนเอง** (ที่ไม่มี
    ลิงก์ Shopee) ใช้ขั้นตอนเดียวกันเป๊ะ ไม่ใช่เขียนสายพานเส้นที่สอง

    เหตุผล: โปรเจกต์นี้เจอปัญหา "สองทางที่ทำเรื่องเดียวกันแล้ววันหลังเพี้ยนคนละทาง"
    มาหลายรอบ (คัดรูปสองรอบทับกัน · กติกาสินค้าปรับท่าเขียนไว้สองที่) การก๊อป
    ตรรกะนี้ไปไว้อีกไฟล์จะได้บั๊กแบบเดียวกันอีกแน่นอน
    """
    import shopee_scrape                                        # noqa: PLC0415

    say(f"ส่งรูป {len(paired)} ใบ + รายละเอียด ให้ Gemini กรองให้ก่อน…")
    try:
        # สินค้าปรับท่าได้ ต้องบอกตั้งแต่รอบนี้ ไม่ใช่ปล่อยให้ขั้นถัดไปคัดใหม่
        rule = shopee_scrape.transform_rule(data["name"], data["detail"])
        if rule:
            say("สินค้านี้ปรับเปลี่ยนรูปทรงได้ — สั่งให้คัดรูปครบทุกท่า")
        curated = shopee_scrape.curate_for_ad(
            data["name"], data["detail"],
            [item["file"] for item in paired], api_key, log=say,
            extra_rule=rule,
        )
        data["picked"] = [paired[i] for i in curated["indexes"]]
        data["highlights"] = curated["highlights"]
        data["highlight_why"] = curated["why"]
        # เก็บจุดขายที่ไล่ได้ทั้งหมดไว้เป็นคลังสำรอง ให้สลับข้อที่ไม่ถูกใจได้
        # โดยไม่ต้องยิง AI ใหม่ (ผู้ใช้สั่ง 22 ส.ค. 2026)
        data["features"] = curated["features"]
        # ความเดือดร้อนของคนซื้อ + คะแนน 1-10 ที่ AI ไล่มาก่อนเลือกรูป
        # (เจ้าของสั่งเพิ่มขั้นนี้ 28 ส.ค. 2569) เก็บไว้กับใบงานเพื่อให้ย้อนดูได้ว่า
        # จุดเด่นที่เลือกมา **มาจากความเดือดร้อนข้อไหน** ไม่ใช่เลือกมาลอยๆ
        data["pains"] = curated.get("pains") or []
        # ⭐ ธงบอกขั้นถัดไปว่า **จุดเด่นข้อที่ i เขียนจากรูปใบที่ i จริง**
        #
        # ต้องเป็นธงชัดๆ ห้ามให้ขั้นถัดไปเดาจากจำนวน เพราะทางถอยข้างล่างก็คืน
        # จุดเด่น 3 ข้อกับรูป 3 ใบเท่ากันเป๊ะ (HIGHLIGHT_COUNT = IMAGE_PICK_COUNT = 3)
        # นับเท่ากันแล้วสรุปว่าตรงกัน = หลอกตัวเอง
        data["highlights_match_images"] = True
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
        # ทางถอยนี้เลือกรูปกับเขียนจุดเด่น **คนละคำขอ คนละสายตา** ตัวเลือกรูป
        # ไม่เห็นคำบรรยาย ตัวเขียนจุดเด่นไม่เห็นรูป จึงไม่มีทางตรงกันโดยตั้งใจ
        data["highlights_match_images"] = False
