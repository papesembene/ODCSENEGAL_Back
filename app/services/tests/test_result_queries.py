"""Bounded result pages, database aggregates and streaming CSV exports."""

import csv
from io import StringIO
from math import ceil

from bson import ObjectId

from app.models.test import Test
from app.models.test_result import TestResult
from app.models.test_violation import TestViolation
from app.services.tests.formation_catalog import formation_aliases


SUMMARY_FIELDS = ("testId", "testTitle", "referentiel", "candidate", "score", "status",
                  "completedAt", "submittedDate", "submittedTime")
STATUSES = {"selected": "admis", "not_selected": "rejeté", "en_attente": "pending"}


def result_query(filters):
    query = {}
    if filters.get("testId") and filters["testId"] != "all":
        query["testId"] = filters["testId"]
    formation = filters.get("referentiel")
    if formation and formation != "all":
        query["referentiel__in"] = formation_aliases(formation)
    status = filters.get("status")
    if status and status != "all":
        status = STATUSES.get(status, status)
        if status not in {"admis", "rejeté", "pending"}:
            raise ValueError("Statut de resultat invalide")
        query["status"] = status
    return TestResult.objects(**query)


def positive_integer(value, default, maximum=None):
    try:
        number = int(value) if value is not None else default
    except (ValueError, TypeError) as error:
        raise ValueError("Pagination invalide") from error
    if number < 1 or (maximum is not None and number > maximum):
        raise ValueError("Pagination invalide (100 resultats maximum par page)")
    return number


def summary(result):
    data = result.to_dict()
    return {key: data[key] for key in ("id", *SUMMARY_FIELDS)}


def result_points(result, test):
    if not test:
        return {"obtained": 0, "total": 0}
    total = sum(question.score or 0 for question in test.questions)
    if not result.answers:
        return {"obtained": int(result.score * total / 100 + 0.5), "total": total}
    obtained = 0
    for index, question in enumerate(test.questions):
        answer = result.answers.get(str(index))
        if question.type == "texte_libre":
            obtained += (result.manualGrades or {}).get(f"q{index}", (result.manualGrades or {}).get(str(index), 0)) or 0
        elif question.type == "qcm_simple" and type(answer) is int and answer == question.correctAnswer:
            obtained += question.score or 0
        elif question.type == "qcm_multiple" and isinstance(answer, list):
            expected = question.correctAnswers or []
            if all(type(value) is int for value in answer) and sorted(answer) == sorted(expected):
                obtained += question.score or 0
    return {"obtained": int(obtained + 0.5), "total": total}


class TestResultQueries:
    @staticmethod
    def page(filters):
        requested_page = positive_integer(filters.get("page"), 1)
        per_page = positive_integer(filters.get("per_page"), 20, 100)
        query = result_query(filters)
        total = query.count()
        pages = max(1, ceil(total / per_page))
        page = min(requested_page, pages)
        results = list(query.only(*SUMMARY_FIELDS, "answers", "manualGrades").order_by(
            "-completedAt", "-id",
        ).skip((page - 1) * per_page).limit(per_page))
        ids = {ObjectId(result.testId) for result in results if ObjectId.is_valid(result.testId)}
        tests = {str(test.id): test for test in Test.objects(id__in=ids).only(
            "questions.type", "questions.score", "questions.correctAnswer", "questions.correctAnswers",
        )} if ids else {}
        pairs = [{"testId": result.testId, "candidateEmail": {"$in": [
            result.candidate.email, result.candidate.email.lower(),
        ]}} for result in results]
        violations = {}
        if pairs:
            for entry in TestViolation._get_collection().find(
                {"$or": pairs}, {"testId": 1, "candidateEmail": 1, "totalViolations": 1},
            ):
                violations[(entry["testId"], entry["candidateEmail"].lower())] = entry.get("totalViolations", 0)
        data = []
        for result in results:
            item = summary(result)
            item["points"] = result_points(result, tests.get(result.testId))
            item["violationSummary"] = {"totalViolations": violations.get((result.testId, result.candidate.email.lower()), 0)}
            data.append(item)
        return {"data": data, "total": total, "pagination": {
            "page": page, "per_page": per_page, "total": total, "total_pages": pages,
        }}

    @staticmethod
    def statistics(filters=None):
        fields = {
            "total": {"$sum": 1}, "total_score": {"$sum": "$score"},
            "average_score": {"$avg": "$score"},
            "admis": {"$sum": {"$cond": [{"$eq": ["$status", "admis"]}, 1, 0]}},
            "rejetes": {"$sum": {"$cond": [{"$eq": ["$status", "rejeté"]}, 1, 0]}},
        }
        for lower in range(0, 100, 20):
            condition = {"$and": [{"$gte": ["$score", lower]}, {"$lt": ["$score", lower + 20]}]} if lower < 80 else {"$gte": ["$score", 80]}
            fields[f"bin_{lower}"] = {"$sum": {"$cond": [condition, 1, 0]}}
        rows = list(result_query(filters or {}).aggregate([{"$group": {"_id": None, **fields}}]))
        row = rows[0] if rows else {}
        total, admitted, rejected = row.get("total", 0), row.get("admis", 0), row.get("rejetes", 0)
        return {"total": total, "admis": admitted, "rejetes": rejected,
                "pending": total - admitted - rejected,
                "average_score": round(row.get("average_score", 0) or 0, 2),
                "pass_rate": round(admitted / total * 100, 2) if total else 0,
                "score_distribution": [{"range": f"{lower}-{lower + 20}", "count": row.get(f"bin_{lower}", 0)} for lower in range(0, 100, 20)]}

    @staticmethod
    def performance_by_referential():
        rows = TestResult.objects.aggregate([{"$group": {
            "_id": "$referentiel", "total": {"$sum": 1}, "total_score": {"$sum": "$score"},
            "admis": {"$sum": {"$cond": [{"$eq": ["$status", "admis"]}, 1, 0]}},
            "rejetes": {"$sum": {"$cond": [{"$eq": ["$status", "rejeté"]}, 1, 0]}},
        }}])
        return [{"referentiel": row["_id"] or "Non specifie", "total": row["total"],
                 "total_score": row["total_score"], "admis": row["admis"], "rejetes": row["rejetes"],
                 "pending": row["total"] - row["admis"] - row["rejetes"],
                 "average_score": round(row["total_score"] / row["total"], 2),
                 "pass_rate": round(row["admis"] / row["total"] * 100, 2)} for row in rows]

    @staticmethod
    def export(filters):
        query = result_query(filters).only(*SUMMARY_FIELDS).order_by("-completedAt", "-id").no_cache().batch_size(500)

        def stream():
            output = StringIO(newline="")
            writer = csv.writer(output)
            yield "\ufeff"
            writer.writerow(["Nom", "Email", "Telephone", "Test", "Referentiel", "Score", "Statut", "Date", "Heure"])
            yield output.getvalue()
            for result in query:
                date = result.completedAt
                values = [result.candidate.name, result.candidate.email, result.candidate.phone,
                          result.testTitle, result.referentiel, result.score,
                          {"admis": "Passe en entretien", "rejeté": "Rejete"}.get(result.status, "En attente"),
                          result.submittedDate or (date.strftime("%d/%m/%Y") if date else ""),
                          result.submittedTime or (date.strftime("%H:%M:%S") if date else "")]
                output.seek(0)
                output.truncate(0)
                writer.writerow(["'" + str(value) if str(value).lstrip().startswith(("=", "+", "-", "@")) else value for value in values])
                yield output.getvalue()
        return stream()
