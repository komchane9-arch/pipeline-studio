"""ทะเบียนมือถือ — รากของการสั่งงานหลายเครื่องพร้อมกัน

**ปัญหาที่แก้** ทั้งระบบเขียนขึ้นตอนมีมือถือเครื่องเดียว จุดที่พึ่งข้อสมมตินั้น
มีทั่วไปหมด: ประตูจอมีใบเดียว · หัวหน้างานโพสต์มีคนเดียว · ตัวนับโควตาจดรวม
ถังเดียว ผลคือพอเสียบเครื่องที่สอง เครื่องแรกใช้โควตาหมดแล้วเครื่องสองทำงาน
ไม่ได้ทั้งที่ยังไม่ได้เริ่ม และถ้าเครื่องแรกโดนบล็อก เครื่องสองโดนตามทั้งที่
คนละบัญชี

ไฟล์นี้เป็นสมุดรายชื่อกลาง: ใครเป็นใคร · เปิดใช้ไหม · รับงานสายไหน ·
ค่าตั้งของตัวเองเป็นอย่างไร ทุกฝั่งอ้างสมุดเล่มนี้เล่มเดียว

**กติกาสามข้อที่ห้ามเปลี่ยน**

1. `resolve()` **ห้ามเดาเอง** เมื่อมีเครื่องเปิดใช้อยู่มากกว่าหนึ่งเครื่อง ต้องโยน
   `DeviceAmbiguous` ให้เห็นชัดๆ — โค้ดเก่าที่ลืมส่ง serial จะได้ล้มเสียงดังตรงจุด
   แทนที่จะไปสั่งผิดเครื่องเงียบๆ แล้วรู้ตัวตอนโพสต์ลงบัญชีผิดไปแล้ว
2. เครื่องที่เพิ่งเสียบเข้ามาได้ `enabled: False` เสมอ — เสียบมือถือมาชาร์จ
   แล้วโดนระบบยิงโพสต์ใส่คือความเสียหายที่กู้คืนไม่ได้
3. จำนวนเครื่องไม่จำกัด ไม่มีที่ไหนในไฟล์นี้ผูกกับเลข 1 หรือ 2

**ค่าตั้งแยกรายเครื่อง** `settings(serial)` คืนค่ากลางของระบบซ้อนด้วยค่าที่เครื่อง
นั้นตั้งเอง ค่าตั้งใหม่ที่ใครเพิ่มทีหลังจึงแยกรายเครื่องได้เองทันที ไม่ต้องกลับมา
แก้ไฟล์นี้ซ้ำ

ใช้จากบรรทัดคำสั่ง:

    python devices.py list
    python devices.py sync
    python devices.py enable 7a95129e
    python devices.py name 7a95129e "Xiaomi - บัญชีหลัก"
    python devices.py lane 7a95129e post,engage
    python devices.py copy 7a95129e DATCW8GQUOCUWK9P
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path

import studio_shared

# เครื่องมือนี้ถูกเรียกมือจากหน้าจอด้วย จึงเจอ stdout ที่ไม่ใช่คอนโซลบ่อย แล้ว
# Python จะใช้ cp1252 ทำให้ print ภาษาไทยพังทั้งโปรเซส (เหมือนที่ file_claims เจอ)
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

BASE_DIR = Path(__file__).resolve().parent
DEVICES_FILE = studio_shared.DATA_DIR / "devices.json"

# เลขรุ่นของโครงสร้างไฟล์ — ใช้กันย้ายค่าเก่าซ้ำ ไม่ใช่เลขเวอร์ชันแอป
VERSION = 1

# สายงานที่มือถือเครื่องหนึ่งรับได้ — เครื่องหนึ่งรับได้หลายสาย
#
# ไม่ได้บังคับว่าต้องมีแค่สี่ตัวนี้ ใครเพิ่มสายใหม่ใส่เข้ามาได้เลย ที่ประกาศไว้
# เพื่อให้หน้าเว็บมีชื่อไทยไปโชว์ และให้ทุกแชทเรียกชื่อสายเดียวกัน
LANES = {
    "post": "โพสต์กลุ่ม",
    "engage": "ตามยอด/ตอบคอมเมนต์",
    "mass": "หาโพสต์แมส",
    "clip": "คลิป",
    # เจ้าของสั่ง 21 ส.ค. 2569: งานค้นหาสินค้าในแอปมือถือ (shopee · lazada ·
    # lineman · shopeefood) ต้องอยู่ **คนละเครื่อง**กับสายโพสต์ เพราะสองงานนี้
    # แย่งจอกันตลอด และเดิมกันชนด้วยการเดาตารางเวลา ซึ่งเคยพลาดจนรอเงียบ 10 ชม.
    "scalp": "ค้นหาสินค้าในแอป",
}

# คีย์ในค่ากลางของระบบที่ **ไม่ใช่** ค่าตั้งรายเครื่อง — ห้ามไหลลงไปเป็นของเครื่อง
#
# `serial` แปลว่า "เครื่องไหนเป็นตัวหลัก" ซึ่งเป็นค่าของระบบ ไม่ใช่ของเครื่อง
# ถ้าปล่อยให้ก๊อปตามไป เครื่อง B จะจำว่าตัวเองคือ A
SHARED_KEYS = {"serial"}

# ใช้ RLock ไม่ใช่ Lock — ฟังก์ชันในไฟล์นี้เรียกกันเองหลายชั้น (upsert → _change,
# _change → mutate → อ่านทะเบียนซ้ำ) Lock ธรรมดาจะค้างตัวเองทันทีที่มีใครเผลอ
# ซ้อนชั้น และเป็นการค้างที่หาสาเหตุยากมากเพราะไม่มี error อะไรออกมาเลย
_lock = threading.RLock()


class DeviceError(RuntimeError):
    """ปัญหาเกี่ยวกับทะเบียนเครื่อง"""


class DeviceUnknown(DeviceError):
    """ไม่มีเครื่องที่ใช้ได้เลย"""


class DeviceAmbiguous(DeviceError):
    """มีหลายเครื่องให้เลือก แต่ไม่มีใครบอกว่าจะเอาเครื่องไหน"""


# ------------------------------------------------------------------ ตัวช่วยเล็ก


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def slug(serial: str) -> str:
    """แปลง serial ให้ใช้เป็นชื่อไฟล์ได้

    serial ของเครื่องที่ต่อผ่าน Wi-Fi หน้าตาเป็น `192.168.1.5:5555` ซึ่งมี `:`
    ที่ Windows ห้ามใช้ในชื่อไฟล์ — เอาไปตั้งชื่อไฟล์ตรงๆ จะเขียนไม่ได้เลย
    ใช้กติกาเดียวกับ `position_file` ใน app.py เพื่อให้ชื่อไฟล์ตรงกันทั้งระบบ
    """
    return re.sub(r"[^A-Za-z0-9_.-]", "_", (serial or "").strip())[:80] or "unknown"


def blank_device(serial: str, **fields) -> dict:
    device = {
        "serial": serial,
        "name": "",                 # ชื่อเล่นที่ผู้ใช้ตั้ง
        "model": "",                # ชื่อรุ่นที่ adb บอก — เก็บไว้โชว์ตอนถอดสาย
        "enabled": False,           # กติกาข้อ 2: ของใหม่ปิดไว้ก่อนเสมอ
        "lanes": [],                # สายงานที่รับ — ว่าง = รับได้ทุกสาย
        "account": "",              # บัญชีเฟซที่ล็อกอินอยู่บนเครื่องนี้
        "bot_profile": "",          # โปรไฟล์บอทที่ผูกกับเครื่องนี้
        "screen": {"w": 0, "h": 0},
        "settings": {},             # ค่าตั้งเฉพาะเครื่อง ซ้อนทับค่ากลาง
        "note": "",
        "added_at": _now(),
        "seen_at": "",
    }
    device.update(fields)
    return device


def blank() -> dict:
    """ทะเบียนเปล่า — **version ต้องเป็น 0**

    เพราะไฟล์ที่ยังไม่เคยมีจะได้ค่านี้ไปเป็นค่าตั้งต้น ถ้าใส่ VERSION ลงไปเลย
    ระบบจะนึกว่า "ย้ายค่าเก่ามาแล้ว" ตั้งแต่วินาทีแรก แล้วค่าที่ผู้ใช้ตั้งไว้เดิม
    จะไม่ถูกย้ายเข้าทะเบียนเลยสักตัว — ผู้ใช้เปิดมาเจอทะเบียนว่างทั้งที่มีเครื่องอยู่
    """
    return {"version": 0, "default_serial": "", "devices": {}}


def _label_in(data: dict, serial: str) -> str:
    """ชื่อเครื่องจากข้อมูลที่ถืออยู่ในมือแล้ว

    ห้ามเรียก `label()` ระหว่างที่ถือล็อกแก้ทะเบียนอยู่ เพราะ `label()` วนกลับไป
    อ่านทะเบียนใหม่ — ถือล็อกอยู่แล้ววนกลับมาขอเองคือค้างทั้งเธรด
    """
    device = data["devices"].get(serial) or {}
    return device.get("name") or device.get("model") or serial or "(ไม่ระบุเครื่อง)"


# ------------------------------------------------------------ อ่าน/เขียนทะเบียน


def _sane(data) -> dict:
    """กันไฟล์เสีย/โครงสร้างผิด ไม่ให้ล้มทั้งระบบเพราะทะเบียนพัง"""
    if not isinstance(data, dict):
        return blank()
    devices = data.get("devices")
    if not isinstance(devices, dict):
        devices = {}
    clean = {}
    for serial, device in devices.items():
        serial = str(serial).strip()
        if not serial or not isinstance(device, dict):
            continue
        merged = blank_device(serial)
        merged.update({k: v for k, v in device.items() if k not in ("serial",)})
        merged["serial"] = serial
        merged["lanes"] = [str(x) for x in (merged.get("lanes") or []) if str(x).strip()]
        merged["enabled"] = bool(merged.get("enabled"))
        if not isinstance(merged.get("settings"), dict):
            merged["settings"] = {}
        if not isinstance(merged.get("screen"), dict):
            merged["screen"] = {"w": 0, "h": 0}
        clean[serial] = merged
    return {
        "version": int(data.get("version") or 0),
        "default_serial": str(data.get("default_serial") or ""),
        "devices": clean,
    }


def _rescue_corrupt() -> bool:
    """ทะเบียนอ่านไม่ออก = เรื่องใหญ่ ห้ามกลบเงียบ — คืน True ถ้าเจอไฟล์เสีย

    ถ้าปล่อยให้ระบบสร้างทะเบียนใหม่เงียบๆ มันจะย้ายค่าเก่ามาแล้ว **เปิดใช้เครื่อง
    ให้เองทุกเครื่อง** ซึ่งผิดกติกาข้อ 2 เต็มๆ — ผู้ใช้อาจมีมือถือเสียบค้างไว้หลาย
    เครื่องที่ตั้งใจปิดไม่ให้ระบบแตะ แล้วอยู่ดีๆ ทุกเครื่องกลับมาเปิดพร้อมกัน

    จึงเก็บไฟล์เสียไว้เป็นหลักฐาน · บอกให้เห็นใน log · แล้วให้เครื่องทุกตัวกลับมา
    แบบ **ปิดไว้** ให้ผู้ใช้เป็นคนเปิดเอง ยอมให้งานหยุดดีกว่าให้เครื่องผิดทำงานเอง
    """
    try:
        raw = DEVICES_FILE.read_bytes()
    except OSError:
        return False                          # ยังไม่มีไฟล์ = ติดตั้งใหม่ ไม่ใช่ของเสีย
    if not raw.strip():
        return False
    try:
        json.loads(raw.decode("utf-8"))
        return False                          # อ่านออก แค่ยังไม่เคยย้ายค่า
    except (ValueError, UnicodeDecodeError):
        pass
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    keep = DEVICES_FILE.with_name(f"devices.เสีย-{stamp}.json")
    try:
        DEVICES_FILE.replace(keep)
    except OSError:
        keep = None
    print(f"⚠️ ทะเบียนมือถืออ่านไม่ออก — สร้างใหม่แบบปิดทุกเครื่องไว้ก่อน "
          f"(เก็บไฟล์เดิมไว้ที่ {keep.name if keep else 'ลบไม่ได้'}) "
          f"ต้องเข้าไปเปิดใช้เครื่องที่ต้องการเองในหน้าตั้งค่า", flush=True)
    return True


def _migrate(data: dict, *, enable_known: bool = True) -> dict:
    """ย้ายค่าเดิมเข้าทะเบียน — ทำครั้งเดียว ผู้ใช้ไม่ต้องตั้งใหม่

    ของเดิมกระจายอยู่สองที่ใน config.json:
      · `device_names`      {serial: ชื่อเล่น}  = เครื่องที่ผู้ใช้เคยตั้งชื่อไว้
      · `facebook.serial`   เครื่องตัวหลักของสายโพสต์

    เครื่องที่โผล่ในสองที่นี้ถือว่า **ผู้ใช้ตั้งมาเองแล้ว** จึงเปิดใช้ให้เลย ไม่งั้น
    อัปเดตเสร็จแล้วงานที่เคยรันอยู่จะหยุดหมดโดยไม่มีใครสั่ง ส่วนเครื่องที่เพิ่งเจอ
    ตอน `sync()` ยังคงปิดไว้ตามกติกาข้อ 2

    ตัดสินด้วย `version` อย่างเดียว ห้ามเอา "ทะเบียนว่าง" มาเป็นเงื่อนไขย้ายซ้ำ
    ไม่งั้นเครื่องที่ผู้ใช้เพิ่งสั่งลบทิ้งจะฟื้นกลับมาเองในการอ่านครั้งถัดไป
    """
    if data.get("version", 0) >= VERSION:
        return data

    config = studio_shared.read_config() or {}
    facebook = config.get("facebook") or {}
    names = config.get("device_names") or {}
    main = str(facebook.get("serial") or "").strip()

    known = [str(s).strip() for s in names]
    if main and main not in known:
        known.append(main)

    for serial in known:
        if not serial or serial in data["devices"]:
            continue
        data["devices"][serial] = blank_device(
            serial,
            name=str(names.get(serial) or ""),
            enabled=bool(enable_known),         # เคยตั้งมาเอง = ใช้งานอยู่จริง
            lanes=["post"],
        )

    # ตั้งตัวหลักเฉพาะตอนที่เครื่องนั้นเปิดใช้อยู่จริง — ตัวหลักที่สั่งงานไม่ได้
    # คือกับดัก: ทุกอย่างชี้ไปหามัน แล้วล้มทุกครั้งโดยไม่บอกว่าเพราะมันถูกปิดอยู่
    if enable_known:
        if main and main in data["devices"]:
            data["default_serial"] = main
        elif len(data["devices"]) == 1:
            data["default_serial"] = next(iter(data["devices"]))

    # ค่าตั้งสายโพสต์ยกไปเป็นของเครื่องตัวหลัก เพราะค่าพวกนั้น (เว้นระยะ · เริ่มเอง ·
    # ล้างเครื่อง) ถูกจูนมาสำหรับเครื่องนั้นโดยเฉพาะ ถ้ามีหลายเครื่องแล้วยังไม่ระบุ
    # ตัวหลัก ปล่อยไว้เป็นค่ากลาง — ทุกเครื่องจะได้ค่าเดียวกันซึ่งคือพฤติกรรมเดิม
    target = data["default_serial"]
    if target and target in data["devices"]:
        data["devices"][target]["settings"].update(
            {k: v for k, v in facebook.items() if k not in SHARED_KEYS}
        )

    data["version"] = VERSION
    return data


def _change(mutate, *, enable_known: bool = True) -> dict:
    """อ่าน-แก้-เขียน ในล็อกเดียว — กันสองโปรเซสเขียนทับกัน

    ต้องอ่านในล็อกด้วย ไม่ใช่แค่เขียน ถ้าอ่านนอกล็อกแล้วค่อยเขียนในล็อก จะกลาย
    เป็น "อ่านของเก่ามาทับของใหม่" ซึ่งคืออัปเดตหายแบบคลาสสิก — `update_json`
    ของ studio_shared ทำครบทั้งสองฝั่งให้แล้ว ใช้ตัวเดียวกับที่ config.json ใช้
    """
    def apply(current):
        data = _migrate(_sane(current), enable_known=enable_known)
        mutate(data)
        return data

    with _lock:
        return studio_shared.update_json(
            DEVICES_FILE, apply, default=blank(), label="ทะเบียนมือถือ"
        )


def load() -> dict:
    """อ่านทะเบียน (ย้ายค่าเดิมให้อัตโนมัติถ้ายังไม่เคยย้าย)

    ทางอ่านล้วนไม่ขอล็อก เพราะเป็นทางที่ถูกเรียกถี่ที่สุด (ทุกครั้งที่หน้าเว็บถาม)
    `read_json` ทนการอ่านชนกับการเขียนอยู่แล้ว — ได้ของเก่าทั้งก้อนหรือของใหม่
    ทั้งก้อน ไม่มีทางได้ครึ่งๆ
    """
    data = _sane(studio_shared.read_json(DEVICES_FILE, blank()))
    if data["version"] >= VERSION:
        return data
    # ถึงตรงนี้มีได้สองสาเหตุที่ต้องแยกให้ออก: **ยังไม่เคยย้ายค่า** (ปกติ ครั้งเดียว)
    # กับ **ไฟล์อ่านไม่ออก** (ผิดปกติ ต้องดัง) สองอย่างนี้ต้องจบไม่เหมือนกัน
    return _change(lambda _data: None, enable_known=not _rescue_corrupt())


# ------------------------------------------------------------------ อ่านข้อมูล


def all_devices() -> dict:
    return load()["devices"]


def listing() -> list[dict]:
    """ทุกเครื่องเรียงแบบที่หน้าเว็บใช้ได้เลย — ตัวหลักก่อน แล้วตัวที่เปิดใช้"""
    data = load()
    default = data["default_serial"]

    def order(device: dict) -> tuple:
        return (
            0 if device["serial"] == default else 1,
            0 if device["enabled"] else 1,
            (device.get("name") or device.get("model") or device["serial"]).lower(),
        )

    return sorted(data["devices"].values(), key=order)


def get(serial: str) -> dict | None:
    return all_devices().get(str(serial or "").strip())


def default_serial() -> str:
    return load()["default_serial"]


def label(serial: str) -> str:
    """ชื่อที่เอาไปโชว์ให้คนอ่าน — ชื่อเล่น > ชื่อรุ่น > serial

    ยังถอยไปอ่าน `device_names` ใน config ด้วย เพราะ `fb_limits.py` กับหน้าเว็บ
    เดิมยังเขียนลงที่นั่น ถ้าไม่ถอย ชื่อที่ผู้ใช้เพิ่งตั้งจากหน้าเดิมจะหายไปเฉยๆ
    """
    serial = str(serial or "").strip()
    device = get(serial)
    if device and (device.get("name") or device.get("model")):
        return device.get("name") or device.get("model")
    legacy = (studio_shared.read_config().get("device_names") or {}).get(serial)
    return legacy or serial or "(ไม่ระบุเครื่อง)"


def enabled_serials(lane: str = "") -> list[str]:
    """เครื่องที่เปิดใช้อยู่ — กรองตามสายงานได้

    เครื่องที่ยังไม่ได้มอบหมายสายไหนเลย (`lanes` ว่าง) ถือว่ารับได้ทุกสาย ไม่งั้น
    ผู้ใช้ที่เปิดเครื่องแล้วลืมติ๊กสายจะงงว่าทำไมสั่งงานไม่ได้ทั้งที่เปิดใช้แล้ว
    """
    out = []
    for device in listing():
        if not device["enabled"]:
            continue
        lanes = device.get("lanes") or []
        if lane and lanes and lane not in lanes:
            continue
        out.append(device["serial"])
    return out


def account(serial: str) -> str:
    """บัญชีที่ล็อกอินอยู่บนเครื่องนี้ — ว่าง = ยังไม่ได้ผูก"""
    device = load()["devices"].get(str(serial or "").strip()) or {}
    return str(device.get("account") or "").strip()


def accounts() -> dict:
    """{ชื่อบัญชี: serial} ของทุกเครื่องที่เปิดใช้และผูกบัญชีไว้แล้ว"""
    data = load()
    out: dict[str, list[str]] = {}
    for serial, device in data["devices"].items():
        if not device.get("enabled"):
            continue
        name = str(device.get("account") or "").strip()
        if name:
            out.setdefault(name, []).append(serial)
    return out


def device_for_account(name: str) -> str:
    """บัญชีนี้อยู่เครื่องไหน — **หนึ่งเครื่องต่อหนึ่งไอดี** (เจ้าของสั่ง 21 ส.ค. 2569)

    ตอบไม่ได้แน่ชัดต้องโยน error พร้อมบอกทางแก้ ห้ามหยิบเครื่องแรกมาใช้ —
    โพสต์ลงบัญชีผิดกู้คืนไม่ได้ ส่วนงานไม่เริ่มพร้อมเหตุผลเสียแค่เวลากดใหม่

    เจอสองเครื่องผูกบัญชีเดียวกัน = ตั้งค่าผิด ต้องบอกให้รู้ทันที ไม่ใช่เลือกให้เอง
    แล้วปล่อยให้ไปเจอตอนโพสต์ซ้ำสองเครื่อง
    """
    wanted = str(name or "").strip()
    if not wanted:
        raise DeviceError("ต้องบอกชื่อบัญชีที่จะโพสต์")
    book = accounts()
    found = book.get(wanted) or []
    if not found:
        known = " · ".join(sorted(book)) or "ยังไม่มีเครื่องไหนผูกบัญชีไว้เลย"
        raise DeviceUnknown(
            f"ไม่รู้ว่าบัญชี '{wanted}' อยู่เครื่องไหน — ผูกด้วย\n"
            f"    python devices.py account <serial> \"{wanted}\"\n"
            f"บัญชีที่ผูกไว้แล้ว: {known}")
    if len(found) > 1:
        where = " · ".join(f"{label(s)} [{s}]" for s in found)
        raise DeviceError(
            f"บัญชี '{wanted}' ถูกผูกไว้ {len(found)} เครื่อง ซึ่งผิดกติกา "
            f"หนึ่งเครื่องต่อหนึ่งไอดี: {where}")
    return found[0]


def resolve(serial: str = "", lane: str = "", *, allow_default: bool = False) -> str:
    """ตอบว่า "จะสั่งงานเครื่องไหน" — ห้ามเดาเองเมื่อมีให้เลือกหลายเครื่อง

    เจตนาคือให้โค้ดเก่าที่ยังไม่ได้แก้ **ล้มเสียงดัง** ทันทีที่ผู้ใช้เปิดเครื่องที่สอง
    แทนที่จะไปสั่งเครื่องผิดเงียบๆ — "โพสต์ลงบัญชีผิด" กู้คืนไม่ได้ ส่วน "งานไม่เริ่ม
    พร้อมข้อความบอกเหตุผล" เสียแค่เวลากดใหม่

    `allow_default=True` ใช้เฉพาะที่ที่แปลว่า "เครื่องตัวหลักของผู้ใช้" จริงๆ เช่น
    ปุ่มลัดที่ตั้งใจยิงไปตัวหลัก — ไม่ใช่ทางลัดสำหรับคนขี้เกียจส่ง serial
    """
    data = load()
    serial = str(serial or "").strip()
    if serial:
        device = data["devices"].get(serial)
        if device is None:
            raise DeviceUnknown(
                f"ไม่มีมือถือ {serial} ในทะเบียน — กดรีเฟรชรายการอุปกรณ์ก่อน"
            )
        if not device["enabled"]:
            raise DeviceError(
                f"มือถือ {_label_in(data, serial)} ยังปิดใช้อยู่ — เปิดใช้ในหน้าตั้งค่าก่อน"
            )
        return serial

    picks = enabled_serials(lane)
    if not picks:
        where = f"สาย{LANES.get(lane, lane)}" if lane else "งานนี้"
        raise DeviceUnknown(
            f"ยังไม่มีมือถือที่เปิดใช้สำหรับ{where} — เปิดใช้อย่างน้อยหนึ่งเครื่องก่อน"
        )
    if len(picks) == 1:
        return picks[0]
    if allow_default and data["default_serial"] in picks:
        return data["default_serial"]
    names = " · ".join(_label_in(data, s) for s in picks)
    raise DeviceAmbiguous(
        f"มีมือถือเปิดใช้อยู่ {len(picks)} เครื่อง ({names}) — "
        "ต้องบอกด้วยว่าจะสั่งเครื่องไหน"
    )


# --------------------------------------------------------------------- ค่าตั้ง


def settings(serial: str) -> dict:
    """ค่าตั้งที่ใช้จริงของเครื่องนี้ = ค่ากลางของระบบ ทับด้วยค่าที่เครื่องนี้ตั้งเอง

    เขียนแบบซ้อนชั้นเพื่อให้ **ค่าตั้งใหม่ที่ใครเพิ่มทีหลังแยกรายเครื่องได้เอง**
    ใครเพิ่มคีย์ใหม่ใน config.facebook วันไหน เครื่องก็ทับค่านั้นเป็นของตัวเองได้
    วันนั้น โดยไม่ต้องกลับมาแก้ไฟล์นี้
    """
    base = {k: v for k, v in (studio_shared.read_config().get("facebook") or {}).items()
            if k not in SHARED_KEYS}
    own = (get(serial) or {}).get("settings") or {}
    return {**base, **own}


def setting(serial: str, key: str, default=None):
    value = settings(serial).get(key, default)
    return default if value is None else value


def set_settings(serial: str, values: dict) -> dict:
    """ตั้งค่าเฉพาะเครื่องนี้ — ส่ง None มาแปลว่า "เลิกตั้งเอง กลับไปใช้ค่ากลาง" """
    serial = str(serial or "").strip()

    def change(data: dict) -> None:
        device = data["devices"].get(serial)
        if device is None:
            raise DeviceUnknown(f"ไม่มีมือถือ {serial} ในทะเบียน")
        for key, value in (values or {}).items():
            if key in SHARED_KEYS:
                continue
            if value is None:
                device["settings"].pop(key, None)
            else:
                device["settings"][key] = value

    _change(change)
    return settings(serial)


def copy_settings(source: str, target: str, keys: list[str] | None = None) -> dict:
    """ก๊อปค่าตั้งจากเครื่องอื่น — ปุ่ม "โหลดค่าจากเครื่องอื่น" ในหน้าตั้งค่า

    ก๊อป **ค่าที่ใช้จริง** ของต้นทาง ไม่ใช่แค่ค่าที่ต้นทางตั้งเอง เพราะสิ่งที่ผู้ใช้
    เห็นบนหน้าจอคือค่าที่ใช้จริง ถ้าก๊อปแค่ส่วนที่ตั้งเอง ปลายทางจะได้ค่าไม่ครบ
    แล้วผู้ใช้จะงงว่า "ก๊อปมาแล้วทำไมสองเครื่องไม่เหมือนกัน"

    ไม่ก๊อป: ชื่อเครื่อง · บัญชี · สายงาน · โปรไฟล์บอท — พวกนั้นคือ **ตัวตน**
    ของเครื่อง ก๊อปตามไปเมื่อไรสองเครื่องจะกลายเป็นเครื่องเดียวกันทันที
    """
    source = str(source or "").strip()
    target = str(target or "").strip()
    if not source or not target:
        raise DeviceError("ต้องบอกทั้งเครื่องต้นทางและเครื่องปลายทาง")
    if source == target:
        raise DeviceError("ต้นทางกับปลายทางเป็นเครื่องเดียวกัน")
    if get(source) is None:
        raise DeviceUnknown(f"ไม่มีมือถือต้นทาง {source} ในทะเบียน")
    live = settings(source)
    if keys:
        live = {k: v for k, v in live.items() if k in set(keys)}
    return set_settings(target, live)


# ------------------------------------------------------------------ แก้ทะเบียน


def upsert(serial: str, **fields) -> dict:
    """เพิ่มหรือแก้เครื่องหนึ่งเครื่อง — คืนข้อมูลเครื่องนั้นหลังแก้"""
    serial = str(serial or "").strip()
    if not serial:
        raise DeviceError("ต้องระบุ serial ของมือถือ")

    def change(data: dict) -> None:
        device = data["devices"].get(serial) or blank_device(serial)
        for key, value in fields.items():
            if key in ("serial", "added_at"):
                continue
            if key == "settings" and isinstance(value, dict):
                device["settings"].update(value)
            elif key == "lanes":
                device["lanes"] = [str(x) for x in (value or []) if str(x).strip()]
            elif key == "enabled":
                device["enabled"] = bool(value)
            else:
                device[key] = value
        data["devices"][serial] = device
        # เครื่องแรกที่ถูกเปิดใช้ได้เป็นตัวหลักไปเลย ผู้ใช้จะได้ไม่ต้องมาตั้งซ้ำ
        # แต่ถ้ามีตัวหลักอยู่แล้วห้ามแย่ง — การเปิดเครื่องใหม่ไม่ควรย้ายตัวหลัก
        if not data["default_serial"] and device["enabled"]:
            data["default_serial"] = serial

    data = _change(change)
    if "name" in fields:
        _mirror_name(serial, str(fields.get("name") or ""))
    return data["devices"][serial]


def _mirror_name(serial: str, name: str) -> None:
    """เขียนชื่อเล่นกลับไปที่ `config.device_names` ด้วย — สะพานให้ของเดิม

    `fb_limits.py` กับหน้าเว็บเดิมยังอ่านชื่อจากที่นั่น ถ้าย้ายมาเก็บที่นี่อย่างเดียว
    รายงานโควตาจะโชว์ serial ดิบแทนชื่อเครื่องทันทีโดยไม่มีอะไรบอก — ล้มเงียบที่หา
    สาเหตุยากมาก ยอมเขียนสองที่ไว้ก่อนจนกว่าจะย้ายผู้อ่านครบทุกราย

    แก้เฉพาะคีย์ `device_names` ผ่าน `update_json` ห้ามอ่านทั้ง config มาเขียนทับ
    ไม่งั้นค่าที่อีกเซิร์ฟเวอร์เพิ่งบันทึกระหว่างนั้นจะหายไปเงียบๆ
    """
    def change(config: dict) -> None:
        names = config.get("device_names")
        if not isinstance(names, dict):
            names = {}
        if name:
            names[serial] = name
        else:
            names.pop(serial, None)
        config["device_names"] = names

    try:
        studio_shared.update_json(
            studio_shared.CONFIG_FILE, change, default={}, label="ชื่อเล่นมือถือ"
        )
    except Exception:                    # noqa: BLE001 — สะพานพังห้ามล้มงานหลัก
        pass


def remove(serial: str) -> bool:
    serial = str(serial or "").strip()
    gone = {"hit": False}

    def change(data: dict) -> None:
        gone["hit"] = data["devices"].pop(serial, None) is not None
        if data["default_serial"] == serial:
            live = [s for s, d in data["devices"].items() if d["enabled"]]
            data["default_serial"] = live[0] if len(live) == 1 else ""

    _change(change)
    if gone["hit"]:
        _mirror_name(serial, "")
    return gone["hit"]


def set_enabled(serial: str, on: bool) -> dict:
    device = upsert(serial, enabled=bool(on))
    if not device["enabled"]:
        # ปิดเครื่องที่เป็นตัวหลักอยู่ ต้องปลดตำแหน่งตัวหลักด้วย ไม่งั้น `resolve`
        # ที่ยอมใช้ตัวหลักจะชี้ไปเครื่องที่สั่งงานไม่ได้ แล้วล้มทุกครั้งโดยไม่บอกว่าทำไม
        def change(data: dict) -> None:
            if data["default_serial"] == serial:
                live = [s for s, d in data["devices"].items() if d["enabled"]]
                data["default_serial"] = live[0] if len(live) == 1 else ""

        _change(change)
    return device


def set_default(serial: str) -> str:
    """ตั้งเครื่องตัวหลัก — ต้องเป็นเครื่องที่เปิดใช้อยู่ ไม่งั้นตัวหลักจะสั่งงานไม่ได้"""
    serial = str(serial or "").strip()

    def change(data: dict) -> None:
        if not serial:
            data["default_serial"] = ""
            return
        device = data["devices"].get(serial)
        if device is None:
            raise DeviceUnknown(f"ไม่มีมือถือ {serial} ในทะเบียน")
        if not device["enabled"]:
            raise DeviceError(
                f"มือถือ {_label_in(data, serial)} ยังปิดใช้อยู่ — เปิดใช้ก่อน"
            )
        data["default_serial"] = serial

    _change(change)
    return serial


def sync(found: list[dict]) -> dict:
    """เอารายชื่อที่ adb เห็นตอนนี้มาปรับทะเบียน

    เครื่องที่ไม่รู้จัก **เพิ่มเข้ามาแบบปิดไว้** (กติกาข้อ 2) ส่วนเครื่องที่รู้จักอยู่แล้ว
    แค่อัปเดตชื่อรุ่นกับเวลาที่เห็นล่าสุด — ไม่แตะ `enabled` ของเดิมเด็ดขาด เพราะ
    การถอดสายชั่วคราวไม่ควรทำให้เครื่องที่ตั้งค่าไว้แล้วถูกปิดใช้ไปเอง

    คืน {"added": [...], "seen": [...]} ให้ฝั่งเรียกเอาไปบอกผู้ใช้ว่ามีเครื่องใหม่
    """
    now = _now()
    result = {"added": [], "seen": []}

    def change(data: dict) -> None:
        for item in found or []:
            serial = str((item or {}).get("serial") or "").strip()
            if not serial:
                continue
            model = str(item.get("model") or "")
            device = data["devices"].get(serial)
            if device is None:
                data["devices"][serial] = blank_device(serial, model=model, seen_at=now)
                result["added"].append(serial)
            else:
                if model:
                    device["model"] = model
                device["seen_at"] = now
                result["seen"].append(serial)

    _change(change)
    return result


def touch_screen(serial: str, width: int, height: int) -> None:
    """จำขนาดจอไว้ในทะเบียน — หน้าเว็บวางกรอบจอได้ก่อนภาพแรกจะมาถึง"""
    if int(width or 0) > 0 and int(height or 0) > 0:
        upsert(serial, screen={"w": int(width), "h": int(height)})


# ------------------------------------------------------------ ไฟล์สถานะรายเครื่อง


def state_dir(serial: str, folder: Path | None = None) -> Path:
    """โฟลเดอร์เก็บสถานะของเครื่องนี้เครื่องเดียว

    ใช้แทนไฟล์รวมทุกที่ที่ "ต้องนับแยกเครื่อง" — โควตาโพสต์ · ตัวนับล้มติดกัน ·
    สถานะโดนบล็อก ของเดิมจดรวมถังเดียว พอมีสองเครื่องเลยกลายเป็นเครื่อง A
    ใช้โควตาหมดแล้วเครื่อง B ทำงานไม่ได้ทั้งที่ยังไม่ได้เริ่ม
    """
    root = folder or studio_shared.POST_STATE
    return Path(root) / "devices" / slug(serial)


def state_file(serial: str, name: str, folder: Path | None = None) -> Path:
    """ที่อยู่ไฟล์สถานะรายเครื่อง — สร้างโฟลเดอร์ให้ด้วย เรียกแล้วเขียนได้เลย"""
    path = state_dir(serial, folder)
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return path / name


# ------------------------------------------------------------------ บรรทัดคำสั่ง


def _adb_devices(adb: str = "adb") -> list[dict]:
    """ถาม adb ว่าตอนนี้เห็นเครื่องไหนบ้าง — ใช้เฉพาะตอนสั่งจากบรรทัดคำสั่ง

    ฝั่งเซิร์ฟเวอร์มี `list_devices()` ของตัวเองอยู่แล้วและต้องใช้ตัวนั้น เพราะมันรู้
    ว่าโปรเจกต์ใช้ adb ตัวไหน (เครื่องนี้มี adb สองตัวคนละรุ่น หยิบผิดตัวเมื่อไร
    จะไล่ฆ่า adb server ของกันเองจนสั่งมือถือไม่ได้ทั้งเครื่อง — เคยเกิดมาแล้ว)
    """
    try:
        result = subprocess.run(
            [adb, "devices", "-l"], capture_output=True, timeout=15,
            creationflags=studio_shared.NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise DeviceError(f"เรียก adb ไม่สำเร็จ: {error}") from error
    out = []
    for line in result.stdout.decode("utf-8", "replace").splitlines()[1:]:
        parts = line.split()
        if len(parts) < 2 or line.startswith("*"):
            continue
        model = next((p.split(":", 1)[1] for p in parts if p.startswith("model:")), "")
        out.append({
            "serial": parts[0],
            "model": model.replace("_", " "),
            "state": parts[1],
        })
    return out


def _safe_live() -> list[dict]:
    try:
        return _adb_devices()
    except DeviceError:
        return []


def _print_list() -> int:
    data = load()
    rows = listing()
    if not rows:
        print("ทะเบียนยังว่าง — สั่ง `python devices.py sync` "
              "เพื่อดึงเครื่องที่เสียบอยู่เข้ามา")
        return 0
    live = {d["serial"]: d["state"] for d in _safe_live()}
    print(f"มือถือในทะเบียน {len(rows)} เครื่อง "
          f"(เปิดใช้ {sum(1 for r in rows if r['enabled'])} เครื่อง)\n")
    for device in rows:
        serial = device["serial"]
        mark = "⭐" if serial == data["default_serial"] else "  "
        power = "🟢 เปิดใช้" if device["enabled"] else "⚪ ปิดอยู่"
        state = live.get(serial)
        plug = "เสียบอยู่" if state == "device" else (state or "ไม่ได้เสียบ")
        lanes = ", ".join(LANES.get(x, x) for x in device["lanes"]) or "ทุกสาย"
        print(f"{mark} {power}  {_label_in(data, serial)}")
        print(f"     serial {serial} · {device['model'] or 'ไม่รู้รุ่น'} · {plug}")
        print(f"     สายงาน: {lanes} · ค่าตั้งเฉพาะเครื่อง {len(device['settings'])} ค่า"
              + (f" · เห็นล่าสุด {device['seen_at']}" if device["seen_at"] else ""))
        # บัญชีต้องเห็นทุกครั้งที่ดูรายการ — "โพสต์ลงบัญชีผิด" กู้ไม่ได้
        # ถ้าไม่โชว์ตรงนี้ คนตั้งค่าจะไม่มีทางรู้ว่าเครื่องไหนยังไม่ได้ผูก
        bound = str(device.get("account") or "").strip()
        print(f"     บัญชี: {bound or '⚠️ ยังไม่ได้ผูก — งานที่ระบุบัญชีจะไม่ยิงใส่เครื่องนี้'}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ทะเบียนมือถือของ pipeline studio")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="ดูทะเบียนทั้งหมด")
    sub.add_parser("sync", help="ดึงเครื่องที่เสียบอยู่เข้าทะเบียน (ของใหม่ปิดไว้)")
    for name, help_text in (("enable", "เปิดใช้"), ("disable", "ปิดใช้"),
                            ("default", "ตั้งเป็นเครื่องตัวหลัก"),
                            ("forget", "ลบออกจากทะเบียน"),
                            ("show", "ดูค่าตั้งที่ใช้จริงของเครื่องนี้")):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("serial")
    p = sub.add_parser("name", help="ตั้งชื่อเล่น")
    p.add_argument("serial")
    p.add_argument("text")
    p = sub.add_parser("lane", help="มอบหมายสายงาน (คั่นด้วยจุลภาค · ว่าง = ทุกสาย)")
    p.add_argument("serial")
    p.add_argument("lanes")
    p = sub.add_parser("account", help="ผูกบัญชีที่ล็อกอินบนเครื่องนี้ (หนึ่งเครื่อง = หนึ่งไอดี)")
    p.add_argument("serial")
    p.add_argument("name")
    p = sub.add_parser("copy", help="ก๊อปค่าตั้งจากเครื่องหนึ่งไปอีกเครื่อง")
    p.add_argument("source")
    p.add_argument("target")

    args = parser.parse_args(argv)
    try:
        if args.command == "list":
            return _print_list()
        if args.command == "sync":
            result = sync(_adb_devices())
            for serial in result["added"]:
                print(f"➕ เจอเครื่องใหม่ {serial} — เพิ่มเข้าทะเบียนแบบ **ปิดไว้ก่อน**")
            print(f"อัปเดตแล้ว: ของใหม่ {len(result['added'])} · "
                  f"ที่รู้จักอยู่แล้ว {len(result['seen'])}\n")
            return _print_list()
        if args.command in ("enable", "disable"):
            device = set_enabled(args.serial, args.command == "enable")
            print(f"{'เปิดใช้' if device['enabled'] else 'ปิดใช้'} "
                  f"{label(args.serial)} แล้ว")
            return 0
        if args.command == "default":
            set_default(args.serial)
            print(f"⭐ ตั้ง {label(args.serial)} เป็นเครื่องตัวหลักแล้ว")
            return 0
        if args.command == "forget":
            print("ลบออกจากทะเบียนแล้ว" if remove(args.serial)
                  else "ไม่มีเครื่องนี้ในทะเบียน")
            return 0
        if args.command == "name":
            upsert(args.serial, name=args.text.strip()[:40])
            print(f"ตั้งชื่อเป็น {label(args.serial)} แล้ว")
            return 0
        if args.command == "lane":
            lanes = [x.strip() for x in args.lanes.split(",") if x.strip()]
            upsert(args.serial, lanes=lanes)
            print(f"{label(args.serial)} รับสาย: "
                  + (", ".join(LANES.get(x, x) for x in lanes) or "ทุกสาย"))
            return 0
        if args.command == "account":
            wanted = args.name.strip()[:60]
            # กันผูกบัญชีเดียวกันสองเครื่องตั้งแต่ตอนตั้งค่า ไม่ใช่ไปเจอตอนโพสต์
            clash = [s for s in (accounts().get(wanted) or []) if s != args.serial]
            if clash:
                where = " · ".join(f"{label(s)} [{s}]" for s in clash)
                raise DeviceError(
                    f"บัญชี '{wanted}' ผูกอยู่กับ {where} แล้ว — "
                    f"หนึ่งเครื่องต่อหนึ่งไอดี ถ้าย้ายเครื่องให้ล้างของเดิมก่อนด้วย\n"
                    f"    python devices.py account {clash[0]} \"\"")
            upsert(args.serial, account=wanted)
            print(f"ผูก {label(args.serial)} เข้ากับบัญชี "
                  + (f"'{wanted}'" if wanted else "— (ล้างการผูกแล้ว)"))
            return 0
        if args.command == "copy":
            merged = copy_settings(args.source, args.target)
            print(f"ก๊อปค่าตั้ง {len(merged)} ค่า จาก {label(args.source)} "
                  f"ไป {label(args.target)} แล้ว")
            return 0
        if args.command == "show":
            own_keys = (get(args.serial) or {}).get("settings") or {}
            print(f"ค่าตั้งที่ใช้จริงของ {label(args.serial)}:")
            for key, value in sorted(settings(args.serial).items()):
                print(f"  {key:16s} = {value!r}  "
                      f"{'(ตั้งเอง)' if key in own_keys else '(ค่ากลาง)'}")
            return 0
    except DeviceError as error:
        print(f"❌ {error}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
