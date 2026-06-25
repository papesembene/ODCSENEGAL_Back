from flask import Blueprint, jsonify, request

from app.services.tests.test_violation_service import (
    TestViolationService,
    TestViolationServiceError,
)


test_violation_bp = Blueprint("test_violations", __name__)
test_violation_service = TestViolationService()


def violation_error_response(error):
    return jsonify({
        "success": False,
        "error": str(error),
    }), error.status_code


@test_violation_bp.route(
    "/tests/<test_id>/log-violation",
    methods=["POST"],
)
def log_violation(test_id):
    try:
        violation = test_violation_service.log(
            test_id,
            request.get_json() or {},
        )
        return jsonify({
            "success": True,
            "message": "Violation enregistrée",
            "data": {
                "totalViolations": violation.totalViolations,
                "stats": violation.stats,
            },
        }), 201
    except TestViolationServiceError as error:
        return violation_error_response(error)
    except Exception as error:
        return jsonify({
            "success": False,
            "error": f"Erreur serveur: {error}",
        }), 500


@test_violation_bp.route(
    "/tests/<test_id>/violations",
    methods=["GET"],
)
def get_test_violations(test_id):
    try:
        violations = test_violation_service.list_for_test(test_id)
        return jsonify({
            "success": True,
            "data": violations,
            "count": len(violations),
        }), 200
    except Exception as error:
        return jsonify({
            "success": False,
            "error": f"Erreur serveur: {error}",
        }), 500


@test_violation_bp.route(
    "/tests/<test_id>/violations/<candidate_email>",
    methods=["GET"],
)
def get_candidate_violations(test_id, candidate_email):
    try:
        violation = test_violation_service.get_for_candidate(
            test_id,
            candidate_email,
        )
        if not violation:
            return jsonify({
                "success": True,
                "data": None,
                "message": "Aucune violation enregistrée",
            }), 200
        return jsonify({
            "success": True,
            "data": violation.to_dict(),
        }), 200
    except Exception as error:
        return jsonify({
            "success": False,
            "error": f"Erreur serveur: {error}",
        }), 500


@test_violation_bp.route("/violations/all", methods=["GET"])
def get_all_violations():
    try:
        violations = test_violation_service.list_all()
        return jsonify({
            "success": True,
            "data": violations,
            "count": len(violations),
        }), 200
    except Exception as error:
        return jsonify({
            "success": False,
            "error": f"Erreur serveur: {error}",
        }), 500


@test_violation_bp.route(
    "/tests/<test_id>/violations/<candidate_email>",
    methods=["DELETE"],
)
def delete_candidate_violations(test_id, candidate_email):
    try:
        test_violation_service.delete_for_candidate(
            test_id,
            candidate_email,
        )
        return jsonify({
            "success": True,
            "message": "Violations supprimées",
        }), 200
    except TestViolationServiceError as error:
        return violation_error_response(error)
    except Exception as error:
        return jsonify({
            "success": False,
            "error": f"Erreur serveur: {error}",
        }), 500
