"""Small reusable CRUD service for simple MongoEngine catalogs."""


class CatalogValidationError(ValueError):
    pass


class CatalogService:
    def __init__(self, model, required_fields, allowed_fields):
        self.model = model
        self.required_fields = tuple(required_fields)
        self.allowed_fields = tuple(allowed_fields)

    def list_all(self):
        return [item.to_dict() for item in self.model.objects()]

    def create(self, data):
        data = data or {}
        for field in self.required_fields:
            if not data.get(field):
                raise CatalogValidationError(
                    f"Le champ {field} est requis",
                )
        values = {
            field: data[field]
            for field in self.allowed_fields
            if field in data
        }
        item = self.model(**values)
        item.save()
        return item
