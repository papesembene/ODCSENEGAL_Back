import os
import unittest
from uuid import uuid4

from mongoengine import connect, disconnect

from app.models.candidature_campaign import CandidatureCampaign
from app.services.candidatures.campaign_service import CandidatureCampaignService, CandidatureCampaignServiceError


def payload(title, formation="all", start="2035-01-10T08:00", end="2035-01-20T18:00", status="published"):
    return {"title": title, "formation": formation, "start_at": start, "end_at": end, "status": status}


@unittest.skipUnless(os.getenv("TEST_LOCAL_MONGO") == "1", "requires local MongoDB")
class CampaignOverlapTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db_name = "odc_campaign_overlap_test_" + uuid4().hex
        cls.addClassCleanup(disconnect)
        connection = connect(cls.db_name, host=os.getenv("TEST_INTERVIEW_MONGO_URI", "mongodb://127.0.0.1:27017"),
                             serverSelectionTimeoutMS=3000)
        connection.admin.command("ping")
        cls.addClassCleanup(connection.drop_database, cls.db_name)

    def setUp(self):
        CandidatureCampaign.drop_collection()
        self.service = CandidatureCampaignService()

    def test_two_published_campaigns_cannot_cover_the_same_formation_at_the_same_time(self):
        first = self.service.create(payload("Promo 1"))
        with self.assertRaisesRegex(CandidatureCampaignServiceError, "Promo 1") as raised:
            self.service.create(payload("Promo 2", start="2035-01-15T08:00", end="2035-02-01T18:00"))
        self.assertEqual(409, raised.exception.status_code)
        with self.assertRaises(CandidatureCampaignServiceError):
            self.service.create(payload("Web seulement", formation="dev-web-mobile"))

    def test_drafts_back_to_back_dates_and_other_formations_are_allowed(self):
        self.service.create(payload("Web", formation="dev-web-mobile"))
        self.service.create(payload("Data", formation="dev-data"))
        self.service.create(payload("Brouillon", status="draft"))
        self.service.create(payload("Suivante", formation="dev-web-mobile", start="2035-01-20T18:00", end="2035-02-01T18:00"))
        self.assertEqual(4, CandidatureCampaign.objects.count())

    def test_republishing_or_editing_into_an_overlap_is_refused(self):
        published = self.service.create(payload("Promo 1"))
        draft = self.service.create(payload("Promo 2", status="draft", start="2035-03-01T08:00", end="2035-03-10T08:00"))
        self.service.update(draft["id"], {"status": "published"})
        with self.assertRaisesRegex(CandidatureCampaignServiceError, "Promo 1"):
            self.service.update(draft["id"], {"start_at": "2035-01-18T08:00"})
        archived = self.service.create(payload("Ancienne", status="archived"))
        with self.assertRaisesRegex(CandidatureCampaignServiceError, "Promo 1"):
            self.service.update(archived["id"], {"status": "published"})
        self.service.update(published["id"], {"title": "Promo 1 renommée"})
        self.service.update(published["id"], {"status": "archived"})
        self.service.update(archived["id"], {"status": "published"})


if __name__ == "__main__":
    unittest.main()
