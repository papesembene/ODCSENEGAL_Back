import unittest

from app.services.interviews.exceptions import InterviewValidationError
from app.services.interviews.questionnaire import grade_answers, review_answers, validate_bank


def row(correct, options=("HTML", "CSS", "SQL", "JavaScript")):
    return {"section": "technique", "profile": "avec", "topic": "Web", "prompt": "Langages du navigateur ?",
            "options": list(options), "correct": correct, "points": 2}


class MultipleAnswersTest(unittest.TestCase):
    def test_import_accepts_several_letters_in_common_formats(self):
        for value in ("A,C", "c;a", "A et C", "AC", ["C", "A"], " a , c "):
            with self.subTest(value=value):
                questions, errors = validate_bank([row(value)])
                self.assertEqual(([], "AC"), (errors, questions[0]["correct"] if questions else None))
        self.assertEqual("B", validate_bank([row("b")])[0][0]["correct"])

    def test_invalid_correct_answers_are_reported_with_their_line(self):
        for value in ("A,A", "E", "", "A,B,C,D", "D"):
            with self.subTest(value=value):
                options = ("HTML", "CSS", "SQL") if value == "D" else ("HTML", "CSS", "SQL", "JavaScript")
                _, errors = validate_bank([row(value, options)])
                self.assertEqual(0, errors[0]["index"])

    def test_multiple_answer_questions_are_all_or_nothing(self):
        question = {**validate_bank([row("A,D")])[0][0], "id": "1"}
        single = {**validate_bank([row("B")])[0][0], "id": "2", "prompt": "Autre"}
        questions = [question, single]
        cases = (
            ({"1": ["D", "A"], "2": "B"}, ("correct", 2), ["A", "D"]),
            ({"1": ["A"], "2": "B"}, ("incorrect", 0), ["A"]),
            ({"1": ["A", "B", "D"], "2": "B"}, ("incorrect", 0), ["A", "B", "D"]),
            ({"1": "aucune", "2": "B"}, ("no_answer", 0), "aucune"),
        )
        for answers, (outcome, points), saved_answer in cases:
            with self.subTest(answers=answers):
                saved, _ = grade_answers(questions, answers, complete=False)
                self.assertEqual(saved_answer, saved["1"])
                mark = review_answers(questions, saved)["1"]
                self.assertEqual((outcome, points, "AD"), (mark["outcome"], mark["points"], mark["expected_option"]))
        for invalid in ("A", ["A", "A"], ["E"], []):
            with self.subTest(invalid=invalid), self.assertRaises(InterviewValidationError):
                grade_answers(questions, {"1": invalid}, complete=False)
        for invalid in (["B"], "BC", ""):
            with self.subTest(single=invalid), self.assertRaises(InterviewValidationError):
                grade_answers(questions, {"2": invalid}, complete=False)
        with self.assertRaises(InterviewValidationError):
            grade_answers(questions, {"1": ["AD"]}, complete=False)


if __name__ == "__main__":
    unittest.main()
