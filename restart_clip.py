"""รีสตาร์ตเซิร์ฟเวอร์สายคลิป (8877) แบบไม่ฆ่างานที่กำลังเดินอยู่

**เหตุการณ์ที่ทำให้ต้องมี — 30 ส.ค. 2569 เสียของจริง**

ผมสั่งรีสตาร์ตด้วยสคริปต์ชั่วคราวที่เขียนว่า

    for _ in range(120):
        if ไม่มีงานเดินอยู่:
            break
        time.sleep(5)
    taskkill ...                 # ← ตกมาถึงตรงนี้ทั้งตอน break และตอนครบ 120 รอบ

คิวไม่เคยว่างเลยตลอด 10 นาที พอครบ 120 รอบมันก็ **เดินหน้าฆ่าเหมือนคิวว่างจริง**
ทั้งที่ความหมายตรงกันข้ามสิ้นเชิง — "รอจนหมดเวลา" แปลว่า *ยิ่งห้ามฆ่า*

    15:40:52  เริ่มรอ (120 รอบ × 5 วินาที = 600 วินาที)
    15:49:17  เจนคลิปรอบใหม่เริ่ม ใช้เครดิตไป 30
    15:50:56  เจนคลิปช่อง 2 เริ่มอีกใบ  ← ถูกฆ่าตรงนี้ log จบทันที
    15:50:56  ครบ 600 วินาทีพอดี

ผลคือ **เซิร์ฟเวอร์ดับ 8 นาที** และคลิปที่ถูกลบไฟล์เดิมทิ้งไปแล้วเพื่อเจนใหม่
เกือบไม่เหลืออะไรเลย (`27328254376` — โชคดีที่ตัวกู้งานค้างตอนเปิดใหม่ช่วยไว้)

**รากของมันคือกติกาข้อ 2.3.1** — คำถาม *"ลูปจบหรือยัง"* ตอบว่า "จบแล้ว" ได้
ทั้งตอนคิวว่างจริงและตอนรอจนเบื่อ ตัวนี้จึงแยกสองสถานะออกจากกันให้ชัด
**หมดเวลา = ออกโดยไม่ทำอะไร แล้วบอกว่าทำไม**

---

    python restart_clip.py              รอจนคิวว่างแล้วรีสตาร์ต (รอสูงสุด 10 นาที)
    python restart_clip.py --wait 20    รอนานขึ้น (นาที)
    python restart_clip.py --check      ดูอย่างเดียว ไม่รีสตาร์ต
    python restart_clip.py --force      รีเลยแม้มีงานเดินอยู่ (ต้องตั้งใจจริงๆ)

คืนค่า 0 = รีสตาร์ตสำเร็จและพอร์ตกลับมาแล้ว · 1 = ไม่ได้รี หรือรีแล้วไม่ขึ้น
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

DATA_DIR = BASE_DIR / "data"
QUEUE_FILE = DATA_DIR / "clip_queue.json"
PORT = 8877

# ขั้นที่แปลว่า "เครื่องกำลังลงมือทำอยู่จริง" — ฆ่าตอนนี้คือทิ้งงานกลางคัน
#
# `generating` แพงที่สุด เพราะจ่ายเครดิต Veo ไปแล้วและถอนคืนไม่ได้
# `collecting` เสียโควตา Shopee และเสี่ยงทำให้โดนบล็อกถ้าไปเริ่มใหม่ถี่ๆ
# `making_storyboard` เสียโควตา ChatGPT หนึ่งรอบ
BUSY_STAGES = ("generating", "collecting", "tiktok_posting")

# ขั้นที่ **ขาดกลางคันแล้วกู้เองได้** — บอกให้รู้ แต่ไม่ห้ามรีสตาร์ต
#
# **เพิ่ม 30 ส.ค. 2569** หลังเจอว่ารอ 12 นาทีแล้วยังหาช่องว่างไม่ได้เลย
# เพราะพอเปิดครบสามช่อง คิวแทบไม่มีวินาทีไหนว่างพร้อมกันทั้งหมด
#
# **แยกตามราคาของการขาดกลางคัน ไม่ใช่แยกตามว่ากำลังทำอยู่ไหม**
#   generating       จ่ายเครดิต Veo ไปแล้ว 15 หน่วย ถอนคืนไม่ได้  → ห้ามขาด
#   collecting       เสี่ยงทำให้ Shopee บล็อกถ้าไปเริ่มดึงใหม่ถี่ๆ  → ห้ามขาด
#   tiktok_posting   กำลังกดจอโพสต์จริง                          → ห้ามขาด
#   making_storyboard  เสียแค่ ChatGPT หนึ่งรอบ (~3 นาที) และ
#                      `clip_jobs.recover()` เอากลับเข้าคิวให้เองตอนเปิดใหม่ → ขาดได้
#   revising           เหมือนกัน คนที่สั่งแก้จะเห็นว่าต้องสั่งใหม่ → ขาดได้
SOFT_STAGES = ("making_storyboard", "revising")

# ขั้นที่ยอมให้ขาดได้ — ตัวกู้งานค้างตอนเปิดใหม่เอากลับเข้าคิวให้เอง
# และไม่ได้จ่ายอะไรไปแล้ว


def say(message: str) -> None:
    try:
        print(message, flush=True)
    except UnicodeEncodeError:
        sys.stdout.buffer.write((message + "\n").encode("utf-8", "replace"))


def port_up(timeout: float = 1.5) -> bool:
    """8877 มีคนฟังอยู่ไหม — ต่อจริง ไม่ใช่เดาจากตารางโปรเซส"""
    with socket.socket() as probe:
        probe.settimeout(timeout)
        return probe.connect_ex(("127.0.0.1", PORT)) == 0


def _all_jobs() -> list[dict]:
    try:
        return json.loads(QUEUE_FILE.read_text(encoding="utf-8"))
    except Exception:                                            # noqa: BLE001
        return []


def busy_jobs() -> list[dict]:
    """งานที่ **ขาดกลางคันไม่ได้** — ไม่ใช่ทุกงานที่กำลังทำอยู่"""
    return [j for j in _all_jobs() if j.get("stage") in BUSY_STAGES]


def server_pids() -> list[int]:
    """หมายเลขโปรเซสของ clip_app.py ที่รันอยู่"""
    done = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
         "Where-Object { $_.CommandLine -like '*clip_app*' } | "
         "ForEach-Object { $_.ProcessId }"],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    return [int(x) for x in done.stdout.split() if x.strip().isdigit()]


def death_reason(lines: int = 300) -> str:
    """สาเหตุที่เปิดไม่ขึ้น อ่านจากท้าย log — บอกสาเหตุ ไม่ใช่บอกแค่อาการ"""
    for name in ("clip_app_restart.log", "clip_server.log"):
        path = DATA_DIR / name
        if not path.is_file():
            continue
        try:
            tail = path.read_text(encoding="utf-8",
                                  errors="replace").splitlines()[-lines:]
        except Exception:                                        # noqa: BLE001
            continue
        for line in reversed(tail):
            text = line.strip()
            if not text or text.startswith(("File ", "Traceback")):
                continue
            if line[:1] in (" ", "\t"):
                continue
            if any(mark in text for mark in ("Error", "Exception", "error:")):
                return f"{name}: {text[:200]}"
    return ""


def report() -> list[dict]:
    """บอกสถานะปัจจุบันแล้วคืนรายการงานที่กำลังทำอยู่"""
    say("=== ตรวจก่อนรีสตาร์ตสายคลิป (8877) ===")
    say(f"• พอร์ต {PORT}: {'ตอบอยู่' if port_up() else 'ไม่ตอบ'}")
    pids = server_pids()
    say(f"• โปรเซส clip_app.py: {pids or 'ไม่มี'}")
    soft = [j for j in _all_jobs() if j.get("stage") in SOFT_STAGES]
    if soft:
        say(f"• งานที่ขาดได้และกู้เองตอนเปิดใหม่ {len(soft)} ใบ:")
        for job in soft:
            say(f"   - {job.get('id')} · {job.get('stage')} · สินค้า {job.get('item_id')}")
    busy = busy_jobs()
    if not busy:
        say("• ไม่มีงานที่ขาดไม่ได้ — รีสตาร์ตได้")
    else:
        say(f"• มีงานกำลังทำอยู่ {len(busy)} ใบ:")
        for job in busy:
            cost = " · จ่ายเครดิต Veo ไปแล้ว" if job.get("stage") == "generating" else ""
            say(f"   - {job.get('id')} · {job.get('stage')} · "
                f"สินค้า {job.get('item_id')}{cost}")
    return busy


def start_server() -> bool:
    """เปิดเซิร์ฟเวอร์ใหม่แล้ว **ยืนยันว่าพอร์ตกลับมาจริง**

    ยืนยันเสมอ ไม่ใช่สั่งแล้วเดินจากไป — ครั้งที่พังคือครั้งเดียวที่สั่งแล้ว
    ไม่ได้รอผล จึงไม่มีใครรู้ว่าตายมา 8 นาที
    """
    log = open(DATA_DIR / "clip_app_restart.log", "ab")
    try:
        # โปรเซสแบบซ่อนหน้าต่างบน Windows ไม่มี console code page ให้ Python
        # จึงอาจตกกลับไปใช้ cp1252 และตายตั้งแต่ print ชื่อเซิร์ฟเวอร์ภาษาไทย
        # ส่ง encoding ให้โปรเซสลูกชัดเจนทุกครั้งที่ปลุกใหม่
        child_env = os.environ.copy()
        child_env["PYTHONIOENCODING"] = "utf-8"
        subprocess.Popen([sys.executable, "clip_app.py"], cwd=str(BASE_DIR),
                         stdout=log, stderr=subprocess.STDOUT,
                         env=child_env,
                         creationflags=0x00000008 | 0x00000200)
    finally:
        log.close()
    for second in range(120):
        if port_up():
            say(f"✅ เซิร์ฟเวอร์กลับมาแล้วใน {second + 1} วินาที")
            return True
        time.sleep(1)
    why = death_reason()
    say("❌ เปิดแล้วพอร์ตไม่กลับมาใน 120 วินาที")
    say(f"   สาเหตุ: {why}" if why else "   หาสาเหตุจาก log ไม่เจอ")
    return False


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wait", type=float, default=10.0,
                        help="รอคิวว่างสูงสุดกี่นาที (ค่าปริยาย 10)")
    parser.add_argument("--check", action="store_true", help="ดูอย่างเดียว ไม่รีสตาร์ต")
    parser.add_argument("--force", action="store_true",
                        help="รีแม้มีงานเดินอยู่ — จะทิ้งงานกลางคันจริงๆ")
    parser.add_argument("--skip-load-check", action="store_true",
                        help="ข้ามการลองโหลดโมดูลก่อนรี (ไม่แนะนำ)")
    args = parser.parse_args(argv)

    busy = report()
    if args.check:
        return 0 if not busy else 1

    # ---- ลองโหลดโมดูลก่อน ปิดก่อนรู้ว่าเปิดไม่ขึ้นคือเสียเวลาเปล่า ----
    if not args.skip_load_check:
        say("\n=== ลองโหลด clip_app ในสนามทดสอบก่อน ===")
        done = subprocess.run([sys.executable, "load_check.py", "--import",
                               "clip_app.py"], cwd=str(BASE_DIR),
                              capture_output=True, text=True,
                              encoding="utf-8", errors="replace")
        say((done.stdout or "").strip() or "(ไม่มีผลลัพธ์)")
        if done.returncode != 0:
            say("\n❌ ไม่รีสตาร์ต — โค้ดโหลดไม่ขึ้น ปิดของเก่าไปจะไม่มีอะไรมาแทน")
            say((done.stderr or "").strip()[-500:])
            return 1

    # ---- รอคิวว่าง แต่ **หมดเวลาแล้วห้ามฆ่า** ----
    deadline = time.time() + args.wait * 60
    if busy and not args.force:
        say(f"\nรอให้งานที่ทำอยู่จบก่อน (สูงสุด {args.wait:.0f} นาที)…")
        while time.time() < deadline:
            busy = busy_jobs()
            if not busy:
                say("คิวว่างแล้ว — รีสตาร์ตได้")
                break
            time.sleep(5)
        else:
            # **นี่คือจุดที่เคยพลาด** — ของเดิมตกมาถึงตรงนี้แล้วฆ่าต่อ
            say(f"\n❌ ไม่รีสตาร์ต — รอครบ {args.wait:.0f} นาทีแล้วยังมีงานเดินอยู่ "
                f"{len(busy)} ใบ")
            for job in busy:
                say(f"   - {job.get('id')} · {job.get('stage')} · "
                    f"สินค้า {job.get('item_id')}")
            say("   \"รอจนหมดเวลา\" ไม่ได้แปลว่า \"ว่างแล้ว\" — "
                "แปลว่างานยังเดินอยู่ ยิ่งห้ามฆ่า")
            # เสนอเวลาที่ **ใช้ได้จริง** — เท่าตัวของค่าที่เพิ่งลอง แต่ไม่ต่ำกว่า 20 นาที
            # (เคยพิมพ์ออกมาเป็น "--wait 0" ตอนทดสอบด้วยค่าน้อยๆ ซึ่งแนะนำแล้วยิ่งพัง)
            again = max(20, round(args.wait * 2))
            say(f"   รอต่อด้วย  python restart_clip.py --wait {again}")
            say("   หรือถ้ายอมทิ้งงานจริงๆ  python restart_clip.py --force")
            return 1

    if busy and args.force:
        say(f"\n⚠️ --force: จะทิ้งงานที่ทำอยู่ {len(busy)} ใบกลางคัน")

    for pid in server_pids():
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                       capture_output=True)
        say(f"ปิดโปรเซส {pid} แล้ว")
    time.sleep(3)
    return 0 if start_server() else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
