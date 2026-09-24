"""ด่านตรวจว่าไฟล์ Python **โหลดขึ้นจริง** ไม่ใช่แค่ไวยากรณ์ถูก

**เหตุการณ์ที่ทำให้ต้องมี (30 ส.ค. 2569)** — แก้ `clip_app.py` แล้ววางบล็อกที่
สร้างตัวแปรไว้ **หลัง** บรรทัดที่เรียกใช้มัน (สร้างบรรทัด ~2860 · ใช้บรรทัด 2839)

    NameError: name 'CLIP_SLOT1_STAGES' is not defined

`ast.parse()` บอกว่าผ่าน เพราะไฟล์นั้น**ไวยากรณ์ถูกต้องสมบูรณ์** ผลคือ
เซิร์ฟเวอร์สายคลิปดับ 8 นาที (15:50–15:58) ตัวเฝ้าไล่ปลุก 5 รอบแล้วตายทุกรอบ

**รากของปัญหาคือคำถามที่ถามผิด** (กติกาข้อ 2.3.1) — `ast.parse()` ถามว่า
*"แปลงเป็นต้นไม้ไวยากรณ์ได้ไหม"* ซึ่งตอบว่า "ได้" ทั้งตอนโค้ดดีและโค้ดพัง
ตัวนี้ถามคำถามที่แยกสองสถานะออกจากกันจริง: *"ชื่อทุกตัวถูกสร้างก่อนถูกใช้ไหม"*

**ทำไมไม่ import จริงไปเลย** — `import clip_app` จะรันโค้ดระดับโมดูลทั้งไฟล์
ซึ่งไปเปิดไฟล์คิว สร้างตัวรัน และอาจแย่งอ่านข้อความบอท Telegram กับตัวจริง
(กติกาข้อ 7.7) ตัวนี้จึงอ่านโครงสร้างอย่างเดียว ไม่รันอะไรเลย

    python load_check.py                        ตรวจโครงสร้างไฟล์ .py ทั้งโปรเจกต์
    python load_check.py clip_app.py            ตรวจเฉพาะไฟล์ที่ระบุ
    python load_check.py --import clip_app.py   **ลองโหลดจริง** ในสนามทดสอบ
                                                (ช้ากว่า แต่จับได้ครบกว่า)

คืนค่า 0 = ผ่าน · 1 = เจอชื่อที่ถูกใช้ก่อนสร้าง
"""

from __future__ import annotations

import ast
import builtins
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


def _say(message: str) -> None:
    try:
        print(message, flush=True)
    except UnicodeEncodeError:
        sys.stdout.buffer.write((message + "\n").encode("utf-8", "replace"))


def _defined_names(tree: ast.Module) -> dict[str, int]:
    """ชื่อระดับโมดูลทั้งหมด → บรรทัดแรกที่มันถูกสร้าง

    นับทุกทางที่ทำให้ชื่อเกิดขึ้นในโมดูล: กำหนดค่า · def · class · import ·
    for ที่ระดับบนสุด · with ... as · except ... as · global ในฟังก์ชัน
    """
    made: dict[str, int] = {}

    def note(name: str, line: int) -> None:
        """จำ **บรรทัดแรกสุด** ที่ชื่อนี้ถูกสร้าง ไม่ใช่บรรทัดแรกที่บังเอิญเดินไปเจอ

        **เจอจริงตอนทดสอบ (30 ส.ค. 2569)** — `ast.walk` เดินแบบทีละชั้น
        ตัวที่อยู่ชั้นบนสุดจึงถูกเจอก่อนตัวที่ซ้อนอยู่ในลูป ผลคือชื่อที่ถูกสร้าง
        ในลูปบรรทัด 94 แล้วใช้บรรทัด 95 ถูกรายงานว่า "ใช้ก่อนสร้าง" เพราะไป
        จำบรรทัด 97 ที่อยู่ชั้นบนสุดแทน — **ด่านที่เตือนผิดจะถูกเลิกสนใจ**
        ภายในไม่กี่วัน แล้วกลายเป็นด่านที่มีไว้เฉยๆ (กติกาข้อ 2.7)
        """
        if not name:
            return
        if name not in made or line < made[name]:
            made[name] = line

    def walk_target(node, line: int) -> None:
        if isinstance(node, ast.Name):
            note(node.id, line)
        elif isinstance(node, (ast.Tuple, ast.List)):
            for item in node.elts:
                walk_target(item, line)
        elif isinstance(node, ast.Starred):
            walk_target(node.value, line)

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            note(node.name, node.lineno)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                walk_target(target, node.lineno)
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
            walk_target(node.target, node.lineno)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                note((alias.asname or alias.name).split(".")[0], node.lineno)
        elif isinstance(node, (ast.For, ast.AsyncFor)):
            walk_target(node.target, node.lineno)
        elif isinstance(node, (ast.With, ast.AsyncWith)):
            for item in node.items:
                if item.optional_vars is not None:
                    walk_target(item.optional_vars, node.lineno)

    # ชื่อที่เกิดในบล็อกซ้อน (if/try/for/while) ก็ใช้ได้จากข้างนอกเหมือนกัน
    for node in ast.walk(tree):
        if isinstance(node, ast.Global):
            for name in node.names:
                note(name, node.lineno)
        if isinstance(node, ast.ExceptHandler) and node.name:
            note(node.name, node.lineno)
        if isinstance(node, ast.Assign):
            for target in node.targets:
                walk_target(target, node.lineno)
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                note((alias.asname or alias.name).split(".")[0], node.lineno)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            note(node.name, node.lineno)
    return made


def _module_level_uses(tree: ast.Module) -> list[tuple[str, int]]:
    """ชื่อที่ถูก **อ่าน** ตอนโมดูลถูกโหลด — ไม่นับที่อยู่ในตัวฟังก์ชัน

    โค้ดในตัวฟังก์ชันยังไม่ทำงานตอน import ชื่อจึงเกิดทีหลังได้ไม่มีปัญหา
    ตัวที่อันตรายคือโค้ดที่ทำงานทันทีตอนโหลดเท่านั้น
    """
    uses: list[tuple[str, int]] = []

    def scan(node) -> None:
        for child in ast.iter_child_nodes(node):
            # ข้ามตัวฟังก์ชันกับคลาส — ข้างในยังไม่ทำงานตอนโหลด
            # (แต่ **ค่าปริยายของพารามิเตอร์** กับ **ตัวตกแต่ง** ทำงานทันที)
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for deco in child.decorator_list:
                    scan_expr(deco)
                for default in child.args.defaults + [
                        d for d in child.args.kw_defaults if d is not None]:
                    scan_expr(default)
                continue
            if isinstance(child, ast.ClassDef):
                for deco in child.decorator_list:
                    scan_expr(deco)
                for base in child.bases:
                    scan_expr(base)
                continue
            if isinstance(child, ast.Lambda):
                continue
            scan(child)
            if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load):
                uses.append((child.id, child.lineno))

    def scan_expr(node) -> None:
        for sub in ast.walk(node):
            if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Load):
                uses.append((sub.id, sub.lineno))

    scan(tree)
    return uses


def check(path: Path) -> list[str]:
    """คืนรายการปัญหาที่เจอในไฟล์นี้ — ว่างแปลว่าผ่าน"""
    try:
        source = path.read_text(encoding="utf-8")
    except Exception as error:                                   # noqa: BLE001
        return [f"อ่านไฟล์ไม่ได้: {error}"]
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as error:
        return [f"ไวยากรณ์ผิด บรรทัด {error.lineno}: {error.msg}"]

    made = _defined_names(tree)
    known = set(dir(builtins)) | {"__name__", "__file__", "__doc__",
                                  "__spec__", "__package__", "__builtins__"}
    problems: list[str] = []
    seen: set[str] = set()
    for name, line in _module_level_uses(tree):
        if name in known or name in seen:
            continue
        birth = made.get(name)
        if birth is None:
            continue          # ไม่รู้จักเลย — ปล่อยไว้ อาจมาจาก star import
        if birth > line:
            seen.add(name)
            problems.append(
                f"บรรทัด {line} ใช้ `{name}` แต่มันถูกสร้างที่บรรทัด {birth} "
                f"(ใช้ก่อนสร้าง = โหลดไฟล์แล้วตายทันที)")
    return problems


def real_import(names: list[str]) -> int:
    """ลองโหลดโมดูลจริงในสนามทดสอบ — ตอบคำถามได้ครบกว่าการอ่านโครงสร้าง

    **แชท main เสนอไว้ 30 ส.ค. 2569** และถูกต้อง — การอ่านโครงสร้างจับได้เฉพาะ
    "ใช้ชื่อก่อนสร้าง **ที่ระดับโมดูล**" ส่วนการเรียกฟังก์ชันที่ยังไม่มีจาก
    **ข้างในฟังก์ชันอื่น** มันมองไม่เห็น (ผมเจอเองตอนแก้ `app.py` วันเดียวกัน)

    **ทำไมต้องมีสนามทดสอบ** การ import จริงจะรันโค้ดระดับโมดูลทั้งไฟล์ ซึ่งไป
    อ่าน-เขียนไฟล์คิวและไฟล์ตั้งค่าของจริง ตั้ง `STUDIO_DATA_DIR` เป็นโฟลเดอร์
    ทิ้งขว้างก่อนจึงจำเป็น (กติกาข้อ 7.4 — ทดสอบห้ามแตะ data จริง)

    ปลอดภัยเรื่องพอร์ต: ทั้ง `app.py` และ `clip_app.py` เรียก `uvicorn.run`
    ใต้ `if __name__ == "__main__"` การ import จึงไม่เปิดพอร์ตและไม่แย่งบอท
    """
    import os                                                    # noqa: PLC0415
    import shutil                                                # noqa: PLC0415
    import subprocess                                            # noqa: PLC0415
    import tempfile                                              # noqa: PLC0415

    sandbox = Path(tempfile.mkdtemp(prefix="loadcheck-"))
    env = dict(os.environ)
    env["STUDIO_DATA_DIR"] = sandbox.name
    env["PYTHONIOENCODING"] = "utf-8"
    # สนามทดสอบต้องอยู่ข้างๆ โปรเจกต์ เพราะโค้ดต่อพาธจาก BASE_DIR
    here = BASE_DIR / sandbox.name
    here.mkdir(exist_ok=True)
    bad = 0
    try:
        for name in names:
            mod = Path(name).stem
            done = subprocess.run(
                [sys.executable, "-c", f"import {mod}"],
                cwd=str(BASE_DIR), env=env, capture_output=True,
                text=True, encoding="utf-8", errors="replace", timeout=180)
            if done.returncode == 0:
                _say(f"✅ {mod} — โหลดขึ้นจริง")
                continue
            bad += 1
            tail = [l for l in (done.stderr or "").splitlines() if l.strip()]
            _say(f"❌ {mod} — โหลดไม่ขึ้น")
            for line in tail[-4:]:
                _say(f"    {line[:180]}")
    finally:
        shutil.rmtree(here, ignore_errors=True)
        shutil.rmtree(sandbox, ignore_errors=True)
    return 1 if bad else 0


def main(argv: list[str]) -> int:
    if argv and argv[0] == "--import":
        rest = argv[1:]
        if not rest:
            _say("บอกชื่อไฟล์ด้วย เช่น  python load_check.py --import clip_app.py")
            return 1
        return real_import(rest)
    names = argv or sorted(p.name for p in BASE_DIR.glob("*.py"))
    bad = 0
    for name in names:
        path = Path(name)
        if not path.is_absolute():
            path = BASE_DIR / name
        problems = check(path)
        if problems:
            bad += 1
            _say(f"❌ {path.name}")
            for line in problems:
                _say(f"    {line}")
    if bad:
        _say(f"\nเจอปัญหา {bad} ไฟล์ — แก้ก่อนรีสตาร์ต")
        return 1
    _say(f"✅ ตรวจ {len(names)} ไฟล์ · ทุกชื่อถูกสร้างก่อนถูกใช้")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
