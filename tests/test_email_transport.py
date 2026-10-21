import os
import smtplib
import unittest
from unittest.mock import Mock, patch

from app.services.email_transport import EmailTransport
from app.services.contact_service import ContactService


class EmailTransportTest(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, {
            "EMAIL_PROVIDER": "smtp", "MAIL_SERVER": "relay.internal",
            "MAIL_DEFAULT_SENDER": "sender@example.org", "MAIL_USE_TLS": "true",
        }, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def test_smtp_uses_configured_host_tls_and_finite_timeout(self):
        with patch("app.services.email_transport.smtplib.SMTP") as smtp:
            server = smtp.return_value.__enter__.return_value
            server.send_message.return_value = {}
            result = EmailTransport().send_html(["recipient@example.org"], "Subject", "<p>OK</p>")
        self.assertTrue(result["sent"])
        smtp.assert_called_once_with("relay.internal", 587, timeout=15)
        server.starttls.assert_called_once()
        server.login.assert_not_called()

    def test_permanent_auth_failure_is_not_retried(self):
        with patch("app.services.email_transport.smtplib.SMTP", side_effect=smtplib.SMTPAuthenticationError(535, b"no")):
            result = EmailTransport().send_html(["recipient@example.org"], "Subject", "OK")
        self.assertFalse(result["sent"])
        self.assertFalse(result["retryable"])

    def test_network_failure_is_retryable(self):
        with patch("app.services.email_transport.smtplib.SMTP", side_effect=TimeoutError()):
            result = EmailTransport().send_html(["recipient@example.org"], "Subject", "OK")
        self.assertTrue(result["retryable"])

    def test_selected_provider_does_not_fall_back_to_old_sendgrid_key(self):
        os.environ["EMAIL_PROVIDER"] = "brevo"
        transport = EmailTransport(sendgrid_client=Mock())
        self.assertEqual("brevo", transport.selected_provider)
        self.assertFalse(transport.is_configured)
        transport.send_html(["recipient@example.org"], "Subject", "OK")
        transport.sendgrid.send.assert_not_called()

    def test_smtp_ssl_and_starttls_cannot_be_combined(self):
        os.environ["MAIL_USE_SSL"] = "true"
        with patch("app.services.email_transport.smtplib.SMTP") as smtp:
            result = EmailTransport().send_html(["recipient@example.org"], "Subject", "OK")
        self.assertFalse(result["retryable"])
        smtp.assert_not_called()

    def test_contact_html_escapes_user_input(self):
        html = ContactService._build_html({"name": '<script>alert("x")</script>', "message": "<img onerror=x>"})
        self.assertNotIn("<script>", html)
        self.assertNotIn("<img", html)
