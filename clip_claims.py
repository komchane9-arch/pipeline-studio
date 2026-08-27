"""ตรวจว่าบทพูดในคลิป **อ้างเกินหน้าสินค้าจริง** หรือเปล่า (ผู้ใช้สั่ง 26 ส.ค. 2026)

**ที่มา** ตอนไล่ตรวจคลิปทั้ง 27 ใบเมื่อ 26 ส.ค. พบว่าตัวเลขสรรพคุณทุกตัวมาจาก
หน้าสินค้าจริงหมด **ยกเว้นหนึ่งจุด** — คลิป TCL Monitor 27 นิ้ว (53662354223)
ฉาก 5 พูดว่า *"แถม DC Dimming เล่นนานๆ ก็สบายตาขึ้น"* แต่หน้าสินค้าไม่มีคำว่า
"DC Dimming" เลย มีแต่ "Precise Dimming Zones" (คนละเรื่อง — ระบบคุมแสงแบ็คไลท์
84 โซน ไม่ใช่เทคโนโลยีลดการกะพริบ) **AI หยิบคำว่า Dimming มาแล้วเติม DC เข้าไปเอง**

**ทำไมเรื่องนี้แพงกว่าเรื่องลิขสิทธิ์** กฎ Shopee หัก
  · ละเมิดทรัพย์สินทางปัญญา     1 คะแนน
  · ข้อมูลบิดเบือน/อ้างเกินจริง  3 คะแนน   ← **หนักกว่า 3 เท่า**
(ดู SHOPEE-VIDEO-RULES.md · กฎ AI ข้อ 5 "ห้ามกล่าวอ้างสรรพคุณสินค้าเกินจริง")

**กติกาที่ห้ามละเมิดในไฟล์นี้ — แหล่งอ้างอิงต้องเป็นของ Shopee เท่านั้น**

ตอนเขียนครั้งแรกผมเผลอเอา `highlights` (จุดเด่นที่ AI คัดมาเอง) ไปนับเป็นแหล่ง
อ้างอิงด้วย ซึ่งคือ **การเอาคำตอบของ AI มาตรวจ AI เอง** — บทพูดถูกเขียนขึ้นจาก
จุดเด่นชุดนั้นอยู่แล้ว ตรวจแบบนั้นจึงได้ 0 เสมอไม่ว่าจริงหรือไม่จริง
ที่นี่จึงยึด **ชื่อสินค้า + รายละเอียดจากหน้า Shopee (`detail.txt`)** เท่านั้น

    import clip_claims
    bad = clip_claims.check(run, folder)     # [{"scene":5,"kind":"คำ","value":"DC Dimming",...}]
    clip_claims.summary(bad)                 # ข้อความไทยพร้อมโชว์

ดูจากบรรทัดคำสั่ง

    python clip_claims.py            ตรวจทุกงานที่มีบทพูด
    python clip_claims.py <item_id>  ตรวจใบเดียว
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

# ตัวเลขทั่วไปที่ไม่ใช่การอ้างสรรพคุณ — "ลอง 3 โหมด" "2 ปุ่ม" ไม่ต้องตรวจ
# **ห้ามใส่เลขที่เป็นสเปกจริงลงมา** เช่น 4 (4K) 8 (8K) เพราะจะกลายเป็นรูรั่ว
COMMON_NUMBERS = {"1", "2", "3", "5", "10", "100"}

# ตัวย่อที่ใช้กันทั่วไปจนไม่ต้องมีในหน้าสินค้า
COMMON_WORDS = {"AI", "HDR", "4K", "8K", "LED", "TV", "PRO", "DC", "UV", "HD",
                "FHD", "QLED", "OLED", "USB", "LCD", "PC"}

NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)?")

# คำเฉพาะในบทพูด — เดี่ยวหรือสองคำติดกัน (จับ "DC Dimming" · "Dolby Atmos")
#
# **ต้องกิน `\d*` ที่ติดหน้าคำด้วย** ไม่งั้นตัดคำพลาดแล้วเตือนมั่ว
# เจอจริง 26 ส.ค. 2026: บทพูดเขียนว่า "120Hz DLG" แต่ตัวจับเดิมเริ่มที่ตัวอักษร
# จึงได้ "Hz DLG" ซึ่งไม่มีในหน้าสินค้า → เตือนว่าอ้างเกินจริง
# ทั้งที่หน้าสินค้าเขียนว่า **"120Hz DLG for 55-85""** ตรงตัว
#
# **ตัวตรวจที่เตือนมั่วอันตรายพอกับตัวตรวจที่เงียบ** — เตือนผิดสองสามครั้ง
# แล้วคนจะเลิกอ่าน พอของจริงโผล่มาก็ถูกกดข้ามไปด้วย
WORD_RE = re.compile(
    r"\d*[A-Za-z][A-Za-z0-9.\-]{1,}(?:\s+\d*[A-Za-z][A-Za-z0-9.\-]+)?")


def _numbers(text: str) -> set[str]:
    """ตัวเลขในข้อความ — ตัดจุลภาคออกให้เทียบกันได้ (18,436 = 18436)"""
    found: set[str] = set()
    for raw in NUMBER_RE.findall(text or ""):
        clean = raw.replace(",", "")
        found.add(clean)
        if clean.endswith(".0"):
            found.add(clean[:-2])
    return found


def source_text(run: dict, folder: Path) -> str:
    """ข้อความต้นฉบับจาก Shopee — **ห้ามใส่อะไรที่ AI เขียนลงไปเด็ดขาด**"""
    parts = [str(run.get("name") or "")]
    detail = folder / "detail.txt"
    if detail.is_file():
        parts.append(detail.read_text(encoding="utf-8", errors="replace"))
    return " ".join(parts)


def check(run: dict, folder: Path) -> list[dict]:
    """คืนรายการคำอ้างที่ไม่มีในหน้าสินค้า — ว่าง = ไม่พบอะไรน่าสงสัย"""
    script = list(run.get("script") or [])
    if not script:
        return []
    source = source_text(run, folder)
    if not source.strip():
        return []                      # ไม่มีต้นฉบับให้เทียบ = ตอบไม่ได้ ไม่ใช่ผ่าน
    have_numbers = _numbers(source)
    low = source.lower()

    found: list[dict] = []
    for scene, line in enumerate(script, start=1):
        for number in _numbers(line):
            if number in COMMON_NUMBERS or number in have_numbers:
                continue
            found.append({"scene": scene, "kind": "ตัวเลข",
                          "value": number, "line": line})
        for raw in WORD_RE.findall(line):
            word = raw.strip()
            if len(word) < 3 or word.upper() in COMMON_WORDS:
                continue
            if word.lower() in low:
                continue
            # คำแรกมีในหน้าสินค้าก็ปล่อย — กันกรณีจับคำถัดไปติดมาด้วย
            head = word.split()[0]
            if len(head) >= 3 and head.lower() in low:
                continue
            found.append({"scene": scene, "kind": "คำ",
                          "value": word, "line": line})
    return found


def summary(found: list[dict]) -> str:
    """สรุปเป็นข้อความไทยพร้อมโชว์ในแชทหรือบนหน้าเว็บ"""
    if not found:
        return ""
    rows = [f"⚠️ <b>คำอ้างที่ไม่มีในหน้าสินค้า {len(found)} จุด</b> "
            "— แก้ก่อนโพสต์ ไม่งั้นเข้าข่ายอ้างสรรพคุณเกินจริง (หัก 3 คะแนน)"]
    for item in found:
        rows.append(f"  · ฉาก {item['scene']}: {item['kind']} “{item['value']}” "
                    f"ไม่มีในหน้าสินค้า")
        rows.append(f"    {item['line']}")
    return "\n".join(rows)


# งานถูกแยกโฟลเดอร์ตามสถานะตั้งแต่ 27 ส.ค. 2569 — ต้องไล่ให้ครบทุกอัน
_PRODUCT_DIRS = ("shopee_products", "clips", "clipsfb", "clipstiktok",
                 "waitstory", "waitclips", "waitclipsfb", "waitclipstiktok")


def _run_dirs(root: Path):
    folders = [f for name in _PRODUCT_DIRS for f in (root / name).glob("*")]
    for folder in sorted(folders, key=lambda f: f.name):
        run_file = folder / "run.json"
        if run_file.is_file():
            try:
                yield folder, json.loads(run_file.read_text(encoding="utf-8"))
            except Exception:                                # noqa: BLE001
                continue


if __name__ == "__main__":
    import studio_shared
    root = studio_shared.DATA_DIR
    only = sys.argv[1] if len(sys.argv) > 1 else ""
    total = dirty = 0
    for folder, run in _run_dirs(root):
        if only and str(run.get("item_id")) != only:
            continue
        if not (run.get("script") or []):
            continue
        total += 1
        found = check(run, folder)
        if not found:
            continue
        dirty += 1
        print(f"── {run.get('item_id')} | {(run.get('name') or '')[:46]}")
        for item in found:
            print(f"     ฉาก {item['scene']}: {item['kind']} \"{item['value']}\" "
                  f"ไม่มีในหน้าสินค้า")
            print(f"        → {item['line']}")
        print()
    print(f"ตรวจ {total} ใบ · พบคำอ้างน่าสงสัย {dirty} ใบ")
    if not dirty:
        print("ทุกตัวเลขและทุกคำเฉพาะในบทพูด มาจากหน้าสินค้าจริงทั้งหมด")
