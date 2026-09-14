"""นำสินค้า Shopee ไปค้นหาและเพิ่มเข้าโชว์เคส TikTok บนมือถือจริง

ผังนี้ไม่โพสต์ ไม่กดสั่งซื้อ และไม่แก้ข้อมูลใน TikTok ทำเพียง:

1. เลือกรูปแรกในใบงานที่เห็นสินค้าเต็มชิ้น
2. สร้างคำค้นจากชื่อสินค้า ยี่ห้อ และรุ่น แล้วค้นด้วยข้อความใน TikTok ก่อน
3. ส่งสำเนารูปเต็มไปยังโฟลเดอร์ของระบบบนมือถือเพื่อเก็บใบปัจจุบันให้ชัดเจน
4. ตรวจสินค้าสี่อันดับแรกเทียบกับชื่อ/รุ่นและรูปเต็มด้วยโมเดลภาพในเครื่อง
5. เปิดเฉพาะผลที่ตรงและมั่นใจสูง → เปิดข้อมูลโปรโมชั่น → เพิ่มในโชว์เคส
6. ถ้าไม่มีตัวที่มั่นใจ ห้ามเลือกอันดับแรกแทน ให้เก็บสถานะรอตรวจโดยไม่มี URL

ทุกการกดแอปเกิดผ่าน ``adb shell input`` ซึ่งเป็นการแตะหน้าจอ Android จริง
และผู้เรียกต้องถือบัตรคิวมือถือไว้ตลอดการรัน
"""

from __future__ import annotations

import base64
import io
import json
import os
import random
import re
import shutil
import subprocess
import tempfile
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import Callable

import httpx
from PIL import Image, ImageDraw, ImageOps

import clip_pickimg
import clip_store
import scrcpy_control


TIKTOK_PACKAGE = "com.ss.android.ugc.trill"
# พบจริงบน Xiaomi 11T Pro: แอปอ่าน PDF ตัวนี้ค้างเป็นหน้าสุดและเป็นจอดำ
# แม้สั่งเปิด TikTok แล้ว ทำให้บอทแตะจอผิดแอป จึงปิดเฉพาะตัวที่ยืนยันแล้ว
# ก่อนเริ่มค้นหาแต่ละใบ ไม่ปิดแอปอื่นแบบเดาสุ่ม
KNOWN_BLOCKING_PACKAGES = {"com.alldocumentexplor.ade"}
REMOTE_DIR = "/sdcard/Pictures/pipeline-products"
MEDIA_URI = "content://media/external/images/media"
BASE_SCREEN = (1080, 2400)

# คำที่หน้าตาเหมือนรหัสรุ่นแต่จริง ๆ เป็นเพียงสเปก. ถ้าเอาคำเหล่านี้เป็นรุ่น
# คำค้นจะกว้างจน TikTok ส่งทีวีคนละรุ่นมาเป็นอันดับแรก (เคยเกิดกับ ``4K``).
_SPEC_CODE_RE = re.compile(
    r"^(?:2K|4K|5K|8K|FHD|QHD|UHD|HDR\d*|HDMI\d*|USB\d*|PD\d*|"
    r"\d+(?:HZ|MS|NITS?|BTU|W|MAH|GBPS|TB|GB|MB))$",
    re.I,
)
_MODEL_CODE_RE = re.compile(
    r"\b(?=[A-Z0-9/-]*[A-Z])(?=[A-Z0-9/-]*\d)"
    r"[A-Z0-9]+(?:-[A-Z0-9]+)*(?:/[A-Z0-9-]+)*\b",
    re.I,
)


class TikTokLinkError(RuntimeError):
    """ผังค้นหาลิงก์เดินต่อไม่ได้โดยไม่เสี่ยงเลือกสินค้าผิด"""


class TikTokLinkStopped(TikTokLinkError):
    """ผู้ใช้กด Stop ระหว่างค้น/เพิ่มสินค้า ไม่ใช่ operational failure."""


def promo_add_button_bounds(image: Image.Image) -> tuple[int, int, int, int] | None:
    """หาปุ่มชมพูยาว ``เพิ่มในโชว์เคส`` จากภาพจริงเมื่อ UI XML ว่าง.

    TikTok บางหน้าวาด bottom sheet ด้วย canvas จึงมองเห็นข้อความบนจอแต่
    uiautomator ไม่คืน node และ OCR ภาษาไทยที่ติดตั้งอยู่ก็อ่านไม่ได้สม่ำเสมอ.
    ปุ่มนี้มีลักษณะเฉพาะเป็นแถบ TikTok-red กว้างเกินครึ่งจอในช่วงล่าง จึงใช้
    สีและรูปทรงเป็น fallback โดยไม่เดาพิกัดจากสถานะก่อนหน้า.
    """
    rgb = image.convert("RGB")
    width, height = rgb.size
    if width < 100 or height < 200:
        return None
    pixels = rgb.load()
    qualifying: list[tuple[int, int, int]] = []
    for y in range(int(height * .76), int(height * .98), 2):
        xs = []
        for x in range(int(width * .02), int(width * .98), 2):
            red, green, blue = pixels[x, y]
            if red >= 225 and green <= 105 and blue <= 145 and red - green >= 125:
                xs.append(x)
        if len(xs) * 2 >= width * .55:
            qualifying.append((y, min(xs), max(xs)))
    if len(qualifying) * 2 < height * .035:
        return None
    return (
        min(row[1] for row in qualifying),
        qualifying[0][0],
        max(row[2] for row in qualifying) + 2,
        qualifying[-1][0] + 2,
    )


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _find_adb() -> str:
    for candidate in (
        Path(__file__).resolve().parent / "tools" / "platform-tools" / "adb.exe",
        Path("C:/adb/adb.exe"),
        Path("C:/platform-tools/adb.exe"),
    ):
        if candidate.is_file():
            return str(candidate)
    found = shutil.which("adb")
    if found:
        return found
    raise TikTokLinkError("ไม่พบ adb.exe")


OLLAMA_EXE = Path(__file__).resolve().parent.parent / "_ollama" / "ollama.exe"
_ollama_started = False


def ollama_alive(timeout: float = 4.0) -> bool:
    """ตัว AI ในเครื่องตอบอยู่ไหม — ถามของที่มีเฉพาะตอนมันทำงานจริง"""
    try:
        reply = httpx.get(f"{clip_pickimg.OLLAMA_URL}/api/tags", timeout=timeout)
        return reply.status_code == 200
    except Exception:                                          # noqa: BLE001
        return False


def ensure_ollama(log=print) -> None:
    """เปิด Ollama ให้เองถ้ามันไม่ได้รันอยู่ ต่อไม่ติดจริงๆ ให้ **ฟ้องดัง**

    **เจอจริง 11 ก.ย. 2569** เครื่องบูตใหม่ตอน 10:03 น. แล้ว **ไม่มีอะไรเปิด
    Ollama กลับ** สายหาสินค้าจึงตายทั้งสายตั้งแต่เช้าโดยไม่มีใครรู้

    อาการที่เห็นคือข้อความ ``ตรวจสี่อันดับไม่ได้: [WinError 10061]`` ซึ่งซ่อน
    อยู่ลึกในผลลัพธ์ของใบงาน **ไม่มีแบนเนอร์ ไม่มีเตือนบนหน้าเว็บ** ถ้าเปิด
    สวิตช์อัตโนมัติทิ้งไว้ มันจะไล่ล้มทีละใบเงียบๆ ทั้ง 296 ใบที่เหลือ

    ตัวนี้แก้สองอย่างพร้อมกัน: **เปิดให้เอง** และ **ถ้าเปิดไม่ได้ก็บอกให้ชัด
    ว่าต้องไปทำอะไร** ไม่ใช่คืน error ของ socket ที่คนอ่านแล้วไม่รู้เรื่อง
    """
    global _ollama_started
    if ollama_alive():
        return
    if not OLLAMA_EXE.is_file():
        raise TikTokLinkError(
            f"ตัว AI ในเครื่อง (Ollama) ไม่ได้เปิดอยู่ และหาโปรแกรมไม่เจอที่ "
            f"{OLLAMA_EXE} — สายหาสินค้าทำงานไม่ได้จนกว่าจะเปิดมันก่อน")
    if not _ollama_started:
        log("ตัว AI ในเครื่อง (Ollama) ไม่ได้เปิดอยู่ — กำลังเปิดให้")
        try:
            subprocess.Popen(
                [str(OLLAMA_EXE), "serve"], cwd=str(OLLAMA_EXE.parent),
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "DETACHED_PROCESS", 0)
                | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
            )
            _ollama_started = True
        except Exception as error:                             # noqa: BLE001
            raise TikTokLinkError(
                f"เปิด Ollama ไม่สำเร็จ: {type(error).__name__}: {error}") from error
    for _ in range(20):                      # รอสูงสุด ~30 วินาที
        time.sleep(1.5)
        if ollama_alive():
            log("ตัว AI ในเครื่องพร้อมแล้ว")
            return
    raise TikTokLinkError(
        f"เปิด Ollama แล้วแต่ยังไม่ตอบที่ {clip_pickimg.OLLAMA_URL} ภายใน 30 วินาที "
        "— สายหาสินค้าหยุดไว้ก่อน ต้องไปดูที่เครื่องว่ามันขึ้นจริงไหม")


def _json_reply(text: str) -> dict:
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise TikTokLinkError("โมเดลตรวจผลค้นหาไม่คืน JSON")
    try:
        value = json.loads(text[start:end + 1])
    except ValueError as error:
        raise TikTokLinkError("อ่านผลตรวจสี่อันดับไม่ได้") from error
    return value if isinstance(value, dict) else {}


def build_search_query(product_name: str) -> str:
    """คำค้นอ่านได้สำหรับ TikTok โดยเก็บยี่ห้อ/รุ่นไว้ก่อนรายละเอียดฟุ่มเฟือย"""
    clean = re.sub(r"\s+", " ", str(product_name or "")).strip()
    # ตัดรหัสแคมเปญ/คำขายที่ขึ้นต้น แต่ไม่ตัดชื่อรุ่นซึ่งอยู่ในเนื้อสินค้าจริง
    clean = re.sub(r"^\[[^]]*]\s*", "", clean, flags=re.I)
    clean = re.sub(r"^【[^】]*】\s*", "", clean)
    clean = re.sub(r"^buy\S*\s*", "", clean, flags=re.I)
    clean = re.sub(r"^(?:NEW\s+\d{4}|HOT\s+SALE|BEST\s+SELLER)\s*", "", clean, flags=re.I)
    if not clean:
        raise TikTokLinkError("ใบงานไม่มีชื่อสินค้าให้ค้นหา")

    # TCL มีทั้งทีวี จอ และแอร์ และชื่อมักมี ``4K`` อยู่ก่อนคำว่า ``รุ่น``.
    # ของเดิมหยิบ token ตัวแรกที่มีทั้งตัวอักษรและตัวเลข จึงเคยเลือก 4K เป็นรุ่น
    # แล้วค้นเจอทีวีคนละรุ่น. ให้คะแนนรหัสที่อยู่หลังคำว่า "รุ่น" และรหัสที่มี
    # ขนาดนำหน้า (55V6C) สูงกว่า โดยกันคำสเปกออกชัดเจน.
    if re.search(r"\bTCL\b", clean, re.I):
        upper = clean.upper()
        size = (re.search(r"\b\d{2,3}(?:\s*[-–]\s*\d{2,3})?\s*นิ้ว", clean, re.I)
                or re.search(r"\b\d{2,3}(?:\.\d+)?\s*(?:INCH|INCHES)\b", clean, re.I))
        size_digits = ""
        if size:
            size_digits = re.match(r"\d{2,3}", size.group(0)).group(0)
        model_marks = [match.end() for match in re.finditer(r"(?:รุ่น|MODEL)\s*[:：-]?\s*", upper)]
        ranked: list[tuple[int, int, str]] = []
        for match in _MODEL_CODE_RE.finditer(upper):
            code = match.group(0).strip("/-")
            if _SPEC_CODE_RE.fullmatch(code):
                continue
            score = min(len(code), 25)
            if size_digits and code.startswith(size_digits):
                score += 60
            if any(0 <= match.start() - mark <= 55 for mark in model_marks):
                score += 100
            # ปี/ขนาด/กำลังไฟที่หลุดจากรายการกันคำ ไม่ควรชนะรหัสรุ่นจริง
            if code.isdigit():
                score -= 200
            ranked.append((score, -match.start(), code))
        model = max(ranked, default=(0, 0, ""))[2]
        if model and re.search(rf"\b{re.escape(model)}\s+PRO\b", clean, re.I):
            model += " PRO"
        if re.search(r"แอร์|เครื่องปรับอากาศ|\bAIR\s*CON", clean, re.I):
            kind = "แอร์"
            size = re.search(r"\b\d[\d,.-]*\s*BTU\b", clean, re.I)
        elif re.search(r"\bMONITOR\b|จอคอม", clean, re.I):
            kind = "Monitor"
        else:
            kind = "ทีวี"
        query = " ".join(part for part in ("TCL", model, kind,
                                             size.group(0) if size else "") if part)
        return query[:120]
    return clean[:140]


def choose_reference(run: dict, data_dir: Path, log: Callable[[str], None]) -> tuple[Path, dict]:
    """คืนรูปแรกตามลำดับใบงานที่เห็นสินค้าเต็ม ไม่ใช่ ``images[0]`` แบบตายตัว"""
    item_id = str(run.get("item_id") or "")
    names = [str(name) for name in (run.get("images") or []) if str(name).strip()]
    paths = [clip_store.file_path(data_dir, item_id, name) for name in names]
    paths = [path for path in paths if path.is_file()]
    if not paths:
        raise TikTokLinkError("ใบงานไม่มีรูปที่ใช้ค้นหาสินค้า")

    first_check: dict = {}
    for index, path in enumerate(paths):
        checked = clip_pickimg.score_one(path)
        if index == 0:
            first_check = checked
        raw = checked.get("raw") or {}
        full = int(raw.get("product") or 0) >= 2
        feature_panel = int(raw.get("feature") or 0) == 1
        log(f"ตรวจรูป {index + 1}/{len(paths)}: {path.name} — {checked.get('what') or 'อ่านไม่ออก'}")
        # งานค้นหาสินค้าต้องการ "ตัวสินค้าเต็มชิ้น" ไม่ใช่รูปอธิบายชิ้นส่วน
        # คะแนนรวมของ clip_pickimg ใช้คัดฉากวิดีโอและอาจติดลบเพราะมีหัวข้อ/
        # ไอคอนสเปก ทั้งที่รูปยังเหมาะมากสำหรับค้นหา (เช่น ภาพรุ่น+ตัวสินค้าชัด)
        if raw and full and not feature_panel:
            return path, {"index": index + 1, **checked}

    # อ่านภาพไม่ได้หรือไม่มีใบไหนผ่านเต็ม ๆ: ใช้รูปแรกได้ แต่ต้องส่งผลไปเป็นรอตรวจ
    return paths[0], {"index": 1, "reference_review": True, **first_check}


def analyze_four(
    reference: Path,
    first_screen: Path,
    second_screen: Path,
    product_name: str,
    work_dir: Path,
    layout: str = "visual",
) -> dict:
    """ให้โมเดลภาพในเครื่องเทียบเป้าหมายกับผล TikTok สี่อันดับแรก"""
    def panel(path: Path, size: tuple[int, int], crop: tuple[int, int, int, int] | None = None) -> Image.Image:
        image = Image.open(path).convert("RGB")
        if crop:
            # Coordinates were trained on 1080x2400; REDMI captures 720x1600.
            # PIL pads out-of-image crops with black, silently hiding products.
            width, height = image.size
            crop = tuple(round(value * (width / 1080 if index % 2 == 0 else height / 2400))
                         for index, value in enumerate(crop))
            image = image.crop(crop)
        return ImageOps.contain(image, size, Image.Resampling.LANCZOS)

    target = panel(reference, (560, 560))
    if layout == "full":
        # หน้า Shop เต็มจอ: แถวแรกอันดับ 1-2 และแถวสองอันดับ 3-4
        # Keep both columns and their text. Card heights vary; splitting rows
        # at a fixed Y can cut the model name off or assign the wrong rank.
        top = panel(first_screen, (540, 1120), (0, 390, 1080, 2380))
        lower = panel(second_screen, (540, 1120), (0, 390, 1080, 2380))
    else:
        # แผงผลค้นหาด้วยภาพ: หนึ่งแถวต่อหน้าจอ ต้องเลื่อนเพื่อดูแถวถัดไป
        top = panel(first_screen, (540, 1120), (0, 1120, 1080, 2260))
        lower = panel(second_screen, (540, 1120), (0, 1120, 1080, 2260))
    canvas = Image.new("RGB", (1680, 1220), "white")
    draw = ImageDraw.Draw(canvas)
    draw.text((15, 10), "TARGET", fill="black")
    draw.text((575, 10), "RESULTS 1-4" if layout == "full" else "RESULTS 1-2", fill="black")
    draw.text((1125, 10), "SAME RESULTS SECOND CAPTURE" if layout == "full" else "RESULTS 3-4", fill="black")
    canvas.paste(target, (0, 45))
    canvas.paste(top, (570, 45))
    canvas.paste(lower, (1120, 45))
    collage = work_dir / "tiktok-link-four-results.jpg"
    canvas.save(collage, quality=90)

    prompt = (
        "Compare the TARGET product on the left with exactly the first four TikTok Shop "
        "results. "
        + ("Center and right panels show the SAME results grid captured twice. "
           "Ranks 1,2 are top-left,top-right; ranks 3,4 are the next left,right cards. "
           "Do not count the second capture as new products. " if layout == "full" else
           "Center column is ranks 1-2; right column is ranks 3-4. ")
        +
        "Target worksheet name: " + product_name + "\n"
        "Use the worksheet name to identify the product category; a reference image may "
        "show a feature demonstration or compatible device rather than the product itself. "
        "Read the visible listing titles verbatim into titles; use an empty string if unreadable. "
        "Never invent a model or specification. Compatible phone/laptop names are not the "
        "product's own model. A listing offering multiple variants can include the target, "
        "but do not assume an unshown variant is available. Explain concrete visible evidence. "
        # ---- เกณฑ์ตัดสินสองชั้น (เจ้าของสั่ง 13 ก.ย. 2569) ------------------
        #
        # ของเดิมบังคับให้ตรงครบห้าอย่าง (ยี่ห้อ · ชนิด · รหัสรุ่น · ขนาด · ตัวเลือก)
        # ขาดข้อเดียวตอบว่าไม่ตรงทันที — เข้มเกินจริง เจ้าของเปิดภาพหลักฐานเองแล้ว
        # เห็นว่าใบ TCL 55Q7D Pro ผลอันดับ 1 คือสินค้าตัวเดียวกันเป๊ะ แต่ AI ตอบ
        # ไม่ตรงเพราะชื่อประกาศเขียน QLED ส่วนใบงานเขียน LED
        #
        # ชั้นที่ 1  **รหัสรุ่นตรง = เอาเลย** รหัสรุ่นเป็นตัวชี้ที่ชัดที่สุด ถ้าตรง
        #            ก็คือสินค้าตัวเดียวกัน ไม่ต้องไปติดคำโฆษณารอบๆ
        # ชั้นที่ 2  รหัสรุ่นไม่ตรงหรืออ่านไม่ออก -> ดูอีกสี่อย่าง และ
        #            **ต้องตรงครบทั้งสี่** ยี่ห้อ · ชนิดสินค้า · ขนาด · ตัวเลือก
        "Decide in two stages.\n"
        "STAGE 1 - model code: if a listing shows the SAME model code as the target, "
        "that listing IS the product. Choose it and answer confidence high, even when "
        "marketing words around the code differ (for example LED vs QLED, Pro vs PRO, "
        "or extra words such as New or 2025).\n"
        "STAGE 2 - only when no listing shows a matching model code, or the code is "
        "not readable: then brand, product type, size and variant must ALL FOUR agree. "
        "If all four agree, choose that listing and answer confidence medium. "
        "If even one of the four disagrees, it is NOT a match.\n"
        "Never treat a guessed model code as readable. Return one JSON object only:\n"
        '{"match":0,"confidence":"high|medium|low","reason":"short Thai reason",'
        '"titles":["","","",""]}\n'
        "match must be 1,2,3,4 for the chosen listing; use 0 when neither stage matches."
    )
    blob = base64.b64encode(collage.read_bytes()).decode("ascii")
    ensure_ollama()
    try:
        response = httpx.post(
            f"{clip_pickimg.OLLAMA_URL}/api/generate",
            timeout=180,
            json={
                "model": clip_pickimg.OLLAMA_MODEL,
                "stream": False,
                "images": [blob],
                "prompt": prompt,
                "options": {"num_predict": 240, "temperature": 0.0},
            },
        )
        response.raise_for_status()
        result = _json_reply(str(response.json().get("response") or ""))
    except Exception as error:                                  # noqa: BLE001
        # แยก "วิเคราะห์ไม่ได้" ออกจาก "วิเคราะห์แล้วไม่มีตัวตรง" ให้ชัด.
        # อย่างแรกเป็นความขัดข้องชั่วคราวและต้อง retry ใบเดิม; ถ้าบันทึกเป็น
        # pending_review ตัวอัตโนมัติจะถือว่าใบนี้ทำแล้วและไม่กลับมาลองอีก.
        return {"match": 0, "confidence": "low",
                "reason": f"ตรวจสี่อันดับไม่ได้: {error}", "titles": [],
                "analysis_error": True}

    try:
        rank = int(result.get("match") or 0)
    except (TypeError, ValueError):
        rank = 0
    result["match"] = rank if rank in (0, 1, 2, 3, 4) else 0
    result["confidence"] = str(result.get("confidence") or "low").lower()
    result["titles"] = [str(title)[:160] for title in (result.get("titles") or [])][:4]
    return result


class PhoneFlow:
    def __init__(self, serial: str, adb: str = "", log: Callable[[str], None] = print,
                 stop: Callable[[], bool] = lambda: False):
        self.serial = serial
        self.adb = adb or _find_adb()
        self.log = log
        self.stop = stop
        self.width, self.height = self._screen_size()

    def adb_run(self, *args: str, timeout: int = 30, check: bool = True) -> bytes:
        if self.stop():
            raise TikTokLinkStopped("ผู้ใช้กด Stop ระหว่างเพิ่มสินค้า TikTok")
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        try:
            done = subprocess.run(
                [self.adb, "-s", self.serial, *args], capture_output=True,
                timeout=timeout, creationflags=flags,
            )
        except subprocess.TimeoutExpired as error:
            raise TikTokLinkError(f"มือถือไม่ตอบภายใน {timeout} วินาที") from error
        if check and done.returncode:
            detail = (done.stderr or done.stdout).decode("utf-8", "replace")[:240]
            raise TikTokLinkError(detail or "ADB ทำงานไม่สำเร็จ")
        return done.stdout

    def _screen_size(self) -> tuple[int, int]:
        out = self.adb_run("shell", "wm", "size").decode("utf-8", "replace")
        found = re.search(r"(\d+)x(\d+)", out)
        return (int(found.group(1)), int(found.group(2))) if found else BASE_SCREEN

    def point(self, x: int, y: int) -> tuple[int, int]:
        return round(x * self.width / BASE_SCREEN[0]), round(y * self.height / BASE_SCREEN[1])

    def tap(self, x: int, y: int) -> None:
        px, py = self.point(x, y)
        # เยื้องเล็กน้อยเพื่อไม่กด pixel เดิมซ้ำทุกครั้ง แต่จำกัดไว้แค่ 2px
        # เพราะลูกศรสองขีดบนหน้าสินค้าเป็นเป้าหมายที่แคบมาก.
        px = max(0, min(self.width - 1, px + random.randint(-2, 2)))
        py = max(0, min(self.height - 1, py + random.randint(-2, 2)))
        self.adb_run("shell", "input", "tap", str(px), str(py))

    def tap_actual_bounds(self, bounds: tuple[int, int, int, int]) -> None:
        """แตะกึ่งกลางกรอบจริงพร้อม jitter ที่ยังอยู่ภายในปุ่ม."""
        x1, y1, x2, y2 = bounds
        radius = max(1, min(6, (x2 - x1) // 5, (y2 - y1) // 5))
        x = (x1 + x2) // 2 + random.randint(-radius, radius)
        y = (y1 + y2) // 2 + random.randint(-radius, radius)
        self.adb_run("shell", "input", "tap", str(x), str(y))

    def swipe(self, x1: int, y1: int, x2: int, y2: int, ms: int = 450) -> None:
        a, b = self.point(x1, y1), self.point(x2, y2)
        self.adb_run("shell", "input", "swipe", str(a[0]), str(a[1]), str(b[0]), str(b[1]), str(ms))

    def nodes(self) -> list[dict]:
        remote = "/sdcard/tiktok-product-link.xml"
        self.adb_run("shell", "rm", "-f", remote, check=False)
        self.adb_run("shell", "uiautomator", "dump", remote, timeout=20, check=False)
        raw = self.adb_run("shell", "cat", remote, timeout=15, check=False)
        try:
            root = ET.fromstring(raw.decode("utf-8", "replace"))
        except ET.ParseError:
            return self.ocr_nodes()
        rows = []
        for node in root.iter("node"):
            bounds = re.findall(r"\d+", node.attrib.get("bounds", ""))
            if len(bounds) != 4:
                continue
            rows.append({
                "text": node.attrib.get("text", ""),
                "desc": node.attrib.get("content-desc", ""),
                "bounds": tuple(map(int, bounds)),
            })
        return rows or self.ocr_nodes()

    def ocr_nodes(self) -> list[dict]:
        """อ่านตัวอักษรจากภาพจริงเมื่อ TikTok ไม่ส่ง Accessibility XML.

        **ใช้ตัวอ่านภาษาไทยก่อนเสมอ** (แก้ 11 ก.ย. 2569) — ของเดิมใช้ตัวอ่าน
        กลางซึ่งโมเดลรู้จักแค่จีน/อังกฤษ คอมเมนต์หัวไฟล์นี้เขียนไว้เองว่า
        *"OCR ภาษาไทยที่ติดตั้งอยู่ก็อ่านไม่ได้สม่ำเสมอ"* ซึ่งเป็นเรื่องจริง:
        วัดแล้ว "ร้านค้า" ถูกอ่านออกมาเป็น "Suusefu"

        ผลคือขั้น **ตรวจผลเพิ่มโชว์เคส** หาคำว่า "เพิ่มในโชว์เคสแล้ว" ไม่เจอ
        แล้วบันทึกใบงานเป็น error ทั้งที่กดเพิ่มไปแล้วจริง (เจอจริงใบ
        29708428217 เวลา 14:29) — สินค้าจึงไม่เคยพร้อมลงสักใบ

        ตัวอ่านไทยตัวใหม่อยู่ในสายเดียวกัน (`tiktok_publish_bot.get_thai_ocr`)
        วัดแล้วอ่านไทยได้จริง 1.4 วินาทีต่อภาพ
        """
        try:
            png = self.adb_run("exec-out", "screencap", "-p", timeout=45)
            image = Image.open(io.BytesIO(png)).convert("RGB")
        except Exception:                                      # noqa: BLE001
            return []

        try:
            import numpy as np                                  # noqa: PLC0415
            import tiktok_publish_bot as _bot                    # noqa: PLC0415
            thai = _bot.get_thai_ocr()
            if thai is not None:
                rows = []
                for coords, value, score in thai.readtext(np.array(image)) or []:
                    value = str(value).strip()
                    if not value or float(score) < .20:
                        continue
                    xs = [int(p[0]) for p in coords]
                    ys = [int(p[1]) for p in coords]
                    rows.append({"text": value, "desc": "",
                                 "bounds": (min(xs), min(ys), max(xs), max(ys))})
                if rows:
                    self.log("uiautomator อ่านจอ TikTok ไม่ได้ — "
                             f"ใช้ตัวอ่านภาษาไทยจากภาพแทน ({len(rows)} คำ)")
                    return rows
        except Exception as error:                             # noqa: BLE001
            self.log(f"ตัวอ่านภาษาไทยใช้ไม่ได้: {type(error).__name__} — "
                     "ถอยไปใช้ตัวอ่านกลาง")

        try:
            import publish_flow                                 # noqa: PLC0415
            engine = publish_flow.get_ocr_engine()
            if not engine:
                return []
            boxes, _ = engine(image)
        except Exception:                                      # noqa: BLE001
            return []
        rows = []
        for row in boxes or []:
            try:
                coords, value, score = row[0], str(row[1]).strip(), float(row[2])
                if not value or score < .30:
                    continue
                xs = [int(point[0]) for point in coords]
                ys = [int(point[1]) for point in coords]
                rows.append({"text": value, "desc": "",
                             "bounds": (min(xs), min(ys), max(xs), max(ys))})
            except (TypeError, ValueError, IndexError):
                continue
        if rows:
            self.log("uiautomator อ่านจอ TikTok ไม่ได้ — ใช้ OCR จากภาพจริงแทน")
        return rows

    def foreground_package(self) -> str:
        """ชื่อแพ็กเกจที่อยู่หน้าสุดจริง; ใช้กันแตะหน้าต่างแอปอื่นผิดตัว"""
        raw = self.adb_run(
            "shell", "dumpsys", "activity", "activities",
            timeout=30, check=False,
        ).decode("utf-8", "replace")
        found = re.search(
            r"(?:topResumedActivity|mResumedActivity)=[^\n]*?\s([\w.]+)/",
            raw,
        )
        return found.group(1) if found else ""

    def launch_tiktok(self) -> None:
        """กลับหน้า Home แล้วเปิด TikTok พร้อมยืนยันว่าแอปขึ้นหน้าสุดจริง"""
        self.adb_run("shell", "input", "keyevent", "224", check=False)
        self.adb_run("shell", "wm", "dismiss-keyguard", check=False)
        self.adb_run("shell", "input", "keyevent", "82", check=False)
        for package in KNOWN_BLOCKING_PACKAGES:
            self.adb_run("shell", "am", "force-stop", package, check=False)
        self.adb_run("shell", "input", "keyevent", "3", check=False)
        time.sleep(0.8)
        self.adb_run("shell", "am", "force-stop", TIKTOK_PACKAGE)
        self.adb_run("shell", "monkey", "-p", TIKTOK_PACKAGE,
                     "-c", "android.intent.category.LAUNCHER", "1", timeout=30)
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if self.foreground_package() == TIKTOK_PACKAGE:
                time.sleep(2.5)  # รอหน้าแรกพ้น splash ก่อนแตะแว่นขยาย
                return
            time.sleep(0.8)
        raise TikTokLinkError("เปิด TikTok แล้วแต่แอปไม่ขึ้นหน้าสุด")

    def tap_text(self, *needles: str) -> bool:
        wanted = [needle.casefold() for needle in needles if needle]
        for row in self.nodes():
            hay = (row["text"] + " " + row["desc"]).casefold()
            if not any(needle in hay for needle in wanted):
                continue
            self.tap_actual_bounds(row["bounds"])
            return True
        return False

    def promo_button_from_screen(self) -> tuple[int, int, int, int] | None:
        try:
            png = self.adb_run("exec-out", "screencap", "-p", timeout=45)
            return promo_add_button_bounds(Image.open(io.BytesIO(png)))
        except Exception:                                      # noqa: BLE001
            return None

    def wait_text(self, *needles: str, timeout: float = 12.0) -> bool:
        """รอข้อความ/คำอธิบายบนหน้าจอโดยไม่กด เพื่อกันเดินข้ามหน้าที่ยังไม่มา"""
        wanted = [needle.casefold() for needle in needles if needle]
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for row in self.nodes():
                hay = (row["text"] + " " + row["desc"]).casefold()
                if any(needle in hay for needle in wanted):
                    return True
            time.sleep(0.7)
        return False

    def capture(self, path: Path) -> None:
        png = self.adb_run("exec-out", "screencap", "-p", timeout=45)
        if not png.startswith(b"\x89PNG"):
            raise TikTokLinkError("ถ่ายหน้าผลค้นหาไม่ได้")
        path.write_bytes(png)

    @staticmethod
    def _screen_text(nodes: list[dict]) -> str:
        return " ".join(
            (row.get("text", "") + " " + row.get("desc", "")).strip()
            for row in nodes
        ).casefold()

    def dismiss_blocking_popup(self) -> bool:
        """ปิดเฉพาะป๊อปอัปที่ยืนยันได้ว่าบัง TikTok อยู่.

        ฟังก์ชันนี้ถูกเรียก *หลัง* ขั้นอ่านหน้าจอไม่พบสิ่งที่คาดไว้เท่านั้น.
        ถ้าปิดได้ ผู้เรียกต้องกลับไปอ่าน/ทำขั้นเดิมอีกหนึ่งครั้ง ไม่เดินข้ามขั้น.
        """
        nodes = self.nodes()
        # TikTok บางหน้าวาด modal ด้วย canvas แม้ XML ยังมี node ของฉากหลัง
        # จึงเสริม OCR เฉพาะตอนที่ขั้นอ่านล้มเหลว ไม่เพิ่มภาระในเส้นทางปกติ.
        ocr = self.ocr_nodes()
        if ocr:
            nodes = nodes + ocr
        screen_text = self._screen_text(nodes)

        # ป๊อปอัปรับคูปองที่พบจริงบนหน้าสินค้า. แตะ CTA เฉพาะเมื่อมีหัวข้อ
        # คูปองอยู่ใน modal เดียวกัน เพื่อไม่ให้คำว่า ``เก็บ`` ที่อื่นถูกกดผิด.
        if any(marker in screen_text for marker in (
            "รับคูปองส่วนลด", "คูปองส่วนลด", "coupon discount", "get coupon",
        )):
            for row in nodes:
                label = re.sub(
                    r"\s+", " ",
                    (row.get("text", "") + " " + row.get("desc", "")).strip(),
                ).casefold()
                if (label in {"เก็บ", "เก็บเลย", "รับคูปอง", "collect", "claim"}
                        or "เก็บคูปอง" in label):
                    self.tap_actual_bounds(row["bounds"])
                    self.log("ปิดป๊อปอัปรับคูปองแล้ว")
                    time.sleep(1.5)
                    return True
            # รู้แน่ว่าเป็น coupon modal แต่ CTA อ่านไม่ได้: Back ปิด modal
            # โดยไม่ออกจากหน้าสินค้า; ปลอดภัยกว่าการเดาพิกัดปุ่มจากภาพ.
            self.adb_run("shell", "input", "keyevent", "4", check=False)
            self.log("ปิดป๊อปอัปรับคูปองด้วยปุ่มย้อนกลับแล้ว")
            time.sleep(1.5)
            return True

        # ป๊อปอัปขอตำแหน่งบังสินค้าทั้งสี่อันดับ. ไม่จำเป็นต่อการคัดลอกลิงก์
        # และไม่ควรอนุญาตข้อมูลตำแหน่งโดยพลการ — ปิดด้วย Back ก่อน; ถ้ายังอยู่
        # ให้เปิดกล่องสิทธิ์แล้วเลือก "ไม่อนุญาต" ชัดเจน
        if "เปิดตำแหน่งที่ตั้งของคุณ" in screen_text or "location" in screen_text:
            self.adb_run("shell", "input", "keyevent", "4", check=False)
            time.sleep(1.5)
            if self.wait_text("เปิดตำแหน่งที่ตั้งของคุณ", timeout=1.5):
                if self.tap_text("ดำเนินการต่อ", "continue"):
                    time.sleep(1)
                    if not self.tap_text("ไม่อนุญาต", "don't allow", "deny"):
                        self.adb_run("shell", "input", "keyevent", "4", check=False)
                    time.sleep(1.5)
            return True
        # ---- หน้าดูรูปสินค้าเต็มจอ ไม่ใช่ป๊อปอัป (แก้ 14 ก.ย. 2569) ----------
        #
        # หน้านี้พื้นหลัง **ดำสนิท** จึงผ่านด่าน "ฉากหลังถูกหรี่" ข้างล่างเต็มๆ
        # แล้วไปแตะ (540,1570) ซึ่งบนหน้านี้คือ **กลางรูปสินค้า** ไม่ใช่ปุ่มปิด
        # — ปิดไม่ลงไม่ว่าจะลองกี่ครั้ง แล้วขั้นที่เรียกมาก็ล้มด้วยเหตุผลที่ไม่ใช่
        # สาเหตุจริง ("อ่านชื่อสินค้า TikTok ไม่ได้")
        #
        # วัดจากภาพตอนล้มจริง ใบ 25108916661 เวลา 09:12:54 (จอ 720x1600):
        #   จุดที่ใช้วัดความมืดทั้งสี่จุด = 0.0 ทุกจุด → เข้าเงื่อนไขป๊อปอัปเต็มๆ
        #   จุดที่จะไปแตะ = (360,1047) ซึ่งอยู่กลางรูป
        #
        # ปุ่มปิดจริงคือ ✕ มุมซ้ายบน ใช้ปุ่มย้อนกลับแทนได้และปลอดภัยกว่าการ
        # เดาพิกัด เพราะย้อนจากหน้าดูรูปจะกลับมาหน้าสินค้าเดิม ไม่ได้ออกจากหน้าสินค้า
        viewer_marks = ("ค้นหาสินค้าที่คล้ายกัน", "search for similar products")
        if any(mark in screen_text for mark in viewer_marks):
            self.adb_run("shell", "input", "keyevent", "4", check=False)
            time.sleep(1.5)
            later = self.nodes()
            later_ocr = self.ocr_nodes()
            if later_ocr:
                later = later + later_ocr
            if not any(mark in self._screen_text(later) for mark in viewer_marks):
                self.log("ปิดหน้าดูรูปสินค้าเต็มจอด้วยปุ่มย้อนกลับแล้ว")
                return True
            self.log("⚠️ หน้าดูรูปสินค้าเต็มจอยังไม่ปิด แม้กดย้อนกลับแล้ว")
            return False

        png = self.adb_run("exec-out", "screencap", "-p", timeout=45)
        try:
            image = Image.open(io.BytesIO(png)).convert("RGB")
        except Exception:  # noqa: BLE001 - ตรวจไม่ได้ก็ห้ามเดาสุ่มแตะหน้าจอ
            return False
        samples = [self.point(40, 120), self.point(1040, 120),
                   self.point(40, 500), self.point(1040, 500)]
        dim = sum(sum(image.getpixel(point)) / 3 for point in samples) / len(samples)
        if dim >= 100:
            return False
        # โปรโมชันที่พบจริงมีปุ่ม X กลางล่าง; แตะเฉพาะเมื่อฉากหลังถูกหรี่ชัดเจน
        self.tap(540, 1570)
        time.sleep(2)
        # **ต้องพิสูจน์ว่าปิดลงจริง ไม่ใช่แค่แตะไปแล้ว** (กติกาข้อ 2.3.1 ข้อ 2)
        # ของเดิมคืน True เสมอ ผู้เรียกจึงไปอ่านซ้ำบนจอที่ยังถูกบังอยู่เหมือนเดิม
        # แล้วรายงานว่า "อ่านไม่ได้" แทนที่จะบอกว่า "ปิดสิ่งที่บังอยู่ไม่ลง"
        shot = self.adb_run("exec-out", "screencap", "-p", timeout=45)
        try:
            after = Image.open(io.BytesIO(shot)).convert("RGB")
        except Exception:  # noqa: BLE001 - ตรวจไม่ได้ = ยังไม่รู้ผล ไม่ใช่ปิดสำเร็จ
            self.log("⚠️ แตะปุ่มปิดแล้วแต่แคปจอมาตรวจไม่ได้ — ยังไม่รู้ว่าปิดลงไหม")
            return False
        bright = sum(sum(after.getpixel(point)) / 3 for point in samples) / len(samples)
        if bright < 100:
            self.log(f"⚠️ แตะปุ่มปิดป๊อปอัปแล้วแต่ฉากหลังยังมืดอยู่ "
                     f"(สว่าง {bright:.0f} จากเกณฑ์ 100) — ปิดไม่ลง")
            return False
        return True

    def dismiss_shop_popup(self) -> bool:
        """ชื่อเดิมสำหรับผู้เรียกเก่า; ใช้ตัวตรวจป๊อปอัปกลางชุดเดียวกัน."""
        return self.dismiss_blocking_popup()

    def read_after_popup(self, step_name: str, reader: Callable[[], object]):
        """อ่านขั้นเดิมซ้ำหนึ่งรอบ เมื่อมีป๊อปอัปที่ตรวจพบและปิดได้."""
        value = reader()
        if value:
            return value
        if not self.dismiss_blocking_popup():
            return value
        self.log(f"ป๊อปอัปบังขั้น '{step_name}' — ปิดแล้ว กลับมาตรวจขั้นเดิมอีกครั้ง")
        time.sleep(1.5)
        return reader()

    def clear_and_push(self, local: Path, item_id: str) -> str:
        self.adb_run("shell", "mkdir", "-p", REMOTE_DIR)
        rows = self.adb_run(
            "shell", "content", "query", "--uri", MEDIA_URI,
            "--projection", "_id:_data", timeout=60, check=False,
        ).decode("utf-8", "replace")
        for line in rows.splitlines():
            if "/Pictures/pipeline-products/" not in line.replace("\\", "/"):
                continue
            found = re.search(r"(?:^|[, ])_id=(\d+)", line)
            if found:
                self.adb_run("shell", "content", "delete", "--uri", MEDIA_URI,
                             "--where", f"_id={found.group(1)}", check=False)
        self.adb_run("shell", "rm", "-f", f"{REMOTE_DIR}/*", check=False)
        remote = f"{REMOTE_DIR}/{item_id}{local.suffix.lower()}"
        self.adb_run("push", str(local), remote, timeout=300)
        self.adb_run("shell", "touch", remote)
        self.adb_run("shell", "content", "call", "--uri", "content://media",
                     "--method", "scan_file", "--arg", remote, timeout=60)
        time.sleep(1.5)
        return remote

    def open_search_with_text(self, query: str) -> str:
        """ค้นชื่อ/ยี่ห้อ/รุ่นก่อน แล้วเปิดผลสินค้า TikTok Shop"""
        def paste_query() -> None:
            try:
                scrcpy_control.set_clipboard(self.adb, self.serial, query, paste=True)
            except Exception as error:                         # noqa: BLE001
                # ตัวรันชั้นนอก retry เฉพาะ TikTokLinkError. ถ้าปล่อย
                # ScrcpyUnavailable หลุดตรงๆ ใบงานจะจบ error โดยไม่ได้ปิด session
                # เก่าและเริ่มใบเดิมใหม่ ทั้งที่เป็นการหลุดชั่วคราวที่พบบ่อย.
                raise TikTokLinkError(
                    f"วางคำค้นผ่าน scrcpy ไม่สำเร็จ: {type(error).__name__}: {error}"
                ) from error

        # ปลุกจอและเปิด TikTok จากหน้าแรกใหม่ทุกใบ เพื่อตัดคำค้นค้างจากใบก่อน
        self.adb_run("shell", "input", "keyevent", "224", check=False)
        self.swipe(540, 2100, 540, 400, 350)
        self.launch_tiktok()
        self.tap(1000, 160)                         # แว่นขยายหน้าแรก
        time.sleep(2)
        # ช่องค้นหาถูกโฟกัสหลังแตะแว่นขยาย ใช้ scrcpy paste เพื่อส่งภาษาไทยและ
        # เครื่องหมายรุ่นโดยไม่เสียอักขระแบบ `adb input text`
        paste_query()
        time.sleep(1)
        self.adb_run("shell", "input", "keyevent", "66")  # Enter/Search
        time.sleep(5)
        # หน้า TikTok มีวิดีโอ/แอนิเมชันตลอดเวลา บางรอบ uiautomator รายงาน
        # `could not get idle state` ทั้งที่แท็บร้านค้าอยู่บนจอจริง. ถ้าอ่านชื่อ
        # ปุ่มไม่ได้ให้แตะตำแหน่งแท็บร้านค้าจากหน้าจอ 1080x2400 ที่ตรวจแล้ว
        # ผลลัพธ์ยังต้องผ่านการเทียบ 4 อันดับก่อน จึงไม่มีทางเก็บลิงก์ผิดเพราะ
        # การแตะ fallback นี้เพียงอย่างเดียว
        if not self.read_after_popup(
            "อ่านแท็บร้านค้า",
            lambda: self.tap_text("ร้านค้า"),
        ):
            self.tap(390, 250)
        time.sleep(5)
        # เคยพบป๊อปอัปตั้งค่าแอปอ่าน PDF ค้างอยู่หน้าสุดแทน TikTok ทำให้ระบบ
        # ถ่ายภาพหน้าผิดแล้วแตะเข้าแอปเอกสาร. ตรวจแพ็กเกจก่อนทุกครั้งและลอง
        # เปิดค้นใหม่หนึ่งรอบ; ถ้ายังหลุดให้หยุดแทนการคัดลอกลิงก์ผิดสินค้า.
        if self.foreground_package() != TIKTOK_PACKAGE:
            self.log("มีแอปอื่นขึ้นทับ TikTok — เปิด TikTok และค้นใหม่อีกครั้ง")
            self.launch_tiktok()
            self.tap(1000, 160)
            time.sleep(2)
            paste_query()
            time.sleep(1)
            self.adb_run("shell", "input", "keyevent", "66")
            time.sleep(5)
            if not self.read_after_popup(
                "อ่านแท็บร้านค้า",
                lambda: self.tap_text("ร้านค้า"),
            ):
                self.tap(390, 250)
            time.sleep(5)
            if self.foreground_package() != TIKTOK_PACKAGE:
                raise TikTokLinkError("ค้นหาแล้วมีแอปอื่นขึ้นทับ TikTok ซ้ำ")
        self.dismiss_shop_popup()
        time.sleep(2)
        return "full"

    def open_rank(self, rank: int, layout: str, lower_screen: bool) -> None:
        if self.foreground_package() != TIKTOK_PACKAGE:
            raise TikTokLinkError("ก่อนเลือกสินค้า TikTok มีแอปอื่นขึ้นทับหน้าจอ")
        if layout == "visual":
            if rank in (1, 2) and lower_screen:
                self.swipe(540, 900, 540, 2180, 500)
                time.sleep(1.5)
            if rank in (3, 4) and not lower_screen:
                self.swipe(540, 1950, 540, 950, 500)
                time.sleep(1.5)
            y = 1550
        else:
            y = 850 if rank in (1, 2) else 1550
        self.tap(250 if rank in (1, 3) else 780, y)
        time.sleep(5)
        if self.foreground_package() != TIKTOK_PACKAGE:
            raise TikTokLinkError("กดสินค้าแล้วมีแอปอื่นขึ้นทับ TikTok")

    def copy_current_product_name(self, expected_name: str) -> str:
        """อ่านชื่อเต็มจากหน้าสินค้า คัดลอกลง Clipboard และคืนไว้บันทึกใบงาน."""
        found = self.read_after_popup(
            "อ่านชื่อสินค้า TikTok",
            lambda: product_title_from_nodes(self.nodes(), expected_name, self.height),
        )
        if not found:
            raise TikTokLinkError("เปิดหน้าสินค้าแล้วแต่อ่านชื่อสินค้า TikTok ไม่ได้")
        title, bounds = found
        # ชื่อย่อมี ... และลูกศรขยายอยู่มุมขวาล่างของกรอบชื่อสินค้า.
        if "..." in title or "…" in title:
            x1, y1, x2, y2 = bounds
            self.adb_run("shell", "input", "tap",
                         str(max(x1 + 1, x2 - 48)), str(max(y1 + 1, y2 - 15)))
            time.sleep(1.2)
            expanded = self.read_after_popup(
                "อ่านชื่อสินค้าแบบขยาย",
                lambda: product_title_from_nodes(
                    self.nodes(), expected_name, self.height,
                ),
            )
            if expanded and len(expanded[0]) > len(title):
                title = expanded[0]
        title = title.strip()
        if not title:
            raise TikTokLinkError("ชื่อสินค้า TikTok ที่อ่านได้เป็นค่าว่าง")
        try:
            scrcpy_control.set_clipboard(self.adb, self.serial, title, paste=False)
        except Exception as error:                              # noqa: BLE001
            raise TikTokLinkError(f"คัดลอกชื่อสินค้า TikTok ไม่สำเร็จ: {error}") from error
        self.log(f"คัดลอกชื่อสินค้า TikTok แล้ว: {title[:120]}")
        return title

    def add_current_product_to_showcase(self) -> None:
        """เปิดข้อมูลโปรโมชั่นและเพิ่มสินค้าปัจจุบันเข้าโชว์เคสพร้อมตรวจผล.

        ปุ่มลูกศรสองขีดไม่มี text/resource-id ให้เกาะ จึงใช้พิกัดที่เทรนจาก
        REDMI 15C; หลังจากนั้นทุกจุดใช้ข้อความจริงบนหน้าจอ. สำเร็จต่อเมื่อปุ่ม
        เปลี่ยนเป็น ``สำรวจสินค้าสำหรับคุณ`` หรือข้อความ ``เพิ่มในโชว์เคสแล้ว``
        เท่านั้น การที่ปุ่มเดิมหายอย่างเดียวไม่พอ เพราะอาจเป็นหน้าจอผิดหน้า.
        """
        if self.foreground_package() != TIKTOK_PACKAGE:
            raise TikTokLinkError("ก่อนเปิดข้อมูลโปรโมชั่นมีแอปอื่นขึ้นทับ TikTok")
        def promotion_state() -> str:
            state = " ".join(
                (row.get("text", "") + " " + row.get("desc", "")).strip()
                for row in self.nodes()
            )
            markers = ("สร้างตอนนี้เลย", "สำรวจสินค้าสำหรับคุณ", "เพิ่มในโชว์เคสแล้ว")
            if not any(marker in state for marker in markers):
                # The native hierarchy can contain the sheet title while the
                # successful CTA is rendered only on canvas. Read that evidence
                # before treating the add as failed or tapping anything again.
                state += " " + " ".join(str(row.get("text") or "")
                                        for row in self.ocr_nodes())
            return state

        current = promotion_state()
        if ("สร้างตอนนี้เลย" in current
                or "สำรวจสินค้าสำหรับคุณ" in current
                or "เพิ่มในโชว์เคสแล้ว" in current):
            # มีเครื่องหมายถูกบนถุงสินค้าและ CTA เปลี่ยนเป็นสร้างวิดีโอแล้ว.
            return
        visual_button = self.promo_button_from_screen()
        if "ข้อมูลโปรโมชั่น" not in current and not visual_button:
            # ถ้าหน้าสินค้าถูก modal บัง การแตะลูกศรจะไม่เกิดผล. ปิด modal
            # แล้วกลับมาเริ่ม sub-step เปิดข้อมูลโปรโมชั่นจากตำแหน่งเดิม.
            if self.dismiss_blocking_popup():
                self.log("ป๊อปอัปบังขั้น 'เปิดข้อมูลโปรโมชั่น' — ปิดแล้ว กลับมาขั้นเดิม")
                time.sleep(1.5)
                current = promotion_state()
                if ("สร้างตอนนี้เลย" in current
                        or "สำรวจสินค้าสำหรับคุณ" in current
                        or "เพิ่มในโชว์เคสแล้ว" in current):
                    return
                visual_button = self.promo_button_from_screen()
            # วัดซ้ำบน REDMI 15C 720x1600 วันที่ 6 ก.ย. 2569: จุดกึ่งกลางจริง
            # อยู่ y≈1297 หรือ 1945 บนฐาน 1080x2400. ค่าเดิม 1960 สเกลเป็น
            # 1307 และหลุดใต้ไอคอนแคบ ทำให้หน้าสินค้าถูกแต่เปิดแผงไม่ติด.
            self.tap(540, 1945)
            if not self.wait_text("ข้อมูลโปรโมชั่น", timeout=4):
                visual_button = self.promo_button_from_screen()
            if not visual_button and "ข้อมูลโปรโมชั่น" not in promotion_state():
                # modal อาจโผล่หลังแตะครั้งแรก: ปิดแล้วกลับมากดลูกศรของ
                # sub-step เดิมอีกหนึ่งครั้งเท่านั้น ไม่เริ่มใบงานใหม่.
                if self.dismiss_blocking_popup():
                    self.log("ป๊อปอัปบังหลังแตะลูกศร — ปิดแล้ว กลับมาขั้นเดิม")
                    time.sleep(1.5)
                    self.tap(540, 1945)
                    if not self.wait_text("ข้อมูลโปรโมชั่น", timeout=4):
                        visual_button = self.promo_button_from_screen()
                if not visual_button and "ข้อมูลโปรโมชั่น" not in promotion_state():
                    raise TikTokLinkError("กดลูกศรสองขีดแล้วไม่พบแผงข้อมูลโปรโมชั่น")

        tapped_visual = False
        tapped = bool(self.read_after_popup(
            "อ่านปุ่มเพิ่มในโชว์เคส",
            lambda: self.tap_text("เพิ่มในโชว์เคส"),
        ))
        # แม้ tap_text จะกดจาก UI node ได้ แต่ถ้าภาพก่อนกดยืนยันปุ่มแดงไว้แล้ว
        # ให้ใช้การที่ปุ่ม/แผงหายหลังคลิกเป็นหลักฐานสำเร็จร่วมกันได้ด้วย.
        if tapped and visual_button:
            tapped_visual = True
        if not tapped:
            visual_button = visual_button or self.promo_button_from_screen()
            if visual_button:
                self.log("UI XML อ่านปุ่มไม่ได้ — ยืนยันแถบปุ่มจากภาพจริงแล้วแตะภายในกรอบ")
                self.tap_actual_bounds(visual_button)
                tapped = tapped_visual = True
        if not tapped:
            # สินค้าที่เคยเพิ่มแล้วอาจแสดงผลสำเร็จอยู่ก่อนเริ่มขั้นนี้.
            current = promotion_state()
            if ("สำรวจสินค้าสำหรับคุณ" in current
                    or "เพิ่มในโชว์เคสแล้ว" in current
                    or "สร้างตอนนี้เลย" in current):
                return
            raise TikTokLinkError("ไม่พบปุ่มเพิ่มในโชว์เคสของสินค้าที่เลือก")

        def wait_success(timeout: float = 12) -> bool:
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                current = promotion_state()
                if ("สำรวจสินค้าสำหรับคุณ" in current
                        or "เพิ่มในโชว์เคสแล้ว" in current
                        or "สร้างตอนนี้เลย" in current):
                    return True
                # หลังแตะปุ่ม canvas ปุ่ม ``เพิ่มในโชว์เคส`` จะหาย/เปลี่ยนสถานะ.
                # ใช้เป็นหลักฐานภาพเฉพาะเมื่อเราเพิ่งยืนยันและแตะปุ่มจริงไปแล้ว.
                if tapped_visual and self.promo_button_from_screen() is None:
                    return True
                time.sleep(.7)
            return False

        if wait_success():
            return
        # อาจมี modal โผล่หลังแตะเพิ่มและบังข้อความยืนยันผล. ปิดแล้วอ่านสถานะ
        # ขั้นเดิมอีกครั้ง แต่ห้ามแตะปุ่มเพิ่มซ้ำเพราะคำสั่งแรกอาจสำเร็จไปแล้ว.
        if self.dismiss_blocking_popup():
            self.log("ป๊อปอัปบังขั้น 'ตรวจผลเพิ่มโชว์เคส' — ปิดแล้ว กลับมาตรวจขั้นเดิม")
            time.sleep(1.5)
            if wait_success(4):
                return
        raise TikTokLinkError("กดเพิ่มในโชว์เคสแล้ว แต่หน้าจอไม่ยืนยันผลสำเร็จ")

def confident_rank(vision: dict, reference_check: dict) -> int:
    """คืนอันดับที่ยืนยันได้จริง; 0 = ต้องรอคนตรวจและห้ามเลือกอัตโนมัติ."""
    try:
        rank = int((vision or {}).get("match") or 0)
    except (TypeError, ValueError):
        return 0
    # **รับทั้งสองชั้นตามที่เจ้าของสั่ง 13 ก.ย. 2569**
    #   high    = ชั้นที่ 1 รหัสรุ่นตรง -> เลือกเลย
    #   medium  = ชั้นที่ 2 ยี่ห้อ · ชนิด · ขนาด · ตัวเลือก ตรงครบทั้งสี่ -> เลือกได้
    # ของเดิมรับเฉพาะ high ถ้าไม่แก้ตรงนี้ ชั้นที่ 2 จะไม่มีวันถูกเลือกเลย
    # แม้คำสั่งจะบอกให้เลือก — คำสั่งกับตัวกรองต้องตรงกัน ไม่งั้นแก้แล้วเหมือนไม่ได้แก้
    #
    # ด่านที่กันการกดผิดตัวยังอยู่ครบ: หลังกดต้องเปิดหน้าสินค้าแล้วอ่านชื่อจริง
    # กลับมาเทียบกับใบงาน ถ้าไม่มีคำตรงกันสักคำ งานจะล้มก่อนเพิ่มโชว์เคส
    return (rank if rank in (1, 2, 3, 4)
            and str((vision or {}).get("confidence") or "").lower() in {"high", "medium"}
            and not (reference_check or {}).get("reference_review") else 0)


def product_title_from_nodes(
    nodes: list[dict], expected_name: str, screen_height: int
) -> tuple[str, tuple[int, int, int, int]] | None:
    """หาชื่อสินค้าจากแถบรายละเอียด ไม่หยิบข้อความในช่องค้นหาหรือราคา."""
    expected = {
        token.upper() for token in re.findall(r"[\w/-]+", expected_name or "")
        if len(token) >= 3 and not token.isdigit()
    }
    candidates: list[tuple[int, str, tuple[int, int, int, int]]] = []
    for row in nodes or []:
        bounds = tuple(row.get("bounds") or ())
        if len(bounds) != 4:
            continue
        x1, y1, x2, y2 = map(int, bounds)
        # จอ REDMI 15C: ชื่ออยู่ช่วงรายละเอียดครึ่งล่าง ส่วนช่องค้นหาอยู่ด้านบน.
        if not (.55 * screen_height <= y1 <= .84 * screen_height):
            continue
        value = re.sub(r"\s+", " ",
                       (str(row.get("text") or "") + " "
                        + str(row.get("desc") or "")).replace("\ufffc", " ")).strip()
        if len(value) < 18 or value.startswith(("฿", "รับ ฿")):
            continue
        tokens = {token.upper() for token in re.findall(r"[\w/-]+", value)
                  if len(token) >= 3 and not token.isdigit()}
        overlap = len(expected & tokens)
        if expected and not overlap:
            continue
        candidates.append((len(value) + overlap * 40, value, (x1, y1, x2, y2)))
    if not candidates:
        return None
    _, value, bounds = max(candidates, key=lambda row: row[0])
    return value, bounds


def find_product_link(
    serial: str,
    item_id: str,
    run: dict,
    data_dir: Path,
    *,
    adb: str = "",
    log: Callable[[str], None] = print,
    stop: Callable[[], bool] = lambda: False,
    progress: Callable[[int, str, str, bool | None, str], None] = (
        lambda _no, _step, _name, _ok, _message: None
    ),
    confirmed_rank: int = 0,
) -> dict:
    """เดินผังหนึ่งใบถึงเพิ่มโชว์เคส; ชื่อเดิมคงไว้เพื่อไม่ทำลาย API เก่า."""
    reference, reference_check = choose_reference(run, data_dir, log)
    folder = clip_store.target_dir(data_dir, item_id)
    evidence = folder / "tiktok-link"
    evidence.mkdir(parents=True, exist_ok=True)
    first_screen = evidence / "results-1-2.png"
    second_screen = evidence / "results-3-4.png"

    if stop():
        raise TikTokLinkStopped("ผู้ใช้กด Stop ก่อนเริ่มเพิ่มสินค้า TikTok")
    phone = PhoneFlow(serial, adb, log, stop)
    progress(1, "prepare", "เตรียมรูปสินค้าและส่งเข้ามือถือ", None, "")
    remote = phone.clear_and_push(reference, item_id)
    log(f"ส่งรูป {reference.name} เข้ามือถือแล้ว: {remote}")
    progress(1, "prepare", "เตรียมรูปสินค้าและส่งเข้ามือถือ", True,
             f"ส่ง {reference.name} แล้ว")
    search_query = build_search_query(str(run.get("name") or ""))
    log(f"ค้นหา TikTok ด้วยชื่อ/ยี่ห้อ/รุ่น: {search_query}")
    # หน้าจอ TikTok/เมนูแชร์อาจสะดุดจาก lock screen หรือแอปอื่นขึ้นทับ แต่ห้าม
    # เริ่มใบเดิมซ้ำในรอบอัตโนมัติ: caller จะเก็บภาพ พักใบนี้ และเดินใบถัดไป.
    # การลองใบเดิมใหม่ต้องเกิดจากผู้ใช้กด Reset หลังตรวจหลักฐานแล้วเท่านั้น.
    last_error: Exception | None = None
    for flow_attempt in range(1, 2):
        try:
            progress(2, "search", "เปิด TikTok และค้นหาชื่อ/ยี่ห้อ/รุ่น", None,
                     search_query)
            layout = phone.open_search_with_text(search_query)
            progress(2, "search", "เปิด TikTok และค้นหาชื่อ/ยี่ห้อ/รุ่น", True,
                     search_query)
            progress(3, "results_1_2", "เก็บภาพผลค้นหาอันดับ 1–2", None, "")
            phone.capture(first_screen)
            progress(3, "results_1_2", "เก็บภาพผลค้นหาอันดับ 1–2", True,
                     first_screen.name)
            if layout == "visual":
                phone.swipe(540, 1950, 540, 950, 500)
                time.sleep(2)
            progress(4, "results_3_4", "เก็บภาพผลค้นหาอันดับ 3–4", None, "")
            phone.capture(second_screen)
            progress(4, "results_3_4", "เก็บภาพผลค้นหาอันดับ 3–4", True,
                     second_screen.name)

            progress(5, "analyze", "ตรวจความตรงของสินค้า 4 อันดับ", None, "")
            vision = analyze_four(
                reference, first_screen, second_screen,
                str(run.get("name") or ""), evidence, layout,
            )
            if vision.get("analysis_error"):
                raise TikTokLinkError(str(vision.get("reason") or "โมเดลวิเคราะห์ผลไม่ได้"))
            selected = confident_rank(vision, reference_check)
            # ---- เจ้าของยืนยันเองว่าอันดับไหนใช่ -> เชื่อคน ไม่เชื่อ AI -------
            #
            # เจ้าของสั่ง 13 ก.ย. 2569 หลังเปิดภาพหลักฐานดูเองแล้วเห็นว่า AI
            # อ่านพลาด — ใบ TCL 55Q7D Pro ผลอันดับ 1 คือสินค้าตัวเดียวกันเป๊ะ
            # แต่ AI ตอบว่าไม่ตรงเพราะไปติดคำว่า QLED กับ LED ในชื่อประกาศ
            #
            # **ยังเดินขั้นที่เหลือครบเหมือนเดิมทุกขั้น** คนแทนที่แค่ "การตัดสินว่า
            # อันไหนใช่" ไม่ได้ข้ามการเปิดหน้าสินค้าและอ่านชื่อจริงกลับมาเทียบ
            # ซึ่งเป็นด่านที่กันการกดโดนสินค้าผิดอยู่แล้ว — ถ้าผลค้นหาสลับที่จน
            # อันดับที่ยืนยันไว้กลายเป็นของคนละตัว ชื่อบนหน้าจะไม่มีคำตรงกับใบงาน
            # แล้วงานจะล้มก่อนถึงขั้นเพิ่มโชว์เคส
            # อ่านจากใบงานได้ด้วย ผู้เรียกจึงไม่ต้องแก้อะไรเลย — ตัวเรียกจริง
            # อยู่ใน app.py ซึ่งเป็นของสายกลาง
            try:
                picked = int(confirmed_rank
                             or (run.get("tiktok_product_link") or {}).get("confirmed_rank")
                             or 0)
            except (TypeError, ValueError):
                picked = 0
            if picked in (1, 2, 3, 4):
                log(f"เจ้าของยืนยันเองว่าเป็นอันดับ {picked} "
                    f"(AI ตอบ {selected or 0}) — ใช้ตามที่เจ้าของเลือก")
                selected = picked
                vision = dict(vision or {})
                vision["confidence"] = "human_confirmed"
                vision["reason"] = (f"เจ้าของเปิดภาพหลักฐานแล้วยืนยันเองว่าเป็น"
                                    f"อันดับ {picked}")
            if not selected:
                # ไม่มีตัวที่ยืนยันได้ = จบแบบรอตรวจ ไม่ใช่ operational error.
                # ห้ามเปิดอันดับแรกและห้ามคัดลอก URL มาเป็นหลักฐานเท็จ.
                log(f"ตรวจสี่อันดับ: {vision.get('reason') or '-'} — "
                    "ยังไม่มีตัวที่มั่นใจ จึงไม่เลือกสินค้าและค้างรอตรวจ")
                progress(5, "analyze", "ตรวจความตรงของสินค้า 4 อันดับ", True,
                         str(vision.get("reason") or "ไม่พบตัวที่มั่นใจ"))
                progress(6, "review", "หยุดใบนี้ไว้รอตรวจสินค้า", False,
                         str(vision.get("reason") or "ไม่พบสินค้าที่มั่นใจ"))
                return {
                    "status": "pending_review",
                    "label": "รอตรวจ",
                    "showcase_added": False,
                    "selected_rank": 0,
                    "matched_rank": 0,
                    "confidence": vision.get("confidence") or "low",
                    "reason": str(vision.get("reason") or "")[:400],
                    "result_titles": vision.get("titles") or [],
                    "search_query": search_query,
                    "reference_image": reference.name,
                    "reference_index": reference_check.get("index") or 1,
                    "reference_check": reference_check,
                    "results_images": [str(first_screen.relative_to(folder)),
                                       str(second_screen.relative_to(folder))],
                    "results_layout": layout,
                    "updated_at": _now(),
                }
            log(f"ตรวจสี่อันดับ: {vision.get('reason') or '-'} — "
                f"มั่นใจว่าสินค้าตรงอันดับ {selected}")
            progress(5, "analyze", "ตรวจความตรงของสินค้า 4 อันดับ", True,
                     f"ตรงอันดับ {selected}")
            progress(6, "open_product", "เปิดสินค้าและคัดลอกชื่อเต็ม", None, "")
            phone.open_rank(selected, layout, lower_screen=(layout == "visual"))
            product_title = phone.copy_current_product_name(str(run.get("name") or ""))
            progress(6, "open_product", "เปิดสินค้าและคัดลอกชื่อเต็ม", True,
                     product_title[:180])
            progress(7, "showcase", "เพิ่มสินค้าเข้าโชว์เคส", None, "")
            phone.add_current_product_to_showcase()
            progress(7, "showcase", "เพิ่มสินค้าเข้าโชว์เคส", True,
                     f"เพิ่มอันดับ {selected} แล้ว")
            break
        except TikTokLinkStopped:
            raise
        except TikTokLinkError as error:
            last_error = error
            raise
    else:                                                       # pragma: no cover - กันชนเชิงโครงสร้าง
        raise TikTokLinkError(str(last_error or "ค้นหาลิงก์ไม่สำเร็จ"))
    return {
        "status": "showcase_added",
        "label": "เพิ่มโชว์เคสแล้ว",
        "showcase_added": True,
        "tiktok_product_name": product_title,
        "selected_rank": selected,
        "matched_rank": selected,
        "confidence": vision.get("confidence") or "low",
        "reason": str(vision.get("reason") or "")[:400],
        "result_titles": vision.get("titles") or [],
        "search_query": search_query,
        "reference_image": reference.name,
        "reference_index": reference_check.get("index") or 1,
        "reference_check": reference_check,
        "results_images": [str(first_screen.relative_to(folder)), str(second_screen.relative_to(folder))],
        "results_layout": layout,
        "updated_at": _now(),
    }
