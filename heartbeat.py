"""ยามเฝ้า — งานที่รันยาวทุกตัวต้องบอกว่า "ผมยังอยู่" และถ้าตายต้องทิ้งร่องรอยเสมอ

**ทำไมต้องมี** 21 ส.ค. 2569 ตัวเก็บข้อมูล Bot9 ตายเงียบ ทำจบ 0/3 กลุ่ม
รายการรันค้างเปิดอยู่ 27.1 + 22.2 = **49.3 ชั่วโมง** โดยไม่มีใครรู้ เพราะสองอย่างพร้อมกัน:

  1. **ไม่มีชีพจร** — ไม่มีใครรู้ว่ามันหยุดไปแล้ว รู้อีกทีตอนไปเปิดดูเอง
  2. ความตายวิ่งเข้า stderr ของหน้าต่างที่สั่งรัน แล้วหายไปพร้อมหน้าต่างนั้น

ข้อ 2 แก้ไปแล้วที่ `fb_posts_collect.guarded_main()` แต่ข้อ 1 ยังไม่มี
และบทเรียนเดียวกันนี้เคยแก้มาแล้วครั้งหนึ่งเมื่อ 13 ส.ค. — แต่ใส่ไว้แค่ `fb_mass_bot.py`
ตัวเดียว พอ **ตัวอื่น**ตายบ้างจึงไม่มีอะไรกันไว้เลย (กติกาข้อ 2.6: บั๊กเก่าต้องกลายเป็น
ด่านตรวจถาวร ไม่ใช่บรรทัดในบันทึก)

ไฟล์นี้ทำให้ "ใส่ยามเฝ้า" เหลือ **2 บรรทัดต่อสคริปต์** จะได้ไม่มีตัวไหนตกหล่นอีก:

    import heartbeat
    heartbeat.watch("ชื่องาน")                       # เริ่มเต้นชีพจร
    raise SystemExit(heartbeat.guard("ชื่องาน", main, notify=say))   # ตายแล้วต้องดัง

ดูสถานะทุกตัวได้ตรงๆ:

    python heartbeat.py            ← ตอนนี้ใครยังหายใจอยู่บ้าง

รูปแบบไฟล์ชีพจรเป็น "เลขวินาทีล้วน" เหมือนเดิมเป๊ะ (`data/<ชื่อ>.heartbeat`)
เพื่อให้ `app.py:mass_bot_running()` ที่อ่าน `fb_mass_bot.heartbeat` อยู่แล้วใช้ต่อได้
โดยไม่ต้องแก้อะไร
"""

from __future__ import annotations

import threading
import time
import traceback
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
LOG_DIR = DATA_DIR / "logs"
WATCHDOG_LOG = LOG_DIR / "watchdog.log"

BEAT_SECONDS = 15       # เต้นถี่แค่ไหน
STALE_SECONDS = 90      # เงียบเกินเท่านี้ = ถือว่าตาย (ตรงกับ app.py:MASS_BOT_STALE)
ALERT_AFTER = 180       # แต่จะ "ร้อง" ต่อเมื่อเงียบเกินเท่านี้ — กันเตือนผิดตอนเครื่องหน่วง

# จำว่าร้องไปแล้วตัวไหน จะได้ไม่ร้องซ้ำทุกนาที
_reported: set[str] = set()


def _path(name: str) -> Path:
    return DATA_DIR / f"{name}.heartbeat"


def _write_log(text: str) -> None:
    """เขียนลงล็อกของโปรเจกต์เสมอ — ยามเฝ้าห้ามพึ่ง Telegram อย่างเดียว
    เพราะตอนเน็ตหรือโทเคนมีปัญหา เสียงร้องจะหายไปทั้งเสียง"""
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        with WATCHDOG_LOG.open("a", encoding="utf-8") as fh:
            fh.write(f"{stamp} {text}\n")
    except OSError:
        pass


def beat(name: str) -> None:
    """แตะไฟล์ชีพจรหนึ่งครั้ง — บอกว่ายังมีชีวิต"""
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        _path(name).write_text(str(int(time.time())), encoding="utf-8")
    except OSError:
        pass        # เขียนชีพจรไม่ได้ ห้ามทำให้งานหลักตาย


def _loop(name: str) -> None:
    while True:
        beat(name)
        time.sleep(BEAT_SECONDS)


def watch(name: str) -> threading.Thread:
    """เริ่มเต้นชีพจรใน thread แยก

    **ต้องแยก thread** เพราะงานหลักค้างยาวเป็นปกติ (long-poll ของ Telegram ·
    อ่านหน้าจอมือถือครั้งละ 2.3 วิ · รอ Gemini เจนคลิป) ถ้าเต้นในลูปหลัก
    ชีพจรจะห่างเท่าความช้าของงาน แล้วดูเหมือนตายทั้งที่ยังทำงานอยู่
    """
    beat(name)
    thread = threading.Thread(target=_loop, args=(name,), daemon=True, name=f"beat-{name}")
    thread.start()
    return thread


def stop(name: str) -> None:
    """จบงานตามปกติ — ลบชีพจรทิ้ง

    สำคัญ: ถ้าไม่ลบ ไฟล์เก่าจะค้างเป็นผี แล้ว `sweep()` จะร้องว่า "ตาย"
    ทั้งที่มันแค่ทำงานเสร็จแล้วเดินออกไปเฉยๆ
    """
    try:
        _path(name).unlink()
    except OSError:
        pass
    _reported.discard(name)


def age(name: str) -> float | None:
    """เงียบมากี่วินาทีแล้ว — คืน None ถ้าไม่มีไฟล์ชีพจร (= ไม่ได้รันอยู่)"""
    try:
        stamp = int(_path(name).read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None
    return time.time() - stamp


def alive(name: str) -> bool:
    seconds = age(name)
    return seconds is not None and seconds < STALE_SECONDS


def roster() -> list[dict]:
    """ทุกงานที่มีชีพจรอยู่ตอนนี้ + สถานะ เรียงชื่อ"""
    rows = []
    for path in sorted(DATA_DIR.glob("*.heartbeat")):
        name = path.name[: -len(".heartbeat")]
        seconds = age(name)
        rows.append({
            "name": name,
            "silent_for": seconds,
            "alive": seconds is not None and seconds < STALE_SECONDS,
        })
    return rows


def sweep(notify=None) -> list[str]:
    """ตรวจทุกตัวรอบเดียว — ตัวไหนเงียบเกินกำหนดให้ร้องหนึ่งครั้ง แล้วเก็บหลักฐานไว้

    เรียกจากลูปที่เดินอยู่แล้วของ `app.py` (ทุก 60 วิ) — คืนชื่อตัวที่เพิ่งร้องไป
    ร้องแล้วเปลี่ยนชื่อไฟล์เป็น `.heartbeat.dead` เพื่อ (1) ไม่ร้องซ้ำทุกนาที
    (2) ยังเหลือหลักฐานว่าตายตอนกี่โมงไว้ไล่ย้อนหลัง
    """
    fired = []
    for row in roster():
        name, seconds = row["name"], row["silent_for"]
        if seconds is None or seconds < ALERT_AFTER or name in _reported:
            continue
        _reported.add(name)
        minutes = int(seconds / 60)
        text = f"💀 <b>{name} เงียบไป {minutes} นาที</b> — น่าจะตายแล้ว ไม่มีใครทำงานนี้ต่อ"
        _write_log(f"{name} เงียบ {minutes} นาที — แจ้งเตือนแล้ว")
        if notify:
            try:
                notify(text)
            except Exception as error:                          # noqa: BLE001
                _write_log(f"แจ้งเตือน {name} ไม่ออก: {error}")
        try:
            _path(name).rename(DATA_DIR / f"{name}.heartbeat.dead")
        except OSError:
            pass
        fired.append(name)
    return fired


def guard(name: str, func, notify=None) -> int:
    """ครอบงานหลัก — ตายแบบไหนก็ต้องทิ้ง traceback ไว้ + ร้องออกมา ห้ามหายเงียบ

    ครอบ `BaseException` ไม่ใช่แค่ `Exception` เพราะ `SystemExit` / `MemoryError` /
    ตัวที่ถูกฆ่ากลางทาง ก็ทำให้งานหยุดเหมือนกัน และเป็นแบบที่ไล่ย้อนหลังยากที่สุด
    """
    try:
        code = func()
        stop(name)
        return int(code or 0)
    except KeyboardInterrupt:
        _write_log(f"{name} หยุดด้วยมือ (Ctrl-C)")
        stop(name)
        return 130
    except BaseException as error:                              # noqa: BLE001
        detail = f"{type(error).__name__}: {error}"
        _write_log(f"💥 {name} ตายกลางทาง: {detail}\n{traceback.format_exc()}")
        if notify:
            try:
                notify(f"💥 <b>{name} ตายกลางทาง</b>\n{detail[:300]}")
            except Exception:                                   # noqa: BLE001
                pass
        stop(name)      # ร้องไปแล้ว ไม่ต้องให้ sweep ร้องซ้ำ
        return 1


def main() -> int:
    rows = roster()
    if not rows:
        print("ไม่มีงานไหนรันอยู่เลย (ไม่มีไฟล์ชีพจร)")
        return 0
    print(f"{'งาน':<28} {'สถานะ':<12} เงียบมาแล้ว")
    for row in rows:
        mark = "✅ ยังอยู่" if row["alive"] else "💀 น่าจะตาย"
        print(f"{row['name']:<28} {mark:<12} {int(row['silent_for'])} วิ")
    dead = [r["name"] for r in rows if not r["alive"]]
    return 1 if dead else 0


if __name__ == "__main__":
    raise SystemExit(main())
