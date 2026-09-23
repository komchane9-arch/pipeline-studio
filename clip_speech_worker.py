# -*- coding: utf-8 -*-
"""ถอดเสียงพูดจากคลิปด้วย faster-whisper — **รันใน `_vision_env` เท่านั้น**

⚠️ ไฟล์นี้ห้าม import อะไรจากโปรเจกต์เลยสักตัว เพราะมันรันด้วย Python คนละตัว
กับตัวหลัก (`_vision_env`) ซึ่งไม่มีไลบรารีของโปรเจกต์อยู่ — เหมือน
`clip_human_worker.py` ที่ทำแบบเดียวกัน

รับพาธคลิปทาง argv แล้วพิมพ์ผลออกมาเป็น JSON บรรทัดเดียวทาง stdout
"""
import json
import sys
import time

# ขนาดโมเดลที่เลือก — วัดกับคลิปจริง 3 ใบเทียบกับ **บทพูดต้นฉบับ** เมื่อ 23 ก.ย. 2569
#
#     small      ตรงบท 82%   3.5 วินาที/คลิป
#     medium     ตรงบท 85%   9.2 วินาที/คลิป
#     large-v3   ตรงบท 86%  15.7 วินาที/คลิป   <- เจ้าของเลือกตัวนี้เอง
#     Gemini     ตรงบท 85%   (ของเดิม ต้องใช้เครดิตและล่มบ่อย)
#
# **ตัวเลขขยับนิดเดียวแต่คุณภาพต่างกันชัด** เพราะคะแนนนับเป็นตัวอักษร และบทใน
# run.json มีขีดคั่นคำ ("เติม-บ่อยๆ") ซึ่งไม่มีในเสียงจริง คะแนนจึงติดเพดาน
# ดูที่คำสำคัญจะเห็นชัดกว่า
#
#     คำจริง        small        medium       large-v3
#     ใกล้ๆ         ไกลๆ  ผิด    ไกลๆ  ผิด    ใกล้ๆ  ถูก
#     ฉุน           ชุน   ผิด    ชุ่น   ผิด    ฉุน    ถูก
#     แท็บเล็ต      แทบเลด ผิด   แทปเลต ผิด   แท็บเล็ต ถูก
#     ออกไปข้างนอก  หอกไป  ผิด   ออกไป ถูก    ออกไป  ถูก
#
# คำที่ถอดผิดจะทำให้ด่านเทียบกับบทตัดสินผิดตาม จึงคุ้มที่จะยอมช้าขึ้น
MODEL_SIZE = "large-v3"

# เงียบแค่ไหนถึงถือว่าไม่มีคนพูด — ไม่ได้ดูความดัง แต่ดูว่าถอดได้เป็นคำไหม
MIN_CHARS = 4


def main(argv: list[str]) -> int:
    if not argv:
        print(json.dumps({"ok": False, "why": "ไม่ได้บอกว่าจะถอดไฟล์ไหน"}))
        return 2
    clip = argv[0]
    want_lang = argv[1] if len(argv) > 1 else "th"

    try:
        from faster_whisper import WhisperModel
    except Exception as error:                                   # noqa: BLE001
        print(json.dumps({"ok": False,
                          "why": f"ไม่มี faster-whisper ใน _vision_env: {error}"},
                         ensure_ascii=False))
        return 3

    began = time.perf_counter()
    try:
        model = WhisperModel(MODEL_SIZE, device="cpu", compute_type="int8")
        load_seconds = time.perf_counter() - began

        began = time.perf_counter()
        segments, info = model.transcribe(clip, language=want_lang, beam_size=5)
        parts = [s.text for s in segments]
        text = "".join(parts).strip()
        took = time.perf_counter() - began
    except Exception as error:                                   # noqa: BLE001
        print(json.dumps({"ok": False,
                          "why": f"{type(error).__name__}: {str(error)[:300]}"},
                         ensure_ascii=False))
        return 4

    letters = [c for c in text if not c.isspace()]
    print(json.dumps({
        "ok": True,
        "engine": f"faster-whisper {MODEL_SIZE} (ในเครื่อง)",
        "transcript": text,
        # **ถอดไม่ได้สักตัว = ไม่มีเสียงพูด** ไม่ใช่ "ตรวจไม่ได้" เพราะตัวถอด
        # ทำงานสำเร็จแล้วและบอกว่าไม่ได้ยินคำพูด ซึ่งเป็นคำตอบที่แน่นอน
        "has_speech": len(letters) >= MIN_CHARS,
        "language": info.language,
        "language_probability": round(float(info.language_probability), 3),
        "segments": len(parts),
        "load_seconds": round(load_seconds, 1),
        "seconds": round(took, 1),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
