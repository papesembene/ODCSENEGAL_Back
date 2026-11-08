import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

from app.services.candidatures.campaign_service import (
    CandidatureCampaignService,
    CandidatureCampaignServiceError,
)


class FakeQuery:
    def __init__(self, campaigns):
        self.campaigns = campaigns

    def filter(self, **filters):
        campaigns = self.campaigns
        if "start_at__lte" in filters:
            campaigns = [
                campaign for campaign in campaigns
                if campaign.start_at <= filters["start_at__lte"]
            ]
        if "end_at__gte" in filters:
            campaigns = [
                campaign for campaign in campaigns
                if campaign.end_at >= filters["end_at__gte"]
            ]
        if "start_at__gt" in filters:
            campaigns = [
                campaign for campaign in campaigns
                if campaign.start_at > filters["start_at__gt"]
            ]
        if "end_at__lt" in filters:
            campaigns = [
                campaign for campaign in campaigns
                if campaign.end_at < filters["end_at__lt"]
            ]
        return FakeQuery(campaigns)

    def order_by(self, *fields):
        campaigns = self.campaigns
        for field in reversed(fields):
            campaigns = sorted(
                campaigns,
                key=lambda campaign: getattr(campaign, field.lstrip("-")),
                reverse=field.startswith("-"),
            )
        return FakeQuery(campaigns)

    def first(self):
        return self.campaigns[0] if self.campaigns else None


class CandidatureCampaignServiceTest(unittest.TestCase):
    def test_validate_rejects_inverted_dates(self):
        with self.assertRaisesRegex(
            CandidatureCampaignServiceError,
            "fermeture doit être après",
        ):
            CandidatureCampaignService._validate({
                "title": "Promotion 2026",
                "start_at": datetime(2026, 7, 10, 8),
                "end_at": datetime(2026, 7, 9, 18),
                "status": "published",
            })

    def test_public_status_is_open_for_current_campaign(self):
        service = CandidatureCampaignService()
        campaign = self._campaign(
            start_at=datetime(2026, 7, 1, 8),
            end_at=datetime(2026, 7, 20, 18),
        )

        with patch(
            "app.services.candidatures.campaign_service.datetime",
            SimpleNamespace(utcnow=lambda: datetime(2026, 7, 8, 10), fromisoformat=datetime.fromisoformat),
        ), patch(
            "app.services.candidatures.campaign_service.CandidatureCampaign.objects",
            return_value=FakeQuery([campaign]),
        ):
            status = service.get_public_status("dev-web-mobile")

        self.assertTrue(status["isOpen"])
        self.assertEqual("open", status["lifecycleStatus"])

    def test_public_status_uses_next_campaign_when_not_open_yet(self):
        service = CandidatureCampaignService()
        campaign = self._campaign(
            start_at=datetime(2026, 7, 15, 8),
            end_at=datetime(2026, 7, 20, 18),
        )

        with patch(
            "app.services.candidatures.campaign_service.datetime",
            SimpleNamespace(utcnow=lambda: datetime(2026, 7, 8, 10), fromisoformat=datetime.fromisoformat),
        ), patch(
            "app.services.candidatures.campaign_service.CandidatureCampaign.objects",
            return_value=FakeQuery([campaign]),
        ):
            status = service.get_public_status("dev-web-mobile")

        self.assertFalse(status["isOpen"])
        self.assertEqual("upcoming", status["lifecycleStatus"])
        self.assertEqual("Les candidatures ouvrent bientôt.", status["message"])

    def test_no_published_campaign_announces_opening_without_a_date(self):
        service = CandidatureCampaignService()
        with patch(
            "app.services.candidatures.campaign_service.CandidatureCampaign.objects",
            return_value=FakeQuery([]),
        ):
            status = service.get_public_status()
            with self.assertRaises(CandidatureCampaignServiceError) as raised:
                service.assert_open()

        self.assertFalse(status["isOpen"])
        self.assertEqual("upcoming", status["lifecycleStatus"])
        self.assertIsNone(status["campaign"])
        self.assertEqual("Les candidatures ouvrent bientôt.", status["message"])
        self.assertEqual(403, raised.exception.status_code)

    def test_expired_campaign_stays_closed_instead_of_announcing_a_new_opening(self):
        service = CandidatureCampaignService()
        old = self._campaign(datetime(2026, 5, 1), datetime(2026, 5, 20))
        recent = self._campaign(datetime(2026, 6, 1), datetime(2026, 6, 20))
        with patch(
            "app.services.candidatures.campaign_service.datetime",
            SimpleNamespace(utcnow=lambda: datetime(2026, 7, 8, 10)),
        ), patch(
            "app.services.candidatures.campaign_service.CandidatureCampaign.objects",
            return_value=FakeQuery([old, recent]),
        ):
            status = service.get_public_status()
            with self.assertRaises(CandidatureCampaignServiceError):
                service.assert_open()

        self.assertFalse(status["isOpen"])
        self.assertEqual("closed", status["lifecycleStatus"])
        self.assertEqual(recent.end_at.isoformat(), status["campaign"]["endAt"])

    def test_next_published_campaign_takes_priority_over_the_expired_one(self):
        old = self._campaign(datetime(2026, 6, 1), datetime(2026, 6, 20))
        upcoming = self._campaign(datetime(2026, 7, 15), datetime(2026, 7, 20))
        with patch(
            "app.services.candidatures.campaign_service.datetime",
            SimpleNamespace(utcnow=lambda: datetime(2026, 7, 8, 10)),
        ), patch(
            "app.services.candidatures.campaign_service.CandidatureCampaign.objects",
            return_value=FakeQuery([old, upcoming]),
        ):
            status = CandidatureCampaignService().get_public_status()

        self.assertEqual("upcoming", status["lifecycleStatus"])
        self.assertEqual(upcoming.start_at.isoformat(), status["campaign"]["startAt"])

    @staticmethod
    def _campaign(start_at, end_at):
        now = datetime(2026, 7, 8, 10)
        lifecycle = "upcoming" if start_at > now else "closed" if end_at < now else "open"
        return SimpleNamespace(
            id="campaign-id",
            title="Promotion 2026",
            promotion="Promotion 2026",
            formation="all",
            start_at=start_at,
            end_at=end_at,
            status="published",
            description="",
            created_by="",
            updated_by="",
            created_at=start_at,
            updated_at=start_at,
            lifecycle_status=lambda now=None: lifecycle,
            to_dict=lambda now=None: {
                "id": "campaign-id",
                "title": "Promotion 2026",
                "promotion": "Promotion 2026",
                "formation": "all",
                "startAt": start_at.isoformat(),
                "endAt": end_at.isoformat(),
                "status": "published",
                "lifecycleStatus": lifecycle,
                "isOpen": lifecycle == "open",
                "description": "",
            },
        )


if __name__ == "__main__":
    unittest.main()
