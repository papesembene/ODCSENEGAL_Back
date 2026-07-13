"""SendGrid transport for online-test invitations."""

import logging
import os

import certifi
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Content, Email, Mail, To

from app.services.email_templates.test_invitation import (
    build_test_invitation_html,
)
from app.services.sendgrid_helpers import (
    sendgrid_error_detail,
    sendgrid_response_detail,
)


os.environ.setdefault("SSL_CERT_FILE", certifi.where())


class TestEmailService:
    def __init__(self, client=None):
        self.sendgrid_api_key = os.getenv("SENDGRID_API_KEY")
        self.from_email = os.getenv(
            "SENDGRID_FROM_EMAIL",
            "orangedigitalcenter@orange-sonatel.com",
        )
        self.frontend_url = os.getenv(
            "FRONTEND_URL",
            "https://orangedigitalcenter.sn",
        )
        self.client = client or (
            SendGridAPIClient(self.sendgrid_api_key)
            if self.sendgrid_api_key
            else None
        )
        if not self.sendgrid_api_key:
            logging.warning(
                "SENDGRID_API_KEY non configurée; emails désactivés."
            )

    def send_test_invitation(
        self,
        candidate_email,
        candidate_name,
        candidate_phone,
        test_title,
        test_date,
        test_time,
        test_duration,
        test_link,
        candidate_gender=None,
    ):
        if not self.client:
            logging.error(
                "SendGrid non configuré; email non envoyé à %s",
                candidate_email,
            )
            return False
        html_content = build_test_invitation_html(
            candidate_email=candidate_email,
            candidate_name=candidate_name,
            candidate_phone=candidate_phone,
            candidate_gender=candidate_gender,
            test_title=test_title,
            test_date=test_date,
            test_time=test_time,
            test_duration=test_duration,
            test_link=test_link,
        )
        message = Mail(
            from_email=Email(
                self.from_email,
                "Orange Digital Center",
            ),
            to_emails=To(candidate_email),
            subject=f"Invitation au test - {test_title}",
            html_content=Content("text/html", html_content),
        )
        try:
            response = self.client.send(message)
            if response.status_code in {200, 201, 202}:
                logging.info("Email envoyé à %s", candidate_email)
                return True
            logging.error(
                "Erreur SendGrid pour %s: statut %s - %s",
                candidate_email,
                response.status_code,
                sendgrid_response_detail(response),
            )
        except Exception as error:
            logging.exception(
                "Erreur d'envoi à %s: %s",
                candidate_email,
                sendgrid_error_detail(error),
            )
        return False

    def send_bulk_invitations(
        self,
        candidates,
        test_title,
        test_date,
        test_time,
        test_duration,
        test_link,
    ):
        candidates = list(candidates or [])
        if not self.client:
            return {
                "success": False,
                "error": "SENDGRID_API_KEY non configurée",
                "sent": 0,
                "failed": len(candidates),
                "failed_emails": [],
                "total": len(candidates),
            }
        failed_emails = []
        sent = 0
        for candidate in candidates:
            email = getattr(candidate, "email", "")
            try:
                delivered = self.send_test_invitation(
                    candidate_email=email,
                    candidate_name=(
                        f"{candidate.first_name} {candidate.last_name}"
                    ),
                    candidate_phone=getattr(
                        candidate,
                        "phone",
                        "Non renseigné",
                    ),
                    candidate_gender=getattr(candidate, "gender", None),
                    test_title=test_title,
                    test_date=test_date,
                    test_time=test_time,
                    test_duration=test_duration,
                    test_link=test_link,
                )
            except Exception:
                logging.exception(
                    "Erreur inattendue pour le candidat %s",
                    email or "inconnu",
                )
                delivered = False
            if delivered:
                sent += 1
            else:
                failed_emails.append(email)
        failed = len(failed_emails)
        return {
            "success": failed == 0,
            "sent": sent,
            "failed": failed,
            "failed_emails": failed_emails,
            "total": len(candidates),
        }
