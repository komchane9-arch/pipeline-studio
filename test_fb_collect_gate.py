import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import fb_collect_gate as gate
import fb_engagement


class GateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.patch = patch.object(gate, 'STATE_FILE', Path(self.temp.name)/'gate.json')
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.temp.cleanup()

    def test_gap_is_60_to_300_seconds_and_persisted(self):
        with patch.object(gate.time, 'time', return_value=1000), \
             patch.object(gate.random, 'uniform', return_value=180) as draw:
            self.assertEqual(gate.reserve_gap(), 180)
            draw.assert_called_once_with(60, 300)
        with patch.object(gate.time, 'time', return_value=1040):
            self.assertEqual(gate.status()['wait_seconds'], 140)
        self.assertEqual(gate.state()['next_at'], 1180)

    def test_login_wall_stops_without_fetching_again(self):
        page, browser = MagicMock(), MagicMock()
        page.url = 'https://www.facebook.com/login/'
        browser.cookies.return_value = [{'name':'c_user', 'value':'test'}]
        with self.assertRaises(gate.LoginRequired):
            gate.require_login(page, browser)
        page.goto.assert_not_called()
        gate.pause_login('needs login')
        with patch('fb_mass_finder.find_bot') as launch:
            self.assertTrue(fb_engagement.check_once()['needs_login'])
        launch.assert_not_called()

    def test_backoff_persists_and_caps_at_hour(self):
        with patch.object(gate.time, 'time', return_value=1000):
            waits = [gate.failure('network')['retry_at']-1000 for _ in range(5)]
        self.assertEqual(waits, [300,900,1800,3600,3600])
        gate.healthy()
        self.assertEqual(gate.state()['failures'], 0)

    def test_interrupt_preserves_remaining_gap(self):
        with patch.object(gate.time, 'time', return_value=1000):
            gate.reserve_gap(180)
            self.assertFalse(gate.wait_for_turn(stop=lambda: True))
            self.assertEqual(gate.status()['wait_seconds'], 180)

    def test_bot8_and_requested_interval(self):
        self.assertEqual(fb_engagement.COLLECTOR_PROFILE, 'Bot8')
        self.assertEqual(fb_engagement.BETWEEN_POSTS, (60,300))


if __name__ == '__main__':
    unittest.main()
