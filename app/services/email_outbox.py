"""Shared atomic delivery and retry policy for durable email jobs."""

from datetime import datetime, timedelta
from uuid import uuid4

from pymongo.errors import BulkWriteError

from app.models.email_job import EmailJob
from app.runtime_config import env_int
from app.services.email_transport import EmailTransport


class EmailOutbox:
    def __init__(self, transport=None, now=None):
        self.transport = transport or EmailTransport()
        self.now = now or datetime.utcnow
        self.max_attempts = env_int("EMAIL_MAX_ATTEMPTS", 5, maximum=10)

    @staticmethod
    def _insert_jobs(collection, operations):
        try:
            collection.bulk_write(operations, ordered=False)
        except BulkWriteError as error:
            details = error.details
            if details.get("writeConcernErrors") or not details.get("writeErrors") or any(
                item["code"] != 11000 for item in details["writeErrors"]
            ):
                raise

    @staticmethod
    def summarize(query):
        counts = dict.fromkeys(("pending", "sending", "sent", "failed", "cancelled"), 0)
        for row in query.aggregate([{"$group": {"_id": "$status", "count": {"$sum": 1}}}]):
            counts[row["_id"]] = row["count"]
        return {**counts, "queued": counts["pending"] + counts["sending"], "total": sum(counts.values())}

    def requeue(self, query):
        if not self.transport.is_configured:
            raise ValueError("Service email non configure")
        query.filter(status="failed").update(
            set__status="pending", set__attempts=0, set__next_attempt_at=self.now(), unset__last_error=1,
        )

    def run_once(self):
        from app.services.invitation_queue import InvitationQueue
        from app.services.result_notification_service import ResultNotificationService

        now = self.now()
        EmailJob.objects(status="sending", locked_until__lte=now, attempts__gte=self.max_attempts).update(
            set__status="failed", set__last_error="Worker interrompu pendant le dernier essai",
        )
        token = uuid4().hex
        job = EmailJob.objects(attempts__lt=self.max_attempts, __raw__={"$or": [
            {"status": "pending", "next_attempt_at": {"$lte": now}},
            {"status": "sending", "locked_until": {"$lte": now}},
        ]}).order_by("next_attempt_at").modify(
            new=True, set__status="sending", set__lock_token=token,
            set__locked_until=now + timedelta(minutes=2), inc__attempts=1,
        )
        if not job:
            return False
        handler = ResultNotificationService if job.kind == "test_result" else InvitationQueue
        try:
            message = handler.prepare(job, now)
            if message is None:
                EmailJob.objects(id=job.id, lock_token=token).update_one(set__status="cancelled", unset__payload=1)
                return True
            result = self.transport.send_html(*message)
        except Exception:
            result = {"sent": False, "retryable": True, "message": "Erreur temporaire du worker"}
        if result["sent"]:
            updated = EmailJob.objects(id=job.id, lock_token=token).update_one(
                set__status="sent", set__sent_at=self.now(), unset__payload=1,
            )
            if updated:
                handler.on_accepted(job, self.now())
        else:
            retry = result.get("retryable", False) and job.attempts < self.max_attempts
            EmailJob.objects(id=job.id, lock_token=token).update_one(
                set__status="pending" if retry else "failed",
                set__next_attempt_at=self.now() + timedelta(seconds=min(30 * 2 ** (job.attempts - 1), 3600)),
                set__last_error=result.get("message", "Erreur email")[:300],
            )
        return True
