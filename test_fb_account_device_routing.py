"""ทดสอบว่างาน Telegram ห้ามถอยไปโพสต์เครื่องตัวหลักเมื่อบัญชีไม่ตรง."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest import mock


TEST_ROOT = Path(tempfile.mkdtemp(prefix="pipeline-fb-routing-"))
os.environ["STUDIO_DATA_DIR"] = str(TEST_ROOT / "data")

import app  # noqa: E402
import fb_auto_post  # noqa: E402


def check(ok: bool, message: str) -> None:
    if not ok:
        raise AssertionError(message)
    print("✅ " + message)


with (
    mock.patch.object(app.fb_auto_post, "posting_account", return_value="บัญชีไม่มีเครื่อง"),
    mock.patch.object(
        app.device_book,
        "device_for_account",
        side_effect=app.device_book.DeviceError("ไม่พบเครื่องของบัญชีนี้"),
    ),
    mock.patch.object(app.device_book, "resolve", return_value="default-phone") as resolve,
):
    try:
        app._fb_serial()
    except fb_auto_post.AutoPostError as error:
        check("ป้องกันการโพสต์ผิดเครื่อง" in str(error), "บัญชีไม่มีเครื่องถูกปฏิเสธเสียงดัง")
    else:
        raise AssertionError("บัญชีไม่มีเครื่องกลับถูกส่งไปเครื่องตัวหลัก")
    check(not resolve.called, "ไม่ถอยไปเรียกเครื่องตัวหลัก")


with (
    mock.patch.object(app.fb_auto_post, "posting_account", return_value="Khao Fang Nichapa"),
    mock.patch.object(app.device_book, "device_for_account", return_value="redmi-screen-2"),
    mock.patch.object(app.device_book, "resolve", return_value="redmi-screen-2"),
    mock.patch.object(
        app,
        "list_devices",
        return_value=[{"serial": "redmi-screen-2", "ready": True}],
    ),
):
    check(app._fb_serial() == "redmi-screen-2", "บัญชีที่ผูกแล้วเลือก REDMI จอ 2")
