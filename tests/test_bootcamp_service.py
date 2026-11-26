import os
import unittest
from datetime import date, datetime, timedelta
from unittest.mock import Mock, patch
from uuid import uuid4

from bson import ObjectId
from mongoengine import connect, disconnect

from app.models.bootcamp import Bootcamp, BootcampParticipant
from app.models.candidature import Candidature
from app.models.candidature_campaign import CandidatureCampaign
from app.models.email_job import EmailJob
from app.models.interview import InterviewCampaign, InterviewEvaluation
from app.models.user import User
from app.services.bootcamps.results_service import FinalResultOutbox, FinalResultsService
from app.services.bootcamps.service import BootcampInvitationOutbox, BootcampService
from app.services.interviews.exceptions import (
    InterviewConflictError, InterviewForbiddenError, InterviewValidationError,
)


@unittest.skipUnless(os.getenv("TEST_LOCAL_MONGO") == "1", "requires local MongoDB")
class BootcampServiceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db_name = "odc_bootcamp_test_" + uuid4().hex
        cls.addClassCleanup(disconnect)
        connection = connect(cls.db_name, host=os.getenv("TEST_INTERVIEW_MONGO_URI", "mongodb://127.0.0.1:27017"),
                             serverSelectionTimeoutMS=3000)
        connection.admin.command("ping")
        cls.addClassCleanup(connection.drop_database, cls.db_name)

    def _user(self, email, role, formations):
        return User(email=email, password_hash="x", first_name="Coach", last_name=email.split("@")[0], is_admin=True,
                    admin_type="competences", profile_type="student", is_active=True,
                    profile_data={"admin_scope": "interview_member", "interview_role": role, "interview_formations": formations}).save()

    def setUp(self):
        for model in (Bootcamp, BootcampParticipant, Candidature, CandidatureCampaign, EmailJob, InterviewCampaign, InterviewEvaluation, User):
            model.drop_collection()
        now = datetime.utcnow()
        self.source = CandidatureCampaign(title="Promo", formation="all", status="published",
                                          start_at=now - timedelta(days=10), end_at=now - timedelta(days=1)).save()
        self.ids = [str(ObjectId()) for _ in range(4)]
        Candidature._get_collection().insert_many([
            {"_id": ObjectId(candidate), "first_name": "Awa", "last_name": f"Candidat{index}", "email": f"c{index}@example.com",
             "phone": "770000000", "cni_or_passport_number": f"CNI{index}", "status": "pending", "desired_training": "dev-data", "candidature_campaign_id": str(self.source.id)}
            for index, candidate in enumerate(self.ids)
        ])
        self.workspace = InterviewCampaign(
            name="Data", formation="dev-data", referential_key=f"dev-data:{self.source.id}",
            candidature_campaign_id=str(self.source.id), status="active", distribution={"revision": 0, "validators": {}},
            preselection={"status": "draft", "selected": self.ids[:3], "revision": 1},
        ).save()
        InterviewEvaluation(campaign_id=str(self.workspace.id), candidature_id=self.ids[0],
                            questionnaire={"status": "validated", "comment": "Très motivée", "scores": {"global": 81.5}}).save()
        self.coach = self._user("coach@example.com", "coach", ["dev-data"])
        self.other_coach = self._user("autre@example.com", "coach", ["dev-data"])
        self.foreign_coach = self._user("web@example.com", "coach", ["dev-web-mobile"])
        self.admin = User(email="admin@example.com", password_hash="x", first_name="Ada", last_name="Admin", is_admin=True,
                          admin_type="super_admin", profile_type="student", profile_data={}).save()
        self.service = BootcampService()
        self.start = (date.today() + timedelta(days=7)).isoformat()
        self.end = (date.today() + timedelta(days=21)).isoformat()

    def _create(self, title="Bootcamp 1", **changes):
        return self.service.create("dev-data", {"title": title, "start_date": self.start, "end_date": self.end,
                                                "coach_ids": [str(self.coach.id)], **changes})["id"]

    def _validate_preselection(self):
        InterviewCampaign.objects(id=self.workspace.id).update_one(set__preselection__status="validated")

    def test_bootcamps_need_a_validated_preselection_and_valid_fields(self):
        with self.assertRaisesRegex(InterviewValidationError, "présélection"):
            self._create()
        self._validate_preselection()
        for changes in ({"end_date": "2000-01-01"}, {"coach_ids": [str(self.foreign_coach.id)]}, {"title": " "}, {"capacity": 0}):
            with self.subTest(changes=changes), self.assertRaises(InterviewValidationError):
                self._create(**changes)
        first, second = self._create(), self._create("Bootcamp 2", coach_ids=[str(self.other_coach.id)])
        detail = self.service.detail("dev-data")
        self.assertEqual(["Bootcamp 1", "Bootcamp 2"], [bootcamp["title"] for bootcamp in detail["bootcamps"]])
        self.assertEqual(self.ids[:3], [row["candidate_id"] for row in detail["candidates"]])
        self.assertEqual((81.5, "Très motivée"), (detail["candidates"][0]["interview_score"], detail["candidates"][0]["validator_comment"]))
        self.assertEqual({str(self.coach.id), str(self.other_coach.id)}, {coach["id"] for coach in detail["available_coaches"]})
        overview = next(row for row in self.service.overview() if row["formation"] == "dev-data")
        self.assertEqual((3, 2, 2), (overview["preselected"], overview["bootcamps"], overview["coaches"]))
        self.assertNotEqual(first, second)

    def test_candidates_are_placed_once_and_only_from_the_preselection(self):
        self._validate_preselection()
        first, second = self._create(capacity=2), self._create("Bootcamp 2")
        with self.assertRaisesRegex(InterviewValidationError, "présélectionnés"):
            self.service.set_participants(first, {"candidate_ids": [self.ids[3]], "revision": 0})
        with self.assertRaisesRegex(InterviewValidationError, "au maximum 2"):
            self.service.set_participants(first, {"candidate_ids": self.ids[:3], "revision": 0})
        self.service.set_participants(first, {"candidate_ids": self.ids[:2], "revision": 0})
        with self.assertRaisesRegex(InterviewConflictError, "autre Bootcamp"):
            self.service.set_participants(second, {"candidate_ids": [self.ids[1], self.ids[2]], "revision": 0})
        with self.assertRaises(InterviewConflictError):
            self.service.set_participants(first, {"candidate_ids": [self.ids[0]], "revision": 0})
        self.service.set_participants(first, {"candidate_ids": [self.ids[0]], "revision": 1})
        self.service.set_participants(second, {"candidate_ids": [self.ids[1], self.ids[2]], "revision": 0})
        placed = {row["candidate_id"]: row["bootcamp_id"] for row in self.service.detail("dev-data")["candidates"]}
        self.assertEqual({self.ids[0]: first, self.ids[1]: second, self.ids[2]: second}, placed)

    def test_launch_queues_invitations_and_coach_decides_manually(self):
        self._validate_preselection()
        bootcamp = self._create(location="ODC Dakar")
        empty = self._create("Sans coach", coach_ids=[])
        self.service.set_participants(bootcamp, {"candidate_ids": self.ids[:2], "revision": 0})
        with self.assertRaisesRegex(InterviewValidationError, "coach"):
            self.service.launch(empty, {"confirmed": True, "revision": 0}, self.admin)
        with self.assertRaisesRegex(InterviewForbiddenError, "pas encore lancé"):
            self.service.coach_bootcamp(bootcamp, self.coach)
        with patch("app.services.email_outbox.EmailTransport", return_value=Mock(is_configured=True)):
            summary = self.service.launch(bootcamp, {"confirmed": True, "revision": 1}, self.admin)
        self.assertEqual(2, summary["pending"])
        job = EmailJob.objects(kind="bootcamp_invitation", candidate_id=self.ids[0]).get()
        recipients, subject, html = BootcampInvitationOutbox.prepare(job, datetime.utcnow())
        self.assertEqual((["c0@example.com"], True), (recipients, "Bootcamp 1" in subject))
        self.assertIn("ODC Dakar", html)
        self.assertIn(date.fromisoformat(self.start).strftime("%d/%m/%Y"), html)
        with self.assertRaises(InterviewConflictError):
            self.service.set_participants(bootcamp, {"candidate_ids": self.ids[:1], "revision": 2})

        with self.assertRaises(InterviewForbiddenError):
            self.service.coach_bootcamp(bootcamp, self.other_coach)
        with self.assertRaises(InterviewForbiddenError):
            self.service.coach_dashboard(self.admin)
        dashboard = self.service.coach_dashboard(self.coach)
        self.assertEqual((["Bootcamp 1"], 2, 2), ([item["title"] for item in dashboard["bootcamps"]],
                                                  dashboard["totals"]["participants"], dashboard["totals"]["to_evaluate"]))
        self.assertEqual([], self.service.coach_dashboard(self.other_coach)["bootcamps"])
        rows = self.service.coach_bootcamp(bootcamp, self.coach)["participants"]
        self.assertEqual({"pending"}, {row["decision"] for row in rows})
        self.assertEqual("Très motivée", next(row for row in rows if row["candidate_id"] == self.ids[0])["validator_comment"])

        self.service.coach_decide(bootcamp, self.ids[0], {"decision": "retained", "comment": "Excellent"}, self.coach)
        with self.assertRaisesRegex(InterviewValidationError, "1 candidat"):
            self.service.coach_submit(bootcamp, {"confirmed": True}, self.coach)
        self.service.coach_decide(bootcamp, self.ids[1], {"decision": "waiting_list"}, self.coach)
        self.service.coach_decide(bootcamp, self.ids[1], {"decision": "rejected", "comment": "À revoir"}, self.coach)
        self.service.coach_submit(bootcamp, {"confirmed": True}, self.coach)
        with self.assertRaises(InterviewConflictError):
            self.service.coach_decide(bootcamp, self.ids[1], {"decision": "retained"}, self.coach)
        overview = next(row for row in self.service.overview() if row["formation"] == "dev-data")
        self.assertEqual((1, 0, 1, 0), (overview["retained"], overview["waiting_list"], overview["rejected"], overview["to_evaluate"]))
        revision = Bootcamp.objects(id=bootcamp).get().revision
        self.service.reopen_results(bootcamp, {"revision": revision})
        self.service.coach_decide(bootcamp, self.ids[1], {"decision": "waiting_list"}, self.coach)
        self.assertEqual("waiting_list", BootcampParticipant.objects(candidate_id=self.ids[1]).get().decision)


    def test_final_results_are_validated_previewed_and_sent_once_per_decision(self):
        self._validate_preselection()
        results = FinalResultsService()
        bootcamp = self._create()
        self.service.set_participants(bootcamp, {"candidate_ids": self.ids[:2], "revision": 0})
        transport = patch("app.services.email_outbox.EmailTransport", return_value=Mock(is_configured=True))
        transport.start()
        self.addCleanup(transport.stop)
        self.service.launch(bootcamp, {"confirmed": True, "revision": 1}, self.admin)
        self.service.coach_decide(bootcamp, self.ids[0], {"decision": "retained"}, self.coach)
        self.service.coach_decide(bootcamp, self.ids[1], {"decision": "rejected"}, self.coach)
        with self.assertRaisesRegex(InterviewValidationError, "Bootcamp 1"):
            results.validate("dev-data", {"confirmed": True, "revision": 0}, self.admin)
        self.service.coach_submit(bootcamp, {"confirmed": True}, self.coach)

        state = results.get("dev-data")
        self.assertEqual(([True, True], "draft"), ([row["final"] for row in state["rows"]], state["status"]))
        with self.assertRaisesRegex(InterviewValidationError, "Validez"):
            results.send("dev-data", {"confirmed": True, "candidate_ids": self.ids[:2], "revision": 0}, self.admin)
        results.validate("dev-data", {"confirmed": True, "revision": 0, "campaign_id": ""}, self.admin)

        results.save_templates("dev-data", {"revision": 1, "templates": {
            **{key: {"subject": "Résultat {referentiel}", "body": "Bonjour {prenom}"} for key in ("waiting_list", "rejected")},
            "retained": {"subject": "Bravo {prenom}", "body": "Bonjour {prenom} {nom},\n\nVous êtes retenu(e) au {bootcamp}. <script>x</script>"},
        }}, self.admin)
        preview = results.preview("dev-data", {"decision": "retained"})
        self.assertEqual(("Bravo Awa", "c0@example.com", False), (preview["subject"], preview["to"], preview["sample"]))
        self.assertIn("Bonjour Awa Candidat0", preview["html"])
        self.assertIn("&lt;script&gt;", preview["html"])
        self.assertNotIn("<script>", preview["html"])

        sent = results.send("dev-data", {"confirmed": True, "candidate_ids": self.ids[:2], "revision": 2}, self.admin)
        self.assertEqual((2, 0, {"retained": 1, "waiting_list": 0, "rejected": 1}), (sent["queued"], sent["skipped"], sent["counts"]))
        again = results.send("dev-data", {"confirmed": True, "candidate_ids": self.ids[:2], "revision": 3}, self.admin)
        self.assertEqual((0, 2), (again["queued"], again["skipped"]))
        job = EmailJob.objects(kind="final_result", candidate_id=self.ids[0]).get()
        recipients, subject, html = FinalResultOutbox.prepare(job, datetime.utcnow())
        self.assertEqual((["c0@example.com"], "Bravo Awa"), (recipients, subject))
        self.assertIn("Bootcamp 1", html)
        history = results.get("dev-data")["history"]
        self.assertEqual(["validate", "send"], [event["action"] for event in history])
        self.assertEqual("Bravo {prenom}", history[-1]["templates"]["retained"]["subject"])

        revision = Bootcamp.objects(id=bootcamp).get().revision
        self.service.reopen_results(bootcamp, {"revision": revision})
        self.service.coach_decide(bootcamp, self.ids[1], {"decision": "waiting_list"}, self.coach)
        self.service.coach_submit(bootcamp, {"confirmed": True}, self.coach)
        self.assertTrue(results.get("dev-data")["changed_since_validation"])
        self.assertIsNone(FinalResultOutbox.prepare(EmailJob.objects(kind="final_result", candidate_id=self.ids[1]).get(), datetime.utcnow()))
        with self.assertRaisesRegex(InterviewConflictError, "validez de nouveau"):
            results.send("dev-data", {"confirmed": True, "candidate_ids": self.ids[:2], "revision": 3}, self.admin)
        results.validate("dev-data", {"confirmed": True, "revision": 3}, self.admin)
        resent = results.send("dev-data", {"confirmed": True, "candidate_ids": self.ids[:2], "revision": 4}, self.admin)
        self.assertEqual((1, 1, 1), (resent["queued"], resent["skipped"], resent["counts"]["waiting_list"]))
        listing = {row["candidate_id"]: row for row in results.all_results()["rows"]}
        self.assertEqual(("retained", "waiting_list"), (listing[self.ids[0]]["decision"], listing[self.ids[1]]["decision"]))
        self.assertEqual(("Développement Data & IA", "Bootcamp 1", 81.5, True),
                         (listing[self.ids[0]]["formation_title"], listing[self.ids[0]]["bootcamp"],
                          listing[self.ids[0]]["interview_score"], listing[self.ids[0]]["final"]))
        self.assertEqual("pending", listing[self.ids[0]]["notification_status"])
        self.assertFalse(listing[self.ids[0]]["notified"])

    def test_a_validator_can_also_be_coach(self):
        dual = self._user("double@example.com", "validator", ["dev-data"])
        User.objects(id=dual.id).update_one(set__profile_data__interview_roles=["validator", "coach"])
        dual.reload()
        self._validate_preselection()
        self.assertIn(str(dual.id), {coach["id"] for coach in self.service.detail("dev-data")["available_coaches"]})
        bootcamp = self._create(coach_ids=[str(dual.id)])
        self.assertEqual([], self.service.coach_dashboard(dual)["bootcamps"])
        with self.assertRaises(InterviewForbiddenError):
            self.service.coach_dashboard(self._user("solo@example.com", "validator", ["dev-data"]))
        self.assertTrue(bootcamp)

if __name__ == "__main__":
    unittest.main()
