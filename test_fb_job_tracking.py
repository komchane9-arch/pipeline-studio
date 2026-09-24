import unittest
from unittest import mock
from types import SimpleNamespace

import fb_engagement


class JobTrackingTests(unittest.TestCase):
    def test_job_metadata_is_resolved_inside_requested_profile_only(self):
        same_link = 'https://facebook.com/groups/g/posts/1'
        jobs = {
            'Khao Fang Nichapa': [{
                'id':'PK','caption':'ของเขาฝาง','status':'done','source':'telegram',
                'created_at':'2026-09-21T10:00:00','images':['k.jpg'],
                'comments':['คอมเมนต์เขาฝาง'],'groups':['g'],
                'results':[{'link':same_link,'group_id':'g'}],
            }],
            'Preaw Buchakorn': [{
                'id':'PP','caption':'ของแพรว','status':'ready','source':'web',
                'created_at':'2026-09-21T11:00:00','images':['p.jpg','p2.jpg'],
                'comments':['หนึ่ง','สอง'],'groups':['g'],
                'results':[{'link':same_link,'group_id':'g'}],
            }],
        }
        with mock.patch.object(fb_engagement, 'watched_accounts',
                               return_value=list(jobs)), \
             mock.patch.object(fb_engagement.shared, 'known_accounts',
                               return_value=list(jobs)), \
             mock.patch.object(fb_engagement, '_jobs_of',
                               side_effect=lambda account: jobs[account]):
            khao = fb_engagement._post_meta_by_link('Khao Fang Nichapa')[same_link]
            preaw = fb_engagement._post_meta_by_link('Preaw Buchakorn')[same_link]
        self.assertEqual((khao['job_id'], khao['job_account'], khao['caption']),
                         ('PK', 'Khao Fang Nichapa', 'ของเขาฝาง'))
        self.assertEqual((preaw['job_id'], preaw['job_account'], preaw['caption']),
                         ('PP', 'Preaw Buchakorn', 'ของแพรว'))
        self.assertEqual(preaw['job_comment_count'], 2)
        self.assertEqual(preaw['job_group_count'], 1)

    def test_check_once_reserves_one_gap_per_job_not_per_post(self):
        posts = [
            {'account':'Khao Fang Nichapa','job_id':'P1','post_url':'u1','group_name':'g1','caption':''},
            {'account':'Khao Fang Nichapa','job_id':'P1','post_url':'u2','group_name':'g2','caption':''},
            {'account':'Khao Fang Nichapa','job_id':'P2','post_url':'u3','group_name':'g3','caption':''},
        ]
        opened = []
        result = {'reachable':True,'reactions':0,'comments':0,'shares':0,
                  'comments_list':[],'comments_snapshot_complete':True,'note':''}

        class Context:
            def cookies(self, *_): return [{'name':'c_user','value':'1'}]
        class Page:
            url = 'https://www.facebook.com/'
            context = Context()
        class Browser:
            pages = [Page()]
            def close(self): pass
        class PlaywrightCM:
            def __enter__(self): return SimpleNamespace()
            def __exit__(self, *_): return False
        conn = mock.Mock()
        conn.execute.return_value.fetchone.return_value = None

        def read(_page, url, **_kwargs):
            opened.append(url)
            return dict(result)

        with mock.patch('playwright.sync_api.sync_playwright', return_value=PlaywrightCM()), \
             mock.patch('fb_mass_finder.find_bot', return_value=SimpleNamespace()), \
             mock.patch('fb_mass_finder.launch_bot_browser', return_value=Browser()), \
             mock.patch.object(fb_engagement, 'open_db', return_value=conn), \
             mock.patch.object(fb_engagement, 'still_worth_watching', return_value=(True,'')), \
             mock.patch.object(fb_engagement, 'canonical_url', side_effect=lambda url: url), \
             mock.patch.object(fb_engagement, 'read_post', side_effect=read), \
             mock.patch.object(fb_engagement, 'save', return_value=(0,0)), \
             mock.patch.object(fb_engagement, 'watch_status', return_value={}), \
             mock.patch.object(fb_engagement, 'watched_accounts', return_value=['Khao Fang Nichapa']), \
             mock.patch('fb_collect_gate.state', return_value={}), \
             mock.patch('fb_collect_gate.wait_for_turn', return_value=True), \
             mock.patch('fb_collect_gate.require_login'), \
             mock.patch('fb_collect_gate.reserve_gap', return_value=0) as reserve, \
             mock.patch('fb_collect_gate.healthy'), \
             mock.patch('fb_collect_gate.status', return_value={'wait_seconds':0}):
            out = fb_engagement.check_once(force=True, posts_override=posts)

        self.assertEqual(opened, ['u1','u2','u3'])
        # เว้นระยะเฉพาะเมื่อยังมีใบงานถัดไป; หลังโพสต์สุดท้ายต้องจบทันที
        # เพื่อคืน Bot8 ให้รอบอัตโนมัติ/อีกบัญชีโดยไม่ค้าง 1–5 นาทีเปล่า ๆ.
        self.assertEqual(reserve.call_count, 1)
        self.assertTrue(all(call.kwargs.get('scope') == 'job'
                            for call in reserve.call_args_list))
        self.assertEqual(out['ok'], 3)

    def test_collector_groups_interleaved_posts_and_pauses_only_at_job_end(self):
        rows = [
            {'account':'Khao Fang Nichapa','job_id':'P1','post_url':'k1'},
            {'account':'Preaw Buchakorn','job_id':'P9','post_url':'p1'},
            {'account':'Khao Fang Nichapa','job_id':'P2','post_url':'k3'},
            {'account':'Khao Fang Nichapa','job_id':'P1','post_url':'k2'},
            {'account':'Khao Fang Nichapa','job_id':'','post_url':'legacy1'},
            {'account':'Khao Fang Nichapa','job_id':'','post_url':'legacy2'},
        ]
        ordered = fb_engagement._prioritize_collect_posts(rows)
        self.assertEqual([row['post_url'] for row in ordered],
                         ['k1','k2','k3','legacy1','legacy2','p1'])
        self.assertEqual(
            [fb_engagement._collect_job_ends(ordered, i) for i in range(len(ordered))],
            [False, True, True, True, True, True])

    def test_our_posts_carries_source_job_id(self):
        jobs = [{'id':'P100','created_at':'2026-09-21T08:00:00','caption':'cap',
                 'results':[{'link':'https://facebook.com/groups/g/posts/1','group_id':'g'}]}]
        groups = '[{"group_id":"g","name":"Group G"}]'
        fake_file = mock.Mock()
        fake_file.read_text.return_value = groups
        with mock.patch.object(fb_engagement, 'watched_accounts', return_value=['Preaw']), \
             mock.patch.object(fb_engagement.shared, 'known_accounts', return_value=['Preaw']), \
             mock.patch.object(fb_engagement.shared, 'account_dir') as account_dir, \
             mock.patch.object(fb_engagement, '_jobs_of', return_value=jobs), \
             mock.patch.object(fb_engagement, '_captions_by_link', return_value={}), \
             mock.patch.object(fb_engagement, '_caption_of', return_value=''):
            account_dir.return_value.__truediv__.return_value = fake_file
            rows = fb_engagement.our_posts()
        self.assertEqual(rows[0]['job_id'], 'P100')
        self.assertEqual(rows[0]['account'], 'Preaw')

    def test_cancel_job_changes_only_matching_account_job_posts(self):
        source = [dict(post_url='u1',job_id='P100'),dict(post_url='u2',job_id='P100')]
        changed = []
        def set_one(**kwargs):
            changed.append(kwargs)
            return {'post_url':kwargs['post_url']}
        with mock.patch.object(fb_engagement, 'tracked_posts', return_value=source) as tracked, \
             mock.patch.object(fb_engagement, 'set_post_watch', side_effect=set_one):
            out = fb_engagement.set_job_watch(
                account='Preaw', job_id='P100', active=False, actor='web')
        tracked.assert_called_once_with('Preaw', job_id='P100')
        self.assertEqual(out['post_urls'], ['u1','u2'])
        self.assertTrue(all(row['active'] is False for row in changed))
        self.assertTrue(all(row['account'] == 'Preaw' for row in changed))


if __name__ == '__main__':
    unittest.main()
