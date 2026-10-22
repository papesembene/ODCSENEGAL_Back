"""Candidate reads use synthetic records in a disposable local database only."""

import csv
from datetime import datetime, timezone
from io import StringIO
import os
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import uuid4

from bson import ObjectId
from flask import Flask
from mongoengine import connect, disconnect
from pymongo.monitoring import CommandListener

from app.models.candidature import Candidature
from app.repositories.candidature_read_repository import CandidatureReadRepository
from app.routes.candidature_routes import candidature_bp
from app.services.candidatures.export_service import export_candidates
from app.models.test_result import TestResult
from app.models.test_session import TestSession
from app.services.tests.test_result_queries import TestResultQueries
from app.services.tests.test_session_service import TestSessionService, TestSessionServiceError
from app.services.tests.test_group_service import TestGroupService


class QueryRecorder(CommandListener):
    def __init__(self):
        self.commands = []

    def started(self, event):
        self.commands.append(dict(event.command))

    def succeeded(self, event):
        pass

    def failed(self, event):
        pass


@unittest.skipUnless(os.getenv("TEST_CANDIDATE_MONGO") == "1", "requires disposable MongoDB on localhost:27027")
class CandidatureQueriesIntegrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.name = "odc_candidate_queries_" + uuid4().hex
        cls.recorder = QueryRecorder()
        cls.client = connect(cls.name, host="mongodb://127.0.0.1:27027", serverSelectionTimeoutMS=3000,
                             event_listeners=[cls.recorder])
        cls.client.admin.command("ping")
        cls.repository = CandidatureReadRepository()
        app = Flask(__name__)
        app.register_blueprint(candidature_bp, url_prefix="/api/admin")
        cls.http = app.test_client()

    @classmethod
    def tearDownClass(cls):
        cls.client.drop_database(cls.name)
        disconnect()

    def setUp(self):
        Candidature.drop_collection()
        Candidature.ensure_indexes()
        now = datetime.now(timezone.utc).replace(hour=12, minute=0, second=0, microsecond=0)
        self.rows = [{"_id": ObjectId(f"{index + 1:024x}"), "first_name": f"Candidat {index}", "last_name": "Ba",
                      "email": f"candidate{index}@example.org", "phone": f"+22178{index:07d}",
                      "gender": "Homme" if index % 2 else "FEMALE", "nationality": "Senegalaise",
                      "desired_training": "dev-web-mobile" if index % 2 else "Data", "status": "accepted" if index % 3 else "rejected",
                      "created_at": now, "cni_or_passport_number": f"PRIVATE-{index}"}
                     for index in range(235)]
        self.rows[-1].update(first_name="\u00c9milie", last_name="Diop", nationality="S\u00e9n\u00e9galaise",
                             phone="+221 77 123-45-67", desired_training="Dev Web", gender=" f\u00e9minin ")
        Candidature._get_collection().insert_many(self.rows)
        self.recorder.commands.clear()

    def test_pages_are_bounded_stable_and_projected(self):
        first = self.repository.page({})
        second = self.repository.page({"page": "2"})
        self.assertEqual(235, first["total"])
        self.assertEqual(20, len(first["data"]))
        self.assertEqual(str(self.rows[-1]["_id"]), first["data"][0]["id"])
        self.assertFalse({row["id"] for row in first["data"]} & {row["id"] for row in second["data"]})
        self.assertNotIn("cni_or_passport_number", first["data"][0])
        reads = [command for command in self.recorder.commands if command.get("find") == "candidature"]
        self.assertEqual([20, 20], [command["limit"] for command in reads])

    def test_search_handles_case_accents_full_names_and_phone_spacing(self):
        for text in ("EMILIE", "  emilie   diop  ", "Diop \u00c9MILIE", "E\u0301milie Diop", "+221771234567", "77 123 45 67"):
            with self.subTest(text=text):
                result = self.repository.page({"search": text})
                self.assertEqual(1, result["total"])
                self.assertEqual("candidate234@example.org", result["data"][0]["email"])
        self.assertEqual(235, self.repository.page({"search": "senegalaise"})["total"])

    def test_user_input_is_literal_not_an_executable_regular_expression(self):
        for text in (".*", "[", "(a+)+$", "\\"):
            with self.subTest(text=text):
                self.assertEqual(0, self.repository.page({"search": text})["total"])

    def test_filters_apply_before_pagination_and_accept_legacy_labels(self):
        filters = {"desired_training": "dev-web-mobile", "gender": "female", "search": "emilie", "per_page": "10"}
        self.assertEqual(1, self.repository.page(filters)["total"])
        Candidature._get_collection().update_one({"_id": self.rows[-1]["_id"]}, {"$set": {"status": "interviewed"}})
        self.assertEqual(1, self.repository.page({"search": "emilie", "status": "interview"})["total"])
        Candidature._get_collection().update_one({"_id": self.rows[-1]["_id"]}, {"$unset": {"status": ""}})
        self.assertEqual(1, self.repository.page({"search": "emilie", "status": "pending"})["total"])

    def test_invalid_parameters_and_empty_pages(self):
        for filters in ({"per_page": "101"}, {"page": "0"}, {"page": "bad"}, {"per_page": ""},
                        {"gender": "other"}, {"status": "bad"}, {"search": "a" * 201}):
            with self.subTest(filters=filters), self.assertRaises(ValueError):
                self.repository.page(filters)
        last = self.repository.page({"page": "9999", "per_page": "100"})
        self.assertEqual(3, last["pagination"]["page"])
        self.assertEqual(35, len(last["data"]))
        self.assertEqual(1, self.repository.page({"search": "missing", "page": "999"})["pagination"]["page"])

    def test_statistics_are_global_database_aggregates(self):
        result = self.repository.dashboard()
        self.assertEqual(235, result["stats"]["total"])
        self.assertEqual(118, result["formations"]["dev-web-mobile"]["total"])
        self.assertEqual(117, result["formations"]["dev-data"]["total"])
        self.assertEqual(118, result["stats"]["femmes"])
        self.assertEqual(235, sum(row["applications"] for row in result["daily"]))
        self.assertEqual(235, sum(row["value"] for row in result["nationalities"]))
        self.assertFalse(any(command.get("find") == "candidature" for command in self.recorder.commands))

    def test_exports_include_all_filtered_pages_and_escape_formulas(self):
        Candidature._get_collection().update_one({"_id": self.rows[-1]["_id"]}, {"$set": {"first_name": "=HYPERLINK(example)"}})
        rows = list(csv.reader(StringIO("".join(export_candidates({"per_page": "10"})).lstrip("\ufeff"))))
        self.assertEqual(236, len(rows))
        self.assertTrue(rows[1][0].startswith("'="))
        self.assertTrue(rows[1][3].startswith("'+221"))
        filtered = list(csv.reader(StringIO("".join(export_candidates({"desired_training": "dev-data"})).lstrip("\ufeff"))))
        self.assertEqual(118, len(filtered))

    def test_empty_summary_and_export(self):
        Candidature.drop_collection()
        self.assertEqual(0, self.repository.dashboard()["stats"]["total"])
        self.assertEqual(1, len(list(csv.reader(StringIO("".join(export_candidates({})).lstrip("\ufeff"))))))

    def test_result_search_and_export_use_the_same_accent_and_phone_rules(self):
        TestResult.drop_collection()
        TestResult._get_collection().insert_many([
            {"testId": "local", "testTitle": "Evaluation numerique", "referentiel": "Dev Web", "status": "admis", "score": 80,
             "candidate": {"name": "\u00c9milie Diop", "email": "emilie@example.org", "phone": "+221 77 123-45-67"},
             "completedAt": datetime.now(timezone.utc), "answers": {}, "manualGrades": {}},
            {"testId": "local", "testTitle": "Autre test", "referentiel": "Data", "status": "pending", "score": 20,
             "candidate": {"name": "Moussa Ba", "email": "moussa@example.org", "phone": "780000000"},
             "completedAt": datetime.now(timezone.utc), "answers": {}, "manualGrades": {}},
        ])
        for search in ("  EMILIE   DIOP ", "diop emilie", "EMILIE@EXAMPLE.ORG", "+221771234567", "Evaluation numerique"):
            with self.subTest(search=search):
                result = TestResultQueries.page({"search": search})
                self.assertEqual(1, result["total"])
                self.assertEqual("emilie@example.org", result["data"][0]["candidate"]["email"])
        exported = "".join(TestResultQueries.export({"search": "emilie", "per_page": "1"}))
        self.assertIn("emilie@example.org", exported)
        self.assertNotIn("moussa@example.org", exported)
        self.assertEqual(0, TestResultQueries.page({"search": ".*"})["total"])
        with self.assertRaises(ValueError):
            TestResultQueries.page({"search": "a" * 201})

    def test_session_search_and_group_selection_share_candidate_search_rules(self):
        TestSession.drop_collection()
        TestSession(testId="local", candidateName="\u00c9milie Diop", candidateEmail="emilie@example.org",
                    candidatePhone="+221 77 123-45-67").save()
        for search in ("diop EMILIE", "+221771234567"):
            self.assertEqual(1, TestSessionService._build_admin_query({"search": search}).count())
        with self.assertRaises(TestSessionServiceError):
            TestSessionService._build_admin_query({"search": "a" * 201})
        with patch.object(TestGroupService, "_assigned_candidate_ids", return_value=set()):
            result = TestGroupService.list_available_candidates("dev-web-mobile", search="EMILIE DIOP", per_page=10)
            self.assertEqual(1, result["total"])
            self.assertEqual("candidate234@example.org", result["data"][0]["email"])

    def test_http_routes_validate_and_enforce_platform_admin_permissions(self):
        paths = ("/api/admin/candidatures?page=1", "/api/admin/candidatures/dashboard", "/api/admin/candidatures/export")
        for path in paths:
            self.assertEqual(401, self.http.get(path).status_code)
        headers = {"Authorization": "Bearer local-test-token"}
        with patch("app.utils.auth_decorators.AuthService.verify_token", return_value=SimpleNamespace(
            is_admin=True, admin_type="super_admin", profile_data={},
        )):
            self.assertEqual(200, self.http.get(paths[0], headers=headers).status_code)
            self.assertEqual(200, self.http.get(paths[1], headers=headers).status_code)
            self.assertEqual(400, self.http.get(paths[0] + "&per_page=101", headers=headers).status_code)
            self.assertEqual(400, self.http.get(paths[1] + "?days=bad", headers=headers).status_code)
            self.assertEqual(400, self.http.get(paths[2] + "?status=bad", headers=headers).status_code)
            self.assertEqual(236, len(list(csv.reader(StringIO(self.http.get(paths[2], headers=headers).text.lstrip("\ufeff"))))))
        with patch("app.utils.auth_decorators.AuthService.verify_token", return_value=SimpleNamespace(
            is_admin=True, admin_type="competences", profile_data={"admin_scope": "interview_member"},
        )):
            for path in paths:
                self.assertEqual(403, self.http.get(path, headers=headers).status_code)


if __name__ == "__main__":
    unittest.main()
