"""ทดสอบว่าคิวโพสต์ TikTok ไม่หยิบใบที่ยังไม่ได้เพิ่มสินค้าเข้าโชว์เคส."""

from __future__ import annotations

import json
import io
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import clip_app                                               # noqa: E402


class TikTokAutoPublishReadyTests(unittest.TestCase):
    def test_visible_tiktok_toggle_controls_full_publish_pipeline(self) -> None:
        self.assertEqual(clip_app.BOARD_AUTO_STEP["tiktok"], "tiktok_publish")

    def test_ป้ายห้ามเจนซ้ำต้องไม่กั้นการโพสต์เมื่อใบนั้นเจนเสร็จแล้ว(self) -> None:
        """เจอจริง 13 ก.ย. 2569 — ใบ 29670968378 เจนเสร็จ คลิปครบ ด่านลำดับผ่าน
        แต่ไม่เคยถูกหยิบไปลงเลย เพราะในคิวมีแถวซ้ำที่ถูกพักไว้ตั้งแต่ 10 ก.ย.
        ด้วยเหตุผล "ห้ามให้ตัวกวาดดึงกลับมาเจนซ้ำ" ซึ่งคนละเรื่องกับการโพสต์

        เจตนา "ห้ามโพสต์" ของเจ้าของอยู่ที่ตัวใบงาน (`run["parked"]`) ซึ่งต้อง
        ยังกั้นอยู่ — เทสนี้ตรวจทั้งสองฝั่ง
        """
        jobs = [
            {"item_id": "เจนเสร็จแล้ว", "stage": "failed",
             "parked": {"why": "ห้ามให้ตัวกวาดดึงกลับมาเจนซ้ำ"}},
            {"item_id": "เจนเสร็จแล้ว", "stage": "done", "parked": None},
            {"item_id": "ยังเจนไม่เสร็จ", "stage": "failed",
             "parked": {"why": "ห้ามให้ตัวกวาดดึงกลับมาเจนซ้ำ"}},
        ]

        class FakeQueue:
            def all(self):
                return jobs

        runs = [{"item_id": "เจนเสร็จแล้ว"}, {"item_id": "ยังเจนไม่เสร็จ"},
                {"item_id": "เจ้าของสั่งพัก", "parked": {"why": "กดพักจากแชท"}}]
        ready_rows = [{"item_id": row["item_id"]} for row in runs]

        with patch.object(clip_app, "clip_jobs", FakeQueue()),              patch.object(clip_app.clip_store, "list_runs", return_value=runs),              patch.object(clip_app.clip_store, "list_done", return_value=[]),              patch.object(clip_app.clip_store, "load_run",
                          side_effect=lambda _d, item: next(
                              (r for r in runs if r["item_id"] == item), {})),              patch.object(clip_app.publish_order, "ready_now",
                          return_value=ready_rows),              patch.object(clip_app.publish_stop, "first",
                          side_effect=lambda _d, _t, rows: rows):
            got = [str(row.get("item_id"))
                   for row in clip_app._auto_publish_ready("shopee_video")]

        self.assertIn("เจนเสร็จแล้ว", got,
                      "ใบที่เจนเสร็จแล้วต้องลงได้ ป้ายห้ามเจนซ้ำหมดหน้าที่ไปแล้ว")
        self.assertNotIn("ยังเจนไม่เสร็จ", got,
                         "ใบที่ยังเจนไม่เสร็จและถูกพัก ต้องยังถูกกั้นอยู่")
        self.assertNotIn("เจ้าของสั่งพัก", got,
                         "ใบที่เจ้าของสั่งพักที่ตัวใบงาน ต้องยังถูกกั้นอยู่")

    def test_tiktok_toggle_stays_on_when_link_batch_is_complete(self) -> None:
        with patch.object(clip_app, "_auto_tiktok_link_ready", return_value=[]):
            actual = clip_app._auto_toggle_state(
                {"tiktok_link": True, "facebook_post": True},
                "tiktok_publish", True,
            )
        self.assertTrue(actual["tiktok_publish"])
        self.assertFalse(actual["tiktok_link"])
        self.assertTrue(actual["facebook_post"])

    def test_tiktok_toggle_enables_link_first_when_items_still_wait(self) -> None:
        with patch.object(
            clip_app, "_auto_tiktok_link_ready",
            return_value=[{"item_id": "waiting"}],
        ):
            actual = clip_app._auto_toggle_state({}, "tiktok_publish", True)
        self.assertTrue(actual["tiktok_publish"])
        self.assertTrue(actual["tiktok_link"])
        self.assertFalse(actual["tiktok_post"])

        stopped = clip_app._auto_toggle_state(actual, "tiktok_publish", False)
        self.assertFalse(stopped["tiktok_publish"])
        self.assertFalse(stopped["tiktok_link"])

    def test_link_queue_excludes_parked_batch_member(self) -> None:
        rows = [
            {"item_id": "parked"},
            {"item_id": "next"},
        ]

        def load(_root, item_id):
            return ({"item_id": item_id, "parked": {"why": "รอแก้"}}
                    if item_id == "parked" else {"item_id": item_id})

        with (
            patch.object(clip_app, "_tiktok_link_batch_rows", return_value=rows),
            patch.object(clip_app.clip_store, "load_run", side_effect=load),
        ):
            actual = clip_app._auto_tiktok_link_ready()
        self.assertEqual([row["item_id"] for row in actual], ["next"])

    def test_legacy_matched_url_returns_to_showcase_queue(self) -> None:
        rows = [{"item_id": "legacy"}, {"item_id": "review"}]

        def load(_root, item_id):
            if item_id == "legacy":
                return {
                    "item_id": item_id,
                    "tiktok_product_url": "https://vt.tiktok.com/old/",
                    "tiktok_product_link": {
                        "status": "matched",
                        "url": "https://vt.tiktok.com/old/",
                    },
                }
            return {
                "item_id": item_id,
                "tiktok_product_link": {"status": "pending_review"},
            }

        with (
            patch.object(clip_app, "_tiktok_link_batch_rows", return_value=rows),
            patch.object(clip_app.clip_store, "load_run", side_effect=load),
        ):
            actual = clip_app._auto_tiktok_link_ready()
        self.assertEqual([row["item_id"] for row in actual], ["legacy"])

    def test_only_showcase_added_job_is_publishable(self) -> None:
        runs = [
            {
                "item_id": "ready",
                "video_check": {"ok": True},
                "tiktok_product_link": {
                    "status": "showcase_added", "showcase_added": True,
                    "confidence": "high",
                },
                "publish": {"tiktok": {"status": "pending"}},
            },
            {
                "item_id": "review",
                "video_check": {"ok": True},
                "tiktok_product_link": {"status": "pending_review"},
                "publish": {"tiktok": {"status": "pending"}},
            },
            {
                "item_id": "missing",
                "publish": {"tiktok": {"status": "pending"}},
            },
        ]
        rows = [{"item_id": run["item_id"]} for run in runs]
        with (
            patch.object(clip_app.clip_store, "list_runs", return_value=runs),
            patch.object(clip_app.clip_store, "list_done", return_value=[]),
            patch.object(clip_app.publish_order, "ready_now", return_value=rows),
            patch.object(clip_app.clip_jobs, "all", return_value=[]),
        ):
            actual = clip_app._auto_publish_ready("tiktok")
        self.assertEqual([row["item_id"] for row in actual], ["ready"])

    def test_rejects_showcase_job_when_video_check_failed_or_missing(self) -> None:
        runs = [
            {
                "item_id": "failed",
                "video_check": {"ok": False, "problems": ["คำพูดผิด"]},
                "tiktok_product_link": {
                    "status": "showcase_added", "showcase_added": True,
                    "confidence": "high",
                },
                "publish": {"tiktok": {"status": "pending"}},
            },
            {
                "item_id": "unchecked",
                "tiktok_product_link": {
                    "status": "showcase_added", "showcase_added": True,
                    "confidence": "high",
                },
                "publish": {"tiktok": {"status": "pending"}},
            },
        ]
        rows = [{"item_id": run["item_id"]} for run in runs]
        with (
            patch.object(clip_app.clip_store, "list_runs", return_value=runs),
            patch.object(clip_app.clip_store, "list_done", return_value=[]),
            patch.object(clip_app.publish_order, "ready_now", return_value=rows),
            patch.object(clip_app.clip_jobs, "all", return_value=[]),
        ):
            actual = clip_app._auto_publish_ready("tiktok")
        self.assertEqual(actual, [])

    def test_other_targets_are_not_affected(self) -> None:
        run = {
            "item_id": "facebook-ready",
            "publish": {"facebook_reels": {"status": "pending"}},
        }
        with (
            patch.object(clip_app.clip_store, "list_runs", return_value=[run]),
            patch.object(clip_app.clip_store, "list_done", return_value=[]),
            patch.object(
                clip_app.publish_order, "ready_now",
                return_value=[{"item_id": "facebook-ready"}],
            ),
            patch.object(clip_app.clip_jobs, "all", return_value=[]),
        ):
            actual = clip_app._auto_publish_ready("facebook_reels")
        self.assertEqual([row["item_id"] for row in actual], ["facebook-ready"])

    def test_duplicate_pending_rows_are_returned_only_once_for_every_target(self) -> None:
        for target in ("shopee_video", "facebook_reels", "tiktok"):
            with self.subTest(target=target):
                common = {
                    "item_id": "same-item",
                    "videos": ["one.mp4"],
                    "video_check": {"ok": True},
                    "tiktok_product_link": {
                        "status": "showcase_added", "showcase_added": True,
                        "confidence": "high",
                    },
                    "publish": {target: {"status": "pending"}},
                }
                copies = [common, dict(common)]
                rows = [{"item_id": "same-item"}, {"item_id": "same-item"}]
                with (
                    patch.object(clip_app.clip_store, "list_runs", return_value=copies),
                    patch.object(clip_app.clip_store, "list_done", return_value=[]),
                    patch.object(clip_app.clip_store, "load_run", return_value=copies[0]),
                    patch.object(clip_app.publish_order, "ready_now", return_value=rows),
                    patch.object(clip_app.publish_order, "check", return_value=(True, "พร้อม")),
                    patch.object(clip_app.clip_jobs, "all", return_value=[]),
                ):
                    actual = clip_app._auto_publish_ready(target)
                self.assertEqual([row["item_id"] for row in actual], ["same-item"])

    def test_any_posted_duplicate_vetoes_item_for_every_target(self) -> None:
        for target in ("shopee_video", "facebook_reels", "tiktok"):
            with self.subTest(target=target):
                pending = {
                    "item_id": "same-item",
                    "videos": ["one.mp4"],
                    "video_check": {"ok": True},
                    "tiktok_product_link": {
                        "status": "showcase_added", "showcase_added": True,
                        "confidence": "high",
                    },
                    "publish": {target: {"status": "pending"}},
                }
                posted = {
                    **pending,
                    "publish": {target: {"status": "posted"}},
                }
                with (
                    patch.object(
                        clip_app.clip_store, "list_runs",
                        return_value=[pending, posted],
                    ),
                    patch.object(clip_app.clip_store, "list_done", return_value=[]),
                    patch.object(
                        clip_app.publish_order, "ready_now",
                        return_value=[{"item_id": "same-item"}],
                    ),
                    patch.object(clip_app.clip_jobs, "all", return_value=[]),
                ):
                    actual = clip_app._auto_publish_ready(target)
                self.assertEqual(actual, [])

    def test_already_posted_409_is_not_treated_as_retryable_failure(self) -> None:
        for name in ("Shopee Video", "Facebook Reels", "TikTok"):
            with self.subTest(name=name):
                self.assertTrue(clip_app._already_posted_conflict(
                    409, f"{name} ลงไปแล้ว ไม่ต้องลงซ้ำ"))
        self.assertFalse(clip_app._already_posted_conflict(409, "ต้องลง Shopee ก่อน"))
        self.assertFalse(clip_app._already_posted_conflict(500, "ลงไปแล้ว"))

    def test_final_gate_finds_posted_copy_in_every_target_and_duplicate_folder(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for index, target in enumerate(
                ("shopee_video", "facebook_reels", "tiktok"), start=1
            ):
                item_id = f"item-{index}"
                stale = root / "shopee_products" / item_id
                posted = root / "clipsfb" / f"{item_id}-ซ้ำ-123"
                stale.mkdir(parents=True)
                posted.mkdir(parents=True)
                (stale / "run.json").write_text(json.dumps({
                    "item_id": item_id,
                    "publish": {target: {"status": "pending"}},
                }), encoding="utf-8")
                (posted / "run.json").write_text(json.dumps({
                    "item_id": item_id,
                    "publish": {target: {"status": "posted"}},
                }), encoding="utf-8")
                found = clip_app.clip_store.posted_copy(root, item_id, target)
                self.assertEqual(
                    ((found.get("publish") or {}).get(target) or {}).get("status"),
                    "posted",
                )

    def test_publish_gets_phone_before_next_product_link(self) -> None:
        calls: list[str] = []
        with (
            patch.object(
                clip_app, "_auto_on",
                return_value={"tiktok_link": True, "tiktok_publish": True},
            ),
            patch.object(clip_app, "_auto_publish_blocker", return_value=""),
            patch.object(
                clip_app, "_auto_publish_one",
                side_effect=lambda step: calls.append(step) or True,
            ),
            patch.object(
                clip_app, "_ensure_tiktok_link_worker",
                side_effect=lambda: calls.append("tiktok_link") or True,
            ),
        ):
            clip_app._auto_sweep()
        self.assertEqual(calls[:2], ["tiktok_publish", "tiktok_link"])

    def test_link_worker_yields_without_disabling_publish(self) -> None:
        states = iter([
            {"tiktok_link": True, "tiktok_publish": True},
            {"tiktok_link": True, "tiktok_publish": True},
            {"tiktok_link": False, "tiktok_publish": True},
        ])
        with (
            patch.object(clip_app, "_auto_on", side_effect=lambda: next(states)),
            patch.object(clip_app, "_auto_publish_ready", return_value=[{"item_id": "ready"}]),
            patch.object(clip_app, "_auto_tiktok_link_one") as link_one,
            patch.object(clip_app, "_set_auto_flags") as set_flags,
            patch.object(clip_app.time, "sleep", return_value=None),
        ):
            clip_app._tiktok_link_worker()
        link_one.assert_not_called()
        set_flags.assert_not_called()

    def test_link_item_error_parks_only_that_item_and_keeps_worker_on(self) -> None:
        response = urllib.error.HTTPError(
            "http://127.0.0.1/test", 400, "Bad Request", None,
            io.BytesIO(json.dumps({"detail": "หาปุ่มไม่พบ"}).encode("utf-8")),
        )
        old_next = clip_app._auto_link_next
        clip_app._auto_link_next = 0
        try:
            with (
                patch.object(
                    clip_app, "_auto_tiktok_link_device",
                    return_value=("W4FYYPYTLFYLIFHM", ""),
                ),
                patch.object(
                    clip_app, "_auto_tiktok_link_ready",
                    return_value=[{"item_id": "bad-item", "name": "สินค้าเทส"}],
                ),
                patch.object(
                    clip_app.urllib.request, "urlopen", side_effect=response,
                ),
                patch.object(clip_app, "_park_failed_tiktok", return_value=True) as park,
                patch.object(clip_app, "_set_auto_flags") as set_flags,
            ):
                actual = clip_app._auto_tiktok_link_one("tiktok_link")
            self.assertFalse(actual)
            park.assert_called_once()
            self.assertEqual(park.call_args.args[:2], ("bad-item", "สินค้าเทส"))
            set_flags.assert_not_called()
        finally:
            clip_app._auto_link_next = old_next


if __name__ == "__main__":
    unittest.main()
