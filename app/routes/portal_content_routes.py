from flask import Blueprint, g, jsonify, request

from app.services.portal_content_service import (
    PortalContentService,
    PortalContentServiceError,
)
from app.utils.auth_decorators import admin_required


portal_content_bp = Blueprint("portal_content", __name__)
portal_content_service = PortalContentService()


def _error_response(error):
    return jsonify({"success": False, "error": str(error)}), error.status_code


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
@admin_required({"super_admin"})
def list_admin_portal_content():
    return jsonify({
        "success": True,
        "data": portal_content_service.list_admin(
            content_type=request.args.get("type"),
            status=request.args.get("status"),
        ),
    }), 200


@portal_content_bp.route("/admin/portal-content", methods=["POST"])
@admin_required({"super_admin"})
def create_portal_content():
    try:
        content = portal_content_service.create(
            request.get_json() or {},
            admin_email=getattr(g.current_admin, "email", ""),
        )
        return jsonify({"success": True, "data": content}), 201
    except PortalContentServiceError as error:
        return _error_response(error)


@portal_content_bp.route("/admin/portal-content/<content_id>", methods=["PATCH"])
@admin_required({"super_admin"})
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
@admin_required({"super_admin"})
def delete_portal_content(content_id):
    try:
        portal_content_service.delete(content_id)
        return jsonify({"success": True}), 200
    except PortalContentServiceError as error:
        return _error_response(error)
