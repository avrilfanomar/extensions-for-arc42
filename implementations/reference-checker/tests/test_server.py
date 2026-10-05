"""The web GUI: routing, live-reload token, what-if rows, escaping, the Host check, and a real socket."""

import os
import shutil
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from datetime import date
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from unittest import mock

from arc42ext.server import App, Server

REPO = Path(__file__).resolve().parents[3]
TRIGGERS_EXAMPLE = REPO / "extensions/triggers/EN/example.adoc"
TODAY = date(2026, 10, 5)
HOST = "localhost:8042"


class TestApp(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.doc = self.tmp / "doc.adoc"
        shutil.copy(TRIGGERS_EXAMPLE, self.doc)
        self.app = App(self.doc, today=lambda: TODAY)

    def get(self, target, host=HOST):
        status, content_type, body = self.app.handle(target, host)
        return status, body.decode()

    def touch(self, path: Path):
        st = path.stat()
        os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000))

    def test_dashboard(self):
        status, page = self.get("/?date=2026-10-04")
        self.assertEqual(status, 200)
        self.assertIn("rv-004", page)
        self.assertIn("1 day overdue", page)

    def test_element_pages(self):
        self.assertEqual(self.get("/elements")[0], 200)
        self.assertEqual(self.get("/elements?by=kind")[0], 200)
        status, page = self.get("/elements/adr-007?date=2026-10-04")
        self.assertEqual(status, 200)
        self.assertIn("rv-003", page)
        self.assertEqual(self.get("/elements/nope")[0], 404)
        self.assertEqual(self.get("/nowhere")[0], 404)

    def test_static_files(self):
        status, content_type, body = self.app.handle("/static/serve.js", HOST)
        self.assertEqual((status, content_type), (200, "text/javascript"))
        self.assertIn(b"/api/version", body)
        self.assertEqual(self.app.handle("/static/../server.py", HOST)[0], 404)

    def test_other_hosts_are_refused(self):
        self.assertEqual(self.get("/", "attacker.example:8042")[0], 400)
        self.assertEqual(self.get("/api/version", "")[0], 400)
        for host in ("127.0.0.1:8042", "[::1]:8042", "localhost"):
            self.assertEqual(self.get("/api/version", host)[0], 200)
        self.assertEqual(App(self.doc, allowed_hosts=None).handle("/api/version", "192.168.1.9:8042")[0], 200)

    def test_rows_for_a_future_date_are_what_if(self):
        _, page = self.get("/?date=2026-10-28")
        self.assertIn("ev-006", page)
        self.assertIn("What-if", page)
        self.assertNotIn("data-copy", page)
        app = App(self.doc, today=lambda: date(2026, 10, 28))
        page = app.handle("/?date=2026-10-28", HOST)[2].decode()
        self.assertIn("data-copy", page)
        self.assertNotIn("What-if", page)

    def test_bad_date_falls_back(self):
        status, page = self.get("/?date=2026-13-40")
        self.assertEqual(status, 200)
        self.assertIn("is not a YYYY-MM-DD date", page)

    def test_version_follows_the_document_and_its_includes(self):
        main = self.tmp / "main.adoc"
        part = self.tmp / "part.adoc"
        main.write_text("= Doc\n\ninclude::part.adoc[]\n")
        part.write_text("== Part\n\n* [[rq-001]]Requirement\n")
        app = App(main, today=lambda: TODAY)
        app.handle("/", HOST)  # the first read finds the include
        first = app.handle("/api/version", HOST)[2]
        self.assertEqual(first, app.handle("/api/version", HOST)[2])
        self.touch(part)
        second = app.handle("/api/version", HOST)[2]
        self.assertNotEqual(first, second)
        self.touch(main)
        self.assertNotEqual(second, app.handle("/api/version", HOST)[2])

    def test_page_carries_the_token_it_was_rendered_at(self):
        _, page = self.get("/")
        self.assertIn(f'data-version="{self.get("/api/version")[1]}"', page)
        self.assertTrue(self.get("/api/version")[1].endswith(TODAY.isoformat()))  # rolls over at midnight
        fixed = App(self.doc, fixed_date=date(2026, 10, 4))
        self.assertNotIn("-2026", fixed.handle("/api/version", HOST)[2].decode())

    def test_unreadable_document_shows_an_error(self):
        self.doc.unlink()
        status, page = self.get("/")
        self.assertEqual(status, 500)
        self.assertIn("Cannot read the document", page)
        shutil.copy(TRIGGERS_EXAMPLE, self.doc)
        self.assertEqual(self.get("/")[0], 200)

    def test_a_failing_page_still_reloads(self):
        with mock.patch("arc42ext.server.dashboard", side_effect=RuntimeError("boom")):
            status, page = self.get("/")
        self.assertEqual(status, 500)
        self.assertIn("RuntimeError: boom", page)
        self.assertIn('src="/static/serve.js"', page)

    def test_document_text_is_escaped(self):
        self.doc.write_text("= <script>alert(1)</script>\n\n[[adr-001]]\n=== ADR-001: <img src=x onerror=alert(2)>\n\n"
                            "[.links]\nrelates-to:: javascript:alert(3)\n")
        _, page = self.get("/elements/adr-001")
        self.assertNotIn("<script>alert", page)
        self.assertNotIn("<img", page)
        self.assertIn("&lt;img src=x onerror=alert(2)&gt;", page)
        self.assertNotIn('href="javascript:', page)

    def test_editor_links_use_absolute_quoted_paths(self):
        self.addCleanup(os.chdir, os.getcwd())
        os.chdir(self.tmp)
        spaced = self.tmp / "my doc.adoc"
        shutil.copy(TRIGGERS_EXAMPLE, spaced)
        app = App(Path("my doc.adoc"), editor_url="vscode://file{path}:{line}", today=lambda: TODAY)
        page = app.handle("/elements/adr-007", HOST)[2].decode()
        absolute = spaced.resolve().as_posix().replace(" ", "%20")
        self.assertIn(f'href="vscode://file{absolute}:', page)
        self.assertIn(">my doc.adoc:", page)


class TestServer(unittest.TestCase):

    @mock.patch.object(BaseHTTPRequestHandler, "log_message")
    def test_serves_over_http(self, _log):
        server = Server(("127.0.0.1", 0), App(TRIGGERS_EXAMPLE, fixed_date=date(2026, 10, 4)))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)

        with urllib.request.urlopen(server.url) as response:
            self.assertEqual(response.headers["Content-Type"], "text/html; charset=utf-8")
            self.assertIn("script-src 'self'", response.headers["Content-Security-Policy"])
            self.assertIn("rv-004", response.read().decode())
        request = urllib.request.Request(server.url, method="POST", data=b"")
        with self.assertRaises(urllib.error.HTTPError) as raised:
            urllib.request.urlopen(request)
        self.assertEqual(raised.exception.code, 501)  # read-only: only GET is implemented


if __name__ == "__main__":
    unittest.main()
