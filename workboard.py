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
OUT_HTML = BASE_DIR / "web" / "workboard.html"
TODO_FILE = studio_shared.DATA_DIR / "todo.json"

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


def to_html(d: dict) -> str:
    def card(title, body, tone="") -> str:
        return f'<section class="card {tone}"><h2>{title}</h2>{body}</section>'

    problems = "".join(f"<li>{_esc(p)}</li>" for p in d["problems"])
    problems_html = (f"<ul class='warn'>{problems}</ul>" if problems
                     else "<p class='ok'>ไม่มีอะไรค้างที่ต้องรีบ</p>")

    todo_html = "".join(
        f"<li>{_esc(t['text'])}" + (f" <span class='who'>{_esc(t['who'])}</span>" if t.get("who") else "") + "</li>"
        for t in d["todo"]) or "<li class='muted'>ยังไม่มีงานจดไว้</li>"

    rows = []
    for w in d["working"]:
        files = ", ".join(w["files"][:5]) or "ยังไม่ได้จับไฟล์ไหน"
        badge = "<span class='badge quiet'>เงียบนานแล้ว</span>" if w["quiet"] else ""
        badge += "<span class='badge clash'>ติดข้อพิพาท</span>" if w["clash"] else ""
        rows.append(
            f"<tr><td><b>{_esc(w['chat'])}</b>{badge}<div class='muted'>{_esc(w['session'])}</div></td>"
            f"<td>{_esc(w['text'][:160] or '(ยังไม่มีคำสั่งชัดเจน)')}</td>"
            f"<td class='mono'>{_esc(files)}</td>"
            f"<td class='nowrap'>{_esc(_ago(w['moved']))}</td></tr>")
    working_html = ("<table><thead><tr><th>แชท</th><th>ถูกสั่งให้ทำ</th><th>ไฟล์</th>"
                    "<th>ขยับล่าสุด</th></tr></thead><tbody>"
                    + ("".join(rows) or "<tr><td colspan=4 class='muted'>ไม่มีแชทไหนมีงานค้าง</td></tr>")
                    + "</tbody></table>")

    lanes = []
    for lane, items in sorted(d["dirty"].items(), key=lambda kv: -len(kv[1])):
        newest = max((r["touched"] for r in items if r["touched"]), default=None)
        names = " · ".join(_esc(r["file"]) for r in items[:8])
        more = f" <span class='muted'>+อีก {len(items) - 8}</span>" if len(items) > 8 else ""
        lanes.append(f"<tr><td><b>{_esc(lane)}</b></td><td class='nowrap'>{len(items)} ไฟล์</td>"
                     f"<td class='nowrap'>{_esc(_ago(newest))}</td>"
                     f"<td class='mono small'>{names}{more}</td></tr>")
    dirty_html = (f"<p>รวม <b>{d['dirty_total']}</b> ไฟล์</p><table><thead><tr><th>สาย</th>"
                  "<th>จำนวน</th><th>ล่าสุด</th><th>ไฟล์</th></tr></thead><tbody>"
                  + ("".join(lanes) or "<tr><td colspan=4 class='muted'>สะอาด</td></tr>")
                  + "</tbody></table>")

    sys_rows = [
        ("เว็บ 8866", "ปกติ" if d["post_up"] else "ต่อไม่ได้", d["post_up"]),
        ("คลิป 8877", "ปกติ" if d["clip_up"] else "ต่อไม่ได้", d["clip_up"]),
        ("โพสต์กำลังรัน", ("ใช่" if d["post_running"] else "ไม่") if d["post_up"] else "-", True),
        ("งานคลิปยังไม่จบ", str(d["clip_open"]) if d["clip_up"] else "-", True),
        ("รอคุณกดอนุมัติ", str(len(d["clip_waiting"])), not d["clip_waiting"]),
        ("มือถือต่ออยู่", ", ".join(d["phones"]) or "ไม่มี", bool(d["phones"])),
        ("ไฟล์ที่มีคนถือ", str(len(d["claims"])), True),
        ("แก้โดยไม่จอง", str(len(d["loose"])), not d["loose"]),
    ]
    sys_html = "<table><tbody>" + "".join(
        f"<tr><td>{_esc(k)}</td><td class='{'ok' if good else 'bad'}'>{_esc(v)}</td></tr>"
        for k, v, good in sys_rows) + "</tbody></table>"

    commits_html = "<ul class='mono small'>" + "".join(
        f"<li>{_esc(c)}</li>" for c in d["commits"][:8]) + "</ul>"

    return f"""<!doctype html>
<html lang="th"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>กระดานสรุปงาน — Pipeline Studio</title>
<style>
:root {{ --bg:#f6f7f9; --fg:#1b1d21; --card:#fff; --line:#e3e6ea; --muted:#6b7280;
         --ok:#1a7f43; --bad:#c02626; --warn:#fff6e5; --warnline:#e0a33a; }}
@media (prefers-color-scheme: dark) {{
  :root {{ --bg:#15171a; --fg:#e8eaed; --card:#1e2126; --line:#2f343b; --muted:#9aa3ad;
           --ok:#4ade80; --bad:#f87171; --warn:#33291a; --warnline:#b7791f; }} }}
* {{ box-sizing:border-box }}
body {{ margin:0; padding:18px; background:var(--bg); color:var(--fg);
        font:15px/1.6 "Segoe UI",system-ui,sans-serif; }}
header {{ max-width:1100px; margin:0 auto 16px; }}
h1 {{ font-size:21px; margin:0 0 4px; }}
.stamp {{ color:var(--muted); font-size:13px; }}
.wrap {{ max-width:1100px; margin:0 auto; display:grid; gap:14px; }}
.card {{ background:var(--card); border:1px solid var(--line); border-radius:12px; padding:14px 16px; }}
.card h2 {{ font-size:15px; margin:0 0 10px; }}
.card.alert {{ background:var(--warn); border-color:var(--warnline); }}
table {{ width:100%; border-collapse:collapse; }}
th,td {{ text-align:left; padding:7px 8px; border-bottom:1px solid var(--line); vertical-align:top; }}
th {{ color:var(--muted); font-weight:600; font-size:13px; }}
tr:last-child td {{ border-bottom:0 }}
ul {{ margin:0; padding-left:20px }}
ul.warn li {{ margin:4px 0 }}
.mono {{ font-family:Consolas,monospace; font-size:12.5px }}
.small {{ font-size:12px }}
.muted {{ color:var(--muted) }}
.ok {{ color:var(--ok) }} .bad {{ color:var(--bad); font-weight:600 }}
.nowrap {{ white-space:nowrap }}
.badge {{ font-size:11px; padding:1px 6px; border-radius:6px; margin-left:6px;
          border:1px solid var(--warnline); background:var(--warn) }}
.who {{ color:var(--muted); font-size:12px }}
@media (max-width:640px) {{ .mono {{ font-size:11px }} body {{ padding:10px }} }}
</style></head>
<body>
<header>
  <h1>กระดานสรุปงาน</h1>
  <div class="stamp">อัปเดตล่าสุด {d['at']:%d/%m/%Y %H:%M} น. · อัปเดตเองทุกวัน 08:00</div>
</header>
<div class="wrap">
  {card("ต้องลงมือ", problems_html, "alert" if d["problems"] else "")}
  {card("งานที่จดไว้", f"<ul>{todo_html}</ul>")}
  {card("แชทที่กำลังทำอยู่", working_html)}
  {card("ของค้างยังไม่ commit", dirty_html)}
  {card("ระบบ", sys_html)}
  {card("commit ล่าสุด", commits_html)}
</div>
</body></html>"""


def render(quiet: bool = False) -> int:
    data = collect()
    OUT_HTML.parent.mkdir(parents=True, exist_ok=True)
    OUT_HTML.write_text(to_html(data), encoding="utf-8", newline="\n")
    if not quiet:
        print(to_text(data))
        print("")
        print("หน้าเว็บ: http://localhost:8866/static/workboard.html")
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

    args = parser.parse_args(argv)
    if args.command == "add":
        return todo_add(args.text, args.who)
    if args.command == "done":
        return todo_done(args.number)
    return render(quiet=getattr(args, "quiet", False))


if __name__ == "__main__":
    raise SystemExit(main())
