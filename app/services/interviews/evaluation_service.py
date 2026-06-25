"""Interview candidate planning and evaluation workflows."""

from datetime import datetime

from mongoengine.errors import NotUniqueError

from app.models.candidature import Candidature
from app.models.interview import (
    InterviewCampaign,
    InterviewEvaluation,
    InterviewSlot,
)
from app.models.test_result import TestResult
from app.services.interviews.exceptions import (
    InterviewConflictError,
    InterviewForbiddenError,
    InterviewNotFoundError,
    InterviewValidationError,
)
from app.services.interviews.query_service import InterviewQueryService
from app.services.interviews.scorecard_service import (
    is_evaluation_complete,
    is_scorecard_ready,
    sanitize_review,
)


class InterviewEvaluationService:
    REVIEW_FIELD_BY_ROLE = {
        "filter": "filter_review",
        "validator": "validator_review",
        "motivation": "motivation_review",
    }
    ASSIGNED_FIELD_BY_ROLE = {
        "filter": "assigned_filter_ids",
        "validator": "assigned_validator_ids",
        "motivation": "assigned_motivation_ids",
    }

    def __init__(self, query_service=None, now=None):
        self.query_service = query_service or InterviewQueryService()
        self.now = now or datetime.utcnow

    def seed(self, data):
        campaign_id = data.get("campaign_id")
        formation = data.get("formation")
        if not campaign_id or not formation:
            raise InterviewValidationError(
                "Les champs campaign_id et formation sont requis"
            )
        campaign = InterviewCampaign.objects(
            id=campaign_id,
            formation=formation,
        ).first()
        if not campaign:
            raise InterviewNotFoundError(
                "Campagne non trouvée pour ce référentiel"
            )
        if not is_scorecard_ready(campaign.scorecard_config):
            raise InterviewValidationError(
                "Ajoutez au moins un critère métier avant de planifier "
                "les candidats."
            )

        slots = self._staffed_slots(campaign_id, formation)
        if not slots:
            raise InterviewValidationError(
                "Aucun créneau complet. Affectez d'abord les trois "
                "rôles jury à un créneau."
            )
        candidates = list(
            Candidature.objects(
                desired_training=formation,
            ).order_by("created_at")
        )
        admitted_emails = self._admitted_emails(candidates)
        evaluations = {
            item.candidature_id: item
            for item in InterviewEvaluation.objects(
                campaign_id=campaign_id
            )
        }
        occupancy = self._slot_occupancy(slots, evaluations.values())
        counts = {
            "created": 0,
            "planned": 0,
            "already_planned": 0,
            "no_capacity": 0,
            "not_admitted": 0,
        }

        for candidate in candidates:
            if (
                self.query_service.normalize_email(candidate.email)
                not in admitted_emails
            ):
                counts["not_admitted"] += 1
                continue
            self._accept_pending_candidate(candidate)
            self._plan_candidate(
                campaign_id,
                candidate,
                slots,
                evaluations,
                occupancy,
                counts,
            )
        counts["message"] = (
            f"{counts['planned']} candidat(s) planifié(s), "
            f"{counts['already_planned']} déjà planifié(s), "
            f"{counts['no_capacity']} sans place disponible"
        )
        return counts

    def update(self, evaluation_id, data, current_admin):
        evaluation = InterviewEvaluation.objects(
            id=evaluation_id
        ).first()
        if not evaluation:
            raise InterviewNotFoundError("Évaluation non trouvée")
        campaign = InterviewCampaign.objects(
            id=evaluation.campaign_id
        ).first()
        scorecard = campaign.scorecard_config if campaign else {}
        sections = (scorecard or {}).get("sections") or {}

        if self.query_service._is_interview_member(current_admin):
            self._update_member_review(
                evaluation,
                data,
                current_admin,
                sections,
            )
        else:
            for field in ("final_status", "is_locked"):
                if field in data:
                    setattr(evaluation, field, data[field])

        evaluation.is_complete = is_evaluation_complete(
            evaluation,
            scorecard,
        )
        if (
            evaluation.slot_id
            and evaluation.interview_progress_status == "a_planifier"
        ):
            evaluation.interview_progress_status = "planifie"
        if (
            evaluation.interview_progress_status != "absent"
            and evaluation.is_complete
        ):
            evaluation.interview_progress_status = "passe"
        evaluation.updated_at = self.now()
        evaluation.save()
        return evaluation

    def _update_member_review(
        self,
        evaluation,
        data,
        current_admin,
        sections,
    ):
        profile_data = current_admin.profile_data or {}
        role = profile_data.get("interview_role")
        review_field = self.REVIEW_FIELD_BY_ROLE.get(role)
        assigned_field = self.ASSIGNED_FIELD_BY_ROLE.get(role)
        if not evaluation.slot_id:
            raise InterviewForbiddenError(
                "Cette fiche ne vous est pas affectée"
            )
        slot = InterviewSlot.objects(id=evaluation.slot_id).first()
        assigned_ids = (
            getattr(slot, assigned_field, [])
            if slot and assigned_field
            else []
        )
        if (
            not review_field
            or str(current_admin.id) not in (assigned_ids or [])
        ):
            raise InterviewForbiddenError(
                "Cette fiche ne vous est pas affectée"
            )
        try:
            review = sanitize_review(
                data.get(review_field) or {},
                sections.get(role) or {},
            )
        except (TypeError, ValueError) as error:
            raise InterviewValidationError(str(error)) from error
        setattr(evaluation, review_field, review)

    @staticmethod
    def _staffed_slots(campaign_id, formation):
        slots = InterviewSlot.objects(
            campaign_id=campaign_id,
            formation=formation,
            status__in=["scheduled", "in_progress"],
        ).order_by("start_at")
        return [
            slot
            for slot in slots
            if (slot.assigned_filter_ids or slot.assigned_jury_ids)
            and slot.assigned_validator_ids
            and slot.assigned_motivation_ids
        ]

    def _admitted_emails(self, candidates):
        emails = [item.email for item in candidates if item.email]
        if not emails:
            return set()
        results = TestResult.objects(
            candidate__email__in=emails,
            status="admis",
        ).only("candidate")
        return {
            self.query_service.normalize_email(result.candidate.email)
            for result in results
            if result.candidate and result.candidate.email
        }

    @staticmethod
    def _slot_occupancy(slots, evaluations):
        occupancy = {str(slot.id): 0 for slot in slots}
        for evaluation in evaluations:
            if evaluation.slot_id in occupancy:
                occupancy[evaluation.slot_id] += 1
        return occupancy

    @staticmethod
    def _available_slot(slots, occupancy):
        for slot in slots:
            slot_id = str(slot.id)
            if occupancy[slot_id] < max(slot.capacity or 0, 0):
                return slot
        return None

    @staticmethod
    def _accept_pending_candidate(candidate):
        if candidate.status == "pending":
            candidate.status = "accepted"
            candidate.save()

    def _plan_candidate(
        self,
        campaign_id,
        candidate,
        slots,
        evaluations,
        occupancy,
        counts,
    ):
        candidate_id = str(candidate.id)
        evaluation = evaluations.get(candidate_id)
        if evaluation and evaluation.slot_id:
            counts["already_planned"] += 1
            return
        slot = self._available_slot(slots, occupancy)
        if not slot:
            counts["no_capacity"] += 1
            if not evaluation:
                evaluation = self._new_evaluation(
                    campaign_id,
                    candidate,
                )
                evaluations[candidate_id] = evaluation
                counts["created"] += 1
            return
        if not evaluation:
            evaluation = InterviewEvaluation(
                campaign_id=campaign_id,
                candidature_id=candidate_id,
                final_status="en_attente",
                is_complete=False,
            )
            counts["created"] += 1
        evaluation.candidate_snapshot = (
            self.query_service.build_candidate_snapshot(candidate)
        )
        evaluation.slot_id = str(slot.id)
        evaluation.interview_progress_status = "planifie"
        evaluation.updated_at = self.now()
        try:
            evaluation.save()
        except NotUniqueError as error:
            raise InterviewConflictError(
                "Ce candidat est déjà rattaché à cette campagne"
            ) from error
        evaluations[candidate_id] = evaluation
        occupancy[str(slot.id)] += 1
        counts["planned"] += 1

    def _new_evaluation(self, campaign_id, candidate):
        evaluation = InterviewEvaluation(
            campaign_id=campaign_id,
            candidature_id=str(candidate.id),
            candidate_snapshot=(
                self.query_service.build_candidate_snapshot(candidate)
            ),
            interview_progress_status="a_planifier",
            final_status="en_attente",
            is_complete=False,
        )
        evaluation.save()
        return evaluation
