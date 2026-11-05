"""Stable sites: archiving never removes a candidate's historical choice."""

from datetime import datetime

from app.database import db


class TrainingSite(db.Document):
    code = db.StringField(primary_key=True, max_length=80)
    data = db.DictField(required=True)
    alias_tokens = db.ListField(db.StringField(), default=list)
    version = db.IntField(default=1, min_value=1)
    updated_at = db.DateTimeField(default=datetime.utcnow)
    updated_by = db.StringField(default="")
    meta = {"collection": "training_sites", "indexes": [{"fields": ["alias_tokens"], "unique": True}]}

    def to_dict(self):
        return {**self.data, "id": self.code, "code": self.code,
                "version": self.version, "updatedAt": self.updated_at.isoformat()}
