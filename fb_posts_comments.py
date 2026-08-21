"""ดึงคอมเมนต์ของโพสต์เดียวให้ **ครบทุกอัน** พร้อมยอดไลค์ · รูป · การตอบกลับ

พิสูจน์จากของจริง (18 ส.ค. 2569) ว่าคอมเมนต์ **ไม่ได้อยู่ใน GraphQL** ตอนเปิด
permalink — ก้อน GraphQL ที่ได้มีแต่ข้อมูลระบบ (ตั้งค่าวิดีโอ/messenger)
ตัวคอมเมนต์จริงอยู่ใน DOM ที่ Comet เรนเดอร์แล้ว จึงต้องอ่านจากหน้าจอ

สามด่านที่ต้องผ่าน ไม่งั้นได้คอมเมนต์ไม่ครบ:
  1. ค่าเริ่มต้นเรียงแบบ "เกี่ยวข้องมากที่สุด" ซึ่ง **ซ่อนคอมเมนต์ส่วนใหญ่**
     ต้องสลับเป็น "ความคิดเห็นทั้งหมด" ก่อน (ยืนยันแล้ว: พอสลับ คอมเมนต์โผล่เพิ่มทันที)
  2. โหลดทีละหน้า ต้องกด "ดูความคิดเห็นเพิ่มเติม" ซ้ำจนปุ่มหาย
  3. การตอบกลับพับไว้ ต้องกด "ดูการตอบกลับทั้งหมด" ทุกอัน
     (ถ้าไม่กาง จะได้แต่คอมเมนต์แม่ = เสียงคนขายมากกว่าเสียงลูกค้า)
"""
from __future__ import annotations

import re
import time
from collections import Counter

# ปุ่ม/ข้อความที่ต้องกด — รับทั้งไทยและอังกฤษตามกติกาโปรเจกต์
MORE_COMMENTS_RE = re.compile(
    r"(ดูความคิดเห็นเพิ่มเติม|ดูความคิดเห็นอีก|ความคิดเห็นก่อนหน้า"
    r"|ดูความคิดเห็นทั้งหมด|View more comments|View \d+ more comment"
    r"|Previous comments)")
# ข้อความจริงบนปุ่ม (ยืนยันจากหน้าเว็บ 18 ส.ค.): "ดูการตอบกลับ 6 รายการ"
# — เลขอยู่ **หลัง** คำว่าตอบกลับ ไม่ใช่หน้า (ของเดิมเขียนกลับด้านจึงกดไม่โดน)
MORE_REPLIES_RE = re.compile(
    r"(ดูการตอบกลับ\s*\d*\s*รายการ|ดูการตอบกลับทั้งหมด|ดูการตอบกลับอีก"
    r"|ดูการตอบกลับ|การตอบกลับทั้งหมด"
    r"|View all \d+ replies|View \d+ repl|View more replies)")
SORT_TRIGGER = ("เกี่ยวข้องมากที่สุด", "Most relevant", "จัดเรียงตาม")
SORT_CHOICE = ("ความคิดเห็นทั้งหมด", "All comments", "ใหม่ที่สุด", "Newest")

# ตัวเลขไทยย่อในหน้า Facebook — "2.3 พัน" = 2300
_UNIT = {"พัน": 1_000, "หมื่น": 10_000, "แสน": 100_000, "ล้าน": 1_000_000,
         "K": 1_000, "k": 1_000, "M": 1_000_000}
_NUM_RE = re.compile(r"([\d.,]+)\s*(พัน|หมื่น|แสน|ล้าน|[KkM])?")


def thai_number(text: str) -> int:
    """'2.3 พัน' → 2300 · '478' → 478 · อ่านไม่ออก → 0"""
    m = _NUM_RE.search(text or "")
    if not m:
        return 0
    try:
        value = float(m.group(1).replace(",", ""))
    except ValueError:
        return 0
    return int(round(value * _UNIT.get(m.group(2) or "", 1)))


# ดึงคอมเมนต์ทั้งหมดจาก DOM — คืนข้อมูลดิบให้ฝั่ง Python จัดการต่อ
#
# โครงสร้างจริงของ Facebook Comet:
#   div[role="article"][aria-label="ความคิดเห็นจาก <ชื่อ> เมื่อ <เวลา>"]
#     ├ a[href=โปรไฟล์] > ...รูปอวาตาร์ (image/img)
#     ├ ฟองข้อความ: div[dir="auto"] ที่ไม่ได้อยู่ใน <a>
#     ├ ยอดไลค์: element ที่ aria-label ว่า "N คนแสดงความรู้สึก..."
#     └ การตอบกลับ = article ซ้อนอยู่ข้างใน (จับด้วยการนับ ancestor)
_EXTRACT_JS = r"""
() => {
  const arts = [...document.querySelectorAll('div[role="article"]')];
  const isComment = el => /ความคิดเห็นจาก|Comment by/i.test(el.getAttribute('aria-label') || '');
  const out = [];
  for (const el of arts) {
    const label = el.getAttribute('aria-label') || '';
    if (!isComment(el)) continue;

    // ความลึก: Facebook ไม่ได้ซ้อน article ของการตอบกลับไว้ในคอมเมนต์แม่เสมอ
    // (ทดสอบจริงแล้วนับ ancestor ได้ 0 ทั้งที่กางการตอบกลับสำเร็จ 161 ครั้ง)
    // จึงวัดจาก "การเยื้องซ้าย" บนหน้าจอแทน — การตอบกลับถูกดันเข้าไปเสมอ
    let depth = 0, p = el.parentElement;
    while (p) { if (p.matches?.('div[role="article"]') && isComment(p)) depth++; p = p.parentElement; }
    const left = Math.round(el.getBoundingClientRect().left);

    // ทุกอย่างต้องเป็นของคอมเมนต์ใบนี้เอง ไม่ใช่ของการตอบกลับที่ซ้อนอยู่
    const own = node => node.closest('div[role="article"]') === el;

    // ลิงก์โปรไฟล์คนคอมเมนต์
    //
    // ⚠️ ห้ามหยิบ "ลิงก์แรกที่เจอ" — วัดจริง 19 ส.ค. พบว่า 9,669 จาก 9,688 แถว
    // (99%) ได้ลิงก์ **โพสต์** มาแทนลิงก์คน เพราะลิงก์ตัวแรกในบล็อกคอมเมนต์คือ
    // เวลา ("37 สัปดาห์") ซึ่งชี้ไป permalink ของโพสต์ ไม่ใช่โปรไฟล์
    // ผลคือแยกไม่ออกว่าใครเป็นใคร → วิเคราะห์ฐานลูกค้าไม่ได้
    // ในกลุ่ม Facebook ลิงก์โปรไฟล์จริงมีรูปแบบ /groups/<gid>/user/<uid>/
    // ส่วนนอกกลุ่มเป็น /profile.php?id= หรือ /<username>
    const isProfile = h =>
      /\/groups\/\d+\/user\/\d+/.test(h) ||
      /facebook\.com\/profile\.php\?id=\d+/.test(h) ||
      (/facebook\.com\/[A-Za-z0-9.\-_]+\/?(\?|$)/.test(h) &&
       !/\/(posts|permalink|photo|videos|watch|groups|reel|story\.php|events)/.test(h));
    const links = [...el.querySelectorAll('a[href]')].filter(own)
      .map(a => a.href).filter(Boolean);
    const profileHref = links.find(isProfile) || '';

    // อวาตาร์: Facebook ใช้ <image> ใน svg บ้าง <img> บ้าง
    let avatar = '';
    const sv = [...el.querySelectorAll('svg image')].find(own);
    if (sv) avatar = sv.getAttribute('xlink:href') || sv.getAttribute('href') || '';
    if (!avatar) { const im = [...el.querySelectorAll('img')].find(own);
                   if (im) avatar = im.src || ''; }

    // ข้อความ: div[dir=auto] ที่ไม่ได้อยู่ในลิงก์ (ลิงก์ = ชื่อคน/แท็ก/ปุ่ม)
    //
    // ⚠️ ต้องเช็ค closest === el ด้วย ไม่งั้นคอมเมนต์แม่จะดูดข้อความของ
    // "การตอบกลับ" ที่ซ้อนอยู่ข้างในมาเป็นของตัวเอง (การตอบกลับเป็น article
    // ซ้อน แต่ div ข้อความของมันไม่ได้ครอบ article ไว้ ตัวกรองแบบเดิมจึงไม่กัน)
    const mine = node => node.closest('div[role="article"]') === el;
    const texts = [...el.querySelectorAll('div[dir="auto"]')]
      .filter(d => mine(d) && !d.closest('a'))
      .map(d => (d.innerText || '').trim())
      .filter(Boolean);

    // ยอดไลค์ของคอมเมนต์นี้
    let likes = '';
    for (const n of el.querySelectorAll('[aria-label]')) {
      const al = n.getAttribute('aria-label') || '';
      if (/แสดงความรู้สึก|reacted|reaction/i.test(al) && /\d/.test(al)) {
        if (n.closest('div[role="article"]') === el) { likes = al; break; }
      }
    }

    // รูปในคอมเมนต์ = รูปที่ไม่ใช่อวาตาร์ (อวาตาร์เล็กและอยู่ในลิงก์โปรไฟล์)
    const imgs = [...el.querySelectorAll('img')]
      .filter(own)
      .filter(i => i.src && i.src.includes('fbcdn'))
      .filter(i => (i.naturalWidth || i.width || 0) > 80 || /scontent.*t39/.test(i.src))
      .filter(i => i.src !== avatar)
      .map(i => i.src);

    out.push({label, depth, left, texts, likes, avatar,
              profile: profileHref,
              imgs: [...new Set(imgs)].slice(0, 4)});
  }
  return out;
}
"""


# เลื่อนหน้าโพสต์เดี่ยว — **ห้ามใช้ mouse.wheel / window.scrollTo**
#
# วัดจริง 18 ส.ค. บนหน้า permalink: body ไม่เลื่อนเลย (scrollY=0, docH=winH=757)
# เพราะ Facebook ใส่คอมเมนต์ไว้ในคอนเทนเนอร์ที่เลื่อนเองซ้อนข้างใน
#   mouse.wheel   → คอมเมนต์ 20 → 20  (ไม่ขยับ)
#   window.scrollTo → 20 → 20        (ไม่ขยับ)
#   กด End        → 20 → 70  ✅
#   เลื่อนคอนเทนเนอร์ตรงๆ → 70 → 80 ✅
# จึงใช้สองวิธีหลังคู่กัน
_SCROLL_BOXES_JS = """
() => {
  let moved = 0;
  for (const d of document.querySelectorAll('div')) {
    if (d.scrollHeight > d.clientHeight + 200 && d.clientHeight > 200) {
      d.scrollTop = d.scrollHeight; moved++;
    }
  }
  return moved;
}
"""


def _scroll_down(page, pause: int = 1500) -> None:
    """เลื่อนลงล่างสุดด้วยวิธีที่พิสูจน์แล้วว่าได้ผลกับหน้าโพสต์เดี่ยว"""
    try:
        page.keyboard.press("End")
    except Exception:
        pass
    try:
        page.evaluate(_SCROLL_BOXES_JS)
    except Exception:
        pass
    page.wait_for_timeout(pause)


def _log_candidates(page, log) -> None:
    """หาปุ่ม/ลิงก์ที่ "น่าจะ" ใช่ปุ่มโหลดคอมเมนต์เพิ่ม — ใช้ตอน pattern ไม่ตรง

    ถ้าไม่มีตัวช่วยนี้ เวลา Facebook เปลี่ยนคำบนปุ่ม เราจะเก็บได้ไม่ครบแบบเงียบๆ
    โดยไม่รู้เลยว่าพลาดเพราะอะไร (กติกาโปรเจกต์: ห้ามให้ความล้มเหลวเงียบ)
    """
    try:
        found = page.evaluate(
            """() => [...document.querySelectorAll(
                 'div[role="button"],span[role="button"],a[role="link"]')]
                 .map(e => (e.innerText||'').trim())
                 .filter(t => t && t.length < 60 &&
                    /(ความคิดเห็น|ตอบกลับ|เพิ่มเติม|comment|repl|more)/i.test(t))
                 .slice(0, 12)""")
        if found:
            log(f"    ปุ่มที่เจอบนหน้า (ไม่ตรง pattern): {found}")
    except Exception:
        pass


# กดปุ่มทั้งหน้าในจังหวะเดียวด้วย JS แทนการสั่งทีละปุ่มผ่าน Playwright
#
# เหตุผลด้านความเร็ว (วัดจริง): กดทีละปุ่มแบบ locator ใช้ ~1.2 วิ/ปุ่ม ×
# 12 ปุ่ม/รอบ × 15 รอบ = 6.5 นาทีต่อโพสต์เดียว ซึ่งเอาไปใช้กับ 100 โพสต์/กลุ่ม
# ไม่ไหว · กดผ่าน JS ทีเดียวทั้งหน้าเหลือ ~0.1 วิ แล้วค่อยรอโหลดรอบเดียว
_CLICK_JS = """
(source) => {
  const re = new RegExp(source);
  let n = 0;
  const seen = new WeakSet();
  for (const el of document.querySelectorAll(
        'div[role="button"],span[role="button"],a[role="link"]')) {
    if (seen.has(el)) continue;
    const t = (el.innerText || '').trim();
    if (t && t.length < 60 && re.test(t)) { seen.add(el); el.click(); n++; }
  }
  return n;
}
"""


def _click_all(page, pattern: re.Pattern, limit: int, log, what: str,
               diagnose: bool = False) -> int:
    """กดทุกปุ่มที่ข้อความตรง pattern ในรอบเดียว — คืนจำนวนปุ่มที่กดได้"""
    try:
        clicks = page.evaluate(_CLICK_JS, pattern.pattern)
    except Exception as error:
        log(f"    กด{what}ไม่ได้: {type(error).__name__}")
        return 0
    if not clicks and diagnose:
        _log_candidates(page, log)
    return int(clicks or 0)


def switch_sort_to_all(page, log) -> bool:
    """สลับการเรียงคอมเมนต์เป็น "ความคิดเห็นทั้งหมด" — คืน True ถ้าสลับได้

    ⚠️ ด่านนี้สำคัญที่สุด: ค่าเริ่มต้น "เกี่ยวข้องมากที่สุด" ซ่อนคอมเมนต์
    ไว้เยอะมาก ถ้าไม่สลับ จะเก็บได้ไม่ครบแล้วไม่รู้ตัว
    """
    for trigger in SORT_TRIGGER:
        try:
            el = page.get_by_text(trigger, exact=False)
            if not el.count():
                continue
            el.first.click(timeout=4_000)
            page.wait_for_timeout(1_800)
            for choice in SORT_CHOICE:
                opt = page.get_by_text(choice, exact=False)
                if opt.count():
                    opt.first.click(timeout=4_000)
                    page.wait_for_timeout(3_000)
                    log(f"    สลับการเรียง → {choice}")
                    return True
            page.keyboard.press("Escape")
        except Exception:
            continue
    log("    ⚠️ สลับการเรียงไม่ได้ — อาจได้คอมเมนต์ไม่ครบ")
    return False


def clean_comment(raw: dict) -> dict | None:
    """แปลงข้อมูลดิบจาก DOM เป็นคอมเมนต์ที่พร้อมเก็บ"""
    label = raw.get("label") or ""
    m = re.match(r"(?:ความคิดเห็นจาก|Comment by)\s+(.+?)"
                 r"(?:\s+(?:เมื่อ|on)\s+(.+?)(?:ที่แล้ว)?)?$", label)
    if not m:
        return None
    name = m.group(1).strip()
    when = (m.group(2) or "").strip()

    texts = [t for t in (raw.get("texts") or []) if t]
    # ทิ้งบรรทัดที่เป็นปุ่ม/ป้ายของ Facebook ไม่ใช่เนื้อคอมเมนต์
    drop = re.compile(r"^(ถูกใจ|ตอบกลับ|แชร์|ดูคำแปล|แก้ไขแล้ว|ติดตาม|ผู้เขียน|"
                      r"ผู้ดูแล|Like|Reply|Share|Author|Admin|\d+\s*(สัปดาห์|วัน|ปี|"
                      r"ชม\.|นาที|เดือน))$")
    body_parts = [t for t in texts if not drop.match(t.strip())]
    body = " ".join(body_parts).strip()
    body = re.sub(r"\s{2,}", " ", body)
    # ตัดชื่อตัวเองที่บางทีติดมาหัวข้อความ
    body = re.sub(r"^" + re.escape(name) + r"\s*", "", body).strip()

    return {
        "author": name,
        "author_url": (raw.get("profile") or "").split("?")[0],
        "avatar": raw.get("avatar") or "",
        "when": when,
        "text": body,
        "likes": thai_number(raw.get("likes") or ""),
        "images": raw.get("imgs") or [],
        "depth": int(raw.get("depth") or 0),
    }


def collect_comments(page, url: str, log=print, expect: int = 0,
                     max_more: int = 60) -> dict:
    """เปิดโพสต์แล้วเก็บคอมเมนต์ให้ครบที่สุด — คืนผลพร้อมตัวเลขกำกับความครบ

    คืน {"comments": [...], "expect": N, "got": N, "sorted_all": bool,
         "more_clicks": N, "reply_clicks": N, "seconds": N}
    ตัวเลข expect/got ต้องเก็บลงฐานด้วย — ไว้บอกว่า "เก็บได้ครบไหม"
    ห้ามบันทึกว่า done ทั้งที่ got << expect (กติกา: ห้ามให้ความล้มเหลวเงียบ)
    """
    started = time.time()
    page.goto(url, wait_until="domcontentloaded", timeout=90_000)
    page.wait_for_timeout(5_000)

    # เลื่อนลงให้ถึงโซนคอมเมนต์ก่อน (Comet โหลดแบบขี้เกียจ)
    for _ in range(3):
        _scroll_down(page)

    sorted_all = switch_sort_to_all(page, log)

    # วน "เลื่อนลงสุด → กดปุ่มโหลดเพิ่ม → นับ" จนกว่าจำนวนคอมเมนต์จะไม่เพิ่ม
    #
    # ทำเป็นลูปเพราะพิสูจน์แล้วว่ากดครั้งเดียวไม่พอ และปุ่มโหลดเพิ่มอยู่ **ท้าย
    # รายการ** ซึ่งต้องเลื่อนไปให้ถึงก่อนถึงจะมีอยู่ใน DOM (รอบแรกที่ทำแบบกด
    # อย่างเดียวได้แค่ 17 จาก 478 คอมเมนต์ = 3%)
    more = replies = 0
    prev, idle = 0, 0
    for round_number in range(1, max_more + 1):
        more += _click_all(page, MORE_COMMENTS_RE, 3, log, "ดูเพิ่มเติม",
                           diagnose=(round_number == 1))
        replies += _click_all(page, MORE_REPLIES_RE, 3, log, "กางการตอบกลับ")
        _scroll_down(page)
        try:
            now = page.evaluate(
                """() => [...document.querySelectorAll('div[role="article"]')]
                     .filter(e => /ความคิดเห็นจาก|Comment by/i
                       .test(e.getAttribute('aria-label')||'')).length""")
        except Exception:
            now = prev
        if now <= prev:
            idle += 1
        else:
            idle = 0
        if round_number % 5 == 0 or now != prev:
            log(f"    รอบ {round_number}: คอมเมนต์บนหน้า {now} "
                f"(กดเพิ่ม {more} · กางตอบกลับ {replies})")
        prev = now
        if expect and now >= expect:
            log(f"    ครบตามที่ฟีดบอก ({now} ≥ {expect})")
            break
        if idle >= 4:              # 4 รอบติดไม่เพิ่ม = หมดจริง
            log(f"    ไม่เพิ่มแล้ว 4 รอบติด — หยุดที่ {now} คอมเมนต์")
            break
    else:
        log(f"    ชนเพดาน {max_more} รอบ — หยุดที่ {prev} คอมเมนต์")

    raw = []
    try:
        raw = page.evaluate(_EXTRACT_JS)
    except Exception as error:
        log(f"    อ่าน DOM ไม่ได้: {type(error).__name__}: {error}")

    # ความลึกวัดจากการเยื้องซ้าย — คอมเมนต์แม่ชิดซ้ายสุด การตอบกลับถูกดันเข้าไป
    #
    # ใช้ "ค่าที่พบบ่อยที่สุด" เป็นฐาน ไม่ใช่ค่าน้อยสุด: องค์ประกอบที่ยังไม่ถูก
    # เรนเดอร์จะได้ left = 0 ซึ่งลากฐานให้ต่ำผิด แล้วคอมเมนต์แม่ทุกใบจะถูกนับ
    # เป็นการตอบกลับหมด (เจอจริงรอบก่อน: 170/170 ใบกลายเป็นตอบกลับ)
    lefts = [int(r.get("left") or 0) for r in raw if int(r.get("left") or 0) > 0]
    base_left = Counter(lefts).most_common(1)[0][0] if lefts else 0

    comments, seen = [], set()
    for item in raw:
        clean = clean_comment(item)
        if clean is None:
            continue
        if not clean["depth"]:
            indent = int(item.get("left") or 0) - base_left
            clean["depth"] = 1 if indent >= 20 else 0
        key = (clean["author"], clean["text"][:60], clean["when"])
        if key in seen:
            continue
        seen.add(key)
        comments.append(clean)

    elapsed = round(time.time() - started, 1)
    got = len(comments)
    note = ""
    if expect and got < expect * 0.5:
        note = f"เก็บได้ {got} จากที่ควรมี {expect} — ไม่ครบ"
        log(f"    ⚠️ {note}")
    log(f"    คอมเมนต์ {got} อัน (ตอบกลับ {sum(1 for c in comments if c['depth'])}) "
        f"· กดเพิ่ม {more} ครั้ง · {elapsed} วิ")
    return {"comments": comments, "expect": expect, "got": got,
            "sorted_all": sorted_all, "more_clicks": more,
            "reply_clicks": replies, "seconds": elapsed, "warn": note}
