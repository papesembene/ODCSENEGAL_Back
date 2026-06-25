from flask import Blueprint, jsonify, request

from app.services.contact_service import ContactService


contact_bp = Blueprint("contact", __name__)
contact_service = ContactService()


@contact_bp.route("/", methods=["POST", "OPTIONS"])
def contact():
    if request.method == "OPTIONS":
        return "", 200

    try:
        contact_service.send(request.get_json() or {})
        return jsonify({"message": "Message envoyé avec succès"}), 200
    except Exception as error:
        return jsonify({
            "error": f"Échec de l'envoi de l'email: {error}",
        }), 500
