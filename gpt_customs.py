# -*- coding: utf-8 -*-
"""ทะเบียน ChatGPT custom ของสายโปสเตอร์ — แยกรายกล่อง เพิ่มเองได้หลายตัว

เจ้าของสั่ง 23 ก.ย. 2569 (สเปค: SPEC-สายโปสเตอร์.md ข้อ 4)

    *"ทำให้ผมเพิ่มเองได้ ให้เพิ่มได้มากกว่า 1"*
    *"เลือกตอนทำงาน ถ้าเลือกตัวไหน ใช้ตัวนั้นตลอดจนกว่าจะเปลี่ยน"*

สามกล่อง — Poster · Caption · Comment — แต่ละกล่องมีรายการของตัวเอง และมี
**ตัวที่เลือกไว้หนึ่งตัว** ซึ่งใช้กับทุกใบจนกว่าจะกดเปลี่ยน ไม่สลับเองอัตโนมัติ

    python gpt_customs.py                       ดูทุกกล่อง
    python gpt_customs.py add poster "ชื่อ" <ลิงก์>
    python gpt_customs.py use poster <รหัส>
    python gpt_customs.py drop poster <รหัส>

## ทำไมเก็บในไฟล์เดียวด้วย `update_json`

สองเซิร์ฟเวอร์ (8866 กับ 8877) อ่าน-เขียนไฟล์นี้ได้ทั้งคู่ อ่าน-แก้-เขียนเองเคย
ทำข้อมูลหาย 4 ใน 5 รอบทดสอบ (กติกาข้อ 7.5) จึงต้องผ่านตัวล็อกกลางเสมอ
"""
from __future__ import annotations

import argparse
import re
import sys
import time
import uuid

import studio_shared

STORE = studio_shared.DATA_DIR / "poster_customs.json"

# กล่องที่มี custom — ชื่อที่คนอ่าน ใช้ในข้อความตอบกลับ
BOXES = {
    "poster": "Poster",
    "caption": "Caption",
    "comment": "Comment",
}

# ตัวอย่างที่เจ้าของยกมาเอง: custom ที่สายคลิปใช้ทำ storyboard
# ใส่ให้กล่อง Poster ตั้งแต่แรก เจ้าของจะได้เห็นว่าหน้าตาเป็นยังไง แล้วเพิ่มของตัวเองต่อ
SEED = {
    "poster": [{
        "name": "นักสร้าง storyboard (ตัวเดียวกับสายคลิป)",
        "url": "https://chatgpt.com/g/g-6a75eb744634819187f2cf52dcb0b7a3",
    }],
}

# ลิงก์ custom GPT ต้องเป็นแบบนี้ — กันวางลิงก์แชทธรรมดาหรือลิงก์อื่นผิดมา
# (ลิงก์แชทธรรมดา /c/... ไม่ใช่ custom แค่เปิดแชทเก่าขึ้นมา ซึ่งไม่ใช่ที่ต้องการ)
GPT_URL = re.compile(r"^https://chatgpt\.com/g/g-[A-Za-z0-9-]+")


class CustomError(ValueError):
    """ทำตามที่สั่งไม่ได้ — ข้อความข้างในเขียนเป็นภาษาคน"""


def _box(name: str) -> str:
    key = str(name or "").strip().lower()
    if key not in BOXES:
        raise CustomError(f"ไม่รู้จักกล่อง “{name}” — มีแค่ {', '.join(BOXES)}")
    return key


def _fresh() -> dict:
    data: dict = {}
    for box in BOXES:
        rows = [{"id": uuid.uuid4().hex[:8], "added_at": time.strftime("%Y-%m-%d %H:%M"),
                 **row} for row in SEED.get(box, [])]
        data[box] = {"items": rows, "selected": rows[0]["id"] if rows else ""}
    return data


def load() -> dict:
    """ทุกกล่อง {กล่อง: {items: [...], selected: รหัส}} — ยังไม่มีไฟล์ = ใส่ตัวอย่างให้"""
    def ensure(data: dict) -> dict:
        if not isinstance(data, dict) or not data:
            return _fresh()
        for box in BOXES:
            data.setdefault(box, {"items": [], "selected": ""})
        return data

    return studio_shared.update_json(STORE, ensure, default={})


def selected(box: str) -> dict | None:
    """custom ที่เลือกไว้ของกล่องนี้ — None = ยังไม่ได้เลือก (ห้ามเดาตัวแรกให้)

    **ไม่มีตัวที่เลือก ต้องคืน None ไม่ใช่หยิบตัวแรกมาใช้** เจ้าของสั่งไว้ชัดว่า
    "เลือกตัวไหนใช้ตัวนั้น" — ถ้าเดาตัวแรกให้ วันที่เจ้าของเพิ่มตัวใหม่ขึ้นหน้าสุด
    งานจะเปลี่ยนไปใช้ตัวนั้นเองโดยไม่มีใครสั่ง
    """
    box = _box(box)
    group = load()[box]
    pick = group.get("selected") or ""
    return next((row for row in group["items"] if row["id"] == pick), None)


def add(box: str, name: str, url: str, use_now: bool = False) -> dict:
    """เพิ่ม custom — ลิงก์ต้องเป็นลิงก์ custom GPT จริง"""
    box = _box(box)
    name = str(name or "").strip()
    url = str(url or "").strip().split("?")[0].rstrip("/")
    if not name:
        raise CustomError("ต้องตั้งชื่อ custom ด้วย จะได้แยกออกว่าตัวไหนเป็นตัวไหน")
    if not GPT_URL.match(url):
        raise CustomError(
            "ลิงก์นี้ไม่ใช่ลิงก์ custom GPT — ต้องขึ้นต้นด้วย https://chatgpt.com/g/g-… "
            "(ลิงก์แชทธรรมดาที่เป็น /c/… ใช้ไม่ได้)")
    row = {"id": uuid.uuid4().hex[:8], "name": name[:80], "url": url,
           "added_at": time.strftime("%Y-%m-%d %H:%M")}

    def change(data: dict) -> None:
        group = data.setdefault(box, {"items": [], "selected": ""})
        if any(item["url"] == url for item in group["items"]):
            raise CustomError(f"ลิงก์นี้มีอยู่ในกล่อง {BOXES[box]} แล้ว")
        group["items"].append(row)
        # กล่องที่ยังไม่มีตัวที่เลือก ใช้ตัวแรกที่เพิ่มเลย — ไม่งั้นกล่องใช้งานไม่ได้
        if use_now or not group.get("selected"):
            group["selected"] = row["id"]

    studio_shared.update_json(STORE, change, default=_fresh())
    return row


def use(box: str, custom_id: str) -> dict:
    """เลือกตัวที่จะใช้ — ใช้ยาวจนกว่าจะเปลี่ยน"""
    box = _box(box)
    found: list = []

    def change(data: dict) -> None:
        group = data.setdefault(box, {"items": [], "selected": ""})
        row = next((item for item in group["items"] if item["id"] == custom_id), None)
        if row is None:
            raise CustomError(f"ไม่พบ custom รหัส {custom_id} ในกล่อง {BOXES[box]}")
        group["selected"] = custom_id
        found.append(row)

    studio_shared.update_json(STORE, change, default=_fresh())
    return found[0]


def drop(box: str, custom_id: str) -> None:
    """ลบ custom — **ตัวที่ใช้อยู่ลบไม่ได้** ต้องเลือกตัวอื่นก่อน

    ถ้ายอมให้ลบตัวที่ใช้อยู่ งานใบถัดไปจะไม่มี custom ให้ใช้แล้วล้มกลางทาง
    ซึ่งเจ้าของจะแยกไม่ออกว่าล้มเพราะอะไร
    """
    box = _box(box)

    def change(data: dict) -> None:
        group = data.setdefault(box, {"items": [], "selected": ""})
        if group.get("selected") == custom_id:
            raise CustomError("ลบตัวที่ใช้อยู่ไม่ได้ — เลือกตัวอื่นเป็นตัวที่ใช้ก่อน แล้วค่อยลบ")
        before = len(group["items"])
        group["items"] = [item for item in group["items"] if item["id"] != custom_id]
        if len(group["items"]) == before:
            raise CustomError(f"ไม่พบ custom รหัส {custom_id} ในกล่อง {BOXES[box]}")

    studio_shared.update_json(STORE, change, default=_fresh())


def rename(box: str, custom_id: str, name: str) -> None:
    box = _box(box)
    name = str(name or "").strip()
    if not name:
        raise CustomError("ชื่อว่างไม่ได้")

    def change(data: dict) -> None:
        for item in data.setdefault(box, {"items": [], "selected": ""})["items"]:
            if item["id"] == custom_id:
                item["name"] = name[:80]
                return
        raise CustomError(f"ไม่พบ custom รหัส {custom_id}")

    studio_shared.update_json(STORE, change, default=_fresh())


# ---------------------------------------------------------------- คอนโซล

def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass
    parser = argparse.ArgumentParser(description="ChatGPT custom ของสายโปสเตอร์")
    sub = parser.add_subparsers(dest="cmd")
    p_add = sub.add_parser("add")
    p_add.add_argument("box")
    p_add.add_argument("name")
    p_add.add_argument("url")
    for name in ("use", "drop"):
        p = sub.add_parser(name)
        p.add_argument("box")
        p.add_argument("custom_id")
    args = parser.parse_args(argv)

    try:
        if args.cmd == "add":
            row = add(args.box, args.name, args.url)
            print(f"เพิ่มแล้ว {row['id']} · {row['name']}")
        elif args.cmd == "use":
            row = use(args.box, args.custom_id)
            print(f"กล่อง {BOXES[args.box]} ใช้ “{row['name']}” แล้ว")
        elif args.cmd == "drop":
            drop(args.box, args.custom_id)
            print("ลบแล้ว")
    except CustomError as error:
        print(f"✕ {error}")
        return 1

    data = load()
    for box, label in BOXES.items():
        group = data[box]
        print(f"\n{label}  ({len(group['items'])} ตัว)")
        if not group["items"]:
            print("   — ยังไม่มี custom ในกล่องนี้ —")
        for item in group["items"]:
            mark = "▶ ใช้อยู่" if item["id"] == group.get("selected") else "        "
            print(f"   {mark}  {item['id']}  {item['name']}")
            print(f"              {item['url']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
