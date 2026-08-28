"""ตรวจว่าโปรไฟล์ที่ระบบใช้ ยิงถามข้อมูล Shopee ได้จริงหรือยัง

**ทำไมต้องมี** — ตัวเช็ค "ผ่านด่านหรือยัง" ของเดิมดูแค่ว่า *หน้าที่เปิดอยู่ตอนนี้
ไม่ใช่หน้าด่าน* ซึ่งตอบว่า "ผ่าน" ได้ทั้งที่หน้าถูกเปลี่ยนไปที่อื่นแล้ว
(25 ส.ค. 2026 รายงานว่าผ่านด่าน ทั้งที่หน้าต่างไปโผล่หน้า Pipeline Studio)

ไฟล์นี้ตรวจของจริง: **ยิงถามข้อมูลสินค้าแบบเดียวกับที่ตัวดึงใช้** แล้วดูว่าได้ชื่อ
สินค้ากลับมาไหม — ได้ชื่อจริง = ใช้งานได้ · ไม่ได้ = ยังโดนบล็อกอยู่

    python check_shopee.py <ลิงก์สินค้า>
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))


def _say(message: str) -> None:
    try:
        print(message, flush=True)
    except UnicodeEncodeError:
        sys.stdout.buffer.write((message + "\n").encode("utf-8", "replace"))


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    link = argv[0] if argv else "https://s.shopee.co.th/7Ad1yg2zAT"

    import shopee_scrape
    from flow_worker import open_browser
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = open_browser(playwright, hidden=True)   # ไม่ต้องโชว์ แค่ตรวจ
        try:
            page = browser.new_page()                     # หน้าใหม่เสมอ ไม่ใช้แท็บเก่า
            page.goto(link, wait_until="domcontentloaded", timeout=90_000)
            time.sleep(2.5)
            here = page.url
            _say(f"หน้าที่ไปถึง : {here[:90]}")
            if "shopee." not in here:
                _say("❌ ไม่ได้อยู่บนหน้า Shopee — ตรวจไม่ได้")
                return 2

            gate = shopee_scrape._page_is_gated(page)
            _say(f"ด่านบนหน้า   : {gate or 'ไม่มี'}")

            try:
                shop_id, item_id = shopee_scrape.parse_ids(page.url)
            except Exception:
                shop_id = item_id = ""
            if not item_id:
                _say("❌ อ่านรหัสสินค้าจากลิงก์ไม่ได้")
                return 2
            _say(f"รหัสสินค้า   : shop {shop_id} · item {item_id}")

            try:
                result = page.evaluate(shopee_scrape.API_FETCH_JS, [item_id, shop_id])
            except Exception as error:
                _say(f"❌ ยังโดนบล็อก — ถามข้อมูลแล้วโดนเด้ง ({str(error)[:70]})")
                return 1

            name = (result or {}).get("name") or ""
            if not name or shopee_scrape._looks_blocked(name):
                _say(f"❌ ยังโดนบล็อก — ได้ชื่อกลับมาเป็น “{name or 'ว่าง'}”")
                return 1
            _say(f"✅ ใช้งานได้แล้ว — ได้ชื่อสินค้าจริง: {name[:60]}")
            _say(f"   รูปที่เจอ {len((result or {}).get('images') or [])} ใบ")
            return 0
        finally:
            try:
                browser.close()
            except Exception:
                pass


if __name__ == "__main__":
    raise SystemExit(main())
