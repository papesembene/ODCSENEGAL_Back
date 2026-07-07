import unittest

from app.models.candidature import Candidature
from app.models.test import Test
from app.models.test_group import TestGroup
from app.models.test_result import TestResult
from app.models.test_violation import TestViolation


def declared_index_fields(model):
    fields = set()
    for index in model._meta.get("index_specs", []):
        fields.add(tuple(field for field, _direction in index.get("fields", [])))
    return fields


class DatabaseIndexesTest(unittest.TestCase):
    def test_candidature_indexes_cover_public_and_admin_queries(self):
        indexes = declared_index_fields(Candidature)
        self.assertIn(("email",), indexes)
        self.assertIn(("phone",), indexes)
        self.assertIn(("desired_training", "status", "created_at"), indexes)

    def test_online_test_indexes_cover_access_and_group_queries(self):
        test_indexes = declared_index_fields(Test)
        group_indexes = declared_index_fields(TestGroup)

        self.assertIn(("referentiel", "status"), test_indexes)
        self.assertIn(("status", "scheduledDate", "scheduledTime"), test_indexes)
        self.assertIn(("test_id", "status"), group_indexes)
        self.assertIn(("formation", "status", "candidate_ids"), group_indexes)

    def test_result_and_violation_indexes_cover_candidate_flow(self):
        result_indexes = declared_index_fields(TestResult)
        violation_indexes = declared_index_fields(TestViolation)

        self.assertIn(("testId", "candidate.email"), result_indexes)
        self.assertIn(("testId", "status", "completedAt"), result_indexes)
        self.assertIn(("referentiel", "status", "completedAt"), result_indexes)
        self.assertIn(("testId", "candidateEmail"), violation_indexes)
        self.assertIn(("testId", "updatedAt"), violation_indexes)
        self.assertIn(("testId", "totalViolations"), violation_indexes)


if __name__ == "__main__":
    unittest.main()
