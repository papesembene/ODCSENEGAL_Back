"""Contact email preparation and delivery."""

from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import os
import smtplib


class ContactService:
    SMTP_HOST = "smtp.gmail.com"
    SMTP_PORT = 587

    def send(self, data):
        data = data or {}
        sender_email = os.getenv("MAIL_USERNAME")
        sender_password = os.getenv("MAIL_PASSWORD")
        recipient_email = os.getenv(
            "CONTACT_RECIPIENT_EMAIL",
            "thiernohamidou.balde@orange-sonatel.com",
        )
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
