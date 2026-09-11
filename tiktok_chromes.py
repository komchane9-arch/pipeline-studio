"""Chrome แยกรายบัญชี TikTok — สำหรับลงคลิปผ่านคอม ไม่ใช่ผ่านมือถือ

**เจ้าของสั่ง 11 ก.ย. 2569** — *"ทำ chrome ตรง tiktok ไว้ 7 chrome ทำให้สามารถ
กดเรียกดูและจำ ไอดี tiktok ที่ล็อกอินแยกแต่ละ chrome อันนี้จะเอาไว้ลง tiktok
ผ่าน chrome ในคอม แยกจากการลงผ่านมือถือ"*

---

## ทำไมต้องแยกโปรไฟล์

ของเดิม `flow_worker.login_tiktok()` ให้ล็อกอิน TikTok **ในโปรไฟล์เดียวกับ Flow**
ซึ่งใช้ได้กับบัญชีเดียวเท่านั้น — คุกกี้ TikTok มีชุดเดียวต่อโปรไฟล์

พอต้องการหลายบัญชี **ต้องแยกโฟลเดอร์โปรไฟล์** ทางเดียว เหมือนที่ทำกับบัญชี
Google Flow ตอน 10 ก.ย. ซึ่งพิสูจน์แล้วว่าสลับบัญชีได้จริงโดยไม่ต้องล็อกอินใหม่
และไม่เจอ reCAPTCHA เลย

## ต่างจากการลงผ่านมือถืออย่างไร

    ผ่านมือถือ (tiktok_publish_bot)  กดจอจริงบน REDMI 15C · หนึ่งบัญชีต่อเครื่อง
                                     ต้องรอคิวมือถือ · ใบละ 4-7 นาที
    ผ่านคอม (ตัวนี้ + tiktok_post)   เปิด TikTok Studio บนเว็บ · หลายบัญชีพร้อมกัน
                                     ไม่แย่งมือถือ · คลิปอยู่บนคอมอยู่แล้ว

**ทั้งสองทางอยู่ร่วมกันได้** ไม่ต้องเลือกอย่างใดอย่างหนึ่ง

## กติกาที่ยึด

**ไอดีที่จำไว้ต้องมาจากหน้าจริง ไม่ใช่ให้คนพิมพ์เอง** (กติกาข้อ 2.3.1) —
ถ้าให้พิมพ์เอง วันหนึ่งโปรไฟล์กับไอดีจะไม่ตรงกันโดยไม่มีใครรู้ แล้วคลิปจะขึ้น
ผิดช่องแบบถอนไม่ได้ ตัวนี้อ่านจากหน้า TikTok ที่ล็อกอินอยู่เท่านั้น

**ยังไม่รู้ ≠ ยังไม่ได้ล็อกอิน** — เก็บเป็น `None` แล้วแสดงต่างหาก
"""
from __future__ import annotations

import json
import re
import subprocess
from datetime import datetime
from pathlib import Path

import studio_shared as shared

PROFILES_DIR = shared.DATA_DIR / "tiktok_profiles"
STATE_FILE = shared.DATA_DIR / "tiktok_chromes.json"
HOW_MANY = 7
UPLOAD_URL = "https://www.tiktok.com/tiktokstudio/upload"

# ไอดี TikTok บนหน้า — ขึ้นต้นด้วย @ ตามด้วยตัวอักษร/ตัวเลข/จุด/ขีดล่าง
HANDLE_RE = re.compile(r"@[A-Za-z0-9._]{2,24}")


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def profile_dir(slot: int) -> Path:
    """โฟลเดอร์โปรไฟล์ของช่องที่ N — ตั้งชื่อด้วยเลขช่อง ไม่ใช่ชื่อบัญชี

    **ตั้งใจไม่ใช้ชื่อบัญชีเป็นชื่อโฟลเดอร์** เพราะบทเรียนจากฝั่ง Flow:
    พอล็อกอินสลับหน้าต่างกันแล้วต้องมาซ่อม ชื่อโฟลเดอร์กับบัญชีจึงไม่ตรงกัน
    และหลอกคนอ่านตลอดมา เลขช่องเป็นแค่ที่อยู่ ส่วนไอดีจริงอ่านจากหน้าเว็บ
    """
    return PROFILES_DIR / f"tiktok{int(slot)}"


def ensure_profiles(how_many: int = HOW_MANY) -> list[Path]:
    """สร้างโฟลเดอร์โปรไฟล์ให้ครบ — ว่างเปล่าก็ได้ Chrome จะเติมเองตอนเปิด"""
    PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    made = []
    for slot in range(1, int(how_many) + 1):
        folder = profile_dir(slot)
        folder.mkdir(parents=True, exist_ok=True)
        made.append(folder)
    return made


# ------------------------------------------------------------ ที่เก็บไอดี


def load() -> dict:
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save(name: str, handle: str | None, note: str = "") -> None:
    """จดไอดีของโปรไฟล์หนึ่ง — `handle=None` แปลว่า **ยังอ่านไม่ได้** ไม่ใช่ไม่มี"""
    def change(data: dict) -> dict:
        if not isinstance(data, dict):
            data = {}
        old = data.get(str(name)) or {}
        row = {"profile": str(name), "checked_at": _now(), "note": str(note or "")}
        if handle:
            row["handle"] = str(handle)
            row["stale"] = False
            row["last_ok_at"] = row["checked_at"]
        else:
            row["handle"] = old.get("handle")
            row["stale"] = True
            row["last_ok_at"] = old.get("last_ok_at") or ""
        data[str(name)] = row
        return data

    shared.update_json(STATE_FILE, change, default={},
                       label=f"จดไอดี TikTok ของ {name}")


def rows() -> list[dict]:
    """ทั้ง 7 ช่อง พร้อมไอดีที่รู้ — ช่องที่ยังไม่ล็อกอินก็ต้องอยู่ในรายการ"""
    import chrome_view

    ensure_profiles()
    known = load()
    out = []
    for slot in range(1, HOW_MANY + 1):
        folder = profile_dir(slot)
        row = dict(known.get(folder.name) or {})
        out.append({
            "slot": slot,
            "profile": folder.name,
            "handle": row.get("handle"),
            "checked_at": row.get("checked_at") or "",
            "stale": bool(row.get("stale")),
            "note": row.get("note") or "",
            "running": chrome_view.profile_running(folder),
            "ready": bool(row.get("handle")),
        })
    return out


# --------------------------------------------------------- อ่านไอดีจากหน้าจริง


def read_identity(profile: str | Path, log=print) -> dict:
    """เปิดโปรไฟล์นี้แล้วอ่านไอดี TikTok ที่ล็อกอินอยู่

    **เปิดแบบซ่อน** ไม่แย่งจอที่เจ้าของใช้ และถือล็อกของโฟลเดอร์ตัวเองไว้
    ไม่ให้ตัวอื่นเปิด user-data-dir เดียวกันซ้อนจนโปรไฟล์เสีย
    """
    from playwright.sync_api import sync_playwright

    import chrome_view
    import flow_worker

    folder = Path(profile)
    if not folder.is_dir():
        return {"ok": False, "profile": folder.name, "why": "ไม่พบโฟลเดอร์โปรไฟล์"}
    if chrome_view.profile_running(folder):
        return {"ok": False, "profile": folder.name,
                "why": "โครมของช่องนี้เปิดอยู่ — ปิดก่อนแล้วค่อยกดอ่านใหม่"}

    lock = f"tiktok-{folder.name}"
    try:
        with shared.browser_lock(timeout=120, profile=lock,
                                 label=f"อ่านไอดี TikTok {folder.name}"):
            with sync_playwright() as pw:
                browser = flow_worker.open_browser(pw, hidden=True,
                                                   profile_dir=folder)
                try:
                    page = browser.pages[0] if browser.pages else browser.new_page()
                    page.goto(UPLOAD_URL, wait_until="domcontentloaded",
                              timeout=90_000)
                    page.wait_for_timeout(9_000)
                    handle, why = _handle_on_page(page)
                    if not handle:
                        # เก็บภาพ + ผังหน้าไว้ **ก่อนปิด** ปิดแล้วแคปไม่ได้อีก
                        # (กติกา 2.6.1) รอบหน้าที่มีคนล็อกอินจริงแล้วยังอ่านไม่ได้
                        # จะได้เห็นหน้าจริงเลยว่า TikTok วางชื่อบัญชีไว้ตรงไหน
                        # ไม่ต้องไล่เดาทีละรอบ
                        try:
                            import evidence
                            evidence.shot(
                                page, f"อ่านไอดี TikTok ไม่ได้ {folder.name}",
                                tag="tiktok",
                                note=f"เหตุผล: {why} · ที่อยู่หน้า: {page.url}"
                                     f" · {_where_names_live(page)}")
                        except Exception as snap:              # noqa: BLE001
                            log(f"   (เก็บภาพหน้าไม่ได้: {type(snap).__name__})")
                finally:
                    browser.close()
    except Exception as error:                                 # noqa: BLE001
        save(folder.name, None, note=f"{type(error).__name__}")
        return {"ok": False, "profile": folder.name,
                "why": f"{type(error).__name__}: {str(error)[:90]}"}

    save(folder.name, handle, note=why)
    if not handle:
        log(f"   {folder.name}: ยังอ่านไอดีไม่ได้ — {why}")
        return {"ok": False, "profile": folder.name, "handle": None, "why": why}
    log(f"   {folder.name}: {handle}")
    return {"ok": True, "profile": folder.name, "handle": handle}


# ----------------------------------------------- ที่อยู่ของชื่อบัญชีบนหน้า TikTok
#
# วัดจากบัญชีจริงที่ล็อกอินอยู่ (12 ก.ย. 2569) — สองหน้าเก็บคนละที่
#
#   หน้า Studio   <script id="__Creator_Center_Context__">   (เข้ารหัสแบบ HTML)
#                 commonAppContext.user.uniqueId
#   หน้าแรก       <script id="__UNIVERSAL_DATA_FOR_REHYDRATION__">
#                 __DEFAULT_SCOPE__["webapp.app-context"].user.uniqueId
#
# ทั้งสองให้ค่าตรงกัน และ **หน้า Studio ไม่มีก้อนของหน้าแรกเลย**
# ตอนแรกเขียนไว้เฉพาะก้อนของหน้าแรกแล้วอ่านหน้า Studio ไม่ออก
BLOB_ID = "__UNIVERSAL_DATA_FOR_REHYDRATION__"
STUDIO_BLOB_ID = "__Creator_Center_Context__"
STUDIO_PATH = ("commonAppContext", "user", "uniqueId")
WWW_PATH = ("__DEFAULT_SCOPE__", "webapp.app-context", "user", "uniqueId")

# สคริปต์นี้ทดสอบกับบัญชีจริงที่ล็อกอินอยู่แล้ว ได้ "taiwhatsale" ทั้งสองหน้า
READ_JS = """() => {
  const parse = (raw) => {
    try { return JSON.parse(raw); } catch (e) {}
    try { const ta = document.createElement('textarea');
          ta.innerHTML = raw; return JSON.parse(ta.value); } catch (e) { return null; }
  };
  const read = (id, path) => {
    const el = document.getElementById(id);
    if (!el) return null;
    let n = parse(el.textContent || '');
    for (const k of path) {
      n = (n && typeof n === 'object') ? n[k] : null;
      if (n === null || n === undefined) return null;
    }
    return typeof n === 'string' ? n : null;
  };
  return {
    studio: read(%(studio_id)s, %(studio_path)s),
    www: read(%(www_id)s, %(www_path)s),
    hasStudioBlob: !!document.getElementById(%(studio_id)s),
    hasWwwBlob: !!document.getElementById(%(www_id)s)
  };
}""" % {
    "studio_id": json.dumps(STUDIO_BLOB_ID),
    "www_id": json.dumps(BLOB_ID),
    "studio_path": json.dumps(list(STUDIO_PATH)),
    "www_path": json.dumps(list(WWW_PATH)),
}


def pick_handle(found: dict | None, url: str) -> tuple[str | None, str]:
    """เลือกไอดีจากค่าที่อ่านมาได้ — คืน (ไอดี, เหตุผลถ้าไม่ได้)

    **รับเฉพาะที่อยู่ของบัญชีตัวเอง ห้ามไล่หาทั้งหน้า** วัดของจริง 11 ก.ย.:
    หน้าแรก TikTok ตอนยังไม่ล็อกอิน มีชื่อบัญชีคนอื่นฝังอยู่ 3 ชื่อในฟีด
    ตัวอ่านที่ไล่หาทั้งก้อนจะหยิบชื่อคนแปลกหน้ามาจดว่าเป็นช่องเรา
    แล้ววันหนึ่งคลิปจะขึ้นผิดช่องแบบถอนไม่ได้

    สองแหล่งที่ได้มาต้องตรงกัน ไม่ตรง = ไม่เดา ไม่เลือกข้าง
    """
    text = str(url or "")
    if "/login" in text or "signup" in text:
        return None, "ยังไม่ได้ล็อกอิน — หน้าเด้งไปหน้าเข้าสู่ระบบ"
    if not isinstance(found, dict):
        return None, "อ่านหน้าไม่ได้ — ไม่ได้ค่ากลับมาเลย"

    picks = {}
    for key in ("studio", "www"):
        value = str(found.get(key) or "").strip()
        if value and HANDLE_RE.fullmatch("@" + value):
            picks[key] = "@" + value

    if len(set(picks.values())) > 1:
        return None, ("สองแหล่งบนหน้าให้ไอดีไม่ตรงกัน (" +
                      " กับ ".join(sorted(set(picks.values()))) +
                      ") — ไม่เดา ต้องดูด้วยตาก่อน")
    if picks:
        return next(iter(picks.values())), ""

    # ไม่มีบัญชีตัวเองในหน้า — แต่ถ้ายังอยู่หน้า Studio ได้แปลว่าล็อกอินแล้วแน่
    # เพราะหน้านั้นไล่คนที่ยังไม่ล็อกอินไปหน้าเข้าสู่ระบบเสมอ (วัดแล้ว)
    if "tiktokstudio" in text:
        return None, ("ล็อกอินแล้วแต่ยังอ่านไอดีไม่ได้ — TikTok ย้ายที่เก็บ "
                      "ชื่อบัญชี ต้องแก้โค้ด (เก็บภาพหน้าจอไว้แล้ว)")
    return None, f"ยังไม่ได้ล็อกอิน — ไม่พบบัญชีในหน้า ({text[:60]})"


def _handle_on_page(page) -> tuple[str | None, str]:
    """อ่าน @ไอดี จากหน้า TikTok — คืน (ไอดี, เหตุผลถ้าไม่ได้)"""
    url = str(page.url or "")
    try:
        found = page.evaluate(READ_JS)
    except Exception as error:                                 # noqa: BLE001
        return None, f"อ่านหน้าไม่ได้: {type(error).__name__}"
    return pick_handle(found, url)


def _where_names_live(page) -> str:
    """ตอนอ่านไอดีไม่ได้ ให้บอกว่าชื่อบัญชีไปโผล่ตรงไหนในข้อมูลบ้าง

    เก็บไว้กับหลักฐาน เพื่อให้รอบที่มีคนล็อกอินจริงแล้วยังอ่านไม่ออก
    แก้ได้จบในรอบเดียว ไม่ต้องให้เจ้าของล็อกอินซ้ำหลายรอบเพื่อไล่เดา
    """
    try:
        found = page.evaluate(
            """(ids) => {
                 const parse = (raw) => {
                   try { return JSON.parse(raw); } catch (e) {}
                   try { const ta = document.createElement('textarea');
                         ta.innerHTML = raw; return JSON.parse(ta.value); }
                   catch (e) { return null; }
                 };
                 const out = [];
                 for (const id of ids) {
                   const el = document.getElementById(id);
                   if (!el) { out.push(id + ': ไม่มีก้อนนี้บนหน้า'); continue; }
                   const d = parse(el.textContent || '');
                   if (!d) { out.push(id + ': แกะข้อมูลไม่ได้'); continue; }
                   out.push(id + ': ช่องบนสุด ' + Object.keys(d).slice(0, 10).join(','));
                   const walk = (node, path, depth) => {
                     if (depth > 9 || !node || typeof node !== 'object') return;
                     for (const k of Object.keys(node)) {
                       if (k === 'uniqueId' || k === 'nickName') {
                         out.push('  ' + path + '.' + k + ' = ' + String(node[k]).slice(0, 30));
                       } else { walk(node[k], path + '.' + k, depth + 1); }
                     }
                   };
                   walk(d, id, 0);
                 }
                 return out.slice(0, 20);
               }""", [STUDIO_BLOB_ID, BLOB_ID]) or []
    except Exception as error:                                 # noqa: BLE001
        return f"ดูที่เก็บชื่อไม่ได้: {type(error).__name__}"
    return "ชื่อบัญชีโผล่ที่: " + " | ".join(str(x) for x in found)


def refresh_all(log=print) -> dict:
    """ไล่อ่านไอดีทุกช่อง — ข้ามช่องที่เปิดค้างอยู่พร้อมบอกเหตุผล"""
    ensure_profiles()
    done, failed, skipped = [], [], []
    log(f"ไล่อ่านไอดี TikTok {HOW_MANY} ช่อง")
    for slot in range(1, HOW_MANY + 1):
        folder = profile_dir(slot)
        got = read_identity(folder, log=log)
        if got.get("ok"):
            done.append(got)
        elif "เปิดอยู่" in str(got.get("why") or ""):
            skipped.append(got)
        else:
            failed.append(got)
    return {"ok": bool(done), "done": done, "failed": failed,
            "skipped": skipped, "total": HOW_MANY}


def prove_reader(log=print) -> dict:
    """พิสูจน์ตัวอ่านไอดีบน **หน้าเว็บจริง** โดยไม่ต้องมีบัญชี

    ทำไมต้องมีคำสั่งนี้ — ตัวอ่านจะถูกใช้ตัดสินว่าคลิปจะขึ้นช่องไหน
    อ่านผิดแปลว่าคลิปขึ้นผิดช่องแบบถอนไม่ได้ จะรอพิสูจน์ตอนมีบัญชีจริง
    ไม่ได้ และเทสที่รันจากข้อมูลแช่แข็งอย่างเดียวก็ไม่ได้แตะเบราว์เซอร์เลย

    เปิดหน้า TikTok จริง แล้ววัดสองด้าน
      ก) หน้าที่ยังไม่ล็อกอิน ซึ่งมีชื่อบัญชีคนอื่นฝังอยู่ในฟีด -> ต้องปฏิเสธ
      ข) หน้าเดียวกันที่เติมก้อนบัญชีแบบตอนล็อกอินแล้ว -> ต้องอ่านไอดีออก

    ข้อ (ข) ใส่ก้อนบัญชีเข้าไปในข้อมูลเดิมของหน้าจริง ไม่ได้แต่งหน้าขึ้นใหม่
    จึงพิสูจน์ได้ทั้งเส้น ตั้งแต่ดึงข้อมูลจากหน้า แกะ ไล่ที่อยู่ ไปจนตรวจรูปแบบ
    """
    global STATE_FILE

    import shutil
    import tempfile

    from playwright.sync_api import sync_playwright

    import flow_worker

    want = "@komchan.shop"
    out = {"ok": False, "steps": []}
    folder = profile_dir(HOW_MANY)          # ใช้ช่องสุดท้าย ไม่ไปชนช่องที่ใช้จริง
    folder.mkdir(parents=True, exist_ok=True)
    with shared.browser_lock(timeout=120, profile=f"tiktok-{folder.name}",
                             label="พิสูจน์ตัวอ่านไอดี TikTok"):
        with sync_playwright() as pw:
            browser = flow_worker.open_browser(pw, hidden=True, profile_dir=folder)
            try:
                page = browser.pages[0] if browser.pages else browser.new_page()
                page.goto("https://www.tiktok.com/", wait_until="domcontentloaded",
                          timeout=90_000)
                page.wait_for_timeout(6_000)

                # ฟีดหน้าแรกเปลี่ยนทุกวัน บางรอบไม่มีชื่อคนอื่นติดมาเลย
                # ถ้าปล่อยไว้ ขั้นนี้จะ "ผ่าน" ทั้งที่ไม่ได้ทดสอบกับดักอะไร
                # จึงวางกับดักเองให้มีแน่นอนทุกรอบ ใช้ชื่อที่เคยติดมาจริง
                strangers = page.evaluate(
                    """(id) => {
                         const el = document.getElementById(id);
                         if (!el) return 0;
                         const d = JSON.parse(el.textContent);
                         const scope = d.__DEFAULT_SCOPE__ || (d.__DEFAULT_SCOPE__ = {});
                         const items = scope['webapp.updated-items'] || [];
                         for (const name of ['armkiss', '_ply01', 'wan.vogvax']) {
                           items.push({author: {uniqueId: name}});
                         }
                         scope['webapp.updated-items'] = items;
                         el.textContent = JSON.stringify(d);
                         return ((el.textContent || '').match(/"uniqueId"/g) || []).length;
                       }""", BLOB_ID)
                handle, why = _handle_on_page(page)
                step1 = handle is None and strangers >= 3
                out["steps"].append(
                    {"ชื่อ": "หน้าจริงที่ยังไม่ล็อกอิน + วางชื่อคนอื่นเป็นกับดัก",
                     "ผ่าน": step1,
                     "ชื่อบัญชีคนอื่นในหน้า": strangers,
                     "ตัวอ่านตอบ": handle or why})

                # ก้อนของหน้า Studio — ของจริงเข้ารหัสแบบ HTML และเก็บคนละที่
                # กับหน้าแรก ต้องทดสอบแยก ไม่งั้นพลาดแบบเดิมอีก
                page.evaluate(
                    """(args) => {
                         const [id, want] = args;
                         document.getElementById(id)?.remove();
                         const s = document.createElement('script');
                         s.id = id; s.type = 'application/json';
                         const raw = JSON.stringify({isUpload: true, commonAppContext:
                           {user: {uid: '69123', nickName: 'ชื่อที่โชว์ ไม่ใช่ไอดี',
                                   uniqueId: want, storeRegion: 'TH'}}});
                         const ta = document.createElement('textarea');
                         ta.textContent = raw;           // เข้ารหัสแบบ HTML เหมือนของจริง
                         s.textContent = ta.innerHTML;
                         document.body.appendChild(s);
                         history.replaceState(null, '', '/tiktokstudio/upload');
                       }""", [STUDIO_BLOB_ID, want.lstrip("@")])
                handle2, why2 = _handle_on_page(page)
                step2 = handle2 == want
                out["steps"].append(
                    {"ชื่อ": "หน้า Studio แบบล็อกอินแล้ว (ก้อนเข้ารหัส HTML)",
                     "ผ่าน": step2, "ตัวอ่านตอบ": handle2 or why2, "ที่ควรได้": want})

                # ก้อนของหน้าแรก
                page.evaluate(
                    """(args) => {
                         const [studioId, wwwId, want] = args;
                         document.getElementById(studioId)?.remove();
                         const el = document.getElementById(wwwId);
                         const d = JSON.parse(el.textContent);
                         d.__DEFAULT_SCOPE__['webapp.app-context'].user =
                           {uniqueId: want, storeRegion: 'TH'};
                         el.textContent = JSON.stringify(d);
                         history.replaceState(null, '', '/');
                       }""", [STUDIO_BLOB_ID, BLOB_ID, want.lstrip("@")])
                handle3, why3 = _handle_on_page(page)
                step3 = handle3 == want
                out["steps"].append(
                    {"ชื่อ": "หน้าแรกแบบล็อกอินแล้ว", "ผ่าน": step3,
                     "ตัวอ่านตอบ": handle3 or why3, "ที่ควรได้": want})

                # ---- อ่านออกแล้วต้อง "จดลงแฟ้ม" ได้จริงด้วย ----
                # อ่านออกแต่จดไม่ลง = ช่องนั้นยังขึ้นว่ายังไม่ได้ล็อกอินอยู่ดี
                # ใช้แฟ้มชั่วคราว ไม่แตะของจริง (กติกา 7.4)
                real_file = STATE_FILE
                temp_dir = Path(tempfile.mkdtemp(prefix="tiktok-prove-"))
                try:
                    STATE_FILE = temp_dir / "tiktok_chromes.json"
                    save(folder.name, handle3, note="พิสูจน์การจด")
                    row = next(r for r in rows() if r["profile"] == folder.name)
                    step4 = bool(row["handle"] == want and row["ready"]
                                 and not row["stale"] and row["checked_at"])
                    out["steps"].append(
                        {"ชื่อ": "จดไอดีลงแฟ้มแล้วอ่านกลับมาได้",
                         "ผ่าน": step4,
                         "ในแฟ้ม": {"ไอดี": row["handle"], "พร้อมใช้": row["ready"],
                                    "ไอดีเก่า": row["stale"],
                                    "ตรวจเมื่อ": row["checked_at"]}})

                    # รอบถัดไปอ่านไม่ได้ ต้อง **ไม่ลบไอดีเดิมทิ้ง** แต่ติดธงว่าเก่า
                    # ถ้าลบทิ้ง วันที่เน็ตสะดุดครั้งเดียว ช่องที่ล็อกอินไว้แล้ว
                    # จะกลายเป็น "ยังไม่ได้ล็อกอิน" ทั้งที่ยังล็อกอินอยู่
                    save(folder.name, None, note="อ่านไม่ได้รอบนี้")
                    row2 = next(r for r in rows() if r["profile"] == folder.name)
                    step5 = bool(row2["handle"] == want and row2["stale"])
                    out["steps"].append(
                        {"ชื่อ": "รอบถัดไปอ่านไม่ได้ ต้องเก็บไอดีเดิมไว้และติดธงว่าเก่า",
                         "ผ่าน": step5,
                         "ในแฟ้ม": {"ไอดี": row2["handle"], "ไอดีเก่า": row2["stale"],
                                    "เหตุผล": row2["note"]}})
                finally:
                    STATE_FILE = real_file
                    shutil.rmtree(temp_dir, ignore_errors=True)
            finally:
                browser.close()

    out["ok"] = all(bool(s["ผ่าน"]) for s in out["steps"])
    for step in out["steps"]:
        log(("   ผ่าน  " if step["ผ่าน"] else "   ไม่ผ่าน ") + str(step))
    log("   สรุป: " + ("ตัวอ่านใช้ได้" if out["ok"] else "ตัวอ่านมีปัญหา"))
    return out


if __name__ == "__main__":
    import sys

    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    if arg == "พิสูจน์":
        raise SystemExit(0 if prove_reader().get("ok") else 1)
    if arg == "อ่าน":
        print(refresh_all())
    elif arg == "เปิด" and len(sys.argv) > 2:
        import chrome_view
        folder = profile_dir(int(sys.argv[2]))
        folder.mkdir(parents=True, exist_ok=True)
        print(chrome_view.launch_profile(folder, UPLOAD_URL))
    else:
        data = rows()
        print(f"Chrome ของ TikTok {len(data)} ช่อง "
              f"(สำหรับลงผ่านคอม แยกจากการลงผ่านมือถือ)\n")
        print(f"   {'ช่อง':<7}{'โปรไฟล์':<12}{'ไอดี TikTok':<22}{'อ่านเมื่อ':<18}สถานะ")
        for row in data:
            handle = row["handle"] or "— ยังไม่ได้ล็อกอิน —"
            mark = []
            if row["running"]:
                mark.append("เปิดอยู่")
            if row["stale"] and row["handle"]:
                mark.append("ไอดีเก่า")
            print(f"   {row['slot']:<7}{row['profile']:<12}{handle:<22}"
                  f"{(row['checked_at'] or '-')[:16]:<18}{' · '.join(mark)}")
        ready = sum(1 for r in data if r["ready"])
        print(f"\n   ล็อกอินแล้ว {ready} จาก {len(data)} ช่อง")
        if ready < len(data):
            print("   เปิดช่องที่ยังว่างด้วย: python tiktok_chromes.py เปิด <เลขช่อง>")
