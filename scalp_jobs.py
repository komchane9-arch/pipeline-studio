"""คลังคำสั่งค้นหาสินค้า — แชทหย่อนงานลงกล่อง พนักงานเดินงานไล่ทำทีละใบ

**ทำไมต้องมีกล่องคั่นกลาง** เจ้าของสั่ง 21 ส.ค. 2569 ให้แยกเป็น 4 แชทตามหัวข้อ
(shopee · lazada · lineman · shopeefood) เพื่อให้ดูข้อมูลง่าย แล้วสั่งเพิ่มว่า
"แชทไหนทำเสร็จ อีกแชทเริ่มทันที"

ถ้าให้แต่ละแชทลงมือเอง คำว่า "เริ่มทันที" จะเป็นจริงเฉพาะแชทที่เปิดค้างรออยู่ —
เพราะ**ไม่มีอะไรปลุกแชทที่ปิดไปแล้วได้** (ข้อจำกัดของตัวแชทเอง จดไว้ในคู่มือข้อ 7.8
พิสูจน์แล้ว 15 ส.ค.: ข้อความข้ามแชทไปวางรออยู่ข้ามวันโดยไม่มีใครตอบ)

กล่องนี้จึงเป็นตัวคั่น: แชทหย่อนคำสั่งแล้วปิดไปได้เลย · `scalp_worker.py` ไล่ทำ
ต่อจนหมดกล่องแม้ไม่มีแชทไหนเปิดอยู่ · แชทกลับมาเปิดเมื่อไรก็อ่านผลที่ทำเสร็จแล้ว

**มาก่อนได้ก่อนข้ามหัวข้อ** เรียงตามเลขใบล้วน ไม่ใช่วนทีละหัวข้อ — เจ้าของสั่ง
FIFO และต้องเห็นลำดับชัดเจน ถ้าวนตามหัวข้อ คนที่สั่งก่อนอาจได้ทำทีหลัง

**งานที่ต้องให้คนตัดสิน** (เจอ CAPTCHA · สินค้าราคาแปลก · แอปเด้งออก) ไม่ทำต่อเอง
แต่ติดธง `attention` แล้วข้ามไปใบถัดไป เพื่อไม่ให้ทั้งกล่องค้างเพราะใบเดียว

    python scalp_jobs.py add shopee "หูฟังบลูทูธ" --chat "แชท shopee"
    python scalp_jobs.py board
    python scalp_jobs.py show 12
    python scalp_jobs.py drop 12
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import sqlite3
import sys
import threading
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
_data_name = os.environ.get("STUDIO_DATA_DIR", "data").strip() or "data"
DATA_DIR = Path(_data_name) if Path(_data_name).is_absolute() else BASE_DIR / _data_name
DB_PATH = DATA_DIR / "scalp_jobs.db"

# หัวข้อที่รับ — เพิ่มหัวข้อใหม่แก้ที่นี่ที่เดียว ทั้งกล่องและพนักงานอ่านจากตรงนี้
TOPICS = {
    "shopee": "Shopee",
    "lazada": "Lazada",
    "lineman": "LINE MAN",
    "shopeefood": "Shopee Food",
}

QUEUED, RUNNING, DONE, FAILED, ATTENTION, CANCELLED = (
    "queued", "running", "done", "failed", "attention", "cancelled")
OPEN_STATES = (QUEUED, RUNNING)


class JobError(RuntimeError):
    """กล่องปฏิเสธคำขอ — ต้องดังเสมอ"""


_local = threading.local()


def connect() -> sqlite3.Connection:
    conn = getattr(_local, "conn", None)
    if conn is not None:
        return conn
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=15.0, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=15000")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS job("
        " id         INTEGER PRIMARY KEY AUTOINCREMENT,"
        " topic      TEXT NOT NULL,"
        " keyword    TEXT NOT NULL,"
        " chat       TEXT NOT NULL DEFAULT '',"
        " state      TEXT NOT NULL DEFAULT 'queued',"
        " created_at REAL NOT NULL,"
        " started_at REAL,"
        " ended_at   REAL,"
        " ticket     INTEGER,"
        " result     TEXT NOT NULL DEFAULT '',"
        " note       TEXT NOT NULL DEFAULT '',"
        " options    TEXT NOT NULL DEFAULT '{}')")
    conn.execute("CREATE INDEX IF NOT EXISTS job_open ON job(state, id)")
    _local.conn = conn
    return conn


def _topic_key(topic: str) -> str:
    key = str(topic or "").strip().lower()
    if key not in TOPICS:
        raise JobError(
            f"ไม่รู้จักหัวข้อ '{topic}' — ที่รับอยู่: {' · '.join(sorted(TOPICS))}")
    return key


def submit(topic: str, keyword: str, chat: str = "", **options) -> int:
    """หย่อนคำสั่งค้นหาลงกล่อง — คืนเลขใบงาน"""
    key = _topic_key(topic)
    word = str(keyword or "").strip()
    if not word:
        raise JobError("ต้องบอกคำที่จะค้นหา")
    conn = connect()
    dup = conn.execute(
        "SELECT id FROM job WHERE topic=? AND keyword=? AND state IN (?,?)",
        (key, word, QUEUED, RUNNING)).fetchone()
    if dup:
        raise JobError(
            f"คำนี้อยู่ในกล่องแล้ว (ใบที่ {dup['id']}) — ยิงซ้ำคือเสียเวลาจอเปล่าๆ")
    cur = conn.execute(
        "INSERT INTO job(topic,keyword,chat,state,created_at,options) VALUES(?,?,?,?,?,?)",
        (key, word, str(chat or ""), QUEUED, time.time(),
         json.dumps(options, ensure_ascii=False)))
    return int(cur.lastrowid)


def claim_next(worker: str) -> dict | None:
    """หยิบใบถัดไปตามลำดับที่หย่อนเข้ามา — คืน None ถ้ากล่องว่าง

    ใช้ธุรกรรมเดียวกันทั้งอ่านและจอง ไม่งั้นพนักงานสองคน (ถ้าวันหนึ่งมีสอง)
    จะหยิบใบเดียวกันไปทำพร้อมกัน
    """
    conn = connect()
    for _ in range(40):
        try:
            conn.execute("BEGIN IMMEDIATE")
        except sqlite3.OperationalError:
            time.sleep(0.25)
            continue
        try:
            row = conn.execute(
                "SELECT * FROM job WHERE state=? ORDER BY id LIMIT 1", (QUEUED,)).fetchone()
            if row is None:
                conn.execute("COMMIT")
                return None
            conn.execute("UPDATE job SET state=?, started_at=?, note=? WHERE id=?",
                         (RUNNING, time.time(), f"พนักงาน: {worker}", row["id"]))
            conn.execute("COMMIT")
            return dict(row)
        except Exception:
            with contextlib.suppress(Exception):
                conn.execute("ROLLBACK")
            raise
    raise JobError("กล่องงานถูกล็อกนานผิดปกติ — มีอะไรค้างอยู่ ต้องไปดู")


def finish(job_id: int, state: str = DONE, note: str = "", result: str = "") -> None:
    if state not in (DONE, FAILED, ATTENTION, CANCELLED):
        raise JobError(f"สถานะปิดใบงานไม่ถูกต้อง: {state}")
    connect().execute(
        "UPDATE job SET state=?, ended_at=?, note=?, result=? WHERE id=?",
        (state, time.time(), str(note or ""), str(result or ""), int(job_id)))


def get(job_id: int) -> dict:
    row = connect().execute("SELECT * FROM job WHERE id=?", (int(job_id),)).fetchone()
    if row is None:
        raise JobError(f"ไม่มีใบงานที่ {job_id}")
    return dict(row)


def reset_stuck(worker: str = "") -> int:
    """ใบที่ค้างสถานะ 'กำลังทำ' ตอนพนักงานเกิดใหม่ = รอบก่อนตายกลางทาง

    คืนเข้ากล่องให้ทำใหม่ ไม่ใช่ทิ้ง — และไม่ใช่ปล่อยค้าง เพราะใบที่ค้าง
    'กำลังทำ' จะไม่มีใครหยิบไปทำอีกเลยตลอดกาล (บทเรียนเดียวกับรายการรันค้าง
    ของตัวเก็บโพสต์ที่เปิดค้าง 49 ชั่วโมงเมื่อ 21 ส.ค. 2569)
    """
    cur = connect().execute(
        "UPDATE job SET state=?, started_at=NULL, note=? WHERE state=?",
        (QUEUED, f"คืนเข้ากล่องตอน {worker or 'พนักงาน'} เกิดใหม่ (รอบก่อนตายกลางทาง)",
         RUNNING))
    return cur.rowcount or 0


def board() -> dict:
    conn = connect()
    rows = [dict(r) for r in conn.execute(
        "SELECT * FROM job WHERE state IN (?,?) ORDER BY id", OPEN_STATES)]
    attention = [dict(r) for r in conn.execute(
        "SELECT * FROM job WHERE state=? ORDER BY id DESC LIMIT 20", (ATTENTION,))]
    return {
        "running": next((r for r in rows if r["state"] == RUNNING), None),
        "queued": [r for r in rows if r["state"] == QUEUED],
        "attention": attention,
    }


def history(topic: str = "", limit: int = 20) -> list[dict]:
    conn = connect()
    if topic:
        rows = conn.execute(
            "SELECT * FROM job WHERE topic=? AND state NOT IN (?,?) ORDER BY id DESC LIMIT ?",
            (_topic_key(topic), QUEUED, RUNNING, int(limit)))
    else:
        rows = conn.execute(
            "SELECT * FROM job WHERE state NOT IN (?,?) ORDER BY id DESC LIMIT ?",
            (QUEUED, RUNNING, int(limit)))
    return [dict(r) for r in rows]


def _ago(seconds: float) -> str:
    seconds = max(0.0, seconds)
    if seconds < 60:
        return f"{seconds:.0f} วิ"
    if seconds < 3600:
        return f"{seconds / 60:.0f} นาที"
    return f"{seconds / 3600:.1f} ชม."


def print_board() -> None:
    data = board()
    now = time.time()
    run = data["running"]
    print("📦 กล่องคำสั่งค้นหา")
    if run:
        print(f"   กำลังทำ : [{TOPICS[run['topic']]}] {run['keyword']}"
              f"  · สั่งโดย {run['chat'] or '—'}"
              f"  ({_ago(now - (run['started_at'] or run['created_at']))})  ใบ #{run['id']}")
    else:
        print("   กำลังทำ : — ว่าง")
    if data["queued"]:
        for i, row in enumerate(data["queued"], 1):
            print(f"   คิวที่ {i} : [{TOPICS[row['topic']]}] {row['keyword']}"
                  f"  · สั่งโดย {row['chat'] or '—'}"
                  f"  (รอมา {_ago(now - row['created_at'])})  ใบ #{row['id']}")
    else:
        print("   คิวถัดไป: ไม่มีงานรอ")
    if data["attention"]:
        print("\n🚨 รอคนตัดสิน — พนักงานทำต่อเองไม่ได้")
        for row in data["attention"]:
            print(f"   ใบ #{row['id']} [{TOPICS[row['topic']]}] {row['keyword']} — {row['note']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="คลังคำสั่งค้นหาสินค้า")
    sub = parser.add_subparsers(dest="cmd")

    one = sub.add_parser("add", help="หย่อนคำสั่งค้นหาลงกล่อง")
    one.add_argument("topic", help=" · ".join(sorted(TOPICS)))
    one.add_argument("keyword")
    one.add_argument("--chat", default="")

    sub.add_parser("board", help="ใครกำลังทำ ใครรอ ใครติดปัญหา")

    one = sub.add_parser("show", help="ดูใบงานหนึ่งใบ")
    one.add_argument("job_id", type=int)

    one = sub.add_parser("drop", help="ยกเลิกใบงาน")
    one.add_argument("job_id", type=int)

    one = sub.add_parser("history", help="ที่ทำไปแล้ว")
    one.add_argument("--topic", default="")
    one.add_argument("--limit", type=int, default=20)

    args = parser.parse_args(argv)
    cmd = args.cmd or "board"
    if cmd == "add":
        job_id = submit(args.topic, args.keyword, args.chat)
        waiting = len(board()["queued"])
        print(f"📥 รับเรื่องแล้ว ใบที่ {job_id} · มีงานรออยู่ {waiting} ใบ")
    elif cmd == "board":
        print_board()
    elif cmd == "show":
        row = get(args.job_id)
        for key, value in row.items():
            print(f"  {key:11s} = {value}")
    elif cmd == "drop":
        finish(args.job_id, CANCELLED, "เจ้าของสั่งยกเลิก")
        print(f"🗑 ยกเลิกใบที่ {args.job_id} แล้ว")
    elif cmd == "history":
        for row in history(args.topic, args.limit):
            print(f"  #{row['id']:<5} {row['state']:<10} [{row['topic']:<11}] "
                  f"{row['keyword'][:30]:<30} {row['note'][:40]}")
    return 0


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        with contextlib.suppress(Exception):
            _stream.reconfigure(encoding="utf-8")
    raise SystemExit(main())
