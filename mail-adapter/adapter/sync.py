"""Синхронизация ящика по IMAP.

Только чтение: `select(readonly=True)`, письмо помечается прочитанным в нашей копии, а не в ящике
человека. Пачки по 10 с переподключением — на Яндексе большая выборка рвёт соединение (проверено).

Что в счёт идёт: письма за `days` дней в папках из конфига. Каждое превращается в строку в SQLite;
повторный проход по тем же UID ничего не дублирует.
"""

from __future__ import annotations

import contextlib
import imaplib
import re
import threading
from datetime import UTC, datetime, timedelta

from .approval import APPROVAL_SUBJECT
from .config import Account
from .mime import parse_letter

BATCH = 10


LIST_RE = re.compile(r'^\((?P<flags>[^)]*)\)\s+(?:"(?P<delim>[^"]*)"|NIL)\s+(?P<name>.+)$')


def parse_list_line(raw) -> dict | None:
    """Строка LIST → {flags, name}. Имя бывает в кавычках и в модифицированном UTF-7."""
    line = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)
    match = LIST_RE.match(line.strip())
    if not match:
        return None
    name = match.group("name").strip()
    if name.startswith('"') and name.endswith('"'):
        name = name[1:-1]
    return {"flags": match.group("flags").lower(), "name": name}


def resolve_folder(client, wanted: str) -> str | None:
    """Настоящее имя папки: у Яндекса «Отправленные», а не Sent.

    Ищем по флагу IMAP (\\Sent, \\Inbox), потом по имени: так работает и у провайдеров,
    которые называют папки на своём языке.
    """
    status, boxes = client.list()
    if status != "OK" or not boxes:
        return None
    parsed = [item for item in (parse_list_line(raw) for raw in boxes) if item]
    key = wanted.strip().lower()
    flag = {"inbox": "\\inbox", "sent": "\\sent", "drafts": "\\drafts", "trash": "\\trash"}.get(key)

    if flag:
        for item in parsed:
            if flag in item["flags"]:
                return item["name"]
    for item in parsed:
        if item["name"].lower() == key:
            return item["name"]
    words = {
        "sent": ("sent", "отправленн"),
        "inbox": ("inbox", "входящие"),
    }.get(key, ())
    for item in parsed:
        name = item["name"].lower()
        if any(word in name for word in words):
            return item["name"]
    return None


def folder_kind(folder: str) -> str:
    name = folder.strip().lower()
    if name in ("inbox", "входящие"):
        return "inbox"
    if any(word in name for word in ("sent", "отправленн", "outbox")):
        return "sent"
    return "other"


def _connect(account: Account) -> imaplib.IMAP4:
    if account.imap_tls:
        client: imaplib.IMAP4 = imaplib.IMAP4_SSL(account.imap_host, account.imap_port)
    else:
        client = imaplib.IMAP4(account.imap_host, account.imap_port)
        client.starttls()
    client.login(account.username, account.password)
    return client


def _since(days: int) -> str:
    moment = datetime.now(UTC) - timedelta(days=days)
    return moment.strftime("%d-%b-%Y")


def sync_folder(account: Account, store, folder: str, days: int) -> dict:
    """Прочитать одну папку. Возвращает счётчики, а не бросает: ящик может быть недоступен."""
    kind = folder_kind(folder)
    added = 0
    seen = 0
    failed = 0

    client = _connect(account)
    try:
        actual = resolve_folder(client, folder)
        if not actual:
            return {"folder": folder, "added": 0, "failed": 1, "error": f"в ящике нет папки «{folder}»"}
        status, _ = client.select(actual, readonly=True)
        if status != "OK":
            return {"folder": folder, "added": 0, "failed": 1, "error": f"не открылась папка {actual}"}

        # `uid("search", None, …)`: None — это «без второго аргумента», именно так imaplib
        # и отправляет UID SEARCH. Пустая строка давала BAD на Яндексе.
        status, data = client.uid("search", None, f"(SINCE {_since(days)})")
        if status != "OK" or not data or not data[0]:
            return {"folder": folder, "added": 0, "failed": 0, "error": None}

        uids = data[0].split()
        for start in range(0, len(uids), BATCH):
            batch = uids[start:start + BATCH]
            for uid in batch:
                try:
                    status, payload = client.uid("fetch", uid, "(RFC822 FLAGS)")
                    if status != "OK" or not payload:
                        failed += 1
                        continue
                    raw = b""
                    flags = b""
                    for part in payload:
                        if isinstance(part, tuple):
                            raw += part[1]
                            if isinstance(part[0], bytes):
                                flags += part[0]
                    if not raw:
                        failed += 1
                        continue
                    seen += 1
                    letter = parse_letter(raw)
                    # Письмо с кодом подтверждения в нашу копию не попадает: иначе агент
                    # прочитал бы код и подтвердил отправку сам за человека.
                    if letter.subject.startswith(APPROVAL_SUBJECT):
                        continue
                    read = b"\\Seen" in flags
                    stored = store.add(
                        account=account.id,
                        folder=kind,
                        uid=int(uid),
                        direction="out" if kind == "sent" else "in",
                        letter=letter,
                        read=read,
                    )
                    if stored is not None:
                        added += 1
                except (imaplib.IMAP4.error, OSError, ValueError):
                    failed += 1
            # Пачка прочитана — соединение могло устареть, проверяем и при необходимости
            # переподключаемся, иначе следующие fetch'и падают все сразу.
            try:
                client.noop()
            except (imaplib.IMAP4.error, OSError):
                with contextlib.suppress(imaplib.IMAP4.error, OSError):
                    client.logout()
                client = _connect(account)
                client.select(actual, readonly=True)
                # После переподключения сервер заново объявляет возможности; без NOOP
                # следующая команда может упасть на CAPABILITY и записаться как fail.
                with contextlib.suppress(imaplib.IMAP4.error, OSError):
                    client.noop()
    finally:
        with contextlib.suppress(imaplib.IMAP4.error, OSError):
            client.logout()

    return {"folder": folder, "added": added, "seen": seen, "failed": failed, "error": None}


def sync_account(account: Account, store) -> dict:
    results = []
    for folder in account.folders:
        try:
            results.append(sync_folder(account, store, folder, account.days))
        except Exception as error:  # один ящик не должен останавливать остальные
            results.append({"folder": folder, "added": 0, "failed": 1, "error": str(error)})
    return {
        "account": account.id,
        "folders": results,
        "added": sum(item.get("added") or 0 for item in results),
        "failed": sum(item.get("failed") or 0 for item in results),
    }


def sync_all(accounts: list[Account], store) -> list[dict]:
    return [sync_account(account, store) for account in accounts]


def start_periodic_sync(accounts: list[Account], store, interval_seconds: int = 300) -> threading.Thread:
    """Фоновый проход: сразу после старта и потом по интервалу."""

    def loop() -> None:
        while True:
            try:
                for result in sync_all(accounts, store):
                    print(f"[mail-adapter] sync {result}", flush=True)
            except Exception as error:
                print(f"[mail-adapter] sync failed: {error}", flush=True)
            threading.Event().wait(interval_seconds)

    thread = threading.Thread(target=loop, name="mail-sync", daemon=True)
    thread.start()
    return thread
