"""เจ้าหน้าที่คิว — ตัดสินว่าแชทไหนได้แก้ไฟล์ไหนก่อน

**ทำไมต้องมี** `file_claims.py` มีมาก่อนแล้วและใช้ได้จริง แต่วัดเมื่อ 18 ส.ค. 2026
พบว่า `claims: 0` ทั้งที่มีแชทอื่นแก้ `fb_mass_bot.py` ไปเมื่อ 11 นาทีก่อนและแก้
`fb_posts_probe.py` เมื่อ 2.8 นาทีก่อน — แปลว่าเครื่องมือไม่ได้พัง แต่**ไม่มีใครจำได้ว่า
ต้องจอง** และไม่มีใครตัดสินว่าใครก่อนใครหลัง

ไฟล์นี้เลยแยกหน้าที่ออกเป็นสองชั้น:

    ด่าน (guard)      เด้งเองทุกครั้งที่แชทจะแก้ไฟล์ ผ่าน PreToolUse hook
                      ไม่ต้องพึ่งความจำใคร — ว่างก็จองให้เงียบๆ ไม่ว่างก็หยุดไว้
    เจ้าหน้าที่ (ask)  ตัดสินตอนชนกันจริง ว่าใครแซงใครได้ ใครต้องรอ

**กติกาตัดสิน** (ผู้ใช้เลือกไว้ 18 ส.ค. 2026)
  1. ของพังมาก่อน — งาน `fix` แซงงาน `feat` ได้
  2. เสมอกันแล้วใครขอก่อนได้ก่อน
  3. เจ้าหน้าที่ตัดสินเองได้เลย ผู้ใช้เข้ามาเฉพาะตอนอุทธรณ์

**ด่านต้องไม่ทำให้ทุกแชทติดตาย** ทุกทางที่ผิดคาดคือ "ปล่อยผ่าน" ไม่ใช่ "บล็อก"
โค้ดพัง · อ่าน stdin ไม่ออก · ไฟล์อยู่นอกโปรเจกต์ → ผ่านหมด เพราะด่านที่บล็อก
ผิดพลาดจะทำให้ทุกแชทแก้อะไรไม่ได้เลย ซึ่งแย่กว่าการปล่อยให้ชนกันบางครั้งมาก
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import file_claims
import studio_shared

BASE_DIR = file_claims.BASE_DIR
NAMES_FILE = studio_shared.DATA_DIR / "chat_names.json"

# แก้ไฟล์ไว้ภายในกี่นาที ถือว่า "ยังนั่งทำอยู่" — ใช้ตอนรายงานว่าคนถือทิ้งงานไปหรือยัง
FRESH_MINUTES = 20

# งานประเภทไหนแซงใครได้ (มากกว่า = แซงได้)
RANK = {"fix": 2, "feat": 1, "": 1}

# ข้อความที่ด่านใช้จองแทนเจ้าตัว — ใช้แยกว่าเป็นการจอง "โดยตั้งใจ" หรือ "โดยด่าน"
AUTO_WHY = "แก้ผ่านด่านอัตโนมัติ"

# การจองที่ด่านทำให้เองเป็นสัญญาณอ่อนกว่าการมาขอเอง จึงถือว่าทิ้งงานเร็วกว่า
# ไม่งั้นแชทที่แก้ไฟล์ครั้งเดียวแล้วไปทำอย่างอื่น จะล็อกไฟล์ไว้เต็ม 25 นาที
AUTO_ABANDON_MINUTES = 10

# ด่านไม่ยุ่งกับพวกนี้ — เป็นข้อมูล ไม่ใช่โค้ดที่คนสองคนจะแก้ชนกัน
SKIP_PARTS = {".git", "__pycache__", "node_modules", ".claude"}
SKIP_DIRS = {"data", "data-test", "logs"}
SKIP_SUFFIX = {".lock", ".log", ".json.tmp"}


# --------------------------------------------------------------- ตัวตน

def _names() -> dict:
    return studio_shared.read_json(NAMES_FILE, {}) or {}


def name_for(session: str) -> str:
    """sessionId → ชื่อที่คนอ่านรู้เรื่อง

    ด่านรู้จักแชทจาก sessionId ที่ Claude Code ส่งมาให้เท่านั้น ถ้ายังไม่เคย
    ตั้งชื่อไว้ก็ใช้ตัวย่อไปก่อน ดีกว่าปล่อยเป็นค่าว่างแล้วทุกแชทกลายเป็นคนเดียวกัน
    """
    session = (session or "").strip()
    if session:
        known = _names().get(session)
        if known:
            return known
    from_env = os.environ.get("STUDIO_CHAT", "").strip()
    if from_env:
        return from_env
    return f"แชท {session[:8]}" if session else "แชทไม่ทราบชื่อ"


def remember_name(session: str, label: str) -> None:
    def change(data: dict) -> None:
        data[session] = label

    studio_shared.update_json(NAMES_FILE, change, default={},
                              label="ตั้งชื่อแชท")


# ----------------------------------------------------------- ขอบเขตด่าน

def in_scope(path: str) -> str | None:
    """ไฟล์นี้อยู่ในความดูแลไหม — คืน path แบบสัมพัทธ์ ถ้าไม่ใช่คืน None

    ด่านติดตั้งระดับผู้ใช้ (ใช้กับทุกโปรเจกต์) จึงต้องกันไม่ให้ไปยุ่งกับงานอื่น
    ของผู้ใช้ที่ไม่เกี่ยวกับ pipeline studio เลย
    """
    raw = str(path or "").strip().strip('"')
    if not raw:
        return None            # ไม่มีพาธมาด้วย = ไม่ใช่การแก้ไฟล์ ไม่ต้องยุ่ง
    try:
        full = Path(raw).resolve()
        rel = full.relative_to(BASE_DIR).as_posix()
    except (ValueError, OSError):
        return None
    # `Path("").resolve()` คืนโฟลเดอร์ปัจจุบัน ซึ่งกลายเป็น "." แล้วด่านจะไปจอง
    # ทั้งโปรเจกต์เป็นไฟล์ชื่อ "." — กันไว้ตรงนี้ รวมถึงกรณีชี้มาที่โฟลเดอร์ด้วย
    if rel in ("", ".") or full.is_dir():
        return None
    parts = rel.split("/")
    if parts[0] in SKIP_DIRS or set(parts) & SKIP_PARTS:
        return None
    if any(rel.endswith(suffix) for suffix in SKIP_SUFFIX):
        return None
    return rel


# ------------------------------------------------------------ ตัวตัดสิน

def _touched_ago(rel: str) -> float | None:
    when = file_claims.file_touched(rel)
    if when is None:
        return None
    return (datetime.now() - when).total_seconds() / 60


def _left_minutes(claim: dict) -> float | None:
    ends = file_claims._parse(claim.get("expires", ""))
    if ends is None:
        return None
    return (ends - datetime.now()).total_seconds() / 60


def peek(rel: str) -> dict | None:
    """ใครถือไฟล์นี้อยู่ — อ่านจากไฟล์ข้อมูลตรงๆ ไม่แตะ git

    ด่านทำงานทุกครั้งที่แชทกด Edit ถ้าเรียก `status()` ตรงนี้จะได้ subprocess git
    เพิ่ม 4 ตัวต่อการแก้หนึ่งครั้ง ซึ่งแพงเกินไปสำหรับทางที่วิ่งบ่อยที่สุด —
    กรณีปกติคือ "ไฟล์นี้เราถืออยู่แล้ว" ซึ่งตอบได้จากไฟล์ข้อมูลอย่างเดียว

    แลกมาด้วยการไม่ได้เก็บกวาดการจองหมดอายุให้ จึงต้องเช็คหมดอายุเองตรงนี้
    (ตัวเก็บกวาดจริงจะทำงานตอน claim/release รอบถัดไป)
    """
    held = (file_claims._load()["claims"] or {}).get(rel)
    if not held:
        return None
    if file_claims._expired(held) and not file_claims._still_working(rel, held):
        return None
    return held


def abandoned(rel: str, held: dict) -> bool:
    """คนถืออยู่ทิ้งงานไปแล้วไหม — ดูจากว่าไฟล์ไม่ขยับมานานแค่ไหน"""
    ago = _touched_ago(rel)
    if ago is None:
        return False
    limit = (AUTO_ABANDON_MINUTES if held.get("why") == AUTO_WHY
             else file_claims.ACTIVE_MINUTES)
    return ago > limit


def _busy_note(rel: str, claim: dict) -> str:
    """บรรยายว่าคนถืออยู่ยังทำอยู่จริงไหม — เอาไว้ให้คนอ่านตัดสินใจต่อได้"""
    ago = _touched_ago(rel)
    left = _left_minutes(claim)
    bits = []
    if ago is None:
        bits.append("ยังไม่เคยแตะไฟล์")
    elif ago <= FRESH_MINUTES:
        bits.append(f"ยังทำอยู่จริง (แตะเมื่อ {ago:.0f} นาทีก่อน)")
    else:
        bits.append(f"ไม่แตะไฟล์มา {ago:.0f} นาที")
    if left is not None:
        bits.append(f"เหลือเวลาถือ {left:.0f} นาที")
    return " · ".join(bits)


def decide(rel: str, me: str, kind: str) -> dict:
    """หัวใจของเจ้าหน้าที่ — คืนคำตัดสินหนึ่งข้อ

    ค่า `verdict` เป็นได้ 4 อย่าง: go · mine · take · wait
    """
    info = file_claims.status(rel)
    holder = info.get("claim")
    if not holder:
        return {"verdict": "go", "file": rel, "handovers": info.get("handovers") or []}
    if holder.get("chat") == me:
        return {"verdict": "mine", "file": rel, "holder": holder}

    outranks = RANK.get(kind, 1) > RANK.get(holder.get("kind", ""), 1)
    gone = abandoned(rel, holder)

    if outranks or gone:
        ago = _touched_ago(rel)
        return {"verdict": "take", "file": rel, "holder": holder,
                "why_take": "งานซ่อมของพังมาก่อน" if outranks else
                            f"คนถือไม่แตะไฟล์มา {ago:.0f} นาที ถือว่าทิ้งงานแล้ว"}
    return {"verdict": "wait", "file": rel, "holder": holder,
            "queue": info.get("queue") or []}


# ------------------------------------------------------------ ด่านอัตโนมัติ

def guard(raw: str) -> int:
    """เรียกจาก PreToolUse hook — คืน 0 = ให้แก้ต่อ, 2 = หยุดไว้

    รับ JSON ของ Claude Code ทาง stdin ตัวที่ใช้จริงคือ `tool_input.file_path`
    กับ `session_id`
    """
    try:
        payload = json.loads(raw or "{}")
    except (ValueError, TypeError):
        return 0                      # อ่านไม่ออก = ไม่ใช่เรื่องของเรา ปล่อยผ่าน

    tool_input = payload.get("tool_input") or {}
    target = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
    rel = in_scope(target)
    if not rel:
        return 0

    session = str(payload.get("session_id") or "")
    me = name_for(session)
    # ---- ชั้นที่ 1: ข้อพิพาทระดับ "คำสั่ง" ต้องตัดสินก่อนถึงจะแตะไฟล์ได้ ----
    # ล็อกไฟล์กันได้แค่ "สองคนเขียนทับกัน" แต่กันไม่ได้เลยเวลาเจ้าของสั่งสองแชท
    # ให้ทำสิ่งที่สวนทางกัน ตรงนั้นต้องมีคนชี้ขาดก่อน ไม่ใช่แค่เข้าคิว
    #
    # import ตรงนี้ไม่ใช่บนหัวไฟล์ เพราะ orders.py import dispatcher อยู่แล้ว
    # ถ้า import กลับบนหัวจะวนกันตายตั้งแต่โหลดโมดูล
    try:
        import orders
        dispute = orders.pending(session, rel)
    except Exception:              # noqa: BLE001 - สมุดคำสั่งพังห้ามลามมาบล็อกการแก้ไฟล์
        dispute = None
    if dispute:
        other = (dispute.get("with") or [{}])[0]
        print(chr(10).join([
            "🛑 " + rel + " ติดข้อพิพาทที่ยังไม่มีใครตัดสิน — แก้ไม่ได้ตอนนี้",
            '   ชนกับ "' + str(other.get("chat")) + '" ที่ถูกสั่งให้: '
            + str(other.get("text") or "")[:110],
            "",
            "   เจ้าของโปรเจกต์สั่งไว้แล้วว่ากรณีนี้ให้เรียกเจ้าหน้าที่เองอัตโนมัติ:",
            '   เรียก Agent tool ด้วย subagent_type="dispatcher" เดี๋ยวนี้',
            "   ให้มันตอบว่าสองคำสั่งนี้รวมกันได้หรือขัดกันเอง แล้วสั่งปลดล็อกด้วย",
            '     python orders.py resolve --session ' + session + ' --note "คำตัดสิน"',
        ]), file=sys.stderr)
        return 2
    holder = peek(rel)

    if holder is None:
        # ว่างอยู่ก็จองให้เงียบๆ — ตรงนี้แหละที่แก้ปัญหา "ไม่มีใครจำได้ว่าต้องจอง"
        file_claims.claim(rel, me, why=AUTO_WHY, session=session)
        return 0
    if holder.get("chat") == me:
        return 0                      # ของเราอยู่แล้ว ปล่อยผ่านทันที ไม่ต้องแตะ git
    if abandoned(rel, holder):
        # ต้อง force ไม่งั้น claim() จะพาไปต่อคิวเงียบๆ แล้วเราปล่อยให้แก้ทับ
        file_claims.claim(rel, me, why=AUTO_WHY, session=session, force=True)
        return 0
    why = holder.get("why") or ""
    lines = [
        f"⛔ {rel} มีคนแก้อยู่ — \"{holder.get('chat')}\"",
        f"   {'ยังไม่ได้บอกว่าทำอะไร (ด่านจองให้ตอนเขาเริ่มแก้)' if why == AUTO_WHY else why or 'ไม่ได้บอกว่าทำอะไร'}",
        f"   {_busy_note(rel, holder)}",
        "",
        "   ถ้างานคุณคือซ่อมของพัง แซงได้:",
        f"     python dispatcher.py ask {rel} --fix --why \"...\"",
        "   ถ้าไม่ใช่ ให้ต่อคิวแล้วไปทำอย่างอื่นก่อน:",
        f"     python dispatcher.py ask {rel} --why \"...\"",
    ]
    print("\n".join(lines), file=sys.stderr)
    return 2


# ------------------------------------------------------------- กระดาน

def board() -> int:
    """ภาพรวมหน้าเดียว — ใครถืออะไร ใครรอ และใครแก้อยู่โดยไม่จอง"""
    data = file_claims.listing()
    claims, queue = data["claims"], data["queue"]

    if claims:
        print("🔒 ถืออยู่")
        for rel, held in claims.items():
            mark = "🔧" if held.get("kind") == "fix" else "  "
            print(f"  {mark} {rel:34s} {held.get('chat','?'):22s} {_busy_note(rel, held)}")
            print(f"       {held.get('why') or ''}")
    else:
        print("🟢 ไม่มีใครถือไฟล์ไหนอยู่")

    waiting = {rel: rows for rel, rows in queue.items() if rows}
    if waiting:
        print("\n⏳ รอคิว")
        for rel, rows in waiting.items():
            for i, row in enumerate(rows, 1):
                print(f"     {rel:34s} คิว {i}: {row.get('chat','?')} — {row.get('why') or ''}")

    loose = unclaimed(claims)
    if loose:
        print("\n⚠️  แก้อยู่โดยไม่ได้จอง — ตรงนี้คือจุดที่เดิมมองไม่เห็น")
        for ago, rel in loose:
            print(f"     {rel:34s} แก้เมื่อ {ago:.0f} นาทีก่อน")

    file_claims._print_handovers(data)
    return 0


def unclaimed(claims: dict) -> list[tuple[float, str]]:
    """ไฟล์ที่เพิ่งถูกแก้แต่ไม่มีใครจอง

    ดูจาก git ว่ามีอะไรเปลี่ยนบ้าง แล้วกรองด้วยเวลาแก้ล่าสุด — จับได้แม้แชทนั้น
    จะไม่เคยเรียกเครื่องมือนี้เลยสักครั้ง เพราะ mtime ไม่ต้องขอความร่วมมือจากใคร
    """
    changed = file_claims._git("status", "--porcelain")
    found = []
    for line in changed.splitlines():
        raw = line[3:].strip().strip('"')
        rel = in_scope(str(BASE_DIR / raw))
        if not rel or rel in claims:
            continue
        ago = _touched_ago(rel)
        if ago is not None and ago <= FRESH_MINUTES:
            found.append((ago, rel))
    return sorted(found)


# ------------------------------------------------------------ คำสั่งมือ

def ask(rel: str, me: str, why: str, kind: str, session: str) -> int:
    call = decide(rel, me, kind)
    verdict = call["verdict"]

    if verdict in ("go", "mine"):
        file_claims.claim(rel, me, why, session, kind=kind)
        word = "ต่ออายุให้แล้ว" if verdict == "mine" else "ว่างอยู่ จองให้แล้ว"
        print(f"✅ เอาเลย — {rel} {word}")
        return 0

    holder = call["holder"]
    if verdict == "take":
        file_claims.claim(rel, me, why, session, force=True, kind=kind)
        print(f"🔧 คุณแซงได้ — {rel} ยึดมาให้แล้ว")
        print(f"   เหตุผล: {call['why_take']}")
        print(f"   คนที่โดนแซง: \"{holder.get('chat')}\" — {holder.get('why') or ''}")
        print(f"   ⚠️ ไปบอกเขาด้วยว่าโดนแซงเพราะอะไร อย่าให้รู้ตอนงานหาย")
        return 0

    out = file_claims.claim(rel, me, why, session, kind=kind)
    print(f"⏳ รอก่อน — {rel} ถืออยู่โดย \"{holder.get('chat')}\"")
    print(f"   {holder.get('why') or 'ไม่ได้บอกว่าทำอะไร'}")
    print(f"   {_busy_note(rel, holder)}")
    print(f"   คุณอยู่คิวที่ {out.get('position', '?')} — ว่างเมื่อไรจะมีสัญญาณส่งมา")
    return 1


def done(rel: str, me: str, note: str) -> int:
    out = file_claims.release(rel, me, note)
    if not out.get("ok"):
        print(f"⚠️ คืน {rel} ไม่ได้ — {out.get('reason') or 'ไม่ทราบสาเหตุ'}")
    else:
        print(f"✅ คืน {rel} แล้ว")
    for hand in out.get("handovers") or []:
        print(f"   ➡️ ยกให้ \"{hand.get('chat')}\" ต่อแล้ว")
    nxt = out.get("next")
    if nxt:
        print(f"   ➡️ คิวถัดไป: \"{nxt.get('chat')}\" — {nxt.get('why') or ''}")
        print(f"      ไปบอกเขาว่าว่างแล้ว (sessionId: {nxt.get('session') or 'ไม่ได้ให้ไว้'})")
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
        description="เจ้าหน้าที่คิว — ตัดสินว่าแชทไหนได้แก้ไฟล์ไหนก่อน")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("guard", help="ใช้โดย hook เท่านั้น — รับ JSON ทาง stdin")
    sub.add_parser("board", help="ดูภาพรวมหน้าเดียว")

    p_name = sub.add_parser("name", help="ตั้งชื่อแชทนี้ให้คนอ่านรู้เรื่อง")
    p_name.add_argument("label")
    p_name.add_argument("--session", default=os.environ.get("STUDIO_SESSION", ""))

    for word, help_text in (("ask", "ขอแก้ไฟล์"), ("done", "แก้เสร็จแล้ว คืนคิว")):
        p = sub.add_parser(word, help=help_text)
        p.add_argument("file")
        p.add_argument("--chat", default=os.environ.get("STUDIO_CHAT", ""))
        p.add_argument("--session", default=os.environ.get("STUDIO_SESSION", ""))
        p.add_argument("--why", default="")
        if word == "ask":
            p.add_argument("--fix", action="store_true",
                           help="งานนี้คือซ่อมของพัง — แซงงานเพิ่มฟีเจอร์ได้")
        else:
            p.add_argument("--note", default="")

    args = parser.parse_args(argv)

    if args.command == "guard":
        try:
            return guard(_read_stdin())
        except Exception as error:          # noqa: BLE001 - ด่านห้ามล้มแล้วบล็อก
            print(f"(เจ้าหน้าที่คิวมีปัญหา จึงปล่อยผ่าน: {error})", file=sys.stderr)
            return 0

    if args.command == "board":
        return board()

    if args.command == "name":
        if not args.session:
            print("❌ ต้องบอก --session ด้วย (หรือตั้ง STUDIO_SESSION)")
            return 2
        remember_name(args.session, args.label)
        print(f"✅ จำแล้ว — session {args.session[:8]} คือ \"{args.label}\"")
        return 0

    rel = in_scope(args.file) or file_claims.normalise(args.file)
    me = args.chat.strip() or name_for(args.session)
    if me == "แชทไม่ทราบชื่อ":
        print("❌ ไม่รู้ว่าคุณเป็นแชทไหน — ใส่ --chat \"ชื่อ\" หรือตั้ง STUDIO_CHAT")
        return 2

    if args.command == "ask":
        return ask(rel, me, args.why, "fix" if args.fix else "feat", args.session)
    return done(rel, me, args.note)


if __name__ == "__main__":
    raise SystemExit(main())
