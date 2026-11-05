"""Public referentials and role-protected catalogue management."""

from flask import Blueprint, g, jsonify, request
from werkzeug.exceptions import BadRequest

from app.services.public_image_service import save_public_image
from app.services.trainings.catalog import get_catalog
from app.services.trainings.schema import TrainingCatalogError
from app.services.trainings.service import TrainingCatalogService
from app.services.trainings.regional_eligibility import regional_rules
from app.utils.auth_decorators import admin_required

training_bp = Blueprint("training_catalog", __name__)
MANAGERS = {"super_admin", "competences"}
service = TrainingCatalogService()


def response(data=None, status=200, error=None, **metadata):
    payload = {"success": error is None, "error": error} if error else {"success": True, "data": data}
    payload.update(metadata)
    result = jsonify(payload)
    result.headers["Cache-Control"] = "no-store"
    return result, status


@training_bp.route("/trainings", methods=["GET"])
def public_catalog():
    return response([item for item in get_catalog() if item["status"] == "published"], regionalRules=regional_rules())


@training_bp.route("/admin/trainings", methods=["GET"])
@admin_required(MANAGERS, allow_interview_members=True)
def admin_catalog():
    return response(get_catalog(force=True), regionalRules=regional_rules())


@training_bp.route("/admin/trainings", methods=["POST"])
@admin_required(MANAGERS)
def create_training():
    try:
        return response(service.create(request.get_json(silent=True) or {}, g.current_admin.email), 201)
    except TrainingCatalogError as error:
        return response(status=error.status_code, error=str(error))


@training_bp.route("/admin/trainings/media", methods=["POST"])
@admin_required(MANAGERS)
def upload_training_image():
    try:
        return response({"imageUrl": save_public_image(request.files.get("image"), "trainings")}, 201)
    except BadRequest as error:
        return response(status=400, error=error.description)


@training_bp.route("/admin/trainings/<code>", methods=["PATCH", "DELETE"])
@admin_required(MANAGERS)
def update_training(code):
    try:
        data = request.get_json(silent=True) or {}
        if request.method == "DELETE":
            if not isinstance(data, dict):
                raise TrainingCatalogError("Version du référentiel requise.")
            result = service.archive(code, data.get("version"), g.current_admin.email)
        else:
            result = service.update(code, data, g.current_admin.email)
        return response(result)
    except TrainingCatalogError as error:
        return response(status=error.status_code, error=str(error))
