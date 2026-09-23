# -*- coding: utf-8 -*-
"""ที่อยู่ของสายโปสเตอร์ที่หน้าเว็บเรียก + ตัวเดินงาน (สเปค: SPEC-สายโปสเตอร์.md)

แยกไฟล์ออกมาจาก app.py โดยตั้งใจ — app.py ยาวเป็นหมื่นบรรทัดและทุกสายแตะ
ที่นี่แตะแค่ `app.include_router(poster_api.create_router())` บรรทัดเดียว

## หลักการของกล่อง — เหมือนกระดานสายคลิป (เจ้าของสั่ง 23 ก.ย. 2569)

    ใบเข้ากล่องไหน ระบบทำของกล่องนั้นเอง → ได้ของแล้วรอตรวจ → ✅ อนุมัติ = ไปกล่องถัดไป
    ☐ อัตโนมัติบนหัวกล่อง = อนุมัติแทนคนทุกใบที่รอตรวจในกล่องนั้น ยกเว้นใบที่พักไว้

**การทำของเดินเองเสมอ ไม่ต้องเปิดสวิตช์** — เหมือนสายคลิปที่อนุมัติชุดรูปแล้ว
สตอรีบอร์ดเริ่มทำเอง ส่วนที่คุมค่าใช้จ่ายคือด่านอนุมัติ: ใบใหม่ทุกใบหยุดรอที่
กล่อง Picture-post ก่อน ไม่มีใครอนุมัติ = ไม่ยิง ChatGPT สักครั้ง

## คนงาน — ทำทีละใบเสมอ

ChatGPT ใช้โปรไฟล์ Chrome ตัวเดียวร่วมกับสายคลิป (ล็อกร่วมกัน) ทำพร้อมกันหลายใบ
ก็ไม่เร็วขึ้น ได้แต่รอล็อก ลำดับที่หยิบ: ✏️ สั่งแก้ที่คนกดไว้ก่อน → ใบที่รอคิวทำ
ตามลำดับที่เข้ากล่อง · ใบที่ล้มหยุดอยู่ที่ป้ายแดง ไม่ถูกหยิบซ้ำเอง (กันยิงซ้ำวนไม่จบ)

นอกจากนั้นทุก 60 วินาทีไล่แตกใบ `-post` จากใบที่ดึงรูปเสร็จ
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
# กล่องที่มีปุ่ม ☐ อัตโนมัติ — กล่อง Facebook ยังไม่มี เพราะขั้นลงเพจยังไม่เปิด
# (ถ้าเปิดทีหลังต้องถามก่อนเปิดเหมือนกองโพสต์ของสายคลิป เพราะลงแล้วถอนไม่ได้)
AUTO_BOXES = ("picture", "poster", "caption", "comment")
STOCK_TARGET = 10          # เส้นวัดเดียวกับกระดานสายคลิป (clip_board.STOCK_TARGET)

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
        # เดิมเป็นสวิตช์รวมตัวเดียว (True/False) — แปลงเป็นรายกล่อง ปิดทุกกล่องไว้ก่อน
        if not isinstance(data.get("auto"), dict):
            data["auto"] = {}
        for box in AUTO_BOXES:
            data["auto"].setdefault(box, False)

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

def _auto_approve() -> None:
    """☐ อัตโนมัติ — อนุมัติแทนคนทุกใบที่รอตรวจในกล่องที่เปิดไว้ ยกเว้นใบที่พัก"""
    auto = settings()["auto"]
    for card in ps.list_all():
        box = card.get("stage")
        if auto.get(box) and card.get("status") == "review" and not card.get("parked"):
            try:
                ps.approve(card["id"])
                log(f"☑ อนุมัติอัตโนมัติ {card['id']} กล่อง {ps.STAGE_LABEL[box]}")
            except ps.PosterError as error:
                log(f"✕ อนุมัติอัตโนมัติ {card['id']} ไม่ได้: {error}")


def _next_make():
    """ใบถัดไปที่ต้องทำของ — รอคิวนานสุดก่อน ข้ามใบที่พักไว้/กล่องที่ยังไม่เลือก custom"""
    rows = [c for c in ps.list_all()
            if c.get("stage") in ps.MAKE_BOXES and c.get("status") == "queued"
            and not c.get("parked")]
    for card in sorted(rows, key=lambda r: r.get("updated_at", "")):
        if gpt_customs.selected(card["stage"]):
            return card["id"], card["stage"], ""
    return None


def _worker() -> None:
    import poster_worker

    last_sweep = 0.0
    while True:
        try:
            if time.time() - last_sweep >= 60:
                last_sweep = time.time()
                ps.sweep(log=log)
            _auto_approve()
            job = _queue.popleft() if _queue else _next_make()
            if job:
                poster_id, box, instruction = job
                label = f"{poster_id} · {ps.STAGE_LABEL.get(box, box)}"
                _state.update(busy=label + (" · สั่งแก้" if instruction else ""), since=time.time())
                try:
                    poster_worker.run_safe(poster_id, box, log=log, instruction=instruction)
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
    # ใบที่ค้าง "กำลังทำ" จากเซิร์ฟเวอร์รอบก่อน (รีสตาร์ตกลางงาน) ไม่มีใครทำต่อแล้ว
    # ถ้าไม่คืนเข้าคิว ป้ายจะบอก "กำลังทำ" ไปตลอดกาล (ข้อ 2.3.1 — ป้ายต้องตรงความจริง)
    for card in ps.list_all():
        if card.get("status") == "running":
            ps.set_status(card["id"], "queued")
            log(f"↺ {card['id']} ค้างกลางงานจากรอบก่อน — คืนเข้าคิวทำใหม่")
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

class NoteBody(BaseModel):
    text: str = ""


class MoveBody(BaseModel):
    stage: str


class EditBody(BaseModel):
    caption: str | None = None
    comments: list[str] | None = None
    shopee_url: str | None = None
    lazada_url: str | None = None


class ImagesBody(BaseModel):
    images: list[str]
    pool: list[str] = []


class CustomBody(BaseModel):
    name: str = ""
    url: str = ""


class PageBody(BaseModel):
    name: str = ""
    url: str = ""


class AutoBody(BaseModel):
    box: str
    on: bool


def _card(card: dict) -> dict:
    out = {k: card.get(k) for k in (
        "id", "source_id", "name", "product_name", "stage", "status", "parked", "park_why",
        "images", "image_pool", "poster_images", "caption", "comments", "highlights",
        "shopee_url", "lazada_url", "error", "posted", "page",
        "poster_custom", "caption_custom", "comment_custom", "created_at", "updated_at")}
    out["stage_label"] = ps.STAGE_LABEL.get(card.get("stage"), card.get("stage"))
    out["status_label"] = ps.STATUS_LABEL.get(card.get("status"), card.get("status") or "")
    return out


HINT = {
    "picture": "ใบที่แตกมาจากใบดึงรูป — ตรวจชุดรูปแล้วอนุมัติเพื่อส่งเข้าทำโปสเตอร์",
    "poster": "ส่งรูปสินค้าเข้า ChatGPT custom ทำโปสเตอร์ — ได้แล้วรอตรวจ",
    "caption": "ส่งรูปโปสเตอร์เข้า ChatGPT custom เขียนแคปชัน — ได้แล้วรอตรวจ",
    "comment": "ส่งรูป + แคปชัน + ลิงก์ เข้า ChatGPT custom เขียนคอมเมนต์ — ได้แล้วรอตรวจ",
    "facebook": "ลงรูปโปสเตอร์ + แคปชันลงเพจ กดไลก์ แล้วคอมเมนต์ — ขั้นนี้ยังไม่เปิด",
    "done": "ลงเพจครบแล้ว",
}
# ไอคอนหน้าชื่อกล่อง — กระดานสายเจนคลิปมีทุกกล่อง (🐣 ดึง Link · 🖼️ Picture …)
ICON = {"picture": "🖼️", "poster": "🎨", "caption": "✍️", "comment": "💬",
        "facebook": "📘", "done": "✅"}
REFILL = {
    "picture": "เติมเองเมื่อมีใบดึงรูปใหม่ในสายคลิป",
    "poster": "อนุมัติชุดรูปในกอง Picture-post",
    "caption": "อนุมัติโปสเตอร์ในกอง Poster",
    "comment": "อนุมัติแคปชันในกอง Caption",
    "facebook": "อนุมัติคอมเมนต์ในกอง Comment",
}


def _buckets(cards: list[dict]) -> list[dict]:
    auto = settings()["auto"]
    out = []
    for key in ps.STAGES:
        here = [c for c in cards if c["stage"] == key]
        live = [c for c in here if not c["parked"]]
        parked = [c for c in here if c["parked"]]
        target = 0 if key == "done" else STOCK_TARGET
        waiting = sum(1 for c in live if c["status"] == "review")
        out.append({
            "key": key, "title": f"{ICON[key]} {ps.STAGE_LABEL[key]}", "hint": HINT[key],
            "count": len(live), "target": target,
            "short": max(0, target - len(live)) if target else 0,
            "refill": REFILL.get(key, ""),
            "auto": ({"key": key, "label": ps.STAGE_LABEL[key], "on": bool(auto.get(key)),
                      "waiting": waiting, "parked_skipped": len(parked)}
                     if key in AUTO_BOXES else None),
            "custom": gpt_customs.selected(key) if key in ps.MAKE_BOXES else None,
            "cards": sorted(live, key=lambda r: r.get("updated_at") or "", reverse=True),
            "parked": parked, "parked_count": len(parked),
        })
    return out


def create_router() -> APIRouter:
    router = APIRouter(prefix="/api/poster")

    def _do(action):
        try:
            result = action()
        except ps.PosterError as error:
            raise HTTPException(409, str(error)) from error
        _wake.set()
        return _card(result)

    @router.get("/board")
    def board():
        cards = [_card(c) for c in ps.list_all()]
        return {
            "buckets": _buckets(cards),
            "customs": gpt_customs.load(),
            "pages": pages(),
            "busy": _state["busy"],
            "busy_seconds": int(time.time() - _state["since"]) if _state["since"] else 0,
            "queue": [f"{a} · {ps.STAGE_LABEL.get(b, b)} · สั่งแก้" for a, b, _ in _queue],
            "lines": list(_lines)[-40:],
            "since": ps.start_date(),
        }

    @router.get("/card/{poster_id}")
    def card(poster_id: str):
        data = ps.load(poster_id)
        if not data:
            raise HTTPException(404, f"ไม่พบใบ {poster_id}")
        return _card(data)

    @router.get("/file/{poster_id}/{sub}/{name}")
    def file(poster_id: str, sub: str, name: str):
        if sub not in ("images", "poster") or "/" in name or "\\" in name or ".." in name:
            raise HTTPException(404)
        path = ps.folder(poster_id) / sub / name
        if not path.is_file():
            raise HTTPException(404, "ไม่พบไฟล์")
        return FileResponse(path)

    @router.post("/{poster_id}/approve")
    def approve(poster_id: str):
        return _do(lambda: ps.approve(poster_id))

    @router.post("/{poster_id}/redo")
    def redo(poster_id: str):
        return _do(lambda: ps.redo(poster_id))

    @router.post("/{poster_id}/revise")
    def revise(poster_id: str, body: NoteBody):
        data = ps.load(poster_id)
        box = data.get("stage")
        if box not in ps.MAKE_BOXES:
            raise HTTPException(409, f"กล่อง {ps.STAGE_LABEL.get(box)} สั่งแก้ผ่าน ChatGPT ไม่ได้")
        if data.get("status") not in ("review", "failed"):
            raise HTTPException(
                409, f"ยังสั่งแก้ไม่ได้ — ใบนี้{ps.STATUS_LABEL.get(data.get('status'), '')}")
        if not body.text.strip():
            raise HTTPException(400, "พิมพ์ก่อนว่าจะแก้ตรงไหน")
        if any(q[0] == poster_id for q in _queue):
            return {"ok": True, "note": "ใบนี้มีคำสั่งแก้รอคิวอยู่แล้ว"}
        # ขึ้นเป็น "กำลังทำ" ตั้งแต่ตอนรับคำสั่ง — ไม่ใช่ "รอคิวทำ" เพราะคนงานหยิบ
        # ใบ "รอคิวทำ" ไปทำใหม่ทั้งกล่องเอง ซึ่งจะแซงคำสั่งแก้แล้วยิง ChatGPT สองรอบ
        ps.set_status(poster_id, "running")
        _queue.append((poster_id, box, body.text.strip()))
        _wake.set()
        return {"ok": True, "note": f"ส่งคำสั่งแก้เข้าคิวแล้ว (ลำดับที่ {len(_queue)})"}

    @router.post("/{poster_id}/park")
    def park(poster_id: str, body: NoteBody):
        return _do(lambda: ps.park(poster_id, body.text))

    @router.post("/{poster_id}/unpark")
    def unpark(poster_id: str):
        return _do(lambda: ps.unpark(poster_id))

    @router.post("/{poster_id}/move")
    def move(poster_id: str, body: MoveBody):
        return _do(lambda: ps.move(poster_id, body.stage))

    @router.post("/{poster_id}/images")
    def images(poster_id: str, body: ImagesBody):
        return _do(lambda: ps.set_images(poster_id, body.images, body.pool))

    @router.put("/{poster_id}")
    def edit(poster_id: str, body: EditBody):
        fields = {k: v for k, v in body.model_dump().items() if v is not None}
        if "comments" in fields:
            fields["comments"] = [c.strip() for c in fields["comments"] if c.strip()]

        def mutate(data: dict) -> None:
            data.update(fields)

        return _do(lambda: ps.change(poster_id, mutate))

    @router.post("/auto")
    def auto(body: AutoBody):
        if body.box not in AUTO_BOXES:
            raise HTTPException(
                400, f"กล่อง {ps.STAGE_LABEL.get(body.box, body.box)} ไม่มีอนุมัติอัตโนมัติ")

        def mutate(data: dict) -> None:
            if not isinstance(data.get("auto"), dict):
                data["auto"] = {}
            data["auto"][body.box] = body.on

        studio_shared.update_json(SETTINGS, mutate, default={})
        label = ps.STAGE_LABEL[body.box]
        log(f"{'เปิด' if body.on else 'ปิด'}อนุมัติอัตโนมัติของ {label}")
        _wake.set()
        return {"on": body.on,
                "message": f"{'เปิด' if body.on else 'ปิด'}อนุมัติอัตโนมัติของ \"{label}\" แล้ว"}

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
