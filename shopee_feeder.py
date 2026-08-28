# -*- coding: utf-8 -*-
"""ป้อนสินค้าจากคลัง Shopee เข้าเป็น **แม่แบบ** ของตารางโพสต์ประจำวัน

ทำไมต้องมี — วัดจริง 21 ส.ค. 2026: ตารางโพสต์ 4 รอบต่อวัน (09:30 · 12:50 ·
14:30 · 16:40) ทุกรอบชี้ไปที่แม่แบบ **ใบเดียวกัน** (`p194893071` ชาเขียว 39 บาท)
ตัวหมุนแม่แบบทำงานถูกต้องทุกประการ (`sources[next % len]`) แต่มีของให้หมุนใบเดียว
จึงวนกลับมาโพสต์ข้อความเดิมทุกวัน — 20 ส.ค. 17:03 กับ 21 ส.ค. 09:43 เหมือนกันทุกไบต์

ขณะเดียวกันคลังสินค้าที่เก็บด้วยมือถือมี 377 ชิ้น (รูป 5,015 ใบ · 2.3 GB) ที่ยัง
ไม่เคยถูกใช้เลยสักชิ้น ตัวนี้คือท่อที่ต่อสองฝั่งเข้าหากัน

สิ่งที่ทำ
  1. อ่าน `products.csv` ของสายเก็บข้อมูล แล้วคัดเฉพาะชิ้นที่โพสต์ได้จริง
  2. ครอปรูปหน้าจอให้เหลือเฉพาะตัวสินค้า แล้วแปลงเป็น .jpg
  3. สร้างงานแม่แบบ **ที่ตรึงไว้** (`pinned`) ในคลังงาน — ไม่ยิงเอง ไม่กวนคิวจริง
  4. คืนรหัสงานให้เอาไปเติมใน `sources` ของตาราง (ต้องให้เจ้าของสั่งเอง)

สิ่งที่ **ไม่** ทำ — ไม่โพสต์ ไม่ตั้งเวลา ไม่แก้ตารางเอง เพราะทั้งสามอย่างนั้น
ส่งของออกสู่สาธารณะจริง ต้องให้เจ้าของตัดสินใจเสมอ

    python shopee_feeder.py list --top 15     ดูว่าจะเลือกอะไร (ไม่เขียนอะไรเลย)
    python shopee_feeder.py make --count 10   สร้างแม่แบบจริง
    python shopee_feeder.py status            แม่แบบที่มีอยู่ + สินค้าที่เหลือ
"""
from __future__ import annotations

import argparse
import csv
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import fb_auto_post
import studio_shared

# คลังสินค้าของสายเก็บข้อมูล (โปรเจกต์ 12.เก็บข้อมูล เขียนไว้บน Drive เดียวกัน)
PRODUCT_DIR = Path(os.environ.get(
    "SHOPEE_PRODUCT_DIR", r"G:\My Drive\pipeline studio\Video\Product"))
PRODUCTS_CSV = PRODUCT_DIR / "products.csv"

# แถวเก่า 197 แถวยังจดที่อยู่รูปเป็นโฟลเดอร์ในเครื่อง ทั้งที่ไฟล์ย้ายขึ้น Drive แล้ว
# แมปให้ตอนอ่าน ไม่ไปแก้ CSV ของสายอื่น (เจ้าของไฟล์คนละสาย)
OLD_PREFIX = r"C:\project\2.Auto gen Video\12.เก็บข้อมูล\data"

IMAGE_DIR = studio_shared.POST_DIR / "images"
USED_FILE = studio_shared.post_file("shopee_feeder_used.json")

# โซนรูปสินค้าบนภาพหน้าจอเต็มจอ — วัดจาก 40 ใบสุ่ม พบว่า 30 ใบตรงกันเป๊ะที่
# y 504-1583 เพราะเป็นมือถือเครื่องเดียวหน้าจอเดียวกัน โครง Shopee จึงอยู่ที่เดิม
# ใช้ค่าคงที่แทนการหาขอบจากความสว่าง เพราะสินค้าพื้นหลังดำ (Black Shark) ทำให้
# ตัวหาขอบกินเนื้อสินค้าไปด้วย — วัดได้ 740-1347 แทนที่จะเป็น 504-1583
FULL_SCREEN = (1080, 2190)
GALLERY_TOP, GALLERY_BOTTOM = 504, 1584

POST_WIDTH = 1080          # กว้างพอสำหรับ FB โดยไม่ให้ไฟล์บวม
JPEG_QUALITY = 88

# ราคาต่ำกว่านี้ไม่เอา — ในคลังมี 8 ชิ้นที่จดราคาไว้ 1-2 บาท ซึ่งไม่ใช่ราคาสินค้าจริง
# แต่เป็นราคาของ "ตัวเลือกที่ถูกที่สุด" (ฟิล์ม 1 ชิ้น · หัวสายเปล่า) ที่หน้าร้านโชว์
# ไว้ล่อให้กดเข้าไป โพสต์ออกไปว่า "1 บาท" แล้วคนกดเจอคนละราคา = เสียความเชื่อถือ
# ของกลุ่ม ซึ่งเป็นทุนก้อนเดียวที่เรามีจริงๆ
MIN_PRICE = 15


# ------------------------------------------------------------ อ่านคลังสินค้า

def _price(raw: str) -> int:
    """ราคาเป็นตัวเลขล้วน — CSV เก็บมาเป็น "1,690" บ้าง "0" บ้าง"""
    digits = re.sub(r"[^\d]", "", str(raw or "").split(".")[0])
    return int(digits) if digits else 0


def _sold(raw: str) -> int:
    """"ขายแล้ว 30k+ ชิ้น" -> 30000 (ใช้จัดอันดับความนิยม)"""
    match = re.search(r"([\d.,]+)\s*(k?)", str(raw or ""), re.IGNORECASE)
    if not match:
        return 0
    number = float(match.group(1).replace(",", ""))
    return int(number * 1000) if match.group(2).lower() == "k" else int(number)


def clean_name(raw: str) -> str:
    """ชื่อสินค้าที่คนอ่านรู้เรื่อง — ของดิบจาก Shopee รกเกินกว่าจะเอาไปโพสต์

    ตัวอย่างจริงในคลัง:
      "[8.15 | โค้ดลด 25%] HUAWEI FreeBuds SE 3 | หูฟัง | ฟั ฟังเพลงได้ยาวนาน…"
      "000013-inch MacBook Neo: Apple A18 Pro chip with 6-core CPU…"
    """
    text = str(raw or "").strip()
    for _ in range(3):                                          # ป้ายโปรซ้อนกันได้
        text = re.sub(r"^\s*[\[【(][^\]】)]*[\]】)]\s*", "", text)
    text = re.sub(r"^0+(?=\d)", "", text)                       # 000013-inch -> 13-inch
    text = text.split("|")[0].split("｜")[0]                     # เอาท่อนแรกพอ
    # "สำหรับ สาย Xiaomi Redmi watch 3" อ่านในแคปชันแล้วสะดุด ("ใครเคยซื้อ สำหรับ…")
    # ตัดคำเชื่อมหน้าชื่อออก เหลือชื่อของจริงขึ้นต้นประโยค — เจอในคลัง 38 ชิ้น
    text = re.sub(r"^(สำหรับ|สําหรับ|for)\s+", "", text, flags=re.IGNORECASE)
    text = text.split(" / ")[0]                                 # "Fit 3 / Fit 4 / …"
    text = re.sub(r"\s+", " ", text).strip(" -–—:,/")
    if len(text) > 46:                                          # ยาวไปคนไม่อ่าน
        text = text[:46].rsplit(" ", 1)[0].strip() + "…"
    return text


def _folder(row: dict) -> Path:
    raw = str(row.get("โฟลเดอร์") or "").strip()
    if raw.startswith(OLD_PREFIX):
        raw = raw.replace(OLD_PREFIX, str(PRODUCT_DIR / "data"))
    return Path(raw)


def _images(folder: Path) -> list[Path]:
    if not folder.is_dir():
        return []
    return sorted(p for p in folder.iterdir()
                  if p.name.startswith("img_") and p.suffix.lower() == ".png")


def load_used() -> set[str]:
    """ลิงก์ที่เคยทำแม่แบบไปแล้ว — กันสินค้าซ้ำ ซึ่งเป็นปัญหาที่เรากำลังแก้อยู่พอดี"""
    data = studio_shared.read_json(USED_FILE, {})
    return set(data.get("links") or [])


def mark_used(link: str, job_id: str, name: str) -> None:
    def mutate(current):
        current.setdefault("links", [])
        current.setdefault("jobs", {})
        if link not in current["links"]:
            current["links"].append(link)
        current["jobs"][job_id] = {"link": link, "name": name}
        return current

    studio_shared.update_json(USED_FILE, mutate, default={},
                              label="จดสินค้าที่ทำแม่แบบแล้ว")


def candidates(skip_used: bool = True) -> list[dict]:
    """สินค้าที่โพสต์ได้จริง เรียงจากที่น่าจะไปได้ไกลที่สุดก่อน

    ตัดทิ้งสามอย่างที่ทำให้โพสต์ออกไปแล้วเสียของ:
      ราคา 0 (บั๊กตอนเก็บ อ่านราคาจากโซนโปรโมชันมา) · ไม่มีลิงก์ · ไฟล์รูปหาย
    """
    if not PRODUCTS_CSV.is_file():
        raise SystemExit(f"ไม่พบคลังสินค้า: {PRODUCTS_CSV}")
    used = load_used() if skip_used else set()
    picked: list[dict] = []
    with PRODUCTS_CSV.open(encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            link = str(row.get("ลิงก์") or "").strip()
            price = _price(row.get("ราคา"))
            if not link or price < MIN_PRICE or link in used:
                continue
            images = _images(_folder(row))
            if not images:
                continue
            picked.append({
                "shop": str(row.get("ร้าน") or "").strip(),
                "name": clean_name(row.get("ชื่อสินค้า")),
                "raw_name": str(row.get("ชื่อสินค้า") or "").strip(),
                "price": price,
                "sold": _sold(row.get("ขายแล้ว")),
                "link": link,
                "images": images,
            })
    picked.sort(key=_rank, reverse=True)
    return picked


def _rank(item: dict) -> tuple:
    """ของถูก + คนซื้อเยอะ มาก่อน

    มาจากของจริง: โพสต์ที่เจ้าของใช้อยู่ตอนนี้คือ "ชาเขียว แก้วละ 39 บาท" —
    กลุ่ม Facebook ไทยตอบสนองกับ **ราคาต่อชิ้นที่น่าตกใจ** มากกว่าของแพงที่ลดเยอะ
    ของเกินสองพันจึงถูกดันลงท้ายแถว ไม่ได้ตัดทิ้ง (ยังใช้ได้ถ้าของถูกหมด)
    """
    cheap = 2 if item["price"] <= 199 else 1 if item["price"] <= 799 else 0
    return (cheap, item["sold"], -item["price"])


# ------------------------------------------------------------------- แคปชัน

# สูตรมาจากงานวิเคราะห์ของเจ้าของเอง (`Post/2.Analyse/hook-taxonomy-analysis.md`
# 21 ส.ค. 2026): บน Facebook ตระกูลที่พาถึงล้านวิวคือ 1 ตัวเลขช็อก · 4 เตือนภัย ·
# 6 คำถามจี้ใจ · 7 เรื่องเล่า — ทั้งหมดเป็นสาย "มีสาระ/มีน้ำใจ" ที่คนแชร์ต่อให้คนที่ห่วง
#
# หมุนหลายสูตรแทนที่จะใช้สูตรเดียว เพราะโพสต์หน้าตาเหมือนกันทุกวันคือสิ่งที่ทั้ง
# คนอ่านและตัวจัดอันดับของ Facebook จับได้เร็วที่สุด
HOOKS = [
    ("ตัวเลขช็อก", "{name} เหลือ {price} บาท 😳\nราคานี้จริงเหรอเนี่ย"),
    ("เตือนภัย", "เสียดาย พึ่งเห็น 😩\n{name} {price} บาทเอง ซื้อแพงมาตลอด"),
    ("คำถามจี้ใจ", "ใครเคยซื้อ {name} แพงกว่านี้บ้าง 🙋\nอันนี้ {price} บาท"),
    ("เรื่องเล่า", "ลูกสั่งมาให้ {name} ราคา {price} บาท\nใช้แล้วดีกว่าที่คิดเยอะ"),
    ("ตัวเลข+สังคม", "คนซื้อไปแล้ว {sold} 😮\n{name} {price} บาท"),
    ("เตือนภัย 2", "อย่าเพิ่งซื้อ {name} ที่อื่น\nเจอที่ {price} บาทมาแล้ว"),
]

COMMENT_LEAD = "/comment พิกัดนี้น้า 👉\n{link}"


def _sold_text(sold: int) -> str:
    if sold >= 1000:
        return f"{sold // 1000} พันกว่าคน" if sold < 10000 else f"{sold // 1000}k+"
    return f"{sold} คน"


def build_caption(item: dict, index: int) -> tuple[str, str]:
    """คืน (แคปชัน, ชื่อสูตรที่ใช้) — สลับสูตรตามลำดับที่สร้าง"""
    label, template = HOOKS[index % len(HOOKS)]
    caption = template.format(
        name=item["name"],
        price=f"{item['price']:,}",
        sold=_sold_text(item["sold"]),
    )
    return caption, label


# --------------------------------------------------------------------- รูป

def prepare_image(source: Path, target: Path) -> Path:
    """ครอปภาพหน้าจอให้เหลือเฉพาะตัวสินค้า แล้วเซฟเป็น .jpg

    ภาพในคลังมีสองแบบ (วัดจาก 448 ใบ): 1080x860 คือของที่ครอปมาแล้วตอนเก็บ
    ส่วน 1080x2190 คือภาพเต็มจอที่ยังมีแถบดำ · ปุ่มย้อนกลับ · ป้าย "ซื้อเลย" ติดมา
    ถ้าโพสต์ทั้งใบคนเห็นทันทีว่าเป็นภาพก๊อปหน้าจอ
    """
    from PIL import Image

    target.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(source) as image:
        if image.size == FULL_SCREEN:
            image = image.crop((0, GALLERY_TOP, image.width, GALLERY_BOTTOM))
        image = image.convert("RGB")
        if image.width > POST_WIDTH:
            ratio = POST_WIDTH / image.width
            image = image.resize((POST_WIDTH, round(image.height * ratio)),
                                 Image.LANCZOS)
        image.save(target, "JPEG", quality=JPEG_QUALITY, optimize=True)
    return target


# ---------------------------------------------------------------- สร้างแม่แบบ

def create_template(item: dict, index: int, jobs: fb_auto_post.JobStore,
                    groups: fb_auto_post.GroupStore, set_name: str) -> dict:
    """สร้างงานแม่แบบหนึ่งใบ — **ตรึงไว้ ไม่ตั้งเวลา ไม่เข้าคิวรอโพสต์**

    สถานะเป็น `cancelled` ตั้งแต่เกิด ตามแบบแม่แบบเดิม (`p194893071`) เพราะ
    `_fb_open_job` ใน app.py จะไล่ปิดงานที่ยัง "เปิดอยู่และไม่มีเวลา" ทิ้งทุกครั้ง
    ที่เจ้าของเริ่มงานใหม่ทาง Telegram — ถ้าปล่อยเป็น ready แม่แบบจะหายไปเงียบๆ
    ส่วนตัวตรวจของตาราง (`_routine_check_source`) ดูแค่แคปชันกับไฟล์รูป ไม่ดูสถานะ
    """
    caption, hook = build_caption(item, index)
    job = jobs.add(
        caption=caption,
        source="shopee_feeder",
        status=fb_auto_post.STATUS_CANCELLED,
        pinned=True,
        set=set_name,
        groups=groups.enabled_ids(set_name),
    )
    stem = IMAGE_DIR / job["id"]
    post_image = prepare_image(item["images"][0], Path(f"{stem}-1.jpg"))
    # รูปแนบคอมเมนต์ใช้ใบที่สอง ถ้าไม่มีก็ใช้ใบเดิม — คอมเมนต์ที่มีรูปถูกกดดูมากกว่า
    second = item["images"][1] if len(item["images"]) > 1 else item["images"][0]
    comment_image = prepare_image(second, Path(f"{stem}-c1.jpg"))
    comment = COMMENT_LEAD.format(link=item["link"])
    job = jobs.update(
        job["id"],
        image=str(post_image),
        images=[str(post_image)],
        comment=comment,
        comments=[comment],
        comment_images=[str(comment_image)],
    ) or job
    mark_used(item["link"], job["id"], item["name"])
    job["_hook"] = hook
    return job


# --------------------------------------------------------------------- CLI

def _stores() -> tuple[fb_auto_post.JobStore, fb_auto_post.GroupStore, str]:
    jobs = fb_auto_post.JobStore(studio_shared.post_file("fb_jobs.json"))
    groups = fb_auto_post.GroupStore(studio_shared.post_file("fb_groups.json"))
    config = studio_shared.read_json(studio_shared.post_file("config.json"), {})
    set_name = (config.get("facebook") or {}).get("set", "") if config else ""
    return jobs, groups, set_name


def cmd_list(args) -> None:
    items = candidates()
    print(f"สินค้าที่ยังไม่เคยทำแม่แบบ และโพสต์ได้จริง: {len(items)} ชิ้น\n")
    for index, item in enumerate(items[:args.top]):
        caption, hook = build_caption(item, index)
        head = caption.replace("\n", " / ")
        print(f"{index + 1:>3}. ฿{item['price']:<7,} ขาย {_sold_text(item['sold']):<9}"
              f" รูป {len(item['images']):<2} [{hook}]")
        print(f"     {head}")
        print(f"     {item['link']}")


def cmd_make(args) -> None:
    jobs, groups, set_name = _stores()
    items = candidates()
    if not items:
        raise SystemExit("ไม่มีสินค้าที่ยังไม่ได้ใช้แล้ว")
    made = []
    for index, item in enumerate(items[:args.count]):
        job = create_template(item, index, jobs, groups, set_name)
        made.append(job)
        print(f"✅ {job['id']} [{job['_hook']}] {item['name']} — ฿{item['price']:,}")
    print(f"\nสร้างแม่แบบแล้ว {len(made)} ใบ (ตรึงไว้ ไม่ถูกตัดตอนคิวเต็ม)")
    print("รหัสสำหรับเติมเข้าตาราง:")
    print("  " + " ".join(job["id"] for job in made))


def cmd_status(args) -> None:
    jobs, _groups, _set = _stores()
    mine = [j for j in jobs.listing() if j.get("source") == "shopee_feeder"]
    print(f"แม่แบบจากคลังสินค้า: {len(mine)} ใบ")
    for job in mine:
        images = [p for p in (job.get("images") or []) if Path(p).is_file()]
        mark = "✅" if images and job.get("caption") else "⚠️"
        head = (job.get("caption") or "").splitlines()[0][:44]
        print(f"  {mark} {job['id']} · รูป {len(images)} · {head}")
    print(f"\nสินค้าที่ยังไม่ได้ใช้: {len(candidates())} ชิ้น")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    listing = sub.add_parser("list", help="ดูว่าจะเลือกสินค้าอะไร (ไม่เขียนอะไร)")
    listing.add_argument("--top", type=int, default=15)
    listing.set_defaults(func=cmd_list)

    make = sub.add_parser("make", help="สร้างแม่แบบจริง")
    make.add_argument("--count", type=int, default=5)
    make.set_defaults(func=cmd_make)

    status = sub.add_parser("status", help="แม่แบบที่มีอยู่ + สินค้าที่เหลือ")
    status.set_defaults(func=cmd_status)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
