"""Only opt-in localhost Redis, with unique keys and no FLUSHDB."""

from concurrent.futures import ThreadPoolExecutor
import os
import unittest
from unittest.mock import patch
from uuid import uuid4
from flask import Flask, session
from flask_session import Session

from app.runtime_config import redis_client
from app.services.tests.test_access_service import SlidingWindowRateLimiter
from app.utils.shared_rate_limit import shared_rate_limited


@unittest.skipUnless(os.getenv("TEST_REDIS_URL"), "requires disposable local Redis")
class SharedRedisIntegrationTest(unittest.TestCase):
    def setUp(self):
        url = os.environ["TEST_REDIS_URL"]
        if not url.startswith(("redis://127.0.0.1:", "redis://localhost:")):
            self.fail("Integration Redis tests accept localhost only")
        self.namespace = "odc_redis_test_" + uuid4().hex
        self.environment = patch.dict(os.environ, {"REDIS_URL": url, "MONGO_DBNAME": self.namespace})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.client = redis_client(url)
        self.client.ping()
        self.addCleanup(self.clear_own_keys)

    def clear_own_keys(self):
        keys = list(self.client.scan_iter(match=f"odc:{self.namespace}:rate:*"))
        if keys:
            self.client.delete(*keys)
        self.client.close()

    def test_independent_api_instances_share_the_same_counter(self):
        first, second = SlidingWindowRateLimiter(limit=2), SlidingWindowRateLimiter(limit=2)
        self.assertFalse(first.is_limited("candidate"))
        self.assertFalse(second.is_limited("candidate"))
        self.assertTrue(first.is_limited("candidate"))
        self.assertTrue(second.is_limited("candidate"))

    def test_simultaneous_checks_cannot_exceed_limit(self):
        with ThreadPoolExecutor(max_workers=8) as pool:
            decisions = list(pool.map(lambda _: shared_rate_limited("candidate", 3, 60), range(20)))
        self.assertEqual(3, decisions.count(False))
        self.assertEqual(17, decisions.count(True))

    def test_expired_attempts_are_removed_and_keys_have_a_ttl(self):
        self.assertFalse(shared_rate_limited("candidate", 1, 60, now=100))
        self.assertTrue(shared_rate_limited("candidate", 1, 60, now=101))
        self.assertFalse(shared_rate_limited("candidate", 1, 60, now=161))
        key = next(self.client.scan_iter(match=f"odc:{self.namespace}:rate:*"))
        self.assertGreater(self.client.ttl(key), 0)

    def test_flask_session_is_readable_by_a_second_api_instance(self):
        prefix = self.namespace + ":session:"

        def instance():
            app = Flask(__name__)
            app.config.update(SECRET_KEY="test-redis-session", SESSION_TYPE="redis",
                              SESSION_REDIS=self.client, SESSION_KEY_PREFIX=prefix)
            Session(app)

            @app.get("/write")
            def write():
                session["test_value"] = "shared"
                return "ok"

            @app.get("/read")
            def read():
                return {"value": session.get("test_value")}

            return app.test_client()

        try:
            first, second = instance(), instance()
            cookie = first.get("/write").headers["Set-Cookie"].split(";", 1)[0].split("=", 1)[1]
            second.set_cookie("session", cookie)
            self.assertEqual("shared", second.get("/read").json["value"])
        finally:
            keys = list(self.client.scan_iter(match=prefix + "*"))
            if keys:
                self.client.delete(*keys)
