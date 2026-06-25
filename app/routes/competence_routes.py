from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required

from app.models.competence import Competence
from app.services.catalog_service import (
    CatalogService,
    CatalogValidationError,
)


competence_bp = Blueprint("competence", __name__)
competence_service = CatalogService(
    Competence,
    required_fields=("name",),
    allowed_fields=("name", "description", "level"),
)


@competence_bp.route("/", methods=["GET"])
@jwt_required()
def get_all_competences():
    return jsonify(competence_service.list_all())


@competence_bp.route("/", methods=["POST"])
@jwt_required()
def create_competence():
    try:
        competence = competence_service.create(request.get_json() or {})
        return jsonify(competence.to_dict()), 201
    except CatalogValidationError as error:
        return jsonify({"error": str(error)}), 400
