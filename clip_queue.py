"""คิวงานเจนคลิป — วางหลายลิงก์แล้วทำทีละงาน พร้อมจุดหยุดรออนุมัติ

ทำไมต้องมีคิว: เบราว์เซอร์มีโปรไฟล์เดียว (Chrome เปิดโปรไฟล์เดียวกันซ้อนกันไม่ได้)
ถ้าผู้ใช้วางลิงก์รวดเดียว 5 อัน แล้วแต่ละอันเปิดเบราว์เซอร์ของตัวเอง งานหลังจะไล่
หน้าต่างของงานหน้าออกกลางคัน — ทุกงานพังพร้อมกัน

ทำไมสถานะไม่ใช่เส้นตรง: ทุกชิ้นต้องผ่านการอนุมัติจากผู้ใช้ก่อนไปต่อ ตัวรันจึงไม่ได้
ไล่ทำจนจบรวดเดียว แต่ทำถึงจุดที่ต้องให้คนตัดสินแล้ว **หยุดรอ** งานที่หยุดรอไม่กิน
คิว งานถัดไปเดินต่อได้เลย

    queued ─► collecting ─► image_review ─► ready_storyboard ─► making_storyboard
                               (ตรวจรูป)      (รูปผ่านแล้ว)              │
                                                                         ▼
                                                              storyboard_review
                                                               (สตอรีบอร์ด+บทพูด)
                                                                    │       │
                                                       (สั่งแก้) revising    │
                                                                    └───────┤
                                                                            ▼
                                              ready_flow ─► generating ─► video_review
                                                                            │
                                                                            ▼
                                                                           done

"ทำได้เลย" มี 4 สถานะ: queued · ready_storyboard · revising · ready_flow
นอกนั้นคือรอคนกด ตัวรันจะข้ามไป

**ขั้น image_review มีไว้ทำไม** ผู้ใช้ต้องแก้ชุดรูปได้ก่อนส่งเข้า GPT — เพิ่ม/ลบ/
เปลี่ยนรูป เพราะตัวคัดอัตโนมัติเลือกผิดได้ และรูปที่ส่งเข้าไปเป็นตัวกำหนดหน้าตา
ของทั้งคลิป แก้ทีหลังคือต้องทำใหม่ทั้งงาน
"""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Callable

STAGE_QUEUED = "queued"
STAGE_COLLECTING = "collecting"
STAGE_IMAGE_REVIEW = "image_review"          # รอผู้ใช้ตรวจ/แก้ชุดรูปก่อนส่งเข้า GPT
STAGE_READY_STORYBOARD = "ready_storyboard"  # รูปผ่านแล้ว รอทำสตอรีบอร์ด
STAGE_MAKING = "making_storyboard"           # กำลังคุยกับ GPT อยู่
STAGE_STORYBOARD_REVIEW = "storyboard_review"
STAGE_SCRIPT_REVIEW = "script_review"
STAGE_REVISING = "revising"
STAGE_READY_FLOW = "ready_flow"
STAGE_GENERATING = "generating"
STAGE_VIDEO_REVIEW = "video_review"
# สองสถานะล่างนี้ใช้เฉพาะสาย TikTok repost (kind="tiktok") — คลิปผ่านแล้วแต่ยัง
# ต้องยืนยันของอีก 4 อย่างก่อนโพสต์ (Clip · Product ID · #hashtag · คำพูดบนตะกร้า)
# สาย Shopee ไม่ผ่านสองสถานะนี้ กด ✅ ที่คลิปแล้วจบที่ done เหมือนเดิม
STAGE_POST_REVIEW = "tiktok_post_review"
STAGE_POSTING = "tiktok_posting"
STAGE_DONE = "done"
STAGE_FAILED = "failed"
STAGE_CANCELLED = "cancelled"

# สถานะที่ตัวรันหยิบไปทำได้ทันที — ที่เหลือคือรอผู้ใช้กด
ACTIONABLE = {
    STAGE_QUEUED, STAGE_READY_STORYBOARD, STAGE_REVISING, STAGE_READY_FLOW,
    STAGE_POSTING,
}
# สถานะที่ถือว่างานยังไม่จบ ใช้ตอนนับคิวและตอนหางานล่าสุดของแชท
OPEN_STAGES = {
    STAGE_QUEUED, STAGE_COLLECTING, STAGE_IMAGE_REVIEW, STAGE_READY_STORYBOARD,
    STAGE_MAKING,
    STAGE_STORYBOARD_REVIEW, STAGE_SCRIPT_REVIEW, STAGE_REVISING,
    STAGE_READY_FLOW, STAGE_GENERATING, STAGE_VIDEO_REVIEW,
    STAGE_POST_REVIEW, STAGE_POSTING,
}

STAGE_LABEL = {
    STAGE_QUEUED: "รอคิว",
    STAGE_COLLECTING: "กำลังดึงสินค้า",
    STAGE_IMAGE_REVIEW: "รอตรวจชุดรูป",
    STAGE_READY_STORYBOARD: "รอทำสตอรีบอร์ด",
    STAGE_MAKING: "กำลังทำสตอรีบอร์ด + บทพูด",
    # สตอรีบอร์ดกับบทพูดส่งไปพร้อมกันและกดอนุมัติแยกกัน จึงใช้สถานะเดียวคุมทั้งคู่
    # แล้วดูที่ธง storyboard_ok / script_ok ว่าผ่านครบหรือยัง
    STAGE_STORYBOARD_REVIEW: "รออนุมัติสตอรีบอร์ด + บทพูด",
    # เหลือไว้ให้งานรุ่นก่อนที่ยังค้างอยู่ในสถานะนี้เดินต่อได้
    STAGE_SCRIPT_REVIEW: "รออนุมัติบทพูด",
    STAGE_REVISING: "กำลังแก้ตามคำสั่ง",
    STAGE_READY_FLOW: "รอเจนใน Google Flow",
    STAGE_GENERATING: "กำลังเจนคลิป",
    STAGE_VIDEO_REVIEW: "รออนุมัติคลิป",
    STAGE_POST_REVIEW: "รอยืนยันก่อนโพสต์ TikTok",
    STAGE_POSTING: "กำลังโพสต์ขึ้น TikTok",
    STAGE_DONE: "เสร็จแล้ว",
    STAGE_FAILED: "ล้มเหลว",
    STAGE_CANCELLED: "ยกเลิก",
}


class ClipQueueError(RuntimeError):
    """คิวงานเจนคลิปมีปัญหา"""


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class ClipQueue:
    """เก็บคิวลงไฟล์ — รีสตาร์ตเซิร์ฟเวอร์แล้วงานที่ค้างไม่หาย

    งานที่ "กำลังทำอยู่" ตอนเซิร์ฟเวอร์ดับจะค้างสถานะกลางทาง (collecting/generating)
    จึงมี `recover()` ดึงกลับมาเป็นสถานะที่ทำใหม่ได้ตอนเปิดเซิร์ฟเวอร์
    """

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.lock = threading.RLock()
        self.jobs: list[dict] = []
        self._load()

    # ------------------------------------------------------------ ไฟล์

    def _load(self) -> None:
        try:
            self.jobs = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.jobs = []

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".json.tmp")
        temp.write_text(
            json.dumps(self.jobs, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        temp.replace(self.path)

    def recover(self) -> int:
        """งานที่ค้างกลางทางตอนเซิร์ฟเวอร์ดับ → ดึงกลับมาให้ทำใหม่ได้

        ไม่ทำแบบนี้งานจะค้าง "กำลังดึงสินค้า" ตลอดกาล ผู้ใช้รอเก้อโดยไม่มีอะไรฟ้อง
        """
        back = {
            STAGE_COLLECTING: STAGE_QUEUED,
            STAGE_MAKING: STAGE_READY_STORYBOARD,
            STAGE_GENERATING: STAGE_READY_FLOW,
            # ดับตอนกำลังโพสต์ = **ไม่รู้ว่าโพสต์ขึ้นไปแล้วหรือยัง** ห้ามยิงซ้ำเอง
            # เพราะโพสต์ TikTok ซ้ำแล้วเรียกคืนไม่ได้ ส่งกลับไปให้คนตัดสินแทน
            STAGE_POSTING: STAGE_POST_REVIEW,
        }
        notes = {
            STAGE_POSTING: (
                "เซิร์ฟเวอร์ดับระหว่างโพสต์ — เช็คใน TikTok ก่อนว่าขึ้นไปแล้วหรือยัง "
                "ค่อยกดโพสต์ซ้ำ"
            ),
        }
        moved = 0
        with self.lock:
            for job in self.jobs:
                if job.get("stage") in back:
                    was = job["stage"]
                    job["stage"] = back[was]
                    job["note"] = notes.get(
                        was, "เซิร์ฟเวอร์รีสตาร์ตระหว่างทำ — เอากลับเข้าคิวใหม่"
                    )
                    job["updated_at"] = _now()
                    moved += 1
            if moved:
                self._save()
        return moved

    # ------------------------------------------------------------ เขียน

    def add(self, link: str, chat_id: str) -> dict:
        with self.lock:
            job = {
                "id": f"{int(time.time() * 1000):x}{len(self.jobs):02x}",
                "link": link,
                "chat_id": str(chat_id),
                "stage": STAGE_QUEUED,
                "item_id": "",
                "name": "",
                "storyboard_ok": False,
                "script_ok": False,
                "pending_edit": None,
                "note": "",
                "error": "",
                "created_at": _now(),
                "updated_at": _now(),
            }
            self.jobs.append(job)
            self._save()
            return dict(job)

    def update(self, job_id: str, **fields) -> dict:
        with self.lock:
            for job in self.jobs:
                if job["id"] == job_id:
                    job.update(fields)
                    job["updated_at"] = _now()
                    self._save()
                    return dict(job)
        raise ClipQueueError(f"ไม่พบงาน {job_id}")

    def claim_next(self) -> dict | None:
        """หยิบงานที่ทำได้ทันทีมาหนึ่งงาน แล้วตั้งสถานะ "กำลังทำ" ทันทีในล็อกเดียว

        ต้องเปลี่ยนสถานะในล็อกเดียวกับตอนหยิบ ไม่งั้นถ้ามีตัวรันสองตัว (หรือกดสั่ง
        ซ้ำเร็วๆ) จะหยิบงานเดียวกันไปทำพร้อมกัน แล้วแย่งเบราว์เซอร์กันเอง
        """
        moving = {
            STAGE_QUEUED: STAGE_COLLECTING,
            STAGE_READY_STORYBOARD: STAGE_MAKING,
            STAGE_REVISING: STAGE_REVISING,
            STAGE_READY_FLOW: STAGE_GENERATING,
            # ทุกสถานะใน ACTIONABLE ต้องมีคู่ในตารางนี้ ไม่งั้น KeyError ตอนหยิบงาน
            STAGE_POSTING: STAGE_POSTING,
        }
        with self.lock:
            for job in self.jobs:
                if job.get("stage") in ACTIONABLE:
                    was = job["stage"]
                    job["stage"] = moving[was]
                    job["claimed_from"] = was
                    job["updated_at"] = _now()
                    self._save()
                    return dict(job)
        return None

    def move(self, job_id: str, delta: int) -> dict:
        """เลื่อนลำดับงานที่ยัง "รอคิว" อยู่

        เลื่อนได้เฉพาะในกลุ่ม queued ด้วยกันเท่านั้น — งานที่เริ่มไปแล้วมีของค้าง
        อยู่ในเครื่อง (โฟลเดอร์สินค้า แชท GPT ที่เปิดไว้) การสลับตำแหน่งมันไม่ได้
        ทำให้เกิดอะไรขึ้นจริง มีแต่ทำให้รายการที่ผู้ใช้เห็นไม่ตรงกับความจริง
        """
        with self.lock:
            slots = [i for i, j in enumerate(self.jobs) if j.get("stage") == STAGE_QUEUED]
            here = next((k for k, i in enumerate(slots) if self.jobs[i]["id"] == job_id), None)
            if here is None:
                raise ClipQueueError("เลื่อนได้เฉพาะงานที่ยังรอคิวอยู่")
            there = here + (1 if delta > 0 else -1)
            if not 0 <= there < len(slots):
                raise ClipQueueError("อยู่สุดทางแล้ว")
            a, b = slots[here], slots[there]
            self.jobs[a], self.jobs[b] = self.jobs[b], self.jobs[a]
            self._save()
            return dict(self.jobs[b])

    def remove(self, job_id: str) -> bool:
        """ลบงานออกจากคิวถาวร — ใช้กับงานที่จบแล้วเท่านั้น

        ไม่แตะโฟลเดอร์งานในดิสก์ ของที่ทำไว้ยังอยู่ครบและยังเปิดดูได้จาก
        รายการ "งานที่เก็บไว้" — ลบตรงนี้คือลบแค่แถวในคิว
        """
        with self.lock:
            job = next((j for j in self.jobs if j["id"] == job_id), None)
            if job is None:
                raise ClipQueueError(f"ไม่พบงาน {job_id}")
            if job.get("stage") in OPEN_STAGES:
                raise ClipQueueError("งานนี้ยังไม่จบ — ยกเลิกก่อนถึงจะลบได้")
            self.jobs = [j for j in self.jobs if j["id"] != job_id]
            self._save()
            return True

    def prune(self, keep: int = 60) -> int:
        """ตัดงานที่จบแล้วให้เหลือเท่าที่กำหนด — ไฟล์คิวจะได้ไม่โตไม่หยุด"""
        with self.lock:
            closed = [j for j in self.jobs if j.get("stage") not in OPEN_STAGES]
            if len(closed) <= keep:
                return 0
            drop = {id(j) for j in closed[: len(closed) - keep]}
            before = len(self.jobs)
            self.jobs = [j for j in self.jobs if id(j) not in drop]
            self._save()
            return before - len(self.jobs)

    # ------------------------------------------------------------- อ่าน

    def get(self, job_id: str) -> dict | None:
        with self.lock:
            return next((dict(j) for j in self.jobs if j["id"] == job_id), None)

    def all(self) -> list[dict]:
        with self.lock:
            return [dict(j) for j in self.jobs]

    def waiting(self) -> list[dict]:
        with self.lock:
            return [dict(j) for j in self.jobs if j.get("stage") in OPEN_STAGES]

    def latest_for_chat(self, chat_id: str, stages: set[str] | None = None) -> dict | None:
        """งานล่าสุดของแชทนี้ที่อยู่ในสถานะที่สนใจ

        ใช้ตอนผู้ใช้พิมพ์คำสั่งแก้เข้ามาเฉยๆ โดยไม่ได้ระบุว่างานไหน — ผูกกับงาน
        ที่เพิ่งคุยกันอยู่ ไม่ใช่ให้ผู้ใช้ต้องจำรหัสงาน
        """
        with self.lock:
            found = [
                j for j in self.jobs
                if str(j.get("chat_id")) == str(chat_id)
                and (stages is None or j.get("stage") in stages)
            ]
        return dict(found[-1]) if found else None


class ClipRunner:
    """ตัวรันงานในคิว — ทีละงานเท่านั้น

    เดินอยู่ตัวเดียวตลอดอายุเซิร์ฟเวอร์ ปลุกด้วย `wake()` เมื่อมีงานใหม่หรือมีคนกด
    อนุมัติ ไม่ได้ใช้การวนถามถี่ๆ เพราะงานเจนคลิปนานเป็นนาที ไม่ต้องรีบ
    """

    def __init__(self, queue: ClipQueue, handler: Callable[[dict], None], log=print) -> None:
        self.queue = queue
        self.handler = handler
        self.log = log
        self.signal = threading.Event()
        self.thread: threading.Thread | None = None
        self.current = ""

    def start(self) -> None:
        if self.thread and self.thread.is_alive():
            return
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def wake(self) -> None:
        self.signal.set()

    @property
    def busy(self) -> bool:
        return bool(self.current)

    def _loop(self) -> None:
        while True:
            job = self.queue.claim_next()
            if not job:
                # รอสัญญาณ แต่ตื่นเองทุก 30 วิด้วย เผื่อมีคนแก้ไฟล์คิวจากข้างนอก
                self.signal.wait(timeout=30)
                self.signal.clear()
                continue
            self.current = job["id"]
            try:
                self.handler(job)
            except Exception as error:
                # งานหนึ่งพังต้องไม่ทำให้ตัวรันตายทั้งตัว งานที่เหลือในคิวต้องเดินต่อ
                self.log(f"งาน {job['id']} ล้มเหลว: {type(error).__name__}: {error}")
                try:
                    self.queue.update(
                        job["id"], stage=STAGE_FAILED, error=str(error)[:400]
                    )
                except ClipQueueError:
                    pass
            finally:
                self.current = ""
