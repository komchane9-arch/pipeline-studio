"""สถานะหัวคิวของงานโพสต์ที่ผู้ใช้กด Stop.

ไฟล์นี้มีเฉพาะข้อมูลร่วมระหว่าง ``app.py`` (รับปุ่ม Stop) กับ ``clip_app.py``
(ผู้เลือกใบถัดไปจากคิว) เพื่อไม่ให้สองโปรเซสเขียนกติกาคิวคนละชุด.
"""

from __future__ import annotations

from pathlib import Path

import studio_shared


FILE_NAME = "publish_queue_front.json"
TARGETS = {"shopee_video", "facebook_reels", "tiktok"}


def _file(root: Path) -> Path:
    return Path(root) / FILE_NAME


def pin(root: Path, target: str, item_id: str) -> None:
    """ตรึงใบงานไว้หัวคิวของปลายทางจนกว่าจะโพสต์สำเร็จ."""
    target = str(target or "").strip()
    item_id = str(item_id or "").strip()
    if target not in TARGETS or not item_id:
        return

    def change(data: dict) -> dict:
        if not isinstance(data, dict):
            data = {}
        data[target] = item_id
        return data

    studio_shared.update_json(_file(root), change, default={})


def clear(root: Path, target: str, item_id: str = "") -> None:
    """ปลดหัวคิว เฉพาะเมื่อยังเป็นใบที่ caller คาดไว้ (กัน race)."""
    target = str(target or "").strip()
    expected = str(item_id or "").strip()
    if target not in TARGETS:
        return

    def change(data: dict) -> dict:
        if not isinstance(data, dict):
            return {}
        if not expected or str(data.get(target) or "") == expected:
            data.pop(target, None)
        return data

    studio_shared.update_json(_file(root), change, default={})


def first(root: Path, target: str, rows: list[dict]) -> list[dict]:
    """คืนรายการโดยย้ายใบที่ถูก Stop ไปตำแหน่งแรก; ไม่แก้ลำดับใบอื่น."""
    saved = studio_shared.read_json(_file(root), {})
    wanted = str(saved.get(target) or "") if isinstance(saved, dict) else ""
    if not wanted:
        return rows
    index = next((i for i, row in enumerate(rows)
                  if str(row.get("item_id") or "") == wanted), -1)
    if index <= 0:
        return rows
    return [rows[index], *rows[:index], *rows[index + 1:]]
