"""Verify isolation boundaries of the registration load-test launcher."""
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("registration_load", Path(__file__).resolve().parents[1] / "load_tests" / "registration_load.py")
load = importlib.util.module_from_spec(spec)
spec.loader.exec_module(load)


class RegistrationLoadTest(unittest.TestCase):
    def test_child_does_not_inherit_production_credentials_or_targets(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {
            "MONGO_URI": "mongodb://production.invalid/odcdb", "ODC_ENV_FILE": "production.env",
            "SENDGRID_API_KEY": "production-key", "REDIS_URL": "redis://production.invalid/0",
            "HTTPS_PROXY": "http://proxy.invalid", "ELASTIC_APM_SERVER_URL": "https://apm.invalid",
        }):
            env = load.child_environment("a" * 32, 27029, 5401, Path(directory), 8, 50)
            self.assertEqual(env["MONGO_URI"], "mongodb://127.0.0.1:27029/odc_registration_load_" + "a" * 32)
            self.assertEqual(env["EMAIL_DELIVERY_MODE"], "queued")
            self.assertTrue(Path(env["ODC_ENV_FILE"]).is_file())
            for key in ("SENDGRID_API_KEY", "REDIS_URL", "HTTPS_PROXY", "ELASTIC_APM_SERVER_URL"):
                self.assertNotIn(key, env)

    def test_child_refuses_unexpected_database_before_loading_app(self):
        with patch.dict(os.environ, {"ODC_LOAD_RUN_ID": "a" * 32, "MONGO_DBNAME": "odcdb"}):
            with self.assertRaisesRegex(RuntimeError, "unexpected test database"):
                load.serve_child()

    def test_percentiles_and_errors_include_failed_requests(self):
        summary = load.summarize([(10, 201, True), (20, 201, True), (2000, 500, False)])
        self.assertEqual(summary["p50_ms"], 20)
        self.assertEqual(summary["p95_ms"], 2000)
        self.assertEqual(summary["errors"], 1)
        self.assertEqual(summary["statuses"], {"201": 2, "500": 1})
