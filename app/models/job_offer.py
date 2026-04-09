from mongoengine import Document, StringField, DateTimeField, BooleanField
import datetime

class JobOffer(Document):
    title = StringField(required=True)
    description = StringField()
    company_name = StringField()
    location = StringField()
    is_active = BooleanField(default=True)  # Pour savoir si l'offre est encore active
    created_at = DateTimeField(default=datetime.datetime.utcnow)

    def to_dict(self):
        return {
            "id": str(self.id),
            "title": self.title,
            "description": self.description,
            "company_name": self.company_name,
            "location": self.location,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat()
        }
