import json
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
import facebook_group_post as fb


class VerificationTests(unittest.TestCase):
    def test_callable_is_resolved_to_both_comments(self):
        self.assertEqual(fb._as_texts(lambda: ['one', 'two']), ['one', 'two'])

    def test_real_mobile_viewports_accumulate_both_comments(self):
        root = Path('diagnostics/job-comments-20260921-184414')
        evidence = json.loads((root / 'evidence.json').read_text(encoding='utf-8'))
        frames = [(root / f'{i:02d}.xml').read_text(encoding='utf-8') for i in range(9)]
        phone = Mock()
        phone.dump.side_effect = frames
        with patch.object(fb.time, 'sleep'):
            result = fb.verify_existing_comments(phone, lambda: evidence['wanted'], evidence['account'])
        self.assertEqual(result['comments_seen'], 2)
        self.assertEqual(result['comments_wanted'], 2)
        self.assertTrue(result['comments_complete'])
        self.assertGreater(phone.vswipe.call_count, 0)

    def test_partial_view_is_unknown_and_wrong_author_does_not_match(self):
        root = Path('diagnostics/job-comments-20260921-184414')
        evidence = json.loads((root / 'evidence.json').read_text(encoding='utf-8'))
        phone = Mock()
        phone.dump.return_value = (root / '02.xml').read_text(encoding='utf-8')
        with patch.object(fb.time, 'sleep'):
            result = fb.verify_existing_comments(phone, evidence['wanted'], 'Preaw Buchakorn')
        self.assertIsNone(result['comments_seen'])
        self.assertEqual(result['comments_observed'], 0)
        self.assertFalse(result['comments_complete'])


if __name__ == '__main__':
    unittest.main()
