import os
import unittest
from types import SimpleNamespace
from uuid import uuid4

from bson import ObjectId
from mongoengine import connect, disconnect

from app.models.candidature import Candidature
from app.models.interview import InterviewCampaign, InterviewEvaluation
from app.services.interviews.questionnaire_service import InterviewQuestionnaireService


def bank():
    rows = []
    for section, count in (("technique", 5), ("motivation", 3), ("social", 2)):
        for index in range(count):
            for profile in (("avec", "sans") if section == "technique" else ("tous",)):
                rows.append({
                    "section": section, "profile": profile, "topic": f"{section}-{index}", "prompt": f"{section} {profile} {index}",
                    "options": ["Un", "Deux", "Trois"] if section == "technique" else [], "correct": "A" if section == "technique" else "",
                    "points": 1,
                })
    return rows


@unittest.skipUnless(os.getenv("TEST_LOCAL_MONGO") == "1", "requires local MongoDB")
class DeclaredProfileTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db_name = "odc_declared_profile_test_" + uuid4().hex
        cls.addClassCleanup(disconnect)
        connection = connect(cls.db_name, host=os.getenv("TEST_INTERVIEW_MONGO_URI", "mongodb://127.0.0.1:27017"),
                             serverSelectionTimeoutMS=3000)
        connection.admin.command("ping")
        cls.addClassCleanup(connection.drop_database, cls.db_name)

    def test_questionnaire_uses_the_computer_profile_declared_at_application(self):
        workspace = InterviewCampaign(name="Web", formation="dev-web-mobile", referential_key="dev-web-mobile:x",
                                      candidature_campaign_id=str(ObjectId()), question_bank=bank()).save()
        admin = SimpleNamespace(id=ObjectId(), admin_type="super_admin", profile_data={})
        service = InterviewQuestionnaireService()
        for skills, expected in ((True, "avec"), (False, "sans")):
            candidate = ObjectId()
            Candidature._get_collection().insert_one({"_id": candidate, "computer_skills": skills, "email": f"{candidate}@example.com",
                                                      "cni_or_passport_number": str(candidate)})
            evaluation = InterviewEvaluation(campaign_id=str(workspace.id), candidature_id=str(candidate)).save()
            with self.subTest(skills=skills):
                self.assertEqual(expected, service.get(str(evaluation.id), admin)["declared_profile"])
                # Even if the screen sends another profile, the application form wins.
                form = service.generate(str(evaluation.id), {"profile": "sans" if skills else "avec"}, admin)
                self.assertEqual(expected, form["profile"])
                self.assertEqual({expected, "tous"}, {question["profile"] for question in form["questions"]})


if __name__ == "__main__":
    unittest.main()
