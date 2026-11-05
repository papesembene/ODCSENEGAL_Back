"""Verify isolation boundaries of the registration load-test launcher."""
import importlib.util
from contextlib import redirect_stderr
from io import StringIO
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, Mock, patch

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

    def test_candidate_site_defaults_or_configuration_keep_unique_synthetic_identities(self):
        default = load.candidate("abc123", 1)
        selected = load.candidate("abc123", 2, "thies")
        self.assertEqual(default["training_site"], "dakar")
        self.assertEqual(selected["training_site"], "thies")
        self.assertNotEqual(default["email"], selected["email"])
        self.assertNotEqual(default["cni_or_passport_number"], selected["cni_or_passport_number"])

    def test_journey_posts_the_selected_site_with_http_doubles_only(self):
        payload = {**load.candidate("abc123", 1, "thies"), "desired_training": "dev-data"}
        responses = []
        for status, body in ((200, {"data": {"isOpen": True}}), (200, {"exists": False}),
                             (201, {"candidature_id": "synthetic-id", "email_status": "queued"})):
            response = Mock(status_code=status)
            response.json.return_value = body
            responses.append(response)
        session = Mock()
        session.request.side_effect = responses
        context = MagicMock()
        context.__enter__.return_value = session
        gate = Mock()
        with patch.object(load.requests, "Session", return_value=context):
            result = load.journey("http://127.0.0.1:5401", payload, gate)
        gate.wait.assert_called_once()
        self.assertFalse(session.trust_env)
        self.assertEqual(session.request.call_args_list[0].kwargs["params"], {"formation": "dev-data"})
        self.assertEqual(session.request.call_args_list[2].kwargs["json"]["training_site"], "thies")
        self.assertTrue(all(sample[2] for sample in result.values()))

    def test_site_argument_is_configurable_and_invalid_codes_never_launch_processes(self):
        with tempfile.TemporaryDirectory() as directory:
            mongod = Path(directory) / "mongod-fixture.exe"
            mongod.touch()
            for extra, expected in (([], "dakar"), (["--site", "thies"], "thies")):
                with patch("sys.argv", ["registration_load.py", "--mongod", str(mongod), *extra]), \
                     patch.object(load, "execute", return_value=0) as execute:
                    self.assertEqual(load.main(), 0)
                    self.assertEqual(execute.call_args.args[0].site, expected)
            for site in ("", "Dakar", "bad/site", "x" * 81):
                with self.subTest(site=site), patch("sys.argv", ["registration_load.py", "--mongod", str(mongod), "--site", site]), \
                     patch.object(load, "execute") as execute, redirect_stderr(StringIO()), self.assertRaises(SystemExit):
                    load.main()
                execute.assert_not_called()
