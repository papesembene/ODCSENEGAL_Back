"""Recent dashboard activity projection."""

from datetime import datetime

from app.models.candidature import Candidature
from app.models.event import Event, Registration
from app.models.startup import Startup
from app.models.test_group import TestGroup


def _relative_time(now, value):
    delta = now - value
    if delta.days > 0:
        return f"Il y a {delta.days} jour(s)"
    hours = delta.seconds // 3600
    if hours:
        return f"Il y a {hours}h"
    return f"Il y a {delta.seconds // 60} min"


class DashboardActivityService:
    def recent(self, now=None):
        now = now or datetime.utcnow()
        activities = []
        self._append_candidatures(activities, now)
        self._append_groups(activities, now)
        self._append_startups(activities, now)
        self._append_events(activities, now)
        activities.sort(key=lambda item: item.pop("_timestamp"), reverse=True)
        return activities[:5]

    def _append_candidatures(self, activities, now):
        rows = Candidature.objects.order_by("-created_at").limit(5)
        for item in rows:
            created_at = item.created_at or item.id.generation_time
            self._append(
                activities,
                now,
                created_at,
                "candidature",
                "Compétences",
                f"Nouvelle candidature - {item.first_name} {item.last_name}",
            )

    def _append_groups(self, activities, now):
        rows = TestGroup.objects.order_by("-created_at").limit(2)
        for group in rows:
            if not group.created_at:
                continue
            count = len(group.candidate_ids or [])
            self._append(
                activities,
                now,
                group.created_at,
                "test",
                "Tests",
                f"{group.name} - {count} candidats",
            )

    def _append_startups(self, activities, now):
        rows = Startup.objects(
            startup_name__ne=None
        ).order_by("-createdAt").limit(2)
        for startup in rows:
            if not startup.createdAt:
                continue
            self._append(
                activities,
                now,
                startup.createdAt,
                "startup",
                "Startups",
                f"{startup.program or 'Programme'} - {startup.startup_name}",
            )

    def _append_events(self, activities, now):
        rows = Event.objects.order_by("-created_at").limit(2)
        for event in rows:
            if not event.created_at:
                continue
            count = Registration.objects(event_id=event.id).count()
            self._append(
                activities,
                now,
                event.created_at,
                "event",
                "Événements",
                f"{event.title} - {count} inscriptions",
            )

    @staticmethod
    def _append(
        activities,
        now,
        timestamp,
        activity_type,
        module,
        action,
    ):
        activities.append(
            {
                "type": activity_type,
                "module": module,
                "action": action,
                "time": _relative_time(now, timestamp),
                "_timestamp": timestamp,
            }
        )
