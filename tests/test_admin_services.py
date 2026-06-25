import unittest
from datetime import datetime
from types import SimpleNamespace

from app.services.admin.application_read_service import (
    AdminApplicationReadService,
)
from app.services.admin.dashboard_activity_service import _relative_time


class AdminServicesTest(unittest.TestCase):
    def test_startup_serializer_supports_current_model_fields(self):
        startup = SimpleNamespace(
            id="startup-id",
            startup_name="Acme-unique",
            companyName="Acme",
            website="https://acme.example",
            creationDate="2026-01-12",
            sector="Tech",
            businessModel="B2B",
            employees="4",
            program="startup_lab",
            firstName="Awa",
            lastName="Diop",
            founder_email="awa@example.com",
            email="awa@example.com",
            fullPhone="+221771234567",
            phone="771234567",
            role="CEO",
            activityDescription="Produit numérique",
            createdAt=datetime(2026, 1, 12, 10, 0),
            cv="uploads/cv.pdf",
            pitchDeck="uploads/pitch.pdf",
        )

        data = AdminApplicationReadService._serialize_startup(startup)

        self.assertEqual(data["founder_first_name"], "Awa")
        self.assertEqual(data["founding_date"], "2026-01-12")
        self.assertEqual(data["pitchdeck_filename"], "uploads/pitch.pdf")

    def test_relative_time_uses_real_timestamp_order(self):
        now = datetime(2026, 6, 25, 12, 0)

        self.assertEqual(
            _relative_time(now, datetime(2026, 6, 25, 11, 0)),
            "Il y a 1h",
        )


if __name__ == "__main__":
    unittest.main()
