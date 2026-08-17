"""Read models and query helpers for interview endpoints."""

import csv
import io
import re
from datetime import UTC, datetime

from bson import ObjectId

from app.models.candidature import Candidature
from app.models.interview import (
    InterviewCampaign,
    InterviewEvaluation,
    InterviewSlot,
)
from app.models.test_result import TestResult
from app.models.test import Test
from app.models.test_violation import TestViolation
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

    def member_capabilities(self, current_admin):
        if not self._is_interview_member(current_admin):
            return {
                "is_interview_member": False,
                "can_manage_questions": True,
                "validator_campaign_ids": [],
            }

        admin_id = str(current_admin.id)
        validator_slots = InterviewSlot.objects(
            assigned_validator_ids=admin_id,
        ).only("campaign_id")
        validator_campaign_ids = sorted(
            {
                slot.campaign_id
                for slot in validator_slots
                if slot.campaign_id
            }
        )
        return {
            "is_interview_member": True,
            "can_manage_questions": bool(validator_campaign_ids),
            "validator_campaign_ids": validator_campaign_ids,
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

    def export_evaluations_csv(self, request_args, current_admin=None):
        query = self.build_evaluation_query(
            request_args,
            current_admin=current_admin,
        )
        rows = self.serialize_evaluations(query)

        output = io.StringIO()
        writer = csv.writer(output, delimiter=";")
        writer.writerow([
            "Nom",
            "Email",
            "Téléphone",
            "Référentiel",
            "Campagne",
            "Créneau",
            "Score test",
            "Infractions",
            "Avis filtreur",
            "Avis coach",
            "Badges coach",
            "Avis motivation",
            "Statut entretien",
            "Décision finale",
            "Fiche complète",
        ])

        for row in rows:
            candidate = row.get("candidate_snapshot") or {}
            writer.writerow([
                self._candidate_name(candidate),
                candidate.get("email", ""),
                candidate.get("phone", ""),
                candidate.get("desired_training", ""),
                row.get("campaign_name", ""),
                self._slot_label(row),
                row.get("test_score", ""),
                self._violation_count(row),
                self._review_summary(row, "filter"),
                self._review_summary(row, "validator"),
                self._coach_badges(row),
                self._review_summary(row, "motivation"),
                self._progress_label(row.get("interview_progress_status")),
                self._final_status_label(row.get("final_status")),
                "Oui" if row.get("is_complete") else "Non",
            ])

        filename = "entretiens"
        formation = (request_args.get("formation") or "").strip()
        if formation and formation != "all":
            filename = f"{filename}-{formation}"
        filename = f"{filename}-{datetime.now(UTC).strftime('%Y%m%d')}.csv"
        return "\ufeff" + output.getvalue(), filename

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
        slot_ids = {
            evaluation.slot_id
            for evaluation in evaluation_list
            if evaluation.slot_id
        }
        campaigns_by_id = {
            str(campaign.id): campaign
            for campaign in (
                InterviewCampaign.objects(id__in=list(campaign_ids))
                if campaign_ids
                else []
            )
        }
        slots_by_id = {
            str(slot.id): slot
            for slot in (
                InterviewSlot.objects(id__in=list(slot_ids))
                if slot_ids
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
        test_ids = {
            result.testId
            for result in test_results_by_email.values()
            if result.testId
        }
        mongo_test_ids = [
            test_id for test_id in test_ids if ObjectId.is_valid(test_id)
        ]
        tests_by_id = {
            str(test.id): test
            for test in (
                Test.objects(id__in=mongo_test_ids)
                if mongo_test_ids
                else []
            )
        }
        violations = (
            TestViolation.objects(
                testId__in=list(test_ids),
                candidateEmail__in=candidate_emails,
            )
            if test_ids and candidate_emails
            else []
        )
        violations_by_key = {
            (
                str(violation.testId),
                self.normalize_email(violation.candidateEmail),
            ): violation
            for violation in violations
        }

        payloads = []
        for evaluation in evaluation_list:
            payload = evaluation.to_dict()
            campaign = campaigns_by_id.get(evaluation.campaign_id)
            slot = slots_by_id.get(evaluation.slot_id)
            payload["campaign_name"] = campaign.name if campaign else ""
            payload["campaign_scorecard_config"] = (
                campaign.scorecard_config if campaign else {}
            )
            payload["slot_label"] = slot.label if slot else ""
            payload["slot_start_at"] = (
                slot.start_at.isoformat() if slot and slot.start_at else None
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
            payload["test_details"] = self.serialize_test_details(
                linked_result,
                tests_by_id,
                violations_by_key,
            )
            payloads.append(payload)

        return payloads

    @staticmethod
    def _candidate_name(candidate):
        return " ".join(
            item for item in [
                candidate.get("first_name"),
                candidate.get("last_name"),
            ] if item
        ) or candidate.get("email", "")

    @staticmethod
    def _slot_label(row):
        label = row.get("slot_label") or ""
        start_at = row.get("slot_start_at") or ""
        if label and start_at:
            return f"{label} ({start_at})"
        return label or start_at

    @staticmethod
    def _section_review(row, section_key):
        legacy_fields = {
            "filter": "filter_review",
            "validator": "validator_review",
            "motivation": "motivation_review",
        }
        return (
            (row.get("section_reviews") or {}).get(section_key)
            or row.get(legacy_fields.get(section_key), {})
            or {}
        )

    def _review_summary(self, row, section_key):
        review = self._section_review(row, section_key)
        decision = (
            review.get("decision")
            or review.get("verdict")
            or review.get("status")
            or ""
        )
        comment = review.get("comment") or review.get("notes") or ""
        if decision and comment:
            return f"{decision} - {comment}"
        return decision or comment

    def _coach_badges(self, row):
        review = self._section_review(row, "validator")
        badges = [
            ("coach_pick", "Coup de coeur"),
            ("strong_potential", "Potentiel fort"),
            ("cohort_balance", "Équilibre cohorte"),
            ("social_context", "Contexte social"),
        ]
        return ", ".join(label for key, label in badges if review.get(key))

    @staticmethod
    def _violation_count(row):
        violations = ((row.get("test_details") or {}).get("violations") or {})
        return violations.get("totalViolations", 0)

    @staticmethod
    def _progress_label(value):
        return {
            "a_planifier": "À planifier",
            "planifie": "Planifié",
            "passe": "Passé",
            "absent": "Absent",
        }.get(value, value or "")

    @staticmethod
    def _final_status_label(value):
        return {
            "en_attente": "En attente",
            "retenu": "Retenu",
            "liste_attente": "Liste d'attente",
            "rejete": "Rejeté",
        }.get(value, value or "")

    def serialize_test_details(
        self,
        test_result,
        tests_by_id,
        violations_by_key,
    ):
        if not test_result:
            return None

        test = tests_by_id.get(str(test_result.testId))
        candidate_email = self.normalize_email(
            getattr(test_result.candidate, "email", None),
        )
        violation = violations_by_key.get((str(test_result.testId), candidate_email))
        questions = []
        for index, question in enumerate(test.questions if test else []):
            answer = (test_result.answers or {}).get(str(index))
            if answer is None:
                answer = (test_result.answers or {}).get(index)
            questions.append({
                "index": index + 1,
                "question": question.question,
                "type": question.type,
                "options": question.options or [],
                "answer": answer,
                "answerLabel": self.format_answer_label(question, answer),
                "correctAnswer": question.correctAnswer,
                "correctAnswers": question.correctAnswers or [],
                "correctAnswerLabel": self.format_correct_answer_label(question),
                "isCorrect": self.is_correct_answer(question, answer, test_result, index),
                "score": question.score,
                "manualGrade": (test_result.manualGrades or {}).get(str(index)),
            })

        return {
            "testId": test_result.testId,
            "testTitle": test_result.testTitle,
            "score": test_result.score,
            "status": test_result.status,
            "completedAt": test_result.completedAt.isoformat() if test_result.completedAt else None,
            "questions": questions,
            "violations": violation.to_dict() if violation else None,
        }

    @staticmethod
    def format_answer_label(question, answer):
        if question.type == "qcm_simple":
            try:
                index = int(answer)
                return question.options[index] if question.options and 0 <= index < len(question.options) else str(answer)
            except (TypeError, ValueError):
                return str(answer or "")
        if question.type == "qcm_multiple":
            labels = []
            for item in answer or []:
                try:
                    index = int(item)
                    labels.append(question.options[index] if question.options and 0 <= index < len(question.options) else str(item))
                except (TypeError, ValueError):
                    labels.append(str(item))
            return ", ".join(labels)
        return str(answer or "")

    @staticmethod
    def format_correct_answer_label(question):
        if question.type == "qcm_simple":
            index = question.correctAnswer
            return question.options[index] if question.options and index is not None and 0 <= index < len(question.options) else ""
        if question.type == "qcm_multiple":
            labels = []
            for index in question.correctAnswers or []:
                if question.options and 0 <= index < len(question.options):
                    labels.append(question.options[index])
            return ", ".join(labels)
        return ""

    @staticmethod
    def is_correct_answer(question, answer, test_result, index):
        if question.type == "qcm_simple":
            try:
                return int(answer) == int(question.correctAnswer)
            except (TypeError, ValueError):
                return False

        if question.type == "qcm_multiple":
            try:
                selected = sorted(int(item) for item in (answer or []))
                expected = sorted(int(item) for item in (question.correctAnswers or []))
                return selected == expected
            except (TypeError, ValueError):
                return False

        manual_grade = (test_result.manualGrades or {}).get(str(index))
        try:
            return float(manual_grade) > 0
        except (TypeError, ValueError):
            return False

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
