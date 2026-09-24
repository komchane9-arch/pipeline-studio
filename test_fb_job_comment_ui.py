"""UI contract: account -> work order -> group -> post -> comments."""
import copy
import unittest
from pathlib import Path
from playwright.sync_api import sync_playwright, expect


class JobCommentUI(unittest.TestCase):
    def test_job_hierarchy_collect_and_cancel_whole_job(self):
        posts = [
            dict(post_url='https://facebook.com/groups/g1/posts/1', account='Preaw',
                 job_id='P100', group_id='g1', group_name='กลุ่มหนึ่ง', caption='งานแรก',
                 job_account='Preaw', job_status='ready', job_source='telegram',
                 job_created_at='2026-09-21T13:45:00', job_run_at='2026-09-21T15:00:00',
                 job_group_count=2, images=1, job_comment_count=2,
                 job_comment_texts=['คอมเมนต์หนึ่ง', 'คอมเมนต์สอง'], comment_images=0,
                 active=True, pending=1, comments_list=[dict(comment_key='c1', author='A',
                 body='สนใจ', is_ours=False, answered=0)]),
            dict(post_url='https://facebook.com/groups/g2/posts/2', account='Preaw',
                 job_id='P100', group_id='g2', group_name='กลุ่มสอง', caption='งานแรก',
                 active=True, pending=0, comments_list=[]),
            dict(post_url='https://facebook.com/groups/g1/posts/3', account='Preaw',
                 job_id='P200', group_id='g1', group_name='กลุ่มหนึ่ง', caption='งานสอง',
                 active=True, pending=0, comments_list=[]),
        ]
        requests = []
        with sync_playwright() as pw:
            browser = pw.chromium.launch(channel='chrome', headless=True)
            page = browser.new_page()
            def route(r):
                path = r.request.url.split('studio.test', 1)[1].split('?', 1)[0]
                if path == '/':
                    ids = ['egNote','egTimer','egList','egDaily','egCollector','egManualFeedback','egStamp']
                    r.fulfill(content_type='text/html', body=''.join(f'<div id="{x}"></div>' for x in ids))
                elif path == '/api/fb/engage/threads':
                    r.fulfill(json={'account':'Preaw','posts':copy.deepcopy(posts),
                        'reply_worker': {'active': True, 'author': 'A',
                            'job_id': 'P100', 'group_name': 'กลุ่มหนึ่ง',
                            'post_url': posts[0]['post_url'],
                            'action': 'กำลังพิมพ์คำตอบบนมือถือ'}})
                elif path == '/api/fb/engage/collect':
                    requests.append(r.request.post_data_json)
                    r.fulfill(json={'manual':{'status':'queued','current_account':'Preaw'}})
                elif path == '/api/fb/engage/watch':
                    body = r.request.post_data_json
                    requests.append(body)
                    stopped = [p['post_url'] for p in posts if p['job_id'] == body['job_id']]
                    r.fulfill(json={'job_id':body['job_id'],'post_urls':stopped,'changed':len(stopped)})
                elif path == '/core.js':
                    r.fulfill(content_type='text/javascript', body='export const api=async(u,o={})=>{const r=await fetch(u,o);return r.json()};')
                elif path == '/gfaccount.js':
                    r.fulfill(content_type='text/javascript', body='export const gfQuery=p=>p; export const gfAccount=()=>"Preaw";')
                elif path == '/engage.js':
                    r.fulfill(path=str(Path('web/engage.js').resolve()))
                else:
                    r.fulfill(json={})
            page.route('**/*', route)
            page.on('dialog', lambda dialog: dialog.accept())
            page.goto('http://studio.test/')
            page.evaluate("async()=>{window.eg=await import('/engage.js');await eg.loadEngage()}")
            expect(page.locator('.eg-job')).to_have_count(2)
            p100 = page.locator('.eg-job[data-job-id="P100"]')
            expect(p100.locator(':scope > .eg-job-body > .eg-job-groups > .eg-group')).to_have_count(2)
            # เปิดตรง state ของ dropdown; การ click กลาง summary ใน viewport จำลอง
            # อาจตกบนปุ่ม action ที่เรียงอยู่ใน summary แทนลูกศร.
            p100.evaluate('(node) => { node.open = true; node.dispatchEvent(new Event("toggle")); }')
            # รายละเอียดใบงานย้ายขึ้นเป็นก้อนแรก และรายละเอียดโพสต์/ช่องตอบ
            # อยู่ในกลุ่มตรงตำแหน่งเดิม ไม่ต้องกด preview แล้วเลื่อนไปอีกชุด.
            expect(p100.locator(':scope > .eg-job-body > :first-child')).to_have_class('eg-job-detail')
            expect(p100.locator('.eg-job-links')).to_have_count(0)
            expect(p100.locator('.eg-comment[data-comment-key="c1"]')).to_be_visible()
            expect(p100.locator('.eg-comment[data-comment-key="c1"] textarea')).to_be_visible()
            expect(page.locator('#egTimer')).to_contain_text('กำลังตอบ A · ใบงาน P100')
            expect(page.locator('#egTimer')).to_contain_text('กลุ่ม กลุ่มหนึ่ง')
            expect(page.locator('#egTimer')).to_contain_text('กำลังพิมพ์คำตอบบนมือถือ')
            expect(page.locator('#egTimer a')).to_have_attribute('href', posts[0]['post_url'])
            expect(p100.locator('.eg-job-account')).to_have_text('👤 Preaw')
            expect(p100.locator('.eg-job-profile')).to_have_text('👤 โปรไฟล์ Preaw')
            expect(p100.locator('.eg-job-state')).to_contain_text('รอโพสต์')
            expect(p100.locator('.eg-job-state')).to_contain_text('จาก Telegram')
            expect(p100.locator('.eg-job-meta')).to_have_text('🖼 1 ใบ · 💬 2 คอมเมนต์ · 📦 2 กลุ่ม')
            expect(p100.locator('.eg-job-times')).to_contain_text('สร้าง 13:45')
            p100.locator('.eg-job-content > summary').click()
            expect(p100.locator('.eg-job-content-body .eg-job-comment')).to_have_count(2)
            expect(p100.locator('.eg-job-content-body')).to_contain_text('คอมเมนต์สอง')
            expect(p100.locator('.eg-comment[data-comment-key="c1"]')).to_contain_text('สนใจ')
            p100.get_by_role('button', name='▶ เก็บใบงานนี้ใหม่').click()
            page.wait_for_function('window.__noop===undefined')
            self.assertEqual(requests[0], {'scope':'job','account':'Preaw','job_id':'P100'})
            # Reset mock busy state so the cancellation button is still independent.
            p100.get_by_role('button', name='🛑 ยกเลิกตามเก็บใบงาน').click()
            expect(page.locator('.eg-job[data-job-id="P100"]')).to_have_count(0)
            expect(page.locator('.eg-job[data-job-id="P200"]')).to_have_count(1)
            self.assertEqual(requests[1], {'action':'stop','account':'Preaw','job_id':'P100'})
            browser.close()


if __name__ == '__main__':
    unittest.main()
