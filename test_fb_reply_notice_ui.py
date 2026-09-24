"""Browser test with intercepted APIs only; never sends a real reply."""
import copy
import unittest
from pathlib import Path
from playwright.sync_api import sync_playwright, expect


class ReplyNoticeUI(unittest.TestCase):
    def test_resume_verify_failure_and_completion_link_without_post_navigation(self):
        rows = [dict(comment_key='demi', author='Demi', body='hello', reply_draft='saved', reply_error='TimeoutExpired'),
                dict(comment_key='unknown', author='Alice', body='hello', reply_draft='other', reply_error='unknown', reply_submitted_at='submitted'),
                dict(comment_key='remove-me', author='Bob', body='hello', reply_draft='third', reply_error='AccountUnreadable')]
        states = {}
        requests = []
        fail = False
        with sync_playwright() as pw:
            browser = pw.chromium.launch(channel='chrome', headless=True)
            page = browser.new_page()
            def handle(route):
                nonlocal fail
                path = route.request.url.split('studio.test', 1)[1].split('?', 1)[0]
                if path == '/':
                    route.fulfill(content_type='text/html', body='<div id="egNote"></div><div id="egTimer"></div><div id="egList"></div>')
                elif path == '/api/fb/engage/threads':
                    route.fulfill(json={'account':'Preaw', 'posts':[dict(post_url='https://www.facebook.com/share/p/test/',account='Preaw',group_id='g',group_name='group',active=True,comments_list=copy.deepcopy(rows))]})
                elif path == '/api/fb/engage/retry':
                    requests.append(route.request.post_data_json)
                    if fail:
                        route.fulfill(status=400, json={'detail':'retry failed'})
                    else:
                        key = route.request.post_data_json['comment_key']
                        route.fulfill(json={'reply_queued_at':'queued', 'reply_submitted_at':'submitted' if key=='unknown' else ''})
                elif path == '/api/fb/engage/reply-status':
                    route.fulfill(json={'comments':[dict(comment_key=k, **v) for k,v in states.items()]})
                elif path == '/api/fb/engage/ignore':
                    requests.append(route.request.post_data_json)
                    route.fulfill(json={'ok':True,'ignored':True})
                elif path == '/core.js':
                    route.fulfill(content_type='text/javascript', body='export async function api(u,o={}) {const r=await fetch(u,o);const j=await r.json();if(!r.ok)throw new Error(j.detail);return j;}')
                elif path == '/gfaccount.js':
                    route.fulfill(content_type='text/javascript', body='export const gfQuery = p => p; export const gfAccount = () => "Preaw";')
                elif path == '/engage.js':
                    route.fulfill(path=str(Path('web/engage.js').resolve()))
                else:
                    route.fulfill(json={})
            page.route('**/*', handle)
            page.goto('http://studio.test/')
            page.evaluate("async()=>{window.eg=await import('/engage.js');await eg.loadEngage();window.ticks=[];window.setInterval=(fn)=>{ticks.push(fn);return ticks.length;};eg.wireEngage();}")
            demi = page.locator('.eg-reply-notice[data-comment-key="demi"]')
            unknown = page.locator('.eg-reply-notice[data-comment-key="unknown"]')
            removable = page.locator('.eg-reply-notice[data-comment-key="remove-me"]')
            expect(demi.get_by_role('button',name='▶ ทำต่อ',exact=True)).to_be_visible()
            expect(unknown.get_by_role('button',name='🔎 ตรวจผล',exact=True)).to_be_visible()
            expect(removable.get_by_role('button',name='🗑 ลบรายการ',exact=True)).to_be_visible()
            removable.get_by_role('button',name='🗑 ลบรายการ',exact=True).click()
            expect(removable).to_have_count(0)
            self.assertEqual(requests[-1], {'comment_key':'remove-me','on':True})
            # Local unsaved input elsewhere must survive all status polls.
            # รายการที่ต้องทำเปิดใบงาน/กลุ่ม/โพสต์ให้เองตามโครงสร้างใหม่.
            # Submitted inputs are disabled intentionally, keep a different editable field.
            draft = page.locator('.eg-comment[data-comment-key="demi"] textarea')
            draft.fill('unsaved edit: do not submit this')
            page.locator('.eg-group > summary').click()  # หุบไว้ระหว่าง poll
            fail = True
            demi.locator('.eg-notice-retry').click()
            expect(demi).to_contain_text('retry failed')
            fail = False
            demi.locator('.eg-notice-retry').click()
            expect(demi.locator('.eg-notice-retry')).to_have_text('เข้าคิวแล้ว')
            self.assertEqual(requests[-1], {'comment_key':'demi','account':'Preaw'})
            states['demi'] = dict(reply_error='new failure', reply_sent_at='', reply_submitted_at='')
            page.evaluate('async()=>{await ticks[1]();}')
            expect(demi).to_contain_text('new failure')
            expect(draft).to_have_value('unsaved edit: do not submit this')
            demi.locator('.eg-notice-retry').click()
            expect(demi.locator('.eg-notice-retry')).to_have_text('เข้าคิวแล้ว')
            states['demi'] = dict(reply_sent_at='verified',answered=1,reply_error='')
            page.evaluate('async()=>{await ticks[1]();}')
            expect(demi).to_have_count(0)
            success = page.locator('.eg-reply-notice.is-done')
            expect(success).to_contain_text('Demi ตอบสำเร็จ')
            expect(success.get_by_role('link')).to_have_attribute('href','https://www.facebook.com/share/p/test/')
            # โหมดเริ่มต้นใหม่แสดงทุกใบงาน จึงคงคอมเมนต์ที่ตอบแล้วไว้เป็นประวัติ.
            expect(page.locator('.eg-comment[data-comment-key="demi"]')).to_have_count(1)
            unknown.locator('.eg-notice-retry').click()
            expect(unknown).to_contain_text('รอตรวจผล ไม่ส่งซ้ำ')
            self.assertEqual(requests[-1], {'comment_key':'unknown','account':'Preaw'})
            success.get_by_role('button',name='ปิด').click()
            expect(success).to_have_count(0)
            browser.close()

if __name__ == '__main__':
    unittest.main()
