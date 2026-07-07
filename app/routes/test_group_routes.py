from flask import Blueprint, current_app, jsonify, request

from app.services.tests.test_group_service import (
    TestGroupService,
    TestGroupServiceError,
)
from app.utils.auth_decorators import admin_required


test_group_bp = Blueprint("test_group", __name__)
test_group_service = TestGroupService()


def group_error_response(error):
    return jsonify({
        "success": False,
        "error": str(error),
    }), error.status_code


@test_group_bp.route("/test-groups", methods=["GET"])
@admin_required({"competences", "super_admin"})
def get_all_test_groups():
    try:
        groups = test_group_service.list_groups(
            formation=request.args.get("formation"),
            status=request.args.get("status"),
        )
        return jsonify({
            "success": True,
            "data": groups,
            "total": len(groups),
        }), 200
    except Exception as error:
        return jsonify({
            "success": False,
            "error": (
                "Erreur lors de la récupération des groupes : "
                f"{error}"
            ),
        }), 500


@test_group_bp.route("/test-groups", methods=["POST"])
@admin_required({"competences", "super_admin"})
def create_test_group():
    try:
        group = test_group_service.create_group(
            request.get_json() or {},
        )
        return jsonify({
            "success": True,
            "message": "Groupe créé avec succès",
            "data": group.to_dict(),
        }), 201
    except TestGroupServiceError as error:
        return group_error_response(error)
    except Exception as error:
        return jsonify({
            "success": False,
            "error": f"Erreur lors de la création du groupe : {error}",
        }), 500


@test_group_bp.route("/test-groups/available-candidates", methods=["GET"])
@admin_required({"competences", "super_admin"})
def get_available_group_candidates():
    try:
        page = max(request.args.get("page", default=1, type=int), 1)
        per_page = min(
            max(request.args.get("per_page", default=100, type=int), 1),
            200,
        )
        payload = test_group_service.list_available_candidates(
            formation=request.args.get("formation", ""),
            search=request.args.get("search", ""),
            page=page,
            per_page=per_page,
        )
        return jsonify({"success": True, **payload}), 200
    except TestGroupServiceError as error:
        return group_error_response(error)
    except Exception as error:
        return jsonify({
            "success": False,
            "error": (
                "Erreur lors de la récupération des candidats "
                f"disponibles : {error}"
            ),
        }), 500


@test_group_bp.route("/test-groups/<group_id>", methods=["GET"])
@admin_required({"competences", "super_admin"})
def get_test_group(group_id):
    try:
        group = test_group_service.get_group(group_id)
        return jsonify({
            "success": True,
            "data": test_group_service.serialize_group(group),
        }), 200
    except TestGroupServiceError as error:
        return group_error_response(error)
    except Exception as error:
        return jsonify({
            "success": False,
            "error": (
                "Erreur lors de la récupération du groupe : "
                f"{error}"
            ),
        }), 500


@test_group_bp.route(
    "/test-groups/<group_id>",
    methods=["PATCH", "PUT"],
)
@admin_required({"competences", "super_admin"})
def update_test_group(group_id):
    try:
        group = test_group_service.update_group(
            group_id,
            request.get_json() or {},
        )
        return jsonify({
            "success": True,
            "message": "Groupe mis à jour avec succès",
            "data": group.to_dict(),
        }), 200
    except TestGroupServiceError as error:
        return group_error_response(error)
    except Exception as error:
        return jsonify({
            "success": False,
            "error": f"Erreur lors de la mise à jour : {error}",
        }), 500


@test_group_bp.route("/test-groups/<group_id>", methods=["DELETE"])
@admin_required({"competences", "super_admin"})
def delete_test_group(group_id):
    try:
        test_group_service.delete_group(group_id)
        return jsonify({
            "success": True,
            "message": "Groupe supprimé avec succès",
        }), 200
    except TestGroupServiceError as error:
        return group_error_response(error)
    except Exception as error:
        return jsonify({
            "success": False,
            "error": f"Erreur lors de la suppression : {error}",
        }), 500


@test_group_bp.route(
    "/test-groups/<group_id>/send-invitations",
    methods=["POST"],
)
@admin_required({"competences", "super_admin"})
def send_test_invitations(group_id):
    try:
        result = test_group_service.send_invitations(
            group_id,
            frontend_url=current_app.config.get(
                "FRONTEND_URL",
                "http://localhost:3000",
            ),
            simulate=request.host.startswith(
                ("localhost", "127.0.0.1", "192.168."),
            ),
        )
        return jsonify(result["payload"]), result["status_code"]
    except TestGroupServiceError as error:
        return group_error_response(error)
    except Exception as error:
        current_app.logger.exception(
            "Erreur lors de l'envoi des invitations",
        )
        return jsonify({
            "success": False,
            "error": (
                "Erreur lors de l'envoi des invitations : "
                f"{error}"
            ),
        }), 500


@test_group_bp.route("/test-groups/statistics", methods=["GET"])
@admin_required({"competences", "super_admin"})
def get_test_groups_statistics():
    try:
        return jsonify({
            "success": True,
            "data": test_group_service.get_statistics(
                request.args.get("formation"),
            ),
        }), 200
    except Exception as error:
        return jsonify({
            "success": False,
            "error": (
                "Erreur lors de la récupération des statistiques : "
                f"{error}"
            ),
        }), 500
