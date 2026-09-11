"""คำสั่งจริงที่ส่งเข้า AI แต่ละเจ้า — สำหรับให้หน้าเว็บโชว์

**เจ้าของสั่ง 31 ส.ค. 2569** — *"ตรงหน้า storyboard เวลากดมาให้มีโชว์ ตรงนี้
เป็นปุ่มตั้งค่า ถ้ากดไปให้ลิ้งไปอีกหน้านึง โชว์ 1.prompt ที่ส่งเข้า gemini
เพื่อเลือกรูป 2.prompt ที่ส่งเข้า chatgpt เพื่อ gen story board"*

**ทำไมต้องโชว์ของจริง ไม่ใช่คำอธิบาย** — เคยเจอว่าพร้อมหลักที่ฝังใน custom GPT
ขัดกับกติกาที่เราส่งไปทับถึง 3 จุด (จำนวนจุดเด่น 3 vs 4 · "no text" vs ตัวหนังสือ
ไทย · ชั้นวางของที่ค้างมาจากสินค้าเก่า) กว่าจะเจอต้องให้เจ้าของเอาพร้อมมาวางเทียบเอง
ถ้าเห็นของจริงทั้งชุดในหน้าเดียว จะจับขัดกันได้ตั้งแต่แรก

---

**แยกออกมาจาก `clip_app.py` เมื่อ 11 ก.ย. 2569** ตามที่เจ้าของสั่งให้ผ่าไฟล์ใหญ่

เลือกก้อนนี้เป็นก้อนแรกเพราะ **ไม่พึ่งตัวแปรใน `clip_app` เลย** — อ่านค่าคงที่
จากโมดูลอื่นแล้วคืนข้อมูลออกมาอย่างเดียว ถ้าพังก็พังแค่หน้าโชว์คำสั่ง
ไม่กระทบการเจนคลิป จึงปลอดภัยพอจะใช้พิสูจน์ว่าวิธีผ่าแบบนี้ใช้ได้จริง

ก่อนแยก `clip_app.py` มี 10,825 บรรทัด ซึ่งทำให้ทุกแชทต้องมาแตะไฟล์เดียวกัน
(app.py ถูกแก้ 60 commit ใน 30 วัน) แล้ว commit แยกกันไม่ได้
"""
from __future__ import annotations

import chatgpt_driver
import clip_rules


def _prompt_groups() -> list[dict]:
    """คำสั่งจริงที่ส่งเข้า AI แต่ละเจ้า แยกเป็นก้อนให้หน้าเว็บวาดได้เลย

    **ประกอบจากค่าคงที่จริงในโค้ด ไม่ใช่ข้อความที่เขียนอธิบายไว้**
    แก้โค้ดเมื่อไรหน้านี้เปลี่ยนตามทันที ไม่ต้องมาแก้สองที่
    """
    import shopee_scrape                                     # noqa: PLC0415

    want = chatgpt_driver.HIGHLIGHT_SCENES
    closing = chatgpt_driver.pick_closing("ตัวอย่าง")
    rules_label, rules_text = clip_rules.ask_of({})

    return [
        {
            "key": "gemini_images",
            "step": 2,
            "service": "Gemini",
            "title": "เลือกรูปเข้าคลิป",
            "note": "ส่งคำสั่งข้างล่างพร้อมรูปสินค้าทุกใบ แล้วให้ตอบกลับมาเป็น"
                    f"เลขรูปที่เลือก {want} ใบ",
            "models": list(getattr(shopee_scrape, "IMAGE_JUDGE_MODELS", [])),
            "parts": [
                {"label": "คำสั่งหลัก",
                 "source": "shopee_scrape.IMAGE_JUDGE_PROMPT",
                 "text": shopee_scrape.IMAGE_JUDGE_PROMPT.format(count=want)},
                {"label": "ต่อท้ายเมื่อสินค้าปรับเปลี่ยนรูปทรงได้",
                 "source": "clip_app (hint)",
                 "vary": True,
                 "text": "ใส่เฉพาะใบที่จุดเด่นบอกว่าสินค้าพับ/ปรับ/หมุนได้ "
                         "— บอกให้เลือกรูปให้ครบทุกท่า"},
            ],
        },
        {
            "key": "gemini_highlights",
            "step": 2,
            "service": "Gemini",
            "title": "ไล่จุดเด่นจากคำบรรยายสินค้า",
            "note": "แทนที่ {name} ด้วยชื่อสินค้า และ {detail} ด้วยคำบรรยายจาก "
                    "Shopee (ตัดที่ 6,000 ตัวอักษร)",
            "models": list(getattr(shopee_scrape, "IMAGE_HIGHLIGHT_CHOICES", [])
                           or getattr(shopee_scrape, "IMAGE_JUDGE_MODELS", [])),
            "parts": [
                {"label": "คำสั่งหลัก",
                 "source": "shopee_scrape.ANALYSE_PROMPT",
                 "text": shopee_scrape.ANALYSE_PROMPT.replace(
                     "{count}", str(want))},
            ],
        },
        {
            "key": "chatgpt_storyboard",
            "step": 3,
            "service": "ChatGPT",
            "title": "ทำสตอรีบอร์ด (ข้อความที่ 1)",
            "note": "ส่งพร้อมรูปสินค้าที่คัดไว้ ไปที่ custom GPT ตัวที่เจ้าของ"
                    "ตั้งค่าไว้ — ดูข้อความที่ 2 ต่อข้างล่าง",
            "gpt_url": chatgpt_driver.storyboard_slot(1).get("gpt", ""),
            "parts": [
                {"label": "⚠️ พร้อมประจำตัวของ custom GPT",
                 "source": "อยู่ฝั่ง OpenAI — โค้ดเราอ่านหรือแก้ไม่ได้",
                 "outside": True,
                 "text": "ส่วนนี้เจ้าของตั้งไว้ในตัว GPT เอง ระบบเราไม่เห็น\n"
                         "แก้ได้ที่หน้าตั้งค่าของ custom GPT บน chatgpt.com เท่านั้น\n\n"
                         "⚠️ ถ้าพร้อมตรงนั้นขัดกับกติกาข้างล่าง GPT จะเลือกฟัง"
                         "อันใดอันหนึ่ง แล้วเราจะไล่สาเหตุยาก\n"
                         "(เจอจริง 31 ส.ค. 2569 ขัดกัน 3 จุด)"},
                {"label": "ข้อมูลสินค้า + จุดเด่น",
                 "source": "chatgpt_driver.make_storyboard",
                 "vary": True,
                 "text": "สินค้า: <ชื่อสินค้า>\n\n"
                         "จุดเด่น:\n- <จุดเด่นข้อ 1>\n- <จุดเด่นข้อ 2>\n…\n\n"
                         "แนบรูปสินค้าจริงมาให้ N ใบ (เรียงเป็นรูปที่ 1–N)"},
                {"label": f"กติกาที่ติ๊กเปิดไว้{(' — ' + rules_label) if rules_label else ''}",
                 "source": "clip_rules.ask_of()",
                 "text": rules_text or "(ตอนนี้ไม่ได้ติ๊กข้อไหนไว้)"},
                {"label": "คำขอปิดท้าย",
                 "source": "chatgpt_driver.make_storyboard",
                 "text": "ช่วยทำ storyboard สำหรับคลิปโฆษณาสั้น "
                         "แล้ว**ออกมาเป็นรูปภาพ** ให้ด้วย"},
            ],
        },
        {
            "key": "chatgpt_flow",
            "step": 3,
            "service": "ChatGPT",
            "title": "ขอคำสั่ง Google Flow + บทพูด (ข้อความที่ 2)",
            "note": "ถามต่อในแชทเดิมหลังได้สตอรีบอร์ดแล้ว — บทพูดที่คลิปพูดจริง"
                    "มาจากบรรทัด Audio ในคำตอบนี้",
            "parts": [
                {"label": "คำขอ (เจ้าของกำหนดถ้อยคำเอง ห้ามแก้)",
                 "source": "chatgpt_driver.FLOW_PROMPT_ASK",
                 "text": chatgpt_driver.FLOW_PROMPT_ASK},
                {"label": "กติกาบรรทัดเสียง + ประโยคปิดการขาย",
                 "source": "chatgpt_driver.flow_audio_rule()",
                 "text": chatgpt_driver.flow_audio_rule(closing)},
                {"label": "ประโยคปิดการขายที่สุ่มได้",
                 "source": "chatgpt_driver.CLOSING_LINES",
                 "vary": True,
                 "text": "สุ่มจากรหัสสินค้า ใบเดิมได้ประโยคเดิมเสมอ:\n"
                         + "\n".join(f"- {x}" for x in chatgpt_driver.CLOSING_LINES)},
            ],
        },
    ]
