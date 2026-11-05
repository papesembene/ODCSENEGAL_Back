"""Residence is personal information, never a training-site assignment."""

from app.services.trainings.schema import token

RESIDENCE_LOCATIONS = (
    "Dakar", "Diamniadio", "Diourbel", "Fatick", "Kaffrine", "Kaolack", "Kédougou",
    "Kolda", "Louga", "Matam", "Saint-Louis", "Sédhiou", "Tambacounda", "Thiès", "Ziguinchor",
)
_aliases = {token(value): value for value in RESIDENCE_LOCATIONS}
_aliases["tamba"] = "Tambacounda"


def canonical_residence(value):
    return _aliases.get(token(value)) if isinstance(value, str) else None
