from datetime import datetime

from bson import ObjectId
from mongoengine.errors import ValidationError

from app.models.portal_content import PortalContent


class PortalContentServiceError(Exception):
    def __init__(self, message, status_code=400):
        super().__init__(message)
        self.status_code = status_code


class PortalContentService:
    WRITABLE_FIELDS = {
        "type",
        "slot_key",
        "title",
        "summary",
        "body",
        "category",
        "image_url",
        "link_label",
        "link_url",
        "placement",
        "priority",
        "is_pinned",
        "status",
        "starts_at",
        "ends_at",
    }

    FIELD_ALIASES = {
        "imageUrl": "image_url",
        "slotKey": "slot_key",
        "linkLabel": "link_label",
        "linkUrl": "link_url",
        "isPinned": "is_pinned",
        "startsAt": "starts_at",
        "endsAt": "ends_at",
    }

    def list_admin(self, content_type=None, status=None):
        query = {}
        if content_type and content_type != "all":
            query["type"] = content_type
        if status and status != "all":
            query["status"] = status
        return [
            content.to_dict()
            for content in PortalContent.objects(**query).order_by(
                "-is_pinned",
                "-priority",
                "-updated_at",
            )
        ]

    def list_public(self, content_type=None, placement="home"):
        now = datetime.utcnow()
        query = {
            "status": "published",
            "placement": placement or "home",
        }
        if content_type and content_type != "all":
            query["type"] = content_type

        contents = PortalContent.objects(**query).order_by(
            "-is_pinned",
            "-priority",
            "-created_at",
        )
        return [
            content.to_dict()
            for content in contents
            if self._is_visible_now(content, now)
        ]

    def create(self, data, admin_email=""):
        values = self._normalize_payload(data)
        self._validate_required(values)
        values["created_by"] = admin_email or ""
        values["updated_by"] = admin_email or ""

        try:
            content = PortalContent(**values)
            content.save()
            return content.to_dict()
        except ValidationError as error:
            raise PortalContentServiceError(
                f"Erreur de validation: {error}",
            ) from error

    def update(self, content_id, data, admin_email=""):
        content = self._get_document(content_id)
        values = self._normalize_payload(data)
        if not values:
            raise PortalContentServiceError("Aucune modification fournie")

        for key, value in values.items():
            setattr(content, key, value)
        content.updated_by = admin_email or content.updated_by
        content.updated_at = datetime.utcnow()

        try:
            content.save()
            return content.to_dict()
        except ValidationError as error:
            raise PortalContentServiceError(
                f"Erreur de validation: {error}",
            ) from error

    def delete(self, content_id):
        content = self._get_document(content_id)
        content.delete()

    @staticmethod
    def _get_document(content_id):
        if not ObjectId.is_valid(str(content_id)):
            raise PortalContentServiceError("Identifiant invalide", 400)
        content = PortalContent.objects(id=content_id).first()
        if not content:
            raise PortalContentServiceError("Contenu introuvable", 404)
        return content

    @classmethod
    def _normalize_payload(cls, data):
        raw_values = dict(data or {})
        values = {}
        for key, value in raw_values.items():
            normalized_key = cls.FIELD_ALIASES.get(key, key)
            if normalized_key not in cls.WRITABLE_FIELDS:
                continue
            values[normalized_key] = cls._normalize_value(normalized_key, value)
        return values

    @staticmethod
    def _normalize_value(key, value):
        if key == "priority":
            try:
                return int(value or 0)
            except (TypeError, ValueError) as error:
                raise PortalContentServiceError(
                    "La priorité doit être un nombre"
                ) from error
        if key == "is_pinned":
            return bool(value)
        if key in {"starts_at", "ends_at"}:
            return PortalContentService._parse_date(value)
        if isinstance(value, str):
            return value.strip()
        return value

    @staticmethod
    def _parse_date(value):
        if not value:
            return None
        if isinstance(value, datetime):
            return value
        try:
            normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
            return datetime.fromisoformat(normalized).replace(tzinfo=None)
        except (AttributeError, ValueError) as error:
            raise PortalContentServiceError(
                "Format de date invalide"
            ) from error

    @staticmethod
    def _validate_required(values):
        if not values.get("type"):
            raise PortalContentServiceError("Le type est requis")
        if not values.get("title"):
            raise PortalContentServiceError("Le titre est requis")
        if values["type"] not in PortalContent.CONTENT_TYPES:
            raise PortalContentServiceError("Type de contenu invalide")
        if values.get("status") and values["status"] not in PortalContent.STATUSES:
            raise PortalContentServiceError("Statut invalide")

    @staticmethod
    def _is_visible_now(content, now):
        if content.starts_at and content.starts_at > now:
            return False
        if content.ends_at and content.ends_at < now:
            return False
        return True
