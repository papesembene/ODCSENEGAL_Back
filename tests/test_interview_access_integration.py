"""Optional real-Mongo checks: TEST_LOCAL_MONGO=1, isolated disposable database."""

import os
import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from bson import ObjectId
from flask import Flask
from mongoengine import connect, disconnect

from app.models.interview import InterviewCampaign, InterviewEvaluation, InterviewSlot
from app.routes.interview_routes import interview_bp
from app.services.interviews.evaluation_service import InterviewEvaluationService
from app.services.interviews.query_service import InterviewQueryService


@unittest.skipUnless(os.getenv("TEST_LOCAL_MONGO") == "1", "requires local MongoDB")
class InterviewAccessIntegrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db_name = "odc_interview_access_test_" + uuid4().hex
        cls.connection = connect(cls.db_name, host="mongodb://127.0.0.1:27017", serverSelectionTimeoutMS=3000)
        cls.connection.admin.command("ping")

    @classmethod
    def tearDownClass(cls):
        cls.connection.drop_database(cls.db_name)
        disconnect()

    def setUp(self):
        InterviewEvaluation.drop_collection()
        InterviewSlot.drop_collection()
        InterviewCampaign.drop_collection()
        self.now = datetime(2026, 10, 19, 12)
        self.admin = SimpleNamespace(
            id=ObjectId(), admin_type="competences", is_admin=True, is_active=True,
            email="jury@example.com",
            profile_data={"admin_scope": "interview_member", "interview_role": "filter"},
            first_name="Awa", last_name="Diop",
        )
        self.query = InterviewQueryService(now=lambda: self.now)
        self.evaluations = InterviewEvaluationService(query_service=self.query, now=lambda: self.now)
        self.campaign = InterviewCampaign(name="Access test", formation="data").save()
        self.slots = {}
        self.records = {}
        for name, start, end in (
            ("past", -2, -1), ("current", -1, 1), ("future", 1, 2),
        ):
            slot = InterviewSlot(
                campaign_id=str(self.campaign.id), label=name, formation="data",
                start_at=self.now + timedelta(hours=start), end_at=self.now + timedelta(hours=end),
                assigned_filter_ids=[str(self.admin.id)],
            ).save()
            self.slots[name] = slot
            self.records[name] = InterviewEvaluation(
                campaign_id=str(self.campaign.id), slot_id=str(slot.id),
                candidature_id=str(ObjectId()), candidate_snapshot={"email": name + "@example.com"},
            ).save()
        app = Flask(__name__)
        app.register_blueprint(interview_bp, url_prefix="/api/admin")
        self.client = app.test_client()
        self.auth = patch("app.utils.auth_decorators.AuthService.verify_token", return_value=self.admin)
        self.auth.start()
        self.addCleanup(self.auth.stop)
        for name, service in (("query_service", self.query), ("evaluation_service", self.evaluations)):
            patched = patch("app.routes.interview_routes." + name, service)
            patched.start()
            self.addCleanup(patched.stop)
        self.headers = {"Authorization": "Bearer access-test"}

    def get(self, path):
        return self.client.get("/api/admin/interviews/" + path, headers=self.headers)

    def test_bootstrap_slots_and_evaluations_hide_past_and_future(self):
        bootstrap = self.get("bootstrap")
        self.assertEqual(200, bootstrap.status_code)
        data = bootstrap.json["data"]
        self.assertEqual(["current"], [slot["label"] for slot in data["slots"]])
        self.assertEqual(["filter"], data["slots"][0]["access"]["editable_roles"])
        self.assertTrue(data["server_now"].endswith("Z"))
        self.assertEqual(["current"], [slot["label"] for slot in self.get("slots").json["data"]])
        page = self.get("evaluations?pageSize=25")
        self.assertEqual([str(self.records["current"].id)], [item["id"] for item in page.json["data"]])

    def test_direct_slot_filter_and_csv_cannot_bypass_window(self):
        response = self.get("evaluations?slotId=" + str(self.slots["future"].id))
        self.assertEqual([], response.json["data"])
        csv = self.get("evaluations/export").get_data(as_text=True)
        self.assertIn("current@example.com", csv)
        self.assertNotIn("past@example.com", csv)
        self.assertNotIn("future@example.com", csv)

    def test_filter_patch_after_end_is_403_without_persisting(self):
        self.now = self.slots["current"].end_at
        response = self.client.patch(
            "/api/admin/interviews/evaluations/" + str(self.records["current"].id),
            headers=self.headers, json={"filter_review": {}},
        )
        self.assertEqual(403, response.status_code)
        self.assertEqual({}, self.records["current"].reload().filter_review)
        self.assertNotIn("current", [slot["label"] for slot in self.get("slots").json["data"]])

    def test_validator_can_read_and_save_own_section_after_end(self):
        slot = self.slots["past"]
        slot.assigned_validator_ids = [str(self.admin.id)]
        slot.save()
        response = self.client.patch(
            "/api/admin/interviews/evaluations/" + str(self.records["past"].id),
            headers=self.headers, json={"validator_review": {}},
        )
        self.assertEqual(200, response.status_code)
        self.assertEqual(str(self.admin.id), self.records["past"].reload().validator_review["_owner_admin_id"])
        slots = self.get("slots").json["data"]
        past = next(item for item in slots if item["label"] == "past")
        self.assertEqual(["validator"], past["access"]["editable_roles"])

    def test_validator_elsewhere_does_not_unlock_filter_slot(self):
        self.slots["past"].assigned_validator_ids = [str(self.admin.id)]
        self.slots["past"].save()
        self.now = self.slots["current"].end_at
        visible_ids = self.query._get_assigned_slot_ids(self.admin)
        self.assertIn(str(self.slots["past"].id), visible_ids)
        self.assertNotIn(str(self.slots["current"].id), visible_ids)

    def test_filter_cannot_save_a_future_slot_even_with_direct_url(self):
        response = self.client.patch(
            "/api/admin/interviews/evaluations/" + str(self.records["future"].id),
            headers=self.headers, json={"filter_review": {}},
        )
        self.assertEqual(403, response.status_code)
        self.assertEqual({}, self.records["future"].reload().filter_review)

    def test_mixed_payload_cannot_write_expired_filter_review(self):
        self.slots["past"].assigned_validator_ids = [str(self.admin.id)]
        self.slots["past"].save()
        response = self.client.patch(
            "/api/admin/interviews/evaluations/" + str(self.records["past"].id),
            headers=self.headers, json={"filter_review": {}, "validator_review": {}},
        )
        self.assertEqual(403, response.status_code)
        evaluation = self.records["past"].reload()
        self.assertEqual({}, evaluation.filter_review)
        self.assertEqual({}, evaluation.validator_review)

    def test_members_cannot_reschedule_slots_or_create_campaigns(self):
        for method, path, data in (
            ("patch", "slots/" + str(self.slots["past"].id), {"end_at": "2030-01-01T12:00"}),
            ("post", "slots", {}), ("post", "campaigns", {}),
            ("patch", "campaigns/" + str(self.campaign.id), {"status": "active"}),
            ("post", "evaluations/seed", {}),
        ):
            with self.subTest(path=path):
                response = getattr(self.client, method)(
                    "/api/admin/interviews/" + path, headers=self.headers, json=data,
                )
                self.assertEqual(403, response.status_code)

    def test_planning_admin_keeps_all_slots(self):
        self.admin.profile_data = {}
        self.assertEqual(3, len(self.get("slots").json["data"]))


if __name__ == "__main__":
    unittest.main()
