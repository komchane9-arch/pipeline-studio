"""Browser regression: failed/late loads must never cross account tabs."""
import unittest
from pathlib import Path
from playwright.sync_api import sync_playwright


class AccountIsolation(unittest.TestCase):
    def test_switch_clears_every_panel_and_rejects_late_response(self):
        with sync_playwright() as pw:
            browser = pw.chromium.launch(channel='chrome', headless=True)
            page = browser.new_page()
            def route(r):
                path = r.request.url.split('studio.test', 1)[1]
                if path == '/':
                    ids = ['gfAccountTabs', 'gfAccountNote', 'gfLinkedGroups', 'gfLinkedCount',
                           'egList', 'egDaily', 'egTimer', 'egReplyAlerts', 'egCollector',
                           'egManualFeedback', 'egStamp', 'egNote', 'fcList', 'fcHistory', 'fcStamp', 'fcNote']
                    r.fulfill(content_type='text/html', body=''.join(f'<div id="{x}"></div>' for x in ids))
                elif path == '/core.js':
                    r.fulfill(content_type='text/javascript', body='export const $=s=>document.querySelector(s); export const api=(...a)=>window.mockApi(...a);')
                else:
                    r.fulfill(path=str(Path('web', path.lstrip('/')).resolve()))
            page.route('**/*', route)
            page.goto('http://studio.test/')
            page.evaluate('''async()=>{
              window.hold=false; window.fail=false; window.pending=[];
              window.mockApi=async(u,o)=>{
                if(u==='/api/fb/post-accounts')return {current:'A',accounts:['A','B'].map(account=>({account,device:account,groups:0,ready:true}))};
                const account=new URL(u,location.href).searchParams.get('account');
                if(window.fail)throw new Error('database is locked');
                if(window.hold)return new Promise(resolve=>pending.push({u,resolve}));
                return {account,posts:[],jobs:[],groups:[]};
              };
              window.gf=await import('/gfaccount.js');window.eg=await import('/engage.js');window.fc=await import('/fbcontrol.js');
              await gf.loadGfAccounts();
              gf.onGfAccountChange(()=>Promise.all([eg.loadEngage(),fc.loadFbControl()]));
              await eg.loadEngage();await fc.loadFbControl();
              for(const id of ['egList','egDaily','egTimer','egReplyAlerts','egCollector','egManualFeedback','fcList','fcHistory'])document.getElementById(id).textContent='OLD_ACCOUNT_SECRET';
              window.hold=true;eg.loadEngage();fc.loadFbControl();window.hold=false;window.fail=true;
            }''')
            page.get_by_role('tab').filter(has_text='B').click()
            page.wait_for_function("document.querySelector('#egNote').textContent.includes('database is locked')")
            self.assertNotIn('OLD_ACCOUNT_SECRET', page.locator('body').inner_text())
            page.evaluate("()=>pending.forEach(p=>p.resolve({account:'A',posts:[],jobs:[],groups:[]}))")
            page.wait_for_timeout(100)
            self.assertIn('database is locked', page.locator('#egNote').inner_text())
            self.assertEqual(page.locator('#egList').inner_text(), '')
            self.assertEqual(page.locator('#fcList').inner_text(), '')
            browser.close()


if __name__ == '__main__':
    unittest.main()
