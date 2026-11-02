"""Catalogue contracts, using an isolated in-memory repository, never production data."""

import unittest
from copy import deepcopy
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import patch
from tempfile import TemporaryDirectory
from pathlib import Path
import base64

from flask import Flask

from app.routes.training_routes import training_bp
from app.services.tests.formation_catalog import formation_aliases, normalize_formation
from app.services.trainings.catalog import DEFAULT_TRAININGS, find_training, get_catalog, invalidate_catalog
from app.services.trainings.schema import TrainingCatalogError
from app.services.trainings.service import TrainingCatalogService


class MemoryTrainings:
    def __init__(self):
        self.rows = {}

    def list(self):
        return deepcopy(list(self.rows.values()))

    def save(self, data, version, actor):
        current = self.rows.get(data["code"], {"version": 0})
        if current["version"] != version:
            raise TrainingCatalogError("Version obsolète", 409)
        self.rows[data["code"]] = {**deepcopy(data), "version": version + 1}
        return deepcopy(self.rows[data["code"]])


class TrainingCatalogTest(unittest.TestCase):
    def setUp(self):
        self.repo = MemoryTrainings()
        self.service = TrainingCatalogService(self.repo)

    def create(self, **overrides):
        return self.service.create({"title": "Robotique", "durationMonths": 6, "status": "published", **overrides})

    def test_defaults_are_read_only_and_preserve_seven_existing_courses(self):
        self.assertEqual(7, len(self.service.list()))
        self.assertEqual({}, self.repo.rows)
        self.assertEqual("dev-web-mobile", find_training("DEV WEB")["code"])

    def test_create_rename_preserves_identity_and_all_previous_names(self):
        created = self.create()
        renamed = self.service.update(created["code"], {"title": "Robotique avancée", "version": created["version"]})
        self.assertEqual("robotique", renamed["code"])
        self.assertEqual(created["value"], renamed["value"])
        self.assertEqual(2, renamed["version"])
        self.assertEqual("robotique", find_training("ROBOTIQUE", self.service.list())["code"])
        self.assertEqual("robotique", find_training("robotique avancee", self.service.list())["code"])

    def test_first_edit_of_virtual_default_persists_and_can_be_edited_again(self):
        edited = self.service.update("dev-web-mobile", {"version": 0, "description": "Nouvelle description"})
        self.assertEqual(1, edited["version"])
        self.assertEqual("Dev Web", edited["value"])
        self.assertEqual("Nouvelle description", self.service.list()[0]["description"])
        self.service.update(edited["code"], {"version": 1, "title": "Web actualisé"})

    def test_archive_keeps_history_and_republishing_reuses_identity(self):
        created = self.create()
        archived = self.service.archive(created["code"], created["version"])
        self.assertEqual("archived", find_training("Robotique", self.service.list())["status"])
        restored = self.service.update(created["code"], {"version": archived["version"], "status": "published"})
        self.assertEqual(created["code"], restored["code"])

    def test_names_and_legacy_aliases_are_unique_accent_insensitively(self):
        self.create(title="Électronique")
        for title in ("electronique", "Dev Web", "dev-web-mobile"):
            with self.subTest(title=title), self.assertRaises(TrainingCatalogError) as raised:
                self.create(title=title)
            self.assertEqual(409, raised.exception.status_code)

    def test_bad_fields_and_numbers_are_rejected_without_writes(self):
        for invalid in ({"durationMonths": "6"}, {"durationMonths": True}, {"durationMonths": 0},
                        {"durationMonths": float("nan")}, {"status": []}, {"femaleOnly": "true"},
                        {"imageUrl": "javascript:alert(1)"}, {"skills": "HTML"}, {"code": "replace"},
                        {"title": ""}, {"displayOrder": -1}):
            with self.subTest(payload=invalid), self.assertRaises(TrainingCatalogError):
                self.create(**invalid)
        self.assertEqual({}, self.repo.rows)

    def test_stale_version_cannot_overwrite_or_archive_a_newer_edit(self):
        created = self.create()
        self.service.update(created["code"], {"version": 1, "title": "Nouveau nom"})
        for payload in ({"version": 1, "title": "Ancien nom"}, {"version": 1, "status": "archived"}):
            with self.assertRaises(TrainingCatalogError) as raised:
                self.service.update(created["code"], payload)
            self.assertEqual(409, raised.exception.status_code)
        self.assertEqual("Nouveau nom", self.repo.rows[created["code"]]["title"])

    def test_unknown_or_missing_version_is_not_silently_upserted(self):
        for code, payload, status in (("unknown", {"version": 0}, 404), ("dev-web-mobile", {}, 400)):
            with self.assertRaises(TrainingCatalogError) as raised:
                self.service.update(code, payload)
            self.assertEqual(status, raised.exception.status_code)

    def test_custom_cloud_course_is_not_confused_with_aws(self):
        created = self.create(title="Cloud souverain")
        self.assertEqual(created["code"], find_training("Cloud souverain", self.service.list())["value"])
        self.assertEqual("Cloud souverain", normalize_formation("Cloud souverain"))
        self.assertIn("Dev Web", formation_aliases("dev-web-mobile"))

    def test_cache_has_no_writes_and_mutations_invalidate_it(self):
        app = Flask(__name__)
        with app.app_context(), patch("app.repositories.training_repository.TrainingRepository", return_value=self.repo):
            before = get_catalog()
            self.assertEqual(7, len(before))
            self.create()
            self.assertEqual(8, len(get_catalog()))
            invalidate_catalog()
            before[0]["title"] = "Changed copy"
            self.assertNotEqual("Changed copy", get_catalog()[0]["title"])

    def test_archived_course_cannot_accept_new_applications(self):
        from app.services.candidatures.service import CandidatureService, CandidatureServiceError
        from tests.test_candidature_service import CandidatureServiceTest, FakeCampaignService, FakeRepository
        repository = FakeRepository()
        service = CandidatureService(repository=repository, campaign_service=FakeCampaignService())
        archived = {**DEFAULT_TRAININGS[0], "status": "archived"}
        with patch("app.services.trainings.catalog.get_catalog", return_value=[archived]):
            with self.assertRaises(CandidatureServiceError):
                service.submit(CandidatureServiceTest._valid_payload())
        self.assertIsNone(repository.created)

    def test_women_only_flag_is_enforced_on_server_not_just_in_the_form(self):
        from app.services.candidatures.service import CandidatureService, CandidatureServiceError
        from tests.test_candidature_service import CandidatureServiceTest, FakeCampaignService, FakeRepository
        repository = FakeRepository()
        service = CandidatureService(repository=repository, campaign_service=FakeCampaignService())
        payload = {**CandidatureServiceTest._valid_payload(), "desired_training": "hackeuses"}
        with self.assertRaises(CandidatureServiceError):
            service.submit(payload)
        self.assertIsNone(repository.created)
        payload["gender"] = "female"
        self.assertEqual("hackeuses", service.submit(payload).desired_training)


class TrainingRoutesTest(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.register_blueprint(training_bp, url_prefix="/api")
        self.client = self.app.test_client()
        self.repo = MemoryTrainings()
        self.service = TrainingCatalogService(self.repo)
        self.user = SimpleNamespace(is_admin=True, admin_type="super_admin", profile_data={}, email="admin@example.org")
        for target, value in (("app.routes.training_routes.service", self.service),
                              ("app.routes.training_routes.get_catalog", lambda **_: self.service.list()),
                              ("app.utils.auth_decorators.AuthService.verify_token", lambda _: self.user)):
            patched = patch(target, value)
            patched.start()
            self.addCleanup(patched.stop)
        self.headers = {"Authorization": "Bearer fake"}

    def request(self, method, path="", **kwargs):
        return getattr(self.client, method)("/api/admin/trainings" + path, headers=self.headers, **kwargs)

    def test_public_only_contains_published_and_no_internal_credentials(self):
        self.service.create({"title": "Draft", "durationMonths": 3, "status": "draft"})
        self.service.archive("dev-web-mobile", 0)
        result = self.client.get("/api/trainings")
        self.assertEqual(200, result.status_code)
        self.assertEqual(6, len(result.json["data"]))
        self.assertEqual("no-store", result.headers["Cache-Control"])
        self.assertTrue(all(item["status"] == "published" for item in result.json["data"]))

    def test_both_manager_profiles_can_create_edit_and_archive(self):
        for role in ("super_admin", "competences"):
            self.user.admin_type = role
            created = self.request("post", json={"title": role, "durationMonths": 6})
            self.assertEqual(201, created.status_code)
            item = created.json["data"]
            edited = self.request("patch", "/" + item["code"], json={"version": 1, "status": "published"})
            self.assertEqual(200, edited.status_code)
            self.assertEqual(200, self.request("delete", "/" + item["code"], json={"version": 2}).status_code)

    def test_jury_can_read_but_never_manage_referentials_or_upload(self):
        self.user.admin_type = "competences"
        self.user.profile_data = {"admin_scope": "interview_member"}
        self.assertEqual(200, self.request("get").status_code)
        for method, path in (("post", ""), ("patch", "/dev-web-mobile"), ("delete", "/dev-web-mobile"), ("post", "/media")):
            self.assertEqual(403, self.request(method, path, json={}).status_code)
        self.assertEqual({}, self.repo.rows)

    def test_other_roles_and_anonymous_cannot_manage(self):
        self.assertEqual(401, self.client.post("/api/admin/trainings", json={}).status_code)
        for role in ("cm", "startups", "user"):
            self.user.admin_type = role
            self.assertEqual(401, self.request("post", json={}).status_code)
        self.user.is_admin = False
        self.user.admin_type = "super_admin"
        self.assertEqual(401, self.request("get").status_code)

    def test_invalid_media_and_concurrent_edits_are_explicit_errors(self):
        self.assertEqual(400, self.request("post", "/media").status_code)
        bad_image = {"image": (BytesIO(b"not an image"), "exploit.svg")}
        self.assertEqual(400, self.request("post", "/media", data=bad_image).status_code)
        self.service.update("dev-web-mobile", {"version": 0, "title": "Web"})
        self.assertEqual(409, self.request("patch", "/dev-web-mobile", json={"version": 0, "title": "Override"}).status_code)
        self.assertEqual(400, self.request("delete", "/dev-web-mobile", json=[]).status_code)

    def test_upload_stores_a_valid_image_with_a_generated_filename(self):
        png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aC1sAAAAASUVORK5CYII=")
        with TemporaryDirectory() as folder:
            self.app.root_path = folder
            result = self.request("post", "/media", data={"image": (BytesIO(png), "robot.png")})
            self.assertEqual(201, result.status_code)
            image_path = result.json["data"]["imageUrl"]
            self.assertTrue(image_path.startswith("/static/uploads/trainings/"))
            self.assertNotEqual("robot.png", image_path.split("/")[-1])
            self.assertEqual(png, (Path(folder) / image_path.lstrip("/")).read_bytes())


if __name__ == "__main__":
    unittest.main()
