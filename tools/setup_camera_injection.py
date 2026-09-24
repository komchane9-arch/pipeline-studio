"""เครื่องมือช่วยตั้งค่าและเริ่มระบบ Camera Injection (ส่งภาพกล้องมือถือรีโมท เข้า Facebook/TikTok/Shopee บน Emulator)

หลักการทำงาน:
1. มือถือเครื่องรีโมท (เช่น Xiaomi 11T Pro) เปิดแอป Iriun Webcam เพื่อส่งภาพกล้องสดผ่าน Wi-Fi/USB
2. เครื่องโฮสต์ (คอมพิวเตอร์) รับสัญญาณผ่าน Iriun Webcam Driver บน Windows
3. สคริปต์นี้เปิด LDPlayer 14 พร้อมเชื่อมต่อ ADB (127.0.0.1:5555) เข้าสู่ระบบ Pipeline Studio
4. ภายใน LDPlayer เมื่อแอป Facebook, TikTok, หรือ Shopee เรียกเปิดกล้อง จะเห็นภาพจากกล้องมือถือรีโมททันที
5. ผู้ใช้สามารถควบคุมหน้าจอ LDPlayer ผ่าน Pipeline Remote (web/remote.html) ได้เหมือนมือถือจริง
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
ADB_BIN = r"C:\project\2.Auto gen Video\7.web app\tools\platform-tools\adb.exe"
IRIUN_EXE = r"C:\Program Files (x86)\Iriun Webcam\IriunWebcam.exe"
LDCONSOLE_EXE = r"C:\LDPlayer\LDPlayer14\ldconsole.exe"

def say(msg: str = "") -> None:
    try:
        print(msg, flush=True)
    except UnicodeEncodeError:
        sys.stdout.buffer.write((msg + "\n").encode("utf-8", "replace"))

def check_iriun() -> bool:
    if not os.path.exists(IRIUN_EXE):
        say("❌ ไม่พบโปรแกรม Iriun Webcam บนคอมพิวเตอร์")
        return False
    say("✅ พบโปรแกรม Iriun Webcam บนคอมพิวเตอร์เรียบร้อย")
    return True

def ensure_iriun_running() -> None:
    # ตรวจว่า IriunWebcam.exe รันอยู่หรือไม่
    res = subprocess.run(["tasklist", "/FI", "IMAGENAME eq IriunWebcam.exe"], capture_output=True, text=True)
    if "IriunWebcam.exe" not in res.stdout:
        say("• กำลังเปิด IriunWebcam.exe บนคอมพิวเตอร์...")
        subprocess.Popen([IRIUN_EXE], creationflags=0x00000008 | 0x00000200)
        time.sleep(2)
    else:
        say("✅ IriunWebcam.exe กำลังเปิดทำงานอยู่แล้ว")

def check_ldplayer() -> bool:
    if not os.path.exists(LDCONSOLE_EXE):
        say("❌ ไม่พบ LDPlayer 14 บน C:\\LDPlayer\\LDPlayer14")
        return False
    say("✅ พบ LDPlayer 14 บน C:\\LDPlayer\\LDPlayer14 เรียบร้อย")
    return True

def configure_ldplayer_mobile(instance_index: int = 0) -> None:
    """ตั้งค่า LDPlayer ให้อยู่ในโหมดมือถือแนวตั้ง (Portrait 720x1280 320dpi) สำหรับ TikTok / Shopee / FB"""
    say(f"• ปรับขนาดหน้าจอ LDPlayer (Instance {instance_index}) ให้เป็นโหมดมือถือ (720x1280)...")
    subprocess.run([
        LDCONSOLE_EXE, "modify", "--index", str(instance_index),
        "--resolution", "720,1280,320",
        "--cpu", "4",
        "--memory", "4096"
    ], capture_output=True, text=True)

def launch_ldplayer(instance_index: int = 0) -> None:
    say(f"• ตรวจสอบสถานะ LDPlayer (Instance {instance_index})...")
    res = subprocess.run([LDCONSOLE_EXE, "isrunning", "--index", str(instance_index)], capture_output=True, text=True)
    if "running" not in res.stdout.lower():
        configure_ldplayer_mobile(instance_index)
        say(f"• กำลังเปิด LDPlayer (Instance {instance_index})...")
        subprocess.run([LDCONSOLE_EXE, "launch", "--index", str(instance_index)])
        say("• กำลังรอให้อีมูเลเตอร์บูตระบบเสร็จสิ้น (ประมาณ 15-25 วินาที)...")
        for i in range(40):
            time.sleep(1)
            check = subprocess.run([LDCONSOLE_EXE, "isrunning", "--index", str(instance_index)], capture_output=True, text=True)
            if "running" in check.stdout.lower():
                time.sleep(5)  # รอ OS พร้อมรับ ADB
                break
    else:
        say(f"✅ LDPlayer (Instance {instance_index}) กำลังทำงานอยู่แล้ว")

def connect_adb() -> None:
    if not os.path.exists(ADB_BIN):
        say("⚠️ ไม่พบ adb.exe ในโฟลเดอร์เครื่องมือ")
        return
    say("• เชื่อมต่อ ADB เข้าสู่ LDPlayer (127.0.0.1:5555)...")
    subprocess.run([ADB_BIN, "connect", "127.0.0.1:5555"], capture_output=True, text=True)
    time.sleep(1)
    res = subprocess.run([ADB_BIN, "devices"], capture_output=True, text=True)
    say("รายการอุปกรณ์ในระบบ ADB:")
    for line in res.stdout.strip().splitlines():
        say(f"   {line}")

def main() -> int:
    say("=" * 65)
    say("🚀 เริ่มต้นระบบ Camera Injection (ส่งภาพกล้องมือถือรีโมท → โฮสต์)")
    say("=" * 65)

    if not check_iriun():
        return 1
    ensure_iriun_running()

    if not check_ldplayer():
        return 1
    launch_ldplayer(0)

    connect_adb()

    say("-" * 65)
    say("📌 คำแนะนำในการใช้งาน:")
    say("1. บนมือถือเครื่องรีโมท (Xiaomi):")
    say("   - เปิดแอป 'Iriun 4K Webcam' (โหลดฟรีจาก Play Store)")
    say("   - เชื่อมต่อ Wi-Fi วงเดียวกับคอม หรือเสียบสาย USB")
    say("   - เมื่อต่อติด ไฟสถานะบน Iriun ของคอมพิวเตอร์จะเปลี่ยนเป็นสีเขียว")
    say("2. บนเครื่องโฮสต์ (คอมพิวเตอร์ / LDPlayer):")
    say("   - เปิดแอป Facebook, TikTok หรือ Shopee ใน LDPlayer")
    say("   - เมื่อกดถ่ายคลิปหรือเปิดกล้อง ภาพจะมาจากกล้องมือถือรีโมททันที")
    say("3. บนหน้าเว็บ Pipeline Remote (web/remote.html):")
    say("   - อุปกรณ์ LDPlayer (emulator-5554 หรือ 127.0.0.1:5555) จะปรากฏให้เลือก")
    say("   - สามารถแตะสัมผัสหน้าจอและควบคุม LDPlayer ผ่านมือถือได้แบบสดๆ")
    say("=" * 65)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
