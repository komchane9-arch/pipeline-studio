"""Exercise the real followup method without importing app or touching phones/data."""
import ast
from contextlib import contextmanager, nullcontext
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch


class FollowupAccountTests(unittest.TestCase):
    def run_case(self, fail=False, callback_fail=False):
        tree = ast.parse(Path(__file__).with_name('fb_auto_post.py').read_bytes())
        method = next(n for n in ast.walk(tree)
                      if isinstance(n, ast.FunctionDef) and n.name == '_run_followup')
        current = ['outer']
        seen = []
        logs = []

        @contextmanager
        def use_account(name):
            before = current[0]
            current[0] = name
            try:
                yield name
            finally:
                current[0] = before

        def followup(**kwargs):
            self.assertEqual(current[0], 'Preaw')
            if fail:
                raise RuntimeError('phone failed')
            return [{'posted': True}]

        def done(results, error):
            seen.append((current[0], results, error))
            if callback_fail:
                raise RuntimeError('callback failed')

        ns = dict(active_account=lambda: current[0], use_account=use_account,
                  studio_shared=SimpleNamespace(PhoneBusy=type('PhoneBusy', (Exception,), {})),
                  facebook_group_post=SimpleNamespace(followup_groups=followup))
        exec(compile(ast.Module(body=[method], type_ignores=[]), '<followup>', 'exec'), ns)
        runner = SimpleNamespace(job_id='test', stop_flag=SimpleNamespace(is_set=lambda: False),
                                 _phone=lambda *args: nullcontext())
        with patch.dict(sys.modules, devices=SimpleNamespace(account=lambda serial: 'Preaw')):
            ns['_run_followup'](runner, adb='unused', serial='test-phone', caption='test',
                                targets=[], comment=[], on_log=logs.append,
                                on_result=lambda entry: None, on_done=done)
        self.assertEqual(seen[0][0], 'Preaw')
        self.assertEqual(seen[0][2], 'phone failed' if fail else '')
        self.assertEqual(current[0], 'outer')
        self.assertEqual(runner.job_id, '')
        if callback_fail:
            self.assertTrue(any('callback failed' in line for line in logs))

    def test_success(self):
        self.run_case()

    def test_phone_failure(self):
        self.run_case(fail=True)

    def test_callback_failure_restores_context(self):
        self.run_case(callback_fail=True)


if __name__ == '__main__':
    unittest.main()
