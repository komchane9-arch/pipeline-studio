"""บอท Telegram สายหาโพสต์แมส (@NewestBoyBot) — โปรเซสแยกของตัวเอง

ทำไมต้องแยกโปรเซส: getUpdates ของโทเคนหนึ่งตัวมีตัวอ่านได้ตัวเดียว (อ่านซ้อน
= 409 Conflict ข้อความหายสลับไปมา — บทเรียนเดียวกับบอทสายคลิปที่แยกไป
clip_app.py) บอทตัวนี้จึงตั้ง role เป็น "mass" ซึ่ง app.py (8866) จะไม่เฝ้า
แล้วโปรเซสนี้เฝ้าเองทั้งตัว

คำสั่ง:
    /find            เริ่มสแกนหาโพสต์แมสทุกกลุ่มทันที
    /add <ลิงก์>     กดเข้าร่วมกลุ่ม + เพิ่มเข้า list ค้นหา
    /groups          ดูกลุ่มทั้งหมด กดปุ่มลบได้
    /pending         งานค้างรอตัดสิน (ก้ำกึ่งรอ Approve/Reject + ที่ปัดตกไว้ กู้คืนได้)
    /set             ดู/ปรับเกณฑ์ (ไลค์ แชร์ คอมเมนต์ รอบเลื่อนฟีด)

รัน: python fb_mass_bot.py   (ต้องรันค้างไว้เหมือน app.py/clip_app.py)
"""

from __future__ import annotations

import html
import msvcrt
import re
import threading
import time
import traceback
from datetime import datetime
from pathlib import Path

import fb_mass_finder as mf          # พ่วง utf-8 guard ของ stdout มาด้วย
import studio_shared
import telegram_bot
from bot_profiles import FarmError

LOCK_FILE = mf.DATA_DIR / "fb_mass_bot.lock"
# ชีพจร — เขียนเวลาปัจจุบันทุกรอบ poll ให้ app.py เช็คว่าบอทยังมีชีวิต
# (app.py ปลุกใหม่ถ้าชีพจรค้างเกิน ~90 วิ) ใช้ไฟล์แยกจากล็อก เพราะเปิดไฟล์
# ที่ถูก msvcrt ล็อกจากอีกโปรเซสได้ PermissionError — เช็คด้วยล็อกไม่ได้
HEARTBEAT_FILE = mf.DATA_DIR / "fb_mass_bot.heartbeat"
LOG_FILE = studio_shared.LOG_DIR / "fb_mass.log"
LOG_LIMIT = studio_shared.LOG_LIMIT_BYTES


def beat() -> None:
    """แตะไฟล์ชีพจร — บอก app.py ว่ายังมีชีวิต"""
    try:
        HEARTBEAT_FILE.write_text(str(int(time.time())), encoding="utf-8")
    except OSError:
        pass


def _heartbeat_loop() -> None:
    """เต้นทุก 15 วิใน thread แยก — ไม่ผูกกับ getUpdates ที่อาจ long-poll ค้างนาน
    (ถ้า beat แค่ในลูปหลัก ชีพจรจะห่างเท่า latency ของ poll แล้วดูเหมือนตาย)"""
    while True:
        beat()
        time.sleep(15)

HELP = "\n".join([
    "🤖 <b>บอทหาโพสต์แมส</b>",
    "/find — เริ่มหาโพสต์แมสทุกกลุ่มตอนนี้",
    "/test — เจาะลึก 1000 โพสต์ล่าสุด (เลือกได้หลายกลุ่ม เทียบกัน)",
    "/keyword คำค้น — หากลุ่ม >100k แล้ว test อัตโนมัติทุกกลุ่ม "
    "(มีชีวิต→whitelist · ตาย→ตัดทิ้ง · ก้ำกึ่ง→ถามคุณ) สรุปตอนจบ",
    "/keyword คำค้น 10k-50k — จำกัดช่วงสมาชิกเอง (ใส่ได้ทั้ง 10k และ 10000)",
    "/bands — กวาดช่วง 10k–50k และ 50k–100k ของ<b>ทุกคำค้นเดิม</b>ต่อให้อัตโนมัติ",
    "/recheck [จำนวน] — เจาะซ้ำกลุ่มที่เคยถูกตัดว่าตาย ด้วยตัวนับที่แก้แล้ว",
    "/pending — งานค้างรอตัดสิน: กลุ่มก้ำกึ่งรอ Approve/Reject + ที่ปัดตกไว้ (กู้คืนได้)",
    "/whitelists — กลุ่มที่ผ่านทั้งหมดทุกคำค้น",
    "/whitelist — กลุ่มที่ผ่านแยกตามคำค้น (เลือกคำค้นก่อน)",
    "/private — ดูกลุ่มส่วนตัวที่ระบบตรวจพบและบันทึกแยกไว้",
    "/add ลิงก์กลุ่ม — เข้าร่วมกลุ่ม + เพิ่มเข้า list",
    "/groups — ดูกลุ่มทั้งหมด เลือกลบได้",
    "/set — ดู/ปรับเกณฑ์คัดโพสต์",
])

# รุ่นของ state — migration ของ flow เก่ารันเฉพาะตอน state ยังต่ำกว่ารุ่นนี้
# (ถ้าไม่ล็อกไว้ การ์ดก้ำกึ่งของ flow ใหม่จะถูกล้างทิ้งทุกครั้งที่รีสตาร์ต)
KW_SCHEMA = 2

# ความล้มเหลว "เชิงสภาพแวดล้อม" = ทรัพยากรไม่ว่าง ไม่ใช่กลุ่มมีปัญหา
# ต้องคืนกลุ่มเข้าคิว ห้ามนับเป็นเจาะแล้ว (ดู requeue() ใน _kw_run_next_test)
BUSY_ERRORS = (studio_shared.BotBusy, studio_shared.BrowserBusy)

# จำนวนโพสต์ที่ /test เจาะลึกต่อกลุ่ม (ตามที่ผู้ใช้สั่ง: 1000 โพสต์ล่าสุด)
TEST_TARGET = 1000
# กลุ่มที่ผู้ใช้ติ๊กเลือกใน /test — {chat_id: set(index)} (ในหน่วยความจำพอ
# เพราะเลือกเสร็จกดเริ่มในคราวเดียว รีสตาร์ตก็แค่เลือกใหม่)
_test_selection: dict[str, set] = {}

# ชื่อเกณฑ์ที่ /set รับ — รับทั้งไทย/อังกฤษ (พิมพ์แบบไหนก็ต้องเข้าใจ)
SET_FIELDS = {
    # เกณฑ์หลักคือ engagement รวม — รับทั้งคำใหม่และคำเก่า "ไลค์" (คนชินคำเดิม)
    "min_likes": ("engagement", "เอนเกจ", "แมส", "ไลค์", "ไลก์", "like", "likes"),
    "min_shares": ("แชร์", "share", "shares"),
    "min_comments": ("คอมเมนต์", "คอมเม้น", "comment", "comments"),
    "max_posts": ("โพสต์", "จำนวนโพสต์", "post", "posts"),
    "scrolls": ("เลื่อน", "scroll", "scrolls"),
}

# งานเบราว์เซอร์ (สแกน/เข้ากลุ่ม) ทำทีละอย่าง — โปรไฟล์ต้องไม่ใช่ Bot10
_busy = threading.Lock()

# การ์ด /groups ใบล่าสุดของแต่ละแชท — ปุ่มลบผูกกับ "ลำดับในรายการ" ซึ่งเลื่อนได้
# เมื่อรายการเปลี่ยน กดจากการ์ดเก่าจะลบผิดกลุ่ม จึงยอมรับเฉพาะใบล่าสุดเท่านั้น
# (ใบเก่าถูกกด = ถอดปุ่มทิ้ง + ส่งใบใหม่ให้แทน) — in-memory พอ รีสตาร์ตแล้ว
# ใบก่อนหน้าทั้งหมดถือว่าเก่า ผู้ใช้ได้ใบสดใหม่เสมอ
_groups_card_mid: dict[str, int] = {}


def _send_groups_card(token: str, chat_id: str) -> None:
    """ส่งการ์ด /groups ใบใหม่ + จดว่าใบนี้คือใบล่าสุดที่กดได้"""
    message, keyboard = groups_card(mf.load_config())
    try:
        mid = telegram_bot.send_message(token, chat_id, message, keyboard)
        _groups_card_mid[chat_id] = mid
    except telegram_bot.TelegramError as error:
        log(f"ส่งการ์ดกลุ่มไม่ได้: {error}")


def log(message: str) -> None:
    """เขียน log ลงไฟล์ (หมุนเองที่ 90% ของเพดาน) + สะท้อนขึ้นจอ"""
    print(f"{datetime.now():%H:%M:%S} {message}", flush=True)
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        if LOG_FILE.is_file() and LOG_FILE.stat().st_size >= LOG_LIMIT * 0.9:
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            LOG_FILE.replace(LOG_FILE.with_name(f"fb_mass-{stamp}.log"))
        with LOG_FILE.open("a", encoding="utf-8") as handle:
            handle.write(f"{datetime.now():%H:%M:%S} {message}\n")
    except OSError:
        pass


def say(token: str, chat_id: str, text: str, keyboard: dict | None = None) -> None:
    try:
        telegram_bot.send_message(token, chat_id, text, keyboard)
    except telegram_bot.TelegramError as error:
        log(f"ส่งข้อความไม่ได้: {error}")


# ------------------------------------------------------------------- คำสั่ง

def groups_card(config: dict) -> tuple[str, dict | None]:
    groups = config.get("groups", [])
    if not groups:
        return "ยังไม่มีกลุ่มใน list — เพิ่มด้วย /add ลิงก์กลุ่ม", None
    lines = [f"📋 <b>กลุ่มที่ค้นหา ({len(groups)} กลุ่ม)</b>", ""]
    rows = []
    for index, group in enumerate(groups, 1):
        name = group.get("name") or group.get("url", "")
        lines.append(f"{index}. {html.escape(name[:60])}")
        rows.append([{
            "text": f"🗑 ลบ {index}. {name[:24]}",
            "callback_data": f"md:{index - 1}",
        }])
    lines += ["", "กดปุ่มด้านล่างเพื่อลบกลุ่มออกจาก list"]
    return "\n".join(lines), {"inline_keyboard": rows}


# ---------------------------------------------------- /test เจาะลึกหลายกลุ่ม

def test_card(config: dict, selected: set) -> tuple[str, dict | None]:
    """การ์ดเลือกกลุ่มสำหรับ /test — ติ๊กได้หลายกลุ่ม"""
    groups = config.get("groups", [])
    if not groups:
        return "ยังไม่มีกลุ่มใน list — เพิ่มด้วย /add ลิงก์กลุ่มก่อน", None
    lines = [f"🔬 <b>เลือกกลุ่มเจาะลึก {TEST_TARGET:,} โพสต์ล่าสุด</b>",
             "ติ๊กได้หลายกลุ่มเพื่อเทียบกัน แล้วกดเริ่ม", ""]
    rows = []
    for index, group in enumerate(groups):
        name = group.get("name") or group.get("url", "")
        mark = "☑️" if index in selected else "⬜"
        rows.append([{"text": f"{mark} {name[:34]}",
                      "callback_data": f"mt:t:{index}"}])
    rows.append([
        {"text": "เลือกทั้งหมด", "callback_data": "mt:all"},
        {"text": "ล้าง", "callback_data": "mt:none"},
    ])
    rows.append([{"text": f"▶️ เริ่มเจาะลึก ({len(selected)} กลุ่ม)",
                  "callback_data": "mt:go"}])
    return "\n".join(lines), {"inline_keyboard": rows}


def do_test(token: str, chat_id: str, groups: list) -> None:
    """เจาะลึกกลุ่มที่เลือก แล้วรายงานสถิติ engagement เทียบกัน"""
    if not _busy.acquire(blocking=False):
        say(token, chat_id, "⏳ มีงานเบราว์เซอร์ค้างอยู่ — รอให้เสร็จก่อนแล้วสั่งใหม่")
        return

    def work() -> None:
        try:
            mins = max(1, len(groups) * TEST_TARGET // 80)   # ~12 นาที/กลุ่ม
            say(token, chat_id,
                f"🔬 เจาะลึก {len(groups)} กลุ่ม กลุ่มละสูงสุด {TEST_TARGET:,} โพสต์ "
                f"(~{mins} นาที) — เดี๋ยวสรุปผลเทียบให้")
            results = mf.deep_scan_groups(groups, TEST_TARGET, log=log)
            # กราฟ PNG ก่อน (ภาพรวมเห็นง่าย) แล้วตามด้วยรายงานข้อความ (มีลิงก์)
            min_eng = int(mf.load_config().get("min_likes", 100))
            chart = mf.render_test_chart(results, min_eng, log=log)
            if chart and chart.is_file():
                try:
                    telegram_bot.send_photo(
                        token, chat_id, chart,
                        caption="🔬 ผลเจาะลึก — engagement ตามความลึกฟีด")
                except telegram_bot.TelegramError as error:
                    log(f"ส่งกราฟไม่ได้: {error}")
            say(token, chat_id, _test_report(results))
            log(f"/test เสร็จ {len(results)} กลุ่ม")
        except (mf.MassFinderError, FarmError) as error:
            say(token, chat_id, f"❌ {error}")
            log(f"/test ล้ม: {error}")
        except Exception:
            say(token, chat_id, "❌ เจาะลึกล้มกลางทาง — ดูรายละเอียดใน log")
            log(f"/test ล้มกลางทาง:\n{traceback.format_exc()}")
        finally:
            _busy.release()

    threading.Thread(target=work, daemon=True).start()


def _test_report(results: list) -> str:
    """สรุปผล /test — เรียงกลุ่มที่ engagement ดีสุดขึ้นก่อน"""
    ok = [r for r in results if not r.get("error")]
    ok.sort(key=lambda r: -r["avg"])
    lines = ["🔬 <b>ผลเจาะลึก (เรียงตาม engagement เฉลี่ย)</b>", ""]
    for r in ok:
        verdict = "✅ มีชีวิต" if r["over"] >= 5 else "❌ เงียบ"
        lines.append(f"<b>{html.escape(r['name'][:40])}</b> {verdict}")
        vids = r.get("videos", 0)
        vid_note = f" · 🎬 วิดีโอ {vids}" if vids else ""
        lines.append(f"อ่าน {r['count']:,} · เกิน 100: {r['over']} · "
                     f"เฉลี่ย {r['avg']}{vid_note} ({r['seconds']:.0f} วิ)")
        for i, p in enumerate(r["top"][:3], 1):
            vw = f" 👁{p['views']:,}" if p.get("views", 0) else ""
            lines.append(f"  {i}. 🔥{p['eng']:,} (❤️{p['likes']} 💬{p['comments']} "
                         f"↗{p['shares']}{vw})\n  {p['url']}")
        lines.append("")
    for r in results:
        if r.get("error"):
            lines.append(f"⚠ {html.escape(r['name'][:40])}: อ่านไม่ได้")
    return "\n".join(lines).strip()


def do_find(token: str, chat_id: str) -> None:
    if not _busy.acquire(blocking=False):
        say(token, chat_id, "⏳ มีงานเบราว์เซอร์ค้างอยู่ — รอให้เสร็จก่อนแล้วสั่งใหม่")
        return

    def work() -> None:
        try:
            config = mf.load_config()
            say(token, chat_id,
                f"🔎 เริ่มสแกน {len(config.get('groups', []))} กลุ่ม "
                f"(~35 วิ/กลุ่ม) — เจอโพสต์ใหม่จะส่งมาทีละกลุ่ม")
            summary = mf.run(use_telegram=True, log=log)
            log(f"สแกนเสร็จ ส่งใหม่ {summary['sent_new']} ลิงก์")
        except (mf.MassFinderError, FarmError) as error:
            say(token, chat_id, f"❌ {error}")
            log(f"สแกนล้ม: {error}")
        except Exception:
            say(token, chat_id, "❌ สแกนล้มกลางทาง — ดูรายละเอียดใน log")
            log(f"สแกนล้มกลางทาง:\n{traceback.format_exc()}")
        finally:
            _busy.release()

    threading.Thread(target=work, daemon=True).start()


def do_add(token: str, chat_id: str, url: str) -> None:
    if not re.match(r"https?://(www\.|web\.|m\.)?facebook\.com/", url):
        say(token, chat_id,
            "ต่อท้ายด้วยลิงก์กลุ่ม Facebook เช่น\n"
            "<code>/add https://www.facebook.com/share/g/xxxx/</code>")
        return
    if not _busy.acquire(blocking=False):
        say(token, chat_id, "⏳ มีงานเบราว์เซอร์ค้างอยู่ — รอให้เสร็จก่อนแล้วสั่งใหม่")
        return

    def work() -> None:
        try:
            say(token, chat_id, "🚪 กำลังเปิดกลุ่มด้วยโปรไฟล์บอท…")
            result = mf.join_group(url, log=log)
            status = {
                "joined-request": "✅ เข้าร่วมกลุ่มสำเร็จ",
                "already": "✅ เป็นสมาชิกอยู่แล้ว",
                "pending": "⏳ ส่งคำขอแล้ว — รอแอดมินอนุมัติ",
                "stuck": "⚠️ กดเข้าร่วมแล้วแต่กลุ่มอาจมีคำถามสมาชิกให้กรอก "
                         "— เปิดบอทเข้าไปกรอกเองหนึ่งครั้ง",
            }.get(result["status"], result["status"])
            note = ("เพิ่มเข้า list ค้นหาแล้ว ✅" if result["added"]
                    else "มีอยู่ใน list แล้ว ไม่เพิ่มซ้ำ")
            say(token, chat_id,
                f"<b>{html.escape(result['name'] or url)}</b>\n{status}\n{note}")
            log(f"/add {url} → {result['status']} added={result['added']}")
        except (mf.MassFinderError, FarmError) as error:
            say(token, chat_id, f"❌ {error}")
            log(f"/add ล้ม: {error}")
        except Exception:
            say(token, chat_id, "❌ เข้าร่วมกลุ่มไม่สำเร็จ — ดูรายละเอียดใน log")
            log(f"/add ล้มกลางทาง:\n{traceback.format_exc()}")
        finally:
            _busy.release()

    threading.Thread(target=work, daemon=True).start()


# ------------------------------------------- /keyword หากลุ่มใหม่ตามคำค้น

# เลื่อนหน้า search กี่รอบต่อการขุดหนึ่งครั้ง (ขุดซ้ำจะลึกกว่าเดิมทีละชุด)
KW_SEARCH_ROUNDS = 6


def kw_caption(group: dict, keyword: str) -> str:
    """ข้อความบรรยายการ์ดเสนอกลุ่ม (ใช้เป็น caption ของรูปหน้ากลุ่ม)"""
    return "\n".join([
        f'📣 กลุ่มจากคำค้น "{html.escape(keyword)}"',
        f"<b>{html.escape((group.get('name') or '?')[:60])}</b>",
        f"👥 สมาชิก ~{group.get('members', 0):,} คน",
        group.get("url", ""),
    ])


def kw_buttons(gid: str) -> dict:
    return {"inline_keyboard": [[
        {"text": "✅ Approve → /test", "callback_data": f"kg:ap:{gid[:50]}"},
        {"text": "❌ Reject", "callback_data": f"kg:rj:{gid[:50]}"},
    ]]}


# (ปุ่ม Keep/Removed ของ flow เก่าถูกแทนด้วยการตัดสินอัตโนมัติ — ตัวจัดการ kk:
#  ยังอยู่เพื่อปิดปุ่มการ์ดเก่าที่ค้างในประวัติแชทอย่างสุภาพ)


def _kw_del_shot(group: dict | None) -> None:
    """ลบไฟล์ภาพหน้ากลุ่มที่แคปไว้ (ส่งเข้า Telegram แล้ว เก็บในเครื่องต่อไม่จำเป็น)"""
    shot = (group or {}).get("shot")
    if shot:
        try:
            Path(shot).unlink(missing_ok=True)
        except OSError:
            pass


def _kw_edit_card(token: str, chat_id: str, group: dict, extra: str) -> None:
    """แก้การ์ดเดิมให้ขึ้นสถานะ (รูป=editMessageCaption · ข้อความ=editMessageText)"""
    mid = group.get("message_id")
    if not mid:
        return
    # การ์ดก้ำกึ่งเก็บ caption จริงไว้ — ใช้ตัวนั้น ไม่งั้นข้อความเดิมจะถูกทับผิดรูปแบบ
    base = group.get("caption") or kw_caption(group, group.get("keyword", ""))
    photo = group.get("is_photo")
    method = "editMessageCaption" if photo else "editMessageText"
    field = "caption" if photo else "text"
    try:
        telegram_bot.call(token, method, {
            "chat_id": chat_id, "message_id": mid,
            field: base + "\n\n" + extra, "parse_mode": "HTML"})
    except telegram_bot.TelegramError as error:
        log(f"แก้การ์ดกลุ่มไม่ได้: {error}")


def _config_add_group(group: dict) -> bool:
    """เพิ่มกลุ่มเข้า list หาโพสต์แมส (กันซ้ำด้วย group id) — เพิ่มจริงคืน True"""
    config = mf.load_config()
    gid = group.get("gid", "")
    known = {mf.group_id_from_url(g.get("canonical") or g.get("url", ""))
             for g in config.get("groups", [])}
    if gid and gid in known:
        return False
    config.setdefault("groups", []).append({
        "url": group.get("url", ""), "canonical": group.get("url", ""),
        "name": group.get("name", "")})
    mf.save_config(config)
    return True


def _config_remove_group(gid: str) -> bool:
    """เอากลุ่มออกจาก list หาโพสต์แมส — เอาออกจริงคืน True"""
    config = mf.load_config()
    groups = config.get("groups", [])
    kept = [g for g in groups
            if mf.group_id_from_url(g.get("canonical") or g.get("url", "")) != gid]
    if len(kept) == len(groups):
        return False
    config["groups"] = kept
    mf.save_config(config)
    return True


def _kw_range(state: dict) -> tuple[int, int]:
    """ช่วงสมาชิกที่รอบนี้สนใจ — (ล่าง, บน) · บน = 0 แปลว่าไม่จำกัด"""
    return (int(state.get("min_members") or mf.KW_MIN_MEMBERS),
            int(state.get("max_members") or 0))


def _kw_in_range(members: int, low: int, high: int) -> bool:
    """อยู่ในช่วง (ล่าง, บน] ไหม — ขอบบนนับรวม ขอบล่างไม่นับ

    ทำแบบนี้แบนด์ 10k-50k / 50k-100k / >100k จึงต่อกันสนิทโดยไม่ทับกัน
    (กลุ่ม 50,000 คนพอดีอยู่แบนด์แรกที่เดียว)
    """
    if members <= low:
        return False
    return not high or members <= high


def _kw_next_candidate(state: dict) -> dict | None:
    """หยิบกลุ่มถัดไปจากคิวที่ยังไม่ถูกปัด/ไม่เคยส่ง/ไม่ส่วนตัว — คืน None ถ้าไม่มี"""
    low, high = _kw_range(state)
    while state["queue"]:
        group = state["queue"].pop(0)
        gid = group.get("gid", "")
        if not gid or gid in state["rejected"] or gid in state["sent"] \
                or gid in state.get("private", {}):
            continue
        if not _kw_in_range(group.get("members", 0), low, high):
            continue
        mf.save_kw_state(state)
        return group
    mf.save_kw_state(state)
    return None


def _kw_mark_private(gid: str, group: dict, via: str) -> None:
    """จดกลุ่มเข้า list ส่วนตัว (บันทึกแยกตามที่ผู้ใช้สั่ง) — ไม่เสนอซ้ำอีก"""
    state = mf.load_kw_state()
    state.setdefault("private", {})[gid] = {
        "name": group.get("name", ""), "url": group.get("url", ""),
        "members": group.get("members", 0), "via": via,
        "at": datetime.now().strftime("%Y-%m-%d %H:%M")}
    mf.save_kw_state(state)
    log(f"PRIVATE กลุ่ม ({via}): {group.get('name')}")


def _kw_fill_queue(keyword: str) -> tuple[int, int, int]:
    """สแกนหน้า search เพิ่ม เติมกลุ่มใหม่เข้าคิว — คืน (เจอทั้งหมด, เข้าคิว, ส่วนตัว)

    กลุ่มที่การ์ด search บอกชัดว่า "ส่วนตัว" ไม่เข้าคิว — จดแยกเข้า list ส่วนตัวเลย
    ไม่ต้องเสียเวลาเปิดหน้ากลุ่ม (กลุ่มที่ป้ายไม่ชัดค่อยไปตรวจซ้ำตอนเปิดถ่ายรูป)
    """
    state = mf.load_kw_state()
    exclude = set(state["rejected"]) | set(state["sent"]) \
        | set(state.get("private", {})) | {g.get("gid", "") for g in state["queue"]}
    depth = int(state.get("depth", 0))
    found = mf.search_groups(keyword, exclude, depth=depth,
                             rounds=KW_SEARCH_ROUNDS, log=log)
    state = mf.load_kw_state()          # โหลดใหม่หลังงานช้า (ผู้ใช้อาจแก้ระหว่างรอ)
    state["depth"] = int(state.get("depth", 0)) + KW_SEARCH_ROUNDS
    low, high = _kw_range(state)
    queued = {g.get("gid", "") for g in state["queue"]}
    fresh, private_count = [], 0
    for g in found:
        if not _kw_in_range(g["members"], low, high) or g["gid"] in queued \
                or g["gid"] in state["rejected"] or g["gid"] in state["sent"] \
                or g["gid"] in state.get("private", {}):
            continue
        if g.get("private") is True:
            state.setdefault("private", {})[g["gid"]] = {
                "name": g.get("name", ""), "url": g.get("url", ""),
                "members": g.get("members", 0), "via": "search",
                "at": datetime.now().strftime("%Y-%m-%d %H:%M")}
            private_count += 1
            log(f"PRIVATE กลุ่ม (search): {g.get('name')}")
            continue
        fresh.append(g)
    state["queue"].extend(fresh)
    mf.save_kw_state(state)
    return len(found), len(fresh), private_count


# เกณฑ์ตัดสินอัตโนมัติหลังเจาะ 1,000 โพสต์ล่าสุด (สรุปจากข้อมูลจริง 14 ส.ค.):
#   มีชีวิต = โพสต์ engagement เกิน 100 อย่างน้อย KW_ALIVE_OVER โพสต์
#             **และ** engagement เฉลี่ย ≥ KW_ALIVE_AVG
#   ตาย    = ไม่ผ่านทั้งสองข้อ · ก้ำกึ่ง = ผ่านข้อเดียว → ส่งการ์ดให้ผู้ใช้ตัดสิน
KW_ALIVE_OVER = 5
KW_ALIVE_AVG = 8.0

# เจาะซ้ำกลุ่มที่เคยถูกตัดครั้งละกี่กลุ่ม ก่อนกลับไปทำคำค้นถัดไป
# (สลับกันไปเรื่อยๆ — ทั้งสองงานคืบหน้าพร้อมกัน ไม่มีงานไหนต้องรออีกงานจบ)
RECHECK_BATCH = 20


def _kw_judge(result: dict) -> str:
    """ตัดสินผลเจาะลึกหนึ่งกลุ่ม — คืน alive / dead / borderline"""
    pass_over = result.get("over", 0) >= KW_ALIVE_OVER
    pass_avg = result.get("avg", 0) >= KW_ALIVE_AVG
    if pass_over and pass_avg:
        return "alive"
    if pass_over or pass_avg:
        return "borderline"
    return "dead"


# ขุด search แล้วไม่เจอของใหม่กี่รอบติดถึงเลิก — ต้อง >1 เพราะพอกรองเป็น "ช่วง"
# สมาชิก ผลค้นบางช่วงความลึกอาจไม่มีกลุ่มในช่วงเลยสักใบ แต่ลึกกว่านั้นยังมีอยู่
# (แบนด์ >100k เดิมใช้ 1 รอบก็พอ เพราะกลุ่มใหญ่เกาะอยู่หน้าต้นๆ)
KW_DRY_ROUNDS = 2


def _kw_grow_reserve(token: str, chat_id: str) -> None:
    """ขุดหน้า search รวบรวมกลุ่ม "ในช่วงสมาชิกที่กำหนด" ให้หมด — ถือ _busy อยู่แล้ว

    งานเบา (เก็บแค่ชื่อ/ลิงก์/สมาชิก) ขุดซ้ำจน search ไม่มีของใหม่ (exhausted)
    แล้วทุกกลุ่มในคิวจะถูกไล่ /test อัตโนมัติทีละกลุ่ม
    """
    state = mf.load_kw_state()
    keyword = state.get("keyword", "")
    if not keyword:
        return
    low, high = _kw_range(state)
    total, fresh, private_count = _kw_fill_queue(keyword)
    state = mf.load_kw_state()
    after = len(state.get("queue") or [])
    label = mf.band_label(low, high)
    log(f"รวบรวมกลุ่ม [{label}]: เจอ {total} · เข้าคิว {fresh} · "
        f"ส่วนตัว {private_count} · รอ test รวม {after}")
    if private_count:
        run = state.setdefault("run", {})
        run["private"] = int(run.get("private", 0)) + private_count
        mf.save_kw_state(state)
    state = mf.load_kw_state()
    dry = int(state.get("dry", 0)) + 1 if fresh == 0 else 0
    state["dry"] = dry
    if dry >= KW_DRY_ROUNDS:
        state["exhausted"] = True
        mf.save_kw_state(state)
        hours = after * 14 / 60
        span = (f"ในช่วง {low:,}–{high:,} คน" if high
                else f"เกิน {low:,} คน")
        say(token, chat_id,
            f'📋 ค้น "{html.escape(keyword)}" [{label}] ครบแล้ว — '
            f"พบกลุ่มสมาชิก{span} "
            f"รอเจาะ {after} กลุ่ม (~{hours:.1f} ชม. · ~14 นาที/กลุ่ม)\n"
            "จะไล่ /test อัตโนมัติ: มีชีวิต→whitelist · ตาย→rejected · "
            "ก้ำกึ่ง→ส่งการ์ดให้กดตัดสิน แล้วสรุปตอนจบ")
    else:
        mf.save_kw_state(state)


def _kw_run_next_test(token: str, chat_id: str) -> None:
    """หยิบกลุ่มแรกจากคิวมาเจาะลึกแล้ว **ตัดสินอัตโนมัติ** — ถือ _busy อยู่แล้ว

    มีชีวิต → whitelist · ตาย → rejected · ก้ำกึ่ง → การ์ด (กราฟ+ปุ่ม) ให้ผู้ใช้กด
    ก่อนเจาะเปิดดูหน้ากลุ่มก่อน: กันกลุ่มส่วนตัว + เอาชื่อจริงจาก title
    """
    state = mf.load_kw_state()
    low, high = _kw_range(state)
    group = None
    while state.get("queue"):
        cand = state["queue"].pop(0)
        cgid = cand.get("gid", "")
        if not cgid or cgid in state.get("whitelist", {}) \
                or cgid in state["rejected"] or cgid in state.get("private", {}):
            continue
        # กันของค้างจากรอบก่อนที่ช่วงสมาชิกไม่ตรงกับรอบนี้ (เช่นสลับแบนด์กลางคัน)
        if not _kw_in_range(cand.get("members", 0), low, high):
            continue
        group = cand
        break
    # คิวปกติหมดแล้วค่อยหยิบกลุ่มเจาะซ้ำ — ไม่ให้แย่งคิวงานหลัก แต่ก็ไม่หายไป
    # (ไม่กรองด้วยช่วงสมาชิก เพราะกลุ่มพวกนี้มาจากหลายคำค้น/หลายช่วง)
    while group is None and state.get("recheck_queue"):
        cand = state["recheck_queue"].pop(0)
        cgid = cand.get("gid", "")
        if not cgid or cgid in state.get("whitelist", {}) \
                or cgid in state.get("private", {}):
            continue
        group = cand
        break
    if group is None:
        mf.save_kw_state(state)
        return
    gid = group["gid"]
    keyword = state.get("keyword", "")
    band = mf.band_label(low, high)
    state["testing"] = gid
    mf.save_kw_state(state)

    def finish(counter: str | None = None) -> None:
        st = mf.load_kw_state()
        st["testing"] = None
        st["sent"][gid] = {"name": group.get("name", ""),
                           "url": group.get("url", ""),
                           "members": group.get("members", 0)}
        run = st.setdefault("run", {})
        run["tested"] = int(run.get("tested", 0)) + 1
        if counter:
            if counter == "failed":
                run.setdefault("failed", []).append(group.get("name") or gid)
            else:
                run[counter] = int(run.get(counter, 0)) + 1
        mf.save_kw_state(st)

    def requeue(why: str) -> None:
        """คืนกลุ่มกลับหัวคิว — ใช้กับความล้มเหลว "เชิงสภาพแวดล้อม" เท่านั้น

        ⚠️ ห้ามใช้ finish() กับกรณีนี้เด็ดขาด: finish จด gid ลง sent = "เคยเสนอ
        แล้ว" ซึ่งทำให้กลุ่มนั้น **ไม่ถูกหยิบมาเจาะอีกตลอดกาล** ทั้งที่ยังไม่เคย
        เจาะเลย แค่บังเอิญเบราว์เซอร์ไม่ว่างวินาทีนั้น (พอมีบอทเก็บโพสต์มาแย่ง
        เบราว์เซอร์ด้วย จะเผากลุ่มทิ้งวันละหลายสิบกลุ่ม)
        """
        st = mf.load_kw_state()
        st["testing"] = None
        if not any(q.get("gid") == gid for q in st.get("queue") or []):
            st.setdefault("queue", []).insert(0, group)
        mf.save_kw_state(st)
        log(f"คืนกลุ่มเข้าคิว ({why}): {group.get('name') or gid}")

    try:
        # เปิดหน้ากลุ่มก่อนเจาะ — ตรวจส่วนตัว + ชื่อจริง (ชื่อจาก search เพี้ยนได้)
        try:
            info = mf.inspect_group(group["url"], gid, log=log)
        except BUSY_ERRORS:
            requeue("เบราว์เซอร์ไม่ว่างตอนเปิดตรวจกลุ่ม")
            return
        except Exception:
            info = {}
            log(f"เปิดตรวจกลุ่มก่อนเจาะไม่สำเร็จ:\n{traceback.format_exc()}")
        if info.get("shot"):
            _kw_del_shot({"shot": info["shot"]})     # flow ใหม่ไม่ใช้รูปหน้ากลุ่ม
        page_name = (info.get("page_name") or "").strip()
        if page_name and page_name.lower() not in ("facebook", "เยี่ยมชม", "visit"):
            group["name"] = page_name
        gname = group.get("name") or gid
        if info.get("private") is True:
            _kw_mark_private(gid, group, via="เปิดหน้ากลุ่ม")
            say(token, chat_id,
                f"🔒 {html.escape(gname[:50])} เป็นกลุ่มส่วนตัว — บันทึกแยก ข้ามไป")
            finish("private")
            return

        remain = len(mf.load_kw_state().get("queue") or [])
        log(f"เจาะกลุ่ม: {gname} (เหลือคิว {remain})")
        results = mf.deep_scan_groups([{"url": group["url"], "name": gname}],
                                      TEST_TARGET, log=log)
        r = results[0] if results else {}
        if r.get("error") or not r.get("count"):
            reason = r.get("error") or "อ่านโพสต์ไม่ได้"
            say(token, chat_id,
                f"⚠️ {html.escape(gname[:50])}: {html.escape(str(reason)[:100])} "
                "— ข้าม (ไม่นับเป็นตาย)")
            log(f"เจาะไม่ได้: {gname} — {reason}")
            finish("failed")
            return

        verdict = _kw_judge(r)
        entry = {"name": gname, "url": group.get("url", ""),
                 "members": group.get("members", 0), "keyword": keyword,
                 "band": band,
                 "over": r.get("over", 0), "avg": r.get("avg", 0),
                 "at": datetime.now().strftime("%Y-%m-%d %H:%M")}
        stats = (f"เกิน100={r.get('over', 0)} · เฉลี่ย={r.get('avg', 0)} "
                 f"(อ่าน {r.get('count', 0):,} โพสต์)")
        # กลุ่มที่เอากลับมาเจาะซ้ำ — โชว์ว่าตัวนับใหม่ทำให้ผลเปลี่ยนไปแค่ไหน
        old = group.get("recheck")
        if old:
            entry["recheck_from"] = old
            stats += (f"\n(ครั้งก่อนนับได้ เกิน100={old.get('over')} · "
                      f"เฉลี่ย={old.get('avg')})")
        if verdict == "alive":
            st = mf.load_kw_state()
            st.setdefault("whitelist", {})[gid] = entry
            mf.save_kw_state(st)
            revived = "♻️ <b>กู้คืนได้!</b> " if group.get("recheck") else ""
            say(token, chat_id,
                f"{revived}✅ <b>{html.escape(gname[:50])}</b> มีชีวิต ({stats}) → whitelist")
            log(f"ALIVE: {gname} ({stats})")
            finish("alive")
        elif verdict == "dead":
            st = mf.load_kw_state()
            st["rejected"][gid] = {**entry, "verdict": "dead"}
            mf.save_kw_state(st)
            say(token, chat_id,
                f"❌ {html.escape(gname[:50])} ตายแล้ว ({stats}) → rejected")
            log(f"DEAD: {gname} ({stats})")
            finish("dead")
        else:
            # ก้ำกึ่ง — ส่งกราฟ+ตัวเลข พร้อมปุ่มให้ผู้ใช้ตัดสิน
            min_eng = int(mf.load_config().get("min_likes", 100))
            chart = mf.render_test_chart(results, min_eng, log=log)
            caption = "\n".join([
                f"⚖️ <b>ก้ำกึ่ง: {html.escape(gname[:50])}</b>",
                f"👥 ~{group.get('members', 0):,} คน · {stats}",
                group.get("url", ""),
                "Approve = เข้า whitelist · Reject = ตัดทิ้ง",
            ])
            keyboard = kw_buttons(gid)
            message_id = None
            if chart and chart.is_file():
                try:
                    message_id = telegram_bot.send_photo(
                        token, chat_id, chart, caption=caption, keyboard=keyboard)
                    group["is_photo"] = True
                except telegram_bot.TelegramError as error:
                    log(f"ส่งการ์ดก้ำกึ่ง (รูป) ไม่ได้: {error}")
            if message_id is None:
                try:
                    message_id = telegram_bot.send_message(
                        token, chat_id, caption, keyboard)
                    group["is_photo"] = False
                except telegram_bot.TelegramError as error:
                    log(f"ส่งการ์ดก้ำกึ่งไม่ได้: {error}")
            st = mf.load_kw_state()
            st.setdefault("pending", {})[gid] = {
                **entry, "gid": gid, "message_id": message_id,
                "is_photo": group.get("is_photo", False), "caption": caption}
            mf.save_kw_state(st)
            log(f"BORDERLINE: {gname} ({stats}) รอผู้ใช้ตัดสิน")
            finish("borderline")
    # ⚠️ ต้องดัก BUSY_ERRORS **ก่อน** สองตัวล่าง เพราะ BotBusy/BrowserBusy สืบทอด
    # RuntimeError ถ้าไปตกที่ except Exception จะถูก finish("failed") = เผากลุ่มทิ้ง
    except BUSY_ERRORS:
        requeue("เบราว์เซอร์ไม่ว่างตอนเจาะ")
    except (mf.MassFinderError, FarmError) as error:
        say(token, chat_id, f"❌ เจาะ {html.escape(str(group.get('name', gid))[:40])}: {error}")
        log(f"เจาะล้ม: {error}")
        finish("failed")
    except Exception:
        say(token, chat_id,
            f"❌ เจาะกลุ่ม {html.escape(str(group.get('name', gid))[:40])} ล้มกลางทาง — ดู log")
        log(f"เจาะล้มกลางทาง:\n{traceback.format_exc()}")
        finish("failed")


def _kw_send_summary(token: str, chat_id: str) -> None:
    """สรุปผลท้าย keyword — ส่งครั้งเดียวเมื่อไล่ test ครบทุกกลุ่ม"""
    state = mf.load_kw_state()
    keyword = state.get("keyword", "")
    low, high = _kw_range(state)
    band = mf.band_label(low, high)
    run = state.get("run") or {}
    wl = [e for e in (state.get("whitelist") or {}).values()
          if e.get("keyword") == keyword
          and (e.get("band") or mf.band_label(mf.KW_MIN_MEMBERS, 0)) == band]
    wl.sort(key=lambda e: -(e.get("avg") or 0))
    pending_n = len(state.get("pending") or {})
    span = f"{low:,}–{high:,} คน" if high else f"เกิน {low:,} คน"
    lines = [f'🏁 <b>สรุป /keyword "{html.escape(keyword)}" [{band}]</b>',
             f"ช่วงสมาชิก {span} · เจาะทั้งหมด {run.get('tested', 0)} กลุ่ม", ""]
    lines.append(f"✅ มีชีวิต → whitelist: {run.get('alive', 0)} กลุ่ม")
    for e in wl[:15]:
        lines.append(f"  • {html.escape(e.get('name', '')[:40])} "
                     f"(เฉลี่ย {e.get('avg')})")
    lines.append(f"❌ ตาย → rejected: {run.get('dead', 0)} กลุ่ม")
    if pending_n:
        lines.append(f"⚖️ ก้ำกึ่งรอคุณกดตัดสิน: {pending_n} ใบ (เลื่อนดูการ์ดด้านบน)")
    if run.get("private"):
        lines.append(f"🔒 กลุ่มส่วนตัวข้าม: {run.get('private', 0)} (ดู /private)")
    if run.get("failed"):
        lines.append(f"⚠️ อ่านไม่ได้ {len(run['failed'])} กลุ่ม: "
                     + ", ".join(str(n)[:25] for n in run["failed"][:5]))
    lines += ["", "ดูกลุ่มที่ผ่านทั้งหมด: /whitelists · แยกตามคำค้น: /whitelist"]
    say(token, chat_id, "\n".join(lines))
    state = mf.load_kw_state()
    state["summary_sent"] = True
    done_key = mf.job_key(keyword, low, high)
    done_keys = set()
    for item in (state.get("keywords_done") or []):
        job = mf.as_job(item)
        done_keys.add(mf.job_key(job["kw"], job["lo"], job["hi"]))
    if keyword and done_key not in done_keys:
        state.setdefault("keywords_done", []).append(
            {"kw": keyword, "lo": low, "hi": high})
    # มีกลุ่มรอเจาะซ้ำอยู่ → แทรกทำเป็นชุดก่อนขึ้นคำค้นถัดไป
    # (ไม่ปล่อยให้รอจนคำค้นหมดทั้ง 45 งาน เพราะกลุ่มพวกนี้เป็นกลุ่มใหญ่ที่รู้ค่าแล้ว
    #  แค่ถูกตัดด้วยยอดที่นับผิด — ยิ่งกู้เร็วยิ่งได้ใช้เร็ว)
    if state.get("recheck_queue"):
        state["recheck_left"] = RECHECK_BATCH
        mf.save_kw_state(state)
        say(token, chat_id,
            f"♻️ แทรกเจาะซ้ำกลุ่มที่เคยถูกตัด {RECHECK_BATCH} กลุ่ม "
            f"(เหลือในคิวเจาะซ้ำ {len(state['recheck_queue'])} กลุ่ม) "
            "แล้วค่อยไปคำค้นถัดไป")
        log(f"แทรกเจาะซ้ำ {RECHECK_BATCH} กลุ่ม")
    else:
        mf.save_kw_state(state)
        _kw_next_keyword(token, chat_id)
    log(f'สรุป keyword "{keyword}" [{band}] ส่งแล้ว')


def _kw_next_keyword(token: str, chat_id: str) -> None:
    """เริ่มงานถัดไปในคิวคำค้น — เรียกหลังสรุปจบ หรือหลังชุดเจาะซ้ำจบ"""
    state = mf.load_kw_state()
    kw_queue = state.get("keyword_queue") or []
    if not kw_queue:
        mf.save_kw_state(state)
        return
    nxt = mf.as_job(kw_queue.pop(0))
    state["keyword_queue"] = kw_queue
    _kw_activate(state, nxt["kw"], nxt["lo"], nxt["hi"])
    mf.save_kw_state(state)
    nxt_label = mf.band_label(nxt["lo"], nxt["hi"])
    say(token, chat_id,
        f'▶️ เริ่มงานถัดไปในคิว: "{html.escape(nxt["kw"])}" [{nxt_label}]'
        + (f" (เหลือคิวอีก {len(kw_queue)} งาน)" if kw_queue else " (งานสุดท้ายในคิว)"))
    log(f'เริ่มงานถัดไปจากคิว: "{nxt["kw"]}" [{nxt_label}]')


def _kw_worker_loop(token: str, chat_id: str) -> None:
    """เดมอนของ /keyword (flow อัตโนมัติเต็ม):

    1. ขุดหน้า search จนหมด (exhausted) — รวบรวมทุกกลุ่ม >100k เข้าคิว
    2. ไล่เจาะ /test ทีละกลุ่ม แล้วตัดสินเอง (มีชีวิต/ตาย/ก้ำกึ่ง)
    3. ครบทุกกลุ่ม → ส่งสรุปเข้า Telegram ครั้งเดียว
    อ่านทุกอย่างจาก state file — รีสตาร์ตแล้วเดินต่อเองได้
    """
    log("เดมอน /keyword (โหมดอัตโนมัติ) ทำงานแล้ว")
    while True:
        try:
            # Bot10 สงวนให้ตัวเก็บคอมเมนต์เท่านั้น ถ้ายังไม่ได้ผูกโปรไฟล์อื่น
            # ให้พักคิวเดิมไว้เฉย ๆ ห้ามหยิบออก/ทำ failed และห้ามเปิด Chrome.
            if not bool(mf.load_config().get("browser_enabled", True)):
                time.sleep(15)
                continue
            state = mf.load_kw_state()
            if not state.get("keyword"):
                time.sleep(5)
                continue
            if not state.get("exhausted"):
                with _busy:
                    _kw_grow_reserve(token, chat_id)     # 1. รวบรวมให้หมดก่อน
            elif state.get("queue"):
                with _busy:
                    _kw_run_next_test(token, chat_id)    # 2. เจาะ+ตัดสินทีละกลุ่ม
            elif not state.get("summary_sent"):
                _kw_send_summary(token, chat_id)         # 3. สรุปครั้งเดียว
            elif state.get("recheck_queue") and int(state.get("recheck_left", 0)) > 0:
                # 4. แทรกเจาะซ้ำกลุ่มที่เคยถูกตัด เป็นชุดๆ ระหว่างคำค้น
                with _busy:
                    _kw_run_next_test(token, chat_id)
                st = mf.load_kw_state()
                st["recheck_left"] = max(0, int(st.get("recheck_left", 0)) - 1)
                mf.save_kw_state(st)
                if st["recheck_left"] == 0:
                    _kw_next_keyword(token, chat_id)
            else:
                time.sleep(4)
                continue
            time.sleep(2)      # กันลูปถี่เกินตอนงานล้มเหลวซ้ำๆ
        except Exception:
            log(f"เดมอน /keyword พังกลางทาง:\n{traceback.format_exc()}")
            time.sleep(15)


def _kw_activate(state: dict, keyword: str,
                 low: int | None = None, high: int = 0) -> None:
    """ตั้ง "งาน" ใหม่เป็นตัวทำงาน — รีเซ็ตคิว/ความลึก/ตัวนับของรอบ

    งาน = คำค้น + ช่วงสมาชิก (low, high] · high = 0 คือไม่จำกัดขอบบน
    """
    low = int(mf.KW_MIN_MEMBERS if low is None else low)
    state["keyword"] = keyword
    state["min_members"] = low
    state["max_members"] = int(high or 0)
    state["queue"] = []
    state["depth"] = 0
    state["dry"] = 0
    state["exhausted"] = False
    state["summary_sent"] = False
    state["run"] = {"keyword": keyword, "band": mf.band_label(low, high),
                    "tested": 0, "alive": 0,
                    "dead": 0, "borderline": 0, "private": 0, "failed": []}


def _kw_current_job(state: dict) -> dict:
    """งานที่กำลังทำอยู่ในรูป {kw, lo, hi}"""
    low, high = _kw_range(state)
    return {"kw": state.get("keyword", ""), "lo": low, "hi": high}


def _kw_known_keywords(state: dict) -> set:
    """งานที่ "เคยพิมพ์ไปแล้ว" — กำลังทำ + รอคิว + ทำจบแล้ว (คีย์ = คำ+ช่วง)

    คำเดิมแต่คนละช่วงสมาชิกถือเป็นคนละงาน จึงไม่ติดเตือนซ้ำ
    """
    known = set()
    for item in list(state.get("keywords_done") or []) \
            + list(state.get("keyword_queue") or []):
        job = mf.as_job(item)
        known.add(mf.job_key(job["kw"], job["lo"], job["hi"]))
    if state.get("keyword"):
        job = _kw_current_job(state)
        known.add(mf.job_key(job["kw"], job["lo"], job["hi"]))
    return known


# ช่วงสมาชิกที่พิมพ์ต่อท้ายคำค้นได้ — "บ้าน 10k-50k" · "บ้าน 50000-100000"
_RANGE_RE = re.compile(r"^(?P<kw>.*?)\s+(?P<lo>[\d.,]+)\s*(?P<lom>[kKmM])?\s*"
                       r"[-–]\s*(?P<hi>[\d.,]+)\s*(?P<him>[kKmM])?$")


def _parse_amount(number: str, suffix: str | None) -> int:
    value = float((number or "0").replace(",", ""))
    return int(round(value * {"k": 1e3, "m": 1e6}.get((suffix or "").lower(), 1)))


def _kw_parse_word(word: str) -> tuple[str, int, int]:
    """แยกคำค้น + ช่วงสมาชิกออกจากข้อความที่ผู้ใช้พิมพ์

    "บ้าน" → (บ้าน, 100000, 0) ตามเดิม · "บ้าน 10k-50k" → (บ้าน, 10000, 50000)
    """
    match = _RANGE_RE.match(word)
    if not match:
        return word, mf.KW_MIN_MEMBERS, 0
    low = _parse_amount(match.group("lo"), match.group("lom"))
    high = _parse_amount(match.group("hi"), match.group("him"))
    if low > high:
        low, high = high, low
    keyword = match.group("kw").strip()
    if not keyword:                       # พิมพ์แต่ตัวเลข — ไม่ใช่ช่วงสมาชิก
        return word, mf.KW_MIN_MEMBERS, 0
    return keyword, low, high


def _kw_enqueue_job(keyword: str, low: int, high: int,
                    force: bool = False) -> str:
    """ใส่งาน (คำค้น+ช่วง) เข้าระบบ — คืน "started" / "queued" / "dupe"

    ที่เดียวที่ตัดสินว่างานเริ่มเลยหรือต่อคิว — /keyword และ /bands ใช้ร่วมกัน
    """
    state = mf.load_kw_state()
    key = mf.job_key(keyword, low, high)
    if not force and key in _kw_known_keywords(state):
        return "dupe"
    if force:
        # บังคับรันซ้ำ — เอาออกจากประวัติก่อน จะได้ไม่ติดเตือนซ้ำรอบหน้า
        kept = []
        for item in (state.get("keywords_done") or []):
            job = mf.as_job(item)
            if mf.job_key(job["kw"], job["lo"], job["hi"]) != key:
                kept.append(item)
        state["keywords_done"] = kept
    active = state.get("keyword")
    busy = active and not (state.get("summary_sent") and not state.get("queue"))
    if busy:
        state.setdefault("keyword_queue", []).append(
            {"kw": keyword, "lo": low, "hi": high})
        result = "queued"
    else:
        _kw_activate(state, keyword, low, high)
        result = "started"
    mf.save_kw_state(state)
    log(f'งาน "{keyword}" [{mf.band_label(low, high)}] → '
        + ("เริ่มเลย" if result == "started" else "ต่อคิว"))
    return result


def _job_text(keyword: str, low: int, high: int) -> str:
    """ชื่องานสำหรับโชว์ใน Telegram (escape แล้ว)"""
    return f'{html.escape(keyword)} [{mf.band_label(low, high)}]'


def do_keyword(token: str, chat_id: str, argument: str) -> None:
    state = mf.load_kw_state()
    if not argument:
        testing = state.get("testing")
        run = state.get("run") or {}
        keyword = state.get("keyword") or "-"
        low, high = _kw_range(state)
        kw_q = [mf.as_job(i) for i in (state.get("keyword_queue") or [])]
        band = mf.band_label(low, high)
        wl_kw = sum(1 for e in (state.get("whitelist") or {}).values()
                    if e.get("keyword") == state.get("keyword"))
        say(token, chat_id, "\n".join([
            "ใช้แบบนี้: <code>/keyword บ้าน, รีวิว, ของกิน</code> (หลายคำคั่นด้วย ,)",
            "จำกัดช่วงสมาชิก: <code>/keyword บ้าน 10k-50k</code> "
            "· กวาดทุกคำเดิมทุกช่วง: /bands",
            f"งานปัจจุบัน: {html.escape(keyword)} [{band}]"
            + ("" if state.get("exhausted") else " (กำลังรวบรวมกลุ่ม)"),
            "คิวถัดไป: " + (" → ".join(
                f'{html.escape(j["kw"])}[{mf.band_label(j["lo"], j["hi"])}]'
                for j in kw_q[:12]) + (f" …อีก {len(kw_q) - 12}" if len(kw_q) > 12 else "")
                if kw_q else "-"),
            f"คิวรอเจาะ {len(state['queue'])} กลุ่ม"
            + (" · กำลังเจาะอยู่ 1 กลุ่ม" if testing else ""),
            f"เจาะแล้ว {run.get('tested', 0)}: ✅ {run.get('alive', 0)} · "
            f"❌ {run.get('dead', 0)} · ⚖️ {run.get('borderline', 0)}",
            f"การ์ดก้ำกึ่งรอกด {len(state.get('pending') or {})} ใบ",
            f"whitelist คำนี้ {wl_kw} กลุ่ม (ดู /whitelists) · "
            f"ส่วนตัว {len(state.get('private', {}))}",
        ]))
        return

    # รับหลายคำในครั้งเดียว — คั่นด้วย , หรือขึ้นบรรทัดใหม่ · ลงท้าย "!" = บังคับรันซ้ำ
    words = [w.strip() for chunk in argument.splitlines()
             for w in chunk.split(",") if w.strip()]
    started, queued, dupes = [], [], []
    for word in words:
        force = word.endswith("!")
        raw = word.rstrip("!").strip()
        if not raw:
            continue
        keyword, low, high = _kw_parse_word(raw)
        result = _kw_enqueue_job(keyword, low, high, force)
        {"started": started, "queued": queued,
         "dupe": dupes}[result].append(_job_text(keyword, low, high))

    lines = []
    if started:
        lines.append(f'🔎 เริ่มงาน "{started[-1]}" — รวบรวมกลุ่มในช่วงที่กำหนด '
                     "แล้วไล่เจาะอัตโนมัติ "
                     "(✅→whitelist · ❌→ตัดทิ้ง · ⚖️→ถามคุณ · สรุปตอนจบ)")
    if queued:
        state = mf.load_kw_state()
        lines.append("📥 ต่อคิว: " + " → ".join(queued)
                     + f" (รวมคิว {len(state.get('keyword_queue') or [])} งาน "
                     "— งานก่อนหน้าสรุปจบแล้วเริ่มต่อเอง)")
    if dupes:
        lines.append("⚠️ ซ้ำ ไม่เพิ่ม: " + " · ".join(dupes)
                     + " — เคยพิมพ์/ทำไปแล้ว (บังคับรันใหม่: พิมพ์ <code>/keyword คำ!</code>)")
    if lines:
        say(token, chat_id, "\n".join(lines))
    # เดมอนเบื้องหลังเห็นคำค้นแล้วเริ่มรวบรวมเองใน ~5 วิ


def do_recheck(token: str, chat_id: str, argument: str) -> None:
    """/recheck [จำนวน] — เอากลุ่มที่เคยถูกตัดว่า "ตาย" กลับมาเจาะใหม่

    ทำไมต้องมี: ตัวนับ engagement เดิมจับคู่ยอดผิด นับไลค์ต่ำกว่าจริงมาก
    (พิสูจน์ 18 ส.ค.: โพสต์หนึ่งได้ไลค์ 3 ทั้งที่ Facebook แสดง "2.3 พัน คน")
    กลุ่มที่ถูกตัดด้วยยอดผิดจึงอาจเป็นกลุ่มดีที่เสียไปฟรีๆ

    เอาเฉพาะที่ระบบตัดสินเอง (verdict='dead') — ไม่แตะกลุ่มที่ผู้ใช้ปัดเอง
    หรือกลุ่มที่กด Removed ไปแล้ว (เจตนาของคนต้องชนะกฎเสมอ)
    """
    state = mf.load_kw_state()
    rejected = state.get("rejected") or {}
    queued = {g.get("gid") for g in state.get("queue") or []}
    dead = [(gid, info) for gid, info in rejected.items()
            if info.get("verdict") == "dead"
            and gid not in queued
            and gid not in (state.get("whitelist") or {})
            and "(removed)" not in str(info.get("name", ""))]
    dead.sort(key=lambda item: -(item[1].get("avg") or 0))   # ใกล้ผ่านก่อน

    if not dead:
        say(token, chat_id,
            "ไม่มีกลุ่มที่ระบบตัดว่าตายให้เจาะซ้ำ "
            f"(ในรายการตัดทิ้ง {len(rejected)} กลุ่ม เป็นการปัดด้วยมือทั้งหมด)")
        return

    arg = argument.strip().lower()
    if arg in ("all", "ทั้งหมด", "หมด"):
        want = len(dead)
    else:
        try:
            want = int(arg) if arg else 30
        except ValueError:
            want = 30
    want = max(1, min(want, len(dead)))
    batch = dead[:want]

    state = mf.load_kw_state()
    already = {g.get("gid") for g in state.get("recheck_queue") or []}
    for gid, info in batch:
        if gid in already:
            continue
        state["rejected"].pop(gid, None)
        # ลงคิวแยก — คิวปกติถูกล้างทุกครั้งที่เปลี่ยนคำค้น กลุ่มพวกนี้จะหายหมด
        state.setdefault("recheck_queue", []).append({
            "gid": gid,
            "name": info.get("name", ""),
            "url": info.get("url") or f"https://www.facebook.com/groups/{gid}/",
            "members": info.get("members", 0),
            # จำผลเดิมไว้เทียบตอนได้ผลใหม่ — จะได้รู้ว่าตัวนับใหม่เปลี่ยนอะไร
            "recheck": {"over": info.get("over"), "avg": info.get("avg"),
                        "keyword": info.get("keyword", "")},
        })
        # ต้องเอาออกจาก sent ด้วย ไม่งั้นตัวคัดจะข้ามกลุ่มนี้ทันที
        state.get("sent", {}).pop(gid, None)
    state["summary_sent"] = False
    mf.save_kw_state(state)

    hours = len(batch) * 13 / 60
    log(f"/recheck: คืน {len(batch)} กลุ่มเข้าคิวเจาะใหม่")
    say(token, chat_id, "\n".join([
        f"♻️ <b>เจาะซ้ำ {len(batch)} กลุ่ม</b> ที่เคยถูกตัดว่าตาย",
        f"เหลือที่ยังไม่ได้เจาะซ้ำอีก {len(dead) - len(batch)} กลุ่ม "
        f"(สั่งเพิ่มด้วย <code>/recheck 50</code>)",
        f"⏱ ประมาณ {hours:.1f} ชม. · คิวรวมตอนนี้ {len(state['queue'])} กลุ่ม",
        "",
        "เหตุผล: ตัวนับเดิมอ่านยอดไลค์ต่ำกว่าจริง กลุ่มพวกนี้อาจถูกตัดทั้งที่ยังดี "
        "— ตัวนับใหม่ตรวจกับหน้าจอ Facebook แล้วว่าตรง",
    ]))


def do_bands(token: str, chat_id: str, argument: str) -> None:
    """/bands — กวาดช่วงสมาชิกที่เหลือ (10k-50k, 50k-100k) ของ "ทุกคำค้นเดิม"

    ผู้ใช้สั่ง 18 ส.ค. 2569: หาต่อด้วย keyword เดิม แต่เอากลุ่มขนาดกลาง
    ไม่ระบุ argument = ใช้ทุกคำที่เคยทำจบแล้ว · ระบุได้ว่าเอาคำไหนบ้าง
    """
    state = mf.load_kw_state()
    if argument.strip():
        words = [w.strip() for chunk in argument.splitlines()
                 for w in chunk.split(",") if w.strip()]
    else:
        # คำค้นเดิมทั้งหมด เรียงตามลำดับที่เคยทำ — ไม่ซ้ำคำ
        words, seen = [], set()
        for item in (state.get("keywords_done") or []):
            kw = mf.as_job(item)["kw"]
            if kw and kw not in seen:
                seen.add(kw)
                words.append(kw)
    if not words:
        say(token, chat_id,
            "ยังไม่มีคำค้นเดิมให้กวาดต่อ — เริ่มด้วย <code>/keyword คำค้น</code>")
        return

    started, queued, dupes = [], [], []
    for keyword in words:
        for low, high in mf.KW_BANDS:
            result = _kw_enqueue_job(keyword, low, high)
            {"started": started, "queued": queued,
             "dupe": dupes}[result].append(_job_text(keyword, low, high))

    state = mf.load_kw_state()
    bands_text = " · ".join(f"{low:,}–{high:,}" for low, high in mf.KW_BANDS)
    lines = [f"🎯 <b>กวาดช่วงสมาชิกเพิ่ม</b> ({bands_text} คน)",
             f"คำค้น {len(words)} คำ × {len(mf.KW_BANDS)} ช่วง = "
             f"{len(words) * len(mf.KW_BANDS)} งาน"]
    if started:
        lines.append(f"▶️ เริ่มเลย: {started[0]}")
    if queued:
        lines.append(f"📥 ต่อคิวเพิ่ม {len(queued)} งาน "
                     f"(คิวรวม {len(state.get('keyword_queue') or [])} งาน)")
    if dupes:
        lines.append(f"⚠️ ข้ามที่เคยทำแล้ว {len(dupes)} งาน")
    lines.append("ดูสถานะ: /keyword · ผลที่ผ่าน: /whitelists")
    say(token, chat_id, "\n".join(lines))
    log(f"/bands: {len(words)} คำ → เริ่ม {len(started)} · ต่อคิว {len(queued)} "
        f"· ซ้ำ {len(dupes)}")


def do_kw_remove(token: str, chat_id: str, decision: dict) -> None:
    """Removed: ให้ Bot10 ออกจากกลุ่ม + ลบออกจาก list + ใส่ rejected (removed)"""
    def work() -> None:
        gid = decision.get("gid", "")
        name = decision.get("name", gid)
        url = decision.get("url", "")
        note = ""
        with _busy:
            say(token, chat_id, f"🚪 กำลังให้ Bot10 ออกจากกลุ่ม {html.escape(name[:40])}…")
            try:
                result = mf.leave_group(url, log=log)
                note = {
                    "left": "ออกจากกลุ่มแล้ว ✅",
                    "not-member": "Bot10 ไม่ได้เป็นสมาชิกกลุ่มนี้ (ไม่ต้องออก)",
                    "stuck": "⚠️ หาปุ่มออกจากกลุ่มไม่เจอ — ออกเองในแอปหนึ่งครั้ง",
                }.get(result.get("status", ""), result.get("status", ""))
            except (mf.MassFinderError, FarmError) as error:
                note = f"ออกจากกลุ่มไม่สำเร็จ: {error}"
                log(f"leave_group ล้ม: {error}")
            except Exception:
                note = "ออกจากกลุ่มล้มกลางทาง — ดู log"
                log(f"leave_group ล้มกลางทาง:\n{traceback.format_exc()}")
        removed = _config_remove_group(gid)
        state = mf.load_kw_state()
        state["rejected"][gid] = {"name": name + " (removed)", "url": url,
                                  "at": datetime.now().strftime("%Y-%m-%d %H:%M")}
        state["approved"].pop(gid, None)
        mf.save_kw_state(state)
        say(token, chat_id,
            f"🗑 เอากลุ่มออกแล้ว: <b>{html.escape(name[:50])}</b>\n"
            + ("• ลบออกจาก list หาโพสต์แมสแล้ว\n" if removed else "• ไม่ได้อยู่ใน list\n")
            + "• ใส่บัญชี rejected เป็น (removed)\n• " + note)
        log(f"REMOVED กลุ่ม: {name}")
        # คิวเบื้องหลังเห็น state แล้วเติมการ์ด/ไล่ /test ต่อเอง — ไม่ต้องสั่งอะไรเพิ่ม

    threading.Thread(target=work, daemon=True).start()


def _wl_by_keyword(state: dict) -> dict[str, list]:
    """จัดกลุ่ม whitelist ตาม keyword — {keyword: [entry เรียง avg มาก→น้อย]}"""
    grouped: dict[str, list] = {}
    for entry in (state.get("whitelist") or {}).values():
        grouped.setdefault(entry.get("keyword") or "?", []).append(entry)
    for items in grouped.values():
        items.sort(key=lambda e: -(e.get("avg") or 0))
    return grouped


def _wl_band(entry: dict) -> str:
    """ป้ายช่วงสมาชิกของ entry — ของเก่าที่ยังไม่มี band ถือเป็นแบนด์ >100k"""
    return entry.get("band") or mf.band_label(mf.KW_MIN_MEMBERS, 0)


def _wl_lines(items: list) -> list[str]:
    """รายการ whitelist — แบ่งหัวข้อย่อยตามช่วงสมาชิก (ใหญ่→เล็ก)"""
    by_band: dict[str, list] = {}
    for entry in items:
        by_band.setdefault(_wl_band(entry), []).append(entry)
    # เรียงแบนด์จากใหญ่ไปเล็กด้วยเลขขอบล่างที่อ่านจากป้าย ("100k+" → 100000)
    def band_order(label: str) -> int:
        head = label.split("-")[0].rstrip("+")
        try:
            return -int(float(head.rstrip("kK")) * (1000 if head[-1:].lower() == "k" else 1))
        except ValueError:
            return 0
    lines, shown, index = [], 0, 0
    for band in sorted(by_band, key=band_order):
        entries = by_band[band]
        if len(by_band) > 1:
            lines.append(f"  <i>ช่วง {band} ({len(entries)} กลุ่ม)</i>")
        for e in entries:
            if shown >= 25:
                break
            index += 1
            shown += 1
            stat = (f" — เฉลี่ย {e.get('avg')} · เกิน100 {e.get('over')}"
                    if e.get("avg") is not None else " — (รับด้วยมือ)")
            members = e.get("members") or 0
            lines.append(f"{index}. {html.escape(str(e.get('name', ''))[:45])}{stat}"
                         + (f" · ~{members:,} คน" if members else ""))
            lines.append(e.get("url", ""))
    if len(items) > shown:
        lines.append(f"…และอีก {len(items) - shown} กลุ่ม")
    return lines


def do_whitelists(token: str, chat_id: str) -> None:
    """/whitelists — กลุ่มที่ผ่านทั้งหมด ทุก keyword"""
    grouped = _wl_by_keyword(mf.load_kw_state())
    if not grouped:
        say(token, chat_id, "ยังไม่มีกลุ่มใน whitelist — เริ่มด้วย /keyword <คำค้น>")
        return
    total = sum(len(v) for v in grouped.values())
    lines = [f"🏆 <b>Whitelist ทั้งหมด ({total} กลุ่ม)</b>"]
    for keyword, items in grouped.items():
        lines += ["", f'🔑 <b>"{html.escape(keyword)}"</b> ({len(items)} กลุ่ม)']
        lines += _wl_lines(items)
    say(token, chat_id, "\n".join(lines))


def do_whitelist(token: str, chat_id: str, argument: str) -> None:
    """/whitelist — เลือก keyword ก่อน แล้วโชว์กลุ่มที่ผ่านของคำนั้น"""
    grouped = _wl_by_keyword(mf.load_kw_state())
    if not grouped:
        say(token, chat_id, "ยังไม่มีกลุ่มใน whitelist — เริ่มด้วย /keyword <คำค้น>")
        return
    if argument and argument in grouped:
        items = grouped[argument]
        say(token, chat_id, "\n".join(
            [f'🏆 <b>Whitelist "{html.escape(argument)}" ({len(items)} กลุ่ม)</b>', ""]
            + _wl_lines(items)))
        return
    # ยังไม่เลือก/พิมพ์ไม่ตรง — ให้เลือกด้วยปุ่ม หรือพิมพ์ /whitelist <คำค้น>
    rows = [[{"text": f'🔑 {kw} ({len(items)})',
              "callback_data": f"wl:{kw[:50]}"}]
            for kw, items in grouped.items()]
    say(token, chat_id,
        "เลือกคำค้นที่จะดู whitelist (หรือพิมพ์ <code>/whitelist คำค้น</code>)",
        {"inline_keyboard": rows})


def do_private(token: str, chat_id: str) -> None:
    """/private — รายการกลุ่มส่วนตัวที่ตรวจพบและบันทึกแยกไว้"""
    items = mf.load_kw_state().get("private", {})
    if not items:
        say(token, chat_id, "ยังไม่มีกลุ่มส่วนตัวที่บันทึกไว้")
        return
    lines = [f"🔒 <b>กลุ่มส่วนตัวที่บันทึกแยกไว้ ({len(items)} กลุ่ม)</b>", ""]
    for index, (gid, info) in enumerate(list(items.items())[:30], 1):
        members = info.get("members", 0)
        lines.append(f"{index}. {html.escape(info.get('name', gid)[:50])}"
                     + (f" — ~{members:,} คน" if members else ""))
        lines.append(info.get("url", ""))
    if len(items) > 30:
        lines.append(f"…และอีก {len(items) - 30} กลุ่ม")
    say(token, chat_id, "\n".join(lines))


# --------------------------------------------------- /pending งานค้างรอตัดสิน

# rejected โชว์พร้อมปุ่ม ♻️ สูงสุดกี่ใบ — เยอะเกินนี้ปุ่มล้นแชท (ที่เหลือบอกจำนวน)
_REJECT_SHOW = 12


def _rejected_card(rejected: dict) -> tuple[str, dict | None]:
    """การ์ดกลุ่มที่ถูกปัดตก + ปุ่ม ♻️ กู้คืน — คืน (ข้อความ, keyboard|None)

    เรียงกลุ่มที่เพิ่งปัดตกล่าสุดขึ้นก่อน (ดู 'at') เพราะของที่เพิ่งพลาดมือ
    น่ากู้สุด · ปุ่มผูกด้วย gid ไม่ใช่ลำดับ จึงไม่เพี้ยนเวลาแก้การ์ดในที่
    """
    items = sorted(rejected.items(),
                   key=lambda kv: str(kv[1].get("at", "")), reverse=True)
    shown = items[:_REJECT_SHOW]
    lines = [f"🗑 <b>ถูกปัดตกไปแล้ว: {len(items)} กลุ่ม</b>",
             "กด ♻️ เพื่อกู้กลับมาให้ /keyword พิจารณาใหม่", ""]
    buttons = []
    for index, (gid, info) in enumerate(shown, 1):
        name = str(info.get("name") or info.get("url") or gid)
        tag = {"dead": "ตายแล้ว", "user-reject": "คุณปัดเอง",
               "removed": "ลบ+ออกจากกลุ่ม"}.get(info.get("verdict", ""), "")
        lines.append(f"{index}. {html.escape(name[:45])}"
                     + (f" · {tag}" if tag else ""))
        buttons.append([{"text": f"♻️ กู้ {name[:22]}",
                         "callback_data": f"pd:rs:{gid[:50]}"}])
    if len(items) > _REJECT_SHOW:
        lines.append(f"\n…และอีก {len(items) - _REJECT_SHOW} กลุ่ม "
                     "(กู้ได้เฉพาะที่เพิ่งปัดล่าสุด)")
    return "\n".join(lines), ({"inline_keyboard": buttons} if buttons else None)


def do_pending(token: str, chat_id: str) -> None:
    """/pending — งานค้างรอตัดสิน: กลุ่มก้ำกึ่งรอ Approve/Reject + กลุ่มที่ถูกปัดตก

    การ์ดก้ำกึ่งใบเก่ามักถูกดันหายในประวัติแชท (โดยเฉพาะหลังบอทรีสตาร์ต) —
    คำสั่งนี้ส่งการ์ดใหม่ที่กดได้จริง แล้ว **ผูกปุ่มกับใบใหม่** (อัปเดต message_id
    ใน state) ไม่งั้น kg: handler จับคู่ message_id ไม่ตรง จะขึ้น "การ์ดนี้จบไปแล้ว"
    """
    state = mf.load_kw_state()
    pending = state.get("pending") or {}
    rejected = state.get("rejected") or {}
    if not pending and not rejected:
        say(token, chat_id,
            "✨ ไม่มีงานค้าง — ไม่มีกลุ่มก้ำกึ่งรอตัดสิน และไม่มีกลุ่มที่ถูกปัดตก")
        return
    if pending:
        say(token, chat_id,
            f"⚖️ <b>ก้ำกึ่งรอคุณตัดสิน: {len(pending)} กลุ่ม</b>\n"
            "Approve = เข้า whitelist · Reject = ตัดทิ้ง")
        for gid, entry in list(pending.items()):
            caption = (entry.get("caption")
                       or kw_caption(entry, entry.get("keyword", "")))
            try:
                new_mid = telegram_bot.send_message(
                    token, chat_id, caption, kw_buttons(gid))
            except telegram_bot.TelegramError as error:
                log(f"/pending ส่งการ์ดก้ำกึ่ง {gid} ไม่ได้: {error}")
                continue
            # ผูกปุ่มกับการ์ดใบใหม่ (ส่งเป็นข้อความ = is_photo False)
            fresh = mf.load_kw_state()
            if gid in fresh.get("pending", {}):
                fresh["pending"][gid]["message_id"] = new_mid
                fresh["pending"][gid]["is_photo"] = False
                mf.save_kw_state(fresh)
    if rejected:
        message, keyboard = _rejected_card(rejected)
        say(token, chat_id, message, keyboard)


def kw_link_status(text: str) -> str | None:
    """ผู้ใช้ส่งลิงก์กลุ่มเข้ามาเฉยๆ — บอกสถานะถ้าเคยจัดการแล้ว (โชว์ rejected)"""
    gid = mf.group_id_from_url(text)
    if not gid:
        return None
    state = mf.load_kw_state()
    if gid in state.get("private", {}):
        info = state["private"][gid]
        return (f"🔒 กลุ่มนี้ถูกบันทึกเป็น<b>กลุ่มส่วนตัว</b>ไว้แล้ว\n"
                f"{html.escape(info.get('name', gid))}")
    if gid in state["rejected"]:
        info = state["rejected"][gid]
        return (f"⛔ <b>REJECTED</b> — กลุ่มนี้ถูกปัดตกไปแล้ว\n"
                f"{html.escape(info.get('name', gid))}")
    if gid in state["approved"]:
        info = state["approved"][gid]
        return (f"✅ กลุ่มนี้เคย Approve และส่งเข้า /test แล้ว\n"
                f"{html.escape(info.get('name', gid))}")
    if gid in state["sent"]:
        return "🕐 กลุ่มนี้เคยเสนอไปแล้ว ยังไม่ได้ตัดสิน/อยู่ในคิว"
    return "ยังไม่เคยเจอกลุ่มนี้ใน /keyword"


def do_set(token: str, chat_id: str, argument: str) -> None:
    config = mf.load_config()
    if not argument:
        say(token, chat_id, mf.settings_text(config))
        return
    parts = argument.split()
    value = parts[-1] if parts and parts[-1].lstrip("-").isdigit() else None
    field = next(
        (key for key, aliases in SET_FIELDS.items()
         if any(alias in argument.lower() for alias in aliases)),
        None)
    if field is None or value is None:
        say(token, chat_id, "ไม่เข้าใจคำสั่ง — ดูวิธีปรับ:\n\n" + mf.settings_text(config))
        return
    number = max(0, int(value))
    if field == "min_likes" and number == 0:
        say(token, chat_id, "เกณฑ์ engagement ปิดไม่ได้ — ใส่ค่ามากกว่า 0")
        return
    if field == "scrolls":
        number = max(1, min(30, number))
    config[field] = number
    mf.save_config(config)
    log(f"/set {field} = {number}")
    say(token, chat_id, "บันทึกแล้ว ✅\n\n" + mf.settings_text(config))


def on_command(token: str, chat_id: str, text: str) -> None:
    command, _, argument = text.partition(" ")
    command = command.lower().split("@")[0]
    argument = argument.strip()
    # log ทุกคำสั่งที่รับ — ไม่ปล่อยให้เป็นกล่องดำ (เห็นชัดว่ารับถึงจริง)
    log(f"รับคำสั่ง: {command}{(' ' + argument[:40]) if argument else ''}")
    if command in ("/start", "/help"):
        say(token, chat_id, HELP)
    elif command == "/find":
        do_find(token, chat_id)
    elif command == "/test":
        _test_selection[chat_id] = set()
        message, keyboard = test_card(mf.load_config(), set())
        say(token, chat_id, message, keyboard)
    elif command == "/keyword":
        do_keyword(token, chat_id, argument)
    elif command == "/bands":
        do_bands(token, chat_id, argument)
    elif command == "/recheck":
        do_recheck(token, chat_id, argument)
    elif command == "/pending":
        do_pending(token, chat_id)
    elif command == "/whitelists":
        do_whitelists(token, chat_id)
    elif command == "/whitelist":
        do_whitelist(token, chat_id, argument)
    elif command == "/private":
        do_private(token, chat_id)
    elif command == "/add":
        do_add(token, chat_id, argument)
    elif command == "/groups":
        _send_groups_card(token, chat_id)
    elif command == "/set":
        do_set(token, chat_id, argument)
    else:
        say(token, chat_id, "ไม่รู้จักคำสั่งนี้\n\n" + HELP)


def on_callback(token: str, callback: dict) -> None:
    data = str(callback.get("data") or "")
    chat_id = str(((callback.get("message") or {}).get("chat") or {}).get("id", ""))
    log(f"รับปุ่ม: {data}")
    answer = ""
    if data.startswith("mr:"):
        # ผู้ใช้กด "ไม่เอาโพสต์นี้" — เข้าบัญชีดำถาวร รอบหน้าไม่นับไม่ส่งอีก
        post_id = data[3:]
        entry = mf.reject_post(post_id)
        answer = "ตัดโพสต์นี้แล้ว — จะหาโพสต์อื่นมาแทนในรอบถัดไป"
        log(f"ไม่เอาโพสต์ {post_id} ({entry.get('likes', 0)} ไลค์ "
            f"จาก {entry.get('group') or 'ไม่ทราบกลุ่ม'})")
        message = callback.get("message") or {}
        original = message.get("text", "")
        if message.get("message_id"):
            # ขีดฆ่าข้อความเดิม + ปุ่มหายไปเอง (editMessageText ไม่ส่ง keyboard)
            try:
                telegram_bot.call(token, "editMessageText", {
                    "chat_id": chat_id,
                    "message_id": message["message_id"],
                    "text": f"🚫 ตัดแล้ว\n<s>{html.escape(original)}</s>",
                    "parse_mode": "HTML",
                })
            except telegram_bot.TelegramError as error:
                log(f"ขีดฆ่าข้อความไม่สำเร็จ: {error}")
    elif data.startswith("md:"):
        mid = (callback.get("message") or {}).get("message_id")
        if mid != _groups_card_mid.get(chat_id):
            # การ์ดเก่า — ลำดับในปุ่มไม่ตรงรายการปัจจุบันแล้ว กดต่อจะลบผิดกลุ่ม
            answer = "การ์ดนี้เก่าแล้ว — ส่งรายการล่าสุดให้ใหม่"
            if mid:
                try:
                    telegram_bot.call(token, "editMessageReplyMarkup", {
                        "chat_id": chat_id, "message_id": mid,
                        "reply_markup": {"inline_keyboard": []}})
                except telegram_bot.TelegramError as error:
                    log(f"ถอดปุ่มการ์ดกลุ่มเก่าไม่ได้: {error}")
            _send_groups_card(token, chat_id)
        else:
            config = mf.load_config()
            index = int(data[3:])
            if 0 <= index < len(config["groups"]):
                removed = config["groups"].pop(index)
                mf.save_config(config)
                name = removed.get("name") or removed.get("url", "")
                answer = f"ลบ {name[:40]} แล้ว"
                log(f"ลบกลุ่มออกจาก list: {name}")
            else:
                answer = "รายการนี้ถูกลบไปแล้ว"
            # แก้การ์ดใบเดิมในที่ — รายการ+ปุ่มสดเสมอ ไม่ส่งใบใหม่รก แชทไม่ยาว
            message, keyboard = groups_card(mf.load_config())
            try:
                payload = {"chat_id": chat_id, "message_id": mid,
                           "text": message, "parse_mode": "HTML"}
                if keyboard:
                    payload["reply_markup"] = keyboard
                telegram_bot.call(token, "editMessageText", payload)
            except telegram_bot.TelegramError as error:
                if "not modified" not in str(error).lower():
                    log(f"อัปเดตการ์ดกลุ่มไม่ได้: {error}")
    elif data.startswith("kg:"):
        # ตัดสินกลุ่มจาก /keyword (โหมดคิว) — การ์ดค้างได้หลายใบ จับคู่ด้วย gid
        action, _, gid = data[3:].partition(":")
        state = mf.load_kw_state()
        entry = (state.get("pending") or {}).get(gid)
        message = callback.get("message") or {}
        if not entry or message.get("message_id") != entry.get("message_id"):
            answer = "การ์ดนี้จบไปแล้ว"
            mid = message.get("message_id")
            if mid:      # ถอดปุ่มการ์ดเก่าทิ้ง จะได้ไม่ถูกกดอีก
                try:
                    telegram_bot.call(token, "editMessageReplyMarkup", {
                        "chat_id": chat_id, "message_id": mid,
                        "reply_markup": {"inline_keyboard": []}})
                except telegram_bot.TelegramError as error:
                    log(f"ถอดปุ่มการ์ดเก่าไม่ได้: {error}")
        else:
            # การ์ดก้ำกึ่ง (flow อัตโนมัติ): Approve = เข้า whitelist · Reject = ตัดทิ้ง
            info = {"name": entry.get("name", ""), "url": entry.get("url", ""),
                    "members": entry.get("members", 0),
                    "keyword": entry.get("keyword", state.get("keyword", "")),
                    "over": entry.get("over"), "avg": entry.get("avg"),
                    "at": datetime.now().strftime("%Y-%m-%d %H:%M")}
            if action == "rj":
                state["rejected"][gid] = {**info, "verdict": "user-reject"}
                state["pending"].pop(gid, None)
                mf.save_kw_state(state)
                answer = "ปัดตกแล้ว ❌"
                log(f"REJECT (ก้ำกึ่ง): {info['name']}")
                _kw_edit_card(token, chat_id, entry,
                              "❌ <b>REJECTED</b> — ตัดทิ้งตามที่กด")
                _kw_del_shot(entry)
            elif action == "ap":
                state.setdefault("whitelist", {})[gid] = info
                state["pending"].pop(gid, None)
                mf.save_kw_state(state)
                answer = "รับแล้ว ✅ — เข้า whitelist"
                log(f"APPROVE (ก้ำกึ่ง): {info['name']} → whitelist")
                _kw_edit_card(token, chat_id, entry,
                              "✅ <b>APPROVED</b> — เข้า whitelist แล้ว (ดู /whitelists)")
                _kw_del_shot(entry)
            else:
                answer = "ปุ่มไม่รู้จัก"
    elif data.startswith("wl:"):
        # เมนูเลือกดู whitelist ราย keyword — กดดูซ้ำได้ ไม่ปิดปุ่ม
        do_whitelist(token, chat_id, data[3:])
        answer = "โชว์ whitelist แล้ว"
    elif data.startswith("kk:"):
        # หลัง /test ของ /keyword — เก็บกลุ่มไว้ใน list หรือเอาออก+ออกจากกลุ่ม
        # (โหมดคิว: การ์ด Keep/Removed ค้างได้หลายใบ จับคู่ด้วย gid)
        action, _, gid = data[3:].partition(":")
        state = mf.load_kw_state()
        decision = (state.get("decisions") or {}).get(gid)
        message = callback.get("message") or {}

        def _seal_kk(mid: int | None, status: str) -> None:
            """แก้การ์ด Keep/Removed เป็นข้อความสถานะ — ปุ่มหายไป กดซ้ำไม่ได้อีก

            popup ตอบกลับใช้ไม่ได้กับปุ่มที่กดช้าเกิน 15 วิ (query too old)
            ผู้ใช้เลยไม่รู้ว่ากดติดแล้วและกดซ้ำเรื่อยๆ — ต้องให้การ์ดพูดแทน
            """
            if not mid:
                return
            try:
                telegram_bot.call(token, "editMessageText", {
                    "chat_id": chat_id, "message_id": mid,
                    "text": status, "parse_mode": "HTML"})
            except telegram_bot.TelegramError as error:
                if "not modified" not in str(error).lower():
                    log(f"ลบปุ่มการ์ด Keep/Removed ไม่ได้: {error}")

        if not decision or message.get("message_id") != decision.get("message_id"):
            answer = "รายการนี้จบไปแล้ว"
            # ปุ่มค้างจากการ์ดเก่า — ลบปุ่มออกจากการ์ดนั้นเลย จะได้ไม่ถูกกดอีก
            _seal_kk(message.get("message_id"),
                     "✔️ รายการนี้ตัดสินไปแล้ว — ดูสถานะที่ /keyword หรือ /groups")
        elif action == "kp":
            added = _config_add_group(decision)
            state = mf.load_kw_state()
            state["decisions"].pop(gid, None)
            mf.save_kw_state(state)
            answer = "เก็บไว้แล้ว 📌"
            log(f"KEEP กลุ่ม: {decision.get('name')}")
            _seal_kk(decision.get("message_id"),
                     f"📌 <b>KEEP</b> — เก็บ {html.escape(decision.get('name', gid)[:50])} "
                     "ไว้ใน list แล้ว")
            say(token, chat_id,
                f"📌 เก็บ <b>{html.escape(decision.get('name', gid)[:50])}</b> "
                + ("เข้า list หาโพสต์แมสแล้ว" if added else "ไว้ (มีใน list อยู่แล้ว)"))
        elif action == "rm":
            state["decisions"].pop(gid, None)    # เอาออกก่อนเริ่มงาน — กันกดซ้ำลบสองรอบ
            mf.save_kw_state(state)
            answer = "กำลังลบ + ออกจากกลุ่ม…"
            _seal_kk(decision.get("message_id"),
                     f"🗑 <b>REMOVED</b> — กำลังลบ {html.escape(decision.get('name', gid)[:50])} "
                     "+ ออกจากกลุ่ม…")
            do_kw_remove(token, chat_id, decision)
        else:
            answer = "ปุ่มไม่รู้จัก"
    elif data.startswith("mt:"):
        # เลือกกลุ่มสำหรับ /test — ติ๊กหลายกลุ่มแล้วกดเริ่ม
        config = mf.load_config()
        groups = config.get("groups", [])
        sel = _test_selection.setdefault(chat_id, set())
        action = data[3:]
        msg = callback.get("message") or {}
        mid = msg.get("message_id")
        if action == "go":
            chosen = [groups[i] for i in sorted(sel) if 0 <= i < len(groups)]
            if not chosen:
                answer = "ยังไม่ได้เลือกกลุ่ม — ติ๊กอย่างน้อย 1 กลุ่ม"
            else:
                if mid:
                    try:
                        telegram_bot.call(token, "editMessageText", {
                            "chat_id": chat_id, "message_id": mid,
                            "text": f"🔬 กำลังเจาะลึก {len(chosen)} กลุ่ม…",
                            "parse_mode": "HTML"})
                    except telegram_bot.TelegramError:
                        pass
                _test_selection.pop(chat_id, None)
                answer = "เริ่มเจาะลึกแล้ว"
                do_test(token, chat_id, chosen)
        else:
            if action == "all":
                sel.clear()
                sel.update(range(len(groups)))
            elif action == "none":
                sel.clear()
            elif action.startswith("t:"):
                index = int(action[2:])
                sel.discard(index) if index in sel else sel.add(index)
            if mid:
                _, keyboard = test_card(config, sel)
                try:
                    telegram_bot.call(token, "editMessageReplyMarkup", {
                        "chat_id": chat_id, "message_id": mid,
                        "reply_markup": keyboard})
                except telegram_bot.TelegramError as error:
                    log(f"อัปเดตการ์ด /test ไม่ได้: {error}")
            answer = f"เลือก {len(sel)} กลุ่ม"
    elif data.startswith("pd:rs:"):
        # /pending — กู้กลุ่มที่ถูกปัดตกกลับมา: เอาออกจาก rejected + sent
        # เพื่อให้รอบค้น /keyword ถัดไปเจอ+เทสใหม่ได้ (ปุ่มผูก gid ไม่เพี้ยน)
        gid = data[6:]
        state = mf.load_kw_state()
        info = (state.get("rejected") or {}).pop(gid, None)
        if info is None:
            answer = "กลุ่มนี้ไม่อยู่ในรายการปัดตกแล้ว"
        else:
            (state.get("sent") or {}).pop(gid, None)
            mf.save_kw_state(state)
            answer = "กู้คืนแล้ว ♻️ — จะถูกพิจารณาใหม่รอบค้นถัดไป"
            log(f"RESTORE (กู้ rejected): {info.get('name', gid)}")
            mid = (callback.get("message") or {}).get("message_id")
            if mid:
                rejected = mf.load_kw_state().get("rejected") or {}
                if rejected:
                    text, keyboard = _rejected_card(rejected)
                else:
                    text = "✨ กู้คืนครบแล้ว — ไม่มีกลุ่มถูกปัดตกเหลือ"
                    keyboard = None
                try:
                    payload = {"chat_id": chat_id, "message_id": mid,
                               "text": text, "parse_mode": "HTML"}
                    if keyboard:
                        payload["reply_markup"] = keyboard
                    telegram_bot.call(token, "editMessageText", payload)
                except telegram_bot.TelegramError as error:
                    if "not modified" not in str(error).lower():
                        log(f"อัปเดตการ์ด rejected ไม่ได้: {error}")
    try:
        telegram_bot.call(token, "answerCallbackQuery", {
            "callback_query_id": callback.get("id", ""), "text": answer[:180],
        })
    except telegram_bot.TelegramError as error:
        log(f"ตอบปุ่มไม่สำเร็จ: {error}")


# --------------------------------------------------------------------- ลูปหลัก

def main() -> int:
    # กันเปิดสองตัว — getUpdates ซ้อนกัน = 409 ข้อความหายสลับไปมา
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    lock_handle = open(LOCK_FILE, "a+b")
    try:
        msvcrt.locking(lock_handle.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        print("❌ fb_mass_bot.py เปิดอยู่แล้วอีกตัว — ห้ามรันซ้อน (getUpdates ชนกัน)")
        return 1

    config = mf.load_config()
    token, home_chat = mf.telegram_target(config)
    beat()
    threading.Thread(target=_heartbeat_loop, daemon=True).start()
    log(f"บอทหาโพสต์แมสเริ่มทำงาน (chat {home_chat})")
    say(token, home_chat, "🟢 บอทหาโพสต์แมสพร้อมทำงาน\n\n" + HELP)

    _migrate_legacy_state(token, home_chat)
    _recover_interrupted(token, home_chat)
    # เดมอน /keyword โหมดอัตโนมัติ — ทำงานตลอดอายุโปรเซส
    threading.Thread(target=_kw_worker_loop, args=(token, home_chat),
                     daemon=True).start()
    _bot_loop(token, home_chat)
    return 0


def _recover_interrupted(token: str, home_chat: str) -> None:
    """กลุ่มที่กำลังเจาะอยู่ตอนโปรเซสตาย ต้องกลับเข้าคิว — **ทุกครั้งที่บูต**

    ช่องโหว่ที่อุดตรงนี้: `_kw_run_next_test` ดึงกลุ่มออกจากคิวแล้ว save ทันที
    (state["testing"] = gid) ถ้าโปรเซสถูกปิดกลางทาง กลุ่มนั้นจะไม่อยู่ทั้งใน
    คิวและใน sent = **หายไปเฉยๆ** ไม่มีใครหยิบมาเจาะอีก
    เดิมมี migration คอยกวาดให้ แต่พอปิด migration ด้วย schema (กันมันกิน
    การ์ดก้ำกึ่ง) ช่องโหว่นี้จึงโผล่ — ต้องมีตัวกู้แยกที่รันทุกครั้ง
    """
    state = mf.load_kw_state()
    gid = state.get("testing")
    if not gid:
        return
    if any(q.get("gid") == gid for q in state.get("queue") or []):
        state["testing"] = None
        mf.save_kw_state(state)
        return
    known = (state.get("sent") or {}).get(gid) or {}
    state.setdefault("queue", []).insert(0, {
        "gid": gid,
        "name": known.get("name", ""),
        "url": known.get("url") or f"https://www.facebook.com/groups/{gid}/",
        "members": known.get("members", 0),
    })
    state["testing"] = None
    mf.save_kw_state(state)
    log(f"กู้กลุ่มที่ค้างกลางการเจาะกลับเข้าคิว: {known.get('name') or gid}")
    say(token, home_chat,
        f"♻️ กู้กลุ่มที่ค้างตอนปิดโปรแกรมกลับเข้าคิวแล้ว "
        f"({html.escape(str(known.get('name') or gid)[:40])})")


def _migrate_legacy_state(token: str, home_chat: str) -> None:
    """ย้ายงานค้างจาก flow เก่าทุกชนิดเข้า loop อัตโนมัติใหม่ (ผู้ใช้สั่ง 14 ส.ค.)

    ⚠️ รันได้ **ครั้งเดียวตลอดกาล** — ล็อกด้วย schema เพราะคีย์ "pending" ถูกใช้
    ซ้ำสองความหมาย: flow เก่า = การ์ดรอ Approve ก่อน test · flow ใหม่ = กลุ่ม
    ก้ำกึ่งที่เจาะเสร็จแล้วรอผู้ใช้ตัดสิน ถ้าปล่อยให้รันทุกครั้งที่บูต การ์ด
    ก้ำกึ่งของ flow ใหม่จะถูกล้างทิ้งแล้วโยนกลับเข้าคิวเจาะซ้ำ (เสีย ~14 นาที
    ต่อกลุ่ม และคำตัดสินที่ผู้ใช้ยังไม่ได้กดหายไปเงียบๆ)
    """
    kw = mf.load_kw_state()
    if int(kw.get("schema") or 0) >= KW_SCHEMA:
        return
    changed = False
    carried: list[dict] = []

    def _carry(entry: dict, what: str) -> None:
        nonlocal changed
        if entry and entry.get("gid"):
            carried.append({k: entry.get(k)
                            for k in ("gid", "name", "url", "members")})
            changed = True
            log(f"โยก{what}: {entry.get('name')} เข้าคิวเจาะอัตโนมัติ")

    for legacy_key in ("current", "decision"):
        _carry(kw.pop(legacy_key, None) or {}, "งานค้างเก่า")
    # ❌ ห้ามแตะ kw["pending"] ที่นี่ — flow ใหม่ใช้คีย์เดียวกันเก็บ "การ์ดก้ำกึ่ง
    # ที่เจาะเสร็จแล้วรอผู้ใช้ตัดสิน" ของเก่า (การ์ดรอ Approve ก่อน test) ถูกย้าย
    # ไปหมดแล้วตั้งแต่บูตแรกของ flow ใหม่ 14 ส.ค. — โค้ดย้าย pending จึงถอดออก
    for gid, entry in list((kw.get("decisions") or {}).items()):
        _carry(entry, "การ์ด Keep/Removed ค้าง")
        try:
            telegram_bot.call(token, "editMessageText", {
                "chat_id": home_chat, "message_id": entry.get("message_id"),
                "text": "⏩ flow ใหม่ — กลุ่มนี้จะถูกเจาะ+ตัดสินอัตโนมัติ",
            })
        except telegram_bot.TelegramError:
            pass
    kw["decisions"] = {}
    for gid in (kw.get("test_queue") or []) + ([kw.get("testing")] if kw.get("testing") else []):
        info = (kw.get("approved") or {}).get(gid) or {}
        _carry({"gid": gid, "name": info.get("name", gid),
                "url": info.get("url") or f"https://www.facebook.com/groups/{gid}/",
                "members": info.get("members", 0)}, "คิว /test เดิม")
    kw["test_queue"] = []
    kw["testing"] = None
    # approved เดิม (ผู้ใช้เคยกดรับใน flow เก่า) → เข้า whitelist ตรง ยกเว้นที่ถูกปัดไปแล้ว
    for gid, info in list((kw.get("approved") or {}).items()):
        if gid in kw.get("rejected", {}) or gid in kw.get("whitelist", {}):
            continue
        kw.setdefault("whitelist", {})[gid] = {
            "name": info.get("name", gid), "url": info.get("url", ""),
            "members": info.get("members", 0),
            "keyword": info.get("keyword") or kw.get("keyword", ""),
            "over": None, "avg": None, "at": info.get("at", ""), "legacy": True}
        changed = True
    if carried:
        seen_carry = set()
        fresh_carry = []
        for c in carried:
            gid = c.get("gid")
            if gid in seen_carry or gid in kw.get("rejected", {}) \
                    or gid in kw.get("whitelist", {}) \
                    or any(q.get("gid") == gid for q in kw.get("queue", [])):
                continue
            seen_carry.add(gid)
            fresh_carry.append(c)
        kw["queue"] = fresh_carry + kw.get("queue", [])
        kw["summary_sent"] = False
        log(f"โยกงานค้างรวม {len(fresh_carry)} กลุ่มเข้าคิวเจาะอัตโนมัติ")
    kw["schema"] = KW_SCHEMA          # ปิดประตู — บูตครั้งหน้าไม่รันซ้ำ
    mf.save_kw_state(kw)
    log(f"migration flow เก่า: ทำครั้งเดียวจบ (schema={KW_SCHEMA})"
        + (" · ไม่มีอะไรต้องย้าย" if not changed else ""))


def _bot_loop(token: str, home_chat: str) -> None:
    """ลูปอ่านข้อความ Telegram — แยกออกมาให้ main() อ่านง่าย"""
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
                callback = update.get("callback_query")
                if callback:
                    on_callback(token, callback)
                    continue
                message = update.get("message") or {}
                chat_id = str((message.get("chat") or {}).get("id", ""))
                text = (message.get("text") or "").strip()
                if not chat_id or not text:
                    continue
                if chat_id != str(home_chat):
                    # คุยกับเจ้าของคนเดียว — คนอื่นเจอบอทแล้วสั่งไม่ได้
                    log(f"เมินข้อความจาก chat แปลกหน้า {chat_id}")
                    continue
                if text.startswith("/"):
                    on_command(token, chat_id, text)
                else:
                    # ส่งลิงก์กลุ่มมาเฉยๆ = ถามสถานะ (เคย reject ต้องโชว์ rejected)
                    status = kw_link_status(text)
                    say(token, chat_id, status if status else HELP)
            except Exception:
                # ข้อความเดียวพังต้องไม่ฆ่าลูป — แต่ต้องลง log เสมอ (กติกา 2.4)
                log(f"จัดการข้อความไม่สำเร็จ:\n{traceback.format_exc()}")


if __name__ == "__main__":
    raise SystemExit(main())
