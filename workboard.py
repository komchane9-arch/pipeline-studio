"""กระดานสรุปงาน — หน้าเดียวจบ อัปเดตเองทุกเช้า 08:00

**ตั้งใจให้เป็น "สรุปเช้า" ไม่ใช่ "กองสถานะ"** ความต่างอยู่ที่ลำดับ: สิ่งที่ต้องลงมือ
ขึ้นก่อนเสมอ ส่วนของที่วิ่งอยู่ปกติดันลงล่าง เพราะเปิดมาตอนเช้าแล้วต้องตอบได้ทันทีว่า
*วันนี้ต้องทำอะไร* ไม่ใช่ต้องไล่อ่านทั้งหน้าเพื่อหาว่ามีอะไรผิดปกติไหม

ดึงจากของจริงทุกช่อง ไม่มีตัวเลขที่พิมพ์แช่ไว้:

    สมุดคำสั่ง (orders.py)      ใครถูกสั่งอะไร
    สมุดจอง (file_claims.py)    ใครถือไฟล์ไหน
    git                         อะไรค้างยังไม่ commit · commit ล่าสุด
    API 8866 / 8877             คิวโพสต์ · คิวคลิป
    adb                         มือถือที่ต่ออยู่
    data/todo.json              งานที่ต้องทำด้วยมือ (เติมเองได้)

**ห้ามพังทั้งหน้าเพราะช่องเดียวอ่านไม่ได้** ทุกช่องหุ้ม try ไว้ แล้วรายงานว่าอ่านไม่ได้
แทนที่จะโยน exception — ตัวรันตอน 08:00 ไม่มีคนดู ถ้าล้มก็เงียบหายไปเฉยๆ

เขียนผลลงสองที่: `web/workboard.html` (เปิดผ่านเซิร์ฟเวอร์ที่รันอยู่แล้วได้เลย
ไม่ต้องแก้ app.py) และพิมพ์ลงจอสำหรับเรียกดูจากบรรทัดคำสั่ง
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

import file_claims
import orders
import studio_shared

BASE_DIR = Path(__file__).resolve().parent
# **ต้องอยู่ในโฟลเดอร์ย่อย ห้ามวางไว้ชั้นบนสุดของ web/**
# app.py คิดเวอร์ชันแอปจาก sha1 ของไฟล์ .html/.js/.css ทุกตัวใน web/ ชั้นบนสุด
# ไฟล์นี้ถูกเขียนใหม่ทุกวัน เนื้อไม่เหมือนเดิมสักครั้ง ถ้าวางไว้ชั้นบนสุดเวอร์ชันแอปจะ
# เปลี่ยนทุกเช้า แล้วผู้ใช้จะเจอแบนเนอร์ "หน้าเว็บกับเซิร์ฟเวอร์เป็นคนละรุ่น" ทุกวัน
# ทั้งที่ไม่มีใครแก้โค้ดอะไรเลย (เกิดจริงแล้ว 19 ส.ค. 2026)
# glob("*.*") ของ app.py ไม่ไล่โฟลเดอร์ย่อย — โฟลเดอร์ย่อยจึงปลอดภัยถาวร
OUT_HTML = BASE_DIR / "web" / "board" / "index.html"
TODO_FILE = studio_shared.DATA_DIR / "todo.json"
MISSIONS_FILE = studio_shared.DATA_DIR / "missions.json"
# หน้าแยกสำหรับดูของค้างทั้งหมด — บนกระดานหลักโชว์แค่ย่อ ไม่งั้นยาวจนกลบเรื่องอื่น
OUT_DIRTY = BASE_DIR / "web" / "board" / "dirty.html"

# แผนงานประจำเดือนของเจ้าของโปรเจกต์ (Master plan) — ตั้งต้นจากที่เขาเขียนไว้เอง
# ตัวเลขเป้ากับที่ทำได้ต้องกรอกเอง ระบบไม่รู้จัก Reels/IG/Youtube/Shopee
# จึงไม่เดาให้ เพราะกราฟที่เดาตัวเลขเองอันตรายกว่ากราฟว่าง
DEFAULT_MISSIONS = [
    "Social media", "FB Reels", "Adboost", "IG", "Youtube",
    "Spaylater / Shopeefood / ท่องเที่ยว",
]

# กันพลาดซ้ำด้วยตัวเอง ไม่ใช่พึ่งให้คนจำกติกาได้ — ถ้าวันหนึ่งมีใครย้ายไฟล์ผลลัพธ์
# กลับไปไว้ชั้นบนสุดของ web/ ให้ตายตรงนี้เลย ดีกว่าไปโผล่เป็นแบนเนอร์ผิดรุ่นทุกเช้า
if OUT_HTML.parent == BASE_DIR / "web":
    raise SystemExit(
        "workboard.py: ห้ามเขียนผลลัพธ์ไว้ที่ web/ ชั้นบนสุด — app.py คิดเวอร์ชันแอป"
        " จากไฟล์ตรงนั้น เวอร์ชันจะเปลี่ยนทุกวัน ให้ใช้โฟลเดอร์ย่อยเช่น web/board/")

# ของค้างไม่ commit ที่เก่ากว่านี้ = ควรสะสางแล้ว
STALE_DAYS = 2
# งานคลิปที่รอกดอนุมัตินานกว่านี้ = ค้าง ไม่ใช่แค่ "เพิ่งเข้าคิว"
CLIP_WAIT_HOURS = 12

# แบ่งไฟล์เข้าสายตามตาราง 7.1 ของ CLAUDE.md — ไว้บอกว่าของค้างเป็นของแชทไหน
LANES = [
    ("post", ("fb_", "facebook_", "shopee_", "publish_flow", "hashtag", "web/post.js")),
    ("คลิป/วิดีโอ", ("flow_", "clip_", "chatgpt_driver", "gem", "tiktok", "drive_store",
                     "web/video.js")),
    ("ส่วนกลาง", ("app.py", "studio_shared", "telegram_bot", "dispatcher", "orders.py",
                  "file_claims", "workboard", "web/core.js", "web/index.html",
                  "web/phone.js", "CLAUDE.md")),
]


def _lane(rel: str) -> str:
    for name, prefixes in LANES:
        if any(rel.startswith(p) or rel == p for p in prefixes):
            return name
    return "อื่นๆ"


def _git(*args: str) -> str:
    try:
        done = subprocess.run(["git", *args], cwd=str(BASE_DIR), capture_output=True,
                              timeout=25, creationflags=studio_shared.NO_WINDOW)
        return done.stdout.decode("utf-8", errors="replace").strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def _get(url: str, timeout: float = 4.0):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as answer:
            return json.loads(answer.read().decode("utf-8"))
    except Exception:                      # noqa: BLE001 - เซิร์ฟเวอร์ดับไม่ใช่เรื่องผิดปกติ
        return None


def _ago(when: datetime | None) -> str:
    if when is None:
        return "ไม่ทราบ"
    gap = (datetime.now() - when).total_seconds()
    if gap < 3600:
        return f"{gap / 60:.0f} นาทีก่อน"
    if gap < 86400:
        return f"{gap / 3600:.1f} ชั่วโมงก่อน"
    return f"{gap / 86400:.1f} วันก่อน"


# --------------------------------------------------------------- งานมือ

def todos() -> list[dict]:
    rows = studio_shared.read_json(TODO_FILE, None)
    return rows if isinstance(rows, list) else []


def todo_add(text: str, who: str = "") -> int:
    def change(data):
        data.append({"text": text, "who": who, "at": datetime.now().isoformat(timespec="seconds"),
                     "done": False})

    studio_shared.update_json(TODO_FILE, change, default=[], label="เพิ่มงานค้าง")
    print("เพิ่มแล้ว: " + text)
    return 0


def todo_done(number: int) -> int:
    hit = {"text": ""}

    def change(data):
        open_rows = [r for r in data if not r.get("done")]
        if 1 <= number <= len(open_rows):
            open_rows[number - 1]["done"] = True
            hit["text"] = open_rows[number - 1]["text"]

    studio_shared.update_json(TODO_FILE, change, default=[], label="ปิดงานค้าง")
    print(("ปิดแล้ว: " + hit["text"]) if hit["text"] else "ไม่พบข้อ " + str(number))
    return 0


def missions() -> dict:
    """แผนเดือนนี้ — ไม่มีไฟล์ก็สร้างโครงจากรายการตั้งต้นให้เลย"""
    data = studio_shared.read_json(MISSIONS_FILE, None)
    if not isinstance(data, dict) or not isinstance(data.get("missions"), list):
        return {"month": datetime.now().strftime("%Y-%m"),
                "title": f"Master plan {datetime.now():%B %Y}",
                "missions": [{"name": n, "target": 0, "done": 0, "note": ""}
                             for n in DEFAULT_MISSIONS]}
    return data


def mission_set(name: str, target=None, done=None, note=None) -> int:
    """ตั้งเป้า/อัปเดตความคืบหน้าของ mission หนึ่งข้อ (จับชื่อแบบมีคำนี้อยู่ก็พอ)"""
    hit = {"name": ""}

    def change(data):
        if not isinstance(data.get("missions"), list) or not data["missions"]:
            data.clear()
            data.update(missions())
        for row in data["missions"]:
            if name.lower() in row["name"].lower():
                if target is not None:
                    row["target"] = target
                if done is not None:
                    row["done"] = done
                if note is not None:
                    row["note"] = note
                row["updated"] = datetime.now().isoformat(timespec="seconds")
                hit["name"] = row["name"]
                return

    studio_shared.update_json(MISSIONS_FILE, change, default={}, label="ตั้งค่า mission")
    if hit["name"]:
        print(f"อัปเดตแล้ว: {hit['name']}")
    else:
        print(f"ไม่พบ mission ที่มีคำว่า “{name}” — ดูรายชื่อด้วย mission list")
    return 0


def mission_list() -> int:
    plan = missions()
    print(plan.get("title", "แผนเดือนนี้"))
    for i, row in enumerate(plan["missions"], 1):
        target, done = row.get("target", 0), row.get("done", 0)
        bar = "ยังไม่ตั้งเป้า" if not target else f"{done}/{target} ({done / target * 100:.0f}%)"
        print(f"  {i}. {row['name']:38s} {bar}")
    return 0


# ------------------------------------------------------------- เก็บข้อมูล

def collect() -> dict:
    now = datetime.now()
    out: dict = {"at": now, "problems": [], "notes": []}

    # ---- ของค้างไม่ commit แยกตามสาย ----
    dirty: dict[str, list] = {}
    oldest = None
    for line in _git("status", "--porcelain").splitlines():
        rel = line[3:].strip().strip('"')
        if not rel:
            continue
        full = BASE_DIR / rel
        touched = None
        try:
            touched = datetime.fromtimestamp(full.stat().st_mtime)
        except OSError:
            pass
        dirty.setdefault(_lane(rel), []).append({"file": rel, "touched": touched,
                                                 "new": line.startswith("??")})
        if touched and (oldest is None or touched < oldest):
            oldest = touched
    out["dirty"] = dirty
    out["dirty_total"] = sum(len(v) for v in dirty.values())
    out["dirty_oldest"] = oldest
    if oldest and (now - oldest).days >= STALE_DAYS:
        out["problems"].append(
            f"ของค้างไม่ commit {out['dirty_total']} ไฟล์ — เก่าสุดตั้งแต่ {_ago(oldest)}")

    # ---- ใครถูกสั่งอะไร / ถือไฟล์อะไร ----
    try:
        book = orders._load()["orders"]
    except Exception:                      # noqa: BLE001
        book = {}
    try:
        claims = file_claims._load()["claims"]
    except Exception:                      # noqa: BLE001
        claims = {}

    working = []
    for session, row in book.items():
        if row.get("status") != "open":
            continue
        moved = orders._parse(row.get("updated", ""))
        held = [rel for rel, c in claims.items() if c.get("chat") == row.get("chat")]
        working.append({
            "chat": row.get("chat") or "ไม่ทราบชื่อ",
            "session": session[:8],
            "text": (row.get("text") or "").strip(),
            "files": held or (row.get("files") or []),
            "moved": moved,
            "quiet": moved is not None and (now - moved).total_seconds() > orders.STALE_MINUTES * 60,
            "clash": bool((row.get("clash") or {}).get("shared")
                          and not (row.get("clash") or {}).get("resolved")),
        })
    working.sort(key=lambda w: w["moved"] or now, reverse=True)
    out["working"] = working
    out["claims"] = claims
    for w in working:
        if w["clash"]:
            out["problems"].append(f'"{w["chat"]}" ติดข้อพิพาทค้าง ยังไม่มีใครตัดสิน')

    # ---- แก้อยู่โดยไม่ได้จอง ----
    try:
        import dispatcher
        out["loose"] = dispatcher.unclaimed(claims)
    except Exception:                      # noqa: BLE001
        out["loose"] = []

    # ---- คิวโพสต์ ----
    posts = _get("http://127.0.0.1:8866/api/fb/jobs")
    out["post_up"] = posts is not None
    out["post_running"] = bool(posts.get("running")) if posts else None
    if posts is None:
        out["problems"].append("ต่อเซิร์ฟเวอร์หน้าเว็บ (8866) ไม่ได้ — หน้าเว็บใช้ไม่ได้")

    # ---- คิวคลิป ----
    clip = _get("http://127.0.0.1:8877/api/health")
    out["clip_up"] = clip is not None
    out["clip_open"] = clip.get("queue") if clip else None
    if clip is None:
        out["problems"].append("ต่อเซิร์ฟเวอร์คลิป (8877) ไม่ได้ — บอทคลิปจะเงียบ")

    # งานที่รอ "คนกดอนุมัติ" คนละตัวกับ "งานที่ยังไม่จบ" — แยกให้ชัด ไม่งั้นเลขหลอกตา
    waiting, oldest_wait = [], None
    try:
        rows = studio_shared.read_json(studio_shared.DATA_DIR / "clip_queue.json", [])
        rows = rows if isinstance(rows, list) else rows.get("items", [])
        for job in rows:
            if not job.get("awaiting"):
                continue
            born = orders._parse(job.get("created_at") or job.get("updated_at") or "")
            waiting.append({"name": (job.get("name") or job.get("id") or "?")[:60],
                            "since": born})
            if born and (oldest_wait is None or born < oldest_wait):
                oldest_wait = born
    except Exception:                      # noqa: BLE001
        pass
    out["clip_waiting"] = waiting
    if oldest_wait and (now - oldest_wait).total_seconds() > CLIP_WAIT_HOURS * 3600:
        out["problems"].append(
            f"คลิป {len(waiting)} งานรอคุณกดอนุมัติ — เก่าสุดตั้งแต่ {_ago(oldest_wait)}")

    # ---- มือถือ ----
    try:
        done = subprocess.run(["adb", "devices"], capture_output=True, timeout=15,
                              creationflags=studio_shared.NO_WINDOW)
        lines = done.stdout.decode("utf-8", errors="replace").splitlines()[1:]
        out["phones"] = [l.split()[0] for l in lines if l.strip().endswith("device")]
    except (OSError, subprocess.SubprocessError):
        out["phones"] = []
    if not out["phones"]:
        out["problems"].append("ไม่มีมือถือต่ออยู่ — งานโพสต์รันไม่ได้")

    # ---- commit ล่าสุด ----
    out["commits"] = [l for l in _git("log", "--oneline", "-8").splitlines() if l]

    # ---- งานที่ต้องทำด้วยมือ ----
    out["todo"] = [t for t in todos() if not t.get("done")]
    out["plan"] = missions()
    return out


# ------------------------------------------------------------ แสดงผลจอ

def to_text(d: dict) -> str:
    L = [f"กระดานสรุปงาน — {d['at']:%d/%m/%Y %H:%M}", "=" * 58, ""]

    if d["problems"]:
        L.append(f"[ ต้องลงมือ {len(d['problems'])} เรื่อง ]")
        for p in d["problems"]:
            L.append("  ! " + p)
    else:
        L.append("[ ไม่มีอะไรค้างที่ต้องรีบ ]")
    L.append("")

    if d["todo"]:
        L.append(f"[ งานที่จดไว้ {len(d['todo'])} ข้อ ]")
        for i, t in enumerate(d["todo"], 1):
            L.append(f"  {i}. {t['text']}" + (f"  ({t['who']})" if t.get("who") else ""))
        L.append("")

    L.append("[ แชทที่กำลังทำอยู่ ]")
    if not d["working"]:
        L.append("  ไม่มีแชทไหนมีงานค้าง")
    for w in d["working"]:
        tag = " (เงียบนานแล้ว)" if w["quiet"] else ""
        L.append(f"  - {w['chat']}{tag}")
        L.append(f"      {w['text'][:100] or '(ยังไม่มีคำสั่งชัดเจน)'}")
        if w["files"]:
            L.append(f"      ไฟล์: {', '.join(w['files'][:5])}")
        L.append(f"      ขยับล่าสุด {_ago(w['moved'])}")
    L.append("")

    L.append(f"[ ของค้างไม่ commit {d['dirty_total']} ไฟล์ ]")
    for lane, rows in sorted(d["dirty"].items(), key=lambda kv: -len(kv[1])):
        newest = max((r["touched"] for r in rows if r["touched"]), default=None)
        L.append(f"  {lane}: {len(rows)} ไฟล์  (ล่าสุด {_ago(newest)})")
    L.append("")

    L.append("[ ระบบ ]")
    L.append(f"  เว็บ 8866      {'ปกติ' if d['post_up'] else 'ต่อไม่ได้'}"
             + (f" · โพสต์กำลังรัน: {'ใช่' if d['post_running'] else 'ไม่'}" if d["post_up"] else ""))
    L.append(f"  คลิป 8877      {'ปกติ' if d['clip_up'] else 'ต่อไม่ได้'}"
             + (f" · งานยังไม่จบ {d['clip_open']} · รอกดอนุมัติ {len(d['clip_waiting'])}"
                if d["clip_up"] else ""))
    L.append(f"  มือถือ         {', '.join(d['phones']) if d['phones'] else 'ไม่มี'}")
    L.append(f"  ไฟล์ที่มีคนถือ  {len(d['claims'])}")
    if d["loose"]:
        L.append(f"  แก้โดยไม่จอง   {len(d['loose'])} ไฟล์ (ระบบมองไม่เห็นว่าใครทำ)")
    L.append("")

    L.append("[ commit ล่าสุด ]")
    for c in d["commits"][:6]:
        L.append("  " + c)
    return "\n".join(L)


# ------------------------------------------------------------ แสดงผลเว็บ
def _esc(text) -> str:
    return (str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


# หน้านี้ยืมภาษาออกแบบมาจาก web/styles.css ของแอปหลัก (โทน iOS grouped list) เพื่อให้
# รู้สึกเป็นของชุดเดียวกัน ไม่ใช่หน้าแปลกปลอมที่ถูกแปะเข้ามา:
#   · พื้น #f2f2f7 · การ์ดขาวมุมมน 14px · เส้นคั่นบางร่นจากซ้าย · เงาอ่อนมาก
#   · SF Pro VF ตามด้วย Leelawadee UI — **ห้ามตัดฟอนต์ไทยออก** SF Pro ไม่มีอักษรไทย
#     ถ้าไม่มีตัวสำรอง สระกับวรรณยุกต์จะลอยผิดตำแหน่งทั้งหน้า
#   · แอปหลักเป็นโหมดสว่างอย่างเดียว หน้านี้จึงไม่ทำโหมดมืด จะได้ไม่ขัดกันเอง
_CSS = """
@font-face { font-family:"SF Pro VF"; src:url("/static/fonts/SFPro.ttf") format("truetype-variations");
             font-weight:1 1000; font-style:normal; font-display:swap; }
:root{
  --bg:#f2f2f7; --panel:#fff; --ink:#000; --ink-2:#3c3c43; --ink-3:#8e8e93;
  --sep:rgba(60,60,67,.29); --line:rgba(0,0,0,.10);
  --green:#34c759; --red:#ff3b30; --orange:#ff9500; --blue:#0088ff; --purple:#af52de;
  --r:14px; --shadow:0 1px 2px rgba(0,0,0,.04), 0 8px 24px rgba(0,0,0,.06);
}
*{box-sizing:border-box}
body{margin:0; padding:22px 18px 40px; background:var(--bg); color:var(--ink);
     font-family:"SF Pro VF","Leelawadee UI",-apple-system,"Segoe UI",sans-serif;
     font-size:15px; line-height:22px; -webkit-font-smoothing:antialiased;}
.page{max-width:1080px; margin:0 auto}

/* ---------- หัวหน้า ---------- */
.top{display:flex; align-items:flex-start; justify-content:space-between; gap:16px;
     flex-wrap:wrap; margin-bottom:20px}
h1{font-size:28px; line-height:34px; font-weight:700; margin:0; letter-spacing:-.4px}
.sub{color:var(--ink-3); font-size:13px; line-height:18px; margin-top:3px}
.pill{display:inline-flex; align-items:center; gap:7px; padding:9px 15px; border-radius:980px;
      font-size:14px; font-weight:600; white-space:nowrap}
.pill .dot{width:9px; height:9px; border-radius:50%; background:currentColor; flex:none}
.pill.good{background:rgba(52,199,89,.14); color:#1a7f43}
.pill.warn{background:rgba(255,149,0,.16); color:#a35b00}
.pill.bad {background:rgba(255,59,48,.14); color:#c02626}

/* ---------- ตัวเลขใหญ่ ---------- */
.kpis{display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:12px;
      margin-bottom:20px}
.kpi{background:var(--panel); border-radius:var(--r); box-shadow:var(--shadow); padding:16px 18px}
.kpi .n{font-size:34px; line-height:40px; font-weight:700; letter-spacing:-1px;
        font-variant-numeric:tabular-nums}
.kpi .k{font-size:13px; line-height:18px; color:var(--ink-3); margin-top:2px}
.kpi .s{font-size:12px; line-height:17px; color:var(--ink-3); margin-top:6px}
.kpi.hot .n{color:var(--red)} .kpi.mid .n{color:var(--orange)} .kpi.calm .n{color:var(--green)}

/* ---------- การ์ด ---------- */
.grid{display:grid; grid-template-columns:repeat(auto-fit,minmax(330px,1fr)); gap:14px}
.card{background:var(--panel); border-radius:var(--r); box-shadow:var(--shadow);
      overflow:hidden; margin-bottom:14px}
.card h2{font-size:13px; line-height:18px; font-weight:600; color:var(--ink-3);
         margin:0; padding:14px 18px 8px; letter-spacing:.2px}
.card.alert{background:linear-gradient(180deg,#fff8ec,#fff)}
.card.alert h2{color:#a35b00}
.row{display:flex; gap:12px; padding:11px 18px; align-items:flex-start;
     border-top:.5px solid var(--sep)}
.row:first-of-type{border-top:none}
.row .grow{flex:1; min-width:0}
.row .val{color:var(--ink-2); white-space:nowrap; font-variant-numeric:tabular-nums}
.name{font-weight:600}
.muted{color:var(--ink-3); font-size:13px; line-height:18px}
.mono{font-family:ui-monospace,Consolas,monospace; font-size:12.5px; line-height:18px;
      word-break:break-all}
.empty{padding:16px 18px; color:var(--ink-3)}

/* ---------- ชิ้นเล็ก ---------- */
.mark{width:22px; flex:none; text-align:center; font-size:15px; line-height:22px}
.tag{display:inline-block; font-size:11px; line-height:16px; padding:1px 8px; border-radius:980px;
     margin-left:7px; vertical-align:1px; font-weight:600}
.tag.quiet{background:rgba(142,142,147,.18); color:#5c5c60}
.tag.clash{background:rgba(255,59,48,.14); color:#c02626}
.dotline{display:flex; align-items:center; gap:8px}
.sdot{width:9px; height:9px; border-radius:50%; flex:none}
.ok .sdot{background:var(--green)} .no .sdot{background:var(--red)}
.ok .val{color:#1a7f43} .no .val{color:#c02626; font-weight:600}

/* ---------- แถบสัดส่วน ---------- */
.bar{display:flex; height:12px; border-radius:980px; overflow:hidden; margin:2px 18px 12px;
     background:rgba(120,120,128,.12)}
.bar i{display:block; height:100%}
.legend{display:flex; flex-wrap:wrap; gap:14px; padding:0 18px 12px; font-size:12.5px;
        color:var(--ink-2)}
.legend span{display:inline-flex; align-items:center; gap:6px}
.legend i{width:9px; height:9px; border-radius:3px; display:inline-block}

/* ---------- กราฟแผนประจำเดือน ---------- */
.mission{display:grid; grid-template-columns:minmax(120px,190px) 1fr auto; gap:10px 12px;
         align-items:center; padding:10px 18px 14px}
.mission .m-name{font-weight:600; font-size:14px}
.mission .m-track{height:18px; border-radius:980px; background:rgba(120,120,128,.14);
                  overflow:hidden}
.mission .m-fill{height:100%; border-radius:980px}
.mission .m-num{font-size:13px; color:var(--ink-2); white-space:nowrap;
                font-variant-numeric:tabular-nums}
.mission .m-none{color:var(--ink-3); font-size:12.5px}
.plan-head{display:flex; justify-content:flex-end; padding:0 18px 2px}
.plan-head .sum{font-size:13px; color:var(--ink-3); font-variant-numeric:tabular-nums}
.linkbtn{display:inline-block; font-size:12.5px; font-weight:600; text-decoration:none;
         padding:4px 12px; border-radius:980px; background:rgba(120,120,128,.14);
         color:var(--ink-2); float:right; margin-top:-3px}
.linkbtn:hover{background:rgba(120,120,128,.22)}
@media (max-width:560px){ .mission{grid-template-columns:1fr; gap:4px} }

@media (max-width:560px){
  body{padding:16px 12px 32px}
  h1{font-size:24px; line-height:30px}
  .kpi .n{font-size:28px; line-height:34px}
  .row{padding:10px 14px} .card h2{padding:12px 14px 6px}
  .bar,.legend{margin-left:14px; margin-right:14px; padding-left:0; padding-right:0}
}
"""

# เตือนเองเมื่อหน้านี้เก่าเกินหนึ่งวัน — ตัวตั้งเวลาอาจถูกปิดหรือเครื่องไม่ได้เปิดตอน 08:00
# ถ้าไม่มีตัวนี้ หน้าที่ค้างจะดูเหมือนข้อมูลสดทุกประการ ซึ่งอันตรายกว่าไม่มีหน้าเลย
_JS = """
(function(){
  var born = new Date(document.body.dataset.born);
  var hours = (Date.now() - born.getTime()) / 3600000;
  if (hours > 26) {
    var b = document.createElement('div');
    b.className = 'card alert';
    b.innerHTML = '<h2>ข้อมูลนี้เก่าแล้ว</h2><div class="row"><span class="mark">!</span>'
      + '<div class="grow">สร้างไว้เมื่อ ' + hours.toFixed(0) + ' ชั่วโมงก่อน '
      + 'แต่ควรสร้างใหม่ทุกวัน 08:00 — ตัวตั้งเวลาอาจไม่ทำงาน<div class="muted mono">'
      + 'powershell -Command "Get-ScheduledTaskInfo -TaskName PipelineStudio-Workboard"'
      + '</div></div></div>';
    document.querySelector('.page').insertBefore(b, document.querySelector('.kpis'));
  }
})();
"""

LANE_COLORS = {"post": "#0088ff", "คลิป/วิดีโอ": "#af52de", "ส่วนกลาง": "#ff9500",
               "อื่นๆ": "#8e8e93"}


def to_html(d: dict) -> str:
    def card(title, inner, tone="") -> str:
        return f'<section class="card {tone}"><h2>{title}</h2>{inner}</section>'

    def row(mark, main, value="") -> str:
        right = f'<div class="val">{value}</div>' if value else ""
        return f'<div class="row"><span class="mark">{mark}</span><div class="grow">{main}</div>{right}</div>'

    # ---------- ป้ายสถานะรวม ----------
    broken = not d["post_up"] or not d["clip_up"]
    if broken:
        pill, word = "bad", "ระบบมีปัญหา"
    elif d["problems"]:
        pill, word = "warn", f"ต้องลงมือ {len(d['problems'])} เรื่อง"
    else:
        pill, word = "good", "ทุกอย่างปกติ"

    # ---------- ตัวเลขใหญ่ ----------
    quiet_n = sum(1 for w in d["working"] if w["quiet"])
    wait_n = len(d["clip_waiting"])
    old_txt = f"เก่าสุด {_ago(d['dirty_oldest'])}" if d["dirty_oldest"] else "ไม่มีของค้าง"
    oldest_wait = min((w["since"] for w in d["clip_waiting"] if w["since"]), default=None)
    kpis = [
        ("hot" if d["dirty_total"] > 20 else "mid" if d["dirty_total"] else "calm",
         d["dirty_total"], "ไฟล์ค้างไม่ commit", old_txt),
        ("hot" if wait_n else "calm", wait_n, "คลิปรอคุณกดอนุมัติ",
         f"ค้างมา {_ago(oldest_wait)}" if oldest_wait else "ไม่มีค้าง"),
        ("calm" if d["working"] and not quiet_n else "mid", len(d["working"]),
         "แชทที่มีงานเปิด", f"เงียบนานแล้ว {quiet_n}" if quiet_n else "ขยับกันอยู่"),
        ("calm" if d["phones"] else "hot", len(d["phones"]), "มือถือที่ต่ออยู่",
         " · ".join(d["phones"]) or "งานโพสต์รันไม่ได้"),
    ]
    kpi_html = "".join(
        f'<div class="kpi {tone}"><div class="n">{n}</div><div class="k">{_esc(k)}</div>'
        f'<div class="s">{_esc(s)}</div></div>' for tone, n, k, s in kpis)

    # ---------- ต้องลงมือ ----------
    alert_html = ""
    if d["problems"]:
        inner = "".join(row("!", _esc(p)) for p in d["problems"])
        alert_html = card("ต้องลงมือ", inner, "alert")

    # ---------- งานที่จดไว้ ----------
    if d["todo"]:
        inner = "".join(
            row("○", f'{_esc(t["text"])}'
                     + (f'<span class="tag quiet">{_esc(t["who"])}</span>' if t.get("who") else ""))
            for t in d["todo"])
    else:
        inner = '<div class="empty">ยังไม่มีงานจดไว้</div>'
    todo_html = card(f"งานที่จดไว้ · {len(d['todo'])} ข้อ", inner)

    # ---------- แชทที่กำลังทำอยู่ ----------
    if d["working"]:
        parts = []
        for w in d["working"]:
            tags = ('<span class="tag quiet">เงียบนานแล้ว</span>' if w["quiet"] else "") \
                 + ('<span class="tag clash">ติดข้อพิพาท</span>' if w["clash"] else "")
            files = " · ".join(w["files"][:4]) or "ยังไม่ได้จับไฟล์ไหน"
            body = (f'<div class="name">{_esc(w["chat"])}{tags}</div>'
                    f'<div>{_esc(w["text"][:130] or "(ยังไม่มีคำสั่งชัดเจน)")}</div>'
                    f'<div class="muted mono">{_esc(files)}</div>')
            parts.append(row("👤" if not w["quiet"] else "💤", body, _ago(w["moved"])))
        inner = "".join(parts)
    else:
        inner = '<div class="empty">ไม่มีแชทไหนมีงานค้าง</div>'
    working_html = card("แชทที่กำลังทำอยู่", inner)

    # ---------- ของค้าง ----------
    lanes = sorted(d["dirty"].items(), key=lambda kv: -len(kv[1]))
    total = max(d["dirty_total"], 1)
    bar = "".join(f'<i style="width:{len(v) / total * 100:.1f}%;'
                  f'background:{LANE_COLORS.get(k, "#8e8e93")}"></i>' for k, v in lanes)
    legend = "".join(f'<span><i style="background:{LANE_COLORS.get(k, "#8e8e93")}"></i>'
                     f'{_esc(k)} {len(v)}</span>' for k, v in lanes)
    lane_rows = []
    for lane, items in lanes:
        newest = max((r["touched"] for r in items if r["touched"]), default=None)
        names = " · ".join(_esc(r["file"]) for r in items[:6])
        more = f" +อีก {len(items) - 6}" if len(items) > 6 else ""
        lane_rows.append(row(
            "•", f'<div class="name">{_esc(lane)} · {len(items)} ไฟล์</div>'
                 f'<div class="muted mono">{names}{more}</div>', _ago(newest)))
    inner = ((f'<div class="bar">{bar}</div><div class="legend">{legend}</div>'
              + "".join(lane_rows)) if lanes else '<div class="empty">สะอาด ไม่มีของค้าง</div>')
    dirty_html = card(
        f"ของค้างยังไม่ commit · {d['dirty_total']} ไฟล์"
        '<a class="linkbtn" href="dirty.html" target="_blank" rel="noreferrer">ดูทั้งหมด →</a>',
        inner)

    # ---------- แผนประจำเดือน (Master plan) ----------
    plan = d.get("plan") or {}
    plan_rows = plan.get("missions") or []
    tone = ["#0088ff", "#34c759", "#af52de", "#ff9500", "#5ac8fa", "#ff2d55"]
    bars = []
    # ห้ามตั้งชื่อตัวแปรนี้ว่า row — จะไปบังฟังก์ชัน row() ที่ประกาศไว้บนสุดของ to_html
    # แล้วการ์ด commit ด้านล่างจะพังด้วย TypeError (เจอจริง 20 ส.ค. 2026)
    for i, m in enumerate(plan_rows):
        target = int(m.get("target") or 0)
        done = int(m.get("done") or 0)
        if target > 0:
            pct = max(0.0, min(done / target * 100, 100.0))
            right = f"{done}/{target} · {pct:.0f}%"
            fill = (f'<div class="m-fill" style="width:{pct:.1f}%;'
                    f'background:{tone[i % len(tone)]}"></div>')
        else:
            right = '<span class="m-none">ยังไม่ตั้งเป้า</span>'
            fill = ""
        bars.append(f'<div class="m-name">{_esc(m.get("name", "?"))}</div>'
                    f'<div class="m-track">{fill}</div>'
                    f'<div class="m-num">{right}</div>')
    aimed = [r for r in plan_rows if int(r.get("target") or 0) > 0]
    if aimed:
        got = sum(min(int(r.get("done") or 0), int(r["target"])) for r in aimed)
        want = sum(int(r["target"]) for r in aimed)
        summary = f"รวม {got}/{want} · {got / want * 100:.0f}%"
    else:
        summary = "ยังไม่ได้ตั้งเป้าสักข้อ"
    plan_html = card(
        _esc(plan.get("title") or "แผนประจำเดือน"),
        (f'<div class="plan-head"><span class="sum">{_esc(summary)}</span></div>'
         f'<div class="mission">{"".join(bars)}</div>')
        if bars else '<div class="empty">ยังไม่มีแผน</div>')

    # ---------- ระบบ ----------
    checks = [
        ("เซิร์ฟเวอร์หน้าเว็บ 8866", "ปกติ" if d["post_up"] else "ต่อไม่ได้", d["post_up"]),
        ("เซิร์ฟเวอร์คลิป 8877", "ปกติ" if d["clip_up"] else "ต่อไม่ได้", d["clip_up"]),
        ("งานโพสต์กำลังรัน", ("ใช่" if d["post_running"] else "ไม่") if d["post_up"] else "—", True),
        ("งานคลิปที่ยังไม่จบ", str(d["clip_open"]) if d["clip_up"] else "—", True),
        ("รอคุณกดอนุมัติ", str(wait_n), wait_n == 0),
        ("ไฟล์ที่มีคนถืออยู่", str(len(d["claims"])), True),
        ("แก้อยู่โดยไม่ได้จอง", str(len(d["loose"])), not d["loose"]),
    ]
    inner = "".join(
        f'<div class="row {"ok" if good else "no"}"><span class="mark"></span>'
        f'<div class="grow dotline"><i class="sdot"></i>{_esc(label)}</div>'
        f'<div class="val">{_esc(value)}</div></div>' for label, value, good in checks)
    system_html = card("ระบบ", inner)

    # ---------- commit ----------
    parts = []
    for line in d["commits"][:7]:
        sha, _, msg = line.partition(" ")
        parts.append(row("", f'<span class="mono">{_esc(sha)}</span> {_esc(msg)}'))
    commits_html = card("commit ล่าสุด", "".join(parts) or '<div class="empty">ไม่มี</div>')

    return f"""<!doctype html>
<html lang="th"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>กระดานสรุปงาน — Pipeline Studio</title>
<style>{_CSS}</style></head>
<body data-born="{d['at'].isoformat()}">
<div class="page">
  <div class="top">
    <div>
      <h1>กระดานสรุปงาน</h1>
      <div class="sub">อัปเดตล่าสุด {d['at']:%d/%m/%Y %H:%M} น. · สร้างใหม่เองทุกวัน 08:00</div>
    </div>
    <div class="pill {pill}"><span class="dot"></span>{word}</div>
  </div>
  <div class="kpis">{kpi_html}</div>
  {plan_html}
  {alert_html}
  <div class="grid">
    <div>{todo_html}{system_html}</div>
    <div>{working_html}{dirty_html}{commits_html}</div>
  </div>
</div>
<script>{_JS}</script>
</body></html>"""
def to_dirty_html(d):
    """หน้าแยกสำหรับดูของค้างทั้งหมด

    บนกระดานหลักโชว์แค่ 6 ไฟล์แรกต่อสาย เพราะ 40+ ไฟล์จะกลบเรื่องอื่นจนหมด
    ใครอยากเห็นครบค่อยกดมาหน้านี้ — แยกหน้าดีกว่าให้หน้าหลักยาวเป็นหางว่าว
    """
    blocks = []
    for lane, items in sorted(d["dirty"].items(), key=lambda kv: -len(kv[1])):
        rows = []
        for r in sorted(items, key=lambda r: r["touched"] or datetime.min, reverse=True):
            tag = '<span class="tag quiet">ไฟล์ใหม่</span>' if r["new"] else ""
            rows.append('<div class="row"><span class="mark">.</span>'
                        '<div class="grow mono">' + _esc(r["file"]) + tag + '</div>'
                        '<div class="val">' + _esc(_ago(r["touched"])) + '</div></div>')
        blocks.append('<section class="card"><h2>' + _esc(lane) + ' &middot; '
                      + str(len(items)) + ' ไฟล์</h2>' + "".join(rows) + '</section>')

    head = ('<!doctype html><html lang="th"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>ของค้างยังไม่ commit — Pipeline Studio</title><style>'
            + _CSS + '</style></head><body><div class="page"><div class="top"><div>'
            '<h1>ของค้างยังไม่ commit</h1><div class="sub">รวม '
            + str(d["dirty_total"]) + ' ไฟล์ &middot; เก่าสุด ' + _ago(d["dirty_oldest"])
            + ' &middot; ข้อมูล ณ ' + format(d["at"], "%d/%m/%Y %H:%M")
            + ' น.</div></div><a class="pill warn" href="index.html" '
            'style="text-decoration:none">&larr; กลับกระดาน</a></div>')
    body = "".join(blocks) or ('<section class="card"><div class="empty">'
                               'สะอาด ไม่มีของค้าง</div></section>')
    return head + body + "</div></body></html>"



def render(quiet: bool = False) -> int:
    data = collect()
    OUT_HTML.parent.mkdir(parents=True, exist_ok=True)
    OUT_HTML.write_text(to_html(data), encoding="utf-8", newline="\n")
    OUT_DIRTY.write_text(to_dirty_html(data), encoding="utf-8", newline=chr(10))
    if not quiet:
        print(to_text(data))
        print("")
        print("หน้าเว็บ: http://localhost:8866/static/board/index.html")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="กระดานสรุปงานหน้าเดียว")
    sub = parser.add_subparsers(dest="command")

    p_show = sub.add_parser("show", help="สร้างใหม่แล้วแสดงผล (ค่าเริ่มต้น)")
    p_show.add_argument("--quiet", action="store_true", help="ไม่ต้องพิมพ์ลงจอ (ใช้ตอนรันอัตโนมัติ)")

    p_add = sub.add_parser("add", help="จดงานที่ต้องทำด้วยมือ")
    p_add.add_argument("text")
    p_add.add_argument("--who", default="")

    p_done = sub.add_parser("done", help="ปิดงานที่จดไว้ (ใส่เลขข้อจากกระดาน)")
    p_done.add_argument("number", type=int)

    p_m = sub.add_parser("mission", help="ดู/ตั้งเป้าแผนประจำเดือน")
    p_m.add_argument("action", choices=["list", "set"])
    p_m.add_argument("name", nargs="?", default="", help="ชื่อ mission (พิมพ์บางส่วนพอ)")
    p_m.add_argument("--target", type=int, default=None, help="เป้าของเดือนนี้")
    p_m.add_argument("--done", type=int, default=None, help="ทำไปแล้วเท่าไร")
    p_m.add_argument("--note", default=None)

    args = parser.parse_args(argv)
    if args.command == "add":
        return todo_add(args.text, args.who)
    if args.command == "done":
        return todo_done(args.number)
    if args.command == "mission":
        if args.action == "list":
            return mission_list()
        if not args.name:
            print("ต้องบอกชื่อ mission ด้วย เช่น: mission set Reels --target 20")
            return 2
        return mission_set(args.name, args.target, args.done, args.note)
    return render(quiet=getattr(args, "quiet", False))


if __name__ == "__main__":
    raise SystemExit(main())
