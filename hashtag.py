"""สร้างและคัดแฮชแท็กสำหรับโพสต์วิดีโอ

กติกาที่ผู้ใช้กำหนด — แฮชแท็ก 5 ตัวประกอบจาก
    1. ยี่ห้อสินค้า
    2. ชนิดของสินค้า
    3. ชนิดสินค้า + รายละเอียด 1
    4. ชนิดสินค้า + รายละเอียด 2
    5. ชนิดสินค้า + รายละเอียด 3

แล้วพิมพ์ทีละตัวลงช่องแฮชแท็กของแอป พอพิมพ์ครบแอปจะโชว์ "ยอดพูดถึง"
ของแท็กนั้น — **เอาเฉพาะตัวที่มากกว่า 10,000** ที่เหลือทิ้ง

ทำไมต้องอ่านยอดจากหน้าจอ ไม่คำนวณเอง
    ยอดพูดถึงเป็นข้อมูลฝั่ง Shopee ไม่มี API สาธารณะให้ถาม การเดาเองแล้วโพสต์
    แท็กที่ไม่มีคนตามคือเสียพื้นที่แท็กฟรีๆ จึงต้องพิมพ์แล้วอ่านของจริง

ไฟล์นี้เก็บเฉพาะส่วนที่ **ไม่ต้องมีมือถือ** เพื่อให้ทดสอบได้ด้วยข้อความล้วน
ส่วนการพิมพ์/แตะหน้าจอจริงอยู่ใน publish_flow.py
"""

from __future__ import annotations

import json
import re

# เกณฑ์ยอดพูดถึงขั้นต่ำ — ผู้ใช้กำหนดไว้ที่หมื่น
MENTION_MIN = 10_000

TAG_COUNT = 5
MAX_TAG_LENGTH = 40          # แท็กยาวเกินนี้แอปมักตัดเอง และไม่มีใครค้นหา


# ------------------------------------------------------- แปลงข้อความเป็นแท็ก


# อักขระที่ใช้ในแฮชแท็กไม่ได้ — เว้นวรรคด้วย เพราะเว้นวรรคคือตัวจบแท็ก
TAG_STRIP_RE = re.compile(r"[\s#\-–—_/\\|,.;:!?\"'()\[\]{}<>+*&%$@^~`=]+")


def normalize(text: str) -> str:
    """ตัดอักขระที่แฮชแท็กใช้ไม่ได้ออก **โดยไม่ตัดความยาว**

    แยกจาก to_tag เพราะ to_tag ตัดที่ 40 ตัวอักษรตามข้อจำกัดของแท็ก ซึ่งใช้กับ
    ข้อความต้นทางไม่ได้ (เจอจริง: ชื่อสินค้าขึ้นต้นด้วย 【จัดส่งภายใน 24 ชั่วโมง
    ที่กรุงเทพฯ】 ยาวเกิน 40 ตัว ทำให้ยี่ห้อ "Trikings" ที่อยู่ถัดไปถูกตัดหาย
    แล้วด่านตรวจยี่ห้อฟันว่าเป็นของแต่งขึ้น ทั้งที่มีอยู่จริง)
    """
    return TAG_STRIP_RE.sub("", str(text or "")).strip()


def to_tag(*parts: str) -> str:
    """ต่อคำเป็นแฮชแท็กตัวเดียว — ตัดเว้นวรรคทิ้งเพราะแท็กมีช่องว่างไม่ได้

    ผู้ใช้ยืนยันรูปแบบ "ชนิดสินค้า+รายละเอียด" ให้ต่อติดกัน เช่น
        โซฟาเบด + ปรับนั่งนอนได้ -> โซฟาเบดปรับนั่งนอนได้
    """
    joined = "".join(str(part or "") for part in parts)
    clean = TAG_STRIP_RE.sub("", joined).strip()
    return clean[:MAX_TAG_LENGTH]


def build_candidates(brand: str, kind: str, details: list[str]) -> list[str]:
    """ประกอบแท็ก 5 ตัวตามสูตรของผู้ใช้ — คืนเป็นชื่อแท็กล้วน ไม่มี #

    ตัวที่ประกอบแล้วว่างหรือซ้ำกับตัวก่อนหน้าจะถูกตัดทิ้ง เพราะพิมพ์ซ้ำ
    ในแอปจะได้แท็กเดิมสองครั้ง เปลืองช่องเปล่าๆ
    """
    raw = [to_tag(brand), to_tag(kind)]
    for detail in (details or [])[:3]:
        raw.append(to_tag(kind, detail))
    seen: set[str] = set()
    tags: list[str] = []
    for tag in raw:
        key = tag.casefold()
        if not tag or key in seen:
            continue
        seen.add(key)
        tags.append(tag)
    return tags[:TAG_COUNT]


# ------------------------------------------------------- อ่านยอดพูดถึงบนจอ


# หน่วยย่อที่เคยเห็นบนแอปไทย/อังกฤษ — ตัวคูณของแต่ละหน่วย
UNIT_MULTIPLIER = {
    "พัน": 1_000, "หมื่น": 10_000, "แสน": 100_000, "ล้าน": 1_000_000,
    "k": 1_000, "m": 1_000_000, "b": 1_000_000_000,
}

# ตัวเลขที่อาจมีจุดทศนิยม ตามด้วยหน่วย (เว้นวรรคหรือไม่ก็ได้)
COUNT_RE = re.compile(
    r"(\d[\d,]*(?:\.\d+)?)\s*(พัน|หมื่น|แสน|ล้าน|[KkMmBb])?",
)


def parse_mention_count(text: str) -> int | None:
    """แปลงข้อความยอดพูดถึงเป็นจำนวนเต็ม — คืน None ถ้าไม่ใช่ตัวเลขยอด

    รองรับที่เจอได้จริงบนแอป: `12,345` · `1.2 หมื่น` · `12K` · `3 ล้าน`
    ตั้งใจ **ไม่เดา** เมื่ออ่านไม่ออก — คืน None แล้วให้ผู้เรียกรายงานตรงๆ
    ว่าอ่านยอดไม่ได้ ดีกว่าเดาเป็น 0 แล้วทิ้งแท็กที่จริงๆ ยอดสูง
    """
    if not text:
        return None
    match = COUNT_RE.search(str(text).replace(" ", " "))
    if not match:
        return None
    number_text, unit = match.group(1), (match.group(2) or "")
    try:
        number = float(number_text.replace(",", ""))
    except ValueError:
        return None
    multiplier = UNIT_MULTIPLIER.get(unit.casefold(), 1) if unit else 1
    return int(round(number * multiplier))


# ข้อความรอบตัวเลขที่บอกว่านี่คือ "ยอดพูดถึง" ไม่ใช่ตัวเลขอย่างอื่นบนจอ
MENTION_HINT_RE = re.compile(
    r"(โพสต์|ครั้ง|มีการพูดถึง|พูดถึง|views?|posts?|mentions?)", re.I
)


def looks_like_mention(text: str) -> bool:
    """ข้อความนี้น่าจะเป็นยอดพูดถึงไหม

    ใช้กรองตัวเลขอื่นบนแถวเดียวกัน (เช่นลำดับที่ หรือราคา) ออกก่อนแปลง
    ถ้าเป็นตัวเลขล้วนไม่มีคำใบ้ ก็ยังรับ — แอปบางรุ่นโชว์แค่ตัวเลขเปล่า
    """
    if not text:
        return False
    if MENTION_HINT_RE.search(text):
        return True
    return bool(re.fullmatch(r"[\d,.\s]*\d[\d,.\s]*(พัน|หมื่น|แสน|ล้าน|[KkMmBb])?", text.strip()))


def passes(count: int | None, minimum: int = MENTION_MIN) -> bool:
    """ผ่านเกณฑ์ไหม — อ่านยอดไม่ได้ถือว่า **ไม่ผ่าน**

    เลือกทางนี้เพราะโพสต์แท็กที่ไม่รู้ยอดคือเดาสุ่ม ส่วนการตกหล่นไป 1 แท็ก
    เสียหายน้อยกว่า และระบบรายงานให้เห็นทุกตัวว่าอ่านได้เท่าไร
    """
    return count is not None and count > minimum


# ------------------------------------------------------- สกัดยี่ห้อ/ชนิดสินค้า


def _fallback_parts(name: str, highlights: list[str]) -> dict:
    """ไม่มีคีย์ Gemini — เดาจากชื่อสินค้าด้วยกฎง่ายๆ

    ชื่อสินค้าบน Shopee มักขึ้นต้นด้วยคำโปรโมชัน (`ส่งฟรี`, `【...】`) แล้วค่อยเป็น
    ยี่ห้อ จึงตัดวงเล็บ/คำโปรทิ้งก่อนแล้วเอาคำแรกเป็นยี่ห้อ คำถัดไปเป็นชนิด
    ผลลัพธ์หยาบแน่นอน — จึงต้องให้ผู้ใช้แก้ได้ในแชทเสมอ
    """
    text = re.sub(r"【[^】]*】|\[[^\]]*\]|\([^)]*\)", " ", name or "")
    text = re.sub(r"(ส่งฟรี|ลดราคา|โปรโมชั่น|พร้อมส่ง|แถมฟรี|ของแท้)", " ", text)
    words = [word for word in re.split(r"[\s/|,]+", text) if word]
    brand = words[0] if words else ""
    kind = words[1] if len(words) > 1 else ""
    # จุดเด่นเป็นประโยคยาว 60 ตัวอักษร เอามาต่อท้ายชนิดสินค้าตรงๆ จะได้แท็กที่
    # ถูกตัดกลางคำและไม่มีใครค้นหา — ตัดเหลือวรรคแรกสั้นๆ พอเป็นคำค้น
    details = []
    for item in (highlights or [])[:3]:
        short = re.split(r"[\s,·]+", str(item).strip())[0]
        if short:
            details.append(short[:15])
    return {"brand": brand, "kind": kind, "details": details}


PARTS_PROMPT = (
    "นี่คือสินค้าจาก Shopee\n"
    "ชื่อ: {name}\n"
    "จุดเด่นที่สรุปไว้: {highlights}\n\n"
    "แยกข้อมูลออกมาเพื่อเอาไปทำแฮชแท็ก ตอบเป็น JSON object เท่านั้น 3 คีย์:\n"
    '  "brand"   = ยี่ห้อสินค้า **คัดลอกมาจากชื่อสินค้าตรงตัวอักษรต่ออักษร** '
    "ห้ามแปล ห้ามถอดเป็นคำอ่านไทย ห้ามเดาจากความรู้ภายนอก "
    "ถ้าชื่อสินค้าไม่ได้บอกยี่ห้อไว้ ให้ตอบเป็นสตริงว่าง\n"
    '  "kind"    = ชนิดของสินค้าแบบสั้นที่สุดที่คนใช้ค้นหา เช่น "โซฟาเบด" '
    '"เราเตอร์ใส่ซิม" (ห้ามใส่ยี่ห้อ ห้ามใส่รุ่น)\n'
    '  "details" = อาร์เรย์ 3 ข้อความสั้นๆ ที่เป็นคุณสมบัติเด่นที่คนน่าจะค้นหา '
    "ข้อละไม่เกิน 15 ตัวอักษร ห้ามมีเว้นวรรค ห้ามซ้ำกัน\n"
    "kind กับ details เป็นภาษาไทย ส่วน brand ใช้ตัวสะกดเดิมจากชื่อสินค้า "
    "ห้ามมีคำอธิบายอื่นนอก JSON"
)


def verify_brand(brand: str, *sources: str) -> str:
    """คืนยี่ห้อเฉพาะเมื่อมันปรากฏในข้อความต้นทางจริง ไม่งั้นคืนสตริงว่าง

    **เจอจริง**: Gemini ตอบยี่ห้อ "TP-Link" ให้สินค้าชื่อ "Pocket WiFi6 ใส่ซิม
    Wireless 3000mAh 4G Router SIM AIS True NT" ซึ่งไม่มีคำนั้นอยู่เลย —
    เป็นการเดาจากความรู้ภายนอก ถ้าปล่อยผ่านจะได้แท็กยี่ห้อผิดตัวติดคลิปไปเลย

    เทียบแบบตัดเว้นวรรค/ขีด/จุด และไม่สนตัวพิมพ์ เพื่อให้ "D-Link" จับคู่กับ
    "DLink" ได้ แต่คำอ่านไทย ("ดีลิงก์") จะไม่ผ่าน — ตั้งใจให้ไม่ผ่าน
    เพราะคนค้นหาด้วยตัวสะกดจริงมากกว่าคำอ่าน
    """
    tag = normalize(brand).casefold()
    if not tag:
        return ""
    haystack = normalize(" ".join(sources)).casefold()
    return brand.strip() if tag in haystack else ""


def extract_parts(
    name: str, highlights: list[str], api_key: str | None, log=print
) -> dict:
    """สกัด {brand, kind, details[3]} จากข้อมูลสินค้า

    ให้ AI ทำเพราะชื่อสินค้าบน Shopee ยาวและปนคำโปรโมชันจนกฎธรรมดาแยกไม่ออก
    (เช่น "【จัดส่งภายใน 24 ชั่วโมง ที่กรุงเทพฯ】Trikings เวอร์ชันอัปเกรด โซฟาเบด...")
    ล้มเหลวเมื่อไรถอยไปใช้กฎ ไม่ทำให้ทั้งงานพัง
    """
    if not api_key:
        log("ไม่มีคีย์ Gemini — แยกยี่ห้อ/ชนิดสินค้าด้วยกฎแทน")
        return _fallback_parts(name, highlights)

    import httpx

    instruction = PARTS_PROMPT.format(
        name=(name or "")[:300],
        highlights=" · ".join(highlights or []) or "(ไม่มี)",
    )
    try:
        response = httpx.post(
            "https://generativelanguage.googleapis.com/v1beta/models/"
            "gemini-3.5-flash:generateContent",
            params={"key": api_key},
            json={"contents": [{"parts": [{"text": instruction}]}]},
            timeout=60.0,
        )
        if response.status_code != 200:
            raise RuntimeError(f"Gemini ตอบ {response.status_code}")
        text = response.json()["candidates"][0]["content"]["parts"][0]["text"]
        found = re.search(r"\{.*\}", text, re.S)
        if not found:
            raise RuntimeError("Gemini ไม่ได้ตอบเป็น JSON")
        data = json.loads(found.group(0))
        details = [str(item).strip() for item in (data.get("details") or [])]
        raw_brand = str(data.get("brand") or "").strip()
        brand = verify_brand(raw_brand, name or "", " ".join(highlights or []))
        if raw_brand and not brand:
            log(f"ยี่ห้อ \"{raw_brand}\" ไม่มีอยู่ในชื่อสินค้า — ตัดทิ้งกันแท็กผิดตัว")
        parts = {
            "brand": brand,
            "kind": str(data.get("kind") or "").strip(),
            "details": [item for item in details if item][:3],
        }
        if not parts["kind"]:
            raise RuntimeError("Gemini ไม่ได้บอกชนิดสินค้า")
        return parts
    except Exception as error:
        log(f"แยกยี่ห้อ/ชนิดสินค้าด้วย Gemini ไม่สำเร็จ ({error}) — ใช้กฎแทน")
        return _fallback_parts(name, highlights)


def plan_for_run(run: dict, api_key: str | None, log=print) -> dict:
    """เตรียมชุดแท็กของสินค้าหนึ่งตัว พร้อมส่วนประกอบที่ผู้ใช้แก้ได้ในแชท

    คืน {brand, kind, details[], tags[]} — เก็บส่วนประกอบไว้ด้วยเพราะผู้ใช้
    ต้องแก้ยี่ห้อ/ชนิด/รายละเอียดได้ทีละชิ้น แล้วให้ระบบประกอบแท็กใหม่เอง
    ถ้าเก็บแต่แท็กสำเร็จรูป จะแก้ทีต้องพิมพ์ใหม่ทั้งตัว
    """
    parts = extract_parts(
        run.get("name", ""), run.get("highlights") or [], api_key, log=log
    )
    parts["tags"] = build_candidates(
        parts["brand"], parts["kind"], parts["details"]
    )
    return parts
