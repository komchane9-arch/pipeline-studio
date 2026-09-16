# -*- coding: utf-8 -*-
"""เพิ่มกลุ่มให้บัญชีสายโพสต์ทีเดียวหลายลิงก์

    python fb_add_groups.py "Preaw Buchakorn" <ลิงก์1> <ลิงก์2> ...
    python fb_add_groups.py "Preaw Buchakorn" --file links.txt
    python fb_add_groups.py --list                 ← ดูว่าแต่ละบัญชีมีกี่กลุ่ม

**ทำไมต้องมี (16 ก.ย. 2569)** ตอนต่อสายโพสต์บัญชีที่สอง ชิ้นสุดท้ายที่เหลือคือ
"เพิ่มกลุ่ม" ซึ่งบนหน้าเว็บทำได้ทีละลิงก์ พอมีสิบกลุ่มก็ต้องวางสิบรอบ
ตัวนี้รับทีเดียวทั้งชุด แล้วรายงานทีละบรรทัดว่าอันไหนเข้า อันไหนซ้ำ อันไหนพัง

**ห้ามเดาบัญชี** ต้องบอกชื่อบัญชีมาเสมอ และชื่อต้องตรงกับที่ผูกไว้กับมือถือจริง
— โพสต์ลงบัญชีผิดกู้คืนไม่ได้ ส่วนพิมพ์ชื่อผิดแล้วโดนปฏิเสธ เสียแค่เวลาพิมพ์ใหม่
(CLAUDE.md ข้อ 8)
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import devices as device_book                                   # noqa: E402
import fb_auto_post                                             # noqa: E402
import studio_shared as shared                                  # noqa: E402


def _out():
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")


def bound_accounts() -> dict[str, str]:
    """บัญชี → เครื่องที่ผูกไว้ เฉพาะเครื่องที่เปิดใช้ในสายโพสต์"""
    post = set(device_book.enabled_serials("post"))
    out: dict[str, str] = {}
    for name, serials in device_book.accounts().items():
        hit = [s for s in serials if s in post]
        if name and hit:
            out[name] = hit[0]
    return dict(sorted(out.items()))


def store_for(account: str) -> fb_auto_post.GroupStore:
    path = shared.account_file(account, "fb_groups.json")
    return fb_auto_post.GroupStore(lambda: path)


def show_all() -> int:
    _out()
    bound = bound_accounts()
    if not bound:
        print("ยังไม่มีบัญชีไหนผูกกับมือถือสายโพสต์เลย")
        return 1
    for name, serial in bound.items():
        groups = store_for(name).listing()
        print(f"{name:24s} {len(groups):3d} กลุ่ม   ({device_book.label(serial)})")
        for g in groups:
            print(f"      {g['group_id']:20s} {g.get('name','')}")
    return 0


def add_many(account: str, links: list[str]) -> int:
    _out()
    bound = bound_accounts()
    if account not in bound:
        print(f"❌ ไม่รู้จักบัญชี '{account}' ในสายโพสต์")
        print("   บัญชีที่มี: " + (" · ".join(bound) or "(ยังไม่มีเลย)"))
        return 1
    store = store_for(account)
    ok = dup = bad = 0
    for link in links:
        link = link.strip()
        if not link or link.startswith("#"):
            continue
        try:
            entry = store.add(link)
        except Exception as error:                              # noqa: BLE001
            bad += 1
            print(f"❌ {link[:60]}\n     {type(error).__name__}: {str(error)[:90]}")
            continue
        if entry.get("duplicated"):
            dup += 1
            print(f"• มีอยู่แล้ว  {entry['group_id']}  {entry.get('name','')}")
        else:
            ok += 1
            print(f"✅ เพิ่มแล้ว   {entry['group_id']}  {entry.get('name','')}")
    total = len(store.listing())
    print(f"\nสรุป: เพิ่มใหม่ {ok} · มีอยู่แล้ว {dup} · ไม่สำเร็จ {bad}")
    print(f"ตอนนี้บัญชี {account} มี {total} กลุ่ม  (เครื่อง {device_book.label(bound[account])})")
    if bad:
        print("ลิงก์ที่ไม่สำเร็จมักเป็นลิงก์ที่ไม่ใช่กลุ่ม หรือกลุ่มปิดที่บัญชีนี้ยังไม่ได้เข้าร่วม")
    return 0 if not bad else 2


def main() -> int:
    args = sys.argv[1:]
    if not args or args[0] in {"--list", "-l"}:
        return show_all()
    account = args[0]
    rest = args[1:]
    links: list[str] = []
    if rest and rest[0] in {"--file", "-f"}:
        if len(rest) < 2:
            _out()
            print("บอกชื่อไฟล์ด้วย: --file links.txt")
            return 1
        links = Path(rest[1]).read_text(encoding="utf-8").splitlines()
    else:
        links = rest
    if not links:
        _out()
        print(__doc__)
        return 1
    return add_many(account, links)


if __name__ == "__main__":
    raise SystemExit(main())
