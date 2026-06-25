from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required

from app.models.startup_school import StartupSchool
from app.services.catalog_service import (
    CatalogService,
    CatalogValidationError,
)


startup_school_bp = Blueprint("startup_school", __name__)
startup_school_service = CatalogService(
    StartupSchool,
    required_fields=("name",),
    allowed_fields=(
        "name",
        "description",
        "start_date",
        "end_date",
    ),
)


@startup_school_bp.route("/", methods=["GET"])
@jwt_required()
def get_all_startup_schools():
    return jsonify(startup_school_service.list_all())


@startup_school_bp.route("/", methods=["POST"])
@jwt_required()
def create_startup_school():
    try:
        startup_school = startup_school_service.create(
            request.get_json() or {},
        )
        return jsonify(startup_school.to_dict()), 201
    except CatalogValidationError as error:
        return jsonify({"error": str(error)}), 400
