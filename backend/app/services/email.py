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
    def __init__(self, message: str = "Email delivery failed", *, category: str = "provider_error", retryable: bool = True):
        super().__init__(message)
        self.category = category
        self.retryable = retryable

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
            raise EmailDeliveryError("Email provider is not configured", category="provider_misconfigured", retryable=False)
        # Reject line breaks and controls before values reach RFC mail headers.
        for value in (settings.email_from, message.to, message.subject):
            if any(ord(char) < 32 or ord(char) == 127 for char in value):
                raise EmailDeliveryError("Email payload is invalid", category="payload_invalid", retryable=False)
        if len(message.to) > 255 or "@" not in message.to or len(message.subject) > 160:
            raise EmailDeliveryError("Email payload is invalid", category="payload_invalid", retryable=False)
        email=EmailMessage()
        email["From"]=settings.email_from
        email["To"]=message.to
        email["Subject"]=message.subject
        email.set_content(message.text)
        try:
            with smtplib.SMTP(settings.smtp_host,settings.smtp_port,timeout=settings.smtp_timeout_seconds) as smtp:
                if settings.smtp_starttls:
                    smtp.starttls(context=ssl.create_default_context())
                if settings.smtp_username:
                    smtp.login(settings.smtp_username,settings.smtp_password or "")
                smtp.send_message(email)
            return True
        except smtplib.SMTPAuthenticationError:
            raise EmailDeliveryError("Email provider authentication failed", category="provider_authentication", retryable=False) from None
        except smtplib.SMTPRecipientsRefused as exc:
            codes = [int(reply[0]) for reply in exc.recipients.values() if reply and reply[0]]
            retryable = bool(codes) and all(400 <= code < 500 for code in codes)
            category = "recipient_temporary" if retryable else "recipient_rejected"
            raise EmailDeliveryError("Email recipient was rejected", category=category, retryable=retryable) from None
        except smtplib.SMTPResponseException as exc:
            retryable = 400 <= int(exc.smtp_code) < 500
            category = "provider_temporary" if retryable else "provider_rejected"
            raise EmailDeliveryError("Email provider rejected the message", category=category, retryable=retryable) from None
        except (OSError, smtplib.SMTPException):
            # Do not include message, credentials, reset token, or SMTP response in exception/log output.
            raise EmailDeliveryError("Email provider delivery failed", category="provider_transient", retryable=True) from None

def get_email_provider() -> EmailProvider:
    if settings.email_mode == "smtp":
        return SMTPEmailProvider()
    return DisabledEmailProvider()

def send_account_email(message: OutgoingEmail) -> bool:
    """Returns true only when a provider accepted the message for sending."""
    return get_email_provider().send(message)
