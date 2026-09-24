"""A failed group post must not be reported complete by /followup."""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest


def followup_with(job, pending, resume):
    tree = ast.parse(Path(__file__).with_name("app.py").read_bytes())
    function = next(node for node in ast.walk(tree)
                    if isinstance(node, ast.FunctionDef) and node.name == "_fb_followup")
    calls = []

    def run_job(*args, **kwargs):
        calls.append((args, kwargs))
        return resume

    namespace = {
        "fb_jobs": SimpleNamespace(get=lambda _id: job, listing=lambda: [job]),
        "fb_auto_post": SimpleNamespace(STATUS_MANUAL_DONE="manual_done"),
        "_fb_cancel_followup_wait": lambda _id: None,
        "_fb_pending_groups": lambda _job: pending,
        "_fb_run_job": run_job,
        "_fb_gate": lambda *_args: ("serial", "internal followup gate"),
    }
    exec(compile(ast.Module(body=[function], type_ignores=[]), "app.py", "exec"),
         namespace)
    return namespace["_fb_followup"], calls


class FollowupMissingPostTests(unittest.TestCase):
    def setUp(self):
        self.job = {"id": "p234660098", "status": "failed", "manual_completed": False,
                    "results": [{"group_id": "329297298358942", "posted": False}]}

    def test_followup_resumes_only_missing_post_instead_of_claiming_complete(self):
        followup, calls = followup_with(self.job, ["329297298358942"], "")
        message = followup(job_id=self.job["id"], resume_missing_posts=True)
        self.assertIn("1 กลุ่ม", message)
        self.assertIn("โดยไม่โพสต์ซ้ำ", message)
        self.assertEqual([((self.job["id"],), {"queued": False, "resume": True})], calls)

    def test_busy_or_rejected_resume_is_reported_not_hidden(self):
        followup, calls = followup_with(self.job, ["329297298358942"], "มือถือไม่ว่าง")
        self.assertEqual("มือถือไม่ว่าง", followup(
            job_id=self.job["id"], resume_missing_posts=True))
        self.assertEqual(1, len(calls))

    def test_comment_override_does_not_silently_post_without_saved_comment(self):
        followup, calls = followup_with(self.job, ["329297298358942"], "")
        self.assertIn("กด Resume", followup(
            "ข้อความใหม่", self.job["id"], resume_missing_posts=True))
        self.assertEqual([], calls)

    def test_manually_completed_job_stays_closed(self):
        self.job["manual_completed"] = True
        followup, calls = followup_with(self.job, ["329297298358942"], "")
        self.assertIn("กดจบด้วยมือ", followup(
            job_id=self.job["id"], resume_missing_posts=True))
        self.assertEqual([], calls)

    def test_internal_pending_approval_scan_does_not_become_new_post(self):
        followup, calls = followup_with(self.job, ["329297298358942"], "")
        self.assertEqual("internal followup gate", followup(job_id=self.job["id"]))
        self.assertEqual([], calls)


if __name__ == "__main__":
    unittest.main()
