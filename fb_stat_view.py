"""หน้าเว็บ "พิมพ์ชื่อกลุ่ม แล้วเห็นทุกอย่างในหน้าเดียว"

อ่านจาก data/fb_stats.db ที่คำนวณไว้แล้วล้วนๆ (ไม่คำนวณสดสักตัว) ตามกติกา "ห้ามช้า"
ยกเว้นตัวอย่างโพสต์/คอมเมนต์ที่ต้องดึงข้อความจริงจาก src ซึ่งเป็นการอ่านตรง PK

ใช้ได้ 2 ทาง:
  1) ฝังใน pipeline studio (พอร์ต 8866):  import fb_stat_view; fb_stat_view.mount(app)
     → /fb-stats            หน้าค้นหากลุ่ม
       /fb-stats/{gid}      หน้าบทวิเคราะห์เต็ม
  2) ทดสอบเดี่ยว:  python fb_stat_view.py <gid> out.html
"""
from __future__ import annotations

import html
import sys
import time
from pathlib import Path

import fb_stat_store as st

CSS = """
:root{--bg:#f0f2f5;--card:#fff;--ink:#1c1e21;--dim:#65676b;--line:#dadde1;
      --ok:#31a24c;--warn:#f7b928;--bad:#e41e3f;--blue:#1877f2}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
     font-family:'Segoe UI',Roboto,'Helvetica Neue',sans-serif;font-size:15px;line-height:1.55}
.wrap{max-width:900px;margin:0 auto;padding:16px}
.card{background:var(--card);border-radius:10px;padding:16px 18px;margin-bottom:14px;
      box-shadow:0 1px 2px rgba(0,0,0,.1)}
h1{font-size:22px;margin:0 0 4px} h2{font-size:17px;margin:0 0 10px}
.sub{color:var(--dim);font-size:13px}
.badge{display:inline-block;padding:2px 9px;border-radius:12px;font-size:12px;
       font-weight:600;color:#fff}
.b-high{background:var(--ok)}.b-medium{background:var(--blue)}
.b-low{background:var(--warn);color:#3a2b00}.b-none{background:var(--bad)}
.alert{border-left:4px solid var(--bad);background:#fff0f2;padding:10px 12px;
       border-radius:6px;margin:8px 0;font-size:14px}
.alert.warn{border-color:var(--warn);background:#fff8e6}
table{width:100%;border-collapse:collapse;font-size:13.5px}
th,td{padding:6px 8px;border-bottom:1px solid var(--line);text-align:left}
th{color:var(--dim);font-weight:600;font-size:12.5px}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}
.pill{padding:1px 7px;border-radius:10px;font-size:12px;white-space:nowrap}
.p-pass{background:#e3f6e8;color:#16632c}.p-weak{background:#fff3d6;color:#7a5600}
.p-reject{background:#f0f2f5;color:#65676b}.p-constant{background:#f0f2f5;color:#8a8d91}
.p-blocked{background:#ffe3e8;color:#9c0a24}
.bar{height:9px;background:var(--blue);border-radius:5px;display:inline-block;min-width:2px}
.ev{display:block;padding:6px 8px;border-left:3px solid var(--blue);background:#f7f9ff;
    margin:5px 0;font-size:13px;text-decoration:none;color:inherit;border-radius:0 6px 6px 0}
.ev:hover{background:#eef3ff}
input[type=search]{width:100%;padding:10px 12px;border:1px solid var(--line);
                   border-radius:20px;font-size:15px}
a.grp{display:block;padding:9px 4px;border-bottom:1px solid var(--line);
      text-decoration:none;color:inherit}
a.grp:hover{background:#f7f8fa}
.md{white-space:pre-wrap;font-size:14.5px}
.empty{color:var(--dim);font-style:italic}
"""


def _e(s) -> str:
    return html.escape(str(s if s is not None else ""))


def _bar(v: float, mx: float, w: int = 120) -> str:
    px = max(2, int((v / mx) * w)) if mx else 2
    return f'<span class="bar" style="width:{px}px"></span>'


def index_html(conn) -> str:
    rows = conn.execute("""SELECT gid,name,members,n_posts,n_mass,ok_content,ok_audience
                           FROM group_stats ORDER BY n_posts DESC""").fetchall()
    items = "".join(
        f'<a class="grp" href="/fb-stats/{_e(r["gid"])}" data-k="{_e(r["name"]).lower()} {_e(r["gid"])}">'
        f'<b>{_e(r["name"])}</b> <span class="sub">· {r["n_posts"]:,} โพสต์ · แมส {r["n_mass"]} '
        f'· {"วิเคราะห์ content ได้" if r["ok_content"] else "ตัวอย่างไม่พอ"}'
        f'{" · ฐานลูกค้าได้" if r["ok_audience"] else ""}</span></a>' for r in rows)
    return f"""<!doctype html><meta charset="utf-8"><title>วิเคราะห์กลุ่ม</title>
<style>{CSS}</style><div class="wrap"><div class="card">
<h1>วิเคราะห์กลุ่ม Facebook</h1>
<p class="sub">พิมพ์ชื่อกลุ่มเพื่อกรอง — มีข้อมูล {len(rows)} กลุ่ม</p>
<input type="search" id="q" placeholder="พิมพ์ชื่อกลุ่ม…" autofocus>
<div id="list">{items}</div></div></div>
<script>
const q=document.getElementById('q');
q.addEventListener('input',()=>{{const v=q.value.trim().toLowerCase();
 document.querySelectorAll('a.grp').forEach(a=>{{
   a.style.display = !v || a.dataset.k.includes(v) ? '' : 'none';}});}});
</script>"""


def group_html(conn, gid: str) -> str:
    g = conn.execute("SELECT * FROM group_stats WHERE gid=?", (gid,)).fetchone()
    if g is None:
        return f'<!doctype html><meta charset="utf-8"><style>{CSS}</style>' \
               f'<div class="wrap"><div class="card">ยังไม่มีสถิติของกลุ่ม {_e(gid)} — ' \
               f'สั่ง <code>python fb_stat_layer.py {_e(gid)}</code> ก่อน</div></div>'
    an = conn.execute("SELECT * FROM group_analysis WHERE gid=? ORDER BY rev DESC LIMIT 1",
                      (gid,)).fetchone()
    conf = an["confidence"] if an else st.confidence_of(g)
    P: list[str] = [f'<!doctype html><meta charset="utf-8"><title>{_e(g["name"])}</title>',
                    f"<style>{CSS}</style><div class='wrap'>"]

    # ── หัวเรื่อง + ระดับความเชื่อถือ ──
    P.append('<div class="card">')
    P.append(f'<h1>{_e(g["name"])} <span class="badge b-{conf}">ความเชื่อถือ: {conf}</span></h1>')
    P.append(f'<p class="sub">สมาชิก {g["members"] or 0:,} · เก็บได้ {g["n_posts"]:,} โพสต์ '
             f'(แมส {g["n_mass"]}) · คอมเมนต์ {g["cmt_got"] or 0:,} '
             f'· คำนวณเมื่อ {time.strftime("%d/%m/%Y %H:%M", time.localtime(g["computed_at"]))} '
             f'· ชุดข้อมูล {_e(g["input_hash"])}</p>')
    if not g["ok_content"]:
        P.append(f'<div class="alert"><b>ยังสรุปแนวทาง content ไม่ได้</b> — {_e(g["block_reason"])}<br>'
                 f'ต้องเก็บโพสต์แมสเพิ่มอีกอย่างน้อย {max(0, st.MIN_MASS - g["n_mass"])} ใบ</div>')
    if not g["ok_audience"]:
        P.append('<div class="alert warn"><b>ยังวิเคราะห์ฐานลูกค้าไม่ได้</b> — '
                 f'เก็บคอมเมนต์ได้ {g["cmt_cov_pct"]}% (ต้อง ≥{int(st.MIN_CMT_COV*100)}%) '
                 f'· มีเนื้อหาจริง {g["cmt_content"] or 0} อัน (ต้อง ≥{st.MIN_CMT})</div>')
    if g["shares_trust"] == "suspect":
        P.append(f'<div class="alert warn">ยอดแชร์อ่านไม่ได้เกือบทั้งกลุ่ม (มีแชร์&gt;0 แค่ '
                 f'{g["shares_pos_pct"]}%) → engagement จริงน่าจะสูงกว่าที่เห็น '
                 'ทุกข้อสรุปด้านล่างยืนยันซ้ำด้วยไลก์+คอมเมนต์แล้ว</div>')
    P.append('</div>')

    # ── บทวิเคราะห์ ──
    P.append('<div class="card"><h2>บทวิเคราะห์</h2>')
    if an is None:
        P.append('<p class="empty">ยังไม่มีบทวิเคราะห์ — สั่ง '
                 f'<code>python fb_stat_brief.py {_e(gid)}</code> เอาซองไปให้ Claude ในแชท '
                 'แล้วเขียนผลกลับด้วย <code>--apply</code></p>')
    else:
        stale = st.input_hash(conn, gid) != an["input_hash"]
        P.append(f'<p class="sub">rev {an["rev"]} · เขียนโดย {_e(an["author"])} · '
                 f'{time.strftime("%d/%m/%Y %H:%M", time.localtime(an["created_at"]))} · '
                 f'วิเคราะห์จากโพสต์ {an["n_posts"]:,} ใบ (แมส {an["n_mass"]}) '
                 f'คอมเมนต์ {an["n_comments"] or 0:,}'
                 + (' · <b style="color:var(--bad)">ข้อมูลเปลี่ยนแล้ว ควรวิเคราะห์ใหม่</b>'
                    if stale else '') + '</p>')
        if an["drift_note"]:
            P.append(f'<p class="sub">{_e(an["drift_note"])}</p>')
        if an["verdict"]:
            P.append(f'<p><b>{_e(an["verdict"])}</b></p>')
        for title, key in (("ทำแบบนี้", "do_md"), ("อย่าทำแบบนี้", "dont_md"),
                           ("ฐานลูกค้า", "audience_md"), ("ข้อจำกัด", "caveats_md")):
            if an[key]:
                P.append(f'<h2 style="margin-top:12px">{title}</h2>'
                         f'<div class="md">{_e(an[key])}</div>')
        ev = conn.execute("""SELECT e.*, p.url, substr(p.caption,1,90) cap, p.engagement,
                                    c.body cbody
                             FROM analysis_evidence e
                             LEFT JOIN src.fb_post p ON p.post_id=e.ref_id
                             LEFT JOIN src.fb_comment c ON c.comment_id=e.ref_id
                             WHERE e.gid=? AND e.rev=?""", (gid, an["rev"])).fetchall()
        if ev:
            P.append('<h2 style="margin-top:12px">หลักฐานที่อ้าง</h2>')
            for e in ev:
                if e["kind"] == "post":
                    P.append(f'<a class="ev" href="{_e(e["url"])}" target="_blank">'
                             f'[โพสต์ eng {e["engagement"]}] {_e(e["cap"])}… '
                             f'<span class="sub">— {_e(e["note"])}</span></a>')
                else:
                    P.append(f'<span class="ev">[คอมเมนต์] {_e((e["cbody"] or "")[:120])} '
                             f'<span class="sub">— {_e(e["note"])}</span></span>')
    P.append('</div>')

    # ── ตัวเลขที่วัดได้ ──
    P.append('<div class="card"><h2>ตัวเลขที่วัดได้</h2>')
    P.append(f'<p>engagement มัธยฐาน <b>{g["eng_p50"]}</b> · P90 {g["eng_p90"]} '
             f'· P95 {g["eng_p95"]} · สูงสุด {g["eng_max"]:,} · ได้ศูนย์ {g["eng_zero_pct"]}%<br>'
             f'มี caption {g["cap_pct"]}% (มัธยฐาน {g["cap_p50_len"]} ตัวอักษร) · '
             f'มีรูป {g["img_pct"]}% · คนโพสต์ {g["authors_n"]:,} คน '
             f'(ขาจร {g["author_once_pct"]}%)</p>')
    hrs = conn.execute("SELECT * FROM group_hour WHERE gid=? ORDER BY hour", (gid,)).fetchall()
    if hrs:
        mx = max(h["n"] for h in hrs)
        P.append('<table><tr><th>ชั่วโมง</th><th class="num">โพสต์</th><th></th>'
                 '<th class="num">มัธยฐาน eng</th><th class="num">แมส</th></tr>')
        for h in hrs:
            P.append(f'<tr><td>{h["hour"]:02d}:00</td><td class="num">{h["n"]}</td>'
                     f'<td>{_bar(h["n"], mx)}</td><td class="num">{h["eng_p50"]}</td>'
                     f'<td class="num">{h["mass_n"]}</td></tr>')
        P.append('</table>')
        if (g["hours_covered"] or 0) < 18:
            P.append(f'<p class="sub">⚠️ มีข้อมูลแค่ {g["hours_covered"]} ชั่วโมงที่ต่างกัน '
                     'ยังสรุป "เวลาไหนดีที่สุด" ไม่ได้</p>')
    P.append('</div>')

    # ── ฟีเจอร์ ──
    feats = conn.execute("""SELECT * FROM group_feature WHERE gid=?
        ORDER BY CASE status WHEN 'pass' THEN 0 WHEN 'weak' THEN 1 WHEN 'reject' THEN 2
                 WHEN 'constant' THEN 3 ELSE 4 END, ABS(COALESCE(auc,.5)-.5) DESC""",
                         (gid,)).fetchall()
    lab = {"pass": "ใช้ได้", "weak": "อ่อน", "reject": "ไม่ต่าง",
           "constant": "เกือบคงที่", "blocked": "ห้ามใช้"}
    P.append('<div class="card"><h2>ฟีเจอร์ที่ทดสอบแล้ว</h2>'
             f'<p class="sub">Mann-Whitney U · ผ่านเมื่อ p ≤ {st.P_MAX} และ |AUC−0.5| ≥ '
             f'{st.AUC_MIN} และทิศไม่พลิกเมื่อตัดยอดแชร์</p>'
             '<table><tr><th>ฟีเจอร์</th><th>ผล</th><th class="num">AUC</th>'
             '<th class="num">p</th><th>เหตุผล</th></tr>')
    for f in feats:
        pv = "-" if f["p"] is None else f"{f['p']:.1g}"
        au = "-" if f["auc"] is None else f"{f['auc']:.3f}"
        P.append(f'<tr><td>{_e(f["label"])}</td>'
                 f'<td><span class="pill p-{f["status"]}">{lab.get(f["status"], f["status"])}</span></td>'
                 f'<td class="num">{au}</td><td class="num">{pv}</td>'
                 f'<td class="sub">{_e(f["reason"])}</td></tr>')
    P.append('</table></div>')

    for f in [x for x in feats if x["status"] == "pass"]:
        bs = conn.execute("SELECT * FROM feature_bucket WHERE gid=? AND feat=? ORDER BY ord",
                          (gid, f["feat"])).fetchall()
        if not bs:
            continue
        mx = max(b["mass_pct"] or 0 for b in bs) or 1
        P.append(f'<div class="card"><h2>{_e(f["label"])}</h2><table>'
                 '<tr><th>ช่วง</th><th class="num">โพสต์</th><th class="num">มัธยฐาน eng</th>'
                 '<th class="num">%แมส</th><th></th><th class="num">%ได้ศูนย์</th></tr>')
        for b in bs:
            P.append(f'<tr><td>{_e(b["bucket"])}</td><td class="num">{b["n"]}</td>'
                     f'<td class="num">{b["eng_p50"]}</td><td class="num">{b["mass_pct"]}%</td>'
                     f'<td>{_bar(b["mass_pct"] or 0, mx, 90)}</td>'
                     f'<td class="num">{b["zero_pct"]}%</td></tr>')
        P.append('</table></div>')

    # ── คอมเมนต์ ──
    roles = conn.execute("""SELECT COALESCE(NULLIF(llm_role,''),rule_role) role, COUNT(*) n
                            FROM comment_label WHERE gid=? GROUP BY 1 ORDER BY n DESC""",
                         (gid,)).fetchall()
    if roles:
        tot = sum(r["n"] for r in roles)
        P.append('<div class="card"><h2>คอมเมนต์แยกตามบทบาท (กฎเป็นคนตี)</h2><table>')
        for r in roles:
            P.append(f'<tr><td>{_e(r["role"])}</td><td class="num">{r["n"]:,}</td>'
                     f'<td>{_bar(r["n"], tot, 200)}</td>'
                     f'<td class="num">{r["n"]/tot*100:.1f}%</td></tr>')
        P.append(f'</table><p class="sub">รวม {tot:,} อัน · '
                 f'ที่ล้างแล้วมีเนื้อหาจริง {g["cmt_content"] or 0:,} อัน — '
                 'ตัวเลขนี้คือของที่ "เก็บลงฐานได้" ไม่ใช่ของที่มีบน FB ทั้งหมด</p></div>')

    P.append('<p class="sub" style="text-align:center">'
             f'<a href="/fb-stats">← กลับไปเลือกกลุ่มอื่น</a></p></div>')
    return "\n".join(P)


def mount(app) -> None:
    """ฝังเข้า FastAPI ของ pipeline studio — เรียกครั้งเดียวตอน startup"""
    from fastapi.responses import HTMLResponse

    @app.get("/fb-stats", response_class=HTMLResponse)
    def _idx():
        conn = st.connect(write=False)
        try:
            return index_html(conn)
        finally:
            conn.close()

    @app.get("/fb-stats/{gid}", response_class=HTMLResponse)
    def _grp(gid: str):
        conn = st.connect(write=False)
        try:
            return group_html(conn, gid)
        finally:
            conn.close()


def main() -> int:
    conn = st.connect(write=True)
    if len(sys.argv) < 2:
        out = Path("_fb_stats_index.html")
        out.write_text(index_html(conn), encoding="utf-8")
    else:
        out = Path(sys.argv[2] if len(sys.argv) > 2 else f"_fb_stats_{sys.argv[1]}.html")
        out.write_text(group_html(conn, sys.argv[1]), encoding="utf-8")
    conn.close()
    print(out.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
