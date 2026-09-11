"""อ่านหน้าจอมือถือ — และ **แยกให้ออกว่า "ไม่เจอ" กับ "อ่านไม่ได้" คนละเรื่อง**

**เจ้าของสั่งยกขึ้นเป็นของกลาง 11 ก.ย. 2569** หลังวันเดียวเจอโรคเดียวกัน 8 ครั้ง

---

## โรคที่ตัวนี้มีไว้รักษา

ทุกครั้งหน้าตาเหมือนกันหมด: ตัวตรวจบอกว่า "ไม่พบ X" แล้วคนไปไล่หาสาเหตุที่ตัว X
ทั้งที่ความจริงคือ **อ่านหน้าจอไม่ได้ตั้งแต่แรก**

    ข้อความที่ระบบบอก          ความจริง
    "ไม่พบปุ่มค้นหา"           มีกล่องขอสิทธิ์ของ Android บังจออยู่
    "ไม่พบแท็บร้านค้า"         ชื่อแท็บเป็นภาษาไทย ตัวอ่านเดิมอ่านไม่ออก
    "ผลสินค้ายังไม่โหลด"       ด่านแรกหาคำที่อ่านไม่ได้อยู่แล้ว
    "ไม่มีคำชวนบังจอ"          มีบังเต็มจอ
    "ไม่ยืนยันผลโพสต์"         โพสต์ขึ้นไปแล้วเรียบร้อย

กติกาข้อ 2.3.1 เขียนเรื่องนี้ไว้ตั้งแต่ 28 ส.ค. **แต่บังคับด้วยความจำ ไม่ได้
บังคับด้วยโค้ด** จึงเกิดซ้ำเรื่อยมา ตัวนี้ทำให้ทำถูกง่ายกว่าทำผิด

## ใช้ยังไง

    import screen_read

    view = screen_read.read(serial)
    if not view.readable:
        raise RuntimeError(view.why)        # บอกสาเหตุจริง ไม่ใช่ "ไม่พบ X"
    if view.has("ร้านค้า"):
        ...

`view.why` ตอบได้ว่าอ่านไม่ได้เพราะอะไร — มีกล่องระบบบัง · อยู่ผิดแอป ·
หรืออยู่ถูกที่แต่หน้านั้นไม่ส่งตัวหนังสือออกมาเลย
"""
from __future__ import annotations

import html
import io
import re
import subprocess
from dataclasses import dataclass, field

# สระบน/ล่าง · วรรณยุกต์ · ไม้ไต่คู้ · การันต์ — ตัวอ่านภาพทำตกได้บ่อย
THAI_MARKS_RE = re.compile(r"[ัิ-ฺ็-๎]")

# กล่องของระบบที่เด้งทับแอปได้ — ตอนบังอยู่ ผังที่อ่านได้เป็นของกล่องนี้
# ไม่ใช่ของแอปที่เรากำลังทำงานด้วย
SYSTEM_DIALOG_PACKAGES = (
    "com.google.android.permissioncontroller",
    "com.android.permissioncontroller",
    "com.android.packageinstaller",
)

_THAI_OCR = None


def thai_loose(text: str) -> str:
    """ตัดสระบนล่างกับวรรณยุกต์ออก เพื่อเทียบคำแบบยอมให้อ่านตกได้

    **ต้องมีเพราะตัวอ่านภาพทำเครื่องหมายตกจริง** (วัด 11 ก.ย. 2569)
    ปุ่ม "เพิ่ม" ถูกอ่านเป็น "เพิม" · "ยอดการดูโพสต์" เป็น "ยอดการดูไพสต์"

    ใช้ **เฉพาะตอนที่ผังมาจากการอ่านภาพ** — ผังจริงจากระบบตัวอักษรถูก 100%
    อยู่แล้ว เทียบหลวมโดยไม่จำเป็นคือเปิดช่องให้กดโดนปุ่มที่สะกดใกล้กัน
    """
    return THAI_MARKS_RE.sub("", str(text or "")).casefold()


def get_thai_ocr():
    """ตัวอ่านตัวอักษร **ภาษาไทย** จากภาพ — โหลดครั้งเดียวแล้วเก็บไว้

    ตัวอ่านกลางเดิม (rapidocr) ใช้โมเดล ``ch_PP-OCRv4`` ซึ่งรู้จักแค่จีนกับ
    อังกฤษ ภาษาไทยออกมาเป็นขยะ — "ร้านค้า" อ่านได้เป็น "Suusefu"

    ตัวนี้อ่านไทยได้จริง วัดแล้ว 1.4 วินาทีต่อภาพบน RTX 3070
    """
    global _THAI_OCR
    if _THAI_OCR is None:
        try:
            import easyocr                                     # noqa: PLC0415
            _THAI_OCR = easyocr.Reader(["th", "en"], gpu=True, verbose=False)
        except Exception:                                      # noqa: BLE001
            _THAI_OCR = False
    return _THAI_OCR if _THAI_OCR is not False else None


def blocking_system_dialog(text: str) -> str:
    """คืนชื่อแอปของ **กล่องระบบที่บังจออยู่** ถ้าไม่มีคืนค่าว่าง

    **เจอจริง 11 ก.ย. 2569** ขั้น "เปิดหน้าสินค้า" ล้มด้วยข้อความ
    *"ไม่พบปุ่มค้นหา"* ทั้งที่ภาพหน้าจอเห็นแว่นขยายชัดเจน

        ผังตอนปกติ   45,585 ตัวอักษร · อ่านชื่อปุ่มได้ 19 คำ · เป็นของแอปเรา
        ผังตอนล้ม     7,867 ตัวอักษร · อ่านชื่อปุ่มได้  0 คำ ·
                     เป็นของ com.google.android.permissioncontroller

    ⚠️ **กล่องพวกนี้ปิดด้วยโปรแกรมไม่ได้** — ลองครบ 3 วิธี (แตะ · ปุ่มย้อนกลับ ·
    swipe) ไม่ขยับสักวิธี เพราะ Android กันไม่ให้โปรแกรมกดยินยอมแทนคน
    **ต้องมีคนกดที่เครื่อง** เจอเมื่อไรให้หยุดแล้วบอกเจ้าของ อย่าพยายามปิดเอง
    """
    plain = html.unescape(text or "")
    for package in SYSTEM_DIALOG_PACKAGES:
        if f'package="{package}"' in plain:
            return package
    return ""


@dataclass
class View:
    """สิ่งที่อ่านได้จากหน้าจอ **พร้อมคำตอบว่าเชื่อได้แค่ไหน**"""

    xml: str = ""
    words: list[str] = field(default_factory=list)
    source: str = ""            # "ระบบ" = ผังจริง · "ภาพ" = อ่านจากภาพ
    app: str = ""               # แอปที่อยู่หน้าสุด
    blocked_by: str = ""        # กล่องระบบที่บังอยู่ (ถ้ามี)
    readable: bool = False
    why: str = ""

    def has(self, needle: str) -> bool:
        """เจอคำนี้บนจอไหม — ยอมวรรณยุกต์ตกเฉพาะตอนอ่านมาจากภาพ"""
        if not needle:
            return False
        plain = html.unescape(self.xml or "") + " " + " ".join(self.words)
        if str(needle).casefold() in plain.casefold():
            return True
        return self.source == "ภาพ" and thai_loose(needle) in thai_loose(plain)

    def any_of(self, *needles: str) -> bool:
        return any(self.has(value) for value in needles if value)


def _run(serial: str, *args: str, timeout: int = 60) -> bytes:
    return subprocess.run(["adb", "-s", serial, *args],
                          capture_output=True, timeout=timeout).stdout


def foreground_app(serial: str) -> str:
    """แอปที่อยู่หน้าสุด — อ่านจาก dumpsys **ไม่ใช่จากผังจอ**

    สำคัญเพราะหน้าที่ไม่ส่งผังออกมาเลยก็ยังตอบข้อนี้ได้ จึงใช้แยก
    "อยู่ผิดแอป" ออกจาก "อยู่ถูกแอปแต่อ่านไม่ได้" ได้เสมอ
    """
    try:
        text = _run(serial, "shell", "dumpsys", "window", timeout=45)
        found = re.search(r"mCurrentFocus=Window\{[^}]*\s([\w.]+)/",
                          text.decode("utf-8", errors="replace"))
        return found.group(1) if found else ""
    except Exception:                                          # noqa: BLE001
        return ""


def read(serial: str, want_app: str = "", log=lambda *_: None) -> View:
    """อ่านหน้าจอหนึ่งครั้ง แล้วบอกให้ครบว่าเชื่อได้แค่ไหน

    ลำดับ: ผังจริงจากระบบก่อน (แม่นที่สุด) ถ้าอ่านชื่อปุ่มไม่ได้เลยจึงถอยไป
    อ่านจากภาพด้วยตัวอ่านภาษาไทย
    """
    view = View()
    view.app = foreground_app(serial)

    # ---- ชั้นที่ 1: ผังจริงจากระบบ -------------------------------------
    try:
        _run(serial, "shell", "rm", "-f", "/sdcard/screen_read.xml", timeout=30)
        told = _run(serial, "shell", "uiautomator", "dump",
                    "/sdcard/screen_read.xml", timeout=60)
        # **ห้ามอ่านไฟล์เก่าเมื่อคำสั่งล้ม** — uiautomator ล้มแล้วไฟล์เดิมยังอยู่
        # ทำให้ได้ผังของเมื่อสิบนาทีก่อนมาโดยไม่มีอะไรบอก (เจอจริง 11 ก.ย.
        # ค่าที่วัดขัดกันเองจนไล่ผิดทางอยู่พักใหญ่)
        if b"dumped" in told:
            view.xml = _run(serial, "shell", "cat", "/sdcard/screen_read.xml",
                            timeout=45).decode("utf-8", errors="replace")
    except Exception as error:                                 # noqa: BLE001
        log(f"  อ่านผังจากระบบไม่ได้: {type(error).__name__}")

    view.blocked_by = blocking_system_dialog(view.xml)
    if view.blocked_by:
        view.why = (f"มีกล่องขอสิทธิ์ของ Android บังจออยู่ ({view.blocked_by}) "
                    "— โปรแกรมปิดเองไม่ได้ ต้องมีคนกดที่เครื่อง")
        view.source = "ระบบ"
        return view

    if re.search(r'(?:text|content-desc)="[^"\s][^"]*"', view.xml or ""):
        view.source = "ระบบ"
        view.readable = True
        return view

    # ---- ชั้นที่ 2: อ่านจากภาพ ------------------------------------------
    reader = get_thai_ocr()
    if reader is None:
        view.why = "ผังจากระบบอ่านชื่อปุ่มไม่ได้ และตัวอ่านภาษาไทยจากภาพก็ใช้ไม่ได้"
        return view
    try:
        import numpy as np                                     # noqa: PLC0415
        from PIL import Image                                  # noqa: PLC0415

        png = _run(serial, "exec-out", "screencap", "-p", timeout=60)
        shot = Image.open(io.BytesIO(png)).convert("RGB")
        view.words = [str(value).strip()
                      for _, value, score in reader.readtext(np.array(shot)) or []
                      if str(value).strip() and float(score) >= .20]
    except Exception as error:                                 # noqa: BLE001
        view.why = f"อ่านจากภาพไม่สำเร็จ: {type(error).__name__}: {error}"
        return view

    view.source = "ภาพ"
    if view.words:
        view.readable = True
        return view

    # อ่านไม่ได้ทั้งสองทาง — บอกให้ชัดว่าเป็นเพราะอะไร
    if want_app and want_app not in view.app:
        view.why = f"แอปที่อยู่หน้าสุดคือ {view.app or '(อ่านไม่ได้)'} ไม่ใช่ {want_app}"
    else:
        view.why = (f"อยู่ที่ {view.app or '(อ่านไม่ได้)'} "
                    "แต่หน้านี้ไม่ส่งตัวหนังสือออกมาเลยทั้งจากระบบและจากภาพ")
    return view


def why_not_found(view: View, looking_for: str) -> str:
    """ข้อความล้มที่บอก **สาเหตุจริง** ไม่ใช่แค่ "ไม่พบ X"

    ห้ามปล่อยให้ข้อความล้มบอกแค่ว่าไม่พบของที่หา เพราะคนอ่านจะไปไล่หาสาเหตุ
    ที่ตัวของนั้น ทั้งที่ของจริงคือมีอย่างอื่นบังหรืออยู่ผิดหน้า — เสียเวลา
    ไล่ผิดทางทั้งวัน (เกิดจริง 11 ก.ย. 2569 กับข้อความ "ไม่พบปุ่มค้นหา")
    """
    if not view.readable:
        return f"{looking_for} — {view.why}"
    return (f"{looking_for} — อ่านหน้าจอได้ปกติ ({view.source}: "
            f"{len(view.words) or 'ผังระบบ'} คำ ที่ {view.app}) "
            "แปลว่าของที่หาไม่ได้อยู่บนจอจริง อาจย้ายที่หรือเปลี่ยนชื่อ")


if __name__ == "__main__":
    import sys

    phone = sys.argv[1] if len(sys.argv) > 1 else "W4FYYPYTLFYLIFHM"
    got = read(phone, log=print)
    print(f"แอปหน้าสุด : {got.app or '(อ่านไม่ได้)'}")
    print(f"อ่านได้ไหม : {'ได้' if got.readable else 'ไม่ได้'} (ทาง{got.source or '-'})")
    if got.blocked_by:
        print(f"มีของบัง   : {got.blocked_by}")
    if got.why:
        print(f"เหตุผล     : {got.why}")
    if got.words:
        print(f"อ่านได้ {len(got.words)} คำ: {got.words[:12]}")
    elif got.xml:
        found = re.findall(r'(?:text|content-desc)="([^"]{1,30})"', got.xml)
        print(f"ผังระบบ {len(got.xml)} ตัวอักษร · ป้าย {len(set(found))} คำ: "
              f"{sorted(set(found))[:12]}")
