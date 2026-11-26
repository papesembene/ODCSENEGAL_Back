import unittest
from datetime import date, datetime
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

    def test_linked_campaign_plans_only_eligible_candidates_without_test_results(self):
        eligible = SimpleNamespace(status="pending", date_of_birth=date(2000, 6, 24), created_at=datetime(2026, 6, 24))
        underage = SimpleNamespace(status="pending", date_of_birth=date(2010, 6, 24), created_at=eligible.created_at)
        rejected = SimpleNamespace(status="rejected", date_of_birth=eligible.date_of_birth, created_at=eligible.created_at)
        campaign = SimpleNamespace(candidature_campaign_id="source-id", scorecard_config={})
        service = InterviewEvaluationService()
        module = "app.services.interviews.evaluation_service"

        with (
            patch(f"{module}.InterviewCampaign.objects", return_value=Mock(first=Mock(return_value=campaign))),
            patch(f"{module}.InterviewEvaluation.objects", return_value=[]),
            patch(f"{module}.is_scorecard_ready", return_value=True),
            patch(f"{module}.require_training", return_value={"level": "Âgé de 18 à 35 ans"}),
            patch.object(service, "_planning_slots", return_value=[SimpleNamespace(id="slot-id")]),
            patch.object(service, "_planning_candidates", return_value=[eligible, underage, rejected]),
            patch.object(service, "_admitted_emails") as test_lookup,
            patch.object(service, "_plan_candidate") as plan_candidate,
        ):
            counts = service.seed({"campaign_id": "interview-id", "formation": "data"})

        test_lookup.assert_not_called()
        plan_candidate.assert_called_once()
        self.assertIs(eligible, plan_candidate.call_args.args[1])
        self.assertEqual(1, counts["eligible_candidates"])
        self.assertEqual(2, counts["not_admitted"])

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
