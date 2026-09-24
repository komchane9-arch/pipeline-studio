import ast
import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from fastapi import FastAPI, Request, HTTPException
from fastapi.testclient import TestClient
from link_library import LinkLibrary

class SaveTests(unittest.TestCase):
    def test_save_is_persistent_without_queue_or_network_and_can_pull_later(self):
        with tempfile.TemporaryDirectory() as directory:
            store=LinkLibrary(Path(directory)/'links.db')
            app=FastAPI()
            queue=Mock(side_effect=AssertionError('save must not queue'))
            env=dict(app=app,asyncio=asyncio,Request=Request,HTTPException=HTTPException,
                     link_library=store,clip_jobs=queue,_wake_runners=queue)
            tree=ast.parse(Path(__file__).with_name('clip_app.py').read_text(encoding='utf-8'))
            fn=next(n for n in tree.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='link_library_save')
            exec(compile(ast.Module(body=[fn],type_ignores=[]),'<save route>','exec'),env)
            url='https://shopee.co.th/product/1/2?affiliate=original'
            with patch('socket.create_connection',side_effect=AssertionError('no network')):
                client=TestClient(app)
                result=client.post('/api/link-library/save',json={'links':url+'\n'+url,'shop':'ร้าน A'})
                self.assertEqual(result.status_code,200)
                self.assertEqual(result.json()['count'],1)
            row=LinkLibrary(store.path).listing([])['items'][0]
            self.assertEqual(row['url'],url)
            self.assertEqual(row['shop'],'ร้าน A')
            self.assertEqual(row['job_id'],'')
            store.record(url,'job1','ร้าน A')
            store.listing([dict(id='job1',link=url,item_id='2',name='สินค้า',stage='done')])
            store.save_links(url,'ร้าน B')
            row=store.listing([])['items'][0]
            self.assertEqual(row['job_id'],'job1')
            self.assertEqual(row['item_id'],'2')
            self.assertEqual(row['shop'],'ร้าน B')
            queue.assert_not_called()
            self.assertEqual(client.post('/api/link-library/save',json={'links':'javascript:alert(1)','shop':'A'}).status_code,400)
            self.assertEqual(client.post('/api/link-library/save',json={'links':url,'shop':''}).status_code,400)
    def test_existing_saved_link_adopts_job_from_another_entry_point(self):
        with tempfile.TemporaryDirectory() as directory:
            store=LinkLibrary(Path(directory)/'links.db')
            url='https://example.com/post'
            store.save_links(url,'A')
            row=store.listing([dict(id='j',link=url,item_id='',stage='queued')])['items'][0]
            self.assertEqual(row['job_id'],'j')
            self.assertEqual(row['shop'],'A')

if __name__=='__main__': unittest.main()

