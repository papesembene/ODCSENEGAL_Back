from flask import Blueprint, Response, g, jsonify, request

from app.services.interviews.evaluation_service import (
    InterviewEvaluationService,
)
from app.services.interviews.exceptions import InterviewError, InterviewForbiddenError, InterviewValidationError
from app.services.interviews.management_service import (
    InterviewManagementService,
)
from app.services.interviews.query_service import InterviewQueryService
from app.services.interviews.questionnaire_service import InterviewQuestionnaireService
from app.services.interviews.ranking_service import InterviewRankingService
from app.services.interviews.referential_service import ReferentialInterviews
from app.services.trainings.schema import TrainingCatalogError
from app.utils.auth_decorators import admin_required


interview_bp = Blueprint("interview_bp", __name__)
interview_public_bp = Blueprint("interview_public_bp", __name__)
management_service = InterviewManagementService()
query_service = InterviewQueryService()
evaluation_service = InterviewEvaluationService(query_service=query_service)
questionnaire_service = InterviewQuestionnaireService()
referential_service = ReferentialInterviews()
ranking_service = InterviewRankingService(referential_service)
ADMIN_TYPES = {"competences", "super_admin"}


def _error_response(error):
    return jsonify(
        {"success": False, "error": str(error)}
    ), error.status_code


def _require_planning_admin():
    if query_service._is_interview_member(getattr(g, "current_admin", None)):
        raise InterviewForbiddenError("La planification est réservée aux administrateurs.")


@interview_bp.route("/interviews/bootstrap", methods=["GET"])
@admin_required(ADMIN_TYPES, allow_interview_members=True)
def get_interviews_bootstrap():
    data = query_service.bootstrap(
        request.args.get("formation"),
        getattr(g, "current_admin", None),
    )
    return jsonify({"success": True, "data": data}), 200


@interview_bp.route("/interviews/overview", methods=["GET"])
@admin_required(ADMIN_TYPES)
def get_interview_overview():
    try:
        campaign_id = request.args.get("campaign_id") or None
        return jsonify({
            "success": True, "data": referential_service.overview(campaign_id),
            "campaigns": referential_service.overview_campaigns(), "campaign_id": campaign_id,
        }), 200
    except InterviewError as error:
        return _error_response(error)


@interview_bp.route("/interviews/referentials/<formation>", methods=["GET", "POST"])
@admin_required(ADMIN_TYPES)
def manage_referential_interviews(formation):
    try:
        if request.method == "GET":
            page = max(1, request.args.get("page", 1, type=int))
            data = referential_service.get(
                formation, request.args.get("search", "")[:150].strip(), page,
                group=request.args.get("group"),
                groups_only=request.args.get("groups_only") == "true",
                campaign_id=request.args.get("campaign_id"),
            )
        else:
            payload = request.get_json(silent=True)
            action = payload.get("action") if isinstance(payload, dict) else None
            operations = {"settings": referential_service.settings, "links": referential_service.import_links,
                          "prepare_questions": referential_service.prepare_questions,
                          "assign_links": referential_service.assign_links,
                          "dispatch": referential_service.dispatch, "reassign": referential_service.reassign,
                          "set_link": referential_service.set_link, "notify_validators": referential_service.notify_validators,
                          "notify": referential_service.notify}
            if not isinstance(action, str) or action not in operations:
                raise InterviewValidationError("Action inconnue.")
            data = operations[action](formation, payload)
        return jsonify({"success": True, "data": data}), 200
    except InterviewError as error:
        return _error_response(error)
    except TrainingCatalogError as error:
        return jsonify({"success": False, "error": str(error)}), error.status_code


@interview_bp.route("/interviews/referentials/<formation>/ranking", methods=["GET", "POST"])
@admin_required(ADMIN_TYPES)
def manage_referential_ranking(formation):
    try:
        _require_planning_admin()
        if request.method == "GET":
            data = ranking_service.get(formation, request.args.get("campaign_id"))
        else:
            payload = request.get_json(silent=True)
            action = payload.get("action") if isinstance(payload, dict) else None
            operations = {"preselect": ranking_service.preselect, "replace": ranking_service.replace,
                          "validate": ranking_service.validate}
            if action not in operations:
                raise InterviewValidationError("Action inconnue.")
            data = operations[action](formation, payload, g.current_admin)
        return jsonify({"success": True, "data": data}), 200
    except InterviewError as error:
        return _error_response(error)
    except TrainingCatalogError as error:
        return jsonify({"success": False, "error": str(error)}), error.status_code


@interview_bp.route("/interviews/capabilities", methods=["GET"])
@admin_required(ADMIN_TYPES, allow_interview_members=True)
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
@admin_required(ADMIN_TYPES, allow_interview_members=True)
def get_interview_campaigns():
    return jsonify(
        {
            "success": True,
            "data": query_service.list_campaigns(
                request.args.get("formation"),
                getattr(g, "current_admin", None),
            ),
        }
    ), 200


@interview_bp.route("/interviews/campaigns", methods=["POST"])
@admin_required(ADMIN_TYPES)
def create_interview_campaign():
    try:
        _require_planning_admin()
        data = request.get_json(silent=True)
        if not isinstance(data, dict) or not data.get("candidature_campaign_id"):
            raise InterviewValidationError("Sélectionnez la campagne de candidature.")
        campaign = management_service.create_campaign(data)
        return jsonify(
            {"success": True, "data": campaign.to_dict()}
        ), 201
    except InterviewError as error:
        return _error_response(error)


@interview_bp.route(
    "/interviews/campaigns/<campaign_id>",
    methods=["PATCH"],
)
@admin_required(ADMIN_TYPES, allow_interview_members=True)
def update_interview_campaign(campaign_id):
    try:
        data = request.get_json(silent=True) or {}
        if set(data) - {"filter_questions"}:
            _require_planning_admin()
        campaign = management_service.update_campaign(
            campaign_id,
            data,
            current_admin=getattr(g, "current_admin", None),
        )
        return jsonify(
            {"success": True, "data": campaign.to_dict()}
        ), 200
    except InterviewError as error:
        return _error_response(error)


@interview_bp.route("/interviews/campaigns/<campaign_id>/question-bank", methods=["GET", "POST", "PUT", "PATCH"])
@admin_required(ADMIN_TYPES)
def manage_interview_question_bank(campaign_id):
    try:
        _require_planning_admin()
        if request.method == "GET":
            data = questionnaire_service.get_bank(campaign_id)
        elif request.method == "PATCH":
            data = questionnaire_service.edit_bank(campaign_id, request.get_json(silent=True))
        else:
            data = questionnaire_service.process_bank(campaign_id, request.get_json(silent=True), save=request.method == "PUT")
            if request.method == "PUT" and data["errors"]:
                return jsonify({"success": False, "error": "La banque contient des erreurs.", "data": data}), 422
        return jsonify({"success": True, "data": data}), 200
    except InterviewError as error:
        return _error_response(error)


@interview_bp.route("/interviews/campaigns/<campaign_id>/questionnaire-config", methods=["PUT"])
@admin_required(ADMIN_TYPES)
def update_interview_questionnaire_config(campaign_id):
    try:
        _require_planning_admin()
        data = questionnaire_service.update_config(campaign_id, request.get_json(silent=True))
        return jsonify({"success": True, "data": data}), 200
    except InterviewError as error:
        return _error_response(error)


@interview_bp.route("/interviews/slots", methods=["GET"])
@admin_required(ADMIN_TYPES, allow_interview_members=True)
def get_interview_slots():
    return jsonify(
        {
            "success": True,
            "data": query_service.list_slots(
                request.args.get("campaignId"),
                getattr(g, "current_admin", None),
            ),
        }
    ), 200


@interview_bp.route("/interviews/slots", methods=["POST"])
@admin_required(ADMIN_TYPES)
def create_interview_slot():
    try:
        _require_planning_admin()
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
        _require_planning_admin()
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
@admin_required(ADMIN_TYPES, allow_interview_members=True)
def get_interview_evaluations():
    page = query_service.evaluation_page(
        request.args,
        getattr(g, "current_admin", None),
    )
    return jsonify({"success": True, **page}), 200


@interview_bp.route("/interviews/evaluations/export", methods=["GET"])
@admin_required(ADMIN_TYPES, allow_interview_members=True)
def export_interview_evaluations():
    csv_content, filename = query_service.export_evaluations_csv(
        request.args,
        getattr(g, "current_admin", None),
    )
    return Response(
        csv_content,
        mimetype="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f"attachment; filename={filename}",
        },
    )


@interview_bp.route(
    "/interviews/evaluations/seed",
    methods=["POST"],
)
@admin_required(ADMIN_TYPES)
def seed_interview_evaluations():
    try:
        _require_planning_admin()
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
@admin_required(ADMIN_TYPES, allow_interview_members=True)
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


@interview_bp.route("/interviews/evaluations/<evaluation_id>/questionnaire", methods=["GET", "POST", "PATCH"])
@admin_required(ADMIN_TYPES, allow_interview_members=True)
def manage_interview_questionnaire(evaluation_id):
    try:
        admin = getattr(g, "current_admin", None)
        if request.method == "GET":
            data = questionnaire_service.get(evaluation_id, admin)
        else:
            operation = questionnaire_service.generate if request.method == "POST" else questionnaire_service.save
            data = operation(evaluation_id, request.get_json(silent=True), admin)
        return jsonify({"success": True, "data": data}), 200
    except InterviewError as error:
        return _error_response(error)


@interview_bp.route("/interviews/evaluations/<evaluation_id>/questionnaire/check", methods=["POST"])
@admin_required(ADMIN_TYPES, allow_interview_members=True)
def check_interview_answer(evaluation_id):
    try:
        data = questionnaire_service.check_answer(evaluation_id, request.get_json(silent=True), g.current_admin)
        return jsonify({"success": True, "data": data}), 200
    except InterviewError as error:
        return _error_response(error)
