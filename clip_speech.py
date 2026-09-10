"""ฟังบทพูดก่อนเจนจริง — ทำเสียงตัวอย่างให้ใกล้กับที่ Google Flow จะพูดออกมา

**เจ้าของสั่ง 31 ส.ค. 2569** — *"ตรงบทพูด storyboard สร้างฟังก์ชั่นให้สามารถ
กดเล่นเสียงให้หน่อย กดทีเดียวเล่นทั้งหมด เสียงเอาเสียงที่คาดว่า google flow
จะเจนออกมาประมาณนี้"* และ *"เอาเสียงให้เหมือนกับที่จะเจนใน google flow ด้วยนะ"*

**ทำไมถึงคุ้ม** — ตอนนี้ต้องจ่ายเครดิต Veo 15 หน่วยถึงจะรู้ว่าบทพูดยาวเกินไหม
พูดแล้วลื่นไหมไหม ฟังก่อนได้ = รู้ตั้งแต่ยังไม่เสียเครดิต


ใกล้ของจริงแค่ไหน — วัดแล้ว ไม่ได้เดา
------------------------------------

วัดจากคลิปที่ Google Flow เจนไปแล้วจริง 8 ใบ (บทพูด 100–200 ตัวอักษร)
เทียบว่าเสียงตัวอย่างที่ทำได้ยาวต่างจากคลิปจริง 10 วินาทีเท่าไร

    ความเร็ว +0%   ต่างจากของจริง  -0.69 วินาที   ← เลือกอันนี้
    ความเร็ว +5%   ต่างจากของจริง  -1.13 วินาที
    ความเร็ว +8%   ต่างจากของจริง  -1.37 วินาที

**เร่งความเร็วแล้วห่างขึ้น ไม่ได้ใกล้ขึ้น** จึงใช้ความเร็วปกติ

⚠️ **ตัวเลข 13.5 ตัวอักษร/วินาที ที่เคยใช้เป็นเพดานนั้นต่ำไป** วัดจากคลิปจริง
19 ใบได้ **15.8 ตัวอักษร/วินาที** (ช่วง 11.4–17.0) และมีใบที่พูด 170 ตัวอักษร
จบใน 10 วินาทีจริง — แปลว่าเพดาน 135 ตัวที่ตั้งไว้ **ตัดบททิ้งมากเกินจำเป็น**
ยังไม่แก้เพดานในรอบนี้เพราะต้องให้เจ้าของฟังก่อนว่า 170 ตัวยังฟังรู้เรื่องไหม


ต้องตัดขีดจังหวะทิ้งก่อนพูด
---------------------------

บทพูดที่เก็บไว้มีขีดคั่นพยางค์ (`ชาร์จ-ไว-หก-สิบ-วัตต์`) ซึ่งใส่ไว้ให้ Veo
เว้นจังหวะ **แต่ตัวทำเสียงอ่านขีดเป็นการหยุดจริง** ทำให้ยาวเกินไป 1.76 วินาที

    มีขีด      11.76 วินาที   ห่างจากของจริง +1.76
    ตัดขีดแล้ว 10.51 วินาที   ห่างจากของจริง +0.51

ของจริงพูดจบใน 10.00 วินาที — **ตัดขีดแล้วใกล้กว่าเกือบ 4 เท่า**
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path

# เสียงไทยที่มีให้เลือก — ทั้งคู่เป็นเสียงสังเคราะห์แนวเดียวกับที่ Veo ใช้
# **ยังไม่รู้ว่าของจริงเป็นเสียงหญิงหรือชาย** เพราะคลิปมีเพลงคลอตลอด แยกไม่ออก
# จึงให้เลือกเอง แทนที่จะเดาแล้วบอกว่าเหมือน (กติกาข้อ 2.3.1 — ไม่รู้ต้องบอกว่าไม่รู้)
VOICES = {
    "female": ("th-TH-PremwadeeNeural", "เสียงหญิง"),
    "male": ("th-TH-NiwatNeural", "เสียงชาย"),
}
DEFAULT_VOICE = "female"

# ความเร็วที่ใกล้ของจริงที่สุดจากการวัด — อย่าเปลี่ยนโดยไม่วัดใหม่
RATE = "+0%"

# ช่องว่างระหว่างฉาก — Veo ตัดฉากแล้วพูดต่อทันที ไม่ได้เว้นยาว
GAP_SECONDS = 0.18

SPEECH_DIR = "speech"
CLIP_SECONDS = 10.0

_HYPHEN_RE = re.compile(r"[-‑‒–—]")
_SPACE_RE = re.compile(r"[ \t ]{2,}")


class SpeechError(RuntimeError):
    """ทำเสียงตัวอย่างไม่สำเร็จ — บอกเหตุผลเป็นภาษาคนเสมอ"""


def spoken_form(line: str) -> str:
    """ตัดขีดจังหวะทิ้งให้เหลือคำที่จะพูดจริง

    ขีดพวกนี้เป็นสัญญาณให้ Veo เว้นจังหวะ ไม่ใช่ตัวอักษรที่ต้องอ่าน
    """
    out = _HYPHEN_RE.sub("", line or "")
    return _SPACE_RE.sub(" ", out).strip()


def _ffmpeg() -> str:
    found = shutil.which("ffmpeg")
    if not found:
        raise SpeechError("เครื่องนี้ยังไม่มี ffmpeg — ต่อเสียงแต่ละฉากเข้าด้วยกันไม่ได้")
    return found


def duration(path: Path) -> float:
    """ไฟล์เสียงนี้ยาวกี่วินาที — คืน 0 ถ้าอ่านไม่ออก

    **0 แปลว่าอ่านไม่ได้ ไม่ใช่แปลว่าไม่มีเสียง** ผู้เรียกต้องแยกสองอย่างนี้เอง
    """
    probe = shutil.which("ffprobe")
    if not probe:
        return 0.0
    try:
        out = subprocess.run(
            [probe, "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", str(path)],
            capture_output=True, text=True, timeout=30,
        ).stdout.strip()
        return float(out or 0)
    except (OSError, ValueError, subprocess.SubprocessError):
        return 0.0


def _stamp(script: list[str], voice_key: str) -> str:
    """ลายนิ้วมือของบทพูด+เสียง — บทเปลี่ยนเมื่อไรได้ไฟล์ใหม่เอง"""
    raw = json.dumps([script, voice_key, RATE, GAP_SECONDS],
                     ensure_ascii=False).encode("utf-8")
    return hashlib.sha1(raw).hexdigest()[:12]


async def _say(text: str, voice: str, out: Path) -> None:
    import edge_tts                                          # noqa: PLC0415
    await edge_tts.Communicate(text, voice, rate=RATE).save(str(out))


# ตัวทำเสียงแถมความเงียบหัวท้ายมาให้ทุกชิ้น ราวชิ้นละ 1 วินาที
#
# **ไม่ตัดทิ้ง = ตัวเลขโกหก** วัดจริงกับใบ 55253513771: บทเดียวกันยิงทีเดียว
# ได้ 10.51 วินาที แต่ยิงแยก 5 ฉากแล้วต่อกันได้ 15.70 วินาที — ต่างกัน 5.19
# วินาทีที่เป็นความเงียบล้วน แล้วหน้าเว็บจะขึ้นว่า "เกินคลิป 5.7 วินาที"
# ทั้งที่บทพูดพอดีอยู่แล้ว → คนจะไปตัดบทที่ไม่ได้ยาวเกินจริง
_TRIM = ("silenceremove=start_periods=1:start_silence=0:start_threshold=-45dB"
         ":detection=peak,areverse,"
         "silenceremove=start_periods=1:start_silence=0:start_threshold=-45dB"
         ":detection=peak,areverse")


def _trim(path: Path) -> None:
    """ตัดความเงียบหัวท้ายของชิ้นเสียงทิ้ง — ตัดไม่ได้ก็ปล่อยของเดิมไว้"""
    cut = path.with_suffix(".trim.mp3")
    try:
        done = subprocess.run(
            [_ffmpeg(), "-y", "-v", "error", "-i", str(path), "-af", _TRIM,
             "-b:a", "48k", str(cut)],
            capture_output=True, text=True, timeout=90,
        )
        if not done.returncode and cut.is_file() and duration(cut) > 0.2:
            cut.replace(path)
        else:
            cut.unlink(missing_ok=True)
    except (OSError, subprocess.SubprocessError, SpeechError):
        cut.unlink(missing_ok=True)


def build(folder: Path, script: list[str], voice_key: str = DEFAULT_VOICE) -> dict:
    """ทำไฟล์เสียงของบทพูดทั้งชุด — กดครั้งเดียวได้ยินครบทุกฉาก

    คืนข้อมูลที่หน้าเว็บเอาไปแสดงได้เลย

        {"file": "speech/…mp3", "seconds": 10.4, "over": 0.4,
         "voice": "female", "voice_label": "เสียงหญิง",
         "scenes": [{"index":1, "text":…, "seconds":2.1, "start":0.0}, …]}

    **ทำแยกฉากแล้วค่อยต่อกัน** ไม่ใช่ยิงทีเดียวทั้งก้อน เพราะต้องรู้ว่า
    **ฉากไหนกินเวลาเท่าไร** — ถ้ายาวเกินจะได้รู้ว่าต้องตัดฉากไหน ไม่ใช่รู้แค่
    ว่า "รวมแล้วเกิน" ซึ่งบอกไม่ได้ว่าต้องแก้ตรงไหน
    """
    lines = [spoken_form(s) for s in (script or [])]
    lines = [s for s in lines if s]
    if not lines:
        raise SpeechError("ใบนี้ยังไม่มีบทพูด — ทำเสียงตัวอย่างไม่ได้")

    voice_key = voice_key if voice_key in VOICES else DEFAULT_VOICE
    voice, voice_label = VOICES[voice_key]

    out_dir = Path(folder) / SPEECH_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = _stamp(script, voice_key)
    final = out_dir / f"{voice_key}-{stamp}.mp3"

    parts_dir = out_dir / f".parts-{stamp}"
    made: list[Path] = []
    try:
        if not final.is_file():
            parts_dir.mkdir(parents=True, exist_ok=True)

            async def make_all() -> None:
                for index, text in enumerate(lines, 1):
                    piece = parts_dir / f"{index:02d}.mp3"
                    await _say(text, voice, piece)
                    _trim(piece)
                    made.append(piece)

            asyncio.run(make_all())
            missing = [p for p in made if not p.is_file() or not p.stat().st_size]
            if missing or len(made) != len(lines):
                raise SpeechError(
                    f"ทำเสียงได้ไม่ครบ ({len(made) - len(missing)}/{len(lines)} ฉาก) "
                    "— ตัวทำเสียงต้องต่อเน็ตได้")
            _concat(made, final)
        else:
            made = sorted(parts_dir.glob("*.mp3")) if parts_dir.is_dir() else []

        scenes, at = [], 0.0
        for index, text in enumerate(lines, 1):
            piece = parts_dir / f"{index:02d}.mp3"
            seconds = duration(piece) if piece.is_file() else 0.0
            scenes.append({"index": index, "text": text,
                           "seconds": round(seconds, 2), "start": round(at, 2)})
            at += seconds + GAP_SECONDS

        total = duration(final)
        return {
            "file": f"{SPEECH_DIR}/{final.name}",
            "seconds": round(total, 2),
            "over": round(max(0.0, total - CLIP_SECONDS), 2),
            "limit": CLIP_SECONDS,
            "voice": voice_key,
            "voice_label": voice_label,
            "chars": sum(len(s) for s in lines),
            "scenes": scenes,
        }
    finally:
        # เก็บชิ้นส่วนไว้ เพราะใช้บอกความยาวรายฉาก — แต่ล้างของรุ่นเก่าทิ้ง
        _sweep(out_dir, keep=stamp)


def _concat(parts: list[Path], out: Path) -> None:
    """ต่อไฟล์เสียงเข้าด้วยกัน โดยแทรกความเงียบสั้นๆ คั่นฉาก"""
    # **รายชื่อต้องวางไว้ในโฟลเดอร์เดียวกับชิ้นส่วน** — ffmpeg อ่านชื่อในรายชื่อ
    # โดยเทียบจากที่ตั้งของไฟล์รายชื่อ ไม่ใช่จากโฟลเดอร์ที่รันคำสั่ง
    listing = parts[0].parent / ".list.txt"
    silence = out.parent / ".gap.mp3"
    if not silence.is_file():
        subprocess.run(
            [_ffmpeg(), "-y", "-v", "error", "-f", "lavfi",
             "-i", f"anullsrc=r=24000:cl=mono", "-t", str(GAP_SECONDS),
             "-b:a", "48k", str(silence)],
            check=False, timeout=60,
        )
    rows = []
    for index, part in enumerate(parts):
        rows.append(f"file '{part.name}'")
        if index < len(parts) - 1 and silence.is_file():
            rows.append(f"file '../{silence.name}'")
    listing.write_text("\n".join(rows) + "\n", encoding="utf-8")
    try:
        done = subprocess.run(
            [_ffmpeg(), "-y", "-v", "error", "-f", "concat", "-safe", "0",
             "-i", str(listing), "-c", "copy", str(out)],
            capture_output=True, text=True, timeout=180,
        )
        if done.returncode or not out.is_file():
            raise SpeechError(f"ต่อไฟล์เสียงไม่สำเร็จ: {done.stderr.strip()[:200]}")
    finally:
        listing.unlink(missing_ok=True)


def _sweep(out_dir: Path, keep: str, limit: int = 4) -> None:
    """ลบเสียงรุ่นเก่าทิ้ง เหลือไว้ไม่กี่ชุด — บทถูกแก้บ่อย ไฟล์จะกองเร็ว"""
    try:
        files = sorted(out_dir.glob("*.mp3"), key=lambda p: p.stat().st_mtime,
                       reverse=True)
        for old in files[limit:]:
            old.unlink(missing_ok=True)
        for folder in sorted(out_dir.glob(".parts-*")):
            if keep not in folder.name and folder.is_dir():
                stem = folder.name.replace(".parts-", "")
                if not any(stem in f.name for f in out_dir.glob("*.mp3")):
                    shutil.rmtree(folder, ignore_errors=True)
    except OSError:
        pass


if __name__ == "__main__":                                   # ลองมือ
    import sys
    folder = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    run = json.loads((folder / "run.json").read_text(encoding="utf-8"))
    got = build(folder, run.get("script") or [],
                sys.argv[2] if len(sys.argv) > 2 else DEFAULT_VOICE)
    print(f"{got['voice_label']} · รวม {got['seconds']} วินาที "
          f"({got['chars']} ตัวอักษร)"
          + (f" · เกินคลิป {got['over']} วินาที" if got["over"] else " · พอดีคลิป"))
    for scene in got["scenes"]:
        print(f"  ฉาก {scene['index']}  {scene['seconds']:>5.2f} วิ  {scene['text']}")
    print("ไฟล์:", folder / got["file"])
