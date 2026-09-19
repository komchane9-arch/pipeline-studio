"""กติกาตัดสินว่า "สินค้า TikTok ที่หาเจอ คือสินค้าตัวเดียวกับใบงานจริงไหม"

**ทำไมต้องมีไฟล์นี้ — 14 ก.ย. 2569 TikTok ตีธงใบ 52807075353**
ว่าผิดนโยบาย *"โปรโมตสินค้าที่ไม่ตรงกับสินค้าจริง"* ผลคือคลิปถูกลดการมองเห็น
และสินค้าถูกถอดออกจากวิดีโอทั้งหมด

ไล่รากเหง้าจากของจริงในใบงานนั้นได้ 3 ชั้น (ทุกตัวเลขอ่านจาก ``run.json`` จริง)

1. **ตัดสินว่า "ตรง" จากหน้าตาอย่างเดียว** — เหตุผลที่ AI บันทึกไว้คือ
   *"decorative phone case with a similar glittery finish and Hello Kitty
   design"* ซึ่งเป็นความเหมือนของรูปล้วน ๆ เคสกากเพชรลายคิตตี้มีคนขาย
   เป็นร้อยเจ้า คนละร้าน คนละรายการ **แต่ระบบตอบ confidence = high**
   ซ้ำร้าย ชื่อประกาศที่อ่านได้ของอันดับ 1 คือ
   *"Lereach Anti-Spy HD Glass สำหรับ Vivo X300..."* ซึ่งเป็น **ฟิล์ม**
   ไม่ใช่ **เคส** — คนละชนิดสินค้ากันคนละเรื่อง
2. **คำค้นมีแต่รหัสรุ่น** — คำค้นจริงคือ
   ``สำหรับ Vivo X300 X300 pro X200 ultra X300fe ... V70 เคสdiandu``
   คำบอกชนิดสินค้า (``เคส``) ถูกกลืนอยู่ท้ายสุดติดกับขยะ ``diandu``
   TikTok จึงค้นด้วยรายการรหัสรุ่นล้วน แล้วคืนอะไรก็ได้ที่มีรุ่นตรง
3. **ชื่อที่อ่านจากหน้า TikTok ไม่ใช่ชื่อสินค้า** — บันทึกไว้จริงว่า
   ``x300 ultra x3oo pro x300 x3oo`` (คำซ้ำ · มีแต่รหัสรุ่น ·
   ``x3oo`` คือ ``x300`` ที่ตัวอ่านภาพอ่านเพี้ยน) **แต่ระบบก็ยังผูกให้**

ไฟล์นี้รวบกติกาทั้งสี่ข้อที่เจ้าของสั่งไว้ไว้ที่เดียว เพื่อไม่ให้ตัวหา ตัวโพสต์
และตัวตรวจย้อนหลังเขียนกติกาคนละอย่าง (บทเรียนเดียวกับ ``publish_order.py``)

**กติกา 2.3.1 บังคับทั้งไฟล์** — ทุกตัวตรวจในนี้คืน ``Verdict`` ที่แยก
``ok=None`` (ยังไม่ได้ตรวจ / ตรวจไม่ได้) ออกจาก ``ok=False`` (ตรวจแล้วไม่ผ่าน)
ชัดเจน **ห้ามยุบสองอย่างนี้เป็นค่าเดียวกันเด็ดขาด** ไม่งั้นวันที่ตรวจไม่ได้
ของเสียจะได้เครื่องหมายถูก
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# คำบอก "ชนิดสินค้า" — สิ่งที่ตอบคำถามว่า "ไอ้นี่มันคืออะไร"
# ---------------------------------------------------------------------------
#
# คำพวกนี้คือสิ่งที่หายไปจากคำค้นและจากชื่อที่อ่านได้ ในใบที่โดนตีธง
# รายการสร้างจากชื่อสินค้าจริง 113 ใบในโฟลเดอร์ ``data`` ไม่ได้นั่งเดาเอง
#
# คีย์ = ชื่อชนิดที่เอาไว้เทียบกัน (ใบงานเป็น "เคส" แต่ประกาศเป็น "ฟิล์ม"
# = คนละชนิด = ไม่ตรง) · ค่า = คำที่เจอได้จริงบนหน้าจอทั้งไทยและอังกฤษ
TYPE_WORDS: dict[str, tuple[str, ...]] = {
    "เคสมือถือ": ("เคสโทรศัพท์", "เคสมือถือ", "เคส", "phone case", "case"),
    "ฟิล์มกันจอ": ("ฟิล์มกระจก", "ฟิล์มกันรอย", "ฟิล์ม", "กระจกนิรภัย",
                   "ป้องกันหน้าจอ", "ปกป้องหน้าจอ", "screen protector",
                   "tempered glass", "anti-spy", "hd glass"),
    "สายชาร์จ": ("สายชาร์จ", "สายเคเบิล", "สายข้อมูล", "สายถัก",
                 "charging cable", "data cable", "cable"),
    "ที่ชาร์จ": ("ที่ชาร์จ", "เครื่องชาร์จ", "หัวชาร์จ", "ชุดชาร์จ",
                 "แท่นชาร์จ", "ที่ชาร์จไร้สาย", "อะแดปเตอร์ชาร์จ",
                 "charger", "wireless charger", "power adapter", "wall charger"),
    "พาวเวอร์แบงค์": ("พาวเวอร์แบงค์", "แบตเตอรี่สำรอง", "แบตสำรอง",
                      "power bank", "powerbank"),
    "ฮับ/แท่นวาง": ("ฮับ", "แท่นวาง", "แท่นต่อ", "hub", "docking station",
                    "dock", "splitter"),
    "อะแดปเตอร์": ("อะแดปเตอร์", "ตัวแปลง", "adapter", "converter"),
    "หูฟัง": ("หูฟัง", "earphone", "earbuds", "headphone"),
    "ปลั๊ก/ซ็อกเก็ต": ("ปลั๊ก", "ซ็อกเก็ต", "รางปลั๊ก", "socket", "plug"),
    "เราเตอร์": ("เราเตอร์", "เร้าเตอร์", "ใส่ซิม", "router", "pocket wifi",
                 "wifi6", "wi-fi"),
    "ทีวี": ("ทีวี", "โทรทัศน์", "tv", "television", "smart tv"),
    "จอคอม": ("จอคอม", "จอคอมพิวเตอร์", "monitor"),
    "แอร์": ("แอร์", "เครื่องปรับอากาศ", "air conditioner", "airconditioner"),
    "พัดลม": ("พัดลม", "fan"),
    "ตู้เย็น": ("ตู้เย็น", "refrigerator", "fridge"),
    "เครื่องซักผ้า": ("เครื่องซักผ้า", "washing machine"),
    "โซฟา": ("โซฟา", "โซฟาเบด", "sofa", "couch"),
    "เก้าอี้": ("เก้าอี้", "chair"),
    "โต๊ะ": ("โต๊ะ", "desk", "table"),
    "ที่นอน": ("ที่นอน", "ฟูก", "mattress"),
    "กระจกแต่งตัว": ("กระจกแต่งหน้า", "กระจกแต่งตัว", "กระจกตั้งพื้น",
                     "กระจกเสริมความงาม", "mirror"),
    "ชั้นวางของ": ("ชั้นวางของ", "ชั้นวาง", "ชั้นเก็บของ", "shelf", "rack"),
    "กล่องเก็บของ": ("กล่องเก็บ", "กล่องรองเท้า", "กล่องใส่",
                     "storage box", "organizer"),
    "เครื่องพิมพ์": ("เครื่องพิมพ์", "printer"),
    "ขาตั้ง": ("ขาตั้ง", "ที่วางโทรศัพท์", "stand", "holder", "mount"),
    "กระเป๋า": ("กระเป๋า", "bag", "pouch", "sleeve"),
    "ลำโพง": ("ลำโพง", "speaker"),
    "นาฬิกา": ("นาฬิกา", "smartwatch", "watch"),
    "ไฟ/โคมไฟ": ("โคมไฟ", "ไฟ led", "หลอดไฟ", "lamp", "light strip"),
}

# ``ชิ้นส่วนของชื่อ`` ที่ไม่ได้บอกว่าสินค้าคืออะไร — มีอยู่เต็มไปหมดในชื่อ
# Shopee แต่เอาไปค้นแล้วได้อะไรก็ไม่รู้
_FILLER = {
    "pro", "max", "plus", "ultra", "mini", "air", "lite", "fe", "series",
    "new", "for", "and", "with", "the", "set", "type", "edition", "version",
    "สำหรับ", "สําหรับ", "เหมาะสำหรับ", "เหมาะสําหรับ", "รุ่น", "ขนาด",
    "พร้อม", "แบบ", "และ", "หรือ", "ของ", "ใหม่", "แท้", "ชิ้น", "สี",
    "official", "mall", "shop", "store", "cod", "hot", "sale", "best",
    "seller", "free", "ส่งฟรี", "ลด", "โค้ด",
}

# รหัสรุ่น/สเปก: มีทั้งตัวอักษรและตัวเลขปนกัน (X300 · 65W · PD100W · 4K60HZ)
_CODE_RE = re.compile(r"^(?=[A-Za-z0-9/-]*[A-Za-z])(?=[A-Za-z0-9/-]*\d)[A-Za-z0-9/-]+$")
_THAI_MARKS_RE = re.compile(r"[ัิ-ฺ็-๎]")
_TOKEN_RE = re.compile(r"[A-Za-z0-9ก-๙]+(?:[-/][A-Za-z0-9]+)*")

_FILLER_FLAT: set[str] = set()   # เติมทีหลังเมื่อ ``normalize`` พร้อมใช้งาน

# คำขยายไทยที่วางไว้ "หน้า" ชนิดสินค้าได้ตามปกติ — เขียนในรูปที่ตัดวรรณยุกต์แล้ว
# เพราะเทียบกับข้อความที่ผ่าน ``normalize`` มา ("แผ่น" → "แผน" · "ชุด" → "ชุด")
# ของจริง: "แผ่นฟิล์มกระจกปกป้องหน้าจอ" ต้องอ่านออกว่าเป็นฟิล์ม
_TYPE_PREFIXES = ("แผน", "ชุด", "ตว", "อุปกรณ", "กระจก", "ท", "เครอง", "ราง")

# ตัวอักษรกับตัวเลขที่ตัวอ่านภาพสลับกันประจำ — ใช้จับ ``x3oo`` ที่จริงคือ ``x300``
_LOOKALIKE = str.maketrans({"o": "0", "O": "0", "l": "1", "i": "1", "I": "1",
                            "s": "5", "S": "5", "b": "8", "B": "8",
                            "g": "9", "q": "9", "z": "2"})


@dataclass
class Verdict:
    """ผลตรวจหนึ่งด่าน — **ok=None คือยังไม่รู้ผล ไม่ใช่ผ่าน**

    ``ok`` | ความหมาย
    ------ | ---------
    True   | ตรวจแล้วผ่าน
    False  | ตรวจแล้ว **ไม่ผ่าน** — ต้องหยุดและพักใบงาน
    None   | **ตรวจไม่ได้** (ข้อมูลไม่พอ/อ่านไม่ออก) — ก็ต้องหยุดเหมือนกัน
             แต่เป็นคนละเรื่อง และต้องบอกเจ้าของคนละแบบ
    """

    ok: bool | None
    why: str = ""
    problems: list[str] = field(default_factory=list)
    detail: dict = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        """ผ่านจริงเท่านั้น — ``None`` ไม่ใช่ผ่าน (กติกา 2.3.1 ข้อ 4)"""
        return self.ok is True

    def as_dict(self) -> dict:
        return {"ok": self.ok, "why": self.why, "problems": list(self.problems),
                **({"detail": self.detail} if self.detail else {})}


# ---------------------------------------------------------------------------
# เครื่องมือพื้นฐาน
# ---------------------------------------------------------------------------

def normalize(text: str) -> str:
    """ข้อความสำหรับเทียบคำ — ตัดวรรณยุกต์/สระบนล่างที่ตัวอ่านภาพทำตกประจำ

    ชื่อที่อ่านจากหน้า TikTok มาจากการอ่านภาพ ซึ่ง **วรรณยุกต์ตกเป็นปกติ**
    (วัดไว้ 11 ก.ย. 2569: "เพิ่ม" อ่านได้เป็น "เพิม") ถ้าเทียบตรงตัวจะไม่เจอ
    คำที่อยู่บนจอจริง แล้วด่านนี้จะกลายเป็นด่านที่ปฏิเสธทุกใบ
    """
    value = unicodedata.normalize("NFC", str(text or ""))
    value = value.replace("￼", " ").replace("ํา", "ำ")
    value = _THAI_MARKS_RE.sub("", value)
    return re.sub(r"\s+", " ", value).strip().casefold()


_FILLER_FLAT.update(normalize(word) for word in _FILLER)


def tokens(text: str) -> list[str]:
    return _TOKEN_RE.findall(normalize(text))


def is_code(token: str) -> bool:
    """คำนี้เป็นรหัสรุ่น/สเปกไหม (X300 · 65W · 4K60HZ)"""
    return bool(_CODE_RE.match(token))


def is_filler(token: str) -> bool:
    """คำเติมที่ไม่ได้บอกอะไร — เทียบกับรูปที่ตัดวรรณยุกต์แล้วเสมอ

    ``normalize`` ตัดวรรณยุกต์ทิ้ง "สำหรับ" จึงกลายเป็น "สาหรบ" ถ้าเอารายการ
    ที่เขียนเต็มไปเทียบตรง ๆ จะไม่ตรงสักคำ (พลาดมาแล้วตอนทดสอบ)
    """
    return normalize(token) in _FILLER_FLAT


def is_informative(token: str) -> bool:
    """คำนี้ช่วยบอกไหมว่าสินค้าคืออะไร — รหัสรุ่นกับคำเติมไม่ช่วย"""
    return not (is_code(token) or is_filler(token) or len(token) < 2
                or token.isdigit())


def _word_at(flat: str, word: str) -> int:
    """ตำแหน่งแรกที่คำนี้โผล่ — คำอังกฤษต้องเป็น **คำเต็ม** ไม่ใช่ส่วนของคำอื่น

    เจอจริงตอนทดสอบกับชื่อ 113 ใบ: ``iWatch`` ทำให้ระบบคิดว่าที่ชาร์จไร้สาย
    เป็น "นาฬิกา" และ ``Google TV`` แย่งคำว่า "ทีวี" ไปจากชื่อทีวีจริง
    ภาษาไทยเขียนติดกันไม่มีช่องว่าง จึงยังต้องเทียบแบบอยู่ข้างในคำได้
    """
    needle = normalize(word)
    if not needle:
        return -1
    if needle.isascii():
        found = re.search(r"(?<![a-z0-9])" + re.escape(needle) + r"(?![a-z0-9])", flat)
        return found.start() if found else -1
    # ภาษาไทยไม่เว้นวรรคระหว่างคำ แต่ **ต้องเริ่มที่ต้นคำ** ไม่ใช่โผล่กลางคำอื่น
    # วัดจากชื่อจริง: "แม่เหล็กไร้สายชาร์จเร็ว" มีตัวอักษร "สายชาร์จ" อยู่ข้างใน
    # ทำให้พาวเวอร์แบงค์ถูกนับเป็นสายชาร์จ — หายไปเมื่อบังคับว่าตัวหน้าต้องไม่ใช่
    # พยัญชนะไทย ยกเว้นคำขยายที่วางไว้หน้าชนิดสินค้าเป็นปกติ ("แผ่นฟิล์ม")
    for found in re.finditer(re.escape(needle), flat):
        before = flat[:found.start()]
        if not before or before[-1] not in "กขฃคฅฆงจฉชซฌญฎฏฐฑฒณดตถทธนบปผฝพฟภมยรลวศษสหฬอฮ":
            return found.start()
        if before.endswith(_TYPE_PREFIXES):
            return found.start()
    return -1


def types_in(text: str) -> set[str]:
    """ชนิดสินค้าทั้งหมดที่คำในข้อความนี้บอกได้"""
    flat = normalize(text)
    return {kind for kind, words in TYPE_WORDS.items()
            if any(_word_at(flat, word) >= 0 for word in words)}


def main_type(text: str) -> str:
    """ชนิดสินค้าหลัก — คำบอกชนิด **คำแรก** ที่โผล่ในชื่อ

    ชื่อ Shopee ขึ้นต้นด้วยรายการเครื่องที่ใส่ได้เสมอ
    (*"สำหรับ iPhone 17 ... เคส"*) ซึ่งในรายการนั้น **ไม่มีคำบอกชนิดสินค้าเลย**
    คำบอกชนิดคำแรกที่เจอจึงเป็นตัวสินค้าจริงทุกครั้ง

    ทดสอบกับชื่อจริง 113 ใบแล้ว: เอาคำท้ายสุดจะได้ *"กล่องเก็บอุปกรณ์หูฟัง"*
    เป็น "หูฟัง" และ *"เคสโทรศัพท์ MagSafe ... ขาตั้งกล้อง"* เป็น "ขาตั้ง"
    """
    flat = normalize(text)
    best, best_at, best_len = "", len(flat) + 1, 0
    for kind, words in TYPE_WORDS.items():
        for word in words:
            at = _word_at(flat, word)
            if at < 0:
                continue
            if at < best_at or (at == best_at and len(word) > best_len):
                best, best_at, best_len = kind, at, len(word)
    return best


def _brandish(all_tokens: list[str]) -> str:
    """คำที่น่าจะเป็นยี่ห้อ/ชื่อเครื่อง — ตัวอักษรล้วน ยาวพอ ไม่ใช่คำเติม"""
    for token in all_tokens:
        if (token.isascii() and token.isalpha() and len(token) >= 3
                and not is_filler(token) and not types_in(token)):
            return token
    return ""


# ---------------------------------------------------------------------------
# ข้อ 2 — คำค้นต้องมีคำบอกชนิดสินค้า ไม่ใช่รหัสรุ่นล้วน
# ---------------------------------------------------------------------------

# ⚠️ ต้องเทียบกับข้อความที่ผ่าน ``normalize`` แล้วเท่านั้น เพราะ ``normalize``
# ตัดวรรณยุกต์/สระบนล่างทิ้ง คำว่า "สำหรับ" จึงกลายเป็น "สาหรบ" — เขียนคำเต็ม
# ไว้ในรูปแบบแล้วเทียบกับข้อความที่ถูกตัดมาร์กแล้ว จะไม่มีวันเจอสักครั้ง
# (พลาดมาแล้วตอนทดสอบรอบแรก: ตัวย่อคำค้นไม่ทำงานเลยสักใบใน 113 ใบ)
_COMPAT_MARKS = ("สำหรับ", "เหมาะสำหรับ", "for", "compatible")


def _looks_like_compat_list(text: str) -> bool:
    flat = normalize(text)
    return any(_word_at(flat, mark) >= 0 for mark in _COMPAT_MARKS)


def query_check(query: str) -> Verdict:
    """คำค้นนี้บอกไหมว่ากำลังหา "อะไร" — ไม่ใช่แค่ "รุ่นอะไร" """
    if not str(query or "").strip():
        return Verdict(None, "ยังไม่มีคำค้นให้ตรวจ")
    kinds = types_in(query)
    if kinds:
        return Verdict(True, f"คำค้นบอกชนิดสินค้าแล้ว: {'/'.join(sorted(kinds))}")
    every = tokens(query)
    codes = [token for token in every if is_code(token) or token.isdigit()]
    share = len(codes) / len(every) if every else 0
    return Verdict(
        False,
        "คำค้นไม่มีคำบอกชนิดสินค้าเลย (เช่น เคส · สายชาร์จ · หูฟัง) "
        f"— เป็นรหัสรุ่น/ตัวเลข {len(codes)} จาก {len(every)} คำ "
        f"({share * 100:.0f}%) ค้นแบบนี้ TikTok จะคืนสินค้าอะไรก็ได้ที่รุ่นตรง",
        ["no_type_word"],
        {"code_share": round(share, 2)},
    )


def improve_query(query: str, full_name: str) -> tuple[str, str]:
    """เติม/ย่อคำค้นให้บอกชนิดสินค้าเสมอ คืน ``(คำค้นใหม่, สิ่งที่ทำไป)``

    สองอาการที่เจอจริงและแก้คนละทาง

    1. **ไม่มีคำบอกชนิดเลย** → เอาชนิดที่อ่านได้จากชื่อเต็มมาใส่หน้าคำค้น
    2. **มีคำบอกชนิด แต่จมอยู่ในรายการรุ่นที่ใส่ได้ยาวเป็นพืด**
       (``สำหรับ Vivo X300 X300 pro X200 ultra ... V70 เคสdiandu``)
       → ย่อเหลือ ``เคส Vivo X300`` เพราะรายการยาวแบบนั้นคือ "รุ่นที่ใส่ได้"
       ไม่ใช่ตัวสินค้า และทำให้ TikTok คืนอะไรก็ได้ที่มีรุ่นตรงสักตัว
    """
    query = re.sub(r"\s+", " ", str(query or "")).strip()
    name = str(full_name or "")
    kind = main_type(query) or main_type(name)
    if not kind:
        return query, ""

    every = tokens(query)
    codes = [token for token in every if is_code(token)]
    # "ชื่อที่เป็นรายการรุ่นที่ใส่ได้" หน้าตาแบบนี้: รหัสรุ่นเป็นพืด แล้วมีคำที่
    # บอกอะไรจริง ๆ อยู่แค่สองคำ (ยี่ห้อเครื่อง + ชนิดสินค้า) เช่น
    # ``สำหรับ Vivo X300 X300 pro ... V70 เคสdiandu``
    #
    # **ห้ามย่อชื่อที่บรรยายสินค้าจริง** — วัดกับชื่อจริง 113 ใบแล้ว ถ้าย่อ
    # ทุกใบที่มีรหัสรุ่นเยอะ ชื่อ UGREEN ที่เคยค้นเจอถูกตัวจะถูกย่อจนเสียของ
    # (``Ugreen ฮับ USB C 10Gbps 4K60Hz 9 in 1 ...`` → ``ฮับ ugreen 10Gbps``)
    meaty = [token for token in every if is_informative(token)]
    crowded = len(codes) >= 4 and len(meaty) <= 2
    if crowded:
        word = _type_word_as_written(query) or _type_word_as_written(name) or kind
        brand = _brandish(every)
        first_code = next((token.upper() for token in every if is_code(token)), "")
        short = " ".join(part for part in (word, brand, first_code) if part)
        return short[:120], (
            f"คำค้นเดิมเป็นรายการรุ่นที่ใส่ได้ {len(codes)} รุ่น — "
            f"ย่อเหลือ “{short}” ให้บอกว่ากำลังหาอะไร")
    if types_in(query):
        return query, ""
    word = _type_word_as_written(name) or kind
    fixed = f"{word} {query}"[:140]
    return fixed, f"คำค้นเดิมไม่บอกชนิดสินค้า — เติม “{word}” นำหน้า"


def _type_word_as_written(text: str) -> str:
    """คำบอกชนิดตามที่เขียนไว้จริงในชื่อ (เอาไว้ใช้ค้นให้ตรงภาษาที่ TikTok ใช้)"""
    kind = main_type(text)
    if not kind:
        return ""
    flat = normalize(text)
    present = [word.strip() for word in TYPE_WORDS[kind]
               if _word_at(flat, word) >= 0]
    return max(present, key=len, default=kind)


# ---------------------------------------------------------------------------
# ข้อ 1 — ชื่อที่อ่านจากหน้า TikTok ไม่ใช่ชื่อสินค้า = ห้ามผูก
# ---------------------------------------------------------------------------

def title_check(title: str, worksheet_name: str = "") -> Verdict:
    """ชื่อที่อ่านได้จากหน้าสินค้า TikTok เป็น "ชื่อสินค้า" จริงไหม

    ตัวอย่างที่ต้องปฏิเสธ (ของจริง ใบ 52807075353 ที่ TikTok ตีธง)::

        x300 ultra x3oo pro x300 x3oo

    ผิดพร้อมกันสี่อย่าง: ไม่มีคำบอกชนิดสินค้า · มีแต่รหัสรุ่น · คำซ้ำ ·
    ``x3oo`` คือ ``x300`` ที่อ่านเพี้ยน
    """
    raw = re.sub(r"\s+", " ", str(title or "")).strip()
    if not raw:
        # **ยังไม่รู้ผล ไม่ใช่ไม่ผ่าน** — อ่านไม่ได้เลยเป็นคนละเรื่องกับอ่านได้
        # แล้วพบว่าไม่ใช่ชื่อสินค้า
        return Verdict(None, "ยังอ่านชื่อสินค้าจากหน้า TikTok ไม่ได้")

    flat = normalize(raw)
    every = tokens(raw)
    problems: list[str] = []
    notes: list[str] = []

    if len(flat) < 12 or len([t for t in every if is_informative(t)]) < 2:
        problems.append("too_short")
        notes.append(f"สั้นเกินกว่าจะเป็นชื่อสินค้า (อ่านได้ {len(flat)} ตัวอักษร)")

    kinds = types_in(raw)
    if not kinds:
        problems.append("no_type_word")
        notes.append("ไม่มีคำบอกว่าเป็นสินค้าอะไร (เช่น เคส · สายชาร์จ · ทีวี)")

    codes = [token for token in every if is_code(token) or token.isdigit()]
    dull = [token for token in every if not is_informative(token)]
    if every and len(dull) / len(every) >= .85:
        problems.append("codes_only")
        notes.append(f"มีแต่รหัสรุ่นกับคำเติม ({len(dull)} จาก {len(every)} คำ)")

    repeated = {token for token in every if every.count(token) > 1}
    if repeated and len(set(every)) / len(every) < .8:
        problems.append("repeated")
        notes.append("คำซ้ำกันเอง: " + " ".join(sorted(repeated))[:60])

    garbled = _garbled_tokens(every, worksheet_name)
    if garbled:
        problems.append("garbled")
        notes.append("อ่านเพี้ยน: " + ", ".join(f"“{bad}” น่าจะเป็น “{good}”"
                                                for bad, good in garbled[:3]))

    # ---- ชื่อที่ถูกตัดท้าย = **อ่านไม่ครบ ไม่ใช่ชื่อปลอม** (กติกา 2.3.1) -----
    #
    # ของจริงใบ 41625762598 อ่านได้ ``...MagFlow Wireless 25W Cha ...`` ซึ่ง
    # คำว่า Charger ถูกตัดหายไปพอดี ถ้าตัดสินว่า "ไม่ผ่าน" จะเป็นการกล่าวหา
    # ทั้งที่จริง ๆ คือ **เรายังอ่านไม่ครบ** — ต้องแยกให้ออก ทั้งสองอย่างหยุด
    # ใบงานเหมือนกัน แต่เจ้าของต้องเห็นเหตุผลคนละแบบ
    if problems == ["no_type_word"] and raw.rstrip().endswith(("...", "…")) \
            and len(flat) >= 30:
        return Verdict(
            None,
            f"อ่านชื่อจากหน้า TikTok ได้ไม่ครบ ถูกตัดท้ายไว้ (“{raw[:70]}”) "
            "— ยังยืนยันไม่ได้ว่าเป็นสินค้าชนิดไหน",
            ["title_truncated"],
            {"title": raw[:200]},
        )

    if problems:
        return Verdict(
            False,
            f"ชื่อที่อ่านจากหน้า TikTok ใช้ไม่ได้ (“{raw[:70]}”) — "
            + " · ".join(notes),
            problems,
            {"title": raw[:200], "codes": len(codes), "tokens": len(every)},
        )
    return Verdict(True, f"ชื่อสินค้าอ่านได้ครบ: {raw[:80]}",
                   detail={"types": sorted(kinds)})


def _garbled_tokens(every: list[str], worksheet_name: str) -> list[tuple[str, str]]:
    """คำที่ตัวอ่านภาพอ่านเพี้ยน — จับจากของจริงสองแบบที่เจอ

    * ``x3oo`` คู่กับ ``x300`` ในชื่อเดียวกัน (ตัวเลขศูนย์กลายเป็นตัว o)
    * ``ugreem`` ทั้งที่ใบงานเขียน ``ugreen`` (ยี่ห้อพิมพ์ผิดหนึ่งตัว)
    """
    found: list[tuple[str, str]] = []
    folded: dict[str, str] = {}
    for token in every:
        key = token.translate(_LOOKALIKE)
        twin = folded.get(key)
        if twin and twin != token:
            pair = (token, twin) if token != key else (twin, token)
            if pair not in found:
                found.append(pair)
        else:
            folded.setdefault(key, token)

    brands = [token for token in tokens(worksheet_name)
              if token.isascii() and token.isalpha() and len(token) >= 5]
    for token in every:
        if not (token.isascii() and token.isalpha() and len(token) >= 5):
            continue
        for brand in brands:
            if token != brand and _one_letter_off(token, brand):
                if (token, brand) not in found:
                    found.append((token, brand))
                break
    return found


def _one_letter_off(left: str, right: str) -> bool:
    """ต่างกันแค่ตัวเดียวในตำแหน่งเดียวกันไหม (ไม่นับสลับความยาว)"""
    if len(left) != len(right):
        return False
    return sum(1 for a, b in zip(left, right) if a != b) == 1


# ---------------------------------------------------------------------------
# ข้อ 3 — ห้ามตัดสินว่าตรงจากหน้าตาอย่างเดียว
# ---------------------------------------------------------------------------

# คำที่บอกว่า AI ตัดสินจาก "รูปเหมือนกัน" ล้วน ๆ — เก็บจากเหตุผลจริงที่ AI
# เขียนไว้ในใบที่โดนตีธง: *"similar glittery finish and Hello Kitty design"*
_LOOKS_ONLY = (
    "similar", "looks like", "look the same", "same design", "same pattern",
    "same style", "appearance", "visually", "identical design", "glittery",
    "decorative", "color", "colour", "shape", "คล้าย", "หน้าตา", "ลักษณะ",
    "ลวดลาย", "ลาย", "ดีไซน์", "รูปทรง", "สีเดียวกัน", "เหมือนกันในรูป",
)
# คำที่บอกว่ามีหลักฐานจาก "ตัวหนังสือ" จริง — ชื่อ/รุ่น/รายละเอียด
_TEXT_EVIDENCE = (
    "model code", "model number", "title", "listing name", "name matches",
    "same model", "รหัสรุ่น", "ชื่อประกาศ", "ชื่อสินค้า", "ชื่อรุ่น", "รุ่น",
    "รายละเอียด", "สเปก",
)


def evidence_check(vision: dict, worksheet_name: str) -> Verdict:
    """AI ตอบว่า "ตรง" โดยมีหลักฐานจากตัวหนังสือด้วยไหม หรือดูแต่รูป

    **เจ้าของสั่ง 14 ก.ย. 2569** — ถ้ามีแต่ความเหมือนของรูป ให้ตอบว่า
    *"ตัดสินไม่ได้"* ไม่ใช่ *"ตรง"*

    ตรวจสามชั้นจากของที่บันทึกไว้จริงในใบงาน

    1. ช่อง ``evidence`` ที่ขอจากโมเดลตรง ๆ (``model_code`` / ``title_text``
       / ``image_only``) — ``image_only`` = ไม่ผ่านทันที
    2. เหตุผลที่โมเดลเขียน ถ้าพูดถึงแต่หน้าตา/ลาย/สี และไม่พูดถึงชื่อหรือรุ่นเลย
       = ตัดสินจากรูปล้วน
    3. **ชนิดสินค้าของประกาศที่เลือก ต้องเป็นชนิดเดียวกับใบงาน** — ใบที่โดน
       ตีธงเลือกอันดับ 1 ที่ชื่อว่า *"Lereach Anti-Spy HD Glass"* ซึ่งเป็น
       ฟิล์ม ทั้งที่ใบงานเป็นเคส
    """
    vision = vision or {}
    try:
        rank = int(vision.get("match") or 0)
    except (TypeError, ValueError):
        rank = 0
    if rank not in (1, 2, 3, 4):
        return Verdict(None, "ยังไม่มีอันดับที่เลือก จึงยังไม่ต้องตรวจหลักฐาน")

    reason = str(vision.get("reason") or "")
    flat = reason.casefold()
    titles = [str(value) for value in (vision.get("titles") or [])]
    chosen = titles[rank - 1] if len(titles) >= rank else ""
    stated = str(vision.get("evidence") or "").strip().lower()

    problems: list[str] = []
    notes: list[str] = []

    if stated == "image_only":
        problems.append("image_only")
        notes.append("โมเดลบอกเองว่าดูจากรูปอย่างเดียว")

    looks = [word for word in _LOOKS_ONLY if word in flat]
    texty = [word for word in _TEXT_EVIDENCE if word in flat]
    if looks and not texty:
        problems.append("looks_only_reason")
        notes.append("เหตุผลพูดถึงแต่หน้าตา/ลาย/สี ไม่ได้อ้างชื่อหรือรุ่นเลย "
                     f"(“{reason[:90]}”)")

    if chosen.strip():
        clash = type_clash(worksheet_name, chosen)
        if clash:
            problems.append("type_mismatch")
            notes.append(f"ใบงานเป็น “{clash[0]}” แต่ประกาศอันดับ {rank} "
                         f"เป็น “{clash[1]}” — คนละชนิดสินค้ากันคนละเรื่อง")

    if problems:
        return Verdict(False,
                       "ตัดสินไม่ได้ว่าเป็นสินค้าตัวเดียวกัน — " + " · ".join(notes),
                       problems, {"rank": rank, "listing": chosen[:160]})

    if not chosen.strip():
        # **ยังไม่มีหลักฐาน ไม่ใช่มีหลักฐานว่าไม่ตรง** (กติกา 2.3.1)
        # อ่านชื่อประกาศบนหน้าผลค้นหาไม่ได้เป็นเรื่องปกติ เพราะการ์ดบนจอตัดชื่อ
        # ทิ้งตั้งแต่ครึ่งทาง ยังพิสูจน์ต่อได้ที่ **หน้าสินค้าจริง** หลังกดเข้าไป
        # ซึ่งชื่อเต็มกว่ามาก — ผู้เรียกต้องบังคับให้ผ่านด่านชื่อที่นั่นแทน
        return Verdict(None,
                       f"อ่านชื่อประกาศอันดับ {rank} จากหน้าผลค้นหาไม่ได้ "
                       "— ต้องไปพิสูจน์ด้วยชื่อเต็มบนหน้าสินค้าจริงแทน",
                       ["no_listing_title"], {"rank": rank})
    return Verdict(True, "มีหลักฐานจากชื่อ/รายละเอียด ไม่ได้ดูแต่รูป",
                   detail={"rank": rank, "listing": chosen[:160]})


# ---------------------------------------------------------------------------
# ชนิดสินค้าที่ "เรียกคนละชื่อแต่เป็นของกลุ่มเดียวกัน" กับที่ "คนละเรื่องกันจริง"
# ---------------------------------------------------------------------------
#
# ห้ามเทียบชนิดแบบตรงตัว — วัดกับใบจริงแล้วพบว่าจะฟ้องผิดทันที
#   ใบ 9983149742 ชื่อ "อะแดปเตอร์ฮับ USB" ประกาศเขียน "Docking Station"
#   ใบ 47350858748 ชื่อ "...สายเคเบิลในตัว Power Bank" ประกาศเขียน "Power Bank"
# สองใบนี้ตรงตัวจริง ๆ แค่เรียกคนละชื่อ ส่วนที่ต้องจับให้ได้คือ
#   ใบ 52807075353 ใบงานเป็น **เคส** แต่ประกาศเป็น **ฟิล์มกันรอย**
_FAMILY = {
    "อะแดปเตอร์": "ต่อพ่วง", "ฮับ/แท่นวาง": "ต่อพ่วง",
    "ที่ชาร์จ": "ชาร์จไฟ", "สายชาร์จ": "ชาร์จไฟ",
    "พาวเวอร์แบงค์": "ชาร์จไฟ", "ปลั๊ก/ซ็อกเก็ต": "ชาร์จไฟ",
    "ทีวี": "จอภาพ", "จอคอม": "จอภาพ",
    "โซฟา": "เฟอร์นิเจอร์นั่ง", "เก้าอี้": "เฟอร์นิเจอร์นั่ง",
}


def family(kind: str) -> str:
    return _FAMILY.get(kind, kind)


def type_clash(worksheet_name: str, listing: str) -> tuple[str, str] | None:
    """ใบงานกับประกาศเป็นสินค้าคนละเรื่องกันไหม — คืน ``(ของใบงาน, ของประกาศ)``"""
    want = main_type(worksheet_name)
    got = types_in(listing)
    if not want or not got:
        return None
    if family(want) in {family(kind) for kind in got}:
        return None
    return want, "/".join(sorted(got))


def name_agreement(product_title: str, worksheet_name: str) -> Verdict:
    """ชื่อเต็มบนหน้าสินค้า TikTok กับชื่อในใบงาน พูดถึงของชิ้นเดียวกันไหม

    นี่คือ **หลักฐานทางตัวหนังสือ** ที่เจ้าของสั่งให้ต้องมี (ข้อ 3) ตอนที่
    ชื่อประกาศบนหน้าผลค้นหาอ่านไม่ได้ ต้องมีคำที่ไม่ใช่รหัสรุ่นตรงกันอย่างน้อย
    หนึ่งคำ — **รหัสรุ่นอย่างเดียวไม่นับ** เพราะใบที่โดนตีธงก็มี ``X300`` ตรงกัน
    ทั้งที่เป็นฟิล์มของอีกร้าน
    """
    if not str(product_title or "").strip():
        return Verdict(None, "ยังไม่มีชื่อจากหน้าสินค้าให้เทียบ")
    if not str(worksheet_name or "").strip():
        return Verdict(None, "ใบงานไม่มีชื่อสินค้าให้เทียบ")

    clash = type_clash(worksheet_name, product_title)
    if clash:
        return Verdict(False,
                       f"หน้าสินค้าที่เปิดเป็น “{clash[1]}” แต่ใบงานเป็น "
                       f"“{clash[0]}” — คนละชนิดสินค้า",
                       ["type_mismatch"])

    mine = {token for token in tokens(worksheet_name) if is_informative(token)}
    theirs = {token for token in tokens(product_title) if is_informative(token)}
    shared = mine & theirs
    if not shared:
        return Verdict(
            False,
            "ชื่อบนหน้าสินค้า TikTok ไม่มีคำไหนตรงกับใบงานเลย นอกจากรหัสรุ่น "
            f"— ใบงาน “{str(worksheet_name)[:50]}” · หน้าสินค้า "
            f"“{str(product_title)[:50]}”",
            ["no_shared_word"],
        )
    return Verdict(True, "ชื่อตรงกับใบงาน: " + " ".join(sorted(shared))[:80],
                   detail={"shared": sorted(shared)[:10]})


# ---------------------------------------------------------------------------
# ข้อ 4 — ของทั่วไปที่หน้าตาซ้ำกันทั้งตลาด ต้องให้เจ้าของยืนยันเสมอ
# ---------------------------------------------------------------------------

# ชนิดที่ "ใครก็ขายได้ หน้าตาเหมือนกันหมด" — รูปเหมือนกันไม่ได้แปลว่าตัวเดียวกัน
LOOKALIKE_TYPES = {"เคสมือถือ", "ฟิล์มกันจอ", "สายชาร์จ", "ขาตั้ง",
                   "กระเป๋า", "กล่องเก็บของ"}

# ยี่ห้อที่เขียนชื่อตัวเองไว้บนสินค้า/กล่อง ทำให้แยกออกจากของโนเนมได้
_KNOWN_BRANDS = {"ugreen", "anker", "baseus", "apple", "samsung", "tcl",
                 "xiaomi", "huawei", "belkin", "spigen", "nillkin", "esr",
                 "index", "patara", "perfect", "woodpanda", "dobee",
                 "solomon", "trikings", "d-link", "tp-link"}


def generic_lookalike(worksheet_name: str) -> Verdict:
    """สินค้านี้เป็นของทั่วไปที่หน้าตาซ้ำกันทั้งตลาดไหม

    ``ok=True`` แปลว่า **ใช่ — ต้องให้เจ้าของยืนยันเสมอ ห้ามผ่านอัตโนมัติ**
    (ตั้งใจให้ ``True`` แปลว่า "เข้าข่าย" ไม่ใช่ "ผ่าน" เพราะฟังก์ชันนี้ตอบ
    คำถามว่า "เข้าข่ายไหม" ไม่ใช่ "ผ่านไหม")
    """
    name = str(worksheet_name or "")
    if not name.strip():
        return Verdict(None, "ไม่มีชื่อสินค้าให้ดู")
    kind = main_type(name)
    if kind not in LOOKALIKE_TYPES:
        return Verdict(False, "ไม่ใช่ของทั่วไปที่หน้าตาซ้ำกันทั้งตลาด",
                       detail={"type": kind})
    brands = {token for token in tokens(name)} & _KNOWN_BRANDS
    if brands:
        return Verdict(False,
                       f"เป็น “{kind}” แต่มียี่ห้อกำกับ ({'/'.join(sorted(brands))})",
                       detail={"type": kind, "brands": sorted(brands)})
    return Verdict(True,
                   f"เป็น “{kind}” ที่ไม่มียี่ห้อกำกับ — ของแบบนี้มีคนขาย"
                   "เป็นร้อยเจ้า หน้าตาเหมือนกันหมด ต้องให้เจ้าของยืนยันก่อน",
                   ["generic_lookalike"], {"type": kind})


# ---------------------------------------------------------------------------
# ตรวจใบเก่าย้อนหลัง
# ---------------------------------------------------------------------------

def audit_run(run: dict) -> dict:
    """ใบงานที่ผูกไว้แล้วใบนี้ ผ่านกติกาใหม่ไหม — ใช้ไล่ตรวจของเก่า"""
    run = run or {}
    link = run.get("tiktok_product_link") or {}
    name = str(run.get("name") or "")
    title = str(link.get("tiktok_product_name") or "")
    vision = {"match": link.get("selected_rank") or link.get("matched_rank") or 0,
              "reason": link.get("reason") or "",
              "titles": link.get("result_titles") or link.get("titles") or [],
              "evidence": link.get("evidence") or ""}
    checks = {
        "query": query_check(str(link.get("search_query") or "")),
        "title": title_check(title, name),
        "evidence": evidence_check(vision, name),
        "generic": generic_lookalike(name),
    }
    blocking = [key for key in ("query", "title", "evidence")
                if checks[key].ok is False]
    unknown = [key for key in ("query", "title", "evidence")
               if checks[key].ok is None]
    needs_owner = checks["generic"].ok is True
    return {
        "item_id": str(run.get("item_id") or ""),
        "name": name,
        "status": str(link.get("status") or ""),
        "tiktok_product_name": title,
        "search_query": str(link.get("search_query") or ""),
        "fails": blocking,
        "unknown": unknown,
        "needs_owner_confirm": needs_owner,
        "checks": {key: value.as_dict() for key, value in checks.items()},
    }
