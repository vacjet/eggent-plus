#!/usr/bin/env python3
"""Проверка русской локали eggent-plus.

Сверяет `src/i18n/messages.ru.ts` с английским справочником `tests/i18n/en-reference.json`
(снимок ключей и подстановок с тега v0.8.0) и проверяет, что словарь намерений
`src/i18n/vocabulary.ts` и регистрация локали на месте.

    python3 scripts/check-i18n.py                  # обычная проверка
    python3 scripts/check-i18n.py --self-test      # негативные тесты самого валидатора
    python3 scripts/check-i18n.py --regen-reference upstream/src/i18n/messages.ts

Коды возврата: 0 — всё сходится, 1 — есть расхождения, 2 — ошибка запуска/самопроверки.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_REFERENCE = ROOT / "tests" / "i18n" / "en-reference.json"
DEFAULT_RU = ROOT / "upstream" / "src" / "i18n" / "messages.ru.ts"
DEFAULT_VOCABULARY = ROOT / "upstream" / "src" / "i18n" / "vocabulary.ts"
DEFAULT_LOCALES = ROOT / "upstream" / "src" / "i18n" / "locales.ts"
DEFAULT_MESSAGES = ROOT / "upstream" / "src" / "i18n" / "messages.ts"

ENTRY_RE = re.compile(r'^  "([^"]+)": (".*"),$')
PLACEHOLDER_RE = re.compile(r"\{([A-Za-z0-9_]+)\}")

# Значения, которые по-русски остаются латиницей: адреса, аббревиатуры, имена продуктов.
LATIN_OK_RE = re.compile(
    r"^(?:https?://|/|mailto:)[^\s]*$"
    r"|^(?:API|MCP|OAuth|IMAP|SMTP|IMAP\s*/\s*SMTP|JSON|HTML|CSS|JS|TS|CLI|URL|ID|AI|PDF|CSV|"
    r"Telegram|Eggent|Eggent Cloud|GitHub|Google|Docker|Linux|Windows|macOS)$"
)

# Значения, которые состоят из подстановок, версии или сокращения и переводятся не словами.
LATIN_ALLOWED_VALUES = {
    "Id",
    "ID",
    "v{n}",
    "v{from} → v{to}",
    "{minutes}:{seconds}",
    "{job} · {month} {day}",
}

# Минимум, без которого словарь намерений не может распознать русскую реплику.
REQUIRED_VOCAB = {
    "STOP_PHRASES": ["стоп", "хватит", "отмена"],
    "NEGATIONS": ["не", "не надо"],
    "AFFIRMATIVES": ["да", "ок"],
    "MEMORY_REQUEST_PHRASES": ["запомни"],
    "SCHEDULE_NOUNS": ["расписание"],
}


def parse_dictionary(text: str, origin: str) -> tuple[dict[str, str], list[str]]:
    """Разбирает словарь сообщений: возвращает {ключ: значение} и список проблем."""
    problems: list[str] = []
    values: dict[str, str] = {}
    seen: Counter[str] = Counter()
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip() or line.lstrip().startswith(("//", "*", "/**")):
            continue
        match = ENTRY_RE.match(line)
        if not match:
            if line.strip() in ("};", "{", "}") or line.strip().startswith(("export ", "import ")):
                continue
            problems.append(f"{origin}:{number}: строка не похожа на запись словаря: {line[:80]}")
            continue
        key, raw = match.group(1), match.group(2)
        seen[key] += 1
        try:
            values[key] = json.loads(raw)
        except json.JSONDecodeError as error:
            problems.append(f"{origin}:{number}: не разбирается значение ключа {key}: {error}")
    for key, count in seen.items():
        if count > 1:
            problems.append(f"{origin}: ключ {key} встречается {count} раза")
    return values, problems


def check_messages(reference: dict[str, dict], ru: dict[str, str]) -> list[str]:
    """Ключи, подстановки и непереведённые значения."""
    problems: list[str] = []
    ref_keys = list(reference)
    missing = [key for key in ref_keys if key not in ru]
    extra = [key for key in ru if key not in reference]
    if missing:
        problems.append(
            f"нет перевода для {len(missing)} ключей: " + ", ".join(missing[:10])
            + (" …" if len(missing) > 10 else "")
        )
    if extra:
        problems.append(
            f"лишние ключи, которых нет в английском словаре ({len(extra)}): "
            + ", ".join(extra[:10]) + (" …" if len(extra) > 10 else "")
        )
    placeholders = 0
    untranslated = 0
    for key, entry in reference.items():
        value = ru.get(key)
        if value is None:
            continue
        expected = Counter(entry["ph"])
        actual = Counter(PLACEHOLDER_RE.findall(value))
        if expected != actual:
            placeholders += 1
            problems.append(
                f"подстановки не совпадают у {key}: ожидались {sorted(expected)} "
                f"({', '.join(f'{k}×{v}' if v > 1 else k for k, v in sorted(expected.items()))}), "
                f"получены {sorted(actual)}"
            )
        if (
            not re.search(r"[А-Яа-яЁё]", value)
            and value.strip() not in LATIN_ALLOWED_VALUES
            and not LATIN_OK_RE.search(value.strip())
        ):
            untranslated += 1
            problems.append(f"значение не переведено у {key}: {value!r}")
    if not problems and ru:
        print(f"словарь: {len(ru)} ключей, подстановки совпадают, непереведённых нет")
    return problems


def extract_list(text: str, name: str) -> list[str] | None:
    match = re.search(rf"export const {name}[^=]*=\s*\[(.*?)\];", text, re.S)
    if not match:
        return None
    return re.findall(r'"((?:[^"\\]|\\.)*)"', match.group(1))


def extract_string(text: str, name: str) -> str | None:
    match = re.search(rf"export const {name}\s*=\s*\"((?:[^\"\\]|\\.)*)\"", text)
    return match.group(1) if match else None


def check_wiring(locales: str, messages: str, vocabulary: str, ru: dict[str, str]) -> list[str]:
    """Регистрация локали и словарь намерений."""
    problems: list[str] = []
    if not re.search(r'SUPPORTED_LOCALES\s*=\s*\[[^\]]*"ru"', locales):
        problems.append("locales.ts: «ru» не добавлен в SUPPORTED_LOCALES")
    if not re.search(r'DEFAULT_LOCALE[^=]*=\s*"ru"', locales):
        problems.append("locales.ts: DEFAULT_LOCALE не «ru» (для нашей сборки ожидается ru)")
    if not re.search(r'\{\s*value:\s*"ru"', locales):
        problems.append("locales.ts: в LOCALE_OPTIONS нет пункта с value \"ru\"")
    if not re.search(r"\bru:\s*ruMessages\b", messages):
        problems.append("messages.ts: русский словарь не зарегистрирован (нет `ru: ruMessages`)")
    if not re.search(r'from\s+"(?:\./messages\.ru|@/i18n/messages\.ru)"', messages):
        problems.append("messages.ts: нет импорта словаря (./messages.ru или @/i18n/messages.ru)")

    for name, required in REQUIRED_VOCAB.items():
        words = extract_list(vocabulary, name)
        if words is None:
            problems.append(f"vocabulary.ts: нет списка {name}")
            continue
        lowered = [word.lower() for word in words]
        for word in required:
            # Записи пишутся основами: «расписани» ловит «расписание» и «расписанию».
            if not any(word in entry or entry in word for entry in lowered):
                problems.append(f"vocabulary.ts: в {name} нет русского «{word}»")

    titles = extract_list(vocabulary, "DEFAULT_CHAT_TITLES") or []
    new_chat = ru.get("nav.newChat")
    if not new_chat:
        problems.append("messages.ru.ts: нет nav.newChat — нечем сверить DEFAULT_CHAT_TITLES")
    elif new_chat not in titles:
        problems.append(
            f"vocabulary.ts: DEFAULT_CHAT_TITLES не содержит названия нового чата «{new_chat}»"
        )

    alphabet = extract_string(vocabulary, "SLUG_EXTRA_CHARACTERS")
    if alphabet is None:
        problems.append("vocabulary.ts: отсутствует SLUG_EXTRA_CHARACTERS")
    elif not re.search(r"[а-я]", alphabet):
        problems.append("vocabulary.ts: SLUG_EXTRA_CHARACTERS не содержит русских букв")

    phrases = extract_list(vocabulary, "RELATIVE_DELAY_PATTERNS") or []
    if not any("мин" in p for p in phrases):
        problems.append("vocabulary.ts: RELATIVE_DELAY_PATTERNS не понимает «через N минут»")
    return problems


def build_reference(messages_path: Path) -> dict[str, dict]:
    text = messages_path.read_text(encoding="utf-8")
    start = text.find("const enMessages")
    end = text.find("} as const;", start)
    if start < 0 or end < 0:
        raise SystemExit(f"{messages_path}: не найден словарь enMessages")
    body = text[start:end]
    reference: dict[str, dict] = {}
    for line in body.splitlines():
        match = ENTRY_RE.match(line)
        if not match:
            continue
        key, raw = match.group(1), match.group(2)
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as error:
            raise SystemExit(f"{messages_path}: не разбирается значение {key}: {error}") from error
        reference[key] = {"en": value, "ph": sorted(PLACEHOLDER_RE.findall(value))}
    return reference


def load_reference(path: Path) -> dict[str, dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise SystemExit(f"{path}: справочник повреждён: {error}") from error


def run(args: argparse.Namespace) -> int:
    reference = load_reference(Path(args.reference))
    ru_values, problems = parse_dictionary(Path(args.ru).read_text(encoding="utf-8"), args.ru)
    problems += check_messages(reference, ru_values)
    problems += check_wiring(
        Path(args.locales).read_text(encoding="utf-8"),
        Path(args.messages).read_text(encoding="utf-8"),
        Path(args.vocabulary).read_text(encoding="utf-8"),
        ru_values,
    )
    if problems:
        print(f"русская локаль: {len(problems)} расхождений", file=sys.stderr)
        for problem in problems[:60]:
            print(f"  - {problem}", file=sys.stderr)
        if len(problems) > 60:
            print(f"  … ещё {len(problems) - 60}", file=sys.stderr)
        return 1
    print("русская локаль: ok")
    return 0


# --- самопроверка: каждый пункт обязан уметь падать ---------------------------


def self_test() -> int:
    reference = {
        "nav.newChat": {"en": "New Chat", "ph": []},
        "schedules.rowActions": {"en": "Actions for {name}", "ph": ["name"]},
        "files.count": {"en": "{count} files", "ph": ["count"]},
    }
    good = {
        "nav.newChat": "Новый чат",
        "schedules.rowActions": "Действия: {name}",
        "files.count": "Файлов: {count}",
    }
    cases: list[tuple[str, dict[str, str], str]] = [
        ("пропущен ключ", {k: v for k, v in good.items() if k != "files.count"}, "нет перевода"),
        ("лишний ключ", {**good, "nav.extra": "Лишний"}, "лишние ключи"),
        (
            "потеряна подстановка",
            {**good, "files.count": "Файлы"},
            "подстановки не совпадают",
        ),
        (
            "переименована подстановка",
            {**good, "files.count": "Файлов: {total}"},
            "подстановки не совпадают",
        ),
        ("значение не переведено", {**good, "nav.newChat": "New Chat"}, "не переведено"),
        (
            "повтор ключа в файле",
            good,
            "встречается",
        ),
    ]

    vocabulary = """
export const STOP_PHRASES = ["стоп", "хватит", "отмена"];
export const NEGATIONS = ["не", "не надо"];
export const AFFIRMATIVES = ["да", "ок"];
export const MEMORY_REQUEST_PHRASES = ["запомни"];
export const SCHEDULE_NOUNS = ["расписание"];
export const DEFAULT_CHAT_TITLES = ["Новый чат"];
export const RELATIVE_DELAY_PATTERNS = ["через\\\\s+\\\\d+\\\\s+мин"];
export const SLUG_EXTRA_CHARACTERS = "абвгдеёжзийклмнопрстуфхцчшщъыьэюя";
"""
    locales = """
export const SUPPORTED_LOCALES = ["en", "ru"] as const;
export const DEFAULT_LOCALE: SupportedLocale = "ru";
export const LOCALE_OPTIONS = [{ value: "ru", label: "Русский" }];
"""
    messages_ts = 'import { ruMessages } from "./messages.ru";\nconst x = { en: enMessages, ru: ruMessages };\n'

    failures: list[str] = []
    base = check_messages(reference, good)
    if base:
        failures.append("положительный контроль словаря не прошёл: " + "; ".join(base))
    base = check_wiring(locales, messages_ts, vocabulary, good)
    if base:
        failures.append("положительный контроль обвязки не прошёл: " + "; ".join(base))

    for title, ru, needle in cases:
        problems = check_messages(reference, ru)
        if title == "повтор ключа в файле":
            text = "export const ruMessages = {\n" + "\n".join(
                f'  "{key}": "{value}",' for key, value in ru.items()
            ) + f'\n  "nav.newChat": "{ru["nav.newChat"]}",\n}};\n'
            _, problems = parse_dictionary(text, "<self-test>")
        if not any(needle in problem for problem in problems):
            failures.append(f"правка «{title}» не поймана (ожидалось «{needle}»), получено {problems}")

    broken_wiring = [
        ("locale без ru", locales.replace('"en", "ru"', '"en"')),
        ("DEFAULT_LOCALE не ru", locales.replace('= "ru"', '= "en"')),
        ("нет пункта LOCALE_OPTIONS", locales.replace('{ value: "ru", label: "Русский" }', '')),
        ("нет ru: ruMessages", messages_ts.replace("ru: ruMessages", "")),
        ("нет импорта messages.ru", messages_ts.replace('import { ruMessages } from "./messages.ru";', "")),
        ("нет стоп-слов", vocabulary.replace('["стоп", "хватит", "отмена"]', "[]")),
        ("нет отрицаний", vocabulary.replace('["не", "не надо"]', "[]")),
        ("нет названия нового чата", vocabulary.replace('["Новый чат"]', '["New Chat"]')),
        ("нет русских букв для slug", vocabulary.replace('"абвгдеёжзийклмнопрстуфхцчшщъыьэюя"', '""')),
        ("нет шаблона «через N минут»", vocabulary.replace('["через\\\\s+\\\\d+\\\\s+мин"]', "[]")),
    ]
    for title, broken in broken_wiring:
        parts = broken.split("\n")
        problems = check_wiring(parts[0], parts[1] if len(parts) > 1 else messages_ts,
                                "\n".join(parts[2:]) if len(parts) > 2 else vocabulary, good)
        if not problems:
            failures.append(f"порча «{title}» не поймана")

    if failures:
        for failure in failures:
            print(f"  провал самопроверки: {failure}", file=sys.stderr)
        return 2
    print(f"самопроверка check-i18n: ok (6 кейсов словаря + {len(broken_wiring)} кейсов обвязки)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Проверка русской локали eggent-plus")
    parser.add_argument("--reference", default=str(DEFAULT_REFERENCE))
    parser.add_argument("--ru", default=str(DEFAULT_RU))
    parser.add_argument("--vocabulary", default=str(DEFAULT_VOCABULARY))
    parser.add_argument("--locales", default=str(DEFAULT_LOCALES))
    parser.add_argument("--messages", default=str(DEFAULT_MESSAGES))
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--regen-reference", metavar="MESSAGES_TS")
    args = parser.parse_args()

    if args.regen_reference:
        reference = build_reference(Path(args.regen_reference))
        DEFAULT_REFERENCE.write_text(
            json.dumps(reference, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
        )
        print(f"справочник обновлён: {DEFAULT_REFERENCE} ({len(reference)} ключей)")
        return 0
    if args.self_test:
        return self_test()
    return run(args)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except FileNotFoundError as error:
        print(f"check-i18n: нет файла {error.filename}", file=sys.stderr)
        sys.exit(2)
