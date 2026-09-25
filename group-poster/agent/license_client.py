"""ตัวตรวจ license ฝั่งลูกค้า — activate, heartbeat และช่วงใช้ออฟไลน์

หลักการ:
- ตรวจลายเซ็นของ token ในเครื่องได้เสมอด้วย public key จาก config.json
- ต่ออายุกับ server ทุก 30 นาที ถ้า server ติดต่อไม่ได้ ใช้ต่อได้อีก 72 ชั่วโมง
  นับจากครั้งล่าสุดที่ server ตอบว่าใช้ได้ (เครื่องเจ้าของดับ ลูกค้าไม่ควรหยุดงานทันที)
- ถ้า server ตอบกลับชัดเจนว่า "ระงับ/หมดอายุ/ปลดเครื่องแล้ว" ให้หยุดทันที ไม่รอ 72 ชั่วโมง
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
import sys
import threading
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common import license_format as lf  # noqa: E402

APP_VERSION = "0.1.0"
GRACE = timedelta(hours=72)
HEARTBEAT_SECONDS = 30 * 60
# salt คงที่ของสินค้า — กันไม่ให้ machine_id ที่ส่งไป server เอาไปเทียบกับที่อื่นได้
MACHINE_SALT = "group-poster/v1"


def _windows_machine_guid() -> str:
    try:
        out = subprocess.run(
            ["reg", "query", r"HKLM\SOFTWARE\Microsoft\Cryptography", "/v", "MachineGuid"],
            capture_output=True, text=True, timeout=5,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        ).stdout
        return out.strip().split()[-1] if "MachineGuid" in out else ""
    except (OSError, subprocess.SubprocessError, IndexError):
        return ""


def _linux_machine_id() -> str:
    for path in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
        try:
            return Path(path).read_text().strip()
        except OSError:
            continue
    return ""


def machine_id() -> str:
    """รหัสประจำเครื่องแบบ hash — ไม่ส่งค่าดิบของเครื่องลูกค้าออกไป"""
    raw = os.environ.get("GP_MACHINE_ID") or ""
    if not raw:
        raw = _windows_machine_guid() if os.name == "nt" else _linux_machine_id()
    if not raw:
        raw = f"{uuid.getnode():x}"
    return hashlib.sha256(f"{MACHINE_SALT}:{raw}".encode()).hexdigest()[:40]


def machine_label() -> str:
    return f"{platform.node() or 'pc'} ({platform.system()})"[:80]


class LicenseClient:
    def __init__(self, config: dict, data_dir: Path,
                 http: Callable[..., httpx.Response] | None = None,
                 machine: str | None = None) -> None:
        self.server_url = str(config.get("server_url", "")).rstrip("/")
        self.public = lf.public_key_from_text(config["public_key"])
        self.file = Path(data_dir) / "license.json"
        self.file.parent.mkdir(parents=True, exist_ok=True)
        self.machine = machine or machine_id()
        self._http = http
        self.lock = threading.RLock()
        self.state = self._load()
        self._stop = threading.Event()

    # ------------------------------------------------------------ ไฟล์

    def _load(self) -> dict:
        try:
            return json.loads(self.file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _save(self) -> None:
        temp = self.file.with_suffix(".tmp")
        temp.write_text(json.dumps(self.state, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temp, self.file)

    # ------------------------------------------------------------ http

    def _post(self, path: str, body: dict) -> dict:
        url = f"{self.server_url}{path}"
        if self._http:
            response = self._http("POST", url, json=body)
        else:
            response = httpx.post(url, json=body, timeout=15)
        if response.status_code >= 400:
            try:
                detail = response.json().get("detail")
            except ValueError:
                detail = ""
            raise PermissionError(detail or f"server ตอบกลับ {response.status_code}")
        return response.json()

    # ------------------------------------------------------------ คำสั่ง

    def activate(self, code: str) -> dict:
        result = self._post("/v1/activate", {
            "code": code, "machine": self.machine,
            "label": machine_label(), "app_version": APP_VERSION,
        })
        # ตรวจเองอีกชั้นว่า server ที่ตอบคือของผู้ขายจริง (ลายเซ็นตรง public key)
        lf.check_token(self.public, result["token"], self.machine)
        with self.lock:
            self.state = {"token": result["token"], "last_ok": lf.iso(lf.utc_now()),
                          "error": "", "revoked": False}
            self._save()
        return self.status()

    def heartbeat(self) -> dict:
        with self.lock:
            token = self.state.get("token")
        if not token:
            return self.status()
        try:
            result = self._post("/v1/heartbeat", {
                "token": token, "machine": self.machine, "app_version": APP_VERSION})
            lf.check_token(self.public, result["token"], self.machine)
            with self.lock:
                self.state.update(token=result["token"], last_ok=lf.iso(lf.utc_now()),
                                  error="", revoked=False)
                self._save()
        except PermissionError as error:
            # server ตอบกลับมาแล้วว่าใช้ไม่ได้ = คำตอบสุดท้าย ไม่ใช่เน็ตหลุด
            with self.lock:
                self.state.update(error=str(error), revoked=True)
                self._save()
        except (httpx.HTTPError, OSError, ValueError, KeyError) as error:
            with self.lock:
                self.state["error"] = f"ติดต่อ server ไม่ได้ ({type(error).__name__})"
                self._save()
        except lf.LicenseError as error:
            with self.lock:
                self.state.update(error=str(error), revoked=True)
                self._save()
        return self.status()

    def deactivate(self) -> None:
        with self.lock:
            token = self.state.get("token")
        if token:
            self._post("/v1/deactivate", {
                "token": token, "machine": self.machine, "app_version": APP_VERSION})
        with self.lock:
            self.state = {}
            self._save()

    # ------------------------------------------------------------ สถานะ

    def status(self, now: datetime | None = None) -> dict:
        now = now or lf.utc_now()
        with self.lock:
            state = dict(self.state)
        base = {"active": False, "machine": self.machine, "server_url": self.server_url,
                "app_version": APP_VERSION, "message": "", "license": None}
        token = state.get("token")
        if not token:
            return {**base, "message": "ยังไม่ได้ใส่รหัส"}
        try:
            payload = lf.check_token(self.public, token, self.machine, now)
        except lf.LicenseError as error:
            return {**base, "message": str(error)}
        base["license"] = payload
        if state.get("revoked"):
            return {**base, "message": state.get("error") or "license ใช้ไม่ได้แล้ว"}
        last_ok = lf.parse_iso(state.get("last_ok") or payload["issued"])
        offline_until = last_ok + GRACE
        base["offline_until"] = lf.iso(offline_until)
        if now > offline_until:
            return {**base, "message": "ติดต่อ server ไม่ได้เกิน 72 ชั่วโมง กรุณาต่ออินเทอร์เน็ต"}
        return {**base, "active": True, "message": state.get("error") or "ใช้งานได้"}

    def require(self) -> dict:
        """เรียกก่อนเริ่มงานทุกครั้ง — ใช้ไม่ได้จะ raise PermissionError"""
        status = self.status()
        if not status["active"]:
            raise PermissionError(status["message"])
        return status["license"]

    # ------------------------------------------------------------ เบื้องหลัง

    def start_background(self) -> None:
        # ต่ออายุครั้งแรกในเธรดด้วย — server ช้าหรือดับ ต้องไม่ทำให้โปรแกรมเปิดช้า
        def loop() -> None:
            self.heartbeat()
            while not self._stop.wait(HEARTBEAT_SECONDS):
                self.heartbeat()

        threading.Thread(target=loop, name="license-heartbeat", daemon=True).start()

    def stop_background(self) -> None:
        self._stop.set()
