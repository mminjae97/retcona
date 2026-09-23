"""EmailClient interface (design doc 10.4.3 style): sending the signup
verification code (auth/email_verification.py).

- smtp: any SMTP server (Gmail with an app password, Amazon SES, SendGrid, ...),
  configured by SMTP_* (see .env.example).
- console (the default): nothing is sent; the message is logged. For local
  development only — a code in the log is a code anyone who can read the log
  can use.
"""

import logging
import os
import smtplib
import ssl
from abc import ABC, abstractmethod
from email.message import EmailMessage

logger = logging.getLogger(__name__)


class EmailSendError(Exception):
    """The message couldn't be handed to the mail server."""


class EmailClient(ABC):
    @abstractmethod
    def send(self, to: str, subject: str, body: str) -> None:
        """Send a plain-text message, or raise EmailSendError."""


class ConsoleEmailClient(EmailClient):
    def send(self, to: str, subject: str, body: str) -> None:
        logger.warning("EMAIL_PROVIDER=console, not sending. To: %s | %s\n%s", to, subject, body)


class SmtpEmailClient(EmailClient):
    def __init__(self, host: str, port: int, username: str, password: str, sender: str, security: str):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.sender = sender
        self.security = security  # starttls | ssl | none

    def send(self, to: str, subject: str, body: str) -> None:
        message = EmailMessage()
        message["From"] = self.sender
        message["To"] = to
        message["Subject"] = subject
        message.set_content(body)
        try:
            if self.security == "ssl":
                server = smtplib.SMTP_SSL(self.host, self.port, timeout=10, context=ssl.create_default_context())
            else:
                server = smtplib.SMTP(self.host, self.port, timeout=10)
            with server:
                if self.security == "starttls":
                    server.starttls(context=ssl.create_default_context())
                if self.username:
                    server.login(self.username, self.password)
                server.send_message(message)
        except (smtplib.SMTPException, OSError) as exc:
            raise EmailSendError(str(exc)) from exc


def get_email_client() -> EmailClient:
    provider = os.environ.get("EMAIL_PROVIDER", "console").strip().lower()
    if provider == "smtp":
        return SmtpEmailClient(
            host=os.environ["SMTP_HOST"],
            port=int(os.environ.get("SMTP_PORT", "587")),
            username=os.environ.get("SMTP_USERNAME", ""),
            password=os.environ.get("SMTP_PASSWORD", ""),
            sender=os.environ.get("SMTP_FROM") or os.environ.get("SMTP_USERNAME", ""),
            security=os.environ.get("SMTP_SECURITY", "starttls").strip().lower(),
        )
    return ConsoleEmailClient()
