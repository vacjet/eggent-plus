"""Подтверждение отправки на чужой адрес.

Письмо «не себе» необратимо: отозвать его нельзя. Поэтому оно не уходит сразу, а превращается
в заявку с кодом: код отправляется на адрес владельца ящика, а адаптер **скрывает это письмо**
из своей выдачи, чтобы агент не мог прочитать код и подтвердить сам за человека. Человек видит код
в своей почтовой программе и говорит его агенту; агент подтверждает заявку.

Заявка живёт час. Всё хранится рядом с письмами в SQLite.
"""

from __future__ import annotations

import secrets
import sqlite3
import threading
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

APPROVAL_HEADER = "X-Eggent-Approval"
APPROVAL_SUBJECT = "Код подтверждения письма"
TTL_MINUTES = 60

SCHEMA = """
CREATE TABLE IF NOT EXISTS approvals (
  id TEXT PRIMARY KEY,
  code TEXT NOT NULL,
  to_json TEXT NOT NULL,
  subject TEXT NOT NULL,
  text TEXT NOT NULL,
  attachments_json TEXT NOT NULL,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  decided_at TEXT,
  decided_via TEXT
);
"""


def _now() -> datetime:
    return datetime.now(UTC)


class Approvals:
    def __init__(self, connection: sqlite3.Connection):
        self._connection = connection
        self._lock = threading.Lock()
        with self._lock:
            self._connection.executescript(SCHEMA)
            self._connection.commit()

    def create(self, *, to: list[str], subject: str, text: str, attachments: list[dict]) -> dict:
        import json

        approval_id = secrets.token_hex(8)
        code = f"{secrets.randbelow(900000) + 100000}"
        created = _now()
        expires = created + timedelta(minutes=TTL_MINUTES)
        with self._lock:
            self._connection.execute(
                "INSERT INTO approvals (id, code, to_json, subject, text, attachments_json, status, created_at, expires_at)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                (approval_id, code, json.dumps(to, ensure_ascii=False), subject, text, json.dumps(attachments), "pending", created.isoformat(), expires.isoformat()),
            )
            self._connection.commit()
        return {
            "id": approval_id,
            "code": code,
            "status": "pending",
            "to": to,
            "subject": subject,
            "text": text,
            "attachments": attachments,
            "expiresAt": expires.isoformat(),
            "createdAt": created.isoformat(),
        }

    def get(self, approval_id: str) -> dict | None:
        import json

        with self._lock:
            row = self._connection.execute("SELECT * FROM approvals WHERE id = ?", (approval_id,)).fetchone()
        if row is None:
            return None
        return {
            "id": row["id"],
            "code": row["code"],
            "to": json.loads(row["to_json"]),
            "subject": row["subject"],
            "text": row["text"],
            "attachments": json.loads(row["attachments_json"]),
            "status": row["status"],
            "createdAt": row["created_at"],
            "expiresAt": row["expires_at"],
        }

    def decide(self, approval_id: str, code: str) -> tuple[bool, str, dict | None]:
        """Сверить код. Возвращает (решено, причина, заявка)."""
        found = self.get(approval_id)
        if not found:
            return False, "No such request", None
        if found["status"] != "pending":
            return False, f"That request is already {found['status']}", found
        if _now() > datetime.fromisoformat(found["expiresAt"]):
            self._set_status(approval_id, "expired", "expired")
            return False, "That request has expired; send it again", found
        if not secrets.compare_digest(found["code"], str(code).strip()):
            return False, "That code does not match", found
        self._set_status(approval_id, "approved", "email")
        return True, "", found

    def reject(self, approval_id: str) -> None:
        self._set_status(approval_id, "rejected", "email")

    def _set_status(self, approval_id: str, status: str, via: str) -> None:
        with self._lock:
            self._connection.execute(
                "UPDATE approvals SET status = ?, decided_at = ?, decided_via = ? WHERE id = ?",
                (status, _now().isoformat(), via, approval_id),
            )
            self._connection.commit()

    def view(self, approval: dict) -> dict:
        """Форма, которую ждёт Eggent (`EmailRequestView`)."""
        return {
            "id": approval["id"],
            "to": approval["to"],
            "subject": approval["subject"],
            "status": approval["status"],
            "waitsIn": "email",
            "createdAt": approval["createdAt"],
            "expiresAt": approval["expiresAt"],
            "decidedVia": None,
            "error": None,
        }


def sends_code(account, approvals: Approvals, sender: Callable[[dict], dict]) -> Callable[[dict], str]:
    """Отправить код владельцу ящика тем же SMTP и вернуть подпись для скрытия письма."""

    def notify(approval: dict) -> str:
        body = {
            "to": [account.owner or account.address],
            "subject": f"{APPROVAL_SUBJECT} {approval['id']}",
            "text": (
                f"Агент просит отправить письмо на {', '.join(approval['to'])}.\n"
                f"Тема: {approval['subject']}\n\n"
                f"Код подтверждения: {approval['code']}\n\n"
                f"Если это ты — скажи агенту код. Если нет — не говори его никому.\n"
                f"Заявка действует до {approval['expiresAt']}.\n"
            ),
        }
        sender(body)
        return f"{APPROVAL_SUBJECT} {approval['id']}"

    return notify
