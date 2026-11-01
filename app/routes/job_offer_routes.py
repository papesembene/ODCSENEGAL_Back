from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required
from app.utils.auth_decorators import admin_required

from app.models.job_offer import JobOffer
from app.services.catalog_service import (
    CatalogService,
    CatalogValidationError,
)


job_offer_bp = Blueprint("job_offer", __name__)
job_offer_service = CatalogService(
    JobOffer,
    required_fields=("title",),
    allowed_fields=(
        "title",
        "description",
        "company_name",
        "location",
    ),
)


@job_offer_bp.route("/", methods=["GET"])
@jwt_required()
def get_all_job_offers():
    return jsonify(job_offer_service.list_all())


@job_offer_bp.route("/", methods=["POST"])
@admin_required({"competences", "startups", "super_admin"})
def create_job_offer():
    try:
        job_offer = job_offer_service.create(request.get_json() or {})
        return jsonify(job_offer.to_dict()), 201
    except CatalogValidationError as error:
        return jsonify({"error": str(error)}), 400
