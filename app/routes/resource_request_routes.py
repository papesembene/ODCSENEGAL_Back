from flask import Blueprint, jsonify, request

from app.services.resource_request_service import ResourceRequestService


resource_bp = Blueprint("resource_bp", __name__)
resource_request_service = ResourceRequestService()


@resource_bp.route("/request-access", methods=["POST"])
def request_access():
    try:
        resource_request_service.create(request.get_json() or {})
        return jsonify({
            "message": "Demande enregistrée avec succès",
        }), 201
    except Exception as error:
        return jsonify({"error": str(error)}), 500


@resource_bp.route("/all", methods=["GET"])
def get_all_requests():
    try:
        return jsonify(resource_request_service.list_all()), 200
    except Exception as error:
        return jsonify({"error": str(error)}), 500
