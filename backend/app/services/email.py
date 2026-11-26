"""Email delivery abstraction with an explicit no-delivery development mode."""
from dataclasses import dataclass
from email.message import EmailMessage
import smtplib
import ssl
from app.core.config import settings

@dataclass(frozen=True)
class OutgoingEmail:
    to: str
    subject: str
    text: str

class EmailDeliveryError(RuntimeError):
    pass

class EmailProvider:
    def send(self, message: OutgoingEmail) -> bool:
        raise NotImplementedError

class DisabledEmailProvider(EmailProvider):
    """Safe fallback: no delivery, no token logging, and an explicit False result."""
    def send(self, message: OutgoingEmail) -> bool:
        return False

class SMTPEmailProvider(EmailProvider):
    def send(self, message: OutgoingEmail) -> bool:
        if not settings.smtp_host or not settings.email_from:
            raise EmailDeliveryError("SMTP delivery is enabled but SMTP_HOST/EMAIL_FROM is missing")
        email=EmailMessage()
        email["From"]=settings.email_from
        email["To"]=message.to
        email["Subject"]=message.subject
        email.set_content(message.text)
        try:
            with smtplib.SMTP(settings.smtp_host,settings.smtp_port,timeout=10) as smtp:
                if settings.smtp_starttls:
                    smtp.starttls(context=ssl.create_default_context())
                if settings.smtp_username:
                    smtp.login(settings.smtp_username,settings.smtp_password or "")
                smtp.send_message(email)
            return True
        except (OSError, smtplib.SMTPException) as exc:
            # Do not include message, credentials, reset token, or SMTP response in exception/log output.
            raise EmailDeliveryError("Email provider delivery failed") from exc

def get_email_provider() -> EmailProvider:
    if settings.email_mode == "smtp":
        return SMTPEmailProvider()
    return DisabledEmailProvider()

def send_account_email(message: OutgoingEmail) -> bool:
    """Returns true only when a provider accepted the message for sending."""
    return get_email_provider().send(message)
