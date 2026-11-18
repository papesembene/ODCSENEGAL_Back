import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock, patch

from flask import Flask

from app.routes.candidature_routes import candidature_public_bp
from app.services.candidatures.service import (
    CandidatureService,
    CandidatureServiceError,
)


class FakeRepository:
    def __init__(self):
        self.created = None
        self.email_exists = False
        self.identity_exists = False
        self.possible_duplicates = []

    def find_by_email(self, _email):
        return self.email_exists

    def find_by_identity_number(self, _identity):
        return self.identity_exists

    def find_by_phone_and_birth_date(self, _phone, _birth_date):
        return self.possible_duplicates

    def create(self, **values):
        self.created = SimpleNamespace(id="candidate-id", **values)
        return self.created

    @staticmethod
    def save(candidate):
        return candidate


class FakeCampaignService:
    def assert_open(self, _formation=None):
        return None


class CandidatureServiceTest(unittest.TestCase):
    def setUp(self):
        self.repository = FakeRepository()
        self.service = CandidatureService(
            repository=self.repository,
            now=lambda: datetime(2026, 6, 25, 8, 0, 0),
            campaign_service=FakeCampaignService(),
        )

    def test_submit_normalizes_contact_data(self):
        candidate = self.service.submit(self._valid_payload())

        self.assertEqual("moussa@example.com", candidate.email)
        self.assertEqual("+221771234567", candidate.phone)

    def test_current_age_rules_are_enforced_per_program_before_writes(self):
        cases = [
            ("startup-school", "Agé de 25 à 40 ans", "1991-06-25", True),
            ("startup-school", "Agé de 25 à 40 ans", "2002-06-25", False),
            ("startup-school", "Agé de 25 à 40 ans", "2001-06-25", True),
            ("startup-school", "Agé de 25 à 40 ans", "1986-06-25", True),
            ("startup-school", "Agé de 25 à 40 ans", "1985-06-26", True),
            ("startup-school", "Agé de 25 à 40 ans", "1985-06-25", False),
            ("tech-broadband", "Agé de 18 à 40 ans", "1991-06-25", True),
            ("tech-broadband", "Agé de 18 à 40 ans", "2008-06-25", True),
            ("tech-broadband", "Agé de 18 à 40 ans", "2008-06-26", False),
            ("tech-broadband", "Agé de 18 à 40 ans", "1986-06-25", True),
            ("tech-broadband", "Agé de 18 à 40 ans", "1985-06-25", False),
            ("dev-web-mobile", "Agé de 18 à 30 ans", "1991-06-25", False),
            ("dev-web-mobile", "Agé de 18 à 30 ans", "1996-06-25", True),
            ("dev-web-mobile", "Agé de 18 à 30 ans", "1995-06-26", True),
            ("dev-web-mobile", "Agé de 18 à 30 ans", "1995-06-25", False),
            ("dev-web-mobile", "Agé de 18 à 30 ans", "2008-06-25", True),
            ("dev-web-mobile", "Agé de 18 à 30 ans", "2008-06-26", False),
            ("hackeuses", "Agée de + de 18 ans", "2008-06-25", False),
            ("hackeuses", "Agée de + de 18 ans", "2008-06-24", True),
            ("hackeuses", "Agée de + de 18 ans", "1946-06-25", True),
        ]
        for code, level, birth, allowed in cases:
            with self.subTest(code=code, birth=birth):
                repository = Mock(wraps=FakeRepository())
                service = CandidatureService(repository=repository, now=self.service.now, campaign_service=FakeCampaignService())
                payload = {**self._valid_payload(), "desired_training": code, "date_of_birth": birth}
                with patch("app.services.trainings.catalog.get_catalog", return_value=[self._training(code, level)]):
                    if allowed:
                        self.assertEqual(birth, service.submit(payload).date_of_birth.isoformat())
                        repository.create.assert_called_once()
                        repository.save.assert_called_once()
                    else:
                        with self.assertRaisesRegex(CandidatureServiceError, "à la date d'inscription") as error:
                            service.submit(payload)
                        self.assertEqual(400, error.exception.status_code)
                        repository.create.assert_not_called()
                        repository.save.assert_not_called()

    def test_missing_or_ambiguous_policy_never_invents_a_registration_restriction(self):
        for level in ("Bac + 2 / BTS", "", "Agé de 18 à 30 ans ou âgé de 25 à 40 ans"):
            with self.subTest(level=level), patch("app.services.trainings.catalog.get_catalog", return_value=[
                self._training("cyber-security", level),
            ]):
                for birth in ("1990-01-01", "2009-01-01"):
                    self.repository.created = None
                    payload = {**self._valid_payload(), "desired_training": "cyber-security", "date_of_birth": birth}
                    self.assertEqual(birth, self.service.submit(payload).date_of_birth.isoformat())

    def test_submission_uses_utc_day_even_when_injected_clock_has_an_offset(self):
        with patch("app.services.trainings.catalog.get_catalog", return_value=[
            self._training("dev-web-mobile", "Agé de 18 à 30 ans"),
        ]):
            self.service.now = lambda: datetime(2026, 6, 26, 0, 30, tzinfo=timezone(timedelta(hours=2)))
            payload = {**self._valid_payload(), "date_of_birth": "2008-06-26"}
            with self.assertRaisesRegex(CandidatureServiceError, "entre 18 et 30 ans inclus"):
                self.service.submit(payload)
            self.assertIsNone(self.repository.created)
            self.service.now = lambda: datetime(2026, 6, 24, 23, 30, tzinfo=timezone(timedelta(hours=-3)))
            payload["date_of_birth"] = "2008-06-25"
            self.assertEqual("2008-06-25", self.service.submit(payload).date_of_birth.isoformat())

    @staticmethod
    def _training(code, level):
        return {"code": code, "value": code, "title": code, "aliases": [], "level": level,
                "status": "published", "siteIds": ["dakar"], "femaleOnly": False}

    def test_submit_requires_real_booleans(self):
        payload = self._valid_payload()
        payload["accept_conditions"] = "true"

        with self.assertRaisesRegex(
            CandidatureServiceError,
            "doit être un booléen",
        ):
            self.service.submit(payload)

    def test_submit_rejects_duplicate_email(self):
        self.repository.email_exists = True

        with self.assertRaisesRegex(
            CandidatureServiceError,
            "email existe déjà",
        ):
            self.service.submit(self._valid_payload())

    def test_submit_rejects_same_person_with_new_email_and_document(self):
        self.repository.possible_duplicates = [SimpleNamespace(
            first_name="Moussa",
            last_name="Bà",
        )]
        payload = self._valid_payload()
        payload["email"] = "moussa.new@example.com"
        payload["cni_or_passport_number"] = "A12345678"
        payload["desired_training"] = "dev-data"
        payload["first_name"] = "  MOUSSA  "
        payload["last_name"] = "Ba"

        with self.assertRaisesRegex(CandidatureServiceError, "Une candidature existe déjà"):
            self.service.submit(payload)

    def test_submit_allows_shared_phone_and_birth_date_for_a_different_name(self):
        self.repository.possible_duplicates = [SimpleNamespace(
            first_name="Awa",
            last_name="Ba",
        )]

        candidate = self.service.submit(self._valid_payload())

        self.assertEqual("Moussa", candidate.first_name)

    def test_submit_rejects_invalid_or_future_birth_date(self):
        for birth_date in ("2001-02-29", "2026-06-26", "25/06/2000"):
            with self.subTest(birth_date=birth_date):
                payload = self._valid_payload()
                payload["date_of_birth"] = birth_date
                with self.assertRaisesRegex(CandidatureServiceError, "date de naissance"):
                    self.service.submit(payload)

    @staticmethod
    def _valid_payload():
        return {
            "first_name": "Moussa",
            "last_name": "Ba",
            "email": " Moussa@Example.COM ",
            "phone": "+221 77 123 45 67",
            "date_of_birth": "2000-01-01",
            "place_of_birth": "Dakar",
            "gender": "homme",
            "cni_or_passport_number": "123456789",
            "nationality": "Sénégalaise",
            "region_of_residence": "Dakar",
            "computer_skills": True,
            "available_for_10_months": True,
            "desired_training": "dev-web-mobile",
            "training_site": "dakar",
            "accept_conditions": True,
        }


class CandidatureAgeRegistrationHttpTest(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__)
        app.config["TESTING"] = True
        app.register_blueprint(candidature_public_bp, url_prefix="/api/candidature")
        self.http = app.test_client()

    def test_public_api_rejects_outside_published_rule_and_accepts_inclusive_endpoints(self):
        for code, level, birth, status in (
            ("dev-web-mobile", "Agé de 18 à 30 ans", "1991-06-25", 400),
            ("startup-school", "Agé de 25 à 40 ans", "2002-06-25", 400),
            ("dev-web-mobile", "Agé de 18 à 30 ans", "1996-06-25", 201),
            ("startup-school", "Agé de 25 à 40 ans", "1986-06-25", 201),
        ):
            with self.subTest(code=code, birth=birth):
                repository = Mock(wraps=FakeRepository())
                service = CandidatureService(repository=repository, now=lambda: datetime(2026, 6, 25, 8),
                                             campaign_service=FakeCampaignService())
                payload = {**CandidatureServiceTest._valid_payload(), "desired_training": code, "date_of_birth": birth}
                with patch("app.services.trainings.catalog.get_catalog", return_value=[
                    CandidatureServiceTest._training(code, level),
                ]), patch("app.services.candidatures.service.require_site", return_value={"code": "dakar", "name": "Dakar"}), patch(
                    "app.routes.candidature_routes.candidature_service", service,
                ), patch("app.routes.candidature_routes.is_request_rate_limited", return_value=False):
                    response = self.http.post("/api/candidature/apply", json=payload)
                self.assertEqual(status, response.status_code)
                if status == 400:
                    self.assertIn(code, response.get_json()["error"])
                    self.assertIn("à la date d'inscription", response.get_json()["error"])
                    repository.create.assert_not_called()
                    repository.save.assert_not_called()
                    repository.find_by_email.assert_not_called()
                    repository.find_by_identity_number.assert_not_called()
                    repository.find_by_phone_and_birth_date.assert_not_called()
                else:
                    repository.create.assert_called_once()
                    repository.save.assert_called_once()


if __name__ == "__main__":
    unittest.main()
