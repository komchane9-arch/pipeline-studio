"""กระดาน 6 ขั้น — งานไหนค้างอยู่ตรงไหน (ผู้ใช้สั่ง 26 ส.ค. 2026)

*"ตอนนี้ผมงงกับงานมากไม่รู้ว่าอันไหนอยู่ stage ไหนเท่าไรบ้าง"*

**ปัญหาเดิม** คิวมี 13 สถานะ (`clip_queue.OPEN_STAGES`) ซึ่งเป็นสถานะของ
**เครื่องจักร** ไม่ใช่ของคน — `ready_storyboard` กับ `making_storyboard` กับ
`storyboard_review` เป็นคนละสถานะ แต่สำหรับคนที่นั่งดูมันคือเรื่องเดียวกันหมด
คือ "ยังอยู่ช่วงทำสตอรีบอร์ด" พอเรียงรวมกันเป็นลิสต์เดียวจึงมองไม่ออกว่าค้างตรงไหน

**ที่ทำใหม่** ยุบเหลือ 6 กองตามที่ผู้ใช้วาดมา แต่ละกองคือ "สิ่งที่ต้องทำต่อ"
ไม่ใช่ "สถานะภายใน"

    1. ดึง Link        มีลิงก์แล้ว รอดึงข้อมูล
    2. Storyboard      ดึงข้อมูลเสร็จ รอตรวจ/อนุมัติจนได้สตอรีบอร์ด + บทพูด
    3. Clip            มีคลิปแล้ว รออนุมัติคลิป
    4. Shopee Video    อนุมัติคลิปแล้ว รอโพสต์ Shopee Video
    5. Facebook Reels  ลง Shopee แล้ว รอโพสต์ Facebook Reels
    6. TikTok          ลง Facebook แล้ว รอโพสต์ TikTok

**กติกาข้อ 4-6 ต้องมาจาก `publish_order` เท่านั้น ห้ามคิดเอง**
เพราะนั่นคือด่านตัวเดียวกับที่กั้นก่อนโพสต์จริง (กติกาข้อ 2.8 ของโปรเจกต์)
ถ้าเขียนแยกกันสองชุด วันหลังจะกลายเป็น "กระดานบอกว่าพร้อมลง แต่กดแล้วด่านปฏิเสธ"
แล้วไม่มีใครรู้ว่าฝั่งไหนถูก

**งานที่ล้ม/ยกเลิกไม่เข้ากองไหนเลย** — กองทั้ง 6 คือของที่ยังเดินต่อได้
ของที่ล้มมีที่ของมันอยู่แล้ว (รายการงานที่เก็บไว้) เอามาปนจะทำให้ตัวเลขในวงเล็บ
โกหกว่ามีงานค้างเยอะกว่าความจริง
"""

from __future__ import annotations

import clip_queue
import publish_order

# ---------------------------------------------------------------- นิยามกอง

# เส้นวัดสต๊อกของแต่ละขั้น (ผู้ใช้สั่ง 26 ส.ค. 2026)
#
# *"แต่ละขั้นจะมี stock 10 อันทุกขั้น และถ้าขั้นถัดไป stock เหลือ 9
#   ขั้นก่อนหน้าให้สั่งทำไปเติมให้ครบ 10 เสมอ"*
# *"stock สามารถใส่เกิน 10 ได้ แต่ตัว 10 คือตัววัด ถ้าน้อยกว่าให้นำมาเติม"*
#
# **10 เป็นเส้นวัด ไม่ใช่เพดาน** — มีเกิน 10 ได้ ไม่ต้องหยุดรับงาน
# ต่ำกว่า 10 เมื่อไรถึงจะนับว่า "ต้องเติม"
STOCK_TARGET = 10

LINK = "link"
STORY = "story"
CLIP = "clip"
SHOPEE = "shopee_video"
REELS = "facebook_reels"
TIKTOK = "tiktok"
FIX = "fix"

# ขั้นในคิวที่ยังไม่ถึงมือคน — งานกำลังเดินอยู่ ยังไม่ต้องตัดสินใจอะไร
LINK_STAGES = {clip_queue.STAGE_QUEUED, clip_queue.STAGE_COLLECTING}

# ทุกขั้นระหว่าง "ได้ข้อมูลสินค้าแล้ว" ถึง "ได้สตอรีบอร์ด + บทพูดครบ"
STORY_STAGES = {
    clip_queue.STAGE_IMAGE_REVIEW,
    clip_queue.STAGE_READY_STORYBOARD,
    clip_queue.STAGE_MAKING,
    clip_queue.STAGE_STORYBOARD_REVIEW,
    clip_queue.STAGE_SCRIPT_REVIEW,
    clip_queue.STAGE_REVISING,
}

# ช่วงเจนคลิปจนถึงรออนุมัติคลิป
CLIP_STAGES = {
    clip_queue.STAGE_READY_FLOW,
    clip_queue.STAGE_GENERATING,
    clip_queue.STAGE_VIDEO_REVIEW,
}

# อีโมจิ + ชื่อของแต่ละกอง
#
# **สีอยู่ฝั่งหน้าเว็บ ไม่ได้ส่งมาจากที่นี่** — สีเป็นเรื่องของการแสดงผล ถ้าส่งค่าสี
# มาจากเซิร์ฟเวอร์ วันหลังเปลี่ยนธีมมืด/สว่างจะต้องมาแก้ที่ Python ด้วย
# ฝั่งหน้าเว็บผูกสีกับ **รหัสกอง** (`key`) ซึ่งไม่มีวันเปลี่ยน
BOARD = (
    (LINK,   "🐣 ดึง Link",        "มีลิงก์แล้ว รอดึงข้อมูลสินค้า"),
    (STORY,  "🎨 Storyboard",      "ได้ข้อมูลแล้ว รอตรวจรูป · จุดเด่น · สตอรีบอร์ด · บทพูด"),
    (CLIP,   "🎬 Clip",            "มีคลิปแล้ว รออนุมัติก่อนโพสต์"),
    (SHOPEE, "🛍️ Shopee Video",    "อนุมัติคลิปแล้ว รอลง Shopee Video"),
    (REELS,  "💙 Facebook Reels",  "ลง Shopee แล้ว รอลง Facebook Reels"),
    (TIKTOK, "🎵 TikTok",          "ลง Facebook แล้ว รอลง TikTok"),
    (FIX,    "🅿️ รอแก้",           "พักไว้ก่อน รอคุณกลับมาแก้ — เครื่องจะไม่แตะจนกว่าจะเอากลับ"),
)

# กองที่ **ไม่มีเส้นวัด 10** — รอแก้ยิ่งน้อยยิ่งดี ไม่ใช่ของที่ต้องมีสำรองไว้
#
# ถ้าใส่เส้นวัดให้ด้วย หน้าเว็บจะขึ้นว่า "ขาดอีก 10 ใบ" ซึ่งกลับหัวกลับหางกับ
# ความจริง แล้วคนอ่านจะเข้าใจว่าต้องไปหางานพังมาเติม
NO_TARGET = {FIX}

# ปลายทางของกองที่ 4-6 → ชื่อที่ `publish_order` ใช้
POST_TARGET = {SHOPEE: "shopee_video", REELS: "facebook_reels", TIKTOK: "tiktok"}


def bucket_of(job: dict, run: dict | None = None) -> tuple[str, str]:
    """งานใบนี้อยู่กองไหน — คืน (รหัสกอง, เหตุผลภาษาคน)

    คืนกองว่างถ้างานจบ/ล้ม/ยกเลิก หรือยังตอบไม่ได้
    """
    stage = (job or {}).get("stage") or ""
    # **พักไว้รอแก้ = ไปกองรอแก้เสมอ ไม่ว่าค้างอยู่ขั้นไหน** (ผู้ใช้สั่ง 27 ส.ค. 2026)
    #
    # ต้องตรวจก่อนทุกข้ออื่น เพราะใบที่พักไว้ยังคงสถานะเดิมของมันไว้ครบ (ตั้งใจ
    # ให้เป็นแบบนั้น จะได้เอากลับเข้าขั้นเดิมได้โดยไม่ต้องเดา) ถ้าตรวจทีหลัง
    # มันจะไปโผล่ในกองเดิมด้วย = อยู่สองที่พร้อมกัน แล้วตัวเลขในวงเล็บจะเกินจริง
    parked = (job or {}).get("parked") or {}
    if parked:
        why = parked.get("why") or "พักไว้รอแก้"
        came = clip_queue.STAGE_LABEL.get(parked.get("from") or stage,
                                          parked.get("from") or stage)
        return FIX, f"ค้างที่ขั้น “{came}” · {why}"
    if stage in LINK_STAGES:
        return LINK, clip_queue.STAGE_LABEL.get(stage, stage)
    if stage in STORY_STAGES:
        return STORY, clip_queue.STAGE_LABEL.get(stage, stage)
    if stage in CLIP_STAGES:
        return CLIP, clip_queue.STAGE_LABEL.get(stage, stage)

    # ---- เลยขั้นคลิปแล้ว = ไปอยู่กองปลายทางที่ถึงคิวลง ---------------------
    #
    # ใช้ `publish_order.next_target()` ตัวเดียวกับด่านก่อนโพสต์ ไม่คิดเอง
    if run is None:
        return "", ""
    target = publish_order.next_target(run)
    if not target:
        return "", ""                       # ลงครบทั้งสามที่แล้ว
    for key, name in POST_TARGET.items():
        if name == target:
            ok, why = publish_order.check(run, target)
            return key, (why if not ok else "พร้อมลงได้เลย")
    return "", ""


def bucket_of_run(run: dict) -> str:
    """งานที่เก็บไว้ (run.json ล้วน ไม่มีใบงานในคิว) อยู่กองไหน

    ผู้ใช้สั่ง 26 ส.ค. 2026: *"แยกงานที่เก็บไว้ตามแต่ละขั้นเลย"*

    **ตัดสินจากของที่มีอยู่จริงในงาน ไม่ใช่จากสถานะคิว** เพราะงานพวกนี้ออกจากคิว
    ไปแล้ว (จบ/ถูกเก็บ) สิ่งเดียวที่บอกได้ว่าไปถึงไหนคือ **มีอะไรอยู่ในโฟลเดอร์**
    — มีรูปไหม มีสตอรีบอร์ดไหม มีคลิปไหม ลงไปที่ไหนแล้วบ้าง

    คืนค่าว่าง = ลงครบทั้งสามที่แล้ว ไม่ต้องทำอะไรต่อ จึงไม่เข้ากองไหน
    """
    if not run:
        return ""
    if not (run.get("images") or []):
        return LINK
    if not (run.get("storyboard") or []) and not (run.get("script") or []):
        return STORY
    if not (run.get("videos") or []):
        return CLIP
    target = publish_order.next_target(run)
    for key, name in POST_TARGET.items():
        if name == target:
            return key
    return ""


def build(jobs: list[dict], load_run) -> dict:
    """จัดงานทั้งหมดลง 6 กอง — `load_run(item_id)` คืน run.json ของงานนั้น

    **โหลด run.json เฉพาะงานที่จำเป็น** งานที่ยังไม่ถึงขั้นโพสต์ตัดสินจากสถานะ
    ในคิวได้เลย ไม่ต้องอ่านไฟล์ — คิวมีเป็นร้อยใบ ถ้าอ่านหมดทุกครั้งที่เปิดหน้า
    จะช้าโดยไม่จำเป็น
    """
    piles: dict[str, list[dict]] = {key: [] for key, _, _ in BOARD}
    for job in jobs or []:
        stage = job.get("stage") or ""
        run = None
        # **ใบที่พักไว้รอแก้เข้ากองรอแก้เสมอ ไม่ต้องไปอ่านไฟล์อะไรทั้งนั้น**
        #
        # ต้องดักก่อนด่านข้างล่าง เพราะใบที่ "ล้มแล้วพักไว้รอแก้" จะโดนกรองทิ้ง
        # ตรงบรรทัด failed/cancelled — ซึ่งเป็นเคสที่ผู้ใช้อยากเห็นที่สุด
        if job.get("parked"):
            key, why = bucket_of(job, None)
            piles[key].append({
                "id": job.get("id"),
                "item_id": job.get("item_id") or "",
                "name": job.get("name") or job.get("link") or "(ยังไม่รู้ชื่อสินค้า)",
                "stage": stage,
                "stage_label": clip_queue.STAGE_LABEL.get(stage, stage),
                "why": why,
                "parked": job.get("parked"),
                "created_at": job.get("created_at") or "",
                "updated_at": job.get("updated_at") or "",
            })
            continue
        if stage not in LINK_STAGES | STORY_STAGES | CLIP_STAGES:
            if stage in {clip_queue.STAGE_FAILED, clip_queue.STAGE_CANCELLED}:
                continue                    # ของที่ล้มมีที่ของมันเอง
            item_id = job.get("item_id") or ""
            if not item_id:
                continue
            try:
                run = load_run(item_id)
            except Exception:                # noqa: BLE001
                run = None
            if not run:
                continue
        key, why = bucket_of(job, run)
        if not key:
            continue
        piles[key].append({
            "id": job.get("id"),
            "item_id": job.get("item_id") or "",
            "name": job.get("name") or job.get("link") or "(ยังไม่รู้ชื่อสินค้า)",
            "stage": stage,
            "stage_label": clip_queue.STAGE_LABEL.get(stage, stage),
            "why": why,
            "created_at": job.get("created_at") or "",
            "updated_at": job.get("updated_at") or "",
        })

    counts = {key: len(rows) for key, rows in piles.items()}
    return {
        "buckets": [
            {"key": key, "title": title, "hint": hint,
             "count": counts[key],
             # กองรอแก้ไม่มีเส้นวัด — ยิ่งน้อยยิ่งดี ไม่ใช่ของที่ต้องมีสำรอง
             "target": 0 if key in NO_TARGET else STOCK_TARGET,
             # ขาดอีกกี่ใบถึงจะถึงเส้นวัด — 0 = ถึงแล้วหรือเกินแล้ว
             "short": 0 if key in NO_TARGET else max(0, STOCK_TARGET - counts[key]),
             # **บอกวิธีเติมด้วย ไม่ใช่บอกแค่ว่าขาด**
             "refill": "" if key in NO_TARGET else refill_hint(key, counts),
             "jobs": piles[key]}
            for key, title, hint in BOARD
        ],
        "total": sum(counts.values()),
        "target": STOCK_TARGET,
    }


def refill_hint(key: str, counts: dict[str, int]) -> str:
    """ขาดอยู่ต้องทำอะไรถึงจะเติมได้ — คืนค่าว่างถึงเส้นวัดแล้ว

    **ต้องบอกวิธี ไม่ใช่บอกแค่ตัวเลข** ตัวเลข "ขาด 8" ตอบไม่ได้ว่าต้องทำอะไรต่อ
    และแต่ละขั้นเติมด้วยวิธีคนละอย่างสิ้นเชิง — ต้นน้ำเติมด้วยการส่งลิงก์
    กลางน้ำเติมด้วยการกดอนุมัติ ปลายน้ำเติมด้วยการรอครบวัน

    **ขั้นที่ต้องให้คนกดอนุมัติ ระบบเติมเองไม่ได้และไม่ควรได้** — 26 ส.ค. 2026
    เพิ่งเจอมาแล้วว่าคลิปที่ผ่านทุกด่านอัตโนมัติยังโดน Shopee ลบเพราะภาพบนจอ
    ถ้าให้ระบบอนุมัติเองแล้วโพสต์เลย ความเสียหายคือคะแนนสะสมจนแบนถาวร ซึ่งกู้ไม่ได้
    """
    short = max(0, STOCK_TARGET - counts.get(key, 0))
    if not short:
        return ""
    if key == LINK:
        return f"ส่งลิงก์สินค้าเพิ่มอีก {short} ใบ"
    if key == STORY:
        waiting = counts.get(LINK, 0)
        if waiting:
            return f"มีลิงก์รอดึงอยู่ {waiting} ใบ — ระบบกำลังทยอยทำให้"
        return f"ส่งลิงก์สินค้าเพิ่มอีก {short} ใบ (ต้นน้ำว่าง)"
    if key == CLIP:
        ready = counts.get(STORY, 0)
        if ready:
            return f"กดผ่านสตอรีบอร์ด + บทพูดอีก {min(short, ready)} ใบ"
        return f"ต้นน้ำว่าง — ส่งลิงก์เพิ่มอีก {short} ใบก่อน"
    if key == SHOPEE:
        ready = counts.get(CLIP, 0)
        if ready:
            return f"กดอนุมัติคลิปอีก {min(short, ready)} ใบ"
        return f"ยังไม่มีคลิปให้อนุมัติ — เติมต้นน้ำก่อน"
    if key == REELS:
        return "ลง Shopee Video ก่อน แล้วเว้น 1 วันปฏิทินถึงจะลง Facebook ได้"
    if key == TIKTOK:
        return "ลง Facebook Reels ก่อน แล้วเว้น 1 วันปฏิทินถึงจะลง TikTok ได้"
    return ""
