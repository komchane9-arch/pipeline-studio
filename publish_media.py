"""ด่านยืนยันตัวตนของคลิปก่อนเปิดผังโพสต์บนมือถือ.

ฟังก์ชันในไฟล์นี้เป็น pure functions เพื่อให้ทดสอบได้โดยไม่แตะ ADB หรือมือถือจริง.
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath


class PublishMediaIdentityError(RuntimeError):
    """ข้อมูลใบงาน/ชื่อไฟล์/MediaStore ไม่ตรงกัน จึงห้ามเริ่มโพสต์."""


def expected_phone_video_name(
    item_id: str,
    run_item_id: str,
    stored_video: str,
) -> str:
    """คืนชื่อไฟล์บนมือถือ โดยยืนยันก่อนว่าไฟล์เป็นของใบงานเดียวกัน."""
    wanted = str(item_id or "").strip()
    recorded = str(run_item_id or "").strip()
    if not wanted:
        raise PublishMediaIdentityError("ใบงานไม่มีรหัสสินค้า")
    if not recorded:
        raise PublishMediaIdentityError(
            f"ใบงาน {wanted} ไม่มี item_id ใน run.json — ห้ามเดาว่าคลิปเป็นของใบนี้"
        )
    if recorded != wanted:
        raise PublishMediaIdentityError(
            f"รหัสใบงานไม่ตรงกัน: คิว={wanted} แต่ run.json={recorded}"
        )

    clean = str(stored_video or "").strip().replace("\\", "/")
    basename = PurePosixPath(clean).name
    if not clean or basename in {"", ".", ".."}:
        raise PublishMediaIdentityError(f"ใบงาน {wanted} ไม่มีชื่อไฟล์คลิปที่ใช้ได้")
    return f"{wanted}-{basename}"


def media_store_rows(raw: str) -> list[dict[str, str]]:
    """อ่านผล ``content query`` โดยเก็บชื่อและ path ของวิดีโอแต่ละแถว."""
    rows: list[dict[str, str]] = []
    for line in str(raw or "").splitlines():
        if not line.lstrip().startswith("Row:"):
            continue
        name = re.search(r"(?:^|[, ])_display_name=([^,]*)(?:,|$)", line)
        data = re.search(r"(?:^|[, ])_data=([^,]*)(?:,|$)", line)
        rows.append({
            "name": (name.group(1).strip() if name else ""),
            "data": (data.group(1).strip() if data else ""),
        })
    return rows


def validate_phone_video_inventory(
    item_id: str,
    expected_name: str,
    remote_files: list[str],
    media_rows_raw: str,
    remote_dir: str,
) -> str:
    """ยืนยันว่าตัวเลือกคลิปจะเห็นวิดีโอของใบงานนี้เพียงใบเดียว.

    การมีคลิปอื่นแม้เพียงใบเดียวถือว่าไม่ปลอดภัย เพราะ Facebook ใช้ลำดับใน
    gallery ของตัวเองและขั้นเลือกคลิปเป็นการแตะช่องภาพ ไม่ได้ส่ง path ให้แอปตรงๆ.
    """
    wanted = str(item_id or "").strip()
    expected = str(expected_name or "").strip()
    files = [str(name).strip() for name in remote_files if str(name).strip()]
    if files != [expected]:
        shown = ", ".join(files[:5]) or "ไม่มีไฟล์"
        raise PublishMediaIdentityError(
            f"คลิปใน {remote_dir} ไม่ตรงกับใบงาน {wanted}: "
            f"ต้องมี {expected} ใบเดียว แต่พบ {shown}"
        )

    rows = media_store_rows(media_rows_raw)
    if len(rows) != 1:
        shown = ", ".join(row["name"] or "(ไม่มีชื่อ)" for row in rows[:5])
        raise PublishMediaIdentityError(
            f"MediaStore ต้องมีวิดีโอใบงาน {wanted} เพียงรายการเดียว "
            f"แต่พบ {len(rows)} รายการ{(': ' + shown) if shown else ''}"
        )
    row = rows[0]
    if row["name"] != expected:
        raise PublishMediaIdentityError(
            f"ชื่อคลิปใน MediaStore ไม่ตรงกับใบงาน {wanted}: "
            f"ต้องเป็น {expected} แต่พบ {row['name'] or '(ไม่มีชื่อ)'}"
        )
    data = row["data"].replace("\\", "/")
    # `/sdcard` เป็น symlink ของ `/storage/emulated/0`; MediaStore รายงานแบบหลัง
    # จึงเทียบเฉพาะโฟลเดอร์ปลายทางที่มีความหมายจริง ไม่เทียบ alias ของ root.
    dir_parts = PurePosixPath(remote_dir.replace("\\", "/")).parts
    meaningful = dir_parts[-2:] if len(dir_parts) >= 2 else dir_parts
    expected_tail = "/" + "/".join((*meaningful, expected))
    if data and data != "null" and not data.endswith(expected_tail):
        raise PublishMediaIdentityError(
            f"ตำแหน่งคลิปใน MediaStore ไม่ตรงกับใบงาน {wanted}: {data}"
        )
    return f"ชื่อไฟล์และ MediaStore ตรงกับใบงาน {wanted}: {expected}"
