"""ลำดับและจังหวะการลงคลิป — คลิปเดียวลงได้ทีละที่ ห่างกันอย่างน้อยข้ามวัน

**กติกาที่ผู้ใช้สั่ง 25 ส.ค. 2026**

    1. Shopee Video   →   2. Facebook Reels   →   3. TikTok

    คลิปเดียวกันต้องลงห่างกัน **อย่างน้อย 1 วัน** และ **นับเป็นวันในปฏิทิน
    ไม่ใช่ 24 ชั่วโมงเป๊ะ** — ลงวันที่ 21 กี่โมงก็ได้ วันที่ 22 ลงที่ถัดไปได้เลย
    ไม่ต้องรอให้ครบ 24 ชั่วโมง (ผู้ใช้ระบุเอง: "นับแค่วัน เช่น 21 22
    ไม่ต้องนับเวลา 24 ชม เป้ะๆ")

**ทำไมต้องแยกเป็นไฟล์ของตัวเอง** — ตอนนี้มีตัวโพสต์ **สองระบบที่ไม่รู้จักกัน**

    publish_flow.py   กดบนจอมือถือจริง   → Shopee Video · Facebook Reels
    tiktok_post.py    เปิดหน้าเว็บบนคอม   → TikTok

    ถ้าเอากติกาไปฝังในตัวใดตัวหนึ่ง อีกตัวจะไม่รู้แล้วลงข้ามลำดับได้ทันที
    ไฟล์นี้จึงเป็นที่เดียวที่ตอบว่า "ตอนนี้คลิปนี้ลงที่ไหนได้" และทั้งสองระบบ
    ต้องถามที่นี่ก่อนลงเสมอ

**ทำไมนับวันปฏิทิน ไม่นับชั่วโมง** — คนทำงานคิดเป็นวัน ไม่ได้จับเวลา ถ้าใช้
24 ชั่วโมงเป๊ะ คลิปที่ลงตอน 22:00 จะลงต่อไม่ได้จนถึง 22:00 ของอีกวัน
ทั้งที่ในความรู้สึกคนมันคือ "คนละวันแล้ว" ตั้งแต่เที่ยงคืน

    python publish_order.py <item_id>     คลิปนี้ลงอะไรไปแล้ว ลงอะไรต่อได้
"""

from __future__ import annotations

import sys
from datetime import date, datetime, timedelta
from pathlib import Path

# ลำดับที่ต้องลง — **ห้ามสลับ ห้ามข้าม** (ผู้ใช้กำหนดเอง 25 ส.ค. 2026)
ORDER = ("shopee_video", "facebook_reels", "tiktok")

NAMES = {
    "shopee_video": "Shopee Video",
    "facebook_reels": "Facebook Reels",
    "tiktok": "TikTok",
}

# กี่วันในปฏิทินที่ต้องเว้นระหว่างสองปลายทางของคลิปเดียวกัน
GAP_DAYS = 1

# ---- โควตาต่อวัน (เจ้าของสั่ง 28 ส.ค. 2569) ------------------------------
#
# *"shopee video 70/วัน · facebook reels 70/วัน · tiktok 70/วัน
#   ถ้าเกินโควต้าแล้วมีงานเข้ามา ให้ต่อคิวแล้วไปรันในวันถัดไป"*
#
# **ทำไมต้องอยู่ในไฟล์นี้** ด้วยเหตุผลเดียวกับกติกาลำดับ — ตัวโพสต์มีสองระบบ
# ที่ไม่รู้จักกัน (`publish_flow.py` กดจอมือถือ · `tiktok_post.py` เปิดเว็บบนคอม)
# ถ้าฝังโควตาไว้ในตัวใดตัวหนึ่ง อีกตัวจะโพสต์ทะลุเพดานทันทีโดยไม่มีใครรู้
#
# **นับต่อบัญชี ไม่ใช่ต่อเครื่อง** (เจ้าของเลือกเอง) เพราะเพดานเป็นของบัญชี
# บนแพลตฟอร์ม ไม่ใช่ของเครื่อง — วันหน้าถ้าเอาสองเครื่องมาใช้บัญชีเดียวกัน
# การนับต่อเครื่องจะปล่อยให้ลงได้ 140 ใบต่อบัญชี ซึ่งพังทั้งจุดประสงค์
DAY_LIMIT = 70

# วันใหม่เริ่มตี 4 (เจ้าของเลือกเอง 28 ส.ค. 2569)
#
# ไม่ใช่เที่ยงคืน เพราะรอบไล่โพสต์กลางคืนมักคาบเกี่ยวข้ามเที่ยงคืน
# (คืน 27→28 ส.ค. รันตั้งแต่ 00:08 ถึง 02:31) ถ้าตัดที่เที่ยงคืน
# งานรอบเดียวกันจะถูกนับแยกเป็นสองวันโดยไม่มีเหตุผล
DAY_START_HOUR = 4


class OrderError(RuntimeError):
    """ลงตอนนี้ไม่ได้ตามกติกาลำดับ — ไม่ใช่ความผิดพลาดของระบบ"""


def _as_date(stamp) -> date | None:
    """แปลงเวลาที่บันทึกไว้เป็น **วันที่** อย่างเดียว ทิ้งเวลาทิ้งไป

    รับได้ทั้ง `2026-08-21T14:03:00` และ `2026-08-21` เพราะของเก่าในไฟล์งาน
    เคยเก็บมาแล้วทั้งสองแบบ อ่านไม่ออก = คืน None แล้วให้ผู้เรียกตัดสิน
    ห้ามเดาเป็นวันนี้ เพราะจะกลายเป็นปล่อยให้ลงซ้อนวันได้
    """
    if isinstance(stamp, datetime):
        return stamp.date()
    if isinstance(stamp, date):
        return stamp
    text = str(stamp or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "")).date()
    except ValueError:
        pass
    try:
        return datetime.strptime(text[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def posting_day(stamp=None) -> date | None:
    """วันของรอบโพสต์ — วันใหม่เริ่มตี 4 ไม่ใช่เที่ยงคืน

    โพสต์ตอน 02:00 ของวันที่ 28 ยังนับเป็นวันที่ 27 เพราะเป็นรอบเดียวกับ
    ที่เริ่มตั้งแต่คืนวันที่ 27 — ตัดที่เที่ยงคืนจะผ่ารอบเดียวออกเป็นสองวัน
    """
    if stamp is None:
        moment = datetime.now()
    elif isinstance(stamp, datetime):
        moment = stamp
    else:
        text = str(stamp or "").strip()
        if not text:
            return None
        try:
            moment = datetime.fromisoformat(text.replace("Z", ""))
        except ValueError:
            got = _as_date(text)
            return got                     # มีแค่วันที่ ไม่มีเวลา ใช้ตามนั้น
    shifted = moment - timedelta(hours=DAY_START_HOUR)
    return shifted.date()


def day_used(runs, target: str, account: str = "", today: date | None = None) -> int:
    """นับว่าวันนี้ลงปลายทางนี้ไปกี่คลิปแล้ว สำหรับบัญชีนั้น

    **นับจากบันทึกการลงจริง ไม่ใช่ตัวนับแยก** (ตั้งใจ) — เพราะตัวนับแยกจะเพี้ยน
    จากความจริงได้ ซึ่งเจอมาแล้วทั้งวัน 28 ส.ค. 2569 (ระบบจดว่าลงแล้วทั้งที่ไม่ได้ลง)
    นับจากที่เดียวกับที่ `clip_store.mark_posted` เขียน จึงได้ของแถมสองอย่าง
      · **งานที่เจ้าของกดจดเองในแชทถูกนับด้วย** (เจ้าของสั่งไว้)
      · แก้บันทึกที่ผิดแล้ว ยอดนับแก้ตามเองทันที
    บัญชีว่าง = นับทุกบัญชีรวมกัน (ใช้ตอนยังไม่ได้ผูกบัญชีกับเครื่อง)
    """
    if today is None:
        today = posting_day()
    used = 0
    for run in runs or []:
        info = ((run.get("publish") or {}).get(target) or {})
        if info.get("status") != "posted":
            continue
        if posting_day(info.get("posted_at")) != today:
            continue
        if account and str(info.get("account") or "") not in ("", account):
            continue
        used += 1
    return used


def quota_check(runs, target: str, account: str = "",
                today: date | None = None) -> tuple[bool, str]:
    """ยังลงปลายทางนี้ได้อีกไหมวันนี้ — คืน (ลงได้ไหม, เหตุผลภาษาคน)

    เต็มแล้ว **ไม่ทิ้งงาน** ผู้เรียกต้องคาไว้ในคิวแล้วลองใหม่ ตัวรันตื่นเองทุก
    30 วินาทีอยู่แล้ว พอพ้นตี 4 ยอดนับกลับเป็น 0 งานที่ค้างจึงเดินต่อเอง
    """
    used = day_used(runs, target, account, today)
    left = DAY_LIMIT - used
    who = f"บัญชี {account}" if account else "ทุกบัญชีรวมกัน"
    if left > 0:
        return True, f"{NAMES.get(target, target)} วันนี้ลงไป {used}/{DAY_LIMIT} · เหลืออีก {left} ({who})"
    return False, (
        f"⏳ {NAMES.get(target, target)} เต็มโควตาวันนี้แล้ว "
        f"({used}/{DAY_LIMIT} · {who}) — งานไม่ได้หายไปไหน "
        f"ค้างอยู่ในคิวและจะเริ่มเองหลังตี 4"
    )


def posted_rows(run: dict) -> list[tuple[str, date | None]]:
    """ปลายทางที่ลงสำเร็จแล้ว คู่กับวันที่ลง เรียงตามลำดับที่กำหนด"""
    publish = (run or {}).get("publish") or {}
    rows = []
    for target in ORDER:
        info = publish.get(target) or {}
        if info.get("status") == "posted":
            rows.append((target, _as_date(info.get("posted_at"))))
    return rows


def last_posted(run: dict) -> tuple[str, date | None] | None:
    """ปลายทางล่าสุดที่ลงไปแล้ว — ตัวที่กำหนดว่าต้องรอถึงวันไหน

    เอา **วันที่ล่าสุด** ไม่ใช่ตัวท้ายสุดตามลำดับ เพราะถ้ามีของเก่าที่ลงข้ามลำดับ
    มาก่อนกติกานี้ ตัวท้ายตามลำดับอาจลงก่อนตัวอื่นก็ได้
    """
    rows = [r for r in posted_rows(run) if r[1] is not None]
    if not rows:
        return None
    return max(rows, key=lambda r: r[1])


def next_target(run: dict) -> str | None:
    """ปลายทางถัดไปที่ควรลง — None = ลงครบทุกที่แล้ว"""
    publish = (run or {}).get("publish") or {}
    for target in ORDER:
        if (publish.get(target) or {}).get("status") != "posted":
            return target
    return None


def check(run: dict, target: str, today: date | None = None) -> tuple[bool, str]:
    """ลงปลายทางนี้ตอนนี้ได้ไหม — คืน (ได้ไหม, เหตุผลเป็นภาษาคน)

    **ห้ามให้ผู้เรียกเดาเอง** ทุกกรณีที่ตอบว่าไม่ได้ ต้องบอกด้วยว่าเพราะอะไร
    และต้องรอถึงเมื่อไร ไม่งั้นผู้ใช้จะเห็นแค่ "ลงไม่ได้" แล้วไม่รู้จะทำยังไงต่อ
    """
    today = today or date.today()
    if target not in ORDER:
        return False, f"ไม่รู้จักปลายทาง {target}"

    # ---- คลิปที่แพลตฟอร์มลบไปแล้ว ห้ามลงซ้ำเด็ดขาด (26 ส.ค. 2026) ----------
    #
    # เกิดจริง: คลิปทีวี 85 นิ้ว (24842141705) โดน Shopee ลบเพราะ
    # "Intellectual Property Rights Violation" — บนจอทีวีในคลิปมีภาพถ่ายทอดสด
    # อเมริกันฟุตบอล และหน้า Google TV ที่โชว์โลโก้ Netflix/Disney+/HBO
    #
    # **ลงซ้ำไม่ใช่แค่โดนลบซ้ำ แต่คะแนนความประพฤติสะสม** ครบ 15 คะแนนเมื่อไร
    # ถูกระงับการโพสต์บน Shopee Video **ถาวร** และการรีเซตคะแนนรายไตรมาส
    # ไม่ช่วยคนที่โดนแบนถาวรแล้ว (ดู SHOPEE-VIDEO-RULES.md)
    #
    # ด่านอยู่ที่นี่เพราะเป็นทางผ่านเดียวที่ทั้งตัวโพสต์บนมือถือและตัวโพสต์ TikTok
    # ต้องเรียกก่อนลงเสมอ — ใส่ไว้ที่อื่นอีกตัวจะรอด
    banned = (run or {}).get("banned") or {}
    if banned:
        why = banned.get("reason") or "ผิดนโยบายของแพลตฟอร์ม"
        where = banned.get("by") or "แพลตฟอร์ม"
        return False, (f"คลิปนี้เคยถูก {where} ลบไปแล้วเพราะ “{why}” "
                       "— ลงซ้ำจะโดนลบอีกและสะสมคะแนนจนโดนแบนถาวร "
                       "ต้องเจนคลิปใหม่ที่แก้ต้นเหตุก่อน")

    # ไม่มีไฟล์คลิปก็ลงไม่ได้ — ต้องดักที่นี่ ไม่ใช่ปล่อยให้ไปรู้ตอนแตะจอ
    #
    # **อันตรายกว่าที่คิด** ขั้น "เลือกคลิปที่จะโพสต์" แตะพิกัดที่เทรนไว้เฉยๆ
    # มันไม่ได้อ่านว่าช่องนั้นเป็นคลิปอะไร ถ้าไม่มีคลิปของงานอยู่ในเครื่อง
    # มันจะหยิบ**คลิปเก่าของสินค้าอื่น**มาโพสต์แล้วเดินจนจบโดยไม่มีอะไรฟ้อง
    if not (run or {}).get("videos"):
        return False, ("งานนี้ยังไม่มีไฟล์คลิป — เจนคลิปให้เสร็จก่อนถึงจะลงได้ "
                       "(ถ้าคลิปเคยมีแล้วหายไป ให้เช็คว่าถูกย้ายไป data/banned/ หรือเปล่า)")

    publish = (run or {}).get("publish") or {}
    if (publish.get(target) or {}).get("status") == "posted":
        return False, f"{NAMES[target]} ลงไปแล้ว ไม่ต้องลงซ้ำ"

    # ต้องลงตามลำดับ — ที่อยู่ก่อนหน้ายังไม่ลง ห้ามข้าม
    for earlier in ORDER[:ORDER.index(target)]:
        if (publish.get(earlier) or {}).get("status") != "posted":
            return False, (f"ต้องลง {NAMES[earlier]} ก่อน "
                           f"แล้วค่อยลง {NAMES[target]}")

    recent = last_posted(run)
    if recent is None:
        rows = posted_rows(run)
        if rows:            # ลงไปแล้วแต่ไม่มีวันที่ = ของเก่าก่อนมีกติกานี้
            return True, (f"ลง {NAMES[target]} ได้ "
                          f"(ของเดิมไม่ได้บันทึกวันที่ไว้ จึงไม่นับระยะห่าง)")
        return True, f"ยังไม่เคยลงที่ไหน — เริ่มที่ {NAMES[target]} ได้เลย"

    name, when = recent
    waited = (today - when).days
    if waited < GAP_DAYS:
        allowed = when.toordinal() + GAP_DAYS
        allowed_date = date.fromordinal(allowed)
        return False, (
            f"เพิ่งลง {NAMES[name]} ไปวันที่ {when:%d/%m} "
            f"— คลิปเดียวกันต้องเว้นอย่างน้อย {GAP_DAYS} วัน "
            f"ลง {NAMES[target]} ได้ตั้งแต่วันที่ {allowed_date:%d/%m} เป็นต้นไป"
        )
    return True, (f"ลง {NAMES[target]} ได้ — ลง {NAMES[name]} ไปเมื่อวันที่ "
                  f"{when:%d/%m} ห่างมาแล้ว {waited} วัน")


def require(run: dict, target: str, today: date | None = None) -> None:
    """เหมือน `check` แต่โยน `OrderError` ถ้าลงไม่ได้ — ใช้ที่ต้นทางการโพสต์"""
    ok, why = check(run, target, today)
    if not ok:
        raise OrderError(why)


def rows(run: dict, today: date | None = None) -> list[dict]:
    """สถานะทั้งสามปลายทางในรูปที่เอาไปวาดปุ่มได้เลย — **คิดที่นี่ที่เดียว**

    หน้าเว็บห้ามคำนวณเองว่า "กดลงได้ไหม / ต้องรอถึงเมื่อไร" ไม่งั้นกติกาจะมีสองชุด
    แล้วเพี้ยนกันเงียบๆ ตอนแก้ข้างเดียว — `summary()` ข้างล่างก็ประกอบจากตัวนี้

    ทุกแถวมี `can_post` (กดได้ไหม) คู่กับ `why` (เพราะอะไร) เสมอ **ห้ามส่งอันเดียว**
    ปุ่มที่กดไม่ได้โดยไม่บอกเหตุผล ผู้ใช้แยกไม่ออกจากระบบพัง
    """
    today = today or date.today()
    publish = (run or {}).get("publish") or {}
    out: list[dict] = []
    for index, target in enumerate(ORDER, start=1):
        info = publish.get(target) or {}
        status = info.get("status") or "pending"
        when = _as_date(info.get("posted_at"))
        ok, why = check(run, target, today)
        if status == "posted":
            mark = f"✅ ลงแล้ว{f' {when:%d/%m}' if when else ''}"
        elif status == "failed":
            mark = f"❌ ล้มเหลว — {info.get('error') or 'ไม่ทราบสาเหตุ'}"
        else:
            mark = ("⏭ ลงได้เลย" if ok else f"⏳ {why}")
        out.append({
            "step": index,
            "target": target,
            "name": NAMES[target],
            "status": status,
            "posted_at": info.get("posted_at") or "",
            "url": info.get("url") or "",
            "error": info.get("error") or "",
            "can_post": ok,
            "why": why,
            "mark": mark,
        })
    return out


def summary(run: dict, today: date | None = None) -> str:
    """สรุปสถานะคลิปนี้ให้คนอ่าน — ใช้ในแชทและหน้าเว็บ"""
    return "\n".join(
        f"{row['step']}. {row['name']} — {row['mark']}"
        for row in rows(run, today)
    )


# ------------------------------------------------------------------ คำสั่ง

def ready_now(runs, target: str) -> list[dict]:
    """คลิปที่ลงปลายทางนี้ได้ **เดี๋ยวนี้** — ผ่านครบทั้งลำดับ · ระยะวัน · โควตา

    **ต้องตอบด้วยเกณฑ์เดียวกับด่านที่กั้นจริงตอนโพสต์** ไม่ใช่คิดเกณฑ์ใหม่
    ไม่งั้นรายชื่อบนจอกับสิ่งที่กดได้จริงจะไม่ตรงกัน แล้วคนจะเชื่อรายชื่อ
    แล้วไปงงว่าทำไมกดแล้วไม่ได้ (กติกาข้อ 2.3 — ตัวที่บอกว่าผ่านทั้งที่ไม่ผ่าน)
    จึงเรียก `check()` ตัวเดียวกับที่ `app.py` ใช้ ไม่ได้เขียนเงื่อนไขซ้ำ

    เรียง**ตัวที่รอนานสุดขึ้นก่อน** เพราะคลิปที่ลง Shopee ไปตั้งแต่วันก่อนๆ
    ควรได้ลงก่อนตัวที่เพิ่งลงเมื่อวาน
    """
    out = []
    for run in runs or []:
        info = ((run.get("publish") or {}).get(target) or {})
        if info.get("status") == "posted":
            continue
        ok, _ = check(run, target)
        if not ok:
            continue
        last = last_posted(run)
        out.append({
            "item_id": str(run.get("item_id") or ""),
            "name": run.get("name") or "",
            "videos": len(run.get("videos") or []),
            "since": last[1].isoformat() if last and last[1] else "",
            "after": NAMES.get(last[0], last[0]) if last else "",
        })
    out.sort(key=lambda r: r["since"] or "9999")
    return out


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print("ใช้: python publish_order.py <item_id>       ← ดูใบเดียว")
        print("     python publish_order.py ready [ปลายทาง]  ← ดูรวมว่าใบไหนลงได้แล้ว")
        print("ลำดับที่กำหนดไว้: " + " → ".join(NAMES[t] for t in ORDER))
        print(f"เว้นระยะอย่างน้อย {GAP_DAYS} วัน (นับวันในปฏิทิน)")
        return 0

    if argv[0] in ("ready", "พร้อม"):
        import clip_store
        root = Path(__file__).resolve().parent / "data"
        runs = clip_store.list_runs(root) + clip_store.list_done(root)
        targets = [argv[1]] if len(argv) > 1 and argv[1] in NAMES else list(ORDER)
        for target in targets:
            rows = ready_now(runs, target)
            used = day_used(runs, target)
            left = max(0, DAY_LIMIT - used)
            print(f"\n=== {NAMES[target]} — ลงได้เลยตอนนี้ {len(rows)} คลิป "
                  f"(โควตาวันนี้เหลือ {left}/{DAY_LIMIT}) ===")
            if not rows:
                print("   ไม่มีคลิปที่พร้อม — ดูเหตุผลรายใบด้วย "
                      "python publish_order.py <item_id>")
                continue
            for i, r in enumerate(rows, 1):
                since = f"ลง{r['after']}ไปเมื่อ {r['since'][5:]}" if r["since"] else "ยังไม่เคยลงที่ไหน"
                print(f"  {i:>2}. {r['item_id']:13} คลิป {r['videos']} ไฟล์ · {since}")
                print(f"      {r['name'][:70]}")
            if len(rows) > left:
                print(f"   ⚠️ วันนี้ลงได้อีกแค่ {left} คลิป ที่เหลือจะค้างไว้ทำวันพรุ่งนี้")
        return 0

    import clip_store
    root = Path(__file__).resolve().parent / "data"
    run = clip_store.load_run(root, argv[0])
    if not run:
        print(f"ไม่พบงานของสินค้า {argv[0]}")
        return 1
    print(f"สินค้า: {run.get('name') or argv[0]}")
    print(summary(run))
    nxt = next_target(run)
    print("\nถัดไป: " + (NAMES[nxt] if nxt else "ลงครบทุกที่แล้ว"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
