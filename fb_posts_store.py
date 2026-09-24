"""ฐานข้อมูลคลังโพสต์ — SQLite ในเครื่อง (ค้นเร็ว) + รูปไป Google Drive

แบ่งที่เก็บตามที่ผู้ใช้สั่ง 18 ส.ค. 2569:
  ข้อความ/ตัวเลข/คอมเมนต์ → SQLite ในเครื่อง (query ต้องเร็ว วางบนคลาวด์ไม่ได้)
  รูปทั้งหมด             → G:\\My Drive\\Identify group post facebook\\

⚠️ ข้อควรรู้เรื่อง G: (วัดจริง 18 ส.ค.):
  Win32_LogicalDisk รายงาน C: กับ G: ขนาดเท่ากันเป๊ะ (510,544,646,144 B)
  และ Get-Volume เห็นแค่ C: — G: คือ Google Drive แบบสตรีม ไม่ใช่ดิสก์ลูกที่สอง
  ทุกไฟล์ที่เขียนต้องผ่านแคชบน C: ก่อนอัปขึ้นคลาวด์ ถ้าเขียนเร็วกว่าที่อัปทัน
  ดิสก์ C: จะเต็มแล้วพังทั้งเครื่อง → ต้องมีด่าน disk_ok() คอยเบรก
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import sqlite3
import time
from datetime import datetime
from pathlib import Path

import fb_mass_finder as mf

DB_FILE = mf.DATA_DIR / "fb_posts.db"
# โฟลเดอร์รูปบน Google Drive (ผู้ใช้ยืนยันโฟลเดอร์นี้ 18 ส.ค. 2569)
MEDIA_ROOT = Path(r"G:\My Drive\Identify group post facebook")
# พื้นที่ว่างขั้นต่ำบนไดรฟ์ที่แคชอยู่ — ต่ำกว่านี้ให้หยุดเก็บรูปทันที
DISK_FLOOR_GB = 4.0

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS fb_group (
  gid          TEXT PRIMARY KEY,
  name         TEXT NOT NULL DEFAULT '',
  url          TEXT NOT NULL DEFAULT '',
  members      INTEGER,
  keyword      TEXT,
  band         TEXT,
  first_seen   INTEGER NOT NULL DEFAULT (unixepoch()),
  last_run_at  INTEGER,
  posts_seen   INTEGER NOT NULL DEFAULT 0,
  state        TEXT NOT NULL DEFAULT 'pending',
  -- การจองกลุ่ม: บอทสองตัวต้องไม่หยิบกลุ่มเดียวกัน และถ้าบอทตายกลางทาง
  -- ต้องมีวันหมดอายุให้ตัวอื่นมารับช่วงต่อได้ (ไม่ค้างถาวร)
  claimed_by   TEXT NOT NULL DEFAULT '',
  lease_until  INTEGER NOT NULL DEFAULT 0,
  attempts     INTEGER NOT NULL DEFAULT 0,
  last_error   TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS ix_group_state ON fb_group(state, last_run_at);
CREATE INDEX IF NOT EXISTS ix_group_name  ON fb_group(name);

CREATE TABLE IF NOT EXISTS fb_post (
  post_id      TEXT PRIMARY KEY,
  gid          TEXT NOT NULL REFERENCES fb_group(gid) ON DELETE CASCADE,
  url          TEXT NOT NULL DEFAULT '',
  author       TEXT NOT NULL DEFAULT '',
  author_url   TEXT NOT NULL DEFAULT '',
  avatar       TEXT NOT NULL DEFAULT '',
  posted_at    INTEGER,
  caption      TEXT NOT NULL DEFAULT '',
  caption_len  INTEGER NOT NULL DEFAULT 0,
  -- NULL = อ่านค่าไม่ได้ · 0 = รู้ว่าไม่มีจริง (ห้ามยุบสองอย่างนี้เป็นค่าเดียว)
  reactions    INTEGER,
  comments     INTEGER,
  shares       INTEGER,
  views        INTEGER,
  engagement   INTEGER NOT NULL DEFAULT 0,
  is_mass      INTEGER NOT NULL DEFAULT 0,
  feed_rank    INTEGER,
  images_n     INTEGER NOT NULL DEFAULT 0,
  -- สถานะการเก็บคอมเมนต์: pending/done/partial/skipped/failed
  comments_state    TEXT NOT NULL DEFAULT 'pending',
  comments_expected INTEGER,
  comments_got      INTEGER,
  comments_note     TEXT NOT NULL DEFAULT '',
  collected_at INTEGER NOT NULL DEFAULT (unixepoch())
);
CREATE INDEX IF NOT EXISTS ix_post_group  ON fb_post(gid, engagement DESC);
CREATE INDEX IF NOT EXISTS ix_post_todo   ON fb_post(gid, comments_state, comments DESC);
CREATE INDEX IF NOT EXISTS ix_post_time   ON fb_post(gid, posted_at DESC);

CREATE TABLE IF NOT EXISTS post_image (
  post_id  TEXT NOT NULL REFERENCES fb_post(post_id) ON DELETE CASCADE,
  idx      INTEGER NOT NULL,
  src_url  TEXT NOT NULL,
  sha256   TEXT,
  rel_path TEXT,
  bytes    INTEGER,
  width    INTEGER,
  height   INTEGER,
  alt      TEXT NOT NULL DEFAULT '',
  state    TEXT NOT NULL DEFAULT 'pending',
  error    TEXT NOT NULL DEFAULT '',
  PRIMARY KEY (post_id, idx)
);
CREATE INDEX IF NOT EXISTS ix_image_state ON post_image(state);

CREATE TABLE IF NOT EXISTS fb_comment (
  comment_id TEXT PRIMARY KEY,
  post_id    TEXT NOT NULL REFERENCES fb_post(post_id) ON DELETE CASCADE,
  seq        INTEGER NOT NULL,
  depth      INTEGER NOT NULL DEFAULT 0,
  author     TEXT NOT NULL DEFAULT '',
  author_url TEXT NOT NULL DEFAULT '',
  avatar     TEXT NOT NULL DEFAULT '',
  body       TEXT NOT NULL DEFAULT '',
  when_text  TEXT NOT NULL DEFAULT '',
  likes      INTEGER NOT NULL DEFAULT 0,
  is_spam    INTEGER NOT NULL DEFAULT 0,
  spam_score INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_comment_post   ON fb_comment(post_id, seq);
CREATE INDEX IF NOT EXISTS ix_comment_author ON fb_comment(author);
CREATE INDEX IF NOT EXISTS ix_comment_spam   ON fb_comment(is_spam);

CREATE TABLE IF NOT EXISTS comment_image (
  comment_id TEXT NOT NULL REFERENCES fb_comment(comment_id) ON DELETE CASCADE,
  idx      INTEGER NOT NULL,
  src_url  TEXT NOT NULL,
  sha256   TEXT,
  rel_path TEXT,
  bytes    INTEGER,
  state    TEXT NOT NULL DEFAULT 'pending',
  error    TEXT NOT NULL DEFAULT '',
  PRIMARY KEY (comment_id, idx)
);

CREATE TABLE IF NOT EXISTS collect_run (
  run_id     INTEGER PRIMARY KEY AUTOINCREMENT,
  gid        TEXT NOT NULL,
  bot        TEXT NOT NULL DEFAULT '',
  stage      TEXT NOT NULL,
  started_at INTEGER NOT NULL DEFAULT (unixepoch()),
  ended_at   INTEGER,
  status     TEXT NOT NULL DEFAULT 'running',
  posts_seen INTEGER NOT NULL DEFAULT 0,
  posts_new  INTEGER NOT NULL DEFAULT 0,
  comments_new INTEGER NOT NULL DEFAULT 0,
  images_new INTEGER NOT NULL DEFAULT 0,
  note       TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS ix_run_group ON collect_run(gid, started_at DESC);
"""


def connect() -> sqlite3.Connection:
    DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_FILE, timeout=60)
    conn.row_factory = sqlite3.Row
    # บอทสองตัวเขียนฐานเดียวกัน — ต้องรอคิวกันได้นานพอ ไม่งั้นเจอ
    # "database is locked" แล้วทิ้งกลุ่มทั้งกลุ่ม (เกิดจริงกับ "รีวิวแม็คโคร")
    conn.execute("PRAGMA busy_timeout=60000")
    conn.executescript(SCHEMA)
    # เติมคอลัมน์ที่เพิ่มทีหลัง — CREATE TABLE IF NOT EXISTS ไม่เติมให้เอง
    have = {r["name"] for r in conn.execute("PRAGMA table_info(fb_group)")}
    for col, ddl in (("claimed_by", "TEXT NOT NULL DEFAULT ''"),
                     ("lease_until", "INTEGER NOT NULL DEFAULT 0"),
                     ("attempts", "INTEGER NOT NULL DEFAULT 0"),
                     ("last_error", "TEXT NOT NULL DEFAULT ''"),
                     # เลื่อนฟีดจนสุดแล้วหรือยัง — ใช้ตอนบอทกลับมาทำต่อ
                     # ถ้าไม่จำไว้ บอทจะเลื่อนฟีดซ้ำทั้งพันโพสต์ทุกครั้งที่ทำต่อ
                     ("feed_done", "INTEGER NOT NULL DEFAULT 0")):
        if col not in have:
            conn.execute(f"ALTER TABLE fb_group ADD COLUMN {col} {ddl}")
    # รูปโปรไฟล์คนโพสต์/คนคอมเมนต์ — ผู้ใช้สั่งให้เก็บ "ชื่อคน, รูป, เนื้อหา"
    # URL ของ Facebook หมดอายุ ~103 ชม. จึงต้องดาวน์โหลดเก็บเป็นไฟล์เหมือนรูปอื่น
    for table in ("fb_post", "fb_comment"):
        cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        if "avatar_path" not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN avatar_path TEXT "
                         "NOT NULL DEFAULT ''")
    conn.commit()
    return conn


# --------------------------------------------------------------- จองกลุ่มทำงาน

# ⚠️ เคยตั้งไว้ 3 ชม. พร้อมคอมเมนต์ว่า "ยาวกว่าเวลาเก็บจริงมาก" — ผิด
# วัดจาก collect_run ที่จบจริง 4 กลุ่ม: 4.55 · 4.85 · 6.80 · 7.55 ชม.
# แปลว่าการจองหมดอายุ "ทุกกลุ่ม" ตั้งแต่ยังทำไม่เสร็จ ถ้าบอทไม่ต่ออายุ
# บอทอีกตัวจะแย่งกลุ่มที่ยังทำอยู่ไปทำซ้ำ → ตั้งใหม่ให้ยาวกว่ากลุ่มช้าสุด 1.5 เท่า
LEASE_SECONDS = 12 * 3600


def claim_group(conn: sqlite3.Connection, bot: str) -> dict | None:
    """จองกลุ่มถัดไปให้บอทตัวนี้ — คืน None ถ้าไม่มีงานเหลือ

    กลุ่มที่ยังไม่เคยทำมาก่อน จะถูกจองด้วย UPDATE ... WHERE ที่กันแข่งกันเอง
    (SQLite ล็อกทั้งไฟล์ตอนเขียน จึงมีแค่ตัวเดียวที่ชนะ)
    กลุ่มที่บอทอื่นจองไว้แต่หมดอายุแล้ว = บอทนั้นตายกลางทาง เอามาทำต่อได้
    """
    now = int(time.time())
    for _ in range(50):
        # ⚠️ ต้องรวม state='running' ที่หมดอายุจองด้วย — ถ้ากรองแค่ pending/failed
        # กลุ่มที่บอทตายคาไว้จะค้างเป็น running ตลอดกาล ไม่มีใครหยิบไปทำต่อ
        # (เกิดจริง: "อวดบ้านกันนะ" ค้างของ Bot9 อยู่ 19 ชม. หลังบอทตาย)
        row = conn.execute("""
            SELECT gid, name, url, members FROM fb_group
            WHERE (state IN ('pending','failed')
                   OR (state='running' AND lease_until < ?))
              AND (claimed_by='' OR lease_until < ?)
              AND attempts < 3
            ORDER BY COALESCE(priority, 0) DESC, attempts, COALESCE(members,0) DESC
            LIMIT 1""", (now, now)).fetchone()
        if row is None:
            return None
        changed = conn.execute("""
            UPDATE fb_group SET state='running', claimed_by=?, lease_until=?,
                   attempts=attempts+1
            WHERE gid=? AND (claimed_by='' OR lease_until < ?)""",
            (bot, now + LEASE_SECONDS, row["gid"], now)).rowcount
        conn.commit()
        if changed:
            return dict(row)
    return None


def renew_lease(conn: sqlite3.Connection, gid: str, bot: str) -> None:
    """ต่ออายุการจองระหว่างทำงาน — กลุ่มใหญ่ใช้เวลาเกิน 3 ชม.ได้

    ถ้าไม่ต่อ บอทอีกตัวจะเห็นว่าจองหมดอายุแล้วแย่งกลุ่มไปทำซ้ำ ทั้งที่ตัวแรก
    ยังทำอยู่ = เปิดหน้าเดียวกันสองบอท เสี่ยงโดน Facebook จับผิดปกติ
    """
    conn.execute("UPDATE fb_group SET lease_until=? WHERE gid=? AND claimed_by=?",
                 (int(time.time()) + LEASE_SECONDS, gid, bot))
    conn.commit()


def finish_group(conn: sqlite3.Connection, gid: str, status: str,
                 error: str = "") -> None:
    conn.execute("""UPDATE fb_group SET state=?, claimed_by='', lease_until=0,
                    last_error=?, last_run_at=unixepoch() WHERE gid=?""",
                 (status, error[:300], gid))
    conn.commit()


def import_whitelist(conn: sqlite3.Connection) -> int:
    """ดึงกลุ่มที่ผ่านการคัดแล้วจาก /keyword เข้ามาเป็นคิวเก็บข้อมูล"""
    state = mf.load_kw_state()
    added = 0
    for gid, info in (state.get("whitelist") or {}).items():
        row = conn.execute("SELECT 1 FROM fb_group WHERE gid=?", (gid,)).fetchone()
        if row:
            continue
        save_group(conn, {
            "gid": gid, "name": info.get("name", ""),
            "url": info.get("url") or f"https://www.facebook.com/groups/{gid}/",
            "members": info.get("members"), "keyword": info.get("keyword"),
            "band": info.get("band"),
        })
        added += 1
    return added


# ------------------------------------------------------------------ พื้นที่ดิสก์

def disk_free_gb(path: Path) -> float:
    try:
        return shutil.disk_usage(path).free / (1024 ** 3)
    except OSError:
        return 0.0


def disk_ok() -> tuple[bool, str]:
    """พอไหมที่จะเขียนรูปต่อ — เช็คทั้งไดรฟ์ฐานข้อมูลและไดรฟ์รูป

    เช็ค C: ด้วยเสมอ แม้รูปจะไปลง G: เพราะ G: คือ Google Drive แบบสตรีม
    ที่แคชไฟล์ไว้บน C: ก่อนอัป — ถ้าดูแค่ G: จะไม่เห็นว่ากำลังจะเต็ม
    """
    for label, path in (("ฐานข้อมูล", DB_FILE.parent), ("รูป", MEDIA_ROOT)):
        if not path.exists():
            continue
        free = disk_free_gb(path)
        if free < DISK_FLOOR_GB:
            return False, f"พื้นที่{label}เหลือ {free:.1f} GB (ต่ำกว่าขีด {DISK_FLOOR_GB} GB)"
    return True, ""


def media_ready() -> tuple[bool, str]:
    """Google Drive ต่ออยู่ไหม — ถ้าไม่ ห้ามเก็บรูปแล้วบันทึกว่าสำเร็จ"""
    if not MEDIA_ROOT.exists():
        return False, (f"ไม่พบโฟลเดอร์รูป {MEDIA_ROOT} — "
                       "Google Drive อาจไม่ได้เปิดอยู่")
    try:
        probe = MEDIA_ROOT / ".write_test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as error:
        return False, f"เขียนลงโฟลเดอร์รูปไม่ได้: {error}"
    return True, ""


# ------------------------------------------------------------------ เก็บข้อมูล

def _safe_name(text: str, limit: int = 60) -> str:
    """ชื่อโฟลเดอร์ที่ Windows รับได้ — คงภาษาไทยไว้ให้คนอ่านออก"""
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", text or "").strip(" .")
    return (cleaned[:limit] or "group").rstrip()


def group_dir(gid: str, name: str) -> Path:
    return MEDIA_ROOT / f"{_safe_name(name)}_{gid}"


def save_group(conn: sqlite3.Connection, group: dict) -> None:
    conn.execute("""
        INSERT INTO fb_group (gid, name, url, members, keyword, band)
        VALUES (?,?,?,?,?,?)
        ON CONFLICT(gid) DO UPDATE SET
          name=COALESCE(NULLIF(excluded.name,''), fb_group.name),
          url=COALESCE(NULLIF(excluded.url,''), fb_group.url),
          members=COALESCE(excluded.members, fb_group.members),
          keyword=COALESCE(excluded.keyword, fb_group.keyword),
          band=COALESCE(excluded.band, fb_group.band)
    """, (group["gid"], group.get("name", ""), group.get("url", ""),
          group.get("members"), group.get("keyword"), group.get("band")))
    conn.commit()


def save_posts(conn: sqlite3.Connection, gid: str, posts: list[dict],
               mass_threshold: int = 100) -> int:
    """บันทึกโพสต์ทั้งชุด — คืนจำนวนโพสต์ใหม่ที่เพิ่งเห็นครั้งแรก"""
    new = 0
    for rank, post in enumerate(posts, 1):
        eng = (int(post.get("likes") or 0) + int(post.get("comments") or 0)
               + int(post.get("shares") or 0))
        unknown = set(post.get("unknown") or [])
        row = conn.execute("SELECT 1 FROM fb_post WHERE post_id=?",
                           (post["id"],)).fetchone()
        if row is None:
            new += 1
        conn.execute("""
            INSERT INTO fb_post (post_id, gid, url, author, author_url, avatar,
              posted_at, caption, caption_len, reactions, comments, shares,
              views, engagement, is_mass, feed_rank, images_n)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(post_id) DO UPDATE SET
              caption=CASE WHEN length(excluded.caption) > length(fb_post.caption)
                           THEN excluded.caption ELSE fb_post.caption END,
              author=COALESCE(NULLIF(excluded.author,''), fb_post.author),
              posted_at=COALESCE(excluded.posted_at, fb_post.posted_at),
              reactions=COALESCE(excluded.reactions, fb_post.reactions),
              comments=COALESCE(excluded.comments, fb_post.comments),
              shares=COALESCE(excluded.shares, fb_post.shares),
              views=COALESCE(excluded.views, fb_post.views),
              engagement=MAX(excluded.engagement, fb_post.engagement),
              is_mass=excluded.is_mass,
              images_n=MAX(excluded.images_n, fb_post.images_n)
        """, (
            post["id"], gid, post.get("url", ""), post.get("author", ""),
            post.get("author_url", ""), post.get("avatar", ""),
            post.get("posted_at"), post.get("caption", ""),
            len(post.get("caption") or ""),
            None if "reactions" in unknown else int(post.get("likes") or 0),
            None if "comments" in unknown else int(post.get("comments") or 0),
            None if "shares" in unknown else int(post.get("shares") or 0),
            int(post.get("views") or 0) or None,
            eng, 1 if eng > mass_threshold else 0, rank,
            len(post.get("images") or []),
        ))
        for idx, img in enumerate(post.get("images") or []):
            conn.execute("""
                INSERT INTO post_image (post_id, idx, src_url, width, height, alt)
                VALUES (?,?,?,?,?,?)
                ON CONFLICT(post_id, idx) DO UPDATE SET src_url=excluded.src_url
            """, (post["id"], idx, img.get("uri", ""), img.get("width"),
                  img.get("height"), (img.get("alt") or "")[:300]))
    conn.execute("UPDATE fb_group SET posts_seen=(SELECT COUNT(*) FROM fb_post "
                 "WHERE gid=?), last_run_at=unixepoch() WHERE gid=?", (gid, gid))
    conn.commit()
    return new


def save_comments(conn: sqlite3.Connection, post_id: str, result: dict,
                  spam_fn, score_fn=None) -> int:
    """บันทึกคอมเมนต์ของโพสต์หนึ่ง + จดว่าเก็บได้ครบแค่ไหน (ห้ามเงียบ)"""
    comments = result.get("comments") or []
    for seq, c in enumerate(comments, 1):
        cid = f"{post_id}_{seq}"
        text = c.get("text", "")
        conn.execute("""
            INSERT INTO fb_comment (comment_id, post_id, seq, depth, author,
              author_url, avatar, body, when_text, likes, is_spam, spam_score)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(comment_id) DO UPDATE SET
              body=excluded.body, likes=excluded.likes,
              is_spam=excluded.is_spam, spam_score=excluded.spam_score
        """, (cid, post_id, seq, int(c.get("depth") or 0), c.get("author", ""),
              c.get("author_url", ""), c.get("avatar", ""), text,
              c.get("when", ""), int(c.get("likes") or 0),
              1 if spam_fn(text) else 0,
              # เดิมยัด 0 ตายตัวทั้งที่มีตัวคำนวณอยู่แล้ว → 9,688 แถวได้ 0 หมด
              # ทำให้ปรับเกณฑ์สแปมย้อนหลังไม่ได้ ต้องไปไล่เก็บใหม่ทั้งชุด
              int(score_fn(text)) if score_fn else 0))
        for idx, url in enumerate(c.get("images") or []):
            conn.execute("""
                INSERT INTO comment_image (comment_id, idx, src_url)
                VALUES (?,?,?)
                ON CONFLICT(comment_id, idx) DO UPDATE SET src_url=excluded.src_url
            """, (cid, idx, url))

    expected = int(result.get("expect") or 0)
    got = len(comments)
    # "done" เฉพาะตอนได้ครบพอสมควรจริงๆ — ไม่งั้นบันทึกเป็น partial พร้อมเหตุผล
    if not expected:
        state = "done" if got else "skipped"
    elif got >= expected * 0.8:
        state = "done"
    else:
        state = "partial"
    conn.execute("""UPDATE fb_post SET comments_state=?, comments_expected=?,
                    comments_got=?, comments_note=? WHERE post_id=?""",
                 (state, expected or None, got,
                  result.get("warn", "")[:200], post_id))
    conn.commit()
    return got


# ------------------------------------------------------------------ รูปภาพ

def save_image(conn: sqlite3.Connection, table: str, owner_id: str, idx: int,
               data: bytes, gid: str, group_name: str, kind: str) -> str:
    """เขียนไฟล์รูปแบบ atomic แล้วค่อยบันทึกลงฐาน — ไฟล์ต้องครบก่อนฐานรู้จัก

    เขียน .tmp → fsync → rename ทำให้ไม่มีทางเหลือไฟล์ครึ่งๆ ที่ฐานบอกว่าครบ
    """
    sha = hashlib.sha256(data).hexdigest()
    folder = group_dir(gid, group_name) / kind / sha[:2]
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{sha}.jpg"
    rel = str(target.relative_to(MEDIA_ROOT)).replace("\\", "/")
    if not target.exists():
        tmp = target.with_suffix(".tmp")
        with open(tmp, "wb") as fh:
            fh.write(data)
            fh.flush()
            import os
            os.fsync(fh.fileno())
        tmp.replace(target)
    conn.execute(f"""UPDATE {table} SET sha256=?, rel_path=?, bytes=?,
                     state='stored', error='' WHERE {'post_id' if table=='post_image'
                     else 'comment_id'}=? AND idx=?""",
                 (sha, rel, len(data), owner_id, idx))
    return rel


def mark_image_failed(conn: sqlite3.Connection, table: str, owner_id: str,
                      idx: int, error: str) -> None:
    key = "post_id" if table == "post_image" else "comment_id"
    conn.execute(f"UPDATE {table} SET state='failed', error=? "
                 f"WHERE {key}=? AND idx=?", (error[:200], owner_id, idx))


# ------------------------------------------------------------------ รายงาน

def group_summary(conn: sqlite3.Connection, gid: str) -> dict:
    row = conn.execute("""
        SELECT COUNT(*) posts,
               SUM(is_mass) mass,
               SUM(CASE WHEN comments_state='done' THEN 1 ELSE 0 END) com_done,
               SUM(COALESCE(comments_got,0)) com_got,
               MAX(engagement) top_eng
        FROM fb_post WHERE gid=?""", (gid,)).fetchone()
    imgs = conn.execute("""SELECT COUNT(*) n, SUM(COALESCE(bytes,0)) b
        FROM post_image WHERE state='stored' AND post_id IN
        (SELECT post_id FROM fb_post WHERE gid=?)""", (gid,)).fetchone()
    return {"posts": row["posts"] or 0, "mass": row["mass"] or 0,
            "comments": row["com_got"] or 0, "posts_with_comments": row["com_done"] or 0,
            "top_engagement": row["top_eng"] or 0,
            "images": imgs["n"] or 0, "image_mb": (imgs["b"] or 0) / 1024 / 1024}


def start_run(conn: sqlite3.Connection, gid: str, bot: str, stage: str) -> int:
    cur = conn.execute("INSERT INTO collect_run (gid, bot, stage) VALUES (?,?,?)",
                       (gid, bot, stage))
    conn.commit()
    return int(cur.lastrowid)


def mark_feed_done(conn: sqlite3.Connection, gid: str) -> None:
    """จำไว้ว่ากลุ่มนี้เลื่อนฟีดครบแล้ว — รอบหน้าจะได้ไม่ต้องเลื่อนซ้ำ"""
    conn.execute("UPDATE fb_group SET feed_done=1 WHERE gid=?", (gid,))
    conn.commit()


def feed_done(conn: sqlite3.Connection, gid: str) -> bool:
    row = conn.execute("SELECT feed_done FROM fb_group WHERE gid=?",
                       (gid,)).fetchone()
    return bool(row and row["feed_done"])


def close_stale_runs(conn: sqlite3.Connection, bot: str) -> int:
    """ปิดรายการรันของบอทตัวนี้ที่ค้างเปิดอยู่จากรอบก่อน (บอทตายกลางทาง)

    ถ้าไม่ปิด ตาราง collect_run จะโกหกว่ายัง "running" ตลอดกาล — เคยเกิดจริง
    Bot9 ทิ้งรายการค้างไว้ 2 รายการ อายุ 27 ชม. และ 22 ชม.
    บอทตัวเดิมจะเปิดรอบใหม่เสมอตอนบูต จึงปิดของเก่าตัวเองได้อย่างปลอดภัย
    """
    n = conn.execute("""UPDATE collect_run SET ended_at=unixepoch(),
                        status='dead', note='บอทตายกลางทาง — ปิดตอนบูตรอบใหม่'
                        WHERE bot=? AND ended_at IS NULL""", (bot,)).rowcount
    conn.commit()
    return n


def end_run(conn: sqlite3.Connection, run_id: int, status: str, **counts) -> None:
    conn.execute("""UPDATE collect_run SET ended_at=unixepoch(), status=?,
                    posts_seen=?, posts_new=?, comments_new=?, images_new=?,
                    note=? WHERE run_id=?""",
                 (status, counts.get("posts_seen", 0), counts.get("posts_new", 0),
                  counts.get("comments_new", 0), counts.get("images_new", 0),
                  str(counts.get("note", ""))[:300], run_id))
    conn.commit()
