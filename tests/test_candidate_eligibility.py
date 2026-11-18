"""Age filters are calendar-based read predicates, including unknown legacy dates."""

from datetime import date, datetime, timezone
from copy import deepcopy
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from flask import Flask

from app.repositories.candidature_filters import candidate_filter
from app.routes.candidature_routes import candidature_bp
from app.services.candidatures.service import CandidatureService
from app.services.trainings.age_rules import AgeRule
from app.utils.candidate_eligibility import age_eligibility_filter, rule_bounds, utc_today
from age_rule_fixtures import CATALOG


class CandidateEligibilityTest(unittest.TestCase):
    def setUp(self):
        catalog = patch("app.services.trainings.catalog.get_catalog", return_value=deepcopy(CATALOG))
        catalog.start()
        self.addCleanup(catalog.stop)

    def test_absent_and_all_preserve_the_existing_unfiltered_read(self):
        self.assertEqual({}, age_eligibility_filter())
        self.assertEqual({}, age_eligibility_filter("all"))
        self.assertEqual(candidate_filter({}), candidate_filter({"eligibility": "all"}))

    def test_invalid_filter_values_are_rejected(self):
        for value in ("", "Eligible", "age", "under_30", 0, [], {}):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "éligibilité"):
                age_eligibility_filter(value, today=date(2026, 11, 17))

    def test_inclusive_range_covers_the_entire_maximum_completed_age(self):
        today = date(2026, 11, 17)
        self.assertEqual((datetime(1985, 11, 18, tzinfo=timezone.utc), datetime(2001, 11, 18, tzinfo=timezone.utc)),
                         rule_bounds(AgeRule("range", 25, 40), today))
        query = age_eligibility_filter("eligible", today=today, catalog=[CATALOG[0]])
        bounds = query["$or"][0]["$and"][1]["date_of_birth"]
        self.assertEqual(datetime(1995, 11, 18, tzinfo=timezone.utc), bounds["$gte"])
        self.assertEqual(datetime(2008, 11, 18, tzinfo=timezone.utc), bounds["$lt"])
        self.assertEqual("date", bounds["$type"])
        self.assertEqual({"$type": "array"}, bounds["$not"])
        self.assertNotIn("$expr", repr(query))

    def test_strict_over_eighteen_starts_the_day_after_the_eighteenth_birthday(self):
        self.assertEqual((None, datetime(2008, 11, 17, tzinfo=timezone.utc)),
                         rule_bounds(AgeRule("over", 18), date(2026, 11, 17)))

    def test_strict_over_leap_anniversaries_roll_to_march_1_without_waiting_until_nineteen(self):
        self.assertEqual((None, datetime(2010, 3, 1, tzinfo=timezone.utc)),
                         rule_bounds(AgeRule("over", 18), date(2028, 2, 29)))
        self.assertEqual((None, datetime(2008, 2, 29, tzinfo=timezone.utc)),
                         rule_bounds(AgeRule("over", 18), date(2026, 3, 1)))
        self.assertEqual((None, datetime(2008, 3, 2, tzinfo=timezone.utc)),
                         rule_bounds(AgeRule("over", 18), date(2026, 3, 2)))

    def test_unknown_includes_non_dates_arrays_and_future_dates(self):
        query = age_eligibility_filter("unknown", today=date(2026, 11, 17))
        valid = query["$or"][0]["$nor"][0]["date_of_birth"]
        self.assertEqual({"$type": "array"}, valid["$not"])
        self.assertEqual("date", valid["$type"])
        self.assertEqual(datetime(1, 1, 1, tzinfo=timezone.utc), valid["$gte"])
        self.assertEqual(datetime(2026, 11, 18, tzinfo=timezone.utc), valid["$lt"])
        self.assertIn("desired_training", query["$or"][1]["$nor"][0])

    def test_no_age_policy_never_invents_a_fallback(self):
        catalog = [CATALOG[-1]]
        self.assertEqual({}, age_eligibility_filter("unknown", catalog=catalog))
        for value in ("eligible", "ineligible"):
            self.assertEqual({"_id": {"$in": []}}, age_eligibility_filter(value, catalog=catalog))

    def test_policy_is_read_from_current_editable_metadata(self):
        catalog = deepcopy(CATALOG[:1])
        original = age_eligibility_filter("eligible", today=date(2026, 11, 17), catalog=catalog)
        catalog[0]["level"] = "Bac / Agé de 25 à 40 ans"
        changed = age_eligibility_filter("eligible", today=date(2026, 11, 17), catalog=catalog)
        self.assertNotEqual(original, changed)
        self.assertEqual(datetime(1985, 11, 18, tzinfo=timezone.utc),
                         changed["$or"][0]["$and"][1]["date_of_birth"]["$gte"])

    def test_default_day_comes_from_utc_clock(self):
        with patch("app.utils.candidate_eligibility.datetime") as clock:
            clock.now.return_value = datetime(2026, 11, 17, 23, 30, tzinfo=timezone.utc)
            self.assertEqual(date(2026, 11, 17), utc_today())
            clock.now.assert_called_once_with(timezone.utc)

    def test_eligibility_is_combined_with_existing_search_and_status(self):
        with patch("app.utils.candidate_eligibility.utc_today", return_value=date(2026, 11, 17)):
            query = candidate_filter({"eligibility": "eligible", "status": "accepted", "search": "Awa"})
        self.assertEqual(3, len(query["$and"]))
        self.assertIn("$or", query["$and"][0])
        self.assertIn({"status": "accepted"}, query["$and"])

    def test_bulk_service_uses_same_filter_for_rows_and_count(self):
        repository = Mock()
        repository.list_filtered.return_value = []
        repository.count_filtered.return_value = 0
        service = CandidatureService(repository=repository)
        service.list_candidatures(desired_training="Dev Web", eligibility="ineligible", page=2, per_page=10)
        filters = {"desired_training": "Dev Web", "eligibility": "ineligible"}
        repository.list_filtered.assert_called_once_with(filters, "", page=2, per_page=10)
        repository.count_filtered.assert_called_once_with(filters, "")
        repository.reset_mock()
        service.list_candidatures()
        repository.list_filtered.assert_called_once_with({}, "", page=None, per_page=None)
        repository.save.assert_not_called()


class CandidateEligibilityHttpTest(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__)
        app.config["TESTING"] = True
        app.register_blueprint(candidature_bp, url_prefix="/api/admin")
        self.http = app.test_client()
        auth = patch("app.utils.auth_decorators.AuthService.verify_token", return_value=SimpleNamespace(
            is_admin=True, admin_type="super_admin", profile_data={},
        ))
        auth.start()
        self.addCleanup(auth.stop)
        self.headers = {"Authorization": "Bearer synthetic-admin-token"}

    def test_bulk_route_passes_explicit_eligibility_to_existing_service(self):
        with patch("app.routes.candidature_routes.candidature_service.list_candidatures", return_value={
            "data": [], "total": 0, "page": None, "per_page": None,
        }) as service:
            response = self.http.get("/api/admin/candidatures?eligibility=eligible", headers=self.headers)
        self.assertEqual(200, response.status_code)
        self.assertEqual("eligible", service.call_args.kwargs["eligibility"])

    def test_invalid_filter_fails_on_bulk_page_and_export_before_any_database_read(self):
        with patch("app.repositories.candidature_repository.Candidature") as model, patch(
            "app.repositories.candidature_read_repository.CandidatureReadRepository.collection",
        ) as collection:
            for suffix in ("?eligibility=bad", "?page=1&eligibility=bad", "/export?eligibility=bad"):
                with self.subTest(suffix=suffix):
                    response = self.http.get("/api/admin/candidatures" + suffix, headers=self.headers)
                    self.assertEqual(400, response.status_code)
            model.objects.assert_not_called()
            collection.assert_not_called()


if __name__ == "__main__":
    unittest.main()
