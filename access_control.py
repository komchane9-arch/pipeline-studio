"""สิทธิ์เข้าใช้จากมือถือ — ยกระบบเดียวกับ 7.web app มาทั้งชุด

หลักการ: เครื่องที่รันโปรแกรมนี้คือ "เครื่องหลัก" มีสิทธิ์เต็มเสมอ
ส่วนมือถือ/เครื่องอื่นในวง LAN ที่เปิดเว็บเข้ามาจะได้สถานะ `pending`
จนกว่าเครื่องหลักจะกด "อนุญาต" ให้ — กันคนอื่นในวงเน็ตเดียวกันเปิดมาสั่งมือถือเรา

ทำไมไม่ใช้รหัสผ่าน: ผู้ใช้คนเดียวกันทั้งคอมและมือถือ การพิมพ์รหัสบนมือถือทุกครั้ง
กวนกว่าเดิม และรหัสที่จำง่ายพอจะพิมพ์บนมือถือก็เดาง่ายพอกัน — อนุมัติทีละเครื่อง
จากคอมจึงทั้งง่ายกว่าและแน่นกว่า
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import secrets
import socket
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

ACCESS_COOKIE = "pipeline_studio_access"
ACCESS_TOKEN_HEADER = "x-device-token"


def now_text() -> str:
    return datetime.now().isoformat(timespec="seconds")


class AccessStore:
    """ทะเบียนอุปกรณ์ที่เคยเข้ามา — เก็บเป็นไฟล์ JSON ข้าง data/"""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.lock = threading.RLock()
        self.devices: dict[str, dict[str, Any]] = self._load()

    def _load(self) -> dict[str, dict[str, Any]]:
        if not self.path.is_file():
            return {}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        records: dict[str, dict[str, Any]] = {}
        for item in payload.get("devices", []):
            # ไม่มี token_hash = ระเบียนพัง อนุมัติไปก็เทียบโทเคนไม่ได้ ทิ้งไปเลย
            if isinstance(item, dict) and item.get("id") and item.get("token_hash"):
                records[str(item["id"])] = item
        return records

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        payload = {
            "devices": sorted(
                self.devices.values(),
                key=lambda item: item.get("created_at", ""),
                reverse=True,
            )
        }
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temporary.replace(self.path)

    # ------------------------------------------------------------- อ่าน/เขียน

    def find_by_token(self, token: str) -> dict[str, Any] | None:
        if not token:
            return None
        hashed = token_hash(token)
        with self.lock:
            return next(
                (
                    record
                    for record in self.devices.values()
                    # compare_digest กัน timing attack เวลาเทียบโทเคน
                    if secrets.compare_digest(str(record.get("token_hash", "")), hashed)
                ),
                None,
            )

    def create(self, token: str, ip: str, user_agent: str) -> dict[str, Any]:
        record = {
            "id": uuid.uuid4().hex[:12],
            "token_hash": token_hash(token),
            "device": device_label(user_agent),
            "ip": ip,
            "user_agent": user_agent,
            "status": "pending",
            "created_at": now_text(),
            "last_seen": now_text(),
            "approved_at": None,
            "revoked_at": None,
        }
        with self.lock:
            self.devices[record["id"]] = record
            self.save()
        return record

    def touch(self, record: dict[str, Any], ip: str, user_agent: str,
              persist: bool = False) -> None:
        with self.lock:
            record["last_seen"] = now_text()
            record["ip"] = ip
            record["user_agent"] = user_agent
            record["device"] = device_label(user_agent)
            if persist:
                self.save()

    def set_status(self, device_id: str, status: str) -> dict[str, Any] | None:
        with self.lock:
            record = self.devices.get(device_id)
            if record is None:
                return None
            record["status"] = status
            if status == "approved":
                record["approved_at"] = now_text()
                record["revoked_at"] = None
            elif status == "revoked":
                record["revoked_at"] = now_text()
                # เปลี่ยนโทเคนทิ้งด้วย ไม่งั้นเครื่องที่ถูกถอนสิทธิ์ยังถือโทเคนเดิมอยู่
                # แล้วถ้าอนุมัติใหม่ทีหลังมันจะกลับมาใช้ได้ทันทีโดยไม่ต้องขอใหม่
                record["token_hash"] = token_hash(secrets.token_urlsafe(32))
            self.save()
            return record

    def purge_revoked(self) -> int:
        with self.lock:
            removed = [
                key for key, record in self.devices.items()
                if record.get("status") == "revoked"
            ]
            for key in removed:
                self.devices.pop(key, None)
            if removed:
                self.save()
        return len(removed)

    def listing(self) -> list[dict[str, Any]]:
        with self.lock:
            return [
                public_device(record)
                for record in sorted(
                    self.devices.values(),
                    key=lambda item: item.get("last_seen", ""),
                    reverse=True,
                )
            ]


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def public_device(record: dict[str, Any]) -> dict[str, Any]:
    """ตัด token_hash ออกก่อนส่งให้หน้าเว็บเสมอ"""
    return {
        key: record.get(key)
        for key in (
            "id", "device", "ip", "status",
            "created_at", "last_seen", "approved_at", "revoked_at",
        )
    }


def device_label(user_agent: str) -> str:
    value = (user_agent or "").lower()
    for key, label in (
        ("iphone", "iPhone"), ("ipad", "iPad"), ("android", "Android"),
        ("windows", "Windows"), ("macintosh", "Mac"), ("mac os", "Mac"),
        ("linux", "Linux"),
    ):
        if key in value:
            return label
    return "อุปกรณ์ไม่ทราบชนิด"


def client_ip(request) -> str:
    return request.client.host if request.client else "unknown"


def is_local_request(request) -> bool:
    """เครื่องหลัก = เบราว์เซอร์บนคอมเครื่องนี้เท่านั้น

    คำขอที่วิ่งผ่าน proxy/tunnel จะมีเฮดเดอร์ forwarded ติดมาเสมอ จึงตัดออกก่อน
    ไม่ให้ปลอมเฮดเดอร์แล้วกลายเป็นเครื่องหลัก (uvicorn เขียน client เป็น
    127.0.0.1 ได้ถ้าเชื่อ X-Forwarded-For)
    """
    if any(
        header in request.headers
        for header in ("x-forwarded-for", "forwarded", "x-real-ip")
    ):
        return False
    host = client_ip(request)
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return host.lower() == "localhost"


def lan_ip() -> str | None:
    """IP ของเครื่องนี้ในวง LAN — ไว้ทำลิงก์/QR ให้มือถือสแกน

    ต่อ UDP ไปที่อยู่นอกวง (ไม่ได้ส่งจริง) เพื่อให้ระบบเลือก interface ที่ใช้ออกเน็ต
    แม่นกว่าการอ่าน hostname ซึ่งได้ IP ของ VPN/virtual adapter ปนมา
    """
    candidates: list[str] = []
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("10.255.255.255", 1))
            candidates.append(probe.getsockname()[0])
    except OSError:
        pass
    try:
        candidates.extend(
            item[4][0]
            for item in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)
        )
    except OSError:
        pass
    for candidate in candidates:
        try:
            address = ipaddress.ip_address(candidate)
        except ValueError:
            continue
        if address.is_private and not address.is_loopback and not address.is_link_local:
            return candidate
    return None
