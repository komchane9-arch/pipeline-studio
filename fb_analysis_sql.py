"""ชั้น SQL ของระบบวิเคราะห์กลุ่ม — คำนวณให้หมดก่อนส่งให้คนอ่าน

หลักการที่ยึด (ผู้ใช้สั่ง 19 ส.ค. 2569):
  1) อะไรที่นับได้ด้วย SQL ต้องนับที่นี่ ห้ามโยนให้ LLM นับ
  2) ทุกแถวที่คืนออกไปต้องพก "หลักฐาน" (post_id / comment_id) ติดมาด้วยเสมอ
     เพื่อให้หน้าเว็บกดดูของจริงได้ และกัน LLM แต่งเรื่อง
  3) ห้ามยุบ NULL กับ 0 — คอลัมน์ reactions/comments/shares ออกแบบไว้ว่า
     NULL = อ่านไม่ได้ แต่ตัวเก็บปัจจุบันไม่เคยเขียน NULL เลย จึงต้องมีธง
     เตือนความน่าเชื่อถือ (ดู GROUP_QUALITY_SQL) แทนการเชื่อตัวเลขดิบ

ทุกคำสั่งในไฟล์นี้ทดสอบรันจริงกับ data/fb_posts.db แล้ว (sqlite 3.39.4)
"""
from __future__ import annotations

# ------------------------------------------------------------------ 1. ฟีเจอร์รายโพสต์
# วิว: แปลงโพสต์ดิบเป็นฟีเจอร์ที่ใช้เทียบได้ — ไม่เก็บซ้ำ อ่านสดจากตารางจริง
# หมายเหตุ: เลือกเฉพาะฟีเจอร์ที่รอดการวัดจริงแล้ว (caption_len / images_n /
# ความถี่ผู้โพสต์) + ฟีเจอร์เฝ้าดู (ชั่วโมง / แฮชแท็ก) ส่วน feed_rank กับอายุโพสต์
# ตัดทิ้งเพราะวัดแล้วไม่ต่าง (rho=+0.040 p=0.21)
FEATURES_SQL = """
DROP VIEW IF EXISTS v_post_feat;
CREATE VIEW v_post_feat AS
SELECT
  p.post_id, p.gid, p.url, p.author, p.posted_at, p.collected_at,
  p.caption, p.caption_len, p.images_n,
  p.reactions, p.comments, p.shares, p.engagement, p.is_mass,
  p.comments_state, p.comments_expected, p.comments_got,
  /* แถบความยาว caption — ตัดตามจุดที่ median engagement เปลี่ยนจริง */
  CASE WHEN p.caption_len = 0   THEN 'ไม่มี caption'
       WHEN p.caption_len <= 40 THEN 'สั้น 1-40'
       WHEN p.caption_len <= 80 THEN 'กลาง 41-80'
       WHEN p.caption_len <=160 THEN 'ยาว 81-160'
       ELSE 'ยาวมาก 160+' END AS cap_band,
  /* แถบจำนวนรูป — ไม่เป็นเส้นตรง (2-4 รูปแย่กว่า 1 รูป) จึงต้องแบ่งเป็นแถบ */
  CASE WHEN p.images_n = 0 THEN 'ไม่มีรูป'
       WHEN p.images_n = 1 THEN '1 รูป'
       WHEN p.images_n <=4 THEN '2-4 รูป'
       ELSE '5+ รูป' END AS img_band,
  /* ความถี่ของผู้โพสต์ในกลุ่มนี้ — ใช้ window function ไม่ใช่ subquery ต่อแถว */
  COUNT(*) OVER (PARTITION BY p.gid, p.author) AS author_posts,
  CASE WHEN COUNT(*) OVER (PARTITION BY p.gid, p.author) = 1 THEN 'ขาจร 1 ใบ'
       WHEN COUNT(*) OVER (PARTITION BY p.gid, p.author) <=4 THEN 'ขาประจำ 2-4'
       WHEN COUNT(*) OVER (PARTITION BY p.gid, p.author) <=10 THEN 'ขาประจำ 5-10'
       ELSE 'ขาประจำ 11+' END AS author_band,
  CAST(strftime('%H', p.posted_at, 'unixepoch', 'localtime') AS INTEGER) AS hour_local,
  CASE WHEN p.posted_at IS NULL THEN 'ไม่รู้เวลา'
       WHEN CAST(strftime('%H', p.posted_at,'unixepoch','localtime') AS INTEGER) < 9  THEN 'เช้า 00-08'
       WHEN CAST(strftime('%H', p.posted_at,'unixepoch','localtime') AS INTEGER) < 12 THEN 'สาย 09-11'
       WHEN CAST(strftime('%H', p.posted_at,'unixepoch','localtime') AS INTEGER) < 15 THEN 'เที่ยง 12-14'
       WHEN CAST(strftime('%H', p.posted_at,'unixepoch','localtime') AS INTEGER) < 18 THEN 'บ่าย 15-17'
       ELSE 'เย็น 18-23' END AS hour_band,
  CASE WHEN instr(p.caption, '#') > 0 THEN 'มี #' ELSE 'ไม่มี #' END AS tag_band,
  /* alt ของรูปแรก — FB ใส่คำบรรยายภาพมาให้ 99.5% ใช้แทนการเปิดดูรูปได้ */
  (SELECT i.alt FROM post_image i
    WHERE i.post_id = p.post_id AND i.alt <> '' ORDER BY i.idx LIMIT 1) AS first_alt,
  (SELECT COUNT(*) FROM fb_comment c WHERE c.post_id = p.post_id) AS comments_stored
FROM fb_post p;
"""

# ------------------------------------------------------------------ 2. สถิติกลุ่ม
# ตัวเลขหัวกระดาษ: ใช้ทั้งในซองข้อมูลและหน้าเว็บ — คำนวณครั้งเดียว
GROUP_STAT_SQL = """
WITH f AS (SELECT * FROM v_post_feat WHERE gid = :gid),
     o AS (SELECT engagement e, ROW_NUMBER() OVER (ORDER BY engagement) rn,
                  COUNT(*) OVER () n FROM f)
SELECT
  (SELECT COUNT(*) FROM f)                                    AS n_post,
  (SELECT COUNT(*) FROM f WHERE is_mass = 1)                  AS n_mass,
  (SELECT COUNT(*) FROM f WHERE engagement = 0)               AS n_zero,
  (SELECT MAX(engagement) FROM f)                             AS eng_max,
  (SELECT MAX(CASE WHEN rn = (n+1)/2            THEN e END) FROM o) AS eng_p50,
  (SELECT MAX(CASE WHEN rn = MAX(1,(n*75)/100)  THEN e END) FROM o) AS eng_p75,
  (SELECT MAX(CASE WHEN rn = MAX(1,(n*90)/100)  THEN e END) FROM o) AS eng_p90,
  (SELECT MAX(CASE WHEN rn = MAX(1,(n*95)/100)  THEN e END) FROM o) AS eng_p95,
  (SELECT COUNT(*) FROM f WHERE caption_len > 0)              AS n_caption,
  (SELECT COUNT(*) FROM f WHERE images_n > 0)                 AS n_image,
  (SELECT COUNT(DISTINCT author) FROM f)                      AS n_author,
  (SELECT MIN(posted_at) FROM f)                              AS first_post_at,
  (SELECT MAX(posted_at) FROM f)                              AS last_post_at,
  (SELECT MAX(collected_at) FROM f)                           AS last_collect_at,
  (SELECT COALESCE(SUM(comments),0) FROM f)                   AS comments_on_fb,
  (SELECT COALESCE(SUM(comments_stored),0) FROM f)            AS comments_stored,
  (SELECT COUNT(*) FROM f WHERE comments_state = 'pending')   AS n_cm_pending,
  (SELECT COUNT(*) FROM f WHERE shares = 0)                   AS n_share_zero
"""

# ------------------------------------------------------------------ 3. คุณภาพข้อมูลนำเข้า
# ตอบคำถาม "ตัวเลขของกลุ่มนี้เชื่อได้แค่ไหน" ก่อนจะสรุปอะไรทั้งสิ้น
GROUP_QUALITY_SQL = """
WITH f AS (SELECT * FROM v_post_feat WHERE gid = :gid)
SELECT
  ROUND(100.0 * SUM(CASE WHEN shares = 0 THEN 1 ELSE 0 END) / COUNT(*), 1) AS pct_share_zero,
  SUM(CASE WHEN shares IS NULL THEN 1 ELSE 0 END)                          AS n_share_null,
  ROUND(100.0 * COALESCE(SUM(comments_stored),0)
        / NULLIF(SUM(COALESCE(comments,0)),0), 1)                          AS pct_comment_cov,
  SUM(CASE WHEN comments_state IN ('done','partial') THEN 1 ELSE 0 END)    AS n_post_with_cm,
  SUM(CASE WHEN comments_state = 'pending' THEN 1 ELSE 0 END)              AS n_post_cm_pending,
  ROUND(100.0 * SUM(CASE WHEN posted_at IS NULL THEN 1 ELSE 0 END)/COUNT(*),1) AS pct_no_time,
  MIN(hour_local) AS hour_min, MAX(hour_local) AS hour_max,
  COUNT(DISTINCT date(posted_at,'unixepoch','localtime'))                  AS n_days
FROM f
"""

# ------------------------------------------------------------------ 4. ตารางเทียบ แมส vs ไม่แมส
# หัวใจของงาน: ทุกแถวมี n / มัธยฐาน / %แมส / %ศูนย์ + post_id ตัวอย่าง 3 ใบ
# (ตัวอย่างเรียงจาก engagement สูงสุด เพื่อให้กดดูแล้วเห็น "หน้าตาของแถบนี้")
CONTRAST_SQL = """
WITH f AS (SELECT * FROM v_post_feat WHERE gid = :gid),
d AS (
  SELECT '0_ทั้งกลุ่ม' dim, 'ทุกโพสต์' band, post_id, engagement FROM f
  UNION ALL SELECT '1_ความยาว caption', cap_band,    post_id, engagement FROM f
  UNION ALL SELECT '2_จำนวนรูป',        img_band,    post_id, engagement FROM f
  UNION ALL SELECT '3_ความถี่ผู้โพสต์',  author_band, post_id, engagement FROM f
  UNION ALL SELECT '4_ช่วงเวลาโพสต์',    hour_band,   post_id, engagement FROM f
  UNION ALL SELECT '5_แฮชแท็ก',          tag_band,    post_id, engagement FROM f
),
r AS (
  SELECT dim, band, post_id, engagement,
         ROW_NUMBER() OVER (PARTITION BY dim, band ORDER BY engagement)      AS rn_asc,
         ROW_NUMBER() OVER (PARTITION BY dim, band ORDER BY engagement DESC) AS rn_desc,
         COUNT(*)     OVER (PARTITION BY dim, band)                          AS n
  FROM d
)
SELECT dim, band, n,
       MAX(CASE WHEN rn_asc = (n+1)/2 THEN engagement END)                    AS med_eng,
       ROUND(100.0*SUM(CASE WHEN engagement > 100 THEN 1 ELSE 0 END)/n, 1)    AS pct_mass,
       ROUND(100.0*SUM(CASE WHEN engagement = 0   THEN 1 ELSE 0 END)/n, 1)    AS pct_zero,
       MAX(engagement)                                                        AS max_eng,
       group_concat(CASE WHEN rn_desc <= 3 THEN post_id END)                  AS ex_post_ids
FROM r
GROUP BY dim, band
HAVING n >= :min_n
ORDER BY dim, med_eng DESC
"""

# ------------------------------------------------------------------ 5. ตัวอย่างโพสต์
# แมส: เอาทั้งหมด (เรียง engagement) — ถ้าเกินเพดานค่อยตัด
SAMPLE_MASS_SQL = """
SELECT post_id, url, author, author_posts, posted_at, hour_local,
       caption, caption_len, images_n, first_alt,
       reactions, comments, shares, engagement, comments_stored
FROM v_post_feat WHERE gid = :gid AND is_mass = 1
ORDER BY engagement DESC LIMIT :limit
"""

# ไม่แมส: สุ่มแบบคงที่ (hash ของ post_id) — ซองเดิมต้องได้ตัวอย่างชุดเดิมเสมอ
# และคัดจากช่วงกลาง (ไม่ใช่ก้นสุดที่ engagement=0 เสมอกันทั้งกอง ซึ่งเทียบไม่ได้)
SAMPLE_NORMAL_SQL = """
WITH f AS (SELECT * FROM v_post_feat WHERE gid = :gid AND is_mass = 0)
SELECT post_id, url, author, author_posts, posted_at, hour_local,
       caption, caption_len, images_n, first_alt,
       reactions, comments, shares, engagement, comments_stored
FROM f
ORDER BY substr(post_id, -3) || substr(post_id, 1, 3)
LIMIT :limit
"""

# โพสต์ที่ "ควรแมสแต่ไม่แมส" — เข้าเงื่อนไขสูตรทุกข้อแต่ผลออกมาแย่
# ใช้เป็นตัวถ่วง กัน Claude สรุปสูตรจากด้านชนะอย่างเดียว
SAMPLE_COUNTER_SQL = """
SELECT post_id, url, author, author_posts, posted_at, caption, caption_len,
       images_n, first_alt, engagement
FROM v_post_feat
WHERE gid = :gid AND is_mass = 0 AND caption_len > 80 AND images_n >= 5
ORDER BY engagement ASC LIMIT :limit
"""

# ------------------------------------------------------------------ 6. ชั้นคอมเมนต์ (ฐานลูกค้า)
# อ่านจาก fb_comment + ตารางเสริม comment_enrich (ล้างแท็ก/ตีบทบาทด้วยกฎ)
# ถ้ายังไม่ได้ enrich จะ fallback เป็น body ดิบ + role='ยังไม่จัด' อย่างซื่อสัตย์
CUSTOMER_SQL = """
WITH c AS (
  SELECT cm.comment_id, cm.post_id, cm.author, cm.body, cm.likes, cm.is_spam,
         p.is_mass, p.url AS post_url,
         COALESCE(e.body_clean, cm.body)  AS txt,
         COALESCE(e.role, 'ยังไม่จัด')     AS role,
         COALESCE(e.is_tag_only, 0)       AS tag_only
  FROM fb_comment cm
  JOIN fb_post p ON p.post_id = cm.post_id
  LEFT JOIN comment_enrich e ON e.comment_id = cm.comment_id
  WHERE p.gid = :gid
)
SELECT role,
       COUNT(*)                                        AS n,
       ROUND(100.0*COUNT(*)/(SELECT COUNT(*) FROM c),1) AS pct,
       SUM(likes)                                       AS likes_sum,
       ROUND(AVG(length(txt)),1)                        AS avg_len,
       SUM(CASE WHEN is_mass = 1 THEN 1 ELSE 0 END)     AS n_on_mass,
       group_concat(CASE WHEN rk <= 3 THEN comment_id END) AS ex_comment_ids
FROM (SELECT c.*, ROW_NUMBER() OVER (PARTITION BY role ORDER BY length(txt) DESC) rk FROM c)
GROUP BY role ORDER BY n DESC
"""

# คอมเมนต์ที่ "ใช้วิเคราะห์ลูกค้าได้จริง" — ตัดแท็กเพื่อน/ว่าง/สแปม/ขานรับสั้นออก
# เรียงด้วยความยาวข้อความ ไม่ใช่ยอดไลก์ (ไลก์สูงสุดในฐานคือ 10 ใช้จัดอันดับไม่ได้
# และคอมเมนต์ไลก์สูงสุดที่วัดได้คือกองชื่อคนแท็กกัน 8 ชื่อ)
CUSTOMER_SAMPLE_SQL = """
WITH c AS (
  SELECT cm.comment_id, cm.post_id, cm.author, cm.likes, p.is_mass,
         COALESCE(e.body_clean, cm.body) AS txt,
         COALESCE(e.role,'ยังไม่จัด')     AS role
  FROM fb_comment cm
  JOIN fb_post p ON p.post_id = cm.post_id
  LEFT JOIN comment_enrich e ON e.comment_id = cm.comment_id
  WHERE p.gid = :gid
    AND COALESCE(e.is_tag_only, 0) = 0
    AND cm.is_spam = 0
    /* ตัดกองที่ไม่มีสัญญาณลูกค้าออก — สแปมต้องตัดด้วย role ไม่ใช่ธง is_spam
       เพราะ is_spam() ของตัวเก็บ recall แค่ 40% (พลาดพนัน/ใบขับขี่) */
    AND COALESCE(e.role,'ยังไม่จัด') NOT IN ('สแปม','แท็กเพื่อน','ว่าง','ขานรับ','รูป/สติกเกอร์')
    AND length(COALESCE(e.body_clean, cm.body)) >= :min_len
),
/* ตัดข้อความซ้ำเป๊ะทิ้ง — คอมเมนต์แบบ 'ราคาดีมาก' ซ้ำกันหลายอัน
   ถ้าไม่ตัด ตัวอย่างจะเต็มไปด้วยประโยคเดียวกัน กินที่ของเสียงจริง */
u AS (SELECT * FROM (SELECT c.*, ROW_NUMBER() OVER (PARTITION BY txt ORDER BY comment_id) dup FROM c)
      WHERE dup = 1),
r AS (SELECT u.*, ROW_NUMBER() OVER (PARTITION BY role ORDER BY length(txt) DESC) rn FROM u)
SELECT comment_id, post_id, author, likes, txt, role, is_mass
FROM r WHERE rn <= :per_role
/* เอาบทบาทที่หายากขึ้นก่อน (ลูกค้า/คนขาย) แล้วค่อยกองคุยเล่น */
ORDER BY CASE role WHEN 'ลูกค้า' THEN 0 WHEN 'คนขาย' THEN 1 ELSE 2 END,
         length(txt) DESC
LIMIT :limit
"""

# ฮิสโตแกรมชั่วโมง (หน้าเว็บวาดกราฟ + เตือนว่าหน้าต่างเก็บครอบคลุมกี่ชั่วโมง)
HOUR_HIST_SQL = """
SELECT hour_local AS hour, COUNT(*) n,
       MAX(CASE WHEN rn = (c+1)/2 THEN engagement END) med_eng,
       SUM(is_mass) n_mass
FROM (SELECT hour_local, engagement, is_mass,
             ROW_NUMBER() OVER (PARTITION BY hour_local ORDER BY engagement) rn,
             COUNT(*)     OVER (PARTITION BY hour_local) c
      FROM v_post_feat WHERE gid = :gid AND posted_at IS NOT NULL)
GROUP BY hour_local ORDER BY hour_local
"""

# ลายเซ็นข้อมูลนำเข้า — ใช้ตัดสินว่าบทวิเคราะห์เก่าล้าสมัยหรือยัง
INPUT_SIG_SQL = """
SELECT COUNT(*) AS n_post, COALESCE(SUM(is_mass),0) AS n_mass,
       COALESCE(MAX(collected_at),0) AS last_collect,
       COALESCE(SUM(engagement),0) AS eng_sum,
       (SELECT COUNT(*) FROM fb_comment c JOIN fb_post p2 ON p2.post_id=c.post_id
         WHERE p2.gid = :gid) AS n_comment
FROM fb_post WHERE gid = :gid
"""
