"""pipeline เจนคลิปโฆษณา 4 ซีน — พอร์ตวิธีการจาก 2.Extension/8.Auto-gen(stepbystep)

ขั้นตอนเหมือนระบบเดิมทุกประการ:
    ข้อมูลสินค้า → Gemini (คอนเซปต์ 4 ซีน) → Flow เจนรูป 4 ซีน
    → Flow เจนวิดีโอ 4 ซีน → ดาวน์โหลด → รวมด้วย ffmpeg → {รุ่น} full.mp4

ต่างจากเดิมตรงที่ใช้ Playwright แทน Chrome Extension จึง:
    - ไม่ต้องเปิด side panel ค้างไว้ (ปิดหน้าต่างไหนก็ได้ worker ทำต่อ)
    - ไม่มีแบนเนอร์ "เริ่มการแก้ไขข้อบกพร่อง" และเปิด DevTools ได้
    - รันเป็นคิวเบื้องหลังได้จริง ไม่ต้องเฝ้า

ตัวขับหน้า Flow อยู่ที่ flow_driver.py (ยก logic ตรวจจับมาเป็น JS ชุดเดิม)
"""

from __future__ import annotations

import base64
import json
import mimetypes
import re
import shutil
import subprocess
import time
from collections.abc import Callable
from pathlib import Path

import httpx

import flow_driver
import tiktok_post
import gemini_quota
from flow_driver import (
    FlowDriver,
    FlowError,
    NeedsLogin,
    PolicyBlocked,
    UnusualActivity,
)

# ซ่อนหน้าต่างคอนโซลตอนสั่งโปรแกรมภายนอก — ไม่ให้กะพริบใส่ผู้ใช้
# ประกาศในไฟล์เองแทนการ import studio_shared เพื่อไม่เพิ่มสายพึ่งพาโดยไม่จำเป็น
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

SCENE_COUNT = 4
BATCH_PAUSE_SECONDS = 10   # พักระหว่างรุ่น ลดโอกาสโดน Google จำกัดการใช้งาน
UNUSUAL_PAUSE_SECONDS = 300  # โดน flag กิจกรรมผิดปกติ ต้องพักยาว
MERGE_SIZE = "1080x1920"
MERGE_FPS = 30
SILENCE_DB = -32           # ค่าเริ่มต้นเดียวกับระบบเดิม
SILENCE_MIN_SECONDS = 0.6
SILENCE_MAX_SEGMENTS = 120  # เสียงแตกย่อยเกินนี้ = ไม่ตัด (กันคลิปกระตุก)

GEMINI_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models"

SCENE_SYSTEM_PROMPT = """คุณคือผู้กำกับโฆษณาสินค้าสำหรับคลิปแนวตั้ง 9:16
สร้างคอนเซปต์คลิปโฆษณาความยาวรวมประมาณ 32 วินาที แบ่งเป็น 4 ซีน ซีนละ ~8 วินาที

ตอบกลับเป็น JSON เท่านั้น ห้ามมีข้อความอื่นนอก JSON รูปแบบ:
{"scenes":[{"image_prompt":"...","video_prompt":"...","speech":"..."}, ... 4 ชิ้น]}

image_prompt  = คำสั่งภาษาอังกฤษสำหรับสร้างภาพนิ่งของซีนนั้น (บรรยายภาพ มุมกล้อง แสง)
video_prompt  = คำสั่งภาษาอังกฤษสำหรับทำให้ภาพนั้นเคลื่อนไหว (การเคลื่อนกล้อง การเคลื่อนไหวในเฟรม)
speech        = บทพูดภาษาไทยสั้นๆ ของซีนนั้น (ไม่เกิน 2 ประโยค)
"""


# ------------------------------------------------------------ ขั้นที่ 1: Gemini


def build_scene_parts(instruction: str, product_image: Path | None = None,
                      log: Callable[[str], None] = print) -> list[dict]:
    """ประกอบ `parts` ที่จะส่งให้ Gemini — ข้อความ แล้วต่อด้วยรูปสินค้าถ้ามี

    **ระบบเดิมส่งรูปไปด้วยเสมอถ้ามี** (`2.Extension/8.Auto-gen(stepbystep)/
    sidepanel/app.js:1533`) เพราะคอนเซปต์ที่ได้จะอิงหน้าตาสินค้าจริง ไม่ใช่
    จินตนาการจากชื่อรุ่นอย่างเดียว

    ใช้ชื่อคีย์แบบ snake_case (`inline_data` / `mime_type`) ตามที่ฝั่ง Python
    ของโปรเจกต์นี้ใช้อยู่จริงและผ่านของจริงมาแล้ว (`shopee_scrape.judge_images`)
    ต้นฉบับเป็น JS จึงเป็น camelCase — REST รับได้ทั้งสองแบบ แต่เอาให้เหมือน
    เพื่อนบ้านในภาษาเดียวกันดีกว่า

    อ่านรูปไม่ได้ = **เตือนแล้วส่งเฉพาะข้อความ ไม่ล้มทั้งงาน** (ตามระบบเดิม)
    แต่ห้ามเงียบ เพราะคอนเซปต์ที่ได้จะคุณภาพต่างจากที่ควรได้ (กติกาข้อ 2.4)
    """
    parts: list[dict] = [{"text": instruction}]
    if product_image is None:
        return parts
    try:
        payload = Path(product_image).read_bytes()
    except OSError as error:
        log(f"⚠️ อ่านรูปสินค้า {product_image} ไม่ได้ ({error}) — ส่งเฉพาะข้อความ")
        return parts
    mime = mimetypes.guess_type(str(product_image))[0] or "image/jpeg"
    parts.append({
        "inline_data": {
            "mime_type": mime,
            "data": base64.b64encode(payload).decode("ascii"),
        }
    })
    return parts


def generate_scenes(
    api_key: str, model: str, product: str, detail: str,
    product_image: Path | None = None, log: Callable[[str], None] = print,
) -> list[dict]:
    """ให้ Gemini แตกข้อมูลสินค้าเป็นคอนเซปต์ 4 ซีน

    ระบบเดิมถ้าแตกซีนไม่ครบ 4 จะขอใหม่อัตโนมัติสูงสุด 2 รอบ — ทำเหมือนกัน
    """
    instruction = (
        f"{SCENE_SYSTEM_PROMPT}\n\nสินค้า: {product}\nรายละเอียด: {detail}"
    )
    parts = build_scene_parts(instruction, product_image, log)
    last_error = ""
    for attempt in range(1, 3 + 1):
        response = httpx.post(
            f"{GEMINI_ENDPOINT}/{model}:generateContent",
            params={"key": api_key},
            json={
                "contents": [{"parts": parts}],
                "generationConfig": {"responseMimeType": "application/json"},
            },
            timeout=flow_driver.TIMEOUTS["gemini_reply"],
        )
        gemini_quota.record(model, ok=response.status_code == 200,
                            response=response)
        if response.status_code != 200:
            last_error = f"HTTP {response.status_code}: {response.text[:200]}"
            continue
        try:
            text = response.json()["candidates"][0]["content"]["parts"][0]["text"]
            scenes = json.loads(text)["scenes"]
        except (KeyError, IndexError, ValueError) as error:
            last_error = f"อ่านคำตอบไม่ได้: {error}"
            continue
        if len(scenes) == SCENE_COUNT:
            return scenes
        last_error = f"ได้ {len(scenes)} ซีน ไม่ครบ {SCENE_COUNT}"
    raise FlowError(f"Gemini แตกคอนเซปต์ไม่สำเร็จ: {last_error}")


# --------------------------------------------------------- ขั้นที่ 2-4: Flow


def scene_paths(out_dir: Path, name: str, index: int) -> tuple[Path, Path]:
    """ตั้งชื่อไฟล์แบบเดียวกับระบบเดิม: '{รุ่น} scene N.png/.mp4'"""
    return (
        out_dir / f"{name} scene {index}.png",
        out_dir / f"{name} scene {index}.mp4",
    )


def missing_files(out_dir: Path, name: str) -> list[int]:
    """คืนเลขซีนที่ไฟล์ยังไม่ครบ (ใช้กับโหมด 'ลองเฉพาะที่ขาด')"""
    missing = []
    for index in range(1, SCENE_COUNT + 1):
        image, video = scene_paths(out_dir, name, index)
        if not image.is_file() or not video.is_file():
            missing.append(index)
    return missing


def run_scenes(
    driver: FlowDriver,
    scenes: list[dict],
    out_dir: Path,
    name: str,
    only: list[int] | None = None,
    product_image: Path | None = None,
    projects: dict | None = None,
    log=print,
) -> dict:
    """เจนรูปแล้วต่อด้วยวิดีโอทีละซีน

    ระบบเดิมทำรูปครบ 4 ก่อนแล้วค่อยทำวิดีโอ — ทำตามนั้น เพราะถ้ารูปพัง
    จะได้รู้ตั้งแต่ยังไม่เสียเครดิตวิดีโอ (วิดีโอแพงกว่ามาก)
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    targets = only or list(range(1, SCENE_COUNT + 1))
    # โปรเจกต์ Flow แยกต่อซีน — เก็บไว้เพื่อกลับเข้าตอนเจนวิดีโอและตอน retry
    projects = projects if projects is not None else {}
    result = {"ok": [], "failed": {}, "projects": projects}

    for index in targets:
        image_path, _ = scene_paths(out_dir, name, index)
        if image_path.is_file():
            log(f"  ซีน {index}: มีรูปอยู่แล้ว ข้าม")
            continue
        log(f"  ซีน {index}: เจนรูป")
        try:
            # โปรเจกต์ใหม่ต่อซีน — baseline สะอาด ไทล์ซีนก่อนไม่มาปน
            key = str(index)
            if projects.get(key):
                driver.goto_project(projects[key])
            else:
                projects[key] = driver.new_project()
            driver.generate(
                scenes[index - 1]["image_prompt"], "image", image_path,
                start_image=product_image,
            )
        except PolicyBlocked as error:
            # ไม่ retry ด้วย prompt เดิม ตามกติกาเดิม
            result["failed"][index] = f"policy: {error}"
            log(f"  ซีน {index}: ขัดนโยบาย ไม่ลองซ้ำด้วย prompt เดิม")
            continue
        except FlowError as error:
            result["failed"][index] = str(error)
            continue

    for index in targets:
        if index in result["failed"]:
            continue
        image_path, video_path = scene_paths(out_dir, name, index)
        if video_path.is_file():
            log(f"  ซีน {index}: มีวิดีโออยู่แล้ว ข้าม")
            result["ok"].append(index)
            continue
        if not image_path.is_file():
            result["failed"][index] = "ไม่มีรูปตั้งต้น"
            continue
        log(f"  ซีน {index}: เจนวิดีโอ")
        try:
            # กลับเข้าโปรเจกต์ของซีนนั้น (รูปตั้งต้นอยู่ในโปรเจกต์เดียวกัน)
            if projects.get(str(index)):
                driver.goto_project(projects[str(index)])
            else:
                projects[str(index)] = driver.new_project()
            driver.generate(
                scenes[index - 1]["video_prompt"], "video", video_path,
                start_image=image_path,
            )
            result["ok"].append(index)
        except PolicyBlocked as error:
            result["failed"][index] = f"policy: {error}"
        except FlowError as error:
            result["failed"][index] = str(error)
    return result


# ------------------------------------------------------------ ขั้นที่ 5: รวมคลิป


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def merge_scenes(out_dir: Path, name: str, log=print) -> Path:
    """รวม 4 ซีนเป็นไฟล์เดียว 1080×1920 30fps มีเสียง (เหมือนระบบเดิม)"""
    if not ffmpeg_available():
        raise FlowError("ไม่พบ ffmpeg ใน PATH (winget install Gyan.FFmpeg)")
    parts = [scene_paths(out_dir, name, i)[1] for i in range(1, SCENE_COUNT + 1)]
    for part in parts:
        if not part.is_file():
            raise FlowError(f"ยังไม่มีไฟล์ {part.name} รวมคลิปไม่ได้")
    target = out_dir / f"{name} full.mp4"
    listing = out_dir / "_merge_list.txt"
    listing.write_text(
        "\n".join(f"file '{part.name}'" for part in parts), encoding="utf-8"
    )
    command = [
        "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(listing),
        "-vf", f"scale={MERGE_SIZE.replace('x', ':')}:force_original_aspect_ratio=decrease,"
               f"pad={MERGE_SIZE.replace('x', ':')}:(ow-iw)/2:(oh-ih)/2,fps={MERGE_FPS}",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(target),
    ]
    result = subprocess.run(command, capture_output=True, cwd=str(out_dir), creationflags=_NO_WINDOW)
    listing.unlink(missing_ok=True)
    if result.returncode != 0:
        raise FlowError(
            "ffmpeg รวมคลิปไม่สำเร็จ: "
            + result.stderr.decode("utf-8", errors="replace")[-300:]
        )
    log(f"  รวมคลิปแล้ว → {target.name}")
    return target


def trim_silence(source: Path, log=print) -> Path | None:
    """ตัดช่วงที่ไม่มีบทพูดออก

    กันพลาดแบบเดียวกับระบบเดิม: ทั้งคลิปเงียบ / ช่วงเงียบรวมน้อยกว่า 0.3 วิ /
    เสียงแตกย่อยเกิน 120 ช่วง → ไม่ตัด แล้ว log บอกเหตุผล
    """
    if not ffmpeg_available():
        return None
    probe = subprocess.run(
        ["ffmpeg", "-i", str(source), "-af",
         f"silencedetect=noise={SILENCE_DB}dB:d={SILENCE_MIN_SECONDS}", "-f", "null", "-"],
        capture_output=True, creationflags=_NO_WINDOW)
    text = probe.stderr.decode("utf-8", errors="replace")
    starts = [float(m) for m in re.findall(r"silence_start: ([\d.]+)", text)]
    ends = [float(m) for m in re.findall(r"silence_end: ([\d.]+)", text)]
    if not starts:
        log("  ไม่พบช่วงเงียบ — ไม่ตัด")
        return None
    if len(starts) > SILENCE_MAX_SEGMENTS:
        log(f"  เสียงแตกย่อย {len(starts)} ช่วง เกินเพดาน — ไม่ตัด กันคลิปกระตุก")
        return None

    duration = _media_duration(source)
    keep: list[tuple[float, float]] = []
    cursor = 0.0
    for index, start in enumerate(starts):
        if start > cursor:
            keep.append((cursor, start))
        cursor = ends[index] if index < len(ends) else duration
    if cursor < duration:
        keep.append((cursor, duration))
    kept = sum(end - begin for begin, end in keep)
    if not keep or kept < 0.3:
        log("  ตัดแล้วจะเหลือสั้นเกินไป — ไม่ตัด")
        return None

    target = source.with_name(source.stem + " trimmed.mp4")
    parts = "".join(
        f"[0:v]trim={b}:{e},setpts=PTS-STARTPTS[v{i}];"
        f"[0:a]atrim={b}:{e},asetpts=PTS-STARTPTS[a{i}];"
        for i, (b, e) in enumerate(keep)
    )
    concat = "".join(f"[v{i}][a{i}]" for i in range(len(keep)))
    graph = f"{parts}{concat}concat=n={len(keep)}:v=1:a=1[v][a]"
    result = subprocess.run(
        ["ffmpeg", "-y", "-i", str(source), "-filter_complex", graph,
         "-map", "[v]", "-map", "[a]", str(target)],
        capture_output=True, creationflags=_NO_WINDOW)
    if result.returncode != 0:
        log("  ตัดช่วงเงียบไม่สำเร็จ — ใช้ไฟล์เต็มแทน")
        return None
    log(f"  ตัดช่วงเงียบแล้ว {duration:.1f} → {kept:.1f} วิ ({len(keep)} ช่วงพูด)")
    return target


def _media_duration(path: Path) -> float:
    result = subprocess.run(
        ["ffmpeg", "-i", str(path)], capture_output=True, creationflags=_NO_WINDOW)
    text = result.stderr.decode("utf-8", errors="replace")
    match = re.search(r"Duration: (\d+):(\d+):([\d.]+)", text)
    if not match:
        return 0.0
    hours, minutes, seconds = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


# ------------------------------------------------------------------ ทั้ง pipeline


def run_pipeline(
    page,
    api_key: str,
    gemini_model: str,
    product: str,
    detail: str,
    out_dir: Path,
    project_url: str = "",
    product_image: Path | None = None,
    projects: dict | None = None,
    scenes: list[dict] | None = None,
    only_missing: bool = False,
    do_merge: bool = True,
    do_trim: bool = True,
    post_tiktok: bool = False,
    tiktok_tags: list[str] | None = None,
    log=print,
) -> dict:
    """รันครบทั้ง pipeline ของหนึ่งรุ่น คืนสรุปผล"""
    driver = FlowDriver(page, log=log, debug_dir=out_dir)
    summary: dict = {"product": product, "scenes": [], "video": None, "errors": {}}

    # กติกาเดิม: รันซ้ำต้องใช้ prompt ชุดเดิมที่เก็บไว้ ไม่เรียก Gemini ใหม่
    # ไม่งั้น prompt จะไม่ตรงกับรูปที่เจนไว้แล้ว วิดีโอจะหลุดคอนเซปต์
    saved = out_dir / "scenes.json"
    if scenes is None and saved.is_file():
        try:
            scenes = json.loads(saved.read_text(encoding="utf-8"))
            log(f"ใช้คอนเซปต์เดิมจาก {saved.name} ({len(scenes)} ซีน) ไม่เรียก Gemini ใหม่")
        except (OSError, ValueError):
            scenes = None

    if scenes is None:
        log("ขั้น 1/5 — Gemini แตกคอนเซปต์ 4 ซีน")
        scenes = generate_scenes(
            api_key, gemini_model, product, detail, product_image=product_image,
            log=log,
        )
        (out_dir).mkdir(parents=True, exist_ok=True)
        (out_dir / "scenes.json").write_text(
            json.dumps(scenes, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    summary["scenes"] = scenes

    # ไม่เปิดโปรเจกต์รวมอีกต่อไป — แต่ละซีนใช้โปรเจกต์ของตัวเอง
    projects = dict(projects or {})
    if project_url:
        log("ขั้น 2/5 — ใช้โปรเจกต์ที่ระบุมาสำหรับทุกซีน")
        driver.goto_project(project_url)
        for index in range(1, SCENE_COUNT + 1):
            projects.setdefault(str(index), project_url)
    else:
        log("ขั้น 2/5 — จะสร้างโปรเจกต์ใหม่แยกต่อซีน")
    summary["projects"] = projects

    only = missing_files(out_dir, product) if only_missing else None
    if only_missing:
        log(f"ขั้น 3-4/5 — ทำเฉพาะซีนที่ขาด: {only or 'ไม่มี'}")
        if not only:
            log("  ครบอยู่แล้ว ไม่ต้องเจนใหม่")
    else:
        log("ขั้น 3-4/5 — เจนรูปแล้วต่อด้วยวิดีโอ")
    outcome = run_scenes(
        driver, scenes, out_dir, product, only=only,
        product_image=product_image, projects=projects, log=log,
    )
    summary["projects"] = outcome.get("projects", projects)
    summary["errors"] = outcome["failed"]

    if do_merge and not missing_files(out_dir, product):
        log("ขั้น 5/5 — รวมคลิป")
        merged = merge_scenes(out_dir, product, log=log)
        summary["video"] = str(merged)
        if do_trim:
            trimmed = trim_silence(merged, log=log)
            if trimmed:
                summary["video"] = str(trimmed)
    elif do_merge:
        log("ยังมีซีนขาด — ข้ามขั้นรวมคลิป")

    # ขั้นสุดท้าย: โพสต์ขึ้น TikTok (คลิปอยู่บนคอมแล้ว ไม่ต้อง push เข้ามือถือ)
    if post_tiktok and summary.get("video"):
        log("ขั้น 6/6 — โพสต์ขึ้น TikTok")
        try:
            poster = tiktok_post.TikTokPoster(page, log=log)
            caption = " ".join(
                scene.get("speech", "") for scene in scenes[:1]
            ).strip() or product
            # ดึงแฮชแท็กและ product id จาก 5 ช่องที่กรอกไว้ (เหมือนระบบเดิม)
            # แท็กที่ส่งมากับงานมาก่อน ถ้าไม่ระบุค่อยใช้ของช่อง
            slot = tiktok_post.slot_for(product) or {}
            tags = tiktok_tags or [t for t in (slot.get("tags") or "").split() if t]
            if slot.get("pid"):
                log(f"  ใช้ช่อง code={slot.get('code') or '(ว่าง)'} pid={slot['pid']}")
            summary["tiktok"] = poster.post(
                Path(summary["video"]), caption=caption, tags=tags,
                pid=slot.get("pid", ""), ptxt=slot.get("ptxt", ""),
            )
            # นับเข้าโควตาต่อวันชุดเดียวกับการโพสต์แบบชุด ไม่งั้นโพสต์ผ่านคิวงาน
            # จะไม่ถูกนับ แล้วยอดรวมต่อ 24 ชม. จะเกินลิมิตจริงโดยไม่รู้ตัว
            history = tiktok_post.PostHistory()
            history.mark_posted(Path(summary["video"]).name)
            history.record_post()
        except tiktok_post.TikTokNeedsLogin as error:
            log(f"  {error}")
            summary["tiktok"] = {"ok": False, "needs_login": True, "error": str(error)}
        except tiktok_post.TikTokError as error:
            log(f"  โพสต์ TikTok ไม่สำเร็จ: {error}")
            summary["tiktok"] = {"ok": False, "error": str(error)}
    elif post_tiktok:
        log("ยังไม่มีไฟล์คลิปรวม — ข้ามขั้นโพสต์ TikTok")
    return summary


def run_batch(
    page,
    api_key: str,
    gemini_model: str,
    items: list[dict],
    root: Path,
    log=print,
    **kwargs,
) -> list[dict]:
    """ทำต่อเนื่องหลายรุ่น — รุ่นไหนพัง log แล้วไปต่อ ไม่หยุดทั้งคิว
    พัก 10 วินาทีระหว่างรุ่น (ลดโอกาสโดน Google จำกัดการใช้งาน)"""
    results = []
    for index, item in enumerate(items, start=1):
        product = item["product"]
        log(f"\n=== [{index}/{len(items)}] {product} ===")
        try:
            summary = run_pipeline(
                page, api_key, gemini_model, product, item.get("detail", ""),
                root / product, log=log, **kwargs,
            )
            summary["status"] = "done" if not summary["errors"] else "partial"
        except UnusualActivity as error:
            log(f"  โดนจำกัดการใช้งาน พัก {UNUSUAL_PAUSE_SECONDS} วิ: {error}")
            summary = {"product": product, "status": "paused", "error": str(error)}
            time.sleep(UNUSUAL_PAUSE_SECONDS)
        except NeedsLogin as error:
            log(f"  ต้องล็อกอินใหม่ หยุดคิว: {error}")
            results.append({"product": product, "status": "needs_login", "error": str(error)})
            break
        except Exception as error:
            log(f"  พัง: {type(error).__name__}: {error}")
            summary = {"product": product, "status": "failed", "error": str(error)}
        results.append(summary)
        if index < len(items):
            time.sleep(BATCH_PAUSE_SECONDS)
    ok = sum(1 for r in results if r.get("status") == "done")
    log(f"\nสรุป: สำเร็จ {ok}/{len(items)} รุ่น")
    return results
