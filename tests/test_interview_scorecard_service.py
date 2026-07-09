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
        self.assertIsNotNone(sanitize_scorecard_config(first))
        first["sections"]["filter"]["criteria"][0]["label"] = "Modifié"
        self.assertNotEqual(
            first["sections"]["filter"]["criteria"][0]["label"],
            second["sections"]["filter"]["criteria"][0]["label"],
        )

    def test_dwm_scorecard_accepts_custom_business_criteria(self):
        scorecard = get_default_scorecard_config("dev-web-mobile")
        scorecard["sections"]["filter"]["criteria"].append({
            "key": "niveau_general",
            "label": "Niveau général filtre",
            "type": "number",
            "required": True,
            "min": 0,
            "max": 5,
        })

        sanitized = sanitize_scorecard_config(scorecard)

        self.assertEqual(
            "niveau_general",
            sanitized["sections"]["filter"]["criteria"][-1]["key"],
        )

    def test_custom_scorecard_accepts_dynamic_business_criteria(self):
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
            {
                "key": "question_reponse",
                "label": "Question posée au candidat",
                "type": "textarea",
            },
            {
                "key": "avis",
                "label": "Avis jury",
                "type": "select",
                "options": [
                    {"value": "favorable", "label": "Favorable"},
                    {"value": "reserve", "label": "Réserve"},
                ],
            },
        ])

        sanitized = sanitize_scorecard_config(valid_scorecard)

        self.assertEqual(
            ["checkbox", "number", "textarea", "select"],
            [
                criterion["type"]
                for criterion in sanitized["sections"]["filter"]["criteria"]
            ],
        )

    def test_custom_scorecard_accepts_referentiel_specific_sections(self):
        scorecard = {
            "source": "custom",
            "sections": {
                "preselection": {
                    "title": "Préselection métier",
                    "roles": ["filter", "validator"],
                    "criteria": [
                        {
                            "key": "portfolio",
                            "label": "Portfolio présenté",
                            "type": "checkbox",
                        },
                    ],
                },
                "coach_review": {
                    "title": "Avis coach",
                    "roles": ["validator"],
                    "criteria": [
                        {
                            "key": "comment",
                            "label": "Commentaire coach",
                            "type": "textarea",
                            "required": True,
                        },
                    ],
                },
            },
        }

        sanitized = sanitize_scorecard_config(scorecard)

        self.assertEqual(
            ["preselection", "coach_review"],
            list(sanitized["sections"].keys()),
        )
        self.assertEqual(
            ["filter", "validator"],
            sanitized["sections"]["preselection"]["roles"],
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
            "section_reviews": {
                "filter": {"presence": False},
                "validator": {"note": 12},
                "motivation": {"comment": "Motivé"},
            },
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
