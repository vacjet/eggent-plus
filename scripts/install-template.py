#!/usr/bin/env python3
"""Ставит шаблон проекта в данные экземпляра.

    python3 scripts/install-template.py --template seo --project my-site
    python3 scripts/install-template.py --template seo --project my-site --data /root/testdata-55
    python3 scripts/install-template.py --template seo --project my-site --name "Мой сайт" --owner 1000:1000

Что делает:

1. читает `templates/<id>/template.json` (карточка шаблона);
2. копирует `templates/<id>/project/` в `<data>/projects/<project>/`, подставляя переменные
   (`{{site}}` и остальные из `template.json`);
3. пишет `project.json` — карточку проекта, которую видит панель Eggent;
4. ставит в проект специалиста из `bundled-skills/` и скиллы из `skills/`, перечисленные в шаблоне;
5. выставляет `check.sh` исполняемым и, если попросили, владельца (в контейнере это 1000:1000 —
   каталог должен быть доступен приложению на запись).

Коды возврата: 0 — поставлено, 1 — каталог проекта уже не пуст (нужен `--force`), 2 — ошибка
запуска: нет шаблона, нет данных, неправильный `template.json`.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = ROOT / "templates"
BUNDLED = ROOT / "bundled-skills"
SKILLS = ROOT / "skills"

REQUIRED_KEYS = ("id", "title", "summary", "project")


class InstallError(Exception):
    """Ошибка запуска, а не состояния проекта: печатаем и выходим с кодом 2."""


def load_template(template_id: str, templates_root: Path | None = None) -> tuple[Path, dict]:
    directory = (templates_root or TEMPLATES) / template_id
    meta_path = directory / "template.json"
    if not meta_path.is_file():
        raise InstallError(f"нет шаблона {template_id}: {meta_path}")
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise InstallError(f"template.json не разбирается: {error}") from error
    missing = [key for key in REQUIRED_KEYS if not meta.get(key)]
    if missing:
        raise InstallError(f"в template.json нет полей: {', '.join(missing)}")
    if meta["id"] != template_id:
        raise InstallError(f"id шаблона {meta['id']!r} не совпадает с папкой {template_id!r}")
    if not (directory / "project").is_dir():
        raise InstallError(f"в шаблоне {template_id} нет папки project/")
    return directory, meta


def substitute(text: str, variables: dict[str, str]) -> str:
    for key, value in variables.items():
        text = text.replace("{{" + key + "}}", str(value))
    return text


def copy_tree(source: Path, target: Path, variables: dict[str, str]) -> None:
    for item in sorted(source.rglob("*")):
        relative = item.relative_to(source)
        destination = target / relative
        if item.is_dir():
            destination.mkdir(parents=True, exist_ok=True)
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        if item.name.endswith((".md", ".txt", ".json", ".sh", ".py")):
            destination.write_text(substitute(item.read_text(encoding="utf-8"), variables), encoding="utf-8")
        else:
            shutil.copy2(item, destination)


def install(args: argparse.Namespace) -> int:
    template_dir, meta = load_template(args.template, Path(args.templates).resolve() if args.templates else None)
    data_dir = Path(args.data).expanduser().resolve()
    if not data_dir.is_dir():
        raise InstallError(f"нет каталога данных экземпляра: {data_dir}")

    project_dir = data_dir / "projects" / args.project
    if project_dir.exists() and any(project_dir.iterdir()) and not args.force:
        print(f"каталог проекта уже не пуст: {project_dir} (--force, чтобы дополнить)", file=sys.stderr)
        return 1

    variables = {key: str(value) for key, value in (meta.get("variables") or {}).items()}

    # Всё, что шаблон просит, проверяется до первой записи: иначе неудачная установка
    # оставляет полупустой проект, который ещё и принадлежит не тому пользователю.
    for name in meta.get("specialists") or []:
        if not (BUNDLED / name).is_dir():
            raise InstallError(f"шаблон просит специалиста {name}, а его нет в bundled-skills/")
    for name in meta.get("skills") or []:
        if not (SKILLS / name).is_dir():
            raise InstallError(f"шаблон просит скилл {name}, а его нет в skills/")

    created = not project_dir.exists()
    try:
        copy_tree(template_dir / "project", project_dir, variables)
    except Exception:
        if created:
            shutil.rmtree(project_dir, ignore_errors=True)
        raise

    instructions = (project_dir / "AGENTS.md").read_text(encoding="utf-8") if (project_dir / "AGENTS.md").is_file() else ""
    now = datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
    project_meta = (meta.get("project") or {})
    card = {
        "id": args.project,
        "name": args.name or meta["title"],
        "description": project_meta.get("description") or meta["summary"],
        "instructions": instructions,
        "memoryMode": project_meta.get("memoryMode") or "isolated",
        "createdAt": now,
        "updatedAt": now,
    }
    (project_dir / "project.json").write_text(json.dumps(card, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    installed_skills: list[str] = []
    try:
        for name in meta.get("specialists") or []:
            shutil.copytree(BUNDLED / name, project_dir / "skills" / name)
            installed_skills.append(name)
        for name in meta.get("skills") or []:
            destination = project_dir / "skills" / name
            if destination.exists():
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(SKILLS / name, destination, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            installed_skills.append(name)
    except Exception:
        if created:
            shutil.rmtree(project_dir, ignore_errors=True)
        raise

    check = project_dir / (meta.get("check") or "check.sh")
    if check.is_file():
        check.chmod(0o755)

    if args.owner:
        uid_text, _, gid_text = args.owner.partition(":")
        uid = int(uid_text)
        gid = int(gid_text or uid_text)
        for path in [project_dir, *project_dir.rglob("*")]:
            os.chown(path, uid, gid)

    print(f"проект {args.project} поставлен из шаблона {args.template}: {project_dir}")
    print(f"  файлов: {sum(1 for p in project_dir.rglob('*') if p.is_file())}, скиллов: {', '.join(installed_skills) or 'нет'}")
    print("  дальше: открыть проект в панели и запустить ./check.sh внутри него")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Поставить шаблон проекта в данные экземпляра")
    parser.add_argument("--template", required=True, help="id шаблона из templates/")
    parser.add_argument("--project", required=True, help="id проекта (папка в data/projects/)")
    parser.add_argument("--data", default="/app/data", help="каталог data экземпляра (по умолчанию /app/data)")
    parser.add_argument("--templates", default="", help="каталог шаблонов (по умолчанию templates/ репозитория)")
    parser.add_argument("--name", default="", help="имя проекта в панели (по умолчанию из шаблона)")
    parser.add_argument("--owner", default="", help="владелец файлов, например 1000:1000")
    parser.add_argument("--force", action="store_true", help="дополнить непустой каталог проекта")
    args = parser.parse_args()
    try:
        return install(args)
    except InstallError as error:
        print(f"ошибка: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
