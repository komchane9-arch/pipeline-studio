"""ตัวจัดคิวการแก้ไฟล์ระหว่างแชท — จองก่อนแก้ ปล่อยเมื่อเสร็จ

**ปัญหาที่แก้** โปรเจกต์นี้มีหลายแชทแก้พร้อมกัน แล้วไม่มีใครรู้ว่าไฟล์ไหน
มีคนถืออยู่ ผลที่เกิดจริงในวันเดียว (14 ส.ค. 2026):

    · เวอร์ชันชนกัน 3 รอบ เพราะสองแชทแก้ไฟล์หน้าเว็บพร้อมกัน
    · แชทหนึ่งเขียน fb_auto_post.py ทับจน line ending เปลี่ยนทั้งไฟล์
    · แชทหลักจะแก้ app.py แต่ต้องหยุดรอ เพราะอีกแชทกำลังพิมพ์อยู่ —
      รู้ได้เพราะบังเอิญไปดู mtime ไม่ใช่เพราะมีระบบบอก

**นี่เป็นล็อกแบบ "ตกลงกันไว้" ไม่ใช่ล็อกที่บังคับได้**

แชทแต่ละตัวเป็นคนละโปรเซส ห้ามกันไม่ให้เรียกเครื่องมือแก้ไฟล์จริงๆ ไม่ได้
สิ่งที่ไฟล์นี้ทำคือ **ทำให้รู้ตัวก่อนชน** และทำให้การถามว่า "ใครถืออยู่"
ใช้เวลาแค่วินาทีเดียว จนไม่มีเหตุผลจะข้าม

ต่างจาก `studio_shared.browser_lock()` ตรงที่อันนั้นล็อกทรัพยากรของ **โปรเซส
ที่กำลังรัน** ระบบปฏิบัติการจึงปลดให้เองเมื่อโปรเซสตาย ส่วนอันนี้ผู้ถือคือ
"แชท" ซึ่งไม่ใช่โปรเซส จึงต้องมีวันหมดอายุเอง ไม่งั้นแชทที่ปิดไปจะล็อกไฟล์
ค้างตลอดกาล — บทเรียนเดียวกับที่ทำให้ browser_lock ต้องใช้ล็อกของ OS

**การจัดคิว** ถ้าไฟล์มีคนถืออยู่ ผู้ขอจะถูกต่อคิวไว้ พอคนแรกปล่อย
คิวถัดไปจะได้สิทธิ์อัตโนมัติ พร้อมข้อความสำเร็จรูปให้แชทที่ปล่อยส่งไปบอก
(ส่งเองไม่ได้เพราะเป็นสคริปต์ ไม่ใช่ตัวแชท — ตัวแชทต้องเป็นคนส่ง)

ใช้จากบรรทัดคำสั่ง:

    python file_claims.py status app.py
    python file_claims.py claim app.py --chat "webapp หลัก" --why "เพิ่มปุ่ม fb:cl"
    python file_claims.py release app.py --chat "webapp หลัก"
    python file_claims.py list
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

import studio_shared

# เครื่องมือนี้ถูกเรียกมือจากหน้าจอเป็นหลัก จึงเจอ stdout ที่ไม่ใช่คอนโซลบ่อย
# แล้ว Python จะใช้ cp1252 ทำให้ print ภาษาไทยพังทั้งโปรเซส (เจอจริง 2 ครั้ง
# ในวันเดียวกับ clip_app.py) — กันไว้เหมือนที่ fb_mass_finder ทำ
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

BASE_DIR = Path(__file__).resolve().parent
CLAIMS_FILE = studio_shared.DATA_DIR / "file_claims.json"

# ถือได้นานสุดกี่นาทีก่อนหมดอายุเอง
#
# ยาวพอสำหรับงานแก้จริงหนึ่งก้อน แต่ไม่ยาวจนแชทที่ปิดไปแล้วล็อกไฟล์ค้างทั้งวัน
# ต่ออายุได้ด้วยการ claim ซ้ำ — งานที่ยาวกว่านี้ควรต่ออายุเป็นระยะอยู่แล้ว
HOLD_MINUTES = 45

# คิวถัดไปได้สิทธิ์แล้วแต่ยังไม่เริ่ม ให้เวลาเท่านี้ก่อนปล่อยให้คนอื่น
#
# สั้นกว่าปกติมากโดยตั้งใจ: แชทที่ได้คิวอาจไม่ได้เปิดอยู่ ถ้าให้เต็ม 45 นาที
# คนที่พร้อมทำจริงจะถูกบล็อกฟรีๆ
GRACE_MINUTES = 10

# แตะไฟล์ครั้งล่าสุดภายในกี่นาที ถึงจะนับว่า "ยังทำอยู่จริง" แล้วต่ออายุให้เอง
#
# **จำเป็นจริง ไม่ใช่เผื่อไว้** — เจอกับตัวเองรอบแรกที่ใช้เครื่องมือนี้:
# จองไว้ 4 ไฟล์ตอน 17:48 งานยาวถึง 23:08 การจองหมดอายุกลางทางโดยคนถือไม่รู้ตัว
# ถ้าช่วงนั้นมีแชทอื่นมาขอ จะได้ไฟล์ไปทั้งที่อีกฝั่งกำลังแก้ค้างอยู่
#
# ใช้ "ไฟล์ถูกแตะจริง" เป็นตัวตัดสินแทนการเชื่อนาฬิกา เพราะเป็นหลักฐานว่ายังทำอยู่
# ไม่ใช่แค่ลืมปล่อย — คนที่ทิ้งไปแล้วไฟล์จะไม่ขยับ แล้วหมดอายุตามปกติ
ACTIVE_MINUTES = 25

# เตือนล่วงหน้าเมื่อเหลือน้อยกว่านี้ — เห็นตอนรันคำสั่งอะไรก็ได้
WARN_MINUTES = 12

HISTORY_LIMIT = 60


class ClaimError(RuntimeError):
    """จองไฟล์ไม่ได้"""


def _now() -> datetime:
    return datetime.now()


def _stamp(when: datetime) -> str:
    return when.isoformat(timespec="seconds")


def _parse(text: str) -> datetime | None:
    try:
        return datetime.fromisoformat(str(text))
    except (TypeError, ValueError):
        return None


def _ago(when: datetime | None) -> str:
    if when is None:
        return "ไม่ทราบ"
    seconds = (_now() - when).total_seconds()
    if seconds < 90:
        return f"{int(seconds)} วินาทีก่อน"
    if seconds < 5400:
        return f"{int(seconds // 60)} นาทีก่อน"
    return f"{seconds / 3600:.1f} ชั่วโมงก่อน"


def normalise(path: str) -> str:
    """ทำให้ทุกแชทเรียกไฟล์เดียวกันด้วยชื่อเดียวกัน

    ไม่งั้น "app.py" กับ "./app.py" กับพาธเต็ม จะกลายเป็นคนละล็อกกัน
    แล้วสองแชทจะถือ "คนละไฟล์" ที่จริงเป็นไฟล์เดียวกัน
    """
    raw = Path(str(path).strip().strip('"').replace("\\", "/"))
    try:
        resolved = raw if raw.is_absolute() else (BASE_DIR / raw)
        return resolved.resolve().relative_to(BASE_DIR).as_posix()
    except (ValueError, OSError):
        return raw.as_posix()


# ------------------------------------------------------------------ git

def _git(*args: str) -> str:
    try:
        done = subprocess.run(
            ["git", *args], cwd=str(BASE_DIR), capture_output=True, timeout=20, creationflags=studio_shared.NO_WINDOW)
        return done.stdout.decode("utf-8", errors="replace").strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def git_state(rel: str) -> dict:
    """ไฟล์นี้อยู่เวอร์ชันไหน มีของแก้ค้างไหม — เอาจาก git ตรงๆ ไม่เดา"""
    last = _git("log", "-1", "--format=%h|%ad|%an|%s",
                "--date=format:%d/%m %H:%M", "--", rel)
    commit, when, who, subject = (last.split("|", 3) + ["", "", "", ""])[:4]
    stat = _git("diff", "--numstat", "--", rel)
    added = removed = 0
    if stat:
        parts = stat.split("\t")
        if len(parts) >= 2:
            added = int(parts[0]) if parts[0].isdigit() else 0
            removed = int(parts[1]) if parts[1].isdigit() else 0
    staged = bool(_git("diff", "--cached", "--name-only", "--", rel))
    tracked = bool(_git("ls-files", "--", rel))
    return {
        "commit": commit, "when": when, "who": who, "subject": subject,
        "dirty": bool(stat) or staged,
        "added": added, "removed": removed,
        "tracked": tracked,
    }


def file_touched(rel: str) -> datetime | None:
    """ไฟล์ถูกแก้จริงล่าสุดเมื่อไร — ใช้ดูว่าคนถืออยู่ยัง "ทำอยู่จริง" ไหม

    สำคัญกว่าที่คิด: การจองที่ค้างมา 40 นาทีแต่ไฟล์เพิ่งถูกแก้เมื่อ 2 นาทีก่อน
    แปลว่ายังทำอยู่ ส่วนการจองที่ค้าง 40 นาทีแล้วไฟล์ไม่ขยับเลย แปลว่าน่าจะทิ้งแล้ว
    ตัวเลขนี้เลยเป็นหลักฐานให้คนตัดสินใจว่าจะแย่ง (steal) ดีไหม
    """
    try:
        return datetime.fromtimestamp((BASE_DIR / rel).stat().st_mtime)
    except OSError:
        return None


# ------------------------------------------------------------- ตัวข้อมูล

def _blank() -> dict:
    return {"claims": {}, "queue": {}, "history": []}


def _load() -> dict:
    data = studio_shared.read_json(CLAIMS_FILE, None)
    if not isinstance(data, dict):
        return _blank()
    for key, empty in (("claims", {}), ("queue", {}), ("history", [])):
        if not isinstance(data.get(key), type(empty)):
            data[key] = empty
    return data


def _expired(claim: dict) -> bool:
    ends = _parse(claim.get("expires", ""))
    return ends is None or _now() >= ends


def _sweep(data: dict) -> list[dict]:
    """ปล่อยการจองที่หมดอายุ แล้วยกให้คิวถัดไป — คืนรายการที่ต้องแจ้ง

    ต้องทำทุกครั้งที่อ่านข้อมูล ไม่ใช่มีตัวตั้งเวลาแยก เพราะไม่มีโปรเซสไหน
    รันค้างไว้คอยเก็บกวาดให้ (สคริปต์นี้ทำงานแล้วจบทันที)

    **ห้ามเรียก git ในนี้** ฟังก์ชันนี้ทำงานใต้ล็อกไฟล์ข้อมูล การไปเรียก
    subprocess ระหว่างถือล็อกแปลว่าอีกแชทที่ขอพร้อมกันอาจรอจนหมดเวลา
    """
    handovers = []
    for rel, claim in list(data["claims"].items()):
        if not _expired(claim):
            continue
        # ยังแตะไฟล์อยู่จริง = ยังทำอยู่ ต่ออายุให้เลย อย่าไปยึดคืนกลางทาง
        if _still_working(rel, claim):
            claim["expires"] = _stamp(_now() + timedelta(minutes=HOLD_MINUTES))
            claim["auto_renewed"] = int(claim.get("auto_renewed", 0)) + 1
            continue
        data["claims"].pop(rel, None)
        _remember(data, {**claim, "file": rel, "released": _stamp(_now()),
                         "how": "หมดอายุเอง",
                         "last_touch": _stamp(file_touched(rel)) if file_touched(rel) else ""})
        nxt = _promote(data, rel)
        if nxt:
            handovers.append(nxt)
    return handovers


def _still_working(rel: str, claim: dict) -> bool:
    """คนถืออยู่ยังทำอยู่จริงไหม — ดูจากว่าไฟล์ถูกแตะหลังจองและแตะเมื่อไม่นานนี้

    ใช้ `stat()` อย่างเดียว ไม่เรียก subprocess — ฟังก์ชันนี้ทำงานใต้ล็อกไฟล์ข้อมูล
    """
    since = _parse(claim.get("since", ""))
    touched = file_touched(rel)
    if since is None or touched is None or touched <= since:
        return False        # ไม่เคยแตะเลยตั้งแต่จอง = จองทิ้งไว้ ไม่ต้องต่อให้
    return (_now() - touched) <= timedelta(minutes=ACTIVE_MINUTES)


def _promote(data: dict, rel: str, base_commit: str = "") -> dict | None:
    """ยกสิทธิ์ให้คิวถัดไปทันทีที่ว่าง

    ยกให้เลยแทนที่จะปล่อยว่างให้ไปแย่งกัน เพราะถ้าปล่อยว่าง แชทที่ถามบ่อยกว่า
    จะได้ไปเรื่อยๆ ส่วนคนที่รอมานานสุดอาจไม่ได้สักที — ให้ตามลำดับที่มาก่อน

    ให้เวลาเริ่มสั้น (GRACE_MINUTES) เพราะแชทที่ได้คิวอาจไม่ได้เปิดอยู่
    ถ้าปล่อยให้ถือเต็มเวลาปกติ คนที่พร้อมทำจริงจะถูกบล็อกฟรีๆ
    """
    waiting = data["queue"].get(rel) or []
    if not waiting:
        return None
    nxt = waiting.pop(0)
    if waiting:
        data["queue"][rel] = waiting
    else:
        data["queue"].pop(rel, None)
    started = _now()
    data["claims"][rel] = {
        "chat": nxt.get("chat", ""),
        "session": nxt.get("session", ""),
        "why": nxt.get("why", ""),
        "since": _stamp(started),
        "expires": _stamp(started + timedelta(minutes=GRACE_MINUTES)),
        "base_commit": base_commit,
        "granted_from_queue": True,
    }
    return {"file": rel, **data["claims"][rel]}


def _remember(data: dict, entry: dict) -> None:
    data["history"].append(entry)
    del data["history"][:-HISTORY_LIMIT]


# ------------------------------------------------------------- คำสั่งหลัก

def claim(path: str, chat: str, why: str = "", session: str = "",
          minutes: int = HOLD_MINUTES, force: bool = False,
          kind: str = "") -> dict:
    """ขอสิทธิ์แก้ไฟล์ — ได้เลย หรือถูกต่อคิว

    คืน dict ที่มี `granted` บอกผล และ `holder` / `position` ประกอบ
    """
    if not str(chat or "").strip():
        raise ClaimError("ต้องบอกชื่อแชทด้วย (--chat) ไม่งั้นไม่รู้ว่าใครถืออยู่")
    rel = normalise(path)
    # อ่าน git **ก่อน** เข้าล็อก — เรียก subprocess ระหว่างถือล็อกไฟล์ข้อมูล
    # ทำให้แชทที่ขอพร้อมกันรอนานเกินจำเป็นและอาจ timeout
    base_commit = git_state(rel).get("commit", "")
    result: dict = {}

    def change(data: dict) -> None:
        result["handovers"] = _sweep(data)
        holder = data["claims"].get(rel)
        if holder and holder.get("chat") == chat:
            # เจ้าของเดิมขอซ้ำ = ต่ออายุ ไม่ใช่ชน
            holder["expires"] = _stamp(_now() + timedelta(minutes=minutes))
            holder["why"] = why or holder.get("why", "")
            holder["kind"] = kind or holder.get("kind", "")
            holder.pop("granted_from_queue", None)
            result.update(granted=True, renewed=True, claim=holder, file=rel)
            return
        if holder and not force:
            waiting = data["queue"].setdefault(rel, [])
            already = next((w for w in waiting if w.get("chat") == chat), None)
            if already:
                already["why"] = why or already.get("why", "")
                position = waiting.index(already) + 1
            else:
                waiting.append({"chat": chat, "session": session, "why": why,
                                "kind": kind, "at": _stamp(_now())})
                position = len(waiting)
            result.update(granted=False, holder=holder, position=position, file=rel)
            return
        if holder and force:
            _remember(data, {**holder, "file": rel, "released": _stamp(_now()),
                             "how": f"ถูก {chat} แย่งไป"})
        started = _now()
        # ไม่ล้างคิวทิ้ง — คนที่รออยู่ยังต้องได้คิวตามลำดับเดิมหลังเราปล่อย
        data["claims"][rel] = {
            # kind = "fix" งานซ่อมของพัง / "feat" งานเพิ่มของใหม่ / "" ไม่ระบุ
            # เจ้าหน้าที่คิว (dispatcher.py) ใช้ค่านี้ตัดสินว่าใครแซงใครได้
            "chat": chat, "session": session, "why": why, "kind": kind,
            "since": _stamp(started),
            "expires": _stamp(started + timedelta(minutes=minutes)),
            "base_commit": base_commit,
        }
        result.update(granted=True, stolen=bool(holder), claim=data["claims"][rel],
                      file=rel)

    studio_shared.update_json(CLAIMS_FILE, change, default=_blank(),
                              label=f"จองไฟล์ {rel}")
    return result


def release(path: str, chat: str, note: str = "") -> dict:
    """คืนสิทธิ์ — คืนข้อมูลคิวถัดไปให้เอาไปแจ้งต่อ"""
    rel = normalise(path)
    state = git_state(rel)          # อ่าน git ก่อนเข้าล็อก เหตุผลเดียวกับ claim()
    result: dict = {}

    def change(data: dict) -> None:
        result["handovers"] = _sweep(data)
        holder = data["claims"].get(rel)
        if not holder:
            # "ไม่มีใครถืออยู่" อย่างเดียวไม่พอ — คนสั่งปล่อยมักเป็นคนที่คิดว่าตัวเอง
            # ถืออยู่ ต้องบอกให้ได้ว่าการจองของเขาจบไปตอนไหนและเพราะอะไร
            mine = [h for h in data["history"]
                    if h.get("file") == rel and h.get("chat") == chat]
            if mine:
                last = mine[-1]
                when = _parse(last.get("released", ""))
                result.update(ok=False, file=rel, expired_before=last, reason=(
                    f"การจองของ \"{chat}\" จบไปแล้ว — {last.get('how')}"
                    f" เมื่อ {_ago(when)}"))
            else:
                result.update(ok=False, reason="ไฟล์นี้ไม่มีใครถืออยู่", file=rel)
            return
        if holder.get("chat") != chat:
            result.update(ok=False, file=rel, holder=holder,
                          reason=f"คนถือคือ \"{holder.get('chat')}\" ไม่ใช่ \"{chat}\"")
            return
        data["claims"].pop(rel, None)
        _remember(data, {**holder, "file": rel, "released": _stamp(_now()),
                         "how": "ปล่อยเอง", "note": note,
                         "end_commit": state.get("commit", ""),
                         "still_dirty": state.get("dirty", False)})
        result.update(ok=True, file=rel, state=state,
                      next=_promote(data, rel, state.get("commit", "")))

    studio_shared.update_json(CLAIMS_FILE, change, default=_blank(),
                              label=f"คืนไฟล์ {rel}")
    return result


def status(path: str) -> dict:
    """ไฟล์นี้ใครถืออยู่ · อยู่เวอร์ชันไหน · เปลี่ยนอะไรไปแล้วบ้าง"""
    rel = normalise(path)
    result: dict = {}

    def change(data: dict) -> None:
        result["handovers"] = _sweep(data)
        result.update(
            file=rel,
            claim=data["claims"].get(rel),
            queue=data["queue"].get(rel) or [],
            history=[h for h in data["history"] if h.get("file") == rel][-5:],
        )

    studio_shared.update_json(CLAIMS_FILE, change, default=_blank(),
                              label=f"ดูสถานะ {rel}")
    result["git"] = git_state(rel)
    result["touched"] = file_touched(rel)
    return result


def listing() -> dict:
    """ทุกไฟล์ที่มีคนถือหรือมีคิวรออยู่"""
    result: dict = {}

    def change(data: dict) -> None:
        result["handovers"] = _sweep(data)
        result.update(claims=dict(data["claims"]), queue=dict(data["queue"]))

    studio_shared.update_json(CLAIMS_FILE, change, default=_blank(),
                              label="ดูรายการจองทั้งหมด")
    return result


# ------------------------------------------------------- แสดงผลบรรทัดคำสั่ง

def _describe_claim(claim: dict, rel: str) -> list[str]:
    since = _parse(claim.get("since", ""))
    ends = _parse(claim.get("expires", ""))
    left = ""
    if ends:
        minutes = (ends - _now()).total_seconds() / 60
        left = f" · เหลือ {int(minutes)} นาที" if minutes > 0 else " · หมดอายุแล้ว"
    lines = [f"   ถือโดย : {claim.get('chat') or '(ไม่ระบุ)'}{left}"]
    if claim.get("auto_renewed"):
        lines.append(f"   ต่ออายุ : อัตโนมัติ {claim['auto_renewed']} ครั้ง"
                     " (ไฟล์ยังถูกแก้อยู่จริง)")
    if claim.get("why"):
        lines.append(f"   ทำอะไร : {claim['why']}")
    lines.append(f"   ตั้งแต่ : {_ago(since)}")
    if claim.get("granted_from_queue"):
        lines.append("   หมายเหตุ: เพิ่งได้คิวต่อ ยังไม่เริ่มทำ")
    touched = file_touched(rel)
    if touched and since:
        working = touched > since
        lines.append(
            f"   ไฟล์   : แตะล่าสุด {_ago(touched)}"
            + ("  ← ยังทำอยู่จริง" if working else "  ← ยังไม่แตะเลยตั้งแต่จอง")
        )
    return lines


def expiring_soon(chat: str) -> list[dict]:
    """การจองของแชทนี้ที่ใกล้หมดอายุ — เอาไปเตือนตอนรันคำสั่งอะไรก็ได้"""
    if not str(chat or "").strip():
        return []
    soon = []
    for rel, claim in (_load().get("claims") or {}).items():
        if claim.get("chat") != chat:
            continue
        ends = _parse(claim.get("expires", ""))
        if ends is None:
            continue
        left = (ends - _now()).total_seconds() / 60
        if left <= WARN_MINUTES:
            soon.append({"file": rel, "left": left,
                         "working": _still_working(rel, claim)})
    return soon


def _print_expiring(chat: str) -> None:
    """เตือนก่อนการจองหมดอายุ

    ที่ผ่านมาไม่มีตัวเตือน แล้วการจองหมดอายุกลางงานโดยคนถือไม่รู้ตัว
    (เจอกับตัวเองรอบแรกที่ใช้: จอง 17:48 งานยาวถึง 23:08)
    """
    soon = expiring_soon(chat)
    if not soon:
        return
    print()
    print("⏰ การจองของคุณใกล้หมดอายุ")
    for item in soon:
        left = int(item["left"])
        state = " (ยังแก้ไฟล์อยู่ ระบบจะต่ออายุให้เอง)" if item["working"] else ""
        print(f"   · {item['file']} — เหลือ {left} นาที{state}")
    if any(not i["working"] for i in soon):
        print(f"   สั่ง claim ซ้ำเพื่อต่ออายุ ถ้ายังทำไม่เสร็จ")


def _print_handovers(info: dict) -> None:
    """บอกว่ามีการจองหมดอายุแล้วยกให้คิวถัดไป — คนที่รันคำสั่งต้องช่วยแจ้งต่อ

    ต้องพิมพ์ทุกคำสั่ง ไม่ใช่เฉพาะตอน release เพราะการยกคิวเกิดขึ้นตอน "หมดอายุ"
    ซึ่งไม่มีใครสั่งอะไร — ใครบังเอิญมาเรียกคำสั่งก่อนเป็นคนเห็น ถ้าไม่พิมพ์ตรงนี้
    คนที่ได้คิวจะไม่มีวันรู้ว่าถึงคิวตัวเองแล้ว
    """
    handovers = info.get("handovers") or []
    if not handovers:
        return
    print()
    print("📨 มีการจองหมดอายุ และยกสิทธิ์ให้คิวถัดไปแล้ว — **ช่วยส่งข้อความบอกเขาด้วย**")
    for h in handovers:
        print(f"   · {h['file']} → \"{h.get('chat')}\""
              f"  session: {h.get('session') or '(ไม่ได้ให้ไว้)'}")
        if h.get("why"):
            print(f"     เขาจะทำ: {h['why']}")
    print(f"   (สิทธิ์นี้หมดอายุใน {GRACE_MINUTES} นาทีถ้าเขาไม่ claim ต่อ)")


def _print_status(info: dict) -> None:
    rel, git = info["file"], info["git"]
    print(f"📄 {rel}")
    if git.get("commit"):
        print(f"   เวอร์ชัน: {git['commit']} · {git['when']} · {git['subject'][:56]}")
    elif not git.get("tracked"):
        print("   เวอร์ชัน: ยังไม่เข้า git (ไฟล์ใหม่)")
    if git.get("dirty"):
        print(f"   ⚠️ มีของแก้ค้างยังไม่ commit (+{git['added']} -{git['removed']} บรรทัด)")
    else:
        print("   ✅ ไม่มีของแก้ค้าง ตรงกับ commit ล่าสุด")

    claim = info.get("claim")
    print()
    if claim:
        print("🔒 มีคนถืออยู่ — อย่าเพิ่งแก้")
        for line in _describe_claim(claim, rel):
            print(line)
    else:
        print("🟢 ว่าง — จองได้เลย")

    if info.get("queue"):
        print()
        print(f"⏳ คิวรอ {len(info['queue'])} ราย")
        for i, item in enumerate(info["queue"], 1):
            print(f"   {i}. {item.get('chat')} — {item.get('why') or '(ไม่ระบุ)'}"
                  f" · ขอเมื่อ {_ago(_parse(item.get('at', '')))}")

    if info.get("history"):
        print()
        print("📜 ใครแก้ไฟล์นี้ล่าสุด")
        for h in reversed(info["history"]):
            note = f" — {h['note']}" if h.get("note") else ""
            print(f"   · {h.get('chat')} · {_ago(_parse(h.get('released', '')))}"
                  f" · {h.get('how')}{note}")
            if h.get("why"):
                print(f"     ทำ: {h['why']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="จัดคิวการแก้ไฟล์ระหว่างแชท — จองก่อนแก้ ปล่อยเมื่อเสร็จ")
    sub = parser.add_subparsers(dest="command", required=True)

    def add_common(p):
        p.add_argument("file")
        p.add_argument("--chat", default=os.environ.get("STUDIO_CHAT", ""),
                       required=False,
                       help="ชื่อแชทที่ขอ (ตั้ง STUDIO_CHAT ไว้ก็ได้)")
        p.add_argument("--session", default=os.environ.get("STUDIO_SESSION", ""),
                       help="sessionId ของแชท ไว้ให้คนที่ปล่อยส่งสัญญาณกลับมาถูกตัว")
        p.add_argument("--why", default="", help="จะแก้อะไร")

    p_status = sub.add_parser("status", help="ไฟล์นี้ใครถืออยู่ / เวอร์ชันไหน")
    p_status.add_argument("file")

    p_claim = sub.add_parser("claim", help="ขอสิทธิ์แก้ไฟล์ (ไม่ว่าง = ต่อคิว)")
    add_common(p_claim)
    p_claim.add_argument("--minutes", type=int, default=HOLD_MINUTES)
    p_claim.add_argument("--force", action="store_true",
                         help="แย่งมาเลย ใช้เมื่อแน่ใจว่าคนถือทิ้งไปแล้ว")
    p_claim.add_argument("--kind", default="", choices=["", "fix", "feat"],
                         help="fix = ซ่อมของพัง (แซงงาน feat ได้) / feat = เพิ่มของใหม่")

    p_release = sub.add_parser("release", help="คืนสิทธิ์ + ดูว่าต้องแจ้งใครต่อ")
    add_common(p_release)
    p_release.add_argument("--note", default="", help="สรุปสั้นๆ ว่าทำอะไรไป")

    sub.add_parser("list", help="ดูทุกไฟล์ที่มีคนถือ/มีคิว")

    args = parser.parse_args(argv)

    watcher = os.environ.get("STUDIO_CHAT", "")

    if args.command == "status":
        info = status(args.file)
        _print_status(info)
        _print_handovers(info)
        _print_expiring(watcher)
        return 0

    if args.command == "list":
        data = listing()
        if not data["claims"] and not data["queue"]:
            print("🟢 ตอนนี้ไม่มีใครถือไฟล์ไหนอยู่เลย")
            _print_handovers(data)
            return 0
        # ห้ามตั้งชื่อตัวแปรนี้ว่า claim — จะไปบังฟังก์ชัน claim() ทั้งฟังก์ชัน main
        # แล้วคำสั่ง claim จะพังด้วย UnboundLocalError (ไวยากรณ์ผ่าน เจอตอนรันเท่านั้น)
        for rel, held in data["claims"].items():
            print(f"🔒 {rel}")
            for line in _describe_claim(held, rel):
                print(line)
            for i, item in enumerate(data["queue"].get(rel) or [], 1):
                print(f"   ⏳ คิว {i}: {item.get('chat')} — {item.get('why') or ''}")
            print()
        for rel, waiting in data["queue"].items():
            if rel not in data["claims"]:
                print(f"⏳ {rel} — มีคิวรอ {len(waiting)} รายแต่ไม่มีคนถือ (จะได้สิทธิ์รอบหน้า)")
        _print_handovers(data)
        _print_expiring(watcher)
        return 0

    if not str(getattr(args, "chat", "") or "").strip():
        print("❌ ต้องบอกชื่อแชทด้วย: --chat \"ชื่อแชท\"  (หรือตั้ง STUDIO_CHAT)")
        return 2

    if args.command == "claim":
        try:
            out = claim(args.file, args.chat, args.why, args.session,
                        args.minutes, args.force, args.kind)
        except ClaimError as error:
            print(f"❌ {error}")
            return 2
        if out.get("granted"):
            what = "ต่ออายุ" if out.get("renewed") else ("แย่งมา" if out.get("stolen") else "จอง")
            print(f"✅ {what}สำเร็จ — {out['file']} เป็นของ \"{args.chat}\" แล้ว")
            print(f"   เวอร์ชันตอนจอง: {out['claim'].get('base_commit') or '(ยังไม่เข้า git)'}")
            print(f"   หมดอายุใน {args.minutes} นาที (สั่ง claim ซ้ำเพื่อต่ออายุ)")
            print("   ⚠️ ทำเสร็จแล้วอย่าลืม release ไม่งั้นคิวถัดไปต้องรอจนหมดอายุ")
            _print_handovers(out)
            _print_expiring(args.chat)
            return 0
        holder = out["holder"]
        print(f"⛔ {out['file']} มีคนถืออยู่ — คุณถูกต่อคิวที่ {out['position']}")
        for line in _describe_claim(holder, out["file"]):
            print(line)
        print()
        print("   พอเขาปล่อย คุณจะได้สิทธิ์อัตโนมัติ และเขาจะส่งข้อความมาบอก")
        if holder.get("session"):
            print(f"   อยากเร่ง ส่งข้อความไปที่ session: {holder['session']}")
        _print_handovers(out)
        return 1

    if args.command == "release":
        out = release(args.file, args.chat, args.note)
        if not out.get("ok"):
            print(f"❌ คืนไม่ได้ — {out.get('reason')}")
            if out.get("expired_before"):
                past = out["expired_before"]
                print("   งานที่ทำค้างไว้ยังอยู่ในไฟล์ ไม่ได้หายไปไหน —"
                      " แค่สิทธิ์จองหลุดเท่านั้น")
                if past.get("still_dirty"):
                    print("   ⚠️ ตอนหลุดยังมีของแก้ไม่ได้ commit")
                print("   ถ้ายังต้องแก้ต่อ สั่ง claim ใหม่ได้เลย")
            return 2
        state = out["state"]
        print(f"✅ คืน {out['file']} แล้ว")
        if state.get("dirty"):
            print(f"   ⚠️ ยังมีของแก้ค้างไม่ได้ commit (+{state['added']} -{state['removed']})")
            print("   คนถัดไปจะเจอไฟล์ที่ยังไม่ commit — ควร commit ก่อนปล่อย")
        else:
            print(f"   commit ล่าสุด: {state.get('commit')} · {state.get('subject','')[:56]}")
        nxt = out.get("next")
        if not nxt:
            print("   ไม่มีใครรอคิว")
            return 0
        print()
        print("📨 มีคนรอคิวอยู่ — **ส่งข้อความไปบอกเขาด้วย**")
        print(f"   แชท    : {nxt.get('chat')}")
        print(f"   session: {nxt.get('session') or '(ไม่ได้ให้ไว้)'}")
        print(f"   เขาจะทำ: {nxt.get('why') or '(ไม่ระบุ)'}")
        print()
        print("   ข้อความสำเร็จรูป:")
        print(f"   ── ถึงคิวคุณแล้ว: {out['file']} ว่างแล้ว ผมปล่อยเรียบร้อย")
        if args.note:
            print(f"   ── สิ่งที่ผมทำไป: {args.note}")
        print(f"   ── เวอร์ชันล่าสุด: {state.get('commit')} · {state.get('subject','')[:56]}")
        if state.get("dirty"):
            print("   ── ⚠️ ยังมีของแก้ค้างไม่ได้ commit ดู git diff ก่อนเริ่ม")
        print(f"   ── สิทธิ์ของคุณหมดอายุใน {GRACE_MINUTES} นาที "
              f"สั่ง claim ซ้ำเพื่อต่ออายุก่อนเริ่มทำ")
        _print_expiring(args.chat)
        return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
