"""ดึงวัตถุดิบจากลิงก์ TikTok — ขั้นแรกสุดของสาย "TikTok repost"

ตามผังลายมือ ขั้นนี้ต้องได้ของ 4 อย่างจากลิงก์เดียว:

    1. รูปภาพสินค้า      → มาจากสินค้าที่ผูกไว้กับคลิป (TikTok Shop anchor)
    2. คลิป              → yt-dlp
    3. ข้อมูลสินค้า      → Product ID (เอาไปใส่ตอนโพสต์คลิปใหม่)
    4. #hashtag ใน caption

ข้อ 2 กับ 4 ทำได้ครบด้วย yt-dlp อย่างเดียว (สูตรยกมาจาก `7.web app/app.py:371`
ที่ใช้งานจริงมาแล้ว) ส่วนข้อ 1 กับ 3 ต้อง **เปิดหน้าเว็บจริง** เพราะ yt-dlp ไม่ได้
อ่านการ์ดสินค้าที่ผูกกับคลิปมาให้ — ดูหัวข้อ "ยังต้องเติมข้อมูล" ท้ายไฟล์

กติกาที่ยึด
  - ลิงก์ที่ผู้ใช้ส่งมาต้องเก็บไว้ดิบๆ ไม่ใช่ลิงก์ที่ระบบแปลงเอง (บทเรียนจากสาย
    Shopee: URL ที่ได้ตอนเปิดหน้าไม่มีรหัสผู้แนะนำ)
  - ทุกอย่างที่โหลดมาเก็บลงโฟลเดอร์ของงานนั้น ไม่กระจาย
  - เจอ error ห้ามกลบ — คืนสาเหตุจริงขึ้นไปให้ผู้เรียกตัดสินใจ
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Callable

import studio_shared

# ลิงก์ TikTok ที่รับ — ทั้งแบบย่อจากปุ่มแชร์ และแบบเต็มจากแถบที่อยู่
#   https://vt.tiktok.com/ZSxxxxxxx/
#   https://vm.tiktok.com/ZSxxxxxxx/
#   https://www.tiktok.com/@user/video/1234567890123456789
#   https://www.tiktok.com/t/ZSxxxxxxx/
TIKTOK_LINK_RE = re.compile(
    r"https?://(?:"
    r"(?:v[tm]|www|m)\.tiktok\.com/[^\s]+"
    r"|tiktok\.com/[^\s]+"
    r")",
    re.I,
)

# แฮชแท็กในแคปชัน — ไทย/อังกฤษ/ตัวเลข/ขีดล่าง ไม่รับช่องว่าง
HASHTAG_RE = re.compile(r"#([^\s#\.,!?;:()\[\]{}\"']+)")

# รหัสคลิปในลิงก์แบบเต็ม (ใช้ตั้งชื่อโฟลเดอร์เมื่อ yt-dlp ยังไม่ได้ตอบ)
VIDEO_ID_RE = re.compile(r"/video/(\d{6,})")

DOWNLOAD_TIMEOUT = 30       # วิ — socket timeout ของ yt-dlp
MAX_HASHTAGS = 30           # TikTok ไม่รับแท็กเยอะเกินจริงอยู่แล้ว
PAGE_SETTLE_SECONDS = 25    # วิ — รอ SPA ของ TikTok เรนเดอร์จนนิ่ง


class TikTokSourceError(RuntimeError):
    """ดึงของจากลิงก์ TikTok ไม่สำเร็จ — ข้อความข้างในคือสาเหตุจริง"""


def extract_links(text: str) -> list[str]:
    """คัดลิงก์ TikTok ออกจากข้อความที่ผู้ใช้พิมพ์มา (วางหลายลิงก์รวดเดียวได้)

    ตัดตัวซ้ำแต่คงลำดับเดิม — ผู้ใช้วางเรียงมาอย่างไรก็ทำตามลำดับนั้น
    """
    found: list[str] = []
    for match in TIKTOK_LINK_RE.findall(text or ""):
        link = match.rstrip(".,)งๆ")  # กันเครื่องหมายท้ายประโยคติดมากับลิงก์
        if link not in found:
            found.append(link)
    return found


def extract_hashtags(caption: str) -> list[str]:
    """ดึง #hashtag ออกจากแคปชัน คงลำดับที่เจอ ตัดตัวซ้ำ

    คืนแบบ **มี # นำหน้า** เพราะ tiktok_post.set_caption() รับรูปแบบนั้น
    """
    tags: list[str] = []
    for raw in HASHTAG_RE.findall(caption or ""):
        tag = f"#{raw.strip()}"
        if len(tag) > 1 and tag not in tags:
            tags.append(tag)
        if len(tags) >= MAX_HASHTAGS:
            break
    return tags


def video_id_from_link(link: str) -> str | None:
    match = VIDEO_ID_RE.search(link or "")
    return match.group(1) if match else None


def _cookie_file() -> Path | None:
    """ไฟล์คุกกี้ TikTok สำหรับ yt-dlp (ถ้าตั้งไว้ใน config)

    คลิปทั่วไปโหลดได้โดยไม่ต้องล็อกอิน แต่คลิปที่จำกัดอายุผู้ชมจะบังคับให้ล็อกอิน
    ตั้งพาธไว้ที่ `tiktok_cookie_file` ใน data/config.json เมื่อเจอเคสนั้น
    """
    value = (studio_shared.read_config().get("tiktok_cookie_file") or "").strip()
    if not value:
        return None
    path = Path(value)
    return path if path.is_file() else None


def download_clip(
    link: str,
    out_dir: Path,
    log: Callable[[str], None] = print,
) -> dict:
    """โหลดคลิป + metadata จากลิงก์ TikTok

    คืน dict: {video: Path, caption: str, hashtags: [..], video_id, uploader, duration}

    สูตร yt-dlp ยกมาจาก `7.web app/app.py:409-441` ทั้งชุด เหตุผลของแต่ละบรรทัด:
      - `app_info` = ใช้ API ของแอปมือถือก่อน ให้ไฟล์วิดีโอครบกว่า API ฝั่งเว็บ
        (โพสต์จำกัดผู้ชมที่ฝั่งเว็บส่งมาแค่ไฟล์เสียง)
      - `impersonate=chrome` + curl_cffi = ผ่านด่านกันบอทของ TikTok
      - `format` บังคับให้มี vcodec — กันได้ไฟล์เสียงล้วนมาแล้วไปพังที่ Gemini
    """
    try:
        import yt_dlp
        from yt_dlp.networking.impersonate import ImpersonateTarget
    except ImportError as exc:  # pragma: no cover - สภาพแวดล้อมขาดของ
        raise TikTokSourceError("ยังไม่ได้ติดตั้ง yt-dlp — รัน pip install yt-dlp") from exc
    try:
        import curl_cffi  # noqa: F401
    except ImportError as exc:  # pragma: no cover
        raise TikTokSourceError(
            "ยังไม่ได้ติดตั้ง curl_cffi — TikTok จะกันบอทถ้าไม่มีตัวนี้"
        ) from exc

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    options = {
        "format": "best[vcodec!=none][ext=mp4]/best[vcodec!=none]/best",
        "extractor_args": {"tiktok": {"app_info": ["7355728856979392262"]}},
        "outtmpl": str(out_dir / "source.%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "windowsfilenames": True,
        "overwrites": False,
        "continuedl": True,
        "impersonate": ImpersonateTarget(client="chrome"),
        "retries": 3,
        "extractor_retries": 3,
        "socket_timeout": DOWNLOAD_TIMEOUT,
        "http_headers": {"Accept-Language": "th-TH,th;q=0.9,en-US;q=0.8,en;q=0.7"},
        # เก็บรูปปกไว้ด้วย — ตอนนี้ยังดึงรูปสินค้าจริงไม่ได้ (ดูหัวข้อ "ยังต้องเติมข้อมูล")
        # รูปปกจึงเป็นรูปเดียวที่มีให้ผู้ใช้ตรวจและใช้เป็นเฟรมตั้งต้นของ Flow ไปก่อน
        "writethumbnail": True,
    }
    cookies = _cookie_file()
    if cookies:
        options["cookiefile"] = str(cookies)
        log(f"ใช้คุกกี้ TikTok จาก {cookies.name}")

    log("อ่านข้อมูลคลิปจาก TikTok…")
    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(link, download=True)
    except Exception as exc:  # yt-dlp โยน error หลายชนิดมาก
        raise TikTokSourceError(_friendly_error(exc)) from exc

    if not info:
        raise TikTokSourceError("TikTok ไม่ส่งข้อมูลคลิปกลับมา")

    video_path = _find_downloaded(out_dir)
    commerce: dict = {}
    if video_path is None:
        # yt-dlp ได้แต่ไฟล์เสียง — **ไม่ได้แปลว่าโพสต์นี้ไม่มีวิดีโอ**
        # วัดจากของจริง: คลิปที่ yt-dlp คืนฟอร์แมต audio ตัวเดียว tikwm กลับคืน
        # URL วิดีโอให้ได้ปกติ เป็นข้อจำกัดของตัวแกะ ไม่ใช่ของตัวโพสต์
        # (7.web app ก็ใช้ tikwm เป็นทางสำรองด้วยเหตุผลเดียวกัน)
        log("yt-dlp ไม่ได้ไฟล์วิดีโอ — ลองทางสำรอง tikwm")
        video_path, commerce = _download_via_tikwm(link, out_dir, log=log)
    if video_path is None:
        raise TikTokSourceError(
            "โหลดวิดีโอไม่สำเร็จทั้งทาง yt-dlp และ tikwm "
            f"(ได้มา {[p.name for p in out_dir.glob('source.*')]})"
        )

    # แคปชันของ TikTok อยู่ที่ description เป็นหลัก บางเคสมีแต่ title
    caption = str(info.get("description") or info.get("title") or "").strip()
    result = {
        "video": video_path,
        "caption": caption,
        "hashtags": extract_hashtags(caption),
        "video_id": str(info.get("id") or video_id_from_link(link) or ""),
        "uploader": str(info.get("uploader") or info.get("creator") or ""),
        "duration": info.get("duration"),
        "source_url": link,
        "webpage_url": str(info.get("webpage_url") or link),
        "cover": _find_cover(out_dir),
        "commerce": commerce,
    }
    # เก็บ metadata ดิบไว้เสมอ — แก้ตัวแกะแล้วเอาของเก่ามาลองใหม่ได้ ไม่ต้องโหลดซ้ำ
    try:
        (out_dir / "source-info.json").write_text(
            json.dumps(info, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
    except (OSError, TypeError, ValueError):
        pass

    size_mb = video_path.stat().st_size / 1024 / 1024
    log(
        f"ได้คลิปแล้ว {video_path.name} ({size_mb:.1f} MB · "
        f"{result['duration'] or '?'} วิ) · แท็ก {len(result['hashtags'])} อัน"
    )
    return result


VIDEO_SUFFIXES = {".mp4", ".mov", ".webm", ".mkv", ".m4v", ".avi"}
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}

TIKWM_API = "https://www.tikwm.com/api/"
TIKWM_TIMEOUT = 90


def _download_via_tikwm(
    link: str, out_dir: Path, log: Callable[[str], None] = print,
) -> tuple[Path | None, dict]:
    """ทางสำรองเมื่อ yt-dlp ดึงฟอร์แมตวิดีโอไม่ได้ — ยกแนวมาจาก 7.web app/app.py:314

    ส่งออกไปแค่ **ลิงก์** ไม่ได้ส่งไฟล์หรือข้อมูลส่วนตัวใดๆ ออกนอกเครื่อง

    คืน (พาธไฟล์วิดีโอ, ข้อมูลเชิงพาณิชย์) — ตัวหลังบอกว่าคลิปนี้ผูกสินค้าไว้ไหม
    ซึ่ง yt-dlp ไม่ได้ให้มาเลย
    """
    import httpx

    try:
        response = httpx.post(
            TIKWM_API, data={"url": link, "hd": "1"},
            headers={"User-Agent": "Mozilla/5.0"}, timeout=TIKWM_TIMEOUT,
        )
        payload = response.json()
    except Exception as error:
        log(f"tikwm ตอบไม่ได้: {str(error)[:120]}")
        return None, {}
    if payload.get("code") != 0:
        log(f"tikwm ปฏิเสธ: {payload.get('msg')}")
        return None, {}

    data = payload.get("data") or {}
    commerce = _read_commerce(data)
    # hdplay ก่อน (ไม่มีลายน้ำและชัดกว่า) ไม่มีค่อยใช้ play
    url = data.get("hdplay") or data.get("play") or ""
    if not url:
        log("tikwm ไม่ส่ง URL วิดีโอกลับมา")
        return None, commerce

    target = out_dir / "source.mp4"
    try:
        with httpx.stream("GET", url, timeout=TIKWM_TIMEOUT,
                          headers={"User-Agent": "Mozilla/5.0"},
                          follow_redirects=True) as stream:
            stream.raise_for_status()
            with target.open("wb") as handle:
                for chunk in stream.iter_bytes(65536):
                    handle.write(chunk)
    except Exception as error:
        target.unlink(missing_ok=True)
        log(f"โหลดวิดีโอจาก tikwm ไม่สำเร็จ: {str(error)[:120]}")
        return None, commerce

    log(f"tikwm ให้วิดีโอมาแล้ว {target.stat().st_size / 1024 / 1024:.1f} MB")
    return target, commerce


def _read_commerce(data: dict) -> dict:
    """อ่านว่าคลิปนี้ผูกสินค้า TikTok Shop ไว้ไหม จากก้อน anchors_extras

    **ยืนยันจากของจริงแล้วว่าในนี้ไม่มี Product ID** — มีแต่ธงว่าเป็นคลิปขายของ
    และหน้าตาของการ์ด (`video_cart_tag`, `is_single_sku`) เลข 16-20 หลักที่อยู่
    ในคำตอบทั้งก้อนเป็น id ของเจ้าของคลิป/คลิป/เพลง ไม่ใช่ของสินค้า
    ดังนั้นยังต้องหา Product ID จากทางอื่นอยู่ (ดู TIKTOK-REPOST.md)
    """
    raw = data.get("anchors_extras")
    if not raw:
        return {}
    try:
        extras = json.loads(raw) if isinstance(raw, str) else raw
    except ValueError:
        return {}
    anchor = extras.get("ec_anchor_info") or {}
    return {
        "is_shop_video": bool(extras.get("is_ec_video")),
        "anchor_tag": anchor.get("anchor_tag") or "",
        "product_id": "",       # ⛔ ยังไม่มีทางได้จากตรงนี้
    }


def _find_downloaded(out_dir: Path) -> Path | None:
    """หาไฟล์วิดีโอที่ yt-dlp เพิ่งบันทึก

    กรองด้วย **นามสกุลวิดีโอ** ไม่ใช่ "ไฟล์ใหญ่สุด" เพราะตั้งแต่เปิด writethumbnail
    โฟลเดอร์นี้มีรูปปกปนอยู่ด้วย ถ้าโหลดวิดีโอล้มแต่รูปปกสำเร็จ วิธีเดิมจะคืนรูปปก
    มาเป็น "คลิป" แล้วไปพังที่ Gemini แทนที่จะฟ้องตรงนี้
    """
    candidates = sorted(
        (p for p in out_dir.glob("source.*") if p.suffix.lower() in VIDEO_SUFFIXES),
        key=lambda p: p.stat().st_size,
        reverse=True,
    )
    return candidates[0] if candidates else None


def _find_cover(out_dir: Path) -> Path | None:
    """รูปปกที่ yt-dlp บันทึกไว้ (ถ้ามี)"""
    for path in sorted(out_dir.glob("source.*")):
        if path.suffix.lower() in IMAGE_SUFFIXES:
            return path
    return None


def _friendly_error(exc: Exception) -> str:
    """แปลง error ของ yt-dlp เป็นข้อความที่บอกได้ว่าต้องทำอะไรต่อ"""
    message = str(exc)
    lowered = message.lower()
    if "login" in lowered or "age" in lowered and "restrict" in lowered:
        return (
            "คลิปนี้ต้องเข้าสู่ระบบก่อนถึงจะโหลดได้ — ตั้งพาธไฟล์ cookies.txt ไว้ที่ "
            "`tiktok_cookie_file` ใน data/config.json"
        )
    if "private" in lowered:
        return "คลิปนี้เป็นส่วนตัว โหลดไม่ได้"
    if "unavailable" in lowered or "not found" in lowered or "404" in lowered:
        return "ไม่พบคลิปนี้แล้ว (อาจถูกลบหรือลิงก์หมดอายุ)"
    if "unable to download webpage" in lowered or "timed out" in lowered:
        return f"เชื่อมต่อ TikTok ไม่ได้: {message[:200]}"
    return f"โหลดคลิปจาก TikTok ไม่สำเร็จ: {message[:300]}"


# ---------------------------------------------------------------------------
# ข้อ 1 + 3 ของผัง: รูปสินค้า และ Product ID
# ---------------------------------------------------------------------------
#
# ⛔ ยังต้องเติมข้อมูล — ดูหัวข้อ "ช่องที่เว้นไว้" ใน TIKTOK-REPOST.md
#
# สินค้าที่ผูกกับคลิป (TikTok Shop anchor) ไม่ได้อยู่ใน metadata ของ yt-dlp
# ต้องเปิดหน้าคลิปจริงด้วยโปรไฟล์ที่ล็อกอินแล้วไปอ่านการ์ดสินค้า
#
# ยังไม่เขียนตัวจับจริง เพราะ **ยังไม่เคยเห็นหน้าจริง** — เดา selector แล้วเขียนไป
# คือการสร้างตัวตรวจที่บอกว่า "ผ่าน" ทั้งที่ยังไม่ผ่าน ซึ่งอันตรายกว่าไม่มีเลย
# (กติกาข้อ 2.3 ของ CLAUDE.md)
#
# ใช้ `probe_product()` กับลิงก์จริง 1 อันเพื่อดูว่าหน้าจริงหน้าตาเป็นยังไงก่อน
# แล้วค่อยเติม PRODUCT_SELECTORS ให้ตรงของจริง

PRODUCT_SELECTORS: dict[str, str] = {
    # "anchor": "",        # การ์ดสินค้าใต้คลิป
    # "product_link": "",  # ลิงก์ที่มี product id อยู่ข้างใน
    # "product_image": "",
    # "product_title": "",
}

# JS ที่ใช้ตอน probe — กวาดหาผู้สมัครทุกแบบที่น่าจะเป็นการ์ดสินค้า แล้วคืนมาให้ดู
# ไม่ตัดสินใจอะไรเอง หน้าที่มันคือ "ทำให้เรามองเห็น" เท่านั้น
PRODUCT_PROBE_JS = """
() => {
  const seen = new Set();
  const out = { links: [], images: [], anchors: [], scripts: [] };

  // 1) ลิงก์ที่หน้าตาเหมือนลิงก์สินค้า
  for (const a of document.querySelectorAll('a[href]')) {
    const href = a.getAttribute('href') || '';
    if (!/product|shop|item|anchor/i.test(href)) continue;
    if (seen.has(href)) continue;
    seen.add(href);
    out.links.push({
      href: href.slice(0, 300),
      text: (a.innerText || '').trim().slice(0, 120),
      cls: (a.className || '').toString().slice(0, 120),
    });
  }

  // 2) element ที่ชื่อคลาส/testid มีคำว่า anchor หรือ product
  for (const el of document.querySelectorAll(
      '[class*="anchor" i],[class*="product" i],[data-e2e*="anchor" i],[data-e2e*="product" i]')) {
    const key = (el.className || '') + '|' + (el.getAttribute('data-e2e') || '');
    if (seen.has(key)) continue;
    seen.add(key);
    const box = el.getBoundingClientRect();
    if (box.width < 20 || box.height < 20) continue;
    out.anchors.push({
      tag: el.tagName,
      cls: (el.className || '').toString().slice(0, 160),
      e2e: el.getAttribute('data-e2e') || '',
      text: (el.innerText || '').trim().slice(0, 160),
      w: Math.round(box.width), h: Math.round(box.height),
    });
  }

  // 3) รูปที่อาจเป็นรูปสินค้า
  for (const img of document.querySelectorAll('img[src]')) {
    const src = img.getAttribute('src') || '';
    if (src.startsWith('data:')) continue;
    const box = img.getBoundingClientRect();
    if (box.width < 40 || box.height < 40) continue;
    out.images.push({
      src: src.slice(0, 300),
      alt: (img.getAttribute('alt') || '').slice(0, 120),
      w: Math.round(box.width), h: Math.round(box.height),
    });
  }

  // 4) ก้อน JSON ที่ TikTok ฝังมาในหน้า — product id มักอยู่ในนี้
  for (const s of document.querySelectorAll('script[id],script[type*="json" i]')) {
    const text = s.textContent || '';
    if (!/product_id|productId|anchor/i.test(text)) continue;
    out.scripts.push({
      id: s.id || '(ไม่มี id)',
      type: s.getAttribute('type') || '',
      length: text.length,
      sample: text.slice(0, 400),
    });
  }
  return out;
}
"""


def probe_product(link: str, dump_to: Path | None = None, log: Callable[[str], None] = print) -> dict:
    """เปิดหน้าคลิปจริงแล้วดัมพ์ผู้สมัครที่น่าจะเป็นการ์ดสินค้าออกมาให้ดู

    ตัวนี้ **ไม่ตัดสินใจอะไร** — มีไว้ให้เราเห็นหน้าจริงก่อนเขียนตัวจับ
    ใช้ครั้งเดียวกับลิงก์ตัวอย่าง แล้วเอาผลไปเติม PRODUCT_SELECTORS

    ถือ browser_lock เพราะโปรไฟล์ Chrome มีตัวเดียวทั้งโปรเจกต์
    """
    from playwright.sync_api import sync_playwright

    result: dict = {}
    with studio_shared.browser_lock(label="probe การ์ดสินค้า TikTok"):
        with sync_playwright() as playwright:
            context = playwright.chromium.launch_persistent_context(
                user_data_dir=str(studio_shared.BROWSER_PROFILE),
                channel="chrome",
                headless=False,
                args=["--disable-blink-features=AutomationControlled"],
            )
            try:
                page = context.pages[0] if context.pages else context.new_page()
                log(f"เปิดหน้าคลิป: {link}")
                page.goto(link, wait_until="domcontentloaded", timeout=90_000)

                # TikTok เป็น SPA หนัก — รอเวลาตายตัวแล้วอ่านเลยคือการอ่านหน้าเปล่า
                # แล้วสรุปว่า "ไม่มีการ์ดสินค้า" ทั้งที่ยังไม่ทันเรนเดอร์
                # รอจนกว่า DOM จะมีเนื้อจริง แล้วค่อยอ่าน (สูงสุด PAGE_SETTLE วินาที)
                grew = 0
                for _ in range(PAGE_SETTLE_SECONDS):
                    page.wait_for_timeout(1_000)
                    size = page.evaluate("() => document.body ? document.body.innerHTML.length : 0")
                    if size > 5_000 and size == grew:
                        break          # นิ่งแล้วและมีเนื้อจริง
                    grew = size
                log(f"ขนาด DOM ที่อ่านได้: {grew:,} ตัวอักษร")

                result = page.evaluate(PRODUCT_PROBE_JS)
                result["url"] = page.url
                result["title"] = page.title()
                result["dom_size"] = grew
                # เก็บหลักฐานว่าหน้าจริงหน้าตาเป็นยังไง — ไม่ต้องเดาอีกต่อไป
                result["body_text"] = page.evaluate(
                    "() => (document.body ? document.body.innerText : '').slice(0, 1500)"
                )
                if dump_to:
                    shot = Path(dump_to).with_suffix(".png")
                    shot.parent.mkdir(parents=True, exist_ok=True)
                    page.screenshot(path=str(shot), full_page=False)
                    log(f"บันทึกภาพหน้าจอไว้ที่ {shot}")
            finally:
                context.close()

    log(
        f"เจอ ลิงก์ที่น่าสน {len(result.get('links', []))} · "
        f"การ์ด {len(result.get('anchors', []))} · "
        f"รูป {len(result.get('images', []))} · "
        f"ก้อน JSON {len(result.get('scripts', []))}"
    )
    if dump_to:
        dump_to = Path(dump_to)
        dump_to.parent.mkdir(parents=True, exist_ok=True)
        dump_to.write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        log(f"บันทึกผล probe ไว้ที่ {dump_to}")
    return result


REHYDRATION_RE = re.compile(
    r'id="__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>(.*?)</script>', re.S
)
# รหัสของ TikTok ทุกชนิดเป็นเลข 15–22 หลัก จึงต้องคัดตัวที่ "ไม่ใช่" ของอย่างอื่นออก
ID_RE = re.compile(r"\b\d{15,22}\b")

# รูปสินค้าใน anchor เก็บเป็น **พาธเปล่า** ไม่ใช่ URL — ต้องประกอบเอง
# ค่าที่ใช้ได้จริง (ทดสอบแล้วได้ 200 ครบ 5 ใบ): host + พาธ + template นี้
# ⚠️ ต้องเป็น `resize-jpeg` ไม่ใช่ `resize` — ใส่ผิดได้ 404 ทุกใบ (เจอมาแล้ว)
# และ **ไม่ต้องมี query string** ตัดทิ้งได้หมด รูปยังโหลดได้ปกติ
IMAGE_HOST = "https://p16-oec-sg.ibyteimg.com"
IMAGE_TMPL = "~tplv-aphluv4xwc-resize-jpeg:800:800.jpeg"


def image_url(path: str) -> str:
    """ประกอบ URL รูปสินค้าจากพาธที่อยู่ใน anchor"""
    return f"{IMAGE_HOST}/{path}{IMAGE_TMPL}"


def product_from_page_data(html: str) -> dict:
    """แกะ Product ID จากก้อน JSON ที่ TikTok ฝังมาในหน้า

    **ที่มาของวิธีนี้** — ไล่จากหน้าจริงที่ล็อกอินแล้ว พบว่าข้อมูลสินค้าไม่ได้อยู่ใน
    DOM ที่หา selector ได้ แต่อยู่ในสคริปต์ `__UNIVERSAL_DATA_FOR_REHYDRATION__`
    ที่ติดมากับ HTML ตั้งแต่แรก โครงคือ

        __DEFAULT_SCOPE__["webapp.video-detail"].itemInfo.itemStruct
            .isECVideo    1 = คลิปนี้ผูกสินค้า
            .AnchorTypes  ["33"]
            .anchors[0]   { type, icon, extra, thumbnail, extraInfo }
                .extra    ← **รหัสสินค้าอยู่ในนี้**

    ใน `extra` มีเลข 15–22 หลักอยู่ 2 ตัวเท่านั้น: รหัสคลิป กับ **รหัสสินค้า**
    จึงคัดรหัสคลิป/เจ้าของ/เพลง ออกแล้วที่เหลือคือของที่ต้องการ

    **ต้องอ่านจาก HTML ดิบ ห้ามอ่านจาก DOM** — TikTok ลบสคริปต์นี้ทิ้งทันทีที่
    หน้าไฮเดรตเสร็จ อ่านจาก DOM ทีหลังจะไม่เจอ (เจอมาแล้ว: อ่านรอบแรกได้ รอบสองหาย)
    """
    match = REHYDRATION_RE.search(html or "")
    if not match:
        return {"product_id": "", "product_title": "", "images": [], "ready": False,
                "note": "ไม่พบก้อนข้อมูลในหน้า — น่าจะยังไม่ได้ล็อกอิน หรือโดนหน้ากันบอท"}
    try:
        scope = json.loads(match.group(1))["__DEFAULT_SCOPE__"]
        item = scope["webapp.video-detail"]["itemInfo"]["itemStruct"]
    except (ValueError, KeyError, TypeError) as error:
        return {"product_id": "", "product_title": "", "images": [], "ready": False,
                "note": f"อ่านโครงข้อมูลไม่ได้: {error}"}

    anchors = item.get("anchors") or []
    if not item.get("isECVideo") or not anchors:
        return {"product_id": "", "product_title": "", "images": [], "ready": False,
                "note": "คลิปนี้ไม่ได้ผูกสินค้าไว้"}

    def loads(value):
        if isinstance(value, str):
            try:
                return json.loads(value)
            except ValueError:
                return None
        return value

    # anchors[0].extra เป็น **สตริง JSON ที่ข้างในเป็นอาร์เรย์** — สินค้าอยู่ตัวแรก
    cards = loads(anchors[0].get("extra")) or []
    card = cards[0] if isinstance(cards, list) and cards else {}
    detail = loads(card.get("extra")) or {}

    # ⚠️ ห้ามอ่าน detail["product_id"] — ค่านั้นเป็น **ตัวเลข** ที่เกินความละเอียด
    # ของ JSON number (>2^53) พอ parse แล้วท้ายเพี้ยน วัดจริง:
    #     ของจริง 1736420320728352251 → อ่านเป็นตัวเลขได้ 1736420320728352300
    # ตัวที่เชื่อได้คือ card["id"] ซึ่งเป็นสตริง และ seo_url ที่มีรหัสอยู่ในพาธ
    product_id = str(card.get("id") or "").strip()
    seo_url = str(detail.get("seo_url") or "")
    from_url = re.search(r"/pdp/(\d+)", seo_url)
    if from_url:
        if product_id and product_id != from_url.group(1):
            # ไม่ตรงกันแปลว่าอ่านผิดที่ — เชื่อ URL เพราะไม่ผ่าน JSON number
            product_id = from_url.group(1)
        product_id = product_id or from_url.group(1)

    categories = loads(detail.get("categories")) or []
    skus = loads(detail.get("skus")) or []
    image_paths = loads(detail.get("img")) or []

    return {
        "product_id": product_id,
        "product_title": str(detail.get("title") or card.get("keyword") or "").strip(),
        "short_title": str(card.get("keyword") or "").strip(),
        "images": [image_url(p) for p in image_paths if isinstance(p, str)],
        "image_paths": [p for p in image_paths if isinstance(p, str)],
        "category": " › ".join(str(c.get("category_name") or "") for c in categories),
        "currency": str(detail.get("currency") or ""),
        "sku_count": len(skus) if isinstance(skus, list) else 0,
        "seo_url": seo_url,
        "anchor_type": card.get("type"),
        "ready": bool(product_id),
        "note": "" if product_id else "เจอการ์ดสินค้าแต่ไม่มีรหัส",
    }


def fetch_product(link: str, out_dir: Path, log: Callable[[str], None] = print) -> dict:
    """เปิดหน้าคลิปด้วยโปรไฟล์ที่ล็อกอินแล้ว → อ่าน Product ID จาก HTML ดิบ

    ต้องล็อกอิน TikTok ในโปรไฟล์ของระบบก่อน (`python flow_worker.py login-tiktok`)
    ไม่ได้ล็อกอิน TikTok จะเสิร์ฟหน้าโครงเปล่าที่ไม่มีก้อนข้อมูลมาให้ — พิสูจน์แล้ว
    """
    from playwright.sync_api import sync_playwright

    with studio_shared.browser_lock(label="อ่าน Product ID จาก TikTok"):
        with sync_playwright() as playwright:
            context = playwright.chromium.launch_persistent_context(
                user_data_dir=str(studio_shared.BROWSER_PROFILE),
                channel="chrome",
                headless=False,
                args=["--disable-blink-features=AutomationControlled"],
            )
            try:
                page = context.pages[0] if context.pages else context.new_page()
                # wait_until="commit" = ได้ response ทันทีที่ header มา ยังไม่ทันไฮเดรต
                response = page.goto(link, wait_until="commit", timeout=90_000)
                html = response.text() if response else ""
            finally:
                context.close()

    result = product_from_page_data(html)
    if result["ready"]:
        log(f"ได้ Product ID: {result['product_id']}")
    else:
        log(f"⛔ ยังไม่ได้ Product ID — {result.get('note')}")
    return result


def collect(
    link: str,
    out_dir: Path,
    want_product: bool = True,
    log: Callable[[str], None] = print,
) -> dict:
    """ดึงของครบชุดจากลิงก์เดียว — ตัวที่สายงานเรียกใช้จริง

    ล้างโฟลเดอร์เดิมก่อนเสมอ (ทับของเก่าตามที่ผู้ใช้เลือกไว้ในสาย Shopee)
    """
    out_dir = Path(out_dir)
    if out_dir.exists():
        shutil.rmtree(out_dir, ignore_errors=True)
    out_dir.mkdir(parents=True, exist_ok=True)

    data = download_clip(link, out_dir, log=log)
    data["product"] = (
        fetch_product(data["webpage_url"], out_dir, log=log)
        if want_product
        else {"product_id": "", "product_title": "", "images": [], "ready": False}
    )
    return data
