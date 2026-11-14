"""Разбор писем: русские заголовки, вложения, html без текста, битые байты."""

import unittest
from email.message import EmailMessage
from email.utils import format_datetime
from datetime import datetime, timezone

from adapter.mime import danger_of, parse_letter


def letter(**kwargs) -> bytes:
    message = EmailMessage()
    message["From"] = kwargs.get("from_", "Иван Петров <ivan@example.ru>")
    message["To"] = kwargs.get("to", "mail@example.com")
    message["Subject"] = kwargs.get("subject", "Тема письма")
    message["Date"] = format_datetime(datetime(2026, 11, 13, 9, 30, tzinfo=timezone.utc))
    message["Message-ID"] = "<abc@example.ru>"
    if kwargs.get("spf"):
        message["Authentication-Results"] = "mx.example.ru; spf=pass smtp.mailfrom=example.ru"
    if kwargs.get("reply"):
        message["In-Reply-To"] = "<parent@example.ru>"
    message.set_content(kwargs.get("text", "Привет!\n\nЭто тело письма."))
    if kwargs.get("html_only"):
        message.clear_content()
        message.set_content("<p>Только <b>HTML</b> тело</p>", subtype="html")
    for name, data in kwargs.get("attachments", []):
        message.add_attachment(data, maintype="application", subtype="octet-stream", filename=name)
    return message.as_bytes()


class MimeTest(unittest.TestCase):
    def test_russian_subject_and_body(self):
        parsed = parse_letter(letter(subject="Проверка кириллицы", text="Здравствуйте, Иван."))
        self.assertEqual(parsed.subject, "Проверка кириллицы")
        self.assertIn("Здравствуйте", parsed.text)
        self.assertEqual(parsed.from_address, "ivan@example.ru")
        self.assertEqual(parsed.from_name, "Иван Петров")
        self.assertEqual(parsed.to, ["mail@example.com"])

    def test_attachment_is_listed_with_number_and_size(self):
        parsed = parse_letter(letter(attachments=[("отчёт.pdf", b"%PDF-1.4 test")]))
        self.assertEqual(len(parsed.attachments), 1)
        item = parsed.attachments[0]
        self.assertEqual(item.n, 1)
        self.assertEqual(item.name, "отчёт.pdf")
        self.assertEqual(item.size, len(b"%PDF-1.4 test"))
        self.assertEqual(item.data, b"%PDF-1.4 test")

    def test_html_only_becomes_text(self):
        parsed = parse_letter(letter(html_only=True))
        self.assertIn("Только", parsed.text)
        self.assertIn("HTML", parsed.text)
        self.assertNotIn("<b>", parsed.text)

    def test_spf_pass_is_noted_and_reply_is_threaded(self):
        parsed = parse_letter(letter(spf=True, reply=True))
        self.assertTrue(parsed.spf_pass)
        self.assertEqual(parsed.in_reply_to, "<parent@example.ru>")

    def test_broken_bytes_do_not_crash(self):
        parsed = parse_letter(b"\xff\xfe not really a message \x00")
        self.assertTrue(parsed.subject)
        self.assertEqual(parsed.attachments, [])

    def test_danger_labels(self):
        self.assertIn("executable", danger_of("invoice.exe") or "")
        self.assertEqual(danger_of("photo.jpg"), None)
        self.assertIn("archive", danger_of("files.zip") or "")


if __name__ == "__main__":
    unittest.main()
