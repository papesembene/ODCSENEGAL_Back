"""Startup Lab email compatibility adapter."""

from app.services.application_email_service import ApplicationEmailService


class StartupEmailService(ApplicationEmailService):
    program_name = "Startup Lab"
    contact_email = "startuplab@contact.sn"
    reply_to = "noreply@startuplab.sn"
