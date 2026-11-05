"""Versioned training sites, without inferring a campus from residence."""

import threading
import time
from copy import deepcopy

from flask import current_app, has_app_context

from app.services.trainings.schema import TrainingCatalogError, token, training_code

DEFAULT_SITES = [
    {"code": code, "name": name, "description": "", "status": "active", "displayOrder": index * 10,
     "aliases": [code, name], "version": 0}
    for index, (code, name) in enumerate([
        ("dakar", "Dakar"), ("thies", "Thiès"), ("diamniadio-uam", "Diamniadio / UAM"),
        ("tambacounda", "Tambacounda"),
    ], 1)
]
_lock = threading.RLock()


def merge_sites(rows):
    merged = {row["code"]: deepcopy(row) for row in DEFAULT_SITES}
    merged.update({row["code"]: deepcopy(row) for row in rows})
    return sorted(merged.values(), key=lambda row: (row["displayOrder"], row["name"].casefold(), row["code"]))


def invalidate_sites():
    if has_app_context():
        with _lock:
            current_app.extensions.pop("training_sites_catalog", None)


def get_sites(force=False):
    if not has_app_context():
        return deepcopy(DEFAULT_SITES)
    from app.repositories.training_site_repository import TrainingSiteRepository
    with _lock:
        cached = current_app.extensions.get("training_sites_catalog")
        if not force and cached and cached["expires"] > time.monotonic():
            return deepcopy(cached["items"])
        items = merge_sites(TrainingSiteRepository().list())
        current_app.extensions["training_sites_catalog"] = {"items": items, "expires": time.monotonic() + 5}
        return deepcopy(items)


def require_site(code):
    site = next((row for row in get_sites() if row["code"] == code and row["status"] == "active"), None)
    if not site:
        raise TrainingCatalogError("Ce site de formation n'est plus disponible. Choisissez un autre site.")
    return site


def with_site_assignments(training):
    data = {key: deepcopy(value) for key, value in training.items()
            if key not in {"applicationRegionMode", "applicationRegions"}}
    defaults = {"dev-data": ["dakar", "thies", "diamniadio-uam"],
                "referent-digital": ["dakar", "tambacounda"],
                "fibre": ["tambacounda"], "fibre-optique": ["tambacounda"]}
    data.setdefault("siteIds", defaults.get(training["code"], ["dakar"]))
    return data


def validate_site_ids(values, published=False):
    import re
    if not isinstance(values, list) or len(values) > 100 or any(
        not isinstance(value, str) or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", value)
        or len(value) > 80 for value in values
    ):
        raise TrainingCatalogError("Les sites de formation sélectionnés sont invalides.")
    if published and not values:
        raise TrainingCatalogError("Choisissez au moins un site de formation avant de publier ce référentiel.")
    return list(dict.fromkeys(values))


def validate_site(payload, previous=None):
    if not isinstance(payload, dict) or set(payload) - {"name", "description", "status", "displayOrder", "version"}:
        raise TrainingCatalogError("Les informations du site sont invalides.")
    data = {**(previous or {}), **{key: value for key, value in payload.items() if key != "version"}}
    for field, limit in (("name", 120), ("description", 500)):
        value = data.get(field, "")
        if not isinstance(value, str) or len(value.strip()) > limit:
            raise TrainingCatalogError("Le nom ou la description du site est invalide.")
        data[field] = value.strip()
    if not data["name"]:
        raise TrainingCatalogError("Le nom du site est obligatoire.")
    if not isinstance(data.get("status", "active"), str) or data.get("status", "active") not in {"active", "archived"}:
        raise TrainingCatalogError("Le statut du site est invalide.")
    data["status"] = data.get("status", "active")
    order = data.get("displayOrder", 0)
    if type(order) is not int or not 0 <= order <= 10000:
        raise TrainingCatalogError("L'ordre du site doit être compris entre 0 et 10000.")
    data["displayOrder"] = order
    return data


class TrainingSiteService:
    def __init__(self, repository=None):
        from app.repositories.training_site_repository import TrainingSiteRepository
        self.repository = repository or TrainingSiteRepository()

    def list(self):
        return merge_sites(self.repository.list())

    def create(self, payload, actor=""):
        data = validate_site(payload)
        code = training_code(data["name"])
        data.update(code=code, aliases=[code, data["name"]])
        if any(row["code"] == code for row in self.list()):
            raise TrainingCatalogError("Un site utilise déjà ce nom ou cet identifiant.", 409)
        self._assert_available(data)
        if len(self.list()) >= 100:
            raise TrainingCatalogError("La limite de 100 sites est atteinte.")
        result = self.repository.save(data, 0, actor)
        invalidate_sites()
        return result

    def update(self, code, payload, actor=""):
        previous = next((row for row in self.list() if row["code"] == code), None)
        if not previous:
            raise TrainingCatalogError("Site introuvable.", 404)
        if not isinstance(payload, dict) or type(payload.get("version")) is not int:
            raise TrainingCatalogError("Actualisez le site avant de le modifier.")
        if payload["version"] != previous["version"]:
            raise TrainingCatalogError("Ce site a changé. Actualisez avant de réessayer.", 409)
        data = validate_site(payload, previous)
        data["aliases"] = list(dict.fromkeys([*previous["aliases"], previous["name"], data["name"]]))
        self._assert_available(data)
        result = self.repository.save(data, previous["version"], actor)
        invalidate_sites()
        return result

    def _assert_available(self, data):
        aliases = {token(value) for value in data["aliases"]}
        for row in self.list():
            if row["code"] != data["code"] and aliases.intersection(token(value) for value in row["aliases"]):
                raise TrainingCatalogError("Un site utilise déjà ce nom ou cet identifiant.", 409)
