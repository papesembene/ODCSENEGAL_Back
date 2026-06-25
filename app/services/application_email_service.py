"""Shared Flask-Mail sender for startup program applications."""

from html import escape
import logging

from flask import current_app
from flask_mail import Mail, Message


logger = logging.getLogger(__name__)


class ApplicationEmailService:
    program_name = "Programme"
    contact_email = "contact@orangedigitalcenter.sn"
    reply_to = "noreply@orangedigitalcenter.sn"

    def __init__(self, app=None):
        self.mail = None
        if app is not None:
            self.init_app(app)

    def init_app(self, app):
        self.mail = Mail(app)

    def send_confirmation_email(self, candidate_data):
        return self._send(
            subject=(
                f"Confirmation de votre candidature {self.program_name}"
            ),
            recipients=[candidate_data["email"]],
            html=self._confirmation_html(candidate_data),
            reply_to=self.reply_to,
        )

    def send_admin_notification(self, candidate_data):
        sender = current_app.config.get("MAIL_DEFAULT_SENDER")
        recipient = current_app.config.get("ADMIN_EMAIL") or sender
        if not recipient:
            logger.warning(
                "Notification %s ignorée: ADMIN_EMAIL absent",
                self.program_name,
            )
            return False
        return self._send(
            subject=(
                f"Nouvelle candidature {self.program_name} - "
                f"{candidate_data.get('companyName', 'N/A')}"
            ),
            recipients=[recipient],
            html=self._admin_html(candidate_data),
        )

    def _send(self, subject, recipients, html, reply_to=None):
        if not self.mail:
            logger.warning(
                "Email %s ignoré: service mail non initialisé",
                self.program_name,
            )
            return False
        sender = current_app.config.get("MAIL_DEFAULT_SENDER")
        if not sender:
            logger.warning(
                "Email %s ignoré: MAIL_DEFAULT_SENDER absent",
                self.program_name,
            )
            return False
        try:
            message = Message(
                subject=subject,
                recipients=recipients,
                html=html,
                sender=sender,
                reply_to=reply_to,
            )
            message.extra_headers = {
                "Auto-Submitted": "auto-generated",
                "X-Auto-Response-Suppress": "All",
                "Precedence": "bulk",
            }
            self.mail.send(message)
            return True
        except Exception:
            logger.exception(
                "Échec d'envoi email %s",
                self.program_name,
            )
            return False

    def _confirmation_html(self, data):
        values = self._values(data)
        return self._layout(
            f"""
            <h1>Candidature {escape(self.program_name)}</h1>
            <p>Bonjour <strong>{values['name']}</strong>,</p>
            <p>Votre candidature a bien été reçue.</p>
            <div class="box">
              <p><strong>Entreprise :</strong> {values['company']}</p>
              <p><strong>Secteur :</strong> {values['sector']}</p>
              <p><strong>Produit :</strong> {values['product']}</p>
              <p><strong>Date :</strong> {values['date']}</p>
            </div>
            <p>Notre équipe examinera votre dossier et vous contactera
            pour la suite du processus.</p>
            <p>Contact : {escape(self.contact_email)}</p>
            """
        )

    def _admin_html(self, data):
        values = self._values(data)
        return self._layout(
            f"""
            <h1>Nouvelle candidature {escape(self.program_name)}</h1>
            <div class="box">
              <p><strong>Candidat :</strong> {values['name']}</p>
              <p><strong>Email :</strong> {values['email']}</p>
              <p><strong>Entreprise :</strong> {values['company']}</p>
              <p><strong>Secteur :</strong> {values['sector']}</p>
              <p><strong>Produit :</strong> {values['product']}</p>
              <p><strong>Date :</strong> {values['date']}</p>
            </div>
            """
        )

    @staticmethod
    def _values(data):
        created_at = data.get("created_at")
        return {
            "name": escape(
                f"{data.get('firstName', '')} "
                f"{data.get('lastName', '')}".strip()
            ),
            "email": escape(str(data.get("email", ""))),
            "company": escape(str(data.get("companyName", ""))),
            "sector": escape(str(data.get("sector", ""))),
            "product": escape(str(data.get("productName", ""))),
            "date": (
                created_at.strftime("%d/%m/%Y à %H:%M")
                if created_at
                else ""
            ),
        }

    @staticmethod
    def _layout(content):
        return f"""<!DOCTYPE html>
        <html lang="fr"><head><meta charset="UTF-8">
        <style>
          body {{ font-family:Arial,sans-serif; color:#333; }}
          main {{ max-width:600px; margin:auto; padding:24px; }}
          h1 {{ color:#f16e00; }}
          .box {{ border-left:4px solid #f16e00; padding:12px 18px;
            background:#f7f7f7; }}
        </style></head><body><main>{content}</main></body></html>"""
