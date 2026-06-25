from flask import Blueprint, jsonify, request
from werkzeug.exceptions import BadRequest, Unauthorized

from app.services.admin import (
    AdminApplicationReadService,
    AdminDashboardService,
)
from app.services.auth_service import AuthService
from app.utils.auth_decorators import admin_required


admin_bp = Blueprint("admin_bp", __name__)


def _login_error_message(error):
    message = str(error)
    if message.startswith(("401", "Unauthorized")):
        parts = message.split(":", 1)
        message = parts[-1].strip() if len(parts) > 1 else message
    if message.startswith(("401", "Unauthorized")):
        return "Email ou mot de passe incorrect"
    return message


@admin_bp.route("/login", methods=["POST", "OPTIONS"])
def admin_login():
    if request.method == "OPTIONS":
        return "", 200
    try:
        data = request.get_json(silent=True)
        if not data:
            raise BadRequest("Données manquantes")
        email = data.get("email")
        password = data.get("password")
        if not email or not password:
            raise BadRequest("Email et mot de passe requis")

        result = AuthService.login_admin(email, password)
        return jsonify(
            {
                "success": True,
                "message": "Connexion réussie",
                "token": result["token"],
                "user": result["user"],
            }
        ), 200
    except Unauthorized as error:
        return jsonify(
            {
                "success": False,
                "error": _login_error_message(error),
            }
        ), 401
    except BadRequest as error:
        return jsonify(
            {"success": False, "error": str(error)}
        ), 400
    except Exception as error:
        return jsonify(
            {
                "success": False,
                "error": f"Erreur lors de la connexion: {error}",
            }
        ), 500


@admin_bp.route("/competences/candidatures", methods=["GET"])
@admin_required({"competences", "super_admin"})
def get_competences_candidatures():
    try:
        return jsonify(
            AdminApplicationReadService().competence_applications()
        ), 200
    except Exception as error:
        return jsonify(
            {
                "success": False,
                "error": str(error),
                "candidatures": [],
                "total": 0,
            }
        ), 500


@admin_bp.route("/startup/candidatures", methods=["GET"])
@admin_required({"startups", "super_admin"})
def get_startup_candidatures():
    try:
        return jsonify(
            AdminApplicationReadService().startup_applications()
        ), 200
    except Exception as error:
        return jsonify(
            {
                "success": False,
                "error": str(error),
                "data": [],
                "total": 0,
            }
        ), 500


@admin_bp.route("/dashboard/statistics", methods=["GET"])
@admin_required({"competences", "startups", "super_admin"})
def get_dashboard_statistics():
    service = AdminDashboardService()
    try:
        try:
            days = int(request.args.get("days", 7))
        except (TypeError, ValueError):
            days = 7
        return jsonify(
            {"success": True, "data": service.build(days)}
        ), 200
    except Exception as error:
        try:
            return jsonify(
                service.fallback(
                    "Certaines statistiques n'ont pas pu être "
                    f"récupérées: {error}"
                )
            ), 200
        except Exception:
            return jsonify(
                {
                    "success": False,
                    "error": (
                        "Erreur lors de la récupération des "
                        f"statistiques : {error}"
                    ),
                }
            ), 500
