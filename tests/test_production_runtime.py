import os
import unittest
from unittest.mock import Mock, patch

from werkzeug.exceptions import ServiceUnavailable

from app.config import Config
from app.runtime_config import env_int
from app.utils.shared_rate_limit import shared_rate_limited


class ProductionRuntimeTest(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, {}, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def test_integer_settings_reject_invalid_budgets(self):
        for value in ("0", "-1", "1000000", "text"):
            with self.subTest(value=value), patch.dict(os.environ, {"LIMIT": value}):
                with self.assertRaises(RuntimeError):
                    env_int("LIMIT", 10, maximum=100)

    def test_shared_rate_limit_fails_closed_if_redis_is_down(self):
        with patch.dict(os.environ, {"REDIS_URL": "redis://test:6379"}), patch(
            "app.utils.shared_rate_limit._client", return_value=Mock(eval=Mock(side_effect=ConnectionError())),
        ):
            with self.assertRaises(ServiceUnavailable):
                shared_rate_limited("candidate@example.org", 5, 60)

    def test_local_development_keeps_in_memory_limits(self):
        self.assertIsNone(shared_rate_limited("local", 5, 60))

    def test_production_requires_explicit_database_and_strong_secrets(self):
        class Production(Config):
            ENVIRONMENT = "production"
            SECRET_KEY = "short"
            JWT_SECRET_KEY = "short"
        with self.assertRaises(RuntimeError) as error:
            Production.validate()
        self.assertIn("MONGO_DBNAME", str(error.exception))
        self.assertIn("32", str(error.exception))

    def test_multiple_instances_require_shared_sessions(self):
        class Production(Config):
            ENVIRONMENT = "production"
            SECRET_KEY = "a" * 32
            JWT_SECRET_KEY = "b" * 32
            FRONTEND_URL = "https://test.example.org"
            SESSION_TYPE = "filesystem"
            MONGODB_SETTINGS = {**Config.MONGODB_SETTINGS, "host": "mongodb://mongo/test", "db": "test"}
        with patch.dict(os.environ, {
            "APP_INSTANCES": "2", "MONGO_URI": "mongodb://mongo/test",
            "MONGO_DBNAME": "test", "CORS_ALLOWED_ORIGINS": "https://test.example.org",
        }), self.assertRaises(RuntimeError) as error:
            Production.validate()
        self.assertIn("SESSION_TYPE=redis", str(error.exception))
