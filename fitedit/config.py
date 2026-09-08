"""Local configuration file for FIT Editor.

Stored in ``~/.fitedit/config.json``. Secrets are encrypted with Windows DPAPI
(per user account) where available; the file is otherwise written with
owner-only permissions and the UI is told that the secret is unprotected.
"""
from __future__ import annotations

import base64
import ctypes
import json
import os
import sys
from ctypes import wintypes
from pathlib import Path
from typing import Any

CONFIG_DIR = Path.home() / ".fitedit"
CONFIG_FILE = CONFIG_DIR / "config.json"

#: Sections the client is allowed to write.
_SECTIONS = ("garmin", "ui", "names")


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _dpapi(func, data: bytes) -> bytes:
    buffer = ctypes.create_string_buffer(data, len(data))
    source = _Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))
    result = _Blob()
    ok = func(ctypes.byref(source), None, None, None, None, 0, ctypes.byref(result))
    if not ok:
        raise OSError("DPAPI call failed")
    try:
        return ctypes.string_at(result.pbData, result.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(result.pbData)


def dpapi_available() -> bool:
    return sys.platform == "win32"


def encrypt(secret: str) -> str:
    raw = secret.encode("utf-8")
    if dpapi_available():
        try:
            blob = _dpapi(ctypes.windll.crypt32.CryptProtectData, raw)
            return "dpapi:" + base64.b64encode(blob).decode("ascii")
        except OSError:
            pass
    return "plain:" + base64.b64encode(raw).decode("ascii")


def decrypt(stored: str) -> str:
    if not stored:
        return ""
    scheme, _, payload = stored.partition(":")
    raw = base64.b64decode(payload)
    if scheme == "dpapi":
        return _dpapi(ctypes.windll.crypt32.CryptUnprotectData, raw).decode("utf-8")
    return raw.decode("utf-8")


def load() -> dict:
    try:
        data = json.loads(CONFIG_FILE.read_text("utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save(data: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(CONFIG_DIR, 0o700)
    except OSError:
        pass
    CONFIG_FILE.write_text(json.dumps(data, indent=1), "utf-8")
    try:
        os.chmod(CONFIG_FILE, 0o600)
    except OSError:
        pass


def update(patch: dict) -> dict:
    """Merge a patch into the config; ``None`` values remove a key."""
    data = load()
    for section, values in (patch or {}).items():
        if section not in _SECTIONS or not isinstance(values, dict):
            continue
        current = data.get(section) if isinstance(data.get(section), dict) else {}
        for key, value in values.items():
            if value is None:
                current.pop(key, None)
            else:
                current[key] = value
        data[section] = current
    save(data)
    return data


def section(name: str) -> dict:
    value = load().get(name)
    return value if isinstance(value, dict) else {}


def set_garmin_credentials(email: str, password: str, remember: bool) -> None:
    patch: dict[str, Any] = {"email": email or None, "remember": bool(remember)}
    patch["password"] = encrypt(password) if (remember and password) else None
    update({"garmin": patch})


def garmin_password() -> str:
    stored = section("garmin").get("password") or ""
    try:
        return decrypt(stored)
    except Exception:
        return ""


def public() -> dict:
    """Config for the UI, with secrets replaced by a flag."""
    data = load()
    garmin = data.get("garmin") if isinstance(data.get("garmin"), dict) else {}
    stored = garmin.get("password") or ""
    return {
        "file": str(CONFIG_FILE),
        "garmin": {
            "email": garmin.get("email", ""),
            "remember": bool(garmin.get("remember")),
            "hasPassword": bool(stored),
            "encrypted": stored.startswith("dpapi:"),
        },
        "ui": data.get("ui") if isinstance(data.get("ui"), dict) else {},
        "secretsEncrypted": dpapi_available(),
    }
