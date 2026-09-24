"""Periodically verify Bot8's Facebook session while its Chrome profile is idle."""

import time

import bot_profiles
import evidence
import fb_collect_gate
import fb_mass_finder
import studio_shared


CHECK_INTERVAL_SECONDS = 5 * 60


def check_once() -> dict:
    """Check the live Facebook page; never infer a valid session from saved files."""
    farm = bot_profiles.ProfileFarm(studio_shared.DATA_DIR)
    profile = next(
        (item for item in farm.list_profiles(fresh=True)["profiles"]
         if item.get("name", "").casefold() == "bot8"), None)
    if profile is None:
        return {"status": "missing", "note": "ไม่พบโปรไฟล์ Bot8"}
    if profile["running"]:
        return {"status": "busy"}

    try:
        with studio_shared.bot_lock(
                profile["id"], timeout=0, label="ตรวจล็อกอิน Facebook Bot8"):
            # Recheck after acquiring the shared lock. A worker might have
            # started between the first process scan and this point.
            if any(item["id"] == profile["id"] and item["running"]
                   for item in farm.list_profiles(fresh=True)["profiles"]):
                return {"status": "busy"}
            from playwright.sync_api import sync_playwright

            with sync_playwright() as playwright:
                browser = fb_mass_finder._open_persistent(playwright, farm, profile)
                try:
                    page = browser.pages[0] if browser.pages else browser.new_page()
                    try:
                        fb_mass_finder.ensure_logged_in(page, browser)
                    except fb_mass_finder.MassFinderError as error:
                        # Capture the actual login/checkpoint screen before closing Chrome.
                        evidence.capture("Bot8 หลุดล็อกอิน Facebook", tag="bot8",
                                         page=page, note=str(error))
                        before = fb_collect_gate.state().get("needs_login", False)
                        fb_collect_gate.update(
                            needs_login=True, note=str(error),
                            updated_at=time.time(), login_checked_at=time.time(),
                            login_probe="logged_out", login_probe_error="")
                        return {"status": "logged_out", "changed": not before}
                    before = fb_collect_gate.state().get("needs_login", False)
                    fb_collect_gate.update(
                        needs_login=False, failures=0, retry_at=0, note="",
                        login_checked_at=time.time(), login_probe="ok",
                        login_probe_error="")
                    return {"status": "ok", "changed": bool(before)}
                finally:
                    browser.close()
    except studio_shared.BotBusy:
        return {"status": "busy"}
    except Exception as error:
        # Network/browser failures do not prove the session is logged out.
        fb_collect_gate.update(login_probe="unknown",
                               login_checked_at=time.time(),
                               login_probe_error=f"{type(error).__name__}: {error}"[:160])
        return {"status": "unknown", "note": str(error)[:160]}


def watch(log) -> None:
    time.sleep(45)
    while True:
        try:
            result = check_once()
            if result.get("changed"):
                log("Bot8 Facebook ต้องล็อกอินใหม่" if result["status"] == "logged_out"
                    else "Bot8 Facebook กลับมาล็อกอินแล้ว")
            elif result["status"] in {"missing", "unknown"}:
                log("ตรวจล็อกอิน Bot8 ไม่สำเร็จ: " + result.get("note", result["status"]))
        except Exception as error:
            log(f"ตัวตรวจล็อกอิน Bot8 สะดุด: {type(error).__name__}: {error}")
        time.sleep(CHECK_INTERVAL_SECONDS)
