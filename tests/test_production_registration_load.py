import importlib.util
from pathlib import Path
import tempfile
import threading
import types
import unittest
from unittest.mock import Mock, patch

from requests.exceptions import ConnectTimeout


class ControlledGate:
    def __init__(self):
        self.signalled = False
        self.on_wait = None

    def set(self):
        self.signalled = True

    def wait(self, timeout=None):
        callback, self.on_wait = self.on_wait, None
        if callback:
            callback()
        return self.signalled


class ProductionRegistrationLoadTest(unittest.TestCase):
    def setUp(self):
        # The backend test environment need not install the external load tool.
        # Keep the real barrier code while replacing only its runtime adapters.
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        locust = types.ModuleType("locust")
        locust.HttpUser = type("HttpUser", (), {})
        locust.between = lambda low, high: None
        locust.task = lambda function: function
        gevent = types.ModuleType("gevent")
        gevent.__path__ = []
        event = types.ModuleType("gevent.event")
        event.Event = threading.Event
        lock = types.ModuleType("gevent.lock")
        lock.Semaphore = threading.Semaphore
        runtime = {"locust": locust, "gevent": gevent,
                   "gevent.event": event, "gevent.lock": lock}
        environment = {
            "ODC_LOAD_RUN_ID": "abcdef012345",
            "ODC_LOAD_EMAILS_PAUSED": "YES",
            "ODC_LOAD_MAX_SIGNUPS": "2",
            "ODC_LOAD_SYNC_BURST": "YES",
            "ODC_LOAD_RESULT_FILE": str(Path(self.temp.name) / "results.jsonl"),
        }
        path = Path(__file__).resolve().parents[1] / "load_tests" / "production_registration_locustfile.py"
        spec = importlib.util.spec_from_file_location("registration_load_under_test", path)
        self.module = importlib.util.module_from_spec(spec)
        with patch.dict("sys.modules", runtime), patch.dict("os.environ", environment):
            spec.loader.exec_module(self.module)
        self.now = 0.0
        self.module.monotonic = lambda: self.now
        self.gate = ControlledGate()
        self.module._burst_gate = self.gate

    def user(self, response=None, error=None):
        user = self.module.ProductionRegistrationUser()
        user.host = "https://api.orangedigitalcenter.sn"
        user.client = Mock()
        user.client.get.return_value = response
        user.client.get.side_effect = error
        return user

    def test_all_participants_release_together(self):
        results = []
        self.gate.on_wait = lambda: results.append(self.module._wait_for_burst())
        results.append(self.module._wait_for_burst())
        self.assertEqual(results, [True, True])
        self.assertTrue(self.module._burst_released)
        self.assertFalse(self.module._burst_aborted)

    def test_timeout_aborts_later_arrivals_instead_of_counting_stale_users(self):
        self.gate.on_wait = lambda: setattr(self, "now", 61.0)
        self.assertFalse(self.module._wait_for_burst())
        self.assertFalse(self.module._wait_for_burst())
        self.assertEqual(self.module._burst_ready, 1)
        self.assertTrue(self.module._burst_aborted)
        self.assertFalse(self.module._burst_released)

    def test_last_arrival_after_deadline_cannot_win_timeout_race(self):
        results = []

        def late_arrival():
            self.now = 61.0
            results.append(self.module._wait_for_burst())

        self.gate.on_wait = late_arrival
        results.append(self.module._wait_for_burst())
        self.assertEqual(results, [False, False])
        self.assertTrue(self.module._burst_aborted)
        self.assertFalse(self.module._burst_released)

    def test_http_zero_logs_transport_error_and_aborts_waiting_users(self):
        good = Mock(status_code=200)
        good.json.return_value = {"data": {"isOpen": True}}
        bad = Mock(status_code=0, error=ConnectTimeout("TCP connect timeout"))
        bad.json.side_effect = ValueError("no response body")
        waiting, failed = self.user(good), self.user(bad)
        self.gate.on_wait = failed.on_start
        with self.assertLogs(self.module.LOGGER, level="ERROR") as logs:
            waiting.on_start()
        for user in (waiting, failed):
            self.assertFalse(user.should_submit)
            user.submit_one_synthetic_candidate()
            user.client.post.assert_not_called()
        self.assertTrue(self.module._burst_aborted)
        self.assertFalse(self.module._burst_released)
        self.assertIn("TCP connect timeout", "\n".join(logs.output))

    def test_request_exception_aborts_before_later_user_can_join(self):
        failed = self.user(error=ConnectTimeout("connection failed"))
        with self.assertLogs(self.module.LOGGER, level="ERROR"):
            failed.on_start()
        self.assertFalse(self.module._wait_for_burst())
        self.assertEqual(self.module._burst_ready, 0)
        self.assertTrue(self.module._burst_aborted)


if __name__ == "__main__":
    unittest.main()
