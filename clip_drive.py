"""ยกงานเจนคลิปขึ้น Google Drive — จัด 4 หมวด **สองมุมมองพร้อมกัน**

ต่อผ่าน Google Drive for Desktop ที่เมาต์ไดรฟ์ `G:` ไว้แล้ว — คัดลอกไฟล์ลงพาธปกติ
แล้วตัว Drive อัปขึ้นคลาวด์เอง ไม่ต้องใช้ API ไม่ต้องขอโทเคน ไม่มีโควตาให้เผา

**โครงบน Drive** (18 ส.ค. 2026 ผู้ใช้สั่ง: "มีโฟลเดอร์สำหรับเก็บ 1.prompt /
2.storyboard / 3.clip / 4.ข้อมูลการโพสต์ (ผ่านช่องทางไหนเวลาเท่าไร)" แล้วสั่งเพิ่มว่า
"เก็บ 2 แบบเลย พื้นที่มันเหลือ")

    <โฟลเดอร์ที่ตั้งไว้>/pipeline-studio/
        สารบัญ.md                        ทุกสินค้า + สถานะครบ 4 หมวด
        บันทึกการโพสต์.md                 ทุกโพสต์ทุกสินค้า เรียงตามเวลา

        ตามสินค้า/                        ← มุมมอง ก: สินค้าหนึ่งชิ้นอยู่ที่เดียวครบ
            <ชื่อสินค้า>-<item_id>/
                สรุป.md · run.json · detail.txt
                1-prompt/                คำสั่ง-flow.md · บทพูด.md + ของดิบจาก GPT
                2-storyboard/            ภาพสตอรีบอร์ด + คำตอบดิบ
                3-clip/                  คลิปที่เจนได้
                4-posting/               การโพสต์.md · publish.json
                0-รูปสินค้า/              (เฉพาะเมื่อเปิด clipdrive_images)

        ตามหมวด/                          ← มุมมอง ข: อยากดูของประเภทเดียวกันทั้งหมด
            1-prompt/<ชื่อสินค้า>-<id>.md
            2-storyboard/<ชื่อสินค้า>-<id>/*.png
            3-clip/<ชื่อสินค้า>-<id>__clip.mp4
            4-posting/<ชื่อสินค้า>-<id>.md

**ทำไมเก็บสองมุมมอง** — คำถามที่ใช้จริงมีสองแบบและตอบด้วยโครงเดียวไม่ได้ทั้งคู่:
"สินค้าชิ้นนี้มีอะไรบ้าง" (ต้องการมุมมอง ก) กับ "ขอดูคลิปทั้งหมดที่มี" (ต้องการมุมมอง ข)
ผู้ใช้ตัดสินให้เก็บทั้งคู่เพราะพื้นที่เหลือเยอะ (ใช้ไป 1.23 GB จาก 20 TB) ต้นทุนคือ
ไฟล์ใหญ่ถูกคัดลอกสองชุด (คลิป 40 MB → 80 MB) ซึ่งไม่มีนัยสำคัญ

ของดิบที่เครื่องอ่าน (`run.json` `prompts.json` `raw` ต่างๆ) เก็บ **เฉพาะมุมมอง ก**
ไม่ซ้ำในมุมมอง ข เพราะมุมมอง ข มีไว้ให้คนเปิดดู ไม่ใช่ให้เครื่องอ่าน

**ทำไมยกตามหลัง ไม่เขียนลง Drive ตรงๆ** — `G:` เป็นไดรฟ์เสมือน ถ้าโปรแกรม Drive
ปิด/อัปเดตตัวเอง ไดรฟ์หายไปทั้งตัว ถ้าสายเจนคลิปเขียนลงตรงนั้น คลิปที่เพิ่งจ่าย
เครดิตไป 15 หน่วยจะเก็บไม่ได้ ดิสก์ในเครื่องจึงยังเป็นตัวหลัก

**วัดจริง 18 ส.ค. 2026 บนเครื่องนี้** เขียน 5 MB ลง G: = 0.022 วิ · เขียน json เล็ก
18 ไฟล์ = 0.372 วิ · `Path.replace()` แบบ atomic ใช้ได้ · เนื้อหาภาษาไทยไม่เพี้ยน

    python clip_drive.py status          ตั้งไว้ที่ไหน ไดรฟ์พร้อมไหม ค้างกี่ชิ้น
    python clip_drive.py sync            ยกทุกชิ้นที่ยังไม่ขึ้น (ซ้ำได้ ไม่ยกของเดิม)
    python clip_drive.py sync <item_id>  ยกเฉพาะชิ้นเดียว
    python clip_drive.py verify          ตรวจว่าของบน Drive ยังครบและขนาดตรง
    python clip_drive.py watch           เฝ้ายกให้เองทุก 2 นาที
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import time
import urllib.parse
import zlib
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

PRODUCTS_DIR = "shopee_products"
# งานที่ผู้ใช้ติ๊กว่า "ทำแล้ว" ถูก **ย้าย** ทั้งโฟลเดอร์มาที่นี่ (clip_store.mark_done)
# ถ้าตัวยกขึ้น Drive มองแต่ PRODUCTS_DIR งานที่ทำเสร็จแล้วจะหายไปจาก Drive เงียบๆ
# — 25 ส.ค. 2026 เจอจริง 9 ชิ้นมีคลิปครบแต่สารบัญขึ้นว่า 0 ทุกช่อง
DONE_PRODUCTS_DIR = "shopee_products_done"
# ตั้งแต่ 27 ส.ค. 2569 งานถูกแยกโฟลเดอร์ตามสถานะอีก 7 อัน (ผู้ใช้สั่ง)
# **ต้องไล่ให้ครบทุกอัน** ไม่งั้นงานที่ย้ายไป clips/ จะหายจาก Drive เงียบๆ
# แบบเดียวกับที่เคยเกิดกับโฟลเดอร์ done เมื่อ 25 ส.ค. (9 ชิ้นสารบัญขึ้น 0)
STATE_PRODUCT_DIRS = ("clips", "clipsfb", "clipstiktok",
                      "waitstory", "waitclips", "waitclipsfb", "waitclipstiktok")
ALL_PRODUCT_DIRS = (DONE_PRODUCTS_DIR, *STATE_PRODUCT_DIRS, PRODUCTS_DIR)
STATE_NAME = "clip_drive_state.json"
CONFIG_NAME = "config.json"

# ค่าตั้งต้น = โฟลเดอร์ที่ผู้ใช้ส่งลิงก์มา 18 ส.ค. 2026
# https://drive.google.com/drive/folders/1zt2k_GbTo9P0S-OMUF1AEDOvFuN6Glvm
# ยืนยันแล้วว่าคือโฟลเดอร์ "Identify group post facebook" ของบัญชี komchane9@gmail.com
DEFAULT_FOLDER = r"G:\My Drive\Identify group post facebook"
DEFAULT_SUBDIR = "pipeline-studio"

# เลขรุ่นของโครงโฟลเดอร์ — ขยับเมื่อไรของเก่าบน Drive จะถูกรื้อแล้วยกใหม่ให้ตรงโครง
# ถ้าไม่มีเลขนี้ โครงเก่าจะค้างปนกับโครงใหม่โดยไม่มีใครรู้ว่าอันไหนของจริง
LAYOUT_VERSION = 3

INDEX_FILE = "สารบัญ.md"
POSTING_LOG_FILE = "บันทึกการโพสต์.md"
SUMMARY_FILE = "สรุป.md"
# หน้าเว็บสำหรับกดดูทุกอย่าง — Google Drive ไม่แสดงผล .md ให้ แต่ .html
# ดับเบิลคลิกจากคอมแล้วเปิดในเบราว์เซอร์ได้ทันที และกดลิงก์ต่อไปหาคลิปได้จริง
BROWSE_FILE = "เปิดดู.html"

BY_PRODUCT = "ตามสินค้า"
BY_CATEGORY = "ตามหมวด"

PROMPT_DIR = "1-prompt"
STORYBOARD_DIR = "2-storyboard"
CLIP_DIR = "3-clip"
POSTING_DIR = "4-posting"
IMAGE_DIR = "0-รูปสินค้า"
CATEGORY_DIRS = (PROMPT_DIR, STORYBOARD_DIR, CLIP_DIR, POSTING_DIR)

# ไฟล์เดี่ยวในโฟลเดอร์สินค้า -> หมวดปลายทาง ("" = วางที่รากของโฟลเดอร์สินค้า)
FILE_MAP = {
    "prompts.json": PROMPT_DIR,
    "script.json": PROMPT_DIR,
    "gpt-flow.md": PROMPT_DIR,
    "gpt-script.md": PROMPT_DIR,
    "gpt-storyboard.md": STORYBOARD_DIR,
    "run.json": "",
    "detail.txt": "",
}
# โฟลเดอร์ย่อยในเครื่อง -> หมวดปลายทาง
DIR_MAP = {
    "storyboard": STORYBOARD_DIR,
    "video": CLIP_DIR,
}
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".webp", ".png"}

# ชื่อช่องทางที่อ่านออก — คีย์ตรงกับ clip_store.PUBLISH_TARGETS
TARGET_NAMES = {
    "facebook_reels": "Facebook Reels",
    "shopee_video": "Shopee Video",
    "tiktok": "TikTok",
}
STATUS_NAMES = {
    "pending": "⏳ รอโพสต์",
    "posted": "✅ โพสต์แล้ว",
    "failed": "❌ ล้มเหลว",
}


class DriveUnavailable(RuntimeError):
    """ไดรฟ์ปลายทางเข้าไม่ถึง — ไม่ใช่ความผิดของข้อมูล ลองใหม่ทีหลังได้"""


# ------------------------------------------------------------------ ที่อยู่

def data_dir() -> Path:
    """โฟลเดอร์ data — รับ STUDIO_DATA_DIR เหมือน studio_shared

    ต้องรับด้วย ไม่งั้นเวลาเทสที่ชี้ data ไปที่อื่น ตัวนี้จะยังไปอ่านของจริง
    แล้วเผลอยกของจริงขึ้น Drive ระหว่างเทส
    """
    name = os.environ.get("STUDIO_DATA_DIR", "data").strip() or "data"
    path = Path(name)
    return path if path.is_absolute() else BASE_DIR / name


def _config(root: Path) -> dict:
    try:
        return json.loads((Path(root) / CONFIG_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def enabled(root: Path) -> bool:
    return bool(_config(root).get("clipdrive_enabled", True))


def include_images(root: Path) -> bool:
    return bool(_config(root).get("clipdrive_images", False))


def base_folder(root: Path) -> Path:
    config = _config(root)
    return Path(str(config.get("clipdrive_folder") or DEFAULT_FOLDER).strip()
                or DEFAULT_FOLDER)


def target_root(root: Path) -> Path:
    """โฟลเดอร์ของเราบน Drive — อยู่ **ข้างใน** โฟลเดอร์ที่ผู้ใช้ชี้มาอีกชั้น

    ไม่เทลงโฟลเดอร์ฐานตรงๆ เพราะที่นั่นมีของโปรเจกต์อื่นปนอยู่แล้ว
    """
    sub = str(_config(root).get("clipdrive_subdir", DEFAULT_SUBDIR)).strip()
    return base_folder(root) / (sub or DEFAULT_SUBDIR)


def available(root: Path) -> tuple[bool, str]:
    """ปลายทางพร้อมเขียนไหม — เช็ค **โฟลเดอร์ฐาน** ไม่ใช่โฟลเดอร์ของเรา

    ต้องเช็คโฟลเดอร์ฐาน เพราะโฟลเดอร์ของเรายังไม่มีตอนรันครั้งแรก ถ้าเช็คผิดชั้น
    จะแยกไม่ออกระหว่าง "Drive ไม่ได้เปิด" กับ "ยังไม่เคยยกอะไรขึ้นไป" แล้วจะเผลอ
    สร้างโฟลเดอร์ลงดิสก์คนละที่ตอนไดรฟ์หาย
    """
    base = base_folder(root)
    try:
        if not base.is_dir():
            return False, f"ไม่พบโฟลเดอร์ปลายทาง {base} — โปรแกรม Google Drive เปิดอยู่ไหม"
    except OSError as error:
        return False, f"ถามที่อยู่ปลายทางไม่ได้: {error}"
    try:
        target_root(root).mkdir(parents=True, exist_ok=True)
    except OSError as error:
        return False, f"สร้างโฟลเดอร์บนไดรฟ์ไม่ได้: {error}"
    return True, "พร้อมใช้งาน"


# ------------------------------------------------------------------ สถานะ

def state_path(root: Path) -> Path:
    return Path(root) / STATE_NAME


def load_state(root: Path) -> dict:
    try:
        data = json.loads(state_path(root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    data.setdefault("items", {})
    return data


def save_state(root: Path, state: dict) -> None:
    """เขียนแบบ temp+replace — ตายกลางคันแล้วต้องไม่เหลือไฟล์สถานะที่อ่านไม่ออก

    ถ้าไฟล์นี้พัง ระบบจะคิดว่ายังไม่เคยยกอะไรขึ้นเลย แล้วยกซ้ำทั้งหมดใหม่
    """
    path = state_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(state, ensure_ascii=False, indent=2, default=str),
                    encoding="utf-8")
    temp.replace(path)


# ------------------------------------------------------------------ ชื่อไฟล์

_BAD_CHARS = re.compile(r'[\\/:*?"<>|\r\n\t]+')


def safe_name(text: str, limit: int = 60) -> str:
    """ชื่อโฟลเดอร์ที่ทั้ง Windows และ Drive รับได้

    ชื่อสินค้า Shopee มีทั้ง `/` `|` `?` และอิโมจิ เอาไปตั้งชื่อโฟลเดอร์ตรงๆ ไม่ได้
    จุดหรือช่องว่างท้ายชื่อก็ห้าม — Windows ตัดทิ้งเงียบๆ แล้วชื่อจะไม่ตรงกับที่จำไว้
    ในไฟล์สถานะ ผลคือรอบหน้าจะคิดว่าโฟลเดอร์หาย แล้วยกขึ้นใหม่ทั้งชุดทุกครั้ง
    """
    clean = _BAD_CHARS.sub(" ", str(text or "")).strip()
    clean = re.sub(r"\s+", " ", clean)[:limit].strip()
    clean = clean.rstrip(". ")
    return clean or "ไม่มีชื่อ"


def folder_name(run: dict, item_id: str) -> str:
    """ชื่อโฟลเดอร์บน Drive — เอาชื่อสินค้านำ เพราะเปิดจากมือถือแล้วต้องอ่านออก

    ต่อท้ายด้วย item_id เสมอ กันสินค้าคนละชิ้นชื่อซ้ำกันแล้วเขียนทับกันเอง
    """
    return f"{safe_name(run.get('name') or '')}-{item_id}"


# ------------------------------------------------------------------ คัดลอก

def source_dir(root: Path, item_id: str) -> Path:
    """โฟลเดอร์ต้นทางของสินค้าชิ้นนี้ — **มองทั้งที่กำลังทำและที่ทำเสร็จแล้ว**

    ห้ามต่อพาธ `PRODUCTS_DIR / item_id` ตรงๆ ที่ไหนอีก งานที่ติ๊กว่าทำแล้วถูกย้าย
    ออกไปโฟลเดอร์ done ตัวที่ต่อพาธเองจะมองไม่เห็นแล้วรายงานว่า "ไม่พบโฟลเดอร์"
    """
    for folder_name_ in ALL_PRODUCT_DIRS:
        folder = Path(root) / folder_name_ / str(item_id)
        if folder.is_dir():
            return folder
    return Path(root) / PRODUCTS_DIR / str(item_id)


def all_sources(root: Path) -> list[tuple[str, Path]]:
    """สินค้าทุกชิ้นในเครื่อง ทั้งที่กำลังทำและทำเสร็จแล้ว เรียงตามรหัส

    ถ้ารหัสเดียวกันมีทั้งสองที่ (เกิดได้ตอนย้ายค้างกลางคัน) เอาตัวที่กำลังทำ
    เป็นหลัก เพราะเป็นตัวที่ระบบเขียนของใหม่ลงไป
    """
    found: dict[str, Path] = {}
    for folder_name_ in ALL_PRODUCT_DIRS:    # ตัวหลังเขียนทับตัวหน้าถ้ารหัสซ้ำ
        base = Path(root) / folder_name_
        if not base.is_dir():
            continue
        for folder in base.iterdir():
            if folder.is_dir():
                found[folder.name] = folder
    return sorted(found.items())


def _link(label: str, target: str) -> str:
    """ลิงก์แบบ markdown ที่ชี้ไปไฟล์บน Drive ด้วยพาธสัมพัทธ์

    ต้องเข้ารหัสช่องว่างและอักขระพิเศษเป็น %xx ไม่งั้นตัวเปิดไฟล์จะตัดลิงก์
    ตรงช่องว่างแรก — ชื่อสินค้าของเรามีช่องว่างแทบทุกชิ้น
    """
    safe = urllib.parse.quote(target.replace("\\", "/"), safe="/#")
    clean = str(label).replace("|", "／").replace("[", "(").replace("]", ")")
    return f"[{clean}]({safe})"


def _fingerprint(path: Path) -> str:
    stat = path.stat()
    return f"{stat.st_size}:{stat.st_mtime_ns}"


def _copy(src: Path, dst: Path) -> int:
    """คัดลอกแล้ว **ตรวจขนาดปลายทาง** ก่อนนับว่าสำเร็จ

    ไดรฟ์เต็มหรือหลุดกลางคัน `copy2` ไม่โยน error เสมอไป ปล่อยผ่านแล้วไฟล์สถานะจะจดว่า
    ยกขึ้นแล้วทั้งที่ของบน Drive ขาด — พังเงียบแบบที่หาสาเหตุยากที่สุด
    """
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    want = src.stat().st_size
    got = dst.stat().st_size
    if got != want:
        raise OSError(f"คัดลอกแล้วขนาดไม่ตรง: {dst.name} ได้ {got} ไบต์ ควรได้ {want}")
    return want


def plan(source: Path, name: str, want_images: bool) -> list[tuple[Path, str]]:
    """ไฟล์ที่จะยกขึ้น คู่กับที่อยู่ปลายทาง (สัมพัทธ์กับโฟลเดอร์ของเราบน Drive)

    ไฟล์เดียวอาจถูกยกสองที่ — มุมมอง "ตามสินค้า" กับ "ตามหมวด" ตามที่ผู้ใช้สั่ง
    ของดิบที่เครื่องอ่าน (`run.json` `prompts.json` ฯลฯ) ยกเฉพาะมุมมองตามสินค้า
    เพราะมุมมองตามหมวดมีไว้ให้คนเปิดดู ไม่ใช่ให้เครื่องอ่าน
    """
    home = f"{BY_PRODUCT}/{name}"
    items: list[tuple[Path, str]] = []

    for filename, category in FILE_MAP.items():
        path = source / filename
        if not path.is_file():
            continue
        items.append((path, f"{home}/{category}/{filename}" if category
                      else f"{home}/{filename}"))

    for folder, category in DIR_MAP.items():
        sub = source / folder
        if not sub.is_dir():
            continue
        for path in sorted(sub.rglob("*")):
            if not path.is_file():
                continue
            inner = path.relative_to(sub).as_posix()
            items.append((path, f"{home}/{category}/{inner}"))
            # มุมมองตามหมวด — สตอรีบอร์ดมีหลายภาพจึงแยกโฟลเดอร์ต่อสินค้า
            # ส่วนคลิปทำเป็นไฟล์เรียบๆ ติดชื่อสินค้านำ จะได้กวาดตาดูทั้งหมดได้ทีเดียว
            if category == CLIP_DIR:
                items.append((path, f"{BY_CATEGORY}/{category}/{name}__{path.name}"))
            else:
                items.append((path, f"{BY_CATEGORY}/{category}/{name}/{inner}"))

    if want_images:
        for path in sorted(source.iterdir()):
            if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES:
                items.append((path, f"{home}/{IMAGE_DIR}/{path.name}"))
    return items


# ------------------------------------------------------- ไฟล์ที่เขียนขึ้นเอง

def _read_run(folder: Path) -> dict:
    try:
        data = json.loads((folder / "run.json").read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def prompt_markdown(run: dict, item_id: str) -> str:
    """หมวด 1 — คำสั่งเจนคลิปแบบอ่านออก (ของดิบเป็น json อยู่ข้างๆ แล้ว)"""
    prompts = run.get("flow_prompts") or []
    lines = [f"# คำสั่งเจนคลิป (Flow) — {run.get('name') or item_id}", ""]
    if not prompts:
        lines.append("_ยังไม่มีคำสั่ง — ยังไม่ได้ผ่านขั้นสตอรีบอร์ด_")
    for index, text in enumerate(prompts, 1):
        lines += [f"## ฉาก {index}", "", str(text), ""]
    return "\n".join(lines).rstrip() + "\n"


def script_markdown(run: dict, item_id: str) -> str:
    """หมวด 1 — บทพูด"""
    script = run.get("script") or []
    lines = [f"# บทพูด — {run.get('name') or item_id}", ""]
    if not script:
        lines.append("_ยังไม่มีบทพูด_")
    for index, text in enumerate(script, 1):
        lines.append(f"{index}. {text}")
    return "\n".join(lines).rstrip() + "\n"


def _publish_rows(run: dict) -> list[tuple[str, str, str, str, str]]:
    """แถวตารางการโพสต์ (ช่องทาง, สถานะ, เวลา, ลิงก์, ข้อผิดพลาด)"""
    rows = []
    for target, info in (run.get("publish") or {}).items():
        info = info if isinstance(info, dict) else {}
        status = str(info.get("status") or "pending")
        rows.append((
            TARGET_NAMES.get(target, target),
            STATUS_NAMES.get(status, status),
            str(info.get("posted_at") or ""),
            str(info.get("url") or ""),
            str(info.get("error") or ""),
        ))
    return rows


def posting_markdown(run: dict, item_id: str) -> str:
    """หมวด 4 — โพสต์ผ่านช่องทางไหน เวลาเท่าไร ตามที่ผู้ใช้สั่ง"""
    lines = [f"# การโพสต์ — {run.get('name') or item_id}", ""]
    rows = _publish_rows(run)
    if not rows:
        lines += ["_ยังไม่ได้อนุมัติให้โพสต์ — ยังไม่มีช่องทางปลายทาง_", "",
                  "คลิปจะมีข้อมูลตรงนี้เมื่อผ่านการอนุมัติในแชทแล้ว"]
        return "\n".join(lines) + "\n"

    lines += ["| ช่องทาง | สถานะ | เวลาที่โพสต์ | ลิงก์ |", "|---|---|---|---|"]
    for channel, status, when, url, _error in rows:
        stamp = when.replace("T", " ")[:16] if when else "—"
        lines.append(f"| {channel} | {status} | {stamp} | {url or '—'} |")
    problems = [(channel, error) for channel, _s, _w, _u, error in rows if error]
    if problems:
        lines += ["", "## ที่ยังติดอยู่", ""]
        lines += [f"- **{channel}** — {error}" for channel, error in problems]
    if run.get("caption"):
        lines += ["", "## แคปชันที่ใช้โพสต์", "", "```", str(run["caption"]), "```"]
    return "\n".join(lines) + "\n"


def summary_markdown(run: dict, item_id: str) -> str:
    """หน้าสรุปหนึ่งหน้าต่อสินค้า — ไว้เปิดอ่านบนมือถือโดยไม่ต้องมีโปรแกรมอะไร"""
    lines = [f"# {run.get('name') or item_id}", "", f"รหัสสินค้า: `{item_id}`"]
    if run.get("affiliate_url"):
        lines.append(f"ลิงก์: {run['affiliate_url']}")
    lines.append("")

    highlights = run.get("highlights") or []
    if highlights:
        lines += ["## จุดเด่น", ""] + [f"- {text}" for text in highlights] + [""]

    posted = sum(1 for row in _publish_rows(run) if "โพสต์แล้ว" in row[1])
    lines += ["## มีอะไรอยู่ในโฟลเดอร์นี้", "",
              f"- `{PROMPT_DIR}/` — คำสั่งเจนคลิป {len(run.get('flow_prompts') or [])} ฉาก "
              f"· บทพูด {len(run.get('script') or [])} บรรทัด",
              f"- `{STORYBOARD_DIR}/` — ภาพสตอรีบอร์ด {len(run.get('storyboard') or [])} ภาพ",
              f"- `{CLIP_DIR}/` — คลิป {len(run.get('videos') or [])} ไฟล์",
              f"- `{POSTING_DIR}/` — โพสต์แล้ว {posted} ช่องทาง "
              f"จากทั้งหมด {len(run.get('publish') or {})}",
              "",
              f"_ยกขึ้น Drive เมื่อ {datetime.now():%Y-%m-%d %H:%M} โดย clip_drive.py_"]
    return "\n".join(lines) + "\n"


def _write_generated(root: Path, name: str, run: dict, item_id: str) -> None:
    """ไฟล์ที่เราเขียนขึ้นเอง — เขียนทับทุกรอบ เพราะสรุปจาก run.json ที่เปลี่ยนได้ตลอด

    ไม่เอาเข้าระบบลายนิ้วมือ (fingerprint) เพราะไม่มีต้นทางให้เทียบ และไฟล์เล็กมาก
    """
    home = target_root(root) / BY_PRODUCT / name
    category = target_root(root) / BY_CATEGORY
    prompt = prompt_markdown(run, item_id)
    script = script_markdown(run, item_id)
    posting = posting_markdown(run, item_id)

    pages = [
        (home / SUMMARY_FILE, summary_markdown(run, item_id)),
        (home / PROMPT_DIR / "คำสั่ง-flow.md", prompt),
        (home / PROMPT_DIR / "บทพูด.md", script),
        (home / POSTING_DIR / "การโพสต์.md", posting),
        (home / POSTING_DIR / "publish.json",
         json.dumps(run.get("publish") or {}, ensure_ascii=False, indent=2)),
        # มุมมองตามหมวด — รวม prompt กับบทพูดไว้ไฟล์เดียวต่อสินค้า จะได้กวาดตาดูได้เร็ว
        (category / PROMPT_DIR / f"{name}.md", prompt + "\n---\n\n" + script),
        (category / POSTING_DIR / f"{name}.md", posting),
    ]
    for path, text in pages:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


# ------------------------------------------------------------------ ยกขึ้น

def _purge(root: Path, name: str) -> None:
    """ลบของสินค้าชิ้นนี้ออกจาก Drive ให้หมดทั้งสองมุมมอง

    จำเป็นตอนโครงเปลี่ยนรุ่นหรือชื่อสินค้าเปลี่ยน ไม่งั้นของเก่าจะค้างปนกับของใหม่
    แล้วเปิดดูจะเห็นสองชุดโดยไม่รู้ว่าอันไหนของจริง

    กันพลาด: ลบได้เฉพาะสิ่งที่อยู่ใต้โฟลเดอร์ของเราเท่านั้น
    """
    if not name:
        return
    home = target_root(root).resolve()

    def under(path: Path) -> bool:
        try:
            resolved = path.resolve()
        except OSError:
            return False
        return resolved != home and home in resolved.parents

    victim = target_root(root) / BY_PRODUCT / name
    if under(victim):
        shutil.rmtree(victim, ignore_errors=True)

    # โครงรุ่นก่อนหน้า (รุ่น 1–2) วางโฟลเดอร์สินค้าไว้ที่ชั้นบนสุดเลย ไม่มี `ตามสินค้า/`
    # ถ้าไม่เก็บกวาดตรงนี้ ของเก่าจะค้างอยู่ชั้นบนปนกับโครงใหม่ — ลบเฉพาะชื่อที่ตรงกับ
    # ที่เราจดไว้เองเท่านั้น ไม่กวาดทั้งชั้นบน เพราะผู้ใช้อาจวางของอย่างอื่นไว้
    legacy = target_root(root) / name
    if legacy.is_dir() and under(legacy):
        shutil.rmtree(legacy, ignore_errors=True)

    for category in CATEGORY_DIRS:
        folder = target_root(root) / BY_CATEGORY / category
        if not folder.is_dir():
            continue
        for path in list(folder.iterdir()):
            # ทั้งโฟลเดอร์ต่อสินค้า (2-storyboard) และไฟล์ติดชื่อนำ (3-clip, 1-prompt)
            if path.name != name and not path.name.startswith(f"{name}__") \
                    and path.stem != name:
                continue
            if not under(path):
                continue
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
            else:
                try:
                    path.unlink()
                except OSError:
                    pass


def sync_run(root: Path, item_id: str, log=None, force: bool = False) -> dict:
    """ยกสินค้าหนึ่งชิ้นขึ้น Drive — ข้ามไฟล์ที่ไม่เปลี่ยนตั้งแต่รอบก่อน

    คืน dict เสมอ **ไม่โยน exception ขึ้นไปให้ผู้เรียก** เพราะตัวเรียกคือลูปที่ยก
    ทีละชิ้น และ hook ใน clip_store ที่ห้ามทำให้สายเจนคลิปล้มเพราะ Drive มีปัญหา
    """
    say = log or (lambda message: None)
    item_id = str(item_id)
    source = source_dir(root, item_id)
    now = datetime.now().isoformat(timespec="seconds")
    result = {"ok": False, "copied": 0, "skipped": 0, "bytes": 0,
              "folder": "", "why": "", "at": now}

    if not source.is_dir():
        result["why"] = f"ไม่พบโฟลเดอร์ของสินค้า {item_id}"
        return result

    ready, why = available(root)
    if not ready:
        result["why"] = why
        return result

    run = _read_run(source)
    state = load_state(root)
    remembered = state["items"].get(item_id) or {}
    known = {} if force else dict(remembered.get("files") or {})

    name = folder_name(run, item_id)
    old = str(remembered.get("folder") or "")

    if remembered.get("layout") != LAYOUT_VERSION:
        # โครงเปลี่ยนรุ่น = รื้อของเก่าทิ้งแล้วยกใหม่ทั้งชุด ไม่ปะผสมกัน
        if remembered:
            say(f"  โครงโฟลเดอร์เปลี่ยนเป็นรุ่น {LAYOUT_VERSION} — รื้อของเก่าแล้วยกใหม่")
        _purge(root, old or name)
        _purge(root, name)
        known = {}
    elif old and old != name:
        # ชื่อสินค้าเปลี่ยน — ลบของเดิมทิ้งแล้วยกใหม่ ง่ายและถูกกว่าไล่เปลี่ยนชื่อ
        # ทีละที่ในสองมุมมอง (ไฟล์ในมุมมองตามหมวดติดชื่อสินค้านำอยู่ในชื่อไฟล์ด้วย)
        say(f"  ชื่อสินค้าเปลี่ยน: {old} → {name} — ยกใหม่ทั้งชุด")
        _purge(root, old)
        known = {}

    files: dict[str, str] = {}
    try:
        for path, key in plan(source, name, include_images(root)):
            mark = _fingerprint(path)
            target = target_root(root) / key
            if known.get(key) == mark and target.is_file():
                files[key] = mark
                result["skipped"] += 1
                continue
            result["bytes"] += _copy(path, target)
            files[key] = mark
            result["copied"] += 1
        _write_generated(root, name, run, item_id)
    except OSError as error:
        result["why"] = str(error)
        # จดเท่าที่ยกสำเร็จไว้ก่อน รอบหน้าจะได้ไม่ต้องยกซ้ำตั้งแต่ต้น
        state["items"][item_id] = {"folder": name, "files": files,
                                   "name": run.get("name") or "",
                                   "layout": LAYOUT_VERSION,
                                   "at": now, "ok": False, "why": str(error)}
        save_state(root, state)
        return result

    result["ok"] = True
    result["folder"] = str(target_root(root) / BY_PRODUCT / name)
    state["items"][item_id] = {"folder": name, "files": files,
                               "name": run.get("name") or "",
                               "layout": LAYOUT_VERSION,
                               "at": now, "ok": True, "why": ""}
    save_state(root, state)
    # เขียนไฟล์รวมใหม่ทุกครั้งที่ยกสำเร็จ — เดิมเขียนเฉพาะตอนยกทั้งชุด ผลคือยกทีละชิ้น
    # แล้วสารบัญบน Drive ค้างของเก่า เปิดจากมือถือจะไม่เห็นของที่เพิ่งขึ้นไป
    # (เจอจากเทส ไม่ใช่จากการเดา) ไฟล์เล็กมาก เขียนซ้ำไม่กระทบอะไร
    write_index(root)
    write_posting_log(root)
    try:
        write_browser(root)
    except Exception as error:      # หน้าเว็บพังห้ามทำให้การยกคลิปนับว่าล้ม
        say(f"  ⚠️ เขียนหน้า {BROWSE_FILE} ไม่ได้: {error}")
    return result


def describe(result: dict, item_id: str = "") -> str:
    head = f"[Drive] {item_id}" if item_id else "[Drive]"
    if not result.get("ok"):
        return f"{head} ยกไม่ขึ้น — {result.get('why') or 'ไม่ทราบสาเหตุ'}"
    size = result.get("bytes", 0) / 1048576
    return (f"{head} ยกขึ้นแล้ว {result['copied']} ไฟล์ ({size:.1f} MB) · "
            f"ของเดิมตรงอยู่แล้ว {result['skipped']} ไฟล์")


def pending(root: Path) -> list[str]:
    """สินค้าที่ยังไม่เคยยกขึ้นสำเร็จ · โครงคนละรุ่น · หรือมีไฟล์เปลี่ยนหลังยกล่าสุด"""
    state = load_state(root)
    want_images = include_images(root)
    late = []
    for item_id, folder in all_sources(root):
        if not (folder / "run.json").is_file():
            continue
        remembered = state["items"].get(item_id) or {}
        if not remembered.get("ok") or remembered.get("layout") != LAYOUT_VERSION:
            late.append(item_id)
            continue
        known = remembered.get("files") or {}
        name = str(remembered.get("folder") or "")
        for path, key in plan(folder, name, want_images):
            try:
                if known.get(key) != _fingerprint(path):
                    late.append(item_id)
                    break
            except OSError:
                continue
    return late


def skipped_folders(root: Path) -> list[str]:
    """โฟลเดอร์สินค้าที่ยังไม่มี run.json — ดึงรูปมาแล้วแต่ยังไม่ได้เจนอะไรเลย

    ไม่ใช่ความผิดพลาด แต่ต้องนับให้เห็น ไม่งั้นเลข "โฟลเดอร์ในเครื่อง 18" กับ
    "ยกขึ้น 17" จะกระทบยอดกันไม่ได้ แล้วต้องมานั่งเดาว่าอีกอันหายไปไหน
    """
    return [item_id for item_id, folder in all_sources(root)
            if not (folder / "run.json").is_file()]


def sync_all(root: Path, log=None, force: bool = False) -> dict:
    """ยกทุกชิ้นที่ยังค้าง — ใช้ตอนเปิดใช้ครั้งแรกและตอนตามเก็บ"""
    say = log or (lambda message: None)
    ready, why = available(root)
    if not ready:
        raise DriveUnavailable(why)

    items = [item_id for item_id, folder in all_sources(root)
             if (folder / "run.json").is_file()]
    if not force:
        late = set(pending(root))
        items = [item for item in items if item in late]

    total = {"items": 0, "ok": 0, "failed": 0, "copied": 0, "bytes": 0, "fails": []}
    for item_id in items:
        total["items"] += 1
        result = sync_run(root, item_id, log=say, force=force)
        say(describe(result, item_id))
        if result["ok"]:
            total["ok"] += 1
            total["copied"] += result["copied"]
            total["bytes"] += result["bytes"]
        else:
            total["failed"] += 1
            total["fails"].append((item_id, result["why"]))
    return total          # ไฟล์รวมเขียนใน sync_run แล้วทุกชิ้น ไม่ต้องเขียนซ้ำ


# ---------------------------------------------------------------- ไฟล์รวม

def _synced_items(root: Path) -> list[tuple[str, dict, dict]]:
    """(item_id, ข้อมูลในสถานะ, run.json) ของชิ้นที่ยกขึ้นสำเร็จแล้ว"""
    state = load_state(root)
    found = []
    for item_id, info in state["items"].items():
        if item_id.startswith("__"):
            continue          # ระเบียนของระบบ (เช่น __logs__) ไม่ใช่สินค้า
        if info.get("ok"):
            found.append((item_id, info, _read_run(source_dir(root, item_id))))
    return found


def write_index(root: Path) -> Path | None:
    """สารบัญรวม — เปิดจากมือถือแล้วเห็นทั้งหมดในหน้าเดียว พร้อมสถานะครบ 4 หมวด"""
    ready, _why = available(root)
    if not ready:
        return None
    rows = []
    for item_id, info, run in _synced_items(root):
        posted = sum(1 for row in _publish_rows(run) if "โพสต์แล้ว" in row[1])
        rows.append((
            str(info.get("at") or ""),
            run.get("name") or info.get("name") or item_id,
            item_id,
            len(run.get("flow_prompts") or []),
            len(run.get("storyboard") or []),
            len(run.get("videos") or []),
            f"{posted}/{len(run.get('publish') or {})}" if run.get("publish") else "—",
            str(info.get("folder") or ""),
        ))
    rows.sort(reverse=True)

    lines = ["# สารบัญคลิปที่เจนแล้ว", "",
             f"ยกขึ้นโดย `clip_drive.py` · ปรับปรุงล่าสุด {datetime.now():%Y-%m-%d %H:%M}",
             "", f"ทั้งหมด {len(rows)} ชิ้น", "",
             f"เก็บไว้สองมุมมอง — `{BY_PRODUCT}/` แยกตามสินค้า · "
             f"`{BY_CATEGORY}/` แยกตามประเภท (prompt · สตอรีบอร์ด · คลิป · การโพสต์)", "",
             "ชื่อสินค้ากดได้ — พาไปที่โฟลเดอร์ของชิ้นนั้น · ตัวเลขในช่องคลิป"
             "กดแล้วเล่นคลิปได้เลย", "",
             "| สินค้า | รหัส | 1·prompt | 2·สตอรีบอร์ด | 3·คลิป | 4·โพสต์แล้ว | ยกขึ้นเมื่อ |",
             "|---|---|---:|---:|---:|:---:|---|"]
    for at, name, item_id, prompts, frames, videos, posted, folder in rows:
        stamp = at[:16].replace("T", " ")
        home = f"{BY_PRODUCT}/{folder}" if folder else ""
        title = _link(name, f"{home}/{SUMMARY_FILE}") if home else name
        clip_cell = str(videos)
        if videos and folder:
            clip_cell = _link(str(videos),
                              f"{BY_CATEGORY}/{CLIP_DIR}/{folder}__clip.mp4")
        board_cell = (_link(str(frames), f"{BY_CATEGORY}/{STORYBOARD_DIR}/{folder}")
                      if frames and folder else str(frames))
        prompt_cell = (_link(str(prompts), f"{home}/{PROMPT_DIR}")
                       if prompts and home else str(prompts))
        lines.append(f"| {title} | `{item_id}` | {prompt_cell} | {board_cell} "
                     f"| {clip_cell} | {posted} | {stamp} |")
    lines += ["", f"ดูรายการโพสต์ทั้งหมดที่ {_link(POSTING_LOG_FILE, POSTING_LOG_FILE)}",
              "", f"ดูบทสนทนาแชทและ log ระบบที่ {_link(LOG_ROOT, LOG_ROOT)}",
              "", f"เปิด {_link('เปิดดู.html', BROWSE_FILE)} เพื่อดูแบบกดผ่านหน้าเว็บ "
              "(ดับเบิลคลิกจากคอมได้เลย)"]
    path = target_root(root) / INDEX_FILE
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def write_posting_log(root: Path) -> Path | None:
    """หมวด 4 แบบรวมข้ามสินค้า — ตอบคำถาม "เมื่อวานโพสต์อะไรไปบ้าง"

    แยกจากสารบัญเพราะคำถามคนละแบบ: สารบัญถามว่า "มีสินค้าอะไรบ้าง"
    ไฟล์นี้ถามว่า "เกิดอะไรขึ้นเมื่อไร" จึงเรียงตามเวลา ไม่ใช่ตามสินค้า
    """
    ready, _why = available(root)
    if not ready:
        return None
    done, waiting = [], []
    for item_id, _info, run in _synced_items(root):
        name = run.get("name") or item_id
        for channel, status, when, url, error in _publish_rows(run):
            if when:
                done.append((when, name, item_id, channel, status, url, error))
            else:
                waiting.append((name, item_id, channel, status, error))
    done.sort(reverse=True)

    lines = ["# บันทึกการโพสต์", "",
             f"ปรับปรุงล่าสุด {datetime.now():%Y-%m-%d %H:%M} · "
             f"โพสต์ไปแล้ว {len(done)} ครั้ง · รออยู่ {len(waiting)} รายการ", ""]

    lines += ["## โพสต์ไปแล้ว", ""]
    if not done:
        lines += ["_ยังไม่มีการโพสต์ที่บันทึกไว้_", "",
                  "> ถ้าโพสต์ไปแล้วแต่ไม่ขึ้นตรงนี้ แปลว่าตัวโพสต์ยังไม่ได้เขียนผล",
                  "> กลับลงไฟล์งาน — ดูที่ `clip_store.mark_posted()` ว่าถูกเรียกหรือยัง", ""]
    else:
        lines += ["| เวลา | ช่องทาง | สินค้า | สถานะ | ลิงก์ |", "|---|---|---|---|---|"]
        for when, name, _item_id, channel, status, url, _error in done:
            stamp = str(when).replace("T", " ")[:16]
            lines.append(f"| {stamp} | {channel} | {name} | {status} | {url or '—'} |")
        lines.append("")

    if waiting:
        lines += ["## ยังรอโพสต์", "", "| สินค้า | ช่องทาง | สถานะ |", "|---|---|---|"]
        for name, _item_id, channel, status, _error in waiting:
            lines.append(f"| {name} | {channel} | {status} |")
        lines.append("")

    path = target_root(root) / POSTING_LOG_FILE
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _esc(text) -> str:
    return (str(text or "").replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def _url(target: str) -> str:
    return urllib.parse.quote(str(target).replace("\\", "/"), safe="/")


BROWSE_STYLE = """
:root{--bg:#f6f4f0;--card:#fff;--ink:#1c1a17;--dim:#6b645c;--line:#e2ddd5;
      --accent:#9a4b23;--good:#2f6b45;--warn:#8a6a12}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){
  --bg:#17151300;--bg:#171513;--card:#211e1b;--ink:#efe9e1;--dim:#a49a8e;
  --line:#332e29;--accent:#e08a55;--good:#7bc79b;--warn:#e0bb63}}
*{box-sizing:border-box}
body{margin:0;padding:28px 20px 60px;background:var(--bg);color:var(--ink);
     font-family:"Sarabun","Leelawadee UI","Segoe UI",system-ui,sans-serif;
     line-height:1.6}
.wrap{max-width:1180px;margin:0 auto}
h1{font-size:1.7rem;margin:0 0 4px;letter-spacing:-.01em}
h2{font-size:1.15rem;margin:40px 0 14px;padding-bottom:7px;
   border-bottom:2px solid var(--line)}
.sub{color:var(--dim);margin:0 0 8px}
.chips{display:flex;flex-wrap:wrap;gap:8px;margin:16px 0 4px}
.chip{background:var(--card);border:1px solid var(--line);border-radius:999px;
      padding:5px 13px;font-size:.85rem}
.chip b{color:var(--accent);font-variant-numeric:tabular-nums}
.grid{display:grid;gap:14px;grid-template-columns:repeat(auto-fill,minmax(310px,1fr))}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;
      overflow:hidden;display:flex;flex-direction:column}
.card img{width:100%;aspect-ratio:16/9;object-fit:cover;background:var(--line);display:block}
.card .body{padding:12px 14px 14px;display:flex;flex-direction:column;gap:8px;flex:1}
.name{font-weight:600;font-size:.95rem;line-height:1.4;text-wrap:balance}
.id{color:var(--dim);font-size:.78rem;font-variant-numeric:tabular-nums}
.links{display:flex;flex-wrap:wrap;gap:6px;margin-top:auto}
a.btn{display:inline-block;padding:4px 10px;border-radius:7px;font-size:.8rem;
      text-decoration:none;border:1px solid var(--line);color:var(--ink);background:transparent}
a.btn:hover{border-color:var(--accent);color:var(--accent)}
a.btn.on{background:var(--accent);border-color:var(--accent);color:#fff}
a.btn.off{opacity:.35;pointer-events:none}
table{width:100%;border-collapse:collapse;font-size:.88rem}
th,td{text-align:left;padding:7px 10px;border-bottom:1px solid var(--line);vertical-align:top}
th{color:var(--dim);font-weight:600;font-size:.8rem}
td.num{text-align:right;font-variant-numeric:tabular-nums}
.scroll{overflow-x:auto;background:var(--card);border:1px solid var(--line);border-radius:12px}
details{background:var(--card);border:1px solid var(--line);border-radius:10px;
        padding:10px 14px;margin-bottom:8px}
summary{cursor:pointer;font-weight:600;font-size:.92rem}
pre{white-space:pre-wrap;word-break:break-word;font-size:.82rem;
    background:var(--bg);padding:10px;border-radius:8px;overflow-x:auto}
.foot{color:var(--dim);font-size:.8rem;margin-top:48px;
      border-top:1px solid var(--line);padding-top:14px}
.in{color:var(--good)}.out{color:var(--accent)}
"""


def write_browser(root: Path) -> Path | None:
    """หน้าเว็บหน้าเดียวที่กดดูได้ทุกอย่าง — คลิป · รูป · บทสนทนา · log

    **ทำไมต้องเป็น HTML ไม่ใช่ .md** — Google Drive ไม่แสดงผลไฟล์ .md ให้
    กดแล้วได้แต่ตัวหนังสือดิบพร้อมวงเล็บลิงก์ที่กดไม่ได้ ส่วนไฟล์ .html
    ดับเบิลคลิกจากคอมแล้วเปิดในเบราว์เซอร์ทันที ลิงก์กดได้ คลิปเล่นได้
    """
    ready, _why = available(root)
    if not ready:
        return None
    here = target_root(root)
    items = []
    for item_id, info, run in _synced_items(root):
        if item_id.startswith("__"):
            continue
        folder = str(info.get("folder") or "")
        home = f"{BY_PRODUCT}/{folder}"
        clip_rel = f"{BY_CATEGORY}/{CLIP_DIR}/{folder}__clip.mp4"
        board = sorted((here / BY_CATEGORY / STORYBOARD_DIR / folder).glob("*.png")) \
            if folder else []
        posted = sum(1 for row in _publish_rows(run) if "โพสต์แล้ว" in row[1])
        items.append({
            "at": str(info.get("at") or ""),
            "name": run.get("name") or info.get("name") or item_id,
            "id": item_id,
            "home": home,
            "thumb": f"{BY_CATEGORY}/{STORYBOARD_DIR}/{folder}/{board[0].name}" if board else "",
            "clip": clip_rel if (here / clip_rel).is_file() else "",
            "prompts": len(run.get("flow_prompts") or []),
            "frames": len(run.get("storyboard") or []),
            "posted": f"{posted}/{len(run.get('publish') or {})}" if run.get("publish") else "—",
            "check": run.get("video_check") or {},
        })
    items.sort(key=lambda x: x["at"], reverse=True)

    with_clip = sum(1 for x in items if x["clip"])
    out = [
        "<!doctype html><html lang=\"th\"><head><meta charset=\"utf-8\">",
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">",
        "<title>คลังงานเจนคลิป</title>",
        f"<style>{BROWSE_STYLE}</style></head><body><div class=\"wrap\">",
        "<h1>คลังงานเจนคลิป</h1>",
        f"<p class=\"sub\">ปรับปรุงล่าสุด {datetime.now():%d/%m/%Y %H:%M} · "
        "ทุกอย่างที่ระบบทำ เก็บไว้ที่นี่</p>",
        "<div class=\"chips\">",
        f"<span class=\"chip\">สินค้า <b>{len(items)}</b> ชิ้น</span>",
        f"<span class=\"chip\">มีคลิป <b>{with_clip}</b> ใบ</span>",
        f"<span class=\"chip\">สตอรีบอร์ด <b>{sum(x['frames'] for x in items)}</b> ภาพ</span>",
        "</div>",
        "<h2>สินค้าทั้งหมด</h2><div class=\"grid\">",
    ]
    for x in items:
        thumb = (f'<img src="{_url(x["thumb"])}" alt="" loading="lazy">'
                 if x["thumb"] else '<img alt="" src="">')
        badge = ""
        check = x["check"] if isinstance(x["check"], dict) else {}
        if check:
            marks = []
            if check.get("hd") is not None:
                marks.append("1080p ✅" if check.get("hd") else "ไม่ถึง 1080p ⚠️")
            if check.get("has_speech") is not None:
                marks.append("มีเสียงพูด ✅" if check.get("has_speech") else "ไม่มีเสียงพูด ⚠️")
            if check.get("text_readable") is False:
                marks.append("ตัวอักษรอ่านไม่ออก ⚠️")
            if marks:
                badge = f'<div class="id">{_esc(" · ".join(marks))}</div>'
        def btn(text: str, rel: str, strong: bool = False) -> str:
            """ปุ่มที่กดได้เฉพาะเมื่อปลายทางมีอยู่จริง

            ปุ่มที่กดแล้วเจอ "ไม่พบไฟล์" แย่กว่าไม่มีปุ่ม เพราะทำให้สงสัย
            ว่าของหายไปจาก Drive ทั้งที่ความจริงคือยังไม่เคยมี
            """
            if not rel or not (here / rel).exists():
                return f'<a class="btn off">{text}</a>'
            klass = "btn on" if strong else "btn"
            return f'<a class="{klass}" href="{_url(rel)}">{text}</a>'

        links = [
            btn("▶ ดูคลิป", x["clip"], True) if x["clip"]
            else '<a class="btn off">ยังไม่มีคลิป</a>',
            btn("สรุป", f'{x["home"]}/{SUMMARY_FILE}'),
            btn("คำสั่ง+บทพูด", f'{x["home"]}/{PROMPT_DIR}'),
            btn("สตอรีบอร์ด", f'{x["home"]}/{STORYBOARD_DIR}'),
            btn("รูปสินค้า", f'{x["home"]}/{IMAGE_DIR}'),
            btn(f'การโพสต์ {_esc(x["posted"])}', f'{x["home"]}/{POSTING_DIR}'),
        ]
        out += [
            '<div class="card">', thumb, '<div class="body">',
            f'<div class="name">{_esc(x["name"])}</div>',
            f'<div class="id">รหัส {_esc(x["id"])} · ยกขึ้น {_esc(x["at"][:16].replace("T", " "))}</div>',
            badge,
            '<div class="links">' + "".join(links) + '</div>',
            '</div></div>',
        ]
    out.append("</div>")

    # ── บทสนทนาแชท ────────────────────────────────────────────────
    out.append("<h2>บทสนทนา Telegram</h2>")
    try:
        import chat_log
        days_found = chat_log.days()
    except Exception:
        days_found = []
    if not days_found:
        out.append('<p class="sub">ยังไม่มีบันทึกบทสนทนา — จะเริ่มเก็บเมื่อบอทส่ง'
                   'หรือรับข้อความครั้งถัดไป</p>')
    else:
        out.append(f'<p class="sub">เก็บไว้ {len(days_found)} วัน · '
                   f'ล่าสุด {_esc(days_found[-1])} · ฉบับเต็มทุกวันอยู่ในโฟลเดอร์ '
                   f'<code>{_esc(CHAT_LOG_DIR)}</code></p>')
        for day in reversed(days_found[-14:]):        # 14 วันล่าสุดกางดูได้ในหน้านี้
            rows = chat_log.load(day)
            sent = sum(1 for r in rows if r.get("dir") == "out")
            out.append(f'<details><summary>{_esc(day)} — {len(rows)} เหตุการณ์ '
                       f'(บอทส่ง {sent} · เข้ามา {len(rows) - sent})</summary>')
            out.append('<div class="scroll"><table><tr><th>เวลา</th><th>ใคร</th>'
                       '<th>ชนิด</th><th>เนื้อหา</th></tr>')
            for r in rows:
                side = "out" if r.get("dir") == "out" else "in"
                who = r.get("who") or chat_log.bot_name(r.get("bot", ""))
                text = re.sub(r"<[^>]+>", "", str(r.get("text") or ""))[:400]
                # ไฟล์สื่อในแชทชี้กลับไปหาตัวจริงบน Drive ถ้าหาเจอ
                # ถ้าไม่เจอให้แสดงชื่อเฉยๆ ดีกว่าทำปุ่มที่กดแล้วไปไม่ถึง
                marks = []
                for f in r.get("files") or []:
                    hit = next((p for p in (here / BY_CATEGORY / CLIP_DIR).glob(
                        f'*{f.get("name", "ไม่มีชื่อ")}')), None) if f.get("name") else None
                    marks.append(
                        f'<a href="{_url(BY_CATEGORY + "/" + CLIP_DIR + "/" + hit.name)}">'
                        f'{_esc(f.get("name"))}</a>' if hit else
                        f'<code>{_esc(f.get("name"))}</code>')
                files = " ".join(marks)
                out.append(f'<tr><td>{_esc(str(r.get("at") or "")[11:19])}</td>'
                           f'<td class="{side}">{_esc(who)}</td>'
                           f'<td>{_esc(chat_log._kind_name(r))}</td>'
                           f'<td>{_esc(text)}{" " + files if files else ""}</td></tr>')
            out.append("</table></div></details>")

    # ── log ระบบ ─────────────────────────────────────────────────
    out.append("<h2>log ระบบ</h2>")
    logs = sorted((here / SYSTEM_LOG_DIR).glob("*")) if (here / SYSTEM_LOG_DIR).is_dir() else []
    logs = [p for p in logs if p.is_file()]
    if not logs:
        out.append('<p class="sub">ยังไม่ได้ยก log ขึ้น — สั่ง '
                   '<code>python clip_drive.py logs</code></p>')
    else:
        out.append('<div class="scroll"><table><tr><th>ไฟล์</th><th>ขนาด</th>'
                   '<th>แก้ล่าสุด</th></tr>')
        for path in logs:
            stat = path.stat()
            out.append(
                f'<tr><td><a href="{_url(SYSTEM_LOG_DIR + "/" + path.name)}">'
                f'{_esc(path.name)}</a></td>'
                f'<td class="num">{stat.st_size / 1000:,.0f} KB</td>'
                f'<td>{datetime.fromtimestamp(stat.st_mtime):%d/%m/%Y %H:%M}</td></tr>')
        out.append("</table></div>")

    out += [
        f'<p class="foot">สร้างโดย <code>clip_drive.py</code> · '
        f'ที่เก็บจริง <code>{_esc(str(here))}</code><br>'
        f'สั่งสร้างใหม่ด้วย <code>python clip_drive.py index</code></p>',
        "</div></body></html>",
    ]
    path = here / BROWSE_FILE
    path.write_text("\n".join(out), encoding="utf-8")
    return path


# ------------------------------------------------------------------ บันทึก

# 25 ส.ค. 2026 ผู้ใช้สั่ง "เก็บ log ทั้งหมด ทั้งข้อความ รูปภาพ วีดีโอ ไว้ใน google
# drive ให้ลิ้งกัน" — ของสามอย่างแรก (prompt/สตอรีบอร์ด/คลิป) ยกอยู่แล้ว
# ส่วนที่ขาดคือ "เกิดอะไรขึ้น" ซึ่งอยู่ในบันทึกแชทกับ log ระบบ
LOG_ROOT = "5-บันทึก"
CHAT_LOG_DIR = f"{LOG_ROOT}/แชท Telegram"
SYSTEM_LOG_DIR = f"{LOG_ROOT}/log ระบบ"
SYSTEM_FULL_DIR = f"{SYSTEM_LOG_DIR}/เก็บเต็มรายวัน"
NOTE_LOG_DIR = f"{LOG_ROOT}/บันทึกงาน"
EVIDENCE_LOG_DIR = f"{LOG_ROOT}/หลักฐานตอนพัง"
LOG_STATE_KEY = "__logs__"

# log ที่ใหญ่กว่านี้ถือว่า "โตตลอดเวลา" — ยกทุกรอบจะดูดเน็ตทิ้งเปล่า
# (Bot8_stdout.log วัดได้ 6.7 MB และขยับทุกนาที ยกทุก 2 นาที = 200 MB/ชม.)
# จึงยกสองแบบ: ท้ายไฟล์สดๆ ทุกรอบ + สำเนาเต็มวันละครั้ง — ไม่มีอะไรถูกทิ้ง
BIG_LOG_BYTES = 2_000_000
TAIL_LINES = 5000
LOG_SUFFIXES = (".log", ".err", ".out")


def _tail_text(path: Path, lines: int) -> str:
    """ท้ายไฟล์ N บรรทัด พร้อมหัวบอกว่าตัดมาจากอะไร — **ห้ามตัดแบบเงียบ**"""
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError as error:
        return f"อ่านไฟล์ไม่ได้: {error}\n"
    rows = raw.splitlines()
    cut = max(0, len(rows) - lines)
    head = [
        f"# {path.name} — เฉพาะท้ายไฟล์ {min(lines, len(rows))} บรรทัด",
        f"# ไฟล์เต็ม {len(rows)} บรรทัด · {path.stat().st_size / 1e6:.1f} MB "
        f"· ตัดส่วนหัวออก {cut} บรรทัด",
        f"# ฉบับเต็มของแต่ละวันอยู่ที่ {SYSTEM_FULL_DIR}/",
        "# " + "-" * 60,
    ]
    return "\n".join(head + rows[-lines:]) + "\n"


def _log_sources(root: Path) -> list[Path]:
    """ไฟล์ log ทุกใบในเครื่อง — ทั้งที่อยู่ใน data/ และ data/logs/"""
    found: list[Path] = []
    for folder in (Path(root), Path(root) / "logs"):
        if not folder.is_dir():
            continue
        for path in sorted(folder.iterdir()):
            if path.is_file() and path.suffix.lower() in LOG_SUFFIXES:
                found.append(path)
    return found


def sync_logs(root: Path, log=None) -> dict:
    """ยกบันทึกทั้งหมดขึ้น Drive — บทสนทนาแชท · log ระบบ · บันทึกงาน

    คืน dict เสมอ ไม่โยน exception เหมือน `sync_run` เพราะตัวเรียกคือลูปเฝ้า
    ที่ห้ามตายเพราะ log ใบเดียวอ่านไม่ออก
    """
    say = log or (lambda message: None)
    result = {"ok": False, "copied": 0, "skipped": 0, "bytes": 0, "why": ""}
    ready, why = available(root)
    if not ready:
        result["why"] = why
        return result

    state = load_state(root)
    known = dict((state["items"].get(LOG_STATE_KEY) or {}).get("files") or {})
    files: dict[str, str] = {}
    today = datetime.now().strftime("%Y-%m-%d")

    def put(src: Path, key: str) -> None:
        mark = _fingerprint(src)
        target = target_root(root) / key
        if known.get(key) == mark and target.is_file():
            files[key] = mark
            result["skipped"] += 1
            return
        result["bytes"] += _copy(src, target)
        files[key] = mark
        result["copied"] += 1

    def put_text(text: str, key: str) -> None:
        """ไฟล์ที่สร้างขึ้นเอง — เทียบเนื้อหาก่อนเขียน จะได้ไม่ปลุก Drive ให้อัปซ้ำ"""
        target = target_root(root) / key
        # ห้ามใช้ hash() ของ Python — ค่าเปลี่ยนทุกครั้งที่เปิดโปรแกรมใหม่
        # (PYTHONHASHSEED สุ่ม) ผลคือไฟล์เดิมถูกเขียนทับใหม่ทุกครั้งที่รีสตาร์ต
        # แล้ว Drive ก็อัปขึ้นคลาวด์ซ้ำทั้งที่เนื้อหาไม่ได้เปลี่ยน
        mark = "text:%d:%08x" % (len(text), zlib.crc32(text.encode("utf-8")))
        if known.get(key) == mark and target.is_file():
            files[key] = mark
            result["skipped"] += 1
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        files[key] = mark
        result["bytes"] += len(text.encode("utf-8"))
        result["copied"] += 1

    try:
        # ── 1. บทสนทนา Telegram ────────────────────────────────────
        try:
            import chat_log
            for day in chat_log.days():
                # ฉบับอ่านง่าย — ลิงก์ไฟล์สื่อชี้กลับไปหาคลิป/รูปตัวจริงบน Drive
                put_text(chat_log.render(day, link_base=f"../../{BY_CATEGORY}/{CLIP_DIR}"),
                         f"{CHAT_LOG_DIR}/{day}.md")
                raw = chat_log.raw_path(day)
                if raw.is_file():
                    put(raw, f"{CHAT_LOG_DIR}/ของดิบ/{day}.jsonl")
        except Exception as error:            # บันทึกแชทพังห้ามล้มทั้งการยก
            say(f"  ⚠️ ยกบันทึกแชทไม่ได้: {error}")

        # ── 2. log ระบบ ──────────────────────────────────────────
        for path in _log_sources(root):
            size = path.stat().st_size
            if size <= BIG_LOG_BYTES:
                put(path, f"{SYSTEM_LOG_DIR}/{path.name}")
                continue
            # ใหญ่และโตตลอด — ท้ายไฟล์สดทุกรอบ + ฉบับเต็มวันละครั้ง
            put_text(_tail_text(path, TAIL_LINES),
                     f"{SYSTEM_LOG_DIR}/{path.stem}-ท้ายไฟล์{path.suffix}")
            full_key = f"{SYSTEM_FULL_DIR}/{today}-{path.name}"
            if not (target_root(root) / full_key).is_file():
                result["bytes"] += _copy(path, target_root(root) / full_key)
                result["copied"] += 1

        # ── 3. บันทึกงาน (note/) ─────────────────────────────────
        notes = BASE_DIR / "note"
        if notes.is_dir():
            for path in sorted(notes.glob("*.md")):
                put(path, f"{NOTE_LOG_DIR}/{path.name}")

        # ── 4. หลักฐานตอนพัง (ภาพหน้าจอ + ผังจอ + บริบท) ─────────
        # ยกขึ้นด้วยเพราะเป็นของที่ต้องเปิดดูย้อนหลังจริง และไฟล์ภาพหายง่าย
        # ถ้าเครื่องมีปัญหา — ตัวที่เก็บไว้ดูสาเหตุ ห้ามหายไปพร้อมสาเหตุ
        shots = Path(root) / "evidence"
        if shots.is_dir():
            for path in sorted(shots.iterdir()):
                if path.is_file():
                    put(path, f"{EVIDENCE_LOG_DIR}/{path.name}")
    except OSError as error:
        result["why"] = str(error)
        state["items"][LOG_STATE_KEY] = {"files": files, "ok": False,
                                         "at": datetime.now().isoformat(timespec="seconds"),
                                         "why": str(error), "layout": LAYOUT_VERSION}
        save_state(root, state)
        return result

    result["ok"] = True
    state["items"][LOG_STATE_KEY] = {
        "files": files, "ok": True, "why": "", "layout": LAYOUT_VERSION,
        "at": datetime.now().isoformat(timespec="seconds"),
    }
    save_state(root, state)
    return result


def verify(root: Path, item_id: str = "") -> dict:
    """ตรวจว่าของบน Drive ยังอยู่ครบและขนาดตรงกับต้นทาง

    มีไว้เพราะ "คัดลอกสำเร็จ" ไม่เท่ากับ "ยังอยู่" — ไฟล์บน Drive ถูกลบจากมือถือได้
    """
    ready, why = available(root)
    if not ready:
        raise DriveUnavailable(why)
    state = load_state(root)
    items = ([item_id] if item_id else
             [key for key in state["items"] if not key.startswith("__")])
    report = {"checked": 0, "missing": [], "wrong_size": [], "items": 0}
    for one in items:
        info = state["items"].get(one) or {}
        if not info.get("ok"):
            continue
        report["items"] += 1
        source = source_dir(root, one)
        name = str(info.get("folder") or "")
        # ปลายทางคนละโครงกับต้นทาง ต้องแปลงกลับก่อนถึงจะเทียบขนาดกันได้
        origins = {key: path for path, key in
                   plan(source, name, include_images(root))}
        for key in info.get("files") or {}:
            report["checked"] += 1
            target = target_root(root) / key
            origin = origins.get(key)
            try:
                if not target.is_file():
                    report["missing"].append(f"{one} → {key}")
                elif origin and origin.is_file() and \
                        target.stat().st_size != origin.stat().st_size:
                    report["wrong_size"].append(f"{one} → {key}")
            except OSError:
                report["missing"].append(f"{one} → {key}")
    return report


# --------------------------------------------------------------------- CLI

def _say(message: str) -> None:
    print(message, flush=True)


def _cmd_status(root: Path) -> int:
    ready, why = available(root)
    late = pending(root)
    state = load_state(root)
    done = sum(1 for key, info in state["items"].items()
               if info.get("ok") and not key.startswith("__"))
    logs = state["items"].get(LOG_STATE_KEY) or {}
    print("📦 ตัวยกงานเจนคลิปขึ้น Google Drive (clip_drive.py)")
    print(f"   เปิดใช้งาน   : {'ใช่' if enabled(root) else 'ไม่'}")
    print(f"   โฟลเดอร์ฐาน  : {base_folder(root)}")
    print(f"   ที่เก็บของเรา : {target_root(root)}")
    print(f"   โครงโฟลเดอร์ : รุ่น {LAYOUT_VERSION} — เก็บสองมุมมอง "
          f"({BY_PRODUCT}/ · {BY_CATEGORY}/)")
    print(f"   รูปสินค้า    : {'ยกด้วย' if include_images(root) else 'ไม่ยก (เอาเฉพาะของที่เจน)'}")
    print(f"   สถานะไดรฟ์   : {'✅ ' + why if ready else '❌ ' + why}")
    print(f"   ยกขึ้นแล้ว   : {done} ชิ้น · ค้าง {len(late)} ชิ้น")
    if logs:
        print(f"   บันทึก/log   : {'✅' if logs.get('ok') else '❌'} "
              f"{len(logs.get('files') or {})} ไฟล์ · ล่าสุด {str(logs.get('at') or '')[:16]}"
              + (f" — {logs.get('why')}" if logs.get("why") else ""))
    else:
        print("   บันทึก/log   : ยังไม่เคยยก — สั่ง `python clip_drive.py logs`")
    if late:
        print("   ค้างอยู่: " + ", ".join(late[:10]) + ("…" if len(late) > 10 else ""))
    empty = skipped_folders(root)
    if empty:
        print(f"   ข้ามไป      : {len(empty)} โฟลเดอร์ ยังไม่มี run.json "
              f"(ดึงรูปแล้วแต่ยังไม่ได้เจนอะไร) — {', '.join(empty[:5])}")
    return 0 if ready else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="ยกงานเจนคลิปขึ้น Google Drive จัด 4 หมวด สองมุมมอง")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status", help="ตั้งไว้ที่ไหน ไดรฟ์พร้อมไหม ค้างกี่ชิ้น")
    p_sync = sub.add_parser("sync", help="ยกของที่ยังค้างขึ้น Drive")
    p_sync.add_argument("item_id", nargs="?", default="")
    p_sync.add_argument("--force", action="store_true", help="ยกใหม่ทั้งหมดไม่สนของเดิม")
    sub.add_parser("index", help="เขียนสารบัญ + บันทึกการโพสต์ใหม่")
    sub.add_parser("logs", help="ยกบันทึกแชท · log ระบบ · บันทึกงาน ขึ้น Drive")
    p_verify = sub.add_parser("verify", help="ตรวจว่าของบน Drive ยังครบ")
    p_verify.add_argument("item_id", nargs="?", default="")
    p_watch = sub.add_parser("watch", help="เฝ้ายกให้เองเรื่อยๆ")
    p_watch.add_argument("--every", type=int, default=120, help="ทุกกี่วินาที")

    args = parser.parse_args(argv)
    root = data_dir()

    if args.command == "status":
        return _cmd_status(root)

    if args.command == "sync":
        try:
            if args.item_id:
                result = sync_run(root, args.item_id, log=_say, force=args.force)
                _say(describe(result, args.item_id))
                return 0 if result["ok"] else 1
            total = sync_all(root, log=_say, force=args.force)
            # บันทึกยกไปพร้อมกันเสมอ — ไม่งั้นต้องจำว่าต้องสั่งสองคำสั่ง
            # แล้วสุดท้ายก็จะมีแต่คลิปบน Drive ไม่มีร่องรอยว่าเกิดอะไรขึ้น
            report = sync_logs(root, log=_say)
            if report["copied"]:
                _say(f"[Drive] บันทึก/log — ยก {report['copied']} ไฟล์")
            elif not report["ok"]:
                _say(f"[Drive] ⚠️ ยกบันทึกไม่สำเร็จ — {report['why']}")
        except DriveUnavailable as error:
            _say(f"❌ ไดรฟ์ยังไม่พร้อม — {error}")
            return 1
        if not total["items"]:
            _say("✅ ไม่มีอะไรค้าง ของบน Drive ตรงกับในเครื่องแล้ว")
            return 0
        _say(f"\nสรุป: ยกสำเร็จ {total['ok']}/{total['items']} ชิ้น · "
             f"{total['copied']} ไฟล์ · {total['bytes'] / 1048576:.1f} MB")
        for item_id, why in total["fails"]:
            _say(f"   ❌ {item_id}: {why}")
        return 1 if total["failed"] else 0

    if args.command == "logs":
        report = sync_logs(root, log=_say)
        if not report["ok"]:
            _say(f"❌ ยกบันทึกไม่สำเร็จ — {report['why']}")
            return 1
        _say(f"✅ ยกบันทึกแล้ว {report['copied']} ไฟล์ "
             f"({report['bytes'] / 1048576:.1f} MB) · เดิมอยู่แล้ว {report['skipped']} ไฟล์")
        _say(f"   ที่เก็บ: {target_root(root) / LOG_ROOT}")
        return 0

    if args.command == "index":
        index = write_index(root)
        log = write_posting_log(root)
        page = write_browser(root)
        if not index:
            _say("❌ ไดรฟ์ยังไม่พร้อม")
            return 1
        _say(f"เขียนแล้ว: {index}")
        _say(f"เขียนแล้ว: {log}")
        _say(f"เขียนแล้ว: {page}")
        return 0

    if args.command == "verify":
        try:
            report = verify(root, args.item_id)
        except DriveUnavailable as error:
            _say(f"❌ ไดรฟ์ยังไม่พร้อม — {error}")
            return 1
        _say(f"ตรวจ {report['items']} ชิ้น · {report['checked']} ไฟล์")
        for key in report["missing"]:
            _say(f"   ❌ หายไป: {key}")
        for key in report["wrong_size"]:
            _say(f"   ⚠️ ขนาดไม่ตรง: {key}")
        if not report["missing"] and not report["wrong_size"]:
            _say("✅ ครบและขนาดตรงทุกไฟล์")
            return 0
        return 1

    if args.command == "watch":
        _say(f"เฝ้ายกขึ้น Drive ทุก {args.every} วิ — Ctrl+C เพื่อหยุด")
        while True:
            try:
                if enabled(root):
                    total = sync_all(root, log=_say)
                    report = sync_logs(root)
                    if report["copied"]:
                        _say(f"— บันทึก/log {report['copied']} ไฟล์")
                    if total["items"]:
                        _say(f"— ยก {total['ok']}/{total['items']} ชิ้น "
                             f"({total['bytes'] / 1048576:.1f} MB)")
            except DriveUnavailable as error:
                _say(f"⏳ ไดรฟ์ยังไม่พร้อม — {error}")
            except Exception as error:          # ตัวเฝ้าต้องไม่ตายกลางทาง
                _say(f"⚠️ รอบนี้ผิดพลาด: {type(error).__name__}: {error}")
            time.sleep(max(10, args.every))

    return 0


if __name__ == "__main__":
    sys.exit(main())
