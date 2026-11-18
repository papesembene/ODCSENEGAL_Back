"""Only explicit, unambiguous editable age text defines an age policy."""

import unittest

from app.services.trainings.age_rules import AgeRule, parse_age_rule


class TrainingAgeRulesTest(unittest.TestCase):
    def test_explicit_ranges_accept_accents_spacing_and_educational_context(self):
        for text, expected in (
            ("Pas de niveau requis / Agé de 25 à 40 ans", AgeRule("range", 25, 40)),
            ("Bac+2 / ÂGÉE DE 18 À 30 ANS", AgeRule("range", 18, 30)),
            ("âgé(e) de 18à40ans", AgeRule("range", 18, 40)),
            ("Age de 18 a 18 ans", AgeRule("range", 18, 18)),
        ):
            with self.subTest(text=text):
                self.assertEqual(expected, parse_age_rule(text))

    def test_strict_over_literals_do_not_invent_an_upper_limit(self):
        for text in ("Agée de + de 18 ans", "plus de 18 ans", "+ de18ans",
                     "Pas de niveau requis / Agée de + de 18 ans"):
            with self.subTest(text=text):
                self.assertEqual(AgeRule("over", 18), parse_age_rule(text))

    def test_missing_malformed_negated_and_conflicting_policies_are_unknown(self):
        for text in (None, "", "Bac + 2 / BTS", "Entre 18 et 30", "18 à 30 ans", "Agé de 40 à 25 ans",
                     "Agé de 18 à 130 ans", "Agé de -1 à 30 ans", "plus de 180 ans", "pas plus de 18 ans",
                     "au plus de 18 ans", "non âgé de 18 à 30 ans", "Agé de 18 à 30 ans ou âgé de 25 à 40 ans",
                     "Agé de 18 à 30 ans / âge minimum inconnu", "Agé de 18 à 30 ans / plus de 25 ans"):
            with self.subTest(text=text):
                self.assertIsNone(parse_age_rule(text))

    def test_repeated_identical_explicit_rule_is_not_a_conflict(self):
        self.assertEqual(AgeRule("range", 18, 30), parse_age_rule("Agé de 18 à 30 ans / Agée de 18 à 30 ans"))


if __name__ == "__main__":
    unittest.main()
