"""Clone one Facebook job into a one-group retry without touching its history."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import fb_auto_post  # noqa: E402
import studio_shared  # noqa: E402


def clone_one_group(
    account: str,
    job_id: str,
    group_id: str,
    image_override: str = "",
) -> dict:
    with fb_auto_post.use_account(account):
        jobs = fb_auto_post.JobStore(
            lambda: studio_shared.account_file(
                fb_auto_post.posting_account(), "fb_jobs.json"))
        groups = fb_auto_post.GroupStore(
            lambda: studio_shared.account_file(
                fb_auto_post.posting_account(), "fb_groups.json"))
        source = jobs.get(job_id)
        if source is None:
            raise ValueError(f"job {job_id} was not found in {account}")
        if groups.get(group_id) is None:
            raise ValueError(f"group {group_id} is not registered in {account}")
        images = [image_override] if image_override else [
            str(path) for path in (source.get("images") or []) if path
        ]
        if not images and source.get("image"):
            images = [str(source["image"])]
        missing = [path for path in images if not Path(path).is_file()]
        if not images or missing:
            raise ValueError(f"post image is missing: {missing or '(no image)'}")

        retry = jobs.add(
            caption=str(source.get("caption") or ""),
            comment=str(source.get("comment") or ""),
            comments=list(source.get("comments") or []),
            comment_images=list(source.get("comment_images") or []),
            image=images[0],
            images=images,
            groups=[group_id],
            set="",
            status=fb_auto_post.STATUS_READY,
            source=f"retry:{job_id}",
            chat_id=str(source.get("chat_id") or ""),
            message_id=0,
            media_group="",
            retry_of=job_id,
        )
        jobs.append_log(
            retry["id"],
            f"สร้างจาก {job_id} เพื่อโพสต์ใหม่เฉพาะกลุ่ม {group_id}",
        )
        return retry


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("account")
    parser.add_argument("job_id")
    parser.add_argument("group_id")
    parser.add_argument(
        "--image",
        default="",
        help="replacement image path when the source job image was cleaned up",
    )
    args = parser.parse_args()
    retry = clone_one_group(
        args.account,
        args.job_id,
        args.group_id,
        image_override=args.image,
    )
    print(retry["id"])


if __name__ == "__main__":
    main()
