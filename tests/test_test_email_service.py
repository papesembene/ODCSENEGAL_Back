import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.services.email_templates.test_invitation import (
    build_test_invitation_html,
)
from app.services.test_email_service import TestEmailService


class TestEmailServiceTest(unittest.TestCase):
    def test_bulk_invitations_use_brevo_without_sendgrid(self):
        with patch.dict(os.environ, {
            "BREVO_API_KEY": "test-brevo-key",
            "BREVO_FROM_EMAIL": "sender@example.com",
        }, clear=True):
            service = TestEmailService()
        service.delivery.send_html = Mock(return_value={"sent": True})
        candidate = SimpleNamespace(
            email="candidate@example.com",
            first_name="Test",
            last_name="Candidate",
            phone="771234567",
        )

        result = service.send_bulk_invitations(
            [candidate], "Test", "25/06/2026", "10:00", 60,
            "http://localhost:3001/test/test-1",
        )

        self.assertIsNone(service.client)
        self.assertTrue(result["success"])
        self.assertEqual(result["sent"], 1)
        service.delivery.send_html.assert_called_once()
        self.assertIn(
            "http://localhost:3001/test/test-1",
            service.delivery.send_html.call_args.kwargs["html"],
        )

    def test_brevo_failure_is_reported_without_a_second_send(self):
        client = Mock()
        with patch.dict(os.environ, {
            "BREVO_API_KEY": "test-brevo-key",
            "BREVO_FROM_EMAIL": "sender@example.com",
        }, clear=True):
            service = TestEmailService(client=client)
        service.delivery.send_html = Mock(return_value={
            "sent": False,
            "message": "Provider rejected the email",
        })

        delivered = service.send_test_invitation(
            "candidate@example.com", "Test Candidate", "771234567",
            "Test", "25/06/2026", "10:00", 60,
            "http://localhost:3001/test/test-1",
        )

        self.assertFalse(delivered)
        service.delivery.send_html.assert_called_once()
        client.send.assert_not_called()

    def test_bulk_invitations_fail_without_an_email_provider(self):
        with patch.dict(os.environ, {}, clear=True):
            service = TestEmailService()
        service.delivery.send_html = Mock()

        result = service.send_bulk_invitations(
            [SimpleNamespace(email="candidate@example.com")],
            "Test", "25/06/2026", "10:00", 60,
            "http://localhost:3001/test/test-1",
        )

        self.assertFalse(result["success"])
        self.assertEqual(result["failed"], 1)
        service.delivery.send_html.assert_not_called()

    def test_template_escapes_candidate_values(self):
        html = build_test_invitation_html(
            candidate_email="test@example.com",
            candidate_name="<script>alert(1)</script>",
            candidate_phone="771234567",
            candidate_gender="femme",
            test_title="Test JS",
            test_date="25/06/2026",
            test_time="10:00",
            test_duration=60,
            test_link="https://example.com/test",
        )

        self.assertNotIn("<script>", html)
        self.assertIn("inscrite", html)

    def test_bulk_result_tracks_failed_addresses(self):
        client = Mock()
        service = TestEmailService(client=client)
        service.sendgrid_api_key = "configured"
        service.send_test_invitation = Mock(side_effect=[True, False])
        candidates = [
            SimpleNamespace(
                email="one@example.com",
                first_name="One",
                last_name="Candidate",
                phone="1",
                gender=None,
            ),
            SimpleNamespace(
                email="two@example.com",
                first_name="Two",
                last_name="Candidate",
                phone="2",
                gender=None,
            ),
        ]

        result = service.send_bulk_invitations(
            candidates,
            "Test",
            "25/06/2026",
            "10:00",
            60,
            "https://example.com/test",
        )

        self.assertEqual(result["sent"], 1)
        self.assertEqual(result["failed_emails"], ["two@example.com"])


if __name__ == "__main__":
    unittest.main()
