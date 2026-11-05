from app.models.training_site import TrainingSite
from app.repositories.versioned_catalog_repository import VersionedCatalogRepository


class TrainingSiteRepository(VersionedCatalogRepository):
    document = TrainingSite
    conflict_message = "Ce site a changé. Actualisez avant de réessayer."
