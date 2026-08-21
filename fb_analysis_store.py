"""ที่เก็บผลวิเคราะห์ + ตัวล้างคอมเมนต์ — ต่อยอดจาก fb_posts_store.py

ทำไมต้องมีไฟล์นี้ (ตรวจแล้ว 19 ส.ค. 2569 ว่าฐานเดิมไม่มีอะไรรองรับเลย):
  ฐานเดิมเก็บได้แค่ "ของดิบ" + ตัวเลขที่คิดตอน insert (engagement, is_mass)
  ไม่มีที่ลงบทวิเคราะห์ ไม่มีที่ลงบทบาทคนคอมเมนต์ ไม่มี snapshot สถิติ

กติกาที่ฝังไว้ในตาราง (ไม่ใช่แค่เขียนในเอกสาร):
  * ทุก claim ต้องมีหลักฐานอย่างน้อย 1 ชิ้น และหลักฐานต้องเป็น post_id/comment_id
    ที่ "มีจริงในฐาน และอยู่ในกลุ่มเดียวกับบทวิเคราะห์" — บังคับด้วย TRIGGER
    ระดับฐานข้อมูล ใส่ id มั่วไม่เข้า (ตัวกัน LLM แต่งเรื่องด่านสุดท้าย)
  * ตัวเลขทุกตัวในบทวิเคราะห์ ระบบเติมเองจาก SQL — ห้ามรับตัวเลขจาก LLM
  * ระดับความเชื่อถือ (confidence) คำนวณจากขนาดตัวอย่างจริง ไม่ใช่ให้ LLM ประเมินตัวเอง
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
from pathlib import Path

DB_FILE = Path(r"C:\project\2.Auto gen Video\8.pipeline studio\data\fb_posts.db")

# เวอร์ชันกฎล้างคอมเมนต์ — เปลี่ยนกฎเมื่อไรต้องขยับเลข แล้ว enrich ใหม่ทั้งกอง
RULE_VER = 2

ANALYSIS_SCHEMA = """
-- ---------------------------------------------------------------- ซองข้อมูล
-- เก็บ "สิ่งที่ Claude ได้อ่าน" ไว้ทั้งดุ้น เพื่อให้ย้อนตรวจได้ว่าบทวิเคราะห์
-- มาจากข้อมูลชุดไหน และเพื่อแปลง handle (P1/C7) กลับเป็น id จริงตอนเขียนกลับ
CREATE TABLE IF NOT EXISTS analysis_brief (
  brief_id   INTEGER PRIMARY KEY AUTOINCREMENT,
  gid        TEXT NOT NULL REFERENCES fb_group(gid) ON DELETE CASCADE,
  brief_hash TEXT NOT NULL UNIQUE,     -- sha256 ของตัวซอง (8 ตัวแรกใช้เรียกในแชท)
  input_sig  TEXT NOT NULL,            -- ลายเซ็นข้อมูลนำเข้า ใช้ดูว่าล้าสมัยยัง
  created_at INTEGER NOT NULL DEFAULT (unixepoch()),
  n_post INTEGER NOT NULL, n_mass INTEGER NOT NULL,
  n_normal INTEGER NOT NULL, n_comment INTEGER NOT NULL,
  chars      INTEGER NOT NULL,         -- ขนาดซอง (ตัวอักษร) ไว้เทียบงบโทเคน
  manifest   TEXT NOT NULL,            -- JSON: {"P1":"post_id", "C3":"comment_id"}
  body       TEXT NOT NULL,            -- ตัวซอง markdown เต็ม
  gates      TEXT NOT NULL DEFAULT '{}' -- JSON: หมวดไหนเปิด/ปิด + เหตุผล
);
CREATE INDEX IF NOT EXISTS ix_brief_gid ON analysis_brief(gid, created_at DESC);

-- ---------------------------------------------------------------- รอบวิเคราะห์
CREATE TABLE IF NOT EXISTS analysis_run (
  run_id     INTEGER PRIMARY KEY AUTOINCREMENT,
  gid        TEXT NOT NULL REFERENCES fb_group(gid) ON DELETE CASCADE,
  brief_id   INTEGER NOT NULL REFERENCES analysis_brief(brief_id) ON DELETE CASCADE,
  created_at INTEGER NOT NULL DEFAULT (unixepoch()),
  analyst    TEXT NOT NULL DEFAULT 'claude-chat',
  input_sig  TEXT NOT NULL,
  n_post INTEGER NOT NULL, n_mass INTEGER NOT NULL, n_comment_usable INTEGER NOT NULL,
  -- ระบบคำนวณเอง: none/low/medium/high  (ห้ามให้ LLM กรอก)
  confidence TEXT NOT NULL,
  confidence_why TEXT NOT NULL DEFAULT '',
  status     TEXT NOT NULL DEFAULT 'active'   -- active/stale/replaced
);
CREATE INDEX IF NOT EXISTS ix_run_gid ON analysis_run(gid, created_at DESC);

-- ---------------------------------------------------------------- ข้อสรุปรายบรรทัด
CREATE TABLE IF NOT EXISTS analysis_claim (
  claim_id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id   INTEGER NOT NULL REFERENCES analysis_run(run_id) ON DELETE CASCADE,
  section  TEXT NOT NULL,   -- do / dont / audience / timing / warning
  ord      INTEGER NOT NULL DEFAULT 0,
  headline TEXT NOT NULL,
  detail   TEXT NOT NULL DEFAULT '',
  -- ตัวเลขประกอบ: ระบบเติมจาก SQL ตอน apply เท่านั้น (metric_key ชี้ไปที่แถวใน
  -- ตาราง contrast) ถ้า LLM ส่งตัวเลขมาเองจะถูกทิ้ง
  metric_key   TEXT NOT NULL DEFAULT '',
  metric_value TEXT NOT NULL DEFAULT '',
  n_evidence   INTEGER NOT NULL DEFAULT 0,
  CHECK (section IN ('do','dont','audience','timing','warning'))
);
CREATE INDEX IF NOT EXISTS ix_claim_run ON analysis_claim(run_id, section, ord);

-- ---------------------------------------------------------------- หลักฐาน
CREATE TABLE IF NOT EXISTS analysis_evidence (
  claim_id INTEGER NOT NULL REFERENCES analysis_claim(claim_id) ON DELETE CASCADE,
  kind     TEXT NOT NULL CHECK (kind IN ('post','comment')),
  ref_id   TEXT NOT NULL,
  note     TEXT NOT NULL DEFAULT '',
  PRIMARY KEY (claim_id, kind, ref_id)
);

-- ด่านสุดท้ายกันการอ้างหลักฐานลอย: id ต้องมีจริง และต้องอยู่ในกลุ่มเดียวกับ run
CREATE TRIGGER IF NOT EXISTS trg_evidence_post BEFORE INSERT ON analysis_evidence
WHEN NEW.kind = 'post'
BEGIN
  SELECT RAISE(ABORT, 'หลักฐานไม่ถูกต้อง: post_id นี้ไม่มีในกลุ่มที่วิเคราะห์')
  WHERE NOT EXISTS (
    SELECT 1 FROM fb_post p
      JOIN analysis_claim cl ON cl.claim_id = NEW.claim_id
      JOIN analysis_run  r  ON r.run_id     = cl.run_id
     WHERE p.post_id = NEW.ref_id AND p.gid = r.gid);
END;

CREATE TRIGGER IF NOT EXISTS trg_evidence_comment BEFORE INSERT ON analysis_evidence
WHEN NEW.kind = 'comment'
BEGIN
  SELECT RAISE(ABORT, 'หลักฐานไม่ถูกต้อง: comment_id นี้ไม่มีในกลุ่มที่วิเคราะห์')
  WHERE NOT EXISTS (
    SELECT 1 FROM fb_comment c
      JOIN fb_post p ON p.post_id = c.post_id
      JOIN analysis_claim cl ON cl.claim_id = NEW.claim_id
      JOIN analysis_run  r  ON r.run_id     = cl.run_id
     WHERE c.comment_id = NEW.ref_id AND p.gid = r.gid);
END;

-- ---------------------------------------------------------------- คอมเมนต์ที่ล้างแล้ว
-- แยกตารางออกมา ไม่แตะ fb_comment ของตัวเก็บ (บอทกำลังเขียนอยู่ ห้ามชน)
CREATE TABLE IF NOT EXISTS comment_enrich (
  comment_id  TEXT PRIMARY KEY REFERENCES fb_comment(comment_id) ON DELETE CASCADE,
  body_clean  TEXT NOT NULL DEFAULT '',   -- ตัดชื่อที่แท็กออกแล้ว
  tag_names   TEXT NOT NULL DEFAULT '',   -- ชื่อที่ตัดออก (เก็บไว้ตรวจย้อน)
  is_tag_only INTEGER NOT NULL DEFAULT 0, -- แท็กเพื่อนล้วน ไม่มีเนื้อความ
  role        TEXT NOT NULL DEFAULT '',   -- ลูกค้า/คนขาย/แท็กเพื่อน/สแปม/ขานรับ/คุยเล่น/ว่าง
  role_rule   TEXT NOT NULL DEFAULT '',   -- กฎข้อไหนที่ทำให้ได้บทบาทนี้ (ตรวจย้อนได้)
  rule_ver    INTEGER NOT NULL DEFAULT 0,
  enriched_at INTEGER NOT NULL DEFAULT (unixepoch())
);
CREATE INDEX IF NOT EXISTS ix_enrich_role ON comment_enrich(role);

-- ---------------------------------------------------------------- snapshot สถิติ
-- หน้าเว็บต้องเร็ว: อ่านจากตารางนี้ ไม่คำนวณสดทุกครั้ง
CREATE TABLE IF NOT EXISTS group_stat (
  gid         TEXT PRIMARY KEY REFERENCES fb_group(gid) ON DELETE CASCADE,
  computed_at INTEGER NOT NULL DEFAULT (unixepoch()),
  input_sig   TEXT NOT NULL DEFAULT '',
  stat_json   TEXT NOT NULL,   -- ผลของ GROUP_STAT_SQL
  quality_json TEXT NOT NULL,  -- ผลของ GROUP_QUALITY_SQL (ความน่าเชื่อถือ)
  contrast_json TEXT NOT NULL, -- ผลของ CONTRAST_SQL (พร้อม post_id ตัวอย่าง)
  hour_json   TEXT NOT NULL DEFAULT '[]'
);
"""

# ------------------------------------------------------------------ เปิดฐาน

def connect(db_file: Path | str = DB_FILE, readonly: bool = False) -> sqlite3.Connection:
    """เปิดฐาน — โหมด readonly ใช้ตอนบอทกำลังเก็บอยู่ จะได้ไม่ไปล็อกทับ"""
    if readonly:
        conn = sqlite3.connect(f"file:{db_file}?mode=ro", uri=True, timeout=30)
    else:
        conn = sqlite3.connect(str(db_file), timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_schema(conn: sqlite3.Connection) -> None:
    """สร้างตารางวิเคราะห์ + วิวฟีเจอร์ (idempotent เรียกซ้ำได้)"""
    import fb_analysis_sql as q
    conn.executescript(ANALYSIS_SCHEMA)
    conn.executescript(q.FEATURES_SQL)
    conn.commit()


# ------------------------------------------------------------------ ล้างคอมเมนต์

# ชื่อคนที่ FB แท็กมาถูกยำติดกันไม่มีตัวคั่น (วัดจริง: 74.8% ของคอมเมนต์ในกลุ่มทดสอบ)
# กฎที่ใช้ — เรียงจากที่มั่นใจสุดไปน้อยสุด และบันทึกว่าใช้กฎไหนเสมอ
_RE_LATIN_NAME = re.compile(r"\b[A-Z][a-zA-Z]*(?:\s+[A-Z][a-zA-Z]*)+\b")
_RE_CAMEL_BLOB = re.compile(r"\b(?:[A-Z][a-z]+){2,}\b")   # RatchaneeWichLita
_RE_DECOR = re.compile(r"[\u0E2F\u0E46'\u2018\u2019\u02BC\u0E4F]|["
                       r"\U0001F300-\U0001FAFF\u2600-\u27BF]")
_THAI = re.compile(r"[\u0E00-\u0E7F]")

# คำที่บอกว่า "คนนี้ขายของ" — ต้องมีการชักชวนติดต่อ ไม่ใช่แค่พูดถึงราคา
_SELL = ("ทักแชท", "ทักมา", "ทักได้", "แชทมา", "สนใจทัก", "รวมส่ง", "ส่งฟรี",
         "ปล่อยต่อ", "ขายอยู่", "มีของ", "รับออเดอร์", "สั่งได้", "โอนแล้วส่ง",
         "ราคาส่ง", "เหลือตัวเดียว", "จองได้", "ขายค่ะ", "ขายครับ", "เผื่อสนใจ")
# คำที่บอกว่า "คนนี้อยากซื้อ/ถาม" — เป็นคำถามหรือแสดงความต้องการ
_BUY = ("ราคาเท่าไหร่", "ราคาเท่าไร", "เท่าไหร่", "กี่บาท", "ขายไหม", "ขายมั้ย",
        "ยังอยู่ไหม", "ยังอยู่มั้ย", "ยังมีไหม", "สนใจค่ะ", "สนใจครับ", "จองค่ะ",
        "จองครับ", "เอาค่ะ", "เอาครับ", "ขอราคา", "อินบล็อก", "ซื้อยังไง",
        "สั่งยังไง", "สาขาไหน", "ที่ไหน", "มีขายที่")
# สแปมที่ is_spam() เดิมจับไม่ได้ (วัดจริง recall 40% — พลาดพนัน+ใบขับขี่)
_SPAM = ("ปล่อยกู้", "เงินด่วน", "สร้างเครดิต", "ดอกเบี้ยต่ำ", "wy88", "ufa",
         "บาคาร่า", "สล็อต", "เว็บตรง", "แทงบอล", "ใบขับขี่", "พนัน", "ฝากถอนออโต้",
         "ทดลองเล่น", "เครดิตฟรี")
# ขานรับสั้นๆ ที่ไม่มีสัญญาณอะไรเลย (โพสต์ "ใครยังเห็นกลุ่มบ้าง" มี 45 อันแบบนี้)
_ACK = ("เห็น", "อยู่", "มา", "ครับ", "ค่ะ", "จ้า", "555", "+", "ยัง", "โอเค", "ok")


def clean_body(body: str) -> tuple[str, str, bool]:
    """ตัดชื่อที่แท็กออกจากข้อความ — คืน (ข้อความจริง, ชื่อที่ตัดออก, แท็กล้วนไหม)

    วัดจริงแล้วว่าคอมเมนต์ 74.8% มีการแท็ก และ 41.7% เป็นแท็กล้วน
    ถ้าไม่ตัดออก 'คอมเมนต์ยอดนิยม' จะกลายเป็นกองชื่อคน 8 ชื่อต่อกัน
    """
    if not body or not body.strip():
        return "", "", False
    names: list[str] = []

    def _grab(m: re.Match) -> str:
        names.append(m.group(0))
        return " "

    txt = _RE_CAMEL_BLOB.sub(_grab, body)
    txt = _RE_LATIN_NAME.sub(_grab, txt)
    # โทเคนไทยที่มีเครื่องหมายประดับชื่อเล่น (ฯ ' ๆ อิโมจิ) ถือเป็นชื่อคน
    out = []
    for tok in txt.split():
        if _RE_DECOR.search(tok) and _THAI.search(tok):
            names.append(tok)
        else:
            out.append(tok)
    clean = " ".join(out).strip(" .,-·")
    # เหลือน้อยกว่า 4 ตัวอักษร แปลว่าที่เหลือคือเศษ ไม่ใช่ประโยค
    tag_only = bool(names) and len(clean) < 4
    return clean, " | ".join(names), tag_only


def classify(body_clean: str, tag_only: bool, has_image: bool,
             raw: str) -> tuple[str, str]:
    """ตีบทบาทคนคอมเมนต์ด้วยกฎ — คืน (บทบาท, ชื่อกฎที่ใช้)

    เจตนา: ให้ตรวจย้อนได้ทุกแถวว่าเพราะกฎข้อไหน ไม่ใช่กล่องดำ
    ยอมรับข้อจำกัด: กฎคีย์เวิร์ดพลาดได้ ผู้ใช้แก้รายแถวได้จากหน้าเว็บ
    """
    low = (body_clean or "").lower()
    rawl = (raw or "").lower()
    if any(k in rawl for k in _SPAM):
        return "สแปม", "คีย์เวิร์ดสแปม"
    if tag_only:
        return "แท็กเพื่อน", "แท็กล้วนไม่มีเนื้อความ"
    if not body_clean:
        return ("รูป/สติกเกอร์", "ไม่มีข้อความ") if has_image else ("ว่าง", "ไม่มีข้อความ")
    if any(k in low for k in _SELL):
        return "คนขาย", "คีย์เวิร์ดชักชวนติดต่อ"
    if any(k in low for k in _BUY):
        return "ลูกค้า", "คีย์เวิร์ดถามซื้อ"
    # "ราคา" คำเดียวนับเป็นลูกค้าเฉพาะตอนเป็นคอมเมนต์สั้นๆ (ถามราคา)
    # ถ้าอยู่ในประโยคยาวมักเป็นการบ่นเรื่องราคา ไม่ใช่คนอยากซื้อ
    if "ราคา" in low and len(body_clean) <= 12:
        return "ลูกค้า", "ถามราคาสั้นๆ"
    if len(body_clean) <= 6 and any(low.startswith(k) for k in _ACK):
        return "ขานรับ", "ข้อความสั้นไม่มีสาระ"
    if has_image and len(body_clean) < 15:
        return "รูป/สติกเกอร์", "รูปพร้อมข้อความสั้น"
    return "คุยเล่น", "ไม่เข้ากฎอื่น"


def enrich_comments(conn: sqlite3.Connection, gid: str | None = None,
                    force: bool = False) -> dict:
    """ล้าง+ตีบทบาทคอมเมนต์ทั้งกลุ่ม — คืนสรุปจำนวนต่อบทบาท (ห้ามเงียบ)"""
    sql = ("SELECT c.comment_id, c.body, c.is_spam, "
           " (SELECT COUNT(*) FROM comment_image i WHERE i.comment_id=c.comment_id) AS n_img "
           "FROM fb_comment c JOIN fb_post p ON p.post_id=c.post_id WHERE 1=1")
    args: list = []
    if gid:
        sql += " AND p.gid=?"
        args.append(gid)
    if not force:
        sql += (" AND NOT EXISTS (SELECT 1 FROM comment_enrich e "
                "WHERE e.comment_id=c.comment_id AND e.rule_ver=?)")
        args.append(RULE_VER)
    rows = conn.execute(sql, args).fetchall()
    summary: dict[str, int] = {}
    for r in rows:
        clean, names, tag_only = clean_body(r["body"])
        role, rule = classify(clean, tag_only, bool(r["n_img"]), r["body"])
        if r["is_spam"] and role != "สแปม":
            role, rule = "สแปม", "ธง is_spam จากตัวเก็บ"
        conn.execute("""INSERT INTO comment_enrich
              (comment_id, body_clean, tag_names, is_tag_only, role, role_rule,
               rule_ver, enriched_at)
              VALUES (?,?,?,?,?,?,?,unixepoch())
              ON CONFLICT(comment_id) DO UPDATE SET
                body_clean=excluded.body_clean, tag_names=excluded.tag_names,
                is_tag_only=excluded.is_tag_only, role=excluded.role,
                role_rule=excluded.role_rule, rule_ver=excluded.rule_ver,
                enriched_at=excluded.enriched_at""",
                     (r["comment_id"], clean, names[:500], int(tag_only), role,
                      rule, RULE_VER))
        summary[role] = summary.get(role, 0) + 1
    conn.commit()
    return {"n": len(rows), "roles": summary, "rule_ver": RULE_VER}


# ------------------------------------------------------------------ ลายเซ็น/ความเชื่อถือ

def input_sig(conn: sqlite3.Connection, gid: str) -> str:
    """ลายเซ็นข้อมูลนำเข้า — เปลี่ยนเมื่อไรแปลว่าบทวิเคราะห์เก่าล้าสมัย"""
    import fb_analysis_sql as q
    r = conn.execute(q.INPUT_SIG_SQL, {"gid": gid}).fetchone()
    return f"{r['n_post']}p/{r['n_mass']}m/{r['n_comment']}c/{r['eng_sum']}e/{r['last_collect']}"


def confidence_of(n_post: int, n_mass: int, n_comment_usable: int) -> tuple[str, str]:
    """ระดับความเชื่อถือ — คำนวณจากขนาดตัวอย่างจริง ไม่ให้ LLM ประเมินตัวเอง

    เกณฑ์มาจากข้อเท็จจริงที่วัดได้: กลุ่มจริงมีโพสต์แมส 0-129 ใบ
    บางกลุ่ม 0 ใบ ซึ่งสรุปสูตรไม่ได้เลย ต้องบอกตรงๆ ไม่ใช่เขียนให้ดูดี
    """
    if n_post < 30:
        return "none", f"โพสต์ทั้งกลุ่มมีแค่ {n_post} ใบ (ต่ำกว่า 30) สรุปอะไรไม่ได้"
    if n_mass == 0:
        return "none", "กลุ่มนี้ไม่มีโพสต์แมสเลยสักใบ — เทียบแมส/ไม่แมสไม่ได้"
    if n_mass < 5:
        return "low", f"โพสต์แมสมีแค่ {n_mass} ใบ — เป็นเกร็ดตัวอย่าง ไม่ใช่สูตร"
    if n_mass < 20:
        return "medium", f"โพสต์แมส {n_mass} ใบ พอเห็นแนวโน้ม แต่ยังไม่ควรฟันธง"
    return "high", f"โพสต์แมส {n_mass} ใบ จาก {n_post} ใบ — พอสรุปแนวทางได้"


def audience_gate(n_comment_usable: int, pct_cov: float | None,
                  n_post_with_cm: int = 0) -> tuple[str, str]:
    """ประตูหมวด 'ฐานลูกค้า' — คืน (closed/limited/open, เหตุผล)

    ปิดจริงเมื่อคอมเมนต์ไม่พอ ไม่ใช่แค่ขึ้นข้อความเตือนแล้วปล่อยเขียน
    สถานะ limited = เขียนได้แต่ต้องติดป้ายว่ามาจากโพสต์กี่ใบ เพราะคอมเมนต์
    ในฐานกระจุกอยู่บนโพสต์ไม่กี่ใบ (วัดจริง: 613 คอมเมนต์มาจากโพสต์ 7 ใบ
    จาก 1,005 ใบ) — เป็นเสียงของโพสต์เหล่านั้น ไม่ใช่เสียงของทั้งกลุ่ม
    """
    if n_comment_usable < 30:
        return "closed", (f"คอมเมนต์ที่ใช้วิเคราะห์ได้จริงมีแค่ {n_comment_usable} อัน "
                          f"(ต้องการอย่างน้อย 30) — หมวดฐานลูกค้าปิด")
    if n_post_with_cm < 10 or (pct_cov is not None and pct_cov < 20):
        return "limited", (f"ใช้ได้ {n_comment_usable} อัน แต่มาจากโพสต์แค่ "
                           f"{n_post_with_cm} ใบ (ครอบคลุม {pct_cov}% ของคอมเมนต์ที่ FB บอกว่ามี) "
                           f"— เขียนได้แต่ต้องระบุว่าเป็นเสียงจากโพสต์เหล่านี้ ไม่ใช่ทั้งกลุ่ม")
    return "open", f"คอมเมนต์ใช้ได้ {n_comment_usable} อัน จากโพสต์ {n_post_with_cm} ใบ (ครอบคลุม {pct_cov}%)"


def brief_hash(body: str) -> str:
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


# ------------------------------------------------------------------ เขียนผลกลับ

class WritebackError(Exception):
    """ผลวิเคราะห์ไม่ผ่านด่าน — โยนทิ้งทั้งรอบ ไม่เก็บครึ่งๆ กลางๆ"""


def apply_analysis(conn: sqlite3.Connection, brief_hash_short: str,
                   payload: dict, analyst: str = "claude-chat") -> dict:
    """รับ JSON ที่ Claude เขียนกลับมา → ตรวจ → บันทึก (ทั้งหมดหรือไม่เอาเลย)

    ด่านที่ต้องผ่าน:
      1. brief_hash ต้องตรงกับซองที่มีอยู่จริง (รู้ว่าอ่านข้อมูลชุดไหนมา)
      2. ทุก claim ต้องมี evidence อย่างน้อย 1 ชิ้น
      3. handle ทุกตัว (P1/C7) ต้องอยู่ใน manifest ของซองนั้น
      4. หมวดที่ถูก gate ปิดไว้ ห้ามมี claim
      5. ตัวเลขที่ LLM ส่งมาถูกทิ้ง — ระบบเติมจาก SQL เอง
      6. TRIGGER ในฐานตรวจซ้ำว่า id มีจริงและอยู่ในกลุ่มเดียวกัน
    """
    br = conn.execute("SELECT * FROM analysis_brief WHERE brief_hash LIKE ?",
                      (brief_hash_short + "%",)).fetchone()
    if br is None:
        raise WritebackError(f"ไม่พบซองข้อมูล hash={brief_hash_short}")
    manifest = json.loads(br["manifest"])
    gates = json.loads(br["gates"])
    claims = payload.get("claims") or []
    if not claims:
        raise WritebackError("ไม่มี claim เลยสักข้อ")

    sig_now = input_sig(conn, br["gid"])
    n_usable = int(gates.get("n_comment_usable") or 0)
    conf, why = confidence_of(br["n_post"], br["n_mass"], n_usable)

    cur = conn.cursor()
    cur.execute("BEGIN")
    try:
        cur.execute("""INSERT INTO analysis_run
            (gid, brief_id, analyst, input_sig, n_post, n_mass,
             n_comment_usable, confidence, confidence_why)
            VALUES (?,?,?,?,?,?,?,?,?)""",
                    (br["gid"], br["brief_id"], analyst, sig_now, br["n_post"],
                     br["n_mass"], n_usable, conf, why))
        run_id = cur.lastrowid
        for i, c in enumerate(claims):
            sec = (c.get("section") or "").strip()
            if sec == "audience" and gates.get("audience_state") == "closed":
                raise WritebackError(
                    "หมวดฐานลูกค้าถูกปิดไว้ในซองนี้: " + str(gates.get("audience_why")))
            refs = c.get("evidence") or []
            if not refs:
                raise WritebackError(
                    f"claim '{(c.get('headline') or '')[:40]}' ไม่มีหลักฐานอ้างอิง")
            cur.execute("""INSERT INTO analysis_claim
                (run_id, section, ord, headline, detail, metric_key, n_evidence)
                VALUES (?,?,?,?,?,?,?)""",
                        (run_id, sec, i, (c.get("headline") or "").strip(),
                         (c.get("detail") or "").strip(),
                         (c.get("metric_key") or "").strip(), len(refs)))
            claim_id = cur.lastrowid
            for h in refs:
                real = manifest.get(h)
                if real is None:
                    raise WritebackError(
                        f"อ้างหลักฐาน '{h}' ที่ไม่มีในซองข้อมูล — ปฏิเสธทั้งรอบ")
                kind = "post" if h.startswith("P") else "comment"
                cur.execute("""INSERT OR IGNORE INTO analysis_evidence
                    (claim_id, kind, ref_id, note) VALUES (?,?,?,?)""",
                            (claim_id, kind, real, h))
        # รอบเก่าของกลุ่มนี้กลายเป็น replaced
        cur.execute("UPDATE analysis_run SET status='replaced' "
                    "WHERE gid=? AND run_id<>? AND status='active'",
                    (br["gid"], run_id))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return {"run_id": run_id, "confidence": conf, "why": why,
            "n_claim": len(claims), "gid": br["gid"]}
