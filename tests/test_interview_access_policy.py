import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

from app.services.interviews.access_policy import (
    editable_roles, filter_window_open, slot_roles, utc_iso,
)
from app.services.interviews.evaluation_service import InterviewEvaluationService
from app.services.interviews.exceptions import InterviewForbiddenError


class InterviewAccessPolicyTest(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 19, 12)
        self.admin = SimpleNamespace(id="jury-1", first_name="Awa", last_name="Diop")
        self.slot = SimpleNamespace(
            assignments={}, assigned_filter_ids=["jury-1"],
            assigned_jury_ids=[], assigned_validator_ids=[], assigned_motivation_ids=[],
            start_at=self.now - timedelta(hours=1),
            end_at=self.now + timedelta(hours=1), status="scheduled",
        )

    def test_filter_window_includes_start_but_excludes_end(self):
        self.assertTrue(filter_window_open(self.slot, self.slot.start_at))
        self.assertFalse(filter_window_open(self.slot, self.slot.start_at - timedelta(microseconds=1)))
        self.assertFalse(filter_window_open(self.slot, self.slot.end_at))

    def test_closed_cancelled_or_missing_window_denies_filter(self):
        for status in ("completed", "cancelled"):
            self.slot.status = status
            self.assertEqual([], editable_roles(self.slot, self.admin, self.now))
        self.slot.status = "scheduled"
        self.slot.end_at = None
        self.assertFalse(filter_window_open(self.slot, self.now))

    def test_timezone_offsets_are_compared_in_utc(self):
        self.slot.start_at = datetime(2026, 10, 19, 13, tzinfo=timezone(timedelta(hours=2)))
        self.slot.end_at = datetime(2026, 10, 19, 15, tzinfo=timezone(timedelta(hours=2)))
        self.assertTrue(filter_window_open(self.slot, self.now))
        self.assertEqual("2026-10-19T13:00:00Z", utc_iso(self.slot.end_at))

    def test_validator_does_not_extend_filter_permission_on_same_slot(self):
        self.slot.assigned_validator_ids = ["jury-1"]
        self.assertEqual(["filter", "validator"], editable_roles(self.slot, self.admin, self.now))
        self.assertEqual(["validator"], editable_roles(self.slot, self.admin, self.slot.end_at))

    def test_role_is_slot_assignment_not_profile_default(self):
        self.slot.assignments = {"jury-1": ["validator"]}
        self.slot.assigned_filter_ids = []
        self.assertEqual(["validator"], slot_roles(self.slot, self.admin))
        self.slot.assignments = {}
        self.slot.assigned_jury_ids = ["jury-1"]
        self.assertEqual(["filter"], slot_roles(self.slot, self.admin))
        self.assertEqual([], slot_roles(None, self.admin))

    def test_filter_cannot_save_open_page_after_expiry(self):
        service = InterviewEvaluationService(now=lambda: self.slot.end_at)
        evaluation = SimpleNamespace(slot_id="slot-1", section_reviews={}, filter_review={})
        with patch("app.services.interviews.evaluation_service.InterviewSlot.objects") as objects:
            objects.return_value.first.return_value = self.slot
            with self.assertRaises(InterviewForbiddenError):
                service._update_member_review(evaluation, {"filter_review": {}}, self.admin, {})
        self.assertEqual({}, evaluation.filter_review)

    def test_validator_can_save_after_expiry(self):
        self.slot.assigned_validator_ids = ["jury-1"]
        service = InterviewEvaluationService(now=lambda: self.slot.end_at)
        evaluation = SimpleNamespace(slot_id="slot-1", section_reviews={}, validator_review={})
        with patch("app.services.interviews.evaluation_service.InterviewSlot.objects") as objects:
            objects.return_value.first.return_value = self.slot
            with patch("app.services.interviews.evaluation_service.sanitize_review", return_value={"comment": "OK"}):
                service._update_member_review(evaluation, {"validator_review": {"comment": "OK"}}, self.admin, {})
        self.assertEqual("jury-1", evaluation.validator_review["_owner_admin_id"])


if __name__ == "__main__":
    unittest.main()
