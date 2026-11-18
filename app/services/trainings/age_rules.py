"""Parse only explicit age requirements from editable training level text."""

from dataclasses import dataclass
from calendar import isleap, monthrange
from datetime import datetime, time, timedelta, timezone
import re
import unicodedata


AGE_PREFIX = r"\bage(?:e|\s*\(\s*e\s*\))?\s+de\s*"
RANGE = re.compile(AGE_PREFIX + r"([0-9]{1,3})\s*a\s*([0-9]{1,3})\s*ans?\b")
OVER = re.compile(r"(?:" + AGE_PREFIX + r")?(?:\bplus\s+de|\+\s*de)\s*([0-9]{1,3})\s*ans?\b")
AGE_WORD = re.compile(r"\bage(?:e|\s*\(\s*e\s*\))?\b")


@dataclass(frozen=True)
class AgeRule:
    kind: str
    min_age: int
    max_age: int | None = None


def birthday_cutoff(today, years):
    year = today.year - years
    return today.replace(year=year, day=min(today.day, monthrange(year, today.month)[1]))


def midnight(day):
    return datetime.combine(day, time.min, timezone.utc)


def rule_bounds(rule, today):
    """Return an inclusive lower/exclusive upper DOB interval for one age rule."""
    if rule.kind == "range":
        return (midnight(birthday_cutoff(today, rule.max_age + 1) + timedelta(days=1)),
                midnight(birthday_cutoff(today, rule.min_age) + timedelta(days=1)))
    cutoff = birthday_cutoff(today, rule.min_age)
    # Feb-29 birthdays use Mar-1 when their anniversary year is not a leap year.
    if (today.month, today.day) == (2, 29) and not isleap(cutoff.year):
        cutoff += timedelta(days=1)
    elif (today.month, today.day) == (3, 1) and not isleap(today.year) and isleap(cutoff.year):
        cutoff -= timedelta(days=1)
    return None, midnight(cutoff)


def parse_age_rule(level):
    """Return one unambiguous explicit rule, or None when policy is unknown."""
    if not isinstance(level, str):
        return None
    text = "".join(character for character in unicodedata.normalize("NFKD", level.casefold())
                   if not unicodedata.combining(character))
    rules, spans = set(), []
    for pattern, kind in ((RANGE, "range"), (OVER, "over")):
        for match in pattern.finditer(text):
            if re.search(r"\b(?:pas|non|au)\s*$", text[:match.start()]):
                return None
            minimum = int(match[1])
            maximum = int(match[2]) if kind == "range" else None
            if not 0 <= minimum <= 120 or (maximum is not None and not minimum <= maximum <= 120):
                return None
            rules.add(AgeRule(kind, minimum, maximum))
            spans.append(match.span())
    if len(rules) != 1 or any(not any(start <= match.start() < end for start, end in spans)
                              for match in AGE_WORD.finditer(text)):
        return None
    return next(iter(rules))
