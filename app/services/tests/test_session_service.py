"""Candidate online-test session drafts."""

from datetime import datetime, timedelta
from bson import ObjectId

from mongoengine.errors import NotUniqueError, ValidationError

from app.models.candidature import Candidature
from app.models.test import Test
from app.models.test_group import TestGroup
from app.models.test_result import TestResult
from app.models.test_session import TestSession
from app.utils.search import text_search_filter


class TestSessionServiceError(Exception):
    def __init__(self, message, status_code=400):
        super().__init__(message)
        self.status_code = status_code


class TestSessionService:
    @staticmethod
    def get_draft(test_id, candidate_email):
        if not test_id or not candidate_email:
            raise TestSessionServiceError("Test et email requis", 400)

        return TestSession.objects(
            testId=str(test_id),
            candidateEmail=candidate_email.strip().lower(),
        ).first()

    def save_draft(self, test_id, data, access):
        data = data or {}
        candidate = access.get("candidate") or {}
        candidate_email = (candidate.get("email") or data.get("email") or "").strip().lower()
        candidate_phone = (data.get("phone") or "").strip()

        if not test_id or not candidate_email or not candidate_phone:
            raise TestSessionServiceError("Test, email et téléphone requis", 400)

        identity = {"testId": str(test_id), "candidateEmail": candidate_email}
        now = datetime.utcnow()
        try:
            # Create by identity only: terminal sessions must never match an upsert
            # predicate that would attempt to insert a second document.
            TestSession.objects(**identity).modify(
                upsert=True, new=True,
                set_on_insert__candidatePhone=candidate_phone,
                set_on_insert__startedAt=now,
                set_on_insert__status="in_progress",
            )
        except NotUniqueError:
            pass
        try:
            session = TestSession.objects(**identity, status="in_progress").modify(
                new=True,
                set__candidatePhone=candidate_phone,
                set__candidateName=(data.get("name") or "").strip(),
                set__answers=data.get("answers") or {},
                set__lastQuestion=self._safe_int(data.get("lastQuestion"), 0),
                set__remainingTime=self._safe_int(data.get("remainingTime"), 0),
                set__lastSeenAt=now,
            )
        except ValidationError as error:
            raise TestSessionServiceError(f"Brouillon invalide : {error}", 400) from error
        return session or self.get_draft(test_id, candidate_email)

    @staticmethod
    def mark_submitted(test_id, candidate_email, candidate=None):
        candidate = candidate or {}
        now = datetime.utcnow()
        query = TestSession.objects(
            testId=str(test_id),
            candidateEmail=(candidate_email or "").strip().lower(),
        )
        changes = {"set__status": "submitted", "set__submittedAt": now, "set__lastSeenAt": now}
        try:
            return query.modify(
                upsert=True, new=True, **changes,
                set_on_insert__candidatePhone=candidate.get("phone") or "",
                set_on_insert__candidateName=candidate.get("name") or "",
                set_on_insert__startedAt=now,
            )
        except NotUniqueError:
            return query.modify(new=True, **changes)

    def list_admin_sessions(self, filters=None):
        filters = filters or {}
        self.refresh_expired_sessions(filters.get("testId"))
        query = self._build_admin_query(filters)
        page = max(self._safe_int(filters.get("page"), 1), 1)
        per_page = min(max(self._safe_int(filters.get("per_page"), 20), 1), 100)

        sessions = list(
            query.order_by("-lastSeenAt")
            .skip((page - 1) * per_page)
            .limit(per_page)
        )
        tests_by_id = self._get_tests_by_id(sessions)
        updated_sessions = [
            self._sync_session_status(session, tests_by_id.get(session.testId))
            for session in sessions
        ]

        return {
            "data": [
                self._serialize_admin_session(
                    session,
                    tests_by_id.get(session.testId),
                )
                for session in updated_sessions
            ],
            "total": query.count(),
            "page": page,
            "per_page": per_page,
        }

    def refresh_expired_sessions(self, test_id=None):
        filters = {"status": "in_progress"}
        if test_id and test_id != "all":
            filters["testId"] = test_id

        test_ids = TestSession.objects(**filters).distinct("testId")
        valid_ids = [value for value in test_ids if ObjectId.is_valid(value)]
        for test in Test.objects(id__in=valid_ids).only("id", "scheduledDate", "scheduledTime", "duration"):
            if self._is_expired(None, test):
                TestSession.objects(testId=str(test.id), status="in_progress").update(
                    set__status="expired",
                )

    def mark_for_reschedule(self, session_id):
        session = TestSession.objects(id=session_id).first()
        if not session:
            raise TestSessionServiceError("Session introuvable", 404)

        if session.status == "submitted":
            raise TestSessionServiceError(
                "Un test déjà soumis ne peut pas être reprogrammé",
                409,
            )

        session = TestSession.objects(id=session.id, status__ne="submitted").modify(
            new=True, set__status="to_reschedule", set__remainingTime=0,
            set__lastSeenAt=datetime.utcnow(),
        )
        if not session:
            raise TestSessionServiceError("Un test deja soumis ne peut pas etre reprogramme", 409)
        self._release_candidate_from_test_group(session)
        return session

    @staticmethod
    def _safe_int(value, default):
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _build_admin_query(filters):
        filters = filters or {}
        query_filters = {}
        status = filters.get("status")

        if status and status != "all":
            query_filters["status"] = status

        test_id = filters.get("testId")
        if test_id and test_id != "all":
            query_filters["testId"] = test_id

        try:
            search = text_search_filter(filters.get("search"), (
                "candidateEmail", "candidateName", "candidatePhone",
            ), ("candidatePhone",))
        except ValueError as error:
            raise TestSessionServiceError(str(error)) from error
        return TestSession.objects(**query_filters).filter(__raw__=search)

    @staticmethod
    def _get_tests_by_id(sessions):
        test_ids = list({session.testId for session in sessions if ObjectId.is_valid(session.testId)})
        if not test_ids:
            return {}

        return {str(test.id): test for test in Test.objects(id__in=test_ids)}

    def _sync_session_status(self, session, test):
        if session.status in ("submitted", "to_reschedule"):
            return session

        result_exists = TestResult.objects(
            testId=session.testId,
            candidate__email=session.candidateEmail,
        ).only("id").first()
        if result_exists:
            return self.mark_submitted(session.testId, session.candidateEmail, {
                "phone": session.candidatePhone, "name": session.candidateName,
            })

        if self._is_expired(session, test):
            return TestSession.objects(id=session.id, status="in_progress").modify(
                new=True, set__status="expired",
            ) or TestSession.objects(id=session.id).first()

        return session

    @staticmethod
    def _is_expired(session, test):
        if not test:
            return False

        starts_at = TestSessionService._parse_test_start(test)
        if not starts_at:
            return False

        duration = test.duration or 0
        return datetime.utcnow() > starts_at + timedelta(minutes=duration)

    @staticmethod
    def _parse_test_start(test):
        raw_date = (test.scheduledDate or "").strip()
        raw_time = (test.scheduledTime or "00:00").strip()

        for pattern in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
            try:
                return datetime.strptime(f"{raw_date} {raw_time}", pattern)
            except ValueError:
                continue

        try:
            return datetime.fromisoformat(raw_date.replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            return None

    @staticmethod
    def _serialize_admin_session(session, test):
        answers = session.answers or {}
        return {
            **session.to_dict(),
            "answeredCount": len(answers),
            "testTitle": test.title if test else "Test inconnu",
            "referentiel": test.referentiel if test else None,
            "duration": test.duration if test else None,
        }

    @staticmethod
    def _release_candidate_from_test_group(session):
        candidate = Candidature.objects(email=session.candidateEmail).only("id").first()
        if not candidate:
            return

        group = TestGroup.objects(test_id=session.testId).first()
        if not group:
            return

        candidate_id = str(candidate.id)
        if candidate_id not in (group.candidate_ids or []):
            return

        TestGroup.objects(id=group.id).update_one(
            pull__candidate_ids=candidate_id, set__updated_at=datetime.utcnow(),
        )
