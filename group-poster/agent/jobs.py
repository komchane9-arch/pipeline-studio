"""งานโพสต์หนึ่งรอบ — รันในเธรดแยก เก็บ log และผลรายกลุ่มไว้ให้หน้าเว็บอ่าน

ตัวโพสต์จริงคือ `facebook_group_post.post_to_groups` จาก Studio ไม่ได้เขียนใหม่
ไฟล์นี้แค่ห่อให้มีหยุดได้ มีความคืบหน้า และบังคับเพดานตาม license
"""

from __future__ import annotations

import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable

POSTER_DIR = Path(__file__).resolve().with_name("poster")
if str(POSTER_DIR) not in sys.path:
    sys.path.insert(0, str(POSTER_DIR))

MAX_LOG_LINES = 2000
GROUP_ID_RE = re.compile(r"^[0-9]{5,25}$")
GROUP_URL_RE = re.compile(r"facebook\.com/groups/([^/?#\s]+)", re.IGNORECASE)


def parse_groups(text: str) -> tuple[list[str], list[str]]:
    """แยกรายชื่อกลุ่มจากข้อความ — รับทั้งเลข ID และลิงก์กลุ่ม คืน (ใช้ได้, ใช้ไม่ได้)"""
    ids: list[str] = []
    bad: list[str] = []
    for raw in re.split(r"[\s,]+", str(text or "")):
        item = raw.strip()
        if not item:
            continue
        found = GROUP_URL_RE.search(item)
        value = found.group(1) if found else item
        if GROUP_ID_RE.match(value):
            if value not in ids:
                ids.append(value)
        else:
            # ลิงก์แบบชื่อ (facebook.com/groups/abcshop) เปิดผ่าน fb://group/ ไม่ได้
            # ต้องเป็นเลข ID เท่านั้น — บอกให้ชัดตั้งแต่ตอนกรอก ดีกว่าไปล้มกลางงาน
            bad.append(item)
    return ids, bad


def find_adb(configured: str = "") -> str:
    here = Path(__file__).resolve().parent
    for candidate in (configured, here / "tools" / "adb.exe", here / "tools" / "adb"):
        if candidate and Path(candidate).exists():
            return str(candidate)
    return shutil.which("adb") or "adb"


def list_devices(adb: str) -> list[dict]:
    try:
        out = subprocess.run(
            [adb, "devices", "-l"], capture_output=True, text=True, timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        ).stdout
    except (OSError, subprocess.SubprocessError) as error:
        return [{"serial": "", "state": "error", "model": f"เรียก adb ไม่ได้: {error}"}]
    devices = []
    for line in out.splitlines()[1:]:
        parts = line.split()
        if len(parts) < 2:
            continue
        model = next((p.split(":", 1)[1] for p in parts[2:] if p.startswith("model:")), "")
        devices.append({"serial": parts[0], "state": parts[1], "model": model})
    return devices


def default_poster() -> Callable:
    import facebook_group_post
    return facebook_group_post.post_to_groups


class Job:
    def __init__(self, job_id: str, groups: list[str], dry_run: bool) -> None:
        self.id = job_id
        self.groups = groups
        self.dry_run = dry_run
        self.state = "running"
        self.started = time.time()
        self.finished: float | None = None
        self.logs: list[str] = []
        self.results: dict[str, dict] = {}
        self.error = ""
        self.stop_event = threading.Event()
        self.lock = threading.Lock()

    def log(self, message) -> None:
        line = f"{time.strftime('%H:%M:%S')} {message}"
        with self.lock:
            self.logs.append(line)
            del self.logs[:-MAX_LOG_LINES]

    def on_result(self, entry: dict) -> None:
        with self.lock:
            key = str(entry.get("group_id", ""))
            self.results[key] = {**self.results.get(key, {}), **entry}

    def snapshot(self, since: int = 0) -> dict:
        with self.lock:
            return {
                "id": self.id, "state": self.state, "dry_run": self.dry_run,
                "groups": self.groups, "error": self.error,
                "started": self.started, "finished": self.finished,
                "log_total": len(self.logs), "logs": self.logs[since:],
                "results": [self.results.get(g, {"group_id": g}) for g in self.groups],
            }


class JobRunner:
    """รันได้ทีละงานต่อเครื่อง — มือถือเครื่องเดียวทำสองงานพร้อมกันไม่ได้"""

    def __init__(self, upload_dir: Path, poster: Callable | None = None) -> None:
        self.upload_dir = Path(upload_dir)
        self.poster = poster
        self.jobs: dict[str, Job] = {}
        self.current: Job | None = None
        self.lock = threading.Lock()

    def busy(self) -> bool:
        return bool(self.current and self.current.state == "running")

    def start(self, *, adb: str, serial: str, images: list[Path], caption: str,
              comment: str, groups: list[str], gap: tuple[float, float],
              dry_run: bool) -> Job:
        with self.lock:
            if self.busy():
                raise RuntimeError("มีงานกำลังโพสต์อยู่ รอให้จบหรือกดหยุดก่อน")
            job = Job("j" + secrets.token_hex(4), groups, dry_run)
            self.jobs[job.id] = job
            self.current = job
        poster = self.poster or default_poster()

        def run() -> None:
            job.log(f"เริ่มงาน {len(groups)} กลุ่ม บนเครื่อง {serial}"
                    + (" (ทดลอง ไม่กดโพสต์จริง)" if dry_run else ""))
            try:
                poster(
                    adb, serial, [str(p) for p in images], caption, groups,
                    gap_range=gap, dry_run=dry_run, log=job.log,
                    stop=job.stop_event.is_set, on_result=job.on_result,
                    comment=comment,
                )
                job.state = "stopped" if job.stop_event.is_set() else "done"
            except Exception as error:  # noqa: BLE001 — ต้องรายงานทุกแบบให้ผู้ใช้เห็น
                job.error = str(error) or type(error).__name__
                job.log(f"งานล้ม: {job.error}")
                job.state = "failed"
            finally:
                job.finished = time.time()
                job.log("จบงาน")

        threading.Thread(target=run, name=f"job-{job.id}", daemon=True).start()
        return job

    def stop(self, job_id: str) -> bool:
        job = self.jobs.get(job_id)
        if not job:
            return False
        job.stop_event.set()
        job.log("สั่งหยุดแล้ว — จะหยุดหลังขั้นที่กำลังทำอยู่เสร็จ")
        return True
