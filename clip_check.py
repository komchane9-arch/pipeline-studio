"""ตรวจคลิปที่เจนเสร็จ — **ชัดพอไหม** กับ **มีเสียงพูดจริงไหม** (ผู้ใช้สั่ง 22 ส.ค. 2026)

ทำไมต้องมีด่านนี้ ทั้งสองข้อเคยพลาดเงียบมาแล้วจริง

  1. **ความชัด** — Flow ให้ดาวน์โหลดหลายขนาด ถ้าปุ่ม 1080p ยังไม่ขึ้น (อัปสเกลไม่ทัน)
     ตัวโหลดจะถอยไปหยิบ 720p แล้ว**ไฟล์ก็ได้มาปกติ** ไม่มีอะไรฟ้อง วัดจริง 22 ส.ค.
     2026: คลิปในเครื่อง 15 ไฟล์ เป็น 1080p แค่ 4 ไฟล์ อีก 11 ไฟล์ยัง 720×1280 อยู่
     ทั้งที่ไม่มีใครรู้ตัว

  2. **เสียงพูด** — Veo เจนเสียงไทยล้มบ่อย (ดู thai_speech.py) เวลาล้มมัน**ไม่ได้ส่ง
     ไฟล์เปล่ามา** แต่ส่งคลิปที่มีแต่ดนตรี/เสียงบรรยากาศมาแทน เช็คแค่ "มีแทร็กเสียงไหม"
     จึงผ่านหมดทุกไฟล์ (วัดจริง: ทั้ง 15 ไฟล์มี aac 48kHz สเตอริโอครบ) ต้องฟังจริง
     ถึงจะแยกออกว่าเป็นคนพูดหรือแค่ดนตรี

ตรวจสองชั้น เพราะราคาต่างกันมาก

    ชั้น 1  ffprobe + ffmpeg   ฟรี ออฟไลน์ ~0.2 วิ/ไฟล์  → ขนาดภาพ · มีเสียงไหม · ดังแค่ไหน
    ชั้น 2  ส่งเสียงให้ Gemini  ถูกมาก ~3 วิ/ไฟล์        → เป็นเสียงพูดจริงไหม · พูดว่าอะไร

ชั้น 1 ตอบไม่ได้ว่า "เป็นเสียงพูด" — ดนตรีก็ดัง -17 dB เหมือนกัน จึงต้องมีชั้น 2
ชั้น 2 ตอบไม่ได้ว่าไฟล์กี่พิกเซล จึงต้องมีชั้น 1  ขาดข้างใดข้างหนึ่งไม่ได้

**ตรวจไม่ได้ ≠ ผ่าน** ถ้าไม่มีคีย์ Gemini หรือยิงไม่ติด จะคืน has_speech = None แล้ว
รายงานว่า "ตรวจเสียงพูดไม่ได้" ไม่ใช่ตีเป็นผ่าน — ไม่งั้นวันที่คีย์หมดอายุ คลิปเสียงเงียบ
จะไหลผ่านทั้งคิวโดยขึ้นเครื่องหมายถูกให้ดูสบายใจ
"""

from __future__ import annotations

import base64
import json
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import httpx
import gemini_quota

# ---------------------------------------------------------------- ค่าที่ใช้ตัดสิน

# ด้านสั้นต้องถึงเท่านี้ถึงเรียกว่า 1080p — คลิปเป็นแนวตั้ง 1080×1920 ด้าน "สั้น"
# คือ 1080 การวัดด้านสั้นทำให้ใช้ได้ทั้งแนวตั้งและแนวนอนโดยไม่ต้องแยกเคส
MIN_SHORT_SIDE = 1080

# เสียงเบากว่านี้ถือว่า "เงียบ" — วัดจากของจริง คลิปที่มีเสียงปกติได้ max ราว -1 dB
SILENT_MAX_DB = -50.0
# เสียงเฉลี่ยเบากว่านี้ถือว่าเบาผิดปกติ (ของจริงอยู่ราว -16 ถึง -19 dB)
QUIET_MEAN_DB = -35.0

# โมเดลที่ใช้ฟังเสียง — **ตั้งใจไม่ใช้ตัวเดียวกับ policy_fix / hashtag**
#
# โควตาชั้นฟรีนับ **แยกรายโมเดล และเป็นต่อวัน ไม่ใช่ต่อนาที** (อ่านจากคำตอบจริง
# ของ Google 22 ส.ค. 2026: quotaId GenerateRequestsPerDayPerProjectPerModel-FreeTier
# · quotaValue 20 · model gemini-3.5-flash) ถ้าตัวตรวจคลิปไปกินถังเดียวกับตัวแก้
# คำสั่งที่โดนบล็อก ตรวจคลิป 20 ใบวันเดียวจะทำให้ **แก้คำสั่งไม่ได้ทั้งวัน** ซึ่ง
# สำคัญกว่ามาก (แก้ไม่ได้ = เจนคลิปไม่ออกเลย · ตรวจไม่ได้ = แค่ไม่รู้ผล)
#
# 2.5-flash ฟังเสียงไทยแล้วถอดได้แม่นเท่ากันในการทดสอบ (ถอดประโยคเดียวกันตรงกัน)
# ไล่ใช้ตามลำดับ ถังไหนหมดของวันก็ตกไปตัวถัดไป
#
# **ตั้งใจใช้คนละชุดกับ policy_fix.py** ซึ่งใช้ตัวใหญ่ (3.6-flash / 3.5-flash)
# เพราะงานสองอย่างนี้ไม่ควรแย่งถังกัน และสำคัญไม่เท่ากัน
#
#   ตัวแก้คำสั่ง  แก้ไม่ได้ = **เจนคลิปไม่ออกเลย** ต้องได้ตัวเก่งและต้องไม่โดนแย่ง
#   ตัวตรวจคลิป   ตรวจไม่ได้ = แค่ยังไม่รู้ผล คลิปยังอยู่ครบ รอพรุ่งนี้ได้
#
# เจอจริง 22 ส.ค. 2026 เวลา 20:26 — ตัวตรวจคลิปกินถัง 3.5-flash หมดตอนบ่าย
# พอค่ำมีคลิปโดน Flow บล็อก ตัวแก้คำสั่งยิงไปเจอ 429 ทันที **งานล้มโดยไม่ได้
# ลองแก้สักรอบ** ทั้งที่ระบบมีวิธีแก้อยู่ในมือ
#
# ทดสอบแล้วว่ารุ่น lite ถอดเสียงไทยได้ตรงกับรุ่นใหญ่ (ประโยคเดียวกัน คำเดียวกัน)
MODELS = (
    "gemini-3.1-flash-lite",
    "gemini-3.5-flash-lite",
    "gemini-flash-lite-latest",
    "gemini-2.5-flash",
)
MODEL = MODELS[0]                 # เผื่อโค้ดเก่าที่อ้างชื่อเดี่ยว
ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models"
TIMEOUT = 120

# เสียงอย่างเดียว โมโน 16 kHz 48 kbps — คลิป 10 วิได้ราว 60 KB ส่งแนบไปตรงๆ ได้
# ไม่ต้องอัปโหลดแบบ resumable เหมือน gemini_video.py ที่ส่งทั้งวิดีโอ
AUDIO_RATE = 16000
AUDIO_BITRATE = "48k"

# ดึงภาพนิ่งจากคลิปกี่ใบไปให้ AI อ่านตัวอักษร (ผู้ใช้สั่ง 23 ส.ค. 2026)
#
# **ส่งไปพร้อมเสียงในคำขอเดียวกัน ไม่ยิงแยก** โควตาชั้นฟรีนับเป็น "จำนวนครั้ง"
# ไม่ใช่จำนวนโทเคน ยิงแยกจึงกินโควตาเป็นสองเท่าโดยไม่ได้อะไรเพิ่ม
# วัดจริง: เสียง+4 เฟรม = 4,940 โทเคนต่อครั้ง ยังห่างเพดานมาก
#
# 4 ใบพอเห็นข้อความครบทุกช่วง เพราะคลิป 10 วินาทีมี 4-5 ฉาก ฉากละ ~2 วินาที
FRAME_COUNT = 4
FRAME_EVERY = 2.5           # วินาที — ดึงหนึ่งใบทุกๆ เท่านี้
FRAME_WIDTH = 512           # ย่อก่อนส่ง ประหยัดเน็ตและโทเคน อ่านตัวอักษรยังชัด

# 429 = ยิงถี่เกินโควตาต่อนาที · 500/503 = ฝั่ง Google แน่น — ทั้งสองอย่างรอแล้วหาย
# ค่าเดียวกับ gemini_video.py จะได้ไม่ต้องจำสองชุด
BUSY_CODES = {429, 500, 503}
RETRY_WAITS = (15, 30, 60)   # วิ — รอเท่านี้ก่อนลองใหม่แต่ละครั้ง

LISTEN_ASK = (
    "นี่คือคลิปโฆษณาสั้น ส่งมาให้ทั้ง **เสียง** และ **ภาพนิ่งจากคลิป** หลายเฟรม\n"
    "ดูและฟังแล้วตอบเป็น JSON เท่านั้น ห้ามมีข้อความอื่น:\n"
    '{"has_speech": true/false, "language": "th"/"en"/"other"/"none", '
    '"transcript": "ข้อความที่ได้ยินทั้งหมด", "other_sound": "เสียงอื่นที่ได้ยิน", '
    '"clear": true/false, "has_text": true/false, '
    '"speech_ok": true/false, "speech_problem": "ถ้าพูดไม่รู้เรื่องบอกว่าเพราะอะไร", '
    '"split_screen": true/false, "split_seen": "แบ่งกี่ช่อง ฉากไหน", '
    '"text_seen": "ตัวอักษรที่อ่านได้จากภาพ", "text_readable": true/false, '
    '"text_problem": "ถ้าอ่านไม่ออกบอกว่าเพราะอะไร", '
    '"third_party": true/false, "third_party_seen": "เห็นอะไรบ้าง ฉากไหน"}\n\n'
    "has_speech = มีคน**พูดเป็นคำ**จริงๆ ไหม — ดนตรี เสียงบรรยากาศ เสียงฮัม "
    "หรือเสียงคล้ายพูดที่ฟังไม่ออกว่าเป็นคำ ให้ตอบ false\n"
    "clear = เสียงพูดชัดพอที่คนฟังรู้เรื่องไหม (เรื่องคุณภาพเสียง)\n"
    # ผู้ใช้สั่งเพิ่ม 28 ส.ค. 2569: "เอาคลิปที่พูดไทยไม่รู้เรื่อง"
    #
    # **คนละเรื่องกับ `clear`** — `clear` ถามว่าเสียงชัดไหม (ดัง เบา แตก อู้อี้)
    # ส่วนข้อนี้ถามว่า **สิ่งที่พูดออกมาเป็นภาษาไทยที่มีความหมายไหม**
    # Veo ออกเสียงไทยเพี้ยนบ่อยจนได้เสียงที่ "ชัดมาก" แต่ไม่เป็นคำ ซึ่งด่านเดิม
    # ปล่อยผ่านทั้งคู่ เพราะ clear = true และ has_speech = true
    "speech_ok = สิ่งที่พูดออกมา **เป็นภาษาไทยที่มีความหมายจริง** ไหม\n"
    "  · ออกเสียงเพี้ยนจนไม่เป็นคำไทย · ผสมเสียงมั่วคล้ายไทยแต่แปลไม่ได้ = false\n"
    "  · อ่านคำอังกฤษ/ตัวเลขผิดจนฟังไม่รู้ว่าคืออะไร = false\n"
    "  · วรรณยุกต์ผิดจนกลายเป็นคนละคำ เช่น “เก้าอี้” เป็น “เกาอี” = false\n"
    "  · ประโยคขาดกลางคัน จับใจความไม่ได้ = false\n"
    "  · ฟังแล้วเข้าใจว่าพูดอะไร แม้สำเนียงไม่เป๊ะ = true\n"
    "  · พูดภาษาอื่นที่ไม่ใช่ไทยและฟังรู้เรื่อง = true (ไปดูที่ language แทน)\n"
    "speech_problem = ถ้า false ให้ยกคำที่ผิดมาให้ดูด้วย ไม่ใช่บอกลอยๆ\n"
    "transcript = ถอดเท่าที่ได้ยินจริง ห้ามเดาเติมเอง ไม่มีเสียงพูดให้ใส่ค่าว่าง\n\n"
    # ผู้ใช้สั่งเพิ่ม 28 ส.ค. 2569: "เอาคลิปที่ในคลิปแบ่งหน้าเป็นแบบ storyboard"
    #
    # Veo เข้าใจคำสั่งที่เขียนเป็นฉากๆ ผิดเป็นบางครั้ง แล้ววาด **กระดานสตอรีบอร์ด**
    # ออกมาจริงๆ คือแบ่งจอเป็นช่องๆ ใส่ทุกฉากลงไปพร้อมกัน แทนที่จะเล่นทีละฉาก
    # คลิปแบบนี้ใช้ไม่ได้เลย แต่ด่านเดิมมองไม่เห็นเพราะภาพชัด เสียงครบ ตัวอักษรอ่านออก
    "split_screen = เฟรมถูก**แบ่งเป็นหลายช่องพร้อมกัน**ไหม เหมือนกระดาน"
    "สตอรีบอร์ดหรือตารางภาพ แทนที่จะเป็นภาพเดียวเต็มจอ\n"
    "  · แบ่ง 2 ช่องขึ้นไป มีเส้นคั่นหรือขอบขาวคั่นชัดเจน = true\n"
    "  · มีเลขฉากหรือคำว่า Scene / ฉากที่ กำกับแต่ละช่อง = true\n"
    "  · ภาพซ้อนภาพแบบกรอบเล็กในกรอบใหญ่ทั้งคลิป = true\n"
    "  · ภาพเดียวเต็มจอ ตัดสลับฉากไปตามเวลา = false (แบบนี้ถูกต้อง)\n"
    "  · มีแถบดำบนล่างหรือซ้ายขวาเฉยๆ = false (แค่สัดส่วนภาพ ไม่ใช่การแบ่งช่อง)\n"
    "split_seen = ถ้า true บอกว่าแบ่งกี่ช่องและเห็นในเฟรมไหน\n\n"
    "has_text = ในภาพมีตัวอักษรที่**ตั้งใจใส่มาเป็นข้อความโฆษณา**ไหม "
    "(ไม่นับตัวอักษรบนกล่องสินค้า ป้ายในฉาก หรือหน้าจอในภาพ)\n"
    "text_readable = ตัวอักษรนั้น **อ่านออกเป็นคำจริง สะกดครบ** ไหม\n"
    "  · ตัวอักษรขาดกลางคำ เช่น “สายเก” ที่ควรเป็น “สายเกม” = false\n"
    "  · สระลอย วรรณยุกต์ผิดที่ ตัวอักษรบิดเบี้ยวจนไม่เป็นคำ = false\n"
    "  · อังกฤษสะกดผิด เช่น “brigth” แทน “bright” = false\n"
    "  · อ่านรู้เรื่องครบถ้วน = true\n"
    "text_seen = ถอด**ตามที่เห็นจริง** ห้ามเดาเติมให้เป็นคำที่ถูก "
    "เห็นขาดก็ใส่ตามที่ขาด\n\n"
    "third_party = ในภาพมี**ของที่มีเจ้าของลิขสิทธิ์**โผล่มาไหม โดยเฉพาะบน"
    "หน้าจอของสินค้า (ทีวี จอคอม มือถือ) — ตอบ true ถ้าเห็นอย่างใดอย่างหนึ่ง:\n"
    "  · การถ่ายทอดกีฬา (ฟุตบอล อเมริกันฟุตบอล บาส มวย แข่งรถ)\n"
    "  · ฉากหนัง ซีรีส์ การ์ตูน อนิเมะ มิวสิกวิดีโอ\n"
    "  · ภาพเกมที่ดูออกว่าเป็นเกมอะไร\n"
    "  · โลโก้ยี่ห้ออื่น เช่น Netflix · YouTube · Disney+ · HBO · Apple TV · Prime\n"
    "  · ใบหน้าคนที่ดูเหมือนบุคคลจริงหรือคนมีชื่อเสียง\n"
    "  · ลายน้ำของแพลตฟอร์มอื่น (TikTok · Instagram)\n"
    "**ไม่นับ**ยี่ห้อของตัวสินค้าเอง (เช่นคำว่า TCL บนขอบจอ) และไม่นับ"
    "ภาพนามธรรม ลวดลายสี ดอกไม้ ภูเขา อวกาศ\n"
    "third_party_seen = บอกว่าเห็นอะไรตรงไหน เช่น \"ฉากที่ 4 จอฉายอเมริกันฟุตบอล\" "
    "ไม่มีให้ใส่ค่าว่าง"
)

# ⛔ **ห้ามส่งบทพูดไปพร้อมกับเสียงในคำขอเดียวกันเด็ดขาด** ⛔
#
# เคยทำแล้วพัง: การให้โมเดลเห็น "บทที่ควรได้ยิน" ก่อนตอบว่า "ได้ยินอะไร" คือการ
# เอาเฉลยไปวางไว้ในข้อสอบ โมเดลจะอ่านบทแล้วตอบว่าได้ยินบทนั้น แทนที่จะฟังจริง
#
# พิสูจน์แล้ว 22 ส.ค. 2026 กับคลิปเร้าเตอร์ D-Link (22088601141) ซึ่งมีแต่ดนตรี:
#     ให้บทดู   → has_speech=true  ถอดออกมาเป็นบทเป๊ะ "ตัวนี้เน็ต 5G แรงมาก..."
#     ไม่ให้บทดู → has_speech=false "ดนตรีสนุกสนาน"
# คลิปคุมที่มีเสียงพูดจริงตอบว่ามีทั้งสองแบบ (ถอดต่างกันเล็กน้อยตามธรรมชาติ)
# แปลว่าไม่ใช่ว่าไม่ให้บทแล้วตอบว่าไม่มีเสมอ — บทรั่วเข้าไปในคำตอบจริง
#
# **หลอกในทิศที่แย่ที่สุด** คือบอกว่า "มีเสียงพูด ✅" กับคลิปที่เสียงพัง ซึ่งเป็น
# คลิปที่ด่านนี้มีไว้เพื่อจับโดยเฉพาะ ผู้ใช้จะเอาคลิปเงียบไปโพสต์โดยเห็นเครื่องหมายถูก
#
# จึงแยกเป็นสองคำขอ: ฟังก่อน (ไม่เห็นบท) แล้วค่อยเอา "สิ่งที่ได้ยิน" ไปเทียบกับบท
# ทีหลัง ซึ่งเป็นการเทียบข้อความล้วน ไม่มีเสียง ไม่มีทางรั่ว


# ใช้ **หลังจาก**ถอดเสียงเสร็จแล้วเท่านั้น — เทียบข้อความกับข้อความ ไม่มีไฟล์เสียง
#
# ทำไมไม่เทียบตัวอักษรเอง: วัดจริง 22 ส.ค. 2026 คลิป 57002389888 บทเขียนว่า
# "ห้องใหญ่ ต้องตัวนี้เลย เย็นไวทันใจมาก" แต่ Veo พูดว่า "ใครห้องใหญ่ ลองตัวนี้เลย
# เย็นทั่วห้องมาก" — ใจความเดียวกันเป๊ะแต่เทียบตัวอักษรได้แค่ 19% ถ้าใช้ตัวเลขนั้น
# ตัดสิน คลิปที่ดีจะถูกตีตกเกือบทุกใบ Veo เรียบเรียงคำใหม่เป็นปกติ ไม่ใช่ความผิดพลาด
# ต่อบทพูดด้วยการบวกสตริง **ห้ามใช้ str.format** เพราะข้อความมีปีกกาของ JSON
# ตัวอย่างอยู่ format จะอ่านเป็นช่องเติมคำแล้วโยน KeyError (เจอจริงตอนทดสอบ 22 ส.ค.)
MATCH_ASK = (
    "เทียบข้อความสองชุดนี้แล้วตอบ JSON เท่านั้น:\n"
    '{"matches_script": true/false, "match_note": "สั้นๆ"}\n\n'
    "matches_script = ชุด ก. **มีใจความตรงกับ** ชุด ข. ไหม "
    "(คนละถ้อยคำแต่ความหมายเดียวกัน = true · คนละเรื่อง/คนละสินค้า = false)\n\n"
    "ชุด ก. คือสิ่งที่ได้ยินจริงในคลิป:\n"
)


class ClipCheckError(RuntimeError):
    """ตรวจไม่ได้ — คนละเรื่องกับ 'ตรวจแล้วไม่ผ่าน'"""


# ---------------------------------------------------------------- ชั้น 1: วัดจากไฟล์

def _tool(name: str) -> str:
    found = shutil.which(name)
    if not found:
        raise ClipCheckError(f"ไม่มี {name} ในเครื่อง — ตรวจคลิปไม่ได้")
    return found


def probe(path) -> dict:
    """ขนาดภาพ · ความยาว · มีแทร็กเสียงไหม — อ่านจากหัวไฟล์ ไม่ต้องถอดรหัสทั้งคลิป"""
    path = Path(path)
    if not path.is_file():
        raise ClipCheckError(f"ไม่พบไฟล์ {path.name}")
    out = subprocess.run(
        [_tool("ffprobe"), "-v", "error", "-print_format", "json",
         "-show_streams", "-show_format", str(path)],
        capture_output=True, text=True, timeout=60,
    )
    if out.returncode != 0:
        raise ClipCheckError(f"ffprobe อ่าน {path.name} ไม่ได้: {out.stderr.strip()[:120]}")
    try:
        data = json.loads(out.stdout)
    except ValueError as error:
        raise ClipCheckError(f"อ่านผล ffprobe ไม่ได้: {error}") from error

    streams = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), {})
    audio = next((s for s in streams if s.get("codec_type") == "audio"), {})
    width, height = int(video.get("width") or 0), int(video.get("height") or 0)
    return {
        "width": width,
        "height": height,
        "resolution": f"{width}×{height}" if width and height else "",
        "short_side": min(width, height) if width and height else 0,
        "seconds": round(float(data.get("format", {}).get("duration") or 0), 1),
        "size_mb": round(path.stat().st_size / 1048576, 1),
        "has_audio_track": bool(audio),
        "audio_codec": audio.get("codec_name", ""),
    }


_DB_RE = re.compile(r"(mean|max)_volume:\s*(-?[\d.]+) dB")


def loudness(path) -> dict:
    """ดังแค่ไหน — ต้องถอดรหัสเสียงทั้งคลิป (คลิป 10 วิใช้ราว 0.2 วิ)

    ใช้แยก "ไฟล์เสียงเงียบสนิท" ออกจาก "มีเสียงแต่ไม่ใช่คนพูด" ซึ่งเป็นคนละอาการ
    และแก้คนละทาง — เงียบสนิทคือเจนเสียงล้มทั้งแทร็ก ส่วนมีดนตรีคือเจนเสียงพูดล้ม
    """
    out = subprocess.run(
        [_tool("ffmpeg"), "-hide_banner", "-nostats", "-i", str(path),
         "-map", "a:0", "-af", "volumedetect", "-f", "null", "-"],
        capture_output=True, text=True, timeout=180,
    )
    found = dict(_DB_RE.findall(out.stderr))
    if "mean" not in found:
        return {"mean_db": None, "max_db": None}
    return {"mean_db": float(found["mean"]), "max_db": float(found.get("max", found["mean"]))}


# ---------------------------------------------------------------- ชั้น 2: ให้ Gemini ฟัง

def extract_audio(path, out_path) -> Path:
    """ดึงเฉพาะเสียงออกมาเป็นไฟล์เล็ก — ส่งทั้งวิดีโอไปเปลืองเน็ตและช้ากว่ามาก"""
    out_path = Path(out_path)
    run = subprocess.run(
        [_tool("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y", "-i", str(path),
         "-vn", "-ac", "1", "-ar", str(AUDIO_RATE), "-b:a", AUDIO_BITRATE, str(out_path)],
        capture_output=True, text=True, timeout=180,
    )
    if run.returncode != 0 or not out_path.is_file():
        raise ClipCheckError(f"ดึงเสียงออกจากคลิปไม่ได้: {run.stderr.strip()[:120]}")
    return out_path


# คำตอบที่ "หน้าตาเหมือนคำตัดสิน แต่จริงๆ คือ Gemini บอกว่าทำไม่ได้"
#
# เจอจริง 22 ส.ค. 2026: คลิปโซฟาเบด 27239816564 Gemini ตอบ has_speech=false พร้อม
# other_sound = "cannot process audio input" ซึ่งถูกบันทึกเป็น **"ไม่มีเสียงพูด"**
# ทั้งที่พอถามใหม่สองรอบได้ has_speech=true พร้อมบทถอดครบถ้วนทั้งสองรอบ
#
# ต้องดักเพราะคำปฏิเสธที่ถูกนับเป็นคำตัดสินคือรายงานเท็จ — ผู้ใช้จะไปเจนคลิปใหม่
# ทั้งที่ของเดิมไม่มีปัญหา เสียเครดิตฟรี ตรงข้ามกับที่ด่านนี้มีไว้เพื่อป้องกัน
_CANT_RE = re.compile(
    r"cannot\s+process|can'?t\s+process|unable\s+to|not\s+able\s+to|"
    r"no\s+audio\s+(?:was\s+)?(?:provided|found)|ไม่สามารถ|ประมวลผลไม่ได้",
    re.I,
)


def _looks_unprocessed(data: dict) -> str:
    """คำตอบนี้เป็นคำปฏิเสธที่ปลอมเป็นคำตัดสินไหม — คืนข้อความที่ทำให้สงสัย"""
    for key in ("other_sound", "transcript", "match_note"):
        text = str(data.get(key) or "")
        if _CANT_RE.search(text):
            return text[:80]
    return ""


def grab_frames(path, out_dir) -> list:
    """ดึงภาพนิ่งจากคลิปไปให้ AI อ่านตัวอักษร

    ดึงกระจายทั้งคลิป ไม่ใช่กระจุกที่ต้นคลิป เพราะข้อความเปลี่ยนทุกฉาก
    ดึงไม่ได้ก็ไม่ใช่เหตุให้ทั้งการตรวจล้ม — คืนรายการว่าง แล้วตรวจแต่เสียงต่อไป
    """
    out_dir = Path(out_dir)
    run = subprocess.run(
        [_tool("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y", "-i", str(path),
         "-vf", f"fps=1/{FRAME_EVERY},scale={FRAME_WIDTH}:-1", "-q:v", "5",
         str(out_dir / "f%02d.jpg")],
        capture_output=True, text=True, timeout=180,
    )
    if run.returncode != 0:
        return []
    return sorted(out_dir.glob("*.jpg"))[:FRAME_COUNT]


def _parse(raw: str) -> dict:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-z]*\s*|\s*```$", "", text, flags=re.S)
    try:
        data = json.loads(text)
    except ValueError as error:
        raise ClipCheckError(f"อ่านคำตอบ Gemini ไม่ได้: {text[:80]}") from error
    if not isinstance(data, dict) or "has_speech" not in data:
        raise ClipCheckError(f"คำตอบ Gemini ไม่มี has_speech: {text[:80]}")
    excuse = _looks_unprocessed(data)
    if excuse:
        # โยนออกไปให้ลูปยิงใหม่ — ดีกว่าเอาคำปฏิเสธไปบันทึกว่า "ไม่มีเสียงพูด"
        raise ClipCheckError(f"Gemini บอกว่าฟังไฟล์ไม่ได้: {excuse}")
    return data


_RETRY_DELAY_RE = re.compile(r'"retryDelay"\s*:\s*"(\d+)s"')


def _busy_hint(response) -> tuple[int, bool, str]:
    """อ่านจากคำตอบ 429/503 ว่า **โควตาหมดวัน** หรือแค่ยิงถี่ไป

    คืน (วินาทีที่ Google บอกให้รอ, หมดโควตารายวันไหม, คำอธิบายไทย)

    **ต้องแยกให้ออก** เพราะแก้คนละทางสิ้นเชิง
      · ยิงถี่ไป (ต่อนาที) → รอสักครู่แล้วลองใหม่ ได้ผล
      · หมดโควตารายวัน    → รอเท่าไรก็ไม่ได้ ต้องเปลี่ยนโมเดลหรือรอพรุ่งนี้
    ถ้าไม่แยก จะยืนรอ 15+30+60 วินาทีต่อคลิปแล้วแพ้อยู่ดี — เสียเวลาเปล่า
    (เจอจริง 22 ส.ค. 2026: ตรวจ 15 คลิปค้างอยู่ 4 ใบ เพราะวนรอโควตาที่หมดไปแล้ว)
    """
    seconds, daily, why = 0, False, ""
    try:
        body = response.text or ""
    except Exception:                                        # noqa: BLE001
        return 0, False, ""
    found = _RETRY_DELAY_RE.search(body)
    if found:
        seconds = min(int(found.group(1)), 120)
    limit = ""
    try:
        error = response.json().get("error", {})
        why = str(error.get("message") or "")[:200]
        for detail in error.get("details") or []:
            if "QuotaFailure" not in str(detail.get("@type", "")):
                continue
            for hit in detail.get("violations") or []:
                if "PerDay" in str(hit.get("quotaId") or ""):
                    daily = True
                    limit = str(hit.get("quotaValue") or "")
    except Exception:                                        # noqa: BLE001
        why = body[:200]
    if daily:
        why = f"โควตา Gemini วันนี้หมดแล้ว (ชั้นฟรีให้ {limit or '?'} ครั้ง/วัน ต่อโมเดล)"
    return seconds, daily, why


def listen(path, api_key: str, log=print) -> dict:
    """ส่งเสียงให้ Gemini ฟัง — คืน has_speech · language · transcript

    **ฟังอย่างเดียว ไม่เห็นบทพูด** ห้ามเพิ่มพารามิเตอร์ script กลับเข้ามาที่นี่
    เหตุผลอยู่ที่หัวข้อ MATCH_ASK — เคยทำแล้วโมเดลอ่านบทแทนการฟัง คลิปเงียบเลย
    ได้เครื่องหมายถูก ถ้าอยากรู้ว่าตรงบทไหมให้เรียก `compare()` ต่อทีหลัง

    ยิงซ้ำได้เพราะ Gemini ตอบไม่คงที่ทุกครั้ง และการยิงซ้ำถูกกว่าปล่อยให้คลิปที่ดี
    ถูกตีตกเพราะคำตอบเสียครั้งเดียว

    **โดนตัดเพราะโควตารายวัน ต้องเลิกลองทันที** — วัดจริง 22 ส.ค. 2026: ชั้นฟรีให้
    20 ครั้ง/วัน/โมเดล ตอนตรวจ 15 คลิปรวดเดียวจึงหมดตั้งแต่ใบที่ 4 การวนรอ 15/30/60
    วินาทีต่อใบไม่ได้ช่วยอะไรเลย เสียเวลาไป 105 วินาทีต่อใบแล้วแพ้เหมือนเดิม
    หมดถังของโมเดลหลักแล้วจึงสลับไปโมเดลสำรอง ซึ่งนับโควตาคนละถัง
    """
    if not api_key:
        raise ClipCheckError("ไม่มีคีย์ Gemini — ฟังเสียงพูดไม่ได้")

    ask = LISTEN_ASK
    with tempfile.TemporaryDirectory() as tmp:
        audio = extract_audio(path, Path(tmp) / "a.mp3")
        blob = base64.b64encode(audio.read_bytes()).decode()
        # ภาพนิ่งไปด้วยในคำขอเดียวกัน — ดูเหตุผลที่ FRAME_COUNT
        shots = [base64.b64encode(p.read_bytes()).decode()
                 for p in grab_frames(path, tmp)]

    queue = list(MODELS)
    model = queue.pop(0)
    skip_wait = False
    last, told_wait = "", 0
    # เผื่อรอบไว้ให้ครบทั้ง "ลองใหม่เพราะคำตอบเสีย" และ "ไล่เปลี่ยนโมเดลจนหมดชุด"
    # ถ้านับแค่ RETRY_WAITS การไล่เปลี่ยนโมเดลจะกินรอบจนไม่เหลือให้ลองใหม่จริงๆ
    for attempt in range(len(RETRY_WAITS) + len(MODELS)):
        if attempt and not skip_wait:
            # Google บอกมาเองว่าให้รอกี่วินาที ก็เชื่อเขา — เดาเองน้อยไปก็โดนซ้ำ
            # เดามากไปก็ช้าเปล่า ค่าของเราเป็นแค่ทางถอยเมื่อเขาไม่ได้บอก
            wait = max(told_wait, RETRY_WAITS[min(attempt, len(RETRY_WAITS)) - 1])
            log(f"  รอ {wait} วิแล้วฟังใหม่ (ครั้งที่ {attempt}/{len(RETRY_WAITS)}) — {last}")
            time.sleep(wait)
        # สลับโมเดลแล้วยิงต่อได้เลย ไม่ต้องรอ — คนละถังโควตากัน การรอไม่ช่วยอะไร
        skip_wait = False
        try:
            response = httpx.post(
                f"{ENDPOINT}/{model}:generateContent",
                params={"key": api_key},
                json={
                    "contents": [{"parts": [
                        {"text": ask},
                        {"inline_data": {"mime_type": "audio/mp3", "data": blob}},
                    ] + [
                        {"inline_data": {"mime_type": "image/jpeg", "data": shot}}
                        for shot in shots
                    ]}],
                    "generationConfig": {"responseMimeType": "application/json"},
                },
                timeout=TIMEOUT,
            )
            gemini_quota.record(model, ok=response.status_code == 200,
                                response=response)
        except httpx.HTTPError as error:
            last = f"ต่อ Gemini ไม่ได้: {error}"
            continue
        if response.status_code in BUSY_CODES:
            # คนใช้เยอะ/ยิงถี่เกิน — ไม่ใช่ของเราผิด รอแล้วลองใหม่ได้ผล
            #
            # **ต้องเก็บเหตุผลจริงของ Google ไว้ด้วย** ไม่ใช่แค่เลข 429 เพราะตัวเลข
            # เปล่าๆ ไม่บอกว่าชนโควตาต่อนาทีหรือต่อวัน ซึ่งแก้คนละทางสิ้นเชิง
            # (ต่อนาที = เว้นจังหวะแล้วหาย · ต่อวัน = ต้องรอพรุ่งนี้หรือเปลี่ยนคีย์)
            told_wait, daily, why = _busy_hint(response)
            last = why or f"Gemini ตอบ {response.status_code}"
            if daily:
                # ถังของโมเดลนี้หมดวันแล้ว — ไล่ไปตัวถัดไปที่นับคนละถัง
                if queue:
                    model, told_wait = queue.pop(0), 0
                    log(f"  {model} ← สลับโมเดล ({why})")
                    skip_wait = True
                    continue
                # หมดทุกตัวแล้ว รอต่อไม่มีประโยชน์ เลิกทันทีแล้วบอกตรงๆ
                raise ClipCheckError(f"{why} — ลองใหม่พรุ่งนี้")
            continue
        if response.status_code != 200:
            # ผิดจริง (คีย์ผิด · โมเดลไม่มี · ไฟล์ใหญ่เกิน) รอไปก็ไม่หาย เลิกเลย
            raise ClipCheckError(f"Gemini ตอบ {response.status_code}: {response.text[:120]}")
        try:
            raw = response.json()["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, ValueError):
            last = "คำตอบ Gemini ไม่มีเนื้อหา"
            continue
        try:
            return _parse(raw)
        except ClipCheckError as error:
            last = str(error)
    raise ClipCheckError(last or "ฟังเสียงไม่สำเร็จ")


def compare(transcript: str, script, api_key: str, log=print) -> dict:
    """สิ่งที่ได้ยินตรงใจความกับบทที่เขียนไว้ไหม — คืน {matches_script, match_note}

    **เทียบข้อความกับข้อความ ไม่ส่งไฟล์เสียงไปด้วย** เพราะถ้าส่งเสียงไปพร้อมบท
    โมเดลจะกลับไปเดาว่าได้ยินบทนั้นอีก (ดูเหตุผลเต็มที่หัวข้อ MATCH_ASK)

    เรียกเฉพาะตอนฟังแล้วได้ยินเสียงพูดจริง — ไม่มีเสียงพูดก็ไม่มีอะไรให้เทียบ
    และไม่ต้องเปลืองโควตา
    """
    said = (transcript or "").strip()
    if isinstance(script, (list, tuple)):
        script = "\n".join(str(item) for item in script)
    want = str(script or "").strip()
    if not said or not want:
        return {}
    if not api_key:
        raise ClipCheckError("ไม่มีคีย์ Gemini — เทียบกับบทไม่ได้")

    ask = (MATCH_ASK + said[:1200]
           + "\n\nชุด ข. คือบทที่ตั้งใจให้พูด:\n" + want[:1500])

    queue = list(MODELS)
    model = queue.pop(0)
    last = ""
    for _ in range(len(MODELS)):
        try:
            response = httpx.post(
                f"{ENDPOINT}/{model}:generateContent",
                params={"key": api_key},
                json={
                    "contents": [{"parts": [{"text": ask}]}],
                    "generationConfig": {"responseMimeType": "application/json"},
                },
                timeout=TIMEOUT,
            )
            gemini_quota.record(model, ok=response.status_code == 200,
                                response=response)
        except httpx.HTTPError as error:
            last = f"ต่อ Gemini ไม่ได้: {error}"
        else:
            if response.status_code == 200:
                try:
                    raw = response.json()["candidates"][0]["content"]["parts"][0]["text"]
                    data = json.loads(re.sub(r"^```[a-z]*\s*|\s*```$", "", raw.strip(), flags=re.S))
                    if isinstance(data, dict) and "matches_script" in data:
                        return data
                    last = "คำตอบไม่มี matches_script"
                except (KeyError, IndexError, ValueError) as error:
                    last = f"อ่านคำตอบไม่ได้: {error}"
            else:
                _, _, why = _busy_hint(response)
                last = why or f"Gemini ตอบ {response.status_code}"
        if not queue:
            break
        model = queue.pop(0)
        log(f"  {model} ← สลับโมเดลตอนเทียบบท ({last})")
    raise ClipCheckError(last or "เทียบกับบทไม่สำเร็จ")


# ---------------------------------------------------------------- รวมผล

def check(path, api_key: str = "", script=None, log=print) -> dict:
    """ตรวจคลิปหนึ่งไฟล์ครบทั้งสองชั้น — คืนผลเป็น dict เก็บลง run.json ได้ตรงๆ

    เก็บ `problems` เป็นรายการข้อความไทยพร้อมแสดง เพื่อให้ฝั่งแชทไม่ต้องมาตีความ
    ตัวเลขเองแล้วตีความไม่ตรงกันระหว่าง /clips กับการ์ดอนุมัติ
    """
    path = Path(path)
    result: dict = {"file": path.name}
    result.update(probe(path))
    result.update(loudness(path))

    problems: list[str] = []

    # ---- ข้อ 1 ความชัด ----
    result["hd"] = result["short_side"] >= MIN_SHORT_SIDE
    if not result["short_side"]:
        problems.append("อ่านขนาดภาพไม่ได้")
    elif not result["hd"]:
        problems.append(f"ยังไม่ 1080p (ได้ {result['resolution']})")

    # ---- ข้อ 2 เสียง: มีไหม ดังไหม ----
    max_db = result.get("max_db")
    result["silent"] = max_db is not None and max_db < SILENT_MAX_DB
    if not result["has_audio_track"]:
        problems.append("ไม่มีแทร็กเสียงเลย")
    elif result["silent"]:
        problems.append(f"เสียงเงียบสนิท (ดังสุด {max_db} dB)")
    elif result.get("mean_db") is not None and result["mean_db"] < QUIET_MEAN_DB:
        problems.append(f"เสียงเบาผิดปกติ (เฉลี่ย {result['mean_db']} dB)")

    # ---- ข้อ 2 ต่อ: เป็นเสียงพูดจริงไหม ----
    result["has_speech"] = None
    result["transcript"] = ""
    result["language"] = ""
    result["other_sound"] = ""
    result["speech_note"] = ""
    result["matches_script"] = None
    result["match_note"] = ""
    result["has_text"] = None
    result["text_seen"] = ""
    result["text_readable"] = None
    result["text_problem"] = ""
    # None = ยังไม่ได้ดู · False = ดูแล้วไม่เจอ — **ห้ามให้สองอย่างนี้เท่ากัน**
    # ไม่งั้นวันที่ตรวจไม่ได้ คลิปที่มีโลโก้จะขึ้นเครื่องหมายถูกเหมือนคลิปที่สะอาด
    result["third_party"] = None
    result["third_party_seen"] = ""
    # สองข้อที่ผู้ใช้สั่งเพิ่ม 28 ส.ค. 2569 — ตั้งต้นเป็น None ("ยังไม่ได้ดู")
    # ด้วยเหตุผลเดียวกับข้างบน: ยังไม่ได้ดู กับ ดูแล้วไม่เจอ ต้องแยกจากกัน
    result["speech_ok"] = None
    result["speech_problem"] = ""
    result["split_screen"] = None
    result["split_seen"] = ""

    if not result["has_audio_track"]:
        result["speech_note"] = "ไม่มีแทร็กเสียงจึงไม่ต้องฟัง"
        result["has_speech"] = False
    elif result["silent"]:
        result["speech_note"] = "เสียงเงียบสนิทจึงไม่ต้องฟัง"
        result["has_speech"] = False
    else:
        try:
            heard = listen(path, api_key, log=log)
            # **คำตัดสิน "ไม่มีเสียงพูด" ต้องยืนยันสองรอบ** ก่อนเชื่อ
            #
            # ผิดทางนี้แพงกว่าอีกทางมาก: บอกว่าไม่มีเสียงทั้งที่มี → ผู้ใช้ไปเจน
            # คลิปใหม่ = จ่ายเครดิตฟรี ส่วนบอกว่ามีทั้งที่ไม่มี → ผู้ใช้เปิดฟังตอน
            # โพสต์แล้วรู้เอง จึงยอมยิงเพิ่มอีกครั้งเฉพาะตอนคำตอบเป็นลบ (นานๆ ที)
            #
            # เจอจริง 22 ส.ค. 2026: คลิปโซฟาเบดถูกตีว่า "ไม่มีเสียงพูด" รอบเดียว
            # แต่ถามใหม่สองรอบได้บทถอดไทยครบทั้งสองรอบ
            if not heard.get("has_speech"):
                log("  ได้คำตอบว่าไม่มีเสียงพูด — ขอฟังซ้ำอีกรอบก่อนสรุป")
                second = listen(path, api_key, log=log)
                if second.get("has_speech"):
                    log("  รอบสองได้ยินเสียงพูด — ใช้ผลรอบสอง")
                    heard = second
        except ClipCheckError as error:
            result["speech_note"] = str(error)
            problems.append(f"ตรวจเสียงพูดไม่ได้ — {error}")
        else:
            result["has_speech"] = bool(heard.get("has_speech"))
            result["language"] = str(heard.get("language") or "")
            result["transcript"] = str(heard.get("transcript") or "").strip()
            result["other_sound"] = str(heard.get("other_sound") or "")
            result["speech_clear"] = bool(heard.get("clear", True))
            # ตัวอักษรบนคลิป (ผู้ใช้สั่ง 23 ส.ค. 2026)
            #
            # Veo วาดตัวอักษรไทยพลาดบ่อย — ขาดกลางคำ สระลอย วรรณยุกต์ผิดที่
            # เจอจริงในคลิปทีวี 75 นิ้ว: บนจอเขียน "สายเก" ทั้งที่ควรเป็น "สายเกม"
            # ดูจากไฟล์อย่างเดียวจับไม่ได้เลย ต้องให้คนหรือ AI มองภาพจริง
            if "has_text" in heard:
                result["has_text"] = bool(heard.get("has_text"))
                result["text_seen"] = str(heard.get("text_seen") or "").strip()
                result["text_readable"] = (
                    bool(heard.get("text_readable")) if result["has_text"] else None)
                result["text_problem"] = str(heard.get("text_problem") or "")[:150]
                if result["has_text"] and not result["text_readable"]:
                    problems.append(
                        "ตัวอักษรบนคลิปอ่านไม่ออก"
                        + (f" — {result['text_problem']}" if result["text_problem"] else "")
                    )
                # ---- ของมีลิขสิทธิ์บนหน้าจอสินค้า (26 ส.ค. 2026) ----------
                #
                # ข้อนี้แพงกว่าทุกข้อในไฟล์นี้ — ข้ออื่นล้มแล้วแค่คลิปไม่สวย
                # ข้อนี้ล้มแล้ว **คลิปถูกลบและสะสมคะแนนจนแบนถาวร**
                # (ทีวี 85 นิ้ว 24842141705 โดนมาแล้ว — ดู SHOPEE-VIDEO-RULES.md)
                result["third_party"] = bool(heard.get("third_party"))
                result["third_party_seen"] = str(
                    heard.get("third_party_seen") or "").strip()[:200]
                if result["third_party"]:
                    problems.append(
                        "⚠️ มีของที่มีลิขสิทธิ์อยู่บนจอ — โพสต์แล้วเสี่ยงโดนลบ"
                        + (f": {result['third_party_seen']}"
                           if result["third_party_seen"] else "")
                    )
            # ---- จอแบ่งช่องแบบสตอรีบอร์ด (28 ส.ค. 2569) ----------------
            # ดูจากภาพนิ่ง จึงตอบได้แม้ไม่มีเสียงพูด — วางไว้นอกบล็อกเสียงพูด
            if "split_screen" in heard:
                result["split_screen"] = bool(heard.get("split_screen"))
                result["split_seen"] = str(heard.get("split_seen") or "").strip()[:150]
                if result["split_screen"]:
                    problems.append(
                        "จอถูกแบ่งเป็นช่องแบบกระดานสตอรีบอร์ด ไม่ใช่คลิปจริง"
                        + (f" — {result['split_seen']}" if result["split_seen"] else "")
                    )
            if not result["has_speech"]:
                other = result["other_sound"] or "ไม่มีเสียงพูด"
                problems.append(f"ไม่มีเสียงพูด (ได้ยินแต่{other})")
            elif not result["speech_clear"]:
                problems.append("เสียงพูดฟังไม่ค่อยชัด")
            # ---- พูดไทยรู้เรื่องไหม (28 ส.ค. 2569) ---------------------
            # ถามเฉพาะตอนมีเสียงพูดจริง ไม่งั้นจะได้คำตอบมั่วจากความเงียบ
            if result["has_speech"] and "speech_ok" in heard:
                result["speech_ok"] = bool(heard.get("speech_ok"))
                result["speech_problem"] = str(heard.get("speech_problem") or "")[:150]
                if not result["speech_ok"]:
                    problems.append(
                        "พูดไทยไม่รู้เรื่อง"
                        + (f" — {result['speech_problem']}" if result["speech_problem"] else "")
                    )
            # เทียบกับบทเป็น **คำขอที่สอง** และเฉพาะตอนได้ยินเสียงพูดจริงเท่านั้น
            # เทียบไม่ได้ไม่ทำให้ผลตรวจหลักเสีย — ของหลักคือ 1080p กับมีเสียงพูดไหม
            if script and result["has_speech"]:
                try:
                    same = compare(result["transcript"], script, api_key, log=log)
                except ClipCheckError as error:
                    result["match_note"] = f"เทียบกับบทไม่ได้: {error}"
                else:
                    if "matches_script" in same:
                        result["matches_script"] = bool(same.get("matches_script"))
                        result["match_note"] = str(same.get("match_note") or "")[:120]
                        if not result["matches_script"]:
                            problems.append(
                                "พูดไม่ตรงกับบท" +
                                (f" — {result['match_note']}" if result["match_note"] else "")
                            )

    result["problems"] = problems
    # ผ่าน = ชัดถึง 1080p **และ** ยืนยันแล้วว่ามีเสียงพูด
    # ตรวจไม่ได้ (has_speech = None) ไม่นับว่าผ่าน — ดูเหตุผลที่หัวไฟล์
    # ผ่าน = ชัดถึง 1080p **และ** มีเสียงพูด **และ** ตัวอักษรบนคลิปอ่านออก
    #
    # ตัวอักษรอ่านไม่ออกก็โพสต์ไม่ได้เหมือนกัน — คนดูเห็นคำที่สะกดผิดเต็มจอ
    # คลิปที่ไม่มีตัวอักษรเลยไม่ถือว่าตก (text_readable = None) เพราะไม่มีอะไรให้อ่าน
    # ผู้ใช้สั่ง 28 ส.ค. 2569 ให้ตกทั้ง 4 ข้อนี้ — ก่อนหน้านั้นตกแค่ 3 ข้อแรก
    #
    #   1. ไม่มีเสียง                  has_speech
    #   2. พูดไทยไม่รู้เรื่อง            speech_ok      ← เพิ่มใหม่
    #   3. ตัวอักษรอ่านไม่ออก           text_readable
    #   4. จอแบ่งช่องแบบสตอรีบอร์ด      split_screen   ← เพิ่มใหม่
    #
    # เขียนเป็น `is not False` / `is not True` ทุกตัวโดยตั้งใจ **ห้ามเปลี่ยนเป็น
    # ค่าความจริงธรรมดา** เพราะค่า None แปลว่า "ยังไม่ได้ตรวจข้อนี้" ซึ่งต้องไม่ทำให้
    # คลิปตก ไม่งั้นวันที่ Gemini ตอบไม่ครบทุกช่อง คลิปดีจะตกยกคิว
    # (ส่วน "ตรวจเสียงพูดไม่ได้เลย" ยังตกอยู่ เพราะ has_speech เป็น None = ไม่ผ่าน
    #  ข้อนั้นตั้งใจให้เข้มกว่า ดูเหตุผลที่หัวไฟล์)
    result["ok"] = bool(
        result["hd"]
        and result["has_speech"]
        and result["speech_ok"] is not False
        and result["text_readable"] is not False
        and result["split_screen"] is not True
    )
    return result


# ---------------------------------------------------------------- ข้อความสำหรับแชท

def chips(result: dict) -> list[dict]:
    """ผลตรวจแยกเป็นป้ายๆ พร้อมสถานะ — ใช้ทั้งในแชทและบนหน้าเว็บ

    **เขียนที่นี่ที่เดียว** เพราะสองทางนั้นต้องบอกผลตรงกันเสมอ ถ้าแยกกันเขียน
    วันหลังแก้ข้างเดียวจะกลายเป็นแชทบอกว่าผ่าน หน้าเว็บบอกว่าไม่ผ่าน แล้วไม่มี
    ทางรู้ว่าอันไหนจริง — `badge()` ข้างล่างจึงประกอบจากตัวนี้ ไม่ได้เขียนซ้ำ

    `state` มีห้าค่า และ **"ตรวจไม่ได้" ต้องแยกจาก "ไม่ผ่าน" เสมอ** ไม่งั้นวันที่
    คีย์ Gemini หมด คลิปดีๆ ทุกใบจะขึ้นกากบาทเหมือนคลิปเสียจริง แล้วโดนสั่งเจนใหม่
    ทั้งคิวโดยเปล่าประโยชน์

        ok       ผ่าน
        fail     ไม่ผ่าน — เอาไปโพสต์ไม่ได้
        warn     ยังไม่ถึงเกณฑ์ แต่ไม่ถึงกับใช้ไม่ได้
        unknown  ยังตรวจไม่ได้ (ไม่ใช่ผ่าน และไม่ใช่ตก)
        none     ไม่มีอะไรให้ตรวจ

    `detail` คือส่วนขยายที่ยาวได้ แยกจาก `text` เพื่อให้หน้าเว็บเอาไปทำคำอธิบาย
    ใต้ป้ายได้ ส่วนแชทเอามาต่อท้ายด้วย " — " ให้ได้ข้อความเดิมเป๊ะ
    """
    if not result:
        return []

    out: list[dict] = []
    size = result.get("resolution") or "ไม่ทราบขนาด"
    out.append({
        "key": "hd",
        "state": "ok" if result.get("hd") else "warn",
        "text": ("✅ ความชัด " + size) if result.get("hd")
                else ("⚠️ ความชัด " + size + " — ยังไม่ถึง 1080p"),
        "detail": "",
    })

    speech = result.get("has_speech")
    if speech is True:
        lang = {"th": "ไทย", "en": "อังกฤษ"}.get(
            result.get("language") or "", result.get("language") or "")
        voice_text = "✅ มีเสียงพูด" + (f" {lang}" if lang else "")
        state = "ok"
        if result.get("matches_script") is True:
            voice_text += " · ตรงกับบท"
        elif result.get("matches_script") is False:
            voice_text += " · ⚠️ พูดไม่ตรงบท"
            # สีต้องตรงกับข้อความ — ป้ายเขียวที่ข้างในเขียนว่า "⚠️ พูดไม่ตรงบท"
            # อ่านผ่านๆ แล้วนึกว่าผ่าน ซึ่งคือสิ่งที่ป้ายสีมีไว้กันตั้งแต่แรก
            state = "warn"
        out.append({"key": "speech", "state": state, "text": voice_text, "detail": ""})
        # ป้ายแยกสำหรับ "พูดไทยรู้เรื่องไหม" (28 ส.ค. 2569)
        #
        # **ต้องเป็นคนละป้ายกับ "มีเสียงพูด"** เพราะสองข้อนี้ตกคนละสาเหตุและ
        # แก้คนละทาง — ไม่มีเสียง = Veo เจนเสียงล้ม ต้องเจนใหม่ · พูดไม่รู้เรื่อง =
        # บทพูดสะกดแบบที่ Veo อ่านไม่ถูก ต้องไปแก้บทก่อน (ดู thai_speech.py)
        sense = result.get("speech_ok")
        if sense is True:
            out.append({"key": "sense", "state": "ok",
                        "text": "✅ พูดไทยรู้เรื่อง", "detail": ""})
        elif sense is False:
            out.append({"key": "sense", "state": "fail",
                        "text": "❌ พูดไทยไม่รู้เรื่อง",
                        "detail": str(result.get("speech_problem") or "")[:90]})
        else:
            out.append({"key": "sense", "state": "unknown",
                        "text": "❓ ยังไม่ได้ตรวจว่าพูดรู้เรื่องไหม", "detail": ""})
    elif speech is False:
        heard = result.get("other_sound") or ""
        out.append({
            "key": "speech", "state": "fail", "detail": "",
            "text": "❌ ไม่มีเสียงพูด" + (f" (ได้ยินแต่{heard})" if heard else ""),
        })
    else:
        out.append({
            "key": "speech", "state": "unknown", "text": "❓ ตรวจเสียงพูดไม่ได้",
            "detail": str(result.get("speech_note") or "")[:60],
        })

    readable = result.get("text_readable")
    if readable is True:
        seen = (result.get("text_seen") or "").strip()
        out.append({"key": "text", "state": "ok", "text": "✅ ตัวอักษรบนคลิปอ่านออก",
                    "detail": f"“{seen[:60]}”" if seen else ""})
    elif readable is False:
        out.append({"key": "text", "state": "fail", "text": "❌ ตัวอักษรบนคลิปอ่านไม่ออก",
                    "detail": str(result.get("text_problem") or "")[:80]})
    elif result.get("has_text") is False:
        out.append({"key": "text", "state": "none", "text": "• ไม่มีตัวอักษรบนคลิป",
                    "detail": ""})
    else:
        # **เดิมบรรทัดนี้หายไปเฉยๆ** ตอนที่ตรวจตัวอักษรไม่สำเร็จ (หรือผลเก่าที่ตรวจ
        # ไว้ก่อนจะมีการตรวจตัวอักษร) ซึ่งอ่านแล้วแยกไม่ออกจาก "ไม่มีตัวอักษร"
        # การเงียบแบบนั้นคือปล่อยให้เข้าใจว่าผ่าน ทั้งที่ยังไม่มีใครดูสักครั้ง
        out.append({"key": "text", "state": "unknown",
                    "text": "❓ ยังไม่ได้ตรวจตัวอักษรบนคลิป", "detail": ""})

    # ---- ของมีลิขสิทธิ์บนหน้าจอสินค้า ----------------------------------
    #
    # ป้ายนี้ต้องมีทั้งสามสถานะ ไม่ใช่แค่ "เจอ/ไม่เจอ" — **"ยังไม่ได้ตรวจ"
    # ต้องแยกจาก "ตรวจแล้วสะอาด"** เพราะวันที่ยิง Gemini ไม่ติด (503 หรือโควตาหมด
    # ซึ่งเกิดจริงบ่อย) ถ้าสองอย่างนี้หน้าตาเหมือนกัน คลิปที่มีโลโก้จะได้เครื่องหมาย
    # ถูกเหมือนคลิปที่สะอาด แล้วผู้ใช้จะโพสต์ทั้งที่ไม่มีใครดูสักครั้ง
    third = result.get("third_party")
    if third is True:
        out.append({"key": "ip", "state": "fail",
                    "text": "❌ มีของมีลิขสิทธิ์อยู่บนจอ — เสี่ยงโดนลบ",
                    "detail": str(result.get("third_party_seen") or "")[:90]})
    elif third is False:
        out.append({"key": "ip", "state": "ok",
                    "text": "✅ ไม่มีของมีลิขสิทธิ์บนจอ", "detail": ""})
    else:
        out.append({"key": "ip", "state": "unknown",
                    "text": "❓ ยังไม่ได้ตรวจของมีลิขสิทธิ์บนจอ", "detail": ""})

    # ---- จอแบ่งช่องแบบกระดานสตอรีบอร์ด (28 ส.ค. 2569) ------------------
    split = result.get("split_screen")
    if split is True:
        out.append({"key": "split", "state": "fail",
                    "text": "❌ จอถูกแบ่งเป็นช่องแบบสตอรีบอร์ด",
                    "detail": str(result.get("split_seen") or "")[:90]})
    elif split is False:
        out.append({"key": "split", "state": "ok",
                    "text": "✅ ภาพเดียวเต็มจอ ไม่ได้แบ่งช่อง", "detail": ""})
    else:
        out.append({"key": "split", "state": "unknown",
                    "text": "❓ ยังไม่ได้ตรวจว่าจอแบ่งช่องไหม", "detail": ""})
    return out


def badge(result: dict) -> str:
    """สรุปผลสำหรับแนบไปกับคลิปในแชท — ประกอบจาก `chips()` ตัวเดียวกับหน้าเว็บ"""
    if not result:
        return "🔍 ยังไม่ได้ตรวจคลิปนี้"
    return "\n".join(
        chip["text"] + (f" — {chip['detail']}" if chip["detail"] else "")
        for chip in chips(result)
    )
