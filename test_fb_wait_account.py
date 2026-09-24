"""No server imports, phone calls, or real data writes."""
import ast
from contextlib import contextmanager
from pathlib import Path
import threading
import unittest


class WaitAccountTests(unittest.TestCase):
    def check_queue(self, busy=False, account='Preaw'):
        tree = ast.parse(Path(__file__).with_name('app.py').read_bytes())
        fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                  and n.name == '_phone_wait_pump')
        current = ['wrong outer account']
        seen = []
        item = dict(kind='followup', job_id='job', chat_id='', serial='phone')
        queue = [item]

        @contextmanager
        def ctx(job_id):
            self.assertEqual(job_id, 'job')
            old = current[0]
            current[0] = account
            try:
                yield
            finally:
                current[0] = old

        def followup(**kwargs):
            seen.append(current[0])
            self.assertTrue(kwargs['queued'])
            return 'wait' if busy else ''

        ns = dict(_waitlist_lock=threading.Lock(), _phone_waitlist=queue,
                  phone_is_free=lambda serial: True, append_log=lambda *args: None,
                  _job_ctx=ctx, _fb_followup=followup, PHONE_WAIT_NOTE='wait')
        exec(compile(ast.Module(body=[fn], type_ignores=[]), '<queue>', 'exec'), ns)
        ns['_phone_wait_pump']()
        self.assertEqual(seen, [account])
        self.assertEqual(current[0], 'wrong outer account')
        self.assertEqual(queue, [item] if busy else [])

    def test_preaw(self):
        self.check_queue()

    def test_other_account(self):
        self.check_queue(account='Khao Fang Nichapa')

    def test_busy_returns_original_item(self):
        self.check_queue(busy=True)


if __name__ == '__main__':
    unittest.main()
