"""Run one read-only Bot8 popular-post report from the Studio queue."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import shutil
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import bot8_mass_report as jobs
from tools.bot8_today_report import sale_reason, save_report, score

TZ = timezone(timedelta(hours=7))


def linked_groups() -> list[dict]:
    """Read the currently linked groups of every enabled Facebook account."""
    import fb_auto_post as auto
    import fb_engagement

    groups: dict[str, dict] = {}
    accounts = fb_engagement.watched_accounts()
    if not accounts:
        raise RuntimeError("ไม่มีบัญชี Facebook สายโพสต์ที่เปิดใช้อยู่")
    for account in accounts:
        with auto.use_account(account):
            for row in auto.GroupStore(auto.state_file("fb_groups.json")).listing():
                gid = str(row.get("group_id") or "").strip()
                if not gid:
                    continue
                group = groups.setdefault(gid, {
                    "id": gid, "name": str(row.get("name") or f"กลุ่ม {gid}"),
                    "accounts": [],
                })
                if account not in group["accounts"]:
                    group["accounts"].append(account)
    if not groups:
        raise RuntimeError("บัญชีที่เปิดใช้อยู่ยังไม่ผูกกลุ่ม Facebook")
    return list(groups.values())


def qualifying_posts(posts: list[dict], group_id: str) -> list[dict]:
    """Sales posts with explicit offer evidence, strictly >100, any date."""
    result = []
    seen = set()
    for post in posts:
        url = str(post.get("url") or "")
        pid = str(post.get("id") or "")
        if not pid or not url.startswith(f"https://www.facebook.com/groups/{group_id}/"):
            continue
        reason = sale_reason(post)
        if score(post) <= 100 or not reason or pid in seen or url in seen:
            continue
        post["total_engagement"] = score(post)
        post["sales_reason"] = reason
        seen.update((pid, url))
        result.append(post)
    return sorted(result, key=lambda row: -row["total_engagement"])


def run(job_id: str, scrolls: int) -> Path:
    import evidence
    import fb_mass_finder as finder
    import studio_shared as shared
    from bot_profiles import ProfileFarm
    from playwright.sync_api import sync_playwright

    job = jobs.job_status()
    if job.get("id") != job_id or job.get("status") != "running":
        raise RuntimeError("งานนี้ไม่ได้ถือคิว Bot8 — ไม่เปิด Chrome")
    groups = linked_groups()
    stamp = datetime.now(TZ).strftime("%Y%m%d-%H%M%S")
    report_id = f"bot8-mass-sales-{stamp}-{job_id}"
    folder = shared.DATA_DIR / "reports" / report_id
    state = {"date": datetime.now(TZ).date().isoformat(), "mode": "sales",
             "status": "เริ่มอ่านกลุ่ม", "groups": [], "scope": groups,
             "started_at": datetime.now(TZ).isoformat(timespec="seconds")}
    save_report(folder, state)
    jobs.update_job(job_id, report_id=report_id, total=len(groups),
                    current_action=f"เตรียมอ่าน {len(groups)} กลุ่ม")
    last_beat = 0.0

    def log(message: str) -> None:
        nonlocal last_beat
        line = datetime.now(TZ).isoformat() + " " + message
        print(line, flush=True)
        with (folder / "progress.log").open("a", encoding="utf-8") as out:
            out.write(line + "\n")
        if time.monotonic() - last_beat > 10:
            jobs.update_job(job_id)
            last_beat = time.monotonic()

    try:
        farm = ProfileFarm(shared.DATA_DIR)
        entry = finder.find_bot(farm, "Bot8")
        with sync_playwright() as playwright:
            context = finder.launch_bot_browser(playwright, farm, entry)
            try:
                page = context.pages[0] if context.pages else context.new_page()
                try:
                    finder.ensure_logged_in(page, context)
                except Exception as exc:
                    evidence.capture("Bot8-โพสต์แมส-ล็อกอินไม่ผ่าน", tag="bot8",
                                     page=page, note=str(exc))
                    raise
                for index, group in enumerate(groups):
                    if index:
                        state["status"] = "พัก 60 วินาทีก่อนกลุ่มถัดไป"
                        jobs.update_job(job_id, current_action=state["status"])
                        save_report(folder, state)
                        for _ in range(6):
                            time.sleep(10)
                            jobs.update_job(job_id)
                    name = group["name"]
                    state["status"] = f"กำลังอ่าน {name}"
                    record = {**group, "scanned": 0, "eligible_count": 0,
                              "selected": [], "error": ""}
                    state["groups"].append(record)
                    jobs.update_job(job_id, current_group=name,
                                    current_action=state["status"])
                    save_report(folder, state)
                    log(state["status"])
                    try:
                        result = finder.scan_group(
                            page, f"https://www.facebook.com/groups/{group['id']}/",
                            scrolls, log)
                        posts = result["posts"]
                        ranked = qualifying_posts(posts, group["id"])
                        record.update(scanned=len(posts), eligible_count=len(ranked),
                                      error=result.get("error", ""))
                        for post in ranked:
                            if len(record["selected"]) >= 5:
                                break
                            try:
                                jobs.update_job(job_id)
                                page.goto(post["url"], wait_until="domcontentloaded",
                                          timeout=60000)
                                page.wait_for_timeout(4000)
                                if str(post["id"]) not in page.url or any(
                                        word in page.url for word in ("login", "checkpoint")):
                                    raise RuntimeError("หน้าโพสต์ไม่ตรงลิงก์หรือหลุดล็อกอิน")
                                shot = evidence.capture(
                                    f"โพสต์แมส-{group['id']}-{post['id']}", tag="bot8",
                                    page=page, note=json.dumps(post, ensure_ascii=False))
                                if not shot or not shot.with_suffix(".png").is_file():
                                    raise RuntimeError("ไม่มีภาพหน้าจอโพสต์")
                                image = f"{group['id']}-{post['id']}.png"
                                shutil.copy2(shot.with_suffix(".png"), folder / image)
                                post["image"] = image
                                post["capture_note"] = "เปิดลิงก์โพสต์จริงและเก็บภาพแล้ว"
                                record["selected"].append(post)
                                save_report(folder, state)
                                jobs.update_job(job_id, found=sum(
                                    len(item["selected"]) for item in state["groups"]))
                            except Exception as exc:
                                evidence.capture(
                                    f"Bot8-โพสต์แมส-แคปไม่สำเร็จ-{group['id']}",
                                    tag="bot8", page=page,
                                    note=f"{post['url']} · {type(exc).__name__}: {exc}")
                                log(f"ข้ามโพสต์ที่ยืนยันภาพไม่ได้: {post['url']} · {exc}")
                    except Exception as exc:
                        record["error"] = f"{type(exc).__name__}: {exc}"
                        evidence.capture(f"Bot8-อ่านกลุ่มโพสต์แมสไม่สำเร็จ-{group['id']}",
                                         tag="bot8", page=page, note=record["error"])
                        log(record["error"])
                    done = index + 1
                    found = sum(len(item["selected"]) for item in state["groups"])
                    jobs.update_job(job_id, completed=done, found=found,
                                    current_action=f"ตรวจแล้ว {done}/{len(groups)} กลุ่ม · ได้ {found} โพสต์")
                    log(f"เสร็จ {done}/{len(groups)}: {name} ได้ {len(record['selected'])}/5")
                    save_report(folder, state)
            finally:
                context.close()
        errors = sum(bool(group.get("error")) for group in state["groups"])
        found = sum(len(group["selected"]) for group in state["groups"])
        state["status"] = f"จบแล้ว · ได้ {found} โพสต์จาก {len(groups)} กลุ่ม" + (
            f" · มี {errors} กลุ่มที่อ่านไม่สำเร็จ" if errors else "")
        state["finished_at"] = datetime.now(TZ).isoformat(timespec="seconds")
        save_report(folder, state)
        jobs.update_job(job_id, status="complete", completed=len(groups), found=found,
                        current_group="", current_action=state["status"],
                        finished_at=state["finished_at"], error="")
        return folder
    except Exception as exc:
        reason = f"{type(exc).__name__}: {exc}"
        state["status"] = "หยุด: " + reason
        save_report(folder, state)
        jobs.update_job(job_id, status="error", error=reason,
                        current_action=state["status"],
                        finished_at=datetime.now(TZ).isoformat(timespec="seconds"))
        raise


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser()
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--scrolls", type=int, default=60)
    options = parser.parse_args()
    if not 1 <= options.scrolls <= 100:
        raise ValueError("scrolls ต้องอยู่ระหว่าง 1 ถึง 100")
    print("REPORT " + str(run(options.job_id, options.scrolls)), flush=True)


if __name__ == "__main__":
    main()
