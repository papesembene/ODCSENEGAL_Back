"""Admin dashboard use case orchestration."""

from datetime import datetime

from app.models.candidature import Candidature
from app.models.startup import Startup
from app.services.admin.dashboard_activity_service import (
    DashboardActivityService,
)
from app.services.admin.dashboard_distributions import (
    DashboardDistributionService,
)
from app.services.admin.dashboard_metrics import DashboardMetricsService


class AdminDashboardService:
    def __init__(self):
        self.metrics = DashboardMetricsService()
        self.distributions = DashboardDistributionService()
        self.activities = DashboardActivityService()

    def build(self, days=7, now=None):
        now = now or datetime.utcnow()
        days = max(1, min(int(days), 90))
        totals = self.metrics.totals(now)
        return {
            "globalStats": {
                "totalCandidatures": totals["total"],
                "candidaturesCompetences": totals["competences"],
                "candidaturesStartups": totals["startups"],
                "testsProgrammes": totals["scheduled_tests"],
                "evenementsAVenir": totals["upcoming_events"],
                "tauxAcceptation": int(totals["acceptance_rate"]),
                "croissance": int(totals["growth"]),
            },
            "applicationsTrend": self.metrics.trend(now, days),
            "genderDistribution": self._safe(
                self.distributions.gender,
                totals["competences"],
            ),
            "statusDistribution": self._safe(
                self.distributions.status,
                totals["competences"],
            ),
            "nationalityDistribution": self._safe(
                self.distributions.nationality
            ),
            "recentActivities": self._safe(self.activities.recent, now),
            "moduleStats": self._safe(
                self.metrics.modules,
                now,
                totals,
                fallback=self._empty_modules(totals),
            ),
        }

    def fallback(self, warning):
        competences = Candidature.objects.count()
        startups = Startup.objects(startup_name__ne=None).count()
        totals = {
            "competences": competences,
            "startups": startups,
        }
        return {
            "success": True,
            "data": {
                "globalStats": {
                    "totalCandidatures": competences + startups,
                    "candidaturesCompetences": competences,
                    "candidaturesStartups": startups,
                    "testsProgrammes": 0,
                    "evenementsAVenir": 0,
                    "tauxAcceptation": 0,
                    "croissance": 0,
                },
                "applicationsTrend": [],
                "genderDistribution": [],
                "statusDistribution": [],
                "nationalityDistribution": [],
                "recentActivities": [],
                "moduleStats": self._empty_modules(totals),
            },
            "warning": warning,
        }

    @staticmethod
    def _safe(callback, *args, fallback=None):
        try:
            return callback(*args)
        except Exception:
            return [] if fallback is None else fallback

    @staticmethod
    def _empty_modules(totals):
        return {
            "competences": {
                "total": totals["competences"],
                "formations": {},
                "testsActifs": 0,
            },
            "startups": {
                "total": totals["startups"],
                "orangeFab": 0,
                "startupLab": 0,
            },
            "events": {"aVenir": 0, "participants": 0, "ceMois": 0},
            "tests": {
                "actifs": 0,
                "candidatsTestes": 0,
                "tauxReussite": 0,
            },
        }
