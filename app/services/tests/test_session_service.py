"""Candidate online-test session drafts."""

from datetime import datetime

from mongoengine.errors import NotUniqueError, ValidationError

from app.models.test_session import TestSession


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

        session = self.get_draft(test_id, candidate_email) or TestSession(
            testId=str(test_id),
            candidateEmail=candidate_email,
            startedAt=datetime.utcnow(),
        )

        session.candidatePhone = candidate_phone
        session.candidateName = (data.get("name") or "").strip()
        session.answers = data.get("answers") or {}
        session.lastQuestion = self._safe_int(data.get("lastQuestion"), 0)
        session.remainingTime = self._safe_int(data.get("remainingTime"), 0)
        session.status = "in_progress"
        session.lastSeenAt = datetime.utcnow()

        try:
            session.save()
        except NotUniqueError:
            session = self.get_draft(test_id, candidate_email)
            if not session:
                raise
            return self.save_draft(test_id, data, access)
        except ValidationError as error:
            raise TestSessionServiceError(f"Brouillon invalide : {error}", 400) from error

        return session

    @staticmethod
    def mark_submitted(test_id, candidate_email):
        session = TestSession.objects(
            testId=str(test_id),
            candidateEmail=(candidate_email or "").strip().lower(),
        ).first()
        if not session:
            return None

        session.status = "submitted"
        session.submittedAt = datetime.utcnow()
        session.lastSeenAt = datetime.utcnow()
        session.save()
        return session

    @staticmethod
    def _safe_int(value, default):
        try:
            return int(value)
        except (TypeError, ValueError):
            return default
