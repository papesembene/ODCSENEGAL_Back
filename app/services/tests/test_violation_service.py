"""Anti-cheat violation use cases."""

from app.models.test_violation import TestViolation


class TestViolationServiceError(Exception):
    def __init__(self, message, status_code=400):
        super().__init__(message)
        self.status_code = status_code


class TestViolationService:
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
        violation = TestViolation.objects(
            testId=str(test_id),
            candidateEmail=candidate_email,
        ).first()
        if not violation:
            violation = TestViolation(
                testId=str(test_id),
                testResultId=data.get("testResultId"),
                candidateEmail=candidate_email,
                metadata=data.get("metadata", {}),
            )
        violation.testResultId = (
            data.get("testResultId") or violation.testResultId
        )
        violation.add_violation(
            violation_type,
            message,
            data.get("elapsedTime"),
        )
        violation.save()
        return violation

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
