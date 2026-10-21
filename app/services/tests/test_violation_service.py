"""Anti-cheat violation use cases."""

from datetime import datetime
import re
from pymongo.errors import DuplicateKeyError

from app.models.test_violation import TestViolation
from app.services.tests.test_access_service import SlidingWindowRateLimiter


class TestViolationServiceError(Exception):
    def __init__(self, message, status_code=400):
        super().__init__(message)
        self.status_code = status_code


class TestViolationService:
    rate_limiter = SlidingWindowRateLimiter(
        limit=120,
        window=60,
        max_keys=50000,
    )

    @staticmethod
    def log(test_id, data):
        data = data or {}
        candidate_email = (data.get("candidateEmail") or "").strip().lower()
        violation_type = data.get("type")
        message = data.get("message")
        if not candidate_email or not violation_type or not message:
            raise TestViolationServiceError(
                "Email, type et message sont requis"
            )
        if not isinstance(violation_type, str) or not re.fullmatch(r"[a-z_]{1,64}", violation_type):
            raise TestViolationServiceError("Type d'evenement invalide")
        if not isinstance(message, str) or len(message) > 1000:
            raise TestViolationServiceError("Message d'evenement invalide")
        elapsed = data.get("elapsedTime")
        if elapsed is not None and (type(elapsed) is not int or elapsed < 0):
            raise TestViolationServiceError("Temps ecoule invalide")
        if TestViolationService.rate_limiter.is_limited(
            f"{test_id}:{candidate_email}",
        ):
            raise TestViolationServiceError(
                "Trop d'événements anti-triche reçus, réessayez dans un instant",
                429,
            )
        now = datetime.utcnow()
        query = {"testId": str(test_id), "candidateEmail": candidate_email}
        update = {
            "$setOnInsert": {"createdAt": now, "firstViolationAt": now},
            "$set": {"updatedAt": now, "lastViolationAt": now},
            "$inc": {"totalViolations": 1, f"stats.{violation_type}": 1},
            "$push": {"violations": {"violationType": violation_type, "message": message,
                                     "timestamp": now, "elapsedTime": elapsed}},
        }
        collection = TestViolation._get_collection()
        try:
            collection.update_one(query, update, upsert=True)
        except DuplicateKeyError:
            # Two first events may race to create the unique candidate record.
            collection.update_one(query, update, upsert=False)
        return TestViolation.objects(__raw__=query).get()

    @staticmethod
    def list_for_test(test_id):
        return [
            item.to_dict()
            for item in TestViolation.objects(testId=str(test_id)).all()
        ]

    @staticmethod
    def get_for_candidate(test_id, candidate_email):
        return TestViolation.objects(
            testId=str(test_id),
            candidateEmail=candidate_email,
        ).first()

    @staticmethod
    def list_all():
        return [item.to_dict() for item in TestViolation.objects.all()]

    def delete_for_candidate(self, test_id, candidate_email):
        violation = self.get_for_candidate(test_id, candidate_email)
        if not violation:
            raise TestViolationServiceError(
                "Aucune violation trouvée",
                404,
            )
        violation.delete()
