import unittest

from app.services.portal_content_service import (
    PortalContentService,
    PortalContentServiceError,
)
from app.routes.portal_content_routes import PORTAL_ADMIN_TYPES


class PortalContentServiceUnitTest(unittest.TestCase):
    def test_normalize_payload_accepts_frontend_aliases(self):
        values = PortalContentService._normalize_payload({
            "type": "banner",
            "title": "Appel a candidature",
            "imageUrl": "/odc.jpg",
            "linkLabel": "Postuler",
            "linkUrl": "/odc/candidatures",
            "isPinned": True,
            "priority": "10",
        })

        self.assertEqual("/odc.jpg", values["image_url"])
        self.assertEqual("Postuler", values["link_label"])
        self.assertEqual("/odc/candidatures", values["link_url"])
        self.assertTrue(values["is_pinned"])
        self.assertEqual(10, values["priority"])

    def test_required_fields_are_enforced(self):
        with self.assertRaises(PortalContentServiceError):
            PortalContentService._validate_required({"type": "news"})

    def test_invalid_type_is_rejected(self):
        with self.assertRaises(PortalContentServiceError):
            PortalContentService._validate_required({
                "type": "other",
                "title": "Titre",
            })

    def test_date_parser_accepts_datetime_local_value(self):
        value = PortalContentService._parse_date("2026-07-07T12:30")

        self.assertEqual(2026, value.year)
        self.assertEqual(12, value.hour)

    def test_portal_admin_roles_are_limited_to_cm(self):
        self.assertEqual({"cm"}, PORTAL_ADMIN_TYPES)


if __name__ == "__main__":
    unittest.main()
