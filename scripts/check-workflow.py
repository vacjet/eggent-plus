#!/usr/bin/env python3
"""Проверка CI-файла `.github/workflows/patches.yml`.

Файл ещё не запускался на GitHub (репозиторий не опубликован), поэтому проверяем то, что можно
проверить локально: это валидный YAML, в нём есть шаги «Apply patches» и «Build», задан тег
upstream, и порядок шагов такой, что патчи ложатся до сборки.

    python3 scripts/check-workflow.py
    python3 scripts/check-workflow.py --self-test

Выход: 0 — всё на месте, 1 — расхождения, 2 — файла нет или он не разбирается.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github" / "workflows" / "patches.yml"


def problems_for(workflow: object) -> list[str]:
    problems: list[str] = []
    if not isinstance(workflow, dict):
        return ["workflow не разбирается в словарь"]
    jobs = workflow.get("jobs")
    if not isinstance(jobs, dict) or not jobs:
        return ["в workflow нет ни одной job"]
    # PyYAML читает `on:` как булево True (YAML 1.1), GitHub — как строку (YAML 1.2).
    trigger = workflow.get("on") if workflow.get("on") is not None else workflow.get(True)
    if not isinstance(trigger, dict) or "push" not in trigger:
        problems.append("workflow не запускается на push")
    tag = str((workflow.get("env") or {}).get("UPSTREAM_TAG", ""))
    if not tag.startswith("v"):
        problems.append("UPSTREAM_TAG не задан (без него CI соберёт не тот тег)")

    steps: list[str] = []
    for job in jobs.values():
        for step in (job or {}).get("steps") or []:
            steps.append(str(step.get("name") or step.get("uses") or "").lower())
    joined = " | ".join(steps)
    for needed in ("apply patches", "build"):
        if needed not in joined:
            problems.append(f"нет шага «{needed}»")
    if "apply patches" in joined and "build" in joined \
            and steps.index("apply patches") > steps.index("build"):
        problems.append("шаг «Build» стоит раньше «Apply patches»")

    text = "\n".join(
        str(step.get("run", ""))
        for job in jobs.values()
        for step in (job or {}).get("steps") or []
    )
    if "apply --check" not in text:
        problems.append("патчи применяются без `git apply --check` — битый патч не будет виден")
    if "npm run build" not in text:
        problems.append("нет `npm run build` — сборка не проверяется")

    # Node: на раннере по умолчанию 20-й, а тесты upstream вызывают
    # --experimental-strip-types (с 22.6). Без setup-node сборка падает не из-за кода.
    version = node_version(workflow)
    if version is None:
        problems.append("нет шага actions/setup-node — на раннере будет Node 20")
    elif not node_is_recent(version):
        problems.append(f"Node {version} старше 22: --experimental-strip-types не поддерживается")
    return problems


def node_version(workflow: object):
    """`node-version` из первого шага setup-node или None."""
    for job in ((workflow or {}).get("jobs") or {}).values():
        for step in (job or {}).get("steps") or []:
            if str(step.get("uses", "")).startswith("actions/setup-node"):
                return str((step.get("with") or {}).get("node-version") or "") or None
    return None


def node_is_recent(version: str) -> bool:
    """`22`, `22.x`, `22.6.0` — да; `20`, `18.x` — нет; `latest` — да."""
    text = version.strip().lower()
    if text in ("latest", "lts/*"):
        return True
    digits = ""
    for character in text:
        if character.isdigit():
            digits += character
        else:
            break
    return bool(digits) and int(digits) >= 22


def self_test() -> int:
    good = {
        "on": {"push": None},
        "env": {"UPSTREAM_TAG": "v0.8.0"},
        "jobs": {
            "build": {
                "steps": [
                    {"name": "Node 22", "uses": "actions/setup-node@v4", "with": {"node-version": "22"}},
                    {"name": "Apply patches", "run": "git -C upstream apply --check p"},
                    {"name": "Build", "run": "npm run build"},
                ]
            }
        },
    }
    failures: list[str] = []
    if problems_for(good):
        failures.append(f"положительный контроль не прошёл: {problems_for(good)}")

    broken = {
        "нет тега": {**good, "env": {}},
        "нет push": {**good, "on": {"workflow_dispatch": None}},
        "нет build": {**good, "jobs": {"build": {"steps": [{"name": "Apply patches", "run": "git apply --check"}]}}},
        "build раньше apply": {
            **good,
            "jobs": {
                "build": {
                    "steps": [
                        {"name": "Build", "run": "npm run build"},
                        {"name": "Apply patches", "run": "git apply --check p"},
                    ]
                }
            },
        },
        "без setup-node": {
            **good,
            "jobs": {
                "build": {
                    "steps": [
                        {"name": "Apply patches", "run": "git apply --check p"},
                        {"name": "Build", "run": "npm run build"},
                    ]
                }
            },
        },
        "Node 20": {
            **good,
            "jobs": {
                "build": {
                    "steps": [
                        {"name": "Node", "uses": "actions/setup-node@v4", "with": {"node-version": "20"}},
                        {"name": "Apply patches", "run": "git apply --check p"},
                        {"name": "Build", "run": "npm run build"},
                    ]
                }
            },
        },
        "без apply --check": {
            **good,
            "jobs": {
                "build": {
                    "steps": [
                        {"name": "Apply patches", "run": "git apply p"},
                        {"name": "Build", "run": "npm run build"},
                    ]
                }
            },
        },
    }
    for title, workflow in broken.items():
        if not problems_for(workflow):
            failures.append(f"порча «{title}» не поймана")

    if failures:
        for failure in failures:
            print(f"  провал самопроверки: {failure}", file=sys.stderr)
        return 2
    print(f"самопроверка check-workflow: ok ({len(broken)} негативных кейсов)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Проверка CI-файла eggent-plus")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--path", default=str(WORKFLOW))
    args = parser.parse_args()
    if args.self_test:
        return self_test()

    try:
        import yaml
    except ImportError:
        print("check-workflow: нет PyYAML (pip install pyyaml)", file=sys.stderr)
        return 2

    path = Path(args.path)
    if not path.is_file():
        print(f"check-workflow: нет файла {path}", file=sys.stderr)
        return 2
    try:
        workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as error:
        print(f"check-workflow: YAML не разбирается: {error}", file=sys.stderr)
        return 2

    problems = problems_for(workflow)
    if problems:
        print(f"CI-файл: {len(problems)} расхождений", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    jobs = ", ".join(workflow["jobs"])
    print(f"CI-файл: ok (jobs: {jobs}, тег {workflow['env']['UPSTREAM_TAG']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
