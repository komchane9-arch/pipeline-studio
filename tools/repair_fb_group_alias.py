"""Replace an unsafe Facebook vanity group id with its verified numeric id.

Uses the same locked/atomic stores as the running service so the repair cannot
leave half-written JSON when Google Drive is syncing concurrently.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import fb_auto_post  # noqa: E402
import studio_shared  # noqa: E402


def _replace_exact(value, old: str, new: str) -> tuple[object, int]:
    if isinstance(value, str):
        return (new, 1) if value == old else (value, 0)
    if isinstance(value, list):
        changed = 0
        output = []
        for item in value:
            fixed, count = _replace_exact(item, old, new)
            output.append(fixed)
            changed += count
        return output, changed
    if isinstance(value, dict):
        changed = 0
        output = {}
        for key, item in value.items():
            fixed, count = _replace_exact(item, old, new)
            output[key] = fixed
            changed += count
        return output, changed
    return value, 0


def repair(account: str, old: str, new: str) -> dict:
    if not account.strip() or not old.strip():
        raise ValueError("account and old id are required")
    if not new.isdigit() or len(new) < 6:
        raise ValueError("new group id must be a numeric Facebook group id")

    with fb_auto_post.use_account(account):
        groups = fb_auto_post.GroupStore(
            lambda: studio_shared.account_file(
                fb_auto_post.posting_account(), "fb_groups.json"))
        jobs = fb_auto_post.JobStore(
            lambda: studio_shared.account_file(
                fb_auto_post.posting_account(), "fb_jobs.json"))

        with groups.store.lock:
            rows = groups.store._read()
            if any(row.get("group_id") == new for row in rows):
                rows = [row for row in rows if row.get("group_id") != old]
                group_changes = 1
            else:
                group_changes = 0
                for row in rows:
                    if row.get("group_id") == old:
                        row["group_id"] = new
                        group_changes += 1
            if group_changes:
                groups.store._write(rows)

        with jobs.store.lock:
            rows = jobs.store._read()
            fixed_rows, job_changes = _replace_exact(rows, old, new)
            if job_changes:
                jobs.store._write(fixed_rows)

    return {
        "account": account,
        "old": old,
        "new": new,
        "group_changes": group_changes,
        "job_changes": job_changes,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("account")
    parser.add_argument("old")
    parser.add_argument("new")
    args = parser.parse_args()
    print(repair(args.account, args.old, args.new))


if __name__ == "__main__":
    main()
