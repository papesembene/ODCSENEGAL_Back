import unittest
from unittest.mock import Mock, patch

from app.services.applications.application_helpers import (
    ApplicationValidationError,
)
from app.services.applications.base_application_service import (
    BaseApplicationService,
)


class FakeApplication:
    check_email_exists = Mock(return_value=False)
    check_phone_exists = Mock(return_value=False)


class ApplicationServiceTest(unittest.TestCase):
    def setUp(self):
        FakeApplication.check_email_exists.reset_mock()
        FakeApplication.check_email_exists.return_value = False
        FakeApplication.check_phone_exists.reset_mock()
        FakeApplication.check_phone_exists.return_value = False
        self.service = BaseApplicationService(
            FakeApplication,
            "uploads/test",
        )

    def test_normalizes_identity(self):
        data = {
            "email": " CANDIDAT@EXAMPLE.COM ",
            "phone": "77 123 45 67",
            "phoneCountry": "+221",
        }

        self.service._normalize_and_validate_identity(data)

        self.assertEqual(data["email"], "candidat@example.com")
        self.assertEqual(data["phone"], "771234567")
        self.assertEqual(data["fullPhone"], "+221771234567")

    def test_rejects_same_alternate_email(self):
        data = {
            "email": "candidat@example.com",
            "emailAlternate": " CANDIDAT@example.com ",
            "phone": "771234567",
            "phoneCountry": "+221",
        }

        with self.assertRaises(ApplicationValidationError):
            self.service._normalize_and_validate_identity(data)

    @patch(
        "app.services.applications.base_application_service.remove_files"
    )
    @patch(
        "app.services.applications.base_application_service.save_document"
    )
    def test_removes_first_file_when_second_save_fails(
        self,
        save_document_mock,
        remove_files_mock,
    ):
        self.service.required_fields = ("email", "phone", "phoneCountry")
        first_file = Mock(filename="cv.pdf")
        second_file = Mock(filename="pitch.pdf")
        first_file.tell.return_value = 1
        second_file.tell.return_value = 1
        save_document_mock.side_effect = [
            "/tmp/cv.pdf",
            RuntimeError("disk full"),
        ]

        with self.assertRaisesRegex(RuntimeError, "disk full"):
            self.service.submit(
                {
                    "email": "candidat@example.com",
                    "phone": "771234567",
                    "phoneCountry": "+221",
                },
                {"cv": first_file, "pitch_deck": second_file},
            )

        remove_files_mock.assert_called_once_with(["/tmp/cv.pdf"])


if __name__ == "__main__":
    unittest.main()
