"""copy โมดูลโพสต์ชุดล่าสุดจาก Pipeline Studio มาไว้ใน agent/poster/

    python group-poster/sync_poster.py

รันทุกครั้งที่แก้โค้ดโพสต์ใน Studio (เช่นตอนแอป Facebook เปลี่ยนหน้าตา)
แล้วรันเทสของ group-poster ให้ผ่านก่อนส่งโปรแกรมใหม่ให้ลูกค้า
"""

from __future__ import annotations

import shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent
STUDIO = HERE.parent
TARGET = HERE / "agent" / "poster"
FILES = ("facebook_group_post.py", "fb_limits.py", "fb_screen.py", "fb_comment_guard.py")


def main() -> None:
    for name in FILES:
        shutil.copy2(STUDIO / name, TARGET / name)
        print(f"copy {name}")


if __name__ == "__main__":
    main()
