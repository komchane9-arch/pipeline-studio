"""Persistent pacing and login circuit breaker for the comment collector."""
import random
import time
from urllib.parse import urlsplit

import studio_shared as shared

STATE_FILE = shared.DATA_DIR / 'fb_comment_collector_gate.json'


class LoginRequired(RuntimeError):
    pass


def state():
    return shared.read_json(STATE_FILE, {})


def update(**values):
    current = state()
    current.update(values)
    shared.write_json_atomic(STATE_FILE, current)
    return current


def status():
    current = state()
    current['wait_seconds'] = max(0, int(max(current.get('next_at', 0), current.get('retry_at', 0)) - time.time() + 0.999))
    return current


def require_login(page, context):
    signed_in = any(c.get('name') == 'c_user' and c.get('value')
                    for c in context.cookies('https://www.facebook.com'))
    path = urlsplit(page.url).path.lower()
    if not signed_in or any(part in path for part in ('/login', '/checkpoint', '/two_step_verification')):
        raise LoginRequired('Bot8 ต้องล็อกอิน Facebook ใหม่ — หยุดเก็บและรักษา checkpoint ไว้')


def pause_login(reason):
    return update(needs_login=True, note=str(reason), updated_at=time.time())


def healthy():
    return update(needs_login=False, failures=0, retry_at=0, note='')


def failure(reason):
    count = int(state().get('failures', 0)) + 1
    delay = (300, 900, 1800, 3600)[min(count-1, 3)]
    return update(failures=count, retry_at=time.time()+delay, note=str(reason))


def reserve_gap(seconds=None, scope='job'):
    delay = random.uniform(60, 300) if seconds is None else float(seconds)
    update(next_at=time.time()+delay, last_delay_seconds=delay, gap_scope=scope)
    return delay


def wait_for_turn(stop=None, report=None):
    told = False
    while status()['wait_seconds']:
        if stop and stop():
            return False
        if report and not told:
            unit = 'ใบงาน' if state().get('gap_scope') == 'job' else 'โพสต์'
            report(f"Bot8 พักก่อน{unit}ถัดไปอีก {status()['wait_seconds']} วินาที (สุ่ม 1–5 นาที)")
            told = True
        time.sleep(min(1, status()['wait_seconds']))
    return True
