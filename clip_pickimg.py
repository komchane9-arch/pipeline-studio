"""คัดรูปสินค้าด้วยเครื่องตัวเอง — ไม่ต้องพึ่งเครดิต Gemini

**เจ้าของสั่ง 30 ส.ค. 2569** — *"gemini ที่เลือกรูปผมอยากเปลี่ยนมาใช้ local Ai แทน"*
หลังเครดิต Gemini หมดทั้ง 4 ใบแล้วงานหยุดไป 17 ใบ

---

## ทำไมไม่ยัดทั้งกองให้ AI ตัวเดียวเหมือน Gemini

วัดจากของจริง: ส่งรูปครั้งละ **19–30 ใบ** (ส่วนใหญ่ 20–25)

รูปหนึ่งใบกินพื้นที่คิดของโมเดลราว 500–1,500 หน่วย × 25 ใบ = เกินที่การ์ดจอ
8 GB รับไหวในครั้งเดียว ต่อให้โมเดลเก่งแค่ไหนก็ยัดไม่ลง

**จึงแบ่งเป็นสองด่าน** — ด่านแรกตัดรูปซ้ำทิ้งด้วยวิธีที่ไม่ต้องใช้ AI เลย
ด่านสองค่อยให้ AI ดูเฉพาะรูปที่เหลือ

## ด่านแรก: ตัดรูปที่หน้าตาเกือบเหมือนกัน

ครึ่งหนึ่งของเกณฑ์ที่ Gemini ใช้คือ *"ห้ามเลือกรูปที่หน้าตาเกือบเหมือนกัน"*
ซึ่ง **ไม่ต้องเข้าใจภาพก็ทำได้** ใช้ลายนิ้วมือของภาพ (perceptual hash) เทียบกัน

วิธี: ย่อภาพเป็น 32×32 ขาวดำ → แปลงด้วย DCT → เอามุมซ้ายบน 8×8 ซึ่งเก็บ
โครงหยาบของภาพไว้ → เทียบว่าต่างกันกี่บิต

**ทำไมใช้ DCT ไม่ใช่ย่อภาพเฉยๆ** ย่อเฉยๆ จะไวต่อความสว่างและสีพื้นหลัง
รูปสินค้าตัวเดียวกันบนพื้นขาวกับพื้นครีมจะถูกมองว่าคนละรูป ส่วน DCT เก็บ
"รูปทรง" มากกว่า "สี" จึงจับรูปซ้ำได้ตรงกว่าสำหรับงานนี้

ไม่ต้องลง torch ไม่ต้องใช้การ์ดจอ ใช้ PIL กับ numpy ที่มีอยู่แล้ว

## ด่านสอง: ให้ AI ในเครื่องเลือกจากที่เหลือ

`ollama_pick()` คุยกับ Ollama ที่ `http://127.0.0.1:11434` ส่งทีละไม่กี่ใบ
ยังไม่มี Ollama ก็ใช้ด่านแรกอย่างเดียวได้ (`spread_pick` ของเดิมรับช่วงต่อ)

    python clip_pickimg.py compare            เทียบกับที่ Gemini เคยเลือก 10 ใบ
    python clip_pickimg.py compare --n 40     เทียบ 40 ใบ
    python clip_pickimg.py dedupe <โฟลเดอร์>  ดูว่าตัดรูปซ้ำได้เท่าไร
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

DATA_DIR = BASE_DIR / "data"
RUN_DIRS = ("shopee_products", "shopee_products_done", "clips", "waitclips",
            "waitstory", "clipsfb", "clipstiktok", "waitclipsfb", "waitclipstiktok")

# ต่างกันไม่เกินกี่บิตถึงเรียกว่า "รูปเดียวกัน" (จากลายนิ้วมือ 64 บิต)
#
# **วัดจากของจริง 20 สินค้า · รูป 431 ใบ · เทียบกับที่ Gemini เคยเลือก 76 ใบ**
#
#     บิต   เหลือ/สินค้า   ของ Gemini ที่รอด
#      8       19.8            98%
#     10       19.1            97%   ← เลือกค่านี้
#     12       18.4            94%
#     16       16.9            94%
#     20       14.2            84%   ← เริ่มทิ้งของดีเยอะ
#
# **ผลที่วัดได้หักล้างสมมติฐานตั้งต้น** — คิดว่ารูป Shopee ซ้ำกันเยอะจนตัดได้
# ครึ่งหนึ่ง ของจริงตัดได้แค่ 5–11% เพราะแต่ละใบโชว์คนละฟีเจอร์จริงๆ
#
# **ด่านนี้จึงเป็นตาข่ายกันรูปซ้ำ ไม่ใช่ตัวลดจำนวน** เลือก 10 เพราะได้ประโยชน์
# (ตัดซ้ำ 11%) โดยแทบไม่เสียของดี — ดันขึ้นไปอีกได้รูปน้อยลงนิดเดียว
# แต่เริ่มทิ้งรูปที่ Gemini เห็นว่าดี ซึ่งเสียหายกว่ามาก
SAME_BITS = 10

OLLAMA_URL = "http://127.0.0.1:11434"
OLLAMA_MODEL = "qwen2.5vl:7b"


def say(message: str) -> None:
    try:
        print(message, flush=True)
    except UnicodeEncodeError:
        sys.stdout.buffer.write((message + "\n").encode("utf-8", "replace"))


# --------------------------------------------------------- ลายนิ้วมือของภาพ


def fingerprint(path: Path) -> int | None:
    """ลายนิ้วมือ 64 บิตของภาพ — อ่านไม่ได้คืน None

    **คืน None ไม่ใช่ 0** เพราะ 0 คือลายนิ้วมือที่ถูกต้องของภาพสีเดียวทั้งใบ
    ถ้าใช้ 0 แทน "อ่านไม่ได้" ภาพที่เปิดไม่ได้จะถูกมองว่าเหมือนภาพขาวล้วน
    แล้วโดนตัดทิ้งไปพร้อมกัน (กติกาข้อ 2.3.1 ข้อ 4 — ยังไม่ได้ตรวจ ≠ ตรวจแล้ว)
    """
    try:
        import numpy as np                                       # noqa: PLC0415
        from PIL import Image                                    # noqa: PLC0415

        with Image.open(path) as image:
            small = image.convert("L").resize((32, 32), Image.LANCZOS)
            grid = np.asarray(small, dtype=float)
    except Exception:                                            # noqa: BLE001
        return None

    # DCT สองมิติแบบเขียนเอง — เลี่ยงการพึ่ง scipy ซึ่งเครื่องนี้ไม่ได้ลงไว้
    size = 32
    basis = np.cos(np.pi * (2 * np.arange(size)[:, None] + 1)
                   * np.arange(size)[None, :] / (2 * size))
    freq = basis.T @ grid @ basis
    block = freq[:8, :8].flatten()
    median = np.median(block[1:])            # ข้ามช่องแรกซึ่งเป็นความสว่างรวม
    bits = 0
    for index, value in enumerate(block):
        if value > median:
            bits |= 1 << index
    return bits


def distance(a: int, b: int) -> int:
    """ต่างกันกี่บิต"""
    return bin(a ^ b).count("1")


def dedupe(paths: list[Path], same_bits: int = SAME_BITS) -> list[Path]:
    """ตัดรูปที่หน้าตาเกือบเหมือนกันออก เก็บใบแรกของแต่ละกลุ่มไว้

    **อ่านไม่ได้ = เก็บไว้ ไม่ใช่ตัดทิ้ง** ตัดของที่ยังไม่ได้ตรวจคือการเดา
    ปล่อยผ่านเสียแค่มีรูปซ้ำหลุดไปให้ด่านสองคัดต่อ
    """
    kept: list[Path] = []
    marks: list[int] = []
    for path in paths:
        mark = fingerprint(path)
        if mark is None:
            kept.append(path)
            continue
        if any(distance(mark, seen) <= same_bits for seen in marks):
            continue
        kept.append(path)
        marks.append(mark)
    return kept


# ------------------------------------------------------ ด่านสอง: AI ในเครื่อง


def ollama_ready(model: str = OLLAMA_MODEL) -> str:
    """Ollama พร้อมใช้ไหม — คืนข้อความบอกปัญหา ว่างแปลว่าพร้อม

    ตรวจ **ของที่มีเฉพาะตอนพร้อม** คือมีโมเดลตัวที่ต้องใช้อยู่ในรายการจริง
    ไม่ใช่แค่ต่อพอร์ตติด (กติกาข้อ 2.3.1)
    """
    try:
        import httpx                                             # noqa: PLC0415

        reply = httpx.get(f"{OLLAMA_URL}/api/tags", timeout=5.0)
        if reply.status_code != 200:
            return f"Ollama ตอบ {reply.status_code}"
        names = [m.get("name", "") for m in reply.json().get("models", [])]
        if not any(n.split(":")[0] == model.split(":")[0] for n in names):
            return (f"ยังไม่มีโมเดล {model} — โหลดด้วย  ollama pull {model}"
                    + (f" (ตอนนี้มี: {', '.join(names)})" if names else ""))
        return ""
    except Exception as error:                                   # noqa: BLE001
        return f"ต่อ Ollama ไม่ได้: {error}"


# เกณฑ์ให้คะแนนรายรูป — **ถามเป็นข้อๆ ไม่ใช่ให้คะแนนรวม**
#
# **วัดแล้วการถาม "ให้คะแนน 0-10" ใช้ไม่ได้** (30 ส.ค. 2569) โมเดลตอบ 8.0
# ให้ 16 จาก 17 รูป เรียงลำดับไม่ได้เลย ผลคือเลือกไฟล์แรกๆ ตามลำดับชื่อ
# ตรงกับที่ Gemini เลือกแค่ 27%
#
# **แต่ตอนถามว่า "เห็นอะไรในรูป" มันตอบแม่นมาก** — บอกได้ว่าเป็นสายชาร์จ
# เป็นตารางสเปก มีตัวหนังสือเยอะ ฯลฯ
#
# จึงเปลี่ยนเป็นถาม **ข้อเท็จจริงที่ตาเห็น** แล้วเราคิดคะแนนเอง
# โมเดลเล็กเก่งเรื่อง "มีอะไรอยู่ในภาพ" แต่ไม่เก่งเรื่อง "ให้คะแนนความดี"
# เพราะอย่างหลังต้องเทียบกับรูปอื่นที่มันไม่ได้เห็น
SCORE_ASK = (
    "ดูรูปสินค้านี้แล้วตอบเป็น JSON บรรทัดเดียว ห้ามมีข้อความอื่น\n\n"
    "{\n"
    '  "product": <0=ไม่เห็นตัวสินค้าเลย 1=เห็นบางส่วน 2=เห็นเต็มตัวชัดเจน>,\n'
    '  "text": <0=แทบไม่มีตัวหนังสือ 1=มีบ้าง 2=ตัวหนังสือเต็มภาพ>,\n'
    '  "feature": <1=โชว์กลไก/การใช้งาน/วัสดุใกล้ๆ/เทียบขนาดกับของอื่น 0=ไม่โชว์>,\n'
    '  "table": <1=เป็นตารางสเปก ใบรับประกัน แบนเนอร์ หรือโลโก้ล้วน 0=ไม่ใช่>,\n'
    '  "people": <1=มีคนหรือมือใช้งานสินค้าอยู่ในภาพ 0=ไม่มี>,\n'
    '  "what": "<สิ่งที่เห็น ไม่เกิน 10 คำไทย>"\n'
    "}"
)

# น้ำหนักของแต่ละข้อ — ถอดจากเกณฑ์ที่ Gemini ใช้
#
#   เห็นสินค้าเต็มตัว     สำคัญสุด (คลิปต้องโชว์ของ)
#   โชว์กลไก/การใช้งาน   จุดขายที่จับต้องได้
#   มีคนใช้งาน           หยุดสายตาได้ดีกว่าภาพของเปล่า
#   ตัวหนังสือเต็มภาพ    หักหนัก คนดูคลิปสั้นไม่อ่าน
#   ตารางสเปก/แบนเนอร์   หักหนักสุด เป็นฉากที่เสียเปล่า
SCORE_WEIGHT = {"product": 3.0, "feature": 2.5, "people": 1.5,
                "text": -2.0, "table": -4.0}


def score_one(path: Path, model: str = OLLAMA_MODEL, timeout: float = 120.0) -> dict:
    """ให้คะแนนรูปเดียว — คืน {"score": float, "what": str} · ล้มเหลวคืน score = -1

    **คะแนน -1 แปลว่ายังไม่ได้ตรวจ ไม่ใช่ตรวจแล้วได้ 0** (กติกาข้อ 2.3.1 ข้อ 4)
    ถ้าใช้ 0 รูปที่อ่านไม่ได้จะถูกจัดว่าแย่เท่ารูปที่แย่จริง แล้วโดนตัดทิ้ง
    ทั้งที่อาจเป็นรูปดีที่บังเอิญส่งไม่สำเร็จ
    """
    import base64                                                # noqa: PLC0415
    import json as _json                                         # noqa: PLC0415

    import httpx                                                 # noqa: PLC0415

    try:
        blob = base64.b64encode(path.read_bytes()).decode("ascii")
    except OSError as error:
        return {"score": -1.0, "what": f"อ่านไฟล์ไม่ได้: {error}"}
    try:
        reply = httpx.post(f"{OLLAMA_URL}/api/generate", timeout=timeout, json={
            "model": model, "stream": False, "images": [blob],
            "prompt": SCORE_ASK,
            "options": {"num_predict": 120, "temperature": 0.0},
        })
        if reply.status_code != 200:
            return {"score": -1.0, "what": f"Ollama ตอบ {reply.status_code}"}
        text = (reply.json().get("response") or "").strip()
    except Exception as error:                                   # noqa: BLE001
        return {"score": -1.0, "what": f"เรียกไม่สำเร็จ: {error}"}

    # โมเดลเล็กชอบห่อ JSON ด้วยข้อความหรือรั้ว ``` — คว้าเฉพาะก้อนในวงเล็บปีกกา
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return {"score": -1.0, "what": f"แกะคำตอบไม่ได้: {text[:40]}"}
    try:
        got = _json.loads(text[start:end + 1])
    except Exception:                                            # noqa: BLE001
        return {"score": -1.0, "what": f"JSON เสีย: {text[start:start + 40]}"}

    total = 0.0
    for key, weight in SCORE_WEIGHT.items():
        try:
            total += float(got.get(key, 0)) * weight
        except (TypeError, ValueError):
            pass
    return {"score": total, "what": str(got.get("what", ""))[:60],
            "raw": {k: got.get(k) for k in SCORE_WEIGHT}}


def ollama_pick(paths: list[Path], count: int, log=say,
                model: str = OLLAMA_MODEL) -> list[Path]:
    """ตัดรูปซ้ำ แล้วให้คะแนนทีละใบ เลือกใบที่คะแนนสูงสุด `count` ใบ

    คืนลิสต์ว่างถ้า Ollama ไม่พร้อม — ผู้เรียกถอยไปใช้วิธีเดิมได้
    """
    why = ollama_ready(model)
    if why:
        log(f"  ใช้ AI ในเครื่องไม่ได้: {why}")
        return []
    kept = dedupe(paths)
    if len(kept) < len(paths):
        log(f"  ตัดรูปซ้ำออก {len(paths) - len(kept)} ใบ เหลือ {len(kept)} ใบ")
    scored = []
    for path in kept:
        got = score_one(path, model)
        scored.append((got["score"], path, got["what"]))
    ok = [row for row in scored if row[0] >= 0]
    if len(ok) < count:
        log(f"  ให้คะแนนได้แค่ {len(ok)} จาก {len(kept)} ใบ — ไม่พอ {count} ใบ")
        return []
    ok.sort(key=lambda row: -row[0])
    return [path for _, path, _ in ok[:count]]


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command")
    d = sub.add_parser("dedupe", help="ดูว่าตัดรูปซ้ำได้เท่าไร")
    d.add_argument("folder")
    c = sub.add_parser("compare", help="เทียบกับที่ Gemini เคยเลือก")
    c.add_argument("--n", type=int, default=10)
    sub.add_parser("check", help="Ollama พร้อมใช้ไหม")
    args = parser.parse_args(argv)

    if args.command == "check":
        why = ollama_ready()
        say(why or f"✅ Ollama พร้อม · มีโมเดล {OLLAMA_MODEL}")
        return 1 if why else 0

    if args.command == "dedupe":
        folder = Path(args.folder)
        if not folder.is_absolute():
            folder = BASE_DIR / folder
        pics = sorted(p for p in folder.iterdir()
                      if p.suffix.lower() in (".jpg", ".jpeg", ".png"))
        kept = dedupe(pics)
        say(f"{folder.name}: {len(pics)} ใบ → เหลือ {len(kept)} ใบ "
            f"(ตัดซ้ำออก {len(pics) - len(kept)} ใบ)")
        for p in kept:
            say(f"   {p.name}")
        return 0

    if args.command == "compare":
        return compare(args.n)

    say(__doc__ or "")
    return 1


def _runs_with_picks(limit: int) -> list[tuple[Path, list[str], list[str]]]:
    """งานที่มีทั้งรูปทั้งกองและรูปที่ Gemini เลือกไว้ — ไว้ใช้เทียบ"""
    out = []
    for root in RUN_DIRS:
        folder = DATA_DIR / root
        if not folder.is_dir():
            continue
        for run_file in sorted(folder.glob("*/run.json")):
            try:
                run = json.loads(run_file.read_text(encoding="utf-8"))
            except Exception:                                    # noqa: BLE001
                continue
            picked = [str(x) for x in (run.get("images") or [])]
            pool = [str(x) for x in (run.get("image_pool") or [])]
            if len(picked) >= 3 and len(pool) >= 5:
                out.append((run_file.parent, sorted(pool + picked), picked))
            if len(out) >= limit:
                return out
    return out


def compare(limit: int) -> int:
    """ตัดรูปซ้ำแล้วดูว่ารูปที่ Gemini เลือกยังอยู่ครบไหม

    **นี่คือตัววัดที่ถูกต้องสำหรับด่านแรก** — ด่านแรกมีหน้าที่ *ไม่ทิ้งของดี*
    ไม่ใช่เลือกเอง ถ้ามันตัดรูปที่ Gemini เลือกทิ้ง แปลว่าตั้งค่าแรงเกินไป
    """
    rows = _runs_with_picks(limit)
    if not rows:
        say("ไม่มีงานที่เทียบได้")
        return 1
    say(f"{'สินค้า':<16}{'ทั้งกอง':>8}{'เหลือ':>7}{'ตัดออก':>8}{'ของ Gemini ที่รอด':>20}")
    say("-" * 62)
    total_all = total_kept = total_hit = total_pick = 0
    worst = []
    for folder, allpics, picked in rows:
        paths = [folder / name for name in allpics if (folder / name).is_file()]
        if len(paths) < 5:
            continue
        kept = dedupe(paths)
        keptnames = {p.name for p in kept}
        hit = sum(1 for name in picked if name in keptnames)
        total_all += len(paths)
        total_kept += len(kept)
        total_hit += hit
        total_pick += len(picked)
        if hit < len(picked):
            worst.append((folder.name, [n for n in picked if n not in keptnames]))
        say(f"{folder.name:<16}{len(paths):>8}{len(kept):>7}"
            f"{len(paths) - len(kept):>8}{f'{hit}/{len(picked)}':>20}")
    if not total_pick:
        say("ไม่มีข้อมูลพอ")
        return 1
    say("-" * 62)
    say(f"รวม: {total_all} ใบ → เหลือ {total_kept} ใบ "
        f"(ตัดซ้ำออก {total_all - total_kept} ใบ = {(total_all-total_kept)*100//total_all}%)")
    say(f"รูปที่ Gemini เลือกและยังรอดจากด่านแรก: {total_hit}/{total_pick} "
        f"= {total_hit*100//total_pick}%")
    if worst:
        say(f"\nงานที่ตัดของ Gemini ทิ้ง {len(worst)} ใบ:")
        for name, lost in worst[:8]:
            say(f"  {name}: {', '.join(lost)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
