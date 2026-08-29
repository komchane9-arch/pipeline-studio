"""จัดการคีย์ Gemini หลายใบ — ใส่เพิ่ม · ดูสถานะ · ทดสอบทีละใบ

**เจ้าของสั่ง 30 ส.ค. 2569** — *"ผมจะแอดเป็น 2 API key ทำได้เลยไหม"*

    python gemini_keys.py                 ดูว่ามีกี่ใบ ใบไหนใช้ได้
    python gemini_keys.py add <คีย์>       ใส่เพิ่มอีกใบ
    python gemini_keys.py remove <ลำดับ>   เอาออก
    python gemini_keys.py test            ยิงจริงทีละใบ ดูว่าใบไหนยังมีเครดิต

⚠️ **คีย์ที่เพิ่มต้องอยู่คนละโปรเจกต์คนละบัญชี** เครดิตแบบเติมล่วงหน้าผูกกับ
โปรเจกต์ ไม่ได้ผูกกับคีย์ — สร้างคีย์ใหม่ในโปรเจกต์เดิมจะกินเครดิตถังเดียวกัน
เติมไปก็ไม่ช่วยอะไร

**ทำไมต้องมีไฟล์นี้แทนที่จะใส่ในหน้าเว็บ** หน้าเว็บกับ `app.py` เป็นของสายกลาง
(กติกาข้อ 7.1.1) สายคลิปแตะเองไม่ได้ ตัวนี้จึงเป็นทางให้ใช้ได้ทันที
ส่วนช่องกรอกบนหน้าเว็บจะส่งสเปคให้สายกลางทำต่อ
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

import flow_worker as fw                                      # noqa: E402

ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models"
TEST_MODEL = "gemini-2.5-flash"


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD),
                ("pbData", ctypes.POINTER(ctypes.c_char))]


def _say(message: str) -> None:
    try:
        print(message, flush=True)
    except UnicodeEncodeError:
        sys.stdout.buffer.write((message + "\n").encode("utf-8", "replace"))


def save_keys(keys: list[str]) -> None:
    """เขียนคีย์ทุกใบกลับลงไฟล์เดิม เข้ารหัสด้วย DPAPI เหมือนเดิมทุกอย่าง

    คั่นด้วยขึ้นบรรทัด — ใบเดียวจะไม่มีขึ้นบรรทัด ของเก่าจึงอ่านได้เหมือนเดิม
    """
    body = "\n".join(k.strip() for k in keys if k.strip()).encode("utf-8")
    buffer = ctypes.create_string_buffer(body, len(body))
    source = _Blob(len(body), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))
    out = _Blob()
    ok = ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(source), None, None, None, None, 0, ctypes.byref(out))
    if not ok:
        raise SystemExit("เข้ารหัสคีย์ไม่สำเร็จ — ไม่ได้เขียนอะไรลงไฟล์")
    try:
        fw.GEMINI_KEY_FILE.write_bytes(
            ctypes.string_at(out.pbData, out.cbData))
    finally:
        ctypes.windll.kernel32.LocalFree(
            ctypes.cast(out.pbData, wintypes.HLOCAL))


def show() -> None:
    rows = fw.gemini_key_board()
    if not rows:
        _say("ยังไม่มีคีย์ Gemini เลย — ใส่ด้วย  python gemini_keys.py add <คีย์>")
        return
    _say(f"มีคีย์ {len(rows)} ใบ")
    for row in rows:
        state = "ใช้ได้" if row["ok"] else f"พักอยู่ อีก {row['wait_min']} นาที"
        _say(f"  {row['no']}. …{row['tail']}   {state}")
        if row["why"]:
            _say(f"     เหตุผล: {row['why'][:90]}")
    live = fw.load_gemini_api_key() or ""
    _say(f"\nตอนนี้ระบบจะใช้ใบที่ลงท้ายด้วย …{live[-6:]}" if live else "")


def add(key: str) -> None:
    key = key.strip()
    if len(key) < 20:
        raise SystemExit("คีย์สั้นผิดปกติ — ตรวจว่าก๊อปมาครบไหม")
    keys = fw.load_gemini_keys()
    if key in keys:
        _say("คีย์นี้มีอยู่แล้ว ไม่ได้ใส่ซ้ำ")
        return
    keys.append(key)
    save_keys(keys)
    _say(f"ใส่แล้ว — ตอนนี้มี {len(keys)} ใบ")
    show()


def remove(no: int) -> None:
    keys = fw.load_gemini_keys()
    if not 1 <= no <= len(keys):
        raise SystemExit(f"มีคีย์ {len(keys)} ใบ เลือกได้ 1-{len(keys)}")
    gone = keys.pop(no - 1)
    save_keys(keys)
    _say(f"เอาใบที่ {no} (…{gone[-6:]}) ออกแล้ว เหลือ {len(keys)} ใบ")


def test() -> None:
    """ยิงจริงทีละใบ — คำถามสั้นที่สุดเท่าที่ทำได้ เพื่อไม่ให้เปลืองเครดิต"""
    import json                                               # noqa: PLC0415
    import urllib.error                                       # noqa: PLC0415
    import urllib.request                                     # noqa: PLC0415

    keys = fw.load_gemini_keys()
    if not keys:
        _say("ยังไม่มีคีย์ให้ทดสอบ")
        return
    for index, key in enumerate(keys, 1):
        url = f"{ENDPOINT}/{TEST_MODEL}:generateContent?key={key}"
        body = json.dumps({"contents": [{"parts": [{"text": "ok"}]}]}).encode()
        request = urllib.request.Request(
            url, data=body, headers={"Content-Type": "application/json"})
        try:
            urllib.request.urlopen(request, timeout=30)
            _say(f"  {index}. …{key[-6:]}  ✅ ใช้ได้ ยังมีเครดิต")
        except urllib.error.HTTPError as error:
            raw = error.read().decode("utf-8", "replace")
            kind = fw.note_gemini_response(key, error.code, raw)
            note = {"credits": "เครดิตที่เติมไว้หมด — ต้องเติมเงิน",
                    "daily": "โควตารายวันหมด — คืนข้ามวัน",
                    "rate": "ยิงถี่เกินไป — รอสักครู่"}.get(kind, "")
            try:
                why = json.loads(raw).get("error", {}).get("message", "")
            except Exception:                                 # noqa: BLE001
                why = raw[:120]
            _say(f"  {index}. …{key[-6:]}  ❌ HTTP {error.code} {note}")
            _say(f"     {why[:130]}")
        except OSError as error:
            _say(f"  {index}. …{key[-6:]}  ⚠️ ต่อไม่ได้: {error}")


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("list", "board"):
        show()
    elif argv[0] == "add" and len(argv) > 1:
        add(argv[1])
    elif argv[0] == "remove" and len(argv) > 1:
        remove(int(argv[1]))
    elif argv[0] == "test":
        test()
    else:
        _say(__doc__ or "")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
