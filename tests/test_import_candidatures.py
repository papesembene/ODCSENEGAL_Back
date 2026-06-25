import unittest

from app.utils.import_candidatures import parse_boolean


class ImportCandidaturesTest(unittest.TestCase):
    def test_parse_boolean_handles_legacy_answers(self):
        self.assertTrue(parse_boolean("Oui"))
        self.assertTrue(parse_boolean(" true "))
        self.assertFalse(parse_boolean("Non"))


if __name__ == "__main__":
    unittest.main()
