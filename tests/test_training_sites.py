"""Site choices are independent of residence; no real data or emails."""

import unittest
from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from flask import Flask

from app.routes.training_routes import training_bp
from app.routes.candidature_routes import candidature_public_bp
from app.services.trainings.sites import (
    DEFAULT_SITES,
    TrainingSiteService,
    site_application_open,
    validate_site,
    with_site_assignments,
)
from app.services.trainings.schema import TrainingCatalogError
from app.services.trainings.service import TrainingCatalogService
from app.services.trainings.catalog import DEFAULT_TRAININGS
from app.services.candidatures.service import CandidatureService, CandidatureServiceError
from tests.test_training_catalog import MemoryTrainings
from tests.test_candidature_service import CandidatureServiceTest, FakeCampaignService, FakeRepository


class TrainingSitesTest(unittest.TestCase):
    def setUp(self):
        self.repo = MemoryTrainings()
        self.sites = TrainingSiteService(self.repo)
        self.trainings = TrainingCatalogService(MemoryTrainings(), site_catalog=lambda **_: self.sites.list())
        self.candidates = FakeRepository()
        self.admissions = CandidatureService(repository=self.candidates, campaign_service=FakeCampaignService())

    def test_virtual_sites_need_no_write_and_existing_dossiers_have_no_inferred_site(self):
        self.assertEqual(4, len(self.sites.list()))
        self.assertEqual({}, self.repo.rows)
        from app.models.candidature import Candidature
        self.assertEqual("", Candidature(region_of_residence="Thiès").training_site)

    def test_initial_assignments_are_sites_not_residence_restrictions(self):
        data = next(row for row in DEFAULT_TRAININGS if row["code"] == "dev-data")
        self.assertEqual(["dakar", "thies", "diamniadio-uam"], data["siteIds"])
        old = {**DEFAULT_TRAININGS[0], "applicationRegions": ["Thiès"], "applicationRegionMode": "selected"}
        old.pop("siteIds")
        self.assertEqual(["dakar"], with_site_assignments(old)["siteIds"])
        self.assertNotIn("applicationRegions", with_site_assignments(old))

    def test_a_diourbel_resident_can_choose_dakar_web(self):
        candidate = self.admissions.submit({**CandidatureServiceTest._valid_payload(), "region_of_residence": "Diourbel"})
        self.assertEqual("Diourbel", candidate.region_of_residence)
        self.assertEqual("dakar", candidate.training_site)
        self.assertEqual("Dakar", candidate.training_site_name)

    def test_invalid_missing_archived_or_mismatched_site_never_writes(self):
        for site in (None, "", "unknown", "Dakar", {}, "thies"):
            with self.subTest(site=site), self.assertRaises(CandidatureServiceError):
                self.admissions.submit({**CandidatureServiceTest._valid_payload(), "training_site": site})
        with patch("app.services.trainings.sites.get_sites", return_value=[{**DEFAULT_SITES[0], "status": "archived"}]):
            with self.assertRaises(CandidatureServiceError):
                self.admissions.submit(CandidatureServiceTest._valid_payload())
        self.assertIsNone(self.candidates.created)

    def test_site_snapshot_is_derived_from_server_not_client(self):
        payload = {**CandidatureServiceTest._valid_payload(), "training_site": "thies", "training_site_name": "Fake", "desired_training": "dev-data", "region_of_residence": "Dakar"}
        saved = self.admissions.submit(payload)
        self.assertEqual("Thiès", saved.training_site_name)

    def test_sites_have_stable_codes_alias_uniqueness_archive_and_versions(self):
        created = self.sites.create({"name": "Saint-Louis"})
        renamed = self.sites.update(created["code"], {"version": 1, "name": "ODC Saint-Louis"})
        self.assertEqual("saint-louis", renamed["code"])
        self.assertIn("Saint-Louis", renamed["aliases"])
        with self.assertRaises(TrainingCatalogError):
            self.sites.update(created["code"], {"version": 1, "name": "Stale"})
        with self.assertRaises(TrainingCatalogError):
            self.sites.create({"name": "THIES"})
        self.assertEqual("archived", self.sites.update(created["code"], {"version": 2, "status": "archived"})["status"])

    def test_site_deadline_is_optional_validated_and_enforced_at_submission(self):
        deadline = "2026-11-09T12:00"
        site = {**DEFAULT_SITES[3], "applicationDeadline": deadline}
        self.assertEqual(deadline, validate_site({"name": "Tamba", "applicationDeadline": deadline})["applicationDeadline"])
        self.assertEqual("", validate_site({"name": "Tamba", "applicationDeadline": None})["applicationDeadline"])
        for invalid in ("2026-02-30T12:00", "2026-11-09", "pas-une-date"):
            with self.subTest(deadline=invalid), self.assertRaises(TrainingCatalogError):
                validate_site({"name": "Tamba", "applicationDeadline": invalid})

        before = datetime(2026, 11, 9, 11, 59, tzinfo=timezone.utc)
        at_deadline = datetime(2026, 11, 9, 12, 0, tzinfo=timezone.utc)
        self.assertTrue(site_application_open(site, before))
        self.assertFalse(site_application_open(site, at_deadline))

        service = CandidatureService(
            repository=self.candidates,
            now=lambda: at_deadline,
            campaign_service=FakeCampaignService(),
        )
        payload = {**CandidatureServiceTest._valid_payload(),
                   "training_site": "tambacounda", "desired_training": "referent-digital"}
        with patch("app.services.trainings.sites.get_sites", return_value=[site]):
            with self.assertRaisesRegex(CandidatureServiceError, "inscriptions.*clôturées"):
                service.submit(payload)
        self.assertIsNone(self.candidates.created)

    def test_admin_can_change_assignments_without_changing_residence(self):
        row = self.trainings.update("dev-web-mobile", {"version": 0, "siteIds": ["thies"]})
        self.assertEqual(["thies"], row["siteIds"])
        self.assertNotIn("applicationRegions", row)
        with self.assertRaises(TrainingCatalogError):
            self.trainings.update(row["code"], {"version": 1, "siteIds": ["unknown"]})
        with self.assertRaises(TrainingCatalogError):
            self.trainings.update(row["code"], {"version": 1, "siteIds": []})
        self.assertEqual([], self.trainings.update(row["code"], {"version": 1, "status": "draft", "siteIds": []})["siteIds"])

    def test_invalid_site_payloads_and_residence_policy_are_rejected(self):
        for payload in ({"name": ""}, {"name": "Test", "status": []}, {"name": "Test", "displayOrder": True}, {"name": "Test", "code": "fake"}):
            with self.subTest(payload=payload), self.assertRaises(TrainingCatalogError):
                self.sites.create(payload)
        with self.assertRaises(TrainingCatalogError):
            self.trainings.update("dev-data", {"version": 0, "applicationRegionMode": "all"})

    def test_http_submit_cannot_bypass_site_assignment(self):
        app = Flask(__name__)
        app.register_blueprint(candidature_public_bp, url_prefix="/api/candidature")
        with patch("app.routes.candidature_routes.candidature_service", self.admissions), \
             patch("app.routes.candidature_routes.is_request_rate_limited", return_value=False), \
             patch("app.services.trainings.catalog.get_catalog", return_value=DEFAULT_TRAININGS), \
             patch("app.services.trainings.sites.get_sites", return_value=DEFAULT_SITES):
            result = app.test_client().post("/api/candidature/apply", json={**CandidatureServiceTest._valid_payload(), "training_site": "thies"})
        self.assertEqual(400, result.status_code)
        self.assertIsNone(self.candidates.created)


class TrainingSiteRoutesTest(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.register_blueprint(training_bp, url_prefix="/api")
        self.client = self.app.test_client()
        self.service = TrainingSiteService(MemoryTrainings())
        self.user = SimpleNamespace(is_admin=True, admin_type="super_admin", profile_data={}, email="test@example.org")
        for target, value in (("app.routes.training_routes.site_service", self.service),
                              ("app.routes.training_routes.get_sites", lambda **_: self.service.list()),
                              ("app.utils.auth_decorators.AuthService.verify_token", lambda _: self.user)):
            mocked = patch(target, value)
            mocked.start()
            self.addCleanup(mocked.stop)
        self.headers = {"Authorization": "Bearer fake"}

    def test_public_hides_archived_sites_and_managers_can_create(self):
        self.service.update("thies", {"version": 0, "status": "archived"})
        public = self.client.get("/api/training-sites")
        self.assertEqual(3, len(public.json["data"]))
        for role in ("super_admin", "competences"):
            self.user.admin_type = role
            self.assertEqual(201, self.client.post("/api/admin/training-sites", json={"name": role}, headers=self.headers).status_code)

    def test_jury_read_only_and_other_roles_denied(self):
        self.user.admin_type = "competences"
        self.user.profile_data = {"admin_scope": "interview_member"}
        self.assertEqual(200, self.client.get("/api/admin/training-sites", headers=self.headers).status_code)
        for method, path in (("post", ""), ("patch", "/thies"), ("delete", "/thies")):
            self.assertEqual(403, getattr(self.client, method)("/api/admin/training-sites" + path, json={}, headers=self.headers).status_code)
        for role in ("cm", "startups"):
            self.user.admin_type = role
            self.assertEqual(401, self.client.get("/api/admin/training-sites", headers=self.headers).status_code)
