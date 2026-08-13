"""สาย TikTok repost — รับลิงก์คลิป TikTok แล้วสร้างคลิปใหม่ไปโพสต์ทับ

ผังที่ยึด (จากลายมือของผู้ใช้)

    Input ลิงก์ TikTok (ผ่าน chatbot telegram)
      1. ดึงรูปภาพสินค้าจากลิงก์      3. ดึงข้อมูลสินค้า → Product ID
      2. ดึงคลิปจากลิงก์              4. ดึง #hashtag ใน caption
            ↓ เอาคลิปไป
      ① วิเคราะห์เป็น prompt สำหรับสร้างคลิปนี้
      ② ถอดเสียงพูดทั้งหมด แยกบทพูดถ้ามีคนพูดมากกว่า 1 คน
            ↓
      ส่ง 3 อย่างเข้า Telegram ให้ confirm แยกกัน: รูปสินค้า · prompt · บทพูด
            ↓
      เอาข้อมูลที่ confirm ไปทำคลิป (อ้างอิงวิธีขับ Flow จาก KVID)
            ↓
      ส่งกลับไป confirm เพื่อ post ทั้ง 4 อย่าง:
        Clip · Product ID · #hashtag · คำพูดบนตะกร้า

**ไฟล์นี้ไม่ได้เขียนอะไรใหม่ที่มีอยู่แล้ว** — ต่อท่อของเดิมเข้าด้วยกัน:

    ขั้นดึงของ      tiktok_source.py      (ใหม่ — yt-dlp + probe การ์ดสินค้า)
    ขั้นวิเคราะห์    gemini_video.py       (ใหม่ — พอร์ตจาก 7.web app ที่ใช้จริงแล้ว)
    ขั้นทำคลิป      clip_app._clip_generate → flow_driver  (ของเดิม ไม่แตะ)
    ขั้นโพสต์       tiktok_post.py        (ของเดิม พอร์ตจาก extension มาแล้ว)

เหตุผลที่ใช้ `clip_store` ชุดเดิม: ขั้นหลัง `collect` ของสายเดิมทุกขั้นอ่านของจาก
`run.json` ไม่ได้แตะลิงก์เลย ถ้าเราเขียน `flow_prompts` กับ `script` ลงที่เดียวกัน
ขั้นทำคลิป/สั่งแก้/อนุมัติ ของเดิมก็รับช่วงต่อได้ทันทีโดยไม่ต้องแก้อะไร

id ของงานฝั่งนี้ใช้ `tt_<video_id>` เพื่อไม่ให้ชนกับรหัสสินค้า Shopee ที่เป็นตัวเลขล้วน
(`clip_store.run_dir` ใช้โฟลเดอร์ `shopee_products` ร่วมกัน)
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Callable

import clip_store
import gemini_video
import studio_shared as shared
import tiktok_source

DATA_DIR = shared.DATA_DIR

# คำพูดที่ไปอยู่บนปุ่มตะกร้าของ TikTok (ข้อ ④ ของผัง)
# ค่านี้แก้ได้ทางแชท และอ่านจาก config ก่อนเสมอ
DEFAULT_BASKET_TEXT = "จิ้มที่นี่เลย"

# ความยาวคลิปที่ Veo ทำได้ต่อฉาก — ใช้บอก Gemini ให้แบ่งฉากตามนี้
SCENE_SECONDS_HINT = 10
MAX_SCENES = 6


def item_id_for(video_id: str) -> str:
    """รหัสงานฝั่ง TikTok — ต้องไม่ชนกับ item_id ของ Shopee ที่เป็นตัวเลขล้วน"""
    return f"tt_{video_id}"


def basket_text() -> str:
    value = (shared.read_config().get("tiktok_basket_text") or "").strip()
    return value or DEFAULT_BASKET_TEXT


# ---------------------------------------------------------------- ขั้นวิเคราะห์

# โครงคำตอบที่บังคับ Gemini ให้ตอบตาม — บังคับที่ชั้น API ดีกว่ามานั่งซ่อม JSON
# ที่พังทีหลัง (บทเรียนจากสาย ChatGPT ที่ต้องเขียนด่านซ่อม JSON หลายชั้น)
ANALYZE_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "product_guess": {"type": "string"},
        "speaker_count": {"type": "integer"},
        "scenes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "number": {"type": "integer"},
                    "seconds": {"type": "number"},
                    "shot": {"type": "string"},
                    "prompt": {"type": "string"},
                },
                "required": ["number", "prompt"],
            },
        },
        "transcript": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "speaker": {"type": "string"},
                    "start": {"type": "string"},
                    "text": {"type": "string"},
                },
                "required": ["speaker", "text"],
            },
        },
    },
    "required": ["summary", "scenes", "transcript", "speaker_count"],
}

ANALYZE_PROMPT = f"""คุณคือนักวิเคราะห์คลิปโฆษณาสินค้า ดูคลิปที่แนบมาแล้วทำ 2 งานนี้

**งานที่ 1 — เขียนคำสั่งสร้างคลิปนี้ขึ้นมาใหม่**
แยกคลิปออกเป็นฉาก (ไม่เกิน {MAX_SCENES} ฉาก ฉากละประมาณ {SCENE_SECONDS_HINT} วินาที)
แต่ละฉากเขียน `prompt` ให้ AI สร้างวิดีโอ (Google Veo) ทำตามได้ทันที โดยต้องบอกให้ครบ:
  - มุมกล้องและการเคลื่อนกล้อง
  - สิ่งที่อยู่ในเฟรม สินค้าอยู่ตรงไหน ใหญ่แค่ไหน
  - แสง โทนสี อารมณ์ของภาพ
  - สิ่งที่คนในคลิปทำ (ถ้ามีคน)
  - บทพูดของฉากนั้น เขียนกำกับให้ชัดว่าพูดว่าอะไร เป็นภาษาไทย

เขียน `prompt` เป็นภาษาอังกฤษ ยกเว้นประโยคบทพูดที่ต้องคงภาษาไทยไว้ตามเดิม
ห้ามใส่ตัวหนังสือบนภาพ ห้ามใส่โลโก้ยี่ห้อที่ไม่ได้อยู่ในคลิปต้นฉบับ

**งานที่ 2 — ถอดเสียงพูดทั้งหมดในคลิป**
ถอดทุกคำที่ได้ยิน เรียงตามเวลา ใส่ `start` เป็นเวลาโดยประมาณ (เช่น "0:03")
ถ้ามีคนพูดมากกว่า 1 คน **ต้องแยกให้ชัดว่าใครพูดประโยคไหน** ตั้งชื่อผู้พูดเป็น
"ผู้พูด 1" "ผู้พูด 2" ตามลำดับที่ได้ยินครั้งแรก และใส่ `speaker_count` ให้ตรงจำนวนจริง
ถ้าไม่มีเสียงพูดเลยให้ `transcript` เป็นลิสต์ว่าง และ `speaker_count` เป็น 0

ห้ามแต่งเติมคำที่ไม่ได้ยิน ถ้าฟังไม่ชัดให้เขียนว่า [ฟังไม่ชัด]

ตอบเป็น JSON ตามโครงที่กำหนดเท่านั้น"""


def analyze_clip(
    video: Path,
    api_key: str | None = None,
    log: Callable[[str], None] = print,
) -> dict:
    """① เขียน prompt สร้างคลิป + ② ถอดบทพูดแยกผู้พูด — ยิง Gemini ครั้งเดียวได้ทั้งคู่

    ยิงครั้งเดียวเพราะทั้งสองงานต้องดู "คลิปเดียวกัน" อยู่แล้ว แยกยิงสองรอบคือ
    อัปไฟล์ซ้ำและจ่ายค่าประมวลผลวิดีโอสองรอบโดยไม่ได้อะไรเพิ่ม
    """
    raw = gemini_video.analyze_video(
        video_path=Path(video),
        prompt=ANALYZE_PROMPT,
        api_key=api_key,
        response_schema=ANALYZE_SCHEMA,
        log=log,
    )
    data = _parse_json(raw)

    scenes = [s for s in (data.get("scenes") or []) if str(s.get("prompt") or "").strip()]
    if not scenes:
        raise RuntimeError("Gemini ไม่ได้แตกฉากมาให้ — ดูคำตอบดิบใน gpt-flow.md")
    data["scenes"] = scenes[:MAX_SCENES]
    data["transcript"] = data.get("transcript") or []
    data["_raw"] = raw
    log(
        f"วิเคราะห์คลิปแล้ว: {len(data['scenes'])} ฉาก · "
        f"บทพูด {len(data['transcript'])} บรรทัด · "
        f"ผู้พูด {data.get('speaker_count', 0)} คน"
    )
    return data


def _parse_json(raw: str) -> dict:
    """แกะ JSON จากคำตอบ

    ใช้ responseSchema แล้วปกติจะได้ JSON สะอาด แต่ยังกัน ```json fence ไว้
    เพราะเคยเจอโมเดลใส่มาแม้สั่ง responseMimeType แล้ว
    """
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except ValueError:
        match = re.search(r"\{[\s\S]*\}", text)
        if not match:
            raise RuntimeError(f"อ่านคำตอบของ Gemini ไม่ออก: {text[:200]}") from None
        return json.loads(match.group(0))


def transcript_lines(transcript: list[dict], speaker_count: int = 0) -> list[str]:
    """แปลง transcript เป็นบรรทัดที่คนอ่านรู้เรื่อง สำหรับส่งให้ตรวจในแชท

    มีผู้พูดคนเดียวไม่ต้องใส่ชื่อผู้พูด — รกเปล่าๆ
    มีหลายคนต้องใส่เสมอ เพราะนั่นคือสิ่งที่ผังกำกับไว้ว่าต้องแยกให้เห็น
    """
    lines: list[str] = []
    many = (speaker_count or 0) > 1
    for row in transcript:
        text = str(row.get("text") or "").strip()
        if not text:
            continue
        start = str(row.get("start") or "").strip()
        speaker = str(row.get("speaker") or "").strip()
        head = f"[{start}] " if start else ""
        who = f"{speaker}: " if many and speaker else ""
        lines.append(f"{head}{who}{text}")
    return lines


def build_result(analysis: dict, source: dict) -> dict:
    """แปลงผลวิเคราะห์ให้อยู่ในรูปที่ `clip_store.save_storyboard` รับ

    ทำให้ขั้นถัดไปทั้งหมด (ตรวจ/สั่งแก้/เจนคลิป) ใช้โค้ดเดิมได้โดยไม่ต้องแก้อะไร
    `frames` ว่างเพราะสายนี้ไม่มีภาพสตอรีบอร์ด — เรามีคลิปต้นฉบับเป็นตัวอ้างอิงอยู่แล้ว
    """
    scenes = analysis["scenes"]
    return {
        "frames": [],
        "flow_prompts": [str(s["prompt"]).strip() for s in scenes],
        "script": transcript_lines(
            analysis.get("transcript") or [], analysis.get("speaker_count") or 0
        ),
        "chat_url": "",           # สายนี้ไม่มีแชท GPT ให้กลับไปสั่งแก้
        "refused": False,
        "refusal_text": "",
        "reply": analysis.get("_raw", ""),
        "flow_reply": analysis.get("_raw", ""),
        "script_reply": json.dumps(
            analysis.get("transcript") or [], ensure_ascii=False, indent=2
        ),
        "item_id": source["item_id"],
    }


# ------------------------------------------------------------------ ขั้นโพสต์

def post_to_tiktok(
    video: Path,
    caption: str,
    tags: list[str],
    pid: str = "",
    ptxt: str = "",
    log: Callable[[str], None] = print,
) -> dict:
    """โพสต์คลิปขึ้น TikTok — เรียกของเดิมใน `tiktok_post.py` ไม่เขียนตัวโพสต์ใหม่

    ของเดิมทำครบทุกขั้นและ **รีเช็คว่าสำเร็จจริงทุกขั้น** อยู่แล้ว:
        ขั้น 0 เคลียร์ของค้าง (กด Discard ก่อน Escape เสมอ)
        ขั้น 1 อัปโหลด (ลอง 3 ครั้ง ต้องเห็น editor ใน 20 วิ)
        ขั้น 2 รอ TikTok ประมวลผล (≤180 วิ · เจอ uploadFailed ตัดจบทันที)
        ขั้น 3 แคปชัน + แฮชแท็กทีละตัวรอ suggestion
        ขั้น 4 ผูกสินค้าด้วย Product ID แล้วยืนยันด้วย JS
        ขั้น 4.5 แก้ปก (ต้องยืนยันว่า editor ปิดจริง ไม่งั้นบังปุ่มโพสต์)
        ขั้น 6 กดโพสต์ แล้วต้องเห็นหลักฐานว่าโพสต์แล้วใน 30 วิ

    สองอย่างที่ต้องทำเองตรงนี้ ห้ามลืม:
      1. **ถือ browser_lock** — โปรไฟล์ Chrome มีตัวเดียวทั้งโปรเจกต์
      2. **นับเข้าโควตา 24 ชม. ชุดเดียวกับการโพสต์แบบชุด** ไม่งั้นโพสต์ผ่านสายนี้
         จะไม่ถูกนับ แล้วยอดรวมจะเกินลิมิตจริงโดยไม่รู้ตัว (ทำแบบเดียวกับ
         `flow_pipeline.run_pipeline` ขั้น 6/6)
    """
    import tiktok_post
    from flow_worker import open_browser
    from playwright.sync_api import sync_playwright

    video = Path(video)
    if not video.is_file():
        raise RuntimeError(f"ไม่พบไฟล์คลิปที่จะโพสต์: {video}")

    history = tiktok_post.PostHistory()
    resume_at = history.resume_at(tiktok_post.DAY_LIMIT_DEFAULT)
    if resume_at:
        when = datetime.fromtimestamp(resume_at).strftime("%d/%m %H:%M")
        raise RuntimeError(
            f"ถึงลิมิต {tiktok_post.DAY_LIMIT_DEFAULT} คลิปต่อ 24 ชม.แล้ว "
            f"โพสต์ต่อได้หลัง {when}"
        )
    if history.already_posted(video.name):
        raise RuntimeError(f"คลิป {video.name} เคยโพสต์ไปแล้ว — กันโพสต์ซ้ำ")

    with shared.browser_lock(label="โพสต์คลิปขึ้น TikTok"):
        with sync_playwright() as playwright:
            browser = open_browser(playwright, hidden=False)
            page = browser.pages[0] if browser.pages else browser.new_page()
            try:
                poster = tiktok_post.TikTokPoster(page, log=log)
                outcome = poster.post(
                    video, caption=caption, tags=tags or [],
                    pid=pid or "", ptxt=ptxt or basket_text(),
                )
            except tiktok_post.TikTokNeedsLogin as error:
                raise RuntimeError(
                    f"{error}\n\nยังไม่ได้ล็อกอิน TikTok — รันคำสั่งนี้ที่เครื่อง:\n"
                    "python flow_worker.py login-tiktok"
                ) from error
            finally:
                try:
                    browser.close()
                except Exception:
                    pass

    # บันทึกหลังโพสต์สำเร็จเท่านั้น — บันทึกก่อนแล้วโพสต์ล้ม จะกันตัวเองไม่ให้ลองใหม่
    history.mark_posted(video.name)
    history.record_post()
    log(f"โพสต์ TikTok สำเร็จ · นับเข้าโควตาแล้ว ({history.day.get('count')} คลิปในรอบนี้)")
    return outcome


# ------------------------------------------------------------ ตัวช่วยของสายงาน

def build_post_caption(run: dict) -> str:
    """แคปชันที่จะใช้ตอนโพสต์คลิปใหม่

    ใช้บทพูดบรรทัดแรกเป็นหัว แล้วต่อด้วยแฮชแท็ก — แฮชแท็กถูกส่งแยกให้
    `set_caption()` พิมพ์ทีละตัวรอ suggestion อยู่แล้ว จึงไม่ต้องยัดซ้ำในนี้
    """
    name = str(run.get("name") or "").strip()
    script = run.get("script") or []
    first = re.sub(r"^\[[^\]]*\]\s*", "", str(script[0])) if script else ""
    first = re.sub(r"^ผู้พูด\s*\d+:\s*", "", first).strip()
    return (first or name)[:150]


def summarize_source(source: dict) -> str:
    """ข้อความสรุปของที่ดึงมาได้ ส่งเข้าแชทตอนจบขั้นแรก"""
    product = source.get("product") or {}
    lines = [
        f"🎬 คลิปต้นฉบับ: {source.get('video_id') or '-'}",
        f"👤 เจ้าของคลิป: {source.get('uploader') or '-'}",
        f"⏱ ความยาว: {source.get('duration') or '?'} วินาที",
        f"🏷 แฮชแท็ก {len(source.get('hashtags') or [])} อัน: "
        + (" ".join(source.get("hashtags") or []) or "-"),
        f"🛒 Product ID: {product.get('product_id') or '⛔ ยังดึงไม่ได้'}",
    ]
    return "\n".join(lines)


# ------------------------------------------------------------------------ CLI

def _cli() -> int:
    """เครื่องมือทดสอบทีละขั้น — ใช้ตอนไล่บั๊กโดยไม่ต้องผ่านบอท

    python tiktok_repost.py probe   <ลิงก์>     ดัมพ์หน้าคลิปเพื่อหา selector การ์ดสินค้า
    python tiktok_repost.py fetch   <ลิงก์>     โหลดคลิป + แคปชัน + แฮชแท็ก
    python tiktok_repost.py analyze <ไฟล์.mp4>  ยิง Gemini วิเคราะห์คลิป
    """
    import argparse

    parser = argparse.ArgumentParser(description="เครื่องมือทดสอบสาย TikTok repost")
    sub = parser.add_subparsers(dest="command", required=True)

    probe = sub.add_parser("probe", help="ดัมพ์หน้าคลิปหาการ์ดสินค้า")
    probe.add_argument("link")

    fetch = sub.add_parser("fetch", help="โหลดคลิป + metadata")
    fetch.add_argument("link")

    analyze = sub.add_parser("analyze", help="ให้ Gemini วิเคราะห์คลิปในเครื่อง")
    analyze.add_argument("video")

    args = parser.parse_args()
    scratch = DATA_DIR / "tiktok_probe"

    if args.command == "probe":
        tiktok_source.probe_product(args.link, dump_to=scratch / "probe.json")
        return 0

    if args.command == "fetch":
        video_id = tiktok_source.video_id_from_link(args.link) or "unknown"
        data = tiktok_source.download_clip(args.link, scratch / video_id)
        print(json.dumps(
            {k: str(v) for k, v in data.items() if k != "video"} | {"video": str(data["video"])},
            ensure_ascii=False, indent=2,
        ))
        return 0

    if args.command == "analyze":
        result = analyze_clip(Path(args.video))
        result.pop("_raw", None)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(_cli())
