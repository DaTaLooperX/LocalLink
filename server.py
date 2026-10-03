#!/usr/bin/env python3
"""LocalLink: a dependency-free, single-room LAN messenger."""
import argparse
import getpass
import hashlib
import hmac
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import socket
import sqlite3
import threading
import time
from contextlib import contextmanager
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, urlsplit

ROOT = Path(__file__).resolve().parent


class ChatServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, data_dir, password="", max_file_mb=100, storage_mb=2048):
        self.data_dir = Path(data_dir)
        self.upload_dir = self.data_dir / "uploads"
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.data_dir / "chat.sqlite3"
        self.password_hash = hashlib.sha256(password.encode()).digest() if password else None
        self.max_file = max_file_mb * 1024 * 1024
        self.storage_limit = storage_mb * 1024 * 1024
        self.sessions = {}
        self.failures = {}
        self.lock = threading.RLock()
        self.changed = threading.Condition(self.lock)
        self.upload_lock = threading.Lock()
        self.hostnames = {"localhost", socket.gethostname().lower(), socket.getfqdn().lower()}
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("""CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sender TEXT NOT NULL, client_id TEXT NOT NULL, text TEXT NOT NULL,
                created REAL NOT NULL, file_id TEXT, filename TEXT, size INTEGER)""")
        # Incomplete uploads are never made downloadable.
        for partial in self.upload_dir.glob("*.part"):
            partial.unlink(missing_ok=True)
        super().__init__(address, Handler)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.db_path, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def insert(self, session, text="", file_id=None, filename=None, size=None):
        with self.changed:
            with self.connect() as db:
                cursor = db.execute(
                    "INSERT INTO messages(sender,client_id,text,created,file_id,filename,size) VALUES(?,?,?,?,?,?,?)",
                    (session["name"], session["client_id"], text, time.time(), file_id, filename, size),
                )
                row = dict(db.execute("SELECT * FROM messages WHERE id=?", (cursor.lastrowid,)).fetchone())
            self.changed.notify_all()
            return row

    def people(self):
        now = time.time()
        with self.lock:
            expired = [key for key, s in self.sessions.items() if now - s["seen"] > 43200]
            for key in expired:
                del self.sessions[key]
            return [{"id": s["client_id"], "name": s["name"]} for s in self.sessions.values() if now - s["seen"] < 45]


class Handler(BaseHTTPRequestHandler):
    server_version = "LocalLink/1.0"

    def setup(self):
        super().setup()
        self.connection.settimeout(120)

    def log_message(self, format, *args):
        # Do not print session tokens or user content.
        pass

    def headers_out(self, code, mime, length=None, extra=None):
        self.send_response(code)
        self.send_header("Content-Type", mime)
        if length is not None:
            self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()

    def json(self, code, obj, extra=None):
        body = json.dumps(obj).encode()
        self.headers_out(code, "application/json; charset=utf-8", len(body), extra)
        self.wfile.write(body)

    def valid_host(self):
        host_header = self.headers.get("Host", "")
        try:
            host = urlsplit("//" + host_header).hostname
            valid = host and host.lower() in self.server.hostnames
            if not valid:
                ip = ipaddress.ip_address(host or "")
                valid = ip.is_private or ip.is_loopback or ip.is_link_local
        except ValueError:
            valid = False
        if not valid:
            self.json(403, {"error": "Open this app using the host computer's local IP address."})
        return valid

    def session(self):
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie", ""))
            token = cookie["locallink"].value if "locallink" in cookie else ""
        except Exception:
            token = ""
        with self.server.lock:
            session = self.server.sessions.get(token)
            if session and time.time() - session["seen"] < 43200:
                session["seen"] = time.time()
                return session
            self.server.sessions.pop(token, None)
        return None

    def body_length(self, limit):
        try:
            if self.headers.get("Transfer-Encoding"):
                raise ValueError
            size = int(self.headers.get("Content-Length", "-1"))
            if size < 0:
                raise ValueError
        except ValueError:
            self.json(400, {"error": "A valid Content-Length is required."})
            return None
        if size > limit:
            self.json(413, {"error": "This upload or message exceeds the size limit."})
            return None
        return size

    def read_json(self):
        size = self.body_length(20000)
        if size is None:
            return None
        try:
            obj = json.loads(self.rfile.read(size))
            if not isinstance(obj, dict):
                raise ValueError
            return obj
        except (ValueError, UnicodeDecodeError):
            self.json(400, {"error": "Invalid JSON request."})
            return None

    def do_GET(self):
        try:
            self.get()
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            pass
        except Exception as exc:
            print("Request failed:", type(exc).__name__)
            self.json(500, {"error": "The server could not complete the request."})

    def get(self):
        if not self.valid_host():
            return
        url = urlsplit(self.path)
        if url.path in ("/", "/app.js", "/style.css"):
            name, mime = {"/": ("index.html", "text/html"), "/app.js": ("app.js", "text/javascript"), "/style.css": ("style.css", "text/css")}[url.path]
            body = (ROOT / "static" / name).read_bytes()
            self.headers_out(200, mime + "; charset=utf-8", len(body))
            self.wfile.write(body)
            return
        if url.path == "/api/config":
            self.json(200, {"password_required": bool(self.server.password_hash), "max_file_bytes": self.server.max_file})
            return
        session = self.session()
        if not session:
            self.json(401, {"error": "Join the room to continue."})
            return
        if url.path == "/api/me":
            self.json(200, {"name": session["name"], "client_id": session["client_id"]})
        elif url.path == "/api/messages":
            query = parse_qs(url.query)
            try:
                after = int(query["after"][0]) if "after" in query else None
                before = int(query["before"][0]) if "before" in query else None
                if (after is not None and after < 0) or (before is not None and before < 0):
                    raise ValueError
            except ValueError:
                self.json(400, {"error": "Invalid message cursor."})
                return
            def fetch():
                with self.server.connect() as db:
                    if after is not None:
                        return [dict(r) for r in db.execute("SELECT * FROM messages WHERE id>? ORDER BY id LIMIT 101", (after,))]
                    return [dict(r) for r in db.execute("SELECT * FROM messages WHERE id<? ORDER BY id DESC LIMIT 101", (before if before is not None else 9223372036854775807,))]
            with self.server.changed:
                rows = fetch()
                if after is not None and not rows:
                    self.server.changed.wait(timeout=15)
                    rows = fetch()
                more = len(rows) > 100
                rows = rows[:100]
                if after is None:
                    rows.reverse()
                people = self.server.people()
            self.json(200, {"messages": rows, "has_more": more, "people": people})
        elif url.path.startswith("/files/"):
            file_id = url.path.removeprefix("/files/")
            if not re.fullmatch(r"[0-9a-f]{32}", file_id):
                self.json(404, {"error": "File not found."})
                return
            with self.server.connect() as db:
                row = db.execute("SELECT filename,size FROM messages WHERE file_id=?", (file_id,)).fetchone()
            path = self.server.upload_dir / file_id
            if not row or not path.is_file():
                self.json(404, {"error": "File not found."})
                return
            self.headers_out(200, "application/octet-stream", row["size"], {
                "Content-Disposition": "attachment; filename=\"download\"; filename*=UTF-8''" + quote(row["filename"], safe="")})
            with path.open("rb") as source:
                while chunk := source.read(256 * 1024):
                    self.wfile.write(chunk)
        else:
            self.json(404, {"error": "Not found."})

    def do_POST(self):
        try:
            self.post()
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            pass
        except Exception as exc:
            print("Request failed:", type(exc).__name__)
            self.json(500, {"error": "The server could not save your message or file. Check disk space."})

    def post(self):
        if not self.valid_host():
            return
        origin = self.headers.get("Origin")
        if self.headers.get("X-Local-Chat") != "1" or (origin and origin != "http://" + self.headers.get("Host", "")):
            self.json(403, {"error": "Cross-site requests are not allowed."})
            return
        url = urlsplit(self.path)
        if url.path == "/api/join":
            obj = self.read_json()
            if obj is None:
                return
            name = obj.get("name")
            password = obj.get("password", "")
            if not isinstance(name, str) or not 1 <= len(name.strip()) <= 32 or not isinstance(password, str):
                self.json(400, {"error": "Choose a display name of 1–32 characters."})
                return
            with self.server.changed:
                now = time.time()
                self.server.failures = {k: v for k, v in self.server.failures.items() if now - v[0] < 60}
                since, count = self.server.failures.get(self.client_address[0], (now, 0))
                if count >= 10:
                    self.json(429, {"error": "Too many attempts. Try again in one minute."})
                    return
                if self.server.password_hash and not hmac.compare_digest(hashlib.sha256(password.encode()).digest(), self.server.password_hash):
                    self.server.failures[self.client_address[0]] = (since, count + 1)
                    self.json(403, {"error": "Incorrect room password."})
                    return
                self.server.people()
                if len(self.server.sessions) >= 256:
                    self.json(503, {"error": "The room is full. Try again later."})
                    return
                token = secrets.token_urlsafe(32)
                session = {"name": name.strip(), "client_id": secrets.token_hex(16), "seen": now}
                self.server.sessions[token] = session
                self.server.changed.notify_all()
            self.json(200, {"name": session["name"], "client_id": session["client_id"]}, {"Set-Cookie": f"locallink={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age=43200"})
            return
        session = self.session()
        if not session:
            self.json(401, {"error": "Your session ended. Join the room again."})
            return
        if url.path == "/api/logout":
            with self.server.changed:
                self.server.sessions = {k: v for k, v in self.server.sessions.items() if v is not session}
                self.server.changed.notify_all()
            self.json(200, {"ok": True}, {"Set-Cookie": "locallink=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0"})
        elif url.path == "/api/messages":
            obj = self.read_json()
            if obj is None:
                return
            message = obj.get("text")
            if not isinstance(message, str) or not 1 <= len(message.strip()) <= 4000:
                self.json(400, {"error": "Messages must contain 1–4,000 characters."})
                return
            self.json(201, self.server.insert(session, text=message.strip()))
        elif url.path == "/api/files":
            size = self.body_length(self.server.max_file)
            if size is None:
                return
            name = parse_qs(url.query).get("name", [""])[0]
            name = name.replace("\\", "/").split("/")[-1]
            name = "".join(c for c in name if ord(c) >= 32 and ord(c) != 127)[:200].strip()
            if not name:
                self.json(400, {"error": "A filename is required."})
                return
            file_id = secrets.token_hex(16)
            partial = self.server.upload_dir / (file_id + ".part")
            final = self.server.upload_dir / file_id
            # Reserve disk space logically; partial files count against the quota.
            with self.server.upload_lock:
                reserved = getattr(self.server, "reserved", 0)
                used = sum(p.stat().st_size for p in self.server.upload_dir.iterdir() if not p.name.endswith(".part"))
                if used + reserved + size > self.server.storage_limit:
                    self.json(507, {"error": "The room's file storage is full. Ask the host to increase the storage limit."})
                    return
                self.server.reserved = reserved + size
            size_reserved = True
            try:
                with partial.open("xb") as dest:
                    remaining = size
                    while remaining:
                        chunk = self.rfile.read(min(256 * 1024, remaining))
                        if not chunk:
                            raise ConnectionResetError("Incomplete upload")
                        dest.write(chunk)
                        remaining -= len(chunk)
                with self.server.upload_lock:
                    partial.rename(final)
                    self.server.reserved -= size
                    size_reserved = False
                try:
                    row = self.server.insert(session, file_id=file_id, filename=name, size=size)
                except Exception:
                    final.unlink(missing_ok=True)
                    raise
                self.json(201, row)
            finally:
                partial.unlink(missing_ok=True)
                if size_reserved:
                    with self.server.upload_lock:
                        self.server.reserved -= size
        else:
            self.json(404, {"error": "Not found."})


def local_ips():
    addresses = set()
    try:
        addresses.update(socket.gethostbyname_ex(socket.gethostname())[2])
    except OSError:
        pass
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            # UDP connect selects an interface; it sends no packets.
            sock.connect(("192.0.2.1", 9))
            addresses.add(sock.getsockname()[0])
    except OSError:
        pass
    return sorted(ip for ip in addresses if not ip.startswith("127."))


def main():
    parser = argparse.ArgumentParser(description="LocalLink — messaging and file sharing on your Wi-Fi")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    parser.add_argument("--password", action="store_true", help="Prompt for a room password (also supports LOCALCHAT_PASSWORD environment variable)")
    parser.add_argument("--max-file-mb", type=int, default=100)
    parser.add_argument("--storage-mb", type=int, default=2048)
    args = parser.parse_args()
    if min(args.max_file_mb, args.storage_mb) < 1 or not 1 <= args.port <= 65535:
        parser.error("Use positive file/storage limits and a port from 1 to 65535.")
    password = getpass.getpass("Room password: ") if args.password else os.environ.get("LOCALCHAT_PASSWORD", "")
    if args.password and not password:
        parser.error("Password cannot be empty when --password is used.")
    try:
        server = ChatServer((args.host, args.port), args.data_dir, password, args.max_file_mb, args.storage_mb)
    except OSError as exc:
        parser.exit(1, f"Could not start LocalLink: {exc}\nTry another --port if this one is busy.\n")
    print(f"\nLocalLink is running.\n\n  This computer: http://localhost:{args.port}")
    if args.host == "0.0.0.0":
        for ip in local_ips():
            print(f"  Other devices: http://{ip}:{args.port}")
    else:
        print(f"  Listening on:  {args.host}:{args.port}")
    print(f"\n  Password: {'enabled' if password else 'off — anyone who can reach this computer can join'}")
    print(f"  File limit: {args.max_file_mb} MiB | Total file storage: {args.storage_mb} MiB")
    print(f"  Data: {args.data_dir.resolve()}\n\nKeep this window open. Press Ctrl+C to stop.\n", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nLocalLink stopped.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
