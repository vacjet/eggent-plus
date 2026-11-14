"""Общая часть скилла `external-sources`: HTTP, хранилище, статус.

Только стандартная библиотека: скилл копируется в проект Eggent и запускается тем же
python3, что в образе. Секреты не сохраняются — токен читается из файла с правами 600
или из переменной окружения и живёт только в памяти процесса.
"""

from __future__ import annotations

import http.client
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from typing import Any

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_AUTH = 3

# Ответ больше этого не читаем: чужой sitemap или страница на сотни мегабайт не должны
# выедать память процесса. Обрезанное тело — данные, а не повод падать.
MAX_RESPONSE = 8 * 1024 * 1024

STATUS_FILE = "status.json"
LOCK_FILE = "status.lock"
USER_AGENT = "eggent-plus-external/1.0"


class AuthError(Exception):
    """Источник ответил 401/403: токен неверный, просрочен или без прав."""


class SourceError(Exception):
    """Источник недоступен или ответил не тем, что ожидалось."""


def now_iso(when: datetime | None = None) -> str:
    """Время в UTC, ISO 8601 с `Z` — одинаково читается человеком и парсится машиной."""
    moment = when or datetime.now(UTC)
    return (
        moment.astimezone(UTC)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def http_request(
    url: str,
    *,
    method: str = "GET",
    headers: dict | None = None,
    data: bytes | None = None,
    timeout: float = 30.0,
    transport=None,
    max_bytes: int = MAX_RESPONSE,
) -> dict:
    """Один HTTP-запрос: `{status, headers, body, url}`.

    `url` — куда в итоге привёл ответ (редиректы urllib проходит сам).
    HTTP-ошибки (4xx/5xx) не бросаются: код — это данные, их обрабатывает вызывающий.
    Бросается только `SourceError`, когда до сервера не дошли.

    `transport` нужен для тестов: та же подпись, без сети. `max_bytes` — потолок тела:
    читаем не больше, остальное отбрасываем, а не копим в памяти.
    """
    ensure_http(url)
    url = ascii_url(url)
    headers = dict(headers or {})
    headers.setdefault("User-Agent", USER_AGENT)
    if transport is not None:
        answer = transport(
            url=url, method=method, headers=headers, data=data, timeout=timeout
        )
        answer.setdefault("url", url)
        return answer

    request = urllib.request.Request(url, method=method, headers=headers, data=data)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return {
                "status": response.status,
                "headers": dict(response.headers),
                "body": response.read(max_bytes),
                "url": response.geturl() or url,
            }
    except urllib.error.HTTPError as error:
        body = error.read(max_bytes) if hasattr(error, "read") else b""
        return {
            "status": error.code,
            "headers": dict(error.headers or {}),
            "body": body,
            "url": url,
        }
    except (urllib.error.URLError, http.client.InvalidURL, TimeoutError, OSError) as error:
        raise SourceError(f"нет связи с {_host(url)}: {error}") from error


def parse_url(url: str):
    """`urlsplit` + проверка схемы. Битый URL — `SourceError`, а не `ValueError` из недр urllib."""
    try:
        parsed = urllib.parse.urlsplit(url)
        host = parsed.hostname
        port = parsed.port
    except ValueError as error:
        raise SourceError(f"битый адрес: {url[:80]} ({error})") from error
    if parsed.scheme.lower() not in ("http", "https"):
        raise SourceError(f"адрес не по http(s): {url[:80]}")
    if not host:
        raise SourceError(f"в адресе нет имени хоста: {url[:80]}")
    if parsed.username or parsed.password:
        raise SourceError(f"адрес с логином в URL не поддерживается: {url[:80]}")
    return parsed, host, port


def ensure_http(url: str) -> str:
    """Разрешить только http/https: `file:` из чужого sitemap — это чтение нашего диска."""
    parse_url(url)
    return url


def same_site(url: str, base: str) -> bool:
    """Строгое сравнение: схема, хост и порт. `example.ru.evil.com` — уже другой сайт."""
    try:
        left, left_host, left_port = parse_url(url)
        right, right_host, right_port = parse_url(base)
    except SourceError:
        return False
    default = {"http": 80, "https": 443}
    left_default = default.get(left.scheme.lower())
    right_default = default.get(right.scheme.lower())
    return (
        left.scheme.lower() == right.scheme.lower()
        and left_host.lower() == right_host.lower()
        and (left_port or left_default) == (right_port or right_default)
    )


def ascii_url(url: str) -> str:
    """Кириллический домен → punycode: urllib сам этого не делает и падает с UnicodeEncodeError."""
    parsed, host, port = parse_url(url)
    try:
        ascii_host = host.encode("idna").decode("ascii")
    except UnicodeError as error:
        raise SourceError(f"имя хоста не приводится к IDNA: {host[:60]}") from error
    netloc = ascii_host
    if port:
        netloc = f"{ascii_host}:{port}"
    path = urllib.parse.quote(parsed.path, safe="/%:@!$&'()*+,;=~")
    query = urllib.parse.quote(parsed.query, safe="=&?/:@!$'()*+,;%~")
    return urllib.parse.urlunsplit((parsed.scheme, netloc, path, query, parsed.fragment))


def _host(url: str) -> str:
    parsed = urllib.parse.urlsplit(url)
    return parsed.netloc or url


def _auth_message(url: str, status: int) -> str:
    return f"ошибка авторизации: {_host(url)} ответил HTTP {status}"


def request_bytes(url: str, *, headers=None, timeout: float = 30.0, transport=None, data=None, method="GET"):
    """Тело ответа или `AuthError`/`SourceError`. Ожидается 200."""
    answer = http_request(
        url, method=method, headers=headers, data=data, timeout=timeout, transport=transport
    )
    status = answer["status"]
    if status in (401, 403):
        raise AuthError(_auth_message(url, status))
    if status != 200:
        raise SourceError(f"HTTP {status} для {_host(url)}")
    return answer["body"]


def request_json(url: str, *, headers=None, timeout: float = 30.0, transport=None, data=None, method="GET"):
    """Ответ как JSON или `AuthError`/`SourceError`."""
    body = request_bytes(
        url, headers=headers, timeout=timeout, transport=transport, data=data, method=method
    )
    try:
        return json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SourceError(f"ответ {_host(url)} — не JSON: {error}") from error


def read_json(path: str, default: Any = None) -> Any:
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError:
        return default
    except (OSError, json.JSONDecodeError):
        return default


def write_json(path: str, payload) -> None:
    """Запись через временный файл: оборванный запуск не оставляет половину файла."""
    directory = os.path.dirname(os.path.abspath(path))
    temporary = f"{path}.{os.getpid()}.tmp"  # свой у каждого процесса: два запуска не мешают друг другу
    try:
        os.makedirs(directory, exist_ok=True)
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(temporary, path)
    except OSError as error:
        raise SourceError(f"не удалось записать {path}: {error}") from error


def read_env_file(path: str) -> dict:
    """`KEY=VALUE` построчно; комментарии и пустые строки пропускаются.

    Формат тот же, что у `toolbox/secrets.env`: без `export`, кавычки не нужны.
    """
    values: dict[str, str] = {}
    try:
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip().strip('"').strip("'")
    except FileNotFoundError:
        pass
    return values


def token_from(env_name: str, token_file: str | None = None) -> str:
    """Токен из окружения, иначе из файла. Пусто — понятная ошибка, а не пустой заголовок."""
    value = os.environ.get(env_name, "").strip()
    if not value and token_file:
        value = read_env_file(token_file).get(env_name, "").strip()
    if not value:
        where = f"ни в окружении, ни в {token_file}" if token_file else "в окружении"
        raise AuthError(f"ошибка авторизации: токен {env_name} не найден {where}")
    return value


def status_path(out_dir: str) -> str:
    return os.path.join(out_dir, STATUS_FILE)


def read_status(out_dir: str) -> dict:
    return read_json(status_path(out_dir), {"updatedAt": None, "sources": {}}) or {
        "updatedAt": None,
        "sources": {},
    }


def update_status(
    out_dir: str,
    source: str,
    *,
    ok: bool,
    counts: dict | None = None,
    objects: list | None = None,
    error: str | None = None,
) -> dict:
    """Обновить запись одного источника, не теряя записи остальных.

    Повторный запуск перезаписывает запись этого источника — дублей в статусе нет.
    """
    try:
        os.makedirs(out_dir, exist_ok=True)
        with open(os.path.join(out_dir, LOCK_FILE), "a", encoding="utf-8") as lock:
            return _write_status(out_dir, lock, source, ok=ok, counts=counts, objects=objects, error=error)
    except OSError as failure:
        raise SourceError(f"не удалось открыть {out_dir}: {failure}") from failure


def _write_status(out_dir, lock, source, *, ok, counts, objects, error) -> dict:
    try:
        import fcntl

        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
    except (ImportError, OSError):
        pass  # без блокировки тоже работает: запись атомарна
    data = read_status(out_dir)
    sources = data.setdefault("sources", {})
    sources[source] = {
        "lastRun": now_iso(),
        "ok": bool(ok),
        "counts": counts or {},
        "objects": list(objects or []),
        "error": error,
    }
    data["updatedAt"] = sources[source]["lastRun"]
    write_json(status_path(out_dir), data)
    return sources[source]


def render_status(out_dir: str) -> str:
    """Человекочитаемая карточка статуса: когда обновлялось и что доступно."""
    data = read_status(out_dir)
    sources = data.get("sources") or {}
    if not sources:
        return "Статус пуст: ни один источник ещё не читался."
    lines = [f"Обновлено: {data.get('updatedAt') or '—'}"]
    for name in sorted(sources):
        entry = sources[name] or {}
        verdict = "ok" if entry.get("ok") else f"ошибка: {entry.get('error') or 'без описания'}"
        counts = ", ".join(f"{key} {value}" for key, value in sorted((entry.get("counts") or {}).items()))
        objects = "; ".join(entry.get("objects") or []) or "—"
        lines.append(f"\n{name}: {entry.get('lastRun') or '—'} — {verdict}")
        if counts:
            lines.append(f"  Счётчики: {counts}")
        lines.append(f"  Доступно: {objects}")
    return "\n".join(lines)


def host_of(url: str) -> str:
    return urllib.parse.urlsplit(url).netloc
