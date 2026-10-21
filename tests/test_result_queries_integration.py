"""Result queries operate only on a disposable local MongoDB database."""

import csv
from datetime import datetime
from io import StringIO
import os
import unittest
from uuid import uuid4

from bson import ObjectId
from mongoengine import connect, disconnect
from pymongo.monitoring import CommandListener

from app.models.test import Question, Test
from app.models.test_result import TestResult
from app.models.test_violation import TestViolation
from app.services.tests.test_result_queries import TestResultQueries


class QueryRecorder(CommandListener):
    def __init__(self):
        self.commands = []

    def started(self, event):
        self.commands.append(dict(event.command))

    def succeeded(self, event):
        pass

    def failed(self, event):
        pass


@unittest.skipUnless(os.getenv("TEST_LOCAL_MONGO") == "1", "requires disposable local MongoDB")
class ResultQueriesIntegrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.name = "odc_result_query_test_" + uuid4().hex
        cls.recorder = QueryRecorder()
        cls.client = connect(cls.name, host="mongodb://127.0.0.1:27017", serverSelectionTimeoutMS=3000,
                             event_listeners=[cls.recorder])
        cls.client.admin.command("ping")

    @classmethod
    def tearDownClass(cls):
        cls.client.drop_database(cls.name)
        disconnect()

    def setUp(self):
        for model in (Test, TestResult, TestViolation):
            model.drop_collection()
            model.ensure_indexes()
        self.test = Test(title="Local pagination", referentiel="Dev Web", duration=60,
                         scheduledDate="2026-10-21", scheduledTime="10:00", totalQuestions=1,
                         questions=[Question(question="Q", type="qcm_simple", score=5, correctAnswer=1)]).save()
        self.rows = [{"_id": ObjectId(f"{index + 1:024x}"), "testId": str(self.test.id),
                      "testTitle": self.test.title, "referentiel": "Data" if index % 2 else "dev-web-mobile",
                      "candidate": {"name": f"Candidate {index}", "email": f"candidate{index}@example.org", "phone": "+221771234567"},
                      "score": index % 6 * 20, "status": ("admis", "rejeté", "pending")[index % 3],
                      "completedAt": datetime(2026, 10, 21, 10), "answers": {"0": 1}, "manualGrades": {}}
                     for index in range(225)]
        TestResult._get_collection().insert_many(self.rows)
        self.recorder.commands.clear()

    def test_pages_are_bounded_stable_and_do_not_send_answers(self):
        first = TestResultQueries.page({})
        second = TestResultQueries.page({"page": "2"})
        self.assertEqual(225, first["total"])
        self.assertEqual(20, len(first["data"]))
        self.assertEqual(12, first["pagination"]["total_pages"])
        self.assertFalse({item["id"] for item in first["data"]} & {item["id"] for item in second["data"]})
        self.assertEqual(str(self.rows[-1]["_id"]), first["data"][0]["id"])
        self.assertNotIn("answers", first["data"][0])
        self.assertNotIn("manualGrades", first["data"][0])
        self.assertEqual({"obtained": 5, "total": 5}, first["data"][0]["points"])
        reads = [command for command in self.recorder.commands if command.get("find") == "test_results"]
        self.assertEqual([20, 20], [command.get("limit") for command in reads])

    def test_alias_and_status_filters_work_before_pagination(self):
        result = TestResultQueries.page({"referentiel": "Dev Web", "status": "en_attente", "per_page": "10"})
        expected = [row for row in self.rows if row["referentiel"] == "dev-web-mobile" and row["status"] == "pending"]
        self.assertEqual(len(expected), result["total"])
        self.assertEqual(10, len(result["data"]))
        self.assertTrue(all(item["status"] == "pending" and item["referentiel"] == "dev-web-mobile" for item in result["data"]))
        self.assertEqual(0, TestResultQueries.page({"testId": "missing"})["total"])

    def test_invalid_pagination_is_rejected_and_stale_pages_are_clamped(self):
        for filters in ({"page": "0"}, {"page": "no"}, {"per_page": "101"}, {"per_page": "-1"}, {"status": "invalid"}):
            with self.subTest(filters=filters), self.assertRaises(ValueError):
                TestResultQueries.page(filters)
        last = TestResultQueries.page({"page": "9999", "per_page": "100"})
        self.assertEqual(3, last["pagination"]["page"])
        self.assertEqual(25, len(last["data"]))
        empty = TestResultQueries.page({"testId": "missing", "page": "9999"})
        self.assertEqual(1, empty["pagination"]["page"])
        self.assertEqual([], empty["data"])

    def test_violations_are_projected_for_the_page_not_mixed_between_candidates(self):
        last = self.rows[-1]
        TestViolation(testId=str(self.test.id), candidateEmail=last["candidate"]["email"], totalViolations=8).save()
        result = TestResultQueries.page({})
        self.assertEqual({"totalViolations": 8}, result["data"][0]["violationSummary"])
        self.assertEqual({"totalViolations": 0}, result["data"][1]["violationSummary"])
        reads = [command for command in self.recorder.commands if command.get("find") == "test_violations"]
        self.assertEqual(1, len(reads))
        self.assertEqual(20, len(reads[0]["filter"]["$or"]))
        self.assertNotIn("violations", reads[0]["projection"])

    def test_statistics_are_database_aggregates_not_page_counts(self):
        result = TestResultQueries.statistics()
        self.assertEqual(225, result["total"])
        self.assertEqual(75, result["admis"])
        self.assertEqual(75, result["rejetes"])
        self.assertEqual(75, result["pending"])
        self.assertEqual(round(sum(row["score"] for row in self.rows) / 225, 2), result["average_score"])
        self.assertEqual(225, sum(item["count"] for item in result["score_distribution"]))
        self.assertEqual(0, len([command for command in self.recorder.commands if command.get("find") == "test_results"]))
        grouped = TestResultQueries.performance_by_referential()
        self.assertEqual(225, sum(item["total"] for item in grouped))
        self.assertEqual(113, TestResultQueries.statistics({"referentiel": "Dev Web"})["total"])

    def test_export_is_complete_filtered_and_escapes_spreadsheet_formulas(self):
        TestResult.objects(id=self.rows[-1]["_id"]).update_one(set__candidate__name="=HYPERLINK(\"example\")")
        stream = TestResultQueries.export({"per_page": "10"})
        self.assertNotIsInstance(stream, list)
        rows = list(csv.reader(StringIO("".join(stream).lstrip("\ufeff"))))
        self.assertEqual(226, len(rows))
        self.assertTrue(rows[1][0].startswith("'="))
        self.assertTrue(rows[1][2].startswith("'+221"))
        filtered = list(csv.reader(StringIO("".join(TestResultQueries.export({"referentiel": "Dev Web", "status": "pending"})).lstrip("\ufeff"))))
        self.assertEqual(TestResultQueries.page({"referentiel": "Dev Web", "status": "pending"})["total"] + 1, len(filtered))

    def test_empty_aggregates_and_exports_remain_well_formed(self):
        TestResult.drop_collection()
        self.assertEqual(0, TestResultQueries.statistics()["total"])
        self.assertEqual([], TestResultQueries.performance_by_referential())
        self.assertEqual(1, len(list(csv.reader(StringIO("".join(TestResultQueries.export({})).lstrip("\ufeff"))))))
