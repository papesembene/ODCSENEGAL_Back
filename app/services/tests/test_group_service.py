"""Test group planning, assignment and invitation use cases."""

from datetime import datetime

from mongoengine.errors import ValidationError

from app.models.candidature import Candidature
from app.models.test import Test
from app.models.test_group import TestGroup
from app.services.test_email_service import TestEmailService


class TestGroupServiceError(Exception):
    def __init__(self, message, status_code=400):
        super().__init__(message)
        self.status_code = status_code


class TestGroupService:
    FORMATIONS = (
        "Dev Web",
        "Data",
        "Hackeuse",
        "AWS",
        "Référent Digital",
        "Cyber security",
        "Intelligence Artificielle",
    )
    UPDATE_FIELDS = (
        "name",
        "formation",
        "duration",
        "candidate_ids",
        "location",
        "instructions",
        "status",
    )

    @staticmethod
    def list_groups(formation=None, status=None):
        filters = {}
        if formation and formation != "all":
            filters["formation"] = formation
        if status and status != "all":
            filters["status"] = status
        groups = TestGroup.objects(**filters).order_by("-created_at")
        return [
            TestGroupService._serialize_group(group, compact=True)
            for group in groups
        ]

    @staticmethod
    def get_group(group_id):
        group = TestGroup.objects(id=group_id).first()
        if not group:
            raise TestGroupServiceError("Groupe non trouvé", 404)
        return group

    @staticmethod
    def list_available_candidates(
        formation,
        search="",
        page=1,
        per_page=100,
    ):
        if not formation:
            raise TestGroupServiceError("Le référentiel est requis")

        assigned_ids = TestGroupService._assigned_candidate_ids(formation)
        query = Candidature.objects(desired_training=formation)
        if assigned_ids:
            query = query.filter(id__nin=list(assigned_ids))
        if search:
            regex = {"$regex": search, "$options": "i"}
            query = query.filter(__raw__={
                "$or": [
                    {"first_name": regex},
                    {"last_name": regex},
                    {"email": regex},
                    {"phone": regex},
                ],
            })

        total = query.count()
        offset = max(page - 1, 0) * per_page
        candidates = query.order_by("-created_at").skip(offset).limit(per_page)

        return {
            "data": [candidate.to_dict() for candidate in candidates],
            "total": total,
            "page": page,
            "per_page": per_page,
            "assigned_count": len(assigned_ids),
        }

    def create_group(self, data):
        data = data or {}
        for field in ("name", "formation", "test_date", "candidate_ids"):
            if not data.get(field):
                raise TestGroupServiceError(
                    f"Le champ {field} est requis"
                )
        data["candidate_ids"] = self._unique_candidate_ids(
            data["candidate_ids"],
        )
        self._ensure_candidates_exist(data["candidate_ids"])
        self._ensure_candidates_available(
            candidate_ids=data["candidate_ids"],
            formation=data["formation"],
        )
        try:
            group = TestGroup(
                name=data["name"],
                formation=data["formation"],
                test_id=data.get("test_id"),
                test_date=self._parse_date(data["test_date"]),
                duration=data.get("duration", 60),
                candidate_ids=data["candidate_ids"],
                location=data.get("location", ""),
                instructions=data.get("instructions", ""),
                status="pending",
                created_by=data.get("created_by", "admin"),
            )
            group.save()
            self._assign_test(group, data.get("test_id"))
            return group
        except ValidationError as error:
            raise TestGroupServiceError(
                f"Erreur de validation : {error}"
            ) from error

    def update_group(self, group_id, data):
        group = self.get_group(group_id)
        data = data or {}
        if "candidate_ids" in data:
            data["candidate_ids"] = self._unique_candidate_ids(
                data["candidate_ids"],
            )
            self._ensure_candidates_exist(data["candidate_ids"])
            self._ensure_candidates_available(
                candidate_ids=data["candidate_ids"],
                formation=data.get("formation", group.formation),
                current_group_id=group.id,
            )
        if "test_id" in data:
            self._reassign_test(group, data["test_id"])
        for field in self.UPDATE_FIELDS:
            if field in data:
                setattr(group, field, data[field])
        if "test_date" in data:
            group.test_date = self._parse_date(data["test_date"])
        group.updated_at = datetime.utcnow()
        try:
            group.save()
        except ValidationError as error:
            raise TestGroupServiceError(
                f"Erreur de validation : {error}"
            ) from error
        return group

    def delete_group(self, group_id):
        self.get_group(group_id).delete()

    def send_invitations(
        self,
        group_id,
        frontend_url,
        simulate=False,
    ):
        group = self.get_group(group_id)
        test = (
            Test.objects(id=group.test_id).first()
            if group.test_id
            else None
        )
        candidates = list(
            Candidature.objects(id__in=group.candidate_ids),
        )
        if not candidates:
            raise TestGroupServiceError(
                "Aucun candidat trouvé dans ce groupe"
            )
        email_service = TestEmailService()
        if simulate and not email_service.sendgrid_api_key:
            self._mark_scheduled(group)
            return {
                "status_code": 200,
                "payload": {
                    "success": True,
                    "message": (
                        "Invitations simulées localement pour "
                        f"{len(candidates)} candidat(s)"
                    ),
                    "data": {
                        "sent": len(candidates),
                        "failed": 0,
                        "simulated": True,
                        "timestamp": group.email_sent.isoformat(),
                    },
                },
            }
        result = email_service.send_bulk_invitations(
            candidates=candidates,
            test_title=test.title if test else "Test en ligne",
            test_date=group.test_date.strftime("%d/%m/%Y"),
            test_time=group.test_date.strftime("%H:%M"),
            test_duration=group.duration or 60,
            test_link=(
                f"{frontend_url}/test/{test.id}"
                if test
                else f"{frontend_url}/test"
            ),
        )
        return self._build_invitation_response(group, result)

    @staticmethod
    def get_statistics(formation=None):
        filters = (
            {"formation": formation}
            if formation and formation != "all"
            else {}
        )
        groups = TestGroup.objects(**filters)
        payload = TestGroupService._group_counts(groups)
        payload["formationStats"] = {}
        for item in TestGroupService.FORMATIONS:
            payload["formationStats"][item] = (
                TestGroupService._group_counts(
                    TestGroup.objects(formation=item),
                )
            )
        return payload

    @staticmethod
    def serialize_group(group, compact=False):
        return TestGroupService._serialize_group(group, compact)

    @staticmethod
    def _serialize_group(group, compact=False):
        payload = group.to_dict()
        candidates = (
            Candidature.objects(id__in=group.candidate_ids)
            if group.candidate_ids
            else []
        )
        payload["candidates"] = [
            (
                {
                    "id": str(candidate.id),
                    "first_name": candidate.first_name,
                    "last_name": candidate.last_name,
                    "email": candidate.email,
                    "phone": candidate.phone,
                }
                if compact
                else candidate.to_dict()
            )
            for candidate in candidates
        ]
        return payload

    @staticmethod
    def _parse_date(value):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except (AttributeError, ValueError) as error:
            raise TestGroupServiceError(
                "Format de date invalide"
            ) from error

    @staticmethod
    def _unique_candidate_ids(candidate_ids):
        return list(dict.fromkeys(str(candidate_id) for candidate_id in candidate_ids))

    @staticmethod
    def _assigned_candidate_ids(formation):
        assigned_ids = set()
        groups = TestGroup.objects(
            formation=formation,
            status__ne="cancelled",
        ).only("candidate_ids")

        for group in groups:
            assigned_ids.update(group.candidate_ids or [])

        return assigned_ids

    @staticmethod
    def _ensure_candidates_exist(candidate_ids):
        if Candidature.objects(id__in=candidate_ids).count() != len(candidate_ids):
            raise TestGroupServiceError(
                "Certains candidats n'existent pas"
            )

    @staticmethod
    def _ensure_candidates_available(
        candidate_ids,
        formation,
        current_group_id=None,
    ):
        candidate_id_set = set(candidate_ids)
        groups = TestGroup.objects(
            formation=formation,
            status__ne="cancelled",
            candidate_ids__in=candidate_ids,
        ).only("name", "candidate_ids")

        for group in groups:
            if current_group_id and str(group.id) == str(current_group_id):
                continue

            duplicated_ids = candidate_id_set.intersection(
                set(group.candidate_ids or []),
            )
            if duplicated_ids:
                raise TestGroupServiceError(
                    (
                        f"{len(duplicated_ids)} candidat(s) sont déjà "
                        f"affecté(s) au groupe {group.name}."
                    ),
                    409,
                )

    @staticmethod
    def _assign_test(group, test_id):
        if not test_id:
            return
        test = Test.objects(id=test_id).first()
        if test:
            test.candidatesGroup = str(group.id)
            test.save()

    def _reassign_test(self, group, new_test_id):
        old_test_id = group.test_id
        if old_test_id and old_test_id != new_test_id:
            old_test = Test.objects(id=old_test_id).first()
            if old_test and old_test.candidatesGroup == str(group.id):
                old_test.candidatesGroup = ""
                old_test.save()
        group.test_id = new_test_id
        self._assign_test(group, new_test_id)

    @staticmethod
    def _mark_scheduled(group):
        group.email_sent = datetime.utcnow()
        group.status = "scheduled"
        group.save()

    def _build_invitation_response(self, group, result):
        sent = result.get("sent", 0)
        failed = result.get("failed", 0)
        if result.get("success"):
            self._mark_scheduled(group)
            return {
                "status_code": 200,
                "payload": {
                    "success": True,
                    "message": (
                        "Invitations envoyées avec succès à "
                        f"{sent} candidat(s)"
                    ),
                    "data": {
                        "sent": sent,
                        "failed": failed,
                        "timestamp": group.email_sent.isoformat(),
                    },
                },
            }
        if sent > 0:
            self._mark_scheduled(group)
            return {
                "status_code": 207,
                "payload": {
                    "success": False,
                    "message": (
                        "Invitations partiellement envoyées : "
                        f"{sent} succès, {failed} échecs"
                    ),
                    "error": result.get("error"),
                    "data": {
                        "sent": sent,
                        "failed": failed,
                        "failed_emails": result.get(
                            "failed_emails",
                            [],
                        ),
                        "timestamp": group.email_sent.isoformat(),
                    },
                },
            }
        return {
            "status_code": 503,
            "payload": {
                "success": False,
                "error": (
                    result.get("error")
                    or "Aucune invitation n'a pu être envoyée"
                ),
                "data": {
                    "sent": sent,
                    "failed": failed,
                    "failed_emails": result.get(
                        "failed_emails",
                        [],
                    ),
                },
            },
        }

    @staticmethod
    def _group_counts(groups):
        total_candidates = sum(
            len(group.candidate_ids or [])
            for group in groups
        )
        return {
            "total": groups.count(),
            "pending": groups.filter(status="pending").count(),
            "scheduled": groups.filter(status="scheduled").count(),
            "completed": groups.filter(status="completed").count(),
            "cancelled": groups.filter(status="cancelled").count(),
            "total_candidates": total_candidates,
        }
