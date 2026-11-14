#!/usr/bin/env python3
"""Одна страница «что работает, а что нет» — без телеметрии и без сети наружу.

    python3 scripts/diagnose.py --data /app/data
    python3 scripts/diagnose.py --data /app/data --url http://127.0.0.1:3000
    python3 scripts/diagnose.py --self-test

Проверяет то, что ломается чаще всего и видно только после «почему не отвечает»:
какая сборка отвечает, настроена ли модель, поднят ли сервис, сколько серверов MCP,
работают ли расписания, есть ли место на диске и может ли приложение писать в свои данные.

Секретов не печатает: из `auth.json` берутся только имена провайдеров.
Коды: 0 — всё в порядке (или только предупреждения), 1 — есть отказ, 2 — ошибка запуска.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

OK, WARN, FAIL = "ok", "warn", "fail"
MARKS = {OK: "ok  ", WARN: "warn", FAIL: "FAIL"}


def read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def check_build(data: Path) -> tuple[str, str]:
    """Какая сборка отвечает: образ главнее отметки развёртывания."""
    for label, path in (("образ", data.parent / "build-info.json"), ("данные", data / "build-info.json")):
        info = read_json(path)
        if isinstance(info, dict) and info.get("upstream"):
            version = info.get("version")
            if not version:
                base = str(info["upstream"]).lstrip("vV") or "0.0.0"
                version = f"{base}+plus.{info.get('patches') or 0}"
                if info.get("commit"):
                    version += f".{str(info['commit'])[:7]}"
            return OK, f"{version} (из {label}, патчей {info.get('patches')})"
    return WARN, "нет build-info.json ни в образе, ни в данных — сборка не наша?"


def check_model(data: Path) -> tuple[str, str]:
    auth = read_json(data / "pi-agent" / "auth.json")
    if not isinstance(auth, dict) or not auth:
        return FAIL, "нет ни одного провайдера в pi-agent/auth.json — модель не ответит"
    providers = ", ".join(sorted(auth.keys()))
    return OK, f"провайдеры: {providers}"


def check_health(url: str | None) -> tuple[str, str]:
    if not url:
        return WARN, "адрес не передан (--url), сервис не проверялся"
    try:
        with urllib.request.urlopen(f"{url.rstrip('/')}/api/health", timeout=5) as response:
            body = json.loads(response.read().decode("utf-8"))
        return OK, f"HTTP {response.status}, версия {body.get('version')}"
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError) as error:
        return FAIL, f"нет ответа: {error}"


def check_mcp(data: Path) -> tuple[str, str]:
    servers: list[str] = []
    workspace = read_json(data / "pi-agent" / "mcp.json")
    if isinstance(workspace, dict):
        servers += [f"сервер {name}" for name in (workspace.get("mcpServers") or {})]
    projects = data / "projects"
    if projects.is_dir():
        for project in sorted(p for p in projects.iterdir() if p.is_dir()):
            config = read_json(project / ".mcp.json")
            if isinstance(config, dict) and config.get("mcpServers"):
                servers.append(f"{project.name}: {len(config['mcpServers'])}")
    return (OK if servers else WARN), (", ".join(servers) if servers else "серверов MCP нет")


def check_schedules(data: Path) -> tuple[str, str]:
    schedules = read_json(data / "scripts" / "schedules.json")
    if schedules is None:
        return WARN, "расписаний нет (data/scripts/schedules.json отсутствует)"
    jobs = schedules.get("jobs") if isinstance(schedules, dict) else None
    if not isinstance(jobs, list):
        return WARN, "файл расписаний есть, но заданий в нём нет"
    disabled = [job for job in jobs if isinstance(job, dict) and job.get("enabled") is False]
    return OK, f"заданий: {len(jobs)}, выключено: {len(disabled)}"


def check_disk(data: Path) -> tuple[str, str]:
    try:
        usage = shutil.disk_usage(data)
    except OSError as error:
        return FAIL, f"не читается каталог данных: {error}"
    free_gb = usage.free / (1024**3)
    level = OK if free_gb >= 2 else FAIL
    return level, f"свободно {free_gb:.1f} ГБ из {usage.total / (1024**3):.0f} ГБ"


def check_writable(data: Path) -> tuple[str, str]:
    try:
        with tempfile.NamedTemporaryFile(dir=data, prefix=".diagnose-", delete=True):
            pass
        return OK, "приложение может писать в свои данные"
    except OSError as error:
        return FAIL, f"запись в данные не проходит: {error}"


CHECKS = (
    ("сборка", check_build),
    ("модель", check_model),
    ("сервис", None),
    ("mcp", check_mcp),
    ("расписания", check_schedules),
    ("диск", check_disk),
    ("запись в данные", check_writable),
)


def run(data: Path, url: str | None) -> int:
    if not data.is_dir():
        print(f"нет каталога данных: {data}", file=sys.stderr)
        return 2
    worst = OK
    print(f"данные: {data}\n")
    for name, check in CHECKS:
        if check is None:
            level, detail = check_health(url)
        else:
            level, detail = check(data)
        print(f"  {MARKS[level]}  {name:20} {detail}")
        if level == FAIL:
            worst = FAIL
    print()
    if worst == FAIL:
        print("есть отказы — смотри строки FAIL выше")
        return 1
    print("отказов нет")
    return 0


def self_test() -> int:
    failures = 0

    def case(name: str, ok: bool, detail: str = "") -> None:
        nonlocal failures
        print(f"  {'ok  ' if ok else 'FAIL'}  {name}{': ' + detail if detail and not ok else ''}")
        if not ok:
            failures += 1

    with tempfile.TemporaryDirectory(prefix="diagnose-") as work:
        root = Path(work)
        data = root / "data"
        data.mkdir()

        case("без build-info — предупреждение, не отказ", check_build(data)[0] == WARN)
        (root / "build-info.json").write_text(json.dumps({"upstream": "v0.8.0", "patches": 12, "version": "0.8.0+plus.12"}), encoding="utf-8")
        level, detail = check_build(data)
        case("сборка из образа читается", level == OK and "plus.12" in detail, detail)

        case("без провайдеров — отказ", check_model(data)[0] == FAIL)
        (data / "pi-agent").mkdir()
        (data / "pi-agent" / "auth.json").write_text(json.dumps({"deepseek": {"key": "x"}}), encoding="utf-8")
        level, detail = check_model(data)
        case("провайдер назван, ключ не печатается", level == OK and "deepseek" in detail and "x" not in detail.split(":", 1)[1], detail)

        (data / "projects" / "demo").mkdir(parents=True)
        (data / "projects" / "demo" / ".mcp.json").write_text(json.dumps({"mcpServers": {"context7": {}}}), encoding="utf-8")
        case("сервер MCP проекта виден", "demo: 1" in check_mcp(data)[1])

        case("расписаний нет — предупреждение", check_schedules(data)[0] == WARN)
        (data / "scripts").mkdir()
        (data / "scripts" / "schedules.json").write_text(json.dumps({"jobs": [{"enabled": True}, {"enabled": False}]}), encoding="utf-8")
        level, detail = check_schedules(data)
        case("задания посчитаны", level == OK and "заданий: 2" in detail, detail)

        case("запись проверяется делом", check_writable(data)[0] == OK)
        case("сервис без адреса — предупреждение", check_health(None)[0] == WARN)
        case("недоступный сервис — отказ", check_health("http://127.0.0.1:9")[0] == FAIL)

        code = run(data, None)
        case("полный прогон без отказов возвращает 0", code == 0, str(code))

    print(f"\nпровалов: {failures}")
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Диагностика экземпляра Eggent")
    parser.add_argument("--data", default="/app/data", help="каталог data экземпляра")
    parser.add_argument("--url", default="", help="адрес сервиса, например http://127.0.0.1:3000")
    parser.add_argument("--self-test", action="store_true", help="негативные кейсы самого скрипта")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    return run(Path(args.data).expanduser().resolve(), args.url or None)


if __name__ == "__main__":
    raise SystemExit(main())
