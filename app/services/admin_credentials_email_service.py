"""Email notifications for administrator and jury credentials."""

import logging
import os
from html import escape

import certifi
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Content, Email, Mail, To

from app.services.brevo_email_service import BrevoEmailService
from app.services.sendgrid_helpers import (
    sendgrid_error_detail,
    sendgrid_response_detail,
)


os.environ.setdefault("SSL_CERT_FILE", certifi.where())


class AdminCredentialsEmailService:
    def __init__(self, client=None):
        self.sendgrid_api_key = os.getenv("SENDGRID_API_KEY")
        self.from_email = os.getenv(
            "SENDGRID_FROM_EMAIL",
            "orangedigitalcenter@orange-sonatel.com",
        )
        self.frontend_url = os.getenv(
            "FRONTEND_URL",
            "https://orangedigitalcenter.sn",
        ).rstrip("/")
        self.client = client or (
            SendGridAPIClient(self.sendgrid_api_key)
            if self.sendgrid_api_key
            else None
        )
        self.brevo = BrevoEmailService()

    def send_credentials(self, user, temporary_password, role_label):
        html_content = self._build_html(user, temporary_password, role_label)
        if self.brevo.is_configured:
            return self.brevo.send_html(
                recipients=[
                    {
                        "email": user.email,
                        "name": self._display_name(user),
                    }
                ],
                subject="Vos accès jury - Orange Digital Center Sénégal",
                html=html_content,
            )

        if not self.client:
            logging.warning(
                "SENDGRID_API_KEY non configurée; identifiants non envoyés à %s",
                user.email,
            )
            return {
                "sent": False,
                "message": "Email non envoyé: SENDGRID_API_KEY non configurée",
            }

        message = Mail(
            from_email=Email(self.from_email, "Orange Digital Center"),
            to_emails=To(user.email),
            subject="Vos accès jury - Orange Digital Center Sénégal",
            html_content=Content("text/html", html_content),
        )

        try:
            response = self.client.send(message)
            if response.status_code in {200, 201, 202}:
                logging.info("Identifiants envoyés à %s", user.email)
                return {"sent": True, "message": "Email envoyé"}
            logging.error(
                "Erreur SendGrid identifiants %s: statut %s - %s",
                user.email,
                response.status_code,
                sendgrid_response_detail(response),
            )
        except Exception as error:
            detail = sendgrid_error_detail(error)
            logging.exception(
                "Erreur d'envoi des identifiants à %s: %s",
                user.email,
                detail,
            )
            return {
                "sent": False,
                "message": f"Email non envoyé: {detail}",
            }

        return {
            "sent": False,
            "message": "Email non envoyé: erreur du service email",
        }

    @staticmethod
    def _display_name(user):
        return " ".join(
            value
            for value in [
                getattr(user, "first_name", ""),
                getattr(user, "last_name", ""),
            ]
            if value
        ).strip()

    def _build_html(self, user, temporary_password, role_label):
        full_name = self._display_name(user) or getattr(user, "email", "jury")
        login_url = f"{self.frontend_url}/astrodmin"

        return f"""
        <div style="font-family:Arial,sans-serif;line-height:1.5;color:#111827">
          <h2>Vos accès Orange Digital Center Sénégal</h2>
          <p>Bonjour {escape(full_name)},</p>
          <p>Un compte jury a été créé pour vous sur la plateforme d'administration.</p>
          <ul>
            <li><strong>Rôle :</strong> {escape(role_label or "-")}</li>
            <li><strong>Email :</strong> {escape(user.email)}</li>
            <li><strong>Mot de passe temporaire :</strong> {escape(temporary_password)}</li>
          </ul>
          <p>
            Connexion :
            <a href="{escape(login_url)}">{escape(login_url)}</a>
          </p>
          <p style="font-size:12px;color:#6b7280">
            Pour des raisons de sécurité, ce mot de passe doit être conservé avec soin.
          </p>
        </div>
        """
