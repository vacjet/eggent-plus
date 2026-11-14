"""Отправка через SMTP.

Возвращает ответ в форме ядра (`EmailSendAnswer`): `sent` со списком принятых адресов и списком
неудачных, а не исключение на первый же отказ — письмо на три адреса с одним битым не должно
терять два хороших.
"""

from __future__ import annotations

import base64
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid

from .config import Account


def build_message(account: Account, body: dict) -> EmailMessage:
    message = EmailMessage()
    message["From"] = formataddr((account.display_name or account.address, account.address))
    to = [str(item).strip() for item in (body.get("to") or []) if str(item).strip()] or [account.address]
    message["To"] = ", ".join(to)
    message["Subject"] = str(body.get("subject") or "(без темы)")
    message["Date"] = formatdate(localtime=True)
    message["Message-ID"] = make_msgid(domain=account.address.rsplit("@", 1)[-1])
    if body.get("replyTo"):
        message["In-Reply-To"] = f"<{body['replyTo']}>"
    message.set_content(str(body.get("text") or ""))

    for attachment in body.get("attachments") or []:
        if not isinstance(attachment, dict):
            continue
        name = str(attachment.get("name") or "attachment")
        mime = str(attachment.get("mime") or "application/octet-stream")
        maintype, _, subtype = mime.partition("/")
        data = base64.b64decode(str(attachment.get("data") or ""))
        message.add_attachment(data, maintype=maintype or "application", subtype=subtype or "octet-stream", filename=name)
    return message


def send_letter(account: Account, body: dict) -> dict:
    message = build_message(account, body)
    to = [str(item).strip() for item in (body.get("to") or []) if str(item).strip()] or [account.address]
    failed: list[dict] = []

    try:
        if account.smtp_tls and account.smtp_port == 465:
            client: smtplib.SMTP = smtplib.SMTP_SSL(account.smtp_host, account.smtp_port, context=ssl.create_default_context(), timeout=30)
        else:
            client = smtplib.SMTP(account.smtp_host, account.smtp_port, timeout=30)
            if account.smtp_tls:
                client.starttls(context=ssl.create_default_context())
        with client:
            client.login(account.username, account.password)
            client.send_message(message, from_addr=account.address, to_addrs=to)
        return {"status": "sent", "to": to, "ids": [], "failed": failed}
    except (smtplib.SMTPException, OSError, ValueError) as error:
        failed = [{"address": address, "error": str(error)} for address in to]
        return {"status": "sent", "to": [], "ids": [], "failed": failed}
