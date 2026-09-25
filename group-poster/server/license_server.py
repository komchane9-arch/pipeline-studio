"""License server — รันบนเครื่องหลักของเรา (เปิดตลอด)

    python server/license_server.py              # ฟังที่ 127.0.0.1:8870
    GP_SERVER_PORT=9000 python server/license_server.py

ฟังแค่ 127.0.0.1 โดยตั้งใจ ให้ Cloudflare Tunnel เป็นทางเดียวที่คนนอกเข้าถึงได้
(ดู README ส่วน "เปิดให้ลูกค้าเชื่อมต่อ") ไม่ต้องเปิด port ที่เราเตอร์

ห้ามรวมเข้ากับ app.py ของ Pipeline Studio — ถ้าตัวนี้โดนโจมตี
ต้องไม่ลามไปถึงมือถือและบัญชีที่ใช้ทำงานจริง
"""

from __future__ import annotations

import os
import sys
import threading
import time
from collections import defaultdict, deque
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import FastAPI, HTTPException, Request  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

from common import license_format as lf  # noqa: E402
from server.store import Store  # noqa: E402

# ลองรหัสผิดได้ไม่เกินนี้ต่อ IP ต่อ 10 นาที — รหัส 16 ตัวจากชุด 31 ตัวเดาไม่ได้อยู่แล้ว
# แต่ยังกันคนยิงถล่มจนฐานข้อมูลช้า
ACTIVATE_LIMIT = 20
ACTIVATE_WINDOW = 600.0


class ActivateBody(BaseModel):
    code: str = Field(max_length=64)
    machine: str = Field(min_length=16, max_length=128)
    label: str = Field(default="", max_length=80)
    app_version: str = Field(default="", max_length=32)


class TokenBody(BaseModel):
    token: str = Field(max_length=4096)
    machine: str = Field(min_length=16, max_length=128)
    app_version: str = Field(default="", max_length=32)


def create_app(store: Store | None = None) -> FastAPI:
    store = store or Store()
    app = FastAPI(title="Group Poster License Server", docs_url=None, redoc_url=None)
    hits: dict[str, deque] = defaultdict(deque)
    hits_lock = threading.Lock()

    def client_ip(request: Request) -> str:
        # ผ่าน Cloudflare Tunnel ทุก request จะมาจาก 127.0.0.1 — IP จริงอยู่ในหัวนี้
        return (request.headers.get("cf-connecting-ip")
                or (request.client.host if request.client else "unknown"))

    def rate_limit(request: Request) -> None:
        now = time.monotonic()
        ip = client_ip(request)
        with hits_lock:
            queue = hits[ip]
            while queue and now - queue[0] > ACTIVATE_WINDOW:
                queue.popleft()
            if len(queue) >= ACTIVATE_LIMIT:
                raise HTTPException(429, "ลองบ่อยเกินไป กรุณารอสักครู่แล้วลองใหม่")
            queue.append(now)

    @app.get("/health")
    def health() -> dict:
        return {"ok": True, "time": lf.iso(lf.utc_now())}

    @app.get("/v1/public-key")
    def public_key() -> dict:
        return {"public_key": store.public_key_text()}

    @app.post("/v1/activate")
    def activate(body: ActivateBody, request: Request) -> dict:
        rate_limit(request)
        try:
            return store.activate(body.code, body.machine, body.label, body.app_version)
        except ValueError as error:
            raise HTTPException(403, str(error)) from error

    @app.post("/v1/heartbeat")
    def heartbeat(body: TokenBody) -> dict:
        try:
            return store.heartbeat(body.token, body.machine, body.app_version)
        except (ValueError, lf.LicenseError) as error:
            raise HTTPException(403, str(error)) from error

    @app.post("/v1/deactivate")
    def deactivate(body: TokenBody) -> dict:
        try:
            payload = lf.read_token(store.public_key, body.token)
            if payload.get("machine") != body.machine:
                raise ValueError("license นี้ผูกกับเครื่องอื่น")
            store.release(str(payload["lic"]), body.machine)
        except (ValueError, lf.LicenseError) as error:
            raise HTTPException(403, str(error)) from error
        return {"ok": True}

    return app


def main() -> None:
    import uvicorn

    port = int(os.environ.get("GP_SERVER_PORT", "8870"))
    host = os.environ.get("GP_SERVER_HOST", "127.0.0.1")
    store = Store()
    print(f"License server: http://{host}:{port}  (ข้อมูลอยู่ที่ {store.data_dir})")
    uvicorn.run(create_app(store), host=host, port=port)


if __name__ == "__main__":
    main()
