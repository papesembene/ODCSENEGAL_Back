from functools import wraps

from flask import g, jsonify, request
from werkzeug.exceptions import Unauthorized

from app.services.auth_service import AuthService


def _extract_bearer_token():
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise Unauthorized("Token d'authentification manquant")

    token = auth_header.split(" ", 1)[1].strip()
    if not token:
        raise Unauthorized("Token d'authentification invalide")

    return token


def admin_required(admin_types=None):
    allowed_types = set(admin_types or [])

    def decorator(view_func):
        @wraps(view_func)
        def wrapped(*args, **kwargs):
            if request.method == "OPTIONS":
                return "", 200

            try:
                token = _extract_bearer_token()
                user = AuthService.verify_token(token)

                if not getattr(user, "is_admin", False):
                    raise Unauthorized("Accès administrateur requis")

                if allowed_types and getattr(user, "admin_type", None) not in allowed_types:
                    raise Unauthorized("Type d'administrateur non autorisé")

                g.current_admin = user
                return view_func(*args, **kwargs)
            except Unauthorized as error:
                return jsonify({
                    "success": False,
                    "error": str(error),
                }), 401

        return wrapped

    return decorator
