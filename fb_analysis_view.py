"""หน้าเว็บ "พิมพ์ชื่อกลุ่ม → เห็นบทวิเคราะห์ทั้งหมดในหน้าเดียว"

  python fb_analysis_view.py --group "รีวิวโลตัส" --open
  python fb_analysis_view.py --gid reviewlotus --out data/fb_analysis_reviewlotus.html

ทำเป็นไฟล์ HTML ก้อนเดียว (แพทเทิร์นเดียวกับ fb_posts_view.py) ไม่ต้องมีเซิร์ฟเวอร์
ข้อมูลหลักฐานฝังมาในหน้าแล้ว กดปุ๊บเปิดปั๊บ ไม่ต้องยิงฐานซ้ำ

หัวใจของหน้านี้: **ทุกข้อสรุปมีชิปหลักฐานต่อท้าย กดแล้วเห็นโพสต์/คอมเมนต์จริง**
ถ้าข้อสรุปไหนไม่มีหลักฐาน มันจะเข้าฐานไม่ได้ตั้งแต่แรก (ดู fb_analysis_store.py)
"""
from __future__ import annotations

import argparse
import html
import json
import sys
import webbrowser
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fb_analysis_sql as q          # noqa: E402
import fb_analysis_store as st       # noqa: E402

SEC_TITLE = {"do": "✅ แนวทางที่ได้ผล", "dont": "⛔ แนวทางที่ไม่ได้ผล",
             "audience": "👥 ฐานลูกค้าของกลุ่มนี้", "timing": "⏰ เรื่องเวลา",
             "warning": "⚠️ ข้อควรระวัง / ยังสรุปไม่ได้"}
CONF_TXT = {"high": ("เชื่อถือได้", "#1a7f37"), "medium": ("พอเห็นแนวโน้ม", "#9a6700"),
            "low": ("ตัวอย่างน้อยมาก", "#bc4c00"), "none": ("สรุปไม่ได้", "#cf222e")}
E = html.escape


def _t(ts) -> str:
    return datetime.fromtimestamp(ts).strftime("%d/%m/%y %H:%M") if ts else "-"


def collect(conn, gid: str) -> dict:
    g = conn.execute("SELECT * FROM fb_group WHERE gid=?", (gid,)).fetchone()
    s = dict(conn.execute(q.GROUP_STAT_SQL, {"gid": gid}).fetchone())
    ql = dict(conn.execute(q.GROUP_QUALITY_SQL, {"gid": gid}).fetchone())
    contrast = [dict(r) for r in conn.execute(q.CONTRAST_SQL, {"gid": gid, "min_n": 5})]
    hours = [dict(r) for r in conn.execute(q.HOUR_HIST_SQL, {"gid": gid})]
    run = conn.execute("""SELECT * FROM analysis_run WHERE gid=? AND status='active'
                          ORDER BY created_at DESC LIMIT 1""", (gid,)).fetchone()
    claims, ev_ids = [], set()
    if run:
        for c in conn.execute("SELECT * FROM analysis_claim WHERE run_id=? ORDER BY section, ord",
                              (run["run_id"],)):
            ev = [dict(x) for x in conn.execute(
                "SELECT kind, ref_id FROM analysis_evidence WHERE claim_id=?", (c["claim_id"],))]
            for e in ev:
                ev_ids.add((e["kind"], e["ref_id"]))
            claims.append({**dict(c), "evidence": ev})
    # โพสต์ตัวอย่างในตารางตัวเลขก็ต้องกดดูได้เหมือนกัน (ไม่งั้นชิปกดแล้วว่าง)
    for r in contrast:
        for pid in [x for x in (r["ex_post_ids"] or "").split(",") if x][:3]:
            ev_ids.add(("post", pid))
    # ดึงเนื้อหลักฐานมาฝังในหน้า — เฉพาะชิ้นที่ถูกอ้างจริง หน้าจะได้ไม่บวม
    eb: dict[str, dict] = {}
    for kind, rid in ev_ids:
        if kind == "post":
            r = conn.execute("""SELECT post_id, url, author, caption, engagement,
                   reactions, comments, shares, images_n, posted_at, first_alt
                   FROM v_post_feat WHERE post_id=?""", (rid,)).fetchone()
            if r:
                eb["post:" + rid] = {"t": "post", **dict(r)}
        else:
            r = conn.execute("""SELECT c.comment_id, c.post_id, c.author, c.likes,
                   COALESCE(e.body_clean,c.body) body, COALESCE(e.role,'') role,
                   p.url post_url
                   FROM fb_comment c JOIN fb_post p ON p.post_id=c.post_id
                   LEFT JOIN comment_enrich e ON e.comment_id=c.comment_id
                   WHERE c.comment_id=?""", (rid,)).fetchone()
            if r:
                eb["comment:" + rid] = {"t": "comment", **dict(r)}
    return {"g": dict(g) if g else {"gid": gid, "name": gid}, "stat": s, "qual": ql,
            "contrast": contrast, "hours": hours,
            "run": dict(run) if run else None, "claims": claims, "ev": eb,
            "sig_now": st.input_sig(conn, gid)}


CSS = """
*{box-sizing:border-box} body{margin:0;font-family:'Segoe UI',Tahoma,sans-serif;
 background:#f0f2f5;color:#1c1e21} .wrap{max-width:1100px;margin:0 auto;padding:16px}
.card{background:#fff;border-radius:10px;box-shadow:0 1px 2px rgba(0,0,0,.2);
 padding:16px;margin-bottom:14px} h1{font-size:22px;margin:0 0 4px}
h2{font-size:17px;margin:0 0 10px;border-bottom:1px solid #e4e6eb;padding-bottom:6px}
.muted{color:#65676b;font-size:13px} .badge{display:inline-block;padding:2px 9px;
 border-radius:12px;color:#fff;font-size:12px;font-weight:600}
.claim{padding:10px 0;border-bottom:1px solid #f0f2f5} .claim:last-child{border:0}
.claim b{font-size:15px} .metric{font-size:12px;color:#0064d1;background:#eaf3ff;
 padding:2px 8px;border-radius:6px;display:inline-block;margin-top:4px}
.chip{display:inline-block;font-size:12px;background:#e7f3ff;color:#0064d1;
 border:1px solid #cfe4fb;border-radius:12px;padding:1px 9px;margin:3px 4px 0 0;cursor:pointer}
.chip:hover{background:#0064d1;color:#fff} .chip.cm{background:#fff4e5;color:#a35b00;
 border-color:#ffe0b2} .chip.cm:hover{background:#a35b00;color:#fff}
table{border-collapse:collapse;width:100%;font-size:13px}
th,td{border-bottom:1px solid #e4e6eb;padding:5px 7px;text-align:left}
th{background:#f7f8fa} tr:hover td{background:#fafbfc}
.warn{background:#fff8e1;border-left:4px solid #f0b400;padding:10px;
 border-radius:6px;margin:8px 0;font-size:13px}
.err{background:#ffeaea;border-left:4px solid #cf222e}
.bar{height:12px;background:#1877f2;border-radius:3px;display:inline-block;vertical-align:middle}
#dr{position:fixed;inset:0;background:rgba(0,0,0,.45);display:none;z-index:9}
#dr.on{display:block} #box{position:absolute;right:0;top:0;bottom:0;width:min(520px,92vw);
 background:#fff;padding:18px;overflow:auto} #box .close{float:right;cursor:pointer;
 font-size:22px;color:#65676b} .ev{border:1px solid #e4e6eb;border-radius:8px;
 padding:12px;margin-bottom:10px} .ev .cap{white-space:pre-wrap;margin:8px 0}
a{color:#0064d1}
"""

JS = """
const EV=__EV__;
function open_ev(keys){
 const b=document.getElementById('body');b.innerHTML='';
 keys.forEach(k=>{const d=EV[k];const el=document.createElement('div');el.className='ev';
  if(!d){el.innerHTML='<i>ไม่พบหลักฐานชิ้นนี้ในฐาน</i>';}
  else if(d.t==='post'){el.innerHTML=`<b>${d.author||''}</b> <span class="muted">· ${d.when||''}</span>
   <div class="cap">${(d.caption||'(ไม่มี caption)')}</div>
   ${d.first_alt?`<div class="muted">รูป (alt): ${d.first_alt}</div>`:''}
   <div class="muted">ไลก์ ${d.reactions} · คอมเมนต์ ${d.comments} · แชร์ ${d.shares}
   · รูป ${d.images_n} · <b>engagement ${d.engagement}</b></div>
   <a href="${d.url}" target="_blank" rel="noopener">เปิดโพสต์จริงบน Facebook ↗</a>`;}
  else{el.innerHTML=`<b>${d.author||''}</b> <span class="muted">(${d.role||'-'} · ไลก์ ${d.likes})</span>
   <div class="cap">${d.body||'(ไม่มีข้อความ)'}</div>
   <a href="${d.post_url}" target="_blank" rel="noopener">เปิดโพสต์ที่คอมเมนต์นี้อยู่ ↗</a>`;}
  b.appendChild(el);});
 document.getElementById('dr').classList.add('on');
}
function close_ev(){document.getElementById('dr').classList.remove('on');}
document.addEventListener('keydown',e=>{if(e.key==='Escape')close_ev();});
"""


def render(d: dict) -> str:
    g, s, ql = d["g"], d["stat"], d["qual"]
    run, claims = d["run"], d["claims"]
    P = []
    P.append(f"<h1>{E(g.get('name') or g['gid'])}</h1>")
    P.append(f"<div class='muted'>gid <code>{E(g['gid'])}</code> · สมาชิก "
             f"{g.get('members') or '-'} · โพสต์ในฐาน {s['n_post']} ใบ · "
             f"โพสต์แมส {s['n_mass']} ใบ · คอมเมนต์ {s['comments_stored']} อัน</div>")

    # ---- แถบความน่าเชื่อถือ + ล้าสมัย
    if run:
        txt, col = CONF_TXT.get(run["confidence"], ("-", "#65676b"))
        P.append(f"<div style='margin-top:10px'><span class='badge' style='background:{col}'>"
                 f"ความเชื่อถือ: {txt}</span> <span class='muted'>{E(run['confidence_why'])}"
                 f" · วิเคราะห์เมื่อ {_t(run['created_at'])}</span></div>")
        if run["input_sig"] != d["sig_now"]:
            P.append("<div class='warn err'>บทวิเคราะห์นี้<b>ล้าสมัยแล้ว</b> — ข้อมูลในฐาน"
                     f"เปลี่ยนไปหลังวิเคราะห์ ({E(run['input_sig'])} → {E(d['sig_now'])}) "
                     "ให้สร้างซองใหม่: <code>python fb_brief.py --gid "
                     f"{E(g['gid'])}</code></div>")
    else:
        P.append("<div class='warn'>ยังไม่มีบทวิเคราะห์ของกลุ่มนี้ — สร้างซองข้อมูลด้วย "
                 f"<code>python fb_brief.py --gid {E(g['gid'])} --out brief.md</code> "
                 "แล้วเอาไปให้ Claude ในแชทอ่าน จากนั้นบันทึกคำตอบด้วย "
                 "<code>python fb_analysis_apply.py --json ans.json</code></div>")

    # ---- คุณภาพข้อมูล (โชว์ก่อนบทวิเคราะห์เสมอ)
    warns = []
    if ql["pct_share_zero"] and ql["pct_share_zero"] > 50:
        warns.append(f"ยอดแชร์เป็น 0 อยู่ {ql['pct_share_zero']}% ของโพสต์ และไม่มีแถวไหนเป็น NULL "
                     "— ตัวเก็บบันทึก 'อ่านไม่ได้' เป็น 0 → engagement บางใบต่ำกว่าจริง")
    cov = ql["pct_comment_cov"] or 0
    warns.append(f"เก็บคอมเมนต์ได้ {cov}% ของที่ FB บอกว่ามี (จากโพสต์ {ql['n_post_with_cm']} ใบ "
                 f"· ยังไม่ได้เก็บ {ql['n_post_cm_pending']} ใบ)")
    if ql["n_days"] < 7:
        warns.append(f"ข้อมูลครอบคลุมแค่ {ql['n_days']} วัน (ชั่วโมง {ql['hour_min']}–{ql['hour_max']}) "
                     "— สรุปเรื่องวัน/เวลาที่ดีที่สุดไม่ได้")
    P.append("<div class='card'><h2>ข้อมูลชุดนี้เชื่อได้แค่ไหน</h2>" +
             "".join(f"<div class='warn'>{E(w)}</div>" for w in warns) + "</div>")

    # ---- บทวิเคราะห์
    if claims:
        by: dict[str, list] = {}
        for c in claims:
            by.setdefault(c["section"], []).append(c)
        for sec in ("do", "dont", "audience", "timing", "warning"):
            if sec not in by:
                continue
            P.append(f"<div class='card'><h2>{SEC_TITLE[sec]}</h2>")
            for c in by[sec]:
                keys = [f"{e['kind']}:{e['ref_id']}" for e in c["evidence"]]
                chips = "".join(
                    f"<span class='chip{' cm' if e['kind']=='comment' else ''}' "
                    f"onclick=\"open_ev(['{e['kind']}:{e['ref_id']}'])\">"
                    f"{'โพสต์' if e['kind']=='post' else 'คอมเมนต์'} #{E(e['ref_id'][-6:])}</span>"
                    for e in c["evidence"])
                allc = (f"<span class='chip' onclick='open_ev({json.dumps(keys)})'>"
                        f"ดูทั้งหมด {len(keys)} ชิ้น</span>") if len(keys) > 1 else ""
                P.append(f"<div class='claim'><b>{E(c['headline'])}</b>"
                         f"<div class='muted'>{E(c['detail'])}</div>"
                         + (f"<div class='metric'>ตัวเลขจากฐาน: {E(c['metric_value'])}</div>"
                            if c["metric_value"] else "")
                         + f"<div>{chips}{allc}</div></div>")
            P.append("</div>")

    # ---- ตารางตัวเลข
    P.append("<div class='card'><h2>ตัวเลขที่คำนวณจากฐาน (กดชื่อโพสต์ตัวอย่างเพื่อดูของจริง)</h2>"
             "<table><tr><th>มิติ</th><th>แถบ</th><th>n</th><th>มัธยฐาน</th>"
             "<th>%แมส</th><th>%eng=0</th><th>สูงสุด</th><th>ตัวอย่าง</th></tr>")
    for r in d["contrast"]:
        ids = [x for x in (r["ex_post_ids"] or "").split(",") if x][:3]
        ex = "".join(f"<span class='chip' onclick=\"open_ev(['post:{i}'])\">#{E(i[-6:])}</span>"
                     for i in ids)
        P.append(f"<tr><td>{E(r['dim'][2:])}</td><td>{E(r['band'])}</td><td>{r['n']}</td>"
                 f"<td><b>{r['med_eng']}</b></td><td>{r['pct_mass']}%</td>"
                 f"<td>{r['pct_zero']}%</td><td>{r['max_eng']}</td><td>{ex}</td></tr>")
    P.append("</table></div>")

    # ---- กราฟชั่วโมง
    if d["hours"]:
        mx = max(h["n"] for h in d["hours"]) or 1
        P.append("<div class='card'><h2>โพสต์ตามชั่วโมง (เวลาไทย)</h2><table>")
        for h in d["hours"]:
            P.append(f"<tr><td style='width:60px'>{h['hour']:02d}:00</td>"
                     f"<td style='width:70px'>{h['n']} ใบ</td>"
                     f"<td><span class='bar' style='width:{int(220*h['n']/mx)}px'></span></td>"
                     f"<td style='width:150px'>มัธยฐาน {h['med_eng']} · แมส {h['n_mass']}</td></tr>")
        P.append("</table></div>")

    # ---- ตัวหลักฐาน (ฝังข้อมูล + drawer)
    ev = {}
    for k, v in d["ev"].items():
        v = dict(v)
        if v["t"] == "post":
            v["when"] = _t(v.pop("posted_at"))
            v["caption"] = E(v.get("caption") or "")
            v["first_alt"] = E(v.get("first_alt") or "")
            v["author"] = E(v.get("author") or "")
        else:
            v["body"] = E(v.get("body") or "")
            v["author"] = E(v.get("author") or "")
        ev[k] = v
    body = "\n".join(P)
    js = JS.replace("__EV__", json.dumps(ev, ensure_ascii=False))
    return (f"<!doctype html><html lang='th'><head><meta charset='utf-8'>"
            f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<title>วิเคราะห์กลุ่ม {E(g.get('name') or g['gid'])}</title><style>{CSS}</style>"
            f"</head><body><div class='wrap'>{body}</div>"
            f"<div id='dr' onclick='if(event.target.id===\"dr\")close_ev()'>"
            f"<div id='box'><span class='close' onclick='close_ev()'>×</span>"
            f"<h2>หลักฐาน</h2><div id='body'></div></div></div>"
            f"<script>{js}</script></body></html>")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(st.DB_FILE))
    ap.add_argument("--gid")
    ap.add_argument("--group")
    ap.add_argument("--out")
    ap.add_argument("--open", action="store_true")
    a = ap.parse_args()
    conn = st.connect(a.db)
    st.ensure_schema(conn)
    gid = a.gid
    if not gid and a.group:
        r = conn.execute("SELECT gid FROM fb_group WHERE name LIKE ? "
                         "ORDER BY posts_seen DESC LIMIT 1", (f"%{a.group}%",)).fetchone()
        if not r:
            raise SystemExit(f"ไม่พบกลุ่มที่ชื่อมี '{a.group}'")
        gid = r["gid"]
    if not gid:
        raise SystemExit("ต้องระบุ --gid หรือ --group")
    d = collect(conn, gid)
    out = Path(a.out or (Path(a.db).parent / f"fb_analysis_{gid}.html"))
    out.write_text(render(d), encoding="utf-8")
    print(f"[เขียนหน้าเว็บ] {out} ({out.stat().st_size:,} ไบต์ · หลักฐานฝังไว้ {len(d['ev'])} ชิ้น)")
    if a.open:
        webbrowser.open(out.resolve().as_uri())


if __name__ == "__main__":
    main()
