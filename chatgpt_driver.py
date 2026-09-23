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

# โควตารูปของบัญชีหมด — **คนละเรื่องกับโดนตัวกรอง และต้องแก้คนละทาง**
#
# **เจอจริง 30 ส.ค. 2569 เวลา 21:01** บัญชี Plus ใช้สิทธิ์สร้างรูปหมด
# ChatGPT ตอบว่า "You're out of images … wait for more tomorrow at 11:40 AM"
# แล้วยังเขียนสตอรีบอร์ดเป็นข้อความให้ตามปกติ **แต่ไม่มีรูปมาแน่นอน**
#
# ของเดิมจับไม่ได้ เพราะคำใบ้ที่มีคือ "ไม่สามารถสร้างภาพ" แบบติดกัน ส่วนของจริง
# เขียนว่า "ไม่สามารถ**เรียกเครื่องมือ**สร้างภาพ" ซึ่งมีคำคั่นกลาง — **ผลคือทุกใบ
# ไปยืนรอรูปจนครบ IMAGE_TIMEOUT 600 วินาที** วัดได้จากงานจริง:
#
#     17:00-20:00 (โควตายังมี)   13-16 ใบ/ชั่วโมง
#     21:00 เป็นต้นไป (หมดแล้ว)   3.8 ใบ/ชั่วโมง   = ช้าลง 4 เท่า
#
# เพิ่ม 10 นาทีต่อใบ x 175 ใบที่ค้าง = เสียเวลาเปล่า 29 ชั่วโมง
#
# **แยกออกจากคำปฏิเสธเชิงนโยบายเพราะทางแก้ต่างกัน** โดนตัวกรอง = เนื้อหามีปัญหา
# ต้องแก้คำแล้วลองใหม่ · โควตาหมด = ไม่ต้องลองใหม่เลยจนกว่าจะถึงเวลาคืนสิทธิ์
IMAGE_QUOTA_HINTS = [
    "out of image",                     # You're out of images / image creations
    "limit for image generation",       # hit the Plus plan limit for image generations
    "ไม่สามารถเรียกเครื่องมือสร้างภาพ",
]


def image_quota_out(reply: str) -> bool:
    """คำตอบนี้บอกว่าโควตารูปหมดใช่ไหม — รอต่อไปก็ไม่มีรูป"""
    low = (reply or "").lower()
    return any(hint.lower() in low for hint in IMAGE_QUOTA_HINTS)


# ChatGPT บอกเวลาคืนสิทธิ์มาให้ในประโยคเดียวกัน — เก็บไว้บอกผู้ใช้
# ตัวอย่างจริง 31 ส.ค. 2569: "when the limit resets in 12 hours and 21 minutes"
IMAGE_QUOTA_RESET_RE = re.compile(r"resets?\s+in\s+([^.\n]{1,40})", re.I)


def image_quota_reset(reply: str) -> str:
    """โควตารูปจะคืนอีกนานเท่าไร — คืน "" ถ้าคำตอบไม่ได้บอก

    **แยก "ไม่ได้บอก" ออกจาก "บอกว่าเหลือ 0" เสมอ** (กติกาข้อ 2.3.1)
    ค่าว่างแปลว่าไม่รู้ ไม่ใช่แปลว่าคืนแล้ว
    """
    found = IMAGE_QUOTA_RESET_RE.search(reply or "")
    return found.group(1).strip() if found else ""

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
    if image_quota_out(text):
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
        # **รอให้ช่องแนบโผล่ ไม่ใช่นับครั้งเดียว** (23 ก.ย. 2569) — ช่องแนบไฟล์
        # ขึ้นช้ากว่าช่องพิมพ์ `open()` รอแค่ช่องพิมพ์ นับทันทีจึงได้ 0 แล้วล้ม
        # ทั้งที่อีกไม่กี่วินาทีช่องแนบก็มา (วัดจริง: ล้มตอนนับทันที ·
        # รอ 3 วินาทีเจอ 4 ช่อง `upload-files` `upload-photos` …)
        target = self.page.locator('input[type="file"]').first
        try:
            target.wait_for(state="attached", timeout=15_000)
        except Exception:                                        # noqa: BLE001
            raise ChatGPTError("ไม่พบช่องแนบไฟล์ในหน้าแชท (รอแล้ว 15 วินาที)") from None
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
                # จำนวนคำตอบไม่เพิ่ม — **ปกติแปลว่ายังไม่ตอบ แต่ไม่เสมอไป**
                #
                # เจอจริง 30 ส.ค. 2569 เวลา 23:41 ตอนโควตารูป ChatGPT หมด:
                # การ์ด "You're out of images" โผล่ขึ้นมาแล้วหายไปเอง ทำให้จำนวน
                # ก้อนคำตอบ **ลดลงหนึ่ง** พอ GPT ตอบก้อนใหม่จริง ตัวนับจึงกลับมา
                # เท่าเดิมพอดี เงื่อนไขนี้เลยเป็นจริงตลอดกาล
                #
                #   23:41:53  ข้อความ=1676 ตัว · สตรีม=True  · ยังเป็นคำตอบเก่า
                #   23:42:09  ข้อความ=5751 ตัว · สตรีม=True  · ยังเป็นคำตอบเก่า
                #   23:42:24  ข้อความ=5810 ตัว · สตรีม=False · ยังเป็นคำตอบเก่า
                #   …ยืนรอต่ออีก 9 นาทีทั้งที่คำตอบครบอยู่ตรงหน้าแล้ว
                #
                # เสียเวลาเปล่า 10 นาที/ใบ แล้วสุดท้ายก็ไปแกะบทพูดจากของเดิมได้อยู่ดี
                #
                # **ยอมรับได้เมื่อเนื้อความต่างจากก้อนเดิมจริง** ซึ่งยังกันเคส
                # 22 ส.ค. 2569 ไว้ครบ — เคสนั้นคือคืนก้อนเดิมที่เนื้อเหมือนเป๊ะ
                # ส่วนตรงนี้ต้องต่างถึงจะผ่าน จึงคืนของเก่าไม่ได้อยู่ดี
                fresh = bool(previous) and bool(text) and text != previous
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
        # ใช้เกณฑ์เดียวกับตอนวนรอ — ตัวนับคำตอบเชื่อไม่ได้ (ดูเหตุผลข้างบน)
        # "เก่า" คือ **ไม่มีอะไรมาเลย** หรือ **เนื้อเหมือนก้อนเดิมเป๊ะ** เท่านั้น
        stale = (not state["lastReply"]) or bool(
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
            if not seen:
                last = self.state()["lastReply"]
                if image_quota_out(last):
                    self.log("  ⚠️ โควตารูปของบัญชี ChatGPT หมดแล้ว — เลิกรอทันที "
                             "(รูปจะไม่มาจนกว่าจะถึงเวลาคืนสิทธิ์)")
                    return []
                if image_refused(last):
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
#
# **ต้องอยู่ต้นบรรทัดเท่านั้น** (แก้ 28 ส.ค. 2569) — ของเดิมตัดทุกที่ที่เจอคำว่า
# "Scene N" รวมถึงตอนที่ **ประโยคอ้างถึงฉากก่อนหน้า** ซึ่ง GPT เขียนแทบทุกฉาก
#
#     "…commercial continuing seamlessly from Scene 1."
#     "…commercial, seamlessly continuing from Scene 3."
#                                              ↑ ตัดตรงนี้ ผ่าฉากออกเป็นสองท่อน
#
# ผลคือฉากเดียวถูกผ่าเป็นสองก้อน ท่อนหน้าเหลือ 130 ตัวอักษรและ**ไม่มีบรรทัด
# สั่งเสียงพูด** เพราะบทพูดอยู่ในท่อนหลัง ระบบจึงเตือนว่า "ฉาก 2, 5 ไม่มีเสียงพูด"
# แล้วไปขอ GPT ใหม่ ทั้งที่คำตอบเดิมสมบูรณ์อยู่แล้ว
#
# วัดกับคำตอบจริงของใบ 57707748374 (8,146 ตัวอักษร)
#     ของเดิม  ได้ 7 ชุด · 2 ชุดไม่มีบทพูด · ต้องขอ GPT ใหม่ 2 รอบ
#     แบบใหม่  ได้ 5 ชุด · **มีบทพูดครบทุกชุด** · ไม่ต้องขอใหม่เลย
#
# เผื่อสัญลักษณ์นำหน้าที่ GPT ชอบใส่ (`## Scene 1`, `- Scene 1`, `> Scene 1`)
SCENE_HEAD_RE = re.compile(r"(?=^[ \t>*#\-]*(?:SCENE|Scene|ซีน)\s*\d+\b)", re.M)

# ทางถอยสำหรับคำตอบรูปแบบเก่าที่ **ทั้งไฟล์เป็นบรรทัดเดียว ไม่มีการขึ้นบรรทัดเลย**
# (เช่นใบ 27239816564 · 5,320 ตัวอักษร 0 บรรทัด) หัวข้อฉากจึงอยู่กลางบรรทัดเสมอ
# ตัวบนหาไม่เจอสักจุด — ใช้ตัวนี้แทนเฉพาะตอนนั้น ไม่ใช้เป็นตัวหลักเพราะมันตัด
# ประโยคที่อ้างถึงฉากก่อนหน้าด้วย ซึ่งเป็นบั๊กที่เพิ่งแก้ไป
SCENE_HEAD_LOOSE_RE = re.compile(r"(?=(?:\bSCENE\b|\bScene\b|ซีน)\s*\d+\b)")


def _split_scenes(reply: str) -> list[str]:
    """แยกฉากจากคำตอบ — ลองแบบเข้มก่อน ไม่ได้ค่อยถอยไปแบบหลวม

    วัดกับคำตอบจริง 49 ไฟล์ (GPT ถูกสั่งให้ทำ 5 ฉากเสมอ)
        ตัดทุกที่ที่เจอ Scene   ได้ 5 ฉากถูก 26 ไฟล์   ผิด 23
        เฉพาะต้นบรรทัด          ได้ 5 ฉากถูก 47 ไฟล์   แยกไม่ได้เลย 2
        เข้มก่อนแล้วถอย         ได้ 5 ฉากถูก **49 ไฟล์**
    """
    for pattern in (SCENE_HEAD_RE, SCENE_HEAD_LOOSE_RE):
        parts = [part.strip() for part in pattern.split(reply or "")]
        # ชิ้นแรกมักเป็นคำนำก่อนถึงฉากแรก ตัดทิ้งด้วยเกณฑ์ "ต้องขึ้นต้นด้วยหัวข้อฉาก"
        scenes = [s for s in parts if len(s) > 60 and pattern.match(s)]
        if len(scenes) > 1:
            return scenes
    return []


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

    scenes = _split_scenes(reply)
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

# ---- ช่องทำสตอรีบอร์ด (เจ้าของสั่ง 30 ส.ค. 2569) --------------------------
#
# *"สามารถยิงเข้า 2 customs ได้ไหม"* — ได้ **แต่ต้องแยกโปรไฟล์ Chrome ด้วย**
# ไม่งั้นยังทำทีละใบเหมือนเดิม เพราะ Chrome เปิดโปรไฟล์เดียวกันซ้อนไม่ได้
# (คอขวดคือโปรไฟล์ ไม่ใช่จำนวน custom GPT)
#
# **เหตุการณ์ที่ทำให้ต้องมี** วัดเมื่อ 30 ส.ค.: มีงานจอดรอทำสตอรีบอร์ด 156 ใบ
# ทำได้ทีละใบ ใบละราว 2 นาที = ประมาณ 5 ชั่วโมงกว่าจะหมด
#
# แต่ละช่องต้องมี **โปรไฟล์ Chrome ของตัวเอง** และแต่ละโปรไฟล์ต้องล็อกอิน
# ChatGPT ไว้แล้ว — โปรไฟล์ใหม่ที่ยังไม่ได้ล็อกอินจะล้มทุกใบ
#
# `profile` ว่าง = ใช้โปรไฟล์เดิม (ของเดิมจึงไม่เปลี่ยนพฤติกรรม)
# ⚠️ **ช่อง 2 กลับมาใช้ GPT ตัวเดิม** (30 ส.ค. 2569 14:50)
#
# ลองตัวที่สอง (`st riib rd 2`) แล้ว **มันไม่วาดรูปให้เลย** ตอบข้อความครบทุกอย่าง
# — คำสั่ง Flow 5 ชุด บทพูด 5 ฉาก — แต่รอจนครบเพดาน 600 วินาทีได้ภาพ 0 ใบ
# (ใบ 13981157598 · 14:33–14:43)
#
# **คอขวดจริงคือโปรไฟล์ Chrome ไม่ใช่จำนวน custom GPT** (เขียนไว้ข้างบนแล้ว)
# ดังนั้นเอา GPT ตัวเดิมที่พิสูจน์แล้วว่าวาดรูปได้ ไปรันบนโปรไฟล์ 2 ก็ได้ความเร็ว
# เท่ากันโดยไม่ต้องเสี่ยงกับตัวที่ยังไม่รู้ว่าใช้ได้ไหม
#
# **และยังเป็นการทดลองที่แยกสาเหตุได้ด้วย** ถ้าตัวเดิมบนโปรไฟล์ 2 วาดรูปได้
# = ปัญหาอยู่ที่ GPT ตัวใหม่ · ถ้าวาดไม่ได้เหมือนกัน = ปัญหาอยู่ที่บัญชี ChatGPT
# ของโปรไฟล์ 2 (เช่นเป็นบัญชีที่วาดรูปไม่ได้)
STORYBOARD_SLOTS = [
    {"gpt": STORYBOARD_GPT_URL, "profile": ""},
    {"gpt": STORYBOARD_GPT_URL, "profile": "flow_browser_profile2"},
]

# GPT ตัวที่สองที่เจ้าของส่งมาให้ลอง — เก็บที่อยู่ไว้ ยังไม่ได้ใช้
# ใช้ได้เมื่อไรที่ยืนยันว่ามันวาดรูปได้ ให้เอาไปใส่ใน STORYBOARD_SLOTS ช่อง 2
STORYBOARD_GPT_URL_2 = ("https://chatgpt.com/g/"
                        "g-6a93d21ffcac8191a5737ce2a5ba28ed-st-riib-rd-2")


def storyboard_slot(number: int = 1) -> dict:
    """ข้อมูลช่องที่ `number` (เริ่มที่ 1) — เกินจำนวนช่องให้ตกกลับช่องแรก"""
    index = max(1, int(number or 1)) - 1
    return STORYBOARD_SLOTS[index] if index < len(STORYBOARD_SLOTS) else STORYBOARD_SLOTS[0]

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
# จำนวนฉากที่ **มีเสียงพูด** — ภาพยังเป็น 5 ฉากเหมือนเดิม (เจ้าของสั่ง 29 ส.ค. 2569
# *"ให้เลือกทำ 5 ฉาก เหมือนเดิม แต่คัดจาก 5 เหลือ 3 มาเป็นคำพูด"*)
SPEAK_SCENES = 5

# เพดานความยาวบทพูดรวมทั้งคลิป — **วัดจากคลิปจริง 52 ใบ ไม่ได้ตั้งลอยๆ**
#
# **เจ้าของสั่งแก้ 30 ส.ค. 2569** — *"ผมอยากให้เอาจุดเด่นมา 5 อันเหมือนเดิม
# แต่ปรับ speed ในการพูด ให้พูดให้ครบ"* จึงกลับไปพูดครบ 5 ฉาก
# แล้วขยายเพดานตามความเร็วที่พิสูจน์แล้วว่ายังฟังรู้เรื่อง
#
#     ความเร็วที่ Veo พูดจริง   ช้าสุด 3.9 · กลาง 13.6 · เร็วสุด 41.8 ตัว/วินาที
#     เร็วกว่า 16 ตัว/วินาที     6 ใบ · **ฟังไม่รู้เรื่อง 0 ใบ**
#     ตั้งเป้าที่ 20 ตัว/วินาที × 10 วินาที = 200 ตัวอักษร
#
# **ทำไมของเดิม 280 ตัวอักษรถึงไม่ได้** เพราะเกินแม้จะพูดเร็วสุดที่ยังฟังออก
# วัดได้ว่าฉากที่สั่งให้พูด 72 ฉาก ได้ยินจริงแค่ 35 ฉาก (49%)
#
# ⚠️ **Veo ไม่ได้เร่งพูดเองเมื่อบทยาว** — คลิปเก่าบท 280 ตัวอักษรมันพูดที่
# ความเร็วปกติแล้วโดนตัดกลางคัน ไม่ได้พยายามพูดให้ทัน จึงต้อง **สั่งเรื่อง
# จังหวะตรงๆ ในบรรทัดเสียง** (ข้อ 4 ของ FLOW_AUDIO_RULE) ไม่ใช่หวังว่ามันจะรู้เอง
# **แก้ 30 ส.ค. 2569 หลังทดลองจริง** — เคยตั้ง 200 โดยหวังว่าคำสั่งจังหวะ
# จะทำให้ Veo พูดเร็วขึ้นเป็น 20 ตัว/วินาที **ทดลองแล้วไม่ได้ผลเลย**
#
#     สั่งจังหวะไปแล้ว  พูดได้ 133 ตัวอักษร ใน 10 วินาที = 13.3 ตัว/วินาที
#     ไม่สั่งอะไรเลย    ค่ากลางจาก 52 คลิป              = 13.6 ตัว/วินาที
#
# **ความเร็วพูดของ Veo เป็นค่าตายตัว สั่งให้เร็วขึ้นไม่ได้** คลิป 10 วินาที
# พูดได้ราว 135 ตัวอักษรเท่านั้น ตั้งเกินกว่านี้คือสั่งของที่ทำไม่ได้
# แล้วเสียงจะถูกตัดกลางคันเหมือนเดิม
SPEECH_MAX_CHARS = 135

# ⚠️ **บอกตัวเลขให้ต่ำลงเพื่อเผื่อการเขียนเกิน — ลองแล้วไม่ได้ผล อย่าลองซ้ำ**
#
# วัดจริง 31 ส.ค. 2569: 82% ของงานเขียนบทครั้งแรกเกินเพดาน แล้วต้องขอใหม่
# ครั้งละ 57 วินาที = 24% ของเวลาทั้งใบ จึงลองบอกเป้าเป็น 118 แทน 135
# โดยยังตรวจที่ 135 เท่าเดิม หวังว่าส่วนเกิน 14% จะพอดี
#
#     บอก 135 → ครั้งแรกได้ค่ากลาง 154 ตัวอักษร (n=15) · ขอใหม่ 82%
#     บอก 118 → ครั้งแรกได้ค่ากลาง 153 ตัวอักษร (n=8)  · ขอใหม่ 114%
#
# **ไม่ต่างกันเลย GPT ไม่ได้อิงตัวเลขที่เราบอก** ถอนคืนแล้ว
# ถ้าจะลดเวลาตรงนี้จริง ต้องเปลี่ยนวิธี ไม่ใช่เปลี่ยนตัวเลข — เช่นบอกให้แก้
# เฉพาะฉากที่ยาวเกิน แทนที่จะสั่งเขียนใหม่ทั้งชุด (ยังไม่ได้ลอง)

# **ถอนคำสั่งจังหวะออกแล้ว (30 ส.ค. 2569) — ทดลองแล้วไม่ได้ผล**
#
# เคยฝังประโยคสั่งให้พูดเร็วไว้ในทุกบรรทัดเสียง ผลที่วัดได้คือ 13.3 ตัว/วินาที
# ซึ่งเท่ากับค่ากลางเดิมที่ไม่ได้สั่งอะไรเลย (13.6) **Veo ไม่ฟังคำสั่งจังหวะ**
#
# ที่แย่กว่านั้นคือมันยาว 118 ตัวอักษร คูณ 5 ฉาก = **กินโควตาคำสั่งไป 590
# ตัวอักษร** ไปแย่งที่ของคำบรรยายภาพ ซึ่งเป็นที่อยู่ของคำสั่งใส่ตัวหนังสือ
# ผลคือคลิปที่ได้ไม่มีตัวหนังสือสักตัว ทั้งที่สตอรีบอร์ดมีครบทั้ง 5 ฉาก
#
# **บทเรียน: คำสั่งที่ไม่ได้ผลไม่ได้แค่เปล่าประโยชน์ มันแย่งที่ของคำสั่งที่ได้ผล**
AUDIO_PACE = ""


# จำนวนฉากที่เป็น **จุดเด่นของสินค้าจริง** — ฉากที่เหลือคือประโยคปิดการขาย
#
# **เจ้าของสั่ง 30 ส.ค. 2569** — *"เอาจุดเด่นมาแค่ 4 ข้อ อีกข้อเป็นประโยค
# ปิดการขาย เอาแบบสุ่มจะได้ลองปิดการขายหลายๆแบบ"*
HIGHLIGHT_SCENES = 4

# คลังประโยคปิดการขาย — **สุ่มมาใช้ฉากสุดท้าย**
#
# ทำไมต้องให้เราเป็นคนกำหนด ไม่ปล่อยให้ ChatGPT แต่งเอง
#   · ของที่มันแต่งเองยาวเฉลี่ย 37 ตัวอักษร ซึ่งเกินเวลาที่ฉากสุดท้ายมี
#     (ราว 2 วินาที = 27 ตัวอักษร) พอโดนตัดก็กลายเป็นประโยคที่พูดไม่จบ
#   · หลายอันไม่ได้ปิดการขายจริง แต่เป็นการบอกจุดเด่นเพิ่มอีกข้อ = เสียฉากเปล่า
#   · คุมไม่ได้ว่าใช้แบบไหน จึงเทียบไม่ได้ว่าแบบไหนขายดีกว่า
#
# ทุกประโยคในคลังนี้ **ไม่เกิน 27 ตัวอักษรไทย** วัดแล้วทุกอัน
CLOSING_LINES = [
    # ชวนกดตะกร้า
    "ตะกร้ารออยู่แล้ว จัดเลย",
    "กดตะกร้าเลย เดี๋ยวของหมด",
    "สนใจกดตะกร้าข้างล่างเลย",
    "ลิงก์อยู่ในตะกร้านะ กดเลย",
    "จิ้มตะกร้าเลย ไม่ต้องคิดนาน",
    # ปิดด้วยความคุ้ม
    "ของดีราคานี้ หายากนะ",
    "ราคานี้คือคุ้มมาก จัดเลย",
    # ปิดด้วยความเร่ง
    "ช้าหมดนะ ของมีไม่เยอะ",
    "เห็นแล้วอย่าเลื่อนผ่าน",
    "รีบเลย ราคานี้ไม่อยู่นาน",
    "เก็บไว้ก่อน เดี๋ยวหาไม่เจอ",
    # เพื่อนแนะนำเพื่อน
    "บอกต่อเลย ดีจริง",
    "ของมันต้องมี จริงๆนะ",
    "ลองดูนะ ไม่ผิดหวังแน่",
    "เราใช้แล้วชอบ แนะนำเลย",
    "ใครกำลังมองอยู่ ตัวนี้เลย",
    # ผูกกับสินค้า
    "ซื้อทีเดียว ใช้ยาวๆไปเลย",
    "อยากได้แบบนี้ ตัวนี้จบเลย",
    "ห้องคุณขาดตัวนี้อยู่แน่นอน",
]


def pick_closing(seed: str = "") -> str:
    """สุ่มประโยคปิดการขาย — **สุ่มจากรหัสสินค้า ไม่ใช่สุ่มใหม่ทุกครั้ง**

    สินค้าคนละตัวได้คนละประโยค (ได้ลองหลายแบบตามที่เจ้าของต้องการ)
    แต่สินค้าตัวเดิมสั่งซ้ำจะได้ประโยคเดิม — ไม่งั้นเจนใหม่ทีนึงเปลี่ยนที
    แล้วเทียบไม่ได้ว่าที่ผลต่างเป็นเพราะประโยคหรือเพราะอย่างอื่น
    """
    import hashlib                                            # noqa: PLC0415

    if not seed:
        seed = "default"
    digest = hashlib.sha256(str(seed).encode("utf-8")).hexdigest()
    return CLOSING_LINES[int(digest[:8], 16) % len(CLOSING_LINES)]


def flow_audio_rule(closing: str = "") -> str:
    """กติกาบรรทัดเสียงที่ส่งให้ ChatGPT — ใส่ประโยคปิดที่สุ่มได้เข้าไปด้วย

    ทำเป็นฟังก์ชันเพราะประโยคปิดเปลี่ยนไปตามสินค้า ถ้าเป็นค่าคงที่จะสุ่มไม่ได้
    """
    closing = closing or pick_closing()
    return FLOW_AUDIO_RULE + (
        f"\n7) **ฉากที่ {SPEAK_SCENES} เป็นประโยคปิดการขาย ใช้ข้อความนี้เป๊ะๆ "
        f"ห้ามเปลี่ยนคำ** (แต่เขียนเป็นคำอ่านคั่นพยางค์เหมือนฉากอื่น):\n"
        f"   {closing}\n"
        f"   ส่วนฉากที่ 1-{HIGHLIGHT_SCENES} เป็นจุดเด่นของสินค้าตามปกติ"
    )


# กติกาบรรทัดเสียงพูด — **ข้อ 1 คือน้ำเสียง และต้องอยู่บนสุดเสมอ**
#
# **เจ้าของแจ้ง 30 ส.ค. 2569** — *"คลิปเราเสียงพูดเปลี่ยน ตอนแรกเป็นรีวิวแบบเพื่อน
# ตอนนี้กลายเป็นบอกแต่ฟังก์ชันมันน่าเบื่อ"*
#
# วัดจากบทพูดจริง 187 ใบในคลัง ยืนยันว่าเปลี่ยนจริงและเปลี่ยนวันไหน:
#
#     9-28 ส.ค.   176-209 ตัวอักษร/ใบ   13-14 ตัวอักษรต่อช่วงเว้นวรรค
#     30 ส.ค.     142 ตัวอักษร/ใบ       7.6 ตัวอักษรต่อช่วงเว้นวรรค
#
#     9 ส.ค.:  "แก ดูตัวนี้ก่อน โซฟาเบดที่ทั้งนั่งทั้งนอนได้เลย ห้องเล็กคือเหมาะสุดๆ"
#     30 ส.ค.: "หกสิบห้า วัตต์ ชาร์จไว ทันใจ / สาม พอร์ต ชาร์จ หลาย เครื่อง"
#
# **สาเหตุ: กติกาที่เติมเข้ามาไปแย่งที่ของน้ำเสียง** คำว่า "แบบเพื่อนรีวิวให้เพื่อน"
# มีอยู่ประโยคเดียวใน FLOW_PROMPT_ASK แต่ตามด้วยกติกา 6 ข้อที่ขึ้นหัวว่า
# "ห้ามข้าม" ซึ่งเป็นข้อกำหนดกลไกล้วน **ไม่มีข้อไหนพูดถึงน้ำเสียงเลยสักข้อ**
# แล้วข้อบังคับที่ชัดกว่าย่อมชนะคำเกริ่นที่เบากว่าเสมอ
#
# ซ้ำร้ายข้อเดิมยังสั่งว่า "ฉาก 1-4 ต้องเป็นจุดเด่นคนละข้อกัน ห้ามซ้ำแนวกัน
# ห้ามสรุปทวนซ้ำ" + "ฉากละไม่เกิน 27 ตัวอักษร" = บังคับให้ยัดฟีเจอร์ให้ได้
# มากที่สุดในที่แคบที่สุด ซึ่งวิธีเดียวที่ทำได้คือ**ตัดคำเชื่อมและคำลงท้ายทิ้ง**
# ผลคือเหลือแต่ชื่อฟังก์ชันเรียงกัน
#
# **บทเรียนเดียวกับ AUDIO_PACE ข้างล่าง** — กติกาที่เติมทีละข้อโดยไม่ดูของเดิม
# ไม่ได้แค่ยาวขึ้น มันเบียดของสำคัญตกขอบ **เติมกติกากลไกเมื่อไร ต้องเช็คว่า
# น้ำเสียงยังอยู่ไหม** ข้อ 1 จึงถูกตรึงไว้บนสุดพร้อมตัวอย่างของจริง เพราะ
# โมเดลลอกตัวอย่างเก่งกว่าทำตามคำคุณศัพท์มาก
FLOW_AUDIO_RULE = (
    "\n\nข้อกำหนดเพิ่มเติมที่ห้ามข้าม:\n"
    "1) **น้ำเสียงต้องเป็นเพื่อนบอกเพื่อน ไม่ใช่พนักงานอ่านสเปก**\n"
    "   **สูตรของทุกฉาก: พูดถึงตอนที่ได้ใช้ แล้วค่อยบอกว่าดียังไง**\n"
    "   เพื่อนไม่เล่าสเปกให้เพื่อนฟัง เพื่อนเล่าว่า **มันช่วยตอนไหน** "
    "แล้วคนฟังนึกภาพตัวเองออกทันที\n"
    "   ✅ ร้อนๆแบบนี้ พกติดตัวไว้เลย ลมแรงกว่าที่คิด\n"
    "   ✅ ชาร์จทีเดียวใช้ยันเย็น ไม่ต้องหาปลั๊กเลย\n"
    "   ✅ ซอกโซฟาที่ไม้กวาดไม่ถึง อันนี้เอาอยู่นะ\n"
    "   ✅ ห้องเล็กก็วางได้ ไม่เกะกะเลย\n"
    "   ❌ หกสิบห้าวัตต์ ชาร์จไวทันใจ  (อ่านสเปก)\n"
    "   ❌ หัวสิบเอ็ดแบบ ซอกไหนก็ถึง  (อ่านสเปกแล้วเติมคำลงท้าย ยังไม่ใช่เพื่อนพูด)\n"
    "   ❌ ประกันศูนย์ไทยหนึ่งปีนะ  (ข้อมูลบนกล่อง ไม่ใช่เรื่องที่เพื่อนเล่า)\n"
    "   **เติมคำว่า เลย/นะ ท้ายสเปก ไม่นับว่าเป็นเพื่อนพูด** "
    "ต้องมีตอนที่ได้ใช้จริงอยู่ในประโยคด้วย\n"
    f"2) มีทั้งหมด 5 ฉาก และ **ทุกฉากต้องมีเสียงพูด** ครบ {SPEAK_SCENES} ฉาก\n"
    f"   **ฉากที่ 1-{HIGHLIGHT_SCENES} ต้องเล่าจุดเด่นคนละข้อกันจริงๆ** "
    "ห้ามสองฉากพูดเรื่องเดียวกันด้วยคำคนละคำ — "
    "ตัวจิ๋วแต่น่ารักเกินนะ กับ วางตรงไหนก็ดูคิวท์มาก **นับเป็นข้อเดียวกัน**\n"
    f"   ส่วนฉากที่ {SPEAK_SCENES} ใช้ประโยคปิดการขายที่กำหนดให้ในข้อ 7\n"
    f"3) บทพูดรวมทุกฉาก **ห้ามเกิน {SPEECH_MAX_CHARS} ตัวอักษรไทย** "
    f"(เฉลี่ยฉากละไม่เกิน {SPEECH_MAX_CHARS // SPEAK_SCENES} ตัวอักษร) — "
    "คลิปยาว 10 วินาที ถ้ายาวกว่านี้เสียงจะถูกตัดกลางคันแม้จะพูดเร็วแล้ว\n"
    "   **ที่ไม่พอ ให้ตัดตัวเลขกับศัพท์เทคนิคทิ้งก่อนเสมอ** "
    "แล้วเก็บตอนที่ได้ใช้ไว้ — ข้อ 1 สำคัญกว่าความครบของสเปก\n"
    "   ตัวเลขใส่ได้**เฉพาะตอนที่ตัวเลขนั้นคือเรื่องที่เพื่อนจะเล่าเอง** "
    "เช่น ใช้ได้ทั้งวัน สิบสองชั่วโมง — ไม่ใช่ใส่เพราะมันอยู่ในสเปก\n"
    "   ทุกฉากต้องยังรู้ว่า**ของชิ้นนี้ช่วยอะไร** ไม่ใช่คำชมลอยๆ ที่ใช้กับสินค้าอะไรก็ได้\n"
    "   ❌ ตัวจิ๋วแต่น่ารักเกินนะ  (ใช้กับสินค้าอะไรก็ได้ ไม่ได้บอกว่าช่วยอะไร)\n"
    "   ✅ ตัวจิ๋วยัดกระเป๋าไปได้เลย ลมแรงเกินตัว\n"
    "4) เขียนบทพูดเป็น **คำอ่านคั่นพยางค์ด้วยขีด** ทุกคำ เช่น "
    "ทำงาน เขียนเป็น ทำ-งาน · ติดตั้ง เขียนเป็น ติด-ตั้ง · "
    "เก้าอี้ เขียนเป็น เก้า-อี้ (ตัวอ่านเสียงอ่านคำไทยผิดบ่อย ขีดช่วยให้อ่านถูก)\n"
    "   ⚠️ **ห้ามเว้นวรรคคั่นทุกคำ** เว้นวรรคเฉพาะตรงที่ตั้งใจให้หยุดจริงๆ "
    "เพราะตัวอ่านเสียงหยุดทุกช่องว่าง เว้นถี่แล้วจะฟังเหมือนหุ่นยนต์อ่านทีละคำ — "
    "เขียน แบต-อึด-มาก ใช้-ยัน-เย็น-เลย ไม่ใช่ แบต-อึด มาก ใช้ ยัน เย็น เลย\n"
    "   ⚠️ **ขีดนี้ใช้เฉพาะบรรทัด Audio: เท่านั้น** ข้อความไทยที่จะให้โชว์เป็น "
    "ตัวหนังสือบนจอ (Thai on-screen text) **ต้องเขียนแบบปกติ ห้ามมีขีดเด็ดขาด** "
    "เพราะคนดูจะเห็นขีดติดอยู่บนจอจริงๆ — เขียน สีสดสะดุดตา ไม่ใช่ สี-สด-สะ-ดุด-ตา\n"
    "5) ฉากที่มีเสียง เขียนเป็นบรรทัดแยกท้ายฉากนั้น ในรูปแบบนี้เป๊ะๆ "
    "(ขึ้นต้นด้วยคำว่า Audio: เสมอ และ**ต้องมีคำสั่งจังหวะพูดต่อท้ายทุกครั้ง**):\n"
    "Audio: Generate Thai voice-over narration: "
    "\"<คำพูดของฉากนั้น>\"\n"
    "6) ห้ามใช้คำภาษาอังกฤษปนในบทพูด — ให้เขียนเป็นคำอ่านภาษาไทยแทน"
)

# ฉากที่ต้องมีบรรทัดสั่งเสียง — ใช้ตรวจว่า GPT ตอบมาครบไหมก่อนเอาไปใช้จริง
FLOW_AUDIO_LINE_RE = re.compile(r"^\s*Audio\s*[:：]", re.I | re.M)


# **ต้องข้ามคำสั่งจังหวะที่แทรกอยู่ด้วย** (30 ส.ค. 2569) — รูปแบบใหม่คือ
# `Audio: Generate Thai voice-over narration, spoken at a brisk pace…: "…"`
# ถ้าไม่เผื่อช่วง `[^:：]*` ไว้ ตัวแกะจะคืนคำสั่งจังหวะภาษาอังกฤษมาเป็นบทพูดด้วย
# แล้วบทที่โชว์ให้เจ้าของอนุมัติจะมีภาษาอังกฤษปนเต็มไปหมด
from clip_store import spoken_part as _spoken_part  # noqa: E402

AUDIO_TEXT_RE = re.compile(
    r"^\s*Audio\s*[:：]\s*"
    r"(?:Generate\s+Thai\s+voice-?over\s+narration[^:：]*[:：])?\s*(.*)$",
    re.I | re.M)
THAI_CHAR_RE = re.compile(r"[\u0e00-\u0e7f]")


def audio_lines(prompts: list[str]) -> list[str]:
    """คำพูดที่สั่งไว้ในคำสั่ง Flow เรียงตามฉาก — **นี่คือบทพูดฉบับจริง**

    ก่อน 29 ส.ค. 2569 ระบบถาม GPT สองรอบ รอบแรกได้คำสั่ง Flow (ซึ่งมีบทพูด
    ฝังอยู่ในบรรทัด Audio:) แล้วรอบสองขอ "บทพูด" แยกอีกที ผลคือ **ได้บทพูด
    คนละฉบับกัน** ตัวที่ผู้ใช้เห็นและกดอนุมัติคือฉบับรอบสอง แต่ตัวที่ Veo
    อ่านออกเสียงจริงคือฉบับรอบแรก

    วัดจริง: **บทสองฉบับตรงกัน 0 จาก 65 ใบ** และเสียงที่ได้ยินเหมือนฉบับ
    รอบแรก 58% แต่เหมือนฉบับที่อนุมัติแค่ 27% แปลว่าปุ่มอนุมัติบทพูดกับ
    การพิมพ์แก้บทพูด **ไม่มีผลกับคลิปเลยแม้แต่ใบเดียว**

    ตอนนี้จึงเหลือฉบับเดียว — ดึงจากตรงนี้ที่เดียวเสมอ
    """
    out = []
    for text in prompts or []:
        for found in AUDIO_TEXT_RE.finditer(text or ""):
            # เอาเฉพาะข้อความในเครื่องหมายคำพูด — ChatGPT ชอบเขียนคำสั่ง
            # โทนเสียงภาษาอังกฤษต่อท้ายในบรรทัดเดียวกัน (แก้ 30 ส.ค. 2569)
            line = _spoken_part((found.group(1) or '').strip())
            if line:
                out.append(line)
    return out


def speech_chars(lines: list[str]) -> int:
    """นับเฉพาะตัวอักษรไทย — ช่องว่างกับขีดคำอ่านไม่กินเวลาพูด"""
    return sum(len(THAI_CHAR_RE.findall(line)) for line in lines or [])


def flow_audio_problem(prompts: list[str]) -> str:
    """บรรทัดเสียงในคำสั่งชุดนี้มีอะไรผิดกติกาไหม — คืนเหตุผลภาษาคน ว่างแปลว่าผ่าน

    ตรวจ 3 เรื่องที่ **แต่ละเรื่องเคยทำคลิปเสียมาแล้วจริง**
      · ไม่มีเสียงเลย        → คลิปเงียบ ใช้งานไม่ได้ (เจอ 3 ใบ)
      · บทยาวเกินเพดาน       → เสียงถูกตัดกลางคัน (เจอ 100% ของใบที่วัด)
      · ไม่ได้เขียนเป็นคำอ่าน → อ่านคำผิด เช่น ทำงาน เป็น ทวาร (เจอ 11 ใบ)
    """
    lines = audio_lines(prompts)
    if not lines:
        return "ไม่มีบรรทัดสั่งเสียงพูดสักฉาก — คลิปที่ได้จะเงียบ"
    if len(lines) > SPEAK_SCENES:
        return (f"มีฉากพูด {len(lines)} ฉาก เกินที่กำหนดไว้ {SPEAK_SCENES} ฉาก")
    total = speech_chars(lines)
    if total > SPEECH_MAX_CHARS:
        return (f"บทพูดรวม {total} ตัวอักษร เกินเพดาน {SPEECH_MAX_CHARS} "
                "— เสียงจะถูกตัดกลางคันตอนคลิปหมดเวลา")
    if not any("-" in line for line in lines):
        return "บทพูดยังไม่ได้เขียนเป็นคำอ่านคั่นพยางค์ด้วยขีด"
    return ""



def swap_audio_lines(prompts: list[str], spoken: list[str]) -> list[str]:
    """เปลี่ยนเฉพาะ **คำพูด** ในบรรทัด Audio ของแต่ละฉาก ส่วนอื่นคงเดิมทุกตัวอักษร

    ใช้ตอนขอแก้บทพูดที่ยาวเกิน — คำสั่งภาพภาษาอังกฤษยาวๆ ที่ GPT เขียนมาแล้ว
    ไม่มีอะไรผิด **ไม่มีเหตุผลต้องให้เขียนใหม่ทั้งชุด** (วัดแล้วเสีย 57 วินาที/ใบ)

    คืนลิสต์ว่างถ้าจำนวนไม่ตรงหรือหาบรรทัด Audio ไม่ครบ — ผู้เรียกถอยไปใช้
    วิธีเดิมได้ **ห้ามคืนของครึ่งๆ กลางๆ** เพราะฉากที่สลับไม่สำเร็จจะพูดคนละเรื่อง
    กับที่เห็นในบทพูด
    """
    if not prompts or len(spoken) != len(prompts):
        return []
    out: list[str] = []
    for block, words in zip(prompts, spoken):
        lines = block.splitlines()
        hit = -1
        for i, line in enumerate(lines):
            if FLOW_AUDIO_LINE_RE.match(line):
                hit = i
                break
        if hit < 0 or not str(words).strip():
            return []
        old = lines[hit]
        # คงคำสั่งจังหวะ/น้ำเสียงที่ต่อท้ายไว้ — เปลี่ยนแค่ข้อความในเครื่องหมายคำพูด
        # **ต้องดูว่า 'แทนที่ได้ไหม' ไม่ใช่ 'ผลต่างจากเดิมไหม'**
        # ฉากปิดการขายห้ามเปลี่ยนคำอยู่แล้ว ผลจึงเหมือนเดิมเป็นเรื่องปกติ
        # เช็คว่าต่างจากเดิมจะทำให้ฉากนั้นถูกตัดสินว่าล้มเหลวทุกครั้ง
        made, hits = re.subn(
            r'"[^"]*"', lambda _: '"' + str(words).strip() + '"', old, count=1)
        if not hits:                          # ไม่มีเครื่องหมายคำพูดให้แทน
            return []
        lines[hit] = made
        out.append("\n".join(lines))
    return out


def shorten_audio_ask(problem: str, spoken: list[str]) -> str:
    """คำขอแก้ **เฉพาะบรรทัดเสียง** — สั้นกว่าการขอคำสั่งใหม่ทั้งชุดมาก

    **ทำไมต้องมี** วัดจริง 31 ส.ค. 2569: 82% ของงานเขียนบทครั้งแรกยาวเกินเพดาน
    แล้วของเดิมสั่งว่า "ขอคำสั่งชุดเดิมใหม่ทั้งหมด" ซึ่งทำให้ GPT เขียนฉาก
    ภาษาอังกฤษยาว 5,000 ตัวอักษรใหม่ทั้งหมด **เสีย 57 วินาที = 24% ของเวลาทั้งใบ**
    ทั้งที่คำสั่งภาพไม่มีอะไรผิดเลยสักฉาก

    ตัวนี้ขอกลับมาแค่ 5 บรรทัดสั้นๆ แล้วเอาไปสลับใส่ของเดิมด้วย `swap_audio_lines`
    """
    lines = "\n".join(f"{i}. {t}" for i, t in enumerate(spoken, 1))
    return (
        f"บทพูดยังไม่ผ่านกติกา: {problem}\n\n"
        f"บทพูดชุดปัจจุบันคือ\n{lines}\n\n"
        f"**ขอเฉพาะบทพูดใหม่ {len(spoken)} บรรทัดเท่านั้น "
        f"ห้ามส่งคำสั่งภาพหรือคำอธิบายใดๆ กลับมา**\n"
        f"เงื่อนไข: รวมทุกบรรทัดห้ามเกิน {SPEECH_MAX_CHARS} ตัวอักษรไทย · "
        "คงใจความและน้ำเสียงเพื่อนเล่าให้เพื่อนฟังไว้เหมือนเดิม · "
        "บรรทัดสุดท้ายห้ามเปลี่ยนคำ · เขียนเป็นคำอ่านคั่นพยางค์เหมือนเดิม\n"
        "ตอบเป็นตัวเลขนำหน้าบรรทัดละฉาก แบบนี้เป๊ะๆ:\n"
        "1. <บทพูดฉากที่หนึ่ง>\n2. <บทพูดฉากที่สอง>\n…"
    )


def parse_numbered(reply: str, want: int) -> list[str]:
    """แกะบทพูดที่ขอกลับมา — ได้ไม่ครบตามที่ขอคืนลิสต์ว่าง

    **ห้ามพึ่งเลขนำหน้าอย่างเดียว** — วัดจริง 31 ส.ค. 2569 เวลา 02:36
    ChatGPT ตอบกลับมาแบบนี้

        โหลด-ไฟล์-ใหญ่ ไว-ถึง-พัน-เม็ก-เลย      <- **เลข 1. หายไป**
                                                <- บรรทัดว่าง
        2. เล่น-เกม-ลื่น แกน-แยก-ลด-สัญ-ญาณ
        3. …

    เลข `1.` ถูกกลืนเพราะหน้าเว็บจัดให้เป็นรายการอัตโนมัติแล้วซ่อนหัวข้อ ส่วน
    บรรทัดถัดมามีบรรทัดว่างคั่นจนหลุดจากรายการ เลขจึงเหลืออยู่ **แกะด้วยเลข
    อย่างเดียวจึงได้ 4 จาก 5 แล้วล้มทุกครั้ง** (3 ใน 3 ใบที่วัด)

    จึงเปลี่ยนมาเก็บ **บรรทัดที่หน้าตาเป็นบทพูด** แล้วตัดเลขนำหน้าทิ้งถ้ามี
    ได้เกินจำนวนที่ขอให้เอา **ท้ายสุด** เพราะรายการอยู่ท้ายคำตอบเสมอ
    ส่วนคำเกริ่นอยู่ต้น

    **ได้ไม่ครบ = ล้มเหลว ไม่ใช่ได้บางส่วน** ฉากที่ขาดจะทำให้บทพูดเลื่อนฉาก
    ซึ่งแย่กว่าบทที่ยาวเกินเสียอีก
    """
    good: list[str] = []
    for line in (reply or "").splitlines():
        row = line.strip()
        if not row:
            continue
        row = re.sub(r"^\s*\d{1,2}\s*[.)]\s*", "", row)          # ตัดเลขนำหน้าถ้ามี
        row = row.strip().strip('"“”').strip()
        if not row or len(row) > 140:
            continue
        if "audio" in row.lower() or ":" in row:                   # หัวข้อ/คำสั่ง ไม่ใช่บทพูด
            continue
        if not THAI_CHAR_RE.search(row):                           # ต้องมีตัวไทยจริง
            continue
        good.append(row)
    if len(good) < want:
        return []
    return good[-want:]


def flow_visual_problem(prompts: list[str]) -> str:
    """ตัวหนังสือที่จะโชว์บนจอมีอะไรผิดไหม — คืนเหตุผลภาษาคน ว่างแปลว่าผ่าน

    **เจ้าของเจอเอง 30 ส.ค. 2569** — คลิป TCL 55 นิ้วขึ้นตัวหนังสือบนจอว่า
    `สี-สด สวย-สะ-ดุด-ตา / คิว-แอล-อี-ดี` มีขีดคั่นเต็มไปหมด

    **ทำไมต้องมีด่านนี้** เดิมมีแต่ `flow_audio_problem()` ตรวจบรรทัดเสียง
    ส่วนคำสั่งที่บอกว่า "ให้วาดอะไรบนจอ" **ไม่มีใครตรวจเลยสักบรรทัด** ทั้งที่
    Veo วาดตามที่สั่งเป๊ะทุกตัวอักษร ความผิดในคำสั่งจึงกลายเป็นความผิดในคลิป
    ที่จ่ายเครดิตไปแล้ว (15 เครดิตต่อใบ) และถอนคืนไม่ได้

    **ตรวจก่อนจ่าย ไม่ใช่ล้างทีหลัง** — `clip_store.strip_reading_hyphens()`
    เป็นตาข่ายรับที่ล้างให้เงียบๆ ส่วนตัวนี้ทำให้ **ดังขึ้น** แล้วขอ ChatGPT
    ใหม่ ซึ่งได้ของที่ถูกตั้งแต่ต้นทาง ไม่ใช่ของที่ถูกซ่อมทีหลัง
    """
    import clip_store                                           # noqa: PLC0415

    for index, prompt in enumerate(prompts, 1):
        cleaned = clip_store.strip_reading_hyphens(prompt)
        if cleaned == prompt:
            continue
        # หาบรรทัดตัวอย่างมาบอกด้วย จะได้ไม่ต้องเดาว่าผิดตรงไหน
        for before, after in zip(prompt.split(chr(10)), cleaned.split(chr(10))):
            if before != after:
                return (f"ฉากที่ {index} เอาคำอ่านคั่นขีดไปใส่เป็นตัวหนังสือบนจอ "
                        f"({before.strip()[:40]}) — คนดูจะเห็นขีดติดบนจอจริงๆ")
    return ""


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
    # รูปพรีเซนเตอร์ — **แยกจาก `images` โดยตั้งใจ** (เจ้าของสั่ง 9 ก.ย. 2569)
    #
    # ถ้ายัดรวมใน `images` เลข "แนบรูปสินค้ามาให้ N ใบ" จะนับรูปคนเป็นสินค้าไปด้วย
    # แล้ว GPT จะนึกว่าผู้หญิงคนนั้นคือสินค้าที่ต้องโฆษณา
    presenter: list[Path] | None = None,
    # ประโยคเปิดของคลิปก่อนหน้า — ส่งไปบอก GPT ว่าห้ามเขียนซ้ำแนวนี้อีก
    avoid_openers: list[str] | None = None,
) -> dict:
    """ส่ง ชื่อสินค้า + รูป + จุดเด่น เข้า GPT นักสร้างสตอรีบอร์ด แล้วเก็บรูปที่ได้

    คืน {"chat_url", "reply", "frames": [path, …]}
    """
    from playwright.sync_api import sync_playwright

    # บอกจำนวนรูปและเลขกำกับ เพื่อให้ GPT อ้างอิงได้ว่าฉากไหนใช้รูปใบไหน
    # (ไม่บอกเลข มันจะพูดลอยๆ ว่า "ใช้รูปที่แนบ" แล้วเราตรวจไม่ได้ว่าตรงใบไหน)
    faces = list(presenter or [])
    ask = (
        f"สินค้า: {product}\n\n"
        "จุดเด่น:\n" + "\n".join(f"- {text}" for text in highlights) + "\n\n"
        f"แนบรูปสินค้าจริงมาให้ {len(images)} ใบ (เรียงเป็นรูปที่ 1–{len(images)})\n"
        # บอกเลขรูปของพรีเซนเตอร์ให้ชัด ไม่ปล่อยให้ GPT เดาเองว่าใบไหนคือคน
        # ใบเดียวเขียน "รูปที่ 5" ไม่ใช่ "รูปที่ 5–5" ซึ่งอ่านแล้วสะดุด
        + (("และรูปที่ "
            + (str(len(images) + 1) if len(faces) == 1
               else f"{len(images) + 1}–{len(images) + len(faces)}")
            + " คือรูปพรีเซนเตอร์ **ไม่ใช่สินค้า**\n") if faces else "")
        + (extra_ask + "\n" if extra_ask else "")
        + "ช่วยทำ storyboard สำหรับคลิปโฆษณาสั้น แล้ว**ออกมาเป็นรูปภาพ** ให้ด้วย"
    )

    with sync_playwright() as playwright:
        browser = open_browser(playwright, hidden=hidden)
        page = browser.pages[0] if browser.pages else browser.new_page()
        try:
            session = ChatGPTSession(page, log=log)
            session.open(gpt_url or STORYBOARD_GPT_URL)

            log(f"ส่งสินค้า + รูป {len(images)} ใบ + จุดเด่น {len(highlights)} ข้อ"
                + (f" + รูปพรีเซนเตอร์ {len(faces)} ใบ" if faces else ""))
            reply = session.ask(ask, list(images) + faces)

            # ข้อความจบก่อนรูปเสมอ — ต้องรอรูปแยกอีกที ไม่งั้นได้ 0 ใบ
            log("รอ GPT วาดสตอรีบอร์ด…")
            urls = session.wait_reply_images(minimum=1)

            # ตัวกรองของ ChatGPT ปฏิเสธเป็นครั้งคราวแม้เนื้อหาไม่มีอะไร (ตัวมันเองยัง
            # บอกให้ "retry") — ลองใหม่รอบเดียวโดยไม่แนบรูป ให้บรรยายจากข้อความแทน
            # ⛔ **"โควตารูปหมด" ไม่ใช่ "โดนตัวกรองปฏิเสธ" — ห้ามรวมกัน**
            #
            # `image_refused()` คืน True ทั้งสองกรณี (มันเรียก `image_quota_out`
            # อยู่ข้างใน) พอเอามาถามตรงนี้ตัวเดียว **โควตาหมดจึงไปเข้าทาง
            # "ลองใหม่แบบไม่แนบรูป"** ซึ่งขอรูปเหมือนเดิม แล้วก็ไม่ได้รูปเหมือนเดิม
            #
            # ราคาที่จ่ายจริง 31 ส.ค. 2569 — ต่อหนึ่งใบ
            #     เสียเวลาเปล่า      ~2 นาที (ถาม + รอรูปจนหมดเวลา)
            #     เสียโควตาข้อความ  1 ครั้ง → เร่งให้เจอ "Too many requests" เร็วขึ้น
            #     รายงานสาเหตุผิด   ขึ้นว่า "โดนตัวกรองปฏิเสธ" ทั้งที่โควตาหมด
            #
            # นี่คือกติกาข้อ 2.3.1 เป๊ะๆ — คำถามเดียวที่ตอบว่า "ใช่" ได้สองสถานการณ์
            # ที่ต้องแก้คนละทาง หัวไฟล์ตรงนิยาม `IMAGE_QUOTA_HINTS` เขียนเตือนไว้แล้ว
            # ว่าต้องแยก แต่จุดที่เรียกใช้กลับเอามารวมกันอีก
            refused = False
            refusal_text = ""
            quota_out = False
            quota_reset = ""
            if not urls:
                last = session.state()["lastReply"]
                if image_quota_out(last):
                    quota_out = True
                    refusal_text = last[:300]
                    quota_reset = image_quota_reset(last)
                    log("  โควตารูปของบัญชี ChatGPT หมด — **ไม่ลองใหม่**"
                        + (f" (เขาบอกว่าคืนสิทธิ์อีก {quota_reset})"
                           if quota_reset else ""))
                elif image_refused(last):
                    refusal_text = last[:300]
                    log("  โดนตัวกรองปฏิเสธ — ลองใหม่แบบไม่แนบรูปสินค้า")
                    reply = session.ask(
                        "ขอใหม่อีกครั้ง คราวนี้ไม่ต้องอ้างอิงรูปที่แนบ "
                        # ⚠️ เดิมสั่ง "ไม่ต้องมีคน" ซึ่ง**ขัดกับกติกาพรีเซนเตอร์**
                        # (เจ้าของสั่ง 9 ก.ย. 2569) ตัดคำว่าคนออก เหลือห้ามโลโก้
                        "วาด storyboard เป็นภาพสเก็ตช์ช่องๆ (ไม่ต้องมีโลโก้แบรนด์) "
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
                # ประโยคปิดสุ่มจากรหัสสินค้า — สินค้าคนละตัวได้คนละแบบ
                # แต่ตัวเดิมสั่งซ้ำได้แบบเดิม จะได้เทียบผลกันได้
                closing = pick_closing(folder.name)
                log(f"  ประโยคปิดการขายรอบนี้: {closing}")
                flow_reply = session.ask(
                    FLOW_PROMPT_ASK + flow_audio_rule(closing))
                flow_prompts = extract_prompts(flow_reply)
                # ---- ขีดคำอ่านบนจอ: ล้างเอง ไม่ขอใหม่ (30 ส.ค. 2569 15:05) ----
                #
                # **วัดแล้วการขอใหม่เป็นการเสียเวลาเปล่า** ลองไปแล้วสองใบ ใช้เวลา
                # 50 วินาทีต่อใบ แล้ว **ขอใหม่ก็ยังไม่ผ่านอยู่ดี** (14:58:15 ขอใหม่
                # → 14:59:05 ยังมีขีดเหมือนเดิม) ChatGPT ไม่ยอมเลิกใส่ขีดตรงนี้
                # แม้กติกาจะเขียนห้ามชัดเจนแล้ว
                #
                # ของแบบนี้ **เราซ่อมเองได้แน่นอน 100%** เพราะเป็นการลบอักขระ
                # ตามกฎที่ทดสอบแล้ว 6/6 เคส — ซ่อมเองจึงเร็วกว่า แม่นกว่า และ
                # ไม่เสี่ยงกับคำตอบใหม่ที่อาจแย่ลง (รอบที่ขอใหม่เคยได้มา 6 ฉาก
                # ทั้งที่ต้องการ 5)
                #
                # หลัก: **สิ่งที่เราซ่อมเองได้ ให้ซ่อม · สิ่งที่ซ่อมเองไม่ได้
                # (บทยาวเกิน · ฉากไม่ครบ) ถึงค่อยขอใหม่**
                import clip_store as _cs                        # noqa: PLC0415
                cleaned = [_cs.strip_reading_hyphens(x) for x in flow_prompts]
                if cleaned != flow_prompts:
                    log("  ล้างขีดคำอ่านที่หลุดไปอยู่ในตัวหนังสือบนจอให้แล้ว")
                    flow_prompts = cleaned
                log(f"  ได้คำสั่ง {len(flow_prompts)} ชุด")
                if len(flow_prompts) != SPEAK_SCENES:
                    warnings.append(
                        f"ได้คำสั่ง {len(flow_prompts)} ฉาก ไม่ใช่ {SPEAK_SCENES} ฉาก "
                        "— คลิปจะยาว/สั้นกว่าที่ตั้งใจ")
                    log(f"  ⚠️ ได้ {len(flow_prompts)} ฉาก ไม่ใช่ {SPEAK_SCENES}")
                # ---- ตรวจว่ามีบรรทัดสั่งเสียงครบทุกฉากไหม -------------------
                #
                # **ต้องรู้ตรงนี้ ไม่ใช่ไปรู้ตอนคลิปเจนเสร็จแล้วเงียบ** — ตอนนั้น
                # เสียเครดิต Flow ไปแล้วและต้องเจนใหม่ทั้งรอบ ส่วนตรงนี้แค่ถามซ้ำ
                # ในแชทเดิม ไม่มีต้นทุนอะไรเลยนอกจากเวลาไม่กี่วินาที
                #
                # ขอซ้ำครั้งเดียวพอ — ถ้ายังไม่ครบแปลว่า GPT ไม่ยอมทำตาม
                # การวนขอไม่รู้จบมีแต่จะกินเวลาโดยไม่ได้อะไรเพิ่ม
                # ขอใหม่เฉพาะเรื่องที่ **เราซ่อมเองไม่ได้** — บทยาวเกิน · ฉากไม่ครบ
                # ส่วนขีดบนจอล้างไปแล้วข้างบน ไม่ต้องมาขอใหม่ให้เสียเวลา
                problem = flow_audio_problem(flow_prompts)
                if problem:
                    log(f"  ⚠️ บรรทัดเสียงยังไม่ผ่านกติกา: {problem} — ขอใหม่อีกครั้ง")
                    # **ขอแก้เฉพาะบรรทัดเสียงก่อน** คำสั่งภาพไม่ได้ผิดอะไรเลยสักฉาก
                    #
                    # วัดจริง 31 ส.ค. 2569: 82% ของงานเขียนบทครั้งแรกยาวเกินเพดาน แล้วของเดิม
                    # สั่งว่า "ขอคำสั่งชุดเดิมใหม่ทั้งหมด" ทำให้ GPT เขียนฉากภาษาอังกฤษยาว
                    # ราว 5,000 ตัวอักษรใหม่ทั้งชุด **เสีย 57 วินาที = 24% ของเวลาทั้งใบ**
                    # ทั้งที่คำสั่งภาพไม่มีอะไรผิด ผิดแค่บทพูดยาวไป 15-20 ตัวอักษร
                    #
                    # ตรงนี้ขอกลับมาแค่ 5 บรรทัดสั้นๆ แล้วสลับใส่ของเดิม ถ้าไม่สำเร็จ
                    # **ถอยไปใช้วิธีเดิมทั้งดุ้น** ไม่ใช่ยอมรับของครึ่งๆ กลางๆ
                    again = []
                    said = audio_lines(flow_prompts)
                    if said:
                        try:
                            short = session.ask(shorten_audio_ask(problem, said))
                            fresh = parse_numbered(short, len(said))
                            swapped = swap_audio_lines(flow_prompts, fresh) if fresh else []
                            if swapped and not flow_audio_problem(swapped):
                                again, retry = swapped, short
                                log(f"  แก้เฉพาะบรรทัดเสียงสำเร็จ {len(fresh)} ฉาก "
                                    "— ไม่ต้องให้เขียนคำสั่งภาพใหม่")
                            else:
                                # **ต้องบอกว่าไม่ผ่านเพราะอะไร** ไม่งั้นแก้ไม่ถูกจุด
                                if not fresh:
                                    why = ("แกะบรรทัดที่ขึ้นต้นด้วยเลขไม่ได้ · "
                                           f"คำตอบขึ้นต้นว่า {short.strip()[:70]!r}")
                                elif not swapped:
                                    why = "สลับใส่คำสั่งเดิมไม่ได้"
                                else:
                                    why = flow_audio_problem(swapped)
                                log(f"  แก้เฉพาะบรรทัดเสียงไม่ผ่าน ({why}) "
                                    "— ขอคำสั่งใหม่ทั้งชุดแทน")
                        except Exception as error:                      # noqa: BLE001
                            log(f"  ขอแก้บรรทัดเสียงไม่สำเร็จ ({error}) — ขอทั้งชุดแทน")
                    if not again:
                        retry = session.ask(
                            f"คำสั่งที่ให้มายังไม่ถูกกติกา: {problem}"
                            "\n\n"
                            "ขอคำสั่งชุดเดิมใหม่ทั้งหมด โดยทำตามนี้ให้ครบ:"
                            + flow_audio_rule(closing)
                        )
                        again = extract_prompts(retry)
                    # **ตัวตัดสินต้องเป็นตัวเดียวกับด่าน** ของเดิมนับ "ฉากที่ไม่มีเสียง"
                    # ซึ่งกลายเป็นผิดตั้งแต่เปลี่ยนกติกาเป็นพูดแค่ 3 จาก 5 ฉาก —
                    # GPT ตอบถูกกติกามา ระบบจะเห็นว่ามี 2 ฉากไม่มีเสียงแล้ว
                    # **ทิ้งของที่ถูก เก็บของผิดไว้แทน** (แก้ 29 ส.ค. 2569)
                    again = [_cs.strip_reading_hyphens(x) for x in (again or [])]
                    still = flow_audio_problem(again) if again else "ไม่ได้คำสั่งกลับมา"
                    if again and not still:
                        flow_reply, flow_prompts = retry, again
                        log(f"  ได้คำสั่งใหม่ {len(again)} ชุด · ผ่านกติกาแล้ว")
                    else:
                        # ของใหม่ไม่ได้ดีกว่าเดิม เก็บของเดิมไว้ แต่**ต้องไม่เงียบ**
                        warnings.append(
                            f"คำสั่ง Flow ยังไม่ถูกกติกา ({problem}) "
                            "— คลิปที่ได้อาจมีเสียงไม่ครบหรือถูกตัดกลางคัน")
                        log(f"  ⚠️ ขอใหม่แล้วยังไม่ผ่าน ({still}) — เก็บของเดิมไว้")
            except Exception as error:                          # noqa: BLE001
                warnings.append(f"ขอคำสั่ง Flow ไม่สำเร็จ ({error})")
                log(f"  ⚠️ ขอคำสั่ง Flow ไม่สำเร็จ: {error} — เก็บสตอรีบอร์ดที่ได้ไว้ก่อน")

            # ---- บทพูด: ดึงจากบรรทัด Audio ในคำสั่ง Flow ----------------------
            #
            # **เลิกถามรอบสองแล้ว (เจ้าของสั่ง 29 ส.ค. 2569)** เดิมตรงนี้ยิงคำถาม
            # "ขอบทพูด" อีกรอบ แล้ว GPT ก็แต่งบทใหม่ให้คนละสำนวนกับที่ฝังไว้ใน
            # คำสั่ง Flow — ได้บทสองฉบับที่ **ตรงกัน 0 จาก 65 ใบ**
            #
            # ตัวที่ผู้ใช้เห็นและกดอนุมัติคือฉบับรอบสอง แต่ **ตัวที่ Veo อ่านจริง
            # คือฉบับที่อยู่ในคำสั่ง Flow** ปุ่มอนุมัติกับการพิมพ์แก้บทพูดจึงไม่มีผล
            # กับคลิปเลยสักใบ และตัวตรวจคลิปก็เทียบผิดฉบับจนฟ้อง "พูดไม่ตรงบท"
            # ไป 18 ใบทั้งที่ Veo พูดตามที่สั่งเป๊ะทุกคำ
            #
            # ตอนนี้บทมีฉบับเดียว — ที่เห็น ที่อนุมัติ ที่แก้ และที่ Veo อ่าน
            # เป็นข้อความเดียวกันหมด
            #
            # ผลพลอยได้: ตัดการถาม GPT ไปหนึ่งรอบ เร็วขึ้นและกินโควตาน้อยลง
            log("แกะบทพูดจากบรรทัด Audio ในคำสั่ง Flow")
            # เหลือขีดอยู่อีกหลังล้างแล้ว = เจอรูปแบบที่ตัวล้างยังไม่รู้จัก
            # ต้องดังขึ้น ไม่ใช่ปล่อยผ่าน (กติกาข้อ 2.3)
            leftover = flow_visual_problem(flow_prompts)
            if leftover:
                warnings.append(f"ล้างขีดบนจอไม่หมด: {leftover}")
                log(f"  ⚠️ {leftover}")
            script_reply, script = flow_reply, audio_lines(flow_prompts)
            if script:
                log(f"  ได้บทพูด {len(script)} ฉาก "
                    f"({speech_chars(script)} ตัวอักษร)")
            else:
                warnings.append("คำสั่ง Flow ไม่มีบรรทัดสั่งเสียงพูดเลย "
                                "— คลิปที่ได้จะเงียบ")
                log("  ⚠️ ไม่มีบรรทัด Audio ให้แกะ — คลิปจะเงียบ")

            return {
                "chat_url": session.state()["url"],
                "reply": reply,
                "frames": [str(path) for path in frames],
                "refused": refused,
                "refusal_text": refusal_text,
                # **แยกจาก `refused` เพราะทางแก้ต่างกันคนละขั้ว**
                # โดนตัวกรอง = แก้คำแล้วลองใหม่ได้เดี๋ยวนี้
                # โควตาหมด   = ลองใหม่กี่ครั้งก็ไม่มีรูป ต้องรอถึงเวลาคืนสิทธิ์
                "quota_out": quota_out,
                "quota_reset": quota_reset,
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
                if not urls:
                    last = session.state()["lastReply"]
                    # แยกเหมือนตอนทำครั้งแรก — โควตาหมดไม่ใช่โดนปฏิเสธ
                    if image_quota_out(last):
                        result["quota_out"] = True
                        result["quota_reset"] = image_quota_reset(last)
                        result["refusal_text"] = last[:300]
                        result["frames"] = []
                        log("  โควตารูปหมด — สั่งแก้ตอนนี้ก็ไม่ได้ภาพ")
                        return result
                    if image_refused(last):
                        result["refused"] = True
                        result["refusal_text"] = last[:300]
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
