"""TLS-only registration mail transport with safe public failures."""

import logging
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr

from app.core.config import Settings, get_settings
from app.core.errors import AppError
from app.models.auth import normalize_email

logger = logging.getLogger(__name__)


def delivery_error() -> AppError:
    return AppError(503, "email_send_failed", "邮件暂时无法发送，请稍后重试")


def is_ready(settings: Settings) -> bool:
    """Incomplete mail configuration disables registration, not application boot."""
    if settings.smtp_security.strip().lower() not in {"ssl", "starttls"}:
        return False
    if not all(
        value.strip()
        for value in (
            settings.smtp_host,
            settings.smtp_username,
            settings.smtp_password,
            settings.smtp_from_email,
        )
    ):
        return False
    if any(
        char.isspace() or ord(char) < 32 or ord(char) == 127
        for char in settings.smtp_host.strip()
    ):
        return False
    if any(
        ord(char) < 32 or ord(char) == 127
        for value in (settings.smtp_from_name, settings.smtp_username)
        for char in value
    ):
        return False
    try:
        normalize_email(settings.smtp_from_email)
    except ValueError:
        return False
    return True


def send_registration_email(
    recipient: str,
    code: str,
    expires_in_seconds: int,
    *,
    settings: Settings | None = None,
) -> None:
    """Runs in a worker thread; neither SMTP responses nor message bodies are logged."""
    settings = settings or get_settings()
    if not is_ready(settings):
        raise delivery_error()
    try:
        sender = normalize_email(settings.smtp_from_email)
        recipient = normalize_email(recipient)
        message = EmailMessage()
        message["Subject"] = "循课注册验证码"
        message["From"] = formataddr((settings.smtp_from_name, sender))
        message["To"] = recipient
        message.set_content(
            f"您的循课注册验证码是：{code}\n\n"
            f"请在 {max(0, expires_in_seconds)} 秒内完成注册。"
            "验证码仅用于该邮箱注册，请勿向他人提供。\n"
            "重新发送后请使用最新验证码；若非本人操作，请忽略此邮件。\n"
        )
        context = ssl.create_default_context()
        options = {
            "host": settings.smtp_host.strip(),
            "port": settings.smtp_port,
            "timeout": settings.smtp_timeout_seconds,
        }
        if settings.smtp_security.strip().lower() == "ssl":
            connection = smtplib.SMTP_SSL(**options, context=context)
        else:
            connection = smtplib.SMTP(**options)
        with connection as smtp:
            smtp.ehlo()
            if settings.smtp_security.strip().lower() == "starttls":
                smtp.starttls(context=context)
                smtp.ehlo()
            smtp.login(settings.smtp_username, settings.smtp_password)
            refused = smtp.send_message(message, from_addr=sender, to_addrs=[recipient])
            if refused:
                raise smtplib.SMTPException("registration delivery refused")
    except (smtplib.SMTPException, OSError, ValueError) as exc:
        logger.warning(
            "email_delivery_failed",
            extra={"event": "email_delivery_failed", "error_type": type(exc).__name__},
        )
        raise delivery_error() from None
