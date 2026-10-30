"""A failed integration setup must not leak the default MongoEngine alias."""

import importlib
import unittest
from unittest.mock import Mock, patch


class MongoFixtureCleanupTest(unittest.TestCase):
    def test_ping_failure_always_disconnects_without_dropping_a_database(self):
        fixtures = (
            ("test_delivery_and_sessions_integration", "DeliveryAndSessionsIntegrationTest", "connect"),
            ("test_factory_compatibility_integration", "FactoryCompatibilityIntegrationTest", "get_connection"),
            ("test_interview_access_integration", "InterviewAccessIntegrationTest", "connect"),
            ("test_result_queries_integration", "ResultQueriesIntegrationTest", "connect"),
            ("test_candidature_queries_integration", "CandidatureQueriesIntegrationTest", "connect"),
        )
        for module_name, class_name, connection_function in fixtures:
            with self.subTest(fixture=class_name):
                module = importlib.import_module(module_name)
                fixture = getattr(module, class_name)
                connection = Mock()
                connection.admin.command.side_effect = RuntimeError("MongoDB unavailable")
                # The factory also creates an app before obtaining its connection.
                with patch.object(module, "disconnect") as disconnect, patch.object(
                    module, connection_function, return_value=connection,
                ), patch.object(module, "create_app", create=True):
                    try:
                        with self.assertRaisesRegex(RuntimeError, "MongoDB unavailable"):
                            fixture.setUpClass()
                    finally:
                        fixture.doClassCleanups()
                    disconnect.assert_called_once_with()
                    connection.drop_database.assert_not_called()
