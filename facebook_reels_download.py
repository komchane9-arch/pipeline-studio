"""Public clip downloads from several platforms, isolated from all publishing queues.

เจ้าของสั่ง 21 ก.ย. 2569 ให้รับลิงก์จากแพลตฟอร์มอื่นเพิ่ม และให้เลือกโฟลเดอร์
ที่จะเก็บคลิปได้เอง ของเดิมรับเฉพาะ Facebook Reels และเก็บลงที่เดียวตายตัว

ชื่อไฟล์กับที่อยู่ของ API ยังขึ้นต้นว่า facebook-reels ตามเดิม **โดยตั้งใจ** —
เปลี่ยนชื่อตอนนี้จะไปชนกับงานที่อีกเซสชันยังทำค้างอยู่ในไฟล์เดียวกัน
ชื่อเป็นเรื่องรอง ส่วนของที่ใช้งานได้จริงมาก่อน
"""
import json
import os
import re
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel


# แพลตฟอร์มที่รับ — (ชื่อที่เอาไว้บอกคน, โฮสต์ที่ยอม, รูปแบบ path ที่ยอม)
#
# **ยอมเฉพาะที่ระบุไว้ ไม่ใช่ยอมทุกอย่างที่ yt-dlp เปิดได้** yt-dlp รองรับเว็บ
# เป็นพันแห่ง ถ้าเปิดหมดก็เท่ากับยิงคำสั่งไปที่ไหนก็ได้ตามที่พิมพ์มา
# ด่านนี้จึงระบุทีละแพลตฟอร์มตามที่เจ้าของขอ และตรวจ path ด้วย ไม่ใช่ดูแค่โฮสต์
PLATFORMS: tuple[tuple[str, frozenset, str], ...] = (
    ("Facebook", frozenset({"facebook.com", "www.facebook.com",
                            "m.facebook.com", "web.facebook.com"}),
     r"/(?:reel/\d+|share/r/[A-Za-z0-9_-]+|share/v/[A-Za-z0-9_-]+|videos/\d+)/?"),
    ("X", frozenset({"x.com", "www.x.com", "twitter.com",
                     "www.twitter.com", "mobile.twitter.com"}),
     r"/[A-Za-z0-9_]{1,20}/status/\d+/?"),
    ("TikTok", frozenset({"tiktok.com", "www.tiktok.com", "m.tiktok.com"}),
     r"/@[\w.\-]{1,40}/video/\d+/?"),
    # ลิงก์ย่อของ TikTok ที่ปุ่มแชร์ในแอปให้มา
    ("TikTok", frozenset({"vm.tiktok.com", "vt.tiktok.com"}),
     r"/[A-Za-z0-9]{4,20}/?"),
    ("Instagram", frozenset({"instagram.com", "www.instagram.com"}),
     r"/(?:reel|reels|p|tv)/[A-Za-z0-9_-]+/?"),
    ("Reddit", frozenset({"reddit.com", "www.reddit.com", "old.reddit.com"}),
     r"/r/[A-Za-z0-9_]{1,30}/(?:comments/[A-Za-z0-9]+(?:/[^/]*)?|s/[A-Za-z0-9]+)/?"),
    ("YouTube", frozenset({"youtube.com", "www.youtube.com", "m.youtube.com"}),
     r"/(?:watch|shorts/[\w-]{5,20}|live/[\w-]{5,20})/?"),
    ("YouTube", frozenset({"youtu.be"}), r"/[\w-]{5,20}/?"),
)

SUPPORTED = "Facebook · X · TikTok · Instagram · Reddit · YouTube"


def validate_url(value: str) -> tuple[str, str]:
    """คืน (ลิงก์, ชื่อแพลตฟอร์ม) — ไม่เข้าเงื่อนไขโยน ValueError พร้อมเหตุผลไทย"""
    value = value.strip()
    try:
        parts = urlsplit(value)
    except ValueError:
        raise ValueError(f"อ่านลิงก์นี้ไม่ออก — รับเฉพาะ {SUPPORTED}") from None
    if parts.scheme != "https" or parts.username or parts.password             or parts.port not in (None, 443):
        raise ValueError("รับเฉพาะลิงก์ https ปกติ ไม่มีรหัสผ่านหรือพอร์ตแปลกๆ")
    host = (parts.hostname or "").lower()
    for name, hosts, pattern in PLATFORMS:
        if host not in hosts:
            continue
        if not re.fullmatch(pattern, parts.path):
            raise ValueError(f"เป็นลิงก์ {name} แต่ไม่ใช่หน้าคลิป — วางลิงก์คลิปโดยตรง")
        # /watch ของ YouTube เก็บรหัสคลิปไว้ในส่วนท้าย ไม่ได้อยู่ใน path
        if name == "YouTube" and parts.path.rstrip("/") == "/watch"                 and not parse_qs(parts.query).get("v"):
            raise ValueError("ลิงก์ YouTube นี้ไม่มีรหัสคลิป (ต้องมี ?v=…)")
        return value, name
    raise ValueError(f"ยังไม่รองรับเว็บนี้ — รับเฉพาะ {SUPPORTED}")

_settings_lock = threading.Lock()


def _settings_file(default_root: Path) -> Path:
    return default_root / "settings.json"


def _index_file(default_root: Path) -> Path:
    return default_root / "index.json"


def _read_json(path: Path, fallback):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return fallback


def configured_root(default_root: Path) -> Path:
    """โฟลเดอร์ที่จะเก็บคลิป — ค่าที่เจ้าของตั้งไว้ ถ้าไม่มีก็ใช้ที่เดิม"""
    chosen = str(_read_json(_settings_file(default_root), {}).get("folder") or "").strip()
    if not chosen:
        return default_root
    folder = Path(chosen)
    # ที่ตั้งไว้หายไป (ถอดไดรฟ์นอกออก ฯลฯ) — ถอยไปที่เดิม ดีกว่าดาวน์โหลดไม่ได้เลย
    return folder if folder.is_dir() else default_root


def check_folder(value: str, default_root: Path) -> Path:
    """ตรวจโฟลเดอร์ที่เจ้าของพิมพ์มา — ไม่ผ่านโยน ValueError พร้อมเหตุผลไทย

    **ต้องลองเขียนไฟล์จริง ไม่ใช่ดูแค่ว่าโฟลเดอร์มีอยู่** โฟลเดอร์ที่เปิดอ่านได้
    แต่เขียนไม่ได้จะผ่านด่านที่ดูแค่ `is_dir()` แล้วไปพังตอนดาวน์โหลดจริง
    ซึ่งตอนนั้นเจ้าของรอไปแล้วครึ่งนาที
    """
    text = str(value or "").strip().strip('"')
    if not text:
        return default_root
    folder = Path(text)
    if not folder.is_absolute():
        raise ValueError("ใส่ที่อยู่เต็มของโฟลเดอร์ เช่น D:\คลิปที่โหลด")
    folder = folder.resolve()
    if folder.exists() and not folder.is_dir():
        raise ValueError("ที่อยู่นี้เป็นไฟล์ ไม่ใช่โฟลเดอร์")
    if not folder.exists():
        if not folder.parent.is_dir():
            raise ValueError(f"ไม่มีโฟลเดอร์แม่ {folder.parent} — สร้างก่อนหรือพิมพ์ใหม่")
        try:
            folder.mkdir(parents=False)
        except OSError as exc:
            raise ValueError(f"สร้างโฟลเดอร์ไม่ได้: {exc.strerror or exc}") from exc
    probe = folder / f".เขียนได้ไหม-{uuid.uuid4().hex[:8]}"
    try:
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        raise ValueError(f"โฟลเดอร์นี้เขียนไฟล์ไม่ได้: {exc.strerror or exc}") from exc
    return folder


def save_folder(value: str, default_root: Path) -> Path:
    folder = check_folder(value, default_root)
    with _settings_lock:
        default_root.mkdir(parents=True, exist_ok=True)
        _settings_file(default_root).write_text(
            json.dumps({"folder": "" if folder == default_root else str(folder)},
                       ensure_ascii=False, indent=2), encoding="utf-8")
    return folder


def _remember(token: str, folder: Path, default_root: Path) -> None:
    """จำว่าคลิปนี้ไปอยู่โฟลเดอร์ไหน — เปลี่ยนโฟลเดอร์แล้วของเก่ายังเปิดดูได้"""
    with _settings_lock:
        index = _read_json(_index_file(default_root), {})
        if not isinstance(index, dict):
            index = {}
        index[token] = str(folder)
        default_root.mkdir(parents=True, exist_ok=True)
        _index_file(default_root).write_text(
            json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")


def _folder_of(token: str, default_root: Path) -> Path:
    index = _read_json(_index_file(default_root), {})
    known = str(index.get(token) or "") if isinstance(index, dict) else ""
    return Path(known) if known else configured_root(default_root)


def download_reel(url: str, root: Path) -> dict:
    url, platform = validate_url(url)
    token = uuid.uuid4().hex
    folder = root / token
    folder.mkdir(parents=True, exist_ok=False)
    # **ต้องแปลงเป็น mp4 เสมอ** วัดจริง 21 ก.ย. 2569: Reddit กับ YouTube ส่ง
    # webm มาให้ ของเดิมบังคับ `best[ext=mp4]` อย่างเดียวแล้วมองหาไฟล์ชื่อ
    # clip.mp4 เท่านั้น สองเว็บนี้จึงล้มทั้งที่โหลดได้
    # `--remux-video mp4` เปลี่ยนกล่องไฟล์โดยไม่เข้ารหัสใหม่ — เร็วและไม่เสียคุณภาพ
    command = [sys.executable, "-m", "yt_dlp", "--ignore-config", "--no-playlist",
               "--no-progress", "--no-colors", "--socket-timeout", "20",
               "--retries", "1", "--max-filesize", "500M", "--no-simulate",
               "--dump-json", "-f", "best[ext=mp4]/bv*+ba/best",
               "--remux-video", "mp4",
               "-o", str(folder / "clip.%(ext)s"), url]
    try:
        result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8",
                                errors="replace", timeout=300,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("ดาวน์โหลดเกิน 5 นาที กรุณาลองใหม่") from exc
    if result.returncode:
        # ไม่มีคุกกี้/สิทธิ์เข้าถึง และไม่มีทางเข้าสู่ระบบอัตโนมัติ
        raise RuntimeError(
            f"{platform} ไม่ส่งคลิปให้ดาวน์โหลด: คลิปอาจต้องเข้าสู่ระบบ "
            "ถูกจำกัดสิทธิ์ เกิน 500 MB หรือรูปแบบหน้าเปลี่ยน")
    video = folder / "clip.mp4"
    if not video.is_file():
        # remux ไม่ผ่าน (ไม่มี ffmpeg ฯลฯ) — เอาไฟล์ที่ได้จริงมาบอก ไม่เงียบ
        got = sorted(x for x in folder.glob("clip.*") if x.suffix != ".json")
        if got:
            raise RuntimeError(
                f"ได้ไฟล์ {got[0].name} แทน mp4 — แปลงไม่สำเร็จ (ต้องมี ffmpeg)")
    if not video.is_file() or video.stat().st_size < 1024:
        raise RuntimeError("ไม่ได้รับไฟล์ MP4 ที่สมบูรณ์ หรือคลิปเกินขนาด 500 MB")
    info = json.loads(result.stdout.strip().splitlines()[-1])
    record = {"id": token, "source_url": url, "platform": platform,
              "title": str(info.get("title") or f"{platform} clip"),
              # **ต้องจดเวลาไว้ตอนโหลด** ของเดิมไม่มี พอจะเรียงรายการเลยต้องไปเดา
              # จากเวลาแก้ไฟล์ ซึ่งเปลี่ยนได้เวลาก๊อปย้ายโฟลเดอร์
              "saved_at": time.time(),
              "facebook_id": str(info.get("id") or ""), "size": video.stat().st_size,
              "path": str(video.resolve()), "folder": str(folder.parent.resolve()),
              "video_url": f"/api/facebook-reels/files/{token}",
              "download_url": f"/api/facebook-reels/files/{token}?download=true"}
    (folder / "metadata.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    return record


# ---------------------------------------------------------------- ถอดเสียง

# ถอดเสียงในเครื่องด้วย faster-whisper **ไม่ใช่ Gemini** เพราะ
#   1. ไม่กินเครดิต — ตอนเขียนนี้เครดิต Gemini หมดอยู่ ถ้าผูกไว้ก็ใช้ไม่ได้เลย
#   2. โมเดลอยู่ในเครื่องแล้วครบ (tiny/small/medium/large-v3) ไม่ต้องโหลดใหม่
#   3. คลิปไม่ต้องออกจากเครื่อง
#
# วัดจริง 21 ก.ย. 2569 กับคลิปไทย 22 วินาที
#     small   ถอด 21 วินาที  อ่านรู้เรื่อง มีคำเพี้ยนบ้าง ("ช่องใส่เมมริกา")
#     medium  ถอด 60 วินาที  ดีกว่าชัดเจน ("ช่องใส่ Memory Card")
#
# **เจ้าของเลือก large-v3 เอง 21 ก.ย. 2569** — ยอมแลกเวลากับความแม่น
# เพราะสคริปที่ถอดมาเอาไปใช้ต่อ ถอดผิดแล้วต้องมานั่งแก้เองเสียเวลากว่า
# แรมเครื่องนี้ 63.8 GB ว่าง 33.3 GB รับ large-v3 (int8 ~1.6 GB) ได้สบาย
TRANSCRIBE_MODELS = ("tiny", "small", "medium", "large-v3")
TRANSCRIBE_DEFAULT = "large-v3"
# วัดจริงกับ large-v3: ใช้เวลาถอด **ราว 4–5 เท่าของความยาวคลิป**
#     คลิป 22 วินาที → 99 วินาที · คลิป 6 วินาที → 25 วินาที
# เพดานเดิม 15 นาทีจึงกลายเป็นรอเกือบชั่วโมง ซึ่งไม่มีใครนั่งรอ — ลดเหลือ 10 นาที
# (ยังนานถึง ~45 นาที แต่เป็นเคสที่ตั้งใจจริงๆ ไม่ใช่กดเล่น)
TRANSCRIBE_MAX_SECONDS = 10 * 60
# ใช้คูณความยาวคลิปเพื่อบอกเวลารอคร่าวๆ ให้คนกด — เผื่อไว้นิดจะได้ไม่ผิดหวัง
TRANSCRIBE_SLOWDOWN = 5

_model_cache: dict[str, object] = {}
_model_lock = threading.Lock()


def _load_model(size: str):
    """โหลดโมเดลครั้งเดียวแล้วใช้ซ้ำ — โหลดใหม่ทุกครั้งเสียเวลา 2–5 วินาทีเปล่าๆ"""
    with _model_lock:
        if size not in _model_cache:
            from faster_whisper import WhisperModel   # noqa: PLC0415
            _model_cache[size] = WhisperModel(size, device="cpu", compute_type="int8")
        return _model_cache[size]


def _clip_seconds(video: Path) -> float:
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(video)],
        capture_output=True, text=True, timeout=60,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    try:
        return float((probe.stdout or "0").strip())
    except ValueError:
        return 0.0


def transcribe_clip(token: str, default_root: Path,
                    model: str = TRANSCRIBE_DEFAULT) -> dict:
    """ถอดเสียงคลิปที่โหลดไว้เป็นข้อความ — เก็บผลไว้ กดซ้ำได้ทันที"""
    if model not in TRANSCRIBE_MODELS:
        raise ValueError(f"ไม่รู้จักโมเดล {model}")
    folder = _folder_of(token, default_root) / token
    video = folder / "clip.mp4"
    if not video.is_file():
        raise ValueError("ไม่พบไฟล์คลิป — อาจถูกลบไปแล้ว")

    cache = folder / "transcript.json"
    if cache.is_file():
        old = _read_json(cache, {})
        if isinstance(old, dict) and old.get("model") == model and old.get("text"):
            return {**old, "cached": True}

    seconds = _clip_seconds(video)
    if seconds > TRANSCRIBE_MAX_SECONDS:
        raise ValueError(
            f"คลิปยาว {seconds/60:.0f} นาที — ถอดเสียงได้ไม่เกิน "
            f"{TRANSCRIBE_MAX_SECONDS//60} นาที เพราะถอดหนึ่งคลิปใช้เวลา "
            f"ราว {TRANSCRIBE_SLOWDOWN} เท่าของความยาวคลิป")

    wav = folder / "audio.wav"
    pull = subprocess.run(
        ["ffmpeg", "-y", "-i", str(video), "-vn", "-ac", "1", "-ar", "16000",
         "-f", "wav", str(wav)],
        capture_output=True, timeout=300,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if pull.returncode or not wav.is_file() or wav.stat().st_size < 1024:
        # **"ไม่มีเสียง" ต่างจาก "ถอดไม่ได้"** ต้องบอกให้ตรง ไม่งั้นคนจะกดซ้ำเรื่อยๆ
        raise ValueError("คลิปนี้ไม่มีเสียง หรือแยกเสียงออกมาไม่ได้")

    started = time.time()
    try:
        engine = _load_model(model)
        # ไม่บังคับภาษา — คลิปมาจากหลายแพลตฟอร์ม มีทั้งไทยและอังกฤษ
        # บังคับเป็นไทยแล้วคลิปอังกฤษจะได้ข้อความมั่ว ซึ่งอ่านแล้วนึกว่าถอดพัง
        chunks, info = engine.transcribe(str(wav), vad_filter=True)
        lines = [chunk.text.strip() for chunk in chunks if chunk.text.strip()]
    finally:
        wav.unlink(missing_ok=True)

    text = " ".join(lines).strip()
    record = {
        "token": token, "model": model, "text": text,
        "language": str(getattr(info, "language", "") or ""),
        "clip_seconds": round(seconds, 1),
        "took_seconds": round(time.time() - started, 1),
        "lines": lines,
        "cached": False,
    }
    cache.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    return record


# ------------------------------------------------- รายการคลิปที่เก็บไว้

# เจ้าของสั่ง 21 ก.ย. 2569 — "ให้ใบงานค้างไว้ … ให้มีปุ่ม refresh คือ เช็คคลิป
# เผื่อมีอันไหนที่ถูกลบไป และให้มีปุ่มลบที่ลบทั้งคลิปทั้งไฟล์ที่โหลดมาแล้ว และที่แปล"
#
# **รายการอ่านจากสมุดจด (index.json) เท่านั้น ห้ามไล่สแกนโฟลเดอร์** เพราะใน
# โฟลเดอร์เก็บคลิปมีโฟลเดอร์ที่เจ้าของตั้งชื่อเองปนอยู่ด้วย (เช่น "ที่กดกระจก")
# ถ้าไล่สแกนแล้วเอาขึ้นรายการ ปุ่มลบจะกลายเป็นปุ่มลบของที่เราไม่ได้สร้าง

# สามสถานะนี้ **ห้ามยุบรวมกัน** ตามกติกาข้อ 2.3.1 — "ตรวจไม่ได้" ไม่ใช่ "ไฟล์หาย"
CLIP_OK = "ok"            # ตรวจแล้ว ไฟล์อยู่ครบ
CLIP_GONE = "gone"        # ตรวจแล้ว โฟลเดอร์ยังอยู่ แต่ไฟล์หายจริง
CLIP_OFFLINE = "offline"  # โฟลเดอร์เข้าไม่ถึง (ถอดไดรฟ์นอก ฯลฯ) ยังตัดสินไม่ได้

MAX_LIST = 300


def _one_clip(token: str, where: str, default_root: Path) -> dict:
    """อ่านสถานะคลิปหนึ่งใบจากของจริงบนดิสก์ ไม่ใช่จากที่เคยจดไว้"""
    root = Path(where) if where else configured_root(default_root)
    folder = root / token
    meta = _read_json(folder / "metadata.json", {})
    if not isinstance(meta, dict):
        meta = {}
    video = folder / "clip.mp4"

    # ลำดับการถามสำคัญมาก: ถ้าโฟลเดอร์แม่เข้าไม่ถึง จะบอกว่า "ไฟล์ถูกลบ" ไม่ได้
    try:
        root_ok = root.is_dir()
    except OSError:
        root_ok = False
    try:
        has_video = video.is_file()
        size = video.stat().st_size if has_video else 0
    except OSError:
        has_video, size = False, 0

    if has_video:
        state = CLIP_OK
    elif root_ok:
        state = CLIP_GONE
    else:
        state = CLIP_OFFLINE

    script = _read_json(folder / "transcript.json", {})
    if not isinstance(script, dict):
        script = {}

    saved = meta.get("saved_at")
    if not isinstance(saved, (int, float)):
        # ใบเก่าที่โหลดก่อนมีการจดเวลา ใช้เวลาไฟล์แทน ดีกว่าไม่มีลำดับเลย
        saved = 0.0
        for probe in (folder / "metadata.json", video):
            try:
                saved = probe.stat().st_mtime
                break
            except OSError:
                continue

    return {
        "id": token,
        "source_url": str(meta.get("source_url") or ""),
        "platform": str(meta.get("platform") or ""),
        "title": str(meta.get("title") or ""),
        "path": str(meta.get("path") or video),
        "folder": str(root),
        "size": size or int(meta.get("size") or 0),
        "size_live": bool(has_video),
        "state": state,
        "playable": has_video and (folder / "metadata.json").is_file(),
        "saved_at": float(saved or 0.0),
        "video_url": f"/api/facebook-reels/files/{token}",
        "download_url": f"/api/facebook-reels/files/{token}?download=true",
        # **"อ่านไม่ได้" ห้ามหน้าตาเหมือน "ไม่มีสคริป"** (กติกาข้อ 2.3.1)
        # ไดรฟ์ที่ถอดออกจะอ่าน transcript.json ไม่ได้ ถ้าปล่อยให้ส่งค่าว่างออกไป
        # หน้าเว็บจะขึ้นว่ายังไม่เคยถอด แล้วคนจะกดถอดใหม่ทั้งที่มีอยู่แล้ว
        "script_known": state != CLIP_OFFLINE,
        "script": str(script.get("text") or ""),
        "script_model": str(script.get("model") or ""),
        "script_language": str(script.get("language") or ""),
    }


def list_clips(default_root: Path) -> dict:
    """คลิปทั้งหมดที่เคยโหลด ใหม่สุดขึ้นก่อน พร้อมสถานะไฟล์ที่ตรวจสดทุกครั้ง"""
    index = _read_json(_index_file(default_root), {})
    if not isinstance(index, dict):
        index = {}
    items = []
    for token, where in list(index.items())[:MAX_LIST]:
        if not re.fullmatch(r"[0-9a-f]{32}", str(token)):
            continue
        try:
            items.append(_one_clip(str(token), str(where or ""), default_root))
        except Exception as exc:   # ใบเดียวพังห้ามทำให้ทั้งรายการหาย
            items.append({"id": str(token), "state": CLIP_GONE, "size": 0,
                          "title": "", "source_url": "", "platform": "",
                          "path": "", "folder": str(where or ""), "playable": False,
                          "saved_at": 0.0, "script": "", "script_model": "",
                          "script_language": "", "size_live": False,
                          "script_known": False,
                          "video_url": "", "download_url": "",
                          "broken_why": f"อ่านใบนี้ไม่ได้: {exc}"})
    items.sort(key=lambda row: row.get("saved_at") or 0.0, reverse=True)
    tally = {"total": len(items), "ok": 0, "gone": 0, "offline": 0,
             "bytes": 0, "with_script": 0}
    for row in items:
        tally[row["state"]] = tally.get(row["state"], 0) + 1
        if row["state"] == CLIP_OK:
            tally["bytes"] += row["size"]
        if row.get("script"):
            tally["with_script"] += 1
    return {"ok": True, "checked_at": time.time(), "clips": items, "tally": tally}


def delete_clip(token: str, default_root: Path) -> dict:
    """ลบคลิปหนึ่งใบ ทั้งไฟล์คลิป ไฟล์สคริปที่ถอดไว้ และชื่อในสมุดจด

    **ลบได้เฉพาะโฟลเดอร์ที่ชื่อเป็นรหัส 32 ตัวและมีชื่ออยู่ในสมุดจดเท่านั้น**
    เพื่อไม่ให้ไปโดนโฟลเดอร์ที่เจ้าของตั้งชื่อเองซึ่งวางอยู่ที่เดียวกัน
    """
    import shutil   # noqa: PLC0415 — ใช้ที่เดียว ไม่ต้องโหลดตอนเปิดเซิร์ฟเวอร์

    if not re.fullmatch(r"[0-9a-f]{32}", str(token)):
        raise ValueError("ไม่พบคลิปนี้")
    with _settings_lock:
        index = _read_json(_index_file(default_root), {})
        if not isinstance(index, dict):
            index = {}
        if token not in index:
            raise ValueError("ไม่พบคลิปนี้ในรายการ (อาจถูกลบไปแล้ว)")
        root = Path(str(index[token])) if index[token] else configured_root(default_root)
        folder = root / token

        # โฟลเดอร์เข้าไม่ถึง = ยังตัดสินไม่ได้ว่าของหายจริงไหม ห้ามลบชื่อทิ้ง
        # ไม่งั้นถอดไดรฟ์นอกออกแล้วกดลบ รายการจะหายทั้งที่ไฟล์ยังอยู่ในไดรฟ์
        if not root.is_dir():
            raise ValueError(
                f"ยังเข้าโฟลเดอร์ {root} ไม่ได้ เสียบไดรฟ์หรือเชื่อมต่อให้ได้ก่อน "
                "ค่อยลบ จะได้ไม่ลบรายการทิ้งทั้งที่ไฟล์ยังอยู่")

        removed, freed = 0, 0
        if folder.is_dir():
            for item in folder.rglob("*"):
                if item.is_file():
                    removed += 1
                    try:
                        freed += item.stat().st_size
                    except OSError:
                        pass
            shutil.rmtree(folder)
        index.pop(token, None)
        _index_file(default_root).write_text(
            json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True, "id": token, "files": removed, "bytes": freed,
            "folder_was_there": removed > 0}


class DownloadRequest(BaseModel):
    url: str


class FolderRequest(BaseModel):
    path: str = ""


class DeleteRequest(BaseModel):
    id: str


class TranscribeRequest(BaseModel):
    token: str
    model: str = TRANSCRIBE_DEFAULT


def open_download_folder(folder: Path) -> str:
    """เปิดโฟลเดอร์เก็บคลิปใน Explorer — เปิดได้เฉพาะโฟลเดอร์ของฟีเจอร์นี้"""
    folder = folder.resolve()
    folder.mkdir(parents=True, exist_ok=True)
    os.startfile(str(folder))
    return str(folder)


def create_router(root: Path) -> APIRouter:
    """`root` คือโฟลเดอร์ตั้งต้น — เจ้าของเปลี่ยนไปที่อื่นได้จากหน้าเว็บ"""
    router = APIRouter(prefix="/api/facebook-reels")
    lock = threading.Lock()

    @router.get("/folder")
    def folder_now():
        current = configured_root(root)
        return {"ok": True, "path": str(current), "default": str(root.resolve()),
                "is_default": current == root, "supported": SUPPORTED,
                "stt_model": TRANSCRIBE_DEFAULT,
                "stt_slowdown": TRANSCRIBE_SLOWDOWN,
                "stt_max_seconds": TRANSCRIBE_MAX_SECONDS}

    @router.post("/folder")
    def folder_set(payload: FolderRequest):
        try:
            folder = save_folder(payload.path, root)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"ok": True, "path": str(folder), "default": str(root.resolve()),
                "is_default": folder == root,
                "message": f"เก็บคลิปใหม่ลง {folder} แล้ว"}

    @router.post("/download")
    def download(payload: DownloadRequest):
        try:
            validate_url(payload.url)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        if not lock.acquire(blocking=False):
            raise HTTPException(409, "มีคลิปกำลังดาวน์โหลดอยู่ กรุณารอให้เสร็จก่อน")
        try:
            where = configured_root(root)
            where.mkdir(parents=True, exist_ok=True)
            record = download_reel(payload.url, where)
            _remember(record["id"], where, root)
            return record
        except RuntimeError as exc:
            raise HTTPException(502, str(exc)) from exc
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(500, "บันทึกคลิปไม่สำเร็จ กรุณาตรวจพื้นที่และสิทธิ์โฟลเดอร์เก็บคลิป") from exc
        finally:
            lock.release()

    @router.post("/transcribe")
    def transcribe(payload: TranscribeRequest):
        """ถอดเสียงคลิปเป็นข้อความ — เจ้าของสั่ง 21 ก.ย. 2569

        ถอดในเครื่อง ไม่ส่งคลิปออกไปไหน และไม่กินเครดิต AI
        """
        if not re.fullmatch(r"[0-9a-f]{32}", payload.token):
            raise HTTPException(404, "ไม่พบคลิป")
        # ล็อกตัวเดียวกับดาวน์โหลด — สองงานนี้กินซีพียูหนักทั้งคู่
        # ปล่อยให้ชนกันจะช้าทั้งคู่แล้วดูเหมือนเครื่องค้าง
        if not lock.acquire(blocking=False):
            raise HTTPException(409, "มีงานคลิปทำอยู่ กรุณารอให้เสร็จก่อน")
        try:
            return transcribe_clip(payload.token, root, payload.model)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except Exception as exc:
            raise HTTPException(500, f"ถอดเสียงไม่สำเร็จ: {exc}") from exc
        finally:
            lock.release()

    @router.post("/open-folder")
    def open_folder():
        try:
            return {"ok": True, "path": open_download_folder(configured_root(root))}
        except OSError as exc:
            raise HTTPException(500, "เปิดโฟลเดอร์คลิปไม่สำเร็จ กรุณาเปิดจาก path ที่แสดงใต้คลิป") from exc

    @router.get("/clips")
    def clips_now():
        """รายการคลิปที่เก็บไว้ ตรวจไฟล์จริงทุกครั้งที่เรียก ไม่ใช่เชื่อที่จดไว้"""
        return list_clips(root)

    @router.post("/clips/check")
    def clips_check():
        """ปุ่ม เช็คคลิป — ตรวจซ้ำว่ามีไฟล์ไหนหายไปบ้าง

        **ตรวจแล้วรายงานอย่างเดียว ไม่ลบอะไรให้เอง** ถ้าลบให้อัตโนมัติ
        วันที่ถอดไดรฟ์นอกออกแล้วเผลอกดปุ่มนี้ รายการจะหายเกลี้ยงทั้งที่ของยังอยู่
        """
        return list_clips(root)

    @router.post("/clips/delete")
    def clips_delete(payload: DeleteRequest):
        try:
            return delete_clip(payload.id, root)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except OSError as exc:
            raise HTTPException(500, f"ลบไฟล์ไม่สำเร็จ: {exc.strerror or exc}") from exc

    @router.get("/files/{token}")
    def file(token: str, download: bool = False):
        if not re.fullmatch(r"[0-9a-f]{32}", token):
            raise HTTPException(404, "ไม่พบคลิป")
        # คลิปเก่าที่โหลดไว้ก่อนเปลี่ยนโฟลเดอร์ต้องยังเปิดดูได้ จึงดูจากสมุดจดก่อน
        folder = _folder_of(token, root) / token
        path = folder / "clip.mp4"
        if not path.is_file() or not (folder / "metadata.json").is_file():
            raise HTTPException(404, "ไม่พบคลิปที่ดาวน์โหลดสำเร็จ")
        return FileResponse(path, media_type="video/mp4",
                            filename=f"clip-{token}.mp4" if download else None)

    return router
