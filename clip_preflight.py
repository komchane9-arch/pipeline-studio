"""ด่านตรวจก่อนเริ่มงานสายคลิป — ต่อยอดจาก `fb_preflight` ไม่ใช่สร้างซ้ำ

**แบ่งงานกับ `fb_preflight` ยังไง**

    fb_preflight    ฝั่งมือถือ — ADB · เครื่องว่าง · เนื้อที่ · คีย์บอร์ด · โพสต์ซ้ำกลุ่ม
    clip_preflight  ฝั่งคอม   — ล็อกอินครบไหม · เครดิตพอไหม · ล็อกค้างไหม

ไฟล์นี้ใช้ `Check` / `Report` / `check_pc_space` ของ `fb_preflight` ตรงๆ เพื่อให้
ผลตรวจของทั้งสองสายหน้าตาเหมือนกัน **และจะไม่แก้เนื้อในไฟล์นั้นเลย**

⚠️ ไฟล์นี้ไม่แตะ ADB แม้แต่คำสั่งเดียว — ด่านมือถือทั้งหมดเป็นของ `fb_preflight`

---

**ตรวจล็อกอินยังไงโดยไม่ต้องเปิดเบราว์เซอร์**

เปิด Chrome มาตรวจแพงมาก (ต้องยึด `browser_lock` · รอหน้าโหลด · เสี่ยงไปไล่งานอื่น
ที่ใช้โปรไฟล์เดียวกันออก) ทั้งที่คำถามคือแค่ "เคยล็อกอินไว้ไหม"

หลักฐานที่ถูกกว่ามาก: **ชื่อคุกกี้ในโปรไฟล์** — Chrome เข้ารหัสเฉพาะ *ค่า* ของ
คุกกี้ ส่วน *ชื่อ* กับ *วันหมดอายุ* เก็บเป็นข้อความธรรมดา อ่านได้โดยไม่ต้องถอดรหัส
อะไรเลย ไฟล์นี้จึงอ่านแค่ `host_key` · `name` · `expires_utc` **ไม่แตะคอลัมน์ค่า**

ยืนยันกับโปรไฟล์จริงแล้ว (14 ส.ค. 2026) — เห็นความต่างชัดมาก:

    labs.google      __Secure-next-auth.session-token       ← ล็อกอิน Flow แล้ว
    .shopee.co.th    SPC_ST · SPC_U                         ← ล็อกอิน Shopee แล้ว
    .chatgpt.com     __Secure-next-auth.session-token.0/.1  ← ล็อกอิน ChatGPT แล้ว
    .tiktok.com      msToken · ttwid · odin_tt · tt_chain_token
                     └─ ทั้งหมดเป็นคุกกี้ "ผู้เยี่ยมชม" ไม่มี sessionid เลย
                        = **ยังไม่ได้ล็อกอิน TikTok** ตรงกับหน้า Log in wall ที่เจอ

**ข้อจำกัดที่ต้องพูดให้ชัด** (กติกาข้อ 2.3 — ตัวตรวจที่บอกว่าผ่านทั้งที่ยังไม่ผ่าน
อันตรายกว่าไม่มีตัวตรวจ)

    ไม่มีคุกกี้ session   = **พิสูจน์ได้ว่ายังไม่ได้ล็อกอิน**  → ห้ามเริ่ม
    มีแต่หมดอายุแล้ว      = **พิสูจน์ได้ว่าใช้ไม่ได้แล้ว**     → ห้ามเริ่ม
    มีและยังไม่หมดอายุ    = เคยล็อกอินไว้ **แต่ไม่ได้แปลว่าเซิร์ฟเวอร์ยังรับ**
                            (ถูกเตะออกจากอีกเครื่องก็ยังเห็นคุกกี้อยู่) → ผ่านแบบมีข้อแม้

ด่านนี้จึงจับ "ยังไม่เคยล็อกอิน" ได้ 100% ซึ่งคือเคสที่กัดเราจริง — โปรไฟล์ไม่เคย
ล็อกอิน TikTok แล้วไปตายตอนกำลังจะโพสต์ หลังจ่ายค่าเจนคลิปไปหมดแล้ว
"""

from __future__ import annotations

import os
import re
import shutil
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import cost_ledger
import studio_shared
from fb_preflight import Check, PreflightError, Report, check_pc_space

# โปรไฟล์เบราว์เซอร์ที่งานอัตโนมัติทุกตัวใช้ร่วมกัน
BROWSER_PROFILE = studio_shared.DATA_DIR / "flow_browser_profile"
COOKIE_RELATIVE = Path("Default") / "Network" / "Cookies"

# Chrome นับเวลาเป็นไมโครวินาทีตั้งแต่ 1601-01-01 (UTC) ไม่ใช่ Unix epoch
CHROME_EPOCH = datetime(1601, 1, 1)

# ถือล็อกนานเกินเท่านี้ = น่าสงสัยว่าค้าง (ซอมบี้แบบ 14 ส.ค. 2026 ถือไว้ 7 ชม.)
STALE_HOLD_MINUTES = 90

# เครดิตต่อฉากตอนที่ยังไม่มีข้อมูลจริงในสมุดบัญชี — **ค่าสมมติ ไม่ใช่ค่าที่วัดมา**
# พอสมุดบัญชีมีข้อมูลจริงครบ 3 ฉากขึ้นไป `cost_ledger.typical_scene_cost()`
# จะเข้ามาแทนที่เอง
ASSUMED_SCENE_COST = 100

# คุกกี้ที่บอกว่า "เคยล็อกอินไว้" — เทียบแบบขึ้นต้นด้วย เพราะ next-auth ตัด
# โทเคนยาวเป็นหลายใบต่อท้ายด้วย .0 .1
SITES: dict[str, dict] = {
    "flow": {
        "label": "Google Flow",
        "markers": (("labs.google", "__Secure-next-auth.session-token"),),
        "how": "python flow_worker.py login",
    },
    "tiktok": {
        "label": "TikTok",
        "markers": ((".tiktok.com", "sessionid"), (".tiktok.com", "sid_tt")),
        "how": "python flow_worker.py login-tiktok",
    },
    "shopee": {
        "label": "Shopee",
        "markers": ((".shopee.co.th", "SPC_ST"), (".shopee.co.th", "SPC_U")),
        "how": "python flow_worker.py login-shopee",
    },
    "chatgpt": {
        "label": "ChatGPT",
        "markers": ((".chatgpt.com", "__Secure-next-auth.session-token"),),
        "how": "python flow_worker.py login-chatgpt",
    },
}


# ------------------------------------------------------------ อ่านคุกกี้

class CookieUnavailable(RuntimeError):
    """อ่านตารางคุกกี้ของโปรไฟล์ไม่ได้"""


def read_cookie_index(profile: Path | None = None) -> dict[tuple[str, str], datetime | None]:
    """คืน {(โฮสต์, ชื่อคุกกี้): วันหมดอายุ} — **ไม่อ่านค่าคุกกี้เลย**

    ต้องคัดลอกไฟล์ออกมาก่อนอ่าน เพราะถ้า Chrome เปิดโปรไฟล์นี้อยู่ ไฟล์จะถูกล็อก
    การคัดลอกเป็นการอ่านอย่างเดียว ไม่กระทบงานที่กำลังรัน (กติกาข้อ 2.5)

    `expires_utc = 0` แปลว่าเป็นคุกกี้ที่ตายเมื่อปิดเบราว์เซอร์ — คืน None
    """
    root = profile or BROWSER_PROFILE
    source = root / COOKIE_RELATIVE
    if not source.is_file():
        raise CookieUnavailable(
            f"ไม่เจอไฟล์คุกกี้ของโปรไฟล์ ({source}) — โปรไฟล์นี้อาจยังไม่เคยถูกใช้"
        )

    handle, temp_name = tempfile.mkstemp(prefix="preflight-ck-", suffix=".sqlite")
    temp_path = Path(temp_name)
    try:
        os.close(handle)
        shutil.copy2(source, temp_path)
        connection = sqlite3.connect(str(temp_path))
        try:
            rows = connection.execute(
                "SELECT host_key, name, expires_utc FROM cookies"
            ).fetchall()
        finally:
            connection.close()
    except (OSError, sqlite3.Error) as error:
        raise CookieUnavailable(f"อ่านตารางคุกกี้ไม่ได้ ({error})") from error
    finally:
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            pass

    index: dict[tuple[str, str], datetime | None] = {}
    for host, name, expires in rows:
        when = None
        if expires:
            try:
                when = CHROME_EPOCH + timedelta(microseconds=int(expires))
            except (ValueError, OverflowError):
                when = None
        index[(str(host), str(name))] = when
    return index


def _match(index: dict, host: str, prefix: str) -> list[tuple[str, datetime | None]]:
    """หาคุกกี้ที่โฮสต์ตรงและชื่อขึ้นต้นด้วย prefix"""
    return [(name, when) for (h, name), when in index.items()
            if h == host and name.startswith(prefix)]


# ------------------------------------------------------------------ ด่านย่อย

def check_login(site: str, index: dict | None = None,
                now: datetime | None = None) -> Check:
    """เว็บนี้เคยล็อกอินไว้ในโปรไฟล์ไหม และคุกกี้ยังไม่หมดอายุใช่ไหม"""
    spec = SITES.get(site)
    if spec is None:
        return Check(f"ล็อกอิน {site}", False, "ไม่รู้จักเว็บนี้", blocking=False)
    label = spec["label"]

    if index is None:
        try:
            index = read_cookie_index()
        except CookieUnavailable as error:
            # อ่านไม่ได้ ≠ ไม่ได้ล็อกอิน — ห้ามฟันธงแทนกัน แต่ต้องดังพอให้เห็น
            return Check(f"ล็อกอิน {label}", False, str(error), blocking=False)

    now = now or datetime.utcnow()
    found: list[tuple[str, datetime | None]] = []
    for host, prefix in spec["markers"]:
        found.extend(_match(index, host, prefix))

    if not found:
        return Check(f"ล็อกอิน {label}", False,
                     f"ไม่มีคุกกี้ session เลย = ยังไม่ได้ล็อกอิน → สั่ง `{spec['how']}`")

    alive = [(n, w) for n, w in found if w is None or w > now]
    if not alive:
        newest = max((w for _, w in found if w), default=None)
        stamp = f" (หมดอายุ {newest:%d/%m/%Y})" if newest else ""
        return Check(f"ล็อกอิน {label}", False,
                     f"คุกกี้ session หมดอายุแล้ว{stamp} → สั่ง `{spec['how']}`")

    expiries = [w for _, w in alive if w]
    if expiries:
        soonest = min(expiries)
        left = (soonest - now).days
        detail = f"เคยล็อกอินไว้ · คุกกี้เหลืออีก {left} วัน"
        if left <= 3:
            return Check(f"ล็อกอิน {label}", False,
                         f"{detail} — ใกล้หมดอายุ ควรล็อกอินใหม่", blocking=False)
    else:
        detail = "เคยล็อกอินไว้ · คุกกี้ไม่มีวันหมดอายุกำกับ"
    return Check(f"ล็อกอิน {label}", True, detail)


def check_credits(scenes: int, per_scene: float | None = None,
                  stale_days: int = 7) -> Check:
    """เครดิต Flow ที่จดไว้ล่าสุดพอเจน `scenes` ฉากไหม

    อ่านจากสมุดบัญชี **ไม่เปิดเบราว์เซอร์** — เร็วและไม่ไปแย่ง `browser_lock`
    แลกกับการที่ค่าเป็นของ ณ เวลาที่จด จึงต้องบอกอายุของตัวเลขไว้เสมอ
    ไม่งั้นกลายเป็นตัวตรวจที่ให้ความมั่นใจผิดๆ
    """
    if scenes <= 0:
        return Check("เครดิต Flow", True, "งานนี้ไม่ต้องใช้เครดิต", blocking=False)

    balance, at = cost_ledger.latest_credits()
    if balance is None:
        return Check(
            "เครดิต Flow", False,
            "ยังไม่เคยบันทึกเครดิตคงเหลือ — ตรวจไม่ได้ "
            "(จะตรวจได้เองเมื่อสายเจนคลิปเริ่มจดลงสมุดบัญชี)",
            blocking=False,
        )

    if per_scene is None:
        measured = cost_ledger.typical_scene_cost()
        per_scene = measured if measured is not None else ASSUMED_SCENE_COST
        source = "จากที่วัดได้จริง" if measured is not None else "ค่าสมมติ ยังไม่มีข้อมูลจริง"
    else:
        source = "ค่าที่ผู้เรียกกำหนด"

    need = scenes * per_scene
    try:
        when = datetime.fromisoformat(at) if at else None
    except ValueError:
        when = None
    age_days = (datetime.now() - when).days if when else None
    age_text = "" if age_days is None else f" · ตัวเลขอายุ {age_days} วัน"

    if balance < need:
        return Check("เครดิต Flow", False,
                     f"เหลือ {balance:,.0f} แต่ {scenes} ฉากต้องใช้ราว {need:,.0f} "
                     f"({per_scene:,.0f}/ฉาก — {source}){age_text}")

    if age_days is not None and age_days > stale_days:
        return Check("เครดิต Flow", False,
                     f"เหลือ {balance:,.0f} (พอสำหรับ {scenes} ฉาก) แต่ตัวเลขเก่าไป "
                     f"{age_days} วัน — อาจไม่ตรงกับของจริงแล้ว", blocking=False)

    return Check("เครดิต Flow", True,
                 f"เหลือ {balance:,.0f} · ต้องใช้ราว {need:,.0f}{age_text}")


def _pid_alive(pid: int) -> bool | None:
    """โปรเซสนี้ยังอยู่ไหม — คืน None ถ้าตอบไม่ได้

    ⚠️ **ห้ามใช้ `os.kill(pid, 0)` บน Windows** ต่างจากบน POSIX ตรงที่มันไม่ได้
    แปลว่า "ถามเฉยๆ" — Python บน Windows แปลงเป็น `TerminateProcess` ซึ่งจะ
    **ฆ่าโปรเซสนั้นจริงๆ** ตัวตรวจสุขภาพที่ฆ่าสิ่งที่มันไปตรวจคือหายนะเงียบ
    """
    try:
        import psutil
    except ImportError:
        return None
    try:
        return psutil.pid_exists(pid)
    except Exception:
        return None


def check_stale_locks(now: datetime | None = None) -> Check:
    """มีป้ายบอกผู้ถือล็อกค้างอยู่ไหม — **เตือนอย่างเดียว ไม่ห้ามงาน**

    แยกสองอาการที่หน้าตาเหมือนกันแต่คนละเรื่อง:

      1. **PID ตายแล้วแต่ป้ายค้าง** — ล็อกจริงว่างแล้ว (ล็อกของ OS ปล่อยเองเมื่อ
         โปรเซสตาย) แต่ `who_holds_*` จะไปบอกผู้ใช้ว่า "ถูกงานอื่นใช้อยู่"
         ทำให้ไล่ปัญหาผิดทาง — ป้ายค้างเพราะ `finally` ไม่ได้ทำงานตอนโปรเซสตายห้วน

      2. **PID ยังอยู่แต่ถือมานานผิดปกติ** — อาการซอมบี้แบบ 14 ส.ค. 2026
         (PID 23560 ชีพจรค้าง 7 ชม. แต่ยังถือล็อก จน supervisor ปลุกตัวใหม่ไม่ได้)
         อันนี้ล็อกถูกถือจริง ต้องมีคนไปดู

    ห้ามทำเป็นด่านที่บล็อกงาน เพราะงานเจนคลิปที่ยาวเป็นชั่วโมงก็ถือล็อกนานได้
    โดยสุจริต — บล็อกไปจะไปห้ามงานที่ปกติดี
    """
    now = now or datetime.now()
    lock_dir = studio_shared.LOCK_DIR
    if not lock_dir.is_dir():
        return Check("ล็อกค้าง", True, "ยังไม่มีล็อกอยู่เลย")

    dead: list[str] = []
    long_held: list[str] = []
    total = 0
    for info in sorted(lock_dir.glob("*.info")):
        total += 1
        try:
            text = info.read_text(encoding="utf-8").strip()
            age = (now - datetime.fromtimestamp(info.stat().st_mtime)).total_seconds() / 60
        except OSError:
            continue
        found = re.search(r"PID\s+(\d+)", text)
        pid = int(found.group(1)) if found else None
        name = info.stem
        if pid is not None and _pid_alive(pid) is False:
            dead.append(f"{name} (PID {pid} ตายแล้ว)")
        elif age > STALE_HOLD_MINUTES:
            long_held.append(f"{name} ถือมา {age / 60:.1f} ชม.")

    if not total:
        return Check("ล็อกค้าง", True, "ไม่มีงานถือล็อกอยู่")
    if dead:
        return Check("ล็อกค้าง", False,
                     "ป้ายบอกผู้ถือค้างอยู่ " + " · ".join(dead[:3]) +
                     " — ล็อกจริงว่างแล้ว แต่ข้อความแจ้งผู้ใช้จะผิด", blocking=False)
    if long_held:
        return Check("ล็อกค้าง", False,
                     "ถือล็อกนานผิดปกติ " + " · ".join(long_held[:3]) +
                     " — เช็คว่าค้างหรือกำลังทำงานจริง", blocking=False)
    return Check("ล็อกค้าง", True, f"{total} รายการ ปกติทั้งหมด")


# --------------------------------------------------------------- ตัวรวมทั้งหมด

def run_checks(*, need=("flow",), scenes: int = 0, per_scene: float | None = None,
               profile: Path | None = None, now: datetime | None = None) -> Report:
    """ตรวจทุกข้อของสายคลิป — ไม่โยน exception ผู้เรียกตัดสินใจเอง

    `need` = รายชื่อเว็บที่งานนี้ต้องใช้ เช่น `("flow", "tiktok")` สำหรับงาน
    repost ที่ต้องเจนคลิปแล้วโพสต์ต่อ
    """
    report = Report()

    index = None
    if need:
        try:
            index = read_cookie_index(profile)
        except CookieUnavailable as error:
            report.checks.append(Check("โปรไฟล์เบราว์เซอร์", False, str(error)))
    for site in need:
        report.checks.append(check_login(site, index))

    report.checks.append(check_pc_space())
    if scenes:
        report.checks.append(check_credits(scenes, per_scene))
    report.checks.append(check_stale_locks(now=now))
    return report


def guard(*, what: str = "งานนี้", **kwargs) -> Report:
    """ตรวจแล้วโยน `PreflightError` ถ้าไม่ผ่านข้อที่ห้ามเริ่ม

    ใช้ `PreflightError` ตัวเดียวกับ `fb_preflight` เพื่อให้ผู้เรียกดักที่เดียวจบ
    """
    report = run_checks(**kwargs)
    if not report.ok:
        raise PreflightError(f"{what} เริ่มไม่ได้ — {report.reason()}")
    return report


# --------------------------------------------------------------------- CLI

def _cli(argv: list[str]) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    sites = [a for a in argv if a in SITES] or list(SITES)
    scenes = next((int(a) for a in argv if a.isdigit()), 0)
    report = run_checks(need=sites, scenes=scenes)
    print(report.text().replace("<b>", "").replace("</b>", ""))
    print()
    print(f"สรุป: {'เริ่มงานได้' if report.ok else 'ยังเริ่มไม่ได้'}"
          f" · ห้าม {len(report.failures)} · เตือน {len(report.warnings)}")
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(_cli(sys.argv[1:]))
