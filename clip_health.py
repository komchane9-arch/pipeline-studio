"""ตรวจสุขภาพสายคลิป — อะไรพร้อม อะไรไม่พร้อม ในคำสั่งเดียว

**เจ้าของสั่ง 11 ก.ย. 2569** หลังเสียเวลาไล่ปัญหาไป 5 ชั่วโมงกับของที่ตายเงียบ

---

## เหตุการณ์ที่ทำให้ต้องมีตัวนี้

เครื่องบูตใหม่ 10:03 น. **Ollama (ตัว AI ที่ใช้เทียบรูปสินค้า) ไม่ได้เปิดกลับ**
สายหาสินค้า TikTok จึงตายทั้งสายตั้งแต่เช้า

อาการที่มองเห็นคือข้อความ ``ตรวจสี่อันดับไม่ได้: [WinError 10061]`` ซึ่งซ่อนอยู่
ลึกในผลใบงานใบเดียว **ไม่มีแบนเนอร์ ไม่มีเตือนบนหน้าเว็บ ไม่มีที่ไหนบอก**

ถ้าเปิดสวิตช์อัตโนมัติทิ้งไว้ มันจะไล่ล้มทีละใบเงียบๆ ทั้ง 296 ใบที่เหลือ
แล้วเช้าวันรุ่งขึ้นจะเห็นแค่ "ทำไมไม่มีอะไรคืบหน้าเลย"

## หลักที่ยึด

**ทุกข้อต้องถามของที่มีเฉพาะตอนพร้อมใช้จริง** ไม่ใช่ถามว่า "ไม่เจอสิ่งที่แปลว่าพัง"
(กติกาข้อ 2.3.1) — เช่น Ollama ไม่ได้ถามแค่ว่าพอร์ตเปิดไหม แต่ถามว่า
**ตอบรายชื่อโมเดลกลับมาไหม และมีโมเดลที่เราต้องใช้อยู่จริงไหม**

และ **"ตรวจไม่ได้" ต้องไม่หน้าตาเหมือน "ตรวจแล้วผ่าน"** — ใช้สถานะ ⚠️ แยกต่างหาก
"""
from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

import studio_shared as shared

OK, BAD, UNKNOWN = "ok", "bad", "unknown"
MARK = {OK: "✅", BAD: "❌", UNKNOWN: "⚠️"}

CLIP_PHONE = "W4FYYPYTLFYLIFHM"
# เครดิต Flow ต่ำกว่านี้ถือว่าใกล้หมด — หนึ่งคลิปกิน 15 หน่วย
FLOW_CREDIT_LOW = 100


def _row(name: str, state: str, detail: str, fix: str = "") -> dict:
    return {"name": name, "state": state, "detail": detail, "fix": fix}


# ------------------------------------------------------------------ ตัวตรวจ


def check_ollama() -> dict:
    """ตัว AI ในเครื่อง — ต้องตอบรายชื่อโมเดล **และมีโมเดลที่เราใช้อยู่จริง**"""
    try:
        import httpx

        import clip_pickimg
        reply = httpx.get(f"{clip_pickimg.OLLAMA_URL}/api/tags", timeout=5.0)
        if reply.status_code != 200:
            return _row("ตัว AI ในเครื่อง (Ollama)", BAD,
                        f"ตอบรหัส {reply.status_code}",
                        "เปิดด้วย _ollama\\ollama.exe serve")
        names = [str(m.get("name") or "") for m in reply.json().get("models") or []]
        want = clip_pickimg.OLLAMA_MODEL
        if not any(want in n for n in names):
            return _row("ตัว AI ในเครื่อง (Ollama)", BAD,
                        f"เปิดอยู่แต่ไม่มีโมเดล {want} (มี {names or 'ไม่มีเลย'})",
                        f"ollama pull {want}")
        return _row("ตัว AI ในเครื่อง (Ollama)", OK, f"พร้อม · โมเดล {want}")
    except Exception as error:                                 # noqa: BLE001
        return _row("ตัว AI ในเครื่อง (Ollama)", BAD,
                    f"ต่อไม่ได้: {type(error).__name__}",
                    "เปิดด้วย _ollama\\ollama.exe serve "
                    "(ตัวหาสินค้า TikTok เปิดให้เองแล้ว แต่ตัวอื่นยังไม่)")


def check_thai_ocr() -> dict:
    """ตัวอ่านภาษาไทยจากภาพ — ตัวชี้เป็นชี้ตายของสาย TikTok ทั้งสาย"""
    try:
        import tiktok_publish_bot as bot
        reader = bot.get_thai_ocr()
        if reader is None:
            return _row("ตัวอ่านภาษาไทยจากภาพ", BAD, "โหลดไม่ขึ้น",
                        "pip install easyocr --no-deps")
        return _row("ตัวอ่านภาษาไทยจากภาพ", OK, "พร้อม (EasyOCR th+en)")
    except Exception as error:                                 # noqa: BLE001
        return _row("ตัวอ่านภาษาไทยจากภาพ", BAD, f"{type(error).__name__}: {error}")


def check_flow_credits() -> dict:
    """เครดิตเจนคลิป — หมดเมื่อไรต้นน้ำหยุดทันที"""
    try:
        config = json.loads((shared.DATA_DIR / "config.json").read_text("utf-8"))
    except (OSError, ValueError) as error:
        return _row("เครดิต Flow", UNKNOWN, f"อ่าน config ไม่ได้: {error}")
    left = config.get("flow_credits_last")
    if left is None:
        return _row("เครดิต Flow", UNKNOWN, "ยังไม่เคยวัด")
    when = config.get("flow_credits_at")
    ago = ""
    if when:
        hours = (time.time() - float(when)) / 3600
        ago = f" (วัดเมื่อ {hours:.0f} ชม.ที่แล้ว)"
    clips = int(left) // 15
    if int(left) < FLOW_CREDIT_LOW:
        return _row("เครดิต Flow", BAD,
                    f"เหลือ {left} หน่วย = เจนได้อีกราว {clips} คลิป{ago}",
                    "เติมเครดิต หรือสลับบัญชีที่ยังมีเหลือ")
    return _row("เครดิต Flow", OK, f"เหลือ {left} หน่วย ≈ {clips} คลิป{ago}")


def check_phone() -> dict:
    """มือถือสายคลิป — ต้องเสียบอยู่ **และสั่งงานได้จริง**"""
    try:
        done = subprocess.run(["adb", "devices"], capture_output=True, timeout=30)
        listed = done.stdout.decode("utf-8", errors="replace")
    except Exception as error:                                 # noqa: BLE001
        return _row("มือถือสายคลิป", UNKNOWN, f"เรียก adb ไม่ได้: {error}")
    if f"{CLIP_PHONE}\tdevice" not in listed.replace("  ", "\t"):
        online = [l.split()[0] for l in listed.splitlines()[1:] if "\tdevice" in l]
        return _row("มือถือสายคลิป", BAD,
                    f"{CLIP_PHONE} ไม่ได้เสียบ (ที่เสียบอยู่: {online or 'ไม่มีเลย'})",
                    "เสียบสาย USB แล้วกดอนุญาตบนจอมือถือ")
    # เสียบอยู่ไม่พอ — ต้องสั่งงานได้จริง
    try:
        got = subprocess.run(["adb", "-s", CLIP_PHONE, "shell", "echo", "ok"],
                             capture_output=True, timeout=20)
        if b"ok" not in got.stdout:
            return _row("มือถือสายคลิป", BAD, "เสียบอยู่แต่สั่งงานไม่ได้",
                        "ถอดเสียบใหม่ หรือ adb kill-server")
    except Exception as error:                                 # noqa: BLE001
        return _row("มือถือสายคลิป", BAD, f"สั่งงานไม่ได้: {type(error).__name__}")
    return _row("มือถือสายคลิป", OK, f"{CLIP_PHONE} พร้อม")


def check_servers() -> list[dict]:
    """เซิร์ฟเวอร์ทั้งสองตัวต้องตอบจริง ไม่ใช่แค่พอร์ตเปิด"""
    import httpx

    rows = []
    for name, url in (("เซิร์ฟเวอร์กลาง 8866", "http://127.0.0.1:8866/api/system"),
                      ("สายคลิป 8877", "http://127.0.0.1:8877/api/health")):
        try:
            reply = httpx.get(url, timeout=6.0)
            state = OK if reply.status_code == 200 else BAD
            rows.append(_row(name, state, f"ตอบรหัส {reply.status_code}",
                             "" if state == OK else "python restart_studio.py"))
        except Exception as error:                             # noqa: BLE001
            rows.append(_row(name, BAD, f"ไม่ตอบ: {type(error).__name__}",
                             "python restart_studio.py"))
    return rows


def check_switches() -> dict:
    """สวิตช์อัตโนมัติ — ปิดหมดไม่ใช่ความผิดพลาด แต่ต้องเห็นว่าปิดอยู่

    เจอจริง 11 ก.ย.: Shopee หยุดลงมา 7 วันทั้งที่มีของรอ 14 ใบ **ไม่มีอะไรพัง
    แค่ไม่มีใครกด** — ถ้าไม่แสดงตรงนี้ จะไปนั่งไล่หาบั๊กที่ไม่มีอยู่จริง
    """
    try:
        config = json.loads((shared.DATA_DIR / "config.json").read_text("utf-8"))
    except (OSError, ValueError) as error:
        return _row("สวิตช์อัตโนมัติ", UNKNOWN, f"อ่าน config ไม่ได้: {error}")
    switches = config.get("clip_auto_approve") or {}
    on = sorted(k for k, v in switches.items() if v)
    paused = config.get("clip_gen_paused")
    detail = f"เปิดอยู่ {on or 'ไม่มีเลย'}"
    if paused:
        detail += " · การเจนคลิปถูกสั่งพักไว้"
    # ปิดหมดไม่ใช่ "พัง" แต่แปลว่าไม่มีอะไรเดินเอง จึงเป็น ⚠️ ไม่ใช่ ❌
    return _row("สวิตช์อัตโนมัติ", OK if on else UNKNOWN, detail,
                "" if on else "เปิดที่หน้าเว็บถ้าต้องการให้เดินเอง")


def check_disk() -> dict:
    """ที่ว่างในเครื่อง — คลิปกับหลักฐานกินที่เร็วมาก"""
    try:
        import shutil
        usage = shutil.disk_usage(str(shared.DATA_DIR))
        free_gb = usage.free / 1e9
        state = OK if free_gb > 20 else BAD
        return _row("ที่ว่างในเครื่อง", state, f"เหลือ {free_gb:.0f} GB",
                    "" if state == OK else "ลบหลักฐานเก่าใน data/evidence")
    except Exception as error:                                 # noqa: BLE001
        return _row("ที่ว่างในเครื่อง", UNKNOWN, f"{type(error).__name__}")


CHECKS = (check_ollama, check_thai_ocr, check_flow_credits, check_phone,
          check_switches, check_disk)


def board(log=print) -> dict:
    """ตรวจทุกข้อแล้วพิมพ์ออกมา — คืนสรุปให้ผู้เรียกเอาไปใช้ต่อ"""
    rows = []
    for check in CHECKS:
        try:
            rows.append(check())
        except Exception as error:                             # noqa: BLE001
            rows.append(_row(getattr(check, "__name__", "?"), UNKNOWN,
                             f"ตัวตรวจเองพัง: {type(error).__name__}: {error}"))
    rows.extend(check_servers())

    log("สุขภาพสายคลิป")
    for row in rows:
        log(f"  {MARK[row['state']]} {row['name']:<26} {row['detail']}")
        if row["fix"] and row["state"] != OK:
            log(f"      แก้: {row['fix']}")

    bad = [r for r in rows if r["state"] == BAD]
    unknown = [r for r in rows if r["state"] == UNKNOWN]
    log("")
    if bad:
        log(f"  ❌ ใช้งานไม่ได้ {len(bad)} ข้อ: {', '.join(r['name'] for r in bad)}")
    if unknown:
        log(f"  ⚠️ ตรวจไม่ได้/ต้องดู {len(unknown)} ข้อ: "
            f"{', '.join(r['name'] for r in unknown)}")
    if not bad and not unknown:
        log("  ✅ พร้อมทุกข้อ")
    return {"rows": rows, "bad": len(bad), "unknown": len(unknown)}


if __name__ == "__main__":
    import sys
    sys.exit(1 if board()["bad"] else 0)
