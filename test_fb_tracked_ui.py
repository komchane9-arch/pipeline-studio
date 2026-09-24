"""Isolated browser regression: no production API or Facebook access."""
import copy
import unittest
from pathlib import Path
from playwright.sync_api import sync_playwright, expect


class TrackedUItests(unittest.TestCase):
    def test_expand_stop_hidden_and_visible_without_losing_draft(self):
        posts = [{"post_url": f"https://www.facebook.com/groups/1/posts/{n}",
                  "account": "Preaw", "group_id": "1", "group_name": "กลุ่มทดสอบ",
                  "caption": f"โพสต์ทดสอบ {n}", "active": True,
                  "group_active_posts": 34, "pending": 1, "comments_list": [
                      {"comment_key": f"c{n}", "author": "Alice", "body": "สนใจ",
                       "reply_draft": "", "is_ours": False}]} for n in range(34)]
        stopped = set()
        safety_hold = False
        with sync_playwright() as pw:
            browser = pw.chromium.launch(channel="chrome", headless=True)
            page = browser.new_page(viewport={"width": 1100, "height": 900})

            def respond(route):
                path = route.request.url.split("studio.test", 1)[1].split("?", 1)[0]
                if path == "/":
                    route.fulfill(content_type="text/html", body='<link rel="stylesheet" href="/styles.css"><div id="egNote"></div><div id="egTimer"></div><div id="egList"></div>')
                elif path == "/api/fb/engage/threads":
                    visible = [copy.deepcopy(p) for p in posts[:7] if p["post_url"] not in stopped]
                    for p in visible:
                        p["group_active_posts"] = 34-len(stopped)
                    route.fulfill(json={"posts": visible, "account": "Preaw",
                        "reply_schedule": ({"waiting": True, "reason": "safety_hold",
                                            "note": "Facebook จำกัดการแสดงความคิดเห็นชั่วคราว"}
                                           if safety_hold else {})})
                elif path == "/api/fb/engage/tracked":
                    route.fulfill(json={"posts": [p for p in posts if p["post_url"] not in stopped]})
                elif path == "/api/fb/engage/watch":
                    url = route.request.post_data_json["post_url"]
                    stopped.add(url)
                    route.fulfill(json={"post_url": url, "active": False})
                elif path == "/core.js":
                    route.fulfill(content_type="text/javascript", body='export async function api(url, options={}) { const r=await fetch(url, options); if(!r.ok) throw new Error("failed"); return r.json(); }')
                elif path == "/gfaccount.js":
                    route.fulfill(content_type="text/javascript", body='export const gfQuery = path => path; export const gfAccount = () => "Preaw";')
                elif path in ("/engage.js", "/styles.css"):
                    route.fulfill(path=str(Path("web") / path[1:]))
                else:
                    route.abort()

            page.route("**/*", respond)
            page.goto("http://studio.test/")
            page.evaluate("async () => { window.engage = await import('/engage.js'); await engage.loadEngage(); }")
            # ใบงานที่มีคอมเมนต์ค้างเปิดกลุ่มและโพสต์ให้ทันที.
            expect(page.locator(".eg-post")).to_have_count(7)
            page.locator(".eg-group .eg-g-active[type=button]").click()
            expect(page.locator(".eg-tracked-row")).to_have_count(34)
            expect(page.locator(".eg-tracked-link").first).to_have_attribute("href", posts[0]["post_url"])
            draft = page.locator(".eg-post").nth(1).locator("textarea").first
            draft.fill("คำตอบที่ยังไม่บันทึก")
            page.locator(".eg-tracked-row").nth(33).locator(".eg-watch-stop").click()
            expect(page.locator(".eg-tracked-row")).to_have_count(33)
            expect(page.locator(".eg-group .eg-g-active[type=button]")).to_have_text("กำลังตามเก็บ 33 โพสต์")
            expect(page.locator(".eg-post")).to_have_count(7)
            expect(draft).to_have_value("คำตอบที่ยังไม่บันทึก")
            page.locator(".eg-tracked-row").first.locator(".eg-watch-stop").click()
            expect(page.locator(".eg-post")).to_have_count(6)
            expect(page.locator(".eg-tracked-row")).to_have_count(32)
            expect(page.locator(".eg-group .eg-g-active[type=button]")).to_have_text("กำลังตามเก็บ 32 โพสต์")
            expect(page.locator(".eg-group .eg-g-shown")).to_have_text("แสดง 6 โพสต์")
            # Collector refresh preserves both the expanded catalog and drafts.
            page.evaluate("() => engage.loadEngage({preserveInputs:true})")
            expect(page.locator(".eg-tracked-row")).to_have_count(32)
            expect(page.locator("textarea").first).to_have_value("คำตอบที่ยังไม่บันทึก")
            page.locator(".eg-group .eg-g-active[type=button]").click()
            expect(page.locator(".eg-tracked-list")).to_be_hidden()
            posts[1]['comments_list'][0].update(reply_error='เปิดโพสต์ไม่ได้')
            page.evaluate("() => engage.loadEngage()")
            expect(page.locator('#egTimer')).to_contain_text('ยังไม่สำเร็จ 1')
            expect(page.locator('#egTimer')).not_to_contain_text('ตรวจผลเท่านั้น ห้ามส่งซ้ำ')
            safety_hold = True
            page.evaluate("() => engage.loadEngage()")
            expect(page.locator('#egTimer')).to_contain_text('Facebook จำกัดการแสดงความคิดเห็นชั่วคราว')
            expect(page.locator('#egTimer')).to_contain_text('ไม่ใช่เวลาที่ Facebook รับรองว่าจะปลด')
            expect(page.locator('#egTimer button')).to_have_count(0)
            browser.close()


if __name__ == "__main__":
    unittest.main()
