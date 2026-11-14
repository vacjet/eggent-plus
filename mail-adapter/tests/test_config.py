"""Конфигурация ящиков: секрет не в json, права на файл пароля, разумные значения по умолчанию."""

import json
import os
import stat
import tempfile
import unittest
from pathlib import Path

from adapter.config import ConfigError, load_accounts


def write_config(directory: Path, accounts: list[dict]) -> None:
    (directory / "accounts.json").write_text(json.dumps({"accounts": accounts}), encoding="utf-8")


def write_secret(directory: Path, account_id: str, password: str, mode: int) -> None:
    secrets = directory / "secrets"
    secrets.mkdir(exist_ok=True)
    path = secrets / account_id
    path.write_text(password, encoding="utf-8")
    os.chmod(path, mode)


class ConfigTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_yandex_defaults_and_secret_file(self):
        write_config(self.dir, [{"id": "work", "address": "work@example.org"}])
        # imap.yandex.ru подставляется только для доменов Яндекса; здесь — общий вид.
        write_secret(self.dir, "work", "app-password", 0o600)
        accounts = load_accounts(self.dir)
        self.assertEqual(accounts[0].id, "work")
        self.assertEqual(accounts[0].address, "work@example.org")
        self.assertEqual(accounts[0].imap_host, "imap.example.org")
        self.assertEqual(accounts[0].folders, ["INBOX"])
        self.assertEqual(accounts[0].days, 30)

    def test_password_inside_json_is_refused(self):
        write_config(self.dir, [{"id": "work", "address": "mail@example.com", "password": "secret"}])
        with self.assertRaises(ConfigError) as caught:
            load_accounts(self.dir)
        self.assertIn("accounts.json", str(caught.exception))

    def test_world_readable_secret_is_refused(self):
        write_config(self.dir, [{"id": "work", "address": "mail@example.com"}])
        write_secret(self.dir, "work", "app-password", 0o644)
        with self.assertRaises(ConfigError) as caught:
            load_accounts(self.dir)
        self.assertIn("600", str(caught.exception))

    def test_missing_secret_names_the_file(self):
        write_config(self.dir, [{"id": "work", "address": "mail@example.com"}])
        with self.assertRaises(ConfigError) as caught:
            load_accounts(self.dir)
        self.assertIn("secrets/work", str(caught.exception))

    def test_duplicate_and_bad_ids_are_refused(self):
        write_config(self.dir, [{"id": "work", "address": "a@example.ru"}, {"id": "work", "address": "b@example.ru"}])
        write_secret(self.dir, "work", "x", 0o600)
        with self.assertRaises(ConfigError):
            load_accounts(self.dir)

        write_config(self.dir, [{"id": "Работа", "address": "a@example.ru"}])
        with self.assertRaises(ConfigError):
            load_accounts(self.dir)

    def test_bad_address_is_refused(self):
        write_config(self.dir, [{"id": "work", "address": "not-an-address"}])
        write_secret(self.dir, "work", "x", 0o600)
        with self.assertRaises(ConfigError):
            load_accounts(self.dir)

    def test_yandex_host_is_filled_in(self):
        write_config(self.dir, [{"id": "y", "address": "someone@yandex.ru"}])
        write_secret(self.dir, "y", "x", 0o600)
        self.assertEqual(load_accounts(self.dir)[0].imap_host, "imap.yandex.ru")


if __name__ == "__main__":
    unittest.main()
