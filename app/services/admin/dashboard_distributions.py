"""Dashboard distributions computed with bounded database operations."""

from mongoengine import Q

from app.models.candidature import Candidature


GENDER_COLORS = {
    "Femmes": "#FF6384",
    "Hommes": "#36A2EB",
    "Non spécifié": "#CCCCCC",
}
NATIONALITY_COLORS = (
    "#FF6384",
    "#36A2EB",
    "#FFCE56",
    "#4BC0C0",
    "#9966FF",
    "#FF9F40",
    "#C9CBCF",
)


class DashboardDistributionService:
    def gender(self, total):
        women = Candidature.objects(
            Q(gender__iexact="femme")
            | Q(gender__iexact="f")
            | Q(gender__iexact="female")
            | Q(gender__iexact="féminin")
            | Q(gender__iexact="féminine")
        ).count()
        men = Candidature.objects(
            Q(gender__iexact="homme")
            | Q(gender__iexact="h")
            | Q(gender__iexact="male")
            | Q(gender__iexact="m")
            | Q(gender__iexact="masculin")
            | Q(gender__iexact="masculine")
        ).count()
        values = (
            ("Femmes", women),
            ("Hommes", men),
            ("Non spécifié", max(total - women - men, 0)),
        )
        return [
            {
                "name": name,
                "value": round(count / total * 100, 0) if total else 0,
                "count": count,
                "color": GENDER_COLORS[name],
            }
            for name, count in values
            if count
        ]

    def status(self, total):
        accepted = Candidature.objects(status="accepted").count()
        rejected = Candidature.objects(status="rejected").count()
        pending = max(total - accepted - rejected, 0)
        return [
            self._status_item("Acceptés", accepted, total),
            self._status_item("En attente", pending, total),
            self._status_item("Refusés", rejected, total),
        ]

    def nationality(self):
        pipeline = [
            {"$match": {"nationality": {"$nin": [None, ""]}}},
            {"$group": {"_id": "$nationality", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
            {"$limit": 20},
        ]
        rows = list(Candidature._get_collection().aggregate(pipeline))
        total = sum(row["count"] for row in rows)
        return [
            {
                "name": str(row["_id"]).strip(),
                "value": round(row["count"] / total * 100, 1)
                if total
                else 0,
                "count": row["count"],
                "color": NATIONALITY_COLORS[
                    index % len(NATIONALITY_COLORS)
                ],
            }
            for index, row in enumerate(rows)
            if str(row["_id"]).strip()
        ]

    @staticmethod
    def _status_item(name, count, total):
        return {
            "name": name,
            "value": round(count / total * 100, 0) if total else 0,
            "count": count,
        }
