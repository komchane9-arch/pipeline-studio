"""บอทโพสต์ TikTok Shop ที่เทรนจาก REDMI 15C ของจริงเมื่อ 3 ก.ย. 2026.

ผังนี้แยกจากผังแก้ไขทั่วไป เพราะมีด่านที่ห้ามข้าม: สินค้าต้องตรง, คลิปต้องเป็น
ใบล่าสุด, ผู้ชมต้องเป็นทุกคน และปุ่มโพสต์แตะได้เพียงครั้งเดียว.
"""

from __future__ import annotations

import html
import io
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np
from PIL import Image

import publish_flow
import publish_media
import tiktok_product_link


SUPPORTED_SERIAL = "W4FYYPYTLFYLIFHM"
TIKTOK_PACKAGE = "com.ss.android.ugc.trill"
CHROME_PACKAGE = "com.android.chrome"
ANCHOR_NAME = "กดซื้อเลย"
ACCOUNT_HANDLE = "@artaiitgadget"
BASE_SCREEN = (720, 1600)
TOTAL_STEPS = 14
SUCCESS_REFERENCE = Path(__file__).resolve().parent / "data/evidence/train-tiktok-after-post.png"


class TikTokPublishError(RuntimeError):
    pass


@dataclass(frozen=True)
class Target:
    label: str
    needles: tuple[str, ...] = ()
    fallback: tuple[int, int, int, int] | None = None


def supports(serial: str) -> bool:
    return str(serial or "").strip() == SUPPORTED_SERIAL


def is_tiktok_foreground(value: str) -> bool:
    """foreground() คืน package/Activity; เทียบเฉพาะ package ฝั่งซ้าย."""
    return str(value or "").split("/", 1)[0] == TIKTOK_PACKAGE


# ชิปกรองบนแท็บร้านค้า — **เทียบแบบไม่สนตัวพิมพ์ใหญ่เล็ก**
# ตัวอ่านภาพคืนตัวพิมพ์เล็กเสมอ ("MALL" บนจอ -> "mall") ของเดิมเทียบตรงตัว
# จึงไม่เจอสักชิป ทั้งที่หน้าจอถูกต้องทุกประการ (เจอจริง 11 ก.ย. 16:48
# ใบงาน 29708428217 — ภาพตอนล้มเห็นสินค้าขึ้นครบ 4 ใบพร้อมราคา)
SHOP_CHIPS = ("MALL", "LIVE", "TopChoice", "จัดส่งวันเดียวกัน")
# แถวเรียงลำดับ **มีเฉพาะแท็บร้านค้า** แท็บ "ดีที่สุด" ไม่มี และตัวอ่านภาพ
# อ่านสามคำนี้ออกครบทุกคำ จึงใช้เป็นหลักฐานสำรองเมื่อชิปอ่านไม่ออก
SHOP_SORTS = ("ตรงกันมากที่สุด", "สินค้าขายดี", "มีคะแนนสูงสุด")
# ราคาที่ตัวอ่านภาพคืนมาจริง: "B173.00" · "邮193.85" · "฿217.50" — สัญลักษณ์บาท
# ถูกอ่านเพี้ยนไปหลายแบบ จึงรับทุกแบบ และยอมรับกรณีไม่มีสัญลักษณ์นำหน้าด้วย
PRICE_RE = re.compile(r"(?:฿|B|邮)?\s?\d[\d,]*\.\d{2}")


def shop_results_visible(xml: str) -> bool:
    """ผลร้านค้าโหลดแล้ว แม้การ์ดสินค้าแบบ canvas จะไม่ส่งชื่อ/ราคา.

    **ห้ามใช้คำว่า "ร้านค้า" เป็นด่านแรก** (แก้ 11 ก.ย. 2569) — ของเดิมขึ้นต้นด้วย
    ``if "ร้านค้า" not in plain: return False`` ซึ่งทำให้ฟังก์ชันนี้ตอบ False
    ตลอดกาลบนเครื่องจริง เพราะ **ชื่อแท็บอ่านไม่ได้เลยทั้งสองทาง**

        ผังจากระบบ  หน้านี้มีนาฬิกานับถอยหลังเดินตลอด ตัวอ่านจึงตอบ
                    "ERROR: could not get idle state." ทุกครั้ง
        OCR สำรอง   อ่านภาษาไทยไม่ออก — "ร้านค้า" ออกมาเป็น "Suusefu"
                    (วัดจริง: อ่านได้ 50 คำ เป็นอังกฤษกับตัวเลขล้วน)

    ผลคือขั้นเปิดหน้าสินค้าล้มทุกใบ ทั้งที่ภาพหน้าจอเห็นสินค้าขึ้นครบสี่ใบ

    **เกาะของที่อ่านได้จริงแทน** — แถบชิปกรอง (MALL · LIVE · จัดส่งวันเดียวกัน)
    ซึ่ง **มีเฉพาะในแท็บร้านค้า** แท็บ "ดีที่สุด" ไม่มี จึงแยกสองแท็บออกจากกันได้
    และต้องเห็นราคาอย่างน้อยสองใบคู่กัน = ตารางสินค้าโหลดเสร็จจริง
    ไม่ใช่โครงเปล่าที่ยังไม่มีของ
    """
    plain = html.unescape(xml or "")
    low = plain.casefold()
    marks = (any(chip.casefold() in low for chip in SHOP_CHIPS)
             or any(word in plain for word in SHOP_SORTS))
    if marks and len(PRICE_RE.findall(plain)) >= 2:
        return True
    if "ร้านค้า" not in plain:
        return False
    if "฿" in plain:
        return True
    # TikTok รุ่นปัจจุบันคืนการ์ดเป็น TextureView/ImageView ที่ไม่มี text แต่
    # กรอบ cover ของสินค้ากว้าง/สูงชัดเจนอยู่ใต้แถบค้นหา.
    canvas_cards: set[tuple[int, int, int, int]] = set()
    for raw in publish_flow.ELEMENT_RE.findall(plain):
        resource = publish_flow._attr(raw, "resource-id").split("/")[-1]
        clazz = publish_flow._attr(raw, "class")
        box = _bounds(raw)
        if not box:
            continue
        x1, y1, x2, y2 = box
        if (resource in {"cover", "yls", "fat", "mz9"}
                or clazz.endswith(("TextureView", "ImageView"))):
            if y1 >= 400 and x2 - x1 >= 220 and y2 - y1 >= 250:
                return True
        if (clazz.endswith("ViewGroup") and 430 <= y1 <= 850
                and x2 - x1 >= 260 and y2 - y1 >= 300):
            canvas_cards.add((x1, y1, x2, y2))
    # อีกรูปแบบซ่อนทั้งชื่อและ resource-id แต่คืนกรอบการ์ดสองคอลัมน์.
    # ต้องเห็นอย่างน้อยสองกรอบคนละตำแหน่ง จึงไม่เชื่อ skeleton ใบเดียว.
    if len(canvas_cards) >= 2:
        return True
    return False


def _bounds(raw: str) -> tuple[int, int, int, int] | None:
    match = re.search(r'bounds="\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]"', raw)
    return tuple(int(match.group(i)) for i in range(1, 5)) if match else None


# ---- ตัวอ่านหน้าจอย้ายไปเป็นของกลางแล้ว (11 ก.ย. 2569) -------------------
#
# เจ้าของสั่งยกขึ้นเป็น `screen_read.py` หลังวันเดียวเจอโรคเดียวกัน 8 ครั้ง
# ในสองไฟล์ ("ไม่พบ X" ทั้งที่จริงคืออ่านจอไม่ได้) — กติกาข้อ 2.3.1 เคยบังคับ
# ด้วยความจำอย่างเดียวจึงเกิดซ้ำเรื่อยมา ตอนนี้มีที่เดียวให้แก้
#
# ชื่อเดิมยังใช้ได้ทั้งหมด ของเก่าที่เรียกอยู่จึงไม่ต้องแก้ตาม
import screen_read

THAI_MARKS_RE = screen_read.THAI_MARKS_RE
SYSTEM_DIALOG_PACKAGES = screen_read.SYSTEM_DIALOG_PACKAGES
thai_loose = screen_read.thai_loose
get_thai_ocr = screen_read.get_thai_ocr
blocking_system_dialog = screen_read.blocking_system_dialog


def from_ocr(xml: str) -> bool:
    """ผังก้อนนี้มาจากการอ่านภาพหรือไม่ (ไม่ใช่ผังจริงจากระบบ)"""
    return 'source="ocr"' in (xml or "")


def find_bounds(xml: str, needles: tuple[str, ...]) -> tuple[int, int, int, int] | None:
    """คืนกรอบ element ที่กดได้ก่อน แล้วจึงถอยไปใช้กรอบป้ายข้อความ."""
    lowered = tuple(value.casefold() for value in needles if value)
    rows = []
    for raw in publish_flow.ELEMENT_RE.findall(html.unescape(xml or "")):
        values = (publish_flow._attr(raw, "resource-id").split("/")[-1].strip().casefold(),
                  publish_flow._attr(raw, "content-desc").strip().strip(",").casefold(),
                  publish_flow._attr(raw, "text").strip().casefold())
        box = _bounds(raw)
        if box:
            rows.append((raw, values, box))
    # exact ก่อนเสมอ: คำว่า "โพสต์" เป็นส่วนหนึ่งของแถวตั้งค่าผู้ชมด้วย และ
    # "โปรไฟล์" เป็นส่วนหนึ่งของปุ่มยอดดูโปรไฟล์ ถ้าใช้ contains ก่อนจะกดผิด.
    for want_clickable, exact in ((True, True), (True, False),
                                  (False, True), (False, False)):
        for raw, values, box in rows:
            matched = (any(needle == value for needle in lowered for value in values)
                       if exact else
                       any(needle in value for needle in lowered for value in values))
            if not matched:
                continue
            if (publish_flow._attr(raw, "clickable") == "true") == want_clickable:
                return box
    # ---- รอบสุดท้าย: ยอมให้วรรณยุกต์ตก **เฉพาะผังที่มาจากการอ่านภาพ** -------
    #
    # ตัวอ่านภาพทำไม้เอกตกจริง ("เพิ่ม" → "เพิม") ถ้าหาไม่เจอก็กดปุ่มไม่ได้
    # ทั้งที่เห็นปุ่มอยู่บนจอ (วัด 11 ก.ย. 2569 บนกล่อง "เพิ่มสินค้าหรือไม่")
    #
    # **ผังจริงจากระบบไม่เข้าเงื่อนไขนี้** ตัวอักษรถูกต้องอยู่แล้ว จึงไม่มีทาง
    # เทียบหลวมแล้วไปกดโดนปุ่มอื่นที่สะกดใกล้กัน
    if not from_ocr(xml):
        return None
    loose = tuple(thai_loose(value) for value in needles if value)
    for want_clickable in (True, False):
        for raw, values, box in rows:
            if not any(needle and needle in thai_loose(value)
                       for needle in loose for value in values):
                continue
            if (publish_flow._attr(raw, "clickable") == "true") == want_clickable:
                return box
    return None


def find_clickable_bounds(xml: str, needles: tuple[str, ...]) -> tuple[int, int, int, int] | None:
    """คืนเฉพาะกรอบที่กดได้จริง; ใช้เมื่อข้อความเดียวกันอยู่ทั้งช่องและคำแนะนำ."""
    lowered = tuple(value.casefold() for value in needles if value)
    for raw in publish_flow.ELEMENT_RE.findall(html.unescape(xml or "")):
        if publish_flow._attr(raw, "clickable") != "true":
            continue
        values = (publish_flow._attr(raw, "resource-id").split("/")[-1].strip().casefold(),
                  publish_flow._attr(raw, "content-desc").strip().strip(",").casefold(),
                  publish_flow._attr(raw, "text").strip().casefold())
        if not any(needle == value for needle in lowered for value in values):
            continue
        box = _bounds(raw)
        if box:
            return box
    # TikTok บางรุ่นให้ TextView ลูกเป็น clickable=false แต่ LinearLayout แม่
    # เป็นแถวที่กดได้จริง. ไล่ ancestry เพื่อคืนกรอบแม่ที่ใกล้ที่สุด.
    try:
        root = ET.fromstring(xml or "")
    except ET.ParseError:
        return None
    found: tuple[int, int, int, int] | None = None

    def walk(node, ancestors) -> None:
        nonlocal found
        if found is not None:
            return
        values = (str(node.attrib.get("text") or "").strip().casefold(),
                  str(node.attrib.get("content-desc") or "").strip().casefold())
        if any(needle == value for needle in lowered for value in values):
            for candidate in reversed([*ancestors, node]):
                if candidate.attrib.get("clickable") != "true":
                    continue
                raw_bounds = candidate.attrib.get("bounds", "")
                match = re.search(r"\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]", raw_bounds)
                if match:
                    found = tuple(int(match.group(i)) for i in range(1, 5))
                    return
        for child in node:
            walk(child, [*ancestors, node])

    walk(root, [])
    return found


def _scaled(box: tuple[int, int, int, int], screen: tuple[int, int]) -> tuple[int, int, int, int]:
    sx, sy = screen[0] / BASE_SCREEN[0], screen[1] / BASE_SCREEN[1]
    return tuple(int(round(value * (sx if index % 2 == 0 else sy)))
                 for index, value in enumerate(box))


def _model_terms(name: str) -> list[str]:
    query = tiktok_product_link.build_search_query(name)
    terms = re.findall(r"[A-Za-z0-9]+(?:[-/][A-Za-z0-9]+)*", query.upper())
    brand = next((term for term in terms if term.isalpha() and len(term) >= 3), "")
    models = [term for term in terms
              if any(ch.isalpha() for ch in term) and any(ch.isdigit() for ch in term)
              and not tiktok_product_link._SPEC_CODE_RE.fullmatch(term)
              and not re.fullmatch(r"\d+(?:G|GHZ)", term)]
    return ([brand] if brand else []) + models[:3]


def showcase_prepared(run: dict) -> bool:
    """งานรูปแบบใหม่เพิ่มสินค้าไว้แล้ว จึงไม่ต้องมีหรือเปิด URL ก่อนโพสต์."""
    state = (run or {}).get("tiktok_product_link") or {}
    confidence = str(state.get("confidence") or "").lower()
    return bool(state.get("status") == "showcase_added"
                and state.get("showcase_added")
                and confidence in {"high", "human_confirmed"})


_PRODUCT_STOP_WORDS = {
    "สำหรับ", "พร้อม", "สินค้า", "รุ่น", "ขนาด", "ของ", "และ", "หรือ",
    "ส่ง", "จัดส่ง", "ใหม่", "แท้", "official", "shop", "store",
}


def _product_tokens(value: str) -> set[str]:
    """คำสำคัญสำหรับเทียบสินค้าที่บันทึกไว้กับหน้าที่เปิดจริง."""
    return {
        token.casefold() for token in re.findall(r"[A-Za-z0-9ก-๙]+", value or "")
        if len(token) >= 2 and token.casefold() not in _PRODUCT_STOP_WORDS
    }


def saved_product_matches(run: dict, xml: str) -> bool:
    """ยืนยันหน้าสินค้าจากชื่อ TikTok ที่คัดลอกไว้ ไม่เดาจากอันดับอย่างเดียว.

    ผลค้นหาอาจสลับอันดับได้ในภายหลัง จึงต้องเทียบชื่อที่เคยยืนยันกับข้อความบน
    หน้าสินค้าหลังแตะอีกครั้ง สำหรับชื่อสั้นรับอย่างน้อย 2 คำ ส่วนชื่อยาวต้อง
    ตรงอย่างน้อย 3 คำและไม่น้อยกว่า 35% ของคำสำคัญทั้งหมด.
    """
    state = (run or {}).get("tiktok_product_link") or {}
    expected = str(state.get("tiktok_product_name") or run.get("name") or "")
    wanted = _product_tokens(expected)
    visible = _product_tokens(html.unescape(xml or ""))
    if not wanted or not visible:
        return False
    common = wanted & visible
    minimum = min(3, len(wanted))
    return len(common) >= minimum and len(common) / len(wanted) >= .35


def product_detail_visible(xml: str) -> bool:
    """แยกหน้ารายละเอียดจริงออกจากวิดีโอที่เพียงมีการ์ดสินค้าตรงชื่อ."""
    plain = html.unescape(xml or "")
    return bool(
        ("ร้านค้า" in plain and "แชท" in plain and "ซื้อเลย" in plain)
        or "ข้อมูลโปรโมชั่น" in plain
        or "content-desc=\"เพิ่มขึ้น\"" in plain
        or "content-desc=\"ลดลง\"" in plain
    )


def truncated_product_title_bounds(run: dict, xml: str) -> tuple[int, int, int, int] | None:
    """กรอบเล็กท้ายชื่อย่อสำหรับขยายชื่อเต็ม โดยไม่แตะปุ่มซื้อ."""
    terms = _model_terms(str((run or {}).get("name") or ""))
    brand = terms[0].casefold() if terms else ""
    for raw in publish_flow.ELEMENT_RE.findall(html.unescape(xml or "")):
        text = publish_flow._attr(raw, "text").strip()
        box = _bounds(raw)
        if (not box or not brand or brand not in text.casefold()
                or ("..." not in text and "…" not in text)):
            continue
        x1, y1, x2, y2 = box
        if y1 < 800:
            continue
        return (max(x1, x2 - 72), y1, x2, y2)
    return None


def promotion_chooser_visible(image: Image.Image) -> bool:
    """ตรวจ bottom sheet เลือกวิดีโอสั้น/กล้อง เมื่อทั้งหน้าเป็น canvas."""
    rgb = image.convert("RGB")
    width, height = rgb.size
    if width < 100 or height < 300:
        return False

    def ratios(box: tuple[int, int, int, int]) -> tuple[float, float]:
        pixels = list(rgb.crop(box).get_flattened_data())
        if not pixels:
            return 0.0, 0.0
        white = sum(max(px) - min(px) < 18 and sum(px) / 3 > 232 for px in pixels)
        black = sum(sum(px) / 3 < 55 for px in pixels)
        return white / len(pixels), black / len(pixels)

    bottom_white, _ = ratios((0, int(height * .45), width, int(height * .98)))
    camera_white, camera_black = ratios((int(width * .07), int(height * .70),
                                          int(width * .30), int(height * .84)))
    return bottom_white >= .82 and camera_white >= .72 and camera_black >= .035


def fresh_post_visible(run: dict, xml: str) -> bool:
    """หลักฐานสำรองหลังโพสต์: ฟีดตนเอง + แท็กครบ + เวลาเป็นวินาที."""
    plain = html.unescape(xml or "")
    tags = [str(tag).strip().lstrip("#") for tag in (run or {}).get("hashtags") or []]
    return bool(tags
                and all("#" + tag in plain for tag in tags)
                and re.search(r"\b\d+\s*วินาที(?:ก่อน)?\b", plain)
                and ("อาไท รีวิว" in plain or ACCOUNT_HANDLE.lstrip("@") in plain))


class Bot:
    def __init__(self, context: publish_flow.RunContext, run: dict,
                 cleanup_media: Callable[[], str] | None = None,
                 stop_before_post: bool = False,
                 resume_current_product: bool = False,
                 resume_anchor_ready: bool = False,
                 resume_editor_ready: bool = False,
                 resume_audience_ready: bool = False,
                 resume_profile_ready: bool = False,
                 resume_step_id: str = "",
                 resume_step_no: int = 0):
        if not supports(context.serial):
            raise TikTokPublishError("บอท TikTok ชุดนี้เทรนไว้เฉพาะ REDMI 15C สายวิดีโอ")
        self.c = context
        self.run = run
        self.cleanup_media = cleanup_media
        self.stop_before_post = bool(stop_before_post)
        self.resume_current_product = bool(resume_current_product)
        self.resume_anchor_ready = bool(resume_anchor_ready)
        self.resume_editor_ready = bool(resume_editor_ready)
        self.resume_audience_ready = bool(resume_audience_ready)
        self.resume_profile_ready = bool(resume_profile_ready)
        self.resume_step_id = str(resume_step_id or "").strip()
        self.resume_step_no = max(0, int(resume_step_no or 0))
        self.results: list[dict] = []
        self.done = 0
        self.post_clicked = False
        # ยอดเล่นของคลิปในโปรไฟล์ ณ ตอนเริ่มงาน — ใช้เทียบว่ามีคลิปใหม่โผล่ไหม
        self.tiles_before: list[str] = []
        self.current_step_id = "preflight"
        self.current_step_name = "ตรวจข้อมูลใบงาน"

    def at(self, step_id: str, name: str) -> None:
        """จดขั้นที่กำลังแตะ เพื่อให้ exception ค้างอยู่ขั้นจริง ไม่ตกเป็น unknown."""
        self.current_step_id = step_id
        self.current_step_name = name

    def report(self, step_id: str, name: str, ok: bool, message: str) -> None:
        step = publish_flow.Step(id=step_id, name=name)
        self.results.append({"step": step_id, "name": name, "ok": ok, "message": message})
        if ok:
            self.done += 1
        self.c.report(step, ok, message)
        self.c.log(("✓ " if ok else "✕ ") + name + " — " + message)

    def fail(self, step_id: str, name: str, message: str, code: str = "tiktok_publish_blocked") -> dict:
        self.report(step_id, name, False, message)
        return self.result(False, message, {"code": code, "auto_key": "tiktok_publish",
                                            "reason": message, "retry": False})

    def result(self, ok: bool, error: str = "", stop: dict | None = None, **extra) -> dict:
        value = {"target": "tiktok", "done": self.done, "total": TOTAL_STEPS,
                 "results": self.results, "tags": self.c.tag_results,
                 "ads_closed": [], "ok": ok, "error": error}
        if stop:
            value["automation_stop"] = stop
        value.update(extra)
        return value

    def xml(self) -> str:
        native = self.c.dump()
        # A hierarchy containing only empty canvas/container nodes is still blind.
        if re.search(r'(?:text|content-desc)="[^"\s][^"]*"', native or ""):
            return native
        # **ลองตัวอ่านภาษาไทยก่อนเสมอ** (เพิ่ม 11 ก.ย. 2569) — หน้าร้านค้า TikTok
        # เป็นภาษาไทยล้วน ส่วนตัวอ่านเดิมรู้จักแค่จีน/อังกฤษ (ดู `get_thai_ocr`)
        thai = get_thai_ocr()
        if thai is not None:
            try:
                shot = Image.open(io.BytesIO(
                    self.c.run_adb("exec-out", "screencap", "-p"))).convert("RGB")
                root = ET.Element("hierarchy", source="ocr")
                found = 0
                for points, value, score in thai.readtext(np.array(shot)) or []:
                    if float(score) < .20 or not str(value).strip():
                        continue
                    xs = [int(p[0]) for p in points]
                    ys = [int(p[1]) for p in points]
                    ET.SubElement(root, "node", text=str(value).strip(),
                                  clickable="false",
                                  bounds=f"[{min(xs)},{min(ys)}][{max(xs)},{max(ys)}]")
                    found += 1
                if found:
                    return ET.tostring(root, encoding="unicode")
            except Exception as error:                        # noqa: BLE001
                self.c.log(f"  อ่านภาษาไทยจากภาพไม่สำเร็จ: {type(error).__name__}: "
                           f"{str(error)[:70]}")

        engine = publish_flow.get_ocr_engine()
        if not engine:
            return native
        try:
            screenshot = Image.open(io.BytesIO(self.c.run_adb("exec-out", "screencap", "-p"))).convert("RGB")
            rows, _ = engine(screenshot)
            root = ET.Element("hierarchy", source="ocr")
            for points, value, score in rows or []:
                if float(score) < .30 or not str(value).strip():
                    continue
                xs, ys = [int(p[0]) for p in points], [int(p[1]) for p in points]
                ET.SubElement(root, "node", text=str(value).strip(), clickable="false",
                              bounds=f"[{min(xs)},{min(ys)}][{max(xs)},{max(ys)}]")
            return ET.tostring(root, encoding="unicode")
        except Exception as error:
            self.c.log(f"  อ่านภาพสำรองไม่สำเร็จ: {type(error).__name__}")
            return native

    def why_blocked(self, xml: str, base: str) -> str:
        """ต่อท้ายข้อความล้มด้วย **สาเหตุจริงที่อ่านได้จากจอ**

        ห้ามปล่อยให้ข้อความล้มบอกแค่ว่า "ไม่พบ X" เพราะคนอ่านจะไปไล่หาสาเหตุ
        ที่ตัว X ทั้งที่ของจริงคือมีอย่างอื่นบังจนอ่านไม่ได้เลย — เสียเวลาไล่
        ผิดทางทั้งวัน (เจอจริง 11 ก.ย. 2569 กับข้อความ "ไม่พบปุ่มค้นหา"
        ที่แท้จริงคือกล่องขออนุญาตของ Android บังอยู่)
        """
        system_app = blocking_system_dialog(xml)
        if system_app:
            return (f"{base} — **มีกล่องขออนุญาตของ Android บังจออยู่** "
                    f"({system_app}) ปิดไม่ลง ต้องกดปิดเองที่เครื่องก่อน")
        frontmost = publish_flow.foreground(self.c.run_adb)
        if not is_tiktok_foreground(frontmost):
            return f"{base} — แอปที่อยู่หน้าสุดไม่ใช่ TikTok แต่เป็น {frontmost}"
        labels = len(set(re.findall(r'(?:text|content-desc)="([^"]{1,40})"', xml or "")))
        return (f"{base} — TikTok อยู่หน้าสุดปกติ และอ่านชื่อปุ่มบนจอได้ "
                f"{labels} คำ (ผัง {len(xml or '')} ตัวอักษร) "
                "แปลว่าของที่หาไม่ได้อยู่บนจอจริง อาจย้ายที่หรือเปลี่ยนชื่อ")

    # หน้าที่แปลว่า "ยังอยู่ในตัวตัดต่อ/ร่างค้าง" ไม่ใช่หน้าแรกที่มีแว่นขยาย
    EDITOR_MARKS = ("ถัดไป", "เพิ่มเสียง", "AutoCut", "สตอรี่ของคุณ",
                    "โพสต์", "ร่าง")
    HOME_MARKS = ("ค้นหา", "สำหรับคุณ", "หน้าหลัก", "กำลังติดตาม")
    # ชื่อหน้าจอที่ถือว่า "กลับมาหน้าแรกแล้ว" — อ่านจาก dumpsys ไม่ใช่จากผังจอ
    HOME_ACTIVITIES = ("main.MainActivity", "splash.SplashActivity")
    # ปุ่มทิ้งร่าง — ต้องเลือก "ทิ้ง" ไม่ใช่ "บันทึก" ไม่งั้นร่างจะกองสะสม
    DISCARD_MARKS = ("ทิ้ง", "ไม่บันทึก", "Discard", "ละทิ้ง")

    def settle_activity(self, timeout: float = 20, need: int = 3) -> str:
        """รอจนชื่อหน้าจอซ้ำกัน ``need`` ครั้งติด = แอปเปิดเสร็จจริงแล้ว

        ห้ามถามว่า "อยู่หน้าไหน" ทันทีหลังเปิดแอป เพราะช่วงนั้นหน้าจอยังเปลี่ยน
        ไปเรื่อย คำตอบที่ได้เป็นภาพชั่วคราวที่อีกวินาทีเดียวก็ไม่จริงแล้ว
        """
        seen, last = 0, ""
        deadline = time.time() + timeout
        while time.time() < deadline:
            where = publish_flow.foreground(self.c.run_adb)
            seen = seen + 1 if where == last else 1
            last = where
            if seen >= need:
                return last
            self.c.pause(1.5)
        return last

    def leave_leftover_draft(self, tries: int = 6) -> str:
        """ถอยออกจากร่างที่ค้างจากรอบก่อน ให้กลับมาหน้าแรกก่อนเริ่มค้นหา

        **เจอจริง 11 ก.ย. 2569** รอบที่หยุดก่อนโพสต์ทิ้ง "ร่าง" ไว้ในแอป
        พอรอบถัดไปสั่ง force-stop แล้วเปิดใหม่ **TikTok กู้ร่างเดิมขึ้นมาแทน
        หน้าแรก** ตัวผังจึงหาแว่นขยายไม่เจอแล้วล้มทั้งใบ

        ข้อนี้สำคัญมากสำหรับการรันต่อเนื่อง — ถ้าไม่แก้ ใบแรกที่หยุดกลางทาง
        จะทำให้ **ทุกใบหลังจากนั้นล้มตามกันหมด** โดยไม่มีใครรู้ว่าเพราะอะไร

        เลือก "ทิ้ง" ไม่ใช่ "บันทึกร่าง" เพราะร่างที่บันทึกไว้จะกลับมาโผล่ซ้ำ
        และร่างพวกนี้เป็นของที่ระบบสร้างเองทั้งหมด ไม่ใช่งานที่เจ้าของทำค้างไว้
        """
        # **เกาะชื่อหน้าจอ ไม่เกาะตัวหนังสือ** (แก้ 11 ก.ย. 2569 รอบสอง)
        #
        # รอบแรกเขียนให้ดูคำว่า "ถัดไป" บนจอ **แล้วไม่ทำงานเลย** เพราะหน้าตัวตัดต่อ
        # ส่งผังมา 59,807 ตัวอักษร แต่อ่านชื่อปุ่มได้แค่ 15 คำ และไม่มี "ถัดไป"
        # อยู่ในนั้น — พอหาไม่เจอ มันเลยสรุปว่า "ไม่ได้ค้างอยู่ในตัวตัดต่อ"
        # ทั้งที่ค้างอยู่เต็มๆ แล้วปล่อยผ่านไปล้มที่ขั้นถัดไปเหมือนเดิม
        #
        # ชื่อหน้าจอมาจาก `dumpsys` ไม่ได้มาจากผัง จึง **อ่านได้เสมอ** ไม่ว่าแอปจะ
        # ซ่อนตัวหนังสือแค่ไหน — วัดจริง: ตัวตัดต่อคือ `SAASceneWrapperActivity`
        # ส่วนหน้าแรกคือ `main.MainActivity`
        # **รอให้หน้าจอนิ่งก่อนตัดสิน** — ตอนเปิดแอปใหม่ TikTok โชว์หน้า Splash
        # ก่อนชั่วครู่ แล้วค่อยกู้ร่างขึ้นมาทีหลัง ถ้าถามตอนนั้นจะได้คำตอบว่า
        # "อยู่หน้าแรกแล้ว" ทั้งที่อีกวินาทีเดียวร่างจะเด้งขึ้นมาทับ
        # (เกิดจริง 11 ก.ย. 2569 — ตัวถอยร่างผ่านฉลุยแต่ขั้นถัดไปล้มเหมือนเดิม)
        self.settle_activity()
        # เก็บ "ยอดเล่นของคลิปในโปรไฟล์ก่อนเริ่มงาน" ไว้เทียบตอนยืนยันผลโพสต์
        # ต้องเก็บตรงนี้เพราะเป็นจังหวะเดียวที่แอปเปิดอยู่และยังไม่ได้ทำอะไร
        if not self.tiles_before:
            self.tiles_before = self.profile_tiles(tries=1)
            self.c.log(f"  จดยอดเล่นก่อนเริ่มงานไว้: {self.tiles_before[:6] or 'อ่านไม่ได้'}")
            self.c.run_adb("shell", "input", "tap", "72", "1520")   # กลับแท็บหน้าหลัก
            self.c.pause(2.5)
        for _ in range(tries):
            where = publish_flow.foreground(self.c.run_adb)
            if any(mark in where for mark in self.HOME_ACTIVITIES):
                return "อยู่หน้าแรกแล้ว"
            if not is_tiktok_foreground(where):
                return f"ไม่ได้อยู่ใน TikTok ({where})"
            self.c.log(f"  ค้างอยู่ที่ {where.split('/')[-1]} — ถอยกลับหน้าแรก")
            self.c.run_adb("shell", "input", "keyevent", "4")
            self.c.pause(1.8)
            box = find_bounds(self.xml(), self.DISCARD_MARKS)
            if box is not None:
                self.tap(Target("ทิ้งร่างที่ค้าง", self.DISCARD_MARKS, box), 2.0)
        where = publish_flow.foreground(self.c.run_adb)
        if any(mark in where for mark in self.HOME_ACTIVITIES):
            return "ถอยกลับหน้าแรกแล้ว"
        # ถอยไม่ออก = เปิดใหม่จากศูนย์อีกรอบ ดีกว่าเดินหน้าไปกดมั่วบนหน้าที่ไม่รู้จัก
        self.c.log("  ถอยออกจากร่างค้างไม่ได้ — ปิดแอปแล้วเปิดใหม่อีกครั้ง")
        self.c.run_adb("shell", "am", "force-stop", TIKTOK_PACKAGE)
        self.c.pause(2.0)
        self.c.run_adb("shell", "monkey", "-p", TIKTOK_PACKAGE,
                       "-c", "android.intent.category.LAUNCHER", "1")
        self.c.pause(6.0)
        return "เปิดแอปใหม่เพื่อล้างร่างค้าง"

    def seen(self, xml: str, needle: str) -> bool:
        """เจอคำนี้บนจอไหม — **ยอมให้วรรณยุกต์ตกได้เฉพาะผังที่มาจากการอ่านภาพ**

        ตัวอ่านภาพทำเครื่องหมายตกจริง (วัด 11 ก.ย. 2569: ปุ่ม "เพิ่ม" อ่านได้
        เป็น "เพิม" ไม้เอกหาย) ถ้าเทียบตรงตัวจะพลาดทั้งที่อ่านถูกทุกตัวหลัก

        **ผังจริงจากระบบยังเทียบเป๊ะเหมือนเดิม** เพราะตัวอักษรถูกต้อง 100%
        อยู่แล้ว — เทียบหลวมโดยไม่จำเป็นคือเปิดช่องให้ไปกดโดนปุ่มที่สะกดใกล้กัน
        """
        plain = html.unescape(xml or "")
        if str(needle or "").casefold() in plain.casefold():
            return True
        return bool(from_ocr(xml) and thai_loose(needle) in thai_loose(plain))

    def wait_text(self, *needles: str, timeout: float = 20) -> str:
        deadline = time.time() + timeout
        last = ""
        while time.time() < deadline:
            last = self.xml()
            if all(self.seen(last, value) for value in needles):
                return last
            self.c.pause(0.8)
        return last

    def wait_any_text(self, *needles: str, timeout: float = 20) -> str:
        deadline = time.time() + timeout
        last = ""
        wanted = [value for value in needles if value]
        while time.time() < deadline:
            last = self.xml()
            if any(self.seen(last, value) for value in wanted):
                return last
            self.c.pause(.8)
        return last

    def wait_clickable(self, *needles: str, timeout: float = 12) -> tuple[int, int, int, int] | None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            box = find_clickable_bounds(self.xml(), tuple(needles))
            if box:
                return box
            self.c.pause(.7)
        return None

    def tap(self, target: Target, settle: float = 1.2) -> tuple[int, int]:
        xml = self.xml()
        box = find_bounds(xml, target.needles)
        if box is None and target.fallback is not None:
            box = _scaled(target.fallback, self.c.screen)
        if box is None:
            raise TikTokPublishError(f"หาปุ่ม {target.label} ไม่พบ")
        point = self.c.tap_in_bounds(box)
        self.c.log(f"  แตะ {target.label} ที่ {point[0]},{point[1]} (อยู่ในกรอบปุ่ม)")
        self.c.pause(settle)
        return point

    def dismiss_soft_prompts(self) -> str:
        """ปิดคำชวนที่บังจอ โดยไม่ตอบรับหรือเปลี่ยนการตั้งค่าบัญชี."""
        xml = self.xml()
        plain = html.unescape(xml)

        # ---- กล่องขออนุญาตของ Android มาก่อนทุกอย่าง (เพิ่ม 11 ก.ย. 2569) ----
        #
        # ตอนกล่องนี้บังอยู่ ผังที่อ่านได้คือผังของกล่อง **ไม่ใช่ของ TikTok**
        # เงื่อนไขทุกข้อข้างล่างจึงไม่ตรงสักข้อ แล้วเมธอดนี้เคยตอบว่า
        # "ไม่มีคำชวนบังจอ" ซึ่งผิดตรงข้ามกับความจริง (เหตุผลเต็มที่
        # `blocking_system_dialog`)
        #
        # **ตอบ "ไม่อนุญาต" เสมอ ห้ามกดให้สิทธิ์** — การให้สิทธิ์แอปเป็น
        # การตั้งค่าของเจ้าของเครื่อง ไม่ใช่สิ่งที่ตัวโพสต์ควรตัดสินใจแทน
        # และงานโพสต์คลิปไม่ต้องใช้สิทธิ์พวกนี้เลยสักอย่าง
        system_app = blocking_system_dialog(xml)
        if system_app:
            deny = ("ไม่อนุญาต", "ไม่ต้องขอบคุณ", "Don't allow", "Deny",
                    "ไม่ใช่ตอนนี้", "Not now")
            bounds = find_bounds(xml, deny)
            if bounds is not None:
                self.tap(Target("ไม่อนุญาต", deny, bounds), 1.5)
                after = self.xml()
                if not blocking_system_dialog(after):
                    return f"ปิดกล่องขออนุญาตของ Android แล้ว (เลือกไม่อนุญาต)"
                # ปิดไม่ลง = อย่าเดาพิกัดต่อ ปล่อยให้ขั้นถัดไปฟ้องพร้อมเหตุผลจริง
                return (f"⚠️ กล่องขออนุญาตของ Android ({system_app}) ยังบังจออยู่ "
                        "แม้กดไม่อนุญาตแล้ว")
            self.c.run_adb("shell", "input", "keyevent", "4")
            self.c.pause(1.5)
            if not blocking_system_dialog(self.xml()):
                return "ปิดกล่องขออนุญาตของ Android ด้วยปุ่มย้อนกลับแล้ว"
            return (f"⚠️ กล่องขออนุญาตของ Android ({system_app}) บังจออยู่ "
                    "และปิดไม่ลง — ต้องกดปิดเองที่เครื่อง")

        # พบจริงบนหน้าสินค้า 10 ก.ย. 2569: modal "รับคูปองส่วนลด" โผล่ทับ
        # หลังแตะลูกศรโปรโมชั่น ทำให้ตัวอ่านหาแผงไม่เจอแล้วพักใบทั้งที่สินค้า
        # ถูกต้อง. กด CTA เฉพาะเมื่อหัวข้อคูปองอยู่บนจอเดียวกัน; ถ้า Android
        # ซ่อนปุ่มจาก XML ให้ Back ปิด modal แทนการเดาพิกัด.
        if any(marker in plain for marker in (
            "รับคูปองส่วนลด", "คูปองส่วนลด", "Coupon discount", "Get coupon",
        )):
            bounds = find_bounds(xml, ("เก็บ", "เก็บเลย", "รับคูปอง", "Collect", "Claim"))
            if bounds is not None:
                self.tap(Target("ปิดป๊อปอัปรับคูปอง",
                                ("เก็บ", "เก็บเลย", "รับคูปอง", "Collect", "Claim"),
                                bounds), 1.5)
                return "ปิดป๊อปอัปรับคูปองแล้ว"
            self.c.run_adb("shell", "input", "keyevent", "4")
            self.c.pause(1.5)
            return "ปิดป๊อปอัปรับคูปองด้วยปุ่มย้อนกลับแล้ว"
        if ("อนุญาตให้เข้าถึงรายชื่อติดต่อ" in plain
                and "ไม่อนุญาต" in plain):
            self.tap(Target("ไม่อนุญาตรายชื่อติดต่อ", ("ไม่อนุญาต",),
                            (80, 910, 359, 1005)))
            return "ปิดคำขอเข้าถึงรายชื่อติดต่อแล้ว"
        if "ปัดขึ้นเพื่อดูเพิ่มเติม" in plain:
            self.c.run_adb("shell", "input", "swipe", "360", "1080", "360", "650", "450")
            self.c.pause(1.2)
            return "ปิดหน้าสอนการปัดแล้ว"
        if "ติดตามเพื่อน ๆ ของคุณ" in plain:
            self.tap(Target("ปิดคำชวนติดตามเพื่อน", ("ปิด",),
                            (620, 330, 680, 390)))
            return "ปิดคำชวนติดตามเพื่อนแล้ว"
        if ("รับการแจ้งเตือนเมื่อมีอัปเดตใหม่หรือไม่" in plain
                and "ไม่ใช่ตอนนี้" in plain):
            self.tap(Target("ไม่ใช่ตอนนี้", ("ไม่ใช่ตอนนี้",),
                            (64, 1398, 352, 1488)))
            return "ปิดคำชวนรับการแจ้งเตือนแล้ว"

        # ---- กล่อง "เพิ่มอีเมล" (เจอจริง 13 ก.ย. 2569 เวลา 23:11 และ 23:14) ----
        #
        # TikTok เด้งกล่องชวนผูกอีเมลเต็มจอ **พร้อมเปิดคีย์บอร์ดรออยู่** ทำให้
        # ขั้นแรกของผังแตะแว่นขยายไม่โดน แล้วล้มที่ขั้น 2 จาก 14 สองใบติดกัน
        # (26577901113 · 27977891222) ตอนล้มอ่านชื่อปุ่มบนจอได้แค่ 3 และ 8 คำ
        # เพราะที่เหลือเป็นคีย์บอร์ดกับกล่องซึ่งไม่ส่งชื่อออกมา
        #
        # **ปิดอย่างเดียว ห้ามกรอกอีเมลและห้ามกด "ดำเนินการต่อ"** — การผูกอีเมล
        # เป็นการตั้งค่าบัญชีของเจ้าของ ไม่ใช่สิ่งที่ตัวโพสต์ตัดสินใจแทน
        # (หลักเดียวกับกล่องขอสิทธิ์ของ Android ข้างบนที่ตอบ "ไม่อนุญาต" เสมอ)
        #
        # กดย้อนกลับสองที: ทีแรกปิดคีย์บอร์ด ทีที่สองปิดกล่อง — และ**ต้องตรวจ
        # ว่าปิดลงจริง** ไม่ใช่กดแล้วเชื่อว่าหาย (กติกา 2.3.1)
        if any(mark in plain for mark in (
            "เพิ่มอีเมล", "เพิ่มที่อยู่อีเมลของคุณ", "Add email",
        )):
            for _ in range(2):
                self.c.run_adb("shell", "input", "keyevent", "4")
                self.c.pause(1.2)
                if "เพิ่มอีเมล" not in html.unescape(self.xml()):
                    return "ปิดกล่องชวนเพิ่มอีเมลแล้ว (ไม่ได้กรอกอะไร)"
            return ("⚠️ กล่องชวนเพิ่มอีเมลของ TikTok บังจออยู่และปิดไม่ลง "
                    "ต้องกดปิดเองที่เครื่องก่อน")
        return "ไม่มีคำชวนบังจอ"

    def hide_keyboard_if_shown(self) -> None:
        raw = self.c.run_adb("shell", "dumpsys", "input_method")
        state = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw)
        if "mInputShown=true" in state or "mImeShowing=true" in state:
            self.c.run_adb("shell", "input", "keyevent", "4")
            self.c.pause(.8)

    @staticmethod
    def anchor_name_entered(xml: str) -> bool:
        """LynxInputView ไม่เปิด text; ใช้ชื่อที่อ่านได้หรือจำนวนอักษรของช่องแทน."""
        plain = html.unescape(xml or "")
        return (ANCHOR_NAME in plain
                or (f"{len(ANCHOR_NAME)}/30" in plain
                    and "LynxInputView" in plain
                    and "ชื่อสินค้า" in plain))

    def verify_product(self, xml: str, require_model: bool = True) -> bool:
        plain = re.sub(r"\s+", "", html.unescape(xml or "")).upper()
        terms = _model_terms(str(self.run.get("name") or ""))
        brand = terms[0] if terms else ""
        models = [term for term in terms[1:] if any(ch.isdigit() for ch in term)]
        return bool(brand and brand in plain
                    and (not require_model or not models or any(term in plain for term in models)))

    def verify_current_after_human_check(self, xml: str) -> bool:
        """ด่านเฉพาะการกลับมาหลังเจ้าของแก้ CAPTCHA บนลิงก์ใบนี้ด้วยมือ."""
        link = self.run.get("tiktok_product_link") or {}
        if link.get("status") != "matched" or str(link.get("confidence") or "").lower() != "high":
            return False
        plain = re.sub(r"\s+", "", html.unescape(xml or "")).upper()
        name = str(self.run.get("name") or "").upper()
        terms = _model_terms(name)
        brand = terms[0] if terms else ""
        size = re.search(r"\b(\d{2,3})\s*(?:นิ้ว|INCH)", name, re.I)
        kind_ok = (("ทีวี" in name or " TV " in f" {name} ")
                   and ("ทีวี" in plain or "TV" in plain))
        return bool(brand and brand in plain and size and size.group(1) in plain and kind_ok)

    def ensure_showcase(self, promotion_xml: str) -> tuple[bool, str]:
        """เพิ่มสินค้าตรงรุ่นเข้าโชว์เคส โดยไม่เลือกสินค้าที่ TikTok แนะนำแทน."""
        plain = html.unescape(promotion_xml or "")
        if "เพิ่มในโชว์เคสแล้ว" in plain:
            return True, "สินค้าอยู่ในโชว์เคสแล้ว"
        if "เพิ่มในโชว์เคส" not in plain:
            return False, "แผงโปรโมชั่นเปิดอยู่แต่ไม่พบปุ่มเพิ่มในโชว์เคส"

        self.tap(Target("เพิ่มในโชว์เคส", ("เพิ่มในโชว์เคส",),
                        (32, 1440, 688, 1528)))
        result_xml = self.wait_text("เพิ่มในโชว์เคส", timeout=8)
        result_plain = html.unescape(result_xml)
        if "เพิ่มในโชว์เคสแล้ว" in result_plain:
            return True, "สินค้าอยู่ในโชว์เคสแล้ว"

        # สินค้าบางรายการพาไปหน้า "สำรวจสินค้า" ซึ่งรายการแรกอาจเป็นคนละรุ่น
        # ห้ามเลือกจากหน้านั้น ให้ย้อนกลับและเปิดวิดีโอตัวอย่างของสินค้าต้นทางแทน
        # เพราะหน้าข้อมูลเชิงลึกแสดงชื่อเต็มและปุ่มเพิ่มของสินค้าตรงรุ่น.
        if "สำรวจสินค้า" not in result_plain:
            return False, "ปุ่มเพิ่มในโชว์เคสไม่เปลี่ยนเป็นเพิ่มแล้ว"
        self.c.run_adb("shell", "input", "keyevent", "4")
        promotion_xml = self.wait_text("ข้อมูลโปรโมชั่น", timeout=10)
        if "ข้อมูลโปรโมชั่น" not in html.unescape(promotion_xml):
            return False, "ย้อนกลับจากหน้าสำรวจสินค้าไม่ถึงข้อมูลโปรโมชั่น"

        # ตำแหน่งรูปตัวอย่างนี้เทรนเฉพาะ REDMI 15C; จุดแตะยังสุ่มอยู่ภายในรูป.
        preview_box = _scaled((246, 1155, 474, 1300), self.c.screen)
        point = self.c.tap_in_bounds(preview_box)
        self.c.log(f"  แตะวิดีโอตัวอย่างสินค้าที่ {point[0]},{point[1]} (อยู่ในกรอบรูป)")
        insight_xml = self.wait_text("ข้อมูลเชิงลึกของวิดีโอ", "สินค้าที่นำเสนอ", timeout=15)
        insight_plain = html.unescape(insight_xml)
        if ("ข้อมูลเชิงลึกของวิดีโอ" not in insight_plain
                or "สินค้าที่นำเสนอ" not in insight_plain):
            return False, "เปิดข้อมูลเชิงลึกของวิดีโอสินค้าไม่ได้"
        if not self.verify_product(insight_xml, require_model=True):
            return False, "สินค้าที่นำเสนอในวิดีโอตัวอย่างไม่ตรงรุ่นในใบงาน"
        if find_bounds(insight_xml, ("เพิ่ม",)) is None:
            return False, "ไม่พบปุ่มเพิ่มของสินค้าตรงรุ่นในข้อมูลเชิงลึก"

        # WebView รายงานแกน Y ไม่ตรงกับพิกัดจริง จึงเลื่อนการ์ดขึ้นก่อน แล้วใช้
        # กรอบจริงที่เทรนจากจอ 720x1600 แทนการเชื่อพิกัด XML ที่คลาดเคลื่อน.
        self.c.run_adb("shell", "input", "swipe", "360", "1380", "360", "760", "500")
        self.c.pause(1.5)
        insight_xml = self.xml()
        if (not self.verify_product(insight_xml, require_model=True)
                or find_bounds(insight_xml, ("เพิ่ม",)) is None):
            return False, "หลังเลื่อนหน้าไม่พบสินค้าตรงรุ่นและปุ่มเพิ่มพร้อมกัน"
        add_box = _scaled((512, 930, 688, 1025), self.c.screen)
        point = self.c.tap_in_bounds(add_box)
        self.c.log(f"  แตะเพิ่มสินค้าตรงรุ่นที่ {point[0]},{point[1]} (อยู่ในกรอบปุ่มจริง)")
        self.c.pause(2.0)
        self.c.run_adb("shell", "input", "keyevent", "4")
        promotion_xml = self.wait_text("ข้อมูลโปรโมชั่น", timeout=12)
        if "เพิ่มในโชว์เคสแล้ว" not in html.unescape(promotion_xml):
            return False, "เพิ่มสินค้าตรงรุ่นแล้ว แต่แผงโปรโมชั่นยังไม่ยืนยันว่าอยู่ในโชว์เคส"
        return True, "เพิ่มสินค้าตรงรุ่นผ่านวิดีโอตัวอย่างสำเร็จ"

    def wait_saved_product(self, timeout: float = 24) -> str:
        """รอหน้าสินค้าที่ตรงกับชื่อที่บันทึกไว้; ไม่เชื่อแค่อันดับผลค้นหา."""
        deadline = time.time() + timeout
        last = ""
        while time.time() < deadline:
            last = self.xml()
            if saved_product_matches(self.run, last):
                return last
            self.c.pause(.8)
        return last

    def wait_product_detail(self, timeout: float = 20) -> str:
        deadline = time.time() + timeout
        last = ""
        while time.time() < deadline:
            last = self.xml()
            if product_detail_visible(last):
                return last
            self.c.pause(.8)
        return last

    def wait_shop_results(self, timeout: float = 30) -> str:
        deadline = time.time() + timeout
        last = ""
        while time.time() < deadline:
            last = self.xml()
            if shop_results_visible(last):
                return last
            self.c.pause(.8)
        return last

    def promotion_panel_visible(self) -> bool:
        """ยืนยัน bottom sheet จากปุ่ม CTA กว้าง เมื่อ TikTok ซ่อน text จาก XML."""
        try:
            image = Image.open(io.BytesIO(
                self.c.run_adb("exec-out", "screencap", "-p")))
            return bool(tiktok_product_link.promo_add_button_bounds(image))
        except Exception:
            return False

    def promotion_chooser_on_screen(self) -> bool:
        try:
            image = Image.open(io.BytesIO(
                self.c.run_adb("exec-out", "screencap", "-p")))
            return promotion_chooser_visible(image)
        except Exception:
            return False

    def open_promotion_panel(self, product_xml: str) -> tuple[str, bool]:
        """เปิดแผงโปรโมชั่น; ถ้ามี popup บังให้ปิดและทำขั้นเดิมซ้ำหนึ่งรอบ."""
        current = product_xml or ""
        if ("ข้อมูลโปรโมชั่น" in html.unescape(current)
                or self.promotion_panel_visible()):
            return current, True

        for attempt in range(2):
            self.tap(Target("ลูกศรขึ้นสองขีด", fallback=(344, 1288, 376, 1328)), 1.5)
            current = self.wait_text("ข้อมูลโปรโมชั่น", timeout=4)
            if ("ข้อมูลโปรโมชั่น" in html.unescape(current)
                    or self.promotion_panel_visible()):
                return current, True

            dismissed = self.dismiss_soft_prompts()
            if dismissed != "ไม่มีคำชวนบังจอ":
                self.c.log(f"  {dismissed} · กลับมาตรวจขั้นเปิดโปรโมชั่นรอบเดิม")
                current = self.xml()
                if ("ข้อมูลโปรโมชั่น" in html.unescape(current)
                        or self.promotion_panel_visible()):
                    return current, True
            # รอบถัดไปแตะลูกศรเดิมอีกครั้ง หลัง popup ถูกปิดแล้ว. จำกัดสองรอบ
            # เพื่อไม่วนกดไม่จบเมื่อ TikTok เปลี่ยนหน้า.
            if attempt == 0:
                continue
        return current, False

    def open_prepared_product(self) -> str:
        """ค้นชื่อสินค้าเดิมและเปิดอันดับที่เคยตรวจผ่าน โดยสุ่มจุดกดทุกปุ่ม."""
        state = self.run.get("tiktok_product_link") or {}
        query = str(state.get("search_query") or self.run.get("name") or "").strip()
        try:
            rank = int(state.get("selected_rank") or 0)
        except (TypeError, ValueError):
            rank = 0
        if not query or rank not in (1, 2, 3, 4):
            raise TikTokPublishError("ใบงานไม่มีคำค้นหรืออันดับสินค้าที่เคยยืนยัน")

        # เปิดใหม่จากหน้าแรกทุกใบเพื่อไม่ให้คำค้น/สินค้าของใบก่อนค้างอยู่บนจอ.
        self.c.run_adb("shell", "am", "force-stop", TIKTOK_PACKAGE)
        self.c.run_adb("shell", "monkey", "-p", TIKTOK_PACKAGE,
                       "-c", "android.intent.category.LAUNCHER", "1")
        self.c.pause(2.5)
        self.dismiss_soft_prompts()
        self.leave_leftover_draft()
        frontmost = publish_flow.foreground(self.c.run_adb)
        # foreground() คืน ``package/Activity`` ไม่ได้คืน package เปล่า.
        # เทียบทั้งสตริงทำให้ TikTok เปิดอยู่จริงก็ถูกหยุดทุกครั้ง.
        if not is_tiktok_foreground(frontmost):
            raise TikTokPublishError("เปิด TikTok แล้วแต่แอปไม่ได้อยู่หน้าสุด")

        # ---- ห้ามถามหน้าฟีดว่า "เห็นปุ่มค้นหาไหม" (แก้ 11 ก.ย. 2569) ---------
        #
        # ของเดิมรอ `wait_any_text("ค้นหา", "สำหรับคุณ", "หน้าหลัก")` แล้วล้มทั้งใบ
        # ถ้าไม่เจอ — **วัดจริงแล้วหน้าฟีดตอบคำถามนี้ไม่ได้เป็นบางครั้ง**
        #
        #   ฟีดเปิดเจอคลิปปกติ   ผัง 45,585 ตัวอักษร · อ่านชื่อปุ่มได้ 19 คำ · เจอ "ค้นหา"
        #   ฟีดเปิดเจอไลฟ์       ผัง  7,867 ตัวอักษร · อ่านชื่อปุ่มได้ **0 คำ** · ไม่เจออะไรเลย
        #                        (วัดติดกัน 6 รอบ นานเกิน 2 นาที — รอไปก็ไม่มีวันเจอ)
        #
        # ไม่ใช่เรื่องเปิดแอปช้า: วัดเวลาเปิดจากศูนย์แล้วเจอปุ่มค้นหาใน **5.1 วินาที**
        # ขณะที่เพดานเดิมตั้งไว้ 20 วินาที — เวลาเหลือเฟือ แต่ของที่ถามหาไม่มีให้อ่าน
        #
        # **ย้ายที่ตรวจ ไม่ใช่ตัดการตรวจทิ้ง** (กติกาข้อ 2.3.1) — แว่นขยายเป็นปุ่ม
        # ประจำแอปที่อยู่กับที่เสมอ ไม่ใช่ช่องที่เนื้อหาเปลี่ยนไปมาแบบตารางเลือกคลิป
        # ของ Facebook แตะตามพิกัดได้ปลอดภัย แล้วไปพิสูจน์ที่ **หน้าค้นหา** แทน
        # ซึ่งอ่านได้แน่นอน (วัด 2 ครั้ง ได้ชื่อปุ่ม 14 คำเท่ากันทั้งคู่)
        self.tap(Target("ค้นหา", ("ค้นหา",), (628, 88, 704, 178)), 1.5)
        search_needles = ("ค้นหา", "ถาม AI", "ติดเทรนด์ในพื้นที่", "ดูเพิ่มเติม")
        search_xml = self.wait_any_text(*search_needles, timeout=20)
        if not any(m in html.unescape(search_xml) for m in search_needles):
            note = self.dismiss_soft_prompts()
            self.c.log(f"  เข้าหน้าค้นหาไม่ได้ — {note}")
            # **ปิดกล่องแล้วต้องแตะแว่นขยายซ้ำ** ไม่ใช่รออย่างเดียว
            #
            # การแตะครั้งแรกถูกกล่องที่บังอยู่กินไปแล้ว พอปิดกล่องได้ หน้าจอจะ
            # กลับมาที่ฟีดหน้าแรก ไม่ใช่หน้าค้นหา — ถ้าแค่รอต่อก็รอจนหมดเวลา
            # แล้วล้มทั้งที่อุปสรรคถูกเอาออกไปแล้ว (เจอจริง 13 ก.ย. 2569
            # กล่อง "เพิ่มอีเมล" ทำสองใบล้มติดกันที่ขั้น 2 จาก 14)
            if not note.startswith(("ไม่มีคำชวนบังจอ", "⚠️")):
                self.tap(Target("ค้นหา", ("ค้นหา",), (628, 88, 704, 178)), 1.5)
            search_xml = self.wait_any_text(*search_needles, timeout=15)
        if not any(m in html.unescape(search_xml) for m in search_needles):
            raise TikTokPublishError(self.why_blocked(
                search_xml, "แตะแว่นขยายแล้วแต่ไม่เข้าหน้าค้นหา"))
        publish_flow._clear_field(self.c)
        publish_flow._put_tag(self.c, query)
        self.c.pause(.7)
        self.c.run_adb("shell", "input", "keyevent", "66")
        # ---- แถบแท็บผลค้นหา: ต้องแตะตามตำแหน่ง อ่านชื่อไม่ได้ (แก้ 11 ก.ย. 2569) ----
        #
        # ของเดิมรอ `wait_text("ร้านค้า")` แล้วล้มทั้งใบถ้าไม่เจอ **แต่วัดแล้ว
        # ชื่อแท็บอ่านไม่ได้เลยทั้งสองทาง**
        #
        #   ผังจากระบบ  หน้าผลค้นหามีนาฬิกานับถอยหลังเดินตลอด + คลิปพรีวิวเล่นวน
        #               `uiautomator dump` จึงตอบ "ERROR: could not get idle state."
        #               (วัดติดกัน 3 รอบ ได้ข้อความเดียวกันทุกรอบ)
        #   OCR สำรอง   อ่านได้ 41 คำ เป็นชื่อสินค้ากับราคา **ไม่มีชื่อแท็บสักอัน**
        #               (ตัวหนังสือแท็บเป็นสีเทาอ่อนตัวเล็ก)
        #
        # **และ TikTok เพิ่งแทรกแท็บ "ถาม" (ถาม AI) เข้ามาเป็นอันแรก** ทำให้ทุกแท็บ
        # เลื่อนไปขวาหนึ่งช่อง กรอบเดิม (145,178)-(270,258) จุดกลาง x=207 จึงไป
        # ตกที่แท็บ **"ดีที่สุด"** แทน "ร้านค้า" — กดถูกทุกครั้งแต่ผิดแท็บ
        #
        # แถบแท็บที่วัดจากภาพจริง (จอกว้าง 720):
        #     ถาม 60 · ดีที่สุด 180 · **ร้านค้า 302** · วิดีโอ 420 · ผู้ใช้/รูปภาพ 530,648
        # ลำดับสองอันท้ายสลับกันได้ แต่ "ร้านค้า" อยู่อันที่ 3 คงที่ทุกครั้งที่วัด
        #
        # ปลอดภัยที่จะแตะตามตำแหน่ง เพราะเป็นแถบประจำแอป ไม่ใช่ช่องที่เนื้อหา
        # เปลี่ยนไปมาแบบตารางเลือกคลิปของ Facebook (บทเรียน 10 ก.ย. ที่โพสต์รูปผิด)
        # **แต่ต้องพิสูจน์ผลหลังแตะเสมอ** ด้วยผลสินค้าที่ขึ้นจริง ถ้า TikTok ย้าย
        # แท็บอีก ด่านข้างล่างจะฟ้องดังพร้อมบอกว่าอ่านอะไรได้บ้าง ไม่ใช่เงียบแล้วกดมั่ว
        self.tap(Target("แท็บร้านค้า", ("ร้านค้า",), (250, 185, 355, 252)), 3.0)
        result_xml = self.wait_shop_results(timeout=30)
        if not shop_results_visible(result_xml):
            # **จุดที่กล่องขอสิทธิ์ตำแหน่งเด้งบ่อยที่สุด** (วัดจริง 11 ก.ย. 2569)
            # TikTok ขอ "เข้าถึงตำแหน่งของอุปกรณ์" ตอนเปิดแท็บร้านค้า เพราะ
            # ผลสินค้าเรียงตามระยะส่ง — กล่องขึ้นหลังผ่านด่านแท็บไปแล้วพอดี
            # ตัวอ่านจึงได้ผังของกล่อง (7,692 ตัวอักษร) ไม่ใช่ผังผลสินค้า
            self.c.log(f"  ยังไม่เห็นผลสินค้า — {self.dismiss_soft_prompts()}")
            result_xml = self.wait_shop_results(timeout=20)
        if not shop_results_visible(result_xml):
            raise TikTokPublishError(self.why_blocked(
                result_xml, "แท็บร้านค้าเปิดแล้วแต่ผลสินค้ายังไม่โหลด"))

        # กรอบเล็กอยู่กลางรูปสินค้า ไม่ทับหัวข้อ ราคา หรือปุ่มอื่น และจุดจริงจะ
        # ถูกสุ่มต่ออีกชั้นโดย tap_in_bounds แต่ยังคงอยู่ในกรอบเสมอ.
        if rank in (3, 4):
            self.c.run_adb("shell", "input", "swipe", "360", "1330", "360", "690", "500")
            self.c.pause(1.5)
        centers = {1: (167, 567), 2: (520, 567), 3: (167, 1033), 4: (520, 1033)}
        cx, cy = centers[rank]
        point = self.c.tap_in_bounds((cx - 34, cy - 34, cx + 34, cy + 34))
        self.c.log(f"  แตะผลสินค้าที่เคยยืนยันอันดับ {rank} ที่ {point[0]},{point[1]}")
        self.c.pause(4.5)
        product_xml = self.wait_saved_product()
        if product_detail_visible(product_xml) and not saved_product_matches(self.run, product_xml):
            expand = truncated_product_title_bounds(self.run, product_xml)
            if expand:
                point = self.c.tap_in_bounds(expand)
                self.c.log(f"  ขยายชื่อสินค้าที่ {point[0]},{point[1]} เพื่ออ่านรุ่นเต็ม")
                self.c.pause(1.5)
                product_xml = self.wait_saved_product(timeout=10)
        if saved_product_matches(self.run, product_xml) and not product_detail_visible(product_xml):
            # ผลบางรอบเป็น shoppable video: ชื่อตรงแต่ยังไม่มีลูกศรโปรโมชัน.
            # แตะบริเวณชื่อบนการ์ด (ไม่แตะปุ่มซื้อด้านขวา) เพื่อเข้ารายละเอียดจริง.
            self.tap(Target("การ์ดสินค้าบนวิดีโอ",
                            fallback=(180, 1075, 548, 1198)), 4.0)
            # หน้าการ์ดก่อนแตะยืนยันชื่อเต็มแล้ว; หน้ารายละเอียดมักตัดชื่อด้วย ...
            # จึงรอโครงสร้างรายละเอียด ไม่เอาชื่อที่ถูกตัดมา reject ซ้ำ.
            product_xml = self.wait_product_detail()
            if product_detail_visible(product_xml):
                return product_xml
        if (not saved_product_matches(self.run, product_xml)
                or not product_detail_visible(product_xml)):
            raise TikTokPublishError(
                f"ผลอันดับ {rank} ยังไม่เปิดเป็นหน้ารายละเอียดสินค้าตรงใบงาน — หยุดก่อนโพสต์")
        return product_xml

    def open_gallery_from_product(self) -> None:
        """เปิดกล้องจากหน้าสินค้าและผูกชื่อสินค้า ก่อนเข้าคลังวิดีโอ."""
        self.tap(Target("สร้างตอนนี้เลย", ("สร้างตอนนี้เลย",),
                        (32, 1438, 688, 1536)), 2.0)
        chooser = self.wait_text("คุณต้องการโปรโมตสินค้าอย่างไร", timeout=4)
        if ("คุณต้องการโปรโมตสินค้าอย่างไร" not in html.unescape(chooser)
                and not self.promotion_chooser_on_screen()):
            raise TikTokPublishError("กดสร้างตอนนี้แล้วแต่หน้าเลือกวิธีโปรโมตไม่เปิด")
        self.tap(Target("กล้อง", ("กล้อง",), (32, 1117, 688, 1324)), 1.5)
        confirm = self.wait_any_text("เพิ่มสินค้าหรือไม่", "edit_anchor_name_input",
                                     timeout=15)
        plain_confirm = html.unescape(confirm)
        if "edit_anchor_name_input" in plain_confirm:
            rename = confirm
        elif "เพิ่มสินค้าหรือไม่" in plain_confirm:
            self.tap(Target("ยืนยันเพิ่มสินค้า", ("เพิ่ม",), (80, 840, 640, 938)), 3.0)
            rename = self.wait_text("edit_anchor_name_input", timeout=25)
        else:
            raise TikTokPublishError("เลือกกล้องแล้วแต่ไม่พบหน้าต่างยืนยันเพิ่มสินค้า")
        if "edit_anchor_name_input" not in html.unescape(rename):
            raise TikTokPublishError("ยืนยันสินค้าแล้วแต่หน้าเปลี่ยนชื่อสินค้าไม่เปิด")

        # หน้าใหม่นี้โฟกัสช่องชื่อให้อัตโนมัติ แต่แตะในกรอบอีกครั้งเพื่อให้การล้าง
        # ทำกับช่องที่ถูกต้องแม้ TikTok เปลี่ยนการโฟกัสในรุ่นถัดไป.
        self.tap(Target("ช่องชื่อสินค้า", ("edit_anchor_name_input",),
                        (32, 800, 688, 900)), .4)
        publish_flow._clear_field(self.c)
        publish_flow._put_tag(self.c, ANCHOR_NAME)
        self.c.pause(.8)
        if not self.anchor_name_entered(self.xml()):
            raise TikTokPublishError("ใส่ชื่อสินค้าใหม่แล้วแต่ตรวจคำว่า กดซื้อเลย ไม่พบ")
        self.hide_keyboard_if_shown()
        self.tap(Target("เพิ่มชื่อสินค้า", ("edit_anchor_add_button", "เพิ่ม"),
                        (32, 1440, 688, 1536)), 4.0)
        camera = self.wait_text("เพิ่มเสียง", timeout=20)
        if "เพิ่มเสียง" not in html.unescape(camera):
            raise TikTokPublishError("บันทึกชื่อสินค้าแล้วแต่หน้ากล้องไม่เปิด")

    def pick_latest_clip(self) -> None:
        self.tap(Target("เปิดคลังวิดีโอ", fallback=(536, 1190, 650, 1325)), 3.0)
        gallery = self.wait_text("วิดีโอ", timeout=18)
        if "อนุญาตทั้งหมด" in html.unescape(gallery):
            self.tap(Target("อนุญาตทั้งหมด", ("อนุญาตทั้งหมด",),
                            (74, 1276, 646, 1376)), 2.0)
            gallery = self.wait_text("วิดีโอ", timeout=15)
        if not re.search(r"(?<!\d)\d{1,2}:\d{2}(?!\d)", html.unescape(gallery)):
            # MediaStore อาจอัปเดตหลังหน้าเดิมสร้างรายการแล้ว: ปิดและเปิดคลัง
            # ใหม่หนึ่งครั้งเท่านั้น ไม่วนกดไม่จบและไม่เลือกภาพนิ่งแทนคลิป.
            self.tap(Target("ปิดคลังเพื่อรีเฟรช", ("ปิด",), (24, 85, 88, 150)), 1.0)
            self.tap(Target("เปิดคลังวิดีโออีกครั้ง", fallback=(536, 1190, 650, 1325)), 3.0)
            gallery = self.wait_text(":", timeout=18)
        if not re.search(r"(?<!\d)\d{1,2}:\d{2}(?!\d)", html.unescape(gallery)):
            raise TikTokPublishError("คลัง TikTok ไม่พบคลิปที่มีระยะเวลา แม้ส่งเข้า MediaStore แล้ว")
        self.tap(Target("คลิปล่าสุด", fallback=(4, 264, 239, 502)), 3.0)
        preview = self.wait_text("ถัดไป", timeout=15)
        if "ถัดไป" not in html.unescape(preview):
            raise TikTokPublishError("เลือกคลิปล่าสุดแล้วแต่หน้าพรีวิวไม่เปิด")
        self.tap(Target("ถัดไปหน้าพรีวิว", ("ถัดไป",), (368, 1448, 696, 1536)), 3.0)

    def run_showcase_flow(self, start_at: int = 2) -> dict:
        """เดินผังโชว์เคสจาก ``start_at`` โดยไม่ทำขั้นที่ผ่านแล้วซ้ำ.

        ขั้น 1 (ปลุกจอ) อยู่ใน ``run_all``. ตอน Resume จะใช้การปลุกเป็นเพียง
        prerequisite ที่ไม่ถูกนับ/รายงาน แล้วเริ่มแตะจากขั้นที่ล้มจริงทันที.
        """
        tags = []
        for tag in self.c.hashtags:
            clean = str(tag).strip().lstrip("#")
            if clean and clean not in tags:
                tags.append(clean)

        product_xml = ""
        if start_at <= 2:
            self.at("send_clip", "ส่งคลิปใบงานเข้า REDMI 15C")
            sent = self.c.send_clip()
            self.report("send_clip", "ส่งคลิปใบงานเข้า REDMI 15C", True, sent)

        if start_at <= 3:
            self.at("open_product", "ค้นและเปิดสินค้าที่เพิ่มโชว์เคสแล้ว")
            product_xml = self.open_prepared_product()
            self.report("open_product", "ค้นและเปิดสินค้าที่เพิ่มโชว์เคสแล้ว", True,
                        "ชื่อหน้าสินค้าตรงกับชื่อที่บันทึกในใบงาน")
        elif start_at == 4:
            self.at("promotion", "เปิดข้อมูลโปรโมชั่น")
            # ขั้นเปิดสินค้าผ่านแล้ว: ใช้หน้าปัจจุบันก่อน ถ้าป๊อปอัป/แอปเด้ง
            # จึงกู้กลับหน้าสินค้าเป็น prerequisite โดยไม่รายงานขั้น 3 ซ้ำ.
            product_xml = self.xml()
            if not product_detail_visible(product_xml):
                product_xml = self.open_prepared_product()

        if start_at <= 4:
            self.at("promotion", "เปิดข้อมูลโปรโมชั่น")
            product_xml, promotion_ok = self.open_promotion_panel(product_xml)
            if not promotion_ok:
                # **แผงนี้เลื่อนขึ้นมาจากขอบล่าง ไม่ได้โผล่ทันที** (แก้ 11 ก.ย. 2569)
                # ภาพตอนล้มจับได้ว่าแผงกำลังเลื่อนอยู่กลางทาง หัวข้อ
                # "ข้อมูลโปรโมชั่น" ซ้อนทับเนื้อหาหน้าสินค้าอยู่ = ถามเร็วไป
                # ไม่ใช่เปิดไม่ขึ้น — รออีกรอบก่อนตัดสินว่าล้ม
                self.c.log("  แผงโปรโมชั่นอาจยังเลื่อนไม่สุด — รอแล้วดูอีกครั้ง")
                self.c.pause(3.0)
                retry = self.wait_text("ข้อมูลโปรโมชั่น", timeout=15)
                if "ข้อมูลโปรโมชั่น" in html.unescape(retry):
                    product_xml, promotion_ok = retry, True
            if not promotion_ok:
                return self.fail("promotion", "เปิดข้อมูลโปรโมชั่น",
                                 self.why_blocked(product_xml,
                                                  "ไม่พบแผงข้อมูลโปรโมชั่น"))
            self.report("promotion", "เปิดข้อมูลโปรโมชั่น", True,
                        "เปิดแล้ว (ตรวจจากข้อความหรือปุ่ม CTA ในภาพจริง)")

        if start_at <= 5:
            self.at("create_from_product", "เริ่มสร้างวิดีโอจากหน้าสินค้า")
            if start_at == 5:
                # ความล้มเหลวอาจทำให้ bottom sheet ปิดไป แต่ไม่ต้องย้อนนับ
                # ขั้นค้นสินค้า/เปิดโปรโมชันใหม่ ให้กู้หน้าเป็นฉากหลังเท่านั้น.
                current = self.xml()
                if ("ข้อมูลโปรโมชั่น" not in html.unescape(current)
                        and not self.promotion_panel_visible()):
                    current = self.open_prepared_product()
                    current, ok = self.open_promotion_panel(current)
                    if not ok:
                        return self.fail("create_from_product", "เริ่มสร้างวิดีโอจากหน้าสินค้า",
                                         "กู้หน้าโปรโมชั่นก่อนทำขั้นเดิมไม่ได้")
            self.open_gallery_from_product()
            self.report("create_from_product", "เริ่มสร้างวิดีโอจากหน้าสินค้า", True,
                        "เลือกกล้องและยืนยันแนบสินค้าแล้ว")
            # ขั้นนี้เป็นผลยืนยันจากหน้าต่างเดียวกับขั้น 5 ไม่มี action แยก.
            self.report("anchor_name", "ตั้งชื่อสินค้าที่แนบ", True, ANCHOR_NAME)

        if start_at == 6:
            # ไม่มี action ที่ต้องทำซ้ำ: ขั้น 6 สำเร็จพร้อมขั้น 5 อยู่แล้ว.
            self.at("anchor_name", "ตั้งชื่อสินค้าที่แนบ")
            if not self.anchor_name_entered(self.xml()):
                return self.fail("anchor_name", "ตั้งชื่อสินค้าที่แนบ",
                                 "หน้าปัจจุบันไม่ยืนยันชื่อสินค้า กดซื้อเลย")
            self.report("anchor_name", "ตั้งชื่อสินค้าที่แนบ", True, ANCHOR_NAME)

        if start_at <= 7:
            self.at("pick_clip", "เลือกคลิปล่าสุดของใบงาน")
            self.pick_latest_clip()
            self.report("pick_clip", "เลือกคลิปล่าสุดของใบงาน", True,
                        "พบคลิปที่มีระยะเวลา")

        if start_at <= 8:
            self.at("editor", "เปิดหน้าก่อนโพสต์")
            editor = self.xml() if start_at == 8 else self.wait_text("ถัดไป", timeout=18)
            plain_editor = html.unescape(editor)
            if "เพิ่มคำอธิบาย" not in plain_editor:
                if "ปรับปรุงฟีเจอร์แก้ไขแล้ว" in plain_editor:
                    self.tap(Target("ตกลง", ("ตกลง",), (64, 1440, 656, 1528)), 1.2)
                self.tap(Target("ถัดไปหน้าแก้ไข", ("ถัดไป",),
                                (368, 1448, 696, 1536)), 3.0)
            if "เพิ่มคำอธิบาย" not in html.unescape(self.xml()):
                return self.fail("editor", "เปิดหน้าก่อนโพสต์", "ไม่พบช่องเพิ่มคำอธิบาย")
            self.report("editor", "เปิดหน้าก่อนโพสต์", True, "พร้อมใส่ข้อมูล")

        if start_at <= 9:
            self.at("hashtags", "ใส่แฮชแท็ก")
            editor_xml = self.xml()
            if "เพิ่มคำอธิบาย" not in html.unescape(editor_xml):
                return self.fail("hashtags", "ใส่แฮชแท็ก",
                                 "หน้าปัจจุบันไม่ใช่หน้าก่อนโพสต์ของใบงานนี้")
            self.tap(Target("เพิ่มคำอธิบาย", ("เพิ่มคำอธิบาย",),
                            (32, 179, 432, 477)), .5)
            publish_flow._clear_field(self.c)
            caption = " ".join("#" + tag for tag in tags)
            publish_flow._put_tag(self.c, caption)
            self.c.pause(1.0)
            xml = self.xml()
            if not all(publish_flow.has_text(xml, "#" + tag) for tag in tags):
                return self.fail("hashtags", "ใส่แฮชแท็ก", "ตรวจแฮชแท็กบนจอไม่ครบ")
            self.c.tag_results = [{"tag": tag, "used": True} for tag in tags]
            self.report("hashtags", "วางแฮชแท็กจากใบงาน", True, f"{len(tags)} แท็ก")

        if start_at <= 10:
            self.at("cover", "เลือกเฟรมข้อความและบันทึกหน้าปก")
            editor_xml = self.xml()
            if not all(publish_flow.has_text(editor_xml, "#" + tag) for tag in tags):
                return self.fail("cover", "เลือกเฟรมข้อความและบันทึกหน้าปก",
                                 "หน้าปัจจุบันไม่มีแฮชแท็กครบ จึงไม่แตะหน้าปก")
            self.tap(Target("แก้ไขหน้าปก", ("แก้ไขหน้าปก",), (464, 410, 688, 477)), 1.2)
            self.tap(Target("เฟรมแรกที่มีข้อความ", fallback=(42, 1200, 124, 1310)), .7)
            self.tap(Target("บันทึกหน้าปก", ("บันทึก",), (574, 74, 720, 178)), 2.0)
            self.report("cover", "เลือกเฟรมข้อความและบันทึกหน้าปก", True, "บันทึกแล้ว")

        post_xml = self.xml()
        if start_at <= 11:
            self.at("hashtag_commit", "ยืนยันแฮชแท็กสุดท้าย")
            last_tag = "#" + tags[-1]
            suggestion = self.wait_clickable(last_tag, timeout=12)
            if not suggestion:
                return self.fail("hashtag_commit", "ยืนยันแฮชแท็กสุดท้าย",
                                 f"ไม่พบคำแนะนำ {last_tag} ที่กดได้ — ไม่แตะข้อความในช่องแทน")
            point = self.c.tap_in_bounds(suggestion)
            self.c.log(f"  แตะคำแนะนำ {last_tag} ที่ {point[0]},{point[1]} (อยู่ในกรอบปุ่ม)")
            self.c.pause(2.0)
            post_xml = self.xml()
            if not all(publish_flow.has_text(post_xml, "#" + tag) for tag in tags):
                return self.fail("hashtag_commit", "ยืนยันแฮชแท็กสุดท้าย",
                                 "เลือกคำแนะนำแล้วแต่แฮชแท็กบนจอไม่ครบ")
            self.report("hashtag_commit", "ยืนยันแฮชแท็กสุดท้าย", True, last_tag)

        if start_at <= 12:
            self.at("audience", "ตรวจผู้ชมและสินค้าก่อนโพสต์")
            post_xml = self.xml()
            plain = html.unescape(post_xml)
            if "ทุกคนสามารถดูโพสต์นี้ได้" not in plain:
                self.tap(Target("การตั้งค่าผู้ชม", ("ดูโพสต์นี้ได้",),
                                (0, 970, 720, 1080)), 1.0)
                self.tap(Target("ทุกคน", ("ทุกคน",), (16, 1153, 704, 1255)), 1.5)
                post_xml = self.xml()
                plain = html.unescape(post_xml)
            if "ทุกคนสามารถดูโพสต์นี้ได้" not in plain:
                return self.fail("audience", "ตั้งผู้ชมเป็นทุกคน", "ตรวจสถานะสาธารณะไม่ได้")
            if ANCHOR_NAME not in plain:
                return self.fail("anchor_chip", "ตรวจสินค้าก่อนโพสต์",
                                 "ไม่พบชิปสินค้าชื่อ กดซื้อเลย บนหน้าก่อนโพสต์")
            self.report("audience", "ตรวจผู้ชมและสินค้าก่อนโพสต์", True,
                        "สาธารณะ · พบชิปกดซื้อเลย")

        if self.stop_before_post:
            return self.result(True, preview_ready=True, awaiting_post_approval=True,
                               message="เตรียมครบแล้วและหยุดก่อนแตะปุ่มโพสต์")
        self.at("post", "โพสต์")
        if self.post_clicked:
            return self.fail("post", "โพสต์", "ตัวป้องกันพบการพยายามกดโพสต์ซ้ำ")
        if not self.c.begin_irreversible():
            raise publish_flow.StopRequested("ผู้ใช้กด Stop ก่อนแตะปุ่มโพสต์")
        self.tap(Target("โพสต์", ("โพสต์",), (368, 1456, 696, 1544)), 0)
        self.post_clicked = True
        self.at("confirm_post", "ยืนยันผลโพสต์")
        success = self.wait_success(timeout=120)
        self.report("post", "แตะโพสต์หนึ่งครั้ง", True, "กดครั้งเดียว")
        if success:
            self.report("confirm_post", "ยืนยันผลโพสต์", True,
                        "พบโพสต์ใหม่ของใบงานบนฟีด" if success == "fresh_feed"
                        else "พบข้อความยืนยันโพสต์สำเร็จ")
            return self.result(True)

        # ---- ตัวตรวจตัวที่สอง: ไปดูตารางคลิปในโปรไฟล์ (เพิ่ม 11 ก.ย. 2569) ----
        #
        # สามทางเดิมล้มพร้อมกันทั้งหมดในการลงจริงใบแรก **ทั้งที่คลิปขึ้นแล้ว**
        #   เทียบภาพกับตัวอย่าง   ไฟล์อ้างอิงเป็นของ 3 ก.ย. TikTok เปลี่ยนหน้าไปแล้ว
        #   หาคำ "โพสต์วิดีโอแล้ว"  เป็นคำไทย อ่านไม่ออก
        #   หาโพสต์ใหม่บนฟีด       ต้องอ่านแฮชแท็กไทยครบทุกตัว จึงไม่ผ่านเช่นกัน
        #
        # ตัวนี้ดู **ยอดเล่นบนตารางคลิปของเราเอง** ซึ่งเป็นเลขอารบิกล้วน อ่านแม่น
        # คลิปใหม่แทรกหัวแถวเสมอ = ลำดับเลื่อนไปหนึ่งช่อง
        if self.new_clip_on_profile(self.tiles_before):
            self.report("confirm_post", "ยืนยันผลโพสต์", True,
                        "เห็นคลิปใหม่แทรกเป็นใบแรกในโปรไฟล์แล้ว")
            return self.result(True)

        # ---- ตรวจไม่ได้ = **ถือว่าลงแล้ว** ไม่ใช่ถือว่าล้ม ------------------
        #
        # **สองความเสี่ยงไม่เท่ากัน** (เจอจริง 11 ก.ย. 2569)
        #   บันทึกว่าล้ม ทั้งที่ขึ้นแล้ว  → ระบบลงซ้ำอีกใบ **ถอนไม่ได้**
        #   บันทึกว่าลง ทั้งที่ยังไม่ขึ้น → แค่ใบนั้นหาย เจ้าของสั่งลงใหม่ได้
        #
        # ปุ่มโพสต์ถูกแตะไปแล้วจริงตรงนี้ จึงเลือกฝั่งที่กู้คืนได้
        # แล้ว **ปิดอัตโนมัติทันที** ไม่ให้เดินใบถัดไปจนกว่าเจ้าของจะมาดูด้วยตา
        warning = ("แตะปุ่มโพสต์ไปแล้วแต่ยืนยันผลไม่ได้ — "
                   "บันทึกเป็น 'ลงแล้ว' เพื่อกันลงซ้ำ และหยุดอัตโนมัติไว้ "
                   "**ต้องเปิดโปรไฟล์ TikTok ตรวจด้วยตาว่าคลิปขึ้นจริงไหม**")
        self.report("confirm_post", "ยืนยันผลโพสต์", True, warning)
        return self.result(True, post_unverified=True, stop={
            "code": "tiktok_post_unverified", "auto_key": "tiktok_publish",
            "reason": warning, "retry": False,
        })

    # ยอดเล่นบนตารางคลิปในโปรไฟล์ เช่น "0" "39" "1.2K" — **ตัวเลขล้วน**
    PLAY_COUNT_RE = re.compile(r"^\d+(?:\.\d+)?[KMB]?$")

    def profile_tiles(self, tries: int = 2) -> list[str]:
        """เปิดโปรไฟล์ตัวเอง แล้วอ่าน **ยอดเล่นของคลิปแถวแรกๆ** ออกมาเป็นรายการ

        **ทำไมอ่านตัวเลข ไม่อ่านตัวหนังสือ** — วันนี้พิสูจน์แล้วว่าตัวอ่านภาพ
        อ่านไทยได้บ้างไม่ได้บ้าง แต่ **อ่านเลขอารบิกได้แม่นเสมอ** (วัดจริง:
        "B173.00" · "邮193.85" · "▶ 0" · "▶ 39" ถูกทุกตัว)

        ใช้เทียบก่อน/หลังโพสต์ — คลิปใหม่จะแทรกเข้ามาเป็นใบแรกเสมอ ทำให้ลำดับ
        ยอดเล่นเลื่อนไปหนึ่งช่อง นั่นคือ **ของที่มีเฉพาะตอนโพสต์สำเร็จจริง**
        ไม่ใช่คำถามที่ตอบว่า "ใช่" ได้ทั้งตอนสำเร็จและตอนล้ม (กติกาข้อ 2.3.1)
        """
        for _ in range(tries):
            try:
                self.c.run_adb("shell", "input", "tap", "648", "1520")   # แท็บโปรไฟล์
                self.c.pause(4.0)
                self.c.run_adb("shell", "input", "tap", "82", "672")     # แท็บวิดีโอ
                self.c.pause(3.5)
                xml = self.xml()
                words = re.findall(r'text="([^"]{1,12})"', html.unescape(xml))
                tiles = [w.strip() for w in words
                         if self.PLAY_COUNT_RE.match(w.strip())]
                if tiles:
                    return tiles
            except Exception as error:                        # noqa: BLE001
                self.c.log(f"  อ่านตารางคลิปในโปรไฟล์ไม่ได้: {type(error).__name__}")
            self.c.pause(2.0)
        return []

    def new_clip_on_profile(self, before: list[str]) -> bool:
        """มีคลิปใหม่แทรกเข้ามาเป็นใบแรกจริงไหม เทียบกับตอนก่อนโพสต์"""
        after = self.profile_tiles()
        if not after:
            self.c.log("  ตรวจโปรไฟล์ไม่ได้ — อ่านยอดเล่นไม่ออกสักใบ")
            return False
        self.c.log(f"  ยอดเล่นก่อนโพสต์ {before[:6]} · หลังโพสต์ {after[:6]}")
        if not before:
            return False
        # ใบใหม่แทรกหัวแถว = ของเดิมใบแรกต้องเลื่อนไปอยู่ช่องที่สอง
        return len(after) > 1 and after[1:len(before) + 1] == before[:len(after) - 1]

    def success_banner_visible(self) -> bool:
        """เทียบหัวแผงแชร์กับหลักฐานจริง เพราะข้อความสำเร็จไม่ติดใน UI XML."""
        if not SUCCESS_REFERENCE.is_file():
            return False
        try:
            from PIL import Image
            current = Image.open(io.BytesIO(
                self.c.run_adb("exec-out", "screencap", "-p"))).convert("L")
            reference = Image.open(SUCCESS_REFERENCE).convert("L")
            if current.size != reference.size:
                return False
            # เฉพาะบรรทัด "โพสต์วิดีโอแล้ว! ทุกคนสามารถดูได้ แชร์:" ไม่รวมรูปบัญชี
            box = (28, 105, 696, 166)
            ref = reference.crop(box)
            now = current.crop(box)
            ref_pixels = list(ref.get_flattened_data())
            now_pixels = list(now.get_flattened_data())
            ink = [i for i, value in enumerate(ref_pixels) if value < 90]
            paper = [i for i, value in enumerate(ref_pixels) if value > 235]
            return (bool(ink) and
                    sum(now_pixels[i] < 125 for i in ink) / len(ink) >= .82 and
                    sum(now_pixels[i] > 210 for i in paper) / len(paper) >= .90)
        except Exception:
            return False

    def wait_success(self, timeout: float = 120) -> str:
        deadline = time.time() + timeout
        notification_closed = False
        while time.time() < deadline:
            # แผงแชร์อยู่ไม่นาน จึงอ่านภาพก่อน UI dump ซึ่งบางหน้ารอได้นาน 30+ วิ
            if self.success_banner_visible():
                return "trained_banner"
            xml = self.xml()
            plain = html.unescape(xml)
            if "โพสต์วิดีโอแล้ว" in plain and "ทุกคนสามารถดูได้" in plain:
                return "ui_text"
            if fresh_post_visible(self.run, xml):
                return "fresh_feed"
            # ป๊อปอัปนี้พบจริงหลังคลิปขึ้น 99% มีเพียงปุ่มรับการแจ้งเตือนกับ X.
            # ปิด X อย่างเดียว ไม่ตอบรับสิทธิ์ และทำครั้งเดียวเพื่อไม่ให้วนแตะ.
            if (not notification_closed
                    and "รับการแจ้งเตือนเมื่อมี" in plain
                    and "อัปเดตใหม่" in plain):
                point = self.c.tap_in_bounds(_scaled((583, 624, 641, 682), self.c.screen))
                self.c.log(f"  ปิดคำชวนรับการแจ้งเตือนหลังโพสต์ที่ {point[0]},{point[1]}")
                notification_closed = True
                self.c.pause(1.0)
                continue
            self.c.pause(.7)
        return ""

    def run_all(self) -> dict:
        product_ready = showcase_prepared(self.run)
        url = str((self.run.get("tiktok_product_link") or {}).get("url")
                  or self.run.get("tiktok_product_url") or "").strip()
        if not url and not product_ready:
            return self.fail("preflight", "ตรวจข้อมูลใบงาน",
                             "ใบงานยังไม่ได้เพิ่มสินค้าเข้าโชว์เคส TikTok")
        if not self.c.hashtags:
            return self.fail("preflight", "ตรวจข้อมูลใบงาน", "ใบงานไม่มีแฮชแท็ก")
        if not self.c.wake_screen or not self.c.send_clip:
            return self.fail("preflight", "ตรวจข้อมูลใบงาน", "ไม่มีตัวปลุกจอหรือตัวส่งคลิป")

        try:
            self.at("wake", "ปลุกและปลดล็อกจอ")
            wake_message = self.c.wake_screen() or "จอพร้อม"
            if self.resume_step_no <= 1:
                self.report("wake", "ปลุกและปลดล็อกจอ", True, wake_message)
            else:
                # ปลุกจอเป็น prerequisite ของทุก Resume แต่ห้ามนับเป็นการย้อน
                # ทำขั้น 1 ใหม่: progress เริ่มที่ failed_step - 1 อยู่แล้ว.
                self.done = self.resume_step_no - 1
            # Flow ใหม่เริ่มจากสินค้าที่ตัวเตรียมตรวจและเพิ่มเข้าโชว์เคสแล้ว.
            # โหมด resume ด้านล่างยังเก็บไว้สำหรับ draft เก่าที่ค้างกลางทาง.
            if self.resume_step_id:
                if not product_ready:
                    return self.fail("preflight", "ตรวจข้อมูลใบงาน",
                                     "Resume ตามเลขขั้นใช้ได้กับสินค้าที่เพิ่มโชว์เคสแล้วเท่านั้น")
                if 3 <= self.resume_step_no <= 7:
                    self.at(self.resume_step_id, "กู้ไฟล์คลิปสำหรับขั้นที่ค้าง")
                    videos = self.run.get("videos") or []
                    item_id = str(self.run.get("item_id") or "")
                    name = publish_media.expected_phone_video_name(item_id, item_id, str(videos[0]))
                    present = self.c.run_adb("shell", "ls", "-l", f"/sdcard/Movies/autopost/{name}")
                    if name not in present.decode("utf-8", "replace"):
                        self.c.log("  ไฟล์สำหรับ Resume หาย — กู้คลิปใบเดิมและตรวจชื่อ/แฮชก่อนทำขั้นที่ค้าง")
                        self.c.send_clip()
                return self.run_showcase_flow(max(2, self.resume_step_no))
            if (product_ready and not any((self.resume_current_product,
                                           self.resume_anchor_ready,
                                           self.resume_editor_ready,
                                           self.resume_audience_ready,
                                           self.resume_profile_ready))):
                return self.run_showcase_flow()
            if self.resume_audience_ready:
                if not self.stop_before_post:
                    return self.fail("resume_audience", "กู้ขั้นตั้งผู้ชม",
                                     "โหมดกู้ขั้นผู้ชมอนุญาตเฉพาะการหยุดก่อนโพสต์")
                editor_xml = self.xml()
                plain_editor = html.unescape(editor_xml)
                if (ANCHOR_NAME not in plain_editor
                        or "ดูโพสต์นี้ได้" not in plain_editor
                        or not all(publish_flow.has_text(editor_xml, "#" + str(tag).strip().lstrip("#"))
                                   for tag in self.c.hashtags)):
                    return self.fail("resume_audience", "กู้ขั้นตั้งผู้ชม",
                                     "หน้าปัจจุบันไม่ใช่ draft ใบนี้ที่มีลิงก์สินค้าและแฮชแท็กครบ")
                self.done = 12
                self.tap(Target("การตั้งค่าผู้ชม", ("ดูโพสต์นี้ได้",),
                                (0, 970, 720, 1080)))
                self.tap(Target("ทุกคน", ("ทุกคน",), (16, 1153, 704, 1255)), 1.5)
                xml = self.xml()
                if "ทุกคนสามารถดูโพสต์นี้ได้" not in html.unescape(xml):
                    return self.fail("audience", "ตั้งผู้ชมเป็นทุกคน", "ตรวจสถานะสาธารณะไม่ได้")
                if ANCHOR_NAME not in html.unescape(xml):
                    return self.fail("anchor_chip", "ตรวจลิงก์สินค้าก่อนโพสต์",
                                     "ไม่พบชิปลิงก์สินค้าที่ตั้งชื่อไว้บนหน้าก่อนโพสต์")
                self.report("audience", "ตั้งผู้ชมเป็นทุกคน", True, "สาธารณะ")
                return self.result(
                    True, preview_ready=True, awaiting_post_approval=True,
                    message="ตั้งผู้ชมแล้ว เตรียมครบและหยุดก่อนแตะปุ่มโพสต์",
                )
            if self.resume_editor_ready:
                if not self.stop_before_post:
                    return self.fail("resume_editor", "กู้หน้าก่อนโพสต์",
                                     "โหมดกู้หน้าก่อนโพสต์อนุญาตเฉพาะการหยุดก่อนโพสต์")
                editor_xml = self.xml()
                if ("เพิ่มลิงก์" not in html.unescape(editor_xml)
                        or not all(publish_flow.has_text(editor_xml, "#" + str(tag).strip().lstrip("#"))
                                   for tag in self.c.hashtags)):
                    return self.fail("resume_editor", "กู้หน้าก่อนโพสต์",
                                     "หน้าปัจจุบันไม่ใช่ draft ใบนี้ที่มีแฮชแท็กครบ")
                self.done = 10
                self.tap(Target("เพิ่มลิงก์", ("เพิ่มลิงก์",), (0, 798, 720, 902)))
                self.tap(Target("สินค้า", ("สินค้า",), (0, 1248, 720, 1392)), 2.5)
                self.tap(Target("เพิ่มสินค้ารายการแรก", fallback=(530, 520, 688, 620)))
                self.tap(Target("ยืนยันเพิ่มสินค้า", ("เพิ่ม",), (160, 840, 560, 940)), 1.8)
                rename_xml = self.xml()
                if not self.verify_product(rename_xml, require_model=False):
                    return self.fail("attach_product", "ตรวจสินค้าก่อนแนบ",
                                     "สินค้ารายการแรกในโชว์เคสไม่ตรงใบงาน")
                self.report("attach_product", "แนบสินค้ารายการแรกที่ตรวจแล้ว", True, "ยี่ห้อ/รุ่นตรง")
                self.tap(Target("ช่องชื่อสินค้า", ("edit_anchor_name_input",),
                                (32, 680, 670, 760)), .4)
                publish_flow._clear_field(self.c)
                publish_flow._put_tag(self.c, ANCHOR_NAME)
                self.c.pause(.8)
                if not self.anchor_name_entered(self.xml()):
                    return self.fail("anchor_name", "ตั้งชื่อลิงก์สินค้า", "ตรวจชื่อใหม่บนจอไม่พบ")
                self.hide_keyboard_if_shown()
                self.tap(Target("เพิ่มลิงก์สินค้าขั้นสุดท้าย", ("edit_anchor_add_button", " เพิ่ม"),
                                (32, 1440, 688, 1536)), 2.0)
                self.report("anchor_name", "ตั้งชื่อลิงก์สินค้า", True, ANCHOR_NAME)
                xml = self.xml()
                if "ใครดูโพสต์นี้ได้บ้าง" not in html.unescape(xml):
                    self.tap(Target("การตั้งค่าผู้ชม", ("ดูโพสต์นี้ได้",),
                                    (0, 902, 720, 1013)))
                self.tap(Target("ทุกคน", ("ทุกคน",), (16, 1153, 704, 1255)), 1.5)
                xml = self.xml()
                if "ทุกคนสามารถดูโพสต์นี้ได้" not in html.unescape(xml):
                    return self.fail("audience", "ตั้งผู้ชมเป็นทุกคน", "ตรวจสถานะสาธารณะไม่ได้")
                if ANCHOR_NAME not in html.unescape(xml):
                    return self.fail("anchor_chip", "ตรวจลิงก์สินค้าก่อนโพสต์",
                                     "ไม่พบชิปลิงก์สินค้าที่ตั้งชื่อไว้บนหน้าก่อนโพสต์")
                self.report("audience", "ตั้งผู้ชมเป็นทุกคน", True, "สาธารณะ")
                return self.result(
                    True, preview_ready=True, awaiting_post_approval=True,
                    message="กู้ draft สำเร็จ เตรียมครบแล้วและหยุดก่อนแตะปุ่มโพสต์",
                )
            if self.resume_anchor_ready:
                if not self.stop_before_post:
                    return self.fail("resume_anchor", "กู้หน้าตั้งชื่อลิงก์",
                                     "โหมดกู้หน้าชื่อสินค้าอนุญาตเฉพาะการหยุดก่อนโพสต์")
                anchor_xml = self.xml()
                if (not self.verify_product(anchor_xml, require_model=True)
                        or not self.anchor_name_entered(anchor_xml)):
                    return self.fail("resume_anchor", "กู้หน้าตั้งชื่อลิงก์",
                                     "หน้าปัจจุบันไม่ใช่สินค้าตรงรุ่นที่กรอกชื่อครบแล้ว")
                self.done = 11
                self.hide_keyboard_if_shown()
                self.tap(Target("เพิ่มลิงก์สินค้าขั้นสุดท้าย", ("edit_anchor_add_button", " เพิ่ม"),
                                (32, 1440, 688, 1536)), 2.0)
                self.report("anchor_name", "ตั้งชื่อลิงก์สินค้า", True, ANCHOR_NAME)
                xml = self.xml()
                if "ใครดูโพสต์นี้ได้บ้าง" not in html.unescape(xml):
                    self.tap(Target("การตั้งค่าผู้ชม", ("ดูโพสต์นี้ได้",),
                                    (0, 902, 720, 1013)))
                self.tap(Target("ทุกคน", ("ทุกคน",), (16, 1153, 704, 1255)), 1.5)
                xml = self.xml()
                if "ทุกคนสามารถดูโพสต์นี้ได้" not in html.unescape(xml):
                    return self.fail("audience", "ตั้งผู้ชมเป็นทุกคน", "ตรวจสถานะสาธารณะไม่ได้")
                if ANCHOR_NAME not in html.unescape(xml):
                    return self.fail("anchor_chip", "ตรวจลิงก์สินค้าก่อนโพสต์",
                                     "ไม่พบชิปลิงก์สินค้าที่ตั้งชื่อไว้บนหน้าก่อนโพสต์")
                self.report("audience", "ตั้งผู้ชมเป็นทุกคน", True, "สาธารณะ")
                return self.result(
                    True, preview_ready=True, awaiting_post_approval=True,
                    message="กู้ขั้นที่ค้างสำเร็จ เตรียมครบแล้วและหยุดก่อนแตะปุ่มโพสต์",
                )
            if self.resume_profile_ready or product_ready:
                link = self.run.get("tiktok_product_link") or {}
                legacy_ready = (link.get("status") == "matched"
                                and str(link.get("confidence") or "").lower() == "high")
                if not (product_ready or legacy_ready):
                    return self.fail("resume_profile", "กู้ต่อจากโปรไฟล์",
                                     "ข้ามหน้าเปิดสินค้าไม่ได้ เพราะยังไม่ยืนยันว่าเพิ่มโชว์เคสสำเร็จ")
                # สินค้าถูกตรวจและเพิ่มโชว์เคสโดยขั้นเตรียมสินค้าแล้ว; ตอนแนบกับ
                # วิดีโอจะตรวจยี่ห้อ/รุ่นซ้ำ จึงไม่ต้องเปิด URL หรือเรียก CAPTCHA.
                self.done = 4
                xml = ""
            else:
                if self.resume_current_product:
                    product_xml = self.xml()
                    if not self.verify_current_after_human_check(product_xml):
                        return self.fail(
                            "verify_product", "ตรวจหน้าสินค้าหลังเจ้าของผ่าน CAPTCHA",
                            "หน้าปัจจุบันไม่ตรงยี่ห้อ/ขนาด/ประเภท หรือผลลิงก์เดิมไม่ได้เป็นตรง-มั่นใจสูง",
                        )
                else:
                    self.c.run_adb("shell", "am", "start", "-a", "android.intent.action.VIEW",
                                   "-d", url, CHROME_PACKAGE)
                    product_xml = self.wait_text(
                        "TCL" if "TCL" in str(self.run.get("name", "")).upper() else "฿",
                        timeout=35)
                plain_product = html.unescape(product_xml)
                if ("Verify to continue" in plain_product
                        or "Drag the puzzle piece into place" in plain_product
                        or "Security Check" in plain_product):
                    return self.fail(
                        "human_verification", "รอเจ้าของยืนยันความปลอดภัย",
                        "TikTok แสดงตัวต่อ Verify to continue ใน Chrome — "
                        "หยุดโดยไม่แตะตัวต่อ กรุณาเลื่อนตัวต่อบน REDMI 15C แล้วสั่งรันต่อ",
                        "tiktok_human_verification_required",
                    )
                if "ERR_UNKNOWN_URL_SCHEME" in product_xml or "หน้าเว็บไม่พร้อมใช้งาน" in product_xml:
                    return self.fail("open_product", "เปิดลิงก์สินค้าผ่าน Chrome",
                                     "Chrome/TikTok เปิดลิงก์ไม่สำเร็จ")
                if (not self.resume_current_product
                        and not self.verify_product(product_xml)
                        and not self.verify_current_after_human_check(product_xml)):
                    return self.fail("verify_product", "ตรวจยี่ห้อและรุ่นสินค้า",
                                     "หน้าสินค้าที่เปิดไม่ตรงกับยี่ห้อ/รุ่นในใบงาน")
                self.report("open_product", "เปิดลิงก์สินค้าผ่าน Chrome", True, "พบสินค้าตรงใบงาน")

                promotion_xml, promotion_ok = self.open_promotion_panel(product_xml)
                if not promotion_ok:
                    return self.fail("promotion", "เปิดข้อมูลโปรโมชั่น", "ไม่พบแผงข้อมูลโปรโมชั่น")
                self.report("promotion", "เปิดข้อมูลโปรโมชั่น", True, "เปิดแล้ว")

                showcase_ok, showcase_message = self.ensure_showcase(self.xml())
                if not showcase_ok:
                    return self.fail("showcase", "เพิ่มสินค้าในโชว์เคส", showcase_message)
                self.report("showcase", "เพิ่มสินค้าในโชว์เคส", True, showcase_message)

            for _ in range(3):
                self.c.run_adb("shell", "input", "keyevent", "4")
                self.c.pause(1)
                xml = self.xml()
                if "โปรไฟล์" in html.unescape(xml) and "สร้าง" in html.unescape(xml):
                    break
            if not find_bounds(xml, ("โปรไฟล์",)):
                self.c.run_adb("shell", "monkey", "-p", TIKTOK_PACKAGE,
                               "-c", "android.intent.category.LAUNCHER", "1")
                xml = self.wait_text("โปรไฟล์", "สร้าง", timeout=20)
            self.dismiss_soft_prompts()
            xml = self.xml()
            if not find_bounds(xml, ("โปรไฟล์",)):
                return self.fail("profile", "เปิดโปรไฟล์ TikTok",
                                 "กลับถึงหน้าเมนูหลัก TikTok ไม่ได้")
            self.tap(Target("โปรไฟล์", ("โปรไฟล์",), (576, 1470, 720, 1568)))
            self.dismiss_soft_prompts()
            profile = self.wait_text(ACCOUNT_HANDLE, timeout=15)
            if ACCOUNT_HANDLE not in html.unescape(profile):
                return self.fail("profile", "เปิดโปรไฟล์ TikTok", f"บัญชีไม่ใช่ {ACCOUNT_HANDLE}")
            self.report("profile", "เปิดโปรไฟล์ TikTok", True, "บัญชีถูกต้อง")

            sent = self.c.send_clip()
            self.report("send_clip", "ส่งคลิปใบงานเข้า REDMI 15C", True, sent)
            self.tap(Target("สร้าง (+)", ("สร้าง",), (288, 1470, 432, 1568)))
            create_xml = self.wait_text("อัปโหลด", timeout=15)
            if "อัปโหลด" not in html.unescape(create_xml):
                return self.fail("open_upload", "เปิดหน้าเลือกคลิป",
                                 "กดสร้างแล้วแต่ปุ่มอัปโหลดยังไม่แสดง — ไม่ใช้พิกัดสำรองบนหน้าโปรไฟล์")
            self.tap(Target("อัปโหลด", ("อัปโหลด",)))
            xml = self.wait_text("วิดีโอ", timeout=15)
            if "อนุญาตทั้งหมด" in html.unescape(xml):
                self.tap(Target("อนุญาตทั้งหมด", ("อนุญาตทั้งหมด",), (74, 1276, 646, 1376)))
                xml = self.wait_text("วิดีโอ", timeout=15)
            gallery = xml
            if not re.search(r'(?<!\d)\d{1,2}:\d{2}(?!\d)', html.unescape(gallery)):
                gallery = self.wait_text(":", timeout=20)
            if not re.search(r'(?<!\d)\d{1,2}:\d{2}(?!\d)', html.unescape(gallery)):
                return self.fail("pick_clip", "ตรวจคลิปล่าสุด",
                                 "หน้าเลือกคลิปไม่พบระยะเวลาของคลิป แม้ในเครื่องมีเพียงคลิปใบล่าสุด")
            self.tap(Target("คลิปล่าสุด", fallback=(4, 264, 239, 502)))
            self.tap(Target("ถัดไปหน้าเลือกคลิป", ("ถัดไป",), (368, 1448, 696, 1536)), 2.5)
            self.report("pick_clip", "เลือกคลิปล่าสุดของใบงาน", True, "คลิป 00:10")

            xml = self.xml()
            if "ปรับปรุงฟีเจอร์แก้ไขแล้ว" in html.unescape(xml):
                self.tap(Target("ตกลง", ("ตกลง",), (64, 1440, 656, 1528)))
            self.tap(Target("ถัดไปหน้าแก้ไข", ("ถัดไป",), (368, 1448, 696, 1536)), 2.0)
            if "เพิ่มคำอธิบาย" not in html.unescape(self.xml()):
                return self.fail("editor", "เปิดหน้าก่อนโพสต์", "ไม่พบช่องเพิ่มคำอธิบาย")
            self.report("editor", "เปิดหน้าก่อนโพสต์", True, "พร้อมใส่ข้อมูล")

            self.tap(Target("เพิ่มคำอธิบาย", ("เพิ่มคำอธิบาย",), (32, 179, 432, 477)), .5)
            publish_flow._clear_field(self.c)
            tags = []
            for tag in self.c.hashtags:
                clean = str(tag).strip().lstrip("#")
                if clean and clean not in tags:
                    tags.append(clean)
            caption = " ".join("#" + tag for tag in tags) + " "
            publish_flow._put_tag(self.c, caption)
            self.c.pause(1)
            xml = self.xml()
            if not all(publish_flow.has_text(xml, "#" + tag) for tag in tags):
                return self.fail("hashtags", "ใส่แฮชแท็ก", "ตรวจแฮชแท็กบนจอไม่ครบ")
            self.c.tag_results = [{"tag": tag, "used": True} for tag in tags]
            self.report("hashtags", "ใส่แฮชแท็กและ Space ท้ายข้อความ", True, f"{len(tags)} แท็ก")

            self.tap(Target("แก้ไขหน้าปก", ("แก้ไขหน้าปก",), (464, 410, 688, 477)))
            self.tap(Target("เฟรมแรกที่มีข้อความ", fallback=(42, 1060, 114, 1245)), .6)
            self.tap(Target("บันทึกหน้าปก", ("บันทึก",), (574, 74, 720, 178)))
            self.report("cover", "เลือกเฟรมข้อความและบันทึกหน้าปก", True, "บันทึกแล้ว")

            self.tap(Target("เพิ่มลิงก์", ("เพิ่มลิงก์",), (0, 798, 720, 902)))
            self.tap(Target("สินค้า", ("สินค้า",), (0, 1248, 720, 1392)), 2.5)
            self.tap(Target("เพิ่มสินค้ารายการแรก", fallback=(530, 520, 688, 620)))
            self.tap(Target("ยืนยันเพิ่มสินค้า", ("เพิ่ม",), (160, 840, 560, 940)), 1.8)
            rename_xml = self.xml()
            if not self.verify_product(rename_xml, require_model=False):
                return self.fail("attach_product", "ตรวจสินค้าก่อนแนบ",
                                 "สินค้ารายการแรกในโชว์เคสไม่ตรงใบงาน")
            self.report("attach_product", "แนบสินค้ารายการแรกที่ตรวจแล้ว", True, "ยี่ห้อ/รุ่นตรง")

            self.tap(Target("ช่องชื่อสินค้า", ("edit_anchor_name_input",), (32, 680, 670, 760)), .4)
            publish_flow._clear_field(self.c)
            publish_flow._put_tag(self.c, ANCHOR_NAME)
            self.c.pause(.8)
            if not self.anchor_name_entered(self.xml()):
                return self.fail("anchor_name", "ตั้งชื่อลิงก์สินค้า", "ตรวจชื่อใหม่บนจอไม่พบ")
            self.hide_keyboard_if_shown()
            self.tap(Target("เพิ่มลิงก์สินค้าขั้นสุดท้าย", ("edit_anchor_add_button",),
                            (32, 1440, 688, 1536)), 2.0)
            self.report("anchor_name", "ตั้งชื่อลิงก์สินค้า", True, ANCHOR_NAME)

            xml = self.xml()
            if "ใครดูโพสต์นี้ได้บ้าง" not in html.unescape(xml):
                self.tap(Target("การตั้งค่าผู้ชม", ("ดูโพสต์นี้ได้",),
                                (0, 902, 720, 1013)))
            self.tap(Target("ทุกคน", ("ทุกคน",), (16, 1153, 704, 1255)), 1.5)
            xml = self.xml()
            if "ทุกคนสามารถดูโพสต์นี้ได้" not in html.unescape(xml):
                return self.fail("audience", "ตั้งผู้ชมเป็นทุกคน", "ตรวจสถานะสาธารณะไม่ได้")
            if ANCHOR_NAME not in html.unescape(xml):
                return self.fail("anchor_chip", "ตรวจลิงก์สินค้าก่อนโพสต์",
                                 "ไม่พบชิปลิงก์สินค้าที่ตั้งชื่อไว้บนหน้าก่อนโพสต์")
            self.report("audience", "ตั้งผู้ชมเป็นทุกคน", True, "สาธารณะ")

            if self.stop_before_post:
                return self.result(
                    True, preview_ready=True, awaiting_post_approval=True,
                    message="เตรียมครบแล้วและหยุดก่อนแตะปุ่มโพสต์",
                )

            # One-shot guard: หลังบรรทัดนี้ไม่มีเส้นทางใดแตะปุ่มโพสต์ซ้ำ.
            if self.post_clicked:
                return self.fail("post", "โพสต์", "ตัวป้องกันพบการพยายามกดโพสต์ซ้ำ")
            if not self.c.begin_irreversible():
                raise publish_flow.StopRequested("ผู้ใช้กด Stop ก่อนแตะปุ่มโพสต์")
            self.tap(Target("โพสต์", ("โพสต์",), (368, 1456, 696, 1544)), 0)
            self.post_clicked = True
            # ห้ามเรียก report ก่อนอ่านแผงสำเร็จ เพราะ report เก็บหลักฐานและอาจใช้
            # หลายวินาทีจนแผงแชร์หายไปก่อนตัวตรวจเห็น.
            success = self.wait_success(timeout=120)
            if not success:
                self.report("post", "แตะโพสต์หนึ่งครั้ง", True, "แตะแล้ว แต่ยังยืนยันผลไม่ได้")
                return self.fail("confirm_post", "ยืนยันผลโพสต์",
                                 "แตะโพสต์แล้วแต่ไม่พบหลักฐานสำเร็จ — หยุดอัตโนมัติและห้ามลองซ้ำ",
                                 "tiktok_post_unknown")
            self.report("post", "แตะโพสต์หนึ่งครั้ง", True, "กดครั้งเดียวและพบแผงสำเร็จ")
            self.report("confirm_post", "ยืนยันผลโพสต์", True,
                        "พบข้อความโพสต์วิดีโอแล้วและทุกคนดูได้"
                        + (" (เทียบแผงจากหลักฐานที่เทรน)" if success == "trained_banner" else ""))

            warning = ""
            if self.cleanup_media:
                try:
                    warning = self.cleanup_media() or "ล้างสื่อแล้ว"
                    self.report("cleanup", "ล้างรูปและคลิปออกจาก REDMI 15C", True, warning)
                except Exception as error:  # โพสต์สำเร็จแล้ว ห้ามเปลี่ยนเป็น retry
                    warning = f"โพสต์สำเร็จ แต่ล้างสื่อไม่สำเร็จ: {error}"
                    self.report("cleanup", "ล้างรูปและคลิปออกจาก REDMI 15C", False, warning)
                    return self.result(True, "", {"code": "tiktok_cleanup_failed",
                                                  "auto_key": "tiktok_publish",
                                                  "reason": warning, "retry": False},
                                       cleanup_warning=warning)
            return self.result(True, cleanup=warning)
        except publish_flow.StopRequested as error:
            self.report("stopped", "หยุดตามคำสั่ง", False, str(error))
            return self.result(False, "ผู้ใช้กด Stop", stopped=True)
        except TikTokPublishError as error:
            return self.fail(self.current_step_id, self.current_step_name, str(error))
        except Exception as error:
            return self.fail(self.current_step_id, self.current_step_name,
                             f"{type(error).__name__}: {error}")


def run(context: publish_flow.RunContext, job: dict,
        cleanup_media: Callable[[], str] | None = None,
        stop_before_post: bool = False,
        resume_current_product: bool = False,
        resume_anchor_ready: bool = False,
        resume_editor_ready: bool = False,
        resume_audience_ready: bool = False,
        resume_profile_ready: bool = False,
        resume_step_id: str = "",
        resume_step_no: int = 0) -> dict:
    return Bot(context, job, cleanup_media, stop_before_post,
               resume_current_product, resume_anchor_ready,
               resume_editor_ready, resume_audience_ready,
               resume_profile_ready, resume_step_id, resume_step_no).run_all()
