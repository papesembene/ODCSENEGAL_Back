from datetime import datetime

from bson import ObjectId
from mongoengine.errors import ValidationError

from app.models.candidature_campaign import CandidatureCampaign
from app.services.trainings.catalog import require_training


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
                "lifecycleStatus": "upcoming",
                "message": "Les candidatures ouvrent bientôt.",
                "campaign": None,
            }

        data = campaign.to_dict()
        return {
            "isOpen": data["isOpen"],
            "lifecycleStatus": data["lifecycleStatus"],
            "message": self._status_message(data),
            "campaign": {
                key: data[key] for key in (
                    "id", "title", "promotion", "formation", "startAt", "endAt",
                    "status", "lifecycleStatus", "isOpen",
                )
            },
        }

    def assert_open(self, formation=None):
        status = self.get_public_status(formation)
        if status["isOpen"]:
            return status["campaign"]["id"]
        raise CandidatureCampaignServiceError(status["message"], 403)

    @staticmethod
    def _assert_no_overlap(values, exclude_id=None):
        """Two published campaigns may not cover the same formation on overlapping dates.

        Otherwise new applications silently go to the most recent one and the other looks open but stays empty.
        A campaign for "all" formations overlaps every formation; different formations may run at the same time.
        """
        if values.get("status") != "published":
            return
        formation = values.get("formation") or "all"
        query = CandidatureCampaign.objects(
            status="published", start_at__lt=values["end_at"], end_at__gt=values["start_at"],
        )
        if formation != "all":
            query = query.filter(formation__in=["all", formation])
        if exclude_id is not None:
            query = query.filter(id__ne=exclude_id)
        other = query.order_by("start_at").first()
        if other:
            dates = f"du {other.start_at.strftime('%d/%m/%Y %H:%M')} au {other.end_at.strftime('%d/%m/%Y %H:%M')}"
            scope = "toutes les formations" if other.formation == "all" else "cette formation"
            raise CandidatureCampaignServiceError(
                f"La campagne « {other.title} » est déjà publiée pour {scope} {dates}. "
                "Changez les dates, la formation, ou archivez l’autre campagne avant de publier celle-ci.",
                409,
            )

    def create(self, data, admin_email=""):
        values = self._normalize_payload(data)
        self._validate(values)
        self._assert_no_overlap(values)
        if values.get("formation", "all") != "all":
            require_training(values["formation"])
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
        if set(values) & {"status", "start_at", "end_at", "formation"}:
            # Renaming or describing a campaign never creates an overlap: only check when publication data changes.
            self._assert_no_overlap(merged, exclude_id=campaign.id)
        if "formation" in values and values["formation"] != campaign.formation and values["formation"] != "all":
            require_training(values["formation"])

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
        filters = {"status": "published"}
        if formation:
            filters["formation__in"] = ["all", formation]
        query = CandidatureCampaign.objects(**filters)
        open_campaign = query.filter(
            start_at__lte=now,
            end_at__gte=now,
        ).order_by(*(["-start_at", "-id"] if formation else ["end_at"])).first()
        if open_campaign:
            return open_campaign

        next_campaign = query.filter(start_at__gt=now).order_by("start_at").first()
        if next_campaign:
            return next_campaign

        return query.filter(end_at__lt=now).order_by("-end_at").first()

    @staticmethod
    def _status_message(status):
        if status["lifecycleStatus"] == "open":
            return "Les candidatures sont ouvertes."
        if status["lifecycleStatus"] == "upcoming":
            return "Les candidatures ouvrent bientôt."
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
        if "formation" in values and not values["formation"]:
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
