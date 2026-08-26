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

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
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
    """คลี่ลิงก์สั้น s.shopee.co.th ให้เป็นลิงก์สินค้าเต็ม"""
    clean = link.strip()
    if not PRODUCT_URL_RE.match(clean) and not SHORT_LINK_RE.match(clean):
        raise ShopeeError("ไม่ใช่ลิงก์ Shopee")
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


def scrape(link: str, open_browser, log=print, assisted: bool = True) -> dict:
    """ดึงข้อมูลสินค้า 1 ชิ้น — `open_browser` ฉีดเข้ามาเพื่อใช้โปรไฟล์เดียวกับตัวอื่น

    assisted=True เปิดหน้าต่างให้เห็น เพราะ Shopee ขึ้นแคปช่าเลื่อนจิ๊กซอว์กับ
    การเข้าแบบอัตโนมัติ ระบบจะ **รอให้ผู้ใช้เลื่อนเอง** แล้วค่อยอ่านข้อมูลต่อ
    (โปรแกรมนี้ไม่แก้แคปช่าให้ — ตั้งใจไม่ทำ)
    """
    from playwright.sync_api import sync_playwright

    full_url = resolve_link(link)
    shop_id, item_id = parse_ids(full_url)
    log(f"เปิดหน้าสินค้า ร้าน {shop_id} สินค้า {item_id}")

    with sync_playwright() as playwright:
        browser = open_browser(playwright, hidden=not assisted)
        page = browser.pages[0] if browser.pages else browser.new_page()
        try:
            # เปิดหน้าแรกก่อน ไม่ใช่หน้าสินค้า — หน้าแรกไม่ค่อยโดนด่านยืนยันตัวตน
            # แล้วค่อยยิง API จากตรงนั้น (same-origin คุกกี้ติดไปเอง)
            page.goto(SHOPEE_HOME, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT)
            time.sleep(2.0)
            if not _page_is_gated(page):
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
        finally:
            browser.close()

    if not data.get("name") or _looks_blocked(data["name"]):
        raise ShopeeError(
            f"Shopee ไม่ให้ข้อมูลสินค้า (หน้าที่ได้คือ \"{data.get('name') or 'หน้าว่าง'}\") "
            "— มักเป็นเพราะยิงถี่เกินไปจนโดนจำกัดการใช้งาน "
            "พักสัก 15-30 นาทีแล้วลองใหม่ · ดูภาพหน้าจอด้วย `python evidence.py`"
        )
    # ทางถอย (อ่าน DOM) แยกประเภทรูปไม่ได้ — ให้ใบแรกเป็นภาพรวม ที่เหลือเป็นแกลเลอรี
    images = [
        {"id": url.split("/")[-1], "url": url,
         "kind": "overview" if index == 0 else "gallery", "label": ""}
        for index, url in enumerate(data.get("images", [])[:MAX_IMAGES])
    ]
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
    "นี่คือรูปสินค้าจากหน้า Shopee เดียวกัน หมายเลขกำกับตามลำดับที่ส่งให้\n"
    "เลือกมา {count} รูปที่ **แตกต่างกันชัดเจน** เพื่อเอาไปทำคลิปโฆษณา\n"
    "เกณฑ์: ห้ามเลือกรูปที่หน้าตาเกือบเหมือนกัน · เอารูปที่เห็นตัวสินค้าชัด · "
    "เลี่ยงรูปที่มีตัวหนังสือเต็มภาพ · ถ้ามีภาพรวมที่มีพื้นหลังสวยให้เอามา 1 รูป\n"
    "ตอบเป็น JSON array ของหมายเลขล้วนๆ เช่น [1, 4, 7] ไม่ต้องอธิบาย"
)


def judge_images(
    paths: list[str], api_key: str | None, count: int = IMAGE_PICK_COUNT, log=print,
    extra_rule: str = "",
) -> list[int]:
    """ให้ Gemini เลือกว่ารูปไหนไม่ซ้ำกัน คืน index (เริ่มที่ 0) ของรูปที่เลือก

    `extra_rule` = เกณฑ์เพิ่มเฉพาะกิจ เช่นสินค้าที่ "ปรับเปลี่ยนรูปทรงได้"
    ต้องได้รูปทั้งก่อนและหลังปรับ ไม่ใช่ได้แต่ท่าเดียวสวยๆ หลายใบ
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
    try:
        response = httpx.post(
            "https://generativelanguage.googleapis.com/v1beta/models/"
            "gemini-3.5-flash:generateContent",
            params={"key": api_key},
            json={"contents": [{"parts": parts}]},
            timeout=120.0,
        )
        gemini_quota.record("gemini-3.5-flash", ok=response.status_code == 200,
                            response=response)
        if response.status_code != 200:
            raise RuntimeError(f"Gemini ตอบ {response.status_code}")
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
            log(f"Gemini เลือกรูปที่ {[i + 1 for i in unique]}")
            return unique
        raise RuntimeError("Gemini ไม่ได้ตอบเป็นเลขรูป")
    except Exception as error:
        log(f"ให้ Gemini เลือกรูปไม่สำเร็จ ({error}) — เลือกแบบกระจายแทน")
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
# ใครใช้อะไรอยู่ (22 ส.ค. 2026)
#   policy_fix   3.6-flash · 3.5-flash · 3-flash-preview
#   clip_check   3.1-flash-lite · 3.5-flash-lite · flash-lite-latest · 2.5-flash
#   hashtag      3.1-flash-lite-preview
#   ที่นี่        3.7-flash (ไม่ซ้ำใคร) แล้วค่อยถอยไป 3.5-flash-lite
# ตัวสำรองซ้ำกับ clip_check เพราะโมเดลที่เปิดให้ใช้ฟรีมีจำกัด — ยอมได้เพราะเป็น
# ทางถอยชั้นสอง ไม่ใช่ทางหลัก
HIGHLIGHT_MODELS = ("gemini-3.7-flash", "gemini-3.5-flash-lite")

# ข้อความที่ไม่ใช่จุดขาย — ตัดทิ้งก่อนคัด ไม่งั้นได้แต่เรื่องใบกำกับภาษี
BORING_RE = re.compile(
    r"ใบกำกับภาษี|ใบเสร็จ|กรอกข้อมูล|สอบถาม|ทักแชท|ช่องแชท|รบกวน|เงื่อนไข"
    r"|เปลี่ยนแปลง|แจ้งให้ทราบ|ขอสงวน|ร้านค้า|จัดส่ง|ขนส่ง",
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
    "  · ห้ามข้ามข้อไหน แม้จะดูธรรมดา · ห้ามแต่งเพิ่มเองที่หน้านี้ไม่ได้เขียน\n"
    "  · **ไม่เอา**: ประกัน · ลงทะเบียน · ใบกำกับภาษี · การจัดส่ง · เงื่อนไขร้าน\n\n"
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
    '{{"features": ["..."], "picked": [{{"text": "...", "why": "..."}}]}}'
)


def analyse_features(name: str, detail: str, api_key: str | None, log=print) -> dict:
    """ไล่จุดขายออกมาให้ครบ แล้วเลือก 3 ข้อที่ว้าวสุด

    คืน {"features": [...ทั้งหมด...], "highlights": [...3 ข้อ...], "why": [...]}
    ล้มเหลวคืน features ว่างและใช้กฎคัด highlights แทน
    """
    if not detail.strip():
        return {"features": [], "highlights": [], "why": []}
    if not api_key:
        log("ไม่มีคีย์ Gemini — คัดรายละเอียดเด่นด้วยกฎแทน")
        return {"features": [], "highlights": _fallback_highlights(detail), "why": []}

    import httpx

    instruction = ANALYSE_PROMPT.format(
        name=name, detail=detail[:6000], count=HIGHLIGHT_COUNT,
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
                "highlights": highlights[:HIGHLIGHT_COUNT],
                "why": why[:HIGHLIGHT_COUNT],
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
# **ห้ามใช้รุ่น lite** — รุ่นนั้นเอาไว้ฟังเสียงในตัวตรวจคลิป และไม่ได้ยืนยันว่า
# อ่านภาพอินโฟกราฟิกภาษาไทยได้ดีเท่ากัน
IMAGE_HIGHLIGHT_MODELS = ("gemini-3.5-flash", "gemini-3.7-flash")

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
    "ห้ามมีข้อความอื่น\n\n"
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
    "  · **ไม่เอา**: ประกัน · ลงทะเบียน · ใบกำกับภาษี · การจัดส่ง · เงื่อนไขร้าน\n\n"
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
    '{{"features": ["..."], '
    '"picked": [{{"image": 1, "text": "...", "why": "..."}}]}}'
)


def analyse_features_from_images(
    name: str, images, api_key: str | None, log=print, count: int = 0,
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

    last = ""
    for model in IMAGE_HIGHLIGHT_MODELS:
        try:
            response = httpx.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/"
                f"{model}:generateContent",
                params={"key": api_key},
                json={
                    "contents": [{"parts": parts}],
                    "generationConfig": {"responseMimeType": "application/json"},
                },
                timeout=IMAGE_HIGHLIGHT_TIMEOUT,
            )
            gemini_quota.record(model, ok=response.status_code == 200,
                                response=response)
            if response.status_code != 200:
                raise RuntimeError(f"{model} ตอบ {response.status_code}")
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
                raise RuntimeError(f"{model} ไม่ได้เลือกจุดเด่นมาให้")
            if model != IMAGE_HIGHLIGHT_MODELS[0]:
                log(f"คัดจุดเด่นจากรูปด้วยโมเดลสำรอง {model}")
            short = f" (ขอไว้ {want} ข้อ ได้ไม่ครบ)" if len(highlights) < want else ""
            log(f"ดูรูป {used} ใบ → ไล่จุดขายได้ {len(features)} ข้อ "
                f"→ เขียนจุดเด่น {len(highlights[:want])} ข้อ{short}")
            return {
                "features": features,
                "highlights": highlights[:want],
                "why": why[:want],
                "images_seen": used,
                "wanted": want,
            }
        except Exception as error:                           # noqa: BLE001
            last = str(error)
            log(f"คัดจุดเด่นจากรูปด้วย {model} ไม่สำเร็จ ({error})")
    raise RuntimeError(f"ให้ AI ดูรูปแล้วคิดจุดเด่นไม่สำเร็จ — {last}")


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
        "ห้ามเอาเรื่องใบกำกับภาษี การจัดส่ง หรือเงื่อนไขร้านมา "
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


def download_images(images: list[str], target_dir: Path, log=print) -> list[str]:
    """โหลดรูปเก็บไว้ในเครื่อง เพื่อส่งต่อให้ขั้นเจนรูปใช้เป็นภาพต้นฉบับ"""
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
