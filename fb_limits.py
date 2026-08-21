"""เพดานการคอมเมนต์ — **ตั้งแยกได้รายบัญชี** ทั้งรายชั่วโมงและรายวัน

**ปัญหาที่แก้** เพดานทั้งสองตัวเคยเป็นค่าคงที่ฝังในโค้ด (`COMMENT_LIMIT_PER_HOUR`
ใน facebook_group_post และ `DAILY_LIMIT` ใน fb_comment_guard) ซึ่งใช้ได้ตอนมี
บัญชีเดียว แต่ฟาร์มบอทมีหลายบัญชี และ **Facebook ให้เพดานไม่เท่ากันในแต่ละบัญชี**
(บัญชีใหม่/บัญชีที่เคยโดนตีธงจะโดนรัดกว่ามาก) ตั้งค่าเดียวใช้ทุกบัญชีจึงต้องเลือก
ระหว่าง "รัดจนบัญชีแข็งแรงทำงานไม่เต็มที่" กับ "หลวมจนบัญชีอ่อนโดนบล็อก"

ไฟล์นี้เป็น **แหล่งจริงแหล่งเดียว** ของเพดานทั้งหมด อีกสองไฟล์นั้นมาอ่านที่นี่

**ค่าตั้งต้นเท่าของเดิมทุกตัว** — ติดตั้งวันแรกพฤติกรรมต้องไม่เปลี่ยนเลย
ใครไม่เคยตั้งอะไรก็ได้ 12/ชั่วโมง 50/วัน แบ่งเลน post 8 · reply 4 เหมือนเดิม

**ที่มาของตัวเลขตั้งต้น — ห้ามแก้โดยไม่อ่าน**

`per_day` 50 เป็นการตัดสินใจของเจ้าของงาน 18 ส.ค. 2026 หลังชนเพดาน 40 สองวันติด
หลักฐานทั้งหมดที่มี (ทุกวันที่เก็บ log ได้):

     8 คอมเมนต์  → ล้ม 4 ครั้ง (11 ส.ค.)   ← ยอดรายวันไม่ใช่ตัวแปรเดียว
    17-28       → ปกติ
    40          → ปกติ (17 ส.ค.)  ← สูงสุดที่พิสูจน์แล้วว่าผ่าน
    58          → โดนบล็อก 21 ชั่วโมง (16 ส.ค.)

50 จึงอยู่ในโซนที่ยังไม่เคยทดลอง ห่างจากตัวที่พังจริงแค่ 8 ครั้ง — ที่พึ่งได้จริง
คือด่านล้ม-3-ครั้งใน fb_comment_guard ซึ่งตัดสินจากอาการจริงไม่ใช่เดาเกณฑ์

**ไฟล์นี้ไม่แตะ ADB และไม่ import โมดูลของสายงานไหน** — รับชื่อบัญชีเข้ามา
คืนตัวเลขออกไป จึงเทสได้โดยไม่ต้องมีมือถือ
"""

from __future__ import annotations

import json
import re

import studio_shared

# **ไฟล์นี้เป็นค่าเซ็ตติง จึงอยู่ในเครื่อง ไม่ขึ้น Google Drive** (เจ้าของงานสั่ง
# 19 ส.ค. 2026) กติกาคือ Drive เก็บรูป/คลิป/ข้อมูลผลงาน ส่วนค่าที่ใช้ทำงานอยู่ใน
# เครื่อง — ที่เดียวกับ `config.json` · `fb_mass_config.json` · `fb_engage_config.json`
#
# **เป็นเรื่องความปลอดภัยด้วย ไม่ใช่แค่การจัดระเบียบ** ถ้าไฟล์นี้อยู่บน Drive แล้ว
# วันไหน Drive ไม่พร้อม (ไม่ได้รัน/เน็ตหลุด/ยังไม่ล็อกอิน) `POST_DIR` จะถอยไป
# `data/` ตามที่ studio_shared ออกแบบไว้ แล้วหาไฟล์นี้ไม่เจอ → `load()` สร้างใหม่
# เป็นค่าตั้งต้นเงียบๆ  บัญชีที่ตั้งรัดไว้ (เช่น 20/วัน) จะเด้งกลับเป็น 50/วันโดย
# ไม่มีใครรู้ = ยิงเกินจนโดนบล็อกทั้งที่ตั้งกันไว้แล้ว
# อยู่ในเครื่องแล้วค่าที่ตั้งไว้อยู่ครบเสมอ ไม่ขึ้นกับว่า Drive พร้อมไหม
LIMITS_FILE = studio_shared.DATA_DIR / "fb_comment_limits.json"

# ค่าตั้งต้นของทุกบัญชีที่ไม่ได้ตั้งเอง — ตรงกับพฤติกรรมเดิมก่อนมีไฟล์นี้
DEFAULTS: dict = {
    "per_hour": 12,
    "per_day": 50,
    # แบ่งเพดานรายชั่วโมงให้แต่ละสายงาน **รวมกันต้องไม่เกิน per_hour**
    # post = งานโพสต์ที่ผู้ใช้สั่ง · reply = บอทตอบคอมเมนต์คนอื่น (งานเบื้องหลัง)
    "lanes": {"post": 8, "reply": 4},
}

DEFAULT_LANE = "post"


class LimitError(ValueError):
    """ค่าที่ตั้งใช้ไม่ได้ — ตั้งใจให้พังเสียงดังตรงจุดที่ตั้ง ไม่ใช่ไปพังตอนคอมเมนต์"""


def _blank() -> dict:
    return {"default": json.loads(json.dumps(DEFAULTS)), "accounts": {}}


def load() -> dict:
    """อ่านค่าที่ตั้งไว้ — ไฟล์หายหรือพังยังไงก็ต้องคืนโครงที่ใช้งานได้

    ไม่มีไฟล์ = เขียนค่าตั้งต้นลงไปให้เลย ผู้ใช้จะได้เปิดดูแล้วรู้ว่าแก้อะไรได้บ้าง
    """
    raw = studio_shared.read_json(LIMITS_FILE, None)
    if not isinstance(raw, dict):
        fresh = _blank()
        save(fresh)
        return fresh
    data = _blank()
    if isinstance(raw.get("default"), dict):
        data["default"].update(_clean(raw["default"], strict=False))
    if isinstance(raw.get("accounts"), dict):
        for key, value in raw["accounts"].items():
            if isinstance(value, dict):
                data["accounts"][str(key)] = _clean(value, strict=False)
    return data


def save(data: dict) -> None:
    """เขียนแบบที่อีกโปรเซสไม่มีวันอ่านเจอไฟล์ครึ่งๆ (ล็อกรายไฟล์ + เขียนอะตอมมิก)"""
    with studio_shared.data_lock(LIMITS_FILE.name, label="fb_limits เขียนเพดาน"):
        studio_shared.write_json_atomic(LIMITS_FILE, data)


def _clean(value: dict, strict: bool = True) -> dict:
    """คัดเฉพาะช่องที่รู้จักและเป็นตัวเลขที่ใช้ได้

    `strict=False` ใช้ตอนอ่านไฟล์ — ค่าเสียหนึ่งช่องต้องไม่ทำให้ทั้งไฟล์ใช้ไม่ได้
    แค่ข้ามช่องนั้นแล้วตกไปใช้ค่าตั้งต้น  `strict=True` ใช้ตอนผู้ใช้สั่งตั้งค่า
    ซึ่งต้องเถียงกลับทันทีถ้าใส่ค่าที่ใช้ไม่ได้
    """
    out: dict = {}
    for key in ("per_hour", "per_day"):
        if key not in value:
            continue
        try:
            number = int(value[key])
        except (TypeError, ValueError):
            if strict:
                raise LimitError(f"{key} ต้องเป็นจำนวนเต็ม (ได้ {value[key]!r})")
            continue
        if number < 1:
            if strict:
                raise LimitError(f"{key} ต้องมากกว่า 0 (ได้ {number})")
            continue
        out[key] = number
    lanes = value.get("lanes")
    if isinstance(lanes, dict):
        kept: dict = {}
        for lane, share in lanes.items():
            try:
                number = int(share)
            except (TypeError, ValueError):
                if strict:
                    raise LimitError(f"ช่องของเลน {lane} ต้องเป็นจำนวนเต็ม")
                continue
            if number < 0:
                if strict:
                    raise LimitError(f"ช่องของเลน {lane} ติดลบไม่ได้")
                continue
            kept[str(lane)] = number
        if kept:
            out["lanes"] = kept
    return out


def limits(account: str = "") -> dict:
    """เพดานที่ใช้จริงของบัญชีนั้น — ซ้อนกันสามชั้น ค่าตั้งต้น ← default ← บัญชี

    ซ้อนทีละช่อง ไม่ใช่ทับทั้งก้อน — ตั้งเฉพาะ per_day ของบัญชีหนึ่งแล้ว per_hour
    กับ lanes ต้องยังเป็นค่าส่วนกลาง ไม่ใช่หายไปกลายเป็นค่าตั้งต้นดิบ
    """
    data = load()
    merged = json.loads(json.dumps(DEFAULTS))
    for layer in (data.get("default") or {},
                  (data.get("accounts") or {}).get(str(account or ""), {})):
        for key, value in (layer or {}).items():
            if key == "lanes" and isinstance(value, dict):
                merged["lanes"] = {**merged["lanes"], **value}
            else:
                merged[key] = value
    return merged


def per_hour(account: str = "") -> int:
    """เพดานรวมต่อชั่วโมงของบัญชีนั้น — ทุกเลนรวมกันห้ามเกินค่านี้"""
    return int(limits(account)["per_hour"])


def per_day(account: str = "") -> int:
    """เพดานต่อวันของบัญชีนั้น"""
    return int(limits(account)["per_day"])


def lane_limit(lane: str = DEFAULT_LANE, account: str = "") -> int:
    """ช่องของเลนนั้น — เลนที่ไม่รู้จักได้ช่องของสายโพสต์ (ทางที่ปลอดภัยกว่า)"""
    lanes = limits(account)["lanes"]
    return int(lanes.get(lane, lanes.get(DEFAULT_LANE, DEFAULTS["lanes"][DEFAULT_LANE])))


def set_limits(account: str = "", per_hour: int | None = None,
               per_day: int | None = None, lanes: dict | None = None) -> dict:
    """ตั้งเพดาน — `account` ว่าง = ตั้งค่าส่วนกลางที่ทุกบัญชีใช้ร่วมกัน

    คืนเพดานที่ใช้จริงหลังตั้งเสร็จ เพื่อให้ผู้เรียกเอาไปแสดงได้โดยไม่ต้องอ่านซ้ำ
    """
    patch: dict = {}
    if per_hour is not None:
        patch["per_hour"] = per_hour
    if per_day is not None:
        patch["per_day"] = per_day
    if lanes is not None:
        patch["lanes"] = lanes
    if not patch:
        raise LimitError("ไม่ได้บอกว่าจะตั้งอะไร")
    patch = _clean(patch, strict=True)

    data = load()
    key = str(account or "")
    target = data["accounts"].setdefault(key, {}) if key else data["default"]
    for name, value in patch.items():
        if name == "lanes" and isinstance(target.get("lanes"), dict):
            target["lanes"] = {**target["lanes"], **value}
        else:
            target[name] = value
    save(data)
    return limits(account)


def forget(account: str) -> bool:
    """เอาค่าเฉพาะของบัญชีนั้นออก กลับไปใช้ค่าส่วนกลาง — False = ไม่เคยตั้งไว้"""
    data = load()
    if str(account) not in data["accounts"]:
        return False
    data["accounts"].pop(str(account))
    save(data)
    return True


def accounts() -> dict:
    """บัญชีที่ตั้งค่าเฉพาะไว้ {ชื่อบัญชี: ค่าที่ตั้ง}"""
    return load()["accounts"]


def warnings(account: str = "") -> list[str]:
    """ค่าที่ตั้งไว้มีตรงไหนขัดกันเองไหม — ว่าง = ไม่มีปัญหา

    **เตือน ไม่ใช่แก้ให้เอง** — แก้ค่าที่ผู้ใช้ตั้งเงียบๆ คือทำให้ตัวเลขที่เห็น
    ในไฟล์ไม่ตรงกับที่ทำงานจริง ซึ่งไล่ปัญหายากกว่าการตั้งผิดเสียอีก
    ตัวคุมจริงที่กันไม่ให้ยิงเกินอยู่ที่ comment_quota_left() ซึ่งเอาค่าน้อยสุด
    ระหว่างช่องของเลนกับเพดานรวมเสมอ
    """
    setting = limits(account)
    notes: list[str] = []
    total = sum(int(x) for x in setting["lanes"].values())
    if total > setting["per_hour"]:
        notes.append(
            f"ช่องของทุกเลนรวมกัน {total} เกินเพดานรวมต่อชั่วโมง "
            f"{setting['per_hour']} — เลนท้ายๆ จะถูกเพดานรวมตัดก่อนใช้ช่องตัวเองหมด")
    elif total < setting["per_hour"]:
        notes.append(
            f"ช่องของทุกเลนรวมกัน {total} น้อยกว่าเพดานรวม {setting['per_hour']} "
            f"— เหลือ {setting['per_hour'] - total} ช่องที่ไม่มีสายไหนใช้ได้")
    if setting["per_day"] < setting["per_hour"]:
        notes.append(
            f"เพดานต่อวัน {setting['per_day']} น้อยกว่าต่อชั่วโมง "
            f"{setting['per_hour']} — เพดานรายชั่วโมงจะไม่มีความหมายเลย")
    return notes


def _label(account: str) -> str:
    """ชื่อที่มนุษย์อ่านออกของบัญชี/เครื่องนั้น (ไม่มีชื่อก็คืนตัว key เดิม)"""
    if not account:
        return "ค่าส่วนกลาง"
    try:
        names = studio_shared.read_config().get("device_names") or {}
    except Exception:
        names = {}
    name = str(names.get(account) or "").strip()
    return f"{account} ({name})" if name else str(account)


def describe(account: str = "") -> list[str]:
    """สรุปเพดานเป็นบรรทัดพร้อมแสดงใน Telegram (ยังไม่ใส่ HTML)"""
    setting = limits(account)
    lanes = " · ".join(f"{lane} {share}"
                       for lane, share in sorted(setting["lanes"].items()))
    lines = [
        f"บัญชี: {_label(account)}",
        f"ต่อชั่วโมง: {setting['per_hour']} (แบ่งเป็น {lanes})",
        f"ต่อวัน: {setting['per_day']}",
    ]
    lines.extend(f"⚠️ {note}" for note in warnings(account))
    return lines


def _slug(text: str) -> str:
    """ชื่อบัญชีให้เป็นชื่อไฟล์ที่ Windows รับได้ (เผื่อวันหน้าที่แยกถังรายบัญชี)"""
    return re.sub(r"[^A-Za-z0-9._-]", "_", str(text).strip())[:60]
