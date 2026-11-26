import os
import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

from bson import ObjectId
from mongoengine import connect, disconnect

from app.models.candidature_campaign import CandidatureCampaign
from app.models.interview import InterviewCampaign, InterviewEvaluation
from app.services.interviews.exceptions import InterviewConflictError, InterviewValidationError
from app.services.interviews.questionnaire_service import InterviewQuestionnaireService
from app.services.interviews.ranking_service import InterviewRankingService, select_best


class SelectBestTest(unittest.TestCase):
    ranked = [("a", 90.0), ("b", 80.0), ("c", 70.0), ("d", 70.0), ("e", 70.0), ("f", 60.0)]

    def test_no_draw_when_the_threshold_is_not_shared(self):
        self.assertEqual((["a", "b"], None), select_best(self.ranked, 2, "0" * 16))
        self.assertEqual((["a", "b", "c", "d", "e"], None), select_best(self.ranked, 5, "0" * 16))
        self.assertEqual(([row[0] for row in self.ranked], None), select_best(self.ranked, 50, "0" * 16))

    def test_draw_fills_the_remaining_places_among_tied_candidates_only(self):
        selected, tie = select_best(self.ranked, 3, "1234567890abcdef")
        self.assertEqual(["a", "b"], selected[:2])
        self.assertEqual((70.0, ["c", "d", "e"], 1), (tie["score"], tie["candidates"], tie["places"]))
        self.assertEqual(1, len(tie["selected"]))
        self.assertIn(tie["selected"][0], {"c", "d", "e"})
        self.assertEqual(selected[2:], tie["selected"])

    def test_same_seed_gives_the_same_draw(self):
        self.assertEqual(select_best(self.ranked, 4, "abcdefabcdef0123"), select_best(self.ranked, 4, "abcdefabcdef0123"))
        draws = {tuple(select_best(self.ranked, 3, f"{index:016x}")[1]["selected"]) for index in range(40)}
        self.assertEqual({("c",), ("d",), ("e",)}, draws)


@unittest.skipUnless(os.getenv("TEST_LOCAL_MONGO") == "1", "requires local MongoDB")
class InterviewRankingIntegrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db_name = "odc_interview_ranking_test_" + uuid4().hex
        cls.addClassCleanup(disconnect)
        connection = connect(cls.db_name, host=os.getenv("TEST_INTERVIEW_MONGO_URI", "mongodb://127.0.0.1:27017"),
                             serverSelectionTimeoutMS=3000)
        connection.admin.command("ping")
        cls.addClassCleanup(connection.drop_database, cls.db_name)

    def setUp(self):
        for model in (CandidatureCampaign, InterviewCampaign, InterviewEvaluation):
            model.drop_collection()
        now = datetime.utcnow()
        self.source = CandidatureCampaign(title="Promo", formation="all", status="published",
                                          start_at=now - timedelta(days=10), end_at=now - timedelta(days=1)).save()
        self.workspace = InterviewCampaign(
            name="Data", formation="dev-data", referential_key=f"dev-data:{self.source.id}",
            candidature_campaign_id=str(self.source.id), status="active", distribution={"revision": 0, "validators": {}},
        ).save()
        self.admin = SimpleNamespace(id=ObjectId(), first_name="Awa", last_name="Admin", email="admin@example.com",
                                     admin_type="super_admin", profile_data={})
        self.service = InterviewRankingService()
        self.ids = {}
        for name, score, status in (("Ba", 82.5, "validated"), ("Cisse", 70, "validated"), ("Diop", 70, "validated"),
                                    ("Fall", 70, "validated"), ("Gaye", 55.25, "validated"), ("Ka", None, "draft"),
                                    ("Ly", None, "absent")):
            candidate = str(ObjectId())
            self.ids[name] = candidate
            InterviewEvaluation(
                campaign_id=str(self.workspace.id), candidature_id=candidate,
                candidate_snapshot={"first_name": "Awa", "last_name": name, "email": f"{name}@example.com"},
                questionnaire={"status": status, "comment": f"Avis {name}", "revision": 3,
                               **({"scores": {"technique": 40, "motivation": 20, "social": 10, "global": score}} if score else {})},
                interview_progress_status="passe" if status == "validated" else "planifie",
            ).save()

    def test_ranking_lists_only_validated_interviews_with_shared_ranks(self):
        ranking = self.service.get("dev-data")
        self.assertEqual((5, 1, 1), (ranking["evaluated"], ranking["pending"], ranking["absent"]))
        self.assertEqual([("Ba", 1), ("Cisse", 2), ("Diop", 2), ("Fall", 2), ("Gaye", 5)],
                         [(row["last_name"], row["rank"]) for row in ranking["rows"]])
        self.assertEqual("Avis Ba", ranking["rows"][0]["comment"])
        self.assertIsNone(ranking["rows"][0]["preselection"])

    def test_tie_draw_is_persisted_replaceable_and_validated(self):
        ranking = self.service.preselect("dev-data", {"count": 2, "revision": 0}, self.admin)
        selection = ranking["preselection"]
        tied = [self.ids[name] for name in ("Cisse", "Diop", "Fall")]
        self.assertEqual((sorted(tied), 1, 70.0), (selection["tie"]["candidates"], selection["tie"]["places"], selection["tie"]["score"]))
        drawn = selection["tie"]["selected"][0]
        self.assertEqual([self.ids["Ba"], drawn], selection["selected"])
        self.assertEqual(selection, self.service.get("dev-data")["preselection"])
        statuses = {row["candidate_id"]: row["preselection"] for row in ranking["rows"]}
        self.assertEqual(("selected", "tie_selected", "not_selected"), (statuses[self.ids["Ba"]], statuses[drawn], statuses[self.ids["Gaye"]]))
        self.assertEqual(2, sum(statuses[candidate] == "tie_not_selected" for candidate in tied))

        other = next(candidate for candidate in tied if candidate != drawn)
        with self.assertRaises(InterviewValidationError):
            self.service.replace("dev-data", {"remove": self.ids["Ba"], "add": other, "revision": 1}, self.admin)
        with self.assertRaises(InterviewConflictError):
            self.service.replace("dev-data", {"remove": drawn, "add": other, "revision": 0}, self.admin)
        replaced = self.service.replace("dev-data", {"remove": drawn, "add": other, "revision": 1}, self.admin)["preselection"]
        self.assertEqual([self.ids["Ba"], other], replaced["selected"])
        self.assertEqual(["draw", "replace"], [event["action"] for event in replaced["history"]])
        self.assertEqual("Awa Admin", replaced["history"][-1]["by"]["name"])

        validated = self.service.validate("dev-data", {"confirmed": True, "revision": 2}, self.admin)["preselection"]
        self.assertEqual("validated", validated["status"])
        with self.assertRaises(InterviewConflictError):
            self.service.preselect("dev-data", {"count": 3, "revision": 3}, self.admin)
        with self.assertRaisesRegex(InterviewConflictError, "présélection"):
            InterviewQuestionnaireService().save(
                str(InterviewEvaluation.objects(candidature_id=self.ids["Ba"]).get().id),
                {"action": "reopen", "revision": 3}, self.admin,
            )

    def test_validation_is_refused_when_interviews_changed_since_the_draw(self):
        self.service.preselect("dev-data", {"count": 1, "revision": 0}, self.admin)
        InterviewEvaluation.objects(candidature_id=self.ids["Ka"]).update_one(
            set__questionnaire={"status": "validated", "revision": 4, "scores": {"global": 99}},
        )
        self.assertTrue(self.service.get("dev-data")["stale"])
        with self.assertRaises(InterviewConflictError):
            self.service.validate("dev-data", {"confirmed": True, "revision": 1}, self.admin)
        refreshed = self.service.preselect("dev-data", {"count": 1, "revision": 1}, self.admin)
        self.assertEqual([self.ids["Ka"]], refreshed["preselection"]["selected"])
        self.assertFalse(refreshed["stale"])


if __name__ == "__main__":
    unittest.main()
