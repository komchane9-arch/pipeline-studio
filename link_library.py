"""Persistent shop labels for clip links; queue and product files remain authoritative."""
import sqlite3
import re
from urllib.parse import urlsplit
from pathlib import Path


class LinkLibrary:
    def __init__(self, path):
        self.path = Path(path)

    def connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        db.executescript("""
            CREATE TABLE IF NOT EXISTS shops (
                name TEXT PRIMARY KEY, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE IF NOT EXISTS links (
                url TEXT PRIMARY KEY, shop TEXT NOT NULL DEFAULT '',
                job_id TEXT NOT NULL DEFAULT '', item_id TEXT NOT NULL DEFAULT '',
                name TEXT NOT NULL DEFAULT '', created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        """)
        return db

    @staticmethod
    def shop_name(value):
        name = str(value or '').strip()
        if len(name) > 120:
            raise ValueError('ชื่อร้านยาวได้ไม่เกิน 120 ตัวอักษร')
        return name

    def add_shop(self, value):
        name = self.shop_name(value)
        if not name:
            raise ValueError('กรุณาใส่ชื่อร้าน')
        db = self.connect()
        try:
            with db:
                db.execute('INSERT OR IGNORE INTO shops(name) VALUES (?)', (name,))
        finally:
            db.close()
        return name

    def record(self, url, job_id, shop=None):
        name = self.shop_name(shop) if shop is not None else None
        db = self.connect()
        try:
            with db:
                if name:
                    db.execute('INSERT OR IGNORE INTO shops(name) VALUES (?)', (name,))
                db.execute('INSERT OR IGNORE INTO links(url,job_id,shop) VALUES (?,?,?)',
                           (url, job_id, name or ''))
                db.execute('UPDATE links SET job_id=? WHERE url=?', (job_id, url))
                if name is not None:
                    db.execute('UPDATE links SET shop=? WHERE url=?', (name, url))
        finally:
            db.close()

    def assign(self, url, shop):
        name = self.shop_name(shop)
        db = self.connect()
        try:
            with db:
                found = db.execute('SELECT 1 FROM links WHERE url=?', (url,)).fetchone()
                if not found:
                    raise ValueError('ไม่พบลิงก์นี้ในคลัง')
                if name:
                    db.execute('INSERT OR IGNORE INTO shops(name) VALUES (?)', (name,))
                db.execute('UPDATE links SET shop=? WHERE url=?', (name, url))
        finally:
            db.close()

    def save_links(self, text, shop):
        """Store URLs only. Never create jobs, resolve redirects, or fetch metadata."""
        name = self.shop_name(shop)
        if not name:
            raise ValueError('กรุณาเลือกร้าน')
        if not isinstance(text, str) or len(text) > 20000:
            raise ValueError('วางลิงก์ได้ไม่เกิน 20,000 ตัวอักษรต่อครั้ง')
        urls = list(dict.fromkeys(re.findall(r'https?://[^\s<>"\']+', text)))
        urls = list(dict.fromkeys(u.rstrip('.,)]}…') for u in urls))
        if not urls:
            raise ValueError('ไม่พบลิงก์ http หรือ https ในข้อความ')
        for url in urls:
            parsed = urlsplit(url)
            if not parsed.hostname or parsed.username or parsed.password:
                raise ValueError('รูปแบบลิงก์ไม่ถูกต้อง')
        db = self.connect()
        try:
            with db:
                db.execute('INSERT OR IGNORE INTO shops(name) VALUES (?)', (name,))
                added = 0
                for url in urls:
                    added += db.execute('INSERT OR IGNORE INTO links(url,shop) VALUES (?,?)', (url,name)).rowcount
                    db.execute('UPDATE links SET shop=? WHERE url=?', (name,url))
            return {'ok': True, 'count': added, 'skipped': len(urls)-added}
        finally:
            db.close()

    def listing(self, jobs):
        # Import older/web/Telegram jobs without replacing user-assigned shops.
        db = self.connect()
        try:
            with db:
                for job in jobs:
                    url = job.get('link', '')
                    if not url:
                        continue
                    db.execute('INSERT OR IGNORE INTO links(url,job_id) VALUES (?,?)',
                               (url, job['id']))
                    db.execute("UPDATE links SET job_id=? WHERE url=? AND job_id=''", (job['id'],url))
                    db.execute("""UPDATE links SET item_id=CASE WHEN ?<>'' THEN ? ELSE item_id END,
                        name=CASE WHEN ?<>'' THEN ? ELSE name END WHERE job_id=?""",
                        (job.get('item_id') or '', job.get('item_id') or '',
                         job.get('name') or '', job.get('name') or '', job['id']))
                rows = [dict(r) for r in db.execute('SELECT * FROM links ORDER BY created_at DESC,rowid DESC')]
                shops = [r['name'] for r in db.execute('SELECT name FROM shops ORDER BY name')]
            by_id = {j['id']: j for j in jobs}
            for row in rows:
                job = by_id.get(row['job_id'], {})
                row.update(stage=job.get('stage', ''), error=job.get('error', ''),
                           item_id=job.get('item_id') or row['item_id'],
                           name=job.get('name') or row['name'])
            return {'ok': True, 'shops': shops, 'items': rows}
        finally:
            db.close()
