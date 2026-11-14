"""Сайт как источник: robots.txt, sitemap и коды страниц. Только чтение.

Запуск:
    python3 site_audit.py --site https://example.ru --out /app/data/external
    python3 site_audit.py --status --out /app/data/external

Пишет `site/pages.json` (страница = строка, ключ — URL, повторный запуск перезаписывает,
дублей нет) и общий `status.json`.
"""

from __future__ import annotations

import argparse
import html
import os
import re
import sys
import urllib.parse

from common import (
    EXIT_FAILED,
    EXIT_OK,
    SourceError,
    http_request,
    now_iso,
    render_status,
    same_site,
    update_status,
    write_json,
)

MAX_BODY = 64 * 1024
MAX_SITEMAP = 8 * 1024 * 1024
SOURCE = "site"
LOC_PATTERN = re.compile(r"<loc>(.*?)</loc>", re.DOTALL | re.IGNORECASE)


def base_url(site: str) -> str:
    """`https://example.ru/anything` → `https://example.ru`."""
    parsed = urllib.parse.urlsplit(site.strip())
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise SourceError(f"нужен адрес сайта вида https://example.ru, получено: {site!r}")
    return f"{parsed.scheme}://{parsed.netloc}"


def parse_robots(text: str) -> dict:
    """Sitemap-адреса и запреты из robots.txt. Комментарии и регистр — как в стандарте."""
    sitemaps: list[str] = []
    disallow: list[str] = []
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip().lower()
        value = value.strip()
        if not value:
            continue
        if key == "sitemap":
            sitemaps.append(value)
        elif key == "disallow":
            disallow.append(value)
    return {"sitemaps": sitemaps, "disallow": disallow}


def parse_sitemap(body: bytes) -> tuple[list[str], list[str]]:
    """Разобрать sitemap или sitemap-индекс: (адреса страниц, адреса вложенных sitemap).

    Разбор — по `<loc>`, без XML-парсера: у sitemap бывает один нужный элемент,
    а любой парсер XML — это лишняя поверхность для чужого документа (XXE, «миллион
    смешных картинок»). Адреса всё равно проверяются на http(s).
    """
    text = body[:MAX_SITEMAP].decode("utf-8", errors="replace")
    lowered = text[:4096].lower()
    if "<sitemapindex" in lowered:
        kind = "children"
    elif "<urlset" in lowered or "<url>" in lowered:
        kind = "urls"
    else:
        raise SourceError("ответ не похож на sitemap: нет ни <urlset>, ни <sitemapindex>")
    locations = [
        html.unescape(match.strip())
        for match in LOC_PATTERN.findall(text)
        if match.strip()
    ]
    if kind == "children":
        return [], locations
    return locations, []


def _unique(items):
    """Порядок важен: sitemap читается сверху вниз, лимит отрезает хвост."""
    seen = set()
    result = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def collect_urls(base: str, robots: dict, *, limit: int, max_sitemaps: int, timeout: float, transport=None):
    """Адреса страниц из sitemap (с заходом в индекс) с запасным вариантом «главная».

    Чужие sitemap не читаем: robots.txt и sitemap — недоверенный вход, а `Sitemap:`
    может указывать на любой хост. Список обрезается по ходу, а не после сбора:
    sitemap на сотни тысяч адресов не должен занимать память целиком.
    """
    queue = [item for item in _unique(list(robots.get("sitemaps") or []) + [f"{base}/sitemap.xml"]) if same_site(item, base)]
    urls: list[str] = []
    visited: list[str] = []
    while queue and len(visited) < max_sitemaps and len(urls) < limit:
        sitemap_url = queue.pop(0)
        if sitemap_url in visited:
            continue
        visited.append(sitemap_url)
        try:
            answer = http_request(sitemap_url, timeout=timeout, transport=transport)
        except SourceError:
            continue
        if answer["status"] != 200:
            continue
        try:
            page_urls, child_sitemaps = parse_sitemap(answer["body"])
        except SourceError:
            continue
        urls.extend(page_urls[: max(0, limit - len(urls))])
        queue.extend(item for item in child_sitemaps if item not in visited and same_site(item, base))
    return _unique(urls)[:limit] or [f"{base}/"], visited


def audit(site: str, *, out_dir: str, limit: int = 50, timeout: float = 30.0, max_sitemaps: int = 5, transport=None) -> dict:
    """Прочитать robots, sitemap и до `limit` страниц. Возвращает снимок."""
    base = base_url(site)
    robots_answer = http_request(f"{base}/robots.txt", timeout=timeout, transport=transport)
    robots_status = robots_answer["status"]
    robots = {"status": robots_status, "sitemaps": [], "disallow": 0}
    if robots_status == 200:
        parsed = parse_robots(robots_answer["body"].decode("utf-8", errors="replace"))
        robots = {"status": robots_status, "sitemaps": parsed["sitemaps"], "disallow": len(parsed["disallow"])}

    urls, sitemaps = collect_urls(
        base, robots, limit=limit, max_sitemaps=max_sitemaps, timeout=timeout, transport=transport
    )

    pages: dict[str, dict] = {}
    skipped: list[str] = []
    homepage_ok = False
    for url in urls:
        if not same_site(url, base):
            skipped.append(url)
            continue
        record = {"checkedAt": now_iso(), "status": None, "finalUrl": None, "bytes": 0, "contentType": None, "error": None}
        try:
            answer = http_request(url, timeout=timeout, transport=transport)
            body = answer["body"][:MAX_BODY]
            record.update(
                {
                    "status": answer["status"],
                    "finalUrl": answer["url"],
                    "bytes": len(body),
                    "contentType": (answer["headers"] or {}).get("Content-Type"),
                }
            )
            if answer["status"] == 200 and url in (f"{base}/", base):
                homepage_ok = True
        except SourceError as error:
            record["error"] = str(error)
        pages[url] = record  # ключ — URL: повторный запуск перезаписывает строку

    if not pages:
        raise SourceError(f"не удалось прочитать ни одной страницы {base}")

    findings = []
    for url in skipped:
        findings.append({"url": url, "reason": "вне сайта: не проверяли"})
    for url, page in pages.items():
        moved = page["finalUrl"] and page["finalUrl"].rstrip("/") != url.rstrip("/")
        if page["status"] is None:
            findings.append({"url": url, "reason": page["error"] or "нет ответа"})
        elif moved:
            findings.append({"url": url, "reason": f"редирект на {page['finalUrl']}"})
        elif page["status"] != 200:
            findings.append({"url": url, "reason": f"HTTP {page['status']}"})

    snapshot = {
        "site": base,
        "updatedAt": now_iso(),
        "robots": robots,
        "sitemaps": sitemaps,
        "pages": pages,
        "findings": findings,
    }
    write_json(os.path.join(out_dir, "site", "pages.json"), snapshot)

    ok_count = sum(1 for page in pages.values() if page["status"] == 200)
    redirects = sum(1 for item in findings if "редирект" in item["reason"])
    counts = {
        "страниц": len(pages),
        "ok": ok_count,
        "не 200": len(pages) - ok_count,
        "редиректов": redirects,
        "sitemap": len(sitemaps),
    }
    objects = [f"сайт {base}", f"robots.txt: HTTP {robots_status}", f"sitemap: {len(urls)} адресов"]
    if not homepage_ok:
        objects.append("главная не отвечает 200")
    update_status(out_dir, SOURCE, ok=bool(ok_count), counts=counts, objects=objects, error=None)
    snapshot["summary"] = counts
    return snapshot


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="robots.txt, sitemap и коды страниц сайта")
    parser.add_argument("--site", help="адрес сайта, например https://example.ru")
    parser.add_argument("--out", default=os.environ.get("EGGENT_EXTERNAL_DIR", "external"), help="каталог данных")
    parser.add_argument("--limit", type=int, default=50, help="сколько страниц проверять (по умолчанию 50)")
    parser.add_argument("--max-sitemaps", type=int, default=5, help="сколько sitemap читать")
    parser.add_argument("--timeout", type=float, default=30.0, help="таймаут одного запроса, с")
    parser.add_argument("--status", action="store_true", help="только показать статус, без сети")
    arguments = parser.parse_args(argv)

    if arguments.status:
        print(render_status(arguments.out))
        return EXIT_OK
    if not arguments.site:
        parser.error("нужен --site или --status")

    try:
        snapshot = audit(
            arguments.site,
            out_dir=arguments.out,
            limit=max(1, arguments.limit),
            timeout=arguments.timeout,
            max_sitemaps=max(1, arguments.max_sitemaps),
        )
    except SourceError as error:
        update_status(arguments.out, SOURCE, ok=False, error=str(error))
        print(f"ошибка: {error}", file=sys.stderr)
        return EXIT_FAILED

    summary = snapshot["summary"]
    print(
        f"сайт {snapshot['site']}: страниц {summary['страниц']}, ok {summary['ok']}, "
        f"не 200 {summary['не 200']}, редиректов {summary['редиректов']}"
    )
    for finding in snapshot["findings"][:10]:
        print(f"  {finding['url']} — {finding['reason']}")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
