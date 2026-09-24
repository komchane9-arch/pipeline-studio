"""Recover only four logged pre-send quota rejections; preserve all other errors."""
import json
import sqlite3
from datetime import datetime
from pathlib import Path

root = Path(__file__).resolve().parents[1]
db = root / "data" / "fb_engagement.db"
names = ("Bunriam Phiwwandee", "จรีรัตน์ พึ่งดาบศ", "จินดา วิลัยพล", "สมบูรณ์ วรรณใส")
with sqlite3.connect(db, timeout=20) as conn:
    backup = db.with_name("fb_engagement-before-quota-recovery-" + datetime.now().strftime("%Y%m%d-%H%M%S") + ".db")
    with sqlite3.connect(backup) as target:
        conn.backup(target)
    conn.execute("BEGIN IMMEDIATE")
    count = 0
    for name in names:
        cursor = conn.execute("""
            UPDATE my_comment SET reply_error=''
            WHERE account='Khao Fang Nichapa' AND author=?
              AND post_url='https://www.facebook.com/share/p/19MWioU8ab/'
              AND reply_error='พิมพ์หรือยืนยันข้อความบน Facebook ไม่สำเร็จ'
              AND REPLACE(reply_attempted_at,' ','T') BETWEEN '2026-09-20T06:49:00' AND '2026-09-20T06:53:00'
              AND COALESCE(reply_sent_at,'')='' AND answered=0
              AND COALESCE(reply_queued_at,'')<>'' AND COALESCE(ignored,0)=0
            """, (name,))
        count += cursor.rowcount
    conn.commit()
print(json.dumps({"recovered": count, "backup": str(backup)}, ensure_ascii=False))
