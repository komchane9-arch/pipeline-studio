import ast
import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from link_library import LinkLibrary


class LibraryTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = LinkLibrary(Path(self.temp.name) / 'library.db')

    def tearDown(self):
        self.temp.cleanup()

    def test_shop_persists_through_stage_changes_and_job_removal(self):
        self.store.record('https://shopee.co.th/a', 'j1', 'ร้าน ก')
        job = dict(id='j1', link='https://shopee.co.th/a', item_id='123', name='โซฟา', stage='done')
        self.store.listing([job])
        result = LinkLibrary(self.store.path).listing([])
        self.assertEqual(result['items'][0]['item_id'], '123')
        self.assertEqual(result['items'][0]['shop'], 'ร้าน ก')
        self.assertEqual(result['items'][0]['name'], 'โซฟา')

    def test_legacy_import_and_reassign_do_not_duplicate(self):
        job = dict(id='j1', link='https://shopee.co.th/a', stage='queued')
        self.store.listing([job])
        self.store.assign(job['link'], 'ร้านใหม่')
        self.store.listing([job])
        self.store.record(job['link'], 'j1')
        result = self.store.listing([job])
        self.assertEqual(len(result['items']), 1)
        self.assertEqual(result['items'][0]['shop'], 'ร้านใหม่')
        self.assertEqual(result['shops'], ['ร้านใหม่'])

    def test_invalid_shop_and_unknown_assignment(self):
        for name in ('', 'x' * 121):
            with self.assertRaises(ValueError): self.store.add_shop(name)
        with self.assertRaises(ValueError): self.store.assign('absent', 'A')

    def test_routes_reuse_queue_preserve_affiliate_and_serve_existing_images(self):
        # Execute actual route definitions without starting live workers or Telegram.
        import re
        app = FastAPI()
        jobs = []
        def add(link, chat):
            row = dict(id=f'j{len(jobs)}', link=link, stage='queued', chat_id=chat)
            jobs.append(row)
            return row.copy()
        def update(id, **fields):
            next(j for j in jobs if j['id'] == id).update(fields)
        queue = SimpleNamespace(all=lambda: [j.copy() for j in jobs], add=add, update=update,
            waiting=lambda: jobs, load_now=lambda: {}, load_text=lambda: '')
        import threading
        env = dict(app=app, asyncio=asyncio, Request=Request, HTTPException=HTTPException,
            link_library=self.store, clip_jobs=queue, _default_clip_chat=lambda: '',
            _web_lock=threading.Lock(), _link_key=lambda s: s, LINK_TAKEN_STAGES={'queued','done'},
            TIKTOK_LINK_RE=re.compile(r'https://www\.tiktok\.com/[^\s]+'),
            SHOPEE_LINK_RE=re.compile(r'https://shopee\.co\.th/[^\s]+'),
            _wake_runners=Mock(), _clip_log=Mock(), _clip_say=Mock(), DATA_DIR=Path(self.temp.name),
            clip_queue=SimpleNamespace(STAGE_LABEL={'queued':'รอดึง', 'done':'เสร็จแล้ว'}),
            clip_store=SimpleNamespace(load_run=lambda root,id: {'images':['one.jpg'], 'image_pool':['one.jpg','two.jpg']}))
        source = Path(__file__).with_name('clip_app.py').read_text(encoding='utf-8')
        names = {'jobs_add','link_library_list','link_library_shop','link_library_assign','link_library_images'}
        tree = ast.parse(source)
        selected = [n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name in names]
        exec(compile(ast.Module(body=selected, type_ignores=[]), '<actual library routes>', 'exec'), env)
        client = TestClient(app)
        self.assertEqual(client.post('/api/jobs', json={'links':'garbage','shop':'A'}).status_code, 400)
        self.assertEqual(client.post('/api/jobs', json={'links':'https://shopee.co.th/a','shop':''}).status_code, 400)
        url = 'https://shopee.co.th/product/1/2?affiliate=KeepMe'
        self.assertEqual(client.post('/api/link-library/shops', json={'name':'ร้าน A'}).status_code, 200)
        first = client.post('/api/jobs', json={'links':url+' '+url,'shop':'ร้าน A'}).json()
        self.assertEqual(first['count'], 1)
        self.assertEqual(jobs[0]['link'], url)
        second = client.post('/api/jobs', json={'links':url,'shop':'ร้าน B'}).json()
        self.assertEqual(second['count'], 0)
        self.assertEqual(second['skipped'], 1)
        jobs[0].update(item_id='123', name='เก้าอี้', stage='done')
        result = client.get('/api/link-library').json()
        self.assertEqual(result['items'][0]['shop'], 'ร้าน B')
        self.assertEqual(result['items'][0]['stage'], 'done')
        self.assertEqual(client.get('/api/link-library/images', params={'url':url}).json()['images'], ['one.jpg','two.jpg'])
        self.assertEqual(client.get('/api/link-library/images', params={'url':'absent'}).status_code, 404)
        self.assertEqual(client.post('/api/link-library/assign', json={'url':url,'shop':'ร้าน A'}).status_code, 200)
        self.assertEqual(len(jobs), 1)


if __name__ == '__main__':
    unittest.main()
