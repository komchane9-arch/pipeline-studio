"""ทดสอบปุ่มควบคุมสายโพสต์หน้า Group Facebook โดยไม่แตะมือถือจริง."""

from __future__ import annotations

import asyncio
import contextlib
import os
import tempfile
from pathlib import Path
from unittest import mock


TEST_ROOT = Path(tempfile.mkdtemp(prefix="pipeline-fb-controls-"))
os.environ["STUDIO_DATA_DIR"] = str(TEST_ROOT / "data")

import app  # noqa: E402
import fb_auto_post  # noqa: E402
import fb_pending  # noqa: E402


def check(ok: bool, message: str) -> None:
    if not ok:
        raise AssertionError(message)
    print("✅ " + message)


job = {
    "id": "p-controls",
    "groups": ["101", "202", "303"],
    "comments": ["คอมเมนต์บังคับ"],
    "results": [
        {"group_id": "101", "posted": True, "link": "https://example/101"},
        {"group_id": "202", "posted": False, "error": "ผู้ใช้สั่งหยุด"},
    ],
}
check(app._fb_pending_groups(job) == ["202", "303"], "Resume ข้ามกลุ่มที่โพสต์สำเร็จแล้ว")

merged = app._fb_merge_run_results(job, [
    {"group_id": "202", "posted": True, "liked": True},
    {"group_id": "303", "posted": False, "error": "เปิดกลุ่มไม่ได้"},
])
check([row["group_id"] for row in merged] == ["101", "202", "303"], "รวมผลตามลำดับกลุ่มเดิม")
check(merged[0]["posted"] is True and merged[0]["link"], "ผลสำเร็จเดิมไม่ถูกล้างตอน Resume")
check(merged[1]["posted"] is True, "ผลรอบ Resume ทับข้อผิดพลาดเดิมของกลุ่มเดียวกัน")
check("error" not in merged[1], "ผลสำเร็จรอบ Resume ล้างเหตุหยุดเก่าที่หมดความหมาย")

check(app._fb_auto_followup_enabled("redmi-test"),
      "รอบตามเก็บเป็นขั้นบังคับและสวิตช์เก่าปิดไม่ได้")
incomplete = {
    "id": "p-incomplete", "groups": ["101"], "comments": ["หนึ่ง"],
    "status": fb_auto_post.STATUS_DONE,
    "results": [{"group_id": "101", "posted": True}],
}
check(app._fb_pending_groups(incomplete) == [], "คิวโพสต์ว่างเมื่อโพสต์ขึ้นแล้ว")
check(app._fb_pending_followup_groups(incomplete) == ["101"],
      "คิวตามเก็บรับกลุ่มที่โพสต์แล้วแต่หลักฐานบังคับยังไม่ครบ")
check(app._fb_effective_status(incomplete) == fb_auto_post.STATUS_FINISHING,
      "งาน done รุ่นเก่าที่ไม่ครบถูกเปิดกลับเป็นคิวตามเก็บ")

stale_verify = {
    "id": "p-stale-verify", "groups": ["101"], "comments": ["หนึ่ง"],
    "status": fb_auto_post.STATUS_FINISHING,
    "results": [{
        "group_id": "101", "posted": True, "liked": True,
        "link": "https://example/101", "commented": True,
        "comment_liked": True, "comment_count": 1,
        "verified": {"comments_seen": 0},
    }],
}
followup_entry = app._fb_normalize_followup_result(stale_verify, {
    "group_id": "101", "posted": True, "liked": True,
    "link": "https://example/101", "commented": True,
    "comment_liked": True, "comment_count": 1,
})
check(followup_entry["verified"]["comments_seen"] == 1,
      "หลักฐานรอบตามเก็บอัปเดตค่าตรวจซ้ำเก่าที่อ่านคอมเมนต์ได้ศูนย์")
stale_verify["results"] = [
    app._fb_merge_run_results(stale_verify, [followup_entry])[0]
]
check(app._fb_job_complete(stale_verify),
      "งานปิดครบได้หลังรอบตามเก็บยืนยันว่าคอมเมนต์มีอยู่แล้ว")
complete = {
    **incomplete,
    "results": [{"group_id": "101", "posted": True, "link": "https://example/101",
                 "liked": True, "commented": True, "comment_count": 1,
                 "comment_liked": True}],
}
check(app._fb_job_complete(complete), "done ได้เมื่อหลักฐานบังคับครบทั้งสี่ชนิด")
verified_missing = {
    **complete,
    "results": [{**complete["results"][0],
                 "verified": {"comments_seen": 0}}],
}
check(not app._fb_job_complete(verified_missing),
      "ผลตรวจจริงว่าคอมเมนต์หายต้องชนะค่าความสำเร็จเก่าที่เคยสะสมไว้")
check(not fb_pending.is_stuck(complete["results"][0], 1),
      "ตัวไล่อัตโนมัติหยุดเมื่อขั้นบังคับครบ")
check(fb_pending.is_stuck({**complete["results"][0], "comment_liked": False}, 1),
      "ตัวไล่อัตโนมัติตามต่อเมื่อยังไม่ได้ไลก์คอมเมนต์")

jobs = fb_auto_post.JobStore(TEST_ROOT / "jobs.json")
saved = jobs.add(
    id="p-web-control", caption="ทดสอบ", image="unused.jpg",
    groups=["101", "202"], status=fb_auto_post.STATUS_STOPPED,
    comments=["คอมเมนต์บังคับ"],
    results=[{"group_id": "101", "posted": True}], source="web",
)

fake_runner = mock.MagicMock()
fake_runner.job_running.return_value = ""
fake_runner.running.return_value = {}
with (
    mock.patch.object(app, "fb_jobs", jobs),
    mock.patch.object(app, "fb_runner", fake_runner),
    mock.patch.object(app, "_account_of_job", return_value="Test Account"),
    mock.patch.object(app, "_job_ctx", side_effect=lambda _job_id: contextlib.nullcontext()),
    mock.patch.object(app, "_fb_run_job", return_value="") as run_job,
):
    response = asyncio.run(app.fb_resume(saved["id"]))
    check(response["ok"] is True, "endpoint Resume รับงานที่หยุดไว้")
    run_job.assert_called_once_with(saved["id"], False, True)

followup_only = jobs.add(
    id="p-followup-only", caption="ทดสอบ", image="unused.jpg",
    groups=["101"], comments=["คอมเมนต์บังคับ"],
    status=fb_auto_post.STATUS_FINISHING,
    results=[{"group_id": "101", "posted": True}], source="web",
)
with (
    mock.patch.object(app, "fb_jobs", jobs),
    mock.patch.object(app, "fb_runner", fake_runner),
    mock.patch.object(app, "_account_of_job", return_value="Test Account"),
    mock.patch.object(app, "_job_ctx", side_effect=lambda _job_id: contextlib.nullcontext()),
    mock.patch.object(app, "_fb_followup", return_value="🔁 เริ่มตามเก็บ 1 กลุ่ม") as followup,
):
    response = asyncio.run(app.fb_resume(followup_only["id"]))
    check(response["ok"] is True, "Resume รับคิวตามเก็บอย่างเดียว")
    followup.assert_called_once_with("", followup_only["id"])

with (
    mock.patch.object(app, "fb_jobs", jobs),
    mock.patch.object(app, "fb_runner", fake_runner),
    mock.patch.object(app, "_job_ctx", side_effect=lambda _job_id: contextlib.nullcontext()),
    mock.patch.object(app, "_web_account", return_value="Test Account"),
    mock.patch.object(app.fb_groups, "label", side_effect=lambda group_id: f"กลุ่ม {group_id}"),
):
    response = asyncio.run(app.fb_reset(saved["id"]))
    check(response["ok"] is True, "endpoint Reset ตอบสำเร็จตอนมือถือว่าง")
    check(jobs.get(saved["id"])["ui_reset"] is True, "Reset ล้างเฉพาะกล่องสถานะ")
    check(jobs.get(saved["id"])["results"][0]["posted"] is True, "Reset ไม่ลบผลโพสต์เดิม")
    payload = asyncio.run(app.fb_list_jobs())
    check(not payload["control_job"] or payload["control_job"]["id"] != saved["id"],
          "Reset ซ่อนใบที่สั่ง Reset โดยไม่ซ่อนงานค้างใบอื่น")

manual = jobs.add(
    id="p-manual-done", caption="ตรวจเองแล้ว", image="unused.jpg",
    groups=["101"], comments=["คอมเมนต์บังคับ"],
    status=fb_auto_post.STATUS_FINISHING,
    results=[{"group_id": "101", "posted": True}], source="web",
)
fake_runner.job_running.return_value = ""
fake_runner.stop_job.return_value = ""
with (
    mock.patch.object(app, "fb_jobs", jobs),
    mock.patch.object(app, "fb_runner", fake_runner),
    mock.patch.object(app, "_job_ctx", side_effect=lambda _job_id: contextlib.nullcontext()),
):
    response = asyncio.run(app.fb_complete(manual["id"]))
    finished = jobs.get(manual["id"])
    check(response["ok"] is True, "endpoint จบงานแบบ Manual ตอบสำเร็จ")
    check(finished["status"] == fb_auto_post.STATUS_MANUAL_DONE,
          "จบงานด้วยมือมีสถานะปลายทางแยกจาก Stop และ Cancel")
    check(finished["manual_completed"] is True and finished["finished_at"],
          "จบงานด้วยมือบันทึกคำตัดสินและเวลาจบถาวร")
    check(finished["results"][0]["posted"] is True,
          "จบงานด้วยมือไม่ลบผลที่ทำสำเร็จแล้ว")
    check(app._fb_effective_status(finished) == fb_auto_post.STATUS_MANUAL_DONE,
          "งานจบด้วยมือไม่ถูกเปิดกลับเป็นคิวตามเก็บแม้หลักฐานยังไม่ครบ")
    with (mock.patch.object(jobs, "listing", return_value=[finished]),
          mock.patch.object(app.fb_groups, "label", return_value="กลุ่ม 101")):
        live = app._fb_jobs_live_body(0, "Test Account")["jobs"][0]
    check(live["pending"] == 0 and live["pending_followup"] == 0,
          "งานจบด้วยมือไม่แสดงยอดค้างจากหลักฐานเดิม")
    check(live["queue"][0]["state"] == "manual"
          and live["queue"][0]["accepted_missing"],
          "หลักฐานที่ขาดยังอยู่ แต่แสดงเป็นผู้ใช้รับรองจบแทนรอตามเก็บ")
    pending = fb_pending.pending_items([finished], state={})
    check(bool(pending) and pending[0]["status"] == "skipped",
          "ตัวไล่โพสต์รออนุมัติข้ามงานที่จบด้วยมือ")
    try:
        asyncio.run(app.fb_resume(manual["id"]))
    except Exception as error:
        check(getattr(error, "status_code", 0) == 409,
              "Resume ถูกปฏิเสธหลังผู้ใช้กดจบงาน")
    else:
        raise AssertionError("Resume ต้องไม่เปิดงานที่จบด้วยมือกลับมาทำ")

running_manual = jobs.add(
    id="p-manual-running", caption="กำลังทำ", image="unused.jpg",
    groups=["101"], comments=["คอมเมนต์บังคับ"],
    status=fb_auto_post.STATUS_RUNNING, results=[], source="web",
)
fake_runner.reset_mock()
fake_runner.job_running.return_value = "redmi-test"
fake_runner.stop_job.return_value = "redmi-test"
with (
    mock.patch.object(app, "fb_jobs", jobs),
    mock.patch.object(app, "fb_runner", fake_runner),
    mock.patch.object(app, "_job_ctx", side_effect=lambda _job_id: contextlib.nullcontext()),
):
    response = asyncio.run(app.fb_complete(running_manual["id"]))
    check(response["stopping"] is True,
          "กดจบระหว่างทำงานแจ้งว่ากำลังหยุดที่จุดปลอดภัย")
    fake_runner.stop_job.assert_called_once_with(running_manual["id"])
    check(jobs.get(running_manual["id"])["status"] == fb_auto_post.STATUS_MANUAL_DONE,
          "ผลจาก worker ไม่มีสิทธิ์เปิดงานที่กดจบกลับขึ้นมา")

fake_runner.job_running.return_value = "redmi-test"
fake_runner.stop_job.return_value = "redmi-test"
with (
    mock.patch.object(app, "fb_jobs", jobs),
    mock.patch.object(app, "fb_runner", fake_runner),
    mock.patch.object(app, "_job_ctx", side_effect=lambda _job_id: contextlib.nullcontext()),
):
    response = asyncio.run(app.fb_stop(saved["id"]))
    check(response["ok"] is True, "endpoint Stop รับคำสั่งระหว่างงานรัน")
    check(jobs.get(saved["id"])["status"] == fb_auto_post.STATUS_STOPPED, "Stop เก็บสถานะให้ Resume ต่อได้")
    check(jobs.get(saved["id"])["results"][0]["posted"] is True, "Stop ไม่ลบผลกลุ่มที่ทำเสร็จแล้ว")
    fake_runner.stop_job.assert_called_with(saved["id"])

print("\nทดสอบปุ่ม Group Facebook ผ่านทั้งหมด")
