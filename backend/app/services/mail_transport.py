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


def _deliver(message: EmailMessage, settings: Settings, sender: str, recipient: str) -> None:
    """Shared TLS-only SMTP delivery; connection details stay out of logs."""
    context = ssl.create_default_context()
    options = {
        "host": settings.smtp_host.strip(),
        "port": settings.smtp_port,
        "timeout": settings.smtp_timeout_seconds,
    }
    try:
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
                raise smtplib.SMTPException("email delivery refused")
    except (smtplib.SMTPException, OSError, ValueError) as exc:
        logger.warning(
            "email_delivery_failed",
            extra={"event": "email_delivery_failed", "error_type": type(exc).__name__},
        )
        raise delivery_error() from None


def _send_code_email(
    recipient: str,
    code: str,
    expires_in_seconds: int,
    *,
    subject: str,
    body: str,
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
        message["Subject"] = subject
        message["From"] = formataddr((settings.smtp_from_name, sender))
        message["To"] = recipient
        message.set_content(body)
        _deliver(message, settings, sender, recipient)
    except (smtplib.SMTPException, OSError, ValueError) as exc:
        logger.warning(
            "email_delivery_failed",
            extra={"event": "email_delivery_failed", "error_type": type(exc).__name__},
        )
        raise delivery_error() from None


def send_registration_email(
    recipient: str,
    code: str,
    expires_in_seconds: int,
    *,
    settings: Settings | None = None,
) -> None:
    _send_code_email(
        recipient,
        code,
        expires_in_seconds,
        subject="循课注册验证码",
        body=(
            f"您的循课注册验证码是：{code}\n\n"
            f"请在 {max(0, expires_in_seconds)} 秒内完成注册。"
            "验证码仅用于该邮箱注册，请勿向他人提供。\n"
            "重新发送后请使用最新验证码；若非本人操作，请忽略此邮件。\n"
        ),
        settings=settings,
    )


def send_password_reset_email(
    recipient: str,
    code: str,
    expires_in_seconds: int,
    *,
    settings: Settings | None = None,
) -> None:
    _send_code_email(
        recipient,
        code,
        expires_in_seconds,
        subject="循课密码重置验证码",
        body=(
            f"您的循课密码重置验证码是：{code}\n\n"
            f"请在 {max(0, expires_in_seconds)} 秒内完成密码重置。"
            "验证码仅用于重置该邮箱账号的密码，请勿向他人提供。\n"
            "重新发送后请使用最新验证码；若非本人操作，请忽略此邮件。\n"
        ),
        settings=settings,
    )


def send_learning_reminder_email(
    recipient: str,
    title: str,
    link_path: str,
    *,
    settings: Settings | None = None,
) -> None:
    """学习提醒只含短提示与站内入口：不发答题正文、资料摘录或薄弱点列表。"""
    origin = (settings.web_origins[0] if settings and settings.web_origins else "").rstrip("/")
    _send_code_email(
        recipient,
        "",
        0,
        subject=f"循课 · {title}",
        body=(
            f"{title}\n\n请登录循课查看：{origin}{link_path}\n"
            "本邮件不包含你的答题内容或学习记录详情。\n"
        ),
        settings=settings,
    )
