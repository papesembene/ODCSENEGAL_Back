from app import db
from datetime import datetime

class ResourceRequest(db.Document):
    startup_name = db.StringField(required=True)
    contact_person = db.StringField(required=True)
    email = db.StringField(required=True)
    phone = db.StringField(required=True)
    resource = db.StringField(required=True)
    requested_date = db.StringField(required=True)
    requested_time = db.StringField()
    details = db.StringField(required=True)
    accept_terms = db.BooleanField(required=True)
    created_at = db.DateTimeField(default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": str(self.id),
            "startup_name": self.startup_name,
            "contact_person": self.contact_person,
            "email": self.email,
            "phone": self.phone,
            "resource": self.resource,
            "requested_date": self.requested_date,
            "requested_time": self.requested_time,
            "details": self.details,
            "accept_terms": self.accept_terms,
            "created_at": self.created_at.isoformat(),
        }
