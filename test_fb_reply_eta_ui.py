"""ETA on the reply bar is account-scoped and refreshes when queue work changes."""
import unittest
from pathlib import Path

from playwright.sync_api import expect, sync_playwright


class ReplyEtaUI(unittest.TestCase):
    def test_maximum_eta_updates_for_both_facebook_accounts(self):
        with sync_playwright() as pw:
            browser = pw.chromium.launch(channel="chrome", headless=True)
            for account in ("Khao Fang Nichapa", "Preaw Buchakorn"):
                with self.subTest(account=account):
                    queued = {"count": 2}
                    page = browser.new_page()

                    def handle(route):
                        path = route.request.url.split("studio.test", 1)[1].split("?", 1)[0]
                        if path == "/":
                            ids = ["egNote", "egTimer", "egList", "egDaily",
                                   "egCollector", "egManualFeedback", "egStamp"]
                            route.fulfill(content_type="text/html", body="".join(
                                f'<div id="{item}"></div>' for item in ids))
                        elif path == "/api/fb/engage/threads":
                            comments = [
                                {"comment_key": f"c{index}", "post_url": "https://facebook.com/p/1",
                                 "author": f"ลูกค้า {index}", "body": "สนใจ", "is_ours": False,
                                 "answered": 0, "reply_queued_at": "queued", "reply_sent_at": "",
                                 "reply_error": ""}
                                for index in range(queued["count"])
                            ]
                            route.fulfill(json={
                                "account": account,
                                "posts": [{"post_url": "https://facebook.com/p/1", "account": account,
                                           "job_id": "P1", "group_id": "G1", "group_name": "กลุ่ม",
                                           "active": True, "comments_list": comments}],
                                "reply_schedule": {"account": account, "waiting": True,
                                                   "wait_seconds": 600,
                                                   "next_at_text": "2026-09-22T19:00:00"},
                            })
                        elif path == "/core.js":
                            route.fulfill(content_type="text/javascript", body=(
                                "export async function api(u,o={}){const r=await fetch(u,o);return r.json()}"))
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
                    timer = page.locator("#egTimer")
                    expect(timer).to_contain_text(account)
                    expect(timer).to_contain_text("คาดว่าเสร็จไม่เกิน")
                    expect(timer).to_contain_text("2 ข้อความใน 1 โพสต์ × สูงสุด 15 นาที/ข้อความ")

                    queued["count"] = 3
                    page.evaluate("async()=>{await eg.loadEngage()}")
                    expect(timer).to_contain_text(
                        "3 ข้อความใน 1 โพสต์ × สูงสุด 15 นาที/ข้อความ")
                    page.close()
            browser.close()


if __name__ == "__main__":
    unittest.main()
