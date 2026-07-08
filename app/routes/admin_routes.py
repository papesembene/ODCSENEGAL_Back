import secrets
import string

from flask import Blueprint, jsonify, request
from werkzeug.exceptions import BadRequest, Unauthorized
from werkzeug.security import generate_password_hash

from app.services.admin import (
    AdminApplicationReadService,
    AdminDashboardService,
)
from app.services.auth_service import AuthService
from app.models.user import User
from app.models.interview import InterviewSlot
from app.utils.auth_decorators import admin_required


admin_bp = Blueprint("admin_bp", __name__)

INTERVIEW_ROLE_LABELS = {
    "filter": "Filtre",
    "validator": "Validation",
    "motivation": "Motivation",
}

ADMIN_TYPE_LABELS = {
    "competences": "Compétences",
    "startups": "Startups",
    "cm": "Community Manager",
    "super_admin": "Super admin",
}


def _generate_temporary_password(length=12):
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def _serialize_interview_member(user):
    profile_data = user.profile_data or {}
    return {
        "id": str(user.id),
        "email": user.email,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "is_active": user.is_active,
        "role": profile_data.get("interview_role"),
        "role_label": INTERVIEW_ROLE_LABELS.get(
            profile_data.get("interview_role"),
            profile_data.get("interview_role") or "-",
        ),
        "created_at": user.created_at.isoformat() if user.created_at else None,
    }


def _interview_member_query():
    return User.objects(
        is_admin=True,
        admin_type="competences",
        __raw__={"profile_data.admin_scope": "interview_member"},
    )


def _admin_profile_query():
    return User.objects(
        is_admin=True,
        __raw__={"profile_data.admin_scope": {"$ne": "interview_member"}},
    )


def _serialize_admin_profile(user):
    return {
        "id": str(user.id),
        "email": user.email,
        "first_name": user.first_name or "",
        "last_name": user.last_name or "",
        "admin_type": user.admin_type,
        "admin_type_label": ADMIN_TYPE_LABELS.get(
            user.admin_type,
            user.admin_type or "-",
        ),
        "is_active": user.is_active,
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "last_login": user.last_login.isoformat() if user.last_login else None,
    }


def _member_has_slot_assignments(member_id):
    member_id = str(member_id)
    return bool(
        InterviewSlot.objects(
            __raw__={
                "$or": [
                    {"assigned_filter_ids": member_id},
                    {"assigned_jury_ids": member_id},
                    {"assigned_validator_ids": member_id},
                    {"assigned_motivation_ids": member_id},
                ]
            },
        ).only("id").first()
    )


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


@admin_bp.route("/admin-profiles", methods=["GET", "POST", "OPTIONS"])
@admin_required({"super_admin"})
def manage_admin_profiles():
    try:
        if request.method == "OPTIONS":
            return "", 200
        if request.method == "GET":
            admin_type = (request.args.get("type") or "").strip()
            query = _admin_profile_query()
            if admin_type in ADMIN_TYPE_LABELS:
                query = query.filter(admin_type=admin_type)
            profiles = [
                _serialize_admin_profile(user)
                for user in query.order_by("-created_at")
            ]
            return jsonify({
                "success": True,
                "data": profiles,
                "total": len(profiles),
            }), 200

        data = request.get_json(silent=True) or {}
        email = (data.get("email") or "").strip().lower()
        first_name = (data.get("first_name") or "").strip()
        last_name = (data.get("last_name") or "").strip()
        admin_type = (data.get("admin_type") or "").strip()
        password = (data.get("password") or "").strip() or _generate_temporary_password()

        if not email or not first_name or not last_name or not admin_type:
            raise BadRequest("Prénom, nom, email et profil sont requis")
        if admin_type not in ADMIN_TYPE_LABELS:
            raise BadRequest("Profil administrateur invalide")
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
            admin_type=admin_type,
            profile_type="student",
            profile_data={},
        )
        user.save()

        return jsonify({
            "success": True,
            "message": "Profil administrateur créé",
            "data": _serialize_admin_profile(user),
            "temporary_password": password,
        }), 201
    except BadRequest as error:
        return jsonify({"success": False, "error": str(error)}), 400
    except Exception as error:
        return jsonify({
            "success": False,
            "error": f"Erreur lors de la gestion des profils: {error}",
        }), 500


@admin_bp.route("/admin-profiles/<profile_id>", methods=["PATCH", "DELETE", "OPTIONS"])
@admin_required({"super_admin"})
def manage_admin_profile(profile_id):
    try:
        if request.method == "OPTIONS":
            return "", 200

        user = _admin_profile_query().filter(id=profile_id).first()
        if not user:
            return jsonify({
                "success": False,
                "error": "Profil administrateur non trouvé",
            }), 404

        if request.method == "DELETE":
            user.is_active = False
            user.save()
            return jsonify({
                "success": True,
                "message": "Profil administrateur désactivé",
                "data": _serialize_admin_profile(user),
            }), 200

        data = request.get_json(silent=True) or {}
        temporary_password = None
        if data.get("reset_password"):
            temporary_password = _generate_temporary_password()
            user.password_hash = generate_password_hash(temporary_password)

        admin_type = (data.get("admin_type") or "").strip()
        if admin_type:
            if admin_type not in ADMIN_TYPE_LABELS:
                raise BadRequest("Profil administrateur invalide")
            user.admin_type = admin_type
        if "is_active" in data:
            user.is_active = bool(data["is_active"])
        if data.get("first_name") is not None:
            user.first_name = data.get("first_name", "").strip()
        if data.get("last_name") is not None:
            user.last_name = data.get("last_name", "").strip()

        user.save()
        return jsonify({
            "success": True,
            "message": "Mot de passe réinitialisé" if temporary_password else "Profil administrateur mis à jour",
            "data": _serialize_admin_profile(user),
            "temporary_password": temporary_password,
        }), 200
    except BadRequest as error:
        return jsonify({"success": False, "error": str(error)}), 400
    except Exception as error:
        return jsonify({
            "success": False,
            "error": f"Erreur lors de la mise à jour du profil: {error}",
        }), 500


@admin_bp.route("/interview-members", methods=["GET", "POST", "OPTIONS"])
@admin_required({"competences", "super_admin"})
def create_interview_member():
    try:
        if request.method == "OPTIONS":
            return "", 200
        if request.method == "GET":
            role = (request.args.get("role") or "").strip()
            query = _interview_member_query()
            if role in INTERVIEW_ROLE_LABELS:
                query = query.filter(
                    __raw__={"profile_data.interview_role": role},
                )

            members = [
                _serialize_interview_member(user)
                for user in query.order_by("-created_at")
            ]
            return jsonify({
                "success": True,
                "data": members,
                "total": len(members),
            }), 200

        data = request.get_json(silent=True)
        if not data:
            raise BadRequest("Données manquantes")

        email = (data.get("email") or "").strip().lower()
        first_name = (data.get("first_name") or "").strip()
        last_name = (data.get("last_name") or "").strip()
        role = (data.get("role") or "").strip()
        password = (data.get("password") or "").strip()
        if not password:
            password = _generate_temporary_password()

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
                "temporary_password": password,
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


@admin_bp.route("/interview-members/<member_id>", methods=["PATCH", "OPTIONS"])
@admin_required({"competences", "super_admin"})
def update_interview_member(member_id):
    try:
        if request.method == "OPTIONS":
            return "", 200

        data = request.get_json(silent=True) or {}
        user = _interview_member_query().filter(id=member_id).first()
        if not user:
            return jsonify({
                "success": False,
                "error": "Membre du jury non trouvé",
            }), 404

        role = (data.get("role") or "").strip()
        if role:
            if role not in INTERVIEW_ROLE_LABELS:
                raise BadRequest("Rôle jury invalide")
            profile_data = user.profile_data or {}
            profile_data["interview_role"] = role
            user.profile_data = profile_data

        if "is_active" in data:
            user.is_active = bool(data["is_active"])

        first_name = data.get("first_name")
        last_name = data.get("last_name")
        if first_name is not None:
            user.first_name = first_name.strip()
        if last_name is not None:
            user.last_name = last_name.strip()

        user.save()
        return jsonify({
            "success": True,
            "message": "Membre du jury mis à jour",
            "data": _serialize_interview_member(user),
        }), 200
    except BadRequest as error:
        return jsonify({"success": False, "error": str(error)}), 400
    except Exception as error:
        return jsonify({
            "success": False,
            "error": (
                "Erreur lors de la mise à jour du membre du jury: "
                f"{error}"
            ),
        }), 500


@admin_bp.route("/interview-members/<member_id>", methods=["DELETE", "OPTIONS"])
@admin_required({"competences", "super_admin"})
def delete_interview_member(member_id):
    try:
        if request.method == "OPTIONS":
            return "", 200

        user = _interview_member_query().filter(id=member_id).first()
        if not user:
            return jsonify({
                "success": False,
                "error": "Membre du jury non trouvé",
            }), 404

        if _member_has_slot_assignments(member_id):
            user.is_active = False
            user.save()
            return jsonify({
                "success": True,
                "message": (
                    "Ce membre est déjà affecté à un créneau. "
                    "Il a été désactivé pour préserver l'historique."
                ),
                "data": _serialize_interview_member(user),
                "deleted": False,
            }), 200

        user.delete()
        return jsonify({
            "success": True,
            "message": "Membre du jury supprimé",
            "deleted": True,
        }), 200
    except Exception as error:
        return jsonify({
            "success": False,
            "error": (
                "Erreur lors de la suppression du membre du jury: "
                f"{error}"
            ),
        }), 500
