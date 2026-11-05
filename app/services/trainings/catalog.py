"""Default catalogue and bounded, process-local read cache."""

import json
import threading
import time
from copy import deepcopy
from pathlib import Path

from flask import current_app, has_app_context

from app.services.trainings.schema import TrainingCatalogError, token
from app.services.trainings.regional_eligibility import with_regional_eligibility

DEFAULT_TRAININGS = [with_regional_eligibility(row) for row in
                    json.loads(Path(__file__).with_name("defaults.json").read_text(encoding="utf-8"))]
_lock = threading.RLock()


def merge_catalog(rows):
    merged = {row["code"]: deepcopy(row) for row in DEFAULT_TRAININGS}
    for row in rows:
        merged[row["code"]] = deepcopy(row)
    return sorted((with_regional_eligibility(row) for row in merged.values()),
                  key=lambda row: (row["displayOrder"], row["title"].casefold(), row["code"]))


def invalidate_catalog():
    if has_app_context():
        with _lock:
            current_app.extensions.pop("training_catalog", None)


def get_catalog(force=False):
    # Pure helpers and offline maintenance keep the legacy naming contract.
    if not has_app_context():
        return deepcopy(DEFAULT_TRAININGS)
    from app.repositories.training_repository import TrainingRepository

    with _lock:
        cached = current_app.extensions.get("training_catalog")
        if not force and cached and cached["expires"] > time.monotonic():
            return deepcopy(cached["items"])
        items = merge_catalog(TrainingRepository().list())
        current_app.extensions["training_catalog"] = {"items": items, "expires": time.monotonic() + 5}
        return deepcopy(items)


def find_training(value, catalog=None):
    wanted = token(value)
    if not wanted:
        return None
    for training in get_catalog() if catalog is None else catalog:
        aliases = [training["code"], training["value"], training["title"], *training.get("aliases", [])]
        if any(token(alias) == wanted for alias in aliases):
            return training
    return None


def require_training(value, *, public=False):
    training = find_training(value)
    if not training or training["status"] == "archived" or (public and training["status"] != "published"):
        raise TrainingCatalogError("Ce référentiel n'est plus proposé. Actualisez la liste des formations.")
    return training
