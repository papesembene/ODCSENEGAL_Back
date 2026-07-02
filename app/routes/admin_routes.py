from flask import Blueprint, jsonify, request
from werkzeug.exceptions import BadRequest, Unauthorized
from werkzeug.security import generate_password_hash

from app.services.admin import (
    AdminApplicationReadService,
    AdminDashboardService,
)
from app.services.auth_service import AuthService
from app.models.user import User
from app.utils.auth_decorators import admin_required


admin_bp = Blueprint("admin_bp", __name__)

INTERVIEW_ROLE_LABELS = {
    "filter": "Filtre",
    "validator": "Validation",
    "motivation": "Motivation",
}


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


@admin_bp.route("/interview-members", methods=["POST", "OPTIONS"])
@admin_required({"competences", "super_admin"})
def create_interview_member():
    try:
        if request.method == "OPTIONS":
            return "", 200

        data = request.get_json(silent=True)
        if not data:
            raise BadRequest("Données manquantes")

        email = (data.get("email") or "").strip().lower()
        first_name = (data.get("first_name") or "").strip()
        last_name = (data.get("last_name") or "").strip()
        role = (data.get("role") or "").strip()
        password = (data.get("password") or "test123").strip()

        if not first_name or not last_name or not email or not role:
            raise BadRequest(
                "Les champs prénom, nom, email et rôle sont requis"
            )

        if role not in INTERVIEW_ROLE_LABELS:
            raise BadRequest("Rôle jury invalide")

        if User.objects(email=email).first():
            raise BadRequest("Un utilisateur avec cet email existe déjà")

        user = User(
            email=email,
            password_hash=generate_password_hash(password),
            first_name=first_name,
            last_name=last_name,
            is_active=True,
            email_verified=True,
            is_admin=True,
            admin_type="competences",
            profile_type="student",
            profile_data={
                "admin_scope": "interview_member",
                "interview_role": role,
            },
        )
        user.save()

        return jsonify(
            {
                "success": True,
                "message": "Membre du jury créé avec succès",
                "user": AuthService.user_to_safe_json(user),
                "role_label": INTERVIEW_ROLE_LABELS[role],
            }
        ), 201
    except BadRequest as error:
        return jsonify({"success": False, "error": str(error)}), 400
    except Exception as error:
        return jsonify(
            {
                "success": False,
                "error": (
                    "Erreur lors de la création du membre du jury: "
                    f"{error}"
                ),
            }
        ), 500
