# -*- coding: utf-8 -*-
"""ทำคลิปให้เป็น 1080p — โปรแกรมเดี่ยว ลากไฟล์มาวางบนไอคอนได้เลย

เจ้าของสั่ง 21 ก.ย. 2569: *"เขียนโปรแกรม up จาก 720 p ไป 1080 P
แล้ววาง shortcut ไว้บน desktop หน่อย"*

ใช้ตัวเดียวกับที่กล่อง Auto 1080P ในระบบใช้ (ffmpeg lanczos) เพราะวัดเทียบ
5 วิธีแล้วตัวนี้ได้ผลดีกว่าตัว AI สามในสี่ตัว และเร็วกว่า 26 เท่า

    waifu2x             48.39 คะแนน   20.7 นาที/คลิป
    ffmpeg lanczos      46.09 คะแนน    0.8 นาที/คลิป   <- ตัวนี้
    Real-ESRGAN x4plus  43.99 คะแนน  493.5 นาที/คลิป
    Real-ESRGAN วิดีโอ  40.88 คะแนน   13.5 นาที/คลิป
    Real-CUGAN          37.57 คะแนน   21.0 นาที/คลิป

--------------------------------------------------------------------------
วิธีใช้
    ลากไฟล์คลิปมาวางบนไอคอนบนเดสก์ท็อป  (ทีละหลายไฟล์ก็ได้)
    หรือดับเบิลคลิกไอคอน แล้วเลือกไฟล์เอง
--------------------------------------------------------------------------

**ไม่แตะไฟล์เดิมเลย** ไฟล์ใหม่ไปวางข้างๆ ในชื่อ `<ชื่อเดิม>-1080p.mp4`
"""
import subprocess
import sys
import time
from pathlib import Path

# ความละเอียดเป้าหมาย นับจาก **ด้านสั้น** เสมอ
#
# ต้องนับด้านสั้น ไม่ใช่ความสูง — คลิปแนวตั้ง 9:16 ขนาด 720p คือ 720 กว้าง
# 1280 สูง ถ้าไปเทียบ "ความสูง >= 1080" คลิป 720p จะผ่านทันทีทั้งที่ยังไม่ใช่
# (เคยพลาดแบบนี้จริงในระบบใหญ่เมื่อ 29 ส.ค. 2569 ตัวตรวจบอกว่าคลิป 720p
#  ผ่านหมด 12 ใบ) ด้านสั้นใช้ได้ทั้งแนวตั้งและแนวนอน ไม่ต้องเดาว่าวางแนวไหน
TARGET_SHORT = 1080

VIDEO_TYPES = {".mp4", ".mov", ".m4v", ".webm", ".avi", ".mkv"}


def say(text: str = "") -> None:
    print(text, flush=True)


def size_of(path: Path) -> tuple[int, int] | None:
    """(กว้าง, สูง) ของคลิป — คืน None เมื่อวัดไม่ได้

    **คืน None เมื่อวัดไม่ได้ ห้ามเดาเป็น 0** เพราะ "วัดไม่ได้" กับ "เล็กกว่า
    ที่ควร" เป็นคนละเรื่อง ถ้าเดาเป็น 0 ไฟล์ที่อ่านไม่ออกจะถูกขยายมั่ว
    """
    try:
        done = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height",
             "-of", "csv=p=0:s=x", str(path)],
            capture_output=True, text=True, timeout=120)
        w, h = done.stdout.strip().split("\n")[0].split("x")[:2]
        return int(w), int(h)
    except Exception:                                            # noqa: BLE001
        return None


def upscale(path: Path) -> str:
    """ขยายคลิปหนึ่งไฟล์ — คืนข้อความสรุปที่อ่านแล้วรู้เรื่องทันที"""
    if not path.is_file():
        return f"❌ {path.name} — ไม่เจอไฟล์นี้"
    if path.suffix.lower() not in VIDEO_TYPES:
        return (f"⏭ {path.name} — ไม่ใช่ไฟล์คลิป "
                f"(รับ {' '.join(sorted(VIDEO_TYPES))})")

    got = size_of(path)
    if not got:
        return f"❓ {path.name} — วัดความละเอียดไม่ได้ จึงไม่ขยาย (ไฟล์อาจเสีย)"
    width, height = got
    short = min(width, height)
    if short >= TARGET_SHORT:
        return f"✅ {path.name} — เป็น {short}p อยู่แล้ว ({width}×{height}) ไม่ต้องขยาย"

    # แนวตั้งขยายด้านกว้าง แนวนอนขยายด้านสูง — -2 คือให้ ffmpeg คิดอีกด้านให้
    # โดยรักษาสัดส่วนเดิมและปัดเป็นเลขคู่ (ตัวเข้ารหัสวิดีโอต้องการเลขคู่)
    if width <= height:
        scale = f"scale={TARGET_SHORT}:-2:flags=lanczos"
    else:
        scale = f"scale=-2:{TARGET_SHORT}:flags=lanczos"

    out = path.with_name(f"{path.stem}-1080p.mp4")
    if out.exists():
        stamp = time.strftime("%H%M%S")
        out = path.with_name(f"{path.stem}-1080p-{stamp}.mp4")

    say(f"   กำลังขยาย {path.name}  ({width}×{height} → ด้านสั้น {TARGET_SHORT}) …")
    began = time.perf_counter()
    done = subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", str(path),
         "-vf", scale,
         "-c:v", "libx264", "-crf", "18", "-preset", "medium",
         "-c:a", "copy", str(out)],
        capture_output=True, text=True, errors="replace")
    seconds = time.perf_counter() - began

    if done.returncode != 0 or not out.is_file():
        why = (done.stderr or "").strip().splitlines()
        return f"❌ {path.name} — ขยายไม่สำเร็จ: {why[-1][:120] if why else 'ไม่รู้สาเหตุ'}"

    # ---- ตรวจไฟล์ที่ได้จริง ไม่ใช่เชื่อว่าสั่งแล้วสำเร็จ ----------------------
    #
    # คำสั่งคืนค่าสำเร็จ ไม่เท่ากับได้ไฟล์ที่ต้องการ ถ้าไม่ตรวจ วันหนึ่งจะได้
    # ไฟล์ที่ความละเอียดไม่ถึงแต่ระบบบอกว่าเรียบร้อย
    made = size_of(out)
    if not made or min(made) < TARGET_SHORT:
        out.unlink(missing_ok=True)
        return (f"❌ {path.name} — ขยายแล้วได้ "
                f"{'วัดไม่ได้' if not made else f'{made[0]}×{made[1]}'} "
                f"ซึ่งยังไม่ถึงเกณฑ์ จึงลบทิ้ง ไฟล์เดิมไม่ถูกแตะ")

    mb_in = path.stat().st_size / 1048576
    mb_out = out.stat().st_size / 1048576
    return (f"✅ {path.name}\n"
            f"      {width}×{height} → {made[0]}×{made[1]}  "
            f"· {mb_in:.1f} → {mb_out:.1f} MB  · ใช้ {seconds:.1f} วินาที\n"
            f"      ได้ไฟล์ใหม่: {out.name}")


def pick_files() -> list[Path]:
    """ไม่ได้ลากไฟล์มา → เปิดหน้าต่างให้เลือกเอง"""
    try:
        import tkinter as tk
        from tkinter import filedialog
    except Exception:                                            # noqa: BLE001
        say("เปิดหน้าต่างเลือกไฟล์ไม่ได้ — ให้ลากไฟล์มาวางบนไอคอนแทน")
        return []
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    names = filedialog.askopenfilenames(
        title="เลือกคลิปที่จะทำให้เป็น 1080p (เลือกหลายไฟล์ได้)",
        filetypes=[("ไฟล์คลิป", "*.mp4 *.mov *.m4v *.webm *.avi *.mkv"),
                   ("ทุกไฟล์", "*.*")])
    root.destroy()
    return [Path(n) for n in names]


def main(argv: list[str]) -> int:
    say("=" * 62)
    say("        ทำคลิปให้เป็น 1080p")
    say("=" * 62)

    files = [Path(a) for a in argv]
    if not files:
        say("ไม่ได้ลากไฟล์มา — เปิดหน้าต่างให้เลือกไฟล์…")
        files = pick_files()
    if not files:
        say()
        say("ไม่ได้เลือกไฟล์ไหนเลย จบการทำงาน")
        return 0

    say()
    say(f"มีไฟล์ให้ทำ {len(files)} ไฟล์")
    say("ไฟล์เดิมจะไม่ถูกแตะ — ไฟล์ใหม่ไปวางข้างๆ ในชื่อลงท้าย -1080p.mp4")
    say("-" * 62)

    results = []
    for index, path in enumerate(files, start=1):
        say(f"[{index}/{len(files)}]")
        line = upscale(path)
        say(f"   {line}")
        results.append(line)
    say("-" * 62)

    ok = sum(1 for r in results if r.startswith("✅") and "ไม่ต้องขยาย" not in r)
    skip = sum(1 for r in results if "ไม่ต้องขยาย" in r or r.startswith("⏭"))
    bad = sum(1 for r in results if r.startswith(("❌", "❓")))
    summary = f"ขยายสำเร็จ {ok} ไฟล์ · ข้าม {skip} ไฟล์ · มีปัญหา {bad} ไฟล์"
    say(f"สรุป: {summary}")

    # ---- โชว์สรุปในหน้าต่างด้วย ไม่ใช่แค่ในหน้าต่างดำ ----------------------
    #
    # หน้าต่างดำของ Windows แสดงภาษาไทยเพี้ยนได้ ขึ้นกับฟอนต์และหน้ารหัสของ
    # เครื่องแต่ละคน ซึ่งเราคุมไม่ได้ — ถ้าเจ้าของอ่านผลไม่ออกก็เท่ากับไม่มีผล
    # หน้าต่างของ tkinter วาดภาษาไทยได้แน่นอนทุกเครื่อง จึงใช้เป็นตัวหลัก
    show_window(summary, results)
    return 0 if bad == 0 else 1


def show_window(summary: str, results: list[str]) -> None:
    """หน้าต่างสรุปผล — เผื่อหน้าต่างดำแสดงภาษาไทยไม่ได้"""
    try:
        import tkinter as tk
        from tkinter import scrolledtext
    except Exception:                                            # noqa: BLE001
        return
    try:
        root = tk.Tk()
        root.title("ทำคลิปให้เป็น 1080p — เสร็จแล้ว")
        root.attributes("-topmost", True)
        tk.Label(root, text=summary, font=("Tahoma", 12, "bold"),
                 pady=8).pack()
        box = scrolledtext.ScrolledText(root, width=78, height=16,
                                        font=("Tahoma", 10), wrap="word")
        box.pack(padx=10, pady=(0, 10))
        box.insert("1.0", chr(10).join(results))
        box.configure(state="disabled")
        tk.Button(root, text="ปิด", width=12, command=root.destroy,
                  font=("Tahoma", 10)).pack(pady=(0, 12))
        root.mainloop()
    except Exception:                                            # noqa: BLE001
        pass                     # โชว์หน้าต่างไม่ได้ก็ไม่เป็นไร ผลอยู่ในหน้าต่างดำแล้ว


if __name__ == "__main__":
    code = 0
    try:
        code = main(sys.argv[1:])
    except KeyboardInterrupt:
        say("\nหยุดกลางคัน")
        code = 1
    except Exception as error:                                   # noqa: BLE001
        say(f"\nเกิดข้อผิดพลาดที่ไม่คาดคิด: {type(error).__name__}: {error}")
        code = 1
    # หน้าต่างสรุปปิดแล้วก็จบเลย ไม่ต้องให้กด Enter ซ้ำอีกที
    say()
    raise SystemExit(code)
