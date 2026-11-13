"""Public error responses use mocked failures, never live data or email."""

import unittest
from unittest.mock import Mock, patch

from flask import Flask

from app.routes.candidature_routes import candidature_public_bp
from app.routes.candidature_startup_routes import startup_bp
from app.routes.contact_route import contact_bp
from app.routes.orangefab_routes import orangefab_bp
from app.services.candidatures.service import CandidatureServiceError


class PublicErrorMessagesTest(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config["TESTING"] = True
        for blueprint, prefix in (
            (candidature_public_bp, "/api/candidature"),
            (startup_bp, "/api/startup"),
            (orangefab_bp, "/api/orangefab"),
            (contact_bp, "/api/contact"),
        ):
            self.app.register_blueprint(blueprint, url_prefix=prefix)
        self.client = self.app.test_client()
        for module in ("candidature_routes", "candidature_startup_routes", "orangefab_routes"):
            self.enterContext(patch(
                f"app.routes.{module}.is_request_rate_limited", return_value=False,
            ))
        self.internal_detail = "INTERNAL_ONLY database host private.example.test driver failure"

    def assert_private_failure(self, response):
        self.assertEqual(response.status_code, 500)
        self.assertTrue(response.is_json)
        self.assertIsInstance(response.get_json()["error"], str)
        self.assertTrue(response.get_json()["error"])
        self.assertNotIn(self.internal_detail, response.get_data(as_text=True))
        self.assertNotIn("private.example.test", response.get_data(as_text=True))

    def test_registration_logs_unexpected_error_without_returning_details(self):
        with patch(
            "app.routes.candidature_routes.candidature_service.submit",
            side_effect=RuntimeError(self.internal_detail),
        ), patch("app.routes.candidature_routes.logger.exception") as log:
            response = self.client.post(
                "/api/candidature/apply", json={"email": "synthetic@example.test"},
            )
        self.assert_private_failure(response)
        log.assert_called_once()

    def test_expected_registration_validation_is_still_actionable(self):
        for status, message in (
            (400, "La date de naissance ne peut pas être dans le futur."),
            (409, "Une candidature existe déjà pour cette personne."),
        ):
            with self.subTest(status=status), patch(
                "app.routes.candidature_routes.candidature_service.submit",
                side_effect=CandidatureServiceError(message, status),
            ):
                response = self.client.post(
                    "/api/candidature/apply", json={"email": "synthetic@example.test"},
                )
                self.assertEqual(response.status_code, status)
                self.assertEqual(response.get_json()["error"], message)

    def test_startup_and_orangefab_checks_hide_backend_failures(self):
        for module, prefix in (
            ("candidature_startup_routes", "/api/startup"),
            ("orangefab_routes", "/api/orangefab"),
        ):
            for field, value in (("email", "synthetic@example.test"), ("phone", "771234567")):
                service = Mock()
                getattr(service, f"{field}_exists").side_effect = RuntimeError(self.internal_detail)
                with self.subTest(module=module, field=field), patch(
                    f"app.routes.{module}._service", return_value=service,
                ), patch.object(self.app.logger, "exception") as log:
                    response = self.client.get(f"{prefix}/check-{field}", query_string={field: value})
                    self.assert_private_failure(response)
                    log.assert_called_once()

    def test_contact_failure_does_not_expose_mail_transport_details(self):
        with patch(
            "app.routes.contact_route.contact_service.send",
            side_effect=RuntimeError(self.internal_detail),
        ), patch.object(self.app.logger, "exception") as log:
            response = self.client.post("/api/contact/", json={"message": "synthetic"})
        self.assert_private_failure(response)
        log.assert_called_once()


if __name__ == "__main__":
    unittest.main()
