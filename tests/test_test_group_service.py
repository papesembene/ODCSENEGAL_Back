import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.services.tests.test_group_service import (
    TestGroupService,
    TestGroupServiceError,
)


class FakeGroupQuerySet(list):
    def only(self, *_fields):
        return self


class TestGroupServiceUnitTest(unittest.TestCase):
    def test_local_invitations_are_simulated_only_without_a_provider(self):
        module = "app.services.tests.test_group_service"
        for configured in (True, False):
            with self.subTest(email_provider_configured=configured):
                service = TestGroupService()
                group = SimpleNamespace(
                    test_id="test-1",
                    candidate_ids=["candidate-1"],
                    test_date=datetime(2026, 6, 25, 10),
                    duration=60,
                    status="pending",
                    save=Mock(),
                )
                email_service = SimpleNamespace(
                    sendgrid_api_key=None,
                    is_configured=configured,
                    send_bulk_invitations=Mock(return_value={
                        "success": True, "sent": 1, "failed": 0,
                    }),
                )
                with (
                    patch.object(service, "get_group", return_value=group),
                    patch(f"{module}.Test.objects") as tests,
                    patch(f"{module}.Candidature.objects", return_value=[
                        SimpleNamespace(email="candidate@example.com"),
                    ]),
                    patch(f"{module}.TestEmailService", return_value=email_service),
                ):
                    tests.return_value.first.return_value = SimpleNamespace(
                        id="test-1", title="Test",
                    )
                    result = service.send_invitations(
                        "group-1", "http://localhost:3001", simulate=True,
                    )

                self.assertEqual(result["status_code"], 200)
                self.assertEqual(
                    result["payload"]["data"].get("simulated", False),
                    not configured,
                )
                self.assertEqual(
                    email_service.send_bulk_invitations.call_count,
                    int(configured),
                )
                self.assertEqual(group.status, "scheduled")
                group.save.assert_called_once()

    def test_date_parser_accepts_iso(self):
        value = TestGroupService._parse_date(
            "2026-06-25T10:00:00Z",
        )
        self.assertEqual(10, value.hour)

    def test_date_parser_rejects_invalid_input(self):
        with self.assertRaises(TestGroupServiceError):
            TestGroupService._parse_date("invalid")

    def test_candidate_ids_are_deduplicated(self):
        self.assertEqual(
            ["candidate-1", "candidate-2"],
            TestGroupService._unique_candidate_ids([
                "candidate-1",
                "candidate-1",
                "candidate-2",
            ]),
        )

    def test_candidates_already_in_active_group_are_rejected(self):
        group = SimpleNamespace(
            id="group-1",
            name="Groupe Dev Web 1",
            candidate_ids=["candidate-1"],
        )

        with patch(
            "app.services.tests.test_group_service.TestGroup.objects",
            return_value=FakeGroupQuerySet([group]),
        ):
            with self.assertRaises(TestGroupServiceError) as context:
                TestGroupService._ensure_candidates_available(
                    candidate_ids=["candidate-1"],
                    formation="Dev Web",
                )

        self.assertEqual(409, context.exception.status_code)
        self.assertIn("déjà affecté", str(context.exception))

    def test_current_group_is_ignored_when_updating_candidates(self):
        group = SimpleNamespace(
            id="group-1",
            name="Groupe Dev Web 1",
            candidate_ids=["candidate-1"],
        )

        with patch(
            "app.services.tests.test_group_service.TestGroup.objects",
            return_value=FakeGroupQuerySet([group]),
        ):
            TestGroupService._ensure_candidates_available(
                candidate_ids=["candidate-1"],
                formation="Dev Web",
                current_group_id="group-1",
            )


if __name__ == "__main__":
    unittest.main()
