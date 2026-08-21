# สเปครวม — ระบบวิเคราะห์คอนเทนต์กลุ่ม Facebook (fbx_*)

> แกน = **evidence-first** (หลักฐานฝังตั้งแต่ชั้น SQL + LLM ห้ามพิมพ์ตัวเลข + TRIGGER ระดับฐาน)
> เสริม = **stats-first** (Mann-Whitney/AUC, สถานะ blocked, แยกไฟล์ฐาน, drift เชิงสัดส่วน)
> เสริม = **usable-first** (eng_core, คู่จับคู่, ยืนยันข้ามกลุ่ม, การ์ดสูตร, บังคับ `cannot_say`)
> เนมสเปซใหม่ `fbx_` ทั้งชุด — **ไม่แตะ** `fb_analysis_*` และ `fb_stat_*` ที่ชนกันอยู่ (ให้ผู้ใช้ลบทีหลัง)

---

## 0. หลักการ 9 ข้อ (ทุกบรรทัดในสเปคนี้สืบกลับมาที่ข้อใดข้อหนึ่ง)

1. **ชั้นนับทำใน SQL/Python ให้จบ** LLM ทำเฉพาะสิ่งที่นับไม่ได้ = ตีความ *เนื้อหา*
2. **LLM ห้ามพิมพ์ตัวเลข** ชี้ `metric_key` แล้วระบบเติมจาก SQL — หาไม่เจอต้อง **error ไม่ใช่ค่าว่าง**
3. **ทุก claim ต้องมีหลักฐาน** ไม่มี = rollback ทั้งรอบ
4. **อายุโพสต์คือ confounder อันดับ 1** ทุกการเปรียบเทียบต้องคุมอายุ ไม่ใช่แค่ block ฟีเจอร์อายุ
5. **ตัวอย่างที่เก็บมาเอียง** (คอมเมนต์มาจากโพสต์ปัง 77–100%) → ประตูต้องวัด *ความเป็นตัวแทน* ไม่ใช่ *ปริมาณ*
6. **มีตัวเลขไม่พอ ต้องมีช่วงความเชื่อมั่น + ชดเชยการทดสอบซ้ำ**
7. **ความล้มเหลวต้องดัง** ทุกจุดที่เคยคืนค่าว่าง/0 เงียบ → raise
8. **ปิดจริง ไม่ใช่เตือน** หมวดที่ข้อมูลไม่พอ ต้องปฏิเสธการบันทึก ไม่ใช่พิมพ์คำเตือนแล้วปล่อยเขียน
9. **ตัวเลขทุกตัวในเอกสาร/หน้าเว็บต้อง generate สด** ฐานโตจาก 121 → 2,126 โพสต์ในวันเดียว

---

## 1. ไฟล์ที่ต้องสร้าง

| ไฟล์ (ใต้ `C:\project\2.Auto gen Video\8.pipeline studio\`) | หน้าที่ |
|---|---|
| `fbx_schema.py` | DDL ฐานผลวิเคราะห์ + TRIGGER + `ensure_schema()` + `connect()` (ATTACH src แบบ ro) |
| `fbx_sql.py` | ค่าคงที่ SQL ทั้งหมด (view, unpivot, customer, quality, pair, twin) |
| `fbx_stats.py` | Wilson CI · median แบบ interpolate · Mann-Whitney U + tie correction · bootstrap ระดับ author · BH-FDR · split-half stability · negative control |
| `fbx_label.py` | `clean_body()` · `role_of()` · dedupe ชื่อ · mask PII · ประเมินกับ golden set |
| `fbx_gates.py` | **ประตูทุกบานอยู่ไฟล์เดียว** (group gate, section gate, feature gate) |
| `fbx_brief.py` | สร้างซอง (`--gid/--group/--all/--digest/--clip/--list`) |
| `fbx_apply.py` | รับ JSON กลับ (`--stdin/--json`) → ตรวจ → บันทึก → เติมตัวเลข |
| `fbx_view.py` | เรนเดอร์ HTML + `mount(app)` เข้า FastAPI พอร์ต 8866 |
| `fbx_replicate.py` | ยืนยันข้ามกลุ่ม + BH-FDR ทั้งระบบ + author-overlap matrix |
| `data/fbx.db` | ฐานผลวิเคราะห์ (**แยกไฟล์**) |
| `data/golden_comments.jsonl` | 200 คอมเมนต์ติดป้ายมือ — เกณฑ์วัดกฎ |
| `tests/test_fbx.py` | round-trip build→hash→apply, unit test ของ `clean_body`/`role_of` |

**ห้ามเขียนลง `fb_posts.db`** — WAL บวม 7.2 MB, `collect_run` ยัง `running` 2 แถว, บอท 2 ตัวเขียนอยู่

---

## 2. สคีมาฐานผลวิเคราะห์ (`data/fbx.db`)

```sql
-- fbx_schema.py : DDL
CREATE TABLE IF NOT EXISTS fbx_brief(
  brief_hash TEXT PRIMARY KEY, gid TEXT NOT NULL, built_at INTEGER,
  body TEXT, manifest_json TEXT,      -- {"P1":"<post_id>", "C7":"<comment_uid>"}
  gates_json TEXT, metrics_json TEXT, -- metric_key -> ค่าที่คำนวณตอนสร้างซอง
  input_sig_json TEXT, n_chars INTEGER, n_tokens INTEGER, mode TEXT);

CREATE TABLE IF NOT EXISTS fbx_run(
  run_id INTEGER PRIMARY KEY, gid TEXT, rev INTEGER, brief_hash TEXT,
  created_at INTEGER, status TEXT DEFAULT 'active',   -- active/replaced
  n_eligible INTEGER, n_top INTEGER, n_comment_usable INTEGER,
  days_covered REAL, hours_covered INTEGER,
  confidence TEXT, confidence_why TEXT, input_sig_json TEXT, drift_note TEXT);

CREATE TABLE IF NOT EXISTS fbx_claim(
  claim_id INTEGER PRIMARY KEY, run_id INTEGER, seq INTEGER,
  section TEXT CHECK(section IN ('do','dont','audience','timing','warning','hypothesis')),
  headline TEXT, detail TEXT,
  metric_key TEXT,                    -- 'dim|band' หรือ 'dim|band@ขาประจำ2+'
  metric_value TEXT,                  -- ระบบเติม ห้าม LLM กรอก
  metric_value_now TEXT,              -- หน้าเว็บเติมสดทุกครั้ง
  claim_conf TEXT);                   -- ความเชื่อถือ "ต่อ claim"

CREATE TABLE IF NOT EXISTS fbx_evidence(
  claim_id INTEGER, kind TEXT CHECK(kind IN ('post','comment')), ref_id TEXT);

CREATE TABLE IF NOT EXISTS fbx_comment(         -- ชั้นล้าง แยกจาก fb_comment
  comment_uid TEXT PRIMARY KEY,                 -- sha1(post_id|author|body) กัน seq ชนกัน
  comment_id TEXT, post_id TEXT, gid TEXT,
  body_raw TEXT, body_clean TEXT, body_masked TEXT,
  tag_names TEXT, mentions_n INTEGER, is_tag_only INTEGER,
  author_norm TEXT, role TEXT, role_rule TEXT, rule_ver INTEGER,
  llm_role TEXT DEFAULT '');

CREATE TABLE IF NOT EXISTS fbx_feature(         -- ผลทดสอบต่อ (กลุ่ม,มิติ,แถบ)
  gid TEXT, dim TEXT, band TEXT, age_band TEXT, calc_at INTEGER,
  n INTEGER, n_top INTEGER, pct_top REAL, ci_lo REAL, ci_hi REAL,
  med_core REAL, lift REAL, auc REAL, auc_lo REAL, p REAL, q REAL,
  auc_author REAL, p_author REAL, flip_rate REAL, n_cohort_agree INTEGER,
  status TEXT, reason TEXT,                     -- pass/weak/no/constant/blocked/thin
  ex_post_ids TEXT, PRIMARY KEY(gid,dim,band,age_band));

CREATE TABLE IF NOT EXISTS fbx_replicate(
  dim TEXT, band TEXT, n_groups INTEGER, groups_json TEXT,
  dir_json TEXT, overlap_max REAL, verdict TEXT, calc_at INTEGER);

CREATE TABLE IF NOT EXISTS fbx_group_stat(gid TEXT PRIMARY KEY, calc_at INTEGER, json TEXT);

-- ด่านสุดท้ายระดับฐาน: หลักฐานต้องมีจริงและอยู่กลุ่มเดียวกับ run
CREATE TRIGGER IF NOT EXISTS trg_ev_post BEFORE INSERT ON fbx_evidence
WHEN NEW.kind='post' AND NOT EXISTS (
  SELECT 1 FROM src.fb_post p JOIN fbx_claim c ON c.claim_id=NEW.claim_id
  JOIN fbx_run r ON r.run_id=c.run_id WHERE p.post_id=NEW.ref_id AND p.gid=r.gid)
BEGIN SELECT RAISE(ABORT,'post_id นี้ไม่มีจริง หรืออยู่คนละกลุ่มกับรอบวิเคราะห์'); END;

CREATE TRIGGER IF NOT EXISTS trg_ev_cmt BEFORE INSERT ON fbx_evidence
WHEN NEW.kind='comment' AND NOT EXISTS (
  SELECT 1 FROM fbx_comment x JOIN fbx_claim c ON c.claim_id=NEW.claim_id
  JOIN fbx_run r ON r.run_id=c.run_id WHERE x.comment_uid=NEW.ref_id AND x.gid=r.gid)
BEGIN SELECT RAISE(ABORT,'comment_uid นี้ไม่มีจริง หรืออยู่คนละกลุ่ม'); END;
```

**การเชื่อมฐาน** (ทุกสคริปต์ใช้ตัวเดียวกัน):
```python
def connect():
    c = sqlite3.connect("data/fbx.db"); c.row_factory = sqlite3.Row
    c.execute("ATTACH DATABASE 'file:data/fb_posts.db?mode=ro&immutable=0' AS src")
    c.execute("PRAGMA busy_timeout=5000")
    return c
```

**คอลัมน์ที่ห้ามใช้ทั้งระบบ** (ประกาศไว้ใน `fbx_sql.DEAD_COLUMNS` และพิมพ์ในซองทุกใบ):
`fb_post.views` (NULL 100%) · `fb_comment.spam_score` (0 ทุกแถว) · `fb_comment.depth` (0 ทุกแถว) · `fb_comment.author_url` (เก็บ URL โพสต์ 99.8%) · `fb_comment.when_text` (ข้อความสัมพัทธ์) · `post_image.alt` (auto-gen 100%, ผิดจริง)

---

## 3. ชั้น SQL (รันได้ทันที)

### 3.1 วิวฟีเจอร์ — `fbx_sql.V_POST_FEAT`

```sql
DROP VIEW IF EXISTS v_post_feat;
CREATE VIEW v_post_feat AS
WITH af AS (
  SELECT gid, author, COUNT(*) AS n_by_author,
         (MAX(posted_at)-MIN(posted_at))/86400.0 AS author_span_d
  FROM src.fb_post GROUP BY gid, author),
xg AS (  -- บัญชีที่โพสต์ข้ามกลุ่ม = สัญญาณบัญชีกระจาย ไม่ใช่ "ขาประจำของกลุ่ม"
  SELECT author, COUNT(DISTINCT gid) AS n_gid FROM src.fb_post GROUP BY author),
ag AS (
  SELECT gid, MAX(collected_at) AS last_col,
         COUNT(*) AS n_g_all FROM src.fb_post GROUP BY gid)
SELECT
  p.post_id, p.gid, p.url, p.author, p.posted_at, p.collected_at, p.feed_rank,
  p.caption, p.caption_len, p.images_n,
  COALESCE(p.reactions,0) AS rx, COALESCE(p.comments,0) AS cm, COALESCE(p.shares,0) AS sh,
  COALESCE(p.reactions,0)+COALESCE(p.comments,0)              AS eng_core,
  p.engagement                                                AS eng_raw,
  CASE WHEN p.engagement>100 THEN 1 ELSE 0 END                AS is_mass,   -- คำนวณเอง (แหล่งความจริงเดียว)
  p.is_mass                                                   AS is_mass_stored,
  (p.collected_at - p.posted_at)/3600.0                       AS age_h,
  CASE WHEN (p.collected_at-p.posted_at)/3600.0 <  48 THEN 'A <48ชม. (ยังโตไม่จบ)'
       WHEN (p.collected_at-p.posted_at)/3600.0 < 168 THEN 'B 2-7 วัน'
       WHEN (p.collected_at-p.posted_at)/3600.0 < 720 THEN 'C 7-30 วัน'
       ELSE                                                'D เก่ากว่า 30 วัน' END AS age_band,
  CASE WHEN p.caption_len>0 OR p.images_n>0 THEN 1 ELSE 0 END  AS readable,
  -- ผู้ต้องสงสัยปักหมุด/ถูกดันกลับฟีด: rank ต้นๆ แต่แก่กว่า 30 วัน
  CASE WHEN p.feed_rank<=20 AND (p.collected_at-p.posted_at)/86400.0>30 THEN 1 ELSE 0 END AS pin_suspect,
  af.n_by_author, af.author_span_d, xg.n_gid AS author_n_groups,
  CASE WHEN p.caption_len=0   THEN 'ไม่มีข้อความ'
       WHEN p.caption_len<=40 THEN 'สั้น 1-40'
       WHEN p.caption_len<=80 THEN 'กลาง 41-80'
       WHEN p.caption_len<=160 THEN 'ยาว 81-160'
       ELSE 'ยาวมาก 161+' END                                 AS cap_band,
  CASE WHEN p.images_n=0 THEN 'ไม่มีรูป' WHEN p.images_n=1 THEN '1 รูป'
       WHEN p.images_n<=4 THEN '2-4 รูป' ELSE '5+ รูป' END     AS img_band,
  -- ความถี่ = อัตราต่อวันในหน้าต่างที่เก็บได้ ไม่ใช่จำนวนใบดิบ
  CASE WHEN xg.n_gid>=3            THEN 'บัญชีกระจายหลายกลุ่ม'
       WHEN af.n_by_author=1       THEN 'ขาจร 1 ใบ'
       WHEN af.n_by_author<=4      THEN 'ขาประจำ 2-4'
       WHEN af.n_by_author<=10     THEN 'ขาประจำ 5-10'
       ELSE 'ขาประจำ 11+' END                                  AS author_band,
  CAST(strftime('%H',p.posted_at,'unixepoch','+7 hours') AS INTEGER) AS hour_th,
  CASE WHEN CAST(strftime('%H',p.posted_at,'unixepoch','+7 hours') AS INTEGER)<9  THEN 'ดึก-เช้า 00-08'
       WHEN CAST(strftime('%H',p.posted_at,'unixepoch','+7 hours') AS INTEGER)<12 THEN 'สาย 09-11'
       WHEN CAST(strftime('%H',p.posted_at,'unixepoch','+7 hours') AS INTEGER)<15 THEN 'เที่ยง 12-14'
       WHEN CAST(strftime('%H',p.posted_at,'unixepoch','+7 hours') AS INTEGER)<18 THEN 'บ่าย 15-17'
       ELSE 'เย็น 18-23' END                                   AS hour_band,
  CASE WHEN instr(p.caption,'#')>0 THEN 'มี #' ELSE 'ไม่มี #' END AS tag_band,
  -- ฟีเจอร์เนื้อหาที่วัดได้จริงและทำตามได้ (แทน f_sell เดิมที่ AUC 0.515)
  CASE WHEN p.caption GLOB '*[0-9]*บาท*' OR p.caption GLOB '*[0-9]*฿*' THEN 'มีราคาเป็นตัวเลข' ELSE 'ไม่มีราคา' END AS price_band,
  CASE WHEN p.caption LIKE '%เหลือ%' OR p.caption LIKE '%ลดเหลือ%' OR p.caption LIKE '%จาก%เหลือ%' THEN 'มีราคาก่อน-หลัง' ELSE 'ไม่มี' END AS discount_band,
  (CAST(substr(p.post_id,-1) AS INTEGER)%2)                    AS negctl_band, -- negative control
  (SELECT COUNT(*) FROM src.fb_comment c WHERE c.post_id=p.post_id) AS cmt_stored
FROM src.fb_post p
JOIN af ON af.gid=p.gid AND af.author=p.author
JOIN xg ON xg.author=p.author
JOIN ag ON ag.gid=p.gid;
```

### 3.2 ชุดตัวอย่างที่ "ใช้ได้" — `ELIGIBLE_SQL`

```sql
-- ทุกสถิติคำนวณจากชุดนี้เท่านั้น จำนวนที่ตัดออกต้องพิมพ์ในซอง
SELECT * FROM v_post_feat
WHERE gid = :gid
  AND readable = 1          -- ตัดโพสต์ที่ parser อ่านเนื้อหาไม่ได้ (เซียนหรั่ง 66/121)
  AND pin_suspect = 0       -- ตัดโพสต์ค้างฟีด/ปักหมุด
  AND age_h >= 48           -- maturity floor: ยังโตไม่จบ = censored ไม่ใช่ negative
  AND posted_at BETWEEN :p05 AND :p95;  -- ตัดหางเวลานอกหน้าต่างจริง
```

### 3.3 ตารางยาว (unpivot) — Python เป็นคนคำนวณสถิติ

```sql
-- LONG_SQL : 1 แถว = (โพสต์ × มิติ) → Python aggregate เอง
-- แก้ปัญหา integer-division ของ median/percentile ใน SQL ทั้งชุด
WITH e AS ( <ELIGIBLE_SQL> )
SELECT 'ความยาว caption' dim, cap_band      band, age_band, author_band, post_id, eng_core, is_mass, author FROM e
UNION ALL SELECT 'จำนวนรูป',        img_band,      age_band, author_band, post_id, eng_core, is_mass, author FROM e
UNION ALL SELECT 'ความถี่ผู้โพสต์',  author_band,   age_band, author_band, post_id, eng_core, is_mass, author FROM e
UNION ALL SELECT 'ช่วงเวลาโพสต์',    hour_band,     age_band, author_band, post_id, eng_core, is_mass, author FROM e
UNION ALL SELECT 'แฮชแท็ก',          tag_band,      age_band, author_band, post_id, eng_core, is_mass, author FROM e
UNION ALL SELECT 'ราคาใน caption',   price_band,    age_band, author_band, post_id, eng_core, is_mass, author FROM e
UNION ALL SELECT 'ราคาก่อน-หลัง',    discount_band, age_band, author_band, post_id, eng_core, is_mass, author FROM e
UNION ALL SELECT 'อายุตอนเก็บ',      age_band,      age_band, author_band, post_id, eng_core, is_mass, author FROM e
UNION ALL SELECT '[ควบคุมลบ]',       CAST(negctl_band AS TEXT), age_band, author_band, post_id, eng_core, is_mass, author FROM e;
```

### 3.4 คู่จับคู่ (หัวใจของซอง) — `PAIR_SQL`

```sql
-- จับคู่ ปัง/ไม่ปัง ที่ age_band + img_band + cap_band + author_band เหมือนกันเป๊ะ
-- เหลือให้ LLM วิเคราะห์แค่ "เนื้อหา" อย่างเดียว
WITH e AS ( <ELIGIBLE_SQL> ),
q AS (SELECT age_band, img_band, cap_band, author_band,
        NTILE(10) OVER (PARTITION BY age_band ORDER BY eng_core) AS dec_,
        post_id, author, caption, images_n, caption_len, eng_core, rx, cm, sh, posted_at
      FROM e),
hi AS (SELECT *, ROW_NUMBER() OVER (PARTITION BY age_band,img_band,cap_band,author_band
                                    ORDER BY eng_core DESC) rk FROM q WHERE dec_=10),
lo AS (SELECT *, ROW_NUMBER() OVER (PARTITION BY age_band,img_band,cap_band,author_band
                                    ORDER BY substr(post_id,-3)) rk       -- สุ่มคงที่
       FROM q WHERE dec_ BETWEEN 3 AND 7)                                 -- ไม่ใช่ล่างสุด (ค่าเสมอ)
SELECT hi.age_band, hi.img_band, hi.cap_band, hi.author_band,
       hi.post_id hi_id, hi.eng_core hi_eng, hi.caption hi_cap, hi.author hi_au,
       lo.post_id lo_id, lo.eng_core lo_eng, lo.caption lo_cap, lo.author lo_au
FROM hi JOIN lo USING (age_band,img_band,cap_band,author_band,rk)
WHERE hi.rk <= :n_pair AND hi.author <> lo.author
ORDER BY hi.eng_core DESC;
```

### 3.5 คู่แฝด (natural experiment) — `TWIN_SQL`

```sql
-- caption เหมือน + คนเดียวกัน + ห่าง <10 นาที แต่ผลต่างกัน >20 เท่า
-- ใช้ตอบว่า "เนื้อหาอธิบายได้แค่ไหน" และจับ parser หยิบยอดผิดใบ
WITH e AS ( <ELIGIBLE_SQL> )
SELECT a.post_id a_id, b.post_id b_id, a.author, a.caption,
       a.eng_core a_eng, b.eng_core b_eng,
       ROUND((a.eng_core+1.0)/(b.eng_core+1.0),1) ratio,
       ABS(a.posted_at-b.posted_at) gap_s
FROM e a JOIN e b
  ON a.author=b.author AND a.caption=b.caption AND a.post_id<b.post_id
 AND ABS(a.posted_at-b.posted_at)<600
WHERE (a.eng_core+1.0)/(b.eng_core+1.0) > 20 OR (b.eng_core+1.0)/(a.eng_core+1.0) > 20;
```

> โพสต์ที่ติดคู่แฝดอัตราส่วน >50 เท่า → ตั้งธง `boost_suspect` และ **กันออกจาก [P1..Pn]**

### 3.6 คุณภาพข้อมูล — `QUALITY_SQL`

```sql
WITH a AS (SELECT * FROM v_post_feat WHERE gid=:gid)
SELECT
 (SELECT COUNT(*) FROM a)                                            n_all,
 (SELECT COUNT(*) FROM a WHERE readable=0)                           n_unreadable,
 (SELECT COUNT(*) FROM a WHERE age_h<48)                             n_immature,
 (SELECT COUNT(*) FROM a WHERE pin_suspect=1)                        n_pin,
 (SELECT COUNT(*) FROM a WHERE is_mass<>is_mass_stored)              n_mass_mismatch, -- ต้อง 0
 (SELECT ROUND(100.0*AVG(CASE WHEN sh=0 THEN 1 ELSE 0 END),1) FROM a) pct_share_zero,
 (SELECT COUNT(*) FROM a WHERE sh IS NULL)                           n_share_null,     -- 0 = กลไก unknown ไม่ทำงาน
 (SELECT COUNT(DISTINCT date(posted_at,'unixepoch','+7 hours')) FROM a) days_covered,
 (SELECT COUNT(DISTINCT hour_th) FROM a)                             hours_covered,
 (SELECT COUNT(DISTINCT strftime('%w',posted_at,'unixepoch','+7 hours')) FROM a) dow_covered,
 (SELECT COALESCE(SUM(cm),0) FROM a)                                 cmt_onfb,
 (SELECT COUNT(*) FROM src.fb_comment c JOIN a ON a.post_id=c.post_id) cmt_got,
 (SELECT COUNT(DISTINCT c.post_id) FROM src.fb_comment c JOIN a ON a.post_id=c.post_id) cmt_posts,
 (SELECT COUNT(*) FROM a WHERE cmt_stored>0 AND is_mass=1)           cmt_posts_mass,
 (SELECT MAX(k) FROM (SELECT COUNT(*) k FROM src.fb_comment c JOIN a ON a.post_id=c.post_id GROUP BY c.post_id)) cmt_max_one_post;
```

**สองตัวชี้วัดคอมเมนต์ ต้องแยกกันเสมอ** (แก้ pct_comment_cov ที่คิดผิดฐาน):
- `cov_attempted` = got / expected เฉพาะโพสต์ `comments_state IN ('done','partial')`
- `cov_group` = โพสต์ที่ลองเก็บ / โพสต์ทั้งกลุ่ม
- `bias_mass` = โพสต์ที่มีคอมเมนต์และเป็นโพสต์ปัง / โพสต์ที่มีคอมเมนต์

### 3.7 ฐานลูกค้า — `CUSTOMER_SQL`

```sql
WITH c AS (
  SELECT x.comment_uid, x.post_id, x.author_norm, x.body_masked,
         COALESCE(NULLIF(x.llm_role,''), x.role) AS role, x.role_rule,
         x.is_tag_only, cm.likes, p.eng_core, p.is_mass, p.url post_url
  FROM fbx_comment x
  JOIN src.fb_comment cm ON cm.comment_id = x.comment_id
  JOIN v_post_feat  p   ON p.post_id      = x.post_id
  WHERE x.gid = :gid)
SELECT role, COUNT(*) n,
       COUNT(DISTINCT author_norm)                       n_people,
       ROUND(100.0*COUNT(*)/(SELECT COUNT(*) FROM c),1)  pct,
       SUM(CASE WHEN is_mass=1 THEN 1 ELSE 0 END)        n_on_mass,
       COUNT(DISTINCT post_id)                           n_posts,
       group_concat(CASE WHEN rk<=3 THEN comment_uid END) ex
FROM (SELECT c.*, ROW_NUMBER() OVER (PARTITION BY role ORDER BY substr(comment_uid,1,4)) rk FROM c)
GROUP BY role ORDER BY n DESC;
```

**ตัวอย่างคอมเมนต์เข้าซอง** — **สุ่มแบบแบ่งชั้น seed คงที่** (ไม่ใช่ `ORDER BY length DESC` ที่ทำให้กองชื่อขึ้นหัว):
โควตาต่อ role · 1 คน 1 อัน · ตัดข้อความซ้ำเป๊ะ · ตัด role ∈ (tag, photo, empty, short, campaign, spam)

---

## 4. ชั้นสถิติ (`fbx_stats.py`) — ทุกฟังก์ชันมี unit test

| ฟังก์ชัน | แก้ flaw |
|---|---|
| `median(xs)` interpolate ด้วย `statistics.quantiles` | median/percentile integer-division เพี้ยน (เซียนหรั่ง p95 ได้ 19 ค่าจริง 23) |
| `wilson(k,n)` → (pct, lo, hi) | ไม่มี CI · แถบ n=6 แสดง 33.3% เท่ากับแถบ n=158 |
| `mwu(x,y)` → AUC, z, p **พร้อม tie correction** | ค่าเสมอเยอะจากฟีเจอร์ไบนารี + eng=0 |
| `mwu_by_author(rows)` 1 คน 1 แถว (median ของคนนั้น) | pseudo-replication: 56 คนผลิต 32.8% ของโพสต์ |
| `boot_auc(rows, resample='author', B=2000)` → CI ของ AUC | ด่าน AUC_MIN คงที่ 0.10 เป็นของตายในกลุ่มเล็ก |
| `bh_fdr(pvalues)` → q ทั้งระบบ (ทุกกลุ่ม × ทุกแถบ) | Bonferroni หาร 10 ทั้งที่ยิง 15×2×110 = 3,300 ครั้ง |
| `split_half(rows, B=200, by='author')` → flip_rate | claim เนื้อหาสวนทาง 40–67% เมื่อแบ่งครึ่ง |
| `cohort_agree(rows)` ทิศทางตรงกันกี่ age_band | อายุคือ confounder อันดับ 1 |

---

## 5. ประตูทั้งหมด (`fbx_gates.py`) — ที่เดียว เป็น loop ต่อ section

### 5.1 ประตูระดับกลุ่ม

| ประตู | เกณฑ์ (ทุกข้อต้องผ่าน) | ถ้าไม่ผ่าน |
|---|---|---|
| `data_ok` | `n_unreadable/n_all ≤ 20%` · `n_mass_mismatch = 0` | `confidence='none'` ทั้งกลุ่ม · **หยุดสร้างซอง** |
| `content_ok` | `n_eligible ≥ 150` · `n_top ≥ 15` · `days_covered ≥ 7` | ปิดหมวด `do`/`dont` |
| `timing_ok` | `hours_covered ≥ 18` · `dow_covered = 7` · ทุกวัน ≥5% ของกลุ่ม · `days_covered ≥ 14` | ปิดหมวด `timing` **และตัดมิติเวลาออกจากตารางซอง** (ไม่ใช่แค่เตือน) |
| `author_ok` | `days_covered ≥ 14` | มิติความถี่ผู้โพสต์ → `blocked` (ในหน้าต่าง 2 วัน "ขาจร" = artifact) |
| `audience_ok` | `n_comment_text ≥ 150` · จากโพสต์ ≥20 ใบ · **คอมเมนต์จากโพสต์ไม่ปัง ≥30%** · โพสต์ใบเดียว ≤25% ของกอง · คนไม่ซ้ำ ≥100 · คนเดียว ≤10% · `n(customer)+n(seller)+n(recommender) ≥ 20` · คอมเมนต์จากคนที่คอมเมนต์ >10 ครั้ง ≤40% · ข้อความซ้ำ ≤15% | ปิดหมวด `audience` — **เขียนมาก็ปฏิเสธทั้งรอบ** |

> เกณฑ์ audience ตัด `chat/คุยเล่น` ออกจากนิยาม usable (เดิมเป็นถังตกค้าง 97%)
> ตอนนี้: reviewlotus (คอมเมนต์จากโพสต์ปัง 77–100%) → **ปิด** · แม็คโคร (100%) → **ปิด** · เซียนหรั่ง (92.8% จาก 3 โพสต์) → **ปิด**
> ⇒ deliverable (ข) **ยังทำไม่ได้เลยแม้แต่กลุ่มเดียว** ต้องบอกผู้ใช้ตรงๆ (ดู §10)

### 5.2 ประตูระดับฟีเจอร์ (แถบใดจะขึ้น ✅)

```
pass  = n≥60 AND n_top≥8 AND q≤0.05 AND boot_auc_lo≥0.05
        AND wilson_ci ไม่คร่อม base rate ของกลุ่ม
        AND p_author≤0.05           (ทดสอบระดับผู้เขียน)
        AND cohort_agree≥2          (ทิศตรงกัน ≥2 age_band)
        AND flip_rate≤0.20          (split-half)
        AND replicate_verdict='ยืนยันแล้ว'  (≥2 กลุ่ม, author overlap<5%)
weak    = ผ่าน q แต่ตกข้ออื่น → โชว์พร้อมเหตุผล ห้ามอ้างเป็น claim
thin    = n_top<8 → แสดงเป็น "แมสจริง 2/11 ใบ — น้อยเกินสรุป" ไม่แปลงเป็น %
constant= ฝั่งน้อย <5% ของกลุ่ม → "เกือบคงที่ ทดสอบไม่ได้"
blocked = feed_rank · alt_len (Pearson กับ images_n = 0.65) · age_band (เป็นตัวคุม ไม่ใช่คำแนะนำ)
```

**Negative control** `[ควบคุมลบ]` (เลขท้าย post_id คู่/คี่) รันทุกกลุ่ม → หน้า index แสดง "ท่อนี้ปล่อยผลบวกลวง N/110 กลุ่ม"

---

## 6. ชั้นล้างคอมเมนต์ (`fbx_label.py`) — แก้บั๊กที่ทำลายข้อมูล

### 6.1 `clean_body()` — ห้ามลบประโยคไทย

```python
RULE_VER = 3
# ❌ เดิม: [^\s]*[ฯ''`ʚɞ๊๋์]+[^\s]*  → ไทยไม่เว้นวรรค = ลบทั้งประโยค (327 อัน = 5.1%)
# ✅ ใหม่: ๆ ์ ๊ ๋ ออกจาก decor class ทั้งหมด (เป็นวรรณยุกต์/ตัวซ้ำคำปกติ)
DECOR = r'[ʚɞ๑๐‘’]{2,}'
NAME_LEXICON = set()   # สร้างจาก fb_post.author + fb_comment.author ทั้งฐาน (~5,187 ชื่อ)
THAI_FUNC = ('ที่','ไม่','ได้','ครับ','ค่ะ','เลย','มาก','จัง','นะ','แล้ว','กับ','ให้')

def clean_body(body, mentions_n=None):
    """คืน (body_clean, tag_names, is_tag_only)
    กติกา: ตัด token ได้ก็ต่อเมื่อ
      (ก) มี mentions_n จากตัวเก็บ (ทางที่ถูก) หรือ
      (ข) token อยู่ใน NAME_LEXICON หรือ
      (ค) เป็น CamelCase ละตินติดกัน ≥2 ชื่อ
    ห้ามตัด token ไทยด้วยเหตุผล 'มีเครื่องหมาย' หรือ 'ยาว ≥8'
    """
```
**assert บังคับ:** `body` ไม่ว่างแต่ `body_clean` ว่าง → บันทึกลง `fbx_clean_drop` และพิมพ์ยอดขึ้นหัวซอง ("ล้างแล้วเหลือว่าง N อัน") — ห้ามหายเงียบ

### 6.2 `role_of()` — ลำดับใหม่

```
1. campaign  : ขอ/แลก/บริจาค แสตมป์-สิทธิ์-ดวง        (ขยะแคมเปญ ไม่ใช่ลูกค้า)
2. spam      : เงินกู้ · พนัน(wy88/ufa/สล็อต) · ใบขับขี่ · ลิงก์นอก
3. customer  : ตรวจ "คำถาม" ก่อน "ขาย"  ← สลับลำดับ
               ต้องมีคำลงท้ายคำถาม (ไหม/มั้ย/เหรอ/หรอ/ป่าว/คะ?/ครับ?/'?')
               + negation window ±6 ตัวอักษร ('ไม่...เท่าไหร่' = ไม่ค่อย ไม่ใช่ถามราคา)
               ตัด 'ราคา$' เดี่ยว และ 'จอง' เดี่ยวออกจาก pattern (FP > TP)
4. seller    : ชั้นแรงเท่านั้น = ราคา+ตัวเลข | รวมส่ง | รับออเดอร์ | เบอร์/ไลน์ไอดี
               ❌ ห้ามใช้ real_img เป็นสัญญาณ (88.5% ของ seller เดิมคือลูกค้า)
5. recommender: แนะนำยี่ห้อ/รายงานสาขา/รายงานราคา   ← บทบาทใหม่ ตอบโจทย์ (ข) ตรงที่สุด
6. intent    : อยากกิน/ต้องไปสอย/คุ้ม/น่าซื้อ
7. tag       : ต้องมี tag_names จริง (mentions_n>0 หรือ ชื่อใน lexicon)  ← ไม่ใช่ "สั้น<4"
8. short     : สั้น <4 ตัวอักษรและไม่มีชื่อถูกตัด           ← แยกออกจาก tag (เดิมผิด 99.7%)
9. photo     : body ว่าง + รูปจริง (t39.30808)             ← ไม่ใช่ seller
10. sticker  : body ว่าง + t39.1997 / external
11. chat / unsure
```

### 6.3 บังคับวัดคุณภาพกฎ
```
python fbx_label.py --eval          # เทียบ data/golden_comments.jsonl (200 อัน ติดป้ายมือ)
→ พิมพ์ precision/recall ต่อ role · ถ้า customer recall < 0.60 หรือ tag precision < 0.80
  → exit 1 ไม่เขียนลงฐาน  (เดิม recall ลูกค้า ≈ 8%, tag precision ≈ 0.3%)
```
ตัวเลข precision/recall ล่าสุดต้องพิมพ์ **ข้างตารางบทบาทในซองและหน้าเว็บทุกครั้ง**

### 6.4 อื่นๆ
- `comment_uid = sha1(post_id|author|body)[:16]` — ปลด time bomb `{post_id}_{seq}`
- `mask_pii()` : เบอร์โทร/ไลน์ไอดี/อีเมล → `[เบอร์โทร]` **ก่อนเขียนซอง** (พบ 22 อันหลุด)
- `author_norm()` : ตัดอักขระประดับ + similarity ≥0.85 ยุบเป็นคนเดียว (พบ 18 คู่ในโลตัสกลุ่มเดียว)
- ธง `bot_account` : ชื่อมี แลก/ปั่น/ผู้ติดตาม/followers → กันออกจากมิติความถี่ผู้โพสต์

---

## 7. ซองข้อมูล (brief)

### 7.1 คำสั่ง
```powershell
python fbx_brief.py --group "รีวิวโลตัส" --clip        # เต็ม + คัดลอกลงคลิปบอร์ด
python fbx_brief.py --all --digest --outdir briefs\     # โหมดคัดกรอง 110 กลุ่ม
python fbx_brief.py --list --ready                      # เรียงกลุ่มตามความพร้อม
```

### 7.2 โครงสร้าง 8 ส่วน (งบสมมาตร)

| ส่วน | เนื้อหา | %ตัวอักษร |
|---|---|---|
| **0. ด่านตรวจ** | บรรทัดแรก = **การกระจายอายุโพสต์** (p25/p50/p75 + ตัดออกกี่ใบเพราะ <48ชม.) · ตัดเพราะอ่านไม่ได้/ปักหมุดกี่ใบ · หน้าต่างวัน/ชั่วโมง · ตาราง 6 ประตูพร้อมสถานะ เปิด/ปิด + ตัวเลขที่ทำให้ตัดสิน · `cov_attempted` และ `cov_group` แยกบรรทัด · **คอมเมนต์มาจากโพสต์ปัง X%** · แชร์เป็น 0 X% และ NULL 0 แถว · รายชื่อคอลัมน์ตายห้ามอ้าง · precision/recall ของกฎบทบาท | 10% |
| **1. ตารางฟีเจอร์** | ทุกแถบ พร้อม `n · n_top · %top (CI 95%) · median · lift · AUC · q · สถานะ ✅🟡❌⬜⛔ · **เหตุผลของทุกตัวที่ไม่ผ่าน**` · **เรียงด้วย %top ไม่ใช่ median** · มีคอลัมน์คู่ `%top รวม` / `%top เฉพาะขาประจำ 2+` (cross-tab) — ถ้าทิศกลับด้าน ยิงคำเตือนอัตโนมัติ | 15% |
| **2. คู่จับคู่ 15 คู่** ⭐ | ซ้าย-ขวา ฟอร์แมตเดียวกันเป๊ะทั้งสองฝั่ง (caption 220 · แยกไลก์/คอม/แชร์ · เวลา · รูป · จำนวนโพสต์ของคนนั้น) คุม age/img/cap/author band เท่ากัน | 35% |
| **3. คู่แฝด** | caption เดียวกัน คนเดียวกัน ห่าง <10 นาที ผลต่าง >20 เท่า — บอกเพดานว่าเนื้อหาอธิบายได้แค่ไหน | 5% |
| **4. เข้าสูตรแต่ไม่ปัง** | เงื่อนไข**ไดนามิกจากแถบที่ชนะจริงของกลุ่มนั้น** (ไม่ hardcode `cap>80 AND img>=5`) · ได้ <5 ใบ ต้องเขียน "ไม่มีตัวถ่วง" ไม่ใช่ข้ามเงียบ | 8% |
| **5. คอมเมนต์** | ตารางบทบาท (n / **n_people** / %) + precision/recall กำกับ + ตัวอย่างสุ่มแบ่งชั้น 25 อัน mask PII แล้ว · ถ้าประตูปิด → พิมพ์ "หมวดนี้ปิด เขียนมาก็ไม่รับ" แทนตัวอย่าง | 15% |
| **6. กติกาตอบ** | JSON template + **รายชื่อ `metric_key` ที่ใช้ได้ทั้งหมด (คัดลอกไปวาง)** + กฎ 6 ข้อ | 10% |
| **7. ท้ายซอง** | `brief_hash` 12 ตัว + จำนวนตัวอักษร/โทเคนจริง | 2% |

### 7.3 ตัวอย่างจริงที่ซองต้องผลิตออกมา

```markdown
## 0. ข้อมูลชุดนี้เชื่อได้แค่ไหน — อ่านก่อนทุกครั้ง

อายุโพสต์ตอนเก็บ: p25=0.6 ชม. · p50=1.1 วัน · p75=1.9 วัน
  ⛔ ตัดออก 469 ใบ (46.7%) เพราะอายุ <48 ชม. — ยังนับ engagement ไม่จบ
  ⛔ ตัดออก 2 ใบ เพราะอ่านเนื้อหาไม่ได้ (ไม่มีทั้ง caption และรูป)
  ⛔ ตัดออก 0 ใบ เพราะสงสัยปักหมุด/ค้างฟีด
  → เหลือใช้จริง 534 ใบ จาก 1,005 ใบ

| ประตู | สถานะ | ตัวเลขที่ทำให้ตัดสิน |
|---|---|---|
| ข้อมูลดิบ | ✅ ผ่าน | อ่านไม่ได้ 0.2% · is_mass ตรงกับ engagement 100% |
| สรุปคอนเทนต์ | ✅ เปิด | ใช้ได้ 534 ใบ · top-decile 53 ใบ · 7 วัน |
| เวลาโพสต์ | ⛔ **ปิด** | ครอบคลุม 11/24 ชม. · 3/7 วัน — มิติเวลาถูกตัดออกจากตารางข้อ 1 แล้ว |
| ความถี่ผู้โพสต์ | ⛔ **ปิด** | หน้าต่างเก็บ 3 วัน — "ขาจร" คือ artifact ไม่ใช่พฤติกรรม |
| ฐานลูกค้า | ⛔ **ปิด** | คอมเมนต์มาจากโพสต์ 57 ใบ (5.6%) และ **77% เป็นโพสต์ปัง** · ลูกค้าที่มั่นใจ 5 อัน (ต้อง ≥20) |

ยอดแชร์: เป็น 0 อยู่ 86.0% และ NULL 0 แถว → กลไก unknown ไม่เคยทำงาน
  ⇒ ระบบจัดอันดับด้วย eng_core (ไลก์+คอมเมนต์) ส่วน is_mass ตามนิยามผู้ใช้ยังแสดงไว้ครบ
คอลัมน์ห้ามอ้าง: views(NULL 100%) · spam_score(0 ทุกแถว) · depth(0 ทุกแถว) · author_url(URL โพสต์)
alt ของรูป: auto-generated 100% และพบเคสเดาผิด (caption "Redmi Watch 5" → alt "เครื่องทำน้ำอุ่น")
  ⛔ ห้ามใช้สรุปหมวดสินค้า
กฎบทบาทคอมเมนต์ (RULE_VER 3): customer P=0.81 R=0.66 · tag P=0.92 R=0.71 · จาก golden 200 อัน

## 2. คู่เทียบ — รูปแบบเหมือนกัน ผลต่างกัน (15 คู่)

### คู่ 1 · อายุ B 2-7 วัน · 1 รูป · caption กลาง 41-80 · ขาจร 1 ใบ
✅ [P1] eng_core 1376 (ไลก์ 1369 / คอม 7) · 18/08 13:20 · Nan Exrta Hyponanone
   "🧡แซลมอนแอตแลนติกนอร์เวย์สด เนื้อสีส้มสวย มาเป็นชิ้นใหญ่ ฟินสุดไปเลยค่ะ"
❌ [P31] eng_core 14 (ไลก์ 13 / คอม 1) · 18/08 11:02 · Malinee A.
   "ผ้าขนหนูลดเยอะมากเซ็ตละ 5 ชิ้น จากราคา 209 เหลือ 97฿"
   ⚠️ ทั้งคู่อยู่ percentile: P1 = 99.8 · P31 = 62.0 (ค่ากลางกลุ่ม = 9)

## 3. คู่แฝด — เนื้อหาเหมือนกันเป๊ะแต่ผลต่างกัน
⚠️ post 27477181398649605 (eng 1377) vs 27477191751981903 (eng 2) — คนเดียวกัน caption เดียวกัน
   ห่างกัน 3 วินาที ต่างกัน 688 เท่า → **ตัวแปรที่อธิบายผลอยู่นอกทุกฟีเจอร์ที่ระบบวัดได้**
   โพสต์นี้ถูกกันออกจากตัวอย่าง [P1..Pn] แล้ว (ธง boost_suspect)
```

### 7.4 กติกาตอบ (ส่วน 6)

```json
{
  "brief_hash": "1a18d2da384e",
  "claims": [
    {"section":"do","headline":"...","detail":"...",
     "metric_key":"ความยาว caption|ยาว 81-160@ขาประจำ2+","evidence":["P1","P7"]}
  ],
  "hypotheses": [                      // ← ช่องใหม่: LLM เสนอฟีเจอร์ให้ SQL ทดสอบ
    {"name":"ราคาก่อน-หลัง","regex":"จาก.{0,12}เหลือ","why":"เห็นในคู่ 1,4,9"}
  ],
  "cannot_say": ["...", "..."]         // ← บังคับ ห้ามว่าง
}
```
กฎ 6 ข้อในซอง:
1. ห้ามพิมพ์ตัวเลขเอง ให้ชี้ `metric_key` จากรายการที่ให้ไว้
2. ทุก claim ต้องมี `evidence` ≥1 (handle P1/C7 ที่มีในซองนี้เท่านั้น)
3. หมวดที่ประตูปิด เขียนมาก็ไม่รับ
4. `cannot_say` ว่าง = ปฏิเสธทั้งรอบ
5. `metric_key` ต้องระบุ `@ขาประจำ2+` เมื่อ cross-tab กลับด้าน
6. ข้อสังเกตเชิงเนื้อหาที่ยังไม่มีตัวเลขรองรับ → ใส่ `hypotheses` ไม่ใช่ `claims`

---

## 8. ทางกลับ (`fbx_apply.py`)

```powershell
Get-Clipboard | python fbx_apply.py --stdin        # ไม่ต้องเซฟไฟล์เอง
python fbx_apply.py --json ans.json
```

**ลำดับด่าน (ผิดข้อใดข้อหนึ่ง → rollback ทั้ง transaction):**

| # | ด่าน | ข้อความเมื่อปฏิเสธ |
|---|---|---|
| 1 | `brief_hash` มีในฐาน | "ไม่พบซองข้อมูล — สร้างใหม่ด้วย `fbx_brief.py --gid ...`" |
| 2 | **drift** (โพสต์ eligible +10% · n_top ±20% · ชุดฟีเจอร์ ✅ เปลี่ยน · AUC ขยับ >0.03) | "ข้อมูลเปลี่ยนจน**ข้อสรุปอาจเปลี่ยน** (top 53→71 ใบ) ต้องสร้างซองใหม่" — คอมเมนต์โตอย่างเดียว **ไม่ปฏิเสธ** แค่ติด `drift_note` |
| 3 | ทุก claim มี evidence | "claim 'xxx' ไม่มีหลักฐาน — ปฏิเสธทั้งรอบ" |
| 4 | handle อยู่ใน manifest | "อ้าง 'P999' ที่ไม่มีในซอง" |
| 5 | `section` ต้องไม่ตรงกับประตูที่ปิด (**loop ทุก section ไม่ใช่ if เดียว**) | "หมวด timing ปิด (ครอบคลุม 11/24 ชม.)" |
| 6 | ต้องมี `section='warning'` ≥1 และ `cannot_say` ไม่ว่าง | "ต้องระบุสิ่งที่ข้อมูลชุดนี้ตอบไม่ได้" |
| 7 | `metric_key` ต้องหาเจอ **ด้วยพารามิเตอร์ชุดเดียวกับซอง** | `raise` ไม่ใช่คืนค่าว่าง (เดิมเงียบ + `min_n=1` ไม่ตรงกับซอง) |
| 8 | `metric_key` ต้องชี้แถบสถานะ `pass` | "แถบนี้สถานะ weak/thin — อ้างเป็นข้อสรุปไม่ได้" |
| 9 | TRIGGER ระดับฐาน | ABORT id ปลอม / ข้ามกลุ่ม |

**หลังผ่าน:** เติม `metric_value` จาก SQL · คำนวณ **`claim_conf` ต่อ claim** (จาก n/n_top/ความกว้าง CI/section ของแถบที่ชี้) · run เก่าของกลุ่ม → `replaced` (เก็บประวัติ ไม่ทับ)

**แก้บั๊ก brief_hash** (เดิมซองพิมพ์รหัสที่ไม่มีวันตรงกับฐาน):
```python
h = brief_hash(body)                       # ← คำนวณจาก body ก่อนต่อ footer
body_out = body + footer(h)                # footer มี h อยู่ข้างใน
store(hash=h, body=body_out)               # ใช้ h ตัวเดียวทั้ง print และ save
```
`tests/test_fbx.py` ต้อง regex ดึง hash ออกจากตัวไฟล์ซองแล้ว round-trip build→apply

**confidence (ระบบคำนวณ ห้าม LLM กรอก)**
```
none  : ประตู data_ok ไม่ผ่าน หรือ n_top=0
low   : n_top 8-14  หรือ days_covered<7  หรือ pct_share_zero>70
medium: n_top 15-39 และ days_covered≥7
high  : n_top≥40 และ n_eligible≥300 และ days_covered≥14 และ hours_covered≥18
```
> ป้ายบนหัวหน้าเว็บ = **ค่าที่แย่ที่สุดในบรรดา claim** ไม่ใช่ค่ารวมของกลุ่ม

---

## 9. หน้าเว็บ (`fbx_view.py` → mount ที่ 8866)

```python
# app.py เพิ่ม 2 บรรทัด
import fbx_view; fbx_view.mount(app)
```
| Route | หน้าที่ |
|---|---|
| `GET /fbx` | ช่องพิมพ์ชื่อกลุ่ม (กรองสดฝั่งเบราว์เซอร์) · เรียงตามความพร้อม · หัวหน้าบอก "เก็บข้อมูลแล้ว 3/110 กลุ่ม · 107 กลุ่มยังไม่มีโพสต์ · คาดว่าครบใน ~2.9 วัน" · แสดงอัตราผลบวกลวงจาก negative control |
| `GET /fbx/{gid}` | หน้าเดียวจบ (โจทย์ข้อ ค) |
| `POST /fbx/api/save` | รับ JSON จาก textarea ในหน้า (ไม่ต้องแตะไฟล์) |

**ลำดับบล็อกในหน้ากลุ่ม**
1. แถบสถานะข้อมูล (ปิดไม่ได้) — ป้ายความเชื่อถือ = ค่าแย่สุดของ claim + รายการหมวดที่ปิด
2. **การ์ดสูตรโพสต์** ตัวใหญ่สุด: มุมเนื้อหา · ประโยคเปิด · ต้องมี · ห้ามทำ · ตัวอย่าง caption + ปุ่มคัดลอก
3. claim แยกหมวด ✅⛔👥⏰⚠️ — ทุกบรรทัดมี **ป้าย "จาก N ใบ · ระดับ X"** + ชิปหลักฐาน + **ตัวเลขคู่ "ตอนวิเคราะห์ 20.2% → ตอนนี้ 17.1%"** (ยิง `metric_lookup` สดทุกครั้งที่เรนเดอร์) · claim ที่ตัวเลขขยับเกิน threshold ติดแดง **เฉพาะ claim นั้น** ไม่ใช่ทั้งหน้า
4. **Drawer หลักฐาน: แสดง `body_raw` เป็นข้อความหลัก** แล้ว `body_clean` เป็นบรรทัดรอง + badge "ตัดออก: `<tag_names>`" — ให้ความผิดพลาดของตัวล้างมองเห็นด้วยตา
5. คู่เทียบ ✅/❌ วางซ้าย-ขวา พร้อมรูปจริง
6. ตารางฟีเจอร์ทั้งหมดพร้อม CI · เรียงตาม %top · ตัวที่ไม่ผ่านโชว์พร้อมเหตุผล ไม่ซ่อน
7. กราฟรายชั่วโมง — **แสดงก็ต่อเมื่อ `timing_ok` ผ่าน** ไม่งั้นขึ้นกล่อง "ครอบคลุม 11/24 ชม. ยังสรุปไม่ได้"
8. ท้ายหน้า: ปุ่มคัดลอกซอง · textarea วาง JSON · ประวัติ rev

---

## 10. กลุ่มข้อมูลไม่พอ — บอกยังไง

| สถานการณ์ | ข้อความที่แสดง (ตรงๆ ไม่อ้อม) |
|---|---|
| ยังไม่มีโพสต์ (107/110 กลุ่ม) | "กลุ่มนี้ยังไม่มีโพสต์ในฐาน — `fbx_brief.py` ปฏิเสธการสร้างซอง" |
| n_top < 8 | "โพสต์ที่ติด top-decile มี 2 ใบ — **สรุปสูตรจากตัวอย่าง 2 ใบไม่ได้** ต้องเก็บเพิ่มอีกประมาณ N ใบ" |
| อ่านเนื้อหาไม่ได้ >20% | "ตัวเก็บอ่านโพสต์ 66/121 ใบไม่ออก (54.5%) — **ตัวเลขทั้งกลุ่มเชื่อไม่ได้** ต้องเก็บซ้ำก่อน" (เซียนหรั่ง) |
| timing ปิด | "ครอบคลุม 11/24 ชม., 3/7 วัน — มิติเวลาถูกตัดออกจากซองแล้ว ไม่ใช่แค่เตือน" |
| audience ปิด | "คอมเมนต์ 3,883 อัน แต่มาจากโพสต์ 57 ใบ (5.6%) และ **77% เป็นโพสต์ปัง** · ลูกค้าที่มั่นใจ 5 อัน<br>⇒ วิเคราะห์ได้แค่ 'คนที่มาคุยใต้โพสต์ดัง' ไม่ใช่ 'ฐานลูกค้าของกลุ่ม' — **หมวดนี้ปิด**" |
| ฟีเจอร์ยืนยันข้ามกลุ่มไม่ผ่าน | "สัญญาณนี้พบใน 1 กลุ่ม และกลับด้านในอีกกลุ่ม — อยู่ใต้ปุ่ม 'ตัวที่ยังเชื่อไม่ได้'" |
| cross-tab กลับด้าน | "⚠️ '5+ รูป' ดีในภาพรวม แต่**แย่กว่าครึ่งหนึ่ง**เมื่อดูเฉพาะขาจร (9.4% vs 18.7%) — ห้ามสรุปเป็นสูตร" |

---

## 11. ขั้นตอนผู้ใช้ทีละขั้น

### รอบแรก (ครั้งเดียว)
```powershell
python fbx_schema.py --init            # สร้าง data/fbx.db + วิว (ไม่แตะ fb_posts.db)
python fbx_label.py --build-lexicon    # ดึงชื่อคนทั้งฐานทำ lexicon
python fbx_label.py --enrich --all     # ล้างคอมเมนต์ทุกกลุ่ม (RULE_VER 3)
python fbx_label.py --eval             # ต้องผ่านเกณฑ์ ไม่งั้น exit 1
python fbx_replicate.py --all          # คำนวณ feature + BH-FDR + ยืนยันข้ามกลุ่ม
# แก้ app.py: import fbx_view ; fbx_view.mount(app)  แล้วรีสตาร์ต 8866
```

### รอบคัดกรอง 110 กลุ่ม (ชั้นที่ 1)
```powershell
python fbx_brief.py --all --digest --outdir briefs\
# ได้ briefs\_queue.md บอกว่ากลุ่มไหนพร้อม กลุ่มไหนข้ามเพราะอะไร
# ซอง digest ~5-6K ตัวอักษร/กลุ่ม → แปะได้ 10-12 กลุ่มต่อแชท
```
วางในแชท → Claude ตอบว่ากลุ่มไหน "น่าลงลึก"

### รอบเจาะลึกต่อกลุ่ม (ชั้นที่ 2) — **4 ขั้น**
```
1) python fbx_brief.py --group "รีวิวโลตัส" --clip      (ซองอยู่ในคลิปบอร์ดแล้ว)
2) Ctrl+V ในแชท → Claude เขียน JSON กลับ
3) Get-Clipboard | python fbx_apply.py --stdin           (ก๊อป JSON จากแชทแล้วรัน)
4) เปิด http://localhost:8866/fbx  พิมพ์ชื่อกลุ่ม
```
> ลดจาก 6–7 ขั้น/660 ท่า เหลือ 4 ขั้น และไม่ต้องเซฟไฟล์เอง

---

## 12. ขนาดซอง + เวลา (ตัวเลขต้องวัดสด ห้ามพิมพ์มือ)

`fbx_brief.py` พิมพ์ตัวเลขจริงหัวซองทุกใบ ด้วยสูตรผสมที่ปรับตามสัดส่วนไทย
(อังกฤษ ~0.28 โทเคน/ตัวอักษร · ไทย ~0.90 โทเคน/ตัวอักษร — hardcode หลัง calibrate ด้วย `count_tokens` 3 ใบ)

| โหมด | ตัวอักษร | โทเคนประมาณ | ใช้ตอน |
|---|---|---|---|
| `--digest` | 5,000–6,500 | **4,500–6,000** | คัดกรอง 110 กลุ่ม (10–12 กลุ่ม/แชท) |
| เต็ม | 18,000–22,000 | **14,000–18,000** | เจาะลึกกลุ่มที่ผ่านประตู (~8 กลุ่ม/แชท) |

> ⚠️ ตัวเลขเดิม "10,600 โทเคน จาก 21,208 ตัวอักษร" มาจากสูตร chars/2 ของภาษาอังกฤษ — ต่ำไป ~1.6 เท่า

**เวลาต่อกลุ่ม (โหมดเต็ม)**: สร้างซอง ~2 วิ · แปะ+รอ Claude 1.5–3 นาที · apply ~1 วิ · เปิดหน้า 5 ms
⇒ **~3–5 นาที/กลุ่ม active**
ตอนนี้กลุ่มที่ผ่านประตู content = 2 กลุ่ม ⇒ งานจริงวันนี้ ~10 นาที ที่เหลือคือรอบอทเก็บ (~4.5 วิ/โพสต์ × 110 กลุ่ม ≈ 2.9 วันด้วย 2 บอท)

---

## 13. ตารางตอบทุก fatal flaw

| # | Flaw | คำตอบในสเปคนี้ |
|---|---|---|
| 1 | อายุโพสต์เป็น confounder แรงสุด (%แมส 4.5→29.0) | maturity floor 48 ชม. · `age_band` เป็นชั้นควบคุมในทุกมิติ · `cohort_agree≥2` · คู่จับคู่คุมอายุ · §3.1/§5.2 |
| 2 | timing ไม่มีประตู | `timing_ok` ปิดจริง + **ตัดมิติเวลาออกจากตารางซอง** §5.1 |
| 3 | ไม่มี CI / ไม่ชดเชยการทดสอบซ้ำ | Wilson CI ทุกแถบ · BH-FDR ทั้งระบบ · negative control · §4 §5.2 |
| 4 | `HAVING n>=5` ไม่กัน n_mass · `metric_lookup min_n=1` | `n≥60 AND n_top≥8` · แถบ thin แสดงเป็น "2/11 ใบ" · metric_lookup ใช้พารามิเตอร์ชุดเดียวกับซองและ **raise เมื่อไม่เจอ** §8 ด่าน 7-8 |
| 5 | คอมเมนต์เก็บเฉพาะโพสต์ปัง | `audience_ok` บังคับ ≥30% จากโพสต์ไม่ปัง + ใบเดียว ≤25% ⇒ **ทั้ง 3 กลุ่มปิด** §5.1 §10 |
| 6 | audience gate กลับด้าน · "คุยเล่น" นับเป็น usable | ตัด chat ออกจาก usable · บังคับ customer+seller+recommender ≥20 · confidence=low ห้าม open |
| 7 | confidence ระดับรอบ + dead param | `claim_conf` ต่อ claim · ป้ายหัวหน้า = ค่าแย่สุด §8 |
| 8 | `pct_comment_cov` ฐานผิด | แยก `cov_attempted` / `cov_group` / `bias_mass` §3.6 |
| 9 | author_band เป็น artifact ของหน้าต่างเก็บ | `author_ok` ปิดเมื่อ <14 วัน · เพิ่มแถบ "บัญชีกระจายหลายกลุ่ม" (32.8% ของโพสต์) · ธง bot_account §3.1 §6.4 |
| 10 | `ORDER BY med_eng` ขัดกับ %แมส · SAMPLE_COUNTER hardcode | เรียงด้วย %top · เงื่อนไขตัวถ่วงไดนามิกจากแถบที่ชนะจริง §7.2 |
| 11 | เกณฑ์ 100 คงที่ข้ามกลุ่ม · องค์ประกอบ eng ต่างกัน | `is_mass` เก็บตามนิยามผู้ใช้ไม่แตะ + สถิติใช้ top-decile ภายใน age_band · ซองพิมพ์องค์ประกอบ ไลก์/คอม/แชร์ ของกอง top เสมอ |
| 12 | โพสต์ปักหมุด/ถูกดันกลับฟีด | `pin_suspect` (feed_rank≤20 + อายุ>30 วัน) ตัดออก + โชว์แยก §3.1 |
| 13 | percentile/median integer division | ย้ายมาคำนวณใน Python ด้วย `statistics.quantiles` §3.3 §4 |
| 14 | `brief_hash` ไม่มีวันตรงกัน | คำนวณก่อนต่อ footer + round-trip test §8 |
| 15 | honesty อ้างว่าไม่แตะฐานจริง (แต่แตะแล้ว) | ฐานแยก `data/fbx.db` · `--init` ประกาศชัด · ทุกตัวเลขในเอกสาร generate สด |
| 16 | `clean_body` ลบประโยคไทยทั้งประโยค (5.1%) | ตัด ๆ ์ ๊ ๋ ออกจาก decor · ตัดได้เฉพาะ token ใน lexicon/mentions · assert + `fbx_clean_drop` §6.1 |
| 17 | tagger ผิด 99.7% | `tag` ต้องมี tag_names จริง · แยก `short` ออกมา §6.2 |
| 18 | seller ก่อน customer · `real_img→seller` | สลับลำดับ + negation window + ตัด real_img ออกจาก seller (เป็น `photo`) §6.2 |
| 19 | โพสต์อ่านเนื้อหาไม่ได้ถูกนับ (54.5% ในเซียนหรั่ง) | `readable` filter + ถ้า >20% → confidence='none' §3.2 §5.1 |
| 20 | คู่แฝดต่างกัน 688 เท่า | `TWIN_SQL` เป็นส่วนบังคับในซอง + ธง boost_suspect กันออกจาก [P1..Pn] §3.5 |
| 21 | drawer แสดง body_clean | drawer แสดง **raw เป็นหลัก** + badge ตัดออก · ด่านที่ 5: claim อ้าง comment ที่ clean<50% ของ raw → เตือน §9 |
| 22 | ชื่อที่แสดง = ตัวตน | `author_norm` dedupe ≥0.85 · นับ `n_people` คู่ `n` เสมอ · ตัดเพจกลุ่ม/แอดมิน §6.4 |
| 23 | alt ใช้แทนดูรูปไม่ได้ (auto 100%, ผิดจริง) | ลบ alt ออกจากซอง · `alt_len` = blocked (Pearson กับ images_n 0.65) · OCR เข้าเฟส 3 §12 |
| 24 | ตาราง marginal ทำให้คำแนะนำกลับด้าน | คอลัมน์คู่ `%top รวม` / `เฉพาะขาประจำ 2+` + คำเตือนอัตโนมัติเมื่อกลับทิศ · `metric_key` บังคับระบุ `@ขาประจำ2+` §7.2 |
| 25 | deliverable (ข) ว่างเปล่าเชิงโครงสร้าง | ยอมรับตรงๆ: **0/3 กลุ่มผ่านประตู audience** · แก้ที่ตัวเก็บเท่านั้น §14 |
| 26 | แถบล้าสมัยไวเกิน + metric_value แช่แข็ง | drift มีโซนทน + ตัดสินจาก "ข้อสรุปเปลี่ยนไหม" · หน้าเว็บยิง metric สดโชว์คู่ §8 §9 |
| 27 | ไม่มี batch · ไม่ต่อกับ 8866 | `--all --digest` · `--stdin` · `mount(app)` · `/fbx` §9 §11 |
| 28 | งบซองเอียงฝั่งชนะ 45% | คู่จับคู่สมมาตร 35% · ฝั่งแมสลดเหลือ 15 ใบ §7.2 |
| 29 | is_mass ↔ engagement หลุดจากกัน (upsert) | v_post_feat คำนวณเอง · `n_mass_mismatch` ต้อง 0 ไม่งั้น **หยุดสร้างซอง** §3.6 §5.1 |
| 30 | PERCENT_RANK ค่าซ้ำ → top10 ได้ 0 ใบ | ใช้ `NTILE`/`ROW_NUMBER` + การันตี `MAX(10, n*0.1)` · lift แบบ smoothed `(m+1)/(M+1)` |
| 31 | ประมาณโทเคนด้วยสูตรอังกฤษ | สูตรผสมตามสัดส่วนไทย calibrate ด้วย tokenizer จริง §12 |
| 32 | pseudo-replication (56 คน = 32.8% ของโพสต์) | `mwu_by_author` · bootstrap resample ระดับ author · author-overlap <5% ในด่านยืนยัน §4 §5.2 |
| 33 | claim เนื้อหาสวนทาง 40–67% เมื่อแบ่งครึ่ง | `split_half` flip_rate ≤20% เป็นด่านบังคับ §4 §5.2 |
| 34 | `cannot_say` ไม่มีในเส้นทางจริง · metric_lookup เงียบ | ทั้งคู่เป็นด่าน 6 และ 7 ใน `fbx_apply.py` §8 |
| 35 | buyer keyword ชนคำ (`เท่าไก่`) · บัญชีปั่น · เบอร์โทรหลุด | คำเต็ม + negation window · ธง bot/campaign · `mask_pii()` §6 |
| 36 | LLM ถูกห้ามสรุปจากสิ่งที่อ่าน | ช่อง `hypotheses[]` + `fbx_replicate.py --test-feature '<regex>'` วนกลับเป็นฟีเจอร์ (พร้อมนับเข้า FDR) §7.4 |
| 37 | `comment_id={post_id}_{seq}` ระเบิดเวลา | `comment_uid = sha1(post_id|author|body)` §6.4 |
| 38 | is_spam recall 40% · spam_score ตาย | กฎใหม่วัดกับ golden set · spam_score หลุดจากทุกคิวรี §6 |

---

## 14. สิ่งที่สเปคนี้ **แก้ไม่ได้** — ต้องแก้ที่ตัวเก็บ (Preventive)

| ปัญหา | Corrective (ทำได้ตอนนี้) | Preventive (ต้องแก้ที่ `fb_posts_*`) |
|---|---|---|
| คอมเมนต์เก็บเฉพาะโพสต์ปัง 77–100% | ปิดหมวดฐานลูกค้าทุกกลุ่ม + บอกตรงๆ | **`fb_posts_comments.py` ต้องสุ่มโพสต์ไม่ปังมาเก็บด้วย (stratified)** — ถ้าไม่แก้ deliverable (ข) เกิดไม่ได้ตลอดไปไม่ว่าจะเก็บอีกกี่แสนโพสต์ |
| `shares` NULL ไม่เคยถูกใช้ (86% เป็น 0) | ใช้ `eng_core` · ประกาศในซองทุกใบ | `fb_posts_parse.py` ต้องส่ง key `unknown` จริงเมื่ออ่านยอดไม่ได้ |
| ไม่มี mentions ในคอมเมนต์ | เดาจาก lexicon (P≈0.92) | เก็บ `mentions_n` / mention span จาก DOM ตั้งแต่ต้นทาง |
| `author_url` เก็บ URL โพสต์ | ตัดฟีเจอร์ "โปรไฟล์คนซ้ำ" ทิ้ง | เก็บ actor id/โปรไฟล์จริงลงคอลัมน์ใหม่ |
| `depth=0` ทุกแถว | ไม่วิเคราะห์เธรด/คอนเวอร์ชัน | ตัวดึงคอมเมนต์ต้องกาง reply |
| ไม่มีธง `pinned` | เดาจาก feed_rank+อายุ | parser ส่ง `is_pinned` + `sort_mode` ลง `collect_run` |
| โพสต์ caption ว่าง + รูป 0 + reactions>0 | ตัดออก + ประกาศ | `fb_posts_store` ติดธง `suspect` ตอน insert ไม่ใช่บันทึกเงียบ |
| 90% ของสารอยู่ในภาพ | ห้าม claim เรื่องราคา/โปร | **OCR ไทยบนรูปแรก** เก็บลง `post_image.ocr_text` (เฟส 3) |
| `collect_run.posts_seen=0` ขณะ running | — | อัปเดต incremental ไม่งั้นตรวจย้อนหลังไม่ได้ |

---

## 15. ลำดับลงมือ

| เฟส | ทำอะไร | เสร็จแล้ววัดอะไร |
|---|---|---|
| **1** | `fbx_schema` + `fbx_sql` + `fbx_stats` + unit test สถิติ | v_post_feat รัน <0.3 วิ/กลุ่ม · `n_mass_mismatch=0` |
| **2** | `fbx_label` + golden set 200 อัน + `--eval` | customer recall ≥0.60 · tag precision ≥0.80 |
| **3** | `fbx_gates` + `fbx_replicate` (FDR + negative control) | รายงานว่าเหลือฟีเจอร์ ✅ กี่ตัวจริงหลังคุมอายุ+คลัสเตอร์ |
| **4** | `fbx_brief` (+digest/all/clip) + round-trip test | ซองสร้าง→apply ได้ด้วยรหัสที่ regex จากไฟล์เอง |
| **5** | `fbx_apply` 9 ด่าน + `fbx_view` + mount app.py | **เทสใน Chrome ตัวจริงของผู้ใช้** (`mcp__claude-in-chrome`) ไม่ใช่ Browser pane |
| **6** | เดินจริง 2 กลุ่มที่ผ่านประตู | ได้การ์ดสูตร + ชิปหลักฐาน resolve ครบ 0 missing |
| **7** (แยกงาน) | แก้ตัวเก็บตาม §14 → เก็บคอมเมนต์แบบ stratified → เปิดหมวดฐานลูกค้า | audience_ok ผ่านอย่างน้อย 1 กลุ่ม |