"""Local HTTP server for the FIT viewer/editor UI (standard library only)."""
from __future__ import annotations

import argparse
import json
import mimetypes
import os
import posixpath
import re
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from . import activity, config, crop, fitfile, garmin

WEB_DIR = Path(__file__).resolve().parent.parent / "web"
DATA_DIR = Path.cwd()
MAX_UPLOAD = 64 * 1024 * 1024
MAX_MARKERS = 2000
_SAFE_NAME = re.compile(r"^[A-Za-z0-9._ ()\-]+$")
_GARMIN = garmin.GarminSession()
GARMIN_ENABLED = True
_GARMIN_OFF = {
    "enabled": False,
    "installed": False,
    "loggedIn": False,
    "mfaPending": False,
    "hint": "the Garmin Connect integration is switched off (--no-garmin)",
}


def _resolve(rel: str) -> Path:
    """Resolve a client supplied path inside DATA_DIR, refusing escapes."""
    candidate = (DATA_DIR / rel).resolve()
    root = DATA_DIR.resolve()
    if candidate != root and root not in candidate.parents:
        raise PermissionError("path outside of the working directory")
    return candidate


#: Credentials of a sign-in that may still be waiting for an MFA code.
_PENDING: dict = {}


def _store_pending() -> None:
    if not _PENDING:
        return
    config.set_garmin_credentials(_PENDING.get("email", ""),
                                  _PENDING.get("password", ""),
                                  bool(_PENDING.get("remember")))
    _PENDING.clear()


#: (name, mtime, size) -> quick file summary, so listing does not re-parse files
_NAME_CACHE: dict = {}


def _file_info(path: Path, stat) -> dict:
    key = (path.name, stat.st_mtime, stat.st_size)
    if key not in _NAME_CACHE:
        if len(_NAME_CACHE) > 200:
            _NAME_CACHE.clear()
        try:
            _NAME_CACHE[key] = activity.quick_info(path.read_bytes())
        except Exception:
            _NAME_CACHE[key] = {"profileName": "", "start": None, "sport": ""}
    info = dict(_NAME_CACHE[key])
    info["activity"] = str(config.section("names").get(path.name) or "")
    return info


def _clean_markers(markers) -> list[dict]:
    """Validate marker records coming from the client or from a file."""
    if not isinstance(markers, list):
        raise ValueError("markers must be a list")
    out = []
    for item in markers[:MAX_MARKERS]:
        if not isinstance(item, dict):
            continue
        try:
            lat = float(item["lat"])
            lon = float(item["lon"])
        except (KeyError, TypeError, ValueError):
            continue
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            continue
        name = str(item.get("name") or "")[:64]
        symbol = str(item.get("symbol") or "")[:32]
        out.append({"name": name, "symbol": symbol, "lat": lat, "lon": lon})
    return out


class Handler(BaseHTTPRequestHandler):
    server_version = "FitEdit/1.0"

    def log_message(self, fmt, *args):  # quieter console
        pass

    # -- helpers -------------------------------------------------------
    def _send(self, code: int, body: bytes, ctype: str, extra: dict | None = None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, payload, code: int = 200):
        self._send(code, json.dumps(payload).encode("utf-8"), "application/json")

    def _error(self, message: str, code: int = 400):
        self._json({"error": message}, code)

    # -- routing -------------------------------------------------------
    def do_GET(self):
        url = urlparse(self.path)
        route = unquote(url.path)
        query = parse_qs(url.query)
        try:
            if route == "/" or route == "/index.html":
                return self._static("index.html")
            if route.startswith("/static/"):
                return self._static(route[len("/static/"):])
            if route == "/api/files":
                return self._json({"files": self._list_files()})
            if route == "/api/load":
                return self._load(query.get("path", [""])[0])
            if route == "/api/markers":
                return self._markers_get(query.get("file", [""])[0])
            if route == "/api/config":
                return self._json(config.public())
            if route == "/api/garmin/status":
                if not GARMIN_ENABLED:
                    return self._json(_GARMIN_OFF)
                probe = query.get("probe", [""])[0] == "1"
                return self._json(_GARMIN.status(resume=not probe))
            if route == "/api/garmin/activities":
                self._require_garmin()
                return self._json({"activities": _GARMIN.activities(
                    days=int(query.get("days", ["7"])[0] or 7),
                    start=query.get("start", [""])[0],
                    end=query.get("end", [""])[0],
                ), "existing": [f["name"] for f in self._list_files()]})
            if route == "/api/download":
                return self._download(query.get("path", [""])[0])
            return self._error("not found", 404)
        except PermissionError as exc:
            return self._error(str(exc), 403)
        except FileNotFoundError:
            return self._error("file not found", 404)
        except fitfile.FitError as exc:
            return self._error(f"invalid FIT file: {exc}", 400)
        except garmin.GarminError as exc:
            return self._error(str(exc), 400)
        except ValueError as exc:
            return self._error(str(exc), 400)
        except Exception as exc:  # pragma: no cover - defensive
            return self._error(f"{type(exc).__name__}: {exc}", 500)

    def do_POST(self):
        url = urlparse(self.path)
        route = unquote(url.path)
        query = parse_qs(url.query)
        try:
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_UPLOAD:
                return self._error("payload too large", 413)
            body = self.rfile.read(length)
            if route == "/api/upload":
                return self._upload(query.get("name", [""])[0], body)
            if route == "/api/crop":
                return self._crop(json.loads(body or b"{}"))
            if route == "/api/rename":
                return self._rename(json.loads(body or b"{}"))
            if route == "/api/markers":
                return self._markers_put(query.get("file", [""])[0],
                                         json.loads(body or b"{}"))
            if route.startswith("/api/garmin/"):
                return self._garmin(route, json.loads(body or b"{}"))
            if route == "/api/config":
                config.update(json.loads(body or b"{}"))
                return self._json(config.public())
            return self._error("not found", 404)
        except PermissionError as exc:
            return self._error(str(exc), 403)
        except FileNotFoundError:
            return self._error("file not found", 404)
        except fitfile.FitError as exc:
            return self._error(f"invalid FIT file: {exc}", 400)
        except garmin.GarminError as exc:
            return self._error(str(exc), 400)
        except ValueError as exc:
            return self._error(str(exc), 400)
        except Exception as exc:  # pragma: no cover - defensive
            return self._error(f"{type(exc).__name__}: {exc}", 500)

    # -- endpoints -----------------------------------------------------
    def _require_garmin(self):
        if not GARMIN_ENABLED:
            raise garmin.GarminError(_GARMIN_OFF["hint"])

    def _static(self, rel: str):
        rel = posixpath.normpath(rel).lstrip("/")
        if rel.startswith(".."):
            raise PermissionError("invalid asset path")
        path = (WEB_DIR / rel).resolve()
        if WEB_DIR.resolve() not in path.parents or not path.is_file():
            return self._error("not found", 404)
        ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript",):
            ctype += "; charset=utf-8"
        self._send(200, path.read_bytes(), ctype)

    def _list_files(self):
        files = []
        for path in sorted(DATA_DIR.glob("*.fit")) + sorted(DATA_DIR.glob("*.FIT")):
            stat = path.stat()
            info = _file_info(path, stat)
            files.append({"name": path.name, "size": stat.st_size,
                          "modified": stat.st_mtime,
                          "activity": info["activity"],
                          "start": info["start"],
                          "type": info["profileName"] or info["sport"]})
        seen, unique = set(), []
        for item in files:
            if item["name"].lower() in seen:
                continue
            seen.add(item["name"].lower())
            unique.append(item)
        return unique

    def _load(self, rel: str):
        if not rel:
            return self._error("missing path")
        path = _resolve(rel)
        data = path.read_bytes()
        fit = fitfile.parse(data)
        payload = activity.extract(fit)
        payload["name"] = path.name
        payload["path"] = path.name
        payload["size"] = len(data)
        payload["activityName"] = str(config.section("names").get(path.name) or "")
        return self._json(payload)

    def _rename(self, payload: dict):
        """The activity name is metadata of Garmin Connect, not of the file."""
        path = _resolve(payload.get("path") or "")
        name = str(payload.get("name") or "").strip()[:64]
        if not path.is_file():
            raise FileNotFoundError
        config.update({"names": {path.name: name or None}})
        return self._json({"name": name})

    def _download(self, rel: str):
        path = _resolve(rel)
        data = path.read_bytes()
        ctype = ("application/json" if path.suffix.lower() == ".json"
                 else "application/vnd.ant.fit")
        self._send(200, data, ctype,
                   {"Content-Disposition": f'attachment; filename="{path.name}"'})

    def _marker_path(self, name: str) -> Path:
        name = os.path.basename(name or "")
        if not name.lower().endswith(".json") or not _SAFE_NAME.match(name):
            raise ValueError("marker files must have a .json name")
        return _resolve(name)

    def _markers_get(self, name: str):
        try:
            path = self._marker_path(name)
        except ValueError as exc:
            return self._error(str(exc))
        if not path.is_file():
            return self._json({"file": path.name, "markers": []})
        payload = json.loads(path.read_text("utf-8"))
        markers = payload.get("markers", payload) if isinstance(payload, dict) else payload
        return self._json({"file": path.name, "markers": _clean_markers(markers)})

    def _markers_put(self, name: str, payload: dict):
        try:
            path = self._marker_path(name)
        except ValueError as exc:
            return self._error(str(exc))
        markers = payload.get("markers", []) if isinstance(payload, dict) else payload
        markers = _clean_markers(markers)
        path.write_text(json.dumps({"markers": markers}, indent=1), "utf-8")
        return self._json({"file": path.name, "count": len(markers)})

    def _upload(self, name: str, body: bytes):
        name = os.path.basename(name or "upload.fit")
        if not _SAFE_NAME.match(name) or not name.lower().endswith(".fit"):
            return self._error("invalid file name")
        path = _resolve(name)
        path.write_bytes(body)
        return self._json({"path": path.name, "size": len(body)})

    def _garmin(self, route: str, payload: dict):
        self._require_garmin()
        action = route[len("/api/garmin/"):]
        if action == "login":
            stored = config.section("garmin")
            email = payload.get("email") or stored.get("email", "")
            password = payload.get("password") or config.garmin_password()
            if not password:
                return self._error("a password is required")
            _PENDING.update({
                "email": email,
                "password": password,
                "remember": bool(payload.get("remember", stored.get("remember"))),
            })
            result = _GARMIN.login(email, password)
            if result.get("status") == "ok":
                _store_pending()
            return self._json(result)
        if action == "mfa":
            result = _GARMIN.submit_mfa(payload.get("code", ""))
            if result.get("status") == "ok":
                _store_pending()
            return self._json(result)
        if action == "logout":
            _GARMIN.logout()
            return self._json(_GARMIN.status())
        if action == "download":
            items = payload.get("activities") or [
                {"id": i, "name": ""} for i in (payload.get("ids") or [])]
            if not isinstance(items, list) or not items:
                return self._error("no activities selected")
            files, failed = [], []
            for item in items[:50]:
                activity_id = item.get("id") if isinstance(item, dict) else item
                try:
                    written = _GARMIN.download(activity_id, DATA_DIR)
                except garmin.GarminError as exc:
                    failed.append({"id": activity_id, "error": str(exc)})
                    continue
                files += written
                title = str(item.get("name") or "").strip()[:64] if isinstance(item, dict) else ""
                if title:
                    config.update({"names": {name: title for name in written}})
            return self._json({"files": files, "failed": failed})
        return self._error("not found", 404)

    def _crop(self, payload: dict):
        rel = payload.get("path") or ""
        start = payload.get("start")
        end = payload.get("end")
        if not rel or start is None or end is None:
            return self._error("path, start and end are required")
        out_name = os.path.basename(payload.get("output") or "")
        if not out_name:
            stem = Path(rel).stem
            out_name = f"{stem}_cropped.fit"
        if not _SAFE_NAME.match(out_name) or not out_name.lower().endswith(".fit"):
            return self._error("invalid output file name")

        src = _resolve(rel)
        dst = _resolve(out_name)
        if dst == src:
            return self._error("refusing to overwrite the source file")

        t_start = int(round(float(start))) - fitfile.FIT_EPOCH
        t_end = int(round(float(end))) - fitfile.FIT_EPOCH
        if t_end <= t_start:
            return self._error("end must be after start")

        data, report = crop.crop(src.read_bytes(), t_start, t_end)
        dst.write_bytes(data)
        title = config.section("names").get(src.name)
        if title:
            config.update({"names": {dst.name: title}})
        report["path"] = dst.name
        report["name"] = title or ""
        return self._json(report)


def main(argv=None):
    global DATA_DIR, GARMIN_ENABLED
    parser = argparse.ArgumentParser(description="View and edit Garmin FIT files")
    parser.add_argument("--dir", default=".", help="directory holding the .fit files")
    parser.add_argument("--port", type=int, default=8731)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--no-garmin", action="store_true",
                        help="disable the optional Garmin Connect download panel")
    args = parser.parse_args(argv)

    GARMIN_ENABLED = not args.no_garmin
    DATA_DIR = Path(args.dir).resolve()
    if not DATA_DIR.is_dir():
        raise SystemExit(f"not a directory: {DATA_DIR}")

    httpd = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    url = f"http://127.0.0.1:{args.port}/"
    print(f"FIT editor serving {DATA_DIR}")
    print(f"Open {url}  (Ctrl+C to stop)")
    if not args.no_browser:
        threading.Timer(0.6, webbrowser.open, args=(url,)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
