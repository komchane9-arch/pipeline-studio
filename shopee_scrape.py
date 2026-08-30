"""ดึงข้อมูลสินค้าจากลิงก์ Shopee — รูปทั้งหมด + ชื่อ + รายละเอียด

ทำไมต้องเปิดเบราว์เซอร์จริง ไม่ยิง API:
  Shopee ปิด API ภายในไว้แล้ว (`/api/v4/pdp/get_pc` ตอบ error 90309999 ทุกครั้ง
  แม้ใส่ Referer/User-Agent ครบ) เหลือทางเดียวคือโหลดหน้าเว็บจริงแล้วอ่าน DOM
  ใช้โปรไฟล์ Chrome ตัวเดียวกับ Flow/TikTok จึงผ่านด่านกันบอทได้เหมือนคนใช้จริง

สิ่งที่ดึง (ตามที่ผู้ใช้วงไว้ในภาพ):
  - ชื่อสินค้า      → หัวเรื่องเหนือราคา
  - รายละเอียด      → บล็อกใต้หัวข้อ "รายละเอียด" (ไม่ใช่ "คุณลักษณะ")
  - รูปทั้งหมด      → รูปหลัก + รูปตัวเลือกสินค้าทุกใบ (แปลงเป็นความละเอียดเต็ม)
"""

from __future__ import annotations

import json
import random
import re
import time
import urllib.request
from datetime import datetime
from pathlib import Path

import evidence
import gemini_quota

# ชื่อที่ Shopee คืนมาตอน **ไม่ใช่หน้าสินค้าจริง** — หน้าบล็อก/หน้ารอ/หน้าโปรโมชัน
#
# เดิมดักแค่ "Hot Deals" ตัวเดียว ผลคือ 25 ส.ค. 2026 หน้าบล็อกที่ชื่อ
# "Please Try Again Later" หลุดผ่านเข้ามาเป็นสินค้าจริง **แล้วถูกบันทึกเข้าคลัง**
# กลายเป็นสินค้าผีที่ไม่มีรูปไม่มีคำบรรยาย — ข้อมูลปลอมแย่กว่าไม่มีข้อมูล
BLOCKED_TITLES = (
    "hot deals",
    "please try again later",
    "try again later",
    "verify to continue",        # หน้าจิ๊กซอว์ยืนยันตัวตน — เจอจริง 25 ส.ค. 16:14
    "shopee thailand",           # หน้าแรก ไม่ใช่หน้าสินค้า
    "access denied",
    "too many requests",
    "page not found",
    "error",
)


def _looks_blocked(name: str) -> bool:
    """ชื่อที่อ่านมาเป็นหน้าบล็อกหรือหน้าสินค้าจริง

    เทียบแบบ "ทั้งชื่อเป็นคำนี้" ไม่ใช่ "มีคำนี้อยู่ข้างใน" เพราะสินค้าจริง
    อาจมีคำว่า error หรือ hot deals อยู่ในชื่อได้ (เช่น "ลำโพง Error Sound")
    ยกเว้น "please try again later" ที่ยาวและเฉพาะพอจะเทียบแบบมีอยู่ข้างในได้
    """
    text = str(name or "").strip().lower()
    if not text:
        return True
    if "please try again" in text or "too many request" in text:
        return True
    return text in BLOCKED_TITLES


SHORT_LINK_RE = re.compile(r"https?://s\.shopee\.[a-z.]+/\S+", re.I)
PRODUCT_URL_RE = re.compile(r"https?://(?:[a-z-]+\.)?shopee\.[a-z.]+/\S+", re.I)
# รูปแบบ id ที่เจอบนหน้าสินค้า: /ชื่อร้าน/shop_id/item_id  หรือ  -i.shop_id.item_id
IDS_PATH_RE = re.compile(r"/(?:[^/]+/)?(\d{6,})/(\d{6,})")
IDS_DASH_RE = re.compile(r"-i\.(\d+)\.(\d+)")

def _chrome_version() -> str:
    """รุ่น Chrome **ที่ติดตั้งจริงในเครื่องนี้** ไม่ใช่เลขที่พิมพ์ค้างไว้ในโค้ด

    **ทำไมถึงต้องอ่านของจริง** (แก้ 27 ส.ค. 2026 หลังโดน Shopee บล็อก)

    ของเดิมพิมพ์ `Chrome/126.0.0.0` ตายตัวไว้ แต่ Chrome ในเครื่องคือ **151**
    ห่างกัน 25 รุ่น ผลคือจากที่อยู่เดียวกันในนาทีเดียวกัน Shopee เห็นสองอย่าง:
    หน้าเว็บถูกเปิดโดย Chrome 151 แล้ว **รูป 129 ใบถูกโหลดโดย "Chrome 126"**
    ซึ่งเป็นไปไม่ได้ในเครื่องจริง — เท่ากับยื่นบัตรคนละใบให้ยามคนเดียวกัน

    เลขที่พิมพ์ตายตัวยัง **เก่าลงทุกวัน** โดยไม่มีใครรู้ตัว Chrome อัปเดตเองทุก
    2-3 สัปดาห์ ส่วนเลขในโค้ดอยู่กับที่ตลอดกาล ยิ่งนานยิ่งผิดชัดขึ้นเรื่อยๆ

    อ่านไม่ได้ = ถอยไปใช้เลขเดิม ไม่ใช่ล้ม (ตัวช่วยแต่งหัวจดหมายห้ามทำงานพัง)
    """
    import subprocess
    for exe in (r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"):
        if not Path(exe).is_file():
            continue
        try:
            out = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 f"(Get-Item '{exe}').VersionInfo.ProductVersion"],
                capture_output=True, text=True, timeout=15,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            ).stdout.strip()
            if re.fullmatch(r"\d+(\.\d+)+", out):
                return out
        except (OSError, subprocess.SubprocessError):
            pass
    return "126.0.0.0"


CHROME_VERSION = _chrome_version()

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        f"(KHTML, like Gecko) Chrome/{CHROME_VERSION} Safari/537.36"
    )
}

PAGE_TIMEOUT = 60_000
SETTLE_SECONDS = 4.0
MAX_IMAGES = 30


SHOPEE_HOME = "https://shopee.co.th/"


class ShopeeError(RuntimeError):
    """ดึงข้อมูลไม่สำเร็จ"""


class ShopeeNeedsLogin(ShopeeError):
    """ยังไม่ได้ล็อกอิน Shopee ในโปรไฟล์เบราว์เซอร์นี้

    Shopee ไทยปิดหน้าสินค้าไม่ให้คนที่ยังไม่ล็อกอินดู (ขึ้น "Login Required")
    จึงต้องล็อกอินครั้งเดียวเก็บคุกกี้ไว้ในโปรไฟล์ เหมือนที่ทำกับ Flow และ TikTok
    """


def resolve_link(link: str) -> str:
    """คลี่ลิงก์สั้น s.shopee.co.th ให้เป็นลิงก์สินค้าเต็ม

    **ลิงก์ที่อ่านรหัสได้อยู่แล้วไม่ต้องยิงถามใหม่** (27 ส.ค. 2569)

    ของเดิมยิงคำขอไป Shopee ทุกครั้งแม้ลิงก์จะเต็มอยู่แล้ว ซึ่ง
    **นับเป็นคำขอสะสมเหมือนกัน** — และยอดสะสมคือตัวที่ทำให้โดนบล็อก
    ไม่ใช่ความถี่ต่อใบ (วัดจริง: 158 คำขอ/11 นาที แล้วโดน)

    ยังยิงอยู่ในสองกรณี — ลิงก์สั้น `s.shopee.co.th` (ไม่คลี่ก็ไม่รู้รหัส)
    และลิงก์เต็มที่อ่านรหัสไม่ออก (หน้าร้าน · หน้าค้นหา · ลิงก์แปลกๆ)
    """
    clean = link.strip()
    if not PRODUCT_URL_RE.match(clean) and not SHORT_LINK_RE.match(clean):
        raise ShopeeError("ไม่ใช่ลิงก์ Shopee")
    if not SHORT_LINK_RE.match(clean):
        try:
            parse_ids(clean)
            return clean          # อ่านรหัสได้แล้ว ไม่ต้องถาม Shopee ซ้ำ
        except ShopeeError:
            pass                  # อ่านไม่ออก ต้องให้ Shopee พาไปหน้าจริง
    request = urllib.request.Request(clean, headers=BROWSER_HEADERS)
    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            return response.geturl()
    except OSError as error:
        raise ShopeeError(f"เปิดลิงก์ไม่ได้: {error}") from error


def parse_ids(url: str) -> tuple[str, str]:
    """คืน (shop_id, item_id) จาก URL สินค้า"""
    dash = IDS_DASH_RE.search(url)
    if dash:
        return dash.group(1), dash.group(2)
    path = IDS_PATH_RE.search(url.split("?")[0])
    if path:
        return path.group(1), path.group(2)
    raise ShopeeError("อ่านรหัสร้าน/รหัสสินค้าจากลิงก์ไม่ได้")


# อ่านค่าจากหน้าเว็บจริง — เขียนเป็น JS ก้อนเดียวเพื่อให้แก้ selector ที่เดียวจบ
# เมื่อ Shopee เปลี่ยนหน้าตา (เว็บนี้เปลี่ยน class บ่อย จึงไล่หาหลายทางซ้อนกัน)
EXTRACT_JS = r"""
() => {
  const norm = (s) => (s || '').replace(/ /g, ' ').replace(/[ \t]+/g, ' ').trim();

  // ---------- ชื่อสินค้า ----------
  // ตัวจริงคือ h1 แต่บางธีมใช้ div ที่มี class ชื่อ product-briefing
  let name = '';
  const h1 = document.querySelector('h1');
  if (h1) name = norm(h1.textContent);
  if (!name) {
    const meta = document.querySelector('meta[property="og:title"]');
    if (meta) name = norm(meta.content);
  }

  // ---------- รายละเอียด ----------
  // หาหัวข้อ "รายละเอียด"/"Product Description" แล้วเก็บเนื้อหาถัดจากนั้น
  // ห้ามเอาบล็อก "คุณลักษณะ" (specification) มาปนเพราะเป็นตาราง ไม่ใช่คำโฆษณา
  let detail = '';
  const heads = [...document.querySelectorAll('div, h2, h3, span, section')];
  for (const head of heads) {
    const text = norm(head.textContent);
    if (head.children.length > 2) continue;
    if (!/^(รายละเอียด|รายละเอียดสินค้า|Product Description)$/i.test(text)) continue;
    let node = head.parentElement;
    for (let depth = 0; depth < 4 && node; depth++) {
      const body = norm(node.innerText);
      if (body.length > text.length + 60) { detail = body; break; }
      node = node.parentElement;
    }
    if (detail) break;
  }
  if (!detail) {
    const meta = document.querySelector('meta[name="description"]');
    if (meta) detail = norm(meta.content);
  }
  // ตัดหัวข้อที่ติดมาข้างหน้าออก เหลือแต่เนื้อ
  detail = detail.replace(/^(รายละเอียดสินค้า|รายละเอียด|Product Description)\s*/i, '');

  // ---------- รูปทั้งหมด ----------
  // Shopee เสิร์ฟรูปเป็น .../ไอดี_tn (ย่อ) — ตัด _tn ทิ้งได้ไฟล์เต็ม
  // เก็บทั้งรูปหลักและรูปตัวเลือกสินค้า (12 ตัวเลือก = 12 ใบ) โดยไม่เอาไอคอน/แบนเนอร์
  const seen = new Set();
  const images = [];
  const push = (raw) => {
    if (!raw) return;
    let url = raw.split('?')[0].replace(/_tn$/, '');
    if (url.startsWith('//')) url = 'https:' + url;
    if (!/(susercontent|shopee)/.test(url)) return;
    const id = url.split('/').pop();
    if (!id || id.length < 12) return;      // ไอคอน/สไปรท์มักชื่อสั้น
    if (seen.has(id)) return;
    seen.add(id);
    images.push(url);
  };
  for (const img of document.querySelectorAll('img')) {
    const box = img.getBoundingClientRect();
    if (box.width < 40 || box.height < 40) continue;   // ตัดไอคอนเล็กๆ ทิ้ง
    push(img.getAttribute('src'));
  }
  // รูปที่วางเป็น background ของ div (Shopee ใช้ทั้งสองแบบ)
  for (const el of document.querySelectorAll('div[style*="background-image"]')) {
    const match = /url\(["']?(.*?)["']?\)/.exec(el.getAttribute('style') || '');
    if (match) push(match[1]);
  }

  return { name, detail, images, url: location.href };
}
"""


CDN_PREFIX = "https://down-th.img.susercontent.com/file/"

# ยิง API ภายในจาก **หน้าเว็บที่ล็อกอินแล้ว** (same-origin จึงติดคุกกี้ไปเอง)
# ยิงจากข้างนอกด้วย urllib จะโดนตอบ error 90309999 เสมอ แม้ใส่เฮดเดอร์ครบ
# ทางนี้ได้ข้อมูลครบกว่าการอ่าน DOM มาก: DOM โหลดรูปแค่ 6-7 ใบ (carousel ยังไม่กาง)
# แต่ API คืนรูปแกลเลอรีครบทุกใบ + รูปตัวเลือกสินค้าทุกแบบ
API_FETCH_JS = r"""
async ([itemId, shopId]) => {
  const url = `/api/v4/pdp/get_pc?item_id=${itemId}&shop_id=${shopId}&detail_level=0`;
  const response = await fetch(url, {
    credentials: 'include',
    headers: {
      'Accept': 'application/json',
      'X-Requested-With': 'XMLHttpRequest',
      'af-ac-enc-dat': 'null',
    },
  });
  const payload = await response.json();
  if (payload.error) return { error: String(payload.error), error_msg: payload.error_msg };
  const data = payload.data || {};
  const item = data.item || {};

  // แยกประเภทรูปไว้ตั้งแต่ต้น เพื่อให้คัดได้ว่าจะเอารูปไหนไปใช้เจน
  //   overview = ภาพรวมมีพื้นหลัง (ใบแรกของแกลเลอรี — ใบที่ Shopee โชว์เป็นปก)
  //   variant  = รูปตัวเลือกสินค้า ใบละสี/รุ่น
  //   gallery  = รูปแกลเลอรีที่เหลือ
  const seen = new Set();
  const images = [];
  const add = (id, kind, label) => {
    if (!id || seen.has(id)) return;      // รูปเดียวกันใช้ซ้ำหลายที่ เก็บครั้งเดียว
    seen.add(id);
    images.push({ id, kind, label: label || '' });
  };

  const gallery = data.product_images?.images || [];
  gallery.forEach((id, index) => add(id, index === 0 ? 'overview' : 'gallery', ''));

  for (const tier of item.tier_variations || []) {
    const options = tier.options || [];
    (tier.images || []).forEach((id, index) => {
      add(id, 'variant', options[index] || `${tier.name || 'ตัวเลือก'} ${index + 1}`);
    });
  }

  // รายละเอียดมาเป็นย่อหน้า มีทั้งข้อความและรูปแทรก
  const paragraphs = item.rich_text_description?.paragraph_list || [];
  const detail = paragraphs.filter((p) => p.text).map((p) => p.text).join('\n');
  paragraphs.filter((p) => p.img_id).forEach((p) => add(p.img_id, 'description', ''));

  return {
    name: item.title || '',
    detail,
    images,
    variation_name: item.tier_variations?.[0]?.name || '',
  };
}
"""

# เช็คว่าของยังมีอยู่ไหม — ใช้ detail_level=1 เพราะระดับ 0 ไม่ส่งรายการตัวเลือกมา
#
# Shopee **ไม่ส่งจำนวนชิ้นจริง** ออกมาทาง endpoint นี้ (ทุกฟิลด์ stock เป็น null
# เพราะร้านซ่อนจำนวนไว้) สิ่งที่เชื่อได้คือสถานะรวม:
#   stock_display  "IN STOCK" / "OUT OF STOCK"
#   is_unavailable  ปิดการขายชั่วคราว
#   item_status     normal = ปกติ, อย่างอื่นคือถูกลบ/ถูกแบน
#   models[].status 1 = ตัวเลือกนั้นยังขายอยู่
STOCK_JS = r"""
async ([itemId, shopId]) => {
  const url = `/api/v4/pdp/get_pc?item_id=${itemId}&shop_id=${shopId}&detail_level=1`;
  const response = await fetch(url, {
    credentials: 'include',
    headers: {
      'Accept': 'application/json',
      'X-Requested-With': 'XMLHttpRequest',
      'af-ac-enc-dat': 'null',
    },
  });
  const payload = await response.json();
  if (payload.error) return { error: String(payload.error) };
  const item = (payload.data || {}).item || {};
  const models = (item.models || []).map((m) => ({
    name: m.name || '',
    active: m.status === 1,
    stock: m.stock ?? m.normal_stock ?? null,
  }));
  return {
    name: item.title || '',
    stock_display: item.stock_display || '',
    is_unavailable: !!item.is_unavailable,
    item_status: item.item_status || '',
    status: item.status,
    hide_stock: !!item.is_hide_stock,
    total_stock: item.stock ?? item.normal_stock ?? null,
    models,
  };
}
"""


def read_stock(link: str, open_browser, log=print) -> dict:
    """เช็คว่าสินค้าจากลิงก์นี้ยังมีของอยู่ไหม

    คืน in_stock=True/False พร้อมเหตุผล และรายการตัวเลือกที่ยังขายอยู่
    ถ้าร้านซ่อนจำนวน (ปกติของ Shopee) จะไม่มีตัวเลข — บอกได้แค่มี/หมด
    """
    from playwright.sync_api import sync_playwright

    full_url = resolve_link(link)
    shop_id, item_id = parse_ids(full_url)

    with sync_playwright() as playwright:
        browser = open_browser(playwright, hidden=True)
        page = browser.pages[0] if browser.pages else browser.new_page()
        try:
            page.goto(SHOPEE_HOME, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT)
            time.sleep(2.0)
            gate = _page_is_gated(page)
            if gate and re.search(r"Login", gate, re.I):
                raise ShopeeNeedsLogin(
                    "Shopee ให้ล็อกอินก่อน — รัน `python flow_worker.py login-shopee`"
                )
            if gate:
                raise ShopeeError(f"Shopee ขึ้นด่านยืนยันตัวตน ({gate})")
            data = page.evaluate(STOCK_JS, [item_id, shop_id])
        finally:
            browser.close()

    if data.get("error"):
        raise ShopeeError(f"Shopee ตอบ error {data['error']}")

    models = data.get("models") or []
    active = [m for m in models if m["active"]]
    display = (data.get("stock_display") or "").upper()

    if data.get("item_status") and data["item_status"] != "normal":
        in_stock, reason = False, f"สินค้าถูกปิด/ลบ (สถานะ {data['item_status']})"
    elif data.get("is_unavailable"):
        in_stock, reason = False, "ร้านปิดการขายชั่วคราว"
    elif "OUT OF STOCK" in display or "SOLD OUT" in display:
        in_stock, reason = False, "Shopee แจ้งว่าของหมด"
    elif models and not active:
        in_stock, reason = False, "ตัวเลือกสินค้าปิดขายหมดทุกแบบ"
    elif "IN STOCK" in display or active or data.get("status") == 1:
        in_stock = True
        reason = (
            f"ยังมีของ ({len(active)} ตัวเลือกจาก {len(models)} แบบ)" if models
            else "ยังมีของ"
        )
    else:
        in_stock, reason = False, "อ่านสถานะไม่ได้ชัดเจน"

    log(f"เช็คสต็อก: {reason}")
    return {
        "url": full_url, "shop_id": shop_id, "item_id": item_id,
        "name": data.get("name", ""),
        "in_stock": in_stock,
        "reason": reason,
        "stock_display": data.get("stock_display", ""),
        # ร้านส่วนใหญ่ซ่อนจำนวน ตัวเลขจึงมักเป็น None — อย่าเอาไปคิดว่าเท่ากับ 0
        "total_stock": data.get("total_stock"),
        "hide_stock": data.get("hide_stock", False),
        "models": models,
        "active_models": [m["name"] for m in active],
        "checked_at": datetime.now().isoformat(timespec="seconds"),
    }


GATE_PATTERNS = re.compile(
    r"Login Required|Log ?in to continue|เข้าสู่ระบบเพื่อ"
    r"|Verify to Continue|slide to complete|Loading Issue|ยืนยันตัวตน",
    re.I,
)

VERIFY_WAIT_SECONDS = 300     # เวลาที่ให้ผู้ใช้เลื่อนจิ๊กซอว์เอง


def _page_is_gated(page) -> str:
    """คืนข้อความด่านที่เจอ ถ้าผ่านแล้วคืนค่าว่าง

    **ห้ามโยน exception ออกไป** — ตัวอ่านหน้าจอต้องไม่ทำให้ทั้งงานล้ม

    25 ส.ค. 2026: Shopee เด้งหน้าไปหน้า CAPTCHA **ระหว่าง** ที่เรากำลังอ่าน
    ทำให้ `page.evaluate` ตายด้วย "Execution context was destroyed" แล้ว error
    ลอยขึ้นไปฆ่าทั้งงาน ทั้งที่ความจริงคือ "กำลังโดนเด้งไปด่าน" ซึ่งเป็นคำตอบ
    ที่ฟังก์ชันนี้มีหน้าที่บอกอยู่แล้ว — ล้ม 20 ใบเพราะเรื่องนี้

    อ่านไม่ได้ = ถือว่าติดด่าน (ปลอดภัยกว่าเดาว่าผ่าน) แล้วรอให้หน้านิ่งลองใหม่
    """
    for attempt in range(3):
        try:
            body = page.evaluate("document.body ? document.body.innerText.slice(0, 400) : ''")
            found = GATE_PATTERNS.search(body or "")
            return found.group(0) if found else ""
        except Exception as error:
            if "context was destroyed" not in str(error).lower() or attempt == 2:
                # อ่านไม่ได้จริงๆ — ตอบว่าติดด่าน ให้ผู้เรียกไปจัดการต่อ
                return "อ่านหน้าไม่ได้ (หน้าถูกเด้งทิ้ง)"
            time.sleep(1.5)      # หน้ากำลังเปลี่ยน รอให้นิ่งแล้วอ่านใหม่
    return ""


# สลับวิธีดึงข้อมูลทีละใบ (ผู้ใช้สั่ง 27 ส.ค. 2026 — "ให้ใช้ทางลัด สลับกับ
# อ่านหน้าเวป 1:1")
#
# **ปัญหาที่แก้** เมื่อคืน 01:11–01:22 เราถามช่องทางลัดของ Shopee **12 ครั้งติดกัน
# ไม่เว้นเลย** ซึ่งเป็นลายเซ็นที่ชัดมาก — หน้าเว็บของคนจริงไม่มีทางเรียกช่องนั้น
# รวดขนาดนั้น แล้ว Shopee ก็ตีตรากลับมาว่า `scene=crawler_item`
#
# สลับ 1:1 แล้วได้สองอย่างพร้อมกัน
#   • ลายเซ็นทางลัดหายไปครึ่งหนึ่ง และไม่เป็นแถวยาวติดกันอีก
#   • ยังเร็วอยู่ครึ่งหนึ่ง ไม่ต้องแลกความเร็วทั้งหมดเหมือนการเลิกใช้ทางลัดไปเลย
#
# **สุ่มจุดเริ่มตอนเปิดโปรแกรม** ไม่ใช่เริ่มที่ใบคี่เสมอ — ไม่งั้นทุกครั้งที่
# รีสตาร์ตแล้วดึงชุดเดิม ใบเดิมจะใช้วิธีเดิมทุกรอบ กลายเป็นรูปแบบซ้ำอีกแบบหนึ่ง
_ROUTE_TURN = random.randint(0, 1)

# ---- ปิดการสลับแล้ว (ผู้ใช้สั่ง 27 ส.ค. 2026: "ลองเลิกสลับ แล้วรันต่อ") ----
#
# **หลักฐานที่ทำให้เลิก** เปิดใช้การสลับตอน 09:02 แล้วโดนบล็อกภายใน 67 วินาที
# และทั้งสองครั้งที่โดน **ตกอยู่บนตาที่อ่านจากหน้าเว็บพอดี**
#
#   09:02:36  ตาทางลัด    → ได้ข้อมูลครบ 15 รูป ผ่านฉลุย
#   09:03:07  ตาอ่านหน้า  → 09:03:39 โดนบล็อก
#   01:22:15  ตาอ่านหน้า  → 01:22:51 โดนบล็อก  (คืนก่อน เส้นทางเดียวกัน)
#
# ยิ่งดูยิ่งชี้ไปทางเดียวกัน: **การเปิดหน้าสินค้าเต็มๆ เสี่ยงกว่าการถามทางลัด**
# ซึ่งสมเหตุสมผล — หน้าสินค้าเต็มโหลดสคริปต์ตรวจจับของ Shopee มาทั้งชุด
# ส่วนทางลัดเป็นการถามข้อมูลจากหน้าแรกที่ผ่านด่านมาแล้ว
#
# การสลับ 1:1 จึงเท่ากับ **บังคับให้เดินเส้นทางเสี่ยงครึ่งหนึ่งของเวลา**
# = เพิ่มความเสี่ยงแทนที่จะลด ตรงข้ามกับที่ตั้งใจไว้
#
# ⚠️ **ยังไม่ใช่ข้อสรุป มีแค่ 2 ตัวอย่าง** เปิดสวิตช์กลับได้ทันทีถ้าข้อมูลเปลี่ยน
# ทางลัดยังคงถอยไปอ่านหน้าเว็บเองอยู่แล้วเวลามันใช้ไม่ได้ ไม่ได้ตัดทางถอยทิ้ง
ALTERNATE_ROUTES = False


def _use_shortcut() -> bool:
    """ใบนี้ใช้ทางลัดหรืออ่านจากหน้าเว็บ"""
    if not ALTERNATE_ROUTES:
        return True
    global _ROUTE_TURN
    _ROUTE_TURN += 1
    return _ROUTE_TURN % 2 == 0


def scrape(link: str, open_browser, log=print, assisted: bool = True,
           image_root: Path | None = None, want_all: bool = False) -> dict:
    """ดึงข้อมูลสินค้า 1 ชิ้น — `open_browser` ฉีดเข้ามาเพื่อใช้โปรไฟล์เดียวกับตัวอื่น

    assisted=True เปิดหน้าต่างให้เห็น เพราะ Shopee ขึ้นแคปช่าเลื่อนจิ๊กซอว์กับ
    การเข้าแบบอัตโนมัติ ระบบจะ **รอให้ผู้ใช้เลื่อนเอง** แล้วค่อยอ่านข้อมูลต่อ
    (โปรแกรมนี้ไม่แก้แคปช่าให้ — ตั้งใจไม่ทำ)

    **`image_root` = ให้โหลดรูปตั้งแต่ตอนที่หน้าเว็บยังเปิดอยู่** (27 ส.ค. 2026)

    ของเดิมโหลดรูปหลังปิดเบราว์เซอร์ไปแล้ว จึงต้องใช้ตัวโหลดของ Python ซึ่งเป็น
    ร่องรอยที่หนักที่สุดที่ทำให้โดนบล็อก (เหตุผลเต็มที่ `grab_images_with_browser`)
    ใส่ค่านี้มา = โหลดด้วย Chrome ตัวเดียวกันแล้วคืนไฟล์ที่บันทึกไว้ใน `saved_files`
    ไม่ใส่ = ทำงานเหมือนเดิมทุกอย่าง (ของเก่าที่เรียกอยู่จึงไม่พัง)
    """
    from playwright.sync_api import sync_playwright

    full_url = resolve_link(link)
    shop_id, item_id = parse_ids(full_url)
    log(f"เปิดหน้าสินค้า ร้าน {shop_id} สินค้า {item_id}")

    def grab(page, images: list[dict], picked: list[dict]) -> list[str]:
        """โหลดรูปชุดที่ผู้เรียกต้องการ ขณะหน้าเว็บยังเปิดอยู่"""
        if image_root is None:
            return []
        wanted = images if want_all else picked
        urls = [image["url"] for image in wanted]
        if not urls:
            return []
        folder = Path(image_root) / item_id
        files = grab_images_with_browser(page, urls, folder, log=log)
        log(f"ให้ Chrome โหลดรูปเอง {len(files)}/{len(urls)} ใบ "
            f"(ไม่ผ่านตัวโหลดแยกอีกแล้ว)")
        return files

    def dom_images(raw: dict) -> list[dict]:
        """ทางถอย (อ่าน DOM) แยกประเภทรูปไม่ได้ — ใบแรกเป็นภาพรวม ที่เหลือเป็นแกลเลอรี"""
        return [
            {"id": url.split("/")[-1], "url": url,
             "kind": "overview" if index == 0 else "gallery", "label": ""}
            for index, url in enumerate(raw.get("images", [])[:MAX_IMAGES])
        ]

    page_saved: list[str] = []

    with sync_playwright() as playwright:
        browser = open_browser(playwright, hidden=not assisted)
        page = browser.pages[0] if browser.pages else browser.new_page()
        try:
            # เปิดหน้าแรกก่อน ไม่ใช่หน้าสินค้า — หน้าแรกไม่ค่อยโดนด่านยืนยันตัวตน
            # แล้วค่อยยิง API จากตรงนั้น (same-origin คุกกี้ติดไปเอง)
            page.goto(SHOPEE_HOME, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT)
            time.sleep(2.0)
            home_gate = _page_is_gated(page)
            if home_gate:
                # **สัญญาณเตือนล่วงหน้าที่เคยเงียบสนิท** (แก้ 27 ส.ค. 2026)
                #
                # ของเดิมเป็นแค่ `if not _page_is_gated(page):` — พอหน้าแรกโดนกั้น
                # โค้ดก็ข้ามทางลัดไปเฉยๆ **โดยไม่เขียน log สักบรรทัด** แล้วไปล้ม
                # เอาที่หน้าสินค้า ผลคือใน log เห็นแค่ "ใบนี้ล้ม" ทั้งที่ความจริงคือ
                # "โดนติดธงตั้งแต่ก่อนเปิดหน้าสินค้าแล้ว" — คนละเรื่องกันคนละวิธีแก้
                #
                # หน้าแรกโดนกั้น = ทั้งบัญชี/ที่อยู่โดนธง ไม่ใช่ใบนี้มีปัญหา
                # ใบต่อๆ ไปจะล้มตามแน่นอน ตัวเรียกจึงควรพักคิวตั้งแต่เห็นบรรทัดนี้
                log(f"⚠️ หน้าแรก Shopee โดนกั้นแล้ว (\"{home_gate}\") — "
                    f"แปลว่าโดนติดธงทั้งเครื่อง ไม่ใช่แค่ลิงก์นี้ · ข้ามทางลัด "
                    f"ไปลองอ่านจากหน้าสินค้าโดยตรง")
                evidence.shot(page, "หน้าแรก Shopee โดนกั้น", tag="shopee",
                              note=f"ด่านที่เจอ: {home_gate}\nลิงก์ที่กำลังจะดึง: {full_url}\n"
                                   f"→ สัญญาณว่าโดนติดธงแล้ว ควรพักคิว")
            elif not _use_shortcut():
                # ตาของ "อ่านจากหน้าเว็บ" — ข้ามทางลัดไปเลย ทั้งที่ทางลัดใช้ได้
                # (ผู้ใช้สั่งให้สลับ 1:1 เหตุผลเต็มอยู่ที่ `_use_shortcut` ข้างบน)
                log("ตานี้อ่านจากหน้าเว็บ (สลับกับทางลัด 1:1 กันโดนจับรูปแบบ)")
            else:
                try:
                    result = page.evaluate(API_FETCH_JS, [item_id, shop_id])
                except Exception as error:
                    # **จุดที่พังจริงตอนโดนบล็อก** — Shopee ตีตราการถาม API ว่าเป็น
                    # โปรแกรมไต่เว็บ (`scene=crawler_item`) แล้ว **เด้งหน้าทิ้ง
                    # กลางคัน** ทำให้ evaluate ตายด้วย "Execution context was destroyed"
                    #
                    # เดิมปล่อยให้ error ลอยขึ้นไป = ทั้งใบล้มทันที ทั้งที่โค้ด
                    # มีทางถอย (อ่านจากหน้าเว็บ) อยู่ข้างล่างแล้ว — เหมือนมีประตู
                    # สำรองแต่ไฟดับก่อนเดินไปถึง (25 ส.ค. 2026 ล้มแบบนี้ 23 ใบ)
                    #
                    # พิสูจน์แล้วว่าโปรไฟล์เราไม่ได้โดนแบน: เปิดหน้าสินค้าเดียวกัน
                    # ด้วยโปรไฟล์นี้ตอน 17:58 เปิดได้ปกติ ไม่ติดด่านเลย
                    # ที่โดนคือ "วิธีถาม" ไม่ใช่ "ตัวเบราว์เซอร์"
                    evidence.shot(page, "โดนเด้งหน้าตอนถามข้อมูลสินค้า", tag="shopee",
                                  note=f"ลิงก์: {full_url}\nสาเหตุ: {error}\n"
                                       f"→ ถอยไปอ่านจากหน้าเว็บแทน")
                    log("ถามข้อมูลทางลัดไม่ได้ (โดนเด้งหน้า) — ถอยไปอ่านจากหน้าเว็บแทน")
                    result = {"error": str(error)[:200]}
                if not result.get("error") and result.get("name"):
                    images = [
                        {**image, "url": CDN_PREFIX + image["id"]}
                        for image in result["images"][:MAX_IMAGES]
                    ]
                    picked = candidate_images(images)
                    log(
                        f"ได้จาก API — รูปทั้งหมด {len(images)} ใบ "
                        f"เป็นตัวเลือกให้คัด {len(picked)} ใบ"
                    )
                    return {
                        "url": full_url, "shop_id": shop_id, "item_id": item_id,
                        "name": result["name"], "detail": result.get("detail", ""),
                        "variation_name": result.get("variation_name", ""),
                        "images": images, "selected": picked,
                        # โหลดตอนนี้ ขณะหน้ายังเปิด — หลัง `finally` เบราว์เซอร์ปิดแล้ว
                        "saved_files": grab(page, images, picked),
                    }
                log("API ไม่คืนข้อมูล — ถอยไปอ่านจากหน้าเว็บแทน")

            page.goto(full_url, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT)
            time.sleep(SETTLE_SECONDS)

            gate = _page_is_gated(page)
            if gate and re.search(r"Login", gate, re.I):
                raise ShopeeNeedsLogin(
                    "Shopee ให้ล็อกอินก่อนถึงจะดูหน้าสินค้าได้ — "
                    "รัน `python flow_worker.py login-shopee` แล้วล็อกอินครั้งเดียว"
                )
            if gate:
                if not assisted:
                    raise ShopeeError(f"Shopee ขึ้นด่านยืนยันตัวตน ({gate})")
                log(f"Shopee ขึ้นด่าน \"{gate}\" — เลื่อนจิ๊กซอว์ในหน้าต่างที่เปิดอยู่")
                deadline = time.time() + VERIFY_WAIT_SECONDS
                while time.time() < deadline:
                    time.sleep(3)
                    if not _page_is_gated(page):
                        log("ผ่านด่านแล้ว — อ่านข้อมูลต่อ")
                        time.sleep(SETTLE_SECONDS)
                        break
                else:
                    raise ShopeeError(
                        "ยังไม่ได้ยืนยันตัวตนภายในเวลา — เลื่อนจิ๊กซอว์ให้ผ่านแล้วกดดึงข้อมูลใหม่"
                    )

            # เลื่อนลงล่างเพื่อให้รูปที่ lazy-load ถูกโหลดจริง ไม่งั้นได้แต่ placeholder
            for _ in range(6):
                page.mouse.wheel(0, 1400)
                time.sleep(0.6)
            page.mouse.wheel(0, -6000)
            time.sleep(1.0)
            try:
                data = page.evaluate(EXTRACT_JS)
            except Exception as error:
                # หน้าเด้งไปที่อื่นกลางคัน (Shopee เตะออกตอนโดนจำกัดการใช้งาน)
                # เก็บภาพไว้ก่อนเบราว์เซอร์ปิด ไม่งั้นหลักฐานหายไปพร้อมกัน
                evidence.shot(page, "อ่านข้อมูลจากหน้าไม่ได้", tag="shopee",
                              note=f"ลิงก์: {full_url}\nสาเหตุ: {error}")
                raise
            # หน้าที่ได้เป็นหน้าสินค้าจริงหรือหน้าบล็อก — ตรวจก่อนปิดเบราว์เซอร์
            # **ต้องตรวจตรงนี้ ไม่ใช่หลัง browser.close()** เพราะหลังปิดแล้ว
            # แคปภาพไม่ได้อีก (25 ส.ค. 2026 ล้ม 8 ใบรวดโดยไม่มีภาพสักใบ)
            if _looks_blocked(data.get("name", "")):
                evidence.shot(page, "Shopee ขึ้นหน้าบล็อก", tag="shopee",
                              note=f"ลิงก์: {full_url}\n"
                                   f"ชื่อที่อ่านได้: {data.get('name','')}\n"
                                   f"รูปที่เจอ: {len(data.get('images') or [])} ใบ")
            elif not str(data.get("detail") or "").strip():
                evidence.shot(page, "ไม่มีคำบรรยายสินค้า", tag="shopee",
                              note=f"ลิงก์: {full_url}\n"
                                   f"ชื่อ: {data.get('name','')}\n"
                                   f"รูปที่เจอ: {len(data.get('images') or [])} ใบ")
            # **ต้องโหลดรูปตรงนี้ ไม่ใช่หลังออกจากบล็อก** — `finally` ข้างล่างปิด
            # เบราว์เซอร์ทิ้ง พ้นจากตรงนี้ไปก็ไม่มีหน้าเว็บให้ใช้โหลดอีกแล้ว
            if not _looks_blocked(data.get("name", "")):
                shots = dom_images(data)
                page_saved = grab(page, shots, candidate_images(shots))
        finally:
            browser.close()

    if not data.get("name") or _looks_blocked(data["name"]):
        raise ShopeeError(
            f"Shopee ไม่ให้ข้อมูลสินค้า (หน้าที่ได้คือ \"{data.get('name') or 'หน้าว่าง'}\") "
            "— มักเป็นเพราะยิงถี่เกินไปจนโดนจำกัดการใช้งาน "
            "พักสัก 15-30 นาทีแล้วลองใหม่ · ดูภาพหน้าจอด้วย `python evidence.py`"
        )
    images = dom_images(data)
    log(f"ได้ชื่อ + รูป {len(images)} ใบ + รายละเอียด {len(data.get('detail',''))} ตัวอักษร")
    return {
        "url": full_url,
        "shop_id": shop_id,
        "item_id": item_id,
        "name": data["name"],
        "detail": data.get("detail", ""),
        "variation_name": "",
        "images": images,
        "selected": candidate_images(images),
        "saved_files": page_saved,
    }


IMAGE_PICK_COUNT = 3        # ตามผัง: ดึงรูปมา 3 รูป ไม่ซ้ำ
CANDIDATE_LIMIT = 12        # ส่งให้ Gemini ดูมากสุดเท่านี้ พอให้เลือกได้โดยไม่เปลืองโควตา


def candidate_images(images: list[dict]) -> list[dict]:
    """รูปที่มีสิทธิ์ถูกเลือก: ภาพรวมมีพื้นหลัง 1 ใบ + ตัวเลือกสินค้าใบละแบบ

    รูปแกลเลอรีที่เหลือมักเป็นภาพโปรโมชัน/สเปกที่มีตัวหนังสือเต็มไปหมด
    เอาไปเป็นภาพต้นฉบับตอนเจนแล้วผลออกมาเละ จึงไม่เอามาเป็นตัวเลือก
    """
    picked = [image for image in images if image["kind"] == "overview"][:1]
    picked += [image for image in images if image["kind"] == "variant"]
    if not picked:
        picked = [image for image in images if image["kind"] == "gallery"][:1]
    return picked[:CANDIDATE_LIMIT]


def spread_pick(images: list[dict], count: int = IMAGE_PICK_COUNT) -> list[dict]:
    """เลือกแบบกระจาย — ใช้เมื่อไม่มีคีย์ Gemini ให้ช่วยดู

    หยิบภาพรวมก่อน แล้วไล่หยิบตัวเลือกแบบเว้นระยะ เพราะตัวเลือกที่อยู่ติดกัน
    มักเป็นรุ่นใกล้เคียงกันจนรูปเกือบเหมือนกัน หยิบเรียงกันจะได้รูปซ้ำๆ
    """
    overview = [image for image in images if image["kind"] == "overview"][:1]
    rest = [image for image in images if image["kind"] != "overview"]
    need = max(0, count - len(overview))
    if not rest or need == 0:
        return (overview + rest)[:count]
    step = max(1, len(rest) // need)
    spread = rest[::step][:need]
    return (overview + spread)[:count]


# ให้ Gemini ดูรูปจริงแล้วเลือก — ไม่มีทางรู้ว่ารูปไหน "ซ้ำกัน" จากชื่อไฟล์
IMAGE_JUDGE_PROMPT = (
    "นี่คือรูปสินค้าจากหน้า Shopee เดียวกัน หมายเลขกำกับตามลำดับที่ส่งให้\n\n"
    "**งานนี้คือเลือกรูปไปทำคลิปโฆษณา affiliate ที่ตั้งเป้ายอดดู 1 ล้านวิว**\n"
    "รูปที่เลือกจะกลายเป็นฉากในคลิป — รูปหนึ่งใบคือหนึ่งฉาก ฉากที่ไม่มีอะไร\n"
    "ให้พูดถึงคือฉากที่เสียเปล่า และคนดูจะเลื่อนผ่านภายใน 2 วินาทีแรก\n\n"
    "เลือกมา {count} รูป โดยยึด **คุณสมบัติเด่นของสินค้าที่ขายได้** เป็นหลัก\n\n"
    "เลือกรูปแบบนี้\n"
    "• รูปที่ **โชว์จุดขายที่จับต้องได้** — ของที่ทำให้คนอยากได้ เช่น กลไกที่ปรับได้ "
    "ขนาดเทียบกับคน วัสดุใกล้ๆ ฟังก์ชันที่คู่แข่งไม่มี\n"
    "• รูปที่ **เห็นแล้วเข้าใจทันทีโดยไม่ต้องอ่าน** — คนดูคลิปสั้นไม่อ่านตัวหนังสือ\n"
    "• รูปที่ **หยุดนิ้วคนดูได้** — มุมแปลก ของใหญ่ ความต่างชัด สีสด\n"
    "• รูปที่ **เล่าต่อกันเป็นเรื่องได้** เมื่อเรียงติดกัน ไม่ใช่ของซ้ำกัน 5 มุม\n\n"
    "ห้ามเลือก\n"
    "• รูปที่หน้าตาเกือบเหมือนกัน (ได้ฉากซ้ำ = เสียฉากฟรี)\n"
    "• รูปที่มีตัวหนังสือเต็มภาพจนไม่เห็นตัวสินค้า\n"
    "• รูปที่มืด เบลอ หรือเห็นสินค้าไม่ชัด\n\n"
    "ถ้ามีภาพรวมที่มีพื้นหลังสวยให้เอามา 1 รูปไว้เปิดคลิป\n"
    "ตอบเป็น JSON array ของหมายเลขล้วนๆ เช่น [1, 4, 7] ไม่ต้องอธิบาย"
)



def judge_images(
    paths: list[str], api_key: str | None, count: int = IMAGE_PICK_COUNT, log=print,
    extra_rule: str = "", model: str = "",
) -> list[int]:
    """ให้ Gemini เลือกว่ารูปไหนไม่ซ้ำกัน คืน index (เริ่มที่ 0) ของรูปที่เลือก

    `extra_rule` = เกณฑ์เพิ่มเฉพาะกิจ เช่นสินค้าที่ "ปรับเปลี่ยนรูปทรงได้"
    ต้องได้รูปทั้งก่อนและหลังปรับ ไม่ใช่ได้แต่ท่าเดียวสวยๆ หลายใบ

    `model` = เลือกโมเดลเอง ว่าง = ไล่สายพานตามลำดับที่วัดมา (27 ส.ค. 2026)
    """
    if len(paths) <= count:
        return list(range(len(paths)))
    if not api_key:
        log("ไม่มีคีย์ Gemini — เลือกรูปแบบกระจายแทน")
        return []

    import base64

    import httpx

    instruction = IMAGE_JUDGE_PROMPT.format(count=count)
    if extra_rule:
        instruction += "\n" + extra_rule
    parts: list[dict] = [{"text": instruction}]
    for index, path in enumerate(paths, start=1):
        try:
            payload = Path(path).read_bytes()
        except OSError:
            continue
        parts.append({"text": f"รูปที่ {index}"})
        parts.append({
            "inline_data": {
                "mime_type": "image/jpeg",
                "data": base64.b64encode(payload).decode("ascii"),
            }
        })
    # เลือกเอง = ตัวนั้นตัวเดียว · ไม่เลือก = ไล่สายพานจนกว่าจะมีตัวตอบ
    #
    # **ของเดิมยิงตัวเดียวแล้วยอมแพ้** พอถังนั้นหมด (20 ครั้ง/วัน/โมเดล)
    # ตัวเลือกรูปก็ตายทั้งวัน ถอยไปเลือกแบบกระจายซึ่งไม่ได้ดูรูปเลยสักใบ
    want = str(model or "").strip()
    if want and want not in IMAGE_HIGHLIGHT_CHOICES:
        log(f"ไม่รู้จักโมเดล {want} — ใช้สายพานอัตโนมัติแทน")
        want = ""
    chain = (want,) if want else tuple(IMAGE_JUDGE_MODELS)

    gemini_quota.check_budget("เลือกรูปเข้าคลิป")
    tried: list[str] = []
    for pick in chain:
        try:
            response = httpx.post(
                "https://generativelanguage.googleapis.com/v1beta/models/"
                f"{pick}:generateContent",
                params={"key": api_key},
                json={"contents": [{"parts": parts}]},
                timeout=120.0,
            )
            gemini_quota.record(pick, ok=response.status_code == 200,
                                response=response)
            if response.status_code != 200:
                raise RuntimeError(f"{pick} ตอบ {response.status_code}")
            text = response.json()["candidates"][0]["content"]["parts"][0]["text"]
            found = re.search(r"\[.*?\]", text, re.S)
            numbers = json.loads(found.group(0)) if found else []
            # แปลงเลขที่คนอ่าน (เริ่ม 1) เป็น index จริง และกันเลขเกินขอบ
            chosen = [
                int(n) - 1 for n in numbers
                if isinstance(n, (int, float)) and 1 <= int(n) <= len(paths)
            ]
            unique = list(dict.fromkeys(chosen))[:count]
            if unique:
                extra = "" if pick == chain[0] else f" [ตัวสำรอง {pick}]"
                log(f"Gemini เลือกรูปที่ {[i + 1 for i in unique]}{extra}")
                return unique
            raise RuntimeError(f"{pick} ไม่ได้ตอบเป็นเลขรูป")
        except Exception as error:                           # noqa: BLE001
            tried.append(f"{pick}: {error}")
            log(f"  เลือกรูปด้วย {pick} ไม่สำเร็จ ({error})")
    log(f"ให้ Gemini เลือกรูปไม่สำเร็จทุกตัว ({' · '.join(tried)}) — เลือกแบบกระจายแทน")
    return []


# ---------------------------------------------------------- คัดรายละเอียดเด่น

HIGHLIGHT_COUNT = 3

# โมเดลที่ใช้คัดจุดเด่น — **ตัวแรกต้องไม่ซ้ำกับใคร**
#
# โควตาชั้นฟรีนับต่อวันต่อโมเดล (20 ครั้ง) ถ้าใช้ถังเดียวกับงานอื่น พอถังหมด
# ตัวคัดจะเงียบๆ ถอยไปใช้กฎ แล้วได้จุดเด่นที่ไม่ใช่จุดขายเลย
#
# เกิดจริง 22 ส.ค. 2026 เวลา 20:53–20:54: ทีวี TCL 4 เครื่องโดน 429 ทั้งหมด
# กฎสำรองคัดได้เครื่องละ 1 ข้อ และเป็นบรรทัด "รับประกัน 3 ปี" ทุกเครื่อง
# ทั้งที่หน้าสินค้ามีจุดขายจริง 12 ข้อ (Mini LED · 100% BT.2020 · HDR 2000 nits
# · 144Hz · 1,056 โซนหรี่แสง · ONKYO 2.1CH)
#
# ─── จัดใหม่ 27 ส.ค. 2026 หลังเจ้าของเปิดการเรียกเก็บเงินแล้ว ───────────────
#
# **เหตุผลเดิม "ตัวแรกต้องไม่ซ้ำกับใคร" หมดความจำเป็นแล้ว** เพราะเพดาน 20 ครั้ง
# ต่อวันต่อโมเดลเป็นของชั้นฟรี พอเปิดเรียกเก็บเงินก็ไม่มีเพดานนั้นอีก
# (พิสูจน์แล้ว: ยิง gemini-2.5-flash รวดเดียว 26 ครั้ง ผ่านหมด ไม่ตันที่ 20)
# ตัวแรกจึงเลือกจาก **ความเร็วกับคุณภาพที่วัดได้** แทนการเลี่ยงถังโควตา
#
# วัดจริงกับคำบรรยายสินค้า 3,000 ตัวอักษร (งานข้อความล้วน)
#
#   gemini-3.5-flash-lite    ✅   2.0 วิ · ไล่จุดขายได้ 10 ข้อ
#   gemini-3.6-flash         ✅  15.7 วิ · ไล่จุดขายได้  8 ข้อ
#   gemini-3.7-flash         ❌  503 หลังรอ 42.7 วินาที
#
# **เอา 3.7-flash ออกจากหัวสายพาน** — เดิมมันอยู่ตัวแรก แปลว่าทุกครั้งที่คัด
# จุดเด่นต้องรอมันตายก่อน 42 วินาที แล้วค่อยได้คำตอบจากตัวสำรองใน 2 วินาที
# วันนี้มันล้ม 68 จาก 68 ครั้ง (100%) ทั้งงานรูปและงานข้อความ
#
# ⚠️ อย่าหลงกลเหมือนผม — ทดสอบด้วยคำสั่งสั้นๆ ว่า "ตอบว่า ok" มันผ่าน HTTP 200
# แต่พองานจริงที่ยาว 3,000 ตัวอักษรกลับ 503 **ต้องทดสอบด้วยงานจริงเท่านั้น**
#
# ใครใช้อะไรอยู่ (27 ส.ค. 2026)
#   policy_fix / clip_fix   3.6-flash · 3.5-flash · 3-flash-preview
#   clip_check (ดูคลิป)      3.1-flash-lite · 3.5-flash-lite · flash-lite-latest · 2.5-flash
#   hashtag                 3.1-flash-lite-preview  ⚠️ ตัวเดียว ไม่มีทางถอย
#   ดูรูป (IMAGE_HIGHLIGHT)  3.5-flash · 3.6-flash · 2.5-flash · 3.1-flash-lite
#   ที่นี่ (ข้อความล้วน)      3.5-flash-lite → 3.6-flash → 2.5-flash
HIGHLIGHT_MODELS = (
    "gemini-3.5-flash-lite",    # 2.0 วิ · ได้จุดขายมากที่สุดในสามตัว
    "gemini-3.6-flash",
    "gemini-2.5-flash",
)

# ข้อความที่ไม่ใช่จุดขาย — ตัดทิ้งก่อนคัด ไม่งั้นได้แต่เรื่องใบกำกับภาษี
#
# เจ้าของสั่ง 28 ส.ค. 2569 ให้เอาเรื่องร้านกลับมาได้ ("โปรโมท สินค้า : ร้าน แบบ 1:1")
# จึงถอด `ร้านค้า` · `จัดส่ง` · `ขนส่ง` ออกจากรายการตัดทิ้ง
# ที่เหลือยังตัดอยู่เพราะเป็น **ภาระของคนซื้อหรือข้อความทางกฎหมาย** ไม่ใช่สิ่งที่เขาได้
BORING_RE = re.compile(
    r"ใบกำกับภาษี|ใบเสร็จ|กรอกข้อมูล|สอบถาม|ทักแชท|ช่องแชท|รบกวน|เงื่อนไข"
    r"|เปลี่ยนแปลง|แจ้งให้ทราบ|ขอสงวน",
    re.I,
)


def _fallback_highlights(detail: str) -> list[str]:
    """คัดด้วยกฎล้วน — ใช้เมื่อไม่มีคีย์ Gemini

    เลือกบรรทัดที่มีตัวเลข/หน่วย (Mbps, GB, วัน, นาที) เพราะจุดขายของสินค้า
    เกือบทั้งหมดพูดเป็นตัวเลข ส่วนบรรทัดเงื่อนไข/ภาษีไม่มีตัวเลขแบบนี้
    """
    scored: list[tuple[int, str]] = []
    for raw in detail.splitlines():
        line = raw.strip(" •-☘✔✅◆●\t")
        if not 12 <= len(line) <= 120 or BORING_RE.search(line):
            continue
        units = len(re.findall(r"\d+\s*(?:Mbps|GB|MB|kbps|วัน|เดือน|นาที|ปี|ชิ้น|บาท)", line, re.I))
        if not units:
            continue
        scored.append((units, line))
    scored.sort(key=lambda item: -item[0])
    return [line for _, line in scored[:HIGHLIGHT_COUNT]]


# สั่งงานสองจังหวะในคำขอเดียว: **เก็บให้ครบก่อน แล้วค่อยเลือก** (ผู้ใช้สั่ง 22 ส.ค. 2026)
#
# ของเดิมสั่งว่า "สรุปจุดขายเด่นที่สุด 3 ข้อ" ซึ่งบีบตั้งแต่ก้าวแรก โมเดลจึงหยิบ
# ข้อที่เจอก่อนหรือข้อที่เขียนเด่นในหน้า ไม่ได้ชั่งน้ำหนักว่าอันไหน "ทำให้คนหยุดดู"
# พอเป็นสินค้าสเปกเยอะอย่างทีวี (จุดขาย 12 ข้อ) ของดีจะหล่นหายไปโดยไม่มีใครเห็น
#
# แบบใหม่บังคับให้ **ไล่ออกมาให้ครบก่อน** แล้วค่อยเลือกโดยมีเกณฑ์ชัดเจน และให้
# บอกเหตุผลที่เลือกมาด้วย — เหตุผลไม่ได้เอาไปใช้ในคลิป แต่ทำให้คนตรวจงานรู้ว่า
# มันคิดยังไง และจับได้เวลามันเลือกผิด
#
# เก็บรายการเต็มไว้ด้วย เพราะผู้ใช้ต้องสลับข้อที่ไม่ถูกใจได้โดยไม่ต้องยิง AI ใหม่
ANALYSE_PROMPT = (
    'นี่คือรายละเอียดสินค้าจาก Shopee ชื่อ "{name}"\n\n'
    "{detail}\n\n"
    "ทำสองขั้นตามลำดับ แล้วตอบเป็น JSON อย่างเดียว ห้ามมีข้อความอื่น\n\n"
    "ขั้นที่ 1 — ไล่จุดขายออกมาให้ **ครบทุกข้อ** ที่หน้านี้พูดถึง (features)\n"
    "  · ข้อละสั้นๆ **ไม่เกิน 30 ตัวอักษรไทย** — เป็นความยาวที่พูดทันจริง\n"
    "    ในหนึ่งฉาก (คลิป 10 วินาที พูดได้ราว 135 ตัวอักษร หาร 5 ฉาก)\n"
    "    ยาวกว่านี้จะโดนตัดกลางประโยคตอนเอาไปทำบทพูด\n"
    "  · **ภาษาพูดที่คนทั่วไปเข้าใจทันที**\n"
    "  · **ห้ามใช้ศัพท์เทคนิคลอยๆ** เช่น QD-MiniLED · Precise Dimming ·\n"
    "    FreeSync Premium · G-Sync · GtG · HDR · nits · DCI-P3 · Local Dimming\n"
    "    ถ้าจะพูดถึงของพวกนี้ ให้บอกว่า **มันทำให้คนใช้ได้อะไร** แทนการเอ่ยชื่อมัน\n"
    "      1ms GtG         → กดปุ๊บติดปั๊บ ภาพไม่ค้างไม่เบลอ\n"
    "      FreeSync/G-Sync → ภาพไม่ฉีกขาดตอนเกมมันส์ๆ\n"
    "      Precise Dimming → ฉากมืดดำสนิท ไม่เป็นสีเทาซีดๆ\n"
    "      QD-Mini LED     → ไฟจิ๋วนับพันดวง สีสดจัดจ้าน\n"
    "      600 nits        → สว่างจนเปิดกลางวันก็ยังเห็นชัด\n"
    "  · **ตัวเลขเก็บไว้ได้และควรเก็บ** (300Hz · 55 นิ้ว · 3 ปี) เพราะตัวเลขคือ\n"
    "    สิ่งที่ทำให้คนหยุดดู — แต่ต้องบอกด้วยว่าตัวเลขนั้นดียังไงในภาษาคน\n"
    "  · ลองอ่านออกเสียงดู ถ้าคนขายของหน้าร้านไม่พูดแบบนั้น แปลว่ายังไม่ผ่าน\n"
    "  · ห้ามข้ามข้อไหน แม้จะดูธรรมดา · ห้ามแต่งเพิ่มเองที่หน้านี้ไม่ได้เขียน\n"
    # เจ้าของสั่ง 28 ส.ค. 2569: "เอาด้วย เพราะเราโปรโมท สินค้า : ร้าน แบบ 1:1"
    # ของเดิมห้ามเรื่องประกันกับการจัดส่งทั้งหมด ซึ่งผิดกับวิธีทำงานจริง —
    # เราไม่ได้ขายแค่ของ แต่ขายร้านไปพร้อมกัน ความกล้าซื้อของคนดูมาจากสองอย่างนี้คู่กัน
    # ที่ยังห้ามคือของที่เป็น **ภาระของคนซื้อ** ไม่ใช่สิ่งที่เขาได้
    "  · **เอาได้และควรเอา**: ประกัน · เคลม · ส่งเร็ว · ร้านทางการ — "
    "เราโปรโมทสินค้าคู่กับร้านแบบ 1:1 ความน่าเชื่อถือของร้านคือเหตุผลที่คนกล้าซื้อ\n"
    "  · **ไม่เอา**: ลงทะเบียน · ใบกำกับภาษี · ทักแชทสอบถาม · กรอกข้อมูล — "
    "พวกนี้เป็นภาระของคนซื้อ ไม่ใช่สิ่งที่เขาได้\n\n"
    "ขั้นที่ 2 — จากรายการข้างบน เลือกมา {count} ข้อ ที่ทำให้คนดูคลิปสั้น "
    "**ว้าวที่สุด** (picked) พร้อมเหตุผลสั้นๆ ว่าทำไมถึงเลือกข้อนั้น (why)\n\n"
    "เกณฑ์คำว่า “ว้าว” เรียงตามความสำคัญ\n"
    "  1. ตัวเลขที่เกินความคาดหมาย จนคนอ่านแล้วต้องหยุด (เช่น 2,000 nits · 1,056 โซน)\n"
    "  2. **ถ่ายให้เห็นได้ในคลิป** — ของที่มองเห็นผลลัพธ์ ชนะของที่เป็นศัพท์เทคนิคล้วน\n"
    "  3. แก้ปัญหาที่คนซื้อของแบบนี้กังวลอยู่แล้วจริงๆ\n"
    "  4. เป็นของที่ยี่ห้ออื่นในราคาเดียวกันไม่ค่อยมี\n\n"
    "ข้อห้ามตอนเลือก\n"
    "  · ห้ามเลือกของที่ทุกยี่ห้อมีเหมือนกันจนไม่ตื่นเต้น\n"
    "  · {count} ข้อต้องมาจาก **คนละมุม** ห้ามซ้ำแนวกัน "
    "(เช่นทีวี: มุมภาพ · มุมเสียง · มุมการใช้งาน)\n"
    "  · เขียนแบบคนขายของพูดให้เพื่อนฟัง ไม่ใช่ลอกสเปกดิบมาวาง\n"
    "  · **ห้ามมีศัพท์เทคนิคหลุดมาในข้อที่เลือก** จำเป็นต้องพูดถึงจริงๆ ให้แปล\n"
    "    เป็นผลลัพธ์ที่คนเห็นภาพได้ก่อนเสมอ\n\n"
    "  · **ห้ามมีคำภาษาอังกฤษ** ยกเว้นชื่อรุ่นสินค้า — จุดเด่นพวกนี้จะถูกเอาไป\n"
    "    ให้เสียงอ่านออกเสียง ตัวอ่านเสียงไทยอ่านคำอังกฤษเพี้ยนแทบทุกครั้ง\n"
    "    ให้เขียนเป็นคำอ่านไทยแทน\n"
    '{{"features": ["..."], "picked": [{{"text": "...", "why": "..."}}]}}'
)


# ============================================================================
# ให้ Gemini คัดให้ก่อนคนตรวจ — **ดูทั้งรูปและรายละเอียดพร้อมกันในครั้งเดียว**
# ============================================================================
#
# ผู้ใช้สั่ง 27 ส.ค. 2026: *"ตรงตรวจชุดรูปสั่งให้เพิ่มขั้นตอน ส่งไปให้ Gemini
# ทั้งหมด ทั้งรูปและรายละเอียด … เพื่อให้ gemini ช่วยกรองก่อน และผมจะเข้าไป
# approve อีกที ขั้นตอน gemini นี้ให้ทำต่อเลยหลังจากได้รูปและรายละเอียด"*
#
# **ทำไมของเดิมไม่พอ** เดิมแยกเป็นสองงานที่ไม่รู้จักกัน
#
#   judge_images()      ดู**รูปอย่างเดียว** → เลือกรูป      (ไม่รู้ว่าสินค้ามีดีอะไร)
#   analyse_features()  อ่าน**ข้อความอย่างเดียว** → จุดเด่น  (ไม่รู้ว่ารูปมีอะไรให้ดู)
#
# ผลคือรูปที่เลือกกับจุดเด่นที่เขียน **ไม่เกี่ยวกันเลย** — คลิปจึงพูดถึงของที่
# คนดูไม่เห็น และฉากที่เห็นก็ไม่มีใครพูดถึง (เจอจริงหลายใบ)
#
# รวมเป็นครั้งเดียวแล้ว Gemini เห็นทั้งสองอย่างพร้อมกัน จึงจับคู่ได้ว่า
# **"จุดขายข้อนี้ ดูได้จากรูปใบนี้"** ซึ่งเป็นสิ่งเดียวที่ทำให้คลิปสั้นทำงาน
#
# ยังประหยัดโควตาด้วย — จาก 2 ครั้ง/สินค้า เหลือ 1 ครั้ง
# **ย่อหน้าเปิดมาจากเจ้าของโดยตรง (27 ส.ค. 2569) ห้ามแก้ถ้อยคำเอง**
# เขาเขียนมาให้ทั้งย่อหน้า — คำว่า "ไวรอล" · "100 ล้านวิว" · "3-5 ใบ" เป็นของเขา
# ที่เหลือข้างล่างเป็นวิธีคิดกับข้อห้ามที่เราเติมจากบทเรียนที่เจอมา
AD_CURATE_PROMPT = (
    "คุณเป็นผู้เชี่ยวชาญในด้านการทำคลิปรีวิวสินค้าให้ไวรอล "
    "และสามารถดึงจุดเด่นของสินค้าออกมาได้ดีที่สุด "
    "เพื่อที่จะนำไปทำคลิปวีดีโอโฆษณาให้ได้ยอดวิว 100 ล้านวิว\n\n"
    "ให้วิเคราะห์ pain point ว่าทำไมคนถึงต้องยอมมาซื้อสินค้าชิ้นนี้ "
    "มาเรียงตาม rating 1-10 แล้วนำ pain point มาเลือกจุดเด่น\n"
    "โดยให้เลือกรูปที่เป็นจุดเด่นมาแค่ 3-5 ใบ\n"
    "อธิบายจุดเด่นเป็นคำพูด 3-5 ข้อ ให้สอดคล้องตามจำนวนรูปที่เลือก\n"
    "ในกรณีที่ยังมีจุดเด่นไม่ถึง 3 ให้วนไปทำ pain point ใหม่\n\n"
    "─────────────────────────────\n"
    'สินค้า: "{name}"\n\n'
    "รายละเอียดจากหน้าขาย:\n{detail}\n"
    "─────────────────────────────\n\n"
    "รูปที่ส่งให้มี {count} ใบ กำกับหมายเลขตามลำดับที่ส่ง\n\n"
    # เจ้าของสั่งเพิ่ม 27 ส.ค. 2569: "ไม่เอารูปที่มีราคาสินค้า"
    #
    # เหตุผลที่ต้องห้ามให้ชัด: ราคาบนหน้า Shopee เปลี่ยนตลอด (โปรลด · โค้ดส่วนลด ·
    # ราคาตามขนาด) แต่คลิปที่เจนแล้วอยู่ถาวร พอราคาจริงไม่ตรงกับที่โชว์ในคลิป
    # ก็กลายเป็นโฆษณาเกินจริงซึ่งโดน Shopee หักคะแนน
    "**ห้ามเลือกรูปพวกนี้เด็ดขาด**\n"
    "• รูปที่มี**ราคาสินค้า**อยู่ในรูป ไม่ว่าจะเป็นตัวเลขบาท ป้ายลดราคา "
    "ราคาขีดฆ่า โค้ดส่วนลด หรือข้อความว่าลดกี่เปอร์เซ็นต์\n"
    "• ถ้ารูปที่ดีที่สุดติดราคามา ให้ข้ามไปเลือกใบถัดไปแทน "
    "อย่าเลือกมาแล้วบอกว่าให้ตัดราคาออกทีหลัง\n\n"
    "**วิธีคิด**\n"
    "1. อ่านรายละเอียดก่อน แล้วถามว่า **คนซื้อของแบบนี้กำลังเดือดร้อนเรื่องอะไร** "
    "ไล่ pain point ออกมาให้ครบ แล้วให้คะแนน 1-10 ว่าข้อไหนทำให้คนยอมควักเงินมากที่สุด "
    "(10 = เจ็บจนต้องซื้อวันนี้ · 1 = รู้สึกเฉยๆ)\n"
    "2. เรียง pain point จากคะแนนมากไปน้อย\n"
    "3. ไล่จุดขายของสินค้า แล้วจับคู่ว่า **จุดขายข้อไหนแก้ pain point ข้อไหน** "
    "จุดขายที่ไม่ได้แก้ pain point ข้อไหนเลย ให้ทิ้ง ต่อให้ฟังดูดีแค่ไหน\n"
    "4. ดูรูปทุกใบ แล้วจับคู่ว่าจุดขายข้อไหน **เห็นได้จากรูปใบไหน**\n"
    "5. เลือก 3-5 ใบ ไล่จาก pain point คะแนนสูงสุดลงมา "
    "โดยไม่เอารูปที่เล่าเรื่องเดียวกันซ้ำ\n"
    "6. **ถ้าได้ไม่ถึง 3 ใบ ให้กลับไปทำข้อ 1 ใหม่** มอง pain point จากมุมอื่น "
    "(เช่น ซื้อไปให้คนอื่น · ใช้ในสถานการณ์ที่ยังไม่ได้คิดถึง) แล้วไล่ลงมาอีกรอบ\n"
    "7. เขียนคำโฆษณาให้รูปละ 1 ข้อ ตรงกับสิ่งที่เห็นในรูปใบนั้น "
    "และตอบ pain point ที่จับคู่ไว้\n\n"
    "**คำโฆษณาต้องเป็นแบบนี้**\n"
    "• พูดเป็นภาษาคนซื้อ ไม่ใช่ภาษาสเปก — บอกว่า**ได้อะไร** ไม่ใช่บอกว่ามีอะไร\n"
    "• สั้น อ่านจบใน 1 ลมหายใจ (ไม่เกิน 18 คำ)\n"
    "• ห้ามอ้างสิ่งที่ไม่มีในรายละเอียด — อ้างเกินจริงโดน Shopee หัก 3 คะแนน\n"
    "• ห้ามพูดถึงยี่ห้ออื่นหรือแบรนด์ที่ไม่ใช่สินค้านี้\n"
    # เจ้าของสั่ง 28 ส.ค. 2569 — เขียนให้ชัดว่าเอาได้ ไม่งั้น AI เซ็นเซอร์ตัวเองทิ้ง
    "• **ความน่าเชื่อถือของร้านนับเป็นจุดขายได้** — ประกัน · เคลม · ส่งเร็ว · "
    "ร้านทางการ เพราะเราโปรโมทสินค้าคู่กับร้านแบบ 1:1 "
    "ถ้ามันตอบ pain point ข้อไหนอยู่ ให้ใช้ได้เลย\n\n"
    "ตอบเป็น JSON อย่างเดียว ห้ามมีข้อความอื่น\n"
    '{{"pains": [{{"pain": "ความเดือดร้อนของคนซื้อ", "rating": 9}}], '
    '"features": ["จุดขายทั้งหมดที่ไล่ได้"], '
    '"picked": [{{"image": 1, "text": "คำโฆษณา", "why": "เห็นอะไรในรูปนี้"}}]}}'
)

# ขอกี่ใบ — ผู้ใช้กำหนด 3-5 ใบ
AD_PICK_MIN, AD_PICK_MAX = 3, 5

# ---- สินค้าที่ปรับเปลี่ยนรูปทรงได้ ต้องได้รูปครบทุกท่า -------------------
#
# ย้ายมาจาก `clip_app.py` เมื่อ 28 ส.ค. 2569 เพื่อให้ **ส่งกติกานี้เข้าไปตั้งแต่
# รอบคัดรูปรอบแรก** ได้ ของเดิมอยู่ในสายคลิปซึ่งทำงานทีหลัง จึงต้องคัดรูปใหม่
# ทั้งชุดเพื่อบังคับกติกา แล้วทับชุดที่คัดมาพร้อมคำโฆษณาโดยไม่แก้คำโฆษณาตาม
TRANSFORM_RE = re.compile(
    r"ปรับ(?:ได้|เป็น|นั่ง|นอน|เอน|ระดับ|ท่า|มุม|องศา)"
    r"|ปรับเปลี่ยน|เปลี่ยนรูปทรง|แปลงร่าง|กางออก|ยืดได้"
    r"|ถอด\S{0,8}ได้|พับ\S{0,8}ได้|พับเก็บ|กาง\S{0,8}ได้"
    r"|นั่ง[–\-]นอน|นอน[–\-]นั่ง|\d+\s*in\s*1|2in1|3in1|multi[- ]?function",
    re.I,
)

TRANSFORM_RULE = (
    "**สินค้านี้ปรับเปลี่ยนรูปทรงได้** — ต้องเลือกรูปที่แสดง **ทุกท่า/ทุกสถานะ** "
    "อย่างน้อยท่าละ 1 รูป (เช่น ตอนเป็นโซฟา กับ ตอนกางเป็นเตียง / ตอนพับ กับ ตอนกาง) "
    "สำคัญกว่าการเลือกรูปสวย ถ้าต้องเลือกระหว่างรูปสวยท่าเดิม กับรูปธรรมดาท่าใหม่ "
    "ให้เอารูปท่าใหม่"
)


def transform_rule(*texts: str) -> str:
    """คืนกติกาเพิ่ม ถ้าข้อความบอกว่าสินค้าปรับเปลี่ยนรูปทรงได้ ไม่ใช่ก็คืนค่าว่าง"""
    return TRANSFORM_RULE if TRANSFORM_RE.search(" ".join(t or "" for t in texts)) else ""

# ส่งรูปให้ดูมากสุดกี่ใบ — ผู้ใช้สั่งว่า "ส่งไปให้ Gemini **ทั้งหมด**"
# จึงตั้งสูงกว่า `CANDIDATE_LIMIT` (12) ที่ใช้กับตัวเลือกรูปแบบเดิม
#
# ไม่ใช่ไม่จำกัด เพราะรูปถูกแปลงเป็นข้อความก่อนส่ง 20 ใบ ≈ 5-6 MB ต่อคำขอ
# ซึ่งยังไหว แต่ถ้าปล่อยไม่จำกัดแล้วเจอสินค้าที่มีรูป 60 ใบ จะหมดเวลาแน่นอน
# ใบที่เกินยังอยู่ในคลังให้ผู้ใช้เลือกเองได้อยู่ ไม่ได้หายไปไหน
AD_CURATE_MAX = 20


def curate_for_ad(
    name: str, detail: str, paths: list[str], api_key: str | None,
    log=print, model: str = "", extra_rule: str = "",
) -> dict:
    """คัดรูป + เขียนคำโฆษณาให้ในครั้งเดียว โดยดูทั้งรูปและรายละเอียดพร้อมกัน

    คืน `{"indexes": [...], "highlights": [...], "why": [...], "features": [...],
    "model": "ตัวที่ตอบจริง"}` โดย `indexes` เป็นลำดับใน `paths` (เริ่มที่ 0)
    และ `highlights[i]` คือคำโฆษณาของ `indexes[i]` — **เรียงตรงกันเสมอ**

    **ล้มแล้วโยน ไม่ถอยเงียบ** ผู้เรียกเป็นคนตัดสินว่าจะถอยไปทางไหน เพราะ
    ทางถอยของแต่ละที่ไม่เหมือนกัน และการถอยเงียบในนี้จะทำให้ไม่มีใครรู้ว่า
    ขั้นตอนที่ผู้ใช้สั่งให้เพิ่มนั้น **ไม่เคยทำงานเลย**
    """
    import base64

    import httpx

    if not paths:
        raise RuntimeError("ไม่มีรูปให้ดู")
    if not api_key:
        raise RuntimeError("ยังไม่ได้ใส่คีย์ Gemini")

    shots: list[dict] = []
    keep: list[int] = []            # ใบที่ส่งได้จริง ชี้กลับไปที่ paths เดิม
    for index, path in enumerate(paths[:AD_CURATE_MAX]):
        try:
            payload = Path(path).read_bytes()
        except OSError as error:
            log(f"  อ่านรูป {Path(path).name} ไม่ได้ ({error}) — ข้ามใบนี้")
            continue
        keep.append(index)
        shots.append({"inline_data": {
            "mime_type": "image/jpeg",
            "data": base64.b64encode(payload).decode("ascii"),
        }})
    if not shots:
        raise RuntimeError("เปิดไฟล์รูปไม่ได้สักใบ")

    # ตัดรายละเอียดไม่ให้คำขอบวมจนหมดเวลา — หัวเรื่องอยู่ต้นข้อความอยู่แล้ว
    body = (detail or "").strip()[:4000] or "(หน้าขายไม่มีคำบรรยาย)"
    instruction = AD_CURATE_PROMPT.format(
        name=name or "(ไม่ทราบชื่อ)", detail=body, count=len(shots))
    # กติกาเพิ่มเฉพาะกิจ เช่น "สินค้านี้ปรับท่าได้ ต้องได้รูปครบทุกท่า"
    #
    # **ต้องส่งเข้ามาตรงนี้ ไม่ใช่ไปคัดรูปใหม่ทีหลัง** (บทเรียน 28 ส.ค. 2569)
    # ของเดิมปล่อยให้ขั้นถัดไปคัดรูปใหม่เองเพื่อบังคับกติกานี้ ซึ่งทับชุดรูปที่
    # คัดมาพร้อมคำโฆษณาแล้ว **แต่ไม่ได้แก้คำโฆษณาตาม** จุดเด่นจึงไปบรรยายรูปที่
    # ถูกทิ้งไปแล้ว — เจ้าของเจอเองจากใบโซฟา `42653351351`
    if extra_rule:
        instruction += f"\n\n**กติกาเพิ่มสำหรับสินค้าชิ้นนี้**\n{extra_rule}\n"
    parts: list[dict] = [{"text": instruction}]
    for spot, shot in enumerate(shots, start=1):
        parts.append({"text": f"รูปที่ {spot}"})
        parts.append(shot)

    want = str(model or "").strip()
    if want and want not in IMAGE_HIGHLIGHT_CHOICES:
        log(f"ไม่รู้จักโมเดล {want} — ใช้สายพานอัตโนมัติแทน")
        want = ""
    chain = (want,) if want else tuple(IMAGE_JUDGE_MODELS)

    gemini_quota.check_budget("ให้ Gemini กรองชุดรูป")
    tried: list[str] = []
    for pick in chain:
        try:
            response = httpx.post(
                "https://generativelanguage.googleapis.com/v1beta/models/"
                f"{pick}:generateContent",
                params={"key": api_key},
                json={"contents": [{"parts": parts}],
                      "generationConfig": {"responseMimeType": "application/json"}},
                timeout=IMAGE_HIGHLIGHT_TIMEOUT,
            )
            gemini_quota.record(pick, ok=response.status_code == 200,
                                response=response)
            if response.status_code != 200:
                raise RuntimeError(f"{pick} ตอบ {response.status_code}")
            text = response.json()["candidates"][0]["content"]["parts"][0]["text"]
            found = re.search(r"\{.*\}", text, re.S)
            data = json.loads(found.group(0)) if found else {}

            rows = []
            for spot, item in enumerate(data.get("picked") or []):
                if not isinstance(item, dict):
                    continue
                line = str(item.get("text") or "").strip()
                if not line:
                    continue
                try:
                    shot = int(item.get("image"))
                except (TypeError, ValueError):
                    shot = len(shots) + spot + 1
                # หมายเลขที่มันตอบคือลำดับ**ที่ส่งให้** ต้องแปลงกลับเป็นลำดับใน paths
                if not 1 <= shot <= len(keep):
                    continue
                rows.append((shot, spot, keep[shot - 1], line,
                             str(item.get("why") or "").strip()))
            # เรียงตามเลขรูป ไม่ใช่ตามลำดับที่มันตอบ — ฉากในคลิปต้องไล่ตามลำดับรูป
            rows.sort(key=lambda row: (row[0], row[1]))

            indexes, highlights, why, seen = [], [], [], set()
            for _, _, real, line, reason in rows:
                if real in seen or line in highlights:
                    continue       # รูปซ้ำหรือคำซ้ำ = เสียฉากไปเปล่าๆ
                seen.add(real)
                indexes.append(real)
                highlights.append(line)
                why.append(reason)
            if len(indexes) < AD_PICK_MIN:
                raise RuntimeError(
                    f"{pick} เลือกมาแค่ {len(indexes)} ใบ (ขอไว้ {AD_PICK_MIN}-{AD_PICK_MAX})")
            indexes = indexes[:AD_PICK_MAX]
            highlights = highlights[:AD_PICK_MAX]
            why = why[:AD_PICK_MAX]

            features = [str(x).strip() for x in (data.get("features") or [])
                        if str(x).strip()]

            # ความเดือดร้อนของคนซื้อที่ AI ไล่ออกมา + คะแนน 1-10 (เจ้าของสั่ง 28 ส.ค. 2569)
            #
            # **ต้องเก็บไว้ ไม่ใช่ให้มันคิดในใจแล้วทิ้ง** — ถ้าไม่บังคับให้ตอบออกมา
            # ไม่มีทางรู้เลยว่ามันวิเคราะห์จริงหรือข้ามไปเลือกรูปตามเดิม แล้วขั้นตอน
            # ที่เจ้าของสั่งให้เพิ่มก็จะไม่เคยทำงานโดยไม่มีใครรู้ (บทเรียนเดียวกับ
            # ขั้นกรองชุดรูปที่เคยล้มเงียบ)
            pains = []
            for item in (data.get("pains") or []):
                if not isinstance(item, dict):
                    continue
                line = str(item.get("pain") or "").strip()
                if not line:
                    continue
                try:
                    score = int(item.get("rating"))
                except (TypeError, ValueError):
                    score = 0
                pains.append({"pain": line, "rating": max(0, min(10, score))})
            pains.sort(key=lambda row: -row["rating"])

            extra = "" if pick == chain[0] else f" [ตัวสำรอง {pick}]"
            log(f"Gemini กรองให้แล้ว — เลือกรูปที่ {[i + 1 for i in indexes]} "
                f"พร้อมคำโฆษณา {len(highlights)} ข้อ · ไล่จุดขายได้ {len(features)} ข้อ{extra}")
            if pains:
                top = " · ".join(f"{p['pain']} ({p['rating']}/10)" for p in pains[:3])
                log(f"  ความเดือดร้อนที่คนซื้ออยากแก้ {len(pains)} ข้อ — สูงสุด: {top}")
            else:
                # ไม่ล้ม แต่ต้องดัง — แปลว่าคำสั่งที่เจ้าของเพิ่มไม่ถูกทำตาม
                log("  ⚠️ ไม่ได้วิเคราะห์ความเดือดร้อนของคนซื้อมาให้ "
                    "(ขั้นตอนที่เจ้าของสั่งไว้อาจถูกข้าม)")
            return {"indexes": indexes, "highlights": highlights, "why": why,
                    "features": features, "pains": pains, "model": pick}
        except Exception as error:                           # noqa: BLE001
            tried.append(f"{pick}: {error}")
            log(f"  ให้ Gemini กรองด้วย {pick} ไม่สำเร็จ ({error})")
    raise RuntimeError("Gemini กรองชุดรูปไม่สำเร็จ — " + " · ".join(tried))


def analyse_features(name: str, detail: str, api_key: str | None, log=print,
                     count: int = HIGHLIGHT_COUNT) -> dict:
    """ไล่จุดขายออกมาให้ครบ แล้วเลือกข้อที่ว้าวสุดมา `count` ข้อ

    คืน {"features": [...ทั้งหมด...], "highlights": [...count ข้อ...], "why": [...]}
    ล้มเหลวคืน features ว่างและใช้กฎคัด highlights แทน

    **`count` เพิ่มมา 30 ส.ค. 2569 · ค่าปริยายเท่าเดิม สายโพสต์จึงไม่กระทบ**
    สายคลิปส่ง 4 เข้ามา เพราะคลิปมี 5 ฉาก โดย 4 ฉากเป็นจุดเด่นและฉากสุดท้าย
    เป็นประโยคปิดการขาย (เจ้าของสั่ง)
    """
    count = max(1, int(count))
    if not detail.strip():
        return {"features": [], "highlights": [], "why": []}
    if not api_key:
        log("ไม่มีคีย์ Gemini — คัดรายละเอียดเด่นด้วยกฎแทน")
        return {"features": [], "highlights": _fallback_highlights(detail), "why": []}

    import httpx

    instruction = ANALYSE_PROMPT.format(
        name=name, detail=detail[:6000], count=count,
    )
    last = ""
    for model in HIGHLIGHT_MODELS:
        try:
            response = httpx.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/"
                f"{model}:generateContent",
                params={"key": api_key},
                json={
                    "contents": [{"parts": [{"text": instruction}]}],
                    "generationConfig": {"responseMimeType": "application/json"},
                },
                timeout=90.0,
            )
            gemini_quota.record(model, ok=response.status_code == 200,
                                response=response)
            if response.status_code != 200:
                raise RuntimeError(f"{model} ตอบ {response.status_code}")
            text = response.json()["candidates"][0]["content"]["parts"][0]["text"]
            found = re.search(r"\{.*\}", text, re.S)
            data = json.loads(found.group(0)) if found else {}
            features = [str(x).strip() for x in (data.get("features") or []) if str(x).strip()]
            picked = data.get("picked") or []
            highlights = [str(p.get("text") or "").strip() for p in picked
                          if isinstance(p, dict) and str(p.get("text") or "").strip()]
            why = [str(p.get("why") or "").strip() for p in picked if isinstance(p, dict)]
            if not highlights:
                raise RuntimeError(f"{model} ไม่ได้เลือกจุดเด่นมาให้")
            if model != HIGHLIGHT_MODELS[0]:
                log(f"คัดจุดเด่นด้วยโมเดลสำรอง {model}")
            log(f"ไล่จุดขายได้ {len(features)} ข้อ → เลือกมา {len(highlights)} ข้อ")
            return {
                "features": features,
                "highlights": highlights[:count],
                "why": why[:count],
            }
        except Exception as error:                           # noqa: BLE001
            last = str(error)
            log(f"คัดจุดเด่นด้วย {model} ไม่สำเร็จ ({error})")
    log(f"ใช้กฎคัดจุดเด่นแทน (ล่าสุด: {last})")
    return {"features": [], "highlights": _fallback_highlights(detail), "why": []}


def extract_highlights(name: str, detail: str, api_key: str | None, log=print) -> list[str]:
    """คืนจุดขาย 3 ข้อสั้นๆ — ตัวห่อของ `analyse_features` ไว้ให้โค้ดเดิมเรียกได้เหมือนเดิม"""
    return analyse_features(name, detail, api_key, log=log)["highlights"]


# ------------------------------------------- คัดจุดเด่นจาก **รูปที่จะใช้จริง**

# โมเดลที่ใช้ดูรูปแล้วเขียนจุดเด่น — **เรียงตามที่วัดมาจริง ไม่ใช่ตามรุ่นใหม่เก่า**
#
# วัดเมื่อ 26 ส.ค. 2026 กับรูป 5 ใบของจอ TCL 27P2A (ยิงจริง 2 รอบ ผลเหมือนกันทั้งคู่)
#
#   gemini-3.7-flash   ❌ หมดเวลาที่ 180 วินาที **ทั้งสองรอบ** ไม่เคยตอบกลับเลย
#   gemini-3.5-flash   ✅ ตอบใน ~12 วินาที และผลอ้างอิงสิ่งที่อยู่ในรูปได้แม่น
#
# ตอนแรกตั้ง 3.7-flash ไว้ก่อนเพราะ "ไม่ซ้ำถังโควตากับใคร" ซึ่งเป็นเหตุผลของ
# ตัวคัดจากข้อความ **แต่ยกมาใช้กับงานรูปไม่ได้** งานรูปหนักกว่ามาก ผลคือทุกครั้ง
# ที่กดปุ่มต้องรอ 180 วินาทีให้ตัวแรกตายก่อน แล้วค่อยได้คำตอบจากตัวสำรองใน 12 วินาที
# = ผู้ใช้รอ 3 นาทีโดยไม่ได้อะไรเพิ่มเลย และ**ทางถอยกลบไว้จนแทบไม่มีใครรู้**
#
# 3.5-flash เป็นตัวเดียวกับที่ให้ Gemini เลือกรูปในไฟล์นี้ ซึ่งพิสูจน์แล้วว่ารับรูปได้จริง
# ยอมแชร์ถังโควตากับตัวเลือกรูป เพราะสองงานนี้ไม่ได้ทำพร้อมกัน (เลือกรูปตอนดึงสินค้า
# ส่วนตัวนี้ตอนผู้ใช้กดปุ่มเอง) และโมเดลที่ตอบได้จริงย่อมดีกว่าโมเดลที่ไม่เคยตอบ
#
# **ห้ามใช้รุ่น lite ในสายพานอัตโนมัติ** — รุ่นนั้นเอาไว้ฟังเสียงในตัวตรวจคลิป
# และไม่ได้ยืนยันว่าอ่านภาพอินโฟกราฟิกภาษาไทยได้ดีเท่ากัน
# (เลือกเองจากดรอปดาวน์ได้ แต่ต้องเป็นการตัดสินใจของคนที่เห็นผลลัพธ์ ไม่ใช่ของระบบ)
#
# ─── วัดซ้ำ 27 ส.ค. 2026 (รูปโซฟา 2 ใบของ 53565455104 ยิงจริงทุกตัว) ───
#
#   gemini-3.6-flash        ✅  3.7 วินาที
#   gemini-3.5-flash-lite   ✅  2.5 วินาที
#   gemini-3.1-flash-lite   ✅  1.7 วินาที
#   gemini-3-flash-preview  ✅  4.3 วินาที
#   gemini-2.5-flash        ✅  7.8 วินาที
#   gemini-3.5-flash        ❌  429 โควตาหมด (ชั้นฟรี 20 ครั้ง/วัน/โมเดล)
#   gemini-3.7-flash        ❌  503 ฝั่ง Google แน่นเอง (เสียเวลาไป 14.4 วินาที)
#   gemini-2.5-pro          ❌  404 เลิกให้บริการแล้ว
#
# **บทเรียนของวันนี้** สายพานเดิมมีแค่ 2 ตัวและวันนี้ตายพร้อมกันทั้งคู่ ปุ่มจึงล้ม
# ทุกครั้งที่กดโดยที่ไม่มีทางไปต่อเลย ทั้งที่ยังมีโมเดลที่ตอบได้อยู่ 5 ตัว
#
# **โควตาชั้นฟรีแยกถังรายโมเดล** (`GenerateRequestsPerDayPerProjectPerModel-FreeTier`
# = 20/วัน) ตัวหนึ่งหมดไม่ได้แปลว่าตัวอื่นหมด การมีหลายตัวในสายพานจึงไม่ใช่แค่
# กันเหตุ Google ล่ม แต่คือการเพิ่มเพดานที่กดได้ต่อวันจาก 20 เป็น 20×จำนวนตัว
#
# **เอา 3.7-flash ออกจากสายพานอัตโนมัติ** — ไม่เคยตอบงานรูปสำเร็จสักครั้งตั้งแต่
# 26 ส.ค. (หมดเวลา 180 วิ ×2 · วันนี้ 503) มีแต่ทำให้รอฟรี ยังเลือกเองได้จากเมนู
# ─── จัดใหม่ 27 ส.ค. 2026 หลังวัดกับสินค้าจริง 5 ชิ้น (รูป 9-20 ใบต่อชิ้น) ───
#
# วัดสองอย่าง ไม่ใช่แค่ความเร็ว — **จำนวนจุดขายที่ไล่ได้** สำคัญกว่า เพราะมันคือ
# คลังสำรองที่ผู้ใช้เอาไว้สลับตอนจุดเด่นข้อไหนไม่ถูกใจ (เจ้าของสั่งไว้ 22 ส.ค.)
#
#   โมเดล                  เวลาเฉลี่ย   จุดขายเฉลี่ย   ล้ม
#   gemini-3.5-flash         15.9 วิ      7.4 ข้อ      0/5   ← ตัวแรก
#   gemini-3.6-flash         16.6 วิ      7.0 ข้อ      1/4 (503)
#   gemini-3.1-flash-lite     6.5 วิ      5.8 ข้อ      0/5
#   gemini-2.5-flash         29.4 วิ      8.0 ข้อ      0/1
#   gemini-3-flash-preview   120+ วิ      หมดเวลา      1/1   ← ถอดออก
#   gemini-3.7-flash          75+ วิ      503          1/1   ← ถอดออก
#
# **ทำไมไม่เอา lite ขึ้นหัวแม้จะเร็วกว่า 2.5 เท่า** — มันไล่จุดขายได้น้อยกว่า 20%
# งานนี้ทำครั้งเดียวต่อสินค้า ไม่ได้วนถี่ 10 วินาทีที่ประหยัดได้ไม่คุ้มกับคลัง
# สำรองที่บางลง แต่เก็บไว้เป็นทางถอยชั้นท้าย เพราะพิสูจน์แล้วว่าใช้ได้จริง
# (กติกาเดิมในไฟล์นี้เขียนว่า "ห้ามใช้รุ่น lite กับงานรูป" เพราะยังไม่เคยวัด
#  ตอนนี้วัดแล้ว 5 ชิ้น — ใช้ได้ แค่ไล่จุดขายได้น้อยกว่า จึงลงไปอยู่ท้ายแถว)
#
# **ถอด 3-flash-preview ออกเพราะเป็นภาระ** — เดิมอยู่อันดับ 3 หมดเวลาที่ 120 วินาที
# แปลว่าถ้าสองตัวแรกล่ม ต้องรอฟรีอีก 2 นาทีก่อนจะถึงตัวที่ใช้ได้
IMAGE_HIGHLIGHT_MODELS = (
    "gemini-3.5-flash",         # 15.9 วิ · ไล่จุดขายได้ดีที่สุดและไม่เคยล้ม
    "gemini-3.6-flash",
    "gemini-2.5-flash",
    "gemini-3.1-flash-lite",    # ทางถอยที่เร็วมาก ยอมได้จุดขายน้อยลงดีกว่าไม่ได้เลย
)

# เมนูให้ผู้ใช้เลือกเองจากหน้าเว็บ (ผู้ใช้สั่ง 27 ส.ค. 2026 — "ด้านข้างในทำ
# drop down เลือกเปลี่ยน model ได้")
#
# **ทุกตัวในนี้ถูกยิงจริงด้วยรูปจริงมาแล้ว** ไม่ใช่รายชื่อที่คัดลอกมาจากเอกสาร
# ตัวที่วัดแล้วใช้ไม่ได้ (2.5-pro เลิกให้บริการ) ไม่อยู่ในเมนู เพราะตัวเลือกที่
# เลือกแล้วล้มแน่นอนคือกับดัก ไม่ใช่ทางเลือก
#
# `note` คือสิ่งที่วัดได้จริง ไม่ใช่คำโฆษณา — คนเลือกต้องเห็นว่าแลกอะไรกับอะไร
IMAGE_HIGHLIGHT_MENU = (
    {"id": "", "label": "อัตโนมัติ (แนะนำ)",
     "note": "ไล่ตามลำดับที่วัดว่าดีที่สุด ตัวไหนล่มข้ามให้เอง"},
    {"id": "gemini-3.6-flash", "label": "3.6 Flash",
     "note": "16.6 วิ · จุดขาย 7.0 ข้อ · เคย 503 ไป 1 ใน 4 ครั้ง"},
    {"id": "gemini-3.5-flash", "label": "3.5 Flash",
     "note": "15.9 วิ · จุดขาย 7.4 ข้อ · ไม่เคยล้ม — ตัวแรกของสายพาน"},
    {"id": "gemini-3-flash-preview", "label": "3 Flash (preview)",
     "note": "⚠️ หมดเวลาที่ 120 วินาทีกับงานรูป — ถอดออกจากสายพานแล้ว"},
    {"id": "gemini-2.5-flash", "label": "2.5 Flash",
     "note": "29.4 วิ · จุดขาย 8 ข้อ · ช้าแต่นิ่ง ไว้ใช้ตอนตัวอื่นล่ม"},
    {"id": "gemini-3.5-flash-lite", "label": "3.5 Flash Lite",
     "note": "4.3 วิ · เร็วมาก แต่ไล่จุดขายได้น้อยสุด (5 ข้อ)"},
    {"id": "gemini-3.1-flash-lite", "label": "3.1 Flash Lite",
     "note": "6.5 วิ · เร็วสุด จุดขาย 5.8 ข้อ · ทางถอยชั้นท้ายของสายพาน"},
    {"id": "gemini-3.7-flash", "label": "3.7 Flash",
     "note": "⚠️ ล้ม 68/68 ครั้งวันนี้ ทั้งงานรูปและข้อความ — เลือกได้แต่จะล้ม"},
)

# ชื่อโมเดลที่ยอมให้เลือกได้จริง — ฝั่งเซิร์ฟเวอร์ต้องตรวจก่อนยิง ไม่ใช่เชื่อ
# ค่าที่หน้าเว็บส่งมา (หน้าเว็บส่งชื่ออะไรมาก็ได้ แล้วจะกลายเป็นยิงมั่วไปที่ Google)
IMAGE_HIGHLIGHT_CHOICES = frozenset(
    row["id"] for row in IMAGE_HIGHLIGHT_MENU if row["id"]
)

# โมเดลที่ใช้ **เลือกรูป** — สายพานเดียวกับตัวคิดจุดเด่น เพราะเป็นงานดูรูปเหมือนกัน
# และวัดมาชุดเดียวกันแล้วว่าตัวไหนตอบได้จริง
#
# **ของเดิมฝังชื่อ `gemini-3.5-flash` ตายตัวไว้ในฟังก์ชัน** ผลคือวันที่ถังนั้นหมด
# (ชั้นฟรี 20 ครั้ง/วัน/โมเดล) ตัวเลือกรูปตายทั้งวันโดยไม่มีทางไป — เกิดจริง
# 27 ส.ค. 2026 เวลา 09:02:57 `Gemini ตอบ 429` แล้วถอยไปเลือกแบบกระจายทันที
# ทั้งที่ยังมีโมเดลอื่นที่ถังว่างอยู่อีก 3 ตัวในสายพานเดียวกันนี้
IMAGE_JUDGE_MODELS = IMAGE_HIGHLIGHT_MODELS

# รอต่อโมเดลนานสุดกี่วินาที — ตั้งจากของที่วัดได้ (ตัวที่ใช้ได้จริงตอบใน ~12 วินาที)
# เผื่อไว้เยอะแล้ว แต่ไม่เผื่อจนตัวที่ค้างลากผู้ใช้รอเป็นนาที
IMAGE_HIGHLIGHT_TIMEOUT = 120.0

# ส่งได้มากสุดกี่ใบต่อครั้ง — กันคำขอบวมจนหมดเวลาหรือโดนปฏิเสธ
# ชุดรูปที่ส่งเข้า GPT จริงมีเพดานอยู่แล้ว (CLIP_MAX_IMAGES) ตัวเลขนี้จึงเป็น
# ตาข่ายชั้นสองเผื่อมีใครเรียกตรงๆ ด้วยรายการยาวกว่านั้น
IMAGE_HIGHLIGHT_MAX = 8

IMAGE_ANALYSE_PROMPT = (
    'รูปพวกนี้คือ **ชุดรูปที่กำลังจะเอาไปทำคลิปสั้น** ของสินค้าชื่อ "{name}"\n'
    "ส่งมา {count} ใบ และ **รูปหนึ่งใบ = หนึ่งฉากในคลิป**\n\n"
    "ดูรูปทุกใบให้ครบก่อน แล้วทำสองขั้นตามลำดับ ตอบเป็น JSON อย่างเดียว "
    "  · ข้อละสั้นๆ **ไม่เกิน 30 ตัวอักษรไทย** — เป็นความยาวที่พูดทันจริง\n"
    "    ในหนึ่งฉาก (คลิป 10 วินาที พูดได้ราว 135 ตัวอักษร หาร 5 ฉาก)\n"
    "    ยาวกว่านี้จะโดนตัดกลางประโยคตอนเอาไปทำบทพูด\n"
    "  · **ภาษาพูดที่คนทั่วไปเข้าใจทันที**\n"
    "ขั้นที่ 1 — ไล่จุดขายที่ **เห็นได้จากรูปพวกนี้** ออกมาให้ครบทุกข้อ (features)\n"
    "  · อ่านตัวหนังสือบนรูปด้วย รูปสินค้าไทยมักเขียนสเปกไว้บนภาพ\n"
    "  · ข้อละสั้นๆ ไม่เกิน 60 ตัวอักษร **ภาษาพูดที่คนทั่วไปเข้าใจทันที**\n"
    "  · **ห้ามใช้ศัพท์เทคนิคลอยๆ** เช่น QD-MiniLED · Precise Dimming ·\n"
    "    FreeSync Premium · G-Sync · GtG · HDR · nits · DCI-P3 · Local Dimming\n"
    "    ถ้าจะพูดถึงของพวกนี้ ให้บอกว่า **มันทำให้คนใช้ได้อะไร** แทนการเอ่ยชื่อมัน\n"
    "      1ms GtG         → กดปุ๊บติดปั๊บ ภาพไม่ค้างไม่เบลอ\n"
    "      FreeSync/G-Sync → ภาพไม่ฉีกขาดตอนเกมมันส์ๆ\n"
    "      Precise Dimming → ฉากมืดดำสนิท ไม่เป็นสีเทาซีดๆ\n"
    "      QD-Mini LED     → ไฟจิ๋วนับพันดวง สีสดจัดจ้าน\n"
    "      600 nits        → สว่างจนเปิดกลางวันก็ยังเห็นชัด\n"
    "  · **ตัวเลขเก็บไว้ได้และควรเก็บ** (300Hz · 55 นิ้ว · 3 ปี) เพราะตัวเลขคือ\n"
    "    สิ่งที่ทำให้คนหยุดดู — แต่ต้องบอกด้วยว่าตัวเลขนั้นดียังไงในภาษาคน\n"
    "  · ลองอ่านออกเสียงดู ถ้าคนขายของหน้าร้านไม่พูดแบบนั้น แปลว่ายังไม่ผ่าน\n"
    "  · **ห้ามแต่งเพิ่มจากความรู้ทั่วไป** ถ้าไม่เห็นในรูปห้ามเขียน — "
    "จุดเด่นที่ไม่มีในรูปจะกลายเป็นคลิปที่พูดถึงของที่คนดูไม่เห็น\n"
    # เจ้าของสั่ง 28 ส.ค. 2569: "เอาด้วย เพราะเราโปรโมท สินค้า : ร้าน แบบ 1:1"
    # ของเดิมห้ามเรื่องประกันกับการจัดส่งทั้งหมด ซึ่งผิดกับวิธีทำงานจริง —
    # เราไม่ได้ขายแค่ของ แต่ขายร้านไปพร้อมกัน ความกล้าซื้อของคนดูมาจากสองอย่างนี้คู่กัน
    # ที่ยังห้ามคือของที่เป็น **ภาระของคนซื้อ** ไม่ใช่สิ่งที่เขาได้
    "  · **เอาได้และควรเอา**: ประกัน · เคลม · ส่งเร็ว · ร้านทางการ — "
    "เราโปรโมทสินค้าคู่กับร้านแบบ 1:1 ความน่าเชื่อถือของร้านคือเหตุผลที่คนกล้าซื้อ\n"
    "  · **ไม่เอา**: ลงทะเบียน · ใบกำกับภาษี · ทักแชทสอบถาม · กรอกข้อมูล — "
    "พวกนี้เป็นภาระของคนซื้อ ไม่ใช่สิ่งที่เขาได้\n\n"
    "ขั้นที่ 2 — เขียนจุดเด่น **ใบละหนึ่งข้อ ให้ครบทั้ง {count} ใบ** (picked)\n"
    "  · เรียงตามลำดับรูปที่ส่งมา และใส่เลขรูปกำกับไว้ในช่อง image\n"
    "  · แต่ละข้อต้องพูดถึง **สิ่งที่อยู่ในรูปใบนั้น** เพราะฉากนั้นจะตัดภาพใบนั้นให้ดู\n"
    "  · ใบไหนไม่มีอะไรเด่นเลย ให้หยิบสิ่งที่ดีที่สุดเท่าที่เห็นในใบนั้นมาเขียน "
    "**ห้ามข้ามใบ** และ**ห้ามหยิบของจากใบอื่นมาใส่**\n"
    "  · ใส่เหตุผลสั้นๆ ว่าทำไมข้อนั้นน่าสนใจ (why)\n\n"
    "เกณฑ์การเลือกของแต่ละใบ เรียงตามความสำคัญ\n"
    "  1. ตัวเลขที่เกินความคาดหมาย จนคนอ่านแล้วต้องหยุด\n"
    "  2. เห็นผลได้ด้วยตาในรูปใบนั้น ชนะศัพท์เทคนิคล้วน\n"
    "  3. แก้ปัญหาที่คนซื้อของแบบนี้กังวลอยู่แล้วจริงๆ\n"
    "  4. เป็นของที่ยี่ห้ออื่นในราคาเดียวกันไม่ค่อยมี\n\n"
    "ข้อห้าม\n"
    "  · ห้ามเขียนซ้ำแนวกันสองใบ ถ้าสองใบพูดเรื่องเดียวกัน "
    "ให้เจาะคนละแง่ (เช่นใบหนึ่งพูดตัวเลข อีกใบพูดว่าใช้แล้วได้อะไร)\n"
    "  · ห้ามเลือกของที่ทุกยี่ห้อมีเหมือนกันจนไม่ตื่นเต้น\n"
    "  · เขียนแบบคนขายของพูดให้เพื่อนฟัง ไม่ใช่ลอกสเปกดิบมาวาง\n"
    "  · **ห้ามมีศัพท์เทคนิคหลุดมาในข้อที่เลือก** จำเป็นต้องพูดถึงจริงๆ ให้แปล\n"
    "    เป็นผลลัพธ์ที่คนเห็นภาพได้ก่อนเสมอ\n\n"
    "  · **ห้ามมีคำภาษาอังกฤษ** ยกเว้นชื่อรุ่นสินค้า — จุดเด่นพวกนี้จะถูกเอาไป\n"
    "    ให้เสียงอ่านออกเสียง ตัวอ่านเสียงไทยอ่านคำอังกฤษเพี้ยนแทบทุกครั้ง\n"
    "    ให้เขียนเป็นคำอ่านไทยแทน\n"
    '{{"features": ["..."], '
    '"picked": [{{"image": 1, "text": "...", "why": "..."}}]}}'
)


def analyse_features_from_images(
    name: str, images, api_key: str | None, log=print, count: int = 0,
    model: str = "",
) -> dict:
    """คัดจุดเด่นจาก **รูปที่ผู้ใช้เลือกไว้จริง** ใบละหนึ่งข้อ (ผู้ใช้สั่ง 26 ส.ค. 2026)

    ต่างจาก `analyse_features` ตรงต้นทาง: ตัวนั้นอ่าน "ข้อความรายละเอียด" ที่เก็บไว้
    ตอนดึงสินค้า ส่วนตัวนี้ให้ Gemini **ดูรูปชุดที่กำลังจะเอาไปทำคลิป**

    ทำไมถึงต้องมีทั้งสองตัว — จุดเด่นที่ดีที่สุดคือข้อที่ **มีภาพรองรับ** พูดแล้ว
    ตัดภาพให้ดูได้ทันที ถ้าคัดจากข้อความล้วน จะได้ข้อที่หน้าเว็บเขียนไว้แต่ไม่มีรูป
    ประกอบ แล้วคลิปต้องพูดถึงของที่คนดูไม่เห็น

    **ได้จุดเด่นเท่ากับจำนวนรูป** (ผู้ใช้สั่งเพิ่ม 26 ส.ค. 2026: "ถ้าผมเลือกไว้ 5 รูป
    ให้เจนจุดเด่นเพิ่ม 5 อัน ตามจำนวนรูปเลย") เพราะรูปหนึ่งใบคือหนึ่งฉากในคลิป
    ฉากที่ไม่มีอะไรให้พูดคือฉากที่เสียเปล่า — `count=0` แปลว่าให้นับจากจำนวนรูปเอง
    ผู้เรียกใส่ตัวเลขมาเองได้ถ้ามีเพดานของตัวเอง (เช่นเพดานจุดเด่นของฝั่งคลิป)

    คืนรูปแบบเดียวกับ `analyse_features` เป๊ะ (`features` / `highlights` / `why`)
    เพื่อให้ `clip_store.save_features()` กินได้เลยโดยไม่ต้องแก้อะไร

    **ล้มแล้วโยน ไม่ถอยไปใช้กฎ** — ต่างจากตัวคัดจากข้อความโดยตั้งใจ เพราะตัวนี้
    ผู้ใช้กดสั่งเองและนั่งรอดูผลอยู่ การถอยไปคัดด้วยกฎเงียบๆ จะได้จุดเด่นที่ไม่ได้
    มาจากรูปเลย ทั้งที่ผู้ใช้กดปุ่มที่เขียนว่า "คิดจากรูป" — ผิดคำสัญญาแบบเงียบๆ

    **`model` = เลือกเอง แล้วใช้ตัวนั้นตัวเดียว ไม่มีทางถอย** (ผู้ใช้สั่ง 27 ส.ค. 2026)

    จงใจไม่ถอยไปตัวอื่น เพราะการเลือกเองแปลว่า "ฉันอยากได้ตัวนี้" ถ้าแอบเปลี่ยน
    ให้เวลาล้ม ผลที่ได้จะมาจากโมเดลที่ผู้ใช้ไม่ได้เลือก โดยที่หน้าเว็บยังโชว์ชื่อ
    ตัวที่เขาเลือกอยู่ — เป็นการโกหกแบบเงียบๆ ชนิดเดียวกับที่กติกาข้อ 2.3 ห้ามไว้
    ไม่ใส่มา = ใช้สายพานอัตโนมัติตามเดิม
    """
    import base64
    import mimetypes

    import httpx

    paths = [Path(p) for p in (images or [])][:IMAGE_HIGHLIGHT_MAX]
    if not paths:
        raise RuntimeError("ไม่มีรูปให้ดู — เลือกรูปอย่างน้อย 1 ใบก่อน")
    if not api_key:
        raise RuntimeError("ยังไม่ได้ใส่คีย์ Gemini — ตั้งค่าก่อนถึงจะให้ AI ดูรูปได้")

    # เตรียมรูปก่อน แล้วค่อยบอกจำนวนใน prompt — ต้องเป็นจำนวน **ใบที่ส่งได้จริง**
    # ไม่ใช่จำนวนที่ตั้งใจส่ง ไม่งั้นถ้ามีใบเปิดไม่ได้ จะไปสั่งให้เขียนเกินจำนวนรูป
    shots: list[dict] = []
    for path in paths:
        try:
            payload = path.read_bytes()
        except OSError as error:
            # ใบที่อ่านไม่ได้ให้ข้าม แต่ต้องบอก ไม่ใช่หายเงียบ — ผู้ใช้เลือกมา 5 ใบ
            # แล้วได้ผลจาก 3 ใบโดยไม่รู้ตัว จะงงว่าทำไมจุดเด่นไม่ตรงกับที่เห็น
            log(f"อ่านรูป {path.name} ไม่ได้ ({error}) — ข้ามใบนี้")
            continue
        shots.append({
            "inline_data": {
                "mime_type": mimetypes.guess_type(path.name)[0] or "image/jpeg",
                "data": base64.b64encode(payload).decode("ascii"),
            }
        })
    used = len(shots)
    if not used:
        raise RuntimeError("เปิดไฟล์รูปไม่ได้สักใบ")

    # ไม่ได้กำหนดมา = ใบละข้อ ตามที่ผู้ใช้สั่ง
    want = used if count <= 0 else max(1, min(int(count), used))
    parts: list[dict] = [{"text": IMAGE_ANALYSE_PROMPT.format(name=name, count=want)}]
    for index, shot in enumerate(shots, start=1):
        parts.append({"text": f"รูปที่ {index}"})
        parts.append(shot)

    # เลือกเอง = ตัวนั้นตัวเดียว · ไม่ได้เลือก = สายพานอัตโนมัติ
    want_model = str(model or "").strip()
    if want_model:
        if want_model not in IMAGE_HIGHLIGHT_CHOICES:
            raise RuntimeError(f"ไม่รู้จักโมเดล {want_model}")
        chain = (want_model,)
        log(f"ผู้ใช้เลือกโมเดล {want_model} เอง — ใช้ตัวนี้ตัวเดียว ไม่มีตัวสำรอง")
    else:
        chain = tuple(IMAGE_HIGHLIGHT_MODELS)

    # **จดทุกตัวที่ลอง ไม่ใช่จำแค่ตัวสุดท้าย** — ของเดิมรายงานแค่ error ตัวท้าย
    # ผู้ใช้จึงเห็นแค่ "gemini-3.7-flash ตอบ 503" ทั้งที่ตัวแรกล้มเพราะโควตาหมด
    # ซึ่งเป็นคนละเรื่องและแก้คนละแบบ (รอ vs เปลี่ยนโมเดล)
    gemini_quota.check_budget("คิดจุดเด่นจากรูป")
    tried: list[str] = []
    for pick in chain:
        try:
            response = httpx.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/"
                f"{pick}:generateContent",
                params={"key": api_key},
                json={
                    "contents": [{"parts": parts}],
                    "generationConfig": {"responseMimeType": "application/json"},
                },
                timeout=IMAGE_HIGHLIGHT_TIMEOUT,
            )
            gemini_quota.record(pick, ok=response.status_code == 200,
                                response=response)
            if response.status_code != 200:
                raise RuntimeError(f"{pick} ตอบ {response.status_code}")
            text = response.json()["candidates"][0]["content"]["parts"][0]["text"]
            found = re.search(r"\{.*\}", text, re.S)
            data = json.loads(found.group(0)) if found else {}
            features = [str(x).strip() for x in (data.get("features") or []) if str(x).strip()]

            # เรียงตามเลขรูปที่มันกำกับมา ไม่ใช่ตามลำดับที่มันตอบ — ฉากในคลิปต้อง
            # ไล่ตามลำดับรูป ถ้าสลับกัน ฉากที่ 1 จะพูดถึงของที่อยู่ในรูปใบท้ายๆ
            # ใบไหนไม่ได้กำกับเลขมา ให้ไปต่อท้าย ไม่ใช่ทิ้ง
            rows = []
            for spot, item in enumerate(data.get("picked") or []):
                if not isinstance(item, dict):
                    continue
                text = str(item.get("text") or "").strip()
                if not text:
                    continue
                try:
                    shot = int(item.get("image"))
                except (TypeError, ValueError):
                    shot = used + spot + 1
                rows.append((shot, spot, text, str(item.get("why") or "").strip()))
            rows.sort(key=lambda row: (row[0], row[1]))

            # ตัดข้อที่เขียนซ้ำคำต่อคำ — บันทึกจุดเด่นซ้ำกันสองข้อคือเสียฉากไปเปล่าๆ
            highlights, why, seen = [], [], set()
            for _, _, text, reason in rows:
                if text in seen:
                    continue
                seen.add(text)
                highlights.append(text)
                why.append(reason)
            if not highlights:
                raise RuntimeError(f"{pick} ไม่ได้เลือกจุดเด่นมาให้")
            if pick != chain[0]:
                log(f"คัดจุดเด่นจากรูปด้วยโมเดลสำรอง {pick}")
            short = f" (ขอไว้ {want} ข้อ ได้ไม่ครบ)" if len(highlights) < want else ""
            log(f"ดูรูป {used} ใบ → ไล่จุดขายได้ {len(features)} ข้อ "
                f"→ เขียนจุดเด่น {len(highlights[:want])} ข้อ{short} [{pick}]")
            return {
                "features": features,
                "highlights": highlights[:want],
                "why": why[:want],
                "images_seen": used,
                "wanted": want,
                # บอกกลับไปว่า **ตัวไหนตอบจริง** ไม่ใช่ตัวไหนถูกขอ — หน้าเว็บจะได้
                # โชว์ของจริง เวลาสายพานอัตโนมัติข้ามไปใช้ตัวสำรอง
                "model": pick,
            }
        except Exception as error:                           # noqa: BLE001
            tried.append(f"{pick}: {error}")
            log(f"คัดจุดเด่นจากรูปด้วย {pick} ไม่สำเร็จ ({error})")
    # **บอกทุกตัวที่ลอง** ผู้ใช้ต้องแยกออกว่า "ทั้งกลุ่มล่ม" (รอ) กับ "โควตาหมด"
    # (เปลี่ยนโมเดล) ซึ่งแก้คนละแบบ — ของเดิมบอกแค่ตัวสุดท้าย ทำให้ตัดสินใจผิด
    detail = " · ".join(tried) or "ไม่ได้ลองสักตัว"
    hint = ("" if want_model else
            " — ลองเลือกโมเดลอื่นจากช่องข้างปุ่มดู (โควตาชั้นฟรีแยกถังรายโมเดล)")
    raise RuntimeError(f"ให้ AI ดูรูปแล้วคิดจุดเด่นไม่สำเร็จ — {detail}{hint}")


def _extract_highlights_old(name: str, detail: str, api_key: str | None, log=print) -> list[str]:
    """ของเดิม — เก็บไว้เทียบผลเวลาไล่ว่าแบบใหม่ดีขึ้นจริงไหม ไม่ได้เรียกใช้แล้ว"""
    if not detail.strip():
        return []
    if not api_key:
        return _fallback_highlights(detail)

    import httpx

    instruction = (
        f"นี่คือรายละเอียดสินค้าจาก Shopee ชื่อ \"{name}\"\n\n"
        f"{detail[:6000]}\n\n"
        f"สรุปจุดขายที่เด่นที่สุด {HIGHLIGHT_COUNT} ข้อ สำหรับเอาไปพูดในคลิปโฆษณา "
        "ข้อละไม่เกิน 60 ตัวอักษร เป็นภาษาไทย เน้นสิ่งที่ลูกค้าได้รับ "
        "ประกันกับการจัดส่งเอาได้ (โปรโมทสินค้าคู่ร้าน 1:1) "
        "แต่ห้ามเอาเรื่องใบกำกับภาษีหรือการให้ลูกค้าไปกรอกข้อมูลมา "
        "ตอบเป็น JSON array ของสตริงล้วนๆ ไม่ต้องมีคำอธิบายอื่น"
    )
    last = ""
    for model in HIGHLIGHT_MODELS:
        try:
            response = httpx.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/"
                f"{model}:generateContent",
                params={"key": api_key},
                json={"contents": [{"parts": [{"text": instruction}]}]},
                timeout=60.0,
            )
            gemini_quota.record(model, ok=response.status_code == 200,
                                response=response)
            if response.status_code != 200:
                raise RuntimeError(f"{model} ตอบ {response.status_code}")
            text = response.json()["candidates"][0]["content"]["parts"][0]["text"]
            found = re.search(r"\[.*\]", text, re.S)
            items = json.loads(found.group(0)) if found else []
            clean = [str(item).strip() for item in items if str(item).strip()]
            if clean:
                if model != HIGHLIGHT_MODELS[0]:
                    log(f"คัดจุดเด่นด้วยโมเดลสำรอง {model}")
                return clean[:HIGHLIGHT_COUNT]
            raise RuntimeError(f"{model} ไม่ได้ตอบเป็นรายการ")
        except Exception as error:                           # noqa: BLE001
            last = str(error)
            log(f"คัดจุดเด่นด้วย {model} ไม่สำเร็จ ({error})")
    # คัดไม่ได้ต้องไม่ทำให้การดึงข้อมูลทั้งก้อนล้ม — ถอยไปใช้กฎ
    log(f"ใช้กฎคัดจุดเด่นแทน (ล่าสุด: {last})")
    return _fallback_highlights(detail)


IMAGE_GRAB_JS = r"""
async (urls) => {
  const out = [];
  for (const url of urls) {
    try {
      // credentials:'omit' — คลังรูปไม่ต้องใช้คุกกี้ และการไม่ส่งคุกกี้ข้ามโดเมน
      // คือสิ่งที่หน้าเว็บจริงทำอยู่แล้ว (แท็ก <img> ก็ไม่ส่ง)
      const r = await fetch(url, { credentials: 'omit' });
      if (!r.ok) { out.push({ url, error: 'HTTP ' + r.status }); continue; }
      const buf = new Uint8Array(await r.arrayBuffer());
      let s = '';
      const CH = 0x8000;      // แปลงทีละก้อน ไม่งั้น apply พังตอนไฟล์ใหญ่
      for (let i = 0; i < buf.length; i += CH) {
        s += String.fromCharCode.apply(null, buf.subarray(i, i + CH));
      }
      out.push({ url, b64: btoa(s), size: buf.length });
    } catch (e) {
      out.push({ url, error: String(e).slice(0, 120) });
    }
  }
  return out;
}
"""

# โหลดทีละกี่ใบต่อการคุยกับหน้าเว็บหนึ่งครั้ง — รูปถูกแปลงเป็นข้อความก่อนส่งกลับ
# ซึ่งทำให้ใหญ่ขึ้นราว 1.35 เท่า ก้อนละ 4 ใบ ≈ 2-3 MB กำลังดี ไม่บวมจนหน่วยความจำพุ่ง
IMAGE_GRAB_CHUNK = 4


def grab_images_with_browser(page, urls: list[str], target_dir: Path,
                             log=print) -> list[str]:
    """โหลดรูปด้วย **Chrome ตัวเดียวกับที่เพิ่งเปิดหน้าสินค้า** (ผู้ใช้สั่ง 27 ส.ค. 2026)

    **ทำไมถึงต้องเป็น Chrome ไม่ใช่ตัวโหลดของ Python**

    วิเคราะห์เหตุโดนบล็อกเมื่อคืน (01:22) พบว่าเราเปิดหน้าเว็บด้วย Chrome จริง
    แต่ **โหลดรูป 129 ใบใน 10 นาทีด้วยตัวโหลดของ Python** ซึ่งจากฝั่ง Shopee
    มองเห็นเป็นคนละโปรแกรมที่ยิงมาจากที่อยู่เดียวกัน ทั้งลายนิ้วมือการเชื่อมต่อ
    ไม่ตรง ไม่มีคุกกี้ ไม่มีหน้าอ้างอิง และแปะป้ายรุ่น Chrome ที่ห่างของจริง 25 รุ่น
    — เหมือนคนเดินเข้าร้านแล้วยื่นบัตรคนละใบตอนหยิบของ 129 ครั้งติด

    ให้หน้าเว็บโหลดเองแล้วได้ทุกอย่างถูกต้องโดยไม่ต้องปลอมสักอย่าง: ลายนิ้วมือ
    เดียวกับ Chrome จริง · หน้าอ้างอิงคือหน้าสินค้าที่เพิ่งเปิด · รุ่นตรงกันเสมอ

    **ทำได้เพราะคลังรูปเปิดให้ข้ามโดเมน** (`Access-Control-Allow-Origin: *`
    ยืนยันด้วยการยิงจริง 27 ส.ค. 2026) ถ้าวันหนึ่ง Shopee ปิดข้อนี้ ตัวนี้จะคืน
    รายการว่างแล้วผู้เรียกถอยไปใช้ `download_images()` ตามเดิม — ไม่ล้ม

    คืนรายชื่อไฟล์ที่บันทึกได้ **เรียงตามลำดับที่ขอ** เหมือน `download_images` เป๊ะ
    """
    import base64

    target_dir.mkdir(parents=True, exist_ok=True)
    saved: list[str] = []
    for start in range(0, len(urls), IMAGE_GRAB_CHUNK):
        chunk = urls[start:start + IMAGE_GRAB_CHUNK]
        try:
            rows = page.evaluate(IMAGE_GRAB_JS, chunk)
        except Exception as error:                           # noqa: BLE001
            # หน้าโดนเด้งกลางคัน = โหลดต่อไม่ได้ แต่ที่ได้มาแล้วยังใช้ได้
            log(f"  ให้หน้าเว็บโหลดรูปไม่สำเร็จ ({str(error)[:80]}) — "
                f"ได้มาแล้ว {len(saved)} ใบ")
            break
        for offset, row in enumerate(rows or []):
            index = start + offset + 1
            if row.get("error") or not row.get("b64"):
                log(f"  โหลดรูปที่ {index} ไม่สำเร็จ: {row.get('error') or 'ไม่มีข้อมูล'}")
                continue
            try:
                payload = base64.b64decode(row["b64"])
            except Exception:                                # noqa: BLE001
                log(f"  รูปที่ {index} แปลงกลับไม่ได้")
                continue
            if len(payload) < 2048:      # เล็กผิดปกติ = ไม่ใช่รูปสินค้าจริง
                continue
            path = target_dir / f"{index:02d}.jpg"
            path.write_bytes(payload)
            saved.append(str(path))
    return saved


def download_images(images: list[str], target_dir: Path, log=print) -> list[str]:
    """โหลดรูปเก็บไว้ในเครื่อง — **ทางถอย** ใช้เมื่อให้ Chrome โหลดเองไม่ได้

    ⚠️ ตัวนี้ยิงจากตัวโหลดของ Python ไม่ใช่จากเบราว์เซอร์ จึงเป็นร่องรอยที่ทำให้
    Shopee ตีตราว่าเป็นโปรแกรมไต่เว็บ (ดูเหตุผลเต็มที่ `grab_images_with_browser`)
    **ใช้เฉพาะตอนไม่มีหน้าเว็บให้ใช้แล้วเท่านั้น**
    """
    target_dir.mkdir(parents=True, exist_ok=True)
    saved: list[str] = []
    for index, url in enumerate(images, start=1):
        path = target_dir / f"{index:02d}.jpg"
        try:
            request = urllib.request.Request(url, headers=BROWSER_HEADERS)
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = response.read()
            if len(payload) < 2048:      # ไฟล์เล็กผิดปกติ = ไม่ใช่รูปสินค้าจริง
                continue
            path.write_bytes(payload)
            saved.append(str(path))
        except OSError as error:
            log(f"  โหลดรูปที่ {index} ไม่สำเร็จ: {error}")
    return saved
