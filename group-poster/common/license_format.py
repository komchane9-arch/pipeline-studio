"""รูปแบบ serial key และ license token — ใช้ร่วมกันทั้งฝั่ง server และ agent

มีของสองชิ้นที่ต้องแยกกันให้ออก:

- **รหัสขาย** `GP-XXXX-XXXX-XXXX-XXXX` สุ่มล้วน ไม่มีข้อมูลอะไรในตัว
  ลูกค้าพิมพ์รหัสนี้ครั้งเดียวตอน activate ตรวจได้ที่ server เท่านั้น
  ตั้งใจไม่ใช้สูตรที่ตรวจในเครื่องได้ เพราะใครแกะสูตรได้ก็สร้างรหัสเองได้ไม่จำกัด

- **license token** ที่ server เซ็นด้วย Ed25519 แล้วส่งกลับหลัง activate สำเร็จ
  agent เก็บไว้ใช้ตอนเน็ตหลุดหรือเครื่องเราดับ ตรวจลายเซ็นด้วย public key
  ปลอมไม่ได้ถ้าไม่มี private key ซึ่งอยู่บนเครื่องเราเท่านั้น
"""

from __future__ import annotations

import base64
import json
import secrets
from datetime import datetime, timezone

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

# ตัดตัวที่อ่านสับสนออก (0/O, 1/I/L) ลูกค้าพิมพ์ตามจากแชทแล้วผิดบ่อยที่สุด
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
CODE_PREFIX = "GP"
CODE_GROUPS = 4
CODE_GROUP_LEN = 4

# แพ็กเกจตั้งต้น — เพิ่มหรือแก้ได้ตอนออกรหัส (admin.py --max-groups ฯลฯ)
PLANS: dict[str, dict] = {
    "trial": {"max_devices": 1, "max_groups": 5, "days": 7},
    "basic": {"max_devices": 1, "max_groups": 30, "days": 30},
    "pro": {"max_devices": 2, "max_groups": 100, "days": 30},
}


class LicenseError(ValueError):
    """token ใช้ไม่ได้ — ข้อความในนี้แสดงให้ลูกค้าเห็นตรงๆ จึงเขียนเป็นภาษาคน"""


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat(timespec="seconds")


def parse_iso(text: str) -> datetime:
    moment = datetime.fromisoformat(text)
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


# ------------------------------------------------------------------ รหัสขาย

def new_code() -> str:
    groups = [
        "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_GROUP_LEN))
        for _ in range(CODE_GROUPS)
    ]
    return "-".join([CODE_PREFIX, *groups])


def normalize_code(text: str) -> str:
    """รับรหัสที่ลูกค้าพิมพ์มาแบบไหนก็ได้ (ตัวเล็ก เว้นวรรค ไม่มีขีด) ให้เป็นรูปเดียว"""
    raw = "".join(ch for ch in str(text).upper() if ch.isalnum())
    if raw.startswith(CODE_PREFIX):
        raw = raw[len(CODE_PREFIX):]
    # ลูกค้าพิมพ์ O แทน 0 หรือ I แทน 1 — ในชุดตัวอักษรไม่มีทั้งสองแบบอยู่แล้ว
    # แต่แปลงไว้ให้ข้อความ error บอกว่า "ไม่พบรหัส" แทนที่จะงงว่ารูปแบบผิด
    parts = [raw[i:i + CODE_GROUP_LEN] for i in range(0, len(raw), CODE_GROUP_LEN)]
    return "-".join([CODE_PREFIX, *parts])


# ------------------------------------------------------------------ กุญแจ

def new_private_key() -> Ed25519PrivateKey:
    return Ed25519PrivateKey.generate()


def private_key_to_pem(key: Ed25519PrivateKey) -> bytes:
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )


def private_key_from_pem(data: bytes) -> Ed25519PrivateKey:
    key = serialization.load_pem_private_key(data, password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("ไฟล์กุญแจไม่ใช่ Ed25519")
    return key


def public_key_text(key: Ed25519PrivateKey | Ed25519PublicKey) -> str:
    """public key เป็นข้อความสั้นบรรทัดเดียว ไว้ฝังใน config ของ agent"""
    public = key.public_key() if isinstance(key, Ed25519PrivateKey) else key
    raw = public.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return _b64(raw)


def public_key_from_text(text: str) -> Ed25519PublicKey:
    return Ed25519PublicKey.from_public_bytes(_unb64(text))


# ------------------------------------------------------------------ token

def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def sign_token(key: Ed25519PrivateKey, payload: dict) -> str:
    body = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    data = body.encode("utf-8")
    return f"{_b64(data)}.{_b64(key.sign(data))}"


def read_token(public: Ed25519PublicKey, token: str) -> dict:
    """ตรวจลายเซ็นแล้วคืน payload — ยังไม่ตรวจวันหมดอายุหรือเครื่อง (ดู check_token)"""
    try:
        body, signature = str(token).split(".", 1)
        data = _unb64(body)
        public.verify(_unb64(signature), data)
        payload = json.loads(data.decode("utf-8"))
    except (ValueError, InvalidSignature, UnicodeDecodeError) as error:
        raise LicenseError("license ไม่ถูกต้อง หรือถูกแก้ไข") from error
    if not isinstance(payload, dict):
        raise LicenseError("license ไม่ถูกต้อง")
    return payload


def check_token(public: Ed25519PublicKey, token: str, machine: str,
                now: datetime | None = None) -> dict:
    """ตรวจครบทุกข้อที่ agent ตรวจเองได้โดยไม่ต้องถาม server"""
    payload = read_token(public, token)
    now = now or utc_now()
    if payload.get("machine") != machine:
        raise LicenseError("license นี้ผูกกับเครื่องอื่น")
    expires = payload.get("expires")
    if expires and parse_iso(expires) <= now:
        raise LicenseError(f"license หมดอายุแล้ว ({expires[:10]})")
    return payload
