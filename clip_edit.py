"""ตัดต่อคลิปหลังเจนเสร็จ — ตัดภาพช่วงที่เสียออก แล้วเร่งเสียงให้พูดจบพอดี

**เจ้าของสั่ง 30 ส.ค. 2569** — *"เพิ่ม function ตัดต่อหลังทำคลิปเสร็จ
เจนคลิป -> ตัดต่อ -> อนุมัติ ถ้าคลิปไหนมีสตอรีบอร์ดในคลิปให้ตัดรูปช่วงนั้นออก
แต่เสียงไม่ต้องตัด ให้ใช้การกรอเร็วเอาในช่วงนั้น"* แล้วระบุเพิ่มว่า
*"ตัด 4-6 · ปรับบทพูดตั้งแต่วินาทีที่ 4 ไปถึง 10 ให้ขึ้นเพื่อให้พูดทันคลิปจบ ·
การรันภาพ 6-10 วิ ยังเหมือนเดิม"*

สิ่งที่ทำ (ตัวอย่างคลิป 10 วินาที ตัดช่วง 4–6)
------------------------------------------------
    ภาพ    0–4 เดิม  +  6–10 เดิม            = 8 วินาที   (ช่วง 4–6 หายไป)
    เสียง  0–4 เดิม  +  4–10 บีบลงใน 4 วิ    = 8 วินาที   (พูดครบ แค่เร็วขึ้น 1.5 เท่า)

**ภาพไม่ถูกยืดหรือบีบเลย** ความเร็วภาพคงเดิมทุกเฟรมที่เหลืออยู่ ที่ปรับคือเสียงอย่างเดียว
ใช้ `atempo` ซึ่ง**คงระดับเสียงไว้** ไม่ทำให้เสียงแหลมเป็นการ์ตูน

ทำไมถึงเลือกวิธีนี้ (เจ้าของตัดสินเอง)
---------------------------------------
ทางเลือกอื่นที่เสนอไปแล้วไม่เอา:
  · กรอภาพเร็วผ่านช่วงเสีย → คนดูจับได้ทันทีว่าภาพวิ่งผิดจังหวะ และภาพหมดก่อนเสียง
  · ตัดภาพแล้วฉายช้าลงให้ยาวเท่าเดิม → ภาพช้าทั้งคลิป และคลิปยังยาว 10 วินาที
วิธีที่เลือกได้คลิปสั้นลงจริง (8 วินาที) แต่ภาพลื่นปกติและได้ยินบทครบทุกคำ

ข้อจำกัดที่ต้องรู้
-------------------
**ยิ่งตัดมาก เสียงยิ่งต้องเร็วขึ้น** และเร็วเกินไปคนฟังไม่รู้เรื่อง
`MAX_TEMPO` จึงกันไว้ที่ 1.6 เท่า **เกินแล้วปฏิเสธเสียงดัง ไม่ใช่ทำให้แล้วเงียบ**
เพราะคลิปที่ฟังไม่รู้เรื่องเสียเปล่ากว่าคลิปที่ยังไม่ได้ตัด

**ห้ามเขียนทับไฟล์เดิมเด็ดขาด** ผลลัพธ์ออกเป็นไฟล์ใหม่เสมอ ตัดผิดช่วงแล้วยังถอยได้
(เคยมีสคริปต์ทดสอบลบข้อมูลจริงหายถาวรมาแล้ว 13 ส.ค. 2569)

ใช้จากบรรทัดคำสั่ง
-------------------
    python clip_edit.py <item_id> <เริ่ม> <จบ>     ตัดคลิปของสินค้านั้น
    python clip_edit.py <ไฟล์.mp4> <เริ่ม> <จบ>    ตัดไฟล์ตรงๆ
    python clip_edit.py plan <ไฟล์.mp4> 4 6        ดูว่าจะได้อะไร โดยยังไม่ตัดจริง
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

# เร็วกว่านี้คนฟังไม่ทัน — วัดจากบทพูดไทย 135 ตัวอักษรใน 10 วินาที (13.5 ตัว/วินาที)
# ที่ 1.6 เท่าคือ 21.6 ตัว/วินาที ซึ่งเป็นเพดานที่ยังฟังออก
MAX_TEMPO = 1.6

# ffmpeg ยอมให้ atempo ตัวเดียวไม่เกิน 2.0 — เกินต้องต่อกันหลายตัว
ATEMPO_MAX = 2.0

EDITED_NAME = "clip-edited.mp4"


class EditError(RuntimeError):
    """ตัดต่อไม่ได้ พร้อมเหตุผลภาษาคน"""


def _tool(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise EditError(f"เครื่องนี้ไม่มี {name} — ติดตั้งก่อนถึงจะตัดต่อได้")
    return path


def duration(video: Path) -> float:
    """คลิปยาวกี่วินาที — อ่านจากไฟล์จริง ไม่ใช่เดาจากชื่อหรือค่าตั้ง"""
    out = subprocess.run(
        [_tool("ffprobe"), "-v", "error", "-show_entries", "format=duration",
         "-of", "json", str(video)],
        capture_output=True, text=True, check=False)
    if out.returncode != 0:
        raise EditError(f"อ่านความยาวคลิปไม่ได้: {(out.stderr or '')[:120]}")
    try:
        return float(json.loads(out.stdout)["format"]["duration"])
    except (KeyError, ValueError, json.JSONDecodeError) as error:
        raise EditError(f"ไฟล์นี้อ่านความยาวไม่ออก ({error})") from error


def has_audio(video: Path) -> bool:
    """มีแทร็กเสียงไหม — ไม่มีแล้วสั่งเร่งเสียงจะพังเงียบๆ"""
    out = subprocess.run(
        [_tool("ffprobe"), "-v", "error", "-select_streams", "a",
         "-show_entries", "stream=index", "-of", "csv=p=0", str(video)],
        capture_output=True, text=True, check=False)
    return bool((out.stdout or "").strip())


def _atempo_chain(factor: float) -> str:
    """แตกอัตราเร่งเป็น atempo หลายตัวเมื่อเกิน 2.0 เท่า"""
    parts = []
    left = factor
    while left > ATEMPO_MAX:
        parts.append(f"atempo={ATEMPO_MAX}")
        left /= ATEMPO_MAX
    parts.append(f"atempo={left:.6f}")
    return ",".join(parts)


def plan(video: Path, start: float, end: float) -> dict:
    """คิดว่าตัดแล้วจะได้อะไร โดยยังไม่แตะไฟล์ — ใช้ตรวจก่อนลงมือ"""
    total = duration(video)
    if not 0 <= start < end <= total + 0.001:
        raise EditError(
            f"ช่วงที่สั่งตัด {start}–{end} วินาที อยู่นอกคลิปที่ยาว {total:.1f} วินาที")
    cut = end - start
    left = total - cut
    if left <= 0.5:
        raise EditError("ตัดแล้วแทบไม่เหลือคลิป — ช่วงที่สั่งตัดยาวเกินไป")
    # เสียงตั้งแต่จุดเริ่มตัดจนจบ ต้องบีบลงในเวลาที่เหลือหลังจุดเริ่มตัด
    tail_was = total - start
    tail_now = left - start
    if tail_now <= 0:
        raise EditError("ตัดถึงท้ายคลิปแล้วไม่เหลือที่ให้เสียงท่อนหลังเลย")
    tempo = tail_was / tail_now
    return {
        "total": round(total, 2), "start": start, "end": end,
        "cut": round(cut, 2), "left": round(left, 2),
        "tail_was": round(tail_was, 2), "tail_now": round(tail_now, 2),
        "tempo": round(tempo, 3),
        "ok": tempo <= MAX_TEMPO,
        "audio": has_audio(video),
    }


def describe(step: dict) -> str:
    """อธิบายแผนเป็นภาษาคน"""
    lines = [
        f"คลิปเดิมยาว {step['total']:.1f} วินาที",
        f"ตัดภาพช่วง {step['start']:.1f}–{step['end']:.1f} วินาทีออก "
        f"({step['cut']:.1f} วินาที)",
        f"ภาพที่เหลือความเร็วเท่าเดิมทุกเฟรม → คลิปใหม่ยาว {step['left']:.1f} วินาที",
        f"เสียงตั้งแต่วินาทีที่ {step['start']:.1f} ถึงจบ ({step['tail_was']:.1f} วินาที) "
        f"บีบลงใน {step['tail_now']:.1f} วินาที = พูดเร็วขึ้น {step['tempo']:.2f} เท่า",
    ]
    if not step["audio"]:
        lines.append("⚠️ คลิปนี้ไม่มีเสียง — จะตัดแต่ภาพอย่างเดียว")
    if not step["ok"]:
        lines.append(f"❌ เร็วเกินเพดาน {MAX_TEMPO} เท่า — ฟังไม่รู้เรื่อง ไม่ตัดให้")
    return "\n".join("  " + line for line in lines)


def cut_and_fit(video: Path, start: float, end: float,
                out: Path | None = None, log=print) -> Path:
    """ตัดภาพช่วง start–end ออก แล้วเร่งเสียงท่อนหลังให้พอดีคลิปใหม่

    คืนพาธไฟล์ใหม่ · **ไม่แตะไฟล์เดิมเลย**
    """
    video = Path(video)
    if not video.is_file():
        raise EditError(f"ไม่เจอไฟล์คลิป {video}")
    step = plan(video, start, end)
    log(describe(step))
    if not step["ok"]:
        raise EditError(
            f"ต้องเร่งเสียง {step['tempo']:.2f} เท่าถึงจะพูดทัน ซึ่งเกินเพดาน "
            f"{MAX_TEMPO} เท่า — ตัดช่วงให้สั้นลง หรือยอมให้คลิปยาวเท่าเดิม")

    out = Path(out) if out else video.with_name(EDITED_NAME)
    if out.resolve() == video.resolve():
        raise EditError("ปลายทางซ้ำกับไฟล์เดิม — ห้ามเขียนทับต้นฉบับ")

    total, tempo = step["total"], step["tempo"]
    chain = [
        f"[0:v]trim=0:{start},setpts=PTS-STARTPTS[v0]",
        f"[0:v]trim={end}:{total},setpts=PTS-STARTPTS[v1]",
        "[v0][v1]concat=n=2:v=1:a=0[v]",
    ]
    maps = ["-map", "[v]"]
    if step["audio"]:
        chain += [
            f"[0:a]atrim=0:{start},asetpts=PTS-STARTPTS[a0]",
            f"[0:a]atrim={start},asetpts=PTS-STARTPTS,{_atempo_chain(tempo)}[a1]",
            "[a0][a1]concat=n=2:v=0:a=1[a]",
        ]
        maps += ["-map", "[a]"]

    cmd = [_tool("ffmpeg"), "-v", "error", "-y", "-i", str(video),
           "-filter_complex", ";".join(chain), *maps,
           "-c:v", "libx264", "-preset", "medium", "-crf", "18",
           "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
           "-movflags", "+faststart", str(out)]
    done = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if done.returncode != 0:
        raise EditError(f"ffmpeg ตัดไม่สำเร็จ: {(done.stderr or '')[:300]}")
    if not out.is_file() or out.stat().st_size < 10_000:
        raise EditError("ตัดแล้วได้ไฟล์เปล่าหรือเล็กผิดปกติ")

    # **ตรวจผลลัพธ์ ไม่ใช่ตรวจว่าสั่งไปแล้ว** (กติกาข้อ 2.3.1 ข้อ 2)
    got = duration(out)
    want = step["left"]
    if abs(got - want) > 0.35:
        raise EditError(
            f"ตัดแล้วความยาวไม่ตรงที่ควรได้ — ได้ {got:.2f} วินาที "
            f"แต่ควรเป็น {want:.2f} วินาที")
    log(f"  ✅ ได้ไฟล์ใหม่ {out.name} ยาว {got:.2f} วินาที "
        f"({out.stat().st_size/1024/1024:.1f} MB)")
    return out


def find_clip(item_id: str) -> Path:
    """หาไฟล์คลิปของสินค้ารหัสนี้"""
    for pattern in (f"*/{item_id}/video/*.mp4", f"*/{item_id}/*.mp4"):
        hits = sorted(Path("data").glob(pattern))
        hits = [h for h in hits if h.name != EDITED_NAME]
        if hits:
            return hits[0]
    raise EditError(f"ไม่เจอคลิปของสินค้า {item_id}")


def main(argv: list[str]) -> int:
    args = argv[1:]
    dry = False
    if args and args[0] == "plan":
        dry, args = True, args[1:]
    if len(args) != 3:
        print(__doc__.split("ใช้จากบรรทัดคำสั่ง")[-1].strip())
        return 2
    target, start, end = args[0], float(args[1]), float(args[2])
    try:
        video = Path(target) if target.lower().endswith(".mp4") else find_clip(target)
        if dry:
            print(f"คลิป: {video}")
            print(describe(plan(video, start, end)))
        else:
            cut_and_fit(video, start, end)
    except EditError as error:
        print(f"❌ {error}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
