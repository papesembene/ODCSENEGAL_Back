import unittest

from app.models.test import Question
from app.services.tests.test_scoring import calculate_test_score


class TestScoringTest(unittest.TestCase):
    def test_simple_choice_uses_stored_correct_answer(self):
        questions = [Question(question="Q", type="qcm_simple", correctAnswer=1, score=5)]
        self.assertEqual(100, calculate_test_score(questions, {"0": 1}))
        self.assertEqual(0, calculate_test_score(questions, {"0": 0}))
        self.assertEqual(0, calculate_test_score(questions, {"0": True}))

    def test_multiple_choice_requires_all_and_only_correct_choices(self):
        questions = [Question(question="Q", type="qcm_multiple", correctAnswers=[0, 2], score=5)]
        self.assertEqual(100, calculate_test_score(questions, {"0": [2, 0]}))
        for answer in ([0], [0, 2, 1], [0, 0], [True, 2], "0,2"):
            self.assertEqual(0, calculate_test_score(questions, {"0": answer}))

    def test_text_preserves_existing_provisional_credit_rule(self):
        questions = [Question(question="Q", type="texte_libre", score=5)]
        self.assertEqual(100, calculate_test_score(questions, {"0": "Response"}))
        self.assertEqual(0, calculate_test_score(questions, {"0": " "}))
        self.assertEqual(0, calculate_test_score(questions, {"0": {"text": "invalid"}}))
