import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from bson import ObjectId

from app.services.tests.test_access_service import (
    SlidingWindowRateLimiter,
    TestAccessService,
    TestAccessError,
)


class TestAccessServiceUnitTest(unittest.TestCase):
    def test_phone_normalization(self):
        self.assertEqual(
            "221771234567",
            TestAccessService.normalize_digits("+221 77 123 45 67"),
        )

    def test_rate_limiter_is_bounded_by_window(self):
        limiter = SlidingWindowRateLimiter(limit=2, window=60)
        self.assertFalse(limiter.is_limited("candidate", now=1))
        self.assertFalse(limiter.is_limited("candidate", now=2))
        self.assertTrue(limiter.is_limited("candidate", now=3))
        self.assertFalse(limiter.is_limited("candidate", now=100))

    def test_short_suffix_or_non_numeric_phone_cannot_authenticate(self):
        service = TestAccessService(
            cache=Mock(get=Mock(return_value=SimpleNamespace(id=ObjectId()))),
            rate_limiter=Mock(is_limited=Mock(return_value=False)), access_logger=Mock(),
        )
        with patch("app.services.tests.test_access_service.Candidature.objects") as candidates, \
                patch("app.services.tests.test_access_service.Test.objects") as tests:
            tests.return_value.only.return_value.first.return_value = SimpleNamespace(id=ObjectId())
            candidates.return_value.only.return_value.first.return_value = SimpleNamespace(phone="+221771234567")
            for phone in ("+", "7", "4567", "1234567"):
                with self.subTest(phone=phone), self.assertRaises(TestAccessError) as error:
                    service.verify(str(ObjectId()), "candidate@example.org", phone, "local")
                self.assertEqual(403, error.exception.status_code)


if __name__ == "__main__":
    unittest.main()
