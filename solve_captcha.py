"""เปิดหน้า Shopee ด้วยโปรไฟล์เดียวกับที่ระบบใช้ ให้ผู้ใช้เลื่อนจิ๊กซอว์เอง

**ทำไมต้องเป็นโปรไฟล์เดียวกัน** — CAPTCHA ผูกกับคุกกี้ของเบราว์เซอร์ตัวที่โดน
ถ้าผู้ใช้ไปแก้ในเบราว์เซอร์ตัวเอง **ไม่มีผลกับตัวที่ระบบใช้เลย** เดี๋ยวก็ติดซ้ำ
ไฟล์นี้จึงเปิดด้วย `flow_worker.open_browser()` ตัวเดียวกับที่ตัวดึงสินค้าใช้

**ทำไมแยกเป็นไฟล์** — ต้องเปิดค้างไว้ให้คนนั่งเลื่อนจิ๊กซอว์ ซึ่งกินเวลาเป็นนาที
ถ้าไปเปิดในโปรเซสของเซิร์ฟเวอร์จะไปยึดล็อกเบราว์เซอร์ที่คิวต้องใช้

    python solve_captcha.py                    เปิดหน้าแรก Shopee
    python solve_captcha.py <ลิงก์สินค้า>       เปิดลิงก์ที่ติด
    python solve_captcha.py --wait 600         รอนานขึ้น (ปกติ 300 วิ)

เลื่อนจิ๊กซอว์เสร็จแล้วหน้าต่างจะปิดเองเมื่อผ่านด่าน แล้วค่อยกดยืนยันในแชท
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

HOME = "https://shopee.co.th/"
CHECK_EVERY = 3.0


def _say(message: str) -> None:
    try:
        print(message, flush=True)
    except UnicodeEncodeError:
        sys.stdout.buffer.write((message + "\n").encode("utf-8", "replace"))


def _ids_of(shopee_scrape, url: str) -> tuple[str, str]:
    """อ่านรหัสร้าน/สินค้าจาก URL — **ห้ามโยน exception**

    `parse_ids` ของเดิมโยน error เมื่ออ่านไม่ได้ ซึ่งถูกต้องสำหรับตัวดึงข้อมูล
    แต่ที่นี่ URL เป็นหน้า CAPTCHA ได้ตลอดเวลา (อ่านรหัสไม่ได้เป็นเรื่องปกติ)
    ปล่อยให้โยนทำให้ลูปรอผู้ใช้ตายกลางคัน แล้วหน้าต่างปิดใส่หน้าคนที่กำลังแก้อยู่
    — เกิดจริง 25 ส.ค. 2026
    """
    try:
        return shopee_scrape.parse_ids(url)
    except Exception:
        return "", ""


def _place_on_main_screen(page, say) -> None:
    """ย้ายหน้าต่างมาที่ **จอหลัก** แล้วดันขึ้นหน้าสุด

    เครื่องนี้มี 6 จอ — Chrome เปิดที่จอไหนก็ได้ตามที่มันจำไว้ครั้งก่อน
    ผลคือหน้าต่างไปโผล่จอที่ผู้ใช้ไม่ได้มอง แล้วนั่งรอเก้อว่า "ไม่เห็นเด้งมา"
    (เกิดจริง 25 ส.ค. 2026 — ผู้ใช้รอหน้าต่างที่เปิดอยู่คนละจอ)

    ใช้ CDP `Browser.setWindowBounds` เพราะ Playwright ไม่มี API ย้ายหน้าต่าง
    ล้มก็ไม่เป็นไร แค่หน้าต่างอยู่ที่เดิม ไม่ทำให้งานพัง
    """
    try:
        session = page.context.new_cdp_session(page)
        window = session.send("Browser.getWindowForTarget")
        session.send("Browser.setWindowBounds", {
            "windowId": window["windowId"],
            "bounds": {"left": 40, "top": 40, "width": 1200, "height": 900,
                       "windowState": "normal"},
        })
        say("   (ย้ายหน้าต่างมาที่จอหลักแล้ว — มุมซ้ายบน)")
    except Exception as error:
        say(f"   (ย้ายหน้าต่างไม่ได้: {type(error).__name__} — หาที่จออื่นด้วยนะครับ)")
    try:
        page.bring_to_front()
    except Exception:
        pass


def _really_passed(page, shopee_scrape, say, want: tuple[str, str] = ("", "")) -> bool:
    """ผ่านด่านจริงหรือยัง — **ต้องพิสูจน์ด้วยผลลัพธ์ ไม่ใช่แค่ "ไม่เห็นคำว่าด่าน"**

    ของเดิมเช็คแค่ว่าข้อความบนหน้าตอนนี้มีคำว่าด่านไหม ซึ่ง **ตอบว่าผ่านได้ทั้งที่
    หน้าถูกเปลี่ยนไปที่อื่นแล้ว** — 25 ส.ค. 2026 รายงานว่า "ผ่านด่านแล้ว"
    ทั้งที่ผู้ใช้ยังไม่ได้แตะอะไรเลย เพราะหน้าต่างไปโผล่หน้า Pipeline Studio
    (กติกา CLAUDE.md ข้อ 2.3 — ตัวตรวจที่บอกว่าผ่านทั้งที่ยังไม่ผ่าน
    อันตรายกว่าไม่มีตัวตรวจ)

    ผ่านจริง = ยังอยู่บนหน้า Shopee **และ** ถามข้อมูลสินค้าแล้วได้ชื่อจริงกลับมา
    """
    try:
        here = page.url or ""
    except Exception:
        return False
    if "shopee." not in here:
        say("   ⚠️ หน้าถูกเปลี่ยนไปที่อื่นแล้ว — ยังไม่นับว่าผ่าน")
        return False
    if shopee_scrape._page_is_gated(page):
        return False
    shop_id, item_id = _ids_of(shopee_scrape, here)
    if not item_id:
        shop_id, item_id = want          # หน้ายังเป็น CAPTCHA — ใช้รหัสที่จำไว้ตอนแรก
    if not item_id:
        return False
    try:
        result = page.evaluate(shopee_scrape.API_FETCH_JS, [item_id, shop_id])
    except Exception:
        return False
    name = (result or {}).get("name") or ""
    return bool(name) and not shopee_scrape._looks_blocked(name)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="เปิดหน้า Shopee ให้เลื่อนจิ๊กซอว์เอง")
    parser.add_argument("link", nargs="?", default=HOME)
    parser.add_argument("--wait", type=float, default=300.0, help="รอกี่วินาที")
    args = parser.parse_args(argv)

    import shopee_scrape
    from flow_worker import open_browser
    from playwright.sync_api import sync_playwright

    _say("กำลังเปิด Chrome ด้วยโปรไฟล์เดียวกับที่ระบบใช้…")
    with sync_playwright() as playwright:
        browser = open_browser(playwright, hidden=False)   # ต้องเห็นหน้าต่าง
        try:
            page = browser.pages[0] if browser.pages else browser.new_page()
            page.goto(args.link, wait_until="domcontentloaded", timeout=90_000)
            time.sleep(2.0)
            # จำรหัสสินค้าไว้ตั้งแต่ยังอยู่หน้าจริง — พอเด้งไปหน้า CAPTCHA
            # จะอ่านรหัสจาก URL ไม่ได้อีก
            want_ids = _ids_of(shopee_scrape, page.url)
            _place_on_main_screen(page, _say)

            gate = shopee_scrape._page_is_gated(page)
            if not gate:
                # เปิดหน้าเฉยๆ ไม่ติดด่าน — ตัวที่ทำให้ติดคือ **การถามข้อมูลทางลัด**
                # (Shopee ตีตราเป็น scene=crawler_item) ต้องยิงให้ติดจริงก่อน
                # ผู้ใช้ถึงจะได้เห็นจิ๊กซอว์และแก้ให้คุกกี้ผ่านด่านได้
                _say("เปิดหน้าได้ปกติ — ลองถามข้อมูลแบบเดียวกับที่ระบบใช้ เพื่อให้ด่านโผล่…")
                try:
                    shop_id, item_id = _ids_of(shopee_scrape, page.url)
                except Exception:
                    shop_id = item_id = ""
                if item_id:
                    try:
                        page.evaluate(shopee_scrape.API_FETCH_JS, [item_id, shop_id])
                    except Exception as error:
                        _say(f"   (ถูกเด้งตามคาด: {str(error)[:60]})")
                    time.sleep(3.0)
                gate = shopee_scrape._page_is_gated(page)
            # **ตัดสินด้วยผลจริง ไม่ใช่แค่ "ไม่เห็นคำว่าด่านบนหน้า"**
            # 25 ส.ค. 2026 หน้าไม่มีคำว่าด่าน แต่ถามข้อมูลแล้วได้ชื่อว่าง = ยังโดนบล็อก
            if not gate and _really_passed(page, shopee_scrape, _say, want_ids):
                _say("✅ ใช้งานได้ปกติ — ถามข้อมูลได้ชื่อสินค้าจริง ไม่ต้องแก้อะไร")
                time.sleep(3)
                return 0

            _say(f"⛔ ติดด่าน: {gate or 'ถามข้อมูลไม่ได้ (ได้ชื่อว่าง)'}")
            _say("   ถ้าไม่เห็นจิ๊กซอว์ ให้กดปุ่ม Try Again บนหน้านั้นก่อน")
            _say("")
            _say("   👉 เลื่อนจิ๊กซอว์ในหน้าต่างที่เพิ่งเปิด")
            _say(f"   รอให้ {args.wait:.0f} วินาที · ผ่านแล้วจะบอกเอง")
            _say("")
            deadline = time.time() + args.wait
            while time.time() < deadline:
                time.sleep(CHECK_EVERY)
                if not _really_passed(page, shopee_scrape, _say, want_ids):
                    left = int(deadline - time.time())
                    if left % 30 < CHECK_EVERY:
                        _say(f"   ยังติดอยู่ — เหลือเวลาอีก {left} วินาที")
                    continue
                _say("")
                _say("✅ ผ่านด่านจริงแล้ว — ถามข้อมูลสินค้าได้ชื่อกลับมาถูกต้อง")
                _say("   คุกกี้ถูกเก็บไว้ในโปรไฟล์เรียบร้อย")
                _say("   กดปุ่ม ✅ ในแชท Telegram เพื่อให้ระบบทำงานต่อได้เลย")
                time.sleep(2)
                return 0
            _say("⏳ หมดเวลารอ — ยังไม่ผ่านด่าน สั่งใหม่ได้ด้วยคำสั่งเดิม")
            return 1
        finally:
            try:
                browser.close()
            except Exception:
                pass


if __name__ == "__main__":
    raise SystemExit(main())
