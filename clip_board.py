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
# กองปลายทางที่ **เดินต่อไม่ได้** — หาสินค้าเดียวกันใน TikTok Shop ไม่เจอ
# เจ้าของสั่ง 13 ก.ย. 2569: *"เพิ่มช่องหน่อย อีกช่องว่าไม่มีสินค้าใน tiktok
# แล้วใบงานไหนไม่มีให้ย้ายไปช่องนั้น"*
NO_SHOP = "tiktok_no_shop"
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

# ============================================================================
# กองรอแก้ — **แยกย่อยตามชนิดของการแก้** (ผู้ใช้สั่ง 27 ส.ค. 2026)
# ============================================================================
#
# *"รอแก้แต่ละขั้นให้เก็บแยกกันนะ ทั้งในเว็บและใน telegram เพราะการแก้แต่ละอย่าง
#   ไม่เหมือนกัน"*
#
# **แยกละเอียดกว่ากอง 6 ขั้นบนกระดานโดยตั้งใจ** — บนกระดาน `image_review`,
# `storyboard_review` และ `script_review` อยู่กอง Storyboard เหมือนกันหมด
# เพราะมองจาก "ไปถึงไหนแล้ว" แต่พอเป็นการแก้ มัน **คนละงานกันสิ้นเชิง**
#
#     ค้างที่ชุดรูป      → ไปหารูปเพิ่ม/สลับรูป แล้วกดผ่าน
#     ค้างที่สตอรีบอร์ด  → พิมพ์คอมเมนต์สั่งแก้ แล้วให้ GPT ทำใหม่
#     ค้างที่บทพูด       → แก้ข้อความบทพูดเอง
#     ค้างที่คลิป        → สั่งเจนใหม่ (เสียเครดิต Veo)
#
# รวมกองเดียวแล้วเปิดมาเจอปนกัน จะแก้ทีละใบสลับไปมาซึ่งช้ากว่าแก้ทีเดียวทั้งกอง
#
# `hint` = **บอกว่าต้องทำอะไรถึงจะแก้ได้** ไม่ใช่บอกแค่ว่าค้างตรงไหน
FIX_GROUPS = (
    ("images", "🖼 ชุดรูป",
     "เปิดใบงานแล้วสลับ/เพิ่มรูป หรือกดให้ AI คัดใหม่ แล้วกดผ่าน",
     {clip_queue.STAGE_IMAGE_REVIEW}),
    ("storyboard", "🎨 สตอรีบอร์ด",
     "พิมพ์คอมเมนต์บอกว่าจะแก้อะไร แล้วให้ GPT ทำใหม่",
     {clip_queue.STAGE_STORYBOARD_REVIEW, clip_queue.STAGE_READY_STORYBOARD,
      clip_queue.STAGE_MAKING, clip_queue.STAGE_REVISING}),
    ("script", "💬 บทพูด",
     "แก้ข้อความบทพูดเองในใบงาน หรือสั่งให้เขียนใหม่",
     {clip_queue.STAGE_SCRIPT_REVIEW}),
    ("clip", "🎬 คลิป",
     "ดูคลิปแล้วสั่งเจนใหม่ — ⚠️ เสียเครดิต Veo ทุกครั้งที่เจน",
     {clip_queue.STAGE_VIDEO_REVIEW, clip_queue.STAGE_READY_FLOW,
      clip_queue.STAGE_GENERATING}),
    ("link", "🐣 ดึงข้อมูล",
     "ลิงก์อาจเสียหรือ Shopee บล็อกอยู่ — ลองเปิดลิงก์ดูเองก่อน",
     {clip_queue.STAGE_QUEUED, clip_queue.STAGE_COLLECTING}),
    ("post", "🛍 ตอนโพสต์",
     "ติดตอนลงแพลตฟอร์ม — ดูว่าค้างขั้นไหนบนมือถือ",
     {clip_queue.STAGE_POST_REVIEW, clip_queue.STAGE_POSTING}),
    ("failed", "💥 ล้มแล้วพักไว้",
     "ล้มก่อนถูกพัก — อ่านเหตุผลในใบงานก่อนสั่งทำต่อ",
     {clip_queue.STAGE_FAILED, clip_queue.STAGE_CANCELLED}),
)

# ค้างที่ขั้นที่ไม่รู้จัก — ต้องมีที่ลง ไม่งั้นใบนั้นหายจากทุกกองเงียบๆ
FIX_OTHER = ("other", "❓ อื่นๆ", "ขั้นที่ระบบยังไม่รู้จัก — เปิดใบงานดูเอง")


# งานที่ออกจากคิวไปแล้วไม่มี "ขั้นในคิว" ให้จด — ตอนพักจึงจดเป็น **ชื่อกองบนกระดาน**
# แทน (`shopee_video` · `facebook_reels` · `tiktok`) ตารางนี้แปลกลับให้ตัวจัดกลุ่ม
#
# **ถ้าไม่มีตารางนี้** ใบที่พักตอนรอลง Shopee จะแปลไม่ออกแล้วตกไปกอง 🎬 คลิป
# ทั้งกอง — เจอจริงตอนทดสอบ 27 ส.ค. 2569 (พักใบรอลง Shopee แล้ว /waitclips
# บอกว่าว่าง ส่วน /waitclip กลับมีใบนั้นอยู่)
BOARD_KEY_FIX_GROUP = {
    LINK: "link", STORY: "storyboard", CLIP: "clip",
    SHOPEE: "post", REELS: "post", TIKTOK: "post", NO_SHOP: "post",
}


def fix_group_of(stage: str) -> str:
    """ใบที่พักไว้จากขั้นนี้ ควรอยู่กลุ่มการแก้ไหน

    รับได้ทั้ง **ขั้นในคิว** (`image_review`) และ **ชื่อกองบนกระดาน**
    (`shopee_video`) เพราะสองที่เก็บจดคนละแบบ — ดู `BOARD_KEY_FIX_GROUP`
    """
    for key, _label, _hint, stages in FIX_GROUPS:
        if stage in stages:
            return key
    if stage in BOARD_KEY_FIX_GROUP:
        return BOARD_KEY_FIX_GROUP[stage]
    return FIX_OTHER[0]


def fix_group_meta(key: str) -> tuple[str, str]:
    """(ชื่อกลุ่ม, วิธีแก้) ของกลุ่มนั้น"""
    for gkey, label, hint, _stages in FIX_GROUPS:
        if gkey == key:
            return label, hint
    return FIX_OTHER[1], FIX_OTHER[2]


def group_parked(rows: list[dict]) -> list[dict]:
    """จัดใบที่พักไว้เป็นกลุ่มตามชนิดของการแก้ — ใช้ร่วมกันทั้งหน้าเว็บและแชท

    **ต้องมีที่เดียวแล้วเรียกร่วมกัน** ไม่งั้นวันหนึ่งหน้าเว็บกับแชทจะจัดกลุ่ม
    ไม่ตรงกัน แล้วไม่มีใครรู้ว่าอันไหนถูก (บทเรียนเดียวกับ `/clips` ที่เลขในรายการ
    เคยไม่ตรงกับเลขที่พิมพ์)

    เรียงกลุ่มตามลำดับใน `FIX_GROUPS` = ตามลำดับสายพาน ต้นน้ำก่อนปลายน้ำ
    กลุ่มที่ว่างไม่ถูกส่งไป — คนอ่านไม่ต้องกวาดตาผ่านกองเปล่า
    """
    piles: dict[str, list[dict]] = {}
    for row in rows or []:
        came = ((row.get("parked") or {}).get("from")
                or row.get("stage") or "")
        piles.setdefault(fix_group_of(came), []).append(row)

    order = [key for key, _l, _h, _s in FIX_GROUPS] + [FIX_OTHER[0]]
    out = []
    for key in order:
        items = piles.get(key)
        if not items:
            continue
        label, hint = fix_group_meta(key)
        out.append({"key": key, "title": label, "hint": hint,
                    "count": len(items), "jobs": items})
    return out


def parked_by_bucket(rows: list[dict]) -> list[dict]:
    """จัดใบที่พักไว้ตาม **กองบนกระดาน** แล้วแยกย่อยตามชนิดการแก้ข้างใน

    ใช้โดยฝั่งแชท (`/wait`) เพื่อให้เห็นโครงเดียวกับหน้าเว็บเป๊ะ — หน้าเว็บได้
    ของนี้มาจาก `build()` อยู่แล้ว แต่แชทมีแค่รายการใบที่พักไว้ล้วนๆ

    **ห้ามฝั่งแชทจัดกลุ่มเอง** ไม่งั้นวันหนึ่งจะบอกไม่ตรงกับหน้าเว็บแล้วไม่มีใคร
    รู้ว่าอันไหนถูก (บทเรียนเดียวกับตอน `/clips` เลขในรายการไม่ตรงกับเลขที่พิมพ์)
    """
    piles: dict[str, list[dict]] = {}
    board_keys = {key for key, _t, _h in BOARD}
    for row in rows or []:
        came = (row.get("parked") or {}).get("from") or row.get("stage") or ""
        # จดมาเป็นชื่อกองอยู่แล้ว (งานที่ออกจากคิวไปแล้ว) ใช้ได้เลย ไม่ต้องแปล
        key = came if came in board_keys else bucket_of({"stage": came}, None)[0]
        piles.setdefault(key or CLIP, []).append(row)

    out = []
    for key, title, _hint in BOARD:
        items = piles.get(key)
        if not items:
            continue
        # เรียงในกองตามชนิดการแก้ ต้นน้ำก่อนปลายน้ำ — แก้ทีเดียวทั้งชนิดได้
        order = {g: i for i, (g, _l, _h, _s) in enumerate(FIX_GROUPS)}
        items.sort(key=lambda r: order.get(
            fix_group_of((r.get("parked") or {}).get("from") or r.get("stage") or ""), 99))
        out.append({"key": key, "title": title, "count": len(items), "jobs": items})
    return out


# อีโมจิ + ชื่อของแต่ละกอง
#
# **สีอยู่ฝั่งหน้าเว็บ ไม่ได้ส่งมาจากที่นี่** — สีเป็นเรื่องของการแสดงผล ถ้าส่งค่าสี
# มาจากเซิร์ฟเวอร์ วันหลังเปลี่ยนธีมมืด/สว่างจะต้องมาแก้ที่ Python ด้วย
# ฝั่งหน้าเว็บผูกสีกับ **รหัสกอง** (`key`) ซึ่งไม่มีวันเปลี่ยน
BOARD = (
    (LINK,   "🐣 ดึง Link",        "มีลิงก์แล้ว รอดึงข้อมูลสินค้า"),
    (STORY,  "🎨 Storyboard",      "ได้ข้อมูลแล้ว รอตรวจรูป · จุดเด่น · สตอรีบอร์ด · บทพูด"),
    (CLIP,   "🎬 Clip",            "รอเจนคลิป หรือมีคลิปแล้วรออนุมัติก่อนโพสต์"),
    (SHOPEE, "🛍️ Shopee Video",    "อนุมัติคลิปแล้ว รอลง Shopee Video"),
    (REELS,  "💙 Facebook Reels",  "ลง Shopee แล้ว รอลง Facebook Reels"),
    (TIKTOK, "🎵 TikTok",          "ลง Facebook แล้ว รอลง TikTok"),
    (NO_SHOP, "🚫 ไม่มีสินค้าใน TikTok",
     "หาสินค้าเดียวกันใน TikTok Shop ไม่เจอ — ลงไม่ได้จนกว่าร้านจะมีของ"),
)

# **ไม่มีกอง "รอแก้" แยกต่างหากแล้ว** (ผู้ใช้สั่งแก้ 27 ส.ค. 2026)
# ใบที่พักไว้ไปอยู่ใต้กองของขั้นที่มันค้าง แยกถังในฟิลด์ `parked` ของกองนั้น
# `FIX` ยังเก็บไว้เป็นรหัสของ "ชนิดการแก้" ที่ `FIX_GROUPS` ใช้ ไม่ใช่กองบนกระดาน
# กองที่ **ไม่มีเส้นวัด** — ยิ่งน้อยยิ่งดี ไม่ใช่ของที่ต้องมีสำรองไว้
#
# กองพวกนี้ต้องส่ง target = 0 ไม่งั้นหน้าเว็บจะขึ้นว่า "(55/10)" ซึ่งอ่านว่า
# "55 จากสต๊อกที่อยากมี 10" — ชวนให้เข้าใจว่ายังขาดอีก ทั้งที่ความจริงคือ
# ยิ่งเยอะยิ่งแย่ (สายกลางจับได้ตอนเทสหน้าเว็บจริง 13 ก.ย. 2569)
NO_TARGET: set[str] = {NO_SHOP}

# ปลายทางของกองที่ 4-6 → ชื่อที่ `publish_order` ใช้
POST_TARGET = {SHOPEE: "shopee_video", REELS: "facebook_reels", TIKTOK: "tiktok"}


def _link_file(layout: str | None, name: str) -> str:
    """ชื่อไฟล์ภาพรวมผลค้นหา — ว่างเมื่อรอบนั้นไม่ได้เก็บภาพรวมไว้"""
    return name if layout else ""


def tiktok_product_missing(run: dict | None) -> str:
    """หาสินค้าเดียวกันใน TikTok Shop ไม่เจอหรือเปล่า — คืนเหตุผล ว่าง = เจอ/ยังไม่ได้หา

    **ดูของที่มีเฉพาะตอนหาไม่เจอ** คือ ``matched_rank == 0`` ซึ่งแปลว่าตัวดูรูป
    เทียบผลค้นหาทุกอันแล้วไม่มีอันไหนเป็นสินค้าตัวเดียวกัน — ต่างจาก
    ``matched_rank`` ที่ยังไม่มีค่า ซึ่งแปลว่า **ยังไม่ได้หา** (กติกา 2.3.1)

    ใบพวกนี้เดินต่อไม่ได้เลยไม่ว่าจะลองอีกกี่รอบ เพราะ TikTok Shop ไม่มีของขาย
    วัดจริง 13 ก.ย. 2569: 53 ใบจาก 78 ใบที่เคยหา · เหตุผลที่จดไว้เป็นการเทียบ
    ของจริง เช่น "เป้าหมายเป็นเคสมือถือลาย Hello Kitty แต่ผลค้นหาสี่อันแรก
    เป็นเคสลายอื่น"
    """
    link = (run or {}).get("tiktok_product_link") or {}
    if not link or link.get("showcase_added"):
        return ""
    if link.get("matched_rank") != 0:
        return ""                      # ยังไม่ได้หา หรือหาเจอแล้ว
    # **ต้องเป็นภาษาที่เจ้าของอ่านรู้เรื่อง** (กติกา 5.2) — เหตุผลดิบของตัวดูรูป
    # เป็นภาษาอังกฤษที่เขียนให้ AI อ่าน ไม่ใช่ให้คนอ่าน เช่น
    # "The TARGET product is a 55Q7D Pro SQD-Mini LED TV, while the first two..."
    # ข้อความเต็มยังอยู่ครบในฟิลด์ `tiktok_link_reason` ของแถว กดดูได้
    #
    # ใส่ **คำที่บอทใช้ค้นจริง** มาด้วย เพราะบางใบหาไม่เจอเพราะคำค้นยาวเกินไป
    # ซึ่งแก้ได้ ต่างจากใบที่ร้านไม่มีของจริงซึ่งแก้ไม่ได้ — เห็นคำค้นแล้วแยกออก
    query = " ".join(str(link.get("search_query") or "").split())
    if query:
        return (f"ไม่เจอสินค้าตัวนี้ใน TikTok Shop — ที่ค้นเจอเป็นรุ่นอื่น "
                f"(ค้นด้วย: {query[:70]}{'…' if len(query) > 70 else ''})")
    return "ไม่เจอสินค้าตัวนี้ใน TikTok Shop — ที่ค้นเจอเป็นรุ่นอื่น"


def active_auto_skip_target(run: dict | None) -> str:
    """ปลายทางที่ใบนี้ถูกกันออกจากอัตโนมัติอยู่ — ว่างเมื่อแก้ลิงก์แล้ว."""
    run = run or {}
    target = publish_order.next_target(run) or ""
    state = ((run.get("publish") or {}).get(target) or {})
    if (state.get("auto_skip")
            and str(state.get("auto_skip_link") or "").strip()
            == str(run.get("affiliate_url") or "").strip()):
        return target
    return ""


def bucket_of(job: dict, run: dict | None = None) -> tuple[str, str]:
    """งานใบนี้อยู่กองไหน — คืน (รหัสกอง, เหตุผลภาษาคน)

    คืนกองว่างถ้างานจบ/ล้ม/ยกเลิก หรือยังตอบไม่ได้
    """
    stage = (job or {}).get("stage") or ""
    # ใบที่ถูกแบนคือหลักฐานย้อนหลัง ไม่ใช่งานที่ต้องเดินต่อ ห้ามให้สถานะคิวเก่า
    # (เช่น ready_flow) ดึงกลับเข้ากอง Clip และเผลอเจนซ้ำ
    if run and run.get("banned"):
        return "", ""
    # **ใบที่พักไว้รอแก้ อยู่ใต้กองของขั้นที่มันค้าง** (ผู้ใช้สั่งแก้ 27 ส.ค. 2026)
    #
    # *"ตัวรอแก้ให้ใส่ในแต่ละใต้ stage แยกกันเลย ว่ารอแก้ stage ไหน"*
    #
    # รอบแรกทำเป็นกองที่ 7 รวมทุกขั้นไว้ด้วยกัน **ซึ่งผิดที่** เพราะพอเปิดกองนั้น
    # ต้องมาไล่อ่านอีกทีว่าใบไหนค้างขั้นไหน ทั้งที่ข้อมูลนั้นมีอยู่แล้ว
    # ตอนนี้อยู่ในกองของขั้นที่ค้าง แต่ `build()` แยกออกจากงานที่เดินได้คนละถัง
    # (ฟิลด์ `parked`) — เห็นทันทีว่าขั้นนี้มีของรอแก้กี่ใบ โดยตัวเลขงานที่เดินได้ไม่เพี้ยน
    #
    # ตัดสินจาก **ขั้นที่ค้างตอนถูกพัก** ไม่ใช่สถานะปัจจุบัน เพราะใบที่ล้มแล้วถูกพัก
    # จะมีสถานะเป็น failed ซึ่งไม่ได้บอกอะไรเลยว่าต้องไปแก้ตรงไหน
    parked = (job or {}).get("parked") or {}
    if parked:
        stage = parked.get("from") or stage
    # ใบที่นำเข้าลิงก์แล้ว Shopee ตอบว่าไม่มีสินค้า ต้องอยู่ให้เห็นในกอง
    # Shopee Video แม้ใบงานเก่าในคิวยังค้างป้าย video_review อยู่ก็ตาม
    # นี่ไม่ใช่การพักทั้งใบ: แค่กันตัวโพสต์อัตโนมัติจนกว่าลิงก์จะถูกแก้
    skipped_target = active_auto_skip_target(run)
    if skipped_target:
        for key, target in POST_TARGET.items():
            if target == skipped_target:
                state = ((run or {}).get("publish") or {}).get(target) or {}
                return key, str(state.get("error") or "ข้ามอัตโนมัติจนกว่าจะแก้ลิงก์")
    if stage in LINK_STAGES:
        return LINK, clip_queue.STAGE_LABEL.get(stage, stage)
    if stage in STORY_STAGES:
        return STORY, clip_queue.STAGE_LABEL.get(stage, stage)
    if stage in CLIP_STAGES:
        return CLIP, clip_queue.STAGE_LABEL.get(stage, stage)

    # ---- เลยขั้นคลิปแล้ว = ตัดสินจาก **ของที่มีอยู่จริงในโฟลเดอร์** -------
    #
    # **ต้องใช้ `bucket_of_run` ตัวเดียวกับที่ `/clips` ใช้ ห้ามคิดเองซ้ำ**
    # ของเดิมกระโดดไป `publish_order.next_target()` เลย ซึ่งตอบว่า "รอลง Shopee"
    # ให้ทุกใบที่ยังไม่ได้ลงที่ไหน **แม้ใบนั้นจะยังไม่มีคลิปด้วยซ้ำ**
    #
    # วัดจริง 27 ส.ค. 2569: กระดานนับกอง Shopee ได้ 27 ใบ แต่ `/clips` ได้ 25
    # เพราะมี 2 ใบที่ยังอยู่ขั้นสตอรีบอร์ด/คลิป แต่ใบงานในคิวขึ้นสถานะ done
    # เลยหลุดมากองปลายทาง — เลขสองที่ไม่ตรงกันแล้วไม่มีใครรู้ว่าฝั่งไหนถูก
    if run is None:
        return "", ""
    key = bucket_of_run(run)
    if not key:
        return "", ""                       # ลงครบทั้งสามที่แล้ว
    if key == NO_SHOP:
        return key, tiktok_product_missing(run) or "หาสินค้าใน TikTok Shop ไม่เจอ"
    if key not in POST_TARGET:
        # ของยังไม่ครบ — ยังอยู่ขั้นต้นน้ำ ถึงใบงานในคิวจะบอกว่าจบแล้วก็ตาม
        return key, "ใบงานในคิวจบแล้ว แต่ของยังไม่ครบ"
    ok, why = publish_order.check(run, POST_TARGET[key])
    return key, (why if not ok else "พร้อมลงได้เลย")


def bucket_of_run(run: dict) -> str:
    """งานที่เก็บไว้ (run.json ล้วน ไม่มีใบงานในคิว) อยู่กองไหน

    ผู้ใช้สั่ง 26 ส.ค. 2026: *"แยกงานที่เก็บไว้ตามแต่ละขั้นเลย"*

    **ตัดสินจากของที่มีอยู่จริงในงาน ไม่ใช่จากสถานะคิว** เพราะงานพวกนี้ออกจากคิว
    ไปแล้ว (จบ/ถูกเก็บ) สิ่งเดียวที่บอกได้ว่าไปถึงไหนคือ **มีอะไรอยู่ในโฟลเดอร์**
    — มีรูปไหม มีสตอรีบอร์ดไหม มีคลิปไหม ลงไปที่ไหนแล้วบ้าง

    คืนค่าว่าง = ลงครบทั้งสามที่แล้ว ไม่ต้องทำอะไรต่อ จึงไม่เข้ากองไหน
    """
    if not run or run.get("banned"):
        return ""
    # คลิปที่มีไฟล์จริงคือหลักฐานว่าผ่านขั้นต้นน้ำมาแล้ว แม้ metadata เก่าบางใบ
    # จะไม่มี storyboard เหลืออยู่ก็ตาม ต้องส่งต่อไปกองโพสต์ตามสถานะเดิมก่อน
    # ตรวจความครบของรูป/Storyboard ไม่เช่นนั้นงานที่มีคลิปแล้วจะถอยหลังผิดกอง
    if _existing_video_names(run):
        target = publish_order.next_target(run)
        for key, name in POST_TARGET.items():
            if name == target:
                # ถึงคิว TikTok แล้วแต่หาสินค้าใน TikTok Shop ไม่เจอ = เดินต่อไม่ได้
                # ย้ายไปกองของมันเอง จะได้ไม่ไปปนกับใบที่รอลงจริงแล้วทำให้
                # ตัวเลขบนหัวกองบอกว่ามีของรอลงเยอะกว่าความจริง
                if key == TIKTOK and tiktok_product_missing(run):
                    return NO_SHOP
                return key
        return ""
    if not (run.get("images") or []):
        return LINK
    # ต้องครบทั้งสองอย่างถึงจะพ้นกอง Storyboard — ของเดิมใช้ `and` ทำให้ใบที่มี
    # แค่บทพูดแต่ไม่มีสตอรีบอร์ดหลุดไปกอง Clip ทั้งที่ยังเจนไม่ได้
    if not (run.get("storyboard") or []) or not (run.get("script") or []):
        return STORY
    return CLIP


def _existing_video_names(run: dict) -> list[str]:
    """ชื่อคลิปที่มีไฟล์จริง — ไม่เชื่อ metadata เก่าที่ไฟล์ถูกย้าย/ลบแล้ว"""
    from pathlib import Path as _Path                          # noqa: PLC0415

    run = run or {}
    folder = _Path(run.get("folder") or "")
    return [n for n in (run.get("videos") or []) if (folder / n).is_file()]


def clip_info(run: dict) -> dict:
    """ข้อมูลคลิปของใบงานนี้ ให้หน้าเว็บเห็นได้จากรายการ **โดยไม่ต้องเปิดการ์ด**

    **เจ้าของสั่ง 30 ส.ค. 2569** — *"เจนเสร็จเอาคลิปทุกคลิปไปใส่ในใบงานด้วยนะ"*
    ของเดิมแถวบนกระดานมีแค่ชื่อกับขั้น มองไม่ออกเลยว่าใบไหนมีคลิปแล้ว
    ต้องเปิดทีละการ์ดถึงจะรู้ ซึ่งตอนมี 39 ใบคือไล่เปิดทั้งวัน

    `checked` แยก **"ตรวจแล้วผ่าน" ออกจาก "ยังไม่ได้ตรวจ"** ด้วยค่า None
    ตามกติกาข้อ 2.3.1 — ห้ามให้สองอย่างนี้หน้าตาเหมือนกัน ไม่งั้นวันที่ตรวจไม่ได้
    ของเสียจะได้เครื่องหมายถูก (เกิดจริง 30 ส.ค.: เครดิต Gemini หมดตอนตรวจ
    ผลออกมาว่างเปล่า ถ้าไม่แยกจะดูเหมือนคลิปไม่มีเสียง ทั้งที่แค่ตรวจไม่ได้)
    """
    run = run or {}          # บางแถวยังไม่มีข้อมูลงาน (ใบที่เพิ่งเข้าคิว)
    files = _existing_video_names(run)
    check = run.get("video_check") or {}
    ok = check.get("ok") if check else None
    tiktok_link = run.get("tiktok_product_link") or {}
    current_target = publish_order.next_target(run)
    publish_state = ((run.get("publish") or {}).get(current_target) or {})
    active_skip = active_auto_skip_target(run) == current_target
    publish_note = (str(publish_state.get("error") or "").strip()
                    if active_skip else "")
    if files:
        clip_state = "approval"
    elif (run.get("storyboard") and run.get("script") and run.get("flow_prompts")
          and not run.get("banned")):
        clip_state = "generation"
    else:
        clip_state = "incomplete"
    return {
        "video_count": len(files),
        # แยก "รอเจน" ออกจาก "มีคลิปรอตรวจ" ให้หน้าเว็บไม่เรียก 112 ใบรวมกัน
        # ว่าเป็นคลิปพร้อมอนุมัติ ทั้งที่จริงยังไม่มีไฟล์
        "clip_state": clip_state,
        "video_at": run.get("videos_at") or "",
        "video_ok": ok,
        "video_note": (check.get("problems") or [None])[0] if ok is False else "",
        "resolution": check.get("resolution") or "",
        # ผลนำสินค้าเข้าโชว์เคส TikTok ต้องเห็นได้จากแถวโดยไม่ต้องเปิดการ์ด.
        # ``pending_review`` หมายถึงยังไม่ได้เลือกสินค้า ไม่ใช่เลือกอันดับแรกไว้.
        "tiktok_link_status": tiktok_link.get("status") or "",
        "tiktok_link_label": tiktok_link.get("label") or "",
        "tiktok_product_url": tiktok_link.get("url") or run.get("tiktok_product_url") or "",
        "tiktok_showcase_added": bool(tiktok_link.get("showcase_added")),
        "tiktok_product_name": tiktok_link.get("tiktok_product_name") or "",
        "tiktok_link_rank": tiktok_link.get("selected_rank") or 0,
        "tiktok_link_reason": tiktok_link.get("reason") or "",
        # ---- หลักฐานที่ใช้ตัดสินว่า "ไม่มีสินค้าใน TikTok" -------------------
        #
        # เจ้าของสั่ง 13 ก.ย. 2569: *"ให้เอารายละเอียดที่ AI อ่านมาใส่ในใบงาน
        # ที่ไม่มีสินค้า พร้อมรูปภาพที่แคปไว้มาเป็นหลักฐานด้วย"*
        #
        # การตัดสินนี้ทำให้ใบหายจากสายถาวร คนต้องตรวจย้อนได้ว่าตัดสินจากอะไร
        # ไม่ใช่เชื่อคำว่า "ไม่เจอ" ลอยๆ (กติกา 2.6.1) — ตรวจแล้ววันที่แนบ
        # ภาพยังอยู่ครบทั้ง 53 ใบ ไม่มีใบไหนภาพหาย
        #
        # ทุกชื่อไฟล์เป็นพาธในโฟลเดอร์งาน โหลดผ่านที่อยู่เดิมได้เลย
        #   /api/clips/<item_id>/file/<ชื่อไฟล์>
        "tiktok_link_shot": _link_file(tiktok_link.get("results_layout"),
                                       "tiktok-link/tiktok-link-four-results.jpg"),
        "tiktok_link_images": [str(name).replace("\\", "/")
                               for name in (tiktok_link.get("results_images") or [])],
        "tiktok_link_reference": str(tiktok_link.get("reference_image") or ""),
        "tiktok_link_at": tiktok_link.get("updated_at") or "",
        # คะแนนที่ตัวดูรูปให้กับรูปสินค้าที่เลือกมาเป็นตัวเทียบ — บอกว่ารูปที่
        # ใช้เทียบดีพอไหม ถ้ารูปตั้งต้นแย่ ผลที่ได้ก็เชื่อไม่ได้เหมือนกัน
        "tiktok_link_reference_note": str(
            ((tiktok_link.get("reference_check") or {}).get("what") or "")),
        "publish_auto_skip": bool(active_skip),
        "publish_note": publish_note,
    }


def publish_options(run: dict | None) -> list[dict]:
    """แถวนี้ **ลงอะไรได้เดี๋ยวนี้บ้าง** — ให้หน้าเว็บใช้ตัดสินว่าจะโชว์ปุ่ม 📤 ไหม

    สายกลางขอไว้ 27 ส.ค. 2569: *"อย่าให้ผมคิดกติกาลำดับเองฝั่งหน้าเว็บ"*
    — ถูกต้องแล้ว กติกาลำดับต้องมาจาก `publish_order` ที่เดียว (กติกาข้อ 2.8)
    ถ้าหน้าเว็บคิดเอง วันหลังจะกลายเป็น "กระดานบอกว่าลงได้ แต่กดแล้วโดนปฏิเสธ"

    คืนรายการเรียงตามลำดับที่ควรลง แต่ละอันบอกครบว่า

        target   ชื่อปลายทางที่ส่งให้ `/api/publish/flow/run`
        label    ชื่อที่เอาไปโชว์
        ok       กดได้เดี๋ยวนี้ไหม
        why      ถ้ากดไม่ได้ เพราะอะไร (ภาษาคน เอาไปโชว์ได้ตรงๆ)

    **ส่งมาทั้งที่กดไม่ได้ด้วย พร้อมเหตุผล** ไม่ใช่ตัดทิ้ง — ปุ่มที่หายไปเฉยๆ
    แยกไม่ออกจาก "ระบบพัง" ส่วนปุ่มที่จางพร้อมเหตุผลบอกได้ว่าต้องรออะไร
    """
    if not run:
        return []
    out = []
    for key, target in POST_TARGET.items():
        state = ((run.get("publish") or {}).get(target) or {}).get("status")
        if state == "posted":
            continue                        # ลงไปแล้ว ไม่ต้องมีปุ่ม
        ok, why = publish_order.check(run, target)
        label = next((t for k, t, _h in BOARD if k == key), target)
        out.append({"target": target, "label": label, "ok": bool(ok),
                    "why": "" if ok else why})
    return out


# ============================================================================
# โฟลเดอร์แยกตามสถานะ (ผู้ใช้สั่ง 27 ส.ค. 2569)
# ============================================================================
#
# *"ให้แยก folder เลยนะ จะได้แยกจากกันชัดเจน พอทำเสร็จแต่ละขั้นค่อยย้าย folder"*
#
# **ตำแหน่งโฟลเดอร์ไม่ใช่ความจริง เป็นเงาของความจริง** ความจริงอยู่ใน `run.json`
# (ช่อง `publish` กับ `parked`) โฟลเดอร์แค่เดินตาม
#
# ถ้าให้ตำแหน่งโฟลเดอร์เป็นความจริงอีกชุด วันหนึ่งย้ายพลาดหรือย้ายไม่ทัน
# สองอย่างจะขัดกันแล้วไม่มีใครรู้ว่าอันไหนถูก — บทเรียนเดียวกับตอนกระดาน
# กับ `/clips` นับไม่ตรงกัน ตอนนั้นแก้ด้วยการให้ทั้งคู่อ่านจากที่เดียว
#
# ขั้นต้นน้ำทั้งสาม (ดึงลิงก์ · สตอรีบอร์ด · รออนุมัติคลิป) อยู่โฟลเดอร์เดิม
# เพราะยังไม่มีคลิปพร้อมลง — แยกไปอีกสามโฟลเดอร์จะเสียงน้อยกว่าที่ได้
FOLDER_OF_BUCKET = {
    SHOPEE: "clips",
    REELS: "clipsfb",
    TIKTOK: "clipstiktok",
    # กองนี้เป็นเรื่องการ **จัดหน้ากระดาน** ล้วนๆ ใช้โฟลเดอร์เดียวกับ TikTok
    # เพื่อไม่ให้ต้องย้ายไฟล์จริงเพียงเพราะเปลี่ยนวิธีแสดงผล
    NO_SHOP: "clipstiktok",
}

# ใบที่พักไว้ — ต้นน้ำทั้งสามขั้นรวมเป็น waitstory ตามที่ผู้ใช้ตั้งชื่อมา
PARKED_FOLDER_OF_BUCKET = {
    LINK: "waitstory", STORY: "waitstory", CLIP: "waitstory",
    SHOPEE: "waitclips",
    REELS: "waitclipsfb",
    TIKTOK: "waitclipstiktok",
    NO_SHOP: "waitclipstiktok",
}

# โฟลเดอร์ของงานที่ยังทำอยู่ (ยังไม่มีคลิปพร้อมลง) และงานที่ลงครบสามที่แล้ว
WORKING_FOLDER = "shopee_products"
FINISHED_FOLDER = "shopee_products_done"


def folder_of_run(run: dict, stage: str = "") -> str:
    """งานชิ้นนี้ **ควรอยู่โฟลเดอร์ไหน** ตามสถานะปัจจุบัน

    ไม่ดูว่าตอนนี้ไฟล์อยู่ที่ไหน — ตัวเรียก (`clip_store.refile`) ย้ายให้ตรงเอง

    `stage` = ขั้นของ **ใบงานที่ยังเปิดอยู่ในคิว** ของสินค้าชิ้นนี้ (ถ้ามี)
    **ต้องส่งมาด้วย ไม่งั้นโฟลเดอร์กับกระดานจะไม่ตรงกัน** — งานที่เจนคลิปเสร็จ
    แต่ยังรอคนอนุมัติ ไฟล์บอกว่า "มีคลิปแล้ว" (น่าจะอยู่ `clips/`) ส่วนคิวบอกว่า
    "ยังรออนุมัติ" (กระดานจัดไว้กอง 🎬 คลิป) วัดจริง 27 ส.ค. 2569 มี 6 ใบแบบนี้
    ทำให้โฟลเดอร์ 37 แต่กระดานนับ 31 — คิวชนะเสมอเพราะยังมีคนต้องตัดสินใจอยู่
    """
    if not run:
        return WORKING_FOLDER
    if stage in LINK_STAGES | STORY_STAGES | CLIP_STAGES:
        return WORKING_FOLDER           # ยังทำอยู่ในคิว ยังไม่พร้อมลงที่ไหน
    if run.get("parked"):
        came = (run.get("parked") or {}).get("from") or ""
        if came in PARKED_FOLDER_OF_BUCKET:
            return PARKED_FOLDER_OF_BUCKET[came]
        # จดมาเป็นขั้นในคิว ไม่ใช่ชื่อกอง — แปลก่อน
        key, _why = bucket_of({"stage": came}, None)
        return PARKED_FOLDER_OF_BUCKET.get(key or CLIP, "waitstory")
    key = bucket_of_run(run)
    if not key:
        return FINISHED_FOLDER          # ลงครบทั้งสามที่แล้ว
    return FOLDER_OF_BUCKET.get(key, WORKING_FOLDER)


def build(jobs: list[dict], load_run, runs: list[dict] | None = None) -> dict:
    """จัดงานทั้งหมดลง 6 กอง — `load_run(item_id)` คืน run.json ของงานนั้น

    `runs` = ไฟล์งานทั้งหมด (`clip_store.list_runs`) ใส่มาด้วยเพื่อให้กองปลายทาง
    นับงานที่ **จบจากคิวไปแล้ว** ด้วย ไม่งั้นกระดานจะบอกน้อยกว่าความจริง
    ไม่ใส่มาก็ยังทำงานได้เหมือนเดิม (ของเก่าที่เรียกอยู่จึงไม่พัง)

    **โหลด run.json เฉพาะงานที่จำเป็น** งานที่ยังไม่ถึงขั้นโพสต์ตัดสินจากสถานะ
    ในคิวได้เลย ไม่ต้องอ่านไฟล์ — คิวมีเป็นร้อยใบ ถ้าอ่านหมดทุกครั้งที่เปิดหน้า
    จะช้าโดยไม่จำเป็น
    """
    piles: dict[str, list[dict]] = {key: [] for key, _, _ in BOARD}
    # ใบที่พักไว้รอแก้ — **คนละถังกับงานที่เดินได้ แต่อยู่ใต้กองเดียวกัน**
    #
    # แยกถังเพราะตัวเลขในวงเล็บบนหัวกองต้องหมายถึง "งานที่เดินได้จริง" เท่านั้น
    # ถ้านับรวมของที่พักไว้ ตัวเลขจะบอกว่ามีของเยอะทั้งที่แตะไม่ได้สักใบ
    parked_piles: dict[str, list[dict]] = {key: [] for key, _, _ in BOARD}
    # มีรายการ run อยู่ในหน่วยความจำจากผู้เรียกแล้ว ใช้ตรวจเฉพาะใบที่ถูกข้าม
    # โดยไม่ต้องเปิด run.json เพิ่มเป็นร้อยไฟล์เพราะงานขั้นต้นน้ำ
    run_by_item = {str(r.get("item_id") or ""): r for r in (runs or [])}
    for job in jobs or []:
        stage = job.get("stage") or ""
        candidate = run_by_item.get(str(job.get("item_id") or ""))
        if candidate and candidate.get("banned"):
            continue
        run = candidate if active_auto_skip_target(candidate) else None
        # **ใบที่พักไว้ไม่ต้องอ่าน run.json** ขั้นที่มันค้างบอกกองได้อยู่แล้ว
        #
        # ต้องดักก่อนด่านข้างล่าง เพราะใบที่ "ล้มแล้วพักไว้รอแก้" จะโดนกรองทิ้ง
        # ตรงบรรทัด failed/cancelled — ซึ่งเป็นเคสที่ผู้ใช้อยากเห็นที่สุด
        # งานเดียวกันอาจยังมีแถวประวัติใน clip_queue แต่ถูกพักภายหลังที่ run.json
        # (เช่นใบแอร์ 9154852607). ถ้าดูเฉพาะ job จะเอาใบพักไปนับในกองพร้อมลง
        # ทั้งที่ตัว Auto ตรวจ run แล้วข้าม จึงเกิดกอง 68 แต่พร้อมจริง 67.
        park = (job.get("parked") or
                ((candidate or {}).get("parked") if candidate else None) or {})
        if park:
            came = park.get("from") or stage
            if came in piles:
                key = came
            else:
                parked_job = {**job, "parked": park}
                key, _why = bucket_of(parked_job, None)
            if not key:
                # ค้างที่ขั้นที่แมปกองไม่ได้ (เช่นล้มตอนโพสต์ หรือล้มก่อนได้รูป)
                # ลงกองคลิปไว้ก่อน ดีกว่าหายเงียบจากทุกกองแล้วไม่มีใครเห็น
                key = CLIP
            group = fix_group_of(came)
            title, hint = fix_group_meta(group)
            parked_piles[key].append({
                "id": job.get("id"),
                "item_id": job.get("item_id") or "",
                "name": (job.get("name") or (candidate or {}).get("name")
                         or job.get("link") or "(ยังไม่รู้ชื่อสินค้า)"),
                "stage": stage,
                "stage_label": clip_queue.STAGE_LABEL.get(stage, stage),
                # ขั้นที่ค้างตอนถูกพัก — ต่างจาก `stage` เมื่อใบนั้นล้มก่อนถูกพัก
                "from_stage": came,
                "from_label": clip_queue.STAGE_LABEL.get(came, came),
                # ชนิดของการแก้ + **วิธีแก้** — หน้าเว็บเอาไปจัดกลุ่มย่อยได้ถ้าต้องการ
                "fix_group": group,
                "fix_title": title,
                "fix_hint": hint,
                "why": str(park.get("why") or "").strip(),
                "parked": park,
                "created_at": job.get("created_at") or "",
                "updated_at": job.get("updated_at") or "",
                # ใบที่พักไว้ไม่มีปุ่มลง — ต้องเอากลับก่อนถึงจะลงได้
                "can_publish": [],
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
            # **งานที่ติ๊กว่าทำแล้วต้องไม่โผล่บนกระดาน** — ของถูกย้ายไปโฟลเดอร์
            # เก็บ (`shopee_products_done/`) แล้ว แต่ `load_run` ยังหาเจอ
            # (ตั้งใจ เพราะเปิดดูย้อนหลังได้) ผลคือใบที่เก็บไปแล้วกลับมานับซ้ำ
            # วัดจริง 27 ส.ค. 2569: กองรอลง Shopee มี 2 ใบที่ /clips ไม่มี
            if "shopee_products_done" in str(run.get("folder") or "").replace("\\", "/"):
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
            # ลงอะไรได้บ้างเดี๋ยวนี้ — หน้าเว็บห้ามคิดกติกาลำดับเอง
            "can_publish": publish_options(run),
            "updated_at": job.get("updated_at") or "",
            **clip_info(run),
        })

    # ---- เติมงานที่ **จบจากคิวไปแล้ว** เข้ากองปลายทาง -----------------------
    #
    # **ทำไมต้องมี** (ผู้ใช้ยืนยัน 27 ส.ค. 2569) กระดานเดิมนับจากคิวอย่างเดียว
    # พองานเจนคลิปเสร็จก็ออกจากคิวไป กระดานจึงมองไม่เห็นมันอีกเลย ทั้งที่คลิป
    # พร้อมลงอยู่ — วัดจริง **รายการ `/clips` บอก 25 ใบ แต่กระดานบอก 8 ใบ**
    # หายไป 17 ใบ ซึ่งเป็นของที่ควรเห็นที่สุดเพราะรอแค่กดลง
    #
    # **กันนับซ้ำด้วยรหัสสินค้า** งานที่ยังอยู่ในคิวถูกนับไปแล้วข้างบน
    if runs:
        already = {str(r.get("item_id")) for rows in piles.values() for r in rows}
        already |= {str(r.get("item_id")) for rows in parked_piles.values() for r in rows}
        for run in runs:
            item_id = str(run.get("item_id") or "")
            if not item_id or item_id in already:
                continue
            key = bucket_of_run(run)
            if key not in (SHOPEE, REELS, TIKTOK, NO_SHOP):
                continue          # ขั้นต้นน้ำยังอยู่ในคิว ไม่ต้องเติมจากไฟล์
            # ป้องกันสำเนาโฟลเดอร์ `-ซ้ำ-` ของ item เดียวกันเพิ่มสองแถวบน
            # กระดาน ขณะที่ตัว Auto รวมเป็นหนึ่งคิวอยู่แล้ว. ต้องจดทันทีในลูป;
            # เซตเดิมมีเฉพาะใบจาก clip_queue จึงกันสำเนาระหว่าง runs ไม่ได้.
            already.add(item_id)
            row = {
                "id": "",                     # ไม่มีใบงานในคิวแล้ว
                "item_id": item_id,
                "name": run.get("name") or "(ยังไม่รู้ชื่อสินค้า)",
                "stage": "",
                "stage_label": "",
                "why": "",
                "created_at": run.get("product_at") or "",
                "can_publish": publish_options(run),
                **clip_info(run),
                "updated_at": run.get("video_at") or run.get("storyboard_at") or "",
            }
            park = run.get("parked") or {}
            if park:
                came = park.get("from") or key
                group = fix_group_of(came)
                title, hint = fix_group_meta(group)
                row.update({
                    "from_stage": came, "from_label": clip_queue.STAGE_LABEL.get(came, came),
                    "fix_group": group, "fix_title": title, "fix_hint": hint,
                    "why": str(park.get("why") or "").strip(), "parked": park,
                    # ใบที่พักไว้ไม่มีปุ่มลง — ต้องเอากลับก่อนถึงจะลงได้
                    # (ตรงกับใบที่พักจากในคิว ต้องเหมือนกันทั้งสองทาง)
                    "can_publish": [],
                })
                parked_piles[key].append(row)
            else:
                piles[key].append(row)

    counts = {key: len(rows) for key, rows in piles.items()}
    clip_waiting_generation = sum(
        1 for row in piles[CLIP] if row.get("clip_state") == "generation")
    clip_waiting_approval = sum(
        1 for row in piles[CLIP] if row.get("clip_state") == "approval")
    return {
        "buckets": [
            {"key": key, "title": title, "hint": hint,
             "count": counts[key],
             "waiting_generation": clip_waiting_generation if key == CLIP else 0,
             "waiting_approval": clip_waiting_approval if key == CLIP else 0,
             # กองรอแก้ไม่มีเส้นวัด — ยิ่งน้อยยิ่งดี ไม่ใช่ของที่ต้องมีสำรอง
             "target": 0 if key in NO_TARGET else STOCK_TARGET,
             # ขาดอีกกี่ใบถึงจะถึงเส้นวัด — 0 = ถึงแล้วหรือเกินแล้ว
             "short": 0 if key in NO_TARGET else max(0, STOCK_TARGET - counts[key]),
             # **บอกวิธีเติมด้วย ไม่ใช่บอกแค่ว่าขาด**
             "refill": "" if key in NO_TARGET else refill_hint(key, counts),
             # **ของรอแก้ของขั้นนี้ แยกถังจากงานที่เดินได้**
             # (ผู้ใช้สั่ง 27 ส.ค. 2026: "ใส่ในแต่ละใต้ stage แยกกันเลย")
             # ทุกกองมีฟิลด์นี้เสมอ ว่างก็เป็นลิสต์เปล่า — หน้าเว็บไม่ต้องเช็คว่ามีไหม
             "parked": parked_piles[key],
             "parked_count": len(parked_piles[key]),
             # **ไม่มีฟิลด์ `groups` แล้ว** (ถอดออก 27 ส.ค. 2569)
             #
             # เคยใส่ไว้ชั่วคราวตอนที่หน้าเว็บยังวาดจากฟิลด์นั้น (commit `9bbcca3`)
             # ตอนนี้หน้าเว็บอ่าน `fix_group` / `fix_title` / `fix_hint` ที่ติดมากับ
             # แต่ละใบใน `parked` โดยตรงแล้ว (commit `ddfe0c7` ของเลน main)
             # เก็บทั้งสองแบบไว้ = ข้อมูลชุดเดียวส่งสองรูป วันหลังแก้ข้างเดียว
             # แล้วเพี้ยนกันเงียบๆ — ตัดทิ้งดีกว่า
             #
             # ฝั่งแชทจัดกลุ่มเองด้วย `parked_by_bucket()` + `fix_group_of()`
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
    if key == NO_SHOP:
        return ("กองนี้ไม่ต้องเติม — เป็นใบที่ TikTok Shop ไม่มีของขาย "
                "รอจนร้านมีของแล้วค่อยกดหาใหม่")
    return ""
