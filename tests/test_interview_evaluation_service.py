import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.services.interviews.evaluation_service import (
    InterviewEvaluationService,
)
from app.services.interviews.exceptions import InterviewForbiddenError


class InterviewEvaluationServiceTest(unittest.TestCase):
    def test_available_slot_respects_planning_limit(self):
        slots = [
            SimpleNamespace(id="one"),
            SimpleNamespace(id="two"),
        ]

        slot = InterviewEvaluationService._available_slot(
            slots,
            {"one": 1, "two": 0},
            planning_limit=1,
        )

        self.assertEqual(slot.id, "two")

    def test_planning_limit_balances_candidates_across_slots(self):
        limit = InterviewEvaluationService._planning_limit(
            admitted_count=1000,
            slots_count=6,
        )

        self.assertEqual(limit, 167)

    def test_manual_planning_limit_overrides_automatic_limit(self):
        limit = InterviewEvaluationService._resolve_planning_limit(
            "50",
            admitted_count=1000,
            slots_count=6,
        )

        self.assertEqual(limit, 50)

    def test_planning_slots_do_not_require_all_jury_roles(self):
        slots = [
            SimpleNamespace(
                id="slot-1",
                assigned_filter_ids=[],
                assigned_validator_ids=["coach-1"],
                assigned_motivation_ids=[],
            )
        ]
        query = Mock()
        query.order_by.return_value = slots

        with patch(
            "app.services.interviews.evaluation_service.InterviewSlot.objects",
            return_value=query,
        ):
            result = InterviewEvaluationService._planning_slots(
                "campaign-1",
                "hackeuses",
            )

        self.assertEqual(["slot-1"], [slot.id for slot in result])
        query.order_by.assert_called_once_with("start_at")

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

    def test_requested_roles_use_submitted_review_sections(self):
        admin = SimpleNamespace(
            profile_data={"interview_role": "filter"},
        )

        roles = InterviewEvaluationService._requested_roles(
            {
                "filter_review": {"comment": "OK"},
                "validator_review": {"comment": "OK"},
            },
            admin,
        )

        self.assertEqual(["filter", "validator"], roles)


if __name__ == "__main__":
    unittest.main()
