"""Online-test invitation templates and delivery results."""

import logging
from app.services.email_transport import EmailTransport
from app.services.email_templates.test_invitation import build_test_invitation_html


class TestEmailService:
    def __init__(self, client=None):
        self.delivery = EmailTransport(sendgrid_client=client)
        self.client = self.delivery.sendgrid

    @property
    def is_configured(self):
        return self.delivery.is_configured

    def send_test_invitation(
        self, candidate_email, candidate_name, candidate_phone,
        test_title, test_date, test_time, test_duration, test_link,
        candidate_gender=None,
    ):
        result = self.delivery.send_html(
            recipients=[{"email": candidate_email, "name": candidate_name}],
            subject=f"Invitation au test - {test_title}",
            html=build_test_invitation_html(
                candidate_email=candidate_email, candidate_name=candidate_name,
                candidate_phone=candidate_phone, candidate_gender=candidate_gender,
                test_title=test_title, test_date=test_date, test_time=test_time,
                test_duration=test_duration, test_link=test_link,
            ),
        )
        if not result["sent"]:
            logging.warning(result["message"])
        return result["sent"]

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
        if not self.is_configured:
            return {
                "success": False,
                "error": "Aucun service email configure (Brevo, SendGrid ou SMTP)",
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
