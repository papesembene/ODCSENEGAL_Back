import unittest

from app.services.tests.test_access_service import (
    SlidingWindowRateLimiter,
    TestAccessService,
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


if __name__ == "__main__":
    unittest.main()
