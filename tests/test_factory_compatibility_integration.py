"""Validate the upgraded Flask stack on an isolated local database."""

from datetime import datetime, timedelta
import os
import unittest
from uuid import uuid4
from unittest.mock import Mock, PropertyMock, patch

from mongoengine import disconnect, get_connection
from werkzeug.security import generate_password_hash

from app import create_app
from app.config import Config
from app.models.user import User
from app.models.candidature import Candidature
from app.models.test import Question, Test
from app.models.test_group import TestGroup
from app.models.test_result import TestResult
from app.models.test_session import TestSession
from app.models.test_violation import TestViolation
from app.models.email_job import EmailJob


@unittest.skipUnless(os.getenv("TEST_LOCAL_MONGO") == "1", "requires disposable local MongoDB")
class FactoryCompatibilityIntegrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db_name = "odc_factory_test_" + uuid4().hex

        class LocalTestConfig(Config):
            TESTING = True
            ENVIRONMENT = "development"
            SECRET_KEY = "test-factory-secret-" + "a" * 32
            JWT_SECRET_KEY = "test-factory-jwt-" + "b" * 32
            JWT_EXPIRATION_DELTA = timedelta(hours=1)
            SESSION_TYPE = "filesystem"
            CORS_ALLOWED_ORIGINS = ["https://test.example.org"]
            RUN_INDEX_MAINTENANCE = False
            MONGODB_SETTINGS = {
                **Config.MONGODB_SETTINGS,
                "db": cls.db_name, "host": "mongodb://127.0.0.1:27017",
                "connect": False, "serverSelectionTimeoutMS": 3000,
            }

        cls.app = create_app(LocalTestConfig)
        cls.connection = get_connection()
        cls.connection.admin.command("ping")

    @classmethod
    def tearDownClass(cls):
        cls.connection.drop_database(cls.db_name)
        disconnect()

    def setUp(self):
        User.drop_collection()
        self.user = User(
            email="admin@example.org", first_name="Test", last_name="Admin",
            profile_type="student", is_admin=True, admin_type="super_admin",
            password_hash=generate_password_hash("Test-password-only", method="pbkdf2:sha256:600000"),
        ).save()
        self.client = self.app.test_client()
        address = uuid4().bytes
        self.client.environ_base["REMOTE_ADDR"] = f"127.1.{address[0]}.{address[1]}"

    def login(self):
        return self.client.post("/api/admin/login", json={
            "email": self.user.email, "password": "Test-password-only",
        }, headers={"Origin": "https://test.example.org"})

    def test_existing_pbkdf2_password_and_jwt_still_work(self):
        response = self.login()
        self.assertEqual(200, response.status_code, response.json)
        self.assertNotIn("password_hash", response.json["user"])
        token = response.json["token"]
        result = self.client.get("/api/admin/interviews/bootstrap", headers={"Authorization": "Bearer " + token})
        self.assertEqual(200, result.status_code, result.json)

    def test_cors_allows_only_the_configured_origin(self):
        response = self.login()
        self.assertEqual("https://test.example.org", response.headers.get("Access-Control-Allow-Origin"))
        rejected = self.client.options("/api/admin/login", headers={
            "Origin": "https://other.example.org", "Access-Control-Request-Method": "POST",
        })
        self.assertIsNone(rejected.headers.get("Access-Control-Allow-Origin"))

    def test_queue_tracking_requires_an_authenticated_admin(self):
        result = self.client.get("/api/admin/test-groups/" + uuid4().hex[:24] + "/invitations/status")
        self.assertEqual(401, result.status_code)
        self.assertEqual(401, self.client.post("/api/admin/tests/results/import", json={}).status_code)
        self.assertEqual(401, self.client.get("/api/admin/tests/results/export").status_code)

    def test_result_pages_and_streaming_export_are_wired_to_admin_routes(self):
        self.seed_online_test()
        headers = {"Authorization": "Bearer " + self.login().json["token"]}
        page = self.client.get("/api/admin/tests/results?page=1&per_page=20", headers=headers)
        self.assertEqual(200, page.status_code, page.json)
        self.assertEqual(0, page.json["total"])
        self.assertEqual(1, page.json["pagination"]["page"])
        self.assertEqual(400, self.client.get("/api/admin/tests/results?per_page=101", headers=headers).status_code)
        exported = self.client.get("/api/admin/tests/results/export", headers=headers)
        self.assertEqual(200, exported.status_code)
        self.assertIn("text/csv", exported.content_type)
        self.assertIn("Email", exported.get_data(as_text=True))

    def test_new_password_hashes_are_supported(self):
        self.user.set_password("Another-test-password")
        self.user.save()
        self.assertTrue(self.user.reload().check_password("Another-test-password"))
        self.assertFalse(self.user.check_password("incorrect"))

    def test_interview_member_cannot_retry_test_invitations(self):
        self.user.admin_type = "competences"
        self.user.profile_data = {"admin_scope": "interview_member", "interview_role": "filter"}
        self.user.save()
        token = self.login().json["token"]
        response = self.client.post(
            "/api/admin/test-groups/" + uuid4().hex[:24] + "/invitations/retry",
            headers={"Authorization": "Bearer " + token},
        )
        self.assertEqual(403, response.status_code)
        imported = self.client.post("/api/admin/tests/results/import", json={}, headers={"Authorization": "Bearer " + token})
        self.assertEqual(403, imported.status_code)

    def test_candidate_content_requires_identity_and_never_exposes_answers(self):
        Candidature.drop_collection()
        candidate = Candidature._get_collection().insert_one({
            "email": "candidate@example.org", "first_name": "Local", "last_name": "Test", "phone": "+221771234567",
        })
        now = datetime.utcnow() - timedelta(minutes=1)
        test = Test(title="Protected", referentiel="Dev Web", duration=60, totalQuestions=1,
                    scheduledDate=now.strftime("%Y-%m-%d"), scheduledTime=now.strftime("%H:%M"),
                    questions=[Question(question="Question", type="qcm_simple", options=["A", "B"], correctAnswer=1, score=5)]).save()
        TestGroup(name="Protected", formation="Dev Web", test_id=str(test.id), test_date=now,
                  candidate_ids=[str(candidate.inserted_id)]).save()
        url = "/api/admin/tests/" + str(test.id)
        self.assertEqual(401, self.client.get(url).status_code)
        self.assertNotEqual(200, self.client.post(url + "/content", json={}).status_code)
        content = self.client.post(url + "/content", json={"email": "candidate@example.org", "phone": "771234567"})
        self.assertEqual(200, content.status_code, content.json)
        self.assertEqual("no-store", content.headers["Cache-Control"])
        question = content.json["data"]["questions"][0]
        self.assertEqual(["A", "B"], question["options"])
        self.assertNotIn("correctAnswer", question)
        self.assertNotIn("correctAnswers", question)
        self.assertNotIn("connectionLogs", content.json["data"])
        token = self.login().json["token"]
        admin = self.client.get(url, headers={"Authorization": "Bearer " + token})
        self.assertEqual(1, admin.json["data"]["questions"][0]["correctAnswer"])

    def seed_online_test(self):
        for model in (Candidature, Test, TestGroup, TestResult, TestSession, TestViolation, EmailJob):
            model.drop_collection()
        candidate = Candidature._get_collection().insert_one({
            "email": "candidate@example.org", "first_name": "Local", "last_name": "Test", "phone": "+221771234567",
        })
        now = datetime.utcnow() - timedelta(minutes=1)
        test = Test(title="Release safety", referentiel="Dev Web", duration=5, totalQuestions=1,
                    scheduledDate=now.strftime("%Y-%m-%d"), scheduledTime=now.strftime("%H:%M"),
                    questions=[Question(question="Question", type="qcm_simple", options=["A", "B"], correctAnswer=1, score=5)]).save()
        TestGroup(name="Release", formation="Dev Web", test_id=str(test.id), test_date=now,
                  duration=5, candidate_ids=[str(candidate.inserted_id)]).save()
        payload = {"testId": str(test.id), "candidate": {
            "name": "Local Test", "email": "candidate@example.org", "phone": "771234567",
        }, "answers": {"0": 1}}
        return test, payload

    def test_jury_cannot_use_admin_apis_outside_interviews(self):
        self.user.admin_type = "competences"
        self.user.profile_data = {"admin_scope": "interview_member"}
        self.user.save()
        headers = {"Authorization": "Bearer " + self.login().json["token"]}
        for path in ("tests", "test-groups", "tests/results", "tests/sessions", "interview-members",
                     "competences/candidatures", "dashboard/statistics", "violations/all"):
            with self.subTest(path=path):
                self.assertEqual(403, self.client.get("/api/admin/" + path, headers=headers).status_code)
        self.assertEqual(200, self.client.get("/api/admin/interviews/bootstrap", headers=headers).status_code)

    def test_violations_require_an_authenticated_planning_admin(self):
        url = "/api/admin/tests/" + uuid4().hex[:24] + "/violations/candidate@example.org"
        self.assertEqual(401, self.client.get(url).status_code)
        self.assertEqual(401, self.client.delete(url).status_code)
        self.assertEqual(401, self.client.get("/api/admin/violations/all").status_code)

    def test_candidate_violation_requires_the_current_candidate_identity(self):
        test, candidate = self.seed_online_test()
        url = "/api/admin/tests/" + str(test.id) + "/log-violation"
        event = {"candidateEmail": candidate["candidate"]["email"], "type": "copy", "message": "Copy attempted", "elapsedTime": 0}
        self.assertEqual(400, self.client.post(url, json=event).status_code)
        self.assertEqual(403, self.client.post(url, json={**event, "candidatePhone": "000000000"}).status_code)
        accepted = self.client.post(url, json={**event, "candidatePhone": "771234567", "testResultId": "forged"})
        self.assertEqual(201, accepted.status_code, accepted.json)
        self.assertEqual(1, accepted.json["data"]["totalViolations"])
        self.assertIsNone(TestViolation.objects.get().testResultId)
        invalid = self.client.post(url, json={**event, "candidatePhone": "771234567", "type": "$bad.type"})
        self.assertEqual(400, invalid.status_code)
        self.assertEqual(1, TestViolation.objects.get().totalViolations)

    def test_lost_submission_confirmation_can_be_retried_after_the_deadline(self):
        test, payload = self.seed_online_test()
        first = self.client.post("/api/admin/tests/results", json=payload)
        self.assertEqual(201, first.status_code, first.json)
        with patch("app.services.tests.test_access_service.datetime") as clock:
            clock.strptime.side_effect = datetime.strptime
            clock.now.return_value = datetime.utcnow() + timedelta(hours=2)
            retried = self.client.post("/api/admin/tests/results", json={**payload, "answers": {"0": 0}})
        self.assertEqual(200, retried.status_code, retried.json)
        self.assertTrue(retried.json["idempotent"])
        self.assertEqual(first.json["data"]["id"], retried.json["data"]["id"])
        self.assertEqual(100, TestResult.objects.get().score)
        self.assertEqual("submitted", TestSession.objects.get().status)

    def test_first_submission_after_grace_period_keeps_the_saved_draft(self):
        test, payload = self.seed_online_test()
        draft_url = "/api/admin/tests/" + str(test.id) + "/session-draft"
        saved = self.client.put(draft_url, json={**payload["candidate"], "answers": payload["answers"]})
        self.assertEqual(200, saved.status_code, saved.json)
        with patch("app.services.tests.test_access_service.datetime") as clock:
            clock.strptime.side_effect = datetime.strptime
            clock.now.return_value = datetime.utcnow() + timedelta(hours=2)
            denied = self.client.post("/api/admin/tests/results", json=payload)
        self.assertEqual(403, denied.status_code)
        self.assertEqual(0, TestResult.objects.count())
        self.assertEqual({"0": 1}, TestSession.objects.get().answers)

    def test_admin_schedule_update_invalidates_candidate_metadata_cache(self):
        test, payload = self.seed_online_test()
        url = "/api/admin/tests/" + str(test.id)
        self.assertEqual(200, self.client.get(url + "/public").status_code)
        later = datetime.utcnow() + timedelta(hours=2)
        changed = self.client.patch(url, headers={"Authorization": "Bearer " + self.login().json["token"]},
                                   json={"scheduledDate": later.strftime("%Y-%m-%d"), "scheduledTime": later.strftime("%H:%M")})
        self.assertEqual(200, changed.status_code, changed.json)
        self.assertEqual(later.strftime("%H:%M"), self.client.get(url + "/public").json["data"]["scheduledTime"])
        self.assertEqual(403, self.client.post(url + "/content", json=payload["candidate"]).status_code)

    def test_result_notification_uses_real_recipients_and_durable_queue(self):
        from app.services.invitation_queue import InvitationQueue

        _, payload = self.seed_online_test()
        submitted = self.client.post("/api/admin/tests/results", json=payload)
        self.assertEqual(201, submitted.status_code, submitted.json)
        result = submitted.json["data"]
        headers = {"Authorization": "Bearer " + self.login().json["token"]}
        notification = {"resultIds": [result["id"]], "emailType": "results_notification",
                        "customMessage": "<script>unsafe</script>", "recipients": [{"email": "forged@example.org"}]}
        with patch("app.services.email_transport.EmailTransport.is_configured", new_callable=PropertyMock, return_value=True):
            first = self.client.post("/api/admin/tests/send-emails", json=notification, headers=headers)
            repeated = self.client.post("/api/admin/tests/send-emails", json=notification, headers=headers)
        self.assertEqual(202, first.status_code, first.json)
        self.assertEqual(202, repeated.status_code, repeated.json)
        self.assertEqual(1, EmailJob.objects.count())
        transport = Mock(is_configured=True)
        transport.send_html.return_value = {"sent": True}
        self.assertTrue(InvitationQueue(transport=transport).run_once())
        self.assertEqual("sent", EmailJob.objects.get().status)
        self.assertEqual({}, EmailJob.objects.get().payload)
        recipients, subject, html = transport.send_html.call_args.args
        self.assertEqual(["candidate@example.org"], recipients)
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)

    def test_result_notification_failure_is_visible_and_retryable(self):
        from app.services.invitation_queue import InvitationQueue

        _, payload = self.seed_online_test()
        result = self.client.post("/api/admin/tests/results", json=payload).json["data"]
        headers = {"Authorization": "Bearer " + self.login().json["token"]}
        with patch("app.services.email_transport.EmailTransport.is_configured", new_callable=PropertyMock, return_value=True):
            response = self.client.post("/api/admin/tests/send-emails", headers=headers,
                                        json={"resultIds": [result["id"]], "emailType": "results_notification"})
        batch = response.json["data"]["batchId"]
        prefix = "/api/admin/tests/notifications/" + batch
        transport = Mock(is_configured=True)
        transport.send_html.return_value = {"sent": False, "retryable": False, "message": "Provider rejected"}
        InvitationQueue(transport=transport).run_once()
        summary = self.client.get(prefix + "/status", headers=headers)
        self.assertEqual(1, summary.json["data"]["failed"])
        self.assertEqual(0, summary.json["data"]["sent"])
        self.assertEqual(401, self.client.get(prefix + "/status").status_code)
        with patch("app.services.email_transport.EmailTransport.is_configured", new_callable=PropertyMock, return_value=True):
            retried = self.client.post(prefix + "/retry", headers=headers)
        self.assertEqual(1, retried.json["data"]["queued"])
        transport.send_html.return_value = {"sent": True}
        InvitationQueue(transport=transport).run_once()
        self.assertEqual(1, self.client.get(prefix + "/status", headers=headers).json["data"]["sent"])
        self.assertEqual(1, EmailJob.objects.count())

    def test_invalid_notification_batch_never_partially_queues(self):
        _, payload = self.seed_online_test()
        result = self.client.post("/api/admin/tests/results", json=payload).json["data"]
        headers = {"Authorization": "Bearer " + self.login().json["token"]}
        for ids in ([result["id"], uuid4().hex[:24]], [result["id"]] * 501, ["invalid"]):
            response = self.client.post("/api/admin/tests/send-emails", headers=headers,
                                        json={"resultIds": ids, "emailType": "results_notification"})
            self.assertEqual(400, response.status_code, response.json)
        self.assertEqual(0, EmailJob.objects.count())

    def test_no_fake_email_success_without_valid_result_selection(self):
        headers = {"Authorization": "Bearer " + self.login().json["token"]}
        response = self.client.post("/api/admin/tests/send-emails", json={"emailType": "information", "recipients": []}, headers=headers)
        self.assertEqual(400, response.status_code, response.json)
