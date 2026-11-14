#!/usr/bin/env python3
"""Типизированная память проекта: проверка формата и запись пунктов.

    python3 scripts/memory.py check <memory.md>
    python3 scripts/memory.py add <memory.md> --type fact --text "..." --source "..."
    python3 scripts/memory.py add <memory.md> --type assumption --text "..." --check "чем проверить"
    python3 scripts/memory.py add <memory.md> --type decision --text "..." --reason "..." [--date ГГГГ-ММ-ДД]
    python3 scripts/memory.py add <memory.md> --type blocker --text "..."
    python3 scripts/memory.py --self-test

Зачем: в свободном тексте факт, догадка и решение неразличимы, а источник нигде, поэтому «решение»
растекается в общие правила и через месяц выдаётся за факт. Здесь у каждого типа свой раздел и своё
обязательное поле, и это проверяет код, а не память агента.

Коды: 0 — всё сходится / добавлено, 1 — нарушение (что именно в stderr), 2 — ошибка запуска.
"""

from __future__ import annotations

import argparse
import re
import sys
import tempfile
from datetime import date
from pathlib import Path

SECTIONS = {
    "fact": "## Факты",
    "assumption": "## Допущения",
    "decision": "## Решения",
    "blocker": "## Блокеры",
}
TITLES = {heading[3:].strip().lower(): kind for kind, heading in SECTIONS.items()}
REQUIRED = {
    "fact": ("источник", "факт без источника — это мнение"),
    "assumption": ("проверить", "допущение без «чем проверить» невозможно закрыть"),
    "decision": (None, None),
    "blocker": (None, None),
}
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
# В тексте человек пишет и 14.11.2026, и 2026-11-14; проверка принимает оба.
DATE_ANY_RE = re.compile(r"\d{4}-\d{2}-\d{2}|\d{2}\.\d{2}\.\d{4}")
FAQ_RE = re.compile(r"^\s*-\s+(?P<body>.+?)\s*$")


class MemoryError(Exception):
    """Нарушение формата: печатаем и выходим с кодом 1."""


def parse(text: str) -> dict[str, list[str]]:
    """Пункты по разделам. Разделы без пунктов остаются пустыми списками."""
    found: dict[str, list[str]] = {kind: [] for kind in SECTIONS}
    current: str | None = None
    for line in text.splitlines():
        heading = re.match(r"^##\s+(.+?)\s*$", line)
        if heading:
            current = TITLES.get(heading.group(1).strip().lower())
            continue
        if current is None:
            continue
        item = FAQ_RE.match(line)
        if item:
            found[current].append(item.group("body"))
    return found


def has_field(body: str, field: str) -> bool:
    return re.search(rf"{field}\s*:", body, re.IGNORECASE) is not None


def body_without_tail(body: str) -> str:
    """Текст пункта без хвоста «— источник: … / — проверить: …»."""
    return re.split(r"\s+[—–-]\s+(?:источник|проверить|дата|причина)\s*:", body, maxsplit=1)[0].strip().lower()


def problems_of(text: str) -> list[str]:
    """Нарушения формата; пустой список значит «память в порядке»."""
    found = parse(text)
    problems: list[str] = []

    if text.strip() and not any(found.values()) and "##" not in text:
        problems.append(
            "нет разделов: память должна быть разложена по «## Факты / Допущения / Решения / Блокеры»"
        )

    for kind, items in found.items():
        field, reason = REQUIRED[kind]
        for body in items:
            if not body.strip():
                problems.append(f"{SECTIONS[kind]}: пустой пункт")
                continue
            if field and not has_field(body, field):
                problems.append(f"{SECTIONS[kind]}: {reason} — «{body[:60]}»")
            if kind == "decision" and not DATE_ANY_RE.search(body):
                problems.append(f"{SECTIONS[kind]}: нет даты в формате ГГГГ-ММ-ДД — «{body[:60]}»")

    # Один и тот же текст не может быть и фактом, и допущением: это и есть «растекание».
    fact_texts = {body_without_tail(body) for body in found["fact"]}
    for body in found["assumption"]:
        if body_without_tail(body) in fact_texts:
            problems.append(
                f"допущение выдано за факт: «{body_without_tail(body)[:60]}» есть в обоих разделах"
            )
    return problems


def ensure_sections(text: str) -> str:
    result = text.rstrip()
    for heading in SECTIONS.values():
        if not re.search(rf"^##\s+{re.escape(heading[3:].strip())}\s*$", result, re.IGNORECASE | re.MULTILINE):
            result += f"\n\n{heading}\n"
    return result.rstrip() + "\n"


def add_item(path: Path, kind: str, text: str, source: str, check: str, reason: str, when: str) -> None:
    if not text.strip():
        raise MemoryError("пустой текст пункта")
    if kind == "fact" and not source.strip():
        raise MemoryError(REQUIRED["fact"][1])
    if kind == "assumption" and not check.strip():
        raise MemoryError(REQUIRED["assumption"][1])
    if kind == "decision" and not reason.strip():
        raise MemoryError("решение без причины — это приказ; укажи --reason")
    if when and not DATE_RE.fullmatch(when.strip()):
        raise MemoryError(f"дата должна быть ГГГГ-ММ-ДД, получено: {when}")

    existing = path.read_text(encoding="utf-8") if path.is_file() else ""
    body = text.strip()
    if kind == "fact":
        body += f" — источник: {source.strip()}"
    elif kind == "assumption":
        body += f" — проверить: {check.strip()}"
    elif kind == "decision":
        body += f" — {when or date.today().isoformat()}, причина: {reason.strip()}"

    content = ensure_sections(existing)
    heading = SECTIONS[kind]
    pattern = re.compile(rf"^({re.escape(heading)}\s*)$", re.IGNORECASE | re.MULTILINE)
    match = pattern.search(content)
    assert match is not None  # ensure_sections гарантирует раздел
    insert_at = match.end()
    content = content[:insert_at] + f"\n- {body}" + content[insert_at:]
    path.write_text(content, encoding="utf-8")


def self_test() -> int:
    failures = 0

    def case(name: str, ok: bool, detail: str = "") -> None:
        nonlocal failures
        print(f"  {'ok  ' if ok else 'FAIL'}  {name}{': ' + detail if detail and not ok else ''}")
        if not ok:
            failures += 1

    good = """## Факты
- В индексе 112 страниц — источник: data/external/webmaster.json, 14.11.2026

## Допущения
- Просадка из-за сезона — проверить: сравнить с прошлым годом

## Решения
- Правки по 404 первыми — 14.11.2026, причина: 23 страницы выпали

## Блокеры
- Нет доступа к staging
"""
    case("правильно оформленная память проходит", problems_of(good) == [], str(problems_of(good)))
    case(
        "факт без источника",
        any("источник" in problem for problem in problems_of("## Факты\n- 112 страниц в индексе\n")),
    )
    case(
        "допущение без способа проверить",
        any("проверить" in problem for problem in problems_of("## Допущения\n- Может, сезон\n")),
    )
    case(
        "решение без даты",
        any("даты" in problem for problem in problems_of("## Решения\n- Делаем 404 первыми\n")),
    )
    case(
        "допущение выдано за факт",
        any(
            "выдано за факт" in problem
            for problem in problems_of(
                "## Факты\n- Сезон — источник: ощущение\n\n## Допущения\n- Сезон — проверить: Метрика\n"
            )
        ),
    )
    case("память без разделов", any("нет разделов" in p for p in problems_of("просто текст про проект\n")))

    with tempfile.TemporaryDirectory(prefix="memory-") as work:
        path = Path(work) / "memory.md"
        path.write_text("# Память\n\nстарое содержимое\n", encoding="utf-8")
        add_item(path, "fact", "Сайт отдаёт 404 на 23 страницах", "data/external/site.json", "", "", "")
        text = path.read_text(encoding="utf-8")
        case("add создаёт раздел и пункт с источником", "## Факты" in text and "источник: data/external/site.json" in text)
        case("старое содержимое не потеряно", "старое содержимое" in text)
        case("записанная память проходит проверку", problems_of(text) == [], str(problems_of(text)))
        before = text
        try:
            add_item(path, "fact", "Без источника", "", "", "", "")
            case("add отказывает факту без источника", False, "не отказал")
        except MemoryError:
            case("add отказывает факту без источника", path.read_text(encoding="utf-8") == before)
        add_item(path, "decision", "Чиним 404 первыми", "", "", "23 страницы выпали", "2026-11-14")
        text = path.read_text(encoding="utf-8")
        case("решение записано с датой и причиной", "2026-11-14, причина: 23 страницы выпали" in text)
    print(f"\nпровалов: {failures}")
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Типизированная память проекта")
    parser.add_argument("--self-test", action="store_true", help="негативные кейсы самого скрипта")
    sub = parser.add_subparsers(dest="command")
    check = sub.add_parser("check", help="проверить формат memory.md")
    check.add_argument("path", help="путь к memory.md")
    add = sub.add_parser("add", help="добавить пункт")
    add.add_argument("path", help="путь к memory.md")
    add.add_argument("--type", required=True, choices=sorted(SECTIONS), help="тип пункта")
    add.add_argument("--text", required=True, help="текст пункта")
    add.add_argument("--source", default="", help="источник (обязателен для факта)")
    add.add_argument("--check", default="", help="чем проверить (обязательно для допущения)")
    add.add_argument("--reason", default="", help="причина (обязательна для решения)")
    add.add_argument("--date", default="", help="дата решения, ГГГГ-ММ-ДД (по умолчанию сегодня)")
    args = parser.parse_args()

    if args.self_test:
        return self_test()
    if args.command == "check":
        path = Path(args.path)
        if not path.is_file():
            print(f"нет файла: {path}", file=sys.stderr)
            return 2
        problems = problems_of(path.read_text(encoding="utf-8"))
        if problems:
            for problem in problems:
                print(f"FAIL: {problem}", file=sys.stderr)
            return 1
        print(f"ok: {path} — формат памяти в порядке")
        return 0
    if args.command == "add":
        try:
            add_item(Path(args.path), args.type, args.text, args.source, args.check, args.reason, args.date)
        except MemoryError as error:
            print(f"ошибка: {error}", file=sys.stderr)
            return 1
        print(f"добавлено в {Path(args.path)}")
        return 0
    parser.print_help(sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
