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

    def find_by_email(self, _email):
        return self.email_exists

    def find_by_identity_number(self, _identity):
        return self.identity_exists

    def create(self, **values):
        self.created = SimpleNamespace(id="candidate-id", **values)
        return self.created

    @staticmethod
    def save(candidate):
        return candidate


class CandidatureServiceTest(unittest.TestCase):
    def setUp(self):
        self.repository = FakeRepository()
        self.service = CandidatureService(
            repository=self.repository,
            now=lambda: datetime(2026, 6, 25, 8, 0, 0),
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
            "accept_conditions": True,
        }


if __name__ == "__main__":
    unittest.main()
