"""Orange Fab email compatibility adapter."""

from app.services.application_email_service import ApplicationEmailService


class EmailService(ApplicationEmailService):
    program_name = "Orange Fab"
    contact_email = "contact@orangefab.sn"
    reply_to = "noreply@orangefab.sn"
