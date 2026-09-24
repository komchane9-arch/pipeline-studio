"""Browser regression: completed Facebook jobs belong only in history."""
import unittest
from pathlib import Path

from playwright.sync_api import expect, sync_playwright


class FbControlTerminalUI(unittest.TestCase):
    def test_terminal_fallback_is_removed_but_live_job_still_renders(self):
        with sync_playwright() as pw:
            browser = pw.chromium.launch(channel="chrome", headless=True)
            page = browser.new_page()

            def route(request):
                path = request.request.url.split("studio.test", 1)[1].split("?", 1)[0]
                if path == "/":
                    ids = ["fcList", "fcHistory", "fcStamp", "fcNote"]
                    request.fulfill(
                        content_type="text/html",
                        body="".join(f'<div id="{item}"></div>' for item in ids),
                    )
                elif path == "/core.js":
                    request.fulfill(
                        content_type="text/javascript",
                        body="export const api=async()=>structuredClone(window.payload);",
                    )
                elif path == "/gfaccount.js":
                    request.fulfill(
                        content_type="text/javascript",
                        body=(
                            'export const gfQuery=p=>p; '
                            'export const gfAccount=()=>"Khao Fang Nichapa";'
                        ),
                    )
                elif path == "/fbcontrol.js":
                    request.fulfill(path=str(Path("web/fbcontrol.js").resolve()))
                else:
                    request.fulfill(status=404)

            page.route("**/*", route)
            page.goto("http://studio.test/")
            page.evaluate(
                """async()=>{
                  window.payload={
                    running:false, live_count:0, at:'18:00:00', history:[],
                    jobs:[{id:'p-done',status:'manual_done'}],
                  };
                  window.fc=await import('/fbcontrol.js');
                  await fc.loadFbControl();
                }"""
            )
            expect(page.locator("#fcList .fc-job")).to_have_count(0)
            expect(page.locator("#fcList")).to_contain_text("ไม่มีงานค้าง")
            expect(page.locator("#fcNote")).to_have_text("⚪ บอทว่าง ไม่มีงานค้าง")

            page.evaluate(
                """async()=>{
                  window.payload={
                    running:false, live_count:1, at:'18:01:00', history:[],
                    jobs:[{
                      id:'p-live',status:'ready',caption:'ใบที่ยังค้าง',source:'telegram',
                      created_at:'2026-09-22T18:00:00',run_at:'',started_at:'',
                      finished_at:'',images:1,comments:2,comment_images:0,
                      comment_texts:['หนึ่ง','สอง'],posted_count:0,failed:0,total:1,
                      pending:1,pending_posts:1,pending_followup:0,queue:[],tail:[],
                      latest_step:'',device:'',posted_via:'',deferred:false,
                      stopping:false,orphan:false,can_run:true,can_resume:false,
                      can_reset:true,can_complete:true,can_stop:false,why:'',
                      blocked_why:'',blocked_at:''
                    }],
                  };
                  await fc.loadFbControl();
                }"""
            )
            expect(page.locator("#fcList .fc-job")).to_have_count(1)
            expect(page.locator("#fcList")).to_contain_text("ใบที่ยังค้าง")

            page.evaluate(
                """async()=>{
                  window.payload={
                    running:false,live_count:0,at:'18:02:00',history:[],
                    jobs:[{id:'p-live',status:'done'}],
                  };
                  await fc.loadFbControl();
                }"""
            )
            expect(page.locator("#fcList .fc-job")).to_have_count(0)
            expect(page.locator("#fcList")).to_contain_text("ไม่มีงานค้าง")
            browser.close()


if __name__ == "__main__":
    unittest.main()
