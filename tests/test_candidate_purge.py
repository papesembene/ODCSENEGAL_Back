import os
import unittest
from uuid import uuid4

from bson import ObjectId
from mongoengine import connect, disconnect

from app.models.bootcamp import BootcampParticipant
from app.models.email_job import EmailJob
from app.models.interview import InterviewCampaign, InterviewEvaluation
from app.services.candidatures.purge import purge_candidate_traces


@unittest.skipUnless(os.getenv("TEST_LOCAL_MONGO") == "1", "requires local MongoDB")
class CandidatePurgeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db_name = "odc_candidate_purge_test_" + uuid4().hex
        cls.addClassCleanup(disconnect)
        connection = connect(cls.db_name, host=os.getenv("TEST_INTERVIEW_MONGO_URI", "mongodb://127.0.0.1:27017"),
                             serverSelectionTimeoutMS=3000)
        connection.admin.command("ping")
        cls.addClassCleanup(connection.drop_database, cls.db_name)

    def test_deleted_candidate_leaves_no_interview_or_bootcamp_trace(self):
        gone, kept = str(ObjectId()), str(ObjectId())
        workspace = InterviewCampaign(
            name="Data", formation="dev-data", referential_key="dev-data:x", candidature_campaign_id=str(ObjectId()),
            distribution={"revision": 4, "starts_at": "2035-12-03T09:00", "validators": {"v1": {
                "slot_id": str(ObjectId()), "teams_url": "https://teams.microsoft.com/l/x", "candidates": [gone, kept],
                "slots": {gone: {"at": "2035-12-03T09:00", "minutes": 15}, kept: {"at": "2035-12-03T09:15", "minutes": 15}},
            }}},
            preselection={"status": "draft", "revision": 2, "selected": [gone, kept], "fingerprint": [[gone, 70], [kept, 70]],
                          "tie": {"score": 70, "candidates": [gone, kept], "selected": [gone], "places": 1}},
        ).save()
        for candidate in (gone, kept):
            InterviewEvaluation(campaign_id=str(workspace.id), candidature_id=candidate).save()
            BootcampParticipant(bootcamp_id="b1", candidature_campaign_id="c1", formation="dev-data", candidate_id=candidate).save()
        EmailJob(dedup_key="pending", batch_key="b", kind="interview_invitation", candidate_id=gone, status="pending", payload={"email": "x@example.com"}).save()
        EmailJob(dedup_key="sent", batch_key="b", kind="interview_invitation", candidate_id=gone, status="sent").save()

        purge_candidate_traces(gone)

        workspace.reload()
        item = workspace.distribution["validators"]["v1"]
        self.assertEqual(([kept], [kept], 5), (item["candidates"], list(item["slots"]), workspace.distribution["revision"]))
        self.assertEqual(([kept], [kept], [], 3), (workspace.preselection["selected"], workspace.preselection["tie"]["candidates"],
                                                   workspace.preselection["tie"]["selected"], workspace.preselection["revision"]))
        self.assertNotIn("fingerprint", workspace.preselection)
        self.assertEqual([kept], [row.candidature_id for row in InterviewEvaluation.objects])
        self.assertEqual([kept], [row.candidate_id for row in BootcampParticipant.objects])
        self.assertEqual("cancelled", EmailJob.objects(dedup_key="pending").get().status)
        self.assertEqual("sent", EmailJob.objects(dedup_key="sent").get().status)


if __name__ == "__main__":
    unittest.main()
