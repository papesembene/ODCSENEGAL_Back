import unittest
from unittest.mock import patch

from flask import Flask

from app.observability import configure_observability


class ObservabilityTest(unittest.TestCase):
    def test_portal_health_alias_reports_dependency_failures(self):
        app = Flask(__name__)
        app.config["TESTING"] = True
        configure_observability(app)
        with patch.dict("os.environ", {"REDIS_URL": ""}), patch(
            "app.observability._mongo_status", return_value={"status": "down"},
        ):
            for path in ("/health", "/api/health"):
                with self.subTest(path=path):
                    response = app.test_client().get(path)
                    self.assertEqual(response.status_code, 503)
                    self.assertEqual(response.get_json()["status"], "degraded")
                    self.assertEqual(response.get_json()["dependencies"]["mongodb"]["status"], "down")

    def test_portal_health_alias_is_available(self):
        app = Flask(__name__)
        app.config["TESTING"] = True
        configure_observability(app)
        with patch.dict("os.environ", {"REDIS_URL": ""}), patch(
            "app.observability._mongo_status", return_value={"status": "up"},
        ):
            response = app.test_client().get("/api/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["status"], "healthy")

    def test_health_and_request_headers(self):
        app = Flask(__name__)
        app.config["TESTING"] = True
        configure_observability(app)

        with patch(
            "app.observability._mongo_status",
            return_value={"status": "up", "latency_ms": 1.2},
        ):
            response = app.test_client().get("/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["status"], "healthy")
        self.assertNotIn("hostname", response.get_json())
        self.assertNotIn("environment", response.get_json())
        self.assertNotIn("apm_enabled", response.get_json())
        self.assertEqual(
            response.get_json()["dependencies"]["mongodb"]["status"],
            "up",
        )
        self.assertTrue(response.headers["X-Request-ID"])
        self.assertIn("ms", response.headers["X-Response-Time"])

    def test_metrics_endpoint_is_available(self):
        app = Flask(__name__)
        app.config["TESTING"] = True
        configure_observability(app)

        with patch(
            "app.observability._mongo_status",
            return_value={"status": "up", "latency_ms": 1.2},
        ):
            response = app.test_client().get("/metrics")

        self.assertIn(response.status_code, (200, 503))
        self.assertIn("text/plain", response.content_type)


if __name__ == "__main__":
    unittest.main()
