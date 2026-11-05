"""Synthetic admissions and policy tests, without real candidates or email."""

import unittest
from unittest.mock import patch

from flask import Flask

from app.routes.candidature_routes import candidature_public_bp
from app.services.candidatures.service import CandidatureService, CandidatureServiceError
from app.services.trainings.catalog import DEFAULT_TRAININGS, get_catalog, invalidate_catalog
from app.services.trainings.regional_eligibility import APPLICATION_REGIONS, canonical_region, is_training_allowed
from app.services.trainings.schema import TrainingCatalogError
from app.services.trainings.service import TrainingCatalogService
from tests import test_candidature_service as candidature_fixtures
from tests.test_training_catalog import MemoryTrainings


class RegionalCandidatureTest(unittest.TestCase):
    def setUp(self):
        self.repository = candidature_fixtures.FakeRepository()
        self.service = CandidatureService(repository=self.repository, campaign_service=candidature_fixtures.FakeCampaignService())
        self.catalog_repository = MemoryTrainings()
        self.catalog = TrainingCatalogService(self.catalog_repository)

    def test_thies_and_diamniadio_only_allow_data_not_the_separate_ai_course(self):
        for region in ("Thiès", "THIES", "  Thiès ", "Diamniadio"):
            with self.subTest(region=region):
                available = [row["code"] for row in DEFAULT_TRAININGS if is_training_allowed(row, region)]
                self.assertEqual(["dev-data"], available)

    def test_tamba_only_allows_referent_and_published_fibre_if_it_exists(self):
        self.assertEqual(["referent-digital"], [row["code"] for row in DEFAULT_TRAININGS if is_training_allowed(row, "Tamba")])
        fibre = self.catalog.create({"title": "Fibre", "durationMonths": 3, "status": "published",
            "applicationRegionMode": "selected", "applicationRegions": ["Tambacounda"]})
        self.assertEqual(["Tambacounda"], fibre["applicationRegions"])
        self.assertTrue(is_training_allowed(fibre, "tambacounda"))
        self.assertFalse(is_training_allowed(fibre, "Thiès"))

    def test_other_regions_keep_all_existing_offers(self):
        for region in ("Dakar", "Kolda", "Saint-Louis", "Ziguinchor", "Matam"):
            self.assertTrue(all(is_training_allowed(row, region) for row in DEFAULT_TRAININGS))

    def test_missing_and_unknown_regions_cannot_bypass_restrictions(self):
        for region in ("", None, {}, "Thiès autre", "Atlantis"):
            self.assertFalse(is_training_allowed(DEFAULT_TRAININGS[0], region))
        self.assertEqual("Tambacounda", canonical_region(" TAMBA "))

    def test_restricted_pair_rejected_before_any_candidate_write(self):
        payload = {**candidature_fixtures.CandidatureServiceTest._valid_payload(), "region_of_residence": "Thiès"}
        with self.assertRaisesRegex(CandidatureServiceError, "région"):
            self.service.submit(payload)
        self.assertIsNone(self.repository.created)

    def test_authorized_pair_is_saved_with_normalized_residence(self):
        payload = {**candidature_fixtures.CandidatureServiceTest._valid_payload(), "region_of_residence": " thies ", "desired_training": "dev-data"}
        candidate = self.service.submit(payload)
        self.assertEqual("Thiès", candidate.region_of_residence)
        self.assertEqual("dev-data", candidate.desired_training)

    def test_admin_can_restrict_web_to_dakar_then_allow_every_residence(self):
        row = self.catalog.update("dev-web-mobile", {"version": 0,
            "applicationRegionMode": "selected", "applicationRegions": [" dakar "]})
        self.assertEqual(["Dakar"], row["applicationRegions"])
        self.assertEqual(["Dakar"], [region for region in APPLICATION_REGIONS if is_training_allowed(row, region)])
        renamed = self.catalog.update(row["code"], {"version": 1, "title": "Web avancé"})
        self.assertEqual(["Dakar"], renamed["applicationRegions"])
        opened = self.catalog.update(row["code"], {"version": 2, "applicationRegionMode": "all"})
        self.assertEqual([], opened["applicationRegions"])
        self.assertTrue(all(is_training_allowed(opened, region) for region in APPLICATION_REGIONS))

    def test_new_courses_use_an_explicit_policy_not_name_based_exceptions(self):
        fibre = self.catalog.create({"title": "Fibre", "durationMonths": 3})
        self.assertEqual("all", fibre["applicationRegionMode"])
        self.assertTrue(all(is_training_allowed(fibre, region) for region in APPLICATION_REGIONS))
        local = self.catalog.create({"title": "Data locale", "durationMonths": 3,
            "applicationRegionMode": "selected", "applicationRegions": ["Matam", "Tamba"]})
        self.assertEqual(["Matam", "Tambacounda"], local["applicationRegions"])
        self.assertFalse(is_training_allowed(local, "Dakar"))

    def test_invalid_assignment_payloads_are_not_accepted(self):
        for values in (None, "Thiès", ["Lieu inconnu"], [{}], [], ["Thiès"] * 16):
            with self.subTest(values=values), self.assertRaises(TrainingCatalogError):
                self.catalog.update("dev-data", {"version": 0, "applicationRegionMode": "selected", "applicationRegions": values})
        for mode in (None, {}, "specific", 1):
            with self.subTest(mode=mode), self.assertRaises(TrainingCatalogError):
                self.catalog.update("dev-data", {"version": 0, "applicationRegionMode": mode})

    def test_legacy_training_documents_receive_defaults_without_seed_writes(self):
        legacy = {**DEFAULT_TRAININGS[1]}
        legacy.pop("applicationRegions")
        legacy.pop("applicationRegionMode")
        self.catalog_repository.rows[legacy["code"]] = legacy
        restored = next(row for row in self.catalog.list() if row["code"] == legacy["code"])
        self.assertEqual(DEFAULT_TRAININGS[1]["applicationRegions"], restored["applicationRegions"])
        self.assertNotIn("applicationRegions", self.catalog_repository.rows[legacy["code"]])
        self.assertNotIn("applicationRegionMode", self.catalog_repository.rows[legacy["code"]])

    def test_an_old_admin_form_cannot_silently_replace_a_complete_policy_with_partial_exceptions(self):
        with self.assertRaisesRegex(TrainingCatalogError, "Actualisez"):
            self.catalog.update("dev-data", {"version": 0, "applicationRegions": ["Thiès"]})
        self.assertEqual({}, self.catalog_repository.rows)

    def test_existing_partial_overrides_keep_exactly_the_same_eligibility(self):
        legacy = {**DEFAULT_TRAININGS[0], "applicationRegions": ["Thiès"]}
        legacy.pop("applicationRegionMode")
        self.catalog_repository.rows[legacy["code"]] = legacy
        restored = next(row for row in self.catalog.list() if row["code"] == legacy["code"])
        expected = [region for region in APPLICATION_REGIONS if region not in {"Diamniadio", "Tambacounda"}]
        self.assertEqual(expected, restored["applicationRegions"])
        saved = self.catalog.update(legacy["code"], {"version": 0, "description": "Même offre"})
        self.assertEqual(expected, saved["applicationRegions"])
        self.assertEqual("selected", saved["applicationRegionMode"])

    def test_public_post_cannot_bypass_selection_by_manually_sending_another_code(self):
        self.catalog.update("dev-web-mobile", {"version": 0,
            "applicationRegionMode": "selected", "applicationRegions": ["Dakar"]})
        app = Flask(__name__)
        app.register_blueprint(candidature_public_bp, url_prefix="/api/candidature")
        client = app.test_client()
        with patch("app.routes.candidature_routes.candidature_service", self.service), \
             patch("app.routes.candidature_routes.is_request_rate_limited", return_value=False), \
             patch("app.repositories.training_repository.TrainingRepository", return_value=self.catalog_repository):
            response = client.post("/api/candidature/apply", json={**candidature_fixtures.CandidatureServiceTest._valid_payload(),
                "region_of_residence": "Diourbel", "desired_training": "dev-web-mobile"})
        self.assertEqual(400, response.status_code)
        self.assertIn("région", response.json["error"])
        self.assertIsNone(self.repository.created)


if __name__ == "__main__":
    unittest.main()
