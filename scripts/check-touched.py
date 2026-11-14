#!/usr/bin/env python3
"""Каждый файл, который трогает патч, обязан быть в `TOUCHED.md`.

Список в `TOUCHED.md` — единственное место, по которому видно цену обновления upstream: перед новым
тегом смотрят туда. Патч, тронувший файл вне таблицы, делает эту цену неизвестной, поэтому проверка
падает, а не печатает предупреждение.

    python3 scripts/check-touched.py
    python3 scripts/check-touched.py --self-test

Выход: 0 — все файлы перечислены, 1 — есть расхождения, 2 — нет файлов для проверки.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PATCHES = ROOT / "patches"
TOUCHED = ROOT / "TOUCHED.md"

FILE_LINE_RE = re.compile(r"^\+\+\+ b/(.+)$", re.M)


def patched_files(patch_text: str) -> list[str]:
    """Пути, которые меняет патч, без повторов и в порядке появления."""
    seen: list[str] = []
    for name in FILE_LINE_RE.findall(patch_text):
        name = name.strip()
        if name and name not in seen:
            seen.append(name)
    return seen


def mentioned_files(touched_text: str) -> set[str]:
    """Пути, упомянутые в таблице `TOUCHED.md` в обратных кавычках."""
    return {match.strip() for match in re.findall(r"`([^`]+)`", touched_text)}


def problems_for(patch_texts: dict[str, str], touched_text: str) -> list[str]:
    listed = mentioned_files(touched_text)
    problems: list[str] = []
    for patch_name, text in patch_texts.items():
        files = patched_files(text)
        if not files:
            problems.append(f"{patch_name}: патч не меняет ни одного файла (или это не git-патч)")
            continue
        for name in files:
            if name not in listed:
                problems.append(f"{patch_name}: файл {name} не указан в TOUCHED.md")
    return problems


def self_test() -> int:
    touched = """
| Файл upstream | Зачем | Патч |
|---|---|---|
| `src/i18n/locales.ts` | добавить ru | ru-locale |
| `src/i18n/messages.ru.ts` | перевод | ru-locale |
"""
    good_patch = """diff --git a/src/i18n/locales.ts b/src/i18n/locales.ts
--- a/src/i18n/locales.ts
+++ b/src/i18n/locales.ts
@@ -1 +1 @@
-x
+y
diff --git a/src/i18n/messages.ru.ts b/src/i18n/messages.ru.ts
--- /dev/null
+++ b/src/i18n/messages.ru.ts
@@ -0,0 +1 @@
+new
"""
    cases = [
        ("файл вне таблицы", {"0002-x.patch": good_patch.replace("src/i18n/locales.ts", "src/lib/secret.ts")}, "не указан"),
        ("два файла, один не указан", {"0001-y.patch": good_patch + "--- /dev/null\n+++ b/next.config.mjs\n@@ -0,0 +1 @@\n+x\n"}, "next.config.mjs"),
        ("пустой патч", {"0003-z.patch": "not a patch\n"}, "не меняет ни одного файла"),
    ]
    failures: list[str] = []
    if problems_for({"0001-good.patch": good_patch}, touched):
        failures.append(f"положительный контроль не прошёл: {problems_for({'0001-good.patch': good_patch}, touched)}")
    for title, patches, needle in cases:
        problems = problems_for(patches, touched)
        if not any(needle in problem for problem in problems):
            failures.append(f"порча «{title}» не поймана (ждали «{needle}»), получено {problems}")
    if failures:
        for failure in failures:
            print(f"  провал самопроверки: {failure}", file=sys.stderr)
        return 2
    print(f"самопроверка check-touched: ok ({len(cases)} негативных кейса)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Сверка патчей с TOUCHED.md")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--patches", default=str(PATCHES))
    parser.add_argument("--touched", default=str(TOUCHED))
    args = parser.parse_args()

    if args.self_test:
        return self_test()

    patch_dir = Path(args.patches)
    touched_path = Path(args.touched)
    if not touched_path.is_file():
        print(f"check-touched: нет {touched_path}", file=sys.stderr)
        return 2
    texts = {p.name: p.read_text(encoding="utf-8") for p in sorted(patch_dir.glob("*.patch"))}
    if not texts:
        print(f"check-touched: в {patch_dir} нет патчей", file=sys.stderr)
        return 2

    problems = problems_for(texts, touched_path.read_text(encoding="utf-8"))
    if problems:
        print(f"TOUCHED.md: {len(problems)} расхождений", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    total = sum(len(patched_files(text)) for text in texts.values())
    print(f"TOUCHED.md: ok ({len(texts)} патча, {total} файлов, все перечислены)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
