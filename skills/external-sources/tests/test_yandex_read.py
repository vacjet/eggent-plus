"""Яндекс: Метрика, Вебмастер, Директ — чтение, ошибка авторизации, отсутствие дублей."""

from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
import urllib.parse
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import common
import yandex_read
from support import FakeWeb

HOST_ENCODED = "https%3Aexample.ru%3A443"
REPORT = (
    '"eggent-plus-2026-11-01-2026-11-13"\n'
    "Date\tCampaignId\tImpressions\tClicks\tCost\n"
    "2026-11-04\t11111111\t9899\t199\t2135000000\n"
    "2026-11-05\t11111111\t100\t5\t500000\n"
)


def web_with_yandex():
    web = FakeWeb()
    web.route(
        "management/v1/counters",
        body={"rows": 1, "counters": [{"id": 12345678, "name": "Example Brand", "site": "example.ru"}]},
    )
    web.route(
        "stat/v1/data",
        body={
            "data": [
                {"dimensions": [{"name": "2026-10-01"}], "metrics": [120, 100]},
                {"dimensions": [{"name": "2026-11-01"}], "metrics": [80, 70]},
            ]
        },
    )
    web.route(
        f"hosts/{HOST_ENCODED}/summary",
        body={"sqi": 50, "searchable_pages_count": 112, "excluded_pages_count": 3, "site_problems": {"POSSIBLE_PROBLEM": 3}},
    )
    web.route(
        f"hosts/{HOST_ENCODED}/indexing/history",
        body={"indicators": {"HTTP_3XX": [{"date": "2026-10-05T13:00:00.000+03:00", "value": 64}]}},
    )
    web.route(
        f"hosts/{HOST_ENCODED}/sitemaps",
        body={"sitemaps": [{"sitemap_url": "https://example.ru/sitemap.xml", "urls_count": 66, "errors_count": 0}]},
    )
    web.route(
        "/hosts/",
        body={"hosts": [{"host_id": "https:example.ru:443", "ascii_host_url": "https://example.ru/"}]},
    )
    web.route("v4/user/", body={"user_id": 39372124})
    web.route(
        "json/v5/campaigns",
        body={"result": {"Campaigns": [{"Id": 11111111, "Name": "Кампания A", "State": "ON", "Type": "TEXT_CAMPAIGN"}]}},
    )
    return web


class MetrikaTest(unittest.TestCase):
    def test_visits_keyed_by_counter_and_month(self):
        with tempfile.TemporaryDirectory() as out:
            result = yandex_read.metrika_read("token", out, transport=web_with_yandex())
            self.assertEqual(result["counters"], 1)
            stored = common.read_json(os.path.join(out, "yandex", "metrika.json"), {})
            self.assertEqual(sorted(stored["visits"]), ["12345678|2026-10", "12345678|2026-11"])
            self.assertEqual(stored["visits"]["12345678|2026-10"]["visits"], 120)
            self.assertEqual(stored["counters"]["12345678"]["name"], "Example Brand")

    def test_rerun_overwrites_visits_without_duplicates(self):
        with tempfile.TemporaryDirectory() as out:
            yandex_read.metrika_read("token", out, transport=web_with_yandex())
            yandex_read.metrika_read("token", out, transport=web_with_yandex())
            stored = common.read_json(os.path.join(out, "yandex", "metrika.json"), {})
            self.assertEqual(len(stored["visits"]), 2)

    def test_token_reaches_api_and_status_names_counter(self):
        web = web_with_yandex()
        with tempfile.TemporaryDirectory() as out:
            yandex_read.metrika_read("token-123", out, transport=web)
            self.assertEqual(web.calls[0]["headers"]["Authorization"], "OAuth token-123")
            entry = common.read_status(out)["sources"]["metrika"]
            self.assertTrue(entry["ok"])
            self.assertIn("счётчик 12345678 Example Brand", entry["objects"])


class MetrikaPaginationTest(unittest.TestCase):
    def test_offset_moves_by_page_and_counters_are_not_lost(self):
        counters = [{"id": number, "name": f"c{number}"} for number in range(1, 251)]
        offsets: list[int] = []

        def transport(**kwargs):
            query = urllib.parse.parse_qs(urllib.parse.urlsplit(kwargs["url"]).query)
            offset = int(query.get("offset", ["1"])[0])
            per_page = int(query.get("per_page", ["100"])[0])
            offsets.append(offset)
            page = counters[offset - 1 : offset - 1 + per_page]
            body = json.dumps({"rows": len(counters), "counters": page}).encode("utf-8")
            return {"status": 200, "headers": {}, "body": body, "url": kwargs["url"]}

        result = yandex_read.metrika_counters("token", transport=transport)
        self.assertEqual(len(result), 250)
        self.assertEqual(len({item["id"] for item in result}), 250)
        self.assertEqual(offsets, [1, 101, 201])


class MetrikaWindowTest(unittest.TestCase):
    def test_stale_months_are_dropped_when_window_narrows(self):
        with tempfile.TemporaryDirectory() as out:
            os.makedirs(os.path.join(out, "yandex"))
            common.write_json(
                os.path.join(out, "yandex", "metrika.json"),
                {"visits": {"12345678|2024-01": {"counter": 12345678, "month": "2024-01", "visits": 1, "users": 1}}},
            )
            yandex_read.metrika_read("token", out, months=6, transport=web_with_yandex())
            stored = common.read_json(os.path.join(out, "yandex", "metrika.json"), {})
            self.assertNotIn("12345678|2024-01", stored["visits"])


class WebmasterTest(unittest.TestCase):
    def test_hosts_and_indexing_are_stored(self):
        with tempfile.TemporaryDirectory() as out:
            result = yandex_read.webmaster_read("token", out, transport=web_with_yandex())
            self.assertEqual(result["hosts"], 1)
            self.assertEqual(result["searchable"], 112)
            stored = common.read_json(os.path.join(out, "yandex", "webmaster.json"), {})
            host = stored["hosts"]["https:example.ru:443"]
            self.assertEqual(host["sqi"], 50)
            self.assertIn("HTTP_3XX", stored["indexing"]["https:example.ru:443"]["indicators"])
            self.assertEqual(stored["sitemaps"]["https:example.ru:443"][0]["urls_count"], 66)
            entry = common.read_status(out)["sources"]["webmaster"]
            self.assertIn("https://example.ru/", entry["objects"])

    def test_rerun_keeps_one_entry_per_host(self):
        with tempfile.TemporaryDirectory() as out:
            yandex_read.webmaster_read("token", out, transport=web_with_yandex())
            yandex_read.webmaster_read("token", out, transport=web_with_yandex())
            stored = common.read_json(os.path.join(out, "yandex", "webmaster.json"), {})
            self.assertEqual(len(stored["hosts"]), 1)
            self.assertEqual(len(stored["indexing"]), 1)


class DirectTest(unittest.TestCase):
    def transport(self, *, report_status=200):
        web = web_with_yandex()

        def route(**kwargs):
            if "reports" in kwargs["url"]:
                if report_status != 200:
                    return {"status": report_status, "headers": {}, "body": b'{"error":"no"}', "url": kwargs["url"]}
                return {"status": 200, "headers": {}, "body": REPORT.encode("utf-8"), "url": kwargs["url"]}

            return web(**kwargs)

        return route

    def test_report_rows_and_cost_in_rubles(self):
        with tempfile.TemporaryDirectory() as out:
            result = yandex_read.direct_read("token", out, date_from="2026-11-01", date_to="2026-11-13", transport=self.transport())
            self.assertEqual(result["campaigns"], 1)
            self.assertEqual(result["rows"], 2)
            self.assertEqual(result["clicks"], 204)
            self.assertAlmostEqual(result["cost"], 2135.5)
            stored = common.read_json(os.path.join(out, "yandex", "direct.json"), {})
            rows = stored["reports"]["2026-11-01|2026-11-13"]["rows"]
            self.assertEqual(sorted(rows), ["2026-11-04|11111111", "2026-11-05|11111111"])
            self.assertAlmostEqual(rows["2026-11-04|11111111"]["cost"], 2135.0)

    def test_rerun_same_period_does_not_duplicate_rows(self):
        with tempfile.TemporaryDirectory() as out:
            for _ in range(2):
                yandex_read.direct_read("token", out, date_from="2026-11-01", date_to="2026-11-13", transport=self.transport())
            stored = common.read_json(os.path.join(out, "yandex", "direct.json"), {})
            self.assertEqual(len(stored["reports"]["2026-11-01|2026-11-13"]["rows"]), 2)

    def test_auth_failure_on_report_is_reported(self):
        with tempfile.TemporaryDirectory() as out:
            with self.assertRaises(common.AuthError) as caught:
                yandex_read.direct_read("token", out, date_from="2026-11-01", date_to="2026-11-13", transport=self.transport(report_status=403))
            self.assertIn("ошибка авторизации", str(caught.exception))

    def test_report_retry_when_not_ready(self):
        web = web_with_yandex()
        state = {"calls": 0, "pauses": []}

        def route(**kwargs):
            if "reports" in kwargs["url"]:
                state["calls"] += 1
                if state["calls"] == 1:
                    return {"status": 202, "headers": {}, "body": b'{"retryIn": 1}', "url": kwargs["url"]}
                return {"status": 200, "headers": {}, "body": REPORT.encode("utf-8"), "url": kwargs["url"]}
            return web(**kwargs)

        with tempfile.TemporaryDirectory():
            yandex_read.direct_report(
                "token",
                "2026-11-01",
                "2026-11-13",
                transport=route,
                pause=lambda seconds: state["pauses"].append(seconds),
            )
        self.assertEqual(state["calls"], 2)
        self.assertEqual(state["pauses"], [1])


class RunSourceTest(unittest.TestCase):
    def test_broken_token_gives_auth_exit_code_and_status_error(self):
        web = FakeWeb().route("management/v1/counters", status=401, body={"error": "invalid token"})
        with tempfile.TemporaryDirectory() as out:
            with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
                code = yandex_read.run_source("metrika", out_dir=out, token_file=None, transport=web)
            self.assertEqual(code, common.EXIT_AUTH)
            entry = common.read_status(out)["sources"]["metrika"]
            self.assertFalse(entry["ok"])
            self.assertIn("ошибка авторизации", entry["error"])

    def test_missing_token_is_auth_error_not_crash(self):
        os.environ.pop("YANDEX_SEO_TOKEN", None)
        with tempfile.TemporaryDirectory() as out:
            with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
                code = yandex_read.run_source("metrika", out_dir=out, token_file=None)
            self.assertEqual(code, common.EXIT_AUTH)

    def test_server_error_is_failed_exit_code(self):
        web = FakeWeb().route("management/v1/counters", status=500, body=b"")
        os.environ["YANDEX_SEO_TOKEN"] = "token"
        try:
            with tempfile.TemporaryDirectory() as out:
                with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
                    code = yandex_read.run_source("metrika", out_dir=out, token_file=None, transport=web)
                self.assertEqual(code, common.EXIT_FAILED)
        finally:
            del os.environ["YANDEX_SEO_TOKEN"]

    def test_cli_returns_auth_code_for_broken_token(self):
        web = FakeWeb().route("management/v1/counters", status=403, body={"error": "bad"})
        with tempfile.TemporaryDirectory() as out:
            with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
                code = yandex_read.main(["--source", "metrika", "--out", out], transport=web)
            self.assertEqual(code, common.EXIT_AUTH)

    def test_cli_all_keeps_auth_code_when_one_source_fails(self):
        web = FakeWeb().route("management/v1/counters", status=401, body={"error": "bad"})
        with tempfile.TemporaryDirectory() as out:
            with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
                code = yandex_read.main(["--source", "metrika", "--out", out], transport=web)
            self.assertEqual(code, common.EXIT_AUTH)

    def test_status_command_prints_without_network(self):
        with tempfile.TemporaryDirectory() as out, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(yandex_read.main(["--status", "--out", out]), common.EXIT_OK)


if __name__ == "__main__":
    unittest.main()
