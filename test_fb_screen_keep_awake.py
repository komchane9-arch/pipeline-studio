"""ทดสอบบัตรกันจอดับของงานมือถือ โดยไม่แตะ ADB จริง."""

from __future__ import annotations

import fb_screen


class FakeShell:
    def __init__(self, stay_on: str = "0") -> None:
        self.stay_on = stay_on
        self.commands: list[str] = []

    def __call__(self, command: str) -> str:
        self.commands.append(command)
        if command == "settings get global stay_on_while_plugged_in":
            return self.stay_on + "\n"
        if command.startswith("settings put global stay_on_while_plugged_in "):
            self.stay_on = command.rsplit(" ", 1)[-1]
            return ""
        if "dumpsys power" in command:
            return "mWakefulness=Awake\n"
        return ""


def check(ok: bool, message: str) -> None:
    if not ok:
        raise AssertionError(message)
    print("✅ " + message)


shell = FakeShell("0")
with fb_screen.keep_awake_while_working(shell):
    check(shell.stay_on == "7", "เปิด stay-on ตลอดช่วงที่งานถือเครื่อง")
check(shell.stay_on == "0", "คืนค่าเดิมเมื่องานสำเร็จ")


shell = FakeShell("3")
try:
    with fb_screen.keep_awake_while_working(shell):
        check(shell.stay_on == "7", "เปิด stay-on ก่อนงานที่อาจล้ม")
        raise RuntimeError("จำลองงานล้ม")
except RuntimeError as error:
    check(str(error) == "จำลองงานล้ม", "ไม่กลืนข้อผิดพลาดของงานหลัก")
else:
    raise AssertionError("ข้อผิดพลาดของงานหลักหายไป")
check(shell.stay_on == "3", "คืนค่าที่ผู้ใช้ตั้งไว้แม้งานล้ม")


shell = FakeShell("7")
with fb_screen.keep_awake_while_working(shell):
    pass
puts = [c for c in shell.commands if c.startswith("settings put global")]
check(not puts, "ไม่เขียนทับหรือปิดค่าเดิมเมื่อเครื่องกันจอดับไว้อยู่แล้ว")
