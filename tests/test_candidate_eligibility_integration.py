"""Optional real Mongo checks use a unique disposable localhost database only."""

import csv
from copy import deepcopy
from datetime import date, datetime, timezone
from io import StringIO
import os
import unittest
from unittest.mock import patch
from uuid import uuid4

from bson import ObjectId
from bson.datetime_ms import DatetimeMS
from pymongo import MongoClient

from app.repositories.candidature_read_repository import CandidatureReadRepository
from app.services.candidatures.export_service import export_candidates
from app.utils.candidate_eligibility import age_eligibility_filter
from age_rule_fixtures import CATALOG


@unittest.skipUnless(os.getenv("TEST_LOCAL_MONGO") == "1", "requires disposable local MongoDB")
class CandidateEligibilityIntegrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = MongoClient("mongodb://127.0.0.1:27017", serverSelectionTimeoutMS=3000)
        cls.addClassCleanup(cls.client.close)
        cls.client.admin.command("ping")
        cls.db_name = "odc_candidate_eligibility_test_" + uuid4().hex
        cls.addClassCleanup(cls.client.drop_database, cls.db_name)
        cls.collection = cls.client[cls.db_name]["candidates"]
        cls.collection.create_index("date_of_birth")

    def setUp(self):
        self.collection.delete_many({})
        self.today = date(2026, 11, 17)
        utc = timezone.utc
        births = [
            ("young", datetime(1996, 11, 18, tzinfo=utc)),
            ("birthday", datetime(1996, 11, 17, 23, 59, tzinfo=utc)),
            ("older", datetime(1990, 1, 1, tzinfo=utc)),
            ("born_today", datetime(2026, 11, 17, 23, 59, tzinfo=utc)),
            ("future", datetime(2026, 11, 18, tzinfo=utc)),
            ("null", None),
            ("text", "2000-01-01"),
            ("number", 946684800000),
            ("date_array", [datetime(2000, 1, 1, tzinfo=utc)]),
            ("object", {"date": datetime(2000, 1, 1, tzinfo=utc)}),
            ("mixed_array", [datetime(1990, 1, 1, tzinfo=utc), datetime(2000, 1, 1, tzinfo=utc)]),
            ("empty_array", []),
        ]
        self.rows = [{
            "_id": ObjectId(), "first_name": label, "last_name": "Synthetic",
            "email": f"{label}@example.org", "desired_training": "Dev Web", "gender": "female",
            "status": "pending", "created_at": datetime(2026, 11, 17, tzinfo=utc), "date_of_birth": birth,
        } for label, birth in births]
        self.rows.append({
            "_id": ObjectId(), "first_name": "missing", "last_name": "Synthetic",
            "email": "missing@example.org", "status": "pending",
            "created_at": datetime(2026, 11, 17, tzinfo=utc),
        })
        self.collection.insert_many(self.rows)
        clock = patch("app.utils.candidate_eligibility.utc_today", return_value=self.today)
        clock.start()
        self.addCleanup(clock.stop)
        catalog = patch("app.services.trainings.catalog.get_catalog", return_value=deepcopy(CATALOG))
        catalog.start()
        self.addCleanup(catalog.stop)
        source = patch.object(CandidatureReadRepository, "collection", return_value=self.collection)
        source.start()
        self.addCleanup(source.stop)
        self.repository = CandidatureReadRepository()

    def test_filters_partition_legacy_values_before_count_pagination_and_csv_export(self):
        expected = {
            "eligible": {"young@example.org", "birthday@example.org"},
            "ineligible": {"older@example.org", "born_today@example.org"},
            "unknown": {row["email"] for row in self.rows} - {
                "young@example.org", "born_today@example.org", "birthday@example.org", "older@example.org",
            },
        }
        for eligibility, emails in expected.items():
            with self.subTest(eligibility=eligibility):
                filters = {"eligibility": eligibility, "per_page": "1"}
                page = self.repository.page(filters)
                self.assertEqual(len(emails), page["total"])
                self.assertEqual(1, len(page["data"]))
                self.assertIn(page["data"][0]["email"], emails)
                second = self.repository.page({**filters, "page": "2"})
                self.assertNotEqual(page["data"][0]["id"], second["data"][0]["id"])
                self.assertEqual(emails, {row["email"] for row in self.repository.export_rows(filters)})
                exported = list(csv.reader(StringIO("".join(export_candidates(filters)).lstrip("\ufeff"))))
                self.assertEqual(emails, {row[2] for row in exported[1:]})
        self.assertEqual(len(self.rows), self.repository.page({})["total"])
        self.assertEqual(len(self.rows), self.repository.page({"eligibility": "all"})["total"])

    def test_age_filters_combine_with_existing_literal_search(self):
        result = self.repository.page({"eligibility": "eligible", "search": "young", "status": "pending"})
        self.assertEqual(1, result["total"])
        self.assertEqual("young@example.org", result["data"][0]["email"])

    def test_real_bson_ranges_handle_february_29_without_overlap(self):
        self.collection.delete_many({})
        self.collection.insert_many([
            {"label": "feb28", "date_of_birth": datetime(2008, 2, 28), "desired_training": "Hackeuse"},
            {"label": "feb29", "date_of_birth": datetime(2008, 2, 29), "desired_training": "Hackeuse"},
            {"label": "mar1", "date_of_birth": datetime(2008, 3, 1), "desired_training": "Hackeuse"},
        ])
        for today, eligible in (
            (date(2026, 2, 28), set()),
            (date(2026, 3, 1), {"feb28"}),
            (date(2026, 3, 2), {"feb28", "feb29", "mar1"}),
        ):
            with self.subTest(today=today):
                self.assertEqual(eligible, {row["label"] for row in self.collection.find(
                    age_eligibility_filter("eligible", today=today, catalog=CATALOG),
                )})
                ineligible = {row["label"] for row in self.collection.find(
                    age_eligibility_filter("ineligible", today=today, catalog=CATALOG),
                )}
                self.assertEqual({"feb28", "feb29", "mar1"} - eligible, ineligible)

    def test_bson_dates_before_year_one_are_unknown_but_year_one_is_valid(self):
        self.collection.delete_many({})
        self.collection.insert_many([
            {"label": "before_year_one", "date_of_birth": DatetimeMS(-62135596800001), "desired_training": "Dev Web"},
            {"label": "year_one", "date_of_birth": datetime(1, 1, 1), "desired_training": "Dev Web"},
        ])
        # Only project labels: default Python datetime decoding cannot represent year zero.
        for mode, expected in (("unknown", {"before_year_one"}), ("ineligible", {"year_one"}), ("eligible", set())):
            with self.subTest(mode=mode):
                self.assertEqual(expected, {row["label"] for row in self.collection.find(
                    age_eligibility_filter(mode, today=self.today, catalog=CATALOG), {"label": 1},
                )})

    def test_rules_are_per_referential_and_include_full_endpoint_ages(self):
        self.collection.delete_many({})
        cases = [
            ("startup35", "Startup School", datetime(1991, 11, 17), "eligible"),
            ("startup_title35", "Startup School – Entrepreneuriat", datetime(1991, 11, 17), "eligible"),
            ("startup_code35", "startup-school", datetime(1991, 11, 17), "eligible"),
            ("tech35", "TECH - BROADBAND", datetime(1991, 11, 17), "eligible"),
            ("dev35", "Développement Web", datetime(1991, 11, 17), "ineligible"),
            ("startup24", "Startup School", datetime(2002, 11, 17), "ineligible"),
            ("startup25", "Startup School", datetime(2001, 11, 17), "eligible"),
            ("startup40", "Startup School", datetime(1986, 11, 17), "eligible"),
            ("startup40lastday", "Startup School", datetime(1985, 11, 18), "eligible"),
            ("startup41", "Startup School", datetime(1985, 11, 17), "ineligible"),
            ("dev30lastday", "Dev Web", datetime(1995, 11, 18), "eligible"),
            ("dev31", "Dev Web", datetime(1995, 11, 17), "ineligible"),
            ("hack18birthday", "Hackeuse", datetime(2008, 11, 17), "ineligible"),
            ("hack18nextday", "Hackeuse", datetime(2008, 11, 16), "eligible"),
            ("hack80", "Hackeuse", datetime(1946, 11, 17), "eligible"),
            ("cyber35", "Cyber Security", datetime(1991, 11, 17), "unknown"),
            ("unrecognized35", "Nonexistent programme", datetime(1991, 11, 17), "unknown"),
            ("non_scalar_formation", ["Dev Web"], datetime(2000, 1, 1), "unknown"),
        ]
        self.collection.insert_many([{"label": label, "desired_training": training, "date_of_birth": birth}
                                     for label, training, birth, _ in cases])
        groups = {}
        for mode in ("eligible", "ineligible", "unknown"):
            groups[mode] = {row["label"] for row in self.collection.find(
                age_eligibility_filter(mode, today=self.today, catalog=CATALOG),
            )}
            self.assertEqual({label for label, _, _, expected in cases if expected == mode}, groups[mode])
        self.assertFalse(groups["eligible"] & groups["ineligible"])
        self.assertFalse(groups["eligible"] & groups["unknown"])
        self.assertFalse(groups["ineligible"] & groups["unknown"])
        self.assertEqual(len(cases), sum(map(len, groups.values())))

    def test_ambiguous_alias_and_conflicting_metadata_are_unknown(self):
        catalog = deepcopy(CATALOG)
        catalog[0]["aliases"].append("Shared Alias")
        catalog[1]["aliases"].append("Shared Alias")
        catalog[2]["level"] = "Agé de 18 à 40 ans ou âgé de 25 à 40 ans"
        self.collection.delete_many({})
        self.collection.insert_many([
            {"label": "ambiguous", "desired_training": "Shared Alias", "date_of_birth": datetime(2000, 1, 1)},
            {"label": "conflicting", "desired_training": "Tech Broadband", "date_of_birth": datetime(2000, 1, 1)},
        ])
        self.assertEqual({"ambiguous", "conflicting"}, {row["label"] for row in self.collection.find(
            age_eligibility_filter("unknown", today=self.today, catalog=catalog),
        )})
        for mode in ("eligible", "ineligible"):
            self.assertEqual(0, self.collection.count_documents(age_eligibility_filter(mode, today=self.today, catalog=catalog)))


if __name__ == "__main__":
    unittest.main()
