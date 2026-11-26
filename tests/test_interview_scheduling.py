import unittest
from datetime import datetime, timedelta

from app.services.interviews.exceptions import InterviewValidationError
from app.services.interviews.questionnaire import (
    config_weights, default_config, generate_questions, grade_answers, normalize_config, question_groups,
)
from app.services.interviews.scheduling import normalize_schedule, plan_times, validator_intervals


def schedule(**changes):
    return normalize_schedule({
        "start_date": "2035-12-07", "day_start": "09:00", "day_end": "11:00", "duration": 30,
        "breaks": [{"start": "10:00", "end": "10:15"}], "skip_weekends": True, **changes,
    })


class InterviewSchedulingTest(unittest.TestCase):
    now = datetime(2035, 1, 1)

    def test_times_skip_breaks_weekends_and_continue_next_day(self):
        # 2035-12-07 is a Friday: 09:00, 09:30, 10:15 fit; the next slot moves to Monday.
        times = plan_times(schedule(), [], 4, self.now)
        self.assertEqual(
            ["2035-12-07T09:00", "2035-12-07T09:30", "2035-12-07T10:15", "2035-12-10T09:00"],
            [value.isoformat(timespec="minutes") for value in times],
        )

    def test_times_avoid_intervals_already_booked_for_the_validator(self):
        busy = [(datetime(2035, 12, 7, 9, 10), datetime(2035, 12, 7, 9, 30))]
        times = plan_times(schedule(), busy, 3, self.now)
        # 09:30-10:00 fits before the break; a slot starting 09:40 would have overlapped it.
        self.assertEqual(
            ["2035-12-07T09:30", "2035-12-07T10:15", "2035-12-10T09:00"],
            [value.isoformat(timespec="minutes") for value in times],
        )
        duration = timedelta(minutes=30)
        for start in times:
            for busy_start, busy_end in busy:
                self.assertFalse(busy_start < start + duration and start < busy_end)

    def test_times_never_start_in_the_past(self):
        times = plan_times(schedule(), [], 1, datetime(2035, 12, 7, 9, 2))
        self.assertEqual(datetime(2035, 12, 7, 9, 5), times[0])

    def test_weekends_can_be_included(self):
        times = plan_times(schedule(day_end="09:30", breaks=[], skip_weekends=False), [], 2, self.now)
        self.assertEqual([datetime(2035, 12, 7, 9), datetime(2035, 12, 8, 9)], times)

    def test_invalid_schedules_are_rejected(self):
        for changes in (
            {"day_end": "08:00"}, {"duration": 3}, {"duration": 200}, {"day_end": "09:20"},
            {"breaks": [{"start": "08:00", "end": "09:30"}]}, {"start_date": "demain"}, {"day_start": "9h"},
        ):
            with self.subTest(changes=changes), self.assertRaises(InterviewValidationError):
                schedule(**changes)

    def test_validator_intervals_include_individual_and_legacy_shared_times(self):
        distribution = {"starts_at": "2035-12-01T10:00", "validators": {"v1": {
            "candidates": ["a", "b", "c"], "slots": {"c": {"at": "2035-12-02T09:00", "minutes": 15}},
        }}}
        self.assertEqual([
            (datetime(2035, 12, 2, 9), datetime(2035, 12, 2, 9, 15)),
            (datetime(2035, 12, 1, 10), datetime(2035, 12, 1, 10, 20)),
        ], validator_intervals(distribution, "v1"))
        self.assertEqual([], validator_intervals(distribution, "other"))


def bank(topics):
    rows = []
    for section, count in topics.items():
        for index in range(count):
            for profile in (("avec", "sans") if section == "technique" else ("tous",)):
                rows.append({
                    "section": section, "profile": profile, "topic": f"{section}-{index}", "prompt": f"{section} {profile} {index}",
                    "options": ["Un", "Deux", "Trois"] if section == "technique" else [], "correct": "A" if section == "technique" else "",
                    "points": 2,
                })
    return rows


class InterviewQuestionnaireConfigTest(unittest.TestCase):
    def test_config_must_cover_each_section_and_total_one_hundred(self):
        self.assertEqual(default_config(), normalize_config(None))
        config = {"technique": {"count": 4, "weight": 60}, "motivation": {"count": 2, "weight": 25}, "social": {"count": 1, "weight": 15}}
        self.assertEqual(config, normalize_config(config))
        for invalid in (
            {**config, "technique": {"count": 4, "weight": 61}},
            {**config, "social": {"count": 0, "weight": 15}},
            {key: value for key, value in config.items() if key != "social"},
            {**config, "motivation": {"count": 2, "weight": 25.5}},
        ):
            with self.subTest(invalid=invalid), self.assertRaises(InterviewValidationError):
                normalize_config(invalid)

    def test_generation_draws_the_configured_number_of_distinct_topics(self):
        config = {"technique": {"count": 3, "weight": 60}, "motivation": {"count": 2, "weight": 30}, "social": {"count": 1, "weight": 10}}
        rows = bank({"technique": 6, "motivation": 4, "social": 2})
        for _ in range(20):
            questions = generate_questions(rows, "avec", config)
            sections = [question["section"] for question in questions]
            self.assertEqual((3, 2, 1), (sections.count("technique"), sections.count("motivation"), sections.count("social")))
            self.assertEqual(len(questions), len({question["topic"] for question in questions}))
            self.assertEqual({"avec", "tous"}, {question["profile"] for question in questions})
            self.assertEqual([str(index) for index in range(1, 7)], [question["id"] for question in questions])

    def test_bank_needs_at_least_the_configured_number_of_topics(self):
        config = {"technique": {"count": 7, "weight": 50}, "motivation": {"count": 3, "weight": 30}, "social": {"count": 2, "weight": 20}}
        with self.assertRaisesRegex(InterviewValidationError, "au moins 7"):
            question_groups(bank({"technique": 6, "motivation": 3, "social": 2}), "sans", config)

    def test_scores_use_the_weights_saved_with_the_questionnaire(self):
        config = {"technique": {"count": 1, "weight": 70}, "motivation": {"count": 1, "weight": 20}, "social": {"count": 1, "weight": 10}}
        questions = [
            {"id": "1", "section": "technique", "options": ["A", "B", "C"], "correct": "A", "points": 2},
            {"id": "2", "section": "motivation", "options": [], "correct": "", "points": 4},
            {"id": "3", "section": "social", "options": [], "correct": "", "points": 4},
        ]
        answers = {"1": "A", "2": {"points": 2, "comment": ""}, "3": {"points": 4, "comment": ""}}
        _, scores = grade_answers(questions, answers, complete=True, weights=config_weights(config))
        self.assertEqual({"technique": 70.0, "motivation": 10.0, "social": 10.0, "global": 90.0}, scores)
        _, legacy = grade_answers(questions, answers, complete=True, weights=config_weights(None))
        self.assertEqual(50 + 15 + 20, legacy["global"])


if __name__ == "__main__":
    unittest.main()
