"""Global, trend and module metrics for the admin dashboard."""

from datetime import datetime, timedelta

from app.models.candidature import Candidature
from app.models.event import Event, Registration
from app.models.startup import Startup
from app.models.test import Test
from app.models.test_group import TestGroup
from app.models.test_result import TestResult
from app.services.trainings.catalog import find_training, get_catalog
from app.services.tests.campaign_scope import (
    current_campaign_year,
    test_ids_for_campaign,
    tests_for_campaign,
)


DAYS_FR = ("Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim")


class DashboardMetricsService:
    def totals(self, now):
        competences = Candidature.objects.count()
        startups = Startup.objects(startup_name__ne=None).count()
        campaign_tests = tests_for_campaign(current_campaign_year())
        active_tests = campaign_tests.filter(status="active").count()
        scheduled_tests = campaign_tests.filter(
            status__in=["scheduled", "active"]
        ).count()
        upcoming_events = Event.objects(date__gte=now).count()
        accepted = Candidature.objects(status="accepted").count()
        return {
            "competences": competences,
            "startups": startups,
            # Headline candidatures count the selected annual collection only.
            # Startup applications remain a separate metric.
            "total": competences,
            "active_tests": active_tests,
            "scheduled_tests": scheduled_tests,
            "upcoming_events": upcoming_events,
            "acceptance_rate": round(
                accepted / competences * 100,
                0,
            )
            if competences
            else 0,
            "application_variation": self._application_variation(now),
        }

    def trend(self, now, days):
        trend = []
        for offset in range(days - 1, -1, -1):
            date = now - timedelta(days=offset)
            start = datetime(date.year, date.month, date.day)
            end = start + timedelta(days=1)
            trend.append(
                {
                    "date": date.strftime("%d/%m"),
                    "day": DAYS_FR[date.weekday()],
                    "competences": Candidature.objects(
                        created_at__gte=start,
                        created_at__lt=end,
                    ).count(),
                    "startups": Startup.objects(
                        startup_name__ne=None,
                        createdAt__gte=start,
                        createdAt__lt=end,
                    ).count(),
                }
            )
        return trend

    def modules(self, now, totals):
        result_collection = TestResult._get_collection()
        test_ids = test_ids_for_campaign(current_campaign_year())
        tested = result_collection.count_documents({"testId": {"$in": test_ids}})
        admitted = result_collection.count_documents({
            "testId": {"$in": test_ids}, "status": "admis",
        })
        return {
            "competences": {
                "total": totals["competences"],
                "formations": self._formations(),
                "testsActifs": totals["active_tests"],
            },
            "startups": {
                "total": totals["startups"],
                "orangeFab": Startup.objects(
                    startup_name__ne=None,
                    program__in=["Orange Fab", "orange_fab"],
                ).count(),
                "startupLab": Startup.objects(
                    startup_name__ne=None,
                    program__in=["Startup Lab", "startup_lab"],
                ).count(),
            },
            "events": {
                "aVenir": totals["upcoming_events"],
                "participants": Registration.objects.count(),
                "ceMois": Event.objects(
                    date__gte=datetime(now.year, now.month, 1)
                ).count(),
            },
            "tests": {
                "actifs": totals["active_tests"],
                "candidatsTestes": tested,
                "tauxReussite": round(admitted / tested * 100, 0)
                if tested
                else 0,
            },
        }

    def _application_variation(self, now):
        this_month = datetime(now.year, now.month, 1)
        previous_month = (
            datetime(now.year - 1, 12, 1)
            if now.month == 1
            else datetime(now.year, now.month - 1, 1)
        )
        current = Candidature.objects(
            created_at__gte=this_month,
            created_at__lt=now,
        ).count()
        comparison_end = min(previous_month + (now - this_month), this_month)
        previous = Candidature.objects(
            created_at__gte=previous_month,
            created_at__lt=comparison_end,
        ).count()
        return current - previous

    def _formations(self):
        pipeline = [
            {
                "$group": {
                    "_id": "$desired_training",
                    "count": {"$sum": 1},
                }
            },
        ]
        rows = Candidature._get_collection().aggregate(pipeline)
        catalog = get_catalog()
        counts = {training["value"]: 0 for training in catalog}
        for row in rows:
            training = find_training(row["_id"], catalog)
            key = training["value"] if training else row["_id"]
            if key:
                counts[key] = counts.get(key, 0) + row["count"]
        return counts
