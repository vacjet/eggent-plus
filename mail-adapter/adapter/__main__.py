"""Точка входа: `python -m adapter` из каталога mail-adapter.

Переменные окружения:
    EGGENT_MAIL_ACCOUNTS   путь к accounts.json (иначе ./accounts.json)
    EGGENT_MAIL_DIR        каталог данных: секреты, база (иначе текущий)
    EGGENT_MAIL_DB         путь к SQLite (иначе <каталог>/letters.sqlite3)
    EGGENT_MAIL_ADAPTER_TOKEN  токен, который Eggent присылает в Authorization
    EGGENT_MAIL_PORT       порт HTTP (иначе 8787)
    EGGENT_MAIL_SYNC_SECONDS  интервал синхронизации (иначе 300)
"""

from __future__ import annotations

import os
import sys

from .api import MailAdapter, serve
from .approval import Approvals, sends_code
from .config import ConfigError, load_accounts, token
from .send import send_letter
from .store import Store, store_path
from .sync import start_periodic_sync, sync_all


def main() -> int:
    directory = os.environ.get("EGGENT_MAIL_DIR") or os.getcwd()
    try:
        accounts = load_accounts(directory)
        auth_token = token()
    except ConfigError as error:
        print(f"mail-adapter: {error}", file=sys.stderr)
        return 2

    store = Store(store_path(directory))
    primary = accounts[0]

    def send(body: dict) -> dict:
        # Отправляет тот ящик, чей адрес указан в «from»; по умолчанию первый.
        wanted = str(body.get("from") or "").strip().lower()
        account = next((item for item in accounts if item.address == wanted), primary)
        return send_letter(account, body)

    approvals = Approvals(store._connection)  # noqa: SLF001 — одно соединение на процесс

    adapter = MailAdapter(
        token=auth_token,
        store=store,
        address=primary.address,
        send=send,
        status_extra=lambda: {"accounts": [{"id": item.id, "address": item.address} for item in accounts]},
        approvals=approvals,
        notify=sends_code(primary, approvals, lambda body: send_letter(primary, body)),
        own_addresses=[item.address for item in accounts] + [item.owner for item in accounts if item.owner],
    )

    sync_all(accounts, store)
    start_periodic_sync(accounts, store, int(os.environ.get("EGGENT_MAIL_SYNC_SECONDS") or 300))

    port = int(os.environ.get("EGGENT_MAIL_PORT") or 8787)
    host = os.environ.get("EGGENT_MAIL_HOST") or "127.0.0.1"
    server = serve(adapter, host=host, port=port)
    print(f"mail-adapter: {primary.address} на http://{host}:{port}, ящиков {len(accounts)}", flush=True)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
