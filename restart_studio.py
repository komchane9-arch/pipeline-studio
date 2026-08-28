"""รีสตาร์ตเซิร์ฟเวอร์ 8866 แบบตรวจก่อนว่าปลอดภัยไหม

**ทำไมต้องมี** `app.py` ไม่มี auto-reload แก้โค้ดแล้วต้องรีสตาร์ตเองทุกครั้ง
แต่การรีสตาร์ตมั่วๆ ทำพังมาแล้วสามแบบ:

    รีสตาร์ตตอนงานโพสต์กำลังรัน   โพสต์ไป 3 จาก 6 กลุ่มแล้วตายกลางคัน
                                  ต้องมาไล่ /followup /fiximage เก็บกวาดเอง
    รีสตาร์ตตอนมีงานตั้งเวลา       งาน 18:30 หายเงียบ
    ฆ่าโปรเซสด้วยตัวกรองหลวมๆ     ตัวกรอง *app.py* ไปโดน clip_app.py ตายด้วย

`start_studio.bat` ของเดิมมี 9 บรรทัดและใจความคือ "สั่งเปิดเลย" ไม่ตรวจอะไร
ทั้งสามข้อข้างบนจึงต้องตรวจเองด้วยมือทุกครั้ง — วันไหนลืมคือวันที่งานพัง
ไฟล์นี้ย้ายการตรวจนั้นมาไว้ในเครื่องแทนหัวคน

**ไม่แตะ ADB เลยแม้แต่คำสั่งเดียว** ทุกอย่างถามผ่าน HTTP กับตารางโปรเซสของ
Windows เท่านั้น รีสตาร์ตเซิร์ฟเวอร์ไม่ควรไปยุ่งกับมือถือที่อาจมีงานอื่นใช้อยู่

วิธีใช้
    python restart_studio.py             ตรวจแล้วรีสตาร์ต
    python restart_studio.py --dry-run   ตรวจอย่างเดียว ไม่แตะอะไร
    python restart_studio.py --force     ข้ามด่านตรวจ (ใช้เมื่อรู้ว่ากำลังทำอะไร)
    python restart_studio.py --no-backup ไม่ต้องสำรองก่อน
"""

from __future__ import annotations

import argparse
import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

# ซ่อนหน้าต่างคอนโซลตอนสั่งโปรแกรมภายนอก — ไม่ให้กะพริบใส่ผู้ใช้
# ประกาศในไฟล์เองแทนการ import studio_shared เพื่อไม่เพิ่มสายพึ่งพาโดยไม่จำเป็น
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


BASE_DIR = Path(__file__).resolve().parent
PYTHON = sys.executable or r"C:\Python311\python.exe"

# พอร์ตตาม STUDIO_PORT เหมือน app.py — สำเนาทดสอบใน git worktree รันคู่กับตัวจริงได้
#     set STUDIO_PORT=8966 && set STUDIO_DATA_DIR=data-wt && restart_studio.bat
# ถ้าอ่านไม่ออกให้ถอยไป 8866 ไม่ใช่ล้ม — สคริปต์กู้สถานการณ์ต้องไม่ตายเพราะค่าตั้งเพี้ยน
try:
    PORT = int(os.environ.get("STUDIO_PORT", "") or 8866)
except ValueError:
    PORT = 8866
API = f"http://127.0.0.1:{PORT}"
SERVER_LOG = "data/server.log"

# งานตั้งเวลาที่จะถึงเร็วกว่านี้ = ไม่ควรรีสตาร์ต
SCHEDULE_GUARD_MINUTES = 10
# รอเซิร์ฟเวอร์ตัวใหม่ขึ้นนานสุดเท่านี้
STARTUP_WAIT_SECONDS = 60

# ตัวกรองโปรเซส — ต้องมีตัวคั่นนำหน้าเสมอ ไม่งั้น clip_app.py ก็เข้าเงื่อนไขด้วย
#
# นี่คือบั๊กที่เคยฆ่า clip_app.py ตายไปจริงๆ ตัวกรองเดิมคือ `*app.py*`
# ซึ่ง "clip_app.py" ก็ตรงเงื่อนไข
APP_PROCESS_RE = re.compile(r'(?:^|[\\/"\'\s])app\.py(?:["\'\s]|$)')


class Blocked(RuntimeError):
    """มีเหตุผลที่ไม่ควรรีสตาร์ตตอนนี้"""


# ------------------------------------------------------------------ ตัวช่วย

def say(line: str = "") -> None:
    print(line, flush=True)


def get_json(path: str, timeout: float = 8.0) -> dict | None:
    """ถาม API — คืน None ถ้าต่อไม่ติด (เซิร์ฟเวอร์อาจไม่ได้รันอยู่ ซึ่งก็ปกติ)"""
    try:
        with urllib.request.urlopen(f"{API}{path}", timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError, TimeoutError):
        return None


def port_busy(port: int = PORT) -> bool:
    with socket.socket() as probe:
        probe.settimeout(1.0)
        return probe.connect_ex(("127.0.0.1", port)) == 0


def python_processes() -> list[dict]:
    """โปรเซส python ทั้งหมดพร้อมบรรทัดคำสั่งและเวลาที่เริ่ม

    ใช้ CIM ของ Windows เพราะต้องได้ **บรรทัดคำสั่งเต็ม** มาแยกให้ออกว่าตัวไหน
    คือ app.py ตัวไหนคือ clip_app.py — `tasklist` เปล่าๆ บอกได้แค่ชื่อ python.exe
    เหมือนกันหมด
    """
    command = (
        "Get-CimInstance Win32_Process -Filter \"Name like '%python%'\" | "
        "Select-Object ProcessId,CommandLine,CreationDate | ConvertTo-Json -Compress"
    )
    try:
        done = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
            capture_output=True, text=True, timeout=40,
            encoding="utf-8", errors="replace", creationflags=_NO_WINDOW)
    except (OSError, subprocess.SubprocessError) as error:
        raise Blocked(f"อ่านตารางโปรเซสไม่ได้: {error}") from error
    raw = (done.stdout or "").strip()
    if not raw:
        return []
    try:
        # strict=False — ยอมให้มีอักขระควบคุมในสตริง
        #
        # โปรเซส python ที่ถูกสั่งด้วยสคริปต์หลายบรรทัด (`python -c "...\n..."`)
        # มี **ขึ้นบรรทัดใหม่จริงๆ อยู่ในบรรทัดคำสั่ง** ซึ่ง JSON มาตรฐานห้ามมี
        # ในสตริง ตัวอ่านแบบเข้มจะพังทั้งก้อนเพราะโปรเซสอื่นที่ไม่เกี่ยวกับเราเลย
        # (เจอจริงตอนทดสอบ: โปรเซสทดสอบของตัวเองทำให้ทั้งสคริปต์อ่านตารางไม่ได้)
        data = json.loads(raw, strict=False)
    except ValueError as error:
        raise Blocked(f"อ่านผลจาก PowerShell ไม่ออก: {error}") from error
    # ตัวเดียว PowerShell คืนเป็น object ไม่ใช่ list — ต้องรับทั้งสองแบบ
    items = data if isinstance(data, list) else [data]
    result = []
    for item in items:
        if not isinstance(item, dict) or not item.get("ProcessId"):
            continue
        result.append({
            "pid": int(item["ProcessId"]),
            "cmd": item.get("CommandLine") or "",
            "started": _cim_time(item.get("CreationDate")),
        })
    return result


def _cim_time(value) -> datetime | None:
    """CreationDate จาก ConvertTo-Json มาได้หลายหน้าตา — แปลงให้ได้เท่าที่ได้

    ถ้าแปลงไม่ได้ก็คืน None แล้วไปใช้หลักฐานอื่นแทน (PID เปลี่ยน) ไม่ใช่ล้มทั้งงาน
    """
    if isinstance(value, str):
        found = re.search(r"/Date\((\d+)", value)
        if found:
            return datetime.fromtimestamp(int(found.group(1)) / 1000)
        try:
            return datetime.strptime(value[:14], "%Y%m%d%H%M%S")
        except ValueError:
            return None
    return None


def listening_pids(port: int = PORT) -> set[int]:
    """ทุก PID ที่ฟังพอร์ตนี้อยู่

    คืนเป็นชุดไม่ใช่ตัวเดียว เพราะพอร์ตเดียวมีผู้ฟังหลายรายการได้จริง — วัดจาก
    เครื่องนี้ 14 ส.ค. พอร์ต 8866 มีสองราย:

        0.0.0.0:8866                      → app.py ตัวจริง
        100.106.61.24:8866 / [fd7a:…]     → ตัวส่งต่อของ Tailscale

    หยิบรายการแรกที่เจอแล้วจบ = มีโอกาสไปฆ่า Tailscale แทน app.py
    """
    found: set[int] = set()
    try:
        done = subprocess.run(["netstat", "-ano"], capture_output=True, text=True,
                              timeout=30, encoding="utf-8", errors="replace", creationflags=_NO_WINDOW)
    except (OSError, subprocess.SubprocessError):
        return found
    for line in (done.stdout or "").splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[0].upper() == "TCP" \
                and parts[1].endswith(f":{port}") and parts[3].upper() == "LISTENING":
            try:
                found.add(int(parts[4]))
            except ValueError:
                continue
    return found


def app_processes() -> list[dict]:
    """โปรเซส app.py ที่ **เป็นเจ้าของพอร์ตนี้** เท่านั้น

    เล็งด้วยพอร์ตไม่ใช่ด้วยชื่อไฟล์ เพราะสำเนาทดสอบใน git worktree ก็รัน `app.py`
    ชื่อเดียวกันเป๊ะ (คนละพอร์ต คนละ data) — กรองด้วยชื่ออย่างเดียวจะ**ฆ่าทั้งสองตัว**
    ซึ่งเป็นบั๊กชนิดเดียวกับที่เคยฆ่า clip_app.py ตายไปด้วย แค่เปลี่ยนหน้ามา

    ยังเทียบชื่อไฟล์ซ้ำอีกชั้น — ผู้ฟังพอร์ตนี้ที่ไม่ใช่ `app.py` (เช่นตัวส่งต่อของ
    Tailscale) ต้องไม่โดนฆ่าไปด้วย เงื่อนไขจึงต้องครบทั้งสอง: ถือพอร์ต **และ**
    เป็น python ที่รัน app.py
    """
    pids = listening_pids()
    if not pids:
        return []
    return [
        p for p in python_processes()
        if p["pid"] in pids and APP_PROCESS_RE.search(p["cmd"])
    ]


def other_studio_processes() -> list[dict]:
    """โปรเซสพี่น้องที่ **ห้ามแตะ** — เอาไว้แสดงให้เห็นว่าไม่ได้ไปยุ่งกับใคร"""
    keep = ("clip_app.py", "fb_mass_bot.py", "fb_engage_bot.py", "telegram_bot.py")
    return [
        p for p in python_processes()
        if any(name in p["cmd"] for name in keep) and not APP_PROCESS_RE.search(p["cmd"])
    ]


# ------------------------------------------------------------------ ด่านตรวจ

# ชื่องานในสมุดชีพจร -> ชื่อที่คนอ่านออก (ตัวที่ไม่อยู่ในนี้ใช้ชื่อดิบ)
HEARTBEAT_NAMES = {
    "fb_mass_bot": "บอทหาโพสต์แมส",
    "fb_posts_collect_Bot8": "Bot8 เก็บโพสต์",
    "fb_posts_collect_Bot9": "Bot9 เก็บโพสต์",
    "fb_engage_bot": "บอทตามยอด/ตอบคอมเมนต์",
}


def running_jobs() -> list[dict]:
    """งานที่รันแยกโปรเซสและยังเต้นชีพจรอยู่ตอนนี้

    **เอาไปใช้ทำอะไร** — สองอย่าง คนละน้ำหนักกัน (25 ส.ค. 2026)

      1. `stop_app()` ใช้ **ห้ามยกระดับไป `/T /F`** ← ของจริง ตรงนี้คือจุดเดียว
         ที่งานพวกนี้จะตายได้
      2. `show_state()` ใช้ **เล่าให้เห็น** ว่ามีอะไรวิ่งอยู่ — เตือน ไม่ห้าม

    **ทำไมไม่เอาไปบล็อกการรีสตาร์ตทั้งอัน (เคยทำแล้วถอยออกมา)**
        รอบแรกใส่ไว้ใน `check_safe()` เป็นตัวบล็อก ผลคือด่านจะห้ามรีสตาร์ต
        แทบตลอดเวลา — Bot8 รอบหนึ่งกินเวลา ~7 ชม.ครึ่ง · fb_mass_bot วิ่งยาว
        ข้ามวัน แปลว่าทุกครั้งที่จะรีต้องพิมพ์ `--force` จนติดเป็นนิสัย
        แล้ววันที่มีงานที่ตัดไม่ได้จริงๆ `--force` ก็จะข้ามไปโดยไม่มีใครอ่าน
        = ได้ด่านที่ไม่มีใครฟัง ซึ่งอันตรายพอกับด่านที่รายงานผิด แค่คนละแบบ

        และที่สำคัญกว่า: **การรีสตาร์ต 8866 ไม่ได้ทำร้ายงานพวกนี้เลย**
        วัดจริง 25 ส.ค. รีสตาร์ตสองรอบ (12:23 · 14:01) Bot8 · Bot9 ·
        fb_mass_bot · clip_app รอดครบทุกตัวทั้งสองรอบ เพราะ `stop_app()`
        ฆ่าด้วย `/F` ซึ่งไม่ลากลูก และตัวเก็บโพสต์เขียนลง sqlite ตรงๆ
        ไม่ได้พึ่ง API ของ 8866 เลย (ที่ยิงออกเน็ตคือโหลดรูปจาก Facebook)

    **ทำไมชีพจรครอบคลุมกว่า "ไล่ดูโปรเซสลูก"**
        งานที่วิ่งอยู่จริงไม่จำเป็นต้องเป็นลูกของ app.py — Bot9 พิสูจน์แล้ว
        (แม่ตายไปตั้งแต่รอบก่อน แต่ตัวมันยังทำงานอยู่) ถ้าด่านดูแค่ลูก
        จะมองไม่เห็น Bot9 เลย ส่วนชีพจรเห็นทุกตัวที่ยังหายใจ ไม่สนว่าใครเปิดมัน
    """
    try:
        import heartbeat
    except ImportError:
        return []
    return [row for row in heartbeat.roster() if row.get("alive")]


def _job_label(row: dict) -> str:
    name = str(row.get("name") or "")
    nice = HEARTBEAT_NAMES.get(name, name)
    silent = row.get("silent_for")
    when = f" (เต้นล่าสุด {silent:.0f} วิที่แล้ว)" if isinstance(silent, (int, float)) else ""
    return f"{nice}{when}"


def check_safe(now: datetime | None = None) -> list[str]:
    """ตรวจว่ารีสตาร์ตตอนนี้ปลอดภัยไหม — คืนรายการเหตุผลที่ห้าม (ว่าง = ผ่าน)"""
    now = now or datetime.now()
    reasons: list[str] = []

    jobs = get_json("/api/fb/jobs")
    if jobs is None:
        say("• เซิร์ฟเวอร์ไม่ตอบ — ข้ามการตรวจงานโพสต์/งานตั้งเวลา")
        return reasons
    if jobs.get("running"):
        current = next(
            (j for j in jobs.get("jobs", []) if j.get("status") == "running"), None
        )
        # ไม่เจองานสถานะ running ไม่ได้แปลว่าว่าง — รอบตามเก็บ/เก็บยอด/แก้รูป
        # ใช้จอมือถืออยู่เหมือนกันแต่ไม่เปลี่ยนสถานะงานเป็น running
        which = f"งาน {current['id']}" if current else \
            "มีงานใช้จออยู่ (ตามเก็บ/เก็บยอด/แก้รูป)"
        done = sum(1 for r in (current or {}).get("results", []) if r.get("posted"))
        total = len((current or {}).get("groups", []) or [])
        progress = f" (โพสต์ไปแล้ว {done}/{total} กลุ่ม)" if total else ""
        reasons.append(f"{which} กำลังรันอยู่{progress}" if current
                       else f"{which}{progress}")
    soon = now + timedelta(minutes=SCHEDULE_GUARD_MINUTES)
    for job in jobs.get("jobs", []):
        when = (job.get("run_at") or "").strip()
        if not when:
            continue
        try:
            at = datetime.fromisoformat(when)
        except ValueError:
            continue
        if now <= at <= soon:
            reasons.append(
                f"งาน {job['id']} ตั้งเวลาไว้ {at:%H:%M} "
                f"(อีก {int((at - now).total_seconds() // 60)} นาที)"
            )
    return reasons


def show_state(now: datetime | None = None) -> None:
    """เล่าสถานะปัจจุบันให้เห็นก่อนตัดสินใจ"""
    now = now or datetime.now()
    system = get_json("/api/system")
    jobs = get_json("/api/fb/jobs") or {}
    if system:
        say(f"• เซิร์ฟเวอร์ 8866 ตอบอยู่ · เวอร์ชัน {system.get('app_version', '?')}")
    else:
        say("• เซิร์ฟเวอร์ 8866 ไม่ตอบ")
    # งานที่รันแยกโปรเซส — เล่าให้เห็นก่อนตัดสินใจ **แต่ไม่ห้าม**
    # การรีสตาร์ตปกติไม่ทำร้ายงานพวกนี้ (วัดจริงแล้ว 2 รอบ) ที่ต้องกันคือ
    # ทางยกระดับไปปิดแบบลากลูก ซึ่งกันไว้ใน stop_app() แล้ว
    live = running_jobs()
    if live:
        say(f"• มีงานทำงานอยู่ {len(live)} ตัว (รีสตาร์ตปกติไม่กระทบ):")
        for row in live:
            say(f"   - {_job_label(row)}")
        say("   ถ้าพอร์ตไม่ยอมว่าง ระบบจะหยุดถามก่อน ไม่ลากงานพวกนี้ตายเอง")
    else:
        say("• ไม่มีงานที่เต้นชีพจรอยู่")
    scheduled = [
        (j["id"], j["run_at"]) for j in jobs.get("jobs", []) if (j.get("run_at") or "")
    ]
    if scheduled:
        for job_id, when in scheduled[:3]:
            say(f"• งานตั้งเวลา {job_id} → {when}")
    else:
        say("• ไม่มีงานตั้งเวลา")
    try:
        holder = _phone_holder()
    except Exception:
        holder = ""
    if holder:
        say(f"• มือถือมีคนถืออยู่: {holder} (ไม่เกี่ยวกับการรีสตาร์ต 8866)")


def _phone_holder() -> str:
    """ใครถือมือถืออยู่ — อ่านจากไฟล์บันทึกเท่านั้น ไม่เรียก ADB"""
    notes = []
    for info in sorted((BASE_DIR / "data" / "locks").glob("phone-*.info")):
        try:
            notes.append(info.read_text(encoding="utf-8").strip())
        except OSError:
            continue
    legacy = BASE_DIR / "data" / "phone.lock.info"
    if legacy.is_file():
        try:
            notes.append(legacy.read_text(encoding="utf-8").strip())
        except OSError:
            pass
    return " · ".join(n for n in notes if n)


# ------------------------------------------------------------ ปิด/เปิดเซิร์ฟเวอร์

def stop_app(processes: list[dict], force: bool = False) -> None:
    """ปิด app.py — **`/F` ก่อนเสมอ เพราะไม่ลากโปรเซสลูกไปด้วย**

    ทางยกระดับ `/T /F` ข้างล่างคือ **จุดเดียวในไฟล์นี้ที่ฆ่างานอื่นได้จริง**
    Bot8 · Bot9 · fb_mass_bot · clip_app เป็นลูกของ app.py (หรือเคยเป็น)
    การป้องกันจึงอยู่ตรงนี้ ไม่ใช่ไปบล็อกการรีสตาร์ตทั้งอันตั้งแต่ต้นทาง
    (เหตุผลเต็มอยู่ที่ `running_jobs()`)
    """
    for process in processes:
        say(f"• ปิด app.py (PID {process['pid']})")
        subprocess.run(["taskkill", "/PID", str(process["pid"]), "/F"],
                       capture_output=True, text=True, creationflags=_NO_WINDOW)
    for _ in range(30):
        if not port_busy():
            return
        time.sleep(0.5)

    # มาถึงตรงนี้ = พอร์ตไม่ยอมว่างใน 15 วิ ทางเดียวที่เหลือคือ /T /F
    # ซึ่งลากลูกตายไปด้วยทั้งชุด — ถ้ามีงานวิ่งอยู่ต้องหยุดให้คนตัดสิน
    # **ห้ามลากงานที่ทำมา 7 ชั่วโมงตายเงียบๆ เพื่อให้พอร์ตว่าง**
    live = running_jobs()
    if live and not force:
        names = " · ".join(_job_label(row) for row in live)
        raise Blocked(
            f"พอร์ต {PORT} ไม่ว่างใน 15 วิ ทางเดียวที่เหลือคือปิดแบบลากโปรเซสลูก "
            f"ซึ่งจะทำให้งานที่กำลังทำอยู่ตายไปด้วย: {names}\n"
            f"   app.py ตัวเดิมถูกปิดไปแล้ว แต่ยังไม่ได้เปิดตัวใหม่\n"
            f"   เลือกทางใดทางหนึ่ง: รอให้งานจบแล้วสั่งใหม่ · "
            f"หรือสั่ง --force ถ้ายอมให้งานพวกนี้ตาย"
        )
    if live:
        say(f"⚠️ --force: ยอมให้ปิดแบบลากลูก — {len(live)} งานอาจตายไปด้วย")
    # ยังไม่ปล่อยพอร์ต = มีลูกหลานค้างอยู่ ค่อยใช้ /T ซึ่งลากลูกไปด้วย
    for process in processes:
        subprocess.run(["taskkill", "/PID", str(process["pid"]), "/T", "/F"],
                       capture_output=True, text=True, creationflags=_NO_WINDOW)
        say(f"• ยังไม่ปล่อยพอร์ต — ปิดซ้ำพร้อมโปรเซสลูกของ PID {process['pid']}")
    for _ in range(20):
        if not port_busy():
            return
        time.sleep(0.5)
    raise Blocked(f"ปิดตัวเดิมแล้วแต่พอร์ต {PORT} ยังไม่ว่าง")


def start_app() -> None:
    log = BASE_DIR / SERVER_LOG
    log.parent.mkdir(parents=True, exist_ok=True)
    handle = open(log, "a", encoding="utf-8", errors="replace")
    handle.write(f"\n=== รีสตาร์ตโดย restart_studio.py {datetime.now():%d/%m %H:%M:%S} ===\n")
    handle.flush()
    # DETACHED_PROCESS — ต้องอยู่ต่อหลังสคริปต์นี้จบ ไม่งั้นปิดหน้าต่างแล้วตายตาม
    subprocess.Popen(
        [PYTHON, "app.py"], cwd=str(BASE_DIR), stdout=handle, stderr=handle,
        creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
    )


def wait_ready(started_after: datetime) -> dict:
    """รอจนเซิร์ฟเวอร์ตอบ แล้วยืนยันว่าเป็น**ตัวใหม่จริง** ไม่ใช่ตัวเดิมที่ไม่ได้ตาย"""
    deadline = time.time() + STARTUP_WAIT_SECONDS
    system = None
    while time.time() < deadline:
        system = get_json("/api/system", timeout=3.0)
        if system:
            break
        time.sleep(1.0)
    if not system:
        raise Blocked(
            f"เปิดแล้วแต่ไม่ตอบภายใน {STARTUP_WAIT_SECONDS} วินาที — ดู {SERVER_LOG}"
        )
    owners = app_processes()
    if not owners:
        raise Blocked(f"ตอบอยู่ก็จริง แต่ไม่เจอโปรเซส app.py ที่ถือพอร์ต {PORT}")
    fresh = [
        p for p in owners
        if p["started"] is None or p["started"] >= started_after - timedelta(seconds=5)
    ]
    if not fresh:
        raise Blocked("ตอบอยู่ก็จริง แต่โปรเซสที่ถือพอร์ตยังเป็นตัวเดิม — ไม่ได้รีสตาร์ตจริง")
    return {"system": system, "process": fresh[0]}


# ------------------------------------------------------------------- main

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="รีสตาร์ต Pipeline Studio 8866")
    parser.add_argument("--force", action="store_true", help="ข้ามด่านตรวจ")
    parser.add_argument("--dry-run", action="store_true", help="ตรวจอย่างเดียว")
    parser.add_argument("--no-backup", action="store_true", help="ไม่ต้องสำรอง")
    args = parser.parse_args(argv)

    say("=== ตรวจก่อนรีสตาร์ต 8866 ===")
    show_state()

    try:
        reasons = check_safe()
    except Blocked as error:
        say(f"\n❌ ตรวจไม่ได้ — {error}")
        return 2
    if reasons:
        say("")
        for reason in reasons:
            say(f"❌ ไม่ควรรีสตาร์ต — {reason}")
        if not args.force:
            say("\nรอให้จบก่อน หรือสั่ง /stop ใน Telegram")
            say("ถ้ายืนยันจะรีสตาร์ตจริงๆ: restart_studio.bat --force")
            return 1
        say("\n⚠️ --force: ข้ามด่านตรวจตามที่สั่ง")
    else:
        # ห้ามพูดว่า "ไม่มีงานรันอยู่" ลอยๆ ถ้าด้านบนเพิ่งไล่ชื่องานที่วิ่งอยู่ให้ดู
        # — ข้อความที่ขัดกับสิ่งที่เห็นตรงหน้าทำให้คนเลิกเชื่อด่านทั้งอัน
        live = running_jobs()
        if live:
            say(f"✅ รีสตาร์ตได้ · ไม่มีงานโพสต์/งานตั้งเวลาขวางอยู่ "
                f"(งานเบื้องหลัง {len(live)} ตัวจะทำงานต่อตามปกติ)")
        else:
            say("✅ ไม่มีงานรันอยู่ · ไม่มีงานตั้งเวลาใกล้ถึง")

    if args.dry_run:
        say("\n(--dry-run: หยุดแค่นี้ ไม่ได้แตะอะไร)")
        return 0

    if not args.no_backup:
        try:
            sys.path.insert(0, str(BASE_DIR))
            import fb_backup
            result = fb_backup.make_backup("restart")
            say(f"✅ สำรองแล้ว → {result['path'].name} "
                f"({result['files']} ไฟล์ · {result['bytes'] / 1024:.0f} KB)")
            for note in result["skipped"]:
                say(f"   ⚠️ ข้าม {note}")
        except Exception as error:
            # สำรองไม่ได้ = ไม่รีสตาร์ต ยกเว้นสั่ง --force
            #
            # จุดประสงค์ของการสำรองคือ "กันของหายตอนรีสตาร์ต" ถ้าปล่อยผ่านตรงนี้
            # ก็เท่ากับไม่มีการสำรองในจังหวะที่ต้องใช้มากที่สุดพอดี
            say(f"❌ สำรองไม่สำเร็จ: {error}")
            if not args.force:
                say("   ข้ามด้วย --no-backup ถ้ายอมรับความเสี่ยงนี้")
                return 2

    running = app_processes()
    others = other_studio_processes()
    started_at = datetime.now()
    try:
        if running:
            stop_app(running, force=args.force)
        else:
            say("• ไม่มี app.py รันอยู่ — เปิดใหม่อย่างเดียว")
        for process in others:
            name = next(
                (n for n in ("clip_app.py", "fb_mass_bot.py", "fb_engage_bot.py")
                 if n in process["cmd"]), "โปรเซสอื่น"
            )
            say(f"• {name} (PID {process['pid']}) ยังอยู่ — ไม่ได้แตะ")
        start_app()
        ready = wait_ready(started_at)
    except Blocked as error:
        say(f"\n❌ {error}")
        return 2

    version = ready["system"].get("app_version", "?")
    say(f"✅ ขึ้นแล้ว PID {ready['process']['pid']} · เวอร์ชัน {version}")
    say(f"   เปิดหน้าเว็บ: {API}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
