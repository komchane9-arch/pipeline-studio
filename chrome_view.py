"""เปิดหรือยกหน้าต่าง Chrome ของโปรไฟล์งานกลับเข้าจอ Windows.

ถ้า worker เปิดโปรไฟล์นั้นอยู่ จะยกเฉพาะหน้าต่างเดิมขึ้นมา. ถ้ายังว่าง ผู้เรียกต้อง
ถือ browser lock ก่อนเปิดโปรไฟล์และถือไว้จนผู้ใช้ปิดหน้าต่าง เพื่อไม่ให้ Chrome กับ
Playwright เปิด ``user-data-dir`` เดียวกันซ้อนกัน.
"""

from __future__ import annotations

import os
from pathlib import Path


def _normal_path(value: str | Path) -> str:
    return os.path.normcase(os.path.abspath(os.path.expandvars(str(value)))).rstrip("\\/")


def _uses_profile(cmdline: list[str], profile_dir: str | Path) -> bool:
    """คืน True เมื่อ command line ระบุ user-data-dir ตรงโปรไฟล์เป้าหมาย."""
    wanted = _normal_path(profile_dir)
    for index, raw in enumerate(cmdline or []):
        value = str(raw or "")
        if value.casefold().startswith("--user-data-dir="):
            value = value.split("=", 1)[1]
        elif value.casefold() == "--user-data-dir" and index + 1 < len(cmdline):
            value = str(cmdline[index + 1] or "")
        else:
            continue
        if _normal_path(value.strip('"')) == wanted:
            return True
    return False


def _is_real_window(visible: bool, title: str) -> bool:
    """หน้าต่างนี้เป็นบานที่คนเห็นบนจอจริงหรือเปล่า

    Chrome แขวนหน้าต่างซ่อนไว้เบื้องหลังเสมอ (Chrome_WidgetWin_0 ขนาด 0x0
    ไม่มีชื่อ) และมันไม่ปิดตามคำสั่งปิด ตัวตรวจที่นับรวมพวกนี้จะตอบว่า
    "ยังเปิดอยู่" ตลอดกาล แล้วจังหวะ "ปิดแล้วจำไอดี" ไม่มีวันทำงาน

    ถามว่า **มีบานที่คนเห็นไหม** ซึ่งมีเฉพาะตอนเปิดจริง ไม่ใช่ถามว่า
    ไม่เหลือหน้าต่างชื่อ Chrome เลยไหม (กติกา 2.3.1)
    """
    return bool(visible) and bool((title or "").strip())


def _chrome_windows() -> list[tuple[int, int, str]]:
    """หน้าต่าง Chrome ระดับบนทั้งหมด; เร็วกว่ากวาด command line ทุกโปรเซส."""
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    handles: list[tuple[int, int, str]] = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    @callback_type
    def collect(hwnd, _lparam):
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        class_name = ctypes.create_unicode_buffer(128)
        user32.GetClassNameW(hwnd, class_name, len(class_name))
        if not class_name.value.startswith("Chrome_WidgetWin"):
            return True
        # นับเฉพาะหน้าต่างที่คนเห็นบนจอจริง — Chrome แขวนหน้าต่างซ่อน
        # (Chrome_WidgetWin_0 ขนาด 0x0 ไม่มีชื่อ) ไว้เบื้องหลังเสมอ และมันไม่ปิด
        # ตามคำสั่งปิด ตัวตรวจเดิมจึงตอบว่า "ยังเปิดอยู่" ตลอดกาล
        # แล้วจังหวะ "ปิดแล้วจำไอดี" ไม่มีวันทำงาน
        length = user32.GetWindowTextLengthW(hwnd)
        title = ctypes.create_unicode_buffer(max(1, length + 1))
        user32.GetWindowTextW(hwnd, title, len(title))
        if not _is_real_window(bool(user32.IsWindowVisible(hwnd)), title.value):
            return True
        handles.append((int(hwnd), int(pid.value), title.value))
        return True

    user32.EnumWindows(collect, 0)
    return handles


def _matching_windows(profile_dir: str | Path) -> list[tuple[int, int, str]]:
    import psutil

    matched: list[tuple[int, int, str]] = []
    for hwnd, pid, title in _chrome_windows():
        try:
            if _uses_profile(psutil.Process(pid).cmdline(), profile_dir):
                matched.append((hwnd, pid, title))
        except (psutil.AccessDenied, psutil.NoSuchProcess, OSError):
            continue
    return matched


def profile_running(profile_dir: str | Path) -> bool:
    """มีหน้าต่างหลักของ Chrome โปรไฟล์นี้อยู่หรือไม่."""
    return bool(_matching_windows(profile_dir)) if os.name == "nt" else False


def show_profile(profile_dir: str | Path) -> dict:
    """ย้าย/ยกหน้าต่าง Chrome ของโปรไฟล์ขึ้นหน้า; ไม่พบแล้วคืน ``running=False``."""
    if os.name != "nt":
        return {"ok": False, "running": False, "reason": "รองรับเฉพาะ Windows"}

    import ctypes
    matched = _matching_windows(profile_dir)
    if not matched:
        return {"ok": False, "running": False,
                "reason": "ตอนนี้โปรไฟล์นี้ยังไม่มีหน้าต่าง Chrome กำลังทำงาน"}

    hwnd, pid, title = matched[0]
    user32 = ctypes.windll.user32
    sw_restore = 9
    swp_nosize = 0x0001
    swp_showwindow = 0x0040
    user32.ShowWindow(hwnd, sw_restore)
    # รอบอัตโนมัติซ่อนหน้าต่างไว้ที่ -32000; ต้องย้ายกลับเข้าจอด้วย ไม่ใช่แค่ focus.
    user32.SetWindowPos(hwnd, 0, 80, 60, 0, 0, swp_nosize | swp_showwindow)
    user32.BringWindowToTop(hwnd)
    user32.SetForegroundWindow(hwnd)
    return {"ok": True, "running": True, "pid": pid, "title": title,
            "profile": str(Path(profile_dir))}


def close_profile(profile_dir: str | Path, timeout: float = 10.0) -> dict:
    """ขอให้ Chrome โปรไฟล์เป้าหมายปิดแบบปกติ โดยไม่แตะ Chrome อื่น."""
    if os.name != "nt":
        return {"ok": False, "running": False, "reason": "รองรับเฉพาะ Windows"}

    import ctypes
    import time

    matched = _matching_windows(profile_dir)
    if not matched:
        return {"ok": True, "running": False, "closed": 0,
                "profile": str(Path(profile_dir))}
    wm_close = 0x0010
    user32 = ctypes.windll.user32
    for hwnd, _pid, _title in matched:
        user32.PostMessageW(hwnd, wm_close, 0, 0)

    deadline = time.monotonic() + max(1.0, float(timeout))
    while time.monotonic() < deadline:
        if not _matching_windows(profile_dir):
            return {"ok": True, "running": False, "closed": len(matched),
                    "profile": str(Path(profile_dir))}
        time.sleep(.25)
    return {"ok": False, "running": True, "closed": 0,
            "reason": "ส่งคำสั่งปิดแล้วแต่หน้าต่าง Chrome ยังไม่ปิด"}


def launch_profile(profile_dir: str | Path, url: str, timeout: float = 12.0) -> dict:
    """เปิด Chrome โปรไฟล์จริงบนจอ แล้วรอจนพบ top-level window."""
    if os.name != "nt":
        return {"ok": False, "running": False, "reason": "รองรับเฉพาะ Windows"}

    import subprocess
    import time

    executables = (
        Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
        Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
    )
    chrome = next((path for path in executables if path.is_file()), None)
    if chrome is None:
        return {"ok": False, "running": False, "reason": "ไม่พบ Google Chrome ในเครื่อง"}

    profile = Path(profile_dir).resolve()
    profile.mkdir(parents=True, exist_ok=True)
    flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(
        subprocess, "CREATE_NO_WINDOW", 0)
    process = subprocess.Popen(
        [str(chrome), f"--user-data-dir={profile}", "--profile-directory=Default",
         "--window-position=80,60", "--new-window", str(url or "about:blank")],
        creationflags=flags,
        close_fds=True,
    )
    deadline = time.monotonic() + max(1.0, float(timeout))
    while time.monotonic() < deadline:
        shown = show_profile(profile)
        if shown.get("ok"):
            return {**shown, "launched": True, "launcher_pid": process.pid}
        if process.poll() is not None:
            break
        time.sleep(.25)
    return {"ok": False, "running": False,
            "reason": "สั่งเปิด Chrome แล้วแต่ยังไม่พบหน้าต่างบนจอ"}
