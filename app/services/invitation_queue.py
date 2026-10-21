"""Bounded invitation enqueueing, atomic claims and retryable delivery."""

from datetime import timedelta
from hashlib import sha256
import json

from bson import ObjectId
from pymongo import UpdateOne

from app.models.candidature import Candidature
from app.models.email_job import EmailJob
from app.models.test_group import TestGroup
from app.services.email_outbox import EmailOutbox
from app.services.email_templates.test_invitation import build_test_invitation_html


class InvitationQueue(EmailOutbox):
    @staticmethod
    def batch_key(group, test, frontend_url):
        signature = json.dumps({
            "test": str(test.id), "title": test.title,
            "date": group.test_date.isoformat(), "duration": group.duration,
            "url": frontend_url.rstrip("/"),
        }, sort_keys=True)
        return f"{group.id}:{sha256(signature.encode()).hexdigest()}"

    def enqueue(self, group, test, frontend_url):
        if group.status in {"cancelled", "completed"}:
            raise ValueError("Ce groupe ne peut plus recevoir d'invitations")
        key = self.batch_key(group, test, frontend_url)
        now = self.now()
        collection = EmailJob._get_collection()
        TestGroup.objects(id=group.id).update_one(set__invitation_batch_key=key)
        group.invitation_batch_key = key
        operations = []
        count = 0
        candidates = Candidature.objects(id__in=group.candidate_ids).only(
            "id", "email", "first_name", "last_name", "phone", "gender",
        ).no_cache().batch_size(500)
        for candidate in candidates:
            payload = {
                "candidate_email": candidate.email,
                "candidate_name": f"{candidate.first_name} {candidate.last_name}",
                "candidate_phone": candidate.phone, "candidate_gender": candidate.gender,
                "test_title": test.title, "test_date": group.test_date.strftime("%d/%m/%Y"),
                "test_time": group.test_date.strftime("%H:%M"), "test_duration": group.duration,
                "test_link": f"{frontend_url.rstrip('/')}/test/{test.id}",
            }
            dedup = sha256(f"{key}:{candidate.id}:{candidate.email}".encode()).hexdigest()
            operations.append(UpdateOne({"dedup_key": dedup}, {"$setOnInsert": {
                "_id": ObjectId(), "dedup_key": dedup, "batch_key": key,
                "group_id": str(group.id), "candidate_id": str(candidate.id),
                "payload": payload, "status": "pending", "attempts": 0,
                "created_at": now, "next_attempt_at": now,
            }}, upsert=True))
            count += 1
            if len(operations) == 500:
                self._insert_jobs(collection, operations)
                operations = []
        if operations:
            self._insert_jobs(collection, operations)
        if not count:
            raise ValueError("Aucun candidat trouve dans ce groupe")
        return self.summary(group)

    @staticmethod
    def summary(group):
        key = getattr(group, "invitation_batch_key", None)
        return EmailOutbox.summarize(EmailJob.objects(group_id=str(group.id), batch_key=key or ""))

    def retry_failed(self, group):
        if group.status in {"cancelled", "completed"}:
            raise ValueError("Ce groupe ne peut plus recevoir d'invitations")
        if not self.transport.is_configured:
            raise ValueError("Service email non configure")
        if group.invitation_batch_key:
            self.requeue(EmailJob.objects(group_id=str(group.id), batch_key=group.invitation_batch_key))
        return self.summary(group)

    @staticmethod
    def prepare(job, now):
        group = TestGroup.objects(id=job.group_id).first()
        valid = group and group.status not in {"cancelled", "completed"} and group.invitation_batch_key == job.batch_key
        valid = valid and job.candidate_id in group.candidate_ids
        valid = valid and now < group.test_date + timedelta(minutes=group.duration)
        if not valid:
            return None
        return ([job.payload["candidate_email"]], f"Invitation au test - {job.payload['test_title']}",
                build_test_invitation_html(**job.payload))

    @staticmethod
    def on_accepted(job, now):
        TestGroup.objects(id=job.group_id, invitation_batch_key=job.batch_key, status__in=["pending", "scheduled"]).update_one(
            set__email_sent=now, set__status="scheduled",
        )
