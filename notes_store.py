"""สมุดโน้ตในหน้าเว็บ — ไว้แปะข้อความและลิงก์ Shopee / Lazada

เจ้าของสั่ง 21 ก.ย. 2569 — *"เขียนเพิ่มตรงหน้านี้ให้หน่อยว่าเป็น note พอคลิ้กแล้ว
ให้โชว์เป็น pop-up ในหน้าเว็ป เอาไว้สำหรับวาง ข้อความ ลิ้ง shopee lazada
ทำลักษณะคล้ายๆ สมุด note ในไอโฟน"*

**ทำไมเก็บที่เซิร์ฟเวอร์ ไม่เก็บในเบราว์เซอร์**
เจ้าของเปิดหน้านี้จากคอมอีกเครื่องผ่าน Tailscale และจากมือถือด้วย ถ้าเก็บใน
เบราว์เซอร์ โน้ตที่พิมพ์บนเครื่องหนึ่งจะไม่มีในอีกเครื่อง แล้วจะกลายเป็นว่า
"โน้ตหาย" ทั้งที่ยังอยู่ — แยกไม่ออกจากของหายจริง

**ลบแล้วไม่หายทันที** ไปอยู่ถังขยะก่อน กู้คืนได้ เพราะโปรเจกต์นี้เคยลบข้อมูลจริง
หายถาวรมาแล้ว (13 ส.ค. 2569 โปรไฟล์บอท Bot1..Bot10) และโน้ตเป็นของที่พิมพ์เอง
พิมพ์ใหม่ไม่ได้ ต่างจากคลิปที่โหลดใหม่ได้
"""
import re
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import studio_shared

# กันไฟล์บวมจนหน้าเว็บโหลดช้า — ตัวเลขนี้เผื่อไว้เยอะแล้วสำหรับงานแปะลิงก์
MAX_NOTES = 500
MAX_CHARS = 100_000          # ต่อโน้ตหนึ่งใบ (~50 หน้ากระดาษ)
TRASH_KEEP = 30              # เก็บใบที่ลบล่าสุดไว้กี่ใบ
TRASH_DAYS = 30              # เกินกี่วันถึงทิ้งจริง

_ID = re.compile(r"[0-9a-f]{32}")


def _now() -> float:
    return time.time()


def _blank() -> dict:
    return {"notes": [], "trash": []}


def title_of(text: str) -> str:
    """ชื่อโน้ต = บรรทัดแรกที่มีตัวอักษร เหมือนสมุดโน้ตในไอโฟน"""
    for line in str(text or "").splitlines():
        clean = line.strip()
        if clean:
            return clean[:80]
    return ""


def preview_of(text: str) -> str:
    """บรรทัดถัดจากชื่อ ไว้โชว์เป็นตัวอย่างใต้ชื่อ"""
    lines = [line.strip() for line in str(text or "").splitlines()]
    hits = [line for line in lines if line]
    return hits[1][:120] if len(hits) > 1 else ""


def _shape(note: dict) -> dict:
    text = str(note.get("text") or "")
    return {
        "id": str(note.get("id") or ""),
        "text": text,
        "title": title_of(text),
        "preview": preview_of(text),
        "created_at": float(note.get("created_at") or 0.0),
        "updated_at": float(note.get("updated_at") or 0.0),
        "deleted_at": float(note.get("deleted_at") or 0.0),
    }


def _clean_text(value) -> str:
    text = str(value if value is not None else "")
    if len(text) > MAX_CHARS:
        raise ValueError(
            f"โน้ตใบเดียวยาวได้ไม่เกิน {MAX_CHARS:,} ตัวอักษร "
            f"(ใบนี้ {len(text):,}) — แยกเป็นหลายใบจะหาง่ายกว่าด้วย")
    return text


def _sweep(data: dict) -> None:
    """ทิ้งของในถังขยะที่เก่าเกินกำหนด — เรียกทุกครั้งที่แก้ไฟล์"""
    cutoff = _now() - TRASH_DAYS * 86400
    trash = [row for row in data.get("trash") or []
             if float(row.get("deleted_at") or 0.0) >= cutoff]
    trash.sort(key=lambda row: float(row.get("deleted_at") or 0.0), reverse=True)
    data["trash"] = trash[:TRASH_KEEP]


def load(path: Path) -> dict:
    data = studio_shared.read_json(path, _blank())
    if not isinstance(data, dict):
        data = _blank()
    notes = [_shape(row) for row in (data.get("notes") or []) if isinstance(row, dict)]
    trash = [_shape(row) for row in (data.get("trash") or []) if isinstance(row, dict)]
    notes.sort(key=lambda row: row["updated_at"], reverse=True)
    trash.sort(key=lambda row: row["deleted_at"], reverse=True)
    return {"ok": True, "notes": notes, "trash": trash,
            "limits": {"max_notes": MAX_NOTES, "max_chars": MAX_CHARS,
                       "trash_days": TRASH_DAYS}}


def create(path: Path, text: str) -> dict:
    text = _clean_text(text)
    note = {"id": uuid.uuid4().hex, "text": text,
            "created_at": _now(), "updated_at": _now()}

    def mutate(data):
        if not isinstance(data, dict):
            data = _blank()
        rows = data.setdefault("notes", [])
        if len(rows) >= MAX_NOTES:
            raise ValueError(f"มีโน้ตครบ {MAX_NOTES} ใบแล้ว — ลบใบที่ไม่ใช้ก่อน")
        rows.insert(0, note)
        _sweep(data)
        return data

    studio_shared.update_json(path, mutate, _blank(), label="เขียนโน้ต")
    return _shape(note)


def save(path: Path, note_id: str, text: str) -> dict:
    if not _ID.fullmatch(str(note_id)):
        raise ValueError("ไม่พบโน้ตใบนี้")
    text = _clean_text(text)
    found: dict = {}

    def mutate(data):
        if not isinstance(data, dict):
            data = _blank()
        for row in data.get("notes") or []:
            if row.get("id") == note_id:
                row["text"] = text
                row["updated_at"] = _now()
                found.update(row)
                _sweep(data)
                return data
        raise ValueError("ไม่พบโน้ตใบนี้ (อาจถูกลบไปแล้ว)")

    studio_shared.update_json(path, mutate, _blank(), label="บันทึกโน้ต")
    return _shape(found)


def remove(path: Path, note_id: str) -> dict:
    """ย้ายลงถังขยะ ไม่ลบทิ้งทันที — กู้คืนได้ภายใน 30 วัน"""
    if not _ID.fullmatch(str(note_id)):
        raise ValueError("ไม่พบโน้ตใบนี้")
    moved: dict = {}

    def mutate(data):
        if not isinstance(data, dict):
            data = _blank()
        rows = data.get("notes") or []
        for index, row in enumerate(rows):
            if row.get("id") == note_id:
                row["deleted_at"] = _now()
                moved.update(row)
                data.setdefault("trash", []).insert(0, rows.pop(index))
                _sweep(data)
                return data
        raise ValueError("ไม่พบโน้ตใบนี้ (อาจถูกลบไปแล้ว)")

    studio_shared.update_json(path, mutate, _blank(), label="ลบโน้ต")
    return _shape(moved)


def restore(path: Path, note_id: str) -> dict:
    if not _ID.fullmatch(str(note_id)):
        raise ValueError("ไม่พบโน้ตใบนี้")
    back: dict = {}

    def mutate(data):
        if not isinstance(data, dict):
            data = _blank()
        trash = data.get("trash") or []
        for index, row in enumerate(trash):
            if row.get("id") == note_id:
                row.pop("deleted_at", None)
                row["updated_at"] = _now()
                back.update(row)
                data.setdefault("notes", []).insert(0, trash.pop(index))
                return data
        raise ValueError("ไม่พบใบนี้ในถังขยะ — อาจเกินกำหนดแล้วถูกทิ้งไป")

    studio_shared.update_json(path, mutate, _blank(), label="กู้โน้ต")
    return _shape(back)


class NewNote(BaseModel):
    text: str = ""


class EditNote(BaseModel):
    text: str = ""


def create_router(path: Path) -> APIRouter:
    router = APIRouter(prefix="/api/notes")

    @router.get("")
    def notes_all():
        return load(path)

    @router.post("")
    def notes_new(payload: NewNote):
        try:
            return create(path, payload.text)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.put("/{note_id}")
    def notes_save(note_id: str, payload: EditNote):
        try:
            return save(path, note_id, payload.text)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.delete("/{note_id}")
    def notes_delete(note_id: str):
        try:
            return remove(path, note_id)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.post("/{note_id}/restore")
    def notes_restore(note_id: str):
        try:
            return restore(path, note_id)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    return router
