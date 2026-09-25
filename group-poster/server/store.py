"""ฐานข้อมูล license ของ server — SQLite ไฟล์เดียว สำรองได้ด้วยการ copy ไฟล์

เก็บเฉพาะที่ต้องใช้จริง (PDPA): รหัส, แพ็กเกจ, หมายเหตุว่าขายให้ใคร,
machine_id ที่ hash มาแล้วจากฝั่ง agent และเวลาที่เห็นล่าสุด
ไม่เก็บข้อความโพสต์ รายชื่อกลุ่ม หรือข้อมูลบัญชี Facebook ของลูกค้า
"""

from __future__ import annotations

import os
import secrets
import sqlite3
import sys
import threading
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common import license_format as lf  # noqa: E402

DATA_DIR = Path(os.environ.get("GP_SERVER_DATA") or Path(__file__).with_name("data"))
KEY_FILE_NAME = "signing_key.pem"
DB_FILE_NAME = "licenses.sqlite3"

# ย้ายเครื่องได้ไม่เกินนี้ต่อ 30 วัน — กันแชร์รหัสเดียวกันใช้หลายคนด้วยการสลับไปมา
MAX_MOVES_PER_MONTH = 3

SCHEMA = """
CREATE TABLE IF NOT EXISTS licenses (
    id          TEXT PRIMARY KEY,
    code        TEXT UNIQUE NOT NULL,
    sku         TEXT NOT NULL,
    max_devices INTEGER NOT NULL,
    max_groups  INTEGER NOT NULL,
    expires     TEXT,
    note        TEXT NOT NULL DEFAULT '',
    revoked     INTEGER NOT NULL DEFAULT 0,
    created     TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS activations (
    license_id  TEXT NOT NULL,
    machine     TEXT NOT NULL,
    label       TEXT NOT NULL DEFAULT '',
    first_seen  TEXT NOT NULL,
    last_seen   TEXT NOT NULL,
    app_version TEXT NOT NULL DEFAULT '',
    active      INTEGER NOT NULL DEFAULT 1,
    released    TEXT,
    PRIMARY KEY (license_id, machine)
);
-- บันทึกการปลดเครื่องที่ลูกค้าทำเอง แยกจาก activations เพราะแถวใน activations
-- ถูกเขียนทับตอน activate ซ้ำ ถ้านับจากตรงนั้น ตัวนับจะรีเซ็ตทุกครั้งที่ย้ายกลับ
CREATE TABLE IF NOT EXISTS releases (
    license_id  TEXT NOT NULL,
    machine     TEXT NOT NULL,
    at          TEXT NOT NULL
);
"""


class Store:
    def __init__(self, data_dir: Path | None = None) -> None:
        self.data_dir = Path(data_dir or DATA_DIR)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(self.data_dir / DB_FILE_NAME, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        self.key = self._load_key()
        self.public_key = self.key.public_key()

    # -------------------------------------------------------------- กุญแจ

    def _load_key(self):
        path = self.data_dir / KEY_FILE_NAME
        if path.exists():
            return lf.private_key_from_pem(path.read_bytes())
        key = lf.new_private_key()
        path.write_bytes(lf.private_key_to_pem(key))
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        return key

    def public_key_text(self) -> str:
        return lf.public_key_text(self.key)

    # -------------------------------------------------------------- ออกรหัส

    def create_license(self, sku: str = "trial", days: int | None = None,
                       max_devices: int | None = None, max_groups: int | None = None,
                       note: str = "") -> dict:
        if sku not in lf.PLANS:
            raise ValueError(f"ไม่รู้จักแพ็กเกจ {sku} (มี: {', '.join(lf.PLANS)})")
        plan = lf.PLANS[sku]
        days = plan["days"] if days is None else days
        now = lf.utc_now()
        # days <= 0 = ไม่มีวันหมดอายุ (ขายขาด)
        expires = lf.iso(now + timedelta(days=days)) if days and days > 0 else None
        row = {
            "id": "lic_" + secrets.token_hex(8),
            "code": lf.new_code(),
            "sku": sku,
            "max_devices": int(max_devices or plan["max_devices"]),
            "max_groups": int(max_groups or plan["max_groups"]),
            "expires": expires,
            "note": note,
            "created": lf.iso(now),
        }
        with self.lock, self.db:
            self.db.execute(
                "INSERT INTO licenses (id, code, sku, max_devices, max_groups, expires,"
                " note, created) VALUES (:id, :code, :sku, :max_devices, :max_groups,"
                " :expires, :note, :created)", row)
        return self.get_license(row["id"])

    def get_license(self, license_id: str) -> dict | None:
        found = self.db.execute("SELECT * FROM licenses WHERE id = ?", (license_id,)).fetchone()
        return dict(found) if found else None

    def find_by_code(self, code: str) -> dict | None:
        found = self.db.execute(
            "SELECT * FROM licenses WHERE code = ?", (lf.normalize_code(code),)).fetchone()
        return dict(found) if found else None

    def find(self, text: str) -> dict | None:
        """หาจาก id หรือรหัสขายก็ได้ — ใช้ในคำสั่ง admin"""
        return self.get_license(text) or self.find_by_code(text)

    def list_licenses(self) -> list[dict]:
        rows = self.db.execute("SELECT * FROM licenses ORDER BY created DESC").fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["devices"] = self.devices(item["id"])
            result.append(item)
        return result

    def devices(self, license_id: str, active_only: bool = False) -> list[dict]:
        sql = "SELECT * FROM activations WHERE license_id = ?"
        if active_only:
            sql += " AND active = 1"
        return [dict(r) for r in self.db.execute(sql + " ORDER BY first_seen", (license_id,))]

    def set_revoked(self, license_id: str, revoked: bool = True) -> None:
        with self.lock, self.db:
            self.db.execute("UPDATE licenses SET revoked = ? WHERE id = ?",
                            (1 if revoked else 0, license_id))

    def extend(self, license_id: str, days: int) -> dict:
        lic = self.get_license(license_id)
        if not lic:
            raise ValueError("ไม่พบ license")
        now = lf.utc_now()
        base = lf.parse_iso(lic["expires"]) if lic["expires"] else now
        base = max(base, now)
        with self.lock, self.db:
            self.db.execute("UPDATE licenses SET expires = ? WHERE id = ?",
                            (lf.iso(base + timedelta(days=days)), license_id))
        return self.get_license(license_id)

    # -------------------------------------------------------------- สถานะ

    def problem(self, lic: dict | None) -> str:
        """license ใช้ไม่ได้เพราะอะไร — ว่าง = ใช้ได้"""
        if not lic:
            return "ไม่พบรหัสนี้ กรุณาตรวจตัวสะกดอีกครั้ง"
        if lic["revoked"]:
            return "รหัสนี้ถูกระงับแล้ว กรุณาติดต่อผู้ขาย"
        if lic["expires"] and lf.parse_iso(lic["expires"]) <= lf.utc_now():
            return f"รหัสนี้หมดอายุแล้ว ({lic['expires'][:10]})"
        return ""

    def _moves_last_month(self, license_id: str) -> int:
        edge = lf.iso(lf.utc_now() - timedelta(days=30))
        found = self.db.execute(
            "SELECT COUNT(*) FROM releases WHERE license_id = ? AND at >= ?",
            (license_id, edge)).fetchone()
        return int(found[0])

    def activate(self, code: str, machine: str, label: str = "", app_version: str = "") -> dict:
        """ผูกเครื่องกับรหัส แล้วคืน token ที่เซ็นแล้ว — ล้มจะ raise ValueError"""
        lic = self.find_by_code(code)
        problem = self.problem(lic)
        if problem:
            raise ValueError(problem)
        now = lf.iso(lf.utc_now())
        with self.lock, self.db:
            existing = self.db.execute(
                "SELECT * FROM activations WHERE license_id = ? AND machine = ?",
                (lic["id"], machine)).fetchone()
            if not (existing and existing["active"]):
                used = len(self.devices(lic["id"], active_only=True))
                if used >= lic["max_devices"]:
                    raise ValueError(
                        f"รหัสนี้ใช้ครบ {lic['max_devices']} เครื่องแล้ว — กด 'ปลดเครื่อง'"
                        " บนเครื่องเดิมก่อน หรือติดต่อผู้ขาย")
            if existing:
                self.db.execute(
                    "UPDATE activations SET active = 1, released = NULL, last_seen = ?,"
                    " label = ?, app_version = ? WHERE license_id = ? AND machine = ?",
                    (now, label, app_version, lic["id"], machine))
            else:
                self.db.execute(
                    "INSERT INTO activations (license_id, machine, label, first_seen,"
                    " last_seen, app_version) VALUES (?, ?, ?, ?, ?, ?)",
                    (lic["id"], machine, label, now, now, app_version))
        return self.issue_token(lic, machine)

    def heartbeat(self, token: str, machine: str, app_version: str = "") -> dict:
        """ต่ออายุ token — ตรวจกับฐานข้อมูลจริง ไม่เชื่อสิ่งที่อยู่ใน token อย่างเดียว"""
        payload = lf.read_token(self.public_key, token)
        if payload.get("machine") != machine:
            raise ValueError("license นี้ผูกกับเครื่องอื่น")
        lic = self.get_license(str(payload.get("lic", "")))
        problem = self.problem(lic)
        if problem:
            raise ValueError(problem)
        with self.lock, self.db:
            found = self.db.execute(
                "SELECT active FROM activations WHERE license_id = ? AND machine = ?",
                (lic["id"], machine)).fetchone()
            if not found or not found["active"]:
                raise ValueError("เครื่องนี้ถูกปลดออกจากรหัสแล้ว กรุณา activate ใหม่")
            self.db.execute(
                "UPDATE activations SET last_seen = ?, app_version = ?"
                " WHERE license_id = ? AND machine = ?",
                (lf.iso(lf.utc_now()), app_version, lic["id"], machine))
        return self.issue_token(lic, machine)

    def release(self, license_id: str, machine: str, by_admin: bool = False) -> None:
        """ปลดเครื่องออกจากรหัส — ลูกค้าปลดเองนับโควตาย้ายเครื่อง แอดมินปลดไม่นับ"""
        if not by_admin and self._moves_last_month(license_id) >= MAX_MOVES_PER_MONTH:
            raise ValueError(
                f"ย้ายเครื่องครบ {MAX_MOVES_PER_MONTH} ครั้งใน 30 วันแล้ว กรุณาติดต่อผู้ขาย")
        now = lf.iso(lf.utc_now())
        with self.lock, self.db:
            self.db.execute(
                "UPDATE activations SET active = 0, released = ?"
                " WHERE license_id = ? AND machine = ?", (now, license_id, machine))
            if not by_admin:
                self.db.execute("INSERT INTO releases (license_id, machine, at)"
                                " VALUES (?, ?, ?)", (license_id, machine, now))

    def release_all(self, license_id: str) -> None:
        with self.lock, self.db:
            self.db.execute("UPDATE activations SET active = 0 WHERE license_id = ?",
                            (license_id,))

    def issue_token(self, lic: dict, machine: str) -> dict:
        payload = {
            "lic": lic["id"],
            "sku": lic["sku"],
            "max_groups": lic["max_groups"],
            "expires": lic["expires"],
            "machine": machine,
            "issued": lf.iso(lf.utc_now()),
        }
        return {"token": lf.sign_token(self.key, payload), "license": payload}
