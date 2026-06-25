import os

from flask import Blueprint, current_app, jsonify, request

from app.services.applications import (
    ApplicationPersistenceError,
    ApplicationValidationError,
    DuplicateApplicationError,
    OrangeFabApplicationService,
)
from app.services.email_service import EmailService
from app.utils.request_guards import normalize_email, normalize_phone


orangefab_bp = Blueprint("orangefab", __name__)
UPLOAD_FOLDER = os.path.join("uploads", "orangefab")


def _service():
    return OrangeFabApplicationService(UPLOAD_FOLDER)


def _send_notifications(application):
    try:
        email_service = EmailService(current_app)
        email_data = _service().build_email_data(application)
        email_service.send_confirmation_email(email_data)
        email_service.send_admin_notification(email_data)
    except Exception as error:
        current_app.logger.warning(
            "Erreur lors de l'envoi de l'email Orange Fab: %s",
            error,
        )


@orangefab_bp.route("/check-email", methods=["GET"])
def check_email():
    email = normalize_email(request.args.get("email"))
    if not email:
        return jsonify({"error": "Email requis"}), 400
    try:
        return jsonify({"exists": _service().email_exists(email)})
    except Exception as error:
        return jsonify({"error": str(error)}), 500


@orangefab_bp.route("/check-phone", methods=["GET"])
def check_phone():
    phone = normalize_phone(request.args.get("phone"))
    if not phone:
        return jsonify({"error": "Téléphone requis"}), 400
    try:
        return jsonify({"exists": _service().phone_exists(phone)})
    except Exception as error:
        return jsonify({"error": str(error)}), 500


@orangefab_bp.route("/", methods=["POST"])
def submit_application():
    try:
        application = _service().submit(request.form, request.files)
        _send_notifications(application)
        return jsonify(
            {
                "message": "Candidature soumise avec succès",
                "id": str(application.id),
            }
        ), 201
    except (
        ApplicationValidationError,
        ApplicationPersistenceError,
        DuplicateApplicationError,
    ) as error:
        status = getattr(error, "status_code", 400)
        return jsonify({"error": str(error)}), status
    except Exception as error:
        current_app.logger.error(
            "Erreur lors de la soumission Orange Fab: %s",
            error,
            exc_info=True,
        )
        return jsonify({"error": "Erreur interne du serveur"}), 500
