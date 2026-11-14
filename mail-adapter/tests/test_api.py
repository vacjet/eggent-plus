"""HTTP-слой на контракте ядра: токен, список, письмо, вложение, отправка."""

import json
import threading
import unittest
import urllib.error
import urllib.request

from adapter.api import MailAdapter, serve

TOKEN = "test-token-0123456789"


class FakeStore:
    """Хранилище в памяти: тест проверяет HTTP, а не SQLite."""

    def __init__(self):
        self.messages = {
            7: {
                "id": 7,
                "direction": "in",
                "folder": "inbox",
                "status": "delivered",
                "from": {"address": "ivan@example.ru", "name": "Иван"},
                "to": ["mail@example.com"],
                "subject": "Письмо",
                "preview": "Привет",
                "at": "2026-11-13T09:30:00+00:00",
                "read": False,
                "fromOwner": False,
                "authenticated": True,
                "threadReply": False,
                "suspicious": None,
                "attachments": [{"n": 1, "name": "отчёт.pdf", "mime": "application/pdf", "size": 9}],
                "size": 120,
                "text": "Привет!\nТело.",
                "messageId": "<abc@example.ru>",
            }
        }
        self.read = set()
        self.attachment_bytes = b"%PDF-1.4"

    def counts(self):
        return {"unread": len([m for m in self.messages.values() if not m["read"]]), "total": len(self.messages), "lastId": 7}

    def list(self, *, folder=None, after=None, unread=False, limit=50):
        items = list(self.messages.values())
        if folder:
            items = [m for m in items if m["folder"] == folder]
        if after is not None:
            items = [m for m in items if m["id"] > after]
        if unread:
            items = [m for m in items if not m["read"]]
        return items[:limit]

    def get(self, message_id):
        return self.messages.get(message_id)

    def mark_read(self, message_id):
        if message_id not in self.messages:
            return False
        self.messages[message_id]["read"] = True
        return True

    def attachment_data(self, message_id, n):
        if message_id == 7 and n == 1:
            return {"name": "отчёт.pdf", "mime": "application/pdf", "data": self.attachment_bytes}
        return None


def attachment_adapter(store):
    """FakeStore отдаёт вложение через метод store.attachment, как настоящий."""
    store.attachment = store.attachment_data  # type: ignore[attr-defined]
    return store


class ApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.store = attachment_adapter(FakeStore())
        cls.sent = []
        cls.adapter = MailAdapter(
            token=TOKEN,
            store=cls.store,
            address="mail@example.com",
            send=lambda body: (cls.sent.append(body) or {"status": "sent", "to": body.get("to") or [], "ids": [], "failed": []}),
            status_extra=lambda: {"accounts": [{"id": "work", "address": "mail@example.com"}]},
        )
        cls.server = serve(cls.adapter, host="127.0.0.1", port=0)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def get(self, path, token=TOKEN):
        request = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", headers={"Authorization": f"Bearer {token}"})
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as error:
            return error.code, error.read()

    def post(self, path, body=None, token=TOKEN):
        data = json.dumps(body or {}).encode()
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}",
            data=data,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as error:
            return error.code, error.read()

    def test_no_token_is_401(self):
        status, _ = self.get("/status", token="")
        self.assertEqual(status, 401)

    def test_wrong_token_is_401(self):
        status, _ = self.get("/messages", token="nope")
        self.assertEqual(status, 401)

    def test_status_shape(self):
        status, body = self.get("/status")
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertTrue(data["enabled"])
        self.assertEqual(data["address"], "mail@example.com")
        self.assertIn("unread", data)

    def test_list_and_filters(self):
        status, body = self.get("/messages?folder=inbox&limit=10")
        self.assertEqual(status, 200)
        self.assertEqual(len(json.loads(body)["messages"]), 1)
        status, body = self.get("/messages?unread=1")
        self.assertEqual(len(json.loads(body)["messages"]), 1)

    def test_unknown_letter_is_404(self):
        status, _ = self.get("/messages/999")
        self.assertEqual(status, 404)

    def test_message_carries_text(self):
        status, body = self.get("/messages/7")
        self.assertEqual(status, 200)
        self.assertIn("Тело", json.loads(body)["message"]["text"])

    def test_attachment_bytes(self):
        status, body = self.get("/messages/7/attachments/1")
        self.assertEqual(status, 200)
        self.assertEqual(body, b"%PDF-1.4")

    def test_mark_read(self):
        status, body = self.post("/messages/7/read")
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(body)["ok"])

    def test_send_passes_body_through(self):
        self.sent.clear()
        status, body = self.post("/send", {"to": ["ivan@example.ru"], "text": "Привет"})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["status"], "sent")
        self.assertEqual(self.sent[0]["text"], "Привет")

    def test_send_without_text_is_400(self):
        status, _ = self.post("/send", {"to": ["ivan@example.ru"]})
        self.assertEqual(status, 400)

    def test_send_with_broken_base64_is_400(self):
        status, _ = self.post("/send", {"text": "x", "attachments": [{"name": "a.bin", "data": "***"}]})
        self.assertEqual(status, 400)


if __name__ == "__main__":
    unittest.main()
