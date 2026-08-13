"""ตัวขับหน้า Google Flow — พอร์ตมาจาก 2.Extension/8.Auto-gen(stepbystep)/content/flow.js

หลักการพอร์ต
  - **ตรรกะตรวจจับยกมาเป็น JavaScript ชุดเดิม** (ดู DETECT_JS) ไม่เขียนใหม่เป็น
    Python locator เพราะของเดิมผ่านการใช้งานจริงมาแล้ว ทั้งการกันไทล์เก่า
    การแยก policy / unusual activity / audio fail และการกรองรูปจิ๋ว
  - **การพิมพ์/คลิกใช้ Playwright แทน CDP** — input ของ Playwright เป็น trusted
    อยู่แล้ว จึงตัดข้อจำกัดเดิมทิ้งได้ 3 ข้อ:
      1. ไม่ต้องเปิด side panel ค้างไว้ (ไม่มี panel)
      2. ไม่มีแบนเนอร์ "เริ่มการแก้ไขข้อบกพร่อง"
      3. เปิด DevTools ระหว่างรันได้ ไม่ชนกัน

เวลาและกติกา retry ยึดตามตาราง README ของระบบเดิมทุกค่า
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

# ---------------------------------------------------------------- ค่าเวลา (วิ)
# ยกมาจากตาราง "ความหมายของการตั้งค่าเวลา" ใน README ของ 8.Auto-gen(stepbystep)
TIMEOUTS = {
    "page_load": 45,
    "attach_image": 30,
    "gemini_reply": 360,
    "flow_settings": 20,
    "image_per_scene": 300,
    "video_per_scene": 600,
    "download": 120,
}
POLL_IMAGE = 5      # poll ทุก 5 วิ ตอนเจนรูป
POLL_VIDEO = 10     # poll ทุก 10 วิ ตอนเจนวิดีโอ
MAX_IMAGE_TRIES = 3  # เจนรูปซ้ำได้ 3 ครั้ง/ซีน (backoff n×15 วิ)
MAX_VIDEO_TRIES = 2  # เจนวิดีโอซ้ำได้ 2 ครั้ง/ซีน
RETRY_BACKOFF = 15
# Flow แจ้ง Failed บางครั้งทั้งที่งานเสร็จแล้ว — รอแล้วตรวจซ้ำก่อนตัดสินใจเจนใหม่
FAILED_RECHECK_SECONDS = 8
# ช่วงต้นหลังกด Create ที่สัญญาณ "Failed" เชื่อไม่ได้
#
# วัดจากของจริง 11 ส.ค. สองรอบ: สัญญาณ Failed โผล่ที่วินาทีที่ 8 ทั้งที่ไทล์
# กำลังเรนเดอร์อยู่จริง (เห็นกับตาว่าขึ้น 16% และ 48%) ส่วนตัวเลข % ของจริง
# เพิ่งอ่านได้ราววินาทีที่ 30-50 — ถ้าตัดสินก่อนหน้านั้นคือทิ้งงานที่จ่ายเงินไปแล้ว
FAILED_GRACE_SECONDS = 90
# กด Create แล้วรอสัญญาณกี่วินาทีก่อนเปลี่ยนไปใช้วิธีกดแบบถัดไป
# สั้นไปจะเปลี่ยนวิธีทั้งที่วิธีแรกติดแล้ว (กดซ้ำ = เจนซ้ำ = เปลืองเครดิต)
# ยาวไปจะเสียเวลาสะสม 5 ชั้น — 6 วินาทีพอเห็นไทล์ใหม่โผล่
CLICK_CONFIRM_SECONDS = 6
# เพดานเวลาพิมพ์ prompt ลงช่อง (ใช้เฉพาะทางสำรอง) — ค่าปริยายของ Playwright คือ
# 30 วิ ซึ่งไม่พอสำหรับ prompt รวมทุกฉากที่ยาว 3,000–4,000 ตัวอักษร
PROMPT_TYPE_TIMEOUT = 180_000
SETTINGS_ATTEMPTS = 3
# อัปโหลด+ประมวลผลรูปฝั่ง Flow ใช้เวลาได้ถึง 60-90 วิ (วัดจากระบบเดิม)
UPLOAD_WAIT = 120

FLOW_URL = "https://labs.google/fx/tools/flow"
PROJECT_URL_RE = re.compile(r"/fx/(?:[a-z]{2}/)?tools/flow/project/[0-9a-f-]{36}")
# เครดิตคงเหลือในเมนูบัญชี — ยืนยันจากหน้าจริง: link "10020 Google Flow credits"
CREDITS_RE = re.compile(r"([\d,]+)\s*Google Flow credits", re.I)

# ป้ายปุ่มเป็น **ภาษาตามบัญชี Google** ไม่ใช่ตาม URL
#
# ลองบังคับด้วย /fx/en/tools/flow แล้ว Google เด้งกลับเป็น /fx/th/ ทุกครั้ง —
# บัญชีของผู้ใช้ตั้งภาษาไทยไว้ จึงต้องจับสองภาษา ไม่ใช่หวังพึ่ง URL
# (ดำหน้าจริงแล้วได้: ปุ่มสร้าง = "arrow_forward สร้าง", โปรเจกต์ใหม่ = "โปรเจ็กต์ใหม่")
NEW_PROJECT_RE = re.compile(r"New project|Create new|โปรเจ็?กต์ใหม่", re.I)
CREATE_BUTTON_RE = re.compile(r"arrow_forward\s*(?:Create|สร้าง)", re.I)


class FlowError(RuntimeError):
    """ล้มเหลวทั่วไป — retry ได้"""


class PolicyBlocked(FlowError):
    """เนื้อหาขัดนโยบาย — ห้าม retry ด้วย prompt เดิม"""


class UnusualActivity(FlowError):
    """Google จำกัดการใช้งานชั่วคราว — ต้องพักก่อน"""


class NeedsLogin(FlowError):
    """หลุดไปหน้าล็อกอิน"""


# ============================================================ ตรรกะตรวจจับ (JS)
# ยกมาจาก content/flow.js เกือบตรงตัว — แก้เฉพาะให้เป็นฟังก์ชันเดียวที่เรียกได้
DETECT_JS = r"""
(() => {
  const POLICY_RE = /policy|นโยบาย|not allowed|violat|blocked|safety|inappropriate/i;
  const norm = (s) => (s || '').replace(/\s+/g, ' ').trim();
  const visible = (el) => {
    if (!el) return false;
    const r = el.getBoundingClientRect();
    return el.offsetParent !== null && r.width > 0 && r.height > 0;
  };
  const hiddenByInlineStyle = (el) => {
    const s = el.style || {};
    return s.display === 'none' || s.visibility === 'hidden' || s.opacity === '0';
  };
  const isMediaHost = (s) =>
    s.indexOf('media.getMediaUrlRedirect') !== -1 ||
    s.indexOf('storage.googleapis.com') !== -1 ||
    s.indexOf('googleusercontent.com') !== -1;
  // ตัดรูปจิ๋ว (avatar/icon) — media จริงต้อง render ใหญ่หรือ natural size ใหญ่
  const bigEnough = (el) => {
    try {
      const r = el.getBoundingClientRect();
      if (r.width >= 60 && r.height >= 60) return true;
      if (el.naturalWidth >= 200 || el.videoWidth >= 200) return true;
    } catch (e) {}
    return false;
  };

  function collectImageUrls() {
    // URL ถาวรต้องมาก่อน blob: เสมอ — blob ตายเมื่อเปลี่ยนหน้า
    const perm = new Set(), blobs = new Set();
    const consider = (img, allowBlob) => {
      const s = img.currentSrc || img.src || '';
      if (!s || s.indexOf('data:') === 0) return;
      if (s.indexOf('blob:') === 0) {
        if (allowBlob && bigEnough(img)) blobs.add(s);
        return;
      }
      if (isMediaHost(s) && bigEnough(img)) perm.add(s);
    };
    document.querySelectorAll('img[alt="Generated image"]').forEach((i) => consider(i, true));
    document.querySelectorAll('[data-tile-id] img').forEach((i) => consider(i, true));
    document.querySelectorAll('img').forEach((i) => consider(i, false));
    return Array.from(perm).concat(Array.from(blobs));
  }

  function collectVideoUrls() {
    const set = new Set();
    document.querySelectorAll('video').forEach((v) => {
      const s = v.currentSrc || v.src || '';
      if (!s || s.indexOf('data:') === 0) return;
      if (s.indexOf('blob:') === 0) {
        if (v.closest('[data-tile-id]') && bigEnough(v)) set.add(s);
        return;
      }
      if (isMediaHost(s)) set.add(s);
    });
    return Array.from(set);
  }

  function collectTileIds() {
    const ids = [];
    document.querySelectorAll('[data-tile-id]').forEach((t) => {
      if (t.parentElement && t.parentElement.closest('[data-tile-id]')) return; // top-level เท่านั้น
      const id = t.getAttribute('data-tile-id');
      if (id) ids.push(id);
    });
    return ids;
  }

  // ร่องรอยความล้มเหลวที่มีอยู่ก่อน — retry ในโปรเจกต์เดิมจะได้ไม่ตัดสินจากไทล์เก่า
  function collectFailureMarks() {
    const tiles = [], texts = [];
    document.querySelectorAll('div, span').forEach((el) => {
      if (el.children.length > 0) return;
      const t = norm(el.textContent);
      if (t !== 'Failed' && t !== 'Generation failed' && t !== 'ล้มเหลว' &&
          t.indexOf("Couldn't generate image") !== 0) return;
      if (hiddenByInlineStyle(el)) return;
      const r = el.getBoundingClientRect();
      if (!(r.width > 0 && r.height > 0)) return;
      const tile = el.closest('[data-tile-id]');
      if (tile) tiles.push(tile.getAttribute('data-tile-id') || '');
      else texts.push(t);
    });
    const toasts = Array.from(document.querySelectorAll('[data-sonner-toast]'))
      .map((x) => norm(x.textContent).substring(0, 150));
    return { failedTileIds: tiles.filter(Boolean), failedTexts: texts, toastTexts: toasts };
  }

  function readPct() {
    let found = null;
    document.querySelectorAll('div, span').forEach((el) => {
      if (found !== null || el.children.length > 0) return;
      const m = /^(\d{1,3})%$/.exec(norm(el.textContent));
      if (m) {
        const v = parseInt(m[1], 10);
        if (v >= 0 && v <= 100) found = v;
      }
    });
    if (found !== null) return found;
    const m2 = (document.body.innerText || '').match(/(\d{1,3})%/);
    if (m2) {
      const v2 = parseInt(m2[1], 10);
      if (v2 >= 0 && v2 <= 100) return v2;
    }
    return null;
  }

  // อ่านจำนวนเครดิตที่จะใช้จากบรรทัด "การสร้างจะใช้ N เครดิต" (0 = ฟรี = Lower Priority)
  function readCreditCost() {
    const els = document.querySelectorAll('div, span, p');
    for (const el of els) {
      if (el.children.length > 2) continue;
      const t = norm(el.textContent);
      const m = /(?:จะใช้|will use|uses)\s*(\d+)\s*(?:เครดิต|credits?)/i.exec(t);
      if (m && visible(el)) return parseInt(m[1], 10);
    }
    return null;
  }

  function genActiveSignal() {
    const btns = document.querySelectorAll('button');
    for (const b of btns) {
      const ic = b.querySelector('i');
      if (ic && norm(ic.textContent) === 'stop' && visible(b)) return 'stop-icon';
    }
    const lottie = document.querySelector('.lf-player-container, #lottie svg');
    if (lottie && lottie.offsetParent !== null) return 'lottie';
    return null;
  }

  function detectFailure(baseline) {
    baseline = baseline || {};
    const baseTiles = new Set(baseline.failedTileIds || []);
    const baseTexts = new Set(baseline.failedTexts || []);
    const baseToasts = new Set(baseline.toastTexts || []);
    const els = document.querySelectorAll('div, span');
    for (const el of els) {
      if (el.children.length > 0) continue;
      const t = norm(el.textContent);
      if (t !== 'Failed' && t !== 'Generation failed' && t !== 'ล้มเหลว') continue;
      if (hiddenByInlineStyle(el)) continue;
      const r = el.getBoundingClientRect();
      if (!(r.width > 0 && r.height > 0)) continue;
      const ownTile = el.closest('[data-tile-id]');
      if (ownTile && baseTiles.has(ownTile.getAttribute('data-tile-id'))) continue;
      if (!ownTile && baseTexts.has(t)) continue;
      // บริบทต้องแคบ — ถ้ากวาดทั้งหน้าจะไปเจอคำว่า "policy" จากลิงก์ท้ายหน้า
      // แล้วตัดสินผิดเป็น PolicyBlocked ซึ่งเป็นชนิดห้าม retry = ทิ้งงานถาวร
      let ctxEl = ownTile;
      if (!ctxEl) {
        // ขึ้นได้ไม่เกิน 3 ชั้น และต้องหยุดก่อนถึง body เสมอ
        // (ถ้าเดินเลยไปแล้วค่อยถอย จะเสียบริบทของกล่องที่มีข้อความเหตุผลอยู่)
        ctxEl = el;
        for (let up = 0; up < 3; up++) {
          const parent = ctxEl.parentElement;
          if (!parent || parent === document.body || parent === document.documentElement) break;
          ctxEl = parent;
        }
      }
      // toast คือที่ที่ Flow แจ้งเหตุผลจริง จึงรวมเฉพาะ toast ไม่ใช่ทั้งหน้า
      const toastText = Array.from(document.querySelectorAll('[data-sonner-toast]'))
        .map((x) => x.textContent || '').join(' ');
      const ctx = ((ctxEl.textContent || '') + ' ' + toastText).substring(0, 2000);
      const unusual = /กิจกรรมที่ผิดปกติ|unusual activity/i.test(ctx);
      const audioFail = /audio (generation )?fail|สร้างเสียง.{0,12}(ไม่สำเร็จ|ล้มเหลว)|เสียงพูด.{0,12}(ไม่สำเร็จ|ล้มเหลว)/i.test(ctx);
      return {
        failed: true, policy: POLICY_RE.test(ctx), unusual, audio: audioFail,
        message: unusual ? 'ล้มเหลว: Google แจ้งพบกิจกรรมที่ผิดปกติ (โดนจำกัดการใช้งานชั่วคราว)'
          : (audioFail ? 'ล้มเหลว: สร้างเสียงพูดไม่สำเร็จ (audio generation failed)' : t),
      };
    }
    for (const toast of document.querySelectorAll('[data-sonner-toast]')) {
      const txt = toast.textContent || '';
      if (baseToasts.has(norm(txt).substring(0, 150))) continue;
      const iconEl = toast.querySelector('i.google-symbols');
      const icon = norm(iconEl && iconEl.textContent);
      if (icon === 'error' || /generation failed/i.test(txt) ||
          txt.indexOf("Couldn't generate image") !== -1 ||
          txt.indexOf('Please try a different prompt') !== -1) {
        return {
          failed: true, policy: POLICY_RE.test(txt),
          unusual: /กิจกรรมที่ผิดปกติ|unusual activity/i.test(txt),
          audio: /audio (generation )?fail|สร้างเสียง.{0,12}(ไม่สำเร็จ|ล้มเหลว)/i.test(txt),
          message: norm(txt).substring(0, 150),
        };
      }
    }
    for (const el of els) {
      if (el.children.length > 0) continue;
      const t2 = norm(el.textContent);
      if (t2 === "Couldn't generate image. Try again later." || t2 === "Couldn't generate image") {
        if (baseTexts.has(t2)) continue;
        if (!hiddenByInlineStyle(el) && visible(el)) {
          return { failed: true, policy: false, unusual: false, audio: false, message: t2 };
        }
      }
    }
    return { failed: false, policy: false, unusual: false, audio: false, message: '' };
  }

  const marks = collectFailureMarks();
  const images = collectImageUrls();
  const videos = collectVideoUrls();
  const tiles = collectTileIds();
  return {
    imageUrls: images,
    videoUrls: videos,
    tileIds: tiles,
    failedTileIds: marks.failedTileIds,
    failedTexts: marks.failedTexts,
    toastTexts: marks.toastTexts,
    counts: { images: images.length, videos: videos.length, tiles: tiles.length },
    pct: readPct(),
    creditCost: readCreditCost(),
    active: genActiveSignal(),
    failure: detectFailure(window.__flowBaseline || null),
    signedOut: location.host.indexOf('accounts.google.com') !== -1,
  };
})()
"""


class FlowDriver:
    """ขับหน้า Flow หนึ่งแท็บ — ใช้ร่วมกับ Playwright sync API"""

    def __init__(self, page, log=print, debug_dir: Path | None = None):
        self.page = page
        self.log = log
        # โฟลเดอร์เก็บสภาพหน้าตอนพัง (ปกติคือโฟลเดอร์ของงานนั้น)
        self.debug_dir = debug_dir

    # ------------------------------------------------------------ พื้นฐาน

    def snapshot(self) -> dict:
        return self.page.evaluate(DETECT_JS)

    def _dump_failure(self, snapshot: dict, failure: dict) -> None:
        """เก็บสภาพหน้าตอนพังไว้ไฟล์เดียว ไล่สาเหตุได้โดยไม่ต้องเจนซ้ำให้เปลืองเครดิต"""
        if self.debug_dir is None:
            return
        try:
            self.debug_dir.mkdir(parents=True, exist_ok=True)
            payload = {
                "url": self.page.url,
                "failure": failure,
                "counts": snapshot.get("counts"),
                "pct": snapshot.get("pct"),
                "active": snapshot.get("active"),
                "tileIds": snapshot.get("tileIds"),
                "failedTileIds": snapshot.get("failedTileIds"),
                "failedTexts": snapshot.get("failedTexts"),
                "toastTexts": snapshot.get("toastTexts"),
                "imageUrls": snapshot.get("imageUrls"),
                "videoUrls": snapshot.get("videoUrls"),
            }
            (self.debug_dir / "flow_failure.json").write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            (self.debug_dir / "flow_failure.html").write_text(
                self.page.content(), encoding="utf-8"
            )
        except Exception:
            pass

    def set_baseline(self, snapshot: dict) -> None:
        """บอกฝั่งหน้าเว็บว่าอะไรคือ 'ของเดิม' ก่อนกดเจนรอบนี้
        ไม่งั้นไทล์ที่พังจากรอบก่อนจะถูกนับเป็นความล้มเหลวของรอบนี้"""
        self.page.evaluate(
            "(b) => { window.__flowBaseline = b; }",
            {
                "failedTileIds": snapshot.get("failedTileIds", []),
                "failedTexts": snapshot.get("failedTexts", []),
                "toastTexts": snapshot.get("toastTexts", []),
            },
        )

    def new_project(self) -> str:
        """สร้างโปรเจกต์ Flow ใหม่ แล้วคืน URL

        ระบบเดิมสร้างโปรเจกต์ใหม่ "ต่อฉาก" (เก็บไว้ที่ autogen.lastRun.projects)
        เหตุผล: baseline สะอาดเสมอ ไทล์ของซีนก่อนไม่มาปนตอนตรวจผลลัพธ์/ความล้มเหลว
        และรูปที่แนบค้างก็ไม่ข้ามซีน
        """
        self.page.goto(FLOW_URL, wait_until="domcontentloaded",
                       timeout=TIMEOUTS["page_load"] * 1000)
        time.sleep(2)
        if self.snapshot().get("signedOut"):
            raise NeedsLogin("หลุดไปหน้าล็อกอิน Google")
        button = self.page.get_by_role(
            "button", name=NEW_PROJECT_RE
        ).first
        try:
            button.wait_for(state="visible", timeout=TIMEOUTS["page_load"] * 1000)
        except Exception as error:
            raise FlowError(
                "หาปุ่ม 'New project' ไม่เจอ — เปิด Flow สร้างโปรเจกต์เองแล้ววางลิงก์แทน"
            ) from error
        button.click()
        self.page.wait_for_url(re.compile(PROJECT_URL_RE.pattern),
                               timeout=TIMEOUTS["page_load"] * 1000)
        self.page.wait_for_load_state("domcontentloaded",
                                      timeout=TIMEOUTS["page_load"] * 1000)
        time.sleep(4)  # ตัวแก้ไขโหลดต่อหลัง DOM พร้อม
        self.log(f"  โปรเจกต์ใหม่: {self.page.url.rsplit('/', 1)[-1]}")
        return self.page.url

    def goto_project(self, project_url: str) -> None:
        """กลับเข้าโปรเจกต์เดิม (ใช้ตอนเจนวิดีโอของซีนที่รูปอยู่ในโปรเจกต์นั้น)"""
        if self.page.url.rstrip("/") == project_url.rstrip("/"):
            return
        self.page.goto(project_url, wait_until="domcontentloaded",
                       timeout=TIMEOUTS["page_load"] * 1000)
        time.sleep(3)

    def ensure_project(self, project_url: str = "") -> str:
        """เปิดโปรเจกต์เดิมถ้าให้ลิงก์มา ไม่งั้นสร้างใหม่
        (README ระบุว่าถ้าหาปุ่ม New project ไม่เจอ ให้ผู้ใช้สร้างเองแล้ววางลิงก์)"""
        if project_url:
            self.page.goto(project_url, wait_until="domcontentloaded",
                           timeout=TIMEOUTS["page_load"] * 1000)
        elif not PROJECT_URL_RE.search(self.page.url):
            button = self.page.get_by_role("button", name=NEW_PROJECT_RE).first
            try:
                # แดชบอร์ดวาดรายการโปรเจกต์หลัง DOM พร้อม ต้องรอปุ่มจริงๆ
                # ไม่ใช่เช็ค count() ทันทีแล้วสรุปว่าไม่มี
                button.wait_for(state="visible", timeout=TIMEOUTS["page_load"] * 1000)
            except Exception as error:
                raise FlowError(
                    "หาปุ่ม 'New project' ไม่เจอ — เปิด Flow สร้างโปรเจกต์เองแล้ววางลิงก์แทน"
                ) from error
            button.click()
            self.page.wait_for_url(re.compile(PROJECT_URL_RE.pattern),
                                   timeout=TIMEOUTS["page_load"] * 1000)
        self.page.wait_for_load_state("domcontentloaded", timeout=TIMEOUTS["page_load"] * 1000)
        time.sleep(3)
        if self.snapshot().get("signedOut"):
            raise NeedsLogin("หลุดไปหน้าล็อกอิน Google")
        return self.page.url

    # ------------------------------------------------------- settings panel

    def _settings_trigger(self):
        """ปุ่มเปิดเมนูตั้งค่า ชื่อเปลี่ยนตามโมเดลที่เลือกอยู่ จึงต้องหาหลายทาง
        (ยกวิธีมาจาก findSettingsTrigger ของเดิม)"""
        menus = self.page.locator('button[aria-haspopup="menu"]')
        for index in range(menus.count()):
            item = menus.nth(index)
            text = (item.inner_text() or "")
            if re.search(r"Banana|Imagen|🍌|Veo\s*\d|crop_", text, re.I):
                return item
        return None

    # แท็บในแผงตั้งค่า — ต้องนับเฉพาะตัวที่ **มองเห็นจริง**
    #
    # element ของแท็บอยู่ใน DOM ตลอดแม้แผงจะปิดอยู่ ถ้านับด้วย count() เฉยๆ
    # open_settings จะรีเทิร์นทันทีโดยไม่ได้เปิดอะไรเลย แล้ว select_tab ไปอ่าน
    # ข้อความจากแท็บที่ซ่อนอยู่ไม่ได้ → "หาแท็บ 'Video' ในเมนูตั้งค่าไม่เจอ"
    TAB_SELECTOR = '.flow_tab_slider_trigger, button[role="tab"]'
    TAB_VISIBLE_SELECTOR = '.flow_tab_slider_trigger:visible, button[role="tab"]:visible'

    def _tabs_open(self) -> bool:
        return self.page.locator(self.TAB_VISIBLE_SELECTOR).count() > 0

    def open_settings(self) -> None:
        for attempt in range(1, SETTINGS_ATTEMPTS + 1):
            if self._tabs_open():
                return
            trigger = self._settings_trigger()
            if trigger is None:
                raise FlowError("ไม่พบปุ่มเปิด settings panel (Banana/Imagen/Veo/crop)")
            trigger.click()
            time.sleep(1.2)
            if self._tabs_open():
                self.log(f"เปิด settings panel สำเร็จ (ครั้งที่ {attempt})")
                return
            time.sleep(0.6)
        raise FlowError(f"เปิด settings panel ไม่สำเร็จหลังลอง {SETTINGS_ATTEMPTS} ครั้ง")

    def close_settings(self) -> None:
        self.page.keyboard.press("Escape")
        time.sleep(0.4)

    def select_tab(self, label: str) -> None:
        """เลือกแท็บในเมนูตั้งค่า รองรับทั้ง UI อังกฤษ/ไทย และ x2 / 2x
        การกันเลือกสัดส่วนผิดตัวยกมาจากเทคนิค KVID ของระบบเดิม"""
        wanted = [label]
        if label == "Image":
            wanted.append("รูปภาพ")
        if label == "Video":
            wanted.append("วิดีโอ")
        match = re.fullmatch(r"x(\d+)", label, re.I)
        if match:
            wanted.append(f"{match.group(1)}x")

        tabs = self.page.locator('.flow_tab_slider_trigger, button[role="tab"]')
        for index in range(tabs.count()):
            tab = tabs.nth(index)
            try:
                text = (tab.inner_text() or "").strip()
            except Exception:
                continue
            if label == "9:16":
                if any(bad in text for bad in ("3:4", "crop_4_3", "crop_3_4", "1:1", "crop_square")):
                    continue
                if "crop_16_9" in text and "crop_9_16" not in text:
                    continue
            if any(want.lower() in text.lower() for want in wanted):
                tab.click()
                time.sleep(0.4)
                return
        raise FlowError(f"หาแท็บ {label!r} ในเมนูตั้งค่าไม่เจอ")

    # ------------------------------------------------------------ เลือกโมเดล

    MENU_ITEMS_JS = """
    () => {
      const norm = (s) => (s || '').replace(/\\s+/g, ' ').trim();
      const nodes = document.querySelectorAll(
        '[role="menu"][data-state="open"] [role="menuitem"], .DropdownMenuContent [role="menuitem"],'
        + ' [role="menu"][data-state="open"] button, .DropdownMenuContent button'
      );
      return Array.from(nodes).map((n, i) => ({ i, text: norm(n.textContent).substring(0, 90) }));
    }
    """

    def _menu_items(self) -> list[dict]:
        return self.page.evaluate(self.MENU_ITEMS_JS)

    def _click_menu_item(self, index: int) -> None:
        self.page.evaluate(
            """(idx) => {
              const nodes = document.querySelectorAll(
                '[role="menu"][data-state="open"] [role="menuitem"], .DropdownMenuContent [role="menuitem"],'
                + ' [role="menu"][data-state="open"] button, .DropdownMenuContent button'
              );
              const n = nodes[idx];
              if (n) (n.querySelector('button') || n).click();
            }""",
            index,
        )
        time.sleep(0.7)

    def _model_trigger(self):
        """ปุ่มเปิดเมนูเลือกโมเดล — มีไอคอน arrow_drop_down และไม่ใช่ชิปตั้งค่า Video x2"""
        buttons = self.page.locator('button[aria-haspopup="menu"], button:has-text("arrow_drop_down")')
        for index in range(buttons.count()):
            item = buttons.nth(index)
            try:
                text = (item.inner_text() or "").replace("\n", " ")
            except Exception:
                continue
            if "arrow_drop_down" not in text:
                continue
            # ชิปตั้งค่า (เช่น "Video crop_9_16 x1") ไม่ใช่ตัวเลือกโมเดล
            if re.match(r"^\s*Video", text, re.I) and re.search(r"\bx\d+\b", text):
                continue
            return item
        return None

    def credit_cost(self) -> int | None:
        return self.snapshot().get("creditCost")

    def select_video_model(
        self, target: str = "Veo 3.1 - Lite", allow_paid_fallback: bool = False
    ) -> bool:
        """เลือกโมเดลวิดีโอ — Lite ต้องเป็น [Lower Priority] = 0 เครดิตเท่านั้น

        ยกกติกามาจาก selectVideoModel ของระบบเดิมทั้งหมด:
          - ชื่อบนปุ่มขึ้น Lite แต่เครดิตยังไม่เป็น 0 = ยังไม่ใช่ Lower Priority ต้องเปิดเมนูเลือกใหม่
          - หาตัวเลือก [Lower Priority] ไม่เจอ **ห้ามแอบเลือกตัวที่กินเครดิต**
            คืน False ให้ผู้เรียกตัดสินตามสวิตช์ allow_paid_fallback
        """
        want_free = bool(re.search(r"Lite", target, re.I))
        trigger = self._model_trigger()
        if trigger is None:
            self.log("  ไม่พบ dropdown โมเดลวิดีโอ")
            return False

        current = (trigger.inner_text() or "").replace("\n", " ")
        if target in current:
            if not want_free:
                return True
            if re.search(r"Lower Priority|ลำดับความสำคัญต่ำ", current, re.I):
                self.log(f"  โมเดล {target} (Lower Priority) เลือกอยู่แล้ว")
                return True
            cost = self.credit_cost()
            if cost == 0:
                self.log(f"  โมเดล {target} เลือกอยู่แล้ว (0 เครดิต)")
                return True
            self.log(f"  ปุ่มเขียน {target} แต่จะใช้ {cost} เครดิต — เปิดเมนูเลือกใหม่")

        trigger.click()
        time.sleep(0.8)
        items = self._menu_items()
        if not items:
            self.log("  เมนูโมเดลวิดีโอไม่เปิด")
            return False

        if want_free:
            chosen = next(
                (
                    item for item in items
                    if re.search(r"Lower Priority|ลำดับความสำคัญต่ำ|0 เครดิต|free", item["text"], re.I)
                    and re.search(r"Lite", item["text"], re.I)
                ),
                None,
            ) or next(
                (
                    item for item in items
                    if re.search(r"Lower Priority|ลำดับความสำคัญต่ำ", item["text"], re.I)
                ),
                None,
            )
            if chosen is None:
                seen = " | ".join(item["text"][:45] for item in items[:8])
                self.log(f"  ไม่พบตัวเลือก [Lower Priority] (บัญชีนี้อาจไม่มี) — เห็น: [{seen}]")
                self.page.keyboard.press("Escape")
                if not allow_paid_fallback:
                    return False  # ไม่แอบเลือกตัวกินเครดิต
                return False
            self._click_menu_item(chosen["i"])
            cost = self.credit_cost()
            self.log(
                f"  เลือก \"{chosen['text'][:50]}\" → "
                + ("อ่านเครดิตไม่ได้" if cost is None else f"จะใช้ {cost} เครดิต")
                + (" ✓ ฟรี" if cost == 0 else "")
            )
            return True

        chosen = next((item for item in items if target in item["text"]), None)
        if chosen is None:
            self.page.keyboard.press("Escape")
            return False
        self._click_menu_item(chosen["i"])
        return True

    def select_image_model(self, target: str = "Nano Banana 2") -> bool:
        trigger = self._model_trigger()
        if trigger is None:
            return False
        if target in (trigger.inner_text() or ""):
            return True
        trigger.click()
        time.sleep(0.8)
        items = self._menu_items()
        chosen = next((item for item in items if target in item["text"]), None)
        if chosen is None:
            self.page.keyboard.press("Escape")
            self.log(f"  เลือกโมเดลรูป {target} ไม่สำเร็จ")
            return False
        self._click_menu_item(chosen["i"])
        return True

    def configure(
        self,
        kind: str,
        aspect: str = "9:16",
        count: str = "x1",
        video_model: str = "Veo 3.1 - Lite",
        image_model: str = "Nano Banana 2",
        allow_paid_fallback: bool = False,
        start_image: Path | None = None,
        # ความยาวคลิปเป็นวินาที — Flow ให้เลือก 4 / 6 / 8 / 10
        seconds: int | None = None,
    ) -> None:
        """ตั้งชนิดผลลัพธ์ / สัดส่วน / ความยาว / จำนวนชิ้น / โมเดล ก่อนสั่งสร้าง

        ล้มกลางคันต้อง **ปิดแผงตั้งค่าให้เรียบร้อยก่อนโยน error** ไม่งั้นแผงค้างเปิด
        แล้วรอบ retry จะหาปุ่มเปิดไม่เจอ (ปุ่มถูกแผงบังอยู่) กลายเป็นล้มคนละสาเหตุ
        กับรอบแรก ไล่ต้นตอไม่เจอ — เจอมาแล้วรอบนี้
        """
        try:
            self._configure(
                kind, aspect=aspect, count=count, video_model=video_model,
                image_model=image_model, allow_paid_fallback=allow_paid_fallback,
                seconds=seconds,
            )
        except Exception:
            try:
                self.close_settings()
            except Exception:
                pass
            raise

    def _configure(
        self,
        kind: str,
        aspect: str = "9:16",
        count: str = "x1",
        video_model: str = "Veo 3.1 - Lite",
        image_model: str = "Nano Banana 2",
        allow_paid_fallback: bool = False,
        seconds: int | None = None,
    ) -> None:
        self.open_settings()
        self.select_tab("Video" if kind == "video" else "Image")
        self.select_tab(aspect)
        # ความยาวคลิป — **ต้องตั้งทุกครั้ง ไม่ใช่ปล่อยตามที่ค้างอยู่ใน UI**
        # เดิมไม่ได้ตั้งเลย ได้ 8 วินาทีตามค่าที่ค้างไว้ ทั้งที่สตอรีบอร์ดเขียนเป็น
        # คลิป 10 วินาที (SCENE 1 = 0–2 วิ … SCENE 5 = 8–10 วิ) ฉากท้ายจึงถูกตัดทิ้ง
        if kind == "video" and seconds:
            try:
                self.select_tab(f"{int(seconds)}s")
            except FlowError:
                # บางโมเดลให้เลือกความยาวไม่ครบทุกค่า — ใช้ค่าที่ตั้งอยู่ต่อไป
                # ดีกว่าล้มทั้งงานเพราะเลือกความยาวไม่ได้
                self.log(f"  เลือกความยาว {seconds}s ไม่ได้ — ใช้ค่าที่ตั้งไว้เดิม")
        self.select_tab(count)
        if kind == "video":
            if not self.select_video_model(video_model, allow_paid_fallback):
                if not allow_paid_fallback:
                    self.close_settings()
                    raise FlowError(
                        f"เลือก {video_model} แบบ Lower Priority (0 เครดิต) ไม่ได้ "
                        "— หยุดไว้ก่อนเพื่อไม่ให้เผาเครดิตโดยไม่ตั้งใจ"
                    )
                self.log("  ใช้โมเดลที่กินเครดิตแทน (เปิดสวิตช์ยอมจ่ายไว้)")
        else:
            self.select_image_model(image_model)
        self.close_settings()

    # -------------------------------------------------- แนบรูปตั้งต้นให้วิดีโอ

    # JS หา element ตามตรรกะเดิม แล้วปักธงไว้ให้ Playwright คลิกแบบ trusted
    # (ใช้ตรรกะที่พิสูจน์จากหน้าจริงของระบบเดิม ไม่เขียน selector ใหม่ให้พลาด)
    MARK_JS = r"""
    (kind) => {
      const norm = (s) => (s || '').replace(/\s+/g, ' ').trim();
      const visible = (el) => {
        const r = el.getBoundingClientRect();
        return el.offsetParent !== null && r.width > 0 && r.height > 0;
      };
      const iconOf = (b) => {
        const i = b.querySelector('i');
        return norm(i && i.textContent).toLowerCase();
      };
      const minTop = (window.innerHeight || 800) * 0.55;
      document.querySelectorAll('[data-wa-target]').forEach((e) => e.removeAttribute('data-wa-target'));

      if (kind === 'add_ingredient') {
        // ปุ่ม + ของ composer เท่านั้น (แถวล่างจอ) — ปุ่มแถบบนเปิดเมนูคนละตัว
        // ยืนยันจากหน้าจริง: composer + อยู่ y≈854, ปุ่มแถบบน y≈22
        let best = null, bestTop = -1;
        for (const b of document.querySelectorAll('button')) {
          const ic = iconOf(b);
          if (ic !== 'add' && ic !== 'add_2' && ic !== 'add_circle') continue;
          if (!visible(b) || b.closest('[role="dialog"]')) continue;
          const r = b.getBoundingClientRect();
          if (r.top < minTop) continue;
          if (r.top > bestTop) { best = b; bestTop = r.top; }
        }
        if (!best) return null;
        best.setAttribute('data-wa-target', '1');
        return Math.round(bestTop);
      }

      if (kind === 'start_slot') {
        for (const el of document.querySelectorAll('div, span, button')) {
          const t = norm(el.textContent);
          if ((t !== 'เริ่ม' && t !== 'Start') || el.children.length > 1) continue;
          if (!visible(el)) continue;
          const r = el.getBoundingClientRect();
          if (r.width > 120 || r.height > 120) continue;
          el.setAttribute('data-wa-target', '1');
          return Math.round(r.top);
        }
        return null;
      }

      if (kind === 'ingredient_remove') {
        // ปุ่มถอดรูปที่แนบ ใช้ icon 'close' หรือ 'cancel'
        // ระวัง: icon close ที่เป็น "ล้างพรอมต์" คนละหน้าที่ ห้ามกด
        for (const b of document.querySelectorAll('button')) {
          if (b.closest('[data-sonner-toast]')) continue;
          if (b.closest('[role="dialog"], [role="alertdialog"]')) continue;
          const ic = iconOf(b);
          if (ic !== 'close' && ic !== 'cancel') continue;
          const bt = norm(b.textContent);
          if (bt.indexOf('ล้างพรอมต์') !== -1 || /clear prompt/i.test(bt)) continue;
          if (!visible(b)) continue;
          b.setAttribute('data-wa-target', '1');
          return 1;
        }
        return null;
      }
      return null;
    }
    """

    def _mark_and_click(self, kind: str) -> bool:
        """ปักธง element ด้วยตรรกะเดิม แล้วคลิกผ่าน Playwright"""
        if self.page.evaluate(self.MARK_JS, kind) is None:
            return False
        target = self.page.locator('[data-wa-target="1"]').first
        try:
            target.click()
        except Exception:
            return False
        finally:
            self.page.evaluate(
                "() => document.querySelectorAll('[data-wa-target]')"
                ".forEach((e) => e.removeAttribute('data-wa-target'))"
            )
        return True

    def clear_ingredients(self) -> int:
        """ถอดรูปที่แนบค้างอยู่ออกให้หมดก่อนเจนทุกครั้ง

        ระบบเดิมเรียกขั้นนี้ "ทุกซีนรวมซีนแรก" เพื่อกัน ingredient ค้างจากงานเก่า
        ในโปรเจกต์เดียวกัน — ถ้าไม่ล้าง ซีนหลังจะถูกรูปของซีนก่อนปนเข้าไป
        """
        removed = 0
        for _ in range(8):  # เพดานกันวนไม่รู้จบ
            if not self._mark_and_click("ingredient_remove"):
                break
            removed += 1
            time.sleep(0.4)
        if removed:
            self.log(f"  ถอดรูปที่แนบค้างออก {removed} รูป")
        return removed

    def read_credits(self) -> int | None:
        """เครดิต Flow ที่เหลืออยู่ — คืน None ถ้าอ่านไม่ได้

        เลขนี้ไม่ได้อยู่บนหน้า ต้องกดปุ่มบัญชี (ปุ่ม "ULTRA …") ให้เมนูกางก่อน
        ยืนยันจากหน้าจริง: มี link ชื่อ "10020 Google Flow credits"

        **ไม่เดาเป็น 0 เมื่ออ่านไม่ได้** เพราะค่านี้เอาไปลบกันหาส่วนต่างต่อ
        ถ้าเดาผิดจะรายงานว่ารอบนี้ใช้เครดิตไปเป็นหมื่นทั้งที่ไม่ได้ใช้
        """
        try:
            button = self.page.get_by_role(
                "button", name=re.compile(r"ULTRA|User profile", re.I)
            ).first
            if not button.count():
                return None
            button.click()
            deadline = time.time() + 6
            while time.time() < deadline:
                link = self.page.get_by_role("link", name=CREDITS_RE)
                if link.count():
                    label = (link.first.get_attribute("aria-label")
                             or link.first.inner_text() or "")
                    found = CREDITS_RE.search(label)
                    if found:
                        self.page.keyboard.press("Escape")
                        return int(found.group(1).replace(",", ""))
                time.sleep(0.4)
            self.page.keyboard.press("Escape")
        except Exception:                                        # noqa: BLE001
            pass
        return None

    def _picker_open(self) -> bool:
        """picker เปิดแล้วหรือยัง — เช็คหลายทางเพราะ UI เปลี่ยนบ่อยและมีสองภาษา

        **เจอจริง (11 ส.ค.)**: บัญชีที่ UI เป็นภาษาอังกฤษ กดปุ่ม + แล้ว picker
        เปิดจริง แต่ตัวเช็คเดิมตอบว่าไม่เปิด แล้วระบบล้มทั้งงานว่า "เปิด media
        picker ไม่สำเร็จ" ทั้งที่กล่องอยู่ตรงหน้า — ของเดิมหา 3 อย่างที่ไม่มีใน UI นี้
          · input[placeholder*="ค้นหา"]  ช่องค้นหาไม่มี placeholder เลย มีแต่
            aria-label "Search assets"
          · ปุ่ม "Add to prompt"          ไม่มีในหน้านี้
          · [role="option"]               หน้านี้ใช้ tab + grid ไม่ใช่ option

        ของจริงที่ยืนยันจาก aria snapshot: มี [role="dialog"] ที่ข้างในมีปุ่ม
        "upload Upload media" · textbox "Search assets" · tab "Uploads"
        จึงตรวจจากตัวกล่องเป็นหลัก แล้วค่อยถอยไปเช็คแบบเดิมเผื่อ UI รุ่นเก่า
        """
        dialog = self.page.locator('[role="dialog"]:visible')
        if dialog.count():
            box = dialog.last
            if box.get_by_role(
                "button", name=re.compile(r"อัปโหลดสื่อ|Upload media", re.I)
            ).count():
                return True
            if box.get_by_role(
                "textbox", name=re.compile(r"ค้นหา|Search", re.I)
            ).count():
                return True
            if box.get_by_role(
                "tab", name=re.compile(r"Uploads|อัปโหลด|Images|รูปภาพ", re.I)
            ).count():
                return True
        return bool(
            self.page.locator('input[placeholder*="ค้นหา"]').count()
            or self.page.get_by_role(
                "button", name=re.compile("เพิ่มไปยังพรอมต์|Add to prompt", re.I)
            ).count()
            or self.page.locator('[role="option"]').count()
        )

    def _open_media_picker(self) -> bool:
        """เปิด picker ด้วยปุ่ม + ของ composer ก่อน ถ้าไม่ได้ค่อยใช้ช่อง "เริ่ม" (Frames)

        ปุ่ม + มี 2 ตัวคนละหน้าที่ — แถบบนเปิดเมนูเพิ่มสื่อระดับโปรเจกต์ (ไม่แนบเข้า prompt)
        แถว composer ล่างสุดถึงจะเปิด picker จริง จึงต้องกรองด้วยตำแหน่งแนวตั้ง
        """
        for name, kind in (("ปุ่ม + ของ composer", "add_ingredient"),
                           ("ช่อง 'เริ่ม' (Frames)", "start_slot")):
            if not self._mark_and_click(kind):
                continue
            deadline = time.time() + 8
            while time.time() < deadline:
                if self._picker_open():
                    self.log(f"  เปิด media picker ด้วย{name}")
                    return True
                time.sleep(0.4)
            self.page.keyboard.press("Escape")
            time.sleep(0.4)
        return False

    def attach_start_image(self, image_path: Path) -> bool:
        """แนบรูปของซีนเป็นภาพตั้งต้นก่อนเจนวิดีโอ (image → video)

        ระบบเดิมทำขั้นนี้ทุกซีน ถ้าไม่แนบ Flow จะเจนจากข้อความล้วน
        ซึ่งวิดีโอจะหลุดคอนเซปต์จากรูปที่เจนไว้ และในบัญชีนี้ Flow ปฏิเสธงานทันที
        """
        if not image_path.is_file():
            raise FlowError(f"ไม่มีไฟล์รูปตั้งต้น {image_path.name}")
        if not self._open_media_picker():
            raise FlowError("เปิด media picker ไม่สำเร็จ (ทั้งปุ่ม + และช่อง 'เริ่ม')")

        # ตั้งชื่อไม่ซ้ำ เพื่อจับคู่แบบตรงเป๊ะ กันเลือกโดนไฟล์ชื่อซ้ำจากรอบก่อน
        unique_name = f"{image_path.stem}-{int(time.time())}{image_path.suffix}"
        unique_path = image_path.with_name(unique_name)
        unique_path.write_bytes(image_path.read_bytes())

        try:
            # ปุ่มอัปโหลดต้องอยู่ครึ่งล่างของจอ — แถบบนมีปุ่ม "เพิ่มสื่อ" ที่หน้าตาคล้ายกัน
            upload = self.page.get_by_role(
                "button", name=re.compile("อัปโหลดสื่อ|Upload media", re.I)
            )
            chooser = None
            if upload.count():
                viewport = self.page.viewport_size or {"height": 800}
                for index in range(upload.count()):
                    item = upload.nth(index)
                    box = item.bounding_box()
                    if not box or box["y"] < viewport["height"] * 0.25:
                        continue
                    with self.page.expect_file_chooser(timeout=10_000) as event:
                        item.click()
                    chooser = event.value
                    break
            if chooser is not None:
                chooser.set_files(str(unique_path))
            else:
                file_input = self.page.locator('input[type="file"]').last
                if not file_input.count():
                    raise FlowError("ไม่พบช่องอัปโหลดไฟล์ใน picker")
                file_input.set_input_files(str(unique_path))

            # อัปโหลด+ประมวลผลฝั่ง Flow ใช้เวลาได้ถึง 60-90 วิ ตามที่วัดไว้ในระบบเดิม
            self.log(f"  อัปโหลด {unique_name} — รอโผล่ในรายการ (สูงสุด {UPLOAD_WAIT} วิ)")
            option = self.page.locator(
                f'[role="option"]:has-text("{image_path.stem}")'
            ).first
            option.wait_for(state="visible", timeout=UPLOAD_WAIT * 1000)
            option.click()
            time.sleep(1.5)
            self.log("  แนบรูปตั้งต้นสำเร็จ")
            return True
        finally:
            unique_path.unlink(missing_ok=True)

    # ------------------------------------------------------------ สั่งสร้าง

    # วิธีกดปุ่ม Create เรียงจากธรรมดาไปพิสดาร
    #
    # Google Labs เปลี่ยนหน้าตาแทบทุก deploy บางรุ่นปุ่มไม่รับคลิกธรรมดา (ดัก
    # pointer event เอง / ต้องมีจังหวะห่างระหว่างกดกับปล่อย) กดทางเดียวแล้วเงียบ
    # คือเสียทั้งฉากโดยไม่รู้สาเหตุ — KVID เจอปัญหานี้จนต้องทำบันไดสำรอง 5 ชั้น
    CLICK_METHODS = ("native", "js", "pointer", "gap", "enter")

    def _click_create(self, create, how: str) -> None:
        """กดปุ่ม Create ด้วยวิธีที่ระบุ — ไม่ตรวจผล ผู้เรียกเป็นคนตรวจ"""
        if how == "native":
            create.click()
        elif how == "js":
            create.evaluate("el => el.click()")
        elif how == "pointer":
            create.evaluate(
                """el => {
                    const opts = {bubbles: true, cancelable: true, composed: true};
                    el.dispatchEvent(new PointerEvent('pointerdown', opts));
                    el.dispatchEvent(new PointerEvent('pointerup', opts));
                    el.dispatchEvent(new MouseEvent('click', opts));
                }"""
            )
        elif how == "gap":
            # บางรุ่นเช็คว่า down กับ up ห่างกันจริงไหม (กันบอทกดรัว)
            box = create.bounding_box()
            if not box:
                raise FlowError("ไม่เห็นตำแหน่งปุ่ม Create")
            x = box["x"] + box["width"] / 2
            y = box["y"] + box["height"] / 2
            self.page.mouse.move(x, y)
            self.page.mouse.down()
            time.sleep(0.12)
            self.page.mouse.up()
        elif how == "enter":
            self.page.locator('[contenteditable="true"]').first.click()
            self.page.keyboard.press("Enter")
        else:
            raise FlowError(f"ไม่รู้จักวิธีกด {how}")

    def _write_prompt(self, editor, prompt: str) -> None:
        """ใส่ข้อความลงช่อง prompt — ใส่ทีเดียว ไม่พิมพ์ทีละตัว

        เดิมใช้ `editor.type(prompt, delay=1)` ซึ่งยิง event ทีละตัวอักษร
        prompt รวมทุกฉากยาว 3,000–4,000 ตัว ช่อง contenteditable ของ Flow
        ประมวลผลไม่ทันจน **ชนเพดาน 30 วินาทีของ Playwright** แล้วล้มก่อนได้กด Create
        (วัดจริง: 3,478 ตัว → Locator.type Timeout 30000ms)

        `fill()` เขียนทีเดียวแล้วยิง input event ให้เอง เร็วกว่าหลายสิบเท่า
        แต่บาง editor ไม่รับ — จึงตรวจว่าข้อความลงจริงไหม ไม่ลงค่อยถอยไปพิมพ์
        (คราวนี้ให้เวลาเยอะพอ) กดส่งทั้งที่ช่องว่างคือเสียรอบเปล่า
        """
        try:
            editor.fill(prompt, timeout=60_000)
        except Exception as error:
            self.log(f"  ใส่ข้อความทีเดียวไม่ได้ ({str(error)[:60]}) — พิมพ์แทน")
            editor.type(prompt, delay=0, timeout=PROMPT_TYPE_TIMEOUT)
            return

        got = (editor.inner_text() or "").strip()
        # ยอมให้ต่างได้บ้าง (editor อาจตัดช่องว่างท้าย/ขึ้นบรรทัดต่างกัน)
        if len(got) >= len(prompt.strip()) * 0.9:
            return
        self.log(f"  ข้อความลงไม่ครบ ({len(got)}/{len(prompt)}) — พิมพ์ซ้ำแทน")
        editor.click()
        self.page.keyboard.press("Control+A")
        self.page.keyboard.press("Delete")
        editor.type(prompt, delay=0, timeout=PROMPT_TYPE_TIMEOUT)

    def submit(self, prompt: str, tile_baseline: int | None = None) -> str:
        """พิมพ์ prompt แล้วกด Create — ไล่วิธีกดจนกว่าจะเห็นสัญญาณว่าเริ่มเจน

        คืนชื่อวิธีที่ได้ผล หรือ `"unconfirmed"` ถ้ากดครบทุกวิธีแล้วยังไม่เห็นสัญญาณ

        **ห้ามโยน error ตอน unconfirmed** — สัญญาณเริ่มเจนของ Labs ไม่แน่นอน
        เคยกดติดแล้วงานเดินอยู่แต่ตรวจไม่เจอ ถ้าฟันธงว่าล้มแล้ว retry จะกดซ้ำ
        ทั้งที่งานแรกกำลังเจนอยู่ = เผาเครดิตสองรอบ ให้ไปตัดสินที่ผลลัพธ์จริงแทน
        """
        editor = self.page.locator('[contenteditable="true"]').first
        editor.wait_for(state="visible", timeout=30_000)
        editor.click()
        self.page.keyboard.press("Control+A")
        self.page.keyboard.press("Delete")
        self._write_prompt(editor, prompt)

        # ปุ่มส่งมีอยู่ตลอดแต่ disabled จนกว่าจะมีข้อความ และ UI อัปเดตช้ากว่าการพิมพ์
        # เช็ค count() ทันทีจึงพลาดได้ ต้องรอจน "กดได้จริง" แล้วค่อยกด
        create = self.page.get_by_role(
            "button", name=CREATE_BUTTON_RE
        ).first
        deadline = time.time() + TIMEOUTS["flow_settings"]
        ready = False
        while time.time() < deadline:
            try:
                if create.count() and create.is_enabled():
                    ready = True
                    break
            except Exception:
                pass
            time.sleep(0.5)
        if not ready:
            raise FlowError(
                "ปุ่ม Create ไม่พร้อมใช้งานภายในเวลา "
                f"(มีปุ่ม={bool(create.count())}) — ข้อความอาจไม่ได้ลงในช่อง prompt"
            )

        if tile_baseline is None:
            tile_baseline = self.snapshot()["counts"]["tiles"]

        for index, how in enumerate(self.CLICK_METHODS, 1):
            try:
                self._click_create(create, how)
            except Exception as error:
                self.log(f"  กดแบบ {how} ไม่ได้: {str(error)[:80]}")
                continue
            started = self.wait_started(tile_baseline, timeout_s=CLICK_CONFIRM_SECONDS)
            if started:
                if index > 1:
                    self.log(f"  กด Create ติดด้วยวิธี {how} (ลองมา {index} แบบ)")
                return how
        self.log("  กดครบทุกวิธีแล้วไม่เห็นสัญญาณ — ไปรอผลลัพธ์จริงแทน")
        return "unconfirmed"

    def wait_started(self, tile_baseline: int, timeout_s: int = 60) -> str | None:
        """รอสัญญาณว่าเริ่มเจนจริง — ไทล์ใหม่ / ปุ่ม stop / เปอร์เซ็นต์"""
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            snap = self.snapshot()
            if snap["counts"]["tiles"] > tile_baseline:
                return "new-tile"
            if snap["active"]:
                return snap["active"]
            if snap["pct"] is not None:
                return "progress-pct"
            time.sleep(0.5)
        return None

    def wait_result(self, kind: str, before: set[str], timeout_s: int, poll_s: int) -> str:
        """รอจนได้ URL ผลลัพธ์ใหม่ หรือจนล้มเหลว/หมดเวลา

        กติกาที่ยกมาจากระบบเดิม: เจอ Failed แล้วยังไม่ตัดสินทันที —
        รอ FAILED_RECHECK_SECONDS แล้วตรวจซ้ำ เพราะบางครั้งงานเสร็จแล้วแต่ detect ช้า
        ถ้าตรวจซ้ำแล้วมีผลลัพธ์ก็ใช้เลย ไม่เจนใหม่ให้เปลืองเครดิต
        """
        key = "videoUrls" if kind == "video" else "imageUrls"
        started = time.time()
        deadline = started + timeout_s
        warned_grace = False
        while time.time() < deadline:
            snap = self.snapshot()
            if snap.get("signedOut"):
                raise NeedsLogin("หลุดไปหน้าล็อกอินระหว่างรอผล")
            fresh = [url for url in snap[key] if url not in before]
            if fresh:
                return fresh[0]

            failure = snap.get("failure") or {}
            # สัญญาณ Failed ช่วงต้นเชื่อไม่ได้ ยกเว้นที่ระบุสาเหตุชัด
            # (policy / unusual / audio) ซึ่งเป็นความล้มเหลวจริงที่รอไปก็ไม่หาย
            if failure.get("failed") and kind == "video":
                explained = any(
                    failure.get(name) for name in ("policy", "unusual", "audio")
                )
                if not explained and time.time() - started < FAILED_GRACE_SECONDS:
                    if not warned_grace:
                        warned_grace = True
                        self.log(
                            "  เจอสัญญาณ Failed ตั้งแต่ต้น แต่ยังอยู่ช่วงเริ่มเจน "
                            f"({FAILED_GRACE_SECONDS} วิแรก) — รอผลจริงก่อน ไม่ทิ้งงาน"
                        )
                    time.sleep(poll_s)
                    continue

            if failure.get("failed"):
                time.sleep(FAILED_RECHECK_SECONDS)
                recheck = self.snapshot()
                fresh = [url for url in recheck[key] if url not in before]
                if fresh:
                    self.log("Flow แจ้ง Failed แต่ตรวจซ้ำแล้วมีผลลัพธ์ — ใช้ผลนั้น ไม่เจนใหม่")
                    return fresh[0]

                # สัญญาณ Failed ของ Flow เป็นของชั่วคราว โผล่แล้วหายได้ระหว่างเจน
                # ถ้าตรวจซ้ำแล้วอาการหายไป = สัญญาณหลอก ห้ามทิ้งงานที่ยังเจนอยู่
                # (รูปเจนเร็วพอที่ 8 วิจะเห็นผล วิดีโอเป็นนาที ไม่มีทางทัน
                #  ถ้าตัดสินจาก 'ยังไม่มีผลลัพธ์' อย่างเดียว วิดีโอจะโดนทิ้งทุกครั้ง)
                if not (recheck.get("failure") or {}).get("failed"):
                    self.log("  สัญญาณ Failed หายไปตอนตรวจซ้ำ — ถือว่าหลอก รอผลต่อ")
                    continue
                if recheck.get("active") or recheck.get("pct") is not None:
                    self.log(
                        f"  ยังเจนอยู่ (active={recheck.get('active')} "
                        f"pct={recheck.get('pct')}) — ไม่ทิ้งงาน"
                    )
                    continue
                message = failure.get("message") or "ล้มเหลว"
                # เก็บบริบทไว้ไล่สาเหตุ — คำว่า "Failed" เฉยๆ บอกอะไรไม่ได้เลย
                detail = (
                    f"{message} [ไทล์ {recheck['counts']['tiles']} "
                    f"รูป {recheck['counts']['images']} วิดีโอ {recheck['counts']['videos']}"
                    f" pct={recheck.get('pct')} active={recheck.get('active')}"
                    f" policy={failure.get('policy')} unusual={failure.get('unusual')}"
                    f" audio={failure.get('audio')}]"
                )
                self._dump_failure(recheck, failure)
                if failure.get("policy"):
                    raise PolicyBlocked(detail)
                if failure.get("unusual"):
                    raise UnusualActivity(detail)
                raise FlowError(detail)

            if snap["pct"] is not None:
                self.log(f"  กำลังเจน {snap['pct']}%")
            time.sleep(poll_s)
        raise FlowError(f"หมดเวลารอผล ({timeout_s} วิ)")

    # ------------------------------------------------------------ ดาวน์โหลด

    def download(self, url: str, target: Path) -> None:
        """โหลดไฟล์ผ่าน request ของเบราว์เซอร์ (ติดคุกกี้ไปด้วย)
        blob: อ่านจาก network ไม่ได้ ต้อง fetch ในหน้าแล้วส่งไบต์ออกมา"""
        target.parent.mkdir(parents=True, exist_ok=True)
        if url.startswith("blob:"):
            data = self.page.evaluate(
                """async (u) => {
                    const r = await fetch(u);
                    const b = new Uint8Array(await r.arrayBuffer());
                    return Array.from(b);
                }""",
                url,
            )
            target.write_bytes(bytes(data))
            return
        response = self.page.request.get(url, timeout=TIMEOUTS["download"] * 1000)
        if not response.ok:
            raise FlowError(f"โหลดไฟล์ผลลัพธ์ไม่สำเร็จ: HTTP {response.status}")
        target.write_bytes(response.body())

    # ------------------------------------------------------ เจนหนึ่งชิ้นครบวง

    def generate(
        self,
        prompt: str,
        kind: str,
        target: Path,
        aspect: str = "9:16",
        max_tries: int | None = None,
        video_model: str = "Veo 3.1 - Lite",
        image_model: str = "Nano Banana 2",
        allow_paid_fallback: bool = False,
        # รูปตั้งต้นที่แนบเข้าไปก่อนพิมพ์ prompt — ตัวฟังก์ชันเรียกใช้ตัวแปรนี้อยู่แล้ว
        # (บรรทัด "if start_image is not None") แต่เดิม **ไม่มีในนิยามฟังก์ชัน**
        # เรียก generate() เมื่อไรจะได้ NameError ทันที ตัวเรียกใน flow_pipeline
        # ก็ส่ง start_image= เข้ามาอยู่แล้วด้วย → พังทั้งสองทาง
        start_image: Path | None = None,
        # on_retry(prompt, attempt, error) -> prompt ใหม่ (คืน None = ใช้ของเดิม)
        on_retry=None,
        # ความยาวคลิปเป็นวินาที (4/6/8/10) — None = ใช้ค่าที่ตั้งอยู่ใน UI
        seconds: int | None = None,
    ) -> None:
        """เจนหนึ่งชิ้นพร้อม retry ตามกติกาเดิม

        - รูป 3 ครั้ง / วิดีโอ 2 ครั้ง
        - backoff n×15 วิ ก่อนลองใหม่แต่ละครั้ง
        - policy violation ไม่ retry ด้วย prompt เดิม
        - unusual activity ไม่ retry ทันที (ต้องพัก) ส่งต่อให้ผู้เรียกตัดสิน
        """
        tries = max_tries or (MAX_VIDEO_TRIES if kind == "video" else MAX_IMAGE_TRIES)
        timeout_s = TIMEOUTS["video_per_scene"] if kind == "video" else TIMEOUTS["image_per_scene"]
        poll_s = POLL_VIDEO if kind == "video" else POLL_IMAGE
        key = "videoUrls" if kind == "video" else "imageUrls"

        last: Exception | None = None
        for attempt in range(1, tries + 1):
            if attempt > 1:
                wait = RETRY_BACKOFF * (attempt - 1)
                self.log(f"  ลองใหม่ครั้งที่ {attempt}/{tries} (รอ {wait} วิ)")
                time.sleep(wait)
                # ให้ผู้เรียกดัดแปลง prompt ก่อนลองใหม่ได้ — retry ด้วยของเดิมซ้ำๆ
                # มักได้ผลเดิม โดยเฉพาะกรณีเสียงพูดไทยล้ม ที่ต้องปรับจังหวะคำ
                if on_retry:
                    try:
                        changed = on_retry(prompt, attempt, last)
                        if changed and changed != prompt:
                            prompt = changed
                            self.log("  ปรับ prompt ก่อนลองใหม่")
                    except Exception as error:
                        self.log(f"  ปรับ prompt ไม่สำเร็จ: {str(error)[:80]}")
            submitted = False
            try:
                baseline = self.snapshot()
                self.set_baseline(baseline)
                before = set(baseline[key])
                self.configure(
                    kind, aspect=aspect, video_model=video_model,
                    image_model=image_model, allow_paid_fallback=allow_paid_fallback,
                    seconds=seconds,
                )
                # ล้างรูปที่แนบค้างก่อนเสมอ (ทุกซีน รวมซีนแรก)
                # ไม่งั้นรูปของซีนก่อนจะปนเข้าไปในซีนถัดไป
                self.clear_ingredients()
                # แนบรูปอ้างอิงก่อนพิมพ์ prompt เสมอเมื่อมี
                #   โหมดรูป   = รูปสินค้าต้นฉบับ (ให้ผลลัพธ์เป็นสินค้าจริง ไม่ใช่ของทั่วไป)
                #   โหมดวิดีโอ = รูปของซีนนั้น (ให้วิดีโอต่อเนื่องกับภาพที่เจนไว้)
                if start_image is not None:
                    self.attach_start_image(start_image)
                self.submit(prompt, baseline["counts"]["tiles"])
                submitted = True          # จากจุดนี้ไป = เครดิตถูกใช้ไปแล้ว
                url = self.wait_result(kind, before, timeout_s, poll_s)
                self.download(url, target)
                return
            except (PolicyBlocked, UnusualActivity, NeedsLogin):
                raise  # ห้าม retry — ผู้เรียกต้องจัดการเอง
            except FlowError as error:
                last = error
                self.log(f"  ล้มเหลว: {error}")
                if submitted:
                    # **กด Create ไปแล้วห้ามยิงซ้ำเด็ดขาด**
                    #
                    # เจอจริง 11 ส.ค.: ตัวจับ Failed ยิงลวงตั้งแต่ 8 วินาทีแรก
                    # ระบบจึงยิงรอบใหม่ทั้งที่รอบแรกกำลังเรนเดอร์อยู่ → ได้ไทล์
                    # 2 อัน (16% กับ 48% พร้อมกัน) เสียเครดิตสองเท่าต่องานเดียว
                    #
                    # retry มีไว้สำหรับความล้มเหลว **ก่อน** กด Create เท่านั้น
                    # (หาปุ่มไม่เจอ แนบรูปไม่ติด) ซึ่งยังไม่เสียเครดิต
                    raise FlowError(
                        f"กด Create ไปแล้ว (เครดิตถูกใช้แล้ว) จึงไม่ยิงซ้ำ — {error}"
                    ) from error
        raise FlowError(f"เจน {kind} ไม่สำเร็จหลังลอง {tries} ครั้ง: {last}")
