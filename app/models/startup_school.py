from mongoengine import Document, StringField, DateTimeField
import datetime

class StartupSchool(Document):
    name = StringField(required=True, unique=True)
    description = StringField()
    start_date = DateTimeField()
    end_date = DateTimeField()
    created_at = DateTimeField(default=datetime.datetime.utcnow)

    def to_dict(self):
        return {
            "id": str(self.id),
            "name": self.name,
            "description": self.description,
            "start_date": self.start_date.isoformat() if self.start_date else None,
            "end_date": self.end_date.isoformat() if self.end_date else None,
            "created_at": self.created_at.isoformat()
        }
