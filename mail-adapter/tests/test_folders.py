"""Имена папок: у провайдеров они не «Sent», а «Отправленные» или с флагом \\Sent."""

import unittest

from adapter.sync import folder_kind, parse_list_line, resolve_folder


class FakeClient:
    def __init__(self, lines):
        self.lines = lines

    def list(self):
        return "OK", self.lines


class FolderTest(unittest.TestCase):
    def test_parse_quoted_name_and_flags(self):
        item = parse_list_line(b'(\\HasNoChildren \\Sent) "|" "&BB4EQgQ,BEAEMAQyBDsENQQ9BD0ESwQ1-"')
        self.assertEqual(item["name"], "&BB4EQgQ,BEAEMAQyBDsENQQ9BD0ESwQ1-")
        self.assertIn("\\sent", item["flags"])

    def test_parse_unquoted_name(self):
        item = parse_list_line(b'(\\HasNoChildren) "/" INBOX')
        self.assertEqual(item["name"], "INBOX")

    def test_sent_is_found_by_flag_not_by_name(self):
        client = FakeClient([
            b'(\\HasNoChildren) "/" INBOX',
            '(\\HasNoChildren \\Sent) "/" "Отправленные"'.encode("utf-8"),
        ])
        self.assertEqual(resolve_folder(client, "Sent"), "Отправленные")

    def test_english_sent_still_works(self):
        client = FakeClient([b'(\\HasNoChildren \\Sent) "/" Sent'])
        self.assertEqual(resolve_folder(client, "Sent"), "Sent")

    def test_name_match_when_no_flags(self):
        client = FakeClient([b'(\\HasNoChildren) "/" "INBOX"', b'(\\HasNoChildren) "/" "Sent Items"'])
        self.assertEqual(resolve_folder(client, "sent"), "Sent Items")

    def test_missing_folder_is_none(self):
        client = FakeClient([b'(\\HasNoChildren) "/" INBOX'])
        self.assertIsNone(resolve_folder(client, "Sent"))

    def test_kind_of_folder(self):
        self.assertEqual(folder_kind("INBOX"), "inbox")
        self.assertEqual(folder_kind("Отправленные"), "sent")
        self.assertEqual(folder_kind("Архив"), "other")


if __name__ == "__main__":
    unittest.main()
