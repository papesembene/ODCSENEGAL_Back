"""Email notifications for interview jury availability."""

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

    def send_availability_request(self, jury, slot, roles, token):
        available_link = self._availability_link(token, "available")
        unavailable_link = self._availability_link(token, "unavailable")
        html_content = self._build_html(
            jury=jury,
            slot=slot,
            roles=roles,
            available_link=available_link,
            unavailable_link=unavailable_link,
        )
        if self.brevo.is_configured:
            result = self.brevo.send_html(
                recipients=[
                    {
                        "email": jury.email,
                        "name": self._jury_name(jury),
                    }
                ],
                subject=f"Disponibilité jury - {slot.label}",
                html=html_content,
            )
            if result["sent"]:
                logging.info(
                    "Email disponibilité Brevo envoyé à %s pour créneau %s",
                    jury.email,
                    slot.id,
                )
                return True
            logging.error(result["message"])
            return False

        if not self.client:
            logging.warning(
                "SENDGRID_API_KEY non configurée; disponibilité non envoyée à %s",
                jury.email,
            )
            return False

        message = Mail(
            from_email=Email(self.from_email, "Orange Digital Center"),
            to_emails=To(jury.email),
            subject=f"Disponibilité jury - {slot.label}",
            html_content=Content("text/html", html_content),
        )

        try:
            response = self.client.send(message)
            if response.status_code in {200, 201, 202}:
                logging.info(
                    "Email disponibilité envoyé à %s pour créneau %s",
                    jury.email,
                    slot.id,
                )
                return True
            logging.error(
                "Erreur SendGrid disponibilité %s: statut %s - %s",
                jury.email,
                response.status_code,
                sendgrid_response_detail(response),
            )
        except Exception as error:
            logging.exception(
                "Erreur d'envoi disponibilité à %s: %s",
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

    def _availability_link(self, token, response):
        return (
            f"{self.api_public_url}/api/interviews/availability/"
            f"{token}?response={response}"
        )

    @staticmethod
    def _build_html(jury, slot, roles, available_link, unavailable_link):
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
          <h2>Confirmation de disponibilité</h2>
          <p>Bonjour {jury_name},</p>
          <p>Vous avez été affecté(e) à un créneau d'entretien.</p>
          <ul>
            <li><strong>Créneau :</strong> {escape(slot.label or "-")}</li>
            <li><strong>Date :</strong> {escape(start_at)} - {escape(end_at)}</li>
            <li><strong>Rôle :</strong> {escape(role_text or "-")}</li>
          </ul>
          <p>Merci de confirmer rapidement votre disponibilité.</p>
          <p>
            <a href="{escape(available_link)}"
               style="display:inline-block;padding:10px 14px;background:#16a34a;color:white;text-decoration:none;border-radius:6px;margin-right:8px">
              Je suis disponible
            </a>
            <a href="{escape(unavailable_link)}"
               style="display:inline-block;padding:10px 14px;background:#dc2626;color:white;text-decoration:none;border-radius:6px">
              Je ne suis pas disponible
            </a>
          </p>
          <p style="font-size:12px;color:#6b7280">Email automatique Orange Digital Center Sénégal.</p>
        </div>
        """
