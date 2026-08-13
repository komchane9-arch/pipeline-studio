"""โพสต์คลิปขึ้น TikTok — พอร์ตมาจาก 2.Extension/4.Tiktok auto post

ต่อท้าย pipeline: เจน 4 ซีน → รวมคลิป → ตัดช่วงเงียบ → **โพสต์ TikTok**

โพสต์ผ่านหน้าเว็บ TikTok Studio (`/tiktokstudio/upload`) ไม่ใช่ผ่านมือถือ
เพราะคลิปอยู่บนคอมอยู่แล้ว ไม่ต้องเสียเวลา push เข้าเครื่องก่อน

หลักการพอร์ตเหมือน flow_driver.py: ยกตรรกะตรวจสภาพหน้ามาเป็น JS ชุดเดิม
ส่วนการพิมพ์/คลิกใช้ Playwright (trusted input จริง ไม่ต้องปลอม event)

กติกาที่ยกมาครบจากของเดิม
  - ทุกขั้น "รีเช็คว่าสำเร็จจริง" ก่อนไปขั้นถัดไป ไม่เดาจากการกดผ่าน
  - อัปโหลดลองได้ 3 ครั้ง ต้องเห็น editor โผล่ภายใน 20 วิถึงนับว่ารับไฟล์
  - TikTok ฟ้องอัปโหลดล้มเหลว = ตัดจบทันที ไม่รอจน timeout 180 วิ
  - แฮชแท็กพิมพ์แล้วเลือกจากรายการ suggestion + ตรวจซ้ำเติมตัวที่ขาด 2 รอบ
    (ขาดจริงก็ไปต่อ ไม่บล็อกการโพสต์)
  - กดโพสต์แล้วต้องเห็นหลักฐานว่าสำเร็จ ไม่งั้นไม่นับว่าโพสต์แล้ว
  - ขั้น 0 เคลียร์ของค้างจากคลิปก่อน (กล่อง Discard / ป็อปอัป / ฟอร์มที่มีคลิปเก่า)
  - ขั้น 4.5 แก้ไขปก: เปิด editor → ลากเฟรมลง → Save → **ต้องปิดจริง** ไม่งั้นหยุดคลิปนี้
  - ขั้น 5 ตั้งเวลา: ตั้งแล้วต้องอ่านค่ากลับมาตรงกัน ไม่งั้นไม่กดโพสต์
  - รันเป็นชุด: เว้นระยะระหว่างคลิป · ข้ามไฟล์ที่โพสต์ไปแล้ว · ลิมิตต่อ 24 ชม.
  - ลบคลิปที่โพสต์แล้วจากหน้า Posts โดยข้ามคลิปที่ปักหมุดเสมอ

ต่างจากของเดิมตรงการคลิก/ลาก: extension ต้องปลอม PointerEvent เอง (ใส่ buttons:1
ให้ overlay ปกยอมขยับ) ที่นี่ใช้เมาส์จริงของ Playwright ซึ่งเบราว์เซอร์ออกอีเวนต์ให้
ครบเองอยู่แล้ว จึงไม่ต้องปลอม
"""

from __future__ import annotations

import json
import re
import shutil
import time
from datetime import datetime, timedelta
from pathlib import Path

UPLOAD_URL = "https://www.tiktok.com/tiktokstudio/upload"
POSTS_URL = "https://www.tiktok.com/tiktokstudio/content"

UPLOAD_ACCEPT_SECONDS = 20      # รอ editor โผล่หลังส่งไฟล์
PROCESS_TIMEOUT_SECONDS = 180   # รอ TikTok ประมวลผลวิดีโอ
POST_VERIFY_SECONDS = 30        # รอหลักฐานว่าโพสต์สำเร็จ
DISABLED_WAIT_SECONDS = 15      # รอปุ่มโพสต์เลิก disabled
UPLOAD_ATTEMPTS = 3
POST_ATTEMPTS = 3
TAG_SUGGESTION_SECONDS = 4


PRODUCT_DIALOG_SECONDS = 6
PRODUCT_SEARCH_WAIT = 4
PRODUCT_VERIFY_SECONDS = 10
PRODUCT_ATTEMPTS = 2

# ---- ขั้น 0 เคลียร์ของค้าง / รีเซ็ตฟอร์ม
RESET_ATTEMPTS = 3
RESET_FRESH_SECONDS = 6
DISMISS_ROUNDS = 3

# ---- ขั้น 4.5 แก้ไขปก
COVER_OPEN_ATTEMPTS = 3
COVER_OPEN_SECONDS = 3.5
COVER_CLOSE_SECONDS = 6
COVER_DRAG_FROM = 0.30   # เริ่มลากที่ 30% ของความสูงรูปปก
COVER_DRAG_TO = 0.78     # ลากลงไปถึง 78% (~ครึ่งคลิป) ตามค่าที่ใช้จริงในของเดิม

# ---- ขั้น 5 ตั้งเวลา
SCHEDULE_ATTEMPTS = 2

# ---- รันเป็นชุด
DAY_LIMIT_DEFAULT = 150          # คลิปต่อ 24 ชม. (ค่าเดิมของ extension)
DAY_WINDOW_SECONDS = 24 * 3600
BATCH_DELAY_SECONDS = 20
POSTED_HISTORY_MAX = 5000        # กันไฟล์ประวัติบวม

# ---- ลบคลิปที่โพสต์แล้ว
DELETE_MAX = 300
DELETE_FAIL_STREAK = 3           # ล้มเหลวติดกันเท่านี้ = หยุดเพื่อความปลอดภัย

STATE_FILE = Path(__file__).resolve().parent / "data" / "tiktok_state.json"
# ข้อความบนป้ายสินค้าที่ใช้ยืนยันว่าเพิ่มสำเร็จ (ตัด 12 ตัวแรกกันโดนตัดคำ)
DEFAULT_PRODUCT_TEXT = "จิ้มที่นี่เลย"

# 5 ช่องเหมือนระบบเดิม — แต่ละช่องเก็บโค้ด/แฮชแท็ก/รหัสสินค้าแยกกัน
SLOT_COUNT = 5
SLOTS_FILE = Path(__file__).resolve().parent / "data" / "tiktok_slots.json"


def empty_slots() -> list[dict]:
    return [
        {"on": index == 0, "code": "", "tags": "", "pid": "", "ptxt": ""}
        for index in range(SLOT_COUNT)
    ]


def load_slots() -> list[dict]:
    """อ่านค่า 5 ช่องที่ผู้ใช้กรอกไว้ (โครงเดียวกับ S.models ของ extension เดิม)"""
    try:
        data = json.loads(SLOTS_FILE.read_text(encoding="utf-8"))
        slots = data.get("slots") if isinstance(data, dict) else data
        if isinstance(slots, list) and slots:
            merged = empty_slots()
            for index, slot in enumerate(slots[:SLOT_COUNT]):
                merged[index].update(
                    {k: slot.get(k, merged[index][k]) for k in merged[index]}
                )
            return merged
    except (OSError, ValueError):
        pass
    return empty_slots()


def save_slots(slots: list[dict]) -> None:
    SLOTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    temporary = SLOTS_FILE.with_suffix(".tmp")
    temporary.write_text(
        json.dumps({"slots": slots}, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temporary.replace(SLOTS_FILE)


def slot_for(code: str) -> dict | None:
    """หาช่องที่เปิดอยู่และโค้ดตรงกับชื่อรุ่น/สินค้า ถ้าไม่ระบุโค้ดใช้ช่องแรกที่เปิด"""
    slots = load_slots()
    if code:
        for slot in slots:
            if slot["on"] and slot["code"] and slot["code"].lower() in code.lower():
                return slot
    for slot in slots:
        if slot["on"]:
            return slot
    return None


PRODUCT_VERIFY_JS = r"""
(chip) => {
  const CAPTION_SEL = '[contenteditable="true"], .DraftEditor-root, [data-e2e="caption-input"]';
  const norm = (s) => (s || '').replace(/\s+/g, ' ').trim();
  if (!chip) return false;
  for (const el of document.querySelectorAll('span, div, p, a, label')) {
    if (el.children.length !== 0) continue;
    if (el.closest(CAPTION_SEL)) continue;   // กันแฮชแท็กที่พิมพ์ไปทำให้ผ่านทั้งที่ยังไม่ได้เพิ่ม
    if (el.offsetParent === null) continue;
    if (norm(el.textContent).includes(chip)) return true;
  }
  return false;
}
"""


class TikTokError(RuntimeError):
    """โพสต์ไม่สำเร็จ"""


class TikTokNeedsLogin(TikTokError):
    """ยังไม่ได้ล็อกอิน TikTok ในโปรไฟล์นี้"""


# ตรวจสภาพหน้า — ยกเงื่อนไขมาจาก ttp-dom.js ตรงตัว
STATE_JS = r"""
(() => {
  const norm = (s) => (s || '').replace(/\s+/g, ' ').trim();
  const isVisible = (el) => {
    if (!el || el.offsetParent === null) return false;
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  };
  const leafHasText = (list) => {
    for (const el of document.querySelectorAll('span, div, p, a, h1, h2, h3, label')) {
      if (el.children.length !== 0 || !isVisible(el)) continue;
      const t = norm(el.textContent);
      if (list.some((x) => t.toLowerCase().includes(x.toLowerCase()))) return true;
    }
    return false;
  };
  // ฟอร์มยังว่าง (ยังไม่ได้ใส่ไฟล์) — ข้อความ "Select video"/"เลือกวิดีโอ" ยังอยู่
  const isFresh = Array.from(document.querySelectorAll('*')).some(
    (el) => el.children.length === 0 && /Select video|เลือกวิดีโอ/i.test(norm(el.textContent))
  );
  const findPostBtn = (type) => {
    const d = document.querySelector('[data-e2e="post_video_button"]');
    if (d) return d;
    for (const b of document.querySelectorAll('button')) {
      const t = norm(b.textContent).toLowerCase();
      if (type === 'schedule' && (t === 'schedule' || t === 'ตั้งเวลา')) return b;
      if (type === 'post' && (t === 'post' || t === 'โพสต์')) return b;
    }
    return null;
  };
  const postBtn = findPostBtn('post');
  const captionEl = document.querySelector(
    '[data-e2e="caption-input"], .DraftEditor-root [contenteditable="true"], [contenteditable="true"]'
  );
  const posted =
    !/\/tiktokstudio\/upload/.test(location.pathname) ||
    isFresh ||
    leafHasText([
      'Your video has been uploaded', 'Your videos are being uploaded',
      'Video published', 'Video scheduled', 'has been scheduled',
      'Manage your posts', 'Upload another video',
      'อัปโหลดวิดีโอของคุณแล้ว', 'วิดีโอของคุณได้รับการอัปโหลด',
      'ตั้งเวลาวิดีโอแล้ว', 'อัปโหลดวิดีออื่น', 'อัปโหลดวิดีโออื่น',
    ]);
  return {
    url: location.href,
    isFresh,
    hasPostBtn: !!postBtn,
    postEnabled: !!postBtn && !postBtn.disabled &&
      postBtn.getAttribute('aria-disabled') !== 'true',
    hasCaption: !!captionEl,
    captionText: captionEl ? norm(captionEl.textContent || captionEl.value || '') : '',
    uploadFailed: leafHasText([
      'อัปโหลดไม่สำเร็จ', 'ไม่สามารถอัปโหลด', 'Upload failed', "couldn't be uploaded",
    ]),
    // ฟอร์มรับไฟล์แล้ว = ไม่ใช่ฟอร์มว่าง และมีปุ่มโพสต์หรือช่องแคปชันโผล่
    accepted: !isFresh && (!!postBtn || !!captionEl),
    posted,
    signedOut: /\/login/.test(location.pathname) ||
      leafHasText(['Log in to TikTok', 'เข้าสู่ระบบ TikTok']),
    hasScheduleBtn: !!findPostBtn('schedule'),
    // มี dialog ของ TikTok เปิดค้างอยู่ไหม — เช็คเฉพาะ selector มาตรฐานและกล่องที่ใหญ่พอ
    // ไม่ใช้ fallback แรงๆ ที่อาจไปจับแถบ fixed ปกติของหน้าแล้วปิดวนไม่จบ
    dialogOpen: Array.from(document.querySelectorAll(
      '[role="dialog"], [aria-modal="true"], [class*="modal" i], [class*="dialog" i], [class*="popup" i]'
    )).some((el) => {
      const r = el.getBoundingClientRect();
      return r.width > 200 && r.height > 100;
    }),
    // หน้าต่าง Edit cover เปิดอยู่ไหม (ค้างอยู่ = กดปุ่มโพสต์ไม่ได้)
    coverOpen: !!document.querySelector(
      '.ScreenGestureOverlay__root, .FramePicker__root'
    ),
  };
})()
"""


# หากล่องปกที่คลิกแล้วเปิด editor — .cover-container คือตัวที่ยืนยันแล้วว่าใช่
# ไม่เจอค่อยไล่จากคำว่า "Edit cover" ขึ้นไปหา ancestor ที่ cursor เป็น pointer
COVER_BOX_JS = r"""
() => {
  const norm = (s) => (s || '').replace(/\s+/g, ' ').trim();
  let box = document.querySelector('.cover-container') ||
            document.querySelector('.edit-container');
  if (!box) {
    let label = null;
    for (const el of document.querySelectorAll('span, div, p, a, label')) {
      if (el.children.length !== 0) continue;
      if (['Edit cover', 'แก้ไขปก'].includes(norm(el.textContent))) { label = el; break; }
    }
    if (label) {
      let node = label;
      for (let i = 0; i < 4 && node; i++) {
        if (getComputedStyle(node).cursor === 'pointer') box = node;
        node = node.parentElement;
      }
      box = box || label;
    }
  }
  if (!box) return null;
  box.setAttribute('data-ttp-cover', '1');
  box.scrollIntoView({ block: 'center' });
  return true;
}
"""


# ตั้งค่าช่อง date/time แบบที่ React ยอมรับ — ใช้เมื่อ fill() ธรรมดาไม่ติด
# (React จำค่าเดิมไว้ใน node ถ้าเซ็ต .value ตรงๆ มันจะมองว่าไม่มีอะไรเปลี่ยน)
SET_REACT_VALUE_JS = r"""
([selector, value]) => {
  const el = document.querySelector(selector);
  if (!el) return false;
  const proto = Object.getPrototypeOf(el);
  const setter = Object.getOwnPropertyDescriptor(proto, 'value')?.set;
  if (setter) setter.call(el, value); else el.value = value;
  el.dispatchEvent(new Event('input', { bubbles: true }));
  el.dispatchEvent(new Event('change', { bubbles: true }));
  return el.value === value;
}
"""


# ติดป้ายแถวโพสต์ในหน้า Posts เพื่อให้ Playwright คลิกด้วยเมาส์จริงได้
# (คืนแค่ข้อมูล ไม่คลิกเอง — การคลิกจาก JS ทำให้เมนู "..." ไม่ตอบสนอง)
POST_ROWS_JS = r"""
() => {
  const norm = (s) => (s || '').replace(/\s+/g, ' ').trim();
  const isPinned = (row) => {
    for (const el of row.querySelectorAll('span, div, p')) {
      if (el.children.length > 2) continue;
      // ตัดช่องว่าง/ไอคอนออกก่อนเทียบ ป้ายอาจเป็น "📌 Pinned" หรือ <svg>+"Pinned"
      const t = el.textContent.replace(/[\s\u{1F300}-\u{1FAFF}\u{2000}-\u{27BF}️]/gu, '');
      if (t === 'Pinned' || t === 'ปักหมุด' || t === 'ปักหมุดแล้ว') return true;
    }
    return false;
  };
  document.querySelectorAll('[data-ttp-row]').forEach((el) => {
    el.removeAttribute('data-ttp-row');
  });
  document.querySelectorAll('[data-ttp-more]').forEach((el) => {
    el.removeAttribute('data-ttp-more');
  });
  const links = Array.from(document.querySelectorAll('a[href*="/video/"]'));
  const rows = [];
  const seen = new Set();
  for (const link of links) {
    let row = link;
    for (let i = 0; i < 12 && row; i++) {
      const r = row.getBoundingClientRect();
      if (r.height > 60 && r.height < 190 && r.width > 500 && row.querySelector('button')) break;
      row = row.parentElement;
    }
    if (!row || seen.has(row)) continue;
    seen.add(row);
    const buttons = Array.from(row.querySelectorAll('button'))
      .filter((b) => b.getBoundingClientRect().width > 0)
      .sort((a, b) => a.getBoundingClientRect().left - b.getBoundingClientRect().left);
    const more = buttons[buttons.length - 1];   // ปุ่ม "..." อยู่ขวาสุดของแถว
    const index = rows.length;
    row.setAttribute('data-ttp-row', String(index));
    if (more) more.setAttribute('data-ttp-more', String(index));
    rows.push({
      index,
      id: (link.getAttribute('href').match(/video\/(\d+)/) || [])[1] || '',
      pinned: isPinned(row),
      hasMore: !!more,
      caption: norm(link.textContent).slice(0, 45),
    });
  }
  return rows;
}
"""


class TikTokPoster:
    def __init__(self, page, log=print):
        self.page = page
        self.log = log

    def state(self) -> dict:
        return self.page.evaluate(STATE_JS)

    def _wait_state(self, key: str, timeout_s: float, poll: float = 0.5) -> bool:
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            if self.state().get(key):
                return True
            time.sleep(poll)
        return False

    # ------------------------------------------------------------- ขั้นตอน

    def open_upload(self) -> None:
        self.page.goto(UPLOAD_URL, wait_until="domcontentloaded", timeout=90_000)
        time.sleep(3)
        state = self.state()
        if state["signedOut"]:
            raise TikTokNeedsLogin(
                "ยังไม่ได้ล็อกอิน TikTok ในโปรไฟล์นี้ — รัน `flow_worker.py login-tiktok` ก่อน"
            )

    def upload(self, video_path: Path) -> None:
        """ส่งไฟล์เข้าฟอร์ม แล้วรีเช็คว่าฟอร์มรับจริง (ไม่เดาจากการส่งผ่าน)"""
        if not video_path.is_file():
            raise TikTokError(f"ไม่มีไฟล์ {video_path}")
        time.sleep(2)
        for attempt in range(1, UPLOAD_ATTEMPTS + 1):
            if attempt > 1:
                self.log(f"  ฟอร์มยังไม่รับไฟล์ — ลองใหม่ ({attempt}/{UPLOAD_ATTEMPTS})")
            sent = False
            # ห้ามยัดไฟล์ลง input แบบเลือกโฟลเดอร์
            for selector in (
                'input[type="file"][accept*="video"]',
                'input[type="file"][accept*="mp4"]',
                'input[type="file"]',
            ):
                inputs = self.page.locator(selector)
                for index in range(inputs.count()):
                    item = inputs.nth(index)
                    try:
                        if item.get_attribute("webkitdirectory") is not None:
                            continue
                        item.set_input_files(str(video_path))
                        sent = True
                        break
                    except Exception:
                        continue
                if sent:
                    break
            if not sent:
                time.sleep(1.5)
                continue
            self.log("  ส่งไฟล์เข้าฟอร์มแล้ว — รอฟอร์มรับไฟล์")
            if self._wait_state("accepted", UPLOAD_ACCEPT_SECONDS):
                self.log("  ฟอร์มรับไฟล์แล้ว")
                time.sleep(2.5)
                return
        raise TikTokError(
            f"อัปโหลดไม่สำเร็จ — ฟอร์มไม่รับไฟล์ (ลองแล้ว {UPLOAD_ATTEMPTS} ครั้ง)"
        )

    def wait_ready(self) -> None:
        """รอจนปุ่มโพสต์กดได้ = วิดีโอประมวลผลเสร็จจริง"""
        self.log("  รอ TikTok ประมวลผลวิดีโอ")
        start = time.time()
        last_note = 0.0
        while time.time() - start < PROCESS_TIMEOUT_SECONDS:
            state = self.state()
            # ฟ้องล้มเหลวแล้วไม่ต้องรอจนหมดเวลา
            if state["uploadFailed"]:
                raise TikTokError("TikTok แจ้งว่าอัปโหลดล้มเหลว")
            if state["postEnabled"]:
                self.log(f"  วิดีโอพร้อม ({time.time() - start:.0f} วิ)")
                return
            waited = time.time() - start
            if waited - last_note >= 30:
                self.log(f"    ยังประมวลผลอยู่ ({waited:.0f} วิ)")
                last_note = waited
            time.sleep(2)
        raise TikTokError(f"วิดีโอไม่พร้อมภายใน {PROCESS_TIMEOUT_SECONDS} วิ")

    def _caption_box(self):
        return self.page.locator(
            '[data-e2e="caption-input"], .DraftEditor-root [contenteditable="true"], '
            '[contenteditable="true"]'
        ).first

    def _type_tag(self, box, tag: str) -> None:
        box.click()
        time.sleep(0.4)
        self.page.keyboard.type(tag, delay=60)
        time.sleep(1.0)
        # เลือกจากรายการ suggestion ถ้ามี ไม่งั้นเคาะ space ปิดท้าย
        suggestion = self.page.locator(
            '[class*="mention"] [class*="item"], [class*="hashtag-sug"], [class*="list-item"]'
        ).first
        try:
            suggestion.wait_for(state="visible", timeout=TAG_SUGGESTION_SECONDS * 1000)
            suggestion.click()
            self.log(f"    เลือก {tag}")
        except Exception:
            self.page.keyboard.type(" ", delay=30)
        time.sleep(0.4)

    def set_caption(self, caption: str = "", tags: list[str] | None = None) -> None:
        """พิมพ์แคปชันแล้วต่อด้วยแฮชแท็ก พร้อมตรวจซ้ำเติมตัวที่ขาด"""
        box = self._caption_box()
        if not box.count():
            self.log("  ไม่พบช่องแคปชัน — ข้ามขั้นนี้")
            return
        box.click()
        time.sleep(0.4)
        if caption:
            self.page.keyboard.type(caption, delay=25)
            self.page.keyboard.type(" ", delay=30)

        wanted = [t if t.startswith("#") else f"#{t}" for t in (tags or []) if t.strip()]
        for tag in wanted:
            self._type_tag(box, tag)

        # รีเช็ค: แท็กต้องครบ ขาดก็พิมพ์ซ้ำเฉพาะตัวที่ขาด สูงสุด 2 รอบ
        for _ in range(2):
            text = self.state()["captionText"].lower()
            missing = [t for t in wanted if t[1:].lower() not in text]
            if not missing:
                if wanted:
                    self.log(f"  แฮชแท็กครบ {len(wanted)} ตัว")
                return
            self.log(f"  แฮชแท็กขาด {len(missing)} ตัว — พิมพ์ซ้ำ")
            for tag in missing:
                self._type_tag(box, " " + tag)
        still = [
            t for t in wanted if t[1:].lower() not in self.state()["captionText"].lower()
        ]
        if still:
            # ไม่บล็อกการโพสต์ ตามพฤติกรรมเดิม
            self.log(f"  แฮชแท็กยังขาด {' '.join(still)} — ไปต่อ")

    # -------------------------------------------------------- ผูกสินค้า (pid)

    def _dialog(self):
        """ป็อปอัปบนสุด — ทุกขั้นของการเพิ่มสินค้าต้องทำในนี้เท่านั้น"""
        return self.page.locator(
            '[role="dialog"], [role="alertdialog"]'
        ).last

    def _attach_product_once(self, pid: str, ptxt: str) -> bool:
        # 4-1 หาปุ่ม "+ เพิ่ม" ใต้หัวข้อ "เพิ่มลิงก์"
        self.log("    หาปุ่ม + เพิ่ม ใต้ 'เพิ่มลิงก์'")
        add_button = self.page.get_by_role(
            "button", name=re.compile(r"^\s*\+?\s*(เพิ่ม|Add)\s*$", re.I)
        )
        if not add_button.count():
            self.log("    ไม่พบปุ่ม + เพิ่ม")
            return False
        # ของเดิมเลือก "ตัวสุดท้าย" เพราะอยู่ล่างสุดใกล้ส่วนเพิ่มลิงก์
        add_button.last.click()
        time.sleep(1.8)

        dialog = self._dialog()
        try:
            dialog.wait_for(state="visible", timeout=PRODUCT_DIALOG_SECONDS * 1000)
        except Exception:
            self.log("    ไม่พบป็อปอัป 'เพิ่มลิงก์'")
            return False

        # 4-2 กด "ถัดไป" (ประเภทลิงก์เป็นสินค้าอยู่แล้ว)
        next_button = dialog.get_by_role(
            "button", name=re.compile(r"^\s*(ถัดไป|Next)\s*$", re.I)
        )
        if next_button.count():
            next_button.first.click()
            time.sleep(2.4)
            dialog = self._dialog()

        # 4-3 ค้นหาด้วย Product ID ในช่องค้นหาของป็อปอัป
        self.log(f"    ค้นหา Product ID {pid}")
        search = dialog.locator('input[type="text"], input:not([type])').first
        if not search.count():
            self.log("    ไม่พบช่องค้นหาสินค้าในป็อปอัป")
            return False
        search.click()
        search.fill("")
        search.type(pid, delay=40)
        time.sleep(0.7)
        self.page.keyboard.press("Enter")
        time.sleep(PRODUCT_SEARCH_WAIT)

        # 4-4 เลือกแถวสินค้า — กดที่วงกลม radio ซ้ายสุดของแถว
        dialog = self._dialog()
        row = dialog.locator(
            f'[class*="item" i]:has-text("{pid}"), [class*="product" i]:has-text("{pid}"), '
            f'[class*="row" i]:has-text("{pid}"), li:has-text("{pid}")'
        ).first
        if not row.count():
            row = dialog.locator(
                '[class*="item" i], [class*="product" i], [class*="row" i], li'
            ).first
            if row.count():
                self.log("    ไม่เจอ ID ตรง ใช้ผลลัพธ์แรก")
        if not row.count():
            self.log("    ไม่พบแถวสินค้าในผลลัพธ์")
            return False
        box = row.bounding_box()
        if not box or box["width"] < 250:
            self.log("    แถวสินค้าเล็กผิดปกติ ข้าม")
            return False
        row.scroll_into_view_if_needed()
        time.sleep(0.5)
        row.click(position={"x": 30, "y": box["height"] / 2})
        time.sleep(1.0)

        # 4-5 ยืนยันในป็อปอัป
        for label in (r"^\s*(เพิ่ม|Add|ยืนยัน|Confirm|เสร็จสิ้น|Done)\s*$",):
            confirm = self._dialog().get_by_role("button", name=re.compile(label, re.I))
            if confirm.count():
                confirm.last.click()
                break
        time.sleep(2.0)
        return True

    def attach_product(self, pid: str, ptxt: str = "") -> bool:
        """ผูกสินค้าเข้าโพสต์ด้วย Product ID

        รีเช็คว่าเพิ่มสำเร็จจริงจากป้ายสินค้าที่โผล่บนหน้า **นอกช่องแคปชัน**
        (ถ้านับรวมช่องแคปชันด้วย แฮชแท็กที่พิมพ์ไปอาจบังเอิญตรงกับข้อความป้าย
        แล้วรีเช็คผ่านทั้งที่สินค้ายังไม่ถูกเพิ่ม)
        """
        if not pid:
            return False
        chip = (ptxt or DEFAULT_PRODUCT_TEXT).strip()[:12]
        for attempt in range(1, PRODUCT_ATTEMPTS + 1):
            self.log(f"  ผูกสินค้า {pid}{'' if attempt == 1 else f' (ครั้งที่ {attempt})'}")
            try:
                self._attach_product_once(pid, chip)
            except Exception as error:
                self.log(f"    ผิดพลาด: {error}")
            deadline = time.time() + PRODUCT_VERIFY_SECONDS
            while time.time() < deadline:
                if self.page.evaluate(PRODUCT_VERIFY_JS, chip):
                    self.log("  ผูกสินค้าสำเร็จ (ยืนยันจากป้ายบนหน้า)")
                    return True
                time.sleep(0.7)
            self.log("  ยังไม่เห็นป้ายสินค้า")
        self.log("  ผูกสินค้าไม่สำเร็จ — โพสต์ต่อโดยไม่มีลิงก์สินค้า")
        return False

    # ------------------------------------------------- ขั้น 0 เคลียร์ของค้าง

    def _click_by_texts(self, texts: list[str]) -> bool:
        """กดปุ่มที่ข้อความ **ตรงตัว** กับตัวใดตัวหนึ่งในรายการ

        ต้องตรงตัวไม่ใช่ contains — คำว่า "ปิด" ไปโผล่ในปุ่มอื่นได้ง่าย
        แล้วจะกดผิดปุ่มโดยไม่รู้ตัว
        """
        pattern = re.compile(
            r"^\s*(" + "|".join(re.escape(t) for t in texts) + r")\s*$", re.I
        )
        button = self.page.get_by_role("button", name=pattern)
        for index in range(button.count()):
            item = button.nth(index)
            try:
                if item.is_visible():
                    item.click(timeout=4000)
                    return True
            except Exception:
                continue
        return False

    def click_discard_if_any(self) -> bool:
        """เจอกล่อง "Discard this post?" ให้กดทิ้งคลิปเก่า

        ต้องกด Discard เท่านั้น — "Not now" จะเก็บคลิปเก่าไว้ในฟอร์ม
        แล้วคลิปถัดไปจะอัปโหลดทับไม่ได้
        """
        if self._click_by_texts(["Discard", "Leave", "ละทิ้ง", "ออกจากหน้านี้"]):
            self.log("    เจอกล่อง Discard — กดทิ้งคลิปเก่า")
            return True
        return False

    def dismiss_dialogs(self) -> bool:
        """ปิดป็อปอัปที่ค้าง (ปุ่มยกเลิก/ปิด → Escape) คืน True ถ้าปิดหมดแล้ว"""
        for _ in range(DISMISS_ROUNDS):
            if not self.state()["dialogOpen"]:
                return True
            if not self._click_by_texts(["Cancel", "ยกเลิก", "Close", "ปิด", "✕", "×"]):
                self.page.keyboard.press("Escape")
            time.sleep(0.7)
        return not self.state()["dialogOpen"]

    def reset_upload_form(self) -> bool:
        """พาฟอร์มกลับเป็นหน้าอัปโหลดสดโดยไม่ reload

        ของเดิมย้ำไว้ว่าห้าม reload ถ้าเลี่ยงได้ เพราะ extension จะเสียสิทธิ์โฟลเดอร์
        ที่นี่ไม่มีปัญหานั้น แต่ยังเลี่ยงอยู่ดีเพราะ reload ช้ากว่าหลายวินาทีต่อคลิป
        """
        self.log("  รีเซ็ตฟอร์มอัปโหลด")
        for attempt in range(1, RESET_ATTEMPTS + 1):
            # โมดัล "โพสต์สำเร็จ" ค้างอยู่ → ปุ่มนี้พาไปฟอร์มสดตรงๆ
            self._click_by_texts(["Upload another video", "อัปโหลดวิดีโออื่น"])
            time.sleep(0.8)
            if not self.state()["isFresh"]:
                upload = self.page.get_by_role(
                    "button", name=re.compile(r"^\s*\+?\s*(Upload|อัปโหลด)\s*$", re.I)
                )
                clicked = False
                for index in range(upload.count()):
                    item = upload.nth(index)
                    try:
                        box = item.bounding_box()
                        # ปุ่ม "+ Upload" ของ TikTok อยู่มุมซ้ายบนเสมอ
                        # ถ้าไม่จำกัดตำแหน่งจะไปโดนปุ่มอัปโหลดอื่นในหน้า
                        if box and box["y"] < 240 and box["x"] < 320:
                            item.click(timeout=4000)
                            clicked = True
                            break
                    except Exception:
                        continue
                if not clicked:
                    self.page.goto(
                        UPLOAD_URL, wait_until="domcontentloaded", timeout=90_000
                    )
            # ระหว่างรอฟอร์มสด ต้องคอยจับกล่อง Discard ตลอด ไม่ใช่เช็คครั้งเดียว
            # (TikTok ขึ้นกล่องช้ากว่าที่รอบแรกจะเช็คทัน แล้วจะรอเก้อทั้งรอบ)
            deadline = time.time() + RESET_FRESH_SECONDS
            while time.time() < deadline:
                if self.state()["isFresh"]:
                    self.log("  ฟอร์มอัปโหลดพร้อมแล้ว")
                    return True
                if self.click_discard_if_any():
                    time.sleep(0.5)
                time.sleep(0.3)
            self.log(f"  ยังไม่สด — ลองรีเซ็ตใหม่ ({attempt}/{RESET_ATTEMPTS})")
        self.log("  รีเซ็ตฟอร์มไม่สำเร็จ")
        return False

    def prepare_form(self) -> None:
        """ขั้น 0 — เคลียร์สถานะค้างจากคลิปก่อนหน้าก่อนเริ่มอัปโหลด

        เช็คกล่อง Discard **ก่อน** ปิดป็อปอัปทั่วไปเสมอ: ตอนนี้คลิปปัจจุบันยังไม่ถูก
        อัปโหลด อะไรที่ค้างอยู่ในฟอร์มคือของรอบก่อนแน่นอน กด Discard จบในทีเดียว
        (ถ้าปล่อยให้ Escape จะปิดแค่กล่อง คลิปเก่ายังอยู่ในฟอร์ม)
        """
        if self.click_discard_if_any():
            time.sleep(0.8)
        state = self.state()
        if state["dialogOpen"]:
            self.log("  พบป็อปอัปค้าง — ปิดก่อนเริ่ม")
            self.dismiss_dialogs()
            state = self.state()
        if not state["isFresh"] and state["hasPostBtn"]:
            self.log("  ฟอร์มมีคลิปเก่าค้าง — รีเซ็ตก่อนอัปโหลด")
            if not self.reset_upload_form():
                raise TikTokError("รีเซ็ตฟอร์มก่อนอัปโหลดไม่สำเร็จ")

    # --------------------------------------------------- ขั้น 4.5 แก้ไขปก

    def edit_cover(self) -> bool:
        """เปิดหน้าแก้ไขปก → ลากเฟรมลง → Save → ยืนยันว่าปิดจริง

        ที่ต้องยืนยันว่าปิด เพราะหน้าต่างนี้ค้างอยู่จะบังปุ่มโพสต์จนกดไม่ได้
        แล้วจะไปตายที่ขั้นถัดไปโดยไม่รู้ว่าสาเหตุอยู่ตรงนี้ — ปิดไม่ได้ = หยุดคลิปนี้
        """
        self.log("  แก้ไขปก")
        time.sleep(0.8)
        if not self.page.evaluate(COVER_BOX_JS):
            self.log("  ไม่พบกล่องปก — ข้ามขั้นนี้")
            return False
        cover = self.page.locator('[data-ttp-cover="1"]').first
        time.sleep(0.5)

        opened = False
        for attempt in range(1, COVER_OPEN_ATTEMPTS + 1):
            try:
                cover.click(timeout=5000)
            except Exception as error:
                self.log(f"    กดกล่องปกไม่ได้: {error}")
            deadline = time.time() + COVER_OPEN_SECONDS
            while time.time() < deadline:
                if self.state()["coverOpen"]:
                    opened = True
                    break
                time.sleep(0.3)
            if opened:
                break
            self.log(f"    ยังไม่เปิด — ลองใหม่ ({attempt}/{COVER_OPEN_ATTEMPTS})")
        if not opened:
            self.log("  เปิดหน้าแก้ไขปกไม่ได้ — ข้าม")
            return False

        overlay = self.page.locator(".ScreenGestureOverlay__root").first
        box = overlay.bounding_box() if overlay.count() else None
        if box:
            x = box["x"] + box["width"] / 2
            self.page.mouse.move(x, box["y"] + box["height"] * COVER_DRAG_FROM)
            self.page.mouse.down()
            # ลากเป็นช่วงย่อยๆ ไม่ใช่กระโดดทีเดียว — overlay อ่านตำแหน่งจาก
            # pointermove ระหว่างทาง ถ้ากระโดดจะถือว่าไม่มีการเคลื่อนที่
            steps = 15
            start = box["y"] + box["height"] * COVER_DRAG_FROM
            end = box["y"] + box["height"] * COVER_DRAG_TO
            for index in range(1, steps + 1):
                self.page.mouse.move(x, start + (end - start) * index / steps)
                time.sleep(0.025)
            self.page.mouse.up()
            self.log("    ลากเฟรมปกแล้ว")
        else:
            self.log("    ไม่พบพื้นที่รูปปก — บันทึกปกเดิม")
        time.sleep(1.0)

        if not self._click_by_texts(["Save", "บันทึก"]):
            self.log("    ไม่พบปุ่ม Save")
        closed = self._wait_gone("coverOpen", COVER_CLOSE_SECONDS)
        if not closed:
            self.log("    หน้าแก้ไขปกยังไม่ปิด — กด Save/Escape ซ้ำ")
            if not self._click_by_texts(["Save", "บันทึก"]):
                self.page.keyboard.press("Escape")
            closed = self._wait_gone("coverOpen", COVER_CLOSE_SECONDS)
        if not closed:
            raise TikTokError("ปิดหน้าแก้ไขปกไม่ได้ — หยุดคลิปนี้ (กันกดโพสต์ไม่ได้)")
        self.log("  บันทึกปกและปิดหน้าแก้ไขปกแล้ว")
        time.sleep(1.2)
        return True

    # ------------------------------------------------------ ขั้น 5 ตั้งเวลา

    def schedule(self, when: datetime) -> None:
        """ตั้งเวลาโพสต์ แล้วอ่านค่ากลับมาตรวจว่าตรงจริง

        ใช้เวลาเครื่อง ไม่ใช่ UTC — เวลาไทยก่อน 07:00 จะกลายเป็นวันก่อนหน้าถ้าแปลง UTC
        ตั้งไม่สำเร็จต้องไม่กดโพสต์ ไม่งั้นคลิปจะออกทันทีแทนที่จะรอเวลา
        """
        date_text = when.strftime("%Y-%m-%d")
        time_text = when.strftime("%H:%M")
        self.log(f"  ตั้งเวลา {date_text} {time_text}")
        for attempt in range(1, SCHEDULE_ATTEMPTS + 1):
            radio = self.page.locator('input[type="radio"][value*="schedule"]').first
            try:
                if radio.count():
                    radio.click(timeout=4000)
                elif not self._click_by_texts(["Schedule", "ตั้งเวลา"]):
                    self.log("    ไม่พบตัวเลือกตั้งเวลา")
            except Exception as error:
                self.log(f"    กดตัวเลือกตั้งเวลาไม่ได้: {error}")
            time.sleep(1.2)

            for selector, value in (
                ('input[type="date"]', date_text),
                ('input[type="time"]', time_text),
            ):
                field = self.page.locator(selector).first
                if not field.count():
                    continue
                try:
                    field.fill(value, timeout=4000)
                except Exception:
                    # fill ไม่ติดกับบางคอมโพเนนต์ของ React — เซ็ตผ่าน native setter แทน
                    self.page.evaluate(SET_REACT_VALUE_JS, [selector, value])
            time.sleep(0.8)

            got_date = self._field_value('input[type="date"]')
            got_time = self._field_value('input[type="time"]')
            if got_date == date_text and got_time == time_text:
                self.log("  ตั้งเวลาแล้ว (ตรวจซ้ำผ่าน)")
                return
            self.log(
                f"    ค่าที่อ่านกลับมาไม่ตรง ({got_date} {got_time}) "
                f"— ลองใหม่ ({attempt}/{SCHEDULE_ATTEMPTS})"
            )
        raise TikTokError("ตั้งเวลาโพสต์ไม่สำเร็จ — ไม่กดโพสต์ (กันโพสต์ผิดเวลา)")

    def _field_value(self, selector: str) -> str:
        field = self.page.locator(selector).first
        if not field.count():
            return ""
        try:
            return field.input_value(timeout=3000)
        except Exception:
            return ""

    def _wait_gone(self, key: str, timeout_s: float, poll: float = 0.3) -> bool:
        """รอจนกว่าเงื่อนไขจะ **หาย** (ตรงข้ามกับ _wait_state)"""
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            if not self.state().get(key):
                return True
            time.sleep(poll)
        return False

    def click_post(self, mode: str = "post") -> None:
        """กดโพสต์แล้วต้องเห็นหลักฐานว่าสำเร็จจริง ไม่งั้นไม่นับว่าโพสต์แล้ว"""
        scheduling = mode == "schedule"
        label = "ตั้งเวลา" if scheduling else "โพสต์"
        button_pattern = (
            re.compile(r"^\s*(schedule|ตั้งเวลา)\s*$", re.I)
            if scheduling
            else re.compile(r"^\s*(post|โพสต์)\s*$", re.I)
        )
        for attempt in range(1, POST_ATTEMPTS + 1):
            self.log(f"  กดปุ่ม{label}{'' if attempt == 1 else f' (ครั้งที่ {attempt})'}")
            time.sleep(1.2)
            state = self.state()
            has_button = state["hasScheduleBtn"] if scheduling else state["hasPostBtn"]
            if not has_button:
                # ปุ่มหาย อาจโพสต์ไปแล้วและ SPA เปลี่ยนหน้า — เช็คหลักฐานก่อนตัดสิน
                if self._wait_state("posted", 8):
                    self.log(f"  {label}สำเร็จ (ยืนยันแล้ว)")
                    return
                raise TikTokError(f"ไม่พบปุ่ม{label}")
            if not state["postEnabled"]:
                self.log("    ปุ่มยัง disabled — รอพร้อม")
                self._wait_state("postEnabled", DISABLED_WAIT_SECONDS)

            button = self.page.get_by_role("button", name=button_pattern).first
            if scheduling or not button.count():
                # ปุ่มตั้งเวลาไม่มี data-e2e ของตัวเอง จับจากข้อความอย่างเดียว
                fallback = self.page.locator('[data-e2e="post_video_button"]').first
                if not scheduling and fallback.count():
                    button = fallback
            try:
                button.click()
            except Exception as error:
                self.log(f"    กดปุ่มไม่ได้: {error}")
            time.sleep(4)

            # popup "โพสต์ต่อหรือไม่" → กด "โพสต์ตอนนี้"
            post_now = self.page.get_by_text(
                re.compile("โพสต์ตอนนี้|Post now", re.I)
            ).first
            try:
                if post_now.count() and post_now.is_visible():
                    self.log('    พบ popup → กด "โพสต์ตอนนี้"')
                    post_now.click()
            except Exception:
                pass

            if self._wait_state("posted", POST_VERIFY_SECONDS, poll=0.7):
                self.log(f"  {label}สำเร็จ (ยืนยันแล้ว)")
                time.sleep(2)
                return
            self.log("  กดแล้วแต่ยังไม่เห็นหลักฐานว่าสำเร็จ — ลองใหม่")
        raise TikTokError(f"กด{label}แล้วยืนยันผลไม่สำเร็จ — ไม่นับว่าโพสต์แล้ว")

    # ------------------------------------------------------------ ทั้งกระบวน

    def post(
        self, video_path: Path, caption: str = "", tags: list[str] | None = None,
        pid: str = "", ptxt: str = "", when: datetime | None = None,
        edit_cover: bool = True, first: bool = True,
    ) -> dict:
        """โพสต์ 1 คลิปครบทุกขั้นตามลำดับของระบบเดิม

        first=False คือคลิปที่ 2 เป็นต้นไปในรอบเดียวกัน — ไม่ต้อง goto ใหม่
        เพราะ TikTok Studio เป็น SPA อยู่แล้ว การโหลดหน้าใหม่เสียเวลาเปล่า
        """
        self.log(f"โพสต์ TikTok: {video_path.name}")
        if first:
            self.open_upload()
        self.prepare_form()                                   # ขั้น 0
        self.upload(video_path)                               # ขั้น 1
        self.wait_ready()                                     # ขั้น 2
        self.set_caption(caption, tags)                       # ขั้น 3
        # ผูกสินค้าหลังใส่แคปชัน ตามลำดับของระบบเดิม
        product_ok = self.attach_product(pid, ptxt) if pid else False   # ขั้น 4
        cover_ok = self.edit_cover() if edit_cover else False           # ขั้น 4.5
        mode = "schedule" if when else "post"
        if when:
            self.schedule(when)                               # ขั้น 5
        self.click_post(mode)                                 # ขั้น 6
        return {
            "ok": True, "video": str(video_path), "caption": caption,
            "tags": tags or [], "pid": pid, "product_attached": product_ok,
            "cover_edited": cover_ok, "mode": mode,
            "scheduled_for": when.isoformat(timespec="minutes") if when else None,
        }


# ==================================================== ประวัติโพสต์ + ลิมิตต่อวัน


class PostHistory:
    """จำว่าไฟล์ไหนโพสต์ไปแล้ว และนับโควตาต่อ 24 ชม.

    ที่ต้องจำชื่อไฟล์: กดเริ่มรอบใหม่ทับของเดิมจะอัปโหลดคลิปเดิมซ้ำ ซึ่งบน TikTok
    คือโพสต์ซ้ำจริงๆ ไม่มีอะไรกันให้ และถ้าเปิดการย้ายไฟล์ไว้ ไฟล์ถูกย้ายออกไปแล้ว
    การอัปโหลดซ้ำจะล้มเหลวแน่นอน
    """

    def __init__(self, path: Path | None = None) -> None:
        # อ่าน STATE_FILE ตอนเรียก ไม่ใช่ตอนนิยาม — ค่า default ของพารามิเตอร์ถูกผูก
        # ตั้งแต่โหลดโมดูล ใครเปลี่ยน STATE_FILE ทีหลังจะไม่มีผลและไปเขียนทับไฟล์จริง
        self.path = path or STATE_FILE
        self.posted: set[str] = set()
        self.day: dict = {"first_ts": None, "count": 0}
        self.load()

    def load(self) -> None:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        self.posted = set(data.get("posted") or [])
        day = data.get("day") or {}
        self.day = {
            "first_ts": day.get("first_ts"),
            "count": int(day.get("count") or 0),
        }

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        names = sorted(self.posted)
        if len(names) > POSTED_HISTORY_MAX:
            names = names[-POSTED_HISTORY_MAX:]
            self.posted = set(names)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(
                {"posted": names, "day": self.day, "updated_at": time.time()},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        temporary.replace(self.path)

    def already_posted(self, name: str) -> bool:
        return name in self.posted

    def mark_posted(self, name: str) -> None:
        if name:
            self.posted.add(name)
            self.save()

    def clear_posted(self) -> int:
        count = len(self.posted)
        self.posted = set()
        self.save()
        return count

    # ------------------------------------------------------------ ลิมิตต่อวัน

    def prune_day(self) -> None:
        """ครบ 24 ชม. จากคลิปแรกแล้วเริ่มนับใหม่"""
        first = self.day.get("first_ts")
        if first and time.time() - first >= DAY_WINDOW_SECONDS:
            self.day = {"first_ts": None, "count": 0}
            self.save()

    def record_post(self) -> None:
        self.prune_day()
        if not self.day.get("first_ts"):
            self.day = {"first_ts": time.time(), "count": 1}
        else:
            self.day["count"] += 1
        self.save()

    def resume_at(self, limit: int) -> float | None:
        """เวลาที่จะโพสต์ต่อได้ ถ้ายังไม่ถึงลิมิตคืน None"""
        self.prune_day()
        first = self.day.get("first_ts")
        if first and self.day["count"] >= limit:
            return first + DAY_WINDOW_SECONDS
        return None


def _wait_for_day_limit(resume_at: float, log, stop) -> bool:
    """รอจนครบ 24 ชม. คืน False ถ้าผู้ใช้สั่งหยุดก่อน

    ไม่รีเซ็ตตัวนับเองตอนออกเพราะถูกสั่งหยุด — ไม่งั้นกดหยุดแล้วเริ่มใหม่
    จะโพสต์ได้อีกเต็มโควตาในหน้าต่างเดียวกัน (prune_day จะรีเซ็ตให้เองเมื่อถึงเวลาจริง)
    """
    until = datetime.fromtimestamp(resume_at).strftime("%d/%m %H:%M")
    log(f"ถึงลิมิตต่อวันแล้ว — รอถึง {until} แล้วโพสต์ต่อ")
    announced = -1
    while time.time() < resume_at:
        if stop():
            return False
        remain = resume_at - time.time()
        minutes = int(remain // 60)
        if minutes != announced and minutes % 30 == 0:
            log(f"  รอลิมิตอีก {int(remain // 3600)} ชม. {minutes % 60} นาที")
            announced = minutes
        time.sleep(15)
    return True


def _move_posted_file(video: Path, destination: Path, log) -> bool:
    """ย้ายคลิปที่โพสต์แล้วออกจากโฟลเดอร์ต้นทาง

    ย้ายหลังยืนยันว่าโพสต์สำเร็จเท่านั้น และความล้มเหลวตรงนี้ต้องไม่ทำให้คลิป
    ที่โพสต์ไปแล้วถูกนับเป็นล้มเหลว (ของเดิมก็แยก try ออกจากกันด้วยเหตุผลเดียวกัน)
    """
    try:
        destination.mkdir(parents=True, exist_ok=True)
        target = destination / video.name
        if target.exists():
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            target = destination / f"{video.stem}-{stamp}{video.suffix}"
        shutil.move(str(video), str(target))
        log(f"  ย้ายไฟล์ไป {target.parent.name}/ แล้ว")
        return True
    except OSError as error:
        log(f"  ย้ายไฟล์ไม่สำเร็จ: {error}")
        return False


def post_batch(
    page,
    videos: list[Path],
    caption: str = "",
    tags: list[str] | None = None,
    pid: str = "",
    ptxt: str = "",
    delay_seconds: float = BATCH_DELAY_SECONDS,
    day_limit: int = DAY_LIMIT_DEFAULT,
    move_to: Path | None = None,
    schedule_from: datetime | None = None,
    schedule_step_minutes: int = 60,
    edit_cover: bool = True,
    log=print,
    stop=lambda: False,
) -> dict:
    """โพสต์หลายคลิปติดกัน — ยกลูปของ extension มาทั้งชุด

    ลำดับเหมือนเดิม: ข้ามไฟล์ที่โพสต์แล้ว → เช็คลิมิตต่อวัน → โพสต์ → จำว่าโพสต์แล้ว
    → ย้ายไฟล์ → รอ → คลิปถัดไป และคลิปที่พังไม่ทำให้ทั้งชุดหยุด
    """
    history = PostHistory()
    poster = TikTokPoster(page, log=log)
    results: list[dict] = []
    done = failed = skipped = 0
    first = True

    for index, video in enumerate(videos):
        if stop():
            log("ผู้ใช้สั่งหยุด")
            break
        if history.already_posted(video.name):
            skipped += 1
            log(f"[{index + 1}/{len(videos)}] ข้าม (โพสต์ไปแล้ว): {video.name}")
            results.append({"video": str(video), "ok": True, "skipped": True})
            continue

        resume_at = history.resume_at(day_limit)
        if resume_at and not _wait_for_day_limit(resume_at, log, stop):
            break

        log(f"[{index + 1}/{len(videos)}] {video.name}")
        when = (
            schedule_from + timedelta(minutes=schedule_step_minutes * len(results))
            if schedule_from
            else None
        )
        try:
            outcome = poster.post(
                video, caption=caption, tags=tags, pid=pid, ptxt=ptxt,
                when=when, edit_cover=edit_cover, first=first,
            )
            first = False
            history.mark_posted(video.name)
            history.record_post()
            done += 1
            log(f"  สำเร็จ (วันนี้ {history.day['count']}/{day_limit})")
            results.append(outcome)
            if move_to:
                _move_posted_file(video, move_to, log)
        except TikTokNeedsLogin:
            raise            # ล็อกอินหลุดแล้วคลิปที่เหลือก็ไปต่อไม่ได้ ไม่ต้องวนให้เสียเวลา
        except TikTokError as error:
            failed += 1
            first = False
            log(f"  ล้มเหลว: {error}")
            results.append({"video": str(video), "ok": False, "error": str(error)})
            # เคลียร์ป็อปอัปที่อาจค้างจากคลิปที่พัง ให้คลิปถัดไปเริ่มได้
            try:
                poster.dismiss_dialogs()
            except Exception:
                pass

        if index < len(videos) - 1 and not stop():
            if delay_seconds > 0:
                log(f"  รอ {delay_seconds:.0f} วินาทีก่อนคลิปถัดไป")
                waited = 0.0
                while waited < delay_seconds and not stop():
                    time.sleep(0.5)
                    waited += 0.5
            # รีเซ็ตฟอร์มเสมอเมื่อยังมีคลิปถัดไป ไม่ผูกกับการรอ — ตั้ง delay เป็น 0
            # ไม่ได้แปลว่าไม่ต้องเคลียร์ฟอร์ม (คลิปถัดไปจะอัปโหลดทับของเดิมไม่ได้)
            if not stop():
                poster.reset_upload_form()

    log(f"จบรอบ: สำเร็จ {done} · ล้มเหลว {failed} · ข้าม {skipped}")
    return {
        "ok": failed == 0, "done": done, "failed": failed, "skipped": skipped,
        "results": results, "day_count": history.day["count"],
    }


# ================================================ ลบคลิปที่โพสต์แล้วจากหน้า Posts


def _goto_posts(page, log) -> bool:
    if page.locator('a[href*="/video/"]').count():
        return True
    page.goto(POSTS_URL, wait_until="domcontentloaded", timeout=90_000)
    deadline = time.time() + 12
    while time.time() < deadline:
        if page.locator('a[href*="/video/"]').count():
            return True
        time.sleep(0.4)
    log("เปิดหน้า Posts ไม่ได้")
    return False


def _delete_one_top_post(page, log) -> dict:
    """ลบโพสต์ล่าสุดที่ **ไม่ได้ปักหมุด** 1 อัน

    คลิปที่ปักหมุดข้ามเสมอ — ผู้ใช้ตั้งใจปักไว้ให้อยู่บนสุด การลบทิ้งกู้กลับมา
    ให้อยู่ที่เดิมไม่ได้
    """
    rows = page.evaluate(POST_ROWS_JS)
    if not rows:
        return {"ok": False, "reason": "ไม่พบโพสต์ในหน้า"}
    target = next((row for row in rows if not row["pinned"]), None)
    if target is None:
        return {"ok": False, "reason": "เหลือแต่คลิปที่ปักหมุด"}
    if not target["hasMore"]:
        return {"ok": False, "reason": "ไม่พบปุ่ม ... ของแถว", "caption": target["caption"]}
    skipped = rows.index(target)
    if skipped:
        log(f"  ข้ามคลิปปักหมุด {skipped} คลิป")

    page.locator(f'[data-ttp-more="{target["index"]}"]').first.click()
    menu_item = page.get_by_text(re.compile(r"^\s*(Delete|ลบ)\s*$")).first
    try:
        menu_item.wait_for(state="visible", timeout=4000)
    except Exception:
        return {"ok": False, "reason": "ไม่พบเมนู Delete", "caption": target["caption"]}
    menu_item.click()

    # กล่องยืนยันของ TikTok มีคำว่า Delete post / กู้คืน อยู่ในเนื้อหา
    dialog = page.locator(
        '[role="dialog"], [class*="TUXModal" i]'
    ).filter(has_text=re.compile(r"Delete post|ลบโพสต์|Recently deleted|กู้คืน|permanently", re.I)).last
    try:
        dialog.wait_for(state="visible", timeout=4000)
    except Exception:
        return {"ok": False, "reason": "ไม่พบกล่องยืนยัน", "caption": target["caption"]}
    confirm = dialog.get_by_role("button", name=re.compile(r"^\s*(Delete|ลบ)\s*$", re.I)).last
    if not confirm.count():
        return {"ok": False, "reason": "ไม่พบปุ่มยืนยันลบ", "caption": target["caption"]}
    confirm.click()

    # ยืนยันว่าหายจริงจาก DOM ไม่ใช่เดาจากการกดผ่าน
    deadline = time.time() + 8
    while time.time() < deadline:
        if not page.locator(f'a[href*="/video/{target["id"]}"]').count():
            return {"ok": True, "caption": target["caption"], "id": target["id"]}
        time.sleep(0.4)
    return {"ok": False, "reason": "กดลบแล้วแต่คลิปยังอยู่", "caption": target["caption"]}


def delete_recent_posts(page, count: int, log=print, stop=lambda: False) -> dict:
    """ลบคลิปล่าสุด N อันออกจาก TikTok (ข้ามคลิปที่ปักหมุดเสมอ)

    ลบทีละอันแล้วรีเฟรชรายการก่อนลบตัวถัดไป — รายการในหน้าเป็น virtual list
    ที่ index เลื่อนหลังลบ ถ้าไม่รีเฟรชจะไปลบผิดตัว
    """
    if count <= 0:
        return {"ok": False, "error": "ต้องระบุจำนวนคลิปที่จะลบ"}
    if count > DELETE_MAX:
        return {"ok": False, "error": f"ลบได้สูงสุด {DELETE_MAX} คลิปต่อครั้ง"}
    if not _goto_posts(page, log):
        return {"ok": False, "error": "เปิดหน้า Posts ไม่ได้"}
    time.sleep(1.2)

    rows = page.evaluate(POST_ROWS_JS)
    pinned = [row for row in rows if row["pinned"]]
    available = [row for row in rows if not row["pinned"]]
    if pinned:
        log(f"พบคลิปปักหมุด {len(pinned)} คลิป — จะข้ามไม่ลบ")
    if not available:
        return {"ok": False, "error": "ไม่มีคลิปที่ลบได้ (ที่เห็นทั้งหมดถูกปักหมุด)"}
    target = min(count, len(available))
    if target < count:
        log(f"มีคลิปที่ลบได้แค่ {target} คลิป (ขอไว้ {count})")

    done = 0
    fail_streak = 0
    deleted: list[str] = []
    for index in range(target):
        if stop():
            log("ผู้ใช้สั่งหยุดลบ")
            break
        outcome = _delete_one_top_post(page, log)
        if outcome["ok"]:
            done += 1
            fail_streak = 0
            deleted.append(outcome.get("caption", ""))
            log(f"[{done}/{target}] ลบแล้ว: {outcome.get('caption', '')}")
        elif outcome["reason"] == "เหลือแต่คลิปที่ปักหมุด":
            log("เหลือแต่คลิปที่ปักหมุด — หยุดลบ")
            break
        else:
            fail_streak += 1
            log(f"ลบไม่สำเร็จ ({outcome['reason']}): {outcome.get('caption', '')}")
            page.keyboard.press("Escape")
            time.sleep(0.5)
            if fail_streak >= DELETE_FAIL_STREAK:
                log(f"ล้มเหลวติดกัน {DELETE_FAIL_STREAK} ครั้ง — หยุดเพื่อความปลอดภัย")
                break
        if index < target - 1 and not stop():
            page.reload(wait_until="domcontentloaded", timeout=60_000)
            time.sleep(1.5)
    log(f"ลบเสร็จ: สำเร็จ {done} (กู้คืนได้ 30 วันใน Recently deleted)")
    return {"ok": done > 0, "deleted": done, "captions": deleted, "skipped_pinned": len(pinned)}
