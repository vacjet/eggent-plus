"""Хранилище писем: SQLite рядом с конфигом.

Своя копия нужна по двум причинам: у IMAP нет сквозного числового id (у каждого ящика свой UID),
а Eggent ждёт именно число и курсор `after`; и второе — письмо не должно исчезать из списка,
когда его убрали из ящика, пока агент ещё не прочитал.

Повторная синхронизация не создаёт дублей: ключ (ящик, папка, UID).
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  account TEXT NOT NULL,
  folder TEXT NOT NULL,
  uid INTEGER NOT NULL,
  direction TEXT NOT NULL,
  subject TEXT NOT NULL,
  preview TEXT NOT NULL,
  from_addr TEXT,
  from_name TEXT,
  to_json TEXT NOT NULL,
  at TEXT NOT NULL,
  read INTEGER NOT NULL DEFAULT 0,
  size INTEGER NOT NULL DEFAULT 0,
  text TEXT NOT NULL DEFAULT '',
  message_id TEXT,
  in_reply_to TEXT,
  spf_pass INTEGER NOT NULL DEFAULT 0,
  UNIQUE (account, folder, uid)
);
CREATE TABLE IF NOT EXISTS attachments (
  message_id INTEGER NOT NULL,
  n INTEGER NOT NULL,
  name TEXT NOT NULL,
  mime TEXT NOT NULL,
  size INTEGER NOT NULL,
  data BLOB NOT NULL,
  PRIMARY KEY (message_id, n)
);
CREATE INDEX IF NOT EXISTS messages_at ON messages (at DESC, id DESC);
"""


def _json_list(raw: str | None) -> list[str]:
    """Список адресов из базы; испорченное значение — пустой список, а не падение."""
    try:
        parsed = json.loads(raw or "[]")
    except json.JSONDecodeError:
        return []
    return [str(item) for item in parsed] if isinstance(parsed, list) else []


class Store:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._connection = sqlite3.connect(self.path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        with self._lock:
            self._connection.executescript(SCHEMA)
            self._connection.commit()

    def close(self) -> None:
        self._connection.close()

    # --- запись ----------------------------------------------------------------

    def add(self, *, account: str, folder: str, uid: int, direction: str, letter, read: bool) -> int | None:
        """Вставить письмо; None — если такое уже есть (тот же UID в той же папке)."""
        with self._lock:
            try:
                cursor = self._connection.execute(
                    """INSERT INTO messages
                       (account, folder, uid, direction, subject, preview, from_addr, from_name, to_json,
                        at, read, size, text, message_id, in_reply_to, spf_pass)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        account,
                        folder,
                        uid,
                        direction,
                        letter.subject,
                        letter.text[:200],
                        letter.from_address,
                        letter.from_name,
                        json.dumps(letter.to, ensure_ascii=False),
                        letter.at,
                        1 if read else 0,
                        letter.size,
                        letter.text,
                        letter.message_id,
                        letter.in_reply_to,
                        1 if letter.spf_pass else 0,
                    ),
                )
            except sqlite3.IntegrityError:
                return None
            if cursor.lastrowid is None:
                return None
            message_id = int(cursor.lastrowid)
            for item in letter.attachments:
                self._connection.execute(
                    "INSERT OR REPLACE INTO attachments (message_id, n, name, mime, size, data) VALUES (?,?,?,?,?,?)",
                    (message_id, item.n, item.name, item.mime, item.size, item.data),
                )
            self._connection.commit()
            return message_id

    def mark_read(self, message_id: int) -> bool:
        with self._lock:
            cursor = self._connection.execute("UPDATE messages SET read = 1 WHERE id = ?", (message_id,))
            self._connection.commit()
            return cursor.rowcount > 0

    # --- чтение ----------------------------------------------------------------

    def _row_to_summary(self, row: sqlite3.Row) -> dict:
        attachments = self.attachments_info(int(row["id"]))
        return {
            "id": int(row["id"]),
            "direction": row["direction"],
            "folder": row["folder"],
            "status": "delivered",
            "from": {"address": row["from_addr"], "name": row["from_name"]},
            "to": _json_list(row["to_json"]),
            "subject": row["subject"],
            "preview": row["preview"],
            "at": row["at"],
            "read": bool(row["read"]),
            "fromOwner": False,
            "authenticated": bool(row["spf_pass"]),
            "threadReply": bool(row["in_reply_to"]),
            "suspicious": None,
            "attachments": attachments,
            "size": int(row["size"]),
        }

    def attachments_info(self, message_id: int) -> list[dict]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT n, name, mime, size FROM attachments WHERE message_id = ? ORDER BY n", (message_id,)
            ).fetchall()
        return [{"n": int(r["n"]), "name": r["name"], "mime": r["mime"], "size": int(r["size"])} for r in rows]

    def list(self, *, folder: str | None = None, after: int | None = None, unread: bool = False, limit: int = 50) -> list[dict]:
        # Один статический запрос с именованными параметрами: условия не собираются строками,
        # поэтому подстановка значений остаётся параметрами, а не текстом SQL.
        sql = (
            "SELECT * FROM messages "
            "WHERE (:folder IS NULL OR folder = :folder) "
            "AND (:after IS NULL OR id > :after) "
            "AND (:unread = 0 OR read = 0) "
            "ORDER BY id ASC LIMIT :limit"
        )
        with self._lock:
            rows = self._connection.execute(
                sql,
                {
                    "folder": folder or None,
                    "after": int(after) if after is not None else None,
                    "unread": 1 if unread else 0,
                    "limit": max(1, min(100, int(limit))),
                },
            ).fetchall()
        return [self._row_to_summary(row) for row in rows]

    def get(self, message_id: int) -> dict | None:
        with self._lock:
            row = self._connection.execute("SELECT * FROM messages WHERE id = ?", (int(message_id),)).fetchone()
        if row is None:
            return None
        summary = self._row_to_summary(row)
        return {**summary, "text": row["text"], "messageId": row["message_id"]}

    def attachment(self, message_id: int, n: int) -> dict | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT name, mime, data FROM attachments WHERE message_id = ? AND n = ?", (int(message_id), int(n))
            ).fetchone()
        if row is None:
            return None
        return {"name": row["name"], "mime": row["mime"], "data": bytes(row["data"])}

    def counts(self) -> dict:
        with self._lock:
            unread = self._connection.execute("SELECT COUNT(*) FROM messages WHERE read = 0").fetchone()[0]
            total = self._connection.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
            last = self._connection.execute("SELECT MAX(id) FROM messages").fetchone()[0]
        return {"unread": int(unread or 0), "total": int(total or 0), "lastId": int(last or 0)}


def store_path(account_dir: str | Path) -> Path:
    return Path(os.environ.get("EGGENT_MAIL_DB") or Path(account_dir) / "letters.sqlite3")
