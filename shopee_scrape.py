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
    """คืนข้อความด่านที่เจอ ถ้าผ่านแล้วคืนค่าว่าง"""
    body = page.evaluate("document.body.innerText.slice(0, 400)")
    found = GATE_PATTERNS.search(body)
    return found.group(0) if found else ""


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
                result = page.evaluate(API_FETCH_JS, [item_id, shop_id])
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
            data = page.evaluate(EXTRACT_JS)
        finally:
            browser.close()

    if not data.get("name") or "Hot Deals" in data["name"]:
        raise ShopeeError(
            "อ่านชื่อสินค้าไม่ได้ — Shopee อาจขึ้นหน้ายืนยันตัวตน "
            "ลองเปิดลิงก์ในเบราว์เซอร์ของโปรไฟล์นี้เองสักครั้งก่อน"
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


def extract_highlights(name: str, detail: str, api_key: str | None, log=print) -> list[str]:
    """คืนจุดขาย 3 ข้อสั้นๆ จากรายละเอียดยาวๆ"""
    if not detail.strip():
        return []
    if not api_key:
        log("ไม่มีคีย์ Gemini — คัดรายละเอียดเด่นด้วยกฎแทน")
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
    try:
        response = httpx.post(
            "https://generativelanguage.googleapis.com/v1beta/models/"
            "gemini-3.5-flash:generateContent",
            params={"key": api_key},
            json={"contents": [{"parts": [{"text": instruction}]}]},
            timeout=60.0,
        )
        if response.status_code != 200:
            raise RuntimeError(f"Gemini ตอบ {response.status_code}")
        text = response.json()["candidates"][0]["content"]["parts"][0]["text"]
        found = re.search(r"\[.*\]", text, re.S)
        items = json.loads(found.group(0)) if found else []
        clean = [str(item).strip() for item in items if str(item).strip()]
        if clean:
            return clean[:HIGHLIGHT_COUNT]
        raise RuntimeError("Gemini ไม่ได้ตอบเป็นรายการ")
    except Exception as error:
        # คัดไม่ได้ต้องไม่ทำให้การดึงข้อมูลทั้งก้อนล้ม — ถอยไปใช้กฎ
        log(f"คัดด้วย Gemini ไม่สำเร็จ ({error}) — ใช้กฎแทน")
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
