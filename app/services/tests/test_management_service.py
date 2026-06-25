"""Test definitions, results and statistics use cases."""

from collections import defaultdict
from datetime import datetime
import re

from mongoengine.errors import ValidationError

from app.models.test import Question, Test
from app.models.test_result import Candidate, TestResult


class TestServiceError(Exception):
    def __init__(self, message, status_code=400, **details):
        super().__init__(message)
        self.status_code = status_code
        self.details = details


class TestManagementService:
    REQUIRED_TEST_FIELDS = (
        "title",
        "referentiel",
        "duration",
        "scheduledDate",
        "scheduledTime",
        "passingScore",
    )
    TEST_UPDATE_FIELDS = (
        "title",
        "referentiel",
        "duration",
        "scheduledDate",
        "scheduledTime",
        "passingScore",
        "candidatesGroup",
        "description",
        "status",
    )

    @staticmethod
    def list_tests():
        return [test.to_dict() for test in Test.objects()]

    @staticmethod
    def get_test(test_id):
        test = Test.objects(id=test_id).first()
        if not test:
            raise TestServiceError("Test non trouvé", 404)
        return test

    def create_test(self, data):
        data = data or {}
        self._require_fields(data, self.REQUIRED_TEST_FIELDS)
        questions = self._build_questions(data.get("questions", []))
        test = Test(
            title=data["title"],
            referentiel=data["referentiel"],
            duration=data["duration"],
            scheduledDate=data["scheduledDate"],
            scheduledTime=data["scheduledTime"],
            totalQuestions=len(questions),
            passingScore=data["passingScore"],
            candidatesGroup=data.get("candidatesGroup", ""),
            description=data.get("description", ""),
            questions=questions,
            status=data.get("status", "active"),
            createdBy=data.get("createdBy", ""),
        )
        try:
            test.save()
        except ValidationError as error:
            raise TestServiceError(
                f"Erreur de validation : {error}",
            ) from error
        return test

    def update_test(self, test_id, data):
        test = self.get_test(test_id)
        data = data or {}
        for field in self.TEST_UPDATE_FIELDS:
            if field in data:
                setattr(test, field, data[field])
        if "questions" in data:
            test.questions = self._build_questions(data["questions"])
            test.totalQuestions = len(test.questions)
        test.updatedAt = datetime.utcnow()
        test.updatedBy = data.get("updatedBy", "")
        try:
            test.save()
        except ValidationError as error:
            raise TestServiceError(
                f"Erreur de validation : {error}",
            ) from error
        return test

    def delete_test(self, test_id):
        test = self.get_test(test_id)
        test.delete()

    @staticmethod
    def list_results(filters):
        query = {
            key: value
            for key, value in filters.items()
            if value
        }
        return [
            result.to_dict()
            for result in TestResult.objects(**query).order_by(
                "-completedAt",
            )
        ]

    @staticmethod
    def get_result(result_id):
        result = TestResult.objects(id=result_id).first()
        if not result:
            raise TestServiceError("Résultat non trouvé", 404)
        return result

    def submit_result(self, data):
        data = data or {}
        self._require_fields(
            data,
            ("testId", "testTitle", "referentiel", "candidate", "score"),
        )
        candidate_data = data.get("candidate") or {}
        self._require_fields(
            candidate_data,
            ("name", "email", "phone"),
        )
        candidate_email = candidate_data["email"].strip()
        email_pattern = re.compile(
            f"^{re.escape(candidate_email)}$",
            re.IGNORECASE,
        )
        if TestResult.objects(
            testId=data["testId"],
            candidate__email=email_pattern,
        ).only("id").first():
            raise TestServiceError(
                "Vous avez déjà passé ce test",
                409,
                duplicate=True,
            )

        passing_score = data.get("passingScore", 70)
        result = TestResult(
            testId=data["testId"],
            testTitle=data["testTitle"],
            referentiel=data["referentiel"],
            candidate=Candidate(
                name=candidate_data["name"],
                email=candidate_email,
                phone=candidate_data["phone"],
            ),
            answers=data.get("answers", {}),
            score=data["score"],
            status=(
                "admis"
                if data["score"] >= passing_score
                else "rejeté"
            ),
            submittedDate=data.get("submittedDate", ""),
            submittedTime=data.get("submittedTime", ""),
            manualGrades=data.get("manualGrades", {}),
        )
        try:
            result.save()
        except ValidationError as error:
            raise TestServiceError(
                f"Erreur de validation : {error}",
            ) from error
        except Exception as error:
            error_text = str(error).lower()
            if any(
                marker in error_text
                for marker in ("duplicate", "e11000", "duplicate key")
            ):
                raise TestServiceError(
                    "Vous avez déjà passé ce test",
                    409,
                    duplicate=True,
                ) from error
            raise
        return result

    def update_result(self, result_id, data):
        result = self.get_result(result_id)
        data = data or {}
        for field in ("status", "score", "manualGrades"):
            if field in data:
                setattr(result, field, data[field])
        try:
            result.save()
        except ValidationError as error:
            raise TestServiceError(
                f"Erreur de validation : {error}",
            ) from error
        return result

    @staticmethod
    def get_statistics(referentiel=None):
        query = {"referentiel": referentiel} if referentiel else {}
        results = TestResult.objects(**query)
        total = results.count()
        admitted = results.filter(status="admis").count()
        rejected = results.filter(status="rejeté").count()
        pending = results.filter(status="pending").count()
        scores = [result.score for result in results]
        average = sum(scores) / len(scores) if scores else 0
        return {
            "total": total,
            "admis": admitted,
            "rejetes": rejected,
            "pending": pending,
            "average_score": round(average, 2),
            "pass_rate": round(
                (admitted / total * 100) if total else 0,
                2,
            ),
        }

    @staticmethod
    def get_performance_statistics(now=None):
        now = now or datetime.utcnow()
        all_results = TestResult.objects()
        by_referential = defaultdict(lambda: {
            "total": 0,
            "admis": 0,
            "rejetes": 0,
            "pending": 0,
            "total_score": 0,
            "average_score": 0,
            "pass_rate": 0,
        })
        for result in all_results:
            stats = by_referential[result.referentiel or "Non spécifié"]
            stats["total"] += 1
            stats["total_score"] += result.score or 0
            if result.status == "admis":
                stats["admis"] += 1
            elif result.status == "rejeté":
                stats["rejetes"] += 1
            else:
                stats["pending"] += 1

        performance = []
        for referential, stats in by_referential.items():
            if stats["total"]:
                stats["average_score"] = round(
                    stats["total_score"] / stats["total"],
                    2,
                )
                stats["pass_rate"] = round(
                    stats["admis"] / stats["total"] * 100,
                    2,
                )
            performance.append({
                "referentiel": referential,
                **stats,
            })

        monthly = []
        month_names = (
            "Jan",
            "Fév",
            "Mar",
            "Avr",
            "Mai",
            "Jun",
            "Jul",
            "Aoû",
            "Sep",
            "Oct",
            "Nov",
            "Déc",
        )
        for offset in range(5, -1, -1):
            month = now.month - offset
            year = now.year
            if month <= 0:
                month += 12
                year -= 1
            start = datetime(year, month, 1)
            end = (
                datetime(year + 1, 1, 1)
                if month == 12
                else datetime(year, month + 1, 1)
            )
            results = TestResult.objects(
                completedAt__gte=start,
                completedAt__lt=end,
            )
            total = results.count()
            admitted = results.filter(status="admis").count()
            monthly.append({
                "mois": month_names[month - 1],
                "taux": round(
                    admitted / total * 100 if total else 0,
                    2,
                ),
                "total": total,
                "admis": admitted,
            })

        total = all_results.count()
        admitted = all_results.filter(status="admis").count()
        return {
            "performance_by_referentiel": performance,
            "monthly_pass_rate": monthly,
            "global_pass_rate": round(
                admitted / total * 100 if total else 0,
                2,
            ),
            "total_tests": total,
            "total_admis": admitted,
        }

    @staticmethod
    def _build_questions(raw_questions):
        return [
            Question(
                question=item.get("question"),
                type=item.get("type"),
                options=item.get("options", []),
                correctAnswer=item.get("correctAnswer"),
                correctAnswers=item.get("correctAnswers", []),
                score=item.get("score", 5),
                image=item.get("image"),
            )
            for item in raw_questions or []
        ]

    @staticmethod
    def _require_fields(data, fields):
        for field in fields:
            if field not in data:
                raise TestServiceError(
                    f"Le champ {field} est requis",
                )
