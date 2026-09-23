# -*- coding: utf-8 -*-
"""ที่เก็บใบงานสายโปสเตอร์ — ใบ `<รหัสเดิม>-post` (สเปค: SPEC-สายโปสเตอร์.md)

เจ้าของสั่ง 23 ก.ย. 2569 — *"ดึงรูปเสร็จแล้วให้ duplicate (ทำตลอดเลย ไม่จำกัด
จำนวน) ใบงาน เป็น ชื่อใบงานเดิม-post"* และ *"เพิ่มกล่อง Picture-post ก่อนเข้า poster"*

    data/posters/<id>-post/
        poster.json     ใบงาน (ขั้นที่อยู่ · ของที่ได้แต่ละขั้น · custom ที่ใช้)
        images/         รูปสินค้าที่ก๊อปมาจากใบเดิม
        poster/         รูปโปสเตอร์ที่ได้จาก ChatGPT
        raw/            คำตอบดิบของ AI ทุกขั้น (หลักการข้อ 3 — แก้ตัวแกะแล้วลองใหม่ได้)

## ทำไมแยกโฟลเดอร์ ไม่ใส่ไว้กับใบสายคลิป

กองของสายคลิปคิดจากโฟลเดอร์ + ช่อง `publish` ใน run.json (clip_store) ถ้าเอาใบ
`-post` ไปวางรวม กระดานสายคลิปจะเห็นเป็นใบคลิปเพิ่มอีกเท่าตัว แล้วไปหยิบมาเจนคลิป
ซึ่งกินเครดิต Veo จริง — แยกที่ตั้งแต่แรกจึงไม่มีทางหยิบผิด

## ขั้นของใบ

    picture → poster → caption → comment → facebook → done

`picture` = กอง Picture-post (แตกมาแล้ว รอเข้าสาย) · ใบไม่ข้ามขั้นเด็ดขาด
(กติกาข้อ 2.9) — ขั้นก่อนหน้ายังไม่มีของ ห้ามเริ่มขั้นถัดไป
"""
from __future__ import annotations

import json
import shutil
import time
from datetime import datetime
from pathlib import Path

import studio_shared

ROOT = studio_shared.DATA_DIR / "posters"
FILE = "poster.json"
SUFFIX = "-post"

STAGES = ("picture", "poster", "caption", "comment", "facebook", "done")
STAGE_LABEL = {
    "picture": "Picture-post", "poster": "Poster", "caption": "Caption",
    "comment": "Comment", "facebook": "Facebook", "done": "ลงเพจแล้ว",
}

# แตกเฉพาะใบที่ดึงรูป **ตั้งแต่วันที่เปิดสายนี้** — เจ้าของสั่ง "ทำตลอด" หมายถึง
# ต่อจากนี้ไป ไม่ใช่ย้อนไปแตกใบเก่า 796 ใบพร้อมกัน (นับจริง 23 ก.ย. 2569)
START_FILE = studio_shared.DATA_DIR / "poster_start.json"


class PosterError(ValueError):
    """ทำไม่ได้ — ข้อความข้างในเป็นภาษาคน"""


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def folder(poster_id: str) -> Path:
    return ROOT / str(poster_id)


def post_id(item_id: str) -> str:
    return f"{item_id}{SUFFIX}"


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def load(poster_id: str) -> dict:
    path = folder(poster_id) / FILE
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def change(poster_id: str, mutate) -> dict:
    """อ่าน-แก้-เขียนใบเดียวผ่านตัวล็อกกลาง (สองเซิร์ฟเวอร์เขียนได้ทั้งคู่ — ข้อ 7.5)"""
    path = folder(poster_id) / FILE
    if not path.is_file():
        raise PosterError(f"ไม่พบใบ {poster_id}")

    def apply(data: dict) -> None:
        mutate(data)
        data["updated_at"] = _now()

    return studio_shared.update_json(path, apply, default={})


def list_all() -> list[dict]:
    rows = []
    if ROOT.is_dir():
        for path in ROOT.glob(f"*/{FILE}"):
            try:
                rows.append(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                continue
    rows.sort(key=lambda r: r.get("created_at", ""), reverse=True)
    return rows


# ---------------------------------------------------------------- แตกใบ

def start_date() -> str:
    """วันที่เริ่มแตกใบ — ครั้งแรกที่ถูกเรียกคือวันนี้ แล้วจำไว้ตลอด"""
    def ensure(data: dict) -> None:
        data.setdefault("since", _now())

    return studio_shared.update_json(START_FILE, ensure, default={})["since"]


def should_spawn(run: dict, since: str) -> bool:
    item_id = str(run.get("item_id") or "")
    if not item_id or item_id.endswith(SUFFIX):
        return False                                # ใบ -post ไม่แตกซ้ำ ไม่งั้นวนไม่จบ
    if not run.get("images"):
        return False                                # ยังดึงรูปไม่เสร็จ
    return str(run.get("product_at") or "") >= since


def spawn(run: dict, source: Path) -> dict | None:
    """แตกใบ `-post` จากใบสายคลิป — มีอยู่แล้วคืน None (ไม่ทับของเดิม)

    ก๊อปรูปมาเก็บเอง ไม่อ้างพาธใบเดิม เพราะใบเดิมถูกย้ายโฟลเดอร์ตามสถานะอยู่ตลอด
    (clip_store.refile) — อ้างพาธแล้ววันหนึ่งรูปจะ "หาย" ทั้งที่ไฟล์ยังอยู่
    """
    item_id = str(run.get("item_id") or "").strip()
    pid = post_id(item_id)
    here = folder(pid)
    if (here / FILE).is_file():
        return None
    images = []
    for name in run.get("images") or []:
        src = Path(source) / name
        if not src.is_file():
            continue
        dst = here / "images" / Path(name).name
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        images.append(f"images/{dst.name}")
    if not images:
        raise PosterError(f"ใบ {item_id} ไม่มีไฟล์รูปอยู่จริงสักใบ — แตกใบไม่ได้")
    data = {
        "id": pid,
        "source_id": item_id,
        "name": f"{run.get('name') or item_id}{SUFFIX}",
        "product_name": run.get("name") or "",
        "highlights": run.get("highlights") or [],
        "images": images,
        "shopee_url": run.get("affiliate_url") or "",
        # ยังไม่มีที่มา — เจ้าของบอก "เดวสร้างระบบหาลิ้งทีหลัง" (23 ก.ย. 2569)
        "lazada_url": "",
        "stage": "picture",
        "poster_images": [], "poster_custom": {},
        "caption": "", "caption_custom": {},
        "comments": [], "comment_custom": {},
        "page": {}, "posted": {},
        "error": "",
        "created_at": _now(), "updated_at": _now(),
    }
    _write(here / FILE, data)
    return data


def sweep(clip_root: Path | None = None, log=print) -> list[str]:
    """ไล่หาใบสายคลิปที่ดึงรูปเสร็จแล้วยังไม่มีใบ -post แล้วแตกให้"""
    import clip_store

    root = Path(clip_root or studio_shared.DATA_DIR)
    since = start_date()
    made = []
    for name in clip_store.ALL_DIRS:
        for run_file in (root / name).glob(f"*/{clip_store.RUN_FILE}"):
            try:
                run = json.loads(run_file.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if not should_spawn(run, since):
                continue
            if (folder(post_id(run["item_id"])) / FILE).is_file():
                continue
            try:
                if spawn(run, run_file.parent):
                    made.append(post_id(run["item_id"]))
                    log(f"🖼 แตกใบ {post_id(run['item_id'])} เข้ากอง Picture-post")
            except PosterError as error:
                log(f"✕ แตกใบ {run.get('item_id')} ไม่ได้: {error}")
    return made


# ---------------------------------------------------------------- เดินขั้น

def _ready_for(data: dict, stage: str) -> str:
    """ขั้นนี้เริ่มได้ไหม — คืน "" = ได้ ไม่งั้นคืนเหตุผลภาษาคน (ข้อ 2.9 ห้ามข้ามขั้น)"""
    if stage == "poster" and not data.get("images"):
        return "ยังไม่มีรูปสินค้า"
    if stage == "caption" and not data.get("poster_images"):
        return "ยังไม่มีรูปโปสเตอร์ — ต้องผ่านกล่อง Poster ก่อน"
    if stage == "comment" and not data.get("caption"):
        return "ยังไม่มีแคปชัน — ต้องผ่านกล่อง Caption ก่อน"
    if stage == "facebook" and not data.get("comments"):
        return "ยังไม่มีคอมเมนต์ — ต้องผ่านกล่อง Comment ก่อน"
    if stage == "done" and data.get("posted", {}).get("status") != "posted":
        return "ยังไม่ได้ลงเพจสำเร็จ"
    return ""


def move(poster_id: str, stage: str) -> dict:
    """ย้ายใบไปขั้น `stage` — ย้ายไปข้างหน้าได้ทีละขั้นและของขั้นก่อนต้องครบ"""
    if stage not in STAGES:
        raise PosterError(f"ไม่รู้จักขั้น {stage}")

    def mutate(data: dict) -> None:
        now = STAGES.index(data.get("stage", "picture"))
        want = STAGES.index(stage)
        if want > now + 1:
            raise PosterError(
                f"ข้ามขั้นไม่ได้ — ใบอยู่ที่ {STAGE_LABEL[STAGES[now]]} "
                f"ต้องผ่าน {STAGE_LABEL[STAGES[now + 1]]} ก่อน")
        why = _ready_for(data, stage) if want > now else ""
        if why:
            raise PosterError(why)
        data["stage"] = stage
        data["error"] = ""

    return change(poster_id, mutate)


def set_result(poster_id: str, stage: str, **fields) -> dict:
    """บันทึกของที่ได้จากขั้นหนึ่ง (โปสเตอร์ · แคปชัน · คอมเมนต์ · ผลลงเพจ)"""
    allowed = {
        "poster": {"poster_images", "poster_custom"},
        "caption": {"caption", "caption_custom"},
        "comment": {"comments", "comment_custom"},
        "facebook": {"page", "posted"},
        "picture": {"images", "shopee_url", "lazada_url"},
    }[stage]
    extra = set(fields) - allowed
    if extra:
        raise PosterError(f"ขั้น {stage} เขียนช่อง {', '.join(sorted(extra))} ไม่ได้")

    def mutate(data: dict) -> None:
        data.update(fields)
        data["error"] = ""

    return change(poster_id, mutate)


def save_raw(poster_id: str, stage: str, text: str) -> Path:
    path = folder(poster_id) / "raw" / f"{stage}-{time.strftime('%Y%m%d-%H%M%S')}.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text or "", encoding="utf-8")
    return path


def fail(poster_id: str, why: str) -> dict:
    def mutate(data: dict) -> None:
        data["error"] = why
        data["error_at"] = _now()

    return change(poster_id, mutate)


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if sys.argv[1:2] == ["sweep"]:
        print(f"แตกใหม่ {len(sweep())} ใบ")
    for row in list_all():
        print(f"{STAGE_LABEL.get(row['stage'], row['stage']):<13} {row['id']:<22} "
              f"{row['name'][:40]}  {('⚠ ' + row['error']) if row.get('error') else ''}")
