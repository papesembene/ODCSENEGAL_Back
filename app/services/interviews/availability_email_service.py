"""Email notifications for interview jury assignments."""

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


class InterviewAvailabilityEmailService:
    def __init__(self, client=None):
        self.sendgrid_api_key = os.getenv("SENDGRID_API_KEY")
        self.from_email = os.getenv(
            "SENDGRID_FROM_EMAIL",
            "orangedigitalcenter@orange-sonatel.com",
        )
        self.api_public_url = os.getenv(
            "API_PUBLIC_URL",
            os.getenv("BACKEND_PUBLIC_URL", "http://localhost:5000"),
        ).rstrip("/")
        self.client = client or (
            SendGridAPIClient(self.sendgrid_api_key)
            if self.sendgrid_api_key
            else None
        )
        self.brevo = BrevoEmailService()

    def send_availability_request(self, jury, slot, roles, token=None):
        html_content = self._build_html(
            jury=jury,
            slot=slot,
            roles=roles,
        )
        if self.brevo.is_configured:
            result = self.brevo.send_html(
                recipients=[
                    {
                        "email": jury.email,
                        "name": self._jury_name(jury),
                    }
                ],
                subject=f"Affectation entretien - {slot.label}",
                html=html_content,
            )
            if result["sent"]:
                logging.info(
                    "Email affectation jury Brevo envoyé à %s pour créneau %s",
                    jury.email,
                    slot.id,
                )
                return True
            logging.error(result["message"])
            return False

        if not self.client:
            logging.warning(
                "SENDGRID_API_KEY non configurée; affectation non envoyée à %s",
                jury.email,
            )
            return False

        message = Mail(
            from_email=Email(self.from_email, "Orange Digital Center"),
            to_emails=To(jury.email),
            subject=f"Affectation entretien - {slot.label}",
            html_content=Content("text/html", html_content),
        )

        try:
            response = self.client.send(message)
            if response.status_code in {200, 201, 202}:
                logging.info(
                    "Email affectation jury envoyé à %s pour créneau %s",
                    jury.email,
                    slot.id,
                )
                return True
            logging.error(
                "Erreur SendGrid affectation jury %s: statut %s - %s",
                jury.email,
                response.status_code,
                sendgrid_response_detail(response),
            )
        except Exception as error:
            logging.exception(
                "Erreur d'envoi affectation jury à %s: %s",
                jury.email,
                sendgrid_error_detail(error),
            )
        return False

    @staticmethod
    def _jury_name(jury):
        return " ".join(
            value
            for value in [
                getattr(jury, "first_name", ""),
                getattr(jury, "last_name", ""),
            ]
            if value
        ).strip()

    @staticmethod
    def _build_html(jury, slot, roles):
        jury_name = escape(
            " ".join(
                value
                for value in [getattr(jury, "first_name", ""), getattr(jury, "last_name", "")]
                if value
            ).strip()
            or getattr(jury, "email", "jury")
        )
        role_labels = {
            "filter": "Filtreur",
            "validator": "Validateur / coach",
            "motivation": "Jury motivation",
        }
        role_text = ", ".join(role_labels.get(role, role) for role in roles)
        start_at = slot.start_at.strftime("%d/%m/%Y %H:%M") if slot.start_at else "-"
        end_at = slot.end_at.strftime("%d/%m/%Y %H:%M") if slot.end_at else "-"

        return f"""
        <div style="font-family:Arial,sans-serif;line-height:1.5;color:#111827">
          <h2>Affectation à un créneau d'entretien</h2>
          <p>Bonjour {jury_name},</p>
          <p>Vous avez été affecté(e) à un créneau d'entretien Orange Digital Center Sénégal.</p>
          <ul>
            <li><strong>Créneau :</strong> {escape(slot.label or "-")}</li>
            <li><strong>Date :</strong> {escape(start_at)} - {escape(end_at)}</li>
            <li><strong>Rôle :</strong> {escape(role_text or "-")}</li>
          </ul>
          <p>Merci de prendre vos dispositions pour être présent(e) sur ce créneau.</p>
          <p>En cas d'indisponibilité, répondez directement à ce message ou contactez l'équipe de coordination.</p>
          <p style="font-size:12px;color:#6b7280">Email automatique Orange Digital Center Sénégal.</p>
        </div>
        """
