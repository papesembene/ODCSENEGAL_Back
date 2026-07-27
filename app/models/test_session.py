from datetime import datetime

from mongoengine import DateTimeField, DictField, Document, IntField, StringField


class TestSession(Document):
    """Brouillon léger de session candidat pour reprise en cas d'incident."""

    testId = StringField(required=True)
    candidateEmail = StringField(required=True)
    candidatePhone = StringField(required=True)
    candidateName = StringField()
    answers = DictField(default=dict)
    lastQuestion = IntField(default=0)
    remainingTime = IntField(default=0)
    status = StringField(
        choices=["in_progress", "submitted", "expired"],
        default="in_progress",
    )
    startedAt = DateTimeField(default=datetime.utcnow)
    lastSeenAt = DateTimeField(default=datetime.utcnow)
    submittedAt = DateTimeField()

    meta = {
        "collection": "test_sessions",
        "indexes": [
            {"fields": ["testId", "candidateEmail"], "unique": True},
            {"fields": ["testId", "status"]},
            {"fields": ["candidateEmail", "-lastSeenAt"]},
            {"fields": ["status", "-lastSeenAt"]},
        ],
    }

    def to_dict(self):
        return {
            "id": str(self.id),
            "testId": self.testId,
            "candidateEmail": self.candidateEmail,
            "candidatePhone": self.candidatePhone,
            "candidateName": self.candidateName,
            "answers": self.answers or {},
            "lastQuestion": self.lastQuestion or 0,
            "remainingTime": self.remainingTime or 0,
            "status": self.status,
            "startedAt": self.startedAt.isoformat() if self.startedAt else None,
            "lastSeenAt": self.lastSeenAt.isoformat() if self.lastSeenAt else None,
            "submittedAt": self.submittedAt.isoformat() if self.submittedAt else None,
        }
