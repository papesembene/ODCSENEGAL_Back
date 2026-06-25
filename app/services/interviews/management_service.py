"""Campaign and slot use cases for the interview module."""

from datetime import datetime

from app.repositories.interview_repository import InterviewRepository
from app.services.interviews.exceptions import (
    InterviewConflictError,
    InterviewNotFoundError,
    InterviewValidationError,
)
from app.services.interviews.scorecard_service import (
    get_default_scorecard_config,
    sanitize_scorecard_config,
)


class InterviewManagementService:
    CAMPAIGN_UPDATE_FIELDS = ("name", "formation", "description", "status")
    SLOT_UPDATE_FIELDS = (
        "label",
        "formation",
        "status",
        "assigned_filter_ids",
        "assigned_jury_ids",
        "assigned_validator_ids",
        "assigned_motivation_ids",
    )

    def __init__(self, repository=None, now=None):
        self.repository = repository or InterviewRepository()
        self.now = now or datetime.utcnow

    def create_campaign(self, data):
        name = self._required_text(data, "name")
        formation = self._required_text(data, "formation")
        campaign = self.repository.create_campaign(
            name=name,
            formation=formation,
            description=(data.get("description") or "").strip(),
            status=data.get("status", "draft"),
            scorecard_config=get_default_scorecard_config(formation),
            created_by=data.get("created_by"),
        )
        campaign.updated_at = self.now()
        return self.repository.save_campaign(campaign)

    def update_campaign(self, campaign_id, data):
        campaign = self.repository.get_campaign(campaign_id)
        if not campaign:
            raise InterviewNotFoundError("Campagne non trouvée")

        for field in self.CAMPAIGN_UPDATE_FIELDS:
            if field in data:
                setattr(campaign, field, data[field])

        if "scorecard_config" in data:
            if self.repository.campaign_has_evaluations(campaign_id):
                raise InterviewConflictError(
                    "La grille ne peut plus être modifiée après la "
                    "planification. Créez une nouvelle campagne."
                )
            try:
                campaign.scorecard_config = sanitize_scorecard_config(
                    data["scorecard_config"],
                )
            except ValueError as error:
                raise InterviewValidationError(str(error)) from error

        campaign.updated_at = self.now()
        return self.repository.save_campaign(campaign)

    def create_slot(self, data):
        required_fields = (
            "campaign_id",
            "label",
            "formation",
            "start_at",
            "end_at",
        )
        missing_fields = [
            field for field in required_fields if not data.get(field)
        ]
        if missing_fields:
            raise InterviewValidationError(
                f"Champs requis: {', '.join(missing_fields)}"
            )

        start_at = self.parse_datetime(data.get("start_at"), "start_at")
        end_at = self.parse_datetime(data.get("end_at"), "end_at")
        slot = self.repository.create_slot(
            campaign_id=data["campaign_id"],
            label=data["label"].strip(),
            formation=data["formation"].strip(),
            start_at=start_at,
            end_at=end_at,
            capacity=int(data.get("capacity", 10) or 10),
            assigned_filter_ids=data.get(
                "assigned_filter_ids",
                data.get("assigned_jury_ids", []),
            ),
            assigned_jury_ids=data.get(
                "assigned_jury_ids",
                data.get("assigned_filter_ids", []),
            ),
            assigned_validator_ids=data.get(
                "assigned_validator_ids",
                [],
            ),
            assigned_motivation_ids=data.get(
                "assigned_motivation_ids",
                [],
            ),
            status=data.get("status", "scheduled"),
        )
        slot.updated_at = self.now()
        return self.repository.save_slot(slot)

    def update_slot(self, slot_id, data):
        slot = self.repository.get_slot(slot_id)
        if not slot:
            raise InterviewNotFoundError("Créneau non trouvé")

        for field in self.SLOT_UPDATE_FIELDS:
            if field in data:
                setattr(slot, field, data[field])

        if (
            "assigned_filter_ids" in data
            and "assigned_jury_ids" not in data
        ):
            slot.assigned_jury_ids = data["assigned_filter_ids"]
        if (
            "assigned_jury_ids" in data
            and "assigned_filter_ids" not in data
        ):
            slot.assigned_filter_ids = data["assigned_jury_ids"]

        if "capacity" in data:
            slot.capacity = int(data["capacity"] or 0)
        if "start_at" in data:
            slot.start_at = self.parse_datetime(
                data["start_at"],
                "start_at",
            )
        if "end_at" in data:
            slot.end_at = self.parse_datetime(
                data["end_at"],
                "end_at",
            )

        slot.updated_at = self.now()
        return self.repository.save_slot(slot)

    @staticmethod
    def parse_datetime(value, field_name):
        if not value:
            raise InterviewValidationError(
                f"Le champ {field_name} est requis"
            )

        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except (AttributeError, ValueError) as error:
            raise InterviewValidationError(
                f"Le champ {field_name} a un format invalide"
            ) from error

    @staticmethod
    def _required_text(data, field):
        value = data.get(field)
        if not value:
            raise InterviewValidationError(
                "Les champs name et formation sont requis"
            )
        return value.strip()
