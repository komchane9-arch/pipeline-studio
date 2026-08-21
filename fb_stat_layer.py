"""ชั้น SQL — คำนวณสถิติต่อกลุ่ม + ทดสอบฟีเจอร์ทีละตัว แล้วเก็บลง fb_analysis.db

หลักการ: งานนับทั้งหมดจบที่ SQL · Python แตะแค่สูตรปิด (erfc ตอนแปลง z→p)
LLM ไม่ต้องนับอะไรเลย เห็นแต่ผลที่ผ่านด่านนัยสำคัญแล้ว

การทดสอบที่ใช้: Mann-Whitney U (rank-sum) แบบมีตัวแก้ค่าเสมอ (tie correction)
  เพราะ engagement เบ้สุดขั้ว — มัธยฐาน 4–6 แต่ค่าสูงสุด 23,445
  ค่าเฉลี่ย/ t-test ใช้ไม่ได้เลย ต้องเป็นการทดสอบเชิงอันดับเท่านั้น
  AUC ที่ได้อ่านตรงตัวว่า "สุ่มโพสต์แมส 1 ใบ กับไม่แมส 1 ใบ โอกาสที่แมสมีค่าฟีเจอร์สูงกว่า"

ด่านสองชั้นที่ต้องผ่านพร้อมกันถึงจะขึ้นสถานะ pass:
  1) p <= P_MAX (Bonferroni)  — กันบังเอิญ
  2) |AUC-0.5| >= AUC_MIN     — กัน "มีนัยสำคัญแต่ผลจิ๋ว" ตอน n ใหญ่
  3) ทิศทางต้องตรงกับ auc_core (เป้าหมายที่ไม่พึ่งยอดแชร์)
     ข้อ 3 มีไว้เพราะ shares เชื่อไม่ได้ (ดู shares_trust) — ถ้าข้อสรุปพลิก
     เมื่อตัดแชร์ออก แปลว่ามันเป็นผลของแชร์ ไม่ใช่ของเนื้อหา
"""
from __future__ import annotations

import math
import sys
import time

import fb_stat_store as st

# ── วิวฟีเจอร์: แปลงโพสต์ดิบเป็นตัวแปรที่ทดสอบได้ ───────────────────────────
V_FEAT = """
CREATE TEMP VIEW IF NOT EXISTS v_feat AS
SELECT
  p.post_id, p.gid, p.is_mass,
  p.engagement                                            AS eng,
  COALESCE(p.reactions,0) + COALESCE(p.comments,0)        AS eng_core,
  p.caption_len                                           AS f_cap_len,
  CASE WHEN p.caption_len > 0   THEN 1 ELSE 0 END         AS f_cap_has,
  CASE WHEN p.caption_len > 80  THEN 1 ELSE 0 END         AS f_cap_gt80,
  p.images_n                                              AS f_img_n,
  CASE WHEN p.images_n > 0      THEN 1 ELSE 0 END         AS f_img_has,
  CASE WHEN p.images_n >= 5     THEN 1 ELSE 0 END         AS f_img_ge5,
  af.c                                                    AS f_author_freq,
  CASE WHEN af.c = 1            THEN 1 ELSE 0 END         AS f_author_once,
  CAST(strftime('%H', p.posted_at, 'unixepoch', '+7 hours') AS INTEGER) AS f_hour,
  CASE WHEN CAST(strftime('%H', p.posted_at, 'unixepoch', '+7 hours') AS INTEGER) >= 15
       THEN 1 ELSE 0 END                                  AS f_hour_pm,
  CASE WHEN instr(p.caption, '#') > 0 THEN 1 ELSE 0 END   AS f_hashtag,
  CASE WHEN instr(p.caption,'?')>0 OR instr(p.caption,'ไหม')>0
         OR instr(p.caption,'มั้ย')>0 OR instr(p.caption,'บ้าง')>0
       THEN 1 ELSE 0 END                                  AS f_question,
  CASE WHEN p.caption_len = 0 THEN 0
       ELSE LENGTH(p.caption) - LENGTH(REPLACE(p.caption, char(10), '')) + 1 END AS f_lines,
  CASE WHEN instr(p.caption,'ราคา')>0 OR instr(p.caption,'บาท')>0
         OR instr(p.caption,'สนใจ')>0 OR instr(p.caption,'ทัก')>0
         OR instr(p.caption,'ขาย')>0 THEN 1 ELSE 0 END    AS f_sell,
  COALESCE(im.altlen, 0)                                  AS f_alt_len,
  (strftime('%s','now') - p.posted_at) / 3600.0           AS f_age_h,
  p.feed_rank                                             AS f_feed_rank
FROM src.fb_post p
LEFT JOIN (SELECT gid, author, COUNT(*) c FROM src.fb_post GROUP BY gid, author) af
       ON af.gid = p.gid AND af.author = p.author
LEFT JOIN (SELECT post_id, SUM(LENGTH(alt)) altlen FROM src.post_image GROUP BY post_id) im
       ON im.post_id = p.post_id
"""

# ── Mann-Whitney U + AUC + z ทำใน SQL ทั้งก้อน ─────────────────────────────
# {feat} และ {tgt} ถูกแทนจาก whitelist ในโค้ดเท่านั้น (ไม่รับค่าจากผู้ใช้)
SQL_MWU = """
WITH b AS (
  SELECT ({tgt}) AS g, ({feat}) AS x
  FROM v_feat WHERE gid = :gid AND ({feat}) IS NOT NULL
),
r AS (SELECT g, x, ROW_NUMBER() OVER (ORDER BY x) AS rn FROM b),
t AS (SELECT x, AVG(rn) AS ar, COUNT(*) AS c FROM r GROUP BY x),
j AS (SELECT r.g AS g, t.ar AS ar FROM r JOIN t ON t.x = r.x),
agg AS (SELECT COUNT(*) n, SUM(g) n1, SUM(1-g) n0,
               SUM(CASE WHEN g=1 THEN ar ELSE 0 END) r1 FROM j),
tc AS (SELECT COALESCE(SUM(c*c*c - c), 0) tie FROM t)
SELECT agg.n, agg.n1, agg.n0,
       (agg.r1 - agg.n1*(agg.n1+1)/2.0)                       AS u,
       (agg.r1 - agg.n1*(agg.n1+1)/2.0)/(agg.n1*agg.n0*1.0)   AS auc,
       ((agg.r1 - agg.n1*(agg.n1+1)/2.0) - agg.n1*agg.n0/2.0)
         / sqrt((agg.n1*agg.n0/12.0)
                * ((agg.n+1) - tc.tie/(agg.n*(agg.n-1.0))))   AS z,
       (SELECT COUNT(DISTINCT x) FROM b)                      AS n_distinct
FROM agg, tc
"""

# มัธยฐานของฟีเจอร์ แยกตามฝั่งแมส/ไม่แมส (nearest-rank)
SQL_MED_BY = """
WITH b AS (SELECT ({feat}) AS x FROM v_feat
           WHERE gid=:gid AND ({tgt})=:g AND ({feat}) IS NOT NULL)
SELECT (SELECT x FROM b ORDER BY x
        LIMIT 1 OFFSET (SELECT CAST((COUNT(*)-1)*0.5 AS INT) FROM b)) AS med,
       (SELECT COUNT(*) FROM b) AS n
"""

# ตารางแบ่งช่วงของฟีเจอร์ — ใช้ทั้งในบรีฟและหน้าเว็บ
SQL_BUCKET = """
WITH b AS (SELECT eng, is_mass FROM v_feat
           WHERE gid=:gid AND ({feat}) >= :lo AND ({feat}) < :hi)
SELECT (SELECT COUNT(*) FROM b) n,
       (SELECT eng FROM b ORDER BY eng
          LIMIT 1 OFFSET (SELECT CAST((COUNT(*)-1)*0.5 AS INT) FROM b)) eng_p50,
       (SELECT ROUND(AVG(is_mass)*100.0, 1) FROM b) mass_pct,
       (SELECT ROUND(AVG(CASE WHEN eng=0 THEN 100.0 ELSE 0 END), 1) FROM b) zero_pct
"""

# สถิติหลักของกลุ่ม (ครั้งเดียวจบ)
SQL_GROUP_CORE = """
WITH b AS (SELECT * FROM v_feat WHERE gid = :gid)
SELECT
  (SELECT COUNT(*) FROM b)                                          n_posts,
  (SELECT SUM(is_mass) FROM b)                                      n_mass,
  (SELECT COUNT(*)-SUM(is_mass) FROM b)                             n_normal,
  (SELECT eng FROM b ORDER BY eng LIMIT 1
     OFFSET (SELECT CAST((COUNT(*)-1)*0.50 AS INT) FROM b))         eng_p50,
  (SELECT eng FROM b ORDER BY eng LIMIT 1
     OFFSET (SELECT CAST((COUNT(*)-1)*0.75 AS INT) FROM b))         eng_p75,
  (SELECT eng FROM b ORDER BY eng LIMIT 1
     OFFSET (SELECT CAST((COUNT(*)-1)*0.90 AS INT) FROM b))         eng_p90,
  (SELECT eng FROM b ORDER BY eng LIMIT 1
     OFFSET (SELECT CAST((COUNT(*)-1)*0.95 AS INT) FROM b))         eng_p95,
  (SELECT MAX(eng) FROM b)                                          eng_max,
  (SELECT ROUND(AVG(CASE WHEN eng=0 THEN 100.0 ELSE 0 END),1) FROM b) eng_zero_pct,
  (SELECT eng_core FROM b ORDER BY eng_core LIMIT 1
     OFFSET (SELECT CAST((COUNT(*)-1)*0.50 AS INT) FROM b))         core_p50,
  (SELECT eng_core FROM b ORDER BY eng_core LIMIT 1
     OFFSET (SELECT CAST((COUNT(*)-1)*0.90 AS INT) FROM b))         core_p90,
  (SELECT ROUND(AVG(f_cap_has)*100.0,1) FROM b)                     cap_pct,
  (SELECT f_cap_len FROM b WHERE f_cap_has=1 ORDER BY f_cap_len LIMIT 1
     OFFSET (SELECT CAST((COUNT(*)-1)*0.5 AS INT) FROM b WHERE f_cap_has=1)) cap_p50_len,
  (SELECT ROUND(AVG(f_img_has)*100.0,1) FROM b)                     img_pct,
  (SELECT f_img_n FROM b WHERE f_img_has=1 ORDER BY f_img_n LIMIT 1
     OFFSET (SELECT CAST((COUNT(*)-1)*0.5 AS INT) FROM b WHERE f_img_has=1)) img_p50,
  (SELECT COUNT(DISTINCT post_id) FROM b)                           n_ids,
  (SELECT COUNT(*) FROM (SELECT DISTINCT author FROM src.fb_post WHERE gid=:gid)) authors_n,
  (SELECT ROUND(AVG(f_author_once)*100.0,1) FROM b)                 author_once_pct,
  (SELECT MIN(posted_at) FROM src.fb_post WHERE gid=:gid)           first_post_at,
  (SELECT MAX(posted_at) FROM src.fb_post WHERE gid=:gid)           last_post_at,
  (SELECT COUNT(DISTINCT f_hour) FROM b)                            hours_covered,
  (SELECT COUNT(DISTINCT date(posted_at,'unixepoch','+7 hours'))
     FROM src.fb_post WHERE gid=:gid)                               days_covered,
  (SELECT ROUND(AVG(CASE WHEN COALESCE(shares,0)>0 THEN 100.0 ELSE 0 END),1)
     FROM src.fb_post WHERE gid=:gid)                               shares_pos_pct
"""

# ความครอบคลุมคอมเมนต์ — ตัวชี้ว่าจะวิเคราะห์ฐานลูกค้าได้ไหม
SQL_CMT_COV = """
SELECT
  (SELECT COALESCE(SUM(comments),0) FROM src.fb_post WHERE gid=:gid)      cmt_onfb,
  (SELECT COALESCE(SUM(comments_expected),0) FROM src.fb_post WHERE gid=:gid) cmt_expected,
  (SELECT COUNT(*) FROM src.fb_comment c JOIN src.fb_post p
     ON p.post_id=c.post_id WHERE p.gid=:gid)                             cmt_got,
  (SELECT COUNT(DISTINCT c.post_id) FROM src.fb_comment c JOIN src.fb_post p
     ON p.post_id=c.post_id WHERE p.gid=:gid)                             cmt_posts_with,
  (SELECT COUNT(*) FROM src.fb_post WHERE gid=:gid AND comments_state='pending') st_pending
"""

SQL_HOUR = """
WITH b AS (SELECT f_hour h, eng, is_mass FROM v_feat WHERE gid=:gid AND f_hour IS NOT NULL),
r AS (SELECT h, eng, is_mass,
             ROW_NUMBER() OVER (PARTITION BY h ORDER BY eng) rn,
             COUNT(*)     OVER (PARTITION BY h)              c FROM b)
SELECT h, MAX(c) n, SUM(is_mass) mass_n,
       MAX(CASE WHEN rn = (c+1)/2 THEN eng END) eng_p50
FROM r GROUP BY h ORDER BY h
"""

# ── ทะเบียนฟีเจอร์ ────────────────────────────────────────────────────────
# (คีย์, นิพจน์, ชนิด, ป้ายไทย, ช่วงแบ่ง [(lo,hi,ชื่อ)], เหตุผลที่ถูกบล็อก)
FEATURES = [
    ("cap_len", "f_cap_len", "num", "ความยาว caption (ตัวอักษร)",
     [(1, 41, "1–40"), (41, 81, "41–80"), (81, 161, "81–160"), (161, 10**9, ">160")], ""),
    ("cap_has", "f_cap_has", "bin", "มีข้อความประกอบหรือไม่",
     [(0, 1, "ไม่มี caption"), (1, 2, "มี caption")], ""),
    ("cap_gt80", "f_cap_gt80", "bin", "caption ยาวเกิน 80 ตัวอักษร",
     [(0, 1, "≤80"), (1, 2, ">80")], ""),
    ("img_n", "f_img_n", "num", "จำนวนรูป",
     [(1, 2, "1 รูป"), (2, 5, "2–4 รูป"), (5, 10**9, "5+ รูป")], ""),
    ("img_has", "f_img_has", "bin", "มีรูปหรือไม่",
     [(0, 1, "ไม่มีรูป"), (1, 2, "มีรูป")], ""),
    ("img_ge5", "f_img_ge5", "bin", "รูป 5 ใบขึ้นไป",
     [(0, 1, "<5 รูป"), (1, 2, "≥5 รูป")], ""),
    ("author_freq", "f_author_freq", "num", "จำนวนโพสต์ของคนโพสต์คนนั้นในกลุ่ม",
     [(1, 2, "โพสต์ครั้งเดียว"), (2, 5, "2–4 ใบ"), (5, 11, "5–10 ใบ"), (11, 10**9, "11+ ใบ")], ""),
    ("author_once", "f_author_once", "bin", "เป็นคนโพสต์ขาจร (โพสต์ใบเดียว)",
     [(0, 1, "ขาประจำ"), (1, 2, "ขาจร")], ""),
    ("alt_len", "f_alt_len", "num", "ความยาวคำบรรยายภาพที่ FB อ่านได้ (alt)",
     [(0, 1, "ไม่มี alt"), (1, 61, "1–60"), (61, 10**9, ">60")], ""),
    ("hour", "f_hour", "num", "ชั่วโมงที่โพสต์ (เวลาไทย)",
     [(6, 12, "06–11"), (12, 15, "12–14"), (15, 18, "15–17"), (18, 24, "18–23")], ""),
    ("hour_pm", "f_hour_pm", "bin", "โพสต์ช่วงบ่ายเย็น (15:00+)",
     [(0, 1, "ก่อนบ่าย 3"), (1, 2, "บ่าย 3 ขึ้นไป")], ""),
    ("hashtag", "f_hashtag", "bin", "มีแฮชแท็ก",
     [(0, 1, "ไม่มี #"), (1, 2, "มี #")], ""),
    ("question", "f_question", "bin", "ตั้งคำถามใน caption",
     [(0, 1, "ไม่ถาม"), (1, 2, "ถาม")], ""),
    ("lines", "f_lines", "num", "จำนวนบรรทัดของ caption",
     [(0, 1, "ไม่มีข้อความ"), (1, 2, "1 บรรทัด"), (2, 10**9, "2+ บรรทัด")], ""),
    ("sell", "f_sell", "bin", "มีคำขายของ (ราคา/บาท/สนใจ/ทัก/ขาย)",
     [(0, 1, "ไม่มี"), (1, 2, "มี")], ""),
    # สองตัวล่างคำนวณไว้ให้เห็นว่า "เคยสงสัย" แต่ห้ามเอาไปสรุป
    ("age_h", "f_age_h", "num", "อายุโพสต์ (ชั่วโมง)", [],
     "อายุโพสต์เป็นผลของ 'ตอนที่บอทเข้าไปเก็บ' ไม่ใช่คุณสมบัติของโพสต์ "
     "และหน้าต่างเก็บแคบ (ไม่กี่วัน) ทำให้มันสัมพันธ์กับทุกอย่างแบบหลอกๆ"),
    ("feed_rank", "f_feed_rank", "num", "ลำดับที่เจอบนฟีด", [],
     "เป็นผลของอัลกอริทึมฟีดขณะบอทเลื่อน ไม่ใช่คุณสมบัติของโพสต์ — "
     "วัดแบบ TOP/BOT เหมือนมีนัยสำคัญ แต่วัดทั้งกลุ่มแล้วหายไป"),
]
FEAT_BY_KEY = {f[0]: f for f in FEATURES}

TGT_MASS = "is_mass"
TGT_CORE = "CASE WHEN eng_core >= :cut THEN 1 ELSE 0 END"


def _p_from_z(z: float | None) -> float | None:
    """สองหาง จาก z — สูตรปิด ไม่ใช่การนับ จึงทำใน Python ได้โดยไม่ผิดกติกา"""
    if z is None:
        return None
    return math.erfc(abs(z) / math.sqrt(2.0))


def refresh_group(conn, gid: str) -> dict:
    """คำนวณสถิติ + ทดสอบฟีเจอร์ทั้งหมดของกลุ่มหนึ่ง แล้วเขียนทับของเดิม"""
    now = int(time.time())
    ih = st.input_hash(conn, gid)
    g = conn.execute("SELECT name, members FROM src.fb_group WHERE gid=?", (gid,)).fetchone()
    if g is None:
        raise SystemExit(f"ไม่มีกลุ่ม {gid} ในฐาน")
    core = conn.execute(SQL_GROUP_CORE, {"gid": gid}).fetchone()
    if not core["n_posts"]:
        raise SystemExit(f"กลุ่ม {gid} ยังไม่มีโพสต์ในฐาน — ยังคำนวณอะไรไม่ได้")
    cov = conn.execute(SQL_CMT_COV, {"gid": gid}).fetchone()

    # เกณฑ์ top10% ของ eng_core ใช้เป็นเป้าหมายสำรองที่ไม่พึ่งยอดแชร์
    cut = core["core_p90"] if core["core_p90"] is not None else 10**9
    cut = max(int(cut), 1)

    # ── ความน่าเชื่อถือของยอดแชร์ ──
    # FB มักไม่แสดงยอดแชร์บนการ์ดฟีด แต่ตัวเก็บบันทึกเป็น 0 (กลไก unknown ไม่เคยทำงาน)
    # ถ้าโพสต์ที่มีแชร์>0 น้อยกว่า 25% ให้ถือว่า "แยกไม่ออกระหว่าง 0 จริงกับอ่านไม่ได้"
    shares_trust = "ok" if (core["shares_pos_pct"] or 0) >= 25.0 else "suspect"

    cmt_cov = (cov["cmt_got"] / cov["cmt_onfb"] * 100.0) if cov["cmt_onfb"] else 0.0
    cmt_content = conn.execute(
        "SELECT COUNT(*) FROM comment_label WHERE gid=? AND is_tagonly=0 AND is_lowinfo=0 "
        "AND COALESCE(NULLIF(llm_role,''), rule_role) <> 'spam'", (gid,)).fetchone()[0]

    ok_content = int(core["n_mass"] >= st.MIN_MASS and core["n_posts"] >= st.MIN_POSTS)
    ok_aud = int(cmt_content >= st.MIN_CMT and cmt_cov >= st.MIN_CMT_COV * 100)
    reasons = []
    if core["n_mass"] < st.MIN_MASS:
        reasons.append(f"โพสต์แมสมีแค่ {core['n_mass']} ใบ (ต้อง ≥{st.MIN_MASS}) — สรุปสูตรไม่ได้")
    if core["n_posts"] < st.MIN_POSTS:
        reasons.append(f"โพสต์รวม {core['n_posts']} ใบ (ต้อง ≥{st.MIN_POSTS})")
    if cmt_content < st.MIN_CMT:
        reasons.append(f"คอมเมนต์ที่มีเนื้อหาจริง {cmt_content} อัน (ต้อง ≥{st.MIN_CMT}) — วิเคราะห์ฐานลูกค้าไม่ได้")
    if cmt_cov < st.MIN_CMT_COV * 100:
        reasons.append(f"เก็บคอมเมนต์ได้ {cmt_cov:.1f}% ของที่ FB บอกว่ามี (ต้อง ≥{int(st.MIN_CMT_COV*100)}%)")
    if shares_trust == "suspect":
        reasons.append(f"ยอดแชร์เชื่อไม่ได้ — มีแชร์>0 แค่ {core['shares_pos_pct']}% "
                       "แปลว่า engagement/is_mass น่าจะต่ำกว่าความจริง")

    conn.execute("DELETE FROM group_stats WHERE gid=?", (gid,))
    conn.execute("""
        INSERT INTO group_stats (gid,name,members,computed_at,input_hash,
          n_posts,n_mass,n_normal,eng_p50,eng_p75,eng_p90,eng_p95,eng_max,eng_zero_pct,
          core_p50,core_p90,cap_pct,cap_p50_len,img_pct,img_p50,authors_n,author_once_pct,
          first_post_at,last_post_at,hours_covered,days_covered,
          shares_pos_pct,shares_trust,cmt_expected,cmt_got,cmt_cov_pct,cmt_posts_with,
          cmt_content,ok_content,ok_audience,block_reason)
        VALUES (?,?,?,?,?, ?,?,?,?,?,?,?,?,?, ?,?,?,?,?,?,?,?, ?,?,?,?, ?,?,?,?,?,?, ?,?,?,?)
    """, (gid, g["name"], g["members"], now, ih,
          core["n_posts"], core["n_mass"], core["n_normal"], core["eng_p50"], core["eng_p75"],
          core["eng_p90"], core["eng_p95"], core["eng_max"], core["eng_zero_pct"],
          core["core_p50"], core["core_p90"], core["cap_pct"], core["cap_p50_len"],
          core["img_pct"], core["img_p50"], core["authors_n"], core["author_once_pct"],
          core["first_post_at"], core["last_post_at"], core["hours_covered"],
          core["days_covered"], core["shares_pos_pct"], shares_trust,
          cov["cmt_expected"], cov["cmt_got"], round(cmt_cov, 1), cov["cmt_posts_with"],
          cmt_content, ok_content, ok_aud, " · ".join(reasons)))

    conn.execute("DELETE FROM group_hour WHERE gid=?", (gid,))
    for r in conn.execute(SQL_HOUR, {"gid": gid}).fetchall():
        conn.execute("INSERT INTO group_hour (gid,hour,n,eng_p50,mass_n) VALUES (?,?,?,?,?)",
                     (gid, r["h"], r["n"], r["eng_p50"], r["mass_n"]))

    # ── ทดสอบฟีเจอร์ทีละตัว ──
    conn.execute("DELETE FROM group_feature WHERE gid=?", (gid,))
    conn.execute("DELETE FROM feature_bucket WHERE gid=?", (gid,))
    n_pass = 0
    for key, expr, kind, label, buckets, blocked in FEATURES:
        m = conn.execute(SQL_MWU.format(feat=expr, tgt=TGT_MASS), {"gid": gid}).fetchone()
        c = conn.execute(SQL_MWU.format(feat=expr, tgt=TGT_CORE),
                         {"gid": gid, "cut": cut}).fetchone()
        auc, z = m["auc"], m["z"]
        p = _p_from_z(z)
        auc_core = c["auc"]
        med1 = conn.execute(SQL_MED_BY.format(feat=expr, tgt=TGT_MASS),
                            {"gid": gid, "g": 1}).fetchone()["med"]
        med0 = conn.execute(SQL_MED_BY.format(feat=expr, tgt=TGT_MASS),
                            {"gid": gid, "g": 0}).fetchone()["med"]

        status, reason = "reject", "ไม่ผ่านเกณฑ์"
        n_tot, n1, n0 = m["n"] or 0, m["n1"] or 0, m["n0"] or 0
        minority = min(n1, n0) / n_tot if n_tot else 0.0
        if blocked:
            status, reason = "blocked", blocked
        elif (m["n_distinct"] or 0) < 2:
            status, reason = "constant", f"ทั้งกลุ่มมีค่าเดียว ({n_tot} ใบ) — ใช้แยกอะไรไม่ได้"
        elif kind == "bin" and _minority_share(conn, gid, expr) < st.MIN_MINORITY:
            status, reason = "constant", (
                f"ฝั่งน้อยเหลือ {_minority_share(conn, gid, expr)*100:.1f}% ของกลุ่ม "
                f"(ต้อง ≥{int(st.MIN_MINORITY*100)}%) — เกือบคงที่ ทดสอบไม่มีความหมาย")
        elif n1 < st.MIN_MASS:
            status, reason = "reject", f"โพสต์แมสมีแค่ {n1} ใบ ยังทดสอบไม่ได้"
        elif auc is None or p is None:
            status, reason = "reject", "ค่าเสมอกันหมด คำนวณอันดับไม่ได้"
        elif p <= st.P_MAX and abs(auc - 0.5) >= st.AUC_MIN:
            same_dir = auc_core is not None and (auc - 0.5) * (auc_core - 0.5) > 0
            if same_dir:
                status, reason = "pass", "ผ่านทั้ง p, ขนาดผล และยืนยันซ้ำโดยไม่ใช้ยอดแชร์"
                n_pass += 1
            else:
                status, reason = "weak", (
                    f"ผ่าน p/ขนาดผล แต่พลิกทิศเมื่อตัดยอดแชร์ออก (AUC {auc:.3f} vs core {auc_core}) "
                    "— น่าจะเป็นผลของการแชร์ ไม่ใช่ของเนื้อหา")
        elif p <= 0.05 or abs(auc - 0.5) >= st.AUC_MIN:
            status, reason = "weak", (
                f"มีสัญญาณแต่ไม่ผ่านด่านเข้ม (p={p:.2g} ต้อง ≤{st.P_MAX}, "
                f"|AUC-0.5|={abs(auc-0.5):.3f} ต้อง ≥{st.AUC_MIN})")
        else:
            reason = f"ไม่ต่าง (p={p:.2g}, AUC={auc:.3f})"

        conn.execute("""INSERT INTO group_feature
            (gid,feat,kind,label,n,n_mass,n_normal,auc,z,p,auc_core,med_mass,med_normal,
             status,reason,computed_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                     (gid, key, kind, label, n_tot, n1, n0, auc, z, p, auc_core,
                      med1, med0, status, reason, now))

        if status in ("pass", "weak"):
            for i, (lo, hi, bname) in enumerate(buckets):
                b = conn.execute(SQL_BUCKET.format(feat=expr),
                                 {"gid": gid, "lo": lo, "hi": hi}).fetchone()
                if b["n"]:
                    conn.execute("""INSERT INTO feature_bucket
                        (gid,feat,bucket,ord,n,eng_p50,mass_pct,zero_pct)
                        VALUES (?,?,?,?,?,?,?,?)""",
                                 (gid, key, bname, i, b["n"], b["eng_p50"],
                                  b["mass_pct"], b["zero_pct"]))
    conn.commit()
    return {"gid": gid, "n_posts": core["n_posts"], "n_mass": core["n_mass"],
            "n_pass": n_pass, "ok_content": ok_content, "ok_audience": ok_aud,
            "input_hash": ih, "shares_trust": shares_trust}


def _minority_share(conn, gid: str, expr: str) -> float:
    r = conn.execute(
        f"SELECT AVG(CASE WHEN ({expr})>0 THEN 1.0 ELSE 0 END) a, COUNT(*) n "
        f"FROM v_feat WHERE gid=:gid AND ({expr}) IS NOT NULL", {"gid": gid}).fetchone()
    a = r["a"] or 0.0
    return min(a, 1.0 - a)


def cross_check(conn, gid: str, feat_a: str, feat_b: str) -> list[dict]:
    """ตัดขวางสองฟีเจอร์ — พิสูจน์ว่าไม่ใช่ตัวเดียวปลอมตัวมาเป็นสองตัว

    คืนตาราง 2x2: ในแต่ละฝั่งของ A ฟีเจอร์ B ยังทำให้ %แมส ต่างกันอยู่ไหม
    """
    ea = FEAT_BY_KEY[feat_a][1]
    eb = FEAT_BY_KEY[feat_b][1]
    med_a = conn.execute(f"SELECT AVG(x) FROM (SELECT ({ea}) x FROM v_feat WHERE gid=:g "
                         f"ORDER BY x LIMIT 2 - (SELECT COUNT(*) FROM v_feat WHERE gid=:g)%2 "
                         f"OFFSET (SELECT (COUNT(*)-1)/2 FROM v_feat WHERE gid=:g))",
                         {"g": gid}).fetchone()[0]
    med_b = conn.execute(f"SELECT AVG(x) FROM (SELECT ({eb}) x FROM v_feat WHERE gid=:g "
                         f"ORDER BY x LIMIT 2 - (SELECT COUNT(*) FROM v_feat WHERE gid=:g)%2 "
                         f"OFFSET (SELECT (COUNT(*)-1)/2 FROM v_feat WHERE gid=:g))",
                         {"g": gid}).fetchone()[0]
    out = []
    for la, sa in ((f"{feat_a} ≤ {med_a:g}", f"({ea}) <= {med_a}"),
                   (f"{feat_a} > {med_a:g}", f"({ea}) > {med_a}")):
        for lb, sb in ((f"{feat_b} ≤ {med_b:g}", f"({eb}) <= {med_b}"),
                       (f"{feat_b} > {med_b:g}", f"({eb}) > {med_b}")):
            r = conn.execute(f"""
                WITH b AS (SELECT eng, is_mass FROM v_feat WHERE gid=:g AND {sa} AND {sb})
                SELECT (SELECT COUNT(*) FROM b) n,
                       (SELECT eng FROM b ORDER BY eng LIMIT 1
                          OFFSET (SELECT CAST((COUNT(*)-1)*0.5 AS INT) FROM b)) med,
                       (SELECT ROUND(AVG(is_mass)*100.0,1) FROM b) mass_pct
            """, {"g": gid}).fetchone()
            out.append({"a": la, "b": lb, "n": r["n"], "eng_p50": r["med"],
                        "mass_pct": r["mass_pct"]})
    return out


def main() -> int:
    conn = st.connect(write=True)
    conn.execute(V_FEAT)
    gids = sys.argv[1:] or [r[0] for r in conn.execute(
        "SELECT gid FROM src.fb_post GROUP BY gid HAVING COUNT(*) > 0")]
    for gid in gids:
        info = refresh_group(conn, gid)
        print(f"[{gid}] โพสต์ {info['n_posts']} · แมส {info['n_mass']} · "
              f"ฟีเจอร์ผ่านด่าน {info['n_pass']} · content={info['ok_content']} "
              f"audience={info['ok_audience']} · shares={info['shares_trust']}")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
