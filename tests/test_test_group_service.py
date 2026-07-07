import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.services.tests.test_group_service import (
    TestGroupService,
    TestGroupServiceError,
)


class FakeGroupQuerySet(list):
    def only(self, *_fields):
        return self


class TestGroupServiceUnitTest(unittest.TestCase):
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
