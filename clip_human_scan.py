"""ตรวจว่าคลิปมี **มือคน** หรือ **คน** อยู่ในฉากไหม — ใช้ตัวตรวจเฉพาะทาง ไม่ใช่ LLM

เจ้าของสั่ง 14 ก.ย. 2569 หลัง TikTok ตีธงคลิปทีวี TCL ว่าผิดนโยบายคุณภาพเนื้อหา
*"ไม่ควรพึ่งพาภาพนิ่งเป็นหลัก"* · *"ควรปรากฏตัวบนหน้าจอและสาธิตสินค้า"*
คลิปที่ไม่มีมือและไม่มีคนจึงต้องถูกคัดออกจากกอง "รอลง TikTok"

**ทำไมไม่ใช้ qwen ตัดสิน** — วัดจริงบนเครื่องนี้ 14 ก.ย. 2569

    ตัดเฟรมด้วย ffmpeg      1.9 วินาที/คลิป      (ไม่ใช่คอขวด)
    qwen2.5vl:7b ตัดสิน     53 วินาที/คลิป       -> 296 ใบ = 4 ชั่วโมงครึ่ง
    สาเหตุ                  ollama รันบน CPU ล้วน (size_vram = 0.0 GB)
                            เครื่องนี้ไม่มีการ์ดจอ NVIDIA (torch.cuda ไม่เห็นอะไร)

ตัวตรวจเฉพาะทางเร็วกว่ามากเพราะตอบคำถามแคบๆ ข้อเดียว ไม่ต้องเข้าใจภาพทั้งใบ

**ของสองตัวนี้อยู่คนละสภาพแวดล้อมกับ Python หลัก** (`_vision_env`) เพราะตอนลงทับ
ของเดิม pip อัปเกรด numpy เป็น 2.x แล้ว cv2 4.9 ใช้ด้วยไม่ได้ ทำให้ทั้งสายพัง
ชั่วคราว — ห้ามลงทับอีก ให้เรียกผ่าน `VISION_PYTHON` เท่านั้น

ใช้งาน
------
    python clip_human_scan.py list          ดูว่ามีคลิปกี่ใบที่ต้องตรวจ
    python clip_human_scan.py probe 12      ตรวจ 12 ใบแรกแล้วเก็บภาพให้คนดูเทียบ
    python clip_human_scan.py run           ตรวจทั้งหมดแล้วบันทึกผลลงใบงาน
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import clip_board                                              # noqa: E402
import clip_store                                              # noqa: E402
import studio_shared                                           # noqa: E402


DATA_DIR = studio_shared.DATA_DIR
VISION_PYTHON = Path(r"C:\project\2.Auto gen Video\_vision_env\Scripts\python.exe")
WORKER = Path(__file__).resolve().parent / "clip_human_worker.py"

# จำนวนเฟรมที่สุ่มจากคลิป — กระจายทั้งความยาว ไม่เอาเฉพาะต้นคลิป
FRAMES = 8


def clips_waiting_tiktok() -> list[tuple[str, str]]:
    """คลิปที่อยู่กอง 'รอลง TikTok' และมีไฟล์วิดีโอจริง"""
    rows: list[tuple[str, str]] = []
    for path in DATA_DIR.glob("*/*/run.json"):
        try:
            run = json.loads(path.read_text(encoding="utf-8"))
        except Exception:                                      # noqa: BLE001
            continue
        if run.get("clip_human"):
            continue                       # ตรวจไปแล้ว
        try:
            if clip_board.bucket_of_run(run) != clip_board.TIKTOK:
                continue
        except Exception:                                      # noqa: BLE001
            continue
        videos = [n for n in (run.get("videos") or []) if (path.parent / n).is_file()]
        if videos:
            rows.append((str(run.get("item_id")), str(path.parent / videos[0])))
    rows.sort()
    return rows


def judge(jobs: list[tuple[str, str]], keep_frames: str = "") -> list[dict]:
    """ส่งงานให้ตัวตรวจในสภาพแวดล้อมแยก แล้วอ่านผลกลับมา"""
    if not VISION_PYTHON.is_file():
        raise RuntimeError(
            f"ไม่พบตัวตรวจภาพที่ {VISION_PYTHON} — ต้องสร้าง _vision_env ก่อน")
    payload = json.dumps({"jobs": jobs, "frames": FRAMES,
                          "keep_frames": keep_frames}, ensure_ascii=False)
    proc = subprocess.run(
        [str(VISION_PYTHON), str(WORKER)], input=payload, text=True,
        encoding="utf-8", capture_output=True,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    if proc.returncode != 0:
        raise RuntimeError(f"ตัวตรวจภาพล้ม: {proc.stderr[-600:]}")
    out = []
    for line in proc.stdout.splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                out.append(json.loads(line))
            except Exception:                                  # noqa: BLE001
                pass
    return out


def save(result: dict) -> None:
    """บันทึกผลลงใบงาน — เก็บหลักฐานว่าตัดสินจากอะไร ไม่ใช่แค่ผ่าน/ไม่ผ่าน"""
    item_id = str(result.get("item_id") or "")
    if not item_id:
        return
    run = clip_store.load_run(DATA_DIR, item_id) or {}
    folder = Path(run.get("folder") or "")
    if not folder.is_dir():
        return
    path = folder / "run.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["clip_human"] = {
        "has_human": bool(result.get("has_human")),
        "hands": int(result.get("hands") or 0),
        "people": int(result.get("people") or 0),
        "frames": int(result.get("frames") or 0),
        "seconds": round(float(result.get("seconds") or 0), 2),
        "checked_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def main(argv: list[str]) -> int:
    action = (argv[1] if len(argv) > 1 else "list").lower()
    jobs = clips_waiting_tiktok()

    if action == "list":
        print(f"คลิปในกอง 'รอลง TikTok' ที่ยังไม่ได้ตรวจ: {len(jobs)} ใบ")
        for item_id, video in jobs[:5]:
            print(f"   {item_id} | {video}")
        return 0

    if action == "probe":
        many = int(argv[2]) if len(argv) > 2 else 10
        keep = str(Path(os.environ.get("TEMP", ".")) / "human-probe")
        started = time.time()
        rows = judge(jobs[:many], keep_frames=keep)
        for row in rows:
            mark = "มีคน/มือ" if row.get("has_human") else "ไม่มีเลย"
            print(f"   {row.get('item_id'):14} {mark:9} "
                  f"มือ {row.get('hands')}/{row.get('frames')} เฟรม · "
                  f"คน {row.get('people')}/{row.get('frames')} เฟรม · "
                  f"{row.get('seconds')} วินาที")
        spent = time.time() - started
        print(f"\nตรวจ {len(rows)} ใบใน {spent:.1f} วินาที "
              f"(เฉลี่ย {spent / max(len(rows), 1):.2f} วินาที/ใบ)")
        print(f"ภาพเฟรมเก็บไว้ที่ {keep}")
        return 0

    if action == "run":
        started = time.time()
        done = no_human = 0
        for index in range(0, len(jobs), 20):
            batch = jobs[index:index + 20]
            for row in judge(batch):
                save(row)
                done += 1
                if not row.get("has_human"):
                    no_human += 1
            print(f"   ตรวจแล้ว {done}/{len(jobs)} ใบ · "
                  f"ไม่มีคน/มือ {no_human} ใบ · "
                  f"ใช้เวลา {time.time() - started:.0f} วินาที", flush=True)
        print(f"\nเสร็จ — ตรวจ {done} ใบ · ไม่มีคน/มือ {no_human} ใบ · "
              f"รวม {time.time() - started:.0f} วินาที")
        return 0

    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
