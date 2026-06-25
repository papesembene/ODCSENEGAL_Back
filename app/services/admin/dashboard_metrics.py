"""Global, trend and module metrics for the admin dashboard."""

from datetime import datetime, timedelta

from app.models.candidature import Candidature
from app.models.event import Event, Registration
from app.models.startup import Startup
from app.models.test import Test
from app.models.test_group import TestGroup
from app.models.test_result import TestResult


FORMATIONS = (
    "Dev Web",
    "Data",
    "Hackeuse",
    "AWS",
    "Design UX/UI",
    "Cyber security",
    "Intelligence Artificielle",
)
DAYS_FR = ("Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim")


class DashboardMetricsService:
    def totals(self, now):
        competences = Candidature.objects.count()
        startups = Startup.objects(startup_name__ne=None).count()
        active_tests = Test.objects(status="active").count()
        scheduled_tests = Test.objects(
            status__in=["scheduled", "active"]
        ).count()
        upcoming_events = Event.objects(date__gte=now).count()
        accepted = Candidature.objects(status="accepted").count()
        return {
            "competences": competences,
            "startups": startups,
            "total": competences + startups,
            "active_tests": active_tests,
            "scheduled_tests": scheduled_tests,
            "upcoming_events": upcoming_events,
            "acceptance_rate": round(
                accepted / competences * 100,
                0,
            )
            if competences
            else 0,
            "growth": self._growth(now),
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
        tested = result_collection.count_documents({})
        admitted = result_collection.count_documents({"status": "admis"})
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

    def _growth(self, now):
        this_month = datetime(now.year, now.month, 1)
        previous_month = (
            datetime(now.year - 1, 12, 1)
            if now.month == 1
            else datetime(now.year, now.month - 1, 1)
        )
        current = Candidature.objects(
            created_at__gte=this_month
        ).count() + Startup.objects(
            startup_name__ne=None,
            createdAt__gte=this_month,
        ).count()
        previous = Candidature.objects(
            created_at__gte=previous_month,
            created_at__lt=this_month,
        ).count() + Startup.objects(
            startup_name__ne=None,
            createdAt__gte=previous_month,
            createdAt__lt=this_month,
        ).count()
        if previous:
            return round((current - previous) / previous * 100, 0)
        return 100 if current else 0

    def _formations(self):
        pipeline = [
            {"$match": {"desired_training": {"$in": list(FORMATIONS)}}},
            {
                "$group": {
                    "_id": "$desired_training",
                    "count": {"$sum": 1},
                }
            },
        ]
        rows = Candidature._get_collection().aggregate(pipeline)
        counts = {formation: 0 for formation in FORMATIONS}
        counts.update({row["_id"]: row["count"] for row in rows})
        return counts
