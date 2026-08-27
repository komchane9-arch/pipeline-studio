"""สร้างและคัดแฮชแท็กสำหรับโพสต์วิดีโอ

กติกาที่ผู้ใช้กำหนด (แก้ล่าสุด 22 ส.ค. 2026) — แฮชแท็ก 5 ตัว
    1. ยี่ห้อสินค้า
    2. ชนิดของสินค้า
    3. จุดเด่นสินค้า 1   (2-5 พยางค์)
    4. จุดเด่นสินค้า 2   (2-5 พยางค์)
    5. จุดเด่นสินค้า 3   (2-5 พยางค์)

**เปลี่ยนจากสูตรเดิม** ข้อ 3-5 เดิมเป็น "ชนิดสินค้า + รายละเอียด" ต่อกัน
(เช่น โซฟาเบด + ปรับนั่งนอนได้ = #โซฟาเบดปรับนั่งนอนได้) ซึ่งได้แท็กยาวและ
ซ้ำคำว่าชนิดสินค้าทั้งสามตัว ตอนนี้ใช้ **จุดเด่นล้วนๆ สั้น 2-5 พยางค์**
(#ปรับนั่งนอนได้) เพราะคนค้นหาด้วยคำสั้นที่เป็นคุณสมบัติ ไม่ได้พิมพ์ยาวขนาดนั้น

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
import gemini_quota

# ตัวอ่านยอดพูดถึงย้ายไป mention_count.py แล้ว (แยกของสายโพสต์ออกจากสายคลิป
# ผู้ใช้สั่ง 27 ส.ค. 2026) — ดึงกลับมาไว้ที่นี่ด้วย เพื่อให้ของเดิมที่เรียก
# `hashtag_lib.passes()` / `hashtag_lib.MENTION_MIN` ทำงานต่อได้โดยไม่ต้องแก้ตาม
from mention_count import (                                    # noqa: F401
    MENTION_MIN, looks_like_mention, parse_mention_count, passes,
)


TAG_COUNT = 5
MAX_TAG_LENGTH = 40          # แท็กยาวเกินนี้แอปมักตัดเอง และไม่มีใครค้นหา

# โมเดลที่ใช้แยกยี่ห้อ/ชนิดสินค้า — **ต้องมีทางถอย** (เพิ่ม 27 ส.ค. 2026)
#
# ของเดิมยิงโมเดลเดียวแล้วจบ ถ้าตัวนั้นล่มก็ตกไปใช้กฎเดาจากชื่อสินค้าทันที
# ซึ่งได้ยี่ห้อผิดบ่อยกับชื่อที่ขึ้นต้นด้วยคำโปรโมชัน — **จุดเดียวที่พังแล้วพังทั้งระบบ**
#
# เหตุผลเดิมที่เลือก 3.1-flash-lite-preview คือ "ไม่ซ้ำถังโควตากับใคร" ซึ่งหมด
# ความจำเป็นแล้วตั้งแต่เจ้าของเปิดการเรียกเก็บเงิน (27 ส.ค.) แต่ยังเก็บไว้เป็น
# ตัวแรกเพราะงานนี้เป็นงานข้อความสั้น ตัว lite ทำได้ดีและเร็วที่สุด
# (วัดกับงานข้อความจริง: 3.5-flash-lite 2.0 วิ · 3.6-flash 15.7 วิ)
#
# **ห้ามใส่ gemini-3.7-flash** — 27 ส.ค. ล้ม 68/68 ครั้ง ทั้งงานรูปและงานข้อความ
MODELS = (
    "gemini-3.1-flash-lite-preview",
    "gemini-3.5-flash-lite",
    "gemini-3.6-flash",
)


# ------------------------------------------------------- นับพยางค์ (ประมาณ)

# เกณฑ์ความยาวของแท็กจุดเด่น ตามที่ผู้ใช้สั่ง 22 ส.ค. 2026
DETAIL_MIN_SYLLABLES = 2
DETAIL_MAX_SYLLABLES = 5
# ตาข่ายชั้นสอง — พยางค์ไทยยาว ~2-4 ตัวอักษร 5 พยางค์จึงราว 20 ตัว
# ใช้คู่กับตัวนับพยางค์เสมอ เพราะตัวนับเป็นการประมาณ ไม่ใช่การตัดคำจริง
DETAIL_MAX_CHARS = 20

_TONE_RE = re.compile(r"[่-๋๎]")        # ่ ้ ๊ ๋ ๎
_KARAN_RE = re.compile(r"[ก-ฮ]์")       # พยัญชนะที่ถูก ์ ฆ่าเสียง
_LEAD_VOWEL_RE = re.compile(r"[เแโใไ]")                # สระหน้า = ขึ้นพยางค์ใหม่เสมอ
_FOLLOW_VOWEL_RE = re.compile(r"[ะัาำิีึืุูๅ็]+")       # สระบน/ล่าง/หลัง ติดกันนับเป็นตัวเดียว
_CONSONANT_RUN_RE = re.compile(r"[ก-ฮ]{3,}")  # พยัญชนะเรียงยาว = มีสระลดรูปซ่อน
# พยางค์ที่ขึ้นต้นด้วยสระหน้าและมีสระตามอยู่ในตัวเดียวกัน (เย็น · เหนียว · เร็ว)
# ต้องยุบให้เหลือรอยเดียวก่อนนับ ไม่งั้นสระหน้ากับสระตามของ **พยางค์เดียวกัน**
# ถูกนับเป็นสองพยางค์ (วัดจริง: "เย็นเร็ว" ได้ 4 ทั้งที่มี 2)
#
# ตัวสะกดท้ายพยางค์ต้อง **ไม่ตามด้วยสระ** ไม่งั้นจะไปกินพยัญชนะต้นของพยางค์
# ถัดไป (วัดจริง: "โซฟาเบด" ได้ 2 ทั้งที่มี 3 เพราะ "ฟ" ของ "ฟา" ถูกกินไป
# เป็นตัวสะกดของ "โซ") ส่วนพยัญชนะควบรับเฉพาะ ร ล ว ที่ควบได้จริง
_LEAD_CLUSTER_RE = re.compile(
    r"[เแโใไ][ก-ฮ][รลว]?[ะัาำิีึืุูๅ็]*(?:[ก-ฮ](?![ะัาำิีึืุูๅ็]))?"
)


def count_syllables(text: str) -> int:
    """**ประมาณ** จำนวนพยางค์ไทย — ไม่ใช่การตัดคำจริง

    ทำไมประมาณ: การนับพยางค์ไทยให้ถูกต้องต้องใช้พจนานุกรมตัดคำ (pythainlp)
    ซึ่งโปรเจกต์นี้ไม่ได้ติดตั้งและไม่คุ้มจะเพิ่มเพื่องานนี้อย่างเดียว

    **ค่านี้ใช้เป็นตัวกรองหยาบเท่านั้น ห้ามใช้ตัดแท็กทิ้ง** — ตัวคุมพยางค์ตัวจริง
    คือคำสั่งที่ส่งให้ Gemini (ดู PARTS_PROMPT) ซึ่งเข้าใจภาษาไทยจริง ที่นี่แค่
    กันของที่ยาวเกินจนเห็นได้ชัดหลุดออกไป

    วิธีนับ: สระหน้า 1 ตัว = 1 พยางค์ · กลุ่มสระบน/ล่าง/หลัง = 1 พยางค์ ·
    พยัญชนะเรียงกันตั้งแต่ 3 ตัว = มีสระลดรูปซ่อนอยู่ (นอน · คน) นับเพิ่ม
    """
    clean = _KARAN_RE.sub("", _TONE_RE.sub("", normalize(text)))
    if not clean:
        return 0
    # ยุบพยางค์สระหน้าให้เหลือรอยเดียวก่อน แล้วค่อยนับสระที่เหลือ
    clean = _LEAD_CLUSTER_RE.sub("เ", clean)
    count = (
        len(_LEAD_VOWEL_RE.findall(clean))
        + len(_FOLLOW_VOWEL_RE.findall(clean))
        + sum(len(run) // 3 for run in _CONSONANT_RUN_RE.findall(clean))
    )
    return max(count, 1)


def detail_ok(text: str) -> bool:
    """จุดเด่นนี้อยู่ในเกณฑ์ 2-5 พยางค์ไหม (วัดด้วยตัวประมาณ + ความยาวตัวอักษร)"""
    clean = normalize(text)
    if not clean or len(clean) > DETAIL_MAX_CHARS:
        return False
    return DETAIL_MIN_SYLLABLES <= count_syllables(clean) <= DETAIL_MAX_SYLLABLES


def trim_to_syllables(text: str, limit: int = DETAIL_MAX_SYLLABLES) -> str:
    """ตัดข้อความให้เหลือไม่เกิน `limit` พยางค์ — **ตัดที่ขอบพยางค์ ไม่ใช่กลางคำ**

    ตัดด้วยจำนวนตัวอักษรตรงๆ ได้เศษคำที่ไม่มีใครค้นหา (วัดจริง: ตัดที่ 20 ตัว
    ได้ "#ระบายอากาศได้ดีมากจร" — คำท้ายขาดครึ่ง) พอไล่ตัดทีละตัวจนพยางค์
    เข้าเกณฑ์ จะได้ "#ระบายอากาศได้" ซึ่งยังอ่านรู้เรื่องและใช้ค้นหาได้จริง
    """
    clean = normalize(text)
    while clean and count_syllables(clean) > limit:
        clean = clean[:-1]
    return clean


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


def build_candidates(brand: str, kind: str, details: list[str], log=None) -> list[str]:
    """ประกอบแท็ก 5 ตัวตามสูตรของผู้ใช้ — คืนเป็นชื่อแท็กล้วน ไม่มี #

        1 ยี่ห้อ · 2 ชนิดสินค้า · 3-5 จุดเด่น (2-5 พยางค์ ไม่ต่อชนิดสินค้านำหน้า)

    ตัวที่ประกอบแล้วว่างหรือซ้ำกับตัวก่อนหน้าจะถูกตัดทิ้ง เพราะพิมพ์ซ้ำ
    ในแอปจะได้แท็กเดิมสองครั้ง เปลืองช่องเปล่าๆ

    จุดเด่นที่ยาวเกินเกณฑ์ **ไม่ทิ้ง** แต่ตัดให้สั้นลงแล้วยังใช้ — เพราะตัวนับ
    พยางค์เป็นการประมาณ (ดู count_syllables) ถ้าเชื่อมันจนทิ้งแท็กดีไปเลย
    จะเสียแท็กฟรีทั้งที่ของจริงอาจอยู่ในเกณฑ์
    """
    raw = [to_tag(brand), to_tag(kind)]
    for detail in (details or [])[:3]:
        tag = to_tag(detail)
        if tag and not detail_ok(tag):
            short = trim_to_syllables(tag)
            # บอกทุกครั้งที่ตัด — การตัดที่ขอบพยางค์ยังทิ้งเศษพยัญชนะท้ายได้
            # (แยก "แดด" ที่ถูกกับ "ได้ด" ที่เป็นเศษ ต้องใช้พจนานุกรมตัดคำ)
            # ผู้ใช้จึงต้องเห็นว่าตัวไหนถูกตัด แล้วแก้เองในแชทได้
            if log and short != tag:
                log(f"จุดเด่น \"{tag}\" ยาวเกิน {DETAIL_MAX_SYLLABLES} พยางค์ "
                    f"— ตัดเหลือ \"{short}\" (แก้เองได้ถ้าอ่านแล้วขาดคำ)")
            tag = short
        raw.append(tag)
    seen: set[str] = set()
    tags: list[str] = []
    for tag in raw:
        key = tag.casefold()
        if not tag or key in seen:
            continue
        seen.add(key)
        tags.append(tag)
    return tags[:TAG_COUNT]


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
    # จุดเด่นเป็นประโยคยาว 60 ตัวอักษร ใช้ทั้งประโยคจะได้แท็กที่ถูกตัดกลางคำ
    # และไม่มีใครค้นหา — ตัดเหลือวรรคแรกสั้นๆ พอเป็นคำค้นตามเกณฑ์ 2-5 พยางค์
    details = []
    for item in (highlights or [])[:3]:
        short = re.split(r"[\s,·]+", str(item).strip())[0]
        if short:
            details.append(short[:DETAIL_MAX_CHARS])
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
    '  "details" = อาร์เรย์ 3 ข้อความสั้นๆ ที่เป็น**จุดเด่นของสินค้า**ที่คนน่าจะค้นหา '
    "**ข้อละ 2-5 พยางค์เท่านั้น** (เช่น กันน้ำ · ปรับนั่งนอนได้ · ประหยัดไฟ) "
    "ห้ามมีเว้นวรรค ห้ามซ้ำกัน "
    "**ห้ามใส่ชนิดสินค้าหรือยี่ห้อนำหน้า** เพราะสองอย่างนั้นเป็นแท็กแยกอยู่แล้ว "
    "(ผิด: โซฟาเบดปรับนั่งนอนได้ · ถูก: ปรับนั่งนอนได้)\n"
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
    try:
        gemini_quota.check_budget("ตั้งแฮชแท็ก")
    except Exception as error:                               # noqa: BLE001
        log(f"{error} — ใช้กฎตั้งแฮชแท็กแทน")
        return _fallback_parts(name, highlights)

    import httpx

    instruction = PARTS_PROMPT.format(
        name=(name or "")[:300],
        highlights=" · ".join(highlights or []) or "(ไม่มี)",
    )
    tried: list[str] = []
    for pick in MODELS:
        try:
            response = httpx.post(
                "https://generativelanguage.googleapis.com/v1beta/models/"
                f"{pick}:generateContent",
                params={"key": api_key},
                json={"contents": [{"parts": [{"text": instruction}]}]},
                timeout=60.0,
            )
            gemini_quota.record(pick, ok=response.status_code == 200,
                                response=response)
            if response.status_code != 200:
                raise RuntimeError(f"{pick} ตอบ {response.status_code}")
            text = response.json()["candidates"][0]["content"]["parts"][0]["text"]
            found = re.search(r"\{.*\}", text, re.S)
            if not found:
                raise RuntimeError(f"{pick} ไม่ได้ตอบเป็น JSON")
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
                raise RuntimeError(f"{pick} ไม่ได้บอกชนิดสินค้า")
            if pick != MODELS[0]:
                log(f"แยกยี่ห้อ/ชนิดสินค้าด้วยโมเดลสำรอง {pick}")
            return parts
        except Exception as error:                           # noqa: BLE001
            tried.append(f"{pick}: {error}")
            log(f"  แยกยี่ห้อ/ชนิดสินค้าด้วย {pick} ไม่สำเร็จ ({error})")
    log(f"ลองครบทุกโมเดลแล้วไม่สำเร็จ ({' · '.join(tried)}) — ใช้กฎแทน")
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
        parts["brand"], parts["kind"], parts["details"], log=log
    )
    return parts
