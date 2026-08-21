"""สร้าง "ซองข้อมูล" ต่อกลุ่ม สำหรับให้ Claude ในแชทอ่านแล้ววิเคราะห์ + รับผลกลับ

ปรัชญา: ซองนี้ต้องไม่มีอะไรให้ LLM ต้องนับเลย ตัวเลขทุกตัวคำนวณมาแล้วจาก SQL
LLM มีหน้าที่เดียวคือ "แปลตัวเลขที่ผ่านด่านนัยสำคัญแล้ว เป็นภาษาคน" และอ่านตัวอย่างจริง
เพื่ออธิบายว่า *ทำไม* โพสต์แบบนั้นถึงไปได้ — ซึ่งเป็นสิ่งที่ SQL ทำแทนไม่ได้

ตัวอย่างที่ใส่ในซองเลือกแบบมีเหตุผล ไม่ได้สุ่มมั่ว:
  แมส        — เอามาให้มากที่สุดเท่าที่งบตัวอักษรไหว (ของหายาก)
  เกือบแมส   — engagement 50–100 คือคู่เทียบที่ให้ข้อมูลมากที่สุด (ต่างกันนิดเดียวแต่ไม่ถึง)
  ธรรมดา     — รอบมัธยฐานของกลุ่ม
  ตาย        — engagement = 0
ทุกใบมี handle (P1, P2, …) แทน post_id ยาวๆ เพื่อประหยัดที่ และเพื่อให้ตอนเขียนกลับ
Claude อ้างได้เฉพาะ handle ที่มีอยู่ในซองจริงเท่านั้น (แต่ง id เองไม่ได้)

ใช้:
  python fb_stat_brief.py <gid>              → พิมพ์ซองออกจอ + บันทึกลง data/briefs/
  python fb_stat_brief.py --apply <gid> <ไฟล์ json>  → เขียนผลวิเคราะห์กลับเข้าฐาน
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import fb_stat_store as st
import fb_stat_layer as sl

BRIEF_DIR = st.HERE / "data" / "briefs"
CAP_CUT = 220          # ตัด caption ที่ยาวเกินนี้ (เก็บหัวไว้ อ่านรู้เรื่องพอ)
N_MASS = 30            # ตัวอย่างโพสต์แมสสูงสุด
N_NEAR = 12            # เกือบแมส
N_MID = 10             # ธรรมดา
N_DEAD = 8             # ตาย
N_CMT = 30             # คอมเมนต์ตัวอย่าง

# ── ตัวอย่างโพสต์แบ่งชั้น — ชั้นเดียวจบใน SQL ────────────────────────────────
SQL_SAMPLE = """
WITH b AS (SELECT * FROM v_feat WHERE gid = :gid),
med AS (SELECT eng FROM b ORDER BY eng LIMIT 1
          OFFSET (SELECT CAST((COUNT(*)-1)*0.5 AS INT) FROM b)),
s AS (
  SELECT 'mass' AS tier, 1 AS ord, post_id, eng FROM b WHERE is_mass=1
    ORDER BY eng DESC LIMIT :n_mass
),
s2 AS (
  SELECT 'near' AS tier, 2 AS ord, post_id, eng FROM b
   WHERE is_mass=0 AND eng BETWEEN 50 AND 100 ORDER BY eng DESC LIMIT :n_near
),
s3 AS (
  SELECT 'mid' AS tier, 3 AS ord, post_id, eng FROM b
   WHERE is_mass=0 AND eng BETWEEN (SELECT eng FROM med) AND (SELECT eng FROM med)+2
   ORDER BY post_id LIMIT :n_mid
),
s4 AS (
  SELECT 'dead' AS tier, 4 AS ord, post_id, eng FROM b
   WHERE eng = 0 ORDER BY post_id LIMIT :n_dead
),
pick AS (SELECT * FROM s UNION ALL SELECT * FROM s2
         UNION ALL SELECT * FROM s3 UNION ALL SELECT * FROM s4)
SELECT pick.tier, pick.ord, p.post_id, p.author, p.engagement, p.reactions, p.comments,
       p.shares, p.images_n, p.caption_len,
       CAST(strftime('%H', p.posted_at,'unixepoch','+7 hours') AS INTEGER) hh,
       (SELECT COUNT(*) FROM src.fb_post q WHERE q.gid=p.gid AND q.author=p.author) author_n,
       substr(replace(replace(p.caption, char(10), ' / '), char(13), ''), 1, :cut) cap,
       -- alt ของ FB มัก OCR เพี้ยนและซ้ำกันทุกใบ เอาแค่ใบแรก 45 ตัวอักษรพอเป็นเบาะแสภาพ
       (SELECT substr(alt,1,45) FROM src.post_image i WHERE i.post_id=p.post_id
          AND alt<>'' AND alt<>'ไม่มีคำอธิบายรูปภาพ' ORDER BY idx LIMIT 1) alts
FROM pick JOIN src.fb_post p ON p.post_id = pick.post_id
ORDER BY pick.ord, p.engagement DESC
"""

# ── คอมเมนต์สำหรับวิเคราะห์ฐานลูกค้า — คัดเฉพาะที่ล้างแล้วมีเนื้อหาจริง ─────────
SQL_CMT = """
SELECT l.comment_id, l.post_id, c.author, l.body_clean, c.likes,
       COALESCE(NULLIF(l.llm_role,''), l.rule_role) role, l.rule_hit,
       p.engagement post_eng, p.is_mass
FROM comment_label l
JOIN src.fb_comment c ON c.comment_id = l.comment_id
JOIN src.fb_post p    ON p.post_id    = l.post_id
WHERE l.gid = :gid AND l.is_tagonly = 0 AND l.is_lowinfo = 0
ORDER BY CASE COALESCE(NULLIF(l.llm_role,''), l.rule_role)
           WHEN 'customer' THEN 0 WHEN 'seller' THEN 1 WHEN 'spam' THEN 2 ELSE 3 END,
         c.likes DESC, length(l.body_clean) DESC
LIMIT :n
"""

SQL_CMT_ROLES = """
SELECT COALESCE(NULLIF(llm_role,''), rule_role) role, COUNT(*) n,
       SUM(is_tagonly) tagonly, SUM(is_lowinfo) lowinfo
FROM comment_label WHERE gid=:gid GROUP BY 1 ORDER BY n DESC
"""


def _thai_dt(ts: int | None) -> str:
    if not ts:
        return "-"
    return time.strftime("%d/%m/%Y", time.localtime(ts))


def build(gid: str) -> tuple[str, dict]:
    conn = st.connect(write=True)
    conn.execute(sl.V_FEAT)
    g = conn.execute("SELECT * FROM group_stats WHERE gid=?", (gid,)).fetchone()
    # บอทเก็บเพิ่มตลอดเวลา ถ้าสถิติล้าสมัยให้คำนวณใหม่ทันที ห้ามสร้างซองจากเลขเก่า
    # (ไม่งั้น input_hash ในซองจะไม่ตรงกับฐาน แล้วเขียนผลกลับไม่ได้ตอนท้าย)
    refreshed = False
    if g is None or st.input_hash(conn, gid) != g["input_hash"]:
        sl.refresh_group(conn, gid)
        g = conn.execute("SELECT * FROM group_stats WHERE gid=?", (gid,)).fetchone()
        refreshed = True
    if g is None:
        raise SystemExit(f"ยังไม่มีสถิติกลุ่ม {gid} — สั่ง `python fb_stat_layer.py {gid}` ก่อน")
    stale = False
    conf = st.confidence_of(g)
    L: list[str] = []
    man: dict[str, str] = {}

    L.append(f"# ซองวิเคราะห์กลุ่ม — {g['name']} (`{gid}`)")
    L.append(f"สมาชิก {g['members']:,} · เก็บโพสต์ได้ {g['n_posts']:,} ใบ "
             f"({_thai_dt(g['first_post_at'])} – {_thai_dt(g['last_post_at'])}) "
             f"· ข้อมูลชุด `{g['input_hash']}`"
             + ("  (คำนวณสถิติใหม่ให้แล้วเพราะบอทเก็บเพิ่ม)" if refreshed else ""))
    L.append("")

    # ── 1. ด่าน: สรุปอะไรได้บ้าง ──
    L.append("## 1. ด่านตรวจก่อนสรุป (ระบบตัดสิน ไม่ใช่ผู้วิเคราะห์)")
    L.append(f"| หัวข้อ | สรุปได้ไหม | เหตุผล |")
    L.append("|---|---|---|")
    L.append(f"| (ก) แนวทาง content | {'✅ ได้' if g['ok_content'] else '❌ **ห้ามสรุป**'} | "
             f"โพสต์แมส {g['n_mass']} ใบ / ไม่แมส {g['n_normal']} ใบ "
             f"(เกณฑ์: แมส ≥{st.MIN_MASS} และรวม ≥{st.MIN_POSTS}) |")
    L.append(f"| (ข) ฐานลูกค้าจากคอมเมนต์ | {'✅ ได้' if g['ok_audience'] else '❌ **ห้ามสรุป**'} | "
             f"เก็บคอมเมนต์ได้ {g['cmt_got']:,} อัน = {g['cmt_cov_pct']}% ของที่ FB แสดง "
             f"· มีเนื้อหาจริง {g['cmt_content']:,} อัน "
             f"(เกณฑ์: เนื้อหาจริง ≥{st.MIN_CMT} และครอบคลุม ≥{int(st.MIN_CMT_COV*100)}%) |")
    L.append(f"| ระดับความเชื่อถือที่ระบบให้ | **{conf}** | คำนวณจากขนาดตัวอย่างล้วนๆ |")
    if g["block_reason"]:
        L.append("")
        L.append(f"> ⚠️ ข้อจำกัดที่ต้องเขียนไว้ในบทวิเคราะห์ด้วย: {g['block_reason']}")
    L.append("")

    # ── 2. ความน่าเชื่อถือของข้อมูลดิบ ──
    L.append("## 2. ข้อมูลดิบเชื่อได้แค่ไหน")
    L.append(f"- **ยอดแชร์: {g['shares_trust']}** — มีโพสต์ที่แชร์>0 อยู่ {g['shares_pos_pct']}% "
             + ("→ ตัวเก็บแยกไม่ออกระหว่าง 'แชร์ 0 จริง' กับ 'FB ไม่โชว์' "
                "ค่า engagement และ is_mass จึงน่าจะ**ต่ำกว่าความจริง** "
                "ทุกข้อสรุปในซองนี้จึงยืนยันซ้ำด้วยเป้าหมายที่ไม่ใช้แชร์ (ไลก์+คอมเมนต์) แล้ว"
                if g["shares_trust"] == "suspect" else "→ ใช้ได้"))
    L.append(f"- **หน้าต่างเวลา:** ครอบคลุม {g['days_covered']} วัน · {g['hours_covered']} ชั่วโมงต่างกัน "
             + ("→ ยังสรุปเรื่อง 'วันไหน/เวลาไหนดี' ไม่ได้"
                if (g["days_covered"] or 0) < 7 or (g["hours_covered"] or 0) < 18 else ""))
    conc = (g["cmt_posts_with"] or 0) / max(g["n_posts"], 1) * 100
    L.append(f"- **คอมเมนต์:** เก็บได้ {g['cmt_got']:,} จากที่ FB บอกว่ามี "
             f"{int(g['cmt_got']/max(g['cmt_cov_pct'],0.01)*100) if g['cmt_cov_pct'] else 0:,} "
             f"= {g['cmt_cov_pct']}% · กระจุกอยู่บนโพสต์แค่ {g['cmt_posts_with']} ใบ "
             f"({conc:.1f}% ของโพสต์ทั้งกลุ่ม)"
             + (" → คนที่เห็นในคอมเมนต์คือคนที่มาคุยใต้ **โพสต์ดัง** เท่านั้น "
                "ไม่ใช่ตัวแทนสมาชิกทั้งกลุ่ม ต้องเขียนข้อจำกัดนี้กำกับบทวิเคราะห์ฐานลูกค้าเสมอ"
                if conc < 10 else ""))
    L.append(f"- **ยอดวิว:** ฐานไม่มีข้อมูล (NULL ทุกแถว) — ห้ามอ้างถึง")
    L.append("")

    # ── 3. ภาพรวมตัวเลข ──
    L.append("## 3. ภาพรวมตัวเลข (คำนวณจาก SQL ทั้งหมด)")
    L.append(f"- engagement: มัธยฐาน **{g['eng_p50']}** · P75 {g['eng_p75']} · P90 {g['eng_p90']} "
             f"· P95 {g['eng_p95']} · สูงสุด {g['eng_max']:,} · ได้ศูนย์ {g['eng_zero_pct']}%")
    L.append(f"- ไลก์+คอมเมนต์อย่างเดียว: มัธยฐาน {g['core_p50']} · P90 {g['core_p90']}")
    L.append(f"- มี caption {g['cap_pct']}% (ยาวมัธยฐาน {g['cap_p50_len']} ตัวอักษร) "
             f"· มีรูป {g['img_pct']}% (มัธยฐาน {g['img_p50']} รูป)")
    L.append(f"- คนโพสต์ {g['authors_n']:,} คน · เป็นขาจร (โพสต์ใบเดียว) {g['author_once_pct']}%")
    hrs = conn.execute("SELECT hour,n,eng_p50,mass_n FROM group_hour WHERE gid=? ORDER BY hour",
                       (gid,)).fetchall()
    if hrs:
        L.append("- โพสต์ต่อชั่วโมง (เวลาไทย) — `ชม.:จำนวน/มัธยฐาน eng`: "
                 + " · ".join(f"{r['hour']:02d}:{r['n']}/{r['eng_p50']}" for r in hrs))
    L.append("")

    # ── 4. ผลทดสอบฟีเจอร์ ──
    L.append("## 4. ฟีเจอร์ที่ทดสอบแล้ว (Mann-Whitney U · แมส vs ไม่แมส)")
    L.append(f"เกณฑ์ผ่าน: p ≤ {st.P_MAX} **และ** |AUC−0.5| ≥ {st.AUC_MIN} "
             "**และ** ทิศทางไม่พลิกเมื่อตัดยอดแชร์ออก")
    L.append("")
    L.append("| ฟีเจอร์ | สถานะ | AUC | AUC(ไม่ใช้แชร์) | p | มัธยฐาน แมส/ไม่แมส |")
    L.append("|---|---|---|---|---|---|")
    feats = conn.execute("""SELECT * FROM group_feature WHERE gid=?
        ORDER BY CASE status WHEN 'pass' THEN 0 WHEN 'weak' THEN 1 WHEN 'reject' THEN 2
                             WHEN 'constant' THEN 3 ELSE 4 END, ABS(COALESCE(auc,0.5)-0.5) DESC""",
                         (gid,)).fetchall()
    icon = {"pass": "✅ ใช้ได้", "weak": "🟡 อ่อน", "reject": "❌ ไม่ต่าง",
            "constant": "⬜ เกือบคงที่", "blocked": "⛔ ห้ามใช้"}
    for f in feats:
        pv = "-" if f["p"] is None else f"{f['p']:.1g}"
        au = "-" if f["auc"] is None else f"{f['auc']:.3f}"
        ac = "-" if f["auc_core"] is None else f"{f['auc_core']:.3f}"
        L.append(f"| {f['label']} | {icon.get(f['status'], f['status'])} | {au} | {ac} | {pv} | "
                 f"{f['med_mass']:g} / {f['med_normal']:g} |")
    L.append("")
    L.append("**เหตุผลของตัวที่ไม่ผ่าน (ห้ามเอาไปเขียนเป็นข้อสรุป):**")
    for f in feats:
        if f["status"] != "pass":
            L.append(f"- {f['label']} — {f['reason']}")
    L.append("")

    passed = [f for f in feats if f["status"] == "pass"]
    if passed:
        L.append("### ตารางแบ่งช่วงของฟีเจอร์ที่ผ่านด่าน")
        for f in passed:
            bs = conn.execute("SELECT * FROM feature_bucket WHERE gid=? AND feat=? ORDER BY ord",
                              (gid, f["feat"])).fetchall()
            if not bs:
                continue
            L.append(f"\n**{f['label']}**\n")
            L.append("| ช่วง | จำนวนโพสต์ | มัธยฐาน eng | %เป็นแมส | %ได้ศูนย์ |")
            L.append("|---|---|---|---|---|")
            for b in bs:
                L.append(f"| {b['bucket']} | {b['n']} | {b['eng_p50']} | "
                         f"{b['mass_pct']}% | {b['zero_pct']}% |")
        if len(passed) >= 2:
            a, b = passed[0]["feat"], passed[1]["feat"]
            L.append(f"\n### ตัดขวาง {passed[0]['label']} × {passed[1]['label']}")
            L.append("(พิสูจน์ว่าไม่ใช่ฟีเจอร์เดียวปลอมตัวมาเป็นสองตัว — ถ้าตัดขวางแล้วยังต่างทั้งคู่ แปลว่าเป็นคนละเรื่องจริง)\n")
            L.append("| | | จำนวน | มัธยฐาน eng | %เป็นแมส |")
            L.append("|---|---|---|---|---|")
            for row in sl.cross_check(conn, gid, a, b):
                L.append(f"| {row['a']} | {row['b']} | {row['n']} | {row['eng_p50']} | "
                         f"{row['mass_pct']}% |")
        L.append("")

    # ── 5. ตัวอย่างโพสต์จริง ──
    L.append("## 5. ตัวอย่างโพสต์จริง (อ้างด้วย handle เท่านั้น)")
    tier_name = {"mass": "แมส", "near": "เกือบแมส (eng 50–100)",
                 "mid": "ธรรมดา (รอบมัธยฐาน)", "dead": "ตาย (eng 0)"}
    rows = conn.execute(SQL_SAMPLE, {"gid": gid, "n_mass": N_MASS, "n_near": N_NEAR,
                                     "n_mid": N_MID, "n_dead": N_DEAD, "cut": CAP_CUT}).fetchall()
    cur_tier, i = None, 0
    for r in rows:
        if r["tier"] != cur_tier:
            cur_tier = r["tier"]
            L.append(f"\n### {tier_name[cur_tier]}")
        i += 1
        h = f"P{i}"
        man[h] = r["post_id"]
        cap = (r["cap"] or "").strip() or "(ไม่มีข้อความ)"
        alts = f" · alt: {r['alts']}" if r["alts"] else ""
        L.append(f"- **{h}** eng {r['engagement']:,} (ไลก์ {r['reactions']}/คอม {r['comments']}"
                 f"/แชร์ {r['shares']}) · {r['images_n']} รูป · {r['hh']:02d} น. · "
                 f"คนโพสต์นี้มี {r['author_n']} ใบในกลุ่ม\n  «{cap}»{alts}")
    L.append("")

    # ── 6. คอมเมนต์ ──
    L.append("## 6. คอมเมนต์ (ล้างชื่อที่แท็กออกแล้ว)")
    roles = conn.execute(SQL_CMT_ROLES, {"gid": gid}).fetchall()
    if roles:
        L.append("| บทบาทที่กฎตีให้ | จำนวน | ที่เป็นแท็กล้วน | ที่ข้อมูลน้อย |")
        L.append("|---|---|---|---|")
        for r in roles:
            L.append(f"| {r['role']} | {r['n']} | {r['tagonly']} | {r['lowinfo']} |")
    if not g["ok_audience"]:
        L.append("\n> ❌ **กลุ่มนี้ยังสรุปฐานลูกค้าไม่ได้** ตัวอย่างข้างล่างให้ดูเป็นบรรยากาศเท่านั้น "
                 "ห้ามเขียนข้อสรุปเรื่องฐานลูกค้าลงไป")
    L.append("")
    cs = conn.execute(SQL_CMT, {"gid": gid, "n": N_CMT}).fetchall()
    for j, c in enumerate(cs, 1):
        h = f"C{j}"
        man[h] = c["comment_id"]
        L.append(f"- **{h}** [{c['role']}] ♥{c['likes']} (บนโพสต์ eng {c['post_eng']}) "
                 f"«{c['body_clean'][:160]}»")
    if not cs:
        L.append("- (ไม่มีคอมเมนต์ที่ผ่านการล้าง — ทั้งหมดเป็นแท็กเพื่อน/ขานรับ/ว่าง)")
    L.append("")

    # ── 7. สิ่งที่ต้องเขียนกลับ ──
    L.append("## 7. สิ่งที่ต้องตอบกลับ (บันทึกเข้าฐานได้เลย)")
    L.append("ตอบเป็น JSON ตามนี้ แล้วสั่ง `python fb_stat_brief.py --apply " + gid + " ไฟล์.json`")
    L.append("")
    L.append("```json")
    L.append(json.dumps({
        "verdict": "สรุป 1 บรรทัดว่ากลุ่มนี้เนื้อหาแบบไหนไปได้",
        "do_md": "- ข้อควรทำ (อ้าง handle เช่น P1, P3 ได้)",
        "dont_md": "- ข้อไม่ควรทำ",
        "audience_md": "" if not g["ok_audience"] else "- ฐานลูกค้าเป็นใคร (อ้าง C1, C2)",
        "caveats_md": "- ข้อจำกัดที่ผู้อ่านต้องรู้",
        "evidence": [{"section": "do", "kind": "post", "handle": "P1", "note": "ทำไมใบนี้"}],
    }, ensure_ascii=False, indent=2))
    L.append("```")
    L.append("")
    L.append("กติกาที่ระบบบังคับตอนบันทึก (ผิดข้อไหนจะไม่ยอมเขียนลงฐาน):")
    L.append(f"1. ห้ามใส่ตัวเลขที่ไม่มีในซองนี้ — ตัวเลขทุกตัวมาจาก SQL แล้ว")
    L.append(f"2. อ้างหลักฐานได้เฉพาะ handle ที่มีในซอง ({len(man)} ตัว) — ระบบแปลงกลับเป็น id จริงและตรวจว่ามีอยู่จริง")
    L.append(f"3. ห้ามเขียนข้อสรุปจากฟีเจอร์ที่สถานะไม่ใช่ ✅ — ตัวที่ ⛔ ห้ามใช้เพราะเป็น artifact ของตัวเก็บ")
    if not g["ok_content"]:
        L.append("4. ⛔ กลุ่มนี้ **ตัวอย่างไม่พอ** — ให้ตอบว่าสรุปไม่ได้ พร้อมบอกว่าต้องเก็บเพิ่มอีกเท่าไร ห้ามเดาให้ดูดี")
    if not g["ok_audience"]:
        L.append("5. ⛔ ห้ามกรอก audience_md (ระบบจะปฏิเสธ)")

    body = "\n".join(L)
    BRIEF_DIR.mkdir(parents=True, exist_ok=True)
    path = BRIEF_DIR / f"{gid}.md"
    path.write_text(body, encoding="utf-8")
    (BRIEF_DIR / f"{gid}.manifest.json").write_text(
        json.dumps(man, ensure_ascii=False, indent=1), encoding="utf-8")
    conn.execute("""INSERT INTO brief_export (gid,created_at,input_hash,n_chars,
                    n_tokens_est,path,manifest) VALUES (?,?,?,?,?,?,?)""",
                 (gid, int(time.time()), g["input_hash"], len(body), len(body) // 2,
                  str(path), json.dumps(man, ensure_ascii=False)))
    conn.commit()
    conn.close()
    return body, man


def apply_json(gid: str, jf: str) -> int:
    """แปลง handle → id จริง แล้วเขียนกลับ (ระบบตรวจซ้ำอีกชั้นใน save_analysis)"""
    man = json.loads((BRIEF_DIR / f"{gid}.manifest.json").read_text(encoding="utf-8"))
    payload = json.loads(Path(jf).read_text(encoding="utf-8"))
    ev = []
    for e in payload.get("evidence", []):
        h = e.get("handle", "")
        if h not in man:
            raise SystemExit(f"handle {h!r} ไม่มีในซองของกลุ่มนี้ — อ้างหลักฐานลอยไม่ได้")
        ev.append({"section": e.get("section", "do"),
                   "kind": "post" if h.startswith("P") else "comment",
                   "ref_id": man[h], "note": e.get("note", "")})
    payload["evidence"] = ev
    return st.save_analysis(gid, payload)


def main() -> int:
    if len(sys.argv) > 3 and sys.argv[1] == "--apply":
        print(f"บันทึกแล้ว rev={apply_json(sys.argv[2], sys.argv[3])}")
        return 0
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    body, man = build(sys.argv[1])
    print(body)
    print(f"\n---\n[ขนาดซอง] {len(body):,} ตัวอักษร ≈ {len(body)//2:,} โทเคน "
          f"· handle {len(man)} ตัว", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
