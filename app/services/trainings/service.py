"""Manage referentials without renaming or deleting historical records."""

from app.repositories.training_repository import TrainingRepository
from app.services.trainings.catalog import invalidate_catalog, merge_catalog
from app.services.trainings.schema import TrainingCatalogError, token, training_code, validate_training
from app.services.trainings.sites import get_sites, with_site_assignments


class TrainingCatalogService:
    def __init__(self, repository=None, site_catalog=None):
        self.repository = repository or TrainingRepository()
        self.site_catalog = site_catalog or get_sites

    def list(self):
        return merge_catalog(self.repository.list())

    def create(self, payload, actor=""):
        data = validate_training(payload)
        code = training_code(data["title"])
        data.update(id=code, code=code, value=code, legacyId=None, aliases=[code, data["title"]])
        data = with_site_assignments(data)
        self._assert_sites(data, payload)
        catalog = self.list()
        if any(row["code"] == code for row in catalog):
            raise TrainingCatalogError("Un référentiel utilise déjà cet identifiant.", 409)
        if len(catalog) >= 1000:
            raise TrainingCatalogError("La limite de 1000 référentiels est atteinte.")
        self._assert_aliases_available(data, catalog)
        result = self.repository.save(data, 0, actor)
        invalidate_catalog()
        return result

    def update(self, code, payload, actor=""):
        catalog = self.list()
        previous = next((row for row in catalog if row["code"] == code), None)
        if not previous:
            raise TrainingCatalogError("Référentiel introuvable.", 404)
        if not isinstance(payload, dict) or type(payload.get("version")) is not int:
            raise TrainingCatalogError("La version du référentiel est requise. Actualisez la page.")
        if payload["version"] != previous["version"]:
            raise TrainingCatalogError("Ce référentiel a changé. Actualisez avant de réessayer.", 409)
        data = validate_training(payload, previous)
        self._assert_sites(data, payload)
        data["aliases"] = list(dict.fromkeys([*previous["aliases"], previous["title"], data["title"]]))
        self._assert_aliases_available(data, catalog)
        result = self.repository.save(data, previous["version"], actor)
        invalidate_catalog()
        return result

    def archive(self, code, version, actor=""):
        return self.update(code, {"status": "archived", "version": version}, actor)

    def _assert_sites(self, data, payload):
        if "siteIds" not in payload:
            return
        known = {site["code"] for site in self.site_catalog(force=True)}
        if set(data["siteIds"]) - known:
            raise TrainingCatalogError("Un site sélectionné n'existe plus. Actualisez la liste des sites.")

    @staticmethod
    def _assert_aliases_available(data, catalog):
        aliases = {token(alias) for alias in data["aliases"]}
        for row in catalog:
            if row["code"] != data["code"] and aliases.intersection(token(alias) for alias in row["aliases"]):
                raise TrainingCatalogError("Un référentiel utilise déjà ce nom ou cet identifiant.", 409)
