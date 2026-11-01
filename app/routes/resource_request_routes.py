from flask import Blueprint, jsonify, request, current_app
from mongoengine.errors import ValidationError

from app.services.resource_request_service import ResourceRequestService
from app.utils.auth_decorators import admin_required
from app.utils.request_guards import is_request_rate_limited


resource_bp = Blueprint("resource_bp", __name__)
resource_request_service = ResourceRequestService()


@resource_bp.route("/request-access", methods=["POST"])
def request_access():
    if is_request_rate_limited("resource_request_ip", request.remote_addr, limit=10, window=300):
        return jsonify(error="Trop de tentatives, veuillez réessayer plus tard"), 429
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error="Objet JSON requis"), 400
    try:
        resource_request_service.create(data)
        return jsonify({
            "message": "Demande enregistrée avec succès",
        }), 201
    except ValidationError:
        return jsonify(error="Demande invalide"), 400
    except Exception:
        current_app.logger.exception("Echec de creation d'une demande de ressource")
        return jsonify(error="Erreur interne du serveur"), 500


@resource_bp.route("/all", methods=["GET"])
@admin_required({"competences", "startups", "super_admin"})
def get_all_requests():
    try:
        return jsonify(resource_request_service.list_all()), 200
    except Exception as error:
        return jsonify({"error": str(error)}), 500
