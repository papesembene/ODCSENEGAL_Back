import unittest
from types import SimpleNamespace

from app.services.interviews.evaluation_service import (
    InterviewEvaluationService,
)
from app.services.interviews.exceptions import InterviewForbiddenError


class InterviewEvaluationServiceTest(unittest.TestCase):
    def test_available_slot_respects_capacity(self):
        slots = [
            SimpleNamespace(id="one", capacity=1),
            SimpleNamespace(id="two", capacity=2),
        ]

        slot = InterviewEvaluationService._available_slot(
            slots,
            {"one": 1, "two": 0},
        )

        self.assertEqual(slot.id, "two")

    def test_member_cannot_edit_unassigned_evaluation(self):
        service = InterviewEvaluationService()
        evaluation = SimpleNamespace(slot_id=None)
        admin = SimpleNamespace(
            id="admin-id",
            profile_data={"interview_role": "filter"},
        )

        with self.assertRaises(InterviewForbiddenError):
            service._update_member_review(
                evaluation,
                {"filter_review": {}},
                admin,
                {},
            )


if __name__ == "__main__":
    unittest.main()
