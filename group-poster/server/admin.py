"""คำสั่งจัดการ license สำหรับเจ้าของ — รันบนเครื่องที่รัน license server

    python server/admin.py new --plan trial --note "คุณเอ LINE @aaa"
    python server/admin.py new --plan pro --days 90 --note "ร้าน B"
    python server/admin.py list
    python server/admin.py show GP-XXXX-XXXX-XXXX-XXXX
    python server/admin.py revoke GP-XXXX-...     /  unrevoke GP-XXXX-...
    python server/admin.py extend GP-XXXX-... --days 30
    python server/admin.py release GP-XXXX-...    # ปลดทุกเครื่อง ให้ลูกค้าย้ายเครื่องได้
    python server/admin.py agent-config --server https://license.example.com
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common import license_format as lf  # noqa: E402
from server.store import Store  # noqa: E402


def _summary(lic: dict) -> str:
    state = "ระงับ" if lic["revoked"] else "ใช้ได้"
    expires = (lic["expires"] or "ไม่หมดอายุ")[:10]
    devices = lic.get("devices")
    used = "" if devices is None else f"  เครื่อง {sum(d['active'] for d in devices)}/{lic['max_devices']}"
    return (f"{lic['code']}  [{lic['sku']}]  {state}  หมด {expires}"
            f"  กลุ่มต่อรอบ {lic['max_groups']}{used}  {lic['note']}")


def main(argv: list[str] | None = None, store: Store | None = None) -> int:
    parser = argparse.ArgumentParser(description="จัดการ license ของ Group Poster")
    sub = parser.add_subparsers(dest="cmd", required=True)

    new = sub.add_parser("new", help="ออกรหัสใหม่")
    new.add_argument("--plan", default="trial", choices=sorted(lf.PLANS))
    new.add_argument("--days", type=int, help="อายุ (วัน) · 0 = ไม่หมดอายุ")
    new.add_argument("--devices", type=int, help="จำนวนเครื่องที่ใช้พร้อมกันได้")
    new.add_argument("--groups", type=int, help="จำนวนกลุ่มสูงสุดต่อรอบ")
    new.add_argument("--note", default="", help="ขายให้ใคร / ช่องทางติดต่อ")
    new.add_argument("--count", type=int, default=1, help="ออกทีละหลายรหัส")

    sub.add_parser("list", help="ดูรหัสทั้งหมด")
    for name, text in (("show", "ดูรายละเอียด"), ("revoke", "ระงับรหัส"),
                       ("unrevoke", "ยกเลิกการระงับ"), ("release", "ปลดทุกเครื่อง")):
        cmd = sub.add_parser(name, help=text)
        cmd.add_argument("code")
    ext = sub.add_parser("extend", help="ต่ออายุ")
    ext.add_argument("code")
    ext.add_argument("--days", type=int, required=True)

    cfg = sub.add_parser("agent-config", help="สร้าง config.json ส่งไปกับโปรแกรมลูกค้า")
    cfg.add_argument("--server", required=True, help="URL ที่ลูกค้าเข้าถึงได้ เช่น https://license.example.com")
    cfg.add_argument("--out", default=str(Path(__file__).resolve().parents[1] / "agent" / "config.json"))

    args = parser.parse_args(argv)
    store = store or Store()

    if args.cmd == "new":
        for _ in range(max(1, args.count)):
            lic = store.create_license(args.plan, args.days, args.devices, args.groups, args.note)
            print(_summary(lic))
        return 0
    if args.cmd == "list":
        rows = store.list_licenses()
        if not rows:
            print("ยังไม่มีรหัส — ออกรหัสแรกด้วย: python server/admin.py new --plan trial")
        for lic in rows:
            print(_summary(lic))
        return 0
    if args.cmd == "agent-config":
        out = Path(args.out)
        out.write_text(json.dumps({
            "server_url": args.server.rstrip("/"),
            "public_key": store.public_key_text(),
        }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"เขียน {out} แล้ว — ไฟล์นี้ส่งไปพร้อมโปรแกรมลูกค้าได้ ไม่มีความลับอยู่ข้างใน")
        return 0

    lic = store.find(args.code)
    if not lic:
        print(f"ไม่พบรหัส {args.code}", file=sys.stderr)
        return 1
    if args.cmd == "revoke":
        store.set_revoked(lic["id"], True)
    elif args.cmd == "unrevoke":
        store.set_revoked(lic["id"], False)
    elif args.cmd == "extend":
        store.extend(lic["id"], args.days)
    elif args.cmd == "release":
        store.release_all(lic["id"])
    lic = store.get_license(lic["id"])
    lic["devices"] = store.devices(lic["id"])
    print(_summary(lic))
    if args.cmd == "show":
        for device in lic["devices"]:
            state = "ใช้งาน" if device["active"] else "ปลดแล้ว"
            print(f"  - {device['label'] or '(ไม่มีชื่อ)'}  {state}"
                  f"  เห็นล่าสุด {device['last_seen'][:16]}  v{device['app_version']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
