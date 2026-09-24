"""ทดสอบ hard stop ของงานโพสต์อัตโนมัติโดยไม่แตะมือถือหรือไฟล์ config จริง."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import clip_app                                               # noqa: E402


def require(ok: bool, message: str) -> None:
    if not ok:
        raise AssertionError(message)
    print("✅ " + message)


original_update = clip_app.shared.update_json
original_log = clip_app._clip_log
original_say = clip_app._clip_say
written: list[dict] = []
logs: list[str] = []
messages: list[str] = []


def fake_update(path, mutate, default=None, timeout=30.0, label=""):
    data = {
        clip_app.AUTO_APPROVE_KEY: {
            "shopee_post": True,
            "facebook_post": True,
            "tiktok_publish": True,
        }
    }
    result = mutate(data)
    written.append(result if result is not None else data)
    return written[-1]


try:
    clip_app.shared.update_json = fake_update
    clip_app._clip_log = logs.append
    clip_app._clip_say = lambda chat_id, text, *args, **kwargs: messages.append(text)
    clip_app._auto_pub_runtime_stops.clear()
    clip_app._auto_pub_next["shopee_post"] = 12345.0

    handled = clip_app._apply_auto_publish_stop(
        "shopee_post",
        {
            "error": "Shopee จำกัดจำนวนโพสต์",
            "automation_stop": {
                "code": "shopee_post_limit",
                "auto_key": "shopee_post",
                "reason": "Post too many video, please have a rest",
                "retry": False,
            },
        },
        "chat-test",
        "1162273790",
        "สินค้าเทส",
    )

    require(handled, "รับ hard stop ที่ตรงกับขั้น")
    switches = written[-1][clip_app.AUTO_APPROVE_KEY]
    require(switches["shopee_post"] is False, "ปิด shopee_post ใน config จริง")
    require(switches["facebook_post"] is True, "ไม่แตะ facebook_post")
    require(switches["tiktok_publish"] is True, "ไม่แตะ tiktok_publish")
    require("shopee_post" in clip_app._auto_pub_runtime_stops,
            "หยุดรอบถัดไปในหน่วยความจำทันที")
    require("shopee_post" not in clip_app._auto_pub_next,
            "ไม่ตั้ง backoff เพื่อกลับมาลอง Post ซ้ำ")
    require(any("Post too many" in line for line in logs), "log มีเหตุผลจาก Shopee")
    require(any("ไม่ลอง Post ซ้ำ" in line for line in messages),
            "Telegram แจ้งว่าปิดสวิตช์และไม่ retry")

    before = len(written)
    ignored = clip_app._apply_auto_publish_stop(
        "facebook_post",
        {"automation_stop": {
            "auto_key": "shopee_post", "reason": "wrong target", "retry": False,
        }},
        "", "x", "x",
    )
    require(not ignored, "ไม่ให้สัญญาณ Shopee ไปปิด Facebook")
    require(len(written) == before, "สัญญาณผิดขั้นไม่เขียน config")
finally:
    clip_app.shared.update_json = original_update
    clip_app._clip_log = original_log
    clip_app._clip_say = original_say
    clip_app._auto_pub_runtime_stops.clear()
    clip_app._auto_pub_next.pop("shopee_post", None)

