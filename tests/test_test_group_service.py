import unittest

from app.services.tests.test_group_service import (
    TestGroupService,
    TestGroupServiceError,
)


class TestGroupServiceUnitTest(unittest.TestCase):
    def test_date_parser_accepts_iso(self):
        value = TestGroupService._parse_date(
            "2026-06-25T10:00:00Z",
        )
        self.assertEqual(10, value.hour)

    def test_date_parser_rejects_invalid_input(self):
        with self.assertRaises(TestGroupServiceError):
            TestGroupService._parse_date("invalid")


if __name__ == "__main__":
    unittest.main()
