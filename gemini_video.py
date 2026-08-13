"""ส่งไฟล์วิดีโอเข้า Gemini แล้วให้วิเคราะห์ — ใช้ในสาย TikTok repost

ทำไมต้องมีไฟล์นี้: Gemini เป็นเจ้าเดียวที่รับ **วิดีโอทั้งไฟล์ (ภาพ+เสียงพร้อมกัน)**
ผ่าน API ตรงๆ เจ้าอื่นต้องแยกเป็น "ดึงเฟรม + ถอดเสียง" เอง สายนี้ต้องการทั้งสองอย่าง
พร้อมกัน (ดูภาพเพื่อเขียน prompt สร้างคลิปใหม่ · ฟังเสียงเพื่อถอดบทพูดแยกผู้พูด)
จึงคุ้มที่จะยิงเข้า Gemini ครั้งเดียวได้ทั้งคู่

โค้ดชุดนี้ยกมาจาก `7.web app/web_app.py:3012 analyze_video_with_gemini` ซึ่งใช้งาน
จริงมาแล้ว **ไม่ได้เขียนใหม่** เพราะรายละเอียดที่ดูจุกจิกทุกข้อล้วนมาจากของจริง:

  - อัปโหลดต้องเป็นแบบ resumable (ไฟล์วิดีโอใหญ่เกินกว่าจะยัดใน body เดียว)
  - อัปเสร็จแล้วไฟล์ยัง **ไม่พร้อมใช้ทันที** ต้องวนถามจนสถานะเป็น ACTIVE
  - 429/500/503 คือ "คนใช้เยอะ" ไม่ใช่ "ของเราผิด" ต้องรอแล้วลองใหม่
  - ลองซ้ำครบแล้วยังไม่ได้ ให้สลับไปโมเดลสำรอง ไม่ใช่ยอมแพ้
  - ต้องลบไฟล์ทิ้งที่ฝั่ง Google เสมอใน finally ไม่งั้นโควตาที่เก็บไฟล์เต็ม

กติกาโปรเจกต์ที่ยึดในไฟล์นี้
  - ขั้นที่กินเวลาเป็นนาทีต้องมีชีพจร (เขียน log ทุก HEARTBEAT_SECONDS)
  - ความล้มเหลวต้องบอกสาเหตุจริงจาก Google ไม่ใช่ "ไม่สำเร็จ" ลอยๆ
"""

from __future__ import annotations

import base64
import mimetypes
import time
from pathlib import Path
from typing import Any, Callable

import httpx

UPLOAD_URL = "https://generativelanguage.googleapis.com/upload/v1beta/files"
API_BASE = "https://generativelanguage.googleapis.com/v1beta"

DEFAULT_MODEL = "gemini-3.5-flash"

# โมเดลสำรองเมื่อโมเดลหลักหนาแน่นต่อเนื่องจนลองซ้ำครบแล้ว
OVERLOAD_FALLBACKS = {
    "gemini-3.5-flash": "gemini-2.5-flash",
    "gemini-3.1-pro-preview": "gemini-2.5-pro",
    "gemini-2.5-pro": "gemini-2.5-flash",
    "gemini-2.5-flash": "gemini-3.5-flash",
}

VIDEO_EXTENSIONS = {
    ".mp4", ".mpeg", ".mov", ".avi", ".flv", ".mpg", ".webm", ".wmv", ".3gpp",
}

UPLOAD_TIMEOUT = 900        # วิ — อัปไฟล์วิดีโอ
GENERATE_TIMEOUT = 900      # วิ — รอคำตอบ (คลิปยาว + prompt ยาว ใช้เวลาได้มาก)
ACTIVE_POLL_SECONDS = 2     # วิ — รอบละเท่าไรตอนถามว่าไฟล์พร้อมยัง
ACTIVE_MAX_ROUNDS = 180     # รอบ (รวม ~6 นาที)
HEARTBEAT_SECONDS = 15      # วิ — เขียนชีพจรระหว่างรอ
RETRY_WAITS = (15, 30, 60)  # วิ — รอเท่านี้ก่อนลองใหม่แต่ละครั้ง


class GeminiError(RuntimeError):
    """Gemini ตอบกลับมาว่าทำไม่ได้ — ข้อความข้างในคือเหตุผลจริงจาก Google"""


def load_api_key() -> str | None:
    """อ่านคีย์ Gemini จากที่เดียวกับทั้งโปรเจกต์ (DPAPI ใน data/gemini_api_key.bin)

    import ข้างในฟังก์ชันตามแบบ shopee_service — flow_worker ลาก playwright มาด้วย
    ไม่ควรโหลดตั้งแต่ import โมดูลนี้
    """
    from flow_worker import load_gemini_api_key

    return load_gemini_api_key()


def _google_error(response: httpx.Response) -> str:
    try:
        payload = response.json()
        return str(payload.get("error", {}).get("message") or response.reason_phrase)
    except ValueError:
        return response.reason_phrase or f"HTTP {response.status_code}"


def _is_transient(response: httpx.Response) -> bool:
    """แยก "คนใช้เยอะ ลองใหม่ได้" ออกจาก "ของเราผิด ลองกี่ครั้งก็เหมือนเดิม"

    ถ้าไม่แยก จะไปลองซ้ำกับ prompt ที่ผิดจริงๆ เสียเวลาเปล่า และในทางกลับกันจะ
    ยอมแพ้ทั้งที่แค่รออีกนิดก็ผ่าน
    """
    if response.status_code in {429, 500, 503}:
        return True
    message = _google_error(response).lower()
    return any(
        marker in message
        for marker in (
            "high demand", "overloaded", "try again later",
            "unavailable", "resource_exhausted", "resource exhausted",
        )
    )


def _upload(video_path: Path, api_key: str, log: Callable[[str], None]) -> dict:
    """อัปวิดีโอแบบ resumable แล้วคืน metadata ของไฟล์ที่ Google เก็บไว้"""
    size = video_path.stat().st_size
    mime_type = mimetypes.guess_type(video_path.name)[0] or "video/mp4"
    if video_path.suffix.lower() == ".mov":
        mime_type = "video/mov"

    log(f"อัปวิดีโอเข้า Gemini… ({size / 1024 / 1024:.1f} MB)")
    initiate = httpx.post(
        UPLOAD_URL,
        headers={
            "x-goog-api-key": api_key,
            "X-Goog-Upload-Protocol": "resumable",
            "X-Goog-Upload-Command": "start",
            "X-Goog-Upload-Header-Content-Length": str(size),
            "X-Goog-Upload-Header-Content-Type": mime_type,
            "Content-Type": "application/json",
        },
        json={"file": {"display_name": video_path.name}},
        timeout=120,
    )
    if not initiate.is_success:
        raise GeminiError(f"Gemini รับไฟล์ไม่ได้: {_google_error(initiate)}")
    upload_url = initiate.headers.get("X-Goog-Upload-URL")
    if not upload_url:
        raise GeminiError("Gemini ไม่ส่งที่อยู่อัปโหลดกลับมา")

    with video_path.open("rb") as stream:
        uploaded = httpx.post(
            upload_url,
            headers={
                "X-Goog-Upload-Offset": "0",
                "X-Goog-Upload-Command": "upload, finalize",
                "Content-Length": str(size),
            },
            content=stream,
            timeout=UPLOAD_TIMEOUT,
        )
    if not uploaded.is_success:
        raise GeminiError(f"อัปโหลดวิดีโอไม่สำเร็จ: {_google_error(uploaded)}")

    info = uploaded.json().get("file") or {}
    if not info.get("name"):
        raise GeminiError("Gemini ไม่ส่งรหัสไฟล์กลับมา")
    info.setdefault("mimeType", mime_type)
    return info


def _wait_active(info: dict, api_key: str, log: Callable[[str], None]) -> dict:
    """รอจนไฟล์พร้อมใช้จริง

    อัปเสร็จ ≠ ใช้ได้ — Google ต้องถอดรหัสวิดีโอก่อน ถ้ายิง generateContent
    ตอนสถานะยัง PROCESSING จะได้ error ที่อ่านไม่ออกว่าเกิดอะไรขึ้น
    """
    name = info["name"]
    started = time.time()
    beat = started
    for _ in range(ACTIVE_MAX_ROUNDS):
        state = str(info.get("state") or "").upper()
        if state == "ACTIVE":
            log(f"Gemini พร้อมอ่านวิดีโอแล้ว ({int(time.time() - started)} วิ)")
            return info
        if state == "FAILED":
            raise GeminiError("Gemini ประมวลผลไฟล์วิดีโอไม่สำเร็จ")
        time.sleep(ACTIVE_POLL_SECONDS)
        if time.time() - beat >= HEARTBEAT_SECONDS:
            beat = time.time()
            log(f"…รอ Gemini เตรียมวิดีโอ {int(time.time() - started)} วิ · สถานะ {state or '-'}")
        metadata = httpx.get(
            f"{API_BASE}/{name}", headers={"x-goog-api-key": api_key}, timeout=60,
        )
        if not metadata.is_success:
            raise GeminiError(f"ตรวจสอบวิดีโอไม่ได้: {_google_error(metadata)}")
        info = metadata.json()
    raise GeminiError("Gemini ใช้เวลาเตรียมวิดีโอนานเกินกำหนด")


def _generate(
    parts: list[dict],
    api_key: str,
    model: str,
    response_schema: dict | None,
    log: Callable[[str], None],
) -> str:
    """ยิง generateContent พร้อมบันไดสองชั้น: ลองซ้ำ → เปลี่ยนโมเดลสำรอง"""
    generation_config: dict[str, Any] = {"temperature": 0.2, "maxOutputTokens": 16384}
    if response_schema is not None:
        generation_config["responseMimeType"] = "application/json"
        generation_config["responseSchema"] = response_schema
    body = {
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": generation_config,
    }

    models = [model]
    fallback = OVERLOAD_FALLBACKS.get(model)
    if fallback and fallback != model:
        models.append(fallback)

    response: httpx.Response | None = None
    for index, current in enumerate(models):
        for attempt in range(len(RETRY_WAITS) + 1):
            response = httpx.post(
                f"{API_BASE}/models/{current}:generateContent",
                headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
                json=body,
                timeout=GENERATE_TIMEOUT,
            )
            if response.is_success:
                break
            if attempt < len(RETRY_WAITS) and _is_transient(response):
                wait = RETRY_WAITS[attempt]
                log(
                    f"Gemini ({current}) แจ้งว่าคนใช้หนาแน่น "
                    f"รอ {wait} วิแล้วลองใหม่ (ครั้งที่ {attempt + 1}/{len(RETRY_WAITS)})"
                )
                time.sleep(wait)
                continue
            break
        if response is not None and response.is_success:
            if index:
                log(f"สำเร็จด้วยโมเดลสำรอง {current}")
            break
        if (
            response is not None
            and _is_transient(response)
            and index + 1 < len(models)
        ):
            log(f"โมเดล {current} หนาแน่นต่อเนื่อง เปลี่ยนไปใช้ {models[index + 1]}")
            continue
        raise GeminiError(f"Gemini วิเคราะห์ไม่สำเร็จ: {_google_error(response)}")

    if response is None or not response.is_success:
        raise GeminiError("Gemini วิเคราะห์ไม่สำเร็จ: ไม่ทราบสาเหตุ")

    payload = response.json()
    candidate = (payload.get("candidates") or [{}])[0]
    answer = "\n".join(
        str(part.get("text", ""))
        for part in candidate.get("content", {}).get("parts", [])
        if part.get("text")
    ).strip()
    if not answer:
        # finishReason คือคำตอบเดียวที่บอกได้ว่าโดน SAFETY หรือชน MAX_TOKENS
        raise GeminiError(
            f"Gemini ไม่ส่งคำตอบกลับมา ({candidate.get('finishReason') or 'ไม่ทราบสาเหตุ'})"
        )
    return answer


def analyze_video(
    video_path: Path,
    prompt: str,
    api_key: str | None = None,
    model: str = DEFAULT_MODEL,
    response_schema: dict | None = None,
    reference_images: list[Path] | None = None,
    log: Callable[[str], None] = print,
) -> str:
    """อัปวิดีโอ → รอพร้อม → ถามตาม prompt → คืนคำตอบเป็นข้อความ

    ส่ง `response_schema` เมื่อต้องการ JSON ที่โครงแน่นอน (Gemini จะถูกบังคับให้
    ตอบตามโครงนั้น ไม่ต้องมานั่งซ่อม JSON ที่พังทีหลัง)

    ลบไฟล์ที่ฝั่ง Google เสมอใน finally — ล้มกลางทางก็ต้องไม่ทิ้งขยะไว้
    """
    video_path = Path(video_path)
    if not video_path.is_file():
        raise GeminiError(f"ไม่พบไฟล์วิดีโอ: {video_path}")
    if video_path.suffix.lower() not in VIDEO_EXTENSIONS:
        raise GeminiError(f"Gemini ไม่รองรับไฟล์ชนิด {video_path.suffix}")

    key = api_key or load_api_key()
    if not key:
        raise GeminiError(
            "ยังไม่ได้ตั้งคีย์ Gemini — ใส่ได้ที่หน้า ⚙ ตั้งค่า ของเว็บ (พอร์ต 8866)"
        )

    info = _upload(video_path, key, log)
    try:
        info = _wait_active(info, key, log)
        parts: list[dict] = [
            {
                "file_data": {
                    "mime_type": info.get("mimeType") or "video/mp4",
                    "file_uri": info["uri"],
                }
            }
        ]
        for image in reference_images or []:
            image = Path(image)
            if not image.is_file():
                continue
            parts.append(
                {
                    "inline_data": {
                        "mime_type": mimetypes.guess_type(image.name)[0] or "image/jpeg",
                        "data": base64.b64encode(image.read_bytes()).decode("ascii"),
                    }
                }
            )
        parts.append({"text": prompt})
        log("ให้ Gemini อ่านคลิปแล้วตอบตามคำสั่ง…")
        return _generate(parts, key, model, response_schema, log)
    finally:
        try:
            httpx.delete(
                f"{API_BASE}/{info['name']}",
                headers={"x-goog-api-key": key},
                timeout=30,
            )
        except httpx.RequestError:
            # ลบไม่ได้ก็ไม่ใช่เรื่องคอขาดบาดตาย Google ลบเองใน 48 ชม.
            pass
