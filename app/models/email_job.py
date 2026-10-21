"""Durable email outbox. Credentials and API keys are never stored here."""

from datetime import datetime
from mongoengine import DateTimeField, DictField, Document, IntField, StringField


class EmailJob(Document):
    dedup_key = StringField(required=True, unique=True)
    batch_key = StringField(required=True)
    kind = StringField(default="test_invitation", choices=["test_invitation", "test_result"])
    group_id = StringField(default="")
    candidate_id = StringField(required=True)
    payload = DictField(default=dict)
    status = StringField(default="pending", choices=["pending", "sending", "sent", "failed", "cancelled"])
    attempts = IntField(default=0)
    next_attempt_at = DateTimeField(default=datetime.utcnow)
    locked_until = DateTimeField()
    lock_token = StringField()
    last_error = StringField()
    created_at = DateTimeField(default=datetime.utcnow)
    sent_at = DateTimeField()

    meta = {"collection": "email_jobs", "indexes": [
        ["status", "next_attempt_at"], ["status", "locked_until"],
        ["group_id", "batch_key", "status"],
        ["kind", "batch_key", "status"],
    ]}
