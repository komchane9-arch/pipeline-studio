"""สรุปว่าอะไรเวิร์ก — เอาข้อมูลที่เก็บมาตลอดไปใช้ตัดสินใจจริง

**ปัญหาที่แก้** ระบบเก็บผลทุกกลุ่มทุกงานมาตั้งแต่ต้น แต่ไม่เคยมีใครสรุปให้เลย
เลยไม่มีใครตอบได้ว่ากลุ่มไหนโพสต์ไปแล้วเงียบสนิท ควรตัดออกจากชุดหรือยัง
ทั้งที่ข้อมูลอยู่ในมือครบ

**ตัวชี้วัดหลักคือ "โพสต์ขึ้นจริงไหม" ไม่ใช่ "กดโพสต์สำเร็จไหม"**

กดโพสต์สำเร็จแปลว่าแค่ส่งเข้าไปได้ ส่วนโพสต์จะขึ้นจริงหรือค้างรอผู้ดูแลอนุมัติ
เป็นคนละเรื่อง — กลุ่มที่ "โพสต์สำเร็จ 100%" แต่ไม่เคยเปิดโพสต์เจอเลยสักครั้ง
คือกลุ่มที่เสียเวลาเปล่า ตัวเลขที่ใช้ตัดสินจึงต้องเป็นตัวหลัง

    เข้าถึงได้ = เปิดหน้าโพสต์เจอ (เก็บลิงก์ได้ หรือกดถูกใจ/คอมเมนต์ได้)
                 นี่คือหลักฐานว่าโพสต์ขึ้นจริง

ยอดถูกใจ/คอมเมนต์ของคนอื่นมาจาก `fb_post_stats.json` ซึ่งบอทสายเก็บยอดเป็นคนเขียน
ยังไม่มีไฟล์นั้นก็รายงานส่วนที่เหลือไปตามปกติ ไม่ใช่ล้มทั้งรายงาน
"""

from __future__ import annotations

from datetime import datetime, timedelta

import studio_shared

STATS_FILE = studio_shared.post_file("fb_post_stats.json")

DEFAULT_DAYS = 30
# กลุ่มที่โพสต์ไปกี่ครั้งขึ้นไปถึงจะเอามาตัดสิน — น้อยกว่านี้ยังไม่พอสรุป
MIN_POSTS_TO_JUDGE = 3
# เข้าถึงได้ต่ำกว่านี้ = ควรพิจารณาตัดกลุ่มออก
POOR_REACH = 0.34

# น้ำหนักคะแนน "แมส" — คอมเมนต์กับแชร์แพงกว่าไลก์เพราะต้องออกแรงมากกว่า
# (ใช้ชุดเดียวกับ fb_engage.mass_report จะได้ไม่มีสองมาตรฐานในระบบเดียว)
WEIGHT_REACTION = 1
WEIGHT_COMMENT = 3
WEIGHT_SHARE = 5


def _parse(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat((value or "").strip())
    except ValueError:
        return None


def _job_time(job: dict) -> datetime | None:
    for key in ("started_at", "finished_at", "created_at"):
        found = _parse(job.get(key, ""))
        if found:
            return found
    return None


def reached(result: dict) -> bool:
    """เปิดหน้าโพสต์เจอไหม — หลักฐานว่าโพสต์ขึ้นจริง"""
    return bool(result.get("link") or result.get("liked") or result.get("commented"))


def _in_window(job: dict, now: datetime, days: int) -> bool:
    when = _job_time(job)
    return when is not None and timedelta(0) <= now - when <= timedelta(days=days)


def group_report(jobs: list[dict], days: int = DEFAULT_DAYS,
                 now: datetime | None = None) -> list[dict]:
    """สรุปรายกลุ่ม เรียงจากกลุ่มที่ควรเก็บไว้ที่สุดลงไป"""
    now = now or datetime.now()
    table: dict[str, dict] = {}
    for job in jobs:
        if not _in_window(job, now, days):
            continue
        when = _job_time(job)
        for result in job.get("results", []):
            group_id = str(result.get("group_id", ""))
            if not group_id:
                continue
            row = table.setdefault(group_id, {
                "group_id": group_id, "tried": 0, "posted": 0, "reached": 0,
                "liked": 0, "commented": 0, "last_post": None,
            })
            row["tried"] += 1
            if not result.get("posted"):
                continue
            row["posted"] += 1
            if when and (row["last_post"] is None or when > row["last_post"]):
                row["last_post"] = when
            if reached(result):
                row["reached"] += 1
            if result.get("liked"):
                row["liked"] += 1
            if result.get("commented"):
                row["commented"] += 1
    rows = []
    for row in table.values():
        posted = row["posted"]
        row["reach_rate"] = row["reached"] / posted if posted else 0.0
        row["post_rate"] = row["posted"] / row["tried"] if row["tried"] else 0.0
        row["stuck"] = posted - row["reached"]
        row["judged"] = posted >= MIN_POSTS_TO_JUDGE
        row["poor"] = row["judged"] and row["reach_rate"] < POOR_REACH
        rows.append(row)
    return sorted(rows, key=lambda r: (-r["reach_rate"], -r["posted"]))


def hour_report(jobs: list[dict], days: int = DEFAULT_DAYS,
                now: datetime | None = None) -> list[dict]:
    """โพสต์ช่วงไหนแล้วขึ้นจริงมากกว่ากัน

    แบ่งเป็นช่วงละ 3 ชั่วโมง ไม่ใช่รายชั่วโมง — ข้อมูลมีหลักสิบงาน แยกเป็น 24 ช่อง
    แล้วแต่ละช่องเหลือหนึ่งถึงสองงาน ซึ่งอ่านเป็นแนวโน้มอะไรไม่ได้เลย
    """
    now = now or datetime.now()
    buckets: dict[int, dict] = {}
    for job in jobs:
        if not _in_window(job, now, days):
            continue
        when = _job_time(job)
        slot = (when.hour // 3) * 3
        row = buckets.setdefault(slot, {"hour": slot, "posted": 0, "reached": 0,
                                        "jobs": 0})
        row["jobs"] += 1
        for result in job.get("results", []):
            if not result.get("posted"):
                continue
            row["posted"] += 1
            if reached(result):
                row["reached"] += 1
    rows = []
    for row in buckets.values():
        row["reach_rate"] = row["reached"] / row["posted"] if row["posted"] else 0.0
        row["label"] = f"{row['hour']:02d}:00-{(row['hour'] + 3) % 24:02d}:00"
        rows.append(row)
    return sorted(rows, key=lambda r: r["hour"])


def load_stats() -> dict:
    return studio_shared.read_json(STATS_FILE, {}) or {}


def engagement_report(stats: dict | None = None, top: int = 5) -> list[dict]:
    """โพสต์ไหนได้ยอดดีที่สุด — ต้องมี fb_post_stats.json ถึงจะมีข้อมูล"""
    stats = stats if stats is not None else load_stats()
    rows = []
    for key, record in stats.items():
        history = record.get("history") or []
        if not history:
            continue
        last = history[-1]
        reactions = int(last.get("reactions") or 0)
        comments = int(last.get("comments") or 0)
        shares = int(last.get("shares") or 0)
        rows.append({
            "key": key,
            "group_id": record.get("group_id", ""),
            "job_id": record.get("job_id", ""),
            "caption": (record.get("caption") or "")[:50],
            "link": record.get("link", ""),
            "reactions": reactions, "comments": comments, "shares": shares,
            "score": (reactions * WEIGHT_REACTION + comments * WEIGHT_COMMENT
                      + shares * WEIGHT_SHARE),
        })
    return sorted(rows, key=lambda r: -r["score"])[:top]


def post_report(jobs: list[dict], days: int = DEFAULT_DAYS,
                now: datetime | None = None, stats: dict | None = None,
                top: int = 8) -> list[dict]:
    """รายโพสต์ (รายงาน) ในกรอบเวลา — เรียงจากที่น่าสนใจที่สุด

    **เรียงรายงาน ไม่ใช่รายกลุ่ม** เพราะหนึ่งงานลงหลายกลุ่ม ถ้าเรียงรายกลุ่มจะได้
    โพสต์เดียวกันโผล่หกครั้งจนกดดูไม่ถูกใบ

    ถ้ามียอดปฏิสัมพันธ์ (`fb_post_stats.json`) เรียงตามคะแนน ถ้ายังไม่มี
    เรียงตามเวลาล่าสุด — ไม่ใช่ซ่อนรายการทิ้งเพราะยังไม่มีตัวเลข
    """
    now = now or datetime.now()
    scores: dict[str, int] = {}
    for row in engagement_report(stats, top=999):
        job_id = row.get("job_id", "")
        if job_id:
            scores[job_id] = scores.get(job_id, 0) + row["score"]

    rows = []
    for job in jobs:
        if not _in_window(job, now, days):
            continue
        results = job.get("results") or []
        posted = sum(1 for r in results if r.get("posted"))
        if not posted:
            continue
        when = _job_time(job)
        images = [p for p in (job.get("images") or [job.get("image", "")]) if p]
        comment_shots = [p for p in (job.get("comment_images") or []) if p]
        rows.append({
            "job_id": job["id"],
            "caption": (job.get("caption") or "").strip(),
            "when": when,
            "posted": posted,
            "reached": sum(1 for r in results if r.get("posted") and reached(r)),
            "images": len(images),
            "comment_images": len(comment_shots),
            "score": scores.get(job["id"], 0),
        })
    rows.sort(key=lambda r: (-r["score"], -(r["when"].timestamp() if r["when"] else 0)))
    return rows[:top]


def post_line(row: dict) -> str:
    """ป้ายสั้นสำหรับปุ่มกด — ต้องอ่านออกว่าโพสต์ไหนภายในความกว้างปุ่มเดียว"""
    when = f"{row['when']:%d/%m %H:%M}" if row["when"] else "?"
    head = row["caption"].splitlines()[0][:24] if row["caption"] else "(ไม่มีแคปชัน)"
    score = f" · {row['score']}" if row["score"] else ""
    return f"📷 {when} · {head}{score}"


def build(jobs: list[dict], days: int = DEFAULT_DAYS, label=None,
          now: datetime | None = None, stats: dict | None = None) -> str:
    """รายงานฉบับเต็มสำหรับ Telegram"""
    now = now or datetime.now()
    naming = label or (lambda g: g)
    groups = group_report(jobs, days=days, now=now)
    if not groups:
        return f"📊 ยังไม่มีข้อมูลงานใน {days} วันที่ผ่านมา"

    posted = sum(r["posted"] for r in groups)
    got = sum(r["reached"] for r in groups)
    jobs_in = sum(1 for j in jobs if _in_window(j, now, days))
    lines = [
        f"📊 <b>สรุป {days} วันที่ผ่านมา</b>",
        f"งาน {jobs_in} งาน · โพสต์ {posted} ครั้ง · "
        f"ขึ้นจริง {got} ({got / posted * 100:.0f}%)" if posted else "ยังไม่มีโพสต์",
        "",
        "<b>รายกลุ่ม</b> (ขึ้นจริง / โพสต์)",
    ]
    for row in groups[:10]:
        mark = "🔴" if row["poor"] else ("🟢" if row["reach_rate"] >= 0.8 else "🟡")
        note = "" if row["judged"] else " <i>(ยังน้อยเกินสรุป)</i>"
        lines.append(
            f"{mark} {naming(row['group_id'])} — {row['reached']}/{row['posted']}"
            f" ({row['reach_rate'] * 100:.0f}%){note}"
        )
    poor = [r for r in groups if r["poor"]]
    if poor:
        names = " · ".join(naming(r["group_id"]) for r in poor[:5])
        lines += ["", f"🔴 <b>ควรพิจารณาตัดออก</b>: {names}",
                  f"<i>โพสต์แล้วเปิดไม่เจอเกิน {(1 - POOR_REACH) * 100:.0f}% "
                  f"ของครั้งที่โพสต์</i>"]

    hours = [h for h in hour_report(jobs, days=days, now=now) if h["posted"] >= 3]
    if hours:
        best = max(hours, key=lambda h: h["reach_rate"])
        lines += ["", "<b>ช่วงเวลา</b> (ขึ้นจริง / โพสต์)"]
        for row in hours:
            star = " ⭐" if row is best else ""
            lines.append(
                f"· {row['label']} — {row['reached']}/{row['posted']}"
                f" ({row['reach_rate'] * 100:.0f}%){star}"
            )

    best_posts = engagement_report(stats, top=5)
    if best_posts:
        lines += ["", "<b>โพสต์ที่ยอดดีที่สุด</b>"]
        for row in best_posts:
            lines.append(
                f"· {naming(row['group_id'])} — ❤️{row['reactions']} "
                f"💬{row['comments']} 🔁{row['shares']} (คะแนน {row['score']})\n"
                f"     <i>{row['caption']}</i>"
            )
    else:
        lines += ["", "<i>ยังไม่มียอดถูกใจ/คอมเมนต์ของคนอื่น — "
                  "ต้องให้บอทสายเก็บยอดทำงานก่อน</i>"]

    if post_report(jobs, days=days, now=now, stats=stats):
        lines += ["", "<i>กดปุ่มข้างล่างเพื่อดูรูปของโพสต์นั้น "
                  "(ทั้งรูปในโพสต์และรูปในคอมเมนต์)</i>"]
    return "\n".join(lines)
