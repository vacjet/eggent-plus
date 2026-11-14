"""Подставной HTTP для тестов: без сети, с журналом вызовов.

`transport` у `common.http_request` — это функция с той же подписью, что у настоящего
запроса. Тест описывает маршруты, а не подменяет urllib.
"""

from __future__ import annotations

import json
import re
from typing import Any


class FakeWeb:
    def __init__(self) -> None:
        self.routes = []
        self.calls = []

    def route(self, match, *, status=200, body: Any = b"", headers=None, url=None, error=None):
        """`match` — подстрока адреса или функция(url) → bool."""
        if isinstance(body, str):
            body = body.encode("utf-8")
        elif not isinstance(body, bytes):
            body = json.dumps(body).encode("utf-8")
        self.routes.append(
            {
                "match": match,
                "status": status,
                "body": body,
                "headers": headers or {"Content-Type": "application/json"},
                "url": url,
                "error": error,
            }
        )
        return self

    def __call__(self, url, method="GET", headers=None, data=None, timeout=None):
        self.calls.append({"url": url, "method": method, "headers": dict(headers or {}), "data": data})
        for route in self.routes:
            matcher = route["match"]
            if callable(matcher):
                matched = bool(matcher(url))
            elif matcher.startswith("^"):
                matched = bool(re.match(matcher, url))  # точный маршрут, а не подстрока
            else:
                matched = matcher in url
            if not matched:
                continue
            if route["error"] is not None:
                raise route["error"]
            return {
                "status": route["status"],
                "headers": dict(route["headers"]),
                "body": route["body"],
                "url": route["url"] or url,
            }
        raise AssertionError(f"тест не описал маршрут для {url}")
