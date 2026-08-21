"""แกะโพสต์จาก GraphQL ของ Facebook แบบ **อ่านในก้อนของโพสต์ตัวเอง**

ทำไมต้องเขียนใหม่แทนที่จะใช้ harvest() เดิม:
harvest() จับคู่ตัวเลขกับโพสต์ด้วย "ระยะใกล้ที่สุดในข้อความ" (PAIR_WINDOW 6,000
ตัวอักษร) ซึ่งพิสูจน์แล้วว่าผิดจริง — โพสต์ 597810391561581 ในดัมพ์ 18 ส.ค.
ได้ share=20,528 จากตำแหน่งหนึ่ง แต่ได้ reaction=1 จากอีกสามตำแหน่ง
แล้ว harvest เก็บ max() ของทุกตำแหน่ง → **ค่าผิดที่สูงกว่าชนะเสมอ ยอดเฟ้อทางเดียว**

ที่นี่แปลง JSON เป็นออบเจ็กต์จริงแล้วเดินหา node ที่ `__typename == "Story"`
ค่าทุกช่องอ่านจาก subtree ของ story นั้นเท่านั้น — ข้ามก้อนไม่ได้ในเชิงโครงสร้าง

โครงสร้างจริงที่สำรวจไว้ (dump 18 ส.ค. 2569):
  story.post_id / permalink_url / creation_time
  story.actors[0].name / .url / .id
  story.comet_sections.content.story.message.text          ← caption
  story.attachments[].styles.attachment.media.photo_image.uri   ← รูป
  story.attachments[].styles.attachment.media.accessibility_caption ← คำบรรยายรูป
"""
from __future__ import annotations

import base64
import json
import re
from typing import Any, Iterator

# คีย์ยอดต่างๆ ที่ Facebook ใช้ — อ่านเฉพาะที่อยู่ใน subtree ของ story นั้น
REACTION_KEYS = ("reaction_count", "reactioncount")
COMMENT_KEYS = ("total_comment_count", "aggregated_comment_count",
                "comment_count", "comments")
SHARE_KEYS = ("share_count", "share_count_reduced")
VIEW_KEYS = ("video_view_count", "video_play_count", "play_count",
             "post_view_count", "feedback_view_count")


def iter_nodes(obj: Any) -> Iterator[dict]:
    """เดินทุก dict ในโครงสร้าง JSON (ลึกเท่าไรก็ได้)"""
    stack = [obj]
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            yield cur
            stack.extend(cur.values())
        elif isinstance(cur, list):
            stack.extend(cur)


def load_json_blocks(text: str) -> list:
    """แปลง body หนึ่งก้อนเป็นออบเจ็กต์ — FB ส่งหลาย JSON คั่นบรรทัดได้"""
    out = []
    text = text.strip()
    if not text:
        return out
    try:
        out.append(json.loads(text))
        return out
    except ValueError:
        pass
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
    return out


def _count_of(value: Any) -> int | None:
    """ยอดมาได้หลายทรง: 62 · "62" · {"count":62} · {"total_count":62}"""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    if isinstance(value, dict):
        for key in ("count", "total_count"):
            got = _count_of(value.get(key))
            if got is not None:
                return got
    return None


def _pick_count(story: dict, keys: tuple[str, ...]) -> int | None:
    """หายอดจาก subtree ของ story นี้ — คืน None ถ้าไม่มีเลย (≠ 0)

    None แปลว่า "ไม่รู้" ส่วน 0 แปลว่า "รู้ว่าไม่มี" — ต้องแยกกัน ไม่งั้น
    ตอนวิเคราะห์จะนับโพสต์ที่อ่านค่าไม่ได้ปนกับโพสต์ที่เงียบจริง
    """
    best = None
    for node in iter_nodes(story):
        for key in keys:
            if key in node:
                got = _count_of(node[key])
                if got is not None and (best is None or got > best):
                    best = got
    return best


def _first_str(story: dict, path_end: str, sub: str = "text") -> str:
    """ดึงข้อความจาก node ที่ชื่อคีย์ตรงกับ path_end (เช่น message.text)"""
    for node in iter_nodes(story):
        value = node.get(path_end)
        if isinstance(value, dict) and isinstance(value.get(sub), str):
            return value[sub]
    return ""


def extract_images(story: dict) -> list[dict]:
    """รูปแนบของโพสต์ — เอาเฉพาะรูปจริง ไม่เอาอวาตาร์/ไอคอน

    รูปโพสต์อยู่ใต้ photo_image / viewer_image ส่วนรูปโปรไฟล์อยู่ใต้
    profile_picture ซึ่งเราไม่เก็บเป็นรูปโพสต์
    """
    seen: dict[str, dict] = {}
    for node in iter_nodes(story):
        for key in ("photo_image", "viewer_image", "image"):
            img = node.get(key)
            if not isinstance(img, dict):
                continue
            uri = img.get("uri")
            if not isinstance(uri, str) or "fbcdn" not in uri:
                continue
            width, height = img.get("width") or 0, img.get("height") or 0
            if isinstance(width, int) and width and width < 200:
                continue                      # เล็กเกินไป = ไอคอน/ตัวอย่างย่อ
            key_id = re.sub(r"[?&](oe|oh|_nc_ohc|ccb|stp)=[^&]*", "", uri)
            found = {"uri": uri, "width": width, "height": height,
                     "alt": node.get("accessibility_caption") or ""}
            old = seen.get(key_id)
            if old is None or (found["width"] or 0) > (old["width"] or 0):
                seen[key_id] = found
    return list(seen.values())


def parse_story(story: dict) -> dict | None:
    """แปลง story node หนึ่งก้อนเป็นข้อมูลโพสต์ที่พร้อมเก็บลงฐาน"""
    post_id = story.get("post_id")
    if not post_id:
        return None
    actors = story.get("actors") or []
    actor = actors[0] if isinstance(actors, list) and actors else {}
    avatar = ""
    for node in iter_nodes(story):
        pic = node.get("profile_picture")
        if isinstance(pic, dict) and isinstance(pic.get("uri"), str):
            avatar = pic["uri"]
            break
    caption = _first_str(story, "message")
    images = extract_images(story)
    return {
        "id": str(post_id),
        "url": story.get("permalink_url") or "",
        "posted_at": story.get("creation_time"),
        "author": (actor.get("name") or "").strip(),
        "author_url": actor.get("url") or "",
        "author_id": str(actor.get("id") or ""),
        "avatar": avatar,
        "caption": caption,
        "images": images,
        "reactions": _pick_count(story, REACTION_KEYS),
        "comments": _pick_count(story, COMMENT_KEYS),
        "shares": _pick_count(story, SHARE_KEYS),
        "views": _pick_count(story, VIEW_KEYS),
    }


def merge(old: dict, new: dict) -> dict:
    """รวมโพสต์เดิมกับที่เจอรอบใหม่ — เลือกก้อนที่ "ข้อมูลครบกว่า"

    ห้ามใช้ max() รายช่องแบบโค้ดเดิม เพราะถ้าก้อนไหนอ่านผิดสูงเกินจริง
    ค่าจะค้างสูงตลอดกาลโดยไม่มีทางลง — ที่ถูกคือเชื่อก้อนที่สมบูรณ์กว่า
    """
    def score(p: dict) -> tuple:
        return (sum(1 for k in ("reactions", "comments", "shares")
                    if p.get(k) is not None),
                1 if p.get("caption") else 0,
                len(p.get("images") or []),
                1 if p.get("posted_at") else 0)
    winner, loser = (new, old) if score(new) > score(old) else (old, new)
    out = dict(winner)
    for key, value in loser.items():                 # เติมเฉพาะช่องที่ผู้ชนะว่าง
        if out.get(key) in (None, "", []) and value not in (None, "", []):
            out[key] = value
    return out


# ยอดของโพสต์ **ไม่ได้อยู่ในก้อนเดียวกับตัวโพสต์** — Facebook ทยอยส่งเป็นชิ้นๆ
# (deferred fragment) แล้วผูกกลับด้วย id ที่เข้ารหัส base64 ว่า "feedback:<post_id>"
# ตัวอย่างจริง: ZmVlZGJhY2s6NTk3ODEwMzkxNTYxNTgx → feedback:597810391561581
# ชิ้นหนึ่งมี share_count · อีกชิ้นมี reaction_count · อีกชิ้นมี total_comment_count
# ต้องเก็บทุกชิ้นแล้วประกอบเข้าด้วยกัน ไม่งั้นได้ค่าไม่ครบแล้วนึกว่าโพสต์เงียบ
_FEEDBACK_ID_RE = re.compile(r"^feedback:(\d+)$")


def feedback_post_id(node_id: Any) -> str:
    """ถอด id ของก้อน feedback กลับเป็น post_id — ไม่ใช่ก้อน feedback คืน ''

    id ที่มีขีดล่าง (เช่น feedback:123_456) คือ feedback ของ "คอมเมนต์"
    ไม่ใช่ของโพสต์ ต้องไม่เอามาปนกับยอดของโพสต์
    """
    if not isinstance(node_id, str) or len(node_id) < 12:
        return ""
    try:
        decoded = base64.b64decode(node_id + "==").decode("utf-8", "ignore")
    except Exception:
        return ""
    match = _FEEDBACK_ID_RE.match(decoded)
    return match.group(1) if match else ""


def index_feedback(bodies: list[str]) -> dict[str, dict]:
    """รวบรวมยอดทุกชิ้นของทุกโพสต์ → {post_id: {reactions, comments, shares, views}}"""
    index: dict[str, dict] = {}
    for body in bodies:
        for obj in load_json_blocks(body):
            for node in iter_nodes(obj):
                post_id = feedback_post_id(node.get("id"))
                if not post_id:
                    continue
                slot = index.setdefault(post_id, {})
                for field, keys in (("reactions", REACTION_KEYS),
                                    ("comments", COMMENT_KEYS),
                                    ("shares", SHARE_KEYS),
                                    ("views", VIEW_KEYS)):
                    got = _pick_count(node, keys)
                    if got is None:
                        continue
                    # ชิ้นเดียวกันส่งซ้ำได้ เก็บค่ามากสุด (ยอดขึ้นตามเวลา)
                    if slot.get(field) is None or got > slot[field]:
                        slot[field] = got
    return index


def parse_bodies(bodies: list[str]) -> dict[str, dict]:
    """แกะทุก body → {post_id: โพสต์} พร้อมประกอบยอดจากชิ้นส่วน feedback"""
    posts: dict[str, dict] = {}
    for body in bodies:
        for obj in load_json_blocks(body):
            for node in iter_nodes(obj):
                if node.get("__typename") != "Story":
                    continue
                post = parse_story(node)
                if post is None:
                    continue
                known = posts.get(post["id"])
                posts[post["id"]] = post if known is None else merge(known, post)

    counts = index_feedback(bodies)
    for post_id, post in posts.items():
        slot = counts.get(post_id)
        if not slot:
            continue
        for field in ("reactions", "comments", "shares", "views"):
            value = slot.get(field)
            if value is None:
                continue
            if post.get(field) is None or value > post[field]:
                post[field] = value
    return posts


class FeedParser:
    """แกะฟีดแบบ **ทยอยป้อนทีละก้อน** — ใช้ตอนเลื่อนยาว 1,000 โพสต์

    parse_bodies() ต้องถือ body ทุกก้อนไว้ในหน่วยความจำก่อนแกะ ซึ่งการเจาะลึก
    1,000 โพสต์กิน 200-250 ก้อน (~50-60 MB) พร้อมกัน — เปลืองและเสี่ยงบวม
    คลาสนี้ป้อนทีละก้อนแล้วทิ้งได้ทันที เก็บแค่ผลลัพธ์ที่ย่อแล้ว

    ใช้:
        parser = FeedParser()
        parser.add(body)          # ทุกครั้งที่ได้ response ใหม่
        posts = parser.result()   # {post_id: โพสต์พร้อมยอดครบ}
    """

    def __init__(self) -> None:
        self.posts: dict[str, dict] = {}
        self.counts: dict[str, dict] = {}

    def add(self, text: str) -> None:
        for obj in load_json_blocks(text):
            for node in iter_nodes(obj):
                if node.get("__typename") == "Story":
                    post = parse_story(node)
                    if post is not None:
                        known = self.posts.get(post["id"])
                        self.posts[post["id"]] = (
                            post if known is None else merge(known, post))
                    continue
                post_id = feedback_post_id(node.get("id"))
                if not post_id:
                    continue
                slot = self.counts.setdefault(post_id, {})
                for field, keys in (("reactions", REACTION_KEYS),
                                    ("comments", COMMENT_KEYS),
                                    ("shares", SHARE_KEYS),
                                    ("views", VIEW_KEYS)):
                    got = _pick_count(node, keys)
                    if got is not None and (slot.get(field) is None
                                            or got > slot[field]):
                        slot[field] = got

    def result(self) -> dict[str, dict]:
        for post_id, post in self.posts.items():
            for field, value in (self.counts.get(post_id) or {}).items():
                if post.get(field) is None or value > post[field]:
                    post[field] = value
        return self.posts

    def as_legacy(self) -> list[dict]:
        """แปลงเป็นรูปแบบเดิมที่โค้ดส่วนอื่นใช้อยู่ (likes/comments/shares/views)

        คงชื่อคีย์เดิมไว้เพื่อให้ /find · /test · กราฟ · การตัดสินกลุ่ม ทำงานต่อ
        ได้โดยไม่ต้องแก้ตาม แล้วแถมช่องใหม่ (caption/author/images/posted_at)
        ให้ตัวเก็บข้อมูลใช้
        """
        out = []
        for post in self.result().values():
            out.append({
                "id": post["id"],
                "url": post.get("url") or "",
                "likes": int(post.get("reactions") or 0),
                "comments": int(post.get("comments") or 0),
                "shares": int(post.get("shares") or 0),
                "views": int(post.get("views") or 0),
                # ช่องเสริมสำหรับงานเก็บข้อมูล — ของเดิมไม่แตะ
                "caption": post.get("caption") or "",
                "author": post.get("author") or "",
                "author_url": post.get("author_url") or "",
                "avatar": post.get("avatar") or "",
                "posted_at": post.get("posted_at"),
                "images": post.get("images") or [],
                # จำไว้ว่าช่องไหน "อ่านไม่ได้" (≠ ศูนย์จริง)
                "unknown": [k for k in ("reactions", "comments", "shares")
                            if post.get(k) is None],
            })
        return out


def engagement(post: dict) -> int:
    """ยอดรวม — ช่องที่อ่านไม่ได้นับเป็น 0 แต่จำไว้ว่ามันคือ 'ไม่รู้'"""
    return sum(int(post.get(k) or 0) for k in ("reactions", "comments", "shares"))


# ------------------------------------------------------------- ตัวกรองสแปม
#
# คอมเมนต์สแปมทำให้บทวิเคราะห์ "ฐานลูกค้า" เพี้ยนทั้งชุด (ผู้ใช้สั่งให้กรอง
# 18 ส.ค. 2569) — ตัวอย่างจริงที่เจอ: "#ปล่อยกู้รายเดือน #รับลูกค้าสร้างเครดิต
# ยอดยังว่าง 50000000-500000000 #ดอกร้อยละ29999999บาท"
SPAM_PATTERNS = [
    (r"ปล่อยกู้|เงินกู้|กู้เงิน|กู้ด่วน|สร้างเครดิต|ดอกร้อยละ|วงเงิน\s*\d", 3),
    (r"รับปิดหนี้|หนี้นอกระบบ|เงินด่วน|อนุมัติไว|ไม่เช็คเครดิต|บริการเงินกู้", 3),
    (r"สนใจทัก|ทักแชท|ทักมา|inbox|ไอดีไลน์|line\s*id|แอดไลน์", 1),
    (r"เว็บตรง|สล็อต|บาคาร่า|พนัน|ufabet|สมัครสมาชิกรับ|แทงบอล", 3),
    (r"รับสมัครงานออนไลน์|รายได้เสริม\s*\d|ทำงานที่บ้านรายได้", 2),
    # เพิ่มจากของจริง 19 ส.ค.: เกณฑ์เดิมจับสแปมได้แค่ 2 จาก 9,849 คอมเมนต์
    # ทั้งที่มีสแปมพนันชัดๆ หลุดอยู่ เช่น "อยากรวยไม่ต้องทำงาน แอดไลน์ @wy88"
    # (ได้ 2 คะแนน ต่ำกว่าเกณฑ์ 3) — เติมรูปแบบให้ของจริงดันคะแนนถึงเกณฑ์เอง
    # ดีกว่าลดเกณฑ์ทั้งระบบ ซึ่งจะลากคอมเมนต์ปกติติดไปด้วย
    (r"อยากรวย|ไม่ต้องทำงาน|รวยเร็ว|รวยง่าย|ลงทุนน้อยกำไรงาม", 2),
    (r"\b(?:wy|ufa|pg|sa|ambbet|fun)\d{2,}|แบรนด์แอมบาสเดอร์.*\d", 2),
    (r"@[A-Za-z]{2,}\d{2,}", 2),                     # ไอดีไลน์แนว @wy88
    (r"(?:\d[\d\-\s]{7,}\d)", 1),                    # เบอร์โทร
    (r"#\w+.*#\w+.*#\w+", 1),                        # แฮชแท็กรัวเกิน 3
]
_SPAM_RE = [(re.compile(p, re.I), w) for p, w in SPAM_PATTERNS]
SPAM_THRESHOLD = 3


def spam_score(text: str) -> int:
    """คะแนนความเป็นสแปม — ยิ่งสูงยิ่งน่าจะเป็นสแปม (≥ SPAM_THRESHOLD = ตัดทิ้ง)"""
    if not text:
        return 0
    return sum(weight for regex, weight in _SPAM_RE if regex.search(text))


def is_spam(text: str) -> bool:
    return spam_score(text) >= SPAM_THRESHOLD
