import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from app.services.email_templates.test_invitation import (
    build_test_invitation_html,
)
from app.services.test_email_service import TestEmailService


class TestEmailServiceTest(unittest.TestCase):
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
