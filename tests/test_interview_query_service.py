import unittest
from types import SimpleNamespace

from app.services.interviews.query_service import InterviewQueryService


class InterviewQueryServiceTest(unittest.TestCase):
    def setUp(self):
        self.service = InterviewQueryService()

    def test_positive_int_applies_default_minimum_and_maximum(self):
        self.assertEqual(25, self.service.get_positive_int("bad", 25))
        self.assertEqual(1, self.service.get_positive_int("-4", 25))
        self.assertEqual(
            100,
            self.service.get_positive_int("500", 25, maximum=100),
        )

    def test_candidate_snapshot_keeps_public_contract(self):
        candidate = SimpleNamespace(
            id="candidate-id",
            first_name="Moussa",
            last_name="Ba",
            email="moussa@example.com",
            phone="771234567",
            gender="M",
            desired_training="dev-web-mobile",
            status="accepted",
        )

        snapshot = self.service.build_candidate_snapshot(candidate)

        self.assertEqual("candidate-id", snapshot["id"])
        self.assertEqual("dev-web-mobile", snapshot["desired_training"])
        self.assertEqual("accepted", snapshot["status"])

    def test_email_normalization_is_stable(self):
        self.assertEqual(
            "moussa@example.com",
            self.service.normalize_email(" Moussa@Example.COM "),
        )

    def test_export_evaluations_csv_contains_decision_summary(self):
        self.service.build_evaluation_query = lambda args, current_admin=None: []
        self.service.serialize_evaluations = lambda rows: [
            {
                "candidate_snapshot": {
                    "first_name": "Moussa",
                    "last_name": "Ba",
                    "email": "moussa@example.com",
                    "phone": "771234567",
                    "desired_training": "dev-web-mobile",
                },
                "campaign_name": "Entretiens Dev Web",
                "slot_label": "Matin",
                "slot_start_at": "2026-08-17T09:00:00",
                "test_score": 82,
                "test_details": {
                    "violations": {"totalViolations": 1},
                },
                "section_reviews": {
                    "filter": {"decision": "OK", "comment": "Bon profil"},
                    "validator": {
                        "decision": "Favorable",
                        "coach_pick": True,
                    },
                    "motivation": {"comment": "Motivé"},
                },
                "interview_progress_status": "passe",
                "final_status": "retenu",
                "is_complete": True,
            }
        ]

        csv_content, filename = self.service.export_evaluations_csv(
            {"formation": "dev-web-mobile"},
        )

        self.assertTrue(csv_content.startswith("\ufeffNom;Email"))
        self.assertIn("Moussa Ba", csv_content)
        self.assertIn("Coup de coeur", csv_content)
        self.assertIn("Retenu", csv_content)
        self.assertTrue(filename.startswith("entretiens-dev-web-mobile-"))


if __name__ == "__main__":
    unittest.main()
