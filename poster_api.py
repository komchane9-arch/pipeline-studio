# -*- coding: utf-8 -*-
"""ที่อยู่ของสายโปสเตอร์ที่หน้าเว็บเรียก + ตัวเดินงาน (สเปค: SPEC-สายโปสเตอร์.md)

แยกไฟล์ออกมาจาก app.py โดยตั้งใจ — app.py ยาวเป็นหมื่นบรรทัดและทุกสายแตะ
ที่นี่แตะแค่ `app.include_router(poster_api.create_router())` บรรทัดเดียว

## ตัวเดินงาน — ทำทีละใบเสมอ

ChatGPT ใช้โปรไฟล์ Chrome ตัวเดียวร่วมกับสายคลิป (ล็อกร่วมกัน) ทำพร้อมกันหลายใบ
ก็ไม่เร็วขึ้น ได้แต่รอล็อก — จึงมีคนงานคนเดียว หยิบงานจากสองทาง

    กดเอง (manual)  → เข้าคิวทันที ทำก่อนงานอัตโนมัติ
    อัตโนมัติ        → เปิดสวิตช์ไว้ = หยิบใบแรกในกล่อง Poster/Caption/Comment
                       ที่ **ไม่มีป้ายแดงค้าง** มาทำ (ใบที่ล้มต้องให้คนดูก่อน
                       ไม่งั้นยิง ChatGPT ซ้ำใบเดิมวนไม่จบ เสียโควตาเปล่า)

นอกจากนั้นทุก 60 วินาทีไล่แตกใบ `-post` จากใบที่ดึงรูปเสร็จ (ไม่ขึ้นกับสวิตช์)
"""
from __future__ import annotations

import collections
import os
import subprocess
import threading
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

import gpt_customs
import poster_store as ps
import studio_shared

SETTINGS = studio_shared.DATA_DIR / "poster_settings.json"
PAGES = studio_shared.DATA_DIR / "poster_pages.json"
# โปรไฟล์ Chrome ของสายนี้ — แยกจากโปรไฟล์ ChatGPT/บอท เจ้าของล็อกอิน Facebook เอง
FB_PROFILE = studio_shared.DATA_DIR / "poster_fb_profile"
AUTO_BOXES = ("poster", "caption", "comment")

_lines: collections.deque = collections.deque(maxlen=200)
_queue: collections.deque = collections.deque()
_state = {"busy": "", "since": 0.0}
_wake = threading.Event()
_started = False


def log(message: str) -> None:
    line = f"{time.strftime('%H:%M:%S')} {message}"
    _lines.append(line)
    print(f"[โปสเตอร์] {line}", flush=True)


def settings() -> dict:
    def ensure(data: dict) -> None:            # ต้องคืน None — ค่าที่คืนจะถูกเขียนทับทั้งไฟล์
        data.setdefault("auto", False)

    return studio_shared.update_json(SETTINGS, ensure, default={})


# ---------------------------------------------------------------- เพจ

def pages() -> dict:
    def ensure(data: dict) -> None:
        data.setdefault("items", [])
        data.setdefault("selected", "")

    return studio_shared.update_json(PAGES, ensure, default={})


def _clean_page(url: str) -> str:
    url = str(url or "").strip().split("?")[0].rstrip("/")
    if not url.startswith(("https://www.facebook.com/", "https://facebook.com/",
                           "https://m.facebook.com/", "https://web.facebook.com/")):
        raise HTTPException(400, "ลิงก์เพจต้องขึ้นต้นด้วย https://www.facebook.com/…")
    return url.replace("://facebook.com/", "://www.facebook.com/").replace(
        "://m.facebook.com/", "://www.facebook.com/").replace(
        "://web.facebook.com/", "://www.facebook.com/")


# ---------------------------------------------------------------- คนงาน

def _next_auto() -> tuple[str, str] | None:
    if not settings().get("auto"):
        return None
    for card in sorted(ps.list_all(), key=lambda r: r.get("created_at", "")):
        if card.get("stage") in AUTO_BOXES and not card.get("error"):
            if gpt_customs.selected(card["stage"]):
                return card["id"], card["stage"]
    return None


def _worker() -> None:
    import poster_worker

    last_sweep = 0.0
    while True:
        try:
            if time.time() - last_sweep >= 60:
                last_sweep = time.time()
                ps.sweep(log=log)
            job = _queue.popleft() if _queue else _next_auto()
            if job:
                poster_id, box = job
                _state.update(busy=f"{poster_id} · {ps.STAGE_LABEL.get(box, box)}", since=time.time())
                try:
                    poster_worker.run_safe(poster_id, box, log=log)
                finally:
                    _state.update(busy="", since=0.0)
                continue
        except Exception as error:                               # noqa: BLE001
            # คนงานห้ามตายเงียบ — ตายแล้วสายทั้งสายหยุดโดยไม่มีใครรู้ (ข้อ 2.4)
            log(f"✕ ตัวเดินงานสะดุด: {error!r}")
        _wake.wait(20)
        _wake.clear()


def start() -> None:
    global _started
    if _started:
        return
    _started = True
    threading.Thread(target=_worker, name="poster-worker", daemon=True).start()


# ---------------------------------------------------------------- Chrome ของเพจ

def _chrome() -> str:
    for base in (os.environ.get("PROGRAMFILES", r"C:\Program Files"),
                 os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"),
                 os.environ.get("LOCALAPPDATA", "")):
        path = Path(base) / "Google/Chrome/Application/chrome.exe"
        if path.is_file():
            return str(path)
    raise HTTPException(500, "หา chrome.exe ไม่เจอในเครื่อง")


def open_fb_profile(url: str = "https://www.facebook.com/") -> None:
    """เปิด Chrome โปรไฟล์ของสายนี้ให้เจ้าของล็อกอินเอง — ระบบไม่กรอกรหัสผ่านเด็ดขาด

    เปิดเป็น Chrome ธรรมดา ไม่ผ่าน Playwright — หน้าล็อกอินของ Facebook/Google
    ปฏิเสธเบราว์เซอร์ที่ถูกควบคุมบ่อย และตอนล็อกอินไม่มีอะไรต้องให้ระบบกดเลย
    """
    FB_PROFILE.mkdir(parents=True, exist_ok=True)
    subprocess.Popen([_chrome(), f"--user-data-dir={FB_PROFILE}",
                      "--profile-directory=Default", "--window-position=80,60", url],
                     creationflags=getattr(subprocess, "DETACHED_PROCESS", 0))


# ---------------------------------------------------------------- ที่อยู่

class RunBody(BaseModel):
    box: str


class MoveBody(BaseModel):
    stage: str


class EditBody(BaseModel):
    caption: str | None = None
    comments: list[str] | None = None
    shopee_url: str | None = None
    lazada_url: str | None = None


class CustomBody(BaseModel):
    name: str = ""
    url: str = ""


class PageBody(BaseModel):
    name: str = ""
    url: str = ""


class AutoBody(BaseModel):
    on: bool


def _card(card: dict) -> dict:
    return {k: card.get(k) for k in (
        "id", "source_id", "name", "product_name", "stage", "images", "poster_images",
        "caption", "comments", "shopee_url", "lazada_url", "error", "posted", "page",
        "poster_custom", "caption_custom", "comment_custom", "created_at", "updated_at")}


def create_router() -> APIRouter:
    router = APIRouter(prefix="/api/poster")

    @router.get("/board")
    def board():
        cards = [_card(c) for c in ps.list_all()]
        return {
            "stages": [{"key": k, "label": ps.STAGE_LABEL[k]} for k in ps.STAGES],
            "cards": cards,
            "customs": gpt_customs.load(),
            "pages": pages(),
            "auto": bool(settings().get("auto")),
            "busy": _state["busy"],
            "busy_seconds": int(time.time() - _state["since"]) if _state["since"] else 0,
            "queue": [f"{a} · {ps.STAGE_LABEL.get(b, b)}" for a, b in _queue],
            "lines": list(_lines)[-40:],
            "since": ps.start_date(),
        }

    @router.get("/file/{poster_id}/{sub}/{name}")
    def file(poster_id: str, sub: str, name: str):
        if sub not in ("images", "poster") or "/" in name or "\\" in name or ".." in name:
            raise HTTPException(404)
        path = ps.folder(poster_id) / sub / name
        if not path.is_file():
            raise HTTPException(404, "ไม่พบไฟล์")
        return FileResponse(path)

    @router.post("/{poster_id}/run")
    def run(poster_id: str, body: RunBody):
        card = ps.load(poster_id)
        if not card:
            raise HTTPException(404, f"ไม่พบใบ {poster_id}")
        if body.box == "facebook":
            raise HTTPException(409, "กล่อง Facebook ยังไม่เปิดให้ลงอัตโนมัติ — "
                                     "ต้องล็อกอินโปรไฟล์เพจก่อน แล้วค่อยสร้างขั้นลงเพจจากหน้าจริง")
        if body.box not in AUTO_BOXES:
            raise HTTPException(400, f"ไม่รู้จักกล่อง {body.box}")
        if card.get("stage") != body.box:
            raise HTTPException(409, f"ใบนี้อยู่กล่อง {ps.STAGE_LABEL.get(card.get('stage'))} "
                                     f"ไม่ใช่ {ps.STAGE_LABEL[body.box]}")
        if not gpt_customs.selected(body.box):
            raise HTTPException(409, f"กล่อง {gpt_customs.BOXES[body.box]} ยังไม่ได้เลือก ChatGPT custom")
        if (poster_id, body.box) in _queue or _state["busy"].startswith(poster_id):
            return {"ok": True, "note": "ใบนี้อยู่ในคิวแล้ว"}
        ps.change(poster_id, lambda d: d.update(error=""))
        _queue.append((poster_id, body.box))
        _wake.set()
        return {"ok": True, "note": f"เข้าคิวแล้ว (ลำดับที่ {len(_queue)})"}

    @router.post("/{poster_id}/move")
    def move(poster_id: str, body: MoveBody):
        try:
            return _card(ps.move(poster_id, body.stage))
        except ps.PosterError as error:
            raise HTTPException(409, str(error)) from error

    @router.put("/{poster_id}")
    def edit(poster_id: str, body: EditBody):
        fields = {k: v for k, v in body.model_dump().items() if v is not None}
        if "comments" in fields:
            fields["comments"] = [c.strip() for c in fields["comments"] if c.strip()]

        def mutate(data: dict) -> None:
            data.update(fields)

        try:
            return _card(ps.change(poster_id, mutate))
        except ps.PosterError as error:
            raise HTTPException(404, str(error)) from error

    @router.post("/auto")
    def auto(body: AutoBody):
        studio_shared.update_json(SETTINGS, lambda d: d.update(auto=body.on), default={})
        log("เปิดโหมดอัตโนมัติ" if body.on else "ปิดโหมดอัตโนมัติ")
        _wake.set()
        return {"auto": body.on}

    @router.post("/customs/{box}")
    def custom_add(box: str, body: CustomBody):
        try:
            return gpt_customs.add(box, body.name, body.url)
        except gpt_customs.CustomError as error:
            raise HTTPException(400, str(error)) from error

    @router.post("/customs/{box}/{custom_id}/use")
    def custom_use(box: str, custom_id: str):
        try:
            return gpt_customs.use(box, custom_id)
        except gpt_customs.CustomError as error:
            raise HTTPException(400, str(error)) from error

    @router.delete("/customs/{box}/{custom_id}")
    def custom_drop(box: str, custom_id: str):
        try:
            gpt_customs.drop(box, custom_id)
            return {"ok": True}
        except gpt_customs.CustomError as error:
            raise HTTPException(400, str(error)) from error

    @router.post("/pages")
    def page_add(body: PageBody):
        url = _clean_page(body.url)
        name = body.name.strip() or url.rsplit("/", 1)[-1]
        row = {"id": os.urandom(4).hex(), "name": name[:80], "url": url}

        def mutate(data: dict) -> None:
            items = data.setdefault("items", [])
            if any(item["url"] == url for item in items):
                raise HTTPException(400, "ผูกเพจนี้ไว้แล้ว")
            items.append(row)
            if not data.get("selected"):
                data["selected"] = row["id"]

        return studio_shared.update_json(PAGES, mutate, default={})

    @router.post("/pages/{page_id}/use")
    def page_use(page_id: str):
        def mutate(data: dict) -> None:
            if not any(i["id"] == page_id for i in data.get("items", [])):
                raise HTTPException(404, "ไม่พบเพจนี้")
            data["selected"] = page_id

        return studio_shared.update_json(PAGES, mutate, default={})

    @router.delete("/pages/{page_id}")
    def page_drop(page_id: str):
        def mutate(data: dict) -> None:
            if data.get("selected") == page_id:
                raise HTTPException(409, "ลบเพจที่ใช้อยู่ไม่ได้ — เลือกเพจอื่นก่อน")
            data["items"] = [i for i in data.get("items", []) if i["id"] != page_id]

        return studio_shared.update_json(PAGES, mutate, default={})

    @router.post("/fb-profile/open")
    def fb_profile_open():
        chosen = next((i for i in pages().get("items", []) if i["id"] == pages().get("selected")), None)
        open_fb_profile(chosen["url"] if chosen else "https://www.facebook.com/")
        return {"ok": True, "note": "เปิด Chrome โปรไฟล์ของสายโปสเตอร์แล้ว — ล็อกอิน Facebook เองได้เลย"}

    return router
