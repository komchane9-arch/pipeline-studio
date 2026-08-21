"""สมุดบัญชีต้นทุน — งานที่เสียเงินจริงต้องมีที่จดว่าเสียไปกับอะไร

**ทำไมต้องมี** กติกาข้อ 2.1 บอกว่า "ปล่อยผ่านคือจ่ายเงินเปล่าซ้ำๆ" แต่ที่ผ่านมา
ไม่มีใครตอบได้ว่าจ่ายเปล่าไปเท่าไร เพราะไม่มีที่จด

ของที่ต้องใช้**มีอยู่แล้ว** — `flow_driver.read_credits()` อ่านเครดิตคงเหลือได้จริง
และ `clip_app.py` ก็อ่านก่อน–หลังทุกรอบอยู่แล้ว แต่เขียนลง log อย่างเดียว แล้ว log
ก็หมุนทิ้งตัวเองที่ 200 KB (`studio_shared.LOG_LIMIT_BYTES`) ตัวเลขจึงหายไปเฉยๆ
ไฟล์นี้แค่รับตัวเลขเดิมนั้นมาเก็บไว้ให้ถาม

**สามคำถามที่ต้องตอบให้ได้**

    คลิปนี้ต้นทุนเท่าไร        by_item("tt_7665...")
    เดือนนี้เผาไปเท่าไร        summary(days=30)
    งานที่ล้มกินไปเท่าไร        summary()["wasted"]    ← ตัวที่ควรทำให้เจ็บพอจะไปแก้

**วัดได้จริง กับ เดาเอา ต้องแยกให้ออก**

`before - after` คือของจริงที่วัดจากหน้าเว็บ ส่วน `creditCost` ที่หน้าเว็บบอกก่อนกด
เป็นแค่ราคาป้าย — บันทึกได้แต่ต้องติดธง `measured=False` ไว้ กติกาข้อ 5 ห้ามเขียน
ของที่ยังไม่ได้พิสูจน์ให้ดูเหมือนพิสูจน์แล้ว

**การจดบัญชีต้องไม่มีวันทำให้งานที่มันจดพัง**

`record()` จึงไม่โยน exception ออกมาเลย — ถ้าเขียนไม่ได้จะลง log ให้ดัง แล้วคืน
`saved=False` กลับไป ตรงนี้ไม่ขัดกับข้อ 2.1 เพราะไม่ได้เอา fallback ไปกลบความล้มเหลว
ของงานหลัก แต่กันไม่ให้ "จดไม่ลง" ไปฆ่ารอบเจนที่เพิ่งจ่ายเครดิตไปแล้ว 30 หน่วย
ความล้มเหลวของตัวจดยังดังเท่าเดิม แค่ไม่ลากงานหลักล้มตาม

**ทำไมเป็น JSONL ไม่ใช่ JSON ก้อนเดียว**

บัญชีมีแต่เพิ่ม ไม่เคยแก้ของเก่า — ต่อท้ายบรรทัดเดียวจึงพอ ไม่ต้องอ่านทั้งไฟล์มา
เขียนใหม่ทุกครั้งแบบ `update_json` ขนาดที่โตจริงคือราวบรรทัดละ 200 ไบต์ · คลิปละ
ราว 8 บรรทัด (ฉากละบรรทัด + วิเคราะห์ + สรุป) = **คลิปละ 1.6 KB** พันคลิปยังไม่ถึง
2 MB จึงยังไม่ต้องมีกลไกหมุนไฟล์ให้ซับซ้อนเกินจำเป็น
"""

from __future__ import annotations

import json
import statistics
import sys
from datetime import datetime, timedelta

import studio_shared

LEDGER_PATH = studio_shared.DATA_DIR / "cost_ledger.jsonl"

# ชนิดต้นทุน → (ชื่อที่คนอ่านรู้เรื่อง, หน่วย)
KINDS: dict[str, tuple[str, str]] = {
    "flow": ("Google Flow", "เครดิต"),
    "gemini": ("Gemini", "ครั้ง"),
    "chatgpt": ("ChatGPT", "ครั้ง"),
    "other": ("อื่นๆ", "หน่วย"),
}


def _now_text() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _parse_time(raw: str) -> datetime | None:
    try:
        return datetime.fromisoformat(str(raw))
    except (TypeError, ValueError):
        return None


# ------------------------------------------------------------------- เขียน

def _resolve_used(used, before, after) -> tuple[float | None, bool, str]:
    """ตัดสินว่ายอดที่ใช้จริงคือเท่าไร วัดได้หรือแค่เดา และมีอะไรผิดปกติไหม

    คืน (ยอดที่ใช้, วัดได้จริงไหม, หมายเหตุเพิ่ม)

    เคสที่ต้องระวัง: **เครดิตเพิ่มขึ้นระหว่างงาน** = มีคนเติมเงินคั่น ถ้าเอา
    `before - after` ไปใช้ตรงๆ จะได้เลขติดลบแล้วยอดรวมทั้งเดือนเพี้ยนตาม
    กรณีนี้ยอมรับว่า "วัดไม่ได้" ดีกว่าบันทึกเลขที่รู้ทั้งรู้ว่าผิด
    """
    if before is not None and after is not None:
        gap = before - after
        if gap < 0:
            return None, False, f"เครดิตเพิ่มขึ้น {-gap:.0f} ระหว่างงาน (เติมเงินคั่น?) วัดยอดใช้ไม่ได้"
        return float(gap), True, ""
    if used is not None:
        return float(used), False, ""
    return None, False, ""


def record(kind: str, *, item_id: str = "", used=None, before=None, after=None,
           ok: bool = True, note: str = "", scene=None, **extra) -> dict:
    """จดหนึ่งรายการ — ไม่โยน exception ไม่ว่าเกิดอะไรขึ้น

    `before`/`after` = เครดิตคงเหลือก่อนและหลัง (มีเฉพาะฝั่ง Flow)
    `used`           = ยอดที่คาดว่าจะใช้ ใช้เมื่ออ่านคงเหลือไม่ได้
    `ok=False`       = งานนี้ล้ม เครดิตที่เสียไปนับเข้าช่อง "จ่ายเปล่า"
    """
    amount, measured, warn = _resolve_used(used, before, after)
    if warn:
        note = f"{note} · {warn}".strip(" ·")

    entry = {
        "at": _now_text(),
        "kind": kind if kind in KINDS else "other",
        "item_id": str(item_id or ""),
        "used": amount,
        "measured": measured,
        "ok": bool(ok),
    }
    if scene is not None:
        entry["scene"] = scene
    if before is not None:
        entry["before"] = before
    if after is not None:
        entry["after"] = after
    if note:
        entry["note"] = note
    for key, value in extra.items():
        if key not in entry:
            entry[key] = value

    entry["saved"] = _append(entry)
    return entry


def _append(entry: dict) -> bool:
    """ต่อท้ายไฟล์หนึ่งบรรทัด — คืน False ถ้าเขียนไม่ได้ (พร้อมลง log ให้ดัง)

    บรรทัดสั้นกว่าบัฟเฟอร์ของ OS มาก การเขียนครั้งเดียวจบจึงไม่ปนกันแม้สอง
    เซิร์ฟเวอร์เขียนพร้อมกัน — เหตุผลเดียวกับ `studio_shared.append_log`
    """
    line = json.dumps({k: v for k, v in entry.items() if k != "saved"},
                      ensure_ascii=False)
    try:
        LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LEDGER_PATH.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
        return True
    except OSError as error:
        try:
            studio_shared.append_log(
                "clip", f"⚠️ จดสมุดบัญชีต้นทุนไม่ได้ ({error}) — รายการที่หาย: {line}"
            )
        except Exception:
            print(f"[cost_ledger] เขียนไม่ได้: {error} | {line}", file=sys.stderr)
        return False


# -------------------------------------------------------------------- อ่าน

_broken_lines = 0        # บรรทัดที่อ่านไม่ออกจากการอ่านครั้งล่าสุด


def entries(*, since: datetime | None = None, until: datetime | None = None,
            item_id: str = "", kind: str = "", days: int | None = None) -> list[dict]:
    """อ่านรายการตามเงื่อนไข

    บรรทัดที่อ่านไม่ออก (เขียนค้างตอนไฟดับ) ถูกข้าม **แต่ไม่หายเงียบ** — นับไว้
    ที่ `_broken_lines` แล้วลง log ให้เห็น กติกาข้อ 2.4 ห้ามปล่อยให้ความล้มเหลวเงียบ
    """
    global _broken_lines
    if days is not None and since is None:
        since = datetime.now() - timedelta(days=days)
    found: list[dict] = []
    broken = 0
    try:
        with LEDGER_PATH.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    broken += 1
                    continue
                when = _parse_time(row.get("at", ""))
                if since and (when is None or when < since):
                    continue
                if until and (when is None or when > until):
                    continue
                if item_id and row.get("item_id") != item_id:
                    continue
                if kind and row.get("kind") != kind:
                    continue
                found.append(row)
    except FileNotFoundError:
        _broken_lines = 0
        return []
    except OSError as error:
        print(f"[cost_ledger] อ่านสมุดบัญชีไม่ได้: {error}", file=sys.stderr)

    _broken_lines = broken
    if broken:
        try:
            studio_shared.append_log(
                "clip", f"⚠️ สมุดบัญชีต้นทุนมีบรรทัดที่อ่านไม่ออก {broken} บรรทัด"
            )
        except Exception:
            print(f"[cost_ledger] มีบรรทัดที่อ่านไม่ออก {broken} บรรทัด", file=sys.stderr)
    return found


def broken_lines() -> int:
    """จำนวนบรรทัดที่อ่านไม่ออกจากการเรียก `entries()` ครั้งล่าสุด"""
    return _broken_lines


def summary(**filters) -> dict:
    """ยอดรวม — แยก "ที่ใช้ไปกับงานที่สำเร็จ" ออกจาก "ที่จ่ายเปล่า" ให้ชัด"""
    rows = entries(**filters)
    total = wasted = 0.0
    measured_total = estimated_total = 0.0
    by_kind: dict[str, dict] = {}
    unknown = 0

    for row in rows:
        amount = row.get("used")
        kind = row.get("kind", "other")
        slot = by_kind.setdefault(kind, {"used": 0.0, "wasted": 0.0, "count": 0})
        slot["count"] += 1
        if amount is None:
            unknown += 1
            continue
        total += amount
        slot["used"] += amount
        if row.get("measured"):
            measured_total += amount
        else:
            estimated_total += amount
        if not row.get("ok", True):
            wasted += amount
            slot["wasted"] += amount

    return {
        "entries": len(rows),
        "used": total,
        "wasted": wasted,
        "measured": measured_total,
        "estimated": estimated_total,
        "unknown_entries": unknown,
        "by_kind": by_kind,
        "items": len({r.get("item_id") for r in rows if r.get("item_id")}),
    }


def by_item(item_id: str) -> dict:
    """ต้นทุนของคลิปเดียว พร้อมรายการย่อยไว้ดูว่าฉากไหนกิน"""
    rows = entries(item_id=item_id)
    result = summary(item_id=item_id)
    result["rows"] = rows
    result["failed"] = [r for r in rows if not r.get("ok", True)]
    return result


def latest_credits() -> tuple[float | None, str]:
    """เครดิต Flow คงเหลือที่บันทึกไว้ล่าสุด — คืน (ค่า, เวลาที่บันทึก)

    ใช้ตอบคำถาม "เหลือพอไหม" **โดยไม่ต้องเปิดเบราว์เซอร์** ซึ่งแพงและต้องยึด
    `browser_lock` ค่าที่ได้เป็นของ ณ เวลาที่จดไว้ ไม่ใช่ของสดๆ — ผู้เรียกต้อง
    บอกผู้ใช้ให้ชัดว่าเป็นค่าเมื่อไร ไม่งั้นจะกลายเป็นตัวตรวจที่หลอกคน (ข้อ 2.3)
    """
    latest_value = None
    latest_at = ""
    for row in entries(kind="flow"):
        for key in ("after", "before"):
            if row.get(key) is not None:
                when = row.get("at", "")
                if when >= latest_at:
                    latest_at, latest_value = when, float(row[key])
                break
    return latest_value, latest_at


def typical_scene_cost() -> float | None:
    """ค่ากลางของเครดิตที่ฉากหนึ่งกินจริง — คืน None ถ้ายังไม่มีข้อมูลพอ

    ใช้ค่ากลาง (median) ไม่ใช่ค่าเฉลี่ย เพราะรอบที่ล้มกลางคันจะได้ยอดต่ำผิดปกติ
    แล้วลากค่าเฉลี่ยลงจนประเมินต่ำเกินจริง
    """
    values = [
        float(r["used"]) for r in entries(kind="flow")
        if r.get("measured") and r.get("used") and r.get("ok", True) and r.get("scene") is not None
    ]
    if len(values) < 3:
        return None
    return float(statistics.median(values))


# ------------------------------------------------------------------ รายงาน

def report_text(days: int = 30) -> str:
    """สรุปสั้นสำหรับส่งเข้า Telegram หรือโชว์บนหน้าเว็บ"""
    data = summary(days=days)
    if not data["entries"]:
        return f"📒 <b>สมุดบัญชีต้นทุน</b>\nยังไม่มีรายการใน {days} วันที่ผ่านมา"

    lines = [f"📒 <b>ต้นทุน {days} วันล่าสุด</b>",
             f"รวม {data['used']:,.0f} · {data['items']} คลิป · {data['entries']} รายการ"]
    if data["wasted"]:
        share = data["wasted"] / data["used"] * 100 if data["used"] else 0
        lines.append(f"🔥 จ่ายเปล่ากับงานที่ล้ม {data['wasted']:,.0f} ({share:.0f}%)")
    if data["estimated"]:
        lines.append(f"⚠️ ในนี้เป็นตัวเลขประมาณ {data['estimated']:,.0f} (ไม่ได้วัดจากคงเหลือจริง)")
    if data["unknown_entries"]:
        lines.append(f"⚠️ อีก {data['unknown_entries']} รายการวัดยอดไม่ได้")
    for kind, slot in sorted(data["by_kind"].items(), key=lambda x: -x[1]["used"]):
        label, unit = KINDS.get(kind, KINDS["other"])
        lines.append(f"  • {label} {slot['used']:,.0f} {unit} ({slot['count']} ครั้ง)")

    balance, at = latest_credits()
    if balance is not None:
        lines.append(f"คงเหลือที่จดไว้ล่าสุด {balance:,.0f} เครดิต (เมื่อ {at})")
    return "\n".join(lines)


# --------------------------------------------------------------------- CLI

def _cli(argv: list[str]) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    action = argv[0] if argv else "summary"

    if action == "summary":
        days = int(argv[1]) if len(argv) > 1 else 30
        text = report_text(days).replace("<b>", "").replace("</b>", "")
        print(text)
    elif action == "item":
        if len(argv) < 2:
            print("ต้องใส่ item_id"); return 2
        data = by_item(argv[1])
        print(f"{argv[1]} — ใช้ {data['used']:,.0f} · จ่ายเปล่า {data['wasted']:,.0f} "
              f"· {data['entries']} รายการ")
        for row in data["rows"]:
            mark = "✅" if row.get("ok", True) else "❌"
            scene = f" ฉาก {row['scene']}" if row.get("scene") is not None else ""
            amount = "?" if row.get("used") is None else f"{row['used']:,.0f}"
            tag = "" if row.get("measured") else " (ประมาณ)"
            print(f"  {mark} {row['at']} {row['kind']}{scene} → {amount}{tag} "
                  f"{row.get('note', '')}")
    elif action == "tail":
        limit = int(argv[1]) if len(argv) > 1 else 20
        for row in entries()[-limit:]:
            print(json.dumps(row, ensure_ascii=False))
    elif action == "where":
        print(LEDGER_PATH)
    else:
        print("ใช้: python cost_ledger.py [summary [วัน] | item <item_id> | tail [n] | where]")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli(sys.argv[1:]))
