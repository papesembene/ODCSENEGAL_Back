"""Atomic catalogue writes with optimistic concurrency control."""

from app.models.training import Training
from app.repositories.versioned_catalog_repository import VersionedCatalogRepository


class TrainingRepository(VersionedCatalogRepository):
    document = Training
    conflict_message = "Ce référentiel a changé. Actualisez avant de réessayer."
