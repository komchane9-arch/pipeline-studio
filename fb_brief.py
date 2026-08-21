"""สร้าง "ซองข้อมูล" ต่อกลุ่ม สำหรับให้ Claude ในแชทวิเคราะห์ (ไม่เรียก API)

วิธีใช้:
  python fb_brief.py --list                       # ดูว่ากลุ่มไหนพร้อมวิเคราะห์
  python fb_brief.py --group "รีวิวโลตัส"          # พิมพ์ซองออกจอ + บันทึกลงฐาน
  python fb_brief.py --gid reviewlotus --out b.md  # เขียนลงไฟล์ไว้ก๊อปวางในแชท

สิ่งที่ยึดในการออกแบบซอง:
  * ทุกตัวอย่างมี "รหัสหลักฐาน" P1/P2/C1 ติดหัว — Claude ต้องอ้างรหัสเหล่านี้
    ทุกข้อสรุป ระบบถึงจะรับเข้าฐาน (ตัวเลข id จริงยาวและ LLM ลอกผิดง่าย
    จึงใช้รหัสสั้นแล้วให้ระบบแปลงกลับเองจาก manifest)
  * ตัวเลขทั้งหมดคำนวณด้วย SQL มาแล้ว — ในซองไม่มีอะไรให้ต้องนับเอง
  * มีทั้งฝั่งชนะและฝั่งแพ้ + "โพสต์ที่เข้าสูตรแต่ไม่แมส" เป็นตัวถ่วง
  * บอกข้อจำกัดข้อมูลไว้บนหัวซอง และปิดหมวดที่ข้อมูลไม่พอ (ปิดจริง)
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fb_analysis_sql as q          # noqa: E402
import fb_analysis_store as st       # noqa: E402

CAP_CUT = 220        # ตัด caption ในซองที่กี่ตัวอักษร
COMMENT_CUT = 140


def _fmt_ts(ts: int | None) -> str:
    return datetime.fromtimestamp(ts).strftime("%d/%m/%y %H:%M") if ts else "-"


def _short(s: str | None, n: int) -> str:
    s = (s or "").replace("\n", " ⏎ ").strip()
    return s if len(s) <= n else s[:n] + "…"


def build(conn, gid: str, limit_mass: int = 30, limit_normal: int = 25,
          limit_comment: int = 40) -> dict:
    """สร้างซอง — คืน dict {body, manifest, gates, stat...}"""
    g = conn.execute("SELECT * FROM fb_group WHERE gid=?", (gid,)).fetchone()
    gname = g["name"] if g else gid
    members = g["members"] if g else None
    s = dict(conn.execute(q.GROUP_STAT_SQL, {"gid": gid}).fetchone())
    ql = dict(conn.execute(q.GROUP_QUALITY_SQL, {"gid": gid}).fetchone())
    if not s["n_post"]:
        raise SystemExit(f"กลุ่ม {gid} ยังไม่มีโพสต์ในฐาน — สร้างซองไม่ได้")

    man: dict[str, str] = {}
    L: list[str] = []
    A = L.append

    # ---------------------------------------------------------- หัวซอง
    A(f"# ซองวิเคราะห์กลุ่ม: {gname}")
    A(f"`gid={gid}` · สมาชิก {members or '-'} · สร้างซอง {_fmt_ts(int(time.time()))}")
    A("")
    A("## 0. ข้อมูลชุดนี้เชื่อได้แค่ไหน (อ่านก่อนสรุปอะไร)")
    A(f"- โพสต์ในฐาน **{s['n_post']}** ใบ · โพสต์แมส (eng>100) **{s['n_mass']}** ใบ "
      f"· eng=0 {s['n_zero']} ใบ · ผู้โพสต์ {s['n_author']} คน")
    A(f"- engagement: มัธยฐาน **{s['eng_p50']}** · P75 {s['eng_p75']} · P90 {s['eng_p90']} "
      f"· P95 {s['eng_p95']} · สูงสุด {s['eng_max']}")
    A(f"- ช่วงเวลาโพสต์ที่เก็บได้: {_fmt_ts(s['first_post_at'])} → {_fmt_ts(s['last_post_at'])} "
      f"({ql['n_days']} วัน · ชั่วโมง {ql['hour_min']}–{ql['hour_max']} น.)")
    if ql["n_days"] < 7 or (ql["hour_max"] - ql["hour_min"]) < 20:
        A(f"  - ⚠️ หน้าต่างเก็บแคบ — **ห้ามสรุปเรื่อง 'วันไหนดี'** และสรุปเรื่องเวลา "
          f"ได้ไม่เกินช่วง {ql['hour_min']}–{ql['hour_max']} น.")
    A(f"- caption ไม่ว่าง {s['n_caption']}/{s['n_post']} · มีรูป {s['n_image']}/{s['n_post']}")
    A(f"- ⚠️ **แชร์เป็น 0 อยู่ {ql['pct_share_zero']}% ของโพสต์** และไม่มีแถวไหนเป็น NULL เลย "
      f"— ตัวเก็บบันทึก 'อ่านไม่ได้' เป็น 0 แยกไม่ออกจาก 'ไม่มีแชร์จริง' "
      f"→ engagement ของบางใบต่ำกว่าความจริง ห้ามสรุปว่า 'โพสต์แนวนี้ไม่มีคนแชร์'")
    A(f"- คอมเมนต์: FB บอกว่ามีรวม {s['comments_on_fb']} · เก็บลงฐานได้ {s['comments_stored']} "
      f"(**{ql['pct_comment_cov'] or 0}%**) จากโพสต์ {ql['n_post_with_cm']} ใบ "
      f"· ยังไม่ได้เก็บอีก {ql['n_post_cm_pending']} ใบ")
    A("- ค่าที่ยังใช้ไม่ได้ทั้งฐาน: `views` (NULL ทุกแถว) · `spam_score` (0 ทุกแถว) "
      "· `depth` ของคอมเมนต์ (0 ทุกแถว = ไม่มีเธรดตอบกลับ) "
      "· `fb_comment.author_url` (เก็บ URL โพสต์ ไม่ใช่โปรไฟล์ → ตามตัวคนไม่ได้)")
    A("")

    # ---------------------------------------------------------- ตารางเทียบ
    A("## 1. ตารางเทียบตามฟีเจอร์ (คำนวณด้วย SQL แล้ว — ห้ามนับเอง)")
    A("| มิติ | แถบ | n | มัธยฐาน eng | %แมส | %eng=0 | ตัวอย่างสูงสุด |")
    A("|---|---|---|---|---|---|---|")
    ex_pool: list[tuple[str, str]] = []
    for r in conn.execute(q.CONTRAST_SQL, {"gid": gid, "min_n": 5}):
        ids = [x for x in (r["ex_post_ids"] or "").split(",") if x][:2]
        hs = []
        for pid in ids:
            ex_pool.append((r["band"], pid))
            hs.append(pid)
        A(f"| {r['dim'][2:]} | {r['band']} | {r['n']} | {r['med_eng']} | "
          f"{r['pct_mass']}% | {r['pct_zero']}% | {' '.join('#' + x[-6:] for x in hs)} |")
    A("")
    A("> แถบที่ n < 5 ถูกตัดออกจากตาราง (เล็กเกินกว่าจะแปลผล)")
    A("")

    # ---------------------------------------------------------- ตัวอย่างโพสต์แมส
    mass = conn.execute(q.SAMPLE_MASS_SQL, {"gid": gid, "limit": limit_mass}).fetchall()
    A(f"## 2. โพสต์แมสจริง ({len(mass)} ใบ จากทั้งหมด {s['n_mass']} ใบ)")
    if not mass:
        A("**ไม่มีโพสต์แมสเลยในกลุ่มนี้** — ห้ามเขียนสูตร 'ทำแบบนี้แล้วแมส' "
          "ให้เขียนได้แค่ว่าอะไรที่ทำแล้วยังไม่เวิร์กในกลุ่มนี้")
    for i, r in enumerate(mass, 1):
        h = f"P{i}"
        man[h] = r["post_id"]
        A(f"- **[{h}]** eng={r['engagement']} (ไลก์ {r['reactions']}/คอม {r['comments']}"
          f"/แชร์ {r['shares']}) · {_fmt_ts(r['posted_at'])} · รูป {r['images_n']} "
          f"· ผู้โพสต์โพสต์ในกลุ่มนี้ {r['author_posts']} ใบ")
        A(f"  - caption: {_short(r['caption'], CAP_CUT) or '(ไม่มี)'}")
        if r["first_alt"]:
            A(f"  - รูป(alt จาก FB): {_short(r['first_alt'], 120)}")
    A("")

    # ---------------------------------------------------------- ตัวอย่างโพสต์ไม่แมส
    n0 = len(man)
    norm = conn.execute(q.SAMPLE_NORMAL_SQL, {"gid": gid, "limit": limit_normal}).fetchall()
    A(f"## 3. โพสต์ไม่แมส (สุ่มแบบคงที่ {len(norm)} ใบ จาก {s['n_post'] - s['n_mass']} ใบ)")
    for i, r in enumerate(norm, 1):
        h = f"P{n0 + i}"
        man[h] = r["post_id"]
        A(f"- **[{h}]** eng={r['engagement']} · รูป {r['images_n']} "
          f"· ผู้โพสต์ {r['author_posts']} ใบ · {_short(r['caption'], 120) or '(ไม่มี caption)'}")
    A("")

    # ---------------------------------------------------------- ตัวถ่วง
    n0 = len(man)
    cnt = conn.execute(q.SAMPLE_COUNTER_SQL, {"gid": gid, "limit": 6}).fetchall()
    if cnt:
        A("## 4. โพสต์ที่ 'เข้าสูตร' แต่ไม่แมส (caption ยาว + รูป 5+) — ตัวถ่วงกันสรุปเกินจริง")
        for i, r in enumerate(cnt, 1):
            h = f"P{n0 + i}"
            man[h] = r["post_id"]
            A(f"- **[{h}]** eng={r['engagement']} · {r['caption_len']} ตัวอักษร "
              f"· รูป {r['images_n']} · {_short(r['caption'], 120)}")
        A("")

    # ---------------------------------------------------------- คอมเมนต์
    roles = conn.execute(q.CUSTOMER_SQL, {"gid": gid}).fetchall()
    n_comment = sum(r["n"] for r in roles)
    usable = [r for r in roles if r["role"] in ("ลูกค้า", "คนขาย", "คุยเล่น")]
    n_usable = sum(r["n"] for r in usable)
    aud_state, why_aud = st.audience_gate(n_usable, ql["pct_comment_cov"],
                                          ql["n_post_with_cm"])
    A("## 5. คอมเมนต์ / ฐานลูกค้า")
    A(f"- คอมเมนต์ในฐานของกลุ่มนี้ **{n_comment}** อัน · ใช้วิเคราะห์ได้จริง **{n_usable}** อัน "
      f"· มาจากโพสต์ {ql['n_post_with_cm']} ใบ (จาก {s['n_post']} ใบ)")
    if roles:
        A("| บทบาท (ตีด้วยกฎ) | n | % | อยู่บนโพสต์แมส | ยาวเฉลี่ย |")
        A("|---|---|---|---|---|")
        for r in roles:
            A(f"| {r['role']} | {r['n']} | {r['pct']}% | {r['n_on_mass']} | {r['avg_len']} |")
    A(f"- สถานะหมวดฐานลูกค้า: **{ {'open':'เปิด','limited':'เปิดแบบจำกัด','closed':'ปิด'}[aud_state] }** "
      f"— {why_aud}")
    A("")
    if aud_state != "closed":
        n0 = len(man)
        cs = conn.execute(q.CUSTOMER_SAMPLE_SQL,
                          {"gid": gid, "min_len": 8, "limit": limit_comment, "per_role": 25}).fetchall()
        A(f"### ตัวอย่างคอมเมนต์ที่มีเนื้อความ ({len(cs)} อัน — ตัดแท็กเพื่อน/สแปม/ว่าง/สติกเกอร์ออกแล้ว "
          f"· เรียงจากยาวไปสั้นในแต่ละบทบาท ไม่ใช่การสุ่ม)")
        for i, r in enumerate(cs, 1):
            h = f"C{i}"
            man[h] = r["comment_id"]
            A(f"- **[{h}]** ({r['role']}) {_short(r['txt'], COMMENT_CUT)}")
        A("")
        if aud_state == "limited":
            A("> ⚠️ คอมเมนต์ชุดนี้กระจุกอยู่บนโพสต์ไม่กี่ใบ — เขียนหมวด `audience` ได้ "
              "แต่ต้องเขียนว่าเป็นเสียงจากโพสต์ไหน ห้ามเขียนว่า 'ลูกค้าของกลุ่มนี้คือ...' ลอยๆ")
            A("")
    else:
        A("> ⚠️ ห้ามเขียนหมวด `audience` ในคำตอบ — ระบบจะปฏิเสธทั้งรอบ")
        A("")

    # ---------------------------------------------------------- วิธีตอบ
    gates = {"audience_state": aud_state, "audience_why": why_aud,
             "n_comment_usable": n_usable, "n_comment": n_comment,
             "n_post_with_cm": ql["n_post_with_cm"]}
    conf, conf_why = st.confidence_of(s["n_post"], s["n_mass"], n_usable)
    A("## 6. กติกาการตอบ (ระบบตรวจจริง ผิดกติกาจะไม่ถูกบันทึก)")
    A(f"- ระดับความเชื่อถือที่ระบบคำนวณไว้แล้ว: **{conf}** — {conf_why} "
      f"(ห้ามกรอกเอง ระบบเติมให้)")
    A("- ตอบเป็น JSON ก้อนเดียวตามรูปนี้ แล้วบันทึกเป็นไฟล์ให้ผู้ใช้รัน "
      "`python fb_analysis_apply.py --brief <hash> --json <ไฟล์>`")
    A("```json")
    A(json.dumps({
        "brief_hash": "<เติมค่าท้ายซอง>",
        "claims": [
            {"section": "do", "headline": "หัวข้อสั้น 1 บรรทัด",
             "detail": "อธิบาย 1-3 ประโยค อ้างของที่เห็นในซองเท่านั้น",
             "metric_key": "1_ความยาว caption|ยาว 81-160",
             "evidence": ["P1", "P4"]},
            {"section": "dont", "headline": "...", "detail": "...", "evidence": ["P31"]},
            {"section": "audience", "headline": "...", "detail": "...", "evidence": ["C2"]},
        ]}, ensure_ascii=False, indent=1))
    A("```")
    A("- `section` ใช้ได้แค่: `do` (ควรทำ) · `dont` (ควรเลี่ยง) · `audience` (ฐานลูกค้า) "
      "· `timing` (เวลา) · `warning` (ข้อควรระวัง/สิ่งที่ยังสรุปไม่ได้)")
    A("- **ทุก claim ต้องมี `evidence` อย่างน้อย 1 รหัส** และรหัสต้องมาจากซองนี้ "
      "ไม่งั้นระบบปฏิเสธทั้งรอบ (ไม่บันทึกครึ่งๆ)")
    A("- **ห้ามใส่ตัวเลขที่คิดเอง** ในคำตอบ — ถ้าจะอ้างตัวเลข ให้ชี้ด้วย `metric_key` "
      "ในรูป `มิติ|แถบ` ตามตารางข้อ 1 แล้วระบบจะดึงตัวเลขจริงมาแสดงเอง")
    A("- ถ้าข้อมูลไม่พอจะสรุปอะไร ให้เขียนเป็น `warning` ตรงๆ ดีกว่าเดาให้ดูดี")
    A("")

    body = "\n".join(L)
    h = st.brief_hash(body)
    body += f"\n<!-- brief_hash={h} -->\nรหัสซอง (brief_hash) สำหรับตอนบันทึกผล: **{h[:12]}**\n"
    return {"gid": gid, "body": body, "manifest": man, "gates": gates,
            "hash": st.brief_hash(body), "stat": s, "quality": ql,
            "n_mass_sample": len(mass), "n_normal_sample": len(norm),
            "n_comment": n_comment, "confidence": conf}


def save(conn, b: dict) -> int:
    """บันทึกซองลงฐาน — ซองเดิม (hash เดิม) ไม่สร้างซ้ำ"""
    row = conn.execute("SELECT brief_id FROM analysis_brief WHERE brief_hash=?",
                       (b["hash"],)).fetchone()
    if row:
        return row["brief_id"]
    cur = conn.execute("""INSERT INTO analysis_brief
        (gid, brief_hash, input_sig, n_post, n_mass, n_normal, n_comment,
         chars, manifest, body, gates) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                       (b["gid"], b["hash"], st.input_sig(conn, b["gid"]),
                        b["stat"]["n_post"], b["stat"]["n_mass"],
                        b["n_normal_sample"], b["n_comment"], len(b["body"]),
                        json.dumps(b["manifest"], ensure_ascii=False),
                        b["body"], json.dumps(b["gates"], ensure_ascii=False)))
    conn.commit()
    return cur.lastrowid


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(st.DB_FILE))
    ap.add_argument("--gid")
    ap.add_argument("--group", help="ค้นจากชื่อกลุ่มบางส่วน")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--out")
    ap.add_argument("--limit-mass", type=int, default=30)
    ap.add_argument("--limit-normal", type=int, default=25)
    ap.add_argument("--no-save", action="store_true")
    a = ap.parse_args()

    conn = st.connect(a.db)
    st.ensure_schema(conn)

    if a.list:
        print(f"{'gid':<20} {'โพสต์':>6} {'แมส':>5} {'คอมเมนต์':>8}  ชื่อกลุ่ม")
        for r in conn.execute("""
            SELECT g.gid, g.name, COUNT(p.post_id) n, COALESCE(SUM(p.is_mass),0) m,
                   (SELECT COUNT(*) FROM fb_comment c JOIN fb_post p2
                     ON p2.post_id=c.post_id WHERE p2.gid=g.gid) cm
            FROM fb_group g LEFT JOIN fb_post p ON p.gid=g.gid
            GROUP BY g.gid HAVING n>0 ORDER BY n DESC"""):
            print(f"{r['gid']:<20} {r['n']:>6} {r['m']:>5} {r['cm']:>8}  {r['name']}")
        return

    gid = a.gid
    if not gid and a.group:
        r = conn.execute("SELECT gid,name FROM fb_group WHERE name LIKE ? "
                         "ORDER BY posts_seen DESC LIMIT 1", (f"%{a.group}%",)).fetchone()
        if not r:
            raise SystemExit(f"ไม่พบกลุ่มที่ชื่อมี '{a.group}'")
        gid = r["gid"]
    if not gid:
        raise SystemExit("ต้องระบุ --gid หรือ --group (หรือ --list ดูรายการ)")

    st.enrich_comments(conn, gid)          # ล้างคอมเมนต์ก่อนเสมอ
    b = build(conn, gid, a.limit_mass, a.limit_normal)
    if not a.no_save:
        bid = save(conn, b)
        print(f"[บันทึกซองแล้ว] brief_id={bid} hash={b['hash'][:12]}", file=sys.stderr)
    print(f"[ขนาดซอง] {len(b['body']):,} ตัวอักษร ≈ {len(b['body'])//3:,}-"
          f"{len(b['body'])//2:,} โทเคน · หลักฐาน {len(b['manifest'])} ชิ้น",
          file=sys.stderr)
    if a.out:
        Path(a.out).write_text(b["body"], encoding="utf-8")
        print(f"[เขียนไฟล์] {a.out}", file=sys.stderr)
    else:
        print(b["body"])


if __name__ == "__main__":
    main()
