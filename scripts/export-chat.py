#!/usr/bin/env python3
"""Выгружает чаты Eggent в Markdown и JSON — чтобы разговор можно было вынести.

    python3 scripts/export-chat.py --data /app/data --chat <id> --out ~/export
    python3 scripts/export-chat.py --data /app/data --project <id> --out ~/export
    python3 scripts/export-chat.py --data /app/data --all --out ~/export
    python3 scripts/export-chat.py --self-test

Зачем: чат хранится файлом в `data/chats/<id>.json`, но читать его человеку нечем, а «вынести
разговор» — обычная просьба. Здесь он превращается в Markdown (читать, отправить, положить в
архив) и в JSON (загрузить обратно в любой инструмент). Ничего не удаляется и не меняется:
источник открывается только на чтение.

Коды: 0 — выгружено, 1 — ничего не нашлось, 2 — ошибка запуска.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from datetime import datetime
from pathlib import Path

MAX_TEXT = 200_000


class ExportError(Exception):
    """Ошибка запуска: нет каталога данных или он не похож на данные Eggent."""


def read_chats(data_dir: Path) -> list[dict]:
    chats_dir = data_dir / "chats"
    if not chats_dir.is_dir():
        raise ExportError(f"нет каталога чатов: {chats_dir}")
    chats: list[dict] = []
    for path in sorted(chats_dir.glob("*.json")):
        try:
            chat = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(chat, dict) and isinstance(chat.get("messages"), list):
            chat.setdefault("id", path.stem)
            chats.append(chat)
    return chats


def slug(text: str, limit: int = 40) -> str:
    cleaned = re.sub(r"[^\w\s-]", "", (text or "").lower(), flags=re.UNICODE)
    cleaned = re.sub(r"[\s_-]+", "-", cleaned).strip("-")
    return (cleaned[:limit] or "chat").strip("-")


def day_of(chat: dict) -> str:
    for key in ("createdAt", "updatedAt"):
        value = chat.get(key)
        if isinstance(value, str) and len(value) >= 10:
            return value[:10]
    return "undated"


def parts_text(message: dict) -> list[str]:
    """Строки одного сообщения: текст как есть, инструменты — одной строкой."""
    lines: list[str] = []
    content = message.get("content")
    if isinstance(content, str) and content.strip():
        lines.append(content.strip())
    parts = message.get("parts")
    if isinstance(parts, list):
        for part in parts:
            if not isinstance(part, dict):
                continue
            kind = part.get("type")
            if kind == "text" and isinstance(part.get("text"), str) and part["text"].strip():
                text = part["text"].strip()
                if not lines or lines[-1] != text:
                    lines.append(text)
            elif kind == "tool" and isinstance(part.get("toolName"), str):
                status = part.get("status") or "done"
                lines.append(f"_(инструмент `{part['toolName']}`, {status})_")
    return lines


def to_markdown(chat: dict, exported_at: str) -> str:
    title = chat.get("title") or "Без названия"
    out: list[str] = [f"# {title}", ""]
    about = [f"Чат: `{chat.get('id')}`", f"Создан: {chat.get('createdAt') or '—'}", f"Изменён: {chat.get('updatedAt') or '—'}"]
    if chat.get("projectId"):
        about.append(f"Проект: `{chat['projectId']}`")
    if isinstance(chat.get("specialist"), dict):
        about.append(f"Специалист: {chat['specialist'].get('title')}")
    out.append("  \n".join(about))
    out += ["", f"_Выгружено {exported_at} из Eggent._", ""]

    for message in chat.get("messages") or []:
        if not isinstance(message, dict):
            continue
        role = message.get("role")
        if role == "tool":
            body = message.get("toolResult") or message.get("content")
            if isinstance(body, str) and body.strip():
                out += ["**Результат инструмента**", "", "```", body.strip()[:4000], "```", ""]
            continue
        who = "Вы" if role == "user" else "Eggent" if role == "assistant" else role
        stamp = message.get("createdAt")
        out.append(f"## {who}{f' · {stamp}' if stamp else ''}")
        out.append("")
        for line in parts_text(message):
            out.append(line)
            out.append("")
        files = message.get("files")
        if isinstance(files, list) and files:
            for group in files:
                for item in (group.get("items") or []) if isinstance(group, dict) else []:
                    if isinstance(item, dict) and isinstance(item.get("path"), str):
                        out.append(f"- файл: `{item['path']}`")
            out.append("")
    return "\n".join(out).rstrip() + "\n"


def export_one(chat: dict, out_dir: Path, written: list[Path]) -> None:
    stamped = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z")
    base = f"{day_of(chat)}-{slug(str(chat.get('title') or ''))}-{str(chat.get('id'))[:8]}"
    markdown_path = out_dir / f"{base}.md"
    json_path = out_dir / f"{base}.json"
    markdown = to_markdown(chat, stamped)
    if len(markdown) > MAX_TEXT:
        markdown = markdown[:MAX_TEXT] + "\n\n_Выгрузка обрезана: чат слишком длинный._\n"
    markdown_path.write_text(markdown, encoding="utf-8")
    json_path.write_text(json.dumps(chat, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    written += [markdown_path, json_path]


def self_test() -> int:
    failures = 0

    def case(name: str, ok: bool, detail: str = "") -> None:
        nonlocal failures
        print(f"  {'ok  ' if ok else 'FAIL'}  {name}{': ' + detail if detail and not ok else ''}")
        if not ok:
            failures += 1

    with tempfile.TemporaryDirectory(prefix="export-") as work:
        data = Path(work) / "data"
        (data / "chats").mkdir(parents=True)
        rich = {
            "id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            "title": "Проверка экспорта",
            "projectId": "demo",
            "createdAt": "2026-11-14T10:00:00.000Z",
            "updatedAt": "2026-11-14T10:05:00.000Z",
            "specialist": {"id": "seo", "title": "SEO", "by": "auto"},
            "messages": [
                {"id": "1", "role": "user", "content": "проверь сайт", "createdAt": "2026-11-14T10:00:00.000Z"},
                {
                    "id": "2",
                    "role": "assistant",
                    "parts": [
                        {"type": "text", "text": "смотрю данные"},
                        {"type": "tool", "toolName": "bash", "status": "done"},
                    ],
                    "files": [{"project": "demo", "items": [{"path": "reports/a.md", "size": 10}], "total": 1}],
                },
            ],
        }
        (data / "chats" / "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee.json").write_text(json.dumps(rich), encoding="utf-8")
        (data / "chats" / "broken.json").write_text("{ это не json", encoding="utf-8")
        (data / "chats" / "empty.json").write_text(json.dumps({"id": "empty", "messages": []}), encoding="utf-8")

        out = Path(work) / "out"
        out.mkdir()
        chats = read_chats(data)
        case("битый файл пропущен, остальные прочитаны", len(chats) == 2, str(len(chats)))

        written: list[Path] = []
        for chat in chats:
            export_one(chat, out, written)
        names = sorted(p.name for p in out.iterdir())
        case("на каждый чат — markdown и json", len(names) == 4, str(names))

        md = next(p for p in out.glob("*.md") if "проверка-экспорта" in p.name).read_text(encoding="utf-8")
        case("заголовок и текст в markdown", "# Проверка экспорта" in md and "проверь сайт" in md)
        case("инструмент отмечен строкой", "инструмент `bash`" in md)
        case("файл ответа назван", "`reports/a.md`" in md)
        case("специалист в шапке", "Специалист: SEO" in md)

        jpath = next(p for p in out.glob("*.json") if "проверка-экспорта" in p.name)
        try:
            back = json.loads(jpath.read_text(encoding="utf-8"))
            same = back["messages"][0]["content"] == "проверь сайт"
        except (OSError, json.JSONDecodeError, KeyError, IndexError):
            same = False
        case("json читается обратно", same)

        empty_md = next(p for p in out.glob("*.md") if "без-названия" in p.name or "chat-" in p.name).read_text(encoding="utf-8")
        case("чат без названия и даты не падает", "# Без названия" in empty_md and "undated" in "".join(p.name for p in out.iterdir()))

        case("нет каталога чатов — ошибка запуска", isinstance(_caught(lambda: read_chats(Path(work) / "nope")), ExportError))

    print(f"\nпровалов: {failures}")
    return 1 if failures else 0


def _caught(work):
    try:
        work()
    except Exception as error:  # noqa: BLE001 - тест сравнивает тип
        return error
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Выгрузка чатов Eggent в Markdown и JSON")
    parser.add_argument("--data", default="/app/data", help="каталог data экземпляра")
    parser.add_argument("--chat", default="", help="id чата")
    parser.add_argument("--project", default="", help="id проекта: все его чаты")
    parser.add_argument("--all", action="store_true", help="все чаты")
    parser.add_argument("--out", default=".", help="каталог для файлов")
    parser.add_argument("--self-test", action="store_true", help="негативные кейсы самого скрипта")
    args = parser.parse_args()

    if args.self_test:
        return self_test()
    if not (args.chat or args.project or args.all):
        print("укажи --chat, --project или --all", file=sys.stderr)
        return 2

    try:
        chats = read_chats(Path(args.data).expanduser().resolve())
    except ExportError as error:
        print(f"ошибка: {error}", file=sys.stderr)
        return 2

    chosen = [
        chat
        for chat in chats
        if (args.chat and chat.get("id") == args.chat)
        or (args.project and chat.get("projectId") == args.project)
        or args.all
    ]
    if not chosen:
        print("ничего не нашлось по этому отбору", file=sys.stderr)
        return 1

    out_dir = Path(args.out).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for chat in chosen:
        export_one(chat, out_dir, written)
    print(f"выгружено чатов: {len(chosen)}, файлов: {len(written)} → {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
