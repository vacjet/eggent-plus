#!/usr/bin/env python3
"""Проверка, что в публичный репозиторий не попали личные данные.

Репозиторий публичный: он про патч к Eggent, а не про работу заказчика. Поэтому здесь
не должно быть ни адресов, ни доступов, ни статистики. Правило (решение 41): домены,
кампании, суммы, почтовые адреса, IP, имена ключей — только плейсхолдерами.

Проверка двухслойная:

1. **Общие шаблоны** — работают всегда: IP-адреса, почтовые адреса не из `example.*`,
   SSH-ключи и пути к ним, токены, суммы в рублях.
2. **Личный денлист** — список настоящих значений (домен, фирма, почтовый адрес, имена
   ключей), который лежит **вне этого репозитория**: путь из `EGGENT_PRIVATE_DENYLIST`
   или `../notes/eggent-plus-deny.txt`. В публичном репозитории его нет и быть не должно —
   иначе проверка сама станет утечкой. Нет денлиста — работают только общие шаблоны,
   и об этом печатается предупреждение.

    python3 scripts/check-private.py
    python3 scripts/check-private.py --self-test
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DENYLIST = ROOT.parent / "notes" / "eggent-plus-deny.txt"
SKIP_DIRS = {".git", "upstream", "node_modules", ".next", "__pycache__", "data"}
SKIP_SUFFIXES = {".png", ".jpg", ".jpeg", ".pdf", ".woff2", ".ico", ".pyc"}

IP = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
EMAIL = re.compile(r"[\w.+-]+@([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+)")
SECRETS = [
    re.compile(r"sk-[A-Za-z0-9_-]{16,}"),
    re.compile(r"ghp_[A-Za-z0-9]{20,}"),
    re.compile(r"AIza[0-9A-Za-z_-]{20,}"),
    re.compile(r"xox[baprs]-[0-9A-Za-z-]{10,}"),
    re.compile(r"BEGIN [A-Z ]*PRIVATE KEY"),
    re.compile(r"Bearer\s+[A-Za-z0-9._-]{20,}"),
    re.compile(r"\b[0-9a-f]{40,}\b"),
]
# Настоящая утечка — имя конкретного ключа, а не сам факт «ssh -i» с плейсхолдером.
SSH = re.compile(r"(/\.ssh/id_|/app/data/keys/[A-Za-z0-9]|\bid_ed25519\b|\bid_rsa\b)")
MONEY = re.compile(r"\d[\d\s.,]*\s*₽")

# Домены, которые в публичном репозитории безопасны: примеры из документации,
# тестовые зоны и сервисы самих поставщиков.
SAFE_EMAIL_DOMAINS = {
    "example.com",
    "example.ru",
    "example.org",
    "example.test",
    "test",
    "localhost",
    "evil.com",  # фикстура проверки «чужой хост», а не настоящий адрес
    "github.com",  # git@github.com:... — это SSH-адрес репозитория
    "id.yandex.ru",  # служебный адрес Яндекса
    # Домены почтовых провайдеров: в коде адаптера они значат «какой IMAP подставить»,
    # а не чей-то ящик. Конкретные личные адреса ловит денлист, а не шаблон.
    "yandex.ru",
    "gmail.com",
    "mail.ru",
    "narod.ru",
}
SAFE_IPS = {"127.0.0.1", "0.0.0.0"}  # noqa: S104 — это адреса, а не bind


def problems_in_text(text: str, deny_terms: list[str], *, skip_ssh: bool = False) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    lowered_terms = [(term.lower(), term) for term in deny_terms if term.strip()]
    for number, line in enumerate(text.splitlines(), start=1):
        for match in IP.finditer(line):
            if match.group(0) not in SAFE_IPS:
                found.append((number, f"IP-адрес {match.group(0)}"))
        for match in EMAIL.finditer(line):
            domain = match.group(1).lower().rstrip("-")
            if domain not in SAFE_EMAIL_DOMAINS:
                found.append((number, f"почтовый адрес на домене {domain}"))
        for pattern in SECRETS:
            if pattern.search(line):
                found.append((number, "похоже на токен или ключ"))
                break
        if not skip_ssh and SSH.search(line):
            found.append((number, "путь или имя SSH-ключа"))
        if MONEY.search(line):
            found.append((number, "сумма в рублях"))
        low = line.lower()
        for term, original in lowered_terms:
            if term in low:
                found.append((number, f"личное значение из денлиста: {original}"))
    return found


def tracked_files(root: Path) -> list[Path]:
    """Файлы репозитория: через git, если он есть, иначе обходом дерева."""
    try:
        output = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z"],
            capture_output=True,
            check=True,
        ).stdout.decode("utf-8")
        files = [root / name for name in output.split("\0") if name]
    except (OSError, subprocess.CalledProcessError):
        files = []
    if not files:
        files = [
            path
            for path in root.rglob("*")
            if path.is_file() and not any(part in SKIP_DIRS for part in path.parts)
        ]
    return [path for path in files if path.suffix.lower() not in SKIP_SUFFIXES]


def scan(root: Path, deny_terms: list[str]) -> dict[str, list[tuple[int, str]]]:
    problems: dict[str, list[tuple[int, str]]] = {}
    for path in tracked_files(root):
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        found = problems_in_text(text, deny_terms, skip_ssh=path.name == ".gitignore")
        if found:
            problems[str(path.relative_to(root))] = found
    return problems


def read_denylist(path: Path) -> list[str]:
    try:
        return [
            line.strip()
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
    except OSError:
        return []


def self_test() -> int:
    failures: list[str] = []
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)

        def write(name: str, text: str) -> None:
            target = root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")

        write(
            "clean.md",
            "Сайт: `--site https://example.ru`. Почта: user@example.com. Ключ: `<ключ сборщика>`.\n",
        )
        if problems_in_text((root / "clean.md").read_text(encoding="utf-8"), []):
            failures.append("положительный контроль не прошёл: чистый файл ругается")

        # Образцы собираются по частям: файл сканируется сам собой, и литерал
        # «IP» или «сумма ₽» в нём дал бы ложную находку на собственном тесте.
        fake_token = "sk-" + "a" * 24
        cases = [
            ("ip", "сервер " + ".".join(["10", "20", "30", "40"]) + ", порт 8080\n", []),
            ("email", "пиши на " + "boss" + "@" + "firma-ooo.ru\n", []),
            ("ssh", "ssh -i /root/.ssh/" + "id_" + "ed25519 root@host\n", []),
            ("token", f"TOKEN={fake_token}\n", []),
            ("money", "расход " + "247" + " 934" + " \u20bd за месяц\n", []),
            ("deny-domain", "смотри " + "site-" + "firma" + ".ru и всё\n", ["firma"]),
            ("deny-case", "ФИРМА заказчика\n", ["фирма"]),
        ]
        for name, text, terms in cases:
            write(f"{name}.md", text)
            if not problems_in_text(text, terms):
                failures.append(f"порча «{name}» не поймана")
        # Чистый адрес на example.* не должен срабатывать даже при включённом денлисте
        if problems_in_text("почта user@example.org", ["firma"]):
            failures.append("example.org ошибочно считается личным")

    if failures:
        for failure in failures:
            print(f"  провал самопроверки: {failure}", file=sys.stderr)
        return 2
    print(f"самопроверка check-private: ok ({len(cases)} негативных кейсов)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Нет ли личных данных в публичном репозитории")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--path", default=str(ROOT))
    parser.add_argument("--denylist", default=os.environ.get("EGGENT_PRIVATE_DENYLIST", str(DEFAULT_DENYLIST)))
    args = parser.parse_args()
    if args.self_test:
        return self_test()

    root = Path(args.path)
    deny_terms = read_denylist(Path(args.denylist))
    if not deny_terms:
        print(
            f"личные данные: денлист не найден ({args.denylist}) — проверены только общие шаблоны",
            file=sys.stderr,
        )
    problems = scan(root, deny_terms)
    if problems:
        total = sum(len(items) for items in problems.values())
        print(f"личные данные: {total} находок в {len(problems)} файлах", file=sys.stderr)
        for name in sorted(problems):
            for number, reason in problems[name]:
                print(f"  {name}:{number}: {reason}", file=sys.stderr)
        return 1
    print(f"личные данные: чисто (шаблоны + денлист: {len(deny_terms)} значений)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
