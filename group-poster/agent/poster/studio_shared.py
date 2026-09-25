"""ตัวแทน studio_shared ของ Pipeline Studio — มีเฉพาะที่โมดูลโพสต์เรียกใช้

ของจริงผูกกับ Windows (msvcrt, ctypes) และระบบล็อกข้ามโปรเซสของ Studio
ซึ่งเกินจำเป็นสำหรับโปรแกรมลูกค้าที่มีโปรเซสเดียว ตัวนี้จึงทำแค่เท่าที่ต้องใช้
และทำงานได้ทั้ง Windows/macOS/Linux

ไฟล์อื่นในโฟลเดอร์นี้ copy มาจาก Studio ตรงๆ ด้วย `python sync_poster.py`
**ห้ามแก้ไฟล์ที่ copy มา** แก้ที่ Studio แล้ว sync ใหม่ ไม่งั้นสองฝั่งจะค่อยๆ ไม่ตรงกัน
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
from contextlib import contextmanager
from pathlib import Path

DATA_DIR = Path(os.environ.get("GP_AGENT_DATA")
                or Path(__file__).resolve().parents[1] / "data")
POST_EVIDENCE = DATA_DIR / "evidence-post"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
CONFIG_FILE = DATA_DIR / "studio_config.json"

_locks: dict[str, threading.RLock] = {}
_locks_guard = threading.Lock()


@contextmanager
def data_lock(name: str, timeout: float = 30.0, poll: float = 0.2, label: str = ""):
    with _locks_guard:
        lock = _locks.setdefault(str(name), threading.RLock())
    with lock:
        yield


def read_json(path: Path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def write_json_atomic(path: Path, payload) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, path)


def read_config() -> dict:
    return read_json(CONFIG_FILE, {})


def account_file(account: str, name: str) -> Path:
    import re
    slug = re.sub(r"[^A-Za-z0-9._-]", "_", str(account or "default").strip())[:60] or "default"
    folder = DATA_DIR / "accounts" / slug
    folder.mkdir(parents=True, exist_ok=True)
    return folder / name
