"""Event, registration and newsletter use cases."""

from datetime import datetime
import os

from mongoengine.errors import ValidationError

from app.models.event import Event, Newsletter, Registration


class EventServiceError(Exception):
    def __init__(self, message, status_code=400):
        super().__init__(message)
        self.status_code = status_code


class EventService:
    WRITABLE_FIELDS = {
        "title",
        "description",
        "category",
        "date",
        "time",
        "location",
        "max_participants",
        "agenda",
        "speakers",
        "details",
        "image",
    }

    @staticmethod
    def list_all():
        return [event.to_dict() for event in Event.get_all_events()]

    @staticmethod
    def list_documents():
        return Event.get_all_events()

    @staticmethod
    def list_upcoming():
        return [event.to_dict() for event in Event.get_upcoming_events()]

    @staticmethod
    def list_past():
        return [event.to_dict() for event in Event.get_past_events()]

    @staticmethod
    def get(event_id):
        event = Event.get_event_by_id(event_id)
        if not event:
            raise EventServiceError("Événement non trouvé", 404)
        return event

    def create(self, data, image_file=None, static_folder=None):
        data = self._normalize_payload(data)
        if image_file:
            data["image"] = self._save_image(
                image_file,
                static_folder,
            )
        else:
            data.setdefault("image", "/static/images/event-default.jpg")
        for field in ("title", "date", "time", "location"):
            if not data.get(field):
                raise EventServiceError(
                    f"Le champ {field} est requis",
                )
        data["date"] = self._parse_date(data["date"])
        data.setdefault("description", "")
        data.setdefault("category", "")
        data.setdefault("agenda", [])
        data.setdefault("speakers", [])
        data.setdefault("details", "")
        try:
            return Event.create_event(data)
        except ValidationError as error:
            raise EventServiceError(
                f"Erreur de validation: {error}",
            ) from error

    @staticmethod
    def update(event_id, data):
        if not data:
            raise EventServiceError("Données de mise à jour requises")
        values = EventService._normalize_payload(data)
        values.pop("id", None)
        if "date" in values:
            values["date"] = EventService._parse_date(values["date"])
        event = Event.update_event(event_id, values)
        if not event:
            raise EventServiceError(
                "Événement non trouvé ou aucune modification",
                404,
            )
        return event

    @staticmethod
    def delete(event_id):
        if not Event.delete_event(event_id):
            raise EventServiceError("Événement non trouvé", 404)

    def register(self, event_id, data):
        data = data or {}
        if any(not data.get(field) for field in ("name", "email", "phone")):
            raise EventServiceError("Nom, email et téléphone requis")
        event = self.get(event_id)
        if Registration.check_registration(event_id, data["email"]):
            return None
        return Registration.create_registration({
            "event_id": event,
            "email": data["email"],
            "name": data["name"],
            "phone": data["phone"],
        })

    @staticmethod
    def list_registrations(event_id):
        return [
            registration.to_dict()
            for registration in Registration.get_registrations_for_event(
                event_id,
            )
        ]

    @staticmethod
    def subscribe(email):
        if not email:
            raise EventServiceError("Email requis")
        return Newsletter.subscribe(email)

    @staticmethod
    def unsubscribe(email):
        if not email:
            raise EventServiceError("Email requis")
        return Newsletter.unsubscribe(email)

    @staticmethod
    def _parse_date(raw_date):
        if not isinstance(raw_date, str):
            raise EventServiceError(
                "Le champ date doit être une chaîne ISO",
            )
        try:
            normalized = (
                raw_date[:-1] + "+00:00"
                if raw_date.endswith("Z")
                else raw_date
            )
            return datetime.fromisoformat(normalized)
        except ValueError as error:
            raise EventServiceError(
                f"Format de date invalide: {error}",
            ) from error

    @staticmethod
    def _save_image(image_file, static_folder):
        if not image_file:
            return "/static/images/event-default.jpg"
        upload_folder = os.path.join(static_folder, "uploads")
        os.makedirs(upload_folder, exist_ok=True)
        filename = image_file.filename
        image_file.save(os.path.join(upload_folder, filename))
        return f"/static/uploads/{filename}"

    @classmethod
    def _normalize_payload(cls, data):
        values = dict(data or {})
        if "maxParticipants" in values:
            try:
                values["max_participants"] = int(
                    values.pop("maxParticipants")
                )
            except (TypeError, ValueError) as error:
                raise EventServiceError(
                    "La capacité doit être un nombre entier positif"
                ) from error
        return {
            field: value
            for field, value in values.items()
            if field in cls.WRITABLE_FIELDS or field == "id"
        }
