"""แปลงแคปชันเป็น "คุณสมบัติที่เทียบกันได้" — หัวใจของการเทียบแมส vs ไม่แมส

ทำไมต้องมีไฟล์นี้: "แคปชันสวย" วัดไม่ได้ เทียบไม่ได้ หาข้อสรุปไม่ได้
แต่ "ยาว 180 ตัวอักษร · ขึ้นต้นด้วยคำถาม · มีราคา · อิโมจิ 3 ตัว · รูป 2 ใบ"
เทียบกันได้ทันที แล้วถามได้ว่า **โพสต์ที่แมสมีอะไรต่างจากโพสต์ที่ไม่แมส**

ทุกช่องออกแบบให้ตอบคำถามเดียวได้ชัดๆ ไม่ใช่คะแนนรวมลอยๆ ที่ตีความไม่ได้
"""
from __future__ import annotations

import re
from datetime import datetime

# อิโมจิ + สัญลักษณ์ภาพ (ครอบช่วงที่ใช้จริงในโพสต์ขายของไทย)
_EMOJI = re.compile(
    "[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF"
    "\U00002190-\U000021FF\U00002B00-\U00002BFF️❤❗❕]")
_HASHTAG = re.compile(r"#[^\s#]{1,40}")
_URL = re.compile(r"https?://\S+|(?:www\.)\S+\.\S+")
_PHONE = re.compile(r"0\d[\d\s-]{7,12}")

# ราคา — ต้องมีตัวเลขคู่กับหน่วยเงิน ไม่ใช่เลขลอยๆ (เลขลอยอาจเป็นเบอร์/ขนาด)
_PRICE = re.compile(
    r"(?:฿\s*[\d,]+)|(?:[\d,]+\s*(?:บาท|บ\.|฿|.-))|(?:ราคา\s*[\d,]+)", re.I)

# กลุ่มคำที่ทีมขายใช้จริง — แยกเป็นหมวดเพื่อดูว่าหมวดไหนได้ผล
_WORDS = {
    "ฟรี/แถม":      r"ฟรี|แถม|ส่งฟรี|ไม่มีค่าส่ง|แจก|free",
    "ลด/โปร":       r"ลด\s*\d|ลดราคา|โปร|โปรโมชั่น|พิเศษ|ถูกกว่า|sale|%",
    "เร่งด่วน":     r"ด่วน|เหลือ|สุดท้าย|หมดเขต|จำนวนจำกัด|วันนี้เท่านั้น|รีบ|หมดแล้วหมดเลย",
    "ชวนทัก":       r"ทักแชท|ทักมา|inbox|กล่องข้อความ|สนใจทัก|สั่งซื้อ|กดลิงก์|คลิกเลย|dm",
    "รีวิว/ประสบการณ์": r"รีวิว|ใช้แล้ว|ลองแล้ว|ประสบการณ์|บอกต่อ|แนะนำ",
    "ถามความเห็น":  r"ใครเคย|มีใคร|แนะนำหน่อย|ช่วยดู|ดีไหม|ว่าไง",
}
_WORDS_RE = {k: re.compile(v, re.I) for k, v in _WORDS.items()}

_QUESTION = re.compile(r"[?？]|ไหม|มั้ย|หรือเปล่า|รึเปล่า|เหรอ|ยังไง|อะไร|ที่ไหน|ใคร")
_EXCLAIM = re.compile(r"[!！]|โอ้|ว้าว|โห|เฮ้ย|omg|ตกใจ")
_GREET = re.compile(r"^(สวัสดี|หวัดดี|ขออนุญาต|ขอโทษ|ฝากด้วย|ฝากร้าน)", re.I)


def opener_kind(caption: str) -> str:
    """บรรทัดแรกเป็นแบบไหน — ตัวที่ตัดสินว่าคนหยุดนิ้วหรือเลื่อนผ่าน"""
    first = ""
    for line in (caption or "").splitlines():
        if line.strip():
            first = line.strip()
            break
    if not first:
        return "ไม่มีข้อความ"
    if _GREET.search(first):
        return "ทักทาย/ขออนุญาต"
    if _PRICE.search(first):
        return "เปิดด้วยราคา"
    if _QUESTION.search(first):
        return "เปิดด้วยคำถาม"
    if _EXCLAIM.search(first):
        return "เปิดด้วยอุทาน"
    if _EMOJI.search(first[:6]):
        return "เปิดด้วยอิโมจิ"
    return "เปิดด้วยเล่าเรื่อง"


_WEEKDAYS = ["จันทร์", "อังคาร", "พุธ", "พฤหัส", "ศุกร์", "เสาร์", "อาทิตย์"]


def time_slot(hour: int | None) -> str:
    if hour is None:
        return ""
    if hour < 6:
        return "ดึก (00-06)"
    if hour < 11:
        return "เช้า (06-11)"
    if hour < 14:
        return "เที่ยง (11-14)"
    if hour < 17:
        return "บ่าย (14-17)"
    if hour < 21:
        return "เย็น (17-21)"
    return "ค่ำ (21-24)"


def extract(post: dict) -> dict:
    """คำนวณคุณสมบัติทั้งหมดของโพสต์หนึ่งใบ"""
    caption = post.get("caption") or ""
    lines = [l for l in caption.splitlines() if l.strip()]
    body = caption.strip()

    stamp = post.get("posted_at")
    when = None
    if isinstance(stamp, (int, float)) and stamp:
        try:
            when = datetime.fromtimestamp(stamp)
        except (OSError, ValueError, OverflowError):
            when = None

    likes = int(post.get("likes") or 0)
    comments = int(post.get("comments") or 0)
    shares = int(post.get("shares") or 0)
    total = likes + comments + shares

    out = {
        "ตัวอักษร": len(body),
        "บรรทัด": len(lines),
        "คำ": len(body.split()),
        "อิโมจิ": len(_EMOJI.findall(body)),
        "แฮชแท็ก": len(_HASHTAG.findall(body)),
        "ลิงก์": len(_URL.findall(body)),
        "เบอร์โทร": 1 if _PHONE.search(body) else 0,
        "มีราคา": 1 if _PRICE.search(body) else 0,
        "การเปิดหัว": opener_kind(caption),
        "จำนวนรูป": len(post.get("image_files") or post.get("image_urls") or []),
        "วัน": _WEEKDAYS[when.weekday()] if when else "",
        "ชั่วโมง": when.hour if when else None,
        "ช่วงเวลา": time_slot(when.hour if when else None),
    }
    for label, pattern in _WORDS_RE.items():
        out[label] = 1 if pattern.search(body) else 0

    # อัตราส่วนที่บอก "คุณภาพ" ของยอด ไม่ใช่แค่ปริมาณ
    out["แชร์ต่อ100ไลค์"] = round(shares * 100 / likes, 1) if likes else 0.0
    out["คอมเมนต์ต่อ100ไลค์"] = round(comments * 100 / likes, 1) if likes else 0.0
    out["ยอดรวม"] = total
    return out


# ------------------------------------------------- จับกลุ่มตามสินค้า/คอนเทนต์
#
# โพสต์แมสคือการเอา **เนื้อเดียวกัน** ไปลงหลายกลุ่ม ดังนั้นโพสต์ที่แคปชัน
# เหมือนกัน = สินค้าเดียวกัน = ชุดเดียวกัน จับกลุ่มด้วยตัวข้อความจึงแม่นกว่า
# การเดาชื่อสินค้าจากคำ และได้ของแถมสำคัญ: **เนื้อเดียวกันลงคนละกลุ่ม
# กลุ่มไหนตอบดีกว่า** ซึ่งเป็นคำถามที่ตอบได้เฉพาะเมื่อจับคู่ถูกเท่านั้น

_NOISE = re.compile(r"[\s​]+")
_STRIP = re.compile(r"[^\wก-๙]+", re.U)


def content_key(caption: str) -> str:
    """ลายนิ้วมือของเนื้อหา — ตัดอิโมจิ เครื่องหมาย ตัวเลข ช่องว่างออกให้หมด

    ตัดตัวเลขออกด้วยเพราะโพสต์ชุดเดียวกันมักแก้แค่ราคาหรือจำนวนที่เหลือ
    ถ้าไม่ตัด โพสต์ชุดเดียวกันจะถูกนับเป็นคนละชุด
    """
    text = _EMOJI.sub("", caption or "")
    text = _URL.sub("", text)
    text = _HASHTAG.sub("", text)
    text = re.sub(r"[\d,.]+", "", text)
    text = _STRIP.sub("", text).lower()
    return text[:150]


def content_label(caption: str, limit: int = 46) -> str:
    """ชื่อที่คนอ่านรู้เรื่อง — บรรทัดแรกที่ตัดอิโมจิออกแล้ว"""
    for line in (caption or "").splitlines():
        clean = _EMOJI.sub("", line).strip(" \t-·•*")
        if len(clean) >= 6:
            return clean[:limit] + ("…" if len(clean) > limit else "")
    clean = _EMOJI.sub("", caption or "").strip()
    return (clean[:limit] or "(ไม่มีข้อความ)")


def load_products(path) -> list[tuple[str, list[str]]]:
    """อ่านสมุดสินค้าที่ผู้ใช้เขียนเอง — บรรทัดละ  ชื่อสินค้า = คำค้น, คำค้น

    ไม่มีไฟล์ = ไม่เป็นไร ระบบจะจับกลุ่มจากตัวข้อความให้เอง
    มีไฟล์เมื่อไร ชื่อที่ผู้ใช้ตั้งจะชนะเสมอ — เพราะเจ้าของรู้ดีกว่าโค้ด
    """
    from pathlib import Path
    path = Path(path)
    if not path.is_file():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, words = line.partition("=")
        keys = [w.strip().lower() for w in words.split(",") if w.strip()]
        if name.strip() and keys:
            out.append((name.strip(), keys))
    return out


def match_product(caption: str, book: list[tuple[str, list[str]]]) -> str:
    """ชื่อสินค้าจากสมุดที่ผู้ใช้เขียน — ไม่ตรงสักอันคืนค่าว่าง (ไม่เดา)"""
    text = (caption or "").lower()
    best, best_hits = "", 0
    for name, keys in book:
        hits = sum(1 for k in keys if k in text)
        if hits > best_hits:
            best, best_hits = name, hits
    return best


def group_by_content(posts: list[dict], book=()) -> dict[str, dict]:
    """จับโพสต์เข้ากลุ่มสินค้า/คอนเทนต์ — คืน {รหัสชุด: ข้อมูลชุด}

    ลำดับการตั้งชื่อ:
      1. ชื่อจากสมุดสินค้าของผู้ใช้ (ถ้าตรง)
      2. บรรทัดแรกของโพสต์ที่ยอดสูงสุดในชุดนั้น
    """
    buckets: dict[str, list[dict]] = {}
    for post in posts:
        key = content_key(post.get("caption") or "") or f"__{post.get('id')}"
        buckets.setdefault(key, []).append(post)

    out: dict[str, dict] = {}
    for key, items in buckets.items():
        items.sort(key=lambda p: p.get("total") or 0, reverse=True)
        named = ""
        for item in items:
            named = match_product(item.get("caption") or "", book)
            if named:
                break
        label = named or content_label(items[0].get("caption") or "")
        groups = sorted({i.get("group_name") or "" for i in items})
        mass = [i for i in items if i.get("is_mass")]
        out[key] = {
            "key": key, "label": label, "from_book": bool(named),
            "posts": items, "n_posts": len(items),
            "n_groups": len(groups), "groups": groups,
            "n_mass": len(mass),
            "total": sum(int(i.get("total") or 0) for i in items),
            "best": items[0].get("total") or 0,
            "worst": items[-1].get("total") or 0,
        }
    return out


# ช่องที่เป็นตัวเลขล้วน — เอาไปหาค่าเฉลี่ยเทียบสองกลุ่มได้
NUMERIC = ["ตัวอักษร", "บรรทัด", "คำ", "อิโมจิ", "แฮชแท็ก", "ลิงก์",
           "จำนวนรูป", "แชร์ต่อ100ไลค์", "คอมเมนต์ต่อ100ไลค์"]
# ช่องที่เป็นใช่/ไม่ใช่ — เอาไปหา "กี่ % ของกลุ่มที่มีสิ่งนี้"
FLAGS = ["มีราคา", "เบอร์โทร"] + list(_WORDS.keys())
# ช่องที่เป็นหมวด — เอาไปนับว่าหมวดไหนเยอะในกลุ่มไหน
CATEGORIES = ["การเปิดหัว", "ช่วงเวลา", "วัน"]


def compare(mass: list[dict], plain: list[dict]) -> list[dict]:
    """เทียบสองกลุ่มทีละช่อง — คืนตารางพร้อมลงชีท Excel

    ตัวเลขที่สำคัญที่สุดคือ **ต่างกันกี่เท่า** ไม่ใช่ค่าดิบของแต่ละฝั่ง
    เพราะ "แมสยาวเฉลี่ย 190 ตัว" ไม่มีความหมายจนกว่าจะรู้ว่าไม่แมสยาว 95
    """
    rows: list[dict] = []

    def avg(items, key):
        vals = [i["features"].get(key) for i in items]
        vals = [v for v in vals if isinstance(v, (int, float))]
        return round(sum(vals) / len(vals), 2) if vals else 0.0

    def pct(items, key):
        if not items:
            return 0.0
        return round(sum(1 for i in items if i["features"].get(key)) * 100
                     / len(items), 1)

    def add(kind, name, a, b, unit=""):
        if b:
            gap = round(a / b, 2)
            verdict = ("แมสมากกว่า " + f"{gap}x" if gap >= 1.15 else
                       "ไม่แมสมากกว่า " + f"{round(b/a,2) if a else '∞'}x"
                       if gap <= 0.87 else "พอๆ กัน")
        else:
            verdict = "แมสมี ไม่แมสไม่มี" if a else "ไม่มีทั้งคู่"
        rows.append({"หมวด": kind, "ช่อง": name, "แมส": a, "ไม่แมส": b,
                     "หน่วย": unit, "ผลเทียบ": verdict})

    for key in NUMERIC:
        add("ค่าเฉลี่ย", key, avg(mass, key), avg(plain, key), "เฉลี่ย")
    for key in FLAGS:
        add("มีกี่ %", key, pct(mass, key), pct(plain, key), "%")
    for key in CATEGORIES:
        kinds = sorted({str(i["features"].get(key) or "")
                        for i in mass + plain} - {""})
        for kind in kinds:
            a = round(sum(1 for i in mass
                          if i["features"].get(key) == kind) * 100
                      / len(mass), 1) if mass else 0.0
            b = round(sum(1 for i in plain
                          if i["features"].get(key) == kind) * 100
                      / len(plain), 1) if plain else 0.0
            add(key, kind, a, b, "%")
    return rows
