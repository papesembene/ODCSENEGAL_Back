"""Request boundaries and explicit protection of private static document folders."""
from flask import jsonify, request


def install_application_security(app):
    app.config.setdefault("MAX_CONTENT_LENGTH", 260 * 1024 * 1024)
    # Flask defines this key with None by default.
    if app.config["MAX_CONTENT_LENGTH"] is None:
        app.config["MAX_CONTENT_LENGTH"] = 260 * 1024 * 1024

    @app.before_request
    def enforce_boundaries():
        if request.endpoint in {"auth.login", "admin_bp.admin_login", "auth.verify_token", "resource_bp.request_access", "candidature_public.apply"}:
            request.max_content_length = 64 * 1024
        elif request.endpoint in {"auth.register", "auth.update_profile"}:
            request.max_content_length = 32 * 1024 * 1024
        elif request.endpoint == "startup.submit_application":
            request.max_content_length = 22 * 1024 * 1024
        if request.endpoint == "static":
            filename = (request.view_args or {}).get("filename", "").replace("\\", "/").lower()
            if filename.startswith(("uploads/students/", "uploads/startups/", "uploads/corporate/")):
                return jsonify(error="Document privé"), 404
