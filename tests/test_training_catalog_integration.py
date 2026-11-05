"""Opt-in persistence tests against a disposable localhost database, never .env."""

import os
import unittest
from unittest.mock import patch
from uuid import uuid4

from flask import Flask
from mongoengine import connect, disconnect

from app.models.training import Training
from app.services.interviews.management_service import InterviewManagementService
from app.services.tests.formation_catalog import formation_aliases, normalize_formation
from app.services.trainings.catalog import get_catalog, invalidate_catalog, require_training
from app.services.trainings.schema import TrainingCatalogError
from app.services.trainings.service import TrainingCatalogService
from app.services.trainings.sites import TrainingSiteService, get_sites, invalidate_sites
from app.models.training_site import TrainingSite


@unittest.skipUnless(os.environ.get("TEST_TRAINING_MONGO") == "1", "requires isolated MongoDB on port 27027")
class TrainingPersistenceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db_name = "odc_training_test_" + uuid4().hex
        cls.addClassCleanup(disconnect)
        cls.connection = connect(cls.db_name, host="mongodb://127.0.0.1:27027", serverSelectionTimeoutMS=3000)
        cls.connection.admin.command("ping")
        cls.addClassCleanup(cls.connection.drop_database, cls.db_name)

    def setUp(self):
        self.connection[self.db_name].drop_collection("candidature")
        Training.drop_collection()
        TrainingSite.drop_collection()
        self.context = Flask(__name__).app_context()
        self.context.push()
        self.addCleanup(self.context.pop)
        self.service = TrainingCatalogService()

    def test_defaults_need_no_seed_and_archiving_does_not_remove_history(self):
        self.assertEqual(7, len(get_catalog()))
        self.assertEqual(0, Training.objects.count())
        candidates = self.connection[self.db_name]["candidature"]
        candidates.insert_one({"email": "history@example.org", "desired_training": "dev-web-mobile"})
        row = self.service.archive("dev-web-mobile", 0)
        self.assertEqual(1, row["version"])
        self.assertEqual("archived", get_catalog()[0]["status"])
        self.assertEqual(1, candidates.count_documents({}))
        with self.assertRaises(TrainingCatalogError):
            require_training("Dev Web", public=True)

    def test_rename_survives_cache_reload_and_old_filters_resolve(self):
        row = self.service.create({"title": "Robotique", "durationMonths": 7, "status": "published"})
        self.service.update(row["code"], {"version": 1, "title": "Systèmes robotisés"})
        invalidate_catalog()
        self.assertEqual("robotique", normalize_formation("Systèmes robotisés"))
        self.assertIn("Robotique", formation_aliases("robotique"))
        self.assertEqual("Systèmes robotisés", require_training("Robotique")["title"])
        campaign = InterviewManagementService().create_campaign({"name": "Robots 2027", "formation": row["code"]})
        self.assertEqual(row["code"], campaign.formation)
        self.assertEqual("custom", campaign.scorecard_config["source"])
        keys = {criterion["key"] for section in campaign.scorecard_config["sections"].values() for criterion in section["criteria"]}
        self.assertFalse(keys.intersection({"anti_cheat_score", "logic_score", "algorithm_logic_score"}),
                         "A new referential must not inherit business criteria from Dev Web")

    def test_atomic_repository_rejects_stale_edit_and_alias_collision(self):
        row = self.service.create({"title": "Robotique", "durationMonths": 3})
        old = dict(row)
        current = self.service.repository.save({**row, "title": "Robotique avancée"}, 1, "one@example.org")
        with self.assertRaises(TrainingCatalogError):
            self.service.repository.save({**old, "title": "Ancien nom"}, 1, "two@example.org")
        self.assertEqual("Robotique avancée", Training.objects.get(code=row["code"]).to_dict()["title"])
        with self.assertRaises(TrainingCatalogError):
            self.service.repository.save({**current, "code": "collision", "id": "collision"}, 0, "other@example.org")
        self.assertEqual(1, Training.objects.count())

    def test_draft_is_hidden_from_public_but_can_prepare_admin_workflows(self):
        self.service.create({"title": "Robotique", "durationMonths": 3, "status": "draft"})
        self.assertEqual("draft", require_training("robotique")["status"])
        with self.assertRaises(TrainingCatalogError):
            require_training("robotique", public=True)

    def test_site_assignments_survive_a_database_and_cache_reload(self):
        row = self.service.create({"title": "Fibre", "durationMonths": 3, "status": "published"})
        self.service.update(row["code"], {"version": 1, "siteIds": ["tambacounda"]})
        invalidate_catalog()
        reloaded = require_training("fibre", public=True)
        self.assertEqual(["tambacounda"], reloaded["siteIds"])
        self.assertEqual(1, Training.objects.count())

    def test_sites_can_be_created_renamed_archived_with_concurrency_control(self):
        sites = TrainingSiteService()
        site = sites.create({"name": "Saint-Louis"})
        self.assertEqual(1, TrainingSite.objects.count())
        sites.update(site["code"], {"version": 1, "name": "ODC Saint-Louis"})
        with self.assertRaises(TrainingCatalogError):
            sites.update(site["code"], {"version": 1, "status": "archived"})
        sites.update(site["code"], {"version": 2, "status": "archived"})
        invalidate_sites()
        self.assertEqual("archived", next(item for item in get_sites() if item["code"] == site["code"])["status"])

    def test_admission_persists_site_and_residence_separately_and_preserves_snapshot(self):
        from app.models.candidature import Candidature
        from app.services.candidatures.service import CandidatureService
        from tests.test_candidature_service import CandidatureServiceTest, FakeCampaignService
        Candidature.drop_collection()
        payload = {**CandidatureServiceTest._valid_payload(), "training_site": "thies",
                   "desired_training": "dev-data", "region_of_residence": "Diourbel"}
        with patch.dict(os.environ, {"EMAIL_DELIVERY_MODE": "disabled"}):
            saved = CandidatureService(campaign_service=FakeCampaignService()).submit(payload)
        sites = TrainingSiteService()
        sites.update("thies", {"version": 0, "name": "ODC Thiès", "status": "archived"})
        reloaded = Candidature.objects.get(id=saved.id)
        self.assertEqual("thies", reloaded.training_site)
        self.assertEqual("Thiès", reloaded.training_site_name)
        self.assertEqual("Diourbel", reloaded.region_of_residence)


if __name__ == "__main__":
    unittest.main()
