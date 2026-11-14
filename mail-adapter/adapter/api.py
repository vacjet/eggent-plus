"""HTTP по контракту ядра (`src/lib/email/client.ts`).

Эндпоинты ровно те, что вызывает Eggent:
    GET  /status
    GET  /messages?folder=&after=&unread=1&limit=
    GET  /messages/<id>
    POST /messages/<id>/read
    GET  /messages/<id>/attachments/<n>
    POST /send

Авторизация — `Authorization: Bearer <EGGENT_MAIL_ADAPTER_TOKEN>`. Без неё 401, как у любого
сервиса с токеном: адаптер видит переписку, и открытым он не бывает.
"""

from __future__ import annotations

import base64
import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from collections.abc import Callable
from urllib.parse import parse_qs, quote, urlparse

MESSAGE_RE = re.compile(r"^/messages/(\d+)$")
ATTACHMENT_RE = re.compile(r"^/messages/(\d+)/attachments/(\d+)$")
READ_RE = re.compile(r"^/messages/(\d+)/read$")


class MailAdapter:
    """То, что нужно HTTP-слою от остального адаптера.

    Отдельный класс, а не свободные функции: тесты подставляют сюда поддельный бэкенд и не
    поднимают ни IMAP, ни SMTP.
    """

    def __init__(
        self,
        *,
        token: str,
        store,
        address: str,
        send: Callable[[dict], dict],
        sync: Callable[[], dict] | None = None,
        status_extra: Callable[[], dict] | None = None,
        approvals=None,
        notify: Callable[[dict], str] | None = None,
        own_addresses: list[str] | None = None,
    ):
        self.token = token
        self.store = store
        self.address = address
        self.send = send
        self.sync = sync
        self.status_extra = status_extra
        self.approvals = approvals
        self.notify = notify
        # Свои адреса: письмо на них уходит сразу, на чужие — только с кодом.
        self.own_addresses = {item.lower() for item in (own_addresses or [address]) if item}
        self._sync_lock = threading.Lock()

    def needs_approval(self, recipients: list[str]) -> bool:
        return any(item.lower() not in self.own_addresses for item in recipients)

    def status(self) -> dict:
        counts = self.store.counts()
        body = {
            "enabled": True,
            "address": self.address,
            "owner": {"confirmed": True, "address": self.address},
            "unread": {"inbox": counts["unread"], "other": 0},
            "approval": None,
            "pending": [],
        }
        if self.status_extra:
            body.update(self.status_extra())
        return body


def _bearer(header: str | None) -> str:
    if not header:
        return ""
    match = re.match(r"(?i)^bearer\s+(.+)$", header.strip())
    return match.group(1).strip() if match else ""


def make_handler(adapter: MailAdapter):
    class Handler(BaseHTTPRequestHandler):
        server_version = "EggentMailAdapter/1"

        def log_message(self, format: str, *args) -> None:  # noqa: A002 — имя из базового класса
            print(f"[mail-adapter] {format % args}", flush=True)

        # --- служебное ---------------------------------------------------------

        def _json(self, status: int, body: dict) -> None:
            payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def _authorized(self) -> bool:
            if _bearer(self.headers.get("Authorization")) == adapter.token:
                return True
            self._json(401, {"error": "Unauthorized", "code": "unauthorized"})
            return False

        # --- маршруты ----------------------------------------------------------

        def do_GET(self) -> None:  # noqa: N802 — имя задаёт http.server
            if not self._authorized():
                return
            parsed = urlparse(self.path)
            path = parsed.path.rstrip("/") or "/"

            if path == "/status":
                return self._json(200, adapter.status())

            if path == "/messages":
                query = parse_qs(parsed.query)
                folder = (query.get("folder") or [None])[0]
                after_raw = (query.get("after") or [None])[0]
                after = int(after_raw) if after_raw and after_raw.isdigit() else None
                unread = (query.get("unread") or ["0"])[0] in ("1", "true", "yes")
                limit_raw = (query.get("limit") or ["50"])[0]
                limit = int(limit_raw) if limit_raw.isdigit() else 50
                return self._json(200, {"messages": adapter.store.list(folder=folder, after=after, unread=unread, limit=limit)})

            match = MESSAGE_RE.match(path)
            if match:
                message = adapter.store.get(int(match.group(1)))
                if message is None:
                    return self._json(404, {"error": "No such letter", "code": "notFound"})
                return self._json(200, {"message": message})

            match = ATTACHMENT_RE.match(path)
            if match:
                found = adapter.store.attachment(int(match.group(1)), int(match.group(2)))
                if found is None:
                    return self._json(404, {"error": "No such attachment", "code": "notFound"})
                data = found["data"]
                self.send_response(200)
                self.send_header("Content-Type", found["mime"] or "application/octet-stream")
                # Имя файла бывает русским, а заголовки — latin-1: по RFC 5987 оно идёт
                # процентным кодированием, иначе отправка заголовка падает и клиент
                # получает оборванное соединение вместо файла.
                fallback = re.sub(r"[^\x20-\x7e]", "_", found["name"]) or "attachment"
                self.send_header(
                    "Content-Disposition",
                    f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{quote(found['name'])}",
                )
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return None

            return self._json(404, {"error": "Unknown route", "code": "notFound"})

        def do_POST(self) -> None:  # noqa: N802
            if not self._authorized():
                return
            parsed = urlparse(self.path)
            path = parsed.path.rstrip("/") or "/"

            match = READ_RE.match(path)
            if match:
                ok = adapter.store.mark_read(int(match.group(1)))
                return self._json(200 if ok else 404, {"ok": ok} if ok else {"error": "No such letter", "code": "notFound"})

            if path == "/approve":
                length = int(self.headers.get("Content-Length") or 0)
                try:
                    body = json.loads(self.rfile.read(length) or b"{}")
                except json.JSONDecodeError:
                    return self._json(400, {"error": "Body must be JSON", "code": "badRequest"})
                if adapter.approvals is None:
                    return self._json(503, {"error": "Approvals are not enabled", "code": "notConfigured"})
                approval_id = str(body.get("id") or "").strip()
                code = str(body.get("code") or "").strip()
                if not approval_id or not code:
                    return self._json(400, {"error": "id and code are required", "code": "badRequest"})
                ok, reason, approval = adapter.approvals.decide(approval_id, code)
                if not ok or approval is None:
                    return self._json(400, {"error": reason, "code": "approvalRefused"})
                sent = adapter.send(
                    {
                        "to": approval["to"],
                        "subject": approval["subject"],
                        "text": approval["text"],
                        "attachments": approval["attachments"],
                    }
                )
                return self._json(200, sent)

            if path == "/send":
                length = int(self.headers.get("Content-Length") or 0)
                try:
                    body = json.loads(self.rfile.read(length) or b"{}")
                except json.JSONDecodeError:
                    return self._json(400, {"error": "Body must be JSON", "code": "badRequest"})
                if not isinstance(body, dict) or not isinstance(body.get("text"), str):
                    return self._json(400, {"error": 'Field "text" must be a string', "code": "badRequest"})
                for attachment in body.get("attachments") or []:
                    if isinstance(attachment, dict) and isinstance(attachment.get("data"), str):
                        try:
                            base64.b64decode(attachment["data"], validate=True)
                        except (ValueError, TypeError):
                            return self._json(400, {"error": f"Attachment {attachment.get('name')} is not base64", "code": "badRequest"})
                recipients = [str(item).strip() for item in (body.get("to") or []) if str(item).strip()] or [adapter.address]
                if adapter.approvals is not None and adapter.needs_approval(recipients):
                    approval = adapter.approvals.create(
                        to=recipients,
                        subject=str(body.get("subject") or "(без темы)"),
                        text=str(body.get("text") or ""),
                        attachments=list(body.get("attachments") or []),
                    )
                    if adapter.notify is not None:
                        try:
                            adapter.notify(approval)
                        except Exception as error:
                            adapter.approvals.reject(approval["id"])
                            return self._json(502, {"error": f"Не удалось отправить код подтверждения: {error}", "code": "approvalNotifyFailed"})
                    return self._json(200, {"status": "pending", "request": adapter.approvals.view(approval)})
                try:
                    answer = adapter.send(body)
                except Exception as error:  # отправка — внешний мир, ошибка возвращается как данные
                    return self._json(502, {"status": "sent", "to": body.get("to") or [], "ids": [], "failed": (body.get("to") or [adapter.address] and [{"address": (body.get("to") or [adapter.address])[0], "error": str(error)}])})
                return self._json(200, answer)

            return self._json(404, {"error": "Unknown route", "code": "notFound"})

    return Handler


def serve(adapter: MailAdapter, host: str = "127.0.0.1", port: int = 8787) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), make_handler(adapter))
    return server
