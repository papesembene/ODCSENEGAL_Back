"""Parse only explicit age requirements from editable training level text."""

from dataclasses import dataclass
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
