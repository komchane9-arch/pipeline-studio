"""ให้ AI **ดูคลิปที่ได้จริง** แล้วแก้คำสั่ง Flow ตามคอมเมนต์ของผู้ใช้

ผู้ใช้สั่ง 26 ส.ค. 2026 สองรอบ:
  1. "ตรงฟังก์ชั่นลบแล้วเจนใหม่ ให้มีช่องใส่คอมเมนต์ที่ต้องแก้ด้วย
     แล้วให้ทำคอมเมนต์นั้นไปปรับแก้"
  2. "AI จะต้องสามารถดูข้อผิดพลาดในวีดีโอได้ด้วย"

**ทำไมต้องมี** ปุ่ม "ลบแล้วเจนใหม่" ของเดิมลบไฟล์คลิปทิ้งแล้ว **เจนซ้ำด้วยคำสั่ง
ชุดเดิมเป๊ะๆ** ซึ่งขัดกติกาของโปรเจกต์ตรงๆ:

    "retry ต้องเปลี่ยนอะไรบางอย่าง ไม่ใช่ยิงของเดิมซ้ำ
     ของเดิมย่อมได้ผลเดิม แต่เสียเครดิตเพิ่ม"   — CLAUDE.md ข้อ 3

คลิปไม่ถูกใจแล้วกดเจนใหม่ จึงได้ของหน้าตาเดิมกลับมา เสียเครดิต Flow ไปฟรีๆ


ใช้ AI ตัวไหน และมันเห็นคลิปจริงไหม
------------------------------------
ใช้ **Gemini รุ่น 3.5-flash ผ่านช่องอัปไฟล์ (Files API)** — ตัวเดียวกับที่สาย
TikTok repost ใช้ดูคลิปอยู่แล้ว (`gemini_video.analyze_video`)

**มันเห็นคลิปจริงทั้งภาพและเสียง** ไม่ใช่เดาจากข้อความ — Gemini เป็นเจ้าเดียวที่รับ
วิดีโอทั้งไฟล์เข้าไปดูได้ตรงๆ เจ้าอื่นต้องแยกเป็น "ดึงเฟรม + ถอดเสียง" เอง
จึงส่งของสามอย่างไปพร้อมกันในคำขอเดียว

    คลิปที่ได้จริง  +  คอมเมนต์ของผู้ใช้  +  คำสั่ง Flow ชุดเดิม

แล้วให้มันบอกกลับมาว่า **เห็นอะไรผิดในคลิปบ้าง** (`problems`) คู่กับคำสั่งที่แก้แล้ว
ส่วน `problems` ไม่ได้เอาไปใช้ทำอะไรต่อ แต่โชว์ให้ผู้ใช้อ่าน — เป็นหลักฐานว่า
มันดูคลิปจริง ไม่ได้แค่แต่งคำสั่งใหม่ลอยๆ

**ต้องแก้คำสั่งก่อนลบคลิป** ผู้เรียกต้องเรียกตัวนี้ให้เสร็จก่อน แล้วค่อยลบไฟล์คลิป
ถ้าลบก่อนจะไม่เหลืออะไรให้ AI ดู (ดู `vid_edit` ใน clip_app.py)

**ไม่ยอมคืนคำสั่งเดิมเงียบๆ** แก้ไม่ได้ = โยน `ClipFixError` ให้ผู้เรียกบอกผู้ใช้ตรงๆ
ดีกว่าปล่อยให้เจนซ้ำแล้วผู้ใช้นึกว่าคอมเมนต์มีผลทั้งที่ไม่มี
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import gemini_quota

# ดูคลิปได้ = ต้องเป็นรุ่นที่รับวิดีโอ ใช้ตัวเดียวกับ `gemini_video` ที่พิสูจน์แล้ว
VIDEO_MODEL = "gemini-3.5-flash"

# ไม่มีคลิปให้ดู (ถูกลบไปแล้ว / ยังไม่เคยเจน) ค่อยถอยมาแก้จากข้อความล้วน
# **ตั้งใจใช้ชุดเดียวกับ policy_fix** เพราะเป็นงานตระกูลเดียวกัน (แก้คำสั่ง Flow
# ด้วยข้อความ) และสองงานนี้ไม่ทำพร้อมกัน
TEXT_MODELS = (
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-3-flash-preview",
)

TIMEOUT = 120.0
MAX_NOTE = 800          # กันคอมเมนต์ยาวจนกินที่ของคำสั่งจริง


class ClipFixError(RuntimeError):
    """แก้คำสั่งตามคอมเมนต์ไม่สำเร็จ"""


_RULES = (
    "กติกา\n"
    "  · **จำนวนชุดต้องเท่าเดิมเป๊ะ {count} ชุด** ห้ามเพิ่ม ห้ามลด "
    "เพราะแต่ละชุดผูกกับฉากในคลิป\n"
    "  · แก้เฉพาะชุดที่เกี่ยวกับสิ่งที่ผู้ใช้บอก "
    "**ชุดที่ไม่เกี่ยวให้คงไว้เหมือนเดิมทุกตัวอักษร**\n"
    "  · ผู้ใช้เขียนภาษาไทย แต่คำสั่งเป็นภาษาอังกฤษ — แปลความต้องการแล้วเขียน\n"
    "    เป็นภาษาอังกฤษให้เข้ากับคำสั่งเดิม ห้ามเปลี่ยนคำสั่งเป็นภาษาไทย\n"
    "  · ผู้ใช้ไม่ได้ระบุฉาก ให้ตีความว่าใช้กับทุกฉาก\n"
    "  · ห้ามแตะโครงสร้างอื่นของคำสั่ง (หัวข้อฉาก · ความยาววินาที · บทพูด)\n"
    "    ถ้าไม่ได้ถูกขอให้แก้\n"
    "  · `why` บอกสั้นๆ เป็นภาษาไทยว่าแก้อะไรไปบ้าง"
)

VIDEO_PROMPT = (
    "คลิปที่แนบมาคือคลิปโฆษณาสินค้าที่เจนจากคำสั่งข้างล่างนี้ "
    "ผู้ใช้ดูแล้วไม่ถูกใจ\n\n"
    "**ดูคลิปให้จบก่อน** แล้วหาว่ามันมีปัญหาตรงไหนจริงๆ "
    "(ภาพ · การเคลื่อนกล้อง · สินค้าถูกตัดขอบ · ตัวหนังสือ · จังหวะ · เสียง)\n"
    "ใส่สิ่งที่เห็นลงในช่อง problems เป็นภาษาไทย ระบุฉากด้วยถ้าระบุได้\n\n"
    "สิ่งที่ผู้ใช้เขียนบอกมาว่าต้องแก้:\n"
    "<<<\n{note}\n>>>\n\n"
    "คำสั่งเดิมมี {count} ชุด (ชุดที่ 1 = ฉากที่ 1 เรียงตามลำดับ):\n\n"
    "{prompts}\n\n"
    "งานของคุณ: แก้คำสั่งให้ตรงกับที่ผู้ใช้ขอ **โดยอ้างอิงจากสิ่งที่เห็นในคลิปจริง**\n"
    "ถ้าเห็นปัญหาอื่นที่ผู้ใช้ไม่ได้พูดถึงแต่เกี่ยวกับเรื่องเดียวกัน แก้ไปด้วยได้\n\n"
    + _RULES
)

TEXT_PROMPT = (
    "นี่คือคำสั่งสร้างวิดีโอสำหรับ Google Flow ที่ใช้เจนคลิปโฆษณาสินค้าไปแล้ว\n"
    "ผู้ใช้ดูคลิปแล้วไม่ถูกใจ และเขียนบอกมาว่าต้องแก้ตรงไหน\n"
    "(คลิปถูกลบไปแล้ว จึงไม่มีให้ดู — แก้จากคำสั่งกับคำบอกเล่าเท่านั้น)\n\n"
    "สิ่งที่ผู้ใช้เขียนบอกมา:\n"
    "<<<\n{note}\n>>>\n\n"
    "คำสั่งเดิมมี {count} ชุด (ชุดที่ 1 = ฉากที่ 1 เรียงตามลำดับ):\n\n"
    "{prompts}\n\n"
    "งานของคุณ: แก้คำสั่งให้ตรงกับที่ผู้ใช้ขอ แล้วตอบเป็น JSON อย่างเดียว\n\n"
    + _RULES + "\n\n"
    '{{"problems": [], "prompts": ["ชุดที่ 1", "ชุดที่ 2", "..."], "why": "..."}}'
)

ANSWER_SCHEMA = {
    "type": "object",
    "properties": {
        "problems": {"type": "array", "items": {"type": "string"}},
        "prompts": {"type": "array", "items": {"type": "string"}},
        "why": {"type": "string"},
    },
    "required": ["prompts", "why"],
}


def _parse(text: str) -> dict:
    """อ่าน JSON จากคำตอบ — เผื่อ AI ห่อ markdown มาให้"""
    body = (text or "").strip()
    fence = re.search(r"```(?:json)?\s*(.+?)```", body, re.S)
    if fence:
        body = fence.group(1).strip()
    found = re.search(r"\{.*\}", body, re.S)
    if not found:
        raise ClipFixError("อ่านคำตอบของ AI ไม่ออก (ไม่เจอ JSON)")
    try:
        data = json.loads(found.group(0))
    except json.JSONDecodeError as error:
        raise ClipFixError(f"คำตอบของ AI ไม่ใช่ JSON ที่ถูกต้อง ({error})") from error
    if not isinstance(data, dict):
        raise ClipFixError("คำตอบของ AI ไม่ใช่ JSON แบบวัตถุ")
    return data


def _finish(data: dict, rows: list[str], how: str, log) -> dict:
    """ตรวจคำตอบแล้วสรุปผล — ที่นี่ที่เดียว ทั้งทางดูคลิปและทางข้อความใช้ร่วมกัน"""
    fixed = [str(p) for p in (data.get("prompts") or [])]
    if len(fixed) != len(rows):
        # **จำนวนชุดต้องเท่าเดิม** ไม่งั้นฉากจะเลื่อนกันทั้งแถบ
        # แล้วคลิปจะพูดเรื่องหนึ่งแต่ภาพเป็นอีกเรื่อง
        raise ClipFixError(
            f"AI คืนคำสั่งมา {len(fixed)} ชุด แต่ของเดิมมี {len(rows)} ชุด")
    if all(a.strip() == b.strip() for a, b in zip(fixed, rows)):
        raise ClipFixError("AI ไม่ได้แก้อะไรเลย — ลองเขียนคอมเมนต์ให้ชัดกว่านี้")

    # เชื่อการเทียบของเราเอง ไม่เชื่อเลขที่ AI บอก — มันบอกผิดได้
    changed = [i for i, (a, b) in enumerate(zip(fixed, rows), 1)
               if a.strip() != b.strip()]
    problems = [str(x).strip() for x in (data.get("problems") or []) if str(x).strip()]
    why = str(data.get("why") or "").strip()
    log(f"  แก้คำสั่ง Flow ไป {len(changed)} ชุด (ชุดที่ {changed}) · {how}"
        + (f" — {why}" if why else ""))
    for line in problems:
        log(f"    AI เห็นปัญหา: {line}")
    return {"prompts": fixed, "changed": changed, "why": why,
            "problems": problems, "how": how}


def _from_text(rows: list[str], note: str, api_key: str, log) -> dict:
    """ทางถอยเมื่อไม่มีคลิปให้ดู — แก้จากคำสั่งกับคอมเมนต์อย่างเดียว"""
    import httpx

    instruction = TEXT_PROMPT.format(
        note=note[:MAX_NOTE], count=len(rows),
        prompts="\n\n".join(f"=== ชุดที่ {i} ===\n{row}"
                            for i, row in enumerate(rows, 1)),
    )
    last = ""
    for model in TEXT_MODELS:
        try:
            response = httpx.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/"
                f"{model}:generateContent",
                params={"key": api_key},
                json={
                    "contents": [{"parts": [{"text": instruction}]}],
                    "generationConfig": {"responseMimeType": "application/json"},
                },
                timeout=TIMEOUT,
            )
            gemini_quota.record(model, ok=response.status_code == 200,
                                response=response)
            if response.status_code != 200:
                raise ClipFixError(f"{model} ตอบ {response.status_code}")
            data = _parse(response.json()["candidates"][0]["content"]["parts"][0]["text"])
            return _finish(data, rows, f"อ่านจากคำสั่งอย่างเดียว ({model})", log)
        except Exception as error:                           # noqa: BLE001
            last = str(error)
            log(f"  แก้คำสั่งด้วย {model} ไม่สำเร็จ ({error})")
    raise ClipFixError(f"ให้ AI แก้คำสั่งตามคอมเมนต์ไม่สำเร็จ — {last}")


def apply_note(prompts, note: str, api_key: str, video=None, log=print) -> dict:
    """ให้ AI ดูคลิปแล้วแก้คำสั่ง Flow ตามคอมเมนต์

    คืน {"prompts", "changed", "why", "problems", "how"}
    โยน `ClipFixError` เมื่อแก้ไม่ได้ — **ห้ามคืนของเดิมเงียบๆ** เพราะถ้าคืนไป
    ตัวเรียกจะเจนคลิปด้วยคำสั่งเดิม แล้วผู้ใช้จะได้คลิปหน้าตาเดิมกลับมา
    ทั้งที่เพิ่งพิมพ์คอมเมนต์ไป — เสียเครดิต Flow ฟรีและเข้าใจผิดว่าระบบพัง
    """
    rows = [str(p) for p in (prompts or []) if str(p).strip()]
    if not rows:
        raise ClipFixError("งานนี้ไม่มีคำสั่ง Flow ให้แก้")
    text = (note or "").strip()
    if not text:
        raise ClipFixError("ยังไม่ได้พิมพ์ว่าจะแก้อะไร")
    if not api_key:
        raise ClipFixError("ยังไม่ได้ใส่คีย์ Gemini — แก้คำสั่งอัตโนมัติไม่ได้")

    clip = Path(video) if video else None
    if not (clip and clip.is_file()):
        log("  ไม่มีไฟล์คลิปให้ AI ดู — แก้จากคำสั่งกับคอมเมนต์แทน")
        return _from_text(rows, text, api_key, log)

    import gemini_video

    instruction = VIDEO_PROMPT.format(
        note=text[:MAX_NOTE], count=len(rows),
        prompts="\n\n".join(f"=== ชุดที่ {i} ===\n{row}"
                            for i, row in enumerate(rows, 1)),
    )
    log(f"  ส่งคลิป {clip.name} ให้ AI ดู แล้วแก้คำสั่ง {len(rows)} ชุดตามคอมเมนต์")
    try:
        answer = gemini_video.analyze_video(
            clip, instruction, api_key=api_key, model=VIDEO_MODEL,
            response_schema=ANSWER_SCHEMA, log=log,
        )
        data = _parse(answer)
        return _finish(data, rows, f"ดูคลิปจริง ({VIDEO_MODEL})", log)
    except ClipFixError:
        raise
    except Exception as error:                               # noqa: BLE001
        # ดูคลิปไม่ได้ (อัปไม่ขึ้น · โควตาหมด) ยังพอแก้จากข้อความได้
        # **แต่ต้องบอกให้รู้ว่าถอยมาทางไหน** ไม่ใช่เงียบแล้วให้เข้าใจว่าดูคลิปแล้ว
        log(f"  ให้ AI ดูคลิปไม่สำเร็จ ({error}) — ถอยไปแก้จากคำสั่งอย่างเดียว")
        return _from_text(rows, text, api_key, log)
