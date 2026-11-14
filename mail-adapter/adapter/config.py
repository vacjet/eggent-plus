"""Ящики и секреты.

Пароль не лежит в `accounts.json`: он либо в файле `secrets/<id>` с правами 600, либо в
переменной окружения `EGGENT_MAIL_PASSWORD_<ID>`. Это проверяется, а не считается соглашением:
если пароль нашёлся в конфиге или файл секрета открыт другим, адаптер отказывается стартовать
и говорит, что именно не так.
"""

from __future__ import annotations

import json
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path

ADDRESS_RE = re.compile(r"^[^\s@<>()\",;:\\\[\]]+@[^\s@<>()\",;:\\\[\]]+\.[^\s@<>()\",;:\\\[\]]+$")
PASSWORD_HINTS = ("password", "passwd", "secret", "token")


class ConfigError(Exception):
    """Конфигурация не годится; текст говорит, что править."""


@dataclass(frozen=True)
class Account:
    id: str
    address: str
    owner: str | None
    imap_host: str
    imap_port: int
    imap_tls: bool
    folders: list[str]
    days: int
    smtp_host: str
    smtp_port: int
    smtp_tls: bool
    username: str
    password: str
    display_name: str | None


def _read_password(account_dir: Path, account_id: str, raw: dict) -> str:
    for key in raw:
        if any(hint in key.lower() for hint in PASSWORD_HINTS):
            raise ConfigError(
                f"account {account_id}: секрет не хранится в accounts.json (найдено поле «{key}»); "
                f"положите пароль в {account_dir / 'secrets' / account_id} с правами 600"
            )
    env_name = f"EGGENT_MAIL_PASSWORD_{account_id.upper().replace('-', '_')}"
    if os.environ.get(env_name):
        return os.environ[env_name].strip()

    secret_path = account_dir / "secrets" / account_id
    if not secret_path.is_file():
        raise ConfigError(
            f"account {account_id}: нет пароля — нужен файл {secret_path} (права 600) или переменная {env_name}"
        )
    mode = stat.S_IMODE(secret_path.stat().st_mode)
    if mode & 0o077:
        raise ConfigError(
            f"account {account_id}: {secret_path} доступен другим (права {mode:o}); нужно 600"
        )
    password = secret_path.read_text(encoding="utf-8").strip()
    if not password:
        raise ConfigError(f"account {account_id}: файл пароля пуст")
    return password


def _require(raw: dict, key: str, account_id: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"account {account_id}: не задано поле «{key}»")
    return value.strip()


def load_accounts(account_dir: str | Path) -> list[Account]:
    account_dir = Path(account_dir)
    path = Path(os.environ.get("EGGENT_MAIL_ACCOUNTS") or account_dir / "accounts.json")
    if not path.is_file():
        raise ConfigError(f"нет файла ящиков {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ConfigError(f"{path}: не разбирается как JSON: {error}") from error

    entries = data.get("accounts") if isinstance(data, dict) else None
    if not isinstance(entries, list) or not entries:
        raise ConfigError(f"{path}: ожидался объект с непустым списком «accounts»")

    accounts: list[Account] = []
    seen: set[str] = set()
    for raw in entries:
        if not isinstance(raw, dict):
            raise ConfigError(f"{path}: каждая запись accounts — объект")
        account_id = _require(raw, "id", "<без id>")
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,31}", account_id):
            raise ConfigError(f"account {account_id}: id — латиница, цифры, «-» и «_», до 32 символов")
        if account_id in seen:
            raise ConfigError(f"account {account_id}: id повторяется")
        seen.add(account_id)

        address = _require(raw, "address", account_id).lower()
        if not ADDRESS_RE.match(address):
            raise ConfigError(f"account {account_id}: «{address}» не похоже на адрес")
        owner_raw = raw.get("owner")
        owner = owner_raw.strip().lower() if isinstance(owner_raw, str) and owner_raw.strip() else None
        if owner and not ADDRESS_RE.match(owner):
            raise ConfigError(f"account {account_id}: owner «{owner}» не похож на адрес")

        imap_raw = raw.get("imap")
        smtp_raw = raw.get("smtp")
        imap: dict = imap_raw if isinstance(imap_raw, dict) else {}
        smtp: dict = smtp_raw if isinstance(smtp_raw, dict) else {}
        folders_raw = raw.get("folders")
        folders = [str(item) for item in folders_raw] if isinstance(folders_raw, list) and folders_raw else ["INBOX"]

        accounts.append(
            Account(
                id=account_id,
                address=address,
                owner=owner,
                imap_host=str(imap.get("host") or _default_host(address)),
                imap_port=int(imap.get("port") or 993),
                imap_tls=bool(imap.get("tls", True)),
                folders=folders,
                days=max(1, min(365, int(raw.get("days") or 30))),
                smtp_host=str(smtp.get("host") or _default_host(address)),
                smtp_port=int(smtp.get("port") or 465),
                smtp_tls=bool(smtp.get("tls", True)),
                username=str(raw.get("username") or address),
                password=_read_password(account_dir, account_id, raw),
                display_name=(raw.get("name") or None),
            )
        )
    return accounts


def _default_host(address: str) -> str:
    """Ящик на известном провайдере не требует вписывать хосты руками."""
    domain = address.rsplit("@", 1)[-1].lower()
    known = {
        "yandex.ru": "imap.yandex.ru",
        "yandex.com": "imap.yandex.com",
        "ya.ru": "imap.yandex.ru",
        "narod.ru": "imap.yandex.ru",
        "gmail.com": "imap.gmail.com",
        "googlemail.com": "imap.gmail.com",
        "mail.ru": "imap.mail.ru",
        "bk.ru": "imap.mail.ru",
        "inbox.ru": "imap.mail.ru",
        "list.ru": "imap.mail.ru",
    }
    return known.get(domain, f"imap.{domain}")


def token() -> str:
    value = (os.environ.get("EGGENT_MAIL_ADAPTER_TOKEN") or "").strip()
    if len(value) < 16:
        raise ConfigError("EGGENT_MAIL_ADAPTER_TOKEN не задан или короче 16 символов")
    return value
