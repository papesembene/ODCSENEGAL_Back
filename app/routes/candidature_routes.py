import json
import logging

from flask import Blueprint, jsonify, request

from app.services.candidatures.service import (
    CandidatureService,
    CandidatureServiceError,
)
from app.utils.auth_decorators import admin_required
from app.utils.request_guards import (
    is_request_rate_limited,
    normalize_email,
)


candidature_public_bp = Blueprint("candidature_public", __name__)
candidature_bp = Blueprint("candidature", __name__)
candidature_service = CandidatureService()
logger = logging.getLogger(__name__)


def candidature_error_response(error):
    return jsonify(error=str(error)), error.status_code


def admin_error_response(error):
    return jsonify({
        "success": False,
        "error": str(error),
    }), error.status_code


def read_submission_payload():
    data = request.get_json(silent=True)
    if not data:
        data = request.form.to_dict()
    if not data:
        raw_body = request.get_data(as_text=True) or ""
        if raw_body.strip():
            try:
                data = json.loads(raw_body)
            except json.JSONDecodeError:
                data = None
    return data


@candidature_public_bp.route("/apply", methods=["POST"])
def apply():
    data = read_submission_payload()
    client_identifier = (
        normalize_email((data or {}).get("email"))
        or request.remote_addr
    )
    if is_request_rate_limited(
        "candidature_apply",
        client_identifier,
        limit=5,
        window=300,
    ):
        return jsonify(
            error="Trop de tentatives, veuillez réessayer plus tard",
        ), 429

    try:
        candidature = candidature_service.submit(data)
    except CandidatureServiceError as error:
        return candidature_error_response(error)
    except Exception as error:
        return jsonify(error=f"Erreur inconnue : {error}"), 500

    return jsonify(
        message="Candidature enregistrée avec succès",
        candidature_id=str(candidature.id),
    ), 201


@candidature_public_bp.route("/check-unique", methods=["GET"])
def check_unique():
    field = request.args.get("field")
    value = request.args.get("value")
    client_identifier = normalize_email(value) or request.remote_addr
    if is_request_rate_limited(
        "candidature_check_unique",
        client_identifier,
        limit=20,
        window=60,
    ):
        return jsonify(
            error="Trop de vérifications, veuillez réessayer plus tard",
        ), 429

    try:
        exists = candidature_service.check_unique(field, value)
    except CandidatureServiceError as error:
        return candidature_error_response(error)
    return jsonify(exists=exists)


@candidature_bp.route("/candidatures", methods=["GET"])
@admin_required({"competences", "super_admin"})
def get_all_candidatures():
    try:
        page = request.args.get("page", type=int)
        per_page = request.args.get("per_page", type=int)
        if page is not None and page < 1:
            page = 1
        if per_page is not None:
            per_page = min(max(per_page, 1), 200)

        result = candidature_service.list_candidatures(
            desired_training=request.args.get("desired_training"),
            status=request.args.get("status"),
            search=request.args.get("search", ""),
            page=page,
            per_page=per_page,
        )
        return jsonify({"success": True, **result}), 200
    except Exception as error:
        return jsonify({
            "success": False,
            "error": (
                "Erreur lors de la récupération des candidatures : "
                f"{error}"
            ),
        }), 500


@candidature_bp.route(
    "/candidatures/<candidature_id>",
    methods=["GET"],
)
@admin_required({"competences", "super_admin"})
def get_candidature(candidature_id):
    try:
        candidature = candidature_service.get_candidature(candidature_id)
        return jsonify({
            "success": True,
            "data": candidature.to_dict(),
        }), 200
    except CandidatureServiceError as error:
        return admin_error_response(error)
    except Exception as error:
        return jsonify({
            "success": False,
            "error": (
                "Erreur lors de la récupération de la candidature : "
                f"{error}"
            ),
        }), 500


@candidature_bp.route(
    "/candidatures/<candidature_id>",
    methods=["PATCH", "PUT"],
)
@admin_required({"competences", "super_admin"})
def update_candidature(candidature_id):
    try:
        candidature = candidature_service.update_candidature(
            candidature_id,
            request.get_json() or {},
        )
        return jsonify({
            "success": True,
            "message": "Candidature mise à jour avec succès",
            "data": candidature.to_dict(),
        }), 200
    except CandidatureServiceError as error:
        return admin_error_response(error)
    except Exception as error:
        return jsonify({
            "success": False,
            "error": f"Erreur lors de la mise à jour : {error}",
        }), 500


@candidature_bp.route(
    "/candidatures/<candidature_id>",
    methods=["DELETE"],
)
@admin_required({"competences", "super_admin"})
def delete_candidature(candidature_id):
    try:
        candidature_service.delete_candidature(candidature_id)
        return jsonify({
            "success": True,
            "message": "Candidature supprimée avec succès",
        }), 200
    except CandidatureServiceError as error:
        return admin_error_response(error)
    except Exception as error:
        return jsonify({
            "success": False,
            "error": f"Erreur lors de la suppression : {error}",
        }), 500


@candidature_bp.route("/candidatures/statistics", methods=["GET"])
@admin_required({"competences", "super_admin"})
def get_statistics():
    try:
        statistics = candidature_service.get_statistics(
            request.args.get("desired_training"),
        )
        return jsonify({
            "success": True,
            "data": statistics,
        }), 200
    except Exception as error:
        return jsonify({
            "success": False,
            "error": (
                "Erreur lors de la récupération des statistiques : "
                f"{error}"
            ),
        }), 500


@candidature_bp.route("/candidatures/send-emails", methods=["POST"])
@admin_required({"competences", "super_admin"})
def send_emails_to_candidates():
    try:
        batch = candidature_service.prepare_email_batch(
            request.get_json() or {},
        )
        logger.info(
            "Simulation email candidatures type=%s destinataires=%s",
            batch["type"],
            len(batch["emails"]),
        )
        return jsonify({
            "success": True,
            "message": batch["message"],
            "data": {
                "sent": batch["sent"],
                "type": batch["type"],
                "timestamp": batch["timestamp"],
            },
        }), 200
    except CandidatureServiceError as error:
        return admin_error_response(error)
    except Exception as error:
        return jsonify({
            "success": False,
            "error": f"Erreur lors de l'envoi des emails : {error}",
        }), 500
