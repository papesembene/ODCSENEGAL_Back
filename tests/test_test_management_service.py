import unittest

from app.services.tests.test_management_service import (
    TestManagementService as OnlineTestManagementService,
    TestServiceError,
)


class TestManagementServiceUnitTest(unittest.TestCase):
    def setUp(self):
        self.service = OnlineTestManagementService()

    def test_question_mapping_preserves_qcm_contract(self):
        questions = self.service._build_questions([
            {
                "question": "2 + 2 ?",
                "type": "qcm_simple",
                "options": ["3", "4"],
                "correctAnswer": 1,
                "score": 5,
            },
        ])

        self.assertEqual(1, len(questions))
        self.assertEqual(1, questions[0].correctAnswer)

    def test_required_field_error_is_stable(self):
        with self.assertRaisesRegex(
            TestServiceError,
            "Le champ title est requis",
        ):
            self.service._require_fields({}, ("title",))


if __name__ == "__main__":
    unittest.main()
