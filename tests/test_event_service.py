import unittest

from app.services.events.event_service import (
    EventService,
    EventServiceError,
)


class EventServiceTest(unittest.TestCase):
    def test_parse_iso_date(self):
        value = EventService._parse_date("2026-06-25T10:00:00Z")
        self.assertEqual(2026, value.year)
        self.assertEqual(10, value.hour)

    def test_invalid_date_contract(self):
        with self.assertRaisesRegex(
            EventServiceError,
            "Format de date invalide",
        ):
            EventService._parse_date("invalide")

    def test_email_is_required_for_newsletter(self):
        with self.assertRaisesRegex(EventServiceError, "Email requis"):
            EventService.subscribe("")


if __name__ == "__main__":
    unittest.main()
