"""สมุดคำสั่ง — จดว่าเจ้าของโปรเจกต์สั่งแชทไหนทำอะไรไว้บ้าง

**ทำไมต้องมี ทั้งที่มี `dispatcher.py` แล้ว**

`dispatcher.py` กันได้แค่ "สองแชทเขียนทับไฟล์เดียวกัน" ซึ่งเป็นการชนแบบเห็นตัว
แต่การชนที่แพงกว่าคือ **คำสั่งที่ขัดกันเองโดยไม่แตะไฟล์เดียวกันเลย**

    แชท A ถูกสั่ง: "ลด polling ให้เหลือน้อยที่สุด"
    แชท B ถูกสั่ง: "เพิ่มแถบสถานะสด อัปเดตทุกวินาที"

คนละไฟล์ก็ได้ ด่านปล่อยผ่านทั้งคู่ ต่างคนต่างทำสำเร็จ ไม่มีใครทำผิดสักคน —
แต่ผลรวมขัดกับสิ่งที่เจ้าของสั่ง และไม่มีใครรู้ตัวจนกว่าจะเห็นของจริง

จะเทียบผลกับคำสั่งได้ **ต้องมีที่เก็บคำสั่งก่อน** ไฟล์นี้คือที่เก็บนั้น

**จดเองผ่าน `UserPromptSubmit` hook** ไม่ต้องให้แชทไหนจำว่าต้องลงทะเบียน —
บทเรียนจากตอนที่ `file_claims.py` มีครบทุกอย่างแต่ `claims: 0` เพราะต้องพึ่งความจำ

**ข้อความที่ผู้ใช้พิมพ์เก็บไว้ใน `data/` ซึ่ง gitignore ไว้แล้ว** ไม่มีทางหลุดขึ้น repo

**hook นี้ห้ามขวางไม่ให้ผู้ใช้พิมพ์เด็ดขาด** ทุกทางที่ผิดคาดคือเงียบแล้วปล่อยผ่าน
ถ้าไฟล์นี้พังแล้วไปบล็อกข้อความ ผู้ใช้จะคุยกับแชทไม่ได้เลย ซึ่งแย่กว่าไม่มีสมุดคำสั่ง
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime

import dispatcher
import file_claims
import studio_shared

ORDERS_FILE = studio_shared.DATA_DIR / "orders.json"

# ข้อความสั้นกว่านี้ถือว่าเป็นการตอบรับ ไม่ใช่คำสั่งใหม่ ("เอาเลย" "ok" "ทำต่อ")
# ถ้าปล่อยให้ทับ หัวข้องานจะกลายเป็น "เอาเลย" แล้วอ่านไม่รู้เรื่องว่ากำลังทำอะไรอยู่
MIN_ORDER_CHARS = 14

# คำตอบรับที่ยาวเกิน MIN_ORDER_CHARS ก็ยังไม่ใช่คำสั่งใหม่
ACK_WORDS = {"เอาเลย", "ทำเลย", "ทำต่อ", "ต่อเลย", "โอเค", "ok", "okay", "ได้",
             "ใช่", "ถูกต้อง", "ครับ", "จ้า", "ultrathink", "ไปต่อ"}

# งานที่ไม่มีความเคลื่อนไหวเกินเท่านี้ ถือว่าจบไปแล้ว ไม่เอามาเตือนว่าชน
STALE_MINUTES = 180

HISTORY_LIMIT = 12
TEXT_LIMIT = 1500

_FILE_RE = re.compile(r"\b[\w][\w./-]*\.(?:py|js|json|md|html|css|bat|txt)\b")


def _now() -> datetime:
    return datetime.now()


def _stamp(when: datetime) -> str:
    return when.isoformat(timespec="seconds")


def _parse(text: str) -> datetime | None:
    try:
        return datetime.fromisoformat(str(text))
    except (TypeError, ValueError):
        return None


def _ago_minutes(text: str) -> float | None:
    when = _parse(text)
    return None if when is None else (_now() - when).total_seconds() / 60


def files_in(text: str) -> list[str]:
    """ดึงชื่อไฟล์ที่ถูกพูดถึงในคำสั่ง

    ตั้งใจให้จับแบบตรงตัวเท่านั้น (ต้องมีนามสกุลไฟล์) เพราะการเดาจากคำทั่วไป
    จะเตือนผิดบ่อยจนคนเลิกอ่าน — เตือนน้อยแต่แม่น ดีกว่าเตือนมากแล้วถูกเมิน
    """
    found = {m.group(0) for m in _FILE_RE.finditer(text or "")}
    return sorted(f for f in found if len(f) > 3)


def _blank() -> dict:
    return {"orders": {}}


def _load() -> dict:
    data = studio_shared.read_json(ORDERS_FILE, None)
    if not isinstance(data, dict) or not isinstance(data.get("orders"), dict):
        return _blank()
    return data


def held_by(chat: str) -> list[str]:
    """ไฟล์ที่แชทนี้จองไว้จริงตอนนี้ — เอามาจากสมุดจองของ dispatcher"""
    claims = file_claims._load()["claims"]
    return sorted(rel for rel, held in claims.items() if held.get("chat") == chat)


# ข้อความที่ระบบยัดเข้ามาเอง ไม่ใช่คำสั่งจากเจ้าของ — ถ้าปล่อยให้จด หัวข้องานจะ
# กลายเป็น "<task-notification>..." ซึ่งอ่านไม่รู้เรื่องและทำให้กระดานสรุปเพี้ยน
#
# `<cross-session-message` เพิ่ม 22 ส.ค. 2569 — ข้อความที่แชทหนึ่งส่งไปหาอีกแชท
# **ไม่ใช่คำสั่งจากเจ้าของ** แต่เดิมถูกจดเป็นคำสั่งงานจริงของแชทที่รับ แล้วระบบ
# ไล่จับชื่อไฟล์จากเนื้อความมาตั้งเป็น "ไฟล์ที่แชทนั้นกำลังทำอยู่" ทั้งที่ไม่เคยแตะ
# ผลคือด่านปักธง "งานชนกัน" ปลอมๆ แล้วล็อกไฟล์ทิ้ง ต้องเรียกเจ้าหน้าที่มาปลดทุกครั้ง
# (รอบละ 40,000-110,000 โทเคน) — วัดจริง 22 ส.ค.: คู่เดียวเกิดซ้ำ 6 รอบในวันเดียว
# และ 3 ใน 13 รายการในทะเบียนเป็นของปลอมที่เกิดจากเหตุนี้
_SYSTEM_MARKS = ("<task-notification", "<system-reminder", "<local-command",
                 "<command-name", "<user-prompt-submit-hook",
                 "<cross-session-message")


def _is_system(text: str) -> bool:
    head = (text or "").strip()[:400].lower()
    return any(mark in head for mark in _SYSTEM_MARKS)


def _is_ack(text: str) -> bool:
    plain = (text or "").strip().strip("?!.ๆ ").lower()
    if _is_system(plain):
        return True
    return len(plain) < MIN_ORDER_CHARS or plain in ACK_WORDS


def record(session: str, chat: str, prompt: str) -> dict:
    """จดคำสั่งล่าสุดของแชทนี้ แล้วคืนรายการที่อาจชนกับคนอื่น"""
    prompt = (prompt or "").strip()[:TEXT_LIMIT]
    mine: dict = {}

    def change(data: dict) -> None:
        book = data.setdefault("orders", {})
        row = book.setdefault(session, {
            "chat": chat, "text": "", "history": [], "files": [],
            "opened": _stamp(_now()), "status": "open",
        })
        row["chat"] = chat or row.get("chat") or ""
        row["updated"] = _stamp(_now())
        row["status"] = "open"
        if prompt and not _is_ack(prompt):
            if row.get("text"):
                row.setdefault("history", []).append(row["text"])
                row["history"] = row["history"][-HISTORY_LIMIT:]
            row["text"] = prompt
            # **ต้องอยู่ในเงื่อนไขเดียวกับหัวข้องาน** (ย้ายเข้ามา 22 ส.ค. 2569)
            #
            # เดิมสองบรรทัดนี้อยู่นอกเงื่อนไข จึงทำงานกับ *ทุก* ข้อความที่เข้ามา
            # ต่อให้ระบบรู้แล้วว่าเป็นข้อความแจ้งเตือน/ข้ามแชท (ไม่ใช่คำสั่ง) มันก็ยัง
            # ไล่จับชื่อไฟล์จากเนื้อความมาใส่ "ไฟล์ที่กำลังทำ" อยู่ดี — แค่กรองที่
            # `_SYSTEM_MARKS` อย่างเดียวจึงไม่พอ นี่คือจุดที่ทำให้เกิดข้อพิพาทปลอมจริง
            #
            # ตัวอย่างที่เกิดจริง: แชทหนึ่งส่งข้อความ *รายงานบั๊กนี้* มาให้อีกแชท
            # ในข้อความมีคำว่า clip_app.py เป็นตัวอย่างประกอบ ระบบจับไปตั้งเป็น
            # "ไฟล์ที่แชทนั้นกำลังทำ" แล้วปักธงชนกับคนที่แก้ clip_app.py อยู่จริง
            seen = set(row.get("files") or []) | set(files_in(prompt))
            row["files"] = sorted(seen)
        mine.update(row)

    studio_shared.update_json(ORDERS_FILE, change, default=_blank(),
                              label="จดคำสั่ง")
    return mine


def clashes(session: str) -> list[dict]:
    """งานของแชทอื่นที่ใช้ไฟล์ทับกับงานนี้

    ตรวจได้เฉพาะการทับที่ "เห็นตัว" คือใช้ไฟล์ร่วมกัน ส่วนคำสั่งที่ขัดกันเชิงความหมาย
    โดยไม่แตะไฟล์เดียวกัน โปรแกรมตัดสินเองไม่ได้ — ต้องให้ subagent `dispatcher`
    อ่านคำสั่งทั้งสองแล้วชี้ขาด ฟังก์ชันนี้จึงเป็นแค่ด่านแรก ไม่ใช่คำตอบสุดท้าย
    """
    book = _load()["orders"]
    me = book.get(session) or {}
    # **แยกสองตะกร้าออกจากกัน** (22 ส.ค. 2569) เดิมเทรวมเป็นก้อนเดียว ระบบจึงแยก
    # ไม่ออกว่าอันไหนคือข้อเท็จจริง อันไหนคือการเดา แล้วบล็อกเหมือนกันหมด
    #
    #   my_guess = เดาจากการอ่านชื่อไฟล์ในข้อความ — ผิดได้ตลอด เช่นสั่งว่า
    #              "อย่าไปแตะ app.py นะ" ก็ถูกจดว่ากำลังแก้ app.py
    #   my_held  = **ตอกบัตรเข้าแล้วยังไม่ตอกออก** — เป็นข้อเท็จจริง
    my_guess = set(me.get("files") or [])
    my_held = set(held_by(me.get("chat", "")))
    if not (my_guess | my_held):
        return []

    found = []
    for other_id, row in book.items():
        if other_id == session or row.get("status") != "open":
            continue
        idle = _ago_minutes(row.get("updated", ""))
        if idle is not None and idle > STALE_MINUTES:
            continue
        other_held = set(held_by(row.get("chat", "")))
        # ของจริง: อีกฝั่ง **ตอกบัตรเข้าไฟล์นั้นแล้วยังไม่ตอกออก** = เขาทำอยู่จริง
        # ถ้าเราเข้าไปแก้ด้วยคือเขียนทับกันแน่ → หยุดไว้ก่อน
        hard = (my_guess | my_held) & other_held
        # แค่พูดถึงกันทั้งคู่ ไม่มีใครตอกบัตรเข้าเลย → เตือนพอ ห้ามบล็อก
        soft = (my_guess & set(row.get("files") or [])) - hard
        if hard or soft:
            found.append({**row, "session": other_id,
                          "shared": sorted(hard or soft),
                          "hard": bool(hard), "idle": idle})
    return found


def mark_clash(me_session, me_chat, me_text, hits, shared):
    """ปักธงข้อพิพาทให้ทุกฝั่งที่เกี่ยวข้อง

    **แต่ละฝั่งต้องจดคู่กรณีของตัวเอง ไม่ใช่ชุดเดียวกันทั้งคู่** เคยเขียนผิดมาก่อน
    คือยัด summary ชุดเดียวกันลงทั้งสองฝั่ง ทำให้ฝั่ง A จดว่า "ชนกับ A" (ตัวเอง)
    แล้วตอนสั่งปลดจาก B จะหาฝั่ง A ไม่เจอ — A ติดค้างตลอดกาลโดยไม่มีใครรู้
    """
    def change(data):
        book = data.get("orders", {})
        stamp = _stamp(_now())

        def flag(row, partners):
            if row is not None:
                row["clash"] = {"shared": shared, "at": stamp,
                                "with": partners, "resolved": False}

        flag(book.get(me_session),
             [{"chat": h.get("chat"), "session": h.get("session"),
               "text": (h.get("text") or "")[:200]} for h in hits])
        mine = [{"chat": me_chat, "session": me_session,
                 "text": (me_text or "")[:200]}]
        for h in hits:
            flag(book.get(h.get("session")), mine)

    studio_shared.update_json(ORDERS_FILE, change, default=_blank(),
                              label="ปักธงงานชนกัน")

def pending(session, rel):
    """ไฟล์นี้ติดข้อพิพาทที่ยังไม่ตัดสินหรือเปล่า

    ด่านของ dispatcher เรียกตัวนี้ก่อนปล่อยให้แก้ — ตอบเฉพาะไฟล์ที่ทับกันจริง
    ไม่ได้หยุดทั้งแชท เพราะงานส่วนที่ไม่เกี่ยวข้องกันต้องเดินต่อได้
    """
    row = (_load()["orders"] or {}).get(session) or {}
    clash = row.get("clash") or {}
    if not clash or clash.get("resolved"):
        return None
    return clash if rel in (clash.get("shared") or []) else None


def resolve(session, note=""):
    """เจ้าหน้าที่ตัดสินแล้ว — ปลดล็อกให้ทั้งสองฝั่งทำงานต่อ"""
    hit = {"n": 0}

    def change(data):
        for sid, row in data.get("orders", {}).items():
            clash = row.get("clash") or {}
            if not clash or clash.get("resolved"):
                continue
            # ปลดพร้อมกันทั้งคู่ — ปลดข้างเดียวแล้วอีกข้างยังติด คือคำตัดสินครึ่งเดียว
            mine = sid == session
            theirs = any(w.get("session") == session for w in clash.get("with") or [])
            if mine or theirs:
                clash.update(resolved=True, decided_at=_stamp(_now()), note=note)
                hit["n"] += 1

    studio_shared.update_json(ORDERS_FILE, change, default=_blank(),
                              label="ปลดข้อพิพาท")
    if hit["n"]:
        print("ปลดข้อพิพาทแล้ว " + str(hit["n"]) + " ฝั่ง — ทั้งสองแชททำงานต่อได้")
    else:
        print("ไม่พบข้อพิพาทที่ค้างอยู่ของ session นี้")
    return 0


# ------------------------------------------------------------------ hook

def _prompt_from(payload):
    """ดึงข้อความที่ผู้ใช้พิมพ์ออกจาก payload ของ hook

    ลองหลายชื่อคีย์เพราะรูปแบบอาจเปลี่ยนตามเวอร์ชัน Claude Code — เดาผิดชื่อเดียว
    แล้วสมุดคำสั่งจะว่างเปล่าเงียบๆ ซึ่งแย่กว่าไม่มีสมุดเลย
    """
    for key in ("prompt", "user_prompt", "message", "text", "content", "input"):
        val = payload.get(key)
        if isinstance(val, str) and val.strip():
            return val
    return ""


def _note_unknown(payload):
    """จดว่า payload หน้าตายังไง ตอนที่หาข้อความไม่เจอ (อยู่ใน data/ ไม่ขึ้น git)"""
    try:
        shape = {k: (type(v).__name__ + ":" + str(v)[:60]) for k, v in payload.items()}

        def change(data):
            data.setdefault("seen", []).append({"at": _stamp(_now()), "shape": shape})
            data["seen"] = data["seen"][-10:]

        studio_shared.update_json(studio_shared.DATA_DIR / "orders_debug.json",
                                  change, default={"seen": []}, label="จดรูปแบบ payload")
    except Exception:              # noqa: BLE001 - ตัวช่วยไล่บั๊กห้ามทำ hook ล้ม
        pass


def catch(raw: str) -> int:
    """เรียกจาก UserPromptSubmit hook — คืน 0 เสมอ ห้ามขวางผู้ใช้"""
    payload = json.loads(raw or "{}")
    prompt = _prompt_from(payload)
    session = str(payload.get("session_id") or "")
    if not session:
        return 0
    if not prompt:
        # ไม่เจอข้อความในคีย์ที่รู้จัก — เก็บโครงของ payload ไว้ให้ไล่ทีหลัง
        # เคยพลาดมาแล้วคือเดาชื่อคีย์ผิดแล้วสมุดคำสั่งว่างเปล่าโดยไม่มีใครรู้
        _note_unknown(payload)

    chat = dispatcher.name_for(session)
    record(session, chat, prompt)

    hits = clashes(session)
    if not hits:
        return 0

    # ---- แค่พูดถึงไฟล์เดียวกัน ไม่มีใครตอกบัตรเข้า → เตือน ห้ามล็อก ----
    #
    # **ห้ามเรียก mark_clash() ทางนี้** เพราะนั่นคือตัวที่ปักธงแล้วทำให้ด่านตอน
    # แก้ไฟล์บล็อก — วัดจริง 22 ส.ค. 2569: คู่เดียวโดนบล็อกจากการเดา 6 รอบใน
    # วันเดียว ต้องเรียกเจ้าหน้าที่ทุกรอบ รอบละ 40,000-110,000 โทเคน
    # ทั้ง 6 รอบนั้นไม่มีใครตอกบัตรเข้าไฟล์นั้นเลยสักคน
    hard_hits = [row for row in hits if row.get("hard")]
    if not hard_hits:
        soft = sorted({f for row in hits for f in row["shared"]})
        who_else = " · ".join(dict.fromkeys(r.get("chat") or "?" for r in hits))
        print(f"⚠️ แชทอื่นพูดถึงไฟล์เดียวกัน: {' · '.join(soft)}  (แชท: {who_else})")
        print("   ยังไม่มีใครตอกบัตรเข้าไฟล์พวกนี้ — ทำงานต่อได้ตามปกติ")
        print("   ถ้าจะแก้ไฟล์เดียวกันจริง ด่านตอนแก้จะกันให้เองอีกชั้น")
        return 0

    hits = hard_hits
    shared = sorted({f for row in hits for f in row["shared"]})
    mine = (_load()["orders"] or {}).get(session) or {}
    mark_clash(session, chat, mine.get("text") or prompt, hits, shared)

    lines = ["🛑 หยุดก่อน — งานนี้ชนกับแชทอื่นที่กำลังทำอยู่", ""]
    for row in hits[:3]:
        idle = row.get("idle")
        when = f"ขยับล่าสุด {idle:.0f} นาทีก่อน" if idle is not None else "ไม่รู้เวลา"
        lines.append(f'   "{row.get("chat")}" ถูกสั่งให้: {(row.get("text") or "")[:110]}')
        lines.append(f"      ไฟล์ที่ทับกัน: {chr(183).join(row['shared'])} {when}")
    lines += [
        "",
        "**เจ้าของโปรเจกต์สั่งไว้แล้วว่ากรณีนี้ให้เรียกเจ้าหน้าที่เองอัตโนมัติ ไม่ต้องถามซ้ำ**",
        'ให้เรียก Agent tool ด้วย subagent_type="dispatcher" เดี๋ยวนี้ ก่อนทำอย่างอื่นทั้งสิ้น',
        "ส่งให้มันครบ 3 อย่าง: คำสั่งที่เพิ่งได้รับ / คำสั่งของอีกแชท / ไฟล์ที่ทับกัน",
        "แล้วให้มันตอบว่า **สองคำสั่งนี้รวมกันได้หรือขัดกันเอง** และใครทำก่อน",
        "",
        "ไฟล์ที่ทับกันจะแก้ไม่ได้จนกว่าเจ้าหน้าที่จะตัดสิน: " + ", ".join(shared),
    ]
    print(chr(10).join(lines))
    return 0


# ---------------------------------------------------------------- รายงาน

def who() -> int:
    """ใครทำอะไร ตรงไหน — รวมสามแหล่งเข้าด้วยกัน

    คำสั่งที่ได้รับ (สมุดนี้) + ไฟล์ที่จองไว้ (dispatcher) + ไฟล์ที่ขยับจริง (mtime)
    """
    book = _load()["orders"]
    rows = [(r.get("updated", ""), s, r) for s, r in book.items()
            if r.get("status") == "open"]
    if not rows:
        print("🟢 ยังไม่มีแชทไหนถูกสั่งงานค้างไว้")
        return 0

    for _, session, row in sorted(rows, reverse=True):
        idle = _ago_minutes(row.get("updated", ""))
        stale = idle is not None and idle > STALE_MINUTES
        mark = "💤" if stale else "👤"
        print(f"{mark} {row.get('chat') or 'ไม่ทราบชื่อ'}   (session {session[:8]})")
        print(f"   สั่งให้ทำ : {(row.get('text') or '(ยังไม่มีคำสั่งชัดเจน)')[:140]}")

        holding = held_by(row.get("chat", ""))
        if holding:
            bits = []
            for rel in holding:
                ago = dispatcher._touched_ago(rel)
                bits.append(f"{rel} ({ago:.0f} นาทีก่อน)" if ago is not None else rel)
            print(f"   ทำอยู่ที่ : {' · '.join(bits)}")
        else:
            mentioned = row.get("files") or []
            print(f"   ทำอยู่ที่ : {' · '.join(mentioned) if mentioned else 'ยังไม่ได้จับไฟล์ไหน'}")

        if idle is not None:
            print(f"   ขยับล่าสุด: {idle:.0f} นาทีก่อน" + ("  ← เงียบนานแล้ว" if stale else ""))
        print()

    pairs = []
    for session in book:
        for other in clashes(session):
            key = tuple(sorted([session, other["session"]]))
            if key not in [p[0] for p in pairs]:
                pairs.append((key, book[session].get("chat"), other))
    if pairs:
        print("⚠️ คู่ที่ใช้ไฟล์ทับกัน — ให้ subagent \"dispatcher\" ตัดสิน")
        for _, mine, other in pairs:
            print(f"   \"{mine}\"  ×  \"{other.get('chat')}\"  →  {' · '.join(other['shared'])}")
    return 0


def card(show_all: bool = False) -> int:
    """บัตรตอกเวลา — เข้าไฟล์ไหนเมื่อไร ออกหรือยัง (เจ้าของสั่ง 22 ส.ค. 2569)

    **กติกาข้อเดียวที่ต้องจำ**: มีเวลาเข้าแต่ยังไม่มีเวลาออก = คนนั้นยังทำไฟล์นั้นอยู่

    ข้อมูลมีอยู่แล้วครบใน `data/file_claims.json` (`since` คือเวลาเข้า · `released`
    คือเวลาออก · `how` คือออกเพราะอะไร) แค่ไม่เคยมีใครเอามาแสดงเป็นบัตรตอกเวลา
    และที่สำคัญกว่าคือ **ตัวตัดสินว่าชนกันไม่ได้ใช้ข้อมูลนี้เลย** — มันไปเดาจาก
    ชื่อไฟล์ในข้อความแทน ซึ่งเป็นต้นเหตุของข้อพิพาทปลอม 6 รอบในวันเดียว
    """
    book = file_claims._load()
    now = _now()

    def hhmm(text: str) -> str:
        when = file_claims._parse(text or "")
        return when.strftime("%H:%M") if when else "—"

    def span(start: str, end: str = "") -> str:
        first = file_claims._parse(start or "")
        last = file_claims._parse(end or "") if end else now
        if not first or not last:
            return ""
        minutes = (last - first).total_seconds() / 60
        return f"{minutes:.0f} นาที" if minutes < 90 else f"{minutes / 60:.1f} ชม."

    rows: dict[str, list[dict]] = {}
    for rel, held in (book.get("claims") or {}).items():
        rows.setdefault(held.get("chat") or "ไม่ทราบชื่อ", []).append(
            {"file": rel, "in": held.get("since", ""), "out": "", "how": ""})
    if show_all:
        for past in (book.get("history") or []):
            rows.setdefault(past.get("chat") or "ไม่ทราบชื่อ", []).append(
                {"file": past.get("file", ""), "in": past.get("since", ""),
                 "out": past.get("released", ""), "how": past.get("how", "")})

    if not rows:
        print("📋 ยังไม่มีใครตอกบัตรเข้าไฟล์ไหนเลย")
        return 0

    print("📋 บัตรตอกเวลา — ใครเข้าไฟล์ไหน ออกหรือยัง\n")
    working = 0
    for chat in sorted(rows):
        print(f"  {chat}")
        for item in sorted(rows[chat], key=lambda x: x["in"], reverse=True):
            if item["out"]:
                print(f"     ⚪ {item['file']:<26} เข้า {hhmm(item['in'])}  "
                      f"ออก {hhmm(item['out'])}  ({span(item['in'], item['out'])}"
                      + (f" · {item['how']}" if item["how"] else "") + ")")
            else:
                working += 1
                print(f"     🟢 {item['file']:<26} เข้า {hhmm(item['in'])}  "
                      f"ออก —      (ยังทำอยู่ {span(item['in'])})")
        print()
    print(f"รวมที่ยังทำอยู่ {working} ไฟล์"
          + ("" if show_all else "  ·  ใส่ --all เพื่อดูที่ตอกออกไปแล้วด้วย"))
    return 0


def close(session: str, note: str = "") -> int:
    done: dict = {}

    def change(data: dict) -> None:
        row = data.get("orders", {}).get(session)
        if not row:
            return
        row["status"] = "done"
        row["closed"] = _stamp(_now())
        row["note"] = note
        done.update(row)

    studio_shared.update_json(ORDERS_FILE, change, default=_blank(),
                              label="ปิดงาน")
    if done:
        print(f"✅ ปิดงานของ \"{done.get('chat')}\" แล้ว")
    else:
        print("⚠️ ไม่พบงานของ session นี้")
    return 0


def _read_stdin() -> str:
    """อ่าน stdin เป็น UTF-8 ตรงๆ ไม่ผ่าน locale ของเครื่อง

    Windows ตั้ง encoding ของ stdin ตาม ANSI codepage (cp874/cp1252) เมื่อไม่ได้ตั้ง
    PYTHONIOENCODING ไว้ — hook ของ Claude Code เรียก python ตรงๆ จึงไม่มีตัวแปรนั้น
    ผลคือข้อความไทยที่ผู้ใช้พิมพ์กลายเป็นขยะตั้งแต่ตอนอ่าน ก่อนถึงโค้ดเราด้วยซ้ำ

    เจอจริง 19 ส.ค. 2026 บนกระดานสรุปงาน:
        ที่พิมพ์  "ทำเป็น dash board สวยๆหน่อย"
        ที่เก็บได้ "à¸—à¸³à¹€à¸›à¹‡à¸™ dash board à¸ªà¸§à¸¢à¹†"

    อ่านเป็น bytes แล้ว decode เองจึงไม่ขึ้นกับ locale ของเครื่องเลย
    """
    try:
        return sys.stdin.buffer.read().decode("utf-8", errors="replace")
    except Exception:              # noqa: BLE001 - stdin แปลกๆ ห้ามทำให้ hook ล้ม
        try:
            return sys.stdin.read()
        except Exception:          # noqa: BLE001
            return ""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="สมุดคำสั่ง — ใครถูกสั่งให้ทำอะไร ทำถึงไหนแล้ว")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("catch", help="ใช้โดย hook เท่านั้น — รับ JSON ทาง stdin")
    sub.add_parser("who", help="ใครทำอะไร ตรงไหน")
    p_card = sub.add_parser("card", help="บัตรตอกเวลา — ใครเข้าไฟล์ไหนเมื่อไร ออกหรือยัง")
    p_card.add_argument("--all", action="store_true", help="เอาประวัติเก่ามาด้วย")

    p_close = sub.add_parser("close", help="ปิดงานของแชทนี้")
    p_close.add_argument("--session", required=True)
    p_close.add_argument("--note", default="")

    p_res = sub.add_parser("resolve", help="เจ้าหน้าที่ตัดสินแล้ว ปลดล็อกไฟล์ที่ชนกัน")
    p_res.add_argument("--session", required=True)
    p_res.add_argument("--note", default="")

    args = parser.parse_args(argv)

    if args.command == "catch":
        try:
            return catch(_read_stdin())
        except Exception:                  # noqa: BLE001 - ห้ามขวางผู้ใช้พิมพ์
            return 0
    if args.command == "who":
        return who()
    if args.command == "card":
        return card(args.all)
    if args.command == "resolve":
        return resolve(args.session, args.note)
    return close(args.session, args.note)


if __name__ == "__main__":
    raise SystemExit(main())
