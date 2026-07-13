from flask import Blueprint, g, jsonify, request

from app.services.interviews.evaluation_service import (
    InterviewEvaluationService,
)
from app.services.interviews.exceptions import InterviewError
from app.services.interviews.management_service import (
    InterviewManagementService,
)
from app.services.interviews.query_service import InterviewQueryService
from app.utils.auth_decorators import admin_required


interview_bp = Blueprint("interview_bp", __name__)
interview_public_bp = Blueprint("interview_public_bp", __name__)
management_service = InterviewManagementService()
query_service = InterviewQueryService()
evaluation_service = InterviewEvaluationService(query_service=query_service)
ADMIN_TYPES = {"competences", "super_admin"}


def _error_response(error):
    return jsonify(
        {"success": False, "error": str(error)}
    ), error.status_code


@interview_bp.route("/interviews/bootstrap", methods=["GET"])
@admin_required(ADMIN_TYPES)
def get_interviews_bootstrap():
    data = query_service.bootstrap(
        request.args.get("formation"),
        getattr(g, "current_admin", None),
    )
    return jsonify({"success": True, "data": data}), 200


@interview_bp.route("/interviews/capabilities", methods=["GET"])
@admin_required(ADMIN_TYPES)
def get_interview_capabilities():
    return jsonify(
        {
            "success": True,
            "data": query_service.member_capabilities(
                getattr(g, "current_admin", None),
            ),
        }
    ), 200


@interview_bp.route("/interviews/campaigns", methods=["GET"])
@admin_required(ADMIN_TYPES)
def get_interview_campaigns():
    return jsonify(
        {
            "success": True,
            "data": query_service.list_campaigns(
                request.args.get("formation")
            ),
        }
    ), 200


@interview_bp.route("/interviews/campaigns", methods=["POST"])
@admin_required(ADMIN_TYPES)
def create_interview_campaign():
    try:
        campaign = management_service.create_campaign(
            request.get_json(silent=True) or {}
        )
        return jsonify(
            {"success": True, "data": campaign.to_dict()}
        ), 201
    except InterviewError as error:
        return _error_response(error)


@interview_bp.route(
    "/interviews/campaigns/<campaign_id>",
    methods=["PATCH"],
)
@admin_required(ADMIN_TYPES)
def update_interview_campaign(campaign_id):
    try:
        campaign = management_service.update_campaign(
            campaign_id,
            request.get_json(silent=True) or {},
            current_admin=getattr(g, "current_admin", None),
        )
        return jsonify(
            {"success": True, "data": campaign.to_dict()}
        ), 200
    except InterviewError as error:
        return _error_response(error)


@interview_bp.route("/interviews/slots", methods=["GET"])
@admin_required(ADMIN_TYPES)
def get_interview_slots():
    return jsonify(
        {
            "success": True,
            "data": query_service.list_slots(
                request.args.get("campaignId")
            ),
        }
    ), 200


@interview_bp.route("/interviews/slots", methods=["POST"])
@admin_required(ADMIN_TYPES)
def create_interview_slot():
    try:
        slot = management_service.create_slot(
            request.get_json(silent=True) or {}
        )
        return jsonify(
            {"success": True, "data": slot.to_dict()}
        ), 201
    except InterviewError as error:
        return _error_response(error)


@interview_bp.route(
    "/interviews/slots/<slot_id>",
    methods=["PATCH"],
)
@admin_required(ADMIN_TYPES)
def update_interview_slot(slot_id):
    try:
        slot = management_service.update_slot(
            slot_id,
            request.get_json(silent=True) or {},
        )
        return jsonify(
            {"success": True, "data": slot.to_dict()}
        ), 200
    except InterviewError as error:
        return _error_response(error)


@interview_public_bp.route(
    "/availability/<token>",
    methods=["GET"],
)
def confirm_interview_availability(token):
    try:
        response = (request.args.get("response") or "").strip().lower()
        result = management_service.confirm_jury_availability(
            token,
            response,
        )
        label = (
            "disponible"
            if result["status"] == "available"
            else "indisponible"
        )
        return (
            "<!doctype html><html><head><meta charset='utf-8'>"
            "<title>Disponibilité enregistrée</title></head>"
            "<body style='font-family:Arial,sans-serif;padding:32px'>"
            "<h2>Merci, votre disponibilité a été enregistrée.</h2>"
            f"<p>Statut déclaré : <strong>{label}</strong>.</p>"
            "</body></html>"
        ), 200
    except InterviewError as error:
        return (
            "<!doctype html><html><head><meta charset='utf-8'>"
            "<title>Lien invalide</title></head>"
            "<body style='font-family:Arial,sans-serif;padding:32px'>"
            "<h2>Impossible d'enregistrer la disponibilité.</h2>"
            f"<p>{str(error)}</p>"
            "</body></html>"
        ), error.status_code


@interview_bp.route("/interviews/evaluations", methods=["GET"])
@admin_required(ADMIN_TYPES)
def get_interview_evaluations():
    page = query_service.evaluation_page(
        request.args,
        getattr(g, "current_admin", None),
    )
    return jsonify({"success": True, **page}), 200


@interview_bp.route(
    "/interviews/evaluations/seed",
    methods=["POST"],
)
@admin_required(ADMIN_TYPES)
def seed_interview_evaluations():
    try:
        result = evaluation_service.seed(
            request.get_json(silent=True) or {}
        )
        return jsonify({"success": True, **result}), 201
    except InterviewError as error:
        return _error_response(error)


@interview_bp.route(
    "/interviews/evaluations/<evaluation_id>",
    methods=["PATCH"],
)
@admin_required(ADMIN_TYPES)
def update_interview_evaluation(evaluation_id):
    try:
        evaluation = evaluation_service.update(
            evaluation_id,
            request.get_json(silent=True) or {},
            getattr(g, "current_admin", None),
        )
        return jsonify(
            {"success": True, "data": evaluation.to_dict()}
        ), 200
    except InterviewError as error:
        return _error_response(error)
