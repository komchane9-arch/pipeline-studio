"""ที่กดบัตรคิวของมือถือ — ทุกคนที่จะแตะจอต้องกดบัตรก่อนเสมอ

**ปัญหาที่แก้** มือถือหนึ่งเครื่องมีจอเดียว แต่ตอนนี้มีสามโปรเจกต์ที่สั่งมันได้
พร้อมกันโดยไม่รู้จักกัน (วัดจริง 21 ส.ค. 2569):

    7.web app          พอร์ต 8765  ล็อกของตัวเอง กันได้แค่ในโปรเซสตัวเอง
    8.pipeline studio  พอร์ต 8866  มี phone_lock() แต่มีแค่ 5 ไฟล์จาก 13 ที่ยอมใช้
    12.เก็บข้อมูล        สคริปต์ตรง  เขียน SER = '7a95129e' ตายตัว ไม่ขอล็อกเลย

วิธีกันชนที่ใช้อยู่คือ **เดาตารางเวลา** — `12/tools/hourly_scheduler.py` หยุดก่อน
ต้นชั่วโมง 3 นาที แล้วเว้นหลังต้นชั่วโมง 35 นาที เพื่อหลบบอท Facebook ซึ่งพลาดมาแล้ว:
16 ส.ค. 69 รอเงียบไปราว 10 ชั่วโมงเพราะบอทค้างจอไว้ที่ Facebook ทั้งคืน

**ของเดิมกันไม่พอตรงไหน** `studio_shared.phone_lock()` กันการแตะพร้อมกันได้จริง
แต่มันเป็น "ใครคว้าได้คว้าไป" — ไม่มีลำดับ ไม่มีชื่อคนรอ ไม่มีใครเห็นว่าใครรออยู่กี่คน
เจ้าของสั่ง 21 ส.ค. 2569 ว่าต้อง **มาก่อนได้ก่อน (FIFO)** และต้องเห็นลำดับชัดเจน

**หลักที่ยึด**

1. **มาก่อนได้ก่อน** เรียงตามเลขบัตรล้วน ไม่มีใครแซง (ยกเว้นเจ้าของสั่งยกเลิกเอง)
2. **หนึ่งเครื่องมีคนทำได้ทีละคน** แต่คนละเครื่องทำขนานกันได้เต็มที่ (กติกาข้อ 8)
3. **ต้องบอก serial เสมอ** ใส่ค่าว่างไม่ได้ — ถ้าปล่อยให้ไม่ใส่ได้ คนที่ลืมใส่จะไป
   ต่อคิวคนละแถวกับคนที่ใส่ แล้วสองงานแตะจอเครื่องเดียวกันโดยไม่มีใครกัน
4. **คนถือบัตรต้องเต้นชีพจร** หายไปเกิน STALE_SECONDS = ตัดบัตรทิ้ง เรียกคิวถัดไป
   (21 ส.ค. เจอของจริง: การจองที่ค้างโดยไม่มีคนทำ ทำให้งานหยุดยาว 9 ชั่วโมง)
5. **ทุกโปรเจกต์ใช้เล่มเดียวกัน** ฐานคิวอยู่ที่พาธสัมบูรณ์ของโปรเจกต์ 8 เสมอ
   ไม่ว่าใครจะ import จากที่ไหน — สองเล่มคือไม่มีเล่มเลย

**วิธีใช้จากโค้ด**

    import phone_queue as pq

    with pq.slot("7a95129e", owner="แชท shopee", task="ค้นหา หูฟังบลูทูธ",
                 lane="scalp") as ticket:
        ...งานที่แตะจอ...          # ออกจาก with = คืนคิวให้คนถัดไปทันที

**วิธีใช้จากบรรทัดคำสั่ง**

    python phone_queue.py board                  ใครทำอยู่ · ใครรอ · รอมานานเท่าไร
    python phone_queue.py take 7a95129e --owner "แชท lazada" --task "ค้นหา ..."
    python phone_queue.py done 12 --note "เก็บได้ 30 ชิ้น"
    python phone_queue.py drop 12                ยกเลิกบัตรใบนั้น
"""

from __future__ import annotations

import argparse
import contextlib
import os
import socket
import sqlite3
import sys
import threading
import time
from pathlib import Path

# ---------------------------------------------------------------- ที่อยู่ของฐาน
#
# **ต้องเป็นพาธสัมบูรณ์ที่คิดจากที่อยู่ของไฟล์นี้เอง** ไม่ใช่จาก cwd — โปรเจกต์ 12
# รันสคริปต์จากโฟลเดอร์ตัวเอง ถ้าคิดจาก cwd มันจะไปสร้างฐานคิวเล่มที่สองของตัวเอง
# แล้วต่างคนต่างต่อคิวคนละแถว = เท่ากับไม่มีคิว
BASE_DIR = Path(__file__).resolve().parent
_data_name = os.environ.get("STUDIO_DATA_DIR", "data").strip() or "data"
DATA_DIR = Path(_data_name) if Path(_data_name).is_absolute() else BASE_DIR / _data_name
DB_PATH = DATA_DIR / "phone_queue.db"

# **คนกำลังทำ กับ คนยืนรอ ต้องคนละเกณฑ์** — เจอตอนเทสรอบแรก (21 ส.ค. 2569)
# ถ้าใช้เกณฑ์เดียวกัน คนยืนรอที่ยังไม่ได้เริ่มเต้นชีพจรจะโดนตัดทิ้งไปด้วยทั้งแถว
#   · คนกำลังทำหายไป = บล็อกทุกคน ต้องตัดเร็ว
#   · คนยืนรอหายไป   = ไม่ได้ขวางใคร แค่กินที่ในแถว ให้เวลาเยอะได้
STALE_RUNNING = 90.0        # กำลังทำอยู่แล้วเงียบเกินนี้ = ตัดทิ้ง เรียกคิวถัดไป
STALE_WAITING = 600.0       # ยืนรออยู่แล้วเงียบเกินนี้ = ถือว่าเลิกรอแล้ว
BEAT_SECONDS = 15.0         # ตัวถือบัตรเต้นชีพจรถี่แค่ไหน
POLL_SECONDS = 1.0          # รอคิวแล้วถามซ้ำทุกกี่วิ (เสร็จปุ๊บคนถัดไปเข้าใน ~1 วิ)

WAITING, RUNNING = "waiting", "running"
DONE, FAILED, GONE, CANCELLED = "done", "failed", "gone", "cancelled"
OPEN_STATES = (WAITING, RUNNING)


class QueueError(RuntimeError):
    """คิวปฏิเสธคำขอ — ต้องดังเสมอ ห้ามคืนค่าว่างเงียบๆ"""


# ---------------------------------------------------------------- ด่านกันลืม
#
# **ทำไมต้องมีสองชั้น** ชั้นแรกคือ slot() ที่ครอบงานทั้งชิ้น (โพสต์หนึ่งกลุ่ม ·
# เก็บหนึ่งร้าน · ค้นหาหนึ่งคำ) ส่วนชั้นนี้คือกันคนเขียนโค้ดใหม่ลืมครอบ
#
# ถ้ากันแค่ชั้นเดียวจะเจอปัญหาเดิมซ้ำ: 21 ส.ค. 2569 นับได้ว่ามี 13 ไฟล์ที่สั่ง ADB
# ได้ แต่มีแค่ 5 ไฟล์ที่ยอมเรียก phone_lock() — ไม่ใช่เพราะใครดื้อ แต่เพราะไม่มี
# อะไรบอกเลยว่าลืม โค้ดที่ลืมทำงานได้ปกติทุกประการจนกว่าจะไปชนกับคนอื่นเข้า
#
# ตั้ง PHONE_QUEUE_ENFORCE=0 = โหมดจดอย่างเดียว (ด่าน 2 ของแผน) ใช้ตอนเพิ่งแปลง
# ระบบเสร็จใหม่ๆ เพื่อดูว่ามีจุดไหนตกหล่นก่อนจะบังคับจริง
ENFORCE = os.environ.get("PHONE_QUEUE_ENFORCE", "1").strip() != "0"
BYPASS_LOG = DATA_DIR / "logs" / "phone_bypass.log"

_held: dict[str, int] = {}
_held_lock = threading.Lock()


def default_owner() -> str:
    """ชื่อที่จะขึ้นบนกระดานถ้าคนเรียกไม่ได้บอกมา

    ตั้ง PHONE_QUEUE_OWNER ให้ตรงกับชื่อแชท/งานเสมอ — ชื่อที่อ่านไม่รู้เรื่อง
    บนกระดานเท่ากับไม่มีกระดาน คนดูต้องตอบได้ทันทีว่า "ใครถือจออยู่"
    """
    named = os.environ.get("PHONE_QUEUE_OWNER", "").strip()
    if named:
        return named
    script = Path(sys.argv[0]).stem if sys.argv and sys.argv[0] else "ไม่ทราบชื่องาน"
    return f"{script} (pid {os.getpid()})"


def device_for_lane(lane: str) -> str:
    """เครื่องที่รับงานสายนี้ — ไม่ชัดเจนต้องล้มเสียงดัง ห้ามเดาเด็ดขาด

    ตามกติกาข้อ 8 ของโปรเจกต์: "โพสต์ลงบัญชีผิด" กู้คืนไม่ได้ ส่วน "งานไม่เริ่ม
    พร้อมเหตุผล" เสียแค่เวลากดใหม่ — เพราะงั้นถ้าตอบไม่ได้แน่ชัดว่าเครื่องไหน
    ต้องโยน error พร้อมบอกชื่อทุกเครื่องให้เลือก ไม่ใช่หยิบเครื่องแรกมาใช้
    """
    if str(BASE_DIR) not in sys.path:
        sys.path.insert(0, str(BASE_DIR))
    import devices                                              # noqa: PLC0415

    serials = devices.enabled_serials(lane)
    if not serials:
        raise QueueError(
            f"ยังไม่มีเครื่องไหนถูกตั้งให้รับงานสาย '{lane}' — "
            f"ตั้งด้วย  python devices.py lane <serial> {lane}\n"
            f"(เครื่องที่เปิดใช้อยู่ตอนนี้: "
            f"{', '.join(devices.enabled_serials()) or 'ไม่มีเลย'})")
    if len(serials) > 1:
        names = " · ".join(f"{devices.label(s)} [{s}]" for s in serials)
        raise QueueError(
            f"สาย '{lane}' มีเครื่องรับงานมากกว่าหนึ่งเครื่อง ต้องระบุมาให้ชัด: {names}")
    return serials[0]


def holding(serial: str) -> int | None:
    """โปรเซสนี้ถือบัตรของเครื่องนี้อยู่ไหม — คืนเลขบัตรถ้าถืออยู่"""
    with _held_lock:
        return _held.get(_device_key(serial))


def require_slot(serial: str, what: str = "") -> int | None:
    """เรียกก่อนยิง ADB ทุกครั้ง — ไม่มีบัตรในมือ = ผิดกติกา

    บังคับจริง (ENFORCE=1) จะโยน QueueError ตรงจุดที่ลืม ทำให้หาที่แก้ได้ใน
    5 วินาที ส่วนโหมดจดอย่างเดียวจะเขียนลง `data/logs/phone_bypass.log`
    แล้วปล่อยผ่าน — ใช้เฉพาะช่วงแปลงระบบ ไม่ใช่ค่าถาวร
    """
    key = _device_key(serial)
    ticket = holding(key)
    if ticket is not None:
        return ticket
    message = (f"ยิง ADB ใส่ {key} โดยไม่ได้กดบัตรคิว"
               + (f" — {what}" if what else ""))
    if ENFORCE:
        raise QueueError(
            message + "\nต้องครอบด้วย  with phone_queue.slot(serial, owner=..., task=...):"
                      "\n(ถ้ากำลังแปลงระบบอยู่ ตั้ง PHONE_QUEUE_ENFORCE=0 ชั่วคราวได้)")
    with contextlib.suppress(OSError):
        BYPASS_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(BYPASS_LOG, "a", encoding="utf-8") as handle:
            handle.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} pid={os.getpid()} {message}\n")
    return None


# ---------------------------------------------------------------- ฐานข้อมูล
_local = threading.local()


def connect() -> sqlite3.Connection:
    """เปิดฐานคิว — หนึ่งการเชื่อมต่อต่อหนึ่งเธรด

    ใช้ WAL เพื่อให้คนอ่านกระดาน (หน้าเว็บ/CLI) ไม่ไปบล็อกคนที่กำลังเขียนคิว
    busy_timeout 15 วิ เพราะสามโปรเจกต์เขียนไฟล์เดียวกัน ชนกันได้จริง
    """
    conn = getattr(_local, "conn", None)
    if conn is not None:
        return conn
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=15.0, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=15000")
    _ensure_schema(conn)
    _local.conn = conn
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS ticket("
        " id         INTEGER PRIMARY KEY AUTOINCREMENT,"
        " device     TEXT NOT NULL,"
        " owner      TEXT NOT NULL,"
        " task       TEXT NOT NULL DEFAULT '',"
        " lane       TEXT NOT NULL DEFAULT '',"
        " state      TEXT NOT NULL DEFAULT 'waiting',"
        " created_at REAL NOT NULL,"
        " started_at REAL,"
        " ended_at   REAL,"
        " beat_at    REAL NOT NULL,"
        " note       TEXT NOT NULL DEFAULT '',"
        " pid        INTEGER,"
        " host       TEXT NOT NULL DEFAULT '')")
    conn.execute("CREATE INDEX IF NOT EXISTS ticket_open ON ticket(device, state, id)")


# ---------------------------------------------------------------- ตัวช่วย
def _device_key(serial: str) -> str:
    """serial ต้องมีจริง — ว่างเปล่าคือคิวคนละแถวโดยไม่มีใครรู้ตัว"""
    key = str(serial or "").strip()
    if not key:
        raise QueueError("phone_queue ต้องระบุ serial ของมือถือ — ห้ามเว้นว่าง")
    return key


def _now() -> float:
    return time.time()


def _sweep(conn: sqlite3.Connection, device: str) -> int:
    """ตัดบัตรของคนที่หายไปแล้วทิ้ง — คืนจำนวนใบที่ตัด

    ทั้งคนที่กำลังทำและคนที่ยืนรอต้องเต้นชีพจร ถ้าหยุดเต้นแปลว่าแชทถูกปิด
    เครื่องรีบูต หรือสคริปต์ตาย — ปล่อยไว้คือทั้งแถวค้างตลอดกาล
    (21 ส.ค. 2569 เจอของจริงในระบบเก็บโพสต์: การจองที่ค้างโดยไม่มีคนทำ
    ทำให้กลุ่มหนึ่งถูกล็อกไว้ 9 ชั่วโมงโดยไม่มีใครทำงานเลย)

    **คนละเกณฑ์กัน** ดูคำอธิบายที่ STALE_RUNNING / STALE_WAITING
    """
    now = _now()
    cur = conn.execute(
        "UPDATE ticket SET state=?, ended_at=?, note=CASE WHEN note='' THEN "
        "'คนถือบัตรหายไป — ระบบตัดให้อัตโนมัติ' ELSE note END "
        "WHERE device=? AND ("
        "  (state=? AND beat_at < ?) OR (state=? AND beat_at < ?))",
        (GONE, now, device,
         RUNNING, now - STALE_RUNNING,
         WAITING, now - STALE_WAITING))
    return cur.rowcount or 0


def _promote(conn: sqlite3.Connection, device: str) -> None:
    """ถ้าเคาน์เตอร์ว่าง เรียกคิวถัดไปเข้าทันที — เรียงตามเลขบัตรล้วน"""
    busy = conn.execute(
        "SELECT id FROM ticket WHERE device=? AND state=? LIMIT 1",
        (device, RUNNING)).fetchone()
    if busy:
        return
    nxt = conn.execute(
        "SELECT id FROM ticket WHERE device=? AND state=? ORDER BY id LIMIT 1",
        (device, WAITING)).fetchone()
    if nxt:
        conn.execute("UPDATE ticket SET state=?, started_at=? WHERE id=?",
                     (RUNNING, _now(), nxt["id"]))


def _settle(conn: sqlite3.Connection, device: str) -> None:
    """เก็บกวาด + เรียกคิว ในธุรกรรมเดียว — กันสองโปรเซสเลื่อนคิวพร้อมกัน"""
    for _ in range(40):
        try:
            conn.execute("BEGIN IMMEDIATE")
        except sqlite3.OperationalError:
            time.sleep(0.25)
            continue
        try:
            _sweep(conn, device)
            _promote(conn, device)
            conn.execute("COMMIT")
            return
        except Exception:
            with contextlib.suppress(Exception):
                conn.execute("ROLLBACK")
            raise
    raise QueueError("ฐานคิวถูกล็อกนานผิดปกติ — มีอะไรค้างอยู่ ต้องไปดู")


# ---------------------------------------------------------------- คำสั่งหลัก
def take(device: str, owner: str, task: str = "", lane: str = "") -> int:
    """กดบัตรเข้าคิว — คืนเลขบัตร (ยังไม่ได้แปลว่าถึงคิวแล้ว)

    ห้ามคนเดิมถือสองใบบนเครื่องเดียวกัน — คนที่ถืออยู่แล้วไปต่อท้ายแถวตัวเอง
    คือรอตัวเองตลอดกาล (เดดล็อกที่หาสาเหตุยากที่สุดแบบหนึ่ง)
    """
    key = _device_key(device)
    who = str(owner or "").strip()
    if not who:
        raise QueueError("ต้องบอกว่าใครขอคิว — ไม่งั้นกระดานอ่านไม่รู้เรื่อง")
    conn = connect()
    _settle(conn, key)
    dup = conn.execute(
        "SELECT id, state FROM ticket WHERE device=? AND owner=? AND state IN (?,?)",
        (key, who, WAITING, RUNNING)).fetchone()
    if dup:
        raise QueueError(
            f"{who} ถือบัตรใบที่ {dup['id']} ของเครื่องนี้อยู่แล้ว ({dup['state']}) — "
            "ต้องคืนใบเดิมก่อนถึงจะกดใหม่ได้")
    now = _now()
    cur = conn.execute(
        "INSERT INTO ticket(device,owner,task,lane,state,created_at,beat_at,pid,host) "
        "VALUES(?,?,?,?,?,?,?,?,?)",
        (key, who, str(task or ""), str(lane or ""), WAITING, now, now,
         os.getpid(), socket.gethostname()))
    ticket = int(cur.lastrowid)
    _settle(conn, key)
    return ticket


def beat(ticket: int) -> None:
    """บอกว่ายังอยู่ — ต้องเรียกทั้งตอนรอคิวและตอนกำลังทำงาน"""
    connect().execute("UPDATE ticket SET beat_at=? WHERE id=? AND state IN (?,?)",
                      (_now(), int(ticket), WAITING, RUNNING))


def status(ticket: int) -> dict:
    row = connect().execute("SELECT * FROM ticket WHERE id=?", (int(ticket),)).fetchone()
    if row is None:
        raise QueueError(f"ไม่มีบัตรใบที่ {ticket}")
    return dict(row)


def position(ticket: int) -> int:
    """ยืนอยู่ลำดับที่เท่าไร — 0 = ถึงคิวแล้ว · -1 = บัตรปิดไปแล้ว"""
    row = status(ticket)
    if row["state"] == RUNNING:
        return 0
    if row["state"] != WAITING:
        return -1
    ahead = connect().execute(
        "SELECT COUNT(*) FROM ticket WHERE device=? AND state=? AND id<?",
        (row["device"], WAITING, int(ticket))).fetchone()[0]
    return int(ahead) + 1


def wait_turn(ticket: int, timeout: float = 1800.0, on_wait=None) -> bool:
    """ยืนรอจนถึงคิวตัวเอง — คืน True เมื่อถึงคิว

    ระหว่างรอจะเต้นชีพจรให้เอง ถ้าคนข้างหน้าหายไป ระบบจะตัดบัตรเขาแล้วเลื่อนคิว
    ให้เอง จึงไม่มีใครค้างแถวเพราะคนข้างหน้าปิดแชทหนี
    """
    tid = int(ticket)
    deadline = _now() + float(timeout)
    told = -2
    while _now() < deadline:
        beat(tid)
        row = status(tid)
        if row["state"] == RUNNING:
            return True
        if row["state"] != WAITING:
            raise QueueError(
                f"บัตรใบที่ {tid} ถูกปิดไปแล้ว ({row['state']}) — {row['note']}")
        _settle(connect(), row["device"])
        if on_wait is not None:
            here = position(tid)
            if here != told:
                told = here
                on_wait(here)
        time.sleep(POLL_SECONDS)
    finish(tid, CANCELLED, "รอเกินเวลาที่ตั้งไว้")
    return False


def finish(ticket: int, state: str = DONE, note: str = "") -> None:
    """คืนคิว — คนถัดไปเข้าทันทีในธุรกรรมเดียวกัน"""
    if state not in (DONE, FAILED, CANCELLED):
        raise QueueError(f"สถานะปิดบัตรไม่ถูกต้อง: {state}")
    conn = connect()
    row = conn.execute("SELECT device FROM ticket WHERE id=?", (int(ticket),)).fetchone()
    if row is None:
        raise QueueError(f"ไม่มีบัตรใบที่ {ticket}")
    conn.execute(
        "UPDATE ticket SET state=?, ended_at=?, note=? WHERE id=? AND state IN (?,?)",
        (state, _now(), str(note or ""), int(ticket), WAITING, RUNNING))
    _settle(conn, row["device"])


@contextlib.contextmanager
def slot(device: str, owner: str, task: str = "", lane: str = "",
         timeout: float = 1800.0, on_wait=None):
    """ทางที่ควรใช้ที่สุด — กดบัตร รอคิว ทำงาน คืนคิว ครบในบล็อกเดียว

    ชีพจรระหว่างทำงานเต้นให้เองด้วยเธรดเบื้องหลัง งานที่กินเวลาหลายนาที
    (เช่นโหลดรูปเป็นพันไฟล์) จึงไม่ถูกเข้าใจผิดว่าตายแล้ว
    """
    ticket = take(device, owner, task, lane)
    stop = threading.Event()

    def _pump() -> None:
        while not stop.wait(BEAT_SECONDS):
            with contextlib.suppress(Exception):
                beat(ticket)

    try:
        got = wait_turn(ticket, timeout=timeout, on_wait=on_wait)
    except BaseException:
        with contextlib.suppress(Exception):
            finish(ticket, CANCELLED, "ยกเลิกระหว่างรอคิว")
        raise
    if not got:
        raise QueueError(f"รอคิวเครื่อง {device} เกิน {timeout:.0f} วินาทีแล้วยังไม่ถึง")

    pump = threading.Thread(target=_pump, daemon=True)
    pump.start()
    key = _device_key(device)
    with _held_lock:
        previous = _held.get(key)          # กันเคสซ้อนบัตรในโปรเซสเดียว
        _held[key] = ticket
    try:
        yield ticket
    except BaseException as error:
        stop.set()
        finish(ticket, FAILED, f"{type(error).__name__}: {error}"[:300])
        raise
    else:
        stop.set()
        finish(ticket, DONE)
    finally:
        with _held_lock:
            if previous is None:
                _held.pop(key, None)
            else:
                _held[key] = previous


# ---------------------------------------------------------------- กระดาน
def board(device: str = "") -> list[dict]:
    """ทุกเคาน์เตอร์ที่มีคิวอยู่ — ใครทำอยู่ · ใครรอ · รอมานานเท่าไร"""
    conn = connect()
    if device:
        devices_seen = [_device_key(device)]
    else:
        devices_seen = [r["device"] for r in conn.execute(
            "SELECT DISTINCT device FROM ticket WHERE state IN (?,?)", OPEN_STATES)]
    out = []
    for dev in sorted(devices_seen):
        _settle(conn, dev)
        rows = [dict(r) for r in conn.execute(
            "SELECT * FROM ticket WHERE device=? AND state IN (?,?) ORDER BY id",
            (dev, WAITING, RUNNING))]
        running = next((r for r in rows if r["state"] == RUNNING), None)
        out.append({
            "device": dev,
            "running": running,
            "waiting": [r for r in rows if r["state"] == WAITING],
        })
    return out


def history(device: str = "", limit: int = 15) -> list[dict]:
    conn = connect()
    if device:
        rows = conn.execute(
            "SELECT * FROM ticket WHERE device=? AND state NOT IN (?,?) "
            "ORDER BY id DESC LIMIT ?",
            (_device_key(device), WAITING, RUNNING, int(limit)))
    else:
        rows = conn.execute(
            "SELECT * FROM ticket WHERE state NOT IN (?,?) ORDER BY id DESC LIMIT ?",
            (WAITING, RUNNING, int(limit)))
    return [dict(r) for r in rows]


def _label(serial: str) -> str:
    """ชื่อที่คนอ่านรู้เรื่อง — ไม่มีทะเบียนก็ใช้ serial ไปตรงๆ ไม่ต้องพัง"""
    try:
        if str(BASE_DIR) not in sys.path:
            sys.path.insert(0, str(BASE_DIR))
        import devices                                        # noqa: PLC0415
        name = devices.label(serial)
        return f"{name} ({serial})" if name and name != serial else serial
    except Exception:                                          # noqa: BLE001
        return serial


def _ago(seconds: float) -> str:
    seconds = max(0.0, seconds)
    if seconds < 60:
        return f"{seconds:.0f} วิ"
    if seconds < 3600:
        return f"{seconds / 60:.0f} นาที"
    return f"{seconds / 3600:.1f} ชม."


def print_board(device: str = "") -> None:
    groups = board(device)
    if not groups:
        print("🟢 ไม่มีใครเข้าคิวมือถือเครื่องไหนเลย")
        return
    now = _now()
    for group in groups:
        print(f"\n📱 {_label(group['device'])}")
        run = group["running"]
        if run:
            since = run["started_at"] or run["created_at"]
            print(f"   กำลังทำ : {run['owner']} — {run['task'] or 'ไม่ได้บอกว่าทำอะไร'}"
                  f"  ({_ago(now - since)})  บัตร #{run['id']}")
        else:
            print("   กำลังทำ : — ว่าง")
        if group["waiting"]:
            for i, row in enumerate(group["waiting"], 1):
                print(f"   คิวที่ {i} : {row['owner']} — {row['task'] or '—'}"
                      f"  (รอมา {_ago(now - row['created_at'])})  บัตร #{row['id']}")
        else:
            print("   คิวถัดไป: ไม่มีใครรอ")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ที่กดบัตรคิวของมือถือ")
    sub = parser.add_subparsers(dest="cmd")

    one = sub.add_parser("board", help="ใครทำอยู่ ใครรอ")
    one.add_argument("--device", default="")

    one = sub.add_parser("take", help="กดบัตรเข้าคิว")
    one.add_argument("device")
    one.add_argument("--owner", required=True)
    one.add_argument("--task", default="")
    one.add_argument("--lane", default="")
    one.add_argument("--wait", type=float, default=0.0, help="รอจนถึงคิวกี่วินาที")

    one = sub.add_parser("done", help="คืนคิว")
    one.add_argument("ticket", type=int)
    one.add_argument("--note", default="")

    one = sub.add_parser("drop", help="ยกเลิกบัตร")
    one.add_argument("ticket", type=int)
    one.add_argument("--note", default="เจ้าของสั่งยกเลิก")

    one = sub.add_parser("history", help="ที่ทำไปแล้วล่าสุด")
    one.add_argument("--device", default="")
    one.add_argument("--limit", type=int, default=15)

    args = parser.parse_args(argv)
    cmd = args.cmd or "board"

    if cmd == "board":
        print_board(getattr(args, "device", ""))
    elif cmd == "take":
        ticket = take(args.device, args.owner, args.task, args.lane)
        print(f"🎫 บัตรใบที่ {ticket} · ลำดับที่ {position(ticket)}")
        if args.wait > 0:
            ok = wait_turn(ticket, timeout=args.wait,
                           on_wait=lambda n: print(f"   ยังรออยู่ ลำดับที่ {n}", flush=True))
            print("✅ ถึงคิวแล้ว" if ok else "⌛ รอเกินเวลา ยกเลิกบัตรแล้ว")
            return 0 if ok else 1
    elif cmd == "done":
        finish(args.ticket, DONE, args.note)
        print(f"✅ คืนบัตรใบที่ {args.ticket} แล้ว")
    elif cmd == "drop":
        finish(args.ticket, CANCELLED, args.note)
        print(f"🗑 ยกเลิกบัตรใบที่ {args.ticket} แล้ว")
    elif cmd == "history":
        for row in history(args.device, args.limit):
            print(f"  #{row['id']:<5} {row['state']:<9} {row['owner']:<22} {row['task'][:40]}")
    return 0


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        with contextlib.suppress(Exception):
            _stream.reconfigure(encoding="utf-8")
    raise SystemExit(main())
