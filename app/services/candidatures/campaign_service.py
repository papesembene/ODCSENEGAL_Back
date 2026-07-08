from datetime import datetime

from bson import ObjectId
from mongoengine.errors import ValidationError

from app.models.candidature_campaign import CandidatureCampaign


class CandidatureCampaignServiceError(Exception):
    def __init__(self, message, status_code=400):
        super().__init__(message)
        self.status_code = status_code


class CandidatureCampaignService:
    WRITABLE_FIELDS = {
        "title",
        "promotion",
        "formation",
        "start_at",
        "end_at",
        "status",
        "description",
    }
    FIELD_ALIASES = {
        "startAt": "start_at",
        "endAt": "end_at",
    }

    def list_admin(self, formation=None):
        query = {}
        if formation and formation != "all":
            query["formation"] = formation
        return [
            campaign.to_dict()
            for campaign in CandidatureCampaign.objects(**query).order_by(
                "-start_at",
                "-created_at",
            )
        ]

    def get_public_status(self, formation=None):
        campaign = self.find_current_or_next(formation=formation)
        if not campaign:
            return {
                "isOpen": False,
                "lifecycleStatus": "closed",
                "message": "Les candidatures ne sont pas encore ouvertes.",
                "campaign": None,
            }

        data = campaign.to_dict()
        return {
            "isOpen": data["isOpen"],
            "lifecycleStatus": data["lifecycleStatus"],
            "message": self._status_message(data),
            "campaign": data,
        }

    def assert_open(self, formation=None):
        status = self.get_public_status(formation)
        if status["isOpen"]:
            return
        raise CandidatureCampaignServiceError(status["message"], 403)

    def create(self, data, admin_email=""):
        values = self._normalize_payload(data)
        self._validate(values)
        values["created_by"] = admin_email or ""
        values["updated_by"] = admin_email or ""

        try:
            campaign = CandidatureCampaign(**values)
            campaign.save()
            return campaign.to_dict()
        except ValidationError as error:
            raise CandidatureCampaignServiceError(
                f"Erreur de validation: {error}"
            ) from error

    def update(self, campaign_id, data, admin_email=""):
        campaign = self._get_document(campaign_id)
        values = self._normalize_payload(data)
        if not values:
            raise CandidatureCampaignServiceError("Aucune modification fournie")

        merged = {
            "title": campaign.title,
            "promotion": campaign.promotion,
            "formation": campaign.formation,
            "start_at": campaign.start_at,
            "end_at": campaign.end_at,
            "status": campaign.status,
            "description": campaign.description,
            **values,
        }
        self._validate(merged)

        for key, value in values.items():
            setattr(campaign, key, value)
        campaign.updated_by = admin_email or campaign.updated_by
        campaign.updated_at = datetime.utcnow()

        try:
            campaign.save()
            return campaign.to_dict()
        except ValidationError as error:
            raise CandidatureCampaignServiceError(
                f"Erreur de validation: {error}"
            ) from error

    def find_current_or_next(self, formation=None):
        now = datetime.utcnow()
        formation_values = ["all"]
        if formation:
            formation_values.append(formation)

        query = CandidatureCampaign.objects(
            status="published",
            formation__in=formation_values,
        )
        open_campaign = query.filter(
            start_at__lte=now,
            end_at__gte=now,
        ).order_by("end_at").first()
        if open_campaign:
            return open_campaign

        return query.filter(start_at__gt=now).order_by("start_at").first()

    @staticmethod
    def _status_message(status):
        if status["lifecycleStatus"] == "open":
            return "Les candidatures sont ouvertes."
        if status["lifecycleStatus"] == "upcoming":
            return "Les candidatures ouvriront prochainement."
        return "Les candidatures sont fermées."

    @staticmethod
    def _get_document(campaign_id):
        if not ObjectId.is_valid(str(campaign_id)):
            raise CandidatureCampaignServiceError("Identifiant invalide", 400)
        campaign = CandidatureCampaign.objects(id=campaign_id).first()
        if not campaign:
            raise CandidatureCampaignServiceError("Campagne introuvable", 404)
        return campaign

    @classmethod
    def _normalize_payload(cls, data):
        values = {}
        for key, value in dict(data or {}).items():
            normalized_key = cls.FIELD_ALIASES.get(key, key)
            if normalized_key not in cls.WRITABLE_FIELDS:
                continue
            values[normalized_key] = cls._normalize_value(normalized_key, value)
        if not values.get("formation"):
            values["formation"] = "all"
        return values

    @staticmethod
    def _normalize_value(key, value):
        if key in {"start_at", "end_at"}:
            return CandidatureCampaignService._parse_date(value)
        if isinstance(value, str):
            return value.strip()
        return value

    @staticmethod
    def _parse_date(value):
        if isinstance(value, datetime):
            return value
        if not value:
            return None
        try:
            normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
            return datetime.fromisoformat(normalized).replace(tzinfo=None)
        except (AttributeError, ValueError) as error:
            raise CandidatureCampaignServiceError("Format de date invalide") from error

    @staticmethod
    def _validate(values):
        if not values.get("title"):
            raise CandidatureCampaignServiceError("Le titre est requis")
        if not values.get("start_at") or not values.get("end_at"):
            raise CandidatureCampaignServiceError("Les dates d'ouverture et de fermeture sont requises")
        if values["end_at"] <= values["start_at"]:
            raise CandidatureCampaignServiceError("La date de fermeture doit être après la date d'ouverture")
        if values.get("status") and values["status"] not in CandidatureCampaign.STATUSES:
            raise CandidatureCampaignServiceError("Statut invalide")
