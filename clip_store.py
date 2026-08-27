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
import shutil
import time
from datetime import datetime
from pathlib import Path

# โฟลเดอร์งาน — ที่แสดงในรายการ กับที่เก็บงานที่ลงครบแล้ว (ย้ายไป ไม่ลบ)
RUNS_DIR = "shopee_products"
DONE_DIR = "shopee_products_done"

# ============================================================================
# โฟลเดอร์แยกตามสถานะ (ผู้ใช้สั่ง 27 ส.ค. 2569)
# ============================================================================
#
# *"ให้แยก folder เลยนะ จะได้แยกจากกันชัดเจน พอทำเสร็จแต่ละขั้นค่อยย้าย folder"*
#
#     shopee_products/       ยังทำอยู่ — ดึงลิงก์ · สตอรีบอร์ด · รออนุมัติคลิป
#     clips/                 มีคลิปแล้ว รอลง Shopee Video
#     clipsfb/               ลง Shopee แล้ว รอลง Facebook Reels
#     clipstiktok/           ลง Facebook แล้ว รอลง TikTok
#     waitstory/             พักไว้รอแก้ ตอนยังทำไม่เสร็จ
#     waitclips/             พักไว้รอแก้ ตอนรอลง Shopee
#     waitclipsfb/           พักไว้รอแก้ ตอนรอลง Facebook
#     waitclipstiktok/       พักไว้รอแก้ ตอนรอลง TikTok
#     shopee_products_done/  ลงครบทั้งสามที่แล้ว
#
# **ตำแหน่งโฟลเดอร์เป็นเงาของ `run.json` ไม่ใช่ความจริงอีกชุด**
# ความจริงคือช่อง `publish` กับ `parked` ในไฟล์งาน — `refile()` ย้ายโฟลเดอร์
# ให้ตรงตามนั้น ถ้าสองอย่างไม่ตรงกันเมื่อไร **เชื่อไฟล์งานแล้วย้ายโฟลเดอร์ตาม**
# (บทเรียนจากตอนกระดานกับ /clips นับไม่ตรงกัน — แก้ด้วยการมีที่มาที่เดียว)
STATE_DIRS = ("clips", "clipsfb", "clipstiktok",
              "waitstory", "waitclips", "waitclipsfb", "waitclipstiktok")

# ทุกที่ที่งานหนึ่งชิ้นอยู่ได้ — ตัวอ่านต้องไล่ให้ครบ ไม่งั้นงานที่ย้ายแล้วจะ "หาย"
ALL_DIRS = (RUNS_DIR, *STATE_DIRS, DONE_DIR)

# โฟลเดอร์ที่ยังนับว่า "ยังไม่จบ" — `list_runs` อ่านจากพวกนี้
ACTIVE_DIRS = (RUNS_DIR, *STATE_DIRS)

# ตัวถามว่า "สินค้าชิ้นนี้ยังมีใบงานเปิดอยู่ในคิวที่ขั้นไหน" — คืน "" ถ้าไม่มี
#
# **ต้องเสียบจากข้างนอก** (`clip_app` ทำให้ตอนเริ่มเซิร์ฟเวอร์) เพราะที่เก็บงาน
# ไม่ควรรู้จักคิว — แต่การย้ายโฟลเดอร์ต้องรู้ ไม่งั้นงานที่เจนคลิปเสร็จแล้วแต่
# ยังรอคนอนุมัติจะถูกย้ายไป `clips/` ทั้งที่กระดานยังจัดไว้กอง "รออนุมัติคลิป"
# แล้วสองที่จะบอกไม่ตรงกัน (เจอจริง 6 ใบ เมื่อ 27 ส.ค. 2569)
#
# ไม่เสียบก็ยังทำงานได้ แค่ตัดสินจากไฟล์อย่างเดียว
stage_lookup = None

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
    return Path(root) / RUNS_DIR / str(item_id)


def done_dir(root: Path, item_id: str) -> Path:
    return Path(root) / DONE_DIR / str(item_id)


def mark_done(root: Path, item_id: str) -> dict:
    """ติ๊กว่าทำแล้ว — **ย้าย**ทั้งโฟลเดอร์ออกไป `shopee_products_done/` ไม่ลบ

    ทำไมย้ายไม่ลบ: ของในโฟลเดอร์คือรูปที่จ่ายเครดิตไปแล้วกับคลิปที่เจนเสร็จ
    ติ๊กผิดแล้วลบทิ้ง = จ่ายซ้ำ ย้ายไว้ข้างๆ กดกลับได้ทันทีด้วย `restore_done()`

    `list_runs()` อ่านเฉพาะ `shopee_products/` งานที่ย้ายแล้วจึงหายจากทุกรายการ
    เองโดยไม่ต้องเพิ่มธงกรองที่ไหนอีก — ที่เดียวจบ ไม่มีจุดที่ลืมกรอง
    """
    # **หาจากทุกโฟลเดอร์** งานอาจอยู่ที่ clips/ หรือ clipsfb/ แล้ว
    # ถ้าหาแต่ shopee_products/ จะขึ้นว่า "ไม่พบโฟลเดอร์งาน" ทั้งที่ของอยู่ครบ
    source = target_dir(root, item_id)
    if not source.is_dir():
        raise ClipStoreError(f"ไม่พบโฟลเดอร์งาน {item_id}")
    run = _read_json(source / RUN_FILE)

    target = done_dir(root, item_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        # เคยติ๊กแล้วเอากลับมาทำใหม่ แล้วติ๊กอีกรอบ — เก็บของเก่าไว้ ไม่ทับ
        target = target.with_name(f"{target.name}-{int(time.time())}")
    shutil.move(str(source), str(target))

    run["done_at"] = _now()
    run["folder"] = str(target)
    try:
        (target / RUN_FILE).write_text(
            json.dumps(run, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except OSError:
        pass  # ย้ายสำเร็จแล้ว แค่ประทับเวลาไม่ติด — ไม่ใช่เหตุให้ล้มทั้งงาน
    return run


def restore_done(root: Path, item_id: str) -> dict:
    """เอางานที่ติ๊กไปแล้วกลับมาแสดงในรายการ — ทางกลับของ `mark_done()`"""
    source = done_dir(root, item_id)
    if not source.is_dir():
        raise ClipStoreError(f"ไม่พบงาน {item_id} ในโฟลเดอร์ที่ทำแล้ว")
    # เอากลับไปวางที่ `shopee_products/` ก่อน แล้วให้ `refile` ย้ายต่อไปโฟลเดอร์
    # ที่ถูกตามสถานะจริง — ไม่ต้องคิดเองว่าควรไปกองไหน
    target = run_dir(root, item_id)
    if target.exists():
        raise ClipStoreError(f"งาน {item_id} อยู่ในรายการอยู่แล้ว")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source), str(target))
    run = _read_json(target / RUN_FILE)
    run.pop("done_at", None)
    run["folder"] = str(target)
    try:
        (target / RUN_FILE).write_text(
            json.dumps(run, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except OSError:
        pass
    run["folder"] = str(refile(root, str(item_id)))
    return run


def _to_drive(root: Path, item_id: str) -> None:
    """ยกงานขึ้น Google Drive ต่อทันทีที่เก็บลงเครื่องเสร็จ

    เรียก **หลัง** เขียนดิสก์เสมอ ไม่ใช่เขียนแทน — ดิสก์ยังเป็นตัวหลักเพราะหน้าเว็บ
    เสิร์ฟรูปจากที่นี่ และไดรฟ์ G: หายไปทั้งตัวได้ถ้าโปรแกรม Drive ไม่ทำงาน
    (เหตุผลเต็มอยู่หัวไฟล์ clip_drive.py)

    **ห้ามโยน exception ออกจากฟังก์ชันนี้เด็ดขาด** — ตัวเรียกคือ `save_storyboard`
    กับ `save_video` ซึ่งเก็บของที่จ่ายเครดิตไปแล้ว ถ้า Drive มีปัญหาแล้วลาก
    ให้การเก็บลงเครื่องล้มไปด้วย = จ่ายเครดิตฟรี `sync_run` คืน dict เสมอ
    อยู่แล้ว ที่ครอบไว้อีกชั้นคือกันกรณีที่คาดไม่ถึงจริงๆ (เช่น import พัง)

    ของที่ยกไม่ขึ้นไม่หายเงียบ — ตามเก็บทีหลังได้ด้วย `python clip_drive.py sync`
    """
    try:
        import clip_drive
        result = clip_drive.sync_run(root, item_id)
        if not result.get("ok"):
            print(f"  [Drive] ยังไม่ได้ยก {item_id} — {result.get('why')}", flush=True)
    except ImportError:
        return          # ถอดตัวยกขึ้น Drive ออกก็ยังเก็บลงเครื่องได้ตามปกติ
    except Exception as error:
        print(f"  [Drive] ยกขึ้นไม่สำเร็จ ({type(error).__name__}: {error}) — "
              f"ของยังอยู่ในเครื่องครบ ตามเก็บด้วย `python clip_drive.py sync`",
              flush=True)


# ------------------------------------------------------------------ เขียน

def target_dir(root: Path, item_id: str) -> Path:
    """โฟลเดอร์ที่ควร **เขียน** ของงานนี้ลงไป

    **ต้องใช้ตัวนี้ทุกที่ที่เขียน ห้ามเรียก run_dir ตรงๆ** เพราะงานที่ผู้ใช้ติ๊กว่า
    "ทำแล้ว" ถูกย้ายไป `shopee_products_done/` แล้ว — ตัวอ่าน (`load_run`) รู้จัก
    ที่ใหม่ แต่ตัวเขียนที่เรียก `run_dir` ตรงๆ จะไปสร้างโฟลเดอร์เปล่าที่เดิม
    กลายเป็น **ไฟล์อยู่ที่หนึ่ง สมุดบันทึกอยู่อีกที่หนึ่ง**

    เกิดจริง 23 ส.ค. 2026 เวลา 22:31 — ทีวี 75 นิ้วที่เคยติ๊กว่าทำแล้ว ถูกสั่งเจน
    คลิปใหม่ ไฟล์ 10.3 MB ลงที่โฟลเดอร์ "ทำแล้ว" ถูกต้อง แต่ `save_video` เขียน
    run.json ไปที่โฟลเดอร์เดิมซึ่งว่างเปล่า ผลคือระบบรายงานว่า "ยังไม่มีไฟล์คลิป"
    ทั้งที่เพิ่งจ่ายเครดิตไป 15 หน่วย และแฮชแท็กออกมา 0 ตัวเพราะอ่านเจอแต่ record เปล่า

    ตั้งแต่ 27 ส.ค. 2569 มีโฟลเดอร์แยกตามสถานะอีก 7 อัน (ดู `STATE_DIRS`)
    ตัวนี้จึงต้องไล่หาให้ครบทุกที่ **ไม่งั้นงานที่ย้ายไปแล้วจะถูกมองว่าไม่มี
    แล้วโค้ดจะสร้างโฟลเดอร์เปล่าทับที่เดิม** — อาการเดียวกับบั๊ก 23 ส.ค. ข้างบน
    แต่เกิดกับทุกงานที่ย้าย ไม่ใช่แค่งานที่ติ๊กว่าทำแล้ว

    ยังไม่เคยมีที่ไหนเลย = งานใหม่ ให้สร้างที่โฟลเดอร์ปกติ
    """
    for name in ALL_DIRS:
        folder = Path(root) / name / str(item_id)
        if folder.is_dir():
            return folder
    return run_dir(root, item_id)


def refile(root: Path, item_id: str) -> Path:
    """ย้ายโฟลเดอร์งานไปให้ตรงกับสถานะใน `run.json` — คืนที่อยู่ใหม่

    เรียกทุกครั้งที่สถานะเปลี่ยน (จดว่าลงแล้ว · พัก · เอากลับ) โฟลเดอร์จะได้
    ตามทันเสมอ **เรียกซ้ำได้ ไม่เกิดผลข้างเคียง** อยู่ถูกที่แล้วก็ไม่ทำอะไร

    **ย้ายไม่สำเร็จไม่ใช่เหตุให้ล้มทั้งงาน** — สถานะจริงอยู่ใน `run.json`
    ซึ่งเขียนไปแล้ว โฟลเดอร์แค่ตามไม่ทัน สั่ง `refile` ใหม่เมื่อไรก็ได้
    (คำสั่งตรวจ-ซ่อมทั้งชุดอยู่ที่ `refile_all`)
    """
    return refile_folder(root, target_dir(root, item_id))


def refile_folder(root: Path, here: Path) -> Path:
    """ย้าย **โฟลเดอร์ที่ระบุ** ไปให้ตรงกับสถานะข้างใน — คืนที่อยู่ใหม่

    **ต้องมีแยกจาก `refile`** เพราะมีรหัสสินค้าที่มีโฟลเดอร์อยู่สองที่พร้อมกัน
    (เกิดตอนส่งลิงก์เดิมซ้ำหลังงานเก่าถูกเก็บไปแล้ว) ถ้า `refile_all` ค้นด้วย
    รหัสสินค้า มันจะเจอตัวแรกเสมอแล้วย้ายตัวเดิมซ้ำๆ ส่วนอีกตัวไม่เคยถูกแตะ

    เจอจริงตอนย้ายชุดแรก 27 ส.ค. 2569: 4 โฟลเดอร์ค้างอยู่ที่เดิมโดยไม่มีอะไรฟ้อง
    """
    import clip_board                                          # noqa: PLC0415
    if not here.is_dir():
        return here
    run = _read_json(here / RUN_FILE)
    if not run:
        return here
    item_id = here.name
    stage = ""
    if stage_lookup:
        try:
            stage = stage_lookup(item_id) or ""
        except Exception:                                      # noqa: BLE001
            stage = ""      # ถามคิวไม่ได้ก็ตัดสินจากไฟล์ไปก่อน ดีกว่าล้มทั้งงาน
    want = clip_board.folder_of_run(run, stage)
    if here.parent.name == want:
        return here                     # อยู่ถูกที่แล้ว

    target = Path(root) / want / str(item_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        # ที่ปลายทางมีของชื่อเดียวกันอยู่แล้ว — **ห้ามทับ** ของในนั้นคือรูปกับคลิป
        # ที่จ่ายเครดิตไปแล้ว เก็บของเก่าไว้ข้างๆ ให้คนมาดูเองว่าจะเอาอันไหน
        target = target.with_name(f"{item_id}-ซ้ำ-{int(time.time())}")
    shutil.move(str(here), str(target))
    run["folder"] = str(target)
    try:
        (target / RUN_FILE).write_text(
            json.dumps(run, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass        # ย้ายสำเร็จแล้ว แค่ประทับที่อยู่ใหม่ไม่ติด ไม่ใช่เหตุให้ล้ม
    return target


def refile_all(root: Path, dry: bool = False) -> list[dict]:
    """ตรวจทั้งชุดว่าทุกโฟลเดอร์อยู่ถูกที่ไหม — คืนรายการที่ย้าย (หรือที่ควรย้าย)

    `dry=True` = ดูอย่างเดียวไม่ย้ายจริง ใช้ก่อนย้ายของจริงทุกครั้ง

    **นี่คือตัวซ่อมเมื่อโฟลเดอร์กับไฟล์งานไม่ตรงกัน** ซึ่งเกิดได้จากย้ายพลาด ·
    เซิร์ฟเวอร์ดับกลางคัน · หรือมีคนย้ายด้วยมือ — ไม่ต้องไล่ซ่อมเอง
    """
    import clip_board                                          # noqa: PLC0415
    moves = []
    for name in ALL_DIRS:
        base = Path(root) / name
        if not base.is_dir():
            continue
        for folder in list(base.iterdir()):
            if not folder.is_dir():
                continue
            run = _read_json(folder / RUN_FILE)
            if not run:
                continue
            stage = ""
            if stage_lookup:
                try:
                    stage = stage_lookup(folder.name) or ""
                except Exception:                              # noqa: BLE001
                    stage = ""
            want = clip_board.folder_of_run(run, stage)
            if want == name:
                continue
            moves.append({"item_id": folder.name, "name": run.get("name", ""),
                          "from": name, "to": want})
            if not dry:
                refile_folder(root, folder)
    return moves


def save_product(root: Path, data: dict) -> Path:
    """เก็บทุกอย่างที่ได้จากขั้นดึงสินค้า — เรียกทันทีที่ดึงเสร็จ

    เรียกก่อนขั้นสตอรีบอร์ดเสมอ เพราะขั้นนั้นล้มได้ ถ้ารอเก็บทีเดียวตอนจบ
    งานที่ดึงสำเร็จแล้วจะหายไปด้วยเวลาสตอรีบอร์ดพัง
    """
    item_id = str(data.get("item_id") or "").strip()
    if not item_id:
        raise ClipStoreError("ไม่มีรหัสสินค้า เก็บไม่ได้")

    folder = target_dir(root, item_id)
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
        # จุดขายที่ไล่ออกมาได้ **ทั้งหมด** กับเหตุผลที่เลือก 3 ข้อนั้น
        # (ผู้ใช้สั่ง 22 ส.ค. 2026) — เก็บไว้เพื่อสองอย่าง
        #   1. สลับข้อที่ไม่ถูกใจได้โดยไม่ต้องยิง AI ใหม่ (โควตาวันละ 20 ครั้ง)
        #   2. ตรวจได้ว่า AI เลือกด้วยเหตุผลอะไร จับได้เวลามันเลือกผิด
        "features": data.get("features", []),
        "highlight_why": data.get("highlight_why", []),
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
    folder = target_dir(root, item_id)
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
    folder = target_dir(root, item_id)
    run = _read_json(folder / RUN_FILE)
    if not run:
        raise ClipStoreError(f"ไม่พบงานของสินค้า {item_id}")
    run["highlights"] = [text for text in highlights if str(text).strip()]
    run["highlights_at"] = _now()
    _write_json(folder / RUN_FILE, run)
    return run


def set_script(root: Path, item_id: str, lines: list[str]) -> dict:
    """เขียนบทพูดที่ผู้ใช้พิมพ์แก้เองกลับลงงาน (ผู้ใช้สั่ง 26 ส.ค. 2026)

    **จำนวนฉากต้องเท่าเดิมเสมอ** — แก้ข้อความได้ แต่เพิ่ม/ลบบรรทัดไม่ได้
    เพราะบทพูดฉากที่ N ผูกกับภาพสตอรีบอร์ดใบที่ N และคำสั่ง Flow ของฉากนั้น
    ถ้าจำนวนเพี้ยน ฉากจะเลื่อนกันทั้งแถบโดยไม่มีอะไรฟ้อง แล้วคลิปจะพูดเรื่องหนึ่ง
    แต่ภาพเป็นอีกเรื่อง (ตัวแก้คำสั่งที่ผิดนโยบายก็บังคับข้อเดียวกันนี้อยู่แล้ว)

    เขียน 3 ที่ให้ตรงกัน — `run["script"]` ที่ทุกคนอ่าน · `script_count` ที่ใช้โชว์
    และตรวจจำนวนฉาก · ไฟล์ `script.json` ที่เก็บแยก ถ้าเขียนไม่ครบ จะมีที่หนึ่ง
    เป็นของเก่าค้างไว้แล้วไล่ไม่เจอว่าทำไมได้บทพูดคนละชุด
    """
    folder = target_dir(root, item_id)
    run = _read_json(folder / RUN_FILE)
    if not run:
        raise ClipStoreError(f"ไม่พบงานของสินค้า {item_id}")

    before = list(run.get("script") or [])
    texts = [str(line or "").strip() for line in lines]
    if any(not text for text in texts):
        raise ClipStoreError("บทพูดต้องไม่มีฉากไหนว่าง")
    if before and len(texts) != len(before):
        raise ClipStoreError(
            f"บทพูดต้องมี {len(before)} ฉากเท่าเดิม (ส่งมา {len(texts)} ฉาก) "
            "— แก้ข้อความได้ แต่เพิ่ม/ลบฉากไม่ได้ เพราะผูกกับภาพสตอรีบอร์ด")

    run["script"] = texts
    run["script_count"] = len(texts)
    run["script_at"] = _now()
    _write_json(folder / RUN_FILE, run)
    _write_json(folder / SCRIPT_FILE, texts)
    return run


def set_story_full_shot(root: Path, item_id: str, value: bool) -> dict:
    """เก็บว่างานใบนี้ติ๊ก "เห็นสินค้าเต็มทุกฉาก" ไว้ไหม

    เก็บรายใบ ไม่ใช่ค่ารวมของทั้งระบบ เพราะสินค้าคนละชิ้นต้องการคนละแบบ
    (ทีวีต้องเห็นเต็มเครื่อง แต่หูฟังซูมเข้าไปดูเนื้องานได้)
    ส่วน "ค่าที่จำไว้ล่าสุด" อยู่ที่ `clip_rules.remember()` ใช้เป็นค่าตั้งต้นเท่านั้น
    """
    folder = target_dir(root, item_id)
    run = _read_json(folder / RUN_FILE)
    if not run:
        raise ClipStoreError(f"ไม่พบงานของสินค้า {item_id}")
    run["story_full_shot"] = bool(value)
    run["story_full_shot_at"] = _now()
    _write_json(folder / RUN_FILE, run)
    return run


def set_flow_prompts(root: Path, item_id: str, prompts: list[str]) -> dict:
    """เขียนคำสั่ง Flow ชุดที่แก้แล้วกลับลงงาน

    ใช้ตอนผู้ใช้กด "ลบแล้วเจนใหม่" พร้อมคอมเมนต์ — AI ดูคลิปแล้วแก้คำสั่งให้
    **จำนวนชุดต้องเท่าเดิม** เพราะแต่ละชุดผูกกับฉากในคลิป ด่านจริงอยู่ที่
    `clip_fix._finish()` ตรงนี้กันอีกชั้นเผื่อมีคนเรียกตรงๆ
    """
    folder = target_dir(root, item_id)
    run = _read_json(folder / RUN_FILE)
    if not run:
        raise ClipStoreError(f"ไม่พบงานของสินค้า {item_id}")
    rows = [str(text) for text in prompts if str(text).strip()]
    if not rows:
        raise ClipStoreError("คำสั่ง Flow ว่างเปล่า")
    before = list(run.get("flow_prompts") or [])
    if before and len(rows) != len(before):
        raise ClipStoreError(
            f"คำสั่ง Flow ต้องมี {len(before)} ชุดเท่าเดิม (ส่งมา {len(rows)} ชุด)")
    run["flow_prompts"] = rows
    run["flow_prompts_at"] = _now()
    _write_json(folder / RUN_FILE, run)
    return run


def read_detail(root: Path, item_id: str) -> str:
    """ข้อความรายละเอียดสินค้าดิบที่เก็บไว้ตอนดึงมา

    มีไว้ให้คัดจุดเด่นใหม่ได้โดย **ไม่ต้องเปิดเบราว์เซอร์ไปดึง Shopee ซ้ำ** ซึ่ง
    ทั้งช้าและต้องแย่งเบราว์เซอร์กับงานเจนคลิป (Chrome โปรไฟล์เดียว เปิดซ้อนไม่ได้)
    """
    for folder in (target_dir(root, item_id),):
        path = folder / DETAIL_FILE
        if path.is_file():
            return path.read_text(encoding="utf-8", errors="replace")
    return ""


def save_features(root: Path, item_id: str, analysis: dict) -> dict:
    """เก็บผลคัดจุดเด่นรอบใหม่ทับของเดิม — ทั้งรายการเต็ม 3 ข้อที่เลือก และเหตุผล"""
    folder = target_dir(root, item_id)
    if not folder.is_dir():
        raise ClipStoreError(f"ไม่พบโฟลเดอร์งาน {item_id}")
    run = _read_json(folder / RUN_FILE)
    run.update({
        "item_id": str(item_id),
        "highlights": list(analysis.get("highlights") or []),
        "features": list(analysis.get("features") or []),
        "highlight_why": list(analysis.get("why") or []),
        "highlights_at": _now(),
    })
    _write_json(folder / RUN_FILE, run)
    return run


def save_storyboard(root: Path, data: dict, result: dict) -> Path:
    """เก็บผลขั้นสตอรีบอร์ด + คำสั่ง Flow ทับลงงานเดิมของสินค้าชิ้นนั้น"""
    item_id = str(data.get("item_id") or "").strip()
    if not item_id:
        raise ClipStoreError("ไม่มีรหัสสินค้า เก็บไม่ได้")

    folder = target_dir(root, item_id)
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
        # **จำจุดเด่นชุดที่ใช้ทำรอบนี้ไว้ด้วย** (ผู้ใช้ถาม 23 ส.ค. 2026)
        #
        # จุดเด่นคือวัตถุดิบที่กำหนดว่าคลิปจะพูดเรื่องอะไร ถ้าแก้จุดเด่นทีหลัง
        # สตอรีบอร์ด คำสั่ง Flow และบทพูดที่ทำไว้แล้วจะ**ไม่เปลี่ยนตาม** —
        # ของพวกนั้นถูกสร้างครั้งเดียวจากจุดเด่นชุดเก่า
        #
        # เก็บสำเนาไว้เพื่อให้เทียบได้ว่า "ที่เห็นอยู่ตรงกับจุดเด่นตอนนี้หรือยัง"
        # ไม่งั้นความไม่ตรงกันจะเงียบ — ผู้ใช้แก้จุดเด่นแล้วนึกว่าคลิปจะเปลี่ยนตาม
        "storyboard_highlights": list(data.get("highlights") or []),
    })
    _write_json(folder / RUN_FILE, run)

    _write_json(folder / PROMPTS_FILE, prompts)
    _write_json(folder / SCRIPT_FILE, script)
    _write_text(folder / STORYBOARD_REPLY_FILE, result.get("reply", ""))
    _write_text(folder / FLOW_REPLY_FILE, result.get("flow_reply", ""))
    _write_text(folder / SCRIPT_REPLY_FILE, result.get("script_reply", ""))
    _to_drive(root, item_id)
    return folder


def drop_storyboard(root: Path, item_id: str, name: str) -> dict:
    """เอาภาพสตอรีบอร์ดใบหนึ่งออกจากงาน (ผู้ใช้สั่ง 26 ส.ค. 2026)

    มีไว้เพราะ **บางครั้ง ChatGPT ส่งภาพมาสองใบให้เลือก** — เป็นกล่องทดลองของ
    OpenAI ที่ถามว่า "Which image do you like more?" แล้ววาดสองแบบมาเทียบกัน
    ตัวโหลดของเราไม่รู้จักกล่องนั้น จึงเก็บมาทั้งคู่ (เจอจริง 1 ใน 27 งาน)
    ผู้ใช้ต้องมีทางเลือกใบที่ไม่เอาออกเอง ไม่ใช่ปล่อยให้สองใบไปคาที่ขั้นตรวจ

    **ย้ายลงถังขยะ ไม่ลบถาวร** — ภาพนี้ต้องเสียโควตา ChatGPT กว่าจะได้มา
    ถ้าลบผิดใบแล้วกู้ไม่ได้ ต้องเจนใหม่ทั้งรอบ ถังขยะอยู่ที่
    `<งาน>/storyboard/_trash/` ลบเองได้เมื่อแน่ใจแล้ว

    **ลบไฟล์แล้วต้องลบรายการในสมุดบันทึกด้วยเสมอ** (บทเรียนเดียวกับ
    `clear_videos`) ไม่งั้นสมุดบอกว่ามีภาพ แต่โฟลเดอร์ไม่มี แล้วทุกอย่างที่
    อ่านสมุดจะเชื่อผิดตามกันหมด
    """
    folder = target_dir(root, item_id)
    run = _read_json(folder / RUN_FILE)
    if not run:
        raise ClipStoreError(f"ไม่พบงานของสินค้า {item_id}")

    frames = list(run.get("storyboard") or [])
    key = str(name or "").strip()
    if key not in frames:
        raise ClipStoreError(f"ไม่มีภาพสตอรีบอร์ดชื่อ {key} ในงานนี้")
    if len(frames) <= 1:
        raise ClipStoreError(
            "เหลือภาพใบเดียว ลบไม่ได้ — ถ้าไม่ชอบใบนี้ให้กด "
            "\"สั่งแก้สตอรีบอร์ด\" เพื่อให้ GPT วาดใหม่แทน")

    target = folder / key
    if target.is_file():
        trash = folder / STORYBOARD_DIR / "_trash"
        trash.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        target.replace(trash / f"{stamp}-{target.name}")

    frames.remove(key)
    run["storyboard"] = frames
    run["storyboard_count"] = len(frames)
    run["storyboard_dropped_at"] = _now()
    _write_json(folder / RUN_FILE, run)
    return run


def save_video(root: Path, item_id: str, videos: list[Path], note: str = "") -> Path:
    """บันทึกคลิปที่เจนได้จาก Google Flow ลงในงานของสินค้าชิ้นนั้น"""
    folder = target_dir(root, item_id)
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
    _to_drive(root, str(item_id))
    return folder


def clear_videos(root: Path, item_id: str) -> dict:
    """ลบ **รายการ** คลิปออกจากสมุดบันทึก — ใช้คู่กับตอนลบไฟล์คลิปทิ้ง

    **ลบไฟล์แล้วต้องลบรายการเสมอ** ไม่งั้นสมุดบันทึกจะบอกว่ามีคลิป แต่โฟลเดอร์ว่าง
    ทุกอย่างที่อ่านสมุดบันทึกจะเชื่อผิดหมด

    เกิดจริง 23 ส.ค. 2026: ปุ่ม 🔄 เจนใหม่ ลบไฟล์คลิปของทีวี 55 นิ้วทิ้ง แต่ไม่ได้
    ลบรายการ พอเปิดดูงานนั้นระบบพยายามไปตรวจคลิปที่ไม่มีอยู่ แล้วขึ้น error
    "งานนี้ยังไม่มีไฟล์คลิป" ซึ่งชี้สาเหตุผิดทาง (ฟังดูเหมือนยังไม่เคยเจน ทั้งที่
    เจนไปแล้วและถูกลบทิ้งเอง)

    ลบผลตรวจเก่าไปด้วย — ผลตรวจผูกกับไฟล์ที่ไม่มีแล้ว เก็บไว้ก็ทำให้เข้าใจผิด
    """
    for folder in (target_dir(root, item_id),):
        if not folder.is_dir():
            continue
        run = _read_json(folder / RUN_FILE)
        if not run:
            continue
        run.update({
            "item_id": str(item_id),
            "videos": [],
            "video_count": 0,
            "video_cleared_at": _now(),
        })
        run.pop("video_check", None)
        run.pop("video_check_at", None)
        _write_json(folder / RUN_FILE, run)
        return run
    raise ClipStoreError(f"ไม่พบโฟลเดอร์งาน {item_id}")


def save_video_check(root: Path, item_id: str, result: dict) -> dict:
    """เก็บผลตรวจคลิป (ชัด 1080p ไหม · มีเสียงพูดไหม) — ผู้ใช้สั่ง 22 ส.ค. 2026

    **เก็บไว้ ไม่ตรวจใหม่ทุกครั้งที่เปิดดู** เพราะชั้นที่ฟังเสียงต้องยิงไปหา Gemini
    ทุกครั้ง ถ้าตรวจสดตอนกด /clips คนที่เปิดดูงานเดิมสิบรอบจะยิงสิบครั้ง แล้วโดน
    429 (เจอจริง 22 ส.ค.: ยิง 15 ครั้งรวดเดียวโดนตัดตั้งแต่ครั้งที่ 4)

    ผลผูกกับ **ไฟล์** ไม่ใช่กับงาน — เก็บชื่อไฟล์กับขนาดไว้ด้วย ถ้าวันหลังโหลด
    คลิปใหม่ทับ (เช่นอัปเป็น 1080p) ขนาดจะไม่ตรงแล้วตัวเรียกรู้ว่าผลเก่าใช้ไม่ได้
    """
    folder = target_dir(root, item_id)
    if not folder.is_dir():
        raise ClipStoreError(f"ไม่พบโฟลเดอร์งาน {item_id}")
    run = _read_json(folder / RUN_FILE)
    data = dict(result or {})
    data["at"] = _now()
    run.update({
        "item_id": str(item_id),
        "video_check": data,
        "video_check_at": data["at"],
    })
    _write_json(folder / RUN_FILE, run)
    return run


def save_fixed_prompt(
    root: Path, item_id: str, scene: int, prompt: str, script: list[str] | None = None,
) -> dict:
    """เก็บคำสั่ง+บทพูดที่ Gemini แก้ให้ผ่านนโยบายแล้ว (ผู้ใช้สั่ง 22 ส.ค. 2026)

    **เก็บแยก ไม่ทับของเดิม** — ของเดิมคือสิ่งที่ ChatGPT เขียนตามสตอรีบอร์ดที่
    ผู้ใช้อนุมัติไปแล้ว ถ้าทับทิ้งจะไม่มีทางรู้ว่าเนื้อหาถูกเปลี่ยนไปตรงไหนบ้าง
    ตัวที่แก้แล้วเก็บไว้ใช้ตอนเจนซ้ำ จะได้ไม่ต้องให้ Gemini แก้ใหม่ทุกครั้ง
    """
    folder = target_dir(root, item_id)
    if not folder.is_dir():
        raise ClipStoreError(f"ไม่พบโฟลเดอร์งาน {item_id}")
    run = _read_json(folder / RUN_FILE)
    fixed = dict(run.get("policy_fixed") or {})
    fixed[str(scene)] = {
        "prompt": prompt,
        "script": list(script or []),
        "at": _now(),
    }
    run.update({
        "item_id": str(item_id),
        "policy_fixed": fixed,
        "policy_fixed_at": _now(),
    })
    _write_json(folder / RUN_FILE, run)
    return run


def save_project_url(root: Path, item_id: str, url: str, scene: int = 0) -> dict:
    """เก็บลิงก์โปรเจกต์ Flow ของสินค้าชิ้นนี้ (ผู้ใช้สั่ง 22 ส.ค. 2026)

    เก็บ **ทุกฉาก** เพราะระบบสร้างโปรเจกต์ใหม่ต่อฉาก (ดู `_clip_generate`) ถ้าเก็บ
    ค่าเดียวจะรู้แค่ฉากสุดท้าย แล้วกลับไปโหลดฉากอื่นไม่ได้

    ใช้ตอนอยากกลับเข้าไปโหลดคลิปความละเอียดสูงกว่าเดิม หรือเจนซ้ำในโปรเจกต์เดิม
    โดยไม่ต้องเปิดไล่หาในหน้า Flow เอง
    """
    folder = target_dir(root, item_id)
    if not folder.is_dir():
        raise ClipStoreError(f"ไม่พบโฟลเดอร์งาน {item_id}")
    run = _read_json(folder / RUN_FILE)
    projects = dict(run.get("flow_projects") or {})
    projects[str(scene)] = url
    run.update({
        "item_id": str(item_id),
        "flow_projects": projects,
        "flow_project_url": url,          # ฉากล่าสุด — ไว้เปิดเร็วๆ
        "flow_project_at": _now(),
    })
    _write_json(folder / RUN_FILE, run)
    return run


def save_hashtags(root: Path, item_id: str, plan: dict) -> dict:
    """เก็บชุดแฮชแท็ก 5 ตัวของสินค้าชิ้นนั้น (ผู้ใช้สั่ง 22 ส.ค. 2026)

    เก็บ **ส่วนประกอบไว้ด้วย** ไม่ใช่แค่แท็กสำเร็จรูป — ผู้ใช้ต้องแก้ยี่ห้อ /
    ชนิดสินค้า / จุดเด่นได้ทีละชิ้นแล้วให้ระบบประกอบใหม่ ถ้าเก็บแต่แท็กสำเร็จ
    จะแก้ทีต้องพิมพ์ใหม่ทั้งตัว (เหตุผลเดียวกับที่ `hashtag.plan_for_run` คืน
    ส่วนประกอบกลับมาด้วย)
    """
    folder = target_dir(root, item_id)
    folder.mkdir(parents=True, exist_ok=True)
    run = _read_json(folder / RUN_FILE)
    tags = [str(tag) for tag in (plan.get("tags") or []) if str(tag).strip()]
    run.update({
        "item_id": str(item_id),
        "hashtags": tags,
        "hashtag_count": len(tags),
        "hashtag_parts": {
            "brand": plan.get("brand", ""),
            "kind": plan.get("kind", ""),
            "details": plan.get("details") or [],
        },
        "hashtag_at": _now(),
    })
    _write_json(folder / RUN_FILE, run)
    _to_drive(root, str(item_id))
    return run


# ปลายทางที่จะเอาคลิปไปโพสต์ — **เรียงตามลำดับที่ผู้ใช้สั่งให้ลง** (25 ส.ค. 2026)
#
#     Shopee Video → Facebook Reels → TikTok  ห่างกันอย่างน้อย 1 วัน (นับวันปฏิทิน)
#
# ลำดับกับระยะห่างบังคับใช้ที่ `publish_order.py` ที่เดียว ห้ามเขียนกติกาซ้ำที่อื่น
# เพราะตัวโพสต์มีสองระบบที่ไม่รู้จักกัน (มือถือ = Shopee/Facebook · เบราว์เซอร์ = TikTok)
PUBLISH_TARGETS = ("shopee_video", "facebook_reels", "tiktok")


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
    folder = target_dir(root, item_id)
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
    folder = target_dir(root, item_id)
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
    _to_drive(root, str(item_id))
    return run


def mark_posted(
    root: Path, item_id: str, target: str, url: str = "", error: str = ""
) -> dict:
    """บันทึกผลการโพสต์ของปลายทางหนึ่ง"""
    if target not in PUBLISH_TARGETS:
        raise ClipStoreError(f"ไม่รู้จักปลายทาง {target}")
    folder = target_dir(root, item_id)
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
    # **ย้ายโฟลเดอร์ตามสถานะใหม่ทันที** ลง Shopee แล้วต้องไปอยู่ clipsfb/
    refile(root, str(item_id))
    # ยกขึ้น Drive ทันที — หมวด 4 บน Drive ("โพสต์ช่องทางไหน เวลาเท่าไร") มีข้อมูล
    # ได้จากตรงนี้ที่เดียว ถ้าไม่ยกตรงนี้ ตารางการโพสต์จะค้างว่างจนกว่าจะมีคนสั่ง
    # sync เอง ซึ่งไม่มีทางรู้ว่าต้องสั่งเมื่อไร
    _to_drive(root, str(item_id))
    return run


def posted_history(root: Path) -> list[dict]:
    """**สมุดบันทึกการลง** — ลงอะไรไปแล้วบ้าง ที่ไหน เมื่อไร (ผู้ใช้สั่ง 27 ส.ค. 2569)

    *"ผมจำไม่ได้ว่าโพสต์อันไหนบ้าง ไม่มีลิ้สที่จดไว้ว่าลงแล้วหรอ บอกให้จด"*

    **ไม่สร้างที่เก็บใหม่ อ่านจากไฟล์งานที่มีอยู่แล้ว** — ทุกครั้งที่จดว่าลงแล้ว
    (`mark_posted`) เวลาถูกเขียนลง `publish.<ปลายทาง>.posted_at` อยู่แล้ว
    ถ้าไปทำสมุดแยกอีกเล่ม วันหนึ่งสองเล่มจะไม่ตรงกันแล้วไม่มีใครรู้ว่าเล่มไหนถูก
    (บทเรียนเดียวกับตอนกระดานกับ `/clips` นับไม่ตรงกัน)

    **อ่านทั้งโฟลเดอร์หลักและโฟลเดอร์ที่เก็บไปแล้ว** — งานที่ลงครบสามที่จะถูก
    ย้ายออกไป ถ้าอ่านแต่โฟลเดอร์หลัก สมุดจะลืมของที่ทำเสร็จสมบูรณ์ที่สุด

    คืนรายการเรียง **ใหม่สุดขึ้นก่อน** แต่ละรายการคือการลงหนึ่งครั้ง
    (คลิปหนึ่งใบลงสามที่ = สามรายการ)
    """
    out: list[dict] = []
    for run in list_runs(root) + list_done(root):
        publish = run.get("publish") or {}
        for target, info in publish.items():
            if not isinstance(info, dict) or info.get("status") != "posted":
                continue
            out.append({
                "item_id": str(run.get("item_id") or ""),
                "name": run.get("name") or "",
                "target": target,
                "at": info.get("posted_at") or "",
                "url": info.get("url") or "",
                # เคยถอนแล้วจดใหม่ไหม — ไว้ไล่ดูตอนสงสัยว่าจดผิด
                "reposted": bool(info.get("unposted_at")),
            })
    out.sort(key=lambda r: r["at"], reverse=True)
    return out


def unmark_posted(root: Path, item_id: str, target: str) -> dict:
    """ถอนการจดว่าลงปลายทางนั้นแล้ว — สำหรับตอนกดปุ่มผิดใบ

    **ต้องมีคู่กับ `mark_posted` เสมอ** ตั้งแต่ 27 ส.ค. 2569 ปุ่ม "✅ ทำแล้ว"
    ปุ่มเดียวเดินหน้าทั้งสาย (Shopee → Facebook → TikTok) กดพลาดหนึ่งทีคลิป
    จะข้ามไปรอปลายทางถัดไปทันที แล้วหายจากรายการเดิมโดยไม่มีทางกลับ

    **ไม่ลบร่องรอย แต่เปลี่ยนกลับเป็น "ยังไม่ลง"** เก็บ `unposted_at` ไว้ด้วย
    เผื่อวันหลังต้องไล่ดูว่ามีการถอนบ่อยผิดปกติตรงไหน
    """
    if target not in PUBLISH_TARGETS:
        raise ClipStoreError(f"ไม่รู้จักปลายทาง {target}")
    folder = target_dir(root, item_id)
    run = _read_json(folder / RUN_FILE)
    if not run:
        raise ClipStoreError(f"ไม่พบงานของสินค้า {item_id}")
    publish = run.get("publish") or {}
    if (publish.get(target) or {}).get("status") != "posted":
        raise ClipStoreError("ใบนี้ไม่ได้จดว่าลงปลายทางนั้นไว้")
    publish[target] = {
        "status": "pending", "posted_at": "", "url": "", "error": "",
        "unposted_at": _now(),
    }
    run["publish"] = publish
    _write_json(folder / RUN_FILE, run)
    refile(root, str(item_id))          # ถอนแล้วต้องย้ายกลับกองเดิม
    _to_drive(root, str(item_id))
    return run


def park_run(root: Path, item_id: str, why: str = "", stage: str = "") -> dict:
    """พักงานที่ **จบจากคิวไปแล้ว** ไว้รอแก้ (ผู้ใช้สั่ง 27 ส.ค. 2569)

    **ทำไมต้องมีแยกจากการพักในคิว** — งานที่เจนคลิปเสร็จแล้วจะออกจากคิวไป
    เหลือแต่ไฟล์งาน วัดจริง 27 ส.ค.: คลิปที่พร้อมลง Shopee มี 25 ใบ
    **มีใบงานในคิวแค่ 2 ใบ อีก 23 ใบจบจากคิวไปแล้ว**

    ถ้าปุ่มพักผูกกับคิวอย่างเดียว จะกดไม่ได้ 23 ใน 25 ใบ — ปุ่มที่กดแล้วขึ้น
    error เกือบทุกครั้งแย่กว่าไม่มีปุ่ม

    `stage` = ขั้นที่ค้างตอนถูกพัก ไม่ใส่มาจะเดาจากของที่มีในงาน (`clip_board`
    เป็นคนบอก) เก็บไว้เพื่อให้รู้ว่าต้องไปแก้อะไร ไม่ใช่แค่รู้ว่าพักไว้

    **ไม่ยกขึ้น Drive** ต่างจาก `mark_posted` โดยตั้งใจ — การพักไว้เป็นสถานะ
    ชั่วคราวของการทำงาน ไม่ใช่ผลลัพธ์ที่ต้องเก็บถาวร
    """
    folder = target_dir(root, item_id)
    run = _read_json(folder / RUN_FILE)
    if not run:
        raise ClipStoreError(f"ไม่พบงานของสินค้า {item_id}")
    run["parked"] = {
        "at": _now(),
        "from": str(stage or "").strip(),
        "why": str(why or "").strip(),
    }
    _write_json(folder / RUN_FILE, run)
    # พักแล้วย้ายเข้าโฟลเดอร์ wait* ของขั้นนั้น — เปิดดูแล้วรู้ทันทีว่าค้างตรงไหน
    run["folder"] = str(refile(root, str(item_id)))
    return run


def unpark_run(root: Path, item_id: str) -> dict:
    """เอางานที่พักไว้กลับมาอยู่ในรายการตามปกติ"""
    folder = target_dir(root, item_id)
    run = _read_json(folder / RUN_FILE)
    if not run:
        raise ClipStoreError(f"ไม่พบงานของสินค้า {item_id}")
    if not run.get("parked"):
        raise ClipStoreError("งานนี้ไม่ได้พักไว้")
    run.pop("parked", None)
    _write_json(folder / RUN_FILE, run)
    run["folder"] = str(refile(root, str(item_id)))     # กลับกองเดิม
    return run


# ------------------------------------------------------------------- อ่าน

def list_runs(root: Path) -> list[dict]:
    """รายการงานทั้งหมด ใหม่สุดขึ้นก่อน

    อ่านแค่ run.json ของแต่ละสินค้า ไม่แตะไฟล์ดิบ — หน้ารายการจะได้ไม่ช้าลง
    เมื่อสินค้าสะสมมากขึ้น
    """
    runs: list[dict] = []
    for name in ACTIVE_DIRS:
        base = Path(root) / name
        if not base.is_dir():
            continue
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


def list_done(root: Path) -> list[dict]:
    """งานที่ติ๊กว่าทำแล้ว — ใหม่สุดขึ้นก่อน (อ่านจาก `shopee_products_done/`)

    แยกเป็นฟังก์ชันของตัวเองแทนที่จะใส่ธงเลือกโฟลเดอร์ให้ `list_runs` เพราะที่
    เรียก list_runs มีหลายจุดทั่วระบบ (คิว · หน้าเว็บ · บอท) ถ้าเผลอส่งธงผิด
    จุดเดียว งานที่เก็บไปแล้วจะโผล่กลับมาปนในรายการหลักโดยไม่มีอะไรฟ้อง
    """
    base = Path(root) / DONE_DIR
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
    runs.sort(key=lambda r: r.get("done_at") or r.get("video_at") or "", reverse=True)
    return runs


def load_run(root: Path, item_id: str) -> dict:
    """งานหนึ่งชิ้นพร้อมของดิบ — ใช้ตอนเปิดดูรายละเอียด

    **ไล่หาทุกโฟลเดอร์** (`ALL_DIRS`) — เพื่อให้ทุกอย่างที่เปิดงานด้วยรหัสสินค้า
    (ส่งคลิปซ้ำ · ทำแฮชแท็ก · ดูรายละเอียด) ใช้ได้กับงานที่ย้ายไปโฟลเดอร์ไหนแล้ว
    ก็ตาม โดยไม่ต้องไล่แก้ทีละจุด — รหัสสินค้าไม่ซ้ำกันจึงไม่กำกวม
    """
    folder = target_dir(root, item_id)
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
    folder = target_dir(root, item_id).resolve()
    target = (folder / name).resolve()
    if folder != target and folder not in target.parents:
        raise ClipStoreError("ขอไฟล์นอกโฟลเดอร์งานไม่ได้")
    return target
