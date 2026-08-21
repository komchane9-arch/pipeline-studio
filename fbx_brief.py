"""สร้าง "ซองข้อมูล" ต่อกลุ่ม ให้ Claude อีกแชทอ่านแล้ววิเคราะห์

ทำไมต้องมีซอง ไม่ส่งฐานข้อมูลไปทั้งก้อน:
  ฐานมี 2,126 โพสต์ · 56,040 คอมเมนต์ อ่านหมดไม่ไหวและไม่จำเป็น
  สิ่งที่ AI ทำได้ดีกว่า SQL คือ "อ่านเนื้อหาแล้วบอกว่าทำไมโพสต์นี้ปัง"
  ส่วนการนับ/เทียบ/ตัดตัวแปรกวน SQL ทำได้แม่นกว่าและถูกกว่า → ทำให้เสร็จก่อนใส่ซอง

หลักการที่ซองนี้บังคับ (มาจากสเปค ultracode 19 ส.ค.):
  1. คุมอายุโพสต์เสมอ — ข้อมูลจริงพิสูจน์ว่าโพสต์เกิน 1 ปีเป็นแมส 65% แต่โพสต์
     วันนี้เป็นแค่ 4% ถ้าไม่คุมจะสรุปผิดว่า "โพสต์แนวเก่าดีกว่า"
  2. ให้ "คู่เทียบ" ไม่ใช่ list โพสต์ปัง — คู่ที่เหมือนกันทุกอย่างยกเว้นผลลัพธ์
     คือของที่อ่านแล้วรู้เหตุผลทันที
  3. คอมเมนต์ต้องล้างก่อน — 49% เป็นแท็กชื่อเพื่อนล้วน ใส่ไปก็เปลืองที่เปล่า
  4. แนบ "เมนูตัวเลข" (metric catalog) ให้อ้างอิง — ผู้วิเคราะห์ห้ามพิมพ์ตัวเลขเอง

รัน:  python fbx_brief.py --gid <gid> [--out <โฟลเดอร์>]
      python fbx_brief.py --list
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

import fb_mass_finder as mf

DB_FILE = mf.DATA_DIR / "fb_posts.db"
OUT_DIR = Path(r"G:\My Drive\pipeline studio\Post\1.Group facebook")

MASS_MIN = 100          # เกณฑ์ "โพสต์แมส" ของผู้ใช้ — engagement เกิน 100
GATE_FULL = 30          # แมสกี่ใบขึ้นไปถึงวิเคราะห์เต็มได้
GATE_WEAK = 8           # ต่ำกว่านี้ = บอกตรงๆ ว่าสรุปไม่ได้
N_PAIRS = 12            # คู่เทียบกี่คู่
N_TOP = 8               # ตัวอย่างโพสต์แมสกี่ใบ
N_COMMENTS = 40         # คอมเมนต์ที่ใช้ได้กี่อัน

# คอมเมนต์ที่เป็น "แท็กชื่อเพื่อน" ล้วน — ไม่มีประโยคจริง มีแต่ชื่อคน
_WORD = re.compile(r"[ก-๙a-zA-Z]{3,}")
_SIGNAL = re.compile(r"[?？]|เท่าไร|เท่าไหร่|ราคา|กี่บาท|กี่ตร|สนใจ|ขายไหม|ซื้อที่ไหน"
                     r"|อยู่ไหน|ยังไง|แนะนำ|รีวิว|ใช้ดีไหม|คุ้มไหม|ที่ไหน")


def is_tag_only(text: str) -> bool:
    """ข้อความที่เป็นแค่การแท็กเพื่อน — ตัดออกก่อนวิเคราะห์ฐานลูกค้า

    ลักษณะ: สั้น · ไม่มีคำถาม/สัญญาณซื้อ · คำส่วนใหญ่เป็นชื่อคน (ขึ้นต้นตัวใหญ่
    หรือคำไทยล้วนที่ไม่ประกอบเป็นประโยค) — ใช้เกณฑ์หยาบแต่วัดผลได้จริง
    """
    body = (text or "").strip()
    if not body:
        return True
    if _SIGNAL.search(body):
        return False
    words = _WORD.findall(body)
    if len(words) >= 8:                       # ยาวพอจะเป็นประโยคจริง
        return False
    return len(body) < 80 and len(words) <= 7


def age_band(seconds: int | None) -> str:
    if not seconds:
        return "ไม่รู้อายุ"
    days = seconds / 86400
    if days < 1:
        return "A ไม่ถึง 1 วัน"
    if days < 7:
        return "B 1-7 วัน"
    if days < 30:
        return "C 7-30 วัน"
    if days < 365:
        return "D 1-12 เดือน"
    return "E เกิน 1 ปี"


def cap_band(n: int) -> str:
    if not n:
        return "ไม่มีข้อความ"
    if n <= 40:
        return "สั้น ≤40"
    if n <= 120:
        return "กลาง 41-120"
    if n <= 300:
        return "ยาว 121-300"
    return "ยาวมาก >300"


def img_band(n: int) -> str:
    return {0: "ไม่มีรูป", 1: "1 รูป"}.get(n, "2+ รูป")


def hour_band(ts: int | None) -> str:
    if not ts:
        return "ไม่รู้เวลา"
    h = datetime.fromtimestamp(ts).hour
    for lo, hi, name in ((5, 9, "เช้า 05-08"), (9, 12, "สาย 09-11"),
                         (12, 14, "เที่ยง 12-13"), (14, 17, "บ่าย 14-16"),
                         (17, 20, "เย็น 17-19"), (20, 23, "ค่ำ 20-22")):
        if lo <= h < hi:
            return name
    return "ดึก 23-04"


def load_posts(conn: sqlite3.Connection, gid: str) -> list[dict]:
    rows = conn.execute("""
        SELECT post_id, url, author, posted_at, collected_at, caption, caption_len,
               images_n, reactions, comments, shares, engagement, is_mass,
               comments_got
        FROM fb_post WHERE gid=?""", (gid,)).fetchall()
    posts = []
    for r in rows:
        age = (r["collected_at"] - r["posted_at"]) if r["posted_at"] else None
        posts.append({
            **dict(r),
            "age_band": age_band(age),
            "cap_band": cap_band(r["caption_len"] or 0),
            "img_band": img_band(r["images_n"] or 0),
            "hour_band": hour_band(r["posted_at"]),
        })
    return posts


def build_pairs(posts: list[dict], limit: int) -> list[tuple[dict, dict]]:
    """จับคู่โพสต์แมส ↔ โพสต์เงียบ ที่ "เหมือนกันทุกอย่างยกเว้นผล"

    คุม: กลุ่มเดียวกัน (อยู่แล้ว) · ช่วงอายุเดียวกัน · ความยาว caption ช่วงเดียวกัน
         · จำนวนรูปช่วงเดียวกัน — เหลือความต่างที่ "เนื้อหา" ซึ่งเป็นงานของ AI
    ใช้แต่ละใบได้ครั้งเดียว (ไม่งั้นใบเดียวจะไปโผล่ทุกคู่จนอ่านแล้วเข้าใจผิด)
    """
    key = lambda p: (p["age_band"], p["cap_band"], p["img_band"])
    mass = sorted((p for p in posts if p["is_mass"] and p["caption_len"]),
                  key=lambda p: -p["engagement"])
    quiet = [p for p in posts if not p["is_mass"] and p["caption_len"]]
    used: set = set()
    pairs = []
    for hi in mass:
        if len(pairs) >= limit:
            break
        for lo in quiet:
            if lo["post_id"] in used or key(lo) != key(hi):
                continue
            if lo["engagement"] > 20:          # ต้องเงียบจริง ไม่ใช่กลางๆ
                continue
            used.add(lo["post_id"])
            pairs.append((hi, lo))
            break
    return pairs


def contrast(posts: list[dict], dim: str) -> list[dict]:
    """เทียบ "สัดส่วนการเป็นแมส" ของแต่ละแถบในมิติหนึ่ง — คุมอายุด้วย

    คิดแยกในแต่ละช่วงอายุแล้วรวมถ่วงน้ำหนัก เพื่อไม่ให้ช่วงอายุที่มีโพสต์เยอะ
    ลากผลทั้งมิติ (โพสต์เก่าเป็นแมสง่ายกว่ามาก — ต่างกัน 16 เท่า)
    """
    из: dict = {}
    for p in posts:
        if p["age_band"] == "ไม่รู้อายุ":
            continue
        slot = из.setdefault((p[dim], p["age_band"]), [0, 0])
        slot[0] += 1
        slot[1] += 1 if p["is_mass"] else 0
    bands: dict = {}
    for (band, age), (n, mass) in из.items():
        b = bands.setdefault(band, {"n": 0, "mass": 0, "ages": set()})
        b["n"] += n
        b["mass"] += mass
        b["ages"].add(age)
    out = []
    for band, b in bands.items():
        if b["n"] < 15:                        # น้อยเกินไป ไม่เอาไปสรุป
            continue
        out.append({"band": band, "n": b["n"], "mass": b["mass"],
                    "pct": round(b["mass"] * 100 / b["n"], 1),
                    "ages": len(b["ages"])})
    out.sort(key=lambda x: -x["pct"])
    return out


def load_comments(conn: sqlite3.Connection, gid: str, limit: int) -> dict:
    rows = conn.execute("""
        SELECT c.comment_id, c.post_id, c.author, c.body, c.likes, c.is_spam,
               p.is_mass, p.engagement
        FROM fb_comment c JOIN fb_post p ON p.post_id=c.post_id
        WHERE p.gid=? AND c.body != ''""", (gid,)).fetchall()
    total = len(rows)
    spam = sum(1 for r in rows if r["is_spam"])
    tag = sum(1 for r in rows if is_tag_only(r["body"]))
    usable = [r for r in rows if not r["is_spam"] and not is_tag_only(r["body"])]
    signal = [r for r in usable if _SIGNAL.search(r["body"] or "")]
    # เอาคอมเมนต์ที่มีสัญญาณซื้อก่อน แล้วเติมด้วยตัวที่ไลค์เยอะ (คนอื่นเห็นด้วย)
    signal.sort(key=lambda r: -(r["likes"] or 0))
    rest = sorted((r for r in usable if r not in signal),
                  key=lambda r: -(r["likes"] or 0))
    picked = signal[:limit * 2 // 3] + rest[:limit - len(signal[:limit * 2 // 3])]
    return {"total": total, "spam": spam, "tag_only": tag,
            "usable": len(usable), "signal": len(signal), "picked": picked}


def fmt_post(p: dict, tag: str) -> str:
    cap = (p["caption"] or "").strip().replace("\n", " ⏎ ")
    if len(cap) > 220:
        cap = cap[:220] + "…"
    when = (datetime.fromtimestamp(p["posted_at"]).strftime("%d/%m/%Y %H:%M")
            if p["posted_at"] else "?")
    return (f"[{tag}] eng {p['engagement']:,} "
            f"(👍{p['reactions'] or 0:,} 💬{p['comments'] or 0:,} ↗{p['shares'] or 0:,}) "
            f"· {when} · {p['img_band']} · {p['cap_band']}\n"
            f"      «{cap or '(ไม่มีข้อความ)'}»")


def build(gid: str, out_dir: Path) -> Path:
    conn = sqlite3.connect(f"file:{DB_FILE}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    g = conn.execute("SELECT * FROM fb_group WHERE gid=?", (gid,)).fetchone()
    if g is None:
        raise SystemExit(f"ไม่พบกลุ่ม {gid}")
    posts = load_posts(conn, gid)
    if not posts:
        raise SystemExit(f"กลุ่ม {gid} ยังไม่มีโพสต์ในฐาน")
    mass_n = sum(1 for p in posts if p["is_mass"])
    gate = ("เต็ม" if mass_n >= GATE_FULL else
            "จำกัด" if mass_n >= GATE_WEAK else "ไม่พอ")

    pairs = build_pairs(posts, N_PAIRS)
    tops = sorted((p for p in posts if p["is_mass"]),
                  key=lambda p: -p["engagement"])[:N_TOP]
    cm = load_comments(conn, gid, N_COMMENTS)

    # เมนูตัวเลขที่ผู้วิเคราะห์อ้างได้ (ห้ามพิมพ์ตัวเลขเอง)
    metrics: dict = {}
    dims = [("img_band", "รูป"), ("cap_band", "ความยาว"),
            ("hour_band", "เวลาโพสต์"), ("age_band", "อายุ")]
    catalog_lines = []
    for dim, label in dims:
        rows = contrast(posts, dim)
        if not rows:
            continue
        catalog_lines.append(f"\n**{label}**")
        for r in rows:
            key = f"{dim}|{r['band']}"
            metrics[key] = {"pct_mass": r["pct"], "n": r["n"], "mass": r["mass"]}
            catalog_lines.append(
                f"  - `{key}` → เป็นแมส {r['pct']}% ({r['mass']} จาก {r['n']} โพสต์)")

    manifest = {}
    lines: list[str] = []
    A = lines.append
    A(f"# ซองวิเคราะห์กลุ่ม: {g['name']}")
    A("")
    A(f"- **gid**: `{gid}`")
    A(f"- สมาชิก ~{g['members'] or 0:,} คน · คำค้นที่เจอกลุ่มนี้: {g['keyword'] or '-'}")
    A(f"- สร้างซองเมื่อ {datetime.now():%d/%m/%Y %H:%M}")
    A("")
    A("## 0. ข้อมูลชุดนี้เชื่อได้แค่ไหน — อ่านก่อนทุกครั้ง")
    A("")
    A(f"| รายการ | ค่า |")
    A("|---|---|")
    A(f"| โพสต์ที่เก็บได้ | {len(posts):,} |")
    A(f"| โพสต์แมส (engagement > {MASS_MIN}) | **{mass_n}** |")
    A(f"| โพสต์ที่มีข้อความ | {sum(1 for p in posts if p['caption_len']):,} |")
    A(f"| คอมเมนต์ทั้งหมด | {cm['total']:,} |")
    A(f"| — เป็นแท็กชื่อเพื่อนล้วน (ตัดทิ้ง) | {cm['tag_only']:,} |")
    A(f"| — เป็นสแปม (ตัดทิ้ง) | {cm['spam']:,} |")
    A(f"| — **ใช้วิเคราะห์ได้** | **{cm['usable']:,}** |")
    A(f"| — มีสัญญาณถาม/สนใจซื้อ | {cm['signal']:,} |")
    A(f"| ระดับความเชื่อมั่น | **{gate}** |")
    A("")
    if gate == "ไม่พอ":
        A(f"> ⛔ กลุ่มนี้มีโพสต์แมสแค่ {mass_n} ใบ **สรุปสูตรไม่ได้** "
          "ให้ตอบว่า `cannot_say` แล้วบอกเหตุผล ห้ามเดาให้ดูดี")
    elif gate == "จำกัด":
        A(f"> ⚠️ มีโพสต์แมสแค่ {mass_n} ใบ สรุปได้แต่ต้องกำกับว่าอิงตัวอย่างน้อย")
    A("")
    A("## 1. คู่เทียบ — เหมือนกันทุกอย่าง ยกเว้นผลลัพธ์")
    A("")
    A("แต่ละคู่คุมไว้แล้วว่า **อยู่ช่วงอายุเดียวกัน · ความยาวข้อความพอกัน · "
      "จำนวนรูปเท่ากัน** สิ่งที่เหลือต่างกันคือ *เนื้อหา* — นี่คือส่วนที่ต้องใช้คุณอ่าน")
    A("")
    if not pairs:
        A("_(จับคู่ไม่ได้ — โพสต์แมสกับโพสต์เงียบไม่มีคู่ที่เงื่อนไขตรงกัน)_")
    for i, (hi, lo) in enumerate(pairs, 1):
        pid_hi, pid_lo = f"P{i}a", f"P{i}b"
        manifest[pid_hi] = hi["post_id"]
        manifest[pid_lo] = lo["post_id"]
        A(f"### คู่ {i} · {hi['age_band']} · {hi['cap_band']} · {hi['img_band']}")
        A(f"- **{pid_hi}** {fmt_post(hi, 'ปัง')}")
        A(f"- **{pid_lo}** {fmt_post(lo, 'เงียบ')}")
        A("")
    A("## 2. โพสต์แมสสูงสุด (ดูว่าเพดานของกลุ่มนี้หน้าตาแบบไหน)")
    A("")
    for i, p in enumerate(tops, 1):
        tid = f"T{i}"
        manifest[tid] = p["post_id"]
        A(f"- **{tid}** {fmt_post(p, 'แมส')}")
    A("")
    A("## 3. เสียงจากคอมเมนต์ (ล้างแล้ว)")
    A("")
    A(f"เลือกมา {len(cm['picked'])} อัน จากที่ใช้ได้ {cm['usable']:,} อัน — "
      "เน้นอันที่มีคำถาม/สัญญาณซื้อก่อน แล้วตามด้วยอันที่คนไลค์เยอะ")
    A("")
    for i, r in enumerate(cm["picked"], 1):
        cid = f"C{i}"
        manifest[cid] = r["comment_id"]
        body = (r["body"] or "").replace("\n", " ")[:180]
        src = "โพสต์แมส" if r["is_mass"] else "โพสต์เงียบ"
        A(f"- **{cid}** [{src} · 👍{r['likes'] or 0}] {r['author'][:24]}: «{body}»")
    A("")
    A("## 4. เมนูตัวเลขที่อ้างได้ (คุมอายุแล้ว)")
    A("")
    A("อ้างด้วย `metric_key` เท่านั้น **ห้ามพิมพ์ตัวเลขเอง** ระบบจะเติมให้ตอนบันทึก")
    lines.extend(catalog_lines)
    A("")
    A("## 5. กติกาการตอบ")
    A("")
    A("เขียนไฟล์ JSON ชื่อ **`" + gid + ".result.json`** ไว้โฟลเดอร์เดียวกับซองนี้")
    A("")
    A("```json")
    A(json.dumps({
        "gid": gid,
        "verdict": "ok | cannot_say",
        "cannot_say_why": "",
        "claims": [
            {"section": "do", "headline": "หัวข้อสั้นๆ ว่าควรทำอะไร",
             "detail": "อธิบายว่าทำไม อ้างสิ่งที่เห็นในซอง",
             "metric_key": "img_band|1 รูป", "evidence": ["P1a", "T2", "C5"]},
            {"section": "dont", "headline": "สิ่งที่ทำแล้วเงียบ",
             "detail": "…", "metric_key": "", "evidence": ["P3b"]},
            {"section": "audience", "headline": "ฐานลูกค้าเป็นใคร",
             "detail": "…", "metric_key": "", "evidence": ["C1", "C7"]},
            {"section": "timing", "headline": "ช่วงเวลาที่ควรโพสต์",
             "detail": "…", "metric_key": "hour_band|เย็น 17-19", "evidence": []},
        ],
    }, ensure_ascii=False, indent=2))
    A("```")
    A("")
    A("**กฎเหล็ก 4 ข้อ**")
    A("")
    A("1. `evidence` ต้องเป็นรหัสที่มีในซองนี้เท่านั้น (P·T·C) — อ้างรหัสที่ไม่มี "
      "ระบบจะปฏิเสธทั้งไฟล์")
    A("2. **ห้ามพิมพ์ตัวเลขในข้อความ** — ถ้าจะอ้างตัวเลข ใส่ `metric_key` "
      "จากหัวข้อ 4 แล้วระบบเติมให้เอง")
    A("3. ทุก claim ต้องมี `evidence` อย่างน้อย 1 รายการ ยกเว้น section `timing` "
      "ที่ใช้ metric_key แทนได้")
    A("4. ถ้าข้อมูลไม่พอจริงๆ ตอบ `\"verdict\": \"cannot_say\"` พร้อมเหตุผล — "
      "ดีกว่าเดาแล้วผู้ใช้เอาไปลงแรงผิดทาง")

    out_dir.mkdir(parents=True, exist_ok=True)
    body = "\n".join(lines)
    path = out_dir / f"{gid}.md"
    path.write_text(body, encoding="utf-8")
    (out_dir / f"{gid}.manifest.json").write_text(
        json.dumps({"gid": gid, "name": g["name"], "manifest": manifest,
                    "metrics": metrics, "gate": gate, "mass_n": mass_n,
                    "built_at": int(datetime.now().timestamp())},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✅ {path}")
    print(f"   {len(body):,} ตัวอักษร (~{len(body)//3:,} โทเคน) · "
          f"คู่เทียบ {len(pairs)} · โพสต์อ้างอิง {len([k for k in manifest if k[0] in 'PT'])} "
          f"· คอมเมนต์ {len([k for k in manifest if k[0]=='C'])} · ความเชื่อมั่น {gate}")
    return path


def main() -> int:
    args = sys.argv[1:]
    conn = sqlite3.connect(f"file:{DB_FILE}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    if "--list" in args or not args:
        print(f"{'gid':>18}  {'แมส':>5}  {'โพสต์':>6}  {'คอมเมนต์':>9}  ชื่อกลุ่ม")
        for r in conn.execute("""
                SELECT g.gid, g.name, COUNT(p.post_id) n, SUM(p.is_mass) m,
                  (SELECT COUNT(*) FROM fb_comment x JOIN fb_post q
                   ON q.post_id=x.post_id WHERE q.gid=g.gid) c
                FROM fb_group g JOIN fb_post p ON p.gid=g.gid
                GROUP BY g.gid ORDER BY m DESC"""):
            print(f"{r['gid']:>18}  {r['m'] or 0:>5}  {r['n']:>6}  {r['c']:>9,}  "
                  f"{r['name'][:38]}")
        return 0
    out_dir = OUT_DIR
    if "--out" in args:
        out_dir = Path(args[args.index("--out") + 1])
    if "--gid" in args:
        build(args[args.index("--gid") + 1], out_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
