"""ตรวจใหม่ว่าสินค้าใน TikTok Shop ตรงกับใบงานไหม — **จากภาพหลักฐานเดิม**

ไม่แตะมือถือ ไม่ค้นใหม่ ไม่เพิ่มอะไรเข้าโชว์เคส — หยิบภาพที่เคยแคปไว้ตอนค้นจริง
มาให้ตัวดูรูปตัดสินใหม่ด้วยเกณฑ์ปัจจุบัน แล้วบอกว่าผลต่างจากที่จดไว้เดิมยังไง

**มีไว้เพราะการเปลี่ยนเกณฑ์ตัดสินต้องวัดผลได้ก่อนเชื่อ** เจ้าของสั่งเปลี่ยนเกณฑ์
เป็นสองชั้นเมื่อ 13 ก.ย. 2569 แล้วสั่งว่า "ลองรีเช็คทั้ง 55 ใบ แล้วรายงานผมหน่อย"
— ถ้าต้องไปค้นใหม่บนเครื่องจริงจะกินเวลาหลายชั่วโมงและแย่งคิวจอ ทั้งที่ภาพที่ใช้
ตัดสินเก็บไว้ครบอยู่แล้วทุกใบ

ผลที่วัดได้รอบแรก (53 ใบ · 124 นาที · เฉลี่ยใบละ 140 วินาที)

    เกณฑ์เดิม   เจอ  0 ใบ
    เกณฑ์ใหม่   เจอ 42 ใบ — **ทั้งหมดเจอที่ชั้นที่ 1 (รหัสรุ่นตรง)**
                ชั้นที่ 2 ไม่ได้ทำงานเลยสักใบ

วิธีใช้

    python tiktok_link_recheck.py            ตรวจทุกใบที่ยังหาไม่เจอ
    python tiktok_link_recheck.py 5          ลอง 5 ใบก่อน

ผลเขียนลง ``%TEMP%/recheck.json`` **ไม่แตะใบงานจริง** ถ้าจะบันทึกผลใหม่ลงใบงาน
ต้องสั่งแยกอีกที (ตั้งใจให้แยก เพราะการเปลี่ยนสถานะใบงานมีผลกับสายโพสต์จริง)

⚠️ ตัวดูรูปตอบไม่ได้เป็นครั้งคราว วัดรอบแรกได้ 5 จาก 53 ใบ (9%) — ผลแบบนั้นคือ
**"ยังไม่ได้ตรวจ" ไม่ใช่ "ตรวจแล้วไม่มี"** อย่าเอาไปนับรวมกัน (กติกา 2.3.1)
"""

import os, sys, json, time, tempfile
sys.path.insert(0, os.getcwd())
from pathlib import Path
import clip_store, studio_shared as shared, tiktok_product_link as tpl

D = shared.DATA_DIR
runs = clip_store.list_runs(D) + clip_store.list_done(D)
todo = []
seen = set()
for r in runs:
    item = str(r.get("item_id") or "")
    link = r.get("tiktok_product_link") or {}
    if not item or item in seen: continue
    if link.get("matched_rank") != 0 or link.get("showcase_added"): continue
    seen.add(item)
    todo.append((item, r, link))

limit = int(sys.argv[1]) if len(sys.argv) > 1 else len(todo)
print(f"ใบที่จะรีเช็ค {len(todo)} ใบ · รอบนี้ทำ {min(limit, len(todo))} ใบ", flush=True)

out = []
tmp = Path(tempfile.mkdtemp(prefix="recheck-"))
for n, (item, run, link) in enumerate(todo[:limit], 1):
    folder = Path(str(run.get("folder") or ""))
    names = [str(p).replace("\\", "/") for p in (link.get("results_images") or [])]
    ref = folder / str(link.get("reference_image") or "")
    files = [folder / x for x in names]
    if len(files) != 2 or not all(f.is_file() for f in files) or not ref.is_file():
        out.append({"item": item, "skip": "ภาพไม่ครบ"}); continue
    t0 = time.time()
    try:
        vision = tpl.analyze_four(ref, files[0], files[1],
                                  str(run.get("name") or ""), tmp,
                                  str(link.get("results_layout") or "visual"))
    except Exception as error:
        out.append({"item": item, "skip": f"{type(error).__name__}: {error}"[:80]}); continue
    rank = tpl.confident_rank(vision, link.get("reference_check") or {})
    out.append({
        "item": item,
        "name": str(run.get("name") or "")[:42],
        "new_match": vision.get("match"),
        "new_conf": vision.get("confidence"),
        "chosen": rank,
        "reason": str(vision.get("reason") or "")[:110],
        "secs": round(time.time() - t0, 1),
    })
    print(f"  [{n}/{min(limit,len(todo))}] {item} -> เลือก {rank} "
          f"({vision.get('confidence')}) {out[-1]['secs']}s", flush=True)

Path(os.environ.get("TEMP", ".") + "/recheck.json").write_text(
    json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
ok = [r for r in out if r.get("chosen")]
print(f"\nสรุป: เลือกได้ {len(ok)} ใบ จาก {len([r for r in out if 'skip' not in r])} ใบที่ตรวจได้")
