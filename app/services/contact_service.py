"""Contact email preparation and delivery."""

from html import escape
import os

from app.services.email_transport import EmailTransport


class ContactService:
    def send(self, data):
        data = data or {}
        recipient_email = os.getenv(
            "CONTACT_RECIPIENT_EMAIL",
            "thiernohamidou.balde@orange-sonatel.com",
        )
        result = EmailTransport().send_html(
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

    @staticmethod
    def _build_html(data):
        data = {key: escape(str(value or "")) for key, value in data.items()}
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
