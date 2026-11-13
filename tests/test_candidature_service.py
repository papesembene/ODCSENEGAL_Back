import unittest
from datetime import datetime
from types import SimpleNamespace

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


if __name__ == "__main__":
    unittest.main()
