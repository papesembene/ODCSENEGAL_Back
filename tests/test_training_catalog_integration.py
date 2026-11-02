"""Opt-in persistence tests against a disposable localhost database, never .env."""

import os
import unittest
from uuid import uuid4

from flask import Flask
from mongoengine import connect, disconnect

from app.models.training import Training
from app.services.interviews.management_service import InterviewManagementService
from app.services.tests.formation_catalog import formation_aliases, normalize_formation
from app.services.trainings.catalog import get_catalog, invalidate_catalog, require_training
from app.services.trainings.schema import TrainingCatalogError
from app.services.trainings.service import TrainingCatalogService


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
        Training.drop_collection()
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


if __name__ == "__main__":
    unittest.main()
