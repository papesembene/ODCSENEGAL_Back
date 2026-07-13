"""Brevo transactional email transport."""

import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from html import escape

import requests


class BrevoEmailService:
    api_url = "https://api.brevo.com/v3/smtp/email"

    def __init__(self, api_key=None, from_email=None, from_name=None):
        self.api_key = api_key or os.getenv("BREVO_API_KEY")
        self.smtp_key = os.getenv("BREVO_SMTP_KEY") or self.api_key
        self.smtp_login = (
            os.getenv("BREVO_SMTP_LOGIN")
            or os.getenv("BREVO_SMTP_USERNAME")
            or os.getenv("MAIL_USERNAME")
        )
        self.smtp_server = os.getenv(
            "BREVO_SMTP_SERVER",
            "smtp-relay.brevo.com",
        )
        self.smtp_port = int(os.getenv("BREVO_SMTP_PORT", "587"))
        self.from_email = (
            from_email
            or os.getenv("BREVO_FROM_EMAIL")
            or os.getenv("MAIL_DEFAULT_SENDER")
            or os.getenv("SENDGRID_FROM_EMAIL")
        )
        self.from_name = (
            from_name
            or os.getenv("BREVO_FROM_NAME")
            or os.getenv("EMAIL_FROM_NAME")
            or "Orange Digital Center"
        )

    @property
    def is_configured(self):
        return bool((self.api_key or self.smtp_key) and self.from_email)

    @property
    def should_use_smtp(self):
        provider = os.getenv("EMAIL_PROVIDER", "").lower()
        if provider == "brevo_smtp":
            return True
        return bool((self.smtp_key or "").startswith("xsmtpsib-"))

    def send_html(self, recipients, subject, html, reply_to=None):
        recipients = self._normalize_recipients(recipients)
        if not self.is_configured:
            return {
                "sent": False,
                "message": (
                    "Email non envoyé: BREVO_API_KEY ou BREVO_FROM_EMAIL "
                    "non configuré"
                ),
            }
        if not recipients:
            return {
                "sent": False,
                "message": "Email non envoyé: aucun destinataire",
            }
        if self.should_use_smtp:
            return self._send_smtp(recipients, subject, html, reply_to)

        payload = {
            "sender": {"email": self.from_email, "name": self.from_name},
            "to": recipients,
            "subject": subject,
            "htmlContent": html,
        }
        if reply_to:
            payload["replyTo"] = {"email": reply_to}

        try:
            response = requests.post(
                self.api_url,
                headers={
                    "accept": "application/json",
                    "api-key": self.api_key,
                    "content-type": "application/json",
                },
                json=payload,
                timeout=15,
            )
            if response.status_code in {200, 201, 202}:
                return {"sent": True, "message": "Email envoyé"}
            detail = self._response_detail(response)
            logging.error(
                "Erreur Brevo: statut %s - %s",
                response.status_code,
                detail,
            )
            return {"sent": False, "message": f"Email non envoyé: {detail}"}
        except Exception as error:
            logging.exception("Erreur Brevo: %s", error)
            return {"sent": False, "message": f"Email non envoyé: {error}"}

    def _send_smtp(self, recipients, subject, html, reply_to=None):
        if not self.smtp_login or not self.smtp_key:
            return {
                "sent": False,
                "message": (
                    "Email non envoyé: BREVO_SMTP_LOGIN et "
                    "BREVO_SMTP_KEY sont requis pour une clé xsmtpsib"
                ),
            }
        try:
            for recipient in recipients:
                message = MIMEMultipart()
                message["From"] = f"{self.from_name} <{self.from_email}>"
                message["To"] = recipient["email"]
                message["Subject"] = subject
                if reply_to:
                    message["Reply-To"] = reply_to
                message.attach(MIMEText(html, "html", "utf-8"))

                with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                    server.ehlo()
                    server.starttls()
                    server.login(self.smtp_login, self.smtp_key)
                    server.send_message(message)
            return {"sent": True, "message": "Email envoyé"}
        except Exception as error:
            logging.exception("Erreur SMTP Brevo: %s", error)
            return {"sent": False, "message": f"Email non envoyé: {error}"}

    @staticmethod
    def _normalize_recipients(recipients):
        if isinstance(recipients, str):
            recipients = [recipients]
        normalized = []
        for item in recipients or []:
            if isinstance(item, dict):
                email = item.get("email")
                name = item.get("name")
            else:
                email = str(item)
                name = ""
            if not email:
                continue
            recipient = {"email": email}
            if name:
                recipient["name"] = name
            normalized.append(recipient)
        return normalized

    @staticmethod
    def _response_detail(response):
        try:
            payload = response.json()
        except ValueError:
            return response.text or f"Statut Brevo {response.status_code}"
        message = payload.get("message")
        code = payload.get("code")
        if message and code:
            return f"{code}: {message}"
        if message:
            return str(message)
        return escape(str(payload))
