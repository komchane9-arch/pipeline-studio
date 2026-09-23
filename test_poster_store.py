# -*- coding: utf-8 -*-
"""ใบงานสายโปสเตอร์ — รันกับโฟลเดอร์ทดสอบ ไม่แตะข้อมูลจริง (ข้อ 7.4)

    python test_poster_store.py
"""
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

TEMP = Path(tempfile.mkdtemp(prefix="poster-test-"))
os.environ["STUDIO_DATA_DIR"] = str(TEMP)

import poster_store as ps                                    # noqa: E402

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ok = fail = 0


def check(label, got, want):
    global ok, fail
    if got == want:
        ok += 1
        print(f"  ✅ {label}")
    else:
        fail += 1
        print(f"  ❌ {label}\n       ได้ {got!r} · ต้องได้ {want!r}")


def refused(label, action):
    global ok, fail
    try:
        action()
    except ps.PosterError:
        ok += 1
        print(f"  ✅ {label}")
        return
    fail += 1
    print(f"  ❌ {label} — ควรปฏิเสธแต่ผ่าน")


def make_run(where, item_id, at, images=("images/a.jpg",)):
    here = TEMP / where / item_id
    (here / "images").mkdir(parents=True)
    for name in images:
        (here / name).write_bytes(b"jpg")
    run = {"item_id": item_id, "name": f"สินค้า {item_id}", "images": list(images),
           "product_at": at, "affiliate_url": "https://s.shopee.co.th/x"}
    (here / "run.json").write_text(json.dumps(run, ensure_ascii=False), encoding="utf-8")


try:
    assert str(ps.ROOT).startswith(str(TEMP)), "ไม่ได้เขียนลงโฟลเดอร์ทดสอบ"
    since = ps.start_date()
    make_run("shopee_products", "111", "2000-01-01T00:00:00")          # ใบเก่า
    make_run("clipsfb", "222", "2999-01-01T00:00:00")                   # ใบใหม่ ย้ายกองแล้ว
    make_run("shopee_products", "333", "2999-01-01T00:00:00", images=())  # ยังไม่มีรูป
    make_run("shopee_products", "444-post", "2999-01-01T00:00:00")      # ชื่อ -post

    print("\n[1] แตกใบ")
    made = ps.sweep(TEMP, log=lambda _m: None)
    check("แตกเฉพาะใบใหม่ที่มีรูป", made, ["222-post"])
    check("รอบสองไม่แตกซ้ำ", ps.sweep(TEMP, log=lambda _m: None), [])
    card = ps.load("222-post")
    check("ชื่อ = ชื่อเดิม-post", card["name"], "สินค้า 222-post")
    check("อยู่กอง Picture-post", card["stage"], "picture")
    check("ก๊อปรูปมาเก็บเอง", (ps.folder("222-post") / "images/a.jpg").is_file(), True)
    check("ลิงก์ Shopee ติดมา", card["shopee_url"], "https://s.shopee.co.th/x")
    check("วันเริ่มจำไว้ ไม่เปลี่ยน", ps.start_date(), since)

    print("\n[2] ห้ามข้ามขั้น (ข้อ 2.9)")
    refused("กระโดดไป Caption", lambda: ps.move("222-post", "caption"))
    ps.move("222-post", "poster")
    refused("ไป Caption ทั้งที่ยังไม่มีโปสเตอร์", lambda: ps.move("222-post", "caption"))
    ps.set_result("222-post", "poster", poster_images=["poster/p1.png"])
    ps.move("222-post", "caption")
    refused("ไป Comment ทั้งที่ยังไม่มีแคปชัน", lambda: ps.move("222-post", "comment"))
    refused("ขั้น caption เขียนคอมเมนต์ไม่ได้",
            lambda: ps.set_result("222-post", "caption", comments=["x"]))
    ps.set_result("222-post", "caption", caption="แคปชัน")
    ps.move("222-post", "comment")
    ps.set_result("222-post", "comment", comments=["คอมเมนต์ 1"])
    ps.move("222-post", "facebook")
    refused("จบทั้งที่ยังไม่ได้ลงเพจ", lambda: ps.move("222-post", "done"))
    ps.set_result("222-post", "facebook", posted={"status": "posted"})
    ps.move("222-post", "done")
    check("ถึงขั้นสุดท้าย", ps.load("222-post")["stage"], "done")
    ps.move("222-post", "poster")
    check("ถอยกลับไปทำใหม่ได้", ps.load("222-post")["stage"], "poster")

    print("\n[3] ความล้มเหลวจดไว้ในใบ และหายเมื่อทำสำเร็จ")
    ps.fail("222-post", "ChatGPT ไม่ตอบ")
    check("จดเหตุผล", ps.load("222-post")["error"], "ChatGPT ไม่ตอบ")
    ps.set_result("222-post", "poster", poster_images=["poster/p2.png"])
    check("ล้างเมื่อสำเร็จ (ป้ายต้องตรงความจริง ข้อ 2.3.1)", ps.load("222-post")["error"], "")
finally:
    shutil.rmtree(TEMP, ignore_errors=True)

print(f"\nผ่าน {ok} · ไม่ผ่าน {fail}")
sys.exit(1 if fail else 0)
