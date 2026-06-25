import unittest

from flask import Flask

from app.observability import configure_observability


class ObservabilityTest(unittest.TestCase):
    def test_health_and_request_headers(self):
        app = Flask(__name__)
        app.config["TESTING"] = True
        configure_observability(app)

        response = app.test_client().get("/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["status"], "healthy")
        self.assertTrue(response.headers["X-Request-ID"])
        self.assertIn("ms", response.headers["X-Response-Time"])


if __name__ == "__main__":
    unittest.main()
