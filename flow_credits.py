"""เครดิต Flow ที่เหลือ **แยกรายโครม** — จดไว้ อ่านใหม่ได้ และไม่เดาเมื่ออ่านไม่ได้

**เจ้าของสั่ง 11 ก.ย. 2569** — *"ให้โชว์เครดิตที่เหลืออยู่ของแต่ละโครมด้วย
โดยเมื่อปิดโครมให้บันทึกเครดิตล่าสุดที่เหลืออยู่ แล้วมีปุ่มกด refresh
โดยกดปุ้บจะเปิด chrome เพื่อเช็คเครดิตแล้วอัพเดตทั้งหมดแต่ละโครม"*

---

## ทำไมต้องแยกรายโครม

ของเดิมเก็บเครดิตค่าเดียวใน `config.json` (`flow_credits_last`) ซึ่งเป็นของ
**บัญชีที่ใช้ล่าสุด** เท่านั้น พอสลับบัญชีตอนเครดิตหมด เลขเดิมก็ใช้ไม่ได้แล้ว
และไม่มีทางรู้ว่าบัญชีอื่นเหลือเท่าไรโดยไม่เปิดดูทีละอัน

ตอนนี้มีโปรไฟล์ 6-7 บัญชีสำหรับสลับ — ต้องเห็นทั้งแถวว่าใครเหลือเท่าไร
ถึงจะเลือกได้ว่ารอบหน้าใช้บัญชีไหน

## กติกาที่ยึด

**อ่านไม่ได้ ≠ เหลือศูนย์** (กติกาข้อ 2.3.1 ข้อ 4) — ค่านี้เอาไปตัดสินว่าจะ
สลับบัญชีไหม ถ้าเดาเป็น 0 ตอนอ่านไม่ออก ระบบจะสลับหนีบัญชีที่ยังมีเครดิตเต็ม
เก็บเป็น `None` แล้วแสดงว่า "ยังไม่เคยวัด" ต่างหากจาก "วัดแล้วเหลือ 0"

**จดเวลาที่วัดไว้ด้วยเสมอ** — เครดิตเปลี่ยนทุกครั้งที่เจนคลิป เลขเมื่อวานกับ
เลขเมื่อครู่มีค่าไม่เท่ากัน คนอ่านต้องรู้ว่าเลขนี้เก่าแค่ไหน
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import studio_shared as shared

CREDITS_FILE = shared.DATA_DIR / "flow_credits.json"

# หนึ่งคลิปกินราว 15 หน่วย — ใช้แปลงเป็น "เจนได้อีกกี่คลิป" ให้คนอ่านเข้าใจ
CREDITS_PER_CLIP = 15


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def PROFILES_ROOT() -> Path:
    """โฟลเดอร์แม่ของโปรไฟล์รายบัญชี — ให้ผู้เรียกต่อชื่อโปรไฟล์เอาเอง

    เป็นฟังก์ชันไม่ใช่ค่าคงที่ เพราะ `flow_accounts` ตั้งค่านี้จาก DATA_DIR
    ซึ่งเปลี่ยนได้ตอนรันด้วย STUDIO_DATA_DIR (ใช้ตอนทดสอบ ห้ามแตะ data จริง)
    """
    try:
        import flow_accounts
        folder = getattr(flow_accounts, "PROFILES_DIR", None)
        if folder:
            return Path(folder)
    except Exception:                                          # noqa: BLE001
        pass
    return shared.DATA_DIR / "flow_profiles"


def load() -> dict:
    try:
        data = json.loads(CREDITS_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save(profile: str, credits: int | None, account: str = "",
         note: str = "") -> None:
    """จดเครดิตของโปรไฟล์หนึ่ง — `credits=None` แปลว่า **อ่านไม่ได้** ไม่ใช่ศูนย์"""
    def change(data: dict) -> dict:
        if not isinstance(data, dict):
            data = {}
        old = data.get(str(profile)) or {}
        row = {
            "profile": str(profile),
            "account": str(account or old.get("account") or ""),
            "checked_at": _now(),
            "note": str(note or ""),
        }
        if credits is None:
            # เก็บเลขเดิมไว้ให้ดูได้ แต่ติดธงว่ารอบนี้อ่านไม่ได้
            row["credits"] = old.get("credits")
            row["stale"] = True
            row["last_ok_at"] = old.get("last_ok_at") or old.get("checked_at") or ""
        else:
            row["credits"] = int(credits)
            row["stale"] = False
            row["last_ok_at"] = row["checked_at"]
        data[str(profile)] = row
        return data

    shared.update_json(CREDITS_FILE, change, default={},
                       label=f"จดเครดิต Flow ของ {profile}")


def rows() -> list[dict]:
    """ทุกโปรไฟล์ที่สายคลิปใช้ พร้อมเครดิตล่าสุดที่รู้ — เรียงเครดิตมากไปน้อย

    โปรไฟล์ที่ยังไม่เคยวัดก็ต้องอยู่ในรายการ **ไม่ใช่หายไปเฉยๆ** ไม่งั้น
    คนอ่านจะนึกว่าไม่มีบัญชีนั้น
    """
    import chrome_view

    known = load()
    out = []
    for folder, label, account in _profiles():
        row = dict(known.get(folder.name) or {})
        credits = row.get("credits")
        out.append({
            "profile": folder.name,
            "label": label,
            "account": account or row.get("account") or "",
            "credits": credits,
            "clips_left": (int(credits) // CREDITS_PER_CLIP
                           if isinstance(credits, int) else None),
            "checked_at": row.get("checked_at") or "",
            "stale": bool(row.get("stale")),
            "running": chrome_view.profile_running(folder),
        })
    out.sort(key=lambda r: (-1 if r["credits"] is None else -int(r["credits"]),
                            r["profile"]))
    return out


def _profiles() -> list[tuple[Path, str, str]]:
    """โปรไฟล์ Chrome ทั้งหมดที่สายเจนคลิปใช้ — (โฟลเดอร์, ชื่อที่โชว์, อีเมล)"""
    found: list[tuple[Path, str, str]] = []
    seen: set[str] = set()

    def add(folder: Path | None, label: str, account: str = "") -> None:
        if folder is None:
            return
        key = str(folder).casefold()
        if key in seen:
            return
        seen.add(key)
        found.append((Path(folder), label, account))

    emails: dict[str, str] = {}
    try:
        import flow_accounts
        # ของเดิมวนบน board() ซึ่งคืน dict ไม่ใช่รายการแถว การวนจึงได้ชื่อคีย์
        # เป็นข้อความ แล้ว .get พัง — และ except ข้างในกลืนเงียบ ผลคือแผง
        # **ตกไปใช้อีเมลที่จำไว้เก่า** โดยไม่มีใครรู้ว่าตัวอ่านสดไม่เคยทำงานเลย
        # (เจอ 13 ก.ย. 2569 หลังเปลี่ยนชื่อโฟลเดอร์ให้ตรงอีเมล แล้วคอลัมน์
        # อีเมลยังขึ้นของเก่าทั้งแถว)
        for mail in flow_accounts.emails():
            emails[Path(flow_accounts.profile_dir_of(mail)).name] = mail
        base = getattr(flow_accounts, "PROFILES_DIR", None)
        if base and Path(base).is_dir():
            for item in sorted(Path(base).iterdir()):
                if item.is_dir():
                    add(item, item.name, emails.get(item.name, ""))
    except Exception as error:                                 # noqa: BLE001
        # ห้ามเงียบ — ไม่รู้ว่าบัญชีไหนคู่กับโฟลเดอร์ไหน คือเรื่องใหญ่
        print(f"[เครดิต Flow] อ่านทะเบียนบัญชีไม่ได้: "
              f"{type(error).__name__}: {error}")

    # ช่องเจนคลิปที่อาจไม่ได้อยู่ในโฟลเดอร์รายบัญชี
    try:
        import flow_worker
        for number in (2, 1):
            try:
                seat = flow_worker.flow_seat(number)
            except Exception:                                  # noqa: BLE001
                continue
            add(seat.get("dir"), f"ช่อง {number}")
    except Exception:                                          # noqa: BLE001
        pass
    return found


def read_now(profile: str | Path, log=print) -> dict:
    """เปิดโปรไฟล์นี้แล้วอ่านเครดิตจาก Flow จริง แล้วจดไว้

    **เปิดแบบซ่อน** ไม่ให้ไปแย่งจอที่เจ้าของกำลังใช้ และถือ browser lock
    ตลอดเพื่อไม่ให้ worker เปิด user-data-dir เดียวกันซ้อนจนโปรไฟล์เสีย
    """
    from playwright.sync_api import sync_playwright

    import flow_driver
    import flow_worker

    folder = Path(profile)
    if not folder.is_dir():
        return {"ok": False, "profile": folder.name, "why": "ไม่พบโฟลเดอร์โปรไฟล์"}

    import chrome_view
    if chrome_view.profile_running(folder):
        return {"ok": False, "profile": folder.name,
                "why": "โครมของโปรไฟล์นี้เปิดอยู่ — ปิดก่อนแล้วค่อยกดอ่านใหม่"}

    # อีเมลของโปรไฟล์นี้ — ใช้ทั้งตอนเข้าแอปและตอนยืนยันว่าไม่ได้สลับบัญชีผิดใบ
    email = ""
    try:
        import flow_accounts
        for candidate in flow_accounts.emails():
            if Path(flow_accounts.profile_dir_of(candidate)).name == folder.name:
                email = candidate
                break
    except Exception:                                          # noqa: BLE001
        pass

    lock = f"flow-acct-{folder.name}"
    try:
        with shared.browser_lock(timeout=120, profile=lock,
                                 label=f"อ่านเครดิต {folder.name}"):
            with sync_playwright() as pw:
                browser = flow_worker.open_browser(pw, hidden=True,
                                                   profile_dir=folder)
                try:
                    page = browser.pages[0] if browser.pages else browser.new_page()
                    # **ใช้ตัวตรวจของ flow_login ไม่ใช่เปิด URL เองแล้วอ่าน**
                    # (แก้ 11 ก.ย. 2569) — เปิด FLOW_URL ตรงๆ ไปตกหน้าโฆษณา
                    # flow.google.com/about ซึ่งไม่มีปุ่มบัญชีให้กด จึงอ่านเครดิต
                    # ไม่ได้ทุกครั้ง แล้วผมสรุปผิดว่า "โปรไฟล์หลุดล็อกอิน" ทั้งที่
                    # ล็อกอินอยู่ครบ — ตัวของ flow_login ผ่านหน้าล็อกอินก่อนแล้ว
                    # ค่อยเข้าแอป และ **ยืนยันว่าอีเมลบนหน้าตรงกับใบที่ตั้งใจ**
                    # ซึ่งกันเคสสองโปรไฟล์เป็นบัญชีเดียวกันโดยไม่รู้ตัวด้วย
                    import flow_login                          # noqa: PLC0415
                    got = flow_login.profile_check(page, email, log=lambda *_: None)
                    credits = got.get("credits")
                    seen = str(got.get("seen") or "")
                    why = str(got.get("why") or "")
                    if credits is None:
                        # เก็บภาพ + ผังหน้าไว้ **ก่อนปิด** ปิดแล้วแคปไม่ได้อีก
                        # (กติกา 2.6.1) ของเดิมล้มแล้วเหลือแต่ประโยคเดียวว่า
                        # "ยังเข้า Flow ไม่สำเร็จ" ซึ่งไล่ต่อไม่ได้เลยว่า
                        # หน้าจริงขึ้นอะไร ต้องให้คนล็อกอินใหม่หรือแค่โหลดช้า
                        try:
                            import evidence                    # noqa: PLC0415
                            evidence.shot(
                                page, f"อ่านเครดิต Flow ไม่ได้ {folder.name}",
                                tag="flow",
                                note=f"บัญชี: {email or '(ไม่รู้)'} · เหตุผล: {why} "
                                     f"· เห็นบนหน้า: {seen[:80]} · ที่อยู่: {page.url}")
                        except Exception as snap:              # noqa: BLE001
                            log(f"   (เก็บภาพหน้าไม่ได้: {type(snap).__name__})")
                finally:
                    browser.close()
    except Exception as error:                                 # noqa: BLE001
        save(folder.name, None, account=email, note=f"{type(error).__name__}")
        return {"ok": False, "profile": folder.name,
                "why": f"{type(error).__name__}: {str(error)[:90]}"}

    save(folder.name, credits, account=email, note=why[:80])
    if credits is None:
        log(f"   {folder.name}: อ่านเครดิตไม่ได้ — {why or 'ไม่ทราบสาเหตุ'}")
        return {"ok": False, "profile": folder.name, "credits": None,
                "account": email, "seen": seen,
                "why": why or "เปิดได้แต่อ่านเลขเครดิตบนหน้าไม่ได้"}
    log(f"   {folder.name}: เหลือ {credits} หน่วย "
        f"≈ {credits // CREDITS_PER_CLIP} คลิป")
    return {"ok": True, "profile": folder.name, "credits": credits,
            "account": email, "seen": seen,
            "clips_left": credits // CREDITS_PER_CLIP}


def refresh_all(log=print) -> dict:
    """ไล่อ่านเครดิตทุกโปรไฟล์ทีละอัน — ข้ามตัวที่เปิดค้างอยู่พร้อมบอกเหตุผล"""
    done, failed, skipped = [], [], []
    targets = _profiles()
    log(f"ไล่อ่านเครดิต {len(targets)} โปรไฟล์")
    for folder, label, _account in targets:
        got = read_now(folder, log=log)
        if got.get("ok"):
            done.append(got)
        elif "เปิดอยู่" in str(got.get("why") or ""):
            skipped.append(got)
            log(f"   {folder.name}: ข้าม — {got.get('why')}")
        else:
            failed.append(got)
            log(f"   {folder.name}: ล้ม — {got.get('why')}")
    return {"ok": bool(done), "done": done, "failed": failed,
            "skipped": skipped, "total": len(targets)}


if __name__ == "__main__":
    import sys

    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    if arg == "อ่าน":
        print(refresh_all())
    else:
        data = rows()
        print(f"เครดิต Flow รายโครม {len(data)} โปรไฟล์\n")
        print(f"   {'โปรไฟล์':<14}{'เครดิต':>9}{'เจนได้':>9}  {'วัดเมื่อ':<18}สถานะ")
        for row in data:
            credits = ("ยังไม่เคยวัด" if row["credits"] is None
                       else f"{row['credits']:,}")
            clips = "-" if row["clips_left"] is None else f"{row['clips_left']} คลิป"
            mark = "เปิดอยู่" if row["running"] else ""
            if row["stale"]:
                mark = (mark + " · เลขเก่า").strip(" ·")
            print(f"   {row['profile']:<14}{credits:>9}{clips:>9}  "
                  f"{(row['checked_at'] or '-')[:16]:<18}{mark}")
