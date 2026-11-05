"""Atomic catalogue persistence shared by referentials and training sites."""

from datetime import datetime

from mongoengine.errors import NotUniqueError

from app.services.trainings.schema import TrainingCatalogError, token


class VersionedCatalogRepository:
    document = None
    conflict_message = "Cet élément a changé. Actualisez avant de réessayer."

    def list(self):
        return [row.to_dict() for row in self.document.objects.order_by("code")]

    def save(self, data, expected_version, actor):
        aliases = sorted({token(alias) for alias in data["aliases"] if token(alias)})
        values = {key: value for key, value in data.items() if key not in {"version", "updatedAt"}}
        try:
            if expected_version == 0:
                row = self.document(code=data["code"], data=values, alias_tokens=aliases, updated_by=actor)
                row.save(force_insert=True)
            else:
                changed = self.document.objects(code=data["code"], version=expected_version).update_one(
                    set__data=values, set__alias_tokens=aliases, set__updated_by=actor,
                    set__updated_at=datetime.utcnow(), inc__version=1,
                )
                if not changed:
                    raise TrainingCatalogError(self.conflict_message, 409)
                row = self.document.objects(code=data["code"]).first()
            return row.to_dict()
        except NotUniqueError as error:
            raise TrainingCatalogError("Ce nom ou cet identifiant existe déjà. Actualisez le catalogue.", 409) from error
