"""Read-only age eligibility from the current, editable training catalogue."""

from collections import defaultdict
from datetime import datetime, timedelta, timezone

from bson.regex import Regex

from app.services.trainings.age_rules import midnight, parse_age_rule, rule_bounds
from app.services.trainings.schema import token
from app.utils.search import literal_pattern


ELIGIBILITY_VALUES = frozenset({"all", "eligible", "ineligible", "unknown"})
MIN_BIRTH_DATE = datetime(1, 1, 1, tzinfo=timezone.utc)


def utc_today():
    return datetime.now(timezone.utc).date()


def formation_patterns_by_rule(catalog):
    owners, rules = defaultdict(set), {}
    for index, training in enumerate(catalog):
        rules[index] = parse_age_rule(training.get("level"))
        aliases = training.get("aliases", [])
        aliases = aliases if isinstance(aliases, (list, tuple)) else []
        for value in [training.get("code"), training.get("value"), training.get("title"), *aliases]:
            if isinstance(value, str) and (alias := token(value)):
                owners[alias].add(index)
    grouped = defaultdict(list)
    for alias, indexes in sorted(owners.items()):
        if len(indexes) != 1:
            continue
        rule = rules[next(iter(indexes))]
        if rule is not None:
            # Match the catalogue token convention across case, accents and separators.
            separator = r"[^\p{L}\p{N}]"
            pattern = "^" + separator + "*" + (separator + "+").join(
                literal_pattern(part) for part in alias.split()) + separator + "*$"
            grouped[rule].append(Regex(pattern, "i"))
    return grouped


def age_eligibility_filter(value=None, *, today=None, catalog=None):
    """Build per-referential age predicates; absent policy never invents a rule."""
    if value is None or value == "all":
        return {}
    if not isinstance(value, str) or value not in ELIGIBILITY_VALUES:
        raise ValueError("Filtre d'éligibilité invalide")

    if catalog is None:
        # Import lazily: the catalogue itself is used while other filters are imported.
        from app.services.trainings.catalog import get_catalog
        catalog = get_catalog()
    today = today or utc_today()
    grouped = formation_patterns_by_rule(catalog)
    # Query $type also matches dates inside arrays; only scalar BSON dates are valid.
    valid = {"$type": "date", "$not": {"$type": "array"}, "$gte": MIN_BIRTH_DATE,
             "$lt": midnight(today + timedelta(days=1))}
    all_patterns = [pattern for patterns in grouped.values() for pattern in patterns]
    if not all_patterns:
        return {} if value == "unknown" else {"_id": {"$in": []}}
    known = {"desired_training": {"$type": "string", "$not": {"$type": "array"}, "$in": all_patterns}}
    if value == "unknown":
        return {"$or": [{"$nor": [{"date_of_birth": valid}]}, {"$nor": [known]}]}
    branches = []
    for rule, patterns in grouped.items():
        formation = {"desired_training": {"$type": "string", "$not": {"$type": "array"}, "$in": patterns}}
        lower, upper = rule_bounds(rule, today)
        if value == "eligible":
            dates = {**valid, "$lt": upper}
            if lower is not None:
                dates["$gte"] = lower
            branches.append({"$and": [formation, {"date_of_birth": dates}]})
        else:
            outside = [{"date_of_birth": {"$gte": upper}}]
            if lower is not None:
                outside.append({"date_of_birth": {"$lt": lower}})
            branches.append({"$and": [formation, {"date_of_birth": valid}, {"$or": outside}]})
    return {"$or": branches}
