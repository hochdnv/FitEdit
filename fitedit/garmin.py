# FIT Editor
# Copyright (C) 2026 K. Hochkirch
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Lesser General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.

"""Optional Garmin Connect integration.

Requires the third-party ``garminconnect`` package. Credentials are only held in
memory for the duration of a sign-in; the resulting OAuth tokens are cached by
the library in ``~/.garminconnect`` so later sessions resume without a password.
"""
from __future__ import annotations

import io
import os
import queue
import ssl
import sys
import tempfile
import threading
import time
import zipfile
from datetime import date, timedelta
from pathlib import Path

TOKEN_DIR = Path.home() / ".garminconnect"
MAX_UNZIP = 128 * 1024 * 1024
INSTALL_HINT = ("the 'garminconnect' package is not installed \u2014 run: "
                "py -3 -m pip install -r requirements-garmin.txt")
_CA_VARS = ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE")
_SERVER_AUTH_OID = "1.3.6.1.5.5.7.3.1"
_ca_ready = False


class GarminError(Exception):
    pass


def _windows_ca_bundle() -> Path | None:
    """Write certifi plus the Windows root store to one PEM file.

    Corporate TLS inspection (Zscaler and friends) issues certificates from a
    root that only lives in the Windows store, which certifi does not know.
    """
    if sys.platform != "win32":
        return None
    pems: list[str] = []
    for store in ("ROOT", "CA"):
        try:
            entries = ssl.enum_certificates(store)
        except Exception:
            continue
        for der, encoding, trust in entries:
            if encoding != "x509_asn":
                continue
            if trust is not True and not (isinstance(trust, set) and _SERVER_AUTH_OID in trust):
                continue
            pems.append(ssl.DER_cert_to_PEM_cert(der))
    if not pems:
        return None

    chunks = []
    try:
        import certifi
        chunks.append(Path(certifi.where()).read_text("ascii", errors="ignore"))
    except Exception:
        pass
    chunks.extend(dict.fromkeys(pems))

    path = Path(tempfile.gettempdir()) / "fitedit_ca_bundle.pem"
    path.write_text("\n".join(chunks), "ascii", errors="ignore")
    return path


def _apply_ca_bundle() -> None:
    global _ca_ready
    if _ca_ready or any(os.environ.get(var) for var in _CA_VARS):
        _ca_ready = True
        return
    _ca_ready = True
    bundle = _windows_ca_bundle()
    if bundle is None:
        return
    for var in _CA_VARS:
        os.environ[var] = str(bundle)


def _garmin_class():
    _apply_ca_bundle()
    try:
        from garminconnect import Garmin
    except ImportError as exc:
        raise GarminError(INSTALL_HINT) from exc
    return Garmin


def _message(exc: Exception) -> str:
    text = str(exc).strip() or type(exc).__name__
    return text[:300]


class GarminSession:
    """Holds one Garmin Connect client, including a pending MFA challenge."""

    def __init__(self, token_dir: Path = TOKEN_DIR):
        self.token_dir = token_dir
        self._client = None
        self._thread: threading.Thread | None = None
        self._mfa_queue: queue.Queue[str] = queue.Queue(maxsize=1)
        self._mfa_needed = threading.Event()
        self._done = threading.Event()
        self._error: str | None = None
        self._resume_tried = False

    # -- state ---------------------------------------------------------
    def status(self, resume: bool = True) -> dict:
        installed, hint = True, ""
        try:
            _garmin_class()
        except GarminError as exc:
            installed, hint = False, str(exc)
        if installed and resume and self._client is None and not self._resume_tried:
            self._resume_tried = True
            self.resume()
        return {
            "enabled": True,
            "installed": installed,
            "hint": hint,
            "loggedIn": self._client is not None,
            "mfaPending": self._mfa_needed.is_set() and not self._done.is_set(),
            "error": self._error,
            "tokenStore": str(self.token_dir),
        }

    def resume(self) -> bool:
        """Log in using previously cached tokens, if there are any."""
        Garmin = _garmin_class()
        if not self.token_dir.exists():
            return False
        try:
            client = Garmin()
            client.login(str(self.token_dir))
        except Exception:
            return False
        self._client = client
        return True

    def logout(self) -> None:
        client, self._client = self._client, None
        self._reset()
        if client is not None:
            try:
                client.logout(str(self.token_dir))
            except Exception:
                pass

    def _reset(self) -> None:
        self._mfa_needed.clear()
        self._done.clear()
        self._error = None
        while not self._mfa_queue.empty():
            self._mfa_queue.get_nowait()

    def _require(self):
        if self._client is None:
            raise GarminError("not signed in to Garmin Connect")
        return self._client

    # -- authentication ------------------------------------------------
    def login(self, email: str, password: str, timeout: float = 60) -> dict:
        Garmin = _garmin_class()
        if not email or not password:
            raise GarminError("email and password are required")
        if self._thread is not None and self._thread.is_alive():
            raise GarminError("a sign-in is already in progress")
        self._client = None
        self._reset()

        client = Garmin(email=email, password=password, prompt_mfa=self._prompt_mfa)

        def run():
            try:
                client.login(str(self.token_dir))
                self._client = client
            except Exception as exc:
                self._error = _message(exc)
            finally:
                self._done.set()

        self._thread = threading.Thread(target=run, daemon=True)
        self._thread.start()
        return self._wait(timeout)

    def submit_mfa(self, code: str, timeout: float = 90) -> dict:
        code = (code or "").strip()
        if not code:
            raise GarminError("an MFA code is required")
        if self._thread is None or not self._thread.is_alive():
            raise GarminError("no sign-in is waiting for a code")
        self._mfa_needed.clear()
        self._mfa_queue.put(code)
        return self._wait(timeout)

    def _prompt_mfa(self) -> str:
        self._mfa_needed.set()
        try:
            return self._mfa_queue.get(timeout=300)
        except queue.Empty:
            raise GarminError("no MFA code was supplied")

    def _wait(self, timeout: float) -> dict:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._done.wait(0.2):
                if self._client is not None:
                    return {"status": "ok"}
                raise GarminError(self._error or "sign-in failed")
            if self._mfa_needed.is_set():
                return {"status": "mfa_required"}
        raise GarminError("sign-in timed out")

    # -- data ----------------------------------------------------------
    def activities(self, days: int | str = 7, start: str = "", end: str = "") -> list[dict]:
        client = self._require()
        end_date = date.fromisoformat(end) if end else date.today()
        if start:
            start_date = date.fromisoformat(start)
        elif str(days).lower() == "all":
            start_date = date(1970, 1, 1)
        else:
            span = max(1, min(int(days or 7), 3650))
            start_date = end_date - timedelta(days=span - 1)
        if start_date > end_date:
            raise GarminError("the start date is after the end date")

        items = client.get_activities_by_date(start_date.isoformat(), end_date.isoformat())
        out = []
        for item in items or []:
            out.append({
                "id": item.get("activityId"),
                "name": item.get("activityName") or "Activity",
                "type": (item.get("activityType") or {}).get("typeKey", ""),
                "start": item.get("startTimeLocal") or item.get("startTimeGMT"),
                "distance": item.get("distance"),
                "duration": item.get("duration"),
            })
        return out

    def download(self, activity_id, dest_dir: Path) -> list[str]:
        """Download the original upload and store the contained FIT file(s)."""
        client = self._require()
        Garmin = _garmin_class()
        data = client.download_activity(
            activity_id, dl_fmt=Garmin.ActivityDownloadFormat.ORIGINAL)
        if not data:
            raise GarminError(f"activity {activity_id} returned no data")

        written = []
        if data[8:12] == b".FIT":
            path = dest_dir / f"{activity_id}_ACTIVITY.fit"
            path.write_bytes(data)
            return [path.name]

        try:
            archive = zipfile.ZipFile(io.BytesIO(data))
        except zipfile.BadZipFile:
            raise GarminError(f"activity {activity_id} is not a FIT upload")
        with archive:
            entries = [i for i in archive.infolist()
                       if i.filename.lower().endswith(".fit") and not i.is_dir()]
            if sum(i.file_size for i in entries) > MAX_UNZIP:
                raise GarminError("the downloaded archive is unexpectedly large")
            for index, info in enumerate(entries):
                suffix = "" if index == 0 else f"_{index + 1}"
                path = dest_dir / f"{activity_id}_ACTIVITY{suffix}.fit"
                path.write_bytes(archive.read(info))
                written.append(path.name)
        if not written:
            raise GarminError(f"activity {activity_id} contains no FIT file")
        return written
