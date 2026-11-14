"""Яндекс.Метрика, Вебмастер и Директ: чтение данных. Только чтение.

Запуск:
    python3 yandex_read.py --source metrika --out /app/data/external
    python3 yandex_read.py --source all --token-file /app/data/secrets/yandex.env --out /app/data/external
    python3 yandex_read.py --status --out /app/data/external

Токены: `YANDEX_SEO_TOKEN` (Метрика и Вебмастер) и `YANDEX_DIRECT_TOKEN` (Директ) —
из окружения или из файла с правами 600. В отчёт и в журнал токен не попадает.
Повторный запуск перезаписывает записи по ключу (счётчик+месяц, хост, дата+кампания),
поэтому дублей не появляется.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.parse
from datetime import date, timedelta

from common import (
    EXIT_AUTH,
    EXIT_FAILED,
    EXIT_OK,
    AuthError,
    SourceError,
    http_request,
    now_iso,
    read_json,
    render_status,
    request_json,
    token_from,
    update_status,
    write_json,
)

METRIKA = "metrika"
WEBMASTER = "webmaster"
DIRECT = "direct"

METRIKA_API = "https://api-metrika.yandex.net"
WEBMASTER_API = "https://api.webmaster.yandex.net/v4"
DIRECT_API = "https://api.direct.yandex.com/json/v5"
REPORT_RETRIES = 5


def _oauth(token: str) -> dict:
    return {"Authorization": f"OAuth {token}"}


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json", "Accept-Language": "ru"}


def _month_start(months_back: int) -> date:
    """Первый день месяца, отстоящего на `months_back` назад от текущего."""
    today = date.today()
    month = today.month - months_back
    year = today.year + (month - 1) // 12
    month = (month - 1) % 12 + 1
    return date(year, month, 1)


# ── Метрика ──────────────────────────────────────────────────────────────────


def metrika_counters(token: str, *, transport=None, timeout: float = 30.0) -> list[dict]:
    """Все счётчики, к которым есть доступ.

    `offset` у Метрики — номер первого счётчика (1-based), поэтому шаг равен размеру
    полученной страницы, а не единице: иначе страницы перекрываются, крайние счётчики
    теряются, а в списке появляются дубли. Повторный id отбрасывается.
    """
    counters: list[dict] = []
    seen: set[str] = set()
    offset = 1
    for _ in range(100):  # потолок на случай, если API начнёт отдавать одно и то же
        url = f"{METRIKA_API}/management/v1/counters?per_page=100&offset={offset}"
        answer = request_json(url, headers=_oauth(token), timeout=timeout, transport=transport)
        batch = answer.get("counters") or []
        for item in batch:
            key = str(item.get("id"))
            if key not in seen:
                seen.add(key)
                counters.append(item)
        if not batch or len(counters) >= int(answer.get("rows") or 0):
            break
        offset += len(batch)
    return counters


def metrika_read(token: str, out_dir: str, *, counters=None, months: int = 12, timeout: float = 30.0, transport=None) -> dict:
    available = metrika_counters(token, timeout=timeout, transport=transport)
    if not available:
        raise SourceError("в Метрике нет ни одного счётчика: проверьте доступ аккаунта")
    chosen = [item for item in available if not counters or item.get("id") in counters]
    if not chosen:
        raise SourceError(f"счётчики {counters} недоступны этому токену")

    path = os.path.join(out_dir, "yandex", "metrika.json")
    store = read_json(path, {}) or {}
    store.setdefault("visits", {})
    store["counters"] = {
        str(item["id"]): {"name": item.get("name"), "site": item.get("site")} for item in available
    }
    date1 = _month_start(max(0, months - 1)).isoformat()
    date2 = date.today().isoformat()
    for item in chosen:
        counter_id = int(item["id"])
        query = urllib.parse.urlencode(
            {
                "ids": counter_id,
                "date1": date1,
                "date2": date2,
                "metrics": "ym:s:visits,ym:s:users",
                "dimensions": "ym:s:date",
                "group": "month",
                "limit": 100,
                "accuracy": "full",
            }
        )
        stat = request_json(
            f"{METRIKA_API}/stat/v1/data?{query}",
            headers=_oauth(token),
            timeout=timeout,
            transport=transport,
        )
        for row in stat.get("data") or []:
            dimensions = row.get("dimensions") or []
            metrics = row.get("metrics") or []
            if not dimensions or not metrics:
                continue
            month = str(dimensions[0].get("name", ""))[:7]
            if not month:
                continue
            store["visits"][f"{counter_id}|{month}"] = {
                "counter": counter_id,
                "month": month,
                "visits": int(metrics[0] or 0),
                "users": int(metrics[1] or 0) if len(metrics) > 1 else None,
            }
    # Срез один: месяцы выбранных счётчиков вне запрошенного окна убираем, иначе
    # прогон с меньшим --months оставлял бы в файле старые месяцы и завышал счётчики.
    chosen_ids = {str(item.get("id")) for item in chosen}
    window_start = date1[:7]
    for key in [
        key
        for key in store["visits"]
        if key.split("|")[0] in chosen_ids and key.split("|")[-1] < window_start
    ]:
        del store["visits"][key]

    store["updatedAt"] = now_iso()
    store["range"] = {"from": date1, "to": date2}
    write_json(path, store)

    total = sum(entry["visits"] for key, entry in store["visits"].items() if int(key.split("|")[0]) in {int(c["id"]) for c in chosen})
    counts = {"счётчиков": len(chosen), "месяцев": len({entry["month"] for entry in store["visits"].values()})}
    objects = [f"счётчик {c['id']} {c.get('name') or ''}".strip() for c in chosen[:5]]
    update_status(out_dir, METRIKA, ok=True, counts=counts, objects=objects)
    return {"counters": len(chosen), "visits": total, "months": counts["месяцев"]}


# ── Вебмастер ────────────────────────────────────────────────────────────────


def webmaster_user(token: str, *, transport=None, timeout: float = 30.0) -> str:
    answer = request_json(f"{WEBMASTER_API}/user/", headers=_oauth(token), timeout=timeout, transport=transport)
    user_id = answer.get("user_id")
    if not user_id:
        raise SourceError("Вебмастер не вернул user_id")
    return str(user_id)


def webmaster_read(token: str, out_dir: str, *, days: int = 30, timeout: float = 30.0, transport=None) -> dict:
    user = webmaster_user(token, timeout=timeout, transport=transport)
    hosts = request_json(f"{WEBMASTER_API}/user/{user}/hosts/", headers=_oauth(token), timeout=timeout, transport=transport).get("hosts") or []
    if not hosts:
        raise SourceError("в Вебмастере нет ни одного подтверждённого сайта")
    date_from = (date.today() - timedelta(days=days)).isoformat()
    date_to = date.today().isoformat()

    path = os.path.join(out_dir, "yandex", "webmaster.json")
    store = read_json(path, {}) or {}
    for name in ("hosts", "indexing", "sitemaps"):
        store.setdefault(name, {})
    for host in hosts:
        host_id = str(host.get("host_id") or "")
        if not host_id:
            continue
        encoded = urllib.parse.quote(host_id, safe="")
        summary = request_json(
            f"{WEBMASTER_API}/user/{user}/hosts/{encoded}/summary/",
            headers=_oauth(token),
            timeout=timeout,
            transport=transport,
        )
        store["hosts"][host_id] = {
            "url": host.get("ascii_host_url"),
            "sqi": summary.get("sqi"),
            "searchable": summary.get("searchable_pages_count"),
            "excluded": summary.get("excluded_pages_count"),
            "problems": summary.get("site_problems") or {},
            "checkedAt": now_iso(),
        }
        history = request_json(
            f"{WEBMASTER_API}/user/{user}/hosts/{encoded}/indexing/history/?date_from={date_from}&date_to={date_to}",
            headers=_oauth(token),
            timeout=timeout,
            transport=transport,
        )
        store["indexing"][host_id] = {"from": date_from, "to": date_to, "checkedAt": now_iso(), "indicators": history.get("indicators") or {}}
        sitemaps = request_json(
            f"{WEBMASTER_API}/user/{user}/hosts/{encoded}/sitemaps/",
            headers=_oauth(token),
            timeout=timeout,
            transport=transport,
        ).get("sitemaps") or []
        store["sitemaps"][host_id] = [
            {
                "url": item.get("sitemap_url"),
                "urls_count": item.get("urls_count"),
                "errors_count": item.get("errors_count"),
                "last_access": item.get("last_access_date"),
            }
            for item in sitemaps
        ]
    store["updatedAt"] = now_iso()
    write_json(path, store)

    searchable = sum(int(entry.get("searchable") or 0) for entry in store["hosts"].values())
    counts = {"сайтов": len(store["hosts"]), "страниц в поиске": searchable}
    objects = [entry.get("url") or host_id for host_id, entry in store["hosts"].items()][:5]
    update_status(out_dir, WEBMASTER, ok=True, counts=counts, objects=objects)
    return {"hosts": len(store["hosts"]), "searchable": searchable}


# ── Директ ───────────────────────────────────────────────────────────────────


def direct_campaigns(token: str, *, transport=None, timeout: float = 60.0) -> list[dict]:
    payload = {
        "method": "get",
        "params": {
            "SelectionCriteria": {},
            "FieldNames": ["Id", "Name", "State", "Type"],
        },
    }
    answer = request_json(
        f"{DIRECT_API}/campaigns",
        method="POST",
        headers=_bearer(token),
        data=json.dumps(payload).encode("utf-8"),
        timeout=timeout,
        transport=transport,
    )
    if answer.get("error"):
        raise SourceError(f"Директ отказал: {answer['error']}")
    return (answer.get("result") or {}).get("Campaigns") or []


def direct_report(token: str, date_from: str, date_to: str, *, transport=None, timeout: float = 60.0, pause=time.sleep) -> list[dict]:
    """Отчёт по кампаниям. Директ может ответить 201/202 и попросить повторить через N секунд."""
    payload = {
        "params": {
            "SelectionCriteria": {"DateFrom": date_from, "DateTo": date_to},
            "FieldNames": ["Date", "CampaignId", "Impressions", "Clicks", "Cost"],
            "ReportName": f"eggent-plus-{date_from}-{date_to}",
            "ReportType": "CAMPAIGN_PERFORMANCE_REPORT",
            "DateRangeType": "CUSTOM_DATE",
            "Format": "TSV",
            "IncludeVAT": "YES",
            "IncludeDiscount": "NO",
        }
    }
    body = json.dumps(payload).encode("utf-8")
    for attempt in range(REPORT_RETRIES + 1):
        answer = http_request(
            f"{DIRECT_API}/reports",
            method="POST",
            headers=_bearer(token),
            data=body,
            timeout=timeout,
            transport=transport,
        )
        status = answer["status"]
        text = answer["body"].decode("utf-8", errors="replace")
        if status in (401, 403):
            raise AuthError(f"ошибка авторизации: Директ ответил HTTP {status}")
        if status == 200:
            return _parse_report(text)
        if status in (201, 202):
            if attempt >= REPORT_RETRIES:
                break
            try:
                retry = int(json.loads(text).get("retryIn") or 5)
            except (ValueError, TypeError, AttributeError):
                retry = 5
            pause(min(30, max(1, retry)))
            continue
        raise SourceError(f"Директ ответил HTTP {status} на отчёт за {date_from}—{date_to}")
    raise SourceError("отчёт Директа не готов после повторов")


def _parse_report(text: str) -> list[dict]:
    rows: list[dict] = []
    header: list[str] | None = None
    for line in text.splitlines():
        if not line.strip():
            continue
        if line.lstrip().startswith('"'):
            continue  # первая строка — имя отчёта в кавычках
        cells = line.split("\t")
        if header is None:
            header = cells
            continue
        record = dict(zip(header, cells, strict=False))
        try:
            rows.append(
                {
                    "date": record.get("Date"),
                    "campaign": str(record.get("CampaignId") or ""),
                    "impressions": int(record.get("Impressions") or 0),
                    "clicks": int(record.get("Clicks") or 0),
                    "costMicros": int(float(record.get("Cost") or 0)),
                }
            )
        except ValueError:
            continue
    return rows


def direct_read(token: str, out_dir: str, *, date_from: str, date_to: str, timeout: float = 60.0, transport=None) -> dict:
    campaigns = direct_campaigns(token, timeout=timeout, transport=transport)
    rows = direct_report(token, date_from, date_to, timeout=timeout, transport=transport)

    path = os.path.join(out_dir, "yandex", "direct.json")
    store = read_json(path, {}) or {}
    store.setdefault("reports", {})
    store["campaigns"] = {
        str(item.get("Id")): {
            "name": item.get("Name"),
            "state": item.get("State"),
            "type": item.get("Type"),
        }
        for item in campaigns
        if item.get("Id") is not None
    }
    key = f"{date_from}|{date_to}"
    store["reports"][key] = {
        "from": date_from,
        "to": date_to,
        "checkedAt": now_iso(),
        "rows": {
            f"{row['date']}|{row['campaign']}": {**row, "cost": round(row["costMicros"] / 1_000_000, 2)}
            for row in rows
        },
    }
    store["updatedAt"] = now_iso()
    write_json(path, store)

    clicks = sum(row["clicks"] for row in rows)
    cost = round(sum(row["costMicros"] for row in rows) / 1_000_000, 2)
    active = [item for item in campaigns if item.get("State") == "ON"]
    counts = {"кампаний": len(store["campaigns"]), "активных": len(active), "строк отчёта": len(rows), "клики": clicks}
    objects = [f"{item.get('Name')} [{item.get('State')}]" for item in active[:5]]
    if not objects:
        objects = [f"{item.get('Name')} [{item.get('State')}]" for item in campaigns[:5]]
    objects.append(f"период {date_from}—{date_to}")
    update_status(out_dir, DIRECT, ok=True, counts={**counts, "расход, ₽": cost}, objects=objects)
    return {"campaigns": len(store["campaigns"]), "rows": len(rows), "clicks": clicks, "cost": cost}


# ── Общий запуск ─────────────────────────────────────────────────────────────


def run_source(name: str, *, out_dir: str, token_file: str | None, transport=None, counters=None,
               months: int = 12, days: int = 30, date_from: str | None = None, date_to: str | None = None,
               timeout: float = 60.0) -> int:
    """Один источник: ошибка авторизации — код 3, любая другая — 1."""
    try:
        if name == METRIKA:
            token = token_from("YANDEX_SEO_TOKEN", token_file)
            result = metrika_read(token, out_dir, counters=counters, months=months, timeout=timeout, transport=transport)
            print(f"Метрика: счётчиков {result['counters']}, визитов {result['visits']}")
        elif name == WEBMASTER:
            token = token_from("YANDEX_SEO_TOKEN", token_file)
            result = webmaster_read(token, out_dir, days=days, timeout=timeout, transport=transport)
            print(f"Вебмастер: сайтов {result['hosts']}, страниц в поиске {result['searchable']}")
        else:
            token = token_from("YANDEX_DIRECT_TOKEN", token_file)
            end = date_to or date.today().isoformat()
            start = date_from or (date.today() - timedelta(days=days)).isoformat()
            result = direct_read(token, out_dir, date_from=start, date_to=end, timeout=timeout, transport=transport)
            print(f"Директ: кампаний {result['campaigns']}, строк {result['rows']}, клики {result['clicks']}, расход {result['cost']} ₽")
        return EXIT_OK
    except AuthError as error:
        update_status(out_dir, name, ok=False, error=str(error))
        print(str(error), file=sys.stderr)
        return EXIT_AUTH
    except SourceError as error:
        update_status(out_dir, name, ok=False, error=str(error))
        print(f"{name}: ошибка — {error}", file=sys.stderr)
        return EXIT_FAILED


def main(argv: list[str] | None = None, transport=None) -> int:
    parser = argparse.ArgumentParser(description="Чтение данных из Метрики, Вебмастера и Директа")
    parser.add_argument("--source", choices=[METRIKA, WEBMASTER, DIRECT, "all"], default="all")
    parser.add_argument("--out", default=os.environ.get("EGGENT_EXTERNAL_DIR", "external"), help="каталог данных")
    parser.add_argument("--token-file", help="файл KEY=VALUE с токенами (права 600)")
    parser.add_argument("--counter", type=int, action="append", help="id счётчика Метрики (можно несколько)")
    parser.add_argument("--months", type=int, default=12, help="сколько месяцев Метрики брать")
    parser.add_argument("--days", type=int, default=30, help="окно Вебмастера и Директа, дней")
    parser.add_argument("--from", dest="date_from", help="начало периода Директа, YYYY-MM-DD")
    parser.add_argument("--to", dest="date_to", help="конец периода Директа, YYYY-MM-DD")
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--status", action="store_true", help="только показать статус, без сети")
    arguments = parser.parse_args(argv)

    if arguments.status:
        print(render_status(arguments.out))
        return EXIT_OK

    names = [METRIKA, WEBMASTER, DIRECT] if arguments.source == "all" else [arguments.source]
    codes = []
    for name in names:
        codes.append(
            run_source(
                name,
                out_dir=arguments.out,
                token_file=arguments.token_file,
                transport=transport,
                counters=arguments.counter,
                months=arguments.months,
                days=arguments.days,
                date_from=arguments.date_from,
                date_to=arguments.date_to,
                timeout=arguments.timeout,
            )
        )
    if EXIT_AUTH in codes:
        return EXIT_AUTH
    if EXIT_FAILED in codes:
        return EXIT_FAILED
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
