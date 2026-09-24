"""ทดสอบด่านชื่อคลิปก่อนโพสต์ โดยไม่แตะมือถือหรือ ADB จริง."""

from __future__ import annotations

import sys

import publish_media

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def require(ok: bool, message: str) -> None:
    if not ok:
        raise AssertionError(message)
    print("✅ " + message)


name = publish_media.expected_phone_video_name(
    "55107737552", "55107737552", "video/clip.mp4",
)
require(name == "55107737552-clip.mp4", "ชื่อบนมือถือผูกกับรหัสใบงาน")

for recorded in ("", "23566255858"):
    try:
        publish_media.expected_phone_video_name(
            "55107737552", recorded, "video/clip.mp4",
        )
    except publish_media.PublishMediaIdentityError:
        pass
    else:
        raise AssertionError("รหัสใน run.json ไม่ตรงต้องถูกหยุด")
print("✅ รหัสคิวกับ run.json ไม่ตรงกันแล้วหยุด")

rows = (
    "Row: 0 _display_name=55107737552-clip.mp4, "
    "_data=/storage/emulated/0/Movies/autopost/55107737552-clip.mp4\n"
)
message = publish_media.validate_phone_video_inventory(
    "55107737552",
    "55107737552-clip.mp4",
    ["55107737552-clip.mp4"],
    rows,
    "/sdcard/Movies/autopost",
)
require("ตรงกับใบงาน 55107737552" in message,
        "ชื่อไฟล์จริงและ MediaStore ตรงกันจึงผ่าน")

bad_cases = [
    (["old.mp4", "55107737552-clip.mp4"], rows, "มีไฟล์อื่นค้าง"),
    (["55107737552-clip.mp4"], rows + rows, "MediaStore มีสองรายการ"),
    (["55107737552-clip.mp4"], rows.replace("55107737552", "23566255858"),
     "ชื่อ MediaStore เป็นคนละใบงาน"),
]
for files, raw, label in bad_cases:
    try:
        publish_media.validate_phone_video_inventory(
            "55107737552", "55107737552-clip.mp4", files, raw,
            "/sdcard/Movies/autopost",
        )
    except publish_media.PublishMediaIdentityError:
        print("✅ " + label + " → หยุด")
    else:
        raise AssertionError(label + " ต้องถูกหยุด")
