import unittest
from types import SimpleNamespace

from app.services.profiles.profile_service import (
    ProfileService,
    ProfileValidationError,
)


class FakeUserRepository:
    def __init__(self):
        self.exists = False

    def find_by_email(self, _email):
        return self.exists

    @staticmethod
    def create(**values):
        return SimpleNamespace(
            id="user-id",
            student_profile=None,
            startup_profile=None,
            corporate_investor_profile=None,
            profile_data={},
            **values,
        )

    @staticmethod
    def save(user):
        return user


class ProfileServiceTest(unittest.TestCase):
    def setUp(self):
        self.repository = FakeUserRepository()
        self.service = ProfileService(self.repository)

    def test_register_builds_student_profile(self):
        user = self.service.register(
            {
                "email": "student@example.com",
                "password": "secret",
                "profileType": "student",
                "institution": "ODC",
                "educationLevel": "Licence",
                "sector": "Web",
            },
            {},
            "/tmp",
        )

        self.assertEqual("ODC", user.student_profile.institution)
        self.assertTrue(user.password_hash)

    def test_register_rejects_unknown_profile(self):
        with self.assertRaisesRegex(
            ProfileValidationError,
            "Type de profil invalide",
        ):
            self.service.register(
                {
                    "email": "x@example.com",
                    "password": "secret",
                    "profileType": "unknown",
                },
                {},
                "/tmp",
            )


if __name__ == "__main__":
    unittest.main()
