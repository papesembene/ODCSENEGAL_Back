import unittest
from datetime import datetime
from types import SimpleNamespace

from app.services.interviews.exceptions import (
    InterviewConflictError,
    InterviewNotFoundError,
    InterviewValidationError,
)
from app.services.interviews.management_service import (
    InterviewManagementService,
)


FIXED_NOW = datetime(2026, 6, 24, 12, 0, 0)


class FakeInterviewRepository:
    def __init__(self):
        self.campaign = None
        self.slot = None
        self.has_evaluations = False

    def create_campaign(self, **values):
        self.campaign = SimpleNamespace(**values)
        return self.campaign

    def get_campaign(self, _campaign_id):
        return self.campaign

    def campaign_has_evaluations(self, _campaign_id):
        return self.has_evaluations

    def save_campaign(self, campaign):
        self.campaign = campaign
        return campaign

    def create_slot(self, **values):
        self.slot = SimpleNamespace(**values)
        return self.slot

    def get_slot(self, _slot_id):
        return self.slot

    def save_slot(self, slot):
        self.slot = slot
        return slot


class InterviewManagementServiceTest(unittest.TestCase):
    def setUp(self):
        self.repository = FakeInterviewRepository()
        self.service = InterviewManagementService(
            repository=self.repository,
            now=lambda: FIXED_NOW,
        )

    def test_create_campaign_preserves_expected_defaults(self):
        campaign = self.service.create_campaign({
            "name": " Campagne P8 ",
            "formation": "dev-web-mobile",
        })

        self.assertEqual("Campagne P8", campaign.name)
        self.assertEqual("draft", campaign.status)
        self.assertEqual(FIXED_NOW, campaign.updated_at)
        self.assertEqual(
            "excel",
            campaign.scorecard_config["source"],
        )

    def test_create_campaign_requires_name_and_formation(self):
        with self.assertRaisesRegex(
            InterviewValidationError,
            "name et formation",
        ):
            self.service.create_campaign({"name": ""})

    def test_update_campaign_blocks_scorecard_after_planning(self):
        self.repository.campaign = SimpleNamespace(
            name="P8",
            formation="dev-web-mobile",
            description="",
            status="draft",
            scorecard_config={},
        )
        self.repository.has_evaluations = True

        with self.assertRaises(InterviewConflictError):
            self.service.update_campaign(
                "campaign-id",
                {"scorecard_config": {"sections": {}}},
            )

    def test_create_slot_keeps_filter_and_legacy_jury_in_sync(self):
        slot = self.service.create_slot({
            "campaign_id": "campaign-id",
            "label": " Matin ",
            "formation": "dev-web-mobile",
            "start_at": "2026-06-24T09:00:00",
            "end_at": "2026-06-24T10:00:00",
            "assigned_filter_ids": ["jury-1"],
        })

        self.assertEqual(["jury-1"], slot.assigned_filter_ids)
        self.assertEqual(["jury-1"], slot.assigned_jury_ids)
        self.assertEqual(FIXED_NOW, slot.updated_at)

    def test_update_slot_rejects_missing_slot(self):
        with self.assertRaises(InterviewNotFoundError):
            self.service.update_slot("missing", {"capacity": 12})

    def test_invalid_date_has_stable_business_message(self):
        with self.assertRaisesRegex(
            InterviewValidationError,
            "start_at a un format invalide",
        ):
            self.service.create_slot({
                "campaign_id": "campaign-id",
                "label": "Matin",
                "formation": "dev-web-mobile",
                "start_at": "date-invalide",
                "end_at": "2026-06-24T10:00:00",
            })


if __name__ == "__main__":
    unittest.main()
