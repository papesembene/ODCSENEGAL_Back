import unittest

from app.services.applications.application_helpers import (
    ApplicationValidationError,
    validate_common_fields,
    validate_email,
    validate_phone,
)


class ApplicationHelpersTest(unittest.TestCase):
    def test_email_and_phone_validation(self):
        validate_email("startup@example.com")
        validate_phone("+221 77 123 45 67")

    def test_conditional_other_field_is_required(self):
        with self.assertRaisesRegex(
            ApplicationValidationError,
            "Précisez votre rôle",
        ):
            validate_common_fields(
                {"role": "Autre"},
                required_fields=("role",),
            )


if __name__ == "__main__":
    unittest.main()
