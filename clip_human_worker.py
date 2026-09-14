"""ตัวตรวจมือ/คนในคลิป — **รันในสภาพแวดล้อมแยก `_vision_env` เท่านั้น**

รับงานทาง stdin เป็น JSON แล้วตอบกลับทาง stdout บรรทัดละหนึ่งใบ

    {"jobs": [[item_id, video_path], ...], "frames": 8, "keep_frames": ""}
    -> {"item_id": "...", "has_human": true, "hands": 3, "people": 5, ...}

**ห้ามให้ไฟล์นี้ import อะไรจากโปรเจกต์** เพราะ Python ของ venv นี้ใช้
numpy 2.x กับ cv2 5.x ซึ่งคนละรุ่นกับที่ Python หลักใช้ (numpy 1.26 · cv2 4.9)
ปนกันเมื่อไรพังทั้งสองฝั่ง — เคยเกิดจริง 14 ก.ย. 2569 ตอนลงทับของเดิม

ตัวตรวจสองชั้น ทั้งคู่ตอบคำถามแคบๆ ข้อเดียว จึงเร็วกว่า LLM หลายสิบเท่า

    MediaPipe Hands   หามือคนโดยเฉพาะ — คลิปสินค้าของเรามักเห็นแค่มือ ไม่เห็นตัว
    YOLO (yolo11n)    หาคนทั้งตัว — เผื่อคลิปที่มีคนแต่มือไม่ชัด

**นับว่ามีคนเมื่อเจออย่างใดอย่างหนึ่ง** เพราะโจทย์คือ "มีมือในฉาก หรือ มีคนในฉาก"
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import cv2
import numpy as np


# ความมั่นใจขั้นต่ำ — ตั้งค่อนข้างสูงเพื่อไม่ให้เงา/ลายไม้ถูกนับเป็นมือ
HAND_CONFIDENCE = 0.6
PERSON_CONFIDENCE = 0.45


def sample_frames(video: str, want: int) -> list[np.ndarray]:
    """ดึงเฟรมกระจายทั้งความยาวคลิป — ไม่เอาเฉพาะช่วงต้นซึ่งมักเป็นภาพปก"""
    cap = cv2.VideoCapture(video)
    if not cap.isOpened():
        return []
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    frames: list[np.ndarray] = []
    if total <= 0:
        while len(frames) < want:
            ok, frame = cap.read()
            if not ok:
                break
            frames.append(frame)
        cap.release()
        return frames
    for index in range(want):
        at = int(total * (index + 0.5) / want)
        cap.set(cv2.CAP_PROP_POS_FRAMES, at)
        ok, frame = cap.read()
        if ok and frame is not None:
            frames.append(frame)
    cap.release()
    return frames


def main() -> int:
    payload = json.loads(sys.stdin.read() or "{}")
    jobs = payload.get("jobs") or []
    want = int(payload.get("frames") or 8)
    keep = str(payload.get("keep_frames") or "")
    keep_dir = Path(keep) if keep else None
    if keep_dir:
        keep_dir.mkdir(parents=True, exist_ok=True)

    import mediapipe as mp
    from ultralytics import YOLO

    hands = mp.solutions.hands.Hands(
        static_image_mode=True, max_num_hands=2,
        min_detection_confidence=HAND_CONFIDENCE)
    yolo = YOLO("yolo11n.pt")

    import time
    for item_id, video in jobs:
        started = time.time()
        frames = sample_frames(video, want)
        hand_hits = person_hits = 0
        for index, frame in enumerate(frames):
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            if (hands.process(rgb).multi_hand_landmarks or None):
                hand_hits += 1
            found = yolo.predict(frame, classes=[0], conf=PERSON_CONFIDENCE,
                                 verbose=False)
            if found and len(found[0].boxes):
                person_hits += 1
            if keep_dir is not None:
                small = cv2.resize(frame, (270, int(frame.shape[0] * 270 / frame.shape[1])))
                cv2.imwrite(str(keep_dir / f"{item_id}-{index}.jpg"), small)
        print(json.dumps({
            "item_id": item_id,
            "has_human": bool(hand_hits or person_hits),
            "hands": hand_hits,
            "people": person_hits,
            "frames": len(frames),
            "seconds": round(time.time() - started, 2),
        }, ensure_ascii=False), flush=True)
    hands.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
