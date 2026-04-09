from datetime import datetime
from bson.objectid import ObjectId
from app import db
import json

class Event(db.Document):
    title = db.StringField(required=True)
    description = db.StringField(default="")
    category = db.StringField(default="")
    date = db.DateTimeField(required=True)
    time = db.StringField(required=True)  # Changed to required
    location = db.StringField(required=True)
    agenda = db.StringField(default="")
    speakers = db.ListField(db.DictField())  # Changed to DictField for objects
    details = db.StringField(default="")
    image = db.StringField(default="/images/event-default.jpg")
    created_at = db.DateTimeField(default=datetime.utcnow)
    updated_at = db.DateTimeField(default=datetime.utcnow)
    
    def to_dict(self):
        return {
            "id": str(self.id),
            "title": self.title,
            "description": self.description,
            "category": self.category,
            "date": self.date.isoformat() if self.date else None,
            "time": self.time,
            "location": self.location,
            "agenda": self.agenda,
            "speakers": self.speakers,
            "details": self.details,
            "image": self.image,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "registration_count": Registration.objects(event_id=self).count(),
        }

    @classmethod
    def create_event(cls, event_data):
        """Crée un nouvel événement"""
        # Convert agenda if it's a list
        if 'agenda' in event_data and isinstance(event_data['agenda'], list):
            event_data['agenda'] = '\n'.join([str(item).strip() for item in event_data['agenda']])
        
        # Ensure speakers is a list of dicts
        if 'speakers' not in event_data:
            event_data['speakers'] = []
        elif isinstance(event_data['speakers'], str):
            try:
                # Corrige les simples quotes et parse la string en liste de dictionnaires
                event_data['speakers'] = json.loads(event_data['speakers'].replace("'", '"'))
            except Exception as e:
                print(f"Erreur lors du parsing des speakers: {e}")
                event_data['speakers'] = []
        elif isinstance(event_data['speakers'], list):
            # Ensure each speaker is a dict
            event_data['speakers'] = [
                s if isinstance(s, dict) else {'name': str(s).strip()}
                for s in event_data['speakers']
            ]
        
        # Remove attendees if it exists since not in model
        event_data.pop('attendees', None)
        
        event = cls(**event_data)
        event.save()
        return event  # Return the full event object now


    @staticmethod
    def get_all_events():
        return Event.objects.order_by('date')

    @staticmethod
    def get_upcoming_events():
        now = datetime.utcnow()
        return Event.objects(date__gte=now).order_by('date')

    @staticmethod
    def get_past_events():
        now = datetime.utcnow()
        return Event.objects(date__lt=now).order_by('-date')

    @staticmethod
    def get_event_by_id(event_id):
        return Event.objects(id=event_id).first()

    @staticmethod
    def update_event(event_id, update_data):
        event = Event.objects(id=event_id).first()
        if event:
            for key, value in update_data.items():
                setattr(event, key, value)
            event.updated_at = datetime.utcnow()
            event.save()
        return event

    @staticmethod
    def delete_event(event_id):
        event = Event.objects(id=event_id).first()
        if event:
            event.delete()
            return True
        return False

    @staticmethod
    def search_events(query):
        return Event.objects(__raw__={
            "$or": [
                {"title": {"$regex": query, "$options": "i"}},
                {"description": {"$regex": query, "$options": "i"}},
                {"category": {"$regex": query, "$options": "i"}},
            ]
        }).order_by('date')


class Registration(db.Document):
    event_id = db.ReferenceField(Event, required=True)
    email = db.StringField(required=True)
    name = db.StringField()
    registered_at = db.DateTimeField(default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": str(self.id),
            "event_id": str(self.event_id.id) if self.event_id else None,
            "email": self.email,
            "name": self.name,
            "registered_at": self.registered_at.isoformat(),
        }

    @staticmethod
    def create_registration(data):
        registration = Registration(**data)
        registration.save()
        return registration

    @staticmethod
    def get_registrations_for_event(event_id):
        return Registration.objects(event_id=event_id).order_by('-registered_at')

    @staticmethod
    def get_user_registrations(user_email):
        return Registration.objects(email=user_email).order_by('-registered_at')

    @staticmethod
    def check_registration(event_id, user_email):
        return Registration.objects(event_id=event_id, email=user_email).first()


class Newsletter(db.Document):
    email = db.StringField(required=True, unique=True)
    subscribed_at = db.DateTimeField(default=datetime.utcnow)
    active = db.BooleanField(default=True)

    def to_dict(self):
        return {
            "email": self.email,
            "subscribed_at": self.subscribed_at.isoformat(),
            "active": self.active,
        }

    @staticmethod
    def subscribe(email):
        existing = Newsletter.objects(email=email).first()
        if existing:
            return False  # Déjà inscrit
        Newsletter(email=email).save()
        return True

    @staticmethod
    def unsubscribe(email):
        newsletter = Newsletter.objects(email=email).first()
        if newsletter:
            newsletter.active = False
            newsletter.save()
            return True
        return False
