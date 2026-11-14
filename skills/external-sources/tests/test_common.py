"""Общая часть скилла: HTTP, хранилище, статус, токены."""

from __future__ import annotations

import http.server
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import common
from support import FakeWeb


class StatusTest(unittest.TestCase):
    def test_status_has_time_error_and_objects(self):
        with tempfile.TemporaryDirectory() as out:
            common.update_status(out, "site", ok=True, counts={"страниц": 3}, objects=["сайт https://example.ru"])
            data = common.read_status(out)
            entry = data["sources"]["site"]
            self.assertTrue(entry["ok"])
            self.assertTrue(entry["lastRun"].endswith("Z"))
            self.assertEqual(entry["objects"], ["сайт https://example.ru"])
            self.assertIsNone(entry["error"])

    def test_status_keeps_other_sources(self):
        with tempfile.TemporaryDirectory() as out:
            common.update_status(out, "site", ok=True)
            common.update_status(out, "metrika", ok=False, error="ошибка авторизации: HTTP 401")
            data = common.read_status(out)
            self.assertEqual(sorted(data["sources"]), ["metrika", "site"])
            self.assertEqual(data["sources"]["metrika"]["error"], "ошибка авторизации: HTTP 401")

    def test_rerun_overwrites_own_entry_without_duplicates(self):
        with tempfile.TemporaryDirectory() as out:
            for _ in range(3):
                common.update_status(out, "direct", ok=True, counts={"кампаний": 2})
            data = common.read_status(out)
            self.assertEqual(list(data["sources"]), ["direct"])
            self.assertEqual(data["sources"]["direct"]["counts"], {"кампаний": 2})

    def test_render_status_mentions_last_run_and_objects(self):
        with tempfile.TemporaryDirectory() as out:
            common.update_status(out, "webmaster", ok=True, objects=["https://example.ru/"])
            text = common.render_status(out)
            self.assertIn("webmaster", text)
            self.assertIn("https://example.ru/", text)
            self.assertIn("ok", text)

    def test_render_status_on_empty_dir(self):
        with tempfile.TemporaryDirectory() as out:
            self.assertIn("Статус пуст", common.render_status(out))


class StorageTest(unittest.TestCase):
    def test_write_json_is_atomic_and_round_trips(self):
        with tempfile.TemporaryDirectory() as out:
            path = os.path.join(out, "nested", "data.json")
            common.write_json(path, {"ключ": "значение"})
            self.assertEqual(common.read_json(path), {"ключ": "значение"})
            self.assertFalse(os.path.exists(path + ".tmp"))

    def test_read_json_returns_default_on_garbage(self):
        with tempfile.TemporaryDirectory() as out:
            path = os.path.join(out, "data.json")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("{не json")
            self.assertEqual(common.read_json(path, {"ok": True}), {"ok": True})

    def test_write_json_reports_unwritable_path(self):
        with tempfile.TemporaryDirectory() as out:
            blocker = os.path.join(out, "file")
            with open(blocker, "w", encoding="utf-8") as handle:
                handle.write("x")
            with self.assertRaises(common.SourceError):
                common.write_json(os.path.join(blocker, "data.json"), {})


class TokenTest(unittest.TestCase):
    def test_token_from_env(self):
        os.environ["SAMPLE_NAME"] = "abc"
        try:
            self.assertEqual(common.token_from("SAMPLE_NAME"), "abc")
        finally:
            del os.environ["SAMPLE_NAME"]

    def test_token_from_file(self):
        with tempfile.TemporaryDirectory() as out:
            path = os.path.join(out, "secrets.env")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("# комментарий\n\nYANDEX_SEO_TOKEN = \"из-файла\"\n")
            self.assertEqual(common.token_from("YANDEX_SEO_TOKEN", path), "из-файла")

    def test_missing_token_is_auth_error(self):
        os.environ.pop("NO_SUCH_TOKEN", None)
        with self.assertRaises(common.AuthError) as caught:
            common.token_from("NO_SUCH_TOKEN")
        self.assertIn("ошибка авторизации", str(caught.exception))


class HttpTest(unittest.TestCase):
    def test_401_is_auth_error_not_a_crash(self):
        web = FakeWeb().route("example", status=401, body='{"error":"bad token"}')
        with self.assertRaises(common.AuthError) as caught:
            common.request_json("https://example.ru/api", transport=web)
        self.assertIn("ошибка авторизации", str(caught.exception))

    def test_500_is_source_error(self):
        web = FakeWeb().route("example", status=500, body=b"")
        with self.assertRaises(common.SourceError):
            common.request_json("https://example.ru/api", transport=web)

    def test_garbage_body_is_source_error(self):
        web = FakeWeb().route("example", status=200, body=b"<html>")
        with self.assertRaises(common.SourceError) as caught:
            common.request_json("https://example.ru/api", transport=web)
        self.assertIn("не JSON", str(caught.exception))

    def test_cyrillic_host_with_login_is_refused(self):
        with self.assertRaises(common.SourceError):
            common.http_request("https://user:pass@еггент.рф/")

    def test_broken_url_is_source_error_not_valueerror(self):
        for bad in ("https://[::1", "https://example.ru:bad/"):
            with self.assertRaises(common.SourceError):
                common.http_request(bad)

    def test_same_site_is_strict(self):
        base = "https://example.ru"
        self.assertTrue(common.same_site("https://example.ru/a?b=1", base))
        self.assertFalse(common.same_site("https://example.ru.evil.com/x", base))
        self.assertFalse(common.same_site("https://example.ru@evil.com/x", base))
        self.assertFalse(common.same_site("https://example.ru:4444/x", base))
        self.assertFalse(common.same_site("http://example.ru/x", base))
        self.assertFalse(common.same_site("https://[::1", base))

    def test_body_is_cut_at_max_bytes(self):
        payload = b"x" * 4096

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                try:
                    self.wfile.write(payload)
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def log_message(self, *args):
                return

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            answer = common.http_request(f"http://127.0.0.1:{server.server_port}/big", max_bytes=1024)
        finally:
            server.shutdown()
            server.server_close()
        self.assertEqual(answer["status"], 200)
        self.assertEqual(len(answer["body"]), 1024)

    def test_file_scheme_is_refused(self):
        with self.assertRaises(common.SourceError):
            common.http_request("file:///etc/passwd")

    def test_network_failure_is_source_error(self):
        web = FakeWeb().route("example", error=common.SourceError("нет связи"))
        with self.assertRaises(common.SourceError):
            common.http_request("https://example.ru/", transport=web)

    def test_cyrillic_host_is_converted_to_punycode(self):
        web = FakeWeb().route("xn--", status=200, body=b"{}")
        common.request_json("https://еггент.рф/api", transport=web)
        self.assertTrue(web.calls[0]["url"].startswith("https://xn--"))

    def test_unencodable_host_is_an_error(self):
        with self.assertRaises(common.SourceError):
            common.http_request("https://exa mple.ru/")

    def test_default_user_agent_is_set(self):
        web = FakeWeb().route("example", status=200, body=b"{}")
        common.request_json("https://example.ru/api", transport=web)
        self.assertEqual(web.calls[0]["headers"]["User-Agent"], common.USER_AGENT)


if __name__ == "__main__":
    unittest.main()
