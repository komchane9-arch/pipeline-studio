"""ให้ Gemini แก้คำสั่ง + บทพูด เมื่อ Google Flow ปฏิเสธด้วยเหตุผลนโยบาย

**ทำไมต้องมี** (วัดจริง 22 ส.ค. 2026)

    prompt ที่มีฉากคนบนเตียง    ได้คลิป 0 จาก 6 งาน
    prompt ที่ไม่มีฉากคนบนเตียง  ได้คลิป 15 จาก 18 งาน

สินค้า "ที่นอน" ทุกตัวโดนปฏิเสธ เพราะ ChatGPT เขียนฉากแบบ "คู่รักนอนบนที่นอน
เดียวกัน คนหนึ่งพลิกตัว" ซึ่งเป็นวิธีโฆษณาที่นอนที่ธรรมชาติที่สุด แต่ Flow รับไม่ได้
ระบบเดิมเจอ PolicyBlocked แล้ว **ข้ามทิ้งเลย** งานเดียวจึงล้มซ้ำ 3 ครั้งใน 3 วัน
โดยไม่มีใครรู้ว่าติดตรงคำไหน

**ทำไมคุ้มที่จะลองใหม่** โดนปฏิเสธเพราะนโยบาย = Google **ไม่คิดเครดิต**
(log 22 ส.ค. 18:46:47 — "เครดิตหลังจบรอบ: 9,690 · รอบนี้ใช้ไป 0") ต่างจากรอบที่
เจนสำเร็จซึ่งหัก 15 การวนแก้จึงเสียแค่เวลา ไม่เสียเงิน

**ทำไมใช้ Gemini ไม่ใช่ ChatGPT** ตัวขับ ChatGPT ต้องเปิดเบราว์เซอร์จริงและแย่ง
โปรไฟล์ Chrome ตัวเดียวกับที่ Flow ใช้อยู่ — เรียกกลางคันตอนเจนไม่ได้ ส่วน Gemini
ยิงผ่าน API ตรง ไม่แตะเบราว์เซอร์ ใช้คีย์เดิมที่มีอยู่แล้ว

**ส่งอะไรให้ Gemini บ้าง** (ผู้ใช้กำหนด 22 ส.ค. 2026) — ต้องเห็นบริบทครบถึงจะแก้ตรงจุด
    1. ภาพสตอรีบอร์ด + รูปสินค้า   ให้เห็นว่าฉากหน้าตายังไง
    2. คำสั่งสร้างวิดีโอ (prompt)
    3. บทพูด (script)
    4. ข้อความ error ที่ Flow แจ้งกลับมาจริง
    5. ชื่อโมเดลที่ใช้เจน           ข้อกำหนดต่างกันตามรุ่น
"""

from __future__ import annotations

import base64
import json
import mimetypes
import re
from pathlib import Path

import httpx
import gemini_quota

ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models"
TIMEOUT = 120.0

# ไล่ใช้ตามลำดับ ตัวไหนโควตาหมดของวันก็ตกไปตัวถัดไป
#
# **ทำไมต้องมีสำรอง** โควตาชั้นฟรีนับ **ต่อวัน ต่อโมเดล** (Google ตอบมาเอง 22 ส.ค.
# 2026: GenerateRequestsPerDayPerProjectPerModel-FreeTier · 20 ครั้ง/วัน) พอถังของ
# โมเดลเดียวหมด ตัวแก้คำสั่งจะตายทั้งระบบ แล้ว**ทุกงานที่โดน Flow บล็อกจะล้มหมด**
# ทั้งที่ระบบมีวิธีแก้อยู่ในมือ — เจอจริงวันนี้ 20:26 คลิปที่นอนใบแรกโดนบล็อก
# ตัวแก้ยิงไปเจอ 429 ทันที งานล้มโดยไม่ได้ลองแก้สักรอบ
#
# เรียงจากเก่งสุดลงมา เพราะงานนี้ต้องอ่านรูปสตอรีบอร์ดแล้วเขียนคำสั่งใหม่ให้
# ความหมายเดิมแต่ผ่านนโยบาย — ตัวเล็กเกินจะเขียนกว้างเกินจนเสียใจความสินค้า
# **ห้ามใส่ตัวที่ซ้ำกับ clip_check.MODELS** ไม่งั้นตัวตรวจคลิปจะกินถังของตัวแก้
# คำสั่งจนหมดโดยไม่รู้ตัว ซึ่งเป็นเหตุที่ทำให้พังมาแล้ววันนี้
MODELS = (
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-3-flash-preview",
)
MODEL = MODELS[0]        # เผื่อโค้ดเก่าที่อ้างชื่อเดี่ยว

# 429 = โควตา/ยิงถี่ · 500/503 = ฝั่ง Google แน่น — ทั้งคู่ควรไปลองโมเดลถัดไป
BUSY_CODES = {429, 500, 503}

# วนแก้ได้กี่รอบต่อหนึ่งฉาก — เท่า KVID (FLOW-PLAYBOOK ข้อ 6.1)
# เกินนี้แปลว่าติดที่เนื้อหาหลักของสินค้า ไม่ใช่แค่ถ้อยคำ วนต่อก็เสียเวลาเปล่า
MAX_ROUNDS = 3
# แนบรูปได้สูงสุดกี่ใบ — มากกว่านี้คำขอใหญ่จนช้า และรูปซ้ำๆ ไม่ได้เพิ่มข้อมูล
MAX_IMAGES = 4

# ฉากที่ยืนยันแล้วว่าทำให้โดนปฏิเสธ — เพิ่มรายการนี้ทุกครั้งที่เจอรูปแบบใหม่
# (ให้บทเรียนอยู่ในโค้ด ไม่ใช่ในหัวคน)
KNOWN_BLOCKED = (
    "คนนอนอยู่บนเตียงหรือบนที่นอน",
    "คู่รัก/สองคนอยู่บนเตียงเดียวกัน",
    "คนกำลังนอนหลับ",
    "คนพลิกตัวบนที่นอน",
    "คนสวมชุดนอนอยู่ในห้องนอน",
)

# คำที่บอกว่ายังมีฉากเสี่ยง — ใช้ทั้งตอนตรวจก่อนยิง (ไม่ต้องรอ Flow ปฏิเสธ 5 นาที)
# และตอนตรวจว่า Gemini แก้ให้จริงหรือแค่ขยับคำ
RISKY_RE = re.compile(
    r"คู่รัก|คู่สามีภรรยา|สามีภรรยา|นอนบนที่นอน|นอนบนเตียง|นอนหลับ|"
    r"พลิกตัว|ชุดนอน|คนนอน|"
    r"\bcouple\b|\blying on\b|\bsleeping\b|\bin bed\b|\basleep\b",
    re.I,
)

REWRITE_PROMPT = """คุณคือผู้ช่วยแก้คำสั่งสร้างวิดีโอโฆษณาให้ผ่านนโยบายของ Google Flow

งานนี้ถูก Google Flow **ปฏิเสธ** ให้ช่วยปรับ **คำสั่ง (prompt)** และ **บทพูด**
ให้ผ่านข้อกำหนดตามที่ error แจ้ง โดยยังขายของได้เหมือนเดิม

━━ ข้อมูลของงานนี้ ━━
โมเดลที่ใช้เจน : {model}
ข้อความ error ที่ Flow แจ้งกลับมา :
{reason}

รูปที่แนบมาคือ **ภาพสตอรีบอร์ดและรูปสินค้าจริง** ของงานนี้ ดูประกอบเพื่อให้เข้าใจว่า
ฉากหน้าตาเป็นอย่างไร แล้วแก้ให้ตรงจุด

━━ ฉากที่เคยโดนปฏิเสธมาแล้ว (ต้องเลี่ยง) ━━
{blocked}

━━ วิธีเปลี่ยนที่ยังขายของได้เหมือนเดิม ━━
ใช้ภาพที่สื่อคุณสมบัติแทนการใช้คน เช่น
- "พลิกตัวไม่กวนคนข้างๆ" → แก้วน้ำวางบนที่นอน มีมือกดที่นอนข้างๆ แล้วน้ำไม่กระเพื่อม
- "นอนหลับสบาย"        → ห้องนอนสงบ ที่นอนจัดเรียบร้อย แสงเช้าสาดผ่านม่าน
- "รองรับสรีระ"         → ภาพตัดขวางโครงสร้างสปริง หรือมือกดผิวที่นอนแล้วคืนตัว

━━ สิ่งที่ห้ามเปลี่ยนเด็ดขาด ━━
- โครงสร้างฉาก หมายเลขฉาก และช่วงเวลา (เช่น "SCENE 3 — 4–6 sec")
- ข้อความบนจอ (ในเครื่องหมายคำพูด)
- ชื่อรุ่นสินค้า
- ความยาวโดยรวม (ต่างได้ไม่เกิน 20%)
- ภาษาที่ใช้ — ส่วนไหนเป็นไทยคงเป็นไทย ส่วนไหนเป็นอังกฤษคงเป็นอังกฤษ
- **จำนวนฉากของบทพูดต้องเท่าเดิม** ({script_count} ฉาก)

━━ รูปแบบคำตอบ ━━
ตอบเป็น JSON เท่านั้น ห้ามมีข้อความอื่นนอก JSON ห้ามใส่ markdown
{{"prompt": "คำสั่งที่แก้แล้ว", "script": ["บทพูดฉาก 1", "บทพูดฉาก 2", ...],
  "changed": "สรุปสั้นๆ ว่าแก้อะไรไป ไม่เกิน 2 บรรทัด"}}

ถ้าบทพูดไม่ต้องแก้ ให้ส่งบทพูดเดิมกลับมาครบทุกฉาก

━━ คำสั่งเดิม ━━
{prompt}

━━ บทพูดเดิม ━━
{script}"""


class PolicyFixError(RuntimeError):
    """แก้คำสั่งให้ผ่านนโยบายไม่สำเร็จ"""


# หัวข้อที่ตามด้วย "ของที่จะได้ยิน/ได้อ่าน" ไม่ใช่ "ของที่จะเห็นเป็นภาพ"
# ต้องตัดออกก่อนตรวจคำเสี่ยง — Google บล็อกที่ภาพที่สร้าง ไม่ใช่ตัวหนังสือหรือเสียง
_NON_VISUAL_RE = re.compile(
    r"^\s*(ข้อความบนจอ|ตัวหนังสือบนจอ|Text on screen|On-screen text|"
    r"Voice ?Over|VO|บทพูด|เสียงพูด)\s*[:：]",
    re.I | re.M,
)


def visual_part(text: str) -> str:
    """ตัดส่วน "ข้อความบนจอ" กับ "Voice Over" ออก เหลือเฉพาะคำอธิบายภาพ

    **ทำไมต้องแยก** คำสั่งหนึ่งฉากมีสามอย่างปนกัน: ภาพที่จะสร้าง · ตัวหนังสือที่จะ
    ขึ้นจอ · เสียงที่จะพูด — Google บล็อกเฉพาะ **ภาพ** ส่วนอีกสองอย่างเป็นจุดขาย
    ที่ต้องคงไว้ (เจอจริง 22 ส.ค.: Gemini แก้ภาพเป็นแก้วน้ำสำเร็จ แต่ถูกตีตกเพราะ
    ข้อความบนจอเขียนว่า "พลิกตัวสบาย" ซึ่งไม่ได้ผิดอะไรและห้ามแก้อยู่แล้ว)
    """
    lines = (text or "").split("\n")
    out, skipping = [], False
    for line in lines:
        if _NON_VISUAL_RE.match(line):
            skipping = True
            continue
        if skipping:
            # ข้ามไปจนกว่าจะเจอบรรทัดว่างสองที หรือหัวข้อใหม่ที่ไม่ใช่คำพูด
            if not line.strip() or re.match(r"^\s*(SCENE|Shot|Camera)\b", line, re.I):
                skipping = False
                if line.strip():
                    out.append(line)
            continue
        out.append(line)
    return "\n".join(out)


def looks_risky(text: str, visual_only: bool = True) -> list[str]:
    """คำเสี่ยงที่พบ — ว่าง = ไม่พบฉากที่เคยโดนปฏิเสธ

    ตรวจเฉพาะส่วนคำอธิบายภาพเป็นค่าปริยาย (ดู `visual_part`) ส่ง
    `visual_only=False` เมื่ออยากดูทั้งก้อนจริงๆ

    ใช้ตรวจ **ก่อน** ยิงเข้า Flow ได้ด้วย จะได้ไม่ต้องรอ 5 นาทีเพื่อรู้ว่าโดนปฏิเสธ
    """
    body = visual_part(text) if visual_only else (text or "")
    return sorted({m.group(0).lower() for m in RISKY_RE.finditer(body)})


def _image_parts(images, log) -> list[dict]:
    """อ่านรูปเป็น inline_data ให้ Gemini — อ่านไม่ได้ก็ข้ามใบนั้น ไม่ล้มทั้งงาน"""
    parts = []
    for path in list(images or [])[:MAX_IMAGES]:
        try:
            payload = Path(path).read_bytes()
        except OSError as error:
            log(f"  แนบรูป {Path(path).name} ไม่ได้ ({error}) — ข้ามใบนี้")
            continue
        mime = mimetypes.guess_type(str(path))[0] or "image/png"
        parts.append({"inline_data": {
            "mime_type": mime,
            "data": base64.b64encode(payload).decode("ascii"),
        }})
    return parts


def rewrite(
    prompt: str,
    reason: str,
    api_key: str,
    script: list[str] | None = None,
    images=None,
    model: str = "",
    log=print,
    _retry_left: int = 2,
) -> dict:
    """ให้ Gemini แก้คำสั่ง+บทพูดให้ผ่านนโยบาย — คืน {prompt, script, changed}

    โยน `PolicyFixError` เมื่อแก้ไม่ได้ ผู้เรียกตัดสินใจเองว่าจะข้ามฉากนี้ไหม
    **ไม่กลืนเงียบ** เพราะถ้าคืนของเดิมไปเฉยๆ ตัวเรียกจะยิงซ้ำด้วยของเดิมแล้ว
    โดนปฏิเสธเหมือนเดิม วนไม่จบ
    """
    if not api_key:
        raise PolicyFixError("ไม่มีคีย์ Gemini — แก้คำสั่งอัตโนมัติไม่ได้")
    if not (prompt or "").strip():
        raise PolicyFixError("คำสั่งว่างเปล่า")

    script = list(script or [])
    instruction = REWRITE_PROMPT.format(
        model=model or "(ไม่ระบุ)",
        reason=(reason or "(Flow ไม่ได้ให้รายละเอียด)")[:600],
        blocked="\n".join(f"  - {item}" for item in KNOWN_BLOCKED),
        script_count=len(script),
        prompt=prompt,
        script="\n".join(f"{i}. {text}" for i, text in enumerate(script, 1))
               or "(ไม่มีบทพูดแยกไว้)",
    )
    parts = [{"text": instruction}] + _image_parts(images, log)
    if len(parts) > 1:
        log(f"  ส่งให้ Gemini พร้อมรูป {len(parts) - 1} ใบ · โมเดล Flow: {model or '-'}")

    # ยิงซ้ำได้ถ้าคำตอบอ่านไม่ออก — Gemini ตอบไม่คงที่ทุกครั้ง (เจอจริง 22 ส.ค.:
    # รอบเดียวกัน ครั้งหนึ่งได้ JSON ครบ อีกครั้งอ่านไม่ออก) การยิงซ้ำถูกและเร็ว
    # กว่าปล่อยให้ทั้งงานตกไปเพราะคำตอบเสียครั้งเดียว
    # ยิงได้สองครั้งต่อโมเดล แล้วถ้าโมเดลนั้นเต็มโควตาก็ตกไปตัวถัดไปใน MODELS
    # (ยิงซ้ำเพราะคำตอบอ่านไม่ออกได้ · เปลี่ยนโมเดลเพราะถังหมดวัน)
    data, last_error, raw = None, "", ""
    for gem in MODELS:
        for attempt in range(1, 3):
            try:
                response = httpx.post(
                    f"{ENDPOINT}/{gem}:generateContent",
                    params={"key": api_key},
                    json={
                        "contents": [{"parts": parts}],
                        "generationConfig": {"responseMimeType": "application/json"},
                    },
                    timeout=TIMEOUT,
                )
                gemini_quota.record(gem, ok=response.status_code == 200,
                                    response=response)
            except httpx.HTTPError as error:
                last_error = f"ต่อ Gemini ไม่ได้: {error}"
                continue
            if response.status_code in BUSY_CODES:
                # ถังของโมเดลนี้เต็ม/ล่ม — ยิงซ้ำตัวเดิมก็ได้ผลเดิม ไปตัวถัดไปเลย
                last_error = f"{gem} ตอบ {response.status_code}"
                log(f"  {last_error} — เปลี่ยนโมเดล")
                break
            if response.status_code != 200:
                last_error = f"{gem} ตอบ {response.status_code}"
                continue
            try:
                raw = response.json()["candidates"][0]["content"]["parts"][0]["text"]
            except (KeyError, IndexError, ValueError):
                last_error = "อ่านคำตอบ Gemini ไม่ได้"
                continue
            try:
                data = _parse(raw)
                break
            except PolicyFixError as error:
                last_error = str(error)
                # **ต้องเห็นของจริงเวลาไล่สาเหตุ** ไม่ใช่รู้แค่ว่า "อ่านไม่ได้"
                log(f"  คำตอบรอบ {attempt} อ่านไม่ออก ({error}) — ยิงซ้ำ · "
                    f"ขึ้นต้นว่า {raw.strip()[:80]!r}")
        if data is not None:
            if gem != MODELS[0]:
                log(f"  ใช้โมเดลสำรอง {gem} แก้ให้แทน")
            break
    if data is None:
        raise PolicyFixError(last_error or "Gemini ตอบกลับมาใช้ไม่ได้")
    fixed = (data.get("prompt") or "").strip()
    if not fixed:
        raise PolicyFixError("Gemini ไม่ได้ส่งคำสั่งใหม่กลับมา")

    # ยาว/สั้นผิดรูป = ไม่ได้แก้ถ้อยคำ แต่เขียนใหม่ทั้งเรื่องหรือตอบไม่ครบ
    ratio = len(fixed) / max(len(prompt), 1)
    if not 0.5 <= ratio <= 1.6:
        raise PolicyFixError(
            f"คำสั่งใหม่ยาวผิดรูป ({len(prompt)} → {len(fixed)} ตัวอักษร)"
        )

    new_script = [str(line).strip() for line in (data.get("script") or []) if str(line).strip()]
    if script and len(new_script) != len(script):
        log(f"  ⚠️ บทพูดที่ได้กลับมา {len(new_script)} ฉาก (เดิม {len(script)}) — ใช้บทเดิมแทน")
        new_script = script

    # ตรวจคำเสี่ยงเฉพาะ **คำสั่งภาพ** ไม่ตรวจบทพูด
    #
    # Google บล็อกที่ภาพที่จะสร้าง ไม่ใช่เสียงที่จะพูด — บทพูด "พลิกตัวก็ไม่ค่อย
    # กวนคนข้างๆ" คือจุดขายของที่นอนที่ต้องมี ถ้าตรวจบทพูดด้วยจะตีตกงานที่แก้
    # ถูกต้องแล้ว (เจอจริง 22 ส.ค.: Gemini แก้ภาพเป็นแก้วน้ำสำเร็จ แต่ถูกตีตก
    # เพราะบทพูดมีคำว่า "พลิกตัว" ซึ่งไม่ได้ผิดอะไรเลย)
    left = looks_risky(fixed)
    if left and _retry_left > 0:
        # บอก Gemini ตรงๆ ว่าเหลือคำไหน แล้วให้แก้ต่อ — ดีกว่ายอมแพ้ตั้งแต่รอบแรก
        # เพราะบางคำมันตีความว่าไม่ผิด (เช่น "คนนอนสบาย" ที่บรรยายคุณสมบัติ
        # ไม่ใช่ภาพคนนอน) พอชี้ให้เห็นก็เปลี่ยนถ้อยคำให้ได้
        log(f"  ยังเหลือคำเสี่ยง {' · '.join(left[:4])} — บอก Gemini ให้แก้ต่อ")
        return rewrite(
            fixed,
            f"{reason}\n\nรอบก่อนแก้แล้วแต่ **คำอธิบายภาพยังมีคำเหล่านี้อยู่**: "
            f"{' · '.join(left)} — ต้องเขียนใหม่ให้ไม่มีคำพวกนี้ในส่วนคำอธิบายภาพ "
            "(ส่วนข้อความบนจอกับ Voice Over คงเดิมได้)",
            api_key, script=new_script or script, images=images, model=model,
            log=log, _retry_left=_retry_left - 1,
        )
    if left:
        raise PolicyFixError(f"คำสั่งภาพยังเหลือคำเสี่ยง: {' · '.join(left[:4])}")

    changed = (data.get("changed") or "").strip()
    log(f"  Gemini แก้ให้แล้ว ({len(prompt)} → {len(fixed)} ตัวอักษร)"
        + (f" — {changed[:120]}" if changed else ""))
    return {"prompt": fixed, "script": new_script or script, "changed": changed}


def _parse(text: str) -> dict:
    """อ่าน JSON จากคำตอบ — เผื่อ AI ห่อ markdown มาให้"""
    body = (text or "").strip()
    fence = re.match(r"^```[a-zA-Z]*\n(.*)\n```$", body, re.S)
    if fence:
        body = fence.group(1).strip()
    try:
        data = json.loads(body)
    except ValueError:
        found = re.search(r"\{.*\}", body, re.S)
        if not found:
            raise PolicyFixError("Gemini ไม่ได้ตอบเป็น JSON") from None
        try:
            data = json.loads(found.group(0))
        except ValueError as error:
            raise PolicyFixError("อ่าน JSON จากคำตอบ Gemini ไม่ได้") from error
    if not isinstance(data, dict):
        raise PolicyFixError("คำตอบ Gemini ไม่ใช่ JSON object")
    return data
