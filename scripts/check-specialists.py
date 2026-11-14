#!/usr/bin/env python3
"""Проверка каталога специалистов: `bundled-skills/<id>/SKILL.md` + `specialist.json`.

Каталог — это каталог встроенных скиллов Eggent: каждая папка внутри `bundled-skills`
становится карточкой на экране «Скиллы» и ставится в проект одной кнопкой. Поэтому
пакет обязан совпадать с тем, что читает runtime:

- имя папки = `name` из frontmatter (в нижнем регистре), только строчные буквы, цифры
  и дефисы — иначе карточка молча не появится;
- `description` не пустой (без него карточки нет);
- `title_ru` / `summary_ru` — подписи карточки по-русски, `card_order` — порядок в ряду.

`specialist.json` — наш слой поверх: что специалист умеет, какой сценарий считается
проверкой и какие подсказки лежат рядом.

    python3 scripts/check-specialists.py
    python3 scripts/check-specialists.py --self-test
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CATALOG = ROOT / "bundled-skills"

NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
REQUIRED_SPECIALIST_KEYS = ("version", "id", "title", "summary", "scenario", "prompts")
KNOWN_CARD_KEYS = {
    "name",
    "description",
    "title",
    "title_ru",
    "summary",
    "summary_ru",
    "card_order",
    "license",
    "compatibility",
    "requires_env",
    "launch_scope",
}
MAX_DESCRIPTION = 1024


def parse_frontmatter(text: str) -> tuple[dict | None, str | None]:
    """Заголовок SKILL.md построчно: `key: value`, кавычки не обязательны.

    Возвращает (поля, ошибка). Строгий YAML здесь не нужен: наш формат — плоские
    пары, а runtime всё равно читает его как YAML, поэтому значение с двоеточием
    должно быть в кавычках — это и проверяем.
    """
    normalized = text.lstrip("\ufeff").replace("\r\n", "\n")
    lines = normalized.split("\n")
    if not lines or lines[0].strip() != "---":
        return None, "нет заголовка: файл не начинается с `---`"
    end = None
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            end = index
            break
    if end is None:
        return None, "заголовок не закрыт строкой `---`"

    fields: dict[str, str] = {}
    for offset, line in enumerate(lines[1:end], start=2):
        if not line.strip() or line.strip().startswith("#"):
            continue
        if ":" not in line:
            return None, f"строка {offset}: ожидалось `ключ: значение`"
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        if not NAME_RE.match(key.replace("_", "-")):
            return None, f"строка {offset}: ключ `{key}` — только буквы, цифры, дефис"
        if value[:1] in ('"', "'"):
            if len(value) < 2 or value[-1] != value[0]:
                return None, f"строка {offset}: кавычка не закрыта"
            value = value[1:-1]
        elif ": " in value:
            return None, f"строка {offset}: двоеточие в значении — возьмите в кавычки"
        fields[key] = value
    return fields, None


def check_skill_md(package: Path) -> list[str]:
    problems: list[str] = []
    skill_file = package / "SKILL.md"
    if not skill_file.is_file():
        return ["нет SKILL.md — карточки в каталоге не будет"]
    try:
        text = skill_file.read_text(encoding="utf-8")
    except OSError as error:
        return [f"SKILL.md не читается: {error}"]

    fields, error = parse_frontmatter(text)
    if error:
        return [f"SKILL.md: {error}"]
    assert fields is not None

    name = fields.get("name", "").strip()
    if not name:
        problems.append("SKILL.md: нет `name` — runtime возьмёт имя папки, карточка может пропасть")
    else:
        if not NAME_RE.match(name):
            problems.append(f"SKILL.md: name `{name}` — только строчные буквы, цифры и дефисы")
        if len(name) > 64:
            problems.append("SKILL.md: name длиннее 64 символов")
        if name != package.name.lower():
            problems.append(f"SKILL.md: name `{name}` не совпадает с папкой `{package.name}` — карточка не появится")

    description = fields.get("description", "").strip()
    if not description:
        problems.append("SKILL.md: нет `description` — без него карточки нет")
    elif len(description) > MAX_DESCRIPTION:
        problems.append(f"SKILL.md: description длиннее {MAX_DESCRIPTION} символов — обрежется")

    if "title_ru" not in fields:
        problems.append("SKILL.md: нет `title_ru` — карточка будет называться латиницей")
    if "summary_ru" not in fields:
        problems.append("SKILL.md: нет `summary_ru` — подпись карточки будет английской")

    order = fields.get("card_order")
    if order is not None and not order.strip().lstrip("-").isdigit():
        problems.append(f"SKILL.md: card_order `{order}` — нужно целое число")

    unknown = sorted(set(fields) - KNOWN_CARD_KEYS)
    if unknown:
        problems.append(f"SKILL.md: неизвестные поля {', '.join(unknown)} — runtime их не читает")

    body = text.split("\n---", 1)[-1].strip()
    if len(body) < 200:
        problems.append("SKILL.md: тело короче 200 символов — специалист без инструкций")
    return problems


def check_specialist_json(package: Path) -> list[str]:
    problems: list[str] = []
    path = package / "specialist.json"
    if not path.is_file():
        return ["нет specialist.json — пакет не описан для каталога"]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return [f"specialist.json не разбирается: {error}"]
    if not isinstance(data, dict):
        return ["specialist.json: ожидался объект"]

    for key in REQUIRED_SPECIALIST_KEYS:
        if key not in data:
            problems.append(f"specialist.json: нет `{key}`")
    if problems:
        return problems

    if data["version"] != 1:
        problems.append(f"specialist.json: version {data['version']} — поддерживается 1")
    if str(data["id"]) != package.name.lower():
        problems.append(f"specialist.json: id `{data['id']}` не совпадает с папкой `{package.name}`")
    for key in ("title", "summary"):
        if not str(data.get(key, "")).strip():
            problems.append(f"specialist.json: пустой `{key}`")

    prompts = data.get("prompts")
    if not isinstance(prompts, dict) or not prompts:
        problems.append("specialist.json: `prompts` должен быть непустым объектом")
    else:
        for prompt_name, relative in prompts.items():
            if not str(relative).strip():
                problems.append(f"specialist.json: пустой путь подсказки `{prompt_name}`")
                continue
            target = package / str(relative)
            if not target.is_file():
                problems.append(f"specialist.json: нет файла подсказки `{relative}`")
            elif len(target.read_text(encoding="utf-8").strip()) < 40:
                problems.append(f"specialist.json: подсказка `{relative}` короче 40 символов")

    scenario = data.get("scenario")
    if not isinstance(scenario, dict):
        problems.append("specialist.json: `scenario` должен быть объектом")
    else:
        if not str(scenario.get("request", "")).strip():
            problems.append("specialist.json: в сценарии нет `request` — нечего проверять")
        expect = scenario.get("expect")
        if not isinstance(expect, list) or not expect:
            problems.append("specialist.json: в сценарии нет `expect` — приёмка не сформулирована")
        elif not all(str(item).strip() for item in expect):
            problems.append("specialist.json: в `expect` есть пустые пункты")

    skills = data.get("skills", [])
    if not isinstance(skills, list):
        problems.append("specialist.json: `skills` должен быть списком")
    return problems


def check_catalog(catalog: Path) -> tuple[dict[str, list[str]], list[str]]:
    problems: dict[str, list[str]] = {}
    if not catalog.is_dir():
        return problems, [f"нет каталога {catalog}"]
    packages = sorted(entry for entry in catalog.iterdir() if entry.is_dir())
    if not packages:
        return problems, [f"каталог {catalog} пуст — карточек не будет"]
    for package in packages:
        found = check_skill_md(package) + check_specialist_json(package)
        if found:
            problems[package.name] = found
    return problems, []


def _write_package(root: Path, name: str, *, skill: str, specialist: dict) -> None:
    package = root / name
    (package / "prompts").mkdir(parents=True, exist_ok=True)
    (package / "SKILL.md").write_text(skill, encoding="utf-8")
    (package / "prompts" / "audit.md").write_text(
        "Проверь сайт и покажи три правки с приоритетом; цифры — со ссылкой на файл данных.",
        encoding="utf-8",
    )
    (package / "specialist.json").write_text(json.dumps(specialist, ensure_ascii=False, indent=2), encoding="utf-8")


def _good_specialist(name: str = "seo") -> dict:
    return {
        "version": 1,
        "id": name,
        "title": "SEO-специалист",
        "summary": "Аудит сайта и индексации",
        "skills": ["external-sources"],
        "prompts": {"audit": "prompts/audit.md"},
        "scenario": {"request": "Проверь сайт", "expect": ["три правки с приоритетом"]},
    }


def _good_skill(name: str = "seo") -> str:
    body = "Порядок работы: читать данные, не выдумывать цифры, отвечать по делу." * 8
    return (
        "---\n"
        f"name: {name}\n"
        'description: "SEO-специалист: аудит сайта и индексации"\n'
        'title_ru: "SEO"\n'
        'summary_ru: "Что не индексируется и что править"\n'
        "card_order: 10\n"
        "---\n\n"
        f"{body}\n"
    )


def self_test() -> int:
    failures: list[str] = []
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        _write_package(root, "seo", skill=_good_skill(), specialist=_good_specialist())
        if check_skill_md(root / "seo") or check_specialist_json(root / "seo"):
            failures.append(f"положительный контроль не прошёл: {check_skill_md(root / 'seo') + check_specialist_json(root / 'seo')}")

        cases: list[tuple[str, Callable[[], object]]] = [
            ("имя не совпадает с папкой", lambda: _write_package(root, "seo", skill=_good_skill("other"), specialist=_good_specialist())),
            ("нет description", lambda: _write_package(root, "seo", skill=_good_skill().replace('description: "SEO-специалист: аудит сайта и индексации"\n', ""), specialist=_good_specialist())),
            ("заголовок не закрыт", lambda: _write_package(root, "seo", skill=_good_skill().replace("card_order: 10\n---", "card_order: 10"), specialist=_good_specialist())),
            ("битый specialist.json", lambda: (root / "seo" / "specialist.json").write_text("{не json", encoding="utf-8")),
            ("id не совпадает", lambda: _write_package(root, "seo", skill=_good_skill(), specialist={**_good_specialist(), "id": "ppc"})),
            ("нет подсказки", lambda: _write_package(root, "seo", skill=_good_skill(), specialist={**_good_specialist(), "prompts": {"audit": "prompts/none.md"}})),
            ("пустой сценарий", lambda: _write_package(root, "seo", skill=_good_skill(), specialist={**_good_specialist(), "scenario": {"request": "", "expect": []}})),
            ("card_order не число", lambda: _write_package(root, "seo", skill=_good_skill().replace("card_order: 10", "card_order: первый"), specialist=_good_specialist())),
            ("нет title_ru", lambda: _write_package(root, "seo", skill=_good_skill().replace('title_ru: "SEO"\n', ""), specialist=_good_specialist())),
            ("нет SKILL.md", lambda: (root / "seo" / "SKILL.md").unlink()),
        ]
        for title, breakage in cases:
            _write_package(root, "seo", skill=_good_skill(), specialist=_good_specialist())
            breakage()
            if not (check_skill_md(root / "seo") + check_specialist_json(root / "seo")):
                failures.append(f"порча «{title}» не поймана")
        # каталог без папок и с пустой папкой
        empty = root / "empty"
        empty.mkdir()
        if not check_catalog(empty)[1]:
            failures.append("пустой каталог не пойман")

    if failures:
        for failure in failures:
            print(f"  провал самопроверки: {failure}", file=sys.stderr)
        return 2
    print(f"самопроверка check-specialists: ok ({len(cases)} негативных кейсов)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Проверка каталога специалистов eggent-plus")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--path", default=str(CATALOG))
    args = parser.parse_args()
    if args.self_test:
        return self_test()

    problems, fatal = check_catalog(Path(args.path))
    if fatal:
        for problem in fatal:
            print(f"специалисты: {problem}", file=sys.stderr)
        return 1
    if problems:
        print(f"специалисты: {len(problems)} пакет(ов) с ошибками", file=sys.stderr)
        for name in sorted(problems):
            for problem in problems[name]:
                print(f"  {name}: {problem}", file=sys.stderr)
        return 1
    packages = sorted(entry.name for entry in Path(args.path).iterdir() if entry.is_dir())
    print(f"специалисты: ok ({len(packages)}: {', '.join(packages)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
