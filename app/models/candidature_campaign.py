from datetime import datetime

from app import db


class CandidatureCampaign(db.Document):
    STATUSES = ("draft", "published", "archived")

    title = db.StringField(required=True)
    promotion = db.StringField()
    formation = db.StringField(default="all")
    start_at = db.DateTimeField(required=True)
    end_at = db.DateTimeField(required=True)
    status = db.StringField(choices=STATUSES, default="draft")
    description = db.StringField()
    created_by = db.StringField()
    updated_by = db.StringField()
    created_at = db.DateTimeField(default=datetime.utcnow)
    updated_at = db.DateTimeField(default=datetime.utcnow)

    meta = {
        "collection": "candidature_campaigns",
        "indexes": [
            "formation",
            "status",
            "start_at",
            "end_at",
            {"fields": ["formation", "status", "start_at", "end_at"]},
        ],
    }

    def lifecycle_status(self, now=None):
        now = now or datetime.utcnow()
        if self.status != "published":
            return "inactive"
        if self.start_at > now:
            return "upcoming"
        if self.end_at < now:
            return "closed"
        return "open"

    def to_dict(self, now=None):
        lifecycle_status = self.lifecycle_status(now)
        return {
            "id": str(self.id),
            "title": self.title,
            "promotion": self.promotion or "",
            "formation": self.formation or "all",
            "startAt": self.start_at.isoformat() if self.start_at else None,
            "endAt": self.end_at.isoformat() if self.end_at else None,
            "status": self.status,
            "lifecycleStatus": lifecycle_status,
            "isOpen": lifecycle_status == "open",
            "description": self.description or "",
            "createdBy": self.created_by or "",
            "updatedBy": self.updated_by or "",
            "createdAt": self.created_at.isoformat() if self.created_at else None,
            "updatedAt": self.updated_at.isoformat() if self.updated_at else None,
        }
