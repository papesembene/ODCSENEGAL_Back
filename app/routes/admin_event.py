from datetime import datetime

from flask import Blueprint, jsonify, request

from app.services.events.event_service import EventService, EventServiceError
from app.utils.auth_decorators import admin_required


admin_event_bp = Blueprint("admin_event", __name__)
event_service = EventService()
ADMIN_TYPES = {"competences", "startups", "super_admin"}


def _serialize(event):
    data = event.to_dict()
    data.update(
        {
            "currentParticipants": data.get("registration_count", 0),
            "maxParticipants": event.max_participants,
            "status": (
                "upcoming"
                if event.date and event.date >= datetime.utcnow()
                else "completed"
            ),
        }
    )
    return data


@admin_event_bp.route("/events", methods=["GET"])
@admin_required(ADMIN_TYPES)
def list_admin_events():
    events = [_serialize(event) for event in event_service.list_documents()]
    return jsonify({"success": True, "data": events}), 200


@admin_event_bp.route("/events", methods=["POST"])
@admin_required(ADMIN_TYPES)
def create_admin_event():
    try:
        event = event_service.create(request.get_json() or {})
        return jsonify(
            {"success": True, "data": _serialize(event)}
        ), 201
    except EventServiceError as error:
        return jsonify({"success": False, "error": str(error)}), (
            error.status_code
        )


@admin_event_bp.route("/events", methods=["PATCH"])
@admin_required(ADMIN_TYPES)
def update_admin_event():
    data = request.get_json() or {}
    event_id = data.pop("id", None)
    if not event_id:
        return jsonify(
            {"success": False, "error": "Identifiant requis"}
        ), 400
    try:
        event = event_service.update(event_id, data)
        return jsonify(
            {"success": True, "data": _serialize(event)}
        ), 200
    except EventServiceError as error:
        return jsonify({"success": False, "error": str(error)}), (
            error.status_code
        )


@admin_event_bp.route("/events", methods=["DELETE"])
@admin_required(ADMIN_TYPES)
def delete_admin_event():
    event_id = request.args.get("id")
    if not event_id:
        return jsonify(
            {"success": False, "error": "Identifiant requis"}
        ), 400
    try:
        event_service.delete(event_id)
        return jsonify({"success": True}), 200
    except EventServiceError as error:
        return jsonify({"success": False, "error": str(error)}), (
            error.status_code
        )
