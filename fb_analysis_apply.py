"""รับบทวิเคราะห์ที่ Claude เขียนกลับมา → ตรวจ → บันทึกลงฐาน

  python fb_analysis_apply.py --json ans.json            # อ่าน brief_hash จากในไฟล์
  python fb_analysis_apply.py --brief c8a1c18b --json ans.json
  python fb_analysis_apply.py --show reviewlotus         # ดูผลล่าสุดของกลุ่ม

ปรัชญา: ถ้ามีข้อไหนผิดกติกา → ไม่บันทึกเลยทั้งรอบ (ห้ามเก็บครึ่งๆ กลางๆ)
ตัวเลขทุกตัวที่โชว์ในหน้าเว็บมาจาก SQL ไม่ใช่จากข้อความที่ LLM เขียน
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fb_analysis_sql as q          # noqa: E402
import fb_analysis_store as st       # noqa: E402


def metric_lookup(conn, gid: str, key: str) -> str:
    """แปลง metric_key 'มิติ|แถบ' เป็นตัวเลขจริงจาก SQL (LLM ห้ามกรอกตัวเลขเอง)"""
    if "|" not in (key or ""):
        return ""
    dim, band = key.split("|", 1)
    for r in conn.execute(q.CONTRAST_SQL, {"gid": gid, "min_n": 1}):
        if r["dim"].endswith(dim) and r["band"] == band:
            return (f"n={r['n']} · มัธยฐาน {r['med_eng']} · แมส {r['pct_mass']}% "
                    f"· eng=0 {r['pct_zero']}%")
    return ""


def show(conn, gid: str) -> None:
    r = conn.execute("""SELECT * FROM analysis_run WHERE gid=? AND status='active'
                        ORDER BY created_at DESC LIMIT 1""", (gid,)).fetchone()
    if not r:
        print("ยังไม่มีบทวิเคราะห์ของกลุ่มนี้")
        return
    sig_now = st.input_sig(conn, gid)
    print(f"run #{r['run_id']} · ความเชื่อถือ {r['confidence']} — {r['confidence_why']}")
    if sig_now != r["input_sig"]:
        print(f"⚠️ ล้าสมัย: ข้อมูลเปลี่ยนแล้ว ({r['input_sig']} → {sig_now})")
    for c in conn.execute("""SELECT * FROM analysis_claim WHERE run_id=?
                             ORDER BY section, ord""", (r["run_id"],)):
        ev = conn.execute("""SELECT kind, ref_id FROM analysis_evidence
                             WHERE claim_id=?""", (c["claim_id"],)).fetchall()
        tag = " ".join(f"[{e['kind'][0]}:{e['ref_id'][-6:]}]" for e in ev)
        print(f"  ({c['section']}) {c['headline']}  {tag}")
        if c["metric_value"]:
            print(f"      ตัวเลขจากฐาน: {c['metric_value']}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(st.DB_FILE))
    ap.add_argument("--json")
    ap.add_argument("--brief")
    ap.add_argument("--show")
    a = ap.parse_args()

    conn = st.connect(a.db)
    st.ensure_schema(conn)
    if a.show:
        show(conn, a.show)
        return
    if not a.json:
        raise SystemExit("ต้องระบุ --json ไฟล์คำตอบ")

    payload = json.loads(Path(a.json).read_text(encoding="utf-8"))
    bh = a.brief or payload.get("brief_hash")
    if not bh:
        raise SystemExit("ไม่รู้ว่าคำตอบนี้มาจากซองไหน — ใส่ --brief <hash>")
    try:
        res = st.apply_analysis(conn, bh, payload)
    except st.WritebackError as e:
        print(f"❌ ไม่บันทึก: {e}")
        raise SystemExit(2)

    # เติมตัวเลขจริงจาก SQL ให้ claim ที่ชี้ metric_key มา
    n_metric = 0
    for c in conn.execute("SELECT claim_id, metric_key FROM analysis_claim "
                          "WHERE run_id=? AND metric_key<>''", (res["run_id"],)).fetchall():
        val = metric_lookup(conn, res["gid"], c["metric_key"])
        conn.execute("UPDATE analysis_claim SET metric_value=? WHERE claim_id=?",
                     (val, c["claim_id"]))
        n_metric += 1 if val else 0
    conn.commit()
    print(f"✅ บันทึกแล้ว run #{res['run_id']} · {res['n_claim']} ข้อสรุป "
          f"· ความเชื่อถือ {res['confidence']} ({res['why']}) "
          f"· เติมตัวเลขจากฐาน {n_metric} จุด")


if __name__ == "__main__":
    main()
