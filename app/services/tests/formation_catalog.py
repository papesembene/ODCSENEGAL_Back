"""Referential naming backed by the shared training catalogue."""

from app.services.trainings.catalog import DEFAULT_TRAININGS, find_training, get_catalog
from app.services.trainings.schema import token as normalize_formation_token

# Compatibility exports for offline scripts; live workflows use get_catalog().
FORMATION_ALIASES = {item["value"]: tuple(item["aliases"]) for item in DEFAULT_TRAININGS}
FORMATIONS = tuple(FORMATION_ALIASES)


def normalize_formation(value):
    training = find_training(value)
    return training["value"] if training else value


def formation_aliases(value):
    training = find_training(value)
    aliases = [*training["aliases"], training["code"], training["value"], training["title"]] if training else []
    return list(dict.fromkeys([*aliases, value])) if value else aliases


def formation_values():
    return tuple(training["value"] for training in get_catalog())
