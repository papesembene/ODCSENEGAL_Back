"""Bounded candidate reads and database aggregates, without loading all documents."""

from datetime import datetime, timedelta, timezone
from math import ceil

from app.models.candidature import Candidature
from app.repositories.candidature_filters import candidate_filter
from app.services.tests.formation_catalog import normalize_formation


PAGE_FIELDS = ("first_name", "last_name", "email", "phone", "gender", "desired_training", "status", "created_at")
TRAININGS = {
    "Dev Web": "dev-web-mobile", "Data": "dev-data", "Hackeuse": "hackeuses",
    "AWS": "aws-cloud", "R\u00e9f\u00e9rent Digital": "referent-digital",
    "Cyber security": "cyber-security", "Intelligence Artificielle": "intelligence-artificielle",
}
EMPTY_COUNTS = dict(total=0, femmes=0, hommes=0, acceptes=0, enAttente=0, refuses=0)


def bounded_integer(value, default, maximum):
    try:
        number = int(value) if value is not None else default
    except (TypeError, ValueError) as error:
        raise ValueError("Pagination invalide") from error
    if not 1 <= number <= maximum:
        raise ValueError(f"Valeur attendue entre 1 et {maximum}")
    return number


def serialize_candidate(row):
    data = {key: value.isoformat() if isinstance(value, datetime) else value
            for key, value in row.items() if key != "_id"}
    data["id"] = str(row["_id"])
    data["application_date"] = data.get("created_at")
    data["status"] = data.get("status") or "pending"
    return data


def count_expression():
    gender = {"$toLower": {"$trim": {"input": {"$ifNull": ["$gender", ""]}}}}
    status = {"$ifNull": ["$status", "pending"]}
    counts = {"total": {"$sum": 1}}
    for key, expression in {
        "femmes": {"$in": [gender, ["female", "femme", "f", "f\u00e9minin", "feminin"]]},
        "hommes": {"$in": [gender, ["male", "homme", "h", "m", "masculin"]]},
        "acceptes": {"$eq": [status, "accepted"]},
        "enAttente": {"$in": [status, ["pending", ""]]},
        "refuses": {"$eq": [status, "rejected"]},
    }.items():
        counts[key] = {"$sum": {"$cond": [expression, 1, 0]}}
    return counts


class CandidatureReadRepository:
    @staticmethod
    def collection():
        return Candidature._get_collection()

    def page(self, filters):
        requested = bounded_integer(filters.get("page"), 1, 10000000)
        per_page = bounded_integer(filters.get("per_page"), 20, 100)
        query = candidate_filter(filters)
        collection = self.collection()
        total = collection.count_documents(query, maxTimeMS=15000)
        pages = max(1, ceil(total / per_page))
        page = min(requested, pages)
        cursor = collection.find(query, {field: 1 for field in PAGE_FIELDS}).sort(
            [("created_at", -1), ("_id", -1)],
        ).skip((page - 1) * per_page).limit(per_page).max_time_ms(15000)
        return {"data": [serialize_candidate(row) for row in cursor], "total": total,
                "page": page, "per_page": per_page,
                "pagination": {"page": page, "per_page": per_page, "total": total, "total_pages": pages}}

    def dashboard(self, days=7):
        days = bounded_integer(days, 7, 90)
        today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        start = today - timedelta(days=days - 1)
        counts = count_expression()
        result = next(self.collection().aggregate([{"$facet": {
            "stats": [{"$group": {"_id": None, **counts}}],
            "formations": [{"$group": {"_id": "$desired_training", **counts}}],
            "nationalities": [
                {"$group": {"_id": {"$trim": {"input": {"$ifNull": ["$nationality", ""]}}}, "value": {"$sum": 1}}},
                {"$match": {"_id": {"$ne": ""}}}, {"$sort": {"value": -1, "_id": 1}},
            ],
            "daily": [
                {"$match": {"created_at": {"$gte": start, "$lt": today + timedelta(days=1)}}},
                {"$group": {"_id": {"$dateToString": {"format": "%Y-%m-%d", "date": "$created_at", "timezone": "UTC"}}, "value": {"$sum": 1}}},
            ],
        }}], maxTimeMS=15000))
        formations = {}
        for row in result["formations"]:
            key = TRAININGS.get(normalize_formation(row["_id"]), row["_id"]) or "Non renseigne"
            totals = formations.setdefault(key, dict(EMPTY_COUNTS))
            for field in EMPTY_COUNTS:
                totals[field] += row[field]
        daily = {row["_id"]: row["value"] for row in result["daily"]}
        return {
            "stats": {field: (result["stats"][0][field] if result["stats"] else 0) for field in EMPTY_COUNTS},
            "formations": formations,
            "nationalities": [{"name": row["_id"], "value": row["value"]} for row in result["nationalities"]],
            "daily": [{"date": (day := start + timedelta(days=index)).strftime("%d/%m"),
                       "applications": daily.get(day.strftime("%Y-%m-%d"), 0)} for index in range(days)],
        }

    def export_rows(self, filters):
        cursor = self.collection().find(candidate_filter(filters)).sort(
            [("created_at", -1), ("_id", -1)],
        ).batch_size(500).max_time_ms(60000)
        try:
            for row in cursor:
                yield serialize_candidate(row)
        finally:
            cursor.close()
