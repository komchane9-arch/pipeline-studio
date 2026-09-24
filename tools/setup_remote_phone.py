"""setup_remote_phone.py — ตั้งค่าและเปิดแอป Mobile Remote บนมือถือ Xiaomi

คำสั่ง:
    python tools/setup_remote_phone.py [serial]

หน้าที่:
1. ตั้ง `adb reverse tcp:8866 tcp:8866` เพื่อให้มือถือเข้าถึงเซิร์ฟเวอร์คอมพิวเตอร์ผ่าน localhost:8866
2. สั่งเปิด Google Chrome บนมือถือไปยัง http://localhost:8866/remote ทันที
3. แนะนำการติดตั้งลงหน้าจอหลัก (Install PWA) เพื่อใช้งานแบบเต็มหน้าจอ (Standalone App)
"""

import subprocess
import sys
import time

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

TARGET_SERIAL = "93a21824"  # Xiaomi 11T Pro (เครื่อง 2)


def run_cmd(cmd):
    p = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
    return p.returncode, p.stdout.strip(), p.stderr.strip()

def main():
    serial = sys.argv[1] if len(sys.argv) > 1 else TARGET_SERIAL

    print(f"=== ตั้งค่า Mobile Remote สำหรับมือถือ [{serial}] ===")
    
    # 1. ตรวจสอบว่าเครื่องเชื่อมต่ออยู่หรือไม่
    rc, out, _ = run_cmd(["adb", "devices"])
    if serial not in out:
        print(f"❌ ไม่พบอุปกรณ์ {serial} ในรายการ adb devices")
        print("กรุณาตรวจสอบว่าเสียบสาย USB และเปิด USB debugging เรียบร้อยแล้ว")
        sys.exit(1)
    
    print(f"✅ พบอุปกรณ์ {serial}")

    # 2. ตั้ง adb reverse
    print("• กำลังตั้งค่าพอร์ต Reverse (tcp:8866 -> tcp:8866)...")
    rc, out, err = run_cmd(["adb", "-s", serial, "reverse", "tcp:8866", "tcp:8866"])
    if rc == 0:
        print("✅ ตั้งค่า Reverse Port สำเร็จ (มือถือเปิด http://localhost:8866/remote ได้โดยตรง)")
    else:
        print(f"⚠️ ตั้งค่า Reverse มีข้อผิดพลาด: {err or out}")

    # 3. สั่งเปิดเบราว์เซอร์บนมือถือ
    url = "http://localhost:8866/remote"
    print(f"• กำลังสั่งเปิดแอปบนหน้าจอมือถือ ({url})...")
    run_cmd(["adb", "-s", serial, "shell", "am", "start", "-a", "android.intent.action.VIEW", "-d", url])
    
    print("\n" + "="*55)
    print("📱 หน้าจอรีโมทเปิดขึ้นบนมือถือ Xiaomi แล้ว!")
    print("="*55)
    print("💡 คำแนะนำการใช้งานให้สะดวกสูงสุด (เต็มจอเหมือนแอปจริง):")
    print("1. บนเบราว์เซอร์ Chrome ในมือถือ: แตะจุดสามจุดที่มุมขวาบน (⋮)")
    print("2. เลือกเมนู 'เพิ่มลงในหน้าจอหลัก' หรือ 'ติดตั้งแอป' (Add to Home screen / Install App)")
    print("3. จะได้ไอคอนแอป 'Remote' บนหน้าจอหลัก เมื่อกดเปิดจะทำงานแบบ Full Screen ไม่มีแถบ URL ทันที!")
    print("="*55)

if __name__ == "__main__":
    main()
