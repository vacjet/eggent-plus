"""Сайт как источник: robots, sitemap, коды страниц, повторный запуск."""

from __future__ import annotations

import contextlib
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import common
import site_audit
from support import FakeWeb

BASE = "https://example.ru"
TWO = BASE + "/two?a=1&b=2"


def web_with_site():
    web = FakeWeb()
    web.route(
        "robots.txt",
        body="User-agent: *\nDisallow: /admin\nSitemap: https://example.ru/sitemap-index.xml\n",
    )
    web.route(
        "sitemap-index.xml",
        body=(
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            "<sitemap><loc>https://example.ru/sitemap-pages.xml</loc></sitemap>"
            "</sitemapindex>"
        ),
    )
    web.route(
        "sitemap-pages.xml",
        body=(
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            "<url><loc>https://example.ru/</loc></url>"
            "<url><loc>https://example.ru/one</loc></url>"
            "<url><loc>https://example.ru/two?a=1&amp;b=2</loc></url>"
            "<url><loc>https://example.ru/moved</loc></url>"
            "</urlset>"
        ),
    )
    web.route("^" + BASE + "/sitemap.xml$", status=404, body=b"no sitemap")
    web.route("^" + BASE + "/one$", body=b"<html>one</html>", headers={"Content-Type": "text/html"})
    web.route(r"^https://example\.ru/two", status=404, body=b"not found")
    web.route("^" + BASE + "/moved$", status=301, body=b"", url=BASE + "/final")
    web.route("^" + BASE + "/$", body=b"<html>home</html>", headers={"Content-Type": "text/html"})
    return web


def web_with_foreign_links():
    '''Sitemap — недоверенный вход: чужие хосты и битые адреса не должны проверяться.'''
    web = FakeWeb()
    web.route("robots.txt", body="Sitemap: https://elsewhere.example/sitemap.xml\n")
    web.route(
        "^https://example\\.ru/sitemap.xml$",
        body=(
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            "<url><loc>https://example.ru/ok</loc></url>"
            "<url><loc>https://example.ru.evil.com/x</loc></url>"
            "<url><loc>https://example.ru@evil.com/y</loc></url>"
            "<url><loc>https://example.ru:4444/z</loc></url>"
            "<url><loc>https://[::1</loc></url>"
            "</urlset>"
        ),
    )
    web.route("^https://example\\.ru/ok$", body=b"<html>ok</html>")
    return web


class ParseTest(unittest.TestCase):
    def test_robots_reads_sitemaps_and_disallow(self):
        parsed = site_audit.parse_robots(
            "# комментарий\nSITEMAP: https://example.ru/sitemap.xml\nDisallow: /admin # закрыто\nDisallow:\n"
        )
        self.assertEqual(parsed["sitemaps"], ["https://example.ru/sitemap.xml"])
        self.assertEqual(parsed["disallow"], ["/admin"])

    def test_sitemap_urlset_with_namespace(self):
        body = (
            b'<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            b"<url><loc>https://example.ru/a&amp;b</loc></url></urlset>"
        )
        urls, children = site_audit.parse_sitemap(body)
        self.assertEqual(urls, ["https://example.ru/a&b"])
        self.assertEqual(children, [])

    def test_sitemap_index_returns_children(self):
        body = (
            b'<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            b"<sitemap><loc>https://example.ru/child.xml</loc></sitemap></sitemapindex>"
        )
        urls, children = site_audit.parse_sitemap(body)
        self.assertEqual(urls, [])
        self.assertEqual(children, ["https://example.ru/child.xml"])

    def test_not_a_sitemap_is_an_error(self):
        with self.assertRaises(common.SourceError):
            site_audit.parse_sitemap(b"<html>no sitemap here</html>")

    def test_site_url_must_be_http(self):
        with self.assertRaises(common.SourceError):
            site_audit.base_url("ftp://example.ru")
        with self.assertRaises(common.SourceError):
            site_audit.base_url("example.ru")


class AuditTest(unittest.TestCase):
    def test_audit_collects_pages_and_findings(self):
        with tempfile.TemporaryDirectory() as out:
            snapshot = site_audit.audit(BASE, out_dir=out, transport=web_with_site())
            self.assertEqual(len(snapshot["pages"]), 4)
            self.assertEqual(snapshot["pages"][BASE + "/one"]["status"], 200)
            self.assertEqual(snapshot["pages"][TWO]["status"], 404)
            reasons = {item["url"]: item["reason"] for item in snapshot["findings"]}
            self.assertEqual(reasons[TWO], "HTTP 404")
            self.assertIn("редирект", reasons[BASE + "/moved"])
            self.assertEqual(snapshot["robots"]["disallow"], 1)
            self.assertEqual(snapshot["summary"]["ok"], 2)

    def test_ampersand_in_sitemap_survives(self):
        with tempfile.TemporaryDirectory() as out:
            snapshot = site_audit.audit(BASE, out_dir=out, transport=web_with_site())
            self.assertIn(TWO, snapshot["pages"])

    def test_rerun_does_not_duplicate_pages(self):
        with tempfile.TemporaryDirectory() as out:
            site_audit.audit(BASE, out_dir=out, transport=web_with_site())
            site_audit.audit(BASE, out_dir=out, transport=web_with_site())
            stored = common.read_json(os.path.join(out, "site", "pages.json"), {})
            self.assertEqual(len(stored["pages"]), 4)
            self.assertEqual(len(stored["findings"]), 2)

    def test_limit_cuts_number_of_pages(self):
        with tempfile.TemporaryDirectory() as out:
            snapshot = site_audit.audit(BASE, out_dir=out, limit=2, transport=web_with_site())
            self.assertEqual(len(snapshot["pages"]), 2)

    def test_status_shows_time_and_objects(self):
        with tempfile.TemporaryDirectory() as out:
            site_audit.audit(BASE, out_dir=out, transport=web_with_site())
            entry = common.read_status(out)["sources"]["site"]
            self.assertTrue(entry["ok"])
            self.assertTrue(entry["lastRun"].endswith("Z"))
            self.assertIn(f"сайт {BASE}", entry["objects"])
            self.assertIn("sitemap: 4 адресов", entry["objects"])

    def test_unreachable_site_reports_failure(self):
        web = FakeWeb().route("robots.txt", error=common.SourceError("нет связи"))
        with tempfile.TemporaryDirectory() as out, self.assertRaises(common.SourceError):
            site_audit.audit(BASE, out_dir=out, transport=web)


class ForeignLinksTest(unittest.TestCase):
    def test_only_own_site_is_fetched(self):
        with tempfile.TemporaryDirectory() as out:
            snapshot = site_audit.audit(BASE, out_dir=out, transport=web_with_foreign_links())
            self.assertEqual(sorted(snapshot["pages"]), [BASE + "/ok"])
            skipped = [item["url"] for item in snapshot["findings"] if item["reason"].startswith("вне сайта")]
            self.assertEqual(len(skipped), 4)
            self.assertIn("https://example.ru.evil.com/x", skipped)


class CliTest(unittest.TestCase):
    def test_status_only_does_not_touch_network(self):
        with tempfile.TemporaryDirectory() as out:
            os.environ["EGGENT_EXTERNAL_DIR"] = out
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(site_audit.main(["--status", "--out", out]), common.EXIT_OK)
            finally:
                del os.environ["EGGENT_EXTERNAL_DIR"]

    def test_missing_site_is_a_usage_error(self):
        with (
            tempfile.TemporaryDirectory() as out,
            self.assertRaises(SystemExit),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            site_audit.main(["--out", out])


if __name__ == "__main__":
    unittest.main()
