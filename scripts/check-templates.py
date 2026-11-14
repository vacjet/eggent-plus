#!/usr/bin/env python3
"""Проверка шаблонов проектов.

Что проверяется:

1. карточка `template.json`: обязательные поля, `id` совпадает с папкой, `project/` есть;
2. файлы проекта: `AGENTS.md`, `context.md`, `memory.md`, `check.sh` — и `check.sh` исполняемый;
3. папки, которые шаблон обещает, и скиллы/специалисты, которые он просит, существуют;
4. установка в пустой каталог проходит (тем же скриптом, что и у человека);
5. `check.sh` проекта зелёный на свежей установке — и **краснеет**, когда правило нарушено:
   отчёт без даты в имени, отчёт со ссылкой на отсутствующий срез, токен в файле.

    python3 scripts/check-templates.py              # все шаблоны
    python3 scripts/check-templates.py --self-test  # негативные кейсы самого валидатора

Коды: 0 — всё сходится, 1 — есть проблемы, 2 — ошибка запуска/самопроверки.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = ROOT / "templates"
BUNDLED = ROOT / "bundled-skills"
SKILLS = ROOT / "skills"
INSTALL = ROOT / "scripts" / "install-template.py"

REQUIRED_KEYS = ("id", "title", "summary", "project")
REQUIRED_FILES = ("AGENTS.md", "context.md", "memory.md", "check.sh")


class TemplateError(Exception):
    """Шаблон не проходит проверку."""


def problems_of(directory: Path) -> list[str]:
    """Все расхождения одного шаблона: пустой список значит «годен»."""
    problems: list[str] = []
    meta_path = directory / "template.json"
    if not meta_path.is_file():
        return [f"{directory.name}: нет template.json"]
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        return [f"{directory.name}: template.json не разбирается: {error}"]

    for key in REQUIRED_KEYS:
        if not meta.get(key):
            problems.append(f"{directory.name}: нет поля {key}")
    if meta.get("id") != directory.name:
        problems.append(f"{directory.name}: id {meta.get('id')!r} не совпадает с папкой")

    project = directory / "project"
    if not project.is_dir():
        return problems + [f"{directory.name}: нет папки project/"]
    for name in REQUIRED_FILES:
        if not (project / name).is_file():
            problems.append(f"{directory.name}: нет project/{name}")
    check = project / (meta.get("check") or "check.sh")
    if check.is_file() and not (check.stat().st_mode & 0o111):
        problems.append(f"{directory.name}: {check.name} не исполняемый")

    for folder in meta.get("folders") or []:
        if not (project / folder).is_dir():
            problems.append(f"{directory.name}: шаблон обещает папку {folder}, её нет")
    for name in meta.get("specialists") or []:
        if not (BUNDLED / name).is_dir():
            problems.append(f"{directory.name}: нет специалиста bundled-skills/{name}")
    for name in meta.get("skills") or []:
        if not (SKILLS / name).is_dir():
            problems.append(f"{directory.name}: нет скилла skills/{name}")
    return problems


def run(cmd: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)


def install_into(directory: Path, workspace: Path, project: str = "tpl-check") -> Path:
    data = workspace / "data"
    (data / "projects").mkdir(parents=True, exist_ok=True)
    result = run(
        [
            sys.executable,
            str(INSTALL),
            "--template",
            directory.name,
            "--project",
            project,
            "--data",
            str(data),
            "--templates",
            str(directory.parent),
        ]
    )
    if result.returncode != 0:
        raise TemplateError(f"{directory.name}: установка не прошла: {result.stderr.strip() or result.stdout.strip()}")
    return data / "projects" / project


def expect_failure(project: Path, what: str, mutate) -> None:
    """Ломает проект и требует, чтобы его check.sh это заметил."""
    mutate(project)
    result = run(["bash", "check.sh"], cwd=project)
    if result.returncode == 0:
        raise TemplateError(f"{project.name}: check.sh не заметил: {what}")


def verification_of(directory: Path, workspace: Path) -> None:
    """Установка в пустой каталог и проверка, которая умеет падать."""
    project = install_into(directory, workspace)
    fresh = run(["bash", "check.sh"], cwd=project)
    if fresh.returncode != 0:
        raise TemplateError(f"{directory.name}: check.sh красный на свежей установке: {fresh.stdout.strip()}")

    (project / "data" / "external" / "2026-01-01-site.json").write_text('{"pages": 3}\n', encoding="utf-8")

    def bad_name(target: Path) -> None:
        (target / "reports" / "отчёт.md").write_text("проверка\n", encoding="utf-8")

    expect_failure(project, "отчёт без даты", bad_name)
    (project / "reports" / "отчёт.md").unlink()

    def missing_slice(target: Path) -> None:
        (target / "reports" / "2026-01-02-итог.md").write_text(
            "смотрели data/external/2026-01-09-нет.json\n", encoding="utf-8"
        )

    expect_failure(project, "ссылка на отсутствующий срез", missing_slice)
    (project / "reports" / "2026-01-02-итог.md").unlink()

    def token(target: Path) -> None:
        (target / "notes" / "токен.md").write_text("YANDEX_SEO_TOKEN=abcdefghijkl\n", encoding="utf-8")

    expect_failure(project, "токен в проекте", token)
    (project / "notes" / "токен.md").unlink()

    good = run(["bash", "check.sh"], cwd=project)
    if good.returncode != 0:
        raise TemplateError(f"{directory.name}: после уборки check.sh остался красным: {good.stdout.strip()}")


def run_templates(names: list[str]) -> int:
    if not TEMPLATES.is_dir():
        print(f"нет каталога шаблонов: {TEMPLATES}", file=sys.stderr)
        return 2
    directories = sorted(p for p in TEMPLATES.iterdir() if p.is_dir())
    if names:
        directories = [p for p in directories if p.name in names]
    if not directories:
        print("шаблонов нет — проверять нечего", file=sys.stderr)
        return 1

    failed = 0
    for directory in directories:
        problems = problems_of(directory)
        if problems:
            failed += 1
            for problem in problems:
                print(f"FAIL: {problem}", file=sys.stderr)
            continue
        try:
            with tempfile.TemporaryDirectory(prefix="tpl-") as work:
                verification_of(directory, Path(work))
            print(f"ok: {directory.name} — формат, установка, проверка и её падения")
        except TemplateError as error:
            failed += 1
            print(f"FAIL: {error}", file=sys.stderr)
    return 1 if failed else 0


def self_test() -> int:
    """Валидатор обязан находить каждую ошибку шаблона, а не только «всё хорошо»."""
    failures = 0

    def meta_of(directory: Path) -> dict:
        """Карточка шаблона, который мы сами же и написали в этом тесте."""
        try:
            return json.loads((directory / "template.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def expect_problem(name: str, mutate, expected_text: str) -> None:
        nonlocal failures
        with tempfile.TemporaryDirectory(prefix="tpl-self-") as work:
            directory = Path(work) / "demo"
            directory.mkdir()
            (directory / "template.json").write_text(
                json.dumps(
                    {
                        "version": 1,
                        "id": "demo",
                        "title": "Демо",
                        "summary": "Проверка",
                        "project": {"description": "Демо", "memoryMode": "isolated"},
                        "folders": ["notes"],
                        "check": "check.sh",
                    }
                ),
                encoding="utf-8",
            )
            (directory / "project").mkdir()
            for required in REQUIRED_FILES:
                (directory / "project" / required).write_text("x\n", encoding="utf-8")
            (directory / "project" / "check.sh").chmod(0o755)
            (directory / "project" / "notes").mkdir()
            # Специалист-пустышка, чтобы правило про скиллы не срабатывало само.
            meta = meta_of(directory)
            meta["specialists"] = []
            meta["skills"] = []
            (directory / "template.json").write_text(json.dumps(meta), encoding="utf-8")

            mutate(directory)
            problems = problems_of(directory)
            if not any(expected_text in problem for problem in problems):
                failures_local = f"не поймал «{expected_text}», увидел: {problems}"
            else:
                failures_local = ""
        print(f"  {'FAIL' if failures_local else 'ok  '}  {name}{': ' + failures_local if failures_local else ''}")
        if failures_local:
            failures += 1

    def rename_id(directory: Path) -> None:
        meta = meta_of(directory)
        meta["id"] = "другой"
        (directory / "template.json").write_text(json.dumps(meta), encoding="utf-8")

    def drop_field(directory: Path) -> None:
        meta = meta_of(directory)
        del meta["summary"]
        (directory / "template.json").write_text(json.dumps(meta), encoding="utf-8")

    def drop_check(directory: Path) -> None:
        (directory / "project" / "check.sh").unlink()

    def not_executable(directory: Path) -> None:
        (directory / "project" / "check.sh").chmod(0o644)

    def missing_folder(directory: Path) -> None:
        try:
            shutil.rmtree(directory / "project" / "notes")
        except OSError:
            pass

    def missing_skill(directory: Path) -> None:
        meta = meta_of(directory)
        meta["specialists"] = ["нет-такого"]
        (directory / "template.json").write_text(json.dumps(meta), encoding="utf-8")

    def install_behaviour() -> int:
        """Установщик: недоделанная установка не оставляет мусора, готовая — не перезаписывается."""
        local = 0

        def case(name: str, ok: bool, detail: str = "") -> None:
            nonlocal local
            print(f"  {'ok  ' if ok else 'FAIL'}  {name}{': ' + detail if detail and not ok else ''}")
            if not ok:
                local += 1

        with tempfile.TemporaryDirectory(prefix="tpl-install-") as work:
            work_path = Path(work)
            broken = work_path / "broken"
            (broken / "project").mkdir(parents=True)
            (broken / "template.json").write_text(
                json.dumps({"id": "broken", "title": "Б", "summary": "б", "project": {"description": "б", "memoryMode": "isolated"}, "specialists": ["нет-такого"]}),
                encoding="utf-8",
            )
            for required in REQUIRED_FILES:
                (broken / "project" / required).write_text("x\n", encoding="utf-8")
            data = work_path / "data" / "projects"
            data.mkdir(parents=True)
            result = run([sys.executable, str(INSTALL), "--template", "broken", "--project", "left-over", "--data", str(work_path / "data"), "--templates", str(work_path)])
            case("недоделанная установка возвращает ошибку", result.returncode == 2, f"код {result.returncode}")
            case("недоделанная установка не оставляет каталог", not (data / "left-over").exists())

        with tempfile.TemporaryDirectory(prefix="tpl-install-ok-") as work:
            work_path = Path(work)
            good = work_path / "good"
            (good / "project").mkdir(parents=True)
            (good / "template.json").write_text(
                json.dumps({"id": "good", "title": "Г", "summary": "г", "project": {"description": "г", "memoryMode": "isolated"}, "folders": []}),
                encoding="utf-8",
            )
            for required in REQUIRED_FILES:
                (good / "project" / required).write_text("x\n", encoding="utf-8")
            (good / "project" / "check.sh").chmod(0o755)
            data_dir = work_path / "data"
            (data_dir / "projects").mkdir(parents=True)
            first = run([sys.executable, str(INSTALL), "--template", "good", "--project", "kept", "--data", str(data_dir), "--templates", str(work_path)])
            second = run([sys.executable, str(INSTALL), "--template", "good", "--project", "kept", "--data", str(data_dir), "--templates", str(work_path)])
            case("первая установка проходит", first.returncode == 0, first.stderr.strip())
            case("повторная установка не затирает проект", second.returncode == 1, f"код {second.returncode}")
        return local

    print("\nповедение установщика:\n")
    failures += install_behaviour()

    print("негативные кейсы валидатора:\n")
    expect_problem("id не совпадает с папкой", rename_id, "не совпадает с папкой")
    expect_problem("нет обязательного поля", drop_field, "нет поля summary")
    expect_problem("нет check.sh", drop_check, "нет project/check.sh")
    expect_problem("check.sh не исполняемый", not_executable, "не исполняемый")
    expect_problem("обещанной папки нет", missing_folder, "обещает папку notes")
    expect_problem("обещанного специалиста нет", missing_skill, "нет специалиста")
    print()
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Проверка шаблонов проектов")
    parser.add_argument("--self-test", action="store_true", help="негативные кейсы валидатора")
    parser.add_argument("--template", action="append", default=[], help="проверить только этот шаблон")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    return run_templates(args.template)


if __name__ == "__main__":
    raise SystemExit(main())
