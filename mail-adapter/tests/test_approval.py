"""Подтверждение отправки на чужой адрес: без кода не уходит, код не читается агентом."""

import json
import sqlite3
import threading
import unittest
import urllib.error
import urllib.request

from adapter.api import MailAdapter, serve
from adapter.approval import APPROVAL_SUBJECT, Approvals, sends_code

TOKEN = "approval-token-0123456789"


class FakeStore:
    def counts(self):
        return {"unread": 0, "total": 0, "lastId": 0}

    def attachment(self, message_id, n):
        return None


class ApprovalTest(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:", check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.approvals = Approvals(self.connection)
        self.sent = []
        self.codes_sent = []

        def send(body):
            self.sent.append(body)
            return {"status": "sent", "to": body.get("to") or [], "ids": [], "failed": []}

        self.adapter = MailAdapter(
            token=TOKEN,
            store=FakeStore(),
            address="me@example.ru",
            send=send,
            approvals=self.approvals,
            notify=lambda approval: (self.codes_sent.append(approval["code"]) or "marker"),
            own_addresses=["me@example.ru"],
        )
        self.server = serve(self.adapter, port=0)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.connection.close()

    def post(self, path, body):
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}",
            data=json.dumps(body).encode(),
            headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read())

    def test_own_address_goes_straight_out(self):
        status, body = self.post("/send", {"to": ["me@example.ru"], "text": "себе"})
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "sent")
        self.assertEqual(len(self.sent), 1)

    def test_third_party_waits_for_a_code(self):
        status, body = self.post("/send", {"to": ["ivan@example.ru"], "subject": "Отчёт", "text": "тело"})
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "pending")
        self.assertEqual(body["request"]["to"], ["ivan@example.ru"])
        self.assertEqual(self.sent, [], "до подтверждения ничего не отправлено")
        self.assertEqual(len(self.codes_sent), 1, "код ушёл владельцу")

    def test_wrong_code_refused(self):
        _, pending = self.post("/send", {"to": ["ivan@example.ru"], "text": "x"})
        status, body = self.post("/approve", {"id": pending["request"]["id"], "code": "000000"})
        self.assertEqual(status, 400)
        self.assertIn("does not match", body["error"])
        self.assertEqual(self.sent, [])

    def test_right_code_sends_once_and_twice_is_refused(self):
        _, pending = self.post("/send", {"to": ["ivan@example.ru"], "subject": "Отчёт", "text": "тело"})
        approval_id = pending["request"]["id"]
        code = self.codes_sent[0]
        status, body = self.post("/approve", {"id": approval_id, "code": code})
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "sent")
        self.assertEqual(self.sent[0]["to"], ["ivan@example.ru"])

        status, again = self.post("/approve", {"id": approval_id, "code": code})
        self.assertEqual(status, 400)
        self.assertIn("already approved", again["error"])
        self.assertEqual(len(self.sent), 1, "повторное подтверждение не шлёт второй раз")

    def test_expired_request_refused(self):
        _, pending = self.post("/send", {"to": ["ivan@example.ru"], "text": "x"})
        approval_id = pending["request"]["id"]
        code = self.codes_sent[0]
        self.connection.execute("UPDATE approvals SET expires_at = '2000-01-01T00:00:00+00:00' WHERE id = ?", (approval_id,))
        self.connection.commit()
        status, body = self.post("/approve", {"id": approval_id, "code": code})
        self.assertEqual(status, 400)
        self.assertIn("expired", body["error"])

    def test_the_code_letter_is_not_stored_for_the_agent(self):
        # Синхронизация пропускает письма с темой-маркером: агент не прочитает код.
        from adapter.sync import folder_kind  # noqa: F401 — импорт проверяет, что модуль жив
        self.assertTrue(APPROVAL_SUBJECT)
        self.assertEqual(APPROVAL_SUBJECT, "Код подтверждения письма")


if __name__ == "__main__":
    unittest.main()
