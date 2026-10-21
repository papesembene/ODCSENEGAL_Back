"""Email notifications for administrator and jury credentials."""

import os
from html import escape
from app.services.email_transport import EmailTransport


class AdminCredentialsEmailService:
    def __init__(self, client=None):
        self.delivery = EmailTransport(sendgrid_client=client)
        self.frontend_url = os.getenv("FRONTEND_URL", "https://orangedigitalcenter.sn").rstrip("/")

    def send_credentials(self, user, temporary_password, role_label):
        return self.delivery.send_html(
            recipients=[{"email": user.email, "name": self._display_name(user)}],
            subject="Vos accès jury - Orange Digital Center Sénégal",
            html=self._build_html(user, temporary_password, role_label),
        )

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
