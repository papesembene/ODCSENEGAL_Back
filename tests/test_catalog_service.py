import unittest
from types import SimpleNamespace

from app.services.catalog_service import (
    CatalogService,
    CatalogValidationError,
)


class FakeQuery(list):
    pass


class FakeModel:
    saved = []

    def __init__(self, **values):
        self.values = values

    def save(self):
        self.saved.append(self)

    def to_dict(self):
        return self.values

    @classmethod
    def objects(cls):
        return FakeQuery(cls.saved)


class CatalogServiceTest(unittest.TestCase):
    def setUp(self):
        FakeModel.saved = []
        self.service = CatalogService(
            FakeModel,
            required_fields=("name",),
            allowed_fields=("name", "description"),
        )

    def test_create_keeps_only_allowed_fields(self):
        item = self.service.create({
            "name": "Data",
            "description": "Formation",
            "ignored": "value",
        })

        self.assertEqual(
            {"name": "Data", "description": "Formation"},
            item.values,
        )

    def test_required_field_is_enforced(self):
        with self.assertRaises(CatalogValidationError):
            self.service.create({"description": "Sans nom"})


if __name__ == "__main__":
    unittest.main()
