"""ตามเก็บยอดโพสต์เก่า + ตอบกลับคอมเมนต์ของคนอื่น

สองงานนี้อยู่โมดูลเดียวกันเพราะทำกับ**ของชิ้นเดียวกัน**: ลิงก์โพสต์ที่เคยเก็บไว้
ในงานของสายโพสต์ และทั้งคู่ต้องใช้จอมือถือเครื่องเดียวกัน แยกเป็นสองตัวจะกลาย
เป็นสองผู้ใช้จอที่ต้องมากันชนกันเองอีกชั้น

**เรื่องจอมือถือ — อ่านก่อนแก้ไฟล์นี้**

ตอนนี้มีสี่โปรเซสในเครื่อง: `app.py` (สายโพสต์) · `clip_app.py` (สายคลิป) ·
`fb_mass_bot.py` (หาโพสต์แมส ใช้ **เบราว์เซอร์** ไม่ใช่ ADB) และตัวนี้
ผู้ใช้ ADB จริงๆ จึงมีสองราย: `app.py` กับโมดูลนี้

`PhoneGate` ใน app.py กันได้แค่ภายในโปรเซสตัวเอง โมดูลนี้จึงกันสองชั้น:

  1. `studio_shared.phone_lock()` — ล็อกระดับ OS กันข้ามโปรเซส
     ฝั่ง `fb_auto_post.PostRunner` ต่อสายเข้าล็อกนี้แล้วทั้ง 4 ทาง
     **โมดูลนี้ถือล็อกทีละโพสต์แล้วปล่อย** ไม่ถือยาวทั้งรอบ ไม่งั้นงานโพสต์ของ
     ผู้ใช้จะรอเกิน 2 นาทีแล้วล้ม ทั้งที่แค่ต้องรอเราจบโพสต์ปัจจุบัน
  2. ถาม `app.py` ผ่าน HTTP ว่ามีงานโพสต์รันอยู่ไหม **และถามซ้ำก่อนขึ้นโพสต์
     ใหม่ทุกใบ** เจอว่ามีเมื่อไรก็ถอยทันที — ล็อกบอกได้แค่ "มีคนถืออยู่ไหม"
     ไม่รู้ว่าคิวฝั่งโน้นยาวแค่ไหน งานของโมดูลนี้เป็นงานเบื้องหลัง หยุดกลางคัน
     แล้วมาต่อรอบหน้าได้ ต่างจากงานโพสต์ที่ขาดตอนแล้วเสียของจริง

**สถานะ: เขียนแล้วแต่ยังไม่ได้ทดสอบกับมือถือ** — เขียนตอน session อื่นใช้ ADB อยู่
ส่วนที่ยกมาจากของที่ทดสอบแล้ว (เปิดโพสต์จากลิงก์ · อ่านยอด · เขียนคอมเมนต์)
เชื่อได้ตามเดิม แต่**ขั้นตอบกลับคอมเมนต์ยังไม่เคยเห็นหน้าจอจริง** — ดูหมายเหตุ
ที่ `reply_to_comment()`
"""

from __future__ import annotations

import json
import subprocess
import time
import urllib.request
import zlib
from datetime import datetime, timedelta
from pathlib import Path

import facebook_group_post as fb
import studio_shared

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
CONFIG_FILE = DATA_DIR / "fb_engage_config.json"
STATS_FILE = DATA_DIR / "fb_post_stats.json"
REPLIES_FILE = DATA_DIR / "fb_replies.json"
JOBS_FILE = DATA_DIR / "fb_jobs.json"
STUDIO_API = "http://127.0.0.1:8866"


class EngageError(RuntimeError):
    """ข้อผิดพลาดที่ตั้งใจส่งข้อความให้ผู้ใช้อ่านตรงๆ"""


DEFAULT_CONFIG = {
    # ชื่อบอทในทะเบียน extra_bots ของ Studio (ว่าง = ใช้บอทหลัก)
    "telegram_bot": "",
    # ว่าง = ใช้มือถือเครื่องแรกที่ต่ออยู่
    "serial": "",
    # ชื่อบัญชีที่ใช้โพสต์ — ใช้แยกว่าคอมเมนต์ไหนเป็นของเราเอง **ต้องตั้งอย่างน้อย 1**
    # ไม่ตั้ง = ไม่ยอมตอบกลับอะไรเลย กันบอทไปตอบคอมเมนต์ตัวเองวนไม่จบ
    #
    # **เก็บได้หลายบัญชี** เพราะผู้ใช้โพสต์จากหลายบัญชี (ฟาร์มบอทมี 10 โปรไฟล์)
    # ถ้าจำได้บัญชีเดียว คอมเมนต์ของบัญชีอื่นของเราเองจะถูกมองเป็นของคนนอก
    # แล้วบอทจะไปตอบตัวเองวนไม่จบ ซึ่งเป็นสิ่งที่ค่านี้มีไว้กันตั้งแต่แรก
    "owner_names": [],
    # ของเดิมเป็นช่องเดียว — เก็บไว้ให้ค่าที่ตั้งไว้แล้วไม่หาย อ่านผ่าน owner_list()
    "owner_name": "",
    # เก็บยอดซ้ำเมื่อผ่านไปกี่ชั่วโมง — ถี่กว่านี้เปลืองเวลาจอโดยไม่ได้ข้อมูลใหม่
    "refresh_hours": 6,
    # ต่อหนึ่งรอบเก็บยอดกี่โพสต์ — โพสต์ละราว 30-50 วินาที
    "max_posts_per_round": 8,
    # นับคอมเมนต์เองเมื่อแอปไม่บอกตัวเลข (ช้าขึ้นราว 20 วินาที/โพสต์)
    "count_comments": True,
    # น้ำหนักคะแนน "แมส"
    #
    # คอมเมนต์กับแชร์หนักกว่าไลก์เพราะต้องลงแรงมากกว่า และเป็นสัญญาณที่
    # Facebook ใช้ดันโพสต์มากกว่าไลก์เปล่าๆ — ปรับได้ตามที่ผู้ใช้เห็นจริง
    "mass_weights": {"reactions": 1, "comments": 3, "shares": 5},
    # คะแนนที่ถือว่า "แมส"
    "mass_score": 30,
    # ── ฝั่งตอบกลับคอมเมนต์ ──
    "reply_enabled": False,          # ต้องเปิดเองเสมอ ไม่เปิดให้อัตโนมัติ
    "max_replies_per_round": 5,
    # ตอบตามคำที่เจอก่อน ถ้าไม่เข้าเงื่อนไขไหนค่อยใช้ replies
    "rules": [
        {"keywords": ["ราคา", "เท่าไหร่", "กี่บาท"],
         "reply": "กดดูราคาล่าสุดในลิงก์ได้เลยค่ะ เดี๋ยวนี้ลดอยู่พอดี 🙏"},
        {"keywords": ["ลิงก์", "ลิ้ง", "link", "ซื้อที่ไหน"],
         "reply": "ลิงก์อยู่ในคอมเมนต์แรกเลยค่ะ กดได้เลย 🛒"},
    ],
    "replies": [
        "ขอบคุณที่แวะมาดูนะคะ 🙏",
        "สนใจทักได้เลยค่ะ เดี๋ยวแนะนำให้ 😊",
    ],
    # เจอคำพวกนี้ = **ไม่ตอบ** ปล่อยให้คนจริงมาจัดการ
    #
    # บอทตอบคำถามยากหรือคำต่อว่าแบบสำเร็จรูปมีแต่ทำให้แย่ลง
    "skip_keywords": ["โกง", "หลอก", "แจ้งความ", "คืนเงิน", "ของปลอม", "ห่วย"],
    # เดินรอบเก็บยอดเองอัตโนมัติไหม
    "auto": False,
    "auto_every_minutes": 180,
}


# ------------------------------------------------------------- ไฟล์ตั้งค่า

def _read_json(path: Path, fallback):
    return studio_shared.read_json(path, fallback)


def _write_json(path: Path, value) -> None:
    """เขียนแบบที่อีกเธรด/โปรเซสไม่มีวันอ่านเจอไฟล์ครึ่งๆ

    ของเดิมเขียนทับตรงๆ ด้วย write_text ซึ่งตัดไฟล์ให้ว่างก่อนแล้วค่อยเขียนใหม่
    ระหว่างนั้นถ้าอีกฝั่งอ่านจะได้ไฟล์ครึ่งๆ แล้ว `_read_json` จะกลืนแล้วคืนค่าตั้งต้น
    เงียบๆ — แปลว่า **ยอดที่เก็บมาทั้งหมดหายไปเฉยๆ** โดยไม่มี error

    เกิดได้จริงเพราะ `refresh_stats` เขียนไฟล์ยอด **ทุกโพสต์** (บรรทัด ~327)
    ขณะที่เธรดคำสั่งของบอทอ่านไฟล์เดียวกันตอนสั่ง /mass หรือ /set

    ถือล็อกรายไฟล์ด้วย เพราะเธรดรอบอัตโนมัติกับเธรดคำสั่งเขียนไฟล์เดียวกันได้
    """
    with studio_shared.data_lock(path.name, label=f"fb_engage เขียน {path.name}"):
        studio_shared.write_json_atomic(path, value)


def load_config() -> dict:
    config = _read_json(CONFIG_FILE, None)
    if config is None:
        _write_json(CONFIG_FILE, DEFAULT_CONFIG)
        return json.loads(json.dumps(DEFAULT_CONFIG))
    # เติม key ที่ขาด — ตั้งค่าเก่าต้องไม่พังเมื่อโค้ดใหม่เพิ่ม key
    for key, value in DEFAULT_CONFIG.items():
        config.setdefault(key, value)
    return config


def save_config(config: dict) -> None:
    _write_json(CONFIG_FILE, config)


def owner_list(config: dict) -> list[str]:
    """ชื่อบัญชีของเราทั้งหมด — รวมช่องเดิม (owner_name) กับช่องใหม่ (owner_names)

    อ่านสองช่องรวมกันเสมอ ไม่ใช่เลือกอันใดอันหนึ่ง เพราะค่าที่ผู้ใช้ตั้งไว้ก่อน
    อัปเดตอยู่ในช่องเดิม ถ้าอ่านแต่ช่องใหม่ = ชื่อที่เคยตั้งหายไปเงียบๆ แล้วบอท
    จะกลับไปตอบคอมเมนต์ตัวเองวนไม่จบ ซึ่งคือสิ่งที่ค่านี้มีไว้กัน

    ตัดชื่อซ้ำแบบไม่สนตัวพิมพ์ และคงลำดับที่ผู้ใช้ใส่ไว้
    """
    names: list[str] = []
    seen: set[str] = set()
    raw = [config.get("owner_name")] + list(config.get("owner_names") or [])
    for item in raw:
        name = str(item or "").strip()
        if not name or name.casefold() in seen:
            continue
        seen.add(name.casefold())
        names.append(name)
    return names


def is_owner(author: str, owners: list[str]) -> bool:
    """คอมเมนต์นี้เป็นของบัญชีเราเองไหม

    เทียบแบบ "ชื่อเราอยู่ในชื่อผู้เขียน" เหมือนเดิม เพราะ Facebook เติมคำต่อท้าย
    ให้บ่อย (เช่น "ผู้เขียน", "ผู้ดูแล") การเทียบเท่ากันเป๊ะจะพลาดทุกครั้ง
    """
    low = (author or "").casefold()
    return any(name.casefold() in low for name in owners)


# --------------------------------------------------------- โพสต์ที่ต้องตาม

def post_targets() -> list[dict]:
    """โพสต์ทุกใบที่เคยลงสำเร็จ **และมีลิงก์** — ลิงก์คือทางเดียวที่เปิดกลับได้ตรงใบ

    อ่านจากไฟล์งานของสายโพสต์ตรงๆ ไม่ผ่าน API เพราะไฟล์นี้เป็นแหล่งจริง และ
    โมดูลนี้ต้องทำงานได้แม้ app.py ปิดอยู่
    """
    raw = _read_json(JOBS_FILE, [])
    jobs = raw if isinstance(raw, list) else (raw.get("jobs") or [])
    found: list[dict] = []
    for job in jobs:
        caption = (job.get("caption") or "").strip()
        for entry in (job.get("results") or []):
            if not (entry.get("posted") and entry.get("link")):
                continue
            found.append({
                "key": f"{job['id']}|{entry['group_id']}",
                "job_id": job["id"],
                "group_id": entry["group_id"],
                "caption": caption,
                "link": entry["link"],
                "post_id": entry.get("post_id", ""),
                "posted_at": job.get("finished_at") or job.get("created_at", ""),
            })
    return found


# ------------------------------------------------------------ ด่านกันแย่งจอ

def phone_busy_elsewhere() -> str:
    """'' = จอว่าง · ข้อความ = มีงานอื่นใช้อยู่

    ถาม app.py เพราะงานโพสต์อยู่ในโปรเซสนั้น ล็อกไฟล์ยังกันไม่ถึง (app.py
    ยังไม่ได้ต่อสายเข้า phone_lock)

    ⚠️ ข้อจำกัดที่รู้ตัว: ดูได้แค่ `fb_runner.busy` — ฝั่ง Claude CLI ที่จอง
    `phone_gate` ไว้ยังไม่มี endpoint ให้ถาม ถ้าจะปิดช่องนี้ให้สนิทต้องเพิ่ม
    endpoint ที่ app.py แล้วมาอ่านเพิ่ม

    ต่อ app.py ไม่ได้ = ถือว่าว่าง เพราะบอทนี้ต้องทำงานได้แม้ Studio ปิดอยู่
    """
    try:
        with urllib.request.urlopen(f"{STUDIO_API}/api/fb/jobs", timeout=6) as page:
            data = json.load(page)
    except (OSError, ValueError):
        return ""
    return "สายโพสต์กำลังใช้จออยู่" if data.get("running") else ""


def resolve_serial(config: dict) -> str:
    """เลขเครื่องที่จะสั่ง — ตั้งเองได้ ไม่ตั้งก็เอาเครื่องแรกที่ต่ออยู่"""
    wanted = str(config.get("serial") or "").strip()
    try:
        out = subprocess.run(
            ["adb", "devices"], capture_output=True, text=True, timeout=30,
            encoding="utf-8", errors="replace", creationflags=studio_shared.NO_WINDOW).stdout
    except (OSError, subprocess.SubprocessError) as error:
        raise EngageError(f"เรียก adb ไม่ได้: {error}") from error
    online = [
        line.split("\t")[0] for line in out.splitlines()[1:]
        if line.strip().endswith("\tdevice")
    ]
    if wanted:
        if wanted not in online:
            raise EngageError(f"ไม่เจอมือถือ {wanted} (ที่ต่ออยู่: {online or 'ไม่มี'})")
        return wanted
    if not online:
        raise EngageError("ไม่มีมือถือเชื่อมต่ออยู่")
    return online[0]


# ---------------------------------------------------------------- เก็บยอด

def load_stats() -> dict:
    return _read_json(STATS_FILE, {})


def _due(record: dict, hours: float) -> bool:
    history = record.get("history") or []
    if not history:
        return True
    try:
        last = datetime.fromisoformat(history[-1]["at"])
    except (ValueError, KeyError):
        return True
    return datetime.now() - last >= timedelta(hours=hours)


def refresh_stats(config: dict, log=print, stop=lambda: False,
                  limit: int | None = None) -> dict:
    """ไล่เปิดโพสต์เก่าแล้วบันทึกยอดลงประวัติ คืนสรุปของรอบนี้

    บันทึกเป็น **ประวัติ** ไม่ใช่ค่าล่าสุดค่าเดียว เพราะ "แมส" ดูจากการโตด้วย
    ไม่ใช่ยอดสะสมอย่างเดียว โพสต์เก่าที่ยอดสูงเพราะอยู่มานานไม่เท่ากับโพสต์ใหม่
    ที่พุ่งใน 6 ชั่วโมง
    """
    busy = phone_busy_elsewhere()
    if busy:
        raise EngageError(f"ยังทำไม่ได้ — {busy}")
    serial = resolve_serial(config)
    stats = load_stats()
    targets = post_targets()
    due = [t for t in targets if _due(stats.get(t["key"], {}),
                                      float(config.get("refresh_hours", 6)))]
    cap = limit or int(config.get("max_posts_per_round", 8))
    due = due[:max(1, cap)]
    if not due:
        return {"checked": 0, "updated": 0, "total": len(targets), "failed": 0}

    updated = failed = 0
    phone = fb.Phone("adb", serial, log=log)
    log(f"เริ่มเก็บยอด {len(due)} โพสต์ (ทั้งหมดที่ตามอยู่ {len(targets)})")
    for index, target in enumerate(due, start=1):
        if stop():
            log("ผู้ใช้สั่งหยุด")
            break
        # ถามซ้ำทุกใบ — งานโพสต์สำคัญกว่า เจอเมื่อไรถอยทันที
        busy = phone_busy_elsewhere()
        if busy:
            log(f"{busy} — หยุดรอบนี้ไว้ก่อน ค่อยมาต่อรอบหน้า")
            break
        log(f"[{index}/{len(due)}] {target['key']}")
        record = stats.setdefault(target["key"], {
            "job_id": target["job_id"], "group_id": target["group_id"],
            "caption": target["caption"][:120], "link": target["link"],
            "posted_at": target["posted_at"], "history": [],
        })
        # **ถือล็อกทีละโพสต์แล้วปล่อย** ไม่ใช่ถือยาวทั้งรอบ
        #
        # ถือยาว = งานโพสต์ที่ผู้ใช้สั่งจะรอเกิน PHONE_LOCK_WAIT (2 นาที) แล้วล้ม
        # ทั้งที่แค่ต้องรอเราจบโพสต์ปัจจุบัน — ปล่อยทุกใบทำให้รอไม่เกิน ~40 วินาที
        with studio_shared.phone_lock(serial, label=f"fb_engage เก็บยอด {target['key']}"):
            fb.require_network(phone)
            if not fb.open_post_link(phone, target["link"], target["caption"],
                                     target["group_id"], target["post_id"]):
                record["last_error"] = "เปิดโพสต์จากลิงก์ไม่ได้"
                failed += 1
                continue
            numbers = fb.read_post_stats(
                phone, target["caption"], single_post=True,
                count_rows=bool(config.get("count_comments", True)),
            )
        if not numbers:
            record["last_error"] = "เปิดได้แต่อ่านแถวตัวนับไม่ได้"
            failed += 1
            continue
        record.pop("last_error", None)
        record["history"].append({
            "at": datetime.now().isoformat(timespec="seconds"),
            "reactions": numbers.get("reactions"),
            "comments": numbers.get("comments"),
            "shares": numbers.get("shares"),
        })
        # เก็บย้อนหลังพอให้ดูแนวโน้มได้ ไม่ให้ไฟล์บวมไม่จบ
        record["history"] = record["history"][-40:]
        updated += 1
        log(f"  {fb.format_stats(numbers)}")
        _write_json(STATS_FILE, stats)      # เขียนทุกใบ ล้มกลางคันแล้วของที่เก็บมาไม่หาย
    _write_json(STATS_FILE, stats)
    return {"checked": len(due), "updated": updated,
            "total": len(targets), "failed": failed}


# ------------------------------------------------------------ หาโพสต์แมส

def _score(sample: dict, weights: dict) -> int:
    """คะแนนของหนึ่งจุดเวลา — ค่าที่อ่านไม่ได้นับเป็น 0 แต่ไม่ถือว่ายืนยันแล้ว"""
    return sum(int(sample.get(key) or 0) * int(weights.get(key, 0))
               for key in ("reactions", "comments", "shares"))


def mass_report(config: dict, top: int = 10) -> list[dict]:
    """จัดอันดับโพสต์ตามคะแนน พร้อมบอกว่าโตเท่าไรตั้งแต่ครั้งก่อน"""
    weights = config.get("mass_weights") or DEFAULT_CONFIG["mass_weights"]
    threshold = int(config.get("mass_score", 30))
    rows: list[dict] = []
    for key, record in load_stats().items():
        history = record.get("history") or []
        if not history:
            continue
        latest = history[-1]
        previous = history[-2] if len(history) > 1 else None
        score = _score(latest, weights)
        rows.append({
            "key": key,
            "group_id": record.get("group_id", ""),
            "caption": record.get("caption", ""),
            "link": record.get("link", ""),
            "at": latest.get("at", ""),
            "reactions": latest.get("reactions"),
            "comments": latest.get("comments"),
            "shares": latest.get("shares"),
            "score": score,
            "gain": score - _score(previous, weights) if previous else None,
            "mass": score >= threshold,
        })
    rows.sort(key=lambda row: (row["score"], row["gain"] or 0), reverse=True)
    return rows[:top]


# --------------------------------------------------- ตอบกลับคอมเมนต์คนอื่น

def load_replies() -> dict:
    return _read_json(REPLIES_FILE, {})


def _fingerprint(target_key: str, author: str, text: str) -> str:
    """ตัวระบุคอมเมนต์หนึ่งอัน — ใช้กันตอบซ้ำ

    ใช้ (โพสต์ + คนเขียน + ต้นข้อความ) เพราะคอมเมนต์ไม่มี id ให้อ่านจากหน้าจอ
    ตัดข้อความที่ 60 ตัวอักษรตัวเดียวกับที่ใช้ตอนนับคอมเมนต์ จะได้ตรงกัน
    """
    return f"{target_key}|{author}|{text[:60]}"


def pick_reply(config: dict, text: str) -> str:
    """เลือกข้อความตอบ ('' = ไม่ควรตอบคอมเมนต์นี้)

    เจอคำใน skip_keywords = ไม่ตอบเลย ปล่อยให้คนจริงจัดการ — คำต่อว่าหรือ
    คำถามยากที่ตอบด้วยข้อความสำเร็จรูปมีแต่ทำให้แย่ลง
    """
    low = text.casefold()
    for word in (config.get("skip_keywords") or []):
        if str(word).casefold() in low:
            return ""
    for rule in (config.get("rules") or []):
        if any(str(word).casefold() in low for word in (rule.get("keywords") or [])):
            return str(rule.get("reply") or "").strip()
    pool = [str(x).strip() for x in (config.get("replies") or []) if str(x).strip()]
    if not pool:
        return ""
    # เลือกแบบคงที่ตามเนื้อคอมเมนต์ ไม่ใช่สุ่ม — รันซ้ำจะได้ผลเดิม ไล่ปัญหาง่ายกว่า
    # และ hash() ของ Python สุ่ม salt ทุกโปรเซส ใช้ไม่ได้ ต้องใช้ crc32
    return pool[zlib.crc32(low.encode("utf-8")) % len(pool)]


COMMENT_ZONE_SCROLLS = 6


def _scroll_into_comments(phone: fb.Phone) -> bool:
    """เลื่อนลงจนเข้าโซนคอมเมนต์ (เจอแถวตัวกรอง) — False = หาไม่เจอ"""
    for _ in range(COMMENT_ZONE_SCROLLS + 1):
        xml = phone.dump()
        for labels, _, _ in fb.iter_widgets(xml):
            joined = " ".join(labels)
            if any(hint in joined for hint in fb.COMMENT_FILTER_HINTS):
                return True
        phone.run(
            "shell", "input", "swipe", "540", "1800",
            "540", str(1800 - fb.SCROLL_STEP), str(fb.SCROLL_DURATION_MS),
        )
        time.sleep(1.8)
    return False


def _comment_zone(xml: str) -> tuple[int, int]:
    """ช่วง y ที่เป็นคอมเมนต์จริง — ตัดหัวจอบนและการ์ด "กลุ่มที่แนะนำ" ท้ายออก"""
    low, high = fb.SAFE_TAP_TOP, 10 ** 6
    for labels, box, _ in fb.iter_widgets(xml):
        joined = " ".join(labels)
        if not joined:
            continue
        if any(hint in joined for hint in fb.COMMENT_FILTER_HINTS):
            low = max(low, box[1])
        if any(hint in joined for hint in fb.COMMENT_ZONE_END_HINTS):
            high = min(high, box[1])
    return low, high


def reply_to_comment(phone: fb.Phone, comment: dict, text: str) -> bool:
    """แตะปุ่มตอบกลับของคอมเมนต์นั้นแล้วส่งข้อความ

    ⚠️ **ยังไม่เคยเห็นหน้าจอหลังกดปุ่มตอบกลับด้วยตาตัวเอง** — เขียนบนสมมติฐานว่า
    แอปเปิด "แผงพิมพ์คอมเมนต์ตัวเดิม" โดยตั้งเป้าหมายเป็นการตอบกลับให้แล้ว
    ซึ่งเป็นพฤติกรรมปกติของแอปรุ่นนี้ แต่ยังไม่ได้ยืนยัน

    ถ้าสมมติฐานผิด จะไม่เจอช่องพิมพ์แล้ว `_write_comment` คืน False เอง
    (มันเช็ค COMMENT_FIELD_HINTS ก่อนพิมพ์เสมอ) — ล้มแบบไม่ทำอะไรพัง ไม่ใช่
    ไปพิมพ์ลงที่ผิด แต่**ต้องยืนยันกับจอจริงก่อนเปิดใช้งานจริง**

    ใช้ `_write_comment` ตัวเดียวกับการคอมเมนต์ปกติ จึงได้ของแถมมาครบ:
    เพดานคอมเมนต์ต่อชั่วโมง · ตรวจว่าข้อความขึ้นช่องจริงก่อนกดส่ง ·
    ตรวจซ้ำหลายรอบว่าขึ้นเป็นคอมเมนต์จริงไม่ใช่ค้างในช่องพิมพ์
    """
    if comment.get("reply") is None:
        phone.log("  ไม่เห็นปุ่มตอบกลับของคอมเมนต์นี้บนจอ")
        return False
    phone.tap(comment["reply"])
    time.sleep(2.5)
    return fb._write_comment(phone, text)


def reply_round(config: dict, log=print, stop=lambda: False,
                limit: int | None = None) -> dict:
    """ไล่ดูคอมเมนต์ของคนอื่นในโพสต์ที่ตามอยู่ แล้วตอบกลับ

    ทำเฉพาะโพสต์ที่ "มีคอมเมนต์มากกว่าที่เราเขียนเอง" ตามข้อมูลที่เก็บยอดไว้
    จะได้ไม่เสียเวลาจอไปเปิดโพสต์ที่ไม่มีใครมาคุยด้วย
    """
    if not config.get("reply_enabled"):
        raise EngageError("ยังไม่ได้เปิดโหมดตอบกลับ — สั่ง /reply on ก่อน")
    owners = owner_list(config)
    if not owners:
        raise EngageError(
            "ยังไม่ได้ตั้งชื่อบัญชีที่ใช้โพสต์ — สั่ง /owner <ชื่อ> ก่อน\n"
            "ไม่ตั้ง = แยกไม่ออกว่าคอมเมนต์ไหนของเราเอง แล้วบอทจะตอบตัวเองวนไม่จบ\n"
            "ใส่ได้หลายบัญชี คั่นด้วยจุลภาค เช่น /owner ชื่อ ก, ชื่อ ข")
    busy = phone_busy_elsewhere()
    if busy:
        raise EngageError(f"ยังทำไม่ได้ — {busy}")
    serial = resolve_serial(config)

    stats = load_stats()
    replied = load_replies()
    # เรียงจากโพสต์ที่คอมเมนต์เยอะสุดก่อน — โอกาสเจอคอมเมนต์คนอื่นสูงกว่า
    ranked = sorted(
        post_targets(),
        key=lambda t: ((stats.get(t["key"], {}).get("history") or [{}])[-1]
                       .get("comments") or 0),
        reverse=True,
    )
    cap = limit or int(config.get("max_replies_per_round", 5))
    sent = skipped = 0
    seen_posts = 0

    phone = fb.Phone("adb", serial, log=log)
    for target in ranked:
        if stop() or sent >= cap:
            break
        if fb.comment_quota_left() <= 0:
            log(f"ครบเพดาน {fb.COMMENT_LIMIT_PER_HOUR} คอมเมนต์/ชั่วโมงแล้ว")
            break
        busy = phone_busy_elsewhere()
        if busy:
            log(f"{busy} — หยุดรอบนี้ไว้ก่อน")
            break
        seen_posts += 1
        log(f"เปิด {target['key']}")
        # ถือล็อก + สลับคีย์บอร์ด **ทีละโพสต์** แล้วคืนทุกครั้ง
        #
        # ถือยาวทั้งรอบ = งานโพสต์ของผู้ใช้ต้องรอถึง 5 โพสต์ (~5 นาที) แล้วล้ม
        # และถ้าโปรเซสนี้ตายกลางทาง คีย์บอร์ดจะค้างที่ ADBKeyboard จนผู้ใช้
        # พิมพ์เองไม่ได้ — คืนทุกใบจึงค้างได้อย่างมากใบเดียว
        with studio_shared.phone_lock(serial, label=f"fb_engage ตอบคอมเมนต์ {target['key']}"):
            fb.require_network(phone)
            original_ime = phone.use_adb_keyboard()
            try:
                if not fb.open_post_link(phone, target["link"], target["caption"],
                                         target["group_id"], target["post_id"]):
                    log("  เปิดโพสต์ไม่ได้ — ข้าม")
                    continue
                if not _scroll_into_comments(phone):
                    log("  ไม่เจอโซนคอมเมนต์ — ข้าม")
                    continue
                xml = phone.dump()
                low, high = _comment_zone(xml)
                for comment in fb.visible_comments(xml, low, high):
                    if stop() or sent >= cap:
                        break
                    author, text = comment["author"], comment["text"]
                    if not text:
                        continue
                    if is_owner(author, owners):
                        continue                     # คอมเมนต์ของบัญชีเราเอง
                    mark = _fingerprint(target["key"], author, text)
                    if mark in replied:
                        continue
                    answer = pick_reply(config, text)
                    if not answer:
                        skipped += 1
                        log(f"  ข้ามคอมเมนต์ของ {author[:20]} (เข้าเงื่อนไขห้ามตอบ)")
                        replied[mark] = {"at": datetime.now().isoformat(
                            timespec="seconds"), "skipped": True}
                        continue
                    log(f"  ตอบ {author[:20]}: {answer[:40]}")
                    if reply_to_comment(phone, comment, answer):
                        sent += 1
                        replied[mark] = {
                            "at": datetime.now().isoformat(timespec="seconds"),
                            "reply": answer, "author": author,
                            "comment": text[:60],
                        }
                    else:
                        log("  ตอบไม่สำเร็จ — ข้ามไปคอมเมนต์ถัดไป")
            finally:
                if original_ime:
                    phone.restore_keyboard(original_ime)
                _write_json(REPLIES_FILE, replied)
    return {"sent": sent, "skipped": skipped, "posts": seen_posts,
            "quota_left": fb.comment_quota_left()}
