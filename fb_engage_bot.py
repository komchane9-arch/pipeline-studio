"""บอทตามยอดโพสต์ + ตอบคอมเมนต์ — โปรเซสแยกของตัวเอง

ทำไมต้องแยกโปรเซส: `getUpdates` ของโทเคนหนึ่งตัวมีตัวอ่านได้ตัวเดียว อ่านซ้อน
= 409 Conflict ข้อความหายสลับไปมา (บทเรียนเดียวกับสายคลิปและสายหาโพสต์แมส)
บอทตัวนี้จึงใช้โทเคนของตัวเองจากทะเบียน extra_bots แล้วเฝ้าเองทั้งตัว

รัน: python fb_engage_bot.py   (ต้องรันค้างไว้เหมือน app.py)

**งานหนักทุกอย่างรันใน thread แยก** ไม่ใช่ในลูปอ่านข้อความ ไม่งั้นระหว่างเก็บยอด
หลายนาทีบอทจะไม่ตอบอะไรเลย และสั่งหยุดก็ไม่ได้

**สถานะ: ยังไม่ได้ทดสอบกับมือถือ** เขียนตอน session อื่นใช้ ADB อยู่
"""

from __future__ import annotations

import re
import threading
import time
import traceback

import facebook_group_post as fb
import fb_engage
import fb_limits
import heartbeat
import studio_shared
import telegram_bot

HELP = (
    "🤖 <b>บอทตามยอดโพสต์ + ตอบคอมเมนต์</b>\n\n"
    "<b>ยอดโพสต์</b>\n"
    "• /stats — ไล่เปิดโพสต์เก่าแล้วเก็บยอด ถูกใจ/คอมเมนต์/แชร์\n"
    "• /mass — จัดอันดับว่าโพสต์ไหนแมส (พร้อมส่วนที่โตขึ้น)\n\n"
    "<b>ตอบคอมเมนต์</b>\n"
    "• /reply — ไล่ตอบคอมเมนต์ของคนอื่นหนึ่งรอบ\n"
    "• /reply on | off — เปิด/ปิดโหมดตอบกลับ\n"
    "• /owner — ดูบัญชีที่ใช้โพสต์ (ไว้แยกคอมเมนต์ของเราเอง)\n"
    "• /owner &lt;ชื่อ&gt; — เพิ่มบัญชี ใส่หลายชื่อคั่นด้วย , ได้\n"
    "• /owner ลบ &lt;ชื่อ&gt; — เอาบัญชีออก\n\n"
    "<b>อื่นๆ</b>\n"
    "• /set — ดูค่าที่ตั้งไว้ + ตามทันไหม\n"
    "• /limit — ดู/ตั้งเพดานคอมเมนต์ต่อชั่วโมงและต่อวัน (แยกรายบัญชีได้)\n"
    "• /auto on | off — เดินรอบเก็บยอดเองอัตโนมัติ\n"
    "• /stop — สั่งหยุดงานที่ทำอยู่"
)

_busy = threading.Lock()
_stop = threading.Event()
_current = ""


def log(message: str) -> None:
    studio_shared.append_log("publish", f"[engage] {message}")


def say(token: str, chat_id: str, text: str) -> None:
    try:
        telegram_bot.send_message(token, chat_id, text)
    except Exception as error:            # ส่งไม่ได้ต้องไม่ฆ่าลูป
        log(f"ส่งข้อความไม่ได้: {error}")


def telegram_target(config: dict) -> tuple[str, str]:
    """(โทเคน, chat id) ของบอทตัวนี้

    **โทเคนของบอทเพิ่มเติมไม่ได้อยู่ใน config.json** — ทะเบียนเก็บแค่
    id/name/username/role/chat_id ส่วนโทเคนเก็บเข้ารหัสไว้ที่
    `data/bots/<id>.bin` ต้องอ่านผ่าน `studio_shared.load_key`
    (เขียนรอบแรกอ่านจาก bot["token"] ซึ่งไม่มีอยู่จริง บอทเลยเริ่มไม่ติด)

    ตั้งชื่อบอทไว้แต่หาไม่เจอ = **พังดังๆ** ไม่ถอยไปใช้บอทหลักเงียบๆ ไม่งั้น
    ข้อความจะไปโผล่ผิดบอทแล้วงงกันทั้งวัน
    """
    studio = studio_shared.read_config()
    wanted = str(config.get("telegram_bot") or "").strip()
    if wanted:
        bot = next(
            (b for b in (studio.get("extra_bots") or [])
             if wanted.casefold() in (str(b.get("name", "")).casefold(),
                                      str(b.get("username", "")).casefold(),
                                      str(b.get("id", "")).casefold())),
            None)
        if bot is None:
            raise fb_engage.EngageError(
                f'ไม่พบบอท "{wanted}" ในทะเบียนบอทเพิ่มเติมของ Studio '
                "— เพิ่มในหน้าตั้งค่าก่อน หรือแก้ \"telegram_bot\" "
                f"ใน {fb_engage.CONFIG_FILE.name}")
        safe = re.sub(r"[^A-Za-z0-9_-]", "_", str(bot["id"]))[:40]
        token = studio_shared.load_key(
            studio_shared.DATA_DIR / "bots" / f"{safe}.bin") or ""
        chat_id = str(config.get("chat_id") or bot.get("chat_id")
                      or studio.get("telegram_chat_id") or "").strip()
        if not token:
            raise fb_engage.EngageError(
                f'บอท "{bot["name"]}" ยังไม่มีโทเคนบันทึกไว้ '
                "— ใส่โทเคนในหน้าตั้งค่า Studio ก่อน")
        if not chat_id:
            raise fb_engage.EngageError(
                f'ยังไม่รู้ chat id ของบอท "{bot["name"]}" '
                "— ทักข้อความหาบอทหนึ่งครั้งแล้วให้ Studio จำ")
        return token, chat_id
    # **ห้ามถอยไปใช้โทเคนบอทหลัก** — app.py เฝ้าโทเคนนั้นอยู่ อ่านซ้อนกันเมื่อไร
    # ก็ 409 Conflict ทันที แล้วข้อความจะหายสลับไปมาระหว่างสองบอท ซึ่งเป็นอาการ
    # ที่ไล่หาสาเหตุยากมาก (เคยเจอมาแล้วทั้งสายคลิปและสายหาโพสต์แมส)
    #
    # บังคับให้ตั้งบอทของตัวเองเสมอ พังตรงนี้ตอนเริ่มดีกว่าไปพังเงียบๆ ตอนใช้งาน
    raise fb_engage.EngageError(
        "ยังไม่ได้ตั้งบอทของตัวเอง — เพิ่มบอทใหม่ในหน้าตั้งค่า Studio "
        'โดยตั้งหน้าที่เป็น "engage" แล้วใส่ชื่อบอทนั้นลงในคีย์ "telegram_bot" '
        f"ของ {fb_engage.CONFIG_FILE.name}\n\n"
        "ห้ามใช้โทเคนร่วมกับบอทหลักหรือบอทตัวอื่น — โทเคนหนึ่งตัวมีตัวอ่านได้"
        "ตัวเดียว ใช้ซ้ำจะชนกันเป็น 409 Conflict")


def run_job(token: str, chat_id: str, name: str, work) -> None:
    """รันงานหนักใน thread แยก — ทำได้ทีละงานเท่านั้น"""
    global _current
    if not _busy.acquire(blocking=False):
        say(token, chat_id, f"⏳ กำลังทำ <b>{_current}</b> อยู่ — รอให้จบก่อน")
        return
    _stop.clear()
    _current = name

    def runner() -> None:
        global _current
        try:
            work()
        except fb_engage.EngageError as error:
            say(token, chat_id, f"❌ {telegram_bot._escape(str(error))}")
        except studio_shared.PhoneBusy as error:
            say(token, chat_id, f"📵 {telegram_bot._escape(str(error))}")
        except Exception:
            log(f"{name} ล้ม:\n{traceback.format_exc()}")
            say(token, chat_id, f"❌ {name} ล้มกลางทาง — ดูรายละเอียดใน log")
        finally:
            _current = ""
            _busy.release()

    threading.Thread(target=runner, daemon=True).start()


def do_stats(token: str, chat_id: str) -> None:
    config = fb_engage.load_config()
    say(token, chat_id, "📊 เริ่มเก็บยอดโพสต์…")

    def work() -> None:
        summary = fb_engage.refresh_stats(
            config, log=lambda m: log(m), stop=_stop.is_set)
        say(token, chat_id, (
            "📊 <b>เก็บยอดจบแล้ว</b>\n"
            f"เปิดดู {summary['checked']} โพสต์ · อัปเดตได้ {summary['updated']}"
            f" · อ่านไม่ได้ {summary['failed']}\n"
            f"โพสต์ที่ตามอยู่ทั้งหมด {summary['total']} ใบ\n\n"
            "ดูอันดับ: /mass"
        ))

    run_job(token, chat_id, "เก็บยอดโพสต์", work)


def do_mass(token: str, chat_id: str) -> None:
    config = fb_engage.load_config()
    rows = fb_engage.mass_report(config, top=10)
    if not rows:
        say(token, chat_id, "ยังไม่มีข้อมูลยอดเลย — สั่ง /stats ก่อน")
        return
    lines = ["🔥 <b>อันดับโพสต์</b> (คะแนน = ถูกใจ×1 + คอมเมนต์×3 + แชร์×5)", ""]
    for order, row in enumerate(rows, 1):
        def show(key: str) -> str:
            value = row.get(key)
            return "?" if value is None else str(value)
        gain = "" if row["gain"] is None else f" (+{row['gain']})"
        flag = "🔥 " if row["mass"] else ""
        lines.append(
            f"{order}. {flag}<b>{row['score']}</b>{gain} — "
            f"❤️ {show('reactions')} · 💬 {show('comments')} · 🔁 {show('shares')}"
        )
        lines.append(f"    <i>{telegram_bot._escape(row['caption'][:50])}…</i>")
        if row["link"]:
            lines.append(f"    {row['link']}")
    lines.append("\n<i>ค่า ? = แอปไม่แสดงตัวเลขนั้นบนหน้าโพสต์</i>")
    say(token, chat_id, "\n".join(lines))


def do_reply(token: str, chat_id: str, argument: str) -> None:
    config = fb_engage.load_config()
    switch = argument.strip().lower()
    if switch in ("on", "off", "เปิด", "ปิด"):
        config["reply_enabled"] = switch in ("on", "เปิด")
        fb_engage.save_config(config)
        state = "เปิด" if config["reply_enabled"] else "ปิด"
        say(token, chat_id, f"โหมดตอบกลับคอมเมนต์: <b>{state}</b>")
        return
    say(token, chat_id, "💬 เริ่มไล่ตอบคอมเมนต์…")

    def work() -> None:
        summary = fb_engage.reply_round(
            config, log=lambda m: log(m), stop=_stop.is_set)
        say(token, chat_id, (
            "💬 <b>ตอบคอมเมนต์จบแล้ว</b>\n"
            f"ตอบไป {summary['sent']} · ข้ามเพราะเข้าเงื่อนไขห้ามตอบ "
            f"{summary['skipped']}\n"
            f"เปิดดู {summary['posts']} โพสต์ · "
            f"เหลือโควตาชั่วโมงนี้ {summary['quota_left']}"
        ))

    run_job(token, chat_id, "ตอบคอมเมนต์", work)


_LIMIT_HELP = (
    "<code>/limit ชม 12</code> เพดานรวมต่อชั่วโมง\n"
    "<code>/limit วัน 50</code> เพดานต่อวัน\n"
    "<code>/limit เลน reply 4</code> ช่องของสายนั้น (post = งานโพสต์)\n"
    "<code>/limit บัญชี 7a95129e วัน 30</code> ตั้งเฉพาะเครื่องนั้น\n"
    "<code>/limit ล้าง 7a95129e</code> กลับไปใช้ค่าส่วนกลาง"
)


def _limit_view(config: dict) -> str:
    """เพดานทั้งหมดที่ใช้อยู่จริง — ค่าส่วนกลางก่อน แล้วตามด้วยบัญชีที่ตั้งเอง"""
    lines = ["🚦 <b>เพดานการคอมเมนต์</b>", ""]
    lines += [telegram_bot._escape(x) for x in fb_limits.describe("")]
    for account in sorted(fb_limits.accounts()):
        lines.append("")
        lines += [telegram_bot._escape(x) for x in fb_limits.describe(account)]
    serial = str(config.get("serial") or "").strip()
    if serial and serial not in fb_limits.accounts():
        lines.append("")
        lines.append(f"<i>เครื่องที่สายนี้ใช้ ({telegram_bot._escape(serial)}) "
                     "ยังไม่ได้ตั้งเอง จึงใช้ค่าส่วนกลาง</i>")
    lines.append("")
    lines.append(_LIMIT_HELP)
    return "\n".join(lines)


def do_limit(token: str, chat_id: str, argument: str) -> None:
    """ดู/ตั้งเพดานคอมเมนต์ — **ตั้งแยกรายบัญชีได้** เพราะแต่ละบัญชีโดนไม่เท่ากัน

    ตั้งใจให้ค่าที่ตั้งผิดเถียงกลับทันทีตรงนี้ (fb_limits โยน LimitError) แทนที่
    จะรับไว้เงียบๆ แล้วไปพังตอนคอมเมนต์จริงซึ่งไล่ย้อนกลับมาหาต้นเหตุยากกว่ามาก
    """
    config = fb_engage.load_config()
    words = (argument or "").split()
    if not words:
        say(token, chat_id, _limit_view(config))
        return

    account = ""
    if words[0] in ("บัญชี", "account", "เครื่อง"):
        if len(words) < 2:
            say(token, chat_id, "บอกด้วยว่าบัญชีไหน เช่น <code>/limit บัญชี 7a95129e วัน 30</code>")
            return
        account, words = words[1], words[2:]
    if words and words[0] in ("ล้าง", "clear", "ลบ"):
        target = account or (words[1] if len(words) > 1 else "")
        if not target:
            say(token, chat_id, "บอกด้วยว่าจะล้างของบัญชีไหน")
            return
        gone = fb_limits.forget(target)
        say(token, chat_id,
            (f"ล้างค่าเฉพาะของ <b>{telegram_bot._escape(target)}</b> แล้ว "
             "กลับไปใช้ค่าส่วนกลาง" if gone
             else f"<b>{telegram_bot._escape(target)}</b> ไม่เคยตั้งค่าเฉพาะไว้")
            + "\n\n" + _limit_view(config))
        return

    try:
        if words[0] in ("เลน", "lane"):
            if len(words) < 3:
                say(token, chat_id, "ใช้ <code>/limit เลน reply 4</code>")
                return
            fb_limits.set_limits(account, lanes={words[1]: int(words[2])})
        elif words[0] in ("ชม", "ชั่วโมง", "hour", "hourly"):
            fb_limits.set_limits(account, per_hour=int(words[1]))
        elif words[0] in ("วัน", "day", "daily"):
            fb_limits.set_limits(account, per_day=int(words[1]))
        else:
            say(token, chat_id, "อ่านคำสั่งไม่ออก\n\n" + _LIMIT_HELP)
            return
    except (IndexError, ValueError) as error:
        # LimitError สืบทอดจาก ValueError จึงกินทั้งค่าที่ใส่ผิดชนิดและใส่ไม่ครบ
        say(token, chat_id, f"❌ {telegram_bot._escape(str(error) or 'ใส่ตัวเลขไม่ครบ')}"
                            "\n\n" + _LIMIT_HELP)
        return
    say(token, chat_id, "✅ ตั้งเพดานแล้ว\n\n" + _limit_view(config))


def do_set(token: str, chat_id: str) -> None:
    config = fb_engage.load_config()
    tracked = len(fb_engage.load_stats())
    lines = [
        "⚙️ <b>ค่าที่ตั้งไว้</b>",
        "• บัญชีที่ใช้โพสต์: <b>"
        + telegram_bot._escape(", ".join(fb_engage.owner_list(config)) or "(ยังไม่ตั้ง)")
        + "</b>",
        f"• โหมดตอบกลับ: <b>{'เปิด' if config.get('reply_enabled') else 'ปิด'}</b>",
        f"• เก็บยอดซ้ำทุก: {config.get('refresh_hours')} ชั่วโมง",
        f"• ต่อรอบเก็บยอด: {config.get('max_posts_per_round')} โพสต์",
        f"• ต่อรอบตอบกลับ: {config.get('max_replies_per_round')} คอมเมนต์",
        f"• คะแนนที่ถือว่าแมส: {config.get('mass_score')}",
        f"• เดินรอบอัตโนมัติ: <b>{'เปิด' if config.get('auto') else 'ปิด'}</b>"
        f" (ทุก {config.get('auto_every_minutes')} นาที)",
        "",
        f"ตามยอดอยู่ {tracked} โพสต์ · ตอบไปแล้ว {len(fb_engage.load_replies())} คอมเมนต์",
    ]

    # **ตามทันไหม** — ความล้มเหลวชนิด "โพสต์ท้ายแถวไม่เคยถูกอ่าน" เงียบสนิท
    # ถ้าไม่เอาตัวเลขมาโชว์ตรงนี้ ก็ไม่มีทางรู้จนกว่าจะมานั่งคำนวณเอง
    fit = fb_engage.capacity_check(config)
    lines.append("")
    lines.append(
        f"📐 <b>กำลังเก็บยอด</b>: ต้องการ {fit['demand_per_day']} ครั้ง/วัน · "
        f"ทำได้ {fit['capacity_per_day']} ครั้ง/วัน "
        f"(ใช้จอ {fit['screen_minutes_per_day']} นาที/วัน)")
    lines.append("   ✅ ตามทัน" if fit["keeps_up"] else
                 f"   ⚠️ <b>ตามไม่ทัน {fit['short_by']} เท่า</b> — "
                 "โพสต์ท้ายแถวจะไม่ถูกอ่านเลย ลด refresh_hours หรือ "
                 "เพิ่ม max_posts_per_round")

    # โควตาที่เหลือของ **เลนตัวเอง** ไม่ใช่ของทั้งบัญชี — ตัวเลขนี้คือสิ่งที่
    # จำกัดสายนี้จริง และทำให้เห็นว่าไม่ได้ไปกินช่องของงานโพสต์
    serial = str(config.get("serial") or "").strip()
    lines.append("")
    lines.append(
        f"🚦 <b>ช่องคอมเมนต์เลนตอบกลับ</b>: เหลือ "
        f"{fb.comment_quota_left(fb_engage.REPLY_LANE, serial)}/"
        f"{fb.comment_lane_limit(fb_engage.REPLY_LANE, serial)} ชั่วโมงนี้ "
        f"(เพดานบัญชี {fb.comment_limit_per_hour(serial)}/ชม. · "
        f"{fb_limits.per_day(serial)}/วัน) — ดู/แก้ที่ /limit")
    lines.append("")
    lines.append(f"<i>แก้ค่าอื่นๆ ได้ที่ {fb_engage.CONFIG_FILE.name}</i>")
    say(token, chat_id, "\n".join(lines))


def _owner_text(names: list[str]) -> str:
    if not names:
        return "ยังไม่ได้ตั้งบัญชีไหนเลย"
    return "\n".join(
        f"{i}. <b>{telegram_bot._escape(n)}</b>" for i, n in enumerate(names, 1))


def do_owner(token: str, chat_id: str, argument: str) -> None:
    """ดู/เพิ่ม/ลบ บัญชีที่ใช้โพสต์ — **เก็บได้หลายบัญชี**

    ผู้ใช้โพสต์จากหลายบัญชี (ฟาร์มบอทมี 10 โปรไฟล์) ถ้าจำได้บัญชีเดียว
    คอมเมนต์ของบัญชีอื่นของเราเองจะถูกมองเป็นของคนนอก แล้วบอทจะไปตอบตัวเอง
    วนไม่จบ ซึ่งคือสิ่งที่ค่านี้มีไว้กันตั้งแต่แรก

    ตั้งใจให้ `/owner <ชื่อ>` เป็น "เพิ่ม" ไม่ใช่ "แทนที่" — คำสั่งเดียวกับของเดิม
    แต่ถ้ายังแทนที่อยู่ ผู้ใช้ที่พิมพ์บัญชีที่สองจะทำบัญชีแรกหายโดยไม่รู้ตัว
    """
    argument = argument.strip()
    config = fb_engage.load_config()
    current = fb_engage.owner_list(config)

    def store(names: list[str]) -> None:
        config["owner_names"] = names
        config["owner_name"] = ""      # ย้ายมารวมที่ช่องใหม่หมดแล้ว กันอ่านซ้อน
        fb_engage.save_config(config)

    if not argument:
        say(token, chat_id,
            "👤 <b>บัญชีที่ใช้โพสต์</b>\n" + _owner_text(current)
            + "\n\n<code>/owner ชื่อ</code> เพิ่ม (คั่นด้วย , ได้หลายชื่อ)"
            + "\n<code>/owner ลบ ชื่อ</code> เอาออก"
            + "\n<code>/owner ล้าง</code> ลบทั้งหมด")
        return

    head, _, rest = argument.partition(" ")
    if head.lower() in ("ล้าง", "clear", "reset"):
        store([])
        say(token, chat_id, "ล้างรายชื่อบัญชีทั้งหมดแล้ว — ต้องตั้งใหม่ก่อนสั่ง /reply")
        return

    if head.lower() in ("ลบ", "del", "remove", "-"):
        target = rest.strip()
        if not target:
            say(token, chat_id, "ใส่ชื่อที่จะลบด้วย เช่น <code>/owner ลบ Kamolchanok</code>")
            return
        keep = [n for n in current if n.casefold() != target.casefold()]
        if len(keep) == len(current):
            say(token, chat_id,
                f"ไม่มี <b>{telegram_bot._escape(target)}</b> ในรายชื่อ\n\n" + _owner_text(current))
            return
        store(keep)
        say(token, chat_id,
            f"เอา <b>{telegram_bot._escape(target)}</b> ออกแล้ว\n\n" + _owner_text(keep))
        return

    # เพิ่ม — รับหลายชื่อคั่นด้วยจุลภาคในครั้งเดียว
    added, dup = [], []
    names = list(current)
    for piece in argument.split(","):
        name = piece.strip()
        if not name:
            continue
        if any(name.casefold() == n.casefold() for n in names):
            dup.append(name)
            continue
        names.append(name)
        added.append(name)
    if not added:
        say(token, chat_id,
            ("มีอยู่แล้วทั้งหมด" if dup else "อ่านชื่อไม่ออก")
            + "\n\n" + _owner_text(names))
        return
    store(names)
    note = f"\n<i>ข้ามที่ซ้ำ: {telegram_bot._escape(', '.join(dup))}</i>" if dup else ""
    say(token, chat_id,
        f"เพิ่ม {len(added)} บัญชีแล้ว{note}\n\n👤 <b>บัญชีที่ใช้โพสต์</b>\n"
        + _owner_text(names))


def do_auto(token: str, chat_id: str, argument: str) -> None:
    config = fb_engage.load_config()
    switch = argument.strip().lower()
    if switch not in ("on", "off", "เปิด", "ปิด"):
        say(token, chat_id, "ใช้ <code>/auto on</code> หรือ <code>/auto off</code>")
        return
    config["auto"] = switch in ("on", "เปิด")
    fb_engage.save_config(config)
    state = "เปิด" if config["auto"] else "ปิด"
    say(token, chat_id, f"เดินรอบเก็บยอดอัตโนมัติ: <b>{state}</b>")


def on_command(token: str, chat_id: str, text: str) -> None:
    command, _, argument = text.partition(" ")
    command = command.split("@")[0].lower()
    if command in ("/start", "/help"):
        say(token, chat_id, HELP)
    elif command == "/stats":
        do_stats(token, chat_id)
    elif command == "/mass":
        do_mass(token, chat_id)
    elif command == "/reply":
        do_reply(token, chat_id, argument)
    elif command == "/owner":
        do_owner(token, chat_id, argument)
    elif command == "/set":
        do_set(token, chat_id)
    elif command == "/limit":
        do_limit(token, chat_id, argument)
    elif command == "/auto":
        do_auto(token, chat_id, argument)
    elif command == "/stop":
        _stop.set()
        say(token, chat_id, "⏹ สั่งหยุดแล้ว — จะหยุดหลังโพสต์ที่ทำอยู่จบ")
    else:
        say(token, chat_id, HELP)


def _auto_loop(token: str, chat_id: str) -> None:
    """เดินรอบเก็บยอดเองตามเวลาที่ตั้งไว้

    เงียบเป็นปกติ — รายงานเฉพาะตอนที่มีอะไรอัปเดตจริง ไม่งั้นแชทจะเต็มไปด้วย
    "ไม่มีอะไรใหม่" ทุกสามชั่วโมง
    """
    while True:
        config = fb_engage.load_config()
        wait = max(15, int(config.get("auto_every_minutes", 180))) * 60
        time.sleep(wait)
        if not fb_engage.load_config().get("auto"):
            continue
        if _busy.locked():
            continue
        busy = fb_engage.phone_busy_elsewhere()
        if busy:
            log(f"ข้ามรอบอัตโนมัติ — {busy}")
            continue

        def work() -> None:
            summary = fb_engage.refresh_stats(
                fb_engage.load_config(), log=lambda m: log(m),
                stop=_stop.is_set)
            if summary["updated"]:
                say(token, chat_id,
                    f"📊 รอบอัตโนมัติ: อัปเดต {summary['updated']} โพสต์ · /mass")

        run_job(token, chat_id, "เก็บยอดอัตโนมัติ", work)


def main() -> int:
    config = fb_engage.load_config()
    token, home_chat = telegram_target(config)
    log(f"บอทตามยอด/ตอบคอมเมนต์เริ่มทำงาน (chat {home_chat})")
    say(token, home_chat, "🟢 บอทตามยอดโพสต์พร้อมทำงาน\n\n" + HELP)
    threading.Thread(target=_auto_loop, args=(token, home_chat), daemon=True).start()

    offset = 0
    while True:
        try:
            updates = telegram_bot.call(token, "getUpdates", {
                "timeout": telegram_bot.POLL_TIMEOUT, "offset": offset,
            }, timeout=telegram_bot.POLL_REQUEST_TIMEOUT)
        except telegram_bot.TelegramError as error:
            log(f"อ่านข้อความไม่ได้: {error}")
            time.sleep(15)
            continue
        for update in updates:
            offset = max(offset, update.get("update_id", 0) + 1)
            try:
                message = update.get("message") or {}
                chat_id = str((message.get("chat") or {}).get("id", ""))
                text = (message.get("text") or "").strip()
                if not chat_id or not text:
                    continue
                if chat_id != str(home_chat):
                    log(f"เมินข้อความจาก chat แปลกหน้า {chat_id}")
                    continue
                if text.startswith("/"):
                    on_command(token, chat_id, text)
                else:
                    say(token, chat_id, HELP)
            except Exception:
                # ข้อความเดียวพังต้องไม่ฆ่าลูป แต่ต้องลง log เสมอ
                log(f"จัดการข้อความไม่สำเร็จ:\n{traceback.format_exc()}")


if __name__ == "__main__":
    raise SystemExit(main())
