"""One explicit transport selection for every transactional email workflow."""

from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import logging
import os
import smtplib
import ssl

from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail
from python_http_client.exceptions import HTTPError

from app.runtime_config import env_int
from app.services.brevo_email_service import BrevoEmailService


logger = logging.getLogger(__name__)


class EmailTransport:
    def __init__(self, sendgrid_client=None):
        self.provider = os.getenv("EMAIL_PROVIDER", "auto").lower()
        self.brevo = BrevoEmailService()
        key = os.getenv("SENDGRID_API_KEY")
        self.sendgrid = sendgrid_client or (SendGridAPIClient(key) if key else None)
        self.sender = (
            os.getenv("BREVO_FROM_EMAIL") if self.provider.startswith("brevo") else None
        ) or os.getenv("MAIL_DEFAULT_SENDER") or os.getenv("SENDGRID_FROM_EMAIL")
        self.smtp_host = os.getenv("MAIL_SERVER")
        self.smtp_port = env_int("MAIL_PORT", 587, maximum=65535)
        self.smtp_login = os.getenv("MAIL_USERNAME")
        self.smtp_password = os.getenv("MAIL_PASSWORD")
        self.smtp_tls = os.getenv("MAIL_USE_TLS", "true").lower() == "true"
        self.smtp_ssl = os.getenv("MAIL_USE_SSL", "false").lower() == "true"
        self.timeout = env_int("EMAIL_TIMEOUT_SECONDS", 15, maximum=60)
        if self.sendgrid:
            self.sendgrid.client.timeout = self.timeout

    @property
    def selected_provider(self):
        if self.provider != "auto":
            return self.provider
        if self.brevo.is_configured:
            return "brevo"
        if self.sendgrid:
            return "sendgrid"
        return "smtp"

    @property
    def is_configured(self):
        provider = self.selected_provider
        if provider in {"brevo", "brevo_smtp"}:
            return self.brevo.is_configured
        if provider == "sendgrid":
            return bool(self.sendgrid)
        return provider == "smtp" and bool(self.smtp_host and self.sender)

    def send_html(self, recipients, subject, html, reply_to=None):
        if not self.is_configured:
            return {"sent": False, "retryable": False, "message": "Service email non configure"}
        recipients = BrevoEmailService._normalize_recipients(recipients)
        if not recipients:
            return {"sent": False, "retryable": False, "message": "Aucun destinataire"}
        provider = self.selected_provider
        if provider in {"brevo", "brevo_smtp"}:
            return self.brevo.send_html(recipients, subject, html, reply_to)
        try:
            if provider == "sendgrid":
                message = Mail(
                    from_email=self.sender or "orangedigitalcenter@orange-sonatel.com",
                    to_emails=[item["email"] for item in recipients],
                    subject=subject, html_content=html,
                )
                if reply_to:
                    message.reply_to = reply_to
                response = self.sendgrid.send(message)
                if response.status_code in {200, 201, 202}:
                    return {"sent": True, "message": "Email accepte par le service"}
                return self._failure(response.status_code)
            return self._send_smtp(recipients, subject, html, reply_to)
        except HTTPError as error:
            return self._failure(error.status_code)
        except smtplib.SMTPResponseException as error:
            logger.warning("SMTP rejected email: code=%s", error.smtp_code)
            return self._failure(error.smtp_code, smtp=True)
        except Exception:
            logger.warning("Echec du transport email %s", provider)
            return {"sent": False, "retryable": True, "message": "Service email temporairement indisponible"}

    def _send_smtp(self, recipients, subject, html, reply_to):
        if self.smtp_tls and self.smtp_ssl:
            return {"sent": False, "retryable": False, "message": "MAIL_USE_TLS et MAIL_USE_SSL sont incompatibles"}
        message = MIMEMultipart()
        message["From"] = self.sender
        message["To"] = ", ".join(item["email"] for item in recipients)
        message["Subject"] = subject
        if reply_to:
            message["Reply-To"] = reply_to
        message.attach(MIMEText(html, "html", "utf-8"))
        connection = smtplib.SMTP_SSL if self.smtp_ssl else smtplib.SMTP
        kwargs = {"timeout": self.timeout}
        if self.smtp_ssl:
            kwargs["context"] = ssl.create_default_context()
        with connection(self.smtp_host, self.smtp_port, **kwargs) as server:
            if self.smtp_tls:
                server.starttls(context=ssl.create_default_context())
            if self.smtp_login:
                server.login(self.smtp_login, self.smtp_password or "")
            refused = server.send_message(message)
        if refused:
            return {"sent": False, "retryable": False, "message": "Destinataire refuse par le serveur SMTP"}
        return {"sent": True, "message": "Email accepte par le serveur SMTP"}

    @staticmethod
    def _failure(status, smtp=False):
        return {
            "sent": False,
            "retryable": 400 <= status < 500 if smtp else status in {408, 429} or status >= 500,
            "message": f"Email refuse par le service (code {status})",
        }
