"""Email notifications for interview jury assignments."""

from html import escape
from app.services.email_transport import EmailTransport


class InterviewAvailabilityEmailService:
    def __init__(self, client=None):
        self.delivery = EmailTransport(sendgrid_client=client)

    def send_availability_request(self, jury, slot, roles, token=None):
        result = self.delivery.send_html(
            recipients=[{"email": jury.email, "name": self._jury_name(jury)}],
            subject=f"Affectation entretien - {slot.label}",
            html=self._build_html(jury, slot, roles),
        )
        return result["sent"]

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
