"""ที่เก็บงานเจนคลิป — สตอรีบอร์ด คำสั่ง Flow และข้อมูลสินค้าทั้งหมด

เก็บ **แยกตามสินค้า ทับของเก่า** ตามที่ตกลงกับผู้ใช้: รันสินค้าเดิมซ้ำแล้วได้ของใหม่
ทับไปเลย ไม่สะสมประวัติ (โฟลเดอร์เดียวต่อสินค้าหนึ่งชิ้น หาง่าย ไม่กินพื้นที่)

โครงในโฟลเดอร์สินค้า `data/shopee_products/<item_id>/`

    01.jpg …                   รูปสินค้าที่คัดแล้ว (ของเดิม มีอยู่ก่อนแล้ว)
    storyboard/…png            ภาพสตอรีบอร์ดจาก GPT (ของเดิม)
    run.json                   สรุปงาน — ตัวนี้ตัวเดียวที่ใช้ตอนไล่ดูรายการ
    prompts.json               คำสั่ง Flow แยกเป็นชุด
    gpt-storyboard.md          คำตอบดิบรอบขอสตอรีบอร์ด
    gpt-flow.md                คำตอบดิบรอบขอคำสั่ง Flow
    detail.txt                 รายละเอียดสินค้าดิบจาก Shopee
    raw.json                   ข้อมูลดิบทั้งก้อนจาก API (รูปทุกใบ ตัวเลือก ราคา ฯลฯ)

**แยก "สรุป" ออกจาก "ของดิบ"** เพราะหน้ารายการต้องอ่าน run.json ของทุกสินค้าพร้อมกัน
ถ้ายัดรายละเอียดสินค้า (ยาวหลักหมื่นตัว) กับคำตอบ GPT ลงไปด้วย การเปิดหน้ารายการ
จะช้าขึ้นเรื่อยๆ ตามจำนวนสินค้า

**ทำไมต้องเก็บคำตอบดิบของ GPT** — ตัวตัดคำสั่ง (`extract_prompts`) ยังไม่นิ่ง
เคยได้ 5,093 ตัวอักษรแต่ตัดออกมาได้ชุดเดียว ถ้าเก็บดิบไว้ เวลาแก้ตัวตัดเอาของเก่า
มาลองใหม่ได้เลย ไม่ต้องยิง GPT ซ้ำให้เสียโควตาและเวลา
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path

RUN_FILE = "run.json"
PROMPTS_FILE = "prompts.json"
SCRIPT_FILE = "script.json"
RAW_FILE = "raw.json"
DETAIL_FILE = "detail.txt"
STORYBOARD_REPLY_FILE = "gpt-storyboard.md"
FLOW_REPLY_FILE = "gpt-flow.md"
SCRIPT_REPLY_FILE = "gpt-script.md"
STORYBOARD_DIR = "storyboard"
VIDEO_DIR = "video"


class ClipStoreError(RuntimeError):
    """เก็บหรืออ่านงานเจนคลิปไม่สำเร็จ"""


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _write_json(path: Path, payload: dict | list) -> None:
    """เขียนแบบเขียนไฟล์ชั่วคราวก่อนแล้วค่อยสลับ

    ถ้าเขียนทับตรงๆ แล้วโปรแกรมตายกลางคัน จะเหลือไฟล์ JSON ที่พังอ่านไม่ได้
    ของเดิมก็หายไปด้วย — งานที่เพิ่งเจนเสร็จหายทั้งก้อน
    ต้องระบุ encoding="utf-8" ทุกครั้ง ไม่งั้น Windows เขียนเป็น cp1252 แล้วภาษาไทยเพี้ยน
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    temp.replace(path)


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text or "", encoding="utf-8")


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def run_dir(root: Path, item_id: str) -> Path:
    return Path(root) / "shopee_products" / str(item_id)


# ------------------------------------------------------------------ เขียน

def save_product(root: Path, data: dict) -> Path:
    """เก็บทุกอย่างที่ได้จากขั้นดึงสินค้า — เรียกทันทีที่ดึงเสร็จ

    เรียกก่อนขั้นสตอรีบอร์ดเสมอ เพราะขั้นนั้นล้มได้ ถ้ารอเก็บทีเดียวตอนจบ
    งานที่ดึงสำเร็จแล้วจะหายไปด้วยเวลาสตอรีบอร์ดพัง
    """
    item_id = str(data.get("item_id") or "").strip()
    if not item_id:
        raise ClipStoreError("ไม่มีรหัสสินค้า เก็บไม่ได้")

    folder = run_dir(root, item_id)
    folder.mkdir(parents=True, exist_ok=True)

    # เก็บชื่อไฟล์แบบสัมพัทธ์ ไม่ใช่พาธเต็ม — ย้ายโฟลเดอร์โปรเจกต์แล้วยังใช้ได้
    images = []
    for path in data.get("saved_images", []):
        try:
            images.append(Path(path).relative_to(folder).as_posix())
        except ValueError:
            images.append(Path(path).name)

    # คลังรูปสำรอง = รูปที่โหลดมาแล้วแต่ไม่ได้ถูกคัดเลือก
    # มีไว้ให้ผู้ใช้กด "เปลี่ยนรูป" / "เพิ่มรูป" ในแชทได้โดยไม่ต้องเปิด Shopee ใหม่
    used = set(images)
    pool = []
    for item in data.get("candidates", []):
        try:
            name = Path(item["file"]).relative_to(folder).as_posix()
        except (ValueError, KeyError):
            continue
        if name not in used and name not in pool:
            pool.append(name)

    run = _read_json(folder / RUN_FILE)
    run.update({
        "item_id": item_id,
        "shop_id": data.get("shop_id", ""),
        "name": data.get("name", ""),
        "highlights": data.get("highlights", []),
        "image_pool": pool,
        # ลิงก์ที่ผู้ใช้ส่งมาคือลิงก์ affiliate ตัวจริง ส่วน url คือลิงก์ที่ระบบ
        # แปลงได้ตอนเปิดหน้า ซึ่ง **ไม่มีรหัสผู้แนะนำ** ห้ามสลับกัน
        "affiliate_url": data.get("affiliate_url", ""),
        "product_url": data.get("url", ""),
        "images": images,
        "image_count": len(images),
        "candidate_count": len(data.get("candidates", [])),
        "product_at": _now(),
    })
    run.setdefault("storyboard", [])
    run.setdefault("flow_prompts", [])
    _write_json(folder / RUN_FILE, run)

    _write_text(folder / DETAIL_FILE, data.get("detail", ""))
    # ข้อมูลดิบทั้งก้อน — เก็บไว้เผื่อวันหลังอยากได้ฟิลด์ที่ตอนนี้ยังไม่ได้ใช้
    # (ราคา ตัวเลือกสี รูปทุกใบ) จะได้ไม่ต้องยิง Shopee ซ้ำ
    _write_json(folder / RAW_FILE, data)
    return folder


def set_images(root: Path, item_id: str, images: list[str], pool: list[str]) -> dict:
    """เขียนชุดรูปที่ผู้ใช้แก้แล้วกลับลงงาน

    เก็บเป็นชื่อไฟล์สัมพัทธ์เหมือนตอนบันทึกครั้งแรก — รูปทุกใบยังอยู่ในโฟลเดอร์เดิม
    การ "ลบ" คือย้ายออกจากชุดที่ใช้ไปไว้ในคลัง **ไม่ได้ลบไฟล์ทิ้ง** จะได้กดกลับมาได้
    """
    folder = run_dir(root, item_id)
    run = _read_json(folder / RUN_FILE)
    if not run:
        raise ClipStoreError(f"ไม่พบงานของสินค้า {item_id}")
    run["images"] = list(images)
    run["image_count"] = len(images)
    run["image_pool"] = list(pool)
    run["images_at"] = _now()
    _write_json(folder / RUN_FILE, run)
    return run


def set_highlights(root: Path, item_id: str, highlights: list[str]) -> dict:
    """เขียนจุดเด่นที่ผู้ใช้แก้แล้วกลับลงงาน

    จุดเด่นเป็นวัตถุดิบที่ส่งเข้า GPT คู่กับรูป — ตัวสกัดอัตโนมัติหยิบผิดได้บ่อย
    (ได้ข้อความโปรโมชันหรือเงื่อนไขร้านแทนคุณสมบัติจริง) ต้องแก้ได้ก่อนส่ง
    """
    folder = run_dir(root, item_id)
    run = _read_json(folder / RUN_FILE)
    if not run:
        raise ClipStoreError(f"ไม่พบงานของสินค้า {item_id}")
    run["highlights"] = [text for text in highlights if str(text).strip()]
    run["highlights_at"] = _now()
    _write_json(folder / RUN_FILE, run)
    return run


def save_storyboard(root: Path, data: dict, result: dict) -> Path:
    """เก็บผลขั้นสตอรีบอร์ด + คำสั่ง Flow ทับลงงานเดิมของสินค้าชิ้นนั้น"""
    item_id = str(data.get("item_id") or "").strip()
    if not item_id:
        raise ClipStoreError("ไม่มีรหัสสินค้า เก็บไม่ได้")

    folder = run_dir(root, item_id)
    folder.mkdir(parents=True, exist_ok=True)

    frames = []
    for path in result.get("frames", []):
        try:
            frames.append(Path(path).relative_to(folder).as_posix())
        except ValueError:
            frames.append(f"{STORYBOARD_DIR}/{Path(path).name}")

    prompts = result.get("flow_prompts") or []
    script = result.get("script") or []
    run = _read_json(folder / RUN_FILE)
    run.update({
        "item_id": item_id,
        "chat_url": result.get("chat_url", ""),
        "storyboard": frames,
        "storyboard_count": len(frames),
        # คำสั่งเจนวิดีโอ — เก็บไว้ใช้ตอนเจนใน Flow แต่ไม่ส่งเข้า Telegram
        "flow_prompts": prompts,
        "flow_prompt_count": len(prompts),
        # บทพูด — ตัวนี้ต่างหากที่ส่งให้ผู้ใช้ตรวจ
        "script": script,
        "script_count": len(script),
        "refused": bool(result.get("refused")),
        "refusal_text": result.get("refusal_text", ""),
        "storyboard_at": _now(),
    })
    _write_json(folder / RUN_FILE, run)

    _write_json(folder / PROMPTS_FILE, prompts)
    _write_json(folder / SCRIPT_FILE, script)
    _write_text(folder / STORYBOARD_REPLY_FILE, result.get("reply", ""))
    _write_text(folder / FLOW_REPLY_FILE, result.get("flow_reply", ""))
    _write_text(folder / SCRIPT_REPLY_FILE, result.get("script_reply", ""))
    return folder


def save_video(root: Path, item_id: str, videos: list[Path], note: str = "") -> Path:
    """บันทึกคลิปที่เจนได้จาก Google Flow ลงในงานของสินค้าชิ้นนั้น"""
    folder = run_dir(root, item_id)
    folder.mkdir(parents=True, exist_ok=True)
    names = []
    for path in videos:
        path = Path(path)
        try:
            names.append(path.relative_to(folder).as_posix())
        except ValueError:
            names.append(f"{VIDEO_DIR}/{path.name}")
    run = _read_json(folder / RUN_FILE)
    run.update({
        "item_id": str(item_id),
        "videos": names,
        "video_count": len(names),
        "video_note": note,
        "video_at": _now(),
    })
    _write_json(folder / RUN_FILE, run)
    return folder


# ปลายทางที่จะเอาคลิปไปโพสต์ — โครงไว้ก่อน ยังไม่ได้ต่อตัวโพสต์จริง
PUBLISH_TARGETS = ("facebook_reels", "shopee_video")


def build_caption(run: dict) -> str:
    """แคปชันสำหรับโพสต์ — ชื่อสินค้า + จุดเด่น + **ลิงก์ affiliate ปิดท้าย**

    ลิงก์ต้องเป็น affiliate_url (ลิงก์ที่ผู้ใช้ส่งมา) เท่านั้น ห้ามใช้ product_url
    ที่ระบบแปลงได้ตอนเปิดหน้า — ตัวนั้นไม่มีรหัสผู้แนะนำ โพสต์ไปก็ไม่ได้ค่าคอม
    """
    lines = [run.get("name", "").strip()]
    lines += [f"• {text}" for text in (run.get("highlights") or [])]
    link = run.get("affiliate_url") or ""
    if link:
        lines += ["", link]
    return "\n".join(line for line in lines if line is not None).strip()


def set_hashtag_plan(root: Path, item_id: str, plan: dict) -> dict:
    """เก็บชุดแฮชแท็กของสินค้า พร้อมส่วนประกอบที่ผู้ใช้แก้ได้

    เก็บ brand/kind/details แยกจาก tags เพราะผู้ใช้แก้ทีละชิ้นแล้วให้ระบบ
    ประกอบแท็กใหม่เอง ถ้าเก็บแต่แท็กสำเร็จรูปจะต้องพิมพ์ใหม่ทั้งตัวทุกครั้ง
    """
    folder = run_dir(root, item_id)
    run = _read_json(folder / RUN_FILE)
    if not run:
        raise ClipStoreError(f"ไม่พบงานของสินค้า {item_id}")
    run["hashtag_plan"] = {
        "brand": str(plan.get("brand", "")),
        "kind": str(plan.get("kind", "")),
        "details": [str(item) for item in (plan.get("details") or [])][:3],
        "tags": [str(item) for item in (plan.get("tags") or [])],
        "updated_at": _now(),
    }
    _write_json(folder / RUN_FILE, run)
    return run


def mark_ready_to_post(root: Path, item_id: str) -> dict:
    """คลิปผ่านการอนุมัติแล้ว — ตั้งคิวปลายทางไว้รอตัวโพสต์มาหยิบ

    เก็บสถานะแยกรายปลายทาง เพราะโพสต์ Reels สำเร็จแต่ Shopee Video ล้มได้
    ถ้าเก็บสถานะเดียวรวมกัน จะไม่รู้ว่าต้องตามเก็บอันไหน
    """
    folder = run_dir(root, item_id)
    run = _read_json(folder / RUN_FILE)
    if not run:
        raise ClipStoreError(f"ไม่พบงานของสินค้า {item_id}")
    publish = run.get("publish") or {}
    for target in PUBLISH_TARGETS:
        publish.setdefault(target, {"status": "pending", "posted_at": "", "url": "", "error": ""})
    run["publish"] = publish
    run["caption"] = build_caption(run)
    run["approved_at"] = _now()
    _write_json(folder / RUN_FILE, run)
    return run


def mark_posted(
    root: Path, item_id: str, target: str, url: str = "", error: str = ""
) -> dict:
    """บันทึกผลการโพสต์ของปลายทางหนึ่ง"""
    if target not in PUBLISH_TARGETS:
        raise ClipStoreError(f"ไม่รู้จักปลายทาง {target}")
    folder = run_dir(root, item_id)
    run = _read_json(folder / RUN_FILE)
    if not run:
        raise ClipStoreError(f"ไม่พบงานของสินค้า {item_id}")
    publish = run.get("publish") or {}
    publish[target] = {
        "status": "failed" if error else "posted",
        "posted_at": _now(),
        "url": url,
        "error": error,
    }
    run["publish"] = publish
    _write_json(folder / RUN_FILE, run)
    return run


# ------------------------------------------------------------------- อ่าน

def list_runs(root: Path) -> list[dict]:
    """รายการงานทั้งหมด ใหม่สุดขึ้นก่อน

    อ่านแค่ run.json ของแต่ละสินค้า ไม่แตะไฟล์ดิบ — หน้ารายการจะได้ไม่ช้าลง
    เมื่อสินค้าสะสมมากขึ้น
    """
    base = Path(root) / "shopee_products"
    if not base.is_dir():
        return []
    runs: list[dict] = []
    for folder in base.iterdir():
        if not folder.is_dir():
            continue
        run = _read_json(folder / RUN_FILE)
        if not run:
            continue
        run["folder"] = str(folder)
        runs.append(run)
    runs.sort(key=lambda r: r.get("storyboard_at") or r.get("product_at") or "", reverse=True)
    return runs


def load_run(root: Path, item_id: str) -> dict:
    """งานหนึ่งชิ้นพร้อมของดิบ — ใช้ตอนเปิดดูรายละเอียด"""
    folder = run_dir(root, item_id)
    run = _read_json(folder / RUN_FILE)
    if not run:
        return {}
    run["folder"] = str(folder)
    for key, name in (
        ("gpt_storyboard_reply", STORYBOARD_REPLY_FILE),
        ("gpt_flow_reply", FLOW_REPLY_FILE),
        ("gpt_script_reply", SCRIPT_REPLY_FILE),
        ("detail", DETAIL_FILE),
    ):
        path = folder / name
        run[key] = path.read_text(encoding="utf-8") if path.is_file() else ""
    return run


def file_path(root: Path, item_id: str, name: str) -> Path:
    """พาธของไฟล์ในงาน — กันไม่ให้หลุดออกนอกโฟลเดอร์งาน

    ชื่อไฟล์มาจาก run.json ซึ่งเราเขียนเอง แต่คำขอมาจากหน้าเว็บ ถ้าไม่กันไว้
    จะยิง `../../` ไล่อ่านไฟล์อะไรในเครื่องก็ได้
    """
    folder = run_dir(root, item_id).resolve()
    target = (folder / name).resolve()
    if folder != target and folder not in target.parents:
        raise ClipStoreError("ขอไฟล์นอกโฟลเดอร์งานไม่ได้")
    return target
