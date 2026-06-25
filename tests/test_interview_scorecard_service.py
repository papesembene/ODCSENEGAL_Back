import unittest

from app.services.interviews.scorecard_service import (
    get_default_scorecard_config,
    is_evaluation_complete,
    is_scorecard_ready,
    sanitize_review,
    sanitize_scorecard_config,
)


class InterviewScorecardServiceTest(unittest.TestCase):
    def test_default_dwm_scorecard_is_ready_and_independent(self):
        first = get_default_scorecard_config("dev-web-mobile")
        second = get_default_scorecard_config("dev-web-mobile")

        self.assertTrue(is_scorecard_ready(first))
        first["sections"]["filter"]["criteria"][0]["label"] = "Modifié"
        self.assertNotEqual(
            first["sections"]["filter"]["criteria"][0]["label"],
            second["sections"]["filter"]["criteria"][0]["label"],
        )

    def test_custom_scorecard_accepts_only_checkbox_and_number(self):
        valid_scorecard = self._scorecard([
            {
                "key": "presence",
                "label": "Présence",
                "type": "checkbox",
                "required": True,
            },
            {
                "key": "note",
                "label": "Note",
                "type": "number",
                "min": 0,
                "max": 20,
            },
        ])

        sanitized = sanitize_scorecard_config(valid_scorecard)

        self.assertEqual(
            ["checkbox", "number"],
            [
                criterion["type"]
                for criterion in sanitized["sections"]["filter"]["criteria"]
            ],
        )

        with self.assertRaisesRegex(
            ValueError,
            "case à cocher ou une note",
        ):
            sanitize_scorecard_config(
                self._scorecard([
                    {
                        "key": "texte",
                        "label": "Texte",
                        "type": "text",
                    },
                ]),
            )

    def test_review_sanitizes_numbers_and_computed_values(self):
        section = {
            "criteria": [
                {
                    "key": "presence",
                    "label": "Présence",
                    "type": "checkbox",
                },
                {
                    "key": "note",
                    "label": "Note",
                    "type": "number",
                    "min": 0,
                    "max": 20,
                },
                {
                    "key": "total",
                    "label": "Total",
                    "type": "computed",
                    "depends_on": ["presence"],
                },
            ],
        }

        review = sanitize_review(
            {"presence": True, "note": "17"},
            section,
        )

        self.assertEqual(
            {"presence": True, "note": 17.0, "total": 1},
            review,
        )

    def test_completion_supports_documents_and_migration_dicts(self):
        scorecard = {
            "sections": {
                "filter": {
                    "criteria": [
                        {
                            "key": "presence",
                            "type": "checkbox",
                            "required": True,
                        },
                    ],
                },
                "validator": {
                    "criteria": [
                        {
                            "key": "note",
                            "type": "number",
                            "required": True,
                        },
                    ],
                },
                "motivation": {
                    "criteria": [
                        {
                            "key": "comment",
                            "type": "textarea",
                            "required": True,
                        },
                    ],
                },
            },
        }
        evaluation = {
            "filter_review": {"presence": False},
            "validator_review": {"note": 12},
            "motivation_review": {"comment": "Motivé"},
        }

        self.assertTrue(is_evaluation_complete(evaluation, scorecard))

    @staticmethod
    def _scorecard(filter_criteria):
        return {
            "source": "custom",
            "sections": {
                "filter": {
                    "title": "Filtreur",
                    "criteria": filter_criteria,
                },
                "validator": {
                    "title": "Validateur",
                    "criteria": [],
                },
                "motivation": {
                    "title": "Motivation",
                    "criteria": [],
                },
            },
        }


if __name__ == "__main__":
    unittest.main()
