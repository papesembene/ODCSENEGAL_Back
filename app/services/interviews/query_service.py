"""Read models and query helpers for interview endpoints."""

import re

from app.models.candidature import Candidature
from app.models.interview import (
    InterviewCampaign,
    InterviewEvaluation,
    InterviewSlot,
)
from app.models.test_result import TestResult
from app.models.user import User


class InterviewQueryService:
    def bootstrap(self, formation=None, current_admin=None):
        campaigns = list(self.list_campaign_documents(formation))
        campaign_ids = [str(item.id) for item in campaigns]
        slots_query = InterviewSlot.objects.order_by("start_at")
        if formation:
            slots_query = slots_query.filter(formation=formation)
        if campaign_ids:
            slots_query = slots_query.filter(
                campaign_id__in=campaign_ids
            )
        if self._is_interview_member(current_admin):
            slots_query = self._filter_slots_for_admin(
                slots_query,
                current_admin,
            )
        slots = list(slots_query)
        if self._is_interview_member(current_admin):
            assigned_campaigns = {slot.campaign_id for slot in slots}
            campaigns = [
                item
                for item in campaigns
                if str(item.id) in assigned_campaigns
            ]
            admins = [current_admin]
        else:
            admins = User.objects(
                is_admin=True,
                is_active=True,
                admin_type__in=["competences", "super_admin"],
                profile_data__admin_scope="interview_member",
                profile_data__interview_role__in=[
                    "filter",
                    "validator",
                    "motivation",
                ],
            ).order_by("first_name", "last_name")
        occupancy = self._occupancy(slots)
        return {
            "campaigns": [
                self.serialize_campaign(item) for item in campaigns
            ],
            "slots": [item.to_dict() for item in slots],
            "admins": [
                self.serialize_admin_user(item) for item in admins
            ],
            "slot_occupancy": occupancy,
        }

    @staticmethod
    def list_campaign_documents(formation=None):
        query = InterviewCampaign.objects.order_by("-created_at")
        return query.filter(formation=formation) if formation else query

    def list_campaigns(self, formation=None):
        return [
            self.serialize_campaign(item)
            for item in self.list_campaign_documents(formation)
        ]

    @staticmethod
    def list_slots(campaign_id=None):
        query = InterviewSlot.objects.order_by("start_at")
        if campaign_id:
            query = query.filter(campaign_id=campaign_id)
        return [item.to_dict() for item in query]

    def evaluation_page(
        self,
        request_args,
        current_admin=None,
    ):
        page = self.get_positive_int(request_args.get("page"), 1)
        page_size = self.get_positive_int(
            request_args.get("pageSize"),
            25,
            maximum=100,
        )
        query = self.build_evaluation_query(
            request_args,
            current_admin=current_admin,
        )
        total = query.count()
        total_pages = max((total + page_size - 1) // page_size, 1)
        page = min(page, total_pages)
        rows = query.skip((page - 1) * page_size).limit(page_size)
        statuses = ("en_attente", "retenu", "liste_attente", "rejete")
        progress_values = ("a_planifier", "planifie", "passe", "absent")
        complete = query.filter(is_complete=True).count()
        return {
            "data": self.serialize_evaluations(rows),
            "pagination": {
                "page": page,
                "page_size": page_size,
                "total": total,
                "total_pages": total_pages,
            },
            "summary": {
                "status": {
                    value: query.filter(final_status=value).count()
                    for value in statuses
                },
                "progress": {
                    value: query.filter(
                        interview_progress_status=value
                    ).count()
                    for value in progress_values
                },
                "complete": complete,
                "incomplete": max(total - complete, 0),
                "ready_for_decision": query.filter(
                    interview_progress_status="passe",
                    final_status="en_attente",
                    is_complete=True,
                ).count(),
            },
        }
    @staticmethod
    def build_candidate_snapshot(candidate):
        return {
            "id": str(candidate.id),
            "first_name": candidate.first_name,
            "last_name": candidate.last_name,
            "email": candidate.email,
            "phone": candidate.phone,
            "gender": candidate.gender,
            "desired_training": candidate.desired_training,
            "status": candidate.status,
        }

    @staticmethod
    def serialize_admin_user(user):
        return {
            "id": str(user.id),
            "email": user.email,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "admin_type": user.admin_type,
            "is_active": user.is_active,
            "profile_data": user.profile_data or {},
        }

    @staticmethod
    def serialize_campaign(campaign):
        payload = campaign.to_dict()
        payload["evaluation_count"] = InterviewEvaluation.objects(
            campaign_id=str(campaign.id),
        ).count()
        return payload

    @staticmethod
    def normalize_email(value):
        return (value or "").strip().lower()

    @staticmethod
    def get_positive_int(value, default, maximum=None):
        try:
            parsed_value = int(value)
        except (TypeError, ValueError):
            return default

        parsed_value = max(parsed_value, 1)
        return min(parsed_value, maximum) if maximum else parsed_value

    def build_evaluation_query(self, request_args, current_admin=None):
        campaign_id = request_args.get("campaignId")
        formation = request_args.get("formation")
        status = request_args.get("status")
        progress = request_args.get("progress")
        completion = request_args.get("completion")
        search = (request_args.get("search") or "").strip()

        query = InterviewEvaluation.objects.order_by("-updated_at")
        if campaign_id:
            query = query.filter(campaign_id=campaign_id)
        if status and status != "all":
            query = query.filter(final_status=status)
        if progress and progress != "all":
            query = query.filter(interview_progress_status=progress)

        raw_conditions = []
        if formation and formation != "all":
            raw_conditions.append({
                "candidate_snapshot.desired_training": formation,
            })
        if search:
            search_regex = {
                "$regex": re.escape(search),
                "$options": "i",
            }
            raw_conditions.append({
                "$or": [
                    {"candidate_snapshot.first_name": search_regex},
                    {"candidate_snapshot.last_name": search_regex},
                    {"candidate_snapshot.email": search_regex},
                    {"candidate_snapshot.phone": search_regex},
                ],
            })

        if completion == "complete":
            query = query.filter(is_complete=True)
        elif completion == "incomplete":
            query = query.filter(is_complete=False)

        if self._is_interview_member(current_admin):
            assigned_slot_ids = self._get_assigned_slot_ids(current_admin)
            query = query.filter(
                slot_id__in=assigned_slot_ids or ["__none__"],
            )

        if raw_conditions:
            query = query.filter(__raw__={"$and": raw_conditions})

        return query

    def serialize_evaluations(self, evaluations):
        evaluation_list = list(evaluations)
        candidate_ids = [
            evaluation.candidature_id
            for evaluation in evaluation_list
        ]
        campaign_ids = {
            evaluation.campaign_id
            for evaluation in evaluation_list
            if evaluation.campaign_id
        }
        campaigns_by_id = {
            str(campaign.id): campaign
            for campaign in (
                InterviewCampaign.objects(id__in=list(campaign_ids))
                if campaign_ids
                else []
            )
        }
        candidates = (
            Candidature.objects(id__in=candidate_ids)
            if candidate_ids
            else []
        )
        candidates_by_id = {
            str(candidate.id): candidate
            for candidate in candidates
        }
        candidate_emails = [
            candidate.email
            for candidate in candidates
            if candidate.email
        ]
        test_results = (
            TestResult.objects(
                candidate__email__in=candidate_emails,
            ).order_by("-completedAt")
            if candidate_emails
            else []
        )
        test_results_by_email = {}
        for result in test_results:
            email = self.normalize_email(
                getattr(result.candidate, "email", None),
            )
            if email and email not in test_results_by_email:
                test_results_by_email[email] = result

        payloads = []
        for evaluation in evaluation_list:
            payload = evaluation.to_dict()
            campaign = campaigns_by_id.get(evaluation.campaign_id)
            payload["campaign_scorecard_config"] = (
                campaign.scorecard_config if campaign else {}
            )
            candidate = candidates_by_id.get(evaluation.candidature_id)
            if not payload.get("candidate_snapshot") and candidate:
                payload["candidate_snapshot"] = (
                    self.build_candidate_snapshot(candidate)
                )
            linked_result = test_results_by_email.get(
                self.normalize_email(
                    payload.get("candidate_snapshot", {}).get("email"),
                ),
            )
            payload["test_score"] = (
                linked_result.score if linked_result else None
            )
            payload["test_result_status"] = (
                linked_result.status if linked_result else None
            )
            payloads.append(payload)

        return payloads

    @staticmethod
    def _is_interview_member(current_admin):
        return bool(
            current_admin
            and current_admin.admin_type != "super_admin"
            and (current_admin.profile_data or {}).get("admin_scope")
            == "interview_member"
        )

    @staticmethod
    def _get_assigned_slot_ids(current_admin):
        admin_id = str(current_admin.id)
        assigned_slots = InterviewSlot.objects(
            __raw__={
                "$or": [
                    {"assigned_filter_ids": admin_id},
                    {"assigned_jury_ids": admin_id},
                    {"assigned_validator_ids": admin_id},
                    {"assigned_motivation_ids": admin_id},
                ],
            },
        ).only("id")
        return [str(slot.id) for slot in assigned_slots]

    @staticmethod
    def _filter_slots_for_admin(query, current_admin):
        admin_id = str(current_admin.id)
        return query.filter(
            __raw__={
                "$or": [
                    {"assigned_filter_ids": admin_id},
                    {"assigned_jury_ids": admin_id},
                    {"assigned_validator_ids": admin_id},
                    {"assigned_motivation_ids": admin_id},
                ]
            }
        )

    @staticmethod
    def _occupancy(slots):
        slot_ids = [str(slot.id) for slot in slots]
        if not slot_ids:
            return {}
        return {
            item["_id"]: item["count"]
            for item in InterviewEvaluation.objects(
                slot_id__in=slot_ids,
            ).aggregate(
                {"$match": {"slot_id": {"$nin": [None, ""]}}},
                {"$group": {"_id": "$slot_id", "count": {"$sum": 1}}},
            )
        }
