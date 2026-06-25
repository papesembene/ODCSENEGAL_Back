from flask import Blueprint, current_app, jsonify, request

from app.services.events.event_service import (
    EventService,
    EventServiceError,
)
from app.utils.auth_decorators import admin_required


events = Blueprint("events", __name__)
event_service = EventService()


def event_error_response(error):
    return jsonify({"error": str(error)}), error.status_code


@events.route("/", methods=["GET"])
def get_events():
    return jsonify({"events": event_service.list_all()}), 200


@events.route("/upcoming", methods=["GET"])
def get_upcoming_events():
    return jsonify({"events": event_service.list_upcoming()}), 200


@events.route("/past", methods=["GET"])
def get_past_events():
    return jsonify({"events": event_service.list_past()}), 200


@events.route("/<event_id>", methods=["GET"])
def get_event(event_id):
    try:
        return jsonify(event_service.get(event_id).to_dict()), 200
    except EventServiceError as error:
        return event_error_response(error)


@events.route("/", methods=["POST"])
@admin_required({"competences", "startups", "super_admin"})
def add_event():
    is_multipart = (
        request.content_type
        and request.content_type.startswith("multipart/form-data")
    )
    data = request.form.to_dict() if is_multipart else request.get_json() or {}
    image_file = request.files.get("image") if is_multipart else None
    try:
        event = event_service.create(
            data,
            image_file=image_file,
            static_folder=current_app.static_folder,
        )
        return jsonify({
            "message": "Événement créé avec succès",
            "event": event.to_dict(),
        }), 201
    except EventServiceError as error:
        return event_error_response(error)
    except Exception:
        return jsonify({"error": "Erreur interne du serveur"}), 500


@events.route("/<event_id>", methods=["PUT"])
@admin_required({"competences", "startups", "super_admin"})
def update_event(event_id):
    try:
        event_service.update(event_id, request.get_json() or {})
        return jsonify({"message": "Événement mis à jour"}), 200
    except EventServiceError as error:
        return event_error_response(error)


@events.route("/<event_id>", methods=["DELETE"])
@admin_required({"competences", "startups", "super_admin"})
def delete_event(event_id):
    try:
        event_service.delete(event_id)
        return jsonify({"message": "Événement supprimé"}), 200
    except EventServiceError as error:
        return event_error_response(error)


@events.route("/<event_id>/register", methods=["POST"])
def register_to_event(event_id):
    try:
        registration = event_service.register(
            event_id,
            request.get_json() or {},
        )
        if not registration:
            return jsonify({"message": "Déjà inscrit"}), 200
        return jsonify({
            "message": "Inscription réussie",
            "registration_id": str(registration.id),
        }), 201
    except EventServiceError as error:
        return event_error_response(error)


@events.route("/<event_id>/registrations", methods=["GET"])
@events.route("api/<event_id>/registrations", methods=["GET"])
@admin_required({"competences", "startups", "super_admin"})
def get_event_registrations(event_id):
    return jsonify({
        "registrations": event_service.list_registrations(event_id),
    }), 200


@events.route("/newsletter/subscribe", methods=["POST"])
def subscribe_to_newsletter():
    try:
        created = event_service.subscribe(
            (request.get_json() or {}).get("email"),
        )
        return jsonify({
            "message": (
                "Inscrit à la newsletter"
                if created
                else "Déjà inscrit"
            ),
        }), 201 if created else 200
    except EventServiceError as error:
        return event_error_response(error)


@events.route("/newsletter/unsubscribe", methods=["POST"])
def unsubscribe_from_newsletter():
    try:
        removed = event_service.unsubscribe(
            (request.get_json() or {}).get("email"),
        )
        return jsonify({
            "message": (
                "Désabonnement réussi"
                if removed
                else "Email non trouvé"
            ),
        }), 200 if removed else 404
    except EventServiceError as error:
        return event_error_response(error)
