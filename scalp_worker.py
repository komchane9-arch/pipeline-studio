"""พนักงานเดินงานค้นหาสินค้า — ไล่ทำงานในกล่องทีละใบ แม้ไม่มีแชทไหนเปิดอยู่

**หน้าที่** หยิบใบงานจาก `scalp_jobs` ตามลำดับที่หย่อนเข้ามา → กดบัตรคิวจอของ
เครื่องสาย scalp → ทำงาน → เขียนผล → หยิบใบถัดไปทันที

**ทำไมต้องเป็นโปรเซสแยก ไม่ใช่ให้แชทลงมือเอง** ไม่มีอะไรปลุกแชทที่ปิดไปแล้วได้
(คู่มือข้อ 7.8) ถ้าให้แชททำเอง "แชทไหนเสร็จ อีกแชทเริ่มทันที" จะเป็นจริงเฉพาะ
ตอนที่ทุกแชทเปิดค้างรออยู่พร้อมกัน ซึ่งไม่ใช่วิธีที่เจ้าของทำงานจริง

**สิ่งที่ยังทำไม่ได้ ต้องพูดให้ชัด** ตอนนี้มีตัวเก็บของจริงแค่ทางเดียวคือ
Shopee แบบไล่ร้านจากหน้า "ร้านฮิตติดเทรนด์" (`12.เก็บข้อมูล/tools/collect.py`)
ส่วน **การค้นหาด้วยคำค้นทั้ง 4 แอปยังไม่มีใครเขียน** — ต้องมีมือถือสาย scalp
อยู่ตรงหน้าถึงจะไล่โครงหน้าจอของแต่ละแอปได้ ไฟล์นี้จึงเตรียมช่องไว้ให้ครบ
แล้ว **ล้มเสียงดังพร้อมบอกว่าขาดอะไร** ไม่ใช่เงียบหรือทำมั่ว

    python scalp_worker.py            ทำไปเรื่อยๆ จนกล่องหมด แล้วเฝ้ารอใบใหม่
    python scalp_worker.py --once     ทำใบเดียวแล้วออก (ใช้ตอนทดสอบ)
"""

from __future__ import annotations

import argparse
import contextlib
import os
import subprocess
import sys
import time
import traceback
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import phone_queue                                              # noqa: E402
import scalp_jobs                                               # noqa: E402

WORKER_NAME = os.environ.get("SCALP_WORKER_NAME", "พนักงานเดินงานค้นหา")
IDLE_SLEEP = 5.0            # กล่องว่างแล้วถามซ้ำทุกกี่วิ
JOB_TIMEOUT = 3600.0        # งานหนึ่งใบใช้เวลาได้นานสุดเท่าไร
COLLECT_DIR = Path(r"C:\project\2.Auto gen Video\12.เก็บข้อมูล\tools")

LOG_FILE = scalp_jobs.DATA_DIR / "logs" / "scalp_worker.log"


def log(message: str) -> None:
    line = f"{time.strftime('%H:%M:%S')} [{WORKER_NAME}] {message}"
    print(line, flush=True)
    with contextlib.suppress(OSError):
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as handle:
            handle.write(line + "\n")


def _beat() -> None:
    """บอกว่ายังมีชีวิต — ใช้ตัวเดียวกับที่ระบบใช้เฝ้าบอทตัวอื่นถ้ามี"""
    with contextlib.suppress(Exception):
        import heartbeat                                        # noqa: PLC0415
        heartbeat.beat("scalp_worker")


class NeedsHuman(RuntimeError):
    """งานนี้คนต้องมาตัดสิน — ห้ามพนักงานเดาเอง

    เช่นเจอ CAPTCHA · แอปเด้งออก · หน้าจอไม่ใช่ที่คาด — ทำต่อเองมีแต่จะได้
    ข้อมูลผิดซึ่งมองไม่ออกจนกว่าจะเอาไปใช้ ยอมหยุดใบนี้แล้วไปใบถัดไปดีกว่า
    """


class NotBuiltYet(RuntimeError):
    """ยังไม่ได้เขียนตัวทำงานของทางนี้ — ต้องบอกให้ชัดว่าขาดอะไร"""


# ---------------------------------------------------------------- ตัวทำงานจริง
def _run_shopee_shops(job: dict) -> str:
    """ไล่เก็บร้านจากหน้า "ร้านฮิตติดเทรนด์" — ของเดิมที่ใช้งานได้จริงอยู่แล้ว

    เรียกเป็นโปรเซสลูกแทนการ import เพราะ `collect.py` ทำงานตอน import
    (ตั้งค่าคงที่ · เปิดไฟล์ผลลัพธ์) และตายกลางทางได้ — แยกโปรเซสแล้ว
    ความตายของมันไม่ลากพนักงานตายตาม
    """
    script = COLLECT_DIR / "collect.py"
    if not script.is_file():
        raise NotBuiltYet(f"ไม่พบ {script}")
    env = dict(os.environ, PYTHONIOENCODING="utf-8",
               PHONE_QUEUE_OWNER=f"{WORKER_NAME} · ใบ #{job['id']}")
    limit = str((job.get("options_parsed") or {}).get("shops") or 1)
    env["MAXSHOPS"] = limit
    result = subprocess.run(
        [sys.executable, str(script)], cwd=str(COLLECT_DIR), env=env,
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=JOB_TIMEOUT)
    tail = "\n".join((result.stdout or "").strip().splitlines()[-6:])
    if "captcha" in (result.stdout or "").lower():
        raise NeedsHuman("เจอ CAPTCHA ระหว่างเก็บ — ต้องมีคนไปปลดก่อน\n" + tail)
    if result.returncode != 0:
        raise RuntimeError(f"ตัวเก็บจบด้วยรหัส {result.returncode}\n{tail}")
    return tail or "จบงานแล้ว"


def _search_not_built(job: dict) -> str:
    app = scalp_jobs.TOPICS[job["topic"]]
    raise NotBuiltYet(
        f"ยังไม่ได้เขียนตัวค้นหาด้วยคำค้นของ {app} — ต้องมีมือถือสาย scalp "
        f"อยู่ตรงหน้าเพื่อไล่โครงหน้าจอก่อน (ช่องจองไว้ให้แล้วที่ "
        f"scalp_worker.HANDLERS[('{job['topic']}', 'search')])")


# (หัวข้อ, โหมด) -> ตัวทำงาน · เพิ่มทางใหม่แก้ที่นี่ที่เดียว
HANDLERS = {
    ("shopee", "shops"): _run_shopee_shops,
    ("shopee", "search"): _search_not_built,
    ("lazada", "search"): _search_not_built,
    ("lineman", "search"): _search_not_built,
    ("shopeefood", "search"): _search_not_built,
}


def run_job(job: dict, serial: str) -> None:
    """ทำหนึ่งใบ — กดบัตรคิวจอครอบไว้ทั้งใบ ไม่ใช่ทีละคำสั่ง"""
    import json
    options = {}
    with contextlib.suppress(Exception):
        options = json.loads(job.get("options") or "{}")
    job["options_parsed"] = options
    mode = str(options.get("mode") or "search").lower()
    handler = HANDLERS.get((job["topic"], mode))
    app = scalp_jobs.TOPICS[job["topic"]]

    if handler is None:
        scalp_jobs.finish(job["id"], scalp_jobs.FAILED,
                          f"ไม่รู้จักโหมด '{mode}' ของ {app}")
        log(f"❌ ใบ #{job['id']} ไม่รู้จักโหมด '{mode}'")
        return

    task = f"[{app}] {job['keyword']}"
    log(f"▶ ใบ #{job['id']} {task} (สั่งโดย {job['chat'] or 'ไม่ระบุ'})")
    try:
        with phone_queue.slot(serial, owner=f"{WORKER_NAME}", task=task,
                              lane="scalp", timeout=JOB_TIMEOUT,
                              on_wait=lambda n: log(f"  ⏳ รอคิวจอ ลำดับที่ {n}")):
            _beat()
            result = handler(job)
    except NeedsHuman as error:
        scalp_jobs.finish(job["id"], scalp_jobs.ATTENTION, str(error)[:400])
        log(f"🚨 ใบ #{job['id']} ต้องให้คนตัดสิน — {error}")
        return
    except NotBuiltYet as error:
        scalp_jobs.finish(job["id"], scalp_jobs.ATTENTION, str(error)[:400])
        log(f"🚧 ใบ #{job['id']} ยังทำไม่ได้ — {error}")
        return
    except subprocess.TimeoutExpired:
        scalp_jobs.finish(job["id"], scalp_jobs.FAILED,
                          f"ทำเกิน {JOB_TIMEOUT / 60:.0f} นาทีแล้วยังไม่จบ")
        log(f"⌛ ใบ #{job['id']} เกินเวลา")
        return
    except Exception as error:                                  # noqa: BLE001
        detail = f"{type(error).__name__}: {error}"
        scalp_jobs.finish(job["id"], scalp_jobs.FAILED, detail[:400])
        log(f"❌ ใบ #{job['id']} ล้ม — {detail}")
        log(traceback.format_exc())
        return
    scalp_jobs.finish(job["id"], scalp_jobs.DONE, "เสร็จแล้ว", result=str(result)[:2000])
    log(f"✅ ใบ #{job['id']} เสร็จ")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="พนักงานเดินงานค้นหาสินค้า")
    parser.add_argument("--once", action="store_true", help="ทำใบเดียวแล้วออก")
    args = parser.parse_args(argv)

    back = scalp_jobs.reset_stuck(WORKER_NAME)
    if back:
        log(f"คืนใบที่ค้างจากรอบก่อนเข้ากล่อง {back} ใบ")

    try:
        serial = phone_queue.device_for_lane("scalp")
        log(f"เครื่องของสายค้นหา: {serial}")
    except Exception as error:                                  # noqa: BLE001
        log(f"⛔ ยังเริ่มไม่ได้ — {error}")
        return 1

    log("พร้อมทำงาน")
    while True:
        _beat()
        job = scalp_jobs.claim_next(WORKER_NAME)
        if job is None:
            if args.once:
                log("กล่องว่าง — ไม่มีอะไรให้ทำ")
                return 0
            time.sleep(IDLE_SLEEP)
            continue
        run_job(job, serial)
        if args.once:
            return 0


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        with contextlib.suppress(Exception):
            _stream.reconfigure(encoding="utf-8")
    raise SystemExit(main())
