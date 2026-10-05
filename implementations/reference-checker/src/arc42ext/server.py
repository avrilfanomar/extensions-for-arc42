"""`arc42ext serve`: a local, read-only web GUI over one document. Standard library only.

The document stays the record of truth: the server never writes, and only answers GET.
"""

import hashlib
import os
import socket
import sys
import threading
import webbrowser
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import parse_qs, unquote, urlsplit

from . import pages
from .analysis import analyze, catalogue, dashboard, element_detail
from .dates import parse_date

LOOPBACK = frozenset({"localhost", "127.0.0.1", "::1"})
STATIC = {"/static/serve.css": "text/css", "/static/serve.js": "text/javascript"}
SECURITY_HEADERS = {
    "Content-Security-Policy": "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; "
                               "img-src 'self'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
}


class Watcher:
    """Analyses the document on demand, again whenever it or a file it includes changes."""

    def __init__(self, path: Path):
        self.path = path
        self.files = [str(path)]
        self.token = None
        self.cache = {}  # evaluation date -> Analysis, for the current token
        self.lock = threading.Lock()

    def version(self) -> str:
        """A token that changes when any file read changes."""
        digest = hashlib.sha1()
        for name in sorted(set(self.files)):
            try:
                st = os.stat(name)
                digest.update(f"{name}\0{st.st_mtime_ns}\0{st.st_size}\n".encode())
            except OSError:
                digest.update(f"{name}\0missing\n".encode())
        return digest.hexdigest()[:16]

    def analysis(self, on: date) -> tuple:
        """Return (analysis, token), where the token was taken before reading, so that a change made while
        reading still reloads the page. Raises whatever reading raises (say, while an editor replaces the file)."""
        with self.lock:
            token = self.version()
            if token != self.token:
                self.token, self.cache = token, {}
            if on not in self.cache:
                result = analyze(self.path, on)
                if sorted(result.doc.files) != sorted(self.files):
                    self.files = list(result.doc.files)  # an include was added or removed: watch the new set
                    self.token, self.cache = self.version(), {}
                if len(self.cache) > 32:
                    self.cache = {}
                self.cache[on] = result
            return self.cache[on], self.token


class App:
    """Routes a GET request to a page. Kept apart from the socket handling so tests can call it directly."""

    def __init__(self, path: Path, fixed_date: Optional[date] = None, editor_url: Optional[str] = None,
                 allowed_hosts: Optional[frozenset] = LOOPBACK, today: Callable[[], date] = date.today):
        self.path = path
        self.fixed_date = fixed_date
        self.editor_url = editor_url
        self.allowed_hosts = allowed_hosts  # None: any Host header (the server listens beyond loopback)
        self.today = today
        self.watcher = Watcher(path)

    def version(self, token: Optional[str] = None) -> str:
        """The live-reload token: the files' token, plus today's date when the evaluation date follows it."""
        token = token or self.watcher.version()
        return token if self.fixed_date else f"{token}-{self.today().isoformat()}"

    def handle(self, target: str, host: str) -> tuple:
        """Return (HTTP status, content type, body bytes) for GET `target`."""
        if self.allowed_hosts is not None and _hostname(host) not in self.allowed_hosts:
            # A page on another site that rebinds its DNS name to 127.0.0.1 must not read the document.
            return 400, "text/plain", b"Unexpected Host header\n"
        url = urlsplit(target)
        if url.path == "/api/version":
            return 200, "text/plain", self.version().encode()
        if url.path in STATIC:
            return 200, STATIC[url.path], resources.files("arc42ext").joinpath(url.path.lstrip("/")).read_bytes()
        if url.path == "/favicon.ico":
            return 204, "text/plain", b""

        query = {key: values[-1] for key, values in parse_qs(url.query).items()}
        today = self.today()
        ctx = pages.Context(self.path, self.version(), today, editor_url=self.editor_url)
        on = self.fixed_date or today
        if query.get("date"):
            chosen = parse_date(query["date"])
            if chosen is None:
                ctx.notices.append(f"'{query['date']}' is not a YYYY-MM-DD date; showing {on.isoformat()}.")
            else:
                on, ctx.date_param = chosen, chosen.isoformat()
        try:
            ctx.analysis, token = self.watcher.analysis(on)
            ctx.version = self.version(token)
            status, page = self._page(ctx, url.path, query)
        except Exception as error:  # the page must survive any half-saved document, and reload once it is fixed
            ctx.analysis = None
            status, page = 500, pages.error_page(ctx, f"{type(error).__name__}: {error}")
        return status, "text/html", page.encode()

    def _page(self, ctx: pages.Context, path: str, query: dict) -> tuple:
        a = ctx.analysis
        if path == "/":
            role = query.get("role") or None
            return 200, pages.dashboard_page(ctx, dashboard(a, role), role)
        if path == "/elements":
            by = "kind" if query.get("by") == "kind" else "section"
            return 200, pages.catalogue_page(ctx, catalogue(a, by), by)
        if path.startswith("/elements/"):
            element_id = unquote(path[len("/elements/"):])
            detail = element_detail(a, element_id)
            if detail is not None:
                return 200, pages.element_page(ctx, detail)
            return 404, pages.not_found_page(ctx, f"No element '{element_id}' in the document.")
        return 404, pages.not_found_page(ctx, f"No page at {path}.")


def _hostname(host: str) -> str:
    try:
        return urlsplit(f"//{host}").hostname or ""
    except ValueError:
        return ""


class _Handler(BaseHTTPRequestHandler):
    server_version = "arc42ext"

    def do_GET(self):
        status, content_type, body = self.server.app.handle(self.path, self.headers.get("Host", ""))
        self.send_response(status)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        for name, value in SECURITY_HEADERS.items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def log_request(self, code="-", size="-"):
        if isinstance(code, int) and code >= 400:  # stay quiet about page loads and live-reload polling
            super().log_request(code, size)


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple, app: App):
        if ":" in address[0]:
            self.address_family = socket.AF_INET6
        super().__init__(address, _Handler)
        self.app = app

    @property
    def url(self) -> str:
        host, port = self.server_address[:2]
        return f"http://[{host}]:{port}/" if ":" in host else f"http://{host}:{port}/"


def serve(path: Path, fixed_date: Optional[date] = None, host: str = "127.0.0.1", port: int = 8042,
          editor_url: Optional[str] = None, open_browser: bool = False) -> int:
    loopback = host in LOOPBACK
    app = App(path, fixed_date, editor_url, LOOPBACK if loopback else None)
    try:
        server = Server((host, port), app)
    except OSError as error:
        print(f"arc42ext: cannot listen on {host}:{port}: {error.strerror or error}. Try another --port, "
              f"or --port 0 for any free port.", file=sys.stderr)
        return 1
    if not loopback:
        print(f"warning: listening on {host}, so other machines can read this document.", file=sys.stderr)
    print(f"Serving {path} at {server.url} (Ctrl+C to stop)", flush=True)
    if open_browser:
        webbrowser.open(server.url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0
