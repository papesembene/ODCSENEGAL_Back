"""Campaign and slot use cases for the interview module."""

from datetime import datetime
import secrets

from mongoengine.connection import ConnectionFailure

from app.models.interview import InterviewSlot
from app.models.user import User
from app.repositories.interview_repository import InterviewRepository
from app.services.interviews.availability_email_service import (
    InterviewAvailabilityEmailService,
)
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

    def __init__(self, repository=None, now=None, availability_email_service=None):
        self.repository = repository or InterviewRepository()
        self.now = now or datetime.utcnow
        self.availability_email_service = (
            availability_email_service or InterviewAvailabilityEmailService()
        )

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

    def update_campaign(self, campaign_id, data, current_admin=None):
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

        if "filter_questions" in data:
            if not self._can_manage_filter_questions(campaign, current_admin):
                raise InterviewValidationError(
                    "Seuls les coachs affectés à ce référentiel peuvent "
                    "modifier les questions d'entretien."
                )
            campaign.filter_questions = self._sanitize_filter_questions(
                data["filter_questions"],
            )

        campaign.updated_at = self.now()
        return self.repository.save_campaign(campaign)

    def _can_manage_filter_questions(self, campaign, current_admin):
        if not current_admin:
            return False
        profile_data = current_admin.profile_data or {}
        if profile_data.get("admin_scope") != "interview_member":
            return False
        return bool(
            InterviewSlot.objects(
                campaign_id=str(campaign.id),
                formation=campaign.formation,
                assigned_validator_ids=str(current_admin.id),
            )
            .only("id")
            .first()
        )

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
        assigned_filter_ids = self._assignment_ids_for_role(
            data.get("assigned_filter_ids", data.get("assigned_jury_ids", [])),
            "filter",
        )
        assigned_validator_ids = self._assignment_ids_for_role(
            data.get("assigned_validator_ids", []),
            "validator",
        )
        assigned_motivation_ids = self._assignment_ids_for_role(
            data.get("assigned_motivation_ids", []),
            "motivation",
        )
        assignments = self._build_assignments({
            "filter": assigned_filter_ids,
            "validator": assigned_validator_ids,
            "motivation": assigned_motivation_ids,
        })
        slot = self.repository.create_slot(
            campaign_id=data["campaign_id"],
            label=data["label"].strip(),
            formation=data["formation"].strip(),
            start_at=start_at,
            end_at=end_at,
            capacity=int(data.get("capacity", 10) or 10),
            assignments=assignments,
            assigned_filter_ids=assigned_filter_ids,
            assigned_jury_ids=assigned_filter_ids,
            assigned_validator_ids=assigned_validator_ids,
            assigned_motivation_ids=assigned_motivation_ids,
            status=data.get("status", "scheduled"),
        )
        slot.updated_at = self.now()
        return self.repository.save_slot(slot)

    def update_slot(self, slot_id, data):
        slot = self.repository.get_slot(slot_id)
        if not slot:
            raise InterviewNotFoundError("Créneau non trouvé")
        previous_assignments = self._slot_user_roles(slot)

        for field in self.SLOT_UPDATE_FIELDS:
            if field in data:
                setattr(slot, field, data[field])

        if "assigned_filter_ids" in data or "assigned_jury_ids" in data:
            slot.assigned_filter_ids = self._assignment_ids_for_role(
                data.get(
                    "assigned_filter_ids",
                    data.get("assigned_jury_ids", []),
                ),
                "filter",
            )
            slot.assigned_jury_ids = slot.assigned_filter_ids
        if "assigned_validator_ids" in data:
            slot.assigned_validator_ids = self._assignment_ids_for_role(
                data["assigned_validator_ids"],
                "validator",
            )
        if "assigned_motivation_ids" in data:
            slot.assigned_motivation_ids = self._assignment_ids_for_role(
                data["assigned_motivation_ids"],
                "motivation",
            )
        if any(
            field in data
            for field in (
                "assigned_filter_ids",
                "assigned_jury_ids",
                "assigned_validator_ids",
                "assigned_motivation_ids",
            )
        ):
            slot.assignments = self._build_assignments({
                "filter": slot.assigned_filter_ids,
                "validator": slot.assigned_validator_ids,
                "motivation": slot.assigned_motivation_ids,
            })

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
        saved_slot = self.repository.save_slot(slot)
        if any(
            field in data
            for field in (
                "assigned_filter_ids",
                "assigned_jury_ids",
                "assigned_validator_ids",
                "assigned_motivation_ids",
            )
        ):
            self._notify_new_jury_assignments(
                saved_slot,
                previous_assignments,
            )
        return saved_slot

    def confirm_jury_availability(self, token, response):
        if response not in {"available", "unavailable"}:
            raise InterviewValidationError("Réponse de disponibilité invalide")

        slot = self.repository.get_slot_by_availability_token(token)
        if not slot:
            raise InterviewNotFoundError("Lien de disponibilité invalide")

        responses = dict(slot.availability_responses or {})
        matched_user_id = None
        for user_id, item in responses.items():
            if item.get("token") == token:
                matched_user_id = user_id
                break

        if not matched_user_id:
            raise InterviewNotFoundError("Lien de disponibilité invalide")

        responses[matched_user_id] = {
            **responses[matched_user_id],
            "status": response,
            "responded_at": self.now().isoformat(),
        }
        slot.availability_responses = responses
        slot.updated_at = self.now()
        self.repository.save_slot(slot)
        return {
            "slot": slot.to_dict(),
            "status": response,
        }

    @staticmethod
    def _assignment_ids_for_role(user_ids, role):
        if not user_ids:
            return []

        normalized_ids = [str(user_id) for user_id in user_ids if user_id]
        if not normalized_ids:
            return []

        try:
            users = User.objects(
                id__in=normalized_ids,
                is_admin=True,
                is_active=True,
            ).only("id", "profile_data")
        except ConnectionFailure:
            return normalized_ids

        allowed_ids = {
            str(user.id)
            for user in users
            if (user.profile_data or {}).get("admin_scope")
            == "interview_member"
        }
        return [user_id for user_id in normalized_ids if user_id in allowed_ids]

    @staticmethod
    def _slot_user_roles(slot):
        assignments = slot.assignments or {}
        if assignments:
            return {
                str(user_id): list(roles or [])
                for user_id, roles in assignments.items()
            }

        roles_by_user = {}
        role_sources = {
            "filter": slot.assigned_filter_ids or slot.assigned_jury_ids or [],
            "validator": slot.assigned_validator_ids or [],
            "motivation": slot.assigned_motivation_ids or [],
        }
        for role, user_ids in role_sources.items():
            for user_id in user_ids:
                roles_by_user.setdefault(str(user_id), [])
                if role not in roles_by_user[str(user_id)]:
                    roles_by_user[str(user_id)].append(role)
        return roles_by_user

    def _notify_new_jury_assignments(self, slot, previous_assignments):
        current_assignments = self._slot_user_roles(slot)
        previous_user_ids = set(previous_assignments.keys())
        new_user_ids = [
            user_id
            for user_id in current_assignments.keys()
            if user_id not in previous_user_ids
        ]
        if not new_user_ids:
            return

        try:
            users = {
                str(user.id): user
                for user in User.objects(id__in=new_user_ids, is_active=True)
            }
        except ConnectionFailure:
            return
        responses = dict(slot.availability_responses or {})
        for user_id in new_user_ids:
            user = users.get(user_id)
            if not user or not getattr(user, "email", None):
                continue

            token = responses.get(user_id, {}).get("token") or secrets.token_urlsafe(24)
            roles = current_assignments.get(user_id, [])
            sent = self.availability_email_service.send_availability_request(
                jury=user,
                slot=slot,
                roles=roles,
                token=token,
            )
            responses[user_id] = {
                "status": "notified",
                "roles": roles,
                "token": token,
                "notified_at": self.now().isoformat(),
                "email_sent": bool(sent),
            }

        slot.availability_responses = responses
        self.repository.save_slot(slot)

    @staticmethod
    def _sanitize_filter_questions(questions):
        if not isinstance(questions, list):
            raise InterviewValidationError(
                "Les questions destinées aux filtreurs sont invalides"
            )

        sanitized_questions = []
        for index, item in enumerate(questions[:50], start=1):
            if not isinstance(item, dict):
                continue

            question = (item.get("question") or "").strip()
            expected_answer = (item.get("expected_answer") or "").strip()
            if not question:
                continue

            sanitized_questions.append({
                "id": (item.get("id") or f"question_{index}").strip(),
                "question": question[:1000],
                "expected_answer": expected_answer[:1500],
            })

        return sanitized_questions

    @staticmethod
    def _build_assignments(role_to_user_ids):
        assignments = {}
        for role, user_ids in role_to_user_ids.items():
            for user_id in user_ids or []:
                assignments.setdefault(str(user_id), [])
                if role not in assignments[str(user_id)]:
                    assignments[str(user_id)].append(role)
        return assignments

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
