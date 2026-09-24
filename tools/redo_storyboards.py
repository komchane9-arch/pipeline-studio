"""สั่งทำสตอรีบอร์ดใหม่ทั้งกอง — ขั้นที่ 3–4 ของแผนใส่พรีเซนเตอร์

**เจ้าของสั่ง 9 ก.ย. 2569** — *"ให้เขียน flow (ไม่ต้องรันเอง) รันสร้างสตอรี่บอร์ด
ใหม่ทั้งหมดโดยมี presenter เป็นผู้หญิงที่ผมแนบ แต่เก็บ storyboard เก่าไว้ด้วยนะ"*

แผนเต็ม: `note/2026-09-09-แผนเจนสตอรีบอร์ดใหม่ทั้งกอง-ใส่พรีเซนเตอร์.md`

    python tools/redo_storyboards.py --scope not-generated --limit 5           ← ดูก่อน
    python tools/redo_storyboards.py --scope not-generated --limit 5 --apply   ← ลอง 5 ใบ
    python tools/redo_storyboards.py --scope not-generated --apply             ← ทั้งกอง


ด่านกันพลาด 4 ชั้น — ผ่านไม่ครบ = ไม่ทำอะไรเลย
----------------------------------------------

1. **ต้องมีรูปพรีเซนเตอร์ใน `data/presenter/`**
   ไม่มีรูป = ChatGPT จะวาดผู้หญิงมั่วขึ้นมาคนละคนทุกใบโดยไม่มีอะไรฟ้อง

2. **ต้องเก็บสตอรีบอร์ดเก่าไปแล้ว** (`tools/archive_storyboards.py`)
   ยังไม่เก็บ = ของเก่าถูกทับหายถาวร ซึ่งขัดกับที่เจ้าของสั่งไว้ตรงๆ

3. **ช่องทำสตอรีบอร์ดต้องปิดอยู่**
   เพราะที่อยู่ `redo-storyboard` **ปลุกตัวรันทันทีที่เรียก** ถ้าช่องเปิดอยู่
   งานจะเริ่มวิ่งกลางคันตั้งแต่ใบแรก ทั้งที่ยังไม่ได้ตรวจ 5 ใบแรกเลย

4. **ห้ามแตะใบที่มีคลิปแล้ว เว้นแต่สั่งด้วยธงพิเศษ**
   ⚠️ ที่อยู่ `redo-storyboard` **ลบไฟล์คลิปเดิมทิ้ง** ก่อนสั่งเขียนใหม่
   ขอบเขต `all` จึงหมายถึงลบคลิปที่เจนไปแล้ว 348 ใบ = เครดิต Veo 5,220 หน่วย
   ที่จ่ายไปแล้วสูญเปล่า **ต้องใส่ `--ยอมลบคลิป` ถึงจะยอมให้ทำ**
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

import clip_rules  # noqa: E402
import clip_store  # noqa: E402
import studio_shared as shared  # noqa: E402

CLIP_API = "http://127.0.0.1:8877"
POST_TARGETS = ("shopee_video", "facebook_reels", "tiktok")


def api(path: str, method: str = "GET", body: dict | None = None, timeout: int = 60):
    data = json.dumps(body or {}).encode() if method == "POST" else None
    request = urllib.request.Request(
        f"{CLIP_API}{path}", data=data, method=method,
        headers={"Content-Type": "application/json"} if data else {})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def posted_anywhere(run: dict) -> bool:
    publish = run.get("publish") or {}
    return any((publish.get(t) or {}).get("status") == "posted" for t in POST_TARGETS)


def gates(root: Path, allow_delete: bool) -> list[str]:
    """เช็คด่านทั้ง 4 — คืนรายการเหตุผลที่ยังผ่านไม่ได้ ว่าง = ผ่านหมด"""
    stop: list[str] = []

    faces = clip_rules.presenter_images()
    if not faces:
        stop.append(
            f"ยังไม่มีรูปพรีเซนเตอร์ใน {clip_rules.PRESENTER_DIR} — "
            "ไม่มีรูปแล้ว GPT จะวาดผู้หญิงคนละคนทุกใบ")

    archived = 0
    for bucket in clip_store.ALL_DIRS:
        base = root / bucket
        if not base.is_dir():
            continue
        for folder in base.iterdir():
            run_file = folder / clip_store.RUN_FILE
            if run_file.is_file():
                run = clip_store._read_json(run_file)          # noqa: SLF001
                if run.get("storyboard_history"):
                    archived += 1
    if not archived:
        stop.append("ยังไม่ได้เก็บสตอรีบอร์ดเก่าสักใบ — "
                    "รัน tools/archive_storyboards.py --apply ก่อน")

    try:
        config = shared.read_config()
        until = float(config.get("clip_storyboard_until") or 0)
        if not (until and time.time() < until) and not config.get("clip_all_paused"):
            stop.append("ช่องทำสตอรีบอร์ดยังเปิดอยู่ — "
                        "งานจะเริ่มวิ่งทันทีที่สั่ง ปิดช่องก่อนแล้วค่อยเปิดตอนพร้อม")
    except Exception as error:                                 # noqa: BLE001
        stop.append(f"อ่านสวิตช์ไม่ได้: {error}")

    if not allow_delete:
        pass          # ตรวจรายใบทีหลัง ตอนรู้ขอบเขตแล้ว
    return stop


def pick(root: Path, scope: str) -> list[dict]:
    rows: list[dict] = []
    for bucket in clip_store.ALL_DIRS:
        base = root / bucket
        if not base.is_dir():
            continue
        for folder in sorted(base.iterdir(), key=lambda p: p.name):
            run_file = folder / clip_store.RUN_FILE
            if not folder.is_dir() or not run_file.is_file():
                continue
            run = clip_store._read_json(run_file)              # noqa: SLF001
            if not run or not run.get("images"):
                continue                  # ไม่มีรูปสินค้า ทำสตอรีบอร์ดไม่ได้
            if scope == "not-posted" and posted_anywhere(run):
                continue
            if scope == "not-generated" and run.get("videos"):
                continue

            # ⛔ **ข้ามใบที่ทำสตอรีบอร์ดรอบใหม่ไปแล้ว**
            #
            # เทียบเวลา: ทำสตอรีบอร์ดทีหลังเวลาที่เก็บของเก่า = ทำรอบใหม่แล้ว
            # ถ้าไม่กัน จะสั่งทำซ้ำใบที่เพิ่งเสร็จ แล้วล้างคำสั่ง Flow กับบทพูด
            # ที่เพิ่งได้ทิ้งไปเปล่าๆ (เจอจริง 10 ก.ย. 2569 — โดน 5 ใบ)
            history = run.get("storyboard_history") or []
            if history and run.get("storyboard_at"):
                last_archive = str(history[-1].get("at") or "")
                if last_archive and str(run.get("storyboard_at")) > last_archive:
                    continue

            rows.append({
                "item_id": str(run.get("item_id") or folder.name),
                "name": str(run.get("name") or "")[:52],
                "videos": len(run.get("videos") or []),
                # **ถือว่าพร้อม** ถ้าเก็บของเก่าไปแล้ว **หรือ** ไม่มีของเก่าให้เก็บ
                #
                # ใบที่ไม่เคยมีสตอรีบอร์ดเลยไม่มีอะไรให้เก็บ ตัวเก็บของเก่าจึงข้าม
                # ถ้าด่านยังบังคับว่าต้องมีประวัติ ใบพวกนั้นจะติดตลอดกาล
                "archived": bool(run.get("storyboard_history"))
                            or not run.get("storyboard"),
            })
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--scope", default="not-generated",
                        choices=("not-posted", "not-generated", "all"))
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--ยอมลบคลิป", dest="allow_delete", action="store_true",
                        help="ยอมให้ลบไฟล์คลิปที่เจนไปแล้ว (คิดให้ดีก่อนใส่)")
    parser.add_argument("--root", default=str(shared.DATA_DIR))
    args = parser.parse_args()

    root = Path(args.root)
    rows = pick(root, args.scope)
    if args.limit:
        rows = rows[:args.limit]

    with_clip = [r for r in rows if r["videos"]]
    no_archive = [r for r in rows if not r["archived"]]

    print(f"ขอบเขต {args.scope} · เลือกได้ {len(rows)} ใบ")
    print(f"  ในนั้นมีคลิปแล้ว {len(with_clip)} ใบ  "
          f"← สั่งทำใหม่ = **ลบคลิปทิ้ง**")
    print(f"  ยังไม่ได้เก็บของเก่า {len(no_archive)} ใบ")
    for row in rows[:8]:
        mark = "🎬มีคลิป " if row["videos"] else "        "
        print(f"   {mark}{row['item_id']:<14} {row['name']}")
    if len(rows) > 8:
        print(f"   … อีก {len(rows) - 8} ใบ")

    stop = gates(root, args.allow_delete)
    if with_clip and not args.allow_delete:
        stop.append(f"มี {len(with_clip)} ใบที่เจนคลิปแล้ว — สั่งทำสตอรีบอร์ดใหม่จะ"
                    "ลบคลิปทิ้ง ถ้าตั้งใจจริงให้ใส่ --ยอมลบคลิป")
    if no_archive:
        stop.append(f"มี {len(no_archive)} ใบที่**มีสตอรีบอร์ดอยู่แต่ยังไม่ได้เก็บ"
                    f"ของเก่า** — รัน archive_storyboards.py --apply ก่อน")

    if stop:
        print("\n⛔ ยังสั่งไม่ได้ ติดอยู่ " + str(len(stop)) + " เรื่อง")
        for why in stop:
            print(f"   · {why}")
        return 1

    if not args.apply:
        print("\nนี่คือโหมดดูอย่างเดียว ยังไม่ได้สั่งอะไร")
        print("ทำจริงให้ใส่ --apply")
        return 0

    try:
        queue = api("/api/queue")
    except urllib.error.URLError as error:
        print(f"⛔ ต่อเซิร์ฟเวอร์สายคลิปไม่ได้: {error}")
        return 1
    jobs = queue if isinstance(queue, list) else queue.get("jobs", [])
    job_of = {j.get("item_id"): j.get("id") for j in jobs}

    sent, missed = 0, []
    for row in rows:
        job_id = job_of.get(row["item_id"])
        if not job_id:
            missed.append((row["item_id"], "ไม่มีใบงานนี้ในคิว"))
            continue
        try:
            api(f"/api/jobs/{job_id}/redo-storyboard", "POST", timeout=120)
            sent += 1
        except Exception as error:                             # noqa: BLE001
            missed.append((row["item_id"], f"{type(error).__name__}: {error}"))
            break            # หยุดทันทีที่ใบแรกพลาด

    print(f"\nสั่งเข้าคิวแล้ว {sent} ใบ · พลาด {len(missed)} ใบ")
    for item_id, why in missed:
        print(f"   ✕ {item_id}: {why}")
    print("\nช่องทำสตอรีบอร์ดยังปิดอยู่ — งานจะยังไม่เริ่มจนกว่าจะเปิดช่อง")
    return 1 if missed else 0


if __name__ == "__main__":
    raise SystemExit(main())
