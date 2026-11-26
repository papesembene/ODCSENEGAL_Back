from datetime import datetime

from mongoengine import DateField, DateTimeField, DictField, Document, IntField, ListField, StringField


BOOTCAMP_STATUSES = ("draft", "launched", "submitted")
FINAL_DECISIONS = ("pending", "retained", "waiting_list", "rejected")


class Bootcamp(Document):
    """A Bootcamp of one referential and one candidature campaign, fed by the validated interview pre-selection."""

    title = StringField(required=True, max_length=150)
    formation = StringField(required=True)
    candidature_campaign_id = StringField(required=True)
    interview_campaign_id = StringField(required=True)
    coach_ids = ListField(StringField(), default=list)
    start_date = DateField(required=True)
    end_date = DateField(required=True)
    location = StringField(max_length=200, default="")
    description = StringField(max_length=3000, default="")
    capacity = IntField(min_value=1)
    status = StringField(choices=BOOTCAMP_STATUSES, default="draft")
    launched_at = DateTimeField()
    launched_by = DictField(default=dict)
    submitted_at = DateTimeField()
    submitted_by = DictField(default=dict)
    revision = IntField(default=0)
    created_at = DateTimeField(default=datetime.utcnow)
    updated_at = DateTimeField(default=datetime.utcnow)

    meta = {
        "collection": "bootcamps",
        "indexes": [
            {"fields": ["formation", "candidature_campaign_id", "start_date"]},
            "coach_ids",
            "interview_campaign_id",
        ],
    }


class BootcampParticipant(Document):
    """One pre-selected candidate in one Bootcamp; the unique index forbids two Bootcamps of the same campaign."""

    bootcamp_id = StringField(required=True)
    candidature_campaign_id = StringField(required=True)
    formation = StringField(required=True)
    candidate_id = StringField(required=True)
    coach_comment = StringField(max_length=3000, default="")
    decision = StringField(choices=FINAL_DECISIONS, default="pending")
    decided_at = DateTimeField()
    decided_by = DictField(default=dict)
    created_at = DateTimeField(default=datetime.utcnow)

    meta = {
        "collection": "bootcamp_participants",
        "indexes": [
            {"fields": ["candidature_campaign_id", "formation", "candidate_id"], "unique": True},
            {"fields": ["bootcamp_id", "decision"]},
        ],
    }
