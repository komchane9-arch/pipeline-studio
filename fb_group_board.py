# -*- coding: utf-8 -*-
"""กระดานกลุ่ม Facebook — แยกตามช่วงสมาชิก × ผลตัดสิน พร้อมให้กด Approve/Reject

**เจ้าของสั่งไว้ 1 ก.ย. 2569** — *"แยกตามเกณฑ์ 100,000 / 50-100 / 10-50 แล้ว
แต่ละอันแยก ดี ก้ำกึ่ง ไม่ดี พร้อมลิงก์เฟส อันไหนก้ำกึ่งมีปุ่มให้ผม approve
หรือ reject ด้วย เอาขึ้นหน้าเว็บเลย"*

---

## ที่มาของข้อมูล — ไม่ได้คิดเกณฑ์ขึ้นใหม่

ทั้งการค้นกลุ่มและการตัดสินมีอยู่แล้วใน `fb_mass_bot.py` (บอทตัวแยก) ตั้งแต่
14 ส.ค. 2569 ตามที่เจ้าของสั่งไว้ตอนนั้น โมดูลนี้แค่**เอาผลมาจัดให้อ่านบนเว็บ**

    เกณฑ์ที่บอทใช้ (fb_mass_bot.KW_ALIVE_OVER / KW_ALIVE_AVG)
      ข้อ 1  มีโพสต์ที่ได้เกิน 100 ไลก์ ตั้งแต่ 5 ใบขึ้นไป
      ข้อ 2  ไลก์เฉลี่ยทุกโพสต์ ตั้งแต่ 8.0 ขึ้นไป
      ผ่านสองข้อ = ดี · ผ่านข้อเดียว = ก้ำกึ่ง · ตกสองข้อ = ไม่ดี

## ⚠️ ทำไมไม่เขียนลงไฟล์ของบอทตรงๆ

`fb_mass_finder.save_kw_state()` เขียนทับทั้งไฟล์ **ไม่มีล็อกและไม่ได้เขียนแบบ
สลับไฟล์** ส่วนจังหวะทำงานของบอทคือ

    อ่านไฟล์ → เปิดเบราว์เซอร์ไล่ 1,000 โพสต์ (นานเป็นนาที) → เขียนทับกลับ

ถ้าหน้าเว็บเขียนแทรกช่วงนั้น **คำตัดสินของเจ้าของหายทันทีโดยไม่มีใครรู้**
และ `studio_shared.update_json` ช่วยไม่ได้ เพราะล็อกฝ่ายเดียวกันไม่ได้ —
อีกฝั่งไม่ได้ขอล็อก

**คำตัดสินจากหน้าเว็บจึงเก็บในไฟล์ของตัวเองที่บอทไม่รู้จัก** แล้วเอามาทับ
ตอนแสดงผล บอทเขียนไฟล์ตัวเองทับกี่รอบก็ลบของเจ้าของไม่ได้

ผลข้างเคียงที่ต้องรู้: กลุ่มที่กดจากเว็บ **การ์ดใน Telegram จะยังค้างอยู่**
เพราะบอทไม่เห็นไฟล์นี้ — กดซ้ำในการ์ดได้ ไม่เสียหาย ผลลัพธ์เหมือนกัน
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import studio_shared

KW_STATE = "fb_kw_state.json"          # ของบอท — **อ่านอย่างเดียว**
DECISIONS = "fb_group_decisions.json"  # ของหน้าเว็บ — เขียนได้เฉพาะที่นี่

# ช่วงสมาชิกตามที่เจ้าของสั่ง (เรียงจากใหญ่ไปเล็ก — ตกช่วงเดียวเสมอ)
BANDS = [
    ("big", "สมาชิกเกิน 100,000", 100_000, None),
    ("mid", "สมาชิก 50,000–100,000", 50_000, 100_000),
    ("small", "สมาชิก 10,000–50,000", 10_000, 50_000),
    ("tiny", "สมาชิกต่ำกว่า 10,000", 0, 10_000),
]

GOOD, EDGE, BAD = "good", "edge", "bad"
STATUS_LABEL = {GOOD: "ดี", EDGE: "ก้ำกึ่ง", BAD: "ไม่ดี"}

# ลำดับความสำคัญตอนกลุ่มหนึ่งโผล่หลายที่ในไฟล์ของบอท — **สูงกว่าชนะ**
# `approved` มาก่อน `whitelist` เพราะเป็นการตัดสินของคนซึ่งหนักกว่าของเครื่อง
_SOURCES = [("approved", GOOD, 3), ("whitelist", GOOD, 2),
            ("pending", EDGE, 1), ("rejected", BAD, 0)]


def _decisions_path() -> Path:
    return Path(studio_shared.DATA_DIR) / DECISIONS


def load_decisions() -> dict:
    """คำตัดสินที่กดจากหน้าเว็บ — {gid: {decision, at, was}}"""
    return studio_shared.read_json(_decisions_path(), {}) or {}


def decide(gid: str, decision: str, note: str = "") -> dict:
    """บันทึกคำตัดสินหนึ่งกลุ่ม — `decision` = approve / reject / clear

    เขียนด้วย `update_json` (ล็อกข้ามโปรเซส + เขียนแบบสลับไฟล์) เพราะหน้าเว็บ
    เปิดหลายแท็บพร้อมกันได้ และรอบถัดไปอาจมีตัวอื่นมาอ่านระหว่างเขียน
    """
    gid = str(gid or "").strip()
    if not gid:
        raise ValueError("ไม่ได้บอกว่ากลุ่มไหน")
    if decision not in ("approve", "reject", "clear"):
        raise ValueError(f"ไม่รู้จักคำสั่ง {decision!r}")

    def mutate(current: dict) -> None:
        if decision == "clear":
            current.pop(gid, None)
            return
        current[gid] = {
            "decision": decision,
            "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "note": str(note or "")[:200],
        }

    return studio_shared.update_json(_decisions_path(), mutate, default={},
                                     label=f"ตัดสินกลุ่ม {gid}")


def _band_of(members) -> str:
    count = int(members or 0)
    for key, _label, low, high in BANDS:
        if count >= low and (high is None or count < high):
            return key
    return "tiny"


def _row(gid: str, item: dict, status: str, chosen: dict | None) -> dict:
    """หนึ่งบรรทัดที่หน้าเว็บเอาไปวาดได้ตรงๆ

    **บอกด้วยเสมอว่าผ่านเกณฑ์ข้อไหน** ไม่ใช่บอกแค่ผลรวม เพราะเจ้าของสั่งว่า
    *"แยกให้ด้วยอันไหนจากเกณฑ์ไหนบ้าง"* — กลุ่มก้ำกึ่งสองใบอาจก้ำกึ่งคนละ
    เหตุผลกันสิ้นเชิง (ใบหนึ่งมีโพสต์ปังแต่พื้นเงียบ อีกใบพื้นดีแต่ไม่มีใบปัง)
    """
    over = item.get("over")
    avg = item.get("avg")
    pass_over = None if over is None else bool(over >= 5)
    pass_avg = None if avg is None else bool(avg >= 8.0)
    members = int(item.get("members") or 0)
    url = str(item.get("url") or "")
    if not url and gid:
        url = f"https://www.facebook.com/groups/{gid}"
    return {
        "gid": gid,
        "name": str(item.get("name") or gid or "(ไม่มีชื่อ)"),
        "url": url,
        "members": members,
        "keyword": str(item.get("keyword") or ""),
        "avg": avg,
        "over": over,
        "pass_avg": pass_avg,
        "pass_over": pass_over,
        "pass_members": members >= 100_000,
        "status": status,
        "status_label": STATUS_LABEL[status],
        "auto_status": status,          # ผลจากบอท ก่อนเอาคำตัดสินมาทับ
        "decision": (chosen or {}).get("decision") or "",
        "decided_at": (chosen or {}).get("at") or "",
    }


def board(want: str = "") -> dict:
    """กระดาน — ช่วงสมาชิก × ผลตัดสิน พร้อมรายชื่อกลุ่ม

    `want` ว่าง = ส่งเฉพาะกอง **ดี** กับ **ก้ำกึ่ง** ส่วนกอง "ไม่ดี" ส่งแค่
    จำนวน เพราะมี 1,173 ใบ คิดเป็น **ราวสองในสามของข้อมูลทั้งหมด**
    (ส่งครบทีเดียว 685 KB · ตัดกองไม่ดีออกเหลือราว 240 KB)

    เจ้าของเปิดหน้านี้ผ่าน Tailscale ไม่ใช่ในเครื่อง การส่งของที่ยังไม่ได้ดู
    ไปด้วยทุกครั้งคือทำให้หน้าช้าฟรีๆ — กองไม่ดีขอเป็นรายกองตอนกดเปิด

    `want` = "<ช่วง>:<สถานะ>" เช่น `big:bad` = ขอเฉพาะกองนั้นกองเดียว
    """
    state = studio_shared.read_json(
        Path(studio_shared.DATA_DIR) / KW_STATE, {}) or {}
    chosen = load_decisions()

    # กลุ่มเดียวอาจอยู่หลายกอง — เก็บกองที่ลำดับสูงสุดไว้กองเดียว
    best: dict[str, tuple[int, str, dict]] = {}
    for source, status, rank in _SOURCES:
        for gid, item in (state.get(source) or {}).items():
            if not isinstance(item, dict):
                continue
            old = best.get(gid)
            if old is None or rank > old[0]:
                best[gid] = (rank, status, item)

    cells: dict[str, dict[str, list]] = {
        key: {GOOD: [], EDGE: [], BAD: []} for key, *_ in BANDS}
    moved = 0
    for gid, (_rank, status, item) in best.items():
        pick = chosen.get(gid)
        if pick:
            # **คำตัดสินของคนทับผลของเครื่องเสมอ** และต้องเห็นว่าเดิมคืออะไร
            final = GOOD if pick.get("decision") == "approve" else BAD
            if final != status:
                moved += 1
            row = _row(gid, item, final, pick)
            row["auto_status"] = status
        else:
            row = _row(gid, item, status, None)
        cells[_band_of(item.get("members"))][final if pick else status].append(row)

    for band in cells.values():
        for rows in band.values():
            # เรียงจากคึกคักสุดลงมา — ใบที่ยังไม่มีตัวเลขไปท้ายสุด
            rows.sort(key=lambda r: (r["avg"] is None, -(r["avg"] or 0)))

    only_band, _, only_status = str(want or "").partition(":")

    bands_out = []
    for key, label, low, high in BANDS:
        cell = cells[key]
        if not any(cell.values()):
            continue
        if only_status:
            # ขอเฉพาะกองเดียว — กองอื่นส่งเป็นรายการว่าง แต่ยังส่งจำนวนไปด้วย
            groups = {s: (cell[s] if (key == only_band and s == only_status)
                          else []) for s in (GOOD, EDGE, BAD)}
        else:
            # ค่าปกติ: ส่ง ดี + ก้ำกึ่ง ครบ ส่วนไม่ดีส่งแค่จำนวน
            groups = {GOOD: cell[GOOD], EDGE: cell[EDGE], BAD: []}
        bands_out.append({
            "key": key,
            "label": label,
            "min_members": low,
            "max_members": high,
            "counts": {s: len(cell[s]) for s in (GOOD, EDGE, BAD)},
            "groups": groups,
        })

    total = sum(len(c[s]) for c in cells.values() for s in (GOOD, EDGE, BAD))
    return {
        "ok": True,
        "bands": bands_out,
        "total": total,
        "decided": len(chosen),
        "moved_by_you": moved,
        "rule": {
            "over": 5, "avg": 8.0,
            "text": ("เกณฑ์ที่บอทใช้ (เจ้าของสั่งไว้ 14 ส.ค. 2569): "
                     "มีโพสต์เกิน 100 ไลก์ ≥ 5 ใบ **และ** ไลก์เฉลี่ย ≥ 8.0 = ดี · "
                     "ผ่านข้อเดียว = ก้ำกึ่ง · ตกทั้งสองข้อ = ไม่ดี"),
        },
        "checked_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }


if __name__ == "__main__":                                    # pragma: no cover
    data = board()
    print(f"รวม {data['total']} กลุ่ม · คุณตัดสินเองไปแล้ว {data['decided']} ใบ "
          f"(ย้ายกอง {data['moved_by_you']} ใบ)\n")
    head = f"{'ช่วงสมาชิก':26} {'ดี':>6} {'ก้ำกึ่ง':>8} {'ไม่ดี':>7}"
    print(head)
    for band in data["bands"]:
        c = band["counts"]
        print(f"{band['label']:26} {c['good']:>6} {c['edge']:>8} {c['bad']:>7}")
