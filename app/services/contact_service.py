"""Contact email preparation and delivery."""

from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import os
import smtplib

from app.services.brevo_email_service import BrevoEmailService


class ContactService:
    SMTP_HOST = "smtp.gmail.com"
    SMTP_PORT = 587

    def send(self, data):
        data = data or {}
        recipient_email = os.getenv(
            "CONTACT_RECIPIENT_EMAIL",
            "thiernohamidou.balde@orange-sonatel.com",
        )
        brevo = BrevoEmailService()
        if brevo.is_configured:
            result = brevo.send_html(
                recipients=[recipient_email],
                subject=(
                    "Nouveau message de contact - "
                    f"{data.get('subject') or 'ODC'}"
                ),
                html=self._build_html(data),
                reply_to=data.get("email"),
            )
            if not result["sent"]:
                raise RuntimeError(result["message"])
            return

        sender_email = os.getenv("MAIL_USERNAME")
        sender_password = os.getenv("MAIL_PASSWORD")
        if not sender_email or not sender_password:
            raise RuntimeError("Configuration email manquante")

        message = self._build_message(
            data,
            sender_email,
            recipient_email,
        )
        with smtplib.SMTP(self.SMTP_HOST, self.SMTP_PORT) as server:
            server.ehlo()
            server.starttls()
            server.login(sender_email, sender_password)
            server.send_message(message)

    @staticmethod
    def _build_message(data, sender_email, recipient_email):
        subject = data.get("subject")
        body = (
            f"Nom: {data.get('name')}\n"
            f"Email: {data.get('email')}\n"
            f"Téléphone: {data.get('phone')}\n"
            "Préférence de contact: "
            f"{data.get('contactPreference')}\n\n"
            f"Message:\n{data.get('message')}\n"
        )
        message = MIMEMultipart()
        message["From"] = sender_email
        message["To"] = recipient_email
        message["Subject"] = f"Nouveau message de contact - {subject}"
        message.attach(MIMEText(body, "plain"))
        return message

    @staticmethod
    def _build_html(data):
        return f"""
        <div style="font-family:Arial,sans-serif;line-height:1.5;color:#111827">
          <h2>Nouveau message de contact</h2>
          <p><strong>Nom :</strong> {data.get('name') or '-'}</p>
          <p><strong>Email :</strong> {data.get('email') or '-'}</p>
          <p><strong>Téléphone :</strong> {data.get('phone') or '-'}</p>
          <p><strong>Préférence :</strong> {data.get('contactPreference') or '-'}</p>
          <p><strong>Message :</strong></p>
          <p>{data.get('message') or ''}</p>
        </div>
        """
