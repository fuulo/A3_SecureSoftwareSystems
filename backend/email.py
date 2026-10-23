import smtplib
from email.message import EmailMessage
from html import escape

from backend.config import (
    SMTP_FROM_EMAIL,
    SMTP_HOST,
    SMTP_PASSWORD,
    SMTP_PORT,
    SMTP_USE_SSL,
    SMTP_USERNAME,
)


def send_password_setup_email(email: str, name: str, link: str) -> None:
    if not SMTP_HOST or not SMTP_FROM_EMAIL:
        raise RuntimeError("SMTP_HOST and SMTP_FROM_EMAIL must be configured to send setup email")

    message = EmailMessage()
    message["Subject"] = "Set up your voting system account"
    message["From"] = SMTP_FROM_EMAIL
    message["To"] = email
    message.set_content(
        f"Hello {name},\n\nUse this link to set your account password:\n{link}\n"
    )
    message.add_alternative(
        f"<p>Hello {escape(name)},</p><p><a href=\"{escape(link, quote=True)}\">Set your account password</a></p>",
        subtype="html",
    )
    smtp_type = smtplib.SMTP_SSL if SMTP_USE_SSL else smtplib.SMTP
    with smtp_type(SMTP_HOST, SMTP_PORT, timeout=15) as server:
        if not SMTP_USE_SSL:
            server.starttls()
        if SMTP_USERNAME:
            server.login(SMTP_USERNAME, SMTP_PASSWORD or "")
        server.send_message(message)
