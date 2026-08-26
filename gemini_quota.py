"""ตัวนับโควตา Gemini ชั้นฟรี — จดว่าวันนี้ยิงไปกี่ครั้ง โมเดลไหนหมดแล้ว

ผู้ใช้สั่ง 26 ส.ค. 2026: "ให้มีแถบโชว์โควต้า API free ของ gemini ด้วย"

**ข้อจำกัดที่ต้องเข้าใจก่อน** — Google **ไม่มีที่ให้ถามว่าเหลือกี่ครั้ง**
ชั้นฟรีบอกโควตาที่เหลือไม่ได้เลย รู้ได้สองทางเท่านั้น

  1. **นับเอง** ว่าเรายิงไปกี่ครั้งวันนี้ (แม่นสำหรับการยิงที่ผ่านตัวนี้)
  2. **รอให้มันบอกตอนหมด** — คำตอบ 429 มี `quotaValue` ติดมาด้วย
     ซึ่งคือเพดานจริงของโมเดลนั้น

จึงแสดงสองอย่างนี้ตรงๆ **ห้ามเดาตัวเลข "เหลืออีกกี่ครั้ง" เอง** ถ้าไม่รู้เพดาน
ตัวเลขที่เดามาแล้วผิดอันตรายกว่าไม่มีตัวเลข เพราะคนจะวางแผนงานตามมัน
(กติกาข้อ 2.3 ของโปรเจกต์: ตัวตรวจที่บอกว่าผ่านทั้งที่ยังไม่ผ่าน อันตรายกว่าไม่มี)

**นับต่อวันตามเวลาไทย** เพราะโควตาชั้นฟรีรีเซ็ตตามเวลาแปซิฟิก แต่คนใช้อยู่ไทย
ถ้าจดตามเวลาเครื่องเฉยๆ เลขจะกระโดดกลางวันโดยไม่มีใครเข้าใจ — ตรงนี้จดตามวันไทย
แล้วบอกไว้ให้ชัดว่าของจริงรีเซ็ตคนละเวลา ดีกว่าแกล้งทำเป็นรู้

ใช้ยังไง
    import gemini_quota
    gemini_quota.record("gemini-3.5-flash", ok=True)
    gemini_quota.record("gemini-3.5-flash", ok=False, response=res)   # จับ 429 ให้เอง
    gemini_quota.today()      # สรุปของวันนี้ ให้หน้าเว็บเอาไปโชว์

ดูจากบรรทัดคำสั่ง
    python gemini_quota.py
"""

from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path

import studio_shared

# วันไทย = UTC+7 ไม่พึ่งเขตเวลาของเครื่อง เพราะเซิร์ฟเวอร์สองตัวอาจตั้งคนละแบบ
_TZ = _dt.timezone(_dt.timedelta(hours=7))

QUOTA_FILE = studio_shared.DATA_DIR / "gemini_quota.json"

# เก็บย้อนหลังกี่วัน — ไว้ดูว่าเมื่อวานใช้ไปเท่าไร พอประมาณการวันนี้ได้
KEEP_DAYS = 14

# งานของแต่ละโมเดลในระบบ — ไว้บอกคนอ่านว่าโมเดลนี้ใครใช้ จะได้รู้ว่าถ้าหมดแล้ว
# อะไรจะพัง (ไล่มาจากคอมเมนต์ที่เขียนไว้ในแต่ละไฟล์)
MODEL_JOBS = {
    "gemini-3.7-flash": "คัดจุดเด่นจากข้อความสินค้า",
    "gemini-3.5-flash": "คัดจุดเด่นจากรูป · เลือกรูปเข้าคลิป",
    "gemini-3.6-flash": "แก้คำสั่ง Flow ที่ผิดนโยบาย",
    "gemini-3.5-flash-lite": "ทางถอยของตัวคัดจุดเด่น · ตรวจคลิป",
    "gemini-3.1-flash-lite": "ตรวจคลิป (เสียง/ตัวอักษร)",
    "gemini-3.1-flash-lite-preview": "ตั้งแฮชแท็ก",
    "gemini-3-flash-preview": "ทางถอยของตัวแก้คำสั่ง Flow",
    "gemini-2.5-flash": "ทางถอยชั้นท้ายของตัวตรวจคลิป",
}


def _today() -> str:
    return _dt.datetime.now(_TZ).strftime("%Y-%m-%d")


def _now() -> str:
    return _dt.datetime.now(_TZ).strftime("%H:%M:%S")


def _blank() -> dict:
    return {"days": {}}


def _read() -> dict:
    try:
        data = json.loads(QUOTA_FILE.read_text(encoding="utf-8"))
    except Exception:                                        # noqa: BLE001
        return _blank()
    return data if isinstance(data, dict) and "days" in data else _blank()


def _quota_from_429(response) -> tuple[bool, str, str]:
    """อ่านคำตอบ 429 ว่าเป็น "หมดวัน" หรือแค่ "ยิงถี่ไป"

    คืน (หมดโควตารายวันไหม, เพดานที่ Google บอก, ข้อความเหตุผล)

    **ต้องแยกให้ออก** เพราะสองอย่างนี้ความหมายต่างกันสิ้นเชิง — ยิงถี่ไปคือรอแป๊บ
    แล้วได้ต่อ ส่วนหมดวันคือรอเท่าไรก็ไม่ได้ ต้องข้ามไปพรุ่งนี้
    (ตรรกะเดียวกับ `clip_check._busy_hint` ที่พิสูจน์กับของจริงมาแล้ว)
    """
    try:
        error = response.json().get("error", {})
    except Exception:                                        # noqa: BLE001
        return False, "", ""
    why = str(error.get("message") or "")[:200]
    for detail in error.get("details") or []:
        if "QuotaFailure" not in str(detail.get("@type", "")):
            continue
        for hit in detail.get("violations") or []:
            if "PerDay" in str(hit.get("quotaId") or ""):
                return True, str(hit.get("quotaValue") or ""), why
    return False, "", why


def record(model: str, ok: bool = True, response=None) -> None:
    """จดหนึ่งครั้งที่ยิงไปหา Gemini

    **ห้ามทำให้งานหลักล้ม** ถ้าจดไม่ได้ก็ปล่อยผ่าน — ตัวนับเป็นของเสริม
    ถ้าเขียนไฟล์พลาดแล้วไปทำให้การเจนคลิปล้ม จะเสียหายกว่าไม่มีตัวนับ
    """
    name = str(model or "").strip()
    if not name:
        return
    daily, limit, why = (False, "", "")
    if not ok and response is not None:
        daily, limit, why = _quota_from_429(response)

    def mutate(data: dict) -> dict:
        if not isinstance(data, dict) or "days" not in data:
            data = _blank()
        day = data["days"].setdefault(_today(), {})
        row = day.setdefault(name, {"calls": 0, "fails": 0})
        row["calls"] = int(row.get("calls", 0)) + 1
        if not ok:
            row["fails"] = int(row.get("fails", 0)) + 1
        if daily:
            row["dry_at"] = _now()
            if limit:
                row["limit"] = limit
            if why:
                row["why"] = why
        # ลบวันเก่าทิ้ง ไม่ให้ไฟล์โตไปเรื่อยๆ
        for old in sorted(data["days"])[:-KEEP_DAYS]:
            data["days"].pop(old, None)
        return data

    try:
        studio_shared.update_json(QUOTA_FILE, mutate)
    except Exception:                                        # noqa: BLE001
        pass


def today() -> dict:
    """สรุปการใช้ของวันนี้ ให้หน้าเว็บเอาไปแสดง

    `limit` มีค่าเฉพาะโมเดลที่**เคยโดน 429 แบบหมดวัน**มาแล้ว เพราะนั่นเป็นทางเดียว
    ที่ Google บอกเพดานจริง — โมเดลที่ยังไม่เคยหมด จะไม่มีเลขเพดาน และ **ห้ามเดาให้**
    """
    data = _read()
    day = data["days"].get(_today(), {})
    rows = []
    for name, row in sorted(day.items(), key=lambda kv: -int(kv[1].get("calls", 0))):
        limit = str(row.get("limit") or "")
        calls = int(row.get("calls", 0))
        left = None
        if limit.isdigit():
            left = max(0, int(limit) - calls)
        rows.append({
            "model": name,
            "job": MODEL_JOBS.get(name, ""),
            "calls": calls,
            "fails": int(row.get("fails", 0)),
            "limit": limit,
            "left": left,
            "dry": bool(row.get("dry_at")),
            "dry_at": row.get("dry_at", ""),
            "why": row.get("why", ""),
        })
    dry = [r["model"] for r in rows if r["dry"]]
    return {
        "date": _today(),
        "rows": rows,
        "total": sum(r["calls"] for r in rows),
        "dry": dry,
        # เขียนไว้ให้คนอ่านเข้าใจข้อจำกัด ไม่ใช่ให้เข้าใจผิดว่าเป็นตัวเลขทางการ
        "note": ("นับจากที่ระบบนี้ยิงเอง — Google ไม่มีที่ให้ถามว่าเหลือกี่ครั้ง "
                 "เพดานจะรู้ก็ต่อเมื่อโดนปฏิเสธเพราะหมดโควตาแล้วเท่านั้น "
                 "และของจริงรีเซ็ตตามเวลาแปซิฟิก ไม่ตรงกับเที่ยงคืนบ้านเรา"),
    }


def history(days: int = 7) -> list[dict]:
    """ยอดรวมย้อนหลัง ไว้ดูว่าปกติวันหนึ่งใช้เท่าไร"""
    data = _read()
    out = []
    for date in sorted(data["days"])[-days:]:
        day = data["days"][date]
        out.append({
            "date": date,
            "total": sum(int(r.get("calls", 0)) for r in day.values()),
            "models": len(day),
            "dry": [n for n, r in day.items() if r.get("dry_at")],
        })
    return out


if __name__ == "__main__":
    now = today()
    print(f"โควตา Gemini วันที่ {now['date']} — ยิงไปทั้งหมด {now['total']} ครั้ง")
    if not now["rows"]:
        print("  (วันนี้ยังไม่ได้ยิงเลย)")
    for row in now["rows"]:
        mark = "🔴 หมดแล้ว" if row["dry"] else "🟢"
        cap = f" / เพดาน {row['limit']}" if row["limit"] else ""
        left = f" · เหลือ {row['left']}" if row["left"] is not None else ""
        fail = f" · ล้ม {row['fails']}" if row["fails"] else ""
        print(f"  {mark} {row['model']:32} {row['calls']} ครั้ง{cap}{left}{fail}")
        if row["job"]:
            print(f"      ใช้ทำ: {row['job']}")
        if row["dry"]:
            print(f"      หมดตอน {row['dry_at']} — {row['why']}")
    print()
    print("ย้อนหลัง:")
    for row in history():
        print(f"  {row['date']}  {row['total']:4} ครั้ง · {row['models']} โมเดล"
              + (f" · หมด: {', '.join(row['dry'])}" if row["dry"] else ""))
    print()
    print(now["note"])
