"""ทดสอบช่องทางสร้างโพสต์หน้าเว็บ โดยใช้ store ชั่วคราวและไม่แตะมือถือจริง."""

from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


TEST_ROOT = Path(tempfile.mkdtemp(prefix="pipeline-fb-web-"))
os.environ["STUDIO_DATA_DIR"] = str(TEST_ROOT / "data")

import app  # noqa: E402
import fb_auto_post  # noqa: E402
import fb_account_guard  # noqa: E402


def check(ok: bool, message: str) -> None:
    if not ok:
        raise AssertionError(message)
    print("✅ " + message)


image_dir = TEST_ROOT / "post-images"
image_dir.mkdir(parents=True)
jobs = fb_auto_post.JobStore(TEST_ROOT / "jobs.json")
groups = fb_auto_post.GroupStore(TEST_ROOT / "groups.json")
groups.store._write([
    {"group_id": "101", "name": "กลุ่มหนึ่ง", "enabled": True},
    {"group_id": "202", "name": "กลุ่มสอง", "enabled": True},
])

with (
    mock.patch.object(app, "FB_POST_DIR", image_dir),
    mock.patch.object(app, "fb_jobs", jobs),
    mock.patch.object(app, "fb_groups", groups),
    mock.patch.object(app.device_book, "resolve", return_value="redmi-web"),
    mock.patch.object(app.device_book, "enabled_serials", return_value=["redmi-web"]),
    mock.patch.object(app.device_book, "account", return_value="Web Account"),
    mock.patch.object(app, "_account_channel", return_value=("token", "chat-web")),
):
    job, account = app._fb_create_web_job_data(
        serial="redmi-web",
        caption="แคปชันจากหน้าเว็บ",
        group_ids=["101", "202"],
        comments=["คอมเมนต์หนึ่ง", "คอมเมนต์สอง"],
        post_assets=[(".jpg", b"post-one"), (".png", b"post-two")],
        comment_assets=[None, (".webp", b"comment-two")],
    )

    check(account == "Web Account", "ผูกงานเว็บกับบัญชีของมือถือที่เลือก")
    check(job["source"] == "web" and job["chat_id"] == "chat-web", "ระบุช่องทางเว็บโดยไม่ตัดช่อง Telegram")
    check(job["status"] == fb_auto_post.STATUS_READY, "สร้างเป็นงานพร้อมโพสต์")
    check(job["groups"] == ["101", "202"], "เก็บกลุ่มที่ผู้ใช้เลือกครบ")
    check(job["caption"] == "แคปชันจากหน้าเว็บ", "เก็บแคปชันครบ")
    check(job["comments"] == ["คอมเมนต์หนึ่ง", "คอมเมนต์สอง"], "เก็บคอมเมนต์สองช่องครบ")
    check(len(job["images"]) == 2 and all(Path(p).is_file() for p in job["images"]), "เก็บรูปโพสต์ทุกใบ")
    check(job["comment_images"][0] == "", "รักษาตำแหน่งคอมเมนต์ที่ไม่มีรูป")
    check(Path(job["comment_images"][1]).is_file(), "เก็บรูปของคอมเมนต์ช่องที่สองตรงช่อง")
    check(app._fb_job_media_path(job, "post", 1).read_bytes() == b"post-two", "เปิดดูรูปโพสต์ตามลำดับได้")
    check(app._fb_job_media_path(job, "comment", 1).read_bytes() == b"comment-two", "เปิดดูรูปคอมเมนต์ตามช่องได้")

    try:
        app._fb_create_web_job_data(
            serial="redmi-web", caption="ทดสอบ", group_ids=["101"],
            comments=["", ""], post_assets=[(".jpg", b"post")],
            comment_assets=[(".jpg", b"orphan"), None],
        )
    except fb_auto_post.AutoPostError as error:
        check("ต้องมีข้อความ" in str(error), "กันรูปคอมเมนต์หลุดไปอยู่ช่องที่ไม่มีข้อความ")
    else:
        raise AssertionError("ยอมรับรูปคอมเมนต์ที่ไม่มีข้อความ")

    try:
        app._fb_create_web_job_data(
            serial="redmi-web", caption="โพสต์อย่างเดียว", group_ids=["101"],
            comments=["", ""], post_assets=[(".jpg", b"post-only")],
            comment_assets=[None, None],
        )
    except fb_auto_post.AutoPostError as error:
        check("ติ๊กยืนยัน" in str(error), "ไม่ยอมเดาว่าคอมเมนต์ว่างคือความตั้งใจ")
    else:
        raise AssertionError("ยอมสร้างงานไม่มีคอมเมนต์โดยยังไม่ยืนยัน")

    time.sleep(0.005)  # รหัสงานใช้มิลลิวินาที; แยกใบของเคสทดสอบให้ชัด
    post_only, _account = app._fb_create_web_job_data(
        serial="redmi-web", caption="โพสต์อย่างเดียว", group_ids=["101"],
        comments=["", ""], post_assets=[(".jpg", b"post-only")],
        comment_assets=[None, None], no_comments_confirmed=True,
    )
    check(post_only["no_comments_confirmed"] is True,
          "เก็บหลักฐานว่าเจ้าของยืนยันโพสต์โดยไม่มีคอมเมนต์")
    result = {
        "group_id": "101", "posted": True,
        "link": "https://facebook.com/share/p/test/", "liked": True,
        "commented": False, "comment_liked": False,
    }
    check(app._fb_result_missing(post_only, result) == [],
          "งานที่ยืนยันไม่มีคอมเมนต์จบได้เมื่อโพสต์ เก็บลิงก์ และไลก์แล้ว")

    runner = mock.Mock()
    runner.start.return_value = None
    with (
        mock.patch.object(app, "_fb_gate", return_value=("redmi-web", "")),
        mock.patch.object(fb_account_guard, "require", return_value="Web Account"),
        mock.patch.object(app.fb_preflight, "check_duplicate",
                          return_value=SimpleNamespace(ok=True, detail="")),
        mock.patch.object(app.fb_runner, "for_device", return_value=runner),
        mock.patch.object(app, "_fb_say"),
        mock.patch.object(app, "_fb_gap_range", return_value=(10.0, 15.0)),
    ):
        start_note = app._fb_run_job_inner(post_only["id"])
    check(start_note == "" and runner.start.called,
          "ชั้นสั่งงานยอมเริ่มโพสต์จริงเมื่อยืนยันว่าไม่มีคอมเมนต์")

    time.sleep(0.005)
    draft = jobs.add(
        caption="รอยืนยัน", image=str(image_dir / "draft.jpg"),
        images=[str(image_dir / "draft.jpg")], groups=["101"],
        status=fb_auto_post.STATUS_READY, chat_id="chat-web",
    )
    _text, keyboard = app._fb_card(draft)
    labels = [button["text"] for row in keyboard["inline_keyboard"] for button in row]
    check("⬜ ยืนยันว่าโพสต์นี้ไม่มีคอมเมนต์" in labels,
          "การ์ด Telegram มีช่องยืนยันเมื่อยังไม่มีคอมเมนต์")
    check("🚀 ยังโพสต์ไม่ได้" in labels,
          "ยังไม่เปิดปุ่มโพสต์จนกว่าจะมีคอมเมนต์หรือกดยืนยัน")

    with mock.patch.object(app, "_fb_show_card"):
        note = app._telegram_callback("chat-web", f"nc:{draft['id']}", {})
    confirmed = jobs.get(draft["id"])
    check("ยืนยันแล้ว" in note and confirmed["no_comments_confirmed"] is True,
          "กดช่อง Telegram แล้วบันทึกการยืนยันลงใบงาน")
    _text, keyboard = app._fb_card(confirmed)
    labels = [button["text"] for row in keyboard["inline_keyboard"] for button in row]
    check("🚀 โพสต์ 1 กลุ่ม" in labels,
          "หลังยืนยันแล้วปุ่มโพสต์พร้อมใช้ทันที")

print("\nทดสอบช่องทางเว็บ Facebook Group ผ่านทั้งหมด")
