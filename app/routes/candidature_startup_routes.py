import os

from flask import (
    Blueprint,
    current_app,
    jsonify,
    request,
    send_from_directory,
)

from app.models.startup import Startup
from app.services.applications import (
    ApplicationPersistenceError,
    ApplicationValidationError,
    DuplicateApplicationError,
    StartupApplicationService,
)
from app.services.startup_email_service import StartupEmailService
from app.utils.auth_decorators import admin_required
from app.utils.request_guards import (
    is_request_rate_limited,
    normalize_email,
    normalize_phone,
)


startup_bp = Blueprint("startup", __name__)
UPLOAD_FOLDER = os.path.join("uploads", "startups")


def _service():
    return StartupApplicationService(UPLOAD_FOLDER)


def _validation_response(error):
    status = getattr(error, "status_code", 400)
    return jsonify({"error": str(error)}), status


def _send_notifications(application):
    try:
        email_service = StartupEmailService(current_app)
        email_data = _service().build_email_data(application)
        email_service.send_confirmation_email(email_data)
        email_service.send_admin_notification(email_data)
    except Exception as error:
        current_app.logger.warning(
            "Erreur lors de l'envoi de l'email startup: %s",
            error,
        )


@startup_bp.route("/check-email", methods=["GET"])
def check_email():
    email = normalize_email(request.args.get("email"))
    identifier = email or request.remote_addr
    if is_request_rate_limited(
        "startup_check_email",
        identifier,
        limit=20,
        window=60,
    ):
        return jsonify(
            {"error": "Trop de vérifications, veuillez réessayer plus tard"}
        ), 429
    if not email:
        return jsonify({"error": "Email requis"}), 400
    try:
        return jsonify({"exists": _service().email_exists(email)})
    except Exception as error:
        return jsonify({"error": str(error)}), 500


@startup_bp.route("/check-phone", methods=["GET"])
def check_phone():
    phone = normalize_phone(request.args.get("phone"))
    identifier = phone or request.remote_addr
    if is_request_rate_limited(
        "startup_check_phone",
        identifier,
        limit=20,
        window=60,
    ):
        return jsonify(
            {"error": "Trop de vérifications, veuillez réessayer plus tard"}
        ), 429
    if not phone:
        return jsonify({"error": "Téléphone requis"}), 400
    try:
        return jsonify({"exists": _service().phone_exists(phone)})
    except Exception as error:
        return jsonify({"error": str(error)}), 500


@startup_bp.route("/submit", methods=["GET", "POST"])
def submit_application():
    if request.method == "GET":
        return jsonify(
            {
                "message": "Submit endpoint for Startup Lab",
                "instructions": (
                    "Send POST request with form-data containing all "
                    "required fields"
                ),
                "program": "startup_lab",
            }
        ), 200

    email = normalize_email(request.form.get("email"))
    identifier = email or request.remote_addr
    if is_request_rate_limited(
        "startup_submit",
        identifier,
        limit=5,
        window=300,
    ):
        return jsonify(
            {"error": "Trop de tentatives, veuillez réessayer plus tard"}
        ), 429

    try:
        application = _service().submit(request.form, request.files)
        _send_notifications(application)
        return jsonify(
            {
                "success": True,
                "message": "Candidature soumise avec succès",
                "data": {
                    "id": str(application.id),
                    "companyName": application.companyName,
                    "startup_name": application.startup_name,
                    "program": "startup_lab",
                },
            }
        ), 201
    except (
        ApplicationValidationError,
        ApplicationPersistenceError,
        DuplicateApplicationError,
    ) as error:
        return _validation_response(error)
    except Exception as error:
        current_app.logger.error(
            "Erreur lors de la soumission startup: %s",
            error,
            exc_info=True,
        )
        return jsonify({"error": "Erreur interne du serveur"}), 500


@startup_bp.route("/uploads/<filename>", methods=["GET"])
def get_uploaded_file(filename):
    try:
        return send_from_directory(UPLOAD_FOLDER, filename)
    except FileNotFoundError:
        return jsonify({"error": "Fichier introuvable"}), 404
    except Exception as error:
        return jsonify({"error": str(error)}), 500


@startup_bp.route("/delete/<startup_id>", methods=["DELETE"])
@admin_required({"startups", "super_admin"})
def delete_startup(startup_id):
    service = _service()
    try:
        service.delete(service.get(startup_id))
        return jsonify(
            {"success": True, "message": "Startup supprimée"}
        ), 200
    except Startup.DoesNotExist:
        return jsonify({"error": "Startup introuvable"}), 404
    except Exception as error:
        current_app.logger.error(
            "Erreur suppression startup: %s",
            error,
            exc_info=True,
        )
        return jsonify({"error": "Suppression échouée"}), 500


@startup_bp.route("/list", methods=["GET"])
@admin_required({"startups", "super_admin"})
def list_startups():
    try:
        startups = _service().list_summaries()
        return jsonify(
            {
                "success": True,
                "count": len(startups),
                "startups": startups,
            }
        ), 200
    except Exception as error:
        return jsonify({"error": str(error)}), 500
