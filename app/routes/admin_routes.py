import re
import secrets
import string

from mongoengine import NotUniqueError

from flask import Blueprint, jsonify, request, current_app, g
from werkzeug.exceptions import BadRequest, Unauthorized, TooManyRequests
from app.utils.request_guards import is_request_rate_limited, login_credentials
from werkzeug.security import generate_password_hash

from app.services.admin import (
    AdminApplicationReadService,
    AdminDashboardService,
)
from app.services.auth_service import AuthService
from app.services.admin_credentials_email_service import (
    AdminCredentialsEmailService,
)
from app.models.user import User
from app.models.bootcamp import Bootcamp
from app.models.interview import InterviewCampaign, InterviewSlot
from app.services.interviews.member_roles import member_roles, role_query
from app.services.trainings.catalog import get_catalog
from app.utils.auth_decorators import admin_required


admin_bp = Blueprint("admin_bp", __name__)

INTERVIEW_ROLE_LABELS = {
    "filter": "Filtre",
    "validator": "Validateur",
    "coach": "Coach",
    "motivation": "Motivation",
}

ADMIN_TYPE_LABELS = {
    "competences": "Compétences",
    "startups": "Startups",
    "cm": "Community Manager",
    "super_admin": "Super admin",
}


def _member_roles(primary, additional):
    """Primary role first, then the additional roles (e.g. a validator who is also a coach)."""
    if not isinstance(additional, list) or any(role not in INTERVIEW_ROLE_LABELS for role in additional):
        raise BadRequest("Rôle jury invalide")
    return list(dict.fromkeys([primary, *additional]))


def _member_formations(values, roles):
    roles = [roles] if isinstance(roles, str) else roles
    allowed = {training["code"] for training in get_catalog() if training["status"] != "archived"}
    if not isinstance(values, list) or any(not isinstance(code, str) or code not in allowed for code in values):
        raise BadRequest("Sélectionnez des référentiels disponibles.")
    if set(roles) & {"validator", "coach"} and not values:
        raise BadRequest("Sélectionnez au moins un référentiel pour ce rôle.")
    return list(dict.fromkeys(values))


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
        "roles": member_roles(profile_data),
        "formations": profile_data.get("interview_formations") or [],
        "role_label": INTERVIEW_ROLE_LABELS.get(
            profile_data.get("interview_role"),
            profile_data.get("interview_role") or "-",
        ),
        "credentials_email_sent": bool(
            profile_data.get("credentials_email_sent")
        ),
        "credentials_email_message": profile_data.get(
            "credentials_email_message",
            "",
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


def _send_member_credentials(user, temporary_password, role):
    role_label = INTERVIEW_ROLE_LABELS.get(role, role or "-")
    result = AdminCredentialsEmailService().send_credentials(
        user=user,
        temporary_password=temporary_password,
        role_label=role_label,
    )
    profile_data = user.profile_data or {}
    profile_data["credentials_email_sent"] = bool(result.get("sent"))
    profile_data["credentials_email_message"] = result.get("message", "")
    user.profile_data = profile_data
    user.save()
    return result


@admin_bp.route("/login", methods=["POST", "OPTIONS"])
def admin_login():
    if request.method == "OPTIONS":
        return "", 200
    try:
        data = request.get_json(silent=True)
        if not data:
            raise BadRequest("Données manquantes")
        email, password = login_credentials(data)
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
    except TooManyRequests as error:
        return jsonify(success=False, error=error.description), 429
    except Exception as error:
        current_app.logger.exception("Echec de connexion administrateur")
        return jsonify(
            {
                "success": False,
                "error": "Erreur interne du serveur",
            }
        ), 500


@admin_bp.route("/me/password", methods=["PATCH"])
@admin_required(allow_interview_members=True)
def change_my_password():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(success=False, error="Renseignez les deux mots de passe."), 400
    current = data.get("current_password")
    new = data.get("new_password")
    if not isinstance(current, str) or not 1 <= len(current) <= 1024:
        return jsonify(success=False, error="Renseignez votre mot de passe actuel."), 400
    if not isinstance(new, str) or not 8 <= len(new) <= 1024 or not new.strip():
        return jsonify(success=False, error="Le nouveau mot de passe doit contenir entre 8 et 1024 caractères."), 400
    if current == new:
        return jsonify(success=False, error="Choisissez un mot de passe différent du mot de passe actuel."), 400

    user = g.current_admin
    if is_request_rate_limited("admin_password_change", str(user.id), limit=10, window=300):
        return jsonify(success=False, error="Trop de tentatives. Réessayez dans quelques minutes."), 429
    if not user.check_password(current):
        return jsonify(success=False, error="Le mot de passe actuel est incorrect."), 400

    updated = User.objects(
        id=user.id, is_active=True, is_admin=True, password_hash=user.password_hash,
    ).modify(
        new=True,
        set__password_hash=generate_password_hash(new),
        set__password_session_version=secrets.token_urlsafe(24),
    )
    if updated is None:
        return jsonify(success=False, error="Le compte a changé. Reconnectez-vous et réessayez."), 409

    token = AuthService.generate_token(updated)["token"]
    response = jsonify(success=True, token=token, message="Mot de passe modifié.")
    response.headers["Cache-Control"] = "no-store"
    return response


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
            user.password_session_version = secrets.token_urlsafe(24)

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
                    __raw__=role_query(role),
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

        roles = _member_roles(role, data.get("additional_roles", []))
        formations = _member_formations(data.get("formations", []), roles)

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
                "interview_roles": roles,
                "interview_formations": formations,
            },
        )
        user.save()
        email_result = _send_member_credentials(user, password, role)

        return jsonify(
            {
                "success": True,
                "message": "Membre du jury créé avec succès",
                "user": AuthService.user_to_safe_json(user),
                "data": _serialize_interview_member(user),
                "role_label": INTERVIEW_ROLE_LABELS[role],
                "temporary_password": password,
                "credentials_email_sent": email_result.get("sent", False),
                "credentials_email_message": email_result.get("message", ""),
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


VALIDATOR_IMPORT_LIMIT = 200
_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


IMPORT_ROLE_WORDS = {
    "validateur": ["validator"], "validator": ["validator"],
    "coach": ["coach"],
    "validateur et coach": ["validator", "coach"], "validateur + coach": ["validator", "coach"],
    "validateur/coach": ["validator", "coach"], "les deux": ["validator", "coach"], "coach et validateur": ["coach", "validator"],
}
ROLE_NAMES = {"validator": "validateur", "coach": "coach"}


def _import_roles(value, default_role):
    text = " ".join(str(value or "").strip().lower().split())
    if not text:
        return [default_role]
    return IMPORT_ROLE_WORDS.get(text)


def _plan_validator_import(rows, formation, default_role="validator"):
    """Decide, row by row, whether to create a member, add roles or the referential, or reject the row."""
    if not isinstance(rows, list) or not 1 <= len(rows) <= VALIDATOR_IMPORT_LIMIT:
        raise BadRequest(f"Importez entre 1 et {VALIDATOR_IMPORT_LIMIT} membres.")
    if default_role not in ROLE_NAMES:
        raise BadRequest("Rôle par défaut invalide.")
    _member_formations([formation], default_role)
    plan, seen = [], set()
    for index, row in enumerate(rows):
        row = row if isinstance(row, dict) else {}
        first_name = str(row.get("first_name") or "").strip()[:80]
        last_name = str(row.get("last_name") or "").strip()[:80]
        email = str(row.get("email") or "").strip().lower()[:254]
        roles = _import_roles(row.get("role"), default_role)
        entry = {"index": index, "first_name": first_name, "last_name": last_name, "email": email, "roles": roles or []}
        if not first_name or not last_name or not _EMAIL_PATTERN.match(email):
            plan.append({**entry, "action": "error", "message": "Prénom, nom et adresse e-mail valide requis."})
            continue
        if not roles:
            plan.append({**entry, "action": "error", "message": "Rôle inconnu : indiquez validateur, coach ou validateur et coach."})
            continue
        if email in seen:
            plan.append({**entry, "action": "error", "message": "Adresse en double dans le fichier."})
            continue
        seen.add(email)
        label = " et ".join(ROLE_NAMES[role] for role in roles)
        user = User.objects(email=email).first()
        if not user:
            plan.append({**entry, "action": "create", "message": f"Compte {label} créé, identifiants envoyés par e-mail."})
            continue
        profile = user.profile_data or {}
        if profile.get("admin_scope") != "interview_member":
            plan.append({**entry, "action": "error", "message": "Cette adresse appartient à un compte administrateur."})
            continue
        missing = [role for role in roles if role not in member_roles(profile)]
        attached = formation in (profile.get("interview_formations") or [])
        if not missing and attached:
            plan.append({**entry, "id": str(user.id), "action": "unchanged", "message": f"Déjà {label} de ce référentiel."})
        else:
            changes = [*(f"rôle {ROLE_NAMES[role]} ajouté" for role in missing), *([] if attached else ["référentiel ajouté"])]
            plan.append({**entry, "id": str(user.id), "action": "attach", "message": "Compte existant : " + ", ".join(changes) + "."})
    return plan


@admin_bp.route("/interview-members/import", methods=["POST", "OPTIONS"])
@admin_required({"competences", "super_admin"})
def import_interview_validators():
    """Preview (preview=true) then import validators and/or coaches from an Excel sheet for one referential."""
    try:
        if request.method == "OPTIONS":
            return "", 200
        data = request.get_json(silent=True) or {}
        formation = data.get("formation")
        plan = _plan_validator_import(data.get("rows"), formation, data.get("default_role") or "validator")
        if data.get("preview") is not False:
            return jsonify({"success": True, "data": {"preview": True, "rows": plan}}), 200
        for entry in plan:
            if entry["action"] == "attach":
                user = User.objects(id=entry["id"]).get()
                profile = user.profile_data or {}
                profile["interview_formations"] = list(dict.fromkeys([*(profile.get("interview_formations") or []), formation]))
                profile["interview_roles"] = list(dict.fromkeys([*member_roles(profile), *entry["roles"]]))
                user.profile_data = profile
                user.save()
            elif entry["action"] == "create":
                password = _generate_temporary_password()
                user = User(
                    email=entry["email"], password_hash=generate_password_hash(password),
                    first_name=entry["first_name"], last_name=entry["last_name"],
                    is_active=True, email_verified=True, is_admin=True, admin_type="competences", profile_type="student",
                    profile_data={"admin_scope": "interview_member", "interview_role": entry["roles"][0],
                                  "interview_roles": entry["roles"], "interview_formations": [formation]},
                )
                try:
                    user.save()
                except NotUniqueError:
                    entry.update(action="error", message="Un compte vient d’être créé avec cette adresse.")
                    continue
                entry["id"] = str(user.id)
                result = _send_member_credentials(user, password, entry["roles"][0])
                if not result.get("sent"):
                    entry["message"] = "Compte créé, mais l’e-mail d’identifiants n’est pas parti : renvoyez-le depuis Paramètres."
        return jsonify({"success": True, "data": {"preview": False, "rows": plan}}), 200
    except BadRequest as error:
        return jsonify({"success": False, "error": str(error.description)}), 400


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
        if role or "formations" in data or "additional_roles" in data:
            profile_data = dict(user.profile_data or {})
            current_role = profile_data.get("interview_role")
            role = role or current_role
            if role not in INTERVIEW_ROLE_LABELS:
                raise BadRequest("Rôle jury invalide")
            roles = _member_roles(role, data["additional_roles"]) if "additional_roles" in data else \
                list(dict.fromkeys([role, *(item for item in member_roles(profile_data) if item != current_role)]))
            formations = _member_formations(data["formations"], roles) if "formations" in data else profile_data.get("interview_formations", [])
            if set(roles) - set(member_roles(profile_data)) & {"validator", "coach"} and not formations:
                raise BadRequest("Sélectionnez au moins un référentiel pour ce rôle.")
            assignments = InterviewCampaign.objects(
                referential_key__ne=None,
                __raw__={f"distribution.validators.{user.id}.candidates.0": {"$exists": True}},
            ).distinct("formation")
            if assignments and ("validator" not in roles or set(assignments) - set(formations)):
                raise BadRequest("Ce validateur a déjà des candidats dans un des référentiels retirés.")
            coached = Bootcamp.objects(coach_ids=str(user.id), status__ne="submitted").distinct("formation")
            if coached and ("coach" not in roles or set(coached) - set(formations)):
                raise BadRequest("Ce coach encadre un Bootcamp en cours dans un des référentiels retirés.")
            user.profile_data = {**profile_data, "interview_role": role, "interview_roles": roles, "interview_formations": formations}

        if "is_active" in data:
            user.is_active = bool(data["is_active"])

        temporary_password = None
        email_result = None
        if data.get("reset_password"):
            temporary_password = _generate_temporary_password()
            user.password_hash = generate_password_hash(temporary_password)
            user.password_session_version = secrets.token_urlsafe(24)

        first_name = data.get("first_name")
        last_name = data.get("last_name")
        if first_name is not None:
            user.first_name = first_name.strip()
        if last_name is not None:
            user.last_name = last_name.strip()

        user.save()
        if temporary_password:
            role = (user.profile_data or {}).get("interview_role")
            email_result = _send_member_credentials(
                user,
                temporary_password,
                role,
            )

        return jsonify({
            "success": True,
            "message": (
                "Mot de passe réinitialisé"
                if temporary_password
                else "Membre du jury mis à jour"
            ),
            "data": _serialize_interview_member(user),
            "temporary_password": temporary_password,
            "credentials_email_sent": (
                email_result.get("sent", False) if email_result else None
            ),
            "credentials_email_message": (
                email_result.get("message", "") if email_result else ""
            ),
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
