"""ชั้นเก็บผลวิเคราะห์กลุ่ม — แยกไฟล์ฐานออกจากฐานที่บอทกำลังเขียน

ทำไมต้องแยกไฟล์ (ตัดสิน 19 ส.ค. 2569):
  fb_posts.db ถูก Bot8/Bot9 เขียนอยู่ตลอด (WAL 4 MB ตอนสำรวจ) การไปเพิ่มตาราง
  หรือเขียนทับในไฟล์เดียวกันจะแย่ง write-lock กับตัวเก็บ และถ้าสคีมาเพี้ยน
  จะพาข้อมูลดิบพังไปด้วย → ผลวิเคราะห์ทั้งหมดอยู่ที่ data/fb_stats.db
  แล้ว ATTACH ฐานดิบเข้ามาแบบ read-only ชื่อ src (เปิด mode=ro จริง เขียนไม่ได้แน่นอน)

ทุกตารางในนี้ต้องตอบคำถามเดียวกันได้เสมอ: "ตัวเลขนี้มาจากกี่ใบ และเชื่อได้แค่ไหน"
จึงบังคับให้ทุกแถวที่เป็นข้อสรุปมี n_* และ status/confidence ติดมาด้วย
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC_DB = HERE / "data" / "fb_posts.db"      # ฐานดิบ — เปิดอ่านอย่างเดียวเท่านั้น
AN_DB = HERE / "data" / "fb_stats.db"       # ฐานผลวิเคราะห์ — ของเราเขียนได้

RULE_VER = "r1"          # เวอร์ชันกฎติดป้ายคอมเมนต์ เปลี่ยนเมื่อแก้ regex
SCHEMA_VER = 1

# ── เกณฑ์นัยสำคัญ (ประกาศไว้ที่เดียว ห้ามฝังตัวเลขในโค้ดที่อื่น) ────────────
MIN_MASS = 8        # โพสต์แมสขั้นต่ำต่อกลุ่ม ถึงจะยอมให้สรุป "สูตรโพสต์แมส"
MIN_POSTS = 60      # โพสต์รวมขั้นต่ำต่อกลุ่ม
P_MAX = 0.005       # Bonferroni ~0.05/10 ฟีเจอร์ที่ทดสอบพร้อมกัน
AUC_MIN = 0.10      # |AUC-0.5| ขั้นต่ำ — กันเคส n เยอะจน p เล็กแต่ผลจริงจิ๋ว
MIN_MINORITY = 0.05 # ฟีเจอร์ไบนารีต้องมีฝั่งน้อยอย่างน้อย 5% ไม่งั้นถือว่าคงที่
MIN_CMT = 30        # คอมเมนต์เนื้อหาจริงขั้นต่ำ ถึงจะยอมสรุป "ฐานลูกค้า"
MIN_CMT_COV = 0.20  # ต้องเก็บคอมเมนต์ได้ ≥20% ของที่ FB บอกว่ามี

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;

-- ─────────── ค. ตัวเลขที่คำนวณล่วงหน้า (หน้าเว็บห้ามคำนวณสด) ───────────
CREATE TABLE IF NOT EXISTS group_stats (
  gid            TEXT PRIMARY KEY,
  name           TEXT NOT NULL DEFAULT '',
  members        INTEGER,
  computed_at    INTEGER NOT NULL,
  input_hash     TEXT NOT NULL DEFAULT '',   -- แฮชข้อมูลดิบ ใช้บอกว่าสถิติล้าสมัยยัง
  n_posts        INTEGER NOT NULL DEFAULT 0,
  n_mass         INTEGER NOT NULL DEFAULT 0,
  n_normal       INTEGER NOT NULL DEFAULT 0,
  eng_p50 INTEGER, eng_p75 INTEGER, eng_p90 INTEGER, eng_p95 INTEGER, eng_max INTEGER,
  eng_zero_pct   REAL,
  core_p50 INTEGER, core_p90 INTEGER,        -- reactions+comments (ไม่พึ่ง shares)
  cap_pct REAL, cap_p50_len INTEGER,
  img_pct REAL, img_p50 INTEGER,
  authors_n INTEGER, author_once_pct REAL,
  first_post_at INTEGER, last_post_at INTEGER,
  hours_covered INTEGER, days_covered INTEGER,
  -- ง. ความน่าเชื่อถือของข้อมูลนำเข้า
  shares_pos_pct REAL,                       -- % โพสต์ที่ shares>0
  shares_trust   TEXT NOT NULL DEFAULT '',   -- ok / suspect (แชร์=0 เยอะผิดปกติ)
  cmt_expected INTEGER, cmt_got INTEGER, cmt_cov_pct REAL, cmt_posts_with INTEGER,
  cmt_content INTEGER,                       -- คอมเมนต์ที่ไม่ใช่แท็ก/ว่าง/สแปม
  -- ด่านตัดสินว่าสรุปได้ไหม
  ok_content INTEGER NOT NULL DEFAULT 0,
  ok_audience INTEGER NOT NULL DEFAULT 0,
  block_reason TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS group_hour (
  gid TEXT NOT NULL, hour INTEGER NOT NULL,
  n INTEGER NOT NULL, eng_p50 INTEGER, mass_n INTEGER,
  PRIMARY KEY (gid, hour)
);

-- ผลทดสอบฟีเจอร์รายตัว — SQL คำนวณให้หมด LLM ห้ามนับเอง
CREATE TABLE IF NOT EXISTS group_feature (
  gid TEXT NOT NULL, feat TEXT NOT NULL,
  kind TEXT NOT NULL DEFAULT 'num',          -- num / bin
  label TEXT NOT NULL DEFAULT '',
  n INTEGER, n_mass INTEGER, n_normal INTEGER,
  auc REAL, z REAL, p REAL,                  -- เทียบ is_mass (นิยามผู้ใช้)
  auc_core REAL,                             -- เทียบ top10% ของ reactions+comments
  med_mass REAL, med_normal REAL,
  status TEXT NOT NULL DEFAULT '',           -- pass/weak/reject/constant/blocked
  reason TEXT NOT NULL DEFAULT '',
  computed_at INTEGER NOT NULL,
  PRIMARY KEY (gid, feat)
);

-- ตารางแบ่งช่วงของฟีเจอร์ที่ผ่านด่าน (เอาไปโชว์เป็นตารางในบรีฟ/หน้าเว็บ)
CREATE TABLE IF NOT EXISTS feature_bucket (
  gid TEXT NOT NULL, feat TEXT NOT NULL, bucket TEXT NOT NULL, ord INTEGER NOT NULL,
  n INTEGER, eng_p50 INTEGER, mass_pct REAL, zero_pct REAL,
  PRIMARY KEY (gid, feat, bucket)
);

-- ─────────── ข. ป้ายกำกับรายชิ้น (กฎเติมก่อน แล้ว Claude แก้ทับ) ───────────
CREATE TABLE IF NOT EXISTS comment_label (
  comment_id TEXT PRIMARY KEY,
  gid TEXT NOT NULL, post_id TEXT NOT NULL,
  body_clean TEXT NOT NULL DEFAULT '',       -- ข้อความหลังตัดชื่อที่แท็กออก
  tag_names  TEXT NOT NULL DEFAULT '',       -- ชื่อที่ตัดออก (คั่นด้วย |)
  n_tags INTEGER NOT NULL DEFAULT 0,
  is_tagonly INTEGER NOT NULL DEFAULT 0,     -- แท็กล้วน ไม่มีเนื้อหา
  is_lowinfo INTEGER NOT NULL DEFAULT 0,     -- สั้น/ขานรับ/ว่าง
  rule_role TEXT NOT NULL DEFAULT 'unknown', -- customer/seller/spam/tagger/chat/unknown
  rule_hit  TEXT NOT NULL DEFAULT '',        -- คำที่ทำให้ตัดสินแบบนั้น (ตรวจย้อนได้)
  llm_role  TEXT NOT NULL DEFAULT '',        -- Claude แก้ทับเฉพาะที่กฎเดาผิด
  llm_note  TEXT NOT NULL DEFAULT '',
  rule_ver  TEXT NOT NULL DEFAULT '',
  labeled_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_cl_gid ON comment_label(gid, rule_role);

CREATE TABLE IF NOT EXISTS post_label (
  post_id TEXT NOT NULL, rev INTEGER NOT NULL DEFAULT 1,
  gid TEXT NOT NULL, topic TEXT NOT NULL DEFAULT '', angle TEXT NOT NULL DEFAULT '',
  note TEXT NOT NULL DEFAULT '', created_at INTEGER NOT NULL,
  PRIMARY KEY (post_id, rev)
);

-- ─────────── ก. คำวิเคราะห์ที่ Claude เขียนกลับมา ───────────
CREATE TABLE IF NOT EXISTS group_analysis (
  gid TEXT NOT NULL, rev INTEGER NOT NULL,
  created_at INTEGER NOT NULL,
  author TEXT NOT NULL DEFAULT 'claude-chat',
  input_hash TEXT NOT NULL DEFAULT '',       -- ต้องตรงกับ group_stats.input_hash ปัจจุบัน
  n_posts INTEGER, n_mass INTEGER, n_normal INTEGER, n_comments INTEGER,
  confidence TEXT NOT NULL DEFAULT 'none',   -- none/low/medium/high (ระบบกำหนด ไม่ใช่ LLM)
  verdict TEXT NOT NULL DEFAULT '',
  do_md TEXT NOT NULL DEFAULT '',
  dont_md TEXT NOT NULL DEFAULT '',
  audience_md TEXT NOT NULL DEFAULT '',
  caveats_md TEXT NOT NULL DEFAULT '',
  raw_md TEXT NOT NULL DEFAULT '',
  drift_note TEXT NOT NULL DEFAULT '',       -- ข้อมูลขยับไปเท่าไรระหว่างอ่านซองกับกดบันทึก
  PRIMARY KEY (gid, rev)
);

-- หลักฐานที่ผูกกับข้อสรุป — ใส่ id มั่วไม่ได้ ตรวจตอนบันทึก
CREATE TABLE IF NOT EXISTS analysis_evidence (
  gid TEXT NOT NULL, rev INTEGER NOT NULL,
  section TEXT NOT NULL,                     -- do/dont/audience/caveat
  kind TEXT NOT NULL,                        -- post/comment
  ref_id TEXT NOT NULL,
  note TEXT NOT NULL DEFAULT '',
  PRIMARY KEY (gid, rev, section, kind, ref_id)
);

CREATE TABLE IF NOT EXISTS brief_export (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  gid TEXT NOT NULL, created_at INTEGER NOT NULL,
  input_hash TEXT NOT NULL DEFAULT '',
  n_chars INTEGER, n_tokens_est INTEGER, path TEXT NOT NULL DEFAULT '',
  manifest TEXT NOT NULL DEFAULT '{}'        -- JSON: {"P1": post_id, "C3": comment_id}
);
CREATE INDEX IF NOT EXISTS ix_be_gid ON brief_export(gid, created_at DESC);
"""


def connect(write: bool = True) -> sqlite3.Connection:
    """เปิดฐานผลวิเคราะห์ แล้ว ATTACH ฐานดิบเข้ามาแบบอ่านอย่างเดียว (alias = src)"""
    AN_DB.parent.mkdir(parents=True, exist_ok=True)
    if not SRC_DB.exists():
        raise SystemExit(f"ไม่พบฐานดิบ: {SRC_DB}")
    uri = f"file:{AN_DB.as_posix()}" + ("" if write else "?mode=ro")
    conn = sqlite3.connect(uri, uri=True, timeout=30)
    conn.row_factory = sqlite3.Row
    if write:
        conn.executescript(SCHEMA)
        # CREATE TABLE IF NOT EXISTS ไม่เติมคอลัมน์ที่เพิ่มทีหลังให้ ต้องไล่เติมเอง
        for tbl, col, ddl in (("group_analysis", "drift_note", "TEXT NOT NULL DEFAULT ''"),):
            have = {r["name"] for r in conn.execute(f"PRAGMA table_info({tbl})")}
            if col not in have:
                conn.execute(f"ALTER TABLE {tbl} ADD COLUMN {col} {ddl}")
        conn.commit()
    conn.execute("ATTACH ? AS src", ("file:///" + SRC_DB.as_posix() + "?mode=ro",))
    # ถ้า ATTACH แล้วอ่านไม่ได้ ต้องดังทันที ห้ามให้เงียบแล้วไปได้บรีฟเปล่า
    conn.execute("SELECT count(*) FROM src.fb_post").fetchone()
    return conn


def input_hash(conn: sqlite3.Connection, gid: str) -> str:
    """ลายนิ้วมือของข้อมูลดิบกลุ่มนี้ — เปลี่ยนเมื่อไรแปลว่าบทวิเคราะห์เก่าล้าสมัย

    ใช้ (จำนวนโพสต์, ผลรวม engagement, เวลาเก็บล่าสุด, จำนวนคอมเมนต์) ซึ่งขยับทุกครั้ง
    ที่บอทเก็บเพิ่ม — ไม่ต้องอ่าน caption ทั้งกลุ่มมาแฮชให้ช้า
    """
    r = conn.execute("""
        SELECT COUNT(*) n, COALESCE(SUM(engagement),0) e, COALESCE(MAX(collected_at),0) t,
               (SELECT COUNT(*) FROM src.fb_comment c JOIN src.fb_post p2
                  ON p2.post_id=c.post_id WHERE p2.gid=:g) cm
        FROM src.fb_post WHERE gid=:g
    """, {"g": gid}).fetchone()
    raw = f"{gid}|{r['n']}|{r['e']}|{r['t']}|{r['cm']}|{SCHEMA_VER}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def confidence_of(row) -> str:
    """ระดับความเชื่อถือ — ตัดสินจากจำนวนตัวอย่างล้วนๆ ไม่เกี่ยวกับความมั่นใจของ LLM"""
    if not row["ok_content"]:
        return "none"
    if row["n_mass"] >= 40 and row["n_posts"] >= 300:
        return "high"
    if row["n_mass"] >= 15:
        return "medium"
    return "low"


def save_analysis(gid: str, payload: dict) -> int:
    """เขียนบทวิเคราะห์ที่ Claude ร่างในแชทกลับเข้าฐาน — คืนเลข rev ที่บันทึก

    payload: {verdict, do_md, dont_md, audience_md, caveats_md, raw_md, author,
              evidence: [{section, kind, ref_id, note}, ...]}

    ด่านที่ต้องผ่านก่อนเขียน (ทั้งหมดออกแบบมากันบทวิเคราะห์ลอย):
      1. ต้องมีสถิติของกลุ่มนี้อยู่ก่อน
      2. input_hash ต้องยังตรง — ถ้าบอทเก็บเพิ่มหลังสร้างบรีฟ ให้ปฏิเสธ
      3. หลักฐานทุกชิ้นต้องเป็น id ที่มีจริงและอยู่ในกลุ่มนี้
      4. confidence ระบบคำนวณเอง ห้าม LLM กรอก
      5. ถ้ากลุ่มไม่ผ่านด่าน ok_audience ห้ามบันทึก audience_md
    """
    conn = connect(write=True)
    try:
        row = conn.execute("SELECT * FROM group_stats WHERE gid=?", (gid,)).fetchone()
        if row is None:
            raise SystemExit(f"ยังไม่มีสถิติของกลุ่ม {gid} — สั่ง fb_stat_layer.py ก่อน")
        cur = input_hash(conn, gid)
        # บอทเก็บเพิ่มตลอดเวลา ถ้าปฏิเสธทุกครั้งที่แฮชขยับ จะบันทึกอะไรไม่ได้เลย
        # จึงวัด "ขยับไปเท่าไร" แทน: เปลี่ยนน้อย → บันทึกได้แต่ติดหมายเหตุ
        #                            เปลี่ยนมากพอจะทำให้ข้อสรุปเปลี่ยน → ปฏิเสธ
        drift = ""
        if cur != row["input_hash"]:
            now_ = conn.execute("""
                SELECT COUNT(*) n, COALESCE(SUM(is_mass),0) m,
                       (SELECT COUNT(*) FROM src.fb_comment c JOIN src.fb_post p2
                          ON p2.post_id=c.post_id WHERE p2.gid=:g) cm
                FROM src.fb_post WHERE gid=:g""", {"g": gid}).fetchone()
            dp = (now_["n"] - row["n_posts"]) / max(row["n_posts"], 1)
            dc = (now_["cm"] - (row["cmt_got"] or 0)) / max(row["cmt_got"] or 1, 1)
            if dp > 0.05 or now_["m"] != row["n_mass"] or dc > 0.25:
                raise SystemExit(
                    f"ข้อมูลดิบเปลี่ยนมากเกินรับได้ระหว่างอ่านซองกับกดบันทึก "
                    f"(โพสต์ {row['n_posts']}→{now_['n']} · แมส {row['n_mass']}→{now_['m']} "
                    f"· คอมเมนต์ {row['cmt_got']}→{now_['cm']}) — "
                    "สร้างซองใหม่แล้ววิเคราะห์ซ้ำ ห้ามบันทึกผลที่อ่านจากข้อมูลเก่า")
            drift = (f"ระหว่างวิเคราะห์ บอทเก็บเพิ่ม: โพสต์ {row['n_posts']}→{now_['n']} "
                     f"· คอมเมนต์ {row['cmt_got']}→{now_['cm']} (อยู่ในเกณฑ์ที่ยอมรับ)")
        if payload.get("audience_md") and not row["ok_audience"]:
            raise SystemExit(
                f"กลุ่มนี้ยังวิเคราะห์ฐานลูกค้าไม่ได้ ({row['block_reason']}) — "
                "ห้ามบันทึก audience_md")
        ev = payload.get("evidence") or []
        for e in ev:
            if e["kind"] == "post":
                ok = conn.execute("SELECT 1 FROM src.fb_post WHERE post_id=? AND gid=?",
                                  (e["ref_id"], gid)).fetchone()
            else:
                ok = conn.execute(
                    "SELECT 1 FROM src.fb_comment c JOIN src.fb_post p ON p.post_id=c.post_id "
                    "WHERE c.comment_id=? AND p.gid=?", (e["ref_id"], gid)).fetchone()
            if not ok:
                raise SystemExit(f"หลักฐานไม่ถูกต้อง: {e['kind']} {e['ref_id']} ไม่มีในกลุ่ม {gid}")

        rev = conn.execute("SELECT COALESCE(MAX(rev),0)+1 FROM group_analysis WHERE gid=?",
                           (gid,)).fetchone()[0]
        conn.execute("""
            INSERT INTO group_analysis (gid,rev,created_at,author,input_hash,
                n_posts,n_mass,n_normal,n_comments,confidence,
                verdict,do_md,dont_md,audience_md,caveats_md,raw_md,drift_note)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (gid, rev, int(time.time()), payload.get("author", "claude-chat"), cur,
              row["n_posts"], row["n_mass"], row["n_normal"], row["cmt_got"],
              confidence_of(row), payload.get("verdict", ""), payload.get("do_md", ""),
              payload.get("dont_md", ""), payload.get("audience_md", ""),
              payload.get("caveats_md", ""), payload.get("raw_md", ""), drift))
        for e in ev:
            conn.execute("""INSERT OR REPLACE INTO analysis_evidence
                (gid,rev,section,kind,ref_id,note) VALUES (?,?,?,?,?,?)""",
                         (gid, rev, e.get("section", "do"), e["kind"], e["ref_id"],
                          e.get("note", "")))
        conn.commit()
        return rev
    finally:
        conn.close()


def main() -> int:
    import sys
    if len(sys.argv) > 2 and sys.argv[1] == "--save":
        gid = sys.argv[2]
        payload = json.loads(Path(sys.argv[3]).read_text(encoding="utf-8"))
        print(f"บันทึกแล้ว rev={save_analysis(gid, payload)}")
        return 0
    conn = connect(write=True)
    print(f"ฐานผลวิเคราะห์พร้อม: {AN_DB}")
    for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY 1"):
        print("  -", r[0])
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
