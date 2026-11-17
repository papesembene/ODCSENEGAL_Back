"""Age eligibility predicates for candidate reads, without changing registrations."""

from calendar import monthrange
from datetime import datetime, time, timedelta, timezone


ELIGIBILITY_VALUES = frozenset({"all", "eligible", "ineligible", "unknown"})
MIN_BIRTH_DATE = datetime(1, 1, 1, tzinfo=timezone.utc)


def utc_today():
    return datetime.now(timezone.utc).date()


def age_eligibility_filter(value=None, *, today=None):
    """Classify stored birth dates by calendar age < 30 on the given UTC day."""
    if value is None or value == "all":
        return {}
    if not isinstance(value, str) or value not in ELIGIBILITY_VALUES:
        raise ValueError("Filtre d'éligibilité invalide")

    today = today or utc_today()
    tomorrow = datetime.combine(today + timedelta(days=1), time.min, timezone.utc)
    if value == "unknown":
        return {"$or": [
            {"date_of_birth": {"$not": {"$type": "date"}}},
            {"date_of_birth": {"$type": "array"}},
            {"date_of_birth": {"$type": "date", "$lt": MIN_BIRTH_DATE}},
            {"date_of_birth": {"$type": "date", "$gte": tomorrow}},
        ]}

    year = today.year - 30
    cutoff = today.replace(year=year, day=min(today.day, monthrange(year, today.month)[1]))
    younger_than_thirty = datetime.combine(cutoff + timedelta(days=1), time.min, timezone.utc)
    # Query $type also matches dates inside arrays; only scalar BSON dates are valid.
    bounds = {"$type": "date", "$not": {"$type": "array"}, "$gte": MIN_BIRTH_DATE}
    if value == "eligible":
        bounds.update({"$gte": younger_than_thirty, "$lt": tomorrow})
    else:
        bounds["$lt"] = younger_than_thirty
    return {"date_of_birth": bounds}
