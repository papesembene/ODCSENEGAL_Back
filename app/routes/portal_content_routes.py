import os
import uuid

from flask import Blueprint, current_app, g, jsonify, request
from werkzeug.exceptions import BadRequest
from werkzeug.utils import secure_filename

from app.services.portal_content_service import (
    PortalContentService,
    PortalContentServiceError,
)
from app.utils.auth_decorators import admin_required


portal_content_bp = Blueprint("portal_content", __name__)
portal_content_service = PortalContentService()
PORTAL_ADMIN_TYPES = {"cm"}


def _error_response(error):
    return jsonify({"success": False, "error": str(error)}), error.status_code


def _save_portal_image(file_storage):
    if not file_storage or not file_storage.filename:
        raise BadRequest("Image requise")

    extension = file_storage.filename.rsplit(".", 1)[-1].lower()
    allowed_extensions = {"png", "jpg", "jpeg", "gif", "webp"}
    if extension not in allowed_extensions:
        raise BadRequest("Format image invalide")

    filename = secure_filename(file_storage.filename)
    unique_filename = f"{uuid.uuid4().hex}_{filename}"
    relative_folder = os.path.join("uploads", "portal")
    absolute_folder = os.path.join(current_app.root_path, "static", relative_folder)
    os.makedirs(absolute_folder, exist_ok=True)
    file_storage.save(os.path.join(absolute_folder, unique_filename))
    return f"/static/uploads/portal/{unique_filename}"


@portal_content_bp.route("/portal-content/public", methods=["GET"])
def list_public_portal_content():
    return jsonify({
        "success": True,
        "data": portal_content_service.list_public(
            content_type=request.args.get("type"),
            placement=request.args.get("placement", "home"),
        ),
    }), 200


@portal_content_bp.route("/admin/portal-content", methods=["GET"])
@admin_required(PORTAL_ADMIN_TYPES)
def list_admin_portal_content():
    return jsonify({
        "success": True,
        "data": portal_content_service.list_admin(
            content_type=request.args.get("type"),
            status=request.args.get("status"),
        ),
    }), 200


@portal_content_bp.route("/admin/portal-content", methods=["POST"])
@admin_required(PORTAL_ADMIN_TYPES)
def create_portal_content():
    try:
        content = portal_content_service.create(
            request.get_json() or {},
            admin_email=getattr(g.current_admin, "email", ""),
        )
        return jsonify({"success": True, "data": content}), 201
    except PortalContentServiceError as error:
        return _error_response(error)


@portal_content_bp.route("/admin/portal-content/media", methods=["POST"])
@admin_required(PORTAL_ADMIN_TYPES)
def upload_portal_content_media():
    try:
        image_url = _save_portal_image(request.files.get("image"))
        return jsonify({
            "success": True,
            "data": {"imageUrl": image_url},
        }), 201
    except BadRequest as error:
        return jsonify({"success": False, "error": str(error)}), 400


@portal_content_bp.route("/admin/portal-content/<content_id>", methods=["PATCH"])
@admin_required(PORTAL_ADMIN_TYPES)
def update_portal_content(content_id):
    try:
        content = portal_content_service.update(
            content_id,
            request.get_json() or {},
            admin_email=getattr(g.current_admin, "email", ""),
        )
        return jsonify({"success": True, "data": content}), 200
    except PortalContentServiceError as error:
        return _error_response(error)


@portal_content_bp.route("/admin/portal-content/<content_id>", methods=["DELETE"])
@admin_required(PORTAL_ADMIN_TYPES)
def delete_portal_content(content_id):
    try:
        portal_content_service.delete(content_id)
        return jsonify({"success": True}), 200
    except PortalContentServiceError as error:
        return _error_response(error)
