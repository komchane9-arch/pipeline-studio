"""ตัวเฝ้าสายมือถือ — ต่อคืนให้เองเมื่อหลุด และร้องเสียงดังเมื่อต่อคืนเองไม่ได้

ทำไมต้องมี
==========

**ก่อนหน้านี้ระบบไม่มีตัวต่อคืนเลยสักตัว** ตรวจจริง 26 ส.ค. 2569:
ค้นทั้งโปรเจกต์ด้วย `grep -rl "adb reconnect|tcpip|adb connect" *.py` ได้ **0 ไฟล์**
มือถือหลุดเมื่อไรจึงค้างอยู่อย่างนั้นจนกว่าคนจะมาเห็นเอง ซึ่งอาจเป็นวันถัดไป

สาเหตุการหลุดที่วัดได้จริงบนเครื่องนี้ (26 ส.ค. 2569 18:38)

* ฮับ USB 8 ตัว (`ROOT_HUB30` + Genesys `VID_05E3` อีก 7) ตั้งไว้ว่า
  **Windows ปิดได้เพื่อประหยัดไฟ** ฮับหลับเมื่อไร มือถือทุกเครื่องใต้ฮับนั้น
  หลุดพร้อมกัน ต่อให้ตัวมือถือเองตั้ง "ห้ามปิด" ไว้แล้วก็ตาม
  (ตัวมือถือทั้งสอง REDMI ตั้ง `AllowPowerOff=False` ไว้ถูกแล้ว แต่ไม่ช่วย
  เพราะไฟถูกตัดที่ฮับข้างบน) — แก้ต้องใช้สิทธิ์ผู้ดูแล ดู `hub_report()`
* ค่าพักพอร์ต USB ในแผนพลังงานปิดอยู่แล้ว (ตรวจแล้ว ไม่ใช่สาเหตุ)

เรื่อง "ต้องกดอนุญาต ADB ใหม่"
==============================

มือถือจำ **กุญแจของคอมเครื่องนี้** ไว้ในตัวเอง (`/data/misc/adb/adb_keys`)
ตอนกด "อนุญาตเสมอ" ตราบใดที่ไฟล์ `~/.android/adbkey` ฝั่งคอมยังอยู่ครบ
มือถือจะไม่ถามอีกเลย **แม้จะรีบูต ถอดสาย หรือ `adb kill-server` ก็ตาม**

ตัวที่ทำให้ต้องกดใหม่ทั้งหมดพร้อมกันมีอย่างเดียว คือกุญแจฝั่งคอมหาย
จึงสำรองไว้แล้วที่ `data/adb-key-backup/` (ดู `key_ok()` ที่คอยตรวจให้ทุกครั้ง)

สิ่งที่ตัวเฝ้านี้ทำได้และทำไม่ได้
=================================

| อาการ | ทำอะไร |
|---|---|
| `offline` | `adb reconnect` เฉพาะเครื่องนั้น |
| หายไปเลย | ต่อคืนทาง Wi-Fi ถ้าเคยเปิดช่องไว้ |
| หายหมดทุกเครื่องนานเกิน 5 นาที | รีสตาร์ตตัวกลาง ADB (กุญแจไม่หาย) |
| `unauthorized` | **ต่อคืนเองไม่ได้** ต้องมีคนกดที่จอ → ร้องดังทันที |

Wi-Fi เป็นทางสำรองเท่านั้น — งานจริงต้องออกเน็ตมือถือ
=====================================================

**เจ้าของสั่งไว้ 26 ส.ค. 2569** — *"ให้ใช้ wifi ในกรณีสำรองเท่านั้นนะ
รันจริงจะใช้แค่ cellular"*

เหตุผล: ถ้าทุกเครื่องออกเน็ตจาก IP บ้านเดียวกัน = มัดบัญชี Facebook
เข้าหากันเอง ซึ่งกู้คืนไม่ได้ถ้าโดนตีธง เน็ตมือถือให้เส้นทางแยกคนละบัญชี

ตัวเฝ้านี้จึงถูกออกแบบให้

1. **ห้ามเปิด Wi-Fi ให้เครื่องที่ปิดอยู่เด็ดขาด** ไม่มีโค้ดสั่ง `svc wifi enable`
   ที่ไหนเลย เครื่องไหนปิด Wi-Fi อยู่จะไม่มีช่องสำรอง และนั่นถูกต้องแล้ว
2. เปิดช่อง Wi-Fi ADB ให้เฉพาะเครื่องที่ **เปิด Wi-Fi อยู่แล้วเอง** เท่านั้น
   (`wifi_is_primary()` เป็นด่านตรวจ)
3. การเปิดช่อง ADB ไม่เปลี่ยนเส้นทางเน็ตของแอปเลย — มันแค่เปิดพอร์ตให้คอมต่อเข้ามา
   แอปยังออกเน็ตทางเดิมทุกประการ
4. **ต่อ Wi-Fi ก็ต่อเมื่อสายหายไปแล้วจริงๆ** (หายติดกัน 2 รอบ = 1 นาที)
   และตัดทิ้งทันทีที่สายกลับมา (`drop_wifi_twins()`)

การแบ่งเส้นทางเน็ตที่ถูกต้อง — เจ้าของยืนยันเอง 26 ส.ค. 2569
==========================================================

    Xiaomi 7a95129e        Wi-Fi        ← ถูกแล้ว ห้ามสลับไป LTE
    REDMI  DATCW8GQUOCUWK9P  LTE        ← ถูกแล้ว ห้ามเปิด Wi-Fi
    REDMI  W4FYYPYTLFYLIFHM  LTE        ← ถูกแล้ว ห้ามเปิด Wi-Fi

**อย่าเห็นว่า Xiaomi ใช้ Wi-Fi แล้วคิดว่าตั้งค่าผิด** มันตั้งใจให้เป็นแบบนี้
เครื่องที่อยู่บน Wi-Fi จึงเป็นเครื่องเดียวที่มีช่องสำรอง ADB ได้ ส่วนสองเครื่อง
ที่ใช้ LTE ต้องพึ่งสาย USB อย่างเดียวโดยตั้งใจ — แลกกับการมีเส้นทางเน็ต
แยกคนละบัญชี ซึ่งสำคัญกว่าความสะดวกในการต่อคืน

ใช้ยังไง
========

    python phone_watch.py board     ดูสถานะทุกเครื่องตอนนี้
    python phone_watch.py once      ตรวจ+ซ่อม 1 รอบแล้วออก
    python phone_watch.py run       เฝ้าไปเรื่อยๆ (app.py เรียกตัวนี้ให้เอง)
    python phone_watch.py hub       ดูว่าฮับ USB ตัวไหนยัง Windows ปิดได้
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(__file__).resolve().parent / "data"
LOG_FILE = DATA_DIR / "logs" / "phone_watch.log"
STATE_FILE = DATA_DIR / "phone_watch.json"
KEY_BACKUP = DATA_DIR / "adb-key-backup"

GAP = 30.0                  # ตรวจทุกกี่วินาที
WIFI_PORT = 5555            # พอร์ตช่อง Wi-Fi ADB
MISSING_BEFORE_WIFI = 2     # หายกี่รอบก่อนลองต่อทาง Wi-Fi
ALL_GONE_BEFORE_RESTART = 10   # หายหมดกี่รอบก่อนรีสตาร์ตตัวกลาง ADB (10 * 30 วิ = 5 นาที)

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


# ---------------------------------------------------------------- พื้นฐาน

def adb_path() -> str:
    """หา adb.exe แบบเดียวกับ app.py — ตัวที่เราคุมได้มาก่อน PATH เสมอ

    บทเรียนเดิม: PATH เคยมี adb เก่าค้างแล้วสั่งมือถือไม่ได้
    """
    for candidate in (
        BASE_DIR / "tools/platform-tools/adb.exe",
        Path("C:/project/2.Auto gen Video/7.web app/tools/platform-tools/adb.exe"),
        Path.home() / "AppData/Local/Android/Sdk/platform-tools/adb.exe",
        Path("C:/platform-tools/adb.exe"),
    ):
        if candidate.is_file():
            return str(candidate)
    found = shutil.which("adb")
    if found:
        return found
    raise RuntimeError("ไม่พบ adb.exe")


ADB = adb_path()


def _run(*args: str, timeout: float = 20.0) -> str:
    try:
        done = subprocess.run(                          # noqa: S603
            [ADB, *args], capture_output=True, text=True, errors="replace",
            timeout=timeout, creationflags=NO_WINDOW,
        )
        return ((done.stdout or "") + (done.stderr or "")).strip()
    except Exception as error:                          # noqa: BLE001
        return f"__error__ {error}"


def log(text: str) -> None:
    """เขียนลงไฟล์เสมอ ไม่ใช่ส่งเข้าแชทอย่างเดียว (กติกาโปรเจกต์ข้อ 2.4)"""
    line = f"{time.strftime('%d/%m %H:%M:%S')} {text}"
    print(line, flush=True)
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with LOG_FILE.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except Exception:                                   # noqa: BLE001, S110
        pass


def _state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:                                   # noqa: BLE001
        return {}


def _save_state(data: dict) -> None:
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                              encoding="utf-8")
    except Exception:                                   # noqa: BLE001, S110
        pass


# ---------------------------------------------------------------- อ่านสถานะ

def states() -> dict[str, str]:
    """serial -> สถานะ ('device' / 'offline' / 'unauthorized' / …)

    อ่านจาก `adb devices` ตรงๆ ไม่ผ่านตัวกลางอื่น เพราะนี่คือความจริงชั้นล่างสุด
    """
    out = _run("devices")
    found: dict[str, str] = {}
    for line in out.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2 and not parts[0].startswith("*"):
            found[parts[0]] = parts[1]
    return found


def key_ok() -> tuple[bool, str]:
    """กุญแจฝั่งคอมยังอยู่ครบไหม — ตัวเดียวที่ทำให้ต้องกดอนุญาตใหม่ทั้งยวง"""
    live = Path.home() / ".android" / "adbkey"
    backup = KEY_BACKUP / "adbkey"
    if not live.is_file():
        if backup.is_file():
            return False, ("กุญแจ ADB ของคอมหายไป! กู้คืนได้จาก "
                           f"{backup} แล้วสั่ง adb kill-server")
        return False, "กุญแจ ADB ของคอมหายไป และไม่มีไฟล์สำรอง"
    if not backup.is_file():
        return True, "กุญแจอยู่ครบ แต่ยังไม่ได้สำรอง — ควรสำรองไว้"
    if live.read_bytes() == backup.read_bytes():
        return True, "กุญแจอยู่ครบและตรงกับไฟล์สำรอง"
    return True, "กุญแจอยู่ครบ แต่ไฟล์สำรองเป็นคนละใบ — ควรสำรองใหม่"


def wifi_is_primary(serial: str) -> str:
    """คืน IP ถ้าเครื่องนี้ **ใช้ Wi-Fi เป็นทางออกเน็ตหลักอยู่แล้ว** ไม่งั้นคืนค่าว่าง

    เงื่อนไขเข้มแบบนี้ตั้งใจ — เครื่องที่ใช้เน็ตมือถือห้ามไปเปิด Wi-Fi ให้
    เพราะจะทำให้ทุกเครื่องออกเน็ตจาก IP บ้านเดียวกัน = มัดบัญชีเข้าหากันเอง
    """
    out = _run("-s", serial, "shell", "dumpsys connectivity", timeout=25)
    if "__error__" in out:
        return ""
    head = ""
    for line in out.splitlines():
        if "NetworkAgentInfo" in line and "CONNECTED" in line:
            head = line
            break
    if not head or "Transports: WIFI" not in head:
        return ""
    for word in head.replace(",", " ").replace("[", " ").replace("]", " ").split():
        if word.count(".") == 3 and word.split("/")[0].replace(".", "").isdigit():
            return word.split("/")[0]
    return ""


# ---------------------------------------------------------------- ซ่อม

def arm_wifi(serial: str) -> str:
    """เปิดช่อง Wi-Fi ADB ไว้เป็นทางสำรอง — คืนที่อยู่ที่ต่อได้ หรือค่าว่าง

    ทำได้เฉพาะตอนสายยังเสียบอยู่ เพราะต้องสั่งผ่านสายก่อน
    ช่องนี้หายเมื่อมือถือรีบูต ตัวเฝ้าจึงเปิดซ้ำให้ทุกครั้งที่เห็นเครื่องกลับมา
    """
    ip = wifi_is_primary(serial)
    if not ip:
        return ""
    out = _run("-s", serial, "tcpip", str(WIFI_PORT), timeout=25)
    if "__error__" in out or "error" in out.lower():
        return ""
    time.sleep(2.0)
    return f"{ip}:{WIFI_PORT}"


def drop_wifi_twins(now: dict[str, str] | None = None) -> list[str]:
    """ตัดช่อง Wi-Fi ทิ้งเมื่อสายยังเสียบอยู่ — **กันเครื่องเดียวขึ้นสองรายการ**

    ทดสอบจริง 26 ส.ค. 2569: พอต่อ Wi-Fi ทั้งที่สายยังเสียบ ทะเบียนขึ้นเป็น
    **4 เครื่อง** ทั้งที่มีจริง 3 — ตัวปลอมคือ `192.168.1.110:5555`
    (โชคดีที่ทะเบียนปิดเครื่องใหม่ไว้ก่อนเสมอตามกติกาข้อ 8 จึงไม่มีงานยิงใส่
    แต่ปล่อยไว้ไม่ได้ เพราะคนอ่านกระดานจะนับเครื่องผิด และถ้าวันหนึ่งมีใคร
    เผลอเปิดใช้ จะกลายเป็นโพสต์ซ้ำสองรอบจากเครื่องเดียวกัน)

    ช่อง Wi-Fi ยัง **เปิดค้างอยู่ที่ตัวมือถือ** ต่อกลับได้ทันทีเมื่อสายหลุด
    การตัดตรงนี้คือตัดแค่ "การเชื่อมต่อ" ไม่ใช่ปิดช่อง
    """
    import devices as device_book                       # noqa: PLC0415

    now = states() if now is None else now
    wired = {s for s, st in now.items() if ":" not in s and st == "device"}
    if not wired:
        return []                       # ไม่มีสายเลย = ช่อง Wi-Fi คือทางเดียว ห้ามตัด

    dropped = []
    for serial, state in list(now.items()):
        if ":" not in serial or state != "device":
            continue
        model = _run("-s", serial, "shell", "getprop ro.serialno",
                     timeout=15).strip()
        if model and model in wired:
            _run("disconnect", serial, timeout=15)
            with __import__("contextlib").suppress(Exception):
                device_book.remove(serial)
            dropped.append(serial)
            log(f"🧹 ตัดช่อง Wi-Fi {serial} ทิ้ง เพราะสายของเครื่องเดียวกัน "
                f"({model}) ยังเสียบอยู่ — กันไม่ให้ขึ้นซ้ำสองรายการ")
    return dropped


def heal_once(*, verbose: bool = True) -> list[str]:
    """ตรวจ+ซ่อม 1 รอบ — คืนรายการสิ่งที่ทำไป (ว่าง = ทุกอย่างปกติ)"""
    import devices as device_book                       # noqa: PLC0415

    saved = _state()
    now = states()
    if drop_wifi_twins(now):
        now = states()
    acted: list[str] = []
    wanted = [d["serial"] for d in device_book.listing() if d.get("enabled")]
    if not wanted:
        wanted = list(now)

    healthy = 0
    for serial in wanted:
        row = saved.setdefault(serial, {})
        was = row.get("state", "")
        state = now.get(serial, "missing")
        name = device_book.label(serial)

        if state == "device":
            healthy += 1
            row["missing_rounds"] = 0
            if was and was != "device":
                acted.append(f"{name} กลับมาต่อติดแล้ว")
                log(f"✅ {name} ({serial}) กลับมาต่อติดแล้ว จากสถานะ {was}")
            # เปิดช่อง Wi-Fi สำรองไว้ทุกครั้งที่เห็นเครื่อง (ช่องหายตอนรีบูต)
            if not row.get("wifi") or was != "device":
                where = arm_wifi(serial)
                if where and where != row.get("wifi"):
                    row["wifi"] = where
                    log(f"📶 {name} เปิดช่องสำรองทาง Wi-Fi ไว้ที่ {where}")

        elif state == "unauthorized":
            row["missing_rounds"] = 0
            if was != "unauthorized":
                acted.append(f"{name} รอกดอนุญาตที่จอ")
                log(f"🛑 {name} ({serial}) ขึ้น unauthorized — "
                    f"**ต่อคืนเองไม่ได้** ต้องปลดล็อกจอแล้วกด "
                    f"'อนุญาตเสมอจากคอมเครื่องนี้'")

        elif state == "offline":
            row["missing_rounds"] = 0
            log(f"⚠️ {name} ({serial}) ขึ้น offline — สั่งต่อคืน")
            _run("reconnect", "offline", timeout=20)
            time.sleep(1.5)
            acted.append(f"{name} สั่งต่อคืนแล้ว")

        else:   # หายไปเลย
            row["missing_rounds"] = int(row.get("missing_rounds", 0)) + 1
            if was == "device":
                log(f"🔌 {name} ({serial}) หลุดไปจากรายชื่อ")
            where = row.get("wifi", "")
            if where and row["missing_rounds"] >= MISSING_BEFORE_WIFI:
                out = _run("connect", where, timeout=20)
                if "connected" in out.lower():
                    acted.append(f"{name} ต่อคืนทาง Wi-Fi สำเร็จ")
                    log(f"📶 {name} ต่อคืนทาง Wi-Fi ที่ {where} สำเร็จ")

        row["state"] = state
        row["at"] = time.time()

    # ทุกเครื่องหายพร้อมกันนานๆ = ตัวกลาง ADB ฝั่งคอมค้าง ไม่ใช่มือถือมีปัญหา
    gone = saved.setdefault("__all__", {})
    if healthy == 0 and wanted:
        gone["rounds"] = int(gone.get("rounds", 0)) + 1
        if gone["rounds"] >= ALL_GONE_BEFORE_RESTART:
            gone["rounds"] = 0
            log("🔁 ไม่เห็นมือถือสักเครื่องนานเกิน 5 นาที — รีสตาร์ตตัวกลาง ADB "
                "(กุญแจอนุญาตไม่หาย ไม่ต้องกดใหม่)")
            _run("kill-server", timeout=20)
            time.sleep(2.0)
            _run("start-server", timeout=30)
            acted.append("รีสตาร์ตตัวกลาง ADB")
    else:
        gone["rounds"] = 0

    _save_state(saved)
    if verbose and not acted:
        ok, why = key_ok()
        if not ok:
            log(f"🛑 {why}")
    return acted


# ---------------------------------------------------------------- ฮับ USB

def hub_report() -> list[tuple[str, bool]]:
    """ฮับ USB ที่ Windows ยังปิดได้ — ปิดเมื่อไรมือถือใต้ฮับหลุดพร้อมกันหมด"""
    script = (
        "Get-WmiObject -Namespace root\\WMI -Class MSPower_DeviceEnable "
        "-ErrorAction SilentlyContinue | "
        "Where-Object { $_.InstanceName -match 'ROOT_HUB|VID_05E3' } | "
        "ForEach-Object { '{0}|{1}' -f $_.InstanceName, $_.Enable }"
    )
    try:
        done = subprocess.run(                          # noqa: S603
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, errors="replace", timeout=60,
            creationflags=NO_WINDOW,
        )
        out = done.stdout or ""
    except Exception:                                   # noqa: BLE001
        return []
    rows = []
    for line in out.splitlines():
        if "|" in line:
            name, enabled = line.rsplit("|", 1)
            rows.append((name.strip(), enabled.strip().lower() == "true"))
    return rows


# ---------------------------------------------------------------- แสดงผล

def board() -> str:
    import devices as device_book                       # noqa: PLC0415

    now = states()
    saved = _state()
    lines = ["📱 สายมือถือ"]
    for device in device_book.listing():
        serial = device["serial"]
        if not device.get("enabled"):
            continue
        state = now.get(serial, "missing")
        mark = {"device": "🟢 ต่อติด", "offline": "🟡 สายสะดุด",
                "unauthorized": "🛑 รอกดอนุญาตที่จอ"}.get(state, "🔴 หายไป")
        wifi = saved.get(serial, {}).get("wifi", "")
        tail = f" · ช่องสำรอง Wi-Fi {wifi}" if wifi else " · ไม่มีช่องสำรอง"
        lines.append(f"   {mark}  {device_book.label(serial)}")
        lines.append(f"      {serial}{tail}")

    ok, why = key_ok()
    lines.append("")
    lines.append(("🔑 " if ok else "🛑 ") + why)

    hubs = hub_report()
    risky = [n for n, on in hubs if on]
    if risky:
        lines.append(f"⚠️ ฮับ USB {len(risky)} ตัวยังถูก Windows ปิดได้เพื่อประหยัดไฟ "
                     f"— ฮับหลับเมื่อไรมือถือใต้ฮับหลุดพร้อมกัน")
        lines.append("   แก้ด้วยสิทธิ์ผู้ดูแล: python phone_watch.py hub --fix")
    elif hubs:
        lines.append(f"🔌 ฮับ USB {len(hubs)} ตัว ตั้งห้ามปิดไฟไว้ครบแล้ว")
    return "\n".join(lines)


def fix_hubs() -> str:
    """ปิดสิทธิ์ Windows ในการดับฮับ USB — **ต้องรันด้วยสิทธิ์ผู้ดูแล**"""
    script = (
        "Get-WmiObject -Namespace root\\WMI -Class MSPower_DeviceEnable "
        "-ErrorAction SilentlyContinue | "
        "Where-Object { $_.InstanceName -match 'ROOT_HUB|VID_05E3' -and $_.Enable } | "
        "ForEach-Object { "
        "  try { $_.Enable = $false; $_.Put() | Out-Null; "
        "        Write-Output ('DONE|' + $_.InstanceName) } "
        "  catch { Write-Output ('FAIL|' + $_.Exception.Message) } }"
    )
    try:
        done = subprocess.run(                          # noqa: S603
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, errors="replace", timeout=120,
            creationflags=NO_WINDOW,
        )
        out = done.stdout or ""
    except Exception as error:                          # noqa: BLE001
        return f"สั่งไม่สำเร็จ: {error}"
    good = [x[5:] for x in out.splitlines() if x.startswith("DONE|")]
    bad = [x[5:] for x in out.splitlines() if x.startswith("FAIL|")]
    if bad and not good:
        return ("แก้ไม่ได้ — ต้องเปิด PowerShell แบบ 'Run as administrator' "
                "แล้วสั่งใหม่\n   สาเหตุ: " + bad[0])
    return f"ปิดสิทธิ์ดับไฟให้ฮับแล้ว {len(good)} ตัว" + \
           (f" · ยังไม่ผ่าน {len(bad)} ตัว" if bad else "")


def run() -> None:
    log("เริ่มเฝ้าสายมือถือ — ตรวจทุก %.0f วินาที" % GAP)
    while True:
        try:
            heal_once()
        except Exception as error:                      # noqa: BLE001
            log(f"ตัวเฝ้าสายมือถือสะดุด: {error}")
        time.sleep(GAP)


if __name__ == "__main__":
    what = sys.argv[1] if len(sys.argv) > 1 else "board"
    if what == "board":
        print(board())
    elif what == "once":
        done = heal_once()
        print("\n".join(f"• {x}" for x in done) if done else "ทุกอย่างปกติ ไม่ต้องซ่อม")
        print()
        print(board())
    elif what == "run":
        run()
    elif what == "hub":
        if "--fix" in sys.argv:
            print(fix_hubs())
        else:
            for name, on in hub_report():
                print(("❌ Windows ปิดได้  " if on else "✅ ปิดไม่ได้      ") + name)
    else:
        print(__doc__)
