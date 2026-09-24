"""reverse_keeper.py — คอยตรวจและเปิด adb reverse tcp:8866 tcp:8866 ให้อัตโนมัติทุกเครื่อง

ป้องกันพอร์ตหลุดเมื่อผู้ใช้ขยับสาย USB หรือถอดเสียบใหม่
"""

import subprocess
import time

PORT = 8866

def keep_reverse():
    try:
        res = subprocess.run(
            ["adb", "devices"], capture_output=True, text=True, timeout=5
        )
        for line in res.stdout.splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 2 and parts[1] == "device":
                serial = parts[0]
                chk = subprocess.run(
                    ["adb", "-s", serial, "reverse", "--list"],
                    capture_output=True,
                    text=True,
                    timeout=3,
                )
                if f"tcp:{PORT}" not in chk.stdout:
                    subprocess.run(
                        ["adb", "-s", serial, "reverse", f"tcp:{PORT}", f"tcp:{PORT}"],
                        capture_output=True,
                        timeout=3,
                    )
    except Exception:
        pass

def main():
    while True:
        keep_reverse()
        time.sleep(2.0)

if __name__ == "__main__":
    main()
