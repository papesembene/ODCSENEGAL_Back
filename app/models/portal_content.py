from datetime import datetime

from app import db


class PortalContent(db.Document):
    CONTENT_TYPES = ("banner", "news", "info")
    STATUSES = ("draft", "published", "archived")

    type = db.StringField(required=True, choices=CONTENT_TYPES)
    slot_key = db.StringField(default="")
    title = db.StringField(required=True, max_length=180)
    summary = db.StringField(default="", max_length=280)
    body = db.StringField(default="")
    category = db.StringField(default="", max_length=80)
    image_url = db.StringField(default="")
    link_label = db.StringField(default="")
    link_url = db.StringField(default="")
    placement = db.StringField(default="home")
    priority = db.IntField(default=0)
    is_pinned = db.BooleanField(default=False)
    status = db.StringField(default="draft", choices=STATUSES)
    starts_at = db.DateTimeField()
    ends_at = db.DateTimeField()
    created_by = db.StringField(default="")
    updated_by = db.StringField(default="")
    created_at = db.DateTimeField(default=datetime.utcnow)
    updated_at = db.DateTimeField(default=datetime.utcnow)

    meta = {
        "collection": "portal_contents",
        "indexes": [
            "type",
            "status",
            "placement",
            "slot_key",
            "-priority",
            "-created_at",
            {
                "fields": (
                    "status",
                    "type",
                    "placement",
                    "-priority",
                    "-created_at",
                )
            },
        ],
    }

    def to_dict(self):
        return {
            "id": str(self.id),
            "type": self.type,
            "slotKey": self.slot_key,
            "title": self.title,
            "summary": self.summary,
            "body": self.body,
            "category": self.category,
            "imageUrl": self.image_url,
            "linkLabel": self.link_label,
            "linkUrl": self.link_url,
            "placement": self.placement,
            "priority": self.priority,
            "isPinned": self.is_pinned,
            "status": self.status,
            "startsAt": self.starts_at.isoformat() if self.starts_at else None,
            "endsAt": self.ends_at.isoformat() if self.ends_at else None,
            "createdBy": self.created_by,
            "updatedBy": self.updated_by,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
            "updatedAt": self.updated_at.isoformat() if self.updated_at else None,
        }
