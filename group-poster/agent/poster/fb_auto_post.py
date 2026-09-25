"""ตัวแทน fb_auto_post ของ Studio — โมดูลโพสต์เรียกใช้แค่ state_file กับ active_account

ของจริงเป็นระบบคิวโพสต์อัตโนมัติทั้งชุด ซึ่งไม่ได้ขายในสินค้านี้
"""

from __future__ import annotations

import threading
from contextlib import contextmanager

import studio_shared

_ACTIVE = threading.local()


def active_account() -> str:
    return str(getattr(_ACTIVE, "account", "") or "")


def posting_account() -> str:
    return active_account() or "default"


def state_file(name: str):
    return studio_shared.account_file(posting_account(), name)


@contextmanager
def use_account(name: str):
    before = getattr(_ACTIVE, "account", "")
    _ACTIVE.account = str(name or "").strip()
    try:
        yield _ACTIVE.account
    finally:
        _ACTIVE.account = before
