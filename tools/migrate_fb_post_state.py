"""Copy Facebook posting state from Drive to local storage, then recover groups.

The operation is deliberately copy-only: it never removes or changes the source.
Every JSON file is parsed before it is accepted, and recovered groups are written
atomically so an interrupted migration cannot leave a half-written registry.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
from datetime import datetime
from pathlib import Path


KNOWN_GROUP_ALIASES = {
    "apparelmakers": "569042730582923",
}


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _atomic_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _backup_existing(destination: Path, backup_root: Path) -> Path | None:
    existing = [path for path in destination.rglob("*") if path.is_file()]
    if not existing:
        return None
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = backup_root / stamp
    shutil.copytree(destination, target)
    return target


def copy_state(source: Path, destination: Path) -> int:
    """Validate and copy every state file without deleting either side."""
    if not source.is_dir():
        raise FileNotFoundError(f"ไม่พบโฟลเดอร์ต้นทาง: {source}")
    files = [path for path in source.rglob("*") if path.is_file()]
    for path in files:
        if path.suffix.casefold() == ".json":
            _read_json(path)
    copied = 0
    for path in files:
        relative = path.relative_to(source)
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        copied += 1
    return copied


def recover_groups(snapshot: Path, destination: Path, account_slug: str) -> int:
    """Merge a known-good group snapshot into one account registry."""
    recovered = _read_json(snapshot)
    if not isinstance(recovered, list):
        raise ValueError("ไฟล์กู้กลุ่มต้องเป็น JSON list")
    target = destination / "accounts" / account_slug / "fb_groups.json"
    try:
        current = _read_json(target)
    except FileNotFoundError:
        current = []
    if not isinstance(current, list):
        raise ValueError(f"ไฟล์ปลายทางไม่ใช่ JSON list: {target}")

    merged: dict[str, dict] = {}
    order: list[str] = []
    for row in [*current, *recovered]:
        if not isinstance(row, dict):
            continue
        raw = str(row.get("group_id", "")).strip()
        group_id = KNOWN_GROUP_ALIASES.get(raw.casefold(), raw)
        if not group_id:
            continue
        fixed = {**row, "group_id": group_id}
        if group_id not in merged:
            order.append(group_id)
            merged[group_id] = fixed
        else:
            # Snapshot fields fill gaps but must not erase newer local values.
            merged[group_id] = {**fixed, **merged[group_id]}
    result = [merged[group_id] for group_id in order]
    _atomic_json(target, result)
    return len(result)


def migrate(source: Path, destination: Path, *, backup_root: Path,
            group_snapshot: Path | None = None,
            account_slug: str = "preaw-buchakorn") -> dict:
    destination.mkdir(parents=True, exist_ok=True)
    backup = _backup_existing(destination, backup_root)
    copied = copy_state(source, destination)
    groups = None
    if group_snapshot is not None:
        groups = recover_groups(group_snapshot, destination, account_slug)
    return {"copied": copied, "groups": groups, "backup": backup}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--backup-root", type=Path, required=True)
    parser.add_argument("--group-snapshot", type=Path)
    parser.add_argument("--account-slug", default="preaw-buchakorn")
    args = parser.parse_args()
    result = migrate(
        args.source, args.destination,
        backup_root=args.backup_root,
        group_snapshot=args.group_snapshot,
        account_slug=args.account_slug,
    )
    print(json.dumps({
        **result,
        "backup": str(result["backup"] or ""),
        "destination": str(args.destination.resolve()),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
