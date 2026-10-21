"""Opt-in real Mongo checks; only a disposable local database is ever modified."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import os
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

from bson import ObjectId
from mongoengine import connect, disconnect

from app.models.candidature import Candidature
from app.models.email_job import EmailJob
from app.models.test import Question, Test
from app.models.test_group import TestGroup
from app.models.test_result import TestResult
from app.models.test_session import TestSession
from app.models.test_violation import TestViolation
from app.services.invitation_queue import InvitationQueue
from app.services.tests.test_management_service import TestManagementService
from app.services.tests.test_session_service import TestSessionService
from app.services.tests.test_violation_service import TestViolationService


@unittest.skipUnless(os.getenv("TEST_LOCAL_MONGO") == "1", "requires disposable local MongoDB")
class DeliveryAndSessionsIntegrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db_name = "odc_delivery_session_test_" + uuid4().hex
        cls.connection = connect(cls.db_name, host="mongodb://127.0.0.1:27017", serverSelectionTimeoutMS=3000)
        cls.connection.admin.command("ping")

    @classmethod
    def tearDownClass(cls):
        cls.connection.drop_database(cls.db_name)
        disconnect()

    def setUp(self):
        for model in (EmailJob, TestGroup, TestResult, TestSession, TestViolation, Test, Candidature):
            model.drop_collection()
            model.ensure_indexes()
        self.now = datetime.utcnow()
        self.test = Test(title="Concurrency", referentiel="Dev Web", duration=60,
                         scheduledDate=self.now.strftime("%Y-%m-%d"), scheduledTime=self.now.strftime("%H:%M"),
                         totalQuestions=1).save()
        self.candidate = {"email": "candidate@example.org", "phone": "770000000", "name": "Local Test"}
        self.sessions = TestSessionService()
        self.draft = {**self.candidate, "answers": {"0": 1}, "remainingTime": 60}
        self.transport = Mock(is_configured=True)
        self.transport.send_html.return_value = {"sent": True}
        self.queue = InvitationQueue(self.transport, now=lambda: self.now)

    def create_jobs(self):
        candidate_id = ObjectId()
        # Raw fixture avoids unrelated application validators; isolated test DB only.
        Candidature._get_collection().insert_one({
            "_id": candidate_id, "email": self.candidate["email"], "first_name": "Local",
            "last_name": "Test", "phone": self.candidate["phone"], "gender": "male",
        })
        group = TestGroup(name="Queue", formation="Dev Web", test_id=str(self.test.id),
                          test_date=self.now + timedelta(hours=1), candidate_ids=[str(candidate_id)]).save()
        self.queue.enqueue(group, self.test, "https://test.example.org")
        return group

    def test_late_autosave_cannot_reopen_submitted_session(self):
        self.sessions.save_draft(str(self.test.id), self.draft, {"candidate": self.candidate})
        self.sessions.mark_submitted(str(self.test.id), self.candidate["email"], self.candidate)
        result = self.sessions.save_draft(str(self.test.id), {**self.draft, "answers": {}}, {"candidate": self.candidate})
        self.assertEqual("submitted", result.status)
        self.assertEqual({"0": 1}, result.answers)

    def test_simultaneous_autosaves_create_only_one_session(self):
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(lambda _: self.sessions.save_draft(str(self.test.id), self.draft, {"candidate": self.candidate}), range(20)))
        self.assertEqual(1, TestSession.objects.count())

    def test_simultaneous_violations_preserve_every_event_and_counter(self):
        email = uuid4().hex + "@example.org"
        def record(index):
            return TestViolationService.log(str(self.test.id), {
                "candidateEmail": email, "type": "copy" if index % 2 else "blur",
                "message": "Local event", "elapsedTime": index,
            })
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(record, range(40)))
        self.assertEqual(1, TestViolation.objects.count())
        violation = TestViolation.objects.get()
        self.assertEqual(40, violation.totalViolations)
        self.assertEqual(40, len(violation.violations))
        self.assertEqual({"copy": 20, "blur": 20}, violation.stats)

    def test_submission_without_previous_autosave_is_visible_to_admin(self):
        self.sessions.mark_submitted(str(self.test.id), self.candidate["email"], self.candidate)
        self.assertEqual("submitted", TestSession.objects.get().status)

    def test_simultaneous_submissions_produce_one_result(self):
        payload = {"testId": str(self.test.id), "testTitle": self.test.title, "referentiel": "Dev Web",
                   "candidate": self.candidate, "score": 100, "answers": {"0": 1}}
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: TestManagementService().submit_result(payload), range(20)))
        self.assertEqual(1, TestResult.objects.count())
        self.assertEqual(1, sum(created for _, created in results))

    def test_forged_score_metadata_and_manual_grades_are_ignored(self):
        self.test.questions = [Question(question="Q", type="qcm_simple", correctAnswer=1, score=5)]
        self.test.save()
        result, _ = TestManagementService().submit_result({
            "testId": str(self.test.id), "candidate": self.candidate,
            "score": 100, "passingScore": 0, "testTitle": "Forged", "referentiel": "Forged",
            "answers": {"0": 0}, "manualGrades": {"0": 100},
        })
        self.assertEqual(0, result.score)
        self.assertEqual("rejeté", result.status)
        self.assertEqual(self.test.title, result.testTitle)
        self.assertEqual(self.test.referentiel, result.referentiel)
        self.assertEqual({}, result.manualGrades)

    def test_explicit_admin_import_preserves_a_valid_imported_score(self):
        result, _ = TestManagementService().submit_result({
            "testId": str(self.test.id), "candidate": self.candidate, "score": 80,
        }, trusted_import=True)
        self.assertEqual(80, result.score)
        self.assertEqual("admis", result.status)

    def test_expiry_does_not_overwrite_a_submitted_session(self):
        self.sessions.mark_submitted(str(self.test.id), self.candidate["email"], self.candidate)
        self.test.scheduledDate = "2020-01-01"
        self.test.save()
        TestSession(testId="legacy-invalid-id", candidateEmail="legacy@example.org", candidatePhone="1").save()
        self.sessions.refresh_expired_sessions()
        self.assertEqual("submitted", TestSession.objects(candidateEmail=self.candidate["email"]).get().status)

    def test_queue_deduplicates_repeated_and_concurrent_enqueue(self):
        group = self.create_jobs()
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda _: self.queue.enqueue(group, self.test, "https://test.example.org"), range(8)))
        self.assertEqual(1, EmailJob.objects.count())

    def test_two_workers_claim_a_job_only_once_and_remove_payload_on_success(self):
        group = self.create_jobs()
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda _: self.queue.run_once(), range(8)))
        self.transport.send_html.assert_called_once()
        self.assertEqual("sent", EmailJob.objects.get().status)
        self.assertEqual({}, EmailJob.objects.get().payload)
        self.assertEqual("scheduled", group.reload().status)

    def test_transient_failure_retries_but_auth_failure_does_not(self):
        self.create_jobs()
        self.transport.send_html.return_value = {"sent": False, "retryable": True, "message": "Timeout"}
        self.queue.run_once()
        self.assertEqual("pending", EmailJob.objects.get().status)
        self.assertFalse(self.queue.run_once())
        self.now += timedelta(minutes=1)
        self.transport.send_html.return_value = {"sent": False, "retryable": False, "message": "Auth"}
        self.queue.run_once()
        self.assertEqual("failed", EmailJob.objects.get().status)
        self.assertEqual(2, EmailJob.objects.get().attempts)

    def test_stale_or_cancelled_groups_are_not_emailed(self):
        group = self.create_jobs()
        group.status = "cancelled"
        group.save()
        self.queue.run_once()
        self.assertEqual("cancelled", EmailJob.objects.get().status)
        self.transport.send_html.assert_not_called()

    def test_worker_crash_lease_is_reclaimed(self):
        self.create_jobs()
        EmailJob.objects.update(set__status="sending", set__attempts=1, set__locked_until=self.now - timedelta(seconds=1))
        self.queue.run_once()
        self.assertEqual("sent", EmailJob.objects.get().status)
        self.assertEqual(2, EmailJob.objects.get().attempts)
