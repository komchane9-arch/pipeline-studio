"""รับผลวิเคราะห์กลับจากแชทวิเคราะห์ → ตรวจ → เก็บลงฐาน

ด่านตรวจคือหัวใจ (สเปค ultracode 19 ส.ค. เลือกแบบ evidence-first เพราะเหตุนี้):
  1. รหัสหลักฐาน (P/T/C) ต้องมีจริงในซองใบนั้น — อ้างมั่ว = ปฏิเสธทั้งไฟล์
  2. metric_key ต้องมีในเมนูตัวเลข — ชี้ผิด = ปฏิเสธ
  3. ข้อความห้ามมีตัวเลขที่ดูเหมือนสถิติ — ระบบเป็นคนเติมเอง
  4. verdict = cannot_say ก็รับได้ (บอกว่าไม่รู้ ดีกว่าเดา)

**เก็บลงไฟล์ฐานคนละอันกับข้อมูลดิบ** (data/fbx.db) เพราะ fb_posts.db มีบอท
2 ตัวเขียนอยู่ตลอด การเขียนซ้อนเสี่ยงล็อกและทำ WAL บวม

รัน:  python fbx_apply.py --gid <gid>          (อ่าน <gid>.result.json)
      python fbx_apply.py --all                (ทุกไฟล์ผลที่ยังไม่ได้เก็บ)
      python fbx_apply.py --show <gid>         (ดูผลที่เก็บแล้ว)
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

import fb_mass_finder as mf

FBX_DB = mf.DATA_DIR / "fbx.db"
SRC_DB = mf.DATA_DIR / "fb_posts.db"
BRIEF_DIR = Path(r"G:\My Drive\pipeline studio\Post\1.Group facebook")

SECTIONS = ("do", "dont", "audience", "timing", "warning")

SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS fbx_run (
  run_id INTEGER PRIMARY KEY AUTOINCREMENT,
  gid TEXT NOT NULL, name TEXT NOT NULL DEFAULT '',
  created_at INTEGER NOT NULL DEFAULT (unixepoch()),
  verdict TEXT NOT NULL, cannot_say_why TEXT NOT NULL DEFAULT '',
  gate TEXT NOT NULL DEFAULT '', mass_n INTEGER,
  status TEXT NOT NULL DEFAULT 'active');
CREATE TABLE IF NOT EXISTS fbx_claim (
  claim_id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id INTEGER NOT NULL REFERENCES fbx_run(run_id) ON DELETE CASCADE,
  seq INTEGER, section TEXT NOT NULL, headline TEXT NOT NULL,
  detail TEXT NOT NULL DEFAULT '',
  metric_key TEXT NOT NULL DEFAULT '',
  metric_text TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS fbx_evidence (
  claim_id INTEGER NOT NULL REFERENCES fbx_claim(claim_id) ON DELETE CASCADE,
  code TEXT NOT NULL, kind TEXT NOT NULL, ref_id TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ix_run_gid ON fbx_run(gid, created_at DESC);
"""

# ตัวเลขที่ "ดูเหมือนสถิติ" — ห้ามให้ผู้วิเคราะห์พิมพ์เอง (ต้องมาจาก metric_key)
_STAT_NUM = re.compile(r"\d+(?:\.\d+)?\s*%|\b\d{2,}\s*(?:โพสต์|ครั้ง|คน|เท่า)")


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(FBX_DB, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def load_manifest(gid: str) -> dict:
    path = BRIEF_DIR / f"{gid}.manifest.json"
    if not path.is_file():
        raise SystemExit(f"ไม่พบ {path} — สร้างซองด้วย fbx_brief.py ก่อน")
    return json.loads(path.read_text(encoding="utf-8"))


def metric_text(key: str, metrics: dict) -> str:
    """แปลง metric_key เป็นข้อความ — ระบบเป็นคนเขียนตัวเลข ไม่ใช่ผู้วิเคราะห์"""
    m = metrics.get(key)
    if m is None:
        raise ValueError(f"metric_key '{key}' ไม่มีในเมนูตัวเลขของซองนี้")
    return f"{m['pct_mass']}% เป็นแมส ({m['mass']} จาก {m['n']} โพสต์)"


def validate(result: dict, manifest: dict) -> list[str]:
    """ตรวจทุกข้ออ้าง — คืนรายการปัญหา (ว่าง = ผ่าน)"""
    problems: list[str] = []
    codes = manifest["manifest"]
    metrics = manifest["metrics"]

    if result.get("gid") != manifest["gid"]:
        problems.append(f"gid ไม่ตรง: ในไฟล์ผล {result.get('gid')} "
                        f"· ในซอง {manifest['gid']}")
    verdict = result.get("verdict")
    if verdict not in ("ok", "cannot_say"):
        problems.append(f"verdict ต้องเป็น ok หรือ cannot_say (ได้ '{verdict}')")
    if verdict == "cannot_say":
        if not (result.get("cannot_say_why") or "").strip():
            problems.append("ตอบ cannot_say ต้องบอกเหตุผลใน cannot_say_why")
        return problems

    claims = result.get("claims") or []
    if not claims:
        problems.append("verdict=ok แต่ไม่มี claims เลย")
    for i, c in enumerate(claims, 1):
        where = f"claim #{i} ({c.get('headline', '')[:30]})"
        if c.get("section") not in SECTIONS:
            problems.append(f"{where}: section '{c.get('section')}' ไม่ถูกต้อง "
                            f"(ต้องเป็น {'/'.join(SECTIONS)})")
        if not (c.get("headline") or "").strip():
            problems.append(f"{where}: ไม่มี headline")
        text = f"{c.get('headline', '')} {c.get('detail', '')}"
        hit = _STAT_NUM.search(text)
        if hit:
            problems.append(f"{where}: มีตัวเลขสถิติในข้อความ ('{hit.group()}') "
                            "— ต้องใช้ metric_key แทน ระบบจะเติมให้เอง")
        key = (c.get("metric_key") or "").strip()
        if key and key not in metrics:
            problems.append(f"{where}: metric_key '{key}' ไม่มีในเมนูตัวเลข")
        ev = c.get("evidence") or []
        bad = [e for e in ev if e not in codes]
        if bad:
            problems.append(f"{where}: อ้างหลักฐานที่ไม่มีในซอง {bad}")
        if not ev and not key:
            problems.append(f"{where}: ต้องมี evidence อย่างน้อย 1 รายการ "
                            "หรือ metric_key")
    return problems


def apply_result(gid: str, conn: sqlite3.Connection) -> bool:
    path = BRIEF_DIR / f"{gid}.result.json"
    if not path.is_file():
        print(f"⏭  {gid}: ยังไม่มีไฟล์ผล ({path.name})")
        return False
    try:
        result = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as error:
        print(f"❌ {gid}: อ่าน JSON ไม่ได้ — {error}")
        return False

    manifest = load_manifest(gid)
    problems = validate(result, manifest)
    if problems:
        print(f"❌ {gid}: ปฏิเสธ {len(problems)} ข้อ — ไม่บันทึกอะไรเลย")
        for p in problems:
            print(f"     · {p}")
        return False

    conn.execute("UPDATE fbx_run SET status='replaced' WHERE gid=? AND status='active'",
                 (gid,))
    cur = conn.execute("""INSERT INTO fbx_run (gid, name, verdict, cannot_say_why,
                          gate, mass_n) VALUES (?,?,?,?,?,?)""",
                       (gid, manifest.get("name", ""), result["verdict"],
                        result.get("cannot_say_why", ""), manifest.get("gate", ""),
                        manifest.get("mass_n")))
    run_id = cur.lastrowid
    codes, metrics = manifest["manifest"], manifest["metrics"]
    n_claims = n_ev = 0
    for seq, c in enumerate(result.get("claims") or [], 1):
        key = (c.get("metric_key") or "").strip()
        text = metric_text(key, metrics) if key else ""
        cc = conn.execute("""INSERT INTO fbx_claim (run_id, seq, section, headline,
                             detail, metric_key, metric_text) VALUES (?,?,?,?,?,?,?)""",
                          (run_id, seq, c["section"], c["headline"],
                           c.get("detail", ""), key, text))
        n_claims += 1
        for code in (c.get("evidence") or []):
            kind = "comment" if code.startswith("C") else "post"
            conn.execute("""INSERT INTO fbx_evidence (claim_id, code, kind, ref_id)
                            VALUES (?,?,?,?)""",
                         (cc.lastrowid, code, kind, codes[code]))
            n_ev += 1
    conn.commit()
    print(f"✅ {gid} ({manifest.get('name','')[:30]}): บันทึก {n_claims} ข้อสรุป "
          f"· หลักฐาน {n_ev} รายการ · verdict={result['verdict']}")
    return True


def show(gid: str, conn: sqlite3.Connection) -> None:
    run = conn.execute("""SELECT * FROM fbx_run WHERE gid=? AND status='active'
                          ORDER BY run_id DESC LIMIT 1""", (gid,)).fetchone()
    if run is None:
        print(f"ยังไม่มีผลวิเคราะห์ของ {gid}")
        return
    src = sqlite3.connect(f"file:{SRC_DB}?mode=ro", uri=True)
    src.row_factory = sqlite3.Row
    print(f"\n{'='*72}\n  {run['name']}  ({run['gid']})")
    print(f"  วิเคราะห์เมื่อ {datetime.fromtimestamp(run['created_at']):%d/%m/%Y %H:%M}"
          f" · ความเชื่อมั่น {run['gate']} · โพสต์แมส {run['mass_n']}")
    print("=" * 72)
    if run["verdict"] == "cannot_say":
        print(f"  ⛔ สรุปไม่ได้: {run['cannot_say_why']}")
        return
    label = {"do": "✅ ควรทำ", "dont": "❌ อย่าทำ", "audience": "👥 ฐานลูกค้า",
             "timing": "🕐 เวลา", "warning": "⚠️ ข้อควรระวัง"}
    for sec in SECTIONS:
        rows = conn.execute("""SELECT * FROM fbx_claim WHERE run_id=? AND section=?
                               ORDER BY seq""", (run["run_id"], sec)).fetchall()
        if not rows:
            continue
        print(f"\n{label[sec]}")
        for r in rows:
            extra = f"  [{r['metric_text']}]" if r["metric_text"] else ""
            print(f"  • {r['headline']}{extra}")
            if r["detail"]:
                print(f"      {r['detail'][:150]}")
            ev = conn.execute("""SELECT code, kind, ref_id FROM fbx_evidence
                                 WHERE claim_id=?""", (r["claim_id"],)).fetchall()
            for e in ev[:3]:
                if e["kind"] == "post":
                    p = src.execute("SELECT url, substr(caption,1,60) c, engagement "
                                    "FROM fb_post WHERE post_id=?",
                                    (e["ref_id"],)).fetchone()
                    if p:
                        print(f"      ↳ {e['code']} eng {p['engagement']:,} «{p['c']}»")
                else:
                    m = src.execute("SELECT author, substr(body,1,60) b FROM fb_comment "
                                    "WHERE comment_id=?", (e["ref_id"],)).fetchone()
                    if m:
                        print(f"      ↳ {e['code']} {m['author'][:18]}: «{m['b']}»")


def main() -> int:
    args = sys.argv[1:]
    conn = connect()
    if "--show" in args:
        show(args[args.index("--show") + 1], conn)
        return 0
    if "--all" in args:
        done = 0
        for path in sorted(BRIEF_DIR.glob("*.result.json")):
            gid = path.name.replace(".result.json", "")
            done += 1 if apply_result(gid, conn) else 0
        print(f"\nบันทึกสำเร็จ {done} กลุ่ม")
        return 0
    if "--gid" in args:
        ok = apply_result(args[args.index("--gid") + 1], conn)
        return 0 if ok else 1
    print(__doc__)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
