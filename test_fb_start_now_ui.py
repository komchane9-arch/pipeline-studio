"""The Start Now button immediately replaces stale cooldown UI after success."""
import unittest
from pathlib import Path

from playwright.sync_api import expect, sync_playwright


class StartNowUI(unittest.TestCase):
    def test_success_updates_local_priority_and_removes_button(self):
        calls = {"start": 0}
        account = "Khao Fang Nichapa"
        with sync_playwright() as pw:
            browser = pw.chromium.launch(channel="chrome", headless=True)
            page = browser.new_page()

            def handle(route):
                path = route.request.url.split("studio.test", 1)[1].split("?", 1)[0]
                if path == "/":
                    ids = ["egNote", "egTimer", "egList", "egDaily",
                           "egCollector", "egManualFeedback", "egStamp"]
                    route.fulfill(content_type="text/html", body="".join(
                        f'<div id="{item}"></div>' for item in ids))
                elif path == "/api/fb/engage/threads":
                    route.fulfill(json={
                        "account": account,
                        "posts": [{"post_url": "https://facebook.com/p/1",
                                   "account": account, "job_id": "P1",
                                   "group_id": "G1", "group_name": "กลุ่ม",
                                   "active": True, "comments_list": [{
                                       "comment_key": "c1", "author": "ลูกค้า",
                                       "body": "สนใจ", "is_ours": False,
                                       "answered": 0, "reply_queued_at": "queued",
                                       "reply_sent_at": "", "reply_error": "",
                                   }]}],
                        "reply_schedule": {"account": account, "waiting": True,
                                           "wait_seconds": 600},
                        "work_priority": {"account": account, "blocked": True,
                                          "reason": "cooldown", "wait_seconds": 600},
                    })
                elif path == "/api/fb/engage/start-now":
                    calls["start"] += 1
                    route.fulfill(json={
                        "ok": True,
                        "work_priority": {"account": account, "blocked": False,
                                          "reason": "", "wait_seconds": 0},
                        "reply_schedule": {"account": account, "waiting": False,
                                           "wait_seconds": 0, "next_at": 0},
                    })
                elif path == "/core.js":
                    route.fulfill(content_type="text/javascript", body=(
                        "export async function api(u,o={}){const r=await fetch(u,o);"
                        "const j=await r.json();if(!r.ok)throw Error(j.detail||'error');return j}"))
                elif path == "/gfaccount.js":
                    route.fulfill(content_type="text/javascript", body=(
                        f'export const gfQuery=p=>p;export const gfAccount=()=>{account!r};'))
                elif path == "/engage.js":
                    route.fulfill(path=str(Path("web/engage.js").resolve()))
                else:
                    route.fulfill(json={})

            page.route("**/*", handle)
            page.goto("http://studio.test/")
            page.evaluate("async()=>{window.eg=await import('/engage.js');await eg.loadEngage()}")
            button = page.locator("#egTimer .eg-start-now")
            expect(button).to_be_visible()
            button.click()
            expect(page.locator("#egTimer")).to_contain_text("ครบเวลาพักแล้ว")
            expect(page.locator("#egTimer .eg-start-now")).to_have_count(0)
            self.assertEqual(calls["start"], 1)
            browser.close()

    def test_restriction_banner_has_confirmed_resume_button(self):
        calls = {"resume": 0}
        account = "Khao Fang Nichapa"
        with sync_playwright() as pw:
            browser = pw.chromium.launch(channel="chrome", headless=True)
            page = browser.new_page()

            def handle(route):
                path = route.request.url.split("studio.test", 1)[1].split("?", 1)[0]
                if path == "/":
                    ids = ["egNote", "egTimer", "egList", "egDaily",
                           "egCollector", "egManualFeedback", "egStamp"]
                    route.fulfill(content_type="text/html", body="".join(
                        f'<div id="{item}"></div>' for item in ids))
                elif path == "/api/fb/engage/threads":
                    route.fulfill(json={
                        "account": account,
                        "posts": [{"post_url": "https://facebook.com/p/1",
                                   "account": account, "job_id": "P1",
                                   "group_id": "G1", "group_name": "กลุ่ม",
                                   "active": True, "comments_list": [{
                                       "comment_key": "c1", "author": "ลูกค้า",
                                       "body": "สนใจ", "is_ours": False,
                                       "answered": 0, "reply_queued_at": "queued",
                                       "reply_sent_at": "", "reply_error": "",
                                   }]}],
                        "reply_schedule": {"account": account, "waiting": True,
                                           "reason": "safety_hold",
                                           "wait_seconds": 12_000,
                                           "note": "พักคอมเมนต์อยู่"},
                        "work_priority": {"account": account, "blocked": False,
                                          "reason": "", "wait_seconds": 0},
                    })
                elif path == "/api/fb/engage/resume-after-restriction":
                    calls["resume"] += 1
                    route.fulfill(json={
                        "ok": True,
                        "work_priority": {"account": account, "blocked": False,
                                          "reason": "", "wait_seconds": 0},
                        "reply_schedule": {"account": account, "waiting": False,
                                           "wait_seconds": 0, "next_at": 0},
                    })
                elif path == "/core.js":
                    route.fulfill(content_type="text/javascript", body=(
                        "export async function api(u,o={}){const r=await fetch(u,o);"
                        "const j=await r.json();if(!r.ok)throw Error(j.detail||'error');return j}"))
                elif path == "/gfaccount.js":
                    route.fulfill(content_type="text/javascript", body=(
                        f'export const gfQuery=p=>p;export const gfAccount=()=>{account!r};'))
                elif path == "/engage.js":
                    route.fulfill(path=str(Path("web/engage.js").resolve()))
                else:
                    route.fulfill(json={})

            page.route("**/*", handle)
            page.on("dialog", lambda dialog: dialog.accept())
            page.goto("http://studio.test/")
            page.evaluate("async()=>{window.eg=await import('/engage.js');await eg.loadEngage()}")
            button = page.locator("#egTimer .eg-start-now")
            expect(button).to_have_text("▶ ลองรันต่อ")
            expect(page.locator("#egTimer")).to_contain_text("Facebook จะปลดข้อจำกัด")
            button.click()
            expect(page.locator("#egTimer")).to_contain_text("ครบเวลาพักแล้ว")
            expect(page.locator("#egTimer .eg-start-now")).to_have_count(0)
            self.assertEqual(calls["resume"], 1)
            browser.close()


if __name__ == "__main__":
    unittest.main()
