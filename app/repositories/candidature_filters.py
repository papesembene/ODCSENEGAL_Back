"""Literal, accent-insensitive filters shared by candidate pages and exports."""

from app.services.tests.formation_catalog import formation_aliases
from app.utils.search import literal_pattern, text_search_filter
import re


SEARCH_FIELDS = ("first_name", "last_name", "email", "phone", "nationality", "pays", "country")
GENDERS = {
    "female": ("female", "femme", "f", "feminin"),
    "male": ("male", "homme", "h", "m", "masculin"),
}


def candidate_filter(filters):
    clauses = []
    site = filters.get("training_site")
    if site and site != "all":
        if not isinstance(site, str) or len(site) > 80 or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", site):
            raise ValueError("Site de formation invalide")
        clauses.append({"training_site": site})
    formation = filters.get("desired_training")
    if formation and formation != "all":
        aliases = formation_aliases(formation)
        clauses.append({"desired_training": {"$in": list(dict.fromkeys(
            variant for alias in aliases for variant in (alias, alias.lower())
        ))}})
    status = filters.get("status")
    if status and status != "all":
        if status == "pending":
            clauses.append({"status": {"$in": ["pending", "", None]}})
        elif status in {"interview", "interviewed"}:
            clauses.append({"status": {"$in": ["interview", "interviewed"]}})
        elif status in {"accepted", "rejected"}:
            clauses.append({"status": status})
        else:
            raise ValueError("Statut de candidature invalide")
    gender = filters.get("gender")
    if gender and gender != "all":
        if gender not in GENDERS:
            raise ValueError("Genre invalide")
        pattern = "^\\s*(?:" + "|".join(literal_pattern(value) for value in GENDERS[gender]) + ")\\s*$"
        clauses.append({"gender": {"$regex": pattern, "$options": "i"}})

    search = text_search_filter(filters.get("search"), SEARCH_FIELDS, ("phone",))
    if search:
        clauses.append(search)
    return {"$and": clauses} if clauses else {}
