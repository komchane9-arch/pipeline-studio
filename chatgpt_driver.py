"""ขับ ChatGPT (GPTs) ผ่านเบราว์เซอร์ — ขั้นกลางของผัง

ทำไมต้องขับเบราว์เซอร์ ไม่ใช้ API:
  ผู้ใช้ต้องการ **GPT ตัวที่ตั้งค่าไว้เอง** (custom GPT) ซึ่ง API ของ OpenAI
  เข้าไม่ถึง — Assistants API เป็นคนละตัวกับ GPTs ที่สร้างในหน้าเว็บ
  จึงต้องเปิดหน้าเว็บจริงแล้วคุยในนั้น เหมือนที่ทำกับ Google Flow

ลำดับตามผัง:
  ส่งรูปทั้งหมด + รายละเอียด → GPT  →  copy prompt สำหรับเจนรูป
  ส่งซ้ำในแชทเดิม            → GPT  →  copy prompt สำหรับเจนวิดีโอ
ทั้งสองรอบอยู่ **แชทเดียวกัน** เพราะรอบสองต้องอ้างอิงของที่ตอบไว้รอบแรก
"""

from __future__ import annotations

import re
import time
from datetime import datetime
from pathlib import Path

CHATGPT_HOME = "https://chatgpt.com/"
PAGE_TIMEOUT = 90_000
SETTLE_SECONDS = 3.0
UPLOAD_SETTLE = 2.5
REPLY_TIMEOUT = 600          # GPT ที่วาดภาพใช้เวลาหลายนาที บางทีเกิน 5
REPLY_QUIET_SECONDS = 3.0    # ข้อความต้องนิ่งเท่านี้ถึงนับว่าตอบจบ
POLL_SECONDS = 1.5
HEARTBEAT_SECONDS = 15       # เขียน log บอกสถานะทุกเท่านี้ ระหว่างรอคำตอบ
IMAGE_SETTLED_SECONDS = 20   # รูปนิ่งเท่านี้ = เสร็จแล้ว ไม่ต้องรอปุ่มหยุดหาย
CHAT_LOAD_TIMEOUT = 20       # เปิดแชทเก่า รอบทสนทนาขึ้นนานสุดเท่านี้
MAX_UPLOAD = 10              # ChatGPT รับไฟล์ต่อข้อความได้จำกัด


class ChatGPTError(RuntimeError):
    """คุยกับ ChatGPT ไม่สำเร็จ"""


class ChatGPTNeedsLogin(ChatGPTError):
    """ยังไม่ได้ล็อกอิน ChatGPT ในโปรไฟล์เบราว์เซอร์นี้"""


# หา "บล็อกคำตอบของ GPT" — ใช้ร่วมกันทุกที่ที่ต้องอ่านคำตอบ
#
# ห้ามยึด `[data-message-author-role="assistant"]` เป็นหลักเด็ดขาด: คำตอบที่เป็น
# **รูปล้วนไม่มีข้อความ** (ซึ่งคือกรณีของสตอรีบอร์ดพอดี) ถูกวางไว้ใน conversation-turn
# ที่ **ไม่มี attribute นั้นติดมาเลย** — วัดของจริงแล้ว:
#     byRole = {assistant: 0, user: 1}
#     conversation-turn-2 → hasRoleChild=false · imgs=3 · alt="Generated image"
# ผลคือตัวรอคำตอบมองไม่เห็นอะไรเลย วนจนหมด 600 วินาทีแล้วโยน "ChatGPT ไม่ตอบ"
# ทั้งที่รูปขึ้นอยู่ในแชทตั้งแต่วินาทีที่ 85
#
# จึงยึด conversation-turn เป็นหลักแล้ว **ตัดเทิร์นของผู้ใช้ออก** — ได้ทั้งกรณีรูปล้วน
# และกรณีข้อความปกติ ส่วน role เดิมเก็บไว้เป็นทางสำรองเผื่อหน้าตาเปลี่ยนอีก
TURNS_JS = r"""
  const assistantTurns = () => {
    const all = [...document.querySelectorAll('[data-testid^="conversation-turn"]')];
    if (all.length) {
      return all.filter((el) => !el.querySelector('[data-message-author-role="user"]'));
    }
    return [...document.querySelectorAll('[data-message-author-role="assistant"]')];
  };

  // รูปที่ GPT วาด — **ห้ามหาโดยไล่ลงมาจากกล่องคำตอบ**
  //
  // ตอนคุยสดๆ ChatGPT ยังไม่ติดป้ายบอกกล่องคำตอบให้เลย ทั้ง data-message-author-role
  // (ไม่มีในคำตอบที่เป็นรูปล้วน) และ data-testid="conversation-turn-N" (โผล่ตอนโหลด
  // หน้าใหม่เท่านั้น) วัดของจริงแล้ว: ระหว่างรัน รูปขึ้นใน DOM ครบ (main img 1→4)
  // แต่ตัวนับคำตอบยังเป็น 0 → รอจนครบ 600 วินาทีแล้วโยน "ไม่ตอบ" ทุกครั้ง
  //
  // จึงไปดู **ตัวรูปเอง** แล้วคัดของที่ไม่ใช่ผลงานออก:
  //   - รูปที่เราอัปโหลดขึ้นไป: อยู่ในเทิร์นของผู้ใช้ และ alt เป็นชื่อไฟล์ ("01.jpg")
  //   - รูปที่ GPT วาด: alt = "Generated image"
  // ถ้ามีตัวที่ alt ตรงก็ใช้เฉพาะตัวนั้น ไม่มีค่อยใช้ทุกใบที่ไม่ใช่ของผู้ใช้
  //
  // ตัดซ้ำด้วย Set เพราะ ChatGPT วาง <img> ของรูปเดียวกันซ้ำ 3 ใบ
  // (ตัวย่อ + ตัวเต็ม + ตัวสำหรับกดขยาย) ถ้าไม่ตัดจะโหลดไฟล์เดิม 3 รอบ
  const generatedImages = () => {
    const usable = [...document.querySelectorAll('main img')].filter((el) => {
      const src = el.currentSrc || el.src || '';
      if (!src || src.startsWith('data:')) return false;
      if (/avatar|icon|logo/i.test(src)) return false;
      // รูปจิ๋วคือไอคอนในปุ่ม ไม่ใช่ผลงาน (0 = ยังโหลดไม่เสร็จ ปล่อยผ่านไว้ก่อน)
      if (el.naturalWidth && el.naturalWidth < 100) return false;
      if (el.closest('[data-message-author-role="user"]')) return false;
      // alt เป็นชื่อไฟล์ = รูปที่เราแนบขึ้นไปเอง ไม่ใช่ผลงานของ GPT
      if (/\.(jpe?g|png|webp|gif)$/i.test(el.getAttribute('alt') || '')) return false;
      return true;
    });
    const drawn = usable.filter((el) =>
      /generated image/i.test(el.getAttribute('alt') || '')
    );
    const use = drawn.length ? drawn : usable;
    return [...new Set(use.map((el) => el.currentSrc || el.src))];
  };
"""


# อ่านสภาพหน้า — รวมไว้ที่เดียว เวลา ChatGPT เปลี่ยนหน้าตาแก้จุดเดียวจบ
STATE_JS = r"""
() => {
  // ยุบเฉพาะเว้นวรรค/แท็บ **ห้ามยุบการขึ้นบรรทัดใหม่**
  //
  // เดิมใช้ /\s+/g ซึ่งกิน \n ไปด้วย ทำให้คำตอบทั้งก้อนเหลือบรรทัดเดียว —
  // โครงสร้างที่ GPT จัดมา (SCENE 1..5 บรรทัดละฉาก, บล็อกโค้ด) หายหมดตั้งแต่
  // ต้นทาง ตัวแกะคำสั่งกับตัวแกะบทพูดเลยหาจุดตัดไม่เจอทั้งคู่ ได้ออกมาอย่างละ 1 ชุด
  // ทั้งที่ของจริงมี 5 ฉาก (วัดแล้ว: ไฟล์ยาว 7,776 ตัว มี 0 บรรทัด)
  const norm = (s) => (s || '')
    .replace(/[ \t ]+/g, ' ')
    .replace(/\n{3,}/g, '\n\n')
    .replace(/[ ]+\n/g, '\n')
    .trim();
  // ช่องพิมพ์จริงคือตัวท้ายสุด — ข้อความเก่าที่แก้ไขได้ก็เป็น contenteditable
  // และอยู่ก่อนหน้า (ดู composer() ฝั่ง Python สำหรับที่มา)
  const boxes = document.querySelectorAll('#prompt-textarea, div[contenteditable="true"]');
  const box = boxes.length ? boxes[boxes.length - 1] : null;
""" + TURNS_JS + r"""
  // ข้อความตอบล่าสุดของ ChatGPT
  const turns = assistantTurns();
  const last = turns[turns.length - 1];

  // ยังพิมพ์อยู่ไหม — ปุ่มหยุดโผล่เฉพาะตอนกำลังสตรีมคำตอบ
  //
  // ห้ามจับด้วย aria-label แบบ *"Stop"* หรือ *"หยุด"* เด็ดขาด: แถบรายชื่อแชท
  // ด้านข้างมีปุ่มของทุกบทสนทนา ถ้าผู้ใช้ตั้งชื่อแชทที่มีคำนั้นอยู่ (เจอจริง:
  // "แคปชันหยุดนิ้วคนดู") จะกลายเป็นว่า "กำลังพิมพ์อยู่" ตลอดเวลา แล้วตัวรอคำตอบ
  // จะไม่มีวันจบ — รอจนหมดเวลาทุกครั้งทั้งที่ ChatGPT ตอบไปแล้วใน 10 วินาที
  const stopping = !!document.querySelector('button[data-testid="stop-button"]');

  // นับรูปในคำตอบล่าสุดด้วย — GPT สร้างภาพมักตอบเป็น "รูปล้วน ไม่มีข้อความ"
  // ถ้าดูแต่ innerText จะเห็นเป็นค่าว่างแล้วเข้าใจผิดว่ายังไม่ตอบ
  const lastImages = generatedImages().length;

  return {
    url: location.href,
    hasBox: !!box,
    streaming: stopping,
    replyCount: turns.length,
    lastImages,
    lastReply: last ? norm(last.innerText) : '',
    signedOut: /\/auth\/login|\/login/.test(location.pathname) ||
      [...document.querySelectorAll('button, a')].some((el) =>
        /^(Log in|Sign up|เข้าสู่ระบบ)$/i.test(norm(el.textContent))
      ),
  };
}
"""


# รูปที่อยู่ใน "คำตอบล่าสุด" เท่านั้น — ตัดไอคอน/รูปโปรไฟล์ และรูป data: ที่เป็น
# ตัวโหลดชั่วคราวออก ไม่งั้นจะได้ไฟล์ขยะปนมากับ storyboard
#
# ต้องจำกัดขอบเขตไว้ที่บล็อกคำตอบเท่านั้น ห้ามกวาดทั้งหน้า — **รูปสินค้าที่เราอัปโหลด
# ขึ้นไปเองก็เป็น <img> ในหน้าเดียวกัน** กวาดทั้งหน้าจะได้รูปสินค้ากลับมาแทนสตอรีบอร์ด
REPLY_IMAGES_JS = r"""
() => {
""" + TURNS_JS + r"""
  return generatedImages();
}
"""

IMAGE_TIMEOUT = 600          # วาดภาพนานกว่าพิมพ์ข้อความมาก
IMAGE_QUIET_SECONDS = 6.0    # รายการรูปต้องนิ่งเท่านี้ถึงนับว่าวาดครบ

# ข้อความที่ ChatGPT ตอบเมื่อ "สร้างภาพไม่ได้" — เจอแล้วต้องเลิกรอทันที
# ไม่งั้นจะไปยืนรอรูปที่ไม่มีวันมาจนครบ 10 นาที (เจอจริงกับสินค้าโซฟา)
IMAGE_REFUSAL_HINTS = [
    "violate our content polic",
    "ไม่สามารถสร้างภาพ",
    "สร้างภาพนี้ไม่ได้",
    "ขัดต่อนโยบาย",
]

# คำปฏิเสธที่ต้องมี **คำปฏิเสธจริง** นำหน้าเท่านั้น
#
# เดิมจับด้วยท่อนสั้นเปล่าๆ ("create that image") ซึ่งไปโดนประโยคบอกเล่าด้วย —
# "Sure, I'll create that image for you" ก็เข้าเงื่อนไข แล้วระบบจะเลิกรอทันที
# ตั้งแต่ยังไม่เริ่มวาด กลายเป็นรายงานว่า "โดนตัวกรอง" ทั้งที่ GPT กำลังทำงานอยู่
#
# ยังต้องครอบ "can not" ที่มีเว้นวรรคไว้ด้วย — ของจริงเขียนแบบนั้น (เจอมาแล้ว)
IMAGE_REFUSAL_RE = re.compile(
    r"(can'?t|can\s?not|won'?t|unable\s+to|not\s+able\s+to|failed\s+to)"
    r"[^.\n]{0,40}?(creat\w*|generat\w*|mak\w*|produc\w*)[^.\n]{0,20}?(image|picture)",
    re.I,
)


def image_refused(reply: str) -> bool:
    """คำตอบนี้บอกว่าสร้างภาพไม่ได้ใช่ไหม"""
    text = reply or ""
    low = text.lower()
    if any(hint.lower() in low for hint in IMAGE_REFUSAL_HINTS):
        return True
    return bool(IMAGE_REFUSAL_RE.search(text))


class ChatGPTSession:
    def __init__(self, page, log=print) -> None:
        self.page = page
        self.log = log

    def state(self) -> dict:
        return self.page.evaluate(STATE_JS)

    def open(self, gpt_url: str = "") -> None:
        """เปิดแชทใหม่ — ใส่ลิงก์ GPT ตัวที่ต้องการได้ ไม่ใส่ = ChatGPT ปกติ"""
        target = gpt_url.strip() or CHATGPT_HOME
        self.page.goto(target, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT)
        time.sleep(SETTLE_SECONDS)
        state = self.state()
        if state["signedOut"]:
            raise ChatGPTNeedsLogin(
                "ยังไม่ได้ล็อกอิน ChatGPT — รัน `python flow_worker.py login-chatgpt` "
                "แล้วล็อกอินครั้งเดียว"
            )
        if not state["hasBox"]:
            raise ChatGPTError("เปิดหน้าแชทไม่สำเร็จ — ไม่พบช่องพิมพ์ข้อความ")

        # เปิด "แชทที่คุยไว้แล้ว" ต้องรอให้บทสนทนาขึ้นก่อน
        #
        # 3 วินาทีไม่พอ วัดจริงแล้วช่องพิมพ์มาก่อน ส่วนบทสนทนาตามมาทีหลัง — ถ้าอ่าน
        # สถานะตอนนั้นจะได้ 0 คำตอบ 0 รูป แล้วเข้าใจผิดว่าแชทว่างเปล่า
        # (เจอจริง: +0s ได้ 0 ทุกอย่าง · +2s ได้ครบ)
        if "/c/" in target:
            deadline = time.time() + CHAT_LOAD_TIMEOUT
            while time.time() < deadline:
                if self.state()["replyCount"]:
                    break
                time.sleep(0.5)
            state = self.state()

        self.log(f"เปิดแชทแล้ว ({state['url'][:70]})")

    # --------------------------------------------------- เคลียร์แผ่นคลุมหน้าจอ

    # แผ่นคลุมเต็มจอที่ดักการคลิกไว้หมด — ChatGPT ใช้กับกล่องโต้ตอบทุกชนิด
    # (โฆษณาฟีเจอร์ใหม่ · ขอให้ยืนยันอะไรบางอย่าง · เมนูที่เปิดค้าง)
    #
    # จับที่ **inset-0 + z-index สูง + กว้างเกือบเต็มจอ** ไม่ใช่ชื่อคลาสตรงตัว
    # เพราะคลาสของ ChatGPT เป็นชุดยาวที่เปลี่ยนทุก deploy (ของจริงที่เจอ:
    # "fixed inset-0 z-50 before:starting:backdrop-blur-0 …" ยาว 12 คลาส)
    OVERLAY_JS = r"""
    () => {
      const hits = [];
      for (const el of document.querySelectorAll('div,section')) {
        const st = getComputedStyle(el);
        if (st.position !== 'fixed' && st.position !== 'absolute') continue;
        if (st.pointerEvents === 'none') continue;
        if (st.display === 'none' || st.visibility === 'hidden') continue;
        const z = parseInt(st.zIndex || '0', 10) || 0;
        if (z < 10) continue;
        const r = el.getBoundingClientRect();
        // ต้องคลุมเกือบเต็มจอถึงจะนับว่าเป็นแผ่นดักคลิก
        if (r.width < innerWidth * 0.9 || r.height < innerHeight * 0.9) continue;
        hits.push({
          z,
          state: el.getAttribute('data-state') || '',
          testid: el.getAttribute('data-testid') || '',
          label: (el.innerText || '').trim().slice(0, 80),
        });
      }
      return hits;
    }
    """

    # ปุ่มปิด/รับทราบที่เคยเห็นบนกล่องโต้ตอบของ ChatGPT ทั้งไทยและอังกฤษ
    DISMISS_LABELS = re.compile(
        r"^(ปิด|ตกลง|รับทราบ|ไว้ทีหลัง|ข้าม|ไม่เป็นไร|"
        r"close|dismiss|got it|okay|ok|no thanks|maybe later|skip|continue)$",
        re.I,
    )

    def overlays(self) -> list[dict]:
        """แผ่นคลุมเต็มจอที่ดักคลิกอยู่ตอนนี้ — ว่างเปล่า = หน้าจอโล่ง"""
        try:
            return self.page.evaluate(self.OVERLAY_JS) or []
        except Exception:                                    # noqa: BLE001
            return []          # อ่านไม่ได้ = อย่าไปขวางงาน ปล่อยให้คลิกลองดู

    def clear_overlays(self, tries: int = 3) -> bool:
        """ปิดแผ่นคลุมหน้าจอก่อนจะไปกดอะไร — คืน True เมื่อหน้าจอโล่งแล้ว

        **ทำไมต้องมี** ChatGPT เด้งกล่องโต้ตอบคลุมทั้งจอเป็นครั้งคราว ช่องพิมพ์
        ยังมองเห็นและ "enabled" อยู่ทุกประการ Playwright จึงพยายามคลิกซ้ำจนหมด
        เวลาแล้วรายงานว่า **Timeout** ซึ่งอ่านแล้วนึกว่าเน็ตช้าหรือหน้าโหลดไม่จบ
        ทั้งที่สาเหตุจริงคือมีแผ่นใสคลุมอยู่

        วัดจริง 22 ส.ค. 2026 เวลา 10:02:37 — งาน TCL BreezeIN Pro ล้มด้วย
        `Timeout 30000ms` โดย log ของ Playwright บอกเองว่า
        `<div class="fixed inset-0 z-50 …"> … intercepts pointer events`
        กดซ้ำไป 57 ครั้งใน 30 วินาที ส่วนงานถัดมาที่ทำต่อทันทีผ่านฉลุย
        (แผ่นคลุมหายไปเอง) — เกิดเป็นครั้งคราว ไม่ใช่ทุกครั้ง

        ไล่จากเบาไปหนัก: Escape ก่อน แล้วค่อยหาปุ่มปิดในกล่องนั้น
        """
        for attempt in range(1, tries + 1):
            found = self.overlays()
            if not found:
                return True
            top = max(found, key=lambda item: item.get("z", 0))
            label = (top.get("label") or "").replace("\n", " ")[:60]
            self.log(f"  มีแผ่นคลุมหน้าจอบังอยู่ (รอบ {attempt}/{tries}) {label}")

            self.page.keyboard.press("Escape")
            time.sleep(0.6)
            if not self.overlays():
                self.log("  ปิดด้วย Escape แล้ว")
                return True

            # Escape ไม่ยอมปิด — กล่องบางแบบบังคับให้กดปุ่มรับทราบเท่านั้น
            for button in self.page.get_by_role("button").all()[:40]:
                try:
                    name = (button.inner_text() or "").strip()
                    aria = (button.get_attribute("aria-label") or "").strip()
                except Exception:                            # noqa: BLE001
                    continue
                if not (self.DISMISS_LABELS.match(name)
                        or self.DISMISS_LABELS.match(aria)):
                    continue
                try:
                    button.click(timeout=3000)
                    time.sleep(0.6)
                except Exception:                            # noqa: BLE001
                    continue
                if not self.overlays():
                    self.log(f"  ปิดด้วยปุ่ม \"{name or aria}\" แล้ว")
                    return True
        return not self.overlays()

    # ------------------------------------------------------------- ส่งข้อความ

    def attach(self, images: list[Path]) -> int:
        """แนบรูปเข้าข้อความ — ยัดลง input[type=file] ตรงๆ ไม่ต้องกดปุ่มคลิปหนีบ

        กดปุ่มแล้วเลือกไฟล์ในหน้าต่างของ Windows อัตโนมัติไม่ได้ แต่ input ที่ซ่อน
        อยู่รับไฟล์ได้เลย — วิธีเดียวกับที่ใช้อัปโหลดคลิปขึ้น TikTok
        """
        files = [str(path) for path in images if Path(path).is_file()][:MAX_UPLOAD]
        if not files:
            return 0
        target = self.page.locator('input[type="file"]').first
        if not target.count():
            raise ChatGPTError("ไม่พบช่องแนบไฟล์ในหน้าแชท")
        target.set_input_files(files)
        # รอให้รูปขึ้นจริงก่อนพิมพ์ข้อความ ไม่งั้นกด Enter ตอนอัปโหลดยังไม่เสร็จ
        # ข้อความจะถูกส่งไปโดยไม่มีรูปติดไปด้วย
        deadline = time.time() + 120
        while time.time() < deadline:
            time.sleep(UPLOAD_SETTLE)
            pending = self.page.locator(
                '[role="progressbar"], [class*="uploading" i]'
            ).count()
            if not pending:
                break
        self.log(f"  แนบรูป {len(files)} ใบแล้ว")
        return len(files)

    def composer(self):
        """ช่องพิมพ์ของ ChatGPT — **ห้ามไปโดนข้อความเก่าที่แก้ไขได้**

        ข้อความที่เราเคยส่งไปแล้วก็เป็น contenteditable เหมือนกัน (ChatGPT มีปุ่ม
        Edit message ให้แก้ย้อนหลัง) และมันอยู่ **ก่อน** ช่องพิมพ์จริงในหน้า
        selector เดิมใช้ `.first` จึงไปหยิบข้อความเก่ามาพิมพ์ทับ — กด Enter ตรงนั้น
        ไม่มีอะไรเกิดขึ้น กลายเป็นอาการ "ส่งแล้ว ChatGPT ไม่ตอบ"

        พิสูจน์แล้ว 12 ส.ค.: เปิดดูข้อความเก่าในแชท เจอข้อความที่เราพยายามส่ง
        4 ครั้งฝังอยู่กลางข้อความเดิมทั้งหมด ("…ble for the final moment.แก้บทพูด
        ตามนี้…") ส่วนจำนวนเทิร์นไม่ขยับเลย (user=2 asst=1 ตลอด 60 วินาที)

        แชทใหม่ที่ยังไม่มีข้อความเลยจึงทำงานได้ปกติ — เพราะ contenteditable
        ตัวเดียวในหน้าคือช่องพิมพ์จริง อาการเลยโผล่เฉพาะตอนคุยต่อในแชทเดิม
        """
        box = self.page.locator("#prompt-textarea").last
        if box.count():
            return box
        # ไม่มี id ก็เอาตัวท้ายสุดของหน้า — ช่องพิมพ์อยู่ล่างสุดเสมอ
        return self.page.locator('div[contenteditable="true"]').last

    # รอ ChatGPT พิมพ์คำตอบเก่าให้จบก่อนส่งคำถามใหม่ได้นานสุดกี่วินาที
    SETTLE_TIMEOUT = 240.0

    def wait_idle(self) -> bool:
        """รอจนกว่า ChatGPT จะพิมพ์คำตอบเก่าจบ — คืน True ถ้าว่างแล้ว

        **ต้องเรียกก่อนส่งคำถามใหม่ทุกครั้ง** ระหว่างที่มันกำลังพิมพ์ ช่องพิมพ์ถูก
        ล็อก ข้อความที่เราพิมพ์ลงไปจะหายเฉยๆ แล้วเราจะยืนรอคำตอบที่ไม่มีวันมา

        เจอจริง 23 ส.ค. 2026 เวลา 01:32 — ตัวรอคำตอบออกก่อนกำหนดตอนข้อความมี
        2,738 ตัว (เพราะทางลัด "รูปนิ่งแล้ว") แล้วเราส่งคำถามถัดไปทันที ทั้งที่
        GPT ยังพิมพ์ต่อจนถึง 5,084 ตัว ผลคืองานค้างรอ 10 นาทีแล้วล้ม
        """
        start = time.time()
        told = False
        while time.time() - start < self.SETTLE_TIMEOUT:
            if not self.state().get("streaming"):
                if told:
                    self.log(f"  GPT พิมพ์จบแล้ว ({int(time.time() - start)} วิ) — ส่งคำถามต่อได้")
                return True
            if not told:
                told = True
                self.log("  GPT ยังพิมพ์คำตอบก่อนหน้าไม่จบ — รอให้จบก่อนค่อยถามต่อ")
            time.sleep(1.0)
        self.log(f"  รอ {self.SETTLE_TIMEOUT:.0f} วิแล้ว GPT ยังพิมพ์ไม่จบ — ส่งคำถามต่อเลย")
        return False

    def send(self, text: str) -> None:
        # ห้ามพิมพ์ทับตอนมันยังตอบอยู่ — ดูเหตุผลเต็มที่ wait_idle
        self.wait_idle()
        box = self.composer()
        if not box.count():
            raise ChatGPTError("ไม่พบช่องพิมพ์ข้อความ")
        # เคลียร์แผ่นคลุมก่อนกดเสมอ — ถ้าไม่ทำจะได้ Timeout ที่ไม่บอกสาเหตุจริง
        if not self.clear_overlays():
            raise ChatGPTError(
                "มีกล่องโต้ตอบของ ChatGPT คลุมหน้าจออยู่ ปิดเองไม่สำเร็จ — "
                "เปิดหน้าต่างเบราว์เซอร์ ปิดกล่องนั้นด้วยมือ แล้วสั่ง /retry"
            )
        box.click()
        time.sleep(0.4)
        # พิมพ์ทีละบรรทัดแล้วขึ้นบรรทัดใหม่ด้วย Shift+Enter
        # ถ้าพิมพ์ \n ตรงๆ ช่องนี้จะถือว่าเป็นการกดส่งทันทีตั้งแต่บรรทัดแรก
        lines = text.split("\n")
        for index, line in enumerate(lines):
            if line:
                self.page.keyboard.type(line, delay=4)
            if index < len(lines) - 1:
                self.page.keyboard.press("Shift+Enter")
        time.sleep(0.5)

        # **ยืนยันว่าข้อความลงไปในช่องจริงก่อนกดส่ง**
        #
        # ของเดิมพิมพ์แล้วกด Enter เลยโดยไม่ดูว่าตัวอักษรลงช่องไหม ถ้าคลิกไม่โดน
        # ช่องจริง (หน้าเปลี่ยนโครงสร้าง / มีแบนเนอร์คั่น) การพิมพ์จะหายไปเฉยๆ
        # แล้ว Enter บนช่องว่างไม่ทำอะไร → กลายเป็น "ส่งแล้วไม่ตอบ" ทั้งที่
        # ไม่เคยส่งอะไรออกไปเลย — วินิจฉัยผิดทางมาทั้งวัน 12 ส.ค.
        typed = (box.inner_text() or "").strip()
        if not typed:
            self.log("  พิมพ์แล้วช่องยังว่าง — คลิกใหม่แล้วพิมพ์ซ้ำ")
            box.click()
            time.sleep(0.6)
            self.page.keyboard.type(text.replace("\n", " ")[:3000], delay=6)
            time.sleep(0.6)
            typed = (box.inner_text() or "").strip()
        if not typed:
            raise ChatGPTError(
                "พิมพ์ข้อความลงช่องของ ChatGPT ไม่ได้ — หน้าอาจมีแบนเนอร์คั่น "
                "หรือช่องพิมพ์เปลี่ยนโครงสร้าง (ยังไม่ได้ส่งอะไรออกไป)"
            )

        before = self.state()["replyCount"]
        # ปุ่มส่งจะโผล่ก็ต่อเมื่อช่องมีข้อความ — ถ้ามีให้กดปุ่มตรงๆ แม่นกว่า Enter
        send_button = self.page.locator(
            'button[data-testid="send-button"]:visible'
        ).first
        if send_button.count():
            send_button.click()
        else:
            self.page.keyboard.press("Enter")
        self._wait_started(before)

    # รอบท้ายๆ ของแชทเดียวกันเริ่มตอบช้ากว่ารอบแรกมาก (บริบทยาวขึ้น + มีรูปแนบ)
    # 30 วิเดิมสั้นเกินจนล้มซ้ำที่ขั้น "ขอบทพูด" ทุกครั้ง 4/4 งาน เมื่อ 11–12 ส.ค.
    START_TIMEOUT = 90.0
    # ถ้าเงียบเกินครึ่งทาง ให้ลองกดส่งซ้ำหนึ่งครั้ง — บางทีปุ่มส่งยังไม่พร้อม
    # ตอนกด Enter ครั้งแรก (ช่องเพิ่งโหลดเสร็จ) ข้อความจึงค้างอยู่ในช่องเฉยๆ
    RESEND_AFTER = 35.0

    def _wait_started(self, before: int) -> None:
        """ยืนยันว่าข้อความถูกส่งจริง — ไม่ใช่เดาจากการกด Enter ผ่าน"""
        start = time.time()
        resent = False
        while time.time() - start < self.START_TIMEOUT:
            state = self.state()
            if state["streaming"] or state["replyCount"] > before:
                if resent:
                    self.log("  กดส่งซ้ำแล้วเริ่มตอบ")
                return
            if not resent and time.time() - start > self.RESEND_AFTER:
                resent = True
                self.log("  ยังไม่เริ่มตอบ — ลองกดส่งอีกครั้ง")
                try:
                    self.page.keyboard.press("Enter")
                except Exception as error:                       # noqa: BLE001
                    self.log(f"  กดส่งซ้ำไม่ได้: {error}")
            time.sleep(0.5)
        raise ChatGPTError(
            f"กดส่งแล้วแต่ ChatGPT ไม่เริ่มตอบภายใน {self.START_TIMEOUT:.0f} วินาที"
        )

    def wait_reply(self, after: int | None = None, previous: str = "") -> str:
        """รอจนตอบจบแล้วคืนข้อความล่าสุด

        ดูสองอย่างประกอบกัน: ปุ่มหยุดหายไป **และ** ข้อความไม่ยาวขึ้นอีกแล้ว
        ดูอย่างเดียวไม่พอ — ปุ่มหยุดแวบหายระหว่างคิดได้ ส่วนข้อความก็นิ่งชั่วครู่
        ตอนกำลังจะพิมพ์ย่อหน้าถัดไป

        แต่ห้ามให้ "ยังสตรีมอยู่" มีอำนาจยับยั้งได้ตลอดกาล — เจอจริงว่ารูปสตอรีบอร์ด
        ขึ้นครบแล้วแต่ปุ่มหยุดยังไม่หาย (หรือข้อความในบล็อกยังกระพริบเพราะมีตัวจับเวลา
        เดินอยู่) ทำให้ยืนรอต่อจนหมดเวลาทั้งที่งานเสร็จไปแล้ว จึงเพิ่มทางออก:
        **ถ้ารูปขึ้นแล้วและจำนวนนิ่งนานพอ ให้ถือว่าเสร็จ ไม่ต้องสนใจปุ่มหยุด**

        `after` = จำนวนคำตอบในแชท **ก่อน** ส่งคำถาม · `previous` = ข้อความของคำตอบ
        ก้อนสุดท้ายตอนนั้น

        **ต้องส่งสองค่านี้มาเสมอ ไม่งั้นจะคืนคำตอบเก่าโดยไม่มีอะไรฟ้อง**
        เจอจริง 22 ส.ค. 2026 เวลา 21:48 — ขอ "บทพูด" แล้ว 14 วินาทีต่อมาระบบบอกว่า
        "ตอบจบแล้ว 4,601 ตัวอักษร" ซึ่ง GPT พิมพ์ไม่ทันแน่ ของที่ได้คือ**คำตอบก้อน
        ก่อนหน้า** (คำสั่ง Flow ภาษาอังกฤษ + คำอธิบายของ GPT) แล้วถูกเก็บเป็นบทพูด
        722 คำ 54 ฉาก ไหลไปถึงหน้าอนุมัติของผู้ใช้
        สาเหตุ: เงื่อนไขจบดูแค่ "ข้อความนิ่งครบ 3 วินาที" ซึ่งคำตอบเก่าก็นิ่งอยู่แล้ว
        """
        started = time.time()
        deadline = started + REPLY_TIMEOUT
        last_text = ""
        last_images = 0
        quiet_since = started
        images_since = started
        beat = started
        told_waiting = False
        while time.time() < deadline:
            state = self.state()
            text = state["lastReply"]
            images = state.get("lastImages", 0)
            streaming = state["streaming"]
            waited = int(time.time() - started)

            # คำตอบก้อนนี้เป็น **ของใหม่** จริงไหม
            #
            # ยึดสองอย่าง: จำนวนคำตอบต้องเพิ่มขึ้น และเนื้อความต้องไม่ใช่ก้อนเดิม
            # (บางครั้งหน้าเว็บวาดใหม่แล้วจำนวนเพี้ยนชั่วคราว เลยเช็คเนื้อความคู่กัน)
            fresh = True
            if after is not None and state.get("replyCount", 0) <= after:
                fresh = False
            elif previous and text == previous:
                fresh = False

            # เขียนชีพจรเป็นระยะ — ห้ามปล่อยให้ขั้นนี้เป็นกล่องดำอีก
            # (เจอจริง: ค้างเกิน 5 นาทีโดยไม่มี log สักบรรทัด ไล่สาเหตุไม่ได้เลย
            #  ต้องนั่งรอให้หมดเวลา 600 วินาทีเพื่อจะได้เห็นบรรทัดแรก)
            if time.time() - beat >= HEARTBEAT_SECONDS:
                beat = time.time()
                mark = "" if fresh else " · ยังเป็นคำตอบเก่า"
                self.log(
                    f"  …รออยู่ {waited} วิ · สตรีม={streaming} "
                    f"ข้อความ={len(text)} ตัว · รูป={images} ใบ{mark}"
                )

            if not fresh:
                # ยังไม่มีคำตอบใหม่ — รีเซ็ตตัวจับเวลาทั้งหมด ห้ามนับว่านิ่ง
                if not told_waiting and waited > 5:
                    told_waiting = True
                    self.log("  ยังเป็นคำตอบก้อนเดิม — รอคำตอบใหม่ต่อ")
                quiet_since = time.time()
                images_since = time.time()
                last_text, last_images = text, images
                time.sleep(POLL_SECONDS)
                continue

            if images != last_images or text != last_text:
                images_since = time.time()
            # รูปขึ้นแล้วและนิ่งพอ = เสร็จแล้ว ต่อให้ปุ่มหยุดยังค้างอยู่ก็ตาม
            #
            # **ต้องให้ข้อความนิ่งด้วย ไม่ใช่ดูแค่จำนวนรูป** — ทางลัดนี้เคยทำให้
            # ออกตอน GPT ยังพิมพ์อยู่ (2,738 ตัว ทั้งที่สุดท้ายยาว 5,084 ตัว)
            # แล้วเราไปส่งคำถามถัดไปทับ กลายเป็นงานค้าง 10 นาทีแล้วล้ม
            # (เจอจริง 23 ส.ค. 2026 เวลา 01:32)
            elif images and time.time() - images_since >= IMAGE_SETTLED_SECONDS:
                self.log(f"  รูปกับข้อความนิ่งแล้ว {images} ใบ ({waited} วิ) — ไม่รอปุ่มหยุดต่อ")
                return text

            # "ตอบแล้ว" นับรูปด้วย ไม่ใช่แค่ข้อความ — GPT สร้างภาพตอบเป็นรูปล้วน
            # ได้ ถ้านับแต่ข้อความจะยืนรอจนหมดเวลาแล้วโยน "ไม่ตอบ" ทั้งที่รูปมาแล้ว
            # (เจอจริง: รอครบ 300 วินาทีแล้วล้ม ทั้งที่ในแชทมีสตอรีบอร์ดขึ้นอยู่)
            if streaming or text != last_text or images != last_images:
                last_text, last_images = text, images
                quiet_since = time.time()
            elif (text or images) and time.time() - quiet_since >= REPLY_QUIET_SECONDS:
                self.log(f"  ตอบจบแล้ว ({len(text)} ตัวอักษร · รูป {images} ใบ)")
                return text
            time.sleep(POLL_SECONDS)

        # หมดเวลาแล้วยังไม่มีคำตอบใหม่ = **ล้มเหลว ห้ามคืนของเก่า**
        # คืนของเก่าไปคือส่งข้อมูลผิดให้ขั้นถัดไปโดยไม่มีใครรู้ ซึ่งแย่กว่าล้มเสียอีก
        state = self.state()
        stale = (after is not None and state.get("replyCount", 0) <= after) or (
            previous and state["lastReply"] == previous)
        if stale:
            raise ChatGPTError(
                f"ส่งคำถามแล้วแต่ ChatGPT ไม่ได้ตอบก้อนใหม่ภายใน {REPLY_TIMEOUT} วินาที"
            )
        if last_text or last_images:
            self.log(f"  หมดเวลารอ — ใช้เท่าที่ได้ (รูป {last_images} ใบ)")
            return last_text
        raise ChatGPTError(f"ChatGPT ไม่ตอบภายใน {REPLY_TIMEOUT} วินาที")

    def ask(self, text: str, images: list[Path] | None = None) -> str:
        if images:
            self.attach(images)
        # จำสภาพก่อนถามไว้ แล้วส่งให้ตัวรอใช้ยืนยันว่าได้ "คำตอบใหม่" จริง
        before = self.state()
        self.send(text)
        return self.wait_reply(
            after=before.get("replyCount", 0), previous=before.get("lastReply", ""),
        )

    # ------------------------------------------------- รูปที่ GPT ตอบกลับมา

    def reply_images(self) -> list[str]:
        """ที่อยู่รูปในคำตอบล่าสุด (เช่น storyboard ที่ GPT วาดให้)"""
        return self.page.evaluate(REPLY_IMAGES_JS)

    def wait_reply_images(self, minimum: int = 1, timeout: int = IMAGE_TIMEOUT) -> list[str]:
        """รอจนรูปในคำตอบขึ้นครบและ**นิ่งแล้ว**

        ข้อความตอบจบก่อนรูปเสมอ — GPT พิมพ์คำอธิบายเสร็จแล้วค่อยวาดรูปต่ออีกพักใหญ่
        ถ้าเช็คแค่ข้อความจะได้รูปไม่ครบ หรือได้ 0 ใบทั้งที่กำลังจะขึ้น
        """
        started = time.time()
        deadline = started + timeout
        seen: list[str] = []
        steady_since = started
        beat = started
        while time.time() < deadline:
            # เช็คคำปฏิเสธก่อน — ถ้า ChatGPT บอกว่าสร้างภาพไม่ได้ รูปจะไม่มีวันมา
            # การยืนรอต่อจนครบ 10 นาทีคือเสียเวลาเปล่าและดูเหมือนโปรแกรมค้าง
            if not seen and image_refused(self.state()["lastReply"]):
                self.log("  ChatGPT ปฏิเสธการสร้างภาพ — เลิกรอ")
                return []
            urls = self.reply_images()
            if time.time() - beat >= HEARTBEAT_SECONDS:
                beat = time.time()
                self.log(f"  …รอรูป {int(time.time() - started)} วิ · เห็นแล้ว {len(urls)} ใบ")
            if urls != seen:
                seen = urls
                steady_since = time.time()
            elif len(seen) >= minimum and time.time() - steady_since >= IMAGE_QUIET_SECONDS:
                return seen
            time.sleep(POLL_SECONDS)
        return seen

    def download_reply_images(self, folder: Path, prefix: str = "frame") -> list[Path]:
        """ดาวน์โหลดรูปจากคำตอบเก็บลงเครื่อง

        ใช้ `page.request` เพราะรูปของ ChatGPT ต้องมีคุกกี้ล็อกอินถึงจะโหลดได้
        โหลดด้วย urllib ธรรมดาจะได้ 403
        """
        folder.mkdir(parents=True, exist_ok=True)
        saved: list[Path] = []
        for index, url in enumerate(self.reply_images(), 1):
            body = b""
            try:
                response = self.page.request.get(url, timeout=120_000)
                if response.ok:
                    body = response.body()
                else:
                    self.log(f"  โหลดรูปที่ {index} ไม่ได้: HTTP {response.status}")
            except Exception as error:
                self.log(f"  โหลดรูปที่ {index} ไม่ได้: {error}")
            if not body:
                # ทางสำรอง: ถ่ายจากหน้าจอเอาเลย ได้ภาพเสมอไม่ว่า url จะโหลดได้ไหม
                # (เผื่อ ChatGPT เปลี่ยนไปใช้ blob: หรือคุกกี้ของ request หลุด)
                body = self._shoot_image(url, index)
            if not body:
                continue
            suffix = ".png" if body[:8].startswith(b"\x89PNG") else ".jpg"
            path = folder / f"{prefix}-{index:02d}{suffix}"
            path.write_bytes(body)
            saved.append(path)
        self.log(f"  เก็บรูปจากคำตอบได้ {len(saved)} ใบ")
        return saved

    def _shoot_image(self, url: str, index: int) -> bytes:
        """ถ่ายรูปจาก <img> บนหน้าจอโดยตรง — ใช้เมื่อโหลดตาม url ไม่สำเร็จ"""
        try:
            target = self.page.locator(f'img[src="{url}"]').first
            if not target.count():
                return b""
            target.scroll_into_view_if_needed(timeout=10_000)
            shot = target.screenshot(timeout=30_000)
            self.log(f"  รูปที่ {index}: โหลดตามลิงก์ไม่ได้ ถ่ายจากหน้าจอแทน")
            return shot
        except Exception as error:
            self.log(f"  รูปที่ {index}: ถ่ายจากหน้าจอก็ไม่ได้: {error}")
            return b""


# ------------------------------------------------------------ ตัดเอาเฉพาะ prompt

# GPT มักตอบเป็นบล็อกโค้ดหรือรายการมีหมายเลข — ดึงเฉพาะเนื้อ prompt ออกมา
CODE_BLOCK_RE = re.compile(r"```(?:[a-zA-Z]*\n)?(.*?)```", re.S)
NUMBERED_RE = re.compile(r"^\s*(?:\d+[.)]|[-•])\s+(.{15,})$", re.M)


# หัวข้อฉากที่ GPT ใช้จริง — "SCENE 1", "Scene 2:", "ซีน 3"
# ตัดแบบ lookahead เพื่อให้หัวข้อติดไปกับเนื้อของฉากนั้น ไม่ใช่หายไปกับตัวคั่น
SCENE_HEAD_RE = re.compile(r"(?=(?:\bSCENE\b|\bScene\b|ซีน)\s*\d+\b)")


def extract_prompts(reply: str) -> list[str]:
    """แยก prompt ออกจากคำตอบ

    ลำดับการลอง: บล็อกโค้ด → หัวข้อ SCENE → รายการมีหมายเลข → ทั้งก้อน

    ต้องมีชั้น "หัวข้อ SCENE" ด้วย เพราะ GPT ตัวนี้ตอบเป็นความเรียงยาวๆ ที่แบ่ง
    SCENE 1–5 ไว้ในเนื้อ **โดยไม่ใส่บล็อกโค้ดเลย** (วัดจริง: 7,776 ตัว 0 บล็อกโค้ด)
    ถ้าไม่ดักชั้นนี้จะได้ prompt ก้อนเดียวยาวเหยียด เอาไปวางใน Flow ทีเดียวไม่ได้
    """
    blocks = [b.strip() for b in CODE_BLOCK_RE.findall(reply) if b.strip()]
    if blocks:
        # บล็อกเดียวที่มีหลายบรรทัด = หลาย prompt เรียงกัน
        if len(blocks) == 1 and "\n" in blocks[0]:
            lines = [l.strip() for l in blocks[0].splitlines() if len(l.strip()) > 15]
            if len(lines) > 1:
                return lines
        return blocks

    scenes = [part.strip() for part in SCENE_HEAD_RE.split(reply or "")]
    # ชิ้นแรกมักเป็นคำนำก่อนถึงฉากแรก ตัดทิ้งด้วยเกณฑ์ "ต้องขึ้นต้นด้วยหัวข้อฉาก"
    scenes = [s for s in scenes if len(s) > 60 and SCENE_HEAD_RE.match(s)]
    if len(scenes) > 1:
        return scenes

    numbered = [m.strip() for m in NUMBERED_RE.findall(reply)]
    if numbered:
        return numbered
    body = reply.strip()
    return [body] if body else []


STORYBOARD_GPT_URL = (
    "https://chatgpt.com/g/"
    "g-6a75eb744634819187f2cf52dcb0b7a3-naksraang-story-board-muue-aachiiph"
)

# ถามต่อในแชทเดิมหลังได้สตอรีบอร์ด — ข้อความนี้ผู้ใช้กำหนดมาเอง ห้ามแก้ถ้อยคำ
FLOW_PROMPT_ASK = (
    "ขอคำสั่งสำหรับสร้างคลิปใน flow omni "
    "มีบทบรรยายแบบเพื่อนรีวิวให้เพื่อน มีตัวหนังสือในคลิปด้วย"
)

# ข้อกำหนดเพิ่มที่**ต่อท้าย**ข้อความข้างบน — ไม่แตะถ้อยคำเดิมของผู้ใช้
#
# **ทำไมต้องมี** (26 ส.ค. 2026) ตรวจคลิป 24 ใบพบว่า 2 ใบไม่มีเสียงพูดเลย
# ไล่ไปที่คำสั่งแล้วพบสองสาเหตุคนละอัน
#   1. คำสั่งยาวเกินเพดาน 4,000 ตัว แล้วบรรทัดสั่งเสียงที่อยู่ท้ายฉากโดนตัดทิ้ง
#      (แก้ที่ `clip_app.build_one_clip_prompt` แล้ว — กันที่ให้บรรทัดเสียงก่อน)
#   2. **GPT ไม่ได้เขียนบรรทัดสั่งเสียงมาให้เลยตั้งแต่แรก** ← ข้อนี้แก้ตรงนี้
#      วัดจริง: ทีวี 55 V6C (25025138544) มีคำสั่ง 5 ฉาก แต่มีบรรทัดเสียงแค่ 1
#
# **ต้องระบุรูปแบบให้ตรงเป๊ะ** เพราะฝั่งที่รวมคำสั่งต้องหาบรรทัดนี้ให้เจอเพื่อกัน
# ไม่ให้โดนตัด ถ้า GPT เขียนคนละรูปแบบทุกครั้ง ตัวกันจะหาไม่เจอแล้วกลับไปพังเหมือนเดิม
FLOW_AUDIO_RULE = (
    "\n\nข้อกำหนดเพิ่มเติมที่ห้ามข้าม:\n"
    "**ทุกฉากต้องมีบรรทัดสั่งเสียงพูดภาษาไทย** เขียนเป็นบรรทัดแยกท้ายฉากนั้น "
    "ในรูปแบบนี้เป๊ะๆ (ขึ้นต้นด้วยคำว่า Audio: เสมอ):\n"
    "Audio: Generate Thai voice-over narration: \"<คำพูดของฉากนั้น>\"\n"
    "ห้ามมีฉากไหนขาดบรรทัดนี้ — ฉากที่ขาดจะกลายเป็นคลิปเงียบซึ่งใช้งานไม่ได้"
)

# ฉากที่ต้องมีบรรทัดสั่งเสียง — ใช้ตรวจว่า GPT ตอบมาครบไหมก่อนเอาไปใช้จริง
FLOW_AUDIO_LINE_RE = re.compile(r"^\s*Audio\s*[:：]", re.I | re.M)


def flow_prompts_missing_audio(prompts: list[str]) -> list[int]:
    """ฉากไหนไม่มีบรรทัดสั่งเสียง — คืนลำดับฉาก (เริ่มที่ 1)

    **ไม่นับชุดแรกถ้าเป็นคำเกริ่น** GPT มักใส่ย่อหน้าอธิบายก่อนถึงฉากแรก
    ซึ่งไม่ใช่ฉากจึงไม่ต้องมีเสียง — ดูจากว่ามีคำว่า SCENE/ซีน อยู่ต้นก้อนไหม
    """
    missing = []
    for index, text in enumerate(prompts or [], start=1):
        if not re.search(r"\b(SCENE|ซีน)\s*\d", (text or "")[:200], re.I):
            continue                      # ก้อนเกริ่น ไม่ใช่ฉาก
        if not FLOW_AUDIO_LINE_RE.search(text or ""):
            missing.append(index)
    return missing

# ขอ "บทพูด" แยกออกมาต่างหาก
#
# คำสั่งสำหรับ Google Flow ยาวหลายพันตัวและเต็มไปด้วยศัพท์เทคนิค (มุมกล้อง แสง
# ความยาวฉาก) ซึ่งผู้ใช้ไม่ได้อยากอ่านในแชท — สิ่งที่อยากตรวจคือ **คำพูดที่จะได้ยิน
# ในคลิป** จึงขอแยกออกมาเป็นอีกคำตอบ แทนที่จะไปเดาแกะจากในคำสั่ง
# (แกะเองพังแน่ เพราะ GPT เขียนรูปแบบไม่เหมือนกันทุกครั้ง)
# ความยาวบทพูด — คลิป 10 วินาทีพูดได้จริงราวนี้ ยาวกว่านี้เสียงจะล้นคลิป
SCRIPT_MIN_WORDS = 25
SCRIPT_MAX_WORDS = 35

SCRIPT_ASK = (
    "ขอเฉพาะ **บทพูดในคลิป** ที่จะได้ยินเป็นเสียง แยกตามฉาก\n"
    f"คลิปยาว 10 วินาที บทพูด**รวมทั้งคลิปต้องอยู่ที่ {SCRIPT_MIN_WORDS}–"
    f"{SCRIPT_MAX_WORDS} คำเท่านั้น** ห้ามเกิน\n"
    "ตอบเป็นรายการสั้นๆ ฉากละบรรทัด ขึ้นต้นด้วยเลขฉาก\n"
    "ไม่ต้องมีคำอธิบายมุมกล้อง ไม่ต้องมีคำสั่งเทคนิค ไม่ต้องมีหัวข้อนำ "
    "ไม่ต้องบอกจำนวนคำ"
)

# มุมเปิดเรื่อง — หมุนเวียนไปตามสินค้า ไม่ให้ทุกคลิปเปิดแบบเดียวกัน
#
# **ทำไมต้องมี** วัดจริง 23 ส.ค. 2026: บทพูด 27 ชิ้นในคลัง **22 ชิ้นขึ้นต้นด้วยคำว่า
# "แก"** (81%) และปิดท้ายด้วยสูตรเดียวกันเกือบทั้งหมด ("...น่าโดนมาก!") ส่วนสินค้า
# ตระกูลเดียวกันบทพูดซ้ำกัน 34–52% เพราะสเปกเหมือนกัน จุดเด่นจึงถูกคัดมาชุดเดียวกัน
# แล้ว GPT ก็เขียนตามสูตรประจำของมัน
#
# คนดูเลื่อนเจอคลิปเราสามคลิปติดกันแล้วรู้สึกว่า "อันเดิม" = เลื่อนผ่าน
#
# เลือกมุมด้วยรหัสสินค้า ไม่ใช่สุ่ม — สินค้าเดิมสั่งซ้ำจะได้มุมเดิม ผลจึงคาดเดาได้
# และเวลาไล่ปัญหาไม่ต้องเดาว่ารอบนั้นได้มุมไหน
SCRIPT_ANGLES = (
    "เปิดด้วย **ปัญหาที่คนเจอ** ก่อน แล้วค่อยเฉลยว่าของชิ้นนี้แก้ให้",
    "เปิดด้วย **คำถามชวนคิด** ที่คนกลุ่มเป้าหมายตอบในใจว่าใช่",
    "เปิดด้วย **ตัวเลขที่น่าตกใจ** ของสินค้าเลย ไม่ต้องเกริ่น",
    "เปิดด้วย **สถานการณ์ในชีวิตจริง** ที่จะได้ใช้ของชิ้นนี้",
    "เปิดด้วย **การเปรียบเทียบกับของเดิม** ที่คนใช้อยู่",
    "เปิดด้วย **คำชวนดูตรงๆ แบบเพื่อนบอกเพื่อน** ไม่ต้องเกริ่นยาว",
)


def script_ask(avoid: list[str] | None = None, seed: str = "") -> str:
    """คำสั่งขอบทพูด + ข้อห้ามไม่ให้เขียนซ้ำของเดิม

    `avoid` = ประโยคเปิดของคลิปก่อนหน้า · `seed` = รหัสสินค้า ใช้เลือกมุมเปิด
    """
    parts = [SCRIPT_ASK]
    if seed:
        angle = SCRIPT_ANGLES[sum(ord(c) for c in str(seed)) % len(SCRIPT_ANGLES)]
        parts.append(f"\n**มุมเปิดของคลิปนี้**: {angle}")
    lines = [text.strip() for text in (avoid or []) if text and text.strip()][:8]
    if lines:
        parts.append(
            "\n**ห้ามเปิดเรื่องซ้ำกับคลิปก่อนหน้าเหล่านี้** (คนดูเลื่อนเจอติดกัน "
            "แล้วจะรู้สึกว่าเป็นคลิปเดิม):\n"
            + "\n".join(f"  · {text[:60]}" for text in lines)
            + "\nห้ามขึ้นต้นด้วยคำเดียวกับข้างบน และห้ามใช้ประโยคปิดแนวเดียวกัน"
        )
    return "".join(parts)


# อักษรไทยเฉลี่ยกี่ตัวต่อหนึ่งคำ ใช้ประมาณจำนวนคำจากความยาวข้อความ
#
# **ห้ามนับตามช่องว่าง** ภาษาไทยไม่เว้นวรรคระหว่างคำ ช่องว่างที่เห็นคือการคั่นวลี
# วัดของจริงแล้ว: บทพูดที่มี ~40 คำ นับตามช่องว่างได้แค่ 15 → ขึ้นว่า "สั้นไป"
# ทั้งที่ยาวเกินเกณฑ์ ถ้าเชื่อตัวเลขนั้นจะสั่งให้ GPT เขียนยาวขึ้นอีก
THAI_CHARS_PER_WORD = 5.5
_THAI_RE = re.compile(r"[฀-๿]")
_LATIN_WORD_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9'’\-]*")


def count_words(script) -> int:
    """ประมาณจำนวนคำในบทพูด — ไทยคิดจากจำนวนอักษร อังกฤษ/ตัวเลขนับเป็นคำตรงๆ

    เป็นค่าประมาณ ไม่ใช่ตัวตัดคำจริง — ที่ต้องการคือรู้ว่า "ยาวเกินคลิป 10 วินาที
    ไหม" ซึ่งความละเอียดระดับนี้พอ และไม่ต้องพึ่งไลบรารีตัดคำเพิ่ม
    """
    if isinstance(script, str):
        text = script
    else:
        text = " ".join(str(line) for line in (script or []))
    thai = len(_THAI_RE.findall(text))
    latin = len(_LATIN_WORD_RE.findall(text))
    return round(thai / THAI_CHARS_PER_WORD) + latin

# บรรทัดบทพูดของแต่ละฉาก — รับได้ทั้ง "1." "ฉาก 1:" "Scene 1 -"
SCRIPT_LINE_RE = re.compile(
    r"^\s*(?:ฉาก|scene)?\s*(\d+)\s*[.):\-–]\s*(.+?)\s*$", re.I | re.M
)


# หัวข้อฉากที่โผล่กลางบรรทัดได้ ใช้ตอนคำตอบไม่มีการขึ้นบรรทัดใหม่เลย
SCRIPT_INLINE_RE = re.compile(r"(?=(?:ฉาก|SCENE|Scene|ซีน)\s*\d+\s*[:：\-–])")


# คลิป 10 วินาทีมีได้กี่ฉาก — เกินนี้แปลว่าแกะผิด ไม่ใช่บทพูดยาว
SCRIPT_MAX_SCENES = 8

# ร่องรอยว่า "นี่ไม่ใช่บทพูด แต่เป็นคำสั่งเจนภาพ/คำอธิบายของ GPT"
_NOT_SCRIPT_RE = re.compile(
    r"\bSCENE\s*\d|\bSHOT\s*:|\bCAMERA\s*:|MASTER STYLE|\bPrompt\b|"
    r"\bCreate a\b|\bvertical 9:16\b|photorealistic|ข้อความบนภาพ",
    re.I,
)


def script_looks_wrong(script: list[str]) -> str:
    """บทพูดชุดนี้หน้าตาผิดปกติไหม — คืนคำอธิบายสั้นๆ ถ้าผิด คืนค่าว่างถ้าปกติ

    **ต้องมีด่านนี้** เพราะ `extract_script` ชั้นสุดท้ายออกแบบให้ "คืนทั้งก้อน"
    เมื่อแกะไม่ได้ ซึ่งดีเวลาคำตอบเป็นความเรียง แต่กลายเป็นช่องให้ของผิดไหลผ่าน
    เวลาได้คำตอบผิดก้อนมา

    เจอจริง 22 ส.ค. 2026: ระบบเก็บ "บทพูด" 54 ฉาก 722 คำ ซึ่งแท้จริงคือคำสั่ง
    เจนวิดีโอภาษาอังกฤษ + คำอธิบายของ GPT — ไหลไปถึงหน้าอนุมัติโดยมีแค่คำเตือน
    ตัวเล็กว่า "ยาวเกิน" ผู้ใช้ต้องมาเห็นเองว่ามันไม่ใช่บทพูด
    """
    if not script:
        return "ไม่มีบทพูดเลย"
    if len(script) > SCRIPT_MAX_SCENES:
        return f"ได้มา {len(script)} ฉาก คลิป 10 วินาทีมีได้ไม่เกิน {SCRIPT_MAX_SCENES}"
    words = count_words(script)
    if words > SCRIPT_MAX_WORDS * 3:
        return f"ยาว {words} คำ เกินเพดาน {SCRIPT_MAX_WORDS} คำหลายเท่า"
    text = "\n".join(script)
    found = _NOT_SCRIPT_RE.search(text)
    if found:
        return f"มีคำสั่งเจนภาพปนมา (“{found.group(0)}”)"
    return ""


def extract_script(reply: str) -> list[str]:
    """แยกบทพูดรายฉากออกจากคำตอบ

    ลองสามชั้นเพราะ GPT ตอบไม่เหมือนกันทุกครั้ง (วัดมาแล้วทั้งสามแบบ):
      1. ขึ้นต้นบรรทัดด้วยเลขฉาก — แบบที่ขอไป
      2. หัวข้อฉากอยู่กลางบรรทัดเดียวยาวๆ
      3. ความเรียงย่อหน้าเดียวไม่แบ่งฉากเลย — คืนทั้งก้อน **ไม่ใช่คืนค่าว่าง**
         เพราะเนื้อหายังใช้ได้ ผู้ใช้อ่านตรวจได้ ดีกว่าเห็นช่องเปล่าแล้วงง
    """
    text = (reply or "").strip()
    if not text:
        return []

    lines = [t.strip(' "“”') for _, t in SCRIPT_LINE_RE.findall(text)]
    lines = [line for line in lines if len(line) > 3]
    if len(lines) > 1:
        return lines

    parts = [p.strip(' -•"“”') for p in SCRIPT_INLINE_RE.split(text)]
    parts = [p for p in parts if len(p) > 8]
    if len(parts) > 1:
        return parts

    body = [
        line.strip(' -•"“”')
        for line in text.splitlines()
        if len(line.strip()) > 8 and not line.strip().startswith("#")
    ]
    return body or [text]


def make_storyboard(
    open_browser,
    product: str,
    highlights: list[str],
    images: list[Path],
    folder: Path,
    gpt_url: str = "",
    log=print,
    hidden: bool = True,
    # ข้อความสั่งเพิ่มที่แทรกก่อนบรรทัดสุดท้าย เช่นกรณีสินค้าปรับเปลี่ยนรูปทรงได้
    extra_ask: str = "",
    # ประโยคเปิดของคลิปก่อนหน้า — ส่งไปบอก GPT ว่าห้ามเขียนซ้ำแนวนี้อีก
    avoid_openers: list[str] | None = None,
) -> dict:
    """ส่ง ชื่อสินค้า + รูป + จุดเด่น เข้า GPT นักสร้างสตอรีบอร์ด แล้วเก็บรูปที่ได้

    คืน {"chat_url", "reply", "frames": [path, …]}
    """
    from playwright.sync_api import sync_playwright

    # บอกจำนวนรูปและเลขกำกับ เพื่อให้ GPT อ้างอิงได้ว่าฉากไหนใช้รูปใบไหน
    # (ไม่บอกเลข มันจะพูดลอยๆ ว่า "ใช้รูปที่แนบ" แล้วเราตรวจไม่ได้ว่าตรงใบไหน)
    ask = (
        f"สินค้า: {product}\n\n"
        "จุดเด่น:\n" + "\n".join(f"- {text}" for text in highlights) + "\n\n"
        f"แนบรูปสินค้าจริงมาให้ {len(images)} ใบ (เรียงเป็นรูปที่ 1–{len(images)})\n"
        + (extra_ask + "\n" if extra_ask else "")
        + "ช่วยทำ storyboard สำหรับคลิปโฆษณาสั้น แล้ว**ออกมาเป็นรูปภาพ** ให้ด้วย"
    )

    with sync_playwright() as playwright:
        browser = open_browser(playwright, hidden=hidden)
        page = browser.pages[0] if browser.pages else browser.new_page()
        try:
            session = ChatGPTSession(page, log=log)
            session.open(gpt_url or STORYBOARD_GPT_URL)

            log(f"ส่งสินค้า + รูป {len(images)} ใบ + จุดเด่น {len(highlights)} ข้อ")
            reply = session.ask(ask, images)

            # ข้อความจบก่อนรูปเสมอ — ต้องรอรูปแยกอีกที ไม่งั้นได้ 0 ใบ
            log("รอ GPT วาดสตอรีบอร์ด…")
            urls = session.wait_reply_images(minimum=1)

            # ตัวกรองของ ChatGPT ปฏิเสธเป็นครั้งคราวแม้เนื้อหาไม่มีอะไร (ตัวมันเองยัง
            # บอกให้ "retry") — ลองใหม่รอบเดียวโดยไม่แนบรูป ให้บรรยายจากข้อความแทน
            refused = False
            refusal_text = ""
            if not urls and image_refused(session.state()["lastReply"]):
                refusal_text = session.state()["lastReply"][:300]
                log("  โดนตัวกรองปฏิเสธ — ลองใหม่แบบไม่แนบรูปสินค้า")
                reply = session.ask(
                    "ขอใหม่อีกครั้ง คราวนี้ไม่ต้องอ้างอิงรูปที่แนบ "
                    "วาด storyboard เป็นภาพสเก็ตช์ช่องๆ (ไม่ต้องมีคนหรือโลโก้แบรนด์) "
                    f"สำหรับคลิปโฆษณาสินค้า: {product}"
                )
                urls = session.wait_reply_images(minimum=1)
                refused = not urls

            frames = [] if refused else session.download_reply_images(
                folder, prefix="storyboard"
            )

            # ถามต่อ **ในแชทเดิม** เพื่อขอคำสั่งไปใช้ใน Google Flow
            # ต้องอยู่แชทเดียวกัน GPT จะได้อ้างอิงสตอรีบอร์ดที่เพิ่งคุยกันไว้
            # ทำแม้ตอนวาดภาพไม่ผ่าน — คำสั่งข้อความยังใช้ได้ ไม่ควรทิ้งไปทั้งงาน
            # **รอบที่ 2 และ 3 ห้ามลากรอบที่ทำสำเร็จแล้วล้มตาม**
            #
            # เจอจริง 11 ส.ค.: GPT วาดสตอรีบอร์ดเสร็จ (storyboard-01.png ลงดิสก์
            # แล้ว) ได้คำสั่ง Flow ครบ 6 ชุด แล้วรอบขอบทพูดไม่ตอบ → error หลุด
            # ออกไปทั้งก้อน → ผู้เรียกไม่ได้เรียก save_storyboard เลย →
            # run.json ยังเป็น 0 ภาพ ทั้งที่ไฟล์อยู่ครบ → ไม่มีอะไรส่งเข้าแชท
            # ผู้ใช้เห็นแค่ "ล้มเหลว" ทั้งที่ของเสร็จไปแล้ว 2 ใน 3 ส่วน
            #
            # หลักการเดียวกับที่ save_product ใช้อยู่แล้ว: เก็บของที่ได้ทันที
            # อย่ารอเก็บทีเดียวตอนจบ เพราะขั้นหลังล้มได้เสมอ
            warnings: list[str] = []

            log("ขอคำสั่งสำหรับ Google Flow ต่อในแชทเดิม")
            flow_reply, flow_prompts = "", []
            try:
                flow_reply = session.ask(FLOW_PROMPT_ASK + FLOW_AUDIO_RULE)
                flow_prompts = extract_prompts(flow_reply)
                log(f"  ได้คำสั่ง {len(flow_prompts)} ชุด")
                # ---- ตรวจว่ามีบรรทัดสั่งเสียงครบทุกฉากไหม -------------------
                #
                # **ต้องรู้ตรงนี้ ไม่ใช่ไปรู้ตอนคลิปเจนเสร็จแล้วเงียบ** — ตอนนั้น
                # เสียเครดิต Flow ไปแล้วและต้องเจนใหม่ทั้งรอบ ส่วนตรงนี้แค่ถามซ้ำ
                # ในแชทเดิม ไม่มีต้นทุนอะไรเลยนอกจากเวลาไม่กี่วินาที
                #
                # ขอซ้ำครั้งเดียวพอ — ถ้ายังไม่ครบแปลว่า GPT ไม่ยอมทำตาม
                # การวนขอไม่รู้จบมีแต่จะกินเวลาโดยไม่ได้อะไรเพิ่ม
                missing = flow_prompts_missing_audio(flow_prompts)
                if missing:
                    log(f"  ⚠️ ฉาก {missing} ไม่มีบรรทัดสั่งเสียงพูด — ขอใหม่อีกครั้ง")
                    retry = session.ask(
                        "คำสั่งที่ให้มายังขาดบรรทัดสั่งเสียงพูดในบางฉาก\n"
                        f"ฉากที่ขาดคือ: {', '.join(str(n) for n in missing)}\n"
                        "ขอคำสั่งชุดเดิมใหม่ทั้งหมด โดย**ทุกฉากต้องมี**บรรทัดนี้"
                        "ท้ายฉาก:\n"
                        "Audio: Generate Thai voice-over narration: \"<คำพูดของฉากนั้น>\""
                    )
                    again = extract_prompts(retry)
                    still = flow_prompts_missing_audio(again)
                    if again and len(still) < len(missing):
                        flow_reply, flow_prompts = retry, again
                        log(f"  ได้คำสั่งใหม่ {len(again)} ชุด · ยังขาดเสียง {len(still)} ฉาก")
                    else:
                        # ของใหม่ไม่ได้ดีกว่าเดิม เก็บของเดิมไว้ แต่**ต้องไม่เงียบ**
                        warnings.append(
                            f"คำสั่ง Flow ยังขาดบรรทัดสั่งเสียงพูด {len(missing)} ฉาก "
                            "— คลิปที่ได้อาจไม่มีเสียงพูด")
                        log("  ⚠️ ขอใหม่แล้วยังไม่ครบ — เก็บของเดิมไว้และแจ้งเตือน")
            except Exception as error:                          # noqa: BLE001
                warnings.append(f"ขอคำสั่ง Flow ไม่สำเร็จ ({error})")
                log(f"  ⚠️ ขอคำสั่ง Flow ไม่สำเร็จ: {error} — เก็บสตอรีบอร์ดที่ได้ไว้ก่อน")

            # บทพูดขอแยกอีกรอบ — คำสั่ง Flow ยาวและเป็นศัพท์เทคนิค ไม่เหมาะให้คนอ่าน
            # ตรวจในแชท ส่วนบทพูดคือสิ่งที่ผู้ใช้ต้องอนุมัติจริงๆ
            log("ขอบทพูดในคลิปแยกอีกรอบ")
            script_reply, script = "", []
            try:
                ask_script = script_ask(avoid_openers, seed=folder.name)
                script_reply = session.ask(ask_script)
                script = extract_script(script_reply)
                bad = script_looks_wrong(script)
                if bad:
                    # ได้ของที่ไม่ใช่บทพูด — ขอใหม่หนึ่งครั้งพร้อมบอกว่าผิดตรงไหน
                    log(f"  ⚠️ ที่ได้มาไม่ใช่บทพูด ({bad}) — ขอใหม่อีกครั้ง")
                    script_reply = session.ask(
                        f"อันนั้นไม่ใช่บทพูด ({bad})\n\n{ask_script}"
                    )
                    script = extract_script(script_reply)
                    bad = script_looks_wrong(script)
                if bad:
                    raise ChatGPTError(f"ขอบทพูดแล้วยังไม่ได้บทพูดจริง ({bad})")
                log(f"  ได้บทพูด {len(script)} ฉาก")
            except Exception as error:                          # noqa: BLE001
                warnings.append(f"ขอบทพูดไม่สำเร็จ ({error})")
                log(f"  ⚠️ ขอบทพูดไม่สำเร็จ: {error} — เก็บของที่ได้ไว้ก่อน")

            return {
                "chat_url": session.state()["url"],
                "reply": reply,
                "frames": [str(path) for path in frames],
                "refused": refused,
                "refusal_text": refusal_text,
                "flow_reply": flow_reply,
                "flow_prompts": flow_prompts,
                "script_reply": script_reply,
                "script": script,
                # ผู้เรียกเอาไปบอกผู้ใช้ว่าได้ของไม่ครบ และขาดอะไร
                "warnings": warnings,
            }
        finally:
            browser.close()


def revise(
    open_browser,
    chat_url: str,
    instruction: str,
    target: str,
    folder: Path,
    log=print,
    hidden: bool = True,
) -> dict:
    """กลับเข้าแชทเดิมแล้วสั่งแก้ตามที่ผู้ใช้พิมพ์มา

    ต้องเป็น **แชทเดิม** เท่านั้น GPT จะได้เห็นสตอรีบอร์ดและบทพูดที่เพิ่งทำไว้
    เปิดแชทใหม่แล้วสั่ง "แก้ฉาก 3" มันไม่รู้ว่าฉาก 3 คืออะไร

    target = "storyboard" → รอรูปชุดใหม่ ·  "script" → รอบทพูดชุดใหม่
    """
    from playwright.sync_api import sync_playwright

    if not chat_url:
        raise ChatGPTError("ไม่มีลิงก์แชทเดิม แก้ต่อไม่ได้")

    if target == "storyboard":
        ask = (
            "แก้สตอรีบอร์ดตามนี้แล้ววาดภาพใหม่ให้ด้วย (ตอบเป็นรูปภาพ):\n"
            f"{instruction}"
        )
    else:
        ask = (
            "แก้บทพูดตามนี้ แล้วตอบบทพูดชุดใหม่ทั้งหมด "
            "แยกตามฉาก ฉากละบรรทัด ขึ้นต้นด้วยเลขฉาก ไม่ต้องมีคำอธิบายอื่น\n"
            # ย้ำเพดานคำทุกครั้งที่แก้ ไม่งั้นแก้ไปแก้มาบทจะยาวขึ้นเรื่อยๆ
            # จนเสียงล้นคลิป 10 วินาที
            f"รวมทั้งคลิปต้องอยู่ที่ {SCRIPT_MIN_WORDS}–{SCRIPT_MAX_WORDS} คำเท่านั้น\n"
            f"{instruction}"
        )

    with sync_playwright() as playwright:
        browser = open_browser(playwright, hidden=hidden)
        page = browser.pages[0] if browser.pages else browser.new_page()
        try:
            session = ChatGPTSession(page, log=log)
            session.open(chat_url)
            log(f"สั่งแก้{'สตอรีบอร์ด' if target == 'storyboard' else 'บทพูด'}")
            reply = session.ask(ask)

            result = {"chat_url": session.state()["url"], "reply": reply}
            if target == "storyboard":
                log("รอ GPT วาดใหม่…")
                urls = session.wait_reply_images(minimum=1)
                if not urls and image_refused(session.state()["lastReply"]):
                    result["refused"] = True
                    result["refusal_text"] = session.state()["lastReply"][:300]
                    result["frames"] = []
                    return result
                # ตั้งชื่อไม่ให้ทับของเดิม จะได้เทียบก่อน/หลังแก้ได้
                stamp = datetime.now().strftime("%H%M%S")
                frames = session.download_reply_images(folder, prefix=f"storyboard-{stamp}")
                result["frames"] = [str(path) for path in frames]
            else:
                result["script"] = extract_script(reply)
                log(f"  ได้บทพูดใหม่ {len(result['script'])} ฉาก")
            return result
        finally:
            browser.close()


def run_stage(
    open_browser,
    gpt_url: str,
    product: str,
    highlights: list[str],
    images: list[Path],
    log=print,
    hidden: bool = True,
) -> dict:
    """ทำช่วง ChatGPT ทั้งท่อนตามผัง คืน prompt ทั้งสองชุด"""
    from playwright.sync_api import sync_playwright

    first_ask = (
        f"สินค้า: {product}\n\n"
        "จุดขาย:\n" + "\n".join(f"- {h}" for h in highlights) + "\n\n"
        "จากรูปสินค้าที่แนบมา ช่วยเขียน prompt ภาษาอังกฤษสำหรับ **สร้างภาพ** "
        "โฆษณาสินค้านี้ใน Google Flow ให้หน่อย ตอบเป็นบล็อกโค้ด บรรทัดละ prompt"
    )
    second_ask = (
        "ต่อจากภาพชุดเดิม ช่วยเขียน prompt ภาษาอังกฤษสำหรับ **สร้างวิดีโอ** "
        "โฆษณาความยาว 8 วินาทีต่อฉาก ใน Google Flow "
        "ให้สอดคล้องกับภาพและจุดขายด้านบน ตอบเป็นบล็อกโค้ด บรรทัดละ prompt"
    )

    with sync_playwright() as playwright:
        browser = open_browser(playwright, hidden=hidden)
        page = browser.pages[0] if browser.pages else browser.new_page()
        try:
            session = ChatGPTSession(page, log=log)
            session.open(gpt_url)

            log("ส่งรูป + จุดขายเข้า ChatGPT")
            image_reply = session.ask(first_ask, images)
            image_prompts = extract_prompts(image_reply)
            log(f"  ได้ prompt สำหรับเจนรูป {len(image_prompts)} อัน")

            # รอบสองอยู่แชทเดิม เพราะต้องอ้างอิงภาพที่คุยกันไว้รอบแรก
            log("ถามต่อในแชทเดิมเพื่อขอ prompt วิดีโอ")
            video_reply = session.ask(second_ask)
            video_prompts = extract_prompts(video_reply)
            log(f"  ได้ prompt สำหรับเจนวิดีโอ {len(video_prompts)} อัน")

            return {
                "chat_url": session.state()["url"],
                "image_prompts": image_prompts,
                "video_prompts": video_prompts,
                "image_reply": image_reply,
                "video_reply": video_reply,
            }
        finally:
            browser.close()
