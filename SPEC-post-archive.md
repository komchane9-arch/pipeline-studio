⚙ Effort: xhigh • 💡 โมเดลที่เหมาะ: Opus — รวม 3 แบบ + ปิด fatal flaw ~60 ข้อให้เป็นสเปคเดียวที่ลงมือเขียนได้ ต้องตัดสินใจแลกข้อดีข้อเสียข้ามไฟล์/ข้ามระบบและคำนวณงบเวลา-ดิสก์-เงินใหม่ทั้งหมด

---

# สเปคระบบ FB Group Archive & Analysis (ฉบับลงมือเขียน)

> แกน = แบบ `cost-aware` · ดึง lease/jobs + broker คิวจาก `pragmatic` · ดึง media_root/PII/gate จาก `data-first`
> **ทุกข้อบกพร่องที่ผู้ตรวจเจอถูกตอบใน §11 (ตารางแมป) ไม่มีข้อไหนเงียบ**

---

## 0. สรุปการตัดสินใจที่ต่างจากทั้ง 3 แบบ (อ่านก่อน)

| เรื่อง | ทั้ง 3 แบบเสนอ | **สเปคนี้ตัดสิน** | เพราะ |
|---|---|---|---|
| ลำดับงาน | ยิง Tier A ครบ 200 กลุ่มก่อน | **pipeline ต่อกลุ่ม** (feed→media→comments→analyze จบทีละกลุ่ม) | URL รูปหมดอายุ + ผู้ใช้ต้องเห็นรายงานจริงภายใน 3 ชม. ไม่ใช่ 25 วัน |
| โหลดรูป | เป็น stage แยกท้ายคิว | **โหลดในเซสชันเดียวกับ feed** ภายใน ≤1 ชม.หลังเก็บ URL + มี `url_exp` | CDN signature หมดอายุ |
| ที่เก็บรูป | G: 24.9 GB เป็นไดรฟ์ที่สอง | **G: = C: ก้อนเดียวกัน** (Google Drive stream, total เท่ากันบิตต่อบิต) → คิดเป็นถัง **เดียว** และห้ามวาง .db บน G: | วัดจริงแล้ว |
| จับคู่ฟิลด์ | `_nearest` ระยะ 6,000 ตัวอักษร | **ตัด story block แล้ว json.loads ต่อ node** · regex เป็น fallback ที่ต้องติดธง | caption/รูปจับข้ามโพสต์ = บทวิเคราะห์ผิดทั้งระบบ |
| จำนวนโพสต์ที่เจาะคอมเมนต์ | 60/กลุ่ม | **30/กลุ่ม (12 top / 10 mid / 8 low, เลือกจาก `comments>0`)** | โควตา permalink + 70% ของโพสต์มีคอมเมนต์ 0 |
| โปรเซส | แยกโปรเซส / แทรก `else:` | **เธรดใน `fb_mass_bot.py` + BrowserBroker แบบมีลำดับความสำคัญ** (ไม่ใช่ `_busy` ดิบ ไม่ใช่กิ่ง else) | getUpdates 409 · `else:` ไม่มีวันถูกเรียก · `_busy` non-blocking ทิ้งคำสั่งผู้ใช้ |
| เกณฑ์ "แมส" | 3× median / decile 0.9 | **gate ก่อน แล้วใช้ PERCENT_RANK ภายในหน้าต่างอายุ + เกณฑ์สัมบูรณ์** | ข้อมูลจริง median eng = 0-2 ใน 5/7 กลุ่ม |
| FTS5 trigram | สร้างตั้งแต่แรก | **เลื่อนไปเฟส 4** (ยังไม่มีฟีเจอร์ไหนใช้ + กิน ~500 MB) | ประหยัดดิสก์ที่ตึงอยู่แล้ว |

---

## 1. เฟส 0 — Probe (บังคับ ห้ามข้าม) `fb_posts_probe.py`

**เหตุผล:** ทั้ง Tier A ตั้งอยู่บนสมมติฐานว่า GraphQL body มี caption/เวลา/รูป ซึ่ง **ยังไม่มีหลักฐานในเครื่องนี้** (`data/fb_mass_raw/` มีไฟล์เดียว 233 ไบต์ เป็น empty dump) และ `harvest()` ปัจจุบันเก็บแค่ 6 คีย์ตัวเลข

รัน 1 กลุ่ม dump body ดิบลง `data/fb_posts_probe/` แล้วออกรายงานตอบ 8 ข้อ **พร้อมเกณฑ์ผ่าน**:

| # | คำถาม | เกณฑ์ผ่าน | ถ้าไม่ผ่าน |
|---|---|---|---|
| P1 | แยก story node ได้ไหม (`__typename":"Story"` / edges) และ 1 node มี `message.text` ตัวเดียวไหม | ≥95% ของ node มี message ≤1 | เลิกทำ Tier A caption จากฟีด → caption ต้องมาจาก permalink (แจ้งผู้ใช้ว่าเวลาพุ่ง 5 เท่า) |
| P2 | `creation_time` ต่อ story | ≥80% | ตัดกราฟชั่วโมง/วัน ออกจาก UI ตั้งแต่ต้น (ห้ามโชว์ช่องว่าง) |
| P3 | `reaction_count`/`share_count`/`total_comment_count` เคยเป็น **string** ไหม ที่ยอดเท่าไร | บันทึกค่าจริง | ต้องแก้ regex ทั้ง 3 ตัวให้รับ `"?(\d+)"?` (ตอนนี้มีแค่ `VIEW_RE` ที่รับ) |
| P4 | คีย์ยอดวิวจริงชื่ออะไร (ปัจจุบันจับได้ **0/2,143 โพสต์**) | ระบุคีย์ได้ | `views` เป็น NULL ถาวร + ห้าม log ว่า "วิดีโอ 0" |
| P5 | `?sorting_setting=CHRONOLOGICAL` ติดหลัง redirect ไหม + posted_at ลดตาม feed order (Spearman ≥0.8) | ผ่าน | ตั้ง `feed_sort='relevance'` และ **ห้ามวิเคราะห์สูตร** จนกว่าจะแก้ได้ |
| P6 | รูป: `httpx` + `Referer: https://www.facebook.com/` โหลดได้โดยไม่ต้องมีคุกกี้ไหม · ถอด `oe=` เป็นเวลาหมดอายุได้ไหม · ลองซ้ำที่ +24/+48h | โหลดได้ + รู้อายุ | ต้องโหลดผ่าน `context.request` = กินคิวเบราว์เซอร์ ต้องคิดเวลาเพิ่ม |
| P7 | คอมเมนต์: ได้ numeric fbid ไหม · มี timestamp สัมบูรณ์ไหม · สลับเป็น "ความคิดเห็นทั้งหมด/ใหม่ที่สุด" ได้ไหม · โครง reply | fbid ≥70% | ปิดฟีเจอร์ "คนซ้ำข้ามกลุ่ม" และ repeat rate |
| P8 | สัดส่วนโพสต์ที่เจอ URL แต่หาตัวเลขไม่เจอ (ปัจจุบันถูก `continue` ทิ้งเงียบ ที่ `fb_mass_finder.py:292-294`) | ≤15% | ปรับ PAIR_WINDOW จากข้อมูลจริง ไม่ใช่ค่า 6000 ที่มาจาก dump เดียว |

ผลลัพธ์ probe → เขียนเป็น **golden fixtures** ใน `tests/fixtures/` แล้ว `tests/test_fb_posts_parse.py` ต้องผ่านก่อนเขียน collector

---

## 2. สถาปัตยกรรมโปรเซส / การกันชนกัน

```
fb_mass_bot.py (โปรเซสเดิม, getUpdates ตัวเดียว, msvcrt lock เดิม, heartbeat เดิม)
├── thread: _kw_worker_loop   (ของเดิม)               prio 1
├── thread: posts_worker      (ใหม่ = fb_posts_worker) prio 2
├── thread: watchdog          (ใหม่)
└── on_command (/find /add /test /posts ...)          prio 0
        ↓ ทุกคนขอเบราว์เซอร์ผ่านตัวเดียว
   BrowserBroker.acquire(prio, timeout)   ← แทนที่ _busy ดิบ
        ↓
   mf.launch_bot_browser(pw, farm, entry, lock_timeout=900)  ← เพิ่มพารามิเตอร์
```

**กติกาแข็ง 6 ข้อ**

1. **ห้ามครอบ `bot_lock` ซ้อน** — `launch_bot_browser` ถือเองอยู่แล้วตลอดอายุ context การครอบอีกชั้นจะ deadlock ตัวเองเมื่อขอคนละเธรด (`studio_shared.py:118-120,131` จดกับดักนี้ไว้แล้ว) → **แก้ที่ต้นทาง: เพิ่ม `lock_timeout` เป็นพารามิเตอร์ของ `launch_bot_browser`**
2. **ห้ามปล่อยล็อกขณะ context ยังเปิด** — 1 slice = เปิด Chrome → ทำงาน → ปิด context → ปล่อย (จ่ายค่าเปิด ~15 วิ/slice แลกความปลอดภัย)
3. **ขนาด slice**: feed = 1 กลุ่ม (≤18 นาที) · comments = ≤10 permalink (≤6 นาที) · media = ไม่ใช้เบราว์เซอร์เลย (httpx)
4. **posts_worker ไม่แตะเบราว์เซอร์** ถ้า `fb_kw_state["queue"]` ไม่ว่าง เว้นแต่ผู้ใช้สั่ง `/posts coexist on` (default = off) → งาน 23 คำ × 2 ช่วงที่ผู้ใช้เพิ่งสั่งเดินจบก่อน
5. **แพตช์บังคับใน `fb_mass_bot.py`**: `_kw_run_next_test` ต้องจับ `studio_shared.BotBusy` **แยกก่อน** `except Exception` แล้ว `state["queue"].insert(0, group)` แทน `finish("failed")` — ของเดิมยัด gid ลง `sent` ถาวร = **กลุ่มหายตลอดกาล** (คำนวณแล้วเผาได้ ~107 กลุ่ม/วัน ถ้าปล่อยไว้)
6. **Preflight ทุกครั้งก่อนเปิด Chrome**: หา process ที่ CommandLine มี `--user-data-dir=<โปรไฟล์ Bot10>` ถ้าไม่ใช่ลูกเรา → kill + ลบ `SingletonLock/SingletonCookie/SingletonSocket` + `run_event(code='orphan_chrome_killed')` (`find_bot()` มองไม่เห็น Chrome ที่ Playwright เปิด เพราะมันดู PID จาก `farm.launch()`; เครื่องนี้มี chrome.exe 47 ตัว ไล่ด้วยตาไม่ได้)

**Watchdog (แยกจาก heartbeat)** — heartbeat เดิมพิสูจน์แค่ "โปรเซสไม่ตาย" ไม่ใช่ "งานเดิน"
```
posts_worker เขียน store.set_progress(ts, stage, gid, n)  ทุกครั้งที่ commit จริง
watchdog: ถ้า now - last_progress > 300s ระหว่าง status='running'
   → log + Telegram + kill chrome.exe ตาม context.browser.process.pid → โยน exception ให้เธรดงานตายจริง
   → ถ้ายังค้างอีก 120s → os._exit(1) (keeper ใน app.py ปลุกใหม่)
```

**Telegram** — ห้ามมี getUpdates ตัวที่สอง คำสั่งทั้งหมดรับที่ `fb_mass_bot.on_command` แล้วเขียนธงลง `runstate` / สร้างแถว `work_item` (โปรเซสเดียวกัน อ่านตรงได้ แต่เขียนลงฐานเพื่อให้รอดรีสตาร์ต)

---

## 3. ที่เก็บ

### 3.1 ข้อจำกัดจริงที่ต้องยึด

* **C: เป็นถังเดียว** — `Win32_LogicalDisk`: C: total 510,544,646,144 B, G: total 510,544,646,144 B (เท่ากันเป๊ะ) · `Get-Volume` เห็นแค่ C: · GoogleDriveFS แคชบน C: → **ห้ามนับ G: เป็นพื้นที่เพิ่ม ห้ามวาง `.db` บน G:**
* `disk_guard()` ต้องตรวจ **ทุกวอลุ่มที่เกี่ยวข้อง**: ไดรฟ์ของ `.db` (+`-wal`,`-shm`), ไดรฟ์ของ `data/bot_profiles/`, ไดรฟ์ของ media_root — และ **ถ้า total เท่ากัน ให้ยุบเป็นถังเดียวแล้วแจ้ง Telegram**
* `/posts root <path>` ต้องปฏิเสธพาธที่อยู่วอลุ่มเดียวกับ C: เว้นแต่ `--force` (ตรวจด้วย `Get-Volume`/`GetVolumeInformationW` เทียบ serial ไม่ใช่เชื่อ `disk_usage`)
* Chrome cache: เติม `--disk-cache-size=536870912 --media-cache-size=268435456` ใน `_open_persistent` และ **ลบ `Default/Cache`, `Default/Code Cache`, `GPUCache` ทุกครั้งที่ปิด context ระหว่างกลุ่ม** แล้ว log ว่าคืนมากี่ MB (โปรไฟล์ Bot10 = 808 MB ใน 5 วัน = ~160 MB/วัน จากงานที่เบากว่านี้)

### 3.2 โครงไฟล์รูป

```
<media_root.path>/<sha[0:2]>/<sha[2:4]>/<sha256>.webp
```
* ฐานเก็บ `root_id` + `rel_path` เท่านั้น ย้ายไดรฟ์ = `UPDATE media_root SET path=...` แถวเดียว
* **เขียนแบบ atomic**: `<sha>.webp.tmp` → `flush()+os.fsync()` → `os.replace()` → **แล้วค่อย** `INSERT media_blob` (ไฟล์ครบก่อนฐานรู้จัก)
* `fb_posts_media.py --verify` ไล่เทียบ `os.path.getsize` กับ `media_blob.bytes` ทั้งราก (เร็ว) → ไม่ตรง = `state='pending'` คืน · รันอัตโนมัติเมื่อบูตแบบไม่ได้ปิดสวย (marker file)
* dedup 3 ชั้น: `url_key` (ตัด query) → `sha256` (หลังย่อ) → `UNIQUE(root_id, rel_path)`
* **avatar ปิดโดยปริยาย** (PII + คุณค่าต่ำ) เก็บแค่ `profile_url`

---

## 4. Schema SQL เต็ม (`data/fb_posts_schema.sql`)

รันด้วย `conn.executescript()` ตอนบูตทุกครั้ง (idempotent) — SQLite 3.39.4 บนเครื่องนี้รองรับครบ

```sql
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;
PRAGMA synchronous  = NORMAL;
PRAGMA busy_timeout = 30000;
PRAGMA wal_autocheckpoint = 1000;
PRAGMA journal_size_limit = 67108864;   -- กัน -wal โตไม่จำกัด

CREATE TABLE IF NOT EXISTS schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL) STRICT;
INSERT OR IGNORE INTO schema_meta(key,value) VALUES ('schema_version','1');

CREATE TABLE IF NOT EXISTS runstate (k TEXT PRIMARY KEY, v TEXT NOT NULL DEFAULT '') STRICT;
INSERT OR IGNORE INTO runstate(k,v) VALUES
 ('paused','0'),('pause_reason',''),('coexist','0'),
 ('day_key',''),('day_groups','0'),('day_permalinks','0'),
 ('progress_ts','0'),('progress_note','');

-- ───────────── ที่เก็บรูป ─────────────
CREATE TABLE IF NOT EXISTS media_root (
  root_id     INTEGER PRIMARY KEY,
  label       TEXT NOT NULL UNIQUE,
  path        TEXT NOT NULL,
  kind        TEXT NOT NULL CHECK (kind IN ('local','removable','network','cloud_sync')),
  volume_id   TEXT,                                  -- serial ของวอลุ่ม กันนับพื้นที่ซ้ำ
  writable    INTEGER NOT NULL DEFAULT 1 CHECK (writable IN (0,1)),
  floor_bytes INTEGER NOT NULL DEFAULT 8589934592,
  quota_bytes INTEGER,
  used_bytes  INTEGER NOT NULL DEFAULT 0,
  added_at    INTEGER NOT NULL DEFAULT (unixepoch())
) STRICT;

CREATE TABLE IF NOT EXISTS media_blob (
  sha256   TEXT PRIMARY KEY,
  root_id  INTEGER NOT NULL REFERENCES media_root(root_id),
  rel_path TEXT NOT NULL,
  bytes    INTEGER NOT NULL,
  width    INTEGER, height INTEGER,
  mime     TEXT NOT NULL DEFAULT 'image/webp',
  variant  TEXT NOT NULL CHECK (variant IN ('thumb','full','avatar')),
  stored_at INTEGER NOT NULL DEFAULT (unixepoch()),
  UNIQUE (root_id, rel_path)
) STRICT;

-- ───────────── กลุ่ม / คน ─────────────
CREATE TABLE IF NOT EXISTS fb_group (
  group_id  INTEGER PRIMARY KEY,
  gid       TEXT NOT NULL UNIQUE,
  name      TEXT NOT NULL,
  url       TEXT NOT NULL,
  keyword   TEXT,
  band      TEXT NOT NULL DEFAULT 'unknown'
            CHECK (band IN ('10k-50k','50k-100k','100k+','unknown')),
  band_src  TEXT NOT NULL DEFAULT 'derived'          -- whitelist ไม่มีคีย์ band สักใบ (0/107)
            CHECK (band_src IN ('whitelist','derived','none')),
  group_kind TEXT NOT NULL DEFAULT 'unknown'         -- marketplace|community|unknown
            CHECK (group_kind IN ('marketplace','community','unknown')),
  is_legacy INTEGER NOT NULL DEFAULT 0,              -- 7 ใบใน whitelist ที่ over/avg = null
  is_active INTEGER NOT NULL DEFAULT 1,
  seq       INTEGER NOT NULL DEFAULT 1000,           -- ลำดับ pipeline (กลุ่มมาก่อน = ทำก่อน)
  first_seen INTEGER NOT NULL DEFAULT (unixepoch())
) STRICT;
CREATE INDEX IF NOT EXISTS ix_group_name ON fb_group(name);

CREATE TABLE IF NOT EXISTS group_snapshot (
  group_id INTEGER NOT NULL REFERENCES fb_group(group_id) ON DELETE CASCADE,
  observed_at INTEGER NOT NULL,
  members INTEGER, members_raw TEXT, members_is_approx INTEGER NOT NULL DEFAULT 1,
  name TEXT,
  PRIMARY KEY (group_id, observed_at)
) STRICT, WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS fb_person (
  person_id  INTEGER PRIMARY KEY,
  person_key TEXT NOT NULL UNIQUE,     -- 'fb:<id>' | 'u:<sha1(path ของ profile_url ตัด query)>' | 'w:<sha1(ชื่อ)>'
  key_kind   TEXT NOT NULL CHECK (key_kind IN ('fbid','url','weak')),
  display_name TEXT, profile_url TEXT,
  avatar_sha256 TEXT REFERENCES media_blob(sha256),
  seller_score REAL,                   -- 0..1 จาก heuristic (ลิงก์/เบอร์/ไลน์/แท็กเปล่า/สั้นมาก)
  first_seen INTEGER NOT NULL DEFAULT (unixepoch()), last_seen INTEGER
) STRICT;
-- ห้ามใช้ URL รูปโปรไฟล์เป็นส่วนของกุญแจ (signature หมุนทุก request)

-- ───────────── รอบเก็บ / เหตุการณ์ ─────────────
CREATE TABLE IF NOT EXISTS collect_run (
  run_id INTEGER PRIMARY KEY,
  group_id INTEGER NOT NULL REFERENCES fb_group(group_id) ON DELETE CASCADE,
  stage TEXT NOT NULL CHECK (stage IN ('feed','media','comments','verify')),
  started_at INTEGER NOT NULL DEFAULT (unixepoch()), finished_at INTEGER,
  status TEXT NOT NULL DEFAULT 'running'
         CHECK (status IN ('running','done','partial','failed','aborted','blocked')),
  stop_reason TEXT CHECK (stop_reason IN
         ('target','idle','max_scroll','trip','error','quota','disk',NULL)),
  feed_sort TEXT CHECK (feed_sort IN ('chronological','relevance','unknown',NULL)),
  target_posts INTEGER,
  url_seen INTEGER NOT NULL DEFAULT 0,          -- POST_URL_RE ไม่ซ้ำที่เจอ
  post_kept INTEGER NOT NULL DEFAULT 0,
  post_dropped_no_metric INTEGER NOT NULL DEFAULT 0,
  post_foreign INTEGER NOT NULL DEFAULT 0,      -- group_key ไม่ตรงกลุ่มที่กำลังเก็บ
  caption_ok INTEGER NOT NULL DEFAULT 0,
  time_ok INTEGER NOT NULL DEFAULT 0,
  parse_fail INTEGER NOT NULL DEFAULT 0,
  drain_total INTEGER NOT NULL DEFAULT 0,
  verify_ok INTEGER NOT NULL DEFAULT 0, verify_total INTEGER NOT NULL DEFAULT 0,
  tool_version TEXT NOT NULL, error TEXT
) STRICT;

CREATE TABLE IF NOT EXISTS run_event (
  event_id INTEGER PRIMARY KEY,
  run_id INTEGER REFERENCES collect_run(run_id) ON DELETE CASCADE,
  group_id INTEGER REFERENCES fb_group(group_id) ON DELETE CASCADE,
  at INTEGER NOT NULL DEFAULT (unixepoch()),
  level TEXT NOT NULL CHECK (level IN ('info','warn','error','block')),
  code TEXT NOT NULL, detail TEXT
) STRICT;
CREATE INDEX IF NOT EXISTS ix_event_code ON run_event(code, at DESC);

-- ───────────── โพสต์ ─────────────
CREATE TABLE IF NOT EXISTS fb_post (
  post_id INTEGER PRIMARY KEY,
  group_id INTEGER NOT NULL REFERENCES fb_group(group_id) ON DELETE CASCADE,
  fb_post_id TEXT NOT NULL,
  src_group_key TEXT NOT NULL,                 -- group_key ที่อ่านได้จริงจาก URL
  url TEXT NOT NULL,
  author_id INTEGER REFERENCES fb_person(person_id),
  posted_at INTEGER,
  posted_at_src TEXT CHECK (posted_at_src IN ('graphql','absolute','relative','none')),
  post_kind TEXT NOT NULL DEFAULT 'unknown'
    CHECK (post_kind IN ('text','photo','album','video','link','share','unknown')),
  kind_src TEXT NOT NULL DEFAULT 'unknown' CHECK (kind_src IN ('typename','guess','unknown')),
  is_pinned INTEGER NOT NULL DEFAULT 0,
  is_shared INTEGER NOT NULL DEFAULT 0,
  caption TEXT,                                 -- NULL = แกะไม่ได้ ≠ '' = โพสต์รูปเปล่า
  caption_src TEXT CHECK (caption_src IN ('story_json','permalink','regex_near',NULL)),
  caption_truncated INTEGER NOT NULL DEFAULT 0,
  caption_sha256 TEXT, caption_chars INTEGER,
  feed_seen_count INTEGER NOT NULL DEFAULT 0,   -- โผล่กี่รอบเลื่อน (ใช้ตรวจปักหมุด)
  feed_first_round INTEGER,
  verify_state TEXT NOT NULL DEFAULT 'unchecked'
    CHECK (verify_state IN ('unchecked','ok','mismatch')),
  comments_state TEXT NOT NULL DEFAULT 'pending'
    CHECK (comments_state IN ('pending','done','partial','failed','skipped','gone')),
  comments_attempts INTEGER NOT NULL DEFAULT 0,
  comments_expected INTEGER, comments_captured INTEGER,
  comments_toplevel_captured INTEGER,
  comment_sort TEXT CHECK (comment_sort IN ('chronological','ranked','unknown',NULL)),
  comments_stop_reason TEXT,
  replies_expanded INTEGER NOT NULL DEFAULT 0,
  media_state TEXT NOT NULL DEFAULT 'pending'
    CHECK (media_state IN ('pending','done','failed','skipped','no_media','expired')),
  first_run_id INTEGER, last_run_id INTEGER, last_error TEXT,
  UNIQUE (group_id, fb_post_id)
) STRICT;
CREATE INDEX IF NOT EXISTS ix_post_group_time ON fb_post(group_id, posted_at DESC);
CREATE INDEX IF NOT EXISTS ix_post_todo_cmt   ON fb_post(group_id, comments_state, comments_attempts);

CREATE TABLE IF NOT EXISTS post_metric (
  post_id INTEGER NOT NULL REFERENCES fb_post(post_id) ON DELETE CASCADE,
  run_id  INTEGER NOT NULL REFERENCES collect_run(run_id) ON DELETE CASCADE,
  observed_at INTEGER NOT NULL,
  age_at_observe INTEGER,                       -- วินาที; NULL ถ้าไม่รู้ posted_at
  reactions INTEGER, comments INTEGER, shares INTEGER, views INTEGER,
  feed_rank INTEGER, seen_count INTEGER NOT NULL DEFAULT 1,
  metric_src TEXT NOT NULL CHECK (metric_src IN ('story_json','regex_near','borrowed')),
  pair_dist INTEGER,                            -- ระยะตัวอักษรที่ใช้จับคู่ (regex เท่านั้น)
  is_latest INTEGER NOT NULL DEFAULT 1,
  engagement INTEGER GENERATED ALWAYS AS (
     CASE WHEN reactions IS NULL THEN NULL
          ELSE reactions + COALESCE(comments,0) + COALESCE(shares,0) END) STORED,
  metric_complete INTEGER GENERATED ALWAYS AS (
     CASE WHEN reactions IS NOT NULL AND comments IS NOT NULL
               AND shares IS NOT NULL AND metric_src='story_json' THEN 1 ELSE 0 END) STORED,
  PRIMARY KEY (post_id, run_id)
) STRICT;
CREATE INDEX IF NOT EXISTS ix_metric_latest ON post_metric(post_id) WHERE is_latest=1;

CREATE TABLE IF NOT EXISTS post_media (
  post_id INTEGER NOT NULL REFERENCES fb_post(post_id) ON DELETE CASCADE,
  idx INTEGER NOT NULL,
  src_url TEXT NOT NULL, url_key TEXT NOT NULL,
  src_seen_at INTEGER NOT NULL, url_exp INTEGER,     -- จาก oe= (hex→unix)
  sha256 TEXT REFERENCES media_blob(sha256),
  state TEXT NOT NULL DEFAULT 'pending'
    CHECK (state IN ('pending','stored','skipped','skip_disk','failed','expired')),
  attempts INTEGER NOT NULL DEFAULT 0, last_error TEXT,
  PRIMARY KEY (post_id, idx)
) STRICT;
CREATE INDEX IF NOT EXISTS ix_postmedia_state ON post_media(state, attempts);

-- ───────────── คอมเมนต์ ─────────────
CREATE TABLE IF NOT EXISTS fb_comment (
  comment_id INTEGER PRIMARY KEY,
  post_id INTEGER NOT NULL REFERENCES fb_post(post_id) ON DELETE CASCADE,
  fb_comment_id TEXT NOT NULL,
  parent_id INTEGER REFERENCES fb_comment(comment_id) ON DELETE CASCADE,
  person_id INTEGER REFERENCES fb_person(person_id),
  body TEXT, body_chars INTEGER,
  created_at INTEGER,
  created_at_src TEXT CHECK (created_at_src IN ('absolute','relative','none')),
  created_at_raw TEXT,
  depth INTEGER NOT NULL DEFAULT 0, seq INTEGER,
  likes INTEGER, likes_is_approx INTEGER NOT NULL DEFAULT 0,   -- "1.2 พัน"
  first_run_id INTEGER,
  UNIQUE (post_id, fb_comment_id)
) STRICT;
CREATE INDEX IF NOT EXISTS ix_comment_post ON fb_comment(post_id, seq);
CREATE INDEX IF NOT EXISTS ix_comment_person ON fb_comment(person_id);

CREATE TABLE IF NOT EXISTS comment_media (
  comment_id INTEGER NOT NULL REFERENCES fb_comment(comment_id) ON DELETE CASCADE,
  idx INTEGER NOT NULL, src_url TEXT NOT NULL, url_key TEXT NOT NULL,
  src_seen_at INTEGER NOT NULL, url_exp INTEGER,
  sha256 TEXT REFERENCES media_blob(sha256),
  state TEXT NOT NULL DEFAULT 'pending'
    CHECK (state IN ('pending','stored','skipped','skip_disk','failed','expired')),
  attempts INTEGER NOT NULL DEFAULT 0, last_error TEXT,
  PRIMARY KEY (comment_id, idx)
) STRICT;

-- ───────────── คิวงาน ─────────────
CREATE TABLE IF NOT EXISTS work_item (
  work_id INTEGER PRIMARY KEY,
  group_id INTEGER NOT NULL REFERENCES fb_group(group_id) ON DELETE CASCADE,
  stage TEXT NOT NULL CHECK (stage IN ('feed','verify','media','comments','analyze')),
  priority INTEGER NOT NULL,          -- media=10 verify=15 comments=20 analyze=25 feed=30
  group_seq INTEGER NOT NULL DEFAULT 1000,
  status TEXT NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending','running','done','failed','paused','dead')),
  lease_owner TEXT, lease_until INTEGER NOT NULL DEFAULT 0,
  expire_at INTEGER,                  -- media: ต้องรันก่อนเวลานี้ ไม่งั้น URL หมดอายุ
  attempts INTEGER NOT NULL DEFAULT 0,
  env_fails INTEGER NOT NULL DEFAULT 0,   -- ล้มเพราะสภาพแวดล้อม: ไม่นับเป็น attempt
  cooldown_until INTEGER NOT NULL DEFAULT 0,
  last_error TEXT, updated_at INTEGER NOT NULL DEFAULT (unixepoch()),
  UNIQUE (group_id, stage)
) STRICT;
CREATE INDEX IF NOT EXISTS ix_work_pick ON work_item(status, cooldown_until, priority, group_seq);

-- ───────────── ฟีเจอร์ / ประชากร / บทวิเคราะห์ ─────────────
CREATE TABLE IF NOT EXISTS population (
  population_sig TEXT PRIMARY KEY,
  group_id INTEGER NOT NULL REFERENCES fb_group(group_id) ON DELETE CASCADE,
  feature_version INTEGER NOT NULL,
  computed_at INTEGER NOT NULL DEFAULT (unixepoch()),
  n_total INTEGER NOT NULL, n_scored INTEGER NOT NULL,
  n_excluded_incomplete INTEGER NOT NULL DEFAULT 0,
  n_excluded_fresh INTEGER NOT NULL DEFAULT 0,
  n_excluded_pinned INTEGER NOT NULL DEFAULT 0,
  n_excluded_notime INTEGER NOT NULL DEFAULT 0,
  eng_p50 REAL, eng_p90 REAL, tie_zero_ratio REAL,
  oldest_post_at INTEGER, newest_post_at INTEGER,
  gate_status TEXT NOT NULL CHECK (gate_status IN ('ok','too_quiet','too_sparse','no_time','unverified'))
) STRICT;

CREATE TABLE IF NOT EXISTS post_feature (
  post_id INTEGER NOT NULL REFERENCES fb_post(post_id) ON DELETE CASCADE,
  population_sig TEXT NOT NULL REFERENCES population(population_sig) ON DELETE CASCADE,
  caption_chars INTEGER, line_count INTEGER, emoji_count INTEGER, hashtag_count INTEGER,
  has_image INTEGER NOT NULL DEFAULT 0, image_count INTEGER NOT NULL DEFAULT 0,
  has_video INTEGER NOT NULL DEFAULT 0, has_link INTEGER NOT NULL DEFAULT 0,
  has_price INTEGER NOT NULL DEFAULT 0, has_phone INTEGER NOT NULL DEFAULT 0,
  has_question INTEGER NOT NULL DEFAULT 0, has_cta INTEGER NOT NULL DEFAULT 0,
  hour_of_day INTEGER, dow INTEGER, age_days REAL, age_bucket TEXT,
  eng_latest INTEGER, eng_per_day REAL,
  eng_pct_in_window REAL,               -- PERCENT_RANK ภายใน (group, age_bucket)
  eng_tie_size INTEGER,
  bucket TEXT CHECK (bucket IN ('top','mid','bottom',NULL)),
  excluded_reason TEXT,                 -- incomplete|too_fresh|pinned|no_time|author_cap|dup_caption
  PRIMARY KEY (post_id, population_sig)
) STRICT;

CREATE TABLE IF NOT EXISTS analysis (
  analysis_id INTEGER PRIMARY KEY,
  group_id INTEGER NOT NULL REFERENCES fb_group(group_id) ON DELETE CASCADE,
  kind TEXT NOT NULL CHECK (kind IN ('content_formula','audience','summary')),
  schema_version INTEGER NOT NULL,
  population_sig TEXT NOT NULL,
  input_sig TEXT NOT NULL,             -- sha256(sorted post_id + population_sig + prompt_version) ห้ามใส่ run_id
  model TEXT, created_at INTEGER NOT NULL DEFAULT (unixepoch()),
  n_posts INTEGER, n_comments_used INTEGER, n_authors_used INTEGER,
  tier_b_done INTEGER, tier_b_target INTEGER,
  dropped_rules INTEGER NOT NULL DEFAULT 0,
  in_tokens INTEGER, out_tokens INTEGER, cost_usd REAL,
  payload TEXT NOT NULL CHECK (json_valid(payload)),
  UNIQUE (group_id, kind, schema_version, input_sig)
) STRICT;

CREATE TABLE IF NOT EXISTS person_attr (
  person_id INTEGER NOT NULL REFERENCES fb_person(person_id) ON DELETE CASCADE,
  attr TEXT NOT NULL, value TEXT NOT NULL, confidence REAL,
  source TEXT NOT NULL CHECK (source IN ('heuristic','llm','observed')),
  updated_at INTEGER NOT NULL DEFAULT (unixepoch()),
  PRIMARY KEY (person_id, attr)
) STRICT;                              -- ลบชั้นอนุมานทิ้งได้ด้วย DELETE เดียว

CREATE TABLE IF NOT EXISTS person_group_activity (
  person_id INTEGER NOT NULL REFERENCES fb_person(person_id) ON DELETE CASCADE,
  group_id INTEGER NOT NULL REFERENCES fb_group(group_id) ON DELETE CASCADE,
  comments INTEGER NOT NULL DEFAULT 0, first_at INTEGER, last_at INTEGER,
  PRIMARY KEY (person_id, group_id)
) STRICT, WITHOUT ROWID;

-- ตารางสรุปสำหรับหน้าเว็บ (ห้ามให้เว็บแตะ post_metric ตรงๆ)
CREATE TABLE IF NOT EXISTS group_rollup (
  group_id INTEGER PRIMARY KEY REFERENCES fb_group(group_id) ON DELETE CASCADE,
  computed_at INTEGER NOT NULL,
  posts INTEGER, posts_scored INTEGER, posts_with_comments INTEGER,
  members INTEGER, eng_p50 REAL, eng_p90 REAL, eng_max INTEGER,
  comment_like_ratio REAL, best_hour INTEGER, best_dow INTEGER,
  distinct_commenters INTEGER, repeat_rate REAL, buying_signal_rate REAL,
  seller_ratio REAL, gate_status TEXT, verify_rate REAL,
  oldest_post_at INTEGER, newest_post_at INTEGER, analyzed_at INTEGER
) STRICT;

-- baseline ข้ามกลุ่ม: กันบทวิเคราะห์ 200 กลุ่มพูดเหมือนกันหมด
CREATE TABLE IF NOT EXISTS global_baseline (
  feature TEXT NOT NULL, group_kind TEXT NOT NULL,
  median_lift REAL, p25 REAL, p75 REAL, n_groups INTEGER,
  computed_at INTEGER NOT NULL,
  PRIMARY KEY (feature, group_kind)
) STRICT;
```

**FTS5 trigram: ไม่สร้างในเฟส 1** (สร้างทีหลังด้วย `rebuild` ได้เสมอ · บังคับ query ≥3 อักษรที่ฝั่ง API)

### 4.1 คำสั่งสำคัญ

```sql
-- จองงาน (atomic, ทดสอบแล้วยึดซ้ำไม่ได้ · lease หมดอายุยึดคืนเอง)
UPDATE work_item SET status='running', lease_owner=:me, lease_until=:now+1200,
       attempts=attempts+1, updated_at=:now
WHERE work_id = (SELECT work_id FROM work_item
   WHERE status IN ('pending','running') AND cooldown_until<=:now AND lease_until<:now
     AND (expire_at IS NULL OR expire_at>:now)
   ORDER BY priority, group_seq, work_id LIMIT 1)
RETURNING work_id, group_id, stage;

-- reaper (ตอนบูต + ทุก 60 วิ)
UPDATE work_item SET status='pending', lease_owner=NULL
WHERE status='running' AND lease_until < unixepoch();

-- upsert metric: เลือกค่าที่ "ระยะจับคู่ใกล้สุด" ไม่ใช่ max()
INSERT INTO post_metric(post_id,run_id,observed_at,age_at_observe,reactions,comments,shares,
                        views,feed_rank,metric_src,pair_dist,seen_count)
VALUES (...)
ON CONFLICT(post_id,run_id) DO UPDATE SET
  reactions = CASE WHEN excluded.metric_src='story_json'
                   OR excluded.pair_dist < COALESCE(post_metric.pair_dist,1<<30)
                   THEN excluded.reactions ELSE post_metric.reactions END,
  comments  = CASE WHEN excluded.metric_src='story_json'
                   OR excluded.pair_dist < COALESCE(post_metric.pair_dist,1<<30)
                   THEN excluded.comments ELSE post_metric.comments END,
  shares    = CASE WHEN excluded.metric_src='story_json'
                   OR excluded.pair_dist < COALESCE(post_metric.pair_dist,1<<30)
                   THEN excluded.shares ELSE post_metric.shares END,
  metric_src = CASE WHEN excluded.metric_src='story_json' THEN 'story_json' ELSE post_metric.metric_src END,
  pair_dist  = MIN(COALESCE(post_metric.pair_dist,1<<30), COALESCE(excluded.pair_dist,1<<30)),
  seen_count = post_metric.seen_count + 1,
  observed_at= excluded.observed_at;

-- caption: ทับได้เฉพาะเมื่อมาจากแหล่งที่ดีกว่าหรือยาวกว่า
UPDATE fb_post SET caption=:c, caption_src=:s
WHERE post_id=:id AND (
      caption IS NULL
   OR (:s='permalink' AND caption_src!='permalink')
   OR (caption_src=:s AND length(:c) > length(caption)));
```

---

## 5. ตัวเก็บ (`fb_posts_collect.py` + `fb_posts_parse.py`)

### 5.1 การแกะข้อมูล — กฎเหล็ก

1. **ห้ามเรียก `response.text()` ใน event handler** (greenlet ชนกัน โปรเซสตายเงียบ) — จดตัว response แล้ว `drain()` นอก handler เหมือนเดิม
2. **ห้าม `harvest(page.content())` ทุกรอบเลื่อน** — เรียกครั้งเดียวตอนเปิดหน้า ที่เหลืออ่านจาก GraphQL อย่างเดียว (ของเดิม 250 รอบ × regex บน HTML หลาย MB = ต้นทุน O(รอบ × ขนาด DOM) และเป็นตัวสร้าง max-bias)
3. **แกะแบบ story block**: ตัด body เป็น node ต่อ story แล้ว `json.loads` → ผูก `fb_post_id ↔ message.text ↔ creation_time ↔ actors ↔ attachments ↔ feedback` **ในออบเจ็กต์เดียวกัน** → `metric_src='story_json'`
4. regex เดิม (`_nearest`/`PAIR_WINDOW`) ใช้ได้เฉพาะ **ตัวเลข** และต้องติดธง `metric_src='regex_near'` + เก็บ `pair_dist`; ถ้า `pair_dist > 1500` → NULL ไม่ใช่รับเลขเพื่อนบ้าน
5. `_nearest` ต้อง **ห้ามข้าม URL โพสต์อื่น** (ส่ง list ตำแหน่ง POST_URL_RE เข้าไป ถ้ามี match ของโพสต์อื่นคั่น = ตัดทิ้ง) และ sort + `bisect` ไม่ใช่ลูปเชิงเส้น
6. **แก้ regex 3 ตัวให้รับเลข string**: `"reaction_count"\s*:\s*(?:\{\s*"count"\s*:\s*)?"?(\d+)"?` เช่นเดียวกับ share/comment (ตอนนี้มีแค่ `VIEW_RE` ที่รับ → **โพสต์ไวรัลถูกทิ้งทั้งใบ**)
7. **ห้าม `or 0`** — คืน `None` แล้วให้ฐานเก็บ NULL
8. โพสต์ที่เจอ URL แต่ไม่มีตัวเลข → **บันทึกแถวไว้** (reactions=NULL) + `post_dropped_no_metric+1` + `run_event('no_metric')` ไม่ใช่ `continue`
9. `group_key` จาก URL ต้องตรงกลุ่มที่กำลังเก็บ ไม่ตรง = ทิ้ง + `post_foreign+1` (FB แทรกยูนิต "โพสต์ที่เกี่ยวข้อง/กลุ่มแนะนำ")
10. `drain()` **ห้าม `except Exception: pass`** — นับ `parse_fail` + `drain_total` ทุกครั้ง

### 5.2 Stage FEED (~15-18 นาที/กลุ่ม)

```
1) preflight orphan chrome → BrowserBroker.acquire(prio=2)
2) mf.launch_bot_browser(..., lock_timeout=900) → mf.ensure_logged_in
3) goto(url + "?sorting_setting=CHRONOLOGICAL", timeout=90_000); ตรวจว่าพารามิเตอร์ยังอยู่หลัง redirect
   ไม่อยู่ → feed_sort='relevance' → เก็บต่อได้ แต่ห้ามวิเคราะห์สูตร (gate จะกัน)
4) keyboard.press("End") + sleep uniform(2.5, 5.5)
5) drain() ทุกรอบ → parse story blocks → บัฟเฟอร์
6) ทุก 25 โพสต์ใหม่: 1 transaction (upsert fb_post + post_metric + post_media(pending)) + COMMIT
   + renew lease + store.set_progress()
7) เงื่อนไขจบ: seen_this_run >= 1000  |  idle 4 รอบ  |  รอบ 250  |  trip
   → บันทึก stop_reason ให้ชัด (แยก "ครบ" ออกจาก "ชนเพดาน")
8) ตรวจปักหมุด: feed_seen_count / รอบทั้งหมด > 0.9 → is_pinned=1
9) จบ: อัปเดตตัวนับทั้งหมดใน collect_run → สร้าง work_item verify/media/comments (group_seq เดิม)
```
**Resume**: เปิดใหม่ต้องเลื่อนจากบนสุดเสมอ (FB ไม่มี cursor) — เก็บ watermark `oldest_posted_at` ต่อกลุ่ม แล้วเลื่อนจนผ่าน watermark ถึงจะนับ `seen_this_run` ใหม่ · **สื่อสารตรงๆ ว่า resume จ่ายเวลาเลื่อนซ้ำ ไม่ใช่ "เสียแค่ 25 โพสต์"**

### 5.3 Stage VERIFY (~7 นาที/กลุ่ม) — ด่านที่ตรวจ "แกะถูกโพสต์ไหม"

สุ่ม 10 โพสต์ → เปิด permalink → เทียบ caption 80 ตัวแรก + posted_at ±60 วิ + จำนวนรูป
* **≥9/10 ผ่าน** → `verify_rate` ลง rollup
* **<9/10** → `paused=1, pause_reason='verify_failed'` **หยุดทั้งระบบ** ห้ามเดินกลุ่มถัดไป (ถ้าเดินต่อจะเก็บขยะครบ 200 กลุ่มก่อนรู้ตัว)
* canary เสริม: caption ซ้ำเป๊ะกับโพสต์อื่นในกลุ่ม > 5% = สัญญาณจับคู่ผิด → trip

### 5.4 Stage MEDIA (~2-3 นาที/กลุ่ม, **ไม่ใช้เบราว์เซอร์**)

* เลือกตัวอย่าง 30 โพสต์ (ดู §6.1) + top 25 ทันทีหลัง feed → โหลดเฉพาะรูปของโพสต์เหล่านี้
* `httpx` + `Referer: https://www.facebook.com/` (P6 ยืนยันแล้ว) → Pillow ย่อ long-edge 1024 WebP q75 → sha256 → CAS atomic write
* `work_item.expire_at = src_seen_at + 12h` · เลย = `state='expired'` แล้วเข้าคิว re-harvest URL ใหม่ **ห้ามยิง 403 ซ้ำ**
* `disk_guard()` ทุก 25 ไฟล์: free < floor → `state='skip_disk'` (คนละความหมายกับ `failed`) + `paused` เฉพาะ media · **ข้อความยังเก็บต่อ**

### 5.5 Stage COMMENTS (~20-22 นาที/กลุ่ม, 30 โพสต์)

* **บังคับสลับเป็น "ความคิดเห็นทั้งหมด / ใหม่ที่สุด"** ก่อนอ่านทุกครั้ง → บันทึก `comment_sort`; สลับไม่ได้ = `comments_state='partial'` ห้ามเป็น `done`
* **กด "ดูการตอบกลับ N รายการ" ด้วย** — ไม่งั้น `parent_id` เป็น NULL ทั้งตาราง และคำถามผู้ซื้อ (ซึ่งอยู่ในเธรดตอบกลับ) หายหมด
  canary: `parent_id IS NOT NULL` = 0% ติดกัน 10 โพสต์ → trip
* เพดาน **60 คอมเมนต์ชั้นบนต่อโพสต์เท่ากันทุก bucket** (ไม่ใช่ 300) เพื่อไม่ให้โพสต์ไวรัลกลืนตัวอย่าง 92%
* `comments_expected` อ่านจากตัวเลขบนหน้า permalink ตอนนั้น **ไม่ใช่** จาก `post_metric.comments` (คนละหน่วย: `total_comment_count` นับ reply ด้วย)
* `comments_state='done'` ได้เฉพาะเมื่อ `comments_toplevel_captured >= expected_toplevel * 0.9` ไม่งั้น `partial`
* โพสต์ 404/ถูกลบ → `gone` (แยกจาก `failed`) แล้วรายงานอัตราหายแยกตาม bucket — ถ้า top หายเกิน 25% ต้องขึ้นเตือนบนหน้าเว็บว่าบทวิเคราะห์เอนเอียง
* 1 โพสต์ = 1 transaction = 1 commit · `attempts>=3` → `skipped` ถาวร นับไว้รายงาน

### 5.6 จังหวะหน่วง / โควตา / tripwire

| จุด | ค่า |
|---|---|
| รอบเลื่อนฟีด | `uniform(2.5, 5.5)` |
| หลังเปิด permalink | `uniform(4, 9)` |
| ระหว่างโพสต์ | `uniform(8, 20)` |
| ทุก 12 โพสต์ | พัก `uniform(90, 240)` |
| ระหว่างกลุ่ม | `uniform(180, 480)` |
| ช่วงเงียบ | 01:00-06:00 ไม่ทำงาน + หน้าต่างผู้ใช้ตั้งเองได้ |

**โควตา (นับใน `runstate` ต่อ `day_key` → รีสตาร์ตไม่รีเซ็ต):** ≤10 กลุ่ม/วัน · ≤500 permalink/วัน (30/กลุ่ม + headroom retry 60%)

**Tripwire — เจอข้อใดข้อหนึ่ง = `paused=1` + Telegram + `cooldown 6-12h` + ห้าม auto-resume**
1. `page.url` มี `checkpoint`/`login` · เรียก `ensure_logged_in` **ทุกกลุ่ม** ไม่ใช่ครั้งเดียวตอนเริ่ม
2. คุกกี้ `c_user` หาย
3. หน้ามี "ถูกบล็อกชั่วคราว" / "You're Temporarily Blocked" / "คุณทำสิ่งนี้เร็วเกินไป" / HTTP 429
4. **โดนหรี่เงียบ**: 5 permalink ติดได้ caption ว่าง + คอมเมนต์ 0 ทั้งที่ `post_metric.comments > 0`
5. `parse_fail / drain_total > 30%` ในกลุ่มเดียว
6. `post_dropped_no_metric / url_seen > 0.15`
7. **circuit breaker ทั่วไป**: ล้มติดกัน 5 work_item ใดๆ ก็ตาม (ไม่ต้องรู้สาเหตุ) — ตัวนี้สำคัญกว่า tripwire รายอาการรวมกัน เพราะดักเคสที่ "เปิดหน้าไม่ได้ตั้งแต่แรก" (Chrome ค้าง/ไฟดับ/เน็ตหลุด/Windows Update — เครื่องนี้ uptime 123 ชม. = รีบูตทุก ~5 วัน)

**แยก env fail ออกจาก data fail**: `env` (เปิดเบราว์เซอร์ไม่ได้/goto timeout/BotBusy) → `env_fails+1` **ไม่เพิ่ม `attempts`** ไม่มีวันกลายเป็น `dead` · มี `/posts retrydead` คืนงานเป็นชุด

---

## 6. การวิเคราะห์ (`fb_posts_features.py` + `fb_posts_analyze.py`)

### 6.1 ชั้น SQL — ตัดตัวแปรกวนก่อนคำนวณ (สำคัญที่สุด)

**ลำดับการกรอง (เขียนลง `post_feature.excluded_reason` ทุกใบ ห้ามหายเงียบ):**
1. `metric_complete=0` → `incomplete`
2. `posted_at IS NULL` → `no_time` · ถ้าเกิน 20% ของกลุ่ม → `gate_status='no_time'` **ไม่ออกสูตร**
3. อายุ < 72 ชม. ตอนสังเกต → `too_fresh` (engagement ยังไม่โตเต็ม)
4. `is_pinned=1` → `pinned` (โพสต์ปักหมุดสะสมข้ามปี ติด top decile ทุกกลุ่ม; หลักฐาน: กลุ่ม 1,002 โพสต์ อันดับ 1 = 820 อันดับ 2 = 89)
5. ต่อ author เกิน 3 ใบ/bucket → `author_cap` · `caption_sha256` ซ้ำ → `dup_caption` (ผู้ขายลงเทมเพลตเดียว 30-40 ครั้ง)

**คำนวณ:**
```sql
eng_pct_in_window = PERCENT_RANK() OVER (PARTITION BY group_id, age_bucket ORDER BY engagement)
```
* **ต้องเป็น PERCENT_RANK เท่านั้น** — `NTILE`/`ROW_NUMBER` จะกระจายค่าที่ tie กัน (โพสต์ eng=0 มี 57-67% ของกลุ่ม) ตาม rowid = ตำแหน่งในฟีด แล้ว "ความแมส" กลายเป็น "โพสต์ใหม่/เก่า"
* `eng_tie_size / n > 0.2` → `eng_pct = NULL`
* `age_bucket` ∈ (3-7d, 8-30d, 31-90d, 90d+) แล้วรวมผลภายหลัง

**Gate ก่อนออกสูตร (`population.gate_status`)** — ข้อมูลจริง: 5/7 กลุ่มมี median eng = 0, 1,002 โพสต์ล่าสุด avg 3.6 เกิน 100 แค่ 1 ใบ
| เงื่อนไข | ผล |
|---|---|
| `n_scored < 300` | `too_sparse` |
| `eng_p50 = 0` หรือ `tie_zero_ratio > 0.40` หรือ `eng_p90 < 10` | `too_quiet` |
| `posted_at` ครอบคลุม < 80% | `no_time` |
| `verify_rate < 0.9` หรือ `feed_sort != 'chronological'` | `unverified` |
| ผ่านหมด | `ok` |

ไม่ `ok` → **ไม่ยิง LLM** และหน้าเว็บขึ้นตรงๆ: *"กลุ่มนี้เงียบเกินกว่าจะสรุปสูตร — 67% ของโพสต์ได้ 0 engagement"* (ข้อมูลนี้มีค่ากับผู้ใช้มากกว่าสูตรปลอม)

**เปรียบเทียบ top vs bottom** — bucket = decile บนสุด vs decile ล่างสุด (ทั้งสองฝั่ง ไม่ใช่ 10% vs 50%)
* ต้อง `n_top ≥ 30` และ `n_bottom ≥ 30` และฟีเจอร์นั้นต้องปรากฏ ≥10 ใบทั้งสองฝั่ง
* คำนวณ **Wilson 95% CI** ของสัดส่วน → **CI ทับกัน = ตัดทิ้ง ห้ามแสดง**
  (จำลองแล้ว: สุ่ม has_image อัตราเดียวกันเป๊ะยังได้ 0.89 vs 0.96 ซึ่งจะถูกพิมพ์เป็น "สูตรที่ไม่เวิร์ก")
* **เทียบกับ `global_baseline`**: แสดงเป็น *ส่วนต่างจากค่ากลางทุกกลุ่ม* เป็นตัวหลัก — อะไรที่ไม่ต่างให้ยุบไว้ (ไม่งั้น 200 กลุ่มจะพูดเหมือนกันว่า "ควรมีรูป ควรบอกราคา")

**n-gram ไทย (3-6 ตัวอักษร)** — ไม่ต้องใช้ตัวตัดคำ แต่ต้อง:
* `df_top ≥ 20` และ `df_รวม ≥ 30` ก่อนคิด lift
* smoothing `(a+1)/(b+1)` + เรียงด้วย log-odds ไม่ใช่ lift ดิบ (ไม่งั้นได้ ∞ จากสตริงที่หายากที่สุด = เบอร์โทร/ชื่อร้าน)
* ยุบ n-gram ที่เป็น substring ของตัวยาวกว่าและ df ต่างไม่เกิน 10%
* ทิ้ง n-gram ที่มีเลข ≥3 ตัวติดกัน → ไปนับเป็น `has_price`/`has_phone` แทน

**เลือกตัวอย่าง Tier B (30 ใบ)**: `top` 12 (decile บน) · `mid` 10 (`eng_pct` 0.45-0.55) · `low` 8 (decile ล่าง) — **ทุกใบต้อง `comments > 0`** ไม่งั้นเปิดไปก็ไม่มีอะไรเก็บ · จัด bucket **ใหม่จากยอด ณ เวลาที่เปิด permalink** ไม่ยึดป้ายเดิม

### 6.2 โปรไฟล์ลูกค้า — เงื่อนไขขั้นต่ำ

* ต้องมี **≥300 คอมเมนต์ จาก ≥150 `person_key` ที่ `key_kind='fbid'`** ไม่ถึง → แสดงตัวเลขดิบ + "ข้อมูลไม่พอทำโปรไฟล์ (41 คอมเมนต์ จาก 18 คน)" **ห้ามยิง LLM**
  (ข้อมูลจริง: 320 โพสต์ได้คอมเมนต์รวม 133-329 → สเกลแล้วทั้งกลุ่มมีราว 400-1,000)
* **repeat rate / คนซ้ำข้ามกลุ่ม นับเฉพาะ `key_kind='fbid'`** และต้องแสดง % ที่ได้ fbid จริงกำกับ — ต่ำกว่า 60% ให้ซ่อนทั้งบล็อก
* **แยกคนขายออกก่อน**: `seller_score` จาก (มี URL/เบอร์/ไลน์ · เป็นแท็กชื่อล้วน · ยาว <8 ตัวอักษร) > 0.5 → ตัดออกจากโปรไฟล์ลูกค้า และรายงานคู่กัน *"คอมเมนต์ 2,431 · หลังตัดคนขาย/แท็ก เหลือ 640 จาก 210 คน"*
* **ฮิสโตแกรมชั่วโมง** ใช้เฉพาะ `created_at_src='absolute'` — ถ้าได้แต่เวลาสัมพัทธ์ **ตัดกราฟทิ้ง** ดีกว่าวาดกราฟที่วัดเวลาที่สคริปต์ตัวเองรัน (สแกนกระจุก 18:00-09:00 จะได้ "ลูกค้าตื่นตี 2" ทุกกลุ่ม)
* ทุกตัวเลขรายงาน **แยกตาม bucket** (top/mid/low) ห้ามรายงานค่ารวมค่าเดียว และระบุ n ระดับโพสต์ควบคู่ n ระดับคอมเมนต์
* PII: `person_attr` แยกตาราง ลบด้วย DELETE เดียว · avatar ปิด default · **ส่งเข้า LLM เฉพาะเนื้อคอมเมนต์ + id ย่อ (C001..) ไม่ส่งชื่อ/รูป**

### 6.3 ชั้น LLM

* 1 call/กลุ่ม · `output_config.format` json_schema (**ห้ามใช้ prefill** — Claude 4.6+ ตอบ 400)
* input: ตาราง lift ที่ผ่าน CI แล้ว + z-score เทียบ baseline + caption top 25 / bottom 15 (ตัด 300 ตัวอักษร) + คอมเมนต์ 120 อัน (ตัด 120 ตัวอักษร)
* **ห้ามส่ง post_id 16 หลักให้โมเดล** — ส่งเป็นเมนู `P01..P40`, `C001..C120` แล้ว map กลับฝั่งเรา (โมเดลพิมพ์เลข 16 หลักผิดหลักเดียว = ชิปหลักฐานกดแล้วเงียบ)
* **validate ทุกข้อ**: อ้าง label ที่ไม่มีในเมนู → **ทิ้งกฎนั้นทั้งข้อ** + `dropped_rules+1` · `dropped_rules > 20%` = ถือว่าพรอมป์พัง ขึ้นเตือน ไม่นับเป็นผล
* สั่งชัดในพรอมป์: *"ห้ามรายงานสิ่งที่ไม่ต่างจากค่ากลางทุกกลุ่ม"*
* `input_sig = sha256(sorted(post_id) + population_sig + prompt_version)` — **ห้ามใส่ run_id** (ไม่งั้นเก็บซ้ำทุกครั้ง = จ่ายซ้ำทุกครั้ง)
* บันทึก `n_posts / n_comments_used / tier_b_done / in_tokens / out_tokens / cost_usd` ทุกครั้ง

---

## 7. หน้าเว็บ (`/groups`)

**เสียบแบบหน้าแยก** เลียนแบบ `/send-link` (`app.py:2729-2736`) → `FileResponse(WEB_DIR/'groups.html', headers={'Cache-Control':'no-store'})` · `web/groups.js` เสิร์ฟผ่าน `/static` · เข้าลูป `_compute_version()` อัตโนมัติ (**ต้องรีสตาร์ต 8866** ไม่งั้นขึ้นแบนเนอร์ "คนละรุ่น") · เปิดจากมือถือต้องเติม `/groups` + `/api/groups` ลง `PUBLIC_PATHS` (`app.py:2679`)

**การเปิดฐานฝั่งเว็บ**: `sqlite3.connect(path)` ปกติ แล้ว `PRAGMA query_only=1` ทันที — **ห้ามใช้ `mode=ro`** เพราะ WAL ต้องการไฟล์ `-shm` ที่ต้องมี writer เปิดค้าง แต่เวลาที่ผู้ใช้อ่านรายงานคือเวลาที่ collector ไม่ได้รัน = จะพัง 500 เกือบ 100% · เปิด-ปิด connection **ต่อ request** ห้ามถือค้าง (ไม่งั้นกัน checkpoint จน `-wal` โต)

### 7.1 หน้าแรก = ตารางจัดอันดับข้ามกลุ่ม (ไม่ใช่ช่องค้นหาอย่างเดียว)

ผู้ใช้จำชื่อกลุ่ม 200 กลุ่มที่ชื่อคล้ายกันไม่ได้ และคำถามจริงคือ "ควรโพสต์กลุ่มไหนก่อน / กลุ่มไหนเลิกได้" ซึ่งเป็นการจัดอันดับข้ามกลุ่ม
อ่านจาก `group_rollup` 200 แถว (< 1 ms) — คอลัมน์เรียงได้ทุกช่อง:
`ชื่อ · สมาชิก(~) · แบนด์ · โพสต์ที่เก็บ · median eng · p90 · %โพสต์แมส · comment:like · คนคุยจริง · buying-signal% · ชั่วโมงดีสุด · %ทับซ้อนคนกับกลุ่มอื่น · สถานะ gate · verify_rate · เก็บล่าสุด`

### 7.2 หน้ารายงานรายกลุ่ม (drill-down) — `/api/groups/{gid}/report` คืน JSON ก้อนเดียว

1. **หัว + แถบความครบถ้วน (บนสุดเสมอ)** — *"เก็บได้ 947 จาก 1,083 โพสต์ที่เห็น (ตกหล่น 136 — หาเลขไม่เจอ) · เจาะคอมเมนต์ 27/30 · คอมเมนต์ 1,204 · เรียงตามเวลา ✓ · ตรวจสอบตรง 10/10 · เก็บ 20 ส.ค."*
2. KPI 4 ช่อง + **gate banner** ถ้าไม่ `ok`
3. **สองคอลัมน์ ✅/❌** — ทุกการ์ดต้องมี: ประโยค + ตัวเลข SQL + `n` + Wilson CI + ส่วนต่างจาก baseline + ชิปหลักฐาน 3 โพสต์ **ห้ามมีการ์ดที่ไม่มีตัวเลข**
4. กราฟ SVG inline (ไม่มี lib นอก): การกระจาย eng 10 ช่วง · median แยก `post_kind` (ถ้า `kind_src='unknown'` > 40% → **ตัดแถวนี้ทิ้งทั้งแถว** พร้อมข้อความ) · heatmap 7×24 สองชั้น (เวลาที่คนโพสต์ vs เวลาที่คนคอมเมนต์)
5. โพสต์ top 10 / bottom 10 วางคู่กัน + thumbnail จาก `/api/media/{sha256}` (validate `^[0-9a-f]{64}$`) · ไฟล์หาย = 404 + placeholder ไม่ใช่ 500 ทั้งหน้า
6. คลิกโพสต์ → กางคอมเมนต์ · ถ้าตัด ต้องขึ้น *"แสดง 60 จาก 173 (เรียงตามเวลา)"* **ห้ามทำเนียนว่าครบ**
7. โปรไฟล์ลูกค้า + ฐานคำนวณจริง + คนซ้ำข้ามกลุ่ม (เฉพาะ fbid)
8. ท้ายหน้า: `cost_usd`, model, `dropped_rules`, ปุ่ม "เก็บคอมเมนต์เพิ่ม" / "วิเคราะห์ใหม่"

**หลักการเดียวที่ห้ามผิด:** ทุกตัวเลขมาจาก SQL · ทุกประโยคตีความมีตัวเลขกำกับ · ทุกที่ที่ข้อมูลไม่ครบต้องเขียนว่าไม่ครบ

---

## 8. คำสั่ง Telegram (รับที่ `fb_mass_bot.on_command` เท่านั้น)

| คำสั่ง | ทำอะไร |
|---|---|
| `/posts` | สถานะ: คิว, กลุ่มที่กำลังทำ, ETA จากอัตราจริง, โควตาวันนี้, ดิสก์ทุกวอลุ่ม, `last_progress` |
| `/posts pilot` | รัน 3 กลุ่มครบสาย + รายงานผลตรวจ (ดู §9 จุดตรวจ) |
| `/posts start` / `pause` / `resume` / `stop` | ควบคุม (resume ต้องเป็นคำสั่งคน ห้าม auto) |
| `/posts coexist on/off` | ยอมให้แย่งเบราว์เซอร์กับ `/keyword` (default off) |
| `/posts group <ชื่อ\|gid>` | ดันกลุ่มขึ้นหัวคิว (`group_seq=0`) |
| `/posts root <path>` | ตั้ง media_root + ตรวจว่าเป็นวอลุ่มต่างจริง |
| `/posts disk` | ตัวเลขดิสก์ + ขนาด DB/-wal/โปรไฟล์ Chrome/media |
| `/posts verify <gid>` | รัน canary ซ้ำ |
| `/posts analyze <gid>` | วิเคราะห์ (เคารพ gate) |
| `/posts cost` | รวม token/cost จากตาราง `analysis` |
| `/posts retrydead` | คืน `dead`/`failed` เป็น `pending` |
| `/report <ชื่อกลุ่ม>` | ส่งการ์ดสรุป + ปุ่ม inline ไปหน้าเว็บ |

---

## 9. ลำดับเฟส + จุดตรวจ

### **เฟสแรกที่ให้ผลใช้งานได้เร็วที่สุด = Phase 1 "Pilot 3 กลุ่ม" (~3-4 ชม.)**
ผู้ใช้เปิด `/groups` เห็นรายงานสมบูรณ์ของ 3 กลุ่มจริง (สูตร + โปรไฟล์ + รูป) **ตั้งแต่วันแรก** ก่อนตัดสินใจว่าจะขยายไป 200 กลุ่มไหม

| เฟส | งาน | เวลา | จุดตรวจ (ต้องผ่านถึงไปต่อ) |
|---|---|---|---|
| **0** | `fb_posts_probe.py` 1 กลุ่ม + golden fixtures + `test_fb_posts_parse.py` | 1-2 ชม. | P1-P8 ผ่านเกณฑ์ §1 · unit test เขียว |
| **0.5** | แพตช์บังคับ: `lock_timeout` param · BotBusy→คืนคิว · regex string-number · `drain()` นับ · chrome args + purge cache · orphan preflight | 2-3 ชม. | `/find` ระหว่าง collector รัน ต้องได้คิวใน ≤3 นาที ไม่ใช่ถูกปฏิเสธ |
| **1** | store + parse + collect(feed/verify/media/comments) + features + **pilot 3 กลุ่ม** + หน้าเว็บขั้นต่ำ | 1-2 วัน + รัน 3-4 ชม. | ดูตารางล่าง |
| **2** | `analyze` + LLM (ทดสอบ 3 กลุ่มก่อน ~฿3) + baseline | 1 วัน | `dropped_rules < 20%` · ทุกการ์ดมีตัวเลข |
| **3** | ขยายทั้ง whitelist (Tier A ทุกกลุ่ม → Tier B ตามลำดับ) | 17-20 คืน | ตัวนับสุขภาพไม่ทะลุเพดาน |
| **4** | FTS5 trigram + ค้นข้อความข้ามกลุ่ม + `--archive` ย้ายรูปไป cold | ทีหลัง | ดิสก์เหลือ ≥12 GB |

**จุดตรวจ Phase 1 (SQL ตรวจได้ตรงๆ)**

| ตัวชี้วัด | เกณฑ์ | Query |
|---|---|---|
| แกะ caption ถูกโพสต์ | `verify_ok/verify_total ≥ 0.9` ทั้ง 3 กลุ่ม | `SELECT verify_ok,verify_total FROM collect_run WHERE stage='verify'` |
| caption ได้จริง | `caption_ok/post_kept ≥ 0.8` | `collect_run` |
| เวลาโพสต์ | `time_ok/post_kept ≥ 0.6` | `collect_run` |
| ตกหล่น | `post_dropped_no_metric/url_seen ≤ 0.15` | `collect_run` |
| โพสต์ต่างกลุ่ม | `post_foreign/url_seen ≤ 0.05` | `collect_run` |
| parse | `parse_fail/drain_total ≤ 0.3` | `collect_run` |
| เรียงตามเวลา | `feed_sort='chronological'` ทั้ง 3 | `collect_run` |
| คอมเมนต์ | `comment_sort='chronological'` · มี `parent_id` ไม่ NULL > 0 | `fb_comment` |
| รูป | `post_media state='stored' ≥ 85%`, `expired = 0` | `post_media` |
| resume | ฆ่าโปรเซสกลางกลุ่ม → reaper คืนงาน → รันต่อได้ไม่มีแถวซ้ำ | `SELECT COUNT(*)-COUNT(DISTINCT gid||fb_post_id) FROM fb_post` = 0 |
| ดิสก์ | ใช้เพิ่ม ≤ 60 MB/กลุ่ม (DB+รูป) | `/posts disk` |
| เวลา | ≤ 50 นาที/กลุ่มครบสาย | `collect_run` |
| กระทบงานเดิม | `/keyword` ยังเดินได้ · ไม่มี gid หลุดเข้า `sent` เพราะ BotBusy | log |

---

## 10. ตัวเลขที่ประเมิน (คำนวณใหม่ ไม่ใช่ลอกมา)

### เวลา (ต่อ 1 กลุ่ม)
| ขั้น | เวลา |
|---|---|
| feed 1,000 โพสต์ (250 รอบ × 4.0 วิ เฉลี่ย + settle) | **15-18 นาที** |
| verify 10 โพสต์ | 7 นาที |
| media 30-55 รูป (httpx ขนานกับอย่างอื่นได้) | 2-3 นาที |
| comments 30 โพสต์ (32 วิ/ใบ + พักยาว 2 ครั้ง) | **20-22 นาที** |
| **รวม + พักระหว่างกลุ่ม 5 นาที** | **≈ 50 นาที/กลุ่ม** |

* 200 กลุ่ม ≈ **167 ชม.** · หน้าต่าง 8-9 ชม./คืน + เพดาน 10 กลุ่ม/วัน → **≈ 20-24 คืน**
* ถ้าเอา Tier A อย่างเดียวก่อน (feed+verify+media, ไม่เจาะคอมเมนต์) = 27 นาที/กลุ่ม → **90 ชม. ≈ 11-12 คืน** แล้วมีสูตรคอนเทนต์ทุกกลุ่ม
* **`/keyword` 46 งานที่ผู้ใช้เพิ่งสั่ง จะกินเบราว์เซอร์ก่อน (คาด ~870 กลุ่ม × 14 นาที ≈ 3-5 สัปดาห์)** → default คือ posts_worker ไม่เริ่มจนคิวว่าง ผู้ใช้ต้องเลือกด้วย `/posts coexist on` หรือ `/kw pause`

### พื้นที่ (ถังเดียว C: เหลือ ~25.5-27 GB)
| ของ | ขนาด |
|---|---|
| `fb_posts.db` (200k โพสต์ + ~300k คอมเมนต์ + index, **ยังไม่มี FTS**) | 400-500 MB |
| `-wal` (คุมด้วย autocheckpoint + journal_size_limit) | ≤ 64 MB |
| รูป thumb 200×30×1.4×110 KB + คอมเมนต์ | **≈ 2.0-2.2 GB** |
| โปรไฟล์ Chrome (คุมด้วย cache cap + purge) | ≤ 1 GB |
| **รวมของใหม่** | **≈ 3.5-4 GB** |
| floor หยุดอัตโนมัติ | free < **8 GB** |
| FTS trigram (เฟส 4) | +500-600 MB |

### ค่า API (200 กลุ่ม, 1 call/กลุ่ม, ~20k in / 1.5k out)
| โมเดล | ต่อกลุ่ม | 200 กลุ่ม | + Batch −50% |
|---|---|---|---|
| `claude-haiku-4-5` ($1/$5) | $0.028 | $5.5 (฿190) | $2.8 (฿95) |
| **`claude-sonnet-5` โปรฯ $2/$10 (ถึง 31 ส.ค. 69)** | $0.055 | $11 (฿375) | **$5.5 (฿190)** ← แนะนำ |
| `claude-sonnet-5` ปกติ $3/$15 | $0.083 | $16.5 (฿560) | $8.3 (฿280) |
| `claude-opus-5` ($5/$25) | $0.138 | $27.5 (฿935) | $13.8 (฿470) |

* **บังคับ**: รัน `client.messages.count_tokens()` (ฟรี) กับ brief จริง 3 กลุ่มก่อน แล้วคูณกลับ — ห้ามใช้ตัวเลขนี้ตัดงบ · **ห้ามใช้ tiktoken** (คนละ tokenizer)
* **prompt caching: ไม่คุ้ม อย่าทำ** — prefix ~2k โทเคน = ~10% ของ input, และถ้ายิง Batch 200 ตัวพร้อมกันจะไม่มีตัวไหนอ่านแคชที่ตัวอื่นกำลังเขียน → จ่าย **1.25×** แทน 0.1× = ขาดทุน · ถ้าจะทำต้องยิง 1 ตัวก่อนจนเห็น `cache_creation_input_tokens > 0` แล้วค่อยยิงที่เหลือ
* ขั้นต่ำแคช: sonnet-5 = 1,024 tok · **haiku-4-5 = 4,096 tok** (prefix 2k จะไม่แคชแบบเงียบๆ)
* **`anthropic` SDK ยังไม่ติดตั้งบนเครื่องนี้** → `pip install anthropic` เป็นขั้นตอนติดตั้ง และเช็คตอนบูตพร้อม error ชัดเจน (ห้าม fallback เงียบ)
* **ต้นทุนจริงของงานนี้คือเวลา ~167 ชม. และความเสี่ยงบัญชี ไม่ใช่ค่า API หลักร้อยบาท**

---

## 11. ตารางแมป — fatal flaw ทุกข้อ ตอบที่ไหน

| # | ข้อบกพร่องที่ผู้ตรวจเจอ | คำตอบในสเปคนี้ |
|---|---|---|
| 1 | URL รูป CDN หมดอายุก่อนถึงคิว media | §5.4 โหลดในเซสชันเดียวกับ feed · `url_exp` จาก `oe=` · `work_item.expire_at` 12h · P6 วัดอายุจริง |
| 2 | `_nearest` จับ caption/รูปข้ามโพสต์ + O(n²) ช้า | §5.1 ข้อ 3-5: story-block + json.loads · ห้ามข้าม URL โพสต์อื่น · bisect · เลิก harvest HTML ทุกรอบ · §5.3 canary caption ซ้ำ >5% |
| 3 | ฟีดเรียงตามกิจกรรม ไม่ใช่เวลา · feed_rank โกหก | §5.2 `?sorting_setting=CHRONOLOGICAL` + ตรวจหลัง redirect + Spearman · `collect_run.feed_sort` · gate `unverified` |
| 4 | engagement ไม่ normalize อายุ → วัดว่าโพสต์เก่าแค่ไหน | §6.1 ตัดโพสต์ <72 ชม. · `age_bucket` + PERCENT_RANK ในหน้าต่างอายุ · `eng_per_day` · `age_at_observe` |
| 5 | เลขเวลาขัดกับโควตาตัวเอง / 5 คืนเป็นไปไม่ได้ | §10 คำนวณใหม่ 50 นาที/กลุ่ม → 20-24 คืน · โควตา 500 permalink/วัน มี headroom 60% |
| 6 | heartbeat อยู่เธรดเดียวกับ Playwright → deadlock | §2 watchdog แยกเธรด อ่าน `progress_ts` · kill chrome ตาม pid · `os._exit(1)` |
| 7 | Chrome กำพร้ายึด user_data_dir | §2 กติกา 6: preflight ตาม `--user-data-dir` + ลบ Singleton* + `run_event` |
| 8 | `_busy` non-blocking ทิ้งคำสั่งผู้ใช้ / เดมอน keyword อดคิว | §2 BrowserBroker prio 0/1/2 + slice ≤10 permalink + `coexist` default off |
| 9 | `bot_lock` nested → deadlock ตัวเอง / timeout 120 วิ | §2 กติกา 1: ห้ามครอบซ้อน เพิ่ม `lock_timeout` param แทน |
| 10 | BotBusy → `finish("failed")` เผากลุ่มถาวร | §2 กติกา 5 (แพตช์บังคับ เฟส 0.5) |
| 11 | งบดิสก์ไม่นับโปรไฟล์ Chrome / WAL / G:=C: | §3.1 ทั้งหมด + §10 ตารางพื้นที่ |
| 12 | median eng = 0 → top/bottom ไร้ความหมาย | §6.1 gate `too_quiet` (p50=0 / tie>40% / p90<10) → ไม่ยิง LLM |
| 13 | tie-break percentile ไม่ระบุ | §6.1 บังคับ `PERCENT_RANK` · `eng_tie_size/n>0.2` → NULL |
| 14 | โพสต์ไม่มี metric ถูก `continue` ทิ้งเงียบ | §5.1 ข้อ 8 + `url_seen/post_kept/post_dropped_no_metric` + trip ที่ 15% + แถบ "เก็บได้ 947 จาก 1,083" |
| 15 | `or 0` + COALESCE ยุบ NULL กับ 0 | §5.1 ข้อ 7 · §4 `engagement` NULL-aware + `metric_complete` |
| 16 | `max()` merge → error ขึ้นทางเดียว | §4.1 upsert เลือก `pair_dist` ต่ำสุด + `story_json` ชนะเสมอ · `seen_count` |
| 17 | เวลาคอมเมนต์สัมพัทธ์ → กราฟวัดเวลาสแกน | §4 `created_at_src/raw` · §6.2 ใช้เฉพาะ `absolute` ไม่งั้นตัดกราฟ |
| 18 | `comments_state='done'` ไม่มีตัวเลขยืนยัน + FB เรียง relevance | §5.5 ครบ (`expected/captured/toplevel/sort/stop_reason` + `partial`) |
| 19 | ไม่กาง reply → ได้เสียงคนขาย | §5.5 บังคับกด "ดูการตอบกลับ" + canary parent_id |
| 20 | โพสต์ปักหมุด/แชร์/ต่างกลุ่ม ปน | §4 `is_pinned/is_shared/src_group_key` · §5.1 ข้อ 9 · §6.1 ตัด pinned |
| 21 | `post_feature` PK ไม่มี population → percentile ขยับ, จ่าย LLM ซ้ำ | §4 ตาราง `population` + PK `(post_id, population_sig)` · `input_sig` ไม่มี run_id |
| 22 | `views` จับไม่ได้เลย 0/2,143 + regex ไม่รับเลข string | §1 P3/P4 · §5.1 ข้อ 6 · `views` NULL ไม่ใช่ 0 |
| 23 | whitelist ไม่มี `band` สักใบ, 7 legacy null, members ประมาณ | §4 `band_src='derived'` คำนวณจาก members · `is_legacy` · `members_is_approx/raw` · UI แสดง "~1.1 ล้าน" |
| 24 | ตัวอย่าง "ไม่แมส" ถูก censor / โพสต์ถูกลบระหว่างรอ | §6.1 bucket ทั้งสองฝั่งเป็น decile · §5.5 `comments_state='gone'` + รายงานอัตราหายแยก bucket + จัด bucket ใหม่ ณ เวลาเปิด |
| 25 | คอมเมนต์ 92% มาจากโพสต์ไวรัล | §5.5 เพดาน 60 เท่ากันทุก bucket · §6.2 รายงานแยก bucket เสมอ |
| 26 | ไม่มี baseline ข้ามกลุ่ม → 200 บทวิเคราะห์เหมือนกัน | §4 `global_baseline` · §6.1 แสดงส่วนต่าง · §6.3 สั่งห้ามรายงานสิ่งที่ไม่ต่าง |
| 27 | UX ผิด: พิมพ์ชื่อกลุ่มตอบคำถามข้ามกลุ่มไม่ได้ | §7.1 หน้าแรก = ตารางจัดอันดับ 200 กลุ่ม |
| 28 | `v_group_stats/v_post_latest` ช้า 520-586 ms/keystroke | §4 ตาราง `group_rollup` จริง + `is_latest` partial index · เว็บห้ามแตะ post_metric |
| 29 | `mode=ro` บน WAL เปิดไม่ได้ตอนไม่มี writer | §7 ใช้ `PRAGMA query_only=1` + เปิด-ปิดต่อ request |
| 30 | n-gram lift คืนเบอร์โทร/ชื่อร้าน/ซ้ำซ้อน | §6.1 df ขั้นต่ำ + log-odds + ยุบ substring + ทิ้งเลข ≥3 ตัว |
| 31 | `analysis` ไม่บอกว่าอิงข้อมูลเท่าไร | §4 `n_posts/n_comments_used/tier_b_done` + §6.2 เกณฑ์ขั้นต่ำ + UI ข้อ 1 |
| 32 | `person_key` จาก URL รูป (signature หมุน) → คนแตก | §4 ลำดับ `fb:` → `u:` (path ตัด query) → `w:` และ **นับเฉพาะ fbid** |
| 33 | เฟส 4 ในกิ่ง `else:` ไม่มีวันถูกเรียก | §2 เป็นเธรดแยก + broker ไม่ใช่กิ่ง if/elif |
| 34 | `attempt>=3 → dead` เผาคิวเมื่อพังเชิงระบบ | §5.6 แยก `env_fails` (ไม่นับ attempt) + circuit breaker 5 ครั้งติด + `/posts retrydead` |
| 35 | resume feed: bucket ใน RAM, ตัวจบ≠ตัวนับ → livelock/จบปลอม | §5.2 `seen_this_run` + watermark + `stop_reason` แยก "ครบ" กับ "ชนเพดาน" |
| 36 | เขียนไฟล์รูปไม่ atomic, ไม่เคยทวนแฮช | §3.2 tmp+fsync+replace แล้วค่อย INSERT · `--verify` อัตโนมัติเมื่อบูตไม่สวย |
| 37 | `post_metric` INSERT ไม่มี ON CONFLICT | §4.1 upsert เต็ม |
| 38 | Stage MEDIA ใช้ `context.request` = ต้องยึด Chrome | §5.4 ใช้ httpx + Referer (P6 พิสูจน์ก่อน) |
| 39 | คำสั่ง Telegram ไปไม่ถึงโปรเซสใหม่ / getUpdates 409 | §2 + §8 รับที่ `fb_mass_bot` เจ้าเดียว เขียนธงลง `runstate`/`work_item` |
| 40 | contrast ไม่มี n ขั้นต่ำ/นัยสำคัญ → รายงาน noise | §6.1 n≥30 สองฝั่ง + count≥10 + Wilson CI ไม่ทับกัน |
| 41 | caption 2 แหล่งตัดไม่เท่ากัน → upsert ทับของดี | §4.1 UPDATE caption แบบมีเงื่อนไข + `caption_src/caption_truncated` |
| 42 | LLM คัดลอก post_id 16 หลักผิด | §6.3 เมนู P01/C001 + validate + `dropped_rules` |
| 43 | กลุ่มคนละพันธุ์ใช้พรอมป์เดียว / คอมเมนต์คือเสียงคนขาย | §4 `group_kind` · §6.2 `seller_score` ตัดออก + baseline แยกตาม group_kind |
| 44 | FTS trigram บวมแต่ไม่มีใครใช้ | §4 เลื่อนไปเฟส 4 · สร้างคืนได้ด้วย `rebuild` |
| 45 | `_wl_band()` ไม่มีอยู่จริงในโค้ด | §4 `band_src='derived'` คำนวณเอง (ห้ามอ้างฟังก์ชันที่ไม่มี) |
| 46 | ผู้ใช้ไม่เห็นผลจนวันที่ 25-50 | §9 pipeline ต่อกลุ่ม (priority media10<verify15<comments20<analyze25<feed30) + **Pilot 3 กลุ่มใน 3-4 ชม.** |
| 47 | "คอมเมนต์ทั้งหมด 1,000 โพสต์ × 200 กลุ่ม" เป็นไปไม่ได้ | §0 + §10: ลดเป็น 30 โพสต์/กลุ่ม พร้อมตัวเลขให้ผู้ใช้ตัดสิน (1,000 ใบ = 1,870 ชม. = 78 วัน + 170,000 permalink) |

---

## 12. ไฟล์ที่ต้องสร้าง/แก้

| ไฟล์ | หน้าที่ |
|---|---|
| `fb_posts_probe.py` **ใหม่** | เฟส 0 · dump GraphQL/HTML ดิบ + ตอบ P1-P8 + สร้าง golden fixtures · **ห้ามเขียน collector ก่อนไฟล์นี้ผ่าน** |
| `data/fb_posts_schema.sql` **ใหม่** | DDL §4 ทั้งหมด (idempotent) |
| `fb_posts_store.py` **ใหม่** | ชั้นฐานตัวเดียว: connect/bootstrap, upsert ทุกตัว, claim/renew/release/reap, `disk_guard()` (ทุกวอลุ่ม + ยุบวอลุ่มซ้ำ), `media_put()`, runstate, `set_progress()`, rebuild rollup, gate · **ห้าม import playwright · ห้าม import `save_kw_state`** (มี assert ตอนบูต) |
| `fb_posts_parse.py` **ใหม่** | ฟังก์ชันบริสุทธิ์: split story block, แกะฟิลด์, normalize เลขย่อ ("1.2 พัน"/string), regex fallback + pair_dist, `oe=`→unix, seller heuristic · unit-test ได้ 100% |
| `fb_posts_collect.py` **ใหม่** | stage feed/verify/media-trigger/comments · หน่วงสุ่ม · tripwire 7 ข้อ · chrome hygiene · เรียกผ่าน `mf.launch_bot_browser(..., lock_timeout=)` เท่านั้น |
| `fb_posts_media.py` **ใหม่** | httpx + Pillow + CAS atomic + `--verify` + `--archive <gid>` |
| `fb_posts_features.py` **ใหม่** | population/gate, post_feature, PERCENT_RANK ตาม age_bucket, contrast+Wilson, n-gram, person_group_activity, baseline, rollup |
| `fb_posts_analyze.py` **ใหม่** | brief + count_tokens + Batch + json_schema + validate evidence + เขียน analysis/cost |
| `fb_posts_worker.py` **ใหม่** | ลูปเธรด: reap → gate โควตา/หน้าต่างเวลา → claim → run stage → release → sleep · try/except + log + sleep 15 วนต่อ |
| `fb_mass_bot.py` **แก้** | BrowserBroker แทน `_busy` ดิบ · start posts thread + watchdog · คำสั่ง §8 · **แพตช์ BotBusy→คืนคิว** |
| `fb_mass_finder.py` **แก้** | `lock_timeout` param · `drain()` นับแทน `pass` · regex รับเลข string · chrome cache args · orphan preflight helper · `except OSError: pass` → log |
| `app.py` **แก้** | `/groups` + `/api/groups/rank|search|{gid}/report` + `/api/media/{sha}` (`query_only=1`, ต่อ request) · PUBLIC_PATHS ถ้าต้องเปิดมือถือ |
| `web/groups.html` / `web/groups.js` **ใหม่** | §7 · SVG มือ ไม่มี lib นอก · เรนเดอร์ได้แม้ข้อมูลไม่ครบ |
| `data/fb_posts_config.json` **ใหม่** | `{image_root, floor_gb:8, feed_target:1000, detail_target:30, comment_cap:60, daily_group_cap:10, daily_permalink_cap:500, quiet_hours:[1,6], work_window, coexist:false}` |
| `tests/test_fb_posts_parse.py` **ใหม่** | golden fixtures จาก probe: 6 รูปแบบตัวเลข (เปลือย/ห่อ/string × react/cmt/share), story แชร์ซ้อน, โพสต์ต่างกลุ่ม, โพสต์ไม่มี metric |
| `WORK-LOG.md` **แก้** | บันทึกตัวเลขจริงที่วัดได้ (เวลา/กลุ่ม, verify_rate, ดิสก์/กลุ่ม, cost จริง) ไม่ใช่ค่าประเมิน |

---

### กติกาที่ต้องเขียนไว้หัวทุกไฟล์
1. `sys.stdout.reconfigure(encoding='utf-8')` ตั้งแต่ import (เคยตายจริง 12 ส.ค. เพราะ cp1252 และเจอซ้ำระหว่างตรวจสเปคนี้)
2. อ่าน `fb_kw_state.json` **read-only เท่านั้น** ห้าม import `save_kw_state` (ไม่ atomic + fallback เป็น state ว่าง = ล้าง whitelist 107 กลุ่มเงียบ)
3. ห้าม `except Exception: pass` ทุกที่ — ทุก error ต้องลง `run_event` + log + traceback
4. แยกความหมาย "ไม่มีข้อมูล" ให้ขาดเสมอ: `NULL`(แกะไม่ได้) ≠ `''`/`0`(ว่างจริง) · `skipped`/`skip_disk`/`failed`/`expired`/`gone` แยกกันหมด
5. ห้ามเรียก sync API ของ Playwright ใน event handler · ห้าม headless · ห้าม minimize หน้าต่าง