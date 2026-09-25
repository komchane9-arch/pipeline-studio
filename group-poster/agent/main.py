"""Group Poster — โปรแกรมฝั่งลูกค้า

    python agent/main.py            # แล้วเปิด http://127.0.0.1:8890

ฟังที่ 127.0.0.1 เท่านั้น ห้ามเปิดให้เครื่องอื่นในวง LAN เข้า
เพราะหน้านี้สั่งมือถือที่ล็อกอิน Facebook ของลูกค้าไว้ได้ทั้งเครื่อง
"""

from __future__ import annotations

import json
import os
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import FastAPI, File, Form, HTTPException, UploadFile  # noqa: E402
from fastapi.responses import FileResponse  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from agent import jobs as jobs_mod  # noqa: E402
from agent.license_client import LicenseClient  # noqa: E402

HERE = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("GP_AGENT_DATA") or HERE / "data")
CONFIG_FILE = Path(os.environ.get("GP_AGENT_CONFIG") or HERE / "config.json")

# ระยะห่างขั้นต่ำระหว่างกลุ่ม — ลูกค้าตั้งให้ห่างขึ้นได้ แต่ถี่กว่านี้ไม่ได้
# ถี่เกินคือทางลัดไปโดน Facebook ตีเป็นสแปม ซึ่งคนที่เสียคือบัญชีของลูกค้าเอง
MIN_GAP = 15.0
MAX_GAP = 600.0
MAX_IMAGES = 3
MAX_IMAGE_BYTES = 15 * 1024 * 1024
IMAGE_TYPES = {".jpg", ".jpeg", ".png", ".webp"}


class CodeBody(BaseModel):
    code: str


def load_config() -> dict:
    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise SystemExit(
            f"อ่าน {CONFIG_FILE} ไม่ได้ — ไฟล์นี้ต้องได้จากผู้ขาย"
            " (สร้างด้วย server/admin.py agent-config)") from error


def create_app(license_client: LicenseClient | None = None,
               runner: jobs_mod.JobRunner | None = None,
               adb: str | None = None, background: bool = True) -> FastAPI:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    config = load_config() if license_client is None else {}
    client = license_client or LicenseClient(config, DATA_DIR)
    runner = runner or jobs_mod.JobRunner(DATA_DIR / "uploads")
    adb_path = adb or jobs_mod.find_adb(config.get("adb", ""))
    app = FastAPI(title="Group Poster", docs_url=None, redoc_url=None)

    if background:
        @app.on_event("startup")
        def _start() -> None:
            client.start_background()

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(HERE / "web" / "index.html")

    @app.get("/api/license")
    def license_status() -> dict:
        return client.status()

    @app.post("/api/license/activate")
    def activate(body: CodeBody) -> dict:
        try:
            return client.activate(body.code)
        except PermissionError as error:
            raise HTTPException(403, str(error)) from error
        except Exception as error:  # noqa: BLE001
            raise HTTPException(502, f"ติดต่อ server ไม่ได้: {error}") from error

    @app.post("/api/license/refresh")
    def refresh() -> dict:
        return client.heartbeat()

    @app.post("/api/license/deactivate")
    def deactivate() -> dict:
        if runner.busy():
            raise HTTPException(409, "มีงานกำลังโพสต์อยู่ หยุดงานก่อนปลดเครื่อง")
        try:
            client.deactivate()
        except PermissionError as error:
            raise HTTPException(403, str(error)) from error
        except Exception as error:  # noqa: BLE001
            raise HTTPException(502, f"ติดต่อ server ไม่ได้: {error}") from error
        return client.status()

    @app.get("/api/devices")
    def devices() -> dict:
        return {"adb": adb_path, "devices": jobs_mod.list_devices(adb_path)}

    @app.post("/api/jobs")
    async def start_job(
        serial: str = Form(...),
        caption: str = Form(...),
        groups: str = Form(...),
        comment: str = Form(""),
        gap_min: float = Form(15.0),
        gap_max: float = Form(20.0),
        dry_run: bool = Form(False),
        images: list[UploadFile] = File(...),
    ) -> dict:
        try:
            lic = client.require()
        except PermissionError as error:
            raise HTTPException(403, str(error)) from error

        ids, bad = jobs_mod.parse_groups(groups)
        if bad:
            raise HTTPException(400, "ใช้ได้เฉพาะเลข ID กลุ่ม หรือลิงก์ที่เป็นเลข: " + ", ".join(bad[:5]))
        if not ids:
            raise HTTPException(400, "ยังไม่ได้ใส่กลุ่ม")
        limit = int(lic.get("max_groups") or 0)
        if limit and len(ids) > limit:
            raise HTTPException(403, f"แพ็กเกจนี้โพสต์ได้ไม่เกิน {limit} กลุ่มต่อรอบ (ใส่มา {len(ids)})")
        if not caption.strip():
            raise HTTPException(400, "ยังไม่ได้ใส่ข้อความโพสต์")
        if not serial:
            raise HTTPException(400, "ยังไม่ได้เลือกมือถือ")
        if not images or len(images) > MAX_IMAGES:
            raise HTTPException(400, f"แนบรูปได้ 1-{MAX_IMAGES} รูป")

        low = max(MIN_GAP, min(gap_min, gap_max))
        high = min(MAX_GAP, max(low, gap_max))

        folder = DATA_DIR / "uploads" / secrets.token_hex(4)
        folder.mkdir(parents=True, exist_ok=True)
        saved: list[Path] = []
        for index, upload in enumerate(images, start=1):
            suffix = Path(upload.filename or "").suffix.lower()
            if suffix not in IMAGE_TYPES:
                raise HTTPException(400, f"ไฟล์ {upload.filename} ไม่ใช่รูป (jpg/png/webp)")
            data = await upload.read()
            if len(data) > MAX_IMAGE_BYTES:
                raise HTTPException(400, f"รูป {upload.filename} ใหญ่เกิน 15 MB")
            # ตั้งชื่อใหม่เอง ไม่ใช้ชื่อไฟล์ที่ส่งมา — กันชื่อแปลกๆ พาออกนอกโฟลเดอร์
            path = folder / f"img{index}{suffix}"
            path.write_bytes(data)
            saved.append(path)

        try:
            job = runner.start(adb=adb_path, serial=serial, images=saved, caption=caption,
                               comment=comment, groups=ids, gap=(low, high), dry_run=dry_run)
        except RuntimeError as error:
            raise HTTPException(409, str(error)) from error
        return job.snapshot()

    @app.get("/api/jobs/current")
    def current(since: int = 0) -> dict:
        job = runner.current
        return {"job": job.snapshot(since) if job else None}

    @app.post("/api/jobs/{job_id}/stop")
    def stop(job_id: str) -> dict:
        if not runner.stop(job_id):
            raise HTTPException(404, "ไม่พบงาน")
        return {"ok": True}

    return app


def main() -> None:
    import uvicorn

    port = int(os.environ.get("GP_AGENT_PORT", "8890"))
    print(f"Group Poster เปิดที่ http://127.0.0.1:{port}")
    uvicorn.run(create_app(), host="127.0.0.1", port=port)


if __name__ == "__main__":
    main()
