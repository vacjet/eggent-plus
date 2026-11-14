"""Письмо IMAP → формы, которые ждёт Eggent (`src/lib/email/types.ts`).

Ошибки разбора здесь не летят наружу: письмо — это чужие данные, и одно битое письмо не должно
ронять синхронизацию ящика. Всё, что не удалось прочитать, превращается в пустое поле и в запись
в журнале, а письмо остаётся в списке.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from email import message_from_bytes
from email.header import decode_header, make_header
from email.message import Message
from email.utils import getaddresses, parsedate_to_datetime

# Расширения, которые просят второго взгляда перед открытием.
DANGEROUS_EXTENSIONS = {
    ".exe", ".scr", ".com", ".bat", ".cmd", ".js", ".jse", ".vbs", ".vbe", ".ps1", ".msi",
    ".jar", ".hta", ".iso", ".img", ".lnk", ".reg", ".docm", ".xlsm", ".pptm", ".dotm",
}
ARCHIVE_EXTENSIONS = {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz"}


def decode_text(value: str | None) -> str:
    """Заголовок в любой кодировке → строка. Ломаное — как есть."""
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except (UnicodeDecodeError, LookupError, ValueError):
        return value


def _bytes_text(part: Message) -> str:
    payload = part.get_payload(decode=True)
    if not isinstance(payload, (bytes, bytearray)):
        raw = part.get_payload()
        return raw if isinstance(raw, str) else ""
    charset = part.get_content_charset() or "utf-8"
    for candidate in (charset, "utf-8", "cp1251", "koi8-r"):
        try:
            return bytes(payload).decode(candidate, errors="strict")
        except (UnicodeDecodeError, LookupError):
            continue
    return bytes(payload).decode("utf-8", errors="replace")


def html_to_text(html: str) -> str:
    """Грубо, но предсказуемо: абзацы и ссылки остаются, теги уходят."""
    text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", html)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</p\s*>", "\n\n", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = text.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"')
    return re.sub(r"[ \t]+", " ", text).strip()


def danger_of(name: str) -> str | None:
    lower = name.lower()
    suffix = "." + lower.rsplit(".", 1)[-1] if "." in lower else ""
    if suffix in DANGEROUS_EXTENSIONS:
        return "executable or macro file"
    if suffix in ARCHIVE_EXTENSIONS:
        return "archive"
    if lower.count(".") >= 2 and suffix in {".pdf", ".doc", ".docx", ".jpg", ".jpeg", ".png"}:
        return "double extension"
    return None


@dataclass
class Attachment:
    n: int
    name: str
    size: int
    mime: str
    data: bytes = field(repr=False, default=b"")

    def info(self) -> dict:
        danger = danger_of(self.name)
        return {
            "n": self.n,
            "name": self.name,
            "size": self.size,
            "mime": self.mime,
            **({"danger": danger} if danger else {}),
        }


@dataclass
class ParsedLetter:
    subject: str
    from_address: str | None
    from_name: str | None
    to: list[str]
    at: str
    text: str
    message_id: str | None
    attachments: list[Attachment]
    size: int
    in_reply_to: str | None
    spf_pass: bool

    def summary(self, *, id: int, direction: str, folder: str, read: bool, address: str, owner: str | None) -> dict:
        preview = re.sub(r"\s+", " ", self.text).strip()[:200]
        from_owner = bool(owner) and (self.from_address or "").lower() == (owner or "").lower()
        suspicious = None if self.spf_pass or direction == "out" else "the sender's domain did not vouch for this address"
        return {
            "id": id,
            "direction": direction,
            "folder": folder,
            "status": "delivered",
            "from": {"address": self.from_address, "name": self.from_name},
            "to": self.to,
            "subject": self.subject,
            "preview": preview,
            "at": self.at,
            "read": read,
            "fromOwner": from_owner,
            "authenticated": self.spf_pass,
            "threadReply": bool(self.in_reply_to),
            "suspicious": suspicious,
            "attachments": [item.info() for item in self.attachments],
            "size": self.size,
        }

    def message(self, **kwargs) -> dict:
        return {**self.summary(**kwargs), "text": self.text, "messageId": self.message_id}


def _spf_pass(message: Message) -> bool:
    """Домен поручился за отправителя: ищем «pass» в заголовках проверки."""
    for header in ("Authentication-Results", "Received-SPF", "ARC-Authentication-Results"):
        for value in message.get_all(header) or []:
            text = str(value).lower()
            if re.search(r"\bspf=pass\b|\bpass\b", text):
                return True
    return False


def parse_letter(raw: bytes) -> ParsedLetter:
    message = message_from_bytes(raw)

    attachments: list[Attachment] = []
    texts: list[str] = []
    htmls: list[str] = []

    for part in message.walk():
        disposition = (part.get("Content-Disposition") or "").lower()
        filename = part.get_filename()
        if filename:
            filename = decode_text(filename)
        is_attachment = "attachment" in disposition or bool(filename)
        if is_attachment:
            data = part.get_payload(decode=True)
            if isinstance(data, (bytes, bytearray)):
                attachments.append(
                    Attachment(
                        n=len(attachments) + 1,
                        name=filename or f"attachment-{len(attachments) + 1}",
                        size=len(data),
                        mime=part.get_content_type(),
                        data=bytes(data),
                    )
                )
            continue
        if part.get_content_maintype() != "text":
            continue
        content_type = part.get_content_type()
        if content_type == "text/plain":
            texts.append(_bytes_text(part))
        elif content_type == "text/html":
            htmls.append(_bytes_text(part))

    body = "\n\n".join(chunk.strip() for chunk in texts if chunk.strip())
    if not body and htmls:
        body = "\n\n".join(html_to_text(chunk) for chunk in htmls)

    subject = decode_text(message.get("Subject"))
    from_pairs = getaddresses([message.get("From") or ""])
    from_address = from_pairs[0][1].lower() if from_pairs and from_pairs[0][1] else None
    from_name = decode_text(from_pairs[0][0]) or None if from_pairs else None
    to = [address.lower() for _, address in getaddresses([message.get("To") or ""]) if address]

    date_header = message.get("Date")
    try:
        at = parsedate_to_datetime(str(date_header)).isoformat() if date_header else ""
    except (TypeError, ValueError):
        at = ""

    return ParsedLetter(
        subject=subject or "(без темы)",
        from_address=from_address,
        from_name=from_name,
        to=to,
        at=at,
        text=body,
        message_id=(message.get("Message-ID") or "").strip() or None,
        attachments=attachments,
        size=len(raw),
        in_reply_to=(message.get("In-Reply-To") or "").strip() or None,
        spf_pass=_spf_pass(message),
    )
