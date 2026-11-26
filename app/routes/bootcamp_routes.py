"""Bootcamp administration (planning admins) and the coach workspace (coaches, own Bootcamps only)."""

from flask import Blueprint, g, jsonify, request

from app.services.bootcamps.results_service import FinalResultsService
from app.services.bootcamps.service import BootcampService
from app.services.interviews.exceptions import InterviewError, InterviewForbiddenError
from app.services.interviews.query_service import InterviewQueryService
from app.services.trainings.schema import TrainingCatalogError
from app.utils.auth_decorators import admin_required


bootcamp_bp = Blueprint("bootcamp_bp", __name__)
service = BootcampService()
results_service = FinalResultsService(service.referentials)
ADMIN_TYPES = {"competences", "super_admin"}


def _respond(operation):
    try:
        return jsonify({"success": True, "data": operation()}), 200
    except InterviewError as error:
        return jsonify({"success": False, "error": str(error)}), error.status_code
    except TrainingCatalogError as error:
        return jsonify({"success": False, "error": str(error)}), error.status_code


def _planning_admin():
    if InterviewQueryService._is_interview_member(getattr(g, "current_admin", None)):
        raise InterviewForbiddenError("La gestion des Bootcamps est réservée aux administrateurs.")


def _payload():
    return request.get_json(silent=True) or {}


@bootcamp_bp.route("/bootcamps/overview", methods=["GET"])
@admin_required(ADMIN_TYPES)
def bootcamps_overview():
    def run():
        _planning_admin()
        return {"rows": service.overview(request.args.get("campaign_id") or None),
                "campaigns": service.referentials.overview_campaigns()}
    return _respond(run)


@bootcamp_bp.route("/bootcamps/referentials/<formation>", methods=["GET", "POST"])
@admin_required(ADMIN_TYPES)
def referential_bootcamps(formation):
    def run():
        _planning_admin()
        campaign_id = request.args.get("campaign_id") or None
        if request.method == "GET":
            return service.detail(formation, campaign_id)
        return service.create(formation, _payload(), campaign_id)
    return _respond(run)


@bootcamp_bp.route("/bootcamps/results", methods=["GET"])
@admin_required(ADMIN_TYPES)
def all_final_results():
    def run():
        _planning_admin()
        return results_service.all_results(request.args.get("campaign_id") or None)
    return _respond(run)


@bootcamp_bp.route("/bootcamps/referentials/<formation>/results", methods=["GET", "POST"])
@admin_required(ADMIN_TYPES)
def final_results(formation):
    def run():
        _planning_admin()
        if request.method == "GET":
            return results_service.get(formation, request.args.get("campaign_id") or None)
        payload = _payload()
        operations = {
            "validate": lambda: results_service.validate(formation, payload, g.current_admin),
            "templates": lambda: results_service.save_templates(formation, payload, g.current_admin),
            "preview": lambda: results_service.preview(formation, payload),
            "send": lambda: results_service.send(formation, payload, g.current_admin),
            "retry": lambda: results_service.retry(formation, payload),
        }
        if payload.get("action") not in operations:
            raise InterviewError("Action inconnue.")
        return operations[payload["action"]]()
    return _respond(run)


@bootcamp_bp.route("/bootcamps/<bootcamp_id>", methods=["PATCH", "DELETE"])
@admin_required(ADMIN_TYPES)
def manage_bootcamp(bootcamp_id):
    def run():
        _planning_admin()
        return service.update(bootcamp_id, _payload()) if request.method == "PATCH" else service.delete(bootcamp_id)
    return _respond(run)


@bootcamp_bp.route("/bootcamps/<bootcamp_id>/<operation>", methods=["POST"])
@admin_required(ADMIN_TYPES)
def bootcamp_operation(bootcamp_id, operation):
    def run():
        _planning_admin()
        operations = {
            "participants": lambda: service.set_participants(bootcamp_id, _payload()),
            "launch": lambda: service.launch(bootcamp_id, _payload(), g.current_admin),
            "retry-invitations": lambda: service.retry_invitations(bootcamp_id),
            "reopen": lambda: service.reopen_results(bootcamp_id, _payload()),
        }
        if operation not in operations:
            raise InterviewError("Action inconnue.")
        return operations[operation]()
    return _respond(run)


@bootcamp_bp.route("/coach/bootcamps", methods=["GET"])
@admin_required(ADMIN_TYPES, allow_interview_members=True)
def coach_bootcamps():
    return _respond(lambda: service.coach_dashboard(g.current_admin))


@bootcamp_bp.route("/coach/bootcamps/<bootcamp_id>", methods=["GET"])
@admin_required(ADMIN_TYPES, allow_interview_members=True)
def coach_bootcamp(bootcamp_id):
    return _respond(lambda: service.coach_bootcamp(bootcamp_id, g.current_admin))


@bootcamp_bp.route("/coach/bootcamps/<bootcamp_id>/participants/<candidate_id>", methods=["PATCH"])
@admin_required(ADMIN_TYPES, allow_interview_members=True)
def coach_decision(bootcamp_id, candidate_id):
    return _respond(lambda: service.coach_decide(bootcamp_id, candidate_id, _payload(), g.current_admin))


@bootcamp_bp.route("/coach/bootcamps/<bootcamp_id>/submit", methods=["POST"])
@admin_required(ADMIN_TYPES, allow_interview_members=True)
def coach_submit(bootcamp_id):
    return _respond(lambda: service.coach_submit(bootcamp_id, _payload(), g.current_admin))
