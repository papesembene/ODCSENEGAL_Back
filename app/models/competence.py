from mongoengine import Document, StringField, DateTimeField
import datetime

class Competence(Document):
    name = StringField(required=True)
    description = StringField()
    level = StringField()  # Exemple : "Beginner", "Intermediate", "Advanced"
    created_at = DateTimeField(default=datetime.datetime.utcnow)

    def to_dict(self):
        return {
            "id": str(self.id),
            "name": self.name,
            "description": self.description,
            "level": self.level,
            "created_at": self.created_at.isoformat()
        }
