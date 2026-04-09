from flask import Blueprint, request, jsonify
from app.models.resource_request import ResourceRequest

resource_bp = Blueprint('resource_bp', __name__)

# ✅ Route pour recevoir une demande d'accès
@resource_bp.route('/request-access', methods=['POST'])
def request_access():
    try:
        data = request.get_json()
        print(">> Données reçues :", data)

        request_doc = ResourceRequest(
            startup_name=data.get("startupName"),
            contact_person=data.get("contactPerson"),
            email=data.get("email"),
            phone=data.get("phone"),
            resource=data.get("resource"),
            requested_date=data.get("requestedDate"),
            requested_time=data.get("requestedTime", ""),
            details=data.get("details"),
            accept_terms=data.get("acceptTerms", False)
        )
        request_doc.save()

        print(">> Document sauvegardé :", request_doc.to_dict())
        return jsonify({"message": "Demande enregistrée avec succès"}), 201

    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ✅ Route pour récupérer toutes les demandes
@resource_bp.route('/all', methods=['GET'])
def get_all_requests():
    try:
        all_requests = ResourceRequest.objects().order_by('-created_at')
        return jsonify([req.to_dict() for req in all_requests]), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
